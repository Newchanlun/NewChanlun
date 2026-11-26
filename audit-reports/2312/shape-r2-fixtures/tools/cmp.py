#!/usr/bin/env python3
"""cmp.py <批目录>：跑 shp.py，与 EXPECT.tsv 比对。期望 GREEN 须无发现；期望红码集合须是实际红码的子集。"""
import os, subprocess, sys
root = sys.argv[1]
exp = dict(l.split("\t") for l in open(os.path.join(root, "EXPECT.tsv")).read().splitlines())
out = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "shp.py"), root, "-v"], capture_output=True, text=True)
got, detail, cur = {}, {}, None
for l in out.stdout.splitlines():
    if l.startswith("      L"):
        detail[cur].append(l.strip()); continue
    parts = l.split()
    if len(parts) >= 3 and parts[0].endswith(".lean"):
        cur = parts[0]; got[cur] = parts[2]; detail[cur] = []
    else: print("??", l)
if out.stderr.strip(): print("STDERR:", out.stderr[:3000])
bad = 0
for rel, e in sorted(exp.items()):
    g = got.get(rel, "MISSING")
    ok = (g == "GREEN") if e == "GREEN" else (g != "GREEN" and g != "MISSING" and (e == "RED" or set(e.split(",")) <= set(g.split(","))))
    if not ok:
        bad += 1
        print("MISMATCH %-44s expect=%s got=%s" % (rel, e, g))
        for d in detail.get(rel, []): print("     ", d)
    elif "-a" in sys.argv:
        print("ok       %-44s expect=%s got=%s" % (rel, e, g))
print("total %d mismatches %d" % (len(exp), bad))
