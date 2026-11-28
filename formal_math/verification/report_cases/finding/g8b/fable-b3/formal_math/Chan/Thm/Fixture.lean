module

public section

theorem c0 (x : Nat) (_hdiv : x ≠ 0) : x + 0 = x := rfl

theorem c1 (x : Nat) (_hdiv : x ≠ 0) : x + 0 = x := Function.const (x ≠ 0) rfl _hdiv

theorem c2 (x : Nat) (_hdiv : x ≠ 0) : x + 0 = x := (fun _ => rfl) _hdiv

theorem c3 (x : Nat) (_hdiv : x ≠ 0) : x + 0 = x := And.left ⟨rfl, _hdiv⟩

private theorem mkEq {x : Nat} (_h : x ≠ 0) : x + 0 = x := rfl

theorem c4 (x : Nat) (_hdiv : x ≠ 0) : x + 0 = x := Eq.trans (mkEq _hdiv) rfl
