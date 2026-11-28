module

/-!
# 缠论原典字面版定义：序、中枢与折线（B-2 / B-3 / B-8 / B-9 / B-38）

本模块仅收载原典字面表述的形式化定义与可判定实例，供后续 `Chan/Audit/Math`
进行反例构造与逻辑核验；完全独立自包含，不导入任何主线模块或外部数学库，亦不包含定理证明。
-/

@[expose] public section

namespace Chan.Audit.Literal

/-- 闭价格区间 `[lo, hi]`，用于刻画中枢与走势段的值域边界。
引文：[020:52]「为方便起见，以后都把这些与中枢方向一致的次级别走势类型称为Z走势段，按中枢中的时间顺序，分别记为Zn等，而相应的高、低点分别记为gn、dn,定义四个指标：GG=max(gn),G=min(gn),D=max(dn),DD=min(dn)，n遍历中枢中所有Zn。」 -/
structure RangeBounds where
  /-- 区间下界。 -/
  lo : Int
  /-- 区间上界。 -/
  hi : Int
  deriving Repr, DecidableEq

/-- 两个整数的较小值。
引文：[020:54]「特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：」 -/
def intMin (a b : Int) : Int :=
  if a ≤ b then a else b

/-- 两个整数的较大值。
引文：[020:54]「特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：」 -/
def intMax (a b : Int) : Int :=
  if a ≤ b then b else a

/-- 闭区间非空性谓词：`lo ≤ hi`。
引文：[020:54]「特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：」 -/
def RangeBounds.valid (r : RangeBounds) : Prop :=
  r.lo ≤ r.hi

/-- `RangeBounds.valid` 的可判定实例。 -/
instance instDecidableRangeBoundsValid (r : RangeBounds) : Decidable r.valid :=
  inferInstanceAs (Decidable (r.lo ≤ r.hi))

/-- 走势段方向：向上或向下。
引文：[078:60]「经过标准化处理后，所有向上线段都是以最低点开始最高点结束，向下线段都是以最高点开始最低点结束，这样，所以线段的连接，就形成一条延续不断、首尾相连的折线，这样，复杂的图形，就会十分地标准化，也为后面的中枢、走势类型等分析提供了最标准且基础的部件。」 -/
inductive SegDir where
  /-- 向上方向。 -/
  | up
  /-- 向下方向。 -/
  | down
  deriving Repr, DecidableEq

/-- 翻转走势段方向。
引文：[078:60]「经过标准化处理后，所有向上线段都是以最低点开始最高点结束，向下线段都是以最高点开始最低点结束，这样，所以线段的连接，就形成一条延续不断、首尾相连的折线，这样，复杂的图形，就会十分地标准化，也为后面的中枢、走势类型等分析提供了最标准且基础的部件。」 -/
def flipSegDir : SegDir → SegDir
  | .up => .down
  | .down => .up

/-- 带起止端点与实际极值区间的有向走势段。
引文：[070:48]「没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。」 -/
structure DirectedSeg where
  /-- 线段方向。 -/
  dir : SegDir
  /-- 线段起点价位。 -/
  startPrice : Int
  /-- 线段终点价位。 -/
  endPrice : Int
  /-- 线段内部实际最低价。 -/
  lo : Int
  /-- 线段内部实际最高价。 -/
  hi : Int
  deriving Repr, DecidableEq

/-- 提取有向走势段的值域区间 `[lo, hi]`。
引文：[054:54]「三个小括弧里的1分钟中枢重叠构成了大括弧里的5分钟高一级别中枢。中枢的区间是[d2，g5]，注意，这时候，就要把1分钟的走势当成线段，小括弧里的都是线段，高低点就是这线段的端点。」 -/
def DirectedSeg.toRange (s : DirectedSeg) : RangeBounds :=
  { lo := s.lo, hi := s.hi }

/-- 有向走势段的方向与极值一致性前提：起止端点均落于 `[lo, hi]` 内，且按 `078:20` 向上段满足 `startPrice < endPrice`、向下段满足 `endPrice < startPrice`。
引文：[078:20]「同样，正如同一笔不可能出现顶低于底的情况，同一线段中，两端的一顶一底，顶肯定要高于底，如果你划出一个不符合这基本要求的线段，那肯定是划错了。」 -/
def directedSegValid (s : DirectedSeg) : Prop :=
  s.lo ≤ s.startPrice ∧
  s.startPrice ≤ s.hi ∧
  s.lo ≤ s.endPrice ∧
  s.endPrice ≤ s.hi ∧
  ((s.dir = .up ∧ s.startPrice < s.endPrice) ∨
   (s.dir = .down ∧ s.endPrice < s.startPrice))

/-- `directedSegValid` 的可判定实例。 -/
instance instDecidableDirectedSegValid (s : DirectedSeg) :
    Decidable (directedSegValid s) :=
  inferInstanceAs (Decidable (
    s.lo ≤ s.startPrice ∧
    s.startPrice ≤ s.hi ∧
    s.lo ≤ s.endPrice ∧
    s.endPrice ≤ s.hi ∧
    ((s.dir = .up ∧ s.startPrice < s.endPrice) ∨
     (s.dir = .down ∧ s.endPrice < s.startPrice))))

/-- 安全读取走势段列表中下标 `idx` 处的元素。
引文：[020:62]「注意，第三类买卖点比第一、二类要后知后觉，但如果抓得好，往往不用浪费盘整的时间，比较适合短线技术较好的资金，但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。」 -/
def nthSegOpt : List DirectedSeg → Nat → Option DirectedSeg
  | [], _ => none
  | x :: _, 0 => some x
  | _ :: xs, n + 1 => nthSegOpt xs n

/-! ### 共享笔序列、特征序列与真实线段破坏分界见证（供 B-2 与 B-9 共用） -/

/-- 构成线段的单笔载体：由起止端点唯一确定方向与值域。
引文：[078:22]「由于图形不断延续，因此，除非是新股上市后最开始的一段，否则任何一段都是破坏前一段的，如果你的划分，不能保证前面每一段都是被后一段破坏，那么这划分肯定不对。线段的破坏是可以逆时间传递的，也就是说被后线段破坏的线段，一定破坏前线段，如果违反这个原则，那线段的划分一定有问题。」 -/
structure PenStroke where
  /-- 笔起点价位。 -/
  startPrice : Int
  /-- 笔终点价位。 -/
  endPrice : Int
  deriving Repr, DecidableEq

/-- 单笔非退化判定：`startPrice ≠ endPrice`。
引文：[078:20]「同样，正如同一笔不可能出现顶低于底的情况，同一线段中，两端的一顶一底，顶肯定要高于底，如果你划出一个不符合这基本要求的线段，那肯定是划错了。」 -/
def penStrokeValidBool (s : PenStroke) : Bool :=
  decide (s.startPrice ≠ s.endPrice)

/-- 单笔方向。
引文：[078:20]「同样，正如同一笔不可能出现顶低于底的情况，同一线段中，两端的一顶一底，顶肯定要高于底，如果你划出一个不符合这基本要求的线段，那肯定是划错了。」 -/
def penStrokeDir (s : PenStroke) : SegDir :=
  if s.startPrice < s.endPrice then .up else .down

/-- 单笔最低价。
引文：[078:58]「注意，这里必须提醒一句，就是这在以前也曾说过，就是，如果线段中，最高或最低点不是线段的端点，那么，在任何以线段为基础的分析中，例如把线段为基础构成最小级别的中枢等，都可以把该线段标准化为最高低点都在端点。因为，在以线段为基础的分析中，都把线段当成一个没有内部结构的基本部件，所以，只需要关心这线段的实际区间就可以，这样就可以只看其高低点。」 -/
def penStrokeLo (s : PenStroke) : Int :=
  intMin s.startPrice s.endPrice

/-- 单笔最高价。
引文：[078:58]「注意，这里必须提醒一句，就是这在以前也曾说过，就是，如果线段中，最高或最低点不是线段的端点，那么，在任何以线段为基础的分析中，例如把线段为基础构成最小级别的中枢等，都可以把该线段标准化为最高低点都在端点。因为，在以线段为基础的分析中，都把线段当成一个没有内部结构的基本部件，所以，只需要关心这线段的实际区间就可以，这样就可以只看其高低点。」 -/
def penStrokeHi (s : PenStroke) : Int :=
  intMax s.startPrice s.endPrice

/-- 单笔的值域闭区间 `[lo, hi]`。
引文：[067:18]「定义：序列X1X2…Xn成为以向上笔开始线段的特征序列；序列S1S2…Sn成为以向下笔开始线段的特征序列。特征序列两相邻元素间没有重合区间，称为该序列的一个缺口。」 -/
def penStrokeRange (s : PenStroke) : RangeBounds :=
  { lo := penStrokeLo s, hi := penStrokeHi s }

/-- 安全读取笔序列中下标 `idx` 处的笔。
引文：[067:16]「以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。」 -/
def nthStrokeOpt : List PenStroke → Nat → Option PenStroke
  | [], _ => none
  | x :: _, 0 => some x
  | _ :: xs, n + 1 => nthStrokeOpt xs n

/-- 校验笔序列按 `expectedDir` 起始、方向严格交替且首尾端点相连。
引文：[077:62]「也就是说，和笔一样，线段也不可能从一个顶开始结束于一个顶，或者从一个底开始结束于一个底。由此可见，线段中包含笔的数目，都是单数的。」 -/
def b9_strokesChainValidBool (expectedDir : SegDir) : List PenStroke → Bool
  | [] => false
  | [s] => penStrokeValidBool s && decide (penStrokeDir s = expectedDir)
  | s1 :: s2 :: rest =>
    penStrokeValidBool s1 &&
    decide (penStrokeDir s1 = expectedDir) &&
    decide (s1.endPrice = s2.startPrice) &&
    b9_strokesChainValidBool (flipSegDir expectedDir) (s2 :: rest)

/-- 校验线段前三笔存在公共重叠（`065:48` 前提）。
引文：[065:48]「线段有一个最基本的前提，就是线段的前三笔，必须有重叠的部分，这个前提在前面可能没有特别强调，这里必须特别强调一次。线段至少有三笔，但并不是连续的三笔就一定构成线段，这三笔必须有重叠的部分。」 -/
def b9_firstThreeOverlapBool : List PenStroke → Bool
  | s1 :: s2 :: s3 :: _ =>
    decide (intMax (intMax (penStrokeLo s1) (penStrokeLo s2)) (penStrokeLo s3) ≤
            intMin (intMin (penStrokeHi s1) (penStrokeHi s2)) (penStrokeHi s3))
  | _ => false

/-- 辅助递归：统计整段笔序列的实际最低点、最高点与末尾终点。
引文：[078:58]「注意，这里必须提醒一句，就是这在以前也曾说过，就是，如果线段中，最高或最低点不是线段的端点，那么，在任何以线段为基础的分析中，例如把线段为基础构成最小级别的中枢等，都可以把该线段标准化为最高低点都在端点。因为，在以线段为基础的分析中，都把线段当成一个没有内部结构的基本部件，所以，只需要关心这线段的实际区间就可以，这样就可以只看其高低点。」 -/
def b9_strokesBoundsLoop (curLo curHi lastEnd : Int) : List PenStroke → Int × Int × Int
  | [] => (curLo, curHi, lastEnd)
  | s :: rest =>
    b9_strokesBoundsLoop
      (intMin curLo (penStrokeLo s))
      (intMax curHi (penStrokeHi s))
      s.endPrice
      rest

