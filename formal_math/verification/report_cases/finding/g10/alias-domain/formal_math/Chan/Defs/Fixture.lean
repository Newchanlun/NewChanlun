module

@[expose] public section

def Price := Nat
instance : Sub Price := ⟨Nat.sub⟩
instance : Div Price := ⟨Nat.div⟩
def gap (x y : Price) : Price := x - y
def rate (x y : Price) : Price := x / y
