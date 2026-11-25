module
public section
theorem claim : have _ : True := trivial; ∀ (x : Nat), x = 0 → x = 1 → False := fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
