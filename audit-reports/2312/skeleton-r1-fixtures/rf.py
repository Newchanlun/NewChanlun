#!/usr/bin/env python3
"""#2312 骨架/环境层搬家独审（r1）的夹具驱动。复用被审提交 runner/selftest.py 的 Repo/template。
用法见各 case_*.py；环境变量 RF_SRC 指向被审检出（含 formal_math/），RF_WORK 指向工作根目录。"""
import importlib.util, os, subprocess, sys, shutil, re

SRC = os.environ.get("RF_SRC", "/home/workspace/.t3/worktrees/NewChanlun/t3-279c6aca-c1e9a2095915fa5f")
WORK = os.environ.get("RF_WORK", "/home/workspace/fm/tmp/review-f/work")
PACKAGES = os.environ.get("RF_PACKAGES", "/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages")
RUN = os.path.join(SRC, "formal_math/verification/runner/run.py")

spec = importlib.util.spec_from_file_location("fm_selftest", os.path.join(SRC, "formal_math/verification/runner/selftest.py"))
st = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st)

DRIVER = r'''
import importlib.util, sys, shutil
spec = importlib.util.spec_from_file_location("fm_run", sys.argv[1])
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
warm, argv = sys.argv[2], sys.argv[3:]
steps = list(run.STEP_FUNCS)
def w(ctx, real=steps[2]):
    shutil.copytree(warm, ctx.trusted_dir + "/verification/auditor/.lake", symlinks=True)
    return real(ctx)
steps[2] = w
sys.exit(run.main(argv, steps=steps))
'''

def repo(name="repo"):
    path = os.path.join(WORK, name)
    if os.path.isdir(path):
        r = st.Repo.__new__(st.Repo); r.path = path
        return r
    os.makedirs(WORK, exist_ok=True)
    return st.Repo(path)

def warm_dir():
    """预编译的审计程序产物（源码与被审提交逐字相同），只为省第 3 步的时间；涉及第 3 步的用例不用它。"""
    pkg = os.path.join(WORK, "warm-auditor")
    if not os.path.isdir(os.path.join(pkg, ".lake", "build", "bin")):
        shutil.rmtree(pkg, ignore_errors=True)
        shutil.copytree(os.path.join(SRC, "formal_math/verification/auditor"), pkg, ignore=shutil.ignore_patterns(".lake"))
        prefix = subprocess.run(["lean", "--print-prefix"], cwd=pkg, capture_output=True, text=True).stdout.strip()
        b = subprocess.run([os.path.join(prefix, "bin", "lake"), "build"], cwd=pkg, capture_output=True)
        assert b.returncode == 0, b.stdout
    return os.path.join(pkg, ".lake")

_n = [0]
def run(name, r, head, base, branch="proof/review", extra=(), warm=True, keep=True, env=None, runpy=None, workdir=None, python_flags=("-I",)):
    work = workdir or os.path.join(WORK, "w-" + re.sub(r"[^A-Za-z0-9_-]", "_", name))
    if workdir is None and os.path.lexists(work):
        subprocess.run(["chmod", "-R", "u+rwX", work]); shutil.rmtree(work)
    argv = ["--repo", r.path, "--base", base, "--head", head, "--branch", branch, "--workdir", work, "--packages", PACKAGES, *extra]
    rp = runpy or RUN
    if warm:
        drv = os.path.join(WORK, "driver.py")
        open(drv, "w").write(DRIVER)
        cmd = [sys.executable, *python_flags, drv, rp, warm_dir(), *argv]
    else:
        cmd = [sys.executable, *python_flags, rp, *argv]
    p = subprocess.run(cmd, capture_output=True, env=env or {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/")})
    out, err = p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    print("=== %s\n$ %s\nrc=%d\n--- stdout\n%s--- stderr(tail)\n%s" % (name, " ".join(map(str, cmd)), p.returncode, out, err[-int(os.environ.get("RF_ERR", "1500")):]))
    sys.stdout.flush()
    return dict(rc=p.returncode, out=out, err=err, work=work)

def base_and_files(r):
    files = st.template()
    return r.commit(files), files
