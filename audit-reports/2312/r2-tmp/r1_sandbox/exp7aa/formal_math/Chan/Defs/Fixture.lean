module
@[expose] public section
structure BspEndpoint where
  side : Nat
  center : Nat
  divPair : Nat
  brokeCenter : Bool
  afterTypeOne : Bool
  leftCenter : Bool
  retracePrice : Nat
  firstRetrace : Bool
def dummyBsp : BspEndpoint := ⟨0, 0, 0, true, true, true, 0, true⟩
end
public section
theorem fakeRefinement :
    dummyBsp.brokeCenter = (dummyBsp.side == 0) ∧
    dummyBsp.afterTypeOne = (dummyBsp.side == 0) ∧
    dummyBsp.leftCenter = (dummyBsp.side == 0) ∧
    dummyBsp.firstRetrace = (dummyBsp.side == 0) :=
  ⟨rfl, rfl, rfl, rfl⟩
