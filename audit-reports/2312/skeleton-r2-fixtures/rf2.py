#!/usr/bin/env python3
"""#2312 骨架独审 r2 的夹具驱动。复用被审提交 runner/selftest.py 的 Repo、template。
默认用 lite 基线（清单里没有依赖包）配临时目录里自建的空假依赖目录，不碰共享依赖目录。
环境变量：RF_SRC 被审检出（含 formal_math/），RF_WORK 工作根目录，RF_ERR 打印的标准错误尾部字节数。"""
import importlib.util, os, re, shutil, subprocess, sys

SRC = os.environ.get("RF_SRC", "/home/workspace/.t3/worktrees/NewChanlun/t3-760e8d7e-916c880f85ebb77a")
WORK = os.environ.get("RF_WORK", "/home/workspace/fm/tmp/review-f2/work")
FAKE = os.path.join(WORK, "fake-packages")
RUN = os.path.join(SRC, "formal_math/verification/runner/run.py")
M = "module\n\npublic section\n\n"

spec = importlib.util.spec_from_file_location("fm_selftest", os.path.join(SRC, "formal_math/verification/runner/selftest.py"))
st = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st)

DRIVER = r'''
import importlib.util, sys, shutil
spec = importlib.util.spec_from_file_location("fm_run", sys.argv[1])
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
warm, start, argv = sys.argv[2], int(sys.argv[3]), sys.argv[4:]
steps = list(run.STEP_FUNCS)
if warm != "-":
    def w(ctx, real=steps[2]):
        shutil.copytree(warm, ctx.trusted_dir + "/verification/auditor/.lake", symlinks=True)
        return real(ctx)
    steps[2] = w
sys.exit(run.main(argv, steps=steps, start=start))
'''


def repo(name="repo"):
    path = os.path.join(WORK, name)
    os.makedirs(FAKE, exist_ok=True)
    if os.path.isdir(path):
        r = st.Repo.__new__(st.Repo)
        r.path = path
        return r
    return st.Repo(path)


def lite(r, **kw):
    files = st.template(lite=True, **kw)
    return r.commit(files), files


def warm_dir():
    """预编译的审计程序产物（源码与被审提交逐字相同），只为省第 3 步的时间。"""
    pkg = os.path.join(WORK, "warm-auditor")
    if not os.path.isfile(os.path.join(pkg, ".lake", "build", "bin", "fm_audit")):
        shutil.rmtree(pkg, ignore_errors=True)
        shutil.copytree(os.path.join(SRC, "formal_math/verification/auditor"), pkg, ignore=shutil.ignore_patterns(".lake"))
        prefix = subprocess.run(["lean", "--print-prefix"], cwd=pkg, capture_output=True, text=True).stdout.strip()
        b = subprocess.run([os.path.join(prefix, "bin", "lake"), "build"], cwd=pkg, capture_output=True)
        assert b.returncode == 0, b.stdout
    return os.path.join(pkg, ".lake")


def fresh(name):
    work = os.path.join(WORK, "w-" + re.sub(r"[^A-Za-z0-9_-]", "_", name))
    if os.path.lexists(work):
        subprocess.run(["chmod", "-R", "u+rwX", work])
        shutil.rmtree(work)
    return work


def command(name, r, head, base, branch="proof/review", extra=(), warm=True, start=1, runpy=None, packages=None,
            workdir=None):
    work = workdir or fresh(name)
    argv = ["--repo", r.path, "--base", base, "--head", head, "--branch", branch, "--workdir", work,
            "--packages", packages or FAKE, *extra]
    rp = runpy or RUN
    if warm or start != 1:
        drv = os.path.join(WORK, "driver.py")
        with open(drv, "w") as f:
            f.write(DRIVER)
        return [sys.executable, "-I", drv, rp, warm_dir() if warm else "-", str(start), *argv], work
    return [sys.executable, "-I", rp, *argv], work


def show(name, cmd, p, full_err=False):
    out, err = p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    tail = err if full_err else err[-int(os.environ.get("RF_ERR", "1200")):]
    print("=== %s\n$ %s\nrc=%d\n--- stdout\n%s--- stderr%s\n%s" % (
        name, " ".join(map(str, cmd)), p.returncode, out, "" if full_err else "(tail)", tail))
    sys.stdout.flush()
    return out, err


def run(name, r, head, base, full_err=False, env=None, **kw):
    cmd, work = command(name, r, head, base, **kw)
    p = subprocess.run(cmd, capture_output=True,
                       env=env or {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/")})
    out, err = show(name, cmd, p, full_err)
    res = st.parse_result(p)
    res["work"] = work
    problem = st.protocol(res)
    print("--- 被审提交自己的 protocol() 核对：%s\n" % (problem or "合规"))
    sys.stdout.flush()
    res["protocol"] = problem
    return res
