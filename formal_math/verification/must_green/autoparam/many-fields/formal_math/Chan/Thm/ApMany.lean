module

public section

/-! 一个文件里多个结构体、每个结构体多个带自动证明默认值的字段。 -/

structure ApRange where
  lo : Nat
  hi : Nat
  mid : Nat
  hLo : lo ≤ mid := by omega
  hHi : mid ≤ hi := by omega
  hSpan : lo ≤ hi := by omega

structure ApPair where
  x : Nat
  y : Nat
  hx : 0 < x + 1 := by omega
  hy : x ≤ x + y := by omega

structure ApBox where
  w : Nat
  h : Nat
  hw : w ≤ w := by omega
  hh : h ≤ h * 1 := by simp

def apRange : ApRange := { lo := 1, hi := 5, mid := 3 }

def apPair : ApPair := { x := 2, y := 3 }

def apBox : ApBox := { w := 2, h := 3 }
