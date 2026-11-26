module


public section

theorem t (a : Nat) : a + 0 = a := by
  simp -zeta (config := {}) [Nat.add_zero]
