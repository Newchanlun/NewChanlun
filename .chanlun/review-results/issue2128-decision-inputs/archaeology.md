# #2128 考古

[grilling] S 被强杀后带 SHM 的介质怎样再准入，恢复后的有效代怎样交接（#2079 设计发现，#1411 前置）

归类：A 已裁 4 · B 有先例未正式裁 2 · C 确未设计 1。C 类 decision 由起草者按推荐答案裁定；B 类默认值由起草者采纳或附依据否决；A 类直接沿用。

## Q1 [A] 正常启动的介质判断是否因上代死亡放宽？

| 路 | 查询词 | 命令 | 命中数 |
|---|---|---|---|
| tracker | "UnsupportedWalShmJournalCombination" in:body,comments | `gh issue list --repo Newchanlun/NewChanlun --state all --search '"UnsupportedWalShmJournalCombination" in:body,comments' --limit 100 --json number,state,title,url` | 5 |
| tracker | SHM R4 in:body,comments | `gh issue list --repo Newchanlun/NewChanlun --state all --search 'SHM R4 in:body,comments' --limit 100 --json number,state,title,url` | 9 |
| repo | UnsupportedWalShmJournalCombination\|介质再准入\|R4.{0,15}SHM\|SHM.{0,15}R4 | `git grep -nE 'UnsupportedWalShmJournalCombination\|介质再准入\|R4.{0,15}SHM\|SHM.{0,15}R4' b9d898dccf46c2a716115eaa1215bc39c458a959 -- docs/adr .chanlun/definitions analysis rust/src/bin/s_session_v3 s_session` | 3 |

命中：
- rust/src/bin/s_session_v3/admission_provider.rs:225–233：未证明私有残留先拒；E6 对 SHM 存在或 WAL/journal 并存具名拒绝。
- https://github.com/Newchanlun/NewChanlun/blob/d18e70fad7aae91156ac28860acab1132a076bea/docs/adr/0065-production-session-endpoint-ownership.md#L49-L65：第 10 条明确保留 S 的 R4、Begin、epoch；第 77 行记可认领端点下首错是 R4。
- https://github.com/Newchanlun/NewChanlun/issues/1411#issuecomment-6991449080：Linux 非空 S 的 SIGTERM 回收留下 WAL 354,352 B、SHM 32,768 B 且无 FD 持有者；只隔离端点复跑时 R4 拒绝。该次退出信号不是 SIGKILL。
- https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6687775294：三种布局的原样 SIGKILL 复跑先触发 socket 预筛，尚未到 E6。

- 出处：rust/src/bin/s_session_v3/admission_provider.rs:225–233

## Q2 [A] 哪个域持何锁，端点与库有无先代资格互认？

| 路 | 查询词 | 命令 | 命中数 |
|---|---|---|---|
| tracker | "原会话端点" in:body,comments | `gh issue list --repo Newchanlun/NewChanlun --state all --search '"原会话端点" in:body,comments' --limit 100 --json number,state,title,url` | 4 |
| tracker | "残留 socket" in:body,comments | `gh issue list --repo Newchanlun/NewChanlun --state all --search '"残留 socket" in:body,comments' --limit 100 --json number,state,title,url` | 6 |
| repo | 残留.*socket\|socket.*残留\|维护锁\|maintenance\.lock\|prepare_socket | `git grep -nE '残留.*socket\|socket.*残留\|维护锁\|maintenance\.lock\|prepare_socket' b9d898dccf46c2a716115eaa1215bc39c458a959 -- docs/adr .chanlun/definitions analysis rust/src/bin/s_session_v3/admission.rs s_session/s_service_control.py` | 12 |

命中：
- docs/adr/0039-production-entry-inventory-and-unique-launcher.md:273–298：本域拥有锁/写权，launcher 只装配。
- rust/src/bin/s_session_v3/admission.rs:19–65,324–343：原 E5 顺序 writer → maintenance，路径与 FD 身份复核，显式解锁。
- https://github.com/Newchanlun/NewChanlun/blob/d18e70fad7aae91156ac28860acab1132a076bea/docs/adr/0065-production-session-endpoint-ownership.md#L49-L65：持锁端点认领不证明数据库可恢复；S 只读预筛，持锁并过本域门后才实际认领。
- s_session/s_service_control.py:711–748,882–915：Python 继承旧独立控制器行为，与 Rust 唯一正式 launcher 并非同一入口。

- 出处：docs/adr/0039-production-entry-inventory-and-unique-launcher.md:273–298

## Q3 [A] 恢复能否自建锚或切换资源预算？

