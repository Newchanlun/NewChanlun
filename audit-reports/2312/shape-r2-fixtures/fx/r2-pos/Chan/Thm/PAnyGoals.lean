module

public import Mathlib.Tactic.Common

public section

theorem t : True ∧ True := by
  constructor
  any_goals aesop (simp_config := {})
