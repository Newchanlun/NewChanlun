module


public section

structure S where
  config : Nat
  n : Nat

def run (config : Nat) (n : Nat) : Nat := config + n

theorem t : run (config := 1) 2 = 3 := rfl
