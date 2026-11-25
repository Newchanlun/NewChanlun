"""Git 对象表的拒收对照：名字按原始字节进入对象，不依赖当前卷能否检出。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_repo import A, B, CHECK, first, gate, git, run, seed, tmp_parent

tmp = Path(tempfile.mkdtemp(dir=tmp_parent()))
repo = tmp/"repo"
seed(Path.cwd(), repo)
base = git(repo, "rev-parse", "HEAD").strip()
blob = git(repo, "rev-parse", "HEAD:"+A+"/SPEC.md").strip()
git(repo, "config", "core.ignoreCase", "false")
git(repo, "config", "core.precomposeUnicode", "false")
script = repo/CHECK


def object_case(label, code, reason):
    tree = git(repo, "write-tree").strip()
    rev = git(repo, "commit-tree", tree, "-p", base, "-m", label).decode().strip()
    p = gate(script, repo, "--no-worktree", "--rev", rev)
    msg = first(p)
    print(label, p.returncode, msg, flush=True)
    assert p.returncode == code and reason in msg
    git(repo, "read-tree", base)


def add(name, mode=b"100644", oid=blob):
    git(repo, "update-index", "--add", "--cacheinfo", mode, oid, name)


admit = A.encode()+b"/"
for name in (b"has space", b"has'quote\"", b"has\nline", b"non-utf8-\xff"):
    add(admit+name)
    object_case(repr(name), 1, "路径含换行" if b"\n" in name else "与钉选")
add(admit+b"spec.MD")
object_case("同存 SPEC.md 和 spec.MD", 1, "与钉选")
for s in ("é.md", "e\u0301.md"):
    add(admit+s.encode())
object_case("同存 NFC 和 NFD", 1, "与钉选")
add(admit+b"module", b"160000", base)
object_case("可读的 gitlink 目标", 1, "非普通文件")
external = b"1234567890abcdef1234567890abcdef12345678"
assert run(repo, "git", "cat-file", "-e", external, check=False).returncode != 0
add(admit+b"module", b"160000", external)
object_case("不在本库的 gitlink 目标", 2, "无法运行")

name = git(repo, "ls-tree", "-rz", "--name-only", "HEAD", "--", B).split(b"\0")[0]
git(repo, "update-index", "--force-remove", "--", name)
object_case("语料少一份", 1, "语料指纹")
ptr = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"0"*64 + b"\nsize 42\n"
pointer = git(repo, "hash-object", "-w", "--stdin", data=ptr).strip()
add(admit+b"SPEC.md", oid=pointer)
object_case("表项换成 LFS 指针 blob", 1, "与钉选")

for is_link in (False, True):
    c = tmp/("link" if is_link else "plain")
    git(tmp, "clone", "-q", "--shared", str(repo), str(c))
    (c/A).rename(c/"materials")
    if is_link:
        os.symlink(os.path.relpath(c/"materials", (c/A).parent), c/A)
    else:
        (c/A).write_text("placeholder\n")
    git(c, "add", "-A", "--", A)
    git(c, "commit", "-qm", "改变数据根目录的类型")
    p = gate(script, c)
    print("已提交数据根", "符号链接" if is_link else "普通文件", p.returncode, first(p), flush=True)
    assert p.returncode == 1 and "与钉选" in first(p)
