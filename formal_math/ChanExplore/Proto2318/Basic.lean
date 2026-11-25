module

/-!
# #2318 原型：区间序列上的声明式分解规范

`ValidDecomp policy S d` 是关系：给定区间序列 `S` 与一份分解 `d`，判断 `d` 是否满足政策
`policy` 的规范。它不产生分解。各政策的块语言与 `py/model.py` 的 `valid` 逐条对应。

这里的定义都是探索用草稿，不是 `Chan` 的正式定义。
-/

@[expose] public section

namespace ChanExplore.Proto2318

/-- 闭区间。`lo > hi` 的值可以构造出来，表示空区间；下面的谓词都先查下标界再用它。 -/
structure Iv where
  lo : Nat
  hi : Nat
  deriving DecidableEq, Repr

/-- 某一级的区间序列。第 0 级由折线生成，更高一级取已完成块的实际值域。 -/
abbrev Seq := List Iv

/-- 折线端点表 → 第 0 级区间序列。 -/
def segs : List Nat → Seq
  | a :: b :: rest => ⟨min a b, max a b⟩ :: segs (b :: rest)
  | _ => []

/-- 三个闭区间有公共部分，单点也算。 -/
def Ov3 (a b c : Iv) : Prop :=
  max a.lo (max b.lo c.lo) ≤ min a.hi (min b.hi c.hi)

/-- 三个区间的公共部分。 -/
def core3 (a b c : Iv) : Iv :=
  ⟨max a.lo (max b.lo c.lo), min a.hi (min b.hi c.hi)⟩

/-- 两个闭区间相触。 -/
def Touch (x c : Iv) : Prop :=
  x.lo ≤ c.hi ∧ c.lo ≤ x.hi

/-- 越界下标取空区间。 -/
def item (S : Seq) (i : Nat) : Iv :=
  S.getD i ⟨1, 0⟩

/-- 第 `i` 项起的连续三项有公共重叠。 -/
def OvAt (S : Seq) (i : Nat) : Prop :=
  i + 3 ≤ S.length ∧ Ov3 (item S i) (item S (i + 1)) (item S (i + 2))

/-- 第 `i` 项起三项的核。 -/
def coreAt (S : Seq) (i : Nat) : Iv :=
  core3 (item S i) (item S (i + 1)) (item S (i + 2))

/-- 第 `j` 项触及第 `s` 项起三项的核。 -/
def TouchAt (S : Seq) (s j : Nat) : Prop :=
  Touch (item S j) (coreAt S s)

instance (a b c : Iv) : Decidable (Ov3 a b c) := by unfold Ov3; infer_instance
instance (x c : Iv) : Decidable (Touch x c) := by unfold Touch; infer_instance
instance (S : Seq) (i : Nat) : Decidable (OvAt S i) := by unfold OvAt; infer_instance
instance (S : Seq) (s j : Nat) : Decidable (TouchAt S s j) := by unfold TouchAt; infer_instance

/-! ## 块语言 -/

/-- 同级别：恰三项且有公共重叠。 -/
def Same (S : Seq) (s e : Nat) : Prop :=
  e = s + 3 ∧ OvAt S s

/-- 接口律下限：奇数项、至少三项、不到九项、块内某处有三项重叠。 -/
def AnyBlk (S : Seq) (s e : Nat) : Prop :=
  e ≤ S.length ∧ (e - s) % 2 = 1 ∧ 3 ≤ e - s ∧ e - s ≤ 7 ∧
    ∃ i, i < e ∧ s ≤ i ∧ i + 3 ≤ e ∧ OvAt S i

/-- 单中枢块：块首三项成核，其后各项都触及该核，不到九项。 -/
def ExtBlk (S : Seq) (s e : Nat) : Prop :=
  e ≤ S.length ∧ (e - s) % 2 = 1 ∧ 3 ≤ e - s ∧ e - s ≤ 7 ∧ OvAt S s ∧
    ∀ j, j < e → s + 3 ≤ j → TouchAt S s j

/-- 核在 `e` 处已被破坏：首个不触核的项是第 `e` 项或第 `e + 1` 项。 -/
def BrokenAt (S : Seq) (s e : Nat) : Prop :=
  OvAt S s ∧ ∃ f, f < S.length ∧ (f = e ∨ f = e + 1) ∧ ¬ TouchAt S s f ∧
    ∀ j, j < f → s + 3 ≤ j → TouchAt S s j

