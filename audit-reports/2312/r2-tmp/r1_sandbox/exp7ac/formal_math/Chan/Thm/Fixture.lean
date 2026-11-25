module
public section
def sneakyTheorem (x : Nat) (h0 : x = 0) (h1 : x = 1) : False :=
  Nat.noConfusion (h0.symm.trans h1)
def sneakyMirror (P : Nat → Prop) (h : ∀ x, P x) (x : Nat) : P x := h x
