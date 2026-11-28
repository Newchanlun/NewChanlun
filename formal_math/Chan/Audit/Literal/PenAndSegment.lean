module

/-!
# 缠论原典字面版定义：分型、笔与线段（B-6 / B-7 / B-36 / B-42）

本模块仅收载原典字面表述的形式化定义与可判定实例，供后续 `Chan/Audit/Math`
进行反例构造与逻辑核验；完全独立自包含，不导入任何主线模块或外部数学库，亦不包含定理证明。
-/

@[expose] public section

namespace Chan.Audit.Literal

/-- K 线或特征序列元素，记作闭区间 `[lo, hi]`。
引文：[062:28]「当然，实际图形里，有些复杂的关系会出现，就是相邻两K线可以出现如图6这种包含关系，也就是一K线的高低点全在另一K线的范围里，这种情况下，可以这样处理，在向上时，把两K线的最高点当高点，而两K线低点中的较高者当成低点，这样就把两K线合并成一新的K线；反之，当向下时，把两K线的最低点当低点，而两K线高点中的较低者当成高点，这样就把两K线合并成一新的K线。经过这样的处理，所有K线图都可以处理成没有包含关系的图形。」 -/
structure KBar where
  /-- 最低价。 -/
  lo : Int
  /-- 最高价。 -/
  hi : Int
  deriving Repr, DecidableEq

/-- 两根 K 线（或特征序列元素）之间存在包含关系（含等号）。
引文：[二级旁证 075:105]「只要有一端相同，那必然是包含，两端相同那更是了，所以如果不是包含关系的，都必然不需要考虑相等关系。」 -/
def kBarNested (a b : KBar) : Bool :=
  (decide (a.lo ≤ b.lo) && decide (b.hi ≤ a.hi)) ||
  (decide (b.lo ≤ a.lo) && decide (a.hi ≤ b.hi))

/-- 向上包含合并：高点取高、低点取高。
引文：[065:18]「当向上时，顺次n个包含关系的K线组，等价于[maxdi,maxgi]」 -/
def kBarMergeUp (a b : KBar) : KBar :=
  { lo := if a.lo ≤ b.lo then b.lo else a.lo
    hi := if a.hi ≤ b.hi then b.hi else a.hi }

/-- 顶分型谓词：第二根高点与低点均严格高于第一、三根。
引文：[062:22]「像图1这种，第二K线高点是相邻三K线高点中最高的，而低点也是相邻三K线低点中最高的，本ID给一个定义叫顶分型；图2这种叫底分型，第二K线低点是相邻三K线低点中最低的，而高点也是相邻三K线高点中最低的。」 -/
def isTopFractalBar (k1 k2 k3 : KBar) : Prop :=
  k1.hi < k2.hi ∧ k3.hi < k2.hi ∧ k1.lo < k2.lo ∧ k3.lo < k2.lo

/-- `isTopFractalBar` 的可判定实例。 -/
instance instDecidableIsTopFractalBar (k1 k2 k3 : KBar) :
    Decidable (isTopFractalBar k1 k2 k3) :=
  inferInstanceAs (Decidable (k1.hi < k2.hi ∧ k3.hi < k2.hi ∧ k1.lo < k2.lo ∧ k3.lo < k2.lo))

/-- 底分型谓词：第二根低点与高点均严格低于第一、三根。
引文：[062:22]「像图1这种，第二K线高点是相邻三K线高点中最高的，而低点也是相邻三K线低点中最高的，本ID给一个定义叫顶分型；图2这种叫底分型，第二K线低点是相邻三K线低点中最低的，而高点也是相邻三K线高点中最低的。」 -/
def isBottomFractalBar (k1 k2 k3 : KBar) : Prop :=
  k2.lo < k1.lo ∧ k2.lo < k3.lo ∧ k2.hi < k1.hi ∧ k2.hi < k3.hi

