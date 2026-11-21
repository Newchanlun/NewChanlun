import Origin.ChanlunElements

namespace NewChanlun.Origin.R5Settlement

/-- 共用扫描的已完成单元投影：不含级别。 -/
structure UnitRange where
  direction : Direction
  lo : Tick
  hi : Tick
  startIndex : Index
  endIndex : Index
  ordered : lo ≤ hi

inductive R5Joint where
  | notOutside
  | breakUnitOutward
  | directionNotAlternating
  | prevOutsideCore
  | jointNotConnected
  | proven (side : Direction)
  deriving DecidableEq, Repr

def jointExtreme (side : Direction) (u : UnitRange) : Tick :=
  match side with
  | .up => u.hi
  | .down => u.lo

def ClosedOverlap (zd zg : Tick) (u : UnitRange) : Prop :=
  u.lo ≤ zg ∧ zd ≤ u.hi

def StrictOutside (zd zg : Tick) (u : UnitRange) (side : Direction) : Prop :=
  match side with
  | .up => zg < u.lo
  | .down => u.hi < zd

instance (zd zg : Tick) (u : UnitRange) (side : Direction) :
    Decidable (StrictOutside zd zg u side) := by
  cases side <;> (unfold StrictOutside; infer_instance)

/-- 与 Rust `r5_joint` 同序；有效核心为 `zd < zg`，相切不构成见证。 -/
def r5Joint (zd zg : Tick) (prev cur : UnitRange) : R5Joint :=
  let outside : Option Direction :=
    if cur.hi < zd then some .down else if zg < cur.lo then some .up else none
  match outside with
  | none => .notOutside
  | some side =>
    if cur.direction = side then .breakUnitOutward
    else if prev.direction ≠ side then .directionNotAlternating
    else if ¬ (prev.lo ≤ zg ∧ zd ≤ prev.hi) then .prevOutsideCore
    else if prev.endIndex = cur.startIndex ∧ jointExtreme side prev = jointExtreme side cur then
      .proven side
    else .jointNotConnected

/-- #2114：端点极值相接且方向交替，严格在外的当前段必朝核心回抽。
    价格上的角色推导不需要 K 序等式；发见证仍须在 `r5Joint` 核 K 序。 -/
theorem connected_alternating_outside_is_pullback
    (zd zg : Tick) (prev cur : UnitRange) (side : Direction)
    (_hCore : zd < zg)
    (hOverlap : ClosedOverlap zd zg prev)
    (hOutside : StrictOutside zd zg cur side)
    (hAlternating : prev.direction ≠ cur.direction)
    (hExtreme : jointExtreme prev.direction prev = jointExtreme prev.direction cur) :
    prev.direction = side ∧ cur.direction = side.flip := by
  have hRole : prev.direction = side := by
    cases side with
    | up =>
      cases hp : prev.direction with
      | up => rfl
      | down =>
        have hEq : prev.lo = cur.lo := by simpa [hp, jointExtreme] using hExtreme
        have hAbove : zg < cur.lo := hOutside
        have hLe : cur.lo ≤ zg := hEq ▸ hOverlap.1
        exact False.elim (Int.not_le_of_gt hAbove hLe)
    | down =>
      cases hp : prev.direction with
      | up =>
        have hEq : prev.hi = cur.hi := by simpa [hp, jointExtreme] using hExtreme
        have hBelow : cur.hi < zd := hOutside
        have hLe : zd ≤ cur.hi := hEq ▸ hOverlap.2
        exact False.elim (Int.not_le_of_gt hBelow hLe)
      | down => rfl
  refine ⟨hRole, ?_⟩
  have hRetest : cur.direction ≠ side := fun hc => hAlternating (hRole.trans hc.symm)
  cases side <;> cases hc : cur.direction <;> simp_all [Direction.flip]

end NewChanlun.Origin.R5Settlement
