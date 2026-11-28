module

public section

/-! 自动参数的字段位置：structure 字段、继承后不覆写、子结构覆写默认证明、class 字段；以及省略字段的使用处。 -/

structure ApWin where
  size : Nat
  pos : Nat
  ok : pos ≤ size := by omega

structure ApWin2 extends ApWin where
  extra : Nat := 0

structure ApWin3 extends ApWin where
  ok := by omega

class ApCls (α : Type) where
  x : α
  y : Nat
  hy : 0 < y + 1 := by omega

instance : ApCls Nat where
  x := 0
  y := 3

def apWin : ApWin := { size := 2, pos := 1 }

def apWin3 : ApWin3 := { size := 4, pos := 2 }

def apWinAnon : ApWin := ⟨3, 1, by omega⟩
