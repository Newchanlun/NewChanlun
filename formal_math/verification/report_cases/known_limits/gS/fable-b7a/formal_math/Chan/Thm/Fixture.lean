module

public import Mathlib.Basic.ExistsUnique

@[expose] public section

def AliasNat := Nat

end

public section

theorem m0 (P : Nat → Prop) (h : ∀ n : Nat, P n) (k : Nat) : P k := h k
theorem m1 (x : Nat) (h : x = 1 ∧ 0 = 0) : x = 1 := h.1
theorem m2 (x : Nat) (h : x = 1 ∧ x = 1) : x = 1 := h.1
theorem m3 (P : AliasNat → Prop) (h : ∀ n : AliasNat, P n) (k : Nat) : P k := h k
theorem m4 (P Q : Nat → Prop) (h : ∀ n : Nat, P n ∧ Q n) (k : Nat) : P k := (h k).1
theorem m5 (P : Nat → Prop) (h : ∀ p : Nat × Nat, P p.1) (k : Nat) : P k := h (k, 0)

theorem u0 (f : Nat → Nat) (x : Nat) : ∃! y, y = f x := ⟨f x, rfl, fun _ h => h⟩
theorem u1 (f : Nat → Nat) (x : Nat) : ∃ y, y = f x ∧ ∀ z, z = f x → id z = y :=
  ⟨f x, rfl, fun _ h => h⟩
theorem u2 (f : Nat → Nat) (x : Nat) : ∃ y, (∀ z, z = f x → z = y) ∧ y = f x :=
  ⟨f x, fun _ h => h, rfl⟩
theorem u3 (f : Nat → Nat) (x : Nat) : ∃! y, y = f x ∧ 0 = 0 :=
  ⟨f x, ⟨rfl, rfl⟩, fun _ h => h.1⟩
theorem u4 (f : Nat → Nat) (x : Nat) : ∃ y, y = f x ∧ ∀ z, z = f x → z = y :=
  ⟨f x, rfl, fun _ h => h⟩
