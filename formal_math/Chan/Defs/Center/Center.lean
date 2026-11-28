module

public import Chan.Defs.Alt.Basic
public import Chan.Defs.Order.IntervalAlg

@[expose] public section

namespace Chan.Defs

open Chan.Defs.Alt Chan.Defs.Order Chan.Defs.Path
variable {P : Type _} [LinearOrder P]

/-- 三段公共交的候选下沿与上沿；两端可以交错，不能预设成核。
[020:48] 有了上面的定理，就可以很精确地讨论走势中枢的问题了：根据走势中枢的数学表达式： A、B、C，分别的高、低点是a1\a2,b1\b2,c1\c2，则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。 -/
def Center.seedBounds (a b c : Seg P) : P × P :=
  (max (max a.range.lo b.range.lo) c.range.lo, min (min a.range.hi b.range.hi) c.range.hi)

/-- 在同一序列确有这三个连续位置，且闭区间公共交非空。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
def Center.CanSeedCenter (xs : List (Seg P)) (i : Nat) : Bool :=
  match xs[i]?, xs[i+1]?, xs[i+2]? with
  | some a, some b, some c => decide ((Center.seedBounds a b c).1 ≤ (Center.seedBounds a b c).2)
  | _, _, _ => false

/-- 从 start 起三段成核；其余各段只能延伸此核。stop 与波动包络由覆盖段导出。
[020:48] 有了上面的定理，就可以很精确地讨论走势中枢的问题了：根据走势中枢的数学表达式： A、B、C，分别的高、低点是a1\a2,b1\b2,c1\c2，则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。
[020:56] 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。 -/
structure Center (P : Type _) [LinearOrder P] where
  start : Nat
  a : Seg P
  b : Seg P
  c : Seg P
  more : List (Seg P)
  alternating : (a :: b :: c :: more).IsChain (fun x y => x.dir ≠ y.dir)
  seed : (Center.seedBounds a b c).1 ≤ (Center.seedBounds a b c).2
  extension : ∀ s ∈ more, overlaps ⟨(Center.seedBounds a b c).1, (Center.seedBounds a b c).2, seed⟩ s.range
  deriving DecidableEq

end Chan.Defs

namespace Chan.Defs.Center

open Chan.Defs.Alt Chan.Defs.Order Chan.Defs.Path
variable {P : Type _} [LinearOrder P]

/-- 核在延伸过程中固定为最初三段的交。
[020:54] 特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理： -/
def core (z : Center P) : Bar P := ⟨_, _, z.seed⟩

/-- 完整覆盖的段列，前三段都已完成。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
def cover (z : Center P) := z.a :: z.b :: z.c :: z.more

/-- 覆盖范围的右开边界，同时是下一段可用的最早位置。
[020:56] 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。 -/
def stop (z : Center P) := z.start + z.cover.length

/-- 从核起逐段扩张包络；核已含于初始三段，结果恰为全部覆盖段的凸包。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def zone (z : Center P) : CoreHull P :=
  z.cover.foldl (fun x s => ⟨x.core,
    ⟨min x.hull.lo s.range.lo, max x.hull.hi s.range.hi,
      le_trans (min_le_left _ _) (le_trans x.hull.ordered (le_max_left _ _))⟩,
    le_trans (min_le_left _ _) x.inside.1, le_trans x.inside.2 (le_max_left _ _)⟩)
    ⟨z.core, z.core, le_refl _, le_refl _⟩

/-- 从指定的左闭右开窗口取证，不把越界截短误认作成核或延伸。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。
[020:56] 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。 -/
def window? (xs : List (Seg P)) (i j : Nat) : Option (Center P) := do
  if j > xs.length then none else
    match xs.extract i j with
    | a :: b :: c :: tail =>
      if h : (a :: b :: c :: tail).IsChain (fun x y => x.dir ≠ y.dir) then
        if k : (seedBounds a b c).1 ≤ (seedBounds a b c).2 then
          if e : ∀ s ∈ tail, overlaps ⟨_, _, k⟩ s.range then some ⟨i,a,b,c,tail,h,k,e⟩
          else none
        else none
      else none
    | _ => none

