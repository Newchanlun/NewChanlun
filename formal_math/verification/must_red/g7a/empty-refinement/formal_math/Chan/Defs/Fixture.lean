module

@[expose] public section

structure Endpoint where
  raw : Nat
  flag : Bool

end
public section

theorem fake (e : Endpoint) (z : Empty) : e.flag = (e.raw == 0) := nomatch z
