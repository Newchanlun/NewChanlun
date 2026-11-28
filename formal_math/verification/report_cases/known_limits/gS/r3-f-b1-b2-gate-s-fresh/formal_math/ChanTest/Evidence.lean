module
public import Chan.Thm.WrapFresh
public section
theorem vac_and.witness : ∃ _x : Nat, True := ⟨0, trivial⟩
theorem mirror_and.witness : ∃ (_P : Nat → Prop) (_k : Nat), True := ⟨fun _ => True, 0, trivial⟩
theorem unused_and.witness : ∃ _x : Nat, True := ⟨0, trivial⟩
theorem vac_iff.witness : True := trivial
theorem vac_eq.witness : True := trivial
theorem vac_nonempty.witness : True := trivial
theorem vac_ind.witness : True := trivial
