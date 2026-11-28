module

public import Chan.Defs.Level.Rule

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Order Chan.Defs.Alt Chan.Defs.Center
variable {P : Type _} [LinearOrder P]

/-- #2296（needs-fable）：九段以前何时允许普通成块。 -/
inductive TimingPolicy where
  | seeded | coreBroken | thirdEvent
  deriving DecidableEq

/-- #2296（needs-fable）：进位后重新起核的三种单层口径。 -/
inductive RestartPolicy where
  | afterNine | entryAfterCarry | atNextSeed
  deriving DecidableEq

/-- 九段前的起核是否必须在独立进入段之后。 -/
inductive EntryPolicy where
  | mayIncludeFirst | requireEntry
  deriving DecidableEq

/-- 三处未定分支由调用者分别选择；前导搜索可以关闭。

[057:42] 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。这一点其实由6这个第三类卖点的存在以及后面的背驰，就可以知道，这中枢级别的扩展，是必然的。
-/
structure CarryNineParams where
  timing : TimingPolicy
  restart : RestartPolicy
  entry : EntryPolicy
  searchLead : Bool
  deriving DecidableEq

/-- 在不早于 start 的最早位置搜索合法三段成核，不要求前导段本身成核。 -/
def firstSeedFrom (xs : List (Seg P)) (start : Nat) : Option Nat :=
  ((List.range (xs.length - start)).map (start + ·)).find?
    (fun n => (Center.window? xs n (n+3)).isSome)

/-- 九段需围绕同一个核，且三个三段凸包有公共交，不要求九段共用一个价格。

[057:42] 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。这一点其实由6这个第三类卖点的存在以及后面的背驰，就可以知道，这中枢级别的扩展，是必然的。
[二级旁证 066:186] 不一定。按3+3+3这样组合后确定5分钟的。
[二级旁证 069:423] 临走回答一下，这问题太典型，就是概念没搞清楚。5分钟中枢，只要3个1分钟走势类型有重合就可以，不是一定要里面的所有段都重合。所有都重合，只是其中一个特殊的情况，这叫又线段延伸九段后形成5分钟中枢，在这种情况下，同样可以看成是三个1分钟走势类型的重合。
-/
def nineAt (xs : List (Seg P)) (i : Nat) : Bool :=
  (Center.window? xs i (i+9)).isSome &&
    -- 此处只读凸包，粗化方向不影响三凸包的交。
    let dir := CoarseDirPolicy.firstSegment (P := P)
    match BlockRule.coarsen xs i (i+3) dir, BlockRule.coarsen xs (i+3) (i+6) dir,
          BlockRule.coarsen xs (i+6) (i+9) dir with
    | some a, some b, some c => decide (overlapsList a.range [b.range,c.range])
    | _, _, _ => false

/-- 前枢的触核延伸结束后，沿同一个核找首次严格回试破坏。
连续离开计入块内，跳空离开从下一块起算。 -/
def thirdEventEnd? (xs : List (Seg P)) (seed : Nat) : Option Nat := do
  let z ← Center.window? xs seed (seed + extRun xs seed)
  let next ← xs[z.stop]?
  if decide (z.extendsWith next) then none else
    let start := z.stop - 1
    ((List.range (xs.length - (start + 1))).map (start + ·)).findSome? fun k => do
      let leave ← xs[k]?
      let back ← xs[k+1]?
      let (third, gap) := match leave.dir with
        | .up => (decide (z.thirdBuyEvent leave back), decide (z.leavesUp leave))
        | .down => (decide (z.thirdSellEvent leave back), decide (z.leavesDown leave))
      if third then some (if gap then k else k + 1) else none

/-- 离开后的第一个新枢起点；允许以回试段作为第一成核段。
不等待第三类事件时，仍须先走完前枢的触核延伸。 -/
def firstReturnFrom (xs : List (Seg P)) (z : Center P) (requireThird : Bool) : Option Nat :=
  let complete := z.departureIndex? .up xs <|> z.departureIndex? .down xs
  let leave :=
    if requireThird then complete
    else if (xs[z.stop]?).any (fun s => decide (z.extendsWith s)) then none
    else complete <|>
      [z.stop - 1, z.stop].find? (fun k => (xs[k]?).any fun s =>
        match s.dir with
        | .up => if k == z.stop then decide (z.leavesUp s) else decide (z.core.hi < s.range.hi)
        | .down => if k == z.stop then decide (z.leavesDown s) else decide (s.range.lo < z.core.lo))
  leave.bind (fun k => firstSeedFrom xs (k+1))

