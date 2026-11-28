module

public import Init.Data.Rat.Basic

@[expose] public section

def divNeZero (x dt : Nat) (_h : dt ≠ 0) : Nat := x / dt
def divSucc (x dt : Nat) : Nat := x / (dt + 1)
def divSubtype (x : Nat) (dt : { n : Nat // 0 < n }) : Nat := x / dt.val
def divInt (x dt : Int) (_h : dt ≠ 0) : Int := x / dt
def divRat (x dt : Rat) (_h : dt ≠ 0 ∧ True) : Rat := x / dt