/-- `isBottomFractalBar` 的可判定实例。 -/
instance instDecidableIsBottomFractalBar (k1 k2 k3 : KBar) :
    Decidable (isBottomFractalBar k1 k2 k3) :=
  inferInstanceAs (Decidable (k2.lo < k1.lo ∧ k2.lo < k3.lo ∧ k2.hi < k1.hi ∧ k2.hi < k3.hi))

/-- 顶分型的布尔判定版本。
引文：[062:22]「像图1这种，第二K线高点是相邻三K线高点中最高的，而低点也是相邻三K线低点中最高的，本ID给一个定义叫顶分型；图2这种叫底分型，第二K线低点是相邻三K线低点中最低的，而高点也是相邻三K线高点中最低的。」 -/
def isTopFractalBool (k1 k2 k3 : KBar) : Bool :=
  decide (k1.hi < k2.hi) && decide (k3.hi < k2.hi) &&
  decide (k1.lo < k2.lo) && decide (k3.lo < k2.lo)

/-! ### B-6：忽略分界点禁包含的字面特征序列处理 -/

/-- 将新元素并入逆序累积栈，做顺序向上包含合并。
引文：[065:20]「而包含关系，不符合传递律，也就是说，第1、2根K线是包含关系，第2、3根也是包含关系，但并不意味着第1、3根就有包含关系。因此在K线包含关系的分析中，还要遵守顺序原则，就是先用第1、2根K线的包含关系确认新的K线，然后用新的K线去和第三根比，如果有包含关系，继续用包含关系的法则结合成新的K线，如果没有，就按正常K线去处理。」 -/
def b6_pushCharUp (acc : List KBar) (e : KBar) : List KBar :=
  match acc with
  | [] => [e]
  | last :: rest =>
    if kBarNested last e then kBarMergeUp last e :: rest else e :: last :: rest

/-- B-6 第 67 课字面特征序列处理：对整段特征序列统一做顺序包含处理，不区分假设分界点前后。
所刻画确切命题：`067:20` 字面规定“把每一元素看成是一 K 线，如同一般 K 线图中找分型的方法做非包含处理”，未禁止分界点前后两元素之间的包含合并。
引文：[067:20]「关于特征序列，把每一元素看成是一K线，那么，如同一般K线图中找分型的方法，也存在所谓的包含关系，也可以对此进行非包含处理。经过非包含处理的特征序列，成为标准特征序列。以后没有特别说明，特征序列都是指标准特征序列。」 -/
def b6_mergeCharSeqGlobalUpLiteral (xs : List KBar) : List KBar :=
  (xs.foldl b6_pushCharUp []).reverse

/-- B-6 第 71 课补丁特征序列处理：在假设转折点前后切分，分界点两侧元素禁止合并，两侧内部各自顺序包含处理。
所刻画确切命题：`071:42` 补充要求在第一种情况下“假设的转折点前后那两元素，是不存在包含关系的”。
引文：[071:42]「这里还要强调一下包含的问题，上面的分析知道，在这假设的转折点前后那两元素，是不存在包含关系的。因为，这两者已经被假设不是同一性质的东西，不一定是同一特征序列的；但假设的转折点后的顶分型的元素，是可以应用包含关系的。为什么？因此，这些元素间，肯定是同一性质的东西，或者就是原线段的延续，那么就同是原线段的特征序列中，或者就是新线段的非特征序列中，反正都是同一类的东西，同一类的东西，当然可以考察包含关系。」
引文：[078:54]「另外，一定要注意，对于第二种情况的第二特征序列的分型判断，必须严格按照包含关系的处理来，这里不存在第一种情况中的假设分界点两边不能进行包含关系处理的要求。为什么？因为在第一种情况中，如果分界点两边出现特征序列的包含关系，那证明对原线段转折的力度特别大，那当然不能用包含关系破坏这种力度的呈现。而在第二种情况的第二特征序列中，其方向是和原线段一致，包含关系的出现，就意味着原线段的能量充足，而第二种情况，本来就意味着对原线段转折的能量不足，这样一来，当然就必须按照包含关系来。」 -/
def b6_mergeCharSeqSplitUp (before after : List KBar) : List KBar :=
  b6_mergeCharSeqGlobalUpLiteral before ++ b6_mergeCharSeqGlobalUpLiteral after

