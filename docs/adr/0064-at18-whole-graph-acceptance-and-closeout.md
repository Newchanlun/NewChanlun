# ADR 0064：AT-18 整图验收报告与关票门

> 正本：本文件是 #1323 AT-18 六项 Destination 逐项核验、TB-01..11 关票门、旧关联票去向与整图报告的正本。
> 最后裁定：以 PR #2065 合入 head 的正式门 `deepagents/review` 双审 PASS 为准（#1551，P 类，依 #1909 代理独审裁定，ADR 0041:41）
> 受影响代码清单：本 ADR 不直接改代码；报告生成与独立总验归 #1391 与 #1403，TB-07 汇总归 #1366，AT-14 原件归 #1418。

## 一、范围与现状

本 ADR 只裁验收证据、报告结构和关票簿记，不交付运行证据，不提前关闭 #1279、TB-11（#1369）或任何实施票。

ADR 0063 的迁移协议合入不等于 #1368 与 #1402 的非空迁移、回退与恢复已经验收。ADR 0058 的 AT-14 仓内报告路径继续有效。新整图报告与独立总验报告按现行仓外交付 manifest（`.sandcastle/CODEX-CHILD.md:54, :58-61`）管理，不将某台机器的绝对路径写成永久报告身份。

本 ADR 不签署真实资金、账户或场所激活、量档容量、成本与风险阈值及凭据权限；这些事项仍适用 ADR 0041:46 的独立用户授权硬门。

## 二、AT-18 逐项证据

每项 Destination 记录固定包含：Destination 编号与完整义务，实施票、范围与精确 commit，覆盖最终产品差异的非作者独评及所审 commit，实际 `origin/main` SHA 与适用 CI run，按 `evidence_class`（仅限 `simulation`、`experiment`、`production` 三值，拒收 `dry-run`）分列的实体报告引用，下游票状态与剩余义务，以及 `"PASS"` 或 `"FAIL"` 结论。

受测场所、隔离与带仓迁移证据须同时满足以下三项下游接口：

1. **证据类严格分列（ADR 0028:48, :70-71；ADR 0062:104, :258；ADR 0063:78-79, :120；CONTEXT.md:373-375）**。每条验收证据必须标明 `evidence_class`。`P1`（`experiment`，如 `P1-hl-testnet`）证据与 `production`（`P2`）证据在 Destination 记录、TB 汇总与整图报告中分槽记录，不得混记，不得以 `P1` 证据冒充生产有效，也不得将 `P1` 拒发语义外推为 `production` 已裁。已启用证据类槽位统一使用 `ArtifactRef[]` 数组（该槽位在当前记录无条目时填 `[]`）；未启用部署槽位（如本图 #1561 下尚未启用的 `production`）统一填 `null`，不得填 `[]`，并保留「生产首次新发送前」具名门。
2. **Destination ⑤ 权限证据三层与能力 hash（ADR 0062:51-79, :258-259）**。Destination ⑤（「目标部署的隔离和权限证据」及 paper 与 live 共核关系）按受测 `evidence_class` 分列核验三层权限证据：（a）授权声明，即场所 profile 记录中由用户签署的 `credential_scope.class` 与 `authorization` 行；（b）场所权限事实，即 #1770 能力记录 `session_permission` 来源栏登记的场所文档 URL、取回日期与 `sha256`；（c）运行时核验，即 X 库启动记录中发送门第 4 至 7 步核验结果与观测记录。三层分开记录，缺任一层或以一层替代另一层均不得记权限证据成立，Destination ⑤ 必须判 `"FAIL"`。整体验收的能力 hash 固定取 `(capability_record_version, capability_record_sha256, venue_profile_sha256)` 三元组，同版本异内容或顶层与 Destination ⑤ 分槽值不一致即判冲突失败。
3. **带仓迁移与回退四项不变量（ADR 0063:120, :123）**。涉及旧入口终态、发送隔离与带仓迁移的核验（Destination ②、③、⑤ 及 #1368、#1402）必须基于非空持仓、未结单、费用尾、中断恢复与回退的实际运行证据，逐项确认不丢权利、不复制资金、不双写、不补发四项同时成立，并按 `experiment` 与 `production` 分槽写入顶层 `migration_invariants`；空仓样例或仅合入协议文书不计通过。

