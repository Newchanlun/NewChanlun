module

public import ChanExplore.Proto2318.Unique
public import ChanExplore.Proto2318.Repr

/-!
# 判别例的内核读数

每条 `validCuts … = …` 都由内核对全部良构切点表穷举得出，与 `py/cases.py` 的输出一致。
`∃!` 结论经 `existsUnique_of_validCuts` 由枚举读数推出，量化范围是全体 `Decomp`。
-/

@[expose] public section

namespace ChanExplore.Proto2318

/-- `0,1` 来回八段。 -/
def osc8 : Seq := segs [0, 1, 0, 1, 0, 1, 0, 1, 0]

/-- `0,1` 来回九段。 -/
def osc9 : Seq := segs [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]

/-- 设计输入的九段折线：后六段都触及原核，末三段自身没有公共部分。 -/
def bend9 : Seq := segs [0, 20, 2, 22, 12, 18, 16, 19, 4, 8]

/-- 相邻两核外缘相触的七段折线：核 `[7,8]` 与 `[13,14]`，外缘 `[6,9]` 与 `[9,15]`。 -/
def exp7 : Seq := segs [9, 6, 8, 7, 15, 9, 14, 13]

/-- 三段成一组的括号树节点。 -/
def group3 (g : Gen) : Tree :=
  .node g (.cons .seg (.cons .seg (.cons .seg .nil)))

/-- 九段按 3+3+3 结合的括号树，根与三组的生成方式可选。 -/
def tree9 (root kid : Gen) : Tree :=
  .node root (.cons (group3 kid) (.cons (group3 kid) (.cons (group3 kid) .nil)))

/-- 九段折线的层状族：第 1 级切 `{0,3,6,9}`，第 2 级切 `{0,9}`。 -/
def lam9 (certs : List Cert) : Laminar where
  level := fun l =>
    match l with
    | 0 => Finset.range 10
    | 1 => {0, 3, 6, 9}
    | 2 => {0, 9}
    | _ => ∅
  depth := 2
  bound := 9
  certs := certs

/-- 九段折线的序列塔，顶层证书可选。 -/
def tower9 (top : Cert) : Tower :=
  [[⟨0, 3, ⟨0, 22⟩, none⟩, ⟨3, 6, ⟨12, 22⟩, none⟩, ⟨6, 9, ⟨4, 19⟩, none⟩],
    [⟨0, 9, ⟨0, 22⟩, some top⟩]]

end ChanExplore.Proto2318

end

public section

namespace ChanExplore.Proto2318

/-! ## 八段来回：3+5 与 5+3 -/

theorem osc8_anyFull : validCuts .anyFull osc8 = [[0, 5, 8], [0, 3, 8]] := by decide +kernel
theorem osc8_anyExh :
    validCuts .anyExh osc8 = [[0, 7], [0, 5, 8], [0, 3, 8], [0, 3, 6]] := by decide +kernel
theorem osc8_extExh :
    validCuts .extExh osc8 = [[0, 7], [0, 5, 8], [0, 3, 8], [0, 3, 6]] := by decide +kernel
theorem osc8_same : validCuts .same osc8 = [[0, 3, 6]] := by decide +kernel
theorem osc8_minimal : validCuts .minimal osc8 = [[0, 3, 6]] := by decide +kernel
theorem osc8_maximal : validCuts .maximal osc8 = [[0, 7]] := by decide +kernel
theorem osc8_noCap : validCuts .noCap osc8 = [[0]] := by decide +kernel
theorem osc8_carry : validCuts .carry osc8 = [[0]] := by decide +kernel

