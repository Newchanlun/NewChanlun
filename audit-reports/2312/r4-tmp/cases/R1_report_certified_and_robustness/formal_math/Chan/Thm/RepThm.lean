module
public import Chan.Hypotheses.RepHyp
public section
theorem depends_on_D : D 0 = 1 := rfl
theorem generalizes_D (n : Nat) : D n = D n := rfl
theorem uses_carryD (c : CarryD) : c.x + 1 = c.x + 1 := rfl
theorem uses_nom (h : NomInd 0) : D 0 = 1 := by cases h with | mk e => exact e | alt e => exact e
theorem uses_prem_omega (a b : Nat) (h : a < b) : a + 1 ≤ b := by omega
theorem unused_prem (a : Nat) (_h : a = 0) : a + 0 = a := Nat.add_zero a
theorem dep_prem (l : List Nat) (i : Nat) (h1 : i < l.length) (h2 : l[i] = 0) : l[i] + 1 = 1 := by omega
