module

public import Mathlib.Tactic.Common

public section

theorem t (n : Nat) : n = n := by
  try plausible (config := { numInst := 5 })
  rfl
