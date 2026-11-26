module


public section

def nat (native : Bool) : Bool := native

theorem t : nat (native := true) = true := rfl
