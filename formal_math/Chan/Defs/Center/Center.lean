module

public import Chan.Defs.Order.IntervalAlg
public import Chan.Defs.Alt.Basic

/-!
# M5 中枢

三段成核取闭区间公共交；延伸按与核闭重叠判定（单点相触算重叠）；离开与第三类事件
须严格越过核边界（分叉 4）。延伸与破坏按区间几何写死，不假定震荡必然结束（清单 B-37）。
-/

@[expose] public section

namespace Chan.Defs

open Chan.Defs.Order

universe u

/-- 中枢：覆盖段范围 `[first, first + count)`（`count ≥ 3`）、核区间 `[ZD, ZG]`
与波动区间 `[DD, GG]`，携带核含于波动区间的不变式。与具体段序列的一致性见 `Center.WellFormed`。
结构本身即命名空间 `Chan.Defs.Center`，其成员（`Center.extendsWith` 等）位于该命名空间下。

[018:24]
> 注意，次级别的前三个走势类型都是完成的才构成该级别的缠中说禅走势中枢，完成的走势类型
-/
structure Center (P : Type u) [LinearOrder P] where
  /-- 首段下标。 -/
  first : Nat
  /-- 覆盖段数。 -/
  count : Nat
  /-- 至少三段。 -/
  count_ge : 3 ≤ count
  /-- 核与波动区间。 -/
  ch : CoreHull P

end Chan.Defs

namespace Chan.Defs.Center

open Chan.Defs.Order Chan.Defs.Alt

universe u

variable {P : Type u} [LinearOrder P]

/-- 连续三段的值域闭区间存在非空公共交（最大低点不超过最小高点）。

[020:48]
> 则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。
-/
def CanSeedCenter (a b c : Seg P) : Prop := overlapsList [a.range, b.range, c.range]

/-- `CanSeedCenter` 可判定。

[020:48]
> 则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。
-/
instance instDecidableCanSeedCenter (a b c : Seg P) : Decidable (CanSeedCenter a b c) := by
  unfold CanSeedCenter; infer_instance

/-- 段序列在下标 `k` 起的连续三段能否成核（布尔判别）。

[018:24]
> 注意，次级别的前三个走势类型都是完成的才构成该级别的缠中说禅走势中枢，完成的走势类型
-/
def seedAtB (segs : List (Seg P)) (k : Nat) : Bool :=
  match List.drop k segs with
  | a :: b :: c :: _ => decide (CanSeedCenter a b c)
  | _ => false

/-- 下标 `k` 起三段的值域列表（成核三段）。

[020:48]
> 则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。
-/
def seedCore (segs : List (Seg P)) (k : Nat) : List (Bar P) :=
  List.map (fun s : Seg P => s.range) (List.take 3 (List.drop k segs))

/-- 自给定段列表开头起，连续与成核三段公共交闭重叠的段数（遇第一段不重叠即停）。
段 `x` 与核闭重叠当且仅当 `x` 与成核三段四者公共交非空。

[020:56]
> 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。
-/
def coreRun (core3 : List (Bar P)) : List (Seg P) → Nat
  | [] => 0
  | x :: xs => if overlapsList (x.range :: core3) then coreRun core3 xs + 1 else 0

/-- 自 `k` 起成核后的中枢延伸总段数（三段成核加其后连续重叠段数），不设上限。

[018:40]
> 例如一个盘整，三个重叠的连续次级别走势类型后，盘整就可以随时完成，也就是说，只要三个重叠的连续次级别走势类型走出来后，盘整随时结束都是完美的，但这可以不结束，可以不断延伸下去，不断围绕这缠中说禅中枢上上下下地延伸下去直到无穷都是可以的。
-/
def seedRunLen (segs : List (Seg P)) (k : Nat) : Nat :=
  3 + coreRun (seedCore segs k) (List.drop (k + 3) segs)

/-- 核下沿 `ZD`。

[020:54]
> 特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：
-/
def zd (c : Center P) : P := c.ch.core.lo

/-- 核上沿 `ZG`。

[020:54]
> 特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：
-/
def zg (c : Center P) : P := c.ch.core.hi

/-- 波动区间下沿 `DD`。

[020:58]
> 前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；
-/
def dd (c : Center P) : P := c.ch.hull.lo

/-- 波动区间上沿 `GG`。

[020:58]
> 后DD>前GG等价于上涨及其延续。
-/
def gg (c : Center P) : P := c.ch.hull.hi

/-- 核区间 `[ZD, ZG]`。

[020:54]
> 显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：
-/
def core (c : Center P) : Bar P := c.ch.core

/-- 中枢在段序列中覆盖的段。

[018:24]
> 注意，次级别的前三个走势类型都是完成的才构成该级别的缠中说禅走势中枢，完成的走势类型
-/
def covered (segs : List (Seg P)) (c : Center P) : List (Seg P) :=
  List.take c.count (List.drop c.first segs)

/-- 中枢与段序列一致：覆盖段数足额；核恰为前三段值域公共交；波动区间恰为全部覆盖段值域凸包；
第四段起每段与核闭重叠（延伸）。

