module
@[expose] public section
def fLet (x : Nat) : Nat := let y := x + 1; y
def fHave (x : Nat) : Nat := have y := x + 1; y
theorem tLet : fLet 0 = 1 := rfl
theorem tHave : fHave 0 = 1 := rfl
