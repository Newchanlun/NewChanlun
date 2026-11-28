module

public import Chan.Defs.Signal.Phase
public import Chan.Defs.Level.TrendType

/-!
# M15 买卖点谓词族

全部买卖点谓词显式接收分解参数（级别塔 `t` 与级别 `lvl`），不假定分解唯一（清单 B-4）。
力度/背驰通过抽象参数 `StrengthJudge` 接入，不依赖任何具体指标（分叉 3）。
第三类买卖点保持纯结构定义，严格越过核边界，不加底部特判（清单 B-11、B-14，分叉 4）。
-/

@[expose] public section

namespace Chan.Defs.Signal

open Chan.Defs.Order Chan.Defs.Alt Chan.Defs.Center Chan.Defs.Level

universe u

/-- 抽象力度/背驰判定参数：`diverges segs c a k` 判定在段序列 `segs` 中、相对中枢 `c`，
进入段 `a` 与离开段 `k` 相比是否力度减弱（背驰）。不绑定任何具体指标。

[053:28]
> 第一类买卖点，就是该级别的背驰点，这足以应付最大多数的情况，但有一种情况是不可以的，就是前面反复强调的小级别转大级别的情况。
-/
structure StrengthJudge (P : Type u) [LinearOrder P] where
  /-- 背驰判定。 -/
  diverges : List (Seg P) → Center P → Nat → Nat → Bool

/-- 第二类买（卖）点强弱三分。`merged`：二三买合一（最强）；`rising`：一二三买依次抬高；
`weak`：二买跌破或触及一买。卖点按对偶解释。

[101:28]
> 第二类买点刚好构成原来下跌的最后一个中枢开始的震荡走势的第三类买点，也就是第二、三类买点合一了，这是最强的走势，这情况，一般都对应V型反转的快速回升，是最有力度的。

[101:32]
> 第二类买点跌破第一类买点，也就是第二类买点比第一类买点低，这是完全可以的，这里一般都构成盘整背驰

[101:38]
> 这种情况下，第一、二、三买点，是依次向上，一个比一个高。
-/
inductive SecondStrength where
  /-- 二三买合一。 -/
  | merged
  /-- 依次抬高。 -/
  | rising
  /-- 跌破或触及一买。 -/
  | weak
  deriving DecidableEq

variable {P : Type u} [LinearOrder P] {r : BlockRule.{u}} {base : List (Seg P)}

/-- 对下标 `k` 处的段施加布尔判别（越界为假）。

[053:20]
> 就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。
-/
def segAt (segs : List (Seg P)) (k : Nat) (f : Seg P → Bool) : Bool :=
  match List.drop k segs with
  | s :: _ => f s
  | [] => false

/-- 对下标 `k`、`k+1` 处的相邻两段施加布尔判别（越界为假）。

[020:62]
> 但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。
-/
def onPair (segs : List (Seg P)) (k : Nat) (f : Seg P → Seg P → Bool) : Bool :=
  match List.drop k segs with
  | a :: b :: _ => f a b
  | _ => false

/-- 两段的突破后回试几何条件：向上时，`a` 向上且高点严格越过 `bound`，紧随的 `b` 向下且低点
严格高于 `bound`（不触及）；向下对称。

[054:24]
> 而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。
-/
def breakoutPair (d : Dir) (bound : P) (a b : Seg P) : Prop :=
  (d = Dir.up ∧ a.dir = Dir.up ∧ bound < a.range.hi ∧ b.dir = Dir.down ∧ bound < b.range.lo) ∨
  (d = Dir.down ∧ a.dir = Dir.down ∧ a.range.lo < bound ∧ b.dir = Dir.up ∧ b.range.hi < bound)

/-- `breakoutPair` 可判定。

[054:24]
> 而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。
-/
instance instDecidableBreakoutPair (d : Dir) (bound : P) (a b : Seg P) :
    Decidable (breakoutPair d bound a b) := by
  unfold breakoutPair; infer_instance

