module

public import Chan.Defs.Dynamics.ForceSpec
public import Chan.Defs.Signal.Points

@[expose] public section

namespace Chan.Defs.Dynamics

open Chan.Defs.Alt Chan.Defs.Order Chan.Defs.Level Chan.Defs.Signal Chan.Defs.Center

/-- 取闭区间全部原始价格样本。
[027:38] 「以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。」
-/
def DivGeometry.samples (h : List ℚ) (w : Span) := h.extract w.first (w.last + 1)

open DivGeometry

/-- 取窗口的最低价和最高价，越过当前历史时没有值。
[061:28] 「因为背驰如果没有创新高，是不存在的。」
-/
def DivGeometry.bounds? (h : List ℚ) (w : Span) : Option (ℚ × ℚ) := do
  if w.last ≥ h.length then none else
    let xs := samples h w
    return (← xs.min?, ← xs.max?)

/-- 向上比较高点，向下比较低点。
[061:28] 「因为背驰如果没有创新高，是不存在的。」
-/
def DivGeometry.extremum (side : Dir) (bounds : ℚ × ℚ) : ℚ :=
  match side with | .up => bounds.2 | .down => bounds.1

/-- 候选后段必须严格刷新前段的方向极值；相触不算，两段都必须完整可见。
[061:28] 「因为背驰如果没有创新高，是不存在的。」
[二级旁证 044:234] 「==创新高或新低才有背驰或盘整背驰的可能。未创新高的情况，其实可以按中枢震荡的方式去看，等于达不到上次震荡的力度，也可以用MACD等辅助看，但和背驰不是同一样东西，这在关于中枢震荡的力度判断那一课里里都有的。」
-/
def MakesNewExtreme (h : List ℚ) (side : Dir) (a c : Span) : Bool :=
  match bounds? h a, bounds? h c with
  | some x, some y => ahead side (extremum side y) (extremum side x)
  | _, _ => false

/-- 单个历史前缀的分解。账本只记已完成段；待定段仅记录已知起点，终点由当下时钟给出。
段表的实际价格、极值和来源索引都用同一价格前缀核对。
[061:26] 「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」
-/
structure DivFrame (rule : BlockRule.{0}) (depth : Nat) (h : List ℚ) where
  stage : Decomposition ℚ
  atRule : stage.rule = rule
  atDepth : stage.depth = depth
  observed : ∀ (i : Fin stage.steps.length), let s := stage.steps[i.val]
    s.source.last < h.length ∧ bounds? h s.source = some (s.range.lo, s.range.hi) ∧
      h[s.source.first]? = some (stage.ledger.price i).entry ∧
      h[s.source.last]? = some (stage.ledger.price i).exit
  chronological : stage.steps.Pairwise (fun a b => a.source.last ≤ b.source.first)
  opened : Option Nat
  boundary : ∀ j, opened = some j → j < h.length ∧
    (match stage.steps.getLast? with
     | none => j = 0
     | some s => s.source.last = j ∨ s.source.last + 1 = j)

/-- 固定级别规则和分解办法后，只把要求观察的前缀交给分解器；不能查询未来行情。
[043:26] 「由于背驰的级别不可能大于当下走势的级别，例如一个30分钟级别的背驰，只可能存在于一个至少是30分钟级别的走势类型中，所以就有这两种不同转折方式的明确分类。」
-/
abbrev DivAnalysis (rule : BlockRule.{0}) :=
  (depth : Nat) → (h : List ℚ) → Option (DivFrame rule depth h)

/-- 以先后有序的来源坐标构造闭跨度。
[027:38] 「以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。」
-/
def DivGeometry.span? (a b : Nat) : Option Span :=
  if h : a ≤ b then some ⟨a, b, h⟩ else none

/-- 先后两个原始跨度共用一个中枢。
[061:26] 「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」
-/
def DivGeometry.window? (a c : Span) (z : Center ℚ) : Option ForceWindow :=
  if h : a.last ≤ c.first then
    let covered := (z.b :: z.c :: z.more).foldl (fun raw seg => raw.join seg.source) z.a.source
    some ⟨a, c, some (covered, z.core), h⟩
  else none

/-- 用实际起止价判定该段沿选定方向推进。
[033:26] 「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」
-/
def DivGeometry.progresses (h : List ℚ) (w : Span) (side : Dir) : Bool :=
  match h[w.first]?, h[w.last]? with
  | some p, some q => ahead side q p
  | _, _ => false

