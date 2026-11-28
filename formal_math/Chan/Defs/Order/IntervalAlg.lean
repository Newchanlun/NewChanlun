module

public import Chan.Defs.Order.Bar

/-!
# M1 重叠与相对位置

闭区间相交即算重叠（单点相触算重叠），严格越过须严格不等号（分叉 4，清单 B-3）。
两个（核、波动区间）对的相对位置分类互斥且穷尽（清单 B-38）。
-/

@[expose] public section

namespace Chan.Defs.Order

universe u

/-- 核加波动区间对：核区间 `[ZD, ZG]` 含于波动区间 `[DD, GG]`，即 `DD ≤ ZD ≤ ZG ≤ GG`。

[020:54]
> 特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：
-/
structure CoreHull (P : Type u) [LinearOrder P] where
  /-- 核区间 `[ZD, ZG]`。 -/
  core : Bar P
  /-- 波动区间 `[DD, GG]`。 -/
  hull : Bar P
  /-- 核含于波动区间。 -/
  inside : hull.contains core

/-- 两个先后同级（核、波动区间）对的相对位置：五类互斥且穷尽。
`sepUp`：后 `DD` 严格高于前 `GG`；`sepDown`：后 `GG` 严格低于前 `DD`；
`expandUp`：后 `ZD` 严格高于前 `ZG` 且后 `DD ≤` 前 `GG`；
`expandDown`：后 `ZG` 严格低于前 `ZD` 且后 `GG ≥` 前 `DD`；`coreOverlap`：两核闭重叠。

[020:58]
> 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。
-/
inductive RelPos where
  /-- 严格向上分离。 -/
  | sepUp
  /-- 严格向下分离。 -/
  | sepDown
  /-- 核不重叠、波动区间重叠，向上扩展。 -/
  | expandUp
  /-- 核不重叠、波动区间重叠，向下扩展。 -/
  | expandDown
  /-- 核闭重叠（含嵌套、相交、相等、单点相触）。 -/
  | coreOverlap
  deriving DecidableEq

variable {P : Type u} [LinearOrder P]

/-- 两闭区间闭重叠：较大低点不超过较小高点（单点相触算重叠）。

[054:24]
> 由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。
-/
def overlaps (a b : Bar P) : Prop := max a.lo b.lo ≤ min a.hi b.hi

/-- `overlaps` 可判定。

[054:24]
> 由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。
-/
instance instDecidableOverlaps (a b : Bar P) : Decidable (overlaps a b) := by
  unfold overlaps; infer_instance

/-- 有限非空区间列表公共交非空：列表非空，且任意两元素满足 `lo ≤ hi`
（等价于最大低点不超过最小高点）。

[020:48]
> 则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。
-/
def overlapsList (l : List (Bar P)) : Prop :=
  0 < l.length ∧ ∀ a ∈ l, ∀ b ∈ l, a.lo ≤ b.hi

/-- `overlapsList` 可判定。

[020:48]
> 则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。
-/
instance instDecidableOverlapsList (l : List (Bar P)) : Decidable (overlapsList l) := by
  unfold overlapsList; infer_instance

/-- 两重叠闭区间之交 `[max 低点, min 高点]`。

[018:24]
> 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。
-/
def interInterval (a b : Bar P) (h : overlaps a b) : Bar P :=
  ⟨max a.lo b.lo, min a.hi b.hi, h⟩

/-- 两区间凸包 `[min 低点, max 高点]`（`hullInterval` 的折叠步）。

[020:56]
> 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。
-/
def hullPair (a b : Bar P) : Bar P :=
  ⟨min a.lo b.lo, max a.hi b.hi,
    le_trans (min_le_left a.lo b.lo) (le_trans a.valid (le_max_left a.hi b.hi))⟩

/-- 有限非空区间列表（首元素 `b` 加其余 `rest`）的凸包，即波动包络。

[020:58]
> 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。
-/
def hullInterval (b : Bar P) (rest : List (Bar P)) : Bar P :=
  List.foldl hullPair b rest

/-- 向上缺口：`b` 的低点严格大于 `a` 的高点。

[020:56]
> 换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。
-/
def gapUp (a b : Bar P) : Prop := a.hi < b.lo

/-- `gapUp` 可判定。

