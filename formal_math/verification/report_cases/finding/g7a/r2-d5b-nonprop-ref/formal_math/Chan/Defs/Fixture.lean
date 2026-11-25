module
@[expose] public section
structure BadS2 where
  raw : Nat
  flag : Bool
def fakeRef (e : BadS2) : Bool := e.flag
