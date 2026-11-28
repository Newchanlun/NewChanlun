# ADR 0064：AT-18 整图验收报告与关票门

> 正本：本文件是 #1323 AT-18 六项 Destination 逐项核验、TB-01..11 关票门、旧关联票去向与整图报告的正本。
> 最后裁定：仅以承载本版最终正文的 PR #2161 合入 `main` 时，其实际获审 head 的正式 `deepagents/review` 双审 PASS 为准（#1551，P 类，依 #1909 代理独审裁定，ADR 0041:41）。PR #2065 是旧稿，不是本版裁定依据。
> 受影响代码清单：本 ADR 不直接改产品代码；#2131 在冻结前交付登记册、lint、运行器、workflow 与独立验证器 `.sandcastle/` 下的 `at18-verification.mts`，并落实 R09 合入入口及 R09/R11 历史留证；#2132 负责 TB-01 绑定及闸前复审；#1391 交付生成器 `.sandcastle/` 下的 `at18-report.mts`、生成并封包，#1403 在 #1391 关票后独立执行总验，#1366/#1418 保留 TB-07/AT-14 合同。

## 一、范围与现状

本 ADR 只裁验收证据、报告结构和关票簿记，不交付运行证据，不提前关闭 #1279、TB-11（#1369）或任何实施票。

ADR 0063 的迁移协议合入不等于 #1368 与 #1402 的非空迁移、回退与恢复已经验收。ADR 0058 的 AT-14 仓内报告路径继续有效。新整图输入包、整图报告与独立总验报告按现行仓外交付 manifest（`.sandcastle/CODEX-CHILD.md:54, :58-63`）管理，不将某台机器的绝对路径写成永久报告身份。

本 ADR 不签署真实资金、账户或场所激活、量档容量、成本与风险阈值、属用户专属闸门的后闸参数值及凭据权限；这些事项仍适用 ADR 0036:29-33 与 ADR 0041:46 的授权硬门。普通研发参数按第二节第 4 条核验。

## 二、AT-18 逐项证据与整图覆盖义务

**读法裁定。** SPEC #1340（`.chanlun/review-results/issue1339-r2-spec-20260909/payload/spec/SPEC.md:422, :370`）的 AT-18 条目所列「实装、最终独评、落地主线及适用 CI」指报告所验的实际主线头 **F**：每项 Destination 对 F 上的最终行为、独评覆盖、主线 CI、实体报告及下游状态逐项求值。TB-11 条目要求汇集实施及独评；不要求在历史落地时点逐片重证 CI。通用交付门仍照 `.sandcastle/docs/graph-engineering.md:15, :237-241`，历史没有绿灯就不得写成当时通过。要求按历史提交重证会使当前验收不可达：R11 的历史原件仍有红灯与无运行，闸前版 DevSkim 也没有手动触发；F 的绿灯不回写为历史合规。#1551 退回裁定见评论 7047086314。

六条 Destination 仍各自有完整义务、实施范围、证据类、相关票态、未完义务与 PASS/FAIL。F 的检查承担当下可重复的行为证明；第六节 R09 核闸后的主线集成，R10 按实际落地、F 留存路径与 blob 身份核闸前复审，两门必须同时满足。片的历史落地列作出处，不拿它的 CI、独评或 manifest 当 F 的证明。

受测场所、隔离、带仓迁移、闸门后参数与 SPEC 全量覆盖核验须同时满足以下五项接口：

1. **证据类严格分列（ADR 0028:48, :70-71；ADR 0062:104, :258；ADR 0063:78-79, :120；CONTEXT.md:373-375）**。每条验收证据必须标明 `evidence_class`。`P1`（`experiment`，如 `P1-hl-testnet`）证据与 `production`（`P2`）证据在 Destination 记录、TB 汇总与整图报告中分槽记录，不得混记，不得以 `P1` 证据冒充生产有效，也不得将 `P1` 拒发语义外推为 `production` 已裁。已启用证据类槽位统一使用 `ArtifactRef[]` 数组（该槽位在当前记录无条目时填 `[]`）；未启用部署槽位（如本图 #1561 下尚未启用的 `production`）统一填 `null`，不得填 `[]`，并保留「生产首次新发送前」具名门。
2. **Destination ⑤ 权限证据三层与能力 hash（ADR 0062:51-79, :258-259）**。Destination ⑤（「目标部署的隔离和权限证据」及 paper 与 live 共核关系）按受测 `evidence_class` 分列核验三层权限证据：（a）授权声明，即场所 profile 记录中由用户签署的 `credential_scope.class` 与 `authorization` 行；（b）场所权限事实，即 #1770 能力记录 `session_permission` 来源栏登记的场所文档 URL、取回日期与 `sha256`；（c）运行时核验，即 X 库启动记录中发送门第 4 至 7 步核验结果与观测记录。三层分开记录，缺任一层或以一层替代另一层均不得记权限证据成立，Destination ⑤ 必须判 `"FAIL"`；已启用场所槽位缺某层证据或缺能力记录时，按第五节 `PermissionSlot` 规则把该层字段或 `capability_hash` 填 `null` 记录缺失，不把整个槽位填 `null`。整体验收的能力 hash 固定取 `(capability_record_version, capability_record_sha256, venue_profile_sha256)` 三元组，同版本异内容或顶层与 Destination ⑤ 分槽值不一致即判冲突失败。
3. **带仓迁移与回退四项不变量（ADR 0063:120, :123）**。涉及旧入口终态、发送隔离与带仓迁移的核验（Destination ②、③、⑤ 及 #1368、#1402）必须基于非空持仓、未结单、费用尾、中断恢复与回退的实际运行证据，逐项确认不丢权利、不复制资金、不双写、不补发四项同时成立，并按 `experiment` 与 `production` 分槽写入顶层 `migration_invariants`；空仓样例或仅合入协议文书不计通过。
4. **闸门后参数按重核验（ADR 0036:26-33, :42）**。TB-11 在各已启用部署槽内，按 `(evidence_class, profile_id, chong_id)` 核验同一受测运行涉及的全部重，逐重保存于 `post_gate_records.<部署槽>.chong_records`，不得择一或折叠。`destination_ids=[]`：后闸原件只留顶层专用槽，不进入任一 Destination 或 TB 的 `evidence_by_class`；键下的延期仍按第八节投影。逐重状态与原件要求如下：
   - `TRIGGERED_AND_ENABLED`：该重当前阶段能力启用或后闸参数仍生效。须出示相互绑定的正式 `GateReachedEvent`、合法参数版本与首次启用记录，满足 `触达.known_at < 版本.authorized_at < 首次启用.known_at`。
   - `TRIGGERED_ENABLED_THEN_REVERTED`：该重曾合法启用，当前已按 ADR 0036:31 回退。保留同样的首次启用三记录，另出示实际回退触发与执行原件（`K` 回正是固定回退项）、生效版本及回退后状态，证明回退晚于该次启用，回退后能力关闭、该后闸参数不再生效，且未擅自恢复。
   - `TRIGGERED_VERSION_AUTHORIZED`：该重已正式触达且参数版本已授权落盘，须出示触达与授权记录，满足 `触达.known_at < 版本.authorized_at`，并证明尚未首次启用、`growth_enabled=false`。
   - `TRIGGERED_AWAITING_POLICY`：该重已正式触达但无适用授权版本，须出示触达记录，并证明保持 `AwaitingPolicy{post_gate_params}`、`growth_enabled=false`。
   - `CANDIDATE_ONLY`：该重有 `GateReachedCandidate`、无正式 `GateReachedEvent`。须以独立于候选标签的原件逐项证实至少一项正式门槛未满足（例如触发原件未全部 Applied、有 Pending 覆盖或 B/E 对账不一致），并证明 `growth_enabled=false` 且从未切换或启用后闸参数。证据齐备可通过，候选仍须记入报告；仅有候选而缺门槛证据，或私自切换或启用后闸参数，必须 FAIL。
   - `NOT_TRIGGERED`：该重资格谓词 `growth_eligible` 在受测运行中从未为真，既无 `GateReachedEvent` 也无 `GateReachedCandidate`；须出示同一重未触达且未启用的证据。不能凭缺事件判断未触发。

   每条记录均须匹配该重、profile 和证据类。`TestOnly` 和历史双跑的 `SimulatedGateReached` 不计正式触达或启用；`experiment` 版本不自动迁入 `production`。所有重都有效才可通过。曾启用与从未启用分别核验：前者逐重满足 ADR 0036:33 的三记录门及 R07 的实际行为检查（已回退的重加验回退后行为），后者须以逐重 `non_activation_evidence` 证明 R07 所定的完整启用历史边界。按第五节聚合槽状态、写入 `bounded_domain_statement`，合法未启用部分以同槽唯一的 `unexecuted[]` `required=false` 条目记账；该条目不豁免同槽其他重的检查。
5. **97 故事、345 family 条目与 496 细项逐项对账（`.chanlun/review-results/issue1340-publication-20260909/view/inputs/TB07-11-EXECUTION-SLICES.md:278, :290`；`.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/IMPLEMENTATION-CROSSWALK.md:5, :115`）**。#1391 必须对照 `IMPLEMENTATION-CROSSWALK.json` 逐条核完 97 个故事、345 个 family 条目与 496 个细项验收输入，写入顶层 `spec_coverage` 供 #1403 逐条复核。crosswalk 条目带 `exclusion_boundary=true` 的 family 条目（所绑定 crosswalk 上是 `OE41` 与 `OE45`）只核排除与防混用边界，其余 family 条目全部是必需条目。`OE42` 是必需条目，#1391 须核实覆盖输入为它登记的 `OUT_OF_SCOPE_PRESERVE` 处分得到遵守（规则见第五节 `SpecCoverageLedger`）。不得仅凭测试计数、子票关闭率或 `N=2` 样例代替逐子义务核验。
第二节第 4 条所称参数版本的「授权」按实际生效域核验。真实资金、真实账户、场所实盘或权限激活、真实交易量档与容量、成本和风险阈值，以及其他用户专属闸门后的参数值，须有对应用户签署原件。ADR 0036:30 所指普通研发参数，在触达证据具备后，若该生效域未启用真实账户或资金能力且不触及上述硬门，可用获非作者独审 PASS 的代理裁定原件。按 ADR 0041:41, :45-48 核对票号、作者、独审身份、实际获审版本、原件与生效域；不得把代理裁定记成 `UserSigned`。两类授权均须与受测的版本、profile 和证据类吻合，适用相同的互引与时序。
组件证据、协议裁定、局部成功、正确拒绝、空域、仅 schema 或未执行测试均不得代替必需成功路径。缺证、跨证据类冒充或射程不符即不得判 `"PASS"`。

## 三、TB-01..11 关票门

关票通用门（`.sandcastle/docs/graph-engineering.md:237-241`）要求票面验收全部满足，全部必需子片交付，非作者评审覆盖最终产品差异，产品进入 `origin/main`，适用必需检查通过，实体报告可读并绑定版本，在制品已有合法处置。失败、未构造、未执行、权限阻塞及跨 TB 未闭合的联合义务必须保留为未完成，不得记为已处置失败。

关票分三阶段，不以任一后置产物证明其前置：

1. **TB-01..10**：按 R12 逐片核原生子票、最终主线行为、实体报告、审查覆盖和各自剩余义务。TB-08..10 的 experiment 必须有本类实测；TB-10 另核本片非空迁移，不能借其他切片证据。
2. **TB-11 前置**：按 R12 只核 F 上 #1391 的生成器、#2131 冻结前交付的独立验证器、F 的通用 CI 与独评覆盖、输入包；`gate_satisfied=true` 只代表前置齐备。生成报告时 #1391 应 OPEN，不要求 #1403 或 #1369 先关；TB-11 的 `entity_reports=[]`、已启用证据类数组 `[]`、未启用 production 槽 `null`。输入包引用按第五节取值；登记可照录但实体不合时前置仍失败。前置门不读本轮成品报告或总验回执。
3. **封包与关图，分两阶段**：
   - **#1391 生成与封包。** 先在 F 上落盘 `at18-input-bundle/1`，在 #1391 自身仓外 delivery manifest 的 `reports` 登记 `at18-input-bundle.json`。生成报告时直接读取该本票清单，按第五节照录登记并另核实体。再落盘并在同一清单追加报告登记，保留输入包原登记及字节。报告不引用将追加的报告条目，也不等 #1403 回执。只有 `overall_result="PASS"`、通过第五节封包预检门且非作者最终独评 PASS 才关 #1391。
   - **#1403 独立总验。** #1391 封包关票后，在同一 F 独立运行 #2131 交付的 `.sandcastle/` 下的 `at18-verification.mts`，读取同一份 #1391 manifest，独立校验其中的输入包与报告实体，并在自己的 `at18-verification/1` 写入 `report_manifest`、`report_ref`、`input_bundle_ref`。对同一 F、同一验收窗口复算，另按 R12 检验实际报告的四类证据；本票回执 PASS、通过同一封包预检门且非作者最终独评 PASS 才关 #1403。两票均完成封包关票、结果和票态在同一窗口复核有效后，才可依次关闭 #1369、#1340、#1323。主控在关闭 #1369 前最后一次按 R01 取证，固定该次通过的窗口与两份封包原件，并以此结束验收窗口、进入关图阶段；三张图级票的关票是窗外动作，不读其未来关闭事件为验收前置。两票的非作者最终独评评的是实际交付，R09 的产品集成审查不代替。


## 四、旧关联票去向

`TB-11-A`（`.chanlun/review-results/issue1340-publication-20260909/view/inputs/TB07-11-EXECUTION-SLICES.md:291-293`；`.chanlun/review-results/issue1340-publication-20260909/view/inputs/LEGACY-TICKET-DISPOSITION.md:88-96, :106`）涉及的七张旧关联票固定按以下边界核验：

- **#942**：保持 `CLOSED` 及既有逐问处分（编排者后裁「乙」接受文档推断加子账户显式 `standard` 防御性初始化，第 1、3、5 问因凭据约束不做，第 2 问已测未决，第 4 问强平实验明确不做，第 6、7 问按 `.chanlun/review-results/hl-margin-table-disabledex-20260808.md` 有界文档推理关闭，第 8 至 10 问挂 #953 等既有承接）。严禁把已关闭的 #942 表述为两家场所隔离已实测完成，也严禁借 #1319 恢复已拒绝的强平实验；受测场所能力与隔离一律按第二节 Destination ⑤ 三层权限证据及 TB-09 独立核验。
- **#1096**：由 TB-10 实际勘察并由 TB-11 对账；冻结或收编终态登记与未来实际删除分别举证，删除仍须满足 ADR 0048 退场条件。
- **#1282**：保持 `CLOSED`、冻结预注册判据（7 标的全部越过各自随机中位及双对照设计）与 #1279 历史实验落档结论，不重开旧翻转实验选择，也不得将该 M1 历史研究结论冒充本图新完整生产程序的回放或试运行验收证据。
- **#1304**：由 TB-07（#1366）完整历史回放、恢复、AsKnown、全状态对拍及 ADR 0058 AT-14 报告器（#1418）承接，#1282 旧翻转实验归档边界保持不变；上述本图承接证据、验收报告器及回归锁载体全部核实前保持 `OPEN`。
- **#1319**：既有 feed 与 wire 由 TB-08 按实际代码核定收编或废弃，并作 TB-08 证据回填对象，不恢复其旧组织（ADR 0028:81；`.chanlun/review-results/issue1339-r2-spec-20260909/payload/spec/SPEC.md:342`）；正式意图与回报归 TB-04，发送前隔离归 TB-09，其中涉及 #942 的可测项严格遵守 #942 既有处分，旧简化链不得冒充完整程序。
- **#1320**：正式完整程序回放由 TB-07（#1366 及 #1381、#1399、#1411、#1418）按 `history-input-profile/1` 承接，属整图通过必需项；ES、GC、CL、ZN、6E、BRN、DX 各十年 1min、冻结预注册 7 标的全量测量与完整结果保留按 `.chanlun/review-results/issue1339-r2-spec-20260909/payload/spec/SPEC.md:432`、`.chanlun/review-results/issue1340-publication-20260909/view/inputs/LEGACY-TICKET-DISPOSITION.md:94`、ADR 0052:310, :357 与 ADR 0058:124 在本图 profile 外单列保留，由 TB-11 对账。组件有界测试与 TB-07 有界回放均不得将该重型测量销项；该重型测量未实际完成且无另行合法废弃裁定时，#1320 必须保持 `OPEN`，并在 `at18-report/1` 的 `unexecuted[]` 中以 `obligation="ISSUE_1320_HEAVY_MEASUREMENT"`、`required=false` 单列记录（阻断将 #1320 关为已完成，不阻断本图整图通过）；若未完成且无合法废弃裁定却将 #1320 记为已销项或关闭，或漏记该单列未执行项，整图对账判 `"FAIL"`。
- **#1279 与 `#1279 放行门`（`.chanlun/review-results/issue1339-r2-spec-20260909/payload/spec/SPEC.md:218, :342, :376`；`.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/inputs/SPEC-COVERAGE-INPUT.md:67`；ADR 0058:66, :124；#1279 评论 `5466854598`、`5501144382`、`5596452227`；#1403 验收第 4 条）**：SPEC 上述关图条款所称「#1279 放行门」即 `DST-06`（`US-DST-06` 与 `A-DST-06-01`）定义的下游试运行拦截门，按报告阶段与关图阶段分层核验：（1）在 #1391 生成报告及 #1403 复核阶段，#1279 评论 `5596452227` 登记归属 #1323 与 SPEC #1340 的六项 Destination、确定性历史回放、账本与执行闭环及 `evidence_class` 分列运行证据由 R13 从各 Destination 聚合前的条目、TB 门、具名裁定门和专用门逐项证成（不读任何 Destination 的成品结论），`legacy_dispositions[]` 的 #1279 条目在 `remaining_obligations` 中零项混入 #1323 或 SPEC #1340 义务（仅列出不属于本图射程的 #1279 自有未完检查项，含评论 `5466854598` 所记跨资产 alpha 研究线及自有试运行核查项）；（2）#1279 当前 `ticket_state` 保持 `"OPEN"`，未提前关图且未宣布试运行放行，也不将超出本图射程的 #1279 自有检查单反向设为 TB-11 前置（以上两项同时成立时报告记 #1279 的 `disposition_valid=true`）；（3）在关图阶段，仅当 #1403 独立总验产出 `verdict="PASS"` 并完成 #1369、#1340、#1323 关闭后，才解除 #1279 上的 #1323 侧前置，且解除前置仍不自动关闭 #1279 或宣告试运行放行。若 `remaining_obligations` 混入任何本图义务、#1279 在自身条件未齐时已关闭或已宣布试运行放行，则 `disposition_valid=false` 并使整图判 `"FAIL"`。

## 五、`at18-input-bundle/1`、`at18-report/1` 与 `at18-verification/1`

整图对账与独立总验采用三份具名版本化仓外记录：输入运行包清单 `at18-input-bundle/1`（`at18-input-bundle.json`）、整图验收报告 `at18-report/1`（`at18-report.json` 及从同一份 JSON 渲染的 `summary.md`，自然语言说明不进入判定或比较）和独立总验回执 `at18-verification/1`（`at18-verification.json`）。三份产物均置于仓外持久证据目录，按 `.sandcastle/CODEX-CHILD.md:56-63` 与 `.sandcastle/delivery-bundle.ts:10-17, :27-38` 由所属票的仓外 delivery manifest 以 `storage: "external"` 绑定 `ticket`、`base`、`head`、路径及文件字节 `sha256`；移动或归档后更新 manifest 并重验。

规范化、`content_hash`、提交祖先与封闭类型规则（对齐 ADR 0025:30 与 ADR 0058:193, :208）：

- **`content_hash` 无自指计算口径**。对 `at18-input-bundle/1`、`at18-report/1` 或 `at18-verification/1` 移除各自顶层 `content_hash` 键后，将其余完整 JSON 对象按 RFC 8785（JCS）规范化为 UTF-8 字节串，求 64 位小写十六进制 `sha256` 写入顶层 `content_hash`。`content_hash` 绑定结构化语义内容，仓外 delivery manifest 的 `sha256` 绑定落盘文件完整字节，两者均不产生自指循环。
- **封闭字段集合与升版边界**。三份 schema 的顶层和全部嵌套对象均为封闭字段集合，禁止未声明额外键；总验器（#1403）遇到缺失必填键、类型不符、枚举越界、固定长度数组长度不符、`content_hash` 不匹配或未声明额外键即拒收判 `"FAIL"`，按下条输出回执；可定位的四类证据结构缺陷另按 R12 记录。本稿在首份正式 /1 报告发布前定义 /1；旧候选不兼容。正式启用后，新增、删除、重命名字段或改变字段语义须升版。
- **形状规则与判定规则分层**。本 ADR 的约束分两层。形状规则只有以下几类：三份 schema 顶层与全部嵌套对象的封闭键集；各字段的声明类型（含 `Sha256Hex`、`GitCommitSha`、`UtcTimestamp` 的格式、正整数，以及 `ArtifactRef` 按 `storage` 区分的 `commit`、`ticket`、`base`、`head` 取值组合）；枚举取值；`schema_version` 常量；文档自身 `content_hash` 按上条口径与其内容相符；`destinations[]` 6 项、`tb_summaries[]` 11 项、`legacy_dispositions[]` 7 项与 `workflow_runs[]` 4 项的固定长度与顺序；写入方自己决定的常量与槽位编码（如 `TB-01..TB-10` 的 `input_bundle` 固定填 `null`、未启用槽位填 `null`）。只有违反形状规则的文档形状不合法，由 #1403 拒收。其余约束都是判定规则，包括字段非 `null`、数组非空、跨字段或跨文档相等、哈希或摘要相符、文件可读、命中 manifest、祖先关系、时序、与 crosswalk 逐条对应的项数，以及状态与证据的搭配。判定规则不满足时照常写出记录：字段记实际观测值，证据缺失或不可读处按字段类型填 `null` 或 `[]`，在 `failed_checks[]` 写入一项 `FailedCheck`，所在记录的结论取失败值（报告 `overall_result="FAIL"`、回执 `verdict="FAIL"`、TB 汇总 `gate_satisfied=false`、覆盖条目 `status="FAIL"`）。本 ADR 写作「PASS 要求」的条件，以及落在判定规则上的「必须」「须」「非 `null`」「非空」「等于」「一致」「恰好」，都只约束取通过值的记录，不约束失败记录的形状。每份文档的身份字段（`schema_version`、`content_hash`、`ticket`、`base`、`head` 与 `generated_at` 或 `verified_at`）只取自该文档自身及登记它的本票仓外 delivery manifest，始终非 `null`，取不到时不写出该文档（见下条「引导前提与无文档结果」）；它与其他文档的任何关系（`head` 相等、哈希相符、命中 manifest）都是判定规则。输入包不承载结论，必需输入缺失或不合法时不生成有效输入包；报告与回执的输入包引用按下文「输入包登记与实体分开核验」取值。#1403 引导成功后，遇到受验对象缺失、不可读或形状不合法时，仍输出形状合法的 `at18-verification/1`：身份字段取自 #1403 自身 manifest；#1391 的 delivery manifest 可读且通过 `deliveryManifestSchema` 校验时，`report_manifest` 填指向它的 `ManifestRef`，否则填 `null`；`report_ref` 照录该 manifest 中形状合法的报告登记，无此登记时填 `null`；已登记的报告实体缺失或摘要不合时仍照录引用并留红；`report_content_hash` 按下文「派生值」规则取重算值或 `null`；每个缺失、不可读或形状不合法的受验对象按第八节写 `FailedCheck`，并判 `verdict="FAIL"`。
- **引导前提与无文档结果**。上条「照常写出记录」以写入方能写出形状合法的文档为前提；本条定义该前提不成立时的唯一结果。#1391 写出 `at18-input-bundle/1` 与 `at18-report/1`、#1403 写出 `at18-verification/1` 之前先完成引导，依次为：（1）读取本票仓外 delivery manifest（此时可尚未登记本次产物），它须可读且通过 `deliveryManifestSchema` 校验；除 #1391 本次报告所消费的输入包登记及实体（按下条判定，不作报告引导条件）外，已登记的 artifact 均按 `.sandcastle/delivery-bundle.ts:180-241, :246` 核重复登记、合法声明、版本、可读实体与字节摘要；未登记的本次输出不在此步核该文件第 242–245 行的必需报告完整性（完成封包时仍全量预检）。文档的 `ticket`、`base`、`head` 只取自它，不取自受验对象、调用参数、环境变量或当前 Git 状态（`HEAD`、分支、`origin/main`）；（2）写 `at18-report/1` 时，`destinations[]`、`tb_summaries[]`、`legacy_dispositions[]` 各固定项中类型不含 `null` 的非结论字段（`id`、`obligation`、`tb_id`、`ticket`、`disposition`）均按封闭 schema 取常量或唯一投影。Destination 的 `obligation` 按 R02 和第八节取值；规范源缺失、不可读、结构非法或字段缺值时用规定的 `DST-0<n>` 身份串并登记失败，仍写 FAIL 报告，不触发引导失败。其余固定身份取不到时不以猜测值代填；（3）待写内容能按本节 `content_hash` 口径规范化，字符串不能规范化时不照录坏值：有第五节缺值编码则填该缺值并按第八节写 `JCS_CANONICALIZE`（`scope` 取合同字段指针，`detail=check_id`）；无合法缺值编码或处理后仍不能规范化时，本步失败；（4）先写临时文件，再改名到输出路径。任一步失败时，该工具不写出该类型文档，输出路径上不出现该文档；它沿用 `.sandcastle/delivery-bundle.ts:116-132` 预检失败载体，在标准输出写出 `status: "BLOCKED"` 与 `diagnostics[]`（元素为同文件的 `DeliveryDiagnostic`，`code` 按上述四步依次取 `MANIFEST_UNREADABLE` 或 `INVALID_MANIFEST`，以及 `DUPLICATE_ENTRY`、`UNDECLARED_REPORT`、`REPORT_DECLARATION_MISMATCH`、`REPORT_VERSION_MISMATCH`、`INVALID_REPORT_PATH`、`REPORT_NOT_REGULAR_FILE`、`REPORT_MISSING`、`REPORT_NOT_IN_HEAD`、`REPORT_HASH_MISMATCH`（各按前述预检对应条件）；第（2）至（4）步分别用`FIXED_ITEM_UNAVAILABLE`、`CONTENT_NOT_CANONICAL`、`OUTPUT_WRITE_FAILED`），并以退出码 `1` 结束（与 `.sandcastle/delivery-bundle.mts:13` 对 `BLOCKED` 的退出码相同）。第（1）步失败时 #1391 两份文档都不写出。引导与写入使用未含本次产物的新输出目录，不以旧文件冒充本轮结果。消费方以输出路径上有无该文档判断，不从退出码推断；`BLOCKED` 载体不是文档，不得登记进 delivery manifest，也不能代替输入包、报告或回执。各消费方对缺失文档的处理如下：没有有效输入包时按下条区分缺登记和缺实体，两种情况均判失败；没有报告时，#1403 按受验对象缺失输出 `verdict="FAIL"` 的回执；没有回执时不存在 `verdict="PASS"` 的 `at18-verification/1`，本节末段关票门不成立。引导成功后，才适用「受验对象缺失、不可读或形状不合法时仍输出 12 键 `verdict="FAIL"` 回执」。
- **输入包登记与实体分开核验**。#1391 报告的 `tb_summaries[TB-11].input_bundle` 和 #1403 回执的 `input_bundle_ref` 都从 #1391 清单取值。清单不可读、结构无效，或未合法登记输入包时，凡通过自身引导的报告或回执，该引用均填 `null`。#1391 清单本身须可读、可规范化、通过 `deliveryManifestSchema` 且 `ticket=1391`；不以整份交付的预检结果替代登记判断。合法登记指：该清单的 `reports` 中恰有一条文件名为 `at18-input-bundle.json` 的记录，该条 `storage="external"`、版本与该清单完全一致、路径以仓外根目录为界且声明合法（`.sandcastle/delivery-bundle.ts:184-207, :211-225`；不以能否读到实体决定登记是否合法）。有合法登记即从该条照录 `ArtifactRef`（含登记的 `sha256`），即使实体缺失、不可读、摘要或内容不合也保留同一个引用，不算有效证据。两类失败按第五、第八节记 `FailedCheck`：无合法登记或实体不可定位、不可读、字节摘要不符记 `ARTIFACT_REF`；摘要相符后内容不合按派生步骤码、`SCHEMA` 或实际失败规则报错。读取/校验输入包的字段指针固定为报告的 `/tb_summaries/10/input_bundle`、回执的 `/input_bundle_ref`；R01 锚诊断另用固定的输入源作用域。两种情况均使 TB-11 前置为假、报告与回执判 FAIL；#1391 自身清单不可读或结构无效时仍不满足上一条的引导前提。
- **派生值**。由另一份产物计算得出的字段，只在计算链每一步都对该产物现有字节成功、且未作任何修复时取计算值；任一步失败时取该字段的缺失值，写一项 `FailedCheck`（`check_id` 为失败步骤 `FILE_READ`、`JSON_PARSE`、`JCS_CANONICALIZE` 或 `SCHEMA`，`scope` 按第八节取读取该源的字段指针，`detail=check_id`），所在记录取失败值。四步依次为：读取文件（`storage="in_repo"` 时读取 `commit` 上的 Git blob）；严格解析为 JSON 对象（RFC 8259 语法、合法 UTF-8、无重复键、顶层为对象，不以后出现的重复键覆盖前者）；按 RFC 8785 规范化（`1e400` 等非有限数值与 `"\ud800"` 等孤立代理码点在此步失败，不得用 `JSON.stringify` 把非有限数值写成 `null` 或保留坏码点冒充成功）；按所属 schema 校验。各派生字段只走自己需要的步骤：文件字节摘要（`ArtifactRef.sha256`、`ManifestRef.manifest_sha256`、`VenuePermissionFact.sha256`、`CapabilityTuple` 的两个 `sha256`、`SpecCoverageLedger.crosswalk_sha256`）只需读取（输入包引用的 `sha256` 按上条照录，实际字节摘要只用于校验）；`report_content_hash` 需读取、解析与规范化，不经 schema，故 schema 不合法但能规范化的报告保留重算值；`report_manifest`、照录自它的 `report_ref`、上条两处照录的输入包引用，以及 `external_manifests[]` 各项需全部四步（schema 为 `deliveryManifestSchema`）；`spec_coverage` 的 `stories`、`families`、`details`（含项数、顺序与 `entry_mode`）、`CapabilityTuple.capability_record_version`、`VenuePermissionFact` 的 `source_url` 与 `retrieved_at`、`PostGateChongRecord` 的三个时间戳需读取、解析与所用字段的校验。缺失值按声明类型取：可空字段填 `null`，数组填 `[]`；`ArtifactRef`、`ManifestRef`、`CapabilityTuple` 或 `VenuePermissionFact` 的任一字段算不出时整条不写，所在可空字段填 `null`，所在数组不列该项；可变长数组的元素有类型不含 `null` 的字段取不到时，不列该元素（如从未观测到状态的 `ReviewRef`）。`at18-input-bundle/1` 的 `spec_ref`、`crosswalk_ref`、`coverage_input_ref`、`registry_ref`、`pregate_review_ref` 与必需切片账引用不可为 `null`，且须有独立核实的 R01 `window_anchor`；任一取不到时按「形状规则与判定规则分层」不生成输入包；这是判定失败，不是引导失败，不出 `BLOCKED`。文档自身的 `content_hash` 不是派生值，由「引导前提与无文档结果」第（3）步约束。
- **`origin/main` 祖先提交一致性**。正式通过报告顶层 `head` 必须等于对账时的实际 `origin/main` SHA；报告内全部 `destinations[].main_sha`、`destinations[].commits[]`、`tb_summaries[].main_sha`（非 `null` 时）与 `ArtifactRef.commit`（`storage="in_repo"` 时）均必须为顶层 `head` 在 `origin/main` 上的可达祖先提交（`git merge-base --is-ancestor` 为真），否则判 `"FAIL"`。`ArtifactRef.head`（`storage="external"` 时）取自上游仓外 delivery manifest 的 `head`（是否命中该 manifest 按 `ArtifactRef` 规则核验），预检要求该 `head` 等于交付工作区的 `HEAD`（`.sandcastle/delivery-bundle.ts:147`），即合入前的交付分支头；squash 交付可能无祖先关系；同树 merge 见 `.sandcastle/deepagents-pilot/pilot1742/review_sweep.py:276-279`。`ArtifactRef.head` 因此必须满足以下两项之一，否则判 `"FAIL"`：（a）它是顶层 `head` 的可达祖先提交；（b）GitHub 记录存在已合入 `main` 的 PR（`merged=true` 且 `base.ref="main"`），其 `head.sha` 等于 `ArtifactRef.head`，且其 `merge_commit_sha` 是顶层 `head` 的可达祖先提交。本项不用于 R09 的审查等价或 R06/R08 的 CI。该 PR 归属 `ArtifactRef.ticket` 的依据是对应 `ManifestRef` 已把同一 `ticket` 与 `head` 绑定，不从 PR 标题或正文推断；本条的祖先补证 PR 按 `head.sha` 查得，不为它额外写入报告；R09 所选 PR 仍按 `ReviewRef` 记录。（b）项只证明该 `head` 已合入 `main`，不证明 GitHub 把该 PR 记在 `ArtifactRef.ticket` 名下；票归属只取 `ManifestRef` 的绑定声明，由该票自身按第三节关票通用门完成的交付验收认可，#1391 与 #1403 均不得把（b）项成立当作票归属已核实。#1403 独立复核本规则，（b）项须自行向 GitHub 查询，不采信报告结论。

