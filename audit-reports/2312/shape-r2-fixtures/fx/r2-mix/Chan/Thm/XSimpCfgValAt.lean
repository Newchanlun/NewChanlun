module


public section

theorem t (a : Nat) (h : a + 0 = a) : a + 0 = a := by
  simp (config := {}) (maxSteps := 10) at h ⊢