/-- 通用突破后首次回试：剥离中枢归属的纯几何模板，下标 `k` 段突破边界 `bound`，
紧随的下标 `k+1` 段（首次反向段）不触及该边界。

[020:62]
> 注意，第三类买卖点比第一、二类要后知后觉，但如果抓得好，往往不用浪费盘整的时间，比较适合短线技术较好的资金，但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。
-/
def BreakoutRetest (d : Dir) (bound : P) (segs : List (Seg P)) (k : Nat) : Prop :=
  onPair segs k (fun a b => decide (breakoutPair d bound a b)) = true

/-- `BreakoutRetest` 可判定。

[020:62]
> 但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。
-/
instance instDecidableBreakoutRetest (d : Dir) (bound : P) (segs : List (Seg P)) (k : Nat) :
    Decidable (BreakoutRetest d bound segs k) := by
  unfold BreakoutRetest; infer_instance

/-- 第一类买点：分解 `t` 第 `lvl` 级上，`prev ++ [c]` 构成下跌趋势，`c` 为最后中枢；
下标 `k` 段位于 `c` 覆盖范围之后、向下且低点严格低于 `DD`（离开最后中枢的 c 段创新低）；
抽象背驰判定以进入段 `c.first - 1` 与离开段 `k` 成立。

[017:60]
> 因为某种类型的走势完成以后就会转化为其他类型的走势，对于下跌的走势来说，一旦完成，只能转化为上涨与盘整，因此，一旦能把握下跌走势转化的关节点买入，就在市场中占据了一个最有利的位置，而这个买点，就是前面反复强调的“第一类买点”；

[101:20]
> 第一类买卖点就是背驰点，第三类买卖点就是中枢破坏点，这都是很清楚的。
-/
def isFirstBuy (t : LevelTower r base) (lvl : Nat) (judge : StrengthJudge P)
    (prev : List (Center P)) (c : Center P) (k : Nat) : Prop :=
  classifyTrend (prev ++ [c]) = some TrendKind.downTrend ∧
  c.WellFormed (t.levelSeq lvl) ∧
  c.first + c.count ≤ k ∧
  segAt (t.levelSeq lvl) k (fun s => decide (s.dir = Dir.down ∧ s.range.lo < c.dd)) = true ∧
  judge.diverges (t.levelSeq lvl) c (c.first - 1) k = true

/-- `isFirstBuy` 可判定。

[017:70]
> “缠中说禅趋势转折定律”：任何级别的上涨转折都是由某级别的第一类卖点构成的；任何的下跌转折都是由某级别的第一类买点构成的。
-/
instance instDecidableIsFirstBuy (t : LevelTower r base) (lvl : Nat) (judge : StrengthJudge P)
    (prev : List (Center P)) (c : Center P) (k : Nat) :
    Decidable (isFirstBuy t lvl judge prev c k) := by
  unfold isFirstBuy; infer_instance

/-- 第一类卖点（对偶）：`prev ++ [c]` 构成上涨趋势；下标 `k` 段位于 `c` 之后、向上且高点严格
高于 `GG`；抽象背驰判定成立。

[017:70]
> “缠中说禅趋势转折定律”：任何级别的上涨转折都是由某级别的第一类卖点构成的；任何的下跌转折都是由某级别的第一类买点构成的。

[053:28]
> 第一类买卖点，就是该级别的背驰点，这足以应付最大多数的情况，但有一种情况是不可以的，就是前面反复强调的小级别转大级别的情况。
-/
def isFirstSell (t : LevelTower r base) (lvl : Nat) (judge : StrengthJudge P)
    (prev : List (Center P)) (c : Center P) (k : Nat) : Prop :=
  classifyTrend (prev ++ [c]) = some TrendKind.upTrend ∧
  c.WellFormed (t.levelSeq lvl) ∧
  c.first + c.count ≤ k ∧
  segAt (t.levelSeq lvl) k (fun s => decide (s.dir = Dir.up ∧ c.gg < s.range.hi)) = true ∧
  judge.diverges (t.levelSeq lvl) c (c.first - 1) k = true

/-- `isFirstSell` 可判定。

[017:70]
> “缠中说禅趋势转折定律”：任何级别的上涨转折都是由某级别的第一类卖点构成的；任何的下跌转折都是由某级别的第一类买点构成的。
-/
instance instDecidableIsFirstSell (t : LevelTower r base) (lvl : Nat) (judge : StrengthJudge P)
    (prev : List (Center P)) (c : Center P) (k : Nat) :
    Decidable (isFirstSell t lvl judge prev c k) := by
  unfold isFirstSell; infer_instance

/-- 第二类买点（版本四）：下标 `k` 为第一类买点段；其后 `k+1` 段向上（次级别回抽），
`k+2` 段向下（再次回试），买点为 `k+2` 段结束点，且该位置处于中阴阶段（以 `k` 为转折段）。

[101:22]
> 其实，所谓第二类买点，就是第一类买点的次级别回抽结束后再次探底或回试的那个次级别走势的结束点。这个定义在前面说得很清楚。

[057:40]
> 如果那7当成是第一类买点，那么9就是第二类买点了，这符合次级别上，次级别下，不创新低或盘整背驰的定义，对比一下2点和9点，一卖一买，都是第二类的。
-/
def isSecondBuy (t : LevelTower r base) (lvl : Nat) (judge : StrengthJudge P)
    (prev : List (Center P)) (c : Center P) (k : Nat) : Prop :=
  isFirstBuy t lvl judge prev c k ∧
  segAt (t.levelSeq lvl) (k + 1) (fun s => decide (s.dir = Dir.up)) = true ∧
  segAt (t.levelSeq lvl) (k + 2) (fun s => decide (s.dir = Dir.down)) = true ∧
  phaseAt t lvl k (k + 2) = Phase.zhongYin

/-- `isSecondBuy` 可判定。

[101:22]
> 其实，所谓第二类买点，就是第一类买点的次级别回抽结束后再次探底或回试的那个次级别走势的结束点。这个定义在前面说得很清楚。
-/
instance instDecidableIsSecondBuy (t : LevelTower r base) (lvl : Nat) (judge : StrengthJudge P)
    (prev : List (Center P)) (c : Center P) (k : Nat) :
    Decidable (isSecondBuy t lvl judge prev c k) := by
  unfold isSecondBuy; infer_instance

/-- 第二类卖点（对偶版本四）：下标 `k` 为第一类卖点段；`k+1` 段向下，`k+2` 段向上，
卖点为 `k+2` 段结束点，且处于中阴阶段。

[017:66]
> “缠中说禅买卖点定律一”：任何级别的第二类买卖点都由次级别相应走势的第一类买点构成。

[057:40]
> 如果那7当成是第一类买点，那么9就是第二类买点了，这符合次级别上，次级别下，不创新低或盘整背驰的定义，对比一下2点和9点，一卖一买，都是第二类的。
-/
def isSecondSell (t : LevelTower r base) (lvl : Nat) (judge : StrengthJudge P)
    (prev : List (Center P)) (c : Center P) (k : Nat) : Prop :=
  isFirstSell t lvl judge prev c k ∧
  segAt (t.levelSeq lvl) (k + 1) (fun s => decide (s.dir = Dir.down)) = true ∧
  segAt (t.levelSeq lvl) (k + 2) (fun s => decide (s.dir = Dir.up)) = true ∧
  phaseAt t lvl k (k + 2) = Phase.zhongYin

/-- `isSecondSell` 可判定。

[017:66]
> “缠中说禅买卖点定律一”：任何级别的第二类买卖点都由次级别相应走势的第一类买点构成。
-/
instance instDecidableIsSecondSell (t : LevelTower r base) (lvl : Nat) (judge : StrengthJudge P)
    (prev : List (Center P)) (c : Center P) (k : Nat) :
    Decidable (isSecondSell t lvl judge prev c k) := by
  unfold isSecondSell; infer_instance

/-- 第二类买点强弱分类（`k` 为一买段，`c` 为原下跌最后中枢）：二买低点严格高于 `ZG` 为二三买合一；
否则严格高于一买低点为依次抬高；否则（跌破或触及一买）为较弱。段越界时无分类。

[101:28]
> 第二类买点刚好构成原来下跌的最后一个中枢开始的震荡走势的第三类买点，也就是第二、三类买点合一了，这是最强的走势，这情况，一般都对应V型反转的快速回升，是最有力度的。

[101:32]
> 第二类买点跌破第一类买点，也就是第二类买点比第一类买点低，这是完全可以的，这里一般都构成盘整背驰

[101:38]
> 这种情况下，第一、二、三买点，是依次向上，一个比一个高。
-/
def secondBuyStrength (t : LevelTower r base) (lvl : Nat) (c : Center P) (k : Nat) :
    Option SecondStrength :=
  match List.head? (List.drop k (t.levelSeq lvl)), List.head? (List.drop (k + 2) (t.levelSeq lvl)) with
  | some s₁, some s₂ =>
    some (if c.zg < s₂.range.lo then SecondStrength.merged
      else if s₁.range.lo < s₂.range.lo then SecondStrength.rising
      else SecondStrength.weak)
  | _, _ => none

/-- 第二类卖点强弱分类（对偶）：二卖高点严格低于 `ZD` 为二三卖合一；否则严格低于一卖高点为
依次降低；否则为较弱。

[101:28]
> 第二类买点刚好构成原来下跌的最后一个中枢开始的震荡走势的第三类买点，也就是第二、三类买点合一了，这是最强的走势，这情况，一般都对应V型反转的快速回升，是最有力度的。
-/
def secondSellStrength (t : LevelTower r base) (lvl : Nat) (c : Center P) (k : Nat) :
    Option SecondStrength :=
  match List.head? (List.drop k (t.levelSeq lvl)), List.head? (List.drop (k + 2) (t.levelSeq lvl)) with
  | some s₁, some s₂ =>
    some (if s₂.range.hi < c.zd then SecondStrength.merged
      else if s₂.range.hi < s₁.range.hi then SecondStrength.rising
      else SecondStrength.weak)
  | _, _ => none

/-- 第三类买点结构核心（任意给定段序列上）：`c` 与序列一致；离开段 `k` 是 `c` 的覆盖末段
（起于震荡内：与核闭重叠）且高点严格越过 `ZG`；回试段 `k+1` 是覆盖之后的首段（首次回试），
向下且低点严格高于 `ZG`。由于回试段不与核重叠，`c` 即该级别最近一个中枢。

[020:60]
> 一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点

[054:24]
> 当然，如果前面d1>g2，那g2就是第三类卖点了。
-/
def thirdBuyCore (segs : List (Seg P)) (c : Center P) (k : Nat) : Prop :=
  c.WellFormed segs ∧ k + 1 = c.first + c.count ∧
  segAt segs k (fun s => decide (overlaps s.range c.core)) = true ∧
  c.thirdBuyAt segs k = true

/-- `thirdBuyCore` 可判定。

[020:60]
> 一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破ZG，则构成第三类买点
-/
instance instDecidableThirdBuyCore (segs : List (Seg P)) (c : Center P) (k : Nat) :
    Decidable (thirdBuyCore segs c k) := by
  unfold thirdBuyCore; infer_instance

/-- 第三类卖点结构核心（对偶）：离开段向下且低点严格跌破 `ZD`，首次回试段向上且高点严格低于 `ZD`。

[054:24]
> 由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。
-/
def thirdSellCore (segs : List (Seg P)) (c : Center P) (k : Nat) : Prop :=
  c.WellFormed segs ∧ k + 1 = c.first + c.count ∧
  segAt segs k (fun s => decide (overlaps s.range c.core)) = true ∧
  c.thirdSellAt segs k = true

/-- `thirdSellCore` 可判定。

[054:24]
> 而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。
-/
instance instDecidableThirdSellCore (segs : List (Seg P)) (c : Center P) (k : Nat) :
    Decidable (thirdSellCore segs c k) := by
  unfold thirdSellCore; infer_instance

/-- 第三类买点（B-11 全要件）：在分解 `t` 第 `lvl` 级段序列上满足 `thirdBuyCore`。纯结构定义。

[018:64]
> 某级别“缠中说禅走势中枢”的破坏，当且仅当一个次级别走势离开该“缠中说禅走势中枢”后，其后的次级别回抽走势不重新回到该“缠中说禅走势中枢”内。

[020:62]
> 注意，第三类买卖点比第一、二类要后知后觉，但如果抓得好，往往不用浪费盘整的时间，比较适合短线技术较好的资金，但一定要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次。
-/
def isThirdBuy (t : LevelTower r base) (lvl : Nat) (c : Center P) (k : Nat) : Prop :=
  thirdBuyCore (t.levelSeq lvl) c k

/-- `isThirdBuy` 可判定。

[101:20]
> 第一类买卖点就是背驰点，第三类买卖点就是中枢破坏点，这都是很清楚的。
-/
instance instDecidableIsThirdBuy (t : LevelTower r base) (lvl : Nat) (c : Center P) (k : Nat) :
    Decidable (isThirdBuy t lvl c k) := by
  unfold isThirdBuy; infer_instance

/-- 第三类卖点（B-11 全要件，对偶）：在分解 `t` 第 `lvl` 级段序列上满足 `thirdSellCore`。
不塞入底部特判（`086:76` 的情形仍满足本谓词，作审计反例）。

[086:76]
> 而且，必须注意，对于趋势的转折来说，例如上面的1分钟下跌趋势，最后背驰转折后，第一个上去的线段卖点，很有可能刚好形成最后一个1分钟中枢的第三类卖点，这时候，这个卖点，几乎没有任何的操作意义，反而是要考虑下来的那个第二类买点。
-/
def isThirdSell (t : LevelTower r base) (lvl : Nat) (c : Center P) (k : Nat) : Prop :=
  thirdSellCore (t.levelSeq lvl) c k

/-- `isThirdSell` 可判定。

[101:20]
> 第一类买卖点就是背驰点，第三类买卖点就是中枢破坏点，这都是很清楚的。
-/
instance instDecidableIsThirdSell (t : LevelTower r base) (lvl : Nat) (c : Center P) (k : Nat) :
    Decidable (isThirdSell t lvl c k) := by
  unfold isThirdSell; infer_instance

/-- 最低级别类第三类买点：在无次级可分解的基底段序列 `segs` 上，基底段直接充当次级别，
以单段离开加单段回试表达同形条件。

[017:40]
> 对最后不能分解的级别，其缠中说禅走势中枢就不能用“至少三个连续次级别走势类型所重叠”定义，而定义为至少三个该级别单位K线重叠部分。
-/
def isPseudoThirdBuy (segs : List (Seg P)) (c : Center P) (k : Nat) : Prop :=
  thirdBuyCore segs c k

/-- `isPseudoThirdBuy` 可判定。

[017:40]
> 对最后不能分解的级别，其缠中说禅走势中枢就不能用“至少三个连续次级别走势类型所重叠”定义，而定义为至少三个该级别单位K线重叠部分。
-/
instance instDecidableIsPseudoThirdBuy (segs : List (Seg P)) (c : Center P) (k : Nat) :
    Decidable (isPseudoThirdBuy segs c k) := by
  unfold isPseudoThirdBuy; infer_instance

/-- 最低级别类第三类卖点（对偶）。

