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

/-- B-16 因果前瞻信号与事后转折的分离见证命题：存在截至当下已进入疑似背驰段、但事后被小级别延伸破坏而未发生转折的观测记录（忠实对应 `043:30` 与 `056:50`）。
引文：[043:30]「例如，一个30分钟的走势类型，在30分钟级别进入背驰段，当然，这个背驰段并不一定就演化成背驰，因为，小级别的延伸足以使得大级别最终摆脱背驰，这与当下的走势判断相关。」
引文：[056:50]「因为529那天，虽然30分钟明显进入背驰段，但由于当天尾盘是高收的，所以用区间套定理并不能确认当时就是背驰了，毕竟还有第二天的走势。」 -/
def b16_exAnteAndExPostSeparated : Prop :=
  ∃ obs : DivergenceObs,
    obs.exAnteSignal = true ∧ obs.notDestroyedLater = false ∧ obs.exPostTurned = false

/-! ### B-20：合法多级区间套定位链与 `056:66` 小转大反例 -/

/-- 多级别区间套逐级定位中的单级记录。
引文：[027:46]「换言之，某大级别的转折点，先找到其背驰段，然后在次级别图里，找出相应背驰段在次级别里的背驰段，将该过程反复进行下去，直到最低级别，相应的转折点就在该级别背驰段确定的范围内。」 -/
structure NestLevelRecord where
  /-- 级别序号（越大表示级别越高）。 -/
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

/-- 递归校验多级嵌套链的逐级降级、时间闭区间逐级包含及每层转折合法性。
引文：[056:66]「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」 -/
def b20_validNestTailBool : List NestLevelRecord → Bool
  | [] => false
  | [r] =>
    decide (r.startT ≤ r.endT) && (r.hasSameLevelDiv || r.turnedBySmallToLarge)
  | r1 :: r2 :: rest =>
    decide (r1.startT ≤ r1.endT) &&
    (r1.hasSameLevelDiv || r1.turnedBySmallToLarge) &&
    decide (r2.level < r1.level) &&
    decide (r1.startT ≤ r2.startT) &&
    decide (r2.endT ≤ r1.endT) &&
    b20_validNestTailBool (r2 :: rest)

/-- 合法的多级区间套定位链谓词：
1. 至少包含 2 个级别（真正执行了从大级别向次级别的逐级定位，排除单条退化记录）；
2. 顶层为非退化时间区间（`startT < endT`）且自身已进入大级别背驰段（`hasSameLevelDiv = true`）；
3. 各级严格降级、时间区间逐级包含，且每级均存在本级背驰或小级别转大级别转折。
引文：[027:46]「换言之，某大级别的转折点，先找到其背驰段，然后在次级别图里，找出相应背驰段在次级别里的背驰段，将该过程反复进行下去，直到最低级别，相应的转折点就在该级别背驰段确定的范围内。」
引文：[056:66]「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」 -/
def b20_validMultiLevelNestChainBool : List NestLevelRecord → Bool
  | r1 :: r2 :: rest =>
    decide (r1.startT < r1.endT) &&
    r1.hasSameLevelDiv &&
    b20_validNestTailBool (r1 :: r2 :: rest)
  | _ => false

/-- 合法多级区间套定位链谓词（`Prop` 版）。
引文：[056:66]「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」 -/
def b20_validMultiLevelNestChain (chain : List NestLevelRecord) : Prop :=
  b20_validMultiLevelNestChainBool chain = true

/-- `b20_validMultiLevelNestChain` 的可判定实例。 -/
instance instDecidableB20ValidMultiLevelNestChain (chain : List NestLevelRecord) :
    Decidable (b20_validMultiLevelNestChain chain) :=
  inferInstanceAs (Decidable (b20_validMultiLevelNestChainBool chain = true))

/-- 检查多级定位链中每一级是否均出现同级别背驰段。
引文：[027:44]「定理：某大级别的转折点，可以通过不同级别背驰段的逐级收缩范围而确定。」 -/
def b20_allLevelsHaveSameLevelDiv : List NestLevelRecord → Bool
  | [] => true
  | r :: rest => r.hasSameLevelDiv && b20_allLevelsHaveSameLevelDiv rest

/-- B-20 强版本区间套断言：在任意从大级别背驰段出发的合法多级定位链中，所有次级层面均必出现同级别背驰。
所刻画确切命题：`027:44,46` 陈述转折点“可以通过”逐级找背驰段定位，此处严格限定为至少两级且顶层为非退化大级别背驰段的合法定位链；即便在此完整前提下，`056:66` 的小转大实盘例子依然证伪“每级必有同级背驰”。
引文：[027:44]「定理：某大级别的转折点，可以通过不同级别背驰段的逐级收缩范围而确定。」
引文：[027:46]「换言之，某大级别的转折点，先找到其背驰段，然后在次级别图里，找出相应背驰段在次级别里的背驰段，将该过程反复进行下去，直到最低级别，相应的转折点就在该级别背驰段确定的范围内。」
引文：[056:66]「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」 -/
def b20_everyLevelMustDivergeLiteral : Prop :=
  ∀ chain : List NestLevelRecord,
    b20_validMultiLevelNestChain chain → b20_allLevelsHaveSameLevelDiv chain = true

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

