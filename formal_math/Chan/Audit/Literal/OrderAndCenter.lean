module

/-!
# 缠论原典字面版定义：序、中枢与折线（B-2 / B-3 / B-8 / B-9 / B-38）

本模块仅收载原典字面表述的形式化定义与可判定实例，供后续 `Chan/Audit/Math`
进行反例构造与逻辑核验；完全独立自包含，不导入任何主线模块或外部数学库，亦不包含定理证明。
-/

@[expose] public section

namespace Chan.Audit.Literal

/-- 闭价格区间 `[lo, hi]`，用于刻画中枢与走势段的值域边界。
引文：[020:52]「为方便起见，以后都把这些与中枢方向一致的次级别走势类型称为Z走势段，按中枢中的时间顺序，分别记为Zn等，而相应的高、低点分别记为gn、dn,定义四个指标：GG=max(gn),G=min(gn),D=max(dn),DD=min(dn)，n遍历中枢中所有Zn。」 -/
structure RangeBounds where
  /-- 区间下界。 -/
  lo : Int
  /-- 区间上界。 -/
  hi : Int
  deriving Repr, DecidableEq

/-- 两个整数的较小值。
引文：[020:54]「特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：」 -/
def intMin (a b : Int) : Int :=
  if a ≤ b then a else b

/-- 两个整数的较大值。
引文：[020:54]「特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：」 -/
def intMax (a b : Int) : Int :=
  if a ≤ b then b else a

/-- 闭区间非空性谓词：`lo ≤ hi`。
引文：[020:54]「特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：」 -/
def RangeBounds.valid (r : RangeBounds) : Prop :=
  r.lo ≤ r.hi

/-- `RangeBounds.valid` 的可判定实例。 -/
instance instDecidableRangeBoundsValid (r : RangeBounds) : Decidable r.valid :=
  inferInstanceAs (Decidable (r.lo ≤ r.hi))

/-- 走势段方向：向上或向下。
引文：[078:60]「经过标准化处理后，所有向上线段都是以最低点开始最高点结束，向下线段都是以最高点开始最低点结束，这样，所以线段的连接，就形成一条延续不断、首尾相连的折线，这样，复杂的图形，就会十分地标准化，也为后面的中枢、走势类型等分析提供了最标准且基础的部件。」 -/
inductive SegDir where
  /-- 向上方向。 -/
  | up
  /-- 向下方向。 -/
  | down
  deriving Repr, DecidableEq

/-- 带起止端点与实际极值区间的有向走势段。
引文：[070:48]「没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。」 -/
structure DirectedSeg where
  /-- 线段方向。 -/
  dir : SegDir
  /-- 线段起点价位。 -/
  startPrice : Int
  /-- 线段终点价位。 -/
  endPrice : Int
  /-- 线段内部实际最低价。 -/
  lo : Int
  /-- 线段内部实际最高价。 -/
  hi : Int
  deriving Repr, DecidableEq

/-- 提取有向走势段的值域区间 `[lo, hi]`。
引文：[054:54]「三个小括弧里的1分钟中枢重叠构成了大括弧里的5分钟高一级别中枢。中枢的区间是[d2，g5]，注意，这时候，就要把1分钟的走势当成线段，小括弧里的都是线段，高低点就是这线段的端点。」 -/
def DirectedSeg.toRange (s : DirectedSeg) : RangeBounds :=
  { lo := s.lo, hi := s.hi }

/-! ### B-2：三段相连必有重叠的字面断言 -/

/-- 单段非退化且端点恰为极值的折线段谓词（用于刻画原典所举的“N 字”三段）。
引文：[二级旁证 019:1058]「一个最简单的例子，你自己画一个N字，上、下、上，无论你怎么画都画不出一个没重合的。」 -/
def b2_isEndpointExtremumSeg (s : DirectedSeg) : Prop :=
  (s.dir = .up ∧ s.lo = s.startPrice ∧ s.hi = s.endPrice ∧ s.startPrice < s.endPrice) ∨
  (s.dir = .down ∧ s.hi = s.startPrice ∧ s.lo = s.endPrice ∧ s.endPrice < s.startPrice)

