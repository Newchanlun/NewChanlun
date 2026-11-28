module

public section

-- 复刻 main_mirror_equivariant 的依赖参数和全称前提。
theorem main_mirror_equivariant (E : Type) (step : Nat → E → Nat)
    (mirrorState : Nat → Nat) (mirrorEvent : E → E)
    (h : ∀ x e, step (mirrorState x) (mirrorEvent e) = mirrorState (step x e))
    (x : Nat) (e : E) : step (mirrorState x) (mirrorEvent e) = mirrorState (step x e) :=
  h x e
