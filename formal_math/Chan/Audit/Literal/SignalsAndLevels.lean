module

/-!
# 缠论原典字面版定义：买卖点、级别规则与趋势定义（B-1 / B-10 / B-14 / B-22 / B-23）

本模块仅收载原典字面表述的形式化定义与可判定实例，供后续 `Chan/Audit/Math`
进行反例构造与逻辑核验；完全独立自包含，不导入任何主线模块或外部数学库，亦不包含定理证明。
-/

@[expose] public section

namespace Chan.Audit.Literal

/-! ### B-1：三套级别升级规则在不同前提下的输出分离（规则甲 / 规则乙 / 规则丙） -/

/-- 围绕同一重叠核心震荡 `segCount` 段次级别走势后，不同原典规则在各自前提下给出的级别与中枢结果。
引文：[018:40]「例如一个盘整，三个重叠的连续次级别走势类型后，盘整就可以随时完成，也就是说，只要三个重叠的连续次级别走势类型走出来后，盘整随时结束都是完美的，但这可以不结束，可以不断延伸下去，不断围绕这缠中说禅中枢上上下下地延伸下去直到无穷都是可以的。」 -/
inductive LevelRuleOutcome where
  /-- 保持本级别单一中枢延伸，记录 `(当前级别, 中枢包含段数)`。 -/
  | sameLevelExtension (level : Nat) (segmentsInCenter : Nat)
  /-- 延伸满九段升级为高一级别中枢，记录 `(升级后级别, 内部本级中枢组合数)`。 -/
  | upgradedCenter (level : Nat) (subCenterGroups : Nat)
  /-- 同级别分解下不定义延伸，拆分为若干个 3 段同级别盘整连接，记录 `(当前级别, 盘整段数)`。 -/
  | sameLevelConsolidationChain (level : Nat) (consolidations : Nat)
  deriving Repr, DecidableEq

/-- B-1 规则甲字面版（不限延伸段数，仅在两同级中枢波动区间重叠时升级；`020:34` 为开盘封涨停的时间延长例示）。
引文：[018:40]「例如一个盘整，三个重叠的连续次级别走势类型后，盘整就可以随时完成，也就是说，只要三个重叠的连续次级别走势类型走出来后，盘整随时结束都是完美的，但这可以不结束，可以不断延伸下去，不断围绕这缠中说禅中枢上上下下地延伸下去直到无穷都是可以的。」
引文：[020:34]「一个简单的例子就能区别以上的情况：例如，一个股票开盘立刻封涨停，那么，只能算是一分钟级别上出现了走势中枢的延伸，无论这个延伸有多长时间，都不可能产生更大级别的走势中枢。」
引文：[020:44]「缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。」
引文：[二级旁证] [017:530]「什么叫至少？如果一万年在一个区间里，那还是一个中枢。」 -/
def b1_ruleA_unboundedExtLiteral (baseLevel segCount : Nat) : LevelRuleOutcome :=
  .sameLevelExtension baseLevel segCount

/-- B-1 规则乙字面版（`033:16` 为消除多义性所设的延伸限段规则，及 `092:22` 超过 9 个数据升级）：围绕同一中枢延伸满 9 个次级别段即升格为 `baseLevel + 1` 级别中枢。
引文：[033:16]「这种情况，只要对中枢延伸的数量进行限制，就可以消除多义性，一般来说，中枢的延伸不能超过5段，也就是一旦出现6段的延伸，加上形成中枢本身那三段，就构成更大级别的中枢了。」
引文：[092:22]「当然，只要有波动，就可以用类似中枢、走势类型之类的手段去分析，不过Zn的数量不会过于庞大，不会超过9个数据，超过了，次级别就要升级了，所以这样的分析意义不大。」
引文：[二级旁证] [032:165]「延伸不能超过9个次级别，否则就变成更大级别的，这根据定义很容易理解。」 -/
def b1_ruleB_nineSegUpgradeLiteral (baseLevel segCount : Nat) : LevelRuleOutcome :=
  if segCount ≥ 9 then
    .upgradedCenter (baseLevel + 1) (segCount / 3)
  else
    .sameLevelExtension baseLevel segCount

/-- B-1 规则丙字面版（`038:26` 作者显式另行制定的同级别分解规则）：在目标级别不定义延伸，每 3 段切分为一个本级盘整，允许盘整+盘整连接。
引文：[038:26]「因此，完全合理、不违反任何理论原则的，可以制定出这样的同级别分解规则：在某级别中，不定义中枢延伸，允许该级别上的盘整+盘整连接；与此同时，规定该级别以下的所有级别，都允许中枢延伸，不允许盘整+盘整连接；至于该级别以上级别，根本不考虑，因为所有走势都按该级别给分解了。」
引文：[二级旁证] [041:259]「同级别分解，不允许盘整里的中枢延伸，因此3段次级别就是了，不存在任意的问题。」 -/
def b1_ruleC_sameLevelDecompLiteral (baseLevel segCount : Nat) : LevelRuleOutcome :=
  .sameLevelConsolidationChain baseLevel (segCount / 3)

/-- 从 `LevelRuleOutcome` 提取当前判定出的级别。
引文：[020:44]「缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。」 -/
def b1_outcomeLevel : LevelRuleOutcome → Nat
  | .sameLevelExtension l _ => l
  | .upgradedCenter l _ => l
  | .sameLevelConsolidationChain l _ => l

