module
public section
mutual
  inductive TreeA where
    | leaf : Nat → TreeA
    | node : TreeB → TreeA
  inductive TreeB where
    | nil : TreeB
    | cons : TreeA → TreeB → TreeB
end
deriving instance Repr for TreeA, TreeB
