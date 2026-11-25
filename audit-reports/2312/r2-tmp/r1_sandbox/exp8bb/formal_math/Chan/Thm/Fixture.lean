module
public section
private theorem helper (d lvl side : Nat) : d > 0 → ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=
  fun _ => ⟨(lvl, side), rfl, rfl⟩
theorem bsp_eta (d lvl side : Nat) (_hdiv : d > 0) :
    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=
  helper d lvl side _hdiv
theorem bsp_eta_true (d lvl side : Nat) :
    ∀ (_hdiv : d > 0), ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=
  helper d lvl side
theorem bsp_let (d lvl side : Nat) (_hdiv : d > 0) :
    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side := by
  let _ := _hdiv
  exact ⟨(lvl, side), rfl, rfl⟩
