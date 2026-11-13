# AGENTS.md

用简体中文回复和写文档。本文件是所有 harness 的正本入口，`CLAUDE.md` 仅作兼容指针。skills 正本在 `.agents/skills/`，`.claude/skills` 是投影。

## 项目与入口

NewChanlun 是以缠论为核心的量化交易系统。四大支柱与里程碑见 `docs/ROADMAP.md`；结构引擎和回测在 `rust/`，Lean 形式化在 `formal/`，词汇在 `CONTEXT.md`，架构决策在 `docs/adr/`。

沿用三条开发基础设施，不另造同用途平台：

- **pstack** 提供工作方法，仓内适配在 `.agents/skills/pstack-*`。持续优化走 Hillclimb，先立可重复基线，一次验证一项改动。
- **Matt 的 wayfinder / Sandcastle** 管票、图与隔离实施。入口为 `docs/agents/wayfinder-workflow.md`、`.sandcastle/README.md`；巡航用 `/graph-run <图号>`，决策流程见 `.sandcastle/docs/graph-engineering.md`。
- **LangChain Deep Agents** 提供执行 loop 与正式 PR 审查。入口为 `.sandcastle/deepagents-pilot/README.md`，实施合同见同目录 `EXECUTOR.md`，`deepagents/review` 见 `EXTERNAL-REVIEW.md`。

## 合入与人工确认

- 普通 T/P 决策与 SPEC 均经起草、非作者独审 PASS 后由代理裁定并记账。BLOCK 返修，缺有效独审不放行，不设人工批准门。
- 合入 main 要求精确 head 上 `deepagents/review` 和 `ci-ok` 通过，并满足 strict 追平。`executor serve` 的 review_sweep 带 `sha=<head>` 合入；代理可按同一规则合入。工蜂与执行器派票 run 只开 PR。draft 须验收后标 ready for review，才进入 sweep。
- 人工确认仅保留实盘下单与资金、密钥与凭证，硬门签署见 graph-engineering「2. 考古」。代理可改 CI 和分支保护配置并报告，但不得放宽必需检查、取消 strict 或绕过保护。

## 底线

- 不为基础设施改缠论或交易判据。靶向验证差异面，全量仅留重型验证窗口；共享工作区的测试计数注明并行改动影响。独审须非作者、独立进程、只读证据，可与作者同模型。
- macOS 本机不跑 `cargo`、`rustc`，Rust 验证走 CI、Boat 或远端。保护其他人的未提交工作；破坏性 Git 操作先备份和只读预检。不泄露凭据，不伪造签名、权限或审查结果。
- 过程证据、运行日志与临时构建放 `/Volumes/AgentStorage`，按 `.sandcastle/CODEX-CHILD.md`「一次收齐交付材料」绑定版本、摘要和可读取实体。旧仓内报告仍可验证；历史纪律恢复见 `.chanlun/review-results/ARCHIVE-INDEX.md`。产品教义、ADR、操作入口和测试 fixture 留仓。

## 领域教义与文档层名分

涉及领域判断或裁定时，起草者与独审者读 `docs/agents/doctrine-rules.md` 完整条文，不用以下摘要代替限定词和举证门。

- **缠论教义正本**在 `.chanlun/definitions/`。原文管语义，`formal/Origin/` 管原文未讲的边界，生产代码只有否决权。裁定落定义文件并附受影响代码行号；注释中的分歧必须带票号。
- **收敛通则 #799** 禁止同一判断以宽松档接管严格档失败。**总缝规则 #804** 要求同一判定每级一致，级别只作为输入值；用同输入同输出的测试锁证明，例外须按完整条文举证。
- 原始博文 `docs/chanlun/text/blog/` 优先于编纂版 `docs/chanlun/text/chan99/`，后者优先于思维导图 `docs/chanlun/text/mindmaps/`。「课号:行号」只认博文正本，援引须核行号、逐字、作者归属和行内注。
- 推论层 `analysis/` 与 `docs/` 散件的主张须搬进票里重过推理链、现场标溯源；裁完落定义、ADR 或 `CONTEXT.md`。正本不回引推论层，历史推论不追溯改写。旧 `AGENTS.md:<行号>` 引用按 doctrine-rules 头部基线查。
- 正式 goal 事件写法见 `.chanlun/goals/SCHEMA.md`；裁定 PDF 入链见 `docs/formal-chain/INDEX.md`。

## 派发与开工纪律

- 主控使用当前会话模型，负责规划、执行或委派、整合和验收。子代理默认继承模型；有明确独立收益才拆分。Sandcastle 模型配置见 `.sandcastle/main-model.mts`，正式审查配置见 `.sandcastle/deepagents-pilot/pilot1742/external_review.py`。
- 用户已常驻授权派发，无需逐次询问；当前任务明确禁派或限制角色时遵从该限制。派发写清职责、边界和验收，不覆盖其他 owner 的工作。
- 实质工作承接已有 ticket 和授权。同范围已获执行授权不再等点头；新工作缺授权时先准备建议。读文件、查状态、回答已知事实和单条配置修改不必挂票。
- **开之前先搜（两路，缺一不可）**：建票前查 `gh issue list --search "<关键词>" --state all`，再查 `rg -n "<关键词>" analysis/ docs/ .chanlun/`；同一工作复用已有票。tracker 为 `Newchanlun/NewChanlun`，操作和票型见 `docs/agents/issue-tracker.md`。
- 需要流程 skill 时读 `.agents/skills/<名字>/SKILL.md`。交付精确版本、相关验证和剩余依赖，不把分派或通过局部检查当作完成。分支与自动化以 main 为基线，代码名分见 `docs/adr/0004-generation-constitution.md`「现行名分与现役线」。