/-- 由笔序列直接导出对应的 `DirectedSeg`（起止端点取首尾笔端点，极值取全部笔的实际 `[lo, hi]`）。
引文：[078:42]「这种情况下，如果那向上笔突破线段B的高点，这时候就会出现，线段的开始点并不是最高点的情况。」 -/
def b9_segFromStrokes (d : SegDir) : List PenStroke → Option DirectedSeg
  | [] => none
  | s :: rest =>
    let (loVal, hiVal, endVal) := b9_strokesBoundsLoop (penStrokeLo s) (penStrokeHi s) s.endPrice rest
    some { dir := d, startPrice := s.startPrice, endPrice := endVal, lo := loVal, hi := hiVal }

/-- 提取单条线段内部的特征序列元素（奇数下标笔 `1, 3, 5, ...`）。
引文：[067:18]「定义：序列X1X2…Xn成为以向上笔开始线段的特征序列；序列S1S2…Sn成为以向下笔开始线段的特征序列。特征序列两相邻元素间没有重合区间，称为该序列的一个缺口。」 -/
def segExtractCharElems : List PenStroke → List RangeBounds
  | _ :: x :: rest => penStrokeRange x :: segExtractCharElems rest
  | _ => []

/-- 判断两特征元素区间是否存在包含关系（含等号）。
引文：[067:20]「关于特征序列，把每一元素看成是一K线，那么，如同一般K线图中找分型的方法，也存在所谓的包含关系，也可以对此进行非包含处理。经过非包含处理的特征序列，成为标准特征序列。以后没有特别说明，特征序列都是指标准特征序列。」 -/
def segRangeNestedBool (a b : RangeBounds) : Bool :=
  (decide (a.lo ≤ b.lo) && decide (b.hi ≤ a.hi)) ||
  (decide (b.lo ≤ a.lo) && decide (a.hi ≤ b.hi))

/-- 向上方向的包含合并（高高取高、低低取高）。
引文：[065:18]「当向上时，顺次n个包含关系的K线组，等价于[maxdi,maxgi]」 -/
def segRangeMergeUp (a b : RangeBounds) : RangeBounds :=
  { lo := intMax a.lo b.lo, hi := intMax a.hi b.hi }

/-- 向下方向的包含合并（低低取低、高高取低）。
引文：[065:18]「向下时，顺次n个包含关系的K线组，等价于[mindi,mingi]」 -/
def segRangeMergeDown (a b : RangeBounds) : RangeBounds :=
  { lo := intMin a.lo b.lo, hi := intMin a.hi b.hi }

/-- 方向正确的特征序列单步顺序包含合并（`065:24` + `067:20`）。
引文：[065:24]「假设，第n根K线满足第n根与第n+1根的包含关系，而第n根与第n-1根不是包含关系，那么如果gn>=gn-1，那么称第n-1、n、n+1根K线是向上的；如果dn<=dn-1，那么称第n-1、n、n+1根K线是向下的。」 -/
def segPushCharElem (initUp : Bool) (acc : List RangeBounds) (e : RangeBounds) : List RangeBounds :=
  match acc with
  | [] => [e]
  | [last] =>
    if segRangeNestedBool last e then
      [if initUp then segRangeMergeUp last e else segRangeMergeDown last e]
    else
      [e, last]
  | last :: prev :: rest =>
    if segRangeNestedBool last e then
      let merged := if prev.hi < last.hi then segRangeMergeUp last e else segRangeMergeDown last e
      merged :: prev :: rest
    else
      e :: last :: prev :: rest

/-- 对单条线段的特征序列执行方向正确的顺序包含合并，产出标准特征序列。
引文：[067:20]「关于特征序列，把每一元素看成是一K线，那么，如同一般K线图中找分型的方法，也存在所谓的包含关系，也可以对此进行非包含处理。经过非包含处理的特征序列，成为标准特征序列。以后没有特别说明，特征序列都是指标准特征序列。」 -/
def segMergeCharElems (initUp : Bool) (xs : List RangeBounds) : List RangeBounds :=
  (xs.foldl (segPushCharElem initUp) []).reverse

/-- 特征序列三元素顶分型判定。
引文：[067:28]「特征序列的顶分型中，第一和第二元素间不存在特征序列的缺口，那么该线段在该顶分型的高点处结束，该高点是该线段的终点；特征序列的底分型中，第一和第二元素间不存在特征序列的缺口，那么该线段在该底分型的低点处结束，该低点是该线段的终点；」 -/
def segRangeIsTopFractalBool (a b c : RangeBounds) : Bool :=
  decide (a.hi < b.hi) && decide (c.hi < b.hi) &&
  decide (a.lo < b.lo) && decide (c.lo < b.lo)

/-- 特征序列三元素底分型判定。
引文：[067:38]「特征序列的顶分型中，第一和第二元素间存在特征序列的缺口，如果从该分型最高点开始的向下一笔开始的序列的特征序列出现底分型，那么该线段在该顶分型的高点处结束，该高点是该线段的终点；特征序列的底分型中，第一和第二元素间存在特征序列的缺口，如果从该分型最低点开始的向上一笔开始的序列的特征序列出现顶分型，那么该线段在该底分型的低点处结束，该低点是该线段的终点；」 -/
def segRangeIsBottomFractalBool (a b c : RangeBounds) : Bool :=
  decide (b.lo < a.lo) && decide (b.lo < c.lo) &&
  decide (b.hi < a.hi) && decide (b.hi < c.hi)

/-- 检查标准特征序列中是否存在顶分型。
引文：[067:38]「特征序列的顶分型中，第一和第二元素间存在特征序列的缺口，如果从该分型最高点开始的向下一笔开始的序列的特征序列出现底分型，那么该线段在该顶分型的高点处结束，该高点是该线段的终点；特征序列的底分型中，第一和第二元素间存在特征序列的缺口，如果从该分型最低点开始的向上一笔开始的序列的特征序列出现顶分型，那么该线段在该底分型的低点处结束，该低点是该线段的终点；」 -/
def segHasTopFractalBool : List RangeBounds → Bool
  | a :: b :: c :: rest => segRangeIsTopFractalBool a b c || segHasTopFractalBool (b :: c :: rest)
  | _ => false

/-- 检查标准特征序列中是否存在底分型。
引文：[067:38]「特征序列的顶分型中，第一和第二元素间存在特征序列的缺口，如果从该分型最高点开始的向下一笔开始的序列的特征序列出现底分型，那么该线段在该顶分型的高点处结束，该高点是该线段的终点；特征序列的底分型中，第一和第二元素间存在特征序列的缺口，如果从该分型最低点开始的向上一笔开始的序列的特征序列出现顶分型，那么该线段在该底分型的低点处结束，该低点是该线段的终点；」 -/
def segHasBottomFractalBool : List RangeBounds → Bool
  | a :: b :: c :: rest => segRangeIsBottomFractalBool a b c || segHasBottomFractalBool (b :: c :: rest)
  | _ => false

/-- `071:32` 复杂情形扫描：当第一情况中第三笔完全落于第一笔范围内时，沿后续笔扫描是否先破第一笔结束位置于破第一笔开始位置之前。
引文：[071:32]「这种情况还有更复杂一点的情况，就是第三笔完全在第一笔的范围内，这样，这三笔就分不出是向上还是向下，这样也就定义不了什么特征序列，为什么？因为特征序列是和走势相反的，而走势连方向都没有，那怎么知道哪个元素属于特征序列？这种情况，无非两种最后的结果：1、最终还是先破了第一笔的结束位置，这时候，新的线段显然成立，旧线段还是被破坏了；2、最终，先破第一笔的开始位置，这样，旧线段只被一笔破坏，接着就延续原来的方向，那么，显然旧线段依然延续，新线段没有出现。」 -/
def segCase1InsideScanBool (d1 : SegDir) (t1Start t1End : Int) : List PenStroke → Bool
  | [] => false
  | s :: rest =>
    match d1 with
    | .up =>
      if penStrokeDir s = .down then
        if s.endPrice < t1End then true else segCase1InsideScanBool d1 t1Start t1End rest
      else
        if s.endPrice > t1Start then false else segCase1InsideScanBool d1 t1Start t1End rest
    | .down =>
      if penStrokeDir s = .up then
        if s.endPrice > t1End then true else segCase1InsideScanBool d1 t1Start t1End rest
      else
        if s.endPrice < t1Start then false else segCase1InsideScanBool d1 t1Start t1End rest

/-- 共享真实线段破坏判定（严格依 `065:44,46`、`067:28,38` 与 `071:30,32,40,42`）：
校验 `st1`（至少 3 笔且奇数笔、方向 `d1`）与后续笔序列 `st2`（至少 3 笔、方向相反、前三笔有重叠、首尾衔接于转折点）在分界点处构成真实线段破坏。
1. **第一种情况（无缺口，分界点两侧 `e1` 与 `e2 = range(t1)` 不做包含合并）**：
   - `d1 = .up`：无缺口 `e2.lo ≤ e1.hi`（`065:44` `dj ≤ gi` 与 `071:40` 判别式，不附加 `e1.hi < e2.hi`），且要么 `t3.endPrice < t1.endPrice`（`071:30`，含 `16→12→14→11`、`16→8→20→6` 及 `0→10→4→8→1→3→0→2` 在 `8` 处），要么 `t3` 落入 `t1` 内部时后续笔先破 `t1.endPrice` 于破 `t1.startPrice` 之前（`071:32`）；
   - `d1 = .down`：对称对偶（无缺口 `e1.lo ≤ e2.hi`）。
2. **第二种情况（严格有缺口，`067:38`）**：`d1 = .up` 时 `e1.hi < e2.lo` 且 `st2` 的标准第二特征序列出现底分型；`d1 = .down` 时 `e2.hi < e1.lo` 且 `st2` 的标准第二特征序列出现顶分型。
引文：[065:44]「如果找到i和j，j>=i+2,使得dj<=gi,那么称向上线段被笔破坏。」
引文：[065:46]「如果找到i和j，j>=i+2,使得gj>=di,那么称向下线段被笔破坏。」
引文：[067:28]「特征序列的顶分型中，第一和第二元素间不存在特征序列的缺口，那么该线段在该顶分型的高点处结束，该高点是该线段的终点；特征序列的底分型中，第一和第二元素间不存在特征序列的缺口，那么该线段在该底分型的低点处结束，该低点是该线段的终点；」
引文：[071:30]「从上面的分析就可以知道，从转折点开始，如果第一笔就破坏了前线段，进而该笔延伸出三笔来，其中第三笔破点第一笔的结束位置，那么，新的线段一定形成，前线段一定结束。」
引文：[071:40]「特征序列的分型中，第一元素就是以该假设转折点前线段的最后一个特征元素，第二个元素，就是从这转折点开始的第一笔，显然，这两者之间是同方向的，因此，如果这两者之间有缺口，那么就是第二种情况，否则就是第一种，然后根据定义来考察就可以。」
引文：[071:42]「这里还要强调一下包含的问题，上面的分析知道，在这假设的转折点前后那两元素，是不存在包含关系的。因为，这两者已经被假设不是同一性质的东西，不一定是同一特征序列的；但假设的转折点后的顶分型的元素，是可以应用包含关系的。为什么？因此，这些元素间，肯定是同一性质的东西，或者就是原线段的延续，那么就同是原线段的特征序列中，或者就是新线段的非特征序列中，反正都是同一类的东西，同一类的东西，当然可以考察包含关系。」 -/
def segPairConfirmsDestructionBool (d1 : SegDir) (st1 st2 : List PenStroke) : Bool :=
  let char1 := segMergeCharElems (decide (d1 = .up)) (segExtractCharElems st1)
  decide (st1.length ≥ 3) &&
  decide (st1.length % 2 = 1) &&
  b9_strokesChainValidBool d1 st1 &&
  b9_firstThreeOverlapBool st1 &&
  decide (st2.length ≥ 3) &&
  b9_strokesChainValidBool (flipSegDir d1) st2 &&
  b9_firstThreeOverlapBool st2 &&
  match st1.reverse, char1.reverse, st2 with
  | last1 :: _, e1 :: _, t1 :: t2 :: t3 :: rest =>
    let e2 := penStrokeRange t1
    decide (last1.endPrice = t1.startPrice) &&
    match d1 with
    | .up =>
      if decide (e2.lo ≤ e1.hi) then
        decide (t3.endPrice < t1.endPrice) ||
        (decide (t2.endPrice ≤ t1.startPrice) &&
         decide (t1.endPrice ≤ t3.endPrice) &&
         segCase1InsideScanBool .up t1.startPrice t1.endPrice rest)
      else
        segHasBottomFractalBool (segMergeCharElems false (segExtractCharElems st2))
    | .down =>
      if decide (e1.lo ≤ e2.hi) then
        decide (t3.endPrice > t1.endPrice) ||
        (decide (t1.startPrice ≤ t2.endPrice) &&
         decide (t3.endPrice ≤ t1.endPrice) &&
         segCase1InsideScanBool .down t1.startPrice t1.endPrice rest)
      else
        segHasTopFractalBool (segMergeCharElems true (segExtractCharElems st2))
  | _, _, _ => false

