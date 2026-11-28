module

public import Chan.Defs.Alt.Basic
public import Chan.Defs.Order.IntervalAlg

/-!
# FM-10d 盲写分离见证（#2321）

甲方：`1fd3f0fe5e7910a66d63070ae82846245b2d5cca`。
乙方：`ea71754a868c0867885b6c83d924e527f782933a`。
两轨共享冻结的区间与交替序列类型。各轨把五个原模块依赖顺序内嵌，
仅替换模块边界和命名空间，保留定义体及声明签名。
-/

@[expose] public section

namespace Chan.Audit.Separation.Fm10d

namespace Opus

section KlineModule

open Chan.Defs.Order Chan.Defs.Alt

variable {P : Type _} [LinearOrder P]

/-- 开头即包含、尚无前一根非包含 K 线时的初始合并方向策略（`#2321` 专项要求一）。
`defaultUp`/`defaultDown` 显式给定初始方向；`pending` 保持方向待定：待定期间相邻包含的 K 线
以外包区间吸收（包含关系下外包区间即为较大那根），并完整记录原始跨度与根数，
直到第一次出现非包含关系、按原文规则定出严格方向为止。不静默丢弃任何原始 K 线。
[065:24] 假设，第n根K线满足第n根与第n+1根的包含关系，而第n根与第n-1根不是包含关系，那么如果gn>=gn-1，那么称第n-1、n、n+1根K线是向上的；如果dn<=dn-1，那么称第n-1、n、n+1根K线是向下的。 -/
inductive InitIncludePolicy where
  | defaultUp
  | defaultDown
  | pending
  deriving DecidableEq

/-- 策略给出的初始方向状态；`none` 表示方向待定。
[065:26] 同样道理，gn>=gn-1与dn<=dn-1不可能同时成立。 -/
def InitIncludePolicy.initDir : InitIncludePolicy → Option Dir
  | .defaultUp => some .up
  | .defaultDown => some .down
  | .pending => none

/-- 合并后 K 线：合并区间、所覆盖的原始 K 线闭索引跨度、所含原始 K 线根数，
以及合并区间高点与低点各自取自的原始 K 线下标（供新笔按原始 K 线计数）。
[065:20] 而包含关系，不符合传递律，也就是说，第1、2根K线是包含关系，第2、3根也是包含关系，但并不意味着第1、3根就有包含关系。因此在K线包含关系的分析中，还要遵守顺序原则，就是先用第1、2根K线的包含关系确认新的K线，然后用新的K线去和第三根比，如果有包含关系，继续用包含关系的法则结合成新的K线，如果没有，就按正常K线去处理。 -/
structure MergedBar (P : Type _) [LinearOrder P] where
  range : Bar P
  span : Span
  rawCount : Nat
  hiIdx : Nat
  loIdx : Nat
  deriving DecidableEq

/-- 单根原始 K 线（下标 `i`）视为尚未合并的合并 K 线。
[065:20] 而包含关系，不符合传递律，也就是说，第1、2根K线是包含关系，第2、3根也是包含关系，但并不意味着第1、3根就有包含关系。因此在K线包含关系的分析中，还要遵守顺序原则，就是先用第1、2根K线的包含关系确认新的K线，然后用新的K线去和第三根比，如果有包含关系，继续用包含关系的法则结合成新的K线，如果没有，就按正常K线去处理。 -/
def MergedBar.single (i : Nat) (b : Bar P) : MergedBar P :=
  ⟨b, ⟨i, i, Nat.le_refl i⟩, 1, i, i⟩

/-- 两闭区间互有包含关系：任一方覆盖另一方，端点相等也算包含（分叉 4）。
[062:28] 当然，实际图形里，有些复杂的关系会出现，就是相邻两K线可以出现如图6这种包含关系，也就是一K线的高低点全在另一K线的范围里，这种情况下，可以这样处理，在向上时，把两K线的最高点当高点，而两K线低点中的较高者当成低点，这样就把两K线合并成一新的K线；反之，当向下时，把两K线的最低点当低点，而两K线高点中的较低者当成高点，这样就把两K线合并成一新的K线。经过这样的处理，所有K线图都可以处理成没有包含关系的图形。 -/
abbrev hasInclusion (a b : Bar P) : Prop := a.contains b ∨ b.contains a

/-- 给定方向的单步包含合并：向上取 `[max lo, max hi]`，向下取 `[min lo, min hi]`。
[065:18] 当向上时，顺次n个包含关系的K线组，等价于[maxdi,maxgi]
[065:18] 向下时，顺次n个包含关系的K线组，等价于[mindi,mingi] -/
def mergePair : Dir → Bar P → Bar P → Bar P
  | .up, a, b => ⟨max a.lo b.lo, max a.hi b.hi,
      max_le (le_trans a.ordered (le_max_left _ _)) (le_trans b.ordered (le_max_right _ _))⟩
  | .down, a, b => ⟨min a.lo b.lo, min a.hi b.hi,
      le_min (le_trans (min_le_left _ _) a.ordered) (le_trans (min_le_right _ _) b.ordered)⟩

/-- 把下标为 `i` 的原始 K 线并入当前合并 K 线：方向已定时按方向合并，方向待定时取外包；
同时累加原始跨度与根数，并更新高低点所在的原始下标（并列时保留较早者）。
[065:20] 而包含关系，不符合传递律，也就是说，第1、2根K线是包含关系，第2、3根也是包含关系，但并不意味着第1、3根就有包含关系。因此在K线包含关系的分析中，还要遵守顺序原则，就是先用第1、2根K线的包含关系确认新的K线，然后用新的K线去和第三根比，如果有包含关系，继续用包含关系的法则结合成新的K线，如果没有，就按正常K线去处理。 -/
def mergeInto (d : Option Dir) (m : MergedBar P) (i : Nat) (b : Bar P) : MergedBar P :=
  let r : Bar P := match d with
    | some e => mergePair e m.range b
    | none => hullInterval m.range [b]
  { range := r
    span := m.span.join ⟨i, i, Nat.le_refl i⟩
    rawCount := m.rawCount + 1
    hiIdx := if m.range.hi = r.hi then m.hiIdx else i
    loIdx := if m.range.lo = r.lo then m.loIdx else i }

/-- 顺序非包含处理的状态机：参数依次为当前方向状态、当前未落定的合并 K 线、下一根原始下标、剩余原始 K 线。
无包含时落定当前合并 K 线，并以“后一根高点严格高于前一根”定向上、否则定向下。
[065:24] 假设，第n根K线满足第n根与第n+1根的包含关系，而第n根与第n-1根不是包含关系，那么如果gn>=gn-1，那么称第n-1、n、n+1根K线是向上的；如果dn<=dn-1，那么称第n-1、n、n+1根K线是向下的。
[065:26] 同样道理，gn>=gn-1与dn<=dn-1不可能同时成立。 -/
def klineNormalizeFrom : Option Dir → Option (MergedBar P) → Nat → List (Bar P) → List (MergedBar P)
  | _, cur, _, [] => cur.toList
  | d, none, i, b :: bs => klineNormalizeFrom d (some (MergedBar.single i b)) (i + 1) bs
  | d, some m, i, b :: bs =>
    if hasInclusion m.range b then
      klineNormalizeFrom d (some (mergeInto d m i b)) (i + 1) bs
    else
      m :: klineNormalizeFrom (some (if m.range.hi < b.hi then .up else .down))
        (some (MergedBar.single i b)) (i + 1) bs

/-- 从左到右的顺序非包含处理函数；开头即包含按 `InitIncludePolicy` 显式处理。价格只做精确比较。
[065:28] 注意，这种定义是唯一的，有统一答案的，就算是本ID，如果弄错了，也就是错，没有任何含糊的地方，是可以在当下或任何时候明确无误地给出唯一答案的，这答案与时间无关，与人无关，是客观的，不可更改的，唯一的要求就是被分析的K线已经走出来。
[081:30] 另外，提一个问题，今天走势的划分，有一些特别的地方，本ID下午说的，有点问题，主要出在，1017的低点5386.47比前一分钟的5386.39点高，所以顶分型的顶在1017那时间，所以那里就是一笔，但图形上粗略看顶在16分那点，下午写东西太快，没有仔细去比较，晚上回来，仔细对比一下数据，才发现那里应该构成一笔，所以整个划分就要有点改变，也就是今天形成1分钟中枢了，该中枢前面一段很简单，关键是第二、三段，究竟怎么划的，能正确划出的，对线段划分也就有点及格了，明天下午再公布答案，可以对比一下。 -/
def klineNormalize (pol : InitIncludePolicy) (bars : List (Bar P)) : List (MergedBar P) :=
  klineNormalizeFrom pol.initDir none 0 bars

