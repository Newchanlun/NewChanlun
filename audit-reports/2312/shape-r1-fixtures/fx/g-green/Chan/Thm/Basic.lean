module

public import Chan.Defs.Core
public import Mathlib.Tactic.Common
public import Mathlib.Tactic.Linarith
public import Mathlib.Tactic.Ring
public import Mathlib.Tactic.Positivity
public import Mathlib.Algebra.BigOperators.Group.Finset.Defs
public import Mathlib.Data.Finset.Lattice.Fold
public import Mathlib.Data.Finset.Card
public import Mathlib.Analysis.SpecialFunctions.Pow.Real
public import Mathlib.Tactic.NormNum.Basic

/-! 日常证明写法。 -/

public section

namespace Chan.Thm

open Chan.Defs
open scoped Nat
open Finset in
theorem sum_const (s : Finset Nat) : ∑ _x ∈ s, (0 : Nat) = 0 := by simp

variable {a b c : Nat}

theorem add_comm' : a + b = b + a := by omega

theorem le_trans' (h1 : a ≤ b) (h2 : b ≤ c) : a ≤ c := le_trans h1 h2

theorem by_cases_ex (p : Prop) [Decidable p] : p ∨ ¬p := by
  by_cases h : p
  · exact Or.inl h
  · exact Or.inr h

theorem rcases_ex (h : a = 0 ∨ a = 1) : a ≤ 1 := by
  rcases h with h | h <;> omega

theorem obtain_ex (h : ∃ n, a = n + 1) : 1 ≤ a := by
  obtain ⟨n, rfl⟩ := h
  omega

theorem calc_ex (h : a = b) (h2 : b = c) : a = c :=
  calc a = b := h
    _ = c := h2

theorem conv_ex : a + 0 = a := by
  conv =>
    lhs
    rw [Nat.add_zero]

theorem ext_ex {f g : Nat → Nat} (h : ∀ x, f x = g x) : f = g := by
  funext x
  exact h x

theorem use_ex : ∃ n : Nat, n + 1 = 1 := by
  use 0

theorem refine_ex : 0 ≤ a ∧ a ≤ a := by
  refine ⟨?_, ?_⟩
  · exact Nat.zero_le a
  · exact Nat.le_refl a

theorem simp_cfg : (a + 0) * 1 = a := by simp

theorem simp_lemmas (h : a = b) : a + 0 = b := by simp only [Nat.add_zero, h]

theorem simp_plus : a + 0 = a := by simp +arith

theorem simp_at (h : a + 0 = b) : a = b := by simpa using h

theorem omega_ex (h : a < b) : a + 1 ≤ b := by omega

theorem linarith_ex (x y : ℝ) (h : x ≤ y) : x - y ≤ 0 := by linarith

theorem nlinarith_ex (x : ℝ) : 0 ≤ x ^ 2 := by nlinarith [sq_nonneg x]

theorem positivity_ex (x : ℝ) (h : 0 < x) : 0 < x ^ 2 + 1 := by positivity

theorem norm_num_ex : (2 : ℝ) + 2 = 4 := by norm_num

theorem ring_ex (x y : ℝ) : (x + y) ^ 2 = x ^ 2 + 2 * x * y + y ^ 2 := by ring

theorem decide_ex : (3 : Nat) < 5 := by decide

theorem list_notation : [1, 2, 3].length = 3 := by simp

theorem finset_notation : ({1, 2} : Finset Nat).card ≤ 2 := by
  simp

theorem induction_ex (n : Nat) : 0 ≤ n := by
  induction n with
  | zero => exact Nat.le_refl 0
  | succ k _ => exact Nat.zero_le _

theorem match_ex (d : Chan.Defs.Dir) : d = .up ∨ d = .down := by
  match d with
  | .up => exact Or.inl rfl
  | .down => exact Or.inr rfl

theorem width_mk (n : Nat) : Chan.Defs.HasWidth.width (Chan.Defs.mk n) = 1 := by
  simp [Chan.Defs.HasWidth.width, Chan.Defs.mk]

theorem set_opt_ok : a + 0 = a := by
  set_option maxHeartbeats 400000 in
  omega

set_option maxRecDepth 2000 in
theorem deep : a + 0 = a := by omega

attribute [simp] add_comm'

theorem long_unicode (α β : Type) (f : α → β) (x : α) : f x = f x := rfl

end Chan.Thm
