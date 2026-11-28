module

public import Chan.Defs.Limits.Liveness
public import Chan.Defs.Dynamics.Divergence

/-!
# M19a 动力学命名假设与极小市场模型

五项假设全部取值为 `Prop`、无默认值、无公理；任一假设的定义都不引用结论谓词 `ReturnsToCenter`。
条件命题 `DivReturnsToCenterStmt` 把每项假设与背驰前提写成独立前件，可逐个剥离。
-/

@[expose] public section

namespace Chan.Hypotheses

open Chan.Defs.Alt Chan.Defs.Limits Chan.Defs.Dynamics Chan.Defs.Signal Chan.Defs.Path

/-- 参与者标签。

[030:24]「其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。」 -/
structure MarketParticipant where
  /-- 编号。 -/
  id : ℕ

/-- 订单/成交事件：参与者、时刻、买卖方向（`up` 买、`down` 卖）、价格与数量。

[030:18]「交易，当然是有规律的，而且这规律是万古不变的，归纳上述就是：交易以时间的不可逆为前提完全等价地反映在价格轨迹上。」 -/
structure OrderEvent (R : Type*) where
  /-- 参与者。 -/
  participant : MarketParticipant
  /-- 时刻。 -/
  time : ℕ
  /-- 买卖方向。 -/
  side : Dir
  /-- 价格。 -/
  price : R
  /-- 数量。 -/
  qty : R

/-- 带参与者标签的市场：按时间不减排列的事件表与成交价格投影。

[030:16]「而本ID的理论，当然也是以这交易时间的不可逆为前提，如果今天的交易可以变成昨天的或者干脆不算了，那本ID的理论马上土崩瓦解。」 -/
structure TaggedMarket (R : Type*) where
  /-- 事件表。 -/
  events : List (OrderEvent R)
  /-- 成交价格投影。 -/
  price : ℕ → R
  /-- 交易时间不可逆：事件按时间不减排列。 -/
  irreversible : events.IsChain (fun a b => a.time ≤ b.time)

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 二阶差分 `x (t+2) - 2 x (t+1) + x t`。

[072:34]「动力学，是属于物理范畴的，但站在更高的层次上看物理，物理的本质就是几何，当然，这是所有物理学家都不可能认同的，但如果用一些几何结构就可以把所有物理的常量给搞掂，那物理学家不认同也是白搭。同样道理，本ID理论里的动力学部分，本质上也是几何，只是这种几何比较特别，需要把价格充分有效市场里的非完全绝对趋同交易作为前提转化为某些几何结构，然后构造出理论的证明来。」 -/
def secondDiff (x : InfPath R) (t : ℕ) : R := x (t + 2) - 2 * x (t + 1) + x t

/-- 活性假设：任意时刻后 `B` 步内既有严格上行也有严格下行，排除永久静止与无回抽单边。

[017:60]「因为上涨和盘整必然要在图形上完成，而上涨和盘整在图形上的要求，是必须包含三个以上的次级别运动，因此后面必须还至少有一个向上的次级别运动，这样的买点是绝对安全的，其安全性由走势的“不患”而保证，这，就是在前面反复强调的第二类买点。」 -/
def LivenessHyp (B : ℕ) (x : InfPath R) : Prop :=
  ∀ n, (∃ m, n < m ∧ m ≤ n + B ∧ x n < x m) ∧ (∃ m, n < m ∧ m ≤ n + B ∧ x m < x n)

/-- 惯性假设：二阶差分绝对值有显式上界 `K`。

[072:34]「动力学，是属于物理范畴的，但站在更高的层次上看物理，物理的本质就是几何，当然，这是所有物理学家都不可能认同的，但如果用一些几何结构就可以把所有物理的常量给搞掂，那物理学家不认同也是白搭。同样道理，本ID理论里的动力学部分，本质上也是几何，只是这种几何比较特别，需要把价格充分有效市场里的非完全绝对趋同交易作为前提转化为某些几何结构，然后构造出理论的证明来。」 -/
def InertiaHyp (K : R) (x : InfPath R) : Prop :=
  ∀ t, abs (secondDiff x t) ≤ K

/-- 衰竭假设：自时刻 `t0`（背驰离开段结束）起，顺向累计推进（定向增量正部之和）不超过预算 `budget`。

[033:30]「那么，这个反转是否成功，不妨把这个后续的反转写成c，那么也只要比较一下a+A+b与c这两段的力度就可以，因为中枢B对这两段的回拉力度是一样的，如果c比a+A+b弱，那当然反转不成功，也就意味着一定要重新回到中枢里，在最强的情况下也至少有一次回拉去确认能否构成一个第三类买点。」 -/
def ExhaustionHyp (side : Dir) (t0 : ℕ) (budget : R) (x : InfPath R) : Prop :=
  ∀ k, ((List.range k).map fun i =>
    max (orient side x (t0 + i + 1) - orient side x (t0 + i)) 0).sum ≤ budget

/-- 回复假设：位于中枢核之外时，二阶差分含指向核的回复项（系数 `κ > 0`，误差 `ε`）。不引用“回到中枢”。

