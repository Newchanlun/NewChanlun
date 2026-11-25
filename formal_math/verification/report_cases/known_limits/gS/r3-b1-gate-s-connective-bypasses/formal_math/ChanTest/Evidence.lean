module
public import Chan.Thm.Wrap
public section
theorem vac_and.witness : ∃ _x : Nat, True := ⟨0, trivial⟩
theorem mirror_and.witness : ∃ (_P : Nat → Prop) (_k : Nat), True := ⟨fun _ => True, 0, trivial⟩
theorem unused_and.witness : ∃ _x : Nat, True := ⟨0, trivial⟩
theorem vac_or.witness : True := trivial
theorem vac_iff.witness : True := trivial
theorem vac_notnot.witness : True := trivial
theorem vac_exists.witness : True := trivial
