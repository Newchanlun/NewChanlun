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

/-- 笔下标用原笔列的坐标；合并后保留首末归属笔。
[067:16] 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。 -/
structure FeatureElem (P : Type _) [LinearOrder P] where
  range : Bar P
  penSpan : Span
  deriving DecidableEq

/-- 按原顺序提取与候选段相反的笔；偏移量给出输入切片首笔的位置。
[067:18] 定义：序列X1X2…Xn成为以向上笔开始线段的特征序列；序列S1S2…Sn成为以向下笔开始线段的特征序列。特征序列两相邻元素间没有重合区间，称为该序列的一个缺口。 -/
def featureSeq (d : Dir) (pens : List (Pen P)) (offset : Nat := 0) : List (FeatureElem P) :=
  (pens.zipIdx offset).filterMap fun (p, i) =>
    if p.dir ≠ d then some ⟨p.range, ⟨i, i, Nat.le_refl _⟩⟩ else none

/-- 严格分离才有缺口；两个闭区间只碰到一点也没有缺口。
[067:18] 定义：序列X1X2…Xn成为以向上笔开始线段的特征序列；序列S1S2…Sn成为以向下笔开始线段的特征序列。特征序列两相邻元素间没有重合区间，称为该序列的一个缺口。 -/
abbrev hasFeatureGap (a b : FeatureElem P) : Prop :=
  gapUp a.range b.range ∨ gapDown a.range b.range

/-- 在同一侧按固定段方向合并；合并所得区间继续和栈顶比较，直到相邻无包含。
[067:20] 关于特征序列，把每一元素看成是一K线，那么，如同一般K线图中找分型的方法，也存在所谓的包含关系，也可以对此进行非包含处理。经过非包含处理的特征序列，成为标准特征序列。以后没有特别说明，特征序列都是指标准特征序列。 -/
def pushFeature (d : Dir) (e : FeatureElem P) : List (FeatureElem P) → List (FeatureElem P)
  | [] => [e]
  | a :: rest =>
    if hasInclusion a.range e.range then
      let toBar := fun (x : FeatureElem P) =>
        MergedBar.mk x.range x.penSpan x.penSpan.first x.penSpan.first
      let m := mergePair d (toBar a) (toBar e)
      pushFeature d ⟨m.range, m.source⟩ rest
    else e :: a :: rest

/-- 标准化一个同侧特征列。有假设分界时，两侧分别处理，绝不跨界合并；
第二特征列不传分界，故按通常规则处理全列。
[071:42] 这里还要强调一下包含的问题，上面的分析知道，在这假设的转折点前后那两元素，是不存在包含关系的。因为，这两者已经被假设不是同一性质的东西，不一定是同一特征序列的；但假设的转折点后的顶分型的元素，是可以应用包含关系的。为什么？因此，这些元素间，肯定是同一性质的东西，或者就是原线段的延续，那么就同是原线段的特征序列中，或者就是新线段的非特征序列中，反正都是同一类的东西，同一类的东西，当然可以考察包含关系。
[078:54] 另外，一定要注意，对于第二种情况的第二特征序列的分型判断，必须严格按照包含关系的处理来，这里不存在第一种情况中的假设分界点两边不能进行包含关系处理的要求。为什么？因为在第一种情况中，如果分界点两边出现特征序列的包含关系，那证明对原线段转折的力度特别大，那当然不能用包含关系破坏这种力度的呈现。而在第二种情况的第二特征序列中，其方向是和原线段一致，包含关系的出现，就意味着原线段的能量充足，而第二种情况，本来就意味着对原线段转折的能量不足，这样一来，当然就必须按照包含关系来。 -/
def stdFeatureSeq (d : Dir) (xs : List (FeatureElem P)) (boundary : Option Nat := none) :
    List (FeatureElem P) :=
  let norm := fun (ys : List (FeatureElem P)) =>
    (ys.foldl (fun stack e => pushFeature d e stack) []).reverse
  match boundary with
  | none => norm xs
  | some i => norm (xs.takeWhile (·.penSpan.first < i)) ++ norm (xs.dropWhile (·.penSpan.first < i))

