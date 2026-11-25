module
public import Init.Data.Rat.Basic
@[expose] public section
def MyInt := Int
def MyRat := Rat
instance : Div MyInt := inferInstanceAs (Div Int)
instance : Div MyRat := inferInstanceAs (Div Rat)
def rInt (x y : MyInt) : MyInt := x / y
def rRat (x y : MyRat) : MyRat := x / y