/-- 辅助递归：检查笔序列 `strokes` 从奇数切分点 `k` 起是否不存在内部提前破坏。
引文：[078:22]「由于图形不断延续，因此，除非是新股上市后最开始的一段，否则任何一段都是破坏前一段的，如果你的划分，不能保证前面每一段都是被后一段破坏，那么这划分肯定不对。线段的破坏是可以逆时间传递的，也就是说被后线段破坏的线段，一定破坏前线段，如果违反这个原则，那线段的划分一定有问题。」 -/
def segNoDestructionFromBool (d : SegDir) (strokes : List PenStroke) (k fuel : Nat) : Bool :=
  match fuel with
  | 0 => true
  | fuel' + 1 =>
    if k + 3 > strokes.length then
      true
    else
      (!segPairConfirmsDestructionBool d (strokes.take k) (strokes.drop k)) &&
      segNoDestructionFromBool d strokes (k + 2) fuel'

/-- 检查单条笔序列在任何内部奇数切分点 `k ∈ {3, 5, ..., length - 3}` 上均未被后续笔提前破坏（杜绝将已在内部破坏的多段串误收为单条线段）。
引文：[078:22]「由于图形不断延续，因此，除非是新股上市后最开始的一段，否则任何一段都是破坏前一段的，如果你的划分，不能保证前面每一段都是被后一段破坏，那么这划分肯定不对。线段的破坏是可以逆时间传递的，也就是说被后线段破坏的线段，一定破坏前线段，如果违反这个原则，那线段的划分一定有问题。」 -/
def segHasNoInternalDestructionBool (d : SegDir) (strokes : List PenStroke) : Bool :=
  segNoDestructionFromBool d strokes 3 strokes.length

/-- 检查完整笔序列 `allStrokes` 在严格小于 `limit` 的所有奇数切分点 `j`（`3 ≤ j < limit`）上均未被 `allStrokes.drop j` 破坏（防止跨真实破坏分界的笔被误认作同一线段内笔）。
引文：[067:28]「特征序列的顶分型中，第一和第二元素间不存在特征序列的缺口，那么该线段在该顶分型的高点处结束，该高点是该线段的终点；特征序列的底分型中，第一和第二元素间不存在特征序列的缺口，那么该线段在该底分型的低点处结束，该低点是该线段的终点；」 -/
def segNoDestructionBeforeLimitBool
    (d : SegDir) (allStrokes : List PenStroke) (limit j fuel : Nat) : Bool :=
  match fuel with
  | 0 => true
  | fuel' + 1 =>
    if j ≥ limit || j + 3 > allStrokes.length then
      true
    else
      (!segPairConfirmsDestructionBool d (allStrokes.take j) (allStrokes.drop j)) &&
      segNoDestructionBeforeLimitBool d allStrokes limit (j + 2) fuel'

/-- 校验单条笔序列构成合法且内部未被提前破坏的线段：至少 3 笔且奇数笔、方向交替首尾相连、前三笔有重叠、导出线段满足 `078:20` 方向一致性，且满足 `segHasNoInternalDestructionBool`。
引文：[078:20]「同样，正如同一笔不可能出现顶低于底的情况，同一线段中，两端的一顶一底，顶肯定要高于底，如果你划出一个不符合这基本要求的线段，那肯定是划错了。」
引文：[078:22]「由于图形不断延续，因此，除非是新股上市后最开始的一段，否则任何一段都是破坏前一段的，如果你的划分，不能保证前面每一段都是被后一段破坏，那么这划分肯定不对。线段的破坏是可以逆时间传递的，也就是说被后线段破坏的线段，一定破坏前线段，如果违反这个原则，那线段的划分一定有问题。」 -/
def b9_validStrokeSegBool (d : SegDir) (strokes : List PenStroke) : Bool :=
  decide (strokes.length ≥ 3) &&
  decide (strokes.length % 2 = 1) &&
  b9_strokesChainValidBool d strokes &&
  b9_firstThreeOverlapBool strokes &&
  segHasNoInternalDestructionBool d strokes &&
  match b9_segFromStrokes d strokes with
  | some seg => decide (directedSegValid seg)
  | none => false

/-! ### B-2：答疑 `019:1058`“三段相连必有重叠”字面断言与 `067:16` 真实同线段前提分离 -/

/-- 单段非退化且端点恰为极值的折线段谓词（用于精确刻画答疑 `019:1058` 所举的“N 字”三段）。
引文：[二级旁证] [019:1058]「一个最简单的例子，你自己画一个N字，上、下、上，无论你怎么画都画不出一个没重合的。」 -/
def b2_isEndpointExtremumSeg (s : DirectedSeg) : Prop :=
  (s.dir = .up ∧ s.lo = s.startPrice ∧ s.hi = s.endPrice ∧ s.startPrice < s.endPrice) ∨
  (s.dir = .down ∧ s.hi = s.startPrice ∧ s.lo = s.endPrice ∧ s.endPrice < s.startPrice)

/-- `b2_isEndpointExtremumSeg` 的可判定实例。 -/
instance instDecidableB2IsEndpointExtremumSeg (s : DirectedSeg) :
    Decidable (b2_isEndpointExtremumSeg s) :=
  inferInstanceAs (Decidable (
    (s.dir = .up ∧ s.lo = s.startPrice ∧ s.hi = s.endPrice ∧ s.startPrice < s.endPrice) ∨
    (s.dir = .down ∧ s.hi = s.startPrice ∧ s.lo = s.endPrice ∧ s.endPrice < s.startPrice)))

/-- 首尾相连且方向交替（上-下-上或下-上-下）的 N 字三段前提。
引文：[二级旁证] [019:1058]「你说这话证明你连三段怎么找都没搞清楚，三段是互相连着的，三段必然有重叠，根本没有可能有什么光边界重叠的情况。」 -/
def b2_connectedAltTriple (a b c : DirectedSeg) : Prop :=
  b2_isEndpointExtremumSeg a ∧
  b2_isEndpointExtremumSeg b ∧
  b2_isEndpointExtremumSeg c ∧
  a.dir ≠ b.dir ∧
  b.dir ≠ c.dir ∧
  a.endPrice = b.startPrice ∧
  b.endPrice = c.startPrice

/-- `b2_connectedAltTriple` 的可判定实例。 -/
instance instDecidableB2ConnectedAltTriple (a b c : DirectedSeg) :
    Decidable (b2_connectedAltTriple a b c) :=
  inferInstanceAs (Decidable (
    b2_isEndpointExtremumSeg a ∧
    b2_isEndpointExtremumSeg b ∧
    b2_isEndpointExtremumSeg c ∧
    a.dir ≠ b.dir ∧
    b.dir ≠ c.dir ∧
    a.endPrice = b.startPrice ∧
    b.endPrice = c.startPrice))

/-- 三段闭区间存在非空公共重叠（允许边界单点重叠）。
引文：[065:48]「线段有一个最基本的前提，就是线段的前三笔，必须有重叠的部分，这个前提在前面可能没有特别强调，这里必须特别强调一次。线段至少有三笔，但并不是连续的三笔就一定构成线段，这三笔必须有重叠的部分。」 -/
def b2_tripleCommonOverlap (a b c : RangeBounds) : Prop :=
  intMax (intMax a.lo b.lo) c.lo ≤ intMin (intMin a.hi b.hi) c.hi

/-- `b2_tripleCommonOverlap` 的可判定实例。 -/
instance instDecidableB2TripleCommonOverlap (a b c : RangeBounds) :
    Decidable (b2_tripleCommonOverlap a b c) :=
  inferInstanceAs (Decidable (
    intMax (intMax a.lo b.lo) c.lo ≤ intMin (intMin a.hi b.hi) c.hi))

/-- 三段闭区间存在严格正宽度公共重叠（排除仅在边界单点相触）。
引文：[二级旁证] [019:1058]「你说这话证明你连三段怎么找都没搞清楚，三段是互相连着的，三段必然有重叠，根本没有可能有什么光边界重叠的情况。」 -/
def b2_tripleStrictOverlap (a b c : RangeBounds) : Prop :=
  intMax (intMax a.lo b.lo) c.lo < intMin (intMin a.hi b.hi) c.hi

/-- `b2_tripleStrictOverlap` 的可判定实例。 -/
instance instDecidableB2TripleStrictOverlap (a b c : RangeBounds) :
    Decidable (b2_tripleStrictOverlap a b c) :=
  inferInstanceAs (Decidable (
    intMax (intMax a.lo b.lo) c.lo < intMin (intMin a.hi b.hi) c.hi))

/-- B-2 答疑字面断言一（单列自答疑 `019:1058`，不与正文 `067:16` 混同）：任意首尾相连且方向交替的 N 字三段必有非空公共重叠。
所刻画确切命题：答疑 `019:1058` 宣称“三段是互相连着的，三段必然有重叠”“画一个 N 字无论怎么画都画不出一个没重合的”，随后在答疑 `031:912` 被作者自行否定。
引文：[二级旁证] [019:1058]「你说这话证明你连三段怎么找都没搞清楚，三段是互相连着的，三段必然有重叠，根本没有可能有什么光边界重叠的情况。」
引文：[二级旁证] [019:1058]「一个最简单的例子，你自己画一个N字，上、下、上，无论你怎么画都画不出一个没重合的。」 -/
def b2_reply019ConnectedThreeAlwaysOverlapLiteral : Prop :=
  ∀ a b c : DirectedSeg,
    b2_connectedAltTriple a b c →
    b2_tripleCommonOverlap a.toRange b.toRange c.toRange

/-- B-2 答疑字面断言二（单列自答疑 `019:1058`）：任意首尾相连且方向交替的 N 字三段不可能仅在边界单点重叠。
所刻画确切命题：答疑 `019:1058` 宣称“根本没有可能有什么光边界重叠的情况”。
引文：[二级旁证] [019:1058]「你说这话证明你连三段怎么找都没搞清楚，三段是互相连着的，三段必然有重叠，根本没有可能有什么光边界重叠的情况。」 -/
def b2_reply019NoBoundaryOnlyOverlapLiteral : Prop :=
  ∀ a b c : DirectedSeg,
    b2_connectedAltTriple a b c →
    b2_tripleStrictOverlap a.toRange b.toRange c.toRange

