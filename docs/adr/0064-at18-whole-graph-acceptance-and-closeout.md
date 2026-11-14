# ADR 0064：AT-18 整图验收报告与关票门

> 正本：本文件是 #1323 AT-18 六项 Destination 逐项核验、TB-01..11 关票门、旧关联票去向与整图报告的正本。
> 最后裁定：#1551（2026-11-14，P 类，依 #1909 代理独审裁定）
> 受影响代码清单：本 ADR 不直接改代码；报告生成与独立总验归 #1391/#1403，TB-07 汇总归 #1366，AT-14 原件归 #1418。

## 一、范围与现状

本 ADR 只裁验收证据、报告结构和簿记，不交付运行证据，不提前关闭 #1279、TB-11（#1369）或任何实施票。

ADR 0063 的迁移协议合入不等于 #1368/#1402 的非空迁移、回退与恢复已经验收。ADR 0058 的 AT-14 仓内报告路径继续有效；新整图报告按现行仓外交付 manifest（`.sandcastle/CODEX-CHILD.md`）管理，不将某台机器的绝对路径写成永久报告身份。

本 ADR 不签署真实资金、账户或场所激活、量档容量、成本/风险阈值及凭据权限；这些事项仍适用 ADR 0041 的独立用户授权硬门。

## 二、AT-18 逐项证据

每项 Destination 记录固定包含：Destination 编号与完整义务；实施票、范围与精确 commit；覆盖最终产品差异的非作者独评及所审 commit；实际 `origin/main` SHA 与适用 CI run；按 `evidence_class`（仅限 `simulation`、`experiment`、`production` 三值，拒收 `dry-run`）分列的实体报告 artifact 路径、`sha256` 和有界射程声明；下游票状态与剩余义务；`PASS|FAIL` 结论。

受测场所、隔离与带仓迁移证据须同时满足以下三项下游接口：

1. **证据类严格分列（ADR 0028:48/:71，ADR 0062:104/:258，ADR 0063:78-79/:120）**：每条验收证据必须标明 `evidence_class`。`P1`（`experiment`，如 `P1-hl-testnet`）证据与 `production`（`P2`）证据在 Destination 记录、TB 汇总与整图报告中分槽记录，不得混记，不得以 `P1` 证据冒充生产有效，也不得将 `P1` 拒发语义外推为 `production` 已裁。在本图 `P2` 未启用（#1561，ADR 0028:70-71）期间，受测实验部署证据写入 `experiment` 槽位，`production` 槽位保持为 `null` 并保留「生产首次新发送前」具名门。
2. **Destination ⑤ 权限证据三层与能力 hash（ADR 0062:51-79/:258-259）**：Destination ⑤（「目标部署的隔离和权限证据」及 paper/live 共核关系）按受测 `evidence_class` 分列核验三层权限证据：（a）授权声明，即场所 profile 记录中由用户签署的 `credential_scope.class` 与 `authorization` 行；（b）场所权限事实，即 #1770 能力记录 `session_permission` 来源栏登记的场所文档 URL、取回日期与 `sha256`；（c）运行时核验，即 X 库启动记录中发送门第 4 至 7 步核验结果与观测记录。三层分开记录，缺任一层或以一层替代另一层均不得记权限证据成立，Destination ⑤ 必须判 `FAIL`。整体验收的能力 hash 固定取 `(capability_record_version, capability_record_sha256, venue_profile_sha256)` 三元组，同版本异内容即判冲突失败。
3. **带仓迁移与回退四项不变量（ADR 0063:120/:123）**：涉及旧入口终态、发送隔离与带仓迁移的核验（Destination ②/③/⑤ 及 #1368/#1402）必须基于非空持仓、未结单、费用尾、中断恢复与回退的实际运行证据，逐项确认不丢权利、不复制资金、不双写、不补发四项同时成立，并按 `P1` 与 `production` 分列；空仓样例或仅合入协议文书不计通过。

组件证据、协议裁定、局部成功、正确拒绝、空域、仅 schema 或未执行测试均不得代替必需成功路径。缺证、跨证据类冒充或射程不符即不得判 `PASS`。

## 三、TB-01..11 关票门

每个 TB 汇总记录固定包含：TB 编号与票号、全部内部实施子片、按 `evidence_class` 分列的完整外部行为实际运行证据、最终非作者独评、实际 `origin/main` SHA、适用 CI run、实体报告绑定、剩余义务与当前票状态。其中 TB-08、TB-09、TB-10、TB-11 的 `P1`（`experiment`）与 `production`（`P2`）证据必须分列，TB-10 与 TB-11 并须核对 ADR 0063:120 的不丢权利、不复制资金、不双写、不补发四项非空行为证据。

