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

/-- 带真实原始 K 线极值下标与原始覆盖区间的合并 K 线结构：用于精确追踪每根合并 K 线的高低点真实原始下标 `(loRawIdx, hiRawIdx)` 及所涵盖原始下标区间 `[rawStart, rawEnd]`，杜绝冒用同价其他原始 K 线下标。
引文：[二级旁证] [081:110]「本ID想了想，计算了一下能量力度，觉得以后可以把笔的成立条件略微放松一下，就是一笔必须满足以下两个条件：1、顶分型与底分型经过包含处理后，不允许共用K线，也就是不能有一K线分别属于顶分型与底分型，这条件和原来是一样的，这一点绝对不能放松，因为这样，才能保证足够的能量力度；2、在满足1的前提下，顶分型中最高K线和底分型的最低K线之间（不包括这两K线），不考虑包含关系，至少有3根（包括3根）以上K线。」 -/
structure TrackedKBar where
  /-- 合并后最低价。 -/
  lo : Int
  /-- 合并后最高价。 -/
  hi : Int
  /-- 贡献当前最低价的真实原始 K 线下标。 -/
  loRawIdx : Nat
  /-- 贡献当前最高价的真实原始 K 线下标。 -/
  hiRawIdx : Nat
  /-- 本合并 K 线覆盖的原始 K 线起始下标。 -/
  rawStart : Nat
  /-- 本合并 K 线覆盖的原始 K 线结束下标。 -/
  rawEnd : Nat
  deriving Repr, DecidableEq

/-- 单根 K 线区间合法性：`lo ≤ hi`。
引文：[062:28]「当然，实际图形里，有些复杂的关系会出现，就是相邻两K线可以出现如图6这种包含关系，也就是一K线的高低点全在另一K线的范围里，这种情况下，可以这样处理，在向上时，把两K线的最高点当高点，而两K线低点中的较高者当成低点，这样就把两K线合并成一新的K线；反之，当向下时，把两K线的最低点当低点，而两K线高点中的较低者当成高点，这样就把两K线合并成一新的K线。经过这样的处理，所有K线图都可以处理成没有包含关系的图形。」 -/
def kBarValidBool (k : KBar) : Bool :=
  decide (k.lo ≤ k.hi)

/-- 两根 K 线（或特征序列元素）之间存在包含关系（含等号）。
引文：[二级旁证] [075:105]「只要有一端相同，那必然是包含，两端相同那更是了，所以如果不是包含关系的，都必然不需要考虑相等关系。」 -/
def kBarNested (a b : KBar) : Bool :=
  (decide (a.lo ≤ b.lo) && decide (b.hi ≤ a.hi)) ||
  (decide (b.lo ≤ a.lo) && decide (a.hi ≤ b.hi))

/-- 向上包含合并：高点取高、低点取高。
引文：[065:18]「当向上时，顺次n个包含关系的K线组，等价于[maxdi,maxgi]」 -/
def kBarMergeUp (a b : KBar) : KBar :=
  { lo := if a.lo ≤ b.lo then b.lo else a.lo
    hi := if a.hi ≤ b.hi then b.hi else a.hi }

/-- 向下包含合并：低点取低、高点取低。
引文：[065:18]「向下时，顺次n个包含关系的K线组，等价于[mindi,mingi]」 -/
def kBarMergeDown (a b : KBar) : KBar :=
  { lo := if a.lo ≤ b.lo then a.lo else b.lo
    hi := if a.hi ≤ b.hi then a.hi else b.hi }

/-- 方向正确的单步顺序包含合并：当栈中已有两根非包含前驱 `(prev, last)` 时，按 `065:24` 由 `prev` 到 `last` 的局部方向决定向上或向下合并；仅有一根前驱时采用显式初始方向 `initUp`。
引文：[065:24]「假设，第n根K线满足第n根与第n+1根的包含关系，而第n根与第n-1根不是包含关系，那么如果gn>=gn-1，那么称第n-1、n、n+1根K线是向上的；如果dn<=dn-1，那么称第n-1、n、n+1根K线是向下的。」 -/
def pushBarDirectional (initUp : Bool) (acc : List KBar) (e : KBar) : List KBar :=
  match acc with
  | [] => [e]
  | [last] =>
    if kBarNested last e then
      [if initUp then kBarMergeUp last e else kBarMergeDown last e]
    else
      [e, last]
  | last :: prev :: rest =>
    if kBarNested last e then
      let merged :=
        if prev.hi < last.hi then kBarMergeUp last e else kBarMergeDown last e
      merged :: prev :: rest
    else
      e :: last :: prev :: rest

/-- 对整段 K 线或特征序列执行方向正确的顺序非包含处理。
引文：[065:20]「而包含关系，不符合传递律，也就是说，第1、2根K线是包含关系，第2、3根也是包含关系，但并不意味着第1、3根就有包含关系。因此在K线包含关系的分析中，还要遵守顺序原则，就是先用第1、2根K线的包含关系确认新的K线，然后用新的K线去和第三根比，如果有包含关系，继续用包含关系的法则结合成新的K线，如果没有，就按正常K线去处理。」 -/
def mergeBarsDirectional (initUp : Bool) (xs : List KBar) : List KBar :=
  (xs.foldl (pushBarDirectional initUp) []).reverse

