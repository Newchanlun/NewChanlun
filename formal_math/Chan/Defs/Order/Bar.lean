module

public import Init.Data.Order.Lemmas

@[expose] public section

namespace Chan.Defs.Order

/-- 由任意可判定线性序取得标准库的价格序包。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
abbrev priceOrder (P : Type _) [LE P] [DecidableLE P] [Std.IsLinearOrder P] :=
  Std.LinearOrderPackage.ofLE P

/-- 整数价格格。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
instance : Std.LinearOrderPackage Int := priceOrder Int

/-- 非负离散价格格。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
instance : Std.LinearOrderPackage Nat := priceOrder Nat

/-- 有限离散价格格。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
instance (n : Nat) : Std.LinearOrderPackage (Fin n) := priceOrder (Fin n)

/-- 线性序上的等号可精确判定。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
instance (priority := low) {P : Type _} [Std.LinearOrderPackage P] : DecidableEq P :=
  instDecidableEqOfLawfulBEq

variable {P Q : Type _} [Std.LinearOrderPackage P] [Std.LinearOrderPackage Q]

/-- K 线只保留精确的闭区间；单价区间也合法。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
structure Bar (P : Type _) [Std.LinearOrderPackage P] where
  lo : P
  hi : P
  ordered : lo ≤ hi
  deriving DecidableEq

/-- 甲覆盖乙；相同的端点不用分开。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
abbrev Bar.contains (a b : Bar P) : Prop := a.lo ≤ b.lo ∧ b.hi ≤ a.hi

/-- 从甲到乙，两端都升高；不要求出现缺口。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
abbrev Bar.strictUp (a b : Bar P) : Prop := a.lo < b.lo ∧ a.hi < b.hi

/-- 从甲到乙，两端都降低。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
abbrev Bar.strictDown (a b : Bar P) : Prop := b.strictUp a

/-- 显式预处理器允许合并价格，但不能颠倒次序。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
structure Quantizer (P Q : Type _) [Std.LinearOrderPackage P] [Std.LinearOrderPackage Q] where
  apply : P → Q
  monotone : ∀ {a b}, a ≤ b → apply a ≤ apply b

/-- 两端经同一预处理器映射；单调性保证像仍是闭区间。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
def Quantizer.mapBar (q : Quantizer P Q) (b : Bar P) : Bar Q :=
  ⟨q.apply b.lo, q.apply b.hi, q.monotone b.ordered⟩

end Chan.Defs.Order
