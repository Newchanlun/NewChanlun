module
public import Chan.Defs.Spec
public section
theorem counterexample : Premise 0 ∧ ¬ Concl 0 := ⟨rfl, by decide⟩
