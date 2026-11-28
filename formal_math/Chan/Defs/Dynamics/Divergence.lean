module

public import Chan.Defs.Dynamics.ForceSpec
public import Chan.Defs.Signal.Points
public import Chan.Defs.Path.History

/-!
# M17 背驰与区间套

在线谓词 `DivOnline` 只依赖当前有限历史；事后确认谓词 `DivConfirmed` 依赖后续延拓，两者分立（B-16）。
趋势背驰与盘整背驰分立并共用力度接口（B-15）；趋势终结三分以首个判别条件划分（B-18）；
区间套为纯结构嵌套，不强加每级同级背驰（B-20）；小转大两义分立（B-21）。
本文件不陈述“背驰必转折”。
-/

@[expose] public section

namespace Chan.Defs.Dynamics

open Chan.Defs.Order Chan.Defs.Alt Chan.Defs.Center Chan.Defs.Level Chan.Defs.Signal Chan.Defs.Path

/-- 趋势终结三分：离开最后中枢的 `c` 段且趋势背驰；无独立 `c` 段而在最后中枢内部背驰后反向离开；
最后中枢直接出现反向第三类买卖点。

[029:16]「缠中说禅背驰-转折定理：某级别趋势的背驰将导致该趋势最后一个中枢的级别扩展、该级别更大级别的盘整或该级别以上级别的反趋势。」
[029:52]「以上三种情况，就完全分类了某级别背驰后的级别与力度，也就是某级别的第一类买点后将发生怎么样的情况，而第一类卖点的情况是一样的，只是方向相反。」 -/
inductive TrendEndCase where
  /-- 情形一：`c` 段离开并趋势背驰。 -/
  | divergenceExit
  /-- 情形二：中枢内部背驰后反向离开。 -/
  | consolidationReversal
  /-- 情形三：直接出现反向第三类买卖点。 -/
  | reverseThird

/-- 区间套中的一层：层深与原始坐标跨度。

[027:46]「换言之，某大级别的转折点，先找到其背驰段，然后在次级别图里，找出相应背驰段在次级别里的背驰段，将该过程反复进行下去，直到最低级别，相应的转折点就在该级别背驰段确定的范围内。」 -/
structure ChainLevel where
  /-- 层深。 -/
  depth : ℕ
  /-- 原始坐标跨度。 -/
  span : Span

/-- 跨度包含：`inner` 落在 `outer` 之内。

[027:38]「以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。」 -/
def SpanWithin (inner outer : Span) : Prop :=
  outer.first ≤ inner.first ∧ inner.last ≤ outer.last

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 创新高/新低（严格不等号）：顶背驰要求后段高点严格高于前段高点，底背驰对称。

[061:28]「对于65开始背驰段的内部走势，当下走到69时，并不构成任何背驰，为什么？」
[061:28]「因为背驰如果没有创新高，是不存在的。」
[二级旁证 044:234]「==创新高或新低才有背驰或盘整背驰的可能。未创新高的情况，其实可以按中枢震荡的方式去看，等于达不到上次震荡的力度，也可以用MACD等辅助看，但和背驰不是同一样东西，这在关于中枢震荡的力度判断那一课里里都有的。」 -/
def MakesNewExtreme (side : Dir) (prev cur : Seg R) : Prop :=
  match side with
  | .up => prev.range.hi < cur.range.hi
  | .down => cur.range.lo < prev.range.lo

/-- 价位 `p` 在方向 `side` 上严格越过 `level`。

[061:28]「因为背驰如果没有创新高，是不存在的。」 -/
def BeyondLevel (side : Dir) (level p : R) : Prop :=
  match side with
  | .up => level < p
  | .down => p < level

/-- 有限历史读成时间序列（越界补零；因果势函数只在历史内取样）。

[079:52]「有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。」 -/
def histSeq (h : History R) : ℕ → R := fun t => h.getD t 0

/-- 进行中的离开段：起点已确认，终点为当下（历史末位）。

[043:30]「例如，一个30分钟的走势类型，在30分钟级别进入背驰段，当然，这个背驰段并不一定就演化成背驰，因为，小级别的延伸足以使得大级别最终摆脱背驰，这与当下的走势判断相关。」 -/
def onlineLeg (cStart : ℕ) (h : History R) : Span :=
  ⟨cStart, max cStart (h.length - 1), Nat.le_max_left _ _⟩

/-- 跨度上的顺向极值：向上取最高，向下取最低。

[061:28]「因为背驰如果没有创新高，是不存在的。」 -/
def windowExtreme (side : Dir) (x : ℕ → R) (sp : Span) : R :=
  let idx := List.range (sp.last + 1 - sp.first)
  match side with
  | .up => idx.foldl (fun m i => max m (x (sp.first + i))) (x sp.first)
  | .down => idx.foldl (fun m i => min m (x (sp.first + i))) (x sp.first)

