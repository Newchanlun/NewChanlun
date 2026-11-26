"""第 4 步的挂载表探针（被审提交自测 S22 只探了第 6、7 步）：用被审 run.py 自己的 sandbox() 加第 4 步的挂载清单跑一段 shell。
只起 bwrap 与 /bin/sh；`lean --print-prefix` 用来定工具链路径。用法：python3 -I case_step4_sandbox.py <run.py> <工作根目录>"""
import importlib.util, os, shutil, subprocess, sys
spec = importlib.util.spec_from_file_location("fm_run", sys.argv[1])
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
root = os.path.join(sys.argv[2], "w-step4-probe")
shutil.rmtree(root, ignore_errors=True)
ctx = run.Run()
ctx.workdir = root
ctx.audited, ctx.trusted_dir = os.path.join(root, "audited"), os.path.join(root, "trusted")
for d in (ctx.audited, ctx.trusted_dir, os.path.join(root, "home"), os.path.join(root, "step1")):
    os.makedirs(d)
open(os.path.join(root, "step1", "canary"), "w").close()
open(os.path.join(ctx.audited, "Chan.lean"), "w").close()
ctx.prefix = os.path.realpath(subprocess.run(["lean", "--print-prefix"], capture_output=True, text=True,
                                               cwd=os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "..", "auditor")).stdout.strip())
os.environ["FM_CANARY"] = "leak"
PROBE = r'''
echo "NET:$(tail -n +3 /proc/net/dev | cut -d: -f1 | tr -d ' ' | sort | tr '\n' ,)"
echo "ENV:$(env | cut -d= -f1 | sort | tr '\n' ,)"
echo "PWD:$(pwd)"
for p in "$1/audited/x" "$1/trusted/x" "$1/x" /tmp/x /home/x /etc/x "$2/x" /dev/shm/x /usr/x; do
  if (echo x > "$p") 2>/dev/null; then echo "WROTE:$p"; else echo "RO:$p"; fi
done
for p in "$1/step1/canary" "$1/home" "$1/audited/Chan.lean" "$1/trusted" "$2/bin/lean" "$HOME/.elan/toolchains" /root /var/log /run/user; do
  test -e "$p" && echo "SEE:$p" || echo "HIDDEN:$p"
done
'''
binds = [("--ro-bind", ctx.audited, ctx.audited), ("--ro-bind", ctx.trusted_dir, ctx.trusted_dir)]   # 与 step_headers 相同
p = run.sandbox(ctx, ["/bin/sh", "-c", PROBE, "probe", root, ctx.prefix], binds, {}, ctx.audited, 60, "PROBE", "probe")
sys.stdout.write(p.stdout.decode())
print("宿主机上 /tmp/x、工作目录/x 是否被写出：", os.path.exists("/tmp/x"), os.path.exists(os.path.join(root, "x")))
shutil.rmtree(root)
