module

public import Mathlib.Tactic.Common

public section

theorem t : True := aux
where
  aux : True := by aesop (config := {})
