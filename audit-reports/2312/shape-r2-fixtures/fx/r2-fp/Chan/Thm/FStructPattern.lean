module


public section

structure S where
  config : Nat
  n : Nat

def run (config : Nat) (n : Nat) : Nat := config + n

def g (s : S) : Nat :=
  match s with
  | ⟨config, n⟩ => config + n

def g2 (s : S) : Nat :=
  let ⟨config, _⟩ := s
  config

def g3 : S → Nat
  | { config := c, n := _ } => c
