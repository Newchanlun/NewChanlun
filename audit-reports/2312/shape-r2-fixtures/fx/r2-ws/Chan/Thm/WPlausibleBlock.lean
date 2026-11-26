module

public import Mathlib.Tactic.Common

public section

theorem t (n : Nat) : n = n := by
  plausible (/- x -/config/- y -/:=/- z -/{ numInst := 5 })
