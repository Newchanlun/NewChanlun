#!/usr/bin/env python3
"""r3：第 6 步挂载布局下硬链接的确切 errno。用被审 run.py 自己的 sandbox()，不跑 lean。
用法：python3 -I case_hardlink_exact.py <run.py> <工作根>"""
import importlib.util, os, shutil, sys
spec = importlib.util.spec_from_file_location("fm_run", sys.argv[1])
run = importlib.util.module_from_spec(spec); spec.loader.exec_module(run)
root = sys.argv[2]
work = os.path.join(root, "hardlink-exact")
if os.path.lexists(work):
    os.system("chmod -R u+rwX %s" % work); shutil.rmtree(work)
ctx = run.Run(); ctx.workdir, ctx.prefix = work, "/usr"
ctx.audited = os.path.join(work, "audited"); ctx.modules = ["Chan.A"]
lake = os.path.join(ctx.audited, ".lake")
os.makedirs(os.path.join(lake, "packages")); os.makedirs(os.path.join(lake, "build/lib/lean/Chan"))
os.makedirs(os.path.join(ctx.audited, "Chan"))
open(os.path.join(ctx.audited, "Chan", "A.lean"), "w").write("module\n")
open(os.path.join(lake, "build/lib/lean/Chan/A.olean"), "w").write("x")
host = os.path.join(root, "hl-canary"); open(host, "w").write("ORIG\n"); os.chmod(host, 0o666)
PROBE = r'''
py() { python3 -c "$@"; }
for src in /etc/hostname /usr/bin/env Chan/A.lean .lake/build/lib/lean/Chan/A.olean HOSTC; do
  python3 - "$src" <<'PY'
import os, sys
src = sys.argv[1]
dst = ".lake/build/lib/lean/Chan/A.trace"
try:
    os.unlink(dst)
except OSError:
    pass
try:
    os.link(src, dst, follow_symlinks=False)
    print("link %-44s 成功 nlink=%d" % (src, os.lstat(dst).st_nlink))
except OSError as e:
    print("link %-44s %s errno=%d" % (src, e.strerror, e.errno))
PY
done
python3 -c "import os;print('CapEff', open('/proc/self/status').read().split('CapEff:')[1].split()[0])"
findmnt -o TARGET,FSTYPE,OPTIONS 2>/dev/null | head -20
'''.replace("HOSTC", host)
binds = [("--ro-bind", ctx.audited, ctx.audited), ("--bind", lake, lake)]
p = run.sandbox(ctx, ["/bin/sh", "-c", PROBE], binds, {}, ctx.audited, 60, "P", "p")
print(p.stdout.decode("utf-8", "replace"))
print("宿主机金丝雀 = %r；被审源码 = %r" % (open(host).read(), open(os.path.join(ctx.audited, "Chan", "A.lean")).read()))
