"""RESULT 行在输出失败与信号路径上是否「恰好一行、总在最后」。T1、T8、T9 走真实命令行入口；T2–T7 经预编译审计程序的驱动省第 3 步。"""
import os, signal, subprocess, sys, time
import rf2
r = rf2.repo()
base, files = rf2.lite(r)
M = rf2.M
ENV = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/")}
green = r.commit({**files, "formal_math/Chan/Thm/Ok.lean": (M + "theorem ok : 1 + 1 = 2 := rfl\n").encode()}, base)
red = r.commit({**files, "formal_math/Chan/Thm/Bad.lean": (M + "theorem bad : 1 = 2 := rfl\n").encode()}, base)
spin = r.commit({**files, "formal_math/ChanExplore/Spin.lean": (
    M + '#eval show IO Unit from do\n  for _ in [0:300] do\n    IO.sleep 200\n'
        '    let h ← IO.FS.Handle.mk ".lake/tick" .append\n    h.putStrLn "t"\n    h.flush\n').encode()}, base)


def report(name, cmd, rc, out, err):
    lines = out.decode("utf-8", "replace").split("\n")
    results = [l for l in lines if l.startswith("FM RESULT ")]
    print("=== %s\nrc=%s\n--- stdout\n%s--- stderr(tail)\n%s\n--- FM RESULT 行 %d 条：%s\n" % (
        name, rc, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")[-600:], len(results), results))
    sys.stdout.flush()


# 1. 标准输出是写满的非阻塞管道：前几行写不出，后来读端开始读。
cmd, work = rf2.command("T1-nonblocking-stdout", r, green, base, warm=False)   # 真实命令行入口
rfd, wfd = os.pipe()
os.set_blocking(wfd, False)
filled = 0
try:
    while True:
        filled += os.write(wfd, b"\n" * 65536)
except BlockingIOError:
    pass
errf = open(os.path.join(rf2.WORK, "T1.err"), "wb+")
p = subprocess.Popen(cmd, stdout=wfd, stderr=errf, env=ENV)
os.close(wfd)
time.sleep(0.6)         # 这段时间里 MODE、RUNNER 等开头几行因 EAGAIN 写不出；整次运行约 12 秒
data = b""
while True:
    chunk = os.read(rfd, 65536)
    if not chunk:
        break
    data += chunk
rc = p.wait()
errf.seek(0)
report("T1 标准输出是写满的非阻塞管道，0.6 秒后读端才开始读（预先填了 %d 个换行）" % filled, cmd, rc, data.lstrip(b"\n"), errf.read())

# 2. 各种关闭与写满。
for name, head, redirect in (("T2 绿，标准输出已关闭", green, ">&-"), ("T3 绿，标准错误已关闭", green, "2>&-"),
                             ("T4 红，标准输出已关闭", red, ">&-"), ("T5 红，标准输出指向 /dev/full", red, ">/dev/full"),
                             ("T6 绿，标准输出指向 /dev/full", green, ">/dev/full"), ("T7 绿，三路全关", green, "<&- >&- 2>&-")):
    cmd, work = rf2.command("T-stream", r, head, base)
    outp, errp = os.path.join(rf2.WORK, "T.out"), os.path.join(rf2.WORK, "T.err")
    script = 'exec "$@" ' + (redirect if ">" in redirect.replace("2>", "") else "> %s %s" % (outp, redirect)) + \
             ("" if "2>" in redirect else " 2> %s" % errp)
    for f in (outp, errp):
        open(f, "wb").close()
    p = subprocess.run(["/bin/sh", "-c", script, "sh", *cmd], env=ENV)
    report(name + "（%s）" % redirect, cmd, p.returncode, open(outp, "rb").read(), open(errp, "rb").read())

# 3. 构建期间给 run.py 发信号。
for name, sig in (("T8 第 6 步期间 SIGINT", signal.SIGINT), ("T9 第 6 步期间 SIGTERM", signal.SIGTERM)):
    cmd, work = rf2.command("T-signal", r, spin, base, warm=False)   # 真实命令行入口：兜底在 run.py 的 __main__ 里
    # 本夹具可能在忽略 SIGINT 的后台环境里跑，子进程里恢复默认处置，Python 才会装上 KeyboardInterrupt 的处理器。
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV,
                         preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    tick = os.path.join(work, "audited", ".lake", "tick")
    for _ in range(600):
        if os.path.exists(tick):
            break
        time.sleep(0.1)
    time.sleep(1)
    p.send_signal(sig)
    out, err = p.communicate()
    size = os.path.getsize(tick) if os.path.exists(tick) else -1
    time.sleep(2)
    after = os.path.getsize(tick) if os.path.exists(tick) else -1
    left = subprocess.run(["pgrep", "-af", work], capture_output=True).stdout.decode().strip()
    report(name, cmd, p.returncode, out, err)
    print("tick 字节数 %d → %d（2 秒后）；仍在运行且命令行含本次工作目录的进程：%s\n" % (size, after, left or "无"))
