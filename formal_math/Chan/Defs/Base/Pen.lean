module

public import Chan.Defs.Base.Fractal

@[expose] public section

namespace Chan.Defs.Base

open Chan.Defs.Order Chan.Defs.Alt
variable {P : Type _} [LinearOrder P]

/-- 合并跨度是中心下标之差；原始间隔只数两个实际极值下标之间的根数，不含两端。
[062:26] 但这里有一个细微的地方要分清楚，因为结合律是必须遵守的，像图3这种，顶和底之间必须共用一个K线，这就违反结合律了，所以这不算一笔，而图4，就光是顶和底了，中间没有其他K线，一般来说，也最好不算一笔，而图5，是一笔的最基本的图形，顶和底之间还有一根K线。 -/
structure PenRule where
  minMergedSpan : Nat
  minRawSpan : Nat
  requireDisjointFractal : Bool
  deriving DecidableEq

/-- 两个三根窗口之间至少留一根独立的合并 K 线。
[062:26] 在实际分析中，都必须要求顶和底之间都至少有一K线当成一笔的最基本要求。 -/
def oldPenRule : PenRule := ⟨4, 0, false⟩

/-- 新笔不许窗口共根，两个原始极值之间至少三根。
[077:34] 如果没有包含关系，3个K线就可以决定一个分型，但注意，任何相邻的分型之间必须满足结合律，也就是，不能有些K线分属不同的分型，这样是不允许的。
[二级旁证 081:110] 本ID想了想，计算了一下能量力度，觉得以后可以把笔的成立条件略微放松一下，就是一笔必须满足以下两个条件：1、顶分型与底分型经过包含处理后，不允许共用K线，也就是不能有一K线分别属于顶分型与底分型，这条件和原来是一样的，这一点绝对不能放松，因为这样，才能保证足够的能量力度；2、在满足1的前提下，顶分型中最高K线和底分型的最低K线之间（不包括这两K线），不考虑包含关系，至少有3根（包括3根）以上K线。显然，第二个条件，比原来分型间必须有独立K线的一条，要稍微放松了一点，这样，象今天绿箭头所指的地方，就是一笔了，相应那三笔下来就构成一段了，整个划分就不会出现比较古怪的线段。 -/
def newPenRule : PenRule := ⟨3, 3, false⟩

/-- 以两端实际极值为界，含两端至少六个原始单位。
[106:16] 任一级别，都有最少的延伸时间，例如，一笔，由于必须有顶与底的分型，因此，必须至少延伸6个基本K线单位，也就是说，如果5日线都不能碰到，那就不会是笔的反弹了。 -/
def sixBarPenRule : PenRule := ⟨3, 4, false⟩

/-- 在选定规则上要求顶区间向上、底区间向下各伸出一部分；两区间仍可相交。
[077:38] 有了上面这基础工作，那这个图就可以看成只有这些分型，分型之间的K线都可以暂时不用管。下面的工作，就是确定笔了。笔，必须是一顶一底，而且顶和底之间至少有一个K线不属于顶分型与底分型。当然，还有一个最显然的，就是在同一笔中，顶分型中最高那K线的区间至少要有一部分高于底分型中最低那K线的区间，如果这条都不满足，也就是顶都在低的范围内或顶比底还低，这显然是不可接受的。
[二级旁证 099:56] 当然，站在本ID理论的角度，由于这次的底分型范围的上沿也在4672点，所以4195点上来的走势最终是否延伸为笔，关键也在4672点的站稳。因为笔的最基本条件就是顶和底分型之间必须有不重合的部分，1月23日那个底分型，就是因为后面不能突破站住1月22日高点4818点，所以使得不可能延伸为笔，进而原来的向下笔继续延伸，形成后面的下跌。 -/
def disjointFractalPenRule (rule : PenRule := newPenRule) : PenRule :=
  { rule with requireDisjointFractal := true }