/-- 不设上限：核被破坏才成块，块长是任意奇数。 -/
def NoCap (S : Seq) (s e : Nat) : Prop :=
  e ≤ S.length ∧ (e - s) % 2 = 1 ∧ 3 ≤ e - s ∧ BrokenAt S s e

/-- 进位有界下的普通块：核被破坏才成块，且不到九项。 -/
def Brk (S : Seq) (s e : Nat) : Prop :=
  ExtBlk S s e ∧ BrokenAt S s e

/-- 块首三项成核，其后六项都触及原核：延伸满九项。 -/
def Nine (S : Seq) (s : Nat) : Prop :=
  s + 9 ≤ S.length ∧ OvAt S s ∧ ∀ j, j < s + 9 → s + 3 ≤ j → TouchAt S s j

instance (S : Seq) (s e : Nat) : Decidable (Same S s e) := by unfold Same; infer_instance
instance (S : Seq) (s e : Nat) : Decidable (AnyBlk S s e) := by unfold AnyBlk; infer_instance
instance (S : Seq) (s e : Nat) : Decidable (ExtBlk S s e) := by unfold ExtBlk; infer_instance
instance (S : Seq) (s e : Nat) : Decidable (BrokenAt S s e) := by unfold BrokenAt; infer_instance
instance (S : Seq) (s e : Nat) : Decidable (NoCap S s e) := by unfold NoCap; infer_instance
instance (S : Seq) (s e : Nat) : Decidable (Brk S s e) := by unfold Brk; infer_instance
instance (S : Seq) (s : Nat) : Decidable (Nine S s) := by unfold Nine; infer_instance

/-! ## 政策 -/

/-- 候选政策。全局择优的 LEX 与 HIGH 只在 Python 侧。 -/
inductive Policy
  | anyFull
  | anyExh
  | same
  | minimal
  | maximal
  | extExh
  | noCap
  | carry
  deriving DecidableEq, Repr

/-- 政策的块语言。`carry` 的九项组另由 `CarryChain` 处理。 -/
def Policy.Blk (p : Policy) (S : Seq) (s e : Nat) : Prop :=
  match p with
  | .anyFull => AnyBlk S s e
  | .anyExh => AnyBlk S s e
  | .same => Same S s e
  | .minimal => AnyBlk S s e ∧ ∀ x, x < e → ¬ AnyBlk S s x
  | .maximal => AnyBlk S s e ∧ ∀ x, x < S.length + 1 → e < x → ¬ AnyBlk S s x
  | .extExh => ExtBlk S s e
  | .noCap => NoCap S s e
  | .carry => Brk S s e

/-- 政策对未完成尾部起点的要求。 -/
def Policy.Tail (p : Policy) (S : Seq) (c : Nat) : Prop :=
  match p with
  | .anyFull => c = S.length
  | .anyExh => ∀ e, e < S.length + 1 → ¬ AnyBlk S c e
  | .same => ∀ e, e < S.length + 1 → ¬ Same S c e
  | .minimal => ∀ e, e < S.length + 1 → ¬ AnyBlk S c e
  | .maximal => ∀ e, e < S.length + 1 → ¬ AnyBlk S c e
  | .extExh => ∀ e, e < S.length + 1 → ¬ ExtBlk S c e
  | .noCap => ∀ e, e < S.length + 1 → ¬ NoCap S c e
  | .carry => (∀ e, e < S.length + 1 → ¬ Brk S c e) ∧ ¬ Nine S c

instance (p : Policy) (S : Seq) (s e : Nat) : Decidable (p.Blk S s e) := by
  cases p <;> (unfold Policy.Blk; infer_instance)

instance (p : Policy) (S : Seq) (c : Nat) : Decidable (p.Tail S c) := by
  cases p <;> (unfold Policy.Tail; infer_instance)

/-! ## 分解与规范 -/

/-- 一份分解：切点下标表。末切点到序列末尾是未完成尾部，不单存。 -/
structure Decomp where
  cuts : List Nat
  deriving DecidableEq, Repr

/-- 良构：首切点为 0，严格递增，不越界。 -/
def WF (n : Nat) (cuts : List Nat) : Prop :=
  cuts.head? = some 0 ∧ cuts.Pairwise (· < ·) ∧ ∀ c ∈ cuts, c ≤ n

