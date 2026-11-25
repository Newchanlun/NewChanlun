module

public import ChanExplore.Proto2318.Cert
public import Mathlib.Data.Finset.Max
public import Mathlib.Data.Finset.Filter
public import Mathlib.Basic.ExistsUnique

/-!
# 多级结构的三种表示

- `Tree`：嵌套括号树，节点带生成方式。
- `Laminar`：各级切点（原始下标）的集合族，证书另表存放。
- `Tower`：逐级的块序列，每块存跨度、实际值域与证书。

三者都导出同一份正规形 `fam : List (List Nat)`（第 1 级起各级切点的原始下标表）
与证书表，再由 `Cert.Holds` 统一校验。每种表示各证两条玩具引理。
-/

@[expose] public section

namespace ChanExplore.Proto2318

/-! ## 表示一：嵌套括号树 -/

/-- 节点内中枢的生成方式。`group` 是九段进位切出的形式三段组，不主张自己成核。 -/
inductive Gen
  | seed3
  | nineExt
  | expand (gap : Nat)
  | group
  deriving DecidableEq, Repr

mutual
  /-- 括号树：叶是第 0 级的一段。 -/
  inductive Tree
    | seg
    | node (g : Gen) (kids : Forest)
  /-- 子树序列。 -/
  inductive Forest
    | nil
    | cons (t : Tree) (rest : Forest)
end

mutual
  /-- 覆盖的第 0 级段数。 -/
  def Tree.width : Tree → Nat
    | .seg => 1
    | .node _ ks => ks.width
  /-- 子树序列覆盖的第 0 级段数。 -/
  def Forest.width : Forest → Nat
    | .nil => 0
    | .cons t r => t.width + r.width
end

/-- 子树个数。 -/
def Forest.len : Forest → Nat
  | .nil => 0
  | .cons _ r => r.len + 1

mutual
  /-- 树高。 -/
  def Tree.height : Tree → Nat
    | .seg => 0
    | .node _ ks => ks.height + 1
  /-- 子树的最大高度。 -/
  def Forest.height : Forest → Nat
    | .nil => 0
    | .cons t r => max t.height r.height
end

mutual
  /-- 等高且每个节点至少三个子节点。树类型本身不保证这一点。 -/
  def Tree.Uniform : Tree → Nat → Prop
    | .seg, h => h = 0
    | .node _ _, 0 => False
    | .node _ ks, h + 1 => 3 ≤ ks.len ∧ ks.Uniform h
  /-- 各子树都等高。 -/
  def Forest.Uniform : Forest → Nat → Prop
    | .nil, _ => True
    | .cons t r, h => t.Uniform h ∧ r.Uniform h
end

mutual
  /-- 高度为 `lvl` 的节点的起点（原始下标），`off` 是本子树的起点。 -/
  def Tree.starts (lvl off : Nat) : Tree → List Nat
    | .seg => if lvl = 0 then [off] else []
    | .node _ ks => if ks.height + 1 = lvl then [off] else ks.starts lvl off
  /-- 子树序列里高度为 `lvl` 的节点的起点。 -/
  def Forest.starts (lvl off : Nat) : Forest → List Nat
    | .nil => []
    | .cons t r => t.starts lvl off ++ r.starts lvl (off + t.width)
end

/-- 第 1 级起各级切点的原始下标表。 -/
def Tree.fam (t : Tree) : List (List Nat) :=
  (List.range t.height).map fun l => t.starts (l + 1) 0 ++ [t.width]

mutual
  /-- 各节点携带的证书，换算成原始下标。 -/
  def Tree.certs (off : Nat) : Tree → List Cert
    | .seg => []
    | .node g ks =>
      (match g with
        | .seed3 => [Cert.seed3 ks.height off]
        | .nineExt => [Cert.nineExt (ks.height - 1) off]
        | .expand gap => [Cert.expand ks.height off (off + gap)]
        | .group => []) ++ ks.certs off
  /-- 子树序列携带的证书。 -/
  def Forest.certs (off : Nat) : Forest → List Cert
    | .nil => []
    | .cons t r => t.certs off ++ r.certs (off + t.width)
end

end ChanExplore.Proto2318

end

public section

namespace ChanExplore.Proto2318

