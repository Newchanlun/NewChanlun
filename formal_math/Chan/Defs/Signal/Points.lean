module

public import Chan.Defs.Signal.Phase

@[expose] public section

namespace Chan.Defs.Signal

open Chan.Defs.Order Chan.Defs.Alt Chan.Defs.Center Chan.Defs.Level
variable {P : Type _} [LinearOrder P]

/-- 由调用者比较同一分解、同一中枢前后的同向段。返回真表示末段力度衰减。
[053:28] 第一类买卖点，就是该级别的背驰点，这足以应付最大多数的情况，但有一种情况是不可以的，就是前面反复强调的小级别转大级别的情况。
[101:20] 第一类买卖点就是背驰点，第三类买卖点就是中枢破坏点，这都是很清楚的。 -/
abbrev StrengthJudge (P : Type _) [LinearOrder P] :=
  Decomposition P → Center P → Nat → Nat → Bool

/-- 买侧用升序，卖侧用反序，使同一判据可镜像使用。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def ahead (side : Dir) (x y : P) : Bool :=
  match side with | .up => decide (y < x) | .down => decide (x < y)

/-- 指定方向的离开边界：向上看上沿，向下看下沿。
[020:54] 特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理： -/
def edge (side : Dir) (b : Bar P) : P := match side with | .up => b.hi | .down => b.lo

/-- 独立几何模板：起于界内，或从仍触界的前一段首次跳到界外；回试必须严格留在界外。 #2296 U-3 分别参数化跳空和实际终点口径。
模板用调用方给定的 `zone` 同时约束起点和突破边界。`thirdGeometry` 则区分前序波动凸包与核边界；
两者不互为失败后的替代判据。

[018:64] 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。
[020:62] 注意，第三类买卖点比第一、二类要后知后觉，但如果抓得好，往往不用浪费盘整的时间，比较适合短线技术较好的资金，但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。
-/
def BreakoutRetest (side : Dir) (zone : Bar P) (xs : List (Seg P)) (cut : Nat)
    (prices : Nat → Option (P × P)) (allowGapLeave useExitEndpoint : Bool) : Bool :=
  if cut < 2 then false else
    let i := cut-2
    match xs[i]?, xs[i+1]? with
    | some leave, some test =>
      let endpoints := if useExitEndpoint then prices i
        else some (edge side.flip leave.range, edge side leave.range)
      match endpoints with
      | none => false
      | some (entry, exit) =>
        let limit := edge side zone
        let startsInside := decide (zone.lo ≤ entry ∧ entry ≤ zone.hi)
        let firstGap := allowGapLeave && decide (0 < i) &&
          ahead side (edge side.flip leave.range) limit &&
          (xs[i-1]?.any fun prior => decide (overlaps zone prior.range))
        decide (leave.dir = side ∧ test.dir = side.flip) && (startsInside || firstGap) &&
          ahead side exit limit && ahead side (edge side.flip test.range) limit
    | _, _ => false

/-- #2296 / #2322（needs-fable U-2）：一类点离开核或再创新极值。 -/
inductive FirstExitThreshold where
  | core | hull
  deriving DecidableEq

