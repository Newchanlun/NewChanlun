module

@[expose] public section

def rate (dx dt : Rat) (_h : 0 < dt) : Rat := dx / dt
def irate (dx dt : Int) (_h : 0 < dt) : Int := dx / dt
def srate (dx : Rat) (dt : { q : Rat // 0 < q }) : Rat := dx / dt.val
def neRate (dx dt : Rat) (_h : dt ≠ 0) : Rat := dx / dt
def natRate (a b : Nat) (_h : 0 < b) : Nat := a / b