mutual
  /-- 玩具引理 T1：等高树的段数至少是 3 的树高次幂，所以级别数受段数的对数约束。 -/
  theorem Tree.pow_le_width : ∀ (t : Tree) (h : Nat), t.Uniform h → 3 ^ h ≤ t.width
    | .seg, h, hu => by
      have h0 : h = 0 := hu
      subst h0
      simp [Tree.width]
    | .node _ _, 0, hu => hu.elim
    | .node _ ks, h + 1, hu => by
      have hk := Forest.len_mul_le_width ks h hu.2
      have h3 : 3 ≤ ks.len := hu.1
      calc 3 ^ (h + 1) = 3 * 3 ^ h := by rw [Nat.pow_succ, Nat.mul_comm]
        _ ≤ ks.len * 3 ^ h := Nat.mul_le_mul_right _ h3
        _ ≤ ks.width := hk
  theorem Forest.len_mul_le_width :
      ∀ (f : Forest) (h : Nat), f.Uniform h → f.len * 3 ^ h ≤ f.width
    | .nil, _, _ => by simp [Forest.len, Forest.width]
    | .cons t r, h, hu => by
      have a := Tree.pow_le_width t h hu.1
      have b := Forest.len_mul_le_width r h hu.2
      simp only [Forest.len, Forest.width, Nat.add_mul, Nat.one_mul]
      omega
end

mutual
  /-- 玩具引理 T2：任何节点的起点都落在所属子树的跨度内，嵌套由构造保证。 -/
  theorem Tree.starts_bounds : ∀ (t : Tree) (lvl off x : Nat),
      x ∈ t.starts lvl off → off ≤ x ∧ x ≤ off + t.width
    | .seg, lvl, off, x, hx => by
      unfold Tree.starts at hx
      split at hx
      · have : x = off := by simpa using hx
        subst this
        simp [Tree.width]
      · simp at hx
    | .node _ ks, lvl, off, x, hx => by
      unfold Tree.starts at hx
      split at hx
      · have : x = off := by simpa using hx
        subst this
        simp [Tree.width]
      · simpa [Tree.width] using Forest.starts_bounds ks lvl off x hx
  theorem Forest.starts_bounds : ∀ (f : Forest) (lvl off x : Nat),
      x ∈ f.starts lvl off → off ≤ x ∧ x ≤ off + f.width
    | .nil, _, _, _, hx => by simp [Forest.starts] at hx
    | .cons t r, lvl, off, x, hx => by
      unfold Forest.starts at hx
      rcases List.mem_append.1 hx with h | h
      · have := Tree.starts_bounds t lvl off x h
        simp only [Forest.width]
        omega
      · have := Forest.starts_bounds r lvl (off + t.width) x h
        simp only [Forest.width]
        omega
end

end ChanExplore.Proto2318

end

@[expose] public section

namespace ChanExplore.Proto2318

/-! ## 表示二：切点集合的层状族 -/

/-- 层状族：`level l` 是第 `l` 级切点的原始下标集。深度、下标上界与证书另存。 -/
structure Laminar where
  level : ℕ → Finset ℕ
  depth : ℕ
  bound : ℕ
  certs : List Cert

/-- 逐级嵌套。对全体自然数量化，本身不可判定；可判定版本只查到 `depth`。 -/
def Laminar.Nested (F : Laminar) : Prop :=
  ∀ l, F.level (l + 1) ⊆ F.level l

/-- 可判定的嵌套检查，只查前 `depth` 级。 -/
def Laminar.NestedUpTo (F : Laminar) : Prop :=
  ∀ l, l < F.depth → F.level (l + 1) ⊆ F.level l

instance (F : Laminar) : Decidable F.NestedUpTo := by
  unfold Laminar.NestedUpTo; infer_instance

/-- 第 1 级起各级切点的原始下标表。按下标上界逐个查成员，不用 `Finset.sort`：
后者在内核里约化不动，`decide +kernel` 会卡住。 -/
def Laminar.fam (F : Laminar) : List (List Nat) :=
  (List.range F.depth).map fun l =>
    (List.range (F.bound + 1)).filter fun x => decide (x ∈ F.level (l + 1))

/-! ## 表示三：逐级粗化的序列塔 -/

/-- 塔里的一块：原始跨度、存下来的实际值域、可选的证书。 -/
structure Blk where
  s : Nat
  e : Nat
  rng : Iv
  cert : Option Cert
  deriving DecidableEq, Repr

