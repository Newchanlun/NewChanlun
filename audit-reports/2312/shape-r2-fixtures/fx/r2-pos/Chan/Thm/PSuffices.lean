module

public import Mathlib.Tactic.Common

public section

theorem t : True := by
  suffices h : True from h
  aesop (config := {})
