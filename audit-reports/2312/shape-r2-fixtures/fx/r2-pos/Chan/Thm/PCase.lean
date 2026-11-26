module

public import Mathlib.Tactic.Common

public section

theorem t : True ∧ True := by
  constructor
  case left => aesop (config := {})
  next => aesop (simp_config := {})