/-- 转折必须是已完成反向趋势的结束切点；最后中枢之后确有 c 段，并由同向比较段检验背驰。
在 `cut = origin` 处阶段恒为中阴；此处真正的准入约束是结束于该切点的 `Finished` 认证。
[017:60] 因为某种类型的走势完成以后就会转化为其他类型的走势，对于下跌的走势来说，一旦完成，只能转化为上涨与盘整，因此，一旦能把握下跌走势转化的关节点买入，就在市场中占据了一个最有利的位置，而这个买点，就是前面反复强调的“第一类买点”；
[053:28] 第一类买卖点，就是该级别的背驰点，这足以应付最大多数的情况，但有一种情况是不可以的，就是前面反复强调的小级别转大级别的情况。 -/
def firstPoint (d : Decomposition P) (judge : StrengthJudge P) (threshold : FirstExitThreshold)
    (side : Dir) (cut : Nat) : Bool :=
  let trend := match side with | .up => TrendKind.downtrend | .down => TrendKind.uptrend
  decide (cut = d.origin ∧ phaseAt d cut = some .transition) &&
    d.ledger.completed.any fun b => decide (b.stop = cut ∧ classifyTrend b = some trend) &&
      match b.centers.reverse, d.steps[cut-1]?, d.prices? (cut-1) with
      | z :: prev :: _, some c, some (_,lastPrice) =>
        let exitZone := match threshold with | .core => z.core | .hull => z.zone.hull
        decide (z.stop < cut ∧ prev.stop < z.start ∧ c.dir = side.flip) &&
          ahead side.flip lastPrice (edge side.flip exitZone) &&
          (List.range (z.start - prev.stop)).any fun n =>
            let i := prev.stop+n
            (d.steps[i]?).any fun connector =>
              decide (connector.dir = c.dir) && judge d z i (cut-1)
      | _, _, _ => false

/-- 下跌趋势完成处的一买。
[017:60] 因为某种类型的走势完成以后就会转化为其他类型的走势，对于下跌的走势来说，一旦完成，只能转化为上涨与盘整，因此，一旦能把握下跌走势转化的关节点买入，就在市场中占据了一个最有利的位置，而这个买点，就是前面反复强调的“第一类买点”；
[101:20] 第一类买卖点就是背驰点，第三类买卖点就是中枢破坏点，这都是很清楚的。 -/
def isFirstBuy (d : Decomposition P) (judge : StrengthJudge P)
    (threshold : FirstExitThreshold) (cut : Nat) :=
  firstPoint d judge threshold .up cut

/-- 上涨趋势完成处的一卖。
[017:70] “缠中说禅趋势转折定律”：任何级别的上涨转折都是由某级别的第一类卖点构成的；任何的下跌转折都是由某级别的第一类买点构成的。
[101:20] 第一类买卖点就是背驰点，第三类买卖点就是中枢破坏点，这都是很清楚的。 -/
def isFirstSell (d : Decomposition P) (judge : StrengthJudge P)
    (threshold : FirstExitThreshold) (cut : Nat) :=
  firstPoint d judge threshold .down cut

/-- 最强、次强、较弱；后两类由二类点是否严格优于一类点区分。
[101:28] 第二类买点刚好构成原来下跌的最后一个中枢开始的震荡走势的第三类买点，也就是第二、三类买点合一了，这是最强的走势，这情况，一般都对应V型反转的快速回升，是最有力度的。
[101:32] 第二类买点跌破第一类买点，也就是第二类买点比第一类买点低，这是完全可以的，这里一般都构成盘整背驰
[101:38] 这种情况下，第一、二、三买点，是依次向上，一个比一个高。 -/
inductive SecondStrength where
  | strongest | intermediate | weak
  deriving DecidableEq

/-- 最近同级枢的末覆盖段或紧随其后的跳空段可以离开。连续离开前的起价须在已见波动内，第 3 段兼离开时只用其前两段的波动。
与 `BreakoutRetest` 的固定区间模板不同，此处以先前波动校验起价，以中枢核校验离开和回试。

[020:62] 注意，第三类买卖点比第一、二类要后知后觉，但如果抓得好，往往不用浪费盘整的时间，比较适合短线技术较好的资金，但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。
-/
def thirdGeometry (d : Decomposition P) (side : Dir) (cut : Nat) : Bool :=
  if cut < 2 then false else
    let i := cut-2
    match d.recent d.origin cut, d.prices? i with
    | some z, some (entry,_) =>
      decide (z.start+2 ≤ i) && z.thirdAt side d.steps i &&
        if i == z.stop then true
        else match d.steps.extract z.start i with
          | [] => false
          | a :: prior =>
            let hull := hullInterval a.range (prior.map Seg.range)
            decide (hull.lo ≤ entry ∧ entry ≤ hull.hi)
    | _, _ => false

