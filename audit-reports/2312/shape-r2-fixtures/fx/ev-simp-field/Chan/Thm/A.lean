module

public import Mathlib.Tactic.Common

public section

theorem probe (a : Nat) : a + 0 = a := by
  simp (config := { maxSteps := (dbgTrace "FM-R2-SIMP-FIELD-RAN" fun _ => 100000) })
