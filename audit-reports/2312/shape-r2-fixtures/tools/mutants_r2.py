#!/usr/bin/env python3
"""独审 r2 自做的弱化：在副本里改一处，用副本的自测跑指定骨架用例，看是否变红。
用法: mutants_r2.py <标签,...|all>   （须 source scripts/fm_env.sh；每种弱化单独包 flock+guard）"""
import os, re, shutil, subprocess, sys, time
WT = "/home/workspace/.t3/worktrees/NewChanlun/t3-d0f2425c-f0be678e43ff7b3c"
FM = WT + "/formal_math"
V = FM + "/verification"
PK = "/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages"
TOP = "/home/workspace/fm/tmp/review-g2/mut"
RUNNER = "verification/runner/run.py"
SHAPE = "verification/auditor/Auditor/Shape.lean"
M = [
    ("control", "对照（未改弱）", None, [], "H1,S32"),
    ("m1", "legacyConfig 只看前两个子节点（不要求第三个是 :=）", SHAPE,
     [('stx[2].isAtom && stx[2].getAtomVal.trimAscii.copy == ":=" then', "true then")], "H1,H1b,H2,D1"),
    ("m2", "名字判据由「以 config 结尾」改成「等于 config」", SHAPE,
     [('if key.endsWith "config" then some key else none', 'if key == "config" then some key else none')], "H1"),
    ("m3", "NO_CERTIFICATE 去掉路径比对（只查 None）", RUNNER,
     [('if certificate is None or certificate != os.path.join(ctx.trusted_dir, "derived.json"):',
       "if certificate is None:")], "S32,S22,D1,D2"),
    ("m4", "legacyConfig 不认标识符形式的键（只认记号）", SHAPE,
     [('else if stx[1].isIdent then stx[1].getId.eraseMacroScopes.toString else ""', 'else ""')], "H1"),
    ("m5", "legacyConfig 不认记号形式的键（只认标识符）", SHAPE,
     [("let key := if stx[1].isAtom then stx[1].getAtomVal.trimAscii.copy\n      else if stx[1].isIdent",
       "let key := if stx[1].isIdent")], "H1"),
    ("m6", "valConfigItem 分支不再查 native", SHAPE,
     [('  | .str _ "valConfigItem" =>\n    if stx[1].getId.eraseMacroScopes == `native then',
       '  | .str _ "valConfigItem" =>\n    if false && stx[1].getId.eraseMacroScopes == `native then')], "H1"),
    ("m7", "NO_CERTIFICATE 只做路径比对、去掉 None 判定之外整条改成恒假的另一半：只留 None 之外（certificate != 路径）", RUNNER,
     [('if certificate is None or certificate != os.path.join(ctx.trusted_dir, "derived.json"):',
       'if certificate is not None and certificate != os.path.join(ctx.trusted_dir, "derived.json"):')], "S32"),
]


def copy(tag):
    root = os.path.join(TOP, tag, "formal_math")
    shutil.rmtree(os.path.join(TOP, tag), ignore_errors=True)
    for rel in ("lean-toolchain", "lake-manifest.json", "ChanTest/Probe.lean"):
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        shutil.copy2(os.path.join(FM, rel), os.path.join(root, rel))
    for sub in ("runner", "precheck", "auditor"):
        shutil.copytree(os.path.join(V, sub), os.path.join(root, "verification", sub),
                        ignore=shutil.ignore_patterns(".lake", "__pycache__"))
    return root


want = sys.argv[1].split(",")
for tag, label, rel, edits, cases in M:
    if want != ["all"] and tag not in want:
        continue
    root = copy(tag)
    if rel:
        path = os.path.join(root, rel)
        text = open(path, encoding="utf-8").read()
        for old, new in edits:
            assert text.count(old) == 1, (tag, text.count(old))
            text = text.replace(old, new)
        open(path, "w", encoding="utf-8").write(text)
    began = time.monotonic()
    p = subprocess.run(["flock", "/home/workspace/fm/lean.lock", "/home/workspace/fm/guard.sh", sys.executable, "-I",
                        os.path.join(root, "verification", "runner", "selftest.py"), "--packages", PK,
                        "--skip-corpus", "--jobs", "2", "--cases", cases], capture_output=True)
    out = p.stdout.decode(errors="replace")
    failed = [l for l in out.splitlines() if l.startswith("失败\t")]
    summary = re.findall(r"自测：.*", out)
    print("%s\t%s\t用例 %s\trc=%d\t%s\t%.0fs" % (tag, label, cases, p.returncode, summary, time.monotonic() - began))
    for l in failed:
        print("    " + l[:900])
    if p.stderr.strip():
        print("    STDERR " + p.stderr.decode(errors="replace")[-600:])
    sys.stdout.flush()
    shutil.rmtree(os.path.join(TOP, tag), ignore_errors=True)
