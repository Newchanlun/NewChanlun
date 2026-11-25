module

public section

theorem claim (x y : Nat) (hx : x = 0) (hy : y = 0) : x + y = 0 := by
  rw [hx, hy]
