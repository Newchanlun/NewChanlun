module

public import Chan.Defs.Base.Pen

@[expose] public section

namespace Chan.Defs.Base

open Chan.Defs.Order Chan.Defs.Alt

variable {P : Type _} [LinearOrder P]

/-- 分歧一的处置口径：第一种情况下假设转折点后的确认条件。
`thirdPenBreaksFirst`（主线，正文）：此后先出现越过第一笔结束位置的同向笔则成立，先越过转折点则不成立；
`anyThreePens`（答疑口径）：转折点后走满三笔且未越过转折点即成立。
[071:30] 从上面的分析就可以知道，从转折点开始，如果第一笔就破坏了前线段，进而该笔延伸出三笔来，其中第三笔破点第一笔的结束位置，那么，新的线段一定形成，前线段一定结束。
[071:32] 这种情况还有更复杂一点的情况，就是第三笔完全在第一笔的范围内，这样，这三笔就分不出是向上还是向下，这样也就定义不了什么特征序列，为什么？因为特征序列是和走势相反的，而走势连方向都没有，那怎么知道哪个元素属于特征序列？这种情况，无非两种最后的结果：1、最终还是先破了第一笔的结束位置，这时候，新的线段显然成立，旧线段还是被破坏了；2、最终，先破第一笔的开始位置，这样，旧线段只被一笔破坏，接着就延续原来的方向，那么，显然旧线段依然延续，新线段没有出现。
[二级旁证 067:194] ==还是没搞清楚，这里是第一种情况，不存在特征序列的缺口，这种情况，任何三笔其实都构成对前面线段的破坏。 -/
inductive BreakConfirmRule where
  | thirdPenBreaksFirst
  | anyThreePens
  deriving DecidableEq

/-- 分歧二的处置口径：假设转折点的选取。
`eachTurningPoint`（主线，正文）：无在审假设时，第三笔起每个同向笔终点都依次作为假设转折点；
`extremeVertex`（答疑口径）：只有创出本段新极值的同向笔终点才作为待破坏顶点。
[071:38] 其实，线段的划分，都是可以当下完成的，无非是如下的程序：假设某转折点是两线段的分界点，然后对此用线段划分的两种情况去考察是否满足，如果满足其中一种，那么这点就是真正的线段的分界点；如果不满足，那就不是，原来的线段依然延续，就这么简单。
[二级旁证 081:222] 首先要选择原线段待破坏的顶点，这里显然是1，3还没1高，显然不构成待破坏的顶点。这样，5下来破坏了1，然后扩展成线段，那就是标准的第一种情况，和3没什么关系。 -/
inductive PivotRule where
  | eachTurningPoint
  | extremeVertex
  deriving DecidableEq

/-- 线段规则配置：显式固定两处答疑与正文冲突的处置口径。
[071:40] 特征序列的分型中，第一元素就是以该假设转折点前线段的最后一个特征元素，第二个元素，就是从这转折点开始的第一笔，显然，这两者之间是同方向的，因此，如果这两者之间有缺口，那么就是第二种情况，否则就是第一种，然后根据定义来考察就可以。 -/
structure SegRuleConfig where
  breakConfirm : BreakConfirmRule
  pivot : PivotRule
  deriving DecidableEq

/-- 主线配置：两处分歧均按正文写死。
[071:30] 从上面的分析就可以知道，从转折点开始，如果第一笔就破坏了前线段，进而该笔延伸出三笔来，其中第三笔破点第一笔的结束位置，那么，新的线段一定形成，前线段一定结束。
[071:38] 其实，线段的划分，都是可以当下完成的，无非是如下的程序：假设某转折点是两线段的分界点，然后对此用线段划分的两种情况去考察是否满足，如果满足其中一种，那么这点就是真正的线段的分界点；如果不满足，那就不是，原来的线段依然延续，就这么简单。 -/
def SegRuleConfig.main : SegRuleConfig := ⟨.thirdPenBreaksFirst, .eachTurningPoint⟩

