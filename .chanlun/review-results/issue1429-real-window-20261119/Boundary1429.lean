import Formal.RecursiveConstruction

namespace Issue1429
open Formal.TrendTrichotomy (Direction)
open Formal.CenterTrichotomy (Center)
open Formal.RecursiveConstruction

/-- 三成员均为线段：候选只要满足原谓词，四个端点就都与同窗原构造器相等。 -/
theorem segment_unique (d0 d1 d2 : Direction) (l0 h0 l1 h1 l2 h2 : Int)
    (c : Center)
    (hov : WindowOverlap (.segment d0 l0 h0) (.segment d1 l1 h1) (.segment d2 l2 h2))
    (hc : CenterDerivedAt [.segment d0 l0 h0, .segment d1 l1 h1, .segment d2 l2 h2] c 0) :
    c = deriveWindowCenter3 (.segment d0 l0 h0) (.segment d1 l1 h1) (.segment d2 l2 h2) hov := by
  obtain ⟨_, hc⟩ := hc
  obtain ⟨hzd, hzg, x, y, z, hx, hy, hz, hdd, hgg⟩ := hc (by change 0 < 3; decide) (by change 1 < 3; decide) (by change 2 < 3; decide)
  change d0 = x at hx
  change d1 = y at hy
  change d2 = z at hz
  subst x
  subst y
  subst z
  cases c with
  | mk dd zd zg gg _ _ _ =>
    dsimp only at hdd hzd hzg hgg
    subst dd
    subst zd
    subst zg
    subst gg
    rfl

/-- 即使是未定投影的上级窗口，首成员始终进入 Zn，合法外缘不可能剪去其高或低。 -/
theorem contains_first (a b c : Move) (k : Center) (h : CenterDerivedAt [a,b,c] k 0) :
    k.dd ≤ a.lo ∧ a.hi ≤ k.gg := by
  obtain ⟨_, h⟩ := h
  obtain ⟨_, _, d0, d1, d2, _, _, _, hdd, hgg⟩ :=
    h (by change 0 < 3; decide) (by change 1 < 3; decide) (by change 2 < 3; decide)
  rw [hdd, hgg]
  exact ⟨znDD_le_first d0 d1 d2 a b c, first_le_znGG d0 d1 d2 a b c⟩

/-- 9011 第二窗的三个 L0 线段：558↓、653↑、678↓。只取交接给本探针的端点。 -/
def realWindow : List Move :=
  [.segment .down 7478 11988, .segment .up 7478 9155, .segment .down 8205 9155]
def localCenter : Center := ⟨7478,8205,9155,11988,by decide,by decide,by decide⟩
def motherOnly : Center := ⟨7478,8205,9155,9155,by decide,by decide,by decide⟩

theorem real_local : windowCenters realWindow = [localCenter] := rfl

theorem real_rejects_mother : ¬ CenterDerivedAt realWindow motherOnly 0 := by
  intro h
  have e := segment_unique .down .up .down 7478 11988 7478 9155 8205 9155 motherOnly (by decide) h
  have g := congrArg Center.gg e
  change (9155 : Int) = 11988 at g
  exact (by decide : (9155 : Int) ≠ 11988) g

/-- 独立的上级判别例：九条交替相接线段，三个真交叠的下窗。 -/
def pack (a b c : Move) : Move := .compose [a,b,c] (windowCenters [a,b,c]) 1
def a : Move := pack (.segment .up 10 30) (.segment .down 15 30) (.segment .up 15 25)
def b : Move := pack (.segment .down 4 25) (.segment .up 4 40) (.segment .down 22 40)
def c : Move := pack (.segment .up 22 35) (.segment .down 20 35) (.segment .up 20 33)

theorem a_wf : WellFormed a :=
  window_wellFormed _ _ _ 0 (by decide) rfl rfl rfl (by simp [WellFormed]) (by simp [WellFormed]) (by simp [WellFormed])
theorem b_wf : WellFormed b :=
  window_wellFormed _ _ _ 0 (by decide) rfl rfl rfl (by simp [WellFormed]) (by simp [WellFormed]) (by simp [WellFormed])
theorem c_wf : WellFormed c :=
  window_wellFormed _ _ _ 0 (by decide) rfl rfl rfl (by simp [WellFormed]) (by simp [WellFormed]) (by simp [WellFormed])

def projected : Center := ⟨10,20,30,35,by decide,by decide,by decide⟩
def canonical : Center := ⟨4,20,30,40,by decide,by decide,by decide⟩

theorem projected_ok : CenterDerivedAt [a,b,c] projected 0 :=
  ⟨by decide, fun _ _ _ => ⟨rfl, rfl, .up, .down, .up, True.intro, True.intro, True.intro, rfl, rfl⟩⟩
theorem canonical_ok : CenterDerivedAt [a,b,c] canonical 0 :=
  ⟨by decide, fun _ _ _ => ⟨rfl, rfl, .up, .up, .up, True.intro, True.intro, True.intro, rfl, rfl⟩⟩
theorem constructor_choice : windowCenters [a,b,c] = [canonical] := rfl

theorem packed_wf (k : Center) (hk : CenterDerivedAt [a,b,c] k 0) :
    WellFormed (.compose [a,b,c] [k] 2) := by
  unfold WellFormed
  refine ⟨by decide, by decide, ?_, by change 1 ≤ 1; decide,
    ⟨List.cons_ne_nil _ _, [0], rfl, True.intro, hk, True.intro⟩, ?_⟩
  · simp only [List.forall_mem_cons, List.not_mem_nil, false_implies, implies_true, and_true]
    exact ⟨rfl,rfl,rfl⟩
  · simp only [List.forall_mem_cons, List.not_mem_nil, false_implies, implies_true, and_true]
    exact ⟨a_wf,b_wf,c_wf⟩

/-- 良构并未补回方向来源。两个不同外缘、相同核心、相同下级，父走势都递归良构。 -/
theorem upper_nonunique :
    projected ≠ canonical ∧ WellFormed (.compose [a,b,c] [projected] 2) ∧
      WellFormed (.compose [a,b,c] [canonical] 2) := by
  refine ⟨?_, packed_wf _ projected_ok, packed_wf _ canonical_ok⟩
  intro e
  exact (by decide : (10 : Int) ≠ 4) (congrArg Center.dd e)

#print axioms contains_first
#print axioms segment_unique
#print axioms real_local
#print axioms real_rejects_mother
#print axioms constructor_choice
#print axioms upper_nonunique
end Issue1429