/-- 按前段末特征与转折后首笔之间是否有缺口区分确认依据。
[067:28] 特征序列的顶分型中，第一和第二元素间不存在特征序列的缺口，那么该线段在该顶分型的高点处结束，该高点是该线段的终点；特征序列的底分型中，第一和第二元素间不存在特征序列的缺口，那么该线段在该底分型的低点处结束，该低点是该线段的终点；
[067:38] 特征序列的顶分型中，第一和第二元素间存在特征序列的缺口，如果从该分型最高点开始的向下一笔开始的序列的特征序列出现底分型，那么该线段在该顶分型的高点处结束，该高点是该线段的终点；特征序列的底分型中，第一和第二元素间存在特征序列的缺口，如果从该分型最低点开始的向上一笔开始的序列的特征序列出现顶分型，那么该线段在该底分型的低点处结束，该低点是该线段的终点； -/
inductive SegTermKind where
  | noGap | secondFractal
  deriving DecidableEq

/-- 给定方向上的严格突破。与闭区间相交的等号规则不同。
[071:32] 这种情况还有更复杂一点的情况，就是第三笔完全在第一笔的范围内，这样，这三笔就分不出是向上还是向下，这样也就定义不了什么特征序列，为什么？因为特征序列是和走势相反的，而走势连方向都没有，那怎么知道哪个元素属于特征序列？这种情况，无非两种最后的结果：1、最终还是先破了第一笔的结束位置，这时候，新的线段显然成立，旧线段还是被破坏了；2、最终，先破第一笔的开始位置，这样，旧线段只被一笔破坏，接着就延续原来的方向，那么，显然旧线段依然延续，新线段没有出现。 -/
def advances (d : Dir) (a b : P) : Bool := if d = .up then a < b else b < a

/-- 同一标准特征列上，向上段找顶，向下段找底；输入栈最新项在前。
[067:22] 注意，以向上笔开始的线段的特征序列，只考察顶分型；以向下笔开始的线段，只考察底分型。 -/
def recentFeatureTurn (d : Dir) : List (FeatureElem P) → Bool
  | c :: b :: a :: _ =>
    classifyTriple a.range b.range c.range = some (if d = .up then .top else .bottom)
  | _ => false

