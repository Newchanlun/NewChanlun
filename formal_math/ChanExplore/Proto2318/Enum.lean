module

public import ChanExplore.Proto2318.Basic

/-!
# 小模型穷举

直接枚举 `Fin k` 上的方向交替折线，对每条折线穷举全部良构切点表并按规范筛。
读数与 `py/census.py raw` 的同规模读数逐格比对，见 `Census.lean`。
-/

@[expose] public section

namespace ChanExplore.Proto2318

/-- `Fin k` 上从 `last` 出发、再走 `n` 段的全部方向交替续写。 -/
def altFrom (k : Nat) : Nat → Bool → Nat → List (List Nat)
  | 0, _, _ => [[]]
  | n + 1, up, last =>
    ((List.range k).filter fun v => if up then last < v else v < last).flatMap fun v =>
      (altFrom k n (!up) v).map (v :: ·)

/-- `Fin k` 上恰 `n` 段的全部方向交替折线（端点表）。 -/
def altPaths (k n : Nat) : List (List Nat) :=
  (List.range k).flatMap fun v =>
    [true, false].flatMap fun up => (altFrom k n up v).map (v :: ·)

/-- 合法分解个数为 0、恰为 1、多于 1 的折线条数。 -/
def census (p : Policy) (k n : Nat) : Nat × Nat × Nat :=
  (altPaths k n).foldl (fun (acc : Nat × Nat × Nat) path =>
    match (validCuts p (segs path)).length with
    | 0 => (acc.1 + 1, acc.2.1, acc.2.2)
    | 1 => (acc.1, acc.2.1 + 1, acc.2.2)
    | _ => (acc.1, acc.2.1, acc.2.2 + 1)) (0, 0, 0)

/-- 全部政策，按 `py/model.py` 的 `LOCAL` 顺序。 -/
def allPolicies : List Policy :=
  [.anyFull, .anyExh, .same, .minimal, .maximal, .extExh, .noCap, .carry]

end ChanExplore.Proto2318