/-- `b2_isEndpointExtremumSeg` 的可判定实例。 -/
instance instDecidableB2IsEndpointExtremumSeg (s : DirectedSeg) :
    Decidable (b2_isEndpointExtremumSeg s) :=
  inferInstanceAs (Decidable (
    (s.dir = .up ∧ s.lo = s.startPrice ∧ s.hi = s.endPrice ∧ s.startPrice < s.endPrice) ∨
    (s.dir = .down ∧ s.hi = s.startPrice ∧ s.lo = s.endPrice ∧ s.endPrice < s.startPrice)))

/-- 首尾相连且方向交替（上-下-上或下-上-下）的三段折线前提。
引文：[二级旁证 019:1058]「你说这话证明你连三段怎么找都没搞清楚，三段是互相连着的，三段必然有重叠，根本没有可能有什么光边界重叠的情况。」 -/
def b2_connectedAltTriple (a b c : DirectedSeg) : Prop :=
  b2_isEndpointExtremumSeg a ∧
  b2_isEndpointExtremumSeg b ∧
  b2_isEndpointExtremumSeg c ∧
  a.dir ≠ b.dir ∧
  b.dir ≠ c.dir ∧
  a.endPrice = b.startPrice ∧
  b.endPrice = c.startPrice

/-- `b2_connectedAltTriple` 的可判定实例。 -/
instance instDecidableB2ConnectedAltTriple (a b c : DirectedSeg) :
    Decidable (b2_connectedAltTriple a b c) :=
  inferInstanceAs (Decidable (
    b2_isEndpointExtremumSeg a ∧
    b2_isEndpointExtremumSeg b ∧
    b2_isEndpointExtremumSeg c ∧
    a.dir ≠ b.dir ∧
    b.dir ≠ c.dir ∧
    a.endPrice = b.startPrice ∧
    b.endPrice = c.startPrice))

/-- 三段闭区间存在非空公共重叠（允许单点重叠）。
引文：[065:48]「线段有一个最基本的前提，就是线段的前三笔，必须有重叠的部分，这个前提在前面可能没有特别强调，这里必须特别强调一次。线段至少有三笔，但并不是连续的三笔就一定构成线段，这三笔必须有重叠的部分。」 -/
def b2_tripleCommonOverlap (a b c : RangeBounds) : Prop :=
  intMax (intMax a.lo b.lo) c.lo ≤ intMin (intMin a.hi b.hi) c.hi

/-- `b2_tripleCommonOverlap` 的可判定实例。 -/
instance instDecidableB2TripleCommonOverlap (a b c : RangeBounds) :
    Decidable (b2_tripleCommonOverlap a b c) :=
  inferInstanceAs (Decidable (
    intMax (intMax a.lo b.lo) c.lo ≤ intMin (intMin a.hi b.hi) c.hi))

/-- 三段闭区间存在非退化（严格正宽度，非仅边界单点）公共重叠。
引文：[二级旁证 019:1058]「你说这话证明你连三段怎么找都没搞清楚，三段是互相连着的，三段必然有重叠，根本没有可能有什么光边界重叠的情况。」 -/
def b2_tripleStrictOverlap (a b c : RangeBounds) : Prop :=
  intMax (intMax a.lo b.lo) c.lo < intMin (intMin a.hi b.hi) c.hi

/-- `b2_tripleStrictOverlap` 的可判定实例。 -/
instance instDecidableB2TripleStrictOverlap (a b c : RangeBounds) :
    Decidable (b2_tripleStrictOverlap a b c) :=
  inferInstanceAs (Decidable (
    intMax (intMax a.lo b.lo) c.lo < intMin (intMin a.hi b.hi) c.hi))

/-- B-2 字面断言一：任意首尾相连且方向交替的三段折线必存在非空公共重叠。
所刻画确切命题：答疑 `019:1058` 宣称“三段是互相连着的，三段必然有重叠”（且任何 N 字上下上都画不出无重合）；同时对照 `067:16` 未明写前提的“任何 Si 与 Si+1 之间一定有重合区间”。
引文：[二级旁证 019:1058]「你说这话证明你连三段怎么找都没搞清楚，三段是互相连着的，三段必然有重叠，根本没有可能有什么光边界重叠的情况。」
引文：[067:16]「以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。容易证明，任何Si与Si+1之间，一定有重合区间。而考察序列X1X2…Xn，该序列中， Xi与Xi+1之间并不一定有重合区间，因此，这序列更能代表线段的性质。」 -/
def b2_connectedThreeAlwaysOverlapLiteral : Prop :=
  ∀ a b c : DirectedSeg,
    b2_connectedAltTriple a b c →
    b2_tripleCommonOverlap a.toRange b.toRange c.toRange

