module
public section
inductive Color | red | blue
attribute [extern "evil_c_symbol"] Color.ctorIdx
attribute [extern "evil_c_impl"] Color.ctorIdx._impl
def myRec : Nat → Nat
  | 0 => 0
  | n + 1 => myRec n
attribute [extern "evil_c_rec"] myRec._unsafe_rec
