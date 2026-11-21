# #2129 考古

E/S 恢复升代后，X 冻结的权威代与 E 的授权来源怎样跟随

归类：A 已裁 1 · B 有先例未正式裁 3 · C 确未设计 0。C 类 decision 由起草者按推荐答案裁定；B 类默认值由起草者采纳或附依据否决；A 类直接沿用。

## Q1 [B] X 对 E/S 的冻结代凭什么、何时、怎样跟随？

| 路 | 查询词 | 命令 | 命中数 |
|---|---|---|---|
| tracker | authority_epoch 冻结 OR authority_profile 升代 X | `gh issue list --repo Newchanlun/NewChanlun --search 'authority_epoch 冻结 OR authority_profile 升代 X' --state all --limit 40 --json number,title,state --jq '.[] \| [.number,.state,.title]\|@tsv'` | 3 |
| tracker | "旧写者" "原收据" 恢复 | `gh issue list --repo Newchanlun/NewChanlun --search '"旧写者" "原收据" 恢复' --state all --limit 40 --json number,title,state --jq '.[] \| [.number,.state,.title]\|@tsv'` | 4 |
| repo | authority_epoch\|authority_profile\|具名恢复\|写者履历 | `git grep -n -E 'authority_epoch\|authority_profile\|具名恢复\|写者履历' b9d898dccf46c2a716115eaa1215bc39c458a959 -- docs/adr .chanlun analysis` | 0 |
| repo | authority_profile\|写者履历 | `git grep -n -E 'authority_profile\|写者履历' 15ffe508 -- docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md` | 2 |

命中：
- https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/economic_session/recovery.rs#L112-L153：具名恢复从当前持久代按原 cut 一次升代；current-recovery 原回执只在下一代仍当前时有效。
- https://github.com/Newchanlun/NewChanlun/blob/15ffe5083724a858e1f0fc669f457f8e6451d84d/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L152-L163：新版 X 业务档保存 E/S 权威及代，部署路径另列；旧账不就地改写。
- https://github.com/Newchanlun/NewChanlun/blob/0f0fd605a8412e83276a1caabda8ee74be2513cd/.chanlun/review-results/issue2129-decision-inputs/probe/boat-probe.log#L78-L110：真 E2 对旧请求报 StaleWriter，活 X 报 IdentityConflict；只换 profile 重启仍拒绝。
- https://github.com/Newchanlun/NewChanlun/issues/2128：S 单域恢复与介质/有效代交接；具体具名回执字段由并行工位同步。
- https://github.com/Newchanlun/NewChanlun/issues/1407：精确交付，锁定命令身份与条件，不裁 X 跟随。

- 出处：https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/economic_session/recovery.rs#L112-L153
- 推理链：域持锁的原回执能证明是同一个持久权威而非仅代变大；#2127 允许新增路径无关版型但不改旧档。启动前只核一个有效代，网络拒绝不当作触发器。
- 默认值：X 同库、同自身代；每个变更域的当前原回执原子追加一条绑定，并保留原有资料。
- 冲突：现行冻结比较拒绝新代，E 也会拒旧目标代；#2079 第 9–13 条只证明域再服务，不赋予 X 跟随。

## Q2 [A] E 的 authorized_sources 和 launcher 参数由谁改变、有何证据？

| 路 | 查询词 | 命令 | 命中数 |
|---|---|---|---|
| tracker | authorized_sources OR current-recovery | `gh issue list --repo Newchanlun/NewChanlun --search 'authorized_sources OR current-recovery' --state all --limit 40 --json number,title,state --jq '.[] \| [.number,.state,.title]\|@tsv'` | 9 |
| repo | authorized_sources\|来源纪元\|producer_epoch\|单写者 | `git grep -n -E 'authorized_sources\|来源纪元\|producer_epoch\|单写者' b9d898dccf46c2a716115eaa1215bc39c458a959 -- docs/adr .chanlun analysis` | 128 |

命中：
- docs/adr/0039-production-entry-inventory-and-unique-launcher.md:283–287：launcher 只启动、顺序、监督、换代与指纹，不持域写身份。
- https://github.com/Newchanlun/NewChanlun/blob/d18e70fad7aae91156ac28860acab1132a076bea/docs/adr/0065-production-session-endpoint-ownership.md#L59-L62：域锁定原库，launcher 只核当前回执、装配有效代，B 按 E 的有效代；在线单域交 #2120。
- rust/src/economic_session/store.rs:355–395,993–1004：来讯按四项来源身份与操作核权，启动验持久 manifest_hash；E 自身代与来讯源不是一个字段。
- https://github.com/Newchanlun/NewChanlun/issues/2120：在运转 launcher 下健康域仍持锁的局部重拉另裁，不属于整会话装配。

