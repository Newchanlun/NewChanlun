module

public import Mathlib.Tactic.Linarith

public section

theorem probe (a b : Nat) (h : a < b) : a ≤ b := by
  linarith (oracle := (dbgTrace "FM-R2-LINARITH-ORACLE-RAN" fun _ => .simplexAlgorithmSparse))
