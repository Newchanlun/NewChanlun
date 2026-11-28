module

public section

/-! 给 Lean 真生成的自动参数载体事后挂 `attribute [extern ...]`：
第 7 步必须同时判 `ENV_EXTERN` 与 `ENV_META`（钉住判据 2 的 `!isExtern`）。 -/

structure SpExt where
  a : Nat
  h : a ≤ a := by omega

attribute [extern "fm_evil_extern"] SpExt.h._autoParam