/-- 特征序列元素：闭区间值域及其所归属的笔下标跨度（合并后为跨度之并）。
[067:18] 定义：序列X1X2…Xn成为以向上笔开始线段的特征序列；序列S1S2…Sn成为以向下笔开始线段的特征序列。特征序列两相邻元素间没有重合区间，称为该序列的一个缺口。 -/
structure FeatureElem (P : Type _) [LinearOrder P] where
  range : Bar P
  penSpan : Span
  deriving DecidableEq

/-- 提取方向为 `d` 的候选线段的特征序列：与 `d` 反向的笔，`i` 为首笔在笔序列中的下标。
[067:18] 定义：序列X1X2…Xn成为以向上笔开始线段的特征序列；序列S1S2…Sn成为以向下笔开始线段的特征序列。特征序列两相邻元素间没有重合区间，称为该序列的一个缺口。
[067:22] 注意，以向上笔开始的线段的特征序列，只考察顶分型；以向下笔开始的线段，只考察底分型。 -/
def featureSeq (d : Dir) : Nat → List (Pen P) → List (FeatureElem P)
  | _, [] => []
  | i, p :: ps =>
    if p.dir = d then featureSeq d (i + 1) ps
    else FeatureElem.mk p.range ⟨i, i, Nat.le_refl i⟩ :: featureSeq d (i + 1) ps

/-- 特征序列缺口：相邻两元素严格分离；端点相触不算缺口（分叉 4）。
[067:18] 定义：序列X1X2…Xn成为以向上笔开始线段的特征序列；序列S1S2…Sn成为以向下笔开始线段的特征序列。特征序列两相邻元素间没有重合区间，称为该序列的一个缺口。 -/
abbrev hasFeatureGap (a b : FeatureElem P) : Prop :=
  gapUp a.range b.range ∨ gapDown a.range b.range

/-- 标准化单步（累积表逆序）：与前一元素有包含关系则按方向 `d` 合并。
[067:20] 关于特征序列，把每一元素看成是一K线，那么，如同一般K线图中找分型的方法，也存在所谓的包含关系，也可以对此进行非包含处理。经过非包含处理的特征序列，成为标准特征序列。以后没有特别说明，特征序列都是指标准特征序列。 -/
def stdFeatureStep (d : Dir) (acc : List (FeatureElem P)) (x : FeatureElem P) : List (FeatureElem P) :=
  match acc with
  | [] => [x]
  | a :: rest =>
    if hasInclusion a.range x.range then
      FeatureElem.mk (mergePair d a.range x.range) (a.penSpan.join x.penSpan) :: rest
    else x :: a :: rest

/-- 标准特征序列：只在调用者给定的同一特征序列范围内，按方向 `d` 顺序作非包含处理
（向上线段的特征序列按向上规则，向下线段按向下规则）。
[067:20] 关于特征序列，把每一元素看成是一K线，那么，如同一般K线图中找分型的方法，也存在所谓的包含关系，也可以对此进行非包含处理。经过非包含处理的特征序列，成为标准特征序列。以后没有特别说明，特征序列都是指标准特征序列。
[071:18] 注意，特征序列的元素包含关系，首先的前提是这元素都在一特征序列里，如果两个不同的特征序列之间的元素，讨论包含关系是没意义的。 -/
def stdFeatureSeq (d : Dir) (xs : List (FeatureElem P)) : List (FeatureElem P) :=
  (xs.foldl (stdFeatureStep d) []).reverse

/-- 序列中是否存在相邻三元素构成 `e` 向分型（`up` 为顶分型，`down` 为底分型）。
[067:22] 注意，以向上笔开始的线段的特征序列，只考察顶分型；以向下笔开始的线段，只考察底分型。 -/
def hasFractalTriple (e : Dir) : List (FeatureElem P) → Bool
  | a :: tl@(b :: c :: _) =>
    (match e with
      | .up => decide (IsTopTriple a.range b.range c.range)
      | .down => decide (IsBottomTriple a.range b.range c.range)) || hasFractalTriple e tl
  | _ => false

