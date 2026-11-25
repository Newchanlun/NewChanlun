module
public section
structure FakeS where
  x : Nat
class MyPropClass : Prop where
  ok : True
instance instProp : MyPropClass := ⟨trivial⟩
opaque opProp : True := trivial
def defProp : True := trivial
private def privDefProp : True := trivial
theorem FakeS.mk.inj_fake (a b : Nat) (h : FakeS.mk a = FakeS.mk b) : a = b := by cases h; rfl