/-- 从起始下标 `idx` 顺序为原始 K 线打上真实原始下标与区间。
引文：[065:20]「而包含关系，不符合传递律，也就是说，第1、2根K线是包含关系，第2、3根也是包含关系，但并不意味着第1、3根就有包含关系。因此在K线包含关系的分析中，还要遵守顺序原则，就是先用第1、2根K线的包含关系确认新的K线，然后用新的K线去和第三根比，如果有包含关系，继续用包含关系的法则结合成新的K线，如果没有，就按正常K线去处理。」 -/
def indexRawBarsFrom (idx : Nat) : List KBar → List TrackedKBar
  | [] => []
  | k :: rest =>
    { lo := k.lo
      hi := k.hi
      loRawIdx := idx
      hiRawIdx := idx
      rawStart := idx
      rawEnd := idx } :: indexRawBarsFrom (idx + 1) rest

/-- 两根带下标追踪 K 线的包含判定（含等号）。
引文：[二级旁证] [075:105]「只要有一端相同，那必然是包含，两端相同那更是了，所以如果不是包含关系的，都必然不需要考虑相等关系。」 -/
def trackedNested (a b : TrackedKBar) : Bool :=
  (decide (a.lo ≤ b.lo) && decide (b.hi ≤ a.hi)) ||
  (decide (b.lo ≤ a.lo) && decide (a.hi ≤ b.hi))

/-- 带真实原始极值下标的向上包含合并（高点取高、低点取高，并保留对应极值的真实原始下标及合并覆盖区间 `[a.rawStart, b.rawEnd]`）。
引文：[065:18]「当向上时，顺次n个包含关系的K线组，等价于[maxdi,maxgi]」 -/
def trackedMergeUp (a b : TrackedKBar) : TrackedKBar :=
  let (loVal, loIdx) := if a.lo < b.lo then (b.lo, b.loRawIdx) else (a.lo, a.loRawIdx)
  let (hiVal, hiIdx) := if a.hi < b.hi then (b.hi, b.hiRawIdx) else (a.hi, a.hiRawIdx)
  { lo := loVal
    hi := hiVal
    loRawIdx := loIdx
    hiRawIdx := hiIdx
    rawStart := a.rawStart
    rawEnd := b.rawEnd }

/-- 带真实原始极值下标的向下包含合并（低点取低、高点取低，并保留对应极值的真实原始下标及合并覆盖区间 `[a.rawStart, b.rawEnd]`）。
引文：[065:18]「向下时，顺次n个包含关系的K线组，等价于[mindi,mingi]」 -/
def trackedMergeDown (a b : TrackedKBar) : TrackedKBar :=
  let (loVal, loIdx) := if b.lo < a.lo then (b.lo, b.loRawIdx) else (a.lo, a.loRawIdx)
  let (hiVal, hiIdx) := if b.hi < a.hi then (b.hi, b.hiRawIdx) else (a.hi, a.hiRawIdx)
  { lo := loVal
    hi := hiVal
    loRawIdx := loIdx
    hiRawIdx := hiIdx
    rawStart := a.rawStart
    rawEnd := b.rawEnd }

/-- 带真实原始极值下标追踪的单步方向正确顺序包含合并。
引文：[065:24]「假设，第n根K线满足第n根与第n+1根的包含关系，而第n根与第n-1根不是包含关系，那么如果gn>=gn-1，那么称第n-1、n、n+1根K线是向上的；如果dn<=dn-1，那么称第n-1、n、n+1根K线是向下的。」 -/
def pushTrackedDirectional (initUp : Bool) (acc : List TrackedKBar) (e : TrackedKBar) :
    List TrackedKBar :=
  match acc with
  | [] => [e]
  | [last] =>
    if trackedNested last e then
      [if initUp then trackedMergeUp last e else trackedMergeDown last e]
    else
      [e, last]
  | last :: prev :: rest =>
    if trackedNested last e then
      let merged :=
        if prev.hi < last.hi then trackedMergeUp last e else trackedMergeDown last e
      merged :: prev :: rest
    else
      e :: last :: prev :: rest

/-- 对原始 K 线序列（从指定原始下标 `startIdx` 起）执行带原始极值下标追踪的方向正确顺序包含合并。
引文：[065:20]「而包含关系，不符合传递律，也就是说，第1、2根K线是包含关系，第2、3根也是包含关系，但并不意味着第1、3根就有包含关系。因此在K线包含关系的分析中，还要遵守顺序原则，就是先用第1、2根K线的包含关系确认新的K线，然后用新的K线去和第三根比，如果有包含关系，继续用包含关系的法则结合成新的K线，如果没有，就按正常K线去处理。」 -/
def mergeTrackedDirectionalFrom (initUp : Bool) (startIdx : Nat) (xs : List KBar) :
    List TrackedKBar :=
  ((indexRawBarsFrom startIdx xs).foldl (pushTrackedDirectional initUp) []).reverse

