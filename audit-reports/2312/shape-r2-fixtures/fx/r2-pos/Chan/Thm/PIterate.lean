module

public import Mathlib.Tactic.Common

public section

theorem t : True := by
  iterate 2 aesop (config := {})
