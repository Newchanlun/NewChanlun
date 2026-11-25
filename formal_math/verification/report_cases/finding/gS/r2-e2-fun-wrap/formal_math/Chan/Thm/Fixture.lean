module
public section
theorem claim : (fun _ : Nat => ∀ (x : Nat), x = 0 → x = 1 → False) 0 := fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
