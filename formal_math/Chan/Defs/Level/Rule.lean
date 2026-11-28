module

public import Chan.Defs.Center.Center

/-!
# M6 级别规则接口

级别以基底标签为类型索引（清单 B-26）。块规则是一族对任意线性序价格类型一致的块语言，
粗化算子固定为“上级段值域 = 所辖下级段值域凸包”（`#2318` 实测结论三），不允许规则自定。
接口律、进位有界律、局部确定性前提都写成命名的命题字段（清单 B-1、B-29、B-32，`#2318` 结论一）。
-/

@[expose] public section

namespace Chan.Defs

universe v

/-- 级别：以基底标签 `base` 为类型索引的自然数递归深度。不同基底下的级别属于不同类型，
不可直接比较。结构本身即命名空间 `Chan.Defs.Level`。

[101:58]
> 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。
-/
structure Level {B : Type v} (base : B) where
  /-- 递归深度（0 为基底本级）。 -/
  depth : Nat
  deriving DecidableEq

end Chan.Defs

namespace Chan.Defs.Level

open Chan.Defs.Order Chan.Defs.Path Chan.Defs.Alt Chan.Defs.Center

universe u v

/-- 同基底级别的序：深度比较。

[102:38]
> 而级别的存在，一个必然的结论就是，任何高级别的改变都必须先从低级别开始。
-/
def le {B : Type v} {base : B} (x y : Level base) : Prop := x.depth ≤ y.depth

/-- `Level.le` 可判定。

[102:38]
> 而级别的存在，一个必然的结论就是，任何高级别的改变都必须先从低级别开始。
-/
instance instDecidableLevelLe {B : Type v} {base : B} (x y : Level base) :
    Decidable (x.le y) := by
  unfold Chan.Defs.Level.le; infer_instance

/-- 高一级。

[053:20]
> 就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。
-/
def succ {B : Type v} {base : B} (x : Level base) : Level base := ⟨x.depth + 1⟩

/-- 块规则（块语言）：`accepts ctx i j` 判定本级段序列 `ctx` 中左闭右开子块 `[i, j)` 是否为一个
已完成的高一级块；`blockDir` 给出粗化后高一级段的方向。两者对一切线性序价格类型一致定义，
以便陈述保序不变与镜像等变。粗化值域由 `BlockRule.coarsen` 固定为凸包。

[038:18]
> 显然，一个好的分解，其分解规则下，必须保证分解的唯一性，否则这种分解就绝对不可能是好的分解。
-/
structure BlockRule : Type (u + 1) where
  /-- 块判定。 -/
  accepts : {Q : Type u} → [LinearOrder Q] → List (Seg Q) → Nat → Nat → Bool
  /-- 高一级段方向。 -/
  blockDir : {Q : Type u} → [LinearOrder Q] → List (Seg Q) → Dir

/-- 默认方向选择：块首段方向（空块取向上，仅为全函数补位）。

[067:16]
> 以向上笔开始的线段，可以用笔的序列表示：S1X1S2X2S3X3…SnXn。
-/
def firstDir {Q : Type u} [LinearOrder Q] : List (Seg Q) → Dir
  | [] => Dir.up
  | s :: _ => s.dir

/-- 段序列的左闭右开子块 `[i, j)`。

[053:20]
> 就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。
-/
def blockOf {Q : Type u} [LinearOrder Q] (ctx : List (Seg Q)) (i j : Nat) : List (Seg Q) :=
  List.take (j - i) (List.drop i ctx)

/-- 粗化算子：非空块粗化为一个高一级段，值域为全部下级段值域的凸包，跨度覆盖全块。

[053:20]
> 但无论这些显微镜如何转换，一个原则是不变的，就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。
-/
def BlockRule.coarsen (r : BlockRule.{u}) {Q : Type u} [LinearOrder Q] :
    List (Seg Q) → Option (Seg Q)
  | [] => none
  | s :: rest =>
    some ⟨r.blockDir (s :: rest),
      hullInterval s.range (List.map (fun x : Seg Q => x.range) rest),
      List.foldl (fun (acc : Span) (x : Seg Q) => Span.join acc x.span) s.span rest⟩

/-- 按本级切点表 `cuts` 把段序列粗化为高一级段序列。

[053:20]
> 就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。
-/
def BlockRule.coarsenBy (r : BlockRule.{u}) {Q : Type u} [LinearOrder Q] (ctx : List (Seg Q))
    (cuts : List Nat) : List (Seg Q) :=
  List.filterMap (fun p : Nat × Nat => r.coarsen (blockOf ctx p.1 p.2)) (List.zip cuts (List.tail cuts))

/-- 尾部起点：自 `i` 起在 `ctx` 内不存在任何被接受的块。

[059:42]
> 但无论如何分解，19-45至少是一个未完成5分钟走势类型的结论不变。
-/
def TailStart (r : BlockRule.{u}) {Q : Type u} [LinearOrder Q] (ctx : List (Seg Q)) (i : Nat) :
    Prop :=
  ∀ j ∈ List.range (ctx.length + 1), r.accepts ctx i j = false

/-- `TailStart` 可判定。

[059:42]
> 但无论如何分解，19-45至少是一个未完成5分钟走势类型的结论不变。
-/
instance instDecidableTailStart (r : BlockRule.{u}) {Q : Type u} [LinearOrder Q]
    (ctx : List (Seg Q)) (i : Nat) : Decidable (TailStart r ctx i) := by
  unfold TailStart; infer_instance

