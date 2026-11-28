module

/-!
# 缠论原典字面版定义：动力学、区间套、MACD 与活性（B-16 / B-20 / B-31 & M19b D0 / M14 & B-25 / B-37）

本模块仅收载原典字面表述的形式化定义与可判定实例，供后续 `Chan/Audit/Math`
进行反例构造与逻辑核验；完全独立自包含，不导入任何主线模块或外部数学库，亦不包含定理证明。
-/

@[expose] public section

namespace Chan.Audit.Literal

/-! ### B-16：前瞻疑似背驰信号与事后确认的防混用逻辑示例（不冒称作者字面同义反复） -/

/-- 背驰观测记录：显式分离截至当下的疑似背驰信号、后续合力是否破坏以及事后是否转折三个独立维度。
所刻画确切命题：`079:52` 仅说明“如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰”，并未直接定义“未被破坏 = 事后已转折”；此处构造三元观测记录，仅用于登记防止将事后结果混入前瞻定义的逻辑边界。
引文：[079:52]「有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。」 -/
structure DivergenceObs where
  /-- 截至时刻 `t` 由既有历史数据判出的疑似背驰信号。 -/
  exAnteSignal : Bool
  /-- 时刻 `t` 之后合力是否未破坏该疑似背驰。 -/
  notDestroyedLater : Bool
  /-- 时刻 `t` 之后走势是否实际发生转折。 -/
  exPostTurned : Bool
  deriving Repr, DecidableEq

/-- B-16 逻辑防混用示例谓词：若实现错误地把“未被破坏”直接等同于“事后已转折”并并入背驰定义，则形成此合取谓词（仅作防混用示例，不作为作者字面定义）。
引文：[079:52]「有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。」 -/
def b16_conflatedPostHocGuardExample (obs : DivergenceObs) : Prop :=
  obs.exAnteSignal = true ∧ obs.notDestroyedLater = true ∧ obs.exPostTurned = true

/-- `b16_conflatedPostHocGuardExample` 的可判定实例。 -/
instance instDecidableB16ConflatedPostHocGuardExample (obs : DivergenceObs) :
    Decidable (b16_conflatedPostHocGuardExample obs) :=
  inferInstanceAs (Decidable (
    obs.exAnteSignal = true ∧ obs.notDestroyedLater = true ∧ obs.exPostTurned = true))

/-- B-16 因果前瞻信号与事后转折的分离见证命题：存在截至当下已进入疑似背驰段、但事后因小级别延伸摆脱背驰而未发生转折的观测记录（忠实对应 `043:30`；注：`056:50` 仅说明 529 当天尾盘前尚不能由区间套确认，其同行后句实际因晚间突发消息立刻确认了背驰，故不将 `056:50` 当作事后被破坏且未转折的实例）。
引文：[043:30]「例如，一个30分钟的走势类型，在30分钟级别进入背驰段，当然，这个背驰段并不一定就演化成背驰，因为，小级别的延伸足以使得大级别最终摆脱背驰，这与当下的走势判断相关。」 -/
def b16_exAnteAndExPostSeparated : Prop :=
  ∃ obs : DivergenceObs,
    obs.exAnteSignal = true ∧ obs.notDestroyedLater = false ∧ obs.exPostTurned = false

/-! ### B-20：绑定目标转折时刻、连续逐级降级至 0 级且区间严格收缩的区间套定位链 -/

/-- 多级别区间套逐级定位中的单级记录。
引文：[027:46]「换言之，某大级别的转折点，先找到其背驰段，然后在次级别图里，找出相应背驰段在次级别里的背驰段，将该过程反复进行下去，直到最低级别，相应的转折点就在该级别背驰段确定的范围内。」 -/
structure NestLevelRecord where
  /-- 级别序号（越大表示级别越高，最低级别为 `0`）。 -/
  level : Nat
  /-- 本级背驰段/转折区间起始时刻。 -/
  startT : Nat
  /-- 本级背驰段/转折区间结束时刻。 -/
  endT : Nat
  /-- 本级内部是否实际存在同级别背驰段。 -/
  hasSameLevelDiv : Bool
  /-- 本级转折是否由小级别转大级别触发（无本级背驰）。 -/
  turnedBySmallToLarge : Bool
  deriving Repr, DecidableEq

