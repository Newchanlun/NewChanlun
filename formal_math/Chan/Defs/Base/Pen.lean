module

public import Chan.Defs.Base.Fractal

@[expose] public section

namespace Chan.Defs.Base

open Chan.Defs.Order Chan.Defs.Alt

variable {P : Type _} [LinearOrder P]

/-- 参数化笔规则：`minMergedSpan` 为顶底分型中心在无包含合并序列上的最小下标距离；
`minRawSpan` 为两分型极值所在原始 K 线之间（不含这两根）的最少原始 K 线根数；
`requireDisjointFractal` 为是否要求顶底分型区间存在不重合部分。
无论参数如何，结合律（中心距离至少 3，即不共用合并 K 线）始终强制。
[062:26] 在实际分析中，都必须要求顶和底之间都至少有一K线当成一笔的最基本要求。
[106:16] 任一级别，都有最少的延伸时间，例如，一笔，由于必须有顶与底的分型，因此，必须至少延伸6个基本K线单位，也就是说，如果5日线都不能碰到，那就不会是笔的反弹了。 -/
structure PenRule where
  minMergedSpan : Nat
  minRawSpan : Nat
  requireDisjointFractal : Bool
  deriving DecidableEq

/-- 老笔：顶底之间至少一根独立合并 K 线（中心距离至少 4），不设原始间隔下限。
[062:26] 在实际分析中，都必须要求顶和底之间都至少有一K线当成一笔的最基本要求。 -/
def oldPenRule : PenRule := ⟨4, 0, false⟩

/-- 新笔：包含处理后不共用 K 线（中心距离至少 3），且顶底极值原始 K 线之间（不含两端）至少 3 根。
[077:34] 如果没有包含关系，3个K线就可以决定一个分型，但注意，任何相邻的分型之间必须满足结合律，也就是，不能有些K线分属不同的分型，这样是不允许的。
[二级旁证 081:110] 本ID想了想，计算了一下能量力度，觉得以后可以把笔的成立条件略微放松一下，就是一笔必须满足以下两个条件：1、顶分型与底分型经过包含处理后，不允许共用K线，也就是不能有一K线分别属于顶分型与底分型，这条件和原来是一样的，这一点绝对不能放松，因为这样，才能保证足够的能量力度；2、在满足1的前提下，顶分型中最高K线和底分型的最低K线之间（不包括这两K线），不考虑包含关系，至少有3根（包括3根）以上K线。显然，第二个条件，比原来分型间必须有独立K线的一条，要稍微放松了一点，这样，象今天绿箭头所指的地方，就是一笔了，相应那三笔下来就构成一段了，整个划分就不会出现比较古怪的线段。 -/
def newPenRule : PenRule := ⟨3, 3, false⟩

/-- 六根笔：不共用合并 K 线，且顶底极值原始 K 线含两端至少 6 根（不含两端至少 4 根）。
[106:16] 任一级别，都有最少的延伸时间，例如，一笔，由于必须有顶与底的分型，因此，必须至少延伸6个基本K线单位，也就是说，如果5日线都不能碰到，那就不会是笔的反弹了。 -/
def sixBarPenRule : PenRule := ⟨3, 4, false⟩

/-- 分型区间不重合变体：不共用合并 K 线，并要求顶分型区间两端都严格越出底分型区间。
[077:38] 有了上面这基础工作，那这个图就可以看成只有这些分型，分型之间的K线都可以暂时不用管。下面的工作，就是确定笔了。笔，必须是一顶一底，而且顶和底之间至少有一个K线不属于顶分型与底分型。当然，还有一个最显然的，就是在同一笔中，顶分型中最高那K线的区间至少要有一部分高于底分型中最低那K线的区间，如果这条都不满足，也就是顶都在低的范围内或顶比底还低，这显然是不可接受的。
[二级旁证 099:56] 当然，站在本ID理论的角度，由于这次的底分型范围的上沿也在4672点，所以4195点上来的走势最终是否延伸为笔，关键也在4672点的站稳。因为笔的最基本条件就是顶和底分型之间必须有不重合的部分，1月23日那个底分型，就是因为后面不能突破站住1月22日高点4818点，所以使得不可能延伸为笔，进而原来的向下笔继续延伸，形成后面的下跌。 -/
def disjointFractalPenRule : PenRule := ⟨3, 0, true⟩

