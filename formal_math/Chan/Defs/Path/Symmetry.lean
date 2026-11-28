module

public import Chan.Defs.Order.Bar

@[expose] public section

namespace Chan.Defs.Path

open Chan.Defs.Order
/-- 同一价格载体的反序副本。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def PriceDual (P : Type _) := P

/-- 反序副本交换比较的左右项。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
instance {P : Type _} [LE P] : LE (PriceDual P) :=
  ⟨fun a b => (show P from b) ≤ (show P from a)⟩

/-- 反序沿用原比较器。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
instance {P : Type _} [LE P] [DecidableLE P] : DecidableLE (PriceDual P) :=
  fun a b => inferInstanceAs (Decidable ((show P from b) ≤ (show P from a)))

/-- 颠倒顺序仍为线性序。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
instance {P : Type _} [LE P] [Std.IsLinearOrder P] : Std.IsLinearOrder (PriceDual P) where
  le_refl a := Std.le_refl (show P from a)
  le_trans _ _ _ h k := Std.le_trans (α := P) k h
  le_antisymm _ _ h k := Std.le_antisymm (α := P) k h
  le_total a b := Std.Total.total (r := fun x y : P => x ≤ y) b a

/-- 以反序比较器构造全部区间运算。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
instance {P : Type _} [Std.LinearOrderPackage P] : Std.LinearOrderPackage (PriceDual P) :=
  priceOrder (PriceDual P)

variable {P Q : Type _} [Std.LinearOrderPackage P] [Std.LinearOrderPackage Q]

/-- 把价格放入反序载体，数值本身不变。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def asDual (p : P) : PriceDual P := p

/-- 反序后旧高点是新低点，旧低点是新高点。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def dualBar (b : Bar P) : Bar (PriceDual P) := ⟨asDual b.hi, asDual b.lo, b.ordered⟩

/-- 严格保序的换价既保留分离也保留端点相等。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
structure OrderEmb (P Q : Type _) [Std.LinearOrderPackage P] [Std.LinearOrderPackage Q] where
  apply : P → Q
  strict : ∀ {a b}, a < b → apply a < apply b

/-- 两端各取一次像，不添加任何价格。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
def mapBarEmb (f : OrderEmb P Q) (b : Bar P) : Bar Q :=
  ⟨f.apply b.lo, f.apply b.hi, by
    by_cases h : b.lo = b.hi
    · rw [h]
      exact Std.le_refl _
    · exact Std.le_of_lt (f.strict (Std.lt_of_le_of_ne b.ordered h))⟩

/-- 在 n 根线的全部端点内数严格小于目标的项。相同价格同秩，出现过的不同价格严格分开。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def SmallModel (bars : List (Bar P)) :
    Fin bars.length → Fin (bars.length + bars.length + 1) × Fin (bars.length + bars.length + 1) :=
  let ends := bars.map Bar.lo ++ bars.map Bar.hi
  let rank (p : P) : Fin (bars.length + bars.length + 1) :=
    ⟨ends.countP (fun q => decide (q < p)), Nat.lt_succ_of_le
      (by simpa [ends] using (List.countP_le_length (l := ends) (p := fun q => decide (q < p))))⟩
  fun i => (rank bars[i].lo, rank bars[i].hi)

end Chan.Defs.Path
