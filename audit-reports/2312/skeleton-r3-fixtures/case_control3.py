#!/usr/bin/env python3
"""r3 回归抽查：被审提交自己的骨架用例里与送审主问题、B-1/B-2 有关的那些，作为对照跑一遍；
另加一项真实构建在 umask 0277 下会不会被目录模式规则误红。须包在 flock + guard.sh 里。"""
import os, re, subprocess, sys

SRC = "/home/workspace/.t3/worktrees/NewChanlun/t3-798198d0-7f46c36c7d707dbd"
PACKAGES = "/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages"
CASES = "S1,S3,S4,S5a,S5b,S5c,S5d,S5e,S7,S13,S16a,S16b,S17,S22,S27a,S27b,E1,E2,E3,E8,E10"
p = subprocess.run([sys.executable, "-I", os.path.join(SRC, "formal_math/verification/runner/selftest.py"),
                    "--packages", PACKAGES, "--skip-corpus", "--jobs", "4", "--cases", CASES],
                   capture_output=True)
out = p.stdout.decode(errors="replace")
print(out)
print("对照退出码 =", p.returncode)
sys.stdout.flush()

# umask 0277 下的真实构建：Lake 建的目录会是 0500，目录模式规则会不会误红
import importlib.util, shutil
spec = importlib.util.spec_from_file_location("fm_run", os.path.join(SRC, "formal_math/verification/runner/run.py"))
run = importlib.util.module_from_spec(spec); spec.loader.exec_module(run)
st_spec = importlib.util.spec_from_file_location("fm_st", os.path.join(SRC, "formal_math/verification/runner/selftest.py"))
st = importlib.util.module_from_spec(st_spec); st_spec.loader.exec_module(st)
OUT = os.path.join(os.environ["TMPDIR"], "review-f3", "umask")
probe = os.path.join(OUT, "tc"); os.makedirs(probe, exist_ok=True)
TOOLCHAIN = open(os.path.join(SRC, "formal_math/lean-toolchain"), "rb").read()
open(os.path.join(probe, "lean-toolchain"), "wb").write(TOOLCHAIN)
PREFIX = subprocess.run(["lean", "--print-prefix"], cwd=probe, capture_output=True, text=True).stdout.strip()
LAKE = os.path.join(PREFIX, "bin", "lake")
for um in (0o022, 0o077, 0o277):
    d = os.path.join(OUT, "u%04o" % um)
    st.rmtree(d); os.makedirs(d)
    files = {"lean-toolchain": TOOLCHAIN, "lake-manifest.json": st.LITE_MANIFEST,
             "Chan.lean": b"module\n", "Chan/A.lean": b"module\n"}
    files["lakefile.toml"] = st.lakefile({"formal_math/" + k: v for k, v in files.items()}, require=False)
    for rel, data in files.items():
        full = os.path.join(d, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "wb").write(data)
    lake = os.path.join(d, ".lake")
    run.mkdir(lake, 0o755)                      # 与 run.py 一样显式建 .lake 并 chmod
    run.mkdir(os.path.join(lake, "packages"), 0o755)
    env = {"PATH": os.path.join(PREFIX, "bin") + ":/usr/bin:/bin", "HOME": os.path.join(d, "home"),
           "LANG": "C.UTF-8", "TMPDIR": os.environ["TMPDIR"]}
    os.makedirs(env["HOME"], exist_ok=True)
    b = subprocess.run([LAKE, "build", "--wfail"], cwd=d, capture_output=True, env=env,
                       preexec_fn=lambda um=um: os.umask(um))
    ctx = run.Run(); ctx.modules = ["Chan", "Chan.A"]
    reds = run.artifact_reds(ctx, lake)
    modes = {}
    for rel in ("build", "build/lib", "build/lib/lean", "build/lib/lean/Chan"):
        pth = os.path.join(lake, rel)
        modes[rel] = oct(os.lstat(pth).st_mode & 0o7777) if os.path.exists(pth) else "不存在"
    print("umask %04o：lake build 退 %d；Lake 建的目录模式 %s；形状表判定 %s"
          % (um, b.returncode, modes, [(c, p.replace("formal_math/.lake/", "")) for c, p, _ in reds] or "无红"))
    sys.stdout.flush()
    st.rmtree(d)
