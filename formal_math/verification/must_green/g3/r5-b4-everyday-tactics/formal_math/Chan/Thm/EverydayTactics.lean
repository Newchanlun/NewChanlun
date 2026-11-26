-- 日常 Lean 4 / Mathlib 基础战术误拒汇总（每项均已在单文件夹具中独立实测门 3 退 1）
module
import Mathlib.Tactic.Common
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Tauto
import Mathlib.Tactic.GCongr
import Mathlib.Tactic.Push
public section

theorem tByCases (p : Prop) : p ∨ ¬p := by by_cases h : p; exact Or.inl h; exact Or.inr h
theorem tSplit (b : Bool) : (if b then 1 else 1) = 1 := by split <;> rfl
theorem tConv (a : Nat) : a + 0 = a := by conv => lhs; rw [Nat.add_zero]
theorem tExfalso (h : False) : 1 = 2 := by exfalso; exact h
theorem tSuffices (n : Nat) : n + 0 = n := by suffices n = n by simpa; rfl
theorem tLet (n : Nat) : n = n := by let m := n; rfl
theorem tFunext : (fun x : Nat => x + 0) = (fun x => x) := by funext x; exact Nat.add_zero x
theorem tSimpAll (a b : Nat) (h : a = b) : a + 0 = b := by simp_all
theorem tRevert (a : Nat) : a = a := by revert a; intro a; rfl
theorem tSpecialize (f : ∀ n : Nat, n = n) : 0 = 0 := by specialize f 0; exact f
theorem tByContra (p : Prop) (h : ¬p → False) : p := by by_contra hp; exact h hp
theorem tPushNeg (p : Prop) : ¬¬p → p := by intro h; push_neg at h; exact h
theorem tUse : ∃ n : Nat, n = 0 := by use 0
theorem tExt {a b : Nat × Nat} (h1 : a.1 = b.1) (h2 : a.2 = b.2) : a = b := by ext <;> assumption
theorem tGcongr {a b : Nat} (h : a ≤ b) : a + 1 ≤ b + 1 := by gcongr
theorem tNlinarith (a : Int) : 0 ≤ a * a := by nlinarith
theorem tTauto (p q : Prop) : p → q → p ∧ q := by tauto
