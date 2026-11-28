module

public import Chan.Defs.Order.Bar

/-!
# M3 对称性与小模型

多空对偶用 `OrderDual`；严格保序变换用序嵌入刻画（线性序上与严格单调等价）；
小模型是有界离散格上的有限区间序列载体。
-/

@[expose] public section

namespace Chan.Defs.Path

open Chan.Defs.Order

universe u v

/-- 严格保序价格变换：`toFun x ≤ toFun y ↔ x ≤ y`。在线性序上这等价于严格单调递增。

[101:58]
> 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。
-/
structure OrderEmb (P : Type u) (Q : Type v) [LinearOrder P] [LinearOrder Q] where
  /-- 底层映射。 -/
  toFun : P → Q
  /-- 保序且反射序。 -/
  le_iff : ∀ x y, toFun x ≤ toFun y ↔ x ≤ y

/-- 有限长度 `n` 的区间序列压缩到有界离散格 `[0, bound)` 上的小模型载体：
每格为 `(低, 高)` 自然数对，满足 `低 ≤ 高 < bound`。

[101:58]
> 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。
-/
structure SmallModel (n bound : Nat) where
  /-- 各格的 `(低, 高)`。 -/
  cells : List (Nat × Nat)
  /-- 长度为 `n`。 -/
  length_eq : cells.length = n
  /-- 值域有界且为合法区间。 -/
  valid : ∀ c ∈ cells, c.1 ≤ c.2 ∧ c.2 < bound

/-- 序对偶下的 K 线：高低点互换后落在 `OrderDual P` 上。

[054:24]
> 而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。
-/
def dualBar {P : Type u} [LinearOrder P] (b : Bar P) : Bar (OrderDual P) :=
  ⟨OrderDual.toDual b.hi, OrderDual.toDual b.lo, b.valid⟩

/-- 严格保序变换在区间上的逐端点提升。

[101:58]
> 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。
-/
def mapBarEmb {P : Type u} {Q : Type v} [LinearOrder P] [LinearOrder Q]
    (e : OrderEmb P Q) (b : Bar P) : Bar Q :=
  ⟨e.toFun b.lo, e.toFun b.hi, (e.le_iff b.lo b.hi).mpr b.valid⟩

/-- 小模型合法性的可判定判据（`SmallModel` 字段的布尔化版本）。

[101:58]
> 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。
-/
def SmallModel.Valid (n bound : Nat) (cells : List (Nat × Nat)) : Prop :=
  cells.length = n ∧ ∀ c ∈ cells, c.1 ≤ c.2 ∧ c.2 < bound

/-- `SmallModel.Valid` 可判定。

[101:58]
> 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。
-/
instance instDecidableSmallModelValid (n bound : Nat) (cells : List (Nat × Nat)) :
    Decidable (SmallModel.Valid n bound cells) := by
  unfold SmallModel.Valid; infer_instance

end Chan.Defs.Path
