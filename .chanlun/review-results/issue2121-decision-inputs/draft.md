# #2121 · 成本停止的逐窗 ROUNDTRIP 波幅下界（送审稿）

## 问题

为 #1441 定义成本比值分子的同一条可复算方法：Q1 估计量；Q2 月块、次数、种子、PRNG 与抽块；Q3 分位和取整；Q4 方法识别、绑定与换代；Q5 逐窗或合并；Q6 对已签阈值、缺项与零成本的接口。保持 #1323 的 Destination、SPEC #1340 的成本停止与进阶验收，不改变缠论结构判断、交易阈值、场所或资金授权。`user_gate=[]`。

## 权威依据

1. `docs/chanlun/text/blog/035-第35课.md:30`【正文】：「级别越小，平均的买卖点间波幅也越小」。该段接着解释摩擦要相对波幅足够小，没给估计量、置信口径或 θ。`060-第60课.md:42`【正文】解释成本、通道和资金限制操作最低级别；不推出统计算法。教义正本 `.chanlun/definitions/qujiantao.md:427–441,459–468,532–536` 保留成本界和塔底，不把具体方法参数写进去。
2. ADR 0035 源基线 :14、:16、:19、:22、:41 与 [#1354 resolution](https://github.com/Newchanlun/NewChanlun/issues/1354#issuecomment-6153713798)：ROUNDTRIP 同趟配对、置信下界、月块、定点、输入与回放；明确 #907 旧材料不足。ADR 0035 :34 只钉 `descent-share/block-bootstrap/1`，只能作工程先例。`AMP_EXEC` 不回归，依据 [#907 resolution](https://github.com/Newchanlun/NewChanlun/issues/907#issuecomment-5194145006) 与 ADR 0035:16。
3. ADR 0022 :28–35、:47–64、:103–131、:149–171；[#853 resolution](https://github.com/Newchanlun/NewChanlun/issues/853#issuecomment-5289198250) 与 [#1441 等同声明](https://github.com/Newchanlun/NewChanlun/issues/1441#issuecomment-6326059290)：时间簇、预登记、样本门和逐窗口径；成本下降速率本身与波幅不是同一个量。ADR 0041 :9–30、:39–48 与 `docs/agents/doctrine-rules.md:43–55,61–77`：合法自由度事前版本化；无备用宽档，同输入各级同输出。
4. ADR 0044 :23、:32–41 与 [#1559 批复](https://github.com/Newchanlun/NewChanlun/issues/1559#issuecomment-6310844461)：两份 v1 签 2/1 与各自成本来源，未签估计量，滑点均 Missing；[已独审的 #2111 resolution](https://github.com/Newchanlun/NewChanlun/issues/2111#issuecomment-7043014665) 保留零总成本定义域及次序。
5. 在案探针作候选依据：`.chanlun/review-results/issue907-cost-gate-level-20260805.md:135–147,173–219,247–295`、`.chanlun/review-results/issue915-capacity-frequency-20260805.md:363,379,407` 与对应代码只证明历史点读法、归桶和研究缺口；不拿其旧读数或候选实装作可用波幅证据。

## 候选

- 对完整往返事件的中位数做月块 bootstrap，采用为默认：#907 以中位数读典型一趟，并明确提议补中位数区间；老报告的上尾使均值是中位数的 2.12–2.91 倍，不宜让典型往返被大幅个例支配。
- 事件均值的同类置信下界是保留的另版本选项，适合期望毛波幅目标，不与默认并行准入；两估计量没有固定宽严序。等月权统计、总和、带价格／量加权的总和比另有估计目标。原始样本分位、单点中位数、块最小值、独立抽样或交易成本变化速率不是本门要求的下界。
- B、seed、PCG、无偏索引及经验逆 CDF 借 ADR 0035:34 的工程形状分别新裁。保留可在具名新版本选择参数的路径，不从下钻占比直接继承有效性。正态、独立次序统计法及诊断输出均不兜底。完整逐项处置、替代方法与未决实证见 [候选表](candidates.md)。

## 裁定

正本落点：docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md

采用 `roundtrip-amplitude/month-block-bootstrap-median/1`；同层每个预登记合格窗按进场 UTC 日历月分块，双端同窗；从 m 个非空月块有放回抽 m 块，对合并的事件取中位数。默认 B=10000、seed=0、PCG-XSH-RR 64/32、stream=1；每窗同初态，确定性无偏拒绝取模。精确按所引门版本的尾概率取第 ceil 项、不插值；v1 第 500 项，最终向下取整到整数 ppb。[手算](example.md) 给两块秩／舍入及三窗的数值反例。Q1–Q4 的确切算法、参数与换代写入编辑合同；Q5 已裁逐窗，任一窗证据不足不能被其他窗替代。层级只选输入，不进方法参数。

预登记冻结一个适用 id；新方法、新参数、新版本不消费旧下界；可核原始样本方可重新登记重跑。AsKnown 仍按旧时点有效绑定，版本不匹配失败关闭。旧 v1 的 θ 含义、签值和 Missing 结果不变；本票不把某个真实阈值迁入新估计量，未来真实门须明确授权对应方法和域。Q6 沿 #2111：成本先验来源不齐不可评估；波幅证据不齐先报不足；全 Known 零和代理零随后分别报既裁状态；正分母照旧逐窗比较。只有 `Enabled` 通过，不新增结构否定。

本修订只落 ADR：区间套正本 :534 已将参数留在正本之外，且已有 ADR 0035 指针；不改其成本经济门、阶段二或塔底文字。ADR 0035 的「中位数读法」明确成「中位数点估计充下界」，区别于「用中位数构造置信界」。

## 验收清单

- 送审分支：`git diff-tree --no-commit-id --name-only -r HEAD` 只列 ADR 0035；`git diff --check HEAD^ HEAD` 退出 0。输入分支在本目录用 `python3 verify_example.py`，第 500 项及取整分别得到 (3, 1 ppb) 和 (5, 2 ppb)，三窗结果 [3,2,5]。编辑合同对源提交逐项唯一命中，并与送审 blob 字节相同。
- #1441 测试 `amplitude_bootstrap_matches_independent_weighted_order_oracle`：用手算和独立计数式对照完整抽样结果，锁 PCG 向量、拒绝取模边界、不等块样本数、重复块权重、偶中位数、秩及向下取整；新进程同种子双跑逐位吻合。
- #1441 测试 `amplitude_bootstrap_uses_entry_month_and_complete_windows`：同一窗跨 UTC 月的事件只进入进场月；跨窗事件不计；边界 bar 不重复、异名级别喂相同分块和合格输入时逐位相同。
- #1441 测试 `amplitude_all_windows_qualify_and_compare_separately`：用 [3,2,5]、C=1、θ=3 得 `Disabled(Measured)`；三窗全过（含等号）才为 `Enabled`；删第二窗的有效块致资格不足得 `InsufficientEvidence(Amplitude)`，不能过滤该窗重判。
- #1441 测试 `amplitude_version_never_uses_unpinned_or_legacy_evidence`：成本来源合格时，缺、未知、未登记或不匹配 method、换代时只有旧摘要，均输出 `InsufficientEvidence(Amplitude)`；具名历史回放还用历史版本。原 P0/P1 缺滑点仍不可评估；#2111 零分母测试原样锁次序。非测试入口只在已登记合格且来源／政策可用的实例中达到两种比较结果。

## 受影响票与 blocking 边变化

- #1441（TB-02-S）是唯一直接消费者，PR #2126 的精确行号见 ADR 修订「下游实现触点」。沿用 **#2121 → #1441**，本稿及推送不解锁。#2111 → #1441 保留至其原流程闭合；#1354、#1359 的闭合及 #1440 OPEN 状态按原图，不增删边。
- #1360 汇总原义务；#1443、#1444 保留对 #1441 的现有前置。#1366 TB-07 消费 AsKnown；#1367 TB-08 及 #1382／#1400／#1412 的成本来源、授权与运行域不变。#852、#1398、#1605 的统计目标和 #915/#917 的容量试验不改；不把替代估计量研究加作整图 blocker。

## 授权引用

本条依 #1909 代理独审裁定

分级 P，仅交普通研发方法起草候选。实际获审版本及非作者身份待主控登记；当前无本票独审结果。不标 `UserSigned`，不签实际 θ、成本、资金、量档、账号或权限；不发票面评论、不开 PR、不合入。

## 引用自证

| 来源 | 核对 | 结果 |
|---|---|---|
| `docs/chanlun/text/blog/035-第35课.md:30,38` | `nl -ba docs/chanlun/text/blog/035-第35课.md` | 摘句逐字，30 在正文界 38 前；行首非注，目视摘句没有行内注。 |
| `docs/chanlun/text/blog/060-第60课.md:42,60` | `nl -ba docs/chanlun/text/blog/060-第60课.md` | 42 在 60 前；原段属缠师正文、非行首注；只概述操作最低级与成本约束，不移引行内文字。 |
| 区间套 :427–441、:459–468、:532–536 | `nl -ba .chanlun/definitions/qujiantao.md` | 区分成本界／结构底，成本参数不入教义，第一层有同探针复测与 ADR 指针。 |
| ADR 0035 :14–22、:28–38、:41–44 | `nl -ba docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md`（源基线） | 第一层仅波幅读法；Q6 :34 的统计量是分子总数／分母总数的另一判断，方法不能冒称已裁。 |
| ADR 0022 :28–35、:47–64、:103–131、:149–171 | `nl -ba docs/adr/0022-acceptance-criterion-parameters.md` | 尾分位／月块、样本及逐窗、冻结与版本规则，§6 对接 A_ℓ。 |
| ADR 0041 :9–30、:39–48；教义纪律 :43–55、:61–77 | `nl -ba docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md`；`nl -ba docs/agents/doctrine-rules.md` | 版本化、禁备用值、历史与真实授权；#799/#804 的判断同一性。 |
| ADR 0044 :23、:32–41，#1559 批复、#2111 获审版 | `git show origin/decision/2111:docs/adr/0044-cost-stop-policy-signed-instance-v1.md`；查询 I1559、I2111 | 签署项、缺项、合格波幅前置及两种零的分流。 |
| #907、#853、#1354 的 resolution 与 #1441 等同声明 | 依 [search/commands.tsv](search/commands.tsv) 重跑 I907、I853、I1354、I1441 | 配对、置信而非点估计、逐窗以及第二层的边界可定位。 |
| #907/#915 的原件；#1441 设计和代码 | `git show <固定提交>:<文件>`；见 [考古](archaeology.md) 的提交与逐行位置 | 只有点统计、聚簇；候选方法失败关闭，不推导新权威。 |
| 主图／SPEC 与原生边 | I1323、I1340、I1360、I1366、I1367、E2121、E1441、E2111 | 源义务与实际边不变；不提前解除其他前置。 |

## 考古对照

| 点 | 归类 | 出处 | 草稿处置 |
|---|---|---|---|
| Q1 | B | #907 报告 :139–147、:294；#915 报告 :363、:407 | 中位数 bootstrap 下界默认；均值是不同 estimand，保留研究新版本。 |
| Q2 | B | ADR 0035 :14、:34；#907 代码 :128–146；#1441 设计 | 显式新裁完整往返归桶、固定重采样记录与无偏可复算细节。 |
| Q3 | B | ADR 0022 :30、:114；ADR 0035 :14、:34；#907 代码 :93–109 | 继承概率，选经验逆 CDF；定点向下，不移植点分位插值。 |
| Q4 | C decision | ADR 0022 §4、ADR 0041 裁定三，候选当前无 id | 用具名预登记绑定固定选择，换代重算原样本、旧证据仅历史回放。 |
| Q5 | A | ADR 0022 裁定七、ADR 0035 裁定一、#1441 等同声明 | 逐窗先有证据再全数过线。 |
| Q6 | A | ADR 0044 签署与 #2111 获审版；ADR 0041 授权节 | 旧签值与旧域不动；方法定义不外推真实阈值授权，零不比较。 |

```canonical_edit
{
  "version": 1,
  "operation": "edit",
  "path": "docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md",
  "replacements": [
    {
      "before": "不填费率、滑点、延迟、持有成本、θ 或任何数值。",
      "after": "不代填费率、滑点、延迟、持有成本、θ 等实际政策数值。"
    },
    {
      "before": "全部定点整数。\n\nADR 0035 `amplitude.pairing` 保持单值",
      "after": "全部定点整数。\n\n波幅下界的可复算算法、版本与证据消费，见文末 #2121 修订。\n\nADR 0035 `amplitude.pairing` 保持单值"
    },
    {
      "before": "中位数读法；θ 固定为 1；",
      "after": "用中位数点估计充波幅下界；θ 固定为 1；"
    },
    {
      "before": "用户 2026-10-26 批复 [resolution](https://github.com/xy7365527-lang/NewChanlun/issues/1598#issuecomment-6403277308)。本次字段修订为 `[新缠论:选择]`，ROUNDTRIP 沿用已裁推论。受影响文件、固定基线与候选承接见 [清单](../../.chanlun/review-results/issue1598-policy-20261026/affected-code.md)；政策批准不代表下游已接单或实现。\n",
      "after": "用户 2026-10-26 批复 [resolution](https://github.com/xy7365527-lang/NewChanlun/issues/1598#issuecomment-6403277308)。本次字段修订为 `[新缠论:选择]`，ROUNDTRIP 沿用已裁推论。受影响文件、固定基线与候选承接见 [清单](../../.chanlun/review-results/issue1598-policy-20261026/affected-code.md)；政策批准不代表下游已接单或实现。\n\n## 修订：第一层 ROUNDTRIP 波幅下界（[#2121](https://github.com/Newchanlun/NewChanlun/issues/2121)，2026-11-20）\n\n本节细化裁定一的 `A_ℓ`，不改配对、阈值、适用成本项或塔底。教义入口仍是 [区间套 §4.5.3](../../.chanlun/definitions/qujiantao.md)；本节不改裁定四的下钻占比方法。方法及默认值为 `[新缠论:选择]`，按 [ADR 0041](0041-degrees-of-freedom-configurable-not-excluded.md) 走 #1909 代理独审裁定，不是 `UserSigned`。\n\n### 方法记录和输入\n\n在既有成本停止记录的 `amplitude.method_id` 冻结每次求值所用方法；预登记窗表、读数原件与结果都绑定同一方法、证据门版本、数据集和原有效域。默认方法是 `roundtrip-amplitude/month-block-bootstrap-median/1`。这是普通研发方法记录的默认值，不是在读数缺失时填默认值：求值时缺项、未知或不匹配均为 `InsufficientEvidence(Amplitude)`。同一有效记录与本轮逐级复测只用一个方法，不能由 run 自选、比较后换值或按级别分派。\n\n方法记录固定其估计量、重采样次数、种子、PRNG／流、块索引规则、分位与定点规则，并记录版本、前版、独审出处、生效域和生效时点；run 另记实际实现版本。具名候选包括事件算术均值的月块 bootstrap（研究「每趟期望毛波幅」，对上尾敏感）、更多重采样次数（如 20,000，减少蒙特卡洛误差、成本近翻倍）和不同种子（研究蒙特卡洛敏感性）。它们保留为事前新版本的选项，不是本版可混用的取值或备用值；估计量候选先以独立研究核准目标、证据及授权再赋予可消费 id。下文 v1 参数来自方法记录，不能用运行时参数覆盖，也不能拿已登记的旧 id 表示新参数。\n\n输入是一层一窗内，同一有效域的合格、唯一、完整 ROUNDTRIP 往返事件及非负整数波幅（ppb，比例一的十亿分之一）。由精确原比例生成 ppb 时向下取整，禁止先走浮点近似；记录中位数、原样本数、非空块数、最大月簇和逐窗下界，由登记原件推导，不把自报摘要当条件。入、出场均须在预登记窗内（端点 bar 都计入）；跨月但同窗的完整往返归进场 UTC 日历月，不切开、不重复；跨窗往返不计入任何窗，不把截断段补成样本。样本有缺损或身份、值、覆盖无法按证据合同核实，不视为零幅或合格缺席。\n\n依 [ADR 0022 记录化 §6](0022-acceptance-criterion-parameters.md#6-与-cost-stop-记录对接) 从所引门版本读 confidence、block_unit 和四项最低门槛。`#1677/evidence-gate/v1` 为单边 95/100、UTC 日历月、每窗 ≥30 个事件且 ≥12 个非空块、≥3 个互不重叠窗、合计时长覆盖预登记全史区间 ≥1/2；各窗资格由原件推导。这里的 v1 方法支持 UTC 日历月，遇不支持的块单位不改走其他算法。最大月簇用最大块事件数／窗内事件数报告，不自创最大簇阈值；12 个非空月块也不证明跨月独立。\n\n### 计算：每窗独立重采样\n\n1. 按进场月升序排该窗的 `m` 个非空块，索引从 0 起。不计空月，月内所有事件共同入样。每次独立有放回抽 `m` 块；某块抽到几次，它的全部事件就计几次。不同月块样本数可以不同。对抽中块合并后的**全部事件**排序取中位数：奇数取中间项，偶数取中间两项的算术平均。每次中位数保留精确半 ppb，用整数分子 `t = 2 × 中位数` 表示；不平均各块中位数，不给每个月或每个事件另设权重。\n2. 新裁配置：`B=10000`，`seed=0`，`PCG-XSH-RR 64/32`，`stream=1`；借裁定四的工程先例，不借其占比分子、分母或 id。为唯一可复算，取 PCG set-sequence 语义：状态 `s` 为无符号 64 位，`inc=(2×stream+1) mod 2^64`。一步取旧状态 `u=s`，更新 `s=(6364136223846793005×u+inc) mod 2^64`；输出把 `(((u >> 18) XOR u) >> 27) mod 2^32` 右循环移位 `u >> 59` 位（32 位，转 0 位即原值）。每窗从 `s=0` 起，先走一步并丢弃输出，加 `seed`（模 `2^64`），再走一步丢弃输出；正式抽样才取下一个输出。每窗重新按同种子初始化，不混入级别、窗口 ID 或并行顺序。\n3. 抽块用拒绝取模：对于 `2 ≤ m ≤ 2^32`，算 `d=2^32 mod m`；若下一无符号 32 位输出 `u32<d`，丢弃并继续取下一个；否则取索引 `u32 mod m`。接受域长度是 `m` 的倍数。一次重采样结束后继续消耗同一窗的流，直到 `B` 次；不得用裸取模、跳过拒绝输出消耗或让线程调度改变抽样序列。\n4. 若置信度为 `p/q`，把 `B` 个 `t` 升序排序，取 1-based 第 `ceil((q−p)×B/q)` 项；用精确整数求秩，不插值。v1 的 `95/100` 与 `B=10000` 给第 **500** 项。选中后才算 `A_{ℓ,w}=floor(t/2)` ppb：向上或就近取整会让边界上的不足量抬到过线；向下最多损失半 ppb。中间整数用足够宽的类型并检查溢出，不饱和、不截断（PRNG 明定的模运算除外）；无法复算是证据不足。这里的 5% 是**重采样中位数分布**的分位，不是原波幅样本的 p5，也不是窗内中位数点估计。\n\n采用中位数置信下界是新裁，目标是「典型完整往返」的保守估计。#907 的报告以中位数描述典型量，并明确建议补中位数区间；直接用点估计仍排除。等月权统计换成了「典型月份」，总和或总价差／总入场价分别混入事件数或价格权重；不作当前事件口径的替代。区块最小值不估计所要求的 bootstrap 置信下界。固定种子与次数定义了可复算口径，不替代区间适用性或合格来源。\n\n### 消费、换代与授权\n\n先核成本来源，再核全部预登记窗的资格并重算各窗 `A_{ℓ,w}`。任一窗不足，整级为 `InsufficientEvidence(Amplitude)`，即使另有窗过线或不过线。全部合格、Known 总成本为正时，各窗分别用同一 `θ` 判 `A_{ℓ,w}/C ≥ θ`，全过才 `Enabled`，任一不过为 `Disabled(Measured)`；不跨窗汇样、平均下界或以合计补窗。置信度是每窗的口径，全窗过线不是一条联合置信度声明。代理成本下界为正时仍只能证明失败。`C=0` 不比较；兼容 #2111 ADR 0044 §三：波幅合格之后，Known 零总成本为 `NotEvaluable(ZeroTotalCost)`，代理下界合计为零为 `InsufficientEvidence(UpperBoundOnly)`。各状态按原四态记录，不当作结构性否定。\n\n改估计量、抽样规则／参数、分位或定点语义，须出新方法 id、新具名绑定版本（记 `supersedes`）；改变六项证据门参数仍按 ADR 0022 另出门版本。方法绑定和证据门的生效时刻、窗表冻结时刻均须严格早于 `run_started_at`（该 run 首次读取评价数据）。只有实现版本变化且规范与可接受输入输出不变时可保留方法 id，须对拍逐位一致。旧下界不改签、不迁移；AsKnown 只能用请求时点实际有效的历史绑定回放。给新方法用旧数据，须按新冻结合同从可核验的原始样本另跑、另登记新证据；只有旧摘要、原件不兼容或新 run 缺失时判证据不足，不降回旧方法。#907 的旧报告仅作来源血统，不升级为通过证据。\n\nθ 仍表示「合格的逐窗波幅置信下界相对往返成本的最小倍数」。本次首次给未指定的估计量定义普通研发方法，不改 ADR 0044 两份 v1 的任何签署值、范围或结果，两份仍因滑点 Missing 不可评估；不得回写签署记录或以新方法激活旧交易授权。同一个 θ 在不同估计量下可以对应不同通过集合。真实交易首次以本方法作准入、或改用另一方法改变既有真实阈值所针对的量时，须让用户在对应政策版本、方法及有效域上确认阈值授权；无对应授权照 ADR 0041 继续等待，不默认迁移。\n\n### 下游实现触点（本裁定不改代码）\n\n- [#1441](https://github.com/Newchanlun/NewChanlun/issues/1441) / PR #2126 候选 `c2806071dec8d0669f478cec4df093781f691232`：[`amplitude.rs:205–255`](https://github.com/Newchanlun/NewChanlun/blob/c2806071dec8d0669f478cec4df093781f691232/rust/src/theta_v0/cost_stop/amplitude.rs#L205-L279) 解析原件，`:257–279,342–364` 方法入口现只收扁平样本，须绑定预登记方法并保留分块与置信度；`:28–71,107–144` 为逐窗报告。候选 [`qualifications.rs:59–149`](https://github.com/Newchanlun/NewChanlun/blob/c2806071dec8d0669f478cec4df093781f691232/rust/src/theta_v0/evidence_gate/qualifications.rs#L59-L149) 为取窗和块的入口；未支持的有效域仍失败关闭。\n- 同一候选 [`cost_stop.rs:217–253`](https://github.com/Newchanlun/NewChanlun/blob/c2806071dec8d0669f478cec4df093781f691232/rust/src/theta_v0/cost_stop.rs#L217-L253) 消费逐窗下界，[`zero_total.rs:4–12`](https://github.com/Newchanlun/NewChanlun/blob/c2806071dec8d0669f478cec4df093781f691232/rust/src/theta_v0/cost_stop/zero_total.rs#L4-L12) 保留 #2111 检查次序；[`cost_stop_public_surface.rs`](https://github.com/Newchanlun/NewChanlun/blob/c2806071dec8d0669f478cec4df093781f691232/rust/tests/cost_stop_public_surface.rs#L10-L43) 是公开面测试入口。源基线 `b9d898dccf46c2a716115eaa1215bc39c458a959` 的 `rust/src/bin/p907_cost_gate_level.rs:93–109,128–178,339–376` 仅作探针血统，合格原始事件和预登记原件归 #1441 的探针片生产。\n"
    }
  ]
}
```
