module

public import Chan.Defs.Level.Rule

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Order Chan.Defs.Alt Chan.Defs.Center
variable {P : Type _} [LinearOrder P]

/-- #2320 裁定三：九段以前默认在首个脱核段处截块，三段成核档只作对照。 -/
inductive TimingPolicy where
  | seeded | coreBroken
  deriving DecidableEq

/-- 进位后从该块的右开边界重新起算，不额外留进入段。 -/
inductive RestartPolicy where
  | afterNine
  deriving DecidableEq

/-- 九段前的起核是否必须在独立进入段之后。 -/
inductive EntryPolicy where
  | mayIncludeFirst | requireEntry
  deriving DecidableEq

/-- 进位规则的三轴参数；前导搜索可以关闭。

[057:42] 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。这一点其实由6这个第三类卖点的存在以及后面的背驰，就可以知道，这中枢级别的扩展，是必然的。
-/
structure CarryNineParams where
  timing : TimingPolicy
  restart : RestartPolicy
  entry : EntryPolicy
  searchLead : Bool
  deriving DecidableEq

/-- #2320 冻结默认：单段脱核，九段后重启，可含首段，搜索前导段。 -/
def CarryNineParams.default : CarryNineParams := ⟨.coreBroken, .afterNine, .mayIncludeFirst, true⟩

/-- 独立进入段若已触核，连续延伸可比九段封顶多一段。 -/
def CarryNineParams.carryBound (p : CarryNineParams) : Nat :=
  match p.entry with | .mayIncludeFirst => 9 | .requireEntry => 10

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
    let dir := CoarseDirPolicy.firstSegment
    match BlockRule.coarsen xs i (i+3) dir, BlockRule.coarsen xs (i+3) (i+6) dir,
          BlockRule.coarsen xs (i+6) (i+9) dir with
    | some a, some b, some c => decide (overlapsList a.range [b.range,c.range])
    | _, _, _ => false

/-- 途径二：前后枢的核分离、波动区间相交。

[020:44] 缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。
[二级旁证 095:86] 次好的，就是在这里形成5分钟中枢后再出现第三类买点，这里有两种途径，一种是9次级别的震荡扩展出5分钟，一种是先1分钟的第三类卖点后底背驰上来再出来5分钟。这里就构成了N次必然的短线机会。
-/
def expandsWith (z next : Center P) : Bool :=
  match relPos z.zone next.zone with
  | .expansionUp | .expansionDown => true
  | _ => false

/-- 只看离开后首个成核的中枢；波动相交可以在该枢延伸时确立。 -/
def hasExpansionAfter (xs : List (Seg P)) (z : Center P) (k : Nat) : Bool :=
  match firstSeedFrom xs (k + 1) with
  | none => false
  | some n => (List.range (extRun xs n - 2)).any fun extra =>
    (Center.window? xs n (n + 3 + extra)).any (expandsWith z)

/-- 从最大延伸前枢的末段起，按固定核逐段找首个闭合事件。
连续离开计入块内，跳空离开从下一块起算；标志位说明该离开之后是否出现扩展后枢。
不要求第三类事件时，同一位置的越核离开也可由扩展后枢确认为闭合。 -/
def firstBreakOrExpand? (xs : List (Seg P)) (seed : Nat)
    (requireThird : Bool) : Option (Nat × Bool) := do
  let z ← Center.window? xs seed (seed + extRun xs seed)
  let next ← xs[z.stop]?
  if decide (z.extendsWith next) then none else
    let start := z.stop - 1
    ((List.range (xs.length - start)).map (start + ·)).findSome? fun k => do
      let leave ← xs[k]?
      let back ← xs[k+1]?
      -- 回试起笔确定衔接的离开侧。在底层该侧等于 leave.dir；
      -- 上层偶数离开块的起笔可能相反。
      let (crosses, gap, third) := match back.dir.flip with
        | .up => (decide (z.core.hi < leave.range.hi), decide (z.leavesUp leave),
            decide (z.thirdBuyEvent leave back))
        | .down => (decide (leave.range.lo < z.core.lo), decide (z.leavesDown leave),
            decide (z.thirdSellEvent leave back))
      let cutEnd := if gap then k else k + 1
      if third then some (cutEnd, hasExpansionAfter xs z k)
      else if !requireThird && crosses && hasExpansionAfter xs z k then some (cutEnd, true)
      else none

