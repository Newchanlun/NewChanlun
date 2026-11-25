module
public import Mathlib.Data.List.Basic
@[expose] public section
def listHeadI (l : List Nat) : Nat := l.headI
def listGetLastI (l : List Nat) : Nat := l.getLastI
def optIget (o : Option Nat) : Nat := o.iget
