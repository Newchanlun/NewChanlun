module

public import Chan.Defs.Level.Rule

/-!
# M7 规范进位实例

`#2318` 留待 `#2296` 冻结的三处原文未定分支显式参数化。两条升级途径：
九段 `3+3+3` 进位在本级直接截块；离开回拉的波动区间重叠升级由上一级对凸包值域的
成核判定自然承接（上级段保留凸包值域，故同级两中枢波动区间重叠即上级三段可成核）。
-/

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Order Chan.Defs.Alt Chan.Defs.Center

universe u

/-- 分支 A：块完成时机。`coreBroken`：核被破坏（出现首个不与核重叠的段）才完成；
`seeded`：三段成核即完成。

[018:40]
> 例如一个盘整，三个重叠的连续次级别走势类型后，盘整就可以随时完成，也就是说，只要三个重叠的连续次级别走势类型走出来后，盘整随时结束都是完美的，但这可以不结束，可以不断延伸下去，不断围绕这缠中说禅中枢上上下下地延伸下去直到无穷都是可以的。
-/
inductive CompletionTiming where
  /-- 核被破坏才完成。 -/
  | coreBroken
  /-- 三段成核即完成。 -/
  | seeded
  deriving DecidableEq

/-- 分支 B：九段进位后的重启策略。`afterNine`：块止于第九段末，自第十段重新起核；
`atNextSeed`：块延续到第九段之后第一个能成核的位置。

[057:42]
> 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。

[二级旁证 066:186]
> 不一定。按3+3+3这样组合后确定5分钟的。
-/
inductive RestartPolicy where
  /-- 自第十段重新起核。 -/
  | afterNine
  /-- 延续到下一个成核位置。 -/
  | atNextSeed
  deriving DecidableEq

/-- 分支 C：成核三段与进入段约定。`mayIncludeFirst`：成核三段可含块首段；
`requireEntry`：块首段为独立进入段，成核三段自第二段起搜索。

[018:24]
> 注意，次级别的前三个走势类型都是完成的才构成该级别的缠中说禅走势中枢，完成的走势类型
-/
inductive SeedConvention where
  /-- 成核三段可含块首段。 -/
  | mayIncludeFirst
  /-- 要求独立进入段。 -/
  | requireEntry
  deriving DecidableEq

/-- 规范进位的三处显式参数。

[099:26]
> 如果后面包括d+e+f延伸出9段，然后又直接上去了，划分中，必须首先保证5分钟中枢的成立。换言之，划分的原则很明确，就是必须保证中枢的确立，在这前提下，可以根据结合律，使得连接中枢的走势保持最完美的形态。
-/
structure CarryNineParams where
  /-- 分支 A。 -/
  timing : CompletionTiming
  /-- 分支 B。 -/
  restart : RestartPolicy
  /-- 分支 C。 -/
  seed : SeedConvention
  deriving DecidableEq

/-- 一组占位参数（待 `#2296` 冻结时拍定，非裁定默认值）。

[099:26]
> 换言之，划分的原则很明确，就是必须保证中枢的确立，在这前提下，可以根据结合律，使得连接中枢的走势保持最完美的形态。
-/
def CarryNineParams.placeholder : CarryNineParams :=
  ⟨CompletionTiming.coreBroken, RestartPolicy.afterNine, SeedConvention.mayIncludeFirst⟩

/-- 按成核约定确定成核搜索起点。

[018:24]
> 注意，次级别的前三个走势类型都是完成的才构成该级别的缠中说禅走势中枢，完成的走势类型
-/
def seedSearchStart : SeedConvention → Nat → Nat
  | SeedConvention.mayIncludeFirst, i => i
  | SeedConvention.requireEntry, i => i + 1

/-- 规范进位块终点：自块起点 `i` 找首个成核位置 `s`；若延伸满九段，优先按 `3+3+3` 进位截块
（优先确立高一级中枢）；否则按完成时机，在三段成核处或核被破坏处截块；尚未完成则无终点。

[099:26]
> 如果后面包括d+e+f延伸出9段，然后又直接上去了，划分中，必须首先保证5分钟中枢的成立。换言之，划分的原则很明确，就是必须保证中枢的确立，在这前提下，可以根据结合律，使得连接中枢的走势保持最完美的形态。

[020:44]
> 缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。

[二级旁证 095:86]
> 次好的，就是在这里形成5分钟中枢后再出现第三类买点，这里有两种途径，一种是9次级别的震荡扩展出5分钟，一种是先1分钟的第三类卖点后底背驰上来再出来5分钟。这里就构成了N次必然的短线机会。
-/
def carryBlockEnd {Q : Type u} [LinearOrder Q] (p : CarryNineParams) (ctx : List (Seg Q))
    (i : Nat) : Option Nat :=
  match firstSeedFrom ctx (seedSearchStart p.seed i) with
  | none => none
  | some s =>
    if 9 ≤ seedRunLen ctx s then
      (match p.restart with
        | RestartPolicy.afterNine => some (s + 9)
        | RestartPolicy.atNextSeed => firstSeedFrom ctx (s + 9))
    else
      (match p.timing with
        | CompletionTiming.seeded => some (s + 3)
        | CompletionTiming.coreBroken =>
          if s + seedRunLen ctx s < ctx.length then some (s + seedRunLen ctx s) else none)

/-- 规范进位块判定：`[i, j)` 被接受当且仅当 `carryBlockEnd` 自 `i` 给出终点 `j`。

[057:42]
> 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。
-/
def carryAccepts {Q : Type u} [LinearOrder Q] (p : CarryNineParams) (ctx : List (Seg Q))
    (i j : Nat) : Bool :=
  decide (carryBlockEnd p ctx i = some j)

/-- 规范进位块规则实例：支持九段 `3+3+3` 升级与离开回拉波动区间重叠升级，
按优先确立高一级中枢择优。

[020:40]
> 缠中说禅走势级别延续定理一：在更大级别缠中说禅走势中枢产生前，该级别走势类型将延续。也就是说，只能是只具有该级别缠中说禅走势中枢的盘整或趋势的延续。

[二级旁证 069:423]
> 5分钟中枢，只要3个1分钟走势类型有重合就可以，不是一定要里面的所有段都重合。
-/
def carryNineRule (p : CarryNineParams) : BlockRule.{u} where
  accepts := fun ctx i j => carryAccepts p ctx i j
  blockDir := fun ctx => firstDir ctx

end Chan.Defs.Level
