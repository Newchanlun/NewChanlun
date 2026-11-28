module

public import Chan.Defs.Limits.Liveness
public import Mathlib.Algebra.BigOperators.Group.Finset.Basic
public import Mathlib.Algebra.Order.Field.Rat

@[expose] public section

namespace Chan.Hypotheses

open Chan.Defs.Alt Chan.Defs.Level Chan.Defs.Limits Chan.Defs.Order Chan.Defs.Signal

/-- #2322 U-6：对指定级别，任一时刻起的统一步数界内各有一段严格上涨与严格下跌。
两端取自原始价格路径，成段由该有限时刻的分解作证；裸价格涨跌或无统一等待界均不足。
[017:60] 「因为某种类型的走势完成以后就会转化为其他类型的走势，对于下跌的走势来说，一旦完成，只能转化为上涨与盘整，因此，一旦能把握下跌走势转化的关节点买入，就在市场中占据了一个最有利的位置，而这个买点，就是前面反复强调的“第一类买点”；」 -/
def LivenessHyp (rule : BlockRule.{0}) (readStage : StageReader Rat rule)
    (depth bound : Nat) (x : InfPath Rat) : Prop :=
  ∀ (since : Nat) (side : Dir), ∃ t, t ≤ since + bound ∧ ∃ s ∈ (readStage depth (prefixOf x (t+1))).val.steps,
    since ≤ s.source.first ∧ s.source.last ≤ t ∧ s.dir = side ∧
      match side with
      | .up => x s.source.first < x s.source.last
      | .down => x s.source.last < x s.source.first

/-- 以 `x (t+1) - x t` 作离散速度，惯性参数限制相邻两步速度变化的绝对值。
[033:34] 「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
def InertiaHyp (x : InfPath Rat) (cap : Rat) : Prop :=
  0 ≤ cap ∧ ∀ t, |(x (t+2) - x (t+1)) - (x (t+1) - x t)| ≤ cap

/-- 从指定离开时刻起，只把推力的同向部分记入预算；对任意有限时长均施加同一个上界。
起算时刻由离开段给定，假设自身不判断背驰。
[033:26] 「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def ExhaustionHyp (thrust : InfPath Rat) (side : Dir) (onset : Nat) (budget : Rat) : Prop :=
  0 ≤ budget ∧ ∀ length : Nat, (Finset.range length).sum (fun i =>
    let f := thrust (onset + i)
    max 0 (match side with | .up => f | .down => -f)) ≤ budget

/-- #2322 U-7：区间外的回复力指向锚定区间，强度至少为同一个正常数 `strength`。
这里只约束下界，允许回复时跳穿整个核。
[033:26] 「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def PullbackHyp (zone : Bar Rat) (restore : Rat → Rat) (strength : Rat) : Prop :=
  0 < strength ∧ ∀ p, (p < zone.lo → strength ≤ restore p) ∧
    (zone.hi < p → restore p ≤ -strength)

/-- #2322 U-7 对照假设：回复下界随离带距离成正比，允许显式误差 `slack`；
与一致正下界不可比，不纳入五项假设包。
[033:26] 「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def LinearPullbackHyp (zone : Bar Rat) (restore : Rat → Rat) (κ slack : Rat) : Prop :=
  0 < κ ∧ 0 ≤ slack ∧ ∀ p,
    (p < zone.lo → κ * (zone.lo - p) - slack ≤ restore p) ∧
    (zone.hi < p → restore p ≤ -(κ * (p - zone.hi)) + slack)

/-- 取同色柱的非负高度。非空柱组左右镜像，左半直到中点不减；允许平顶。
奇数长度的中央柱是唯一没有镜像伙伴的柱，偶数长度则无此柱。
[024:28] 「注意，看MACD 柱子的面积不需要全出来，一般柱子伸长的力度变慢时，把已经出现的面积乘2，就可以当成是该段的面积。」 -/
abbrev SymUnimodalBarGroupHyp (heights : List Rat) : Prop :=
  heights ≠ [] ∧ heights = heights.reverse ∧ (∀ a ∈ heights, 0 ≤ a) ∧
    (heights.take ((heights.length + 1) / 2)).IsChain (· ≤ ·)