共用子记录封闭类型定义如下（`Sha256Hex` 为匹配 `^[0-9a-f]{64}$` 的字符串，`GitCommitSha` 为匹配 `^[0-9a-f]{40}$` 的字符串，`UtcTimestamp` 为 RFC 3339 UTC 时间字符串，`EvidenceClass` 为 `"simulation" | "experiment" | "production"`，`CiConclusion` 为 `"SUCCESS" | "FAILURE" | "CANCELLED" | "TIMED_OUT" | "ACTION_REQUIRED" | "NEUTRAL" | "SKIPPED" | "STALE"`）：

- `ManifestRef`（5 键）：`{ticket: integer, base: GitCommitSha, head: GitCommitSha, manifest_path: string, manifest_sha256: Sha256Hex}`。`ticket` 为正整数；`manifest_path` 为 checkout 外、无 `..` 的绝对路径。PASS 要求 `manifest_path` 无符号链接、文件可读且字节摘要等于 `manifest_sha256`，内容通过 `.sandcastle/delivery-bundle.ts` 的 `deliveryManifestSchema` 校验且内部 `ticket`、`base`、`head` 与本引用完全一致；任一不满足时，该 manifest 登记的引用不计为证据，在 `failed_checks[]` 写明并判 `"FAIL"`。
- `ArtifactRef`（8 键）：`{storage: "in_repo" | "external", path: string, sha256: Sha256Hex, commit: GitCommitSha | null, ticket: integer | null, base: GitCommitSha | null, head: GitCommitSha | null, bounded_scope: string}`。`storage="in_repo"` 用于仓内规范文件与 ADR 0058 既有仓内报告，`path` 为不含 `..` 的仓内相对路径，`commit` 必填 `GitCommitSha`，`ticket`、`base`、`head` 固定为 `null`；`storage="external"` 用于仓外持久证据（`.sandcastle/CODEX-CHILD.md:61`；`.sandcastle/delivery-bundle.ts:11-16`），`path` 为仓外持久证据目录下无 `..` 的绝对路径，`commit` 固定为 `null`，`ticket`（正整数）、`base`、`head` 均必填非 `null`。PASS 要求：`storage="in_repo"` 的 `commit` 在 `origin/main` 上且 Git blob 摘要等于 `sha256`；`storage="external"` 的 `path` 无符号链接，并在对应 delivery manifest 的 `reports` 中有唯一、完全匹配的 `{storage: "external", path, sha256, ticket, base, head}` 条目，且落盘文件可读、字节摘要等于 `sha256`。上游仓外清单由输入包的 `external_manifests[]` 绑定。#1391 对本轮封印原件与已先登记的输入包直接核本票清单，不从 #1403 回执取清单。#1403 从封包后的该 #1391 清单核本轮封印原件、输入包及报告，回执的 `report_manifest` 绑定此时的清单字节。预登记输入包与封包后核验使用同一清单身份（路径、票、base、head）及同一输入包登记项；追加报告项会改变清单字节，不改变报告内输入包引用。任一缺失、不可读、未命中 manifest 或摘要不符时，该引用不计为证据，在 `failed_checks[]` 写明并判 `"FAIL"`，禁止跨存储方式回退。报告中缺失的必需证据按所在字段的规则填 `null` 或 `[]`，不写占位引用；`at18-verification/1` 的受验引用另按其定义处理。
- `EvidenceByClass`（3 键）：`{simulation: ArtifactRef[], experiment: ArtifactRef[], production: ArtifactRef[] | null}`。已启用证据类槽位必填 `ArtifactRef[]`（无条目填 `[]`，不得填 `null`）；未启用部署槽位（#1561 下的 `production`）必填 `null`（不得填 `[]` 或非空数组）；`production` 经独立授权启用后同样必填 `ArtifactRef[]`。
- `CapabilityTuple`（3 键）：`{capability_record_version: string, capability_record_sha256: Sha256Hex, venue_profile_sha256: Sha256Hex}`（ADR 0062:258）。
- `VenuePermissionFact`（3 键）：`{source_url: string, retrieved_at: string, sha256: Sha256Hex}`（ADR 0062:51-79）。
- `PermissionSlot`（4 键）：`{authorization_declaration: ArtifactRef | null, venue_permission_fact: VenuePermissionFact | null, runtime_verification: ArtifactRef | null, capability_hash: CapabilityTuple | null}`。已启用场所槽位的前三个字段依次记第二节第 2 条的（a）授权声明、（b）场所权限事实与（c）运行时核验，`capability_hash` 记能力 hash 三元组。某层证据缺失时该字段填 `null`；能力记录或场所 profile 缺失、三元组任一元素无可读来源时 `capability_hash` 填 `null`；不得以占位引用、不可读引用或他层证据代填。任一字段为 `null` 时 Destination ⑤ 的 `result` 必须为 `"FAIL"`，`failed_checks[]` 须为每个 `null` 字段写入一项（`scope` 固定为对应字段的 RFC 6901 指针 `/destinations/4/permission_evidence/<experiment 或 production>/<字段名>`，`detail=check_id`），`overall_result` 随之为 `"FAIL"`。整个槽位填 `null` 只表示该场所槽位未启用。
- `ReviewRef`（9 键）：`{pr: integer, merged_at: UtcTimestamp, reviewed_head: GitCommitSha, merge_commit: GitCommitSha, status_id: integer, created_at: UtcTimestamp, updated_at: UtcTimestamp, creator: string, state: "success"|"failure"|"pending"|"error"}`。只从 R09 取实际 PR 及合入截止点选中的状态；状态出处用 `status_id` 从 R09 验证的 H 截止快照及其原件读取，不写状态描述或沿用证明的副本，不伪造缺失项。
- `CiRunRef`：`{workflow: string, run_id: integer, run_attempt: integer, head_sha: GitCommitSha, conclusion: CiConclusion | null, url: string}`；只记 R08 选中的实际运行及服务端原结论，未完成时结论填 null。通用 CI 的验收结论单独由 R08 必需作业求值。
- `TicketScopeRef`（2 键）：`{ticket: integer, scope: string}`（`ticket` 为正整数，下同）。
- `SliceStatusRef`：`{ticket: integer, state: TicketState, state_reason: string | null}`；`TicketState = "OPEN" | "CLOSED" | null`（查不到填 null）。
- `DownstreamStatusRef`：`{ticket: integer, state: TicketState}`。
- `MigrationSlot`（5 键）：`{no_lost_rights: boolean, no_duplicated_capital: boolean, no_dual_write: boolean, no_resend: boolean, non_empty_evidence_refs: ArtifactRef[]}`（ADR 0063:120）。四项布尔值记对应不变量是否已由非空运行证据证实成立。已启用部署槽位缺非空运行证据时，未证实的布尔值填 `false`，`non_empty_evidence_refs` 填 `[]`（字段名表示通过条件，不是形状约束），并在 `failed_checks[]` 写明、使 `overall_result` 为 `"FAIL"`。
- `PostGateSlot`（2 键）：`{status: PostGateStatus | "MIXED", chong_records: PostGateChongRecord[]}`。启用槽的记录须逐一对应 R07 从原件独立枚举的受测重全集（非空）；以 `chong_id` 为键，按 UTF-8 字节字典序升序，身份不重复。全集不全、空、无法证实，或任一重未知、缺证、越权、互引或时序违规，槽汇总 `status="UNKNOWN"`，并按 R07 留红；保留可观察的逐重记录，不用其他重补证。全体记录有效且状态相同时取共同状态；全体有效而状态不同时取 `"MIXED"`。两种启用历史态（当前启用、已回退）均属「曾启用」；其余四种可判定状态均属「从未启用」。是否有曾启用重、哪些重可延期，均从逐重记录求集合，不从 `MIXED` 或槽汇总状态猜。
- `PostGateStatus = "UNKNOWN" | "NOT_TRIGGERED" | "CANDIDATE_ONLY" | "TRIGGERED_AWAITING_POLICY" | "TRIGGERED_VERSION_AUTHORIZED" | "TRIGGERED_AND_ENABLED" | "TRIGGERED_ENABLED_THEN_REVERTED"`。`PostGateChongRecord`（11 键）：`{chong_id: string, status: PostGateStatus, gate_reached_event: ArtifactRef | null, gate_reached_candidates: ArtifactRef[], parameter_version: ArtifactRef | null, first_activation: ArtifactRef | null, gate_reached_known_at: UtcTimestamp | null, version_authorized_at: UtcTimestamp | null, first_activation_known_at: UtcTimestamp | null, non_activation_evidence: ArtifactRef[], rollback_evidence: ArtifactRef[]}`。候选数组保留该重所有实际候选原件（含正式触达之前的候选）；三记录依次指 `gate_reached_event`、`parameter_version` 和 `first_activation`，与各自时间戳同有同无才可通过。三时间戳只取其对应原件，不用候选、回退或重新启用时刻替代。
   - 两种启用历史态：三条记录及三个时间戳均非 `null`，严格递增且与同一重互引；`non_activation_evidence=[]`。`rollback_evidence` 保留该重每次实际回退的 R07 封印原件，无回退才填 `[]`。按完整状态转换链判当前状态：最后一次转换是合法启用、能力或后闸参数当前生效，取 `TRIGGERED_AND_ENABLED`；最后一次转换是已执行的合法回退且当前不生效，取 `TRIGGERED_ENABLED_THEN_REVERTED`（`rollback_evidence` 必须非空）。若原件显示回退后重新启用，须另核所用版本、有效授权及实际再次启用，不能用首次启用记录补证此次转换。
   - `TRIGGERED_VERSION_AUTHORIZED`：前两条记录及时间戳非 `null`、严格递增且互引；首次启用及其时间戳为 `null`；`non_activation_evidence` 非空且证明尚未启用。
   - `TRIGGERED_AWAITING_POLICY`：仅正式触达记录及其时间戳非 `null`；`non_activation_evidence` 非空且证明无适用授权版本、输出仍待策略、阶段能力未启用。
   - `CANDIDATE_ONLY`：候选数组非空，三条正式记录及三个时间戳均为 `null`；`non_activation_evidence` 非空，须包含独立的门槛未满足事实和未切换、未启用后闸参数的证据，按第二节第 4 条核实。
   - `NOT_TRIGGERED`：候选数组为空、三条正式记录及三个时间戳均为 `null`；`non_activation_evidence` 非空，并证明资格谓词始终未为真、既无候选也无正式事件且未启用。
   - 四种从未启用态同时要求 `rollback_evidence=[]`，且 `non_activation_evidence` 绑定 R07 从可验证创世态连续至当前的未启用历史；恢复或迁入前的持久历史也须纳入，不能以本轮无新事件代替。历史缺段而不能证明开跑前未启用时，逐重状态填 `UNKNOWN`，不准单重或整域延期。观察到与原件矛盾的启用声明不能作为未启用证据。以上为判定规则；失败时保留实际可读值，缺记录、时间戳填 `null`，缺证据数组填 `[]`，不填占位引用。非空且用于通过的 `parameter_version` 只取第二节第 4 条规定的首次启用时适用授权（从未启用但已授权时取该适用版本）。任一判定失败按 R07 写 `failed_checks[]`，且 `overall_result="FAIL"`。
- `StoryCoverageEntry`（6 键）：`{story_id: string, closure_slice_ids: string[], destination_ids: string[], evidence_refs: ArtifactRef[], deferred_gates: string[], status: "VERIFIED" | "BOUNDED_DEFERRED" | "PENDING_REPORT_VERIFICATION" | "FAIL"}`。`PENDING_REPORT_VERIFICATION` 只用于 R12 的 `US-ENG-10`，不表示合法延期或最终核销。
- `FamilyCoverageEntry`（6 键）：`{family: string, id: string, entry_mode: "REQUIRED" | "OUT_OF_SCOPE_PRESERVE", evidence_refs: ArtifactRef[], deferred_gates: string[], status: "VERIFIED" | "PRESERVED_BOUNDARY" | "BOUNDED_DEFERRED" | "FAIL"}`。
- `DetailCoverageEntry`（5 键）：`{id: string, family_entry_id: string, evidence_refs: ArtifactRef[], deferred_gates: string[], status: "VERIFIED" | "BOUNDED_DEFERRED" | "FAIL"}`。
- `SpecCoverageLedger`（4 键）：`{crosswalk_sha256: Sha256Hex | null, stories: StoryCoverageEntry[], families: FamilyCoverageEntry[], details: DetailCoverageEntry[]}`。成功须按 R02 原行顺序逐条对应 97/345/496；不可读时摘要为 null、数组为 [] 并 FAIL。family 的 `entry_mode` 只由对应 crosswalk 的 `exclusion_boundary=true` 判定：真为 `OUT_OF_SCOPE_PRESERVE`，否则 `REQUIRED`；当前仅 OE41/OE45 是边界。OE42 仍核 coverage input 的 `source_json_pointer` 指向的 `effective_disposition.kind="OUT_OF_SCOPE_PRESERVE"`（`.chanlun/review-results/issue1340-publication-20260909/view/inputs/TB07-11-EXECUTION-SLICES.md:278`），不得改为边界项。条目状态按 R12；通过的非 TB-11 键投影与输入包 `registry_ref` 完全相等的引用；仅非 `FAIL` 的 TB-11 键投影与该 TB 的 `input_bundle` 完全相等的引用。混合条目按第八节取适用引用；`US-ENG-10` 为 `FAIL` 时 `evidence_refs=[]`。所有已通过的具名延期以唯一字符串连接 `unexecuted[]`。
- `FailedCheck`（4 键）：`{scope: string, check_id: string, detail: string, evidence_ref: ArtifactRef | null}`。
- `DestinationGate`（3 键）：`{gate_id:string, decision_refs:ArtifactRef[], result:"PASS"|"FAIL"}`。身份、有效裁定原件与结果按 R02、R13 独立求得；通过必须有非空且齐全的裁定原件引用。FAIL 保留已核实的引用，缺证填 `[]`，不得用占位引用。每个具名门与故事／family／细项覆盖分别记账。

`at18-input-bundle/1` 顶层 14 键：`{schema_version: "at18-input-bundle/1", content_hash: Sha256Hex, ticket: integer, base: GitCommitSha, head: GitCommitSha, generated_at: UtcTimestamp, window_anchor: WindowAnchor, spec_ref: ArtifactRef, crosswalk_ref: ArtifactRef, coverage_input_ref: ArtifactRef, registry_ref: ArtifactRef, pregate_review_ref: ArtifactRef, slice_ledger_refs: ArtifactRef[], external_manifests: ManifestRef[]}`。身份取本票 manifest；#1391 票号固定为 1391。`WindowAnchor` 封闭 3 键 `{status_id: integer, created_at: UtcTimestamp, ledger_commit: GitCommitSha}`：只登记 R01 实时核实的开窗状态正整数 ID、服务端 UTC 创建时刻 W0 原串及对应账本 `open_bind` 所在提交的完整 SHA。以输入包 `head=F` 的完整提交 SHA 查询本仓状态；`window_anchor.ledger_commit` 必须是当前受保护且逐笔验签的账本创世后链上、该 F 当前有效窗的 `open_bind` 提交。W0 必须严格早于输入包与报告各自的 `generated_at`。缺合法锚不生成输入包。规范三件分别为 `.chanlun/review-results/issue1339-r2-spec-20260909/payload/spec/` 下 `SPEC.json`、`IMPLEMENTATION-CROSSWALK.json`、`inputs/SPEC-COVERAGE-INPUT.json`；登记册和 PRE 路径见 R03。切片账按 `TB01-EXECUTION-SLICES.json`、`TB02-06-EXECUTION-SLICES.json`、`TB07-11-EXECUTION-SLICES.json`、`TB01-PARENT-CONTRIBUTION.json` 顺序，均在 `.chanlun/review-results/issue1340-publication-20260909/payload/inputs/`。上述九份 Git 文件以 `in_repo`、`commit=head` 读取（规范三件、登记册、PRE 与四份切片账）。缺任一所需文件、非法引用、无合法摘要，或 R02 的规范三件校验失败，则没有有效输入包；`external_manifests` 仅列报告引用的上游仓外清单（不含 #1391 自身清单），无重复，按票号与路径排序。

F 上两份登记原件的封闭合同（签名不新增）：

- `at18-registry/1 = {schema_version, crosswalk_sha256: Sha256Hex, adapter_contract_sha256: Sha256Hex, experiment_profile_id: string|null, checks: Check[], bindings: Binding[], pregate: {census_sha256: Sha256Hex, landings: Landing[]}}`；`schema_version` 固定为 `"at18-registry/1"`，骨架的 profile 可 null，正式通过须有有效 P1 profile；`adapter_contract_sha256` 按 R03 绑定 F 上的规范适配器数据合同。R10 清册由 #2132 在 .chanlun/ 下的 `at18` 目录交付，清册入口文件名为 `landing-census.json`；`census_sha256` 须等于 F 上该入口文件字节摘要，入口只含 `schema_version="at18-landing-census/1"`、`p0`、`sources:{role,path,sha256}[]`、`attributions:ScopeAttribution[]` 四键，`p0` 固定为 R09 的 P0。`role` 按 `history,relations,signals,adjudication` 各恰一份；路径均指向 F 的获审原件、逐份核其字节摘要，未知或重复角色失败。实际落地与留存结果从这些原件及 Git 重算，而非以清册自报结果替代。
- `Check = {check_id:string, group:string, evidence_class:EvidenceClass, profile_id:string|null, runner:"cargo-test"|"node-test"|"pytest"|"command", selector:string, expected_count:integer, key_aware:boolean, source:{path:string,sha256:Sha256Hex}, record:string|null}`。`check_id` 唯一，组、profile 和 ID 使用 ASCII 字母/数字/点/下划线/连字符的非空单词；`none` 保留作空 profile 编码，不得作为实际 profile ID。record 只接受 R07 具名槽；`selector` 是 runner 的受审选择器，不拼成 shell 或从 dispatch 传入。
- `Binding = {binding_id:string, slice_id:string, basis:{path:string,sha256:Sha256Hex,pointer:string}, keys:{kind:"story"|"family"|"detail",id:string}[], domains:Domain[]}`；`binding_id` 唯一，keys 非空无重复。`Domain = {evidence_class:EvidenceClass,profile_id:string|null,result:"VERIFIED"|"PRESERVED_BOUNDARY"|"BOUNDED_DEFERRED",deferred_gate:string|null,checks:string[]}`；checks 无重复，检查和域必须有实际引用关系；专用或历史 cure 检查可由 R07/R11 引用。
- `Landing = {ticket:integer,commits:GitCommitSha[],attribution_scopes:LandingScope[],cure_checks:{commit:GitCommitSha,run_id:integer|null,run_attempt:integer|null,kind:"test"|"step",target:string,check_id:string}[]}`。`LandingScope` 仅为 `TB-01..TB-10` 或 `GRAPH`；`attribution_scopes` 非空、按 ASCII 升序去重，`GRAPH` 不与 TB 混用。清册 `ScopeAttribution = {ticket:integer,attribution_scopes:LandingScope[],sources:string[]}`，只登记非原生归属（可为已有原生 TB 增补其他 TB）；按票号唯一升序，`sources` 为证明每项归属的非空出处定位串集合，按 UTF-8 字节升序去重，核查时不得从说明文字推断作用域。生成及核验按 R10。`cure_checks` 的 `run_id`、`run_attempt` 对实际失败尝试均为正整数，固定锁两者均为 `null`。同一锁可对应多次失败，每次须各自有登记关联；相同的 F 检查结果可复用，失败尝试行不得合并。测试类型 cure 锁须用 selector 唯一命中所指具名测试（允许引擎完整路径，末段同名且唯一），实跑 1 次；步骤类型 cure 按 R11 定位失败步骤并复跑同一步骤、同一失败条件；警告或拒绝不算。R11 中同票同提交的具名锁不可删。
- `at18-pregate-review/1`（3 键）：`{schema_version:"at18-pregate-review/1",owner_ticket:integer,rows:{path:string,blob:GitCommitSha,mode:"100644"|"100755"|"120000",verdict:"PASS"|"BLOCK"}[]}`。每行 4 键，按 `(path,mode,blob)` 的字节序升序且唯一，允许同一原路径有多个不同的历史对象。path 是 R10 的历史来源相对路径，不写 F 上的改名目标；blob 用 Git SHA-1 的格式，语义为 blob 对象，不是提交。F 上的全部存活路径与正文复审证据按 R10 独立对账，不用行内 `verdict` 代替。

