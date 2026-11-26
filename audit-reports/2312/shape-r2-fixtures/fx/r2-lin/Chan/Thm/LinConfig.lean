module

public import Mathlib.Tactic.Linarith

public section

theorem t (a b : Nat) (h : a < b) : a ≤ b := by
  linarith (config := {})