[020:48]
> 则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。
-/
def WellFormed (segs : List (Seg P)) (c : Center P) : Prop :=
  (Chan.Defs.Center.covered segs c).length = c.count ∧
  (∀ s ∈ List.take 3 (Chan.Defs.Center.covered segs c), s.range.lo ≤ c.zd ∧ c.zg ≤ s.range.hi) ∧
  (∃ s ∈ List.take 3 (Chan.Defs.Center.covered segs c), s.range.lo = c.zd) ∧
  (∃ s ∈ List.take 3 (Chan.Defs.Center.covered segs c), s.range.hi = c.zg) ∧
  (∀ s ∈ Chan.Defs.Center.covered segs c, c.dd ≤ s.range.lo ∧ s.range.hi ≤ c.gg) ∧
  (∃ s ∈ Chan.Defs.Center.covered segs c, s.range.lo = c.dd) ∧
  (∃ s ∈ Chan.Defs.Center.covered segs c, s.range.hi = c.gg) ∧
  (∀ s ∈ List.drop 3 (Chan.Defs.Center.covered segs c), overlaps s.range c.core)

/-- `Center.WellFormed` 可判定。

[020:48]
> 则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。
-/
instance instDecidableWellFormed (segs : List (Seg P)) (c : Center P) :
    Decidable (c.WellFormed segs) := by
  unfold Chan.Defs.Center.WellFormed; infer_instance

/-- 延伸：单段值域与核 `[ZD, ZG]` 闭重叠（单点相触算重叠）。核保持初始值不变。

[020:56]
> 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。
-/
def extendsWith (c : Center P) (s : Seg P) : Prop := overlaps s.range c.core

/-- `Center.extendsWith` 可判定。

[020:56]
> 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。
-/
instance instDecidableExtendsWith (c : Center P) (s : Seg P) :
    Decidable (c.extendsWith s) := by
  unfold Chan.Defs.Center.extendsWith; infer_instance

/-- 向上严格离开核：段值域整体严格高于 `ZG`（低点 `> ZG`，端点相触不算离开）。

[054:24]
> 而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。
-/
def leavesUp (c : Center P) (s : Seg P) : Prop := c.zg < s.range.lo

/-- `Center.leavesUp` 可判定。

[054:24]
> 而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。
-/
instance instDecidableLeavesUp (c : Center P) (s : Seg P) : Decidable (c.leavesUp s) := by
  unfold Chan.Defs.Center.leavesUp; infer_instance

/-- 向下严格离开核：段值域整体严格低于 `ZD`（高点 `< ZD`）。

[054:24]
> 而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。
-/
def leavesDown (c : Center P) (s : Seg P) : Prop := s.range.hi < c.zd

/-- `Center.leavesDown` 可判定。

[054:24]
> 而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。
-/
instance instDecidableLeavesDown (c : Center P) (s : Seg P) : Decidable (c.leavesDown s) := by
  unfold Chan.Defs.Center.leavesDown; infer_instance

/-- 向上第三类事件：向上段 `leave` 高点严格越过 `ZG`，紧接的向下回抽段 `back` 整体严格高于
`ZG`（低点 `> ZG`）。主线按 `054:24` 严格不等号，不采 `020:60` 字面“不跌破”。

[018:64]
> 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。

[054:24]
> 当然，如果前面d1>g2，那g2就是第三类卖点了。
-/
def thirdBuyEvent (c : Center P) (leave back : Seg P) : Prop :=
  leave.dir = Dir.up ∧ c.zg < leave.range.hi ∧ back.dir = Dir.down ∧ c.leavesUp back

/-- `Center.thirdBuyEvent` 可判定。

[018:64]
> 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。
-/
instance instDecidableThirdBuyEvent (c : Center P) (leave back : Seg P) :
    Decidable (c.thirdBuyEvent leave back) := by
  unfold Chan.Defs.Center.thirdBuyEvent; infer_instance

/-- 向下第三类事件：向下段 `leave` 低点严格跌破 `ZD`，紧接的向上回抽段 `back` 整体严格低于
`ZD`（高点 `< ZD`）。

[054:24]
> 而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。
-/
def thirdSellEvent (c : Center P) (leave back : Seg P) : Prop :=
  leave.dir = Dir.down ∧ leave.range.lo < c.zd ∧ back.dir = Dir.up ∧ c.leavesDown back

/-- `Center.thirdSellEvent` 可判定。

[054:24]
> 而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。
-/
instance instDecidableThirdSellEvent (c : Center P) (leave back : Seg P) :
    Decidable (c.thirdSellEvent leave back) := by
  unfold Chan.Defs.Center.thirdSellEvent; infer_instance

/-- 中枢破坏：发生向上或向下第三类事件。

[018:64]
> 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。
-/
def destroyed (c : Center P) (leave back : Seg P) : Prop :=
  c.thirdBuyEvent leave back ∨ c.thirdSellEvent leave back

/-- `Center.destroyed` 可判定。

[018:64]
> 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。
-/
instance instDecidableDestroyed (c : Center P) (leave back : Seg P) :
    Decidable (c.destroyed leave back) := by
  unfold Chan.Defs.Center.destroyed; infer_instance

/-- 段序列中下标 `k`、`k+1` 两段构成向上第三类事件（布尔判别）。

[020:62]
> 但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。
-/
def thirdBuyAt (c : Center P) (segs : List (Seg P)) (k : Nat) : Bool :=
  match List.drop k segs with
  | a :: b :: _ => decide (c.thirdBuyEvent a b)
  | _ => false

/-- 段序列中下标 `k`、`k+1` 两段构成向下第三类事件（布尔判别）。

[020:62]
> 但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。
-/
def thirdSellAt (c : Center P) (segs : List (Seg P)) (k : Nat) : Bool :=
  match List.drop k segs with
  | a :: b :: _ => decide (c.thirdSellEvent a b)
  | _ => false

end Chan.Defs.Center
