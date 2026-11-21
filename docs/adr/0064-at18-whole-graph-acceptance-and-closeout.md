# ADR 0064：AT-18 整图验收报告与关票门

> 正本：本文件是 #1323 AT-18 六项 Destination 逐项核验、TB-01..11 关票门、旧关联票去向与整图报告的正本。
> 最后裁定：以 PR #2065 合入 head 的正式门 `deepagents/review` 双审 PASS 为准（#1551，P 类，依 #1909 代理独审裁定，ADR 0041:41）
> 受影响代码清单：本 ADR 不直接改产品代码；#2131 负责登记册、lint、运行器和 workflow，#2132 负责 TB-01 绑定及闸前复审，#1391/#1403 负责生成与独立总验，#1366/#1418 保留 TB-07/AT-14 合同。

## 一、范围与现状

本 ADR 只裁验收证据、报告结构和关票簿记，不交付运行证据，不提前关闭 #1279、TB-11（#1369）或任何实施票。

ADR 0063 的迁移协议合入不等于 #1368 与 #1402 的非空迁移、回退与恢复已经验收。ADR 0058 的 AT-14 仓内报告路径继续有效。新整图输入包、整图报告与独立总验报告按现行仓外交付 manifest（`.sandcastle/CODEX-CHILD.md:54, :58-63`）管理，不将某台机器的绝对路径写成永久报告身份。

本 ADR 不签署真实资金、账户或场所激活、量档容量、成本与风险阈值、闸门后参数值及凭据权限；这些事项仍适用 ADR 0036:29-33 与 ADR 0041:46 的授权硬门。

## 二、AT-18 逐项证据与整图覆盖义务

**读法裁定。** SPEC #1340 正文第 432 行的「实装、最终独评、落地主线及适用 CI」指报告所验的实际主线头 **F**：每项 Destination 对 F 上的最终行为、独评覆盖、主线 CI、实体报告及下游状态逐项求值。第 380 行要求 TB-11 汇集实施及独评；不要求在历史落地时点逐片重证 CI。通用交付门仍照 `.sandcastle/docs/graph-engineering.md:15, :237-241`，历史没有绿灯就不得写成当时通过。要求按历史提交重证会使当前验收不可达：R11 的历史原件仍有红灯与无运行，闸前版 DevSkim 也没有手动触发；F 的绿灯不回写为历史合规。#1551 退回裁定见评论 7047086314。

六条 Destination 仍各自有完整义务、实施范围、证据类、相关票态、未完义务与 PASS/FAIL。F 的检查承担当下可重复的行为证明；第六节 R09 核闸后的主线集成，R10 按实际落地与 F 留存路径核闸前复审，两门必须同时满足。片的历史落地列作出处，不拿它的 CI、独评或 manifest 当 F 的证明。

受测场所、隔离、带仓迁移、闸门后参数与 SPEC 全量覆盖核验须同时满足以下五项接口：

1. **证据类严格分列（ADR 0028:48, :70-71；ADR 0062:104, :258；ADR 0063:78-79, :120；CONTEXT.md:373-375）**。每条验收证据必须标明 `evidence_class`。`P1`（`experiment`，如 `P1-hl-testnet`）证据与 `production`（`P2`）证据在 Destination 记录、TB 汇总与整图报告中分槽记录，不得混记，不得以 `P1` 证据冒充生产有效，也不得将 `P1` 拒发语义外推为 `production` 已裁。已启用证据类槽位统一使用 `ArtifactRef[]` 数组（该槽位在当前记录无条目时填 `[]`）；未启用部署槽位（如本图 #1561 下尚未启用的 `production`）统一填 `null`，不得填 `[]`，并保留「生产首次新发送前」具名门。
2. **Destination ⑤ 权限证据三层与能力 hash（ADR 0062:51-79, :258-259）**。Destination ⑤（「目标部署的隔离和权限证据」及 paper 与 live 共核关系）按受测 `evidence_class` 分列核验三层权限证据：（a）授权声明，即场所 profile 记录中由用户签署的 `credential_scope.class` 与 `authorization` 行；（b）场所权限事实，即 #1770 能力记录 `session_permission` 来源栏登记的场所文档 URL、取回日期与 `sha256`；（c）运行时核验，即 X 库启动记录中发送门第 4 至 7 步核验结果与观测记录。三层分开记录，缺任一层或以一层替代另一层均不得记权限证据成立，Destination ⑤ 必须判 `"FAIL"`；已启用场所槽位缺某层证据或缺能力记录时，按第五节 `PermissionSlot` 规则把该层字段或 `capability_hash` 填 `null` 记录缺失，不把整个槽位填 `null`。整体验收的能力 hash 固定取 `(capability_record_version, capability_record_sha256, venue_profile_sha256)` 三元组，同版本异内容或顶层与 Destination ⑤ 分槽值不一致即判冲突失败。
3. **带仓迁移与回退四项不变量（ADR 0063:120, :123）**。涉及旧入口终态、发送隔离与带仓迁移的核验（Destination ②、③、⑤ 及 #1368、#1402）必须基于非空持仓、未结单、费用尾、中断恢复与回退的实际运行证据，逐项确认不丢权利、不复制资金、不双写、不补发四项同时成立，并按 `experiment` 与 `production` 分槽写入顶层 `migration_invariants`；空仓样例或仅合入协议文书不计通过。
4. **闸门后参数触达与启用三记录核验（ADR 0036:25-33, :42）**。TB-11 整图对账与关图按已启用 `experiment`、`production` 部署槽位分槽核验闸门后参数协议，每个槽位恰好处于 `PostGateSlot.status` 四种状态之一：（1）`TRIGGERED_AND_ENABLED`，该 profile 下已启用阶段能力（`growth_enabled=true`）或声明闸门后参数生效时只能取此状态，必须同时出示同一 `profile_id` 与 `evidence_class` 下持久互引的触达事件（`GateReachedEvent`）、参数版本与首次启用三条记录，且严格满足 `触达.known_at < 版本.authorized_at < 首次启用.known_at`（`TestOnly` 或历史双跑的 `SimulatedGateReached` 不计激活，`experiment` 版本不得自动迁入 `production`）；（2）`TRIGGERED_VERSION_AUTHORIZED`，即已发生 `GateReachedEvent` 且参数版本已授权落盘，但首次启用尚未记录（ADR 0036:28, :33），必须出示触达事件与参数版本两条记录，满足 `触达.known_at < 版本.authorized_at`，并核实 `growth_enabled=false`；（3）`TRIGGERED_AWAITING_POLICY`，即已发生 `GateReachedEvent` 但尚未签署参数版本，必须核实输出保持 `AwaitingPolicy{post_gate_params}` 且 `growth_enabled=false`；（4）`NOT_TRIGGERED`，即该受测运行未触发 `growth_eligible=true`，必须出示未触达与未启用证据。状态（2）至（4）均不按已激活处理，必须在 `bounded_domain_statement` 如实记账，并在 `unexecuted[]` 以 `required=false` 列入该槽位的 `ADR_0036_POST_GATE_EXPERIMENT` 或 `ADR_0036_POST_GATE_PRODUCTION` 条目（常量见第五节 `unexecuted[]`）。本条是 ADR 0036:33「TB-11 关图须出示三条记录」的适用范围读法：对 `growth_enabled=true` 或声明闸门后参数生效的每个槽位，三条记录是必出项；对闸门未触达或阶段能力尚未启用的槽位，关图义务由未启用证据（`non_activation_evidence`）与上述 `required=false` 条目销项。
5. **97 故事、345 family 条目与 496 细项逐项对账（`.chanlun/review-results/issue1340-publication-20260909/view/inputs/TB07-11-EXECUTION-SLICES.md:278, :290`；`.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/IMPLEMENTATION-CROSSWALK.md:5, :115`）**。#1391 必须对照 `IMPLEMENTATION-CROSSWALK.json` 逐条核完 97 个故事、345 个 family 条目与 496 个细项验收输入，写入顶层 `spec_coverage` 供 #1403 逐条复核。crosswalk 条目带 `exclusion_boundary=true` 的 family 条目（所绑定 crosswalk 上是 `OE41` 与 `OE45`）只核排除与防混用边界，其余 family 条目全部是必需条目。`OE42` 是必需条目，#1391 须核实覆盖输入为它登记的 `OUT_OF_SCOPE_PRESERVE` 处分得到遵守（规则见第五节 `SpecCoverageLedger`）。不得仅凭测试计数、子票关闭率或 `N=2` 样例代替逐子义务核验。

组件证据、协议裁定、局部成功、正确拒绝、空域、仅 schema 或未执行测试均不得代替必需成功路径。缺证、跨证据类冒充或射程不符即不得判 `"PASS"`。

## 三、TB-01..11 关票门

关票通用门（`.sandcastle/docs/graph-engineering.md:237-241`）要求票面验收全部满足，全部必需子片交付，非作者评审覆盖最终产品差异，产品进入 `origin/main`，适用必需检查通过，实体报告可读并绑定版本，在制品已有合法处置。失败、未构造、未执行、权限阻塞及跨 TB 未闭合的联合义务必须保留为未完成，不得记为已处置失败。

关票分三阶段，不以任一后置产物证明其前置：

1. **TB-01..10**：按 R12 逐片核原生子票、最终主线行为、实体报告、审查覆盖和各自剩余义务。TB-08..10 的 experiment 必须有本类实测；TB-10 另核本片非空迁移，不能借其他切片证据。
2. **TB-11 前置**：按 R12 只核代码、F 的通用 CI 与独评覆盖、输入包；`gate_satisfied=true` 只代表前置齐备。生成报告时 #1391 应 OPEN，不要求 #1403 或 #1369 先关；TB-11 的 `entity_reports=[]`、已启用证据类数组 `[]`、未启用 production 槽 `null`。无输入包填 `null`，不得引用当前报告自身或总验回执。
3. **封包与关图**：#1391 在 F 上产出报告和输入包，`overall_result=PASS` 且经本票交付预检与非作者最终独评后关 #1391；#1403 独立读取原件，对同一 F 和同一验收窗口运行总验，`verdict=PASS` 且经本票交付预检与非作者最终独评后关 #1403。两者均为 PASS 且结果和票态在同一窗口复核有效后，方可依次关闭 #1369、#1340、#1323。该步骤的独评是对两份实际交付的非作者评审，不能用 R09 的产品集成审查代替。


## 四、旧关联票去向

`TB-11-A`（`.chanlun/review-results/issue1340-publication-20260909/view/inputs/TB07-11-EXECUTION-SLICES.md:291-293`；`.chanlun/review-results/issue1340-publication-20260909/view/inputs/LEGACY-TICKET-DISPOSITION.md:88-96, :106`）涉及的七张旧关联票固定按以下边界核验：