/-- 从 `LevelRuleOutcome` 提取当前划分出的独立中枢/盘整单元数量。
引文：[038:26]「因此，完全合理、不违反任何理论原则的，可以制定出这样的同级别分解规则：在某级别中，不定义中枢延伸，允许该级别上的盘整+盘整连接；与此同时，规定该级别以下的所有级别，都允许中枢延伸，不允许盘整+盘整连接；至于该级别以上级别，根本不考虑，因为所有走势都按该级别给分解了。」 -/
def b1_outcomeUnitCount : LevelRuleOutcome → Nat
  | .sameLevelExtension _ _ => 1
  | .upgradedCenter _ _ => 1
  | .sameLevelConsolidationChain _ k => k

/-- B-1 规则甲与规则乙级别输出一致性检验命题：检验“不限段数仅看两中枢波动重叠（规则甲）”与“为消除多义性限 9 段升级（规则乙）”在同一段数输入下的级别判定是否恒同。
所刻画确切命题：`020:34` 谈涨停时间延长、`033:16` 谈限段以消多义性、`038:26` 谈另行制定同级别分解；三者处于不同规则与前提下导致输出不同，本命题仅检验甲、乙两套规则函数的输出是否重合，不将其误写为同一划分同一前提下的直接矛盾。
引文：[020:44]「缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。」
引文：[033:16]「这种情况，只要对中枢延伸的数量进行限制，就可以消除多义性，一般来说，中枢的延伸不能超过5段，也就是一旦出现6段的延伸，加上形成中枢本身那三段，就构成更大级别的中枢了。」 -/
def b1_ruleAAndRuleBAgreeOnLevelLiteral : Prop :=
  ∀ baseLevel segCount : Nat,
    segCount ≥ 3 →
    b1_outcomeLevel (b1_ruleA_unboundedExtLiteral baseLevel segCount) =
      b1_outcomeLevel (b1_ruleB_nineSegUpgradeLiteral baseLevel segCount)

/-- B-1 三套规则的规则分离见证命题：存在同一围绕单一中枢的震荡段数输入，使甲、乙、丙三套规则在各自前提下给出两两不同的 `(级别, 单元数)` 划分结果。
引文：[020:44]「缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。」
引文：[033:16]「这种情况，只要对中枢延伸的数量进行限制，就可以消除多义性，一般来说，中枢的延伸不能超过5段，也就是一旦出现6段的延伸，加上形成中枢本身那三段，就构成更大级别的中枢了。」
引文：[038:26]「因此，完全合理、不违反任何理论原则的，可以制定出这样的同级别分解规则：在某级别中，不定义中枢延伸，允许该级别上的盘整+盘整连接；与此同时，规定该级别以下的所有级别，都允许中枢延伸，不允许盘整+盘整连接；至于该级别以上级别，根本不考虑，因为所有走势都按该级别给分解了。」 -/
def b1_threeLevelRulesSeparated : Prop :=
  ∃ baseLevel segCount : Nat,
    segCount ≥ 3 ∧
    let a := b1_ruleA_unboundedExtLiteral baseLevel segCount
    let b := b1_ruleB_nineSegUpgradeLiteral baseLevel segCount
    let c := b1_ruleC_sameLevelDecompLiteral baseLevel segCount
    a ≠ b ∧ b ≠ c ∧ a ≠ c

/-! ### B-10：第二类买点不同版本与操作策略的精确分离 -/

/-- 第二类买点候选结构，区分均线定义、女上位第一吻缠绕退出保护风控、答疑版本一定义、稳妥操作策略与第 101 课版本四纯位置定义。
引文：[101:22]「其实，所谓第二类买点，就是第一类买点的次级别回抽结束后再次探底或回试的那个次级别走势的结束点。这个定义在前面说得很清楚。」 -/
structure SecondBuyCandidate where
  /-- 第一类买点低点价位（或均线语境下前男上位最低位）。 -/
  firstBuyLow : Int
  /-- 一买后第一段次级别回抽的高点。 -/
  firstBounceHigh : Int
  /-- 随后次级别再次探底/回试的结束点价位。 -/
  retestLow : Int
  /-- 均线系统下是否处于女上位第一次缠绕（第一吻）后的下跌。 -/
  isFemaleFirstKiss : Bool
  /-- 是否由已完成的次级别先上后下两段构成。 -/
  completedSubPair : Bool
  deriving Repr, DecidableEq

/-- B-10 均线期二买定义（`014:28`）：女上位第一吻后出现的下跌构成（不把 `013:26` 的跌破退出保护倒写进定义）。
引文：[014:28]「第二类买点：女上位第一吻后出现的下跌构成」 -/
def b10_maSecondBuyDef (c : SecondBuyCandidate) : Prop :=
  c.isFemaleFirstKiss = true ∧ c.retestLow < c.firstBounceHigh

/-- `b10_maSecondBuyDef` 的可判定实例。 -/
instance instDecidableB10MaSecondBuyDef (c : SecondBuyCandidate) :
    Decidable (b10_maSecondBuyDef c) :=
  inferInstanceAs (Decidable (c.isFemaleFirstKiss = true ∧ c.retestLow < c.firstBounceHigh))

/-- B-10 均线期二买退出保护条件（`013:26` 操作风控，非定义否定）：在女上位第一吻该缠绕上下文（`c.isFemaleFirstKiss = true`）中，一旦跌破前面男上位最低位（`c.retestLow < c.firstBuyLow`），说明买入程序出现问题，须在反弹中出清。
引文：[013:26]「而对于上一章所说的第二个买点，一旦该缠绕中出现跌破前面男上位的最低位」
引文：[二级旁证] [013:26]「就意味着买入程序出现问题，必须在任何一个反弹中把股票出清」 -/
def b10_maSecondBuyExitTrigger (c : SecondBuyCandidate) : Prop :=
  c.isFemaleFirstKiss = true ∧ c.retestLow < c.firstBuyLow

/-- `b10_maSecondBuyExitTrigger` 的可判定实例。 -/
instance instDecidableB10MaSecondBuyExitTrigger (c : SecondBuyCandidate) :
    Decidable (b10_maSecondBuyExitTrigger c) :=
  inferInstanceAs (Decidable (c.isFemaleFirstKiss = true ∧ c.retestLow < c.firstBuyLow))

/-- B-10 答疑版本一二买定义（`052:516` 答疑出处）及 `086:80` 稳妥介入操作条件：一买后次级别先上后下回试，且不跌破第一类买点低点（`retestLow ≥ firstBuyLow`）。
引文：[二级旁证] [052:516]「第二类买点的定义很明确，就是例如一个30分钟的第一类买点，一个5分钟次级别上去后，一个5分钟回试不破低点，那就是第二类买点，你说他该在哪一段？用结合进行次级别分解，只能在第二段。」
引文：[086:80]「当然，有一种稳妥的办法，给那些对大级别背驰判断没信心的，就是都在第二类买点介入，当然，实际操作中，你可以完全不管第二类买点形成中的背驰问题，反正第一类买点次级别上去后，次级别回跌，只要不破第一类买点的位置，就介入。这样，只要后面的走势，在下一个次级别不破第一个次级别上去的高点，就坚决卖掉，如果破，就拿着，等待是否出现第三类买点，出现就继续拿着，不出现就卖掉。」 -/
def b10_secondBuyNoBreakCriterion (c : SecondBuyCandidate) : Prop :=
  c.completedSubPair = true ∧
  c.firstBounceHigh > c.firstBuyLow ∧
  c.retestLow ≥ c.firstBuyLow ∧
  c.retestLow < c.firstBounceHigh

/-- `b10_secondBuyNoBreakCriterion` 的可判定实例。 -/
instance instDecidableB10SecondBuyNoBreakCriterion (c : SecondBuyCandidate) :
    Decidable (b10_secondBuyNoBreakCriterion c) :=
  inferInstanceAs (Decidable (
    c.completedSubPair = true ∧
    c.firstBounceHigh > c.firstBuyLow ∧
    c.retestLow ≥ c.firstBuyLow ∧
    c.retestLow < c.firstBounceHigh))

/-- B-10 版本四二买定义（`101:22,32` 正文纯位置定义）：一买后次级别回抽结束后的再次探底/回试次级别走势结束点，正文明确允许低于第一类买点。
引文：[101:22]「其实，所谓第二类买点，就是第一类买点的次级别回抽结束后再次探底或回试的那个次级别走势的结束点。这个定义在前面说得很清楚。」
引文：[101:32]「第二类买点跌破第一类买点，也就是第二类买点比第一类买点低，这是完全可以的，这里一般都构成盘整背驰」 -/
def b10_secondBuyV4PositionDef (c : SecondBuyCandidate) : Prop :=
  c.completedSubPair = true ∧
  c.firstBounceHigh > c.firstBuyLow ∧
  c.retestLow < c.firstBounceHigh

/-- `b10_secondBuyV4PositionDef` 的可判定实例。 -/
instance instDecidableB10SecondBuyV4PositionDef (c : SecondBuyCandidate) :
    Decidable (b10_secondBuyV4PositionDef c) :=
  inferInstanceAs (Decidable (
    c.completedSubPair = true ∧
    c.firstBounceHigh > c.firstBuyLow ∧
    c.retestLow < c.firstBounceHigh))

/-- B-10 版本分离可检验命题：存在合法候选结构满足第 101 课版本四纯位置定义（`101:22,32`），却不满足答疑 `052:516` 与稳妥策略 `086:80` 的不破低点条件。
引文：[101:32]「第二类买点跌破第一类买点，也就是第二类买点比第一类买点低，这是完全可以的，这里一般都构成盘整背驰」
引文：[二级旁证] [052:516]「第二类买点的定义很明确，就是例如一个30分钟的第一类买点，一个5分钟次级别上去后，一个5分钟回试不破低点，那就是第二类买点，你说他该在哪一段？用结合进行次级别分解，只能在第二段。」 -/
def b10_v1AndV4Separated : Prop :=
  ∃ c : SecondBuyCandidate,
    b10_secondBuyV4PositionDef c ∧ ¬ b10_secondBuyNoBreakCriterion c

/-! ### B-14：`086:76` 底部纯结构第三类卖点在同一时间窗口内与“延续趋势破底续跌”的语义分离 -/

/-- 下跌趋势底背驰转折后的底部第三类卖点情景（聚焦紧接该三卖之后同一时间窗口内的下一段向下回落）。
引文：[086:76]「而且，必须注意，对于趋势的转折来说，例如上面的1分钟下跌趋势，最后背驰转折后，第一个上去的线段卖点，很有可能刚好形成最后一个1分钟中枢的第三类卖点，这时候，这个卖点，几乎没有任何的操作意义，反而是要考虑下来的那个第二类买点。很多抄底的人，经常在第一次冲起后就给震掉，然后再追高买回来，就是没搞清楚这种关系。」 -/
structure BottomThirdSellScenario where
  /-- 下跌趋势最后一个中枢的下沿 `ZD`。 -/
  lastCenterZd : Int
  /-- 下跌趋势最后一个中枢的上沿 `ZG`。 -/
  lastCenterZg : Int
  /-- 向下离开最后中枢并形成底背驰第一类买点的最低点。 -/
  firstBuyLow : Int
  /-- 该低点是否已完成趋势底背驰转折（第一类买点）。 -/
  hasBottomDivergence : Bool
  /-- 一买后第一段次级别反弹的高点（触发纯结构第三类卖点）。 -/
  firstBounceHigh : Int
  /-- 紧接该三卖之后的下一段向下次级别走势的低点（同一时间窗口观测）。 -/
  nextDownLegLow : Int
  deriving Repr, DecidableEq

/-- B-14 纯结构字面第三类卖点谓词（不区分趋势是否已底背驰转折）：次级别向下离开最后中枢后，首次次级别反弹高点严格低于 `ZD`。
引文：[086:76]「而且，必须注意，对于趋势的转折来说，例如上面的1分钟下跌趋势，最后背驰转折后，第一个上去的线段卖点，很有可能刚好形成最后一个1分钟中枢的第三类卖点，这时候，这个卖点，几乎没有任何的操作意义，反而是要考虑下来的那个第二类买点。很多抄底的人，经常在第一次冲起后就给震掉，然后再追高买回来，就是没搞清楚这种关系。」 -/
def b14_pureStructuralThirdSellLiteral (s : BottomThirdSellScenario) : Prop :=
  s.lastCenterZd ≤ s.lastCenterZg ∧
  s.firstBuyLow < s.lastCenterZd ∧
  s.firstBounceHigh > s.firstBuyLow ∧
  s.firstBounceHigh < s.lastCenterZd

/-- `b14_pureStructuralThirdSellLiteral` 的可判定实例。 -/
instance instDecidableB14PureStructuralThirdSellLiteral (s : BottomThirdSellScenario) :
    Decidable (b14_pureStructuralThirdSellLiteral s) :=
  inferInstanceAs (Decidable (
    s.lastCenterZd ≤ s.lastCenterZg ∧
    s.firstBuyLow < s.lastCenterZd ∧
    s.firstBounceHigh > s.firstBuyLow ∧
    s.firstBounceHigh < s.lastCenterZd))

/-- 紧接三卖的同一时间窗口内（下一段向下走势）确实发生局部下跌并构成不破一买低点的第二类买点（忠实对应 `086:76`“下来的那个第二类买点”）。
引文：[086:76]「而且，必须注意，对于趋势的转折来说，例如上面的1分钟下跌趋势，最后背驰转折后，第一个上去的线段卖点，很有可能刚好形成最后一个1分钟中枢的第三类卖点，这时候，这个卖点，几乎没有任何的操作意义，反而是要考虑下来的那个第二类买点。很多抄底的人，经常在第一次冲起后就给震掉，然后再追高买回来，就是没搞清楚这种关系。」 -/
def b14_nextLegFormsNonBreakingSecondBuy (s : BottomThirdSellScenario) : Prop :=
  s.hasBottomDivergence = true ∧
  s.nextDownLegLow < s.firstBounceHigh ∧
  s.nextDownLegLow ≥ s.firstBuyLow

/-- `b14_nextLegFormsNonBreakingSecondBuy` 的可判定实例。 -/
instance instDecidableB14NextLegFormsNonBreakingSecondBuy (s : BottomThirdSellScenario) :
    Decidable (b14_nextLegFormsNonBreakingSecondBuy s) :=
  inferInstanceAs (Decidable (
    s.hasBottomDivergence = true ∧
    s.nextDownLegLow < s.firstBounceHigh ∧
    s.nextDownLegLow ≥ s.firstBuyLow))

/-- 紧接三卖的同一时间窗口内（下一段向下走势）延续原下跌趋势继续破底创新低（`nextDownLegLow < firstBuyLow`）。
引文：[054:60]「注意，并不是说一定要形成该级别第三类卖点后才能大幅度下跌，完全可以用该级别以下小级别的第三类卖点就突破中枢，但有一点是肯定的，就是只要足够长时间，该级别的这第三类卖点一定会出现的，当然，在最极端的情况下，这个卖点离中枢很远的位置了，但有一点是肯定的，就是该卖点后一定继续向下。」 -/
def b14_nextLegBreaksPriorLow (s : BottomThirdSellScenario) : Prop :=
  s.nextDownLegLow < s.firstBuyLow

/-- `b14_nextLegBreaksPriorLow` 的可判定实例。 -/
instance instDecidableB14NextLegBreaksPriorLow (s : BottomThirdSellScenario) :
    Decidable (b14_nextLegBreaksPriorLow s) :=
  inferInstanceAs (Decidable (s.nextDownLegLow < s.firstBuyLow))

/-- B-14 同一时间窗口语义分离见证命题：存在满足纯结构第三类卖点条件的底部转折情景，其紧接下一段向下回落构成不破前低的第二类买点（满足“有向下回落”而不满足“延续原下跌趋势破底续跌”）。
所刻画确切命题：比较同一时间范围（紧接三卖的下一段向下走势），区分“局部向下回落（086:76 第二类买点）”与“延续原下跌趋势破底创新低”，避免拿下跌后再上涨当反例。
引文：[086:76]「而且，必须注意，对于趋势的转折来说，例如上面的1分钟下跌趋势，最后背驰转折后，第一个上去的线段卖点，很有可能刚好形成最后一个1分钟中枢的第三类卖点，这时候，这个卖点，几乎没有任何的操作意义，反而是要考虑下来的那个第二类买点。很多抄底的人，经常在第一次冲起后就给震掉，然后再追高买回来，就是没搞清楚这种关系。」
引文：[086:28]「而且，很有可能，一个小级别的第三类卖点后，反而延伸出大级别的买点，这在震荡中太常见了。」 -/
def b14_bottomThirdSellSeparatesFromTrendBreak : Prop :=
  ∃ s : BottomThirdSellScenario,
    b14_pureStructuralThirdSellLiteral s ∧
    b14_nextLegFormsNonBreakingSecondBuy s ∧
    ¬ b14_nextLegBreaksPriorLow s

/-! ### B-22：区分“完成时趋势定义（017:46）”与“形成时前瞻条件（107:30,32）” -/

/-- 上升趋势候选特征，显式区分已完成状态（`isCompleted = true`）与形成中状态（`isCompleted = false`）。
引文：[107:30]「反弹越搞越大，最后就自然成了反转，而是否如此，根本没必须知道，你唯一需要知道的就是，只要在第一中枢后出现第三类买点并形成非背驰类向上，才可以流着口水地持股睡觉等其余中枢形成，否则，随时都有被反回来的风险。」 -/
structure UpTrendCandidate where
  /-- 该走势类型是否已经完成。 -/
  isCompleted : Bool
  /-- 已形成的同级别依次向上且波动区间互不重叠的中枢个数。 -/
  disjointUpCenters : Nat
  /-- 第一中枢后是否已出现第三类买点。 -/
  hasThirdBuyAfterFirst : Bool
  /-- 三买后的离开段是否为“非背驰类向上”。 -/
  nonDivergentUpward : Bool
  deriving Repr, DecidableEq

/-- B-22 完成时上升趋势定义（`017:46`）：某完成的走势类型至少包含两个依次同向、互不重叠的同级别中枢。
引文：[017:46]「缠中说禅趋势：在任何级别的任何走势中，某完成的走势类型至少包含两个以上依次同向的缠中说禅走势中枢，就称为该级别的缠中说禅趋势。」 -/
def b22_completedUpTrendDef (t : UpTrendCandidate) : Prop :=
  t.isCompleted = true ∧ t.disjointUpCenters ≥ 2

/-- `b22_completedUpTrendDef` 的可判定实例。 -/
instance instDecidableB22CompletedUpTrendDef (t : UpTrendCandidate) :
    Decidable (b22_completedUpTrendDef t) :=
  inferInstanceAs (Decidable (t.isCompleted = true ∧ t.disjointUpCenters ≥ 2))

/-- B-22 形成时上升趋势前瞻条件（`107:30,32`）：尚在等待其余中枢形成的当下，第一中枢后出现第三类买点并形成非背驰类向上。
引文：[107:30]「反弹越搞越大，最后就自然成了反转，而是否如此，根本没必须知道，你唯一需要知道的就是，只要在第一中枢后出现第三类买点并形成非背驰类向上，才可以流着口水地持股睡觉等其余中枢形成，否则，随时都有被反回来的风险。」
引文：[107:32]「有人喜欢精确定义，那么这里其实也给出了什么是上升趋势形成的最精确定义，就是在第一中枢后出现第三类买点并形成非背驰类向上。」 -/
def b22_formingUpTrendCondition (t : UpTrendCandidate) : Prop :=
  t.isCompleted = false ∧
  t.disjointUpCenters = 1 ∧
  t.hasThirdBuyAfterFirst = true ∧
  t.nonDivergentUpward = true

/-- `b22_formingUpTrendCondition` 的可判定实例。 -/
instance instDecidableB22FormingUpTrendCondition (t : UpTrendCandidate) :
    Decidable (b22_formingUpTrendCondition t) :=
  inferInstanceAs (Decidable (
    t.isCompleted = false ∧
    t.disjointUpCenters = 1 ∧
    t.hasThirdBuyAfterFirst = true ∧
    t.nonDivergentUpward = true))

/-- B-22 形成时与完成时分离见证命题：存在满足 `107:32` 形成时条件的当下走势，其尚不满足 `017:46` 的完成时双中枢趋势定义。
所刻画确切命题：明确分开“形成时前瞻条件（等其余中枢形成）”与“完成时形态学定义（至少两中枢）”，并在主线中分别命名，避免将两处不同阶段的陈述混作同一定义。
引文：[017:46]「缠中说禅趋势：在任何级别的任何走势中，某完成的走势类型至少包含两个以上依次同向的缠中说禅走势中枢，就称为该级别的缠中说禅趋势。」
引文：[107:32]「有人喜欢精确定义，那么这里其实也给出了什么是上升趋势形成的最精确定义，就是在第一中枢后出现第三类买点并形成非背驰类向上。」 -/
def b22_formingAndCompletedSeparated : Prop :=
  ∃ t : UpTrendCandidate,
    b22_formingUpTrendCondition t ∧ ¬ b22_completedUpTrendDef t

