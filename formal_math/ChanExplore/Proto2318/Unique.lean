module

public import ChanExplore.Proto2318.Cert
public import Mathlib.Basic.ExistsUnique

/-!
# 唯一性的一般论证

这里的定理对任意区间序列成立，不是小模型读数。

- `chain_unique`：块语言在每个起点至多定出一个终点，且尾部条款排斥任何成块，
  则同起点的合法链至多一条。唯一性来自「起点定终点」，没有用到进位有界。
- `same_unique`、`minimal_unique`、`maximal_unique`、`noCap_unique`、`carry_unique`：
  五个政策各自至多一个合法分解。
- `chain_exists`：块都向前且不越界、无块可成时尾部条款成立，则合法链存在。
- `same_existsUnique`、`minimal_existsUnique`、`maximal_existsUnique`、`noCap_existsUnique`、
  `carry_existsUnique`：五个政策下合法分解存在且唯一。
- `tower_unique`、`tower_exists`、`mixed_existsUnique`：唯一性与存在性逐级传递到多级规范。
- `existsUnique_of_validCuts`：把有限枚举上的读数转成 `∃!` 陈述。
-/

public section

namespace ChanExplore.Proto2318

/-- 起点定终点的块语言加排斥成块的尾部条款：同起点的合法链至多一条。 -/
theorem chain_unique {B : Nat → Nat → Prop} {T : Nat → Prop}
    (hB : ∀ s e e', B s e → B s e' → e = e') (hT : ∀ s e, T s → ¬ B s e) :
    ∀ l l' : List Nat, Chain B T l → Chain B T l' → l.head? = l'.head? → l = l'
  | [], _, h, _, _ => h.elim
  | _ :: _, [], _, h', _ => h'.elim
  | [c], [c'], _, _, hh => by simpa using hh
  | [c], c' :: c'' :: r', h, h', hh => by
    have hc : c = c' := by simpa using hh
    subst hc
    exact (hT c c'' h h'.1).elim
  | c :: c1 :: r, [c'], h, h', hh => by
    have hc : c = c' := by simpa using hh
    subst hc
    exact (hT c c1 h' h.1).elim
  | c :: c1 :: r, c' :: c1' :: r', h, h', hh => by
    have hc : c = c' := by simpa using hh
    subst hc
    have h1 : c1 = c1' := hB c c1 c1' h.1 h'.1
    subst h1
    rw [chain_unique hB hT (c1 :: r) (c1 :: r') h.2 h'.2 rfl]

/-- 把链条上的唯一性抬到分解上。 -/
theorem decomp_unique_of_chain {p : Policy} {S : Seq}
    (hlinks : ∀ cuts, p.Links S cuts ↔ Chain (p.Blk S) (p.Tail S) cuts)
    (hB : ∀ s e e', p.Blk S s e → p.Blk S s e' → e = e')
    (hT : ∀ s e, p.Tail S s → ¬ p.Blk S s e)
    {d d' : Decomp} (h : ValidDecomp p S d) (h' : ValidDecomp p S d') : d = d' := by
  have key := chain_unique hB hT d.cuts d'.cuts ((hlinks _).1 h.2) ((hlinks _).1 h'.2)
    (h.1.1.trans h'.1.1.symm)
  cases d
  cases d'
  simpa using key

/-- 同级别分解至多一个。 -/
theorem same_unique {S : Seq} {d d' : Decomp} (h : ValidDecomp .same S d)
    (h' : ValidDecomp .same S d') : d = d' :=
  decomp_unique_of_chain (p := .same) (S := S) (fun _ => Iff.rfl)
    (fun _ _ _ a b => a.1.trans b.1.symm)
    (fun _ e t b => t e (by have := b.2.1; have := b.1; omega) b) h h'

/-- 最早成块政策下分解至多一个。 -/
theorem minimal_unique {S : Seq} {d d' : Decomp} (h : ValidDecomp .minimal S d)
    (h' : ValidDecomp .minimal S d') : d = d' :=
  decomp_unique_of_chain (p := .minimal) (S := S) (fun _ => Iff.rfl)
    (fun _ e e' a b => by
      rcases Nat.lt_trichotomy e e' with hlt | heq | hgt
      · exact (b.2 e hlt a.1).elim
      · exact heq
      · exact (a.2 e' hgt b.1).elim)
    (fun _ e t b => t e (Nat.lt_succ_of_le b.1.1) b.1) h h'

/-- 最晚成块政策下分解至多一个。 -/
theorem maximal_unique {S : Seq} {d d' : Decomp} (h : ValidDecomp .maximal S d)
    (h' : ValidDecomp .maximal S d') : d = d' :=
  decomp_unique_of_chain (p := .maximal) (S := S) (fun _ => Iff.rfl)
    (fun _ e e' a b => by
      rcases Nat.lt_trichotomy e e' with hlt | heq | hgt
      · exact (a.2 e' (Nat.lt_succ_of_le b.1.1) hlt b.1).elim
      · exact heq
      · exact (b.2 e (Nat.lt_succ_of_le a.1.1) hgt a.1).elim)
    (fun _ e t b => t e (Nat.lt_succ_of_le b.1.1) b.1) h h'

/-- 不设上限的块语言里，起点定出终点。 -/
theorem noCap_functional {S : Seq} {s e e' : Nat} (a : NoCap S s e) (b : NoCap S s e') :
    e = e' := by
  obtain ⟨_, hpa, h3a, _, f, _, hfa, hnt, hall⟩ := a
  obtain ⟨_, hpb, h3b, _, f', _, hfb, hnt', hall'⟩ := b
  have hff : f = f' := by
    rcases Nat.lt_trichotomy f f' with hlt | heq | hgt
    · exact (hnt (hall' f hlt (by omega))).elim
    · exact heq
    · exact (hnt' (hall f' hgt (by omega))).elim
  omega

/-- 不设上限政策下分解至多一个。 -/
theorem noCap_unique {S : Seq} {d d' : Decomp} (h : ValidDecomp .noCap S d)
    (h' : ValidDecomp .noCap S d') : d = d' :=
  decomp_unique_of_chain (p := .noCap) (S := S) (fun _ => Iff.rfl)
    (fun _ _ _ a b => noCap_functional a b)
    (fun _ e t b => t e (Nat.lt_succ_of_le b.1) b) h h'

/-- 进位有界的普通块里，起点定出终点。 -/
theorem brk_functional {S : Seq} {s e e' : Nat} (a : Brk S s e) (b : Brk S s e') : e = e' := by
  obtain ⟨⟨_, hpa, h3a, _, _, _⟩, _, f, _, hfa, hnt, hall⟩ := a
  obtain ⟨⟨_, hpb, h3b, _, _, _⟩, _, f', _, hfb, hnt', hall'⟩ := b
  have hff : f = f' := by
    rcases Nat.lt_trichotomy f f' with hlt | heq | hgt
    · exact (hnt (hall' f hlt (by omega))).elim
    · exact heq
    · exact (hnt' (hall f' hgt (by omega))).elim
  omega

/-- 同一个起点上，核被破坏的普通块与延伸满九项互斥。 -/
theorem brk_not_nine {S : Seq} {s e : Nat} (a : Brk S s e) (n : Nine S s) : False := by
  obtain ⟨⟨_, _, h3, h7, _, _⟩, _, f, _, hf, hnt, _⟩ := a
  exact hnt (n.2.2 f (by omega) (by omega))

/-- 规范进位的链条在同状态、同起点下至多一条。 -/
theorem carryChain_unique (S : Seq) : ∀ (st : Nat) (l l' : List Nat),
    CarryChain S st l → CarryChain S st l' → l.head? = l'.head? → l = l'
  | _, [], _, h, _, _ => h.elim
  | _, _ :: _, [], _, h', _ => h'.elim
  | _, [c], [c'], _, _, hh => by simpa using hh
  | st, [c], c' :: c'' :: r', h, h', hh => by
    have hc : c = c' := by simpa using hh
    subst hc
    obtain ⟨rfl, ht⟩ := h
    rcases h' with ⟨hb, _⟩ | ⟨hn, _, _⟩
    · exact (ht.1 c'' (Nat.lt_succ_of_le hb.1.1) hb).elim
    · exact (ht.2 hn).elim
  | st, c :: c1 :: r, [c'], h, h', hh => by
    have hc : c = c' := by simpa using hh
    subst hc
    obtain ⟨rfl, ht⟩ := h'
    rcases h with ⟨hb, _⟩ | ⟨hn, _, _⟩
    · exact (ht.1 c1 (Nat.lt_succ_of_le hb.1.1) hb).elim
    · exact (ht.2 hn).elim
  | 0, c :: c1 :: r, c' :: c1' :: r', h, h', hh => by
    have hc : c = c' := by simpa using hh
    subst hc
    rcases h with ⟨hb, hr⟩ | ⟨hn, he, hr⟩ <;> rcases h' with ⟨hb', hr'⟩ | ⟨hn', he', hr'⟩
    · have h1 := brk_functional hb hb'
      subst h1
      rw [carryChain_unique S 0 (c1 :: r) (c1 :: r') hr hr' rfl]
    · exact (brk_not_nine hb hn').elim
    · exact (brk_not_nine hb' hn).elim
    · subst he
      subst he'
      rw [carryChain_unique S 1 _ _ hr hr' rfl]
  | 1, c :: c1 :: r, c' :: c1' :: r', h, h', hh => by
    have hc : c = c' := by simpa using hh
    subst hc
    obtain ⟨he, hr⟩ := h
    obtain ⟨he', hr'⟩ := h'
    subst he
    subst he'
    rw [carryChain_unique S 2 _ _ hr hr' rfl]
  | _ + 2, c :: c1 :: r, c' :: c1' :: r', h, h', hh => by
    have hc : c = c' := by simpa using hh
    subst hc
    obtain ⟨he, hr⟩ := h
    obtain ⟨he', hr'⟩ := h'
    subst he
    subst he'
    rw [carryChain_unique S 0 _ _ hr hr' rfl]

/-- 规范进位政策下分解至多一个。 -/
theorem carry_unique {S : Seq} {d d' : Decomp} (h : ValidDecomp .carry S d)
    (h' : ValidDecomp .carry S d') : d = d' := by
  have key := carryChain_unique S 0 d.cuts d'.cuts h.2 h'.2 (h.1.1.trans h'.1.1.symm)
  cases d
  cases d'
  simpa using key

/-! ## 存在性 -/

/-- 块都向前且不越界、无块可成时尾部条款成立，则从任意起点出发都有一条合法链。 -/
theorem chain_exists {B : Nat → Nat → Prop} {T : Nat → Prop} (n : Nat)
    (hB : ∀ s e, B s e → s < e ∧ e ≤ n) (hT : ∀ s, (∀ e, ¬ B s e) → T s) :
    ∀ k c, n - c ≤ k → c ≤ n →
      ∃ l : List Nat, l.head? = some c ∧ Chain B T l ∧
        l.Pairwise (· < ·) ∧ ∀ x ∈ l, c ≤ x ∧ x ≤ n := by
  intro k
  induction k with
  | zero =>
    intro c hk hc
    refine ⟨[c], rfl, hT c (fun e he => ?_), List.pairwise_singleton _ _, ?_⟩
    · have := hB c e he
      omega
    · intro x hx
      have : x = c := by simpa using hx
      omega
  | succ k ih =>
    intro c hk hc
    by_cases h : ∃ e, B c e
    · obtain ⟨e, he⟩ := h
      have hbe := hB c e he
      obtain ⟨l, hhead, hchain, hpw, hall⟩ := ih e (by omega) hbe.2
      cases l with
      | nil => simp at hhead
      | cons x r =>
        have hx : x = e := by simpa using hhead
        subst hx
        refine ⟨c :: x :: r, rfl, ⟨he, hchain⟩, ?_, ?_⟩
        · exact List.pairwise_cons.2 ⟨fun y hy => by have := (hall y hy).1; omega, hpw⟩
        · intro y hy
          rcases List.mem_cons.1 hy with rfl | hy'
          · omega
          · have := hall y hy'
            omega
    · refine ⟨[c], rfl, hT c (fun e he => h ⟨e, he⟩), List.pairwise_singleton _ _, ?_⟩
      intro x hx
      have : x = c := by simpa using hx
      omega

/-- 把链条上的存在性抬到分解上。 -/
theorem decomp_exists_of_chain {p : Policy} {S : Seq}
    (hlinks : ∀ cuts, p.Links S cuts ↔ Chain (p.Blk S) (p.Tail S) cuts)
    (hB : ∀ s e, p.Blk S s e → s < e ∧ e ≤ S.length)
    (hT : ∀ s, (∀ e, ¬ p.Blk S s e) → p.Tail S s) : ∃ d, ValidDecomp p S d := by
  obtain ⟨l, hhead, hchain, hpw, hall⟩ :=
    chain_exists S.length hB hT S.length 0 (by omega) (by omega)
  exact ⟨⟨l⟩, ⟨hhead, hpw, fun c hc => (hall c hc).2⟩, (hlinks l).2 hchain⟩

theorem anyBlk_bounds {S : Seq} {s e : Nat} (h : AnyBlk S s e) : s < e ∧ e ≤ S.length := by
  have := h.1
  have := h.2.2.1
  omega

/-- 同级别政策下合法分解存在且唯一，对任意区间序列成立。 -/
theorem same_existsUnique (S : Seq) : ∃! d, ValidDecomp .same S d := by
  obtain ⟨d, hd⟩ := decomp_exists_of_chain (p := .same) (S := S) (fun _ => Iff.rfl)
    (fun s e h => by have := h.1; have := h.2.1; omega)
    (fun _ h e _ => h e)
  exact ⟨d, hd, fun d' hd' => same_unique hd' hd⟩

/-- 最早成块政策下合法分解存在且唯一。 -/
theorem minimal_existsUnique (S : Seq) : ∃! d, ValidDecomp .minimal S d := by
  obtain ⟨d, hd⟩ := decomp_exists_of_chain (p := .minimal) (S := S) (fun _ => Iff.rfl)
    (fun s e h => anyBlk_bounds h.1)
    (fun s h e _ => by
      have key : ∀ e, ¬ AnyBlk S s e := by
        intro e
        induction e using Nat.strongRecOn with
        | _ e ih => exact fun he => h e ⟨he, fun x hx => ih x hx⟩
      exact key e)
  exact ⟨d, hd, fun d' hd' => minimal_unique hd' hd⟩

/-- 最晚成块政策下合法分解存在且唯一。 -/
theorem maximal_existsUnique (S : Seq) : ∃! d, ValidDecomp .maximal S d := by
  have key : ∀ s, (∀ e, ¬ Policy.maximal.Blk S s e) →
      ∀ m e, S.length - e ≤ m → ¬ AnyBlk S s e := by
    intro s h m
    induction m with
    | zero =>
      intro e hm he
      exact h e ⟨he, fun x hx hlt _ => by omega⟩
    | succ m ih =>
      intro e hm he
      exact h e ⟨he, fun x hx hlt hx' => ih x (by omega) hx'⟩
  obtain ⟨d, hd⟩ := decomp_exists_of_chain (p := .maximal) (S := S) (fun _ => Iff.rfl)
    (fun s e h => anyBlk_bounds h.1)
    (fun s h e _ => key s h S.length e (by omega))
  exact ⟨d, hd, fun d' hd' => maximal_unique hd' hd⟩

/-- 不设上限政策下合法分解存在且唯一。 -/
theorem noCap_existsUnique (S : Seq) : ∃! d, ValidDecomp .noCap S d := by
  obtain ⟨d, hd⟩ := decomp_exists_of_chain (p := .noCap) (S := S) (fun _ => Iff.rfl)
    (fun s e h => by have := h.1; have := h.2.2.1; omega)
    (fun _ h e _ => h e)
  exact ⟨d, hd, fun d' hd' => noCap_unique hd' hd⟩

/-- 规范进位政策下，从任意起点出发都有一条合法链。 -/
theorem carryChain_exists (S : Seq) :
    ∀ k c, S.length - c ≤ k → c ≤ S.length →
      ∃ l : List Nat, l.head? = some c ∧ CarryChain S 0 l ∧
        l.Pairwise (· < ·) ∧ ∀ x ∈ l, c ≤ x ∧ x ≤ S.length := by
  intro k
  induction k with
  | zero =>
    intro c hk hc
    refine ⟨[c], rfl, ⟨rfl, fun e _ hb => ?_, fun hn => ?_⟩, List.pairwise_singleton _ _, ?_⟩
    · have := hb.1.1
      have := hb.1.2.2.1
      omega
    · have := hn.1
      omega
    · intro x hx
      have : x = c := by simpa using hx
      omega
  | succ k ih =>
    intro c hk hc
    by_cases hn : Nine S c
    · have h9 := hn.1
      obtain ⟨l, hhead, hchain, hpw, hall⟩ := ih (c + 3 + 3 + 3) (by omega) (by omega)
      cases l with
      | nil => simp at hhead
      | cons x r =>
        have hx : x = c + 3 + 3 + 3 := by simpa using hhead
        subst hx
        have hr : ∀ y ∈ r, c + 3 + 3 + 3 ≤ y ∧ y ≤ S.length :=
          fun y hy => hall y (List.mem_cons_of_mem _ hy)
        refine ⟨c :: (c + 3) :: (c + 3 + 3) :: (c + 3 + 3 + 3) :: r, rfl,
          Or.inr ⟨hn, rfl, rfl, rfl, hchain⟩, ?_, ?_⟩
        · refine List.pairwise_cons.2 ⟨?_, List.pairwise_cons.2 ⟨?_, List.pairwise_cons.2 ⟨?_, hpw⟩⟩⟩
          · intro y hy
            simp only [List.mem_cons] at hy
            rcases hy with rfl | rfl | rfl | hy
            · omega
            · omega
            · omega
            · have := hr y hy
              omega
          · intro y hy
            simp only [List.mem_cons] at hy
            rcases hy with rfl | rfl | hy
            · omega
            · omega
            · have := hr y hy
              omega
          · intro y hy
            simp only [List.mem_cons] at hy
            rcases hy with rfl | hy
            · omega
            · have := hr y hy
              omega
        · intro y hy
          simp only [List.mem_cons] at hy
          rcases hy with rfl | rfl | rfl | rfl | hy
          · omega
          · omega
          · omega
          · omega
          · have := hr y hy
            omega
    · by_cases hb : ∃ e, Brk S c e
      · obtain ⟨e, he⟩ := hb
        have h1 := he.1.1
        have h2 := he.1.2.2.1
        obtain ⟨l, hhead, hchain, hpw, hall⟩ := ih e (by omega) h1
        cases l with
        | nil => simp at hhead
        | cons x r =>
          have hx : x = e := by simpa using hhead
          subst hx
          refine ⟨c :: x :: r, rfl, Or.inl ⟨he, hchain⟩, ?_, ?_⟩
          · exact List.pairwise_cons.2 ⟨fun y hy => by have := (hall y hy).1; omega, hpw⟩
          · intro y hy
            rcases List.mem_cons.1 hy with rfl | hy'
            · omega
            · have := hall y hy'
              omega
      · refine ⟨[c], rfl, ⟨rfl, fun e _ hbe => hb ⟨e, hbe⟩, hn⟩, List.pairwise_singleton _ _, ?_⟩
        intro x hx
        have : x = c := by simpa using hx
        omega

/-- 规范进位政策下合法分解存在且唯一。 -/
theorem carry_existsUnique (S : Seq) : ∃! d, ValidDecomp .carry S d := by
  obtain ⟨l, hhead, hchain, hpw, hall⟩ :=
    carryChain_exists S S.length 0 (by omega) (by omega)
  have hd : ValidDecomp .carry S ⟨l⟩ := ⟨⟨hhead, hpw, fun c hc => (hall c hc).2⟩, hchain⟩
  exact ⟨⟨l⟩, hd, fun d' hd' => carry_unique hd' hd⟩

/-! ## 多级规范 -/

/-- 各级政策都至多一个合法分解时，多级规范也至多一份。 -/
theorem tower_unique {ps : List Policy}
    (hU : ∀ p ∈ ps, ∀ (S : Seq) (d d' : Decomp),
      ValidDecomp p S d → ValidDecomp p S d' → d = d') :
    ∀ (S : Seq) (ds ds' : List Decomp), ValidTower ps S ds → ValidTower ps S ds' → ds = ds' := by
  induction ps with
  | nil =>
    intro S ds ds' h h'
    cases ds with
    | nil =>
      cases ds' with
      | nil => rfl
      | cons _ _ => exact h'.elim
    | cons _ _ => exact h.elim
  | cons p ps ih =>
    intro S ds ds' h h'
    cases ds with
    | nil => exact h.elim
    | cons d r =>
      cases ds' with
      | nil => exact h'.elim
      | cons d' r' =>
        have hd : d = d' := hU p (by simp) S d d' h.1 h'.1
        subst hd
        rw [ih (fun q hq => hU q (List.mem_cons_of_mem _ hq)) _ r r' h.2 h'.2]

/-- 混合政策（下级规范进位、本级同级别、更高级不出现）下，多级分解至多一份。 -/
theorem mixed_unique {S : Seq} {ds ds' : List Decomp} (h : ValidTower [.carry, .same] S ds)
    (h' : ValidTower [.carry, .same] S ds') : ds = ds' := by
  refine tower_unique (fun p hp S d d' a b => ?_) S ds ds' h h'
  rcases List.mem_cons.1 hp with rfl | hp
  · exact carry_unique a b
  · rcases List.mem_cons.1 hp with rfl | hp
    · exact same_unique a b
    · simp at hp

/-- 各级政策都有合法分解时，多级规范也有。 -/
theorem tower_exists {ps : List Policy}
    (hE : ∀ p ∈ ps, ∀ S : Seq, ∃ d, ValidDecomp p S d) : ∀ S : Seq, ∃ ds, ValidTower ps S ds := by
  induction ps with
  | nil => exact fun _ => ⟨[], trivial⟩
  | cons p ps ih =>
    intro S
    obtain ⟨d, hd⟩ := hE p (by simp) S
    obtain ⟨ds, hds⟩ := ih (fun q hq => hE q (List.mem_cons_of_mem _ hq)) (coarsen S d.cuts)
    exact ⟨d :: ds, hd, hds⟩

/-- 混合政策下多级分解存在且唯一。 -/
theorem mixed_existsUnique (S : Seq) : ∃! ds, ValidTower [.carry, .same] S ds := by
  obtain ⟨ds, hds⟩ := tower_exists (ps := [.carry, .same]) (fun p hp S => by
    rcases List.mem_cons.1 hp with rfl | hp
    · exact (carry_existsUnique S).exists
    · rcases List.mem_cons.1 hp with rfl | hp
      · exact (same_existsUnique S).exists
      · simp at hp) S
  exact ⟨ds, hds, fun ds' hds' => mixed_unique hds' hds⟩

/-! ## 有限枚举的完备性 -/

/-- 元素落在 `[lo, lo + fuel)` 的严格递增表都在 `incLists lo fuel` 里。 -/
theorem mem_incLists : ∀ (fuel lo : Nat) (l : List Nat), l.Pairwise (· < ·) →
    (∀ x ∈ l, lo ≤ x ∧ x < lo + fuel) → l ∈ incLists lo fuel
  | 0, lo, l, _, hb => by
    cases l with
    | nil => simp [incLists]
    | cons x t =>
      have := hb x (by simp)
      omega
  | fuel + 1, lo, l, hp, hb => by
    unfold incLists
    cases l with
    | nil =>
      exact List.mem_append_left _ (mem_incLists fuel (lo + 1) [] List.Pairwise.nil (by simp))
    | cons x t =>
      rw [List.pairwise_cons] at hp
      have hbx := hb x (by simp)
      by_cases hx : x = lo
      · subst hx
        refine List.mem_append_right _
          (List.mem_map.2 ⟨t, mem_incLists fuel (x + 1) t hp.2 ?_, rfl⟩)
        intro y hy
        have := hp.1 y hy
        have := hb y (List.mem_cons_of_mem _ hy)
        omega
      · refine List.mem_append_left _
          (mem_incLists fuel (lo + 1) (x :: t) (List.pairwise_cons.2 hp) ?_)
        intro y hy
        rcases List.mem_cons.1 hy with rfl | hyt
        · omega
        · have := hp.1 y hyt
          have := hb y (List.mem_cons_of_mem _ hyt)
          omega

/-- 良构切点表都在候选枚举里。 -/
theorem wf_mem_candidates {n : Nat} {cuts : List Nat} (h : WF n cuts) : cuts ∈ candidates n := by
  obtain ⟨hhead, hp, hb⟩ := h
  cases cuts with
  | nil => simp at hhead
  | cons x t =>
    have hx : x = 0 := by simpa using hhead
    subst hx
    rw [List.pairwise_cons] at hp
    refine List.mem_map.2 ⟨t, mem_incLists n 1 t hp.2 ?_, rfl⟩
    intro y hy
    have := hp.1 y hy
    have := hb y (List.mem_cons_of_mem _ hy)
    omega

/-- 合法分解的切点表恰是 `validCuts` 的成员。 -/
theorem valid_iff_mem_validCuts {p : Policy} {S : Seq} {d : Decomp} :
    ValidDecomp p S d ↔ d.cuts ∈ validCuts p S := by
  constructor
  · intro h
    exact List.mem_filter.2 ⟨wf_mem_candidates h.1, decide_eq_true h⟩
  · intro h
    exact of_decide_eq_true (List.mem_filter.1 h).2

/-- 枚举读数只有一个成员时，合法分解存在且唯一。 -/
theorem existsUnique_of_validCuts {p : Policy} {S : Seq} {c : List Nat}
    (h : validCuts p S = [c]) : ∃! d, ValidDecomp p S d := by
  refine ⟨⟨c⟩, valid_iff_mem_validCuts.2 (by simp [h]), fun d hd => ?_⟩
  have hm := valid_iff_mem_validCuts.1 hd
  rw [h] at hm
  cases d
  simpa using hm

/-- 枚举读数有两个不同成员时，合法分解不唯一。 -/
theorem not_unique_of_validCuts {p : Policy} {S : Seq} {c c' : List Nat}
    (hc : c ∈ validCuts p S) (hc' : c' ∈ validCuts p S) (hne : c ≠ c') :
    ¬ ∃! d, ValidDecomp p S d := by
  rintro ⟨d, _, huniq⟩
  have h1 := huniq ⟨c⟩ (valid_iff_mem_validCuts.2 hc)
  have h2 := huniq ⟨c'⟩ (valid_iff_mem_validCuts.2 hc')
  exact hne (by simpa using h1.trans h2.symm)

end ChanExplore.Proto2318