/-- 两个栈从假设转折点之后开始，互不混用。先创原方向新极值便撤回候选；
有缺口时逐笔观察第二列的反向分型，不要求回补。无缺口时，第三笔内包
就继续等，先破首笔终点才确认，先破其起点则延续原段。
[071:32] 这种情况还有更复杂一点的情况，就是第三笔完全在第一笔的范围内，这样，这三笔就分不出是向上还是向下，这样也就定义不了什么特征序列，为什么？因为特征序列是和走势相反的，而走势连方向都没有，那怎么知道哪个元素属于特征序列？这种情况，无非两种最后的结果：1、最终还是先破了第一笔的结束位置，这时候，新的线段显然成立，旧线段还是被破坏了；2、最终，先破第一笔的开始位置，这样，旧线段只被一笔破坏，接着就延续原来的方向，那么，显然旧线段依然延续，新线段没有出现。
[067:46] 强调，在第二种情况下，后一特征序列不一定封闭前一特征序列相应的缺口，而且，第二个序列中的分型，不分第一二种情况，只要有分型就可以。
[078:52] 从这个例子就知道，笔破坏与线段破坏的异同。对于线段破坏的第二种情况，例如线段B对线段A是第二种情况，而线段C没有形成第二特征序列的分型又直接新高或新低了，这时候，不能认为这是三个线段，线段A、B、C加起来只能算是一个线段。
[078:54] 另外，一定要注意，对于第二种情况的第二特征序列的分型判断，必须严格按照包含关系的处理来，这里不存在第一种情况中的假设分界点两边不能进行包含关系处理的要求。为什么？因为在第一种情况中，如果分界点两边出现特征序列的包含关系，那证明对原线段转折的力度特别大，那当然不能用包含关系破坏这种力度的呈现。而在第二种情况的第二特征序列中，其方向是和原线段一致，包含关系的出现，就意味着原线段的能量充足，而第二种情况，本来就意味着对原线段转折的能量不足，这样一来，当然就必须按照包含关系来。 -/
def observeBreak (d : Dir) (kind : SegTermKind) (tip base : P) (i : Nat)
    (sameSide second : List (FeatureElem P)) (firstTurn secondTurn : Bool) :
    List (Pen P) → Option SegTermKind
  | [] => none
  | p :: ps =>
    let price := p.stop.pivot.extreme
    let e : FeatureElem P := ⟨p.range, ⟨i, i, Nat.le_refl _⟩⟩
    if advances d tip price then none
    else
      let u := if p.dir ≠ d then pushFeature d e sameSide else sameSide
      let v := if p.dir = d then pushFeature d.flip e second else second
      -- 跨界的左邻已经单独检验。右邻及中心只使用转折点后同侧的标准化结果。
      let turned := firstTurn || (match u.reverse with
        | m :: r :: _ => if d = .up then m.range.strictDown r.range else m.range.strictUp r.range
        | _ => false)
      let counter := secondTurn || recentFeatureTurn d.flip v
      match kind with
      | .noGap =>
        if p.dir ≠ d && advances d.flip base price && (turned || p.start.pivot.extreme = tip)
        then some .noGap else observeBreak d kind tip base (i+1) u v turned counter ps
      | .secondFractal =>
        if turned && counter then some .secondFractal
        else observeBreak d kind tip base (i+1) u v turned counter ps

/-- 先隔开分界两侧，取旧段最后一个标准特征和新侧第一笔。无缺口时允许首笔
包含左邻（不消去转折）；有缺口时须向原段方向跳开，再检验两列分型。
[071:40] 特征序列的分型中，第一元素就是以该假设转折点前线段的最后一个特征元素，第二个元素，就是从这转折点开始的第一笔，显然，这两者之间是同方向的，因此，如果这两者之间有缺口，那么就是第二种情况，否则就是第一种，然后根据定义来考察就可以。
[071:42] 这里还要强调一下包含的问题，上面的分析知道，在这假设的转折点前后那两元素，是不存在包含关系的。因为，这两者已经被假设不是同一性质的东西，不一定是同一特征序列的；但假设的转折点后的顶分型的元素，是可以应用包含关系的。为什么？因此，这些元素间，肯定是同一性质的东西，或者就是原线段的延续，那么就同是原线段的特征序列中，或者就是新线段的非特征序列中，反正都是同一类的东西，同一类的东西，当然可以考察包含关系。
[067:38] 特征序列的顶分型中，第一和第二元素间存在特征序列的缺口，如果从该分型最高点开始的向下一笔开始的序列的特征序列出现底分型，那么该线段在该顶分型的高点处结束，该高点是该线段的终点；特征序列的底分型中，第一和第二元素间存在特征序列的缺口，如果从该分型最低点开始的向上一笔开始的序列的特征序列出现顶分型，那么该线段在该底分型的低点处结束，该低点是该线段的终点； -/
def segmentBreak (cfg : SegRuleConfig) (d : Dir) (before after : List (Pen P)) : Option SegTermKind :=
  match (stdFeatureSeq d (featureSeq d before)).getLast?, after with
  | some l, f :: s :: t :: rest =>
    if f.dir = d || s.dir ≠ d || t.dir = d || !decide (overlapsList f.range [s.range, t.range])
      then none
    else
      let tip := f.start.pivot.extreme
      let base := f.stop.pivot.extreme
      let leftTip := if d = .up then l.range.hi else l.range.lo
      if !advances d leftTip tip then none
      else
        let i := before.length
        let m : FeatureElem P := ⟨f.range, ⟨i, i, Nat.le_refl _⟩⟩
        let mode := if hasFeatureGap l m then SegTermKind.secondFractal else SegTermKind.noGap
        if mode = .noGap && cfg.breakConfirm = .anyThreePens then
          if advances d tip s.stop.pivot.extreme || advances d tip t.stop.pivot.extreme
          then none else some .noGap
        else observeBreak d mode tip base (i+1) [m] [] false false (s :: t :: rest)
  | _, _ => none