/-- 判断给定元素序列中是否存在相邻三元素构成顶分型。
引文：[067:22]「注意，以向上笔开始的线段的特征序列，只考察顶分型；以向下笔开始的线段，只考察底分型。」 -/
def b6_containsTopFractal : List KBar → Bool
  | k1 :: k2 :: k3 :: rest =>
    isTopFractalBool k1 k2 k3 || b6_containsTopFractal (k2 :: k3 :: rest)
  | _ => false

/-- B-6 字面等价性断言：忽略分界点禁包含的全局包含处理与按 `071:42` 分界点切分处理总给出相同的顶分型判定。
所刻画确切命题：若第 67 课字面规则已闭合且无需第 71 课补丁，则对任意转折点前后特征序列 `(before, after)`，两种处理是否检出顶分型应当一致；实际中强转折向下笔包含前一特征元素时二者结论相反。
引文：[067:48]「上面两种情况，就给出所有线段划分的标准。显然，出现特征序列的分型，是线段结束的前提条件。本课，就是把前面“线段破坏的充要条件就是被另一个线段破坏”精确化了。因此，以后关于线段的划分，都以此精确的定义为基础。」
引文：[071:42]「这里还要强调一下包含的问题，上面的分析知道，在这假设的转折点前后那两元素，是不存在包含关系的。因为，这两者已经被假设不是同一性质的东西，不一定是同一特征序列的；但假设的转折点后的顶分型的元素，是可以应用包含关系的。为什么？因此，这些元素间，肯定是同一性质的东西，或者就是原线段的延续，那么就同是原线段的特征序列中，或者就是新线段的非特征序列中，反正都是同一类的东西，同一类的东西，当然可以考察包含关系。」 -/
def b6_ignoreBoundaryBanEquivLiteral : Prop :=
  ∀ before after : List KBar,
    b6_containsTopFractal (b6_mergeCharSeqGlobalUpLiteral (before ++ after)) =
    b6_containsTopFractal (b6_mergeCharSeqSplitUp before after)

/-! ### B-7 与 B-42：老笔/新笔参数字面对照与 `077:44` 不等号写反 -/

/-- 成笔候选跨度描述，用于对照老笔、新笔与第 106 课 6 根表述。
引文：[077:38]「有了上面这基础工作，那这个图就可以看成只有这些分型，分型之间的K线都可以暂时不用管。下面的工作，就是确定笔了。笔，必须是一顶一底，而且顶和底之间至少有一个K线不属于顶分型与底分型。当然，还有一个最显然的，就是在同一笔中，顶分型中最高那K线的区间至少要有一部分高于底分型中最低那K线的区间，如果这条都不满足，也就是顶都在低的范围内或顶比底还低，这显然是不可接受的。」 -/
structure PenSpanCandidate where
  /-- 顶分型最高 K 线是否满足高于底分型最低 K 线（顶高于底）。 -/
  topAboveBottom : Bool
  /-- 包含处理后顶分型与底分型是否不共用任何 K 线。 -/
  fractalsDisjoint : Bool
  /-- 包含处理后两分型之间（不含两分型各 3 根）的独立 K 线根数。 -/
  mergedIndependentBetween : Nat
  /-- 原始未包含处理 K 线中，顶分型最高 K 线与底分型最低 K 线之间（不含该两根）的 K 线根数。 -/
  rawBetweenExtrema : Nat
  /-- 原始 K 线总延伸单位数（含首尾）。 -/
  rawTotalBars : Nat
  deriving Repr, DecidableEq

