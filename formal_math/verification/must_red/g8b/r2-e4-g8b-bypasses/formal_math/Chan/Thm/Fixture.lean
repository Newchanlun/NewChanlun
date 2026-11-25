module
public section
private theorem mkEq {d lvl : Nat} (_ : d > 0) : lvl = lvl := rfl
theorem bsp_const (d lvl side : Nat) :
    d > 0 → ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=
  Function.const (d > 0) ⟨(lvl, side), rfl, rfl⟩
theorem bsp_have (d lvl side : Nat) (_hdiv : d > 0) :
    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side := by
  have _ := _hdiv
  exact ⟨(lvl, side), rfl, rfl⟩
theorem bsp_sub_beta (d lvl side : Nat) (_hdiv : d > 0) :
    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=
  ⟨(lvl, side), (fun _ => rfl) _hdiv, rfl⟩
theorem bsp_and_left (d lvl side : Nat) (_hdiv : d > 0) :
    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=
  ⟨(lvl, side), And.left ⟨rfl, _hdiv⟩, rfl⟩
theorem bsp_sub_helper (d lvl side : Nat) (_hdiv : d > 0) :
    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=
  ⟨(lvl, side), mkEq _hdiv, rfl⟩
