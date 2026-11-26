#!/usr/bin/env python3
"""审阅用：对一个目录（当作 formal_math 根）里的 .lean 直接跑 fm_audit shape-plan / shape（bwrap 只读）。
用法: shp.py <根目录> [--raw]   输出每个文件的发现。"""
import json, os, subprocess, sys
AUD = "/home/workspace/fm/tmp/review-g1/auditor/.lake/build/bin/fm_audit"
PK = "/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages"
NAMES = sorted(os.listdir(PK))
PREFIX = subprocess.run(["lean", "--print-prefix"], capture_output=True, text=True, cwd="/home/workspace/fm/tmp/review-g1/auditor").stdout.strip()
ENV = {"LEAN_PATH": ":".join(os.path.join(PK, n, ".lake", "build", "lib", "lean") for n in NAMES),
       "LEAN_SYSROOT": PREFIX, "PATH": PREFIX + "/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/tmp/home", "TMPDIR": "/tmp"}
def run(root, args):
    cmd = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--unshare-all",
           "--die-with-parent", "--clearenv"]
    for k, v in ENV.items(): cmd += ["--setenv", k, v]
    cmd += ["--chdir", root, AUD, *args]
    p = subprocess.run(cmd, capture_output=True)
    rows = [json.loads(l) for l in p.stdout.decode().splitlines() if l.strip()]
    return p.returncode, rows, p.stderr.decode()
def main():
    root = os.path.abspath(sys.argv[1]); raw = "--raw" in sys.argv
    files = []
    for d, _, fs in os.walk(root):
        for f in fs:
            if f.endswith(".lean"):
                rel = os.path.relpath(os.path.join(d, f), root); files.append(rel)
    files.sort()
    mods = {rel: rel[:-5].replace("/", ".") for rel in files}
    rc, rows, err = run(root, ["shape-plan", *(x for rel in files for x in (mods[rel], rel))])
    if rc != 0 or err: print("PLAN rc", rc, err)
    groups = {}
    for r in rows:
        if r[0] == "plan": groups.setdefault(tuple(sorted(set(r[3]))), []).append(r[1])
    out = {f: [] for f in files}; cmds = {}
    for libs, fs in sorted(groups.items()):
        rc, rows, err = run(root, ["shape", *libs, "--", *(x for rel in fs for x in (mods[rel], rel))])
        if raw: print("GROUP", libs, "rc", rc)
        if err.strip(): print("STDERR", libs, err.strip()[:2000])
        for r in rows:
            if raw: print("  ", json.dumps(r, ensure_ascii=False))
            if r[0] == "finding": out[r[2]].append((r[3], r[4], r[5]))
            if r[0] == "file": cmds[r[1]] = r[3]
        if rc not in (0, 1): print("FAULT rc", rc, libs, fs)
    for f in files:
        codes = sorted(set(c for _, c, _ in out[f]))
        print("%-52s cmds=%-3s %s" % (f, cmds.get(f, "?"), ",".join(codes) if codes else "GREEN"))
        if "-v" in sys.argv:
            for l, c, d in out[f]: print("      L%s %s %s" % (l, c, d[:160]))
main()
