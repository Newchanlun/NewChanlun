module

public import Chan.Defs.Level.Tower

/-!
# M15 阶段状态机

围绕前一走势类型的转折点与其后新同级中枢划分三阶段（清单 B-13）：中阴阶段（仅此阶段有
第一、二类买卖点）、中枢震荡阶段（有中枢震荡买卖点）、离开阶段（有第三类买卖点）。
阶段判定显式接收分解（级别塔）参数（清单 B-4）。
-/

@[expose] public section

namespace Chan.Defs.Signal

open Chan.Defs.Order Chan.Defs.Alt Chan.Defs.Center Chan.Defs.Level

universe u

/-- 三阶段状态：中阴、中枢震荡、离开。

[101:42]
> 注意，只有在这回升的中阴状态下才有第一、二类买点，中阴状态结束后，所有的中枢震荡只存在第三类买卖点以及中枢震荡的买卖点，就不存在第一、二类买卖点了。
-/
inductive Phase where
  /-- 中阴阶段：转折后、新同级中枢尚未确立。 -/
  | zhongYin
  /-- 中枢震荡阶段：新同级中枢已确立，走势仍与其核闭重叠。 -/
  | oscillation
  /-- 离开阶段：走势已出现首个不与核重叠的段。 -/
  | leaving
  deriving DecidableEq

variable {P : Type u} [LinearOrder P]

/-- 本级段序列上的阶段判定：`turn` 为前一走势类型结束段（转折点所在段）下标，`k` 为当前段下标。
新中枢为 `turn` 之后首个成核位置 `s`；`k < s + 2`（第三段尚未走完）为中阴；
其后在延伸覆盖范围内为中枢震荡；超出为离开。

[099:34]
> 首先，任何一个后续的更大级别中枢震荡，必然至少要落在前一走势类型的最后一个中枢范围里，这是一个必然结论。

[099:16]
> 中阴的存在恰好客观地反映了走势的这种特性。
-/
def phaseOf (segs : List (Seg P)) (turn k : Nat) : Phase :=
  match firstSeedFrom segs (turn + 1) with
  | none => Phase.zhongYin
  | some s =>
    if k < s + 2 then Phase.zhongYin
    else if k < s + seedRunLen segs s then Phase.oscillation
    else Phase.leaving

/-- 结合分解（级别塔 `t` 与级别 `lvl`）与位置判定当前阶段。

[101:42]
> 注意，只有在这回升的中阴状态下才有第一、二类买点，中阴状态结束后，所有的中枢震荡只存在第三类买卖点以及中枢震荡的买卖点，就不存在第一、二类买卖点了。

[054:58]
> 相应的5分钟中枢区间就是[d3，g5]，在这种情况下，d7g7也是一个中枢震荡，但不构成第三类卖点，因为不符合条件。
-/
def phaseAt {r : BlockRule.{u}} {base : List (Seg P)} (t : LevelTower r base)
    (lvl turn k : Nat) : Phase :=
  phaseOf (t.levelSeq lvl) turn k

end Chan.Defs.Signal
