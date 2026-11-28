module
public section
theorem bsp_sub_beta (d lvl side : Nat) (_hdiv : d > 0) :
    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=
  ⟨(lvl, side), (fun _ => rfl) _hdiv, rfl⟩
