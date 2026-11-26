module

public import Mathlib.Tactic.Common
public import Lean.CoreM

public section

/-! 探针：按编译器建议补上 `import Lean.CoreM`，看第 4 步头部规则是否拦住。 -/

def fmRule : Lean.Elab.Tactic.TacticM Unit := do
  IO.FS.writeFile ".lake/fm-aesop-probe.txt" "ran"
  pure ()

theorem probe : True := by
  aesop (add safe tactic fmRule)