/-- 从原始下标 `0` 起执行带追踪的方向正确顺序包含合并。
引文：[065:20]「而包含关系，不符合传递律，也就是说，第1、2根K线是包含关系，第2、3根也是包含关系，但并不意味着第1、3根就有包含关系。因此在K线包含关系的分析中，还要遵守顺序原则，就是先用第1、2根K线的包含关系确认新的K线，然后用新的K线去和第三根比，如果有包含关系，继续用包含关系的法则结合成新的K线，如果没有，就按正常K线去处理。」 -/
def mergeTrackedDirectional (initUp : Bool) (xs : List KBar) : List TrackedKBar :=
  mergeTrackedDirectionalFrom initUp 0 xs

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

/-- 底分型的布尔判定版本。
引文：[062:22]「像图1这种，第二K线高点是相邻三K线高点中最高的，而低点也是相邻三K线低点中最高的，本ID给一个定义叫顶分型；图2这种叫底分型，第二K线低点是相邻三K线低点中最低的，而高点也是相邻三K线高点中最低的。」 -/
def isBottomFractalBool (k1 k2 k3 : KBar) : Bool :=
  decide (k2.lo < k1.lo) && decide (k2.lo < k3.lo) &&
  decide (k2.hi < k1.hi) && decide (k2.hi < k3.hi)

/-- 安全读取带追踪合并 K 线列表中下标 `idx` 处的元素。
引文：[062:22]「像图1这种，第二K线高点是相邻三K线高点中最高的，而低点也是相邻三K线低点中最高的，本ID给一个定义叫顶分型；图2这种叫底分型，第二K线低点是相邻三K线低点中最低的，而高点也是相邻三K线高点中最低的。」 -/
def nthTrackedOpt : List TrackedKBar → Nat → Option TrackedKBar
  | [], _ => none
  | x :: _, 0 => some x
  | _ :: xs, n + 1 => nthTrackedOpt xs n

/-- 检查列表中每根 K 线均满足 `lo ≤ hi`。
引文：[062:28]「当然，实际图形里，有些复杂的关系会出现，就是相邻两K线可以出现如图6这种包含关系，也就是一K线的高低点全在另一K线的范围里，这种情况下，可以这样处理，在向上时，把两K线的最高点当高点，而两K线低点中的较高者当成低点，这样就把两K线合并成一新的K线；反之，当向下时，把两K线的最低点当低点，而两K线高点中的较低者当成高点，这样就把两K线合并成一新的K线。经过这样的处理，所有K线图都可以处理成没有包含关系的图形。」 -/
def allBarsValid : List KBar → Bool
  | [] => true
  | k :: rest => kBarValidBool k && allBarsValid rest

/-- 检查列表中任意相邻两元素均不存在包含关系。
引文：[065:20]「而包含关系，不符合传递律，也就是说，第1、2根K线是包含关系，第2、3根也是包含关系，但并不意味着第1、3根就有包含关系。因此在K线包含关系的分析中，还要遵守顺序原则，就是先用第1、2根K线的包含关系确认新的K线，然后用新的K线去和第三根比，如果有包含关系，继续用包含关系的法则结合成新的K线，如果没有，就按正常K线去处理。」 -/
def noAdjacentNested : List KBar → Bool
  | [] => true
  | [_] => true
  | a :: b :: rest => (!kBarNested a b) && noAdjacentNested (b :: rest)

/-! ### B-6：方向正确的特征序列包含处理与指定候选分界点位置判定对比（区分 `067:20` 同特征序列规则与 `071:18,40,42` 跨界待定规则） -/

/-- 判断给定元素序列中是否存在相邻三元素构成顶分型（供 B-36 检查闭合观察窗口内是否出现不共用顶分型使用）。
引文：[067:22]「注意，以向上笔开始的线段的特征序列，只考察顶分型；以向下笔开始的线段，只考察底分型。」 -/
def b6_containsTopFractal : List KBar → Bool
  | k1 :: k2 :: k3 :: rest =>
    isTopFractalBool k1 k2 k3 || b6_containsTopFractal (k2 :: k3 :: rest)
  | _ => false

/-- 在带追踪合并序列中定位涵盖原始下标 `targetRawIdx` 的唯一合并元素位置。
引文：[071:40]「特征序列的分型中，第一元素就是以该假设转折点前线段的最后一个特征元素，第二个元素，就是从这转折点开始的第一笔，显然，这两者之间是同方向的，因此，如果这两者之间有缺口，那么就是第二种情况，否则就是第一种，然后根据定义来考察就可以。」 -/
def b6_findIdxContainingRaw (targetRawIdx curIdx : Nat) : List TrackedKBar → Option Nat
  | [] => none
  | k :: rest =>
    if decide (k.rawStart ≤ targetRawIdx) && decide (targetRawIdx ≤ k.rawEnd) then
      some curIdx
    else
      b6_findIdxContainingRaw targetRawIdx (curIdx + 1) rest

