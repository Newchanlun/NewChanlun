module

public import Mathlib.Basic.ExistsUnique

@[expose] public section

abbrev MyEU := @ExistsUnique Nat

end
public section

theorem andTrue (f : Nat → Nat) (x : Nat) : ExistsUnique (fun y => y = f x ∧ True) :=
  ⟨f x, ⟨rfl, trivial⟩, fun _ h => h.1⟩

theorem wrapped (f : Nat → Nat) (x : Nat) : MyEU (fun y => y = f x) :=
  ⟨f x, rfl, fun _ h => h⟩

theorem idWrapped (f : Nat → Nat) (x : Nat) : ExistsUnique (fun y => id y = f x) :=
  ⟨f x, rfl, fun _ h => h⟩

theorem manual (f : Nat → Nat) (x : Nat) :
    ∃ y, y = f x ∧ ∀ z, z = f x → z = y :=
  ⟨f x, rfl, fun _ h => h⟩