/-- 两中枢在方向 `side` 上分离（波动区间不重叠）。

[027:14]「趋势，一定有至少两个同级别中枢，对于背驰来说，肯定不会发生在第一个中枢之后，肯定是至少是第二个中枢之后，对于那种延伸的趋势来说，很有可能在发生第100个中枢以后才背驰，当然，这种情况，一般来说，一百年见不到几次。」 -/
def SepDir (side : Dir) (a b : Center R) : Prop :=
  match side with
  | .up => gapUp a.zone.hull b.zone.hull
  | .down => gapDown a.zone.hull b.zone.hull

/-- 在线背驰：只依赖当前有限历史 `h`。比较段 `b` 为分解中位于中枢 `z` 之前的同向段，
进行中的离开段起于 `cStart`、止于当下；创新极值与力度减弱并列。

[061:26]「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
def DivOnline (rc : ForceRecipe R) (mode : ForceCompareMode) (side : Dir)
    (d : Decomposition R) (z : Center R) (i cStart : ℕ) (h : History R) : Prop :=
  z ∈ d.ledger.centers ∧ i < z.start ∧ (centerSpan z).last ≤ cStart ∧ cStart < h.length ∧
    ∃ b, d.steps[i]? = some b ∧ b.dir = side ∧
      BeyondLevel side (edge side b.range) (windowExtreme side (histSeq h) (onlineLeg cStart h)) ∧
      forceWeaker (rc.withWindow ⟨b.source, onlineLeg cStart h, some (centerSpan z)⟩) mode side
        (histSeq h)

/-- 事后确认背驰：在线背驰成立，后续延拓 `tail` 不再刷新离开段极值，且其中出现回到中枢核边界以内的价位。

[079:52]「有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。」 -/
def DivConfirmed (rc : ForceRecipe R) (mode : ForceCompareMode) (side : Dir)
    (d : Decomposition R) (z : Center R) (i cStart : ℕ) (h tail : History R) : Prop :=
  DivOnline rc mode side d z i cStart h ∧
    (∀ p ∈ tail, ¬BeyondLevel side (windowExtreme side (histSeq h) (onlineLeg cStart h)) p) ∧
    ∃ p ∈ tail, ¬BeyondLevel side (edge side z.core) p

/-- 趋势背驰：`z` 为最后中枢，之前有同向分离的同级中枢；比较 `z` 两侧连接段 `b`（下标 `i`）与 `c`（下标 `j`）。

[027:14]「趋势，一定有至少两个同级别中枢，对于背驰来说，肯定不会发生在第一个中枢之后，肯定是至少是第二个中枢之后，对于那种延伸的趋势来说，很有可能在发生第100个中枢以后才背驰，当然，这种情况，一般来说，一百年见不到几次。」
[015:36]「必须注意：没有趋势，没有背驰。在盘整中是无所谓“背驰”的，这点是必须特别明确的。」 -/
def TrendDiv (rc : ForceRecipe R) (mode : ForceCompareMode) (side : Dir) (d : Decomposition R)
    (x : ℕ → R) (z : Center R) (i j : ℕ) : Prop :=
  z ∈ d.ledger.centers ∧ i < z.start ∧ z.stop ≤ j ∧
    (∀ w ∈ d.ledger.centers, w.start ≤ j → w.start ≤ z.start) ∧
    (∃ prev ∈ d.ledger.centers, prev.stop ≤ i ∧ SepDir side prev z) ∧
    ∃ b c, d.steps[i]? = some b ∧ d.steps[j]? = some c ∧ b.dir = side ∧ c.dir = side ∧
      MakesNewExtreme side b c ∧
      forceWeaker (rc.withWindow (ForceWindow.ofSegs b c (some z))) mode side x

/-- 盘整背驰：单个同级中枢 `z` 之前没有同向分离中枢；比较 `z` 同侧相邻的两次进入/离开段。

[027:16]「如果在第一个中枢就出现背驰，那不会是真正意义上的背驰，只能算是盘整背驰，其真正的技术含义，其实就是一个企图脱离中枢的运动，由于力度有限，被阻止而出现回到中枢里。」
[027:20]「注意，这里是把第一、三段看成两个走势类型之间的比较，这和趋势背驰里的情况有点不同，这两个走势类型是否一定是趋势，都问题不大，两个盘整在盘整背驰中也是可以比较力度的。」 -/
def ConsolDiv (rc : ForceRecipe R) (mode : ForceCompareMode) (side : Dir) (d : Decomposition R)
    (x : ℕ → R) (z : Center R) (i j : ℕ) : Prop :=
  z ∈ d.ledger.centers ∧ i < z.start ∧ z.stop ≤ j ∧
    (∀ w ∈ d.ledger.centers, w.start ≤ j → w.start ≤ z.start) ∧
    (¬∃ prev ∈ d.ledger.centers, prev.stop ≤ i ∧ SepDir side prev z) ∧
    ∃ a c, d.steps[i]? = some a ∧ d.steps[j]? = some c ∧ a.dir = side ∧ c.dir = side ∧
      MakesNewExtreme side a c ∧
      forceWeaker (rc.withWindow (ForceWindow.ofSegs a c (some z))) mode side x

