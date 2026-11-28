module

public import Mathlib.Data.Finset.Lattice.Fold
public import Mathlib.Order.Bounds.Defs

@[expose] public section

def first (xs : List Nat) : Nat := xs.head!
def atIndex (xs : List Nat) (i : Nat) : Nat := xs[i]!
def withFallback (xs : List Nat) (i : Nat) : Nat := xs.getD i 42
def fallback : Nat := Inhabited.default

variable {α β : Type}

def finSup [SemilatticeSup α] [OrderBot α] (s : Finset β) (f : β → α) : α := s.sup f
def finInf [SemilatticeInf α] [OrderTop α] (s : Finset β) (f : β → α) : α := s.inf f
def setSup [SupSet α] (s : Set α) : α := sSup s
def setInf [InfSet α] (s : Set α) : α := sInf s
