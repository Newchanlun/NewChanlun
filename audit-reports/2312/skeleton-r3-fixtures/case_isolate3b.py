#!/usr/bin/env python3
"""r3 N-1 续：精确捕获 run.py 自己的退出码（上一版被 shell 管道与 echo 吃掉了），
并查清 `-c exec(...)` 一例里 linecache 为何被执行。不调用 lean、lake、git。"""
import os, subprocess, sys

W = sys.argv[1]
DIR = os.path.join(W, "dir")
HIT = os.path.join(W, "hit")


def attempt(name, setup):
    open(HIT, "w").close()
    r = setup()
    hits = open(HIT).read().split() or ["否"]
    print("%-40s run.py 自己的 rc=%-5s 冒名模块被执行：%s\n    stdout=%r\n    stderr=%r"
          % (name, r[0], ",".join(hits), r[1][:160], r[2][:160]))


def spawn(argv, close1=False, close2=False, full1=False, full2=False, pipe1=False, pipe2=False):
    """子进程里按需把 fd 置成各种状态，再 execv；父进程直接拿 waitpid 的状态，不经 shell。"""
    rd, wr = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(rd)
            devnull = os.open("/dev/null", os.O_RDONLY)
            os.dup2(devnull, 0)
            cap = {}
            for fd, close, full, pipe in ((1, close1, full1, pipe1), (2, close2, full2, pipe2)):
                if close:
                    os.close(fd)
                elif full:
                    f = os.open("/dev/full", os.O_WRONLY)
                    if f != fd:
                        os.dup2(f, fd); os.close(f)
                elif pipe:
                    a, b = os.pipe()
                    os.close(a)                      # 读端立即关闭 → 写入得 EPIPE
                    os.dup2(b, fd); os.close(b)
                else:
                    f = os.open(os.path.join(W, "out%d" % fd), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
                    if f != fd:
                        os.dup2(f, fd); os.close(f)
                    cap[fd] = True
            import signal as _s
            _s.signal(_s.SIGPIPE, _s.SIG_DFL)        # 不让 Python 的 SIGPIPE 处置干扰
            os.chdir(DIR)
            os.execv(argv[0], argv)
        except BaseException:
            os._exit(127)
    os.close(wr); os.close(rd)
    _, status = os.waitpid(pid, 0)
    rc = "退%d" % os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else \
         "信号%d" % os.WTERMSIG(status)
    got = []
    for fd in (1, 2):
        p = os.path.join(W, "out%d" % fd)
        got.append(open(p, "rb").read().decode("utf-8", "replace") if os.path.exists(p) else "")
        if os.path.exists(p):
            os.remove(p)
    return rc, got[0], got[1]


PY = sys.executable
R = os.path.join(DIR, "run.py")
print("=== 不带 -I：run.py 自己的退出码（fork+execv，不经 shell）")
for name, kw in (("两路正常", {}), ("stdout 关闭", {"close1": True}), ("stderr 关闭", {"close2": True}),
                 ("两路都关", {"close1": True, "close2": True}),
                 ("stdout=/dev/full", {"full1": True}), ("stderr=/dev/full", {"full2": True}),
                 ("两路=/dev/full", {"full1": True, "full2": True}),
                 ("stdout 读端已关管道", {"pipe1": True}), ("stderr 读端已关管道", {"pipe2": True}),
                 ("两路读端已关管道", {"pipe1": True, "pipe2": True}),
                 ("stdout 关、stderr 管道", {"close1": True, "pipe2": True}),
                 ("stdout=/dev/full、stderr 关", {"full1": True, "close2": True})):
    attempt(name, lambda kw=kw: spawn([PY, R, "--repo", "x"], **kw))
print("=== 对照：带 -I（期望 USAGE 退 2）")
for name, kw in (("两路正常", {}), ("两路都关", {"close1": True, "close2": True}),
                 ("两路读端已关管道", {"pipe1": True, "pipe2": True})):
    attempt("带 -I " + name, lambda kw=kw: spawn([PY, "-I", R, "--repo", "x"], **kw))
print("=== `-c exec(open(...).read())`：不是 README 支持的调用方式，查 linecache 从哪来")
attempt("-c exec(run.py)", lambda: spawn([PY, "-c", "exec(open('run.py').read())", "--repo", "x"]))
p = subprocess.run([PY, "-c", "exec(open('run.py').read())", "--repo", "x"], cwd=DIR,
                   capture_output=True, env={"PATH": os.environ["PATH"], "PYTHONVERBOSE": "1"})
tail = [l for l in p.stderr.decode("utf-8", "replace").split("\n") if "linecache" in l or "run.py" in l]
print("    PYTHONVERBOSE 里与 linecache 相关的行：%r" % tail[:6])
print("=== 内建模块能否被同目录文件顶替（直接问解释器）")
for flag in ([], ["-I"]):
    q = subprocess.run([PY, *flag, "-c",
                        "import sys;import posix;print('isolated',sys.flags.isolated,"
                        "'posix.__file__' , getattr(posix,'__file__',None), 'sys.__file__', getattr(sys,'__file__',None),"
                        "'loader', type(posix.__loader__).__name__, 'path0', sys.path[0] if sys.path else None)"],
                       cwd=DIR, capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    print("    flags=%-5s → %s%s" % (flag or ["无"], q.stdout.strip(), q.stderr.strip()[:200]))
