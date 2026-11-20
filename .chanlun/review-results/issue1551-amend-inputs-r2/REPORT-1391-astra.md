# #1391 / TB-11-A 独立审阅：不能用这版 AT-18 通过整图验收

**结论：BLOCK。** 在没有 remote 的合成 Git 仓中，输入中的独评和 CI 都指向旧提交，旧提交之后产品文件发生变化；另一份原件明确只覆盖故事 001、排除故事 002。用候选的真实 CLI 同时核这两件事，仍得到 **TB-02 门满足、两个故事 VERIFIED、整图 PASS、零条 FailedCheck**。[命令驱动](isolated-cli.ts) · [实跑回执](isolated-cli.json)。真实项目没有被置为 PASS：审阅时实际 main 的复跑是 **FAIL / 5,323 条**。前者证明生成器能错放行；后者只证明当前这组缺证输入被拦住。

## 审的是什么

- #1391 票面要求从真实交付与报告逐项对账。比较范围为 `6ba72e84c55aa6d65b11cc46b7288142f4fce62b...b22fd4960d6f18088f19ed7bb9c94144cf2ee3c4`，左端既是 `origin/decision/1551`，也是两端的 merge-base。[差异](diffstat.txt)：新增 5 个文件、1,447 行，恰为实现、CLI、测试、两份 fixture；未改 ADR、delivery-bundle、依赖或锁文件。候选未进 main。
- 合同：[ADR 0064](/Volumes/AgentStorage/review-1391-b22fd496/docs/adr/0064-at18-whole-graph-acceptance-and-closeout.md)，以此基线全文为准；[自身 manifest 形状](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/delivery-bundle.ts:27)、[一次收齐交付材料](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/CODEX-CHILD.md:41)。下文 `ts` 指 [at18-report.ts](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts)，`mts` 指 [CLI](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.mts)，`test` 指 [候选测试](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.test.ts)。所有代码行号均属上述候选。
- 证据分三类：① 用冻结观察和真实 Git blob 跑当前主线；② 用候选测试的正控作底、每次独立换输入，记录发生变化的结论；③ 在无远端的本地 Git 仓让原 CLI 实际读 blob、算摘要、查祖先、落盘。②③的 PASS 只描述工具的行为。完整 [输入及生成器探针](probes.ts)、[逐例结果](matrix.json)、[补充探针](additional.ts)、[补充结果](additional.jsonl)。

## 影响交付的发现

