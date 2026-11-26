"""独审 r3 的弱化测试：在被审树的副本里改一处，用副本自己的自测跑骨架用例。
与作者 --mutants 的 28 种不重复，重点在形状表、隔离检查、结果行三处。
非 lite 的骨架用例（S1、S2、S3、S10）对共享依赖目录仍只是只读挂载；这里没有改沙箱挂载的弱化。
用法：mutants3.py <被审检出> <依赖目录> [标签…]"""
import os, re, shutil, subprocess, sys, time

SRC, PACKAGES, only = sys.argv[1], sys.argv[2], set(sys.argv[3:])
FM = os.path.join(SRC, "formal_math")
TOP = os.path.join(os.environ["TMPDIR"], "review-f3", "mut")
R = "verification/runner/run.py"
MUTANTS = [
    ("Q0", "对照：不改", None, [], "S20,S21,S24,S25,S26a,S26b,S28"),
    ("Q1", "形状表只查文件表，目录一律放过", R,
     [("if rel and not (rel in dirs or CONFIG_DIR.fullmatch(rel) if stat.S_ISDIR(kind)",
       "if rel and not (True if stat.S_ISDIR(kind)")], "S20,S21,S28"),
    ("Q2", "去掉文件模式检查（执行位、特殊位、属主可读）", R,
     [("            if mode & 0o7111 or not mode & 0o400:", "            if False:")], None),
    ("Q3", "ARTIFACT_ROOT 的层级判断写错（==3 改成 ==4）", R,
     [('rel.startswith("build/lib/lean/") and rel.count("/") == 3', 'rel.startswith("build/lib/lean/") and rel.count("/") == 4')],
     "S20,S21,S28"),
    ("Q4", "NO_ARTIFACT 只看路径存在，不要求通过形状检查", R,
     [('        if "build/lib/lean/%s.olean" % "/".join(m) not in good:',
       '        if not os.path.exists(os.path.join(lake_dir, "build/lib/lean/%s.olean" % "/".join(m))):')],
     "S20,S21,S28"),
    ("Q5", "finish() 去掉「整次运行至多写一次」的守卫", R,
     [('    if STATE["result"]:\n        return False\n    STATE["result"] = True\n', '    STATE["result"] = True\n')],
     None),
    ("Q6", "隔离检查的出口改成 raise SystemExit(2)（不用 posix._exit）", R,
     [("    posix._exit(2)", "    raise SystemExit(2)")], "S24"),
]


def copy(tag):
    root = os.path.join(TOP, tag, "formal_math")
    shutil.rmtree(os.path.join(TOP, tag), ignore_errors=True)
    for rel in ("lean-toolchain", "lake-manifest.json", "ChanTest/Probe.lean"):
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        shutil.copy2(os.path.join(FM, rel), os.path.join(root, rel))
    for sub in ("runner", "precheck", "auditor"):
        shutil.copytree(os.path.join(FM, "verification", sub), os.path.join(root, "verification", sub),
                        ignore=shutil.ignore_patterns(".lake", "__pycache__"))
    return root


for tag, label, rel, edits, cases in MUTANTS:
    if only and tag not in only:
        continue
    root = copy(tag)
    if rel:
        path = os.path.join(root, rel)
        text = open(path, encoding="utf-8").read()
        bad = False
        for old, new in edits:
            if text.count(old) != 1:
                print("%s\t%s\t**改弱点出现 %d 次，判失败**" % (tag, label, text.count(old)))
                bad = True
                break
            text = text.replace(old, new)
        if bad:
            continue
        open(path, "w", encoding="utf-8").write(text)
    began = time.monotonic()
    p = subprocess.run([sys.executable, "-I", os.path.join(root, "verification", "runner", "selftest.py"),
                        "--packages", PACKAGES, "--skip-corpus", "--jobs", "4",
                        *(["--cases", cases] if cases else [])], capture_output=True)
    out = p.stdout.decode(errors="replace")
    failed = [l.split("\t")[1][:70] for l in out.splitlines() if l.startswith("失败\t")]
    total = re.findall(r"自测：(\d+/\d+)", out)
    print("%s\t%s\t用例=%s\t自测退出码=%d\t%s\t%.0fs\t%s" % (
        tag, label, cases or "骨架全量", p.returncode, total[0] if total else "?", time.monotonic() - began,
        "抓到：" + "；".join(failed) if failed else ("对照通过" if tag == "Q0" else "**没抓到**")))
    sys.stdout.flush()
    shutil.rmtree(os.path.join(TOP, tag), ignore_errors=True)