- **#942**：保持 `CLOSED` 及既有逐问处分（编排者后裁「乙」接受文档推断加子账户显式 `standard` 防御性初始化，第 1、3、5 问因凭据约束不做，第 2 问已测未决，第 4 问强平实验明确不做，第 6、7 问按 `.chanlun/review-results/hl-margin-table-disabledex-20260808.md` 有界文档推理关闭，第 8 至 10 问挂 #953 等既有承接）。严禁把已关闭的 #942 表述为两家场所隔离已实测完成，也严禁借 #1319 恢复已拒绝的强平实验；受测场所能力与隔离一律按第二节 Destination ⑤ 三层权限证据及 TB-09 独立核验。
- **#1096**：由 TB-10 实际勘察并由 TB-11 对账；冻结或收编终态登记与未来实际删除分别举证，删除仍须满足 ADR 0048 退场条件。
- **#1282**：保持 `CLOSED`、冻结预注册判据（7 标的全部越过各自随机中位及双对照设计）与 #1279 历史实验落档结论，不重开旧翻转实验选择，也不得将该 M1 历史研究结论冒充本图新完整生产程序的回放或试运行验收证据。
- **#1304**：由 TB-07（#1366）完整历史回放、恢复、AsKnown、全状态对拍及 ADR 0058 AT-14 报告器（#1418）承接，#1282 旧翻转实验归档边界保持不变；上述本图承接证据、验收报告器及回归锁载体全部核实前保持 `OPEN`。
- **#1319**：既有 feed 与 wire 由 TB-08 按实际代码核定收编或废弃，并作 TB-08 证据回填对象，不恢复其旧组织（ADR 0028:81；`.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md:344`）；正式意图与回报归 TB-04，发送前隔离归 TB-09，其中涉及 #942 的可测项严格遵守 #942 既有处分，旧简化链不得冒充完整程序。
- **#1320**：正式完整程序回放由 TB-07（#1366 及 #1381、#1399、#1411、#1418）按 `history-input-profile/1` 承接，属整图通过必需项；ES、GC、CL、ZN、6E、BRN、DX 各十年 1min、冻结预注册 7 标的全量测量与完整结果保留按 `.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md:434`、ADR 0052:310, :357 与 ADR 0058:124 在本图 profile 外单列保留，由 TB-11 对账。组件有界测试与 TB-07 有界回放均不得将该重型测量销项；该重型测量未实际完成且无另行合法废弃裁定时，#1320 必须保持 `OPEN`，并在 `at18-report/1` 的 `unexecuted[]` 中以 `obligation="ISSUE_1320_HEAVY_MEASUREMENT"`、`required=false` 单列记录（阻断将 #1320 关为已完成，不阻断本图整图通过）；若未完成且无合法废弃裁定却将 #1320 记为已销项或关闭，或漏记该单列未执行项，整图对账判 `"FAIL"`。
- **#1279 与 `#1279 放行门`（`.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md:220, :344, :378`；`.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/inputs/SPEC-COVERAGE-INPUT.md:67`；ADR 0058:66, :124；#1323:304（「#1319/#1320/#1279 继续受本图约束。#1279 不关图、不宣布试运行放行」一句，ADR 0058:66 已逐字引录；#1323 正文行号随编辑漂移时以该引录为准）；#1279 评论 `5466854598`、`5501144382`、`5596452227`；#1403 验收第 4 条）**：`SPEC.md:378` 所称「#1279 放行门」即 `DST-06`（`US-DST-06` 与 `A-DST-06-01`）定义的下游试运行拦截门，按报告阶段与关图阶段分层核验：（1）在 #1391 生成报告及 #1403 复核阶段，#1279 评论 `5596452227` 登记归属 #1323 与 SPEC #1340 的六项 Destination、确定性历史回放、账本与执行闭环及 `evidence_class` 分列运行证据由 R13 从各 Destination 聚合前的条目、TB 门和专用门逐项证成（不读任何 Destination 的成品结论），`legacy_dispositions[]` 的 #1279 条目在 `remaining_obligations` 中零项混入 #1323 或 SPEC #1340 义务（仅列出不属于本图射程的 #1279 自有未完检查项，含评论 `5466854598` 所记跨资产 alpha 研究线及自有试运行核查项）；（2）#1279 当前 `ticket_state` 保持 `"OPEN"`，未提前关图且未宣布试运行放行，也不将超出本图射程的 #1279 自有检查单反向设为 TB-11 前置（以上两项同时成立时报告记 #1279 的 `disposition_valid=true`）；（3）在关图阶段，仅当 #1403 独立总验产出 `verdict="PASS"` 并完成 #1369、#1340、#1323 关闭后，才解除 #1279 上的 #1323 侧前置，且解除前置仍不自动关闭 #1279 或宣告试运行放行。若 `remaining_obligations` 混入任何本图义务、#1279 在自身条件未齐时已关闭或已宣布试运行放行，则 `disposition_valid=false` 并使整图判 `"FAIL"`。

## 五、`at18-input-bundle/1`、`at18-report/1` 与 `at18-verification/1`

整图对账与独立总验采用三份具名版本化仓外记录：输入运行包清单 `at18-input-bundle/1`（`at18-input-bundle.json`）、整图验收报告 `at18-report/1`（`at18-report.json` 及从同一份 JSON 渲染的 `summary.md`，自然语言说明不进入判定或比较）和独立总验回执 `at18-verification/1`（`at18-verification.json`）。三份产物均置于仓外持久证据目录，按 `.sandcastle/CODEX-CHILD.md:56-63` 与 `.sandcastle/delivery-bundle.ts:10-17, :27-38` 由所属票的仓外 delivery manifest 以 `storage: "external"` 绑定 `ticket`、`base`、`head`、路径及文件字节 `sha256`；移动或归档后更新 manifest 并重验。

规范化、`content_hash`、提交祖先与封闭类型规则（对齐 ADR 0025:30 与 ADR 0058:193, :208）：

- **`content_hash` 无自指计算口径**。对 `at18-input-bundle/1`、`at18-report/1` 或 `at18-verification/1` 移除各自顶层 `content_hash` 键后，将其余完整 JSON 对象按 RFC 8785（JCS）规范化为 UTF-8 字节串，求 64 位小写十六进制 `sha256` 写入顶层 `content_hash`。`content_hash` 绑定结构化语义内容，仓外 delivery manifest 的 `sha256` 绑定落盘文件完整字节，两者均不产生自指循环。
- **封闭字段集合与升版边界**。三份 schema 的顶层和全部嵌套对象均为封闭字段集合，禁止未声明额外键；总验器（#1403）遇到缺失必填键、类型不符、枚举越界、固定长度数组长度不符、`content_hash` 不匹配或未声明额外键即拒收判 `"FAIL"`，并按下条输出回执。本稿在首份正式 /1 报告发布前定义 /1；旧候选不兼容。正式启用后，新增、删除、重命名字段或改变字段语义须升版。
- **形状规则与判定规则分层**。本 ADR 的约束分两层。形状规则只有以下几类：三份 schema 顶层与全部嵌套对象的封闭键集；各字段的声明类型（含 `Sha256Hex`、`GitCommitSha`、`UtcTimestamp` 的格式、正整数，以及 `ArtifactRef` 按 `storage` 区分的 `commit`、`ticket`、`base`、`head` 取值组合）；枚举取值；`schema_version` 常量；文档自身 `content_hash` 按上条口径与其内容相符；`destinations[]` 6 项、`tb_summaries[]` 11 项、`legacy_dispositions[]` 7 项与 `workflow_runs[]` 4 项的固定长度与顺序；写入方自己决定的常量与槽位编码（如 `TB-01..TB-10` 的 `input_bundle` 固定填 `null`、未启用槽位填 `null`）。只有违反形状规则的文档形状不合法，由 #1403 拒收。其余约束都是判定规则，包括字段非 `null`、数组非空、跨字段或跨文档相等、哈希或摘要相符、文件可读、命中 manifest、祖先关系、时序、与 crosswalk 逐条对应的项数，以及状态与证据的搭配。判定规则不满足时照常写出记录：字段记实际观测值，证据缺失或不可读处按字段类型填 `null` 或 `[]`，在 `failed_checks[]` 写入一项 `FailedCheck`，所在记录的结论取失败值（报告 `overall_result="FAIL"`、回执 `verdict="FAIL"`、TB 汇总 `gate_satisfied=false`、覆盖条目 `status="FAIL"`）。本 ADR 写作「PASS 要求」的条件，以及落在判定规则上的「必须」「须」「非 `null`」「非空」「等于」「一致」「恰好」，都只约束取通过值的记录，不约束失败记录的形状。每份文档的身份字段（`schema_version`、`content_hash`、`ticket`、`base`、`head` 与 `generated_at` 或 `verified_at`）只取自该文档自身及登记它的本票仓外 delivery manifest，始终非 `null`，取不到时不写出该文档（见下条「引导前提与无文档结果」）；它与其他文档的任何关系（`head` 相等、哈希相符、命中 manifest）都是判定规则。输入包不承载结论，必需输入缺失时不生成输入包，由报告的 `tb_summaries[TB-11].input_bundle` 与回执的 `input_bundle_ref` 填 `null` 记录缺失。#1403 引导成功后，遇到受验对象缺失、不可读或形状不合法时，仍输出形状合法的 `at18-verification/1`：身份字段取自 #1403 自身 manifest；#1391 的 delivery manifest 可读且通过 `deliveryManifestSchema` 校验时，`report_manifest` 填指向它的 `ManifestRef`，否则填 `null`；`report_ref` 与 `input_bundle_ref` 照录该 manifest 中形状合法的对应登记，无此登记时填 `null`；`report_content_hash` 按下文「派生值」规则取重算值或 `null`；每个缺失、不可读或形状不合法的受验对象各写一项 `FailedCheck`（`scope` 写明受验对象与字段路径），并判 `verdict="FAIL"`。
- **引导前提与无文档结果**。上条「照常写出记录」以写入方能写出形状合法的文档为前提；本条定义该前提不成立时的唯一结果。#1391 写出 `at18-input-bundle/1` 与 `at18-report/1`、#1403 写出 `at18-verification/1` 之前先完成引导，依次为：（1）读取本票仓外 delivery manifest（此时可尚未登记本次产物），它须可读且通过 `deliveryManifestSchema` 校验；已登记的每个 artifact 均按 `.sandcastle/delivery-bundle.ts:189-240` 核合法声明、版本、可读实体与字节摘要，未登记的本次输出不在此步核 `:242-245` 的必需报告完整性（完成封包时仍全量预检）。文档的 `ticket`、`base`、`head` 只取自它，不取自受验对象、调用参数、环境变量或当前 Git 状态（`HEAD`、分支、`origin/main`）；（2）写 `at18-report/1` 时，`destinations[]`、`tb_summaries[]`、`legacy_dispositions[]` 各固定项中类型不含 `null` 的非结论字段（`id`、`obligation`、`tb_id`、`ticket`、`disposition`）均取得实际值，取不到时不以猜测值代填；（3）待写内容能按本节 `content_hash` 口径规范化，写入方照录的字符串含孤立代理码点等不能规范化的内容时不原样写入，改在 `FailedCheck.detail` 中描述，如此处理后仍不能规范化才算本步失败；（4）先写临时文件，再改名到输出路径。任一步失败时，该工具不写出该类型文档，输出路径上不出现该文档；它沿用 `.sandcastle/delivery-bundle.ts:116-132` 预检失败载体，在标准输出写出 `status: "BLOCKED"` 与 `diagnostics[]`（元素为同文件的 `DeliveryDiagnostic`，`code` 按上述四步依次取 `MANIFEST_UNREADABLE` 或 `INVALID_MANIFEST`，以及 `UNDECLARED_REPORT`、`REPORT_DECLARATION_MISMATCH`、`REPORT_VERSION_MISMATCH`、`INVALID_REPORT_PATH`、`REPORT_NOT_REGULAR_FILE`、`REPORT_MISSING`、`REPORT_NOT_IN_HEAD`、`REPORT_HASH_MISMATCH`（各按前述预检对应条件）；第（2）至（4）步分别用`FIXED_ITEM_UNAVAILABLE`、`CONTENT_NOT_CANONICAL`、`OUTPUT_WRITE_FAILED`），并以退出码 `1` 结束（与 `.sandcastle/delivery-bundle.mts:13` 对 `BLOCKED` 的退出码相同）。第（1）步失败时 #1391 两份文档都不写出。引导与写入使用未含本次产物的新输出目录，不以旧文件冒充本轮结果。消费方以输出路径上有无该文档判断，不从退出码推断；`BLOCKED` 载体不是文档，不得登记进 delivery manifest，也不能代替输入包、报告或回执。各消费方对缺失文档的处理如下：没有输入包时，报告的 `tb_summaries[TB-11].input_bundle` 与回执的 `input_bundle_ref` 填 `null` 并判失败；没有报告时，#1403 按受验对象缺失输出 `verdict="FAIL"` 的回执；没有回执时不存在 `verdict="PASS"` 的 `at18-verification/1`，本节末段关票门不成立。引导成功后，才适用「受验对象缺失、不可读或形状不合法时仍输出 12 键 `verdict="FAIL"` 回执」。
- **派生值**。由另一份产物计算得出的字段，只在计算链每一步都对该产物现有字节成功、且未作任何修复时取计算值；任一步失败时取该字段的缺失值，写一项 `FailedCheck`（`check_id` 为失败步骤 `FILE_READ`、`JSON_PARSE`、`JCS_CANONICALIZE` 或 `SCHEMA`，`detail` 写失败结果），所在记录取失败值。四步依次为：读取文件（`storage="in_repo"` 时读取 `commit` 上的 Git blob）；严格解析为 JSON 对象（RFC 8259 语法、合法 UTF-8、无重复键、顶层为对象，不以后出现的重复键覆盖前者）；按 RFC 8785 规范化（`1e400` 等非有限数值与 `"\ud800"` 等孤立代理码点在此步失败，不得用 `JSON.stringify` 把非有限数值写成 `null` 或保留坏码点冒充成功）；按所属 schema 校验。各派生字段只走自己需要的步骤：文件字节摘要（`ArtifactRef.sha256`、`ManifestRef.manifest_sha256`、`VenuePermissionFact.sha256`、`CapabilityTuple` 的两个 `sha256`、`SpecCoverageLedger.crosswalk_sha256`，以及 `tb_summaries[TB-11].input_bundle` 的摘要）只需读取；`report_content_hash` 需读取、解析与规范化，不经 schema，故 schema 不合法但能规范化的报告保留重算值；`report_manifest`、照录自它的 `report_ref` 与 `input_bundle_ref`，以及 `external_manifests[]` 各项需全部四步（schema 为 `deliveryManifestSchema`）；`spec_coverage` 的 `stories`、`families`、`details`（含项数、顺序与 `entry_mode`）、`CapabilityTuple.capability_record_version`、`VenuePermissionFact` 的 `source_url` 与 `retrieved_at`、`PostGateSlot` 的三个时间戳需读取、解析与所用字段的校验。缺失值按声明类型取：可空字段填 `null`，数组填 `[]`；`ArtifactRef`、`ManifestRef`、`CapabilityTuple` 或 `VenuePermissionFact` 的任一字段算不出时整条不写，所在可空字段填 `null`，所在数组不列该项；可变长数组的元素有类型不含 `null` 的字段取不到时，不列该元素（如从未观测到状态的 `ReviewRef`）。`at18-input-bundle/1` 的 `spec_ref`、`crosswalk_ref`、`coverage_input_ref`、`registry_ref`、`pregate_review_ref` 与必需切片账引用不可为 `null`，任一算不出时按「形状规则与判定规则分层」不生成输入包；这是判定失败，不是引导失败，不出 `BLOCKED`。文档自身的 `content_hash` 不是派生值，由「引导前提与无文档结果」第（3）步约束。
- **`origin/main` 祖先提交一致性**。正式通过报告顶层 `head` 必须等于对账时的实际 `origin/main` SHA；报告内全部 `destinations[].main_sha`、`destinations[].commits[]`、`tb_summaries[].main_sha`（非 `null` 时）与 `ArtifactRef.commit`（`storage="in_repo"` 时）均必须为顶层 `head` 在 `origin/main` 上的可达祖先提交（`git merge-base --is-ancestor` 为真），否则判 `"FAIL"`。`ArtifactRef.head`（`storage="external"` 时）取自上游仓外 delivery manifest 的 `head`（是否命中该 manifest 按 `ArtifactRef` 规则核验），预检要求该 `head` 等于交付工作区的 `HEAD`（`.sandcastle/delivery-bundle.ts:147`），即合入前的交付分支头；squash 交付可能无祖先关系；同树 merge 见 `.sandcastle/deepagents-pilot/pilot1742/review_sweep.py:276-279`。`ArtifactRef.head` 因此必须满足以下两项之一，否则判 `"FAIL"`：（a）它是顶层 `head` 的可达祖先提交；（b）GitHub 记录存在已合入 `main` 的 PR（`merged=true` 且 `base.ref="main"`），其 `head.sha` 等于 `ArtifactRef.head`，且其 `merge_commit_sha` 是顶层 `head` 的可达祖先提交。本项不用于 R09 的审查等价或 R06/R08 的 CI。该 PR 归属 `ArtifactRef.ticket` 的依据是对应 `ManifestRef` 已把同一 `ticket` 与 `head` 绑定，不从 PR 标题或正文推断；PR 按 `head.sha` 查得，报告不记录 PR 编号。（b）项只证明该 `head` 已合入 `main`，不证明 GitHub 把该 PR 记在 `ArtifactRef.ticket` 名下；票归属只取 `ManifestRef` 的绑定声明，由该票自身按第三节关票通用门完成的交付验收认可，#1391 与 #1403 均不得把（b）项成立当作票归属已核实。#1403 独立复核本规则，（b）项须自行向 GitHub 查询，不采信报告结论。

