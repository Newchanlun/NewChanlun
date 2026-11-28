module

public import Chan.Defs.Level.Rule

/-!
# M8 同级别分解规则实例

本级别不定义中枢延伸，三段重叠即成块，允许盘整接盘整。本级以下的延伸由所用的下级规则负责。
-/

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Alt Chan.Defs.Center

universe u

/-- 同级别块判定：`[i, j)` 被接受当且仅当 `j = i + 3` 且自 `i` 起三段能成核。

[038:26]
> 因此，完全合理、不违反任何理论原则的，可以制定出这样的同级别分解规则：在某级别中，不定义中枢延伸，允许该级别上的盘整+盘整连接；与此同时，规定该级别以下的所有级别，都允许中枢延伸，不允许盘整+盘整连接；至于该级别以上级别，根本不考虑，因为所有走势都按该级别给分解了。

[二级旁证 041:259]
> 同级别分解，不允许盘整里的中枢延伸，因此3段次级别就是了，不存在任意的问题。
-/
def sameLevelAccepts {Q : Type u} [LinearOrder Q] (ctx : List (Seg Q)) (i j : Nat) : Bool :=
  decide (j = i + 3) && seedAtB ctx i

/-- 同级别分解规则实例：本级不延伸，三段重叠成块，允许盘整接盘整。

[038:18]
> 所谓同级别分解，就是把所有走势按一固定级别的走势类型进行分解。根据“缠中说禅走势分解定理”，同级别分解具有唯一性，不存在任何含糊乱分解的可能。

[二级旁证 038:20]
> 同级别分解的应用，前面已多有论述，例如，以30分钟级别为操作标准的，就可用30分钟级别的分解进行操作，对任何图形，都分解成一段段30分钟走势类型的连接，操作中只选择其中的上涨和盘整类型，而避开所有下跌类型。
-/
def sameLevelRule : BlockRule.{u} where
  accepts := fun ctx i j => sameLevelAccepts ctx i j
  blockDir := fun ctx => firstDir ctx

end Chan.Defs.Level
