module

public section

-- 复刻 divergence_creates_bsp：只用级别和方向构造信号。
theorem divergence_creates_bsp (d lvl side : Nat) (_hdiv : d > 0) :
    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=
  ⟨(lvl, side), rfl, rfl⟩