/-- 严格判定带追踪合并序列中**涵盖指定原始候选分界元素 `targetRawIdx` 的那一位置**是否恰为顶分型中心（绝不扫描序列其余无关位置）。
引文：[071:40]「特征序列的分型中，第一元素就是以该假设转折点前线段的最后一个特征元素，第二个元素，就是从这转折点开始的第一笔，显然，这两者之间是同方向的，因此，如果这两者之间有缺口，那么就是第二种情况，否则就是第一种，然后根据定义来考察就可以。」 -/
def b6_hasTopFractalAtRaw (merged : List TrackedKBar) (targetRawIdx : Nat) : Bool :=
  match b6_findIdxContainingRaw targetRawIdx 0 merged with
  | none => false
  | some 0 => false
  | some (c + 1) =>
    match nthTrackedOpt merged c, nthTrackedOpt merged (c + 1), nthTrackedOpt merged (c + 2) with
    | some k1, some k2, some k3 =>
      isTopFractalBool { lo := k1.lo, hi := k1.hi } { lo := k2.lo, hi := k2.hi } { lo := k3.lo, hi := k3.hi }
    | _, _, _ => false

/-- B-6 跨界全局包含处理（忽略 `071:18,42` 跨界待定前提，将 `067:20` 同特征序列非包含处理直接跨过转折点应用）。
引文：[067:20]「关于特征序列，把每一元素看成是一K线，那么，如同一般K线图中找分型的方法，也存在所谓的包含关系，也可以对此进行非包含处理。经过非包含处理的特征序列，成为标准特征序列。以后没有特别说明，特征序列都是指标准特征序列。」 -/
def b6_mergeCharSeqGlobalLiteral (before after : List KBar) : List TrackedKBar :=
  mergeTrackedDirectional true (before ++ after)

/-- B-6 分界点禁包含处理（遵循 `071:18,42`：两侧各自使用同一方向正确的 `mergeTrackedDirectionalFrom`，但禁止假设转折点前后两元素跨界包含合并）。
引文：[071:18]「注意，特征序列的元素包含关系，首先的前提是这元素都在一特征序列里，如果两个不同的特征序列之间的元素，讨论包含关系是没意义的。」
引文：[071:42]「这里还要强调一下包含的问题，上面的分析知道，在这假设的转折点前后那两元素，是不存在包含关系的。因为，这两者已经被假设不是同一性质的东西，不一定是同一特征序列的；但假设的转折点后的顶分型的元素，是可以应用包含关系的。为什么？因此，这些元素间，肯定是同一性质的东西，或者就是原线段的延续，那么就同是原线段的特征序列中，或者就是新线段的非特征序列中，反正都是同一类的东西，同一类的东西，当然可以考察包含关系。」 -/
def b6_mergeCharSeqSplitAtBoundary (before after : List KBar) : List TrackedKBar :=
  mergeTrackedDirectionalFrom true 0 before ++
  mergeTrackedDirectionalFrom false before.length after

/-- B-6 合法的第一种情况候选分界点前提（向上线段转折点）：
1. `before` 与 `after` 均有效且各自内部已非包含（确保有无跨界合并成为唯一差异）；
2. `before` 末端 `e1` 之前存在严格更低前驱 `e0`（确立原线段向上局部方向），`after` 首元素 `e2`（原始下标 `before.length`）之后存在更低后继 `e3`；
3. `e1` 与 `e2` 之间不存在特征序列缺口（即 `067:28`/`071:40` 的第一种情况），且 `e2` 达到新高（`e1.hi < e2.hi`）。
引文：[067:28]「特征序列的顶分型中，第一和第二元素间不存在特征序列的缺口，那么该线段在该顶分型的高点处结束，该高点是该线段的终点；特征序列的底分型中，第一和第二元素间不存在特征序列的缺口，那么该线段在该底分型的低点处结束，该低点是该线段的终点；」
引文：[071:40]「特征序列的分型中，第一元素就是以该假设转折点前线段的最后一个特征元素，第二个元素，就是从这转折点开始的第一笔，显然，这两者之间是同方向的，因此，如果这两者之间有缺口，那么就是第二种情况，否则就是第一种，然后根据定义来考察就可以。」 -/
def b6_validCase1Boundary (before after : List KBar) : Prop :=
  allBarsValid before = true ∧
  allBarsValid after = true ∧
  noAdjacentNested before = true ∧
  noAdjacentNested after = true ∧
  match before.reverse, after with
  | e1 :: e0 :: _, e2 :: e3 :: _ =>
    e0.hi < e1.hi ∧
    e1.lo ≤ e2.hi ∧
    e2.lo ≤ e1.hi ∧
    e1.hi < e2.hi ∧
    e3.hi < e2.hi
  | _, _ => False

/-- `b6_validCase1Boundary` 的可判定布尔版本。
引文：[071:40]「特征序列的分型中，第一元素就是以该假设转折点前线段的最后一个特征元素，第二个元素，就是从这转折点开始的第一笔，显然，这两者之间是同方向的，因此，如果这两者之间有缺口，那么就是第二种情况，否则就是第一种，然后根据定义来考察就可以。」 -/
def b6_validCase1BoundaryBool (before after : List KBar) : Bool :=
  allBarsValid before &&
  allBarsValid after &&
  noAdjacentNested before &&
  noAdjacentNested after &&
  match before.reverse, after with
  | e1 :: e0 :: _, e2 :: e3 :: _ =>
    decide (e0.hi < e1.hi) &&
    decide (e1.lo ≤ e2.hi) &&
    decide (e2.lo ≤ e1.hi) &&
    decide (e1.hi < e2.hi) &&
    decide (e3.hi < e2.hi)
  | _, _ => false

