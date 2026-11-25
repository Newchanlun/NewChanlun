module
@[expose] public section
structure BspEndpoint where
  side : Nat
  brokeCenter : Bool
  afterTypeOne : Bool
  leftCenter : Bool
  firstRetrace : Bool
end
public section
theorem fakeRefEmpty (e : BspEndpoint) (z : Empty) :
    e.brokeCenter = decide (e.side > 0) ∧
    e.afterTypeOne = decide (e.side > 0) ∧
    e.leftCenter = decide (e.side > 0) ∧
    e.firstRetrace = decide (e.side > 0) :=
  nomatch z
