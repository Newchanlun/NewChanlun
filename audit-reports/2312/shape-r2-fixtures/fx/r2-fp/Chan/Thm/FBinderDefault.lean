module


public section

def a (config := 5) (n : Nat := config) : Nat := config + n

def b (config : Nat := 5) : Nat := config

variable (simp_config := 3)

def c : Nat := simp_config
