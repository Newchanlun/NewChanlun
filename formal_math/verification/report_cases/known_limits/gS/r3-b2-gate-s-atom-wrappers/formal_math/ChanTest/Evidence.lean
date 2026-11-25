module
public import Chan.Thm.AtomWrap
public section
theorem vac_eq.witness : True := trivial
theorem vac_heq.witness : True := trivial
theorem vac_nonempty.witness : True := trivial
theorem vac_sub.witness : True := trivial
theorem vac_dec.witness : True := trivial
theorem vac_ind.witness : True := trivial
theorem vac_box.witness : ∃ _n : Nat, True := ⟨0, trivial⟩
theorem vac_hidden_getd.witness : True := trivial
theorem vac_fvar.witness : ∃ W : Prop → Prop, W = id := ⟨id, rfl⟩
theorem vac_fvar.without_1 : ∃ W : Prop → Prop, ¬ W (∀ x : Nat, x = 0 → x = 1 → False) := ⟨fun _ => False, id⟩
theorem vac_iff_var.witness : ∃ P : Prop, P ↔ (∀ x : Nat, x = 0 → x = 1 → False) := ⟨_, Iff.rfl⟩
theorem vac_iff_var.without_1 : ∃ P : Prop, ¬ P := ⟨False, id⟩
