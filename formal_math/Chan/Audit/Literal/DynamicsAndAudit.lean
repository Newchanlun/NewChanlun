module

/-!
# 缠论原典字面版定义：动力学、区间套、MACD 与活性（B-16 / B-20 / B-31 & M19b D0 / M14 & B-25 / B-37）

本模块仅收载原典字面表述的形式化定义与可判定实例，供后续 `Chan/Audit/Math`
进行反例构造与逻辑核验；完全独立自包含，不导入任何主线模块或外部数学库，亦不包含定理证明。
-/

@[expose] public section

namespace Chan.Audit.Literal

/-! ### B-16：`079:52` 事后未被破坏才算背驰的字面循环定义 -/

/-- 背驰观测记录：分离“截至当下的前瞻信号”与“事后走势是否发生转折”。
引文：[079:52]「有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。」 -/
structure DivergenceObs where
  /-- 截至时刻 `t` 由历史数据判定的疑似背驰信号。 -/
  exAnteSignal : Bool
  /-- 时刻 `t` 之后走势是否实际发生转折（即可能的背驰未被后续合力破坏）。 -/
  exPostTurned : Bool
  deriving Repr, DecidableEq

/-- B-16 事后背驰字面定义（`079:52`）：仅当事后走势未破坏（即实际发生转折）时，才承认该处出现了背驰。
所刻画确切命题：`079:52` 将“事后未被合力破坏”并入背驰成立条件本身，使“背驰必转折”沦为逻辑同义反复。
引文：[079:52]「有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。」
引文：[二级旁证 029:328]「至于背驰的问题，背驰就一定转折，这可以严格地证明。没有什么循环的，因为背驰，所以不可能产生走势的延伸，就这么简单。」 -/
def b16_divPostHocLiteral (obs : DivergenceObs) : Prop :=
  obs.exAnteSignal = true ∧ obs.exPostTurned = true

/-- `b16_divPostHocLiteral` 的可判定实例。 -/
instance instDecidableB16DivPostHocLiteral (obs : DivergenceObs) :
    Decidable (b16_divPostHocLiteral obs) :=
  inferInstanceAs (Decidable (obs.exAnteSignal = true ∧ obs.exPostTurned = true))

/-- B-16 事后定义下的“背驰必转折”字面陈述：对任意观测记录，`b16_divPostHocLiteral obs → obs.exPostTurned = true`。
所刻画确切命题：该蕴含纯为合取投影的同义反复，对任何前瞻信号均无条件成立，不具可证伪实证内容。
引文：[079:52]「有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。」 -/
def b16_postHocDivImpliesTurnLiteral : Prop :=
  ∀ obs : DivergenceObs, b16_divPostHocLiteral obs → obs.exPostTurned = true

/-- B-16 对照的可证伪前瞻命题：凡当下判为疑似背驰者，事后必然发生转折。
引文：[043:30]「例如，一个30分钟的走势类型，在30分钟级别进入背驰段，当然，这个背驰段并不一定就演化成背驰，因为，小级别的延伸足以使得大级别最终摆脱背驰，这与当下的走势判断相关。」 -/
def b16_exAnteDivImpliesTurnLiteral : Prop :=
  ∀ obs : DivergenceObs, obs.exAnteSignal = true → obs.exPostTurned = true

/-! ### B-20：`056:66` 每级必有同级背驰的字面区间套断言 -/

/-- 多级别区间套中的单级记录。
引文：[027:46]「换言之，某大级别的转折点，先找到其背驰段，然后在次级别图里，找出相应背驰段在次级别里的背驰段，将该过程反复进行下去，直到最低级别，相应的转折点就在该级别背驰段确定的范围内。」 -/
structure NestLevelRecord where
  /-- 级别序号（越大表示级别越高）。 -/
  level : Nat
  /-- 本级转折/背驰段起始时间。 -/
  startT : Nat
  /-- 本级转折/背驰段结束时间。 -/
  endT : Nat
  /-- 该段内部是否实际出现本级别背驰。 -/
  hasSameLevelDiv : Bool
  /-- 该段转折是否由小级别转大级别触发（无本级背驰）。 -/
  turnedBySmallToLarge : Bool
  deriving Repr, DecidableEq

/-- 检查嵌套链是否逐级降级、时间区间逐级包含，且每级均发生了本级背驰或小转大转折。
引文：[056:66]「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」 -/
def b20_validNestChainBool : List NestLevelRecord → Bool
  | [] => false
  | [r] =>
    decide (r.startT ≤ r.endT) && (r.hasSameLevelDiv || r.turnedBySmallToLarge)
  | r1 :: r2 :: rest =>
    decide (r1.startT ≤ r1.endT) &&
    (r1.hasSameLevelDiv || r1.turnedBySmallToLarge) &&
    decide (r2.level < r1.level) &&
    decide (r1.startT ≤ r2.startT) &&
    decide (r2.endT ≤ r1.endT) &&
    b20_validNestChainBool (r2 :: rest)

