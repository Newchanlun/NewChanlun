module

meta import ChanExplore.Examples

namespace ChanExplore

private meta def measure (label : String) (search : (n k : Nat) → SearchResult k)
    (n k : Nat) : IO Unit := do
  let start ← IO.monoNanosNow
  let result := search n k
  let elapsed := (← IO.monoNanosNow) - start
  IO.println s!"{label} n={n} k={k} 判定={result.checked} 耗时={elapsed} ns"
  IO.println (repr result.witness)

-- 固定 Fin 8 测试较短路径，再在命中的长度上缩小价格格。
#eval do
  for n in [:4] do
    measure "外包线" outerSearch n 8
  for n in [:5] do
    measure "外包线且仍有顶" outerWithTopSearch n 8
  for k in [:4] do
    measure "外包线" outerSearch 3 k
    measure "外包线且仍有顶" outerWithTopSearch 4 k
  measure "向上对照" upwardSearch 4 8
  for n in [:4] do
    measure "三段" touchingSearch n 8
  for k in [:8] do
    measure "三段" touchingSearch 3 k

-- 首次包含前只有一根，不能猜方向；向上合并确实保留最高价。
#guard
  let path : List (Bar 8) := [⟨0, 0, by decide⟩, ⟨0, 2, by decide⟩,
    ⟨1, 1, by decide⟩, ⟨0, 0, by decide⟩]
  (normalize path).isNone
#guard
  let path : List (Bar 8) := [⟨0, 0, by decide⟩, ⟨1, 1, by decide⟩, ⟨0, 2, by decide⟩]
  (normalize path).any fun (normalized, losses) =>
    normalized.map (fun bar => (bar.low.val, bar.high.val)) == [(0, 0), (1, 2)] &&
      losses.isEmpty

-- 空路径只有一条；空价格格上没有正长度路径。
#guard (findCounterexample 0 0 (fun _ => False)).witness == some []
#guard (findCounterexample 1 0 (fun _ => False)).checked == 0
#guard (findCounterexample 2 2 (fun _ => True)).checked == 9
#guard (findCounterexample 2 3 (fun path => path.all (fun b => b.low == b.high) = true)).checked == 2

-- 抽样保持长度，种子可重放，且预算与首次失败都正确计数。
#guard ((randomCheck 5 8 2319 4 (fun _ => False)).bind (·.witness)).any
  (fun path => path.length == 5)
#guard ((randomCheck 5 8 2319 4 (fun _ => False)).bind (·.witness)) ==
  ((randomCheck 5 8 2319 1 (fun _ => False)).bind (·.witness))
#guard ((randomCheck 5 8 2319 4 (fun _ => False)).map (·.checked)) == some 1
#guard ((randomCheck 5 8 2319 4 (fun _ => True)).map (·.checked)) == some 4
#guard (randomCheck 5 0 2319 4 (fun _ => True)).isNone
#guard ((randomCheck 0 0 2319 1 (fun _ => False)).bind (·.witness)) == some []

end ChanExplore
