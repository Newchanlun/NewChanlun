module

public import Chan.Defs.Alt.Basic

/-!
# M4 切点链、层状族与多级地址

切点链把长度 `N` 的底层序列划分为连续非空左闭右开块；多级切点链逐级嵌套
（上一级切点集是下一级切点集的子集）。
-/

@[expose] public section

namespace Chan.Defs.Alt

/-- 自然数列表严格递增。

[057:42]
> 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。
-/
def StrictIncr (l : List Nat) : Prop := ∀ p ∈ List.zip l (List.tail l), p.1 < p.2

/-- `StrictIncr` 可判定。

[057:42]
> 结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。
-/
instance instDecidableStrictIncr (l : List Nat) : Decidable (StrictIncr l) := by
  unfold StrictIncr; infer_instance

/-- 单级切点链：严格递增、均不超过 `N` 的切点下标表；相邻切点 `[cᵢ, cᵢ₊₁)` 构成非空块。

[057:42]
> 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。
-/
structure CutChain (N : Nat) where
  /-- 切点下标表。 -/
  cuts : List Nat
  /-- 严格递增。 -/
  strict : StrictIncr cuts
  /-- 不超过底层长度。 -/
  bounded : ∀ c ∈ cuts, c ≤ N

/-- 多级逐级嵌套切点表：第 `k+1` 级的每个切点都是第 `k` 级的切点（第 0 级最细）。

[102:38]
> 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式
-/
structure NestedCuts (N : Nat) where
  /-- 自细到粗的各级切点链。 -/
  levels : List (CutChain N)
  /-- 逐级嵌套。 -/
  nested : ∀ p ∈ List.zip levels (List.tail levels), ∀ x ∈ p.2.cuts, x ∈ p.1.cuts

variable {N : Nat}

/-- 切点链的块表 `[(cᵢ, cᵢ₊₁)]`（左闭右开）。

[057:42]
> 结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。
-/
def CutChain.blocks (c : CutChain N) : List (Nat × Nat) := List.zip c.cuts (List.tail c.cuts)

/-- 两个左闭右开块不相交。

[057:40]
> 当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。
-/
def blockDisjoint (a b : Nat × Nat) : Prop := a.2 ≤ b.1 ∨ b.2 ≤ a.1

/-- `blockDisjoint` 可判定。

[057:40]
> 当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。
-/
instance instDecidableBlockDisjoint (a b : Nat × Nat) : Decidable (blockDisjoint a b) := by
  unfold blockDisjoint; infer_instance

/-- 块 `a` 含于块 `b`。

[057:40]
> 当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。
-/
def blockWithin (a b : Nat × Nat) : Prop := b.1 ≤ a.1 ∧ a.2 ≤ b.2

/-- `blockWithin` 可判定。

[057:40]
> 当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。
-/
instance instDecidableBlockWithin (a b : Nat × Nat) : Decidable (blockWithin a b) := by
  unfold blockWithin; infer_instance

/-- 层状族：任意两块要么不相交，要么一个包含另一个。

[102:38]
> 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式
-/
def Laminar (blocks : List (Nat × Nat)) : Prop :=
  ∀ a ∈ blocks, ∀ b ∈ blocks, blockDisjoint a b ∨ blockWithin a b ∨ blockWithin b a

/-- `Laminar` 可判定。

[102:38]
> 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式
-/
instance instDecidableLaminar (blocks : List (Nat × Nat)) : Decidable (Laminar blocks) := by
  unfold Laminar; infer_instance

/-- 在块表中查找含底层索引 `i` 的块编号（`k` 为当前编号累加器）。

[053:20]
> 但无论这些显微镜如何转换，一个原则是不变的，就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。
-/
def blockIndexAux (i : Nat) : Nat → List (Nat × Nat) → Option Nat
  | _, [] => none
  | k, b :: bs => if b.1 ≤ i ∧ i < b.2 then some k else blockIndexAux i (k + 1) bs

/-- 底层索引 `i` 在切点表 `cuts` 中所属块的编号（不在任何块内则为 `none`）。

[053:20]
> 就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。
-/
def blockIndex (cuts : List Nat) (i : Nat) : Option Nat :=
  blockIndexAux i 0 (List.zip cuts (List.tail cuts))

/-- 多级地址：底层索引 `i` 在各级切点链中的块编号路径（自细到粗）。

[102:38]
> 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式
-/
def MultiAddress (nc : NestedCuts N) (i : Nat) : List (Option Nat) :=
  List.map (fun c : CutChain N => blockIndex c.cuts i) nc.levels

end Chan.Defs.Alt
