module
public section
inductive BinTree where
  | leaf (v : Nat)
  | node (l r : BinTree)
deriving Ord
