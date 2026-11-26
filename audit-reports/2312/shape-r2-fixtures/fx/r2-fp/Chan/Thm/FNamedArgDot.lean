module


public section

structure S where
  config : Nat
  n : Nat

def run (config : Nat) (n : Nat) : Nat := config + n

def S.go (s : S) (cfg_config : Nat) : Nat := s.n + cfg_config

def v (s : S) : Nat := s.go (cfg_config := 1)
