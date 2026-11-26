module

public import Mathlib.Tactic.Common

public section

theorem t (a : Nat) : a + 0 = a := by
  simp (disch := aesop (config := {}))