/-- 中枢覆盖范围之后存在顺向越过核边界的独立离开段。

[029:16]「缠中说禅背驰-转折定理：某级别趋势的背驰将导致该趋势最后一个中枢的级别扩展、该级别更大级别的盘整或该级别以上级别的反趋势。」 -/
def ForwardExit (side : Dir) (d : Decomposition R) (z : Center R) : Prop :=
  ∃ j, z.stop ≤ j ∧ ∃ c, d.steps[j]? = some c ∧ c.dir = side ∧
    BeyondLevel side (edge side z.core) (edge side c.range)

/-- 中枢出现反向第三类事件。

[029:16]「缠中说禅背驰-转折定理：某级别趋势的背驰将导致该趋势最后一个中枢的级别扩展、该级别更大级别的盘整或该级别以上级别的反趋势。」 -/
def ReverseExit (side : Dir) (d : Decomposition R) (z : Center R) : Prop :=
  (z.departureIndex? side.flip d.steps).isSome = true

/-- 中枢覆盖段内部两次同向段之间的背驰比较。

[027:16]「如果在第一个中枢就出现背驰，那不会是真正意义上的背驰，只能算是盘整背驰，其真正的技术含义，其实就是一个企图脱离中枢的运动，由于力度有限，被阻止而出现回到中枢里。」 -/
def InnerDiv (rc : ForceRecipe R) (mode : ForceCompareMode) (side : Dir) (d : Decomposition R)
    (x : ℕ → R) (z : Center R) : Prop :=
  ∃ i j, z.start ≤ i ∧ i < j ∧ j < z.stop ∧
    ∃ b c, d.steps[i]? = some b ∧ d.steps[j]? = some c ∧ b.dir = side ∧ c.dir = side ∧
      MakesNewExtreme side b c ∧
      forceWeaker (rc.withWindow (ForceWindow.ofSegs b c (some z))) mode side x

/-- 趋势终结三分谓词：以“有无顺向独立离开段”与“有无内部背驰”两道判别划分，三情形按构造互斥。

[029:16]「缠中说禅背驰-转折定理：某级别趋势的背驰将导致该趋势最后一个中枢的级别扩展、该级别更大级别的盘整或该级别以上级别的反趋势。」
[029:52]「以上三种情况，就完全分类了某级别背驰后的级别与力度，也就是某级别的第一类买点后将发生怎么样的情况，而第一类卖点的情况是一样的，只是方向相反。」 -/
def trendEndClassify (rc : ForceRecipe R) (mode : ForceCompareMode) (side : Dir)
    (d : Decomposition R) (x : ℕ → R) (z : Center R) : TrendEndCase → Prop
  | .divergenceExit => ForwardExit side d z ∧ ∃ i j, TrendDiv rc mode side d x z i j
  | .consolidationReversal =>
      ¬ForwardExit side d z ∧ ReverseExit side d z ∧ InnerDiv rc mode side d x z
  | .reverseThird =>
      ¬ForwardExit side d z ∧ ReverseExit side d z ∧ ¬InnerDiv rc mode side d x z

/-- 某级别背驰段：构成趋势背驰或盘整背驰的那段走势类型，记其分解、方向、锚定中枢与原始跨度。

[027:22]「这里，先补充一个定义：就是在某级别的某类型走势，如果构成背驰或盘整背驰，就把这段走势类型称为某级别的背驰段。」 -/
structure DivSegment (rc : ForceRecipe R) (mode : ForceCompareMode) (x : ℕ → R) where
  /-- 所在级别的显式分解。 -/
  decomp : Decomposition R
  /-- 离开方向。 -/
  side : Dir
  /-- 锚定中枢。 -/
  center : Center R
  /-- 比较前段下标。 -/
  enter : ℕ
  /-- 背驰段下标。 -/
  leave : ℕ
  /-- 背驰段原始跨度。 -/
  span : Span
  /-- 跨度取自分解中的实际段。 -/
  spanOf : (decomp.steps[leave]?).map Seg.source = some span
  /-- 构成趋势背驰或盘整背驰。 -/
  diverges : TrendDiv rc mode side decomp x center enter leave ∨
    ConsolDiv rc mode side decomp x center enter leave