/-- B-2 字面断言二：任意首尾相连且方向交替的三段折线不可能仅在边界单点重叠。
所刻画确切命题：答疑 `019:1058` 宣称“根本没有可能有什么光边界重叠的情况”。
引文：[二级旁证 019:1058]「你说这话证明你连三段怎么找都没搞清楚，三段是互相连着的，三段必然有重叠，根本没有可能有什么光边界重叠的情况。」 -/
def b2_connectedThreeNoBoundaryOnlyLiteral : Prop :=
  ∀ a b c : DirectedSeg,
    b2_connectedAltTriple a b c →
    b2_tripleStrictOverlap a.toRange b.toRange c.toRange

/-! ### B-3：`020:60` 含等号可相触的字面第三类买卖点 -/

/-- 中枢核心区间 `[zd, zg]`。
引文：[020:54]「特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：」 -/
structure CenterCore where
  /-- 中枢核心下沿 `ZD`。 -/
  zd : Int
  /-- 中枢核心上沿 `ZG`。 -/
  zg : Int
  deriving Repr, DecidableEq

/-- B-3 字面第三类买点谓词（含等号，允许回试低点恰好触及 `ZG`）。
所刻画确切命题：`020:60` 字面表述“不跌破 ZG”包含 `retestSeg.lo = z.zg` 的等号情形。
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」 -/
def b3_thirdBuyLiteral (z : CenterCore) (leaveSeg retestSeg : RangeBounds) : Prop :=
  z.zd ≤ z.zg ∧
  leaveSeg.valid ∧
  retestSeg.valid ∧
  leaveSeg.hi > z.zg ∧
  retestSeg.lo ≥ z.zg

/-- `b3_thirdBuyLiteral` 的可判定实例。 -/
instance instDecidableB3ThirdBuyLiteral (z : CenterCore) (leaveSeg retestSeg : RangeBounds) :
    Decidable (b3_thirdBuyLiteral z leaveSeg retestSeg) :=
  inferInstanceAs (Decidable (
    z.zd ≤ z.zg ∧
    leaveSeg.valid ∧
    retestSeg.valid ∧
    leaveSeg.hi > z.zg ∧
    retestSeg.lo ≥ z.zg))

/-- B-3 对偶字面第三类卖点谓词（含等号，允许回抽高点恰好触及 `ZD`）。
所刻画确切命题：`020:60`“不跌破 ZG”的对偶卖点表述允许 `retestSeg.hi = z.zd`，与 `054:24` 将 `d1 = g2` 归为中枢震荡相冲突。
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」
引文：[054:24]「当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。」 -/
def b3_thirdSellLiteral (z : CenterCore) (leaveSeg retestSeg : RangeBounds) : Prop :=
  z.zd ≤ z.zg ∧
  leaveSeg.valid ∧
  retestSeg.valid ∧
  leaveSeg.lo < z.zd ∧
  retestSeg.hi ≤ z.zd

/-- `b3_thirdSellLiteral` 的可判定实例。 -/
instance instDecidableB3ThirdSellLiteral (z : CenterCore) (leaveSeg retestSeg : RangeBounds) :
    Decidable (b3_thirdSellLiteral z leaveSeg retestSeg) :=
  inferInstanceAs (Decidable (
    z.zd ≤ z.zg ∧
    leaveSeg.valid ∧
    retestSeg.valid ∧
    leaveSeg.lo < z.zd ∧
    retestSeg.hi ≤ z.zd))

/-- 走势段触及中枢核心区间（闭区间相交，属中枢震荡）。
所刻画确切命题：`054:24` 明确给出边界相触（`d1 = g2`）即属中枢震荡，不构成第三类买卖点。
引文：[054:24]「当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。」 -/
def b3_touchesCenterOscillation (z : CenterCore) (seg : RangeBounds) : Prop :=
  z.zd ≤ z.zg ∧ seg.valid ∧ seg.lo ≤ z.zg ∧ z.zd ≤ seg.hi

