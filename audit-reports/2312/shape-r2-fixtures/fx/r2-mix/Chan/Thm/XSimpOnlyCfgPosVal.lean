module


public section

theorem t (a : Nat) : a + 0 = a := by
  simp +arith (maxSteps := 5) (config := {}) -zeta only [Nat.add_zero]