/-- 递归校验针对同一目标转折时刻 `turnT` 的多级嵌套链：
1. 每层时间闭区间均包含 `turnT`（`startT ≤ turnT ≤ endT`）且具有合法转折来源（同级背驰或小转大）；
2. 相邻层级别严格连续递降一步（`r2.level + 1 = r1.level`）；
3. 相邻层时间区间真包含并严格收缩（`r1.startT ≤ r2.startT ∧ r2.endT ≤ r1.endT ∧ (r1.startT < r2.startT ∨ r2.endT < r1.endT)`）；
4. 末尾必须落到最低级别 `level = 0` 且定位包含 `turnT`。
引文：[027:46]「换言之，某大级别的转折点，先找到其背驰段，然后在次级别图里，找出相应背驰段在次级别里的背驰段，将该过程反复进行下去，直到最低级别，相应的转折点就在该级别背驰段确定的范围内。」
引文：[056:66]「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」 -/
def b20_validNestTailBool (turnT : Nat) : List NestLevelRecord → Bool
  | [] => false
  | [r] =>
    decide (r.level = 0) &&
    decide (r.startT ≤ turnT) &&
    decide (turnT ≤ r.endT) &&
    (r.hasSameLevelDiv || r.turnedBySmallToLarge)
  | r1 :: r2 :: rest =>
    decide (r1.startT ≤ turnT) &&
    decide (turnT ≤ r1.endT) &&
    (r1.hasSameLevelDiv || r1.turnedBySmallToLarge) &&
    decide (r2.level + 1 = r1.level) &&
    decide (r1.startT ≤ r2.startT) &&
    decide (r2.endT ≤ r1.endT) &&
    (decide (r1.startT < r2.startT) || decide (r2.endT < r1.endT)) &&
    b20_validNestTailBool turnT (r2 :: rest)

/-- 绑定目标转折时刻 `turnT` 的合法多级区间套定位链谓词（布尔版）：
至少两级、顶层非退化（`startT < endT`）且自身已进入大级别背驰段（`hasSameLevelDiv = true`），并逐级连续降级至 `level = 0` 且区间严格收缩围绕同一转折时刻 `turnT`。
引文：[027:46]「换言之，某大级别的转折点，先找到其背驰段，然后在次级别图里，找出相应背驰段在次级别里的背驰段，将该过程反复进行下去，直到最低级别，相应的转折点就在该级别背驰段确定的范围内。」 -/
def b20_validMultiLevelNestChainBool (turnT : Nat) : List NestLevelRecord → Bool
  | r1 :: r2 :: rest =>
    decide (r1.startT < r1.endT) &&
    r1.hasSameLevelDiv &&
    b20_validNestTailBool turnT (r1 :: r2 :: rest)
  | _ => false

/-- 绑定目标转折时刻 `turnT` 的合法多级区间套定位链谓词（`Prop` 版）。
引文：[056:66]「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」 -/
def b20_validMultiLevelNestChain (turnT : Nat) (chain : List NestLevelRecord) : Prop :=
  b20_validMultiLevelNestChainBool turnT chain = true

/-- `b20_validMultiLevelNestChain` 的可判定实例。 -/
instance instDecidableB20ValidMultiLevelNestChain (turnT : Nat) (chain : List NestLevelRecord) :
    Decidable (b20_validMultiLevelNestChain turnT chain) :=
  inferInstanceAs (Decidable (b20_validMultiLevelNestChainBool turnT chain = true))

/-- 检查多级定位链中每一级是否均出现同级别背驰段。
引文：[027:44]「定理：某大级别的转折点，可以通过不同级别背驰段的逐级收缩范围而确定。」 -/
def b20_allLevelsHaveSameLevelDiv : List NestLevelRecord → Bool
  | [] => true
  | r :: rest => r.hasSameLevelDiv && b20_allLevelsHaveSameLevelDiv rest

