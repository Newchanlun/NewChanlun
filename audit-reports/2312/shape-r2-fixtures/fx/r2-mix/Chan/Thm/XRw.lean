module


public section

theorem t (a b : Nat) (h : a = b) : a = b := by
  rw (config := {}) [h]
