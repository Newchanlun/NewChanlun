/- #1496 / #2114：R5 关节见证；导出器不进 lake roots。
   按端点相连、方向交替的字面分支取证；关节极值不等的情形见 #2141。 -/
import Origin.R5Settlement
import Lean.Data.Json

namespace NewChanlun.Origin.R5WitnessFixtureExport

open Lean (Json toJson)

open NewChanlun.Origin.R5Settlement

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
