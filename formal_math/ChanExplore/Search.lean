module

import Init.Data.Random

/-!
# 有界区间搜索

穷举与抽样使用同一个区间类型；二者都把谓词为假的首条路径作为反例。
-/

@[expose] public section

namespace ChanExplore

/-- 价格格 `Fin k` 上的非空闭区间，允许单点。 -/
structure Bar (k : Nat) where
  low : Fin k
  high : Fin k
  ordered : low ≤ high
  deriving Repr, DecidableEq

/-- 按低点、再按高点递增列出全部区间。 -/
def bars (k : Nat) : List (Bar k) :=
  let prices := List.finRange k
  prices.flatMap fun low =>
    prices.filterMap fun high =>
      if h : low ≤ high then some ⟨low, high, h⟩ else none

/-- `checked` 是实际判定次数，包含命中反例的那一次。 -/
structure SearchResult (k : Nat) where
  witness : Option (List (Bar k))
  checked : Nat
  deriving Repr

/-- 按区间字典序深度优先搜索，不构造完整的路径笛卡尔积。 -/
def findCounterexample (n k : Nat) (P : List (Bar k) → Prop) [DecidablePred P] :
    SearchResult k :=
  visit (bars k) n [] 0
where
  visit (choices : List (Bar k)) (remaining : Nat) (revPrefix : List (Bar k))
      (checked : Nat) : SearchResult k :=
    match remaining with
    | 0 =>
      let path := revPrefix.reverse
      ⟨if P path then none else some path, checked + 1⟩
    | m + 1 => Id.run do
      let mut count := checked
      for bar in choices do
        let result := visit choices m (bar :: revPrefix) count
        if result.witness.isSome then return result
        count := result.checked
      return ⟨none, count⟩

/-- 用显式种子抽样测试至多 `trials` 条路径。正长度配空价格格时返回 `none`；
否则返回报告，报告内的 `witness = none` 表示抽样未命中。 -/
def randomCheck (n k seed trials : Nat) (P : List (Bar k) → Prop) [DecidablePred P] :
    Option (SearchResult k) :=
  if hk : 0 < k then
    some (test (draw n hk) trials (mkStdGen seed) 0)
  else if n = 0 then
    some (test (fun g => ([], g)) trials (mkStdGen seed) 0)
  else none
where
  draw (remaining : Nat) (hk : 0 < k) (g : StdGen) : List (Bar k) × StdGen :=
    match remaining with
    | 0 => ([], g)
    | m + 1 =>
      let (x, g₁) := stdNext g
      let (y, g₂) := stdNext g₁
      let low : Fin k := ⟨min (x % k) (y % k), Nat.lt_of_le_of_lt (Nat.min_le_left ..)
        (Nat.mod_lt _ hk)⟩
      let high : Fin k := ⟨max (x % k) (y % k), Nat.max_lt.mpr
        ⟨Nat.mod_lt _ hk, Nat.mod_lt _ hk⟩⟩
      let (tail, g₃) := draw m hk g₂
      (⟨low, high, Nat.le_trans (Nat.min_le_left ..) (Nat.le_max_left ..)⟩ :: tail, g₃)
  test (next : StdGen → List (Bar k) × StdGen) (remaining : Nat) (g : StdGen)
      (checked : Nat) : SearchResult k :=
    match remaining with
    | 0 => ⟨none, checked⟩
    | m + 1 =>
      let (path, g') := next g
      if P path then test next m g' (checked + 1) else ⟨some path, checked + 1⟩

end ChanExplore
