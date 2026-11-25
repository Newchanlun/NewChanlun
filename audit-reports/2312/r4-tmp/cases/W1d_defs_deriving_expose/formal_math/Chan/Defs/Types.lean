module
@[expose] public section
inductive Dir | up | down deriving DecidableEq, BEq, ReflBEq, LawfulBEq, Hashable, Ord, Repr, Inhabited, Nonempty
structure Bar where
  lo : Nat
  hi : Nat
deriving DecidableEq, BEq, Hashable, Ord, Repr, Inhabited
inductive Rose where
  | leaf (n : Nat)
  | node (cs : List Rose)
deriving Repr, BEq, Hashable, Ord, Inhabited