关票通用门（`.sandcastle/docs/graph-engineering.md:237-241`）要求票面验收全部满足，全部必需子片交付，评审覆盖最终产品差异，产品进入 `origin/main`，适用必需检查通过，实体报告可读并绑定版本，在制品已有合法处置。失败、未构造、未执行、权限阻塞及跨 TB 未闭合的联合义务必须保留为未完成。

为消除整图结论与 TB-11（#1369）关票门之间的自指循环（`.sandcastle/CODEX-CHILD.md:54`），报告生成前后的核验层次拆分为：

- **`TB-01..TB-10` 独立关票门**：`TB-01..TB-10` 按上述关票通用门独立核验，在 `tb_summaries[]` 中绑定各自已落地的实体报告路径与 `sha256`；全部满足记 `gate_satisfied=true`，任一未满足如实记 `gate_satisfied=false` 并使整图判 `FAIL`。
- **`tb_summaries[TB-11]` 前置实施与独评门**：`tb_summaries[TB-11]` 只核验 TB-11 自身实施子片（#1391 逐项对账与报告器、#1403 独立总验器）的代码落地 `origin/main` SHA、适用 CI run、总验输入运行包，以及覆盖报告器与总验器最终代码差异的非作者独评（全部满足记 `gate_satisfied=true`，否则记 `false`）；该记录不含整图最终结论，不写入本次 `at18-report/1` 自身的路径、`sha256` 或 `content_hash`，`entity_reports` 固定为空数组 `[]`，且不要求 #1369 在报告生成前已关闭。#1369 在 `at18-report/1` 生成并经仓外 manifest 绑定后，再按第五节引用该报告执行关票。

## 四、旧关联票去向

- #1304：由 TB-07（#1366）完整历史回放、恢复、AsKnown、全状态对拍及 ADR 0058 AT-14 报告器（#1418）承接；证据未齐前保持 open。
- #1319：既有 feed/wire 由 TB-08 按实际代码核定收编或废弃，并作 TB-08 证据回填对象，不恢复其旧组织（ADR 0028:81；`.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md:344`）；正式意图/回报归 TB-04，发送前隔离归 TB-09，旧简化链不得冒充完整程序。
- #1320：正式完整程序回放由 TB-07（#1366 及 #1381/#1399/#1411/#1418）按 `history-input-profile/1` 承接，属整图通过必需项；ES/GC/CL/ZN/6E/BRN/DX 各十年 1min、冻结预注册 7/7 测量与完整结果保留按 `.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md:434`、ADR 0052:310/:357 与 ADR 0058:124 在本图 profile 外单列保留，由 TB-11 对账。组件有界测试与 TB-07 有界回放均不得将该重型测量销项：未实际完成且无另行合法废弃裁定时，#1320 必须保持 open，并在 `at18-report/1` 的 `unexecuted[]` 中单列记录且标 `required=false`（阻断将 #1320 关为已完成，不阻断本图整图通过）；若未完成且无合法废弃裁定却将 #1320 记为已销项或关闭，或漏记该单列未执行项，整图对账判 `FAIL`。
- #1096：TB-10 实际勘察、TB-11 对账；冻结/收编登记与未来实际删除分别举证，删除仍须满足 ADR 0048 退场条件。
- #1279：保持 open 至 #1323 与自身就绪检查完整验收；AT-18 通过不自动关闭它，也不宣布试运行放行。

## 五、at18-report/1

整图报告采用具名版本化记录 `at18-report/1`，由机器可读 JSON（`at18-report.json`）和从同一份 JSON 确定性渲染的 `summary.md` 组成，人读摘要不作独立判定。新报告放仓外持久证据目录，由仓外 delivery manifest 以 `storage: "external"` 绑定 `ticket`、`base`、`head`、artifact 路径及文件字节 `sha256`（`.sandcastle/CODEX-CHILD.md:61`）；移动或归档后更新 manifest 并重验。

规范化、`content_hash` 与升版规则（对齐 ADR 0025:30 与 ADR 0058:193/:208）：

- **`content_hash` 无自指计算口径**：移除报告 JSON 顶层的 `content_hash` 键后，对其余完整 JSON 对象按 RFC 8785（JCS）规范化为 UTF-8 字节串，求小写十六进制 `sha256` 写入顶层 `content_hash`。`content_hash` 绑定结构化语义内容，仓外 delivery manifest 的 `sha256` 绑定落盘文件完整字节，两者均不将自身摘要纳入自身输入。
- **封闭字段集合与升版边界**：`at18-report/1` 顶层与子记录的字段集合封闭，总验器（#1403）遇到缺失必填键、类型不符、`content_hash` 不匹配或未声明额外键即拒收判 `FAIL`；可空槽位（如未启用证据类）显式填 `null`，空列表显式填 `[]`。新增、删除、重命名字段或改变字段语义均须升版为 `at18-report/2`（改字段即升为 `at18-report/2`）。

