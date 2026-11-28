module

public import Chan.Defs.Level.Tower

/-!
# M6 合法分解与规范分解

合法分解集合与规范分解分开（清单 B-4）；规范性以声明式谓词刻画，不写成“等于某算法输出”
（清单 B-32）。
-/

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Alt

universe u

/-- 合法分解：逐级切点表构成合法级别塔，且每级至少含一个完整块（切点数至少 2）。

[057:40]
> 当行情走到6点时，34、45、56这三段，就可以看成是一个1分钟中枢了，当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。
-/
def ValidDecomp (r : BlockRule.{u}) {P : Type u} [LinearOrder P] (base : List (Seg P))
    (cs : List (List Nat)) : Prop :=
  TowerValid r base cs ∧ ∀ c ∈ cs, 2 ≤ c.length

/-- `ValidDecomp` 可判定。

[057:40]
> 但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。
-/
instance instDecidableValidDecomp (r : BlockRule.{u}) {P : Type u} [LinearOrder P]
    (base : List (Seg P)) (cs : List (List Nat)) : Decidable (ValidDecomp r base cs) := by
  unfold ValidDecomp; infer_instance

/-- 声明式规范性：每级末切点是该级序列的尾部起点（尾部穷尽，不得提前停止成块），
且最高一级序列从 0 起不再成块（塔已到顶）。

[101:52]
> 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。
-/
def IsCanonical (r : BlockRule.{u}) {P : Type u} [LinearOrder P] (base : List (Seg P))
    (cs : List (List Nat)) : Prop :=
  (∀ p ∈ List.zip (levelSeqs r base cs) cs, TailStart r p.1 (List.getLastD p.2 0)) ∧
  TailStart r (List.getLastD (levelSeqs r base cs) []) 0

/-- `IsCanonical` 可判定。

[101:52]
> 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。
-/
instance instDecidableIsCanonical (r : BlockRule.{u}) {P : Type u} [LinearOrder P]
    (base : List (Seg P)) (cs : List (List Nat)) : Decidable (IsCanonical r base cs) := by
  unfold IsCanonical; infer_instance

/-- 规范分解：同时合法且规范的逐级切点表。

[102:38]
> 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式
-/
structure CanonicalDecomp (r : BlockRule.{u}) {P : Type u} [LinearOrder P]
    (base : List (Seg P)) where
  /-- 逐级局部切点表。 -/
  cuts : List (List Nat)
  /-- 合法。 -/
  valid : ValidDecomp r base cuts
  /-- 规范。 -/
  canonical : IsCanonical r base cuts

/-- 规范分解对应的级别塔。

[102:38]
> 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式
-/
def CanonicalDecomp.toTower {r : BlockRule.{u}} {P : Type u} [LinearOrder P]
    {base : List (Seg P)} (d : CanonicalDecomp r base) : LevelTower r base :=
  ⟨d.cuts, d.valid.1⟩

end Chan.Defs.Level
