module
@[expose] public section
def Premise (x : Nat) : Prop := x = 0
def Concl (x : Nat) : Prop := x = 1
class Pos (n : Nat) : Prop where
  pos : 0 < n
instance : Pos 2 := ⟨by decide⟩
structure PredWrap where
  P : Nat → Prop
