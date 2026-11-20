# SPEC #1340 R3 修订对照

改前行号以 `body-886112d11873.md` 为准。所依据的 2026-11-20 独审原件为 `review-20261120.json`，其绑定的受审正文摘要为 `886112d118739fc10964759ec9fce220bcc7295d534e51125ee2c6f818f4bf50`。依据链接固定到读取的 `origin/main` 或决策票 resolution。以下是文书修订与实施判据，未执行这些业务验收。

## B1 FG-018：从签署记录的起始级别推导

**L176 改前**

~~~markdown
62. **US-FG-018** 作为多重经营使用者，我需要完整处理「规模取容量、开局从最低可行级别向上」并能查看最低可行层承载及容量测量/窗口/域，容量未知非无限，以便核对实际状态、依据及其变化。（C05, C06, C08, C12）
~~~

**改后**

~~~markdown
62. **US-FG-018** 作为多重经营使用者，我需要完整处理「规模取容量、开局从有效记录的 `l_start` 向上」并能查看起点记录版本和逐级容量、买卖频率及证据窗。各级分别核容量与买卖频率；容量未知不作无限，不在 `l_start` 以下开重，以便核对实际状态、依据及其变化。（C05, C06, C08, C12）
~~~

依据：[ADR 0040:38–59](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0040-funding-signature-and-chong-derivation.md#L38-L59)；[ADR 0041:9–23](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md#L9-L23)。

**L289 改前**

~~~markdown
6. 容量决定规模，频率决定是否开重；原始买卖计数、样本、窗口和稀疏原因保留。行情换档与资金溢出换档两个事件族分别保留触发证据、原重持续经营和新重承接。
~~~

**改后**

~~~markdown
6. 按[ADR 0040:38–59](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0040-funding-signature-and-chong-derivation.md#L38-L59)，从当前有效 `l_start` 向上用剩余总投入逐级推导。买、卖频率任一低于有效阈值则该级不开重、继续向上；频率阈值未签、读数缺失或容量 Unknown 时停在该级报 AwaitingPolicy，不跳级。可放置时规模取剩余投入与该级容量的较小值；剩余为零则停止。保留买卖计数、样本、窗口和稀疏原因。行情换档与资金溢出换档两个事件族分别保留触发证据、原重持续经营和新重承接。
~~~

依据：[ADR 0040:38–59](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0040-funding-signature-and-chong-derivation.md#L38-L59)；[ADR 0041:9–23](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md#L9-L23)；两类换档保留原义，见 [ADR 0034:13–42](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0034-quantity-tier-policy-growth-equity-shift.md#L13-L42)。

**L418 改前**

~~~markdown
| AT-06 | 成本/本金/增长/空头非对称、容量/频率、两类换档的成功与失败路径均依已批政策成立 | C05；FE-03/04/06 |
~~~

**改后**

~~~markdown
| AT-06 | 成本/本金/增长/空头非对称、容量/频率、两类换档的成功与失败路径均依已批政策成立。反例夹具：L0、L1 均通过容量和买卖频率门，且 L1 容量足以承载测试投入；有效记录 `l_start=L1` 时首重在 L1，不在 L0 建重。 | C05；FG-018/FE-03/04/06 |
~~~

依据：[ADR 0040:38–59](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0040-funding-signature-and-chong-derivation.md#L38-L59)；[ADR 0041:9–23](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md#L9-L23)；夹具不改签现行值。

## B2 结构残留：按已裁定义验成功与证据缺口

**L68 改前**

~~~markdown
8. **US-ST-008** 作为结构观察者，我需要完整处理「缺口封闭、笔破坏与段破坏的独立事实」并能查看缺口严格分离/闭重叠已裁互补；笔破坏/段终结分别输出；第二序列扫描范围仍独立待裁，以便核对实际状态、依据及其变化。（C03, C02, C08, C12）
~~~

**改后**

~~~markdown
8. **US-ST-008** 作为结构观察者，我需要完整处理「缺口封闭、笔破坏与段破坏的独立事实」并能查看缺口严格分离与闭重叠相补，笔破坏与段终结分别输出。第二序列分型与原方向严格越界先到者定；开放前缀或资源截断不作否定，以便核对实际状态、依据及其变化。（C03, C02, C08, C12）
~~~

依据：[#1344 resolution](https://github.com/Newchanlun/NewChanlun/issues/1344#issuecomment-6149624668)；[xianduan.md:202–215](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/xianduan.md#L202-L215)。

**L98 改前**

~~~markdown
23. **US-ST-023** 作为结构观察者，我需要完整处理「背驰先结构配对后力度及范围边界」并能查看完整结构Cand集合与正式比较对分别存，保留跨文对象范围待对齐，以便核对实际状态、依据及其变化。（C03, C08, C12）
~~~

**改后**

~~~markdown
23. **US-ST-023** 作为结构观察者，我需要完整处理「背驰先结构配对后力度及范围边界」并能查看完整结构候选集与正式比较对分别存，Comparable 与固定 Sel 按 G-026 的已裁对象域承接，以便核对实际状态、依据及其变化。（C03, C08, C12）
~~~

依据：[#1346 resolution](https://github.com/Newchanlun/NewChanlun/issues/1346#issuecomment-6154425014)。

**L120 改前**

~~~markdown
34. **US-ST-034** 作为结构观察者，我需要完整处理「区间套统一坐标、闭包含与真正父子来源」并能查看raw与merged同源名字空间、闭包含和真实父边分开，价格挂法未裁，以便核对实际状态、依据及其变化。（C04, C08, C12）
~~~

**改后**

~~~markdown
34. **US-ST-034** 作为结构观察者，我需要完整处理「区间套统一坐标、闭包含与真正父子来源」并能查看 raw 与 merged 同源坐标、闭包含和真实父边分开。独立选父的价格证书取共享 raw 闭窗外缘，缺前提报缺证，不充构造血缘，以便核对实际状态、依据及其变化。（C04, C08, C12）
~~~

依据：[#1345 resolution](https://github.com/Newchanlun/NewChanlun/issues/1345#issuecomment-6149626626)；[qujiantao.md:345–355](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/qujiantao.md#L345-L355)。

**L272 改前**

~~~markdown
6. G 目录逐项承接。G-003/G-021 是描述性观察边界，不新增穷尽强弱档；G-025/G-028 及当前核查仍未取得后裁的 G-007 进入残留决定表。其余投影、构造、证明和同步义务是实际交付工作，不能统一标成 Fog 后跳过。
~~~

**改后**

~~~markdown
6. G 目录逐项承接。G-003/G-021 是描述性观察边界，不新增穷尽强弱档。G-001/002/007/025/026/028/029 按 C12 的现行裁定与适用域读取；投影、构造、证明和同步按对应实施票验收，不能统一标成 Fog 后跳过。
~~~

依据：[#1342 resolution](https://github.com/Newchanlun/NewChanlun/issues/1342#issuecomment-6149622771)；[#1343 resolution](https://github.com/Newchanlun/NewChanlun/issues/1343#issuecomment-6153028395)；[#1344 resolution](https://github.com/Newchanlun/NewChanlun/issues/1344#issuecomment-6149624668)；[#1345 resolution](https://github.com/Newchanlun/NewChanlun/issues/1345#issuecomment-6149626626)；[#1346 resolution](https://github.com/Newchanlun/NewChanlun/issues/1346#issuecomment-6154425014)；[#1347 resolution](https://github.com/Newchanlun/NewChanlun/issues/1347#issuecomment-6149628539)；[ADR 0035:10–41](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md#L10-L41)。

**L279 改前**

~~~markdown
4. 成本停止与无更低结构两个触发可同时真；停止不是结构否定，下钻失败不是小转大。Type2/3 的不适用不得填 true，也不得默认填 false 否掉所有二三类；证书处置先通过相应语义门。
~~~

**改后**

~~~markdown
4. 成本停止与无更低结构两个触发可同时真；停止不是结构否定，下钻失败不是小转大。Type1 的 `N^δ` 不变。Type2/3 入口的 `N^δ` 返回带原因的 N/A，不填 true 或 false；另用具名条件证书判「基例确认 ∧ 自身下级完成义务」。几何链和逐 rung N/A 只随证书供观察，不参与合取。
~~~

依据：[#1347 resolution](https://github.com/Newchanlun/NewChanlun/issues/1347#issuecomment-6149628539)；[qujiantao.md:1162–1170](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/qujiantao.md#L1162-L1170)。

**L280 改前**

~~~markdown
5. G-001 初始化方向、G-002 同价身份、G-026 Sel 实例、G-029 成本停止参数须有具名、版本化的明确规则和对照证据。未确定时保留原始材料并阻止依赖该实例的正式判定/交易，不伪造一个“安全默认”。G-029 承接 #907 后裁：阶段二第一层是 L0 处余量加延伸后立即复测，不能退回旧“延伸前算出最低级上限”；已裁 ROUNDTRIP 配对仍受原探针有效域限制，不等于全场所成本政策或阶段二自动放行。这些项的具体状态以残留决定表为准。
~~~

**改后**

~~~markdown
5. 初始化、同价、固定 Sel 与成本停止按 C12 的具名规则、当前有效版本和对应证据验收。G-029 按[ADR 0035:10–41](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md#L10-L41)用 ROUNDTRIP 配对；阶段二第一层保留 L0 余量，延伸后立即同源复测，不退回旧「延伸前算出最低级上限」。缺适用版本、真实成本或两层证据时，分别按原规则报告；不得用假定成本或 #907 探针替代，也不得据此自动开启阶段二。
~~~

依据：[#907 resolution](https://github.com/Newchanlun/NewChanlun/issues/907#issuecomment-5194145006)；[#1354 resolution](https://github.com/Newchanlun/NewChanlun/issues/1354#issuecomment-6153713798)；[ADR 0035:10–41](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md#L10-L41)；[ADR 0044:19–41](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0044-cost-stop-policy-signed-instance-v1.md#L19-L41)。

**L390 改前**

~~~markdown
| G-001/002 | 包含方向、极值及组锚已有定义；初始化和同价端点身份实例仍须明确提审 | 依赖该实例的结构成功路径、TB-02 |
~~~

**改后**

~~~markdown
| G-001/002 | 初始化 W（[#1342 resolution](https://github.com/Newchanlun/NewChanlun/issues/1342#issuecomment-6149622771)）：首个相邻 raw 严格非包含对出现前按 raw 留未定，不产合并组；若始终不出现则保持未定。出现时以其方向从序号 0 左折叠并发布，替代关系可查，旧 cut 不回填。同型同价端点取先，后者身份仍留；实际极值根取集合，raw 间隔取前端末根到后端首根之间（[#1343 resolution](https://github.com/Newchanlun/NewChanlun/issues/1343#issuecomment-6153028395)）。 | [#1393](https://github.com/Newchanlun/NewChanlun/issues/1393) 的 W 发布（含 `pending_since_cut`）、替代、增量和恢复对拍；[#1405](https://github.com/Newchanlun/NewChanlun/issues/1405) 承接同价行为锁，按其实际版本取证；保留对应 Lean 定义与证明义务。 |
~~~

依据：[baohan.md:120–122](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/baohan.md#L120-L122)、[baohan.md:169–187](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/baohan.md#L169-L187)；[#1342 resolution](https://github.com/Newchanlun/NewChanlun/issues/1342#issuecomment-6149622771)；[#1343 resolution](https://github.com/Newchanlun/NewChanlun/issues/1343#issuecomment-6153028395)；[bi.md:305–307](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/bi.md#L305-L307)、[bi.md:323–334](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/bi.md#L323-L334)。

**L391 改前**

~~~markdown
| G-007 | 特征序列语义已定；50/完整扫描及 checkpoint 影响仍未取到后裁，预算耗尽不算否定 | 第二序列完整判断、TB-02 |
~~~

**改后**

~~~markdown
| G-007 | [#1344 resolution](https://github.com/Newchanlun/NewChanlun/issues/1344#issuecomment-6149624668)：先成分型则确认，原方向先严格越过候选极值则失效且不复活；已知前缀内均未发生则开放。同笔先处理包含并检查分型，再查越界；同段不越过开放候选。扫描覆盖与语义态分开，资源耗尽不是否定。 | [#1420](https://github.com/Newchanlun/NewChanlun/issues/1420) 承接每候选折叠游标、checkpoint、失效及超 50 项的判定/恢复对拍，按实际版本取证；族 I 的 50 窗归 TB-10 旧入口处置，不参与准入。 |
~~~

依据：[#1344 resolution](https://github.com/Newchanlun/NewChanlun/issues/1344#issuecomment-6149624668)；[xianduan.md:202–215](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/xianduan.md#L202-L215)。

**L392 改前**

~~~markdown
| G-025 | 真实后代极值链的包含不外推到独立选父；NestInterval 价格挂法需裁 | 相应选父价格证书、TB-02/04 |
~~~

**改后**

~~~markdown
| G-025 | [#1345 resolution](https://github.com/Newchanlun/NewChanlun/issues/1345#issuecomment-6149626626)：独立选父取同源、同有效版本及尺度、完整非空的 raw 闭窗 `[min low, max high]`；price-subset 是索引包含的派生证据，不是第二准入门，不证明血缘。缺前提报缺证，不改选。 | [#1438](https://github.com/Newchanlun/NewChanlun/issues/1438)：实际选中父和双坐标证书、缺证及真实对象对照；TB-04 消费实际证据。 |
~~~

依据：[#1345 resolution](https://github.com/Newchanlun/NewChanlun/issues/1345#issuecomment-6149626626)；[qujiantao.md:345–355](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/qujiantao.md#L345-L355)。

**L393 改前**

~~~markdown
| G-026 | Cand 集和固定 Sel 边界已定；对象投影、全集及具体选择实例需明确 | 主动定位成功路径、TB-02/04 |
~~~

**改后**

~~~markdown
| G-026 | [#1346 resolution](https://github.com/Newchanlun/NewChanlun/issues/1346#issuecomment-6154425014)：已裁 Comparable 与 Sel 可直接复用。闭合候选先按 Dir/Comparable/Extreme 及子区间条件过滤。按 end 最新、start 最新、idx 最小选定，再核所选后门；全候选真值只供观察。 | 按该 resolution 的 I-1～I-8：[#1439](https://github.com/Newchanlun/NewChanlun/issues/1439) 承接全集、所选及观察事实，TB-04 承接后门 predicate_id，TB-07 承接 selector_version，Lean 跟进键序等价。 |
~~~

依据：[#1346 resolution](https://github.com/Newchanlun/NewChanlun/issues/1346#issuecomment-6154425014)。

**L394 改前**

~~~markdown
| G-028 | Type1 有效域、Type2/3 N/A 三值承载已裁；递归证书合成处置未裁 | Type2/3 该路径准入、TB-02/04 |
~~~

**改后**

~~~markdown
| G-028 | [#1347 resolution](https://github.com/Newchanlun/NewChanlun/issues/1347#issuecomment-6149628539)：按 C04 分 Type1 与 Type2/3；Type2/3 条件证书另名，几何链长 `L_geo` 与判据深度 `D_crit` 分报，Type2/3 的 `D_crit=0`。链 B 的 provider Cand 真值不是 N/A 填真。 | [#1442](https://github.com/Newchanlun/NewChanlun/issues/1442)：入口点型随查链，条件证书正反例、链 A/B 的 Type1 同输入同输出锁及旧填真臂退场；TB-04 按实际证书准入。 |
~~~

依据：[#1347 resolution](https://github.com/Newchanlun/NewChanlun/issues/1347#issuecomment-6149628539)；[qujiantao.md:1162–1170](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/definitions/qujiantao.md#L1162-L1170)。

**L395 改前**

~~~markdown
| G-029 | 按 #907 后裁同步 L0 余量与延伸后复测；当前成本参数和两层实证仍需落实，阶段二不因本稿自动开启 | 依赖成本门的操作及原有条件下的基底进阶 |
~~~

**改后**

~~~markdown
| G-029 | [ADR 0035:10–41](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md#L10-L41)规定 ROUNDTRIP、L0 余量及延伸后复测、第二层逐层逐窗证据；[ADR 0044:19–41](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0044-cost-stop-policy-signed-instance-v1.md#L19-L41)登记 P0/P1 已签实例，不跨域借用。 | [#1441](https://github.com/Newchanlun/NewChanlun/issues/1441)、TB-07/08 核有效版本与输入。Missing 不代 0，代理下界不判通过；#907 材料不是第一层通过证据。两层实证未齐不开阶段二，不据此挡既有 L0。 |
~~~

依据：[#1354 resolution](https://github.com/Newchanlun/NewChanlun/issues/1354#issuecomment-6153713798)；[ADR 0035:10–41](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md#L10-L41)；[ADR 0044:19–41](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0044-cost-stop-policy-signed-instance-v1.md#L19-L41)。

## B3 AT-17：每重每稳定点一个样本

**L190 改前**

~~~markdown
69. **US-FG-025** 作为多重经营使用者，我需要完整处理「经营验收用成本事件并保留统计边界」并能查看全正负费事件、样本/窗/排除原因和已裁统计法，未决采样不报通过，以便核对实际状态、依据及其变化。（C05, C06, C08, C12）
~~~

**改后**

~~~markdown
69. **US-FG-025** 作为多重经营使用者，我需要完整处理「经营验收用费后成本及已裁计样边界」并能查看改变成本的正负经济原件、费用和排除原因；按（重，S 稳定点）合并为操作样本，逐重逐月对账，正式读数绑定有效 `evidence_gate`，以便核对实际状态、依据及其变化。（C05, C06, C08, C12）
~~~

依据：[ADR 0036:10–22](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0036-operating-statistics-sampling-and-post-gate-parameter-protocol.md#L10-L22)；[ADR 0022:97–167](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0022-acceptance-criterion-parameters.md#L97-L167)。

**L399 改前**

~~~markdown
| FU-05 | 费后成本速率及统计方法已裁；计样边界待定，后闸参数遵首次触达后且启用前落盘的触发条款 | 相应正式统计和阶段能力启用；不能现在编数 |
~~~

**改后**

~~~markdown
| FU-05 | [ADR 0036:10–22](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0036-operating-statistics-sampling-and-post-gate-parameter-protocol.md#L10-L22)定闸前计样、跨闸分段和费后速率输出；AT-17 读有效 `evidence_gate`。[ADR 0036:24–33](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0036-operating-statistics-sampling-and-post-gate-parameter-protocol.md#L24-L33)另定后闸：真实 experiment/production 原件已 Applied、无覆盖 Pending 且 B/E 对账一致，首次使 `growth_eligible` 为真才记同源 `GateReachedEvent`。 | [#1398](https://github.com/Newchanlun/NewChanlun/issues/1398) 验统计；[#1358](https://github.com/Newchanlun/NewChanlun/issues/1358)、[#1410](https://github.com/Newchanlun/NewChanlun/issues/1410) 另验真实首触、触达后落盘的有效参数版本与首次启用，三记录按「触达 known_at < 参数 authorized_at < 首次启用 known_at」持久互引；启用仍须真实资格成立及启用记录。真实账户启用及资金/风险参数须用户授权。历史/TestOnly 仅演练，缺参不启用、不阻闸前统计。 |
~~~

依据：[ADR 0036:10–22](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0036-operating-statistics-sampling-and-post-gate-parameter-protocol.md#L10-L22)；[ADR 0022:97–167](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0022-acceptance-criterion-parameters.md#L97-L167)；[ADR 0036:24–33](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0036-operating-statistics-sampling-and-post-gate-parameter-protocol.md#L24-L33)；[#1358 resolution](https://github.com/Newchanlun/NewChanlun/issues/1358#issuecomment-6153716650)；[ADR 0041:39–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md#L39-L48)。

**L429 改前**

~~~markdown
| AT-17 | 正负成本事件和费用完整留存；正式统计遵既裁方法及已定采样；稀疏、无证/未定不报通过 | C05/06；FG-025/FE-11 |
~~~

**改后**

~~~markdown
| AT-17 | 按[ADR 0036:10–22](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0036-operating-statistics-sampling-and-post-gate-parameter-protocol.md#L10-L22)保留正负原件，按（重，S 稳定点）合并已 Applied、改变 K 的分量；迟到费用归到达的稳定点，不回填。逐重逐月核完整事件账 = 样本分量 + 具名排除（post_gate 域外、未应用、重算、合并后零基、整重终结）；零时长保留降幅、不入速率，跨闸按 ADR 0036 分段。不汇总多重作门，买卖频率另报。反例：同一重的 29 个合格稳定点各有成交，最后一点同点应用一笔费用，30 份入样原件只成 29 个样本，按 v1 报样本不足，不出通过读数。 | C05/06；FG-025/FE-11 |
~~~

依据：[ADR 0036:10–22](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0036-operating-statistics-sampling-and-post-gate-parameter-protocol.md#L10-L22)；[ADR 0022:97–167](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0022-acceptance-criterion-parameters.md#L97-L167)；[ADR 0022:22–33](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0022-acceptance-criterion-parameters.md#L22-L33)；[#1356 resolution](https://github.com/Newchanlun/NewChanlun/issues/1356#issuecomment-6153715166)。

**L431 改前**

~~~markdown

~~~

**改后**

~~~markdown
AT-17 的正式读数按[ADR 0022:97–167](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0022-acceptance-criterion-parameters.md#L97-L167)绑定本次运行读取评价数据前已生效的 `evidence_gate` 与已冻结的逐窗起讫表；用起讫核窗不重叠，报告逐重每窗下界、样本/块数及合计覆盖，全史区间取数据集首末 bar。用费后速率的单边分块 bootstrap 下界，每窗各自过线（下界大于 0），汇总与点估计不代门。现行 `#1677/evidence-gate/v1` 为 UTC 日历月分块、单边 95% 下界（第 5 百分位）、每窗至少 30 样本和 12 月块、至少 3 窗、合计覆盖至少全史的 1/2。用有效记录取值，不写死 v1；门缺失、越界或证据不足不报通过。
~~~

依据：[ADR 0036:10–22](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0036-operating-statistics-sampling-and-post-gate-parameter-protocol.md#L10-L22)；[ADR 0022:97–167](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0022-acceptance-criterion-parameters.md#L97-L167)；[ADR 0022:22–33](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0022-acceptance-criterion-parameters.md#L22-L33)；[#1356 resolution](https://github.com/Newchanlun/NewChanlun/issues/1356#issuecomment-6153715166)。

## B4 经营政策：照已裁账务规则，按实际范围检查权限

**L152 改前**

~~~markdown
50. **US-FG-006** 作为多重经营使用者，我需要完整处理「重间不作方向仲裁」并能查看相反重均保留信号和决定，共同资源限制不改结构方向；争用政策未裁，以便核对实际状态、依据及其变化。（C06, C08, C12）
~~~

**改后**

~~~markdown
50. **US-FG-006** 作为多重经营使用者，我需要完整处理「重间不作方向仲裁」并能查看相反重各自保留信号和决定；共同资金受有效争用政策约束，不用资金结果改结构方向，以便核对实际状态、依据及其变化。（C06, C08, C12）
~~~

依据：[ADR 0029:13–37](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0029-common-cap-contention-policy.md#L13-L37)。

**L172 改前**

~~~markdown
60. **US-FG-016** 作为多重经营使用者，我需要完整处理「本金回收闸门和多空阶段非对称」并能查看本金回收与阶段实际事件链，空头无第三相且保留欠付义务，以便核对实际状态、依据及其变化。（C05, C06, C08, C12）
~~~

**改后**

~~~markdown
60. **US-FG-016** 作为多重经营使用者，我需要完整处理「本金回收闸门和多空阶段非对称」并能查看已授权本金批次、实际回收与阶段事件；换向延续重账，按在世声部取侧，空头不进入赚股第三相且保留欠付义务，以便核对实际状态、依据及其变化。（C05, C06, C08, C12）
~~~

依据：[ADR 0031:10–34](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0031-principal-batches-phase-predicate-corporate-actions.md#L10-L34)；[ADR 0043:9–35](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0043-chong-reversal-account-continuity.md#L9-L35)。

**L174 改前**

~~~markdown
61. **US-FG-017** 作为多重经营使用者，我需要完整处理「回本后增长与固定Q的衔接不能暗填」并能查看资本/权益/固定Q/增长权属分栏，需批准会计桥推动增长与换档，以便核对实际状态、依据及其变化。（C05, C06, C08, C12）
~~~

**改后**

~~~markdown
61. **US-FG-017** 作为多重经营使用者，我需要完整处理「回本后增长权益与固定 Q 分账」并能查看增长不自动并入本金或固定 Q，重基和两类换档各按有效记录与证据，以便核对实际状态、依据及其变化。（C05, C06, C08, C12）
~~~

依据：[ADR 0034:13–42](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0034-quantity-tier-policy-growth-equity-shift.md#L13-L42)；[ADR 0049:23–34](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0049-funding-quantity-and-policy-reference-dimensions.md#L23-L34)。

**L210 改前**

~~~markdown
79. **US-FG-035** 作为多重经营使用者，我需要完整处理「真正未定钱规则显式保留，已采纳组织按R2承接」并能查看完整R2职责、协议及已披露精确交付窗口已经用户采纳；本金、增长、费用、配对、并发资金及权限等真实残留按具名FU保留。当前SPEC提出的具体技术实例和新增取舍各依原批准门，不因架构采纳获得资金默认值或实施/发布权限，以便核对实际状态、依据及其变化。（C01, C06, C08, C12）
~~~

**改后**

~~~markdown
79. **US-FG-035** 作为多重经营使用者，我需要完整处理「现行经营规则与外效权限分开」并能查看 R2 职责、协议及已披露精确交付窗口继续生效；本金、增长、费用分配、争用和退休按 C05/C06 及 FU 的已裁规则实施，只在适用记录、签署或证据缺失时阻相应动作。SPEC 不代签资金、交易、账户或退出权限，也不替代原发布门，以便核对实际状态、依据及其变化。（C01, C06, C08, C12）
~~~

依据：[ADR 0031:10–34](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0031-principal-batches-phase-predicate-corporate-actions.md#L10-L34)；[ADR 0034:13–42](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0034-quantity-tier-policy-growth-equity-shift.md#L13-L42)；[ADR 0029:13–37](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0029-common-cap-contention-policy.md#L13-L37)；[ADR 0032:10–49](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0032-fill-allocation-policy.md#L10-L49)；[ADR 0030:13–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0030-exit-authorization-and-liability-retirement.md#L13-L48)；[ADR 0041:39–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md#L39-L48)。

**L288 改前**

~~~markdown
5. 降成本、回本金、允许方向的赚股阶段都在范围内。线性空头无赚股第三相且债务仍在。本金细义、跨零回退、分母零和固定 Q 到增长权利的会计桥由具名政策门约束，不能靠虚拟成本为零推断物理风险为零。
~~~

**改后**

~~~markdown
5. 降成本、回本金、允许方向的赚股阶段都在范围内。按[ADR 0031:10–34](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0031-principal-batches-phase-predicate-corporate-actions.md#L10-L34)与[ADR 0043:9–35](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0043-chong-reversal-account-continuity.md#L9-L35)，本金按授权投入分批冻结，利润资本化不入本金，换向不开新批，P/K 和阶段事件跨 Voice 延续。多头按 `P_recovered ≥ P` 判本金回收，空头按累计费后已实现利润覆盖投入保证金批次总额（换向后按 `ΣP_b` 读）。TStage 记录历史，扩量资格按当前真实账及在世声部方向重核；回零只在新 Voice 的求值点按拟开方向取侧。空头不走赚股第三相且继续记欠付义务；零分母报具名 NotComputable、留绝对差额，K 不钳零，也不据此清除物理风险。增长权益 G 不自动并入固定 Q；授权重基与两种换档依 FU-02。
~~~

依据：[ADR 0031:10–34](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0031-principal-batches-phase-predicate-corporate-actions.md#L10-L34)；[ADR 0043:9–35](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0043-chong-reversal-account-continuity.md#L9-L35)；[ADR 0034:13–42](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0034-quantity-tier-policy-growth-equity-shift.md#L13-L42)。

**L301 改前**

~~~markdown
8. 同 slot 完整请求集使用可证输入水位关闭，失效申请者代际与许可同序。全部请求可共同满足约束时一并保留；资源不足、配对、费用归属或插队缺政策时等待具名决议。S 本地核验 FIFO 不得成为资金分配政策。
~~~

**改后**

~~~markdown
8. 同 slot 完整请求集使用可证输入水位关闭，失效申请者代际与许可同序。按[ADR 0029:13–37](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0029-common-cap-contention-policy.md#L13-L37)读有效 cap 与争用版本：共同约束容得下则整 slot 保留；默认 `await_slot` 下容不下则整 slot 等待，后到不越过，按 S 稳定点结构序处理。只有有效记录选 `reject` 才按该政策拒绝；不择重、不缩量、不换档兜底，S 本地核验 FIFO 不决定资金分配。按[ADR 0032:10–49](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0032-fill-allocation-policy.md#L10-L49)读冻结 `projection_kind`：`per_leg` 的回报缺逐腿归属报 Unmatched，不转比例；`netted` 用配额法累计分配 `frozen-manifest-proportional-cumulative/2` 的差量。费用按原件因果入账，更正沿原政策及原分配；缺前件等前件，不改分配算法。
~~~

依据：[ADR 0029:13–37](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0029-common-cap-contention-policy.md#L13-L37)；[ADR 0032:10–49](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0032-fill-allocation-policy.md#L10-L49)；[ADR 0041:39–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md#L39-L48)。

**L396 改前**

~~~markdown
| FU-01/02 | 成本/费用、固定 Q、容量频率与换档主干已裁；本金细义、增长衔接、完整量档和有效参数仍缺 | 完整阶段、量、增长与换档，TB-06/07 |
~~~

**改后**

~~~markdown
| FU-01/02 | 本金、阶段、换向单账按[ADR 0031:10–34](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0031-principal-batches-phase-predicate-corporate-actions.md#L10-L34)、[ADR 0043:9–35](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0043-chong-reversal-account-continuity.md#L9-L35)；固定 Q、量档、容量、G 与两类换档按[ADR 0034:13–42](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0034-quantity-tier-policy-growth-equity-shift.md#L13-L42)和[ADR 0049:23–34](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0049-funding-quantity-and-policy-reference-dimensions.md#L23-L34)。金额与金额、数量与数量同维比较，量档随有效版本冻结，旧金额算例不作数量。 | [#1406](https://github.com/Newchanlun/NewChanlun/issues/1406)、[#1444](https://github.com/Newchanlun/NewChanlun/issues/1444)、[#1445](https://github.com/Newchanlun/NewChanlun/issues/1445)、[#1446](https://github.com/Newchanlun/NewChanlun/issues/1446) 承接。缺有效开局资金、档量、容量或所选定标的签署与证据（如 frozen_quote 的报价原件与 max_quote_age），只挡依赖动作；行情换档份额、真实重基及资金相关新版本按原授权门，不重签已生效原值。 |
~~~

依据：[ADR 0031:10–34](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0031-principal-batches-phase-predicate-corporate-actions.md#L10-L34)；[ADR 0043:9–35](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0043-chong-reversal-account-continuity.md#L9-L35)；[ADR 0034:13–42](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0034-quantity-tier-policy-growth-equity-shift.md#L13-L42)；[ADR 0049:23–34](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0049-funding-quantity-and-policy-reference-dimensions.md#L23-L34)；[ADR 0040:38–59](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0040-funding-signature-and-chong-derivation.md#L38-L59)；[ADR 0041:39–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md#L39-L48)。

**L397 改前**

~~~markdown
| FU-03 | 毛净帽及净省禁复用已裁；争用分配、部分成交/费用归属、公用资金与实际 cap 仍缺 | 相关准入及投影，TB-04/06/07 |
~~~

**改后**

~~~markdown
| FU-03 | [ADR 0029:13–37](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0029-common-cap-contention-policy.md#L13-L37)定争用、公用资金注入与取出规则；按[ADR 0049:15–17](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0049-funding-quantity-and-policy-reference-dimensions.md#L15-L17)原子重核新 cap，不低于已承担责任才可激活。[ADR 0032:10–49](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0032-fill-allocation-policy.md#L10-L49)定逐腿归属、净额累计配额法 /2、费用和更正。净省不复用。 | [#1408](https://github.com/Newchanlun/NewChanlun/issues/1408)、[#1428](https://github.com/Newchanlun/NewChanlun/issues/1428)、[#1406](https://github.com/Newchanlun/NewChanlun/issues/1406) 承接；缺 profile 有效 cap/变更授权只挡相应动作，账面权益不代 cap；缺归属或前件按 C06 处置。 |
~~~

依据：[ADR 0029:13–37](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0029-common-cap-contention-policy.md#L13-L37)；[ADR 0049:15–17](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0049-funding-quantity-and-policy-reference-dimensions.md#L15-L17)；[ADR 0032:10–49](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0032-fill-allocation-policy.md#L10-L49)；[ADR 0041:39–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md#L39-L48)。

**L401 改前**

~~~markdown
| FU-07 | 系统风险与结构判据名分已定；完整退出授权及责任退休策略仍需明确 | 相应退出/迁移/场所行为 |
~~~

**改后**

~~~markdown
| FU-07 | [ADR 0030:13–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0030-exit-authorization-and-liability-retirement.md#L13-L48)定结构/具名风险/手动退出及动作范围。场所订单终态、原 Voice 仓位为零、真实费用结清且 E 无 Pending，才可退休责任；迟到事实按原 Voice 重开。P1 风险清单按[ADR 0045:27–55](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0045-sr-v1-policy-signed.md#L27-L55)，拒发期间同一退出授权待续（[ADR 0030:70–76](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0030-exit-authorization-and-liability-retirement.md#L70-L76)）。 | [#1380](https://github.com/Newchanlun/NewChanlun/issues/1380)、[#1397](https://github.com/Newchanlun/NewChanlun/issues/1397) 承接；仍验具体外部终态/费用/持仓证据与适用风险、退出授权。新真实权限或超出原授权范围须按原门签署。 |
~~~

依据：[ADR 0030:13–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0030-exit-authorization-and-liability-retirement.md#L13-L48)；[ADR 0045:27–55](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0045-sr-v1-policy-signed.md#L27-L55)；[ADR 0030:70–76](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0030-exit-authorization-and-liability-retirement.md#L70-L76)；[ADR 0041:39–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md#L39-L48)。

**L403 改前**

~~~markdown
未决定项当前留在 #1339 已签需求与本 SPEC 依赖中，尚未自动成为新的已发布子票。获准拆票时先查重再建立真实承接和原生 blocking 边；不得发布一个无阻塞的 ready-for-agent 任务让实施者顺手代裁。
~~~

**改后**

~~~markdown
按现有实施票承接已裁规则及证明义务。缺有效记录、真实证据或用户签署时，只封该门覆盖的动作；不得由实施者补造政策、代签真实资金/账户/凭据或把旧有效版本跨域使用。真正未裁且进入实施范围的事项须先有具名裁定与真实 blocking 边，不得先放行实施票让实施者顺手代裁。
~~~

依据：[ADR 0041:39–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md#L39-L48)；[ADR 0028:66–73](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L66-L73)；[ADR 0036:24–33](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0036-operating-statistics-sampling-and-post-gate-parameter-protocol.md#L24-L33)；C12 原有真实前置及 #1909 普通 SPEC 与实际外效分离。

## B5 历史模型与场所：域内撮合，P1、P2 分证

**L196 改前**

~~~markdown
72. **US-FG-028** 作为多重经营使用者，我需要完整处理「回测成交假设与真实外部成交不能混证」并能查看严格穿越/开盘取优/GTC/双滑点纪律；同slot未定义次序具名等待，以便核对实际状态、依据及其变化。（C07, C08, C12）
~~~

**改后**

~~~markdown
72. **US-FG-028** 作为多重经营使用者，我需要完整处理「回测成交假设与真实外部成交不能混证」并能查看严格穿越/开盘取优/GTC/双滑点纪律；同批域内订单按已知前沿撮合，批内先后为 Unknown；域外模型请求具名拒绝，以便核对实际状态、依据及其变化。（C07, C08, C12）
~~~

依据：[ADR 0033:10–44](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L44)；[ADR 0052:273–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L273-L291)。

**L346 改前**

~~~markdown
3. 历史使用明确的模拟能力 profile。既有 bar 限价穿越、开盘取优、GTC、限价费用口径及其适用范围继续保留；新多重并发、混合订单和分配模型无裁定时显式 ModelOrderUnspecified，不能照旧单净单实现自行外推。TestOnly 顺序可用于协议试验，但不能证明完整经营验收。
~~~

**改后**

~~~markdown
3. 历史按[ADR 0033:10–44](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L44)的 `history-sim/bar-batch-known-frontier/1`（确定性，`seed: none`）与[ADR 0052:258–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L258-L291)的 `history-input-profile/1`；继承严格穿越、开盘取优、GTC 与费用纪律。第 t 根 bar 只消费 t−1 收盘时已知且获准的集合；同批各重限价独立对 OHLC 判定，`intra_batch_order: Unknown`。市价仅在具名 `exec_index` 收盘槽成交，限价逻辑先于该槽；t 收盘才知道的新挂/撤/改从 t+1 起生效。部分成交依具证容量合同（含[ADR 0033:77–116](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L77-L116)的容量 epoch），容量合同为 `none` 时，已准入规模内严格穿越即全量成交，单列 L0 假设，不作容量证据；历史默认 `per_leg`，与场所对拍采用该场所冻结的同一 `projection_kind`。域外订单/并发/分配请求在 E-Release 前由 `model_coverage` 持久记为 `Unsupported{reason: ModelOrderUnspecified, model_ref, domain_id, command_id}`，不释放、不执行、不生模拟外效、不回落旧臂。TestOnly 排序只验协议。
~~~

依据：[ADR 0033:10–44](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L44)；[ADR 0033:77–116](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L77-L116)；[ADR 0052:258–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L258-L291)。

**L349 改前**

~~~markdown
6. 首个真实场所、账户/产品、费率/保证金/借贷规则及允许的查询/取消/退出动作仍须明确决定。adapter 合同可先以受控模拟和已留存无敏感回报验证；需要真实外效的验收须独立授权，不因名称为 paper、post-only 或 ALO 推定不会成交。
~~~

**改后**

~~~markdown
6. 首个场所能力验收为[ADR 0028:13–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L13-L48)的 `P1-hl-testnet`：Hyperliquid testnet 主 DEX 加密永续、Netting、`experiment`，绑定账户、endpoint 与专用 API wallet（`trade_no_transfer`），范围为已授权的查询、下单、撤单和 reduce-only 平仓，不含划转、提现或创建子账户。费率、保证金和适用的借贷规则须绑定受测 profile 与证据。按[ADR 0028:91–99](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L91-L99)和[ADR 0062:155–197](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0062-fu18-venue-account-permission-binding.md#L155-L197)先核有效的用户授权、身份、凭据作用域、会话权限和 TB-09 指纹，再构造写传输；不因 paper、post-only 或 ALO 推定不会成交。可用余额前置读不到时，本次只取 P0 确定性回放与受控模拟证据，不做主网存款；P0 不代 P1 场所成功路径。P2 按 C12 保持未启用。
~~~

依据：[ADR 0028:13–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L13-L48)；[ADR 0028:91–99](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L91-L99)；[ADR 0062:80–82](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0062-fu18-venue-account-permission-binding.md#L80-L82)；[ADR 0062:155–197](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0062-fu18-venue-account-permission-binding.md#L155-L197)；[ADR 0028:66–73](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L66-L73)；[ADR 0044:19–41](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0044-cost-stop-policy-signed-instance-v1.md#L19-L41)；[ADR 0045:27–55](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0045-sr-v1-policy-signed.md#L27-L55)。

**L364 改前**

~~~markdown
2. 下列 TB 是待拆票的纵向切片键，不是已创建 issue 或已启用的执行 DAG。每个切片交付可运行的输入到外部可见结果；依赖未清的能力不得准入，切片完成也不关闭整个 SPEC。
~~~

**改后**

~~~markdown
2. 下列 TB 是已人工拆分并挂在本 SPEC 原生子树中的纵向切片。每个切片交付可运行的输入到外部可见结果；依赖未清的能力不得准入，切片完成也不关闭整个 SPEC。
~~~

依据：GitHub REST 原生 [#1340 子票](https://github.com/Newchanlun/NewChanlun/issues/1340)，核法见交付说明；#1561 resolution 已使用既有 #1365/#1368。

**L374 改前**

~~~markdown
| TB-07 | 完整历史双跑、断点恢复、seek/断线续接、AsKnown/重算分证 | TB-02/05/06；完整历史模型 |
~~~

**改后**

~~~markdown
| TB-07 | 按 C10 的具名模型跑域内同批成交与域外拒绝，再验完整历史双跑、断点恢复、seek/断线续接及 AsKnown/重算分证 | TB-02/05/06；[ADR 0033:10–44](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L44)、[ADR 0052:258–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L258-L291) |
~~~

依据：[ADR 0033:10–44](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L44)；[ADR 0052:258–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L258-L291)。

**L375 改前**

~~~markdown
| TB-08 | paper/live adapter 共核、身份/能力/回报证据按范围验收 | TB-04/05/07/09；场所与验证权限 |
~~~

**改后**

~~~markdown
| TB-08 | paper/live adapter 共核；按 P1-hl-testnet 核实际身份、能力与回报证据，标 experiment | TB-04/05/07/09；P1 有效 profile、证据和逐动作权限 |
~~~

依据：[ADR 0028:13–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L13-L48)；[ADR 0028:91–99](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L91-L99)；[ADR 0062:155–197](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0062-fu18-venue-account-permission-binding.md#L155-L197)。

**L376 改前**

~~~markdown
| TB-09 | 受测部署旧写入口禁入、正式 launcher 的 X 独占发送闭环成立；隔离身份与在途责任可查 | TB-04；目标部署身份、凭据及权限明确 |
~~~

**改后**

~~~markdown
| TB-09 | 在 P1 受测部署证明旧写入口禁入、X 排他及发送前重核；隔离身份与在途责任可查 | TB-04；P1 部署身份、凭据作用域与授权证据 |
~~~

依据：[ADR 0028:66–73](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L66-L73)；[ADR 0028:91–99](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L91-L99)；[ADR 0062:155–197](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0062-fu18-venue-account-permission-binding.md#L155-L197)。

**L377 改前**

~~~markdown
| TB-10 | 所有旧入口取得终态，带仓迁移和回退不丢责任，默认启动只到新核 | TB-02/05/07/08/09；对应迁移和启用批准 |
~~~

**改后**

~~~markdown
| TB-10 | 所有旧入口取得终态；在 P1 验带仓迁移、回退保责与默认启动只到新核；生产专属门见下 | TB-02/05/07/08/09；对应迁移和启用批准 |
~~~

依据：[ADR 0028:66–73](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L66-L73)；[ADR 0062:254–260](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0062-fu18-venue-account-permission-binding.md#L254-L260)。

**L380 改前**

~~~markdown
场所验收的前置隔离与生产迁移分为两个切片，顺序为 TB-04 → TB-09 → TB-08 → TB-10 → TB-11；TB 编号不是执行顺序。TB-09 不提前声称所有旧实现已收编或生产迁移已完成。独立实验部署可验收其特定环境、账户、endpoint、凭据作用域和 X 排他性绑定的能力 profile；该结果不能替代生产旧凭据、launcher、OS 身份、在途最大责任和带仓身份映射的验证。生产首次新发送前必须重核目标部署 TB-09 隔离证据仍有效，保留旧最大责任，不能自动恢复旧 writer。具体排程边见[排程附件](https://github.com/xy7365527-lang/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/payload/spec/PLANNED-DAG.json)，故事的销项切片集合不得机械变成阻塞边。
~~~

**改后**

~~~markdown
场所验收的前置隔离与生产迁移分为两个切片，顺序为 TB-04 → TB-09 → TB-08 → TB-10 → TB-11；TB 编号不是执行顺序。TB-09 不提前声称所有旧实现已收编或生产迁移已完成。按[ADR 0028:66–73](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L66-L73)，本图 TB-09/TB-10 验 P1（前置余额读数失败时只保留 P0 射程），P2 不做真钱首发，首发授权格式只登记、不执行。目标生产的旧凭据/launcher/OS 身份隔离、带仓身份映射及默认启用批准仍是生产首次新发送前的独立硬门。到该时点必须先重核目标部署 TB-09 指纹、确认旧责任保留，再由用户本人签署该次具名首发；重核失败拒绝发送，不恢复旧 writer。P1 证据不代生产。具体排程边见[排程附件](https://github.com/xy7365527-lang/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/payload/spec/PLANNED-DAG.json)，故事的销项切片集合不得机械变成阻塞边。
~~~

依据：[ADR 0028:44–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L44-L48)；[ADR 0028:66–73](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L66-L73)；[#1561 resolution](https://github.com/Newchanlun/NewChanlun/issues/1561#issuecomment-6311315578)。

**L398 改前**

~~~markdown
| FU-04 | 模拟/真实分证和能力合同已定；具体场所、账户、权限及真实验证范围仍需明确 | 相应 TB-08 |
~~~

**改后**

~~~markdown
| FU-04 | 已定首个场所验证 profile，按[ADR 0028:13–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L13-L48)、[ADR 0028:91–99](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L91-L99)与[ADR 0062:155–197](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0062-fu18-venue-account-permission-binding.md#L155-L197)验 P1；P2 按[ADR 0028:66–73](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L66-L73)不启用。 | TB-08/09/10 在各自射程验证；P1 核实际账户、能力原件、有效版本、授权及发送前证据；生产专属证据与用户首发签署只在未来 P2 激活时消费。 |
~~~

依据：[ADR 0028:13–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L13-L48)；[ADR 0028:91–99](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L91-L99)；[ADR 0062:155–197](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0062-fu18-venue-account-permission-binding.md#L155-L197)；[ADR 0028:66–73](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L66-L73)。

**L426 改前**

~~~markdown
| AT-14 | 相同完整输入/版本/时钟/调度双跑全状态等价；AsKnown 不回填、重算另列；seek 不偷用未来数据 | C10；Destination 4 |
~~~

**改后**

~~~markdown
| AT-14 | 域内正例（`per_leg`）：两个重的 GTC 买限价 100 与 101（测试 tick），在 t−1 收盘已获准且各自资金独立，规模在已准入的全量撮合域内；t 的 O/H/L/C 为 102/103/99/102，两单各自严格穿越并撮合，归原重、批内先后 Unknown。域外反例：请求同 bar 按未观测逐笔先后决定互斥腿成交，profile 不支持该并发形态；E-Release 前出 ModelOrderUnspecified，该请求零旧臂调用、零成交/费用原件。相同完整输入、版本、时钟和调度双跑核全状态等价；AsKnown 不回填、重算另列；seek 不偷用未来数据。 | C10；Destination 4 |
~~~

依据：[ADR 0033:10–44](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0033-history-simulation-bar-batch-model.md#L10-L44)；[ADR 0052:273–291](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0052-history-input-profile-and-model-order-unspecified.md#L273-L291)；数值是由严格穿越规则构造的测试输入。

**L427 改前**

~~~markdown
| AT-15 | adapter 真实能力的每条证据对应成功/不支持/故障行为；模拟与场所真账单源，缺能力不能放行 | C10；Destination 5 |
~~~

**改后**

~~~markdown
| AT-15 | P1 按有效 profile 逐项核 adapter 的成功、不支持与故障，验证身份、授权、TB-09 指纹、实际发回的场所原件及唯一真账；缺能力不放行，P0 模拟与 P1 场所真账单源分证。TB-09/10 的 P1 隔离与带仓回退证据不作 P2 生产证据，P2 首发另守 C12 硬门。 | C10；Destination 5 |
~~~

依据：[ADR 0028:13–48](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L13-L48)；[ADR 0028:91–99](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L91-L99)；[ADR 0062:155–197](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0062-fu18-venue-account-permission-binding.md#L155-L197)；[ADR 0028:66–73](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0028-first-capability-verification-profile.md#L66-L73)。

## B2–B5 共用说明：现行表优先，归档不变

**L386 改前**

~~~markdown
下表是本轮核实的依赖，批准本 SPEC 不等于选择其空缺答案。来源、旧裁定射程及后裁检索见[残留核查](https://github.com/xy7365527-lang/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/inputs/RESIDUAL-DECISIONS.md)；全部 G/FU 的逐项承接见覆盖附件。既有 closed 票仅承接其已裁内容，未登记新残留的票不能被声称已接单。
~~~

**改后**

~~~markdown
下表的已裁规则与 C03–C06、C10、AT-06/14/15/17 的对应条款优先于 2026-09-09 归档附件在这些事项上的旧描述。覆盖附件的 FG-018 开重起点、FG-025 样本以及对应 G/FU 的旧「待裁」条目按此处读取；覆盖 ID、其余验收义务与历史字节不改。[签署时残留核查](https://github.com/xy7365527-lang/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/inputs/RESIDUAL-DECISIONS.md)仅供追溯。当期验收凭实施、证明和适用域的有效证据，不凭决策票已关。
~~~

依据：覆盖关系：FG-018 [ADR 0040:38–59](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0040-funding-signature-and-chong-derivation.md#L38-L59)；FG-025 [ADR 0036:10–22](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0036-operating-statistics-sampling-and-post-gate-parameter-protocol.md#L10-L22)；G/FU 按下表逐行所引已采纳裁定。

**L388 改前**

~~~markdown
| 依赖 | 当前可继承与尚缺的具体内容 | 受阻行为 |
~~~

**改后**

~~~markdown
| 依赖 | 已裁规则与适用域 | 实施、证明或仍缺的生效前件 |
~~~

依据：列名区分下表各行已采纳裁定与落地证据；不改变原依赖方向。

## 交付与放行

[parseSplitPlan](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/scripts/wayfinder_engine.mts#L388-L407) 读内联 JSON 计划，原正文与 R3 均返回 `null`；[拆票执行器](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/scripts/wayfinder_engine.mts#L1287-L1295) 因此不会自动新建或补发计划票。
[SPEC 祖先索引](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/scripts/wayfinder_engine.mts#L601-L639) 和 [挂队列前复核](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/scripts/wayfinder_engine.mts#L922-L961) 允许 SPEC 原生子树内无机拆标记的既有实施票按祖先链上每张 SPEC 的当前有效 PASS 取得授权；仍须进入扫描集、具备实装票身份，且无负责人、open blocker、hold 或 open 子票等拦截。
仅从 map 继承授权而祖先链上没有 SPEC 的票，没有当前计划项不会放行；SPEC 子树内带机拆标记的票也须匹配计划身份和绑定当前正文的发布凭据，本轮无计划不会放行这类票。
用 `gh api 'repos/Newchanlun/NewChanlun/issues/1340/sub_issues?per_page=100' --paginate` 取直接子票，对照原 TB-01 至 TB-11 汇总票号与标题并查 `<!-- wayfinder-ticket:1340:`，确认这 11 张汇总都在原生子树且未带此标记；这是授权路径核查，不承诺汇总或任一叶子立即获队列标签。

主控先发布 `body-r3.md`，再以实际已发布正文交非作者独审，之后按 #1909 发布绑定新正文的结构化裁定。本分支不含裁定或 GitHub 票面修改。
