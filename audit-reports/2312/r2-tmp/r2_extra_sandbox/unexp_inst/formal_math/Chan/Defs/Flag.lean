module
public section
structure MyNat where val : Nat
instance : BEq MyNat where beq a b := a.val == b.val
end
@[expose] public section
end
