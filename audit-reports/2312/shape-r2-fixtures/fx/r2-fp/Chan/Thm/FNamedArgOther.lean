module


public section

def run2 (cfg : Nat) (n : Nat) : Nat := cfg + n

theorem t : run2 (cfg := 1) (n := 2) = 3 := rfl
