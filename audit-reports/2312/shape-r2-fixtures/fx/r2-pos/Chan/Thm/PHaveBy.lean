module

public import Mathlib.Tactic.Common

public section

theorem t : True := by
  have h : True := by aesop (simp_config := {})
  exact h
