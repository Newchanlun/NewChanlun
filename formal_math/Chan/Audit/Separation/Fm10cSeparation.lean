module

/-!
# FM-10c 双轨定义的有限分离见证（#2320）

甲方 = Opus（`d7a2a8c094`），乙方 = Astra（`9ab813738d`）。
本文件只依赖 Lean 核心。两轨在具体 `Int` 价格、`Nat` 地址上重放，有限量化
用列表检验，区间交与凸包共用算子。保留两轨原有门控、索引和参数；
不从融合版定义反推任一盲写臂。见证编号对应对撞报告第三节。
-/

@[expose] public section

namespace Chan.Audit.Separation.Fm10c

inductive Dir where
  | up | down
  deriving DecidableEq, BEq

def Dir.flip : Dir → Dir
  | .up => .down
  | .down => .up

structure Bar where
  lo : Int
  hi : Int
  deriving DecidableEq

def Bar.overlaps (a b : Bar) : Bool :=
  decide (a.lo ≤ b.hi ∧ b.lo ≤ a.hi)

def Bar.hull (a b : Bar) : Bar :=
  ⟨min a.lo b.lo, max a.hi b.hi⟩

/-- 一段的方向、闭区间和原始跨度。输入例的跨度取该段下标。 -/
structure Seg where
  dir : Dir
  range : Bar
  source : Nat × Nat
  deriving DecidableEq

def segments (rows : List (Dir × Int × Int)) : List Seg :=
  rows.zipIdx.map fun ((d, lo, hi), i) => ⟨d, ⟨lo, hi⟩, i, i⟩

def Bar.mirror (pivot : Int) (x : Bar) : Bar := ⟨pivot - x.hi, pivot - x.lo⟩

def Seg.mirror (pivot : Int) (x : Seg) : Seg :=
  ⟨x.dir.flip, x.range.mirror pivot, x.source⟩

def Seg.entry (s : Seg) : Int :=
  match s.dir with | .up => s.range.lo | .down => s.range.hi

def Seg.exit (s : Seg) : Int :=
  match s.dir with | .up => s.range.hi | .down => s.range.lo

def adjacent {α : Type} (xs : List α) : List (α × α) := xs.zip xs.tail

def alternating (xs : List Seg) : Prop :=
  ∀ p ∈ adjacent xs, p.1.dir ≠ p.2.dir

instance (xs : List Seg) : Decidable (alternating xs) := by
  unfold alternating
  infer_instance

def seedBounds (a b c : Seg) : Bar :=
  ⟨max (max a.range.lo b.range.lo) c.range.lo,
   min (min a.range.hi b.range.hi) c.range.hi⟩

def rangeHull (a : Seg) (tail : List Seg) : Bar :=
  tail.foldl (fun acc s => acc.hull s.range) a.range

namespace Opus

/-! M2：按层逐位对比旧表，新表空位视作撤销；最深层从 1 起计。 -/

structure RevisionCount where
  rewritten : Nat
  deepest : Nat
  deriving DecidableEq

def levelRevisions : List Nat → List Nat → Nat
  | [], _ => 0
  | _ :: os, [] => os.length + 1
  | o :: os, n :: ns => (if o = n then 0 else 1) + levelRevisions os ns

def revisionAux : Nat → List (List Nat) → List (List Nat) → RevisionCount
  | _, [], _ => ⟨0, 0⟩
  | d, o :: os, ns =>
    let later := revisionAux (d + 1) os ns.tail
    let here := levelRevisions o (ns.headD [])
    ⟨here + later.rewritten, if 0 < later.deepest then later.deepest
      else if 0 < here then d + 1 else 0⟩

def measure : List (List Nat) → List (List Nat) → RevisionCount := revisionAux 0

/-! M4：保留空列上的首方向和折线上的独立端点。 -/

structure AltSeq where
  start : Dir
  body : List (Bar × (Nat × Nat))
  deriving DecidableEq

def AltSeq.mirror (pivot : Int) (a : AltSeq) : AltSeq :=
  ⟨a.start.flip, a.body.map fun (r, src) => (r.mirror pivot, src)⟩

def IsZigzag (alt : AltSeq) (ends : List (Int × Int)) : Prop :=
  ends.length = alt.body.length ∧
  (∀ p ∈ ends.zip alt.body, p.2.1.lo ≤ p.1.1 ∧ p.1.1 ≤ p.2.1.hi ∧
    p.2.1.lo ≤ p.1.2 ∧ p.1.2 ≤ p.2.1.hi) ∧
  (∀ p ∈ adjacent ends, p.1.2 = p.2.1)

instance (alt : AltSeq) (ends : List (Int × Int)) : Decidable (IsZigzag alt ends) := by
  unfold IsZigzag
  infer_instance

structure Zigzag where
  alt : AltSeq
  ends : List (Int × Int)
  valid : IsZigzag alt ends
  deriving DecidableEq

def Zigzag.toAltSeq (z : Zigzag) : AltSeq := z.alt

def laminar (blocks : List (Nat × Nat)) : Bool :=
  blocks.all fun a => blocks.all fun b =>
    decide (a.2 ≤ b.1 ∨ b.2 ≤ a.1 ∨ (b.1 ≤ a.1 ∧ a.2 ≤ b.2) ∨
      (a.1 ≤ b.1 ∧ b.2 ≤ a.2))

/-! M5：成核取三段公共交，延伸容许单点相触；事件的离开段按极值判定。 -/

structure Center where
  first : Nat
  count : Nat
  count_ge : 3 ≤ count
  core : Bar
  hull : Bar

def Center.stop (z : Center) : Nat := z.first + z.count

def Center.wellFormed (xs : List Seg) (z : Center) : Bool :=
  let cover := xs.extract z.first z.stop
  let seed := cover.take 3
  decide (cover.length = z.count ∧ z.hull.lo ≤ z.core.lo ∧ z.core.hi ≤ z.hull.hi) &&
    seed.all (fun s => decide (s.range.lo ≤ z.core.lo ∧ z.core.hi ≤ s.range.hi)) &&
    seed.any (fun s => decide (s.range.lo = z.core.lo)) &&
    seed.any (fun s => decide (s.range.hi = z.core.hi)) &&
    cover.all (fun s => decide (z.hull.lo ≤ s.range.lo ∧ s.range.hi ≤ z.hull.hi)) &&
    cover.any (fun s => decide (s.range.lo = z.hull.lo)) &&
    cover.any (fun s => decide (s.range.hi = z.hull.hi)) &&
    (cover.drop 3).all (fun s => s.range.overlaps z.core)

def seedAt (xs : List Seg) (i : Nat) : Bool :=
  match xs.drop i with
  | a :: b :: c :: _ => let r := seedBounds a b c; decide (r.lo ≤ r.hi)
  | _ => false

def coreRun (core : Bar) : List Seg → Nat
  | [] => 0
  | s :: ss => if s.range.overlaps core then coreRun core ss + 1 else 0

-- 调用点均已通过成核检查；ExtRun 自己检查种子。
def seedRunLen (xs : List Seg) (i : Nat) : Nat :=
  match xs.drop i with
  | a :: b :: c :: tail => 3 + coreRun (seedBounds a b c) tail
  | _ => 3

def Center.thirdBuyEvent (z : Center) (leave back : Seg) : Bool :=
  decide (leave.dir = .up ∧ z.core.hi < leave.range.hi ∧
    back.dir = .down ∧ z.core.hi < back.range.lo)

def Center.thirdSellEvent (z : Center) (leave back : Seg) : Bool :=
  decide (leave.dir = .down ∧ leave.range.lo < z.core.lo ∧
    back.dir = .up ∧ back.range.hi < z.core.lo)

def Center.destroyed (z : Center) (leave back : Seg) : Bool :=
  z.thirdBuyEvent leave back || z.thirdSellEvent leave back