共用子记录封闭类型定义如下（`Sha256Hex` 为匹配 `^[0-9a-f]{64}$` 的字符串，`GitCommitSha` 为匹配 `^[0-9a-f]{40}$` 的字符串，`UtcTimestamp` 为 RFC 3339 UTC 时间字符串，`EvidenceClass` 为 `"simulation" | "experiment" | "production"`，`CiConclusion` 为 `"SUCCESS" | "FAILURE" | "CANCELLED" | "TIMED_OUT" | "ACTION_REQUIRED" | "NEUTRAL" | "SKIPPED" | "STALE"`）：

- `ManifestRef`（5 键）：`{ticket: integer, base: GitCommitSha, head: GitCommitSha, manifest_path: string, manifest_sha256: Sha256Hex}`。`ticket` 为正整数；`manifest_path` 为 checkout 外、无 `..` 的绝对路径。PASS 要求 `manifest_path` 无符号链接、文件可读且字节摘要等于 `manifest_sha256`，内容通过 `.sandcastle/delivery-bundle.ts` 的 `deliveryManifestSchema` 校验且内部 `ticket`、`base`、`head` 与本引用完全一致；任一不满足时，该 manifest 登记的引用不计为证据，在 `failed_checks[]` 写明并判 `"FAIL"`。
- `ArtifactRef`（8 键）：`{storage: "in_repo" | "external", path: string, sha256: Sha256Hex, commit: GitCommitSha | null, ticket: integer | null, base: GitCommitSha | null, head: GitCommitSha | null, bounded_scope: string}`。`storage="in_repo"` 用于仓内规范文件与 ADR 0058 既有仓内报告，`path` 为不含 `..` 的仓内相对路径，`commit` 必填 `GitCommitSha`，`ticket`、`base`、`head` 固定为 `null`；`storage="external"` 用于仓外持久证据（`.sandcastle/CODEX-CHILD.md:61`；`.sandcastle/delivery-bundle.ts:11-16`），`path` 为仓外持久证据目录下无 `..` 的绝对路径，`commit` 固定为 `null`，`ticket`（正整数）、`base`、`head` 均必填非 `null`。PASS 要求：`storage="in_repo"` 的 `commit` 在 `origin/main` 上且 Git blob 摘要等于 `sha256`；`storage="external"` 的 `path` 无符号链接，并在对应 `ManifestRef`（本轮运行封印原件对应已登记该文件的 #1391 自身 manifest；上游仓外证据对应 `at18-input-bundle.json` 的 `external_manifests[]`，#1391 自身产出的输入包与报告对应 `at18-verification.json` 的 `report_manifest`）中存在完全匹配的 `{storage: "external", path, sha256, ticket, base, head}` 条目，且落盘文件可读、字节摘要等于 `sha256`。任一缺失、不可读、未命中 manifest 或摘要不符时，该引用不计为证据，在 `failed_checks[]` 写明并判 `"FAIL"`，禁止跨存储方式回退。报告中缺失的必需证据按所在字段的规则填 `null` 或 `[]`，不写占位引用；`at18-verification/1` 的受验引用另按其定义处理。
- `EvidenceByClass`（3 键）：`{simulation: ArtifactRef[], experiment: ArtifactRef[], production: ArtifactRef[] | null}`。已启用证据类槽位必填 `ArtifactRef[]`（无条目填 `[]`，不得填 `null`）；未启用部署槽位（#1561 下的 `production`）必填 `null`（不得填 `[]` 或非空数组）；`production` 经独立授权启用后同样必填 `ArtifactRef[]`。
- `CapabilityTuple`（3 键）：`{capability_record_version: string, capability_record_sha256: Sha256Hex, venue_profile_sha256: Sha256Hex}`（ADR 0062:258）。
- `VenuePermissionFact`（3 键）：`{source_url: string, retrieved_at: string, sha256: Sha256Hex}`（ADR 0062:51-79）。
- `PermissionSlot`（4 键）：`{authorization_declaration: ArtifactRef | null, venue_permission_fact: VenuePermissionFact | null, runtime_verification: ArtifactRef | null, capability_hash: CapabilityTuple | null}`。已启用场所槽位的前三个字段依次记第二节第 2 条的（a）授权声明、（b）场所权限事实与（c）运行时核验，`capability_hash` 记能力 hash 三元组。某层证据缺失时该字段填 `null`；能力记录或场所 profile 缺失、三元组任一元素无可读来源时 `capability_hash` 填 `null`；不得以占位引用、不可读引用或他层证据代填。任一字段为 `null` 时 Destination ⑤ 的 `result` 必须为 `"FAIL"`，`failed_checks[]` 须为每个 `null` 字段写入一项（`scope` 写明 Destination ⑤ 与槽位），`overall_result` 随之为 `"FAIL"`。整个槽位填 `null` 只表示该场所槽位未启用。
- `ReviewRef`：`{pr: integer, reviewed_head: GitCommitSha, merge_commit: GitCommitSha, status_id: integer, creator: string, state: "success"|"failure"|"pending"|"error"}`；只从 R09 取事实，缺 PR 或状态不构造该项。
- `CiRunRef`：`{workflow: string, run_id: integer, run_attempt: integer, head_sha: GitCommitSha, conclusion: CiConclusion | null, url: string}`；只记 R08 选中的实际运行，未完成时结论填 null。
- `TicketScopeRef`（2 键）：`{ticket: integer, scope: string}`（`ticket` 为正整数，下同）。
- `SliceStatusRef`：`{ticket: integer, state: TicketState, state_reason: string | null}`；`TicketState = "OPEN" | "CLOSED" | null`（查不到填 null）。
- `DownstreamStatusRef`：`{ticket: integer, state: TicketState}`。
- `MigrationSlot`（5 键）：`{no_lost_rights: boolean, no_duplicated_capital: boolean, no_dual_write: boolean, no_resend: boolean, non_empty_evidence_refs: ArtifactRef[]}`（ADR 0063:120）。四项布尔值记对应不变量是否已由非空运行证据证实成立。已启用部署槽位缺非空运行证据时，未证实的布尔值填 `false`，`non_empty_evidence_refs` 填 `[]`（字段名表示通过条件，不是形状约束），并在 `failed_checks[]` 写明、使 `overall_result` 为 `"FAIL"`。
- `PostGateSlot`（8 键）：`{status: "UNKNOWN" | "NOT_TRIGGERED" | "TRIGGERED_AWAITING_POLICY" | "TRIGGERED_VERSION_AUTHORIZED" | "TRIGGERED_AND_ENABLED", gate_reached_event: ArtifactRef | null, parameter_version: ArtifactRef | null, first_activation: ArtifactRef | null, gate_reached_known_at: UtcTimestamp | null, version_authorized_at: UtcTimestamp | null, first_activation_known_at: UtcTimestamp | null, non_activation_evidence: ArtifactRef[]}`（ADR 0036:25-33）。`status="TRIGGERED_AND_ENABLED"` 时三条记录及三个时间戳均非 `null`、`non_activation_evidence` 为 `[]`，且满足 `gate_reached_known_at < version_authorized_at < first_activation_known_at` 与同 `profile_id` 互引；`status="TRIGGERED_VERSION_AUTHORIZED"` 时 `gate_reached_event`、`parameter_version`、`gate_reached_known_at` 与 `version_authorized_at` 非 `null`，满足 `gate_reached_known_at < version_authorized_at` 与同 `profile_id` 互引，`first_activation` 与 `first_activation_known_at` 为 `null`，且 `non_activation_evidence` 非空证 `growth_enabled=false`；`status="TRIGGERED_AWAITING_POLICY"` 时仅 `gate_reached_event` 与 `gate_reached_known_at` 非 `null`，其余两记录与两时间戳为 `null`，且 `non_activation_evidence` 非空证 `AwaitingPolicy{post_gate_params}` 与 `growth_enabled=false`；`status="NOT_TRIGGERED"` 时三条记录与三个时间戳全为 `null` 且 `non_activation_evidence` 非空证受测运行未触发 `GateReachedEvent` 且 `growth_enabled=false`。上述各状态对记录、时间戳与 `non_activation_evidence` 的非 `null`、非空要求是该槽位通过的条件，不是记录形状的前提。`status` 按受测运行的实际输出取值（`growth_enabled=true` 或声明闸门后参数生效时仍取 `"TRIGGERED_AND_ENABLED"`，运行证据不足以确定状态时取 `"UNKNOWN"`、相关引用及时间戳缺失填 null，未启用数组缺失填 []；UNKNOWN 不得算非激活证明且必须 FAIL），缺失的记录与时间戳填 `null`，缺失的未启用证据填 `[]`，不得以占位引用代填；任一要求不满足即在 `failed_checks[]` 写明并使 `overall_result` 为 `"FAIL"`。
- `StoryCoverageEntry`（6 键）：`{story_id: string, closure_slice_ids: string[], destination_ids: string[], evidence_refs: ArtifactRef[], deferred_gates: string[], status: "VERIFIED" | "BOUNDED_DEFERRED" | "FAIL"}`。
- `FamilyCoverageEntry`（6 键）：`{family: string, id: string, entry_mode: "REQUIRED" | "OUT_OF_SCOPE_PRESERVE", evidence_refs: ArtifactRef[], deferred_gates: string[], status: "VERIFIED" | "PRESERVED_BOUNDARY" | "BOUNDED_DEFERRED" | "FAIL"}`。
- `DetailCoverageEntry`（5 键）：`{id: string, family_entry_id: string, evidence_refs: ArtifactRef[], deferred_gates: string[], status: "VERIFIED" | "BOUNDED_DEFERRED" | "FAIL"}`。
- `SpecCoverageLedger`（4 键）：`{crosswalk_sha256: Sha256Hex | null, stories: StoryCoverageEntry[], families: FamilyCoverageEntry[], details: DetailCoverageEntry[]}`。成功须按 R02 原行顺序逐条对应 97/345/496；不可读时摘要为 null、数组为 [] 并 FAIL。family 的 `entry_mode` 只由对应 crosswalk 的 `exclusion_boundary=true` 判定：真为 `OUT_OF_SCOPE_PRESERVE`，否则 `REQUIRED`；当前仅 OE41/OE45 是边界。OE42 仍核 coverage input 的 `source_json_pointer` 指向的 `effective_disposition.kind="OUT_OF_SCOPE_PRESERVE"`（`.chanlun/review-results/issue1340-publication-20260909/view/inputs/TB07-11-EXECUTION-SLICES.md:278`），不得改为边界项。条目状态按 R12；通过的非 TB-11 键至少引用与输入包 `registry_ref` 完全相等的引用；TB-11 键至少引用与该 TB `input_bundle` 完全相等的引用；混合条目两者都含。所有已通过的具名延期以唯一字符串连接 `unexecuted[]`。
- `FailedCheck`（4 键）：`{scope: string, check_id: string, detail: string, evidence_ref: ArtifactRef | null}`。

