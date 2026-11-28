module

public import Chan.Defs.Base.Segment

@[expose] public section

namespace Chan.Defs.Base

open Chan.Defs.Order Chan.Defs.Alt
universe u
variable {P : Type u} [LinearOrder P]

/-- 递归的四种起点。标签属于类型，不是事后附加的显示名。
[084:54] 本ID关于中枢等的定义，其实一直没有改变过，因为中枢定义的关键，在于定义的递归性。一般的递归定义，由两部分组成，一、f1(a0)=a1；二、f2(an)=an+1；关于第二条的中枢过程规则，是一直没有任何改变的，而关于第一条，其实，可以随意设置任何的，都不会改变中枢定义的递归性。而且，任何有点数学常识的都知道，f1(a0)=a1之前是不需要再有什么递归性的，也就是，一和二之间的f1、f2可以是完全不同的两个函数。 -/
inductive BaseTag where
  | segments | directFractals | klineOverlap | ticks
  deriving DecidableEq

/-- 级数带基底索引：例如线段基底的第一级与逐笔基底的第一级是不同类型。
[035:14] 如果理论就此打住，那么一个循环定义就不可避免。要解决该循环，级别的概念是不可缺少的。有了级别，一个严格的递归式定义才可以展开。 -/
structure BaseLevel (tag : BaseTag) where
  depth : Nat
  deriving DecidableEq

/-- 只在相同标签下比较递归深度。
[063:20] 再次强调，什么级别的图和什么级别的中枢没有任何必然关系，走势类型以及中枢就如同显微镜下的观察物，是客观存在的，其存在性由上面所说最原始的递归定义保证，而级别的图，就如同显微镜，不同倍数的看这客观的图就看到不同的精细程度，如此而已。
[二级旁证 102:346] 现在，就纯粹探讨技术上的问题，不说那些已经反复说过的东西。看看下面6124点下来的60分钟图，大的走势就一目了然。这次下来，目前只走了4个线段，连一个1分钟的中枢都没形成，注意，这是60分钟图上的1分钟中枢。 -/
def BaseLevel.atMost {tag : BaseTag} (a b : BaseLevel tag) : Bool := a.depth ≤ b.depth

/-- 顺序下标与单点成交价；成交之间相隔多久不改变价格比较。
[053:22] 当然，有这最精细最严格的方法，就是从最低级别的分笔中逐步组合分析上来，这样就不存在上面的问题，但这样太累，而且毫无必要。 -/
structure Tick (P : Type u) where
  time : Nat
  price : P
  deriving DecidableEq

/-- 递归输入序列保留基底标签；跨基底比较必须显式退回裸交替列。
[084:54] 本ID关于中枢等的定义，其实一直没有改变过，因为中枢定义的关键，在于定义的递归性。一般的递归定义，由两部分组成，一、f1(a0)=a1；二、f2(an)=an+1；关于第二条的中枢过程规则，是一直没有任何改变的，而关于第一条，其实，可以随意设置任何的，都不会改变中枢定义的递归性。而且，任何有点数学常识的都知道，f1(a0)=a1之前是不需要再有什么递归性的，也就是，一和二之间的f1、f2可以是完全不同的两个函数。 -/
structure BaseOutput (tag : BaseTag) (P : Type u) [LinearOrder P] where
  seq : AltSeq P
  deriving DecidableEq

/-- 基底由标签索引。接口只指定原始输入与产出的 M4 交替区间，不预设评价函数。
[084:54] 本ID关于中枢等的定义，其实一直没有改变过，因为中枢定义的关键，在于定义的递归性。一般的递归定义，由两部分组成，一、f1(a0)=a1；二、f2(an)=an+1；关于第二条的中枢过程规则，是一直没有任何改变的，而关于第一条，其实，可以随意设置任何的，都不会改变中枢定义的递归性。而且，任何有点数学常识的都知道，f1(a0)=a1之前是不需要再有什么递归性的，也就是，一和二之间的f1、f2可以是完全不同的两个函数。
[101:58] 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。 -/
structure BaseInterface (tag : BaseTag) (P : Type u) [LinearOrder P] where
  Input : Type u
  build : Input → BaseOutput tag P

