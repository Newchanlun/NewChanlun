module

public import Mathlib.Tactic.Common

public section

theorem t : True := by
  aesop (config := {}) (simp_config := {})
