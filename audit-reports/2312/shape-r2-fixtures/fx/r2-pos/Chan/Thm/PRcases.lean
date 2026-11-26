module

public import Mathlib.Tactic.Common

public section

theorem t (h : True ∨ True) : True := by
  rcases h with _ | _
  · aesop (config := {})
  · trivial
