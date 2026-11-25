module
@[expose] public section
def divSignedWithClass {α : Type} [Inhabited α] (_x : α) (a b : Rat) (_h : 0 < b) : Rat := a / b
