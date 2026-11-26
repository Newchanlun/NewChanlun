module

public import Mathlib.Tactic.NormNum.Basic

public section

theorem t : (2 : Nat) + 2 = 4 := by
  norm_num (config := {})
