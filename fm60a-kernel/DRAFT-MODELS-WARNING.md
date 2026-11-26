# 警告：`draft-models-unreviewed.jsonl` 与 `drafts/` 为整理者草稿，不属于本票交付物

以下文件系 #2324 R2 提交（`203a5b4c40787887ae567ab68b822d8ad32bd879`）中 9 条示范判例的建模与合成实例部分，按 R2 独审（`799d96f9`）结论**原样移出、不再修改**，与 `legacy-v1-unreviewed.jsonl` 并列隔离：

- `fm60a-kernel/draft-models-unreviewed.jsonl`：从 `203a5b4c` 原样提取的 9 条示范判例之 `organizer_models` 与 `instances`；
- `fm60a-kernel/drafts/non_normative_probe.py`：从 `demo_harness/` 原样移出的建模层演示脚本。

**强制声明**：
1. **整理者草稿，未过审，不属于本票交付物**；R2 忠实性独审已指出该草稿中存在未闭合问题（包括 R03、R06、R08、R09、R14、R15、R16 等建模前提与反事实归属缺陷）。
2. **仅作参考**：供后续编写形式化定义与回归测试的作者参考；任何使用者**必须在自己名下自行核对全部前提、边界与输出归属**，不得直接将其作为作者判例回归真值导入。
3. 本票 #2324 的正式内核交付物仅为 `fm60a-kernel/kernel-cases.jsonl`（纯作者陈述库 `fm60a-author-statements-v1`）及 `classification.jsonl`。