/-- 对称组的半组面积：左半各柱全计，奇数长度再计中央柱的一半。
例如 `[1,2,1]` 的读数为 `1 + 2/2 = 2`，而非含整根峰柱的 3。
[024:28] 「注意，看MACD 柱子的面积不需要全出来，一般柱子伸长的力度变慢时，把已经出现的面积乘2，就可以当成是该段的面积。」 -/
def halfPeakArea (heights : List Rat) : Rat :=
  let k := heights.length / 2
  (heights.take k).sum + (if heights.length % 2 = 1 then heights[k]?.getD 0 / 2 else 0)

/-- 一次动力学比较的观测与参数。离开方向、锚定区间、预算及活性步数界均显式给出；回拉接口无须引入柱组。
[072:32] 「站在纯理论的角度，形态学是最根本的。形态学，从本质上就是几何，这部分内容，是无须任何前提的。以前说的本ID理论成立的前提，其实并不是针对这部分的，主要是针对动力学部分。因此，就算一个庄家自己全买了，一个人天天自我交易，也永远逃不出形态学画的圈圈。而动力学方面的东西就不同了，必须有本ID要求的那两个前提：价格充分有效市场里的非完全绝对趋同交易。」 -/
structure DynamicsInputs where
  rule : BlockRule.{0}
  readStage : StageReader Rat rule
  depth : Nat
  price : InfPath Rat
  onset : Nat
  side : Dir
  anchor : Bar Rat
  restore : Rat → Rat
  accelerationCap : Rat
  thrustBudget : Rat
  minRestoringForce : Rat
  livenessBound : Nat

/-- 从二阶差分中扣除同一时刻的结构回复，所得残余量用于推力预算。
[033:24] 「把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。」 -/
def DynamicsInputs.residual (s : DynamicsInputs) (t : ℕ) : ℚ :=
  (s.price (t+2) - s.price (t+1)) - (s.price (t+1) - s.price t) -
    s.restore (s.price (t+1))

/-- 五项条件独立给证。在同一路径上，留给外推力的部分是速度变化减去结构回复力。
`t` 标记两步窗口的起点，回复力取中间时刻 `t+1` 的价位，无需虚设零时刻之前的速度。
[072:32] 「站在纯理论的角度，形态学是最根本的。形态学，从本质上就是几何，这部分内容，是无须任何前提的。以前说的本ID理论成立的前提，其实并不是针对这部分的，主要是针对动力学部分。因此，就算一个庄家自己全买了，一个人天天自我交易，也永远逃不出形态学画的圈圈。而动力学方面的东西就不同了，必须有本ID要求的那两个前提：价格充分有效市场里的非完全绝对趋同交易。」 -/
structure DynamicsHypBundle (s : DynamicsInputs) (barHeights : List ℚ) : Prop where
  liveness : LivenessHyp s.rule s.readStage s.depth s.livenessBound s.price
  inertia : InertiaHyp s.price s.accelerationCap
  exhaustion : ExhaustionHyp s.residual s.side s.onset s.thrustBudget
  pullback : PullbackHyp s.anchor s.restore s.minRestoringForce
  bars : SymUnimodalBarGroupHyp barHeights

