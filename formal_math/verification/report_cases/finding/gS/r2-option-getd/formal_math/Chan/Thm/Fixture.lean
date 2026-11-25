module
public section
theorem mirror_getd : Option.getD (some (∀ (P : Nat → Prop), (∀ x, P x) → ∀ x, P x)) True :=
  fun _ h x => h x
theorem bsp_getd : Option.getD (some (∀ (d lvl side : Nat) (_hdiv : d > 0), ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side)) True :=
  fun _ lvl side _ => ⟨(lvl, side), rfl, rfl⟩
theorem vac_getd : Option.getD (some (∀ (x : Nat), x = 0 → x = 1 → False)) True :=
  fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
theorem vac_const : Function.const Unit (∀ (x : Nat), x = 0 → x = 1 → False) () :=
  fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