/-- 合法多级转折嵌套链谓词。
引文：[056:66]「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」 -/
def b20_validNestChain (chain : List NestLevelRecord) : Prop :=
  b20_validNestChainBool chain = true

/-- `b20_validNestChain` 的可判定实例。 -/
instance instDecidableB20ValidNestChain (chain : List NestLevelRecord) :
    Decidable (b20_validNestChain chain) :=
  inferInstanceAs (Decidable (b20_validNestChainBool chain = true))

/-- 检查嵌套链中每一级是否均出现同级别背驰。
引文：[027:44]「定理：某大级别的转折点，可以通过不同级别背驰段的逐级收缩范围而确定。」 -/
def b20_allLevelsHaveSameLevelDiv : List NestLevelRecord → Bool
  | [] => true
  | r :: rest => r.hasSameLevelDiv && b20_allLevelsHaveSameLevelDiv rest

/-- B-20 区间套字面强断言：任何大级别转折的多级嵌套链中，每一级都必然存在同级别背驰。
所刻画确切命题：`027:44` 与 `027:46` 将逐级寻找次级别背驰段表述为普遍定理，而 `056:66` 给出作者自己的反例：大的盘整背驰段内部可以不必有该级别背驰，而以小级别转大级别完成转折。
引文：[027:44]「定理：某大级别的转折点，可以通过不同级别背驰段的逐级收缩范围而确定。」
引文：[027:46]「换言之，某大级别的转折点，先找到其背驰段，然后在次级别图里，找出相应背驰段在次级别里的背驰段，将该过程反复进行下去，直到最低级别，相应的转折点就在该级别背驰段确定的范围内。」
引文：[056:66]「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」 -/
def b20_everyLevelMustDivergeLiteral : Prop :=
  ∀ chain : List NestLevelRecord,
    b20_validNestChain chain → b20_allLevelsHaveSameLevelDiv chain = true

/-! ### B-31 与 M19b D0：`033:26` 假设回拉单调、对称、平移不变的字面同义反复结构 -/

