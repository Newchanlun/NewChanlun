module
public section
abbrev ContradictoryStmt : Prop := ∀ (x : Nat), x = 0 → x = 1 → False
theorem claim : ContradictoryStmt := fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
