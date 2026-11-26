module

public import Mathlib.Tactic.Common

public section

theorem t : True ∧ True := by
  constructor
  all_goals aesop (config := {})
