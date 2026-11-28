module

@[expose] public section

def unlisted (P : Nat → Prop) (h : ∀ n, P n) (x : Nat) : P x := h x