/-- 三笔共交、奇数笔、方向交替且相邻共端。记录起笔下标和确认方式；
无确认方式表示从指定起点已经形成、仍可能延伸的末段。
[065:48] 线段有一个最基本的前提，就是线段的前三笔，必须有重叠的部分，这个前提在前面可能没有特别强调，这里必须特别强调一次。线段至少有三笔，但并不是连续的三笔就一定构成线段，这三笔必须有重叠的部分。
[077:62] 也就是说，和笔一样，线段也不可能从一个顶开始结束于一个顶，或者从一个底开始结束于一个底。由此可见，线段中包含笔的数目，都是单数的。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。
[078:20] 同样，正如同一笔不可能出现顶低于底的情况，同一线段中，两端的一顶一底，顶肯定要高于底，如果你划出一个不符合这基本要求的线段，那肯定是划错了。 -/
structure Segment (P : Type _) [LinearOrder P] where
  firstPen : Nat
  a : Pen P
  b : Pen P
  c : Pen P
  more : List (Pen P)
  common : overlapsList a.range [b.range, c.range]
  evenTail : more.length % 2 = 0
  chain : (a :: b :: c :: more).IsChain (fun x y => x.dir ≠ y.dir ∧ x.stop.pivot = y.start.pivot)
  forward : advances a.dir a.start.pivot.extreme ((c :: more).getLast (by simp)).stop.pivot.extreme
  endedBy : Option SegTermKind
  deriving DecidableEq

/-- 所辖笔的闭下标区间；与原始 K 线下标分开。
[077:62] 也就是说，和笔一样，线段也不可能从一个顶开始结束于一个顶，或者从一个底开始结束于一个底。由此可见，线段中包含笔的数目，都是单数的。 -/
def Segment.penSpan (s : Segment P) : Span :=
  ⟨s.firstPen, s.firstPen + 2 + s.more.length, by omega⟩

/-- 包络全部笔的实际值域及其原始 K 线跨度，不把端点当作必然的段内极值。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。
[078:58] 注意，这里必须提醒一句，就是这在以前也曾说过，就是，如果线段中，最高或最低点不是线段的端点，那么，在任何以线段为基础的分析中，例如把线段为基础构成最小级别的中枢等，都可以把该线段标准化为最高低点都在端点。因为，在以线段为基础的分析中，都把线段当成一个没有内部结构的基本部件，所以，只需要关心这线段的实际区间就可以，这样就可以只看其高低点。 -/
def Segment.toSeg (s : Segment P) : Seg P :=
  let tail := s.b :: s.c :: s.more
  ⟨s.a.dir, hullInterval s.a.range (tail.map Pen.range),
    tail.foldl (fun span p => span.join p.source) s.a.source⟩