`at18-input-bundle/1` 顶层 13 键：`{schema_version: "at18-input-bundle/1", content_hash: Sha256Hex, ticket: integer, base: GitCommitSha, head: GitCommitSha, generated_at: UtcTimestamp, spec_ref: ArtifactRef, crosswalk_ref: ArtifactRef, coverage_input_ref: ArtifactRef, registry_ref: ArtifactRef, pregate_review_ref: ArtifactRef, slice_ledger_refs: ArtifactRef[], external_manifests: ManifestRef[]}`。身份取本票 manifest；#1391 票号固定为 1391。规范三件分别为 `.chanlun/review-results/issue1339-r2-spec-20260909/payload/spec/` 下 `SPEC.json`、`IMPLEMENTATION-CROSSWALK.json`、`inputs/SPEC-COVERAGE-INPUT.json`；登记册和 PRE 路径见 R03。切片账按 `TB01-EXECUTION-SLICES.json`、`TB02-06-EXECUTION-SLICES.json`、`TB07-11-EXECUTION-SLICES.json`、`TB01-PARENT-CONTRIBUTION.json` 顺序，均在 `.chanlun/review-results/issue1340-publication-20260909/payload/inputs/`。以上全部以 `in_repo`、`commit=head` 读取。缺任一所需文件、非法引用或无合法摘要则没有有效输入包；`external_manifests` 仅列报告引用的上游仓外清单，无重复，按票号与路径排序。

F 上两份登记原件的封闭合同（签名不新增）：

- `at18-registry/1 = {schema_version, crosswalk_sha256: Sha256Hex, experiment_profile_id: string|null, checks: Check[], bindings: Binding[], pregate: {census_sha256: Sha256Hex, landings: Landing[]}}`；`schema_version` 固定为 `"at18-registry/1"`，骨架的 profile 可 null，正式通过须有有效 P1 profile。R10 清册由 #2132 在 .chanlun/ 下的 `at18` 目录交付，清册入口文件名为 `landing-census.json`；`census_sha256` 须等于 F 上该入口文件字节摘要，入口只含 `schema_version="at18-landing-census/1"`、`p0` 及 `sources:{role,path,sha256}[]` 三键，`p0` 固定为 R09 的 P0。`role` 按 `history,relations,signals,adjudication` 各恰一份；路径均指向 F 的获审原件、逐份核其字节摘要，未知或重复角色失败。实际落地与留存结果从这些原件及 Git 重算，而非以清册自报结果替代。
- `Check = {check_id:string, group:string, evidence_class:EvidenceClass, profile_id:string|null, runner:"cargo-test"|"node-test"|"pytest"|"command", selector:string, expected_count:integer, key_aware:boolean, source:{path:string,sha256:Sha256Hex}, record:string|null}`。`check_id` 唯一，组、profile 和 ID 使用 ASCII 字母/数字/点/下划线/连字符的非空单词；`none` 只用于封印的空 profile 标记。record 只接受 R07 具名槽；`selector` 是 runner 的受审选择器，不拼成 shell 或从 dispatch 传入。
- `Binding = {binding_id:string, slice_id:string, basis:{path:string,sha256:Sha256Hex,pointer:string}, keys:{kind:"story"|"family"|"detail",id:string}[], domains:Domain[]}`；`binding_id` 唯一，keys 非空无重复。`Domain = {evidence_class:EvidenceClass,profile_id:string|null,result:"VERIFIED"|"PRESERVED_BOUNDARY"|"BOUNDED_DEFERRED",deferred_gate:string|null,checks:string[]}`；checks 无重复，检查和域必须有实际引用关系；专用或历史 cure 检查可由 R07/R11 引用。
- `Landing = {ticket:integer,commits:GitCommitSha[],cure_checks:{commit:GitCommitSha,run_id:integer|null,kind:"test"|"step",target:string,check_id:string}[]}`。测试类型 cure 锁须用 selector 唯一命中所指具名测试（允许引擎完整路径，末段同名且唯一），实跑 1 次；步骤类型 cure 按 R11 定位失败步骤并复跑同一步骤、同一失败条件；警告或拒绝不算。R11 中同票同提交的具名锁不可删。
- `at18-pregate-review/1 = {schema_version:"at18-pregate-review/1",owner_ticket:integer,rows:{path:string,blob:GitCommitSha,mode:"100644"|"100755"|"120000",verdict:"PASS"|"BLOCK"}[]}`。path 是 Git 仓内相对路径；blob 字段用 Git SHA-1 的格式，语义为 blob 对象，不是提交。

工作流与历史观测类型：`WorkflowRun = {workflow:string,run_id:integer|null,run_attempt:integer|null}`；`AcceptanceJob = {workflow:string,run_id:integer,run_attempt:integer,head_sha:GitCommitSha,job:string,conclusion:CiConclusion|null}`；`HistoricalDeviation = {ticket:integer,commit:GitCommitSha,workflow:string,run_id:integer|null,observed:CiConclusion|"NO_RUN"|"INCOMPLETE"|"UNKNOWN"}`。工作流用仓内路径；服务端结论转大写，已识别为尚未完成的历史运行记 INCOMPLETE，未知结论记 UNKNOWN（同时报来源失败），不得翻成 PASS。当前轮未知结论在对应作业记录填 null 并失败。正整数用于所有票、run、attempt、测试数与 PR/status id。

`at18-report/1` 顶层封闭字段集合固定为以下 21 键：

- `schema_version`（固定 `"at18-report/1"`）、`content_hash`（`Sha256Hex`）、`ticket`（正整数，正式整图报告固定为 `1391`，须与绑定本报告的 #1391 仓外 delivery manifest 的 `ticket` 完全一致）、`base`（`GitCommitSha`，须与该 manifest 的 `base` 完全一致）、`head`（`GitCommitSha`，须与该 manifest 的 `head` 完全一致；PASS 要求它等于 `at18-input-bundle/1.head` 与对账时的实际 `origin/main` SHA，候选分支不得冒充 `origin/main`；输入包缺失或其 `head` 与本报告 `head` 不等时，本报告 `head` 仍取自该 manifest，在 `failed_checks[]` 写明并判 `"FAIL"`）、`generated_at`（`UtcTimestamp`）；
- `capability_hash`：`{experiment: CapabilityTuple | null, production: CapabilityTuple | null}`；已启用场所槽位填 `CapabilityTuple`（该槽位 Destination ⑤ 的 `capability_hash` 因能力记录缺失填 `null` 时同填 `null`，按 `PermissionSlot` 规则判 `"FAIL"`），未启用槽位填 `null`，且须与 `destinations[]` 第 5 项（`id=5`）`permission_evidence` 对应槽位的 `capability_hash` 逐槽完全相等，不等即判 `"FAIL"`；
- 恰好 6 项、按 `id` `1..6` 升序排列的 `destinations[]`：每项固定 12 键 `{id: integer, obligation: string, tickets: TicketScopeRef[], commits: GitCommitSha[], independent_reviews: ReviewRef[], main_sha: GitCommitSha | null, ci_runs: CiRunRef[], evidence_by_class: EvidenceByClass, permission_evidence: {experiment: PermissionSlot | null, production: PermissionSlot | null} | null, downstream_status: DownstreamStatusRef[], remaining_obligations: string[], result: "PASS" | "FAIL"}`；仅 `id=5` 的 `permission_evidence` 为非 `null` 分槽对象（已启用场所槽位填 `PermissionSlot`，缺失的证据层与能力 hash 按 `PermissionSlot` 规则在槽内填 `null`；未启用槽位填 `null`），其余 5 项固定填 `null`；可确认的报告主线填 F，否则填 null 并 FAIL。commits 只列 F 与第八节由 R10 得到的适用历史出处（去重），不把出处当行为证明；independent_reviews 由 R09 复算；ci_runs 仅取 R08。
- 恰好 11 项、按 `"TB-01".."TB-11"` 排列的 `tb_summaries[]`：每项固定 12 键 `{tb_id: string, ticket: integer, slices: SliceStatusRef[], input_bundle: ArtifactRef | null, evidence_by_class: EvidenceByClass, final_reviews: ReviewRef[], main_sha: GitCommitSha | null, ci_runs: CiRunRef[], entity_reports: ArtifactRef[], remaining_obligations: string[], ticket_state: TicketState, gate_satisfied: boolean}`；`TB-01..TB-10` 的 `input_bundle` 固定填 `null`，`entity_reports` 列出R07 封印的本轮实体报告（无则填 `[]` 并记 `gate_satisfied=false`），`TB-11` 的 `entity_reports` 固定填 `[]`，`input_bundle` 按第三节及 R12 绑定 `at18-input-bundle.json`；PASS 要求 `TB-11` 的 `input_bundle` 是非 `null` 的 `ArtifactRef`，输入包缺失或不可读时填 `null`、记 `gate_satisfied=false`，在 `failed_checks[]` 写明并判 `"FAIL"`； TB 的 main_sha、适用 CI 与审查取 R08–R10（闸前复审以 PRE 在第一父链的登记合入指向 R09 记录）；不编造切片主线 SHA。
- `spec_coverage`：`SpecCoverageLedger`（覆盖全部 97 故事、345 family 条目与 496 细项对账）；
- `migration_invariants`：`{experiment: MigrationSlot | null, production: MigrationSlot | null}`，已启用部署槽位填 `MigrationSlot`，未启用槽位填 `null`；
- `post_gate_records`：`{experiment: PostGateSlot | null, production: PostGateSlot | null}`，已启用部署槽位填 `PostGateSlot`，未启用槽位填 `null`；
- 恰好 7 项、按 `[942, 1096, 1282, 1304, 1319, 1320, 1279]` 顺序排列的 `legacy_dispositions[]`：每项固定 6 键 `{ticket: integer, disposition: string, evidence_refs: ArtifactRef[], ticket_state: TicketState, remaining_obligations: string[], disposition_valid: boolean}`；
- `unexecuted[]`：元素类型为 5 键 `{obligation: string, reason: string, blocker_or_gap: string, evidence_class: EvidenceClass, required: boolean}`；`obligation` 在 `unexecuted[]` 内不得重复，`deferred_gates` 按 `obligation` 逐字节相等连接到条目。本 ADR 要求的具名条目固定使用以下四个 `obligation` 常量，且 `required=false`：`ISSUE_1561_P2_FIRST_SEND`（#1561 下「生产首次新发送前」具名门，`evidence_class="production"`，`production` 部署槽位未启用时必列）、`ADR_0036_POST_GATE_PRODUCTION` 与 `ADR_0036_POST_GATE_EXPERIMENT`（ADR 0036 闸门后三记录门，`evidence_class` 分别为 `"production"` 与 `"experiment"`，`post_gate_records` 的对应槽位为 `null` 或其 `status` 不是 `"TRIGGERED_AND_ENABLED"` 时必列）、`ISSUE_1320_HEAVY_MEASUREMENT`（第四节 #1320 单列重型测量，`evidence_class="simulation"`，即 CONTEXT.md:374 的确定性回放，该测量未实际完成且无合法废弃裁定时必列）；
- `failed_checks[]`（元素类型为 `FailedCheck`）、`permission_blocked[]`（记录受权限阻塞的本图必需成功项，元素类型为 4 键 `{obligation: string, missing_authorization: string, blocker_ticket: integer, evidence_class: EvidenceClass}`）、`bounded_domain_statement`（非空字符串）；
- `workflow_runs[]`：四项按 ci.yml、devskim.yml、at18-acceptance.yml、at18-experiment.yml 固定顺序；缺 run 时两个 id 均为 null。`acceptance_jobs[]`：R06–R08 取证所用实例与封印作业（含已看到的失败行）。`historical_deviations[]`：R11 的全部偏差。可变数组按工作流路径、run/attempt、作业名或票号、提交、工作流路径、run id 排序（null 在先），不得用摘要替代明细。
- `bounded_domain_statement` 除第二、四节要求外，固定逐行包含 `AT18_LANDING_CI_NOT_CERTIFIED n=<historical_deviations 项数>`、`AT18_PREGATE_REVIEWER_VOUCHED_BY_TICKET 2132`、`AT18_CHECK_SUFFICIENCY_BY_FORMAL_GATE`。第二行说明身份担保方法，不表示 #2132 已关；完整文本按第八节唯一投影。
- `overall_result`：`"PASS" | "FAIL"`。