/-- 无包含规范形：相邻任意两根合并 K 线均无包含关系。
[062:28] 当然，实际图形里，有些复杂的关系会出现，就是相邻两K线可以出现如图6这种包含关系，也就是一K线的高低点全在另一K线的范围里，这种情况下，可以这样处理，在向上时，把两K线的最高点当高点，而两K线低点中的较高者当成低点，这样就把两K线合并成一新的K线；反之，当向下时，把两K线的最低点当低点，而两K线高点中的较低者当成高点，这样就把两K线合并成一新的K线。经过这样的处理，所有K线图都可以处理成没有包含关系的图形。 -/
abbrev IsInclusionFree (ms : List (MergedBar P)) : Prop :=
  ∀ p ∈ ms.zip ms.tail, ¬ hasInclusion p.1.range p.2.range

end KlineModule

section FractalModule

open Chan.Defs.Order Chan.Defs.Alt

variable {P : Type _} [LinearOrder P]

/-- 中间 K 线高点严格最高且低点严格最高（顶分型三根形态）。
[062:22] 像图1这种，第二K线高点是相邻三K线高点中最高的，而低点也是相邻三K线低点中最高的，本ID给一个定义叫顶分型；图2这种叫底分型，第二K线低点是相邻三K线低点中最低的，而高点也是相邻三K线高点中最低的。 -/
abbrev IsTopTriple (a b c : Bar P) : Prop :=
  a.hi < b.hi ∧ c.hi < b.hi ∧ a.lo < b.lo ∧ c.lo < b.lo

/-- 中间 K 线低点严格最低且高点严格最低（底分型三根形态）。
[062:22] 像图1这种，第二K线高点是相邻三K线高点中最高的，而低点也是相邻三K线低点中最高的，本ID给一个定义叫顶分型；图2这种叫底分型，第二K线低点是相邻三K线低点中最低的，而高点也是相邻三K线高点中最低的。 -/
abbrev IsBottomTriple (a b c : Bar P) : Prop :=
  b.lo < a.lo ∧ b.lo < c.lo ∧ b.hi < a.hi ∧ b.hi < c.hi

/-- 无包含三邻 K 线的四态完全分类：上升、下降、顶分型、底分型。
[062:32] 而图7，就给出了经过以上处理，没有包含关系的图形中，三相邻K线之间可能组合的一个完全分类，其中的二、四，就是分别是顶分型和底分型，一可以叫上升K线，三可以叫下降K线。 -/
inductive TripleKind where
  | up
  | down
  | top
  | bottom
  deriving DecidableEq

/-- 判定连续三根（前提：无包含）K 线的类别；先判顶底分型，余下按前两根高点升降分上升/下降。
[062:32] 而图7，就给出了经过以上处理，没有包含关系的图形中，三相邻K线之间可能组合的一个完全分类，其中的二、四，就是分别是顶分型和底分型，一可以叫上升K线，三可以叫下降K线。 -/
def classifyTriple (a b c : Bar P) : TripleKind :=
  if IsTopTriple a b c then .top
  else if IsBottomTriple a b c then .bottom
  else if a.hi < b.hi then .up
  else .down

/-- 分型只有顶分型与底分型两种。
[062:24] 顶分型的最高点叫该分型的顶，底分型的最低点叫该分型的底，由于顶分型的底和底分型的顶是没有意义的，所以顶分型的顶和底分型的底就可以简称为顶和低。 -/
inductive FractalKind where
  | top
  | bottom
  deriving DecidableEq

/-- 分型种类对应的三根形态条件。
[062:22] 像图1这种，第二K线高点是相邻三K线高点中最高的，而低点也是相邻三K线低点中最高的，本ID给一个定义叫顶分型；图2这种叫底分型，第二K线低点是相邻三K线低点中最低的，而高点也是相邻三K线高点中最低的。 -/
def FractalKind.Holds : FractalKind → Bar P → Bar P → Bar P → Prop
  | .top, a, b, c => IsTopTriple a b c
  | .bottom, a, b, c => IsBottomTriple a b c

/-- 分型形态条件可判定。
[065:30] 而一旦当下的K线走出来，就可以当下按客观标准唯一地找出相应的分型结构，当下的分析和事后的分析，是一样的，分析的结果也是一样的，没有任何的不同。 -/
instance (k : FractalKind) (a b c : Bar P) : Decidable (k.Holds a b c) := by
  cases k <;> unfold FractalKind.Holds <;> infer_instance

/-- 局部原始分型（`#2321` 专项区分之一）：无包含序列中相邻三根合并 K 线构成的顶/底分型，
`center` 为中间那根在合并序列中的下标。只看三根，彼此允许共用 K 线，不经任何取舍过滤。
[062:22] 像图1这种，第二K线高点是相邻三K线高点中最高的，而低点也是相邻三K线低点中最高的，本ID给一个定义叫顶分型；图2这种叫底分型，第二K线低点是相邻三K线低点中最低的，而高点也是相邻三K线高点中最低的。
[065:30] 而一旦当下的K线走出来，就可以当下按客观标准唯一地找出相应的分型结构，当下的分析和事后的分析，是一样的，分析的结果也是一样的，没有任何的不同。 -/
structure LocalFractal (P : Type _) [LinearOrder P] where
  kind : FractalKind
  center : Nat
  left : MergedBar P
  mid : MergedBar P
  right : MergedBar P
  shape : kind.Holds left.range mid.range right.range
  deriving DecidableEq

/-- 分型的极值：顶分型取中间 K 线高点，底分型取中间 K 线低点。
[062:24] 顶分型的最高点叫该分型的顶，底分型的最低点叫该分型的底，由于顶分型的底和底分型的顶是没有意义的，所以顶分型的顶和底分型的底就可以简称为顶和低。 -/
def LocalFractal.extreme (f : LocalFractal P) : P :=
  match f.kind with
  | .top => f.mid.range.hi
  | .bottom => f.mid.range.lo

/-- 分型极值所在的原始 K 线下标（不考虑包含关系的计数基准）。
[062:24] 顶分型的最高点叫该分型的顶，底分型的最低点叫该分型的底，由于顶分型的底和底分型的顶是没有意义的，所以顶分型的顶和底分型的底就可以简称为顶和低。 -/
def LocalFractal.extremeIdx (f : LocalFractal P) : Nat :=
  match f.kind with
  | .top => f.mid.hiIdx
  | .bottom => f.mid.loIdx

/-- 分型三根 K 线的整体波动区间（分型区间）。
[108:18] 站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。 -/
def LocalFractal.range (f : LocalFractal P) : Bar P :=
  hullInterval f.left.range [f.mid.range, f.right.range]

/-- 分型三根所覆盖的原始 K 线跨度。
[062:18] 下面的定义与图，都适合任何周期的K线图。 -/
def LocalFractal.rawSpan (f : LocalFractal P) : Span :=
  f.left.span.join f.right.span

/-- 从合并下标 `i` 起扫描相邻三根，逐一产出局部原始分型（窗口每次右移一根，允许共用 K 线）。
[065:30] 而一旦当下的K线走出来，就可以当下按客观标准唯一地找出相应的分型结构，当下的分析和事后的分析，是一样的，分析的结果也是一样的，没有任何的不同。 -/
def scanLocalFractalsFrom : Nat → List (MergedBar P) → List (LocalFractal P)
  | i, a :: tl@(b :: c :: _) =>
    if h : IsTopTriple a.range b.range c.range then
      ⟨.top, i + 1, a, b, c, h⟩ :: scanLocalFractalsFrom (i + 1) tl
    else if h' : IsBottomTriple a.range b.range c.range then
      ⟨.bottom, i + 1, a, b, c, h'⟩ :: scanLocalFractalsFrom (i + 1) tl
    else scanLocalFractalsFrom (i + 1) tl
  | _, _ => []

/-- 扫描无包含序列的全部局部原始分型（下标从 0 起）。
[065:30] 而一旦当下的K线走出来，就可以当下按客观标准唯一地找出相应的分型结构，当下的分析和事后的分析，是一样的，分析的结果也是一样的，没有任何的不同。 -/
def scanLocalFractals (ms : List (MergedBar P)) : List (LocalFractal P) :=
  scanLocalFractalsFrom 0 ms

