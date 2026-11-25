module
public section
inductive Tree where
  | leaf
  | node (cs : List Tree)

namespace instReprTree
partial def repr (n : Nat) : Nat := repr (n + 1)
end instReprTree

instance instReprTree : Repr Tree :=
  let _ := @instReprTree.repr
  { reprPrec := fun _ _ => Std.Format.nil }

def callPartial (n : Nat) : Nat := instReprTree.repr n
