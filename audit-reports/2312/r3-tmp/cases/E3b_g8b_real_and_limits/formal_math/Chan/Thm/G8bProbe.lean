module
public section
theorem uses_h_omega (a b : Nat) (h : a < b) : a ≤ b := by omega
theorem dead_pprod_fst (x : Nat) (h : x ≠ 0) : x + 0 = x := PProd.fst ⟨rfl, h⟩
theorem dead_pprod_dot1 (x : Nat) (h : x ≠ 0) : x + 0 = x := (PProd.mk (rfl : x + 0 = x) h).1
theorem dead_id (x : Nat) (h : x ≠ 0) : x + 0 = x := (id (fun (_ : x ≠ 0) => (rfl : x + 0 = x))) h
