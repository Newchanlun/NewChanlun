module

public import Mathlib.Tactic.Common

public section

theorem probe : True := by
  aesop (config := { maxRuleApplications := (dbgTrace "FM-R2-AESOP-RAN" fun _ => 200) })