/-- 检验端点异性、不共根、两种跨度及顶区间两端都严格高于底区间两端；中心间所有合并根的值域
必须落在这两个极值之间。原始根位置由被选择的具体高点或低点给出。
[077:38] 有了上面这基础工作，那这个图就可以看成只有这些分型，分型之间的K线都可以暂时不用管。下面的工作，就是确定笔了。笔，必须是一顶一底，而且顶和底之间至少有一个K线不属于顶分型与底分型。当然，还有一个最显然的，就是在同一笔中，顶分型中最高那K线的区间至少要有一部分高于底分型中最低那K线的区间，如果这条都不满足，也就是顶都在低的范围内或顶比底还低，这显然是不可接受的。
[077:42] 如果前面的底高于后面的底，那么前面的划分显然是错误的，因为按这种划分，该笔是没有完成的，一个底不经过一个顶后就有一个更低的底，这是最典型的笔没完成的情况。 -/
abbrev ValidPenPair (r : PenRule) (bars : List (MergedBar P)) (a b : LocalFractal P) : Prop :=
  a.kind ≠ b.kind ∧ a.first + 3 ≤ b.first ∧
  a.center + r.minMergedSpan ≤ b.center ∧
  a.extremeAt + 1 + r.minRawSpan ≤ b.extremeAt ∧
  (if a.kind = .bottom then a.middle.range.strictUp b.middle.range
   else b.middle.range.strictUp a.middle.range) ∧
  (r.requireDisjointFractal = true →
    (if a.kind = .bottom then a.range.strictUp b.range else b.range.strictUp a.range)) ∧
  ((bars.drop a.center).take (b.center - a.center + 1)).all (fun k =>
    min a.extreme b.extreme ≤ k.range.lo && k.range.hi ≤ max a.extreme b.extreme) = true

