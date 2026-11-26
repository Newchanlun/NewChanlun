module

public import Mathlib.Tactic.Common

public section

structure S where
  n : Nat
  ok : True := by aesop (config := {})
