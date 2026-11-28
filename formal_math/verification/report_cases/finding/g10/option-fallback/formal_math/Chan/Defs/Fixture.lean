module

@[expose] public section

def optHead (xs : List (Option Nat)) : Option Nat := xs.head!
def optGetD (xs : List (Option Nat)) (i : Nat) : Option Nat := xs.getD i (some 999)
