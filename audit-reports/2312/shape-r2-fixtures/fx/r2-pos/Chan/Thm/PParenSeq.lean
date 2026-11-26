module

public import Mathlib.Tactic.Common

public section

theorem t : True := by
  all_goals (try aesop (config := {}))
