module

public import Mathlib.Tactic.Common

public section

/-! 甲-1 证据：plausible 的旧式 `(config := …)` 明文出现，第 5 步零命中。 -/

theorem probe (n : Nat) : n = n := by
  plausible (config := { numInst := 5 })
