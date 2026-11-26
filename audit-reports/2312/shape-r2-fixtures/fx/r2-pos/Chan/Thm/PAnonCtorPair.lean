module

public import Mathlib.Tactic.Common

public section

theorem t : True ∧ True := ⟨by aesop (config := {}), by aesop (simp_config := {})⟩