/-- B-2 局部三笔不破前低加强价格条件（仅刻画向上-向下-向上相连三笔中回落笔不跌破前向上笔低点 `s1.lo ≤ x1.lo` 的充分价格条件；在此加强前提下相邻向上笔必有重合区间，显式区分于仅要求完好未破坏向上线段的 `b2_lesson67SameUpSegAdjacentPair`）。
引文：[065:48]「线段有一个最基本的前提，就是线段的前三笔，必须有重叠的部分，这个前提在前面可能没有特别强调，这里必须特别强调一次。线段至少有三笔，但并不是连续的三笔就一定构成线段，这三笔必须有重叠的部分。」 -/
def b2_upTripleNoBreakPriorLow (s1 x1 s2 : DirectedSeg) : Prop :=
  b2_connectedAltTriple s1 x1 s2 ∧
  s1.dir = .up ∧
  x1.dir = .down ∧
  s2.dir = .up ∧
  s1.lo ≤ x1.lo

/-- `b2_upTripleNoBreakPriorLow` 的可判定实例。 -/
instance instDecidableB2UpTripleNoBreakPriorLow (s1 x1 s2 : DirectedSeg) :
    Decidable (b2_upTripleNoBreakPriorLow s1 x1 s2) :=
  inferInstanceAs (Decidable (
    b2_connectedAltTriple s1 x1 s2 ∧
    s1.dir = .up ∧
    x1.dir = .down ∧
    s2.dir = .up ∧
    s1.lo ≤ x1.lo))

/-- B-2 正文 `067:16` 真实完好同线段相邻向上笔前提（布尔版，与 B-9 共用 `b9_validStrokeSegBool` 与 `segPairConfirmsDestructionBool` 真实分界见证，忠实遵循 `067:28` + `071:30,32`）：
在以向上笔起始的合法交替衔接完整笔序列 `allStrokes` 上，前缀 `seg := allStrokes.take segLen` 构成合法且内部未被提前破坏的向上线段，
且在整条 `allStrokes` 中 `segLen` 之前的任何奇数位置 `j`（`3 ≤ j < segLen`）均未被 `allStrokes.drop j` 破坏，
同时 `2 * k + 2 < segLen` 定位该同上段内第 `k` 对相邻向上笔 `(S_k, X_k, S_{k+1})`（不人为附加后一向上笔须创新高，也不为原典兜底而扭曲 `071:32`）。
引文：[067:16]「以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。」 -/
def b2_lesson67SameUpSegAdjacentPairBool
    (allStrokes : List PenStroke) (segLen k : Nat) : Bool :=
  let seg := allStrokes.take segLen
  b9_strokesChainValidBool .up allStrokes &&
  decide (segLen ≤ allStrokes.length) &&
  b9_validStrokeSegBool .up seg &&
  segNoDestructionBeforeLimitBool .up allStrokes segLen 3 allStrokes.length &&
  decide (2 * k + 2 < segLen)

/-- B-2 正文 `067:16` 真实完好同线段相邻向上笔前提（`Prop` 版）。
所刻画确切命题：`067:16` 的 `Si` 与 `Si+1` 属于同一条以向上笔开始且按 `067:28` + `071:30,32` 在完整笔序列中未被破坏截断的真实线段，显式与答疑 `019:1058` 的无约束三段及加强价格条件 `b2_upTripleNoBreakPriorLow` 分层。
引文：[067:16]「以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。」 -/
def b2_lesson67SameUpSegAdjacentPair
    (allStrokes : List PenStroke) (segLen k : Nat) : Prop :=
  b2_lesson67SameUpSegAdjacentPairBool allStrokes segLen k = true

/-- `b2_lesson67SameUpSegAdjacentPair` 的可判定实例。 -/
instance instDecidableB2Lesson67SameUpSegAdjacentPair
    (allStrokes : List PenStroke) (segLen k : Nat) :
    Decidable (b2_lesson67SameUpSegAdjacentPair allStrokes segLen k) :=
  inferInstanceAs (Decidable (b2_lesson67SameUpSegAdjacentPairBool allStrokes segLen k = true))

/-- B-2 正文 `067:16` 字面断言：在 `067:28` + `071:30,32` 真实完好向上线段前提 `b2_lesson67SameUpSegAdjacentPair` 下，任意相邻向上笔 `S_k` 与 `S_{k+1}` 必有公共重合区间。
所刻画确切命题：在完整线段破坏规则（含 `071:32` 笔破坏未成段而先破起点延续原段情形）下，该断言本身存在反例（如 `0→10→4→12→1→3→2→15` 或 `0→10→4→8→1→3→2→9` 接 `9→2→8→1` 中 `S2` 与 `S3` 严格不相交）；仅当额外附加回落笔不破前向上笔低点条件 `b2_upTripleNoBreakPriorLow` 时，相邻向上笔重合才可推出。
引文：[067:16]「以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。」
引文：[071:32]「这种情况还有更复杂一点的情况，就是第三笔完全在第一笔的范围内，这样，这三笔就分不出是向上还是向下，这样也就定义不了什么特征序列，为什么？因为特征序列是和走势相反的，而走势连方向都没有，那怎么知道哪个元素属于特征序列？这种情况，无非两种最后的结果：1、最终还是先破了第一笔的结束位置，这时候，新的线段显然成立，旧线段还是被破坏了；2、最终，先破第一笔的开始位置，这样，旧线段只被一笔破坏，接着就延续原来的方向，那么，显然旧线段依然延续，新线段没有出现。」 -/
def b2_lesson67SameUpSegAlwaysOverlapsLiteral : Prop :=
  ∀ (allStrokes : List PenStroke) (segLen k : Nat),
    b2_lesson67SameUpSegAdjacentPair allStrokes segLen k →
    match nthStrokeOpt allStrokes (2 * k), nthStrokeOpt allStrokes (2 * k + 2) with
    | some s1, some s2 =>
      intMax (penStrokeLo s1) (penStrokeLo s2) ≤ intMin (penStrokeHi s1) (penStrokeHi s2)
    | _, _ => False

/-! ### B-3：`020:60` 含等号可相触的字面第三类买卖点（同列表连续下标 `(i, i + 1)` 绑定首次回试，依 `020:60`/`078:42` 不附加回试极值越界门） -/

/-- 中枢核心区间 `[zd, zg]`。
引文：[020:54]「特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：」 -/
structure CenterCore where
  /-- 中枢核心下沿 `ZD`。 -/
  zd : Int
  /-- 中枢核心上沿 `ZG`。 -/
  zg : Int
  deriving Repr, DecidableEq

/-- B-3 纯价格比较分量（买点含等号）：回试低点不跌破 `ZG`（`retestLo ≥ zg`）。
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」 -/
def b3_priceNoBreakZg (zg retestLo : Int) : Prop :=
  retestLo ≥ zg

/-- `b3_priceNoBreakZg` 的可判定实例。 -/
instance instDecidableB3PriceNoBreakZg (zg retestLo : Int) :
    Decidable (b3_priceNoBreakZg zg retestLo) :=
  inferInstanceAs (Decidable (retestLo ≥ zg))

/-- B-3 纯价格比较分量（卖点含等号对偶）：回抽高点不升破 `ZD`（`retestHi ≤ zd`）。
引文：[054:24]「当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。」 -/
def b3_priceNoBreakZd (zd retestHi : Int) : Prop :=
  retestHi ≤ zd

/-- `b3_priceNoBreakZd` 的可判定实例。 -/
instance instDecidableB3PriceNoBreakZd (zd retestHi : Int) :
    Decidable (b3_priceNoBreakZd zd retestHi) :=
  inferInstanceAs (Decidable (retestHi ≤ zd))

/-- 走势段与中枢核心闭区间存在交集（触及即属 `054:24` 中枢震荡）。
引文：[054:24]「当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。」 -/
def b3_touchesCenterOscillation (z : CenterCore) (seg : DirectedSeg) : Prop :=
  z.zd ≤ z.zg ∧ directedSegValid seg ∧ seg.lo ≤ z.zg ∧ z.zd ≤ seg.hi

/-- `b3_touchesCenterOscillation` 的可判定实例。 -/
instance instDecidableB3TouchesCenterOscillation (z : CenterCore) (seg : DirectedSeg) :
    Decidable (b3_touchesCenterOscillation z seg) :=
  inferInstanceAs (Decidable (z.zd ≤ z.zg ∧ directedSegValid seg ∧ seg.lo ≤ z.zg ∧ z.zd ≤ seg.hi))

/-- `b3_touchesCenterOscillation` 的布尔版本。
引文：[054:24]「当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。」 -/
def b3_touchesCenterOscillationBool (z : CenterCore) (seg : DirectedSeg) : Bool :=
  decide (b3_touchesCenterOscillation z seg)

/-- 检查整条已完成次级别走势列表满足每段合法、相邻方向交替且首尾端点衔接。
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」 -/
def b3_validSegChainBool : List DirectedSeg → Bool
  | [] => false
  | [s] => decide (directedSegValid s)
  | s1 :: s2 :: rest =>
    decide (directedSegValid s1) &&
    decide (s1.dir ≠ s2.dir) &&
    decide (s1.endPrice = s2.startPrice) &&
    b3_validSegChainBool (s2 :: rest)

/-- 检查在下标 `i` 之前的所有次级别走势段均仍触及中枢核心区间 `[z.zd, z.zg]`（确保 `i` 之前中枢尚未被破坏，从而 `(i, i + 1)` 不可能是破坏后的第二次回试）。
引文：[020:62]「注意，第三类买卖点比第一、二类要后知后觉，但如果抓得好，往往不用浪费盘整的时间，比较适合短线技术较好的资金，但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。」 -/
def b3_allTouchBeforeBool (z : CenterCore) : Nat → List DirectedSeg → Bool
  | 0, _ => true
  | _, [] => false
  | n + 1, s :: rest =>
    b3_touchesCenterOscillationBool z s && b3_allTouchBeforeBool z n rest

/-- 单对向上离开与紧接回试的几何合法性前提：离开段须自 `lo ≤ ZG` 真实向上离开至 `endPrice > ZG`（杜绝起终点均在核内的段被认作离开），且紧接的向下回试段自 `leaveSeg.endPrice` 衔接。依 `020:60`（仅约束回试低点）与 `078:42`（向下线段起点可非最高点），不附加 `retestSeg.hi ≤ leaveSeg.hi`。
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」
引文：[078:42]「这种情况下，如果那向上笔突破线段B的高点，这时候就会出现，线段的开始点并不是最高点的情况。」 -/
def b3_validUpLeaveAndFirstRetest (z : CenterCore) (leaveSeg retestSeg : DirectedSeg) : Prop :=
  z.zd ≤ z.zg ∧
  directedSegValid leaveSeg ∧
  directedSegValid retestSeg ∧
  leaveSeg.dir = .up ∧
  retestSeg.dir = .down ∧
  leaveSeg.lo ≤ z.zg ∧
  leaveSeg.endPrice > z.zg ∧
  leaveSeg.endPrice = retestSeg.startPrice

/-- `b3_validUpLeaveAndFirstRetest` 的可判定实例。 -/
instance instDecidableB3ValidUpLeaveAndFirstRetest
    (z : CenterCore) (leaveSeg retestSeg : DirectedSeg) :
    Decidable (b3_validUpLeaveAndFirstRetest z leaveSeg retestSeg) :=
  inferInstanceAs (Decidable (
    z.zd ≤ z.zg ∧
    directedSegValid leaveSeg ∧
    directedSegValid retestSeg ∧
    leaveSeg.dir = .up ∧
    retestSeg.dir = .down ∧
    leaveSeg.lo ≤ z.zg ∧
    leaveSeg.endPrice > z.zg ∧
    leaveSeg.endPrice = retestSeg.startPrice))