/-- 区间在方向 `d` 上的极端价位：向上取高点，向下取低点。
[065:44] 如果找到i和j，j>=i+2,使得dj<=gi,那么称向上线段被笔破坏。
[065:46] 如果找到i和j，j>=i+2,使得gj>=di,那么称向下线段被笔破坏。 -/
def dirExt : Dir → Bar P → P
  | .up, b => b.hi
  | .down, b => b.lo

/-- 价位 `x` 在方向 `d` 上严格越过 `y`（严格突破，分叉 4）。
[065:44] 如果找到i和j，j>=i+2,使得dj<=gi,那么称向上线段被笔破坏。
[065:46] 如果找到i和j，j>=i+2,使得gj>=di,那么称向下线段被笔破坏。 -/
def dirBeyond : Dir → P → P → Bool
  | .up, x, y => decide (y < x)
  | .down, x, y => decide (x < y)

/-- 线段结束的两种情况：第一种（特征序列分型第一二元素间无缺口）与第二种（有缺口，待第二特征序列分型）。
[067:28] 特征序列的顶分型中，第一和第二元素间不存在特征序列的缺口，那么该线段在该顶分型的高点处结束，该高点是该线段的终点；特征序列的底分型中，第一和第二元素间不存在特征序列的缺口，那么该线段在该底分型的低点处结束，该低点是该线段的终点；
[067:38] 特征序列的顶分型中，第一和第二元素间存在特征序列的缺口，如果从该分型最高点开始的向下一笔开始的序列的特征序列出现底分型，那么该线段在该顶分型的高点处结束，该高点是该线段的终点；特征序列的底分型中，第一和第二元素间存在特征序列的缺口，如果从该分型最低点开始的向上一笔开始的序列的特征序列出现顶分型，那么该线段在该底分型的低点处结束，该低点是该线段的终点； -/
inductive SegTermKind where
  | firstCase
  | secondCase
  deriving DecidableEq

/-- 线段：至少三笔、笔数为奇数且前三笔有闭区间公共交；保留全部所辖笔值域的实际凸包区间、
原始 K 线跨度与起始笔下标，不强设端点等于极值；`term` 为结束情况（未完成尾段为 `none`）。
[065:48] 线段有一个最基本的前提，就是线段的前三笔，必须有重叠的部分，这个前提在前面可能没有特别强调，这里必须特别强调一次。线段至少有三笔，但并不是连续的三笔就一定构成线段，这三笔必须有重叠的部分。
[077:62] 也就是说，和笔一样，线段也不可能从一个顶开始结束于一个顶，或者从一个底开始结束于一个底。由此可见，线段中包含笔的数目，都是单数的。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。 -/
structure Segment (P : Type _) [LinearOrder P] where
  dir : Dir
  startPen : Nat
  pens : List (Pen P)
  range : Bar P
  rawSpan : Span
  term : Option SegTermKind
  three : 3 ≤ pens.length
  odd : pens.length % 2 = 1
  overlap3 : overlapsList? ((pens.take 3).map Pen.range)
  deriving DecidableEq

/-- 检查并构造线段：不满足至少三笔、奇数笔或前三笔重叠时返回 `none`。
[065:48] 线段有一个最基本的前提，就是线段的前三笔，必须有重叠的部分，这个前提在前面可能没有特别强调，这里必须特别强调一次。线段至少有三笔，但并不是连续的三笔就一定构成线段，这三笔必须有重叠的部分。 -/
def Segment.mk? (d : Dir) (start : Nat) (ps : List (Pen P)) (term : Option SegTermKind) :
    Option (Segment P) :=
  match ps with
  | [] => none
  | p :: qs =>
    if h : 3 ≤ (p :: qs).length ∧ (p :: qs).length % 2 = 1 ∧
        overlapsList? (((p :: qs).take 3).map Pen.range) then
      some ⟨d, start, p :: qs, hullInterval p.range (qs.map Pen.range),
        qs.foldl (fun s q => s.join q.rawSpan) p.rawSpan, term, h.1, h.2.1, h.2.2⟩
    else none

