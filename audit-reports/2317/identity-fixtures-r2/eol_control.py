"""只改变投影仓库根的检出属性，验证保留磁盘原字节与普通 CRLF 客户端能同时成立。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import A, B, SPEC, box, commit, compact, gate, git, summary

if __name__ == "__main__":
    d = box()
    repo = compact(d)
    attrs = repo / ".gitattributes"
    with attrs.open("a") as f:
        f.write(f"\n{A}/** -text\n{B}/** -text\n")
    git(repo, "add", "--", ".gitattributes")
    commit(repo)
    dst = d / "ordinary-crlf"
    git(d, "clone", "-q", "--shared", "-c", "core.autocrlf=true", repo, dst)
    assert not git(dst, "status", "--porcelain")
    print(git(dst, "ls-files", "--eol", "--", SPEC).decode().strip())
    r = gate(dst)
    summary("CRLF 客户端、两棵数据树原样检出", r)
    assert r.returncode == 0
