module

public import Chan.Defs.Alt.Basic
public import Chan.Defs.Order.IntervalAlg

@[expose] public section

namespace Chan.Defs.Center

open Chan.Defs.Alt Chan.Defs.Order Chan.Defs.Path
variable {P : Type _} [Std.LinearOrderPackage P]

/-- 三段公共交的候选下沿与上沿；两端可以交错，不能预设成核。
[020:48] 有了上面的定理，就可以很精确地讨论走势中枢的问题了：根据走势中枢的数学表达式： A、B、C，分别的高、低点是a1\a2,b1\b2,c1\c2，则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。 -/
def seedBounds (a b c : Seg P) : P × P :=
  (max (max a.range.lo b.range.lo) c.range.lo, min (min a.range.hi b.range.hi) c.range.hi)

/-- 在同一序列确有这三个连续位置，且闭区间公共交非空。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
def CanSeedCenter (xs : AltSeq P) (i : Nat) : Bool :=
  match xs.items[i]?, xs.items[i+1]?, xs.items[i+2]? with
  | some a, some b, some c => decide ((seedBounds a b c).1 ≤ (seedBounds a b c).2)
  | _, _, _ => false

/-- 从 start 起三段成核；其余各段只能延伸此核。stop 与波动包络由覆盖段导出。
[020:48] 有了上面的定理，就可以很精确地讨论走势中枢的问题了：根据走势中枢的数学表达式： A、B、C，分别的高、低点是a1\a2,b1\b2,c1\c2，则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。
[020:56] 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。 -/
structure Center (P : Type _) [Std.LinearOrderPackage P] where
  start : Nat
  a : Seg P
  b : Seg P
  c : Seg P
  more : List (Seg P)
  alternating : ∀ p ∈ (a :: b :: c :: more).zip (b :: c :: more), p.1.dir ≠ p.2.dir
  seed : (seedBounds a b c).1 ≤ (seedBounds a b c).2
  extension : ∀ s ∈ more, overlaps ⟨(seedBounds a b c).1, (seedBounds a b c).2, seed⟩ s.range
  deriving DecidableEq

/-- 核在延伸过程中固定为最初三段的交。
[020:54] 特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理： -/
def Center.core (z : Center P) : Bar P := ⟨_, _, z.seed⟩

/-- 完整覆盖的段列，前三段都已完成。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
def Center.cover (z : Center P) := z.a :: z.b :: z.c :: z.more

/-- 覆盖范围的右开边界，同时是下一段可用的最早位置。
[020:56] 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。 -/
def Center.stop (z : Center P) := z.start + z.cover.length

/-- 从核起逐段扩张包络；核已含于初始三段，结果恰为全部覆盖段的凸包。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def Center.zone (z : Center P) : CoreHull P :=
  z.cover.foldl (fun x s => ⟨x.core,
    ⟨min x.hull.lo s.range.lo, max x.hull.hi s.range.hi,
      Std.le_trans Std.min_le_left (Std.le_trans x.hull.ordered Std.left_le_max)⟩,
    Std.le_trans Std.min_le_left x.inside.1, Std.le_trans x.inside.2 Std.left_le_max⟩)
    ⟨z.core, z.core, Std.le_refl _, Std.le_refl _⟩

/-- 从指定的左闭右开窗口取证，不把越界截短误认作成核或延伸。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。
[020:56] 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。 -/
def Center.window? (xs : List (Seg P)) (i j : Nat) : Option (Center P) := do
  if j > xs.length then none else
    match xs.extract i j with
    | a :: b :: c :: tail =>
      if h : ∀ p ∈ (a :: b :: c :: tail).zip (b :: c :: tail), p.1.dir ≠ p.2.dir then
        if k : (seedBounds a b c).1 ≤ (seedBounds a b c).2 then
          if e : ∀ s ∈ tail, overlaps ⟨_, _, k⟩ s.range then some ⟨i,a,b,c,tail,h,k,e⟩
          else none
        else none
      else none
    | _ => none

