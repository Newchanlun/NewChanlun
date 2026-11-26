module


public section

structure S where
  config : Nat
  n : Nat

def run (config : Nat) (n : Nat) : Nat := config + n

def s : S := { config := 1, n := 2 }

def s2 : S := { s with config := 3 }

def s3 : S := ⟨1, 2⟩

def s4 : S where
  config := 1
  n := 2