组件证据、协议裁定、局部成功、正确拒绝、空域、仅 schema 或未执行测试均不得代替必需成功路径。缺证、跨证据类冒充或射程不符即不得判 `"PASS"`。

## 三、TB-01..11 关票门

关票通用门（`.sandcastle/docs/graph-engineering.md:237-241`）要求票面验收全部满足，全部必需子片交付，非作者评审覆盖最终产品差异，产品进入 `origin/main`，适用必需检查通过，实体报告可读并绑定版本，在制品已有合法处置。失败、未构造、未执行、权限阻塞及跨 TB 未闭合的联合义务必须保留为未完成，不得记为已处置失败。

为消除整图结论与 TB-11（#1369）关票门之间的自指循环（`.sandcastle/CODEX-CHILD.md:54`），并拦截未经 #1403 独立总验的自报通过（`.sandcastle/CODEX-CHILD.md:74`），`tb_summaries[]` 与 TB-11 关票按三阶段拆分：

- **`TB-01..TB-10` 独立关票门**。`tb_summaries[]` 中 `TB-01..TB-10` 每项固定核验 TB 编号与票号、全部内部实施子片、按 `evidence_class` 分列的完整外部行为实际运行证据（其中 TB-08、TB-09、TB-10 的 `experiment` 与 `production` 严格分槽，TB-10 并须在自身非空迁移证据上满足 ADR 0063:120 四项不变量）、最终非作者独评、实际 `origin/main` SHA、适用 CI run、各自已落地的实体报告（`entity_reports` 非空，`input_bundle` 固定为 `null`）、剩余义务与票状态。全部满足且票已合法关闭记 `gate_satisfied=true`；任一未满足记 `gate_satisfied=false` 并使整图判 `"FAIL"`。
- **`tb_summaries[TB-11]` 前置实施门（报告生成时）**。`tb_summaries[TB-11]` 只核验 TB-11 自身实施子片（#1391 逐项对账与报告生成器、#1403 独立总验器）在 `origin/main` 上的代码落地 SHA、适用 CI run、覆盖两子片最终代码差异的非作者独评，并在专用字段 `input_bundle` 中绑定供 #1391 与 #1403 共同消费的总验输入运行包清单 `ArtifactRef`（非 `null`）。整图运行证据归各 Destination 与 `TB-01..TB-10`，ADR 0063:120 四项不变量的整图复核只由顶层 `migration_invariants` 承载；因此 `tb_summaries[TB-11]` 的 `evidence_by_class` 在已启用证据类槽位固定填 `[]`、在未启用 `production` 槽位固定填 `null`，`entity_reports` 固定填 `[]`，不写入本次 `at18-report/1` 自身路径、`sha256` 或 `content_hash`，且只要求 #1391 已关闭、#1391 与 #1403 两子片代码均已进入 `origin/main`（`main_sha` 非 `null`），不要求 #1403 与 #1369 在报告生成前已关闭；候选分支运行尚未进入 `origin/main` 时必须记 `gate_satisfied=false`。
- **`#1403` 独立最终总验门（报告生成后、关票前）**。#1391 产出 `at18-report/1` 后，#1403 必须在独立总验会话中对确切 `origin/main` SHA、完整 `input_bundle` 及该份 `at18-report.json` 实际运行校验，输出仓外独立总验回执 `at18-verification/1`（单向绑定 `at18-report.json` 的文件 `sha256` 与 `content_hash`），经 #1403 仓外 delivery manifest 预检通过且获非作者最终独评 `PASS` 后，方可关闭 #1369、SPEC #1340 与 #1323。

## 四、旧关联票去向

