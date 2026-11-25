module
public section
theorem guarded_mirror (x : Nat) (hx : 0 < x)
    (h : ∀ n, 0 < n → n + 1 > 1) : x + 1 > 1 := h x hx