[020:56]
> 换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。
-/
instance instDecidableGapUp (a b : Bar P) : Decidable (gapUp a b) := by
  unfold gapUp; infer_instance

/-- 向下缺口：`b` 的高点严格小于 `a` 的低点。

[020:56]
> 换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。
-/
def gapDown (a b : Bar P) : Prop := b.hi < a.lo

/-- `gapDown` 可判定。

[020:56]
> 换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。
-/
instance instDecidableGapDown (a b : Bar P) : Decidable (gapDown a b) := by
  unfold gapDown; infer_instance

/-- 区间整体严格高于价位 `x`：低点严格大于 `x`（端点相触不算）。

[054:24]
> 而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。
-/
def strictAbove (b : Bar P) (x : P) : Prop := x < b.lo

/-- `strictAbove` 可判定。

[054:24]
> 而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。
-/
instance instDecidableStrictAbove (b : Bar P) (x : P) : Decidable (strictAbove b x) := by
  unfold strictAbove; infer_instance

/-- 区间整体严格低于价位 `x`：高点严格小于 `x`（端点相触不算）。

[054:24]
> 而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。
-/
def strictBelow (b : Bar P) (x : P) : Prop := b.hi < x

/-- `strictBelow` 可判定。

[054:24]
> 而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。
-/
instance instDecidableStrictBelow (b : Bar P) (x : P) : Decidable (strictBelow b x) := by
  unfold strictBelow; infer_instance

/-- 核下沿 `ZD`。

[020:54]
> 特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：
-/
def CoreHull.zd (c : CoreHull P) : P := c.core.lo

/-- 核上沿 `ZG`。

[020:54]
> 特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：
-/
def CoreHull.zg (c : CoreHull P) : P := c.core.hi

/-- 波动区间下沿 `DD`。

[020:58]
> 前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；
-/
def CoreHull.dd (c : CoreHull P) : P := c.hull.lo

/-- 波动区间上沿 `GG`。

[020:58]
> 后DD>前GG等价于上涨及其延续。
-/
def CoreHull.gg (c : CoreHull P) : P := c.hull.hi

/-- 计算两 `CoreHull`（前 `x`、后 `y`）的相对位置。先判核是否闭重叠；否则按核在上方或下方，
再判波动区间是否严格分离。

[020:58]
> 后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。
-/
def relPos (x y : CoreHull P) : RelPos :=
  if max x.zd y.zd ≤ min x.zg y.zg then RelPos.coreOverlap
  else if x.zg < y.zd then
    (if x.gg < y.dd then RelPos.sepUp else RelPos.expandUp)
  else
    (if y.gg < x.dd then RelPos.sepDown else RelPos.expandDown)

/-- 相对位置的声明式刻画：`RelPos.Holds x y k` 表示前 `x`、后 `y` 满足类别 `k` 的几何条件；
在不变式下五类互斥穷尽，且与 `relPos` 的计算一致。

[020:58]
> 后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。
-/
def RelPos.Holds (x y : CoreHull P) : RelPos → Prop
  | RelPos.sepUp => x.gg < y.dd
  | RelPos.sepDown => y.gg < x.dd
  | RelPos.expandUp => x.zg < y.zd ∧ y.dd ≤ x.gg
  | RelPos.expandDown => y.zg < x.zd ∧ x.dd ≤ y.gg
  | RelPos.coreOverlap => max x.zd y.zd ≤ min x.zg y.zg

/-- `RelPos.Holds` 可判定。

[020:58]
> 后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。
-/
instance instDecidableRelPosHolds (x y : CoreHull P) :
    (k : RelPos) → Decidable (RelPos.Holds x y k)
  | RelPos.sepUp => inferInstanceAs (Decidable (x.gg < y.dd))
  | RelPos.sepDown => inferInstanceAs (Decidable (y.gg < x.dd))
  | RelPos.expandUp => inferInstanceAs (Decidable (x.zg < y.zd ∧ y.dd ≤ x.gg))
  | RelPos.expandDown => inferInstanceAs (Decidable (y.zg < x.zd ∧ x.dd ≤ y.gg))
  | RelPos.coreOverlap => inferInstanceAs (Decidable (max x.zd y.zd ≤ min x.zg y.zg))

end Chan.Defs.Order
