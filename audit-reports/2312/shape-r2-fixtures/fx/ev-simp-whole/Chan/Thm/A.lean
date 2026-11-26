module

public import Mathlib.Tactic.Common

public section

theorem probe (a : Nat) : a + 0 = a := by
  simp (config := (dbgTrace "FM-R2-SIMP-WHOLE-RAN" fun _ => {}))
