module

public import Mathlib.Tactic.Simps.Basic

public section

structure P where
  a : Nat
  b : Nat

@[simps -fullyApplied]
def p : P := ⟨1, 2⟩

@[simps (attr := simp) a]
def q : P := ⟨1, 2⟩
