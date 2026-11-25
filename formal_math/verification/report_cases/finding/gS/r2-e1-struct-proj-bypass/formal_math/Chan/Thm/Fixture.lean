module
@[expose] public section
structure StmtBox where
  prop : Prop
def mirrorBox : StmtBox := ⟨∀ (P : Nat → Prop), (∀ x, P x) → ∀ x, P x⟩
def bspBox : StmtBox := ⟨∀ (d lvl side : Nat) (_hdiv : d > 0), ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side⟩
class VacClass where
  prop : Prop
instance : VacClass := ⟨∀ (x : Nat), x = 0 → x = 1 → False⟩
def pairStmt : Prop × Prop := (∀ (x : Nat), x = 0 → x = 1 → False, True)
end
public section
theorem wrapped_mirror : mirrorBox.prop := fun _ h x => h x
theorem wrapped_bsp : bspBox.prop := fun _ lvl side _ => ⟨(lvl, side), rfl, rfl⟩
theorem wrapped_vac_class : VacClass.prop := fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
theorem wrapped_vac_pair : pairStmt.1 := fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
