module

public import Chan.Defs.Alt.Basic
public import Chan.Defs.Order.IntervalAlg

@[expose] public section

namespace Chan.Defs.Base

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

end Chan.Defs.Base
