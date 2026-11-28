module

public import Mathlib.Data.List.Chain

@[expose] public section

namespace Chan.Defs.Alt

/-- 原始坐标中的严格递增边界，允许局部起点，最后边界之后是待分尾部。
[057:40] 当行情走到6点时，34、45、56这三段，就可以看成是一个1分钟中枢了，当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。 -/
structure CutChain (n : Nat) where
  marks : List Nat
  nonempty : marks ≠ []
  increasing : marks.IsChain (· < ·)
  bounded : ∀ i ∈ marks, i ≤ n
  deriving DecidableEq

/-- 完整塔的切点行须从原始坐标零起步。 -/
abbrev CutChain.anchoredZero {n : Nat} (row : CutChain n) : Prop :=
  row.marks.head? = some 0

/-- 各行共用底层坐标；每个上级切点都从紧邻下级保留下来。
[101:52] 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。 -/
structure NestedCuts (n : Nat) where
  rows : List (CutChain n)
  nested : ∀ p ∈ rows.zip rows.tail, ∀ j ∈ p.2.marks, j ∈ p.1.marks
  deriving DecidableEq

/-- 左闭右开块的层状性：任意两块不交或一块包含另一块。
[057:40] 当行情走到6点时，34、45、56这三段，就可以看成是一个1分钟中枢了，当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。 -/
abbrev Laminar (blocks : List (Nat × Nat)) : Prop :=
  (∀ b ∈ blocks, b.1 < b.2) ∧ blocks.Pairwise (fun a b =>
    a.2 ≤ b.1 ∨ b.2 ≤ a.1 ∨ (a.1 ≤ b.1 ∧ b.2 ≤ a.2) ∨ (b.1 ≤ a.1 ∧ a.2 ≤ b.2))

/-- 每一层返回包含底层位置的块号；若该位置仍在待分尾部，则该层无地址。
[102:38] 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式 -/
def MultiAddress {n : Nat} (cuts : NestedCuts n) (i : Fin n) : List (Option Nat) :=
  cuts.rows.map fun row =>
    (row.marks.zip row.marks.tail).findIdx? fun b => decide (b.1 ≤ i.val ∧ i.val < b.2)

end Chan.Defs.Alt
