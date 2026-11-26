#!/usr/bin/env python3
"""r3 N-3 与 N-4 续：lean 工作进程被杀（N-3 的说明）、超时与信号同时发生、
第 4、7 步审计程序被信号杀死（N-3 说明里「沙箱顶层进程」那一半）。须包在 flock + guard.sh 里。"""
import json, os, re, signal, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rf3 as rf
st = rf.st


def shell(script, imports=()):
    head = "module\n\n" + "".join("public import %s\n" % m for m in imports) + "\npublic section\n\n"
    return (head + '#eval show IO Unit from do\n  let _ ← IO.Process.output {cmd := "/bin/sh", args := #["-c", %s]}\n'
            % json.dumps(script)).encode()


r = rf.repo()
lite_files = st.template(lite=True)
base = r.commit(lite_files)
kill_own = r.commit({**lite_files, "formal_math/ChanExplore/KillOwn.lean":
                     shell("kill -KILL $PPID", ("Chan",))}, base)
kill_lake = r.commit({**lite_files, "formal_math/ChanExplore/KillLake.lean":
                      shell("kill -KILL 2", ("Chan",))}, base)
spin = r.commit({**lite_files, "formal_math/ChanExplore/Spin.lean": shell(
    "while :; do echo tick >> .lake/tick; sleep 0.2; done", ("Chan",))}, base)


def plain(name, head, extra=(), mode=None, sig=None, delay=None):
    work = rf.fresh(name)
    cmd, _ = rf.command(name, r, head, base, extra=list(extra), warm=True, workdir=work)
    if mode:
        drv = os.path.join(rf.WORK, "driver-st.py")
        shutil.copy  # 不用
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/")})
    if sig is not None:
        time.sleep(delay)
        try:
            p.send_signal(sig)
        except ProcessLookupError:
            pass
    out, err = p.communicate(timeout=400)
    res = st.parse_result(subprocess.CompletedProcess(cmd, p.returncode, out, err))
    lines = out.decode("utf-8", "replace").splitlines()
    results = [l for l in lines if l.startswith("FM RESULT")]
    print("=== %s\n  rc=%s 红码=%s 故障=%s" % (name, p.returncode, sorted(res["reds"]), res["faults"]))
    print("  结果行 %d 条 %r；最后一行=%r" % (len(results), results, lines[-1] if lines else None))
    fl = [l for l in err.decode("utf-8", "replace").splitlines() if l.startswith("FM FAULT")]
    print("  FM FAULT=%r" % fl[:3])
    logs = [l for l in err.decode("utf-8", "replace").splitlines() if "exited with code" in l or "SIGKILL" in l]
    print("  相关日志=%r" % logs[:3])
    print("  契约：至多一条结果行=%s" % (len(results) <= 1))
    sys.stdout.flush()
    st.rmtree(work)
    return res


import shutil
print("## N-3：lean 工作进程被杀（kill -KILL $PPID）→ 说明说应报 BUILD_WFAIL 退 1")
plain("N3-kill-own-lean", kill_own)
print("## 对照：沙箱顶层进程 lake 被杀（kill -KILL 2）→ 说明说应 SIGNAL 退 2")
plain("N3-kill-lake", kill_lake)
print("## 超时与信号同时发生：第 6 步时限改成 10 秒，第 9.9 秒发 SIGTERM")
work = rf.fresh("N4-timeout-plus-signal")
drv = os.path.join(rf.WORK, "driver-timeout.py")
open(drv, "w").write('''
import importlib.util, sys
spec = importlib.util.spec_from_file_location("fm_run", sys.argv[1])
run = importlib.util.module_from_spec(spec); spec.loader.exec_module(run)
run.TIMEOUT["build"] = 10
import shutil
steps = list(run.STEP_FUNCS)
warm = sys.argv[2]
def w(ctx, real=steps[2]):
    shutil.copytree(warm, ctx.trusted_dir + "/verification/auditor/.lake", symlinks=True)
    return real(ctx)
steps[2] = w
sys.exit(run.main(sys.argv[3:], steps=steps))
''')
cmd = [sys.executable, "-I", drv, rf.RUN, rf.warm_dir(), "--repo", r.path, "--base", base, "--head", spin,
       "--branch", "proof/review", "--workdir", work, "--packages", rf.FAKE]
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/")})
time.sleep(12.4)
try:
    p.send_signal(signal.SIGTERM)
except ProcessLookupError:
    pass
out, err = p.communicate(timeout=400)
lines = out.decode("utf-8", "replace").splitlines()
results = [l for l in lines if l.startswith("FM RESULT")]
print("=== N4-timeout-plus-signal\n  rc=%s\n  结果行 %d 条 %r\n  最后一行=%r" %
      (p.returncode, len(results), results, lines[-1] if lines else None))
print("  FM FAULT=%r" % [l for l in err.decode("utf-8", "replace").splitlines() if l.startswith("FM FAULT")][:3])
tick = os.path.join(work, "audited", ".lake", "tick")
a = os.path.getsize(tick) if os.path.exists(tick) else None
time.sleep(2)
b = os.path.getsize(tick) if os.path.exists(tick) else None
print("  tick 字节数 %s → %s（2 秒后）；残留进程=%r" % (a, b, [l for l in subprocess.run(
    ["ps", "-e", "-o", "pid,comm,args"], capture_output=True, text=True).stdout.splitlines()
    if re.search(r"bwrap|ChanExplore|/lean |/lake ", l)][:3]))
st.rmtree(work)
