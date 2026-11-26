module


public section

theorem t (a : Nat) (h : a = a) : a + 0 = a := by
  simpa (config := {}) using h