工作流与历史观测类型：`WorkflowRun = {workflow:string,run_id:integer|null,run_attempt:integer|null}`；`AcceptanceJob = {workflow:string,run_id:integer,run_attempt:integer,head_sha:GitCommitSha,job:string,conclusion:CiConclusion|null}`；`HistoricalDeviation`（6 键）：`{ticket:integer,commit:GitCommitSha,workflow:string,run_id:integer|null,run_attempt:integer|null,observed:CiConclusion|"NO_RUN"|"INCOMPLETE"|"UNKNOWN"}`。`HistoricalDeviation` 按 R11 只记录报告分母内每个非成功尝试或确证零运行；除 `observed="NO_RUN"` 的两个 id 均为 `null` 外，`run_id`、`run_attempt` 均为正整数。工作流用仓内路径；服务端结论转大写，已识别为尚未完成的历史运行记 INCOMPLETE，未知结论记 UNKNOWN（同时报来源失败），不得翻成 PASS。当前轮未知结论在对应作业记录填 null 并失败。正整数用于所有票、run、attempt、测试数与 PR/status id。

`at18-report/1` 顶层封闭字段集合固定为以下 22 键：

- `schema_version`（固定 `"at18-report/1"`）、`content_hash`（`Sha256Hex`）、`ticket`（正整数，正式整图报告固定为 `1391`，须与绑定本报告的 #1391 仓外 delivery manifest 的 `ticket` 完全一致）、`base`（`GitCommitSha`，须与该 manifest 的 `base` 完全一致）、`head`（`GitCommitSha`，须与该 manifest 的 `head` 完全一致；PASS 要求它等于 `at18-input-bundle/1.head` 与对账时的实际 `origin/main` SHA，候选分支不得冒充 `origin/main`；输入包缺失或其 `head` 与本报告 `head` 不等时，本报告 `head` 仍取自该 manifest，在 `failed_checks[]` 写明并判 `"FAIL"`）、`generated_at`（`UtcTimestamp`）；
- `capability_hash`：`{experiment: CapabilityTuple | null, production: CapabilityTuple | null}`；已启用场所槽位填 `CapabilityTuple`（该槽位 Destination ⑤ 的 `capability_hash` 因能力记录缺失填 `null` 时同填 `null`，按 `PermissionSlot` 规则判 `"FAIL"`），未启用槽位填 `null`，且须与 `destinations[]` 第 5 项（`id=5`）`permission_evidence` 对应槽位的 `capability_hash` 逐槽完全相等，不等即判 `"FAIL"`；
- 恰好 6 项、按 `id` `1..6` 升序排列的 `destinations[]`：每项固定 13 键 `{id: integer, obligation: string, tickets: TicketScopeRef[], commits: GitCommitSha[], independent_reviews: ReviewRef[], main_sha: GitCommitSha | null, ci_runs: CiRunRef[], evidence_by_class: EvidenceByClass, permission_evidence: {experiment: PermissionSlot | null, production: PermissionSlot | null} | null, downstream_status: DownstreamStatusRef[], success_gates: DestinationGate[], remaining_obligations: string[], result: "PASS" | "FAIL"}`；仅 `id=5` 的 `permission_evidence` 为非 `null` 分槽对象（已启用场所槽位填 `PermissionSlot`，缺失的证据层与能力 hash 按 `PermissionSlot` 规则在槽内填 `null`；未启用槽位填 `null`），其余 5 项固定填 `null`；可确认的报告主线填 F，否则填 null 并 FAIL。commits 只列 F 与第八节由 R10 得到的适用历史出处（去重），不把出处当行为证明；independent_reviews 由 R09 复算；ci_runs 仅取 R08。`success_gates[]` 按 `gate_id` 升序；通过时与 R02 的 `success_gate_ids` 精确一一对应且全部 PASS（当前每项 13 行）。分母源失败而不可核定时本字段填 `[]`，该 DST 与整图 FAIL；分母可证而裁定缺失仍逐门填 FAIL 行。
- 恰好 11 项、按 `"TB-01".."TB-11"` 排列的 `tb_summaries[]`：每项固定 12 键 `{tb_id: string, ticket: integer, slices: SliceStatusRef[], input_bundle: ArtifactRef | null, evidence_by_class: EvidenceByClass, final_reviews: ReviewRef[], main_sha: GitCommitSha | null, ci_runs: CiRunRef[], entity_reports: ArtifactRef[], remaining_obligations: string[], ticket_state: TicketState, gate_satisfied: boolean}`；`TB-01..TB-10` 的 `input_bundle` 固定填 `null`，`entity_reports` 列出R07 封印的本轮实体报告（无则填 `[]` 并记 `gate_satisfied=false`），`TB-11` 的 `entity_reports` 固定填 `[]`，`input_bundle` 按本节登记规则照录；只有清单登记、实体及 R01 锚均通过才满足 R12 的输入包条件，否则 `gate_satisfied=false`、留诊断且整图判 `"FAIL"`；TB 的 main_sha、适用 CI 与审查取 R08–R10（闸前复审以 PRE 在第一父链的登记合入指向 R09 记录）；不编造切片主线 SHA。
- `spec_coverage`：`SpecCoverageLedger`（覆盖全部 97 故事、345 family 条目与 496 细项对账）；
- `evidence_by_kind`：封闭 4 键 `{program: EvidenceByClass, proof: EvidenceByClass, ui: EvidenceByClass, venue: EvidenceByClass}`，按 R12 分列程序、证明、UI、场所的实际证据。每类均显式列 `simulation`、`experiment`、`production`，无证据的已启用槽填 `[]`，本版唯一未启用的 production 边界填 `null`。
- `migration_invariants`：`{experiment: MigrationSlot | null, production: MigrationSlot | null}`，已启用部署槽位填 `MigrationSlot`，未启用槽位填 `null`；
- `post_gate_records`：`{experiment: PostGateSlot | null, production: PostGateSlot | null}`，已启用部署槽位填 `PostGateSlot`（含按 `chong_id` 排序的 `chong_records`），未启用槽位填 `null`；
- 恰好 7 项、按 `[942, 1096, 1282, 1304, 1319, 1320, 1279]` 顺序排列的 `legacy_dispositions[]`：每项固定 6 键 `{ticket: integer, disposition: string, evidence_refs: ArtifactRef[], ticket_state: TicketState, remaining_obligations: string[], disposition_valid: boolean}`；
- `unexecuted[]`：元素类型为 5 键 `{obligation: string, reason: string, blocker_or_gap: string, evidence_class: EvidenceClass, required: boolean}`；`obligation` 在 `unexecuted[]` 内不得重复，`deferred_gates` 按 `obligation` 逐字节相等连接到条目。本 ADR 要求的具名条目固定使用以下四个 `obligation` 常量，四种的 `required` 均为 `false`：`ISSUE_1561_P2_FIRST_SEND`（#1561 下「生产首次新发送前」具名门，`evidence_class="production"`，`production` 部署槽位未启用时必列）、`ADR_0036_POST_GATE_PRODUCTION` 与 `ADR_0036_POST_GATE_EXPERIMENT`（ADR 0036 闸门后三记录门，`evidence_class` 分别为 `"production"` 与 `"experiment"`，`post_gate_records` 的对应槽位经核实未启用而为 `null`，或槽有效且逐重集合中至少一重合法从未启用时必列；只覆盖这些重。已回退不算未启用，`UNKNOWN` 不能产生合法延期；是否允许整域延期另按 R04/R07）、`ISSUE_1320_HEAVY_MEASUREMENT`（第四节 #1320 单列重型测量，`evidence_class="simulation"`，即 CONTEXT.md:374 的确定性回放，该测量未实际完成且无合法废弃裁定时必列）；
- `failed_checks[]`（元素类型为 `FailedCheck`）、`permission_blocked[]`（记录受权限阻塞的本图必需成功项，元素类型为 4 键 `{obligation: string, missing_authorization: string, blocker_ticket: integer, evidence_class: EvidenceClass}`）、`bounded_domain_statement`（非空字符串）；
- `workflow_runs[]`：四项按 ci.yml、devskim.yml、at18-acceptance.yml、at18-experiment.yml 固定顺序；只引用 R06/R08 所选的本轮运行，窗口锚通过 TB-11 的 `input_bundle` 引用绑定；缺 run 时两个 id 均为 null。`acceptance_jobs[]`：R06–R08 取证所用实例与封印作业（含已看到的失败行）。`historical_deviations[]`：R11 的全部偏差。可变数组按工作流路径、run/attempt、作业名或票号、提交、工作流路径、run id、run attempt 排序（null 在先），不得用摘要替代明细。
- `bounded_domain_statement` 除第二、四节要求外，固定逐行包含 `AT18_LANDING_CI_NOT_CERTIFIED n=<historical_deviations 项数>`、`AT18_PREGATE_REVIEWER_VOUCHED_BY_TICKET 2132`、`AT18_CHECK_SUFFICIENCY_BY_FORMAL_GATE`。第二行说明身份担保方法，不表示 #2132 已关；完整文本按第八节唯一投影。
- `overall_result`：`"PASS" | "FAIL"`。

`overall_result="PASS"` 只在报告生成阶段适用的 R01–R13 均满足、各引用按本节可复核、六项 Destination 全 PASS、十一项 TB 门全 true、覆盖条目无 FAIL 且 `US-ENG-10` 为待实际报告复验的 `PENDING_REPORT_VERIFICATION`、七张旧票 `disposition_valid=true`，且 `failed_checks=[]`、`permission_blocked=[]`、`unexecuted` 无重复且无 `required=true` 时成立。历史偏差非空本身不阻断，也不掩盖 `DEVIATION_NOT_CURED`。R14 定义所有判定失败的合法写法。

`at18-verification/1` 顶层 12 键：`{schema_version:"at18-verification/1",content_hash:Sha256Hex,ticket:integer,base:GitCommitSha,head:GitCommitSha,verified_at:UtcTimestamp,report_manifest:ManifestRef|null,report_ref:ArtifactRef|null,report_content_hash:Sha256Hex|null,input_bundle_ref:ArtifactRef|null,failed_checks:FailedCheck[],verdict:"PASS"|"FAIL"}`。ticket 固定为 1403；身份从自身 manifest 取，受验引用和缺失值按本节登记与引导条文处理。有合法输入包登记但实体不合时仍保留 `input_bundle_ref` 并判 FAIL。#1403 用通过实体校验的输入包的 `window_anchor` 三字段比对独立从当前账本全链、GitHub Commit Status 及全体受约束票的状态时间线重算的 R01 开窗锚；回执用 `input_bundle_ref` 绑定该锚，不另设字段。#1403 从同一 F、GitHub 与两票仓外清单及登记实体独立重算 R01–R14、摘要、引用、祖先及作用域。PASS 要求 `input_bundle_ref` 与报告 `tb_summaries[TB-11].input_bundle` 完全相同，且同一份 #1391 清单同时命中 `input_bundle_ref` 与 `report_ref`；按第八节重算报告的全部字段（生成时刻独立验时，再用于重算摘要），时间须合法 UTC、落在本轮并晚于所引用运行。资源在 #1391 封包后会多出输入包、报告登记和两票状态变化，仅按第三节已声明的阶段快照解释，不用新票态改写原报告。只有 #1391 封包关票且其封包预检门可独立证实、两个 manifest 与实体校验通过、比较无差异、实际报告的四类证据按 R12 复验通过、受验报告 `overall_result="PASS"` 且本回执 `failed_checks=[]` 才记 PASS。受验物摘要不符仍输出 FAIL 回执。

**封包预检门。** #1391 与 #1403 各在本票最终 manifest 登记齐备后、关票前执行预检；在可信封包收据中固定预检输入、原始 JSON 输出与退出码：`DeliveryPreflightProof`（3 键）为 `{manifest_sha256:Sha256Hex,result_sha256:Sha256Hex,exit_code:integer}`；两个摘要分别绑定实际读取的最终清单与原始 JSON 字节，JSON 的票、base、head 须与该清单一致。收据、JSON 及批准原件在清单外固定，由关票记录定位。退出码 `0` 不是充分条件：现行 CLI 对两个就绪态都返回 `0`（`.sandcastle/delivery-bundle.mts:10-16`）。只接受 `READY_FOR_APPROVAL`（普通就绪、无例外）且无诊断，或 `READY_WITH_EXPLICIT_EXCEPTION`、无诊断且其非空例外集逐项有正式批准原件。现行例外 `SCAN_EXCEPTION_REQUIRES_APPROVAL` 明示尚未批准（`.sandcastle/delivery-bundle.ts:340-345, :358`）。普通扫描例外由主控按 #1909 正式裁定流程取得非作者独审 PASS，并在本票明确批准该例外；若触及现有用户硬门，仍须对应用户签署，预检例外不能豁免硬门。正式批准绑定 `DeliveryExceptionApproval`（6 键）`{ticket:integer,base:GitCommitSha,head:GitCommitSha,manifest_sha256:Sha256Hex,code:string,path:string|null}`（`manifest_sha256` 是受检清单原始字节摘要；`code`、`path` 取该项稳定身份，无 path 填 `null`），并可从批准原件核实该项所指的同清单分诊。每项唯一匹配；重复/不能唯一识别的例外先修预检证据，不能凭文案配对。不得把批准原件追加到已批准的清单字节中；清单变动后重验并重新批准适用例外。仅披露、普通独评 PASS 或对旧清单的批准均不等于该项批准。`BLOCKED`、缺报告、非法/未知状态、非零退出或未批准 / 不匹配例外均不通过。预检不替代最终非作者独评，不授予合入或硬门权限。#1403 从封包原件独立复核 #1391 的门（失败记 `DELIVERY_PREFLIGHT`，`scope=ticket:1391@delivery_preflight`）；#1403 自身的门在回执登记后核，失败则本票不可关，不改写已经生成的回执。

TB-11（#1369）、SPEC #1340 与 #1323 的关票须在 #1391 已生成 `overall_result="PASS"` 的 `at18-report/1`、#1403 对该报告与 `at18-input-bundle/1` 实际运行产出 `verdict="PASS"` 的 `at18-verification/1`（R12 已核销 `US-ENG-10`），且两票的封包预检门、最终非作者独评与关票均成立后执行。关票评论须同时写明 `at18-input-bundle.json`、`at18-report.json`（路径、文件 `sha256`、`content_hash`）与 `at18-verification.json`（路径、文件 `sha256`、`content_hash`、`verdict`）、双方 delivery manifest 路径与 `sha256`、预检收据／报告及适用批准原件的位置、实际 `origin/main` SHA、适用 CI run、最终非作者独评、六项 Destination 证据摘要、程序／证明／UI／场所四类证据与未启用边界、ADR 0036 各槽位的 `PostGateSlot.status` 与对应记录、`unexecuted[]` 明细及七张旧票去向；缺任一实体报告或独立总验未通过时写「无有效总验报告」，不得声明整图通过或关闭 #1369、#1340、#1323。

## 六、从原件计算验收结论

### R01　冻结 F 和原件

生成器 #1391 与总验器 #1403 只消费本仓 Git 对象、GitHub 服务端 API、第五节规定的本票与上游仓外清单及登记实体（#1403 另读封包后的 #1391 清单及第五节明确列出的预检、适用批准与关票原件）、R09 的独立部署引导原件、R09/R11 签章历史证据链与 R09 正式 App 登记及双审回执原件。删去调用方传入的 observations、判定布尔值、状态表与作业结论。两端各自取 GitHub `refs/heads/main` 完整 SHA；在取证开始、输出前及关票前均须等于本轮 `head=F`，并在各时点按下述规则确认同一锚。#1403 另与 #1391 报告记录的四个工作流选择（run id 与 attempt，含无运行）逐项核对。同一 F 上锚或运行选择变化也作废，不拼接窗口。主线前移记 `HEAD_CHANGED`；窗口或来源失败见下文。

**账本保存决定，Commit Status 只证明开窗时刻。** #2131 在交付前建置本仓独立分支 `refs/heads/at18-window-ledger`，以无父、空树的创世提交 `W_GENESIS` 为起点；创世 SHA 和账本签名公钥由 F 上获审的 R03 合同钉住。账本与 `main` 无祖先依赖，追加不移动 F、不占用 F 的状态配额。开窗意图、绑定、作废、退役及冲突都从 Git 全链重算，不随 Actions/状态保留期清理。Git 作者和提交者时钟均不作证；W0 只取 `at18/window` 已绑定状态的服务端 `created_at`，与 R09 的 `deepagents/review` 隔离。

**先核取证时的账本保护。** 两端每次独立核对本仓该分支的生效保护：
- 必须同时覆盖不可绕过的防强推 `non_fast_forward` 和防删除 `deletion`。覆盖集取合格经典保护与生效且零绕过者的 Rulesets 的并集；允许经典保护单独覆盖、Rulesets 单独覆盖或二者各覆盖一部分。下列绕过检查与来源完整性检查独立于覆盖是否齐全。
- 经典保护：读 `GET /repos/{owner}/{repo}/branches/at18-window-ledger/protection` 及 GraphQL `Ref.branchProtectionRule`。只有实际生效、`enforce_admins.enabled=true` 且 `bypassForcePushAllowances.totalCount == 0`（无节点、到完整终页）的规则，才能分别以 `allow_force_pushes.enabled=false` 贡献防强推、以 `allow_deletions.enabled=false` 贡献防删除。已证实无经典保护时贡献空集；已证实经典规则有强推绕过者即拒收。
- Rulesets：无论经典保护是否已覆盖两项，均须完整枚举所有对该分支实际生效（`enforcement="active"`）的目标规则集，包括仓库和继承来源、不施加上述两类禁令的规则集。分页读分支有效规则 `GET /repos/{owner}/{repo}/rules/branches/at18-window-ledger`，与完整的仓库及继承规则集列表、按来源和 `ruleset_id` 读取的明细及分支匹配条件对账，证明目标全集；仓库级列表不代替按分支取证，`evaluate` 不算生效。每个生效目标规则集均须显式 `bypass_actors=[]`，其实际生效禁令才计入覆盖。
- 任一生效目标 Ruleset 有绕过者、经典规则有强推绕过者，或完整取证确认并集缺任一禁令，记 `WINDOW_DRIFT`，全账本不可用。无法读证（含 401/403、缺少列表或字段、分页缺失/截断、目标全集无法确认）记 `SOURCE_UNAVAILABLE`，不得当作空名单、无经典保护或已证缺保护。Ruleset 明细的 `bypass_actors` 只对有该规则集写权限的调用者可见；取证由受信控制面执行，管理凭据不得交候选 workflow。
- 实时 API 只证明取证时生效。与 `.sandcastle/docs/graph-engineering.md:50` 同级的组织运行前提是：从 `W_GENESIS` 起管理员不临时关闭或放宽保护，不回写历史。账本事件的永久性依赖此连续性前提；已知中断则拒收当前账本，单次成功响应不证明历史无中断。

**再验证签名和逐笔结构。** #2131 限制账本分支仅授权控制者可快进追加，写入通道不得授予对任何生效目标 Ruleset 的绕过。两端从本仓远端读取当前 `L_HEAD`，按完整 SHA 取真实 Git 对象（不用缓存 ref 或替换对象），沿真实父指针回到经核验的 `W_GENESIS`。创世后每笔事件提交必须恰有一个父，须以 R03 固定的 SSH 公钥离线验证 Git 提交签名；签章覆盖提交的树和父指针，不信作者名、签章自报身份或本地默认信任库。普通写者的快进提交即使树差合法，其未授权 `void` 或 `retire_head` 也不作窗口事件。签名私钥由控制者独占，不交候选 workflow。

按正序比较完整父子树：每笔唯一变化为新增（`A`）一个常规 blob，路径为 `events/<seq_6digits>-<type>-<id>.json`；`seq` 从 1 连续加一，路径用六位十进制补零，`id` 对 `open_intent`、`open_bind`、`void` 取 `round_id`，对 `retire_head` 取 `head`。只允许容纳首条事件所需的目录随之新增；禁改删、重命名或替换旧条目（`M/D/R/T`），禁空提交、合并提交和非普通文件。事件是严格 UTF-8 JSON 对象，恰有对应键且无重复键；`head` 是 `GitCommitSha`，`round_id` 是 8-4-4-4-12 位小写十六进制 UUID，状态和 run ID 均为正整数。
- `open_intent`：`{schema_version:"at18-window-event/1", seq:integer, type:"open_intent", head:GitCommitSha, round_id:uuid}`。
- `open_bind`：`{schema_version:"at18-window-event/1", seq:integer, type:"open_bind", head:GitCommitSha, round_id:uuid, status_id:integer, created_at:UtcTimestamp, runs:{acceptance:integer, experiment:integer, ci:integer, devskim:integer}}`；四个 run ID 必须互异。
- `void`：`{schema_version:"at18-window-event/1", seq:integer, type:"void", head:GitCommitSha, round_id:uuid}`。
- `retire_head`：`{schema_version:"at18-window-event/1", seq:integer, type:"retire_head", head:GitCommitSha, reason:string}`；`reason` 只取 `STATUS_CAPACITY_EXHAUSTED` 或 `WINDOW_ABORTED`。

错误创世、链断、非单父、非法树差、跳号、形状/路径非法及缺失或无效授权签章是全账本 `WINDOW_DRIFT`；远端 ref、所需对象读取失败，或取证期间账本头改变，记 `SOURCE_UNAVAILABLE`，须对当前头重新完整取证。可解析但重复的 run ID（包括同一 `open_bind` 内重复）按下述语义冲突处理。

**回放每个 F，隔离语义冲突。** 按 `seq` 分 F 回放：`NONE` 或 `VOIDED` 仅可用 `open_intent(r)` 进入意图态；意图态仅可用匹配的 `open_bind(r)` 进入已绑定态，或以 `void(r)` 进入 `VOIDED`；已绑定态须先经匹配的 `void(r)` 才能开下一轮。任一非退役态均可用 `retire_head(F)` 进入终态 `RETIRED`，终态之后不允许任何事件。无意图直接绑定、漏作废连开、错轮作废、重复绑定等均违规；违规迁移不推进状态。有效退役无须已有意图或绑定。

扫描全部事件（包括旧窗、已退役 F 和违规记录）：`round_id` 的重复申领按 `open_intent` 计，合法匹配的绑定和作废只是引用；`status_id` 和 `run_id` 分别在全部 `open_bind` 中查重。重复 ID 或非法状态迁移触及的 F 与身份永久带污点。以违规迁移所在 F 和每个重复身份为起点，沿签章事件记录的 F 与其 `round_id`、`status_id`、`run_id` 的关联取闭包，纳入全部所涉窗口及身份；三类 ID 各用各的命名空间。受污点影响的 F 或身份一律 `WINDOW_DRIFT`；不得删历史、重置创世或复用旧身份。无需清除旧冲突：无关联、迁移合法且身份干净的新 F 仍可验收。写入端串行校验当前受保护账本头，提交前拒绝重复申领、任何重复 status/run ID、非法迁移及借用受污身份；受污但尚未退役的 F 仍可追加一次合法退役以退出。

**只认当前已绑定窗。** 两端分别重算。F 必须未退役、无污点且正处于已绑定态；没有意图、意图未完成、已作废或已退役均不接受，不回退旧窗。本窗 `open_bind.created_at` 必须严格晚于 F 的所有先前绑定时刻与 #1391、#1403 的所有真实重开事件；同秒不算晚。

**逐票核自 W0 起的完整状态时间线。** 分母是本图所有受合同约束的票：图及 SPEC、TB-01..11 汇总和全部原生实施票、实际承接的交付与决策票（含适用的授权/签署票）、R10/R11 归属票、第四节旧关联票、R13 具名裁定所依赖的票及 #1391、#1403。#2131 的 R03 合同固定枚举及取证来源；两端先从规范、完整关系页、登记及固定来源原件独立求票号闭集，不从报告、最终票态或 PASS 结果反推。后续规则发现应纳而未取证的票，不得输出 PASS；补齐全体自 W0 起的时间线后再求值。

两端在取证开始、输出前、关票前逐票读 GitHub 完整分页的 issue timeline 状态事件原件：至少包含 `closed`、`reopened`、`state_reason` 更改及其他实际状态变更（含终态未变而 reason 改变）；核本仓票号、节点/事件唯一身份、条数、完整页链、服务端时间及与当前票态/原因的对账。#1391、#1403 另从完整时间线取所有真实重开时刻核上段先后。任何相关事件历史缺段、未经证明的事件类型覆盖、无法对账、分页不全或时间不可证均记 `SOURCE_UNAVAILABLE`，不能把端点相同或未见事件当作全窗没变。W0 同秒或之后的任一状态变更即 `WINDOW_DRIFT`，当前报告及包作废、判 FAIL；唯一豁免是 #1391、#1403 各自第三、五节可核实、顺序正确且绑定本窗产物的预期封包 `CLOSED/COMPLETED` 事件（状态及原因同一次变更）；提前关闭、其他结案原因、重开和后续原因变更均不豁免。未到本票封包阶段不要求未来关闭事件。

实时读本仓 `GET /repos/{owner}/{repo}/commits/{F}/statuses`（复数历史，不用 `/status`）只做两件事：
1. 连续读两遍完整历史。每遍均从 `page=1` 开始，使用同一固定 `per_page`，沿服务端 `Link` 核同仓、同一完整 F、连续页码和分页边界，直至终页；每遍所有页的 `id` 均不得重复，每行的 `context` 必须可确定。逐页比对两遍全部 context 的有序 `(id, context)` 序列及页边界（含各页条数与终页），完全相等才采信：若第一遍读完第 `k` 页后、取第 `k+1` 页前该页一条记录到期，它仍在第一遍结果内，但无法以原 ID 重建，因此不在第二遍结果内。任一页读取失败、页链无效或缺页、重复 ID、context 无法确定，或两遍序列与页边界有任何差异，整批作废并记 `SOURCE_UNAVAILABLE`，不选四项、不生成有效输入包。只在稳定快照上将 `at18/window` 按 ASCII 大小写不敏感合计所有作者；达 **1,000 条**记 `SOURCE_UNAVAILABLE`，走下述免状态写入退役。
2. 在该稳定且未满额的快照上按 `id == open_bind.status_id` 取 A，核 `creator.id` 在 R03 的 `window_controller_ids` 授权集、`context == "at18/window"`、`state == "pending"`、`created_at == updated_at == open_bind.created_at == W0`、`description == "at18-window-open/1 round=<round_id>"`。完整查询确认 A 缺失（包括过期）或不匹配记 `WINDOW_DRIFT`。其他状态除计配额外不读作者、时间或描述；未入账状态无论作者、同秒或更晚、描述重复与否，均不参与窗口否决、查重或选锚。

