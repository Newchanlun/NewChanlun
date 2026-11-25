module
@[expose] public section
structure BarSeq where
  bars : List Nat
  isPivot : Nat → Prop
  spec : ∀ i, isPivot i ↔ i < bars.length
end
public section
theorem barSeq_ref_pointwise (s : BarSeq) (i : Nat) : s.isPivot i ↔ i < s.bars.length := s.spec i
