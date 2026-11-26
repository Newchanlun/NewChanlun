module

public import Mathlib.Tactic.Common

public section

theorem t : True := by
  aesop (X.config := {})
