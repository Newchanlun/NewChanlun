#!/usr/bin/env python3
"""r3：沙箱里哪些地方可写，写进去的东西会不会出现在宿主机上。用被审 run.py 自己的 sandbox()。"""
import importlib.util, os, shutil, sys
spec = importlib.util.spec_from_file_location("fm_run", sys.argv[1])
run = importlib.util.module_from_spec(spec); spec.loader.exec_module(run)
root = sys.argv[2]; work = os.path.join(root, "shm")
if os.path.lexists(work):
    os.system("chmod -R u+rwX " + work); shutil.rmtree(work)
ctx = run.Run(); ctx.workdir, ctx.prefix = work, "/usr"
ctx.audited = os.path.join(work, "audited"); ctx.modules = ["Chan.A"]
lake = os.path.join(ctx.audited, ".lake")
os.makedirs(os.path.join(lake, "packages")); os.makedirs(os.path.join(lake, "build/lib/lean/Chan"))
open(os.path.join(lake, "build/lib/lean/Chan/A.olean"), "w").write("x")
PROBE = r'''
for d in /dev/shm /tmp /tmp/home /dev /proc /var /run /home /root /etc /usr .lake; do
  if (echo probe > "$d/fm-write-probe") 2>/dev/null; then echo "可写 $d"; else echo "不可写 $d"; fi
done
echo "--- /dev/shm 列表"; ls -A /dev/shm 2>&1 | head -5
echo "--- /dev/shm 挂载"; findmnt -o TARGET,FSTYPE,OPTIONS /dev/shm 2>/dev/null | tail -2
'''
binds = [("--ro-bind", ctx.audited, ctx.audited), ("--bind", lake, lake)]
p = run.sandbox(ctx, ["/bin/sh", "-c", PROBE], binds, {}, ctx.audited, 60, "P", "p")
print(p.stdout.decode("utf-8", "replace"))
print("宿主机 /dev/shm/fm-write-probe 存在=%s" % os.path.exists("/dev/shm/fm-write-probe"))
print("宿主机 /tmp/fm-write-probe 存在=%s" % os.path.exists("/tmp/fm-write-probe"))
print("宿主机 .lake/fm-write-probe 存在=%s（沙箱里 .lake 可写，这个应为 True）"
      % os.path.exists(os.path.join(lake, "fm-write-probe")))