| 严重度 | 位置 | 最小反例与实际后果 | 修订归属 |
|---|---|---|---|
| **HIGH 1：可读文件被当成它没有证明的子义务** | [ts:479–483](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:479)、[748](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:748)、[845–856](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:845)、[875–882](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:875) | 给 US-ST-001、002 的切片同一份原件，原件明确排除 002：两者均 VERIFIED。把 DST-01 的 obligations 原件换成只适用于 DST-06 的文件：输入包与报告**逐字节不变**，新引用在产物中找不到。给 TB-02 一份内部 `content_hash` 错误的 AT-18 包充当其实体报告，外层文件摘要计算正确，仍 PASS。 | #1391 核实原件**哪一项**证明当前义务、切片、证据类和结论；不能仅看观察者填的 CONFIRMED、引用非空和文件摘要。同一报告可合法证明多项，须能逐项定位，不能一律禁重。需要新的跨产品原件协议时先回 #1551。 |
| **HIGH 2：CI 和独评不必覆盖最终产品，子片分母也由输入自报** | [ts:571–584](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:571)、[741–746](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:741)、[763–789](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:763) | 真实 CLI 读到 TB-02 产品 `bc2efc7e72`；CI 与独评只到祖先 `d4f14d7889`，其后 `product.txt` 已改，仍 PASS。另将 TB-02 的期望与实收名单一起缩到 `[1373]`，仍 PASS。不读真实 CI run、适用必需检查集合、最终差异覆盖或独评归属；普通 TB 只要求任一祖先有成功记录。TB-11 虽逐子片匹配 SHA，却也准许父票、#1391、#1403 在报告生成时全为 CLOSED。 | #1391 从独立来源取得本票应交子片、适用检查及最终差异；确有产品字节相等的纯报告尾部按交付协议复用，不把“同在 main”当覆盖。按 §三区分正式生成与事后重放。 |
| **HIGH 3：权限、迁移及证据类可以与原件相反** | [ts:547–567](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:547)、[636–657](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:636)、[678–687](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:678)、[799–805](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:799) | DST-05 的启动核验原件明确写第 4–7 步 FAIL，Destination 及整图仍 PASS。迁移原件写明空持仓、空未结单、未运行，只给观察四个 true，TB-10 仍过。只在 TB-08 experiment 槽放明确标为 simulation 的原件，仍过。classRefs 能拦“同字节先后登记在两类”，不能发现单向错分。 | #1391 从同 profile/类/版本的原件导出三层、场景与四不变量。能力版本和两枚摘要的生成可保留；它们不是启动核验或非空运行的证明。 |
| **HIGH 4：#1358 未触闸豁免既能颠倒状态，也能套在无关故事** | [ts:614–618](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:614)、[699–728](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:699)、[865–875](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:865)；[test:252](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.test.ts:252) | 未启用原件明写 `growth_enabled=true, gate_reached=true`，观察写 NOT_TRIGGERED、附具名未执行项，整图仍 PASS。反过来，激活链首件明确为 TestOnly / SimulatedGateReached，仍 TRIGGERED_AND_ENABLED。给结构故事 US-ST-001 的延期依据写 `p2_first_send_applies:false`，该行仍 BOUNDED_DEFERRED。 | #1391 按 ADR 0036 §七的实际触发种类、growth_enabled、AwaitingPolicy、profile/类核原件；只按该子义务已裁门延期。新投影字段、门与子义务的定位协议归 #1551。 |
| **HIGH 5：七张旧票的处分可以反着填；#1279 自身状态还漏掉覆盖总门** | [ts:911–938](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:911) | #1279 保持 OPEN，却明写“已宣布试运行放行”，剩余列“#1323 Destination ⑥ 尚未完成”，仍 `disposition_valid=true`、整图 PASS。#942 恢复强平、#1282 旧实验代新验收、#1096 未核退场即删、#1304 尚缺报告器却关闭、#1319 用旧简化链、#1320 用一个零年样本关闭，逐例也都有效。另只把故事 97→96，整图 FAIL 而 #1279 仍 valid：它只查现存行是不是 FAIL，不查覆盖本身完整。 | #1391 对每票核对应原件和规则，而非从文字猜含义或用一个通用“去向已确认”位；#1279 消费含数量、未知项与缺失项在内的完整覆盖结果。不得关闭 #1279 或宣布放行。 |
| **MED 6：一个坏元素抹掉 96 条可用故事** | [ts:813–825](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:813)，ADR §五:61 | 仅移除 crosswalk 第 3 个故事的 `story_id`：整个故事数组变 `[]`，而不是保留 96 条并报告坏元素；families/details 未受影响。还把许多原本存在的观察报为不在 crosswalk。 | #1391 按可变长数组的**单元素**派生、逐项报 SCHEMA；保留可读文件摘要与可用元素。 |
| **MED 7：CLI 把可局部记账的问题升级为整批无文档** | [mts:35–41](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.mts:35)、[60–68](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.mts:60)、[ts:540–545](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:540) | 给旧票的一个可省剩余项放孤立代理码点：CLI 直接 CONTENT_NOT_CANONICAL、退出 1、无文件；§五:60 要先在安全的 FailedCheck.detail 描述，仍无法规范化才 BLOCKED。缺固定 TB 票态时报 FIXED_ITEM_UNAVAILABLE 是对的，但同时不发布已具备自身身份和全部规范字节的输入包。 | #1391 区分输入包与报告的引导条件，区分固定项与可转述的坏证据；#1551 可明示“仅报告引导失败时输入包是否独立发布”。 |
| **MED 8：CLI 没有合法 squash 路径的查询能力** | [ts:219–225](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:219)、[409–415](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:409)、[mts:21–33](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.mts:21) | 库的正例靠注入 `mergedMainCommit`；CLI 的 source 不实现它。对一个源 head 不是主线祖先、而 GitHub 记录确实满足 §五:62(b) 的上游仓外报告，CLI 只能判祖先失败。 | #1391 接入并验证规定的 PR 已合到 main、精确 head、merge SHA 的祖先关系；不要把所有非祖先都算作 squash。CI/独评的等价绑定另见下表。 |
| **MED 9：字节摘要不符的已登记自身实体没有阻断生成** | [ts:367–375](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:367)、[mts:35](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.mts:35)，[交付协议:61](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/CODEX-CHILD.md:61) | 自身清单合法、已登记文件实际非空，登记的 SHA 填 64 个 0：CLI 退出 0，写包、报告和摘要，没有 BLOCKED。若摘要**格式**非法则退出 1 且无文件。即使使用已封包清单，CLI 也允许写到与清单所登记路径不同的新目录。 | **不满足本次要求的“摘要不符即无文件”**。ADR §五:60 明写引导只需可读且过 deliveryManifestSchema，可尚未登记本次产物，自身清单也没有自摘要字段。请 #1551 明定对**已登记**实体的引导检查及诊断；若保留两阶段，必须在最终封包预检阻断。不应把完整预检硬塞给空引导清单。此项不是 HIGH 1–5 的前提。 |
| **MED 10：测试能拦缺 TB 报告，拦不住删除覆盖数量门** | [ts:791](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:791)、[831–834](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.ts:831)、[test:147–156](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.test.ts:147)、[224–239](/Volumes/AgentStorage/review-1391-b22fd496/.sandcastle/at18-report.test.ts:224) | 仓外副本删 ENTITY_REPORTS 检查：1 红。独立副本只删 `count.every(...)`、保留摘要条件：13/13 绿。正控验“当前有 97 条”抓不到少一条仍放行。 | #1391 用三组各减一且同步去掉对应观察的负例断言 CROSSWALK_ALIGNMENT，并锁住上述真实错放行。 |

