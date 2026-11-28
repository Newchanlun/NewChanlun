module
@[expose] public section
structure BadS3 where
  raw : Nat
  flag : Bool
end
public section
theorem fakeRefSub (e : BadS3) (_ : Subsingleton BadS3) (_ : Nonempty BadS3) :
    e.flag = (e.raw == 0) := sorry
