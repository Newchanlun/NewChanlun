# formal_math 门禁目录

| 位置 | 内容 |
|---|---|
| [`runner/`](runner/README.md) | 运行脚本 `run.py`（七步，前一步不绿即停）、自测 `selftest.py`、旧夹具归属表 `fixtures.tsv`。**各门的断言、对手、不防什么、谁接都写在这里。** |
| [`precheck/`](precheck/README.md) | 第 1 步预检：纯 Python 加 git，唯一承担对抗断言的自写代码 |
| `auditor/` | 只依赖 Lean 核心的独立审计程序包（第 4 步头部、第 5 步源码形状、第 7 步环境层与声明锁） |
| `must_red/`、`must_green/`、`must_unknown/` | 旧门禁留下的夹具，归属与在新入口上的期望见 `runner/fixtures.tsv` |
| `report_cases/` | 审阅报告（S、7a、7b、8a、8b、9、10）的回归样本。报告的旧实现已随 `run_gates.py` 删除，暂不可用；用户裁定（#2312 评论 7164343103）要求这批夹具保留给报告 |
| `garbage-signoffs.yaml` | 签注文件，归属见预检 README |

旧实现（`run_gates.py`、`SourceGates.lean`、`Perimeter.lean`、`Inventory.lean`、两份名单等）在 #2312 第四片删除，
最后一版见 `594e49b5ec` 的 `formal_math/verification/`，当时的说明文档也在那里。
