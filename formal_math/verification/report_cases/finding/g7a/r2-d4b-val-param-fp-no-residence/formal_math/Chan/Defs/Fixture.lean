module
@[expose] public section
structure Window (k : Nat) where
  raw : Nat
  inRange : Bool
  h_in : inRange = (raw < k)
end
public section
theorem window_ref (k : Nat) (e : Window k) : e.inRange = (e.raw < k) := e.h_in
