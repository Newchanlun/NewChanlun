module
@[expose] public section
def D (n : Nat) : Nat := n + 1
structure CarryD where
  x : Nat
  h : D x = x + 1
def divWithClass {α : Type} [Inhabited α] (_x : α) (a b : Rat) (_h : 0 < b) : Rat := a / b
