module

public import Mathlib.Tactic.Simps.Basic

public section

structure P where
  a : Nat
  b : Nat

@[simps (config := { fullyApplied := false })]
def p : P := ⟨1, 2⟩
