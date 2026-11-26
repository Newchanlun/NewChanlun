module


public section

structure S where
  config : Nat
  n : Nat

def run (config : Nat) (n : Nat) : Nat := config + n

def s : S := S.mk (config := 1) (n := 2)
