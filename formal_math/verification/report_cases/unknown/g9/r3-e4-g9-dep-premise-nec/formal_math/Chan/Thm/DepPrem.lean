module
public section
theorem dep_get (l : List Nat) (i : Nat) (h1 : i < l.length) (h2 : l[i] = 0) : l[i] + 1 = 1 := by
  simp [h2]