/-- 第 1 级起逐级的块序列。 -/
abbrev Tower := List (List Blk)

/-- 一级块序列的切点表。 -/
def blkCuts : List Blk → List Nat
  | [] => []
  | [b] => [b.s, b.e]
  | b :: rest => b.s :: blkCuts rest

/-- 第 1 级起各级切点的原始下标表。 -/
def Tower.fam (T : Tower) : List (List Nat) :=
  T.map blkCuts

/-- 塔里携带的全部证书。 -/
def Tower.certs (T : Tower) : List Cert :=
  T.flatMap fun lv => lv.filterMap (·.cert)

/-- 存下来的值域与第 0 级序列一致。值域是冗余字段，不一致的塔可以构造出来。 -/
def Tower.RangesOK (S : Seq) (T : Tower) : Prop :=
  ∀ lv ∈ T, ∀ b ∈ lv, b.rng = hull ((S.drop b.s).take (b.e - b.s))

instance (S : Seq) (T : Tower) : Decidable (T.RangesOK S) := by
  unfold Tower.RangesOK; infer_instance

end ChanExplore.Proto2318

end

public section

namespace ChanExplore.Proto2318

/-- 玩具引理 L1：逐级嵌套时，高级别切点都是低级别切点。 -/
theorem Laminar.level_antitone (F : Laminar) (h : F.Nested) :
    ∀ l m, l ≤ m → F.level m ⊆ F.level l := by
  intro l m hlm
  induction m with
  | zero =>
    have : l = 0 := by omega
    subst this
    exact fun _ hx => hx
  | succ m ih =>
    by_cases hl : l = m + 1
    · subst hl
      exact fun _ hx => hx
    · exact fun x hx => ih (by omega) (h m hx)

/-- 玩具引理 L2：0 是切点时，每个原始下标在每一级都有唯一的所属块起点。 -/
theorem Laminar.address_unique (F : Laminar) (l i : ℕ) (h0 : 0 ∈ F.level l) :
    ∃! a, a ∈ F.level l ∧ a ≤ i ∧ ∀ b ∈ F.level l, b ≤ i → b ≤ a := by
  have hne : ((F.level l).filter (· ≤ i)).Nonempty :=
    ⟨0, Finset.mem_filter.2 ⟨h0, Nat.zero_le i⟩⟩
  refine ⟨((F.level l).filter (· ≤ i)).max' hne, ⟨?_, ?_, ?_⟩, ?_⟩
  · exact (Finset.mem_filter.1 (Finset.max'_mem _ hne)).1
  · exact (Finset.mem_filter.1 (Finset.max'_mem _ hne)).2
  · intro b hb hbi
    exact Finset.le_max' _ b (Finset.mem_filter.2 ⟨hb, hbi⟩)
  · rintro a ⟨ha, hai, hmax⟩
    apply Nat.le_antisymm
    · exact Finset.le_max' _ a (Finset.mem_filter.2 ⟨ha, hai⟩)
    · exact hmax _ (Finset.mem_filter.1 (Finset.max'_mem _ hne)).1
        (Finset.mem_filter.1 (Finset.max'_mem _ hne)).2

/-- 玩具引理 W1：粗化后的项数是切点数减一。 -/
theorem coarsen_length (S : Seq) : ∀ cuts : List Nat, (coarsen S cuts).length = cuts.length - 1
  | [] => rfl
  | [_] => rfl
  | a :: b :: rest => by
    have ih := coarsen_length S (b :: rest)
    simp only [coarsen, List.length_cons] at ih ⊢
    omega

/-- 玩具引理 W2：三个非空闭区间两两相触，就有公共部分。
九项延伸按 3+3+3 结合后，三组的实际值域两两相触，所以高一级的区间总取得出来。 -/
theorem ov3_of_pairwise_touch {a b c : Iv} (ha : a.lo ≤ a.hi) (hb : b.lo ≤ b.hi)
    (hc : c.lo ≤ c.hi) (hab : Touch a b) (hac : Touch a c) (hbc : Touch b c) : Ov3 a b c := by
  obtain ⟨h1, h2⟩ := hab
  obtain ⟨h3, h4⟩ := hac
  obtain ⟨h5, h6⟩ := hbc
  unfold Ov3
  omega

end ChanExplore.Proto2318
