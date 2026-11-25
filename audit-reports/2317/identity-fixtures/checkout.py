"""把普通检出转换与对象变化分开；记录当前卷的文件名行为。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_repo import A, CHECK, first, gate, git, run, seed, tmp_parent

tmp = Path(tempfile.mkdtemp(dir=tmp_parent()))
source = tmp/"source"
seed(Path.cwd(), source)
(tmp/"CaseTest").touch()
(tmp/"é").touch()
print("同一文件", "CaseTest/casetest", (tmp/"casetest").exists(),
      "NFC/NFD", (tmp/"e\u0301").exists())

for label in ("autocrlf", "filter"):
    root = tmp/label
    git(tmp, "clone", "-q", "--shared", str(source), str(root))
    if label == "autocrlf":
        git(root, "config", "core.autocrlf", "true")
        chosen = root/A/"SPEC.md"
        chosen.unlink()
        git(root, "checkout", "--", A+"/SPEC.md")
        assert b"\r\n" in chosen.read_bytes()
    else:
        # 两个固定命令只为检出的示例文本加前缀、入库时去前缀；不调用外部 LFS。
        git(root, "config", "filter.review.clean", "sed 's/^review: //'")
        git(root, "config", "filter.review.smudge", "sed 's/^/review: /'")
        (root/".gitattributes").write_text(A+"/SPEC.md filter=review\n")
        git(root, "add", "--", ".gitattributes")
        git(root, "commit", "-qm", "检出转换")
        (root/A/"SPEC.md").unlink()
        git(root, "checkout", "--", A+"/SPEC.md")
        assert (root/A/"SPEC.md").read_bytes().startswith(b"review: ")
    assert git(root, "status", "--porcelain") == b""
    p = gate(source/CHECK, root)
    q = gate(source/CHECK, root, "--no-worktree")
    print(label, "git status 干净", "默认", p.returncode, first(p), "只核对象", q.returncode, first(q))
    assert p.returncode == 1 and "工作区内容与提交不同" in first(p) and q.returncode == 0

root = tmp/"newline\n"
git(tmp, "clone", "-q", "--shared", str(source), str(root))
q = run(root, sys.executable, "-I", CHECK, check=False)
r = gate(source/CHECK, root)
print("仓库目录名尾随换行；自动定位", q.returncode, "显式 --root", r.returncode)
assert q.returncode == 2 and r.returncode == 0