/-- 标准化视图把实际高低安排到两个端点；不改变原线段，也不要求相邻视图首尾相等。
[078:58] 注意，这里必须提醒一句，就是这在以前也曾说过，就是，如果线段中，最高或最低点不是线段的端点，那么，在任何以线段为基础的分析中，例如把线段为基础构成最小级别的中枢等，都可以把该线段标准化为最高低点都在端点。因为，在以线段为基础的分析中，都把线段当成一个没有内部结构的基本部件，所以，只需要关心这线段的实际区间就可以，这样就可以只看其高低点。
[078:60] 经过标准化处理后，所有向上线段都是以最低点开始最高点结束，向下线段都是以最高点开始最低点结束，这样，所以线段的连接，就形成一条延续不断、首尾相连的折线，这样，复杂的图形，就会十分地标准化，也为后面的中枢、走势类型等分析提供了最标准且基础的部件。 -/
def standardizeSegment (s : Segment P) : P × P :=
  let r := s.toSeg.range
  if s.a.dir = .up then (r.lo, r.hi) else (r.hi, r.lo)

/-- 从具体笔块构造线段；无三笔公共交、偶数笔、断接或端点倒置均不成立。
[065:48] 线段有一个最基本的前提，就是线段的前三笔，必须有重叠的部分，这个前提在前面可能没有特别强调，这里必须特别强调一次。线段至少有三笔，但并不是连续的三笔就一定构成线段，这三笔必须有重叠的部分。
[078:20] 同样，正如同一笔不可能出现顶低于底的情况，同一线段中，两端的一顶一底，顶肯定要高于底，如果你划出一个不符合这基本要求的线段，那肯定是划错了。 -/
def segmentOfPens (i : Nat) (reason : Option SegTermKind) : List (Pen P) → Option (Segment P)
  | a :: b :: c :: more =>
    if h : overlapsList a.range [b.range, c.range] ∧ more.length % 2 = 0 ∧
        (a :: b :: c :: more).IsChain (fun x y => x.dir ≠ y.dir ∧ x.stop.pivot = y.start.pivot) ∧
        advances a.dir a.start.pivot.extreme ((c :: more).getLast (by simp)).stop.pivot.extreme then
      some ⟨i, a, b, c, more, h.1, h.2.1, h.2.2.1, h.2.2.2, reason⟩
    else none
  | _ => none

/-- 极值顶点臂：候选末笔必须比段内之前每根同向笔推进得更远。
[071:38] 其实，线段的划分，都是可以当下完成的，无非是如下的程序：假设某转折点是两线段的分界点，然后对此用线段划分的两种情况去考察是否满足，如果满足其中一种，那么这点就是真正的线段的分界点；如果不满足，那就不是，原来的线段依然延续，就这么简单。
[二级旁证 081:222] 首先要选择原线段待破坏的顶点，这里显然是1，3还没1高，显然不构成待破坏的顶点。这样，5下来破坏了1，然后扩展成线段，那就是标准的第一种情况，和3没什么关系。 -/
def isExtremeVertex (d : Dir) (chunk : List (Pen P)) : Bool :=
  match chunk.reverse with
  | [] => false
  | p :: prior =>
    prior.all fun q => q.dir ≠ d || advances d q.stop.pivot.extreme p.stop.pivot.extreme

/-- 在指定起点逐一试奇数笔候选，不跳到全局极值。先取最早确认的分界；
仍无破坏时取该起点最长的合法开放段，不吞入末尾未成段的反向一笔。
[071:38] 其实，线段的划分，都是可以当下完成的，无非是如下的程序：假设某转折点是两线段的分界点，然后对此用线段划分的两种情况去考察是否满足，如果满足其中一种，那么这点就是真正的线段的分界点；如果不满足，那就不是，原来的线段依然延续，就这么简单。
[079:58] 其实，明白了上几节课，这两个图一定都不难分辨，首先，前提是这两个的前面都没有其他走势了，否则这种分析没意义，前面有其他走势，就有这很多不同的可能变化。 -/
def nextSegment (cfg : SegRuleConfig) (i : Nat) (pens : List (Pen P)) : Option (Segment P) :=
  match pens with
  | p :: _ =>
    let sizes := (List.range ((pens.length - 1) / 2)).map (fun n => 3 + 2*n)
    let confirmed := sizes.findSome? fun n =>
      let chunk := pens.take n
      if cfg.pivot = .extremeVertex && !isExtremeVertex p.dir chunk then none
      else
        match segmentBreak cfg p.dir chunk (pens.drop n) with
        | none => none
        | reason@(some _) => segmentOfPens i reason chunk
    confirmed.orElse fun _ => sizes.reverse.findSome? (fun n => segmentOfPens i none (pens.take n))
  | [] => none

