/- #1496 / #2114：R5 关节见证；导出器不进 lake roots。
   按端点相连、方向交替的字面分支取证；关节极值不等的情形见 #2141。 -/
import Origin.ChanlunElements
import Lean.Data.Json

namespace NewChanlun.Origin.R5WitnessFixtureExport

open Lean (Json toJson)

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

private def directionName : Direction → String
  | .up => "Up"
  | .down => "Down"

private def jointJson : R5Joint → Json
  | .notOutside => toJson "NotOutside"
  | .breakUnitOutward => toJson "BreakUnitOutward"
  | .directionNotAlternating => toJson "DirectionNotAlternating"
  | .prevOutsideCore => toJson "PrevOutsideCore"
  | .jointNotConnected => toJson "JointNotConnected"
  | .proven side => Json.mkObj [("Proven", toJson (directionName side))]

private def unitJson (u : UnitRange) : Json :=
  Json.mkObj [
    ("direction", toJson (directionName u.direction)),
    ("lo", toJson u.lo), ("hi", toJson u.hi),
    ("start_index", toJson u.startIndex), ("end_index", toJson u.endIndex)]

private def unit (dir : Direction) (lo hi : Tick) (start stop : Index)
    (ordered : lo ≤ hi := by decide) : UnitRange :=
  ⟨dir, lo, hi, start, stop, ordered⟩

private def fixtureCase (name : String) (zd zg : Tick) (prev cur : UnitRange) : Json :=
  Json.mkObj [
    ("name", toJson name), ("zd", toJson zd), ("zg", toJson zg),
    ("prev", unitJson prev), ("cur", unitJson cur),
    ("expected", jointJson (r5Joint zd zg prev cur))]

private def fixture : Json :=
  Json.mkObj [("schema", toJson "tb1496-r5-joint/1"), ("cases", Json.arr #[
    fixtureCase "connected_down" 20 35 (unit .down 5 25 28 32) (unit .up 5 15 32 36),
    fixtureCase "connected_up" 20 35 (unit .up 30 50 28 32) (unit .down 40 50 32 36),
    fixtureCase "outward_up_refSeg4Break" 12 15 (unit .down 13 16 3 4) (unit .up 22 25 4 5),
    fixtureCase "outward_down" 20 35 (unit .up 25 40 12 16) (unit .down 8 16 16 20),
    fixtureCase "unequal_extremes" 20 35 (unit .up 22 45 16 20) (unit .down 38 50 20 24),
    fixtureCase "index_gap" 20 35 (unit .up 22 45 16 20) (unit .down 38 45 21 25),
    fixtureCase "same_direction" 20 35 (unit .down 30 45 12 16) (unit .down 40 50 16 20),
    fixtureCase "touch_zg" 20 35 (unit .up 25 45 16 20) (unit .down 35 45 20 24),
    fixtureCase "prev_outside" 20 35 (unit .up 37 50 16 20) (unit .down 38 50 20 24)
  ])]

#eval IO.println fixture.compress

end NewChanlun.Origin.R5WitnessFixtureExport
