module
public section
local instance (priority := high) fakeLT : LT Nat := ⟨fun _ _ => True⟩
theorem looks_absurd : 10 < 1 := trivial
@[simp] theorem my_simp (x : Nat) : x + 0 = x := Nat.add_zero x
attribute [-simp] my_simp
