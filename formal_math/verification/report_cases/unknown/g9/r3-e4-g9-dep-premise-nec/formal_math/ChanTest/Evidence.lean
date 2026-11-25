module
public import Chan.Thm.DepPrem
public section
theorem dep_get.witness : ∃ (l : List Nat) (i : Nat) (h1 : i < l.length), l[i] = 0 :=
  ⟨[0], 0, by decide, rfl⟩
