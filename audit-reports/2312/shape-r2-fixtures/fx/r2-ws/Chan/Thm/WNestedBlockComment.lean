module

public import Mathlib.Tactic.Common

public section

theorem t : True := by
  aesop (/- 外 /- 内 -/ 外 -/ simp_config := {})