/-- 只取本走势起点以来账本记载的中枢。
[027:14] 「趋势，一定有至少两个同级别中枢，对于背驰来说，肯定不会发生在第一个中枢之后，肯定是至少是第二个中枢之后，对于那种延伸的趋势来说，很有可能在发生第100个中枢以后才背驰，当然，这种情况，一般来说，一百年见不到几次。」
-/
def DivGeometry.sameScope (d : Decomposition ℚ) (since n : Nat) :=
  if d.marks.any (fun j => since < j && d.steps[j-1]?.any (fun s => s.source.last+1 < n))
  then [] else d.ledger.centers.filter fun z => decide (since ≤ z.start)

/-- 至少两个中枢，逐对检验整个波动区间同向严格分离。
[027:14] 「趋势，一定有至少两个同级别中枢，对于背驰来说，肯定不会发生在第一个中枢之后，肯定是至少是第二个中枢之后，对于那种延伸的趋势来说，很有可能在发生第100个中枢以后才背驰，当然，这种情况，一般来说，一百年见不到几次。」
-/
def DivGeometry.trendSide (side : Dir) (zs : List (Center ℚ)) : Bool :=
  zs.length ≥ 2 && (zs.zip zs.tail).all fun (a,b) =>
    match side with
    | .up => decide (gapUp a.zone.hull b.zone.hull)
    | .down => decide (gapDown a.zone.hull b.zone.hull)

/-- #2322 K-4/K-5：把最后两枢之间的全部连接段合为唯一的 b，与给定的 c 配对。
[033:26] 「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」
-/
def DivGeometry.trendWindowOfDecomp? (d : Decomposition ℚ) (prev z : Center ℚ)
    (c : Span) : Option ForceWindow := do
  guard (prev.stop < z.start)
  let firstB ← d.steps[prev.stop]?
  let lastB ← d.steps[z.start - 1]?
  let b ← span? firstB.source.first lastB.source.last
  window? b c z

/-- 由最后两枢确定比较段 b；独立离开段 c 只读到当下。
[033:26] 「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」
-/
def DivGeometry.trendWindow? {r k h} (f : DivFrame r k h) (since : Nat) (side : Dir) :
    Option ForceWindow := do
  let zs := sameScope f.stage since h.length
  guard (trendSide side zs)
  let z :: prev :: _ := zs.reverse | none
  let openAt ← f.opened
  -- 独立 c 可以已有完成的内部段；只取第一段的已知起点，不取未来终点。
  let c ← span? ((f.stage.steps[z.stop]?.map (·.source.first)).getD openAt) (h.length - 1)
  let w ← trendWindowOfDecomp? f.stage prev z c
  let now ← h.getLast?
  guard (progresses h w.earlier side && progresses h c side && ahead side now (edge side z.core))
  return w

/-- 到达中枢闭区间，触及边界也计入。
[098:16] 「一个背驰后，无论是盘整背驰还是真正的背驰，理论只能保证其回拉原来的中枢，这是正确的思维方式，那么，回拉之后如何，这涉及预测。正确的思维是，把回拉后出现的情况进行完全的分类，根据每种分类对应的后果，决定你自己的对策。」
-/
def DivGeometry.touches (z : Center ℚ) (x : ℚ) := decide (z.core.lo ≤ x ∧ x ≤ z.core.hi)

/-- 检验从当前中枢向指定方向突破的已完成段。
[027:16] 「如果在第一个中枢就出现背驰，那不会是真正意义上的背驰，只能算是盘整背驰，其真正的技术含义，其实就是一个企图脱离中枢的运动，由于力度有限，被阻止而出现回到中枢里。」
-/
def DivGeometry.leaveAt (d : Decomposition ℚ) (z : Center ℚ) (side : Dir) (i : Nat) : Bool :=
  match d.steps[i]?, d.prices? i with
  | some s, some (_,out) =>
    s.dir == side && ahead side out (edge side z.core) &&
      (decide (overlaps z.core s.range) ||
       (i > 0 && d.steps[i-1]?.any fun prev => decide (overlaps z.core prev.range)))
  | _, _ => false