/-- 输出原始线段记录；每次确认至少消费三笔。开放末段没有后继。
[079:58] 其实，明白了上几节课，这两个图一定都不难分辨，首先，前提是这两个的前面都没有其他走势了，否则这种分析没意义，前面有其他走势，就有这很多不同的可能变化。
[077:66] 另外，线段必须被线段所破坏才能确定其完成。 -/
def segmentTrace (cfg : SegRuleConfig) (pens : List (Pen P)) (start : Nat) : List (Segment P) :=
  let remaining := pens.drop start
  walk cfg start remaining remaining.length
where
  /-- 剩余笔数给出结构递归上界。
  [065:48] 线段有一个最基本的前提，就是线段的前三笔，必须有重叠的部分，这个前提在前面可能没有特别强调，这里必须特别强调一次。线段至少有三笔，但并不是连续的三笔就一定构成线段，这三笔必须有重叠的部分。 -/
  walk (rule : SegRuleConfig) (i : Nat) (rest : List (Pen P)) : Nat → List (Segment P)
    | 0 => []
    | fuel + 1 =>
      match nextSegment rule i rest with
      | none => []
      | some s =>
        let n := 3 + s.more.length
        if s.endedBy.isSome then s :: walk rule (i+n) (rest.drop n) fuel else [s]

/-- 从首方向和依次反向的区间构造 M4 对象。每一步同时给出表头方向的见证。
[059:18] 还有，前后两线段间，不可能是同向的，同是向上或向下不可能构成两个前后相邻的线段。而且，由于线段都至少呈现上下上或下上下，所以线段不存在一条直线走平的可能，由此也知道，为什么一字涨停，无论如何延续，还是低于线段的级别，是最小级别的。 -/
def alternateRanges (d : Dir) (xs : List (Bar P × Span)) :
    { seq : AltSeq P // ∀ s ∈ seq.items.head?, s.dir = d } :=
  match xs with
  | [] => ⟨⟨[], .nil⟩, by simp⟩
  | (r, span) :: rest =>
    let ⟨⟨tail, chain⟩, headDir⟩ := alternateRanges d.flip rest
    let s : Seg P := ⟨d, r, span⟩
    ⟨⟨s :: tail, by
      cases tail with
      | nil => exact List.isChain_singleton _
      | cons t ts =>
        have h : t.dir = d.flip := headDir t (by simp)
        exact List.isChain_cons_cons.mpr ⟨by
          change d ≠ t.dir
          rw [h]
          cases d <;> decide, chain⟩⟩, by simp [s]⟩

/-- 以调用者给定的笔下标为唯一起点，返回真实凸包的 M4 交替区间列。
[079:58] 其实，明白了上几节课，这两个图一定都不难分辨，首先，前提是这两个的前面都没有其他走势了，否则这种分析没意义，前面有其他走势，就有这很多不同的可能变化。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。
[二级旁证 078:206] 请问老大,上图分几段,怎样分?==如果前面还有走势，那这根本分不了，要看前面的走势。如果前面没有任何走势，那就是三段。 -/
def parseSegments (cfg : SegRuleConfig) (pens : List (Pen P)) (start : Nat) : AltSeq P :=
  match (segmentTrace cfg pens start).map Segment.toSeg with
  | [] => ⟨[], .nil⟩
  | s :: ss => (alternateRanges s.dir ((s :: ss).map (fun x => (x.range, x.source)))).1

end Chan.Defs.Base
