# 送审版本和验算

| 项 | 绑定 |
|---|---|
| 票号及阶段 | #2121，P 类，起草候选 |
| 两分支裁定源基线 | `b9d898dccf46c2a716115eaa1215bc39c458a959`（首次送审时的 `origin/main`） |
| 决策候选 | `decision/2121@e6f9affa8d3a1e94f728300d0f97cadead628100` |
| 首次送审头 | `decision/2121@17ffe810c35c5d2fedb7485d9236634fd4789154`（本次仅修 B1 引用） |
| 正本文件 | `docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md` |
| 设计取证 | `evidence/1441-design-r3@5a33b2abf9980c27c27bf2150457e8ab7b62fd9c` |
| 实现取证 | PR #2126，`impl/1441-cost-stop-policy@c2806071dec8d0669f478cec4df093781f691232` |
| 相邻获审版本 | `decision/2111@8187e126c3af1911dbfad16ae36e210ac4de0832` |

精确编辑逐项唯一命中，生成的结果和工作树正本经 `cmp` 相同；决策差异仅上述 ADR、`git diff --check` 通过。Python 整数 oracle 输出见 [example-output.txt](example-output.txt)，重跑与该输出一致。实际 #1441 实现、非测试实例及非作者审查均不属于本起草验证。