/-- 检查紧接在中枢之后的候选段是否触核；相触可延伸。
[020:56] 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
abbrev Center.extendsWith (z : Center P) (s : Seg P) := overlaps z.core s.range

/-- 整段严格高于核，区别于仅终点冲出上沿。
[020:56] 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。 -/
abbrev Center.leavesUp (z : Center P) (s : Seg P) := strictAbove s.range z.core.hi

/-- 整段严格低于核，区别于仅终点穿过下沿。
[020:56] 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。 -/
abbrev Center.leavesDown (z : Center P) (s : Seg P) := strictBelow s.range z.core.lo

/-- 紧随中枢的离开段及其第一次反向回试，二者均须在核的指定一侧。
[018:64] 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
def Center.thirdEvent (z : Center P) (d : Dir) (xs : List (Seg P)) : Bool :=
  decide (xs.extract z.start z.stop = z.cover) &&
    match xs[z.stop]?, xs[z.stop+1]? with
    | some a, some b => decide (a.dir = d ∧ b.dir = d.flip) &&
      match d with
      | .up => decide (z.leavesUp a ∧ z.leavesUp b)
      | .down => decide (z.leavesDown a ∧ z.leavesDown b)
    | _, _ => false

/-- 向上破坏，触及上沿仍是震荡。
[018:64] 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
def Center.thirdBuyEvent (z : Center P) := z.thirdEvent .up

/-- 向下破坏，触及下沿仍是震荡。
[018:64] 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
def Center.thirdSellEvent (z : Center P) := z.thirdEvent .down

/-- 两个方向的破坏事件并集，不假定它终将发生。
[018:64] 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。 -/
def Center.destroyed (z : Center P) (xs : List (Seg P)) : Bool :=
  z.thirdBuyEvent xs || z.thirdSellEvent xs

/-- 中枢取对偶：逐段交换上下，保留起点、覆盖段数和延伸证据。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def Center.dual (z : Center P) : Center (PriceDual P) := by
  have rev (a b : P) : (asDual a ≤ asDual b) ↔ (b ≤ a) := Iff.rfl
  have mn (a b : P) : min (asDual a) (asDual b) = asDual (max a b) := by
    rw [Std.min_eq_ite, Std.max_eq_ite]
    by_cases h : b ≤ a
    · rw [ite_eq_left h, ite_eq_left (show asDual a ≤ asDual b from h)]
    · rw [ite_eq_right h, ite_eq_right (show ¬asDual a ≤ asDual b from h)]
  have mx (a b : P) : max (asDual a) (asDual b) = asDual (min a b) := by
    rw [Std.min_eq_ite, Std.max_eq_ite]
    by_cases h : a ≤ b
    · rw [ite_eq_left h, ite_eq_left (show asDual b ≤ asDual a from h)]
    · rw [ite_eq_right h, ite_eq_right (show ¬asDual b ≤ asDual a from h)]
  refine ⟨z.start, dualSeg z.a, dualSeg z.b, dualSeg z.c, z.more.map dualSeg, ?_, ?_, ?_⟩
  · change ∀ p ∈ (z.cover.map dualSeg).zip ((z.b :: z.c :: z.more).map dualSeg), _
    rw [List.zip_map]
    intro p hp
    obtain ⟨⟨a,b⟩, h, rfl⟩ := List.mem_map.mp hp
    have hne := z.alternating (a,b) h
    change a.dir.flip ≠ b.dir.flip
    cases ha : a.dir <;> cases hb : b.dir <;> simp_all [Dir.flip]
  · simpa only [seedBounds, dualSeg, dualBar, mn, mx, rev] using z.seed
  · intro s hs
    obtain ⟨a,ha,rfl⟩ := List.mem_map.mp hs
    simpa only [overlaps, seedBounds, dualSeg, dualBar, mn, mx, rev] using z.extension a ha

end Chan.Defs.Center
