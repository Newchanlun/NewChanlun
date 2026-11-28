module

public import Chan.Defs.Base.Kline

@[expose] public section

namespace Chan.Defs.Base

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

end Chan.Defs.Base
