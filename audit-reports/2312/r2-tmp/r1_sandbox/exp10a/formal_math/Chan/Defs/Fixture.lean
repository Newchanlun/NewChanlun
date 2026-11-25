module
@[expose] public section
def Price := Nat
instance : Sub Price := inferInstanceAs (Sub Nat)
instance : Div Price := inferInstanceAs (Div Nat)
def gap (x y : Price) : Price := x - y
def rate (x y : Price) : Price := x / y