/-- B-20 原文 `027:44,46` 存在性阅读（“可以通过”逐级寻找背驰段确定）：在给定候选定位链集合 `chains` 中，**存在**至少一条通往目标转折时刻 `turnT`、逐级连续降级至 `0` 级并严格收缩的合法定位链，其每一层均具备同级别背驰段。
引文：[027:44]「定理：某大级别的转折点，可以通过不同级别背驰段的逐级收缩范围而确定。」
引文：[027:46]「换言之，某大级别的转折点，先找到其背驰段，然后在次级别图里，找出相应背驰段在次级别里的背驰段，将该过程反复进行下去，直到最低级别，相应的转折点就在该级别背驰段确定的范围内。」 -/
def b20_existsAllDivNestChainForTurn (turnT : Nat) (chains : List (List NestLevelRecord)) : Prop :=
  ∃ chain : List NestLevelRecord,
    chain ∈ chains ∧
    b20_validMultiLevelNestChain turnT chain ∧
    b20_allLevelsHaveSameLevelDiv chain = true

/-- B-20 项目加强全称检验命题（显式区分于 `027:44,46` 的存在性表述“可以通过”）：对任意目标转折时刻 `turnT` 与任意合法逐级降级至 `0` 级且严格收缩的多级定位链，该链每一层均必出现同级别背驰段。
所刻画确切命题：清晰分列 `027:44,46` 的存在性定位表述（`b20_existsAllDivNestChainForTurn`）与加强全称命题“任一合法逐级定位链每层必有同级背驰”；即使严格绑定同一 `turnT`、强制连续降级 `next.level + 1 = prev.level` 落到 `0` 级且区间真包含严格收缩，`056:66` 的小转大实盘结构依然证伪后者。
引文：[027:44]「定理：某大级别的转折点，可以通过不同级别背驰段的逐级收缩范围而确定。」
引文：[056:66]「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」 -/
def b20_everyValidNestChainHasAllSameLevelDivProposal : Prop :=
  ∀ (turnT : Nat) (chain : List NestLevelRecord),
    b20_validMultiLevelNestChain turnT chain →
    b20_allLevelsHaveSameLevelDiv chain = true

/-! ### B-31 与 M19b D0：分列 `033:26` 单对离开局部论证与 M19b D0 全局加强模型 -/

