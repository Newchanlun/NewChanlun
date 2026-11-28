module
public import Mathlib.Algebra.Order.Field.Basic
public import Mathlib.Data.List.Basic
@[expose] public section
def genericPosDiv {K : Type} [Field K] [LinearOrder K] (a b : K) (_h : 0 < b) : K := a / b
def genericLitDiv {K : Type} [Field K] [LinearOrder K] (a : K) : K := a / 2
def listHeadI (l : List Nat) : Nat := l.headI
