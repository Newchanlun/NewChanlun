module

public import Chan.Defs.Path.Symmetry
public import Mathlib.Data.List.Chain

@[expose] public section

namespace Chan.Defs.Alt

open Chan.Defs.Order Chan.Defs.Path
variable {P Q : Type _} [LinearOrder P] [LinearOrder Q]

/-- 段的方向只有上和下两种。
[067:16] 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。 -/
inductive Dir where
  | up | down
  deriving DecidableEq

/-- 多空互换。 -/
def Dir.flip : Dir → Dir
  | .up => .down
  | .down => .up

/-- 来源跨度使用闭索引，保留原始位置。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。 -/
structure Span where
  first : Nat
  last : Nat
  ordered : first ≤ last
  deriving DecidableEq

/-- 两个来源跨度的最小共同包络。 -/
def Span.join (a b : Span) : Span :=
  ⟨min a.first b.first, max a.last b.last,
    Nat.le_trans (Nat.min_le_left _ _) (Nat.le_trans a.ordered (Nat.le_max_left _ _))⟩

/-- 走势方向不决定内部极值出现在哪个时刻。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。 -/
structure Seg (P : Type _) [LinearOrder P] where
  dir : Dir
  range : Bar P
  source : Span
  deriving DecidableEq

/-- 反序只改变方向与价格区间，不改变来源。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def dualSeg (s : Seg P) : Seg (OrderDual P) :=
  ⟨s.dir.flip, dualBar s.range, s.source⟩

/-- 换价保持段方向与跨度。 -/
def Seg.mapEmb (f : OrderEmb P Q) (s : Seg P) : Seg Q :=
  ⟨s.dir, mapBarEmb f s.range, s.source⟩

/-- 只要求相邻段反向，不预设端点相接或三段公共交。
[067:16] 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。 -/
structure AltSeq (P : Type _) [LinearOrder P] where
  items : List (Seg P)
  alternating : items.IsChain (fun a b => a.dir ≠ b.dir)
  deriving DecidableEq

/-- 整条序列同时取对偶，顺序不变。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def dualAltSeq (s : AltSeq P) : AltSeq (OrderDual P) :=
  ⟨s.items.map dualSeg, List.isChain_map_of_isChain dualSeg (by
    intro a b h
    change a.dir.flip ≠ b.dir.flip
    cases ha : a.dir <;> cases hb : b.dir <;> simp_all [Dir.flip]) s.alternating⟩

/-- 逐段严格换价保留交替关系。
[067:16] 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。 -/
def AltSeq.mapEmb (f : OrderEmb P Q) (s : AltSeq P) : AltSeq Q :=
  ⟨s.items.map (Seg.mapEmb f), List.isChain_map_of_isChain (Seg.mapEmb f) (fun _ _ h => h) s.alternating⟩

end Chan.Defs.Alt
