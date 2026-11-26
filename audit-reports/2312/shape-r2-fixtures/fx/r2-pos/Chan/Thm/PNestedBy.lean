module

public import Mathlib.Tactic.Common

public section

theorem t : True := by
  exact (by exact (by aesop (config := {})))