/-- 检验取舍：两头不能再接一笔；相邻端点间不能再插入一对合法转折；
同性质的更优极值若能同时接上左右邻，就不能保留劣者。等值不排斥任一解。
[062:26] 两个相邻的顶和底之间构成一笔，所谓笔，就是顶和底之间的其他波动，都可以忽略不算，但注意，一定是相邻的顶和底，隔了几个就不是了。而所谓的线段，就是至少由三笔组成。
[077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
def penChoicesSaturated (r : PenRule) (bars : List (MergedBar P)) (allPivots : List (LocalFractal P))
    (prior : Option (LocalFractal P)) : List (LocalFractal P) → Bool
  | [] => true
  | a :: rest =>
    let edge := fun x y => decide (ValidPenPair r bars x y)
    let next := rest.head?
    let canExtend := (prior.isNone && allPivots.any (edge · a)) ||
      (next.isNone && allPivots.any (edge a ·))
    let dominated := allPivots.any fun x =>
      x.kind = a.kind && (if a.kind = .top then a.extreme < x.extreme else x.extreme < a.extreme) &&
      prior.all (edge · x) && next.all (edge x ·)
    let subdivides := next.any fun b =>
      let interior := allPivots.filter (fun x => a.first < x.first && x.first < b.first)
      interior.any fun x => edge a x && interior.any (fun y => edge x y && edge y b)
    !canExtend && !dominated && !subdivides && penChoicesSaturated r bars allPivots (some a) rest

/-- 在原始候选中按序选出的端点，每对均满足当前参数下的极值和间距约束，
且取舍已经饱和。此关系不调用解析器，不以某个确定性平局选择代替合法性。
[069:16] 打“X”的就是该分型不符合笔所要求分型的规范。这里，只要是两条：一、顶和底之间没有至少一K线；二、不满足顶必须接着底、或底必须接着顶。
[077:38] 有了上面这基础工作，那这个图就可以看成只有这些分型，分型之间的K线都可以暂时不用管。下面的工作，就是确定笔了。笔，必须是一顶一底，而且顶和底之间至少有一个K线不属于顶分型与底分型。当然，还有一个最显然的，就是在同一笔中，顶分型中最高那K线的区间至少要有一部分高于底分型中最低那K线的区间，如果这条都不满足，也就是顶都在低的范围内或顶比底还低，这显然是不可接受的。 -/
abbrev ValidPenDecomp (r : PenRule) (bars : List (MergedBar P)) (xs : List (LocalFractal P)) : Prop :=
  xs.Sublist (scanLocalFractals bars) ∧ xs.IsChain (ValidPenPair r bars) ∧
  (xs.isEmpty = true → (scanLocalFractals bars).isEmpty = true) ∧
  penChoicesSaturated r bars (scanLocalFractals bars) none xs = true

/-- 一笔连接两个保留分型，终点保存的前驱就是起点。
[065:40] 所以，根据上面的分析，对第二种情况进行相应处理（类似对分型中包含关系的处理），就可以严格地说，先顶后底，构成向下一笔；先底后顶，构成向上一笔。而所有的图形，都可以唯一地分解为上下交替的笔的连接。 -/
structure Pen (P : Type _) [LinearOrder P] where
  start : RetainedFractal P
  stop : RetainedFractal P
  linked : stop.previous = some start.pivot
  deriving DecidableEq

/-- 底出发向上，顶出发向下。
[065:40] 所以，根据上面的分析，对第二种情况进行相应处理（类似对分型中包含关系的处理），就可以严格地说，先顶后底，构成向下一笔；先底后顶，构成向上一笔。而所有的图形，都可以唯一地分解为上下交替的笔的连接。 -/
def Pen.dir (p : Pen P) : Dir := if p.start.pivot.kind = .bottom then .up else .down

/-- 合法笔两端给出整笔闭值域。
[062:26] 两个相邻的顶和底之间构成一笔，所谓笔，就是顶和底之间的其他波动，都可以忽略不算，但注意，一定是相邻的顶和底，隔了几个就不是了。而所谓的线段，就是至少由三笔组成。 -/
def Pen.range (p : Pen P) : Bar P :=
  let a := p.start.pivot.extreme
  let b := p.stop.pivot.extreme
  ⟨min a b, max a b, (min_le_left _ _).trans (le_max_left _ _)⟩

/-- 连接的是极值所在的原始位置，不将左右翼计入该笔。
[077:38] 有了上面这基础工作，那这个图就可以看成只有这些分型，分型之间的K线都可以暂时不用管。下面的工作，就是确定笔了。笔，必须是一顶一底，而且顶和底之间至少有一个K线不属于顶分型与底分型。当然，还有一个最显然的，就是在同一笔中，顶分型中最高那K线的区间至少要有一部分高于底分型中最低那K线的区间，如果这条都不满足，也就是顶都在低的范围内或顶比底还低，这显然是不可接受的。 -/
def Pen.source (p : Pen P) : Span :=
  let a := p.start.pivot.extremeAt
  let b := p.stop.pivot.extremeAt
  ⟨min a b, max a b, (Nat.min_le_left _ _).trans (Nat.le_max_left _ _)⟩

/-- 等值候选只有在能接上同一组邻点时才按先后破平。
[077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
inductive PenTiePolicy where
  | preferEarlier | preferLater
  deriving DecidableEq

/-- 非空等值簇：每个成员保存分型和一条已合法连接的逆序前缀。
[077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
structure PenPivotCluster (P : Type _) [LinearOrder P] where
  first : LocalFractal P × List (LocalFractal P)
  laterRev : List (LocalFractal P × List (LocalFractal P))

/-- 从左至右保留初始有效极值。新极值反证当前后缀时逐级重试前驱，
不按全局笔数重选首端；最后只对在线链作饱和三检和可互换等值破平。
[069:20] 例如，第一个红箭头和第二个绿箭头之间显然不能构成一笔，也就是说，这两个，只能取一个：如果取第一个红箭头，那么第二个绿箭头就不是笔中分型，那么第二个红箭头，显然是一个底分型，因此，就形成两个底分型连续的划分，显然，这时候，第一个就不算了，这和前面说取第一个红箭头对着的底分型矛盾。所以，这里，只能取第二个绿箭头，这时候，第一个绿箭头对应的顶分型，自然就不算笔中的顶了。
[077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
def penPivots (r : PenRule) (bars : List (MergedBar P))
    (tie : PenTiePolicy := .preferEarlier) : List (LocalFractal P) :=
  let allPivots := scanLocalFractals bars
  let edge := fun a b => decide (ValidPenPair r bars a b)
  let stack := allPivots.foldl (stepPivots edge) []
  -- 先取一条合法链作锚；修补时按实际前后邻点破平。
  let pivots := stack.head?.map (fun c => (c.first.1 :: c.first.2).reverse)
  saturatePivots tie edge allPivots (2 * allPivots.length ^ 2 + 1) (pivots.getD [])
where
  /-- 只比较同性质极值，顶取更高、底取更低。
  [077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
  betterExtreme (x a : LocalFractal P) : Bool :=
    x.kind = a.kind && (if a.kind = .top then a.extreme < x.extreme else x.extreme < a.extreme)

  /-- 同性质且同极值，不比较位置或邻接。
  [077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
  equalExtreme (x a : LocalFractal P) : Bool := x.kind = a.kind && x.extreme = a.extreme

  /-- 候选均已接通同一组邻点时，严格择优；极值相等才比较下标。
  [077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
  preferPivot (tie : PenTiePolicy) (x a : LocalFractal P) : Bool :=
    betterExtreme x a || (equalExtreme x a &&
      (if tie = .preferEarlier then x.first < a.first else a.first < x.first))

  /-- 筛出可连的前驱，以其中一条合法前缀作为见证；前驱簇仍完整保留。
  这一步不按破平策略选边。
  [077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
  linkPivot (edge : LocalFractal P → LocalFractal P → Bool) (prior : Option (PenPivotCluster P))
      (x : LocalFractal P) : Option (LocalFractal P × List (LocalFractal P)) :=
    match prior with
    | none => some (x, [])
    | some a =>
      let compatible := (a.first :: a.laterRev).filter fun (m, _) => edge m x
      compatible.head?.map fun (m, prefixRev) => (x, m :: prefixRev)

  /-- 从待反证的同性帧开始。每跨一层必须先胜过该层极值或与之等值，
  并重试其紧邻前驱；孤立异向帧或更强历史帧阻止回溯。
  [077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
  rewindPivots (edge : LocalFractal P → LocalFractal P → Bool)
      (x : LocalFractal P) : List (PenPivotCluster P) → Option (List (PenPivotCluster P))
    | [] => none
    | p :: rest =>
      let eqv := equalExtreme x p.first.1
      if eqv || betterExtreme x p.first.1 then
        match linkPivot edge rest.head? x with
        | some m =>
          let frame := if eqv then { p with laterRev := m :: p.laterRev } else ⟨m, []⟩
          some (frame :: rest)
        | none =>
          match rest with
          | _ :: earlier => rewindPivots edge x earlier
          | [] => none
      else none

  /-- 同性等值接得上前驱便入簇；异性先试簇内连边，只在失败后尝试反证。
  回溯不成功则原栈不动。
  [077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
  stepPivots (edge : LocalFractal P → LocalFractal P → Bool)
      (stack : List (PenPivotCluster P)) (x : LocalFractal P) : List (PenPivotCluster P) :=
    match stack with
    | [] => [⟨(x, []), []⟩]
    | a :: rest =>
      if equalExtreme x a.first.1 then
        match linkPivot edge rest.head? x with
        | none => stack
        | some m => { a with laterRev := m :: a.laterRev } :: rest
      else if x.kind = a.first.1.kind then
        (rewindPivots edge x stack).getD stack
      else
        match linkPivot edge (some a) x with
        | some m => ⟨m, []⟩ :: stack
        | none => (rewindPivots edge x rest).getD stack

  /-- 仅返回第一处可修补的未饱和取舍；不做全局笔数优化。
  [077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
  penRepair (tie : PenTiePolicy) (edge : LocalFractal P → LocalFractal P → Bool)
      (allPivots : List (LocalFractal P)) (prior : Option (LocalFractal P)) :
      List (LocalFractal P) → Option (List (LocalFractal P))
    | [] => none
    | a :: rest =>
      let next := rest.head?
      -- 扩展时先试当前端点，再试能接通另一侧既有邻点的等值端点。
      -- 扩展建立新邻边，不在邻点尚未确定时按策略选等值端点。
      let prepend := if prior.isNone then (a :: allPivots).findSome? (fun x =>
        if equalExtreme x a && next.all (edge x ·) then
          (allPivots.find? (edge · x)).map (·, x)
        else none) else none
      let append := if next.isNone then (a :: allPivots).findSome? (fun x =>
        if equalExtreme x a && prior.all (edge · x) then
          (allPivots.find? (edge x ·)).map (x, ·)
        else none) else none
      match prepend, append with
      | some (x, y), _ => some (x :: y :: rest)
      | _, some (x, y) => some [x, y]
      | _, _ =>
        match allPivots.find? (fun x => preferPivot tie x a && prior.all (edge · x) && next.all (edge x ·)) with
        | some x => some (x :: rest)
        | none =>
          let insertions := next.bind fun b =>
            let interior := allPivots.filter (fun x => a.first < x.first && x.first < b.first)
            interior.findSome? fun x =>
              if edge a x then (interior.find? (fun y => edge x y && edge y b)).map (x, ·)
              else none
          match insertions with
          | some (x, y) => some (a :: x :: y :: rest)
          | none => (penRepair tie edge allPivots (some a) rest).map (a :: ·)

  -- 候选按同类极值及破平顺序各取 1..n 的秩，每个端点计 n + 秩。
  -- 择优替换严格增秩；细分增加两项；扩展新增一项且至多让一个旧端点降 n-1 秩。
  -- 每次修补总分严格增加，而链无重复、至多 n 项，总分不超过 2n²。
  /-- 反复修补至端点、替换与细分三项均饱和。
  [077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
  saturatePivots (tie : PenTiePolicy) (edge : LocalFractal P → LocalFractal P → Bool)
      (allPivots : List (LocalFractal P)) : Nat → List (LocalFractal P) → List (LocalFractal P)
    | 0, xs => xs
    | fuel + 1, xs =>
      match penRepair tie edge allPivots none xs with
      | none => xs
      | some ys => saturatePivots tie edge allPivots fuel ys

/-- 沿所选链建立相邻笔共享的端点。携带上一分型的证据排除了共根、同向相接。
[077:34] 如果没有包含关系，3个K线就可以决定一个分型，但注意，任何相邻的分型之间必须满足结合律，也就是，不能有些K线分属不同的分型，这样是不允许的。 -/
def connectPivots (a : RetainedFractal P) : List (LocalFractal P) → List (Pen P)
  | [] => []
  | b :: bs =>
    if h : a.pivot.kind ≠ b.kind ∧ a.pivot.first + 3 ≤ b.first then
      let next : RetainedFractal P := ⟨b, some a.pivot, by simpa using h⟩
      ⟨a, next, rfl⟩ :: connectPivots next bs
    else []

/-- 从无包含历史在线取笔，保首极值并在反证时逐级退栈；单个局部极值不构成笔。
待 `needs-fable` 最终裁定 `U-1`。
[069:20] 例如，第一个红箭头和第二个绿箭头之间显然不能构成一笔，也就是说，这两个，只能取一个：如果取第一个红箭头，那么第二个绿箭头就不是笔中分型，那么第二个红箭头，显然是一个底分型，因此，就形成两个底分型连续的划分，显然，这时候，第一个就不算了，这和前面说取第一个红箭头对着的底分型矛盾。所以，这里，只能取第二个绿箭头，这时候，第一个绿箭头对应的顶分型，自然就不算笔中的顶了。
[065:40] 所以，根据上面的分析，对第二种情况进行相应处理（类似对分型中包含关系的处理），就可以严格地说，先顶后底，构成向下一笔；先底后顶，构成向上一笔。而所有的图形，都可以唯一地分解为上下交替的笔的连接。 -/
def parsePens (r : PenRule) (bars : List (MergedBar P))
    (tie : PenTiePolicy := .preferEarlier) : List (Pen P) :=
  match penPivots r bars tie with
  | [] => []
  | f :: fs => connectPivots ⟨f, none, by simp⟩ fs

/-- 当前方向上的分型构造与确认后的延伸。
[091:28] 缠中说禅笔定理：任何的当下，在任何时间周期的K线图中，走势必然落在一确定的具有明确方向的笔当中（向上笔或向下笔），而在笔当中的位置，必然只有两种情况：一、在分型构造中。二、分型构造确认后延伸为笔的过程中。 -/
inductive PenPhase where
  | forming | extending
  deriving DecidableEq

/-- 方向和阶段分别取两个值。
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
    | .forming => 0
    | .extending => 1))

/-- 末步顺向且没有未被突破的反向局部分型才算延伸。尚无保留分型
时不指定笔方向。待 `needs-fable` 最终裁定 `U-2`。
[091:28] 缠中说禅笔定理：任何的当下，在任何时间周期的K线图中，走势必然落在一确定的具有明确方向的笔当中（向上笔或向下笔），而在笔当中的位置，必然只有两种情况：一、在分型构造中。二、分型构造确认后延伸为笔的过程中。
[091:30] 根据这个定理，对于任何的当下走势，在任何一个时间周期里，我们都可以用两个变量构成的数组精确地定义当下的走势。第一个变量，只有两个取值，不妨用1代表向上的笔，-1代表向下的笔；第二个变量也只有两个取值，0代表分型构造中，1代表分型确认延伸为笔的过程中。 -/
def penOnlineState (r : PenRule) (bars : List (MergedBar P))
    (tie : PenTiePolicy := .preferEarlier) : Option PenOnlineState :=
  match (penPivots r bars tie).getLast? with
  | none => none
  | some f =>
    let d := if f.kind = .bottom then Dir.up else Dir.down
    let uncleared := (scanLocalFractals bars).any fun x =>
      f.first < x.first && x.kind ≠ f.kind &&
        !(bars.drop (x.center + 1)).any (fun b =>
          if d = .up then x.extreme < b.range.hi else b.range.lo < x.extreme)
    let continues := match bars.reverse with
      | b :: a :: _ => if d = .up then decide (a.range.strictUp b.range)
                                   else decide (a.range.strictDown b.range)
      | _ => false
    some ⟨d, if !uncleared && continues then .extending else .forming⟩

end Chan.Defs.Base