/-- 线段作为方向交替区间序列中的一段：方向、实际凸包区间、原始跨度。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。 -/
def Segment.toSeg (s : Segment P) : Seg P :=
  ⟨s.dir, s.range, s.rawSpan⟩

/-- 线段扫描中的在审假设：`idle` 无假设；`awaitE2 t tx` 已假设第 `t` 笔终点（价位 `tx`）为转折点、
待转折点后第一笔；`caseOne t tx th` 第一种情况待确认，`th` 为转折点后第一笔的结束价位；
`caseTwo t tx sec` 第二种情况待第二特征序列分型，`sec` 为已收集的第二特征序列元素。
[071:42] 这里还要强调一下包含的问题，上面的分析知道，在这假设的转折点前后那两元素，是不存在包含关系的。因为，这两者已经被假设不是同一性质的东西，不一定是同一特征序列的；但假设的转折点后的顶分型的元素，是可以应用包含关系的。为什么？因此，这些元素间，肯定是同一性质的东西，或者就是原线段的延续，那么就同是原线段的特征序列中，或者就是新线段的非特征序列中，反正都是同一类的东西，同一类的东西，当然可以考察包含关系。 -/
inductive SegHyp (P : Type _) [LinearOrder P] where
  | idle
  | awaitE2 (t : Nat) (tx : P)
  | caseOne (t : Nat) (tx th : P)
  | caseTwo (t : Nat) (tx : P) (sec : List (FeatureElem P))

/-- 单段扫描结果：在第 `t` 笔（相对下标）终点结束；起点被反向越过而作废；或笔序列耗尽仍未结束。
[067:48] 上面两种情况，就给出所有线段划分的标准。显然，出现特征序列的分型，是线段结束的前提条件。本课，就是把前面“线段破坏的充要条件就是被另一个线段破坏”精确化了。因此，以后关于线段的划分，都以此精确的定义为基础。 -/
inductive SegScanResult where
  | ended (t : Nat) (kind : SegTermKind)
  | voided
  | unfinished
  deriving DecidableEq

