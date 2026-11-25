module

public import Mathlib.Basic.ExistsUnique

public section

theorem eu_dup (f : Nat → Nat) (x : Nat) :
    ExistsUnique (fun y => y = f x ∧ y = f x) :=
  ⟨f x, ⟨rfl, rfl⟩, fun _ h => h.1⟩
