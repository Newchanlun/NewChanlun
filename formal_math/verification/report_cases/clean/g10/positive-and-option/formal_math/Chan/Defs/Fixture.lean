module

@[expose] public section

def rate (x dt : Nat) (_positive : 0 < dt) : Nat := x / dt

def first (xs : List Nat) : Option Nat := xs.head?
