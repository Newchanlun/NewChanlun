module
public section
def sample : List Nat := [10, 20, 5]
theorem sample_bounds : 20 ∈ sample ∧ 99 ∉ sample := by decide
