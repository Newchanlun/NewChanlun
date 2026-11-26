#!/usr/bin/env python3
"""r3：第 6 步沙箱结束与形状表遍历之间有没有时间窗。不调用 lean、lake，只起 bwrap。
用被审 run.py 自己的 sandbox() 与 artifact_reds()，顺序与 step_build 相同：sandbox() 返回后立即遍历。
沙箱里的“构建”是一段 shell：摆好合法形状的产物，再留一个脱离了管道的后台进程，然后自己以 0 退出。
用法：python3 -I race_probe.py <run.py> <工作根目录> <模式> [次数]
模式 measure：后台进程不停把单调时钟写进一个表内文件，量它在 sandbox() 返回之后还活了多久。"""
import importlib.util, os, shutil, subprocess, sys, time

spec = importlib.util.spec_from_file_location("fm_run", sys.argv[1])
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
root, mode, rounds = sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 5

DAEMON_MEASURE = r'''
import os, time
os.setsid()
fd = os.open(".lake/build/ir/Chan/A.c", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
for f in (0, 1, 2):
    os.close(f)
while True:
    os.pwrite(fd, b"%020d" % time.monotonic_ns(), 0)
'''


def one(i, daemon, extra=""):
    work = os.path.join(root, "race-%s-%d" % (mode, i))
    subprocess.run(["chmod", "-R", "u+rwX", work], stderr=subprocess.DEVNULL)
    shutil.rmtree(work, ignore_errors=True)
    ctx = run.Run()
    ctx.workdir, ctx.prefix = work, "/usr"
    ctx.audited = os.path.join(work, "audited")
    ctx.modules = ["Chan.A"]
    lake = os.path.join(ctx.audited, ".lake")
    os.makedirs(os.path.join(lake, "packages"))
    with open(os.path.join(ctx.audited, "daemon.py"), "w") as f:
        f.write(daemon)
    binds = [("--ro-bind", ctx.audited, ctx.audited), ("--bind", lake, lake)]
    script = ("mkdir -p .lake/build/lib/lean/Chan .lake/build/ir/Chan && : > .lake/build/lib/lean/Chan/A.olean && "
              ": > .lake/build/ir/Chan/A.c && %s (python3 -I daemon.py </dev/null >/dev/null 2>&1 &) ; sleep %s; exit 0" % (extra, os.environ.get("RACE_SLEEP", "0.3")))
    p = run.sandbox(ctx, ["sh", "-c", script], binds, {}, ctx.audited, 60, "BUILD", "build", merge=True)
    t_ret = time.monotonic_ns()
    reds = run.artifact_reds(ctx, lake)
    t_done = time.monotonic_ns()
    return work, lake, p.returncode, t_ret, t_done, reds


DAEMON_CROWD = r"""
import os, signal, time
N = %d
os.setsid()
for f in (0, 1, 2):
    os.close(f)
for _ in range(N):          # 先占住一批较小的进程号：1 号进程退出时内核按进程号从小到大逐个发 SIGKILL
    if os.fork() == 0:
        signal.pause()
        os._exit(0)
if os.fork() != 0:          # 真正干活的进程排在最后
    signal.pause()
fd = os.open(".lake/build/ir/Chan/A.c", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
while True:
    os.pwrite(fd, b"%%020d" %% time.monotonic_ns(), 0)
"""

if mode.startswith("crowd"):
    n = int(mode[5:])
    for i in range(rounds):
        work, lake, rc, t_ret, t_done, reds = one(i, DAEMON_CROWD % n, extra="")
        time.sleep(1.0)
        a = int(open(os.path.join(lake, "build/ir/Chan/A.c")).read() or 0)
        time.sleep(0.5)
        b = int(open(os.path.join(lake, "build/ir/Chan/A.c")).read() or 0)
        print("N=%d 第 %d 次：rc=%d reds=%r 遍历耗时 %d µs；后台进程最后一次写入相对 sandbox() 返回 %+d µs，相对遍历结束 %+d µs；"
              "之后是否还在写：%s" % (n, i, rc, reds, (t_done - t_ret) // 1000, (a - t_ret) // 1000, (a - t_done) // 1000,
                                 "是" if b != a else "否"))

if mode == "measure":
    for i in range(rounds):
        work, lake, rc, t_ret, t_done, reds = one(i, DAEMON_MEASURE)
        time.sleep(0.5)
        a = int(open(os.path.join(lake, "build/ir/Chan/A.c")).read() or 0)
        time.sleep(0.5)
        b = int(open(os.path.join(lake, "build/ir/Chan/A.c")).read() or 0)
        print("第 %d 次：rc=%d reds=%r 遍历耗时 %d µs；后台进程最后一次写入相对 sandbox() 返回 %+d µs，相对遍历结束 %+d µs；"
              "0.5 秒后是否还在写：%s" % (i, rc, reds, (t_done - t_ret) // 1000, (a - t_ret) // 1000, (a - t_done) // 1000,
                                 "是" if b != a else "否"))
