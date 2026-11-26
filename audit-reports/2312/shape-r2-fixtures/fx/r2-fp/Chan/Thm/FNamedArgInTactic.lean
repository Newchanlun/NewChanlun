module


public section

structure S where
  config : Nat
  n : Nat

def run (config : Nat) (n : Nat) : Nat := config + n

theorem run_eq (config n : Nat) : run config n = config + n := rfl

theorem t : run 1 2 = 1 + 2 := by
  exact run_eq (config := 1) (n := 2)