/-- 顶分型最高 K 线区间至少有一部分严格高于底分型最低 K 线区间（顶在前或底在前均适用）。
[077:38] 有了上面这基础工作，那这个图就可以看成只有这些分型，分型之间的K线都可以暂时不用管。下面的工作，就是确定笔了。笔，必须是一顶一底，而且顶和底之间至少有一个K线不属于顶分型与底分型。当然，还有一个最显然的，就是在同一笔中，顶分型中最高那K线的区间至少要有一部分高于底分型中最低那K线的区间，如果这条都不满足，也就是顶都在低的范围内或顶比底还低，这显然是不可接受的。 -/
abbrev PenHeightOK (a b : LocalFractal P) : Prop :=
  (a.kind = .top ∧ b.mid.range.hi < a.mid.range.hi) ∨
  (a.kind = .bottom ∧ a.mid.range.hi < b.mid.range.hi)

/-- 顶分型区间的高端严格高于底分型区间高端，且其低端严格高于底分型区间低端。
[二级旁证 099:56] 当然，站在本ID理论的角度，由于这次的底分型范围的上沿也在4672点，所以4195点上来的走势最终是否延伸为笔，关键也在4672点的站稳。因为笔的最基本条件就是顶和底分型之间必须有不重合的部分，1月23日那个底分型，就是因为后面不能突破站住1月22日高点4818点，所以使得不可能延伸为笔，进而原来的向下笔继续延伸，形成后面的下跌。
[108:18] 站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。 -/
abbrev FractalDisjointPart (a b : LocalFractal P) : Prop :=
  (a.kind = .top ∧ b.range.hi < a.range.hi ∧ b.range.lo < a.range.lo) ∨
  (a.kind = .bottom ∧ a.range.hi < b.range.hi ∧ a.range.lo < b.range.lo)

/-- 前分型 `a` 与后分型 `b` 构成合法单笔：一顶一底、满足结合律与规则的合并间距和原始间距、
顶高于底，必要时分型区间不重合。主线不带入 `077:44` 的不等号笔误。
[077:38] 有了上面这基础工作，那这个图就可以看成只有这些分型，分型之间的K线都可以暂时不用管。下面的工作，就是确定笔了。笔，必须是一顶一底，而且顶和底之间至少有一个K线不属于顶分型与底分型。当然，还有一个最显然的，就是在同一笔中，顶分型中最高那K线的区间至少要有一部分高于底分型中最低那K线的区间，如果这条都不满足，也就是顶都在低的范围内或顶比底还低，这显然是不可接受的。
[077:34] 如果没有包含关系，3个K线就可以决定一个分型，但注意，任何相邻的分型之间必须满足结合律，也就是，不能有些K线分属不同的分型，这样是不允许的。 -/
abbrev ValidPenPair (r : PenRule) (a b : LocalFractal P) : Prop :=
  a.kind ≠ b.kind ∧
  a.center + 3 ≤ b.center ∧
  a.center + r.minMergedSpan ≤ b.center ∧
  a.extremeIdx + r.minRawSpan < b.extremeIdx ∧
  PenHeightOK a b ∧
  (r.requireDisjointFractal = false ∨ FractalDisjointPart a b)

