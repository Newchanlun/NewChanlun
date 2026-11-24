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

/-- 草稿：全程取向下合并，两个端点各取较低者；合并后继续检查左邻。 -/
def normalizeDown {k : Nat} (path : List (Bar k)) : List (Bar k) :=
  (path.foldl push []).reverse
where
  push (stack : List (Bar k)) (bar : Bar k) : List (Bar k) :=
    match stack with
    | [] => [bar]
    | prev :: rest =>
      if covers prev bar || covers bar prev then
        push rest ⟨min prev.low bar.low, min prev.high bar.high,
          Nat.le_min_of_le_of_le
            (Nat.le_trans (Nat.min_le_left ..) prev.ordered)
            (Nat.le_trans (Nat.min_le_right ..) bar.ordered)⟩
      else bar :: stack

/-- 草稿：连续三根中，中间一根的高、低都严格高于左右邻居。 -/
def topPrices {k : Nat} (path : List (Bar k)) : List (Fin k) :=
  match path with
  | left :: mid :: right :: rest =>
    let tail := topPrices (mid :: right :: rest)
    if left.high < mid.high && right.high < mid.high &&
        left.low < mid.low && right.low < mid.low then mid.high :: tail
    else tail
  | _ => []

/-- 后一根外包线抬高输入的全局最高价；合并后仍有顶分型，但最高价连高点都不再是。 -/
def outerDropsHigh {k : Nat} (path : List (Bar k)) : Bool :=
  (path.zip path.tail).any fun (inner, outer) =>
    covers outer inner && inner.high < outer.high &&
      path.all (fun bar => bar.high ≤ outer.high) &&
      let normalized := normalizeDown path
      !(topPrices normalized).isEmpty && normalized.all (fun bar => bar.high < outer.high)

/-- 三条非平段按上、下、上或下、上、下交替，相邻段的终点与起点相同，
但最大低点严格高于最小高点（闭区间单点重叠不算反例）。 -/
def touchingWithoutOverlap {k : Nat} (path : List (Bar k)) : Bool :=
  match path with
  | [a, b, c] =>
    a.low < a.high && b.low < b.high && c.low < c.high &&
      ((a.high == b.high && b.low == c.low) || (a.low == b.low && b.high == c.high)) &&
      min a.high (min b.high c.high) < max a.low (max b.low c.low)
  | _ => false

/-- 搜索拒绝「不会吞掉最高价」这一断言。 -/
def outerSearch (n k : Nat) : SearchResult k :=
  findCounterexample n k fun path => outerDropsHigh path = false

/-- 搜索拒绝「没有首尾相接却无公共部分的三段」这一断言。 -/
def touchingSearch (n k : Nat) : SearchResult k :=
  findCounterexample n k fun path => touchingWithoutOverlap path = false

end ChanExplore

end

public section

namespace ChanExplore

/-- 由搜索产出的四根 K 线确实满足最高价消失的反例判据。 -/
theorem outerDropsHigh_found :
    let witness := (outerSearch 4 8).witness
    witness.map (List.map fun bar => (bar.low.val, bar.high.val)) =
      some [(0, 0), (0, 2), (1, 1), (0, 0)] ∧ witness.any outerDropsHigh = true := by
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
