module

public import Chan.Defs.Level.Rule
public import Chan.Defs.Alt.CutChain

/-!
# M6 级别塔

级别塔由底层段序列与逐级（局部下标）切点表构成；判同只比较各级原始切点下标表，
不比较证书（`#2318` 实测结论二）。
-/

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Order Chan.Defs.Alt Chan.Defs.Center

universe u

/-- 逐级段序列：第 0 项为底层，第 `k+1` 项为按第 `k` 项与该级切点表粗化所得。

[053:20]
> 就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。
-/
def levelSeqs (r : BlockRule.{u}) {P : Type u} [LinearOrder P] :
    List (Seg P) → List (List Nat) → List (List (Seg P))
  | cur, [] => [cur]
  | cur, cs :: rest => cur :: levelSeqs r (r.coarsenBy cur cs) rest

/-- 单级切点表合法：严格递增、不越界、首切点为 0、相邻切点构成被接受块（相邻块首尾相接）。

[038:18]
> 显然，一个好的分解，其分解规则下，必须保证分解的唯一性，否则这种分解就绝对不可能是好的分解。
-/
def CutsValid (r : BlockRule.{u}) {P : Type u} [LinearOrder P] (ctx : List (Seg P))
    (cs : List Nat) : Prop :=
  StrictIncr cs ∧ (∀ c ∈ cs, c ≤ ctx.length) ∧ List.headD cs 0 = 0 ∧
  ∀ p ∈ List.zip cs (List.tail cs), r.accepts ctx p.1 p.2 = true

/-- `CutsValid` 可判定。

[038:18]
> 显然，一个好的分解，其分解规则下，必须保证分解的唯一性，否则这种分解就绝对不可能是好的分解。
-/
instance instDecidableCutsValid (r : BlockRule.{u}) {P : Type u} [LinearOrder P]
    (ctx : List (Seg P)) (cs : List Nat) : Decidable (CutsValid r ctx cs) := by
  unfold CutsValid; infer_instance

/-- 塔合法：每一级切点表相对其所在级段序列合法。

[102:38]
> 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式
-/
def TowerValid (r : BlockRule.{u}) {P : Type u} [LinearOrder P] (base : List (Seg P))
    (levels : List (List Nat)) : Prop :=
  ∀ p ∈ List.zip (levelSeqs r base levels) levels, CutsValid r p.1 p.2

/-- `TowerValid` 可判定。

[102:38]
> 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式
-/
instance instDecidableTowerValid (r : BlockRule.{u}) {P : Type u} [LinearOrder P]
    (base : List (Seg P)) (levels : List (List Nat)) : Decidable (TowerValid r base levels) := by
  unfold TowerValid; infer_instance

/-- 级别塔：给定规则 `r` 与底层 `base`，逐级局部切点表及其合法性证书。

[101:52]
> 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。
-/
structure LevelTower (r : BlockRule.{u}) {P : Type u} [LinearOrder P] (base : List (Seg P)) where
  /-- 各级局部切点表（第 `k` 项的下标指向第 `k` 级段序列）。 -/
  levels : List (List Nat)
  /-- 合法性证书。 -/
  valid : TowerValid r base levels

/-- 把局部切点表逐级换算为底层原始下标。

[102:38]
> 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式
-/
def originalCuts : List Nat → List (List Nat) → List (List Nat)
  | _, [] => []
  | prev, cs :: rest =>
    List.map (fun c : Nat => List.getD prev c 0) cs ::
      originalCuts (List.map (fun c : Nat => List.getD prev c 0) cs) rest

/-- 各级原始切点下标表。

[102:38]
> 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式
-/
def LevelTower.cuts {r : BlockRule.{u}} {P : Type u} [LinearOrder P] {base : List (Seg P)}
    (t : LevelTower r base) : List (List Nat) :=
  originalCuts (List.range (base.length + 1)) t.levels

/-- 判同：两座同底同规则的级别塔各级原始切点表逐级相等（不比较证书）。

[038:18]
> 所谓同级别分解，就是把所有走势按一固定级别的走势类型进行分解。根据“缠中说禅走势分解定理”，同级别分解具有唯一性，不存在任何含糊乱分解的可能。
-/
def LevelTower.sameCuts {r : BlockRule.{u}} {P : Type u} [LinearOrder P] {base : List (Seg P)}
    (t₁ t₂ : LevelTower r base) : Prop :=
  t₁.cuts = t₂.cuts

/-- `LevelTower.sameCuts` 可判定。

[038:18]
> 根据“缠中说禅走势分解定理”，同级别分解具有唯一性，不存在任何含糊乱分解的可能。
-/
instance instDecidableSameCuts {r : BlockRule.{u}} {P : Type u} [LinearOrder P]
    {base : List (Seg P)} (t₁ t₂ : LevelTower r base) : Decidable (t₁.sameCuts t₂) := by
  unfold LevelTower.sameCuts; infer_instance

/-- 级别塔第 `lvl` 级的段序列（越界为空）。

[053:20]
> 就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。
-/
def LevelTower.levelSeq {r : BlockRule.{u}} {P : Type u} [LinearOrder P] {base : List (Seg P)}
    (t : LevelTower r base) (lvl : Nat) : List (Seg P) :=
  List.getD (levelSeqs r base t.levels) lvl []

end Chan.Defs.Level
