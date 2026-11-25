"""完整克隆复验两项工作区误红；换行结尾的关联工作树另测自测自动定位。"""
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REV, SELF, SPEC, SRC, box, gate, git, project, run, show


def fresh(tmp, name, autocrlf):
    c = tmp / name
    git(tmp, "clone", "-q", "--shared", "--no-checkout", "-c", "core.autocrlf=" + autocrlf, SRC, c)
    git(c, "switch", "-q", "--detach", REV)
    assert git(c, "rev-parse", "HEAD").strip().decode() == REV
    return c


def check(label, c):
    path = c / SPEC
    raw = git(c, "cat-file", "blob", "HEAD:" + SPEC)
    index = git(c, "ls-files", "-s", SPEC).split()[0]
    print(f"{label}: status={git(c, 'status', '--porcelain')!r} index={index.decode()} "
          f"disk={stat.S_IMODE(path.stat().st_mode):04o} disk==blob={raw == path.read_bytes()}", flush=True)
    show(label, gate(c))


def main():
    tmp = box()
    c = fresh(tmp, "full", "false")
    git(c, "config", "core.filemode", "true")
    spec = c / SPEC
    check("干净分离检出", c)
    spec.chmod(0o654)
    check("只有组执行位", c)
    crlf = fresh(tmp, "crlf", "true")
    print(git(crlf, "ls-files", "--eol", SPEC).decode().strip(), flush=True)
    check("CRLF 干净克隆", crlf)
    # git worktree 的公共对象目录在普通路径，工作树路径的最后一个字节是 LF。
    base = project(tmp)
    linked = tmp / "linked\n"
    git(base, "worktree", "add", "-q", "--detach", linked, "HEAD")
    assert git(linked, "rev-parse", "--show-toplevel").endswith(b"\n\n")
    show("换行尾关联工作树：检查器", gate(linked))
    p = run(linked, sys.executable, "-IB", SELF)
    print("换行尾关联工作树：自测：", p.returncode, (p.stderr or p.stdout).decode().splitlines()[-1], flush=True)


if __name__ == "__main__":
    main()
