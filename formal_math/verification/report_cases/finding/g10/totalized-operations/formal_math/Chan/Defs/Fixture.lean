module

public import Init.Data.Rat.Basic

@[expose] public section

def divInt (x y : Int) : Int := x / y
def divRat (x y : Rat) : Rat := x / y
def pred (x : Nat) : Nat := Nat.pred x
def failValue : Nat := panic! "坏值"
def last (xs : List Nat) : Nat := xs.getLast!
