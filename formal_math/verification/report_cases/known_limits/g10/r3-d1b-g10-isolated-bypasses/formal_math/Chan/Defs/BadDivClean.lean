module
@[expose] public section
def fakeLTNat (a b : Nat) : Nat :=
  let _h : @LT.lt Nat ⟨fun _ _ => True⟩ 0 b := trivial
  a / b

def fakeLTRat (a b : Rat) : Rat :=
  let _h : @LT.lt Rat ⟨fun _ _ => True⟩ 0 b := trivial
  a / b

def fakeOneInt (a : Int) : Int :=
  a / @OfNat.ofNat Int (nat_lit 1) ⟨0⟩

def fakeOneRat (a : Rat) : Rat :=
  a / @OfNat.ofNat Rat (nat_lit 1) ⟨0⟩

def fakeZeroGuard (a b : Int) (_h : b ≠ @OfNat.ofNat Int (nat_lit 0) ⟨1⟩) : Int :=
  a / b

def junkDivInt (a b : Int) : Rat := Rat.divInt a b
def junkMkRat (a : Int) (b : Nat) : Rat := mkRat a b