/-- 成笔分型（`#2321` 专项区分之二）：经顶底交替、相邻分型不共用 K 线（结合律）与同性质去重取舍后，
被保留作笔端点的分型。类型上与 `LocalFractal` 分离，只能由笔解析或显式包装得到。
[077:34] 如果没有包含关系，3个K线就可以决定一个分型，但注意，任何相邻的分型之间必须满足结合律，也就是，不能有些K线分属不同的分型，这样是不允许的。
[069:16] 打“X”的就是该分型不符合笔所要求分型的规范。这里，只要是两条：一、顶和底之间没有至少一K线；二、不满足顶必须接着底、或底必须接着顶。
[077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
structure RetainedFractal (P : Type _) [LinearOrder P] where
  base : LocalFractal P
  deriving DecidableEq

/-- 分型边沿：顶分型取分型区间下边沿，底分型取分型区间上边沿。只作结构特征与必要条件接口，
不构成成笔的充分条件（B-36）。
[108:18] 站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。
[079:86] 注意，顶分型结构后不一定有底分型结构与顶分型结构有一个非共用的K线，也就是不一定构成笔，但一般来说，如果顶分型后有效跌破5日线，那就没什么大戏了，就算不用搞个笔出来，也会用时间换空间，折腾好一阵子。 -/
def fractalEdge (f : LocalFractal P) : P :=
  match f.kind with
  | .top => f.range.lo
  | .bottom => f.range.hi

end FractalModule

section PenModule

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

end PenModule

section SegmentModule

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

end SegmentModule

section InstanceModule

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

end InstanceModule

end Opus

namespace Astra

section KlineModule

open Chan.Defs.Order Chan.Defs.Alt
variable {P : Type _} [LinearOrder P]

/-- 首对即包含时，由调用者指定方向；首个非包含对出现后改用实际方向。
[065:24] 假设，第n根K线满足第n根与第n+1根的包含关系，而第n根与第n-1根不是包含关系，那么如果gn>=gn-1，那么称第n-1、n、n+1根K线是向上的；如果dn<=dn-1，那么称第n-1、n、n+1根K线是向下的。 -/
structure InitIncludePolicy where
  initial : Dir
  deriving DecidableEq

/-- 闭跨度内的原始 K 线连续。分别记录实现当前低、高价的原始下标，等价取早。
[065:20] 而包含关系，不符合传递律，也就是说，第1、2根K线是包含关系，第2、3根也是包含关系，但并不意味着第1、3根就有包含关系。因此在K线包含关系的分析中，还要遵守顺序原则，就是先用第1、2根K线的包含关系确认新的K线，然后用新的K线去和第三根比，如果有包含关系，继续用包含关系的法则结合成新的K线，如果没有，就按正常K线去处理。
[081:30] 另外，提一个问题，今天走势的划分，有一些特别的地方，本ID下午说的，有点问题，主要出在，1017的低点5386.47比前一分钟的5386.39点高，所以顶分型的顶在1017那时间，所以那里就是一笔，但图形上粗略看顶在16分那点，下午写东西太快，没有仔细去比较，晚上回来，仔细对比一下数据，才发现那里应该构成一笔，所以整个划分就要有点改变，也就是今天形成1分钟中枢了，该中枢前面一段很简单，关键是第二、三段，究竟怎么划的，能正确划出的，对线段划分也就有点及格了，明天下午再公布答案，可以对比一下。 -/
structure MergedBar (P : Type _) [LinearOrder P] where
  range : Bar P
  source : Span
  lowAt : Nat
  highAt : Nat
  deriving DecidableEq

/-- 闭跨度含两个端点，单根计一。
[065:18] 当向上时，顺次n个包含关系的K线组，等价于[maxdi,maxgi] -/
def MergedBar.rawCount (b : MergedBar P) : Nat := b.source.last - b.source.first + 1

/-- 任一闭区间含住另一个；端点相等也算。
[062:28] 当然，实际图形里，有些复杂的关系会出现，就是相邻两K线可以出现如图6这种包含关系，也就是一K线的高低点全在另一K线的范围里，这种情况下，可以这样处理，在向上时，把两K线的最高点当高点，而两K线低点中的较高者当成低点，这样就把两K线合并成一新的K线；反之，当向下时，把两K线的最低点当低点，而两K线高点中的较低者当成高点，这样就把两K线合并成一新的K线。经过这样的处理，所有K线图都可以处理成没有包含关系的图形。 -/
abbrev hasInclusion (a b : Bar P) : Prop := a.contains b ∨ b.contains a

/-- 按指定方向选取低、高端点；两个端点可以出自不同原始 K 线。
[065:18] 当向上时，顺次n个包含关系的K线组，等价于[maxdi,maxgi]
[065:18] 向下时，顺次n个包含关系的K线组，等价于[mindi,mingi] -/
def mergePair (dir : Dir) (a b : MergedBar P) : MergedBar P :=
  match dir with
  | .up =>
    ⟨⟨max a.range.lo b.range.lo, max a.range.hi b.range.hi,
      max_le (a.range.ordered.trans (le_max_left _ _)) (b.range.ordered.trans (le_max_right _ _))⟩,
      a.source.join b.source, if a.range.lo < b.range.lo then b.lowAt else a.lowAt,
      if a.range.hi < b.range.hi then b.highAt else a.highAt⟩
  | .down =>
    ⟨⟨min a.range.lo b.range.lo, min a.range.hi b.range.hi,
      le_min ((min_le_left _ _).trans a.range.ordered) ((min_le_right _ _).trans b.range.ordered)⟩,
      a.source.join b.source, if b.range.lo < a.range.lo then b.lowAt else a.lowAt,
      if b.range.hi < a.range.hi then b.highAt else a.highAt⟩

/-- 原始单根的两种极值均在同一下标。
[065:20] 而包含关系，不符合传递律，也就是说，第1、2根K线是包含关系，第2、3根也是包含关系，但并不意味着第1、3根就有包含关系。因此在K线包含关系的分析中，还要遵守顺序原则，就是先用第1、2根K线的包含关系确认新的K线，然后用新的K线去和第三根比，如果有包含关系，继续用包含关系的法则结合成新的K线，如果没有，就按正常K线去处理。 -/
def MergedBar.singleton (p : Bar P) (i : Nat) : MergedBar P :=
  ⟨p, ⟨i, i, Nat.le_refl _⟩, i, i⟩

/-- 从左到右，只把待定末项与下一根比较；不把包含当作传递关系。
[065:20] 而包含关系，不符合传递律，也就是说，第1、2根K线是包含关系，第2、3根也是包含关系，但并不意味着第1、3根就有包含关系。因此在K线包含关系的分析中，还要遵守顺序原则，就是先用第1、2根K线的包含关系确认新的K线，然后用新的K线去和第三根比，如果有包含关系，继续用包含关系的法则结合成新的K线，如果没有，就按正常K线去处理。 -/
def klineNormalize (policy : InitIncludePolicy) : List (Bar P) → List (MergedBar P)
  | [] => []
  | x :: xs => loop 1 policy.initial [] (.singleton x 0) xs
where
  /-- 已落定部分逆序存放，末根继续接受包含合并。
  [065:20] 而包含关系，不符合传递律，也就是说，第1、2根K线是包含关系，第2、3根也是包含关系，但并不意味着第1、3根就有包含关系。因此在K线包含关系的分析中，还要遵守顺序原则，就是先用第1、2根K线的包含关系确认新的K线，然后用新的K线去和第三根比，如果有包含关系，继续用包含关系的法则结合成新的K线，如果没有，就按正常K线去处理。 -/
  loop (i : Nat) (dir : Dir) (doneRev : List (MergedBar P)) (a : MergedBar P) :
      List (Bar P) → List (MergedBar P)
    | [] => (a :: doneRev).reverse
    | b :: bs =>
      let next := MergedBar.singleton b i
      if hasInclusion a.range b then loop (i+1) dir doneRev (mergePair dir a next) bs
      else loop (i+1) (if a.range.hi < b.hi then .up else .down) (a :: doneRev) next bs

/-- 只检验相邻项；空列、单项也属规范形。
[062:28] 当然，实际图形里，有些复杂的关系会出现，就是相邻两K线可以出现如图6这种包含关系，也就是一K线的高低点全在另一K线的范围里，这种情况下，可以这样处理，在向上时，把两K线的最高点当高点，而两K线低点中的较高者当成低点，这样就把两K线合并成一新的K线；反之，当向下时，把两K线的最低点当低点，而两K线高点中的较低者当成高点，这样就把两K线合并成一新的K线。经过这样的处理，所有K线图都可以处理成没有包含关系的图形。 -/
abbrev IsInclusionFree (xs : List (MergedBar P)) : Prop :=
  xs.IsChain (fun a b => ¬ hasInclusion a.range b.range)

end KlineModule

section FractalModule

open Chan.Defs.Order Chan.Defs.Alt
variable {P : Type _} [LinearOrder P]

/-- 相邻两步各有一个严格方向，故无包含三元组恰有四种形状。
[062:32] 而图7，就给出了经过以上处理，没有包含关系的图形中，三相邻K线之间可能组合的一个完全分类，其中的二、四，就是分别是顶分型和底分型，一可以叫上升K线，三可以叫下降K线。 -/
inductive TripleKind where
  | rising | falling | top | bottom
  deriving DecidableEq

/-- 对区间的高、低两端同时比较；不在无包含定义域内时返回空。
[062:22] 像图1这种，第二K线高点是相邻三K线高点中最高的，而低点也是相邻三K线低点中最高的，本ID给一个定义叫顶分型；图2这种叫底分型，第二K线低点是相邻三K线低点中最低的，而高点也是相邻三K线高点中最低的。 -/
def classifyTriple (a b c : Bar P) : Option TripleKind :=
  if a.strictUp b then
    if b.strictUp c then some .rising else if b.strictDown c then some .top else none
  else if a.strictDown b then
    if b.strictDown c then some .falling else if b.strictUp c then some .bottom else none
  else none

/-- 只标记转向，单调三元组不产生分型。
[062:22] 像图1这种，第二K线高点是相邻三K线高点中最高的，而低点也是相邻三K线低点中最高的，本ID给一个定义叫顶分型；图2这种叫底分型，第二K线低点是相邻三K线低点中最低的，而高点也是相邻三K线高点中最低的。 -/
inductive FractalKind where
  | top | bottom
  deriving DecidableEq

/-- 起始下标对应左根，随后两根的下标各加一；形状证据绑定实际三根 K 线。
[062:22] 像图1这种，第二K线高点是相邻三K线高点中最高的，而低点也是相邻三K线低点中最高的，本ID给一个定义叫顶分型；图2这种叫底分型，第二K线低点是相邻三K线低点中最低的，而高点也是相邻三K线高点中最低的。 -/
structure LocalFractal (P : Type _) [LinearOrder P] where
  first : Nat
  left : MergedBar P
  middle : MergedBar P
  right : MergedBar P
  kind : FractalKind
  shape : classifyTriple left.range middle.range right.range =
    some (match kind with | .top => .top | .bottom => .bottom)
  deriving DecidableEq

/-- 中心下标按合并序列计，不用原始 K 线下标代替。
[077:34] 如果没有包含关系，3个K线就可以决定一个分型，但注意，任何相邻的分型之间必须满足结合律，也就是，不能有些K线分属不同的分型，这样是不允许的。 -/
def LocalFractal.center (f : LocalFractal P) : Nat := f.first + 1

/-- 三根所在的完整价格区间。
[108:18] 站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。 -/
def LocalFractal.range (f : LocalFractal P) : Bar P :=
  hullInterval f.middle.range [f.left.range, f.right.range]

/-- 局部分型覆盖的原始 K 线闭跨度。
[077:34] 如果没有包含关系，3个K线就可以决定一个分型，但注意，任何相邻的分型之间必须满足结合律，也就是，不能有些K线分属不同的分型，这样是不允许的。 -/
def LocalFractal.source (f : LocalFractal P) : Span := f.left.source.join f.right.source

/-- 顶取中心高价，底取中心低价。
[062:24] 顶分型的最高点叫该分型的顶，底分型的最低点叫该分型的底，由于顶分型的底和底分型的顶是没有意义的，所以顶分型的顶和底分型的底就可以简称为顶和低。 -/
def LocalFractal.extreme (f : LocalFractal P) : P :=
  match f.kind with | .top => f.middle.range.hi | .bottom => f.middle.range.lo

/-- 极值所在原始下标，而非合并中心根覆盖区间的任一端点。
[081:30] 另外，提一个问题，今天走势的划分，有一些特别的地方，本ID下午说的，有点问题，主要出在，1017的低点5386.47比前一分钟的5386.39点高，所以顶分型的顶在1017那时间，所以那里就是一笔，但图形上粗略看顶在16分那点，下午写东西太快，没有仔细去比较，晚上回来，仔细对比一下数据，才发现那里应该构成一笔，所以整个划分就要有点改变，也就是今天形成1分钟中枢了，该中枢前面一段很简单，关键是第二、三段，究竟怎么划的，能正确划出的，对线段划分也就有点及格了，明天下午再公布答案，可以对比一下。 -/
def LocalFractal.extremeAt (f : LocalFractal P) : Nat :=
  match f.kind with | .top => f.middle.highAt | .bottom => f.middle.lowAt

/-- 以给定下标为左根，逐个扫描所有三根窗口。
[065:30] 而一旦当下的K线走出来，就可以当下按客观标准唯一地找出相应的分型结构，当下的分析和事后的分析，是一样的，分析的结果也是一样的，没有任何的不同。 -/
def scanFractalsFrom (i : Nat) : List (MergedBar P) → List (LocalFractal P)
  | a :: b :: c :: rest =>
    let later := scanFractalsFrom (i+1) (b :: c :: rest)
    match h : classifyTriple a.range b.range c.range with
    | some .top => ⟨i, a, b, c, .top, h⟩ :: later
    | some .bottom => ⟨i, a, b, c, .bottom, h⟩ :: later
    | _ => later
  | _ => []

/-- 窗口每次只移一根，两个局部候选可共用一根或两根。
[065:30] 而一旦当下的K线走出来，就可以当下按客观标准唯一地找出相应的分型结构，当下的分析和事后的分析，是一样的，分析的结果也是一样的，没有任何的不同。 -/
def scanLocalFractals (xs : List (MergedBar P)) : List (LocalFractal P) := scanFractalsFrom 0 xs

/-- 笔端点与其实际前驱。非首端点与前驱必须异性，且三根窗口不共用合并 K 线。
[077:34] 如果没有包含关系，3个K线就可以决定一个分型，但注意，任何相邻的分型之间必须满足结合律，也就是，不能有些K线分属不同的分型，这样是不允许的。
[069:16] 打“X”的就是该分型不符合笔所要求分型的规范。这里，只要是两条：一、顶和底之间没有至少一K线；二、不满足顶必须接着底、或底必须接着顶。 -/
structure RetainedFractal (P : Type _) [LinearOrder P] where
  pivot : LocalFractal P
  previous : Option (LocalFractal P)
  separated : ∀ p ∈ previous, p.kind ≠ pivot.kind ∧ p.first + 3 ≤ pivot.first
  deriving DecidableEq

/-- 顶取整个分型的下边沿，底取上边沿。边沿本身不足以确认笔。
[108:18] 站在分型的角度，底部就是构成底分型的那个区间，而跌破分型最低点意味着底部构成失败，反之，有效站住分型区间上边沿，就意味着底部构造成功并至少展开一笔一上行情。其实，这都不是什么新鲜内容，但这里统一说出来，还是有好处的。同样，顶部反过来就是。 -/
def fractalEdge (f : LocalFractal P) : P :=
  match f.kind with | .top => f.range.lo | .bottom => f.range.hi

end FractalModule

section PenModule

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

/-- 检验端点异性、不共根、两种跨度及方向性突破；中心间所有合并根的值域
必须落在这两个极值之间。原始根位置由被选择的具体高点或低点给出。
[077:38] 有了上面这基础工作，那这个图就可以看成只有这些分型，分型之间的K线都可以暂时不用管。下面的工作，就是确定笔了。笔，必须是一顶一底，而且顶和底之间至少有一个K线不属于顶分型与底分型。当然，还有一个最显然的，就是在同一笔中，顶分型中最高那K线的区间至少要有一部分高于底分型中最低那K线的区间，如果这条都不满足，也就是顶都在低的范围内或顶比底还低，这显然是不可接受的。
[077:42] 如果前面的底高于后面的底，那么前面的划分显然是错误的，因为按这种划分，该笔是没有完成的，一个底不经过一个顶后就有一个更低的底，这是最典型的笔没完成的情况。 -/
abbrev ValidPenPair (r : PenRule) (bars : List (MergedBar P)) (a b : LocalFractal P) : Prop :=
  a.kind ≠ b.kind ∧ a.first + 3 ≤ b.first ∧
  a.center + r.minMergedSpan ≤ b.center ∧
  a.extremeAt + 1 + r.minRawSpan ≤ b.extremeAt ∧
  (if a.kind = .bottom then a.middle.range.hi < b.middle.range.hi
   else b.middle.range.lo < a.middle.range.lo) ∧
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

/-- 多保留已能连接的转折；笔数相同时，同性端点优先留更高的顶或更低的底，
等价才取较早者。各候选分别留在前驱表里，不因本次平局失去后续连接机会。
[077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
def preferPenPath (x y : List (LocalFractal P)) : List (LocalFractal P) :=
  match x, y with
  | [], _ => y
  | _, [] => x
  | a :: _, b :: _ =>
    if x.length ≠ y.length then (if x.length < y.length then y else x)
    else if a.kind = b.kind ∧ a.extreme ≠ b.extreme then
      if (if a.kind = .top then a.extreme < b.extreme else b.extreme < a.extreme) then y else x
    else if b.first < a.first then y else x

/-- 每个候选各保存一条逆序前驱链。新分型尝试所有可接前驱，所以最近候选走不通
时仍能改接早先分支；只在同一端点合并路径。回溯选定的链后恢复时间顺序。
[069:20] 例如，第一个红箭头和第二个绿箭头之间显然不能构成一笔，也就是说，这两个，只能取一个：如果取第一个红箭头，那么第二个绿箭头就不是笔中分型，那么第二个红箭头，显然是一个底分型，因此，就形成两个底分型连续的划分，显然，这时候，第一个就不算了，这和前面说取第一个红箭头对着的底分型矛盾。所以，这里，只能取第二个绿箭头，这时候，第一个绿箭头对应的顶分型，自然就不算笔中的顶了。
[077:54] 二、如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以X掉；对于底，前面的高于后面的，只保留后面的，前面那个可以X掉。不满足上面情况的，例如相等的，都可以先保留。 -/
def penPivots (r : PenRule) (bars : List (MergedBar P)) : List (LocalFractal P) :=
  let paths := (scanLocalFractals bars).foldl (fun paths pivot =>
    let predecessors := paths.filter (fun path =>
      match path with
      | last :: _ => decide (ValidPenPair r bars last pivot)
      | [] => false)
    let best := predecessors.foldl preferPenPath []
    (pivot :: best) :: paths) []
  let bestOf := fun (k : FractalKind) =>
    (paths.filter (fun path => path.head?.any (fun f => f.kind = k))).foldl preferPenPath []
  (preferPenPath (bestOf .top) (bestOf .bottom)).reverse

/-- 沿所选链建立相邻笔共享的端点。携带上一分型的证据排除了共根、同向相接。
[077:34] 如果没有包含关系，3个K线就可以决定一个分型，但注意，任何相邻的分型之间必须满足结合律，也就是，不能有些K线分属不同的分型，这样是不允许的。 -/
def connectPivots (a : RetainedFractal P) : List (LocalFractal P) → List (Pen P)
  | [] => []
  | b :: bs =>
    if h : a.pivot.kind ≠ b.kind ∧ a.pivot.first + 3 ≤ b.first then
      let next : RetainedFractal P := ⟨b, some a.pivot, by simpa using h⟩
      ⟨a, next, rfl⟩ :: connectPivots next bs
    else []

/-- 从无包含历史取出可连接的笔。单个局部极值本身不构成笔。
[069:20] 例如，第一个红箭头和第二个绿箭头之间显然不能构成一笔，也就是说，这两个，只能取一个：如果取第一个红箭头，那么第二个绿箭头就不是笔中分型，那么第二个红箭头，显然是一个底分型，因此，就形成两个底分型连续的划分，显然，这时候，第一个就不算了，这和前面说取第一个红箭头对着的底分型矛盾。所以，这里，只能取第二个绿箭头，这时候，第一个绿箭头对应的顶分型，自然就不算笔中的顶了。
[065:40] 所以，根据上面的分析，对第二种情况进行相应处理（类似对分型中包含关系的处理），就可以严格地说，先顶后底，构成向下一笔；先底后顶，构成向上一笔。而所有的图形，都可以唯一地分解为上下交替的笔的连接。 -/
def parsePens (r : PenRule) (bars : List (MergedBar P)) : List (Pen P) :=
  match penPivots r bars with
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

/-- 以最后保留的转折为当前笔的起点；末根顺向为延伸、逆向为下一分型构造。
尚无转折时处于构造期；不足两根时使用显式起始方向。
[091:28] 缠中说禅笔定理：任何的当下，在任何时间周期的K线图中，走势必然落在一确定的具有明确方向的笔当中（向上笔或向下笔），而在笔当中的位置，必然只有两种情况：一、在分型构造中。二、分型构造确认后延伸为笔的过程中。
[091:30] 根据这个定理，对于任何的当下走势，在任何一个时间周期里，我们都可以用两个变量构成的数组精确地定义当下的走势。第一个变量，只有两个取值，不妨用1代表向上的笔，-1代表向下的笔；第二个变量也只有两个取值，0代表分型构造中，1代表分型确认延伸为笔的过程中。 -/
def penOnlineState (policy : InitIncludePolicy) (r : PenRule)
    (bars : List (MergedBar P)) : PenOnlineState :=
  let step := match bars.reverse with
    | b :: a :: _ => if a.range.strictUp b.range then Dir.up else Dir.down
    | _ => policy.initial
  match (penPivots r bars).getLast? with
  | none => ⟨step, .forming⟩
  | some f =>
    let d := if f.kind = .bottom then Dir.up else Dir.down
    ⟨d, if step = d then .extending else .forming⟩

end PenModule

section SegmentModule

open Chan.Defs.Order Chan.Defs.Alt
variable {P : Type _} [LinearOrder P]

/-- 主线固定两项选择：按时间逐个假设转折点；无缺口时须先破反向首笔终点，
而非任意三笔即确认。两条答疑仅作对照。
[071:30] 从上面的分析就可以知道，从转折点开始，如果第一笔就破坏了前线段，进而该笔延伸出三笔来，其中第三笔破点第一笔的结束位置，那么，新的线段一定形成，前线段一定结束。
[071:40] 特征序列的分型中，第一元素就是以该假设转折点前线段的最后一个特征元素，第二个元素，就是从这转折点开始的第一笔，显然，这两者之间是同方向的，因此，如果这两者之间有缺口，那么就是第二种情况，否则就是第一种，然后根据定义来考察就可以。
[二级旁证 067:194] ==还是没搞清楚，这里是第一种情况，不存在特征序列的缺口，这种情况，任何三笔其实都构成对前面线段的破坏。
[二级旁证 081:222] 首先要选择原线段待破坏的顶点，这里显然是1，3还没1高，显然不构成待破坏的顶点。这样，5下来破坏了1，然后扩展成线段，那就是标准的第一种情况，和3没什么关系。 -/
inductive SegRuleConfig where
  | chronologicalStrictBreak
  deriving DecidableEq

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
def segmentBreak (d : Dir) (before after : List (Pen P)) : Option SegTermKind :=
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
        observeBreak d mode tip base (i+1) [m] [] false false (s :: t :: rest)
  | _, _ => none

/-- 三笔共交、奇数笔、方向交替且相邻共端。记录起笔下标和确认方式；
无确认方式表示从指定起点已经形成、仍可能延伸的末段。
[065:48] 线段有一个最基本的前提，就是线段的前三笔，必须有重叠的部分，这个前提在前面可能没有特别强调，这里必须特别强调一次。线段至少有三笔，但并不是连续的三笔就一定构成线段，这三笔必须有重叠的部分。
[077:62] 也就是说，和笔一样，线段也不可能从一个顶开始结束于一个顶，或者从一个底开始结束于一个底。由此可见，线段中包含笔的数目，都是单数的。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。 -/
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

/-- 在指定起点逐一试奇数笔候选，不跳到全局极值。先取最早确认的分界；
仍无破坏时取该起点最长的合法开放段，不吞入末尾未成段的反向一笔。
[071:38] 其实，线段的划分，都是可以当下完成的，无非是如下的程序：假设某转折点是两线段的分界点，然后对此用线段划分的两种情况去考察是否满足，如果满足其中一种，那么这点就是真正的线段的分界点；如果不满足，那就不是，原来的线段依然延续，就这么简单。
[079:58] 其实，明白了上几节课，这两个图一定都不难分辨，首先，前提是这两个的前面都没有其他走势了，否则这种分析没意义，前面有其他走势，就有这很多不同的可能变化。 -/
def nextSegment (cfg : SegRuleConfig) (i : Nat) (pens : List (Pen P)) : Option (Segment P) :=
  match cfg, pens with
  | .chronologicalStrictBreak, p :: _ =>
    let sizes := (List.range ((pens.length - 1) / 2)).map (fun n => 3 + 2*n)
    let confirmed := sizes.findSome? fun n =>
      let chunk := pens.take n
      match segmentBreak p.dir chunk (pens.drop n) with
      | none => none
      | reason@(some _) => segmentOfPens i reason chunk
    confirmed.orElse fun _ => sizes.reverse.findSome? (fun n => segmentOfPens i none (pens.take n))
  | _, [] => none

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
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。 -/
def parseSegments (cfg : SegRuleConfig) (pens : List (Pen P)) (start : Nat) : AltSeq P :=
  match (segmentTrace cfg pens start).map Segment.toSeg with
  | [] => ⟨[], .nil⟩
  | s :: ss => (alternateRanges s.dir ((s :: ss).map (fun x => (x.range, x.source)))).1

end SegmentModule

section InstanceModule

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
[063:20] 再次强调，什么级别的图和什么级别的中枢没有任何必然关系，走势类型以及中枢就如同显微镜下的观察物，是客观存在的，其存在性由上面所说最原始的递归定义保证，而级别的图，就如同显微镜，不同倍数的看这客观的图就看到不同的精细程度，如此而已。 -/
def BaseLevel.atMost {tag : BaseTag} (a b : BaseLevel tag) : Bool := a.depth ≤ b.depth

/-- 顺序下标与单点成交价；成交之间相隔多久不改变价格比较。
[053:22] 当然，有这最精细最严格的方法，就是从最低级别的分笔中逐步组合分析上来，这样就不存在上面的问题，但这样太累，而且毫无必要。 -/
structure Tick (P : Type u) where
  time : Nat
  price : P
  deriving DecidableEq

/-- 基底由标签索引。接口只指定原始输入与产出的 M4 交替区间，不预设评价函数。
[084:54] 本ID关于中枢等的定义，其实一直没有改变过，因为中枢定义的关键，在于定义的递归性。一般的递归定义，由两部分组成，一、f1(a0)=a1；二、f2(an)=an+1；关于第二条的中枢过程规则，是一直没有任何改变的，而关于第一条，其实，可以随意设置任何的，都不会改变中枢定义的递归性。而且，任何有点数学常识的都知道，f1(a0)=a1之前是不需要再有什么递归性的，也就是，一和二之间的f1、f2可以是完全不同的两个函数。
[101:58] 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。 -/
structure BaseInterface (tag : BaseTag) (P : Type u) [LinearOrder P] where
  Input : Type u
  build : Input → AltSeq P

/-- 默认线段基底：包含处理、局部分型及成笔选择、再从指定笔下标划段。
全程保留实际区间；不调用端点标准化视图。
[063:22] 如果我们首先确立了显微镜的倍数，也就是说，例如我们把1分钟图作为最基本的图，那么就可以开始定义上一课程说的分型、笔、线段等等。有了线段，就可以定义1分钟的中枢，然后就是1分钟的走势类型，然后按照递归的方法，可以逐步定义5分钟、30分钟、日、周、月、季度、年的中枢和走势类型。
[072:62] 分型-笔-线段-最小级别中枢-各级别中枢、走势类型 -/
def segmentBase (policy : InitIncludePolicy) (r : PenRule := oldPenRule) (start : Nat := 0) :
    BaseInterface .segments P where
  Input := List (Bar P)
  build xs := parseSegments .chronologicalStrictBreak (parsePens r (klineNormalize policy xs)) start

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
    | [] => ⟨[], .nil⟩
    | a :: rest =>
      let runs := (pivots.zip rest).map fun (x, y) =>
        let r : Bar P := ⟨min x.extreme y.extreme, max x.extreme y.extreme,
          (min_le_left _ _).trans (le_max_left _ _)⟩
        let s : Span := ⟨min x.extremeAt y.extremeAt, max x.extremeAt y.extremeAt,
          (Nat.min_le_left _ _).trans (Nat.le_max_left _ _)⟩
        (r, s)
      (alternateRanges (if a.kind = .bottom then .up else .down) runs).1

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

/-- 直接按原始 K 线的涨跌切段，保留重叠区间。不经分型或笔，也不在基底内判中枢。
[018:58] 由此，上一章作业三“盘整的高低点是如何造成的”就有了相应的答案：无论离开与返回的走势类型是何种级别的，在站最低级别上看，例如把1分钟图当成最低级别，那么最后连接离开与返回走势类型连接处的最低级别图，只能有两种可能：三根以上1分钟K线的来回重叠震荡后回头； -/
def klineOverlapBase : BaseInterface .klineOverlap P where
  Input := List (Bar P)
  build xs := priceRuns (xs.zipIdx.map fun (bar, i) => (bar, ⟨i, i, Nat.le_refl _⟩))

/-- 成交按严格递增的顺序下标输入。等价成交不换向；输出跨度沿用成交下标。
[053:22] 当然，有这最精细最严格的方法，就是从最低级别的分笔中逐步组合分析上来，这样就不存在上面的问题，但这样太累，而且毫无必要。
[064:14] 别说1分钟图，分笔图也没问题，这就是本ID理论所构筑几何结构的力量。 -/
def tickBase : BaseInterface .ticks P where
  Input := { ts : List (Tick P) // ts.IsChain (fun a b => a.time < b.time) }
  build ts := priceRuns (ts.val.map fun t =>
    (⟨t.price, t.price, le_rfl⟩, ⟨t.time, t.time, Nat.le_refl _⟩))

end InstanceModule

end Astra


open Chan.Defs.Order Chan.Defs.Alt

/-- 有限见证的闭区间由报告中的两端给出。 -/
def bars (rows : List (Int × Int)) : List (Bar Int) :=
  rows.map fun (lo, hi) => ⟨lo, max lo hi, le_max_left _ _⟩

def obars (xs : List (Bar Int)) : List (Opus.MergedBar Int) :=
  xs.zipIdx.map fun (b, i) => Opus.MergedBar.single i b

def abars (xs : List (Bar Int)) : List (Astra.MergedBar Int) :=
  xs.zipIdx.map fun (b, i) => Astra.MergedBar.singleton b i

def dual {P : Type _} [LinearOrder P] (b : Bar P) : Bar (OrderDual P) :=
  ⟨OrderDual.toDual b.hi, OrderDual.toDual b.lo, b.ordered⟩

def view {P : Type _} [LinearOrder P] (s : Seg P) : Dir × P × P × Nat × Nat :=
  (s.dir, s.range.lo, s.range.hi, s.source.first, s.source.last)

def oview (p : Opus.Pen Int) : Dir × Int × Int × Nat × Nat :=
  (p.dir, p.range.lo, p.range.hi, p.rawSpan.first, p.rawSpan.last)

def aview (p : Astra.Pen Int) : Dir × Int × Int × Nat × Nat :=
  (p.dir, p.range.lo, p.range.hi, p.source.first, p.source.last)

def w1 := bars [(10,20),(12,18),(11,19)]

/-- W1：不定向外包吞并第三根，两种定向策略均保留第三根。 -/
theorem sep_klineNormalize_pending :
    (Opus.klineNormalize .pending w1).length = 1 ∧
    (∀ d : Dir, (Astra.klineNormalize ⟨d⟩ w1).length = 2) := by
  refine ⟨by decide, ?_⟩
  intro d
  cases d <;> decide

def point (x : Int) : Bar Int := ⟨x, x, le_refl _⟩

def equalTriple := (bars [(0,10)])[0]'(by decide)
def w2b := bars [(0,5),(2,10),(3,8)]

/-- W2：在包含域上，甲方的默认标签不随序对偶翻转，乙方始终不分类。 -/
theorem sep_classifyTriple_domain_and_dual :
    Opus.classifyTriple equalTriple equalTriple equalTriple = .down ∧
    Opus.classifyTriple (dual equalTriple) (dual equalTriple) (dual equalTriple) = .down ∧
    Astra.classifyTriple equalTriple equalTriple equalTriple = none ∧
    Astra.classifyTriple (dual equalTriple) (dual equalTriple) (dual equalTriple) = none ∧
    Opus.classifyTriple (w2b[0]'(by decide)) (w2b[1]'(by decide)) (w2b[2]'(by decide)) = .up ∧
    Astra.classifyTriple (w2b[0]'(by decide)) (w2b[1]'(by decide)) (w2b[2]'(by decide)) = none := by
  decide

def w3 := bars [(2,12),(0,10),(3,13),(1,11)]
def w3o := Opus.scanLocalFractals (obars w3)
def w3a := Astra.scanLocalFractals (abars w3)
def w3f₁ := w3a[0]'(by decide)
def w3f₂ := w3a[1]'(by decide)

/-- W3：甲方能构造共根笔；乙方的后继证明排除相同端点。 -/
theorem sep_retainedFractal_shared_bar :
    (Opus.Pen.ofPair ⟨w3o[0]'(by cbv)⟩ ⟨w3o[1]'(by cbv)⟩).rawSpan.first = 1 ∧
    (Opus.Pen.ofPair ⟨w3o[0]'(by cbv)⟩ ⟨w3o[1]'(by cbv)⟩).rawSpan.last = 2 ∧
    IsEmpty {r : Astra.RetainedFractal Int // r.pivot = w3f₂ ∧ r.previous = some w3f₁} := by
  refine ⟨by cbv, by cbv, ⟨?_⟩⟩
  intro ⟨r, hp, hv⟩
  have hs := r.separated w3f₁ (by rw [hv]; simp)
  rw [hp] at hs
  exact (by decide : ¬ w3f₁.first + 3 ≤ w3f₂.first) hs.2

def w4 := bars [(2,5),(0,3),(1,6),(7,10),(9,13),(8,12)]

/-- W4：虽然窗口不共根，两个原始极值之间只有两根，不满足默认新笔规则。 -/
theorem sep_disjointFractalPenRule_default :
    (Opus.parsePens Opus.disjointFractalPenRule (obars w4)).length = 1 ∧
    (Astra.parsePens Astra.disjointFractalPenRule (abars w4)).length = 0 ∧
    (Astra.parsePens (Astra.disjointFractalPenRule ⟨3,0,false⟩) (abars w4)).length = 1 := by
  cbv

def w5a := bars [(12,22),(10,20),(11,21),(4,14),(8,18),(14,24),(12,22)]
def w5ao := Opus.scanLocalFractals (obars w5a)
def w5aa := Astra.scanLocalFractals (abars w5a)
def w5b := bars [(12,22),(10,20),(12,22),(11,23),(8,28),(10,30),(8,28)]

def w5bo {P : Type _} [LinearOrder P] (bs : List (Bar P)) :=
  Opus.scanLocalFractals (bs.zipIdx.map fun (b, i) => Opus.MergedBar.single i b)

def w5ba {P : Type _} [LinearOrder P] (bs : List (Bar P)) :=
  Astra.scanLocalFractals (bs.zipIdx.map fun (b, i) => Astra.MergedBar.singleton b i)

/-- W5a 真实序列：只有乙方拒绝中途下破。W5b 隔离端点判断时以空包络输入
屏蔽中间根；用真实序对偶而非改写比较谓词重算两轨。 -/
theorem sep_validPenPair_envelope_and_dual :
    Opus.ValidPenPair Opus.oldPenRule (w5ao[0]'(by cbv)) (w5ao[3]'(by cbv)) ∧
    ¬ Astra.ValidPenPair Astra.oldPenRule (abars w5a) (w5aa[0]'(by decide)) (w5aa[3]'(by decide)) ∧
    Opus.PenHeightOK ((w5bo w5b)[0]'(by cbv)) ((w5bo w5b)[1]'(by cbv)) ∧
    ¬ Opus.PenHeightOK ((w5bo (w5b.map dual))[0]'(by cbv)) ((w5bo (w5b.map dual))[1]'(by cbv)) ∧
    Astra.ValidPenPair Astra.oldPenRule [] ((w5ba w5b)[0]'(by decide)) ((w5ba w5b)[1]'(by decide)) ∧
    Astra.ValidPenPair Astra.oldPenRule [] ((w5ba (w5b.map dual))[0]'(by decide))
      ((w5ba (w5b.map dual))[1]'(by decide)) := by
  cbv; decide

def w6a := bars [(0,5),(2,10),(1,8)]
def w6b := bars [(4,6),(0,2),(3,5),(6,8),(9,11),(12,14),(10,12),(8,10),(6,8),(4,6),
  (8,10),(12,14),(16,18),(20,22),(18,20)]
def w6bars := obars w6b

def w6o0 : Opus.LocalFractal Int :=
  ⟨.bottom, 1, w6bars[0]'(by decide), w6bars[1]'(by decide), w6bars[2]'(by decide), by decide⟩
def w6o1 : Opus.LocalFractal Int :=
  ⟨.top, 5, w6bars[4]'(by decide), w6bars[5]'(by decide), w6bars[6]'(by decide), by decide⟩
def w6o2 : Opus.LocalFractal Int :=
  ⟨.bottom, 9, w6bars[8]'(by decide), w6bars[9]'(by decide), w6bars[10]'(by decide), by decide⟩
def w6o3 : Opus.LocalFractal Int :=
  ⟨.top, 13, w6bars[12]'(by decide), w6bars[13]'(by decide), w6bars[14]'(by decide), by decide⟩
def w6ba := Astra.scanLocalFractals (abars w6b)

instance {α : Type _} [DecidableEq α] (xs ys : List α) : Decidable (xs.Sublist ys) :=
  decidable_of_iff (xs.isSublist ys) List.isSublist_iff_sublist

/-- W6：乙方同时拒绝非空输入的空分解和漏掉可细分的内部转折笔。 -/
theorem sep_validPenDecomp_empty_and_skip :
    Opus.ValidPenDecomp Opus.oldPenRule (obars w6a) [] ∧
    ¬ Astra.ValidPenDecomp Astra.oldPenRule (abars w6a) [] ∧
    Opus.ValidPenDecomp Opus.oldPenRule (obars w6b)
      [⟨w6o0⟩, ⟨w6o3⟩] ∧
    ¬ Astra.ValidPenDecomp Astra.oldPenRule (abars w6b)
      [w6ba[0]'(by decide), w6ba[3]'(by decide)] := by
  refine ⟨by simp [Opus.ValidPenDecomp], by decide, ?_, by decide⟩
  have scan : Opus.scanLocalFractals (obars w6b) = [w6o0, w6o1, w6o2, w6o3] := by cbv
  simp only [Opus.ValidPenDecomp, scan, List.forall_mem_cons, List.not_mem_nil,
    false_implies, implies_true, and_true, List.reverse_cons, List.reverse_nil, List.cons_append,
    List.nil_append, List.tail_cons, List.zip_cons_cons, List.zip_nil_right, List.take_succ_cons,
    List.take_zero]
  repeat' apply And.intro
  all_goals decide

def w7a := bars [(2,12),(0,10),(1,11),(2,12),(1,11),(0,10),(1,11),(2,12),(3,13),(4,14),(3,13)]
def w7b := bars [(18,19),(19,20),(16,18),(14,16),(12,14),(10,12),(15,18),(23,25),(20,22),
  (17,19),(14,16),(12,13),(14,15)]
def w7c := bars [(2,4),(0,2),(8,10),(13,15),(11,13),(9,11),(7,9),(5,7),(9,11),(12,14),
  (15,17),(18,20),(16,18)]
def w7ca := Astra.scanLocalFractals (abars w7c)

/-- W7a：等值底均能成笔，而确定性端点下标不同。 -/
theorem sep_parsePens_tie_break :
    (Opus.parsePens Opus.oldPenRule (obars w7a)).map oview = [(.up, 0, 14, 5, 9)] ∧
    (Astra.parsePens Astra.oldPenRule (abars w7a)).map aview = [(.up, 0, 14, 1, 9)] := by
  cbv

/-- W7b：甲方撤回首对并从新高起笔；乙方留下原笔。 -/
theorem sep_parsePens_contradiction_backtrack :
    (Opus.parsePens Opus.oldPenRule (obars w7b)).map oview = [(.down, 12, 25, 7, 11)] ∧
    (Astra.parsePens Astra.oldPenRule (abars w7b)).map aview = [(.down, 10, 20, 1, 5)] := by
  cbv

/-- W7c：两条不同长度的分解均饱和；两轨分别选取保首底与保更多笔。 -/
theorem sep_parsePens_nonunique_saturated :
    Astra.ValidPenDecomp Astra.oldPenRule (abars w7c)
      [w7ca[0]'(by decide), w7ca[3]'(by decide)] ∧
    Astra.ValidPenDecomp Astra.oldPenRule (abars w7c)
      [w7ca[1]'(by decide), w7ca[2]'(by decide), w7ca[3]'(by decide)] ∧
    (Opus.parsePens Opus.oldPenRule (obars w7c)).map oview = [(.up, 0, 20, 1, 11)] ∧
    (Astra.parsePens Astra.oldPenRule (abars w7c)).map aview =
      [(.down, 5, 15, 3, 7), (.up, 5, 20, 7, 11)] := by
  exact ⟨by decide, by decide, by cbv, by decide⟩

def w8a := bars [(0,10),(2,12)]
def w8b := bars [(2,12),(0,10),(3,13),(1,11),(4,14),(6,16)]

/-- W8：无分型表返值不同；已创新高仍滞留在构造态的是甲方。 -/
theorem sep_penOnlineState_empty_and_sticky :
    Opus.penOnlineState Opus.oldPenRule (obars w8a) = none ∧
    Astra.penOnlineState ⟨.up⟩ Astra.oldPenRule (abars w8a) = ⟨.up,.forming⟩ ∧
    Opus.penOnlineState Opus.oldPenRule (obars w8b) = some ⟨.up,.building⟩ ∧
    Astra.penOnlineState ⟨.up⟩ Astra.oldPenRule (abars w8b) = ⟨.up,.extending⟩ := by
  cbv

def singletonSpan (i : Nat) : Span := ⟨i,i,Nat.le_refl _⟩

def w10 :=
  ((bars [(10,20),(5,15),(12,14)]).zipIdx).map fun (r,i) => (r, singletonSpan (2*i+1))

def w10o := Opus.stdFeatureSeq .up (w10.map fun (r,s) => ⟨r,s⟩)
def w10a := Astra.stdFeatureSeq .up (w10.map fun (r,s) => ⟨r,s⟩)

/-- W10：甲方留下包含对；乙方递归合并到单一元素。 -/
theorem sep_stdFeatureSeq_cascade_inclusion :
    w10o = [⟨(bars [(10,20)])[0]'(by decide), ⟨1,1,by decide⟩⟩,
      ⟨(bars [(12,15)])[0]'(by decide), ⟨3,5,by decide⟩⟩] ∧
    Opus.hasInclusion (w10o[0]'(by decide)).range (w10o[1]'(by decide)).range ∧
    w10a = [⟨(bars [(12,20)])[0]'(by decide), ⟨1,5,by decide⟩⟩] := by
  decide

/-- 线段见证用指定的笔端价格，不把上游笔解析器的差异混入线段判据。
每个端点的局部形状由对应盲写扫描器计算，原始中心下标距四。 -/
def pivotCandles (start : Dir) (value : Int) : List (Bar Int) :=
  let wing := point (if start = .up then value + 1 else value - 1)
  [wing, point value, wing]

def oPens (prices : List Int) : List (Opus.Pen Int) :=
  Opus.pensOf ((prices.zipIdx).flatMap fun (x,i) =>
    let bs := (pivotCandles (if i % 2 = 0 then .up else .down) x).zipIdx (4*i)
    (Opus.scanLocalFractalsFrom (4*i) (bs.map fun (b,j) => Opus.MergedBar.single j b)).map Opus.RetainedFractal.mk)

def aPens (prices : List Int) : List (Astra.Pen Int) :=
  let fs := (prices.zipIdx).flatMap fun (x,i) =>
    let bs := (pivotCandles (if i % 2 = 0 then .up else .down) x).zipIdx (4*i)
    Astra.scanFractalsFrom (4*i) (bs.map fun (b,j) => Astra.MergedBar.singleton b j)
  match fs with
  | [] => []
  | f :: rest => Astra.connectPivots ⟨f,none,by simp⟩ rest

def w9 := [0,10,5,20,10,18,12]
def w11 := [10,20,0,10]
def w12a := [10,20,5,15,2]
def w12b := [0,15,10,30,20,30,19,25,21,28]
def w12c := [0,20,10,15,5,14,12,18,10,13,8]

def oSegments (cfg : Opus.SegRuleConfig) (xs : List Int) :=
  ((Opus.parseSegments cfg (oPens xs) 0).items.map view)

def aSegments (xs : List Int) :=
  ((Astra.parseSegments .chronologicalStrictBreak (aPens xs) 0).items.map view)

/-- W9、W11、W12：对照确认与顶点配置、段端合法性和三条主线切段见证。 -/
theorem sep_segment_forward_and_parse :
    oSegments .main w9 = [(.up,0,20,1,21)] ∧
    oSegments ⟨.anyThreePens,.eachTurningPoint⟩ w9 = [(.up,0,20,1,13),(.down,10,20,13,25)] ∧
    aSegments w9 = [(.up,0,20,1,21)] ∧
    oSegments ⟨.thirdPenBreaksFirst,.extremeVertex⟩ w12c = [(.up,0,20,1,37)] ∧
    (Opus.Segment.mk? .up 0 (oPens w11) none).isSome = true ∧
    (Astra.segmentOfPens 0 none (aPens w11)).isSome = false ∧
    oSegments .main w12a = [(.down,2,20,5,17)] ∧
    aSegments w12a = [(.up,5,20,1,13)] ∧
    oSegments .main w12b = [(.up,0,30,1,13),(.down,19,30,13,25),(.up,19,28,25,37)] ∧
    aSegments w12b = [(.up,0,30,1,37)] ∧
    oSegments .main w12c = [(.up,0,20,1,29),(.down,8,18,29,41)] ∧
    aSegments w12c = [(.up,0,20,1,37)] := by
  cbv
  repeat' first | rfl | constructor

def w13 := ([11,10,12,14,17,20,16,12,8,5,7,9,12,15,12,9,5,2,3] : List Int).map point

/-- W13：把 W12a 的四笔展开为原始点价 K 线后，整个基底仍分离。 -/
theorem sep_segmentBase_end_to_end :
    ((Opus.segmentBase (P := Int) .defaultUp Opus.oldPenRule .main 0).run w13).seq.items.map view =
      [(.down,2,20,5,17)] ∧
    ((Astra.segmentBase (P := Int) ⟨.up⟩).build w13).items.map view = [(.up,5,20,1,13)] := by
  cbv

def w14 := bars [(10,20),(12,18),(11,19),(12,20),(11,19),(12,20)]
def w15 := bars [(10,20),(10,25),(10,18)]

/-- W14/W15：开头包含策略改变直连结果；单端相等的包含对只有乙方基底换向。 -/
theorem sep_fractalDirect_and_klineOverlap :
    ((Opus.fractalDirectBase (P := Int) .pending).run w14).seq.items.length = 0 ∧
    ((Astra.fractalDirectBase (P := Int) ⟨.up⟩).build w14).items.length = 2 ∧
    ((Astra.fractalDirectBase (P := Int) ⟨.down⟩).build w14).items.length = 1 ∧
    ((Opus.klineOverlapBase (P := Int) .defaultUp).run w15).seq.items.length = 0 ∧
    ((Opus.klineOverlapBase (P := Int) .defaultDown).run w15).seq.items.length = 0 ∧
    ((Opus.klineOverlapBase (P := Int) .pending).run w15).seq.items.length = 0 ∧
    ((Astra.klineOverlapBase (P := Int)).build w15).items.map view =
      [(.up,10,25,0,1),(.down,10,25,1,2)] := by
  cbv

def w16oa : List (Opus.Tick Int) := [⟨0,10⟩,⟨1,10⟩,⟨2,15⟩]
def w16ob : List (Opus.Tick Int) := [⟨0,10⟩,⟨1,15⟩,⟨2,15⟩,⟨3,12⟩]
def w16aa : List (Astra.Tick Int) := [⟨0,10⟩,⟨1,10⟩,⟨2,15⟩]
def w16ab : List (Astra.Tick Int) := [⟨0,10⟩,⟨1,15⟩,⟨2,15⟩,⟨3,12⟩]

/-- W16：平价跨段跨度在甲方断开；乙方保留首个平台和转折平台。 -/
theorem sep_tickBase_flat_span :
    ((Opus.tickBase (P := Int)).run w16oa).seq.items.map view = [(.up,10,15,1,2)] ∧
    ((Astra.tickBase (P := Int)).build ⟨w16aa,by decide⟩).items.map view = [(.up,10,15,0,2)] ∧
    ((Opus.tickBase (P := Int)).run w16ob).seq.items.map view = [(.up,10,15,0,1),(.down,12,15,2,3)] ∧
    ((Astra.tickBase (P := Int)).build ⟨w16ab,by decide⟩).items.map view =
      [(.up,10,15,0,2),(.down,12,15,2,3)] := by
  cbv

end Chan.Audit.Separation.Fm10d
