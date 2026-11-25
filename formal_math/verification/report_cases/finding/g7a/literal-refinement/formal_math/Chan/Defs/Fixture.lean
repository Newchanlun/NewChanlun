module

@[expose] public section

structure Endpoint where
  raw : Nat
  flag : Bool

def dummy : Endpoint := ⟨0, true⟩

end
public section

theorem fake : dummy.flag = (dummy.raw == 0) := rfl