/-- B-17 的待检条件命题。在线判据在离开时刻读取同一前缀及其最后中枢；
按 #2322 U-3/U-7，只要求后续一次越过或触及离开侧核沿，不要求样本落入闭核。
[098:16] 「一个背驰后，无论是盘整背驰还是真正的背驰，理论只能保证其回拉原来的中枢，这是正确的思维方式，那么，回拉之后如何，这涉及预测。正确的思维是，把回拉后出现的情况进行完全的分类，根据每种分类对应的后果，决定你自己的对策。」 -/
def DivReturnsToCenterStmt (s : DynamicsInputs)
    (divNow : Chan.Defs.Path.History Rat → Decomposition Rat → Dir → Prop) : Prop :=
  let h := prefixOf s.price (s.onset + 1)
  let d := (s.readStage s.depth h).val
  LivenessHyp s.rule s.readStage s.depth s.livenessBound s.price →
  InertiaHyp s.price s.accelerationCap →
  ExhaustionHyp s.residual s.side s.onset s.thrustBudget →
  PullbackHyp s.anchor s.restore s.minRestoringForce →
  divNow h d s.side →
    (∃ z, d.recent 0 d.steps.length = some z ∧ z.core = s.anchor) →
    ∃ t, s.onset < t ∧
      match s.side with
      | .up => s.price t ≤ s.anchor.hi
      | .down => s.anchor.lo ≤ s.price t

/-- 参与者标签；同方向、同价格的成交仍可区分不同参与者。
[030:24] 「其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。」 -/
structure MarketParticipant where
  id : Nat
  deriving DecidableEq

/-- 一笔已成交委托保留参与者、买卖方向（上为买、下为卖）、成交价与成交数量。
[030:18] 「交易，当然是有规律的，而且这规律是万古不变的，归纳上述就是：交易以时间的不可逆为前提完全等价地反映在价格轨迹上。」 -/
structure OrderEvent where
  participant : MarketParticipant
  side : Dir
  price : Rat
  qty : ℚ
  deriving DecidableEq

/-- 同一时刻可有多笔成交，按先后排列；每笔成交均来自登记参与者。
第一笔成交之前沿用给定初价。
[030:32] 「对本ID的理论有一点是必须明确的，就是本ID的理论是对价格充分有效市场非完全绝对趋同交易的一个完全的数学公理化理论，唯一需要监控的就是价格充分有效市场与非完全绝对趋同交易这两个前提是否还存在，更重要的是，这归根结底是一套关系人的理论，只能不断在交易中修炼，最后比的可是功力。」 -/
structure TaggedMarket where
  participants : Finset MarketParticipant
  tape : Nat → List OrderEvent
  registered : ∀ t, ∀ e ∈ tape t, e.participant ∈ participants
  openingPrice : Rat

/-- 成交价投影取截至该时刻的最后一笔成交；空时刻沿用上次价格。
[030:18] 「交易，当然是有规律的，而且这规律是万古不变的，归纳上述就是：交易以时间的不可逆为前提完全等价地反映在价格轨迹上。」 -/
def tradePrice (m : TaggedMarket) : Nat → Rat
  | 0 => ((m.tape 0).getLast?.map OrderEvent.price).getD m.openingPrice
  | t+1 => ((m.tape (t+1)).getLast?.map OrderEvent.price).getD (tradePrice m t)

/-- 价格有效性相对于给定估值口径：该时刻全部已发生交易所含的估值信息，
由当时的成交价格完全反映。估值函数作为参数独立指定。
[030:32] 「对本ID的理论有一点是必须明确的，就是本ID的理论是对价格充分有效市场非完全绝对趋同交易的一个完全的数学公理化理论，唯一需要监控的就是价格充分有效市场与非完全绝对趋同交易这两个前提是否还存在，更重要的是，这归根结底是一套关系人的理论，只能不断在交易中修炼，最后比的可是功力。」 -/
def EfficientPriceMarket (m : TaggedMarket)
    (value : List (List OrderEvent) → Rat) : Prop :=
  ∀ t, tradePrice m t = value (prefixOf m.tape (t+1))

/-- 两名实际参与者有不同的交易时序或方向：一人下单时，另一人没有同方向交易。
不能用两人完全同步的记录中不同日期的两笔成交作证。
[030:24] 「其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。」 -/
def NonIdenticalTrading (m : TaggedMarket) : Prop :=
  ∃ t u, ∃ a ∈ m.tape t, ∃ b ∈ m.tape u, a.participant ≠ b.participant ∧
    ∀ other ∈ m.tape t, other.participant = b.participant → other.side ≠ a.side

end Chan.Hypotheses
