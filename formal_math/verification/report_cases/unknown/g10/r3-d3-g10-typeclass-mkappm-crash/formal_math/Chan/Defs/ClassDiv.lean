module
@[expose] public section
def divWithClass {α : Type} [Div α] [LT α] [OfNat α 0] (a b : α) (_h : 0 < b) : α := a / b
