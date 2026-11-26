module

public section

/-! 已知的窄误拒：`variable` 绑定器上的自动参数。Lean 为它生成的载体没有任何声明以 autoParam 引用，
环境层按「必须被引用」判 ENV_META。绕开办法：把自动参数写在用到它的 def 或 theorem 自己的绑定器上。 -/

variable (n : Nat) (hv : n ≤ n + 1 := by omega)

theorem apVarThm : n = n := rfl
