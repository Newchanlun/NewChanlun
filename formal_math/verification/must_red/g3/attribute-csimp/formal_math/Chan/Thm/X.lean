module
public section
def f (n : Nat) : Nat := n
def g (n : Nat) : Nat := n
@[csimp] theorem fg : @f = @g := rfl
