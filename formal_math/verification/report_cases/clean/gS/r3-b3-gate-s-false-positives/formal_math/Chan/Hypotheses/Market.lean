module
public import Chan.Defs.Model
@[expose] public section
def PositivePrices : Prop := ∀ n : Nat, 0 < price n
structure GlobalMarket : Prop where
  pos : ∀ n : Nat, 0 < price n
