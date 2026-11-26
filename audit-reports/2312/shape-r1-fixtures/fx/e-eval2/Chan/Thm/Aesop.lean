module

public import Mathlib.Tactic.Common

public section

/-!
探针：Aesop 规则战术按名字对被审声明求值（备忘 3.5 点到、附录 B 列为未核实）。
写入目标只落在第 6 步沙箱内可写的 `.lake`，用来看这条入口在构建期的能力边界。
-/

def fmRule : Lean.Elab.Tactic.TacticM Unit := do
  IO.FS.writeFile ".lake/fm-aesop-probe.txt" "ran"
  pure ()

theorem probe : True := by
  aesop (add safe tactic fmRule)