/-- 检查紧接在中枢之后的候选段是否触核；相触可延伸。
[020:56] 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
abbrev extendsWith (z : Center P) (s : Seg P) := overlaps z.core s.range

/-- 整段严格高于核，区别于仅终点冲出上沿。
[020:56] 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。 -/
abbrev leavesUp (z : Center P) (s : Seg P) := strictAbove s.range z.core.hi

/-- 整段严格低于核，区别于仅终点穿过下沿。
[020:56] 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。 -/
abbrev leavesDown (z : Center P) (s : Seg P) := strictBelow s.range z.core.lo

/-- 候选离开段的极值须严格越过核上沿，回试段整体严格留在上方。

[018:64] 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。
-/
abbrev thirdBuyEvent (z : Center P) (leave back : Seg P) : Prop :=
  leave.dir = .up ∧ z.core.hi < leave.range.hi ∧ back.dir = .down ∧ z.leavesUp back

/-- 向下离开与首次向上回试；相触仍归核内震荡。

[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。
-/
abbrev thirdSellEvent (z : Center P) (leave back : Seg P) : Prop :=
  leave.dir = .down ∧ leave.range.lo < z.core.lo ∧ back.dir = .up ∧ z.leavesDown back

/-- 只允许末覆盖段兼离开，或覆盖范围后紧接的跳空离开。 -/
def thirdAt (z : Center P) (d : Dir) (xs : List (Seg P)) (k : Nat) : Bool :=
  decide (xs.extract z.start z.stop = z.cover) &&
    match xs[k]?, xs[k+1]? with
    | some leave, some back =>
      match d with
      | .up => (k + 1 == z.stop || (k == z.stop && decide (z.leavesUp leave))) &&
          decide (z.thirdBuyEvent leave back)
      | .down => (k + 1 == z.stop || (k == z.stop && decide (z.leavesDown leave))) &&
          decide (z.thirdSellEvent leave back)
    | _, _ => false

/-- 向上第三类事件的序列定位：回试必须紧接离开段。

[020:62] 注意，第三类买卖点比第一、二类要后知后觉，但如果抓得好，往往不用浪费盘整的时间，比较适合短线技术较好的资金，但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。
-/
def thirdBuyAt (z : Center P) (xs : List (Seg P)) (k : Nat) : Bool := z.thirdAt .up xs k

/-- 向下第三类事件的序列定位，含第三成核段兼离开段。

[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。
-/
def thirdSellAt (z : Center P) (xs : List (Seg P)) (k : Nat) : Bool := z.thirdAt .down xs k

/-- 在两个允许衔接的位置中取实际破坏的离开段下标。 -/
def departureIndex? (z : Center P) (d : Dir) (xs : List (Seg P)) : Option Nat :=
  [z.stop - 1, z.stop].find? (z.thirdAt d xs)

/-- 任一方向发生第三类事件即破坏；未发生时不假定它终将出现。

[018:64] 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。
-/
def destroyed (z : Center P) (xs : List (Seg P)) : Bool :=
  (z.departureIndex? .up xs).isSome || (z.departureIndex? .down xs).isSome

/-- 中枢取序对偶，保留来源位置和覆盖证据。 -/
def dual (z : Center P) : Center (OrderDual P) := by
  refine ⟨z.start, dualSeg z.a, dualSeg z.b, dualSeg z.c, z.more.map dualSeg, ?_, ?_, ?_⟩
  · change List.IsChain _ (z.cover.map dualSeg)
    exact List.isChain_map_of_isChain dualSeg (by
      intro a b h
      change a.dir.flip ≠ b.dir.flip
      cases ha : a.dir <;> cases hb : b.dir <;> simp_all [Dir.flip]) z.alternating
  · simpa only [seedBounds, dualSeg, dualBar, ← toDual_min, ← toDual_max, OrderDual.toDual_le_toDual] using z.seed
  · intro s hs
    obtain ⟨a, ha, rfl⟩ := List.mem_map.mp hs
    simpa only [overlaps, seedBounds, dualSeg, dualBar, ← toDual_min, ← toDual_max, OrderDual.toDual_le_toDual] using z.extension a ha

end Chan.Defs.Center
