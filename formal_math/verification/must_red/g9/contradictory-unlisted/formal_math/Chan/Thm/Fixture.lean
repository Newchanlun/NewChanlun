module

public section

theorem claim (x : Nat) (h0 : x = 0) (h1 : x = 1) : False := Nat.noConfusion (h0.symm.trans h1)