/-- B-7 老笔字面成立条件：顶高于底、两分型不共用 K 线，且包含处理后顶底分型之间至少有 1 根独立 K 线。
引文：[062:26]「在实际分析中，都必须要求顶和底之间都至少有一K线当成一笔的最基本要求。」
引文：[077:38]「有了上面这基础工作，那这个图就可以看成只有这些分型，分型之间的K线都可以暂时不用管。下面的工作，就是确定笔了。笔，必须是一顶一底，而且顶和底之间至少有一个K线不属于顶分型与底分型。当然，还有一个最显然的，就是在同一笔中，顶分型中最高那K线的区间至少要有一部分高于底分型中最低那K线的区间，如果这条都不满足，也就是顶都在低的范围内或顶比底还低，这显然是不可接受的。」 -/
def b7_oldPenLiteral (c : PenSpanCandidate) : Prop :=
  c.topAboveBottom = true ∧
  c.fractalsDisjoint = true ∧
  c.mergedIndependentBetween ≥ 1

/-- `b7_oldPenLiteral` 的可判定实例。 -/
instance instDecidableB7OldPenLiteral (c : PenSpanCandidate) :
    Decidable (b7_oldPenLiteral c) :=
  inferInstanceAs (Decidable (
    c.topAboveBottom = true ∧
    c.fractalsDisjoint = true ∧
    c.mergedIndependentBetween ≥ 1))

/-- B-7 新笔字面成立条件：顶高于底、包含处理后两分型不共用 K 线，且顶底极值 K 线之间原始 K 线至少有 3 根。
引文：[二级旁证 081:110]「本ID想了想，计算了一下能量力度，觉得以后可以把笔的成立条件略微放松一下，就是一笔必须满足以下两个条件：1、顶分型与底分型经过包含处理后，不允许共用K线，也就是不能有一K线分别属于顶分型与底分型，这条件和原来是一样的，这一点绝对不能放松，因为这样，才能保证足够的能量力度；2、在满足1的前提下，顶分型中最高K线和底分型的最低K线之间（不包括这两K线），不考虑包含关系，至少有3根（包括3根）以上K线。」 -/
def b7_newPenLiteral (c : PenSpanCandidate) : Prop :=
  c.topAboveBottom = true ∧
  c.fractalsDisjoint = true ∧
  c.rawBetweenExtrema ≥ 3

/-- `b7_newPenLiteral` 的可判定实例。 -/
instance instDecidableB7NewPenLiteral (c : PenSpanCandidate) :
    Decidable (b7_newPenLiteral c) :=
  inferInstanceAs (Decidable (
    c.topAboveBottom = true ∧
    c.fractalsDisjoint = true ∧
    c.rawBetweenExtrema ≥ 3))

/-- B-7 第 106 课 6 根 K 线表述字面条件。
引文：[106:16]「任一级别，都有最少的延伸时间，例如，一笔，由于必须有顶与底的分型，因此，必须至少延伸6个基本K线单位，也就是说，如果5日线都不能碰到，那就不会是笔的反弹了。」 -/
def b7_lesson106PenLiteral (c : PenSpanCandidate) : Prop :=
  c.topAboveBottom = true ∧
  c.fractalsDisjoint = true ∧
  c.rawTotalBars ≥ 6

/-- `b7_lesson106PenLiteral` 的可判定实例。 -/
instance instDecidableB7Lesson106PenLiteral (c : PenSpanCandidate) :
    Decidable (b7_lesson106PenLiteral c) :=
  inferInstanceAs (Decidable (
    c.topAboveBottom = true ∧
    c.fractalsDisjoint = true ∧
    c.rawTotalBars ≥ 6))

/-- B-7 老笔与新笔字面等价断言：在同一套 K 线跨度上，老笔与新笔判定总一致。
所刻画确切命题：答疑 `081:160` 称“稍微改改，又不影响最终的判断”；实际在包含后不共用且中间无独立 K 线、但原始极值间恰有 3 根 K 线时，新笔成笔而老笔不成笔。
引文：[二级旁证 081:160]「本ID自己一直用老标准，因为本ID从来只用一套软件。但这理论公开，就有一个适应性的问题，毕竟不能要求所有人只用一套软件，所以稍微改改，又不影响最终的判断，又何妨？」 -/
def b7_oldNewPenEquivLiteral : Prop :=
  ∀ c : PenSpanCandidate, b7_oldPenLiteral c ↔ b7_newPenLiteral c

