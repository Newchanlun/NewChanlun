module

import Mathlib.Tactic.Common

public section

/-- 探针 E2：Aesop 规则战术按名字对被审声明求值（声明体只打纯代码标记）。 -/
def fmTac : Lean.Elab.Tactic.TacticM Unit :=
  dbgTrace "FM-E2-MARK" fun _ => pure ()

theorem e2 : True := by
  aesop (add safe tactic fmTac)
