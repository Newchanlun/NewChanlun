module
@[expose] public section
def gtInt (a b : Int) (_h : b > 0) : Int := a / b
def gtRat (a b : Rat) (_h : b > 0) : Rat := a / b
def negInt (a b : Int) (_h : b < 0) : Int := a / b
def invGuarded (b : Rat) (_h : 0 < b) : Rat := b⁻¹
