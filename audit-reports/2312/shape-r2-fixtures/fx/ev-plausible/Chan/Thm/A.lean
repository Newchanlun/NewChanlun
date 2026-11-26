module

public import Mathlib.Tactic.Common

public section

theorem probe (n : Nat) : n = n := by
  plausible (config := { numInst := (dbgTrace "FM-R2-PLAUSIBLE-RAN" fun _ => 5) })
