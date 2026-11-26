module

public import Mathlib.Tactic.Common

public section

theorem t : True ∧ True := by
  constructor
  · aesop (config := {})
  · trivial
