module

public section

/-! 对照：生成的载体 `SpLegit.ok._autoParam` 不得出现在红行里。 -/

structure SpLegit where
  a : Nat
  ok : a ≤ a := by omega