`overall_result="PASS"` 只在 R01–R13 均满足、各引用按本节可复核、六项 Destination 全 PASS、十一项 TB 门全 true、覆盖条目无 FAIL、七张旧票 `disposition_valid=true`，且 `failed_checks=[]`、`permission_blocked=[]`、`unexecuted` 无重复且无 `required=true` 时成立。历史偏差非空本身不阻断，也不掩盖 `DEVIATION_NOT_CURED`。R14 定义所有判定失败的合法写法。

`at18-verification/1` 顶层 12 键：`{schema_version:"at18-verification/1",content_hash:Sha256Hex,ticket:integer,base:GitCommitSha,head:GitCommitSha,verified_at:UtcTimestamp,report_manifest:ManifestRef|null,report_ref:ArtifactRef|null,report_content_hash:Sha256Hex|null,input_bundle_ref:ArtifactRef|null,failed_checks:FailedCheck[],verdict:"PASS"|"FAIL"}`。ticket 固定为 1403；身份从自身 manifest 取，受验对象和缺失值按引导条文处理。#1403 从同一 F、GitHub 与仓外原件独立重算 R01–R14、摘要、引用、祖先及作用域；按第八节重算报告的全部字段（生成时刻独立验时，再用于重算摘要），时间须合法 UTC、落在本轮并晚于所引用运行。资源在 #1391 封包后会多出输入包、报告登记和两票状态变化，仅按第三节已声明的阶段快照解释，不用新票态改写原报告。只有两个 manifest 与实体校验通过、比较无差异、受验报告 `overall_result="PASS"` 且本回执 `failed_checks=[]` 才记 PASS。受验物摘要不符仍输出 FAIL 回执。

TB-11（#1369）、SPEC #1340 与 #1323 的关票须在 #1391 已生成 `overall_result` 为 `"PASS"` 的 `at18-report/1` 并完成 #1391 封包关票、#1403 已对该报告与 `at18-input-bundle/1` 实际运行产出 `verdict` 为 `"PASS"` 的 `at18-verification/1` 并完成 #1403 封包关票、两份仓外 delivery manifest 校验均通过（退出码 `0`）且两票最终非作者独评均为 `PASS` 后执行。关票评论须同时写明 `at18-input-bundle.json`、`at18-report.json`（路径、文件 `sha256`、`content_hash`）与 `at18-verification.json`（路径、文件 `sha256`、`content_hash`、`verdict`）、双方 delivery manifest 路径与 `sha256`、实际 `origin/main` SHA、适用 CI run、最终非作者独评、六项 Destination 证据摘要、ADR 0036 各槽位的 `PostGateSlot.status` 与对应记录、`unexecuted[]` 明细及七张旧票去向；缺任一实体报告或独立总验未通过时写「无有效总验报告」，不得声明整图通过或关闭 #1369、#1340、#1323。

## 六、从原件计算验收结论

### R01　冻结 F 和原件

生成器 #1391 与总验器 #1403 只消费本仓 Git 对象、GitHub 服务端 API、本票仓外 manifest 及其登记实体。删去调用方传入的 observations、判定布尔值、状态表与作业结论。两端各自取 GitHub `refs/heads/main` 完整 SHA；在取证开始、输出前及关票前均须等于本轮 `head=F`。#1403 另与 #1391 报告记录的四个工作流选择结果（run id 与 attempt，含无运行）逐项核对；同一个 F 上选择变了也重产报告，不拼接窗口。失败记 `HEAD_CHANGED` 或 `WINDOW_DRIFT`；API 分页不全、鉴权失败、限流或网络错误记 `SOURCE_UNAVAILABLE`，与成功读得空列表区分。

#1391 的验收操作：主控先关闭执行器既有的 `--review-sweep-auto-merge`，确认无在途合入、通知其他合入方暂停，记录 F，从 `main` 手动触发；不得改保护、取消 strict 或停掉正式独审。#1403 同窗口出回执；到关票前若主线前移，废弃本轮验收（保留旧报告作为过期证据），取新 F、重 dispatch、重生成及重验。若 #1391 或 #1403 已封包关闭，只重开受影响的这两张验收票以接回新证据，不重开历史切片。窗口结束或终止后恢复原合入安排。入口见 `.sandcastle/deepagents-pilot/pilot1742/executor.py:889-892, :961-967`；操作单由主控在本 ADR 落地时写进 #1391。

### R02　计算分母

在 F 读输入包固定的 crosswalk。分别按 `rows[*].story_id`、`family_entry_links[*].id`、`detailed_acceptance_links[*].id`，和同一行每个 `success_closure_slice_ids` 展开 `Key=(kind,id,slice_id)`（kind 依次为 `story|family|detail`）。拒绝重复行身份、重复切片、空切片集、未知 ID/切片、无效引用（`COVERAGE_SOURCE`）。当前规范 97/345/496 行，展开 4,071 键：TB-11 113 个，其余 3,958 个。不得读 `slice_success_obligations` 代替展开，也不得产生 Destination 键。六个 `destination_success_obligations` 另须一一对应 DST-01..06；链接 ID 和归属必须有效。编号为 `DST-*` 的 **family** 条目仍按 family 展开。

### R03　绑定必须覆盖出处

承接 #2131 的登记册与 #2132 的闸前复审均读 F：以仓根 .chanlun/ 下的 `at18` 子目录为父目录，文件名分别为 `registry.json` 和 `pregate-review.json`；四份切片账路径见第五节。登记册 `crosswalk_sha256` 与 F 的实际字节相等。按键求必需 basis 集：

1. 三份切片账的 `/units/<i>`，若 `parent_tb=Key.slice_id` 且按 kind 在 `story_ids|family_entry_ids|detailed_acceptance_ids` 命中，**所有**命中各需一个绑定。
2. 无命中时，TB-01 family/detail 若在贡献档 `/rows/<i>` 中按 `family_entry_id|parent_detailed_acceptance_ids` 命中，取所有匹配行；否则取 crosswalk 中该键的唯一展开原节点。贡献档仅是分工出处。coverage input 用于规范语义的指针解读（含 OE42），不能替代上述 basis。

一个 binding 只取一个 basis，声明的每个键必须属于同一 slice 并且该 basis 在该键的必需集中。读取 F 上该路径的 Git blob 校字节摘要和 RFC 6901 指针；不得另挑下钻节点缩验收面。对每个非 TB-11 键，核其实际 `(Key,basis)` 与必需集相等且无重复。超集键 `KEY_NOT_EXPECTED`；无绑定 `KEY_UNBOUND`；错指针、摘要、超出或重复 basis `BASIS_MISMATCH`；缺必需 basis `BASIS_INCOMPLETE`；登记册读不到或形状不合法 `REGISTRY_INVALID`。TB-11 键不得出现在 bindings。

### R04　保持证据域，不做跨类替代

`Domain.result` 是为该域声明的义务类型，不是实测结论。以 `(evidence_class,profile_id)` 区分域；simulation 的 profile 可为 null，experiment/production 必须取受测版本化场所 profile ID。每条 binding 至少一个非延期域。每个运行域的 checks 非空，所指检查的类及 profile 与域完全相等；运行域的 `deferred_gate=null`。仅且所有 `exclusion_boundary=true` 的 family 键使用 `PRESERVED_BOUNDARY`，无延期；OE42 执行其 `OUT_OF_SCOPE_PRESERVE` 处分的检查，但仍为必需 `VERIFIED` 键。

`BOUNDED_DEFERRED` 域不运行检查，`checks=[]`；`deferred_gate` 限 `ISSUE_1561_P2_FIRST_SEND`（production）、`ADR_0036_POST_GATE_EXPERIMENT`（experiment）、`ADR_0036_POST_GATE_PRODUCTION`（production），并须与本轮**独立求得**的具名门状态、槽位及 `unexecuted[]` 同名可延期项相符。#1561 的生产首发送未启用期间不得登记 production 检查；本版 AT-18 只证明本图的 simulation 与 P1，生产槽一律 null；若生产授权已生效，另走相应具名门并修订本验收合同，不让 /1 偷换射程（`PRODUCTION_SCOPE_CHANGED`）。缺 #2133 或受测动作别项硬门时，相关 experiment 仍是必需，记 `AUTH_REQUIRED`，不得延期。域不合（含空域、重复域、跨类、未声明 profile、无法证明延期）记 `DOMAIN_INVALID`。

首次及新增绑定由登记册作者按规范声明域，正式 PR 独审逐键核首定射程、真正需要的 experiment、断言与执行选择器；crosswalk 无这类机读下限，机器不从散文猜测。#2131 的 `at18-registry-lint` 进 `ci-ok.needs`，在每个登记册变更 PR 核 R02–R05 的静态部分（开工骨架可缺覆盖，正式报告不得缺）。以 PR merge base 上的登记册比较：已有 `(Key,basis.path,basis.pointer)` 及域的类/profile 不得删除或移成别键；运行域不得降为延期，已有非延期义务不得以替换基准文件或改指针消失。每次修改须重 pin；规范确有重编或收缩，先修订本合同和覆盖正本再迁移，不设 lint 豁免（`DOMAIN_SHRINK`）。

### R05　检查契约

在 F 读取每条检查的 `source.path`，实际字节摘要须等于登记值（`CHECK_SOURCE_DRIFT`）。固定 `selector` 在该源上执行；运行器按框架读取实际执行名及数，确保命中所登记用例且执行数等于正整数 `expected_count`、跳过和忽略均为 0；选错、未执行或见证缺失时检查进程与作业失败。非键感知测试的 `source` 必须是所执行测试定义所在文件，每个绑定键有独立行 `@at18 <slice_id> <kind> <id>`（允许行首缩进与该语言注释标记，不以子串命中，错标记 `CHECK_NOT_ANNOTATED`）；同源多测试须把标注挂在选中用例下。键感知检查接收按字节序排列的条目 `{kind,id,slice_id,basis_path,basis_pointer}`，运行器核结构化见证的身份集合与输入完全相等、无重复、每项断言成功；`command` 必为键感知，禁止直接信退出 0。R05 的成功仍须有 R06 成功作业。TB-01 的本机耐久、重启与真实浏览器合同改用同射程的 runner 内实际进程重启和 headless 浏览器；无法在 F 上证成即留红，由当前 TB owner（TB-01 为 #2132）登记阻塞缺陷并修复，不把探针报告抄成绿。

### R06　选一次真实执行

