module

/-- 门禁每次先读这个私有定理的证明体，再审计包里的声明。 -/
private theorem gateProofProbe : (1 : Nat) < 2 := by decide
