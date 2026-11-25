module
public import Mathlib.Basic.ExistsUnique
public section
abbrev MyEU := @ExistsUnique Nat
theorem eu_and_true (f : Nat → Nat) (x : Nat) :
    ExistsUnique (fun y => y = f x ∧ True) :=
  ⟨f x, ⟨rfl, trivial⟩, fun _ h => h.1⟩
theorem eu_abbrev (f : Nat → Nat) (x : Nat) :
    MyEU (fun y => y = f x) :=
  ⟨f x, rfl, fun _ h => h⟩
theorem eu_id (f : Nat → Nat) (x : Nat) :
    ExistsUnique (fun y => id y = f x) :=
  ⟨f x, rfl, fun _ h => h⟩
