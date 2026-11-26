#!/usr/bin/env python3
"""r3：核对 README「/home、/root、/run、/var、/tmp 与整个工作目录盖成空 tmpfs」在第 6、7 步的挂载下是否成立。
用被审 run.py 自己的 sandbox()，不跑 lean。"""
import importlib.util, os, shutil, sys
spec = importlib.util.spec_from_file_location("fm_run", sys.argv[1])
run = importlib.util.module_from_spec(spec); spec.loader.exec_module(run)
root = sys.argv[2]
work = os.path.join(root, "cover")
if os.path.lexists(work):
    os.system("chmod -R u+rwX %s" % work); shutil.rmtree(work)
ctx = run.Run(); ctx.workdir, ctx.prefix = work, "/usr"
ctx.audited = os.path.join(work, "audited"); ctx.packages = os.path.join(work, "pkgs")
ctx.trusted_dir = os.path.join(work, "trusted")
ctx.modules = ["Chan.A"]
lake = os.path.join(ctx.audited, ".lake")
for d in (os.path.join(lake, "packages"), os.path.join(lake, "build/lib/lean/Chan"), ctx.packages,
          ctx.trusted_dir, os.path.join(ctx.audited, "Chan")):
    os.makedirs(d)
open(os.path.join(lake, "build/lib/lean/Chan/A.olean"), "w").write("x")
open(os.path.join(ctx.trusted_dir, "secret-trusted"), "w").write("T\n")
# 工作目录里另放一个文件（README 说整个工作目录被盖住）
open(os.path.join(work, "workdir-canary"), "w").write("W\n")

PROBE = r'''
for d in /home /root /run /var /tmp /home/workspace /run/user /var/log /etc /opt /usr/share; do
  n=$(ls -A "$d" 2>/dev/null | wc -l)
  printf '%-18s 存在=%s 条目数=%s 前几项=%s\n' "$d" "$( [ -e "$d" ] && echo 是 || echo 否 )" "$n" "$(ls -A "$d" 2>/dev/null | head -4 | tr '\n' ,)"
done
echo "--- 具体文件"
for f in /etc/passwd /etc/shadow /etc/hostname /run/utmp /var/log/syslog WORKCANARY TRUSTEDFILE; do
  printf '%-40s 可读=%s\n' "$f" "$( [ -r "$f" ] && echo 是 || echo 否 )"
done
echo "--- 宿主机用户家目录"
printf 'HOME=%s 内容数=%s\n' "$HOME" "$(ls -A $HOME 2>/dev/null | wc -l)"
echo "--- findmnt 里 /run 一支"
findmnt -o TARGET,FSTYPE,OPTIONS /run 2>/dev/null
echo "--- /proc/self/mountinfo 里 /run、/home 的最后一条"
grep -E ' /run | /home | /var | /tmp ' /proc/self/mountinfo | tail -8
'''.replace("WORKCANARY", os.path.join(work, "workdir-canary")).replace("TRUSTEDFILE", os.path.join(ctx.trusted_dir, "secret-trusted"))

print("##### 第 6 步的挂载（被审工作区只读、.lake 可写、依赖只读挂到 .lake/packages，受信目录不挂）")
binds6 = [("--ro-bind", ctx.audited, ctx.audited), ("--bind", lake, lake),
          ("--ro-bind", ctx.packages, os.path.join(lake, "packages"))]
p = run.sandbox(ctx, ["/bin/sh", "-c", PROBE], binds6, {}, ctx.audited, 60, "P", "p")
print(p.stdout.decode("utf-8", "replace"))
print("##### 第 7 步的挂载（被审工作区、依赖、受信目录都只读）")
binds7 = [("--ro-bind", ctx.audited, ctx.audited), ("--ro-bind", ctx.packages, ctx.packages),
          ("--ro-bind", ctx.trusted_dir, ctx.trusted_dir)]
p = run.sandbox(ctx, ["/bin/sh", "-c", PROBE], binds7, {}, ctx.audited, 60, "P", "p")
print(p.stdout.decode("utf-8", "replace"))
