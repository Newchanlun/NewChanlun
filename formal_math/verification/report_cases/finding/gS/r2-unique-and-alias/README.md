# 二审 r2-unique-and-alias

`conj_mirror` 的 `∧ True` 仍报 `STATEMENT_FORM`。`eu_eq_zero` 的闭合取项 `0 = 0` 原由「闭命题不能作前提或合取项」判红，该规则按 #2312 裁定（评论 7164343103，R3-H4）删除，不再期望命中；同类写法见 `known_limits/gS/fable-b7a`。