/-- 单对向下离开与紧接回抽的几何合法性前提：离开段须自 `hi ≥ ZD` 真实向下离开至 `endPrice < ZD`（杜绝起终点均在核内的段被认作离开），且紧接的向上回抽段自 `leaveSeg.endPrice` 衔接。依 `020:60` 对偶与 `078:42`（向上线段起点可非最低点），不附加 `retestSeg.lo ≥ leaveSeg.lo`。
引文：[054:24]「当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。」
引文：[078:42]「这种情况下，如果那向上笔突破线段B的高点，这时候就会出现，线段的开始点并不是最高点的情况。」 -/
def b3_validDownLeaveAndFirstRetest (z : CenterCore) (leaveSeg retestSeg : DirectedSeg) : Prop :=
  z.zd ≤ z.zg ∧
  directedSegValid leaveSeg ∧
  directedSegValid retestSeg ∧
  leaveSeg.dir = .down ∧
  retestSeg.dir = .up ∧
  leaveSeg.hi ≥ z.zd ∧
  leaveSeg.endPrice < z.zd ∧
  leaveSeg.endPrice = retestSeg.startPrice

/-- `b3_validDownLeaveAndFirstRetest` 的可判定实例。 -/
instance instDecidableB3ValidDownLeaveAndFirstRetest
    (z : CenterCore) (leaveSeg retestSeg : DirectedSeg) :
    Decidable (b3_validDownLeaveAndFirstRetest z leaveSeg retestSeg) :=
  inferInstanceAs (Decidable (
    z.zd ≤ z.zg ∧
    directedSegValid leaveSeg ∧
    directedSegValid retestSeg ∧
    leaveSeg.dir = .down ∧
    retestSeg.dir = .up ∧
    leaveSeg.hi ≥ z.zd ∧
    leaveSeg.endPrice < z.zd ∧
    leaveSeg.endPrice = retestSeg.startPrice))

/-- B-3 单位置局部字面第三类买卖点判定（含等号口径）：检验相邻两段 `(s1, s2)` 是否已按 `020:60`（含等号）或其卖点对偶构成字面第三类买卖点，供前缀首次性检查排除更早成立的字面三买卖。
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」
引文：[020:62]「注意，第三类买卖点比第一、二类要后知后觉，但如果抓得好，往往不用浪费盘整的时间，比较适合短线技术较好的资金，但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。」 -/
def b3_isLiteralThirdAtLocalBool (z : CenterCore) (s1 s2 : DirectedSeg) : Bool :=
  (decide (b3_validUpLeaveAndFirstRetest z s1 s2) && decide (b3_priceNoBreakZg z.zg s2.lo)) ||
  (decide (b3_validDownLeaveAndFirstRetest z s1 s2) && decide (b3_priceNoBreakZd z.zd s2.hi))

/-- 检查走势段列表 `segs` 在从下标 `j` 起的 `fuel` 个更早位置上均未按自身含等号字面判据提前成立第三类买卖点（杜绝首次触边成立三买卖后，在同一中枢上重复产生第二次“首次”回试）。
引文：[020:62]「注意，第三类买卖点比第一、二类要后知后觉，但如果抓得好，往往不用浪费盘整的时间，比较适合短线技术较好的资金，但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。」 -/
def b3_noPriorLiteralThirdBool (z : CenterCore) (segs : List DirectedSeg) (j fuel : Nat) : Bool :=
  match fuel with
  | 0 => true
  | fuel' + 1 =>
    match nthSegOpt segs j, nthSegOpt segs (j + 1) with
    | some s1, some s2 =>
      (!b3_isLiteralThirdAtLocalBool z s1 s2) &&
      b3_noPriorLiteralThirdBool z segs (j + 1) fuel'
    | _, _ => false

/-- B-3 列表绑定完整前提（向上离开 + 首次回试，布尔版）：在同一条已完成次级别走势列表 `segs` 上，所有下标 `< i` 的段均仍属中枢震荡且此前尚未按自身含等号口径成立过字面第三类买卖点，且连续下标 `(i, i + 1)` 分别给出真实向上离开段与紧接的首次向下回试段。
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」
引文：[020:62]「注意，第三类买卖点比第一、二类要后知后觉，但如果抓得好，往往不用浪费盘整的时间，比较适合短线技术较好的资金，但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。」 -/
def b3_validUpLeaveAndFirstRetestAtBool (z : CenterCore) (segs : List DirectedSeg) (i : Nat) : Bool :=
  b3_validSegChainBool segs &&
  b3_allTouchBeforeBool z i segs &&
  b3_noPriorLiteralThirdBool z segs 0 i &&
  match nthSegOpt segs i, nthSegOpt segs (i + 1) with
  | some leaveSeg, some retestSeg => decide (b3_validUpLeaveAndFirstRetest z leaveSeg retestSeg)
  | _, _ => false

/-- B-3 列表绑定完整前提（向上离开 + 首次回试，`Prop` 版）。
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」
引文：[020:62]「注意，第三类买卖点比第一、二类要后知后觉，但如果抓得好，往往不用浪费盘整的时间，比较适合短线技术较好的资金，但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。」 -/
def b3_validUpLeaveAndFirstRetestAt (z : CenterCore) (segs : List DirectedSeg) (i : Nat) : Prop :=
  b3_validUpLeaveAndFirstRetestAtBool z segs i = true

/-- `b3_validUpLeaveAndFirstRetestAt` 的可判定实例。 -/
instance instDecidableB3ValidUpLeaveAndFirstRetestAt
    (z : CenterCore) (segs : List DirectedSeg) (i : Nat) :
    Decidable (b3_validUpLeaveAndFirstRetestAt z segs i) :=
  inferInstanceAs (Decidable (b3_validUpLeaveAndFirstRetestAtBool z segs i = true))

/-- B-3 列表绑定完整前提（向下离开 + 首次回抽，布尔版）：在同一条已完成次级别走势列表 `segs` 上，所有下标 `< i` 的段均仍属中枢震荡且此前尚未按自身含等号口径成立过字面第三类买卖点，且连续下标 `(i, i + 1)` 分别给出真实向下离开段与紧接的首次向上回抽段。
引文：[020:62]「注意，第三类买卖点比第一、二类要后知后觉，但如果抓得好，往往不用浪费盘整的时间，比较适合短线技术较好的资金，但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。」
引文：[054:24]「当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。」 -/
def b3_validDownLeaveAndFirstRetestAtBool (z : CenterCore) (segs : List DirectedSeg) (i : Nat) : Bool :=
  b3_validSegChainBool segs &&
  b3_allTouchBeforeBool z i segs &&
  b3_noPriorLiteralThirdBool z segs 0 i &&
  match nthSegOpt segs i, nthSegOpt segs (i + 1) with
  | some leaveSeg, some retestSeg => decide (b3_validDownLeaveAndFirstRetest z leaveSeg retestSeg)
  | _, _ => false

/-- B-3 列表绑定完整前提（向下离开 + 首次回抽，`Prop` 版）。
引文：[020:62]「注意，第三类买卖点比第一、二类要后知后觉，但如果抓得好，往往不用浪费盘整的时间，比较适合短线技术较好的资金，但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。」
引文：[054:24]「当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。」 -/
def b3_validDownLeaveAndFirstRetestAt (z : CenterCore) (segs : List DirectedSeg) (i : Nat) : Prop :=
  b3_validDownLeaveAndFirstRetestAtBool z segs i = true

/-- `b3_validDownLeaveAndFirstRetestAt` 的可判定实例。 -/
instance instDecidableB3ValidDownLeaveAndFirstRetestAt
    (z : CenterCore) (segs : List DirectedSeg) (i : Nat) :
    Decidable (b3_validDownLeaveAndFirstRetestAt z segs i) :=
  inferInstanceAs (Decidable (b3_validDownLeaveAndFirstRetestAtBool z segs i = true))

/-- B-3 完整列表绑定字面第三类买点谓词（布尔版）。
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」 -/
def b3_thirdBuyAtLiteralBool (z : CenterCore) (segs : List DirectedSeg) (i : Nat) : Bool :=
  b3_validUpLeaveAndFirstRetestAtBool z segs i &&
  match nthSegOpt segs (i + 1) with
  | some retestSeg => decide (b3_priceNoBreakZg z.zg retestSeg.lo)
  | none => false

/-- B-3 完整列表绑定字面第三类买点谓词（`020:60` 含等号版）：在 `segs` 连续下标 `(i, i + 1)` 满足首次向上离开与回试前提，且 `retestSeg.lo ≥ z.zg`。
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」 -/
def b3_thirdBuyAtLiteral (z : CenterCore) (segs : List DirectedSeg) (i : Nat) : Prop :=
  b3_thirdBuyAtLiteralBool z segs i = true

/-- `b3_thirdBuyAtLiteral` 的可判定实例。 -/
instance instDecidableB3ThirdBuyAtLiteral
    (z : CenterCore) (segs : List DirectedSeg) (i : Nat) :
    Decidable (b3_thirdBuyAtLiteral z segs i) :=
  inferInstanceAs (Decidable (b3_thirdBuyAtLiteralBool z segs i = true))

/-- B-3 完整列表绑定字面第三类卖点谓词（布尔版）。
引文：[054:24]「当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。」 -/
def b3_thirdSellAtLiteralBool (z : CenterCore) (segs : List DirectedSeg) (i : Nat) : Bool :=
  b3_validDownLeaveAndFirstRetestAtBool z segs i &&
  match nthSegOpt segs (i + 1) with
  | some retestSeg => decide (b3_priceNoBreakZd z.zd retestSeg.hi)
  | none => false

/-- B-3 完整列表绑定字面第三类卖点谓词（含等号对偶版）：在 `segs` 连续下标 `(i, i + 1)` 满足首次向下离开与回抽前提，且 `retestSeg.hi ≤ z.zd`。
引文：[054:24]「当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。」 -/
def b3_thirdSellAtLiteral (z : CenterCore) (segs : List DirectedSeg) (i : Nat) : Prop :=
  b3_thirdSellAtLiteralBool z segs i = true

/-- `b3_thirdSellAtLiteral` 的可判定实例。 -/
instance instDecidableB3ThirdSellAtLiteral
    (z : CenterCore) (segs : List DirectedSeg) (i : Nat) :
    Decidable (b3_thirdSellAtLiteral z segs i) :=
  inferInstanceAs (Decidable (b3_thirdSellAtLiteralBool z segs i = true))

/-- B-3 边界互斥性检验命题：在同一条已完成次级别走势列表 `segs` 的合法首次离开-回试位置 `(i, i + 1)` 上，含等号字面第三类买卖点与 `054:24` 触及即中枢震荡二者互斥。
所刻画确切命题：即便在完整走势列表中严格锁定首次离开（`endPrice` 越界）与紧接的首次回试 `segs[i + 1]`，当回试端点恰落于 `ZG` 或 `ZD` 时，含等号字面三买卖与 `054:24` 中枢震荡仍同时成立。
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」
引文：[054:24]「当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。」 -/
def b3_literalThirdDisjointFromOscillation : Prop :=
  ∀ (z : CenterCore) (segs : List DirectedSeg) (i : Nat),
    match nthSegOpt segs (i + 1) with
    | some retestSeg =>
      (b3_thirdBuyAtLiteral z segs i → ¬ b3_touchesCenterOscillation z retestSeg) ∧
      (b3_thirdSellAtLiteral z segs i → ¬ b3_touchesCenterOscillation z retestSeg)
    | none => True

/-! ### B-8：带容差近似相等的字面关系及额外等价关系要求检验 -/

/-- 两整数之差的绝对值。
引文：[064:24]「注意，没有什么精度是十全十美的，例如用相差0.5内看成是相同的，那么如果是0.51呢？这和0.49也没有多大区别。」 -/
def intAbsDiff (a b : Int) : Int :=
  if a ≤ b then b - a else a - b