传入定位或输入包登记须与核实所得 `{status_id: A.id, created_at: W0, ledger_commit: open_bind 所在提交的完整 SHA}` 三字段完全相等，定位不得指定账本读到哪一版。#1403 从当时远端头独立重算：封包后同 F 作废、退役或开启下一轮，或受约束票有上述不豁免的同窗状态变更，旧包即拒收。账本及票态事件是持久的失效原件：未入账的短期 Commit Status 出现又过期不改变有效锚；已入账意图消耗的 UUID、作废和退役也不会因状态清理而消失。实时状态缺失和满额仍各按上述诊断处理。

**主控写入顺序：先记意图，再取服务端原件，最后绑定。** 先停 `--review-sweep-auto-merge`，确认无在途合入、通知其他合入方暂停，记录 F。未满额且未退役的 F 若要重试，先追加并读回匹配的 `void` 结束前轮意图或绑定；尚未开窗或已作废无需重复写。不向 GitHub 写作废状态。仍无法确定旧 dispatch 是否会生成 run 时，不沿用同一 F，先退役换 F。同 F 的主控操作串行执行；所有追加均在已校验的远端头上以授权签章、单父提交、快进写入；若头已前进，重读校验后再决定，不覆盖记录。
1. **先落盘。** 以全账本未使用的 UUID 追加并读回 `open_intent(F,r)`；直到读回成功才可接触 Status/Dispatch 写 API。崩溃或中途缺项留下未完成意图；该 F 不可验收，同 F 重开须先作废，该 UUID 永久消费。
2. **取服务端时刻和本轮 run 身份。** 用 `POST /repos/{owner}/{repo}/statuses/{F}` 写 `context="at18/window"`、`state="pending"`、`description="at18-window-open/1 round=<round_id>"`（61 个 ASCII 字符），取得 `status_id` 与 W0 原串。等过 W0 所在秒，向本仓四个 R06/R08 工作流各发一次 `POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches`，钉住 `X-GitHub-Api-Version: 2022-11-28` 和请求 `ref="main", return_run_details=true`。按每次请求的工作流槽位接收 HTTP 200 的 `workflow_run_id`、`run_url`、`html_url`；只用响应的 `workflow_run_id` 绑定，URL 不代替 ID。204、超时或其他无确证响应、缺任一 ID、重复 ID 均不得形成绑定；不重发去向未明的请求，不从 run 列表猜补。
3. **绑定并读回。** 四个响应身份齐备后，核对 F 仍冻结、同轮意图仍未结束，再追加 `open_bind`；核其状态 ID、W0 和四槽 ID，读回有效锚后交 #1391。R06/R08 只验这四个 ID；任一 run、最新 attempt 或必需作业不合，不能靠其他运行补齐。正常封包后只有锚及四个 run/attempt 未变，#1403 才能同窗复验。

**退役后解冻不等于新窗验收。** 同 context 达 1,000 条或确认写入因配额被拒（HTTP 422）时，不再向该 F 写任何状态；追加 `retire_head(F, STATUS_CAPACITY_EXHAUSTED)`。主动放弃 F 追加 `retire_head(F, WINDOW_ABORTED)`。主控从受保护链读回并核实退役即恢复原有合入安排，#1391 保持 `OPEN`；不必等状态过期、旧 dispatch 返回或第 1,001 条状态写成。新 F 必须独立完成新意图、状态和四次 dispatch 响应的绑定；即使旧请求此时才解析 `main` 并生成 `head_sha=F'` 的 run，也不属于新窗。旧 F 即使日后清空状态仍永久拒收。不得为解冻修改保护、取消 strict 或停止正式独审。

#1391 在未验收阶段保持 `OPEN`，不得提前关闭再重开制造事件；关票只走第三节封包门。到关票前若主线前移或窗口作废，旧报告只留作过期证据，重新确定 F、开窗、四项重跑并重新生成和复验；已封包关闭时只重开受影响的验收票，不重开历史切片。无有效输入包供最终绑定记 `WINDOW_DRIFT`。两类锚诊断均用第八节 `ticket:1391@window_anchor`，不计本轮 run，不生成有效输入包。正常完成后恢复原有合入安排。入口见 `.sandcastle/deepagents-pilot/pilot1742/executor.py:889-892, :960-967`；操作单由主控在本 ADR 落地时写进 #1391。

### R02　计算分母

从 F 读取第五节钉住的规范三件；不需要输入包先存在。分别按 `rows[*].story_id`、`family_entry_links[*].id`、`detailed_acceptance_links[*].id`，和同一行每个 `success_closure_slice_ids` 展开 `Key=(kind,id,slice_id)`（kind 依次为 `story|family|detail`）。拒绝重复行身份、重复切片、空切片集、未知 ID/切片、无效引用（`COVERAGE_SOURCE`）。当前规范 97/345/496 行，展开 4,071 键：TB-11 113 个，其余 3,958 个。不得读 `slice_success_obligations` 代替展开，也不得产生 Destination 键。六个 `destination_success_obligations` 另须一一对应 DST-01..06；链接 ID 和归属必须有效。每项 `success_gate_ids` 必须非空、无重复，逐 ID 在同一 F 的 coverage input 中以 `FU-*` 对应 `policy_gap_dispositions[]`、以 `G-*` 对应 `proof_sync_choice_locator_dispositions[]` 唯一命中；字段非法、ID 未知或无法唯一定位记对应 DST 的 `COVERAGE_SOURCE`（`scope=/destinations/<n-1>/success_gates`）。这组验收关系不加入 4,071 个覆盖键。编号为 `DST-*` 的 **family** 条目仍按 family 展开。

逐一核 `n=1..6`：`SPEC.json` 的 `stories[]` 须唯一命中 `id="US-DST-0<n>"`；`SPEC-COVERAGE-INPUT.json` 的 `destinations[]` 须唯一命中 `id="DST-0<n>"`，且其 `user_story.id` 同为 `US-DST-0<n>`。前者的 `observable_result` 与后者的 `user_story.observable_result` 各须为合法、非纯空白字符串（以 Unicode White_Space 属性判纯空白，只用于校验，不修改输出）。二者描述不同，无须字节相等。无法读取、严格解析、定位唯一对象或满足字段要求时，按受影响的每个固定 Destination 写 `DST-0<n>` 与 `COVERAGE_SOURCE`（`scope=/destinations/<n-1>/obligation`），该项 FAIL；若根结构无法定位任何行，六项都使用此编码。crosswalk 等其他源失败也按 R14 留诊断，不猜分母；只在两处均校验通过后才照录 `SPEC.json` 原字符串，`SPEC.md` 供人阅读，不作该字段的取值源。规范源失败不生成有效输入包；报告自身引导成功即写形状合法的 FAIL 报告。

### R03　绑定必须覆盖出处

先通过 R09 阶段一，再核 R02 的规范三件；不得用合法引用或已知字节摘要把失败源写成有效输入包。承接 #2131 的登记册与 #2132 的闸前复审均读 F：以仓根 .chanlun/ 下的 `at18` 子目录为父目录，文件名分别为 `registry.json` 和 `pregate-review.json`；四份切片账路径见第五节。登记册 `crosswalk_sha256` 与 F 的实际字节相等。按键求必需 basis 集：

#2131 在同一仓根目录 `.chanlun/` 下的 `at18` 子目录交付唯一 F 版规范适配器数据合同，文件名 `adapter-contract.json`，`schema_version="at18-adapter-contract/1"`。从 F 读该普通非空 Git blob，以原始字节重算 SHA-256，必须等于同一 F 的登记册 `adapter_contract_sha256`；输入包既有 `registry_ref` 绑定登记册全字节，因而传递绑定适配器，无第二份适配器引用。合同顶层 `window_controller_ids` 固定 R01 的主控授权 GitHub 数值账号 ID（非空、正整数、升序且无重复，由主控核定并随合同获审合入；两端同读 F，不从调用参数或状态描述取得授权）。合同另以顶层 `window_ledger_genesis: GitCommitSha` 固定 #2131 在交付前建置并加保护的本仓 R01 账本创世提交 `W_GENESIS`；两端同读 F 的获审合同，不从远端现有链或包内定位推断创世，切换 F 不换创世。顶层 `window_ledger_signing_key` 固定该账本专用的控制者 SSH 签名公钥（OpenSSH 公钥格式，`ssh-ed25519` 算法和公钥主体，不含注释）；两端用这一把获审公钥为创世后全部事件提交离线验签，不从事件、Git 作者字段或环境取得授权。顶层另有 R09 的 `history_ledger_genesis` 和同账本签章公钥，与阶段一已验证的独立部署原件对账，只作一致性检查，不参与阶段一。其余取值规则为 R07/R13 的固定来源角色、字段身份、RFC 6901 提取指针或固定文书/票面定位和预期类型。R12 四类证据的固定提取规则也在此合同中声明；一个字段只有一条取值规则，同角色的多个合法原件按第八节取全量。阶段二独立验文件、封闭版本合同及摘要，再用阶段一已求得的 R09 集成结果核登记册和本文件在 F 第一父链上各自最近一次引入或改变该路径条目的提交（从 F 向 P0 比较相邻提交的路径 mode/blob；两者都须在 G0..F）；无锚、非普通文件、缺失、坏合同或摘要漂移记 `REGISTRY_INVALID`，锚的集成门不通过另记 `REVIEW_FINAL_PRODUCT`。任一失败不消费该合同、不生成有效输入包，不从工作区、旧 F、报告或其他适配器补值。

1. 三份切片账的 `/units/<i>`，若 `parent_tb=Key.slice_id` 且按 kind 在 `story_ids|family_entry_ids|detailed_acceptance_ids` 命中，**所有**命中各需一个绑定。
2. 无命中时，TB-01 family/detail 若在贡献档 `/rows/<i>` 中按 `family_entry_id|parent_detailed_acceptance_ids` 命中，取所有匹配行；否则取 crosswalk 中该键的唯一展开原节点。贡献档仅是分工出处。coverage input 用于规范语义的指针解读（含 OE42），不能替代上述 basis。

一个 binding 只取一个 basis，声明的每个键必须属于同一 slice 并且该 basis 在该键的必需集中。读取 F 上该路径的 Git blob 校字节摘要和 RFC 6901 指针；不得另挑下钻节点缩验收面。对每个非 TB-11 键，核其实际 `(Key,basis)` 与必需集相等且无重复。超集键 `KEY_NOT_EXPECTED`；无绑定 `KEY_UNBOUND`；错指针、摘要、超出或重复 basis `BASIS_MISMATCH`；缺必需 basis `BASIS_INCOMPLETE`；登记册读不到或形状不合法 `REGISTRY_INVALID`。TB-11 键不得出现在 bindings。

### R04　保持证据域，不做跨类替代

`Domain.result` 是为该域声明的义务类型，不是实测结论。以 `(evidence_class,profile_id)` 区分域；simulation 的 profile 可为 null，experiment/production 必须取受测版本化场所 profile ID。每条 binding 至少一个非延期域。每个运行域的 checks 非空，所指检查的类及 profile 与域完全相等；运行域的 `deferred_gate=null`。仅且所有 `exclusion_boundary=true` 的 family 键使用 `PRESERVED_BOUNDARY`，无延期；OE42 执行其 `OUT_OF_SCOPE_PRESERVE` 处分的检查，但仍为必需 `VERIFIED` 键。

`BOUNDED_DEFERRED` 域不运行检查，`checks=[]`；`deferred_gate` 限 `ISSUE_1561_P2_FIRST_SEND`（production）、`ADR_0036_POST_GATE_EXPERIMENT`（experiment）、`ADR_0036_POST_GATE_PRODUCTION`（production），并须与本轮**独立求得**的具名门状态、槽位及 `unexecuted[]` 同名可延期项相符。就已启用 P1 profile 的后闸行为域，额外要求 R07 从完整有效槽证明**全体重均从未启用**；存在任一曾启用重（含已回退）即不可整体延期。此时 `unexecuted[]` 即使有同名条目也只登记从未启用子集，不能进入该域或替代实际运行。不得用槽汇总名或事后切换 `Domain.result` 降级已有运行域。#1561 的生产首发送未启用期间不得登记 production 检查；本版 AT-18 只证明本图的 simulation 与 P1，生产槽一律 null；若生产授权已生效，另走相应具名门并修订本验收合同，不让 /1 偷换射程（`PRODUCTION_SCOPE_CHANGED`）。缺 #2133 或受测动作别项硬门时，相关 experiment 仍是必需，记 `AUTH_REQUIRED`，不得延期。域不合（含空域、重复域、跨类、未声明 profile、无法证明延期）记 `DOMAIN_INVALID`。

首次及新增绑定由登记册作者按规范声明域，正式 PR 独审逐键核首定射程、真正需要的 experiment、断言与执行选择器；crosswalk 无这类机读下限，机器不从散文猜测。#2131 的 `at18-registry-lint` 进 `ci-ok.needs`，在每个登记册变更 PR 核 R02–R05 的静态部分（开工骨架可缺覆盖，正式报告不得缺）。以 PR merge base 上的登记册比较：已有 `(Key,basis.path,basis.pointer)` 及域的类/profile 不得删除或移成别键；运行域不得降为延期，已有非延期义务不得以替换基准文件或改指针消失。每次修改须重 pin；规范确有重编或收缩，先修订本合同和覆盖正本再迁移，不设 lint 豁免（`DOMAIN_SHRINK`）。

### R05　检查契约

在 F 读取每条检查的 `source.path`，实际字节摘要须等于登记值（`CHECK_SOURCE_DRIFT`）。固定 `selector` 在该源上执行；运行器按框架读取实际执行名及数，确保命中所登记用例且执行数等于正整数 `expected_count`、跳过和忽略均为 0；选错、未执行或见证缺失时检查进程与作业失败。非键感知测试的 `source` 必须是所执行测试定义所在文件，每个绑定键有独立行 `@at18 <slice_id> <kind> <id>`（允许行首缩进与该语言注释标记，不以子串命中，错标记 `CHECK_NOT_ANNOTATED`）；同源多测试须把标注挂在选中用例下。键感知检查接收按字节序排列的条目 `{kind,id,slice_id,basis_path,basis_pointer}`，运行器核结构化见证的身份集合与输入完全相等、无重复、每项断言成功；`command` 必为键感知，禁止直接信退出 0。R05 的成功仍须有 R06 成功作业。TB-01 的本机耐久、重启与真实浏览器合同改用同射程的 runner 内实际进程重启和 headless 浏览器；无法在 F 上证成即留红，由当前 TB owner（TB-01 为 #2132）登记阻塞缺陷并修复，不把探针报告抄成绿。

### R06　选一次真实执行

只在 R01 核实当前窗后取 `open_bind.runs.acceptance`（simulation，对应 `at18-acceptance.yml`）与 `open_bind.runs.experiment`（对应 `at18-experiment.yml`）；#2131 在 .github/workflows/ 交付两文件，均无自报 dispatch inputs。以下取证规则也适用于 R08 的两个槽：按本仓约定的工作流路径查服务端 `workflow_id`，然后用 `GET /repos/{owner}/{repo}/actions/runs/{run_id}` 读取**该精确 ID**，核响应 ID、`workflow_id`、`head_sha == F`、`head_branch == "main"`、`event == "workflow_dispatch"` 与服务端 `run.created_at > W0`。从服务端 run 取最新正整数 `run_attempt`，读该编号的 attempt 原件和对应分页 Jobs API，复核身份和 attempt；run 与该 attempt 均须 `status == "completed"`。simulation、experiment 与 DevSkim 另要求 run 和 attempt 的 `conclusion == "success"`；通用 `ci.yml` 不用这两个聚合结论作门，只按 R08 的必需作业闭集判断。最新 attempt 不合本槽判据即失败，不回退；部分重跑缺必需作业须在原 run 上全量重跑。不得扫描列表按时间或最大 ID 补选，不借其他 run、旧 attempt、祖先 SHA 或同 F 旧窗。

每个必需组恰有一个名为 `at18 <group> <S>` 的完成成功作业，S 是 F 的登记册文件字节 sha256；组内登记检查必须全部成功，组不得跨类/profile，封印按 R07 同 attempt 核验。已证实所绑 run/attempt 或必需组作业缺失、重名或无法唯一定位，记 `CHECK_JOB_MISSING`；运行身份不合（含时间或所核 attempt 不符）记 `WINDOW_DRIFT`，存在但未完成或非 success 记 `CHECK_JOB_FAILED`。读 API 失败或分页不全记 `SOURCE_UNAVAILABLE`，不写成已知缺失；R01 失败时不读作本轮 run，按 R01 留红。TB 由自己的组结果归并；局部成功不能替代整轮验收。

experiment 工作流只可在 #2133 指定的 self-hosted runner 授权范围内启动接触凭据的作业。在任何接触前按 ADR 0041 和签署票验有效域、期限及动作，未签、越域、撤回或无法核实时不启动；#2133 状态、缺/失效授权原因照录，检查不通过。只读签署不授权发送；受控发送另守 #1412。机器仅按 #2133 实际签署原件和已批准 profile/runner 范围核对，不把 shared GitHub 账号的作者显示名当作可区分人机的签名；项目保证签署只由用户发出（`.sandcastle/docs/graph-engineering.md:50`）。不搬运或记录凭据。simulation 不得运行凭据接触动作。

### R07　封印运行记录

必需运行记录按 `(record,profile_id)` 唯一归属一个组：`permission.experiment`、`migration.experiment`、`post_gate.experiment`，以及 TB 实体报告 `tb.simulation.TB-xx|tb.experiment.TB-xx`。每个允许记录的检查声明一项 `record`，同一记录/profile 不得有两个生产者。权限、迁移、后闸三种记录各须至少一个实际启用的 P1 槽位，报告使用的 profile 由获审登记册明确选定，三个槽位一致；不得从绿色作业反选。为 TB-01..10 各自登记实际需要的类，至少一份本轮实体报告；TB-08..10 必有 P1 实体与相应必需检查。第二节的三专用门所需检查为该记录/profile 的记录生产者与其组，不能用不存在的键推迟。

记录生产者按门或 TB 的固定业务合同，把**运行原件**（数据及必要索引，不收 `passed`/`verdict` 代替事实）写成严格 JSON；共同封闭外层为 `{schema_version:"at18-run-record/1",record:string,head:GitCommitSha,run_id:integer,run_attempt:integer,check_id:string,profile_id:string|null,payload:object}`，各身份字段须与服务端作业及登记检查完全匹配；payload 用对应门的版本化原件格式，不同身份不可互用同一文件。每个运行证据文件字节摘要由同组输出传给同 run 的独立封印作业，作业名 `at18-seal <record> <profile-token> <S> <sha256>`（profile-token 为版本化 ID，simulation 的 null 写 `none`）。一个 kind/profile 可封印多份不同记录文件；每份都恰有一个对应成功封印作业；封印须依赖对应组成功，不得接受来自其他组的输出。只信 R06 所选 run/attempt 含服务端成功封印的字节。检查运行使用受审的 F、无不可信输入；登记名语法与固定前缀分离，运行原件不控作业名除输出摘要外任何字段。

#1391 把文件作为本票 manifest 中的 external reports 登记（先取得已封印原件，再引导；此时报告和输入包可尚未登记；产出和登记顺序按第三节），引用全部同 run、F、类及 profile。专用槽运行引用、`evidence_by_class` 和 `evidence_by_kind` 中用作运行证据的条目、TB 实体均按本条复算；缺登记、字节错、两次运行拼接或无唯一成功封印记 `RECORD_UNSEALED`。非封印原件只可按第五节照录规范文书、合法授权原件（用户签署原件，或第二节第 4 条允许的普通研发域代理独审裁定原件）、场所依据及 ADR 0058 的专用仓内载体。代理裁定不得记为 `UserSigned`。旧报告本身不能绕过 F 运行，有关 AT-14 的现场结论也必须由 F 上的绑定检查执行。仓外清单及 ArtifactRef 的摘要不是业务通过证明。

规范适配器数据合同取 R03 固定且经 R09 锚核验的 F 上唯一文件；#1391 与 #1403 按同一合同各自从原件读取并计算，禁止接收字段同名的结果布尔值：

- 权限记录读实际 X 启动第 4–7 步及 profile/版本的互引；比对签署的授权声明、#1770 文档来源元数据和实际能力记录、profile 字节，以第二节三层及三元组条件重算。授权文书与场所文档属依据，不从运行记录的自报字段补写。
- 迁移记录读同一 profile 的非空前态、未结单及费用尾，回放迁移、中断及回退前后归属、资金账、writer/发送的原始记录，按 ADR 0063 的身份映射、责任与四不变量重算；要求存在实际非空见证，不能把空集合上的全称当成功。
- 后闸记录在获审 P1 profile 的同一受测运行中，从封印的重清册、各重阶段状态及完整事件流独立对账重全集（含运行中新增或终止的重），不以出现触达／启用事件的重作全集。逐重核身份、资格、候选、正式触达、合法版本、首次启用和所有后续转换，包括回退触发、版本、执行时序及回退后状态。授权核实质生效域，不只看签名来源。#2131 的 R03 合同须钉住所选 profile 的后闸行为检查、适用域（binding ID、证据类、profile）及逐重见证字段：由 `post_gate.experiment` 的 R07 记录生产者在 R06 同组中实际执行，封印与同一运行及每重身份匹配的行为结果。逐一对账曾启用重的身份全集；缺任一重的实际检查均不通过，三记录本身不算行为见证。已回退重另须实测已撤能力在回退后继续受禁，且后闸参数不再生效；不得把当前关闭状态或从未启用重的拒绝记录充作该重的回退后行为。检查和见证缺项不能由另一个 profile、重或 attempt 补齐。
- **开跑前的启用历史。** 能认定一只重合法从未启用，须以 R07 封印原件证明从可验证的初始创世态到当前持续未切换、未启用；恢复或迁入时，须追到同一重可验证的初始态，或在封印载荷中绑定完整的恢复／迁入前持久历史原件并校验其来源、字节及前后边界。逐重核同一身份（迁入含可复验的身份映射）、历史事件连续性与运行初态的承接，不把恢复快照当新创世，不把当前关闭或本轮无触达／启用事件当作开跑前未启用。#2131 的 R03 合同固定初始态、历史原件及承接边界的提取与校验。开跑前历史缺段、绑定不可验证或不能排除曾启用时，该重为 `UNKNOWN`，按 `SPECIAL_GATE` 阻断整图且不得延期；历史证实曾启用则按两种启用历史态核相应三记录及实际行为，即使本轮没有新触达／启用事件也不准延期。
- 后闸延期分两层：槽记录全部有效时，只将合法从未启用的重登记到同槽唯一的具名 `unexecuted[]`，其精确范围从逐重状态可重算；只有该集合等于完整槽全集且非空，才准许 R04 的 P1 后闸行为域整体延期。只要有曾启用重，R07 实际行为检查必跑，R04 不接受该 profile 的后闸行为域登记为延期；无论 `MIXED` 还是同态已启用／已回退均如此。未启用部署槽的延期仍按 R04。重全集或汇总失败在槽的 `chong_records` 字段记 `SPECIAL_GATE`，逐重失败在对应记录或缺证字段记 `SPECIAL_GATE`（按第八节指针）；缺证不写成未触发。
- TB 实体读本 TB 的原件中测试身份、键/域集合、实际运行条件和输出，与 R02–R06 计算的集合逐项比对。缺实体或不匹配、专用判据不成立记 `TB_REPORT` 或 `SPECIAL_GATE`；诊断按字段逐项列出。运行记录适配器由生产者写并在 Actions 作业实际运行；#1403 运行 #2131 先行交付的验证器，独立消费固定合同与原件，不导入或调用 #1391 生成器。

### R08　在 F 核通用 CI

只有 R01 确认当前 F 的锚有效，才依 R06 的精确 ID 规则核 `open_bind.runs.ci`（`.github/workflows/ci.yml`）与 `open_bind.runs.devskim`（`.github/workflows/devskim.yml`）及其最新 attempt 和分页作业；不另选 run。R01 失败时按其诊断留红，不计本轮 run；运行身份不符记 `WINDOW_DRIFT`；经完整查询确认所绑 run、attempt 或必需作业缺失、重复、不全或不成功记 `HEAD_CI`，API 失败或分页不全记 `SOURCE_UNAVAILABLE`；取 F 版 YAML 的 `jobs.ci-ok.needs`（字符串或列表，均须归一化为非空 ID 集且含 `at18-registry-lint`）；`ci-ok` 与每个 needs 对应的全部实例须成功，跳过不算。矩阵分母固定为 GitHub 服务端为**该 workflow run 实际展开**的全部矩阵实例，不随 attempt 改写。用能证明完整展开的服务端原始展开记录，或首次展开的 attempt 1 全量分页 Jobs API 原件（含非成功实例，核身份、页链、条数与完整性）固化分母；以 F 的作业 ID、默认名／`name` 和矩阵声明逐个核实例身份及合法展开。仅当原件能证明服务端完整展开才采用，不能从最新 attempt 的子集、`ci-ok`、成功作业或 runner labels 反推。最新 attempt 的 runner labels 只证明执行位置；单作业重跑重新求值 runner 不改变分母。以最新 attempt 的完整作业页对照固定分母，要求每个必需实例恰一次且成功，不借旧 attempt 的结论。分母原件缺失、分页不全或无法证明完整展开记 `SOURCE_UNAVAILABLE`；分母已证但映射歧义、实例重复、缺失或未成功记 `HEAD_CI`。本槽通过条件仅取完成状态及上述闭集（`ci-ok` 本身和其 `needs` 的全部实例）；闭集外的作业（如手动触发的 `macos-session`）既不作验收证据，也不改变 R08 判定，即使它使 GitHub 的 run 或 attempt 聚合结论为 `failure`。仍在 `CiRunRef.conclusion` 如实写服务端 run 结论，不改记 `SUCCESS`；`acceptance_jobs[]` 只投影验收闭集。#2131 对 CI 声明变更保持该全量展开能力，不能识别的表达式不默认为空。DevSkim 须在本窗所选 attempt 中唯一 `DevSkim` 完成且成功；#2131 增加该触发。原工作流的 push 去重与 PR Rust 指纹不进 AT-18 的 CI 证明。取证依据：`.github/workflows/ci.yml:4, :41-46, :455-469, :480-526, :538-561（尤其 :558-559）, :872-891, :1457-1518`；`.github/workflows/devskim.yml:6-27`。

