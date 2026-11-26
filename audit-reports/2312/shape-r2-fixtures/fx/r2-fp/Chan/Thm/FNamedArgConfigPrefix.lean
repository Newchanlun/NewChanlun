module


public section

def run3 (configN : Nat) (config' : Nat) : Nat := configN + config'

theorem t : run3 (configN := 1) (config' := 2) = 3 := rfl