| 路 | 查询词 | 命令 | 命中数 |
|---|---|---|---|
| tracker | "准入合同" in:body,comments | `gh issue list --repo Newchanlun/NewChanlun --state all --search '"准入合同" in:body,comments' --limit 100 --json number,state,title,url` | 10 |
| tracker | "AwaitingMeasurement" in:body,comments | `gh issue list --repo Newchanlun/NewChanlun --state all --search '"AwaitingMeasurement" in:body,comments' --limit 100 --json number,state,title,url` | 2 |
| repo | AwaitingMeasurement\|无锚自动接管\|八项.*(上限\|峰值)\|原启动绝对期限 | `git grep -nE 'AwaitingMeasurement\|无锚自动接管\|八项.*(上限\|峰值)\|原启动绝对期限' b9d898dccf46c2a716115eaa1215bc39c458a959 -- docs/adr .chanlun/definitions analysis rust/src/bin/s_session_v3/admission_anchor.rs rust/src/bin/s_session_v3/admission_issuance.rs` | 15 |

命中：
- docs/adr/0046-s-admission-anchor-issuance-and-takeover.md:17–55：锚绑定库及八项资源限额；不得无锚接管、追认或让实施自填数。
- docs/adr/0050-s-resource-admission-contract-v1.md:8–35：登记值七项 AwaitingMeasurement，现版本全局拒签；内嵌登记唯一，本票不提供待测数值。
- https://github.com/Newchanlun/NewChanlun/issues/1675：承接主线正式成功回执、已有签锚程序和资源测量；不能拿 D2 试验值替代。

- 出处：docs/adr/0046-s-admission-anchor-issuance-and-takeover.md:17–55

## Q4 [B] S 本域怎样保留原 cut、结 Begin 并使具名恢复幂等？

| 路 | 查询词 | 命令 | 命中数 |
|---|---|---|---|
| tracker | "具名恢复" in:body,comments | `gh issue list --repo Newchanlun/NewChanlun --state all --search '"具名恢复" in:body,comments' --limit 100 --json number,state,title,url` | 3 |
| tracker | "未完成Begin" in:body,comments | `gh issue list --repo Newchanlun/NewChanlun --state all --search '"未完成Begin" in:body,comments' --limit 100 --json number,state,title,url` | 5 |
| repo | RecoverHandoff\|recovered_begin\|last_recovered_begin\|未完成.{0,6}Begin\|恢复幂等\|resume_pending | `git grep -nE 'RecoverHandoff\|recovered_begin\|last_recovered_begin\|未完成.{0,6}Begin\|恢复幂等\|resume_pending' b9d898dccf46c2a716115eaa1215bc39c458a959 -- docs/adr .chanlun/definitions analysis rust/src/bin/s_session_v3 s_session/s_service_control.py` | 34 |

命中：
- rust/src/bin/s_session_v3/audit_owner.rs:1802–1875：当前 Recover 在 IMMEDIATE 内核规则、旧代及恢复时钟，结 Begin，同事务记跃迁；现输出未持久具名。
- https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/economic_session/recovery.rs#L27-L154：E/B 以具名身份保存请求及规范回执，按 from+1，历史查询与当前授权分离。
- rust/src/bin/s_session_v3/driver.rs:800–829,7659–7742：新 Driver 按数据库中的原字节续 pending；原先例验证早期 cut 和已接纳身份。
- https://github.com/Newchanlun/NewChanlun/issues/1411#issuecomment-7002229803：具名 E/B 原件丢回包重取已独审运行；S 不在该增量范围。

- 出处：rust/src/bin/s_session_v3/audit_owner.rs:1802–1875
- 推理链：旧 S recover 负责业务事务，E/B 已有精确防二次升代的命名规则；合起来可避免丢回包重试抹掉原身份。
- 默认值：沿用 S 唯一 Recover 事务；具名请求固定 N 与切面，N+1 与原回执一次持久，query/current 分开。
- 冲突：旧 S recover 允许显式更大代；不收窄其原调用者。新具名操作只接受 N+1。

## Q5 [B] 已核本域写者代如何交给 launcher 与其他域？

| 路 | 查询词 | 命令 | 命中数 |
|---|---|---|---|
| tracker | "authority_epoch" in:body,comments | `gh issue list --repo Newchanlun/NewChanlun --state all --search '"authority_epoch" in:body,comments' --limit 100 --json number,state,title,url` | 3 |
| tracker | "authorized_sources" in:body,comments | `gh issue list --repo Newchanlun/NewChanlun --state all --search '"authorized_sources" in:body,comments' --limit 100 --json number,state,title,url` | 1 |
| repo | authority_epoch\|authorized_sources\|authority_profile\|同轨迹\|连续参照 | `git grep -nE 'authority_epoch\|authorized_sources\|authority_profile\|同轨迹\|连续参照' b9d898dccf46c2a716115eaa1215bc39c458a959 -- docs/adr .chanlun/definitions analysis rust/src/history_simulation/runtime.rs rust/src/bin/production_session.rs` | 11 |

命中：
- https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/bin/production_session.rs#L249-L342：E/B 先调本域 current-recovery，launcher 取有效代而不写库。
- https://github.com/Newchanlun/NewChanlun/issues/2129：E 授权来源及 X 冻结权威代有独立决策；S 回执必须保留旧→新证据。
- rust/src/history_simulation/runtime.rs:506–517,815–831：回复与冻结身份/代硬判；不能靠改整数绕开。
- docs/adr/0059-production-session-layout-contract.md:89–124：布局静态判定不等于实际原件或 writer 资格。