/-- B-6 指定候选分界点算法等价性检验命题：在合法的第一种情况候选分界点 `before.length` 处，忽略 `071:18,42` 跨界待定规则而做全局合并与遵守分界点禁包含处理，在**该指定候选分界点位置**上的顶分型判定恒相等。
所刻画确切命题：`067:20` 规定同一特征序列内做包含处理，`071:18,40,42` 补充转折点前后两元素因待定而不属同一特征序列故禁跨界合并；此处严格比较指定候选分界点 `before.length` 处的顶分型结果以刻画是否执行跨界禁令带来的实质操作差异，不将 `067:20` 与 `071:42` 误写为两课直接矛盾。
引文：[067:20]「关于特征序列，把每一元素看成是一K线，那么，如同一般K线图中找分型的方法，也存在所谓的包含关系，也可以对此进行非包含处理。经过非包含处理的特征序列，成为标准特征序列。以后没有特别说明，特征序列都是指标准特征序列。」
引文：[071:18]「注意，特征序列的元素包含关系，首先的前提是这元素都在一特征序列里，如果两个不同的特征序列之间的元素，讨论包含关系是没意义的。」
引文：[071:42]「这里还要强调一下包含的问题，上面的分析知道，在这假设的转折点前后那两元素，是不存在包含关系的。因为，这两者已经被假设不是同一性质的东西，不一定是同一特征序列的；但假设的转折点后的顶分型的元素，是可以应用包含关系的。为什么？因此，这些元素间，肯定是同一性质的东西，或者就是原线段的延续，那么就同是原线段的特征序列中，或者就是新线段的非特征序列中，反正都是同一类的东西，同一类的东西，当然可以考察包含关系。」 -/
def b6_case1IgnoreBoundaryBanEquivLiteral : Prop :=
  ∀ before after : List KBar,
    b6_validCase1BoundaryBool before after = true →
    b6_hasTopFractalAtRaw (b6_mergeCharSeqGlobalLiteral before after) before.length =
    b6_hasTopFractalAtRaw (b6_mergeCharSeqSplitAtBoundary before after) before.length

/-! ### B-7 与 B-42：带真实原始极值下标追踪的老笔/新笔规则分离，与 `077:44` 不等号写反 -/

/-- 基于带原始下标追踪合并序列 `mergeTrackedDirectional true raw` 的一笔候选合法结构前提（不再接受任何外部自由下标，彻底杜绝冒用同价其他原始 K 线下标）：
`raw` 全部合法，包含合并后总根数 `m ≥ 6`，首三根构成底分型（中心 `b1`）、末三根构成顶分型（中心 `t1`），且按 `077:38` 满足 `b1.hi < t1.hi` 及 `b1.loRawIdx < t1.hiRawIdx`。
引文：[077:38]「有了上面这基础工作，那这个图就可以看成只有这些分型，分型之间的K线都可以暂时不用管。下面的工作，就是确定笔了。笔，必须是一顶一底，而且顶和底之间至少有一个K线不属于顶分型与底分型。当然，还有一个最显然的，就是在同一笔中，顶分型中最高那K线的区间至少要有一部分高于底分型中最低那K线的区间，如果这条都不满足，也就是顶都在低的范围内或顶比底还低，这显然是不可接受的。」 -/
def b7_validPenFromBarsBool (raw : List KBar) : Bool :=
  let merged := mergeTrackedDirectional true raw
  let m := merged.length
  allBarsValid raw &&
  decide (m ≥ 6) &&
  match nthTrackedOpt merged 0, nthTrackedOpt merged 1, nthTrackedOpt merged 2,
        nthTrackedOpt merged (m - 3), nthTrackedOpt merged (m - 2), nthTrackedOpt merged (m - 1) with
  | some b0, some b1, some b2, some t0, some t1, some t2 =>
    isBottomFractalBool { lo := b0.lo, hi := b0.hi } { lo := b1.lo, hi := b1.hi } { lo := b2.lo, hi := b2.hi } &&
    isTopFractalBool { lo := t0.lo, hi := t0.hi } { lo := t1.lo, hi := t1.hi } { lo := t2.lo, hi := t2.hi } &&
    decide (b1.hi < t1.hi) &&
    decide (b1.loRawIdx < t1.hiRawIdx)
  | _, _, _, _, _, _ => false

/-- 由底分型中心合并 K 线的真实最低价原始下标 `b1.loRawIdx` 与顶分型中心合并 K 线的真实最高价原始下标 `t1.hiRawIdx` 直接计算原始下标差（`≥ 4` 即两极值 K 线之间严格至少 3 根原始 K 线）。
引文：[二级旁证] [081:110]「本ID想了想，计算了一下能量力度，觉得以后可以把笔的成立条件略微放松一下，就是一笔必须满足以下两个条件：1、顶分型与底分型经过包含处理后，不允许共用K线，也就是不能有一K线分别属于顶分型与底分型，这条件和原来是一样的，这一点绝对不能放松，因为这样，才能保证足够的能量力度；2、在满足1的前提下，顶分型中最高K线和底分型的最低K线之间（不包括这两K线），不考虑包含关系，至少有3根（包括3根）以上K线。」 -/
def b7_newPenGapFromBars (raw : List KBar) : Nat :=
  let merged := mergeTrackedDirectional true raw
  let m := merged.length
  match nthTrackedOpt merged 1, nthTrackedOpt merged (m - 2) with
  | some b1, some t1 => t1.hiRawIdx - b1.loRawIdx
  | _, _ => 0

