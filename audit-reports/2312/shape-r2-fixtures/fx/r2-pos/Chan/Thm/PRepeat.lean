module

public import Mathlib.Tactic.Common

public section

theorem t : True := by
  repeat aesop (config := {})
