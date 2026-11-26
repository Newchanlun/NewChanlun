#!/usr/bin/env python3
"""r3 N-4 续：结果行契约「有绿结果行则退出码为 0」有没有时间窗。
做法只用调用方一侧：标准输出接管道，父进程读到绿结果行的那一刻立刻发 SIGTERM。
写已经完成，所以信号必定落在绿行之后；比的是「父进程发信号」与「子进程走完 SystemExit 与收尾」谁快。
须包在 flock + guard.sh 里。"""
import os, re, signal, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rf3 as rf
st = rf.st

r = rf.repo()
lite_files = st.template(lite=True)
base = r.commit(lite_files)
green = r.commit({**lite_files, "formal_math/Chan/Thm/Ok.lean":
                  b"module\n\npublic section\n\npublic theorem ok : 1 + 1 = 2 := rfl\n"}, base)

hits = []
for i in range(int(sys.argv[1]) if len(sys.argv) > 1 else 12):
    work = rf.fresh("green-signal-%d" % i)
    cmd, _ = rf.command("green-signal-%d" % i, r, green, base, warm=True, workdir=work)
    rfd, wfd = os.pipe()
    p = subprocess.Popen(cmd, stdout=wfd, stderr=subprocess.PIPE,
                         env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/")})
    os.close(wfd)
    buf, killed_at = b"", None
    with os.fdopen(rfd, "rb", buffering=0) as f:
        while True:
            chunk = f.readline()
            if not chunk:
                break
            buf += chunk
            if chunk.startswith(b"FM RESULT GREEN") and killed_at is None:
                try:
                    os.kill(p.pid, signal.SIGTERM)       # 绿行已经写完，立刻发信号
                    killed_at = time.monotonic()
                except ProcessLookupError:
                    killed_at = -1                        # 子进程已经退完，没打中
    err = p.stderr.read(); p.stderr.close()
    rc = p.wait()
    lines = buf.decode("utf-8", "replace").splitlines()
    results = [l for l in lines if l.startswith("FM RESULT")]
    greens = [l for l in results if l.startswith("FM RESULT GREEN")]
    violated = bool(greens) and rc != 0
    hits.append(violated)
    print("第 %2d 次：rc=%s 绿结果行=%d 结果行共 %d 条 发信号=%s → 「有绿则退 0」%s"
          % (i, rc, len(greens), len(results), "打中" if killed_at and killed_at > 0 else "子进程已退出（没打中）",
             "**不成立**" if violated else "成立"))
    if violated:
        print("     标准输出末两行=%r" % lines[-2:])
        print("     标准错误里的 FM FAULT=%r" % [l for l in err.decode("utf-8", "replace").splitlines()
                                            if l.startswith("FM FAULT")])
    sys.stdout.flush()
    st.rmtree(work)
print("\n%d 次里有 %d 次「有绿结果行则退出码为 0」不成立" % (len(hits), sum(hits)))