/-- 相邻切点之间都是合法块，末切点满足尾部要求。 -/
def Chain (B : Nat → Nat → Prop) (T : Nat → Prop) : List Nat → Prop
  | [] => False
  | [c] => T c
  | c :: c' :: rest => B c c' ∧ Chain B T (c' :: rest)

/-- 规范进位：状态 0 是普通位置，1、2 是九项组里的第二、第三块。 -/
def CarryChain (S : Seq) : Nat → List Nat → Prop
  | _, [] => False
  | st, [c] => st = 0 ∧ Policy.carry.Tail S c
  | 0, c :: c' :: rest =>
    (Brk S c c' ∧ CarryChain S 0 (c' :: rest)) ∨
      (Nine S c ∧ c' = c + 3 ∧ CarryChain S 1 (c' :: rest))
  | 1, c :: c' :: rest => c' = c + 3 ∧ CarryChain S 2 (c' :: rest)
  | _ + 2, c :: c' :: rest => c' = c + 3 ∧ CarryChain S 0 (c' :: rest)

instance chainDec (B : Nat → Nat → Prop) (T : Nat → Prop) [∀ s e, Decidable (B s e)]
    [∀ c, Decidable (T c)] : ∀ l, Decidable (Chain B T l)
  | [] => isFalse (fun h => h)
  | [c] => inferInstanceAs (Decidable (T c))
  | c :: c' :: rest =>
    have := chainDec B T (c' :: rest)
    inferInstanceAs (Decidable (B c c' ∧ Chain B T (c' :: rest)))

instance carryDec (S : Seq) : ∀ st l, Decidable (CarryChain S st l)
  | _, [] => isFalse (fun h => h)
  | st, [c] => inferInstanceAs (Decidable (st = 0 ∧ Policy.carry.Tail S c))
  | 0, c :: c' :: rest =>
    have := carryDec S 0 (c' :: rest)
    have := carryDec S 1 (c' :: rest)
    inferInstanceAs (Decidable ((Brk S c c' ∧ CarryChain S 0 (c' :: rest)) ∨
      (Nine S c ∧ c' = c + 3 ∧ CarryChain S 1 (c' :: rest))))
  | 1, c :: c' :: rest =>
    have := carryDec S 2 (c' :: rest)
    inferInstanceAs (Decidable (c' = c + 3 ∧ CarryChain S 2 (c' :: rest)))
  | _ + 2, c :: c' :: rest =>
    have := carryDec S 0 (c' :: rest)
    inferInstanceAs (Decidable (c' = c + 3 ∧ CarryChain S 0 (c' :: rest)))

/-- 政策的链条条款。 -/
def Policy.Links (p : Policy) (S : Seq) (cuts : List Nat) : Prop :=
  match p with
  | .carry => CarryChain S 0 cuts
  | p => Chain (p.Blk S) (p.Tail S) cuts

instance (p : Policy) (S : Seq) (cuts : List Nat) : Decidable (p.Links S cuts) := by
  cases p <;> (unfold Policy.Links; infer_instance)

/-- 声明式规范：`d` 是 `S` 在政策 `p` 下的合法分解。 -/
def ValidDecomp (p : Policy) (S : Seq) (d : Decomp) : Prop :=
  WF S.length d.cuts ∧ p.Links S d.cuts

instance (n : Nat) (cuts : List Nat) : Decidable (WF n cuts) := by unfold WF; infer_instance

instance (p : Policy) (S : Seq) (d : Decomp) : Decidable (ValidDecomp p S d) := by
  unfold ValidDecomp; infer_instance

/-! ## 候选分解的有限枚举 -/

/-- 元素取自 `[lo, lo + fuel)` 的全部严格递增表。 -/
def incLists : Nat → Nat → List (List Nat)
  | _, 0 => [[]]
  | lo, fuel + 1 => incLists (lo + 1) fuel ++ (incLists (lo + 1) fuel).map (lo :: ·)

/-- 长度为 `n` 的序列上全部良构切点表。 -/
def candidates (n : Nat) : List (List Nat) :=
  (incLists 1 n).map (0 :: ·)

/-- 政策 `p` 下 `S` 的全部合法切点表。 -/
def validCuts (p : Policy) (S : Seq) : List (List Nat) :=
  (candidates S.length).filter fun c => decide (ValidDecomp p S ⟨c⟩)

end ChanExplore.Proto2318