/-- B-8 可选两值容差近似相等关系（如价格放大 100 倍，`tol = 50` 即相差 `0.50` 点内视为相同）。
所刻画确切命题：`064:22` 与 `064:24` 提出可选的两值容差比较方式（作者并未宣称其构成等价关系，且 `064:24` 自己指出 `0.51` 与 `0.49` 的边界问题）。
引文：[064:22]「当然，你可能要问为什么一定要取整？这没有什么必然性，只是预设的前提，你可以采取严格到小数后两位的精确度，但其实不同软件，对1分钟这么精细的图，都会有数值上的细微差别，所以，所谓的精确，往往不一定就是，而在这么快速变动的市场中，数值有点细微差别，其实没什么不同，例如，还可以用这样的区别方式，就是两者相差0.5点内的看成是一样的。所有预设精度，唯一必须遵守的，就是精度一旦预设，就一定要一路保持。」
引文：[064:24]「注意，没有什么精度是十全十美的，例如用相差0.5内看成是相同的，那么如果是0.51呢？这和0.49也没有多大区别。」 -/
def b8_approxEqLiteral (tol a b : Int) : Prop :=
  intAbsDiff a b ≤ tol

/-- `b8_approxEqLiteral` 的可判定实例。 -/
instance instDecidableB8ApproxEqLiteral (tol a b : Int) :
    Decidable (b8_approxEqLiteral tol a b) :=
  inferInstanceAs (Decidable (intAbsDiff a b ≤ tol))

/-- B-8 额外等价关系要求（传递性）的可检验命题：对正容差 `tol > 0`，`b8_approxEqLiteral tol` 是否满足传递律。
所刻画确切命题：此为形式化引入的额外数学性质检验（用于证明容差不能作为等价类划分的比较底座，应改用显式单调量化映射），不冒称作者在 `064:22,24` 宣称过该关系具有传递性。
引文：[064:24]「注意，没有什么精度是十全十美的，例如用相差0.5内看成是相同的，那么如果是0.51呢？这和0.49也没有多大区别。」 -/
def b8_approxEqEquivalenceTransitivityRequirement (tol : Int) : Prop :=
  tol > 0 →
  ∀ a b c : Int,
    b8_approxEqLiteral tol a b →
    b8_approxEqLiteral tol b c →
    b8_approxEqLiteral tol a c

/-! ### B-9：符合 `065:44`/`067:28,38`/`071:30,32,40,42`/`078:22,42,50` 真实破坏结构的相邻线段经独立标准化后折线可能断开 -/

/-- 符合 `065:44,46`、`067:28,38`、`071:30,32,40,42` 与 `078:22,42,50` 真实相邻线段破坏结构的笔序列载体前提（支持 `067:38` 第二种情况借助后续确认笔尾 `confirmTail` 确认 `st1/st2` 分界，但不把 `confirmTail` 算入 `st2`）：
1. `st1` 与 `st2` 各自构成内部未被提前破坏的合法线段且方向相反；
2. 沿完整观察序列 `obs1 := st1 ++ st2 ++ confirmTail` 与 `obs2 := st2 ++ confirmTail` 分别排除 `st1` 与 `st2` 存在任何更早的内部破坏分界（杜绝同一条完整笔链将第二段切在两个不同终点）；
3. 若 `confirmTail` 非空，须满足 `obs2` 连续交替合法且 `st2` 在 `st2/confirmTail` 处确实被第三段破坏结束（杜绝中途乱切 `st2`）；
4. `segPairConfirmsDestructionBool d1 st1 obs2 = true`（第一种情况传 `confirmTail = []` 即可确认，第二种情况带缺口分界允许读取确认底/顶分型所需的 `confirmTail`）。
引文：[067:38]「特征序列的顶分型中，第一和第二元素间存在特征序列的缺口，如果从该分型最高点开始的向下一笔开始的序列的特征序列出现底分型，那么该线段在该顶分型的高点处结束，该高点是该线段的终点；特征序列的底分型中，第一和第二元素间存在特征序列的缺口，如果从该分型最低点开始的向上一笔开始的序列的特征序列出现顶分型，那么该线段在该底分型的低点处结束，该低点是该线段的终点；」
引文：[078:22]「由于图形不断延续，因此，除非是新股上市后最开始的一段，否则任何一段都是破坏前一段的，如果你的划分，不能保证前面每一段都是被后一段破坏，那么这划分肯定不对。线段的破坏是可以逆时间传递的，也就是说被后线段破坏的线段，一定破坏前线段，如果违反这个原则，那线段的划分一定有问题。」
引文：[二级旁证] [078:50]「注意，这个例子中有一个最关键的前提，就是线段B已经确认线段破坏了他前面的线段，如果线段B对前面线段的破坏都没确认，那就先确认，这里的分析都不适用了。」 -/
def b9_adjacentDestroyedSegPairBool
    (d1 : SegDir) (st1 st2 confirmTail : List PenStroke) : Bool :=
  let d2 := flipSegDir d1
  let obs2 := st2 ++ confirmTail
  let obs1 := st1 ++ obs2
  let tailOk :=
    match confirmTail with
    | [] => true
    | _ :: _ =>
      b9_strokesChainValidBool d2 obs2 &&
      segPairConfirmsDestructionBool d2 st2 confirmTail
  b9_validStrokeSegBool d1 st1 &&
  b9_validStrokeSegBool d2 st2 &&
  segNoDestructionBeforeLimitBool d1 obs1 st1.length 3 obs1.length &&
  segNoDestructionBeforeLimitBool d2 obs2 st2.length 3 obs2.length &&
  tailOk &&
  segPairConfirmsDestructionBool d1 st1 obs2

/-- `b9_adjacentDestroyedSegPairBool` 的命题版本。
引文：[078:22]「由于图形不断延续，因此，除非是新股上市后最开始的一段，否则任何一段都是破坏前一段的，如果你的划分，不能保证前面每一段都是被后一段破坏，那么这划分肯定不对。线段的破坏是可以逆时间传递的，也就是说被后线段破坏的线段，一定破坏前线段，如果违反这个原则，那线段的划分一定有问题。」 -/
def b9_adjacentDestroyedSegPair
    (d1 : SegDir) (st1 st2 confirmTail : List PenStroke) : Prop :=
  b9_adjacentDestroyedSegPairBool d1 st1 st2 confirmTail = true

/-- `b9_adjacentDestroyedSegPair` 的可判定实例。 -/
instance instDecidableB9AdjacentDestroyedSegPair
    (d1 : SegDir) (st1 st2 confirmTail : List PenStroke) :
    Decidable (b9_adjacentDestroyedSegPair d1 st1 st2 confirmTail) :=
  inferInstanceAs (Decidable (b9_adjacentDestroyedSegPairBool d1 st1 st2 confirmTail = true))

/-- 两条方向一致的原始相邻线段方向交替且在原连接点首尾相连。
引文：[078:20]「同样，正如同一笔不可能出现顶低于底的情况，同一线段中，两端的一顶一底，顶肯定要高于底，如果你划出一个不符合这基本要求的线段，那肯定是划错了。」
引文：[078:42]「这种情况下，如果那向上笔突破线段B的高点，这时候就会出现，线段的开始点并不是最高点的情况。」 -/
def b9_adjacentValidConnectedSegs (s1 s2 : DirectedSeg) : Prop :=
  directedSegValid s1 ∧
  directedSegValid s2 ∧
  s1.dir ≠ s2.dir ∧
  s1.endPrice = s2.startPrice

/-- `b9_adjacentValidConnectedSegs` 的可判定实例。 -/
instance instDecidableB9AdjacentValidConnectedSegs (s1 s2 : DirectedSeg) :
    Decidable (b9_adjacentValidConnectedSegs s1 s2) :=
  inferInstanceAs (Decidable (
    directedSegValid s1 ∧
    directedSegValid s2 ∧
    s1.dir ≠ s2.dir ∧
    s1.endPrice = s2.startPrice))

/-- B-9 字面标准化映射：将向上线段起终点独立置为 `(lo, hi)`，向下线段起终点独立置为 `(hi, lo)`。
引文：[078:58]「注意，这里必须提醒一句，就是这在以前也曾说过，就是，如果线段中，最高或最低点不是线段的端点，那么，在任何以线段为基础的分析中，例如把线段为基础构成最小级别的中枢等，都可以把该线段标准化为最高低点都在端点。因为，在以线段为基础的分析中，都把线段当成一个没有内部结构的基本部件，所以，只需要关心这线段的实际区间就可以，这样就可以只看其高低点。」 -/
def b9_standardizeSegLiteral (s : DirectedSeg) : DirectedSeg :=
  match s.dir with
  | .up => { s with startPrice := s.lo, endPrice := s.hi }
  | .down => { s with startPrice := s.hi, endPrice := s.lo }

/-- B-9 真实笔序列破坏载体上的字面折线连续性断言：任意满足 `065:44`/`067:28,38`/`071:30,32,40,42`/`078:22,42,50` 真实相邻破坏结构（含可选第二种情况确认笔尾 `confirmTail`）的两段笔序列 `st1, st2`，经 `b9_standardizeSegLiteral` 独立标准化后仍首尾相连（仅标准化 `st1` 与 `st2`，不将 `confirmTail` 算入第二段）。
所刻画确切命题：`078:60` 宣称标准化后所有线段的连接形成“延续不断、首尾相连的折线”；端点非极值时标准化后并非必然断开（若相邻两段极值恰相等仍可相接），但存在完全符合真实相邻线段破坏结构且内部均未被提前破坏的两段笔序列（如前上段 `0→15→10→16` 与后下段 `16→8→20→6`、`confirmTail = []`）在独立标准化后直接断开（`16 ≠ 20`）。
引文：[078:60]「经过标准化处理后，所有向上线段都是以最低点开始最高点结束，向下线段都是以最高点开始最低点结束，这样，所以线段的连接，就形成一条延续不断、首尾相连的折线，这样，复杂的图形，就会十分地标准化，也为后面的中枢、走势类型等分析提供了最标准且基础的部件。」 -/
def b9_standardizedStrokeSegsAlwaysConnectedLiteral : Prop :=
  ∀ (d1 : SegDir) (st1 st2 confirmTail : List PenStroke),
    b9_adjacentDestroyedSegPair d1 st1 st2 confirmTail →
    match b9_segFromStrokes d1 st1, b9_segFromStrokes (flipSegDir d1) st2 with
    | some s1, some s2 =>
      (b9_standardizeSegLiteral s1).endPrice = (b9_standardizeSegLiteral s2).startPrice
    | _, _ => False

/-- B-9 抽象段层面的字面折线连续性断言：任意两条方向合法且原首尾相连的交替线段，经 `b9_standardizeSegLiteral` 独立标准化后仍首尾相连（当两段在连接处极值不等时即断开）。
引文：[078:60]「经过标准化处理后，所有向上线段都是以最低点开始最高点结束，向下线段都是以最高点开始最低点结束，这样，所以线段的连接，就形成一条延续不断、首尾相连的折线，这样，复杂的图形，就会十分地标准化，也为后面的中枢、走势类型等分析提供了最标准且基础的部件。」 -/
def b9_standardizedAlwaysConnectedLiteral : Prop :=
  ∀ s1 s2 : DirectedSeg,
    b9_adjacentValidConnectedSegs s1 s2 →
    (b9_standardizeSegLiteral s1).endPrice = (b9_standardizeSegLiteral s2).startPrice

/-! ### B-38：`020:58` 针对绑定同一条连续走势链且按 `020:52` 同向 `Z` 段计算四指标的前后同级中枢分类审计 -/

