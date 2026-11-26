module
public section
def f (n : Nat) : Nat :=
  if h : n = 0 then 0 else f (n - 1)
termination_by n
decreasing_by
  have _ : (2 : Nat) = 2 := by rfl'
  unhygienic omega
