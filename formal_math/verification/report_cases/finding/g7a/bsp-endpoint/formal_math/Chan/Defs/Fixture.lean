module

@[expose] public section

-- 复刻 BspEndpoint：调用者分别给定四项判据。
structure BspEndpoint where
  side : Nat
  center : Nat
  divPair : Nat
  brokeCenter : Bool
  afterTypeOne : Bool
  leftCenter : Bool
  retracePrice : Nat
  firstRetrace : Bool
