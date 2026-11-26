module

public import Batteries.Tactic.Congr

public section

theorem t (f : Nat → Nat) (a b : Nat) (h : a = b) : f a = f b := by
  congr (
      config := {})