/-- 版本四：一类点后的两段依次反弹、回试。强弱取实际终点；二三合一要求回试全段严格越过原中枢边界，单点相触不计。
一类点切点 `cut-2 = origin` 处的中阴门由 `firstPoint` 的 `Finished` 认证约束；
本函数另查二类点的切点 `cut` 是否仍在中阴。
[101:22] 其实，所谓第二类买点，就是第一类买点的次级别回抽结束后再次探底或回试的那个次级别走势的结束点。这个定义在前面说得很清楚。
[057:40] 如果那7当成是第一类买点，那么9就是第二类买点了，这符合次级别上，次级别下，不创新低或盘整背驰的定义，对比一下2点和9点，一卖一买，都是第二类的。
[101:28] 第二类买点刚好构成原来下跌的最后一个中枢开始的震荡走势的第三类买点，也就是第二、三类买点合一了，这是最强的走势，这情况，一般都对应V型反转的快速回升，是最有力度的。
[101:32] 第二类买点跌破第一类买点，也就是第二类买点比第一类买点低，这是完全可以的，这里一般都构成盘整背驰
[101:38] 这种情况下，第一、二、三买点，是依次向上，一个比一个高。 -/
def secondStrength? (d : Decomposition P) (judge : StrengthJudge P)
    (threshold : FirstExitThreshold) (side : Dir) (cut : Nat) : Option SecondStrength := do
  if cut < 3 || !(firstPoint d judge threshold side (cut-2)) ||
      phaseAt d cut != some .transition then none else
    let rebound ← d.steps[cut-2]?
    let test ← d.steps[cut-1]?
    let (_,firstPrice) ← d.prices? (cut-3)
    let (_,secondPrice) ← d.prices? (cut-1)
    let z ← d.recent 0 (cut-2)
    if rebound.dir != side || test.dir != side.flip then none
    else if ahead side (edge side.flip test.range) (edge side z.core)
      then some .strongest
    else if ahead side secondPrice firstPrice then some .intermediate
    else some .weak

/-- 中阴阶段，一买后次级别上、次级别下的结束点。
[101:22] 其实，所谓第二类买点，就是第一类买点的次级别回抽结束后再次探底或回试的那个次级别走势的结束点。这个定义在前面说得很清楚。 -/
def isSecondBuy (d : Decomposition P) (judge : StrengthJudge P)
    (threshold : FirstExitThreshold) (cut : Nat) :=
  (secondStrength? d judge threshold .up cut).isSome

/-- 二卖使用完全相同的次级别时序，价格比较反序。
[017:66] “缠中说禅买卖点定律一”：任何级别的第二类买卖点都由次级别相应走势的第一类买点构成。
[101:22] 其实，所谓第二类买点，就是第一类买点的次级别回抽结束后再次探底或回试的那个次级别走势的结束点。这个定义在前面说得很清楚。 -/
def isSecondSell (d : Decomposition P) (judge : StrengthJudge P)
    (threshold : FirstExitThreshold) (cut : Nat) :=
  (secondStrength? d judge threshold .down cut).isSome

/-- 在所选观察阶段，确立后的最近同级枢由震荡转入离开；不按底部或顶部另设例外。
[018:64] 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。
[020:62] 注意，第三类买卖点比第一、二类要后知后觉，但如果抓得好，往往不用浪费盘整的时间，比较适合短线技术较好的资金，但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
def thirdPoint (d : Decomposition P) (side : Dir) (cut : Nat) : Bool :=
  thirdGeometry d side cut && decide (phaseAt d cut = some .departure) &&
    (decide (phaseAt d (cut-2) = some .oscillation) ||
      (d.recent d.origin cut).any (fun z => z.start + 2 == cut - 2))

