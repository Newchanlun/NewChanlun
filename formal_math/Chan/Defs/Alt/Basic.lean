module

public import Chan.Defs.Path.Symmetry

/-!
# M4 方向、段与方向交替区间序列

核心载体是方向交替区间序列（清单 B-9）：段端点不必是段内极值。方向交替由构造保证：
序列只存首段方向，其后方向逐段取反。
-/

@[expose] public section

namespace Chan.Defs.Alt

open Chan.Defs.Order Chan.Defs.Path

universe u v

/-- 方向：向上或向下。

[067:16]
> 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。
-/
inductive Dir where
  /-- 向上。 -/
  | up
  /-- 向下。 -/
  | down
  deriving DecidableEq

/-- 方向取反。

[067:16]
> 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。
-/
def Dir.flip : Dir → Dir
  | Dir.up => Dir.down
  | Dir.down => Dir.up

/-- 来源跨度：底层索引闭区间 `[start, stop]`，`start ≤ stop`。形态学谓词只依赖其先后次序。

[070:48]
> 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。
-/
structure Span where
  /-- 起点索引。 -/
  start : Nat
  /-- 终点索引。 -/
  stop : Nat
  /-- 起点不超过终点。 -/
  le : start ≤ stop

/-- 两个来源跨度的合并（覆盖两者的最小跨度）。

[070:48]
> 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。
-/
def Span.join (a b : Span) : Span :=
  ⟨min a.start b.start, max a.stop b.stop,
    Nat.le_trans (Nat.min_le_left a.start b.start) (Nat.le_trans a.le (Nat.le_max_left a.stop b.stop))⟩

/-- 段：方向、值域非空闭区间与来源跨度。端点可以不是段内极值。

[070:48]
> 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。
-/
structure Seg (P : Type u) [LinearOrder P] where
  /-- 方向。 -/
  dir : Dir
  /-- 值域闭区间。 -/
  range : Bar P
  /-- 来源跨度。 -/
  span : Span

/-- 方向交替区间序列：首段方向 `start` 与各段（值域，跨度）列表；第 `i` 段方向为 `start`
取反 `i` 次，相邻段方向严格相反由构造保证。

[067:16]
> 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。
-/
structure AltSeq (P : Type u) [LinearOrder P] where
  /-- 首段方向。 -/
  start : Dir
  /-- 各段的值域与跨度。 -/
  body : List (Bar P × Span)

/-- 段的多空对偶：方向取反，值域取序对偶。

[054:24]
> 当然，如果前面d1>g2，那g2就是第三类卖点了。
-/
def dualSeg {P : Type u} [LinearOrder P] (s : Seg P) : Seg (OrderDual P) :=
  ⟨s.dir.flip, dualBar s.range, s.span⟩

/-- 严格保序变换在段上的提升（方向、跨度不变）。

[101:58]
> 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。
-/
def Seg.mapEmb {P : Type u} {Q : Type v} [LinearOrder P] [LinearOrder Q]
    (e : OrderEmb P Q) (s : Seg P) : Seg Q :=
  ⟨s.dir, mapBarEmb e s.range, s.span⟩

/-- 从给定首方向出发，把（值域，跨度）列表展开为方向逐段交替的段列表。

[067:16]
> 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。
-/
def segsFrom {P : Type u} [LinearOrder P] : Dir → List (Bar P × Span) → List (Seg P)
  | _, [] => []
  | d, x :: xs => ⟨d, x.1, x.2⟩ :: segsFrom d.flip xs

/-- 方向交替序列展开成的段列表。

[067:16]
> 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。
-/
def AltSeq.segs {P : Type u} [LinearOrder P] (a : AltSeq P) : List (Seg P) :=
  segsFrom a.start a.body

/-- 段列表的方向交替判据：任意相邻两段方向严格相反（供外部段列表核验）。

[067:16]
> 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。
-/
def Alternating {P : Type u} [LinearOrder P] (l : List (Seg P)) : Prop :=
  ∀ p ∈ List.zip l (List.tail l), p.2.dir = p.1.dir.flip

/-- `Alternating` 可判定。

[067:16]
> 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。
-/
instance instDecidableAlternating {P : Type u} [LinearOrder P] (l : List (Seg P)) :
    Decidable (Alternating l) := by
  unfold Alternating; infer_instance

/-- 方向交替序列的多空对偶：首方向取反，各段值域取序对偶。

[054:24]
> 当然，如果前面d1>g2，那g2就是第三类卖点了。
-/
def dualAltSeq {P : Type u} [LinearOrder P] (a : AltSeq P) : AltSeq (OrderDual P) :=
  ⟨a.start.flip, List.map (fun x : Bar P × Span => (dualBar x.1, x.2)) a.body⟩

end Chan.Defs.Alt