按工作流路径在本仓查询并核服务端 workflow id，列表以 `head_sha=F`、`head_branch=main`、`event=workflow_dispatch` 过滤；#2131 在 .github/workflows/ 交付两份合同文件，simulation 取 `at18-acceptance.yml`、experiment 取 `at18-experiment.yml`，均无自报 dispatch inputs。各工作流独立选数值最大的 run id，取该 run 的**最新** attempt（含未完成、失败和取消），只读该 attempt 的分页 Jobs API；不借前一次 attempt、其他 run 或祖先 SHA。部分重跑若本 attempt 没有全部必需作业，用全量重跑。检查组的每个检查按登记执行且全部成功，组作业才成功。每个类的必需组恰有一个名为 `at18 <group> <S>` 的完成成功作业，S 是 F 的登记册文件字节 sha256；组不得跨类/profile。缺失、重名或无法作为唯一作业定位记 `CHECK_JOB_MISSING`，存在但未完成或非 success 记 `CHECK_JOB_FAILED`。run 必须完成且结论 success；不得看日志猜通过。只有成功查询确实无 run 才可记不存在，F 的缺失/过期都留红并重跑。TB 由自己的组结果归并；若其所用 run 仍失败，有局部成功事实而没有可用的整轮验收。

experiment 工作流只可在 #2133 指定的 self-hosted runner 授权范围内启动接触凭据的作业。在任何接触前按 ADR 0041 和签署票验有效域、期限及动作，未签、越域、撤回或无法核实时不启动；#2133 状态、缺/失效授权原因照录，检查不通过。只读签署不授权发送；受控发送另守 #1412。机器仅按 #2133 实际签署原件和已批准 profile/runner 范围核对，不把 shared GitHub 账号的作者显示名当作可区分人机的签名；项目保证签署只由用户发出（`.sandcastle/docs/graph-engineering.md:50`）。不搬运或记录凭据。simulation 不得运行凭据接触动作。

### R07　封印运行记录

必需运行记录按 `(record,profile_id)` 唯一归属一个组：`permission.experiment`、`migration.experiment`、`post_gate.experiment`，以及 TB 实体报告 `tb.simulation.TB-xx|tb.experiment.TB-xx`。每个允许记录的检查声明一项 `record`，同一记录/profile 不得有两个生产者。权限、迁移、后闸三种记录各须至少一个实际启用的 P1 槽位，报告使用的 profile 由获审登记册明确选定，三个槽位一致；不得从绿色作业反选。为各 TB 登记该 TB 实际需要的类，至少一份本轮实体报告；TB-08..10 必有 P1 实体与相应必需检查。第二区的三专用门所需检查为该记录/profile 的记录生产者与其组，不能用不存在的键推迟。

记录生产者按门或 TB 的固定业务合同，把**运行原件**（数据及必要索引，不收 `passed`/`verdict` 代替事实）写成严格 JSON；共同封闭外层为 `{schema_version:"at18-run-record/1",record:string,head:GitCommitSha,run_id:integer,run_attempt:integer,check_id:string,profile_id:string|null,payload:object}`，各身份字段须与服务端作业及登记检查完全匹配；payload 用对应门的版本化原件格式，不同身份不可互用同一文件。每个运行证据文件字节摘要由同组输出传给同 run 的独立封印作业，作业名 `at18-seal <record> <profile-token> <S> <sha256>`（profile-token 为版本化 ID，simulation 的 null 写 `none`）。一个 kind/profile 可封印多份不同记录文件；每份都恰有一个对应成功封印作业；封印须依赖对应组成功，不得接受来自其他组的输出。只信 R06 所选 run/attempt 含服务端成功封印的字节。检查运行使用受审的 F、无不可信输入；登记名语法与固定前缀分离，运行原件不控作业名除输出摘要外任何字段。

#1391 把文件作为本票 manifest 中的 external reports 登记（先取得已封印原件，再引导；自身报告/输入包可尚未登记），引用全部同 run、F、类及 profile。专用槽运行引用、任何用作运行证据的 `evidence_by_class` 条目、TB 实体均按本条复算；缺登记、字节错、两次运行拼接或无唯一成功封印记 `RECORD_UNSEALED`。仅规范文书、用户签署/场所依据、ADR 0058 的专用仓内载体可按第五节照录；旧报告本身不能绕过 F 运行，有关 AT-14 的现场结论也必须由 F 上的绑定检查执行。仓外清单及 ArtifactRef 的摘要不是业务通过证明。

规范适配器由 #2131 固定在验收入口且经正式门审查；#1391 与 #1403 按同一合同各自从原件读取并计算，禁止接收字段同名的结果布尔值：

- 权限记录读实际 X 启动第 4–7 步及 profile/版本的互引；比对签署的授权声明、#1770 文档来源元数据和实际能力记录、profile 字节，以第二节三层及三元组条件重算。授权文书与场所文档属依据，不从运行记录的自报字段补写。
- 迁移记录读同一 profile 的非空前态、未结单及费用尾，回放迁移、中断及回退前后归属、资金账、writer/发送的原始记录，按 ADR 0063 的身份映射、责任与四不变量重算；要求存在实际非空见证，不能把空集合上的全称当成功。
- 后闸记录读该次受测运行的阶段状态、事件流、参数版本和首次启用记录，按第二节第 4 条及第五节状态联合计算互引、时间序和未启用事实；缺原件记未知，不把未知写成未触发。获得本规则的非激活事实后才产生相应可延期条目，避免 R04 用其自身输出证明延期。
- TB 实体读本 TB 的原件中测试身份、键/域集合、实际运行条件和输出，与 R02–R06 计算的集合逐项比对。缺实体或不匹配、专用判据不成立记 `TB_REPORT` 或 `SPECIAL_GATE`；诊断按字段逐项列出。运行记录适配器由生产者写并在 Actions 作业实际运行；#1403 消费固定合同与原件，不能调用 #1391 生成器代验。

### R08　在 F 核通用 CI

用 R06 的同一选择规则取 `.github/workflows/ci.yml` 的 dispatch；取 F 版 YAML 的 `jobs.ci-ok.needs`（字符串或列表，均须归一化为非空 ID 集且含 `at18-registry-lint`）；`ci-ok` 与每个 needs 对应的全部实例须成功，跳过不算。逐作业将默认名或 F 版 `name` 的矩阵展开匹配服务端作业列表。动态矩阵用 F 的声明、所选 attempt 的服务端 runner labels 和同一 runner 方案展开（本版分别为标准 runner、Boat 两种；不能从已成功作业的子集反推分母）；无法唯一映射或实例不齐记 `HEAD_CI`。不属 `ci-ok.needs` 的额外作业不作验收证据。#2131 对 CI 声明变更保持该全量展开能力，不能识别的表达式不默认为空。DevSkim 也只认 F 在 `main` 的 dispatch、所选 attempt 中唯一 `DevSkim` 完成且成功；#2131 增加该触发。原工作流的 push 去重与 PR Rust 指纹不进 AT-18 的 CI 证明。取证依据：`.github/workflows/ci.yml:4, :41-46, :458-469, :541-560, :875-891, :1457-1518`；`.github/workflows/devskim.yml:12-27`。

### R09　闸后：逐个核主线集成

G0 = PR #1915 的落地提交 `bd54d4b28ec4f83d596837f84f1f861dd085124c`（含 G0），P0 = G0 第一父 `b5cd3fee352e5f7199233de628da05ff06c5798f`。F 的第一父链必须经过 G0。沿 G0..F 的全部第一父提交 M（包括与图无关的提交），每一项均须满足：

1. M 恰有两父，H 为第二父；查 GitHub 与 M 关联的 PR 后唯一命中本仓已合入记录：`merged=true`、`base.ref=main`、`merge_commit_sha=M`、`head.sha=H`；以 Git 比较 `tree(M)=tree(H)`。
2. 查询 H 的 GitHub commit statuses，取精确 context `deepagents/review` 最新一条（服务端逆序首条；先取最新，再验作者），该条 `state=success`，`creator.login=newchanlun-review-gate[bot]`。不以其他 context、其他作者、更早的成功或到 M 后补审代替。报告记实际 PR、H、M、status id/作者/状态，不认自填回执。

任一不成立记 `REVIEW_FINAL_PRODUCT`，不改走 R10。日常合入仍受流程原门；G0 后如选 squash、直接推送或形成异树合入，可能符合某个日常流程读法但不能满足本图的最终独评证明，故本图存续期间 main 应循同树 merge 入口，发现不符合须由后续裁决修订证据合同，不在本规则中补路。实际自动入口见 `.sandcastle/deepagents-pilot/pilot1742/review_sweep.py:276-279`。

### R10　闸前：按主线落地和留存路径补审

#2132 交付闸前来源清册及可重放的枚举程序。先从完整 Git 历史枚举 P0 的全部第一父提交；从 GitHub 分页取 #1359–#1368、图 #1323 与其 SPEC #1340 的原生实施子树（含各 TB 汇总、带 `wayfinder:impl` 的原生实施子票及图直属实施产品与其实施子树）、#1493 在 #1360 下的改挂，以及对这些产品有正式承接/归属的补修、恢复、测试和报告尾件。原生关系只定义考察范围；引用、依赖或触及相同目录本身不是产品归属证据。逐场景从实际 Git 第一父差异、匹配其 merge SHA 的本仓 main PR、票面交付／承接原件核实 `(ticket, M)`；一提交可有多票归属。不能因票仍开、已关、重开、改挂、无 PR 或仅为文档而排除实际落地；PR 未合或 merge SHA 不在 P0 第一父链不计。不能用关票时间或提交作者时间取代第一父归属。

清册须归档（1）遍历的完整 P0 第一父链；（2）原生范围、源码与 GitHub 关联出处；（3）逐一处置命中的候选或交付声明，及对范围内没有归属标记的新增/替换路径与未分配用途的交付扫尾结果；（4）全量 `(ticket,M)` 与每个 M 的原始第一父差异。结构化关联优先采用 GitHub 实际合并记录与明确指向交付物的 Git/票面原件；非结构化命中由 #2132 在获审清册逐条给出处及纳入/排除裁决。#2132 的正式独审须逐 TB 对已落主线的成果对账，交叉检查 PR 与票面原件，并核无归属标记的历史改动；名字、目录、搜索结果或旧表都不能证明完备。图外票的正式承接用对应 TB／图的实际义务归并，独立列来源票；不把图外整票改成阻塞边。发现新出处或歧义先记 `PREGATE_LANDINGS`；由 #2132 在正式合入门补齐清册及复审，不得由调用方覆盖。每端自行从固定来源原件、P0 与 F 核销清册覆盖及重算差异；只给一列 SHA 或 PRE 打满 PASS 不够。#1493 缺已裁的改挂也记 `PREGATE_LANDINGS`。

对每一唯一 M 取 `git diff --no-renames --name-only -z` 的第一父差异并取并集；以 Git 路径字节作键，不按目录或后缀排除。与 P0 和 F 的叶路径集相交得到 PRE；P0 的 `(path,mode,blob)` 逐项核对，F 的对象与 G0..F 对该路径的第一父变更只作来源分类：未改仍验 P0，改过也验 P0 且所有相关闸后集成另过 R09，已删除则不进入 PRE（仍保留历史差异）。非 blob 留红；符号链接验链接自身的 blob。注册的 `pregate.landings` 对齐重算的票／提交全集；PRE 的路径集必须与重算结果全等、无重复、逐条 PASS。清册、登记、PRE 在 F 第一父链最近新增或修改的提交均须通过 R09；`owner_ticket=2132` 且 #2132 为 `CLOSED/COMPLETED`。缺项或不合记 `PREGATE_REVIEW`；#2132 的关票验收与登记 PR 的正式合入门担保非作者复审身份。F 删除或新增需要核对的路径时先正式更正登记再取验收 F。

边界反例：PR #1553、#1571 均归 #1405，不被其关票尾件 #1574 吞掉；#1394 的 #1583 是正式尾件；#1359 与 #1372 可共指同一主线提交。#1406 的 PR #1616 在 P0 第一父链上，即使 #1406 尚 OPEN 也必须纳入；后续恢复、校验或补修产品按同一规则重算。任何示例和作者快照的计数都不是分母上限。#2132 的清册及 PRE 是整图共用门；未分到单一 TB 的图直属/联合产品同样阻断整图，不借未映射到某一项 Destination 脱落。

**#799 / #804 举证。** `postLanding(M)` 是 G0 起的集成事件，证明送入 main 的完整树经过正式应用门；`preResidue(path,mode,blob@P0)` 是仍在 F 留存路径上的历史基准字节，证明经承接非作者复审。两份输入由 Git 与来源清册先算、分别验、最后取合取。即使某一闸后 M 触及同一路径或同 blob，缺其 App 状态依然失败；同样，闸后全绿也不补 PRE。相同 AT-18 行为义务在 F 上统一执行 R02–R08，不按历史或 TB 级别切换判据（`docs/agents/doctrine-rules.md:43-55, :61-79`）。

