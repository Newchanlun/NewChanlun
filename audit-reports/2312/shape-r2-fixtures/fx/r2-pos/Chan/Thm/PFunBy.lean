module

public import Mathlib.Tactic.Common

public section

theorem t : Nat → True := fun _ => by aesop (config := {})