/-- 分别构造入枢窗与再离窗。再离窗只取最近一次同侧离开，且中间有反向触核。
[027:20] 「注意，这里是把第一、三段看成两个走势类型之间的比较，这和趋势背驰里的情况有点不同，这两个走势类型是否一定是趋势，都问题不大，两个盘整在盘整背驰中也是可以比较力度的。」
[061:26] 「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」
-/
def DivGeometry.consolWindowPair {r k h} (f : DivFrame r k h) (since : Nat) (side : Dir) :
    Option ForceWindow × Option ForceWindow := Id.run do
  let [z] := sameScope f.stage since h.length | return (none, none)
  let some j := f.opened | return (none, none)
  let some c := span? j (h.length-1) | return (none, none)
  let some (p,q) := bounds? h c | return (none, none)
  let some out := h.getLast? | return (none, none)
  let xs := f.stage.steps
  unless progresses h c side && ahead side out (edge side z.core) &&
      (decide (p ≤ z.core.hi ∧ z.core.lo ≤ q) ||
       xs.getLast?.any fun prev => decide (overlaps z.core prev.range)) do return (none, none)
  let entry := do
    guard (since < z.start)
    let a ← xs[z.start-1]?
    let lastZ ← z.cover.getLast?
    guard (a.dir == side && progresses h a.source side && lastZ.source.last ≤ c.first)
    window? a.source c z
  let departure := do
    let i ← ((List.range xs.length).filter fun i =>
      z.start ≤ i && leaveAt f.stage z side i).getLast?
    guard ((xs.drop (i+1)).any (fun s => s.dir == side.flip && decide (overlaps s.range z.core)))
    let a ← xs[i]?
    window? a.source c z
  return (entry, departure)

/-- #2322 U-2：列出独立形成的入枢窗与再离窗。真值相对调用方按 `spec.window` 指名的窗，
两窗不互为退路（#799）。
[027:20] 「注意，这里是把第一、三段看成两个走势类型之间的比较，这和趋势背驰里的情况有点不同，这两个走势类型是否一定是趋势，都问题不大，两个盘整在盘整背驰中也是可以比较力度的。」
-/
def DivGeometry.consolWindows {r k h} (f : DivFrame r k h) (since : Nat) (side : Dir) :
    List ForceWindow :=
  let (entry, departure) := consolWindowPair f since side
  entry.toList ++ departure.toList

/-- 核对比较跨度，指定了锚定区间时也核对中枢。
[061:26] 「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」
-/
def DivGeometry.matchesWindow (w v : ForceWindow) : Bool :=
  w.earlier == v.earlier && w.later == v.later &&
    (w.anchor.isNone || decide (w.anchor = v.anchor))

/-- 对匹配的结构窗口分别检验创新极值和力度减弱。
[061:28] 「因为背驰如果没有创新高，是不存在的。」
-/
def DivGeometry.passes (mode : ForceCompareMode) (spec : ForceSpec) (h : List ℚ) (side : Dir)
    (w : ForceWindow) : Bool :=
  matchesWindow spec.window w && MakesNewExtreme h side w.earlier w.later &&
    forceWeaker mode spec h side

/-- #2322 K-2/K-4/K-5/K-6：复用 M15 传入的分解及末枢，不再分解或复验一类点结构。
取离开段收笔方向 `d.closingDir? j`：深度 0 恒等于 `Seg.dir`，深度 ≥ 1 时偶数块的
收笔方向与起笔方向相反。与 M15 `firstPoint` 的收笔方向门一致：`isFirstBuy` 判底背驰。
`prev` 依赖 `d.ledger.centers` 的时间序；b 由两枢之间的全部连接段合成，`i` 不参与求值。
c 从末枢结束处的第一段起，到第 `j` 段终点（含）；价格只读截至该终点的前缀。
依据契约 S1–S5，不重复检查在线 `progresses` 守卫。
[033:26] 「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」
-/
def divJudge (recipe : ForceRecipe) (mode : ForceCompareMode) (h : List ℚ) : StrengthJudge ℚ :=
  fun d z _i j => Id.run do
    let some cSeg := d.steps[j]? | return false
    let some side := d.closingDir? j | return false
    if j < z.stop then return false
    let some prev := (d.ledger.centers.takeWhile (fun p => p.start < z.start)).getLast? | return false
    let some cStart := d.steps[z.stop]?.map (·.source.first) | return false
    let some c := span? cStart cSeg.source.last | return false
    let some w := trendWindowOfDecomp? d prev z c | return false
    let past := h.take (cSeg.source.last + 1)
    return MakesNewExtreme past side w.earlier w.later &&
      forceWeaker mode (recipe.atWindow w) past side