/-- 按证据完成时刻扫描：从短到长逐个检查前缀，返回首个闭合事件。
延拓不改变已检查的前缀，因此唯一的首个命中不会被后来完成的证据撤销。 -/
def firstOnlineBreakOrExpand? (xs : List (Seg P)) (seed : Nat)
    (requireThird : Bool) : Option (Nat × Bool) :=
  (List.range (xs.length + 1)).findSome? fun t =>
    firstBreakOrExpand? (xs.take t) seed requireThird

/-- 途径二在块尾取证，前后枢各至多九段。块尾之后的段不能补造升级证据。 -/
def earlyTimingPullback (xs : List (Seg P)) (seed j : Nat) : Bool :=
  let xs := xs.take j
  (List.range 7).any fun extra =>
    match Center.window? xs seed (seed + 3 + extra) with
    | none => false
    | some z =>
      ((z.departureIndex? .up xs <|> z.departureIndex? .down xs).bind
        (fun k => firstSeedFrom xs (k + 1))).any fun n =>
        (Center.window? xs n j).any fun next =>
          decide (next.cover.length ≤ 9) && expandsWith z next

/-- 普通入口的第一成核点。 -/
def carrySeed? (p : CarryNineParams) (xs : List (Seg P)) (start : Nat) : Option Nat :=
  if p.searchLead then firstSeedFrom xs start
  else if (Center.window? xs start (start+3)).isSome then some start else none

/-- 九段进位的右开边界；无需等待后核。 -/
def nineEnd? (p : CarryNineParams) (xs : List (Seg P)) (seed : Nat) : Option Nat :=
  if !nineAt xs seed then none
  else match p.restart with
  | .afterNine => some (seed+9)

/-- 独立进入段不参与首核搜索；入口不依赖前块类别。 -/
def carryStart (p : CarryNineParams) (i : Nat) : Nat :=
  if p.entry == .requireEntry then i + 1 else i

/-- #2320 封顶：延伸满九段必截，三凸包是否相交只决定该块是否升级。
未满九段时保留途径二，且合并前后枢的块也须满足块内单核延伸界。 -/
def carryClass (p : CarryNineParams) (xs : List (Seg P)) (_past : List Nat)
    (i j : Nat) : Option Nat := do
  let seed ← carrySeed? p xs (carryStart p i)
  if j > xs.length || j < seed + 3 then none else
    let cap := seed + 9
    if cap ≤ j && (Center.window? xs seed cap).isSome then
      if j != cap then none
      else if nineEnd? p xs seed == some j then some 1 else some 0
    else if earlyTimingPullback xs seed j && blockExtWithin p.carryBound (xs.extract i j) then some 1
    else if cap ≤ j then none
    else match p.timing with
      | .seeded => if j == seed + 3 then some 0 else none
      | .coreBroken =>
        match Center.window? xs seed j, xs[j]? with
        | some z, some leave => if decide (¬ z.extendsWith leave) then some 0 else none
        | _, _ => none

/-- 块在完整九段处封顶后，后续回拉不能再改写该切点。 -/
def atCarryCap (p : CarryNineParams) (xs : List (Seg P)) (i j : Nat) : Bool :=
  (carrySeed? p xs (carryStart p i)).any fun seed =>
    j == seed + 9 && (Center.window? xs seed j).isSome

/-- 优先确立的升级占优；其他升级和普通成块仍可作为合法分解。 -/
def carryScore (p : CarryNineParams) (xs : List (Seg P)) (past : List Nat) (i j : Nat) : Option Nat :=
  match carryClass p xs past i j with
  | some 1 => some (if (List.range j).any (fun t => carryClass p xs past i t == some 1) then 1 else 2)
  | some 0 => some (if p.timing == .seeded && atCarryCap p xs i j then 1 else 0)
  | _ => none

/-- 显式选择三处策略；波动回拉和九段路径共享占优次序。
首个升级和占优的九段封顶块可确认。九段前的普通候选仍可能让位于途径二，不先确认。

[057:42] 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。这一点其实由6这个第三类卖点的存在以及后面的背驰，就可以知道，这中枢级别的扩展，是必然的。
[020:44] 缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。
-/
def carryNineRule (p : CarryNineParams) : BlockRule where
  rank _ xs past i j := carryScore p xs past i j
  confirmed _ xs past i j :=
    carryScore p xs past i j == some 2 ||
      (atCarryCap p xs i j &&
        !(List.range j).any (fun t => carryClass p xs past i t == some 1))

end Chan.Defs.Level
