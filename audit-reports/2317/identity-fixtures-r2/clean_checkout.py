"""两个完整、无改码的分离检出：检查 Git 模式及常见行尾设置。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BASE, SPEC, box, clone, gate, git, summary

def inspect(c, label):
    assert git(c, "rev-parse", "HEAD").decode().strip() == BASE
    status = git(c, "status", "--porcelain")
    dirty = git(c, "diff-files", "--raw", "--", SPEC)
    same = (c / SPEC).read_bytes() == git(c, "cat-file", "blob", "HEAD:" + SPEC)
    print(f"{label}: status={status!r} diff-files={dirty!r} blob==disk={same} "
          f"index={git(c, 'ls-files', '-s', '--', SPEC).split()[0].decode()} "
          f"disk={(c/SPEC).stat().st_mode & 0o777:04o}")
    summary("默认", gate(c))
    summary("只核提交", gate(c, "--no-worktree"))

if __name__ == "__main__":
    d = box()
    c = clone(d, "posix", "-c", "core.filemode=true", "-c", "core.autocrlf=false")
    inspect(c, "对照")
    f = c / SPEC
    f.chmod(0o654)
    inspect(c, "只增加组执行位")
    f.chmod(0o744)
    summary("属主执行位", gate(c))
    print("属主执行位的 Git 差异：", git(c, "diff-files", "--summary", "--", SPEC).decode().strip())
    f.chmod(0o644)
    git(c, "config", "--replace-all", "core.filemode", "false")
    summary("仅关闭 core.filemode", gate(c))
    f.chmod(0o754)
    inspect(c, "core.filemode=false 且磁盘可执行")
    c = clone(d, "crlf", "-c", "core.autocrlf=true")
    print(git(c, "ls-files", "--eol", "--", SPEC).decode().strip())
    inspect(c, "未经修改的 CRLF 检出")
