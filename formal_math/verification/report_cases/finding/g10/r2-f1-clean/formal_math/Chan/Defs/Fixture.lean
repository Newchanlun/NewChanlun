module
public import Init.Data.Rat.Basic
@[expose] public section
def invRat (y : Rat) : Rat := y.inv
def intTdiv (x y : Int) : Int := Int.tdiv x y
def intEdiv (x y : Int) : Int := Int.ediv x y
def intFdiv (x y : Int) : Int := Int.fdiv x y
def natMod (x y : Nat) : Nat := x % y
def headD_fn (xs : List Nat) : Nat := xs.headD 0
def getLastD_fn (xs : List Nat) : Nat := xs.getLastD 0
def arrBang (xs : Array Nat) (i : Nat) : Nat := xs[i]!
def optGetBang (o : Option Nat) : Nat := o.get!
def optPanic (xs : List (Option Nat)) : Option Nat := if xs.isEmpty then panic! "x" else xs.head!
def optLastBang (xs : List (Option Nat)) : Option Nat := xs.getLast!
def optGetIdxBang (xs : List (Option Nat)) (i : Nat) : Option Nat := xs[i]!
def intToNat (x : Int) : Nat := x.toNat
