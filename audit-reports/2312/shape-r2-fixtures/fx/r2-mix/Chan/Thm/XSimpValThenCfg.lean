module


public section

theorem t (a : Nat) : a + 0 = a := by
  simp (maxSteps := 10) (config := {})