/-- 背驰段作为区间套的一层。

[061:34]「由此可见，72点这个背驰点的精确定位，是由65开始背驰段的背驰段的背驰段的背驰段构成的，这就构成一个区间套的精确定位，这一切，都可以当下地进行。」 -/
def DivSegment.level {rc : ForceRecipe R} {mode : ForceCompareMode} {x : ℕ → R}
    (s : DivSegment rc mode x) : ChainLevel :=
  ⟨s.decomp.depth, s.span⟩

/-- 纯结构区间套：顶层为背驰段，其下各层层深严格递减、跨度逐级包含；不要求中间级别出现同级背驰。

[027:44]「定理：某大级别的转折点，可以通过不同级别背驰段的逐级收缩范围而确定。」
[027:46]「换言之，某大级别的转折点，先找到其背驰段，然后在次级别图里，找出相应背驰段在次级别里的背驰段，将该过程反复进行下去，直到最低级别，相应的转折点就在该级别背驰段确定的范围内。」
[056:66]「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」 -/
structure NestedDivChain (rc : ForceRecipe R) (mode : ForceCompareMode) (x : ℕ → R) where
  /-- 顶层背驰段。 -/
  top : DivSegment rc mode x
  /-- 逐级向下的层。 -/
  lower : List ChainLevel
  /-- 层深严格递减。 -/
  depthDesc : (top.level :: lower).IsChain (fun a b => b.depth < a.depth)
  /-- 跨度逐级包含。 -/
  nested : (top.level :: lower).IsChain (fun a b => SpanWithin b.span a.span)

/-- 原趋势方向对应的完成形态。

[029:14]「对于上涨的转折，有两种情况：下跌与盘整；对于下跌的转折，也有两种情况：上涨与盘整。转折是有级别的，关于转折与背驰的关系，有如下定理：」 -/
def trendOf (side : Dir) : TrendKind :=
  match side with
  | .up => .uptrend
  | .down => .downtrend

/-- 大级别在切点 `cut` 处转折：自该切点起的完成块不再是原方向趋势。

[029:14]「对于上涨的转折，有两种情况：下跌与盘整；对于下跌的转折，也有两种情况：上涨与盘整。转折是有级别的，关于转折与背驰的关系，有如下定理：」 -/
def BigTurnAt (side : Dir) (big : Decomposition R) (cut : ℕ) : Prop :=
  ∃ b ∈ big.ledger.completed, b.first = cut ∧ classifyTrend b ≠ some (trendOf side)

/-- 小转大义一：次级别背驰段落在大级别末段之内并同向，随后大级别转折。

[043:24]「如果市场的转折与背驰都有这在级别上一一对应关系，那这市场也太没意思、太刻板了，而由于这种小级别背驰逐步积累后导致大级别转折的可能，才使得市场充满当下的生机。」
[044:24]「小级别顶背驰引发大级别向下的必要条件是该级别走势的最后一个次级别中枢出现第三类卖点；」
[044:26]「小级别底背驰引发大级别向上的必要条件提是该级别走势的最后一个次级别中枢出现第三类买点。」
[044:30]「注意，关于这种情况，只有必要条件，而没有充分条件，也就是说不能有一个充分的判断使得一旦出现某种情况，就必然导致大级别的转折。」 -/
def SmallDivTriggersBigTurn {rc : ForceRecipe R} {mode : ForceCompareMode} {x : ℕ → R}
    (small : DivSegment rc mode x) (big : Decomposition R) (cut : ℕ) : Prop :=
  small.decomp.depth < big.depth ∧
    (∃ s, big.steps[cut - 1]? = some s ∧ s.dir = small.side ∧ SpanWithin small.span s.source) ∧
    BigTurnAt small.side big cut

/-- 小转大义二：本级别在切点前没有趋势背驰或盘整背驰，却经反向第三类事件完成转折。

[043:26]「由于背驰的级别不可能大于当下走势的级别，例如一个30分钟级别的背驰，只可能存在于一个至少是30分钟级别的走势类型中，所以就有这两种不同转折方式的明确分类。」
[056:66]「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」 -/
def TurnWithoutSameLevelDiv (rc : ForceRecipe R) (mode : ForceCompareMode) (x : ℕ → R)
    (side : Dir) (big : Decomposition R) (cut : ℕ) : Prop :=
  BigTurnAt side big cut ∧
    (¬∃ z i j, j < cut ∧
      (TrendDiv rc mode side big x z i j ∨ ConsolDiv rc mode side big x z i j)) ∧
    ∃ z ∈ big.ledger.centers, ReverseExit side big z

end Chan.Defs.Dynamics
