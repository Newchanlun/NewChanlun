module

public import Mathlib.Tactic.Common

public section

theorem t : True := by
  aesop (add norm simp Nat.add_zero) (config := {})