/-- B-7 / B-42 笔唯一性证明第一情形（`077:42`）：前面的底高于后面的底（`d1 > d2`）。
引文：[077:42]「如果前面的底高于后面的底，那么前面的划分显然是错误的，因为按这种划分，该笔是没有完成的，一个底不经过一个顶后就有一个更低的底，这是最典型的笔没完成的情况。」 -/
def b42_penProofCase1Literal (d1 d2 : Int) : Prop :=
  d1 > d2

/-- `b42_penProofCase1Literal` 的可判定实例。 -/
instance instDecidableB42PenProofCase1Literal (d1 d2 : Int) :
    Decidable (b42_penProofCase1Literal d1 d2) :=
  inferInstanceAs (Decidable (d1 > d2))

/-- B-7 / B-42 笔唯一性证明第二情形字面条件（`077:44` 不等号写反）：前面的底“不低于”后面的底（`d1 ≥ d2`）。
所刻画确切命题：`077:44` 字面写作“如果前面的底不低于后面的底”，与 `077:42`“前面的底高于后面的底”在 `d1 > d2` 重叠，并完全遗漏 `d1 < d2`（应写作“不高于”）。
引文：[077:44]「如果前面的底不低于后面的底，那么如果再下面一个顶分型出现前，如果有一个底分型低于前面的底，那么，这两种划分都是不正确的，所划分的笔都是没完成的；」 -/
def b42_penProofCase2Literal (d1 d2 : Int) : Prop :=
  d1 ≥ d2

/-- `b42_penProofCase2Literal` 的可判定实例。 -/
instance instDecidableB42PenProofCase2Literal (d1 d2 : Int) :
    Decidable (b42_penProofCase2Literal d1 d2) :=
  inferInstanceAs (Decidable (d1 ≥ d2))

/-- B-7 / B-42 笔唯一性证明分情况讨论合法性字面断言：`077:42` 与 `077:44` 构成对任意 `(d1, d2)` 的互斥且穷尽划分。
所刻画确切命题：该分情况讨论在 `d1 > d2` 处违背互斥性，在 `d1 < d2` 处违背穷尽性。
引文：[077:42]「如果前面的底高于后面的底，那么前面的划分显然是错误的，因为按这种划分，该笔是没有完成的，一个底不经过一个顶后就有一个更低的底，这是最典型的笔没完成的情况。」
引文：[077:44]「如果前面的底不低于后面的底，那么如果再下面一个顶分型出现前，如果有一个底分型低于前面的底，那么，这两种划分都是不正确的，所划分的笔都是没完成的；」 -/
def b42_penProofCasesPartitionLiteral : Prop :=
  ∀ d1 d2 : Int,
    (b42_penProofCase1Literal d1 d2 ∨ b42_penProofCase2Literal d1 d2) ∧
    ¬ (b42_penProofCase1Literal d1 d2 ∧ b42_penProofCase2Literal d1 d2)

/-! ### B-36：把分型边沿跌破/站稳当成成笔充分条件的字面断言 -/

/-- 底分型区间的上边沿（三根构成 K 线的最高点）。
引文：[108:18]「站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。」 -/
def b36_bottomFractalUpperEdge (k1 k2 k3 : KBar) : Int :=
  let m12 := if k1.hi ≤ k2.hi then k2.hi else k1.hi
  if m12 ≤ k3.hi then k3.hi else m12

/-- 确认站稳底分型区间上边沿的字面条件：`k1, k2, k3` 构成底分型，且紧随的第 4 根 K 线 `k4` 整体站上该分型上边沿（`k4.lo > upperEdge`）。
引文：[108:18]「站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。」 -/
def b36_standsAboveBottomEdge (k1 k2 k3 k4 : KBar) : Prop :=
  isBottomFractalBar k1 k2 k3 ∧
  k4.lo ≤ k4.hi ∧
  k4.lo > b36_bottomFractalUpperEdge k1 k2 k3

