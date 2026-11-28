module

public import Chan.Defs.Alt.Basic
public import Chan.Defs.Order.IntervalAlg

@[expose] public section

namespace Chan.Defs.Base

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

end Chan.Defs.Base
