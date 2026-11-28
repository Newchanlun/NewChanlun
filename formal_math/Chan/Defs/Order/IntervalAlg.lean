module

public import Chan.Defs.Order.Bar

@[expose] public section

namespace Chan.Defs.Order

variable {P : Type _} [LinearOrder P]

/-- 单点公共交也算重叠。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
abbrev overlaps (a b : Bar P) : Prop := max a.lo b.lo ≤ min a.hi b.hi

/-- 首项保证非空，余项逐一收紧交的上下界。
[020:48] 有了上面的定理，就可以很精确地讨论走势中枢的问题了：根据走势中枢的数学表达式： A、B、C，分别的高、低点是a1\a2,b1\b2,c1\c2，则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。 -/
abbrev overlapsList (a : Bar P) (bs : List (Bar P)) : Prop :=
  bs.foldl (fun x b => max x b.lo) a.lo ≤ bs.foldl (fun x b => min x b.hi) a.hi

/-- 只在公共交非空时构造交区间。
[020:48] 有了上面的定理，就可以很精确地讨论走势中枢的问题了：根据走势中枢的数学表达式： A、B、C，分别的高、低点是a1\a2,b1\b2,c1\c2，则中枢的区间就是[max（a2,b2,c2），min（a1,b1,c1）]。 -/
def interInterval (a b : Bar P) (h : overlaps a b) : Bar P :=
  ⟨max a.lo b.lo, min a.hi b.hi, h⟩

/-- 取所有低点之最小和所有高点之最大，不以首尾两段代替包络。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def hullInterval (a : Bar P) (bs : List (Bar P)) : Bar P :=
  bs.foldl (fun x b => ⟨min x.lo b.lo, max x.hi b.hi,
    le_trans (min_le_left _ _) (le_trans x.ordered (le_max_left _ _))⟩) a

/-- 后段整体高于前段。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
abbrev gapUp (a b : Bar P) : Prop := a.hi < b.lo

/-- 后段整体低于前段。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
abbrev gapDown (a b : Bar P) : Prop := gapUp b a

/-- 整段在价位之上，相触不算。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
abbrev strictAbove (a : Bar P) (p : P) : Prop := p < a.lo

/-- 整段在价位之下，相触不算。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
abbrev strictBelow (a : Bar P) (p : P) : Prop := a.hi < p

/-- 核区间与覆盖它的实际波动区间。
[020:54] 特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
structure CoreHull (P : Type _) [LinearOrder P] where
  core : Bar P
  hull : Bar P
  inside : hull.contains core
  deriving DecidableEq

/-- 波动分离分上下；波动相交再按核的位置三分。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
inductive RelPos where
  | separatedUp | separatedDown | expansionUp | expansionDown | coresOverlap
  deriving DecidableEq

/-- 先比较波动区间，再比较核；核相等和嵌套都归核重叠。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
def relPos (a b : CoreHull P) : RelPos :=
  if gapUp a.hull b.hull then .separatedUp
  else if gapDown a.hull b.hull then .separatedDown
  else if gapUp a.core b.core then .expansionUp
  else if gapDown a.core b.core then .expansionDown
  else .coresOverlap

/-- 空表不含可用于成核的公共交。 -/
abbrev overlapsList? : List (Bar P) → Prop
  | [] => False
  | a :: bs => overlapsList a bs

instance (bs : List (Bar P)) : Decidable (overlapsList? bs) :=
  match bs with | [] => isFalse id | a :: tail => inferInstanceAs (Decidable (overlapsList a tail))

/-- 相对位置的声明式几何条件。

[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。
-/
def RelPos.Holds (a b : CoreHull P) : RelPos → Prop
  | .separatedUp => gapUp a.hull b.hull
  | .separatedDown => gapDown a.hull b.hull
  | .expansionUp => gapUp a.core b.core ∧ ¬gapUp a.hull b.hull
  | .expansionDown => gapDown a.core b.core ∧ ¬gapDown a.hull b.hull
  | .coresOverlap => overlaps a.core b.core

instance (a b : CoreHull P) (k : RelPos) : Decidable (k.Holds a b) := by
  cases k <;> unfold RelPos.Holds <;> infer_instance

end Chan.Defs.Order
