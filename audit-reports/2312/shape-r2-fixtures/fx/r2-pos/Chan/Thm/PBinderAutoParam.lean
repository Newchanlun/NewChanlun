module

public import Mathlib.Tactic.Common

public section

theorem t (h : True := by aesop (config := {})) : True := h
