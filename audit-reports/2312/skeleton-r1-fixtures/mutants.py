"""弱化（变异）测试：在被审树的副本里逐个弱化 run.py / Main.lean，跑骨架自测（--skip-corpus），看自测是否变红。
用法：mutants.py [变异名[:用例序号,…]]…。副本放 RF_WORK/mut-<名>/formal_math，不动被审检出。
给了用例序号时只跑骨架用例里的那几个（序号按 selftest.skeleton() 返回的次序：0=S1 1=S2 2=S3 3=S4 4-8=S5 9=S6a
10=S6b 11=S7 12=S8 13=S9 14=S10 15=S11 16=S12 17=S14 18=S15 19-20=S16 21=S13），否则跑全部骨架用例。
注意：不要加「把依赖目录挂成可写」的变异——S7 会真的往共享依赖目录里写哨兵。"""
import os, shutil, subprocess, sys
SRC = os.environ.get("RF_SRC", "/home/workspace/.t3/worktrees/NewChanlun/t3-279c6aca-c1e9a2095915fa5f")
WORK = os.environ.get("RF_WORK", "/home/workspace/fm/tmp/review-f/work")
PACKAGES = os.environ.get("RF_PACKAGES", "/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages")
RUNPY, MAIN = "verification/runner/run.py", "verification/auditor/Main.lean"
MUTANTS = {
  "MU0-unmodified": [],
  "MU1-no-runner-mismatch": [(RUNPY, "        if me != object_at(ctx, ctx.trusted, TRUSTED_CODE[0]):", "        if False:")],
  "MU2-no-module-count": [(RUNPY, "    if result[3] != len(ctx.modules):", "    if False:")],
  "MU3b-trusted-writable-in-build": [(RUNPY, '    binds = [("--ro-bind", ctx.audited, ctx.audited), ("--bind", lake_dir, lake_dir),', '    binds = [("--bind", ctx.trusted_dir, ctx.trusted_dir), ("--ro-bind", ctx.audited, ctx.audited), ("--bind", lake_dir, lake_dir),')],
  "MU3c-audited-writable-in-build": [(RUNPY, '    binds = [("--ro-bind", ctx.audited, ctx.audited), ("--bind", lake_dir, lake_dir),', '    binds = [("--bind", ctx.audited, ctx.audited), ("--bind", lake_dir, lake_dir),')],
  "MU4-no-artifact-root": [(RUNPY, "        if name.split(\".\")[0] not in ROOT_NAMES or os.path.islink(os.path.join(lib, name)):", "        if False:"),
                           (RUNPY, "    if os.path.realpath(lib) != lib:", "    if False:")],
  "MU5-continue-after-red": [(RUNPY, '            out(b"RESULT RED", "第 %d 步 %s 判红，后面的步骤没有跑" % (n, name))\n            return 1', '            out(b"RESULT RED", "第 %d 步 %s 判红，后面的步骤没有跑" % (n, name))\n            continue')],
  "MU6-auditor-loads-exts": [(MAIN, "  let env := (← Lean.importModules (mods.map fun m => { module := m }) {}\n    (level := .private)).setExporting false", "  Lean.enableInitializersExecution\n  let env := (← Lean.importModules (mods.map fun m => { module := m }) {}\n    (loadExts := true) (level := .private)).setExporting false")],
  "MU7-network-shared": [(RUNPY, 'b"--unshare-all", ', 'b"--unshare-user", b"--unshare-pid", b"--unshare-ipc", b"--unshare-uts", b"--unshare-cgroup", ')],
  "MU8-no-clearenv": [(RUNPY, '    args.append(b"--clearenv")\n', '')],
  "MU9-no-artifact-check": [(RUNPY, "        if os.path.islink(olean) or not os.path.isfile(olean):", "        if False:")],
  "MU10-exit-code-trusted": [(RUNPY, "            (result[2] == \"red\") != bool(findings) or p.returncode != (1 if findings else 0):", "            False:")],
  "MU11-no-hidden-dirs": [(RUNPY, '    for hidden in ("/home", "/root", "/run", "/var", "/tmp", ctx.workdir):', '    for hidden in ("/tmp",):')],
}
SUBSET = r"""
import importlib.util, os, sys, tempfile, shutil
spec = importlib.util.spec_from_file_location("fm_selftest", sys.argv[1])
st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st)
idx = [int(x) for x in sys.argv[3].split(",")]
tmp = tempfile.mkdtemp(prefix="fm-runner-selftest-", dir=os.environ["TMPDIR"])
try:
    open(os.path.join(tmp, "driver.py"), "w").write(st.DRIVER)
    s = st.Suite(tmp, os.path.realpath(sys.argv[2]))
    cases = st.skeleton(s)
    results = [cases[i]() for i in idx]
    os.write(1, ("自测（子集 %s）：%d/%d 通过\n" % (sys.argv[3], sum(results), len(results))).encode())
finally:
    shutil.rmtree(tmp, ignore_errors=True)
"""
for spec in (sys.argv[1:] or list(MUTANTS)):
    name, _, subset = spec.partition(":")
    root = os.path.join(WORK, "mut-" + name)
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(os.path.join(SRC, "formal_math"), os.path.join(root, "formal_math"),
                    ignore=shutil.ignore_patterns(".lake", "__pycache__", "must_red", "must_green", "must_unknown", "report_cases"))
    for rel, old, new in MUTANTS[name]:
        p = os.path.join(root, "formal_math", rel)
        s = open(p).read()
        assert s.count(old) == 1, (name, rel, s.count(old))
        open(p, "w").write(s.replace(old, new))
    selftest = os.path.join(root, "formal_math/verification/runner/selftest.py")
    if subset:
        drv = os.path.join(root, "subset.py")
        open(drv, "w").write(SUBSET)
        cmd = [sys.executable, "-I", drv, selftest, PACKAGES, subset]
    else:
        cmd = [sys.executable, "-I", selftest, "--packages", PACKAGES, "--skip-corpus", "--jobs", "4"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    failed = [l.split("\t")[1][:60] for l in p.stdout.splitlines() if l.startswith("失败")]
    last = (p.stdout.strip().splitlines() or ["(无输出) " + p.stderr[-300:]])[-1]
    print("%-34s rc=%d %s 失败用例=%s" % (spec, p.returncode, last, failed or "无"), flush=True)
    shutil.rmtree(root, ignore_errors=True)