/-- `b3_touchesCenterOscillation` 的可判定实例。 -/
instance instDecidableB3TouchesCenterOscillation (z : CenterCore) (seg : RangeBounds) :
    Decidable (b3_touchesCenterOscillation z seg) :=
  inferInstanceAs (Decidable (z.zd ≤ z.zg ∧ seg.valid ∧ seg.lo ≤ z.zg ∧ z.zd ≤ seg.hi))

/-- B-3 边界互斥性字面断言：含等号的字面第三类买卖点不会与中枢震荡重合。
所刻画确切命题：若同时采用 `020:60` 含等号字面三买卖与 `054:24` 触及即震荡，则二者在边界相等处不互斥。
引文：[020:60]「一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点」
引文：[054:24]「当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。」 -/
def b3_literalThirdDisjointFromOscillation : Prop :=
  ∀ (z : CenterCore) (leaveSeg retestSeg : RangeBounds),
    (b3_thirdBuyLiteral z leaveSeg retestSeg → ¬ b3_touchesCenterOscillation z retestSeg) ∧
    (b3_thirdSellLiteral z leaveSeg retestSeg → ¬ b3_touchesCenterOscillation z retestSeg)

/-! ### B-8：带容差近似相等的字面关系 -/

/-- 两整数之差的绝对值。
引文：[064:24]「注意，没有什么精度是十全十美的，例如用相差0.5内看成是相同的，那么如果是0.51呢？这和0.49也没有多大区别。」 -/
def intAbsDiff (a b : Int) : Int :=
  if a ≤ b then b - a else a - b

/-- B-8 带容差 `tol` 的近似相等字面关系（如将价格放大 100 倍，`tol = 50` 即相差 `0.50` 点内视为相同）。
所刻画确切命题：`064:22` 与 `064:24` 提出的“相差 0.5 点内看成相同”的近似相等关系。
引文：[064:22]「当然，你可能要问为什么一定要取整？这没有什么必然性，只是预设的前提，你可以采取严格到小数后两位的精确度，但其实不同软件，对1分钟这么精细的图，都会有数值上的细微差别，所以，所谓的精确，往往不一定就是，而在这么快速变动的市场中，数值有点细微差别，其实没什么不同，例如，还可以用这样的区别方式，就是两者相差0.5点内的看成是一样的。所有预设精度，唯一必须遵守的，就是精度一旦预设，就一定要一路保持。」
引文：[064:24]「注意，没有什么精度是十全十美的，例如用相差0.5内看成是相同的，那么如果是0.51呢？这和0.49也没有多大区别。」 -/
def b8_approxEqLiteral (tol a b : Int) : Prop :=
  intAbsDiff a b ≤ tol

/-- `b8_approxEqLiteral` 的可判定实例。 -/
instance instDecidableB8ApproxEqLiteral (tol a b : Int) :
    Decidable (b8_approxEqLiteral tol a b) :=
  inferInstanceAs (Decidable (intAbsDiff a b ≤ tol))

/-- B-8 传递性字面断言：对正容差 `tol`，近似相等关系满足传递律（构成等价关系的必要条件）。
所刻画确切命题：若把“相差 `tol` 内视为相同”当作等价划分标准，则必须满足传递性；任取 `tol > 0` 即存在三数反例。
引文：[064:24]「注意，没有什么精度是十全十美的，例如用相差0.5内看成是相同的，那么如果是0.51呢？这和0.49也没有多大区别。」 -/
def b8_approxEqTransitiveLiteral (tol : Int) : Prop :=
  ∀ a b c : Int,
    b8_approxEqLiteral tol a b →
    b8_approxEqLiteral tol b c →
    b8_approxEqLiteral tol a c

/-! ### B-9：端点必为极值的字面折线断言 -/

/-- 一般有向线段合法性：起止端点均落在内部实际极值区间 `[lo, hi]` 之内（不要求端点即极值）。
引文：[078:42]「这种情况下，如果那向上笔突破线段B的高点，这时候就会出现，线段的开始点并不是最高点的情况。」 -/
def b9_segRangeConsistent (s : DirectedSeg) : Prop :=
  s.lo ≤ s.startPrice ∧ s.startPrice ≤ s.hi ∧ s.lo ≤ s.endPrice ∧ s.endPrice ≤ s.hi

