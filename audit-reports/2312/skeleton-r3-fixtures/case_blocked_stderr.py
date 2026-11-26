#!/usr/bin/env python3
"""r3 N-4 续：标准错误阻塞时 emit() 与 on_signal() 的行为（单元级，不跑 lean）。
on_signal 先写标准错误的 FM FAULT，再写结果行；标准错误写不出去时结果行还能不能出来？"""
import os, subprocess, sys, textwrap

RUN = sys.argv[1]
CHILD = textwrap.dedent(r'''
    import importlib.util, os, signal, sys, time
    spec = importlib.util.spec_from_file_location("fm_run", sys.argv[1])
    run = importlib.util.module_from_spec(spec); spec.loader.exec_module(run)
    mode = sys.argv[2]
    # fd 2 换成一个写满的阻塞管道（读端留着但不读）
    rfd, wfd = os.pipe()
    os.set_blocking(wfd, False)
    try:
        while True:
            os.write(wfd, b"x" * 65536)
    except BlockingIOError:
        pass
    os.set_blocking(wfd, True)
    os.dup2(wfd, 2)
    run.STATE["step"] = "build"
    if mode == "emit":
        run.emit(2, "LOG", "build", "一行普通日志")          # 期望：阻塞
        os.write(1, "emit 返回了\n".encode())
    elif mode == "signal":
        run.on_signal(signal.SIGTERM, None)                 # 期望：卡在 emit，结果行写不出
        os.write(1, "on_signal 返回了\n".encode())
    elif mode == "signal-reordered":
        run.finish("FAULT", run.STATE["step"], "SIGNAL")     # 对照：先写结果行
        os.write(1, "（对照）先写结果行后它出来了\n".encode())
''')
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_child_blocked.py")
open(path, "w").write(CHILD)
for mode in ("emit", "signal", "signal-reordered"):
    p = subprocess.Popen([sys.executable, "-I", path, RUN, mode], stdout=subprocess.PIPE,
                         env={"PATH": os.environ["PATH"]})
    try:
        out, _ = p.communicate(timeout=8)
        print("%-20s 8 秒内结束：rc=%s 标准输出=%r" % (mode, p.returncode, out.decode()))
    except subprocess.TimeoutExpired:
        p.kill()
        out = p.stdout.read()
        print("%-20s **8 秒内没有结束（卡住）**，此前的标准输出=%r" % (mode, out.decode()))
