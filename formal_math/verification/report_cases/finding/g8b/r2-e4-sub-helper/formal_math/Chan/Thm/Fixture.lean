module
public section
private theorem mkEq {d lvl : Nat} (_ : d > 0) : lvl = lvl := rfl
theorem bsp_sub_helper (d lvl side : Nat) (_hdiv : d > 0) :
    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=
  ⟨(lvl, side), mkEq _hdiv, rfl⟩
