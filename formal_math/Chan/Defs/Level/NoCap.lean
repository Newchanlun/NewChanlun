module

public import Chan.Defs.Level.CarryNine

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Alt
variable {P : Type _} [LinearOrder P]

/-- 已触核的段可无限延伸。延伸结束后，沿固定核逐段检查破坏和后枢扩展，
在首个闭合事件处切分；持续时间不触发进位。
[018:40] 例如一个盘整，三个重叠的连续次级别走势类型后，盘整就可以随时完成，也就是说，只要三个重叠的连续次级别走势类型走出来后，盘整随时结束都是完美的，但这可以不结束，可以不断延伸下去，不断围绕这缠中说禅中枢上上下下地延伸下去直到无穷都是可以的。
[020:34] 一个简单的例子就能区别以上的情况：例如，一个股票开盘立刻封涨停，那么，只能算是一分钟级别上出现了走势中枢的延伸，无论这个延伸有多长时间，都不可能产生更大级别的走势中枢。
[020:44] 缠中说禅走势级别延续定理二：更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个同级别缠中说禅走势中枢产生的波动区间产生重叠。 -/
def completesUncapped (xs : List (Seg P)) (i j : Nat) : Bool :=
  match firstSeedFrom xs i with
  | none => false
  | some seed => (firstBreakOrExpand? xs seed false).map Prod.fst == some j

/-- 不设上限的块语言，与九段实例共享几何判定而不共享进位阈值。
[018:40] 例如一个盘整，三个重叠的连续次级别走势类型后，盘整就可以随时完成，也就是说，只要三个重叠的连续次级别走势类型走出来后，盘整随时结束都是完美的，但这可以不结束，可以不断延伸下去，不断围绕这缠中说禅中枢上上下下地延伸下去直到无穷都是可以的。
[020:34] 一个简单的例子就能区别以上的情况：例如，一个股票开盘立刻封涨停，那么，只能算是一分钟级别上出现了走势中枢的延伸，无论这个延伸有多长时间，都不可能产生更大级别的走势中枢。 -/
def noCapRule : BlockRule where
  rank _ xs _ i j := if completesUncapped xs i j then some 0 else none
  confirmed _ xs _ i j := completesUncapped xs i j

end Chan.Defs.Level
