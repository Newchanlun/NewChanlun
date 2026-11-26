module

public import Mathlib.Tactic.Common

public section

theorem t (n : Nat) : True := by
  induction n with
  | zero => aesop (config := {})
  | succ _ _ => trivial
