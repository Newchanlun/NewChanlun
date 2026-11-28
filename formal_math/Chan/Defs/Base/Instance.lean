module

public import Chan.Defs.Base.Segment

@[expose] public section

namespace Chan.Defs.Base

open Chan.Defs.Order Chan.Defs.Alt

universe u

variable {P : Type u} [LinearOrder P]

/-- 四种基底的具名标签，作为类型索引使不同基底产出的级别不可直接比较。
[084:52] 其次，分型只是中枢与走势级别递归定义的一个启始程序，甚至可以说，并不是本ID理论中必然需要的东西，其目的，不过是为了中枢等的递归性定义中给出其最开始的部分，完全可以用别的定义去取代。例如，我们可以用收盘的价位去定义顶分型、低分型结构，也可以用成交量给出相应的递归开始部分，只要能保证分解的唯一性，就可以。
[二级旁证 102:346] 现在，就纯粹探讨技术上的问题，不说那些已经反复说过的东西。看看下面6124点下来的60分钟图，大的走势就一目了然。这次下来，目前只走了4个线段，连一个1分钟的中枢都没形成，注意，这是60分钟图上的1分钟中枢。 -/
inductive BaseTag where
  | segment
  | fractalDirect
  | klineOverlap
  | tick
  deriving DecidableEq

/-- 分笔成交点：顺序索引与单点成交价。
[053:22] 当然，有这最精细最严格的方法，就是从最低级别的分笔中逐步组合分析上来，这样就不存在上面的问题，但这样太累，而且毫无必要。 -/
structure Tick (P : Type u) where
  idx : Nat
  price : P
  deriving DecidableEq

/-- 单点成交视为退化闭区间 `[p, p]`。
[064:14] 别说1分钟图，分笔图也没问题，这就是本ID理论所构筑几何结构的力量。 -/
def Tick.toBar (t : Tick P) : Bar P :=
  ⟨t.price, t.price, le_refl t.price⟩

/-- 带基底标签的产出：方向交替区间序列；标签不同则类型不同。
[035:14] 如果理论就此打住，那么一个循环定义就不可避免。要解决该循环，级别的概念是不可缺少的。有了级别，一个严格的递归式定义才可以展开。 -/
structure BaseOutput (tag : BaseTag) (P : Type u) [LinearOrder P] where
  seq : AltSeq P
  deriving DecidableEq

/-- 抽象递归起始程序 `a0` 的接口：基底标签（类型索引）、原始输入类型、确定性产出方向交替区间序列的算子。
接口不内置任何“最好分解”目标函数。
[084:54] 本ID关于中枢等的定义，其实一直没有改变过，因为中枢定义的关键，在于定义的递归性。一般的递归定义，由两部分组成，一、f1(a0)=a1；二、f2(an)=an+1；关于第二条的中枢过程规则，是一直没有任何改变的，而关于第一条，其实，可以随意设置任何的，都不会改变中枢定义的递归性。而且，任何有点数学常识的都知道，f1(a0)=a1之前是不需要再有什么递归性的，也就是，一和二之间的f1、f2可以是完全不同的两个函数。
[101:58] 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。 -/
structure BaseInterface (tag : BaseTag) (P : Type u) [LinearOrder P] where
  Input : Type u
  run : Input → BaseOutput tag P

/-- 读出基底接口携带的标签。
[101:58] 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。 -/
def BaseInterface.tagOf {tag : BaseTag} (_ : BaseInterface tag P) : BaseTag := tag

/-- 默认线段基底：原始 K 线 → 包含处理 → 分型 → 笔 → 线段 → 方向交替区间序列。
[063:22] 如果我们首先确立了显微镜的倍数，也就是说，例如我们把1分钟图作为最基本的图，那么就可以开始定义上一课程说的分型、笔、线段等等。有了线段，就可以定义1分钟的中枢，然后就是1分钟的走势类型，然后按照递归的方法，可以逐步定义5分钟、30分钟、日、周、月、季度、年的中枢和走势类型。
[072:62] 分型-笔-线段-最小级别中枢-各级别中枢、走势类型 -/
def segmentBase (pol : InitIncludePolicy) (r : PenRule) (cfg : SegRuleConfig) (start : Nat) :
    BaseInterface .segment P where
  Input := List (Bar P)
  run bars := ⟨parseSegments cfg (parsePens r (klineNormalize pol bars)) start⟩

/-- 分型直连单步（栈顶在表头）：同性质只留更极端者（相等留先者），相反性质直接接上。
[084:52] 其次，分型只是中枢与走势级别递归定义的一个启始程序，甚至可以说，并不是本ID理论中必然需要的东西，其目的，不过是为了中枢等的递归性定义中给出其最开始的部分，完全可以用别的定义去取代。例如，我们可以用收盘的价位去定义顶分型、低分型结构，也可以用成交量给出相应的递归开始部分，只要能保证分解的唯一性，就可以。 -/
def fractalChainStep (acc : List (LocalFractal P)) (f : LocalFractal P) : List (LocalFractal P) :=
  match acc with
  | [] => [f]
  | g :: rest =>
    if g.kind = f.kind then (if FractalBeats f g then f :: rest else acc)
    else f :: acc

