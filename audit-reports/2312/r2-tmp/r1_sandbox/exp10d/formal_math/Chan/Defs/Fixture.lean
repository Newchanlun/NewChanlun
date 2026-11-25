module
@[expose] public section
def divNeZero (x dt : Nat) (_h : dt ≠ 0) : Nat := x / dt
def divGeOne (x dt : Nat) (_h : 1 ≤ dt) : Nat := x / dt
def divSucc (x dt : Nat) : Nat := x / (dt + 1)
def divSubtype (x : Nat) (dt : { n : Nat // 0 < n }) : Nat := x / dt.1
