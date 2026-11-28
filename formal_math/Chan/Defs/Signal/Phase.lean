module

public import Chan.Defs.Level.TrendType

@[expose] public section

namespace Chan.Defs.Signal

open Chan.Defs.Order Chan.Defs.Alt Chan.Defs.Center Chan.Defs.Level
universe u
variable {P : Type u} [LinearOrder P]

/-- 中阴、围绕新核震荡、离开该核；阶段相对于所选走势的起点。
[101:42] 注意，只有在这回升的中阴状态下才有第一、二类买点，中阴状态结束后，所有的中枢震荡只存在第三类买卖点以及中枢震荡的买卖点，就不存在第一、二类买卖点了。 -/
inductive Phase where
  | transition | oscillation | departure
  deriving DecidableEq

/-- 实际起止价位于段内，不把区间极值自动当作端点。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。 -/
structure DirectedEndpoints (s : Seg P) where
  entry : P
  exit : P
  entryInside : s.range.lo ≤ entry ∧ entry ≤ s.range.hi
  exitInside : s.range.lo ≤ exit ∧ exit ≤ s.range.hi
  directed : match s.dir with | .up => entry ≤ exit | .down => exit ≤ entry

/-- 段的独立实际端点证书。 -/
abbrev Endpoints (s : Seg P) := DirectedEndpoints s

/-- 单层块划分是信号的显式输入。段表只收已完成次级段（深度零则为基底段）；切点、完成块及其同级枢账逐项对应。
`origin` 是阶段观察起点；一类点另由该切点处的完成趋势认证，截短历史亦可观察阶段。
[054:58] 相应的5分钟中枢区间就是[d3，g5]，在这种情况下，d7g7也是一个中枢震荡，但不构成第三类卖点，因为不符合条件。
[053:20] 但无论这些显微镜如何转换，一个原则是不变的，就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。
[101:42] 注意，只有在这回升的中阴状态下才有第一、二类买点，中阴状态结束后，所有的中枢震荡只存在第三类买卖点以及中枢震荡的买卖点，就不存在第一、二类买卖点了。 -/
structure StageLedger (r : BlockRule.{u}) (depth : Nat) (xs : List (Seg P))
    (marks : List Nat) where
  validMarks : marks ≠ [] ∧ marks.IsChain (· < ·) ∧ (∀ j ∈ marks, j ≤ xs.length)
  price : (i : Fin xs.length) → Endpoints xs[i.val]
  legal : ∀ p ∈ (marks.zip marks.tail).zipIdx,
    (r.rank depth xs (marks.take p.2).reverse p.1.1 p.1.2).isSome = true
  completed : List (Finished xs)
  aligned : completed.map (fun b => (b.first, b.stop)) = marks.zip marks.tail
  centers : List (Center P)
  chronological : centers.Pairwise (fun a b => a.stop ≤ b.start)
  actual : ∀ z ∈ centers, z.stop ≤ xs.length ∧ xs.extract z.start z.stop = z.cover
  respectsCuts : ∀ z ∈ centers, ∀ j ∈ marks, j ≤ z.start ∨ z.stop ≤ j
  accounts : ∀ b ∈ completed,
    centers.filter (fun z => decide (b.first ≤ z.start ∧ z.stop ≤ b.stop)) = b.centers
  origin : Nat
  originBounded : origin ≤ xs.length

/-- 规则、当前层段表、同坐标切点和认证账本。 -/
structure Decomposition (P : Type u) [LinearOrder P] where
  depth : Nat
  rule : BlockRule.{u}
  steps : List (Seg P)
  marks : List Nat
  ledger : StageLedger rule depth steps marks

abbrev Decomposition.origin (d : Decomposition P) := d.ledger.origin

/-- 从塔还原指定层的实际段表和局部切点；端点及中枢须由同一段表的证书提供。 -/
def Decomposition.ofTowerStage? {r : BlockRule.{u}} {dir : CoarseDirPolicy P} {base : AltSeq P}
    (t : LevelTower r dir base) (depth : Nat)
    (certify : (xs : List (Seg P)) → (marks : List Nat) → Option (StageLedger r depth xs marks)) :
    Option (Decomposition P) :=
  match t.stages? with
  | none => none
  | some (levels, top) =>
    match if depth == levels.length then some (top, [0]) else levels[depth]? with
    | none => none
    | some (stage, marks) =>
      match certify stage.items marks with
      | none => none
      | some ledger => some ⟨depth, r, stage.items, marks, ledger⟩

/-- 用段序号取实际端点，越界无观测。
[070:48] 没有人规定分段的结束位置一定是最高、最低的，关键要有至少三笔，因为从37开始到最高的位置，没有三笔，所以不能认为线段已经完成。 -/
def Decomposition.prices? (d : Decomposition P) (i : Nat) : Option (P × P) :=
  if h : i < d.steps.length then
    let p := d.ledger.price ⟨i,h⟩
    some (p.entry,p.exit)
  else none

/-- 截至观察切点，只选指定阶段起点以来已由三段确立的最近同级枢。
[020:54] 特别地，再定义ZG= min(g1、g2),ZD=max(d1、d2)，显然，[ZD，ZG]就是缠中说禅走势中枢的区间，由此有了如下定理：
[054:58] 相应的5分钟中枢区间就是[d3，g5]，在这种情况下，d7g7也是一个中枢震荡，但不构成第三类卖点，因为不符合条件。 -/
def Decomposition.recent (d : Decomposition P) (since cut : Nat) : Option (Center P) :=
  (d.ledger.centers.filter fun z => decide (since ≤ z.start ∧ z.start+3 ≤ cut)).getLast?

/-- 切点是已完成段数。新枢未立为中阴；立枢后按实际覆盖及末段判震荡或离开。越界或早于观察起点没有阶段。
[101:42] 注意，只有在这回升的中阴状态下才有第一、二类买点，中阴状态结束后，所有的中枢震荡只存在第三类买卖点以及中枢震荡的买卖点，就不存在第一、二类买卖点了。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
def phaseAt (d : Decomposition P) (cut : Nat) : Option Phase :=
  if cut < d.origin || d.steps.length < cut then none else
    match d.recent d.origin cut with
    | none => some .transition
    | some z =>
      if cut ≤ z.stop then some .oscillation
      else match d.steps[cut-1]? with
        | some s => if z.extendsWith s then some .oscillation else some .departure
        | none => none

end Chan.Defs.Signal
