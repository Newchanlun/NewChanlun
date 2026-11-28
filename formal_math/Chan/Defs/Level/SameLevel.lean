module

public import Chan.Defs.Level.Rule

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Center

/-- 只在指定层分解：三段成核即完成，不把后一盘整并进前一块。
[038:18] 所谓同级别分解，就是把所有走势按一固定级别的走势类型进行分解。根据“缠中说禅走势分解定理”，同级别分解具有唯一性，不存在任何含糊乱分解的可能。
[038:26] 因此，完全合理、不违反任何理论原则的，可以制定出这样的同级别分解规则：在某级别中，不定义中枢延伸，允许该级别上的盘整+盘整连接；与此同时，规定该级别以下的所有级别，都允许中枢延伸，不允许盘整+盘整连接；至于该级别以上级别，根本不考虑，因为所有走势都按该级别给分解了。 -/
def sameLevelRule (atDepth : Nat := 0) : BlockRule where
  rank k xs _ i j :=
    if k == atDepth && j == i+3 && (Center.window? xs i j).isSome then some 0 else none
  confirmed k xs _ i j := k == atDepth && j == i+3 && (Center.window? xs i j).isSome

end Chan.Defs.Level
