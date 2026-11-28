module

public import Mathlib.Order.Interval.Basic

/-!
# M2 历史、在线语义、修订量

走势历史是有限列表；已确认对象对一切有限延拓不变；未完成尾部显式给出有限候选集合（清单 B-28）。
凡对无穷对象量化的谓词，均另给出在显式有限样本上的可判定版本（`…On` / `StableBetween`）。
-/

@[expose] public section

namespace Chan.Defs.Path

universe u v

/-- 有限走势历史：元素的有限列表。

[099:16]
> 有人可能认为，中阴存在是理论不完善的结果，其实，这是典型的一根筋思维，对于这种思维，世界就是机械的，任何时候都只有一个机械精确的结果，而实际上，世界更多是量子化的，是测不准的，中阴的存在恰好客观地反映了走势的这种特性。
-/
abbrev History (α : Type u) : Type u := List α

/-- 修订量度量：被改写或撤销的已输出对象数 `rewritten`，以及被拆改的最深层级 `deepest`
（层级自 1 起计，0 表示无修订）。

[099:22]
> 因为，最终的划分，就必须把a+b+c+d+e给拆开了。
-/
structure RevisionCount where
  /-- 被改写或撤销的对象数。 -/
  rewritten : Nat
  /-- 被拆改的最深层级。 -/
  deepest : Nat
  deriving DecidableEq

variable {α : Type u} {β : Type v}

/-- 前缀序：`h₁` 是 `h₂` 的前缀，当且仅当 `h₂` 截取 `h₁` 的长度后恰为 `h₁`。

[102:38]
> 而级别的存在，一个必然的结论就是，任何高级别的改变都必须先从低级别开始。
-/
def IsPrefix (h₁ h₂ : History α) : Prop :=
  List.length h₁ ≤ List.length h₂ ∧ List.take (List.length h₁) h₂ = h₁

/-- `IsPrefix` 可判定。

[102:38]
> 而级别的存在，一个必然的结论就是，任何高级别的改变都必须先从低级别开始。
-/
instance instDecidableIsPrefix [DecidableEq α] (h₁ h₂ : History α) :
    Decidable (IsPrefix h₁ h₂) := by
  unfold IsPrefix; infer_instance

/-- 已确认：分析函数 `f` 在历史 `h` 上的输出，对 `h` 的一切有限延拓保持不变。

[059:42]
> 但无论如何分解，19-45至少是一个未完成5分钟走势类型的结论不变。
-/
def Confirmed (f : History α → β) (h : History α) : Prop :=
  ∀ t : History α, f (h ++ t) = f h

/-- 在显式给定的有限延拓样本 `U` 上的已确认谓词（`Confirmed` 的可判定实例）。

[059:42]
> 但无论如何分解，19-45至少是一个未完成5分钟走势类型的结论不变。
-/
def ConfirmedOn (U : List (History α)) (f : History α → β) (h : History α) : Prop :=
  ∀ t ∈ U, f (h ++ t) = f h

/-- `ConfirmedOn` 可判定。

[059:42]
> 但无论如何分解，19-45至少是一个未完成5分钟走势类型的结论不变。
-/
instance instDecidableConfirmedOn [DecidableEq β] (U : List (History α))
    (f : History α → β) (h : History α) : Decidable (ConfirmedOn U f h) := by
  unfold ConfirmedOn; infer_instance

/-- 把字母表中每个元素分别前置到每条历史上。

[099:16]
> 世界更多是量子化的，是测不准的，中阴的存在恰好客观地反映了走势的这种特性。
-/
def prependAll : List α → List (History α) → List (History α)
  | [], _ => []
  | a :: rest, ts => List.map (fun t : History α => a :: t) ts ++ prependAll rest ts

/-- 字母表 `alphabet` 上长度不超过 `k` 的全部延拓（有限样本，供 `…On` 谓词穷举）。

[099:16]
> 世界更多是量子化的，是测不准的，中阴的存在恰好客观地反映了走势的这种特性。
-/
def extensionsUpTo (alphabet : List α) : Nat → List (History α)
  | 0 => [[]]
  | k + 1 => [] :: prependAll alphabet (extensionsUpTo alphabet k)

/-- 延迟因果：位置 `i` 上的判定只依赖截至 `i` 再向后 `k` 步的前缀。

[102:38]
> 例如，绝对不可能出现5分钟从下跌转折为上涨，而1分钟还在下跌段中。
-/
def DelayedCausal (k : Nat) (f : History α → Nat → β) : Prop :=
  ∀ (h : History α) (i : Nat), f h i = f (List.take (i + k + 1) h) i

/-- 在有限历史样本 `U` 上的延迟因果谓词（`DelayedCausal` 的可判定实例）。