/-- 单段确定性扫描（方向 `d`，起点价位 `origin`，参数依次为相对下标、本段已见极值、已见特征元素、在审假设）。
同向笔：越过在审转折点即撤销该假设（旧段延续），并按 `PivotRule` 设立新假设；第二种情况下同向笔并入
第二特征序列并按反方向严格包含处理后找反向分型。反向笔：紧接转折点的第一笔与此前标准特征序列末元素
比较，须在方向 `d` 上更极端才构成特征序列分型候选，再按有无缺口分第一、二种情况；转折点前后两元素之间
不作包含处理。第一种情况按 `BreakConfirmRule` 确认。无在审假设时反向笔严格越过起点则本起点作废。
[071:40] 特征序列的分型中，第一元素就是以该假设转折点前线段的最后一个特征元素，第二个元素，就是从这转折点开始的第一笔，显然，这两者之间是同方向的，因此，如果这两者之间有缺口，那么就是第二种情况，否则就是第一种，然后根据定义来考察就可以。
[067:46] 强调，在第二种情况下，后一特征序列不一定封闭前一特征序列相应的缺口，而且，第二个序列中的分型，不分第一二种情况，只要有分型就可以。
[078:52] 从这个例子就知道，笔破坏与线段破坏的异同。对于线段破坏的第二种情况，例如线段B对线段A是第二种情况，而线段C没有形成第二特征序列的分型又直接新高或新低了，这时候，不能认为这是三个线段，线段A、B、C加起来只能算是一个线段。
[078:54] 另外，一定要注意，对于第二种情况的第二特征序列的分型判断，必须严格按照包含关系的处理来，这里不存在第一种情况中的假设分界点两边不能进行包含关系处理的要求。为什么？因为在第一种情况中，如果分界点两边出现特征序列的包含关系，那证明对原线段转折的力度特别大，那当然不能用包含关系破坏这种力度的呈现。而在第二种情况的第二特征序列中，其方向是和原线段一致，包含关系的出现，就意味着原线段的能量充足，而第二种情况，本来就意味着对原线段转折的能量不足，这样一来，当然就必须按照包含关系来。 -/
def segScan (cfg : SegRuleConfig) (d : Dir) (origin : P) :
    Nat → Option P → List (FeatureElem P) → SegHyp P → List (Pen P) → SegScanResult
  | _, _, _, _, [] => .unfinished
  | i, segExt, feats, hyp, p :: ps =>
    let fe : FeatureElem P := ⟨p.range, ⟨i, i, Nat.le_refl i⟩⟩
    if p.dir = d then
      let x := dirExt d p.range
      let isNewExt : Bool := match segExt with
        | none => true
        | some e => dirBeyond d x e
      let segExt' : Option P := if isNewExt then some x else segExt
      let fresh : SegHyp P :=
        if 2 ≤ i ∧ (cfg.pivot = .eachTurningPoint ∨ isNewExt = true) then .awaitE2 i x else .idle
      match hyp with
      | .caseOne t tx th =>
        if dirBeyond d x tx then segScan cfg d origin (i + 1) segExt' feats fresh ps
        else segScan cfg d origin (i + 1) segExt' feats (.caseOne t tx th) ps
      | .caseTwo t tx sec =>
        if dirBeyond d x tx then segScan cfg d origin (i + 1) segExt' feats fresh ps
        else
          let sec' := sec ++ [fe]
          if hasFractalTriple d.flip (stdFeatureSeq d.flip sec') then .ended t .secondCase
          else segScan cfg d origin (i + 1) segExt' feats (.caseTwo t tx sec') ps
      | _ => segScan cfg d origin (i + 1) segExt' feats fresh ps
    else
      let feats' := feats ++ [fe]
      match hyp with
      | .awaitE2 t tx =>
        match (stdFeatureSeq d feats).getLast? with
        | some e1 =>
          if dirBeyond d (dirExt d p.range) (dirExt d e1.range) then
            if hasFeatureGap e1 fe then
              segScan cfg d origin (i + 1) segExt feats' (.caseTwo t tx []) ps
            else
              segScan cfg d origin (i + 1) segExt feats' (.caseOne t tx (dirExt d.flip p.range)) ps
          else if dirBeyond d.flip (dirExt d.flip p.range) origin then .voided
          else segScan cfg d origin (i + 1) segExt feats' .idle ps
        | none => segScan cfg d origin (i + 1) segExt feats' .idle ps
      | .caseOne t tx th =>
        match cfg.breakConfirm with
        | .anyThreePens => .ended t .firstCase
        | .thirdPenBreaksFirst =>
          if dirBeyond d.flip (dirExt d.flip p.range) th then .ended t .firstCase
          else segScan cfg d origin (i + 1) segExt feats' (.caseOne t tx th) ps
      | .caseTwo .. => segScan cfg d origin (i + 1) segExt feats' hyp ps
      | .idle =>
        if dirBeyond d.flip (dirExt d.flip p.range) origin then .voided
        else segScan cfg d origin (i + 1) segExt feats' .idle ps

/-- 不超过 `n` 的最大奇数（`n = 0` 时为 0）：未完成尾段截至最后一根与首笔同向的笔。
[077:62] 也就是说，和笔一样，线段也不可能从一个顶开始结束于一个顶，或者从一个底开始结束于一个底。由此可见，线段中包含笔的数目，都是单数的。 -/
def oddPrefixLen (n : Nat) : Nat :=
  if n % 2 = 1 then n else n - 1

