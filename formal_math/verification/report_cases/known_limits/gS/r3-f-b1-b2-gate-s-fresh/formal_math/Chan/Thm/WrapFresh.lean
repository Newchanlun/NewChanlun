module
public section
inductive WrapInd (P : Prop) : Prop where
  | mk : P → WrapInd P

theorem vac_and (x : Nat) : (x = x) ∧ (x = 0 → x = 1 → False) :=
  ⟨rfl, fun h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem mirror_and (P : Nat → Prop) (k : Nat) : (k = k) ∧ ((∀ n, P n) → P k) :=
  ⟨rfl, fun h => h k⟩

theorem unused_and (x : Nat) : (x = x) ∧ (x = 0 → x + 0 = x) :=
  ⟨rfl, fun _ => rfl⟩

theorem vac_iff : True ↔ (∀ x : Nat, x = 0 → x = 1 → False) :=
  ⟨fun _ _ h0 h1 => Nat.noConfusion (h0.symm.trans h1), fun _ => trivial⟩

theorem vac_eq : (∀ x : Nat, x = 0 → x = 1 → False) = True :=
  propext ⟨fun _ => trivial, fun _ _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem vac_nonempty : Nonempty (∀ x : Nat, x = 0 → x = 1 → False) :=
  ⟨fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem vac_ind : WrapInd (∀ x : Nat, x = 0 → x = 1 → False) :=
  ⟨fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩
