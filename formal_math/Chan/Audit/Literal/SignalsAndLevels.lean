module

/-!
# 缠论原典字面版定义：买卖点、级别规则与趋势定义（B-1 / B-10 / B-14 / B-22 / B-23）

本模块仅收载原典字面表述的形式化定义与可判定实例，供后续 `Chan/Audit/Math`
进行反例构造与逻辑核验；完全独立自包含，不导入任何主线模块或外部数学库，亦不包含定理证明。
-/

@[expose] public section

namespace Chan.Audit.Literal

/-! ### B-1：原典三套互不等价的级别升级规则字面版 -/

/-- 围绕同一重叠核心震荡 `segCount` 段次级别走势后，不同原典规则给出的级别与中枢结果。
引文：[018:40]「例如一个盘整，三个重叠的连续次级别走势类型后，盘整就可以随时完成，也就是说，只要三个重叠的连续次级别走势类型走出来后，盘整随时结束都是完美的，但这可以不结束，可以不断延伸下去，不断围绕这缠中说禅中枢上上下下地延伸下去直到无穷都是可以的。」 -/
inductive LevelRuleOutcome where
  /-- 保持本级别单一中枢延伸，记录 `(当前级别, 中枢包含段数)`。 -/
  | sameLevelExtension (level : Nat) (segmentsInCenter : Nat)
  /-- 延伸满九段升级为高一级别中枢，记录 `(升级后级别, 内部本级中枢组合数)`。 -/
  | upgradedCenter (level : Nat) (subCenterGroups : Nat)
  /-- 同级别分解下不定义延伸，拆分为若干个 3 段同级别盘整连接，记录 `(当前级别, 盘整段数)`。 -/
  | sameLevelConsolidationChain (level : Nat) (consolidations : Nat)
  deriving Repr, DecidableEq

/-- B-1 规则甲字面版（延伸无上限）：未出现两个同级别中枢波动区间重叠前，延伸无论持续多少段均保持原级别中枢，不升级。
引文：[018:40]「例如一个盘整，三个重叠的连续次级别走势类型后，盘整就可以随时完成，也就是说，只要三个重叠的连续次级别走势类型走出来后，盘整随时结束都是完美的，但这可以不结束，可以不断延伸下去，不断围绕这缠中说禅中枢上上下下地延伸下去直到无穷都是可以的。」
引文：[020:34]「一个简单的例子就能区别以上的情况：例如，一个股票开盘立刻封涨停，那么，只能算是一分钟级别上出现了走势中枢的延伸，无论这个延伸有多长时间，都不可能产生更大级别的走势中枢。」
引文：[020:44]「缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。」
引文：[二级旁证 017:530]「什么叫至少？如果一万年在一个区间里，那还是一个中枢。」 -/
def b1_ruleA_unboundedExtLiteral (baseLevel segCount : Nat) : LevelRuleOutcome :=
  .sameLevelExtension baseLevel segCount

/-- B-1 规则乙字面版（延伸满九段升级）：围绕中枢震荡达到 9 个次级别段（形成 3+3+3 组合）即升级为 `baseLevel + 1` 级别中枢。
引文：[033:16]「这种情况，只要对中枢延伸的数量进行限制，就可以消除多义性，一般来说，中枢的延伸不能超过5段，也就是一旦出现6段的延伸，加上形成中枢本身那三段，就构成更大级别的中枢了。」
引文：[092:22]「当然，只要有波动，就可以用类似中枢、走势类型之类的手段去分析，不过Zn的数量不会过于庞大，不会超过9个数据，超过了，次级别就要升级了，所以这样的分析意义不大。」
引文：[二级旁证 032:165]「延伸不能超过9个次级别，否则就变成更大级别的，这根据定义很容易理解。」 -/
def b1_ruleB_nineSegUpgradeLiteral (baseLevel segCount : Nat) : LevelRuleOutcome :=
  if segCount ≥ 9 then
    .upgradedCenter (baseLevel + 1) (segCount / 3)
  else
    .sameLevelExtension baseLevel segCount

/-- B-1 规则丙字面版（同级别分解不定义延伸）：每 3 段次级别走势即划为一个本级盘整，允许同级别盘整+盘整连接，既不延伸也不升级。
引文：[038:26]「因此，完全合理、不违反任何理论原则的，可以制定出这样的同级别分解规则：在某级别中，不定义中枢延伸，允许该级别上的盘整+盘整连接；与此同时，规定该级别以下的所有级别，都允许中枢延伸，不允许盘整+盘整连接；至于该级别以上级别，根本不考虑，因为所有走势都按该级别给分解了。」
引文：[二级旁证 041:259]「同级别分解，不允许盘整里的中枢延伸，因此3段次级别就是了，不存在任意的问题。」 -/
def b1_ruleC_sameLevelDecompLiteral (baseLevel segCount : Nat) : LevelRuleOutcome :=
  .sameLevelConsolidationChain baseLevel (segCount / 3)

/-- 从 `LevelRuleOutcome` 提取判定出的级别。
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

/-- B-1 三套规则字面等价性断言：对任意围绕同一区间震荡 `segCount ≥ 3` 段的序列，甲乙丙三规则给出的级别与中枢划分数一致。
所刻画确切命题：同一段围绕 1 分钟中枢来回 12 段的走势，甲给 1 级 1 中枢、乙升格为 2 级中枢、丙拆成 1 级 4 个盘整连接，三者互不等价。
引文：[020:44]「缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。」
引文：[033:16]「这种情况，只要对中枢延伸的数量进行限制，就可以消除多义性，一般来说，中枢的延伸不能超过5段，也就是一旦出现6段的延伸，加上形成中枢本身那三段，就构成更大级别的中枢了。」
引文：[038:26]「因此，完全合理、不违反任何理论原则的，可以制定出这样的同级别分解规则：在某级别中，不定义中枢延伸，允许该级别上的盘整+盘整连接；与此同时，规定该级别以下的所有级别，都允许中枢延伸，不允许盘整+盘整连接；至于该级别以上级别，根本不考虑，因为所有走势都按该级别给分解了。」 -/
def b1_threeLevelRulesAgreeLiteral : Prop :=
  ∀ baseLevel segCount : Nat,
    segCount ≥ 3 →
    b1_outcomeLevel (b1_ruleA_unboundedExtLiteral baseLevel segCount) =
      b1_outcomeLevel (b1_ruleB_nineSegUpgradeLiteral baseLevel segCount) ∧
    b1_outcomeUnitCount (b1_ruleA_unboundedExtLiteral baseLevel segCount) =
      b1_outcomeUnitCount (b1_ruleC_sameLevelDecompLiteral baseLevel segCount)

/-! ### B-10：第二类买点版本一（均线/回调不破）与版本四（纯位置）字面对照 -/

/-- 第二类买点候选结构，用于对照版本一（均线/回试不破一买低点）与版本四（纯位置允许低于一买）。
引文：[101:22]「其实，所谓第二类买点，就是第一类买点的次级别回抽结束后再次探底或回试的那个次级别走势的结束点。这个定义在前面说得很清楚。」 -/
structure SecondBuyCandidate where
  /-- 第一类买点低点价位。 -/
  firstBuyLow : Int
  /-- 一买后第一段次级别回抽的高点。 -/
  firstBounceHigh : Int
  /-- 随后的次级别再次探底/回试结束点价位。 -/
  retestLow : Int
  /-- 均线系统下是否处于女上位第一次缠绕（第一吻）后的下跌。 -/
  isFemaleFirstKiss : Bool
  /-- 是否由已完成的次级别先上后下两段构成。 -/
  completedSubPair : Bool
  deriving Repr, DecidableEq

/-- B-10 均线期版本字面二买：女上位第一吻后下跌形成低点且不跌破前面男上位最低位。
引文：[014:28]「第二类买点：女上位第一吻后出现的下跌构成」
引文：[013:26]「而对于上一章所说的第二个买点，一旦该缠绕中出现跌破前面男上位的最低位」 -/
def b10_secondBuyMaLiteral (c : SecondBuyCandidate) : Prop :=
  c.isFemaleFirstKiss = true ∧ c.retestLow ≥ c.firstBuyLow

/-- `b10_secondBuyMaLiteral` 的可判定实例。 -/
instance instDecidableB10SecondBuyMaLiteral (c : SecondBuyCandidate) :
    Decidable (b10_secondBuyMaLiteral c) :=
  inferInstanceAs (Decidable (c.isFemaleFirstKiss = true ∧ c.retestLow ≥ c.firstBuyLow))

/-- B-10 版本一字面二买（回调不破一买低点）：一买后次级别回抽再回试，要求 `retestLow ≥ firstBuyLow`。
引文：[二级旁证 052:516]「第二类买点的定义很明确，就是例如一个30分钟的第一类买点，一个5分钟次级别上去后，一个5分钟回试不破低点，那就是第二类买点，你说他该在哪一段？用结合进行次级别分解，只能在第二段。」
引文：[086:80]「当然，有一种稳妥的办法，给那些对大级别背驰判断没信心的，就是都在第二类买点介入，当然，实际操作中，你可以完全不管第二类买点形成中的背驰问题，反正第一类买点次级别上去后，次级别回跌，只要不破第一类买点的位置，就介入。这样，只要后面的走势，在下一个次级别不破第一个次级别上去的高点，就坚决卖掉，如果破，就拿着，等待是否出现第三类买点，出现就继续拿着，不出现就卖掉。」 -/
def b10_secondBuyV1NoBreakLiteral (c : SecondBuyCandidate) : Prop :=
  c.completedSubPair = true ∧
  c.firstBounceHigh > c.firstBuyLow ∧
  c.retestLow ≥ c.firstBuyLow

/-- `b10_secondBuyV1NoBreakLiteral` 的可判定实例。 -/
instance instDecidableB10SecondBuyV1NoBreakLiteral (c : SecondBuyCandidate) :
    Decidable (b10_secondBuyV1NoBreakLiteral c) :=
  inferInstanceAs (Decidable (
    c.completedSubPair = true ∧
    c.firstBounceHigh > c.firstBuyLow ∧
    c.retestLow ≥ c.firstBuyLow))

/-- B-10 版本四字面二买（第 101 课纯位置定义）：一买后次级别回抽结束后的再次探底/回试次级别走势结束点，明确允许跌破第一类买点低点。
引文：[101:22]「其实，所谓第二类买点，就是第一类买点的次级别回抽结束后再次探底或回试的那个次级别走势的结束点。这个定义在前面说得很清楚。」
引文：[101:32]「第二类买点跌破第一类买点，也就是第二类买点比第一类买点低，这是完全可以的，这里一般都构成盘整背驰」 -/
def b10_secondBuyV4PositionLiteral (c : SecondBuyCandidate) : Prop :=
  c.completedSubPair = true ∧
  c.firstBounceHigh > c.firstBuyLow ∧
  c.retestLow < c.firstBounceHigh

/-- `b10_secondBuyV4PositionLiteral` 的可判定实例。 -/
instance instDecidableB10SecondBuyV4PositionLiteral (c : SecondBuyCandidate) :
    Decidable (b10_secondBuyV4PositionLiteral c) :=
  inferInstanceAs (Decidable (
    c.completedSubPair = true ∧
    c.firstBounceHigh > c.firstBuyLow ∧
    c.retestLow < c.firstBounceHigh))

/-- B-10 字面等价性断言：版本一（不破低点）与版本四（第 101 课纯位置定义）等价。
所刻画确切命题：`101:22` 称“这个定义在前面说得很清楚”，但 `101:32` 允许二买低于一买，与版本一“不破低点”直接冲突。
引文：[101:22]「其实，所谓第二类买点，就是第一类买点的次级别回抽结束后再次探底或回试的那个次级别走势的结束点。这个定义在前面说得很清楚。」
引文：[101:32]「第二类买点跌破第一类买点，也就是第二类买点比第一类买点低，这是完全可以的，这里一般都构成盘整背驰」 -/
def b10_v1AndV4EquivLiteral : Prop :=
  ∀ c : SecondBuyCandidate,
    b10_secondBuyV1NoBreakLiteral c ↔ b10_secondBuyV4PositionLiteral c

/-! ### B-14：`086:76` 纯结构第三类卖点在底部形态下的字面触发谓词 -/

/-- 下跌趋势底背驰转折后的底部形态情景。
引文：[086:76]「而且，必须注意，对于趋势的转折来说，例如上面的1分钟下跌趋势，最后背驰转折后，第一个上去的线段卖点，很有可能刚好形成最后一个1分钟中枢的第三类卖点，这时候，这个卖点，几乎没有任何的操作意义，反而是要考虑下来的那个第二类买点。很多抄底的人，经常在第一次冲起后就给震掉，然后再追高买回来，就是没搞清楚这种关系。」 -/
structure BottomThirdSellScenario where
  /-- 下跌趋势最后一个中枢的下沿 `ZD`。 -/
  lastCenterZd : Int
  /-- 下跌趋势最后一个中枢的上沿 `ZG`。 -/
  lastCenterZg : Int
  /-- 向下离开最后中枢并形成第一类买点的最低点。 -/
  firstBuyLow : Int
  /-- 该低点是否已完成趋势底背驰转折（即第一类买点）。 -/
  hasBottomDivergence : Bool
  /-- 一买后第一段次级别反弹的高点。 -/
  firstBounceHigh : Int
  /-- 反弹后二次回试（第二类买点）的低点。 -/
  secondBuyLow : Int
  /-- 其后第三段向上走势的高点。 -/
  followUpHigh : Int
  deriving Repr, DecidableEq

/-- B-14 纯结构字面第三类卖点谓词（不区分此前是否已发生底背驰转折）：次级别向下离开最后中枢后，次级别向上反抽高点严格低于 `ZD`。
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

/-- B-14 底部反转后续演化谓词：纯结构第三类卖点触发于一买之后，且后续形成不破底的二买并向上越过最后中枢上沿（并未继续向下创新低）。
引文：[086:28]「而且，很有可能，一个小级别的第三类卖点后，反而延伸出大级别的买点，这在震荡中太常见了。」 -/
def b14_bottomReversalContinuesUp (s : BottomThirdSellScenario) : Prop :=
  s.hasBottomDivergence = true ∧
  s.secondBuyLow > s.firstBuyLow ∧
  s.followUpHigh > s.lastCenterZg

/-- `b14_bottomReversalContinuesUp` 的可判定实例。 -/
instance instDecidableB14BottomReversalContinuesUp (s : BottomThirdSellScenario) :
    Decidable (b14_bottomReversalContinuesUp s) :=
  inferInstanceAs (Decidable (
    s.hasBottomDivergence = true ∧
    s.secondBuyLow > s.firstBuyLow ∧
    s.followUpHigh > s.lastCenterZg))

/-- B-14 字面强断言（`054:60`）：任何满足纯结构第三类卖点条件的点位之后一定继续向下（不会在底部反转向上突破原中枢）。
所刻画确切命题：`054:60` 宣称“该卖点后一定继续向下”，而 `086:76` 指出下跌背驰后首次反弹未回最后中枢即满足纯结构三卖，实际处于底部构造与二买演化中。
引文：[054:60]「注意，并不是说一定要形成该级别第三类卖点后才能大幅度下跌，完全可以用该级别以下小级别的第三类卖点就突破中枢，但有一点是肯定的，就是只要足够长时间，该级别的这第三类卖点一定会出现的，当然，在最极端的情况下，这个卖点离中枢很远的位置了，但有一点是肯定的，就是该卖点后一定继续向下。」
引文：[086:76]「而且，必须注意，对于趋势的转折来说，例如上面的1分钟下跌趋势，最后背驰转折后，第一个上去的线段卖点，很有可能刚好形成最后一个1分钟中枢的第三类卖点，这时候，这个卖点，几乎没有任何的操作意义，反而是要考虑下来的那个第二类买点。很多抄底的人，经常在第一次冲起后就给震掉，然后再追高买回来，就是没搞清楚这种关系。」 -/
def b14_thirdSellAlwaysContinuesDownLiteral : Prop :=
  ∀ s : BottomThirdSellScenario,
    b14_pureStructuralThirdSellLiteral s → ¬ b14_bottomReversalContinuesUp s

/-! ### B-22：`107:32` 把三买加非背驰写进趋势定义的字面版 -/

/-- 上升趋势候选特征，用于对照 `017:46`（中枢计数版）与 `107:32`（第一中枢后三买加非背驰版）。
引文：[107:32]「有人喜欢精确定义，那么这里其实也给出了什么是上升趋势形成的最精确定义，就是在第一中枢后出现第三类买点并形成非背驰类向上。」 -/
structure UpTrendCandidate where
  /-- 已形成的同级别依次向上且波动区间互不重叠的中枢个数。 -/
  disjointUpCenters : Nat
  /-- 第一中枢后是否已出现第三类买点。 -/
  hasThirdBuyAfterFirst : Bool
  /-- 三买后的离开段是否为“非背驰类向上”。 -/
  nonDivergentUpward : Bool
  deriving Repr, DecidableEq

/-- B-22 中枢计数版上升趋势定义（`017:46`）：至少包含两个依次同向且互不重叠的同级别中枢。
引文：[017:46]「缠中说禅趋势：在任何级别的任何走势中，某完成的走势类型至少包含两个以上依次同向的缠中说禅走势中枢，就称为该级别的缠中说禅趋势。」 -/
def b22_upTrendByCenterCountLiteral (t : UpTrendCandidate) : Prop :=
  t.disjointUpCenters ≥ 2

/-- `b22_upTrendByCenterCountLiteral` 的可判定实例。 -/
instance instDecidableB22UpTrendByCenterCountLiteral (t : UpTrendCandidate) :
    Decidable (b22_upTrendByCenterCountLiteral t) :=
  inferInstanceAs (Decidable (t.disjointUpCenters ≥ 2))

/-- B-22 第 107 课字面上升趋势定义（`107:32`）：第一中枢后出现第三类买点并形成非背驰类向上（在第二个同级别中枢尚未形成前即宣告趋势形成）。
引文：[107:32]「有人喜欢精确定义，那么这里其实也给出了什么是上升趋势形成的最精确定义，就是在第一中枢后出现第三类买点并形成非背驰类向上。」 -/
def b22_upTrendByLesson107Literal (t : UpTrendCandidate) : Prop :=
  t.disjointUpCenters ≥ 1 ∧
  t.hasThirdBuyAfterFirst = true ∧
  t.nonDivergentUpward = true

/-- `b22_upTrendByLesson107Literal` 的可判定实例。 -/
instance instDecidableB22UpTrendByLesson107Literal (t : UpTrendCandidate) :
    Decidable (b22_upTrendByLesson107Literal t) :=
  inferInstanceAs (Decidable (
    t.disjointUpCenters ≥ 1 ∧
    t.hasThirdBuyAfterFirst = true ∧
    t.nonDivergentUpward = true))

/-- B-22 字面等价性断言：`017:46` 中枢计数版趋势定义与 `107:32`“第一中枢后三买+非背驰向上”定义等价。
所刻画确切命题：`107:32` 把动力学条件写入形态学趋势定义，在仅有 1 个同级别中枢时即可满足，与 `017:46` 至少两个同级别中枢的要求不等价。
引文：[017:46]「缠中说禅趋势：在任何级别的任何走势中，某完成的走势类型至少包含两个以上依次同向的缠中说禅走势中枢，就称为该级别的缠中说禅趋势。」
引文：[107:32]「有人喜欢精确定义，那么这里其实也给出了什么是上升趋势形成的最精确定义，就是在第一中枢后出现第三类买点并形成非背驰类向上。」 -/
def b22_twoTrendDefsEquivLiteral : Prop :=
  ∀ t : UpTrendCandidate,
    b22_upTrendByCenterCountLiteral t ↔ b22_upTrendByLesson107Literal t

/-! ### B-23：走势完成后必接更大级别中枢震荡的无前提字面断言 -/

/-- 已完成同级别走势类型的价格值域 `[lo, hi]`。
引文：[099:30]「由此可见，因为划分中的这种情况，我们就很明确地知道，走势的最大特点就是，连接中枢的走势级别一定小于中枢，换言之，一个走势级别完成后必然面临至少大一级别的中枢震荡。例如，一个5分钟的上涨结束后，必然至少要有一个30分钟的中枢震荡，这就是任何走势的必然结论，没有任何走势可以逃脱。」 -/
structure CompletedWaveBounds where
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

/-- 连续三段已完成同级别走势（上涨 `t1` 后接下跌 `t2` 再接上涨 `t3`）的首尾衔接合法性。
引文：[043:20]「例如，一个1分钟级别的顶背驰，就意味着必然导致一个至少1分钟级别的盘整或下跌走势类型，这就为背驰以后可能的走势以及级别给出了很明确的划定。」 -/
def b23_validThreeWaveContinuation (t1 t2 t3 : CompletedWaveBounds) : Prop :=
  t1.lo < t1.hi ∧
  t2.lo < t2.hi ∧
  t3.lo < t3.hi ∧
  t1.hi = t2.hi ∧
  t2.lo = t3.lo

/-- `b23_validThreeWaveContinuation` 的可判定实例。 -/
instance instDecidableB23ValidThreeWaveContinuation (t1 t2 t3 : CompletedWaveBounds) :
    Decidable (b23_validThreeWaveContinuation t1 t2 t3) :=
  inferInstanceAs (Decidable (
    t1.lo < t1.hi ∧
    t2.lo < t2.hi ∧
    t3.lo < t3.hi ∧
    t1.hi = t2.hi ∧
    t2.lo = t3.lo))

/-- 连续三段本级别走势类型存在公共重叠，从而构成高一级别中枢。
引文：[035:18]「上面就用最低级别的中枢把走势在最低级别上进行了完全分类，而三个连续的最低级别走势类型之间，如果发生重叠关系，也就是三个最低级别走势类型所分别经过的价格区间有交集，那么就形成了高一级别的缠中说禅中枢。」 -/
def b23_formsHigherLevelCenter (t1 t2 t3 : CompletedWaveBounds) : Prop :=
  waveMax3 t1.lo t2.lo t3.lo ≤ waveMin3 t1.hi t2.hi t3.hi

/-- `b23_formsHigherLevelCenter` 的可判定实例。 -/
instance instDecidableB23FormsHigherLevelCenter (t1 t2 t3 : CompletedWaveBounds) :
    Decidable (b23_formsHigherLevelCenter t1 t2 t3) :=
  inferInstanceAs (Decidable (
    waveMax3 t1.lo t2.lo t3.lo ≤ waveMin3 t1.hi t2.hi t3.hi))

/-- B-23 无前提字面断言（`099:30`）：一个同级别走势类型完成后，连同其后的两段交替同级别走势必然存在公共重叠以形成大一级别中枢震荡。
所刻画确切命题：`099:30` 无条件宣称“一个走势级别完成后必然面临至少大一级别的中枢震荡”；当 `t2` 远低于 `t1.lo` 且 `t3` 反弹未回到 `t1.lo` 时，三段无公共重叠，不形成大一级别中枢。
引文：[099:30]「由此可见，因为划分中的这种情况，我们就很明确地知道，走势的最大特点就是，连接中枢的走势级别一定小于中枢，换言之，一个走势级别完成后必然面临至少大一级别的中枢震荡。例如，一个5分钟的上涨结束后，必然至少要有一个30分钟的中枢震荡，这就是任何走势的必然结论，没有任何走势可以逃脱。」 -/
def b23_completionForcesHigherCenterLiteral : Prop :=
  ∀ t1 t2 t3 : CompletedWaveBounds,
    b23_validThreeWaveContinuation t1 t2 t3 →
    b23_formsHigherLevelCenter t1 t2 t3

end Chan.Audit.Literal