### R11　把历史留在历史

按 R10 的每个唯一 M、两个工作流分别分页枚举本仓 push runs；按 `(ticket,M)` 原样分发偏差，不把共享归属当成额外运行。逐个非 success 照录 run id 与实际状态；查询成功但无运行（含过期查不到）按工作流各记 `NO_RUN`。历史结果与 F 的 `ci_runs` 隔离，旧批准例外不作为授权或 SUCCESS。历史 CI failure 须由归属票登记的具名失败测试在 F 成功复跑；逐运行以 `run_id` 关联其应复跑的锁（下表固定锁用 `null`，不因运行是否可查改变）；缺测试定位、原件或获审复跑检查记 `DEVIATION_NOT_CURED`，由 #2132 补办；不从失败类别泛配一个绿灯。若原失败只在编译、配置或基础设施环节而未到达测试，须有原件定位实际失败步骤，由 #2132 在正式门登记能重跑同一步骤并验证同一失败条件消除的具名 R05 检查；仅有“无日志”不能取该合同。DevSkim 历史红灯只照录，当前 DevSkim 由 R08 承担。

| 历史票 | main 落地提交 | 不可删的具名 cure（即使原 run 过期） |
|---|---|---|
| #1392 | `8619a20f2800095e6bb9ec20ba2607a744740f91` | `m3_partition_synthetic_holds` |
| #1404 | `f95a7f3ebc0ce84ec2d2f8a8d71b5030b19f89b9` | `calibration_sweep_finds_non_collapsed_segments` |
| #1414 | `465174240b989a1d99f99a047fbb46b3ee215f49` | `seam_btc_tick_bars_yield_non_trivial_structure` |

#1414 及 #1493 所涉 30 秒公用读契约仍由 #1360（含缺陷 #1497 对应承接）在 F 测，不用旧夹具放宽替代。实测历史红灯与未定位的 cure 缺口列在起草证据；不据该快照预填成功或把未观测写成 `NO_RUN`。

### R12　TB 与逐键归并

TB-11 的前置门**只**读 F 上 .sandcastle/ 目录下由 #1391 交付的 `at18-report.mts`、由 #1403 交付的 `at18-verification.mts`（均为普通非空 blob）、合法 `input_bundle`、R08 与 R09；缺条件记 `TB11_PREFLIGHT`。不读任何报告产物、后续关票状态或 Destination 结论。其 113 个键在报告阶段只引用该输入包、由此前置核销；#1403 独立总验与随后原生关票是最终条件。入口、工具实现不是完整产品验收的替代。

每个非 TB-11 键须覆盖 R03 的每个 basis、每个域：必执行域过 R04–R06；涉及运行记录的同时过 R07；允许延期域只登记 R04 的具名情况。失败即键失败，无第二条路径。每个规范条目以其所有切片键归并：任一 FAIL 即条目 FAIL；否则按边界、合法延期、全部运行验证三者取 `PRESERVED_BOUNDARY`、`BOUNDED_DEFERRED` 或 `VERIFIED`，保留已验和延期的引用。无绑定的 TB-11 键不可加延期。

TB-01..10 逐 TB 要求：汇总票及每张带 `wayfinder:impl` 原生子票口径均为 `CLOSED/COMPLETED`（子票分母非空；票或集合不全分别记 `TICKET_NOT_CLOSED`、`SUBTICKET_INCOMPLETE`）；全部键非 FAIL（`TB_KEYS`）；R07 本 TB 相关专用门、封印实体、R08/R09 及本 TB 的 R10/R11 义务成立；在制品处置仍遵通用门。#1359 旧关票不回写；#2132 承接 TB-01 的新验收前置。其余 TB owner 关票前，在当时的主线头一次 dispatch 核自己的检查，报告阶段再在 F 全量重核。未关 TB 不使同一组 F 上成功的检查变红，但该 TB 门仍关闭不了。

### R13　旧票与 Destination 只聚合一次

旧票按第四节的七项原义务。状态、链接的原生子票和正式关票/授权事件向 GitHub 获取；行为取 R12 的键和 R07 原件。历史处分从本 ADR 第四节钉住的票、规范档及文书原件读，不以调用方的 `disposition_valid` 为真。#2131 给这些具名处分设置固定机读解码器：每项固定核准出处（Git 对象和 issue/comment ID），对相关原件用固定字段、行/段或完整字节 pin；漂移或无法解码即失败 `LEGACY_DISPOSITION`。

- #942、#1282 核已关闭且保留各自原处分；从附件及评论取原始出处，不给它们任何 F 运行命中。#1096 核 TB-10 的入口终态清单与 ADR 0048 退场条件；#1319 核 TB-08 的 feed/wire 决议和 TB-04、TB-09 的绑定实际结果。按第四节用同一事实生成处分、证据和未完清单。
- #1304 核 TB-07 对应键和 ADR 0058 AT-14 实体与锁；#1320 核 TB-07 对应键，重型测量另找七标的完整测量实体或具名有效废弃裁定，否则保留 OPEN 并按第四节延期。报告不接受「关票即测量已完成」。
- #1279 须 OPEN、无提前关图或放行。查实际 GitHub 票态及发布方正式记录；在读取完整评论时，对不符合第四节而明示放行的编排者声明也拒收，不能以缺正式格式把已有违规放行当作没发生。#2131 固定检查原件及其核实范围，无法确定时不得通过。剩余自有义务从 #1279 自有检查单按原稳定条目定位，排除 #1323/#1340 的全量义务；不能将本图失败项移入自有清单。

对每个 DST 取 crosswalk 的 `story_ids|family_entry_ids|detailed_acceptance_ids`，三集引用均须可解析；关联条目全部非 FAIL，其全部关闭切片满足相应 R12 门；应用该 Destination 的第二节专用门，DST-06 另应用 #1304、#1279 合法去向。R08/R09 不成立也不得给任何 DST PASS，失败记 `DESTINATION_AGGREGATE`。第四节 #1279 本图义务条件只消费这些 **聚合前因子**，不读取任何 Destination 的成品结论，也不读自身 `disposition_valid`。要关的 #1369、#1340、#1323 均不是报告前置。

**拓扑顺序**：R01 → R02 → R03 → R05 静态核 → R06/R08/R09 取服务端事实；R06 → R07 专用原件与非激活事实 → R04 延期最终核（R04 静态域先于执行，不能由执行结果改变）；R09 → R10，R05/R06/R10 → R11；R01/R08/R09 → TB-11 前置；R03–R07 + TB-11 前置 → 键 → 各规范条目；键 + R07–R11 → TB-01..10；条目、TB 门与专用因子 → 旧票（含 #1279） → Destination → 整图报告 → #1391 → #1403 → #1369、#1340、#1323。任一处失败不改规则或集合重判。

### R14　失败是可消费的数据

引导成功后，各规则失败均至少输出一个第五节的 `FailedCheck`，`scope` 按第八节定位；`check_id` 为本条文所列诊断码（第五节的形状、引用、祖先和声明失败另用 `SCHEMA`、`ARTIFACT_REF`、`ANCESTRY`、`STATEMENT_MISSING`；其派生规则仍用所列步骤码），`scope/detail/evidence_ref` 只取第八节的规范投影，不照录上游任意文本或日志。逐个缺失键、检查、票、路径或字段登记；无法求分母先记源失败，受依赖的汇总直接为失败而不猜分母。缺 GitHub 作业/状态行不伪造结论；`workflow_runs[].run_id/run_attempt=null`（或留实测身份）、作业/审查数组缺项不填假行；历史只在成功查询为空时记 NO_RUN。权限缺失另列 `permission_blocked[]`，必跑未跑列 `unexecuted[].required=true`（`obligation` 按第八节取带证据域的键或槽位 ID），不占四条合法延期的身份。#1403 还须按报告同一原件重算报告字段及全部结论，失配逐处记 `REPORT_MISMATCH`；封包未登记或受验报告形状不合，按第五节输出 FAIL 回执，不借 summary 文字放行。

## 七、实施归属与图边

承接票 #2131、#2132、#2133 均在 #1369 下，不另开同用途票。#2131 交付登记册合同、lint、运行器、两个验收 workflow 与 DevSkim 的 dispatch；#2132 交付全 TB 闸前底册、PRE、具名复跑锁及 TB-01 键。#1360..#1368 各汇总 owner 负责本 TB 剩余键、实体与实际主线运行；#1366 下 #1381/#1399/#1411 分别保留输入与 profile、seek/AsKnown、双进程与恢复，#1418 仍按 ADR 0058 交 AT-14 原件和锁。#1391 生成、#1403 独立总验，均不充当登记的独审者。#2133 用户签署原有效域，不派代理代签。

沿用现有边 #1551→#2131→#2132、#1551→#1369、TB-01..10→#1391、#1359/#1391→#1403；落地时补 #2131→#1360..#1368、#2132→#1391、#2133→#1365/#1367/#1368。#1403 经 #1391 消费全部 TB，无须重复接边。#1359 已关，#2131 的依赖经 #2132 兑现，不对 #1359 回挂阻塞或重开；不变更切片间既有排程。#1493 从 #1323 直属改挂 #1360，保留其已关记录和原依赖。主控同时在 #1391 写 R01 操作窗口，在受影响的 open 汇总票加本 TB 绑定与一次主线 dispatch AC。旧关联票不设为逆向整票 blocker。

## 八、报告字段的唯一投影（#1391 与 #1403 共用合同）

本节只规定如何编码事实；R01–R14 规定哪些事实和通过条件成立。两端以 F 固定来源读取并分别实现；#1403 可读取同一份已登记原件及 F 上的版本化适配器**数据合同**，不调用 #1391 的生成器，也不以被验 JSON 的任何说明、分类或排序作为输入。缺原件时按第五节缺值规则填报，同时按下列失败投影发出失败记录。若结构化结果会因新观测而改变，按 R01 作废本轮，不从报告补值。用于 R13 的 F 版解码数据合同逐一固定各原子义务所需来源、提取位置及引用角色；同类别有多个有效来源时取全量，不由实现选择一条有利记录。正文的自然语言解释只写同源摘要。

### 身份、时间与排序

- 各文档的 `schema_version` 取对应常量，`ticket/base/head` 取本票通过引导的 manifest；#1403 用 #1391 报告对应 manifest 重算后者的三个值。报告 `generated_at` 与回执 `verified_at` 分别为写出时 UTC，统一用 RFC 3339 的 `YYYY-MM-DDTHH:mm:ss.sssZ`（有更高精度截到毫秒）。原件时间另用同一格式转换；比较业务时序用原始精度，不因展示截断给出通过。对报告先验时间合法且在窗口内，再以该已验证时间放回独立重算的对象，重算 `content_hash`；比较完整 JCS 对象，包括重新算出的摘要，而不是让两个写入时钟相等。输入包引用从 #1391 manifest 的唯一标准文件条目按实际字节求得，独立核包的所有字段与该包自己的时刻/摘要；不重新生成一个带不同时刻的包去替代。
- 数组默认按下述主键升序、去精确重复。数字按数值、字符串按未经 Unicode 归一化的 UTF-8 字节序、`null` 在先、布尔 `false` 在先。主键相同而内容冲突时记 `SCHEMA`，冲突元素不入数组，不选择先到者。保留第五节固定位置的 Destination、TB、旧票、workflow、切片账，以及 SPEC 覆盖数组原行序；其余字符串数组按值，整数数组按值；不能用 GitHub 分页或并发完成顺序决定结果。
- 引用数组键：`ArtifactRef=(storage,path,commit,ticket,base,head,sha256,bounded_scope)`；`ManifestRef=(ticket,manifest_path)`；`ReviewRef=(merge_commit,pr,status_id)`；`CiRunRef=(workflow,run_id,run_attempt)`；`AcceptanceJob=(workflow,run_id,run_attempt,job)`；`HistoricalDeviation=(ticket,commit,workflow,run_id)`；切片及下游票用 `ticket`；`TicketScopeRef=(ticket,scope)`；延期用 `obligation`；权限阻塞用 `(obligation,blocker_ticket,evidence_class)`；诊断用 `(check_id,scope,detail,evidence_ref)`（引用按其键）。不排序结构语义所需的时间序列。
- 仓内 ArtifactRef 的路径/提交用对应规则钉住的 Git 路径和 SHA，仓外身份和绝对路径只用匹配 manifest 的原始条目，不取本机别名、自报路径或自报范围。所有 ArtifactRef 的 `bounded_scope` 恒为 ASCII `AT18:<role>`；每个引用位置按用途取唯一角色：五种输入按 `SPEC/CROSSWALK/COVERAGE_INPUT/REGISTRY/PREGATE`，切片账用 `SLICE_LEDGER`，输入包及报告用 `INPUT_BUNDLE/REPORT`，R07 封印原件用 `RUN_RECORD`，签署用 `AUTHORIZATION`，旧票规范出处用 `LEGACY_SOURCE`，ADR 0058 合法仓内实体用 `AT14_REPORT`。同一对象在证据数组中保留生产它的这些角色，不因转入另一数组重命名。运行槽、裁定和用途边界由原规则求值，不从角色字符串反推。
- `ReviewRef` 逐字段取 R09 实际 PR、H、M 与最新精确 context 的状态记录；`CiRunRef` 取 R08 所选 run 的 workflow 路径、id、attempt、head_sha、结论、`html_url`；运行、作业和历史偏差只取 R06–R11 的服务端字段（作业名取 Jobs API 的 `name`，结论按第五节枚举），不得从日志摘词。GitHub 票态取 API `state` 大写，已知 `state_reason` 只取 `COMPLETED|NOT_PLANNED|REOPENED|DUPLICATE`，无值填 null，未知值留红不照录。TB-11 的 `slices` 只列 #1391 与 #1403，两行写报告生成时刻的实际状态；OPEN 时 `state_reason=null`。#1403 用实际创建、关闭/重开事件重放这两票的报告时态，不用封包后的新票态；报告时 #1391 非 OPEN 或两票阶段无法证成，按第三节留红。其余票态取同窗观测，状态发生改变则按 R01 作废；包括签署、历史 CI 原件、绑定规则和上游实体在内的决策输入不得在同窗换源。服务端查询失败不等于已知缺失。