/-- `b36_standsAboveBottomEdge` 的可判定实例。 -/
instance instDecidableB36StandsAboveBottomEdge (k1 k2 k3 k4 : KBar) :
    Decidable (b36_standsAboveBottomEdge k1 k2 k3 k4) :=
  inferInstanceAs (Decidable (
    isBottomFractalBar k1 k2 k3 ∧
    k4.lo ≤ k4.hi ∧
    k4.lo > b36_bottomFractalUpperEdge k1 k2 k3))

/-- 判断底分型之后的非包含 K 线序列中是否出现不与该底分型共用 K 线的顶分型（从而满足成笔的最低分型结构要求）。
引文：[062:26]「但这里有一个细微的地方要分清楚，因为结合律是必须遵守的，像图3这种，顶和底之间必须共用一个K线，这就违反结合律了，所以这不算一笔，而图4，就光是顶和底了，中间没有其他K线，一般来说，也最好不算一笔，而图5，是一笔的最基本的图形，顶和底之间还有一根K线。」 -/
def b36_hasDisjointTopFractal (afterBottom : List KBar) : Prop :=
  b6_containsTopFractal afterBottom = true

/-- `b36_hasDisjointTopFractal` 的可判定实例。 -/
instance instDecidableB36HasDisjointTopFractal (afterBottom : List KBar) :
    Decidable (b36_hasDisjointTopFractal afterBottom) :=
  inferInstanceAs (Decidable (b6_containsTopFractal afterBottom = true))

/-- B-36 字面充分条件断言一（`108:18`）：只要底分型后第 4 根站稳底分型上边沿（且后续 K 线序列足够长，至少再延续 3 根非包含 K 线），就必然在后续形成与底分型不共用的顶分型从而展开至少一笔向上行情。
所刻画确切命题：`108:18` 将站稳底分型上边沿表述为“至少展开一笔向上行情”的充分条件；实际中第 4 根冲高后若直接连续下跌破底，则第 4 根仅与底分型共用第 3 根，后续不形成任何不共用的顶分型，无法构成一笔。
引文：[108:18]「站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。」
引文：[二级旁证 104:282]「今天低开后，在60分钟刚好跌破顶分型的下边，早上那标准的回抽，极端显然地上不了3613点，因此确认这对顶分型下边的跌破是有效的，因此后面的下跌就顺理成章了，为什么？因为向下要形成笔。」 -/
def b36_bottomEdgeStandSufficientForPenLiteral : Prop :=
  ∀ (k1 k2 k3 k4 : KBar) (rest : List KBar),
    b36_standsAboveBottomEdge k1 k2 k3 k4 →
    rest.length ≥ 3 →
    b36_hasDisjointTopFractal (k4 :: rest)

/-- 判断顶分型之后的非包含 K 线序列中是否从未出现高于该顶分型高点的 K 线。
引文：[080:28]「一、所有的顶点都必然是顶分型。」 -/
def b36_noHigherHighAfter (topHi : Int) : List KBar → Bool
  | [] => true
  | k :: rest => decide (k.hi ≤ topHi) && b36_noHigherHighAfter topHi rest

/-- B-36 字面充分条件断言二（`080:30`）：由“所有顶点必是顶分型”倒推，一旦出现顶分型则该顶分型必然构成局部顶点（后续不会立即创新高成为中继顶分型）。
所刻画确切命题：`080:28` 给出必要条件（顶点 ⇒ 顶分型），`080:30` 直接宣称“从这可以严格推导出……一旦出现顶分型，离开就是唯一的选择”，把必要条件当成充分条件。
引文：[080:28]「一、所有的顶点都必然是顶分型。」
引文：[080:30]「从这可以严格推导出什么？就是一旦出现顶分型，离开就是唯一的选择。」 -/
def b36_topFractalSufficientForPeakLiteral : Prop :=
  ∀ (k1 k2 k3 : KBar) (after : List KBar),
    isTopFractalBar k1 k2 k3 →
    after.length ≥ 1 →
    b36_noHigherHighAfter k2.hi after = true

end Chan.Audit.Literal