`at18-report/1` JSON 的封闭字段集合如下：

- `schema_version`（固定 `"at18-report/1"`）、`content_hash`、`ticket`、`base`、`head`、`generated_at`；
- `capability_hash`：`{experiment, production}` 分槽对象；已启用场所槽位填 `{capability_record_version, capability_record_sha256, venue_profile_sha256}` 三元组（ADR 0062:258），未启用槽位（如 #1561 下的 `production`）填 `null`；
- 恰好六项的 `destinations[]`：每项含 `{id, obligation, tickets, commits, independent_reviews, main_sha, ci_runs, evidence_by_class, permission_evidence, downstream_status, remaining_obligations, result}`；`evidence_by_class` 按 `{simulation, experiment, production}` 分槽列出 `{path, sha256, bounded_scope}` 数组，Destination ⑤ 的 `permission_evidence` 为 `{experiment, production}` 分槽对象（已启用场所槽位含 `{authorization_declaration, venue_permission_fact, runtime_verification, capability_hash}`，未启用槽位填 `null`），其余五项 Destination 的 `permission_evidence` 填 `null`；
- 恰好十一项的 `tb_summaries[]`：每项含 `{tb_id, ticket, slices, evidence_by_class, final_reviews, main_sha, ci_runs, entity_reports, remaining_obligations, ticket_state, gate_satisfied}`；`TB-01..TB-10` 绑定完整关票门与各自实体报告，`TB-11` 按第三节只绑定 #1391/#1403 子片的 `main_sha`、`ci_runs`、总验输入运行包与代码 `final_reviews`，`entity_reports` 固定为 `[]`；
- `migration_invariants`：`{experiment, production}` 分槽对象，受测槽位含 `{no_lost_rights, no_duplicated_capital, no_dual_write, no_resend, non_empty_evidence_refs}`（ADR 0063:120），未启用槽位填 `null`；
- `legacy_dispositions[]`：固定五项，覆盖 #1096、#1304、#1319、#1320、#1279，每项含 `{ticket, disposition, evidence_refs, ticket_state, remaining_obligations, disposition_valid}`；
- `unexecuted[]`：每项含 `{obligation, reason, blocker_or_gap, evidence_class, required}`；
- `failed_checks[]`（每项含 `{scope, check_id, detail, evidence_ref}`）、`permission_blocked[]`（记录受权限阻塞的本图必需成功项，每项含 `{obligation, missing_authorization, blocker_ticket, evidence_class}`）、`bounded_domain_statement`；
- `overall_result: PASS|FAIL`。

`overall_result=PASS` 当且仅当：六 Destination 全部 `PASS`（在已启用受测部署槽位上，含本图 `P2` 未启用期间的 `experiment` 槽位，Destination ⑤ 三层权限证据与 `capability_hash` 三元组齐全，且 ADR 0063 四项迁移回退不变量在非空证据上成立）；`TB-01..TB-10` 均满足第三节完整关票门（`gate_satisfied=true`），且 `TB-11` 满足第三节规定的子片主线落地、适用 CI、运行包与代码独评前置条件（`gate_satisfied=true`）；`P1`（`experiment`）与 `production`（`P2`）证据在全部记录中严格分列且无跨类冒充（`#1561` 未启用期间 `production` 槽位保持为 `null`，目标生产部署专属的「生产首次新发送前」具名门按 ADR 0028:71 以 `evidence_class="production"`、`required=false` 如实列入 `unexecuted[]`）；四张旧工作线（#1096、#1304、#1319、#1320）均满足第四节核实的合法终态、真实承接及单列义务对账规则（含 #1320 未完成单列重型测量时保持 open 并以 `required=false` 记入 `unexecuted[]`），#1279 保持 open 且剩余就绪义务如实列出；所有 `required=true` 的未执行项、未处置失败和权限阻塞均为空。

TB-11（#1369）关票须在 `at18-report/1` 已生成、整图结论为 `PASS` 且仓外 delivery manifest 校验通过后执行；关票评论须写明 manifest 绑定的报告 artifact 路径、文件 `sha256` 与 `content_hash`、实际 `origin/main` SHA、适用 CI run、最终独评、未执行项及五张旧票去向；无实体报告即写「无报告」，不得声明整图通过或关闭 #1369。

## 六、实施归属与图边

#1391 负责逐项对账与 `at18-report/1` 生成，#1403 负责确切提交、完整运行包与报告封闭 schema/`content_hash` 的独立总验。#1366 负责 TB-07 汇总，#1381/#1399/#1411 分别保留完整回放、seek/修订重算、双进程崩溃恢复的既有实施义务；#1418 继续交付 AT-14 原件。本 ADR 不新增或删除 blocking 边，不改变 TB 原 DAG，不把旧关联票整票设为 TB-11 新前置。
