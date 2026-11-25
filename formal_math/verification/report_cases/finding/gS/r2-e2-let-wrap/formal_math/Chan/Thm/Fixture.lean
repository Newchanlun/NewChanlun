module
public section
theorem claim : let _ : Nat := 0; ∀ (x : Nat), x = 0 → x = 1 → False := fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
