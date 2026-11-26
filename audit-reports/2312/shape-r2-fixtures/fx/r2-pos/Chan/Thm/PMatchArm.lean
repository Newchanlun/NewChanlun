module

public import Mathlib.Tactic.Common

public section

theorem t (n : Nat) : True :=
  match n with
  | 0 => by aesop (config := {})
  | _ + 1 => trivial