/-! ### B-23：无限后续演化的活性边界（撤除有限前缀截断与四段悬空断开，仅限中枢间连接段 `b` 使用 `033:24` 缺口或连接段） -/

/-- 已完成同级别走势类型的方向与价格值域 `[lo, hi]`。
引文：[099:30]「由此可见，因为划分中的这种情况，我们就很明确地知道，走势的最大特点就是，连接中枢的走势级别一定小于中枢，换言之，一个走势级别完成后必然面临至少大一级别的中枢震荡。例如，一个5分钟的上涨结束后，必然至少要有一个30分钟的中枢震荡，这就是任何走势的必然结论，没有任何走势可以逃脱。」 -/
structure CompletedWave where
  /-- 是否向上走势（`true` 向上，`false` 向下）。 -/
  isUp : Bool
  /-- 走势类型最低价。 -/
  lo : Int
  /-- 走势类型最高价。 -/
  hi : Int
  deriving Repr, DecidableEq

/-- 三个整数的最大值。
引文：[020:48]「有了上面的定理，就可以很精确地讨论走势中枢的问题了：根据走势中枢的数学表达式： A、B、C，分别的高、低点是a1\a2,b1\b2,c1\c2，则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。」 -/
def waveMax3 (a b c : Int) : Int :=
  let m := if a ≤ b then b else a
  if m ≤ c then c else m

/-- 三个整数的最小值。
引文：[020:48]「有了上面的定理，就可以很精确地讨论走势中枢的问题了：根据走势中枢的数学表达式： A、B、C，分别的高、低点是a1\a2,b1\b2,c1\c2，则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。」 -/
def waveMin3 (a b c : Int) : Int :=
  let m := if a ≤ b then a else b
  if m ≤ c then m else c

/-- 检查相邻两段已完成同级别走势方向交替且首尾端点衔接（无缺口连续性前提）。
引文：[043:20]「例如，一个1分钟级别的顶背驰，就意味着必然导致一个至少1分钟级别的盘整或下跌走势类型，这就为背驰以后可能的走势以及级别给出了很明确的划定。」 -/
def b23_adjacentWavesConnect (w1 w2 : CompletedWave) : Bool :=
  decide (w1.isUp ≠ w2.isUp) &&
  if w1.isUp then decide (w1.hi = w2.hi) else decide (w1.lo = w2.lo)

/-- 检查整条无缺口已完成同级别走势序列每段非退化且相邻首尾衔接、方向交替（在该前提下任意长度 `≥ 4` 的序列均必存在连续三段重叠，契合 `099:24` 后续 `f\g\h` 独立成枢）。
引文：[099:24]「因此，一般划分中，如果中阴状态中从前面的背驰点开始已经构成相应的中枢，例如在a+b+c+d+e+f后又有g\h，f\g\h构成1分钟中枢，那么整个的划分就可以变成a+b+c+d+e+（f+g+h），这样，原来的线段类上涨就可以保持了。」 -/
def b23_validAltWaveSeqBool : List CompletedWave → Bool
  | [] => false
  | [w] => decide (w.lo < w.hi)
  | w1 :: w2 :: rest =>
    decide (w1.lo < w1.hi) &&
    b23_adjacentWavesConnect w1 w2 &&
    b23_validAltWaveSeqBool (w2 :: rest)

/-- 连续三段已完成同级别走势存在非空公共重叠，构成高一级别中枢。
引文：[035:18]「上面就用最低级别的中枢把走势在最低级别上进行了完全分类，而三个连续的最低级别走势类型之间，如果发生重叠关系，也就是三个最低级别走势类型所分别经过的价格区间有交集，那么就形成了高一级别的缠中说禅中枢。」 -/
def b23_tripleOverlapsBool (w1 w2 w3 : CompletedWave) : Bool :=
  decide (waveMax3 w1.lo w2.lo w3.lo ≤ waveMin3 w1.hi w2.hi w3.hi)

/-- 检查走势序列的任意连续三段窗口中是否存在高一级别中枢重叠（允许后续 `f,g,h` 独立成枢）。
引文：[099:24]「因此，一般划分中，如果中阴状态中从前面的背驰点开始已经构成相应的中枢，例如在a+b+c+d+e+f后又有g\h，f\g\h构成1分钟中枢，那么整个的划分就可以变成a+b+c+d+e+（f+g+h），这样，原来的线段类上涨就可以保持了。」 -/
def b23_existsHigherCenterAnywhereBool : List CompletedWave → Bool
  | w1 :: w2 :: w3 :: rest =>
    b23_tripleOverlapsBool w1 w2 w3 || b23_existsHigherCenterAnywhereBool (w2 :: w3 :: rest)
  | _ => false

/-- 构成下跌趋势中单个同级别中枢的真实三段次级别已完成走势见证（上-下-上三段首尾衔接且存在非空公共重叠），所有中枢边界指标直接由三段推导，杜绝裸区间伪造。
引文：[017:38]「某级别走势类型中，被至少三个连续次级别走势类型所重叠的部分，称为缠中说禅走势中枢」
引文：[020:52]「为方便起见，以后都把这些与中枢方向一致的次级别走势类型称为Z走势段，按中枢中的时间顺序，分别记为Zn等，而相应的高、低点分别记为gn、dn,定义四个指标：GG=max(gn),G=min(gn),D=max(dn),DD=min(dn)，n遍历中枢中所有Zn。」 -/
structure B23CenterWitness where
  /-- 构成中枢的第 1 个次级别已完成走势段（向上 `Z1`）。 -/
  s1 : CompletedWave
  /-- 构成中枢的第 2 个次级别已完成走势段（向下反向段）。 -/
  s2 : CompletedWave
  /-- 构成中枢的第 3 个次级别已完成走势段（向上 `Z2`）。 -/
  s3 : CompletedWave
  deriving Repr, DecidableEq

