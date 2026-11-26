#!/usr/bin/env python3
"""对 fixtures.tsv 里归「本片判红」的行，跑第 5 步并与第 5 列红码集合比对。"""
import os, subprocess, sys
WT = "/home/workspace/.t3/worktrees/NewChanlun/t3-96236229-649fa7e07ba1d303"
V = WT + "/formal_math/verification"
HERE = os.path.dirname(os.path.abspath(__file__))
rows = []
for line in open(V + "/runner/fixtures.tsv", encoding="utf-8"):
    if line.startswith("#") or not line.strip(): continue
    fx, owner, rc, step, codes, note = line.rstrip("\n").split("\t")
    if "本片判红" in note:
        rows.append((fx, rc, step, set() if codes == "-" else set(codes.split(",")), note))
sel = rows
if len(sys.argv) > 1 and sys.argv[1].isdigit():
    n = int(sys.argv[1]); off = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    sel = rows[off:off+n]
print("总 %d 行，本次 %d 行" % (len(rows), len(sel)))
bad = 0
for fx, rc, step, codes, note in sel:
    src = os.path.join(V, fx, "formal_math")
    out = subprocess.run([sys.executable, os.path.join(HERE, "shp.py"), src, "-v"], capture_output=True, text=True)
    got = set()
    for l in out.stdout.splitlines():
        p = l.split()
        if len(p) >= 3 and p[0].endswith(".lean") and p[2] != "GREEN":
            got |= set(p[2].split(","))
    ok = (step == "shape" and rc == "1" and got == codes)
    if not ok: bad += 1
    print("%-6s %-52s tsv=%s|%s 实测=%s %s" % ("ok" if ok else "MISMATCH", fx, step, ",".join(sorted(codes)),
          ",".join(sorted(got)) or "GREEN", "" if ok else note[:60]))
print("不符 %d / %d" % (bad, len(sel)))
