module

public import Chan.Defs.Alt.Basic

/-!
# M4 折线

折线是方向交替区间序列的子类型：每段另带起点价与终点价（落在该段值域内），
且相邻两段首尾端点价相等（清单 B-9）。
-/

@[expose] public section

namespace Chan.Defs.Alt

open Chan.Defs.Order

universe u

/-- 折线合法性判据：端点价表与段数等长、每段端点价落在其值域内、相邻段首尾端点价相等。

[070:48]
> 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。
-/
def IsZigzag {P : Type u} [LinearOrder P] (alt : AltSeq P) (ends : List (P × P)) : Prop :=
  ends.length = alt.body.length ∧
  (∀ q ∈ List.zip ends alt.body,
    q.2.1.lo ≤ q.1.1 ∧ q.1.1 ≤ q.2.1.hi ∧ q.2.1.lo ≤ q.1.2 ∧ q.1.2 ≤ q.2.1.hi) ∧
  (∀ q ∈ List.zip ends (List.tail ends), q.1.2 = q.2.1)

/-- `IsZigzag` 可判定。

[070:48]
> 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。
-/
instance instDecidableIsZigzag {P : Type u} [LinearOrder P] (alt : AltSeq P)
    (ends : List (P × P)) : Decidable (IsZigzag alt ends) := by
  unfold IsZigzag; infer_instance

/-- 折线：方向交替区间序列加每段（起点价，终点价），满足 `IsZigzag`。

[067:16]
> 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。
-/
structure Zigzag (P : Type u) [LinearOrder P] where
  /-- 底层方向交替序列。 -/
  alt : AltSeq P
  /-- 每段的（起点价，终点价）。 -/
  ends : List (P × P)
  /-- 折线约束。 -/
  valid : IsZigzag alt ends

/-- 折线到方向交替序列的遗忘嵌入。

[067:16]
> 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。
-/
def Zigzag.toAltSeq {P : Type u} [LinearOrder P] (z : Zigzag P) : AltSeq P := z.alt

end Chan.Defs.Alt