/-- B-31 原典 `033:26` 局部论证条件与结论的分离检验：同一中枢下前段向下离开被拉回、且后段向上离开严格弱于前段（`upLeaveForce < downLeaveForce`），在无额外动力学公设约束时仍可出现后段未被拉回的实证样本。
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

/-! ### M14 / B-25：精确有理数 MACD 与项目提出的逐点同号加强命题 -/

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

/-- M14 / B-25 项目提出的逐点同号加强检验命题（在合法参数域 `k ≥ 2`、`1 ≤ fast < slow`、`1 ≤ sig` 下，检验是否存在严格调大的 1 分钟参数 `fast' > fast, slow' > slow, sig' ≥ sig` 且 `fast' < slow'`，使任意价格序列在每个大周期收盘时刻的柱号与大周期柱号完全一致）。
所刻画确切命题：显式标注此为**项目审计提出的加强检验命题**——`063:24` 与 `050:18` 原文讨论的是选定比较段后的 MACD 累加与近似观察效果，并未宣称逐点柱号恒等；本命题仅刻画“1 分钟调大参数与大周期收盘下采样在严格代数意义上不等价（盘中混叠敏感性）”的可证分离界限，不冒称用它否证原句本身。
引文：[063:24]「日线的背驰，其实在1分钟图上也可以看出来，只不过是需要把所有相应对比段的MACD都加起来进行处理，这样当然是不切实际的，因此就可以看日线图的MACD，在理论上没有任何特别之处，只是为了方便，如果用1分钟的MACD把参数调到足够大，效果其实是一样的」
引文：[050:18]「虽然由于MACD与K线价格相关，所以一般情况下，30分钟级别的走势变化，经常对应在30分钟的MACD上，但这不能因此而改变先根据中枢与走势运动的分析，然后选出需要比较力度的走势段，最后才用MACD辅助判断的顺序原则。」 -/
def m14_pointwiseSignEquivStrengthenedProposal (k fast slow sig : Nat) : Prop :=
  k ≥ 2 →
  1 ≤ fast →
  fast < slow →
  1 ≤ sig →
  ∃ fast' slow' sig' : Nat,
    fast < fast' ∧
    slow < slow' ∧
    fast' < slow' ∧
    sig ≤ sig' ∧
    ∀ ps : List Int,
      m14_seriesSignAgree
        (m14_downsample k (m14_macdHistSeries fast' slow' sig' ps))
        (m14_macdHistSeries fast slow sig (m14_downsample k ps))

/-! ### B-37：由实际次级震荡区间生成的 `Zn` 中点序列与无活性前提检验 -/

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

/-- B-37 无活性前提字面断言（基于实际次级震荡生成的 `Zn` 中点序列）：对任意非退化中枢 `[a, b]`（`a < b`）及任意由合法围绕 `[a, b]` 震荡构成的次级震荡流 `osc : Nat → SubOscillation`，必然存在某次震荡 `n` 使其实际中点 `Zn` 越出 `[a, b]`。
所刻画确切命题：`092:24` 以“否则永远不会出现第三类买卖点，这显然是不可能的”为理由推出 `Zn` 必越出 `[A, B]`；在未显式引入活性公理（或 `092:22` 满 9 段升级切换至更大级别监控对象）时，满足全部围绕中枢前提的实际震荡流（如反复在 `[a, b]` 内部波动）即可使全部中点 `Zn` 恒落于 `[a, b]` 内。
引文：[092:18]「一个中枢确立后，中枢区间的一半位置，称为震荡中轴Z。而每一个次级震荡区间的一半位置，依次用Zn表示，当然，最标准的状态，就是Zn刚好就是Z，但这是很特殊的例子。」
引文：[092:22]「当然，只要有波动，就可以用类似中枢、走势类型之类的手段去分析，不过Zn的数量不会过于庞大，不会超过9个数据，超过了，次级别就要升级了，所以这样的分析意义不大。」
引文：[092:24]「一般来说，这个指标是一个监视。这里，存在着一种必然的关系，就是最终，Zn肯定要超越A或B，为什么？如果不这样，就永远不会出现第三类买卖点了，这显然是不可能的。」 -/
def b37_unconditionalOscillationExitLiteral : Prop :=
  ∀ (a b : Int) (osc : Nat → SubOscillation),
    a < b →
    (∀ n : Nat, b37_validSubOscillation a b (osc n)) →
    ∃ n : Nat, b37_midpointExitsBand a b (osc n)

end Chan.Audit.Literal
