module

public import Mathlib.Basic.ExistsUnique

public section

theorem graph (f : Nat → Nat) (x : Nat) : ExistsUnique (fun y => f x = y) :=
  ⟨f x, rfl, fun _ h => h.symm⟩
