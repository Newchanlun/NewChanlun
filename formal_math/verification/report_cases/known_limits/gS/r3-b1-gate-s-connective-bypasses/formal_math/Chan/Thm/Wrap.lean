module
public section
theorem vac_and (x : Nat) : (x = x) ∧ (x = 0 → x = 1 → False) :=
  ⟨rfl, fun h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem mirror_and (P : Nat → Prop) (k : Nat) : (k = k) ∧ ((∀ n, P n) → P k) :=
  ⟨rfl, fun h => h k⟩

theorem unused_and (x : Nat) : (x = x) ∧ (x = 0 → x + 0 = x) :=
  ⟨rfl, fun _ => rfl⟩

theorem vac_or : False ∨ (∀ x : Nat, x = 0 → x = 1 → False) :=
  Or.inr (fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1))

theorem vac_iff : True ↔ (∀ x : Nat, x = 0 → x = 1 → False) :=
  ⟨fun _ _ h0 h1 => Nat.noConfusion (h0.symm.trans h1), fun _ => trivial⟩

theorem vac_notnot : ¬ ¬ (∀ x : Nat, x = 0 → x = 1 → False) :=
  fun h => h (fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1))

theorem vac_exists : ∃ _ : Nat, ∀ x : Nat, x = 0 → x = 1 → False :=
  ⟨0, fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩
