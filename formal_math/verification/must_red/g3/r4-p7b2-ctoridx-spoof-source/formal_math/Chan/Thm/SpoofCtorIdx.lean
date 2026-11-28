module
public section
inductive MyProp : Prop where
  | mk

unsafe def fakeImpl (n : Nat) : Nat := @getObjTagNat Nat n

@[implemented_by fakeImpl]
def MyProp.ctorIdx (n : Nat) : Nat := 0