def Center.thirdAt (z : Center) (side : Dir) (xs : List Seg) (k : Nat) : Bool :=
  match xs.drop k with
  | a :: b :: _ => match side with
    | .up => z.thirdBuyEvent a b
    | .down => z.thirdSellEvent a b
  | _ => false

/-! M6–M8：块内延伸计数、尾部单调性及两个原规则。 -/

abbrev Accepts := List Seg → Nat → Nat → Bool

def firstSeedFrom (xs : List Seg) (i : Nat) : Option Nat :=
  (List.range xs.length).find? fun k => decide (i ≤ k) && seedAt xs k

def extRun (block : List Seg) (k len : Nat) : Bool :=
  let run := block.extract k (k + len)
  decide (3 ≤ len ∧ run.length = len) && seedAt block k &&
    match run with
    | a :: b :: c :: tail => tail.all fun s => s.range.overlaps (seedBounds a b c)
    | _ => false

-- 全称 CarryBounded 的一个块；k 超出块长时 extRun 的长度检验恒不成立。
def carryBoundedAt (r : Accepts) (bound : Nat) (xs : List Seg) (i j : Nat) : Bool :=
  let block := xs.extract i j
  !r xs i j || (List.range (block.length + 1)).all (fun k => !extRun block k (bound + 1))

def tailStart (r : Accepts) (xs : List Seg) (i : Nat) : Bool :=
  (List.range (xs.length + 1)).all (fun j => !r xs i j)