/-- 默认线段基底：包含处理、局部分型及成笔选择、再从指定笔下标划段。
全程保留实际区间；不调用端点标准化视图。
[063:22] 如果我们首先确立了显微镜的倍数，也就是说，例如我们把1分钟图作为最基本的图，那么就可以开始定义上一课程说的分型、笔、线段等等。有了线段，就可以定义1分钟的中枢，然后就是1分钟的走势类型，然后按照递归的方法，可以逐步定义5分钟、30分钟、日、周、月、季度、年的中枢和走势类型。
[072:62] 分型-笔-线段-最小级别中枢-各级别中枢、走势类型 -/
def segmentBase (policy : InitIncludePolicy) (r : PenRule := oldPenRule) (start : Nat := 0)
    (cfg : SegRuleConfig := .main) : BaseInterface .segments P where
  Input := List (Bar P)
  build xs := ⟨parseSegments cfg (parsePens r (klineNormalize policy xs)) start⟩

/-- 分型直连只合并连续同性候选，等值留早；不作成笔间距检验。
[077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。
[084:52] 其次，分型只是中枢与走势级别递归定义的一个启始程序，甚至可以说，并不是本ID理论中必然需要的东西，其目的，不过是为了中枢等的递归性定义中给出其最开始的部分，完全可以用别的定义去取代。例如，我们可以用收盘的价位去定义顶分型、低分型结构，也可以用成交量给出相应的递归开始部分，只要能保证分解的唯一性，就可以。 -/
def directPivots (fs : List (LocalFractal P)) : List (LocalFractal P) :=
  (fs.foldl (fun stack f => match stack with
    | [] => [f]
    | a :: rest =>
      if a.kind ≠ f.kind then f :: stack
      else if (if a.kind = .top then a.extreme < f.extreme else f.extreme < a.extreme)
        then f :: rest else stack) []).reverse

/-- 将每对相邻异性局部分型直接连接，即便两分型共用 K 线。
[084:52] 其次，分型只是中枢与走势级别递归定义的一个启始程序，甚至可以说，并不是本ID理论中必然需要的东西，其目的，不过是为了中枢等的递归性定义中给出其最开始的部分，完全可以用别的定义去取代。例如，我们可以用收盘的价位去定义顶分型、低分型结构，也可以用成交量给出相应的递归开始部分，只要能保证分解的唯一性，就可以。
[101:58] 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。 -/
def fractalDirectBase (policy : InitIncludePolicy) : BaseInterface .directFractals P where
  Input := List (Bar P)
  build xs :=
    let pivots := directPivots (scanLocalFractals (klineNormalize policy xs))
    match pivots with
    | [] => ⟨⟨[], .nil⟩⟩
    | a :: rest =>
      let runs := (pivots.zip rest).map fun (x, y) =>
        let r : Bar P := ⟨min x.extreme y.extreme, max x.extreme y.extreme,
          (min_le_left _ _).trans (le_max_left _ _)⟩
        let s : Span := ⟨min x.extremeAt y.extremeAt, max x.extremeAt y.extremeAt,
          (Nat.min_le_left _ _).trans (Nat.le_max_left _ _)⟩
        (r, s)
      ⟨(alternateRanges (if a.kind = .bottom then .up else .down) runs).1⟩

/-- 按相邻原始区间判向：两端同升或同降（至少一端严格）才定向；
完全持平或两端向相反方向移动时暂不换向。单点区间上就是严格价格涨跌。
[018:58] 由此，上一章作业三“盘整的高低点是如何造成的”就有了相应的答案：无论离开与返回的走势类型是何种级别的，在站最低级别上看，例如把1分钟图当成最低级别，那么最后连接离开与返回走势类型连接处的最低级别图，只能有两种可能：三根以上1分钟K线的来回重叠震荡后回头；
[064:14] 别说1分钟图，分笔图也没问题，这就是本ID理论所构筑几何结构的力量。 -/
def rangeStep (a b : Bar P) : Option Dir :=
  if a = b then none
  else if a.lo ≤ b.lo ∧ a.hi ≤ b.hi then some .up
  else if b.lo ≤ a.lo ∧ b.hi ≤ a.hi then some .down
  else none

/-- 同方向持续时扩张实际凸包，反转时把前一个观测作为两段共有转折。
开头的无方向观测归入首段；若全程无方向则没有段。
[018:58] 由此，上一章作业三“盘整的高低点是如何造成的”就有了相应的答案：无论离开与返回的走势类型是何种级别的，在站最低级别上看，例如把1分钟图当成最低级别，那么最后连接离开与返回走势类型连接处的最低级别图，只能有两种可能：三根以上1分钟K线的来回重叠震荡后回头；
[064:14] 别说1分钟图，分笔图也没问题，这就是本ID理论所构筑几何结构的力量。 -/
def priceRuns : List (Bar P × Span) → AltSeq P
  | [] => ⟨[], .nil⟩
  | a :: rest =>
    let (first?, doneRev) := walk a a none none [] rest
    match first? with
    | none => ⟨[], .nil⟩
    | some d => (alternateRanges d doneRev.reverse).1
where
  /-- current 是当前整段凸包，prev 是相邻方向比较所用的原始观测。
  [018:58] 由此，上一章作业三“盘整的高低点是如何造成的”就有了相应的答案：无论离开与返回的走势类型是何种级别的，在站最低级别上看，例如把1分钟图当成最低级别，那么最后连接离开与返回走势类型连接处的最低级别图，只能有两种可能：三根以上1分钟K线的来回重叠震荡后回头； -/
  walk (prev current : Bar P × Span) (first dir : Option Dir)
      (doneRev : List (Bar P × Span)) : List (Bar P × Span) → Option Dir × List (Bar P × Span)
    | [] => (first, current :: doneRev)
    | x :: xs =>
      let join := fun (a b : Bar P × Span) => (hullInterval a.1 [b.1], a.2.join b.2)
      match rangeStep prev.1 x.1 with
      | none => walk x (join current x) first dir doneRev xs
      | some d =>
        if dir.isSome && dir ≠ some d then
          walk x (join prev x) first (some d) (current :: doneRev) xs
        else walk x (join current x) (first.orElse fun _ => some d) (some d) doneRev xs

/-- 先按同一开头策略消除包含，再按规范形涨跌切段，跨度仍指向原始 K 线。
待 `needs-fable` 最终裁定 `U-3`。
[018:58] 由此，上一章作业三“盘整的高低点是如何造成的”就有了相应的答案：无论离开与返回的走势类型是何种级别的，在站最低级别上看，例如把1分钟图当成最低级别，那么最后连接离开与返回走势类型连接处的最低级别图，只能有两种可能：三根以上1分钟K线的来回重叠震荡后回头； -/
def klineOverlapBase (policy : InitIncludePolicy) : BaseInterface .klineOverlap P where
  Input := List (Bar P)
  build xs := ⟨priceRuns ((klineNormalize policy xs).map fun b => (b.range, b.source))⟩

/-- 成交按严格递增的顺序下标输入。等价成交不换向；输出跨度沿用成交下标。
[053:22] 当然，有这最精细最严格的方法，就是从最低级别的分笔中逐步组合分析上来，这样就不存在上面的问题，但这样太累，而且毫无必要。
[064:14] 别说1分钟图，分笔图也没问题，这就是本ID理论所构筑几何结构的力量。 -/
def tickBase : BaseInterface .ticks P where
  Input := { ts : List (Tick P) // ts.IsChain (fun a b => a.time < b.time) }
  build ts := ⟨priceRuns (ts.val.map fun t =>
    (⟨t.price, t.price, le_rfl⟩, ⟨t.time, t.time, Nat.le_refl _⟩))⟩

end Chan.Defs.Base