- **#1304**：由 TB-07（#1366）完整历史回放、恢复、AsKnown、全状态对拍及 ADR 0058 AT-14 报告器（#1418）承接；上述证据全部验收前保持 `OPEN`。
- **#1319**：既有 feed 与 wire 由 TB-08 按实际代码核定收编或废弃，并作 TB-08 证据回填对象，不恢复其旧组织（ADR 0028:81；`.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md:344`）；正式意图与回报归 TB-04，发送前隔离归 TB-09，旧简化链不得冒充完整程序。
- **#1320**：正式完整程序回放由 TB-07（#1366 及 #1381、#1399、#1411、#1418）按 `history-input-profile/1` 承接，属整图通过必需项；ES、GC、CL、ZN、6E、BRN、DX 各十年 1min、冻结预注册 7 标的全量测量与完整结果保留按 `.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md:434`、ADR 0052:310, :357 与 ADR 0058:124 在本图 profile 外单列保留，由 TB-11 对账。组件有界测试与 TB-07 有界回放均不得将该重型测量销项；该重型测量未实际完成且无另行合法废弃裁定时，#1320 必须保持 `OPEN`，并在 `at18-report/1` 的 `unexecuted[]` 中单列记录且标 `required=false`（阻断将 #1320 关为已完成，不阻断本图整图通过）；若未完成且无合法废弃裁定却将 #1320 记为已销项或关闭，或漏记该单列未执行项，整图对账判 `"FAIL"`。
- **#1096**：由 TB-10 实际勘察并由 TB-11 对账；冻结或收编终态登记与未来实际删除分别举证，删除仍须满足 ADR 0048 退场条件。
- **#1279 与 `#1279 放行门`（`.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md:220, :344, :378`；`.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/inputs/SPEC-COVERAGE-INPUT.md:67`；ADR 0058:124；#1323:304, :309；#1279 评论 `5466854598`、`5501144382`、`5596452227`；#1403 验收第 4 条）**：`SPEC.md:378` 所称「#1279 放行门」即 `DST-06`（`US-DST-06` / `A-DST-06-01`）定义的下游试运行拦截门，包含三项必须同时取证成立的条件：（1）#1279 评论 `5596452227` 登记由 #1323 与 TB-11（#1369）交付的完整生产程序六项 Destination、确定性历史回放、账本与执行闭环及 `evidence_class` 分列运行证据已在本图 100% 实证闭合，零项 #1323 或 SPEC #1340 义务残留或转入 #1279；（2）在本图完成 #1403 独立总验前，以及在 #1279 自身超出本图射程的独立试运行检查单（含 #1279 评论 `5466854598` 所记尚未确立的跨资产 alpha 研究线与 #1279 自有试运行放行核查项）全部另行核实通过前，#1279 原生阻塞门持续生效，票状态保持 `OPEN`，未提前关图且未宣布试运行放行；（3）本图关闭只解除 #1279 上的 #1323 侧前置，不自动关闭 #1279、不宣告试运行放行，也不将 #1279 超出本图射程的自有检查单反向设为 TB-11 前置。`legacy_dispositions[]` 的 #1279 条目仅允许在 `remaining_obligations` 中列出不属于 #1323 与 SPEC #1340 射程的 #1279 自有未完检查项；若混入任何本图义务、#1279 在自身条件未齐时已关闭或已宣布试运行放行、或缺上述三项门控核验证据，则 `disposition_valid=false` 并使整图判 `"FAIL"`。

## 五、at18-report/1 与 at18-verification/1

整图报告采用具名版本化记录 `at18-report/1`，由机器可读 JSON（`at18-report.json`）和从同一份 JSON 确定性渲染的 `summary.md` 组成，人读摘要不作独立判定。新报告放仓外持久证据目录，由仓外 delivery manifest 以 `storage: "external"` 绑定 `ticket`、`base`、`head`、artifact 路径及文件字节 `sha256`（`.sandcastle/CODEX-CHILD.md:61`；`.sandcastle/delivery-bundle.ts:10-17, :27-35`）；移动或归档后更新 manifest 并重验。

规范化、`content_hash` 与封闭类型规则（对齐 ADR 0025:30 与 ADR 0058:193, :208）：

- **`content_hash` 无自指计算口径**。移除报告 JSON 顶层的 `content_hash` 键后，对其余完整 JSON 对象按 RFC 8785（JCS）规范化为 UTF-8 字节串，求 64 位小写十六进制 `sha256` 写入顶层 `content_hash`。`content_hash` 绑定结构化语义内容，仓外 delivery manifest 的 `sha256` 绑定落盘文件完整字节，两者均不将自身摘要纳入自身输入。
- **封闭字段集合与升版边界**。`at18-report/1` 与 `at18-verification/1` 的顶层和全部嵌套对象均为封闭字段集合，禁止未声明额外键；总验器（#1403）遇到缺失必填键、类型不符、枚举越界、长度不符、`content_hash` 不匹配或未声明额外键即拒收判 `"FAIL"`。新增、删除、重命名字段或改变字段语义均须升版为 `/2`。

共用子记录封闭类型定义如下（`Sha256Hex` 为匹配 `^[0-9a-f]{64}$` 的字符串，`GitCommitSha` 为匹配 `^[0-9a-f]{40}$` 的字符串，`EvidenceClass` 为 `"simulation" | "experiment" | "production"`）：

- `ArtifactRef`：`{storage: "in_repo" | "external", path: string, sha256: Sha256Hex, commit: GitCommitSha | null, bounded_scope: string}`。`storage="in_repo"` 用于 ADR 0058 既有仓内报告，`path` 为不含 `..` 的仓内相对路径，`commit` 必填 `origin/main` 上的 `GitCommitSha` 并核验 Git blob 摘要等于 `sha256`；`storage="external"` 用于仓外持久证据，`path` 为仓外持久证据目录下的无符号链接、无 `..` 绝对路径，`commit` 固定为 `null` 并核对仓外 delivery manifest 绑定（`.sandcastle/CODEX-CHILD.md:58-61`）。任一缺失、不可读或摘要不符即阻断，禁止跨存储方式回退。
- `EvidenceByClass`：`{simulation: ArtifactRef[], experiment: ArtifactRef[], production: ArtifactRef[] | null}`。已启用证据类槽位必填 `ArtifactRef[]`（无条目填 `[]`，不得填 `null`）；未启用部署槽位（#1561 下的 `production`）必填 `null`（不得填 `[]` 或非空数组）；`production` 经独立授权启用后同样必填 `ArtifactRef[]`。
- `CapabilityTuple`：`{capability_record_version: string, capability_record_sha256: Sha256Hex, venue_profile_sha256: Sha256Hex}`（ADR 0062:258）。
- `VenuePermissionFact`：`{source_url: string, retrieved_at: string, sha256: Sha256Hex}`（ADR 0062:51-79）。
- `PermissionSlot`：`{authorization_declaration: ArtifactRef, venue_permission_fact: VenuePermissionFact, runtime_verification: ArtifactRef, capability_hash: CapabilityTuple}`。
- `ReviewRef`：`{reviewer: string, reviewed_head: GitCommitSha, verdict: "PASS" | "BLOCK", artifact: ArtifactRef}`。
- `CiRunRef`：`{workflow: string, run_id: integer, head_sha: GitCommitSha, conclusion: string, url: string}`（`run_id` 为正整数）。
- `TicketScopeRef`：`{ticket: integer, scope: string}`（`ticket` 为正整数，下同）。
- `SliceStatusRef`：`{ticket: integer, state: "OPEN" | "CLOSED", main_sha: GitCommitSha | null}`。
- `DownstreamStatusRef`：`{ticket: integer, state: "OPEN" | "CLOSED"}`。
- `MigrationSlot`：`{no_lost_rights: boolean, no_duplicated_capital: boolean, no_dual_write: boolean, no_resend: boolean, non_empty_evidence_refs: ArtifactRef[]}`（ADR 0063:120）。
- `FailedCheck`：`{scope: string, check_id: string, detail: string, evidence_ref: ArtifactRef | null}`。