/-- 同性质分型中 `f` 严格更极端：顶更高或底更低。
[077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
abbrev FractalBeats (f g : LocalFractal P) : Prop :=
  f.kind = g.kind ∧
  ((g.kind = .top ∧ g.extreme < f.extreme) ∨ (g.kind = .bottom ∧ f.extreme < g.extreme))

/-- 同性质且极值相等的两分型（相等先保留）。
[077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
abbrev FractalTies (f g : LocalFractal P) : Prop :=
  f.kind = g.kind ∧ f.extreme = g.extreme

/-- 单笔：方向、起止两个保留分型、由两端极值构成的值域闭区间、两端极值原始 K 线的跨度。
[062:26] 两个相邻的顶和底之间构成一笔，所谓笔，就是顶和底之间的其他波动，都可以忽略不算，但注意，一定是相邻的顶和底，隔了几个就不是了。而所谓的线段，就是至少由三笔组成。
[065:40] 所以，根据上面的分析，对第二种情况进行相应处理（类似对分型中包含关系的处理），就可以严格地说，先顶后底，构成向下一笔；先底后顶，构成向上一笔。而所有的图形，都可以唯一地分解为上下交替的笔的连接。 -/
structure Pen (P : Type _) [LinearOrder P] where
  dir : Dir
  start : RetainedFractal P
  stop : RetainedFractal P
  range : Bar P
  rawSpan : Span
  deriving DecidableEq

/-- 两分型极值围成的闭区间。
[062:32] 所以，上升的一笔，由结合律，就一定是底分型+上升K线+顶分型；下降的一笔，就是顶分型+下降K线+底分型。 -/
def fractalPairRange (a b : LocalFractal P) : Bar P :=
  ⟨min a.extreme b.extreme, max a.extreme b.extreme, le_trans (min_le_left _ _) (le_max_left _ _)⟩

/-- 两分型极值原始 K 线围成的闭索引跨度。
[062:32] 所以，上升的一笔，由结合律，就一定是底分型+上升K线+顶分型；下降的一笔，就是顶分型+下降K线+底分型。 -/
def fractalPairSpan (a b : LocalFractal P) : Span :=
  ⟨min a.extremeIdx b.extremeIdx, max a.extremeIdx b.extremeIdx,
    Nat.le_trans (Nat.min_le_left _ _) (Nat.le_max_left _ _)⟩

/-- 自分型 `a` 出发的连接方向：底分型出发向上，顶分型出发向下。
[065:40] 所以，根据上面的分析，对第二种情况进行相应处理（类似对分型中包含关系的处理），就可以严格地说，先顶后底，构成向下一笔；先底后顶，构成向上一笔。而所有的图形，都可以唯一地分解为上下交替的笔的连接。 -/
def fractalPairDir (a : LocalFractal P) : Dir :=
  if a.kind = .bottom then .up else .down

/-- 由相邻两个保留分型构造单笔。
[065:40] 所以，根据上面的分析，对第二种情况进行相应处理（类似对分型中包含关系的处理），就可以严格地说，先顶后底，构成向下一笔；先底后顶，构成向上一笔。而所有的图形，都可以唯一地分解为上下交替的笔的连接。 -/
def Pen.ofPair (a b : RetainedFractal P) : Pen P :=
  ⟨fractalPairDir a.base, a, b, fractalPairRange a.base b.base, fractalPairSpan a.base b.base⟩

/-- 笔的起点价位：向上笔为低端，向下笔为高端。
[065:40] 所以，根据上面的分析，对第二种情况进行相应处理（类似对分型中包含关系的处理），就可以严格地说，先顶后底，构成向下一笔；先底后顶，构成向上一笔。而所有的图形，都可以唯一地分解为上下交替的笔的连接。 -/
def Pen.startPrice (p : Pen P) : P :=
  match p.dir with
  | .up => p.range.lo
  | .down => p.range.hi

/-- 笔的终点价位：向上笔为高端，向下笔为低端。
[065:40] 所以，根据上面的分析，对第二种情况进行相应处理（类似对分型中包含关系的处理），就可以严格地说，先顶后底，构成向下一笔；先底后顶，构成向上一笔。而所有的图形，都可以唯一地分解为上下交替的笔的连接。 -/
def Pen.endPrice (p : Pen P) : P :=
  match p.dir with
  | .up => p.range.hi
  | .down => p.range.lo

/-- 声明式合法笔分解（不依赖解析算法）：保留分型均为局部原始分型；相邻两者构成合法单笔，
且其间没有严格更极端的同性质局部分型；最后一个保留分型之后既无更极端的同性质分型，
也无能与之成笔的分型。
[065:40] 所以，根据上面的分析，对第二种情况进行相应处理（类似对分型中包含关系的处理），就可以严格地说，先顶后底，构成向下一笔；先底后顶，构成向上一笔。而所有的图形，都可以唯一地分解为上下交替的笔的连接。
[077:42] 如果前面的底高于后面的底，那么前面的划分显然是错误的，因为按这种划分，该笔是没有完成的，一个底不经过一个顶后就有一个更低的底，这是最典型的笔没完成的情况。 -/
abbrev ValidPenDecomp (r : PenRule) (ms : List (MergedBar P)) (rs : List (RetainedFractal P)) : Prop :=
  (∀ f ∈ rs, f.base ∈ scanLocalFractals ms) ∧
  (∀ p ∈ rs.zip rs.tail, ValidPenPair r p.1.base p.2.base ∧
    ∀ g ∈ scanLocalFractals ms, p.1.base.center < g.center → g.center < p.2.base.center →
      ¬ FractalBeats g p.1.base ∧ ¬ FractalBeats g p.2.base) ∧
  (∀ l ∈ rs.reverse.take 1, ∀ g ∈ scanLocalFractals ms, l.base.center < g.center →
      ¬ FractalBeats g l.base ∧ ¬ ValidPenPair r l.base g)

/-- 解析栈元素：`head` 为当前保留分型，`ties` 为其后极值相等、暂时一并保留的同性质分型。
[077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
structure PenCluster (P : Type _) [LinearOrder P] where
  head : LocalFractal P
  ties : List (LocalFractal P)

/-- 新端点 `f` 与栈中前一个已定端点（若有）仍构成合法单笔。
[077:38] 有了上面这基础工作，那这个图就可以看成只有这些分型，分型之间的K线都可以暂时不用管。下面的工作，就是确定笔了。笔，必须是一顶一底，而且顶和底之间至少有一个K线不属于顶分型与底分型。当然，还有一个最显然的，就是在同一笔中，顶分型中最高那K线的区间至少要有一部分高于底分型中最低那K线的区间，如果这条都不满足，也就是顶都在低的范围内或顶比底还低，这显然是不可接受的。 -/
def penPrevOK (r : PenRule) (rest : List (PenCluster P)) (f : LocalFractal P) : Bool :=
  match rest with
  | [] => true
  | p :: _ => decide (ValidPenPair r p.head f)

/-- 等值保留的决断：在相等分型中取最靠后、且能与新的相反分型 `f` 成笔的那一个。
[077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
def penPickTie (r : PenRule) (c : PenCluster P) (f : LocalFractal P) : Option (LocalFractal P) :=
  (c.head :: c.ties).reverse.find? fun m => decide (ValidPenPair r m f)

/-- 笔解析单步（栈顶在表头）。同性质：更极端者替换、相等者暂存、较弱者忽略；
相反性质：能成笔则入栈；不能成笔但比前一个同性质端点更极端时，反证回退：撤销栈顶并改选 `f`。
[069:20] 例如，第一个红箭头和第二个绿箭头之间显然不能构成一笔，也就是说，这两个，只能取一个：如果取第一个红箭头，那么第二个绿箭头就不是笔中分型，那么第二个红箭头，显然是一个底分型，因此，就形成两个底分型连续的划分，显然，这时候，第一个就不算了，这和前面说取第一个红箭头对着的底分型矛盾。所以，这里，只能取第二个绿箭头，这时候，第一个绿箭头对应的顶分型，自然就不算笔中的顶了。
[065:38] 第二种，在两个顶或底中间没有其他的顶和底；这种情况，意味着第一个顶或底后的转折级别太小，不足以构成值得考察的对象，这种情况下，第一个的顶或底就可以忽略其存在了，可以忽略不算了。 -/
def penStep (r : PenRule) (st : List (PenCluster P)) (f : LocalFractal P) : List (PenCluster P) :=
  match st with
  | [] => [PenCluster.mk f []]
  | c :: rest =>
    if c.head.kind = f.kind then
      if FractalBeats f c.head then
        (if penPrevOK r rest f then PenCluster.mk f [] :: rest else st)
      else if FractalTies f c.head then
        (if penPrevOK r rest f then PenCluster.mk c.head (c.ties ++ [f]) :: rest else st)
      else st
    else
      match penPickTie r c f with
      | some m => PenCluster.mk f [] :: PenCluster.mk m [] :: rest
      | none =>
        match rest with
        | p :: rest' =>
          if FractalBeats f p.head ∧ penPrevOK r rest' f = true then PenCluster.mk f [] :: rest'
          else st
        | [] => st

/-- 由局部原始分型序列解析出保留分型序列（成笔分型）；末端尚未决断的等值组取最靠后者。
[069:16] 打“X”的就是该分型不符合笔所要求分型的规范。这里，只要是两条：一、顶和底之间没有至少一K线；二、不满足顶必须接着底、或底必须接着顶。 -/
def parseRetained (r : PenRule) (fs : List (LocalFractal P)) : List (RetainedFractal P) :=
  ((fs.foldl (penStep r) []).reverse).map fun c => RetainedFractal.mk (c.ties.getLastD c.head)

/-- 相邻保留分型两两连成笔。
[065:40] 所以，根据上面的分析，对第二种情况进行相应处理（类似对分型中包含关系的处理），就可以严格地说，先顶后底，构成向下一笔；先底后顶，构成向上一笔。而所有的图形，都可以唯一地分解为上下交替的笔的连接。 -/
def pensOf : List (RetainedFractal P) → List (Pen P)
  | a :: tl@(b :: _) => Pen.ofPair a b :: pensOf tl
  | _ => []

/-- 带等值保留与反证回溯的确定性笔解析：无包含规范形 → 局部原始分型 → 保留分型 → 交替笔序列。
[069:20] 例如，第一个红箭头和第二个绿箭头之间显然不能构成一笔，也就是说，这两个，只能取一个：如果取第一个红箭头，那么第二个绿箭头就不是笔中分型，那么第二个红箭头，显然是一个底分型，因此，就形成两个底分型连续的划分，显然，这时候，第一个就不算了，这和前面说取第一个红箭头对着的底分型矛盾。所以，这里，只能取第二个绿箭头，这时候，第一个绿箭头对应的顶分型，自然就不算笔中的顶了。
[069:26] 有人可能要疑问，这样分型是否随时可以修改？答案是否定的。一旦完成的图形，这修改就不可能了。分型可修改，证明图形没完成。 -/
def parsePens (r : PenRule) (ms : List (MergedBar P)) : List (Pen P) :=
  pensOf (parseRetained r (scanLocalFractals ms))

/-- 笔中位置二态：`building` 为分型构造中（0），`extending` 为分型确认延伸为笔中（1）。
[091:28] 缠中说禅笔定理：任何的当下，在任何时间周期的K线图中，走势必然落在一确定的具有明确方向的笔当中（向上笔或向下笔），而在笔当中的位置，必然只有两种情况：一、在分型构造中。二、分型构造确认后延伸为笔的过程中。 -/
inductive PenPhase where
  | building
  | extending
  deriving DecidableEq

/-- 笔定理四态在线状态：方向 × 阶段。
[091:30] 根据这个定理，对于任何的当下走势，在任何一个时间周期里，我们都可以用两个变量构成的数组精确地定义当下的走势。第一个变量，只有两个取值，不妨用1代表向上的笔，-1代表向下的笔；第二个变量也只有两个取值，0代表分型构造中，1代表分型确认延伸为笔的过程中。 -/
structure PenOnlineState where
  dir : Dir
  phase : PenPhase
  deriving DecidableEq

/-- 原文的二元数组编码：方向取 1 或 -1，阶段取 0 或 1。
[091:30] 根据这个定理，对于任何的当下走势，在任何一个时间周期里，我们都可以用两个变量构成的数组精确地定义当下的走势。第一个变量，只有两个取值，不妨用1代表向上的笔，-1代表向下的笔；第二个变量也只有两个取值，0代表分型构造中，1代表分型确认延伸为笔的过程中。 -/
def PenOnlineState.code (s : PenOnlineState) : Int × Nat :=
  ((match s.dir with
    | .up => 1
    | .down => -1),
   (match s.phase with
    | .building => 0
    | .extending => 1))

/-- 在线状态判定：当前笔自最后一个保留分型出发（底出发向上、顶出发向下）；
其后若已出现尚未成笔的相反局部分型则处于分型构造中，否则处于延伸为笔中。尚无保留分型时无定义。
[091:28] 缠中说禅笔定理：任何的当下，在任何时间周期的K线图中，走势必然落在一确定的具有明确方向的笔当中（向上笔或向下笔），而在笔当中的位置，必然只有两种情况：一、在分型构造中。二、分型构造确认后延伸为笔的过程中。 -/
def penOnlineState (r : PenRule) (ms : List (MergedBar P)) : Option PenOnlineState :=
  let fs := scanLocalFractals ms
  match (parseRetained r fs).getLast? with
  | none => none
  | some l =>
    if fs.any (fun f => decide (l.base.center < f.center ∧ f.kind ≠ l.base.kind)) then
      some ⟨fractalPairDir l.base, .building⟩
    else
      some ⟨fractalPairDir l.base, .extending⟩

/-- 自给定方向起逐项交替赋向，构造区间序列。
[059:18] 还有，前后两线段间，不可能是同向的，同是向上或向下不可能构成两个前后相邻的线段。而且，由于线段都至少呈现上下上或下上下，所以线段不存在一条直线走平的可能，由此也知道，为什么一字涨停，无论如何延续，还是低于线段的级别，是最小级别的。 -/
def altSegs : Dir → List (Bar P × Span) → List (Seg P)
  | _, [] => []
  | d, x :: xs => ⟨d, x.1, x.2⟩ :: altSegs d.flip xs

/-- 交替赋向的序列相邻必反向（类型不变式）。
[059:18] 还有，前后两线段间，不可能是同向的，同是向上或向下不可能构成两个前后相邻的线段。而且，由于线段都至少呈现上下上或下上下，所以线段不存在一条直线走平的可能，由此也知道，为什么一字涨停，无论如何延续，还是低于线段的级别，是最小级别的。 -/
theorem altSegs_isChain (d : Dir) (xs : List (Bar P × Span)) :
    (altSegs d xs).IsChain (fun a b => a.dir ≠ b.dir) := by
  induction xs generalizing d with
  | nil => simp [altSegs]
  | cons _ xs ih =>
    cases xs with
    | nil => simp [altSegs]
    | cons _ _ =>
      have h := ih d.flip
      cases d <;> (simp [altSegs, Dir.flip] at h ⊢; exact h)

/-- 相邻同向段合并为一段（取外包区间与来源跨度之并）。
[059:18] 还有，前后两线段间，不可能是同向的，同是向上或向下不可能构成两个前后相邻的线段。而且，由于线段都至少呈现上下上或下上下，所以线段不存在一条直线走平的可能，由此也知道，为什么一字涨停，无论如何延续，还是低于线段的级别，是最小级别的。 -/
def coalesceSegs : List (Seg P) → List (Seg P)
  | [] => []
  | s :: rest =>
    match coalesceSegs rest with
    | [] => [s]
    | t :: ts =>
      if s.dir = t.dir then
        Seg.mk s.dir (hullInterval s.range [t.range]) (s.source.join t.source) :: ts
      else s :: t :: ts

/-- 把段列表规范为方向交替区间序列：先合并相邻同向段，再自首段方向起交替赋向。
[059:18] 还有，前后两线段间，不可能是同向的，同是向上或向下不可能构成两个前后相邻的线段。而且，由于线段都至少呈现上下上或下上下，所以线段不存在一条直线走平的可能，由此也知道，为什么一字涨停，无论如何延续，还是低于线段的级别，是最小级别的。 -/
def altSeqOfSegs (l : List (Seg P)) : AltSeq P :=
  let c := coalesceSegs l
  ⟨altSegs ((c.head?.map Seg.dir).getD .up) (c.map fun s => (s.range, s.source)),
    altSegs_isChain _ _⟩

end Chan.Defs.Base