## ADR 0064 合同对照

“满足”指对应规则在所列边界得到证实，不代表组合后满足关票门。“后序”是 ADR 明确分给 #1403 或关图人的动作，不因本片未实现而扣分。

| 条文 | 需满足的输入、派生或结论 | 候选结论 |
|---|---|---|
| §一:9–13；§二:17,27 | 本票只对账；六项完整义务、实施票/范围/精确 commit、最终独评、主线/CI、按类运行件、下游状态、剩余项及结论。拒收局部成功、空域和仅协议。 | 形状齐；6 项按正本顺序输出。有非空引用、有任一成功祖先不等于取得该范围证据（1、2、3）。 |
| §二:21；§五:68,94–95,97 | 仅 simulation/experiment/production；启用槽数组、禁用槽 null；P2 首发前与生产闸门后两项具名且 required=false。 | 输出编码、具名项和类枚举有检查；生产启用只由一个观察布尔值决定，原件单向错分可 PASS（3）。 |
| §二:22；§五:69–71,90–91 | DST-05 逐槽授权声明、场所权限事实 URL/日期/摘要、运行时第 4–7 步；能力版本/能力 SHA/profile SHA 各有原件。缺哪层记哪层 null 并单列失败；同版冲突、顶层/槽值不同不通过。 | 缺层、摘要和同版能力内容冲突有检查；顶层复制自相同 tuple。没有从同一受测身份核实授权行/启动结果，单独一份投影可自称是来源栏（3）。 |
| §二:23；§五:77,94,101 | DST ②③⑤ 与 TB-10/#1402 的非空持仓、未结单、费用尾、恢复/回退；四不变量同时成立，区分类。 | 有四个布尔值、非空 refs、DST/TB-10 联动；空样例仍可通过（3）。 |
| §二:24；§五:78,95,97–98 | 四种 PostGateSlot；同类/profile 和互引、严格时序；已激活必须三原件；已授权未启用两件，等策略一件，未触达零件并有未启用证明；后三态如实记 bounded_domain_statement + 对应具名未执行。 | 有三个时间戳、顺序（含亚毫秒）、部分单向引用、空位和具名项检查；无实际触达/待策略/未启用语义核验，也不检 bounded_domain_statement 是否相反（4）。 |
| §二:25；§五:79–82,93 | 97 stories/345 families/496 details；顺序、ID、引用、OE41/OE45 排除边界、OE42 REQUIRED 但须遵守 coverage input 的处分；逐子义务非空且只在具名边界延期。 | 对真实 crosswalk，数量、行序、模式及 OE42 指针正确；计数来自 crosswalk，非观察数组长度。scope 不相干/具名门不适用仍可通过；1 坏行删掉整个分组（1、4、6）。 |
| §三:31,35；§五:92 | TB-01..10 要有全部内部子片、实跑分槽、最终独评、main/适用绿 CI、实体非空、剩余义务清空、合法关闭；其 input_bundle 固定 null；TB-08..10 分槽，TB-10 自身非空迁移。 | 明确的 OPEN、空实体、非绿 CI 会被挡；子片分母及票态自报，CI/独评/运行不必证明本产品（2、3）。 |
| §三:36；§五:82,92 | TB-11 专用前置：#1391/#1403 两实现、两个 main_sha 与其 CI/独评、共同 input_bundle；空业务证据、entity_reports=[]；本次报告不引用自身/未来回执，正式生成时三票 OPEN。只由 TB-11 关的子义务可直接用共同输入包。 | 两子片、空业务槽及 input_bundle 的外层字节引用成立；缺件各留红。US-ENG-10 无单独观察仍可用 TB-11 前置销项是**合同允许**，不得一刀切。不强制报告阶段票态（2）。 |
| §三:37；§五:53,103,105；§六:109 | #1391 正式包/报告 + 独评及仓外预检；随后 #1403 独立复算；两者通过并依序关票才能关 #1369/#1340/#1323；#1279 另有自有检查。#1366/#1418 保留原职责。 | 后序。#1403 的 12 键回执另有自身引导，须独立复算输入包/报告/清单绑定、外部 PR、覆盖和业务事实；引导成功后，即使受验对象缺失也应出 FAIL 回执。CLI 不写 #1403 回执也不关票；不得拿 CLI 返回 0、两份可解析 JSON 或本次 FAIL 演练代替任何一个关票动作。 |
| §四:43–49 | #942 保留逐问处分；#1096 冻结/收编与未来删除分证；#1282 留冻结实验；#1304 报告器、回归锁、完整回放；#1319 feed/wire、正式意图与隔离归不同 TB；#1320 图内正式回放与图外七标的十年 1min 分列；#1279 OPEN、无图内残债、未宣布放行。 | 固定七项顺序与若干票态检查存在。#1320 缺重型原件时需 OPEN 和具名未执行项；但不相干原件可解除它；其余各项均已找到反语义输出（5）。 |
| §五:53,85 | 包：10 键；版本、hash、ticket=1391/base/head、时间、三个规范 ref 取指定 head 的指定 Git blob；external_manifests 无重复登记上游。三份必需规范任一不可读不出包，报告须 FAIL 而非因此 BLOCKED。 | 正常 CLI 的身份取自自身清单；真实字节计算三 ref，读失败、上游清单解析/重复有诊断，缺包写 TB-11.input_bundle=null。包**没有 coverage 数组**；有无覆盖要查它绑定的 crosswalk 和报告，不把私有 observations 冒充输入包。 |
| §五:53,57–59,87–99 | 报告 18 键；摘要只从同一 JSON 渲染。全部嵌套封闭，正整数、UTC、SHA、枚举、固定 6/11/7 及顺序；显式缺失槽值，数据身份与语义判据分层。 | 顶层、嵌套错键/版本/错自身摘要、固定顺序均有拒收。摘要确定性渲染。通过单文档形状不等于跨文档或业务验证；形状合法的 FAIL 能记录缺证。 |
| §五:57,61 | 自身 content_hash：去**顶层**同名键，JCS UTF-8，再 SHA-256 小写；文件完整字节 SHA 与之不同。严格 JSON 对象、合法 UTF-8、无重复键；投影只走所需步骤。 | JCS 核通过 RFC 向量，见下。FILE_READ/JSON_PARSE/JCS_CANONICALIZE/SCHEMA 可区分。规范、bundle/ref、venue 原件、capability 的文件摘要只依赖字节；上游 manifest 走四步。coverage/时间/版本只解析所用字段，这一例外不等于其他类型的证据也只看 SHA 即可。 |
| §五:59–61 | 形状失败与判定失败分开；缺证填 null/[]，坏可变数组元素只不列该项，FailedCheck 指向失败步骤；固定项不可得不猜；坏字符串先安全描述。 | 缺 review artifact 通常不列该元素。crosswalk 可变数组全组丢失、坏观察提前整批 BLOCKED（6、7）。#1403 的 report_content_hash 只需前三步，本片不产生这个字段。 |
| §五:60 | 按序获取自身清单→固定项实际值→可规范化→临时文件改名。BLOCKED 写 stdout + DeliveryDiagnostic，退出 1；第 1 步失败两文档均不存在。 | 缺清单、无效清单/票号、缺固定 TB、既有目标得到相应具名诊断。实测缺/坏清单连临时文件都没留下。已登记原件摘要不符却写出文件（9）；局部失败与可恢复坏字符见 7。 |
| §五:62,66–67 | 正式 head 等于实际 origin/main；仓内 ref 仅从对应 Git blob，SHA 与祖先相符；仓外 ref 必须仓外、无跳转/符号链、唯一匹配 manifest 的绑定及文件 SHA；允许有已合入 main 的精确 squash 记录；不靠 PR 标题定票。 | 常规路径、字节、身份与祖先有检查，无跨存储回退；CLI 实际读本地 remote-tracking ref，本次已独立对远端；CLI 缺 squash 查询（8）。工作流应固定或更新真正的审定 main，不能把陈旧 tracking ref 称为实时远端。 |
| §五:64,72–76,83 | ManifestRef 5 键 / ArtifactRef 8；ReviewRef 4 / CiRunRef 5 / TicketScopeRef 2 / SliceStatusRef 3 / DownstreamStatusRef 2；FailedCheck 恰 4 键 scope、check_id、detail、nullable evidence_ref。 | 字段齐；可解析相应原件和引用并不证明 reviewer 非作者、工作流适用、工单实际被覆盖（1、2）。 |
| §五:97–101 | 未执行 obligation 不重复，四个指定常量按条件和类出现；有 required=true、permission_blocked 或 FailedCheck 即不准 PASS；所有复合门**同时**成立。 | `overall_result` 是真正判别联合：静态及运行时均拒绝 PASS 带失败、FAIL 空失败；已记录错误确实令整图 FAIL。缺陷在于应记录的错误根本没有加入列表（1–5），不是最终 if 写反。 |

