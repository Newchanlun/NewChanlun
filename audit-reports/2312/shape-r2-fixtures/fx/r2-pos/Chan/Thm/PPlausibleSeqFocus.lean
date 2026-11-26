module

public import Mathlib.Tactic.Common

public section

theorem t (n : Nat) : n = n ∧ n = n := by
  constructor <;> plausible (config := { numInst := 5 })
