module
public import Mathlib.Tactic.Common
public import Mathlib.Tactic.Ring
public import Mathlib.Tactic.Linarith
public import Mathlib.Data.Finset.Basic
public section

/-! 常见写法的语料：字符串插值、记号、结构实例、匿名构造、模式匹配与常用战术。 -/

def greet (n : Nat) : String := s!"n = {n}, n+1 = {n + 1}"

def pairs : List (Nat × Bool) := [(1, true), (2, false)]

def total (xs : List Nat) : Nat := xs.foldl (· + ·) 0

def compose : Nat → Nat := (· * 2) ∘ (· + 1)

def pipeline (n : Nat) : Nat := n |> (· + 1) |> fun k => k % 7

def power (n : Nat) : Nat := n ^ 2 - n / 3

structure Bar where
  lo : Nat
  hi : Nat
  ok : lo ≤ hi

def unitBar : Bar := { lo := 0, hi := 1, ok := by decide }

def mkBar (a : Nat) : Bar := ⟨a, a + 1, Nat.le_succ a⟩

def width (b : Bar) : Nat := b.hi - b.lo

def classify : Nat → String
  | 0 => "零"
  | 1 => "一"
  | _ => "多"

def pick (b : Bool) (x y : Nat) : Nat := if b then x else y

def firstOr (xs : List Nat) : Nat :=
  match xs with
  | [] => 0
  | x :: _ => x

def sumTo (n : Nat) : Nat := Id.run do
  let mut acc := 0
  for i in [0:n] do
    acc := acc + i
  return acc

theorem width_mk (a : Nat) : width (mkBar a) = 1 := by
  simp [width, mkBar]

theorem pick_true (x y : Nat) : pick true x y = x := by simp [pick]

theorem le_example (a b : Nat) (h : a ≤ b) : a < b + 1 := by omega

theorem and_comm' (p q : Prop) : p ∧ q ↔ q ∧ p := by
  constructor
  · rintro ⟨hp, hq⟩
    exact ⟨hq, hp⟩
  · intro h
    obtain ⟨hq, hp⟩ := h
    exact ⟨hp, hq⟩

theorem exists_example : ∃ n : Nat, n + 2 = 5 := ⟨3, rfl⟩

theorem forall_mem (s : Finset Nat) : ∀ x ∈ s, x ∈ s := fun _ h => h

theorem not_example (n : Nat) (h : n ≠ 0) : ¬ n = 0 := h

theorem ring_example (a b : Int) : (a + b) ^ 2 = a ^ 2 + 2 * a * b + b ^ 2 := by ring

theorem linarith_example (x y : Int) (h₁ : x < y) (h₂ : y < 3) : x < 3 := by linarith

theorem calc_example (a b c : Nat) (h₁ : a = b) (h₂ : b = c) : a = c := by
  calc a = b := h₁
    _ = c := h₂

theorem cases_example (n : Nat) : n = 0 ∨ 0 < n := by
  cases n with
  | zero => left; rfl
  | succ k => right; exact Nat.succ_pos k

theorem induction_example (n : Nat) : total (List.replicate n 0) = 0 := by
  induction n with
  | zero => rfl
  | succ k ih => simpa [total, List.replicate_succ] using ih

theorem rw_example (a b : Nat) (h : a = b) : a + 0 = b := by
  rw [Nat.add_zero, h]

theorem show_example (p : Prop) (hp : p) : p := by
  show p
  exact hp

theorem refine_example : ∃ n : Nat, n = n := by
  refine ⟨0, ?_⟩
  rfl

theorem apply_example (p q : Prop) (hpq : p → q) (hp : p) : q := by
  apply hpq
  assumption

theorem unfold_example : classify 0 = "零" := by
  unfold classify
  rfl

theorem have_example (n : Nat) : n + 1 > 0 := by
  have h : 0 < n + 1 := Nat.succ_pos n
  exact h

theorem norm_num_example : (3 : Nat) * 4 = 12 := by norm_num

theorem exact_mod (n : Nat) : n % 2 < 2 := Nat.mod_lt n (by norm_num)
end