- 出处：https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/bin/production_session.rs#L249-L342
- 推理链：把当前性验证留给域内同锁事实，launcher 才能在不读库或编辑 manifest 的条件下提供代。
- 默认值：S current-recovery 严格核当前持久回执；launcher 消费，S 在 serve 锁下复核，跨域投影由 #2129 独立实现。
- 冲突：原 launcher 传静态 s.writer_epoch；新增显式具名选项，不改变未选项入口。

## Q6 [C] 怎样受控收尾原 WAL/SHM，不以原 R4 失败触发兜底？

| 路 | 查询词 | 命令 | 命中数 |
|---|---|---|---|
| tracker | "wal_checkpoint" in:body,comments | `gh issue list --repo Newchanlun/NewChanlun --state all --search '"wal_checkpoint" in:body,comments' --limit 100 --json number,state,title,url` | 2 |
| tracker | "删除 WAL" in:body,comments | `gh issue list --repo Newchanlun/NewChanlun --state all --search '"删除 WAL" in:body,comments' --limit 100 --json number,state,title,url` | 2 |
| repo | NO_CKPT_ON_CLOSE\|wal_checkpoint\|ColdConvertedContent\|WAL.{0,12}收尾\|从.{0,5}签锚.{0,6}重建 | `git grep -nE 'NO_CKPT_ON_CLOSE\|wal_checkpoint\|ColdConvertedContent\|WAL.{0,12}收尾\|从.{0,5}签锚.{0,6}重建' b9d898dccf46c2a716115eaa1215bc39c458a959 -- docs/adr .chanlun/definitions analysis rust/src/bin/s_structure_session.rs rust/src/bin/s_session_v3 s_session` | 22 |

命中：
- rust/src/bin/s_session_v3/admission_private/mod.rs:624–740：已有只读 fd/WAL 视图、计量及 quick_check；不创建 SHM 或写源。
- rust/src/bin/s_structure_session.rs:440–495：H1 冷认证后独占 WAL 转换与物理交接，但并不处理已有残留 SHM。
- probe/wal.py 与 probe/boat.txt：Linux 小探针：NORMAL checkpoint 与最后关闭清掉已有 SHM；EXCLUSIVE checkpoint 成功也留旧 SHM。无 SHM 的 EXCLUSIVE 在提交后真杀只留可读 WAL。
- https://github.com/Newchanlun/NewChanlun/issues/1568：资源/旧介质调查先例不是原址强杀后受准跨域回执合同。

- 推理链：同原库 SQLite 写权限已有，但 R4 前的受限托管、商业恢复事务、丢回包闭合与交接组合未裁。锚只签资源，无可载入的历史快照。
- 推荐值：选显式动作：先计量固定切面，只允许受控 SQLite NORMAL WAL 收尾，然后原 R4 与同一个 S Recover，具名写连接不产生新的 SHM。
- 已搜关键词：wal_checkpoint、删除 WAL、NO_CKPT_ON_CLOSE、ColdConvertedContent
- 缺口去向：起草者按推荐答案裁定
- 冲突：读到成功的 TRUNCATE 不等于没有 SHM；Linux 正负探针已区分。孤立 SHM 保全而不自动清理。

## Q7 [A] 正式验收消费哪些原件与阻塞边？

| 路 | 查询词 | 命令 | 命中数 |
|---|---|---|---|
| tracker | "TB-07-C" in:body,comments | `gh issue list --repo Newchanlun/NewChanlun --state all --search '"TB-07-C" in:body,comments' --limit 100 --json number,state,title,url` | 10 |
| tracker | "cut-1" "SHM" in:body,comments | `gh issue list --repo Newchanlun/NewChanlun --state all --search '"cut-1" "SHM" in:body,comments' --limit 100 --json number,state,title,url` | 4 |
| repo | checkpoint 恢复\|同一故障\|段.*恢复\|不重发\|H2.*恢复\|完整历史双跑 | `git grep -nE 'checkpoint 恢复\|同一故障\|段.*恢复\|不重发\|H2.*恢复\|完整历史双跑' b9d898dccf46c2a716115eaa1215bc39c458a959 -- docs/adr .chanlun/definitions analysis rust/tests/production_session_entry.rs` | 33 |

命中：
- https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md#L324-L334：C09.3 按域隔离、4–6 S 发布/队列/事实、7 epoch、8 X 边界、9 S 独立恢复、10–11 历史/迁移。
- https://github.com/Newchanlun/NewChanlun/issues/1411：正式入口，真杀前后，业务六面/AsKnown、旧责任与不重发，独立 oracle。
- https://github.com/Newchanlun/NewChanlun/blob/15ffe5083724a858e1f0fc669f457f8e6451d84d/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L159-L185：#2127 候选将同轨迹全量比较与对连续参照分开；实施取获审版本。
- source/edges-2128-blocking.json、source/parent-2128.json：原生边 #2128 → #1411；父票 #1366。#2129 也独立阻挡 #1411。

- 出处：https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md#L324-L334

## 机械校验

通过。