[017:40]
> 对最后不能分解的级别，其缠中说禅走势中枢就不能用“至少三个连续次级别走势类型所重叠”定义，而定义为至少三个该级别单位K线重叠部分。
-/
def isPseudoThirdSell (segs : List (Seg P)) (c : Center P) (k : Nat) : Prop :=
  thirdSellCore segs c k

/-- `isPseudoThirdSell` 可判定。

[017:40]
> 对最后不能分解的级别，其缠中说禅走势中枢就不能用“至少三个连续次级别走势类型所重叠”定义，而定义为至少三个该级别单位K线重叠部分。
-/
instance instDecidableIsPseudoThirdSell (segs : List (Seg P)) (c : Center P) (k : Nat) :
    Decidable (isPseudoThirdSell segs c k) := by
  unfold isPseudoThirdSell; infer_instance

/-- 中枢震荡买点：分解 `t` 第 `lvl` 级上，位置 `k` 处于中枢震荡阶段（`turn` 为前一走势结束段）；
`c` 与序列一致且覆盖 `k`；`k` 段向下且低点不高于 `ZD`（在核下边界处反转）。

[101:40]
> 那第二类与第三类买点之间的震荡买点，一般就不给特别的名称了，当然，也可以看成是第二类买点，这样，并没有多大的影响。

[101:42]
> 注意，只有在这回升的中阴状态下才有第一、二类买点，中阴状态结束后，所有的中枢震荡只存在第三类买卖点以及中枢震荡的买卖点，就不存在第一、二类买卖点了。
-/
def isOscillationBuy (t : LevelTower r base) (lvl turn : Nat) (c : Center P) (k : Nat) : Prop :=
  phaseAt t lvl turn k = Phase.oscillation ∧ c.WellFormed (t.levelSeq lvl) ∧
  c.first ≤ k ∧ k < c.first + c.count ∧
  segAt (t.levelSeq lvl) k (fun s => decide (s.dir = Dir.down ∧ s.range.lo ≤ c.zd)) = true

/-- `isOscillationBuy` 可判定。

[101:42]
> 注意，只有在这回升的中阴状态下才有第一、二类买点，中阴状态结束后，所有的中枢震荡只存在第三类买卖点以及中枢震荡的买卖点，就不存在第一、二类买卖点了。
-/
instance instDecidableIsOscillationBuy (t : LevelTower r base) (lvl turn : Nat) (c : Center P)
    (k : Nat) : Decidable (isOscillationBuy t lvl turn c k) := by
  unfold isOscillationBuy; infer_instance

/-- 中枢震荡卖点（对偶）：`k` 段向上且高点不低于 `ZG`（在核上边界处反转）。

[101:42]
> 注意，只有在这回升的中阴状态下才有第一、二类买点，中阴状态结束后，所有的中枢震荡只存在第三类买卖点以及中枢震荡的买卖点，就不存在第一、二类买卖点了。
-/
def isOscillationSell (t : LevelTower r base) (lvl turn : Nat) (c : Center P) (k : Nat) : Prop :=
  phaseAt t lvl turn k = Phase.oscillation ∧ c.WellFormed (t.levelSeq lvl) ∧
  c.first ≤ k ∧ k < c.first + c.count ∧
  segAt (t.levelSeq lvl) k (fun s => decide (s.dir = Dir.up ∧ c.zg ≤ s.range.hi)) = true

/-- `isOscillationSell` 可判定。

[101:42]
> 注意，只有在这回升的中阴状态下才有第一、二类买点，中阴状态结束后，所有的中枢震荡只存在第三类买卖点以及中枢震荡的买卖点，就不存在第一、二类买卖点了。
-/
instance instDecidableIsOscillationSell (t : LevelTower r base) (lvl turn : Nat) (c : Center P)
    (k : Nat) : Decidable (isOscillationSell t lvl turn c k) := by
  unfold isOscillationSell; infer_instance

end Chan.Defs.Signal
