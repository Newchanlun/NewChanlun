module

public import Mathlib.Tactic.Common

public section

theorem t : True := by
  first | (aesop (simp_config := {}); done) | trivial
