module
public import Mathlib.Basic.ExistsUnique
@[expose] public section
def AliasNat := Nat
end
public section
theorem eu_eq_zero (f : Nat → Nat) (x : Nat) :
    ExistsUnique (fun y => y = f x ∧ 0 = 0) :=
  ⟨f x, ⟨rfl, rfl⟩, fun _ h => h.1⟩
theorem eu_dup (f : Nat → Nat) (x : Nat) :
    ExistsUnique (fun y => y = f x ∧ y = f x) :=
  ⟨f x, ⟨rfl, rfl⟩, fun _ h => h.1⟩
theorem eu_manual_rev (f : Nat → Nat) (x : Nat) :
    ∃ y, (∀ z, z = f x → z = y) ∧ y = f x :=
  ⟨f x, fun _ h => h, rfl⟩
theorem eu_manual_id (f : Nat → Nat) (x : Nat) :
    ∃ y, y = f x ∧ ∀ z, z = f x → id z = y :=
  ⟨f x, rfl, fun _ h => h⟩
theorem eu_pair (f : Nat → Nat) (x : Nat) :
    ExistsUnique (fun y => (y, ()) = (f x, ())) :=
  ⟨f x, rfl, fun _ h => congrArg Prod.fst h⟩
theorem alias_mirror (P : Nat → Prop) (x : AliasNat) (h : ∀ n : Nat, P n) : P x := h x
theorem conj_mirror (P : Nat → Prop) (h : (∀ n, P n) ∧ True) (x : Nat) : P x := h.1 x