## 攻击矩阵：哪些东西真被挡住

| 单项变化 | 实际输出 | 判读 |
|---|---|---|
| TB-02 无 entity_report；产品 main_sha 不可达；证据 commit 不可达；CI 明示 FAILURE | 分别 FAIL：ENTITY_REPORTS、MAIN_COMMIT、ARTIFACT_ANCESTRY、REQUIRED_CI | 正确。真实 CI 的适用性另见 HIGH 2。 |
| 外部文件原字节已改；仓内实体 SHA 错；两种 AT-18 文档自身 content_hash 错 | 前两者 FAIL / ARTIFACT_HASH_MISMATCH；后两者 schema 拒绝 | 正确。若把内部摘要错的包改作 TB 实体，只验封皮，仍 PASS。 |
| 同一原件只证明 001、明确排除 002，重复给两行 | 两行 VERIFIED，整图 PASS | 假 PASS。 |
| 分别整项去掉故事 US-ST-001、family ST-001、细项 A-ST-001-01 的观察；加入不存在的故事 | 前三项分别 FAIL / COVERAGE_TB-01 等；多项 FAIL / COVERAGE_UNKNOWN_ENTRY | 正确。TB-11-only 的合同例外另列于上。 |
| crosswalk 和观察同时分别少一个故事/family/细项（96/344/495）；清空全部 coverage；清空 TB-02 slices | 三次均只有 CROSSWALK_ALIGNMENT；空 coverage ⇒ COVERAGE_EVIDENCE 等，空 slices ⇒ IMPLEMENTATION_SLICES | 整图正确 FAIL。少一个故事没有传递到 #1279。 |
| 输入包/报告错版本、额外顶层键、额外嵌套键；PASS 带 FailedCheck；FAIL 不带 FailedCheck | 逐个 schema 拒绝；非法联合也被 TS 拒绝 | 正确。合法空数组不一概拒绝，例如未产出本次报告时 TB-11.entity_reports 必须为空。 |
| 非法缩减 TB 子片分母、用旧 CI/独评、上游证据声明范围相反 | 整图 PASS，零 FailedCheck | 假 PASS。 |
| 正常未触闸但无未启用证明；已有触达与启用却填 NOT_TRIGGERED；把 P2 门给不适用的结构故事 | 前者 FAIL / POST_GATE_NON_ACTIVATION；后两者 PASS | 找到了无证，没找到反证。 |
| 生成后实际改写仓外输入包；再重算其自身 content_hash | 不重算：包 schema 拒绝。重算：包单独过，但两次均与旧报告绑定的**字节摘要不符**；原报告的旧 verdict 不会自动改变 | 可以查出配对失效；正式重新消费、记 FailedCheck 和 FAIL 回执归 #1403，不能声称本 CLI 已实施该总验。[落盘试验](post-generation.json) |
| 规范不可读 / 上游 manifest 坏 JSON、不可规范化、形状不符 | 候选测试及复跑：按需出现 FILE_READ、JSON_PARSE、JCS_CANONICALIZE、SCHEMA；不制造占位引用 | 四步分类可用，部分派生与 BLOCKED 的例外见 6、7。 |

