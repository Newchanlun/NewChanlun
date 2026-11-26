module

public import Mathlib.Tactic.Common

public section

theorem t : True := by
  aesop (config := /- 取值前 -/ { maxRuleApplications := 1 } /- 取值后 -/)
