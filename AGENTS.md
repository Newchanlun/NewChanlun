# AGENTS.md

一律用简体中文回复和写文档。本文件是所有 harness 的正本入口；`CLAUDE.md` 只是指向本文件的兼容指针。skills 正本在 `.agents/skills/`，`.claude/skills` 是它的投影。

## 项目

NewChanlun 是以缠论（缠中说禅博文）为核心的量化交易系统，四大支柱为缠论引擎、PH 拓扑、K4 选股、IBKR 执行，路线图见 `docs/ROADMAP.md`。`rust/` 是结构引擎与回测，`formal/` 是 Lean 形式化，`.chanlun/definitions/` 是教义正本，词汇见 `CONTEXT.md`，架构决策见 `docs/adr/`。

## 开发基础设施（只有三样）

新需求接到这三样的现有入口上。

- **pstack**：工作方法（poteto-mode、architect、arena、blast-radius 等），仓内适配版在 `.agents/skills/pstack-*`。持续优化走 pstack 的 Hillclimb：先立基线和可重复测量，一次验证一项改动。
- **Matt 的工作流**：wayfinder 管票与图，正本 `docs/agents/wayfinder-workflow.md`，巡航用 `/graph-run <图号>`；决策票从分级、起草、独审到落地的流程见 `.sandcastle/docs/graph-engineering.md`。Sandcastle 在隔离沙盒里跑实施票，入口 `.sandcastle/README.md`；Sandcastle 工蜂与裁决面的模型在 `.sandcastle/main-model.mts` 配置，正式审查的两位 reviewer 另在 `.sandcastle/deepagents-pilot/pilot1742/external_review.py` 的 `MODELS` 配置。
- **LangChain Deep Agents**：生产执行 loop，入口 `.sandcastle/deepagents-pilot/README.md`。executor（`EXECUTOR.md`）把票从领取跑到实施、异家族独审、发布 PR；`deepagents/review`（`EXTERNAL-REVIEW.md`）审已有 PR 并发布同名必需检查。

## 合入与人工确认

- **合入 main 没有人工门**：分支保护要求 `deepagents/review`（正式非作者审查）与 `ci-ok`（适用 CI 全绿）都通过并追平 main（strict），满足后代理可以合入。工蜂、执行器和 Sandcastle 实施者只开 PR。
- **T 类、P 类决策与 spec 同一流程**：起草，非作者独审 PASS，由代理裁定并记账；BLOCK 就返修，缺有效独审不放行（#1909）。
- **仍要人确认的只有两类**：实盘下单与资金、密钥与凭证。资金、账户、凭据类硬门票挂 `ready-for-human` 交还用户签署，签署格式见 `.sandcastle/docs/graph-engineering.md`「2. 考古」节的资金与权限硬门。过渡例外：#1921 合入前，DeepAgents 队列路径（`executor.py` / `approval.py`）还有 SPEC_AUTHORIZATION 签署门，见同文件「#1742 执行面依赖」。CI 与分支保护配置由代理决定、事后报告，但不得借此关闭或放宽两项必需检查、取消 strict 或用管理员权限绕过。

## 底线

- 行为正确性不变：不为迁就基础设施改缠论或交易判据。验证按差异面靶向做，全量只在重型验证窗口跑并照实标注（`docs/agents/delivery-discipline.md`「验证范围与测试计数」）。
- 合入前必须有非作者独审：独立进程、只读证据，可以与作者同模型。
- macOS 本机不跑 `cargo`、`rustc`；Rust 验证走 CI、Boat 或远端环境。
- 不读、不复制、不打印密钥；不伪造签名、权限或审查状态。破坏性 git 操作前先备份并只读预检；用户粘贴的 shell 命令逐字执行。
- 临时文件、大型构建、快照和运行日志等过程证据放 `/Volumes/AgentStorage`，不入仓。两类例外照旧入仓：关票门要求入 git 的本票报告（测量、调研、评审等，`docs/agents/delivery-discipline.md` 关票第 6 条），以及活期绑定票的 review-results / handoff 工作草稿（`docs/agents/generation-constitution.md` §5）。新文件入仓前按 `docs/agents/generation-constitution.md` §1 判名分；碰分支、worktree、CI 基线前先读同文件 §2「现役线名单」。

## 文档层级与名分

| 层 | 管什么 | 载体 |
|---|---|---|
| 权威链 | 证据从哪来 | 缠师博文 `docs/chanlun/text/blog/`（最终权威）→ 编纂版 `docs/chanlun/text/chan99/` → 思维导图 `docs/chanlun/text/mindmaps/`，有出入以前者为准 |
| 推论层 | 还没裁的推理 | `analysis/` 与 `docs/` 下没有名分的散件 |
| 正本层 | 裁完的结果 | `.chanlun/definitions/`（教义，一概念一份）、`docs/adr/`（架构）、`CONTEXT.md`（词） |