/-- 带级别与时间范围的同级别中枢四指标结构：`startT < endT` 且 `DD ≤ ZD ≤ ZG ≤ GG`。
引文：[020:52]「为方便起见，以后都把这些与中枢方向一致的次级别走势类型称为Z走势段，按中枢中的时间顺序，分别记为Zn等，而相应的高、低点分别记为gn、dn,定义四个指标：GG=max(gn),G=min(gn),D=max(dn),DD=min(dn)，n遍历中枢中所有Zn。」 -/
structure CenterMetrics where
  /-- 中枢所属级别。 -/
  level : Nat
  /-- 中枢起始时刻。 -/
  startT : Nat
  /-- 中枢结束时刻。 -/
  endT : Nat
  /-- 围绕中枢同向 `Z` 走势段的最低点 `DD`。 -/
  dd : Int
  /-- 中枢核心下沿 `ZD`。 -/
  zd : Int
  /-- 中枢核心上沿 `ZG`。 -/
  zg : Int
  /-- 围绕中枢同向 `Z` 走势段的最高点 `GG`。 -/
  gg : Int
  deriving Repr, DecidableEq

/-- 单个中枢的时间非退化与价格指标序约束：`startT < endT` 且 `dd ≤ zd ≤ zg ≤ gg`。
引文：[020:54]「特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：」 -/
def CenterMetrics.valid (c : CenterMetrics) : Prop :=
  c.startT < c.endT ∧ c.dd ≤ c.zd ∧ c.zd ≤ c.zg ∧ c.zg ≤ c.gg

/-- `CenterMetrics.valid` 的可判定实例。 -/
instance instDecidableCenterMetricsValid (c : CenterMetrics) : Decidable c.valid :=
  inferInstanceAs (Decidable (c.startT < c.endT ∧ c.dd ≤ c.zd ∧ c.zd ≤ c.zg ∧ c.zg ≤ c.gg))

/-- 按 `020:52` 仅遍历与中枢方向一致的 `Z` 走势段 `(s1, s3)` 计算 `DD = min(d1, d2)`（绝不混入中间反向段 `s2` 的内部极端低点）。
引文：[020:52]「为方便起见，以后都把这些与中枢方向一致的次级别走势类型称为Z走势段，按中枢中的时间顺序，分别记为Zn等，而相应的高、低点分别记为gn、dn,定义四个指标：GG=max(gn),G=min(gn),D=max(dn),DD=min(dn)，n遍历中枢中所有Zn。」 -/
def b38_zSegsDD (s1 s3 : DirectedSeg) : Int :=
  intMin s1.lo s3.lo

/-- 按 `020:52` 仅遍历与中枢方向一致的 `Z` 走势段 `(s1, s3)` 计算 `GG = max(g1, g2)`（绝不混入中间反向段 `s2` 的内部极端高点）。
引文：[020:52]「为方便起见，以后都把这些与中枢方向一致的次级别走势类型称为Z走势段，按中枢中的时间顺序，分别记为Zn等，而相应的高、低点分别记为gn、dn,定义四个指标：GG=max(gn),G=min(gn),D=max(dn),DD=min(dn)，n遍历中枢中所有Zn。」 -/
def b38_zSegsGG (s1 s3 : DirectedSeg) : Int :=
  intMax s1.hi s3.hi

/-- 按 `020:48` 取连续三段 `(s1, s2, s3)` 公共重叠区间下沿 `ZD = max(d1, d2, d3)`（保证中枢核心精确等于三段公共交，杜绝纳入中间段 `s2` 从未到过的价格）。
引文：[020:48]「有了上面的定理，就可以很精确地讨论走势中枢的问题了：根据走势中枢的数学表达式： A、B、C，分别的高、低点是a1\a2,b1\b2,c1\c2，则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。」 -/
def b38_threeSegsZD (s1 s2 s3 : DirectedSeg) : Int :=
  intMax (intMax s1.lo s2.lo) s3.lo

/-- 按 `020:48` 取连续三段 `(s1, s2, s3)` 公共重叠区间上沿 `ZG = min(g1, g2, g3)`（保证中枢核心精确等于三段公共交，杜绝纳入中间段 `s2` 从未到过的价格）。
引文：[020:48]「有了上面的定理，就可以很精确地讨论走势中枢的问题了：根据走势中枢的数学表达式： A、B、C，分别的高、低点是a1\a2,b1\b2,c1\c2，则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。」 -/
def b38_threeSegsZG (s1 s2 s3 : DirectedSeg) : Int :=
  intMin (intMin s1.hi s2.hi) s3.hi

/-- 校验中枢 `c` 合法地由连续交替、存在公共重叠的三段次级别走势 `(s1, s2, s3)` 重算生成：外缘 `DD/GG` 按 `020:52` 仅遍历同向 `Z` 段 `(s1, s3)`，核心 `[ZD, ZG]` 按 `020:48` 精确等于三段公共交。
引文：[020:48]「有了上面的定理，就可以很精确地讨论走势中枢的问题了：根据走势中枢的数学表达式： A、B、C，分别的高、低点是a1\a2,b1\b2,c1\c2，则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。」
引文：[020:52]「为方便起见，以后都把这些与中枢方向一致的次级别走势类型称为Z走势段，按中枢中的时间顺序，分别记为Zn等，而相应的高、低点分别记为gn、dn,定义四个指标：GG=max(gn),G=min(gn),D=max(dn),DD=min(dn)，n遍历中枢中所有Zn。」 -/
def b38_centerMatchesThreeSegs (c : CenterMetrics) (s1 s2 s3 : DirectedSeg) : Prop :=
  c.valid ∧
  directedSegValid s1 ∧
  directedSegValid s2 ∧
  directedSegValid s3 ∧
  s1.dir ≠ s2.dir ∧
  s2.dir ≠ s3.dir ∧
  s1.endPrice = s2.startPrice ∧
  s2.endPrice = s3.startPrice ∧
  b2_tripleCommonOverlap s1.toRange s2.toRange s3.toRange ∧
  c.dd = b38_zSegsDD s1 s3 ∧
  c.zd = b38_threeSegsZD s1 s2 s3 ∧
  c.zg = b38_threeSegsZG s1 s2 s3 ∧
  c.gg = b38_zSegsGG s1 s3

/-- `b38_centerMatchesThreeSegs` 的可判定实例。 -/
instance instDecidableB38CenterMatchesThreeSegs
    (c : CenterMetrics) (s1 s2 s3 : DirectedSeg) :
    Decidable (b38_centerMatchesThreeSegs c s1 s2 s3) :=
  inferInstanceAs (Decidable (
    c.valid ∧
    directedSegValid s1 ∧
    directedSegValid s2 ∧
    directedSegValid s3 ∧
    s1.dir ≠ s2.dir ∧
    s2.dir ≠ s3.dir ∧
    s1.endPrice = s2.startPrice ∧
    s2.endPrice = s3.startPrice ∧
    b2_tripleCommonOverlap s1.toRange s2.toRange s3.toRange ∧
    c.dd = b38_zSegsDD s1 s3 ∧
    c.zd = b38_threeSegsZD s1 s2 s3 ∧
    c.zg = b38_threeSegsZG s1 s2 s3 ∧
    c.gg = b38_zSegsGG s1 s3))

/-- 绑定同一条完整连续交替次级别走势链的前后两中枢演化轨迹：
前中枢 `c1` 由 `(c1Seg1, c1Seg2, c1Seg3)` 按 `020:52` 同向 `Z` 段生成，经连续衔接段列表 `bridgeSegs`（整条链须首尾衔接无瞬移）演进至由 `(c2Seg1, c2Seg2, c2Seg3)` 生成的后中枢 `c2`。
引文：[018:64]「某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。」
引文：[020:58]「缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。」 -/
structure B38SequentialCentersTrace where
  /-- 构成前中枢 `c1` 的第 1 个次级别走势段（`Z1`）。 -/
  c1Seg1 : DirectedSeg
  /-- 构成前中枢 `c1` 的第 2 个次级别走势段（反向段）。 -/
  c1Seg2 : DirectedSeg
  /-- 构成前中枢 `c1` 的第 3 个次级别走势段（`Z2`）。 -/
  c1Seg3 : DirectedSeg
  /-- 前一个同级别中枢。 -/
  c1 : CenterMetrics
  /-- 连接 `c1Seg3` 终点与 `c2Seg1` 起点的中间连续次级别走势段列表（彻底杜绝价格瞬移）。 -/
  bridgeSegs : List DirectedSeg
  /-- 构成后中枢 `c2` 的第 1 个次级别走势段（`Z1`）。 -/
  c2Seg1 : DirectedSeg
  /-- 构成后中枢 `c2` 的第 2 个次级别走势段（反向段）。 -/
  c2Seg2 : DirectedSeg
  /-- 构成后中枢 `c2` 的第 3 个次级别走势段（`Z2`）。 -/
  c2Seg3 : DirectedSeg
  /-- 后一个同级别中枢。 -/
  c2 : CenterMetrics
  deriving Repr, DecidableEq

/-- 拼接 `B38SequentialCentersTrace` 的整条连续次级别走势链。
引文：[020:58]「缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。」 -/
def b38_fullSegChain (tr : B38SequentialCentersTrace) : List DirectedSeg :=
  [tr.c1Seg1, tr.c1Seg2, tr.c1Seg3] ++ tr.bridgeSegs ++ [tr.c2Seg1, tr.c2Seg2, tr.c2Seg3]

/-- B-38 公共基础链合法性（布尔版）：`c1`、`c2` 同级别、仅在 `bridgeSegs = []`（六段直连共享转折端点时刻）允许 `c1.endT ≤ c2.startT`，非空 `bridgeSegs` 一律严格要求 `c1.endT < c2.startT`（杜绝非空连接段占用零时间）、各自按 `020:48` 取三段公共核心且按 `020:52` 同向 `Z` 段取外缘重算生成，且整条 `b38_fullSegChain tr` 连续交替首尾衔接（彻底杜绝任何价格瞬移）。
引文：[020:52]「为方便起见，以后都把这些与中枢方向一致的次级别走势类型称为Z走势段，按中枢中的时间顺序，分别记为Zn等，而相应的高、低点分别记为gn、dn,定义四个指标：GG=max(gn),G=min(gn),D=max(dn),DD=min(dn)，n遍历中枢中所有Zn。」 -/
def b38_baseChainValidBool (tr : B38SequentialCentersTrace) : Bool :=
  decide (b38_centerMatchesThreeSegs tr.c1 tr.c1Seg1 tr.c1Seg2 tr.c1Seg3) &&
  decide (b38_centerMatchesThreeSegs tr.c2 tr.c2Seg1 tr.c2Seg2 tr.c2Seg3) &&
  decide (tr.c1.level = tr.c2.level) &&
  (if tr.bridgeSegs.isEmpty then decide (tr.c1.endT ≤ tr.c2.startT)
   else decide (tr.c1.endT < tr.c2.startT)) &&
  b3_validSegChainBool (b38_fullSegChain tr)

/-- B-38 前提一（同课 `020:58` + `020:60` 字面含等号破坏连续链，布尔版）：
在完整连续无瞬移走势链上，前中枢 `c1` 经 `020:60` 字面含等号第三类离开-回试破坏（`retest.lo ≥ c1.zg` 或 `retest.hi ≤ c1.zd`）后紧接形成新同级中枢 `c2`（`bridgeSegs = [leaveSeg]` 时 `c2Seg1` 即首次回试段，`bridgeSegs = [leaveSeg, retestSeg]` 时 `retestSeg` 结束于第三类买卖点并紧接 `c2` 三段）。
引文：[020:58]「缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。」
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」 -/
def b38_validLiteralDestructionChainBool (tr : B38SequentialCentersTrace) : Bool :=
  let c1Core : CenterCore := { zd := tr.c1.zd, zg := tr.c1.zg }
  b38_baseChainValidBool tr &&
  match tr.bridgeSegs with
  | [leaveSeg] =>
    (decide (b3_validUpLeaveAndFirstRetest c1Core leaveSeg tr.c2Seg1) &&
     decide (tr.c2Seg1.lo ≥ tr.c1.zg)) ||
    (decide (b3_validDownLeaveAndFirstRetest c1Core leaveSeg tr.c2Seg1) &&
     decide (tr.c2Seg1.hi ≤ tr.c1.zd))
  | [leaveSeg, retestSeg] =>
    (!decide (b2_tripleCommonOverlap retestSeg.toRange tr.c2Seg1.toRange tr.c2Seg2.toRange)) &&
    ((decide (b3_validUpLeaveAndFirstRetest c1Core leaveSeg retestSeg) &&
      decide (retestSeg.lo ≥ tr.c1.zg)) ||
     (decide (b3_validDownLeaveAndFirstRetest c1Core leaveSeg retestSeg) &&
      decide (retestSeg.hi ≤ tr.c1.zd)))
  | _ => false

