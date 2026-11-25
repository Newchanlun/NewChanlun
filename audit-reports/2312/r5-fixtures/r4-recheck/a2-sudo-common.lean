-- R4-A2 独立复验样本：Mathlib.Tactic.Common 再导出的 sudo set_option；在 R5 门 3 退 1（门 2 退 2）
module
import Mathlib.Tactic.Common
public section
theorem t : True :=
  sudo set_option linter.unusedVariables false in
  by
    have unusedVar : Nat := 1
    trivial
