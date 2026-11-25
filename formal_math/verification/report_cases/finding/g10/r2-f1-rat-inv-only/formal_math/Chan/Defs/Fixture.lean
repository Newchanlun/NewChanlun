module
public import Init.Data.Rat.Basic
@[expose] public section
def invRat (y : Rat) : Rat := y.inv
def divByInv (x y : Rat) : Rat := x * y.inv
