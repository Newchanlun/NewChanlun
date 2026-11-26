module

public import Mathlib.Tactic.Common

public section

theorem t : True := by
  try aesop (config := {})
  trivial
