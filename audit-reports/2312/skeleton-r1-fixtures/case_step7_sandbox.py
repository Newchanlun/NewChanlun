"""第 4、7 步沙箱的挂载表核对：用 run.py 自己的 sandbox() 与各步的挂载清单（逐字照抄 step_headers / step_env），
在里面跑 /bin/sh 探针（不调用 lean/lake）。工作目录复用 case_green 留下的 w-green。"""
import importlib.util, os, subprocess, sys
import rf
spec = importlib.util.spec_from_file_location("fm_run", rf.RUN)
run = importlib.util.module_from_spec(spec); spec.loader.exec_module(run)
ctx = run.Run()
ctx.workdir = os.path.join(rf.WORK, "w-green")
ctx.trusted_dir, ctx.audited, ctx.packages = ctx.workdir + "/trusted", ctx.workdir + "/audited", rf.PACKAGES
ctx.prefix = os.path.realpath(subprocess.run(["lean", "--print-prefix"], capture_output=True, text=True, cwd=ctx.audited).stdout.strip())
probe = r'''
for d in "$A" "$A/Chan" "$A/.lake" "$A/.lake/build/lib/lean" "$T" "$T/verification/auditor/.lake/build/bin" "$P" "$P/mathlib" "$W" /tmp /home /home/workspace "$X"; do
  if (echo x > "$d/rf-probe7") 2>/dev/null; then echo "WRITABLE $d"; rm -f "$d/rf-probe7"; elif [ -e "$d" ]; then echo "只读     $d"; else echo "不存在   $d"; fi
done
echo "env: $(env | sort | tr '\n' ' ')"
(timeout 2 bash -c 'exec 3<>/dev/tcp/1.1.1.1/53 && echo NET-OPEN' 2>/dev/null || echo NET-CLOSED)
ls "$W"
'''
def go(label, binds, env):
    e = {**env, "A": ctx.audited, "T": ctx.trusted_dir, "P": ctx.packages, "W": ctx.workdir, "X": ctx.prefix}
    p = run.sandbox(ctx, ["/bin/sh", "-c", probe], binds, e, ctx.audited, 60, "X", subprocess.PIPE)
    print("=== %s rc=%d\n%s" % (label, p.returncode, p.stdout.decode()))
go("第 4 步挂载", [("--ro-bind", ctx.audited, ctx.audited), ("--ro-bind", ctx.trusted_dir, ctx.trusted_dir)], {})
go("第 7 步挂载", [("--ro-bind", ctx.audited, ctx.audited), ("--ro-bind", ctx.packages, ctx.packages),
                 ("--ro-bind", ctx.trusted_dir, ctx.trusted_dir)], {"LEAN_PATH": "x", "LEAN_SYSROOT": ctx.prefix})
