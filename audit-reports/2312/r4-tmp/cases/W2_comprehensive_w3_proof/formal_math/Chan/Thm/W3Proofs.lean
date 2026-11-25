module
public import Chan.Defs.Model
public import Mathlib.Tactic.Common
public import Mathlib.Tactic.Linarith
public import Mathlib.Tactic.NormNum
public import Mathlib.Tactic.Positivity
public import Mathlib.Algebra.BigOperators.Group.Finset.Basic
public import Mathlib.Data.Finset.Range
public import Mathlib.Data.Rat.Defs
public import Mathlib.Tactic.Ring
public section
open scoped BigOperators

def steps : Nat → Nat
  | 0 => 0
  | n + 1 => 1 + steps (n / 2)
termination_by n => n
decreasing_by omega

def sumWithWhere (xs : List Nat) : Nat := go xs 0
where
  go : List Nat → Nat → Nat
    | [], acc => acc
    | a :: as, acc => go as (acc + a)

def sumLetRec (xs : List Nat) : Nat :=
  let rec loop : List Nat → Nat
    | [] => 0
    | a :: as => a + loop as
  loop xs

mutual
  inductive ExprA | lit (n : Nat) | wrap (b : ExprB)
  inductive ExprB | neg (a : ExprA)
end
deriving instance Repr, BEq, DecidableEq, Hashable, Ord for ExprA, ExprB

mutual
  def szA : ExprA → Nat
    | .lit _ => 1
    | .wrap b => 1 + szB b
  def szB : ExprB → Nat
    | .neg a => 1 + szA a
end

section Params
variable {α : Type} [DecidableEq α] (a : α)
include a
omit [DecidableEq α] in
theorem id_eq_self : a = a := rfl
end Params

@[simp] theorem pt_sum_mk (a b : Nat) : (⟨a, b⟩ : Pt).sum = a + b := rfl

theorem use_calc_omega (a b c : Nat) (h1 : a ≤ b) (h2 : b ≤ c) : a ≤ c + 1 := by
  calc a ≤ b := h1
    _ ≤ c := h2
    _ ≤ c + 1 := by omega

theorem use_decide : (2 + 3 : Nat) = 5 := by decide

theorem use_grind (x y : Nat) (h : x = y) : x + 1 = y + 1 := by grind

theorem use_aesop (P Q : Prop) (h : P ∧ Q) : Q ∧ P := by aesop

theorem use_linarith (x y : Int) (h1 : x ≤ y) (h2 : y ≤ x) : x = y := by linarith

theorem use_norm_num : (2 : Rat) + 3 / 2 = 7 / 2 := by norm_num

theorem use_positivity (x : Rat) (hx : 0 < x) : 0 < x * x := by positivity

theorem use_rcases_obtain (h : ∃ p : Pt, p.x = 1 ∧ p.y = 2) : ∃ n : Nat, n = 3 := by
  rcases h with ⟨⟨x, y⟩, hx, hy⟩
  obtain ⟨m, hm⟩ : ∃ m, m = x + y := ⟨x + y, rfl⟩
  exact ⟨m, by omega⟩

theorem use_induction (xs : List Nat) : sumLetRec xs = xs.sum := by
  induction xs with
  | nil => rfl
  | cons a as ih => simp [sumLetRec, sumLetRec.loop, ih]

theorem use_big_ops (n : Nat) : (∑ i ∈ Finset.range n, (0 : Nat)) = 0 := by
  simp

theorem use_list_big_op (xs : List Nat) : (xs.map (· + 0)).sum = xs.sum := by
  simp
