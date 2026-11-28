module

public import Chan.Defs.Level.Rule

/-!
# M8 不设延伸上限的对照规则实例

单一中枢可无限延伸，仅在核被破坏（出现首个不与核重叠的段）时截块；不设九段强制进位。
波动区间重叠升级由上一级对凸包值域的成核判定承接。
-/

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Alt Chan.Defs.Center

universe u

/-- 不设上限块终点：自 `i` 找首个成核位置 `s`，延伸到核被破坏处截块；未破坏则尚无终点。

[018:40]
> 例如一个盘整，三个重叠的连续次级别走势类型后，盘整就可以随时完成，也就是说，只要三个重叠的连续次级别走势类型走出来后，盘整随时结束都是完美的，但这可以不结束，可以不断延伸下去，不断围绕这缠中说禅中枢上上下下地延伸下去直到无穷都是可以的。
-/
def noCapBlockEnd {Q : Type u} [LinearOrder Q] (ctx : List (Seg Q)) (i : Nat) : Option Nat :=
  match firstSeedFrom ctx i with
  | none => none
  | some s => if s + seedRunLen ctx s < ctx.length then some (s + seedRunLen ctx s) else none

/-- 不设上限块判定：`[i, j)` 被接受当且仅当 `noCapBlockEnd` 自 `i` 给出终点 `j`。

[020:34]
> 一个简单的例子就能区别以上的情况：例如，一个股票开盘立刻封涨停，那么，只能算是一分钟级别上出现了走势中枢的延伸，无论这个延伸有多长时间，都不可能产生更大级别的走势中枢。
-/
def noCapAccepts {Q : Type u} [LinearOrder Q] (ctx : List (Seg Q)) (i j : Nat) : Bool :=
  decide (noCapBlockEnd ctx i = some j)

/-- 不设延伸上限的对照规则实例。

[020:34]
> 一个简单的例子就能区别以上的情况：例如，一个股票开盘立刻封涨停，那么，只能算是一分钟级别上出现了走势中枢的延伸，无论这个延伸有多长时间，都不可能产生更大级别的走势中枢。
-/
def noCapRule : BlockRule.{u} where
  accepts := fun ctx i j => noCapAccepts ctx i j
  blockDir := fun ctx => firstDir ctx

end Chan.Defs.Level