[102:38]
> 例如，绝对不可能出现5分钟从下跌转折为上涨，而1分钟还在下跌段中。
-/
def DelayedCausalOn (U : List (History α)) (k : Nat) (f : History α → Nat → β) : Prop :=
  ∀ h ∈ U, ∀ i ∈ List.range (List.length h), f h i = f (List.take (i + k + 1) h) i

/-- `DelayedCausalOn` 可判定。

[102:38]
> 例如，绝对不可能出现5分钟从下跌转折为上涨，而1分钟还在下跌段中。
-/
instance instDecidableDelayedCausalOn [DecidableEq β] (U : List (History α)) (k : Nat)
    (f : History α → Nat → β) : Decidable (DelayedCausalOn U k f) := by
  unfold DelayedCausalOn; infer_instance

/-- 无限走势 `s` 的长度为 `n` 的前缀。

[017:36]
> “走势终完美”这句话有两个不可分割的方面：任何走势，无论是趋势还是盘整，在图形上最终都要完成。
-/
def streamPrefix (s : Nat → α) (n : Nat) : History α := List.map s (List.range n)

/-- 极限稳定：分析结果在无限走势 `s` 的充分长前缀上最终恒定。

[017:36]
> “走势终完美”这句话有两个不可分割的方面：任何走势，无论是趋势还是盘整，在图形上最终都要完成。
-/
def LimitStable (f : History α → β) (s : Nat → α) : Prop :=
  ∃ N : Nat, ∀ n : Nat, N ≤ n → f (streamPrefix s n) = f (streamPrefix s N)

/-- 在有限窗口 `[N, M)` 上检查的稳定性（`LimitStable` 的可判定实例）。

[017:36]
> “走势终完美”这句话有两个不可分割的方面：任何走势，无论是趋势还是盘整，在图形上最终都要完成。
-/
def StableBetween (f : History α → β) (s : Nat → α) (N M : Nat) : Prop :=
  ∀ n ∈ List.range M, N ≤ n → f (streamPrefix s n) = f (streamPrefix s N)

/-- `StableBetween` 可判定。

[017:36]
> “走势终完美”这句话有两个不可分割的方面：任何走势，无论是趋势还是盘整，在图形上最终都要完成。
-/
instance instDecidableStableBetween [DecidableEq β] (f : History α → β) (s : Nat → α)
    (N M : Nat) : Decidable (StableBetween f s N M) := by
  unfold StableBetween; infer_instance

/-- 单层修订数：旧输出中按位置未被保留的对象个数（被改写或被撤销）。

[099:22]
> 因为，最终的划分，就必须把a+b+c+d+e给拆开了。
-/
def levelRevisions [DecidableEq β] : List β → List β → Nat
  | [], _ => 0
  | _ :: os, [] => List.length os + 1
  | o :: os, n :: ns => (if o = n then 0 else 1) + levelRevisions os ns

/-- 多层修订量的递归计算，`d` 为当前层级（自 0 起）。

[099:22]
> 因为，最终的划分，就必须把a+b+c+d+e给拆开了。
-/
def revisionAux [DecidableEq β] : Nat → List (List β) → List (List β) → RevisionCount
  | _, [], _ => ⟨0, 0⟩
  | d, o :: os, ns =>
    ⟨levelRevisions o (List.headD ns []) + (revisionAux (d + 1) os (List.tail ns)).rewritten,
      if 0 < (revisionAux (d + 1) os (List.tail ns)).deepest then
        (revisionAux (d + 1) os (List.tail ns)).deepest
      else if 0 < levelRevisions o (List.headD ns []) then d + 1 else 0⟩

/-- 从前缀输出 `before` 到延拓输出 `after`（按层级排列的对象列表）的修订量。

[099:22]
> 因为，最终的划分，就必须把a+b+c+d+e给拆开了。
-/
def RevisionCount.measure [DecidableEq β] (before after : List (List β)) : RevisionCount :=
  revisionAux 0 before after

/-- 分析函数 `f` 从历史 `h` 发展到 `h ++ t` 时的修订量。

[099:22]
> 因为，最终的划分，就必须把a+b+c+d+e给拆开了。
-/
def RevisionCount.ofAnalyzer [DecidableEq β] (f : History α → List (List β))
    (h t : History α) : RevisionCount :=
  RevisionCount.measure (f h) (f (h ++ t))

/-- 未完成尾部的有限候选结果集合：在有限延拓样本 `U` 中，凡使 `h ++ t` 合法的延拓 `t`，
收集其分析结果。

[099:16]
> 世界更多是量子化的，是测不准的，中阴的存在恰好客观地反映了走势的这种特性。
-/
def PendingCandidates (legal : History α → Bool) (f : History α → β) (h : History α)
    (U : List (History α)) : List β :=
  List.map (fun t : History α => f (h ++ t)) (List.filter (fun t : History α => legal (h ++ t)) U)

end Chan.Defs.Path
