module

public import Chan.Defs.Level.Rule

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Order Chan.Defs.Alt Chan.Defs.Center
variable {P : Type _} [Std.LinearOrderPackage P]

/-- 三处分支独立选择。重启若另设进入段，则进位后第十段只作进入，第十一段起核；没有隐含默认裁定。
[018:40] 例如一个盘整，三个重叠的连续次级别走势类型后，盘整就可以随时完成，也就是说，只要三个重叠的连续次级别走势类型走出来后，盘整随时结束都是完美的，但这可以不结束，可以不断延伸下去，不断围绕这缠中说禅中枢上上下下地延伸下去直到无穷都是可以的。
[057:42] 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。这一点其实由6这个第三类卖点的存在以及后面的背驰，就可以知道，这中枢级别的扩展，是必然的。
[099:26] 如果后面包括d+e+f延伸出9段，然后又直接上去了，划分中，必须首先保证5分钟中枢的成立。换言之，划分的原则很明确，就是必须保证中枢的确立，在这前提下，可以根据结合律，使得连接中枢的走势保持最完美的形态。 -/
structure CarryNineParams where
  finishAtSeed : Bool
  entryAfterCarry : Bool
  separateEntry : Bool
  deriving DecidableEq

/-- 连续九段围绕同一初核延伸，并检验三个三段凸包的公共交；不要求九段都有一个共同价位。
[057:42] 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。这一点其实由6这个第三类卖点的存在以及后面的背驰，就可以知道，这中枢级别的扩展，是必然的。
[020:56] 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。换言之，若有Zn，使得dn>ZG或gn<ZD，则必然产生高级别的走势中枢或趋势及延续。 -/
def nineAt (xs : List (Seg P)) (i : Nat) : Bool :=
  (Center.window? xs i (i+9)).isSome &&
    match BlockRule.coarsen xs i (i+3), BlockRule.coarsen xs (i+3) (i+6),
          BlockRule.coarsen xs (i+6) (i+9) with
    | some a, some b, some c => decide (overlapsList a.range [b.range,c.range])
    | _, _, _ => false

/-- 离开后的下一个中枢取最早能成核的三段。其波动包络可延伸到 j，须回拉触及前枢波动区间。
[020:44] 缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。
[018:64] 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。 -/
def returningCenter (xs : List (Seg P)) (z : Center P) (j : Nat) (requireThird : Bool) : Bool :=
  match xs[z.stop]? with
  | none => false
  | some leave =>
    let left := match leave.dir with
      | .up => decide (z.leavesUp leave)
      | .down => decide (z.leavesDown leave)
    let first := (List.range (xs.length - z.stop)).map (fun n => z.stop + 1 + n)
    left && (!requireThird || z.destroyed xs) &&
      match first.find? (fun n => (Center.window? xs n (n+3)).isSome) with
      | none => false
      | some n =>
        match Center.window? xs n j with
        | some next => decide (overlaps z.zone.hull next.zone.hull)
        | none => false

/-- 两类升级都优先于普通成块。同一优先级取最早确立的位置，不等待任意后延的再划分。
[057:42] 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。这一点其实由6这个第三类卖点的存在以及后面的背驰，就可以知道，这中枢级别的扩展，是必然的。
[099:26] 如果后面包括d+e+f延伸出9段，然后又直接上去了，划分中，必须首先保证5分钟中枢的成立。换言之，划分的原则很明确，就是必须保证中枢的确立，在这前提下，可以根据结合律，使得连接中枢的走势保持最完美的形态。 -/
def carryClass (p : CarryNineParams) (xs : List (Seg P)) (past : List Nat) (i j : Nat) : Option Nat :=
  let afterNine := match past with
    | [] => false
    | prev :: _ => decide (prev + 9 ≤ i ∧ i ≤ prev + 10) && nineAt xs (i-9)
  let seed := i + (if p.separateEntry || (p.entryAfterCarry && afterNine) then 1 else 0)
  if j > xs.length || j < seed + 3 then none else
    let nine := j == seed + 9 && nineAt xs seed
    let pullback := (List.range (min 9 (j-seed))).any fun n =>
      let stop := seed + n
      match Center.window? xs seed stop with
      | none => false
      | some z => returningCenter xs z j true
    if nine || pullback then some 1
    else if p.finishAtSeed then
      if j == seed + 3 && (Center.window? xs seed j).isSome then some 0 else none
    else if j ≤ seed+8 then
      match Center.window? xs seed j with
      | some z => if z.destroyed xs then some 0 else none
      | none => none
    else none

/-- 先确立的高级别中枢优先；优先级不随以后追加的段数重编号。
[099:26] 如果后面包括d+e+f延伸出9段，然后又直接上去了，划分中，必须首先保证5分钟中枢的成立。换言之，划分的原则很明确，就是必须保证中枢的确立，在这前提下，可以根据结合律，使得连接中枢的走势保持最完美的形态。 -/
def carryScore (p : CarryNineParams) (xs : List (Seg P)) (past : List Nat) (i j : Nat) : Option Nat :=
  match carryClass p xs past i j with
  | some 1 => some (if (List.range j).any (fun t => carryClass p xs past i t == some 1) then 1 else 2)
  | other => other

/-- 规范进位实例。未冻结的三项由调用者给出；九段与离开回拉均可在同一块首赢得优先权。
[057:42] 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。这一点其实由6这个第三类卖点的存在以及后面的背驰，就可以知道，这中枢级别的扩展，是必然的。
[020:44] 缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。
[099:26] 如果后面包括d+e+f延伸出9段，然后又直接上去了，划分中，必须首先保证5分钟中枢的成立。换言之，划分的原则很明确，就是必须保证中枢的确立，在这前提下，可以根据结合律，使得连接中枢的走势保持最完美的形态。 -/
def carryNineRule (p : CarryNineParams) : BlockRule where
  rank _ xs past i j := carryScore p xs past i j
  confirmed _ xs past i j :=
    carryScore p xs past i j == some 2

end Chan.Defs.Level
