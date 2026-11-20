# SPEC #1340 R4 修订对照

改前行号按 `body-2f422bd8f812.md`。本次依 `review-20261120-r3.json`，绑定受审正文 `2f422bd8f8120dcb0170fe20dd73f0582579b4b526c2c3e2179c09e102ef3e34`。

## B1

**L98 改前**

~~~markdown
23. **US-ST-023** 作为结构观察者，我需要完整处理「背驰先结构配对后力度及范围边界」并能查看完整结构候选集与正式比较对分别存，Comparable 与固定 Sel 按 G-026 的已裁对象域承接，以便核对实际状态、依据及其变化。（C03, C08, C12）
~~~

**改后**

~~~markdown
23. **US-ST-023** 作为结构观察者，我需要完整处理「背驰先结构配对后力度及范围边界」并能查看完整结构候选集与正式比较对分别存，Comparable 按 G-026 的已裁对象域承接，Sel 读取有效 `selector_keys` 并保留版本，以便核对实际状态、依据及其变化。（C03, C08, C12）
~~~

依据：[qujiantao.md:1543–1551](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/qujiantao.md#L1543-L1551)。

**L277 改前**

~~~markdown
2. 候选全集、Comparable/Extreme 等实际适用条件、已固定 Sel、选中对象的完整链及失败原因一并保存。全候选任一通过只是观察信息，不可在选中失败后改选以放行同一判断。
~~~

**改后**

~~~markdown
2. 候选全集、Comparable/Extreme 等实际适用条件、本次运行全级共用的有效 `selector_keys` 及其选中身份、选中对象的完整链及失败原因一并保存。全候选任一通过只是观察信息，不可在选中失败后改选以放行同一判断。
~~~

依据：[qujiantao.md:1543–1551](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/qujiantao.md#L1543-L1551)。

**L393 改前**

~~~markdown
| G-026 | [#1346 resolution](https://github.com/Newchanlun/NewChanlun/issues/1346#issuecomment-6154425014)：已裁 Comparable 与 Sel 可直接复用。闭合候选先按 Dir/Comparable/Extreme 及子区间条件过滤。按 end 最新、start 最新、idx 最小选定，再核所选后门；全候选真值只供观察。 | 按该 resolution 的 I-1～I-8：[#1439](https://github.com/Newchanlun/NewChanlun/issues/1439) 承接全集、所选及观察事实，TB-04 承接后门 predicate_id，TB-07 承接 selector_version，Lean 跟进键序等价。 |
~~~

**改后**

~~~markdown
| G-026 | [#1346 resolution](https://github.com/Newchanlun/NewChanlun/issues/1346#issuecomment-6154425014)：已裁 Comparable 与 Sel 可直接复用。闭合候选先按 Dir/Comparable/Extreme 及子区间条件过滤。按[qujiantao.md:1543–1551](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/qujiantao.md#L1543-L1551)用本次有效 `selector_keys` 选定，全级读同一键表。默认 end 降序、start 降序、idx 升序；缺有效记录按合同报告，不取代码常数。再核所选后门；全候选真值只供观察，失败不重选。两个已过滤候选同起止、idx 为 1 和 9，末键升序的默认版本选 1；有效末键降序版本选 9。#1439 验 selected_id，TB-07 按各自原版本回放，不改写旧结果。 | 按该 resolution 的 I-1～I-8：[#1439](https://github.com/Newchanlun/NewChanlun/issues/1439) 承接全集、所选及观察事实，TB-04 承接后门 predicate_id，TB-07 承接 selector_version，Lean 跟进键序等价。 |
~~~

依据：[#1346 resolution](https://github.com/Newchanlun/NewChanlun/issues/1346#issuecomment-6154425014)；[#1600 resolution](https://github.com/Newchanlun/NewChanlun/issues/1600#issuecomment-6307650479)；[qujiantao.md:1543–1551](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/qujiantao.md#L1543-L1551)；[Lean 非默认键序见证](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/formal/Origin/VersionedSelectorTests.lean#L13-L18)。

**L476 改前**

~~~markdown
- 结构 G 表：初始化、同价、第二序列、选父与证书直接承接 [#1342 resolution](https://github.com/Newchanlun/NewChanlun/issues/1342#issuecomment-6149622771)、[#1343 resolution](https://github.com/Newchanlun/NewChanlun/issues/1343#issuecomment-6153028395)、[#1344 resolution](https://github.com/Newchanlun/NewChanlun/issues/1344#issuecomment-6149624668)、[#1345 resolution](https://github.com/Newchanlun/NewChanlun/issues/1345#issuecomment-6149626626)、[#1346 resolution](https://github.com/Newchanlun/NewChanlun/issues/1346#issuecomment-6154425014)、[#1347 resolution](https://github.com/Newchanlun/NewChanlun/issues/1347#issuecomment-6149628539)，成本实例见 [ADR 0044:19–41](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0044-cost-stop-policy-signed-instance-v1.md#L19-L41)。
~~~

**改后**

~~~markdown
- 结构 G 表：初始化、同价、第二序列、选父与证书直接承接 [#1342 resolution](https://github.com/Newchanlun/NewChanlun/issues/1342#issuecomment-6149622771)、[#1343 resolution](https://github.com/Newchanlun/NewChanlun/issues/1343#issuecomment-6153028395)、[#1344 resolution](https://github.com/Newchanlun/NewChanlun/issues/1344#issuecomment-6149624668)、[#1345 resolution](https://github.com/Newchanlun/NewChanlun/issues/1345#issuecomment-6149626626)、[#1346 resolution](https://github.com/Newchanlun/NewChanlun/issues/1346#issuecomment-6154425014)、[#1347 resolution](https://github.com/Newchanlun/NewChanlun/issues/1347#issuecomment-6149628539)；选择键以 R4 指向的 #1600 后裁为准，成本实例见 [ADR 0044:19–41](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0044-cost-stop-policy-signed-instance-v1.md#L19-L41)。
~~~

依据：[qujiantao.md:1543–1551](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/qujiantao.md#L1543-L1551)。

## B2

**L64 改前**

~~~markdown
6. **US-ST-006** 作为结构观察者，我需要完整处理「线段基本良构与正本范式」并能查看全成员笔链、奇数约束、前三闭重叠max(low)<=min(high)与成段终结证据；#246/#249已裁相切，以便核对实际状态、依据及其变化。（C03, C02, C08, C12）
~~~

**改后**

~~~markdown
6. **US-ST-006** 作为结构观察者，我需要完整处理「线段基本良构与正本范式」并能查看全成员笔链、奇数约束、按有效 `tangency` 判前三笔重合（默认 closed），并展示成段终结证据，以便核对实际状态、依据及其变化。（C03, C02, C08, C12）
~~~

依据：[xianduan.md:257–268](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/xianduan.md#L257-L268)。

**L68 改前**

~~~markdown
8. **US-ST-008** 作为结构观察者，我需要完整处理「缺口封闭、笔破坏与段破坏的独立事实」并能查看缺口严格分离与闭重叠相补，笔破坏与段终结分别输出。第二序列分型与原方向严格越界先到者定；开放前缀或资源截断不作否定，以便核对实际状态、依据及其变化。（C03, C02, C08, C12）
~~~

**改后**

~~~markdown
8. **US-ST-008** 作为结构观察者，我需要完整处理「缺口封闭、笔破坏与段破坏的独立事实」并能查看同一有效 `tangency` 下缺口与重合互补，笔破坏与段终结分别输出。第二序列分型与原方向严格越界先到者定；开放前缀或资源截断不作否定，以便核对实际状态、依据及其变化。（C03, C02, C08, C12）
~~~

依据：[xianduan.md:257–268](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/xianduan.md#L257-L268)。

**L140 改前**

~~~markdown
44. **US-ST-048** 作为结构观察者，我需要完整处理「线段扫描上限、相切与结果完整性」并能查看扫描水位/资源截断与缓存形状分离；#246闭重叠相切已裁，51项见证不能被50项截断报全否，以便核对实际状态、依据及其变化。（C03, C02, C08, C12）
~~~

**改后**

~~~markdown
44. **US-ST-048** 作为结构观察者，我需要完整处理「线段扫描上限、相切与结果完整性」并能查看扫描水位/资源截断与缓存形状分离；相切按有效 `tangency` 处理（closed 为 #246 默认口径），51项见证不能被50项截断报全否，以便核对实际状态、依据及其变化。（C03, C02, C08, C12）
~~~

依据：[xianduan.md:257–268](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/xianduan.md#L257-L268)。

**L271 改前**

~~~markdown
5. 已裁边界直接同步和验证：三笔 seed 相切属于闭重叠，正式中枢保持非退化条件；力度在良构非空样本上使用已定首末式；三类回试遵守 Origin 严格端点。不得重开宽档兼容失败或把这些已定事项重新推给用户。
~~~

**改后**

~~~markdown
5. 已裁边界直接同步和验证：三笔 seed 重合与特征序列缺口全级共读同一有效 `tangency`（[xianduan.md:257–268](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/xianduan.md#L257-L268)），版本内缺口与重合互补，不因判定失败换值。默认 `closed`；合法 `open` 版本相切不重合。验收同一输入：[5,10] 与 [10,20] 在 closed 下无缺口，在 open 下有缺口；三笔公共区间只有端点时，closed 算重合、open 不算。正式中枢保持严格非退化条件；力度在良构非空样本上使用已定首末式；三类回试遵守 Origin 严格端点。不得重开宽档兼容失败或把这些已定事项重新推给用户。
~~~

依据：[#1600 resolution](https://github.com/Newchanlun/NewChanlun/issues/1600#issuecomment-6307650479)；[xianduan.md:257–268](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/xianduan.md#L257-L268)；[Lean 相切见证](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/formal/Origin/VersionedTangencyTests.lean#L54-L74)。

## B3

**L196 改前**

~~~markdown
72. **US-FG-028** 作为多重经营使用者，我需要完整处理「回测成交假设与真实外部成交不能混证」并能查看严格穿越/开盘取优/GTC/双滑点纪律；同批域内订单按已知前沿撮合，批内先后为 Unknown；域外模型请求具名拒绝，以便核对实际状态、依据及其变化。（C07, C08, C12）
~~~

**改后**

~~~markdown
72. **US-FG-028** 作为多重经营使用者，我需要完整处理「回测成交假设与真实外部成交不能混证」并能查看有效历史模型、容量来源和适用价规。选中已准入的默认 bar 批模型时，同批域内按已知前沿撮合，保留开盘取优、GTC、双滑点纪律，批内先后为 Unknown；所选模型缺标定与订单超出模型域分别报告，以便核对实际状态、依据及其变化。（C07, C08, C12）
~~~

依据：[ADR 0033:10–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L48)；[ADR 0052:258–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L258-L291)；[ADR 0018:69–87](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0018-limit-order-fill-model.md#L69-L87)。

**L346 改前**

~~~markdown
3. 历史按[ADR 0033:10–44](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L44)的 `history-sim/bar-batch-known-frontier/1`（确定性，`seed: none`）与[ADR 0052:258–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L258-L291)的 `history-input-profile/1`；继承严格穿越、开盘取优、GTC 与费用纪律。第 t 根 bar 只消费 t−1 收盘时已知且获准的集合；同批各重限价独立对 OHLC 判定，`intra_batch_order: Unknown`。市价仅在具名 `exec_index` 收盘槽成交，限价逻辑先于该槽；t 收盘才知道的新挂/撤/改从 t+1 起生效。部分成交依具证容量合同（含[ADR 0033:77–116](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L77-L116)的容量 epoch），容量合同为 `none` 时，已准入规模内严格穿越即全量成交，单列 L0 假设，不作容量证据；历史默认 `per_leg`，与场所对拍采用该场所冻结的同一 `projection_kind`。域外订单/并发/分配请求在 E-Release 前由 `model_coverage` 持久记为 `Unsupported{reason: ModelOrderUnspecified, model_ref, domain_id, command_id}`，不释放、不执行、不生模拟外效、不回落旧臂。TestOnly 排序只验协议。
~~~

**改后**

~~~markdown
3. 历史先从有效 `history-input-profile/1` 读取本次冻结的 `model_id/revision`、`seed`、`capacity_source`、`projection_kind`、`fee_profile` 和适用域（[ADR 0033:10–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L48)；[ADR 0052:258–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L258-L291)）。所选 `stochastic-microevent/<rev>` 缺逐笔/盘口标定，或选 `bar_volume_derived` 而缺公式标定时，容量记 Unknown，依赖动作报 AwaitingPolicy，不撮合、不退回默认模型。订单超出已选模型适用域时，则在 E-Release 前由 `model_coverage` 持久记为 `Unsupported{reason: ModelOrderUnspecified, model_ref, domain_id, command_id}`，不释放、不执行、不生模拟外效、不回落旧臂。

   默认 `history-sim/bar-batch-known-frontier/1` 为确定性模型，`seed: none`，容量来源默认 `scenario_contract`。选中获准 v1 时，第 t 根 bar 只消费 t−1 收盘时已知且获准的集合；同批各重限价独立对 OHLC 判定、开盘取优，`intra_batch_order: Unknown`。限价按有效 `fill_rule`（默认至少 1 tick 的严格穿越，更大缓冲须有标定，touch 仅诊断）与既裁 GTC、费用和双滑点纪律。市价仅在具名 `exec_index` 收盘槽成交，限价逻辑先于该槽；t 收盘才知道的新挂/撤/改从 t+1 起生效。部分成交依具证容量合同（含[ADR 0033:77–116](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L77-L116)的容量 epoch）；容量合同取 `none` 时，已准入规模内满足穿越条件才全量成交，单列为 L0 假设，不作容量证据。历史投影默认 `per_leg`，与场所对拍使用该场所冻结的同一 `projection_kind`。TestOnly 排序只验协议。
~~~

依据：[ADR 0033:10–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L48)；[ADR 0033:77–116](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L77-L116)；[ADR 0052:258–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L258-L291)；[#1598 resolution](https://github.com/Newchanlun/NewChanlun/issues/1598#issuecomment-6407142443)；[ADR 0018:69–87](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0018-limit-order-fill-model.md#L69-L87)；[ADR 0018:120–154](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0018-limit-order-fill-model.md#L120-L154)。

**L374 改前**

~~~markdown
| TB-07 | 按 C10 的具名模型跑域内同批成交与域外拒绝，再验完整历史双跑、断点恢复、seek/断线续接及 AsKnown/重算分证 | TB-02/05/06；[ADR 0033:10–44](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L44)、[ADR 0052:258–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L258-L291) |
~~~

**改后**

~~~markdown
| TB-07 | 按 C10 冻结模型、种子与容量来源；分别验默认模型的域内同批成交、域外拒绝及所选模型/容量缺标定的处置，再验完整历史双跑、断点恢复、seek/断线续接及 AsKnown/重算分证 | TB-02/05/06；[ADR 0033:10–44](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L44)、[ADR 0052:258–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L258-L291) |
~~~

依据：[ADR 0033:10–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L48)；[ADR 0052:258–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L258-L291)。

**L426 改前**

~~~markdown
| AT-14 | 域内正例（`per_leg`）：两个重的 GTC 买限价 100 与 101（测试 tick），在 t−1 收盘已获准且各自资金独立，规模在已准入的全量撮合域内；t 的 O/H/L/C 为 102/103/99/102，两单各自严格穿越并撮合，归原重、批内先后 Unknown。域外反例：请求同 bar 按未观测逐笔先后决定互斥腿成交，profile 不支持该并发形态；E-Release 前出 ModelOrderUnspecified，该请求零旧臂调用、零成交/费用原件。相同完整输入、版本、时钟和调度双跑核全状态等价；AsKnown 不回填、重算另列；seek 不偷用未来数据。 | C10；Destination 4 |
~~~

**改后**

~~~markdown
| AT-14 | 域内正例（确定性 bar 批 v1，`seed: none`，`scenario_contract/none`，`per_leg`，`fill_rule` 为默认穿越）：两个重的 GTC 买限价 100 与 101（测试 tick），在 t−1 收盘已获准且各自资金独立，规模在已准入的全量撮合域内；t 的 O/H/L/C 为 102/103/99/102，两单各自严格穿越并撮合，归原重、批内先后 Unknown。域外反例：请求同 bar 按未观测逐笔先后决定互斥腿成交，profile 不支持该并发形态；E-Release 前出 ModelOrderUnspecified，该请求零旧臂调用、零成交/费用原件。缺标定反例：保持正例两单与 OHLC 不变，事前分别选缺逐笔/盘口标定的 `stochastic-microevent/<rev>`、缺容量公式标定的 `bar_volume_derived`。两者容量均为 Unknown，依赖动作 AwaitingPolicy，该请求不产生 fill，不退回确定性 v1 或全量假设；不记为 ModelOrderUnspecified。相同完整输入、版本、时钟和调度双跑核全状态等价；AsKnown 不回填、重算另列；seek 不偷用未来数据。 | C10；Destination 4 |
~~~

依据：[ADR 0033:10–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L48)；[ADR 0018:69–87](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0018-limit-order-fill-model.md#L69-L87)；[ADR 0052:273–281](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L273-L281)。

**L479 改前**

~~~markdown
- 历史与场所：依 [ADR 0033:10–44](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L44)、[ADR 0052:273–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L273-L291) 区分域内撮合及域外拒绝；依 [ADR 0028:66–73](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L66-L73)、[ADR 0062:155–197](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0062-fu18-venue-account-permission-binding.md#L155-L197) 分开 P1 验收与 P2 首发。
~~~

**改后**

~~~markdown
- 历史与场所：依 [ADR 0033:10–44](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L44)、[ADR 0052:273–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L273-L291) 分别处理已选模型的域内撮合、域外拒绝和所选模型/容量来源缺标定（详见 R4）；依 [ADR 0028:66–73](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L66-L73)、[ADR 0062:155–197](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0062-fu18-venue-account-permission-binding.md#L155-L197) 分开 P1 验收与 P2 首发。
~~~

依据：[ADR 0033:10–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L48)；[ADR 0052:258–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L258-L291)。

## 普查

**L254 改前**

~~~markdown
3. 每次发布绑定规则、目录、程序、schema、数值配置、输入来源和政策版本。任何未支持的适用域都列出精确对象、字段、条件与原因；不默默降级到另一引擎或判据。范围内未实现、未证或未决的必需项未清，整体验收不得通过。
~~~

**改后**

~~~markdown
3. 每次发布绑定规则、目录、程序、schema、数值配置、输入来源和政策版本。已裁可调字段按具名版本在事前选定，一次运行只读一个有效取值；缺项按本字段原合同报告，不把文档默认值当成运行兜底。原文语义、已裁推论和形式化非退化条件不作可调字段。任何未支持的适用域都列出精确对象、字段、条件与原因；不默默降级到另一引擎或判据。范围内未实现、未证或未决的必需项未清，整体验收不得通过。
~~~

依据：[ADR 0041:9–23](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md#L9-L23)。

**L259 改前**

~~~markdown
1. 标准输入包含 source namespace/epoch、instrument、原始事件身份和修订、原始坐标、received_at、逻辑输入顺序、替代关系及来源证据。结构源遵守已裁美股 tick 边界；时间聚合、重采样或执行市场价格不得偷偷改变结构级别语义。
~~~

**改后**

~~~markdown
1. 标准输入包含 source namespace/epoch、instrument、原始事件身份和修订、原始坐标、received_at、逻辑输入顺序、替代关系及来源证据。结构源遵守已裁美股 tick 边界。历史读有效 `input_source`（默认 `massive-stock-tick/1`；已获准的 Databento 校验源按原射程标注），前置缺失报 `Unsupported{reason: InputSourceUnavailable}`，不运行中切源；时间聚合、重采样或执行市场价格不得偷偷改变结构级别语义。
~~~

依据：[ADR 0052:304–317](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L304-L317)。

**L260 改前**

~~~markdown
2. 一条纵向主塔只产生一份 Classification。每一级使用相同判定，级别差异只通过真实输入表达。唯一生产 owner 实际执行完整构造；各重、查询层、Python 外壳和前端不得重判。
~~~

**改后**

~~~markdown
2. 一条纵向主塔只产生一份 Classification。每一级使用相同判定，级别差异只通过真实输入表达。塔底按有效 `tower_base` 构造（默认 `segment`，值域见[zhongshu.md:160–174](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/zhongshu.md#L160-L174)），资源达到有效预算是覆盖截断，不是自然终止。唯一生产 owner 实际执行完整构造；各重、查询层、Python 外壳和前端不得重判。
~~~

依据：[zhongshu.md:160–174](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/zhongshu.md#L160-L174)；[qujiantao.md:1573–1580](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/qujiantao.md#L1573-L1580)；[塔高预算记录](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/rust/src/theta_v0/policy_records/tower-level-budget.json#L3-L16)。

**L280 改前**

~~~markdown
5. 初始化、同价、固定 Sel 与成本停止按 C12 的具名规则、当前有效版本和对应证据验收。G-029 按[ADR 0035:10–41](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md#L10-L41)用 ROUNDTRIP 配对；阶段二第一层保留 L0 余量，延伸后立即同源复测，不退回旧「延伸前算出最低级上限」。缺适用版本、真实成本或两层证据时，分别按原规则报告；不得用假定成本或 #907 探针替代，也不得据此自动开启阶段二。
~~~

**改后**

~~~markdown
5. 初始化、同价、固定 Sel 与成本停止按 C12 的具名规则、当前有效版本和对应证据验收。第二层按有效 `second_layer.rule` 及其前件，默认 `order_relation`；选 `share_threshold` 而该阈值或证据未生效时不评为通过，不改跑默认门。G-029 按[ADR 0035:10–41](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md#L10-L41)用 ROUNDTRIP 配对；阶段二第一层保留 L0 余量，延伸后立即同源复测，不退回旧「延伸前算出最低级上限」。缺适用版本、真实成本或两层证据时，分别按原规则报告；不得用假定成本或 #907 探针替代，也不得据此自动开启阶段二。
~~~

依据：[ADR 0035:24–41](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md#L24-L41)。

**L333 改前**

~~~markdown
4. S 的长期历史使用内容寻址的不可变批次对象和版本索引；先持久写完整对象，再由同一 S 事务发布可达引用，崩溃留下的不可达对象可以回收。发布读数从短事务取得固定 cut 的不可变引用，分页不持有写事务或跨请求读事务。持久 delta 按独立保留策略存储，落后消费者收到 Gap 并从指定 cut 重建。
~~~

**改后**

~~~markdown
4. S 的长期历史使用内容寻址的不可变批次对象和版本索引；先持久写完整对象，再由同一 S 事务发布可达引用，崩溃留下的不可达对象可以回收。发布读数从短事务取得固定 cut 的不可变引用，分页不持有写事务或跨请求读事务。持久 delta 按有效 `delta_retention` 策略（默认 `retain_all`）存储，落后消费者收到 Gap 并从指定 cut 重建。
~~~

依据：[ADR 0051:282–298](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0051-per-bar-domain-event-identity-lifecycle-contract.md#L282-L298)。

**L386 改前**

~~~markdown
下表的已裁规则与 C03–C06、C10、AT-06/14/15/17 的对应条款优先于 2026-09-09 归档附件在这些事项上的旧描述。覆盖附件的 FG-018 开重起点、FG-025 样本以及对应 G/FU 的旧「待裁」条目按此处读取；覆盖 ID、其余验收义务与历史字节不改。[签署时残留核查](https://github.com/xy7365527-lang/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/inputs/RESIDUAL-DECISIONS.md)仅供追溯。当期验收凭实施、证明和适用域的有效证据，不凭决策票已关。
~~~

**改后**

~~~markdown
下表的已裁规则与 C03–C06、C10、AT-06/14/15/17 的对应条款优先于 2026-09-09 归档附件在这些事项上的旧描述。覆盖附件的 FG-018 开重起点、FG-025 样本、ST-006/008/048 的相切、G-026 的键序、FG-028 的模拟模型与对应 G/FU 的旧「待裁」条目按此处读取；覆盖 ID、其余验收义务与历史字节不改。[签署时残留核查](https://github.com/xy7365527-lang/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/inputs/RESIDUAL-DECISIONS.md)仅供追溯。当期验收凭实施、证明和适用域的有效证据，不凭决策票已关。
~~~

依据：[ADR 0041:9–23](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md#L9-L23)；[xianduan.md:257–268](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/xianduan.md#L257-L268)；[qujiantao.md:1543–1551](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/qujiantao.md#L1543-L1551)；[ADR 0033:10–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L48)。

**L391 改前**

~~~markdown
| G-007 | [#1344 resolution](https://github.com/Newchanlun/NewChanlun/issues/1344#issuecomment-6149624668)：先成分型则确认，原方向先严格越过候选极值则失效且不复活；已知前缀内均未发生则开放。同笔先处理包含并检查分型，再查越界；同段不越过开放候选。扫描覆盖与语义态分开，资源耗尽不是否定。 | [#1420](https://github.com/Newchanlun/NewChanlun/issues/1420) 承接每候选折叠游标、checkpoint、失效及超 50 项的判定/恢复对拍，按实际版本取证；族 I 的 50 窗归 TB-10 旧入口处置，不参与准入。 |
~~~

**改后**

~~~markdown
| G-007 | [#1344 resolution](https://github.com/Newchanlun/NewChanlun/issues/1344#issuecomment-6149624668)：先成分型则确认，原方向先严格越过候选极值则失效且不复活；已知前缀内均未发生则开放。同笔先处理包含并检查分型，再查越界；同段不越过开放候选。扫描按有效 `second-seq-scan-budget` 承载，扫描覆盖与语义态分开，资源耗尽不是否定。 | [#1420](https://github.com/Newchanlun/NewChanlun/issues/1420) 承接每候选折叠游标、checkpoint、失效及超 50 项的判定/恢复对拍，按实际版本取证；族 I 的 50 窗归 TB-10 旧入口处置，不参与准入。 |
~~~

依据：[xianduan.md:209–215](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/xianduan.md#L209-L215)；[second-seq-scan-budget.json:5–24](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/rust/src/theta_v0/policy_records/second-seq-scan-budget.json#L5-L24)。

**L401 改前**

~~~markdown
| FU-07 | [ADR 0030:13–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0030-exit-authorization-and-liability-retirement.md#L13-L48)定结构/具名风险/手动退出及动作范围。场所订单终态、原 Voice 仓位为零、真实费用结清且 E 无 Pending，才可退休责任；迟到事实按原 Voice 重开。P1 风险清单按[ADR 0045:27–55](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0045-sr-v1-policy-signed.md#L27-L55)，拒发期间同一退出授权待续（[ADR 0030:70–76](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0030-exit-authorization-and-liability-retirement.md#L70-L76)）。 | [#1380](https://github.com/Newchanlun/NewChanlun/issues/1380)、[#1397](https://github.com/Newchanlun/NewChanlun/issues/1397) 承接；仍验具体外部终态/费用/持仓证据与适用风险、退出授权。新真实权限或超出原授权范围须按原门签署。 |
~~~

**改后**

~~~markdown
| FU-07 | [ADR 0030:13–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0030-exit-authorization-and-liability-retirement.md#L13-L48)定结构/具名风险/手动退出及动作范围。场所订单终态、原 Voice 仓位为零、真实费用结清且 E 无 Pending，才可退休责任；有效 `observation_period` 如有正值，只在四条件成立后延迟释放，默认关闭。迟到事实按原 Voice 重开。P1 风险清单按[ADR 0045:27–55](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0045-sr-v1-policy-signed.md#L27-L55)，拒发期间同一退出授权待续（[ADR 0030:70–76](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0030-exit-authorization-and-liability-retirement.md#L70-L76)）。 | [#1380](https://github.com/Newchanlun/NewChanlun/issues/1380)、[#1397](https://github.com/Newchanlun/NewChanlun/issues/1397) 承接；仍验具体外部终态/费用/持仓证据与适用风险、退出授权。新真实权限或超出原授权范围须按原门签署。 |
~~~

依据：[ADR 0030:38–44](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0030-exit-authorization-and-liability-retirement.md#L38-L44)。

## 下游 handoff

- [#1444](https://github.com/Newchanlun/NewChanlun/issues/1444)「要交付的外部行为」仍写「从最低可行操作级别向上找」。主控在承接时按 C05.6/AT-06 与 [ADR 0040:327–329](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0040-funding-signature-and-chong-derivation.md#L327-L329) 同步成「从有效资金推导记录的 `l_start` 向上」；本次未改票，也不增阻塞边。
- 本轮不加机读计划。已核 `parseSplitPlan(body-r4)` 为 `null`；绑定实际发布正文的独审 PASS 后，符合各自门槛且无机拆身份的既有 SPEC 子树实施票可获祖先授权。无计划不新拆票，不放行仅从 map 继承的计划外票，也不放行缺计划身份及当前正文发布凭据的机拆票。代码依据：[wayfinder_engine.mts:922–961](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/scripts/wayfinder_engine.mts#L922-L961)。