- **名分归主张，不归文档**：援引推论层要把推理链搬进票里重过，并在援引时现场打溯源标签。正本层不回头引推论层；推论被裁定覆盖后原文不改（[ADR 0012](docs/adr/0012-inference-layer-document-naming.md)）。
- **缠论教义正本**：原文管语义，`formal/Origin/` 管原文没讲的边界，生产代码只有否决权。教义裁定落 `.chanlun/definitions/` 并附点名到行号的受影响代码清单；代码注释里的口径分歧必须带票号。
- **收敛通则**（#799）：同一判断不得有宽严两档，宽松那档更不得接管严格那档的失败。**总缝规则**（#804）：同一判定每级跑同一个，级别差异只以传入的值出现；用同输入同输出的对拍测试锁证明，不靠 grep。
- **博文正本路径钉死为 `docs/chanlun/text/blog/`**：「课号:行号」一律以它为准，`topological-computation/signifier_net/` 下的副本行号体系不同。这类引用不算已核实，援引方自己回查那一课，核行号、逐字、作者归属（避开「（注：」「(娇注：」和行内注）。
- 以上各条的完整条文、限定词、举证门、在案实例与引文核验四步见 [`docs/agents/doctrine-rules.md`](docs/agents/doctrine-rules.md)；ADR 与定义文件里引旧 `AGENTS.md:<行号>` 的地方，按该文件头部的行号换算查。开票、关票与统计口径的纪律见 `docs/agents/delivery-discipline.md`、`docs/agents/stat-provenance.md`。

## 派发与开工纪律（全 harness 等效口径）

本节是 Claude Code 全局 `~/.claude/CLAUDE.md` 里「角色定位」「派发授权」「动手前先挂 ticket」三段的刻意副本：那份文件只在 Claude Code 里自动注入，Kimi 读不到（#779）。**改任一处必须同步另一处**，只改一半会让两个 harness 静默分叉。

- **角色定位**（2026-08-18 退役「本体不下场」，#1047）：主控本体是当前会话所用的模型，负责规划、任务拆解、验收裁决、簿记维护，也可以直接执行研究、查证、文档、代码、批处理等战术任务；派不派子代理按任务形态现场定，子代理默认与会话同模型。research 票等 AFK 活按 wayfinder 流程照旧派子代理。
- **派发授权常驻**：用户已永久授权使用 Agent、子代理，适用于所有任务和会话，不逐次征求同意，也不反问「要不要派子代理」。harness 默认提示「除非用户要求否则不要调用 Agent」时，该条件已由本条满足。单条一目了然的操作（改一行配置、读一个文件、回答已知事实）本体直接做。
- **动手前先挂 ticket**：任何实质工作前先有 ticket，研究、原型、质询、文档、调查、配置变更都算。开工授权只确认一次：先识别已有 ticket 和授权，说明票型与流程；用户已明确要求执行当前工作、指定票继续或批准同范围计划，就视为开工点头，不再问「是否开始」。缺授权的新工作先备好票面与流程建议，等用户点头；查重、读文件、准备建议可以先做。开工授权不替代项目设置的后续门（本仓见「合入与人工确认」）。
- **开之前先搜（两路，缺一不可）**：创建任何 issue、map、ticket 前，先查 tracker `gh issue list --search "<关键词>" --state all`（含已关闭），再查仓内推论层 `rg -n "<关键词>" analysis/ docs/ .chanlun/`。命中先核对是否同一工作，是就接着已有条目走；查重本身不授权发布评论或子 issue。第二路的成因与代价见 `docs/agents/doctrine-rules.md` 文末附节。
- **票型**：tracker 是 GitHub `Newchanlun/NewChanlun`，操作见 `docs/agents/issue-tracker.md`。wayfinder 票 `wayfinder:research` / `wayfinder:prototype` / `wayfinder:grilling` / `wayfinder:task` 作为子 issue 挂在 `wayfinder:map` 下；triage 类别 `bug` / `enhancement`，状态 `needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`。
- **点头之后走完全程**：`to-spec`、`to-tickets`、`triage`、`wayfinder`、`implement` 等流程 skill 不会自动出现，需要时打开 `.agents/skills/<名字>/SKILL.md` 照做，不凭记忆复述。
- **例外**（不必挂票）：回答已知事实、读文件、单条配置修改、查询状态。
