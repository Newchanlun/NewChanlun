module

public import ChanExplore.Proto2318.Basic

/-!
# 逐级粗化、混合政策与中枢生成证书

- `coarsen`：按切点表取各块的实际值域，得到上一级的区间序列。
- `ValidTower`：每级各用一条政策的多级规范。政策表的长度就是考虑到第几级，
  更高的级别不出现。
- `Cert`：高一级中枢的三种生成方式，各有自己的判定条件，互不代替。

证书统一用第 0 级的原始下标定位，校验只读第 0 级序列与各级切点表。
-/

@[expose] public section

namespace ChanExplore.Proto2318

/-- 一组区间的实际值域。空表取空区间。 -/
def hull : Seq → Iv
  | [] => ⟨1, 0⟩
  | x :: xs => xs.foldl (fun acc y => ⟨min acc.lo y.lo, max acc.hi y.hi⟩) x

/-- 按切点表取各块的实际值域。末切点之后的尾部不进上一级。 -/
def coarsen (S : Seq) : List Nat → Seq
  | a :: b :: rest => hull ((S.drop a).take (b - a)) :: coarsen S (b :: rest)
  | _ => []

/-- 多级规范：第一条政策管第 0 级到第 1 级，之后逐级用粗化后的序列。
各级切点是相对上一级序列的下标。 -/
def ValidTower : List Policy → Seq → List Decomp → Prop
  | [], _, [] => True
  | p :: ps, S, d :: ds => ValidDecomp p S d ∧ ValidTower ps (coarsen S d.cuts) ds
  | _, _, _ => False

instance towerDec : ∀ ps S ds, Decidable (ValidTower ps S ds)
  | [], _, [] => isTrue trivial
  | p :: ps, S, d :: ds =>
    have := towerDec ps (coarsen S d.cuts) ds
    inferInstanceAs (Decidable (ValidDecomp p S d ∧ ValidTower ps (coarsen S d.cuts) ds))
  | [], _, _ :: _ => isFalse (fun h => h)
  | _ :: _, _, [] => isFalse (fun h => h)

/-! ## 生成证书 -/

/-- 高一级中枢的生成证书。`lvl` 是成核各项所在的级，`a`、`t` 是原始下标。 -/
inductive Cert where
  /-- 三段独立成核：第 `lvl` 级自 `a` 起的三项有公共重叠，且三项各自是真块。 -/
  | seed3 (lvl a : Nat)
  /-- 原核延伸满九项：第 `lvl` 级自 `a` 起三项成核，其后六项都触及原核。 -/
  | nineExt (lvl a : Nat)
  /-- 相邻两核的外缘重叠：第 `lvl` 级自 `a` 起与自 `t` 起各有一核，两核不相触，外缘相触。 -/
  | expand (lvl a t : Nat)
  deriving DecidableEq, Repr

/-- 第 `lvl` 级的切点表（原始下标）。第 0 级每段一切。 -/
def lvlCuts (S : Seq) (fam : List (List Nat)) : Nat → List Nat
  | 0 => List.range (S.length + 1)
  | l + 1 => fam.getD l []

/-- 第 `lvl` 级自原始下标 `a` 起的切点。 -/
def cutsFrom (S : Seq) (fam : List (List Nat)) (lvl a : Nat) : List Nat :=
  (lvlCuts S fam lvl).filter fun x => a ≤ x

/-- 第 `lvl` 级自原始下标 `a` 起的各项。 -/
def itemsFrom (S : Seq) (fam : List (List Nat)) (lvl a : Nat) : Seq :=
  coarsen S (cutsFrom S fam lvl a)

/-- 第 `lvl` 级的块 `[a, b)` 是真块：第 0 级的段无条件算，
更高级的块要求内部有下一级的三项重叠。九段进位切出的形式三段组不一定满足。 -/
def Bona (S : Seq) (fam : List (List Nat)) (lvl a b : Nat) : Prop :=
  match lvl with
  | 0 => True
  | l + 1 =>
    ∃ i, i < S.length ∧
      OvAt (coarsen S ((lvlCuts S fam l).filter fun x => a ≤ x ∧ x ≤ b)) i

instance (S : Seq) (fam : List (List Nat)) (lvl a b : Nat) : Decidable (Bona S fam lvl a b) := by
  cases lvl <;> (unfold Bona; infer_instance)

/-- 第 `lvl` 级自 `a` 起的第 `i` 个切点。 -/
def cutAt (S : Seq) (fam : List (List Nat)) (lvl a i : Nat) : Nat :=
  (cutsFrom S fam lvl a).getD i 0

/-- 证书在给定序列与切点族上成立。 -/
def Cert.Holds (S : Seq) (fam : List (List Nat)) : Cert → Prop
  | .seed3 lvl a =>
    (cutsFrom S fam lvl a).head? = some a ∧ OvAt (itemsFrom S fam lvl a) 0 ∧
      Bona S fam lvl (cutAt S fam lvl a 0) (cutAt S fam lvl a 1) ∧
      Bona S fam lvl (cutAt S fam lvl a 1) (cutAt S fam lvl a 2) ∧
      Bona S fam lvl (cutAt S fam lvl a 2) (cutAt S fam lvl a 3)
  | .nineExt lvl a =>
    (cutsFrom S fam lvl a).head? = some a ∧ Nine (itemsFrom S fam lvl a) 0
  | .expand lvl a t =>
    (cutsFrom S fam lvl a).head? = some a ∧ (cutsFrom S fam lvl t).head? = some t ∧
      4 ≤ (cutsFrom S fam lvl a).idxOf t ∧
      OvAt (itemsFrom S fam lvl a) 0 ∧ OvAt (itemsFrom S fam lvl t) 0 ∧
      ¬ Touch (coreAt (itemsFrom S fam lvl a) 0) (coreAt (itemsFrom S fam lvl t) 0) ∧
      Touch (hull ((itemsFrom S fam lvl a).take 3)) (hull ((itemsFrom S fam lvl t).take 3))

instance (S : Seq) (fam : List (List Nat)) (c : Cert) : Decidable (c.Holds S fam) := by
  cases c <;> (unfold Cert.Holds; infer_instance)

end ChanExplore.Proto2318
