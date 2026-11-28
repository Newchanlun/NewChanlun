module

public import Chan.Defs.Base.Kline

@[expose] public section

namespace Chan.Defs.Base

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

end Chan.Defs.Base
