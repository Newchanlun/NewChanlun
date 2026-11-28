module

public import Chan.Defs.Path.Symmetry

@[expose] public section

namespace Chan.Defs.Alt

open Chan.Defs.Order Chan.Defs.Path
variable {P Q : Type _} [Std.LinearOrderPackage P] [Std.LinearOrderPackage Q]

/-- 段的方向只有上和下两种。
[067:16] 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。 -/
inductive Dir where
  | up | down
  deriving DecidableEq

/-- 多空互换。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
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

/-- 走势方向不决定内部极值出现在哪个时刻。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。 -/
structure Seg (P : Type _) [Std.LinearOrderPackage P] where
  dir : Dir
  range : Bar P
  source : Span
  deriving DecidableEq

/-- 反序只改变方向与价格区间，不改变来源。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def dualSeg (s : Seg P) : Seg (PriceDual P) :=
  ⟨s.dir.flip, dualBar s.range, s.source⟩

/-- 换价保持段方向与跨度。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
def Seg.mapEmb (f : OrderEmb P Q) (s : Seg P) : Seg Q :=
  ⟨s.dir, mapBarEmb f s.range, s.source⟩

/-- 只要求相邻段反向，不预设端点相接或三段公共交。
[067:16] 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。 -/
structure AltSeq (P : Type _) [Std.LinearOrderPackage P] where
  items : List (Seg P)
  alternating : ∀ i : Fin items.length, ∀ j : Fin items.length,
    j.val = i.val + 1 → items[i.val].dir ≠ items[j.val].dir
  deriving DecidableEq

/-- 整条序列同时取对偶，顺序不变。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def dualAltSeq (s : AltSeq P) : AltSeq (PriceDual P) :=
  ⟨s.items.map dualSeg, by
    intro i j hij
    simp only [List.getElem_map]
    let i' : Fin s.items.length := ⟨i, by simpa using i.isLt⟩
    let j' : Fin s.items.length := ⟨j, by simpa using j.isLt⟩
    have h := s.alternating i' j' hij
    change s.items[i'.val].dir.flip ≠ s.items[j'.val].dir.flip
    cases hi : s.items[i'.val].dir <;> cases hj : s.items[j'.val].dir <;> simp_all [Dir.flip]⟩

/-- 逐段严格换价保留交替关系。
[067:16] 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。 -/
def AltSeq.mapEmb (f : OrderEmb P Q) (s : AltSeq P) : AltSeq Q :=
  ⟨s.items.map (Seg.mapEmb f), by
    intro i j hij
    simp only [List.getElem_map]
    exact s.alternating ⟨i, by simpa using i.isLt⟩ ⟨j, by simpa using j.isLt⟩ hij⟩

end Chan.Defs.Alt
