module
public section
structure Base where
  n : Nat
  ok : 0 < n
structure Child extends Base where
  m : Nat
def mkChild : Child := ⟨⟨1, by decide⟩, 2⟩