/-- 局部原始分型的交替链（不经严格成笔规则）。
[084:52] 其次，分型只是中枢与走势级别递归定义的一个启始程序，甚至可以说，并不是本ID理论中必然需要的东西，其目的，不过是为了中枢等的递归性定义中给出其最开始的部分，完全可以用别的定义去取代。例如，我们可以用收盘的价位去定义顶分型、低分型结构，也可以用成交量给出相应的递归开始部分，只要能保证分解的唯一性，就可以。 -/
def fractalChain (fs : List (LocalFractal P)) : List (LocalFractal P) :=
  (fs.foldl fractalChainStep []).reverse

/-- 相邻交替分型两两连成段。
[101:58] 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。 -/
def fractalChainSegs : List (LocalFractal P) → List (Seg P)
  | a :: tl@(b :: _) =>
    Seg.mk (fractalPairDir a) (fractalPairRange a b) (fractalPairSpan a b) :: fractalChainSegs tl
  | _ => []

/-- 分型直连基底：原始 K 线 → 包含处理 → 局部原始分型 → 相邻交替分型直连。
[084:52] 其次，分型只是中枢与走势级别递归定义的一个启始程序，甚至可以说，并不是本ID理论中必然需要的东西，其目的，不过是为了中枢等的递归性定义中给出其最开始的部分，完全可以用别的定义去取代。例如，我们可以用收盘的价位去定义顶分型、低分型结构，也可以用成交量给出相应的递归开始部分，只要能保证分解的唯一性，就可以。
[101:58] 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。 -/
def fractalDirectBase (pol : InitIncludePolicy) : BaseInterface .fractalDirect P where
  Input := List (Bar P)
  run bars := ⟨altSeqOfSegs (fractalChainSegs (fractalChain (scanLocalFractals (klineNormalize pol bars))))⟩

/-- 相邻两根合并 K 线按高点升降给出单步段（区间取两根外包）。
[018:58] 由此，上一章作业三“盘整的高低点是如何造成的”就有了相应的答案：无论离开与返回的走势类型是何种级别的，在站最低级别上看，例如把1分钟图当成最低级别，那么最后连接离开与返回走势类型连接处的最低级别图，只能有两种可能：三根以上1分钟K线的来回重叠震荡后回头； -/
def mergedSteps : List (MergedBar P) → List (Seg P)
  | a :: tl@(b :: _) =>
    Seg.mk (if a.range.hi < b.range.hi then .up else .down) (hullInterval a.range [b.range])
      (a.span.join b.span) :: mergedSteps tl
  | _ => []

/-- K 线重叠基底：最低级别 K 线（经包含处理）按涨跌方向切成交替段。
[018:58] 由此，上一章作业三“盘整的高低点是如何造成的”就有了相应的答案：无论离开与返回的走势类型是何种级别的，在站最低级别上看，例如把1分钟图当成最低级别，那么最后连接离开与返回走势类型连接处的最低级别图，只能有两种可能：三根以上1分钟K线的来回重叠震荡后回头； -/
def klineOverlapBase (pol : InitIncludePolicy) : BaseInterface .klineOverlap P where
  Input := List (Bar P)
  run bars := ⟨altSeqOfSegs (mergedSteps (klineNormalize pol bars))⟩

/-- 两个成交点顺序索引围成的闭跨度。
[063:18] 否则，都从最原始的分笔成交去逐步定义、寻找，那这可操作的操作也没什么操作性了。 -/
def tickSpan (a b : Tick P) : Span :=
  ⟨min a.idx b.idx, max a.idx b.idx, Nat.le_trans (Nat.min_le_left _ _) (Nat.le_max_left _ _)⟩

/-- 相邻成交点的严格涨跌单步段；价格相等不产生方向。
[063:18] 否则，都从最原始的分笔成交去逐步定义、寻找，那这可操作的操作也没什么操作性了。 -/
def tickSteps : List (Tick P) → List (Seg P)
  | a :: tl@(b :: _) =>
    if h : a.price < b.price then
      Seg.mk .up ⟨a.price, b.price, le_of_lt h⟩ (tickSpan a b) :: tickSteps tl
    else if h' : b.price < a.price then
      Seg.mk .down ⟨b.price, a.price, le_of_lt h'⟩ (tickSpan a b) :: tickSteps tl
    else tickSteps tl
  | _ => []

/-- 分笔成交基底：逐笔成交点按严格涨跌单调极值交替分段。
[053:22] 当然，有这最精细最严格的方法，就是从最低级别的分笔中逐步组合分析上来，这样就不存在上面的问题，但这样太累，而且毫无必要。
[064:14] 别说1分钟图，分笔图也没问题，这就是本ID理论所构筑几何结构的力量。 -/
def tickBase : BaseInterface .tick P where
  Input := List (Tick P)
  run ticks := ⟨altSeqOfSegs (tickSteps ticks)⟩

end Chan.Defs.Base
