module
public section
theorem bsp_const (d lvl side : Nat) :
    d > 0 → ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=
  Function.const (d > 0) ⟨(lvl, side), rfl, rfl⟩
