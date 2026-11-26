module


public section

def re (reconfig : Nat) (simp_config : Nat) : Nat := reconfig + simp_config

def v : Nat := re (reconfig := 1) (simp_config := 2)