[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def PullbackHyp (z : Chan.Defs.Center R) (κ ε : R) (x : InfPath R) : Prop :=
  0 < κ ∧ ∀ t,
    (z.core.hi < x (t + 1) → secondDiff x t ≤ -(κ * (x (t + 1) - z.core.hi)) + ε) ∧
    (x (t + 1) < z.core.lo → κ * (z.core.lo - x (t + 1)) - ε ≤ secondDiff x t)

/-- 柱组对称单峰假设（离散、峰值点居中）：长度 `2p+1`，非负，峰前单调不减，关于峰位 `p` 对称。
此时“全组面积 = 2 × 半计峰值点的到峰面积”（见 `barGroupHalfPeakArea`）；含峰整计再翻倍不成立，
例如 `1, 2, 1`：全组 4，含峰到峰 3，翻倍 6，而半计峰值点到峰为 2，翻倍 4。

[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def SymUnimodalBarGroupHyp (g : List R) (p : ℕ) : Prop :=
  g.length = 2 * p + 1 ∧
    (∀ i, i < g.length → 0 ≤ g.getD i 0) ∧
    (∀ i, i < p → g.getD i 0 ≤ g.getD (i + 1) 0) ∧
    ∀ k, k ≤ p → g.getD (p - k) 0 = g.getD (p + k) 0

/-- 半计峰值点的到峰面积：峰前各柱之和加峰值的一半。

[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def barGroupHalfPeakArea (g : List R) (p : ℕ) : R := (g.take p).sum + g.getD p 0 / 2

/-- 五项假设的显式打包，参数与证明全部为字段，无默认值。

[030:32]「对本ID的理论有一点是必须明确的，就是本ID的理论是对价格充分有效市场非完全绝对趋同交易的一个完全的数学公理化理论，唯一需要监控的就是价格充分有效市场与非完全绝对趋同交易这两个前提是否还存在，更重要的是，这归根结底是一套关系人的理论，只能不断在交易中修炼，最后比的可是功力。」 -/
structure DynamicsHypBundle (x : InfPath R) where
  /-- 活性步数界。 -/
  liveBound : ℕ
  /-- 活性假设。 -/
  liveness : LivenessHyp liveBound x
  /-- 惯性上界。 -/
  inertiaBound : R
  /-- 惯性假设。 -/
  inertia : InertiaHyp inertiaBound x
  /-- 衰竭方向。 -/
  exhaustSide : Dir
  /-- 衰竭起点。 -/
  exhaustStart : ℕ
  /-- 推进预算。 -/
  budget : R
  /-- 衰竭假设。 -/
  exhaustion : ExhaustionHyp exhaustSide exhaustStart budget x
  /-- 回复所指中枢。 -/
  center : Chan.Defs.Center R
  /-- 回复系数。 -/
  kappa : R
  /-- 回复误差。 -/
  eps : R
  /-- 回复假设。 -/
  pullback : PullbackHyp center kappa eps x
  /-- 柱组。 -/
  barGroup : List R
  /-- 峰位。 -/
  peak : ℕ
  /-- 柱组对称单峰假设。 -/
  symUnimodal : SymUnimodalBarGroupHyp barGroup peak

/-- 结论谓词：时刻 `t0` 之后价格回到中枢核之内。五项假设的定义均不引用本谓词。

[098:16]「一个背驰后，无论是盘整背驰还是真正的背驰，理论只能保证其回拉原来的中枢，这是正确的思维方式，那么，回拉之后如何，这涉及预测。正确的思维是，把回拉后出现的情况进行完全的分类，根据每种分类对应的后果，决定你自己的对策。」 -/
def ReturnsToCenter (z : Chan.Defs.Center R) (x : InfPath R) (t0 : ℕ) : Prop :=
  ∃ t, t0 ≤ t ∧ z.core.lo ≤ x t ∧ x t ≤ z.core.hi

/-- 待检条件命题“在线背驰后回到最后中枢”：各假设与背驰前提为独立前件。只是陈述，不断言成立。

[098:16]「一个背驰后，无论是盘整背驰还是真正的背驰，理论只能保证其回拉原来的中枢，这是正确的思维方式，那么，回拉之后如何，这涉及预测。正确的思维是，把回拉后出现的情况进行完全的分类，根据每种分类对应的后果，决定你自己的对策。」 -/
def DivReturnsToCenterStmt (rc : ForceRecipe R) (mode : ForceCompareMode) (side : Dir)
    (d : Decomposition R) (z : Chan.Defs.Center R) (i cStart : ℕ) (B : ℕ) (K budget κ ε : R)
    (x : InfPath R) (n : ℕ) : Prop :=
  LivenessHyp B x → InertiaHyp K x → ExhaustionHyp side n budget x → PullbackHyp z κ ε x →
    DivOnline rc mode side d z i cStart (prefixOf x (n + 1)) → ReturnsToCenter z x n

/-- 价格充分有效：每笔事件的价格都等价反映在该时刻的价格轨迹上。

[030:32]「对本ID的理论有一点是必须明确的，就是本ID的理论是对价格充分有效市场非完全绝对趋同交易的一个完全的数学公理化理论，唯一需要监控的就是价格充分有效市场与非完全绝对趋同交易这两个前提是否还存在，更重要的是，这归根结底是一套关系人的理论，只能不断在交易中修炼，最后比的可是功力。」
[072:32]「站在纯理论的角度，形态学是最根本的。形态学，从本质上就是几何，这部分内容，是无须任何前提的。以前说的本ID理论成立的前提，其实并不是针对这部分的，主要是针对动力学部分。因此，就算一个庄家自己全买了，一个人天天自我交易，也永远逃不出形态学画的圈圈。而动力学方面的东西就不同了，必须有本ID要求的那两个前提：价格充分有效市场里的非完全绝对趋同交易。」 -/
def EfficientPriceMarket (M : TaggedMarket R) : Prop :=
  ∀ e ∈ M.events, M.price e.time = e.price

/-- 非完全绝对趋同交易：至少有两名不同参与者的事件不同时或方向不同。

[030:24]「其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。」 -/
def NonIdenticalTrading (M : TaggedMarket R) : Prop :=
  ∃ e₁ ∈ M.events, ∃ e₂ ∈ M.events,
    e₁.participant ≠ e₂.participant ∧ (e₁.time ≠ e₂.time ∨ e₁.side ≠ e₂.side)

end Chan.Hypotheses
