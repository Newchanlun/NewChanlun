module
public section
section
variable (x y : Nat) (h : x = y)
include h
theorem t1 : y = x := h.symm
omit h in
theorem t2 : x = x := rfl
end
