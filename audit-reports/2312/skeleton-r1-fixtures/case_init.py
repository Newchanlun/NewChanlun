"""第 7 步读环境不执行被审模块的初始化器（带正对照）。
被审模块 ChanExplore/Sentinel.lean 带 `meta initialize`：它在任何导入者的精化期都会运行（模块制下非 meta 的 initialize
只在 meta import 时运行，头部规则不许，所以用 meta 版本才有正对照）。初始化器把进程名写到标准错误，并尝试在当前目录的
.lake/ 下落哨兵文件 rf-init-ran-<进程名>。
1) 流水线内：第 6 步构建 User（导入 Sentinel）时应看到 app=…/lean（正对照）；第 7 步不得出现 app=…/fm_audit。
2) 流水线外直跑：对同一批产物，在 .lake 可写的情况下直接执行受信审计二进制，哨兵 rf-init-ran-fm_audit 不得出现；
   再用一段 `importModules (loadExts := true)` 的对照程序读同一批产物，哨兵应出现（证明这批产物里的初始化器确实可被触发）。"""
import rf, os, subprocess, glob
r = rf.repo()
base, files = rf.base_and_files(r)
M = "module\n\npublic section\n\n"
sentinel = M + '''meta initialize
  let app ← IO.appPath
  let name := app.fileName.getD "unknown"
  IO.eprintln s!"RF-INIT-RAN app={app}"
  try IO.FS.writeFile s!".lake/rf-init-ran-{name}" "x" catch _ => pure ()
'''
legacy = M + '''initialize
  let app ← IO.appPath
  IO.eprintln s!"RF-PLAIN-INIT-RAN app={app}"
'''
head = r.commit({**files, "formal_math/ChanExplore/Sentinel.lean": sentinel.encode(),
                 "formal_math/ChanExplore/Plain.lean": legacy.encode(),
                 "formal_math/ChanExplore/User.lean": b"module\n\npublic import ChanExplore.Sentinel\npublic import ChanExplore.Plain\n"}, base)
res = rf.run("I1-init", r, head, base, warm=False)
print("标准错误里的初始化器行：")
for line in res["err"].splitlines():
    if "INIT-RAN" in line:
        print("   ", line[:200])
aud = os.path.join(res["work"], "audited")
print("第 6 步后 .lake 下的哨兵：", sorted(os.path.basename(p) for p in glob.glob(aud + "/.lake/rf-init-ran-*")))
for p in glob.glob(aud + "/.lake/rf-init-ran-*"):
    os.unlink(p)
# 2) 流水线外直跑受信审计二进制（.lake 可写）
binary = os.path.join(res["work"], "trusted/verification/auditor/.lake/build/bin/fm_audit")
prefix = subprocess.run(["lean", "--print-prefix"], capture_output=True, text=True, cwd=aud).stdout.strip()
mods = ["Chan", "Chan.Base", "ChanChallenge.Base", "ChanDyn.Base", "ChanExplore.Base", "ChanExplore.Plain", "ChanExplore.Sentinel", "ChanExplore.User", "ChanTest.Probe"]
env = {"PATH": prefix + "/bin:/usr/bin:/bin", "LEAN_PATH": aud + "/.lake/build/lib/lean", "LEAN_SYSROOT": prefix, "LANG": "C.UTF-8"}
p = subprocess.run([binary, "env", *mods], cwd=aud, env=env, capture_output=True, text=True)
print("直跑 fm_audit env：rc=%d\nstdout:\n%s\nstderr:\n%s" % (p.returncode, p.stdout, p.stderr[-600:]))
print("直跑后 .lake 下的哨兵：", sorted(os.path.basename(p) for p in glob.glob(aud + "/.lake/rf-init-ran-*")))
# 正对照：同一批产物，loadExts := true
ctl = os.path.join(rf.WORK, "init-control.lean")
open(ctl, "w").write('''import Lean
open Lean
unsafe def main : IO Unit := do
  initSearchPath (← findSysroot)
  enableInitializersExecution
  let _ ← importModules #[{module := `ChanExplore.User}] {} (loadExts := true)
  IO.println "control-done"
''')
p = subprocess.run(["lean", "--run", ctl], cwd=aud, env=env, capture_output=True, text=True)
print("正对照（lean --run，loadExts := true）：rc=%d stdout=%r\nstderr:\n%s" % (p.returncode, p.stdout, p.stderr[-600:]))
print("正对照后 .lake 下的哨兵：", sorted(os.path.basename(p) for p in glob.glob(aud + "/.lake/rf-init-ran-*")))