/-- `b9_segRangeConsistent` 的可判定实例。 -/
instance instDecidableB9SegRangeConsistent (s : DirectedSeg) :
    Decidable (b9_segRangeConsistent s) :=
  inferInstanceAs (Decidable (
    s.lo ≤ s.startPrice ∧ s.startPrice ≤ s.hi ∧ s.lo ≤ s.endPrice ∧ s.endPrice ≤ s.hi))

/-- 两条原始相邻线段方向交替且在原连接点处首尾相连。
引文：[078:58]「注意，这里必须提醒一句，就是这在以前也曾说过，就是，如果线段中，最高或最低点不是线段的端点，那么，在任何以线段为基础的分析中，例如把线段为基础构成最小级别的中枢等，都可以把该线段标准化为最高低点都在端点。因为，在以线段为基础的分析中，都把线段当成一个没有内部结构的基本部件，所以，只需要关心这线段的实际区间就可以，这样就可以只看其高低点。」 -/
def b9_adjacentOriginalConnected (s1 s2 : DirectedSeg) : Prop :=
  s1.dir ≠ s2.dir ∧ s1.endPrice = s2.startPrice

/-- `b9_adjacentOriginalConnected` 的可判定实例。 -/
instance instDecidableB9AdjacentOriginalConnected (s1 s2 : DirectedSeg) :
    Decidable (b9_adjacentOriginalConnected s1 s2) :=
  inferInstanceAs (Decidable (s1.dir ≠ s2.dir ∧ s1.endPrice = s2.startPrice))

/-- B-9 字面标准化映射：将向上线段起终点置为 `(lo, hi)`，向下线段起终点置为 `(hi, lo)`。
所刻画确切命题：`078:58` 与 `078:60` 对单条线段独立执行的“最高低点都在端点”的标准化操作。
引文：[078:58]「注意，这里必须提醒一句，就是这在以前也曾说过，就是，如果线段中，最高或最低点不是线段的端点，那么，在任何以线段为基础的分析中，例如把线段为基础构成最小级别的中枢等，都可以把该线段标准化为最高低点都在端点。因为，在以线段为基础的分析中，都把线段当成一个没有内部结构的基本部件，所以，只需要关心这线段的实际区间就可以，这样就可以只看其高低点。」
引文：[078:60]「经过标准化处理后，所有向上线段都是以最低点开始最高点结束，向下线段都是以最高点开始最低点结束，这样，所以线段的连接，就形成一条延续不断、首尾相连的折线，这样，复杂的图形，就会十分地标准化，也为后面的中枢、走势类型等分析提供了最标准且基础的部件。」 -/
def b9_standardizeSegLiteral (s : DirectedSeg) : DirectedSeg :=
  match s.dir with
  | .up => { s with startPrice := s.lo, endPrice := s.hi }
  | .down => { s with startPrice := s.hi, endPrice := s.lo }

/-- B-9 字面折线连续性断言：原首尾相连的任意两条交替线段经 `b9_standardizeSegLiteral` 标准化后仍首尾相连。
所刻画确切命题：`078:60` 宣称“经过标准化处理后……所有线段的连接，就形成一条延续不断、首尾相连的折线”；当端点不是极值时，标准化会直接造成相邻端点断开。
引文：[078:60]「经过标准化处理后，所有向上线段都是以最低点开始最高点结束，向下线段都是以最高点开始最低点结束，这样，所以线段的连接，就形成一条延续不断、首尾相连的折线，这样，复杂的图形，就会十分地标准化，也为后面的中枢、走势类型等分析提供了最标准且基础的部件。」 -/
def b9_standardizedAlwaysConnectedLiteral : Prop :=
  ∀ s1 s2 : DirectedSeg,
    b9_segRangeConsistent s1 →
    b9_segRangeConsistent s2 →
    b9_adjacentOriginalConnected s1 s2 →
    (b9_standardizeSegLiteral s1).endPrice = (b9_standardizeSegLiteral s2).startPrice

/-! ### B-38：`020:58` 仅列两种关系的不穷尽字面分类 -/

