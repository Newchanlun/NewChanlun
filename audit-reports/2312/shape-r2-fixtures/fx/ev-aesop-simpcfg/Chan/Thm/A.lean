module

public import Mathlib.Tactic.Common

public section

theorem probe : True := by
  aesop (simp_config := { maxSteps := (dbgTrace "FM-R2-AESOP-SIMPCFG-RAN" fun _ => 100000) })
