module

public import Mathlib.Tactic.Common

public section

theorem t (n : Nat) : n = n := by
  simp (config.zeta := false)