/-- 由三段见证推导该中枢入口价（向上首段 `s1` 的低点）。
引文：[017:38]「某级别走势类型中，被至少三个连续次级别走势类型所重叠的部分，称为缠中说禅走势中枢」 -/
def B23CenterWitness.entryPrice (c : B23CenterWitness) : Int :=
  c.s1.lo

/-- 由三段见证推导该中枢出口价（向上末段 `s3` 的高点）。
引文：[017:38]「某级别走势类型中，被至少三个连续次级别走势类型所重叠的部分，称为缠中说禅走势中枢」 -/
def B23CenterWitness.exitPrice (c : B23CenterWitness) : Int :=
  c.s3.hi

/-- 按 `020:54` 由同向 `Z` 段 `(s1, s3)` 推导中枢核心下沿 `ZD = max(d1, d2)`。
引文：[020:54]「特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：」 -/
def B23CenterWitness.zd (c : B23CenterWitness) : Int :=
  if c.s1.lo ≤ c.s3.lo then c.s3.lo else c.s1.lo

/-- 按 `020:54` 由同向 `Z` 段 `(s1, s3)` 推导中枢核心上沿 `ZG = min(g1, g2)`。
引文：[020:54]「特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：」 -/
def B23CenterWitness.zg (c : B23CenterWitness) : Int :=
  if c.s1.hi ≤ c.s3.hi then c.s1.hi else c.s3.hi

/-- 按 `020:52` 仅遍历同向 `Z` 段 `(s1, s3)` 推导波动最低点 `DD = min(d1, d2)`。
引文：[020:52]「为方便起见，以后都把这些与中枢方向一致的次级别走势类型称为Z走势段，按中枢中的时间顺序，分别记为Zn等，而相应的高、低点分别记为gn、dn,定义四个指标：GG=max(gn),G=min(gn),D=max(dn),DD=min(dn)，n遍历中枢中所有Zn。」 -/
def B23CenterWitness.dd (c : B23CenterWitness) : Int :=
  if c.s1.lo ≤ c.s3.lo then c.s1.lo else c.s3.lo

/-- 按 `020:52` 仅遍历同向 `Z` 段 `(s1, s3)` 推导波动最高点 `GG = max(g1, g2)`。
引文：[020:52]「为方便起见，以后都把这些与中枢方向一致的次级别走势类型称为Z走势段，按中枢中的时间顺序，分别记为Zn等，而相应的高、低点分别记为gn、dn,定义四个指标：GG=max(gn),G=min(gn),D=max(dn),DD=min(dn)，n遍历中枢中所有Zn。」 -/
def B23CenterWitness.gg (c : B23CenterWitness) : Int :=
  if c.s1.hi ≤ c.s3.hi then c.s3.hi else c.s1.hi

/-- 校验三段见证构成合法的同级别回升型三段中枢（`s1` 上、`s2` 下、`s3` 上，逐段非退化、首尾严格衔接且三段存在非空公共重叠）。
引文：[017:38]「某级别走势类型中，被至少三个连续次级别走势类型所重叠的部分，称为缠中说禅走势中枢」 -/
def b23_validUpCenterWitness (c : B23CenterWitness) : Bool :=
  decide (c.s1.isUp = true) &&
  b23_validAltWaveSeqBool [c.s1, c.s2, c.s3] &&
  b23_tripleOverlapsBool c.s1 c.s2 c.s3

/-- 相邻中枢之间的具体向下连接段见证：常规无缺口的次级别向下连接段 `subWave w`，或 `033:24` 明确允许的中枢间向下跳空缺口 `gap`。
引文：[033:24]「在最极端的情况下，在a+A+b+B+c的走势系列类型里，a和c并不是必然存在的，而b完全可以是一个跳空缺口，这样，整个走势就可以简化为两个孤零零的中枢。」 -/
inductive B23Connector where
  /-- 连续无缺口的次级别向下连接段 `b`。 -/
  | subWave (w : CompletedWave)
  /-- `033:24` 允许的相邻两同级中枢间的向下跳空缺口。 -/
  | gap
  deriving Repr, DecidableEq

/-- 校验向下连接见证把前驱出口价 `prevExit` 合法连接到后继入口价 `nextEntry`（无缺口时要求 `w.isUp = false ∧ w.lo < w.hi ∧ w.hi = prevExit ∧ w.lo = nextEntry`；缺口时仅限中枢间且要求 `nextEntry < prevExit`）。
引文：[033:24]「在最极端的情况下，在a+A+b+B+c的走势系列类型里，a和c并不是必然存在的，而b完全可以是一个跳空缺口，这样，整个走势就可以简化为两个孤零零的中枢。」 -/
def b23_validDownConnector (prevExit nextEntry : Int) : B23Connector → Bool
  | .subWave w =>
    decide (w.isUp = false) &&
    decide (w.lo < w.hi) &&
    decide (w.hi = prevExit) &&
    decide (w.lo = nextEntry)
  | .gap =>
    decide (nextEntry < prevExit)

