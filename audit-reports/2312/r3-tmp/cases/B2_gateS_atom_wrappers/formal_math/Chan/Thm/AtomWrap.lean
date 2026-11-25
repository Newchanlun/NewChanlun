module
public section
inductive WrapInd (P : Prop) : Prop where
  | mk : P → WrapInd P

structure WrapBox (n : Nat) : Prop where
  claim : n = 0 → n = 1 → False

theorem vac_eq : (∀ x : Nat, x = 0 → x = 1 → False) = True :=
  propext ⟨fun _ => trivial, fun _ _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem vac_heq : HEq (∀ x : Nat, x = 0 → x = 1 → False) True :=
  heq_of_eq vac_eq

theorem vac_nonempty : Nonempty (∀ x : Nat, x = 0 → x = 1 → False) :=
  ⟨fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem vac_sub : Nonempty { _u : Unit // ∀ x : Nat, x = 0 → x = 1 → False } :=
  ⟨⟨(), fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩⟩

theorem vac_dec : decide (∀ x : Fin 5, x.val = 0 → x.val = 1 → False) = true := by
  decide

theorem vac_ind : WrapInd (∀ x : Nat, x = 0 → x = 1 → False) :=
  ⟨fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem vac_box (n : Nat) : WrapBox n :=
  ⟨fun h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem vac_hidden_getd : Option.getD (some (∀ x : Nat, x = 0 → x = 1 → False)) True = True :=
  propext ⟨fun _ => trivial, fun _ _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem vac_fvar (W : Prop → Prop) (h : W = id) : W (∀ x : Nat, x = 0 → x = 1 → False) :=
  h ▸ (fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1))

theorem vac_iff_var (P : Prop) (h : P ↔ (∀ x : Nat, x = 0 → x = 1 → False)) : P :=
  h.mpr (fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1))
