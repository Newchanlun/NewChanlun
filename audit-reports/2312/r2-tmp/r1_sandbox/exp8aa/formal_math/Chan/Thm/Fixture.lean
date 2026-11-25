module
public section
abbrev MirrorStmt : Prop :=
  ∀ (P : Nat → Prop), (∀ x, P x) → ∀ x, P x
theorem wrapped_mirror : MirrorStmt := fun _ h x => h x
