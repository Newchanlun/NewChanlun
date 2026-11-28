module

public import Chan.Defs.Alt.Basic

@[expose] public section

namespace Chan.Defs.Alt

variable {P : Type _} [Std.LinearOrderPackage P]

/-- 折线模型的定向起点；一般段不要求在此处起步。
[067:16] 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。 -/
def Seg.zigStart (s : Seg P) : P :=
  match s.dir with | .up => s.range.lo | .down => s.range.hi

/-- 折线模型的定向终点。
[067:16] 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。 -/
def Seg.zigEnd (s : Seg P) : P :=
  match s.dir with | .up => s.range.hi | .down => s.range.lo

/-- 共端折线是交替区间序列的特例。
[067:16] 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。 -/
def Zigzag (P : Type _) [Std.LinearOrderPackage P] :=
  { xs : AltSeq P // ∀ p ∈ xs.items.zip xs.items.tail, p.1.zigEnd = p.2.zigStart }

/-- 忘掉共端证明，保留原样的段和值域。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。 -/
def Zigzag.toAltSeq (z : Zigzag P) : AltSeq P := z.val

end Chan.Defs.Alt
