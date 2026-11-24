module

public section

theorem claim (x y : Nat) (hx : x = 0) (hy : y = 0) : x + y = 0 := by
  rw [hx, hy]

private theorem privateClaim (x : Nat) : x = x := rfl
