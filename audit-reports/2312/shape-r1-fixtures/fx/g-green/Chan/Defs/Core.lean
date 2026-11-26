module

public import Mathlib.Order.Interval.Basic
public import Mathlib.Algebra.Order.Ring.Defs

/-!
# 日常写法误拒探针：Chan/Defs 的典型定义文件

模块注释、文档注释、Unicode 标识符、结构、归纳、类、实例、派生、变量段都在。
-/

@[expose] public section

namespace Chan.Defs

universe u

variable {α : Type u}

/-- K 线：低点与高点。 -/
structure Bar where
  /-- 低点。 -/
  low : Nat
  /-- 高点。 -/
  high : Nat
  /-- 低不高于高。 -/
  le : low ≤ high := by omega
deriving Repr, DecidableEq

/-- 方向。 -/
inductive Dir where
  | up
  | down
deriving DecidableEq, Repr, BEq, Hashable, Ord, Inhabited

instance : ToString Dir where
  toString
    | .up => "上"
    | .down => "下"

/-- 可比较的宽度。 -/
class HasWidth (β : Type u) where
  /-- 宽度。 -/
  width : β → Nat

instance : HasWidth Bar where
  width b := b.high - b.low

/-- 递归列表长度，走结构递归。 -/
def count : List α → Nat
  | [] => 0
  | _ :: t => count t + 1

/-- 良基递归，带 termination_by 与 decreasing_by。 -/
def half (n : Nat) : Nat :=
  if h : n < 2 then 0 else half (n - 2) + 1
termination_by n
decreasing_by omega

/-- 嵌套递归类型，派生会生成 partial 辅助函数。 -/
inductive Tree where
  | leaf
  | node (kids : List Tree)
deriving Repr, BEq, Inhabited

/-- 带默认值的结构与字段证明。 -/
structure Window where
  size : Nat := 3
  pos : Nat := 0
  ok : pos ≤ size := by omega

-- 互递归。
mutual
  def even? : Nat → Bool
    | 0 => true
    | n + 1 => odd? n
  def odd? : Nat → Bool
    | 0 => false
    | n + 1 => even? n
end

/-- 匿名构造子与 let、have。 -/
def mk (n : Nat) : Bar :=
  let lo := n
  have h : lo ≤ lo + 1 := Nat.le_succ lo
  ⟨lo, lo + 1, h⟩

/-- Unicode 标识符与希腊字母。 -/
def «笔宽» (b : Bar) : Nat := b.high - b.low

def σ_sum (xs : List Nat) : Nat := xs.foldl (· + ·) 0

@[simp] theorem count_nil : count ([] : List α) = 0 := rfl

end Chan.Defs