### R09　闸后：逐个核主线集成

**阶段一：从独立部署原件完整验证 R09。** #2131 在冻结前建置本仓 `refs/heads/at18-history-ledger`。受信控制面将其无父空树创世、签章公钥和完整解码合同作为 #2131 的正式部署原件登记；部署清单在仓外受控发行目录固定该原件的版本、不可改写定位与字节摘要。#1391 和 #1403 各自从这一预置信任入口读同一原件，不以 F 的文件、候选 workflow、远端账本当前内容、输入包或调用方自报值选择信任锚。部署原件须绑定本仓数值 ID、主线 `refs/heads/main`、历史账本 ref、G0/P0、最后一笔尚未受新入口保护的主线提交，及下述版本化解码规则。部署原件或其版本不可核即 `SOURCE_UNAVAILABLE`；不得用运行中的 F 补齐。

`HistoryBootstrap`（10 键）：`{schema_version:"at18-history-bootstrap/1",repository_id:integer,main_ref:string,ledger_ref:string,genesis:GitCommitSha,signing_key:string,g0:GitCommitSha,p0:GitCommitSha,legacy_through:GitCommitSha,decoder:HistoryDecoder}`。`HistoryDecoder`（3 键）：`{version:string,locator:string,sha256:Sha256Hex}`，定位于同一受控发行目录下不可改写的相对路径。主线与账本 ref 取上述常量，公钥使用 OpenSSH `ssh-ed25519` 算法和公钥主体，不含注释，`legacy_through` 须是 F 第一父链上从 G0 起的最后一笔入口前提交；新入口启用时由部署方以实际切换前的主线回读钉住，不从待验账本推断，不按通过与否划线。

解码合同随部署原件一并固定并校验字节，至少包括账本外层、记录类型、下表的原件角色及必需集合和条件，及各角色权威来源、相对定位、基数、字段提取位置与类型、正反值规则、服务端身份／时间／页链的解码版本。对不同冻结 controller 版本的正式发布、回执、沿用准入等，明确登记完整 SHA 对应的解码版本；只有经独立部署登记的版本才可使用，不执行 F 或历史 PR 中的候选代码来取得判据。缺版本、未知必需角色、必需字段或原件缺失均失败。阶段一共用的 Git 保护、签章和分页读法随部署合同固定，不读 R01 取自 F 的任何开窗合同或账本。下表以角色组简写；每组中的各原件角色、条件和基数须在部署原件中逐项展开，不能自行选少验哪一件：

| R09 记录或情形 | 必需原件组 |
|---|---|
| `merge_intent` | `merge_request`：含原执行者唯一实例、仓库/PR、方法、路径、完整请求 SHA 及 base/head；`pre_merge`：预合入 PR/main 回读与完整状态页、正式 App 证据（含适用的沿用组）。 |
| `CONFIRMED_NOT_MERGED` | `merge_rejection`：可归原请求的服务端终结且未执行原件；`post_merge_readback`：新取同一 PR/main 原件。 |
| `SUPERSEDED_UNKNOWN_INTENT` | `sender_exit`：受信控制面原执行实例及写入子进程退出／不再派发的证据；`head_fence`：推进前后 PR、同源 ref、Git 对象和不可回退的控制原件；`post_merge_readback`：屏障后 PR/main 与第一父链核验。 |
| `MERGED_PASS` / `MERGED_VIOLATION` | `post_merge_readback`；`merge_cutoff`：实际 M、PR 合入时刻与两批完整状态原件；正式 App 证据，沿用另加原轮、竞争轮和锁内时序组。请求响应若可取须保留，但不是确定实际合入的前提。 |
| 正式 App 证据 | `review_registration`、`review_publication`：逐轮 target、outcome、发布日志及绑定的 GitHub 状态；`review_receipts`：直接审查两份独立回执；沿用另加 `reuse_history`，完整登记、回执/最终消息、原发布及沿用准入、锁内单调登记原件与高水位、服务端截止取证，以及适用的锁前可见性或锁内枚举原件，按下文第 3 步定条件。 |
| `violation_archive` / `history_baseline` | 前者须有 `repair_decision`；后者须有 `baseline_inventory`（第一父提交和已核出处、可核字段及缺件清单），可证齐全者另须有 `merge_cutoff`、正式 App 证据和可验证的 `baseline_coverage`（下文补录规则）。 |

历史链按独立部署合同验证生效保护（R01 相同判据，但查询历史账本分支）、连续保护前提、授权签章、单父、连续序号及只追加树差；不混入 R01 开窗事件。每笔只新增一条记录及其原件，不得改删旧条目。原件由签章树直接保存或以摘要绑定至同样不可改写的归档。阶段一验证全链签章与载荷外层身份，只对 R09 记录及必需原件解码求值；R11 记录有独立类型和版本，阶段一不消费其业务载荷或通过值。两端分别重算 G0..F 的每笔集成与全部未决锁；证据链不可读、不可验证、存在不一致或采集未完，按所涉作用域记 `SOURCE_UNAVAILABLE`，不将缺项当空集合。

**阶段二：R09 通过才读取并消费 F 上的业务合同。** R03 复用阶段一已经算出的各提交集成结果核各自引入／变更锚，并核 F 上的历史账本创世、公钥与独立部署原件一致。之后才用获审 R03 合同验证 R01 开窗、R04–R08、R11–R13 的仓内合同与业务原件；不以第二阶段任何结果反证阶段一。R09 失败时只留有关诊断和可核实观测，不能生成有效输入包。写锁与验收另判：确认未合入与旧意图被替换是两种不同的封口，都不产生集成缺口；违规封口不是未决，也不因此通过。

**原件从哪里取。** 从 GitHub `GET /repos/{owner}/{repo}/commits/{M}/pulls` 枚举关联 PR，逐项用 `GET /repos/{owner}/{repo}/pulls/{pr}` 核实际合入；主线头读 `GET /repos/{owner}/{repo}/git/ref/heads/main`。以完整 H 读 `GET /repos/{owner}/{repo}/commits/{H}/statuses?per_page=100`，遍历服务端页链，保留原始响应和服务端时间；不用合并视图 `/status`、check run 或只留最新结论（现有 `.sandcastle/deepagents-pilot/pilot1742/delivery.py:238-253` 只列当前可见记录和提交状态）。正式发布方为 `newchanlun-review-gate[bot]`，按部署登记的 App 及服务端作者身份校验。受信控制面从 App 的 `external-review/runs/<登记目录>/` 取 `target.json`、`outcome.json`、`effects/status-*.json` 和 reviewer 子目录下的 `launch.json`、`receipt.json` 及适用的 `events.jsonl`。按完整 `run_id`、`publication.id` 和冻结仓库/PR/base/head 对账，不以目录名或 `mtime` 作证；待认回的发布日志不是发布完成。将这些原件按第 2–3 步封入签章链或不可改写归档；运行目录中尚可更新的 outcome 不是固化快照。

