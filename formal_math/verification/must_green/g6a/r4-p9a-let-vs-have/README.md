# 第四轮 P9a：`let` 改 `have`

Lean 4.36.0 把这两种写法精化成**同一个**内核表达式（`letE … (nondep := true)`，本机打印两者的 `ConstantInfo.value` 逐字相同），所以声明锁不变是对的。FM-lock-v3 仍按建议编码了 `nondep` 位：若两种写法将来精化出不同的 `nondep`，锁会变。
