module
public section
inductive BinTree where
  | leaf (v : Nat)
  | node (l r : BinTree)
deriving DecidableEq, BEq, ReflBEq, LawfulBEq, Hashable, Repr, Inhabited, Nonempty