/-- 离开中枢的方向：向上离开或向下离开。
引文：[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
inductive LeaveDir where
  /-- 向上离开中枢。 -/
  | up
  /-- 向下离开中枢。 -/
  | down
  deriving Repr, DecidableEq

/-- B-31 / M19b D0 字面同义反复结构：将 `033:26` 隐含的三条无证明公设（单调性、上下对称性、时间平移不变性）打包为中枢回拉模型。
所刻画确切命题：`033:26` 论证“向上离开比向下离开弱且向下离开被拉回 ⇒ 向上离开必被拉回”，其全部推导力均来自这三条预先塞入的公设，原典并未给出它们在市场走势上的定义或证明。
引文：[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」
引文：[072:34]「动力学，是属于物理范畴的，但站在更高的层次上看物理，物理的本质就是几何，当然，这是所有物理学家都不可能认同的，但如果用一些几何结构就可以把所有物理的常量给搞掂，那物理学家不认同也是白搭。同样道理，本ID理论里的动力学部分，本质上也是几何，只是这种几何比较特别，需要把价格充分有效市场里的非完全绝对趋同交易作为前提转化为某些几何结构，然后构造出理论的证明来。」 -/
structure B31CenterPullbackModel where
  /-- 给定时刻、离开方向与离开力度，走势是否被拉回中枢。 -/
  pulledBack : Nat → LeaveDir → Int → Prop
  /-- 隐含公设 1（力度单调性）：若较强力度被拉回，则更弱力度在同一时刻同方向下亦被拉回。 -/
  monotone : ∀ (t : Nat) (d : LeaveDir) (f1 f2 : Int),
    f2 ≤ f1 → pulledBack t d f1 → pulledBack t d f2
  /-- 隐含公设 2（方向对称性）：中枢对向上离开与向下离开具有相同的回拉作用。 -/
  symmetric : ∀ (t : Nat) (f : Int),
    pulledBack t .up f ↔ pulledBack t .down f
  /-- 隐含公设 3（时间平移不变性）：中枢回拉能力不随时间与市场状态漂移。 -/
  timeInvariant : ∀ (t1 t2 : Nat) (d : LeaveDir) (f : Int),
    pulledBack t1 d f ↔ pulledBack t2 d f

/-- B-31 / M19b D0 打包公设后的字面回拉命题：一旦预设 `B31CenterPullbackModel` 的三条公设，顶背驰必拉回即成一步重写重言式。
引文：[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def b31_pullbackTautologyLiteral : Prop :=
  ∀ (m : B31CenterPullbackModel) (t1 t2 : Nat) (fb fc : Int),
    m.pulledBack t1 .down fb → fc ≤ fb → m.pulledBack t2 .up fc

/-- 不预设单调/对称/平移不变的一般中枢回拉模型（用于对照检验证明缺失）。
引文：[104:28]「具体怎么样，以后慢慢说来。」 -/
structure B31GeneralPullbackModel where
  /-- 给定时刻、离开方向与离开力度，判定是否拉回中枢。 -/
  pulledBack : Nat → LeaveDir → Int → Bool

/-- B-31 无三条隐含公设前提时的字面回拉命题（在一般市场回拉函数下不成立）。
引文：[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def b31_generalPullbackWithoutAssumptionsLiteral : Prop :=
  ∀ (m : B31GeneralPullbackModel) (t1 t2 : Nat) (fb fc : Int),
    m.pulledBack t1 .down fb = true → fc ≤ fb → m.pulledBack t2 .up fc = true

/-! ### M14 / B-25：`063:24` 1 分钟调大参数 MACD 等价大周期 MACD 的字面断言 -/

/-- 精确有理数表示 `num / (denPred + 1)`（分母恒正，避免零依赖外部有理数库且保持线性代数结构）。
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

/-- 计算价格序列的 MACD 柱状图序列 `DIF - DEA`（差值正负号与 `2 * (DIF - DEA)` 完全一致）。
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

/-- 两个精确有理数的正负零符号完全一致（即同在零轴之上、同在零轴之下或同为零）。
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

/-- M14 / B-25 字面断言（`063:24`）：对周期倍数 `k ≥ 2` 与大周期 MACD 参数 `(fast, slow, sig)`，存在调大后的 1 分钟 MACD 参数 `(fast', slow', sig')`（满足 `1 ≤ fast' < slow'`, `1 ≤ sig'`），使任意 1 分钟价格序列在各大周期收盘时刻的 1 分钟柱状图符号与大周期柱状图符号一致。
所刻画确切命题：`063:24` 宣称“如果用 1 分钟的 MACD 把参数调到足够大，效果其实是一样的”；由于大周期仅采样收盘价、对盘中前 `k-1` 根价格零敏感，而任意非退化 1 分钟 EMA 对盘中价格具严格非零权重，盘中波动可任意翻转 1 分钟 MACD 符号而大周期保持不变。
引文：[063:24]「日线的背驰，其实在1分钟图上也可以看出来，只不过是需要把所有相应对比段的MACD都加起来进行处理，这样当然是不切实际的，因此就可以看日线图的MACD，在理论上没有任何特别之处，只是为了方便，如果用1分钟的MACD把参数调到足够大，效果其实是一样的」 -/
def m14_scaledMinMacdEquivCoarseLiteral (k fast slow sig : Nat) : Prop :=
  ∃ fast' slow' sig' : Nat,
    1 ≤ fast' ∧
    fast' < slow' ∧
    1 ≤ sig' ∧
    ∀ ps : List Int,
      m14_seriesSignAgree
        (m14_downsample k (m14_macdHistSeries fast' slow' sig' ps))
        (m14_macdHistSeries fast slow sig (m14_downsample k ps))

/-! ### B-37：无活性前提下震荡必结束的字面断言 -/

/-- 中枢震荡中轴序列 `z` 最终越出中枢区间 `[a, b]`。
引文：[092:24]「一般来说，这个指标是一个监视。这里，存在着一种必然的关系，就是最终，Zn肯定要超越A或B，为什么？如果不这样，就永远不会出现第三类买卖点了，这显然是不可能的。」 -/
def b37_oscillationExitsBand (a b : Int) (z : Nat → Int) : Prop :=
  ∃ n : Nat, z n < a ∨ z n > b

/-- B-37 无活性前提字面断言（`092:24`）：不施加任何活性公理，对任意非空区间 `[a, b]` 与任意震荡序列 `z : Nat → Int`，`z` 最终必然超越 `a` 或 `b`。
所刻画确切命题：`092:24` 以“否则永远不会出现第三类买卖点，这显然是不可能的”为理由得出 `Zn` 必越出中枢，属于用待证结论当理由；在没有活性前提时，恒在区间内的常值或周期震荡序列即为反例。
引文：[092:24]「一般来说，这个指标是一个监视。这里，存在着一种必然的关系，就是最终，Zn肯定要超越A或B，为什么？如果不这样，就永远不会出现第三类买卖点了，这显然是不可能的。」
引文：[092:16]「中枢震荡，最终一定以某级别的第三类买卖点结束。但问题是，如何预先给出有参考价值的提示，也就是如何去监控这震荡是在逐步走强，还是逐步走弱，这是一个有操作价值的问题。当然，顺便地，可以为每次的震荡高低点的把握给出一个大致的区间。」 -/
def b37_unconditionalOscillationExitLiteral : Prop :=
  ∀ (a b : Int) (z : Nat → Int),
    a ≤ b → b37_oscillationExitsBand a b z

end Chan.Audit.Literal