/-- 次级别离开与第一次回试。相触按第 54 课仍归震荡。
第 20 课本条字面与 #2295 分叉 4 相反，主线按下列第 54 课第 24 行的严格不等号。
[020:60] 一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
def isThirdBuy (d : Decomposition P) (cut : Nat) :=
  decide (0 < d.depth) && thirdPoint d .up cut

/-- 次级别向下破核后，首个向上回试严格留在核下方。
[018:64] 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
def isThirdSell (d : Decomposition P) (cut : Nat) :=
  decide (0 < d.depth) && thirdPoint d .down cut

/-- 基底不可再分，以相邻两个基底段判类三买。
[017:40] 这里有一个递归的问题，就是这次级别不能无限下去，就像有些半吊子哲学胡诌什么，而“分”不是无限的，按照量子力学，物质之分是有极限的，同样，级别之次也不可能无限，在实际之中，对最后不能分解的级别，其缠中说禅走势中枢就不能用“至少三个连续次级别走势类型所重叠”定义，而定义为至少三个该级别单位K线重叠部分。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
def isPseudoThirdBuy (d : Decomposition P) (cut : Nat) :=
  decide (d.depth = 0) && thirdPoint d .up cut

/-- 基底段作离开与回试，反向判类三卖。
[017:40] 这里有一个递归的问题，就是这次级别不能无限下去，就像有些半吊子哲学胡诌什么，而“分”不是无限的，按照量子力学，物质之分是有极限的，同样，级别之次也不可能无限，在实际之中，对最后不能分解的级别，其缠中说禅走势中枢就不能用“至少三个连续次级别走势类型所重叠”定义，而定义为至少三个该级别单位K线重叠部分。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
def isPseudoThirdSell (d : Decomposition P) (cut : Nat) :=
  decide (d.depth = 0) && thirdPoint d .down cut

/-- 在线版：在触边段结束时即可判断；以最近中枢的阶段与实际终点为准。

[101:42] 注意，只有在这回升的中阴状态下才有第一、二类买点，中阴状态结束后，所有的中枢震荡只存在第三类买卖点以及中枢震荡的买卖点，就不存在第一、二类买卖点了。
-/
def oscillationPoint (d : Decomposition P) (side : Dir) (cut : Nat) : Bool :=
  decide (0 < cut ∧ phaseAt d cut = some .oscillation) &&
    match d.recent d.origin cut, d.steps[cut-1]?, d.prices? (cut-1) with
    | some z, some a, some (_, p) =>
      decide (a.dir = side.flip ∧ z.extendsWith a) && !ahead side p (edge side.flip z.core)
    | _, _, _ => false

/-- 围绕当前核下边界的在线买点。

[101:42] 注意，只有在这回升的中阴状态下才有第一、二类买点，中阴状态结束后，所有的中枢震荡只存在第三类买卖点以及中枢震荡的买卖点，就不存在第一、二类买卖点了。
-/
def isOscillationBuy (d : Decomposition P) (cut : Nat) := oscillationPoint d .up cut

/-- 围绕当前核上边界的在线卖点。

[101:42] 注意，只有在这回升的中阴状态下才有第一、二类买点，中阴状态结束后，所有的中枢震荡只存在第三类买卖点以及中枢震荡的买卖点，就不存在第一、二类买卖点了。
-/
def isOscillationSell (d : Decomposition P) (cut : Nat) := oscillationPoint d .down cut

/-- 后继反转段已完成的确认版；不要求前后端点相接。 -/
def isConfirmedOscillationBuy (d : Decomposition P) (cut : Nat) : Bool :=
  isOscillationBuy d cut && (d.steps[cut]?).any (fun s => s.dir == .up)

/-- 后继向下段完成后确认震荡卖点。 -/
def isConfirmedOscillationSell (d : Decomposition P) (cut : Nat) : Bool :=
  isOscillationSell d cut && (d.steps[cut]?).any (fun s => s.dir == .down)

end Chan.Defs.Signal
