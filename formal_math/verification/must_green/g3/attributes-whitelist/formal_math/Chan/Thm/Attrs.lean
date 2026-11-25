module
public import Mathlib.Order.Basic
public section
@[simp] theorem a1 : (1 : Nat) = 1 := rfl
@[ext] structure S where
  x : Nat
@[reducible] def r1 : Nat := 1
@[irreducible] def r2 : Nat := 1
@[inline] def r3 : Nat := 1
@[specialize] def r4 (f : Nat → Nat) : Nat := f 1
instance (priority := low) i1 : Inhabited S := ⟨⟨0⟩⟩
@[refl] theorem rf (n : Nat) : n ≤ n := Nat.le_refl n
@[symm] theorem sy (a b : Nat) (h : a = b) : b = a := h.symm
@[gcongr] theorem g1 (a b c : Nat) (h : a ≤ b) : a + c ≤ b + c := Nat.add_le_add_right h c
@[elab_as_elim] theorem e1 {motive : Nat → Prop} (h0 : motive 0) (hs : ∀ n, motive n → motive (n + 1)) (n : Nat) : motive n := Nat.rec h0 hs n
@[deprecated "改用 r1" (since := "2026-01-01")] def dep : Nat := 1
attribute [simp] r1
attribute [-simp] a1
@[no_expose] def ne : Nat := 1
@[expose] def ex : Nat := 1
@[local simp] theorem l1 : (2 : Nat) = 2 := rfl
namespace Inner
@[scoped simp] theorem l2 : (3 : Nat) = 3 := rfl
end Inner
set_option maxHeartbeats 400000 in
theorem big : (4 : Nat) = 4 := by
  set_option maxRecDepth 2000 in
  exact rfl
end