-- DeterministicBlocks.tailExhaust 在一对起点上的实例。
def tailExhaustAt (r : Accepts) (xs : List Seg) (i i' : Nat) : Bool :=
  !tailStart r xs i || !decide (i ≤ i') || tailStart r xs i'

def sameLevelAccepts (xs : List Seg) (i j : Nat) : Bool :=
  decide (j = i + 3) && seedAt xs i

def brokenEnd (xs : List Seg) (s : Nat) : Option Nat :=
  let stop := s + seedRunLen xs s
  if stop < xs.length then some stop else none

def noCapAccepts (xs : List Seg) (i j : Nat) : Bool :=
  decide (((firstSeedFrom xs i).bind (brokenEnd xs)) = some j)

-- W10 只有一行切点，保留本层 CutsValid 与 ValidDecomp 的切点个数检查。
def validOneLevel (r : Accepts) (xs : List Seg) (marks : List Nat) : Bool :=
  decide (2 ≤ marks.length) && (adjacent marks).all (fun (i, j) => decide (i < j)) &&
  marks.all (fun j => decide (j ≤ xs.length)) && decide (marks.headD 0 = 0) &&
  (adjacent marks).all (fun (i, j) => r xs i j)

inductive CompletionTiming where | coreBroken | seeded
inductive RestartPolicy where | afterNine | atNextSeed
inductive SeedConvention where | mayIncludeFirst | requireEntry

structure CarryNineParams where
  timing : CompletionTiming
  restart : RestartPolicy
  seed : SeedConvention

def carryBlockEnd (p : CarryNineParams) (xs : List Seg) (i : Nat) : Option Nat := do
  let s ← firstSeedFrom xs (match p.seed with | .mayIncludeFirst => i | .requireEntry => i + 1)
  if 9 ≤ seedRunLen xs s then
    match p.restart with
    | .afterNine => some (s + 9)
    | .atNextSeed => firstSeedFrom xs (s + 9)
  else
    match p.timing with
    | .coreBroken => brokenEnd xs s
    | .seeded => some (s + 3)

def carryAccepts (p : CarryNineParams) (xs : List Seg) (i j : Nat) : Bool :=
  decide (carryBlockEnd p xs i = some j)

/-- 甲方 confirmedStable 的逐输入蕴含，不另区分普通块和已确认块。 -/
def confirmedStableAt (r : Accepts) (ctx ext : List Seg) (i j : Nat) : Bool :=
  !r ctx i j || r (ctx ++ ext) i j

/-! M9/M15：取指定层的段表作输入；走势类型在传入的中枢表上判定。 -/

inductive TrendKind where | consolidation | uptrend | downtrend
  deriving DecidableEq

def classifyTrend : List Center → Option TrendKind
  | [] => none
  | [_] => some .consolidation
  | a :: b :: rest =>
    let pairs := adjacent (a :: b :: rest)
    if pairs.all (fun (x,y) => decide (x.hull.hi < y.hull.lo)) then some .uptrend
    else if pairs.all (fun (x,y) => decide (y.hull.hi < x.hull.lo)) then some .downtrend
    else none

/-- 甲方前瞻：首枢的末覆盖段离开，后续不得回核，但不要求再创新高或新低。 -/
def trendFormingProspect (side : Dir) (xs : List Seg) (z : Center) (k : Nat) : Bool :=
  z.wellFormed xs && (List.range z.first).all (fun i => !seedAt xs i) &&
    decide (k + 1 = z.stop) && z.thirdAt side xs k &&
    (xs.drop (k + 2)).all (fun s => match side with
      | .up => decide (z.core.hi < s.range.lo)
      | .down => decide (s.range.hi < z.core.lo))

abbrev StrengthJudge := List Seg → Center → Nat → Nat → Bool

def firstPoint (side : Dir) (xs : List Seg) (judge : StrengthJudge)
    (prev : List Center) (z : Center) (i : Nat) : Bool :=
  let trend := match side with | .up => TrendKind.downtrend | .down => TrendKind.uptrend
  decide (classifyTrend (prev ++ [z]) = some trend) && z.wellFormed xs &&
    decide (z.stop ≤ i) &&
    (xs[i]?.any fun s => decide (s.dir = side.flip) &&
      match side with
      | .up => decide (s.range.lo < z.hull.lo)
      | .down => decide (z.hull.hi < s.range.hi)) &&
    judge xs z (z.first - 1) i

inductive Phase where | zhongYin | oscillation | leaving
  deriving DecidableEq

def phaseOf (xs : List Seg) (turn k : Nat) : Phase :=
  match firstSeedFrom xs (turn + 1) with
  | none => .zhongYin
  | some s =>
    if k < s + 2 then .zhongYin
    else if k < s + seedRunLen xs s then .oscillation
    else .leaving

def secondPoint (side : Dir) (xs : List Seg) (judge : StrengthJudge)
    (prev : List Center) (z : Center) (i : Nat) : Bool :=
  firstPoint side xs judge prev z i &&
    (xs[i+1]?.any fun s => decide (s.dir = side)) &&
    (xs[i+2]?.any fun s => decide (s.dir = side.flip)) &&
    decide (phaseOf xs i (i + 2) = .zhongYin)

inductive SecondStrength where | merged | rising | weak
  deriving DecidableEq

def secondStrength (side : Dir) (xs : List Seg) (z : Center) (i : Nat) : Option SecondStrength := do
  let first ← xs[i]?
  let second ← xs[i+2]?
  some <| match side with
  | .up => if z.core.hi < second.range.lo then .merged
    else if first.range.lo < second.range.lo then .rising else .weak
  | .down => if second.range.hi < z.core.lo then .merged
    else if second.range.hi < first.range.hi then .rising else .weak

-- 真三类点与类三类点均调用此式，不额外分流层级。
def thirdCore (side : Dir) (xs : List Seg) (z : Center) (k : Nat) : Bool :=
  z.wellFormed xs && decide (k + 1 = z.stop) &&
    (xs[k]?.any fun s => s.range.overlaps z.core) && z.thirdAt side xs k

def isOscillationBuy (xs : List Seg) (turn : Nat) (z : Center) (k : Nat) : Bool :=
  decide (phaseOf xs turn k = .oscillation) && z.wellFormed xs &&
    decide (z.first ≤ k ∧ k < z.stop) &&
    (xs[k]?.any fun s => decide (s.dir = .down ∧ s.range.lo ≤ z.core.lo))

end Opus

namespace Astra

/-! M2：只回读见证指定的稳定地址，被撤销和被改写都计一次。 -/

def revisionCount (h tail keys : List Nat) (_distinct : keys.Nodup) (level : Nat → Nat)
    (readAt : List Nat → Nat → Option Nat) : Nat × Option Nat :=
  let changed := keys.filter fun k =>
    (readAt h k).isSome && decide (readAt h k ≠ readAt (h ++ tail) k)
  (changed.length, (changed.map level).max?)

/-! M4：只存交替段表；折线端点从段极值导出。 -/

structure AltSeq where
  items : List Seg
  alternating : Fm10c.alternating items
  deriving DecidableEq

def AltSeq.mirror (pivot : Int) (s : AltSeq) : Option AltSeq :=
  let items := s.items.map (Seg.mirror pivot)
  if h : Fm10c.alternating items then some ⟨items, h⟩ else none

def ExtremalJoints (a : AltSeq) : Prop :=
  ∀ p ∈ adjacent a.items, p.1.exit = p.2.entry

instance (a : AltSeq) : Decidable (ExtremalJoints a) := by
  unfold ExtremalJoints
  infer_instance

abbrev Zigzag := { xs : AltSeq // ExtremalJoints xs }

def Zigzag.toAltSeq (z : Zigzag) : AltSeq := z.val

def laminar (blocks : List (Nat × Nat)) : Bool :=
  blocks.all (fun b => decide (b.1 < b.2)) &&
    decide (blocks.Pairwise fun a b =>
      a.2 ≤ b.1 ∨ b.2 ≤ a.1 ∨ (a.1 ≤ b.1 ∧ b.2 ≤ a.2) ∨ (b.1 ≤ a.1 ∧ a.2 ≤ b.2))

/-! M5：window? 保留全段交替、三段成核、延伸与真实覆盖检查。 -/

structure Center where
  start : Nat
  a : Seg
  b : Seg
  c : Seg
  more : List Seg
  deriving DecidableEq

def Center.cover (z : Center) : List Seg := z.a :: z.b :: z.c :: z.more

def Center.stop (z : Center) : Nat := z.start + z.cover.length

def Center.core (z : Center) : Bar := seedBounds z.a z.b z.c

def Center.hull (z : Center) : Bar := rangeHull z.a (z.b :: z.c :: z.more)

def Center.window? (xs : List Seg) (i j : Nat) : Option Center :=
  if j > xs.length then none else
    match xs.extract i j with
    | a :: b :: c :: more =>
      let core := seedBounds a b c
      if alternating (a :: b :: c :: more) && decide (core.lo ≤ core.hi) &&
          more.all (fun s => core.overlaps s.range)
      then some ⟨i, a, b, c, more⟩ else none
    | _ => none

def Center.actual (xs : List Seg) (z : Center) : Bool :=
  decide (Center.window? xs z.start z.stop = some z)

def Center.thirdEvent (z : Center) (side : Dir) (xs : List Seg) : Bool :=
  decide (xs.extract z.start z.stop = z.cover) &&
    match xs[z.stop]?, xs[z.stop+1]? with
    | some a, some b => decide (a.dir = side ∧ b.dir = side.flip) &&
      match side with
      | .up => decide (z.core.hi < a.range.lo ∧ z.core.hi < b.range.lo)
      | .down => decide (a.range.hi < z.core.lo ∧ b.range.hi < z.core.lo)
    | _, _ => false

def Center.destroyed (z : Center) (xs : List Seg) : Bool :=
  z.thirdEvent .up xs || z.thirdEvent .down xs

def windows (xs : List Seg) : List Center :=
  (List.range xs.length).flatMap fun i =>
    (List.range (xs.length + 1)).filterMap (Center.window? xs i)

/-! M6：块语言按 rank 接受，粗化方向取首段，成塔还需交替。 -/

abbrev Rank := Nat → List Seg → List Nat → Nat → Nat → Option Nat

abbrev Confirmed := Nat → List Seg → List Nat → Nat → Nat → Bool

def coarsen (xs : List Seg) (i j : Nat) : Option Seg :=
  if j > xs.length then none else
    match xs.extract i j with
    | [] => none
    | a :: tail =>
      let span := tail.foldl (fun (x : Nat × Nat) s =>
        (min x.1 s.source.1, max x.2 s.source.2)) a.source
      some ⟨a.dir, rangeHull a tail, span⟩

def ends (r : Rank) (k : Nat) (xs : List Seg) (past : List Nat) (i : Nat) :
    List (Nat × Nat) :=
  (List.range (xs.length + 1)).filterMap fun j =>
    if i < j then (r k xs past i j).map (fun score => (j, score)) else none

def preferred (r : Rank) (k : Nat) (xs : List Seg) (past : List Nat) (i j : Nat) : Bool :=
  match r k xs past i j with
  | none => false
  | some score => decide (i < j ∧ j ≤ xs.length) &&
      (ends r k xs past i).all (fun q => decide (q.2 ≤ score))

/-- 乙方 InterfaceLaws 的稳定子句；保留合法、占优、改分与确认状态的全部判定。 -/
def stableAt (r : Rank) (confirmed : Confirmed) (k : Nat) (s t : AltSeq)
    (past : List Nat) (i j : Nat) : Bool :=
  let score := r k s.items past i j
  !confirmed k s.items past i j || !(s.items.isPrefixOf t.items) ||
    (score.isSome && preferred r k s.items past i j &&
      decide (r k t.items past i j = score) && preferred r k t.items past i j &&
      confirmed k t.items past i j)

def carryBounded (r : Rank) (bound k : Nat) (xs : List Seg) (past : List Nat) (i : Nat) :
    Bool :=
  (ends r k xs past i).all (fun q => decide (i + 3 ≤ q.1 ∧ q.1 ≤ i + bound))

def deterministicBlocks (r : Rank) (k : Nat) (xs : List Seg) (marks : List Nat) : Bool :=
  decide (marks.head? = some 0) && marks.zipIdx.all fun (i, n) =>
    let past := (marks.take n).reverse
    let es := ends r k xs past i
    match marks[n+1]? with
    | some j => decide ((es.filter fun q => preferred r k xs past i q.1).map Prod.fst = [j])
    | none => es.isEmpty

def sameLevelRank (atDepth : Nat) : Rank :=
  fun k xs _ i j =>
    if k == atDepth && j == i + 3 && (Center.window? xs i j).isSome then some 0 else none

structure Stage where
  seq : AltSeq
  raw : List Nat

def Stage.bottom (s : AltSeq) : Stage := ⟨s, List.range (s.items.length + 1)⟩

def Stage.ascend (s : Stage) (raw : List Nat) : Option (List Nat × Stage) := do
  if raw.length < 2 || !(raw.all (fun j => s.raw.contains j)) then none else
    let localCuts := raw.map (fun j => s.raw.idxOf j)
    let blocks ← (adjacent localCuts).mapM fun (i, j) => coarsen s.seq.items i j
    if h : alternating blocks then some (localCuts, ⟨⟨blocks, h⟩, raw⟩) else none

/-- 单行、深度零的 ValidDecomp：先还原实际几何，再逐块检查 rank，切点用原坐标。 -/
def validOneLevel (r : Rank) (s : Stage) (raw : List Nat) : Bool :=
  (s.ascend raw).any fun (cuts, _) =>
    (adjacent cuts).zipIdx.all fun ((i,j), n) =>
      (r 0 s.seq.items (cuts.take n).reverse i j).isSome

/-! M7：固定种子、三凸包公交和离开回拉，按进位类别及优先级打分。 -/

structure CarryNineParams where
  finishAtSeed : Bool
  entryAfterCarry : Bool
  separateEntry : Bool

def nineAt (xs : List Seg) (i : Nat) : Bool :=
  (Center.window? xs i (i + 9)).isSome &&
    match coarsen xs i (i+3), coarsen xs (i+3) (i+6), coarsen xs (i+6) (i+9) with
    | some a, some b, some c => let r := seedBounds a b c; decide (r.lo ≤ r.hi)
    | _, _, _ => false

def returningCenter (xs : List Seg) (z : Center) (j : Nat) (requireThird : Bool) : Bool :=
  match xs[z.stop]? with
  | none => false
  | some leave =>
    let left := match leave.dir with
      | .up => decide (z.core.hi < leave.range.lo)
      | .down => decide (leave.range.hi < z.core.lo)
    let candidates := (List.range (xs.length - z.stop)).map (fun n => z.stop + 1 + n)
    left && (!requireThird || z.destroyed xs) &&
      match candidates.find? (fun n => (Center.window? xs n (n + 3)).isSome) with
      | none => false
      | some n => (Center.window? xs n j).any fun next => z.hull.overlaps next.hull

def carryClass (p : CarryNineParams) (xs : List Seg) (past : List Nat) (i j : Nat) : Option Nat :=
  let afterNine := match past with
    | [] => false
    | prev :: _ => decide (prev + 9 ≤ i ∧ i ≤ prev + 10) && nineAt xs (i - 9)
  let seed := i + (if p.separateEntry || (p.entryAfterCarry && afterNine) then 1 else 0)
  if j > xs.length || j < seed + 3 then none else
    let nine := j == seed + 9 && nineAt xs seed
    let pullback := (List.range (min 9 (j - seed))).any fun n =>
      (Center.window? xs seed (seed + n)).any fun z => returningCenter xs z j true
    if nine || pullback then some 1
    else if p.finishAtSeed then
      if j == seed + 3 && (Center.window? xs seed j).isSome then some 0 else none
    else if j ≤ seed + 8 then
      if (Center.window? xs seed j).any (fun z => z.destroyed xs) then some 0 else none
    else none

def carryScore (p : CarryNineParams) (xs : List Seg) (past : List Nat) (i j : Nat) : Option Nat :=
  match carryClass p xs past i j with
  | some 1 =>
    some (if (List.range j).any (fun t => decide (carryClass p xs past i t = some 1))
      then 1 else 2)
  | other => other

def carryConfirmed (p : CarryNineParams) (xs : List Seg) (past : List Nat) (i j : Nat) : Bool :=
  decide (carryScore p xs past i j = some 2)

/-! M9/M15：原有认证账本、端点观测与按 cut 查询的阶段门。 -/

inductive TrendKind where | consolidation | uptrend | downtrend
  deriving DecidableEq

structure FinishedBlock where
  first : Nat
  stop : Nat
  centers : List Center

def canSeedCenter (xs : List Seg) (i : Nat) : Bool :=
  match xs[i]?, xs[i+1]?, xs[i+2]? with
  | some a, some b, some c => let r := seedBounds a b c; decide (r.lo ≤ r.hi)
  | _, _, _ => false

def FinishedBlock.certified (b : FinishedBlock) (xs : List Seg) : Bool :=
  decide (b.first < b.stop ∧ b.stop ≤ xs.length) &&
    b.centers.all (fun z => decide (b.first ≤ z.start ∧ z.stop ≤ b.stop) && z.actual xs) &&
    decide (b.centers.Pairwise (fun a z => a.stop ≤ z.start)) &&
    (List.range b.stop).all (fun i =>
      !(decide (b.first ≤ i ∧ i + 3 ≤ b.stop) && canSeedCenter xs i) ||
      b.centers.any (fun z => decide (i < z.stop ∧ z.start < i + 3)))

def classifyTrend (b : FinishedBlock) : Option TrendKind :=
  match b.centers with
  | [] => none
  | [_] => some .consolidation
  | _ :: _ :: _ =>
    let pairs := adjacent b.centers
    if pairs.all (fun (a,z) => decide (a.hull.hi < z.hull.lo)) then some .uptrend
    else if pairs.all (fun (a,z) => decide (z.hull.hi < a.hull.lo)) then some .downtrend
    else none

/-- 乙方前瞻：只收一个前枢；跳空离开后不得回核，且必须顺向越过离开段极值。 -/
def trendFormingProspect (s : AltSeq) (centers : List Center) (side : Dir) (atCut : Nat) : Bool :=
  match centers with
  | [z] =>
    let follow := s.items.extract (z.stop + 2) atCut
    z.thirdEvent side s.items && decide (atCut ≤ s.items.length) &&
      (follow.all fun x => match side with
        | .up => decide (z.core.hi < x.range.lo)
        | .down => decide (x.range.hi < z.core.lo)) &&
      match s.items[z.stop]? with
      | none => false
      | some leave => follow.any fun x => decide (x.dir = side) &&
          match side with
          | .up => decide (leave.range.hi < x.range.hi)
          | .down => decide (x.range.lo < leave.range.lo)
  | _ => false

structure DecompData where
  depth : Nat
  rule : Rank
  steps : AltSeq
  prices : List (Int × Int)
  cuts : List Nat
  completed : List FinishedBlock
  centers : List Center
  origin : Nat

def DecompData.certified (d : DecompData) : Bool :=
  let xs := d.steps.items
  decide (d.prices.length = xs.length) &&
    (xs.zip d.prices).all (fun (s, a, b) =>
      decide (s.range.lo ≤ a ∧ a ≤ s.range.hi ∧ s.range.lo ≤ b ∧ b ≤ s.range.hi) &&
      match s.dir with
      | .up => decide (a ≤ b)
      | .down => decide (b ≤ a)) &&
    decide (d.cuts.head? = some 0 ∧ d.cuts.Pairwise (· < ·)) &&
    d.cuts.all (fun j => decide (j ≤ xs.length)) &&
    (adjacent d.cuts).zipIdx.all (fun ((i,j), n) =>
      (d.rule (d.depth - 1) xs (d.cuts.take n).reverse i j).isSome) &&
    d.completed.all (fun b => b.certified xs) &&
    decide (d.completed.map (fun b => (b.first, b.stop)) = adjacent d.cuts) &&
    decide (d.centers.Pairwise (fun a b => a.stop ≤ b.start)) &&
    d.centers.all (fun z => z.actual xs &&
      d.cuts.all (fun j => decide (j ≤ z.start ∨ z.stop ≤ j))) &&
    d.completed.all (fun b =>
      decide (d.centers.filter (fun z => decide (b.first ≤ z.start ∧ z.stop ≤ b.stop)) =
        b.centers)) &&
    (d.origin == 0 || d.completed.any (fun b => decide (b.stop = d.origin ∧
      (classifyTrend b = some .downtrend ∨ classifyTrend b = some .uptrend))))

abbrev Decomposition := { d : DecompData // d.certified = true }

inductive Phase where | transition | oscillation | departure
  deriving DecidableEq

def recent (d : Decomposition) (since cut : Nat) : Option Center :=
  (d.val.centers.filter fun z => decide (since ≤ z.start ∧ z.start + 3 ≤ cut)).getLast?

def phaseAt (d : Decomposition) (cut : Nat) : Option Phase :=
  let xs := d.val.steps.items
  if cut < d.val.origin || xs.length < cut then none else
    match recent d d.val.origin cut with
    | none => some .transition
    | some z =>
      if cut ≤ z.stop then some .oscillation
      else match xs[cut-1]?, d.val.prices[cut-1]? with
        | some s, some (a,b) =>
          let cross := match s.dir with
            | .up => decide (a ≤ z.core.hi ∧ z.core.hi < b)
            | .down => decide (z.core.lo ≤ a ∧ b < z.core.lo)
          if cross || !z.core.overlaps s.range then some .departure else some .oscillation
        | _, _ => none

abbrev StrengthJudge := Decomposition → Center → Seg → Seg → Bool

def ahead (side : Dir) (x y : Int) : Bool :=
  match side with | .up => decide (y < x) | .down => decide (x < y)

def edge (side : Dir) (b : Bar) : Int :=
  match side with | .up => b.hi | .down => b.lo

def breakoutRetest (d : Decomposition) (side : Dir) (zone : Bar) (cut : Nat) : Bool :=
  let xs := d.val.steps.items
  if cut < 2 then false else
    match xs[cut-2]?, xs[cut-1]?, d.val.prices[cut-2]? with
    | some leave, some test, some (a,b) =>
      let limit := edge side zone
      decide (leave.dir = side ∧ test.dir = side.flip) &&
        !ahead side a limit && ahead side b limit && ahead side (edge side.flip test.range) limit
    | _, _, _ => false

def firstPoint (d : Decomposition) (judge : StrengthJudge) (side : Dir) (cut : Nat) : Bool :=
  let trend := match side with | .up => TrendKind.downtrend | .down => TrendKind.uptrend
  let xs := d.val.steps.items
  decide (cut = d.val.origin ∧ phaseAt d cut = some .transition) &&
    d.val.completed.any fun b => decide (b.stop = cut ∧ classifyTrend b = some trend) &&
      match b.centers.getLast?, xs[cut-1]?, d.val.prices[cut-1]? with
      | some z, some c, some (_,lastPrice) =>
        decide (z.stop < cut ∧ c.dir = side.flip) &&
          ahead side.flip lastPrice (edge side.flip z.core) &&
          (xs.extract b.first z.start).any fun prior =>
            decide (prior.dir = c.dir) && judge d z prior c
      | _, _, _ => false

def thirdGeometry (d : Decomposition) (side : Dir) (cut : Nat) : Bool :=
  let xs := d.val.steps.items
  if cut < 2 then false else
    let i := cut - 2
    match recent d 0 cut, d.val.prices[i]? with
    | some z, some (entry,_) =>
      decide (z.start + 3 ≤ i) &&
        match Center.window? xs z.start (min z.stop i) with
        | some earlier => decide (earlier.hull.lo ≤ entry ∧ entry ≤ earlier.hull.hi) &&
            (decide (i ≤ z.stop) || xs[i-1]?.any (fun s => z.core.overlaps s.range)) &&
            breakoutRetest d side z.core cut
        | none => false
    | _, _ => false

inductive SecondStrength where | strongest | intermediate | weak
  deriving DecidableEq

def secondStrength? (d : Decomposition) (judge : StrengthJudge) (side : Dir) (cut : Nat) :
    Option SecondStrength := do
  if cut < 3 || !firstPoint d judge side (cut - 2) ||
      !decide (phaseAt d cut = some .transition) then none else
    let xs := d.val.steps.items
    let rebound ← xs[cut-2]?
    let test ← xs[cut-1]?
    let (_,firstPrice) ← d.val.prices[cut-3]?
    let (_,secondPrice) ← d.val.prices[cut-1]?
    let z ← recent d 0 (cut - 2)
    if rebound.dir != side || test.dir != side.flip then none
    else if thirdGeometry d side cut || !ahead side (edge side z.core) (edge side.flip test.range)
      then some .strongest
    else if ahead side secondPrice firstPrice then some .intermediate
    else some .weak

def thirdPoint (d : Decomposition) (side : Dir) (cut : Nat) : Bool :=
  thirdGeometry d side cut && decide (phaseAt d (cut - 2) = some .oscillation ∧
    phaseAt d cut = some .departure)

def isThirdBuy (d : Decomposition) (cut : Nat) : Bool :=
  decide (0 < d.val.depth) && thirdPoint d .up cut

def isPseudoThirdBuy (d : Decomposition) (cut : Nat) : Bool :=
  decide (d.val.depth = 0) && thirdPoint d .up cut

def isThirdSell (d : Decomposition) (cut : Nat) : Bool :=
  decide (0 < d.val.depth) && thirdPoint d .down cut

def isPseudoThirdSell (d : Decomposition) (cut : Nat) : Bool :=
  decide (d.val.depth = 0) && thirdPoint d .down cut

def oscillationPoint (d : Decomposition) (side : Dir) (cut : Nat) : Bool :=
  let xs := d.val.steps.items
  decide (0 < cut ∧ phaseAt d cut = some .oscillation) &&
    match recent d d.val.origin cut, xs[cut-1]?, xs[cut]?,
          d.val.prices[cut-1]?, d.val.prices[cut]? with
    | some z, some a, some b, some (_,p), some (q,_) =>
      decide (a.dir = side.flip ∧ b.dir = side ∧ p = q) &&
        z.core.overlaps a.range && !ahead side p (edge side.flip z.core)
    | _, _, _, _, _ => false

end Astra

/-! ## W1、W4、W5、W7：稳定地址、空列、折线、半开块 -/

def readRevision (history : List Nat) (key : Nat) : Option Nat :=
  match key with
  | 0 => if history.contains 2 then none else some 10
  | 1 => some 20
  | _ => none

theorem w1_revision_count :
    Opus.measure [[10,20]] [[20]] = ⟨2,1⟩ ∧
    (Opus.measure [[10,20]] [[20]]).rewritten ≠ 1 ∧
    Astra.revisionCount [0,1] [2] [0,1] (by decide) (fun _ => 0) readRevision = (1,some 0) := by
  decide

def opusEmpty (d : Dir) : Opus.AltSeq := ⟨d, []⟩

def astraEmpty : Astra.AltSeq := ⟨[], by decide⟩

theorem w4_empty_direction :
    (opusEmpty .up).body = (opusEmpty .down).body ∧ opusEmpty .up ≠ opusEmpty .down ∧
    (opusEmpty .up).mirror 0 = opusEmpty .down ∧ astraEmpty.mirror 0 = some astraEmpty := by
  decide

theorem w4_astra_empty_unique (x : Astra.AltSeq) (h : x.items = []) : x = astraEmpty := by
  cases x with
  | mk items proof =>
    cases h
    rfl

def zigPair : List Seg := segments [(.up,0,10), (.down,2,8)]

def opusAlt (d : Dir) (xs : List Seg) : Opus.AltSeq :=
  ⟨d, xs.map fun s => (s.range, s.source)⟩

theorem w5a_non_extremal_joint :
    Opus.IsZigzag (opusAlt .up zigPair) [(0,6),(6,2)] ∧
    ¬Astra.ExtremalJoints ⟨zigPair, by decide⟩ := by
  decide

def zigSingle : List Seg := segments [(.up,0,10)]

def opusReversed : Opus.Zigzag := ⟨opusAlt .up zigSingle, [(9,1)], by decide⟩

def opusExtremal : Opus.Zigzag := ⟨opusAlt .up zigSingle, [(0,10)], by decide⟩

def astraExtremal : Astra.Zigzag := ⟨⟨zigSingle, by decide⟩, by decide⟩

theorem w5b_opus_two_lifts :
    opusReversed ≠ opusExtremal ∧ opusReversed.toAltSeq = opusExtremal.toAltSeq := by
  decide

theorem w5b_astra_unique_lift (z : Astra.Zigzag)
    (h : z.toAltSeq = astraExtremal.toAltSeq) : z = astraExtremal :=
  Subtype.ext h

theorem w7_empty_and_reversed_blocks :
    Opus.laminar [(3,3)] = true ∧ Astra.laminar [(3,3)] = false ∧
    Opus.laminar [(1,4),(3,2)] = true ∧ Astra.laminar [(1,4),(3,2)] = false := by
  decide

/-! ## W8：相交的离开段不需要整段脱核 -/

def w8aSteps : List Seg :=
  segments [(.down,10,20), (.up,10,20), (.down,10,20), (.up,10,30), (.down,25,30)]

def w8bSteps : List Seg :=
  segments [(.up,10,20), (.down,10,20), (.up,10,20), (.down,5,20), (.up,5,8)]

def threeSeed : Opus.Center := ⟨0, 3, by decide, ⟨10,20⟩, ⟨10,20⟩⟩

theorem w8a_continuous_buy :
    threeSeed.wellFormed w8aSteps = true ∧
    threeSeed.thirdBuyEvent w8aSteps[3] w8aSteps[4] = true ∧
    threeSeed.destroyed w8aSteps[3] w8aSteps[4] = true ∧
    (Astra.Center.window? w8aSteps 0 3).isSome = true ∧
    (Astra.windows w8aSteps).any (fun z => z.thirdEvent .up w8aSteps) = false ∧
    (Astra.windows w8aSteps).any (fun z => z.destroyed w8aSteps) = false := by
  decide

/--
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。
此处固定为 `d1 = 10 > 8 = g2`，并取已完成三段的核作为离开前中枢。
-/
theorem w8b_continuous_sell :
    threeSeed.wellFormed w8bSteps = true ∧
    threeSeed.thirdSellEvent w8bSteps[3] w8bSteps[4] = true ∧
    threeSeed.destroyed w8bSteps[3] w8bSteps[4] = true ∧
    (Astra.Center.window? w8bSteps 0 3).isSome = true ∧
    (Astra.windows w8bSteps).any (fun z => z.thirdEvent .down w8bSteps) = false ∧
    (Astra.windows w8bSteps).any (fun z => z.destroyed w8bSteps) = false := by
  decide

/-! ## W9、W10、W11：规则与成塔 -/

def opusCarry : Opus.CarryNineParams := ⟨.coreBroken, .afterNine, .mayIncludeFirst⟩

def astraCarry : Astra.CarryNineParams := ⟨false, false, false⟩

def opusSeeded : Opus.CarryNineParams := { opusCarry with timing := .seeded }

def astraSeeded : Astra.CarryNineParams := { astraCarry with finishAtSeed := true }

def astraSeededRank : Astra.Rank :=
  fun _ xs past i j => Astra.carryScore astraSeeded xs past i j

def astraSeededConfirmed : Astra.Confirmed :=
  fun _ xs past i j => Astra.carryConfirmed astraSeeded xs past i j

def w9bNine : List Seg :=
  segments [(.up,10,20), (.down,10,20), (.up,10,20), (.down,10,20), (.up,10,20),
    (.down,10,20), (.up,10,20), (.down,10,20), (.up,10,20)]

def w9bPrefix : List Seg := w9bNine.take 3

def w9bExtension : List Seg := w9bNine.drop 3

def w9bBase : Astra.AltSeq := ⟨w9bNine, by decide⟩

def w9bShort : Astra.AltSeq := ⟨w9bPrefix, by decide⟩

theorem w9b_seeded_prefix_stability :
    w9bPrefix ++ w9bExtension = w9bNine ∧
    Opus.carryAccepts opusSeeded w9bPrefix 0 3 = true ∧
    Opus.carryAccepts opusSeeded w9bNine 0 3 = false ∧
    Opus.carryAccepts opusSeeded w9bNine 0 9 = true ∧
    Opus.confirmedStableAt (Opus.carryAccepts opusSeeded) w9bPrefix w9bExtension 0 3 = false ∧
    astraSeededRank 0 w9bPrefix [] 0 3 = some 0 ∧
    astraSeededConfirmed 0 w9bPrefix [] 0 3 = false ∧
    Astra.stableAt astraSeededRank astraSeededConfirmed 0 w9bShort w9bBase [] 0 3 = true := by
  decide

def w9cSteps : List Seg :=
  segments [(.down,0,5), (.up,10,20), (.down,10,20), (.up,10,20), (.down,10,20),
    (.up,10,20), (.down,10,20), (.up,10,20), (.down,10,20), (.up,10,20)]

/-- 乙方选独立进入段，使两规则均合法接受相同的十段块。 -/
def w9cRank : Astra.Rank :=
  fun _ xs past i j => Astra.carryScore { astraCarry with separateEntry := true } xs past i j

theorem w9c_extension_count_not_block_length :
    Opus.carryAccepts opusCarry w9cSteps 0 10 = true ∧
    w9cRank 0 w9cSteps [] 0 10 = some 2 ∧
    Opus.extRun w9cSteps 1 9 = true ∧
    Opus.carryBoundedAt (Opus.carryAccepts opusCarry) 9 w9cSteps 0 10 = true ∧
    Astra.carryBounded w9cRank 9 0 w9cSteps [] 0 = false := by
  decide

def w9dSteps : List Seg :=
  segments [(.up,0,1), (.down,10,20), (.up,10,20), (.down,10,20)]

theorem w9d_later_seed_breaks_tail_monotonicity :
    Opus.tailStart Opus.sameLevelAccepts w9dSteps 0 = true ∧
    Opus.tailStart Opus.sameLevelAccepts w9dSteps 1 = false ∧
    Opus.tailExhaustAt Opus.sameLevelAccepts w9dSteps 0 1 = false ∧
    Astra.deterministicBlocks (Astra.sameLevelRank 0) 0 w9dSteps [0] = true := by
  decide

theorem w9d_refutes_opus_tail_exhaust :
    ¬(∀ (xs : List Seg) (i i' : Nat),
        Opus.tailStart Opus.sameLevelAccepts xs i = true → i ≤ i' →
        Opus.tailStart Opus.sameLevelAccepts xs i' = true) := by
  intro law
  have h := law w9dSteps 0 1 (by decide) (by decide)
  exact (by decide : Opus.tailStart Opus.sameLevelAccepts w9dSteps 1 ≠ true) h

def w10aSteps : List Seg :=
  segments [(.up,10,20), (.down,10,20), (.up,10,20), (.down,10,20),
    (.up,30,40), (.down,30,40), (.up,30,40), (.down,50,60)]

def w10aBottom : Astra.Stage := Astra.Stage.bottom ⟨w10aSteps, by decide⟩

theorem w10a_even_block_before_another :
    Opus.validOneLevel Opus.noCapAccepts w10aSteps [0,4,7] = true ∧
    (Astra.coarsen w10aSteps 0 4).map Seg.dir = some .up ∧
    (Astra.coarsen w10aSteps 4 7).map Seg.dir = some .up ∧
    (w10aBottom.ascend [0,4,7]).isSome = false := by
  decide

theorem w10b_legal_nonpreferred_seed_split :
    Opus.validOneLevel (Opus.carryAccepts opusSeeded) w9bNine [0,3,6,9] = false ∧
    Opus.validOneLevel (Opus.carryAccepts opusSeeded) w9bNine [0,9] = true ∧
    Astra.validOneLevel astraSeededRank (Astra.Stage.bottom w9bBase) [0,3,6,9] = true ∧
    Astra.validOneLevel astraSeededRank (Astra.Stage.bottom w9bBase) [0,9] = true ∧
    astraSeededRank 0 w9bNine [] 0 3 = some 0 ∧
    Astra.preferred astraSeededRank 0 w9bNine [] 0 3 = false := by
  decide

def w11aSteps : List Seg :=
  segments [(.up,10,20), (.down,10,20), (.up,10,20), (.down,0,10), (.up,0,10),
    (.down,0,10), (.up,20,30), (.down,20,30), (.up,20,30)]

theorem w11a_nine_with_disjoint_hulls :
    Opus.seedRunLen w11aSteps 0 = 9 ∧ (Astra.Center.window? w11aSteps 0 9).isSome = true ∧
    Opus.carryAccepts opusCarry w11aSteps 0 9 = true ∧ Astra.nineAt w11aSteps 0 = false ∧
    Astra.carryScore astraCarry w11aSteps [] 0 9 = none := by
  decide

def w11bSteps : List Seg :=
  segments [(.up,0,5), (.down,10,20), (.up,10,20), (.down,10,20), (.up,25,30), (.down,26,30)]

theorem w11b_non_seed_lead :
    Opus.firstSeedFrom w11bSteps 0 = some 1 ∧
    Opus.carryAccepts opusCarry w11bSteps 0 4 = true ∧
    Astra.carryScore astraCarry w11bSteps [] 0 4 = none ∧
    (List.range (w11bSteps.length + 1)).all
      (fun j => (Astra.carryScore astraCarry w11bSteps [] 0 j).isNone) = true := by
  decide

def w11cSteps : List Seg :=
  segments [(.up,10,20), (.down,10,20), (.up,10,20), (.down,0,5)]

theorem w11c_core_break_without_retest :
    Opus.carryAccepts opusCarry w11cSteps 0 3 = true ∧
    (Astra.Center.window? w11cSteps 0 3).isSome = true ∧
    Astra.carryScore astraCarry w11cSteps [] 0 3 = none := by
  decide

def w11dSteps : List Seg :=
  segments [(.down,0,20), (.up,10,20), (.down,10,20), (.up,25,35), (.down,22,35),
    (.up,18,30), (.down,18,30)]

theorem w11d_gap_pullback_upgrades :
    Opus.carryAccepts opusCarry w11dSteps 0 3 = true ∧
    Opus.carryAccepts opusCarry w11dSteps 0 7 = false ∧
    (Astra.Center.window? w11dSteps 0 3).any (fun z =>
      Astra.returningCenter w11dSteps z 7 true) = true ∧
    Astra.carryScore astraCarry w11dSteps [] 0 7 = some 2 := by
  decide

/-! ## W14：连续离开、跳空离开与顺向推进 -/

def w14aSeq (high : Int) : List Seg :=
  segments [(.down,10,20), (.up,10,20), (.down,10,20), (.up,10,30), (.down,22,30),
    (.up,22,high)]

def w14aAlt : Astra.AltSeq := ⟨w14aSeq 40, by decide⟩

def w14aCover : Opus.Center := ⟨0,4,by decide,⟨10,20⟩,⟨10,30⟩⟩

theorem w14a_continuous_leave :
    Opus.trendFormingProspect .up (w14aSeq 40) w14aCover 3 = true ∧
    Opus.trendFormingProspect .up (w14aSeq 29) w14aCover 3 = true ∧
    (∀ z ∈ Astra.windows w14aAlt.items, Astra.trendFormingProspect w14aAlt [z] .up 6 = false) := by
  decide

def w14bSeq (high : Int) : List Seg :=
  segments [(.down,10,20), (.up,10,20), (.down,10,20), (.up,25,30), (.down,26,30),
    (.up,26,high)]

theorem w14b_gap_leave_requires_progress :
    threeSeed.wellFormed (w14bSeq 40) = true ∧
    Opus.trendFormingProspect .up (w14bSeq 40) threeSeed 2 = false ∧
    Astra.trendFormingProspect ⟨w14bSeq 40, by decide⟩
      ((Astra.Center.window? (w14bSeq 40) 0 3).toList) .up 6 = true ∧
    Astra.trendFormingProspect ⟨w14bSeq 29, by decide⟩
      ((Astra.Center.window? (w14bSeq 29) 0 3).toList) .up 6 = false := by
  decide

/-! ## W17–W19：认证转折、触核等号、第 3 段兼离开 -/

def trendSteps (cLow reboundHigh backLow : Int) : List Seg :=
  segments [(.up,40,50), (.down,40,50), (.up,40,50), (.down,20,40),
    (.up,10,25), (.down,5,20), (.up,10,20), (.down,cLow,20),
    (.up,cLow,reboundHigh), (.down,backLow,reboundHigh)]

def trendA : Opus.Center := ⟨0, 3, by decide, ⟨40,50⟩, ⟨40,50⟩⟩

def trendB : Opus.Center := ⟨4, 3, by decide, ⟨10,20⟩, ⟨5,25⟩⟩

def Opus.Center.mirror (z : Opus.Center) (pivot : Int) : Opus.Center :=
  ⟨z.first, z.count, z.count_ge, z.core.mirror pivot, z.hull.mirror pivot⟩

/-- 完成块 `[0,8)` 的合法性由见证专用的块规则提供，两核必须通过乙方账本校验。 -/
def trendData (steps : Astra.AltSeq) : Astra.DecompData :=
  let centers := [0,4].flatMap fun i => (Astra.Center.window? steps.items i (i + 3)).toList
  ⟨1, (fun _ _ _ i j => if i = 0 ∧ j = 8 then some 0 else none),
    steps, steps.items.map (fun s => (s.entry,s.exit)), [0,8], [⟨0,8,centers⟩], centers, 8⟩

def w17aSteps : List Seg := trendSteps 8 15 11

def w17aMirror : List Seg := w17aSteps.map (Seg.mirror 60)

def w17aBuy : Astra.Decomposition := ⟨trendData ⟨w17aSteps, by decide⟩, by decide⟩

def w17aSell : Astra.Decomposition := ⟨trendData ⟨w17aMirror, by decide⟩, by decide⟩

def opusTrivialStrength : Opus.StrengthJudge := fun _ _ _ _ => true

def astraTrivialStrength : Astra.StrengthJudge := fun _ _ _ _ => true

theorem w17a_core_vs_hull_buy :
    Opus.firstPoint .up w17aSteps opusTrivialStrength [trendA] trendB 7 = false ∧
    Astra.firstPoint w17aBuy astraTrivialStrength .up 8 = true ∧
    Opus.secondPoint .up w17aSteps opusTrivialStrength [trendA] trendB 7 = false ∧
    (Astra.secondStrength? w17aBuy astraTrivialStrength .up 10).isSome = true := by
  decide

theorem w17a_core_vs_hull_sell :
    Opus.firstPoint .down w17aMirror opusTrivialStrength [trendA.mirror 60]
      (trendB.mirror 60) 7 = false ∧
    Astra.firstPoint w17aSell astraTrivialStrength .down 8 = true ∧
    Opus.secondPoint .down w17aMirror opusTrivialStrength [trendA.mirror 60]
      (trendB.mirror 60) 7 = false ∧
    (Astra.secondStrength? w17aSell astraTrivialStrength .down 10).isSome = true := by
  decide

def w17bSingle : List Seg :=
  segments [(.up,10,20), (.down,10,20), (.up,10,20), (.down,2,15)]

def w17bFakePrev : Opus.Center := ⟨99,3,by decide,⟨50,60⟩,⟨50,60⟩⟩

def w17bUnderflowJudge : Opus.StrengthJudge := fun xs _ prior exit =>
  decide (prior = 0 ∧ exit = 3) &&
    (xs[prior]?.any fun s => s.dir == .up)

def w17bSingleData : Astra.DecompData :=
  let centers := (Astra.Center.window? w17bSingle 0 3).toList
  ⟨1, (fun _ _ _ i j => if i = 0 ∧ j = 4 then some 0 else none),
    ⟨w17bSingle, by decide⟩, w17bSingle.map (fun s => (s.entry,s.exit)),
    [0,4], [⟨0,4,centers⟩], centers, 0⟩

def w17bSingleDecomp : Astra.Decomposition := ⟨w17bSingleData, by decide⟩

/-- 甲方只验证后枢，且误用饱和减法所得的第零段。乙方认证这四段为盘整，不能把块尾登记为趋势转折。 -/
theorem w17b_fabricated_prev_and_underflow :
    w17bFakePrev.wellFormed w17bSingle = false ∧
    threeSeed.first - 1 = 0 ∧ w17bSingle[threeSeed.first - 1].dir = .up ∧
    w17bSingle[3].dir = .down ∧
    Opus.firstPoint .up w17bSingle w17bUnderflowJudge [] threeSeed 3 = false ∧
    Opus.firstPoint .up w17bSingle w17bUnderflowJudge [w17bFakePrev] threeSeed 3 = true ∧
    w17bSingleData.completed.head?.bind Astra.classifyTrend = some .consolidation ∧
    ({ w17bSingleData with origin := 4 }).certified = false ∧
    Astra.firstPoint w17bSingleDecomp astraTrivialStrength .up 4 = false := by
  decide

def w17bPrior : List Seg :=
  segments [(.down,50,60), (.up,40,50), (.down,40,50), (.up,40,50), (.down,20,40),
    (.up,10,25), (.down,5,20), (.up,10,20), (.down,2,20), (.up,2,15), (.down,11,15)]

def w17bPriorA : Opus.Center := { trendA with first := 1 }

def w17bPriorB : Opus.Center := { trendB with first := 5 }

def w17bPriorDecomp : Astra.Decomposition :=
  let centers := [1,5].flatMap fun i => (Astra.Center.window? w17bPrior i (i + 3)).toList
  ⟨⟨1, (fun _ _ _ i j => if i = 0 ∧ j = 9 then some 0 else none),
    ⟨w17bPrior, by decide⟩, w17bPrior.map (fun s => (s.entry,s.exit)),
    [0,9], [⟨0,9,centers⟩], centers, 9⟩, by decide⟩

def opusOnlyPrior (i : Nat) : Opus.StrengthJudge :=
  fun _ _ prior exit => decide (prior = i ∧ exit = 8)

def astraOnlyPrior (i : Nat) : Astra.StrengthJudge :=
  fun _ _ prior exit => decide (prior.source = (i,i) ∧ exit.source = (8,8))

/-- 离开同时越过核和波动下沿；只认可第一枢前的比较段时，两套搜索域才分离。 -/
theorem w17b_prior_before_first_center :
    Opus.firstPoint .up w17bPrior (opusOnlyPrior 0) [w17bPriorA] w17bPriorB 8 = false ∧
    Astra.firstPoint w17bPriorDecomp (astraOnlyPrior 0) .up 9 = true ∧
    Opus.firstPoint .up w17bPrior (opusOnlyPrior 4) [w17bPriorA] w17bPriorB 8 = true ∧
    Astra.firstPoint w17bPriorDecomp (astraOnlyPrior 4) .up 9 = true := by
  decide

def w18Steps : List Seg := trendSteps 3 28 20

def w18Buy : Astra.Decomposition := ⟨trendData ⟨w18Steps, by decide⟩, by decide⟩

/-- 分叉 4：回试低点等于 ZG。双方都判二买，唯乙方误判二三买合一。 -/
theorem w18_touch_zg_is_not_merged :
    w18Steps[9].range.lo = trendB.core.hi ∧
    Opus.secondPoint .up w18Steps opusTrivialStrength [trendA] trendB 7 = true ∧
    Opus.secondStrength .up w18Steps trendB 7 = some .rising ∧
    Opus.secondStrength .up w18Steps trendB 7 ≠ some .merged ∧
    Astra.thirdGeometry w18Buy .up 10 = false ∧
    Astra.secondStrength? w18Buy astraTrivialStrength .up 10 = some .strongest := by
  decide

def w19aSteps : List Seg :=
  segments [(.down,10,30), (.up,10,20), (.down,5,20), (.up,5,8)]

def w19aSeed : Opus.Center := ⟨0,3,by decide,⟨10,20⟩,⟨5,30⟩⟩

def w19aData (depth : Nat) : Astra.DecompData :=
  ⟨depth, fun _ _ _ _ _ => none, ⟨w19aSteps, by decide⟩,
    w19aSteps.map (fun s => (s.entry,s.exit)), [0], [],
    (Astra.Center.window? w19aSteps 0 3).toList, 0⟩

def w19aDepth0 : Astra.Decomposition := ⟨w19aData 0, by decide⟩

def w19aDepth1 : Astra.Decomposition := ⟨w19aData 1, by decide⟩

/-- 同 W8b 的第 54 课标杆，但成核第 3 段同时是离开段。 -/
theorem w19a_third_segment_is_leave :
    Opus.thirdCore .down w19aSteps w19aSeed 2 = true ∧
    Astra.breakoutRetest w19aDepth1 .down ⟨10,20⟩ 4 = true ∧
    Astra.thirdGeometry w19aDepth1 .down 4 = false ∧
    Astra.isThirdSell w19aDepth1 4 = false ∧
    Astra.isPseudoThirdSell w19aDepth0 4 = false := by
  decide

def astraOpenData (depth : Nat) (steps : Astra.AltSeq) (first stop : Nat) : Astra.DecompData :=
  ⟨depth, fun _ _ _ _ _ => none, steps, steps.items.map (fun s => (s.entry,s.exit)),
    [0], [], (Astra.Center.window? steps.items first stop).toList, 0⟩

def w19bSteps : List Seg :=
  segments [(.up,0,20), (.down,10,20), (.up,10,25), (.down,22,25)]

def w19bSeed : Opus.Center := ⟨0,3,by decide,⟨10,20⟩,⟨0,25⟩⟩

def w19bAlt : Astra.AltSeq := ⟨w19bSteps, by decide⟩

def w19bDepth0 : Astra.Decomposition := ⟨astraOpenData 0 w19bAlt 0 3, by decide⟩

def w19bDepth1 : Astra.Decomposition := ⟨astraOpenData 1 w19bAlt 0 3, by decide⟩

theorem w19b_third_segment_leaves_up :
    Opus.thirdCore .up w19bSteps w19bSeed 2 = true ∧
    Astra.breakoutRetest w19bDepth1 .up ⟨10,20⟩ 4 = true ∧
    Astra.thirdGeometry w19bDepth1 .up 4 = false ∧
    Astra.isThirdBuy w19bDepth1 4 = false ∧
    Astra.isPseudoThirdBuy w19bDepth0 4 = false := by
  decide

def w19cCover : Opus.Center := ⟨0,4,by decide,⟨10,20⟩,⟨10,30⟩⟩

def w19cDepth0 : Astra.Decomposition :=
  ⟨astraOpenData 0 ⟨w8aSteps, by decide⟩ 0 3, by decide⟩

/-- 甲方在底层同样调用几何判据；乙方几何与阶段均通过，但只准调用类三买。 -/
theorem w19c_depth_zero_routes_to_pseudo :
    Opus.thirdCore .up w8aSteps w19cCover 3 = true ∧
    Astra.thirdPoint w19cDepth0 .up 5 = true ∧
    Astra.isThirdBuy w19cDepth0 5 = false ∧
    Astra.isPseudoThirdBuy w19cDepth0 5 = true := by
  decide

/-! ## W20：在线触边与后继反转段 -/

def w20aSteps : List Seg :=
  segments [(.down,0,5), (.up,10,20), (.down,10,20), (.up,10,20), (.down,8,15)]

def w20aCover : Opus.Center := ⟨1,4,by decide,⟨10,20⟩,⟨8,20⟩⟩

def w20aData : Astra.DecompData := astraOpenData 0 ⟨w20aSteps, by decide⟩ 1 5

def w20aOpen : Astra.Decomposition := ⟨w20aData, by decide⟩

def w20aConfirmedSteps : List Seg := w20aSteps ++ [⟨.up, ⟨8,18⟩, (5,5)⟩]

def w20aConfirmed : Astra.Decomposition :=
  ⟨astraOpenData 0 ⟨w20aConfirmedSteps, by decide⟩ 1 5, by decide⟩

/-- 对撞报告取 origin = 1，但此处没有完成趋势可认证该起点。改按基底起点观察，仍选同一中枢并处于震荡；只补端点相接的反转段即可翻转乙方结果。 -/
theorem w20a_oscillation_waits_for_reversal :
    Opus.isOscillationBuy w20aSteps 0 w20aCover 4 = true ∧
    ({ w20aData with origin := 1 }).certified = false ∧
    Astra.phaseAt w20aOpen 5 = some .oscillation ∧
    Astra.oscillationPoint w20aOpen .up 5 = false ∧
    Astra.oscillationPoint w20aConfirmed .up 5 = true := by
  decide

end Chan.Audit.Separation.Fm10c
