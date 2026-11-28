module

public import Mathlib.Tactic.Common

public section

/-! 甲-1 证据：点名禁用的旧式 `(config := …)` 以明文出现，第 5 步零命中，取值在构建期被求值。 -/

theorem probe : True := by
  aesop (config := { maxRuleApplications := (dbgTrace "FM-LEGACY-CONFIG-RAN" fun _ => 200) })