`at18-report/1` 顶层封闭字段集合固定为以下 16 键：

- `schema_version`（固定 `"at18-report/1"`）、`content_hash`（`Sha256Hex`）、`ticket`（正整数，取承载本次报告交付的票号，须与绑定本报告的仓外 delivery manifest 的 `ticket` 完全一致）、`base`（`GitCommitSha`，须与该 manifest 的 `base` 完全一致）、`head`（`GitCommitSha`，须与该 manifest 的 `head` 完全一致；正式整图通过报告的 `head` 必须等于对账时的实际 `origin/main` SHA，候选分支不得冒充 `origin/main`）、`generated_at`（RFC 3339 UTC 时间字符串）；
- `capability_hash`：`{experiment: CapabilityTuple | null, production: CapabilityTuple | null}`；已启用场所槽位填 `CapabilityTuple`，未启用槽位填 `null`，且须与 `destinations[]` 第 5 项（`id=5`）`permission_evidence` 对应槽位的 `capability_hash` 逐槽完全相等，不等即判 `"FAIL"`；
- 恰好 6 项、按 `id` `1..6` 升序排列的 `destinations[]`：每项固定 12 键 `{id: integer, obligation: string, tickets: TicketScopeRef[], commits: GitCommitSha[], independent_reviews: ReviewRef[], main_sha: GitCommitSha, ci_runs: CiRunRef[], evidence_by_class: EvidenceByClass, permission_evidence: {experiment: PermissionSlot | null, production: PermissionSlot | null} | null, downstream_status: DownstreamStatusRef[], remaining_obligations: string[], result: "PASS" | "FAIL"}`；仅 `id=5` 的 `permission_evidence` 为非 `null` 分槽对象（已启用场所槽位填 `PermissionSlot`，未启用槽位填 `null`），其余 5 项固定填 `null`；
- 恰好 11 项、按 `"TB-01".."TB-11"` 排列的 `tb_summaries[]`：每项固定 12 键 `{tb_id: string, ticket: integer, slices: SliceStatusRef[], input_bundle: ArtifactRef | null, evidence_by_class: EvidenceByClass, final_reviews: ReviewRef[], main_sha: GitCommitSha | null, ci_runs: CiRunRef[], entity_reports: ArtifactRef[], remaining_obligations: string[], ticket_state: "OPEN" | "CLOSED", gate_satisfied: boolean}`；`TB-01..TB-10` 的 `input_bundle` 固定填 `null` 且 `entity_reports` 非空，`TB-11` 按第三节在 `input_bundle` 填入非 `null` 总验输入运行包 `ArtifactRef`、`entity_reports` 固定填 `[]`；
- `migration_invariants`：`{experiment: MigrationSlot | null, production: MigrationSlot | null}`，已启用部署槽位填 `MigrationSlot`，未启用槽位填 `null`；
- 恰好 5 项、按 `[1096, 1304, 1319, 1320, 1279]` 顺序排列的 `legacy_dispositions[]`：每项固定 6 键 `{ticket: integer, disposition: string, evidence_refs: ArtifactRef[], ticket_state: "OPEN" | "CLOSED", remaining_obligations: string[], disposition_valid: boolean}`；
- `unexecuted[]`：元素类型为 `{obligation: string, reason: string, blocker_or_gap: string, evidence_class: EvidenceClass, required: boolean}`；
- `failed_checks[]`（元素类型为 `FailedCheck`）、`permission_blocked[]`（记录受权限阻塞的本图必需成功项，元素类型为 `{obligation: string, missing_authorization: string, blocker_ticket: integer, evidence_class: EvidenceClass}`）、`bounded_domain_statement`（非空字符串）；
- `overall_result`：`"PASS" | "FAIL"`。