/-- B-7 老笔定义（直接基于带追踪合并序列）：不共用底/顶分型、顶高于底且包含处理后总根数 `≥ 7`（两分型间至少 1 根独立合并 K 线）。
引文：[062:26]「在实际分析中，都必须要求顶和底之间都至少有一K线当成一笔的最基本要求。」
引文：[077:38]「有了上面这基础工作，那这个图就可以看成只有这些分型，分型之间的K线都可以暂时不用管。下面的工作，就是确定笔了。笔，必须是一顶一底，而且顶和底之间至少有一个K线不属于顶分型与底分型。当然，还有一个最显然的，就是在同一笔中，顶分型中最高那K线的区间至少要有一部分高于底分型中最低那K线的区间，如果这条都不满足，也就是顶都在低的范围内或顶比底还低，这显然是不可接受的。」 -/
def b7_oldPenFromBars (raw : List KBar) : Prop :=
  b7_validPenFromBarsBool raw = true ∧
  (mergeTrackedDirectional true raw).length ≥ 7

/-- `b7_oldPenFromBars` 的可判定实例。 -/
instance instDecidableB7OldPenFromBars (raw : List KBar) :
    Decidable (b7_oldPenFromBars raw) :=
  inferInstanceAs (Decidable (
    b7_validPenFromBarsBool raw = true ∧
    (mergeTrackedDirectional true raw).length ≥ 7))

/-- B-7 新笔定义（直接基于带追踪合并序列）：包含处理后两分型不共用 K 线（`m ≥ 6`），且顶分型中心真实最高原始下标与底分型中心真实最低原始下标之差 `≥ 4`（其间不含两端至少 3 根原始 K 线）。
引文：[二级旁证] [081:110]「本ID想了想，计算了一下能量力度，觉得以后可以把笔的成立条件略微放松一下，就是一笔必须满足以下两个条件：1、顶分型与底分型经过包含处理后，不允许共用K线，也就是不能有一K线分别属于顶分型与底分型，这条件和原来是一样的，这一点绝对不能放松，因为这样，才能保证足够的能量力度；2、在满足1的前提下，顶分型中最高K线和底分型的最低K线之间（不包括这两K线），不考虑包含关系，至少有3根（包括3根）以上K线。」 -/
def b7_newPenFromBars (raw : List KBar) : Prop :=
  b7_validPenFromBarsBool raw = true ∧
  b7_newPenGapFromBars raw ≥ 4

/-- `b7_newPenFromBars` 的可判定实例。 -/
instance instDecidableB7NewPenFromBars (raw : List KBar) :
    Decidable (b7_newPenFromBars raw) :=
  inferInstanceAs (Decidable (
    b7_validPenFromBarsBool raw = true ∧
    b7_newPenGapFromBars raw ≥ 4))

/-- B-7 第 106 课 6 根 K 线表述（直接基于带追踪合并序列）：满足不共用分型且原始总根数 `≥ 6`。
引文：[106:16]「任一级别，都有最少的延伸时间，例如，一笔，由于必须有顶与底的分型，因此，必须至少延伸6个基本K线单位，也就是说，如果5日线都不能碰到，那就不会是笔的反弹了。」 -/
def b7_lesson106PenFromBars (raw : List KBar) : Prop :=
  b7_validPenFromBarsBool raw = true ∧
  raw.length ≥ 6

/-- `b7_lesson106PenFromBars` 的可判定实例。 -/
instance instDecidableB7Lesson106PenFromBars (raw : List KBar) :
    Decidable (b7_lesson106PenFromBars raw) :=
  inferInstanceAs (Decidable (
    b7_validPenFromBarsBool raw = true ∧
    raw.length ≥ 6))

/-- B-7 老笔与新笔规则分离见证命题：存在合法原始 K 线序列使新笔成立而老笔不成立。
所刻画确切命题：`081:110` 明确提出放松条件、`081:160` 说明个人仍用老标准；二者属于需要参数化分离的两套成笔规则，且新笔间隔完全由合并分型中心的真实原始极值下标计算，不冒称作者宣称逐项等价。
引文：[二级旁证] [081:110]「本ID想了想，计算了一下能量力度，觉得以后可以把笔的成立条件略微放松一下，就是一笔必须满足以下两个条件：1、顶分型与底分型经过包含处理后，不允许共用K线，也就是不能有一K线分别属于顶分型与底分型，这条件和原来是一样的，这一点绝对不能放松，因为这样，才能保证足够的能量力度；2、在满足1的前提下，顶分型中最高K线和底分型的最低K线之间（不包括这两K线），不考虑包含关系，至少有3根（包括3根）以上K线。」
引文：[二级旁证] [081:160]「本ID自己一直用老标准，因为本ID从来只用一套软件。但这理论公开，就有一个适应性的问题，毕竟不能要求所有人只用一套软件，所以稍微改改，又不影响最终的判断，又何妨？」 -/
def b7_oldNewPenRuleSeparated : Prop :=
  ∃ raw : List KBar,
    b7_newPenFromBars raw ∧ ¬ b7_oldPenFromBars raw

