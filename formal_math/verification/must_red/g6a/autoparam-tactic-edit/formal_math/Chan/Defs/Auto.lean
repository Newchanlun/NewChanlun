module

@[expose] public section

/-! 声明锁现状记录：锁文件按 `by omega` 生成；这里只把默认证明的战术改成 `by (omega)`，
只有载体 `LockWin.ok._autoParam` 的锁行变（LOCK_CHANGED），结构体与构造子的锁行不变。 -/

structure LockWin where
  size : Nat
  pos : Nat
  ok : pos ≤ size := by (omega)
