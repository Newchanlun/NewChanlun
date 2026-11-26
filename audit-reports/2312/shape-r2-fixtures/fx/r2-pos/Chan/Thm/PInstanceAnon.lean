module

public import Mathlib.Tactic.Common

public section

instance : Inhabited True := ⟨by aesop (config := {})⟩