/-- 线段划分主循环（燃料为步数上界，`start` 为当前起始笔下标）：本段结束后自转折点后第一笔起划下一段；
起点作废或成段条件不满足时起点后移一笔；笔序列耗尽时输出满足成段条件的未完成尾段。
[079:58] 其实，明白了上几节课，这两个图一定都不难分辨，首先，前提是这两个的前面都没有其他走势了，否则这种分析没意义，前面有其他走势，就有这很多不同的可能变化。 -/
def segLoop (cfg : SegRuleConfig) (pens : List (Pen P)) : Nat → Nat → List (Segment P)
  | 0, _ => []
  | fuel + 1, start =>
    match pens.drop start with
    | [] => []
    | p :: qs =>
      match segScan cfg p.dir (dirExt p.dir.flip p.range) 0 none [] .idle (p :: qs) with
      | .ended t k =>
        match Segment.mk? p.dir start ((p :: qs).take (t + 1)) (some k) with
        | some s => s :: segLoop cfg pens fuel (start + t + 1)
        | none => segLoop cfg pens fuel (start + 1)
      | .voided => segLoop cfg pens fuel (start + 1)
      | .unfinished =>
        match Segment.mk? p.dir start ((p :: qs).take (oddPrefixLen (p :: qs).length)) none with
        | some s => [s]
        | none => segLoop cfg pens fuel (start + 1)

/-- 以笔序列与起始笔下标为输入的线段列表（划分结果依赖起点）。
[079:58] 其实，明白了上几节课，这两个图一定都不难分辨，首先，前提是这两个的前面都没有其他走势了，否则这种分析没意义，前面有其他走势，就有这很多不同的可能变化。 -/
def parseSegmentList (cfg : SegRuleConfig) (pens : List (Pen P)) (start : Nat) : List (Segment P) :=
  segLoop cfg pens (pens.length + 1) start

/-- 确定性线段划分：输出方向交替区间序列，每段保留实际凸包区间与原始跨度。
[067:52] 显然，按照这个划分，一切同一级别图上的走势都可以唯一地划分为线段的连接，正如一切同一级别图上的走势都可以唯一地划分笔的连接。有了这两个基础，那么整个中枢与走势类型的递归体系就可以建立起来。这是基础的基础，请务必搞清楚，否则肯定学不好。
[079:58] 其实，明白了上几节课，这两个图一定都不难分辨，首先，前提是这两个的前面都没有其他走势了，否则这种分析没意义，前面有其他走势，就有这很多不同的可能变化。 -/
def parseSegments (cfg : SegRuleConfig) (pens : List (Pen P)) (start : Nat) : AltSeq P :=
  altSeqOfSegs ((parseSegmentList cfg pens start).map Segment.toSeg)

/-- 标准化视图：把线段高低极值放到端点，返回（起点价位，终点价位）；向上段自最低到最高，向下段反之。
[078:58] 注意，这里必须提醒一句，就是这在以前也曾说过，就是，如果线段中，最高或最低点不是线段的端点，那么，在任何以线段为基础的分析中，例如把线段为基础构成最小级别的中枢等，都可以把该线段标准化为最高低点都在端点。因为，在以线段为基础的分析中，都把线段当成一个没有内部结构的基本部件，所以，只需要关心这线段的实际区间就可以，这样就可以只看其高低点。
[078:60] 经过标准化处理后，所有向上线段都是以最低点开始最高点结束，向下线段都是以最高点开始最低点结束，这样，所以线段的连接，就形成一条延续不断、首尾相连的折线，这样，复杂的图形，就会十分地标准化，也为后面的中枢、走势类型等分析提供了最标准且基础的部件。 -/
def standardizeSegment (s : Segment P) : P × P :=
  match s.dir with
  | .up => (s.range.lo, s.range.hi)
  | .down => (s.range.hi, s.range.lo)

/-- 实际端点：首笔起点价位与末笔终点价位，可不等于段内极值（与标准化视图对照）。
[078:42] 这种情况下，如果那向上笔突破线段B的高点，这时候就会出现，线段的开始点并不是最高点的情况。
[078:20] 同样，正如同一笔不可能出现顶低于底的情况，同一线段中，两端的一顶一底，顶肯定要高于底，如果你划出一个不符合这基本要求的线段，那肯定是划错了。 -/
def Segment.actualEndpoints (s : Segment P) : Option (P × P) :=
  match s.pens.head?, s.pens.getLast? with
  | some a, some b => some (a.startPrice, b.endPrice)
  | _, _ => none

end Chan.Defs.Base
