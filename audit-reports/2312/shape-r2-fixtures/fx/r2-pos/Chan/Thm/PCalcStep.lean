module

public import Mathlib.Tactic.Common

public section

theorem t (a : Nat) : a = a := by
  calc a = a := by aesop (config := {})
    _ = a := by plausible (config := {})