`overall_result=PASS` 当且仅当以下条件同时成立：六项 `destinations[]` 的 `result` 全部为 `"PASS"`（在全部已启用受测部署槽位上，含本图 `P2` 未启用期间的 `experiment` 槽位，`id=5` 的三层权限证据齐全且其 `capability_hash` 与顶层 `capability_hash` 逐槽相等，顶层 `migration_invariants` 对应槽位的四项布尔值全为 `true` 且 `non_empty_evidence_refs` 非空）；`TB-01..TB-10` 全部 `gate_satisfied=true`、`ticket_state="CLOSED"` 且 `entity_reports` 非空，`TB-11` 满足第三节前置实施门且 `gate_satisfied=true`、`input_bundle` 非 `null`、`entity_reports=[]`；`experiment`（`P1`）与 `production`（`P2`）证据在全部字段中严格分槽且无跨类冒充（#1561 未启用期间全部 `production` 槽位均为 `null`，目标生产部署专属的「生产首次新发送前」具名门按 ADR 0028:71 以 `evidence_class="production"`、`required=false` 列入 `unexecuted[]`）；五项 `legacy_dispositions[]` 全部满足第四节规则且 `disposition_valid=true`（含 #1320 未完成单列重型测量时保持 `OPEN` 并以 `required=false` 记入 `unexecuted[]`，以及 #1279 满足第四节三项放行门条件且 `remaining_obligations` 不含任何本图义务）；`failed_checks` 为空数组 `[]`，`permission_blocked` 为空数组 `[]`，且 `unexecuted[]` 中不存在 `required=true` 的条目。任一检查失败必须写入 `failed_checks[]` 并强制 `overall_result` 为 `"FAIL"`。

#1403 独立总验输出的 `at18-verification/1`（`at18-verification.json`）固定为以下 11 键封闭对象：`{schema_version: "at18-verification/1", content_hash: Sha256Hex, ticket: integer, base: GitCommitSha, head: GitCommitSha, verified_at: string, report_ref: ArtifactRef, report_content_hash: Sha256Hex, input_bundle_ref: ArtifactRef, failed_checks: FailedCheck[], verdict: "PASS" | "FAIL"}`，其中 `content_hash` 采用与 `at18-report/1` 相同的无自指 JCS `sha256` 口径，`ticket`、`base`、`head` 与 #1403 的仓外 delivery manifest 一致且 `head` 等于被验报告的 `head`，`verdict="PASS"` 当且仅当被验 `at18-report.json` 通过全部封闭 schema、`content_hash`、证据摘要、Git 提交与业务判据复核且 `failed_checks` 为 `[]`。

TB-11（#1369）、SPEC #1340 与 #1323 的关票须在 #1391 已生成 `overall_result` 为 `"PASS"` 的 `at18-report/1`、#1403 已对该报告实际运行产出 `verdict` 为 `"PASS"` 的 `at18-verification/1`、两份仓外 delivery manifest 校验均通过（退出码 `0`）且 #1403 最终非作者独评为 `PASS` 后执行。关票评论须同时写明 `at18-report.json`（路径、文件 `sha256`、`content_hash`）与 `at18-verification.json`（路径、文件 `sha256`、`content_hash`、`verdict`）、实际 `origin/main` SHA、适用 CI run、最终非作者独评、`unexecuted[]` 明细及五张旧票去向；缺任一实体报告或独立总验未通过时写「无有效总验报告」，不得声明整图通过或关闭 #1369、#1340、#1323。

## 六、实施归属与图边

#1391 负责逐项对账与 `at18-report/1` 生成，#1403 负责对确切提交、完整 `input_bundle` 与 `at18-report/1` 执行独立最终总验并产出 `at18-verification/1`。#1366 负责 TB-07 汇总；按 ADR 0058:113，#1381 负责输入与 profile 装载，#1399 负责 seek/AsKnown，#1411 负责双进程与恢复，#1418 继续交付 AT-14 原件与回归锁。本 ADR 不新增或删除 blocking 边，不改变 TB 原 DAG，不把旧关联票整票设为 TB-11 新前置。