/-- B-23 无限后续连续轨迹前提（带完整三段成枢见证与具体连接段 `b_n` 见证，**绝不**将 `(centers (n + 1)).gg < (centers n).dd` 写入前提以防同义反复）：
已完成同级别向上走势 `t1` 之后，经具体连接见证 `bInit` 衔接至首个由三段次级别走势构成的中枢 `centers 0`；
其后对所有 `n : Nat`，每个 `centers n` 均具完整合法三段成枢见证，经具体连接见证 `links n` 衔接至 `centers (n + 1)`，且仅要求连接段与下一中枢首段满足 `018:64`/`054:24` 对前中枢核心下沿 `zd` 的严格第三类卖点破坏（`entryPrice < prev.zd ∧ s1.hi < prev.zd`）。
注：该前提下既存在后续 `s3` 反抽触及前枢 `dd` 从而形成大一级别中枢扩展的合法轨迹，也存在全程零缺口（全部使用 `.subWave`）且所有相邻中枢波动区间互不重叠的无止境同级下跌趋势（`018:42`/`020:36`）。
引文：[018:42]「同样，面对趋势，形成两个依次同向的缠中说禅走势中枢后，任何趋势都可以随时结束而完美，但也可以不断地延伸下去，形成更多的中枢。」
引文：[018:64]「某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。」
引文：[020:36]「换言之，走势中枢的延伸与不断产生新的走势中枢并相应围绕波动互不重叠而形成趋势，在这两种情况下」
引文：[020:36]「一定不可能形成更大级别的走势中枢。」 -/
def b23_validPostCompletedDownTrendTrace
    (t1 : CompletedWave)
    (bInit : B23Connector)
    (centers : Nat → B23CenterWitness)
    (links : Nat → B23Connector) : Prop :=
  t1.isUp = true ∧
  t1.lo < t1.hi ∧
  b23_validDownConnector t1.hi (centers 0).entryPrice bInit = true ∧
  (centers 0).s1.hi < t1.hi ∧
  (∀ n : Nat,
    b23_validUpCenterWitness (centers n) = true ∧
    b23_validDownConnector (centers n).exitPrice (centers (n + 1)).entryPrice (links n) = true ∧
    (centers (n + 1)).entryPrice < (centers n).zd ∧
    (centers (n + 1)).s1.hi < (centers n).zd)

/-- 依据 `020:44` 走势级别延续定理二：后续同级中枢流中存在连续两个同级中枢的波动区间 `[dd, gg]` 产生重叠，从而形成高一级别中枢。
引文：[020:44]「缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。」 -/
def b23_hasOverlappingCenterPair (centers : Nat → B23CenterWitness) : Prop :=
  ∃ n : Nat,
    (centers n).dd ≤ (centers (n + 1)).gg ∧
    (centers (n + 1)).dd ≤ (centers n).gg

/-- B-23 无活性前提检验命题（带完整三段成枢与连续连接段 `b_n` 见证、无前提循环）：一个同级别走势 `t1` 完成后，在不引入“后续反向趋势必然终结”的活性公理、允许后续持续经连续连接段或 `033:24` 缺口走入满足第三类卖点破坏的无穷同级中枢链时，仍必然出现首中枢与 `t1` 区间相交或相邻同级中枢波动重叠从而进入大一级别中枢震荡。
所刻画确切命题：揭示 `099:30` 与 `043:20` 的真实逻辑边界——当后续满足活性（至少走出 3 段无缺口交替已完成同级走势）时，高一级中枢确实必然成立（含 `099:24` 后续 `f\g\h` 独立成枢）；但若剥离活性公理，即便要求每枢具备完整三段成枢见证且相邻中枢全程以无缺口次级别向下连接段 `.subWave` 首尾衔接（且不预先假定波动分离、同时排除 `centers 0` 回到 `t1` 区间内的伪反例），仍存在合法无止境同级下跌趋势使大一级别中枢永不出现。
引文：[099:30]「由此可见，因为划分中的这种情况，我们就很明确地知道，走势的最大特点就是，连接中枢的走势级别一定小于中枢，换言之，一个走势级别完成后必然面临至少大一级别的中枢震荡。例如，一个5分钟的上涨结束后，必然至少要有一个30分钟的中枢震荡，这就是任何走势的必然结论，没有任何走势可以逃脱。」
引文：[018:42]「同样，面对趋势，形成两个依次同向的缠中说禅走势中枢后，任何趋势都可以随时结束而完美，但也可以不断地延伸下去，形成更多的中枢。」
引文：[033:24]「在最极端的情况下，在a+A+b+B+c的走势系列类型里，a和c并不是必然存在的，而b完全可以是一个跳空缺口，这样，整个走势就可以简化为两个孤零零的中枢。」 -/
def b23_unconditionalHigherCenterWithoutLivenessLiteral : Prop :=
  ∀ (t1 : CompletedWave) (bInit : B23Connector)
    (centers : Nat → B23CenterWitness) (links : Nat → B23Connector),
    b23_validPostCompletedDownTrendTrace t1 bInit centers links →
    (t1.lo ≤ (centers 0).gg ∧ (centers 0).dd ≤ t1.hi) ∨
    b23_hasOverlappingCenterPair centers

end Chan.Audit.Literal