/-- B-42 笔唯一性证明第一情形局部转写（`077:42`，独立于 B-7 新老笔分离）：前面的底高于后面的底（`d1 > d2`）。
引文：[077:42]「如果前面的底高于后面的底，那么前面的划分显然是错误的，因为按这种划分，该笔是没有完成的，一个底不经过一个顶后就有一个更低的底，这是最典型的笔没完成的情况。」 -/
def b42_penProofCase1Literal (d1 d2 : Int) : Prop :=
  d1 > d2

/-- `b42_penProofCase1Literal` 的可判定实例。 -/
instance instDecidableB42PenProofCase1Literal (d1 d2 : Int) :
    Decidable (b42_penProofCase1Literal d1 d2) :=
  inferInstanceAs (Decidable (d1 > d2))

/-- B-42 笔唯一性证明第二情形局部转写（`077:44` 不等号写反）：前面的底“不低于”后面的底（`d1 ≥ d2`）。
所刻画确切命题：`077:44` 字面写作“不低于”，与 `077:42` 的“高于”在 `d1 > d2` 重叠并遗漏 `d1 < d2`（应为“不高于”）。
引文：[077:44]「如果前面的底不低于后面的底，那么如果再下面一个顶分型出现前，如果有一个底分型低于前面的底，那么，这两种划分都是不正确的，所划分的笔都是没完成的；」 -/
def b42_penProofCase2Literal (d1 d2 : Int) : Prop :=
  d1 ≥ d2

/-- `b42_penProofCase2Literal` 的可判定实例。 -/
instance instDecidableB42PenProofCase2Literal (d1 d2 : Int) :
    Decidable (b42_penProofCase2Literal d1 d2) :=
  inferInstanceAs (Decidable (d1 ≥ d2))

/-- B-42 笔唯一性证明分情况讨论合法性局部命题：`077:42` 与 `077:44` 构成对任意 `(d1, d2)` 的互斥且穷尽划分。
引文：[077:42]「如果前面的底高于后面的底，那么前面的划分显然是错误的，因为按这种划分，该笔是没有完成的，一个底不经过一个顶后就有一个更低的底，这是最典型的笔没完成的情况。」
引文：[077:44]「如果前面的底不低于后面的底，那么如果再下面一个顶分型出现前，如果有一个底分型低于前面的底，那么，这两种划分都是不正确的，所划分的笔都是没完成的；」 -/
def b42_penProofCasesPartitionLiteral : Prop :=
  ∀ d1 d2 : Int,
    (b42_penProofCase1Literal d1 d2 ∨ b42_penProofCase2Literal d1 d2) ∧
    ¬ (b42_penProofCase1Literal d1 d2 ∧ b42_penProofCase2Literal d1 d2)

/-! ### B-36：以首次破底为严格观察终点的闭合追踪（区分项目选定站稳确认标准与 `108:18` 原句） -/

/-- 底分型区间的上边沿（三根构成 K 线的最高点）。
引文：[108:18]「站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。」 -/
def b36_bottomFractalUpperEdge (k1 k2 k3 : KBar) : Int :=
  let m12 := if k1.hi ≤ k2.hi then k2.hi else k1.hi
  if m12 ≤ k3.hi then k3.hi else m12

/-- 检查后续序列中是否出现低于 `minLo` 的新低（`108:18`“跌破分型最低点意味着底部构成失败”）。
引文：[108:18]「站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。」 -/
def b36_breaksBelowLo (minLo : Int) : List KBar → Bool
  | [] => false
  | k :: rest => decide (k.lo < minLo) || b36_breaksBelowLo minLo rest

/-- 严格将 `followUp` 截断到**首次跌破 `minLo` 的那根 K 线**（含该破底 K 线、丢弃其后追加的全部 K 线），确保首次破底作为观察终点且破底之后追加的任何 K 线绝不改变包含合并或顶分型判定。
引文：[108:18]「站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。」 -/
def b36_takeThroughFirstBreak (minLo : Int) : List KBar → List KBar
  | [] => []
  | k :: rest =>
    if k.lo < minLo then [k]
    else k :: b36_takeThroughFirstBreak minLo rest

/-- 项目选定的因果站稳确认条件之一：确认段 `confirmBars` 中每根 K 线均守住底分型上边沿 `upperEdge`（`k.lo ≥ upperEdge`）。
引文：[108:18]「站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。」 -/
def b36_allHoldAtOrAboveEdge (upperEdge : Int) : List KBar → Bool
  | [] => true
  | k :: rest => decide (k.lo ≥ upperEdge) && b36_allHoldAtOrAboveEdge upperEdge rest