**Status 保留边界。** [GitHub 仓库设置文档](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository#configuring-the-retention-period-for-checks-workflow-runs-commit-statuses-artifacts-and-logs-in-your-repository) 说明 2026-10-01 起统一保留策略包含第三方 Commit Status；默认 90 天，改值只适用于新对象。设置页 `Settings → Actions → General` 可读采集当时的实际统一设置；制品或日志专用保留值、当前值和默认值都不能倒证某条历史状态的有效期。[Commit Status REST](https://docs.github.com/en/rest/commits/statuses) 无逐条删除审计或历史保留配置读取接口；[组织审计事件目录](https://docs.github.com/en/organizations/keeping-your-organization-secure/managing-security-settings-for-your-organization/audit-log-events-for-your-organization) 中 Actions 制品／日志保留及 workflow 删除事件也不能证明 Commit Status 历史无删除。不得要求这样的 REST 响应作为补录前置。近／超保留期以有同时期记录支持的最早失效时点为界，服务端观测距它不超过 24 小时（含过期）即不得新建该历史的完整性证明；没有同时期依据则不声称历史保留期可证。R11 仍分别验证 workflow、尝试及日志的留证，不借 Status 证据推断 Actions 历史。

G0 = PR #1915 的落地提交 `bd54d4b28ec4f83d596837f84f1f861dd085124c`（含 G0），P0 = G0 第一父 `b5cd3fee352e5f7199233de628da05ff06c5798f`。F 的第一父链必须经过 G0。沿 G0..F 的全部第一父提交 M（包括与图无关的提交），每一项均须满足：

1. M 恰有两父，H 为第二父；查 GitHub 与 M 关联的 PR 后唯一命中本仓已合入记录：`merged=true`、`base.ref=main`、`merge_commit_sha=M`、`head.sha=H`；以 Git 比较 `tree(M)=tree(H)`。
2. 用 GitHub 服务端的 `merged_at`（UTC）作硬截止点。须先核该合入绑定的已固化快照：两遍全量分页均先按 `ascii_lowercase(context) == "deepagents/review"` 收齐同一检查的状态记录（只折叠 ASCII A–Z，保留原 context 拼写、全部作者和状态；不先按作者、结论或时间筛选）。固化两次完整页链、各页条数与边界、服务端时间、上述组的全量 `(id, context, state, creator, created_at, updated_at, description)` 及可核原始响应。按 R01 的双遍稳定分页法比对全部页，并核该组的完整元组，不只核 ID 与 context。此归组适用于 R09 的预合入、合入截止、历史补录及沿用涉及的各 head；#2131 须纠正现役读取器的精确匹配（`.sandcastle/deepagents-pilot/pilot1742/external_review.py:208-210`），入口、发布器与独立复算用同一规则。新入口在首次发布前建立该 H 的取证起点（也可使用已可证覆盖的旧 H），按有效保留边界及时做请求前及实际合入秒后的完整快照，并交叉核对正式 App 发布、登记及回执；出现无法覆盖的窗口不得发请求或封作通过。沿用涉及的其他历史 head 同样保留据以证明原发布、否决及完结性的状态页和正式 App 原件。缺有效固化截止快照记 `SOURCE_UNAVAILABLE`；入口上线前的既有合入按下文补录，不拿当前可见的旧 `success` 补历史。复核须对照固化快照和所绑定的原件；仍可取得的实时原件亦须对账，出现影响截止点的差异即留红，正常过期不得删掉固化条目。

   确立完整性后，任一状态缺可比时间或数值 id、或 `created_at > updated_at`，均不能证明顺序。H 上归入该检查的任一状态（含大小写变体）的 `created_at == merged_at` 或 `updated_at == merged_at`（不论状态或作者）即拒收，秒级时间和 status 数值 id 不能与合入事件消歧，不改选更早的成功。无碰撞时按 `(created_at,id)` 降序选首条 `created_at < merged_at`，先选后验。所选条目须满足 **`created_at <= updated_at < merged_at`**，且为 `newchanlun-review-gate[bot]` 的 `success`。所选条目到合入后才更新即失败；严格晚于合入秒创建的状态既不补审，也不覆盖截止证据。
3. 解析所选状态的 `description`，只认 `run=<run_id> b=<base12> h=<head12> success` 或其后接 ` reuse=<source_run_id> p=<patch12>` 的正式格式。`b/h` 前缀只校验文本格式，须分别等于 M 第一父与 H 的前 12 位，不代替完整身份。**两种发布共用登记门**：用状态的 `id` 与描述的 `run_id` 唯一查回正式 App 的 `target.json` 和 `outcome.json`，核两份原件对同一 run 的冻结身份一致：`repository_id` 为本仓服务端 ID、`pr_number` 为第 1 步唯一命中的已合入 PR、完整 40 位 `base_sha` 为 M 第一父、完整 40 位 `head_sha=H`；且 `publication.id` 等于所选 status 的 `id`、`publication.state="success"`。状态挂在提交上，共享完整 base/head 的另一 PR 的发布也不得借用。发布与登记见 `.sandcastle/deepagents-pilot/pilot1742/external_review.py:93-115, :469-479, :499-501, :984-992, :1027-1040, :1114-1119`。
   - **直接双审**：描述无沿用后缀、正式 outcome 无 `reused_from` 且为 `PASS`，同一 `run_id` 下有两份独立、已完结的审查员 PASS 原始回执（不同审查员、不同 session，绑定该轮冻结身份，并与 outcome 明细一致）。
   - **沿用溯源**：当前正式 outcome 为 `PASS`、`reviews=[]`，`reused_from.run_id` 等于描述的 `source_run_id`。按该 ID 在同一仓库与同一 PR 唯一找到非沿用的原双审轮，按上项核两份独立 PASS 回执；原轮的正式 `success` 也须在该合入的固化快照内按原状态 ID 取证、与 App 登记、完整冻结 `base_sha=B_orig` / `head_sha=H_orig` 及其发布记录绑定。原状态须由同一 App 发布且 `created_at <= updated_at`、`updated_at` 严格早于本次沿用状态的 `created_at`。原轮和沿用轮的 `policy_version`、`review_contract`、`controller_code_head` 须逐项可证相同，两轮均须完结；来源为沿用、迁移发布或不唯一均拒收。
   - **部署准入**：从沿用轮的 `outcome.json` 取 `reused_from.admission`，按该轮冻结 `controller_code_head` 所对应的发布器合同核验。`admission.controller_code_head` 须等于该轮冻结身份；非空 `admission.image_id` 须符合当时合同规定的格式，并与原双审轮**两份**原始审查员 `receipt.json` 的 `image_id` 逐字相等。该冻结合同若要求 `isolation_contract` 等其他准入字段，须按当时合同核其格式和绑定；要求与回执匹配的字段（如 `isolation_contract`）须在 admission 和两份原始回执中均存在且逐字相等。合同不可证，或当时任一必需字段缺失、不可读、不合合同或与任一原回执不合，均记 `REVIEW_FINAL_PRODUCT`，不拿现役新增字段倒套旧格式。现役依据：同文件 `:762-778, :774-794, :1027-1039`；历史依据：[冻结 controller b5cd3fee 的镜像准入与比较，第 730–757 行](https://github.com/Newchanlun/NewChanlun/blob/b5cd3fee352e5f7199233de628da05ff06c5798f/.sandcastle/deepagents-pilot/pilot1742/external_review.py#L730-L757)（第 745–757 行核两份旧回执，不要求 `isolation_contract`）。
   - **补丁身份**：两端分别从 Git 重算当前 `merge-base(M 第一父,H)` 与原审 `merge-base(B_orig,H_orig)`，两者都须唯一并与各自登记的 `merge_base_sha` 一致；仅当前 merge base 须等于 M 第一父。冻结的 `B_orig` 与原 `merge_base_sha` 是两个字段，不要求二者相等（如 #2043）。对各自的 merge base 与 head 用 `git diff-tree -r --raw -z --no-renames --no-abbrev <merge-base> <head>` 取逐路径改动的前后 mode 与 blob 清单；用其原始字节重算完整 `patch_id`（`sha256:<64 位十六进制摘要>`），两端、两轮登记均须相等且摘要前 12 位等于 `p`。`B_orig` 须在 M 第一父的第一父链上；逐相邻提交取主线变更路径，与补丁涉及的路径求交，必须为空。补丁身份见同文件 `:1-12, :262-265, :545-552`。
   - **沿用否决与完结性**：从正式 App 完整枚举该 PR 的全部登记（含被替换的 head），读其 `target.json`、`outcome.json`、原始审查员回执及最终消息，并逐 head 核已固化的 GitHub 完整分页与其原件（仍可读的实时状态另行对账），按完整 ID 将正式状态对应到登记而非按 head 或前缀猜 PR。用登记的冻结对象核同 PR、同 `patch_id`。历史、补丁身份、时序或完结性不能证实，不沿用。合入截止点前，任一同补丁轮有任一审查员 `BLOCK` 即否决（包括汇总发布 `failure`、`BLOCK+FAILED` 发布 `error` 或只留下 `STALE` 原件）；任一同补丁轮未完结也否决（须有汇总且已派发者各有可读回执）。只按下述锁内持久化顺序选最新合格的真实双 PASS 并判取代：原审登记之后的任一同补丁非 `PASS` 裁定（含 FAILED、`failure`、`error`、`STALE` 或未完结）均取代旧结论，不能复活旧绿灯。已在截止点前完结的 PASS 不因其先前的 `pending` 记录被否决；只有可证早于原审持久登记、已完结且无任何 `BLOCK` 的 `error` 或未发布终态的 `STALE` 才不取代后来的真实双 PASS。
   - **锁内持久化登记顺序（#2131）**：现役先在锁外调用 `_frozen` 取本机 `registered_at_ns`（同文件 `:527, :558`），后持 PR 锁写 `target.json`（`:541-542`），而沿用排序读该时间（`:727-752`）。修复后，登记方在同一 PR 锁内将递增登记序号与冻结 run 身份作为同一持久化登记提交，序号按本仓同 PR 单调分配，跨 head、attempt、patch 和进程不可复用、回退或重排；失败或崩溃后从持久原件恢复，不补写假顺序。登记原件 `ReviewRegistrationOrder`（5 键）：`{repository_id:integer,pr_number:integer,patch_id:string,run_id:string,registration_seq:integer}`；`registration_seq` 为正整数，patch 与 run 身份按本步核。沿用发布前在同锁内以持久账本的最新水位枚举、重验并绑定该次发布；固化覆盖区间、水位及原件，独立复验按完整登记重算。缺记录、冲突、无法证明完整性或缺锁内单调顺序，一律不可沿用；包括只有锁外 `registered_at_ns` 或只有可见性上界的历史记录。发布器此时走当前独立双审；对已经合入的历史沿用不得倒补顺序或改写旧发布，按证据缺口／确定性违规留红。
   - **其他历史 head 的截止点**：持久登记相对合入秒的先后要另用可核服务端时刻原件证明（锁内持久化前后的可信服务端时刻可给出上下界），不能由序号推出 UTC 或用锁外本机时间。任一同 PR、同补丁登记与合入同秒、无法排除同秒，或归组后正式 App 的否决状态（`failure` 或 `error`）的 `created_at` 或 `updated_at` 与合入同秒，均拒绝沿用，记 `REVIEW_FINAL_PRODUCT`；不以数值 ID、纳秒或分页顺序消歧。只能排除可证严格晚于合入秒的竞争或否决；截止前的回执/裁定若无法从原件判定时序，拒绝沿用。历史 `failure` / `error` 的完整 run ID 若唯一绑定同 PR 登记，且从冻结 Git 对象重算确定为异补丁，则排除该状态，不因其本地缺终态 `publication` 拒绝沿用（如 #2025 的状态 58409480743）。H 上仍适用第 2 步更广的同秒门。原件枚举、否决、完结性及发布分流见同文件 `:636-662, :664-689, :692-699, :710-752, :1027-1040, :1089-1097, :1114-1125, :1224-1229`。
   - **无终态发布的同补丁旧轮**：借沿用轮的正式 `success` 作为旧轮 X 的完结上界前，须证明 X 在该轮持同一 PR 锁枚举历史前已落盘可见。可接受的独立证据二选一：
     1. X 在完整 `head_sha` 上的 GitHub `pending` 由正式 bot 发布，以完整 `run_id` 及状态 ID 绑定 X 的 `target.json` 与本地 `effects/status-pending.json`。其服务端 `created_at` 严格早于沿用轮自身已绑定的 GitHub `pending`（或 `success`）的 `created_at`。此证据要求核实 X 的冻结发布器先在同一 PR 登记锁下持久化 `target.json`、再发布 `pending`，且沿用轮从枚举到创建所比较的状态持续持有这把锁。例：#1949 的旧轮 `pending` 58402803627（08:12:38Z）早于沿用 `pending` 58405163765（08:57:08Z）和 `success` 58405166812（08:57:12Z）。
     2. 沿用轮的冻结发布器写出的可验证锁内枚举清单明确包含 X 的完整 `run_id`，且清单唯一绑定此次沿用发布。

     不论取哪种证据，仍须核该沿用轮冻结 `controller_code_head` 对应的代码确在该锁内重读历史、核验 X 所在集合的完结性及否决后才正式发布，并逐轮读原始汇总、回执和最终消息核否决。只有如此才能以该沿用 `success` 的服务端 `updated_at` 为 X 的完结上界（须严格早于合入）；这只证明完结上界，不证明 X 与原审的登记先后，仍须核锁内单调登记原件。缺独立可见性证据或锁内核验不可证，记 `REVIEW_FINAL_PRODUCT`，不以文件 `mtime` 或先取后写的本机 `registered_at_ns` 猜测。现役登记、枚举与锁内发布见同文件 `:527-558, :570-580, :710-752, :1027-1039, :1089-1097, :1224-1229`；#1949 见 [b5cd3fee 登记与 PR 锁，第 527–548 行](https://github.com/Newchanlun/NewChanlun/blob/b5cd3fee352e5f7199233de628da05ff06c5798f/.sandcastle/deepagents-pilot/pilot1742/external_review.py#L527-L548)、[锁内重验，第 963–969 行](https://github.com/Newchanlun/NewChanlun/blob/b5cd3fee352e5f7199233de628da05ff06c5798f/.sandcastle/deepagents-pilot/pilot1742/external_review.py#L963-L969)。

**合入入口门（#2131 冻结前上线）。** 现有 `.sandcastle/deepagents-pilot/pilot1742/review_sweep.py:236` 只返回结论（第 240–246 行丢弃状态时刻），`.sandcastle/deepagents-pilot/pilot1742/review_sweep.py:730` 进入直接合入分支（第 731 行发出调用）。#2131 须将以下门接入该入口及所有获准自动／人工合入入口；未经过同一门的入口不得用于本图存续期间的 main 合入：

1. 串行控制所有自动／人工入口，从当前可信账本头读回写锁状态。重验精确 base/head、PR 及全部 review 历史；在预合入快照中按上文 R09 截止快照的状态排序规则先选当前最新条目再验，核正式 `success` 的服务端 `created_at` 与 `updated_at`。以新鲜、非缓存的 GitHub 服务端 UTC 时钟秒为准，至少等到当前秒严格晚于该状态创建与更新时间才可发起合入（验收以实际 `merge_second > status.created_at` 且 `merge_second > status.updated_at` 为准）。等待后重读，最新条目或 base/head 变化即重验，不凭本机时钟或睡眠时长放行。请求前签章追加并读回 `merge_intent`，绑定该 PR／base／head、所选状态、完整预合入快照、原执行实例和唯一意图序号。签章前须确认 PR 源分支有获准的快进通道，且一旦建立第 3 步的 SHA 屏障便不能回到请求的 H；不能建立这一保障的源分支不得发请求。每个意图仅允许一次直接 `PUT /repos/{owner}/{repo}/pulls/{pr}/merge`，请求固定带完整 `sha=H` 及 `merge_method=merge`；禁止客户端自动重发、无 SHA 写入、原生 auto-merge 或 merge queue 替代。未归口时停止后续主线合入和开启验收窗口。
2. 请求后重查 GitHub，不用 CLI 退出码判实际结果。只有下列证据之一齐备才追加并读回与意图唯一匹配的 `merge_terminal`：
   - **`CONFIRMED_NOT_MERGED`**：保存该请求的服务端终结且不执行的拒绝响应原件（含状态码，如带 `sha` 的请求因 head 漂移返回 HTTP 409，见 `.sandcastle/deepagents-pilot/pilot1742/review_sweep.py:276-279`），以及拒绝之后新取的 PR 仓库／号／state、`merged=false`、base ref 与实际 head、`main` 顶端原件。须确认没有实际合入且主线仍为意图基线；head 可与请求不同（409 时照录漂移后的 head）。保持原意图，终态 `merge_commit=null`，不创建 R09 主线集成或 R11 push 偏差行；读回后按原有门恢复正常合入，新请求重新预检、使用新意图。
   - **`MERGED_PASS` 或 `MERGED_VIOLATION`**：从实际已合入 PR、`main` 与 Git 第一父链独立核实 M、PR 与服务端 `merged_at`。严格跨过实际合入秒后重读稳定的完整历史，核预合入至截止点的条目未消失、不以更新后的记录替代原件；按 R09 第 1–3 步复算，并核 M 的两父分别为意图 base、head，截止点所选状态 ID 与预检值一致。保存请求响应（若可取）、实际 PR／主线原件和合入前后两批证据；终态唯一绑定 M。完整原件满足全部判据才记 `MERGED_PASS`；完整原件明确证实同秒创建／更新、截止状态变化等确定性违规，记 `MERGED_VIOLATION`，对 M 输出 `REVIEW_FINAL_PRODUCT`。不能定位真实 M、不能重建同一截止点或原件不完整时仍未封口，记 `SOURCE_UNAVAILABLE`，不能写违规终态换取解锁。
3. **结果未知：先查实际合入，再使旧 SHA 失效。** 超时、断网、发出前崩溃、响应不可归因或 PR／主线不一致都不算拒绝（当前入口将写超时列为 `write-unknown`，见同文件 `:207-213, :730-742`）。保留原意图并持锁，禁止重发。受信控制面按意图的实例身份证实原执行进程和写入子进程已退出且不会重新派发；不能只看 PID 或本机等待时长。用新鲜的 GitHub PR 原件、`main` ref 与第一父链检查实际 M；若已有合入，按第 2 步的已合入分支求值。若取得可归到本请求的服务端终结未执行原件，按第 2 步如实写 `CONFIRMED_NOT_MERGED`。
   - PR 未合入、主线仍为意图基线但没有拒绝原件时，在主线写锁内将**同一 PR 的原源分支**快进到 H 的严格后代 H′，只改 PR 分支，不向 main 写入。已在该源分支安全快进的 H′ 可直接核验。归档完整 H/H′、源仓库和 ref 身份、快进对象关系以及源 ref 防回退、防删除重建的控制证据；从该次推进起不得再使这个 PR 的 head 回到 H（拒绝 force-push、删建、换源或任何恢复旧匹配的动作；若不能保证，不能用这条路径解锁）。只关 PR 后读 `closed` 不够：后续重开可重新匹配 H。
   - 新鲜 GitHub 回读须证明同一 PR 的 `head.repo.id`、`head.ref`、`head.sha` 和实际源 ref 一致，已切到 H′，再核 `merged=false`、base 仍为 main、`main` 顶端仍为意图基线且第一父链没有本意图的合入；末次再读 PR，确认无竞争合入或身份漂移。若原请求抢先执行，则实际 M 优先，不能以进程退出或快进遮盖。只有屏障及屏障后的 PR/main 回读均可验证时，才可凭 [GitHub 合入端点的 SHA 前置条件](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request) 证明旧请求今后不能成功：服务端执行合入要求当时 PR head 等于请求的 H，而同一 PR 已永久离开 H。仅本地新提交、只读到 PR 未合入、源 ref 与 PR 回读尚未一致、无法约束退回 H，均记 `SOURCE_UNAVAILABLE`，继续持锁。
   - 对证据齐备的未知请求，签章追加并读回 `merge_terminal(result="SUPERSEDED_UNKNOWN_INTENT",merge_commit=null)`，附原执行实例退出、SHA 屏障及之后的 PR、源 ref 与 main 回读原件，独立重放验证后解锁。原意图永远保留，不声称原请求收到拒绝、不写虚构响应或 M，不产生 R09 集成行或 R11 push 偏差行。针对同 PR 的新请求必须使用合规的新 head 和独立预检及新意图；其他 PR 同样恢复正常入口。
4. **已证违规归档后仅解锁修复。** `MERGED_VIOLATION` 签章封口后，控制者将对应 M、完整原件与 #1551 下可验证的具名后续处置裁定绑定，显式追加并读回 `violation_archive`；裁定须明确范围并列出获准的针对性修复或新基线评估票。独立复验该 M、终态、违规和裁定后，只解除此违规的写锁，且只允许清单内的修复／评估 PR，仍须走原有分支保护、正式非作者双审、必需 CI、strict 及本入口的全部取证门。其他未封口或未归档事项仍各自持锁。归档不删除、不撤销 M，不使原窗口复活；M 及其失败在所有仍遍历 M 的 F 报告和 #1403 回执中保留，并继续阻断 AT-18 关图。不同 F、修复 PR 合入或新基线评估本身均不核销该失败；如需另订基线，走独立的正式合同裁定并保留本版历史失败，不在本版跳过 G0..F 中的 M。

合入留证的封闭类型（在共用账本的序号、仓库 ID、版本外层内，不增加三份验收文档的顶层键）：`HistoryOriginal`（3 键）`{role:string,locator:string,sha256:Sha256Hex}`。R09 的角色、相对定位及原件字节摘要按独立部署解码合同验证；R11 的角色按阶段二合同验证。原件组按各自角色核完整性，不能用一份自报结论替代。R09 四种记录载荷为：
- `MergeIntent`（6 键）：`{type:"merge_intent",pr:integer,base:GitCommitSha,head:GitCommitSha,status_id:integer,originals:HistoryOriginal[]}`。身份为该条正整数账本序号；原件绑定预合入 PR、main 与完整快照。
- `MergeTerminal`（5 键）：`{type:"merge_terminal",intent_seq:integer,result:"CONFIRMED_NOT_MERGED"|"SUPERSEDED_UNKNOWN_INTENT"|"MERGED_PASS"|"MERGED_VIOLATION",merge_commit:GitCommitSha|null,originals:HistoryOriginal[]}`。每个先前意图最多一个有效终态；仅两种已合入枚举允许且要求非空 M。原件依上款绑定本次请求／核实结果与同一 PR；适用的响应状态码、服务端时间、PR state/head 与主线 ref 从原件读，不凭终态字面放行。
- `ViolationArchive`（5 键）：`{type:"violation_archive",terminal_seq:integer,repair_tickets:integer[],decision:HistoryOriginal,merge_commit:GitCommitSha}`。终态必须是对应同一 M 的 `MERGED_VIOLATION`；每违规终态只归档一次，修复/评估票非空、升序、无重复且与正式处置原件一致。归档条目不改变终态；#1391/#1403 按原件计算 R09 失败，不从归档状态推断通过。
- `HistoryBaseline`（5 键）：`{type:"history_baseline",commit:GitCommitSha,pr:integer|null,state:"EVIDENCE_READY"|"SOURCE_UNAVAILABLE",originals:HistoryOriginal[]}`。仅用于部署原件所定的新入口前区间；PR 未核定填 null，`EVIDENCE_READY` 要求 PR 已核且全部冻结原件齐备，不等于第 1–3 步通过。同一 M 只允许一条初录及从 `SOURCE_UNAVAILABLE` 到 `EVIDENCE_READY` 的一次追加补齐，旧记录保留；证据冲突、重复补齐或区间外使用均拒收。

**冻结前逐笔清查基线，而不是补造旧意图。** #2131 按 Git 第一父链枚举截至 `origin/main@0e29d008f766a82a05898244caf5a30924f24b51` 的 45 笔（含 G0），以及此后至新入口生效前的全部过渡笔（含尚未走新入口的实施 PR）。逐笔核两父／同树、实际 PR、H 与 `merged_at`，再从正式 App 原件和 GitHub 全分页交叉核查可见的状态与裁定。每笔都登记已核字段、出处和未能证明的范围；不根据时间、目录或现存 `success` 声称全历史完备。

- 能从独立、同一截止点的可信留证重建全集（例如当时已固化的完整状态页与评审发布档案，或覆盖全体同 context 作者及相关 head 的连续归档，带可复验的起止、水位和完整性证据）时，登记 `EVIDENCE_READY`，保存原始页链或可验证原始归档与当前分页的对账，并按同一第 1–3 步验证；不能用只覆盖 App 自身的日志代替全作者的状态证据。已知实际违规仍按 `REVIEW_FINAL_PRODUCT`，不记来源缺失来掩盖。
- 无法证明旧状态的截止点或完整性时，保留所有可证事实，登记 `SOURCE_UNAVAILABLE`；明确缺件与不可恢复原因，不把未知写成无删除、通过或未合入。清查完成即可交付 #2131 的入口和清查成果；这类历史缺口不持新入口写锁。正常合入用新协议，原 AT-18 窗口仍不得冻结／放行：可取得当时原件则追加补齐；经查确实不可恢复，由主控走 #1551 下独立的正式基线裁定，明列每个 M、未知事实及新基线如何证明留存产品。若变更验收区间或证明义务，须在另版合同明示并获正式独审后才能按新基线验收，不回填本版历史 PASS、不在本版跳过任何 M。

冻结前独立对账：第一父链每笔须唯一归入基线／过渡或新入口；前两者按上述状态有完整清查处置，后者须有归口的实际合入记录与固化原件。只有本版 R09 全部通过且无未决写锁才可开窗；保留配置读不到或不存在不可取得的删除日志，不妨碍先完成逐笔清查和交付入口。

证据源不完备时用 `SOURCE_UNAVAILABLE`；完整原件证实违反集成、时序或审查条件时用 `REVIEW_FINAL_PRODUCT`，不改走 R10。报告按第八节记录可定位的所选状态；同秒碰撞或完整性不足无法选定时不造 ReviewRef。违规归档后仍按 `commit:<M>` 留确定性诊断；只有意图序号、尚未知 M 的采集缺口按 `merge_intent:<seq>` 记录。G0 后的 squash、直接推送或异树合入不能满足本图的最终独评证明；main 应循同树 merge 入口（现有合入调用见 `.sandcastle/deepagents-pilot/pilot1742/review_sweep.py:276-279`）。

### R10　闸前：按主线落地、留存路径与 blob 身份补审

#2132 交付闸前来源清册及可重放的枚举程序。先从完整 Git 历史枚举 P0 的全部第一父提交；从 GitHub 分页取 #1359–#1368、图 #1323 与其 SPEC #1340 的原生实施子树（含各 TB 汇总、带 `wayfinder:impl` 的原生实施子票及图直属实施产品与其实施子树）、#1493 在 #1360 下的改挂，以及对这些产品有正式承接/归属的补修、恢复、测试和报告尾件。原生关系只定义考察范围；引用、依赖或触及相同目录本身不是产品归属证据。逐场景从实际 Git 第一父差异、匹配其 merge SHA 的本仓 main PR、票面交付／承接原件核实 `(ticket, M)`；一提交可有多票归属。不能因票仍开、已关、重开、改挂、无 PR 或仅为文档而排除实际落地；PR 未合或 merge SHA 不在 P0 第一父链不计。不能用关票时间或提交作者时间取代第一父归属。

清册须归档（1）遍历的完整 P0 第一父链；（2）原生范围、源码与 GitHub 关联出处；（3）逐一处置命中的候选或交付声明，及对范围内没有归属标记的新增/替换路径与未分配用途的交付扫尾结果；（4）全量 `(ticket,M)` 与每个 M 的原始第一父差异。结构化关联优先采用 GitHub 实际合并记录与明确指向交付物的 Git/票面原件；非结构化命中由 #2132 在获审清册逐条给出处及纳入/排除裁决。#2132 的正式独审须逐 TB 对已落主线的成果对账，交叉检查 PR 与票面原件，并核无归属标记的历史改动；名字、目录、搜索结果或旧表都不能证明完备。图外票的正式承接用对应 TB／图的实际义务归并，独立列来源票；不把图外整票改成阻塞边。发现新出处或歧义先记 `PREGATE_LANDINGS`；由 #2132 在正式合入门补齐清册及复审，不得由调用方覆盖。每端自行从固定来源原件、P0 与 F 核销清册覆盖及重算差异；只给一列 SHA 或 PRE 打满 PASS 不够。#1493 缺已裁的改挂也记 `PREGATE_LANDINGS`。

每端先独立重算实际落地票／提交全集，再逐来源票生成 `attribution_scopes`：从票自身沿清册已钉住的原生父链取第一个 `#1359..#1368`（含汇总票本身）；#1493 的改挂必须按上段核实。原生 scope 只查此表，不按票号连续推导；第八节用同一映射。映射取发布正本 `.chanlun/review-results/issue1340-publication-20260909/view/tickets/1323-UPDATED.md:80-92`。TB-11 行仅用于汇总身份，不进入 R10 的 `LandingScope`。

| 汇总票 | TB |
|---|---|
| #1359 | TB-01 |
| #1360 | TB-02 |
| #1361 | TB-03 |
| #1362 | TB-04 |
| #1363 | TB-05 |
| #1364 | TB-06 |
| #1366 | TB-07 |
| #1367 | TB-08 |
| #1365 | TB-09 |
| #1368 | TB-10 |
| #1369 | TB-11 |

将原生 scope 与清册 `attributions` 中该票的已裁非原生 scope 取并集；无原生 TB 必须恰有一条显式映射，只有有据可查的图级/联合义务或仍不可分切的图直属产品可裁为 `["GRAPH"]`，不是漏映射的默认值。清册行不得给原生 TB 票填 `GRAPH` 或重列其原生 scope。多 TB 是已裁的多个 TB scope，不折叠为 GRAPH。由 #2132 非作者正式独审逐项核现有产品的归属及出处；不得从代码目录、关键词、共享提交、关联声明的自由文本或当前票态推导 scope。映射缺失、多余、重复、超域、原生父链矛盾/循环或出处不成立，均记 `PREGATE_LANDINGS`；无法核实归属的票不进 Destination 投影，不删除其 R10 落地或留存路径。在同一已核原件上，任何状态翻转都不得改变票／提交关系、scope 或 PRE 路径。

对每一唯一 M 枚举完整第一父原始树差（`git diff-tree -r --raw -z --no-renames --no-abbrev <M第一父> <M>`），以 Git 路径字节及完整 Git 对象身份为准，不按目录、后缀或 rename 相似度过滤。PRE 是以下两组历史来源元组 `(path,mode,blob)` 的并集；同时用 F 的完整叶树记录每个元组的全部匹配目标：
1. **同名留存**：闸前差异路径与 P0、F 的叶路径集相交，取对应 P0 元组；F 同名内容即使改过也须复审 P0 的原正文。
2. **对象留存**：对每次 M 引入或修改的非删除后像，从 M 树取该元组；其完整 Git blob SHA 只要在 F 的任一叶路径出现，即纳入 PRE，包含纯改名、搬移、复制，甚至该对象在 P0 已不在原路径或已不在 P0。F 的匹配不受路径和 mode 限制；逐一对账全部目标，不为每个副本重复评审相同来源元组。源路径删除且其对象在 F 无任何匹配、也不满足同名留存时不入 PRE，仍保留历史树差。

对 P0/M 的来源元组及 F 的匹配路径重算模式、对象类型和完整 SHA；所需非 blob 条目留红，符号链接审链接 blob 本身、不解引用。闸后对留存路径或对象的任何相关集成仍独立过 R09。登记的 `pregate.landings` 对齐重算的票／提交全集和逐票 `attribution_scopes`（错配记 `PREGATE_LANDINGS`）；PRE 的登记键集与重算的完整历史元组集合严格相等，每行须 PASS。清册、登记、PRE 在 F 第一父链最近新增或修改的提交均须通过 R09；`owner_ticket=2132` 且 #2132 为 `CLOSED/COMPLETED`。F 的留存改变导致集合或复审射程不符，先正式更正登记再取验收 F。

**正文复审。** #2132 的 PRE 登记版本须由非作者直接双审。逐项在正式审查输入中提供来源 Git 提交、路径、mode、完整 blob SHA 及由该对象读取的完整正文（同一 blob 可共用一份正文）；两份独立原始回执与其绑定的审查记录均须能定位每个元组、确认实际复审覆盖该对象的完整字节并通过。两端以 R09 正式回执绑定实际获审登记版本，从 P0/M Git 对象对账所审内容，不从 F 的路径名或自报 PASS 推断。现役补丁提取 `.sandcastle/deepagents-pilot/pilot1742/external_review.py:343-348` 的纯 rename/copy diff 可无正文，不能作此证；只有路径、摘要、改名元数据、部分上下文或未定位到正文的双 PASS 均不够。缺项或不合记 `PREGATE_REVIEW`（`pre:<历史来源 Git 路径>`）。

边界反例：PR #1553、#1571 均归 #1405，不被其关票尾件 #1574 吞掉；#1394 的 #1583 是正式尾件；#1359 与 #1372 可共指同一主线提交。#1406 的 PR #1616 在 P0 第一父链上，即使 #1406 尚 OPEN 也必须纳入；后续恢复、校验或补修产品按同一规则重算。任何示例和作者快照的计数都不是分母上限。#2132 的清册及 PRE 是整图共用门；`GRAPH` 来源仍走同一整图门，并按第八节列作所有 Destination 的出处，不成为任一 TB 自身的原生子票。

**#799 / #804 举证。** `postLanding(M)` 是 G0 起的集成事件，证明送入 main 的完整树经过正式应用门；`preResidue(path,mode,blob)` 是按 F 同名路径或存活 Git blob 重算的 P0/M 历史基准字节，须有非作者完整正文复审。两份输入由 Git 与来源清册先算、分别验、最后取合取。即使某一闸后 M 触及同一路径或同 blob，缺其 App 状态依然失败；同样，闸后全绿也不补 PRE。相同 AT-18 行为义务在 F 上统一执行 R02–R08，不按历史或 TB 级别切换判据（`docs/agents/doctrine-rules.md:43-55, :61-79`）。

### R11　把历史留在历史

**采集范围与封存。** #2131 冻结前在可证未过期、无删除缺口的窗口内，将 `G0..F`（含两端）所有第一父提交的 `ci.yml`、`devskim.yml` main push run/attempt 全量清单及 R10 所需闸前 M 的同类原件固化到 R09 历史证据链。#2131 落地后每笔合入立即启动采集：按实际 M 与 workflow 身份持久记录触发结果、全部 run 与各次 attempt、服务端时刻、完整页链、结论及分页作业／步骤原件；触发分发未决不能封成零，随后新增 run 或 attempt 只追加并保留旧尝试，冻结／关窗前再取完整清单与实时对账。明确的零运行按 M 与工作流登记，须附该 M 实际适用的 workflow 触发条件和主线变更等独立原件，证明路径未触发。采集端用 Actions 实际适用的保留期及删除／留证原件排除缺口（近／超为距可证最早失效点不超过 24 小时，含已过期）后才封存；已丢失且无有效的既有固化原件记 `SOURCE_UNAVAILABLE`（包括闸前），不得倒填空。

失败、取消、超时或其他异常终态的 attempt，封存前须同步保存原始作业日志或结构化测试结果（如 JUnit 或测试框架输出），连同 Jobs 原件定位每个实际失败、中止或异常步骤。一个步骤可运行多个测试（`.github/workflows/ci.yml:432-440`）；对运行了测试的步骤，须保存足以确定全部实际失败用例的原件（测试目标／套件和完整用例标识，不能只存日志片段或失败数）。无测试失败或作业未启动也须由执行／调度原件证明，不能从步骤名或缺日志猜出空集。无测试步骤异常须固化能定位其失败条件的原件；尚在运行的尝试只记观测，不封作完毕。绑定载荷 `CiStepEvidence`（7 键）为 `{run_id:integer,run_attempt:integer,job_id:integer,step_number:integer,step_name:string,kind:"JOB_LOG"|"TEST_RESULT",original:HistoryOriginal}`：作业与步骤身份从该次分页 Jobs API 核对，`original.sha256` 绑定原件字节，同份作业日志涉及多个步骤时逐步骤绑定原件内的实际定位。若根本未获分配 job／step，用同 attempt 的服务端调度或取消原件证明未执行，不伪造 job/step id。原件必须足以确定异常位置与失败用例（或证实无测试可列）；缺失、过期、截断或身份错配一律记 `SOURCE_UNAVAILABLE`，保留已证尝试行但不得以步骤级成功声称逐用例已复验。日志／测试内容只供独立定位与复验，不进入成品报告的自由文本或诊断字段。

**报告范围与逐次投影。** 闸前分母为 R10 重算的全部 `(ticket,M)`；闸后遍历 `G0..F` 的每个 M，以 R09 核实的实际 PR、第一父差异、GitHub 原生关系与正式交付／承接原件按 R10 的归属证据规则重算（不沿用 R10 的 P0 截止，也不修改其 PRE 或 Destination 历史出处）。凡交付本图产品、正式承接的修复、配置、测试或实体报告尾件，按实际来源票列入全部归属；共用 M 每票一条归属，只引用本图但未交付的或已证图外 M 不入偏差报告，即使其原件仍须封存。关联不清不默认图外，记 `HISTORY_ATTRIBUTION`；全区间的来源缺口不因归属待定或图外而免除。

#2132 逐 M 将原件交控制者在 R09 历史链签章登记 `PostGateLanding`（6 键）：`{type:"post_gate_landing",commit:GitCommitSha,pr:integer,classification:"GRAPH_DELIVERY"|"OUTSIDE_GRAPH",attributions:PostGateAttribution[],originals:HistoryOriginal[]}`；`PostGateAttribution`（3 键）：`{ticket:integer,attribution_scopes:LandingScope[],originals:HistoryOriginal[]}`。分类及每票归属分别在外层及对应条目的原件组绑定非作者核过的正式原件（图外含排除裁据）；本图交付按票号升序列出非空、互异的归属，TB／GRAPH 的求值与 R10 相同；图外的归属数组固定为空。原件只按及至 M 的已交付内容和对应正式关系／处置作证；票在窗内换态不重分配。两端用固定的原始来源独立核对全区间及归属，不信分类字面、不读 PR 标题/票态猜归属。后置记录以已知 M 为键，不要求包含 M 自己的受审 Git 树预写未来提交 SHA。

对每个 M 的两个工作流，从服务端最新 `run_attempt` 遍历该 run 的 1 至该编号，按 Actions 的 `GET /repos/{owner}/{repo}/actions/runs/{run_id}/attempts/{attempt_number}` 与分页 `/jobs` 核 `workflow_id`、`head_sha=M`、`head_branch="main"`、`event="push"`、run id、attempt、结论及作业步骤，并与固化证据逐一对账。无有效清单时无论实时列表是否为空均留来源失败；作业／步骤不全记 `SOURCE_UNAVAILABLE`，已证的行不消失。对报告分母内每个 `(ticket,M)`，每个实测非 `SUCCESS` 尝试写一条第五节六键 `HistoricalDeviation`：`commit=M`，`workflow` 取仓内路径，已知身份但结论不可证写 `UNKNOWN` 并记来源失败；证实未完成写 `INCOMPLETE`。按工作流确证零才写 `NO_RUN`，不造尝试 ID。首次失败、再次失败和后续成功各保留于历史链，成功不入偏差数组、不改写任一失败行；同一 run 重跑成功或后续修复提交不是自动核销证据。历史行不进 F 的 `ci_runs`。

**零运行不等于未见运行。** 仅当有效持久清单与完整实时查询均证实为零，且（a）仍在可证未过期窗口内、无删除缺口，或（b）固化清单与绑定原件已证合入／关窗时确为路径未触发的零运行、无删除缺口，才按工作流记 `NO_RUN`（两 id 为 `null`）。实时分页为空却无有效清单，或已近／超保留期、保留期不可读而无（b）的零运行证据，一律记 `SOURCE_UNAVAILABLE`，不造 `NO_RUN` 行。持久清单记过的 run／attempt 在实时 API 缺失时，只有具备该尝试的固化原件，且本图归属另有对应的合规 F 复跑证据，才能消除来源阻断；否则 `SOURCE_UNAVAILABLE`，既不抹掉已证偏差也不放行。分页不全或接口失败不是零运行证明。

**逐次核销。** 对报告分母内每个 `(ticket,M,workflow,run_id,run_attempt)` 的已结束非成功尝试，逐一关联全部实际失败测试及无测试异常步骤或中止条件，并在 F 经 R05/R06 审定的选择器实跑同一测试（唯一、执行 1 次）或同一步骤、同一失败条件；未启动的取消等须复跑原件定位的受阻入口和未完成条件，不得虚构失败用例。完整证据可证明是由某步骤传递导致的聚合失败时，按实际失败步骤核销，不给每个下游跳过步骤造新失败。不能定位、仍未完成、缺登记或 F 未实跑成功记 `DEVIATION_NOT_CURED`；原件缺失、过期或无法确定实际失败用例时并记 `SOURCE_UNAVAILABLE`。对实时缺失的已知尝试，仍按上段的固化原件和对应 F 复跑条件核对；对已固化成功的本图尝试，如实时已不可见，复跑已证执行的步骤和条件，不造偏差行。图外尝试只核来源／完整性，不产生本图 cure 义务。R08 的通用绿灯、在历史 M 上随后重跑成功、另一修复提交的 CI 绿灯，都不能代替 F 的对应具名实跑。后续修复提交本身仍按 R11 独立归属、报告其自有失败；其新测试实现可作为 F 复跑载体，原偏差仍归原票和原 M。

闸前 cure 沿用第五节 `Landing.cure_checks`，每项按该 attempt 原件唯一定位实际目标；同名目标跨步骤不唯一时先用作业／步骤与测试目标全名消歧。闸后由 #2132 提交控制者在受保护历史链按次签章登记 `PostGateCure`（12 键）：`{type:"post_gate_cure",ticket:integer,commit:GitCommitSha,workflow:string,run_id:integer,run_attempt:integer,job_id:integer|null,step_number:integer|null,step_name:string|null,kind:"test"|"step",target:string,check_id:string}`。只有服务端证实在分配相应作业或步骤前中止，才将尚未获分配的身份填 `null`；`target` 对测试取可唯一定位的完整用例标识，对步骤或未启动条件取 R03 合同钉住的稳定定位。每行匹配其实际归属、精确失败原件及 F 获审登记册中可运行的 `check_id`，以 `(ticket,commit,workflow,run_id,run_attempt,job_id,step_number,kind,target)` 唯一校验；登记不能取代两端重算的完整目标集合或 F 上的成功见证。同一真实 F 见证可核销多个独立登记行，但不得合并失败尝试或改变偏差行归属。三项固定闸前锁的两 id 均为 `null`；原运行过期也不免除，固定锁不代替按次留证与复跑。

| 历史票 | main 落地提交 | 不可删的具名 cure（即使原 run 过期） |
|---|---|---|
| #1392 | `8619a20f2800095e6bb9ec20ba2607a744740f91` | `m3_partition_synthetic_holds` |
| #1404 | `f95a7f3ebc0ce84ec2d2f8a8d71b5030b19f89b9` | `calibration_sweep_finds_non_collapsed_segments` |
| #1414 | `465174240b989a1d99f99a047fbb46b3ee215f49` | `seam_btc_tick_bars_yield_non_trivial_structure` |

#1414 及 #1493 所涉 30 秒公用读契约仍由 #1360（含缺陷 #1497 对应承接）在 F 测，不用旧夹具放宽替代。实测历史红灯与未定位的 cure 缺口列在起草证据；不据该快照预填成功或把未观测写成 `NO_RUN`。

### R12　TB 与逐键归并

TB-11 前置门只读 F 上 `.sandcastle/` 中两个普通非空 blob：`at18-report.mts`（#1391 的生成器）、`at18-verification.mts`（#2131 冻结前交付的独立验证器）；另核第三节已先登记且合法的 `input_bundle`、R08 与 R09。缺条件记 `TB11_PREFLIGHT`。不读本轮报告、总验回执、后续关票状态或 Destination 结论；不要求 #1403 已派工。

R02 从 `IMPLEMENTATION-CROSSWALK.json` 展开 TB-11 的 113 个键（`story=6`、`family=84`、`detail=23`）；`(story,US-ENG-10,TB-11)` 是 `US-ENG-10` 唯一关闭键。其余 112 个键在报告阶段按前置门归并，最终关闭仍须通过 #1403。按 `.chanlun/review-results/issue1339-r2-spec-20260909/payload/spec/SPEC.md:238`，#1391 另须在报告中构造 `evidence_by_kind`，显式分列程序、证明、UI、场所证据。四类只从 R03 获审合同钉住的来源角色、实际字段与原件定位独立计算，经 R05–R07 验证执行、证据类、profile 和封印后才入列；不得用自报分类、报告自身、同类标签或未运行的文档代替原件。

- `program`：完整程序或其受测组件的实际运行和行为验证原件。
- `proof`：规范要求的证明、形式接口对拍或独立 oracle 的实核原件，不用 PR 状态代充。
- `ui`：实际浏览器运行的交互与可观测输出，不用截图、文档或模拟的 UI 状态自报代充。
- `venue`：受测场所的权限、隔离和能力的实核原件，至少含有效的 `experiment` 证据；模拟或签署不能代替场所实测。

每类至少一份有效证据；本版 `production=null` 仅登记 #1561 未启用的槽位，不替代本图必需的 simulation 或 experiment 证据。按 R02 对应的规范义务及实际证据类核射程，不能把同一原件复制到其他类来凑数。#1391 只核分列所需的输入事实，不读生成后的报告：前置和所需证据均成立时，`US-ENG-10` 写 `PENDING_REPORT_VERIFICATION`、`deferred_gates=[]`，`evidence_refs` 只列合法的 `input_bundle` 引用；任一条件不成立则写 `FAIL`、`evidence_refs=[]`，即使前置已通过也不列输入包引用。缺有效证据按第八节记 `TB11_EVIDENCE_BY_KIND`。

#1403 在 #1391 封包关票后于同一 F 执行独立验证器，打开 #1391 manifest 所登记的实际报告 JSON，核四类是否显式分列、各类是否有合法且非空的证据、未启用槽是否如实标记，并与按原件重算的分列逐项对照。任一类缺失、空列、归类错误或以未启用边界代替必需证据，回执写 `TB11_EVIDENCE_BY_KIND`、`verdict="FAIL"`，不得核销 `US-ENG-10` 或关闭 TB-11。通过后保留报告的生成阶段状态不回写，由同一报告和输入包的独立 PASS 回执确认 `US-ENG-10` 最终核销。

每个非 TB-11 键须覆盖 R03 的每个 basis、每个域：必执行域过 R04–R06；涉及运行记录的同时过 R07；允许延期域只登记 R04 的具名情况。失败即键失败，无第二条路径。每个规范条目以其所有切片键归并：任一键 FAIL 即条目 FAIL；除按上文单列的 `US-ENG-10` 外，键全部非 FAIL 时按边界、合法延期、全部运行验证三者取 `PRESERVED_BOUNDARY`、`BOUNDED_DEFERRED` 或 `VERIFIED`，保留已验和延期的引用。无绑定的 TB-11 键不可加延期。

TB-01..10 逐 TB 要求：汇总票及每张带 `wayfinder:impl` 原生子票口径均为 `CLOSED/COMPLETED`（子票分母非空；票或集合不全分别记 `TICKET_NOT_CLOSED`、`SUBTICKET_INCOMPLETE`）；全部键非 FAIL（`TB_KEYS`）；R07 本 TB 相关专用门、封印实体、R08/R09 及本 TB 的 R10/R11 义务成立（R11 的本图归属按原生／已裁 TB scope 分派；GRAPH、图外来源不全或未能确认归属的阻断为整图义务）；在制品处置仍遵通用门。#1359 旧关票不回写；#2132 承接 TB-01 的新验收前置。其余 TB owner 关票前，在当时的主线头一次 dispatch 核自己的检查，报告阶段再在 F 全量重核。未关 TB 不使同一组 F 上成功的检查变红，但该 TB 门仍关闭不了。

### R13　旧票与 Destination 只聚合一次

旧票按第四节的七项原义务。状态、链接的原生子票和正式关票/授权事件向 GitHub 获取；行为取 R12 的键和 R07 原件。历史处分从本 ADR 第四节钉住的票、规范档及文书原件读，不以调用方的 `disposition_valid` 为真。#2131 给这些具名处分设置固定机读解码器：每项固定核准出处（Git 对象和 issue/comment ID），对相关原件用固定字段、行/段或完整字节 pin；漂移或无法解码即失败 `LEGACY_DISPOSITION`。

- #942、#1282 核已关闭且保留各自原处分；从附件及评论取原始出处，不给它们任何 F 运行命中。#1096 核 TB-10 的入口终态清单与 ADR 0048 退场条件；#1319 核 TB-08 的 feed/wire 决议和 TB-04、TB-09 的绑定实际结果。按第四节用同一事实生成处分、证据和未完清单。
- #1304 核 TB-07 对应键和 ADR 0058 AT-14 实体与锁；#1320 核 TB-07 对应键，重型测量另找七标的完整测量实体或具名有效废弃裁定，否则保留 OPEN 并按第四节延期。报告不接受「关票即测量已完成」。
- #1279 须 OPEN、无提前关图或放行。查实际 GitHub 票态及发布方正式记录；在读取完整评论时，对不符合第四节而明示放行的编排者声明也拒收，不能以缺正式格式把已有违规放行当作没发生。#2131 固定检查原件及其核实范围，无法确定时不得通过。剩余自有义务从 #1279 自有检查单按原稳定条目定位，排除 #1323/#1340 的全量义务；不能将本图失败项移入自有清单。

**具名裁定门是独立分母。** 从 R02 核过的每项 `destination_success_obligations[].success_gate_ids` 求该 DST 的门全集。当前 DST-01..06 分别都要求同一组：`FU-01`、`FU-02`、`FU-03`、`FU-04`、`FU-05`、`FU-07`、`G-001`、`G-002`、`G-007`、`G-025`、`G-026`、`G-028`、`G-029`（13 个身份、78 个 DST-门关系；crosswalk 字段位于 9567、10429、11112、11354、12186、12421 行）。逐项按 coverage input 的 ID 同源义务和《SPEC》具名残留表核其有效裁定；即使同 ID 又是 family 条目，family 通过也不能代替裁定门。

#2131 在 R03 获审合同中为全集每个 gate ID 固定唯一规则：钉住规范节点、裁定来源角色、正式裁定的 Git commit/path/段落或 issue/comment ID 与字节原件、授权类型、生效域、需核的落实证据及失效／取代判据。GitHub 裁定须读实际票及正式事件，核版本、来源、签署／非作者独审和有无撤回、取代或更改；引用归档的实际裁定字节，不以票状态、标签、规范中的待裁条目、自报 `PASS` 或给相近 gate 的证据替代。两端验证裁定实际满足该门的 SPEC 义务、适用于本轮 F 及所述域，再核 R07/R12 已要求的实际实现或行为证据；可共享同一原件，但必须独立定位并证明它覆盖每个所绑定的门。只在原义务容许且有效正式裁定明确时，按其实核 `AwaitingPolicy`、`Unsupported` 或从未启用等保留边界；不能补参数默认值、代签或把保留边界当成必需成功路径。

每个门缺证、裁定无效／越域／被取代或原条件未满足，门判 FAIL，按第八节记 `DESTINATION_GATE`，阻断每个关联 DST 及整图。只允许复用同一门、同一域上已独立核实的事实，仍逐 DST 投影结果；不得从 TB 全绿、旧票已关或另一 DST 的通过结论反推。

对每个 DST 取 crosswalk 的 `story_ids|family_entry_ids|detailed_acceptance_ids`，三集引用均须可解析；关联条目全部非 FAIL，且每个 DST 对应的 `obligation` 已按 R02 核实，其全部关闭切片满足相应 R12 门，全部具名 `success_gates` 通过；应用该 Destination 的第二节专用门。按 SPEC（`.chanlun/review-results/issue1339-r2-spec-20260909/payload/spec/SPEC.md:212, :216, :218`），DST-03 另要求 #1096、DST-05 另要求 #1319、DST-06 继续要求 #1304 与 #1279 合法去向：每张适用旧票均须 `disposition_valid=true` 且无该票失败诊断，否则对应 Destination FAIL，并按第八节归入该票的失败诊断。R08/R09 不成立也不得给任何 DST PASS，失败记 `DESTINATION_AGGREGATE`。第四节 #1279 本图义务条件只消费条目、TB 门、各具名裁定门和专用门等 **聚合前因子**，不读取任何 Destination 的成品结论，也不读自身 `disposition_valid`。要关的 #1369、#1340、#1323 均不是报告前置。

**拓扑顺序**：R01 先确定 F 的服务端身份 → 独立部署原件、受保护历史链及服务端／归档原件 → R09 阶段一完整核集成 → R02 → R03（仅用已求得的 R09 结果核集成锚）→ 用获审合同及独立票号闭集／原始时间线核 R01 窗口锚，再由 R04/R05 静态核进入 R06/R08 取运行事实；R06 → R07 专用原件与非激活事实 → R04 延期最终核；R09 → R10，R05/R06/R09/R10 → R11（核闸前与闸后归属及逐次原件）。按 R02/R03 及报告各义务收集原件和上游清单，再生成输入包并登记；收集来源不依赖任何成品报告或归并结论。R01/R08/R09 + 已登记输入包 → TB-11 前置；R03–R07 → 四类证据；R03–R07 + TB-11 前置 + 四类证据所需输入 → 键 → 各规范条目；键 + R07–R11 → TB-01..10；R02/R03 的门分母和规则 + 相应裁定原件与 R07/R12 的落实证据 → R13 逐具名门；条目、TB 门、四类证据、逐具名门与专用因子 → 旧票（含 #1279） → Destination → 整图报告 → #1391 封包关票 → #1403 独立复验（含实际报告四类分列）及封包关票 → #1369、#1340、#1323。任一处失败不改规则或集合重判。

### R14　失败是可消费的数据

引导成功后，各规则失败均至少输出一个第五节的 `FailedCheck`，`scope` 按第八节定位；`check_id` 为本条文所列诊断码（第五节的形状、引用、祖先和声明失败另用 `SCHEMA`、`ARTIFACT_REF`、`ANCESTRY`、`STATEMENT_MISSING`；其派生规则仍用所列步骤码），`scope/detail/evidence_ref` 只取第八节的规范投影，不照录上游任意文本或日志。逐个缺失键、检查、票、路径或字段登记；无法求分母先记源失败，受依赖的汇总直接为失败而不猜分母。缺 GitHub 作业/状态行不伪造结论；`workflow_runs[].run_id/run_attempt=null`（或留实测身份）、作业/审查数组缺项不填假行；历史只在符合 R11 的留证与对账条件时记 `NO_RUN`，实时空页不作未运行证明。权限缺失另列 `permission_blocked[]`，必跑未跑列 `unexecuted[].required=true`（`obligation` 按第八节取带证据域的键或槽位 ID），不占四条合法延期的身份。#1403 还须按报告同一原件重算报告字段及全部结论，失配逐处记 `REPORT_MISMATCH`；封包未登记或受验报告形状不合，按第五节输出 FAIL 回执，不借 summary 文字放行。R02 规范源失败不算报告引导失败；缺失 `observable_result` 的固定项仍按第八节填身份并逐项诊断。#1403 能解析受验报告为 JSON 对象时，即使四类分列缺键已触发 `SCHEMA`，同样执行 R12 的分列校验并记 `TB11_EVIDENCE_BY_KIND`；其他无法读取或解析的情况按第五节记录，不假称检查过其内容。

## 七、实施归属与图边

承接票 #2131、#2132、#2133 均在 #1369 下，不另开同用途票。#2131 交付登记册合同、lint、运行器、两个验收 workflow 与 DevSkim 的 dispatch，并在冻结 F 前将 `.sandcastle/` 下的 `at18-verification.mts` 合入 main。冻结前 #2131 须交付 R09 的独立部署原件及自动／人工入口门，完成拒绝／未知封口等夹具与 45 笔基线、过渡及新入口的逐笔留证和处置。历史不可恢复的处理按 R09：可完成入口及清查交付，不放行本版窗口。实际冻结还要求 R09 全量通过、无未决写锁，且 R11 的历史与新合入全量 run/attempt 清单、异常步骤／用例原件及本图归属均已按规则固化并对账。验证器须用独立于 #1391 的实现会话和非作者独审会话交付，不得直接或间接导入、调用 `.sandcastle/` 下的 `at18-report.mts` 生成器；F 上按 R09 核验其交付。#2132 交付全 TB 闸前底册、PRE、具名复跑锁及 TB-01 键。#1360..#1368 各汇总 owner 负责本 TB 剩余键、实体与实际主线运行；#1366 下 #1381/#1399/#1411 分别保留输入与 profile、seek/AsKnown、双进程与恢复，#1418 仍按 ADR 0058 交 AT-14 原件和锁。#1391 先合入生成器代码，票保持 OPEN，冻结 F 后再按第三节生成并封包；#1403 只在 #1391 封包关票后执行同一 F 上已有的验证器，按第五节和 R12 独立验输入包、报告与四类原件，出具 `at18-verification/1`。若总验发现验证器代码缺陷，走常规 PR 修订并合入 main；主线前移按 R01 作废重跑。#1391 与 #1403 均不充当登记的独审者。#2131 固定四类证据源及定位，#2132 按 R11 交付闸后逐 M 归属及闸前／闸后分 attempt 的 cure 关联，两端分别读取并验证。#2133 用户签署原有效域，不派代理代签。

沿用现有边 #1551→#2131→#2132、#1551→#1369、TB-01..10→#1391、#1359/#1391→#1403；落地时补 #2131→#1360..#1368、#2132→#1391、#2133→#1365/#1367/#1368。#2131 的验证器源码经 #2132 成为 #1391 的冻结前依赖；#1391→#1403 阻塞边只约束封包后的独立总验执行。#1403 经 #1391 消费全部 TB，无须重复接边。#1359 已关，#2131 的依赖经 #2132 兑现，不对 #1359 回挂阻塞或重开；不变更切片间既有排程。#1493 从 #1323 直属改挂 #1360，保留其已关记录和原依赖。主控同时在 #1391 写 R01 操作窗口，在受影响的 open 汇总票加本 TB 绑定与一次主线 dispatch AC。旧关联票不设为逆向整票 blocker。

## 八、报告字段的唯一投影（#1391 与 #1403 共用合同）

本节只规定如何编码事实；R01–R14 规定哪些事实和通过条件成立。两端以 F 固定来源读取并分别实现；#1403 运行 #2131 交付的独立验证器，可读取同一份已登记原件及 F 上的版本化适配器**数据合同**，不导入或调用 #1391 的生成器，也不以被验 JSON 的任何说明、分类或排序作为输入。缺原件时按第五节缺值规则填报，同时按下列失败投影发出失败记录。若结构化结果会因新观测而改变，按 R01 作废本轮，不从报告补值。R03 绑定的 F 版数据合同逐一固定各原子义务所需来源、提取位置及引用角色；同类别有多个有效来源时取全量，不由实现选择一条有利记录。正文的自然语言解释只写同源摘要。

### 身份、时间与排序

- 各文档的 `schema_version` 取对应常量，`ticket/base/head` 取本票通过引导的 manifest；#1403 用 #1391 报告对应 manifest 重算后者的三个值。报告 `generated_at` 与回执 `verified_at` 分别为写出时 UTC，统一用 RFC 3339 的 `YYYY-MM-DDTHH:mm:ss.sssZ`（有更高精度截到毫秒）。原件时间另用同一格式转换；比较业务时序用原始精度，不因展示截断给出通过。对报告先验时间合法且在窗口内（R01 的 W0 严格早于输入包与报告生成），再以该已验证时间放回独立重算的对象，重算 `content_hash`；比较完整 JCS 对象，包括重新算出的摘要，而不是让两个写入时钟相等。输入包引用按第五节从 #1391 manifest 的唯一合法登记构造；独立核包的实际字节、字段与该包自己的时刻/摘要；不重新生成一个带不同时刻的包去替代。
- 数组默认按下述主键升序、去精确重复。数字按数值、字符串按未经 Unicode 归一化的 UTF-8 字节序、`null` 在先、布尔 `false` 在先。主键相同而内容冲突时记 `SCHEMA`，冲突元素不入数组，不选择先到者。保留第五节固定位置的 Destination、TB、旧票、workflow、切片账，以及 SPEC 覆盖数组原行序；其余字符串数组按值，整数数组按值；不能用 GitHub 分页或并发完成顺序决定结果。
- 引用数组键：`ArtifactRef=(storage,path,commit,ticket,base,head,sha256,bounded_scope)`；`ManifestRef=(ticket,manifest_path)`；`ReviewRef=(merge_commit,pr,status_id)`；`CiRunRef=(workflow,run_id,run_attempt)`；`AcceptanceJob=(workflow,run_id,run_attempt,job)`；`HistoricalDeviation=(ticket,commit,workflow,run_id,run_attempt)`；切片及下游票用 `ticket`；`TicketScopeRef=(ticket,scope)`；`PostGateChongRecord=chong_id`（全集有重复身份按第五节留红，不靠去重通过）；延期用 `obligation`；权限阻塞用 `(obligation,blocker_ticket,evidence_class)`；诊断用 `(check_id,scope,detail,evidence_ref)`（引用按其键）。不排序结构语义所需的时间序列。
- 仓内 ArtifactRef 的路径/提交用对应规则钉住的 Git 路径和 SHA，仓外身份和绝对路径只用匹配 manifest 的原始条目，不取本机别名、自报路径或自报范围。所有 ArtifactRef 的 `bounded_scope` 恒为 ASCII `AT18:<role>`；每个引用位置按用途取唯一角色：五种输入按 `SPEC/CROSSWALK/COVERAGE_INPUT/REGISTRY/PREGATE`，切片账用 `SLICE_LEDGER`，输入包及报告用 `INPUT_BUNDLE/REPORT`，R07 封印原件用 `RUN_RECORD`，授权原件用 `AUTHORIZATION`，旧票规范出处用 `LEGACY_SOURCE`，ADR 0058 合法仓内实体用 `AT14_REPORT`，Destination 具名门裁定原件用 `DESTINATION_DECISION`。`PostGateChongRecord` 的 `gate_reached_event`、`gate_reached_candidates[]`、`first_activation`、`non_activation_evidence[]` 和 `rollback_evidence[]` 固定为 `AT18:RUN_RECORD`，必须来自 R07 封印；`parameter_version` 在任何非空引用中固定为 `AT18:AUTHORIZATION`。按第二节的授权有效域取用户签署原件，或取普通研发域合法的代理独审裁定原件；二者不可代签或改记来源。封印运行原件只证明授权版本与运行的关联。同一对象在证据数组中保留生产它的这些角色，不因转入另一数组重命名。运行槽、裁定和用途边界由原规则求值，不从角色字符串反推。
- `ReviewRef` 逐字段取 R09 实际 PR、`merged_at`、H、M 与经完整性验证的截止快照中按 `created_at < merged_at` 选中的状态记录（id、`created_at`、`updated_at`、作者、状态）；`created_at <= updated_at < merged_at` 才可作通过证据，对 H 上按 `ascii_lowercase(context) == "deepagents/review"` 归组后与合入同秒的任一记录按 R09 留 `REVIEW_FINAL_PRODUCT`，不回退选旧成功。直接双审、沿用均用 `status_id` 和该状态 `description` 的 `run_id` 按 R09 核正式登记是否绑定此实际已合入 PR 及完整 SHA，再分别核回执和沿用否决；不增写 ReviewRef 字段；`CiRunRef` 取 R08 所选 run 的 workflow 路径、id、attempt、head_sha、结论、`html_url`；运行、作业和历史偏差只取 R06–R11 的服务端字段（含 R11 对账通过的固化原件），历史每行保留 `run_attempt`（R11 已证为零才两 ID 为 null；证据缺口另留来源诊断）（作业名取 Jobs API 的 `name`，结论按第五节枚举），不得从日志摘词。GitHub 票态取 API `state` 大写，已知 `state_reason` 只取 `COMPLETED|NOT_PLANNED|REOPENED|DUPLICATE`，无值填 null，未知值留红不照录。TB-11 的 `slices` 只列 #1391 与 #1403，两行写报告生成时刻的实际状态；OPEN 时 `state_reason=null`。#1403 用实际创建、关闭/重开事件重放这两票的报告时态，不用封包后的新票态；报告时 #1391 非 OPEN 或两票阶段无法证成，按第三节留红。其余票态取同窗观测，并按 R01 完整时间线拒绝同窗状态变更（包括重开又关回同一终态或仅修改状态原因）；包括签署、历史 CI 原件、绑定规则和上游实体在内的决策输入不得在同窗换源。服务端查询失败不等于已知缺失。

### 投影表

| 字段 | 唯一来源／投影 |
|---|---|
| 输入包及其 `window_anchor`、`external_manifests` | 仓内对象及顺序按第五节；`window_anchor` 从 R01 独立核实的状态 A 与当前 `open_bind` 写 `{status_id: A.id, created_at: W0, ledger_commit: open_bind 所在提交的完整 SHA}`（W0 取服务端 UTC 原串，不作本节毫秒展示转换），只写入输入包，报告与回执分别由 TB-11 的 `input_bundle` 与 `input_bundle_ref` 绑定；上游仅列实际消费并匹配有效原件的清单，不列 #1391 自身清单。无合法登记两处引用均为 null，有合法登记则两处均照录该项，实体或锚失败另诊断；总验独立重选当前锚，不能用该引用代替 R01。 |
| `destinations[].obligation` | R02 两处原件均有效才照录 F 的 SPEC JSON 中对应 `US-DST-0<n>` 的 `observable_result` 原字符串，不改写空白。任一缺值、非法或不能唯一定位时填对应 `DST-0<n>`，并按 R02 记该字段的 `COVERAGE_SOURCE`，该 DST 与整图均 FAIL。 |
| `destinations[].success_gates` | 逐 DST 取 R02 已核分母并按 gate ID 的 UTF-8 字节升序输出；逐门取 R13 核实的裁定原件全量引用（依引用键排序去重），仓内用固定 Git 原件，仓外用依第五节在 manifest 登记的裁定档案字节。应用独立求得的门结果；同一门可按各 DST 实际适用域复用原件，不引用其他 DST 的结果。分母源不合按第五节留红。 |
| Destination 的 `tickets/commits/downstream_status` | 从该 DST crosswalk 三集取所有对应 closure TB；其汇总和 R12 原生实施子票进入 `tickets`，`scope` 固定该 TB 的 ID；再按 R10 重算的 `Landing.attribution_scopes` 逐对加入 `(ticket,scope)`：具体 TB 仅进 closure 含该 TB 的 DST，`(ticket,"GRAPH")` 进入全部六项，只列历史出处，不扩 R12 子票或 R13 义务。按 R13，DST-03 另加 `(1096,"LEGACY")`，DST-05 另加 `(1319,"LEGACY")`，DST-06 另加 `(1304,"LEGACY")`、`(1279,"LEGACY")`。对最终 `tickets` 的每个票号取其全部 R10 历史提交，与可确认的 F 一起取并集写 `commits`（共享提交只列一次）；`downstream_status` 对同一票号集合逐票只列一次实际状态，查询不到按第五节取 null 并留诊断。 |
| Destination/TB 的主线、CI 和审查 | `main_sha` 为 R01 确认的 F，无法确认时 null；两类记录均列 R08 的两个通用 CI 及 R09 观察到的全部集成审查（含 PRE 锚的有效合入记录）。这些门对整图适用，不能按作者猜测裁切。 |
| Destination/TB 的证据 | TB-01..10 的 `evidence_by_class[c]` 恰为该 TB 的全部合法、R07 封印的 `tb.<c>.TB-xx` 实体引用；`entity_reports` 为两启用类的并集，不混入专用槽。DST 取其 closure TB 的同类数组并集，experiment 仅另并入以下实际、合法且封印的 `AT18:RUN_RECORD` 引用：DST-05 的 `permission_evidence.experiment.runtime_verification` 非空值，DST-02/03/05 的 `migration_invariants.experiment.non_empty_evidence_refs[]`。权限授权声明、能力元组、场所权限事实均不进两类 `evidence_by_class`；`post_gate_records` 专用引用只留顶层（`destination_ids=[]`），不额外并入任何 TB 或 DST。simulation 不并专用引用；启用类无引用为 `[]`，production 本版固定 `null`；TB-11 按第三节固定空实体、启用类空数组及输入包引用。 |
| `evidence_by_kind` | R03 合同按 R12 四类声明的、经 R05–R07 核实的原件，按每类实际证据域分槽并保留原有引用角色。采用同一 `ArtifactRef` 排序、缺值和未启用边界；不从现有 `evidence_by_class` 或报告自报内容猜分类。 |
| Destination/TB 的未完义务 | 合法延期只按表后闭集加入。必跑未跑键 ID 与失败键的基 ID 按该键归属（TB 为 `slice`；DST 同时要求该 TB 属其 closure、键的 `(kind,id)` 在 R13 对应三集中）。逐具名门诊断只投影到其 DST，不进入 TB 或 #1279 自有义务；R02 的门分母源诊断同样只投影到受影响的 DST。专用槽必跑未跑按第二节适用 DST，并归 R12 明确依赖该槽的 TB；后闸专用槽的必跑未跑只归 TB-11 的整图对账，不因 closure 传播。未完成必需票写 `ticket:<n>`，按 R12 原生子票与 R13 专用旧票的实际义务关系投影；未到关票阶段的 TB-11 不写未完。失败诊断在其被检对象的义务范围内投影为 `check_id+"@"+scope`：键与票同上（#1096 失败归 DST-03，#1319 失败归 DST-05，#1304/#1279 失败归 DST-06；包括 `ticket:<n>` 及其具名义务域），专用槽同其必跑未跑范围；`TB11_EVIDENCE_BY_KIND` 按 `(story,US-ENG-10,TB-11)` 的键归属投影（TB 只归 TB-11，DST 为本版关联的 DST-01..06），不传播至 TB-01..10；整图门失败适用于全部。各项取并集、排序去重。Destination `result` 取 R13（适用旧票的 `disposition_valid` 或诊断不过即 FAIL），TB `gate_satisfied` 取 R12，`slices` 来自 R12 原生实施分母。TB `tb_id/ticket` 按下列与 R10 同源的固定映射。 |
| 权限、能力、迁移 | 第二节与 R07 的原件。运行引用只取 R07 封印来源，授权与场所依据按实际角色读取；单值槽多条候选仅在对同一业务身份互证且无冲突后取引用排序第一项，否则缺值并留红。能力三元组版本取实际能力记录规范版本字段，两个摘要取能力记录与场所 profile 原始字节；场所来源 URL、取回时间取 #1770 来源字段。布尔值从 R07 重算，Destination ⑤ 的槽位能力值原样投影到顶层。 |
| `post_gate_records` | 按 R07 独立枚举、核验并保留全部 `chong_records`，以 `chong_id` 字典序排列。引用按本节角色取值，每重自有正式触达、候选、授权、首次启用引用及其全部封印回退引用（无则 `[]`）；三个时间戳只取与该重配对的三条原件对应时间字段，不从其他重借值。同一重的单值字段只允许同一原件身份的无冲突互证（引用排序取第一），不同重不得竞争一个字段。`CANDIDATE_ONLY` 的门槛缺口及未切换、未启用事实取独立的封印原件，不由候选标签推断。槽状态严格按第五节汇总，逐重缺证与非法启用留红，不从报告的结论键或摘要取值。 |
| `spec_coverage` | 标识、族、闭包切片与 DST 从 R02 各对应 crosswalk 行的字段逐值投影；family 的 `entry_mode` 按第五节；`status` 按 R12。条目证据只列适用的登记册引用（有通过的非 TB-11 键）及输入包引用（有非 `FAIL` 的 TB-11 键：其余 112 个键通过前置时，或 `US-ENG-10` 为 `PENDING_REPORT_VERIFICATION` 时）。`US-ENG-10` 为 `FAIL` 时 `evidence_refs=[]`。`deferred_gates` 取该条目获准延期域 ID 并集，无则空。 |
| `legacy_dispositions[]` | 固定票序。`disposition` 按票依序固定为 `PRESERVE_BOUNDED/RETIRE_OR_INCORPORATE/PRESERVE_ARCHIVE/ADOPT_AT14/INCORPORATE_FEED_WIRE/REPLAY_AND_PRESERVE_HEAVY/KEEP_OPEN`（逐票一值）。证据取 R13 固定解码器实际消费的来源引用及该票专用实体，不列交叉票的所有产物。`remaining_obligations` 取未证成的 R13 义务 ID；#1279 自有义务用 `ISSUE_1279:<规范原件 JSON Pointer 或固定评论 ID 和条目序号>`，从 R13 固定检查单取，不复制说明文字。本图义务失败留 R13 诊断，不列到 #1279 的自有清单。状态及 `disposition_valid` 只取 R13。 |
| `workflow_runs/acceptance_jobs/historical_deviations` | R06/R08 只按同一 R01 当前有效 `open_bind.runs` 的四个精确 ID 核实运行及最新 attempt（`run.created_at > W0`；锚不可用或 run/attempt 无法核实填 null，不从列表补入）、R06–R08 精确名字或名字语法所及的实际尝试作业和封印行、R11 按闸前与闸后本图归属及 run/attempt 分列的偏差（图外采集仅入历史链）。未声明作业、替代运行和互不匹配的封印不作证，不从结果中反选。 |
| `bounded_domain_statement` | 第五节三条固定声明按列出顺序，以 LF 连接（末尾不加 LF），然后依次追加 `AT18_SCOPE SIMULATION_P1_ONLY`、`AT18_PRODUCTION_SLOT DISABLED`、`AT18_POST_GATE_EXPERIMENT <state>`、`AT18_POST_GATE_PRODUCTION <state>`（空槽写 `DISABLED`，否则取第五节的槽汇总状态，逐重审计见 `chong_records`）；若具名重测仍保留，再追加 `AT18_HEAVY_MEASUREMENT DEFERRED`。计数为 `historical_deviations.length` 的无前导零十进制。 |
| `overall_result`、回执 `verdict` | 第五节合取及逐字段比较，不能从摘要或已关票推断。回执的受验引用从封包后的 #1391 manifest 取值，`report_manifest` 绑定该清单，报告摘要从实体派生；缺件分别按第五节处理。 |

| `tb_id` | `ticket` |
|---|---|
| TB-01 | #1359 |
| TB-02 | #1360 |
| TB-03 | #1361 |
| TB-04 | #1362 |
| TB-05 | #1363 |
| TB-06 | #1364 |
| TB-07 | #1366 |
| TB-08 | #1367 |
| TB-09 | #1365 |
| TB-10 | #1368 |
| TB-11 | #1369 |

合法延期在两类 `remaining_obligations` 中的闭集（都以同名 `required=false` 条目实际存在为前提）：

| `unexecuted.obligation` | TB 汇总 | Destination |
|---|---|---|
| `ISSUE_1561_P2_FIRST_SEND`、`ADR_0036_POST_GATE_EXPERIMENT`、`ADR_0036_POST_GATE_PRODUCTION` | 仅有该 ID 的 R04 已核准延期域的非 TB-11 键所属 TB。 | 仅有该延期键的 DST：该键的 `(kind,id)` 在 R13 对应集合且其 `slice` 在该 DST closure。 |
| `ISSUE_1320_HEAVY_MEASUREMENT` | 仅 TB-11（第四节单列；同时保留顶层 `unexecuted[]` 与旧票 #1320 的本项，不入任一键的 `deferred_gates`）。 | 不入任一 DST；TB-11 归属不向下投影。 |

非激活状态本身不会向 TB-11 或任一 DST 附加 `ADR_0036_POST_GATE_*`；仅以上表中已核准的键为准。键级延期按具体键和域投影，不得拿汇总后丢失 slice 的 `spec_coverage[].deferred_gates` 向全部切片反推。

### 原因、缺口与诊断码

- 四种合法延期的 `(reason, blocker_or_gap)` 固定如下；只有第五节触发条件成立才列，`required=false`、证据类仍取第五节。后闸槽汇总为 `UNKNOWN` 时由槽状态、逐重可读记录及 R07 失败诊断留痕，不造合法延期行。已启用部署槽的合法延期行只涵盖合法从未启用子集；只有 R04/R07 核准整个域延期才投影到键。

| `obligation` | `reason` | `blocker_or_gap` |
|---|---|---|
| `ISSUE_1561_P2_FIRST_SEND` | `PRODUCTION_NOT_ENABLED` | `ticket:1561` |
| `ADR_0036_POST_GATE_EXPERIMENT` | `POST_GATE:<实验槽状态枚举或 DISABLED>` | `adr:0036` |
| `ADR_0036_POST_GATE_PRODUCTION` | `POST_GATE:<生产槽状态枚举或 DISABLED>` | `adr:0036` |
| `ISSUE_1320_HEAVY_MEASUREMENT` | `MEASUREMENT_NOT_COMPLETED` | `ticket:1320` |

- 必跑未跑：按义务 ID 归并（键用下表「域」格式，不带 basis；专用门用「槽」格式）；同一义务多个未跑原因只按以下顺序取第一个：权限未证 `AUTH_REQUIRED` → 来源不可用 `SOURCE_UNAVAILABLE` → 完整尝试无相应执行 `CHECK_NOT_RUN`。对应 `blocker_or_gap` 分别写 `ticket:<最小有效硬门票号>`、`SOURCE_UNAVAILABLE`、`CHECK_NOT_RUN`；`evidence_class` 从对应域或槽条目取。实跑失败写诊断，不冒充未跑。权限阻塞按同一义务和每张未满足的实际硬门票输出，`missing_authorization` 固定 `AUTH_REQUIRED`，`blocker_ticket` 取实际硬门票（P1 凭据接触面为 #2133，发送另外适用 #1412）；不抄票面文句。无有效 #2133 仍填必跑未跑及权限阻塞，不能冒充合法延期。
- `FailedCheck` 只读原规则的诊断码。每个被测对象/字段未满足命名判据即写一行，`detail=check_id`；同一码同一作用域合一，不用真人或异常对象的措辞（归因细节由取证原件和人读摘要承接）。`evidence_ref` 固定用该失败检查所读取且自身合法的最小引用（按引用排序）；源读取/校验失败或无合法引用固定 null；同一码同一域合并时在全部合法引用中取最小，否则 null。作用域按被检对象的合同身份固定：覆盖键、basis、域、票及槽用下表字面模板；集成、历史分别用 `commit:<SHA>` 和 `history:<ticket 或 none>/<SHA>/<workflow basename>/<run_id 或 none>/<run_attempt 或 none>`；尚无 M 的未封口合入意图用 `merge_intent:<账本序号>`；`HISTORY_ATTRIBUTION` 固定用 `commit:<SHA>`；历史来源未能归票或经证实图外时历史作用域票号写 `none`，不造偏差报告行；权限用上述义务 ID；PRE 逐路径用 `pre:<Git 路径>`；检查/作业分别用 `check:<check_id>`、`job:<workflow basename>/<run_id 或 none>/<job name>`；R01 锚的 `WINDOW_DRIFT` 或锚源的 `SOURCE_UNAVAILABLE` 固定用输入源作用域 `ticket:1391@window_anchor`、`evidence_ref=null`（含无可用输入包/锚、绑定运行身份不合、开窗账本及保护取证失败、窗口原件分页失败、受约束票同窗状态变更或触及 1,000 条上限，按一码同域合一；不使用报告或回执的 JSON 指针）。R07 逐重后闸失败按 `/post_gate_records/<部署槽>/chong_records` 或其对应记录及字段的 RFC 6901 指针定位，不用槽义务 ID 代替；其他字段用所写文档 schema 的 RFC 6901 指针（数组上用规范顺序，缺项用规则应有的位置），源失败用读取该源的字段指针。不得由异常文案决定 ID、引用或粒度。`REPORT_MISMATCH` 只在回执，按 JCS 对象递归遍历，对首个缺键、类型/标量差异、数组长度差异输出相应 JSON Pointer；长度不等的数组在其自身停止下钻，其余继续逐叶列差异。两端不得只比较总体布尔值。

`TB11_EVIDENCE_BY_KIND` 的 `scope`：整个分列缺失或不是对象用 `/evidence_by_kind`；类缺失或不是对象用 `/evidence_by_kind/<kind>`。仅对存在且为对象的类逐域核验：证据域字段缺失、槽位编码不合法、引用与独立计算的应有证据集不符，用 `/evidence_by_kind/<kind>/<evidence_class>`；`venue` 缺少必需的有效 `experiment` 证据时，固定用 `/evidence_by_kind/venue/experiment`，不因 `venue.simulation` 非空或同类另有域失败而省略。已有域级诊断时不另报类级空列；仅该类完全没有有效证据且没有任何域级诊断时，才用 `/evidence_by_kind/<kind>` 报空列。

下表的 `K` 恒为 `key:<slice>/<kind>/<id>`；`slice` 取 TB ID，`kind` 为 `story|family|detail`，`id` 取 crosswalk 身份。表中 `@`、`/`、`:` 均为字面分隔符，尖括号是代入项，不写进结果；票号用无前导零的十进制。profile 有值就照录，`null` 固定写 `none`，无域时整个后缀省略（不是空域）。basis 路径和指针分别作为一个 token，先按 RFC 6901 的 token 转义（`~→~0` 后 `/→~1`），再将原 `%` 编为 `%25`、`@` 编为 `%40`（依次替换，不对新增的百分号二次编码），只做这些替换；根指针为空 token，仍保留其前面的 `@`。crosswalk ID 若含分隔字符按同一 token 规则编码；未带 basis/domain 的覆盖失败 ID 与未完数组引用同一个 `K`。专用义务 ID 内的 `%`、`@` 也依次转义为 `%25`、`%40`，其他字符照录。

| 对象 | 唯一模板 |
|---|---|
| 键（无 basis、无域） | `K` |
| basis（无域） | `K@basis:<esc_path>@<esc_pointer>` |
| 域（无 basis；亦为必跑未跑及权限义务 ID） | `K@<evidence_class>@<profile 或 none>` |
| basis 与域同时有 | `K@basis:<esc_path>@<esc_pointer>@<evidence_class>@<profile 或 none>` |
| R01 窗口锚输入源（报告与回执共用） | `ticket:1391@window_anchor` |
| Destination 具名门 | `gate:<DST-0n>/<gate_id>`（`DESTINATION_GATE`） |
| 票态 / 某张票的具名义务 | `ticket:<n>` / `ticket:<n>@<obligation_id>` |
| 槽（含 simulation 的 null profile） | `slot:<record>@<profile 或 none>` |

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

#2131 按 R03 交付的 F 版规范适配器数据合同逐字段钉紧 JSON Pointer／固定来源 ID 与类型，尤其是运行记录的业务字段、#1770 文档来源字段和 #1279 自有检查单清册；不得交付多个候选取值器。验收夹具须包含同一原件不同分页/输入顺序、不同日志措辞、#1391 封包前后状态、两个共享提交归属、非原生单 TB／多 TB／GRAPH 路由与漏归属拒绝、四种合法延期的 TB/DST 精确边界、专用原件排除授权引用、后闸两种授权及越域拒收、输入包先登记与 #1403 清单错配、无合法输入包登记（两处引用均为 null）及已合法登记但实体缺失或摘要/内容不合（两处引用均保留且判红）、合入后 success/pending、合入同秒创建或更新任一状态均拒收、严格较早秒内按 status id 排序、共享 base/head 的不同 PR 不得借用状态、合法沿用与沿用来源断链/同补丁 BLOCK+FAILED 或 STALE/晚登记非 PASS/历史 head 合入同秒否决或登记/main 路径重合拒收、X 取时早却在沿用锁枚举后才落盘（无锁前 pending 或锁内清单）判 `REVIEW_FINAL_PRODUCT`、#1949 同型锁前 pending 只给出有效完结上界，不能代替锁内登记序号、#2025 异补丁 error 缺本地终态 publication 不误拒、同 PR 同补丁但 `reused_from.admission` 与两份原回执任一不合判 `REVIEW_FINAL_PRODUCT`。另须覆盖以下源与后闸对照：

- **R09 登记取时与持锁落盘交错**：X 先取 `registered_at_ns`，A 后取时但先持锁登记并双 PASS；X 随后持锁落盘，序号大于 A，并以 FAILED 完结。即使 X 在沿用枚举前已落盘且没有 BLOCK，仍取代 A、拒绝沿用；无锁内单调顺序原件时同样不得沿用，不从较早本机时间或锁前可见性猜 X 先登记。对照锁内原件证明已完结、无 BLOCK 的 X 确在 A 之前，其余条件齐全才允许沿用 A。
- **R09 context 大小写与同秒截止**：H 有较早正式 `deepagents/review` success，完整页中另有 `DeepAgents/Review` 在合入同秒创建或更新（分别测试，无论作者或结论）→ 拒绝选旧 success，`REVIEW_FINAL_PRODUCT`；原件完整且已经实际合入则 `MERGED_VIOLATION`。对照仅有异检查名的同秒记录，不归本组，不触发本门。
- **R10 改名、搬移或复制保留正文**：P0 的闸前 `a.rs` 在 G0 后原封不动改名为 `b.rs`，并可再复制到另一目录；F 不必保留 `a.rs`，原元组仍在 PRE、F 的全部匹配路径须对账。登记齐全且两份独立回执证明完整正文复审 → 此门 PASS；移除原元组、任一目标的对账或正文复审证据，仅给无正文的 rename/copy diff 或普通 PASS → `PREGATE_REVIEW`。对照原路径和该 blob 在 F 全部消失且无同名留存，不加入 PRE。

- **R09 合入结果与截止快照**：正式 PASS 的创建秒或更新秒尚未过去时不调用合入；服务端严格跨秒、身份不变且真实 M 与两批完整快照匹配 → `MERGED_PASS`。带旧 H 的请求收到可归因的 409，后读 PR 未合入、head=H′、主线仍为基线 → `CONFIRMED_NOT_MERGED`、无 M；删掉拒绝原件且无有效 SHA 屏障，或漏掉实态核验 → 不封口。重查找到实际 M 且截止原件齐备 → 按 M 实际结果封口。
- **R09 崩溃／超时恢复**：分别模拟落盘后发出前崩溃和已发出无响应；PR 未合入且 head 仍为 H，即使已证旧进程退出、main 未动，仍 `SOURCE_UNAVAILABLE`、持锁且不重发。原执行实例已退出、同源受控快进 H′，屏障后 PR/ref 一致且未合，main/第一父链仍为基线 → 签章 `SUPERSEDED_UNKNOWN_INTENT`，保留原意图及未知标记，不造拒绝、集成或偏差行；模拟迟到 `PUT(sha=H)` 在服务端被拒，新 H′ 或其他 PR 可依正常入口开新意图。对照只本地提交、只关闭可重开的 PR、允许退回 H、源 ref 与 PR 不一致、缺退出或任一屏障后读证 → 不解锁。若迟到请求抢在屏障前合入，按实际 M 分流，不准写替换未知终态。
- **R09 独立引导**：令 M 首次引入 R03，下一笔 M′ 修改它。阶段一禁止任何 R03 文件读取，仍由独立部署原件解码齐全的两笔 R09 原件并通过；阶段二才读 R03 并用已验证的 M′ 核锚。对照删除部署原件中的必需角色、集合或解码版本／给错创世或公钥，F 上即使有正确值也不补，阶段一 `SOURCE_UNAVAILABLE`；阶段一通过但 F 版创世、公钥或锚不合，阶段二拒收，不重写阶段一。
- **R09 已证违规与缺证分流**：预检合格，实际合入 M 后发现任一作者的同 context 状态与合入同秒；原件齐全 → `MERGED_VIOLATION`，M 留 `REVIEW_FINAL_PRODUCT`。无有效归档则仍锁；有可验证归档仅允许所列修复／评估 PR，普通 PR 或该修复 PR 缺正式审查/CI 仍不放行。修复合入产生 F′ 后，只要仍遍历 M，整图仍 FAIL。对照去掉关键快照页 → `SOURCE_UNAVAILABLE`、保持未封口与写锁；不得假写违规归档。补齐同一截止点后再按事实分流。
- **R09 历史完整性**：旧 App 双审及 `success` 可核、实时全分页也一致，但无该合入时点的全作者截止证据（例如已过期的否决状态），登记该笔 `SOURCE_UNAVAILABLE`，保留已核字段、不锁新合入、不冻结本版窗口；不能用页面当前 90 天或重读空页补证。对照有当时独立固化的完整原件，即使如今状态过期，也按截止点原件重算：原件齐全且无违规才通过；有固化否决条目仍拒绝，不回退旧 `success`。确实不可恢复的 M 不能凭清查完成或处置评论变绿。
- **R13 Destination 具名门**：其余规则全绿时六项各列 13 门，全量裁定及落实证据有效才通过。仅移除 `G-025` 裁定原件，或以失效／异域裁定、已通过同名 family 测试替代，或使用有效裁定但其必要条件未成立 → 六个 `G-025` FAIL、六条 `DESTINATION_GATE`、六项 DST 与整图 FAIL；TB 不因该投影变红。重复／未知 crosswalk gate ID 或分母缺失 → 受影响的 DST 记 `COVERAGE_SOURCE`，不猜分母。报告删一门、重名或篡改其结论，独立复验不得接受。
- **封包预检**：退出 0、`READY_FOR_APPROVAL`、无诊断/例外 → 普通预检门过；退出同为 0、`READY_WITH_EXPLICIT_EXCEPTION`、有分诊但无批准，或只批准旧清单摘要／其他例外 → 不过，相关票不可关。逐项批准绑定受检清单字节及其精确例外身份 → 仅预检门过，最终独评仍必需。向 manifest 追加报告改变字节后，旧版本批准不可复用。
- **R11 历史对账与逐次核销**：闸后本图 M 归票 A/B，ci.yml 的 run 21 第 1、2 次失败、第 3 次成功 → 偏差数组恰有 A/B 各两条六键行（第 1、2 次），各次分别从其原件绑定失败测试／步骤；同一 F 具名成功见证可支持多条关联，但漏关联第 2 次仍失败。后来修复 M′ 不改 M 的归属或历史行；M′ 自身失败另记。已证不交付本图的 Mₓ 失败原件仍入链，无本图偏差行或 cure；去掉足以证实图外的原件 → `HISTORY_ATTRIBUTION`。失败 run 过期／删除后实时空页，无清单或本图尝试缺合规 F 复跑 → `SOURCE_UNAVAILABLE`，不写 `NO_RUN`；已证失败行照录。有完整固化原件且具名复跑成功时仍保留原失败行。有效持久清单与完整实时 API 都证零且满足保留期／无删除门时才写 `NO_RUN`；完整空页单独输入不得写零。
- **R11 多测试、异常与原件身份**：同一 cargo 步骤实际失败测试 X/Y，Jobs 只给步骤 failure；有正确绑定的结果原件且 X/Y 都按该 attempt 在 F 复跑成功 → 该偏差可核销。只跑 X → `DEVIATION_NOT_CURED`；只有 Jobs、日志截断/已过期、把第 2 次日志给第 1 次或原件步骤号/名称不符 → `SOURCE_UNAVAILABLE`，通用 CI 绿也不通过。取消／超时但测试已执行时仍核日志或结果；同 attempt 的服务端原件证明在 job 分派前取消时，不造失败用例，复跑受阻入口；仅有取消结论、无执行或调度原件则留来源失败。
- **逐重后闸与混合延期**：同一 P1 profile 两个重均合法触达、授权、启用且各有行为见证 → 保留两行，槽为 `TRIGGERED_AND_ENABLED`；其中一重越域或乱序 → FAIL，另一重不能补证。候选须有独立门槛缺口及未切换／未启用原件；缺证或私自启用 → FAIL，有候选不得写 `NOT_TRIGGERED`。槽内一重合法候选、一重合法未触发（均未启用）→ 汇总 `MIXED`，可整体延期；把后者改为已有合法启用的 A，候选 B 不变 → 仍 `MIXED`，只登记 B 的延期，覆盖 A 的实际行为见证才通过；把整个域改延期、只跑 B、只提供 A 的三记录均失败。
- **逐重回退**：A 有有效首次启用三记录，之后 K 回正、执行回退，当前关闭且有回退后实际行为见证 → `TRIGGERED_ENABLED_THEN_REVERTED`，原三记录和回退引用均保留，不计 A 为可延期，即使槽内没有当前启用重。A 与候选 B 同槽 → `MIXED`，只登记 B，不能跳过 A 的检查。移除首次启用历史、回退原件或回退后行为见证、颠倒回退/启用时序、回退后擅自启用，均 → `SPECIAL_GATE` / FAIL；不得把 A 改记为从未启用。

- **逐重恢复／迁入前已回退**：A 开跑前曾合法启用并回退，本轮始终关闭、无新增触达／启用事件。P1 仅有本轮清册和事件 → A 与槽为 `UNKNOWN`、`SPECIAL_GATE` / FAIL，不产生单重或整域延期；补齐可信恢复／迁入前历史、原三记录、回退和本轮回退后行为见证 → A 为 `TRIGGERED_ENABLED_THEN_REVERTED`，仍不延期。对照可从创世连续证明从未启用并满足相应状态条件的重才可延期。

窗口夹具须覆盖：

- 完整开窗按意图、服务端 Status/四个 dispatch 响应、签章绑定的顺序；意图未绑定不得验收，须先 `void` 才可同 F 重开。A → `void(A)` → B → `void(B)` → C 只认 C。漏 `void` 连开、无前置意图绑定、错轮作废、退役后再追加均拒收并标记所涉窗口及身份。
- 本窗只认绑定 run 及最新 attempt：正常四项通过；`run.created_at == W0`、run 身份不符、最新 attempt 作业或封印不全均不通过。前窗请求未决时退役旧 F；若旧请求在新窗 W0 后才解析 `main` 并产生新 F 上的 run 81，新窗只返回三项时不得绑定，已绑定第四项但其原件缺失时也不得借 81；真正第四项齐备时，只认新窗四个精确 ID。
- **R06/R08 手动 CI 闭集**：`workflow_dispatch` 的同一最新已完成 attempt 中，`ci-ok` 与所有 `ci-ok.needs` 作业实例均 `success`，仅闭集外 `macos-session` 为 `failure`，GitHub run/attempt 聚合失败 → R08 通用 CI 槽通过，`CiRunRef.conclusion="FAILURE"` 原样留存，`acceptance_jobs[]` 不列该作业。对照让任一 needs 实例失败、跳过或缺失，即使 `ci-ok` 为绿也记 `HEAD_CI`，不借旧 attempt 补齐。DevSkim、simulation、experiment 仍按 R06 要求 run 及 attempt 成功。
- **R08 重跑换 runner**：同一 workflow run 初次服务端按托管展开 `rust-test-s-session` 四片（0–3）；仅一片重跑换到 Boat 时，原始分母仍为四片，最新 attempt 缺任一片或其他必需实例即 `HEAD_CI`，不按 Boat 两片或旧 attempt 放行。对照最新 attempt 四片及其余闭集均成功才过本门，不因 runner labels 混合而改分母；缺完整展开原件记 `SOURCE_UNAVAILABLE`。
- 未入账状态过期：第 0 天开 A 并绑定 11–14，第 1 天出现 1 天期的授权孤儿状态（含同秒、较晚和重复 UUID），第 2 天清理；两个新读端始终选 A 与 11–14。A 自身过期或不匹配时按锚失效拒收。用逐请求取数的分页源复现：每页 100 条，共 1,051 条，含 1,000 条目标 context；第一遍读完第 2 页后，该页一条其他 context 的状态到期，原第 201 条目标状态移进第 2 页。首屏和终页页码均未变；单轮完整双遍判不一致，记 `SOURCE_UNAVAILABLE`，不选四项、不生成有效输入包。源稳定后再读，两遍相同并数得 1,000 条，仍因满额拒收；对照源的目标 context 稳定为 999 条且 A 合法，稳定双遍通过。
- B1 作废过期：第 0 天以 90 天保留期开 A、入账并跑齐四项；第 1 天追加 `void(A)`（对照输入另有 1 天保留期作废状态）；第 2 天状态清理后仍可见 A 和四个旧 run，但两个新读端仍从账本拒收，两端均不需要作废状态。
- B1 UUID 过期：保留期恒为 90 天。第 0 天先入账 `open_intent(U)`，分别模拟 A1 完成绑定与 A1 只写状态后崩溃；第 89 天即使先作废再错误追加 A2(U)，也与第 91 天 A1 状态清理后一样拒收。串行写端拒绝复用；另测跨 F 重复 UUID、重复 `status_id`、跨槽位/窗口重复 `run_id`。旧 F 退役后保留全部冲突记录和污点，任何沿用污点身份的窗口均拒收，全新且无关联的 F 能验收。
- B2 满额解冻：第 999 条为合法 A，第 1,000 条由非作废状态占满，第 1,001 条写入被拒（HTTP 422）；只追加并读回 `retire_head(F, STATUS_CAPACITY_EXHAUSTED)`，两端拒旧 F，#1391 保持 `OPEN`，可恢复合入。新 F 新绑定四项通过；旧 F 状态清空或再出现旧 F 事件仍拒收。主动放弃用 `WINDOW_ABORTED`，也不写状态。
- 账本保护（其余条件满足）：① 经典保护覆盖两项，完整枚举确证目标生效 Rulesets 为空 → PASS；② 同样的经典保护，目标 Ruleset 仅覆盖 `non_fast_forward` 且零绕过者 → PASS；③ 同②但含绕过者 → `WINDOW_DRIFT`；④ 无经典保护，生效 Rulesets 仅覆盖 `non_fast_forward`、缺 `deletion` → `WINDOW_DRIFT`；⑤ 合格经典保护仅防强推、无绕过的生效 Ruleset 仅防删除 → PASS。目标生效 Ruleset 即使没有这两项禁令，有绕过者也记 `WINDOW_DRIFT`；经典三个布尔值符合而 `bypassForcePushAllowances.totalCount > 0` 也拒收。缺 `bypass_actors`、401/403、分页不全或 API 失败 → `SOURCE_UNAVAILABLE`，经典保护合格不豁免。
- 真实 Git 父链夹具核错创世、非单父、改删旧事件、跳号、非法路径/字段；普通写者无签章或用非授权密钥快进伪造 `retire_head`、`void` 时全账本拒收，不采信伪造事件。
- 仅有按序的预期封包关闭时，#1403 同窗独立复验通过；封包后 `void`、`retire_head` 或后继意图，或受约束票在 W0 同秒或之后发生任何非豁免状态变更，均拒收旧包。报告生成后令 #1360 重开、再以 `CLOSED/COMPLETED` 关闭；即便 F、锚、运行选择及终态与报告完全相同，两条原始事件仍使 #1403 记 `WINDOW_DRIFT`、判 FAIL。对照只修改 `state_reason` 同样作废；漏任一时间线页记 `SOURCE_UNAVAILABLE`。模拟三项关票条件逐一缺失，未验收和重试保持 #1391 `OPEN`，零提前关闭事件。

其余夹具须覆盖：TB-07/08/09 映射、#1096/#1319 仅令各自 Destination 失败、同 run 首次 failure 后重跑 success、规范源不可读及可读缺项均给 FAIL、四类缺列/错列与合法未启用边界、`key` 四种后缀组合与 `ticket/slot` 分隔符和 `none`、适配器缺件/异字节/锚失败、#2133 无效授权、可延期与必跑未跑，以及改一个合法标量造成精确 `REPORT_MISMATCH`。#1403 以原件为输入独立实跑，对比双方结果。