/-- 同级别中枢的四指标结构：`DD ≤ ZD ≤ ZG ≤ GG`。
引文：[020:52]「为方便起见，以后都把这些与中枢方向一致的次级别走势类型称为Z走势段，按中枢中的时间顺序，分别记为Zn等，而相应的高、低点分别记为gn、dn,定义四个指标：GG=max(gn),G=min(gn),D=max(dn),DD=min(dn)，n遍历中枢中所有Zn。」 -/
structure CenterMetrics where
  /-- 围绕中枢波动的最低点 `DD`。 -/
  dd : Int
  /-- 中枢核心下沿 `ZD`。 -/
  zd : Int
  /-- 中枢核心上沿 `ZG`。 -/
  zg : Int
  /-- 围绕中枢波动的最高点 `GG`。 -/
  gg : Int
  deriving Repr, DecidableEq

/-- 中枢四指标序约束：`dd ≤ zd ≤ zg ≤ gg`。
引文：[020:54]「特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：」 -/
def CenterMetrics.valid (c : CenterMetrics) : Prop :=
  c.dd ≤ c.zd ∧ c.zd ≤ c.zg ∧ c.zg ≤ c.gg

/-- `CenterMetrics.valid` 的可判定实例。 -/
instance instDecidableCenterMetricsValid (c : CenterMetrics) : Decidable c.valid :=
  inferInstanceAs (Decidable (c.dd ≤ c.zd ∧ c.zd ≤ c.zg ∧ c.zg ≤ c.gg))

/-- `020:58` 分支一（下跌及其延续）：后 `GG <` 前 `DD`。
引文：[020:58]「缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。」 -/
def b38_centerRelDownLiteral (c1 c2 : CenterMetrics) : Prop :=
  c2.gg < c1.dd

/-- `b38_centerRelDownLiteral` 的可判定实例。 -/
instance instDecidableB38CenterRelDownLiteral (c1 c2 : CenterMetrics) :
    Decidable (b38_centerRelDownLiteral c1 c2) :=
  inferInstanceAs (Decidable (c2.gg < c1.dd))

/-- `020:58` 分支二（上涨及其延续）：后 `DD >` 前 `GG`。
引文：[020:58]「缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。」 -/
def b38_centerRelUpLiteral (c1 c2 : CenterMetrics) : Prop :=
  c2.dd > c1.gg

/-- `b38_centerRelUpLiteral` 的可判定实例。 -/
instance instDecidableB38CenterRelUpLiteral (c1 c2 : CenterMetrics) :
    Decidable (b38_centerRelUpLiteral c1 c2) :=
  inferInstanceAs (Decidable (c2.dd > c1.gg))

/-- `020:58` 分支三（形成高级别中枢）：`(后ZG < 前ZD ∧ 后GG ≥ 前DD) ∨ (后ZD > 前ZG ∧ 后DD ≤ 前GG)`。
引文：[020:58]「缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。」 -/
def b38_centerRelHigherLiteral (c1 c2 : CenterMetrics) : Prop :=
  (c2.zg < c1.zd ∧ c2.gg ≥ c1.dd) ∨ (c2.zd > c1.zg ∧ c2.dd ≤ c1.gg)

/-- `b38_centerRelHigherLiteral` 的可判定实例。 -/
instance instDecidableB38CenterRelHigherLiteral (c1 c2 : CenterMetrics) :
    Decidable (b38_centerRelHigherLiteral c1 c2) :=
  inferInstanceAs (Decidable (
    (c2.zg < c1.zd ∧ c2.gg ≥ c1.dd) ∨ (c2.zd > c1.zg ∧ c2.dd ≤ c1.gg)))

/-- B-38 字面分类穷尽性断言：`020:58` 所列三种关系覆盖任意两个合法同级别中枢的位置关系。
所刻画确切命题：`020:58` 仅按外缘分离与核心分离下外缘重叠列出分支，漏掉了两中枢核心区间本身存在重叠（或单点相触）等情形。
引文：[020:58]「缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。」 -/
def b38_centerTheorem2ExhaustiveLiteral : Prop :=
  ∀ c1 c2 : CenterMetrics,
    c1.valid →
    c2.valid →
    b38_centerRelDownLiteral c1 c2 ∨
    b38_centerRelUpLiteral c1 c2 ∨
    b38_centerRelHigherLiteral c1 c2

end Chan.Audit.Literal
