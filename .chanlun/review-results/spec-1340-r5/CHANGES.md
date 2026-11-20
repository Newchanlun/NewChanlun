# SPEC #1340 R5 修订对照

改前行号以 `body-041cbf75968c.md` 为准；开工前 GitHub 正文与该副本逐字一致。源为 `review-20261120-r4.json`（所审正文摘要 `041cbf75968c46d7c97cca18a22f38acad79311f459da65cb9a7324163a7478c`）及其独审报告。本轮只恢复以下已裁前件；逐处复核见 [CONDITIONS-CHECK.md](CONDITIONS-CHECK.md)。

## H1 · 塔高预算不等于还有一级可算

[#1603 裁定](https://github.com/Newchanlun/NewChanlun/issues/1603#issuecomment-6308897078)要求两条件同时成立；[tower-level-budget.json:7–13](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/rust/src/theta_v0/policy_records/tower-level-budget.json#L7-L13)说明下一级单位数门，[pipeline.rs:1781–1790](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/rust/src/theta_v0/classifier/pipeline.rs#L1781-L1790)区分不足时的 NATURAL。AT-01 固定同一预算，通过改变下一级材料数区分两个结果；阈值正好 3 已算「足够」。其他状态（如段账本拒读）不并入自然终止。

**L260 改前**

~~~markdown
2. 一条纵向主塔只产生一份 Classification。每一级使用相同判定，级别差异只通过真实输入表达。塔底按有效 `tower_base` 构造（默认 `segment`，值域见[zhongshu.md:160–174](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/zhongshu.md#L160-L174)），资源达到有效预算是覆盖截断，不是自然终止。唯一生产 owner 实际执行完整构造；各重、查询层、Python 外壳和前端不得重判。
~~~

**改后**

~~~markdown
2. 一条纵向主塔只产生一份 Classification。每一级使用相同判定，级别差异只通过真实输入表达。塔底按有效 `tower_base` 构造（默认 `segment`，值域见[zhongshu.md:160–174](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/zhongshu.md#L160-L174)）。按[#1603 裁定](https://github.com/Newchanlun/NewChanlun/issues/1603#issuecomment-6308897078)，在有效 `l_max` 处完成本级构造且下一级仍有至少 `min_parts_per_level` 个可升级单元时，报覆盖截断 `INCOMPLETE_RESOURCE_BOUND`；下一级单元不足则为自然终止 `NATURAL`，即使已经达到 `l_max`。唯一生产 owner 实际执行完整构造；各重、查询层、Python 外壳和前端不得重判。
~~~

**L415 改前**

~~~markdown
| AT-01 | 每个 CC 先按有效验收类型核对象域：真正分类不漏不重；角色/集合完整保留、公式依定义计算、描述不造互斥档；真实投影、合法组合构造与程序定义对拍分别成立 | C02/03；全部 ST/CC/LC/G |
~~~

**改后**

~~~markdown
| AT-01 | 每个 CC 先按有效验收类型核对象域：真正分类不漏不重；角色/集合完整保留、公式依定义计算、描述不造互斥档；真实投影、合法组合构造与程序定义对拍分别成立；同设 `l_max=0`、`min_parts_per_level=3`，完成 L0 后下一级仅剩 1 个可升级单元时为 `NATURAL`，剩 3 个（或更多）时为 `INCOMPLETE_RESOURCE_BOUND` | C02/03；全部 ST/CC/LC/G |
~~~

## H2 · 窗内落后继续读，不重建

[ADR 0051:284–296](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0051-per-bar-domain-event-identity-lifecycle-contract.md#L284-L296)区分出窗、链与快照的一致性、旧代际/旧 writer_epoch。AT-04 用游标 10 跟进 cut 11 和游标 9 实际出窗作对照；另核不一致及旧代拒收。

**L333 改前**

~~~markdown
4. S 的长期历史使用内容寻址的不可变批次对象和版本索引；先持久写完整对象，再由同一 S 事务发布可达引用，崩溃留下的不可达对象可以回收。发布读数从短事务取得固定 cut 的不可变引用，分页不持有写事务或跨请求读事务。持久 delta 按有效 `delta_retention` 策略（默认 `retain_all`）存储，落后消费者收到 Gap 并从指定 cut 重建。
~~~

**改后**

~~~markdown
4. S 的长期历史使用内容寻址的不可变批次对象和版本索引；先持久写完整对象，再由同一 S 事务发布可达引用，崩溃留下的不可达对象可以回收。发布读数从短事务取得固定 cut 的不可变引用，分页不持有写事务或跨请求读事务。持久 delta 按有效 `delta_retention` 策略（默认 `retain_all`）存储。按[ADR 0051:284–296](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0051-per-bar-domain-event-identity-lifecycle-contract.md#L284-L296)，同会话、同代际、同 `writer_epoch` 且租约有效时，游标虽落后于最新 cut，只要仍在可用保留窗内且 delta 链完整可验（应用结果与对应快照逐字段相等），就返回 delta 正常续接。游标落出保留窗或续接一致性失败，才返回 Gap 并给出重建 cut；旧代际或旧 `writer_epoch` 另行拒收。
~~~

**L418 改前**

~~~markdown
| AT-04 | 同 cut 分页/快照等于 delta 续接，Gap/代际/会话隔离正确；撤回与替代原子可查 | C08；FE-09 |
~~~

**改后**

~~~markdown
| AT-04 | 同 cut 分页/快照等于 delta 续接，撤回与替代原子可查；同会话同代同 epoch、租约有效，`retain_all` 下最新 cut=11、游标=10 且 10→11 的 delta 完整可验，正常续接不重建；保留窗从 10 开始且 9→10 已不可用时，游标 9 收到 Gap 与重建 cut。窗内链与快照不一致时也报 Gap；旧代际/epoch 独立拒收，异会话不得续接 | C08/09；FE-09 |
~~~

## 逐处复核追加 · C10.3 的 none 不把限价价规施于市价

[ADR 0033:10–27](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L27)区分限价穿越与市价 exec_index 收盘槽，[ADR 0033:89–116](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L89-L116)区分两种资格且 none 沿用原全量合同。R4 句末把穿越变成所有全量成交的前件。对照：已准入规模内、合法市价单到 exec_index，none 下按收盘槽成交，不要求穿越不存在的限价。原有限价规则、场所容量和缺标定分支不改。

**L348 改前**

~~~markdown
   默认 `history-sim/bar-batch-known-frontier/1` 为确定性模型，`seed: none`，容量来源默认 `scenario_contract`。选中获准 v1 时，第 t 根 bar 只消费 t−1 收盘时已知且获准的集合；同批各重限价独立对 OHLC 判定、开盘取优，`intra_batch_order: Unknown`。限价按有效 `fill_rule`（默认至少 1 tick 的严格穿越，更大缓冲须有标定，touch 仅诊断）与既裁 GTC、费用和双滑点纪律。市价仅在具名 `exec_index` 收盘槽成交，限价逻辑先于该槽；t 收盘才知道的新挂/撤/改从 t+1 起生效。部分成交依具证容量合同（含[ADR 0033:77–116](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L77-L116)的容量 epoch）；容量合同取 `none` 时，已准入规模内满足穿越条件才全量成交，单列为 L0 假设，不作容量证据。历史投影默认 `per_leg`，与场所对拍使用该场所冻结的同一 `projection_kind`。TestOnly 排序只验协议。
~~~

**改后**

~~~markdown
   默认 `history-sim/bar-batch-known-frontier/1` 为确定性模型，`seed: none`，容量来源默认 `scenario_contract`。选中获准 v1 时，第 t 根 bar 只消费 t−1 收盘时已知且获准的集合；同批各重限价独立对 OHLC 判定、开盘取优，`intra_batch_order: Unknown`。限价按有效 `fill_rule`（默认至少 1 tick 的严格穿越，更大缓冲须有标定，touch 仅诊断）与既裁 GTC、费用和双滑点纪律。市价仅在具名 `exec_index` 收盘槽成交，限价逻辑先于该槽；t 收盘才知道的新挂/撤/改从 t+1 起生效。部分成交依具证容量合同（含[ADR 0033:77–116](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L77-L116)的容量 epoch）；容量合同取 `none` 时，在已准入规模内，限价单满足其穿越条件、市价单到其具名收盘槽才按各自路径全量成交，单列为 L0 假设，不作容量证据。历史投影默认 `per_leg`，与场所对拍使用该场所冻结的同一 `projection_kind`。TestOnly 排序只验协议。
~~~

## 逐处复核追加 · G-002 同价取先的比较域

[#1343 裁定 Q1](https://github.com/Newchanlun/NewChanlun/issues/1343#issuecomment-6153028395)和[bi.md:313–332](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/bi.md#L313-L332)要求相邻同型且量化后精确相等。中间若有合法的反型端点，两同价同型分型不是同一次相邻比较；否则会错误丢掉后一个笔端点。未改极值根集合、raw 间隔和同价身份。

**L392 改前**

~~~markdown
| G-001/002 | 初始化 W（[#1342 resolution](https://github.com/Newchanlun/NewChanlun/issues/1342#issuecomment-6149622771)）：首个相邻 raw 严格非包含对出现前按 raw 留未定，不产合并组；若始终不出现则保持未定。出现时以其方向从序号 0 左折叠并发布，替代关系可查，旧 cut 不回填。同型同价端点取先，后者身份仍留；实际极值根取集合，raw 间隔取前端末根到后端首根之间（[#1343 resolution](https://github.com/Newchanlun/NewChanlun/issues/1343#issuecomment-6153028395)）。 | [#1393](https://github.com/Newchanlun/NewChanlun/issues/1393) 的 W 发布（含 `pending_since_cut`）、替代、增量和恢复对拍；[#1405](https://github.com/Newchanlun/NewChanlun/issues/1405) 承接同价行为锁，按其实际版本取证；保留对应 Lean 定义与证明义务。 |
~~~

**改后**

~~~markdown
| G-001/002 | 初始化 W（[#1342 resolution](https://github.com/Newchanlun/NewChanlun/issues/1342#issuecomment-6149622771)）：首个相邻 raw 严格非包含对出现前按 raw 留未定，不产合并组；若始终不出现则保持未定。出现时以其方向从序号 0 左折叠并发布，替代关系可查，旧 cut 不回填。相邻同型分型在 tick 量化后价格相等时端点取先，后者身份仍留；实际极值根取集合，raw 间隔取前端末根到后端首根之间（[#1343 resolution](https://github.com/Newchanlun/NewChanlun/issues/1343#issuecomment-6153028395)）。 | [#1393](https://github.com/Newchanlun/NewChanlun/issues/1393) 的 W 发布（含 `pending_since_cut`）、替代、增量和恢复对拍；[#1405](https://github.com/Newchanlun/NewChanlun/issues/1405) 承接同价行为锁，按其实际版本取证；保留对应 Lean 定义与证明义务。 |
~~~

## 逐处复核追加 · AT-17 区分配置错误与证据不足

[ADR 0022:153–167](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0022-acceptance-criterion-parameters.md#L153-L167)规定：缺门记录/字段或值越界时显式报错、停止且不出验收读数；[ADR 0036:11–22](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0036-operating-statistics-sampling-and-post-gate-parameter-protocol.md#L11-L22)规定证据不足是有效合同下的具名输出。原句只说「不报通过」，容许无记录时继续生成未通过的读数，或误记样本不足。本次分开这两条分支；每个样本、预登记时间门与其他正式结果不改。

**L434 改前**

~~~markdown
AT-17 的正式读数按[ADR 0022:97–167](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0022-acceptance-criterion-parameters.md#L97-L167)绑定本次运行读取评价数据前已生效的 `evidence_gate` 与已冻结的逐窗起讫表；用起讫核窗不重叠，报告逐重每窗下界、样本/块数及合计覆盖，全史区间取数据集首末 bar。用费后速率的单边分块 bootstrap 下界，每窗各自过线（下界大于 0），汇总与点估计不代门。现行 `#1677/evidence-gate/v1` 为 UTC 日历月分块、单边 95% 下界（第 5 百分位）、每窗至少 30 样本和 12 月块、至少 3 窗、合计覆盖至少全史的 1/2。用有效记录取值，不写死 v1；门缺失、越界或证据不足不报通过。
~~~

**改后**

~~~markdown
AT-17 的正式读数按[ADR 0022:97–167](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0022-acceptance-criterion-parameters.md#L97-L167)绑定本次运行读取评价数据前已生效的 `evidence_gate` 与已冻结的逐窗起讫表；用起讫核窗不重叠，报告逐重每窗下界、样本/块数及合计覆盖，全史区间取数据集首末 bar。用费后速率的单边分块 bootstrap 下界，每窗各自过线（下界大于 0），汇总与点估计不代门。现行 `#1677/evidence-gate/v1` 为 UTC 日历月分块、单边 95% 下界（第 5 百分位）、每窗至少 30 样本和 12 月块、至少 3 窗、合计覆盖至少全史的 1/2。用有效记录取值，不写死 v1；门记录或字段缺失、值越界时显式报错并停止，不出验收读数；门有效但样本或窗口证据不足时，报 `InsufficientEvidence`，不报通过。
~~~

## 发布交接

- 文末仅追加 R5 记录；六项 Destination、TB 顺序、资金/账户/凭据/真实外效权限门、原签署与归档不变。
- R4 两项条件性待裁以 [R4 原登记](https://github.com/Newchanlun/NewChanlun/blob/0da193a14675dd0ebfaf7f13dd1e9ca7488baff3/.chanlun/review-results/spec-1340-r4/NEEDS-DECISION.md) 为准，本轮不改登记、不新开票。
- 本轮验证的是文书反例及交付完整性，不是实装业务验收。由主控发布新稿后，另跑绑定实际正文的非作者独审；证据分支不授权实施。
- Wayfinder 的 `parseSplitPlan` 对本稿仍返回 null，引擎不会据此创建实施票。已有原生 SPEC 子树内未带拆票标记的票，在全部祖先 SPEC 均有当前正文的有效 PASS、且票自身准入条件满足后，可走子树放行。仅挂在 map 下靠此 SPEC 授权的票、以及带该 SPEC 拆票标记但对不上计划项的票不会因此放行；计划项须带当前正文发布凭据。见 [wayfinder_engine.mts:934–960](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/scripts/wayfinder_engine.mts#L934-L960)。