/-- 离开中枢的方向：向上离开或向下离开。
引文：[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
inductive LeaveDir where
  /-- 向上离开中枢。 -/
  | up
  /-- 向下离开中枢。 -/
  | down
  deriving Repr, DecidableEq

/-- B-31 原典 `033:26` 针对同一中枢一对离开 `(b, c)` 的局部论证输入结构（原话比较的是同一中枢的向下离开 `b` 与向上离开 `c`，且为严格“比……弱”即 `fc < fb`）。
引文：[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
structure B31PairwiseLeaveCase where
  /-- 前段向下离开 `b` 的力度值。 -/
  downLeaveForce : Int
  /-- 后段向上离开 `c` 的力度值。 -/
  upLeaveForce : Int
  /-- 前段向下离开 `b` 是否被拉回中枢。 -/
  downPulledBack : Bool
  /-- 后段向上离开 `c` 是否被拉回中枢。 -/
  upPulledBack : Bool
  deriving Repr, DecidableEq

/-- B-31 无约束模型逻辑可能性见证：在不附加额外动力学公设的自由模型中，逻辑上存在赋值使同一中枢的前段向下离开被拉回、后段向上离开严格弱于前段（`upLeaveForce < downLeaveForce`）且后段未被拉回。
所刻画确切命题：明确标注此为**无约束模型的逻辑可能性见证**（说明若不补齐显式动力学公设，结论不能从纯逻辑推出），并非实盘实证样本。
引文：[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」
引文：[104:28]「具体怎么样，以后慢慢说来。」 -/
def b31_localPairwiseArgumentUnforced : Prop :=
  ∃ p : B31PairwiseLeaveCase,
    p.downPulledBack = true ∧
    p.upLeaveForce < p.downLeaveForce ∧
    p.upPulledBack = false

/-- M19b D0 全局加强模型（项目审计为分析原典论证所需的充分公设而抽取的加强结构，显式与 `033:26` 原文局部论证分列，不冒称作者字面表述）：假定中枢回拉谓词全局满足力度单调性、上下对称性与时间平移不变性。
引文：[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」
引文：[072:34]「动力学，是属于物理范畴的，但站在更高的层次上看物理，物理的本质就是几何，当然，这是所有物理学家都不可能认同的，但如果用一些几何结构就可以把所有物理的常量给搞掂，那物理学家不认同也是白搭。同样道理，本ID理论里的动力学部分，本质上也是几何，只是这种几何比较特别，需要把价格充分有效市场里的非完全绝对趋同交易作为前提转化为某些几何结构，然后构造出理论的证明来。」 -/
structure M19bD0StrengthenedPullbackModel where
  /-- 给定时刻、离开方向与离开力度，走势是否被拉回中枢。 -/
  pulledBack : Nat → LeaveDir → Int → Prop
  /-- 加强公设 1（全局力度单调性）：若强力度被拉回，则严格更弱力度在同一时刻同方向下亦被拉回。 -/
  monotone : ∀ (t : Nat) (d : LeaveDir) (f1 f2 : Int),
    f2 < f1 → pulledBack t d f1 → pulledBack t d f2
  /-- 加强公设 2（全局方向对称性）：同一时刻下，向上离开与向下离开具有相同回拉作用。 -/
  symmetric : ∀ (t : Nat) (f : Int),
    pulledBack t .up f ↔ pulledBack t .down f
  /-- 加强公设 3（全局时间平移不变性）：不同时刻的回拉作用不变。 -/
  timeInvariant : ∀ (t1 t2 : Nat) (d : LeaveDir) (f : Int),
    pulledBack t1 d f ↔ pulledBack t2 d f

/-- M19b D0 全局加强模型下的充分推论陈述（采用原话严格不等 `fc < fb`）：一旦装入上述三条未证加强公设，回拉结论形式封闭。
引文：[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def m19bD0_strengthenedPullbackClosure : Prop :=
  ∀ (m : M19bD0StrengthenedPullbackModel) (t1 t2 : Nat) (fb fc : Int),
    m.pulledBack t1 .down fb → fc < fb → m.pulledBack t2 .up fc

/-! ### M14 / B-25：精确有理数 MACD 与项目提出的逐点同号加强命题（排除 `sig = 1` 退化） -/

/-- 精确有理数表示 `num / (denPred + 1)`（分母恒正）。
注意：`ExactRat` 上派生 `DecidableEq` 判定的是**表示相等**（分子、分母字段逐位一致，例如 `1/2 ≠ 2/4`）；**数值相等**请使用交叉相乘谓词 `ExactRat.valEq`。
引文：[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
structure ExactRat where
  /-- 分子。 -/
  num : Int
  /-- 分母减一（实际分母为 `denPred + 1 ≥ 1`）。 -/
  denPred : Nat
  deriving Repr, DecidableEq

/-- 整数嵌入精确有理数。
引文：[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def ExactRat.ofInt (z : Int) : ExactRat :=
  { num := z, denPred := 0 }

/-- 精确有理数**数值相等**谓词（交叉相乘 `a.num * (b.denPred + 1) = b.num * (a.denPred + 1)`，区别于结构表示相等 `=`）。
引文：[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def ExactRat.valEq (a b : ExactRat) : Prop :=
  a.num * Int.ofNat (b.denPred + 1) = b.num * Int.ofNat (a.denPred + 1)

/-- `ExactRat.valEq` 的可判定实例。 -/
instance instDecidableExactRatValEq (a b : ExactRat) : Decidable (ExactRat.valEq a b) :=
  inferInstanceAs (Decidable (
    a.num * Int.ofNat (b.denPred + 1) = b.num * Int.ofNat (a.denPred + 1)))

/-- 精确有理数减法。
引文：[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def ExactRat.sub (a b : ExactRat) : ExactRat :=
  let da := a.denPred + 1
  let db := b.denPred + 1
  { num := a.num * Int.ofNat db - b.num * Int.ofNat da
    denPred := da * db - 1 }

/-- 精确有理数严格小于谓词。
引文：[063:24]「日线的背驰，其实在1分钟图上也可以看出来，只不过是需要把所有相应对比段的MACD都加起来进行处理，这样当然是不切实际的，因此就可以看日线图的MACD，在理论上没有任何特别之处，只是为了方便，如果用1分钟的MACD把参数调到足够大，效果其实是一样的」 -/
def ExactRat.lt (a b : ExactRat) : Prop :=
  a.num * Int.ofNat (b.denPred + 1) < b.num * Int.ofNat (a.denPred + 1)

/-- `ExactRat.lt` 的可判定实例。 -/
instance instDecidableExactRatLt (a b : ExactRat) : Decidable (ExactRat.lt a b) :=
  inferInstanceAs (Decidable (
    a.num * Int.ofNat (b.denPred + 1) < b.num * Int.ofNat (a.denPred + 1)))

/-- 单步标准 EMA 递推：`EMA_t = (2 * x_t + (n - 1) * EMA_{t-1}) / (n + 1)`（当 `n = 0` 时退化为恒取 `x_t`）。
引文：[063:24]「日线的背驰，其实在1分钟图上也可以看出来，只不过是需要把所有相应对比段的MACD都加起来进行处理，这样当然是不切实际的，因此就可以看日线图的MACD，在理论上没有任何特别之处，只是为了方便，如果用1分钟的MACD把参数调到足够大，效果其实是一样的」 -/
def m14_emaStep (n : Nat) (prev x : ExactRat) : ExactRat :=
  if n = 0 then
    x
  else
    let dPrev := prev.denPred + 1
    let dX := x.denPred + 1
    let numVal :=
      (2 * x.num) * Int.ofNat dPrev +
      Int.ofNat (n - 1) * prev.num * Int.ofNat dX
    let denVal := (n + 1) * dPrev * dX
    { num := numVal, denPred := denVal - 1 }

/-- 辅助递归：由前一期 EMA 值计算剩余序列的 EMA 序列。
引文：[063:24]「日线的背驰，其实在1分钟图上也可以看出来，只不过是需要把所有相应对比段的MACD都加起来进行处理，这样当然是不切实际的，因此就可以看日线图的MACD，在理论上没有任何特别之处，只是为了方便，如果用1分钟的MACD把参数调到足够大，效果其实是一样的」 -/
def m14_emaLoop (n : Nat) (prev : ExactRat) : List ExactRat → List ExactRat
  | [] => []
  | x :: rest =>
    let cur := m14_emaStep n prev x
    cur :: m14_emaLoop n cur rest

/-- 对有理数序列计算 `n` 周期标准 EMA 序列（首项 `EMA_0 = x_0`）。
引文：[063:24]「日线的背驰，其实在1分钟图上也可以看出来，只不过是需要把所有相应对比段的MACD都加起来进行处理，这样当然是不切实际的，因此就可以看日线图的MACD，在理论上没有任何特别之处，只是为了方便，如果用1分钟的MACD把参数调到足够大，效果其实是一样的」 -/
def m14_emaSeries (n : Nat) : List ExactRat → List ExactRat
  | [] => []
  | x :: rest => x :: m14_emaLoop n x rest

/-- 逐项计算两有理数序列之差。
引文：[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def m14_zipSub : List ExactRat → List ExactRat → List ExactRat
  | a :: as, b :: bs => ExactRat.sub a b :: m14_zipSub as bs
  | _, _ => []

/-- 计算价格序列的 MACD 柱状图序列 `DIF - DEA`。
引文：[063:24]「日线的背驰，其实在1分钟图上也可以看出来，只不过是需要把所有相应对比段的MACD都加起来进行处理，这样当然是不切实际的，因此就可以看日线图的MACD，在理论上没有任何特别之处，只是为了方便，如果用1分钟的MACD把参数调到足够大，效果其实是一样的」 -/
def m14_macdHistSeries (fast slow sig : Nat) (ps : List Int) : List ExactRat :=
  let qs := ps.map ExactRat.ofInt
  let dif := m14_zipSub (m14_emaSeries fast qs) (m14_emaSeries slow qs)
  let dea := m14_emaSeries sig dif
  m14_zipSub dif dea

/-- 辅助递归：每 `k` 根取第 `k` 根元素（大周期收盘下采样）。
引文：[063:24]「日线的背驰，其实在1分钟图上也可以看出来，只不过是需要把所有相应对比段的MACD都加起来进行处理，这样当然是不切实际的，因此就可以看日线图的MACD，在理论上没有任何特别之处，只是为了方便，如果用1分钟的MACD把参数调到足够大，效果其实是一样的」 -/
def m14_downsampleLoop {α : Type} (k step : Nat) : List α → List α
  | [] => []
  | x :: rest =>
    if step = k then x :: m14_downsampleLoop k 1 rest
    else m14_downsampleLoop k (step + 1) rest

/-- 对 1 分钟序列按周期倍数 `k` 下采样，取每个大周期收盘时刻对应的值。
引文：[063:24]「日线的背驰，其实在1分钟图上也可以看出来，只不过是需要把所有相应对比段的MACD都加起来进行处理，这样当然是不切实际的，因此就可以看日线图的MACD，在理论上没有任何特别之处，只是为了方便，如果用1分钟的MACD把参数调到足够大，效果其实是一样的」 -/
def m14_downsample {α : Type} (k : Nat) (xs : List α) : List α :=
  if k = 0 then [] else m14_downsampleLoop k 1 xs

/-- 两个精确有理数的正负零符号一致。
引文：[103:22]「就一个最简单MACD指标，0轴分为多空主导，也就是说，一旦MACD指标陷入0轴之下，那么就在对应时间单位的图表下进入空头主导，而这是必须远离的。」 -/
def m14_sameSign (a b : ExactRat) : Prop :=
  (ExactRat.lt (ExactRat.ofInt 0) a ↔ ExactRat.lt (ExactRat.ofInt 0) b) ∧
  (ExactRat.lt a (ExactRat.ofInt 0) ↔ ExactRat.lt b (ExactRat.ofInt 0))

/-- `m14_sameSign` 的可判定实例。 -/
instance instDecidableM14SameSign (a b : ExactRat) : Decidable (m14_sameSign a b) :=
  inferInstanceAs (Decidable (
    (ExactRat.lt (ExactRat.ofInt 0) a ↔ ExactRat.lt (ExactRat.ofInt 0) b) ∧
    (ExactRat.lt a (ExactRat.ofInt 0) ↔ ExactRat.lt b (ExactRat.ofInt 0))))

/-- 两条有理数序列逐项符号一致。
引文：[063:24]「日线的背驰，其实在1分钟图上也可以看出来，只不过是需要把所有相应对比段的MACD都加起来进行处理，这样当然是不切实际的，因此就可以看日线图的MACD，在理论上没有任何特别之处，只是为了方便，如果用1分钟的MACD把参数调到足够大，效果其实是一样的」 -/
def m14_seriesSignAgree : List ExactRat → List ExactRat → Prop
  | [], [] => True
  | a :: as, b :: bs => m14_sameSign a b ∧ m14_seriesSignAgree as bs
  | [], _ :: _ => False
  | _ :: _, [] => False

/-- `m14_seriesSignAgree` 的可判定实例。 -/
instance instDecidableM14SeriesSignAgree :
    (xs ys : List ExactRat) → Decidable (m14_seriesSignAgree xs ys)
  | [], [] => isTrue trivial
  | a :: as, b :: bs =>
    match instDecidableM14SameSign a b, instDecidableM14SeriesSignAgree as bs with
    | isTrue h1, isTrue h2 => isTrue ⟨h1, h2⟩
    | isFalse h1, _ => isFalse (fun h => h1 h.1)
    | _, isFalse h2 => isFalse (fun h => h2 h.2)
  | [], _ :: _ => isFalse (fun h => h)
  | _ :: _, [] => isFalse (fun h => h)

/-- M14 / B-25 项目提出的逐点同号加强检验命题（在严格非退化参数域 `k ≥ 2`、`1 ≤ fast < slow`、`sig > 1` 且 `sig' > 1` 下，排除 `EMA_1(DIF) = DIF` 致柱恒为零的退化情形，检验是否存在严格调大的细周期参数使任意价格序列在每个大周期收盘时刻的柱号与大周期柱号完全一致）。
所刻画确切命题：显式标注此为**项目审计提出的加强检验命题**——`063:24` 与 `050:18` 原文讨论的是选定比较段后的 MACD 累加与近似观察效果，并未宣称逐点柱号恒等；本命题仅刻画非退化参数域下细周期调大参数与大周期下采样在严格代数意义上的分离界限，不冒称用它否证原句本身。
引文：[063:24]「日线的背驰，其实在1分钟图上也可以看出来，只不过是需要把所有相应对比段的MACD都加起来进行处理，这样当然是不切实际的，因此就可以看日线图的MACD，在理论上没有任何特别之处，只是为了方便，如果用1分钟的MACD把参数调到足够大，效果其实是一样的」
引文：[050:18]「虽然由于MACD与K线价格相关，所以一般情况下，30分钟级别的走势变化，经常对应在30分钟的MACD上，但这不能因此而改变先根据中枢与走势运动的分析，然后选出需要比较力度的走势段，最后才用MACD辅助判断的顺序原则。」 -/
def m14_pointwiseSignEquivStrengthenedProposal (k fast slow sig : Nat) : Prop :=
  k ≥ 2 →
  1 ≤ fast →
  fast < slow →
  sig > 1 →
  ∃ fast' slow' sig' : Nat,
    fast < fast' ∧
    slow < slow' ∧
    fast' < slow' ∧
    sig' > 1 ∧
    sig ≤ sig' ∧
    ∀ ps : List Int,
      m14_seriesSignAgree
        (m14_downsample k (m14_macdHistSeries fast' slow' sig' ps))
        (m14_macdHistSeries fast slow sig (m14_downsample k ps))

/-! ### B-37：区分 `092:22` 满 9 次窗口（`n ≤ 9`）与超过 9 次升级（`n > 9`），并单列剥离升级前提后的边界模型 -/

/-- 围绕中枢 `[a, b]` 运行的一次实际次级震荡区间 `[lo, hi]`。
引文：[092:18]「一个中枢确立后，中枢区间的一半位置，称为震荡中轴Z。而每一个次级震荡区间的一半位置，依次用Zn表示，当然，最标准的状态，就是Zn刚好就是Z，但这是很特殊的例子。」 -/
structure SubOscillation where
  /-- 次级震荡最低价。 -/
  lo : Int
  /-- 次级震荡最高价。 -/
  hi : Int
  deriving Repr, DecidableEq

/-- 合法围绕中枢 `[a, b]` 的单次次级震荡谓词：自身非退化（`lo < hi`）且与中枢区间 `[a, b]` 存在交集（尚未走出第三类买卖点脱离中枢）。
引文：[092:16]「中枢震荡，最终一定以某级别的第三类买卖点结束。但问题是，如何预先给出有参考价值的提示，也就是如何去监控这震荡是在逐步走强，还是逐步走弱，这是一个有操作价值的问题。当然，顺便地，可以为每次的震荡高低点的把握给出一个大致的区间。」 -/
def b37_validSubOscillation (a b : Int) (o : SubOscillation) : Prop :=
  o.lo < o.hi ∧ o.lo ≤ b ∧ a ≤ o.hi

/-- `b37_validSubOscillation` 的可判定实例。 -/
instance instDecidableB37ValidSubOscillation (a b : Int) (o : SubOscillation) :
    Decidable (b37_validSubOscillation a b o) :=
  inferInstanceAs (Decidable (o.lo < o.hi ∧ o.lo ≤ b ∧ a ≤ o.hi))

/-- 由实际次级震荡区间 `o` 诱导的中点 `Zn = (o.lo + o.hi) / 2` 是否越出中枢区间 `[a, b]`（以精确两倍整数不等式 `o.lo + o.hi < 2 * a ∨ o.lo + o.hi > 2 * b` 表示，避免整除截断失真）。
引文：[092:18]「一个中枢确立后，中枢区间的一半位置，称为震荡中轴Z。而每一个次级震荡区间的一半位置，依次用Zn表示，当然，最标准的状态，就是Zn刚好就是Z，但这是很特殊的例子。」
引文：[092:24]「一般来说，这个指标是一个监视。这里，存在着一种必然的关系，就是最终，Zn肯定要超越A或B，为什么？如果不这样，就永远不会出现第三类买卖点了，这显然是不可能的。」 -/
def b37_midpointExitsBand (a b : Int) (o : SubOscillation) : Prop :=
  o.lo + o.hi < 2 * a ∨ o.lo + o.hi > 2 * b

/-- `b37_midpointExitsBand` 的可判定实例。 -/
instance instDecidableB37MidpointExitsBand (a b : Int) (o : SubOscillation) :
    Decidable (b37_midpointExitsBand a b o) :=
  inferInstanceAs (Decidable (o.lo + o.hi < 2 * a ∨ o.lo + o.hi > 2 * b))

/-- B-37 `092:22` 同级监控计数阶段分类：严格区分同级窗口内（`count ≤ 9`）与超过 9 次触发次级别升级（`count > 9`）。
引文：[092:22]「当然，只要有波动，就可以用类似中枢、走势类型之类的手段去分析，不过Zn的数量不会过于庞大，不会超过9个数据，超过了，次级别就要升级了，所以这样的分析意义不大。」 -/
inductive B37MonitorPhase where
  /-- 处于原级别中枢震荡监控窗口内（`count ≤ 9`）。 -/
  | withinNineCount (count : Nat)
  /-- 超过 9 次触发次级别升级，监控对象切换至高一级别（`count > 9`）。 -/
  | upgradedBeyondNine (count : Nat)
  deriving Repr, DecidableEq

/-- 按 `092:22` 界限将震荡次数归入 `n ≤ 9`（同级窗口）或 `n > 9`（升级切换）。
引文：[092:22]「当然，只要有波动，就可以用类似中枢、走势类型之类的手段去分析，不过Zn的数量不会过于庞大，不会超过9个数据，超过了，次级别就要升级了，所以这样的分析意义不大。」 -/
def b37_classifyOscillationCount (count : Nat) : B37MonitorPhase :=
  if count ≤ 9 then .withinNineCount count else .upgradedBeyondNine count

/-- B-37 同级 9 次窗口内未越界见证命题：在 `092:22` 规定的同级监控窗口（满 9 次 `n < 9`，对应 1..9 个 `Zn` 数据）内，存在合法围绕 `[a, b]` 的实际次级震荡流使全部 9 次中点 `Zn` 均落于 `[a, b]` 内，直到第 10 次（`n > 9`）触发升级切换前均未发生越界。
引文：[092:22]「当然，只要有波动，就可以用类似中枢、走势类型之类的手段去分析，不过Zn的数量不会过于庞大，不会超过9个数据，超过了，次级别就要升级了，所以这样的分析意义不大。」
引文：[092:24]「一般来说，这个指标是一个监视。这里，存在着一种必然的关系，就是最终，Zn肯定要超越A或B，为什么？如果不这样，就永远不会出现第三类买卖点了，这显然是不可能的。」 -/
def b37_withinNineWindowMayStayInside : Prop :=
  ∃ (a b : Int) (osc : Nat → SubOscillation),
    a < b ∧
    (∀ n : Nat, n < 9 →
      b37_validSubOscillation a b (osc n) ∧ ¬ b37_midpointExitsBand a b (osc n))

/-- B-37 项目剥离升级规则与活性公理后的边界检验模型（明确标为项目边界模型，不冒称直接否证保留 `092:22` 升级切换规则的 `092:24` 原句）：若删去 `092:22`“超过 9 次即升级切换”与活性公理，检验无限围绕 `[a, b]` 的实际次级震荡流是否必有某次中点 `Zn` 越界。
所刻画确切命题：`092:22` 已显式说明 `Zn` 超过 9 个数据后次级别就要升级；因此“无限次同级等震荡永不越界”仅存在于项目显式剥离 `092:22` 升级规则与活性公理后的边界模型中，用于标定主线活性公理与升级规则的必要作用，不冒称直接否证原句。
引文：[092:18]「一个中枢确立后，中枢区间的一半位置，称为震荡中轴Z。而每一个次级震荡区间的一半位置，依次用Zn表示，当然，最标准的状态，就是Zn刚好就是Z，但这是很特殊的例子。」
引文：[092:22]「当然，只要有波动，就可以用类似中枢、走势类型之类的手段去分析，不过Zn的数量不会过于庞大，不会超过9个数据，超过了，次级别就要升级了，所以这样的分析意义不大。」
引文：[092:24]「一般来说，这个指标是一个监视。这里，存在着一种必然的关系，就是最终，Zn肯定要超越A或B，为什么？如果不这样，就永远不会出现第三类买卖点了，这显然是不可能的。」 -/
def b37_noUpgradeBoundaryModelExitProposal : Prop :=
  ∀ (a b : Int) (osc : Nat → SubOscillation),
    a < b →
    (∀ n : Nat, b37_validSubOscillation a b (osc n)) →
    ∃ n : Nat, b37_midpointExitsBand a b (osc n)

end Chan.Audit.Literal
