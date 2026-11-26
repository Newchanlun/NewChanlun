module

public import Mathlib.Tactic.Common

public section

/-! 探针：只做纯计算（dbgTrace 打标记）的 Aesop 规则战术，看被审声明是否在构建期被求值。 -/

def fmRule : Lean.Elab.Tactic.TacticM Unit :=
  dbgTrace "FM-AESOP-RULE-RAN" fun _ => pure ()

theorem probe : True := by
  aesop (add safe tactic fmRule)
