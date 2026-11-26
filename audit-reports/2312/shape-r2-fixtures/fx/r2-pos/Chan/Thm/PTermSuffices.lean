module

public import Mathlib.Tactic.Common

public section

theorem t : True :=
  suffices h : True from h
  by aesop (config := {})