/-- B-38 前提一（同课 `020:58` + `020:60` 字面含等号破坏连续链，`Prop` 版）。
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」 -/
def b38_validLiteralDestructionChain (tr : B38SequentialCentersTrace) : Prop :=
  b38_validLiteralDestructionChainBool tr = true

/-- `b38_validLiteralDestructionChain` 的可判定实例。 -/
instance instDecidableB38ValidLiteralDestructionChain (tr : B38SequentialCentersTrace) :
    Decidable (b38_validLiteralDestructionChain tr) :=
  inferInstanceAs (Decidable (b38_validLiteralDestructionChainBool tr = true))

/-- B-38 前提二（`054:24` 严格不触核破坏 + 无缺口无倒灌连续链，布尔版）：
在上述基础上收紧回试为严格不触核（`> c1.zg` 或 `< c1.zd`），且三买直连新中枢时 `c2Seg1` 亦不内部倒灌回原核；用于精确标定 `020:58` 三分支得以穷尽所隐含的额外边界条件。
引文：[018:64]「某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。」
引文：[054:24]「当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。」 -/
def b38_validStrictDestructionChainBool (tr : B38SequentialCentersTrace) : Bool :=
  let c1Core : CenterCore := { zd := tr.c1.zd, zg := tr.c1.zg }
  b38_baseChainValidBool tr &&
  match tr.bridgeSegs with
  | [leaveSeg] =>
    (decide (b3_validUpLeaveAndFirstRetest c1Core leaveSeg tr.c2Seg1) &&
     decide (tr.c2Seg1.lo > tr.c1.zg)) ||
    (decide (b3_validDownLeaveAndFirstRetest c1Core leaveSeg tr.c2Seg1) &&
     decide (tr.c2Seg1.hi < tr.c1.zd))
  | [leaveSeg, retestSeg] =>
    (!decide (b2_tripleCommonOverlap retestSeg.toRange tr.c2Seg1.toRange tr.c2Seg2.toRange)) &&
    ((decide (b3_validUpLeaveAndFirstRetest c1Core leaveSeg retestSeg) &&
      decide (retestSeg.lo > tr.c1.zg) &&
      decide (tr.c2Seg1.lo > tr.c1.zg)) ||
     (decide (b3_validDownLeaveAndFirstRetest c1Core leaveSeg retestSeg) &&
      decide (retestSeg.hi < tr.c1.zd) &&
      decide (tr.c2Seg1.hi < tr.c1.zd)))
  | _ => false

/-- B-38 前提二（`054:24` 严格不触核破坏 + 无缺口无倒灌连续链，`Prop` 版）。
引文：[054:24]「当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。」 -/
def b38_validStrictDestructionChain (tr : B38SequentialCentersTrace) : Prop :=
  b38_validStrictDestructionChainBool tr = true

/-- `b38_validStrictDestructionChain` 的可判定实例。 -/
instance instDecidableB38ValidStrictDestructionChain (tr : B38SequentialCentersTrace) :
    Decidable (b38_validStrictDestructionChain tr) :=
  inferInstanceAs (Decidable (b38_validStrictDestructionChainBool tr = true))

/-- 检查衔接段列表 `segs` 内部不存在任何连续三段公共重叠（防止在同级别分解中把一个完整中枢塞进 `bridgeSegs` 而跳过中间中枢）。
引文：[038:26]「因此，完全合理、不违反任何理论原则的，可以制定出这样的同级别分解规则：在某级别中，不定义中枢延伸，允许该级别上的盘整+盘整连接；与此同时，规定该级别以下的所有级别，都允许中枢延伸，不允许盘整+盘整连接；至于该级别以上级别，根本不考虑，因为所有走势都按该级别给分解了。」 -/
def b38_hasNoTripleOverlapBool : List DirectedSeg → Bool
  | s1 :: s2 :: s3 :: rest =>
    (!decide (b2_tripleCommonOverlap s1.toRange s2.toRange s3.toRange)) &&
    b38_hasNoTripleOverlapBool (s2 :: s3 :: rest)
  | _ => true

/-- B-38 前提三（`038:26` 同级别分解相邻两同级中枢链，布尔版）：在完整连续无瞬移走势链上，允许盘整+盘整六段直连（`bridgeSegs = []`，对应 `038:22`）或经不含独立三段中枢的连接段相连（`b38_hasNoTripleOverlapBool tr.bridgeSegs`，禁止跳过中间完整中枢）。
引文：[038:26]「因此，完全合理、不违反任何理论原则的，可以制定出这样的同级别分解规则：在某级别中，不定义中枢延伸，允许该级别上的盘整+盘整连接；与此同时，规定该级别以下的所有级别，都允许中枢延伸，不允许盘整+盘整连接；至于该级别以上级别，根本不考虑，因为所有走势都按该级别给分解了。」 -/
def b38_validSameLevelDecompChainBool (tr : B38SequentialCentersTrace) : Bool :=
  b38_baseChainValidBool tr && b38_hasNoTripleOverlapBool tr.bridgeSegs

/-- B-38 前提三（`038:26` 同级别分解相邻两同级中枢链，`Prop` 版）。
引文：[038:26]「因此，完全合理、不违反任何理论原则的，可以制定出这样的同级别分解规则：在某级别中，不定义中枢延伸，允许该级别上的盘整+盘整连接；与此同时，规定该级别以下的所有级别，都允许中枢延伸，不允许盘整+盘整连接；至于该级别以上级别，根本不考虑，因为所有走势都按该级别给分解了。」 -/
def b38_validSameLevelDecompChain (tr : B38SequentialCentersTrace) : Prop :=
  b38_validSameLevelDecompChainBool tr = true

/-- `b38_validSameLevelDecompChain` 的可判定实例。 -/
instance instDecidableB38ValidSameLevelDecompChain (tr : B38SequentialCentersTrace) :
    Decidable (b38_validSameLevelDecompChain tr) :=
  inferInstanceAs (Decidable (b38_validSameLevelDecompChainBool tr = true))

/-- `020:58` 分支一（下跌及其延续）：后 `GG <` 前 `DD`。
引文：[020:58]「缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。」 -/
def b38_centerRelDownLiteral (c1 c2 : CenterMetrics) : Prop :=
  c2.gg < c1.dd

/-- `b38_centerRelDownLiteral` 的可判定实例。 -/
instance instDecidableB38CenterRelDownLiteral (c1 c2 : CenterMetrics) :
    Decidable (b38_centerRelDownLiteral c1 c2) :=
  inferInstanceAs (Decidable (c2.gg < c1.dd))

/-- `020:58` 分支二（上涨及其延续）：后 `DD >` 前 `GG`。
引文：[020:58]「缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。」 -/
def b38_centerRelUpLiteral (c1 c2 : CenterMetrics) : Prop :=
  c2.dd > c1.gg

/-- `b38_centerRelUpLiteral` 的可判定实例。 -/
instance instDecidableB38CenterRelUpLiteral (c1 c2 : CenterMetrics) :
    Decidable (b38_centerRelUpLiteral c1 c2) :=
  inferInstanceAs (Decidable (c2.dd > c1.gg))

/-- `020:58` 分支三（形成高级别中枢）：`(后ZG < 前ZD ∧ 后GG ≥ 前DD) ∨ (后ZD > 前ZG ∧ 后DD ≤ 前GG)`。
引文：[020:58]「缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。」 -/
def b38_centerRelHigherLiteral (c1 c2 : CenterMetrics) : Prop :=
  (c2.zg < c1.zd ∧ c2.gg ≥ c1.dd) ∨ (c2.zd > c1.zg ∧ c2.dd ≤ c1.gg)

/-- `b38_centerRelHigherLiteral` 的可判定实例。 -/
instance instDecidableB38CenterRelHigherLiteral (c1 c2 : CenterMetrics) :
    Decidable (b38_centerRelHigherLiteral c1 c2) :=
  inferInstanceAs (Decidable (
    (c2.zg < c1.zd ∧ c2.gg ≥ c1.dd) ∨ (c2.zd > c1.zg ∧ c2.dd ≤ c1.gg)))

/-- B-38 字面分类穷尽性断言（同课 `020:58` + `020:60` 字面破坏连续链）：在绑定同一条无瞬移连续走势链且按 `020:52` 同向 `Z` 段重算指标的前提下，`020:58` 三分支覆盖所有 `020:60` 字面破坏后新成的同级中枢。
所刻画确切命题：即便杜绝瞬移并严格按 `020:52` 同向 `Z` 段重算四指标，在同课 `020:60` 含等号字面第三类破坏下仍存在连续链（如 `c1=[10,20]` 经 `10→30→20→25→18` 得 `c2.zd = 20 = c1.zg`）使三分支全不覆盖。
引文：[020:58]「缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。」
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」 -/
def b38_centerTheorem2ExhaustiveLiteral : Prop :=
  ∀ tr : B38SequentialCentersTrace,
    b38_validLiteralDestructionChain tr →
    b38_centerRelDownLiteral tr.c1 tr.c2 ∨
    b38_centerRelUpLiteral tr.c1 tr.c2 ∨
    b38_centerRelHigherLiteral tr.c1 tr.c2

/-- B-38 同级别分解连贯链分类穷尽性断言（`038:26`）：在允许盘整+盘整连续衔接的同级别分解连续链上，`020:58` 三分支覆盖所有前后同级两中枢（核心可真重叠而不落任一分支）。
引文：[038:26]「因此，完全合理、不违反任何理论原则的，可以制定出这样的同级别分解规则：在某级别中，不定义中枢延伸，允许该级别上的盘整+盘整连接；与此同时，规定该级别以下的所有级别，都允许中枢延伸，不允许盘整+盘整连接；至于该级别以上级别，根本不考虑，因为所有走势都按该级别给分解了。」 -/
def b38_centerTheorem2ExhaustiveSameLevelDecompLiteral : Prop :=
  ∀ tr : B38SequentialCentersTrace,
    b38_validSameLevelDecompChain tr →
    b38_centerRelDownLiteral tr.c1 tr.c2 ∨
    b38_centerRelUpLiteral tr.c1 tr.c2 ∨
    b38_centerRelHigherLiteral tr.c1 tr.c2

/-- B-38 严格无缺口破坏边界命题（待下游证成 `020:58` 的隐含边界条件）：当收紧为 `054:24` 严格不触核破坏且无缺口无倒灌连续演进至首个后枢时，`020:58` 三分支穷尽成立。
引文：[020:58]「缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。」 -/
def b38_centerTheorem2ExhaustiveStrictGaplessBoundary : Prop :=
  ∀ tr : B38SequentialCentersTrace,
    b38_validStrictDestructionChain tr →
    b38_centerRelDownLiteral tr.c1 tr.c2 ∨
    b38_centerRelUpLiteral tr.c1 tr.c2 ∨
    b38_centerRelHigherLiteral tr.c1 tr.c2

end Chan.Audit.Literal
