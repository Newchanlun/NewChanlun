module
public section
structure Bar where
  x : Nat
namespace Bar
inductive Rose where
  | mk (cs : List Rose)
deriving Repr, BEq, Hashable, Ord
end Bar

private inductive PrivRose where
  | mk (cs : List PrivRose)
deriving Repr, BEq, Hashable, Ord

inductive ParamRose (α : Type) where
  | leaf (a : α)
  | node (cs : List (ParamRose α))
deriving Repr, BEq, Hashable, Ord
