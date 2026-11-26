module

public section

/-! 日常写法：结构字段的 autoParam 默认证明 `:= by omega`。 -/

structure Win where
  size : Nat
  pos : Nat
  ok : pos ≤ size := by omega
