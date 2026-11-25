import Origin.SegmentMemberRange
import Origin.SegmentAutoConstruct
import Lean.Data.Json

/-! #1486：逐个把 #1419 冻结的 BTC CC-013 成员笔交给 `segmentsOfComplete .closed`，
    每组必须原样消费成一段；不读取塔的 hi/lo。
    导出：`cd formal && lake env lean Origin/SegmentRangeParityExport.lean`。 -/

namespace NewChanlun.Origin.SegmentRangeParityExport

open Lean (Json)

private def field (row : Json) (key : String) : Except String String :=
  row.getObjValAs? String key

private def index (row : Json) (key : String) : Except String Nat := do
  let value ← field row key
  let some parsed := value.toNat? | throw s!"{key} 不是下标: {value}"
  return parsed

private def price (row : Json) (key : String) : Except String Tick := do
  let value ← field row key
  let some parsed := value.toInt? | throw s!"{key} 不是整数 tick: {value}"
  return parsed

private structure UnitInput where
  startStroke : Nat
  direction : Direction
  strokes : List Stroke

private def unitInput (data : Json) : Except String UnitInput := do
  let construction ← data.getObjVal? "construction"
  let start ← index construction "start_stroke"
  let dirName ← field construction "direction"
  let dir : Direction ← match dirName with
    | "UP" => pure .up
    | "DOWN" => pure .down
    | name => throw s!"未知段方向: {name}"
  let refs ← (← data.getObjValAs? (Array Json) "stroke_refs").mapM fun row => do
    pure (← index row "stroke_index", row)
  let indices ← construction.getObjValAs? (List String) "stroke_indices"
  let members ← indices.mapM fun key => do
    let some i := key.toNat? | throw s!"成员笔下标无效: {key}"
    let some (_, row) := refs.find? (fun ref => ref.1 == i) | throw s!"找不到成员笔 {i}"
    let s ← price row "start_price"
    let e ← price row "end_price"
    -- 该夹具不带成员笔的 K 线索引；以笔序号标记边界，区间求值只读端价。
    pure ({ direction := if s ≤ e then .up else .down
            startIndex := i, endIndex := i + 1, startPrice := s, endPrice := e } : Stroke)
  return { startStroke := start, direction := dir, strokes := members }

private def btcUnits : Except String (Array UnitInput) := do
  let raw ← Json.parse (include_str "../../s_session/tests/fixtures/tb02e-real/btc-tail50k-first600.json")
  let mut rows := #[]
  for record in ← raw.getObjValAs? (Array Json) "segments" do
    if (← field record "kind") == "CC-013.segment" then
      let data ← (← record.getObjVal? "payload").getObjVal? "data"
      let result ← field data "result"
      if result == "CASE_ONE" || result == "CASE_TWO" then
        rows := rows.push (← unitInput data)
  return rows.qsort (fun a b => a.startStroke < b.startStroke)

private def constructUnit (unit : UnitInput) : Except String Segment := do
  let first :: rest := unit.strokes | throw s!"完成段 {unit.startStroke} 无成员笔"
  let [segment] := segmentsOfComplete .closed unit.strokes
    | throw s!"完成段 {unit.startStroke} 的成员未被消费为一段"
  if segment.startIndex != unit.startStroke || segment.endIndex != (rest.getLastD first).endIndex ||
      segment.direction != unit.direction then
    throw s!"完成段 {unit.startStroke} 的边界索引或方向不一致"
  return segment

-- 单元 0 的七笔：几何终价为 7759246000000，实际构造必须返回更低的成员极值。
private def unitZero : Except String (Nat × Nat × Tick) := do
  let some unit := (← btcUnits)[0]? | throw "缺少单元 0"
  let segment ← constructUnit unit
  return (unit.startStroke, unit.strokes.length, segLow segment)

#guard unitZero.toOption == some (0, 7, 7756973000000)

private def fixture : Except String Json := do
  let units ← (← btcUnits).mapM fun unit => do
    let segment ← constructUnit unit
    let dirName := match segment.direction with | .up => "UP" | .down => "DOWN"
    return Json.mkObj [("start_stroke", Lean.toJson segment.startIndex), ("dir", Json.str dirName),
      ("hi", Lean.toJson (segHigh segment)), ("lo", Lean.toJson (segLow segment))]
  return Json.mkObj [("schema", Json.str "theta-v0-segment-range-parity/1"), ("units", Json.arr units)]

#eval do
  match fixture with
  | .ok json => IO.println json.compress
  | .error msg => throw (IO.userError msg)

end NewChanlun.Origin.SegmentRangeParityExport
