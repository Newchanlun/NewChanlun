"""正向兼容性测试：只设置钉选文本的检出行尾；提交和两个数据目录应仍相符。"""
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_repo import A, B, CHECK, G, REV, first, gate, git, tmp_parent

temp = Path(tempfile.mkdtemp(dir=tmp_parent()))
origin, checkout = temp/"source", temp/"checkout"
git(temp, "clone", "-q", "--shared", "--no-checkout", str(Path.cwd()), str(origin))
git(origin, "checkout", "-q", "--detach", REV)
pin = G+"/admit_identity.pin"
attrs = origin/".gitattributes"
with attrs.open("a") as f:
    f.write("\n"+pin+" text eol=crlf\n")
git(origin, "add", "--", ".gitattributes")
git(origin, "commit", "-qm", "规定文本钉选在检出时使用 CRLF")
git(temp, "clone", "-q", "--shared", str(origin), str(checkout))
assert git(checkout, "diff", "--name-only", REV, "HEAD").decode().strip() == ".gitattributes"
assert git(checkout, "status", "--porcelain") == b""
print("提交差异仅 .gitattributes；干净克隆；", git(checkout, "ls-files", "--eol", pin).decode().strip())
raw = git(checkout, "show", "HEAD:"+pin)
assert (checkout/pin).read_bytes() == raw.replace(b"\n", b"\r\n")
for name in git(checkout, "ls-tree", "-rz", "--name-only", "HEAD", "--", A, B).split(b"\0"):
    if name:
        p = name.decode()
        assert (checkout/p).read_bytes() == git(checkout, "show", "HEAD:"+p)
p = gate(checkout/CHECK, checkout)
print("预期 0；实际", p.returncode, first(p))
q = gate(checkout/CHECK, checkout, "--no-worktree")
print("只核提交预期 0；实际", q.returncode, first(q))
sys.exit(int(p.returncode != 0 or q.returncode != 0))