/-- 项目选定的因果站稳确认条件之二：确认段 `confirmBars` 中至少一根 K 线严格站上底分型上边沿 `upperEdge`（`k.lo > upperEdge`）。
引文：[108:18]「站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。」 -/
def b36_hasBarStandingAboveEdge (upperEdge : Int) : List KBar → Bool
  | [] => false
  | k :: rest => decide (k.lo > upperEdge) || b36_hasBarStandingAboveEdge upperEdge rest

/-- B-36 以首次破底为严格观察终点的闭合追踪场景：
1. 从非包含底分型 `(k1, k2, k3)` 出发，经非空确认段 `confirmBars`（满足项目选定的因果站稳确认标准：全段 `lo ≥ upperEdge` 且至少一根 `lo > upperEdge`）；
2. `followUp` 中存在跌破底分型最低点 `k2.lo` 的底部失败事件，并经 `b36_takeThroughFirstBreak k2.lo followUp` 严格截断到首次破底 K 线作为观察终点 `obsSeq`（其后追加的任何 K 线绝不参与计算）；
3. 仅对 `obsSeq` 做方向正确包含合并，且原底分型 `[k1, k2, k3]` 保持完整。
所刻画确切命题：`108:18` 原句未给出“有效站住”的形式化定义；本结构显式区分项目选定的因果站稳确认标准与 `108:18` 原句，并保证首次破底之后追加任意 K 线均不改变闭合判定。
引文：[108:18]「站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。」 -/
def b36_closedPostStandFailureTrace
    (k1 k2 k3 : KBar) (confirmBars followUp : List KBar) : Prop :=
  let edge := b36_bottomFractalUpperEdge k1 k2 k3
  let obsFollow := b36_takeThroughFirstBreak k2.lo followUp
  let obsSeq := [k1, k2, k3] ++ confirmBars ++ obsFollow
  let merged := mergeBarsDirectional true obsSeq
  allBarsValid obsSeq = true ∧
  noAdjacentNested [k1, k2, k3] = true ∧
  isBottomFractalBar k1 k2 k3 ∧
  merged.take 3 = [k1, k2, k3] ∧
  confirmBars ≠ [] ∧
  b36_allHoldAtOrAboveEdge edge confirmBars = true ∧
  b36_hasBarStandingAboveEdge edge confirmBars = true ∧
  b36_breaksBelowLo k2.lo confirmBars = false ∧
  b36_breaksBelowLo k2.lo followUp = true

/-- `b36_closedPostStandFailureTrace` 的可判定布尔版本。
引文：[108:18]「站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。」 -/
def b36_closedPostStandFailureTraceBool
    (k1 k2 k3 : KBar) (confirmBars followUp : List KBar) : Bool :=
  let edge := b36_bottomFractalUpperEdge k1 k2 k3
  let obsFollow := b36_takeThroughFirstBreak k2.lo followUp
  let obsSeq := [k1, k2, k3] ++ confirmBars ++ obsFollow
  let merged := mergeBarsDirectional true obsSeq
  allBarsValid obsSeq &&
  noAdjacentNested [k1, k2, k3] &&
  isBottomFractalBool k1 k2 k3 &&
  decide (merged.take 3 = [k1, k2, k3]) &&
  decide (confirmBars ≠ []) &&
  b36_allHoldAtOrAboveEdge edge confirmBars &&
  b36_hasBarStandingAboveEdge edge confirmBars &&
  (!b36_breaksBelowLo k2.lo confirmBars) &&
  b36_breaksBelowLo k2.lo followUp

/-- B-36 `108:18` 在项目选定因果站稳标准下的闭合检验命题：凡在底分型后满足站稳上边沿确认、且后续跌破 `k2.lo` 闭合的走势，截断至**首次跌破 `k2.lo`** 为止的观察窗口 `obsSeq` 经包含合并后，必然已形成与原底分型不共用的顶分型（即满足展开向上一笔的必要条件）。
所刻画确切命题：明确区分项目选定的站稳确认标准与 `108:18` 原句（原句未定义“有效站住”）；将首次跌破 `k2.lo` 锁定为观察终点后，既杜绝截短上涨前缀的假反例，又保证破底后追加任何 K 线均不改变结论。注：`080:30` 后句明列“1、形成笔；2、不形成笔”，故不为其建价格上界反驳；亦不将“站稳上边沿”错写为老笔成笔的必要条件。
引文：[108:18]「站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。」
引文：[二级旁证] [104:282]「今天低开后，在60分钟刚好跌破顶分型的下边，早上那标准的回抽，极端显然地上不了3613点，因此确认这对顶分型下边的跌破是有效的，因此后面的下跌就顺理成章了，为什么？因为向下要形成笔。」 -/
def b36_standAboveEdgeEnsuresPenBeforeFailureLiteral : Prop :=
  ∀ (k1 k2 k3 : KBar) (confirmBars followUp : List KBar),
    b36_closedPostStandFailureTraceBool k1 k2 k3 confirmBars followUp = true →
    let obsFollow := b36_takeThroughFirstBreak k2.lo followUp
    let obsSeq := [k1, k2, k3] ++ confirmBars ++ obsFollow
    b6_containsTopFractal ((mergeBarsDirectional true obsSeq).drop 3) = true

end Chan.Audit.Literal
