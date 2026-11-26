module

public import Mathlib.Tactic.Common

public section

theorem t : True := by
  aesop (/- 块 -/ config /- 块 -/ := /- 块 -/ {})