- 出处：docs/adr/0039-production-entry-inventory-and-unique-launcher.md:283–287

## Q3 [B] 旧代在途、可能已发与完成的交换怎样核证并防复活？

| 路 | 查询词 | 命令 | 命中数 |
|---|---|---|---|
| tracker | MayHaveCalled OR QueryExecuteCommitted | `gh issue list --repo Newchanlun/NewChanlun --search 'MayHaveCalled OR QueryExecuteCommitted' --state all --limit 40 --json number,title,state --jq '.[] \| [.number,.state,.title]\|@tsv'` | 13 |
| repo | MayHaveCalled\|QueryExecuteCommitted\|不重发\|旧代在途 | `git grep -n -E 'MayHaveCalled\|QueryExecuteCommitted\|不重发\|旧代在途' b9d898dccf46c2a716115eaa1215bc39c458a959 -- docs/adr .chanlun analysis` | 143 |

命中：
- https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md#L299-L305：S ExecuteCommitted 只给原收据；X 持久 MayHaveCalled 后无自动重发；无记录或超时不释放责任。
- https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md#L329-L334：X 隔离及在途不因换代消失，原命令/一次占有长期只读可审。
- docs/adr/0051-per-bar-domain-event-identity-lifecycle-contract.md:271–276：同事实同内容回原应用；不同内容硬拒。
- rust/src/history_simulation/runtime.rs:296–448,682–750：现有启动审计和旧证据共用当前 profile；ExecutionRequested 仅查询；ExecutionReady 或 MayHaveCalled 复用持久证据。
- https://github.com/Newchanlun/NewChanlun/issues/1422：一次占有与受控调用为独立实施义务，所有代不得复活旧命令。

- 出处：https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md#L299-L305
- 推理链：已裁责任只能按原身份查；当前网络回话与历史证据分别关联各自发生时有效绑定，不能从当前 profile 推回旧代。
- 默认值：保存持久绑定引用，旧结果从原记录读回；已请求不得重试资格，未请求才按原权威判据首次入场。
- 冲突：现行 QueryCommand 把当前 profile 的 E 代写入旧因果视图，直接覆写 profile 会误标历史。

## Q4 [B] 权威履历怎样进入 #1411 的正反对照而不放宽全状态核验？

| 路 | 查询词 | 命令 | 命中数 |
|---|---|---|---|
| tracker | in:title TB-07 OR "双跑差异" | `gh issue list --repo Newchanlun/NewChanlun --search 'in:title TB-07 OR "双跑差异"' --state all --limit 40 --json number,title,state --jq '.[] \| [.number,.state,.title]\|@tsv'` | 8 |
| repo | H2\|同轨迹重复\|部署位置 | `git grep -n -E 'H2\|同轨迹重复\|部署位置' b9d898dccf46c2a716115eaa1215bc39c458a959 -- docs/adr .chanlun analysis` | 242 |

命中：
- https://github.com/Newchanlun/NewChanlun/blob/15ffe5083724a858e1f0fc669f457f8e6451d84d/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L165-L176：R₁/R₂ 保证同轨迹完整原字节同；R₁/R₂ 对 C 逐面与履历从冻结轨迹独立复核，不删代/根/回执。
- https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md#L336-L343：固定真实输入、故障轨迹、完整状态，不以分量末值代替。
- https://github.com/Newchanlun/NewChanlun/issues/1411：真实结束域并正式恢复，从原 cut 续接；#2127、#2128、#2129 各有入边。

- 出处：https://github.com/Newchanlun/NewChanlun/blob/15ffe5083724a858e1f0fc669f457f8e6451d84d/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L165-L176
- 推理链：主线 ADR 0038 的 H2 连续参照已裁；更细的同轨迹/跨轨迹比较以同轮 #2127 固定候选作相邻合同。
- 默认值：原样沿用 #2127 分法，双跑另核权威绑定履历，不屏蔽代/根/因果。

## 机械校验

通过。
