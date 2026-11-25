module
public section
theorem claim : True ∧ (∀ (x : Nat), x = 0 → x = 1 → False) := ⟨trivial, fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩
