module
public import Mathlib.Algebra.Field.Defs
@[expose] public section
def invField {K : Type} [Field K] (y : K) : K := y⁻¹
def divViaInv {K : Type} [Field K] (x y : K) : K := x * y⁻¹