/-- 途径二：前后枢的核分离、波动区间相交。可选上界只约束后枢延伸。

[020:44] 缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。
[二级旁证 095:86] 次好的，就是在这里形成5分钟中枢后再出现第三类买点，这里有两种途径，一种是9次级别的震荡扩展出5分钟，一种是先1分钟的第三类卖点后底背驰上来再出来5分钟。这里就构成了N次必然的短线机会。
-/
def returningCenter (xs : List (Seg P)) (z : Center P) (j : Nat)
    (requireThird : Bool) (bound : Option Nat := none) : Bool :=
  match firstReturnFrom xs z requireThird with
  | none => false
  | some n =>
    match Center.window? xs n j with
    | none => false
    | some next => bound.all (fun b => decide (next.cover.length ≤ b)) &&
        match relPos z.zone next.zone with
        | .expansionUp | .expansionDown => true
        | _ => false

/-- 普通入口的第一成核点。 -/
def carrySeed? (p : CarryNineParams) (xs : List (Seg P)) (start : Nat) : Option Nat :=
  if p.searchLead then firstSeedFrom xs start
  else if (Center.window? xs start (start+3)).isSome then some start else none

/-- 进位块的边界由重启策略决定；等待后核的策略只认第一个后核。 -/
def nineEnd? (p : CarryNineParams) (xs : List (Seg P)) (seed : Nat) : Option Nat :=
  if !nineAt xs seed then none
  else match p.restart with
  | .afterNine | .entryAfterCarry => some (seed+9)
  | .atNextSeed => firstSeedFrom xs (seed+9)

/-- 从最近块首沿逆序历史还原前块的实际起核搜索位置。若前块以九段进位闭合，
为当前块留一个进入段；普通入口已要求进入段时不再叠加。 -/
def carryStart (p : CarryNineParams) (xs : List (Seg P)) (past : List Nat) (i : Nat) : Nat :=
  if p.entry == .requireEntry then i + 1
  else match p.restart, past with
    | .entryAfterCarry, prev :: earlier =>
      let priorNine := (carrySeed? p xs (carryStart p xs earlier prev)).any fun n =>
        n + 9 == i && nineAt xs n
      if priorNine then i + 1 else i
    | _, _ => i
termination_by structural past

/-- 普通块与升级块均可合法；升级只使用在块尾已经出现的证据。
九段满足进位几何时，普通块须在九段前结束；三凸包不相交时则继续按普通时机封块。 -/
def carryClass (p : CarryNineParams) (xs : List (Seg P)) (past : List Nat) (i j : Nat) : Option Nat := do
  let seed ← carrySeed? p xs (carryStart p xs past i)
  if j > xs.length || j < seed + 3 then none else
    let nine := nineEnd? p xs seed == some j
    let pullback := (List.range 7).any fun n =>
      match Center.window? xs seed (seed+3+n) with
      | none => false
      | some z => returningCenter xs z j true (some 9)
    if nine || pullback then some 1
    else if j ≥ seed + 9 && nineAt xs seed then none
    else match p.timing with
    | .seeded => if j == seed + 3 then some 0 else none
    | .coreBroken =>
      match Center.window? xs seed j, xs[j]? with
      | some z, some leave => if decide (¬ z.extendsWith leave) then some 0 else none
      | _, _ => none
    | .thirdEvent =>
      if thirdEventEnd? xs seed == some j then some 0 else none

/-- 优先确立的升级占优；其他升级和普通成块仍可作为合法分解。 -/
def carryScore (p : CarryNineParams) (xs : List (Seg P)) (past : List Nat) (i j : Nat) : Option Nat :=
  match carryClass p xs past i j with
  | some 1 => some (if (List.range j).any (fun t => carryClass p xs past i t == some 1) then 1 else 2)
  | other => other

/-- 显式选择三处策略；波动回拉和九段路径共享占优次序。

[057:42] 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。这一点其实由6这个第三类卖点的存在以及后面的背驰，就可以知道，这中枢级别的扩展，是必然的。
[020:44] 缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。
-/
def carryNineRule (p : CarryNineParams) : BlockRule where
  rank _ xs past i j := carryScore p xs past i j
  confirmed _ xs past i j := carryScore p xs past i j == some 2

end Chan.Defs.Level