/-- 票面合法集（覆盖全程、每块有中枢、不到九段）在八段来回上有两个不同的合法分解。 -/
theorem osc8_anyFull_not_unique : ¬ ∃! d, ValidDecomp .anyFull osc8 d :=
  not_unique_of_validCuts (c := [0, 5, 8]) (c' := [0, 3, 8])
    (by rw [osc8_anyFull]; decide) (by rw [osc8_anyFull]; decide) (by decide)

theorem osc8_same_existsUnique : ∃! d, ValidDecomp .same osc8 d :=
  existsUnique_of_validCuts osc8_same
theorem osc8_minimal_existsUnique : ∃! d, ValidDecomp .minimal osc8 d :=
  existsUnique_of_validCuts osc8_minimal
theorem osc8_maximal_existsUnique : ∃! d, ValidDecomp .maximal osc8 d :=
  existsUnique_of_validCuts osc8_maximal
theorem osc8_noCap_existsUnique : ∃! d, ValidDecomp .noCap osc8 d :=
  existsUnique_of_validCuts osc8_noCap
theorem osc8_carry_existsUnique : ∃! d, ValidDecomp .carry osc8 d :=
  existsUnique_of_validCuts osc8_carry

/-- 五个起点定终点的政策把 3+5 与 5+3 都排掉。 -/
theorem osc8_rejects_both :
    ∀ p ∈ [Policy.same, .minimal, .maximal, .noCap, .carry],
      ¬ ValidDecomp p osc8 ⟨[0, 3, 8]⟩ ∧ ¬ ValidDecomp p osc8 ⟨[0, 5, 8]⟩ := by
  decide +kernel

/-- 排除依据之一：三段块与五段块同起点且都合法，块语言不是起点定终点的。 -/
theorem osc8_prefix_clash : AnyBlk osc8 0 3 ∧ AnyBlk osc8 0 5 ∧ AnyBlk osc8 0 7 := by
  decide +kernel

/-- 排除依据之二：八段全都触及首三段的核，核没有被破坏，也没满九段。 -/
theorem osc8_core_unbroken :
    (∀ j, j < 8 → TouchAt osc8 0 j) ∧ ¬ BrokenAt osc8 0 3 ∧ ¬ BrokenAt osc8 0 5 ∧
      ¬ Nine osc8 0 := by
  decide +kernel

/-! ## 九段折线 -/

theorem bend9_anyFull : validCuts .anyFull bend9 = [] := by decide +kernel
theorem bend9_anyExh :
    validCuts .anyExh bend9 = [[0, 7], [0, 5, 8], [0, 3, 8], [0, 3, 6]] := by decide +kernel
theorem bend9_extExh :
    validCuts .extExh bend9 = [[0, 7], [0, 5, 8], [0, 3, 8], [0, 3, 6]] := by decide +kernel
theorem bend9_same : validCuts .same bend9 = [[0, 3, 6]] := by decide +kernel
theorem bend9_minimal : validCuts .minimal bend9 = [[0, 3, 6]] := by decide +kernel
theorem bend9_maximal : validCuts .maximal bend9 = [[0, 7]] := by decide +kernel
theorem bend9_noCap : validCuts .noCap bend9 = [[0]] := by decide +kernel
theorem bend9_carry : validCuts .carry bend9 = [[0, 3, 6, 9]] := by decide +kernel

theorem bend9_same_existsUnique : ∃! d, ValidDecomp .same bend9 d :=
  existsUnique_of_validCuts bend9_same
theorem bend9_carry_existsUnique : ∃! d, ValidDecomp .carry bend9 d :=
  existsUnique_of_validCuts bend9_carry

/-- 九段都触及原核，而第七至九段自身没有公共部分。 -/
theorem bend9_nine_without_third_seed : Nine bend9 0 ∧ OvAt bend9 0 ∧ OvAt bend9 3 ∧
    ¬ OvAt bend9 6 := by
  decide +kernel

/-- 九段来回上各政策的读数：规范进位在第九段处切成 3+3+3。 -/
theorem osc9_carry : validCuts .carry osc9 = [[0, 3, 6, 9]] := by decide +kernel
theorem osc9_same : validCuts .same osc9 = [[0, 3, 6, 9]] := by decide +kernel
theorem osc9_noCap : validCuts .noCap osc9 = [[0]] := by decide +kernel

/-! ## 混合政策（038:24 至 038:28）：下级规范进位，本级同级别，更高级不出现 -/

theorem bend9_mixed_tower :
    ValidTower [.carry, .same] bend9 [⟨[0, 3, 6, 9]⟩, ⟨[0, 3]⟩] := by decide +kernel

theorem bend9_same_tower :
    ValidTower [.same, .same] bend9 [⟨[0, 3, 6]⟩, ⟨[0]⟩] := by decide +kernel

/-! ## 生成证书：后两类不能冒充第一类 -/

/-- 九段折线上，九项延伸证书成立。 -/
theorem bend9_nineExt_holds : (Cert.nineExt 0 0).Holds bend9 [[0, 3, 6, 9], [0, 9]] := by
  decide +kernel

/-- 九段折线上，无论第 1 级怎么切，都拿不出「三块各自成核且有公共重叠」的证书。 -/
theorem bend9_no_seed3 :
    ∀ c ∈ candidates 9, ∀ a, a < 10 → ¬ (Cert.seed3 1 a).Holds bend9 [c] := by
  decide +kernel

/-- 九段来回是特殊情形：九项延伸与三块成核两种证书同时成立。 -/
theorem osc9_both_certs :
    (Cert.nineExt 0 0).Holds osc9 [[0, 3, 6, 9]] ∧ (Cert.seed3 1 0).Holds osc9 [[0, 3, 6, 9]] := by
  decide +kernel

/-- 七段折线上，相邻两核外缘相触的证书成立。 -/
theorem exp7_expand_holds : (Cert.expand 0 0 4).Holds exp7 [] := by decide +kernel

/-- 同一条七段折线上，无论第 1 级怎么切，三块成核与九项延伸两种证书都不成立。 -/
theorem exp7_no_other_cert :
    ∀ c ∈ candidates 7, ∀ a, a < 8 →
      ¬ (Cert.seed3 1 a).Holds exp7 [c] ∧ ¬ (Cert.nineExt 0 a).Holds exp7 [c] := by
  decide +kernel

/-- 两个三段种子端点相同、核相同，实际值域不同。 -/
theorem seeds_same_core_diff_hull :
    coreAt (segs [0, 4, 2, 3]) 0 = coreAt (segs [0, 7, 2, 3]) 0 ∧
      hull (segs [0, 4, 2, 3]) = ⟨0, 4⟩ ∧ hull (segs [0, 7, 2, 3]) = ⟨0, 7⟩ := by
  decide +kernel

/-- 同一个后继值域 `[5,6]` 与前一个种子不相触，与后一个种子相触：
上一级只留端点、或只留端点加核，都分不开这两种相对位置。 -/
theorem seeds_relative_position_differs :
    ¬ Touch (hull (segs [0, 4, 2, 3])) ⟨5, 6⟩ ∧ Touch (hull (segs [0, 7, 2, 3])) ⟨5, 6⟩ := by
  decide +kernel

/-! ## 三种表示各自承载同一份证书 -/

theorem tree9_fam : (tree9 .nineExt .group).fam = [[0, 3, 6, 9], [0, 9]] := by decide +kernel
theorem tree9_uniform : (tree9 .nineExt .group).Uniform 2 := by
  refine ⟨by decide, ⟨?_, ?_, ?_, trivial⟩⟩ <;>
    exact ⟨by decide, rfl, rfl, rfl, trivial⟩

/-- 括号树：根标九项延伸，证书成立。 -/
theorem tree9_certs_hold :
    ∀ c ∈ (tree9 .nineExt .group).certs 0, c.Holds bend9 (tree9 .nineExt .group).fam := by
  decide +kernel

/-- 括号树：根与三组都改标三段成核，根证书与第三组证书不成立。 -/
theorem tree9_forged :
    ((tree9 .seed3 .seed3).certs 0).map (fun c => decide (c.Holds bend9 (tree9 .seed3 .seed3).fam)) =
      [false, true, true, false] := by
  decide +kernel

theorem lam9_fam : (lam9 []).fam = [[0, 3, 6, 9], [0, 9]] := by decide +kernel
theorem lam9_nested : (lam9 []).NestedUpTo := by decide +kernel

/-- 层状族：证书表放九项延伸则成立，放三块成核则不成立。 -/
theorem lam9_certs :
    (∀ c ∈ (lam9 [.nineExt 0 0]).certs, c.Holds bend9 (lam9 [.nineExt 0 0]).fam) ∧
      ¬ ∀ c ∈ (lam9 [.seed3 1 0]).certs, c.Holds bend9 (lam9 [.seed3 1 0]).fam := by
  decide +kernel

theorem tower9_fam : (tower9 (.nineExt 0 0)).fam = [[0, 3, 6, 9], [0, 9]] := by decide +kernel
theorem tower9_ranges : (tower9 (.nineExt 0 0)).RangesOK bend9 := by decide +kernel

/-- 序列塔：顶层证书为九项延伸则成立，改成三块成核则不成立。 -/
theorem tower9_certs :
    (∀ c ∈ (tower9 (.nineExt 0 0)).certs, c.Holds bend9 (tower9 (.nineExt 0 0)).fam) ∧
      ¬ ∀ c ∈ (tower9 (.seed3 1 0)).certs, c.Holds bend9 (tower9 (.seed3 1 0)).fam := by
  decide +kernel

end ChanExplore.Proto2318

#print axioms ChanExplore.Proto2318.same_existsUnique
#print axioms ChanExplore.Proto2318.carry_existsUnique
#print axioms ChanExplore.Proto2318.mixed_existsUnique
#print axioms ChanExplore.Proto2318.osc8_anyFull_not_unique
#print axioms ChanExplore.Proto2318.osc8_carry_existsUnique
#print axioms ChanExplore.Proto2318.bend9_no_seed3
#print axioms ChanExplore.Proto2318.Tree.pow_le_width
#print axioms ChanExplore.Proto2318.Laminar.address_unique