### 投影表

| 字段 | 唯一来源／投影 |
|---|---|
| 输入包引用、`external_manifests` | 第五节固定仓内对象及顺序；上游只列下面规则实际消费的、由有效原件匹配的 manifest，去掉本次报告发布才追加的目标包/报告条目。 |
| `destinations[].obligation` | F 的 SPEC JSON 中 `stories` 唯一 `id="US-DST-0<n>"` 的 `observable_result` 原字符串（不改写空白）；缺失用 `DST-0<n>` 作身份并报 `COVERAGE_SOURCE`。 |
| Destination 的 `tickets/commits/downstream_status` | 从该 DST crosswalk 三集取所有对应 closure TB；其汇总和 R12 原生实施子票进入 `tickets`，`scope` 固定该 TB 的 ID；加 R10 经对应 TB 归属的补修来源票，同一票可属多个 TB；DST-06 另加 `(1304,"LEGACY")`、`(1279,"LEGACY")`。`commits` 取可确认的 F 加这些票的 R10 历史提交；`downstream_status` 取同一票号集合的实际状态。 |
| Destination/TB 的主线、CI 和审查 | `main_sha` 为 R01 确认的 F，无法确认时 null；两类记录均列 R08 的两个通用 CI 及 R09 观察到的全部集成审查（含 PRE 锚的有效合入记录）。这些门对整图适用，不能按作者猜测裁切。 |
| Destination/TB 的证据与未完 | TB 实体取 R07 按 TB 和证据类封印的所有合法记录；Destination 取其 closure TB 的实体及第二节适用于该 Destination 的专用槽原件。simulation/experiment 分槽放现有合法引用，production 本版固定 null；TB-11 按第三节固定空实体／证据和输入包引用。两类 `remaining_obligations` 只投影归属其义务的 `unexecuted` ID、失败覆盖键 ID（`key:<slice>/<kind>/<id>`）、未完成必需票 `ticket:<n>` 与适用的失败诊断 ID（`check_id+"@"+scope`）；适用范围从 R12 的 TB 与键和 R13 的对应关系取，整图门失败适用于全部，不把 TB-11 阶段待关写成失败。TB `tb_id/ticket` 固定 TB-01..11 对应 #1359..#1369，`slices` 来自 R12 原生实施分母。最终 `result/gate_satisfied` 分别取 R13/R12。 |
| 权限、能力、迁移、后闸 | 第二节与 R07 的三类记录。每槽引用取该合法记录/场所原件的全部已封印来源，单值槽若有多条候选仅在对同一业务身份互证且无冲突后取引用排序第一项，否则缺值并留红；能力三元组版本取实际能力记录规范版本字段、两个摘要取能力记录与场所 profile 的原始字节；场所来源 URL、取回时间取 #1770 来源字段；后闸时间只取所配对的实际三记录时间字段。布尔值与状态从 R07 重算，不从文件的结论键照录。Destination ⑤ 槽的能力值原样投影到顶层。 |
| `spec_coverage` | 标识、族、闭包切片与 DST 从 R02 各对应 crosswalk 行的字段逐值投影；family 的 `entry_mode` 按第五节；`status` 按 R12。条目证据只列适用的登记册引用（有通过的非 TB-11 键）及输入包引用（有通过的 TB-11 键）；`deferred_gates` 取该条目获准延期域 ID 并集，无则空。 |
| `legacy_dispositions[]` | 固定票序。`disposition` 按票依序固定为 `PRESERVE_BOUNDED/RETIRE_OR_INCORPORATE/PRESERVE_ARCHIVE/ADOPT_AT14/INCORPORATE_FEED_WIRE/REPLAY_AND_PRESERVE_HEAVY/KEEP_OPEN`（逐票一值）。证据取 R13 固定解码器实际消费的来源引用及该票专用实体，不列交叉票的所有产物。`remaining_obligations` 取未证成的 R13 义务 ID；#1279 自有义务用 `ISSUE_1279:<规范原件 JSON Pointer 或固定评论 ID 和条目序号>`，从 R13 固定检查单取，不复制说明文字。本图义务失败留 R13 诊断，不列到 #1279 的自有清单。状态及 `disposition_valid` 只取 R13。 |
| `workflow_runs/acceptance_jobs/historical_deviations` | R06/R08 四次独立选择、R06–R08 精确名字或名字语法所及的实际尝试作业和封印行、R11 逐归属偏差。未声明作业、替代运行和互不匹配的封印不作证，不从结果中反选。 |
| `bounded_domain_statement` | 第五节三条固定声明按列出顺序，以 LF 连接（末尾不加 LF），然后依次追加 `AT18_SCOPE SIMULATION_P1_ONLY`、`AT18_PRODUCTION_SLOT DISABLED`、`AT18_POST_GATE_EXPERIMENT <state>`、`AT18_POST_GATE_PRODUCTION <state>`（空槽写 `DISABLED`，否则取实际状态枚举）；若具名重测仍保留，再追加 `AT18_HEAVY_MEASUREMENT DEFERRED`。计数为 `historical_deviations.length` 的无前导零十进制。 |
| `overall_result`、回执 `verdict` | 第五节合取及逐字段比较，不能从摘要或已关票推断。回执的受验引用、报告 manifest 与报告摘要取其已登记实体，能算到哪一步按第五节写到哪一步。 |

### 原因、缺口与诊断码

- 四种合法延期的 `(reason, blocker_or_gap)` 固定如下；只有第五节触发条件成立才列，`required=false`、证据类仍取第五节。后闸未知时写 `UNKNOWN` 显示不可证，并照 R07 留红；不据该行给 R04 可延期通过。

| `obligation` | `reason` | `blocker_or_gap` |
|---|---|---|
| `ISSUE_1561_P2_FIRST_SEND` | `PRODUCTION_NOT_ENABLED` | `ticket:1561` |
| `ADR_0036_POST_GATE_EXPERIMENT` | `POST_GATE:<实验槽状态枚举或 DISABLED>` | `adr:0036` |
| `ADR_0036_POST_GATE_PRODUCTION` | `POST_GATE:<生产槽状态枚举或 DISABLED>` | `adr:0036` |
| `ISSUE_1320_HEAVY_MEASUREMENT` | `MEASUREMENT_NOT_COMPLETED` | `ticket:1320` |

- 必跑未跑：按义务 ID 归并（键使用 `key:<slice>/<kind>/<id>@<evidence_class>@<profile_id 或 none>`，专用门使用 `slot:<record>@<profile_id>`）；同一义务多个未跑原因只按以下顺序取第一个：权限未证 `AUTH_REQUIRED` → 来源不可用 `SOURCE_UNAVAILABLE` → 完整尝试无相应执行 `CHECK_NOT_RUN`。对应 `blocker_or_gap` 分别写 `ticket:<最小有效硬门票号>`、`SOURCE_UNAVAILABLE`、`CHECK_NOT_RUN`；`evidence_class` 从对应域或槽条目取。实跑失败写诊断，不冒充未跑。权限阻塞按同一义务和每张未满足的实际硬门票输出，`missing_authorization` 固定 `AUTH_REQUIRED`，`blocker_ticket` 取实际硬门票（P1 凭据接触面为 #2133，发送另外适用 #1412）；不抄票面文句。无有效 #2133 仍填必跑未跑及权限阻塞，不能冒充合法延期。
- `FailedCheck` 只读原规则的诊断码。每个被测对象/字段未满足命名判据即写一行，`detail=check_id`；同一码同一作用域合一，不用真人或异常对象的措辞（归因细节由取证原件和人读摘要承接）。`evidence_ref` 固定用该失败检查所读取且自身合法的最小引用（按引用排序）；源读取/校验失败或无合法引用固定 null；同一码同一域合并时在全部合法引用中取最小，否则 null。作用域按被检对象的合同身份固定：覆盖与关联域用 `key:<slice>/<kind>/<id>`（涉及 basis 或域时各追加 RFC 6901 转义的路径/指针及类/profile）；集成、历史分别用 `commit:<SHA>` 和 `history:<ticket>/<SHA>/<workflow basename>/<run_id 或 none>`；权限用上述义务 ID；票态和专用旧票用 `ticket:<n>`（具体义务追加其稳定 ID）；PRE 逐路径用 `pre:<Git 路径>`；检查/作业/记录分别用 `check:<check_id>`、`job:<workflow basename>/<run_id 或 none>/<job name>`、`slot:<record>@<profile_id>`；其他字段用报告 schema 的 RFC 6901 指针（数组上用规范顺序，缺项用规则应有的位置），源失败用读取该源的字段指针。不得由异常文案决定 ID、引用或粒度。`REPORT_MISMATCH` 只在回执，按 JCS 对象递归遍历，对首个缺键、类型/标量差异、数组长度差异输出相应 JSON Pointer；长度不等的数组在其自身停止下钻，其余继续逐叶列差异。两端不得只比较总体布尔值。

诊断在投影剩余义务之前完成；剩余义务与摘要不参与判定输入，也不从它们再派生诊断。R13 的稳定旧票原子 ID 及各自语义固定如下；其余 #942/#1282 已定范围内的原文附件仅作来源，不能新增待执行项：

| 票 | 稳定义务 ID（每项按第四节原条件核验） |
|---|---|
| #942 | `ISSUE_942_DISPOSITION` |
| #1096 | `ISSUE_1096_ENTRY_END_STATE`、`ISSUE_1096_RETIREMENT_CONDITIONS`（发生删除才核） |
| #1282 | `ISSUE_1282_ARCHIVE` |
| #1304 | `ISSUE_1304_REPLAY`、`ISSUE_1304_RECOVERY`、`ISSUE_1304_AS_KNOWN`、`ISSUE_1304_STATE_PARITY`、`ISSUE_1304_AT14` |
| #1319 | `ISSUE_1319_FEED_WIRE`、`ISSUE_1319_INTENT_RECEIPT`、`ISSUE_1319_SEND_ISOLATION` |
| #1320 | `ISSUE_1320_FULL_REPLAY`、`ISSUE_1320_HEAVY_MEASUREMENT`（未销项仍单列） |
| #1279 | 自有检查单 ID，按上表；本图前置条件只作 `disposition_valid` 与相应诊断的输入 |

#2131 交付的 F 版规范适配器逐字段钉紧 JSON Pointer／固定来源 ID 与类型，尤其是运行记录的业务字段、#1770 文档来源字段和 #1279 自有检查单清册；不得交付多个候选取值器。验收夹具须包含同一原件不同分页/输入顺序、不同日志措辞、#1391 封包前后状态、两个共享提交归属、#2133 无效授权、可延期与必跑未跑，以及改一个合法标量造成精确 `REPORT_MISMATCH`。#1403 以原件为输入独立实跑，对比双方结果。
