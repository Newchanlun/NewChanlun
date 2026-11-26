module

public import Mathlib.Tactic.Simps.Basic

public section

structure P where
  a : Nat

@[simps +native]
def p : P := ⟨1⟩
