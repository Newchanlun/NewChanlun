#!/usr/bin/env python3
"""sweep.py <根> <夹具相对路径...>：对每个夹具目录只跑第 5 步（shape-plan + shape），打印红码集合。"""
import os, subprocess, sys, json
V = "/home/workspace/.t3/worktrees/NewChanlun/t3-96236229-649fa7e07ba1d303/formal_math/verification"
HERE = os.path.dirname(os.path.abspath(__file__))
for fx in sys.argv[1:]:
    src = os.path.join(V, fx, "formal_math")
    if not os.path.isdir(src):
        print("%-60s NO-DIR" % fx); continue
    out = subprocess.run([sys.executable, os.path.join(HERE, "shp.py"), src, "-v"], capture_output=True, text=True)
    codes, lines = set(), []
    for l in out.stdout.splitlines():
        p = l.split()
        if len(p) >= 3 and p[0].endswith(".lean") and p[2] != "GREEN":
            codes |= set(p[2].split(","))
        if l.startswith("      L"): lines.append(l.strip()[:110])
    extra = ""
    if out.stderr.strip() or "FAULT" in out.stdout or "STDERR" in out.stdout:
        extra = " !!" + (out.stdout[out.stdout.find("STDERR"):][:150] if "STDERR" in out.stdout else out.stderr[:150])
    print("%-56s %s%s" % (fx, ",".join(sorted(codes)) or "GREEN", extra))
    if "-v" in os.environ.get("SWEEP", ""):
        for x in lines[:4]: print("      ", x)
