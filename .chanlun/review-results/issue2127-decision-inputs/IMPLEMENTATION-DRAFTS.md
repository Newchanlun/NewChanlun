# 下游实施票草稿（由主控开票）

本票交文档；以下测试名及 CLI 数据约定为落地验收，尚未实现或运行。各票沿原有唯一写者、正式 launcher 与 Q/档案读口，不增加可写镜像。源提交基线见 [代码事实](CODE-FACTS.md)。

## I1 — [impl] 新会话分离 E/B/X 业务承诺与本机部署，旧档按原切面只读

**范围**：一条从正式生产入口到存储和公开档案读口的纵切。新增显式持久版本，冻结有类型的业务/部署清单；E/B 业务 manifest 承诺、Voice 新版 bundle/独评与内容闭包，E/B 跨域 proof、X simulation profile 一起保证新写不把本机路径传入业务表/根。分别绑定部署映射、同址重启、权限/资源及物理布局检查。旧版本的档案读取、根校验、AsKnown 与存量活账在原合同内的只读审计/续服保持；不接管任何旧活账，不调整策略、账或外部发送。采用现有内容库/档案能力，实施先列出当前支持的 `economic-session`、Voice、FIN、X profile 组合与目标版本号，禁止隐式回落。

**验收（Linux / CI 或 Boat，现有组件负控可复用但需绑定新调用入口）**：

- `cargo test --test production_session_entry ledger_deployment_paths_isolated`：正式 launcher 两个新进程、相同业务输入和固定会话业务身份，分别使用不同长短的绝对目录/库/锁/socket/Voice 文件位置。实际产 BindVoice、B→E 与 E→B 的 proof、X 权威交换和非空原重入账（成交及费用）。枚举版本规定的实际 SQLite 业务库全部表、逐行规范字节与 E/B 根链，零差异；部署原件位置不同且各自有效。不能用删字段的导出或相同逻辑挂载字符串通过。单一模型/夹具的证明射程如实列；真实 γ 的独立验证不能被单元夹具取代。
- `cargo test --test production_session_entry voice_artifact_closure_path_independent`：版本固定的 bundle/独评按内容地址在新位置能验证；原目录不可访问仍能独立读出全部所需 blob 与原收据。替换一份同名原件、改变摘要/长度/位序、异权威、错独评、漏一 evidence ID 或断开证明引用：失败且不写业务。另核同目录但内容不同能被侦测，不能把「paths gone」当作核证。
- `cargo test --test production_session_entry ledger_archive_original_verifiers`：冻结真实旧版样本（含不同目录的旧根、B→E→B、X profile），迁走原目录并禁用旧 socket，只读核原 `AsKnown`、原 `manifest_hash`、回执/根和全链引用；旧同路径对拍成功，旧不同路径仍有原本根差。损坏任何旧原件或旧配置、删必要 WAL/外部原件、混用版本/链或旧程序打开新写格式失败；无 DDL、写入、根或时点变化。旧归档缺 artifact 时可区分根可核与完整证据失败，不把缺件变新 ID。
- `cargo test --test production_session_entry x_authority_not_socket_identity`：两个独立空库不同各自合法位置，X 业务冻结等同；同一既存部署不准直接改三个 socket 或换 S/E 身份/authority_epoch。正常原址续服保持原写权和原收据。对实际 reply 的来源、代、schema 和条件设负控，不用位置相等作通过依据。E/S 升代成功交接另由 #2129。

**阻塞边（拟）**：`#2127 → I1`（正本确认后新写）；`I1 → I2`（#1411 的异目录正例需真写入）。与 #1425、#1407、#1769 及 #2079 实施协调版本与入口，不把本票挂成 #1425/#1406 的整票 blocker。可先写读档向量及结构测试，正式原址故障恢复验收继续等待既有 #2079/#2128/#2129 各自条件。

## I2 — [impl] #1411 正式全状态差异报告接入冻结双跑计划与原根核验

**范围**：验收夹具与报告器，不改生产判据。#1411 owner 冻结唯一版本的计划与独立记录，分别启动两臂；严格枚举六面、checkpoint、业务表和引用。报告输出非 0 = FAIL，只有受测各面齐全并全相等才返回 0。实验/生产的真实外效权限不因本票变化；H2 的真实中断仍按 #1411 完整边界和 ADR 0038 #1539 修订。

**验收**：

- `cargo test --test production_session_entry dual_run_frozen_plan_strict_roots`：复用 I1 异目录输入，报告通过，附启动前计划和逐臂回执、全部检查点、两臂原根与完整输出；有头部标签时合法一一映射通过，没标签且计划为空也通过。两臂进程、介质、端点隔离，完整业务 `session_id` 等固定。旧异目录样本报告以非 0 返回，实际列出最早变根和后继，不删 manifest/根，不换版本重试。
- `cargo test --test production_session_entry dual_run_rejects_unexplained_difference`：先后登记伪造、迟登记、臂互换、重复/未知/未声明字段、藏在见证里的 run_id、缺一表/行/检查点、变一笔费用或 AsKnown、替换真实域/代/TStage/事实键/因果引用、仅变根而总账不变，分别有明确 FAIL 与位置；不得用 advisory、inconclusive、仅终态或最终净仓放行。
- `cargo test --test production_session_entry dual_run_h2_recovery_strict_archive`：真实中断各域提交前后及回报/应用边界，原址按现行恢复门续接，与同轨迹参照全状态对拍；原收据、旧代在途、最大责任、晚到获知时刻、不可重复调用均核，还须用独立 oracle 对业务关键量。#1425 的 E/B 示例不是 S/X 恢复通过证据。

**阻塞边（拟）**：`#2127 → I2`、`I1 → I2 → #1411`（依赖的是正式验收；若主控把 I2 并入 #1411，就直接 `I1 → #1411`，不重复票）。保留 `#2127 → #1411` 的裁定边及 #1411 原前置。#1381、#1418、#1387 / #1551 只消费同一正式证据及原有汇总链，不横挂整票 blocker。