/-- K-2 镜像义务：势为反号等变时，价格取负且分解与中枢镜像的判定一致。
段跨度和中枢段号保持不变，起笔与收笔方向均翻转，传入末枢的核取负并交换上下沿。
[033:26] 「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」
-/
def DivJudgeMirrorEquiv (recipe : ForceRecipe) (mode : ForceCompareMode) : Prop :=
  MirrorAntiSym recipe.potential →
    ∀ (h : List ℚ) (d d' : Decomposition ℚ) (z z' : Center ℚ) (i j : Nat),
      d'.steps.map (fun s => (s.source, s.dir)) =
        d.steps.map (fun s => (s.source, s.dir.flip)) →
      (∀ k, d'.closingDir? k = (d.closingDir? k).map Dir.flip) →
      d'.ledger.centers.map (fun p => (p.start, p.stop)) =
        d.ledger.centers.map (fun p => (p.start, p.stop)) →
      z'.start = z.start → z'.stop = z.stop →
      z'.core.lo = -z.core.hi → z'.core.hi = -z.core.lo →
      divJudge recipe mode (h.map Neg.neg) d' z' i j = divJudge recipe mode h d z i j

/-- K-2 因果义务：历史在离开段终点及之前逐项相同，则同一切点的结果相同。
[033:26] 「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」
-/
def DivJudgeCausal (recipe : ForceRecipe) (mode : ForceCompareMode) : Prop :=
  ∀ (h₁ h₂ : List ℚ) (d : Decomposition ℚ) (z : Center ℚ) (i j : Nat) (c : Seg ℚ),
    d.steps[j]? = some c →
    h₁.take (c.source.last + 1) = h₂.take (c.source.last + 1) →
    divJudge recipe mode h₁ d z i j = divJudge recipe mode h₂ d z i j

/-- K-4 合窗义务：改变 M15 传入的连接段下标不改变判定。
[033:26] 「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」
-/
def DivJudgeIndepOfIndex (recipe : ForceRecipe) (mode : ForceCompareMode) : Prop :=
  ∀ (h : List ℚ) (d : Decomposition ℚ) (z : Center ℚ) (i₁ i₂ j : Nat),
    divJudge recipe mode h d z i₁ j = divJudge recipe mode h d z i₂ j

variable (rule : BlockRule.{0}) (analyse : DivAnalysis rule)

/-- 趋势至少有两个连续同向、严格分离的同级中枢。比较倒数两个中枢之间的 b 与最后中枢以后的 c。
`since` 是本走势在本层段表的起点，价格窗口另用底层坐标。
[027:14] 「趋势，一定有至少两个同级别中枢，对于背驰来说，肯定不会发生在第一个中枢之后，肯定是至少是第二个中枢之后，对于那种延伸的趋势来说，很有可能在发生第100个中枢以后才背驰，当然，这种情况，一般来说，一百年见不到几次。」
[033:26] 「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」
-/
def TrendDiv (depth since : Nat) (h : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) : Bool :=
  (analyse depth h).any fun f => (trendWindow? f since side).any (passes mode spec h side)

/-- #2322 U-2：只在单枢内按 `spec.window` 指名检验，真值相对所选窗口。
等价于 `ConsolDivEntry` 与 `ConsolDivRepeat` 之或；指名的窗失败时，不换另一窗重判（#799）。
[027:16] 「如果在第一个中枢就出现背驰，那不会是真正意义上的背驰，只能算是盘整背驰，其真正的技术含义，其实就是一个企图脱离中枢的运动，由于力度有限，被阻止而出现回到中枢里。」
[027:20] 「注意，这里是把第一、三段看成两个走势类型之间的比较，这和趋势背驰里的情况有点不同，这两个走势类型是否一定是趋势，都问题不大，两个盘整在盘整背驰中也是可以比较力度的。」
-/
def ConsolDiv (depth since : Nat) (h : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) : Bool :=
  (analyse depth h).any fun f => (consolWindows f since side).any (passes mode spec h side)

/-- 单枢盘背的入枢窗：用 `spec.window` 指名紧邻中枢的同向进入段与成枢后离开段。
[027:20] 「注意，这里是把第一、三段看成两个走势类型之间的比较，这和趋势背驰里的情况有点不同，这两个走势类型是否一定是趋势，都问题不大，两个盘整在盘整背驰中也是可以比较力度的。」
-/
def ConsolDivEntry (depth since : Nat) (h : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) : Bool :=
  (analyse depth h).any fun f => (consolWindowPair f since side).1.any (passes mode spec h side)

/-- 单枢盘背的再离窗：用 `spec.window` 指名经反向触核分隔的相邻同侧离开段。
[027:16] 「如果在第一个中枢就出现背驰，那不会是真正意义上的背驰，只能算是盘整背驰，其真正的技术含义，其实就是一个企图脱离中枢的运动，由于力度有限，被阻止而出现回到中枢里。」
-/
def ConsolDivRepeat (depth since : Nat) (h : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) : Bool :=
  (analyse depth h).any fun f => (consolWindowPair f since side).2.any (passes mode spec h side)

/-- 只用当前前缀检验趋势或盘整的候选背驰，不预扣下一根价格或下一段回拉。
[043:40] 「这种小级别背驰最终转化成大级别转折的情况，最值得注意的，是出现在趋势走势的冲顶或赶底之中，这种情况一般都会引发大级别的转折，这种例子前面都说过，例如20070104的工行，20061207的北辰实业、20070122的水井坊等。」
[079:52] 「有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。」
-/
def DivOnline (depth since : Nat) (h : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) : Bool :=
  TrendDiv rule analyse depth since h side spec mode || ConsolDiv rule analyse depth since h side spec mode

/-- 在同一前缀上保留在线判定，再检查整个确认后缀未再刷新离开段极值。
中枢确认条件单独传入，使两种 U-3 口径只在触核事件上分离。
[079:52] 「有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。」
[098:16] 「一个背驰后，无论是盘整背驰还是真正的背驰，理论只能保证其回拉原来的中枢，这是正确的思维方式，那么，回拉之后如何，这涉及预测。正确的思维是，把回拉后出现的情况进行完全的分类，根据每种分类对应的后果，决定你自己的对策。」
-/
def DivGeometry.confirmedBy (returned : Center ℚ → ℚ → Bool) (depth since : Nat)
    (h tail : List ℚ) (side : Dir) (spec : ForceSpec) (mode : ForceCompareMode) : Bool :=
  DivOnline rule analyse depth since h side spec mode &&
    match analyse depth h, bounds? h spec.window.later with
    | some f, some limits =>
      let cap := extremum side limits
      (sameScope f.stage since h.length).getLast?.any (fun z => tail.any (returned z)) &&
        tail.all (fun p => !ahead side p cap)
    | _, _ => false

/-- 以离开侧核边缘的闭半平面确认。一步跳到另一侧带外也满足。
[098:16] 「一个背驰后，无论是盘整背驰还是真正的背驰，理论只能保证其回拉原来的中枢，这是正确的思维方式，那么，回拉之后如何，这涉及预测。正确的思维是，把回拉后出现的情况进行完全的分类，根据每种分类对应的后果，决定你自己的对策。」
-/
def DivCrossedCore (depth since : Nat) (h tail : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) : Bool :=
  DivGeometry.confirmedBy rule analyse (fun z p => !ahead side p (edge side z.core))
    depth since h tail side spec mode

/-- 以真实离散样本落入闭核确认，不把跳穿视作落入。
[098:16] 「一个背驰后，无论是盘整背驰还是真正的背驰，理论只能保证其回拉原来的中枢，这是正确的思维方式，那么，回拉之后如何，这涉及预测。正确的思维是，把回拉后出现的情况进行完全的分类，根据每种分类对应的后果，决定你自己的对策。」
-/
def DivTouchedCore (depth since : Nat) (h tail : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) : Bool :=
  DivGeometry.confirmedBy rule analyse touches depth since h tail side spec mode

/-- #2322 U-3：确认取 `DivCrossedCore` 的越沿口径。在线背驰成立、后缀未刷新离开段极值，
且有样本不再严格越过离开侧核沿，即予确认。更严的 `DivTouchedCore` 要求有样本落入闭核：
落核蕴含越沿，跳穿整个核说明反向不成立。
[098:16] 「一个背驰后，无论是盘整背驰还是真正的背驰，理论只能保证其回拉原来的中枢，这是正确的思维方式，那么，回拉之后如何，这涉及预测。正确的思维是，把回拉后出现的情况进行完全的分类，根据每种分类对应的后果，决定你自己的对策。」
-/
def DivConfirmed (depth since : Nat) (h tail : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) : Bool :=
  DivCrossedCore rule analyse depth since h tail side spec mode

/-- 三种互斥的终结机制。仍在发展的走势没有终结标签。
[033:24] 「在最极端的情况下，在a+A+b+B+c的走势系列类型里，a和c并不是必然存在的，而b完全可以是一个跳空缺口，这样，整个走势就可以简化为两个孤零零的中枢。」
[027:18] 「但如果是低位，那意义就不同了，因为多数的第二、三类买点，其实都是由盘整背驰构成的，而第一类买点，多数由趋势的背驰构成。」
[044:24] 「小级别顶背驰引发大级别向下的必要条件是该级别走势的最后一个次级别中枢出现第三类卖点；」
-/
inductive TrendEndCase where
  | divergentExit | internalReversal | reverseThird
  deriving DecidableEq

/-- 取中枢末覆盖段的底层末坐标。
[027:38] 「以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。」
-/
def DivGeometry.lastRaw? (z : Center ℚ) := z.cover.getLast?.map (·.source.last)

/-- 沿实际延拓寻找终结证据；尚未终结时不发出标签。
[079:52] 「有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。」
-/
def DivGeometry.confirmedCase? (depth since : Nat) (h tail : List ℚ) (side : Dir)
    (spec : ForceSpec) (mode : ForceCompareMode) : Option TrendEndCase := do
  let some f := analyse depth h | none
  let some g := analyse depth (h ++ tail) | none
  let zs := sameScope f.stage since h.length
  guard (trendSide side zs && !tail.isEmpty)
  let z ← zs.getLast?
  -- 延拓中允许原枢延伸，但须仍是同一组三段成核。
  let z' ← g.stage.ledger.centers.find? fun v =>
    decide (v.start = z.start ∧ v.a = z.a ∧ v.b = z.b ∧ v.c = z.c)
  let kind := match side with | .up => TrendKind.uptrend | .down => TrendKind.downtrend
  let finished ← g.stage.ledger.completed.find? fun b =>
    decide (b.first = since ∧ classifyTrend b = some kind ∧ b.centers.getLast? = some z')
  let endZ ← lastRaw? z'
  let w := spec.window.later
  if endZ ≤ w.first && g.stage.steps[finished.stop-1]?.any (fun s => s.source.last == w.last) &&
      TrendDiv rule analyse depth since h side spec mode &&
      DivConfirmed rule analyse depth since h tail side spec mode then return .divergentExit
  let opposite := side.flip
  if w.last ≤ endZ && ConsolDiv rule analyse depth z.start h side spec mode &&
      [z'.stop - 1, z'.stop].any (fun i =>
        g.stage.steps[i]?.any fun s => h.length ≤ s.source.last &&
          leaveAt g.stage z' opposite i) then return .internalReversal
  let i ← z'.departureIndex? opposite g.stage.steps
  let retest ← g.stage.steps[i+1]?
  guard (h.length ≤ retest.source.last)
  return .reverseThird

/-- 对已见的终结事件只给一个标签：独立 c 趋势背驰、末枢内部盘背后反向离开、直接反向三类点。
按延拓中已确认的末枢边界区分内部与独立 c；最后一类也必须实际出现三类事件。
[033:24] 「在最极端的情况下，在a+A+b+B+c的走势系列类型里，a和c并不是必然存在的，而b完全可以是一个跳空缺口，这样，整个走势就可以简化为两个孤零零的中枢。」
[027:16] 「如果在第一个中枢就出现背驰，那不会是真正意义上的背驰，只能算是盘整背驰，其真正的技术含义，其实就是一个企图脱离中枢的运动，由于力度有限，被阻止而出现回到中枢里。」
[044:26] 「小级别底背驰引发大级别向上的必要条件提是该级别走势的最后一个次级别中枢出现第三类买点。」
-/
def trendEndClassify (depth since : Nat) (h tail : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) (label : TrendEndCase) : Bool :=
  decide (confirmedCase? rule analyse depth since h tail side spec mode = some label)

/-- 把在线趋势背驰或盘整背驰定位到该层后一个比较段的原始跨度。
[027:22] 「这里，先补充一个定义：就是在某级别的某类型走势，如果构成背驰或盘整背驰，就把这段走势类型称为某级别的背驰段。」
-/
def DivSegment (depth since : Nat) (h : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) (source : Span) : Bool :=
  source == spec.window.later && DivOnline rule analyse depth since h side spec mode

/-- 检验区间套一层的跨度是否始末均有该层的来源边界。
[027:38] 「以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。」
-/
def DivGeometry.observedSpan {r k h} (f : DivFrame r k h) (s : Span) : Bool :=
  let xs := f.stage.steps
  xs.any (fun a => a.source == s) ||
    f.stage.ledger.completed.any (fun b =>
      xs[b.first]?.any (fun a => a.source.first == s.first) &&
      xs[b.stop-1]?.any (fun a => a.source.last == s.last)) ||
    (f.opened.isSome && s.last+1 == h.length &&
      (f.opened == some s.first || f.stage.ledger.centers.any (fun z =>
        xs[z.stop]?.any (fun a => a.source.first == s.first))))

/-- 原始闭跨度包含；允许内外端点相等。
[027:38] 「以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。」
-/
abbrev SpanWithin (inner outer : Span) : Prop :=
  outer.first ≤ inner.first ∧ inner.last ≤ outer.last

/-- 检验实际分解中的各层来源跨度，顶层还须由在线背驰定位到同一跨度。
[027:22] 「这里，先补充一个定义：就是在某级别的某类型走势，如果构成背驰或盘整背驰，就把这段走势类型称为某级别的背驰段。」
[027:38] 「以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。」
-/
def DivGeometry.checkedChain (since : Nat) (h : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) (chain : List (Nat × Span)) : Bool :=
  chain.head?.any (fun (k,s) => DivSegment rule analyse k since h side spec mode s) &&
    chain.tail.all (fun (k,s) => s.last < h.length &&
      ((analyse k h).any (fun f => observedSpan f s) ||
        (analyse k (h.take (s.last+1))).any (fun f => observedSpan f s)))

/-- #2322 U-4 主口径：层深严格下降，可跳层；原始闭跨度按非严格 `SpanWithin` 嵌套，允许相等。
顶层须为背驰段，内层只须在实际分解中可观测。
[027:38] 「以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。」
[056:66] 「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」
-/
def NestedDivChain (since : Nat) (h : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) (chain : List (Nat × Span)) : Bool :=
  DivGeometry.checkedChain rule analyse since h side spec mode chain &&
    (chain.zip chain.tail).all fun ((k,u),(j,v)) => decide (j < k ∧ SpanWithin v u)

/-- #2322 U-4 字面理想档：相邻逐层且跨度真包含；顶层背驰与下层来源验证与主口径一致。
[027:38] 「以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。」
-/
def StrictNestedDivChain (since : Nat) (h : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) (chain : List (Nat × Span)) : Bool :=
  DivGeometry.checkedChain rule analyse since h side spec mode chain &&
    (chain.zip chain.tail).all fun ((k,u),(j,v)) => decide (k = j+1 ∧ SpanWithin v u ∧ u ≠ v)

/-- 把离开方向映射为相应的趋势类型。
[029:14] 「对于上涨的转折，有两种情况：下跌与盘整；对于下跌的转折，也有两种情况：上涨与盘整。转折是有级别的，关于转折与背驰的关系，有如下定理：」
-/
def DivGeometry.trendKind : Dir → TrendKind
  | .up => .uptrend
  | .down => .downtrend

-- 转折要有两段相邻完成走势：原趋势以及异类后继；不能单凭次级三类点宣告大级别转折。
/-- 同级相邻的已完成块先为原趋势、后为异类走势，在给定原始时点衔接。
[029:14] 「对于上涨的转折，有两种情况：下跌与盘整；对于下跌的转折，也有两种情况：上涨与盘整。转折是有级别的，关于转折与背驰的关系，有如下定理：」
-/
def DivGeometry.oldTrend? (d : Decomposition ℚ) (side : Dir) (turn : Nat) : Option Span := do
  let done := d.ledger.completed
  let (a,_) ← (done.zip done.tail).find? fun (a,b) =>
    decide (a.stop = b.first ∧ classifyTrend a = some (trendKind side)) &&
      (classifyTrend b).any (fun kind => kind != trendKind side) &&
      d.steps[a.stop-1]?.any (fun s => s.source.last == turn)
  let first ← d.steps[a.first]?
  span? first.source.first turn

/-- 在大趋势实际覆盖的最后次级中枢上检验反向三类点或反向离开。
[044:24] 「小级别顶背驰引发大级别向下的必要条件是该级别走势的最后一个次级别中枢出现第三类卖点；」
-/
def DivGeometry.subBreak (d : Decomposition ℚ) (span : Span) (earliest : Nat)
    (side : Dir) (thirdOnly : Bool) : Bool := Id.run do
  let zs := d.ledger.centers.filter fun z =>
    decide (span.first ≤ z.a.source.first ∧ z.c.source.last ≤ span.last)
  let some z := zs.getLast? | return false
  if let some i := z.departureIndex? side d.steps then
    if d.steps[i+1]?.any (fun s => earliest ≤ s.source.last) then return true
  if thirdOnly then return false
  return [z.stop-1, z.stop].any fun i =>
    d.steps[i]?.any fun s => earliest ≤ s.source.last && leaveAt d z side i

/-- 小级别出现背驰，大级别确已转折，并在其最后次级中枢找到反向三类点。
小级别可以低于次级；次级三类点是独立必要条件，不能单凭它推出转折。
[043:24] 「如果市场的转折与背驰都有这在级别上一一对应关系，那这市场也太没意思、太刻板了，而由于这种小级别背驰逐步积累后导致大级别转折的可能，才使得市场充满当下的生机。」
[044:24] 「小级别顶背驰引发大级别向下的必要条件是该级别走势的最后一个次级别中枢出现第三类卖点；」
[044:26] 「小级别底背驰引发大级别向上的必要条件提是该级别走势的最后一个次级别中枢出现第三类买点。」
[044:30] 「注意，关于这种情况，只有必要条件，而没有充分条件，也就是说不能有一个充分的判断使得一旦出现某种情况，就必然导致大级别的转折。」
-/
def SmallDivTriggersBigTurn (small big since turn : Nat) (h tail : List ℚ)
    (side : Dir) (spec : ForceSpec) (mode : ForceCompareMode) : Bool :=
  small < big && h.length-1 ≤ turn &&
    (List.range tail.length).any (fun n =>
      DivConfirmed rule analyse small since h (tail.take (n+1)) side spec mode) &&
    match analyse big (h ++ tail), analyse (big-1) (h ++ tail) with
    | some g, some sub =>
      (oldTrend? g.stage side turn).any (fun span => span.first ≤ spec.window.later.first &&
        subBreak sub.stage span (h.length-1) side.flip true)
    | _, _ => false

/-- 固定读法、端点、势和比较开关，遍历本次分解实际给出的本级比较窗。即使没有本级背驰，
次级三类点或反向离开仍可伴随一个已由完成块认证的大级别转折。
[056:66] 「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」
[102:38] 「而级别的存在，一个必然的结论就是，任何高级别的改变都必须先从低级别开始。例如，绝对不可能出现5分钟从下跌转折为上涨，而1分钟还在下跌段中。」
-/
def TurnWithoutSameLevelDiv (big since : Nat) (h tail : List ℚ)
    (side : Dir) (spec : ForceSpec) (mode : ForceCompareMode) : Bool := Id.run do
  let some f := analyse big h | return false
  let some g := analyse big (h ++ tail) | return false
  let some sub := analyse (big-1) (h ++ tail) | return false
  let turn := h.length-1
  let some span := oldTrend? g.stage side turn | return false
  let windows := (trendWindow? f since side).toList ++ consolWindows f since side
  let divergent := windows.any fun w =>
    let v := if spec.window.anchor.isNone then {w with anchor := none} else w
    passes mode {spec with window := v} h side w
  let aligned := f.stage.steps[since]?.any (fun s => s.source.first == span.first)
  return big > 0 && !h.isEmpty && aligned && !divergent && subBreak sub.stage span turn side.flip false

end Chan.Defs.Dynamics
