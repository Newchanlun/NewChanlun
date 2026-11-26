module

public import Batteries.Tactic.Congr

public section

theorem probe (f : Nat → Nat) (a b : Nat) (h : a = b) : f a = f b := by
  congr (config := { closePost := (dbgTrace "FM-R2-CONGR-RAN" fun _ => true) }) 1
