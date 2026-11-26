module

public import Mathlib.Tactic.Common

public section

/-! 甲-1 证据：旧式 `(config := …)` 明文出现，七步全绿。 -/

theorem probe : True := by
  aesop (config := { maxRuleApplications := 200, warnOnNonterminal := false })
