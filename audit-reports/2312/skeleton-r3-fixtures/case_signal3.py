#!/usr/bin/env python3
"""r3 N-4：新装的信号处理函数与子进程组管理。各步被打断、处理函数里再被打断、孤儿进程、
bwrap 是否随进程组结束、超时与信号同时发生。走真实命令行入口（不预热审计程序的那几例注明）。
须包在 flock + guard.sh 里。"""
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
green = r.commit({**lite_files, "formal_math/Chan/Ok.lean":
                  b"module\n\npublic section\n\npublic theorem ok : 1 + 1 = 2 := rfl\n"}, base)
# 构建期无限循环、每 0.2 秒往 .lake/tick 追加一行（用来看沙箱里的进程有没有随信号结束）
spin = r.commit({**lite_files, "formal_math/ChanExplore/Spin.lean": shell(
    "while :; do echo tick >> .lake/tick; sleep 0.2; done", ("Chan",))}, base)


def procs():
    out = subprocess.run(["ps", "-e", "-o", "pid,pgid,sess,comm,args"], capture_output=True, text=True).stdout
    keep = [l for l in out.splitlines()[1:]
            if re.search(r"bwrap|/lean\b|/lake\b|ChanExplore|fm_audit", l) and "ps -e" not in l]
    return keep


def one(name, head, sig, delay, extra=(), second=None, stderr_full=False, warm=True, env=None):
    work = rf.fresh(name)
    cmd, _ = rf.command(name, r, head, base, extra=list(extra), warm=warm, workdir=work)
    before = procs()
    kw = {}
    if stderr_full:
        rfd, wfd = os.pipe()          # 读端不读：处理函数写标准错误时会阻塞
        os.set_blocking(wfd, False)
        try:
            while True:
                os.write(wfd, b"x" * 65536)
        except BlockingIOError:
            pass
        os.set_blocking(wfd, True)
        kw["stderr"] = wfd
    else:
        kw["stderr"] = subprocess.PIPE
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, env=env or {"PATH": os.environ["PATH"],
                                                                  "HOME": os.environ.get("HOME", "/")}, **kw)
    time.sleep(delay)
    try:
        p.send_signal(sig)
        if second is not None:
            time.sleep(second)
            p.send_signal(sig)
    except ProcessLookupError:
        pass
    out, err = p.communicate(timeout=300)
    rc = p.returncode
    if stderr_full:
        os.close(kw["stderr"]); os.close(rfd)
        err = "(标准错误是满的管道，没有读)".encode()
    time.sleep(1.5)
    leftover = [l for l in procs() if l not in before]
    tick = os.path.join(work, "audited", ".lake", "tick")
    t1 = os.path.getsize(tick) if os.path.exists(tick) else None
    time.sleep(2)
    t2 = os.path.getsize(tick) if os.path.exists(tick) else None
    lines = out.decode("utf-8", "replace").splitlines()
    results = [l for l in lines if l.startswith("FM RESULT")]
    greens = [l for l in results if l.startswith("FM RESULT GREEN")]
    print("=== %s（%s，延迟 %.1fs%s）\n  rc=%s（%s）" %
          (name, signal.Signals(sig).name, delay, "，%.1fs 后再来一次" % second if second else "", rc,
           "被信号终止" if rc < 0 else "正常退出"))
    print("  标准输出行数=%d；结果行 %d 条：%r" % (len(lines), len(results), results))
    print("  最后一行=%r" % (lines[-1] if lines else None))
    print("  绿结果行=%d；契约：至多一条结果行=%s，绿则 rc=0=%s，rc=0 则恰一条绿且在最后=%s"
          % (len(greens), len(results) <= 1, (not greens) or rc == 0,
             rc != 0 or (len(greens) == 1 and lines and lines[-1].startswith("FM RESULT GREEN"))))
    if not stderr_full:
        fl = [l for l in err.decode("utf-8", "replace").splitlines() if l.startswith("FM FAULT")]
        print("  标准错误的 FM FAULT 行 %d 条：%r" % (len(fl), fl[:4]))
    print("  残留进程 %d 个：%r" % (len(leftover), leftover[:4]))
    print("  .lake/tick 字节数 %s → %s（2 秒后）" % (t1, t2))
    sys.stdout.flush()
    st.rmtree(work)


print("## 各步被 SIGTERM / SIGINT 打断（延迟按预热后各步的时点挑）")
one("sig-step1-TERM", green, signal.SIGTERM, 0.05)
one("sig-step3-INT", green, signal.SIGINT, 0.35)
one("sig-step6-TERM-spin", spin, signal.SIGTERM, 2.2)
one("sig-step6-INT-spin", spin, signal.SIGINT, 2.2)
print("## 处理函数里再被打断（第二次信号紧随其后）")
one("sig-double-INT-spin", spin, signal.SIGINT, 2.2, second=0.001)
print("## 处理函数写标准错误时阻塞（标准错误是满的管道），再来第二次信号")
one("sig-stderr-full-spin", spin, signal.SIGTERM, 2.2, second=0.5, stderr_full=True)
print("## 不预热审计程序的真实入口（第 3 步 lake build 期间打断，子进程不在沙箱里）")
one("sig-step3-real-TERM", green, signal.SIGTERM, 1.0, warm=False)
