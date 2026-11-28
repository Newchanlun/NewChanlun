module

public import Chan.Defs.Order.Bar
public import Mathlib.Order.OrderDual
public import Mathlib.Data.List.Dedup
public import Mathlib.Order.Fin.Basic
public import Mathlib.Order.Monotone.Basic

@[expose] public section

namespace Chan.Defs.Path

open Chan.Defs.Order
variable {P Q : Type _} [LinearOrder P] [LinearOrder Q]

/-- 反序后旧高点是新低点，旧低点是新高点。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def dualBar (b : Bar P) : Bar (OrderDual P) := ⟨OrderDual.toDual b.hi, OrderDual.toDual b.lo, b.ordered⟩

/-- 严格保序的换价既保留分离也保留端点相等。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
structure OrderEmb (P Q : Type _) [LinearOrder P] [LinearOrder Q] where
  apply : P → Q
  le_iff : ∀ a b, apply a ≤ apply b ↔ a ≤ b

/-- 严格单调映射给出保序且反射序的嵌入。 -/
def OrderEmb.strict (f : P → Q) (h : StrictMono f) : OrderEmb P Q :=
  ⟨f, fun _ _ => h.le_iff_le⟩

/-- 两端各取一次像，不添加任何价格。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
def mapBarEmb (f : OrderEmb P Q) (b : Bar P) : Bar Q :=
  ⟨f.apply b.lo, f.apply b.hi, (f.le_iff _ _).2 b.ordered⟩

/-- 有界小模型保留区间顺序、相等和相触关系。

[101:58] 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。
-/
structure SmallModel (n bound : Nat) where
  cells : List (Bar (Fin bound))
  length_eq : cells.length = n
  deriving DecidableEq

/-- 原始自然数端点表是否可编码为指定大小的小模型。 -/
abbrev SmallModel.Valid (n bound : Nat) (cells : List (Nat × Nat)) : Prop :=
  cells.length = n ∧ ∀ c ∈ cells, c.1 ≤ c.2 ∧ c.2 < bound

/-- 先去重，再数严格低于目标的端点。重复价同秩，不消耗额外格点。 -/
def SmallModel.compress (bars : List (Bar P)) : SmallModel bars.length (2 * bars.length + 1) :=
  let ends := bars.map Bar.lo ++ bars.map Bar.hi
  let distinct := ends.dedup
  let rank (p : P) : Fin (2 * bars.length + 1) :=
    ⟨distinct.countP (fun q => decide (q < p)), by
      have hn := (List.countP_le_length (l := distinct) (p := fun q => decide (q < p)))
      have hd : distinct.length ≤ 2 * bars.length := by
        simpa [distinct, ends, Nat.two_mul] using ends.dedup_sublist.length_le
      omega⟩
  ⟨bars.map (fun b => ⟨rank b.lo, rank b.hi, by
    change distinct.countP (fun q => decide (q < b.lo)) ≤
      distinct.countP (fun q => decide (q < b.hi))
    exact List.countP_mono_left (fun q _ h => decide_eq_true (lt_of_lt_of_le (of_decide_eq_true h) b.ordered))⟩),
    by simp⟩

end Chan.Defs.Path
