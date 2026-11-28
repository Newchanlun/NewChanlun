module
public section
theorem bsp_and_left (d lvl side : Nat) (_hdiv : d > 0) :
    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=
  ⟨(lvl, side), And.left ⟨rfl, _hdiv⟩, rfl⟩
