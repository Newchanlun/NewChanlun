module
public section
mutual
partial def ping (n : Nat) : Nat := pong n
partial def pong (n : Nat) : Nat := ping (n + 1)
end
