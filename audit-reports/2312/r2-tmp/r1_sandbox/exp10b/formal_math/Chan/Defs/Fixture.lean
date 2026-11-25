module
@[expose] public section
def divInt (x y : Int) : Int := x / y
def divRat (x y : Rat) : Rat := x / y
def truncPred (x : Nat) : Nat := Nat.pred x
def boom : Nat := panic! "boom"
def lastBang (xs : List Nat) : Nat := xs.getLast!
