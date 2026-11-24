module

public import ChanExplore.Search

/-!
# 两个搜索见证

这里的包含处理与顶分型是探索用的草稿定义，不是本包的正式定义。
-/

@[expose] public section

namespace ChanExplore

/-- 草稿：允许端点相等的闭区间包含。 -/
def covers {k : Nat} (outer inner : Bar k) : Bool :=
  outer.low ≤ inner.low && inner.high ≤ outer.high

/-- 包含合并使用的已定方向。 -/
inductive Direction
  | up
  | down
  deriving DecidableEq, BEq

/-- 草稿：只有高、低同向严格变化才能判定方向。 -/
def direction {k : Nat} (left right : Bar k) : Option Direction :=
  if left.low < right.low && left.high < right.high then some .up
  else if right.low < left.low && right.high < left.high then some .down
  else none

/-- 草稿：沿已定方向取两端点的较大值或较小值。 -/
def merge {k : Nat} (dir : Direction) (a b : Bar k) : Bar k :=
  match dir with
  | .up =>
    ⟨⟨max a.low.val b.low.val, Nat.max_lt.mpr ⟨a.low.isLt, b.low.isLt⟩⟩,
      ⟨max a.high.val b.high.val, Nat.max_lt.mpr ⟨a.high.isLt, b.high.isLt⟩⟩,
      Nat.max_le.mpr ⟨Nat.le_trans a.ordered (Nat.le_max_left ..),
        Nat.le_trans b.ordered (Nat.le_max_right ..)⟩⟩
  | .down =>
    ⟨⟨min a.low.val b.low.val, Nat.lt_of_le_of_lt (Nat.min_le_left ..) a.low.isLt⟩,
      ⟨min a.high.val b.high.val, Nat.lt_of_le_of_lt (Nat.min_le_left ..) a.high.isLt⟩,
      Nat.le_min_of_le_of_le
        (Nat.le_trans (Nat.min_le_left ..) a.ordered)
        (Nat.le_trans (Nat.min_le_right ..) b.ordered)⟩

/-- 草稿：用已处理序列最后两根确定方向。遇到包含而方向未定时返回 `none`；
成功时返回规范序列和每次合并直接压低的高点及其方向。 -/
def normalize {k : Nat} (path : List (Bar k)) :
    Option (List (Bar k) × List (Direction × Fin k)) := do
  let (stack, losses) ← path.foldlM (fun (stack, losses) bar => push stack bar losses) ([], [])
  return (stack.reverse, losses.reverse)
where
  push (stack : List (Bar k)) (bar : Bar k) (losses : List (Direction × Fin k)) :
      Option (List (Bar k) × List (Direction × Fin k)) :=
    match stack with
    | [] => some ([bar], losses)
    | prev :: rest =>
      if covers prev bar || covers bar prev then do
        let left ← rest.head?
        let dir ← direction left prev
        let merged := merge dir prev bar
        let losses := if merged.high < prev.high then (dir, prev.high) :: losses else losses
        let losses := if merged.high < bar.high then (dir, bar.high) :: losses else losses
        push rest merged losses
      else some (bar :: stack, losses)

/-- 草稿：连续三根中，中间一根的高、低都严格高于左右邻居。 -/
def topPrices {k : Nat} (path : List (Bar k)) : List (Fin k) :=
  match path with
  | left :: mid :: right :: rest =>
    let tail := topPrices (mid :: right :: rest)
    if left.high < mid.high && right.high < mid.high &&
        left.low < mid.low && right.low < mid.low then mid.high :: tail
    else tail
  | _ => []

/-- 只计入指定方向直接压低的高点：它必须是原始唯一最高价，且在规范序列中消失。 -/
def dropsHigh {k : Nat} (dir : Direction) (requireTop : Bool) (path : List (Bar k)) : Bool :=
  match normalize path with
  | none => false
  | some (normalized, losses) =>
    (!requireTop || !(topPrices normalized).isEmpty) &&
      losses.any fun (eventDir, price) =>
        eventDir == dir && path.all (fun bar => bar.high ≤ price) &&
          path.countP (fun bar => bar.high.val == price.val) == 1 &&
          normalized.all (fun bar => bar.high.val != price.val)

/-- 向下合并吞掉唯一最高价，不额外要求规范序列有顶分型。 -/
def outerDropsHigh {k : Nat} (path : List (Bar k)) : Bool :=
  dropsHigh .down false path

/-- 三条非平段按上、下、上或下、上、下交替，相邻段的终点与起点相同，
但最大低点严格高于最小高点（闭区间单点重叠不算反例）。 -/
def touchingWithoutOverlap {k : Nat} (path : List (Bar k)) : Bool :=
  match path with
  | [a, b, c] =>
    a.low < a.high && b.low < b.high && c.low < c.high &&
      ((a.high.val == b.high.val && b.low.val == c.low.val) ||
        (a.low.val == b.low.val && b.high.val == c.high.val)) &&
      min a.high.val (min b.high.val c.high.val) < max a.low.val (max b.low.val c.low.val)
  | _ => false

/-- 搜索拒绝「不会吞掉最高价」这一断言。 -/
def outerSearch (n k : Nat) : SearchResult k :=
  findCounterexample n k fun path => outerDropsHigh path = false

/-- 在吞掉最高价的同时，要求规范序列仍有顶分型。 -/
def outerWithTopSearch (n k : Nat) : SearchResult k :=
  findCounterexample n k fun path => dropsHigh .down true path = false

/-- 对照：检验向上合并是否直接压低唯一最高价。 -/
def upwardSearch (n k : Nat) : SearchResult k :=
  findCounterexample n k fun path => dropsHigh .up false path = false

/-- 搜索拒绝「没有首尾相接却无公共部分的三段」这一断言。 -/
def touchingSearch (n k : Nat) : SearchResult k :=
  findCounterexample n k fun path => touchingWithoutOverlap path = false

end ChanExplore

end

public section

namespace ChanExplore

/-- 首个反例的处理有结果，并且明确由已定的向下合并吞掉唯一最高价 2。 -/
theorem outerDropsHigh_found :
    let witness := (outerSearch 3 8).witness
    witness.map (List.map fun bar => (bar.low.val, bar.high.val)) =
      some [(1, 1), (0, 0), (0, 2)] ∧
    witness.any outerDropsHigh = true ∧
    (witness.bind normalize).any (fun (_, losses) =>
      losses.any fun (dir, price) => dir == .down && price.val == 2) = true := by
  decide

/-- 由搜索产出的三段确实首尾相接、方向交替且没有公共部分。 -/
theorem touchingWithoutOverlap_found :
    let witness := (touchingSearch 3 8).witness
    witness.map (List.map fun bar => (bar.low.val, bar.high.val)) =
      some [(0, 1), (0, 3), (2, 3)] ∧ witness.any touchingWithoutOverlap = true := by
  decide

#print axioms outerDropsHigh_found
#print axioms touchingWithoutOverlap_found

end ChanExplore
