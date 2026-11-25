module
public section
theorem and_mirror : True ∧ (∀ (P : Nat → Prop), (∀ x, P x) → ∀ x, P x) :=
  ⟨trivial, fun _ h x => h x⟩
theorem and_bsp : True ∧ (∀ (d lvl side : Nat) (_hdiv : d > 0), ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side) :=
  ⟨trivial, fun _ lvl side _ => ⟨(lvl, side), rfl, rfl⟩⟩