## JCS、命令及主线结果

- **RFC 8785**：[官方原文](https://www.rfc-editor.org/rfc/rfc8785)附录 B 的 26 行按给定 IEEE-754 位模式读入：24 个有限值逐字匹配，NaN 与 Infinity 拒绝。另测 §3.2.3 UTF-16 排序（CR、大小写、欧元、非 BMP、BMP 高码点）、控制字符、U+2028/U+2029 不多转义、合法代理对、孤立键/值、非法 UTF-8、转义后重键、`1e21/1e-7/-0/1.23000/1e400`。键序改变摘要不变，26 个非自身顶层字段逐一改动摘要都变；候选测试另外覆核嵌套字段。JSON 数字 `9007199254740993` 进入 binary64 后是 `9007199254740992`，是 JCS 舍入，不是任意精度整数协议。[独立向量](jcs-check.ts) · [结果](jcs.log)。
- **CLI**：[逐例 stdout、exit 与文件清单](cli-results.json)。缺清单/显式空路径 ⇒ MANIFEST_UNREADABLE；形状/票号/摘要格式不合法 ⇒ INVALID_MANIFEST；均 stdout BLOCKED、exit 1、目标目录为空。目标已有 summary.md ⇒ OUTPUT_WRITE_FAILED、exit 1，原字节未动、无新文件。附加 `--skip-checks` ⇒ 用法错误、exit 2、无文件，没有跳检参数。已登记摘要**数值**错与可恢复坏字符串的实际结果见 9、7。
- **main**：`git ls-remote origin refs/heads/main` 与本地 tracking ref 均为 `b9d898dccf46c2a716115eaa1215bc39c458a959`。候选驱动 `node --import tsx .sandcastle/at18-report.mts <review-wt> <作者最终delivery-manifest.json> <作者main-observations.json> <仓外新目录>`。得到 [FAIL 报告](cli/main/at18-report.json)、[输入包](cli/main/at18-input-bundle.json)、[摘要](cli/main/summary.md)。从 head 的 Git blob 独立逐序比较全部 938 个 ID，三组 97/345/496 及 crosswalk 字节摘要吻合。TB-02..10 各有单独 TB_NOT_CLOSED；实时核对的 10 张 OPEN TB 全部 gate=false（含 TB-11）；已关的 TB-01 也未凭票态自动过门；#1279 OPEN、disposition_valid=false。[详单](main-comparison.json)。**exit 0 只表示报告成功生成。**
- **票态时效**：作者冻结观察与审阅时查询的 TB 票态一致，但 TB-02 的 GitHub 子票已由 28 变 29，多出 OPEN 的讨论票 #2111；其余十个 TB 的子票清单、状态未变。[快照差异](ticket-snapshot-delta.json)。是否把讨论票列入“必需实施子片”要按已裁义务分类；这里既不自动计入，也不把旧冻结清单说成实时全量。它不改变这次 FAIL。
- **项目检查**：候选原目录 `npm ci --ignore-scripts`、`npm run typecheck`、`npx tsx --test .sandcastle/at18-report.test.ts`：安装/类型均退出 0，定向 **13/13**。[定向 TAP](targeted.log)。额外 tsc [正反类型用例](type-proof.ts) 成功。两次仓外隔离变异沿用同一套测试：[结果](mutation-results.txt)，删实体必需断言 12/13，删计数门 13/13。
- **CI 原命令**（[ci.yml:1401–1409](/Volumes/AgentStorage/review-1391-b22fd496/.github/workflows/ci.yml:1401)）：`npx tsx --test .sandcastle/*.test.ts .sandcastle/*.test.mts scripts/wayfinder_engine*.test.mts`。复用已运行的[基线原始 TAP](../sandcastle-ts-base.log)和[候选原始 TAP](../sandcastle-ts-head.log)，本次独立提取失败名/取消名并比对错误；没有重复跑全套。基线 849：817 过、17 败、10 取消、5 跳过；候选 862：851 过、6 败、0 取消、5 跳过。候选独有失败名 **0**；六个同名失败为 #1742 模型白名单、harvest PR 模式、真实容器默认关闭、classifyTicket、planReleases、renderStatus。**本地全套在两端都红；不是线上 CI 成功。** [两端完整失败集合](ci-comparison.json)。本次没有运行 cargo/rustc，未更改项目文件、票、PR 或远端。

## 给 #1551 / PR #2065 的意见

| 作者提出的六点 | 独立判断及建议 |
|---|---|
| 1. #1391/#1403 先后 | **有实际执行歧义，不是关票逻辑自相矛盾。** #1403 原生 blocked-by 有 #1391；两个票允许不消费前置的准备。ADR :36 要两实现先入 main，:37 才依次封包关票。应把“#1403 验证器代码可先进入 main”和“正式总验/关票须后于 #1391”写开，不撤销整条依赖。 |
| 2. 采集/证据判断协议 | **成立，而且已影响正确性。** ADR 已明确要实际 CI、最终产品非作者独审、逐子义务与真实行为；没规定通用 JSON 格式，不等于授权把 `CONFIRMED + 任一可读 ref` 作为证明。先复用已有 manifest 覆盖链、GitHub 与已定原件；对没有既有载体的判断，在 #1551 定义可信来源、定位键、射程与缺证语义。在此之前留红。不得悄悄给 /1 输出新增字段。 |
| 3. 三记录、权限原件、复算 | **一半是协议缺口，一半已有规定。** ADR 0036:25–33 已区分真实 Applied 与 TestOnly/Simulated；ADR 0062:41,58,82 已给启动记录、session_permission 来源栏与授权行。候选自行选择 `id/gate_reached_event_id/parameter_version_id` 的投影、独立的 URL 投影及几个时间戳，不能单凭投影宣布原件正确或持久互引成立。#1551 明定原件到投影如何绑定，以及 #1403 用什么稳定定位复核。 |
| 4. squash、CI、独评 | **对 CI/独评等价的疑问成立，对外部 ArtifactRef 的疑问不成立。** §五:62(b) 已完整规定外部 head 的 squash 路径，CLI 缺实现。对于普通 CI/独评，“任一祖先即可”与最终差异要求冲突；TB-11 的同 SHA 或可信 PR 映射也不能自行推广为全部涵盖。#1551 写清适用工作流、PR head、主线落点及纯报告尾部差异等价。 |
| 5. 固定值不可知 vs 缺规范 | **不是同一前提的两种结果。** §五:61 使缺必需 ref 时不出包；若另一份真规范仍给出完整、逐字同义务，报告可取得该固定值、继续写 FAIL。两份源都没有固定值时 §五:60(2) 不能写报告。若规范仍可读、只是某行缺失或两份规范冲突，是否允许切换来源及是否须保留失败应写明：本次只删除 coverage-input 一条 Destination、另一源有同义务，候选直接 PASS。生产是否启用未知也不应猜 false。另请分清已登记自身实体摘要异常、局部内容错误和“哪一种文档”被 BLOCKED。 |
| 6. 仓外绝对路径与迁移 | **有真实限制，不是 JCS 算法错误。** 只移动未被 JSON 引用的自身 manifest 与移动被引用的 input bundle/上游实体不是一回事。后一种变更了参与 JCS 的 path（也可能改变 manifest_sha256）；只改交付清单不会使旧绑定再次成立。现行 /1 应写明重建受影响的引用、报告、#1403 回执并重验；稳定逻辑身份若改变字段语义，须另行升版。 |

**下一步**：#1391 先让上述错 scope、旧 CI/独评、反向运行状态、旧票反处分都在真实 CLI 或等价受控输入下产生具名失败；#1551 明定确实缺失的采集/引导口径。验收时保留 `合法共享报告` 与 `确实只由 TB-11 前置销项` 两个正例。当前不能以候选、13/13 绿或 main 缺证演练关 #1391、#1369、#1340、#1323；#1279 保持原门。

VERDICT: BLOCK 未覆盖该子义务的原件及未审最终差异的旧 CI 仍能生成整图 PASS。
