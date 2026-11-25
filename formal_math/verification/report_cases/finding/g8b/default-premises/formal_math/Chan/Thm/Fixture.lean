module

public section

theorem defaultScan (d lvl side : Nat) (_hdiv : d > 0) :
    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side := ⟨(lvl, side), rfl, rfl⟩
