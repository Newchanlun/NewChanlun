module

@[expose] public section

structure Endpoint where
  raw : Nat
  flag : Bool

end

public section

theorem notARefinement (e : Endpoint) : e.flag = e.flag := rfl
