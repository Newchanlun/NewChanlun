module
public section
-- 已知不防的接手对照：rfl' 展开时关掉 smartUnfolding，形状门看不见；它不能让假命题过关。
theorem rflPrimeFalse : (2 : Nat) = 3 := by rfl'
