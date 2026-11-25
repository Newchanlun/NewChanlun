module
public section
structure Bar where
  x : Nat
deriving Repr
namespace Bar
inductive Tree (b : Bar) where
  | leaf
  | node (cs : List (Tree b))
deriving Repr
end Bar