/-- 自 `start` 起第一个能成核的下标。

[018:24]
> 注意，次级别的前三个走势类型都是完成的才构成该级别的缠中说禅走势中枢，完成的走势类型
-/
def firstSeedFrom {Q : Type u} [LinearOrder Q] (ctx : List (Seg Q)) (start : Nat) : Option Nat :=
  List.head? (List.filter (fun k : Nat => decide (start ≤ k) && seedAtB ctx k)
    (List.range ctx.length))

/-- 延伸段落：块内自 `k` 起长 `len` 的窗口为一次中枢延伸（前三段成核，其后每段与核闭重叠）。

[020:56]
> 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。
-/
def ExtRun {Q : Type u} [LinearOrder Q] (block : List (Seg Q)) (k len : Nat) : Prop :=
  3 ≤ len ∧ (List.take len (List.drop k block)).length = len ∧
  overlapsList (seedCore block k) ∧
  ∀ s ∈ List.drop 3 (List.take len (List.drop k block)), overlapsList (s.range :: seedCore block k)

/-- `ExtRun` 可判定。

[020:56]
> 缠中说禅走势中枢中心定理一：走势中枢的延伸等价于任意区间[dn，gn]与[ZD，ZG]有重叠。
-/
instance instDecidableExtRun {Q : Type u} [LinearOrder Q] (block : List (Seg Q)) (k len : Nat) :
    Decidable (ExtRun block k len) := by
  unfold ExtRun; infer_instance

/-- 五条接口律：
1. 切点收缩：被接受块非空且不越界；
2. 至少三段含核：被接受块至少三段且内部存在能成核的连续三段；
3. 保序不变：对严格保序变换不变；
4. 镜像等变：对多空对偶接受性不变、方向取反；
5. 已确认稳定：已接受的块在任意延拓下仍被接受。

[043:44]
> 缠中说禅走势类型分解原则：一个某级别的走势类型中，不可能出现比该级别更大的中枢，一旦出现，就证明这不是一个某级别的走势类型，而是更大级别走势类型的一部分或几个该级别走势类型的连接。

[二级旁证 018:36]
> “缠中说禅走势分解定理二“：任何级别的任何走势类型，都至少由三段以上次级别走势类型构成。
-/
structure InterfaceLaws (r : BlockRule.{u}) : Prop where
  /-- 切点收缩。 -/
  cutShrink : ∀ {Q : Type u} [LinearOrder Q] (ctx : List (Seg Q)) (i j : Nat),
    r.accepts ctx i j = true → i < j ∧ j ≤ ctx.length
  /-- 至少三段含核。 -/
  coreInside : ∀ {Q : Type u} [LinearOrder Q] (ctx : List (Seg Q)) (i j : Nat),
    r.accepts ctx i j = true → i + 3 ≤ j ∧ ∃ k : Nat, i ≤ k ∧ k + 3 ≤ j ∧ seedAtB ctx k = true
  /-- 保序不变。 -/
  orderInvariant : ∀ {Q R : Type u} [LinearOrder Q] [LinearOrder R] (e : OrderEmb Q R)
    (ctx : List (Seg Q)) (i j : Nat),
    r.accepts (List.map (Seg.mapEmb e) ctx) i j = r.accepts ctx i j ∧
    r.blockDir (List.map (Seg.mapEmb e) ctx) = r.blockDir ctx
  /-- 镜像等变。 -/
  mirrorEquivariant : ∀ {Q : Type u} [LinearOrder Q] (ctx : List (Seg Q)) (i j : Nat),
    r.accepts (List.map dualSeg ctx) i j = r.accepts ctx i j ∧
    r.blockDir (List.map dualSeg ctx) = (r.blockDir ctx).flip
  /-- 已确认稳定。 -/
  confirmedStable : ∀ {Q : Type u} [LinearOrder Q] (ctx ext : List (Seg Q)) (i j : Nat),
    r.accepts ctx i j = true → r.accepts (ctx ++ ext) i j = true

/-- 进位有界律：任何被接受块内不存在长度超过 `K` 的中枢延伸段落。

[057:42]
> 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。
-/
def CarryBounded (r : BlockRule.{u}) (K : Nat) : Prop :=
  ∀ {Q : Type u} [LinearOrder Q] (ctx : List (Seg Q)) (i j : Nat),
    r.accepts ctx i j = true → ∀ k : Nat, ¬ ExtRun (blockOf ctx i j) k (K + 1)

/-- 局部确定性前提（`#2318` 修正）：起点定终点（每个起点至多一个被接受的终点），
加尾部穷尽（某起点一旦不成块，其后任一起点在同一序列上也不成块，故规范分解的未完成尾部唯一）。

[038:18]
> 显然，一个好的分解，其分解规则下，必须保证分解的唯一性，否则这种分解就绝对不可能是好的分解。
-/
structure DeterministicBlocks (r : BlockRule.{u}) : Prop where
  /-- 起点定终点。 -/
  uniqueEnd : ∀ {Q : Type u} [LinearOrder Q] (ctx : List (Seg Q)) (i j₁ j₂ : Nat),
    r.accepts ctx i j₁ = true → r.accepts ctx i j₂ = true → j₁ = j₂
  /-- 尾部穷尽。 -/
  tailExhaust : ∀ {Q : Type u} [LinearOrder Q] (ctx : List (Seg Q)) (i i' : Nat),
    TailStart r ctx i → i ≤ i' → TailStart r ctx i'

end Chan.Defs.Level
