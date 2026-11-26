# ADR 0035：成本停止 policy 实例、缺项状态与两层进阶证据门

**日期**：2026-10-14
**裁定人**：代理依用户 2026-10-13 授权裁定（分析：claude-fable-5-1；根逐条复核），走 #1354（G-029）
**状态**：已采纳。本 ADR 只定记录形状、输入来源门、读法、缺项状态与进阶判据形态；不代填费率、滑点、延迟、持有成本、θ 等实际政策数值。教义正本：`.chanlun/definitions/qujiantao.md` §4（成本门 `[旧缠论]` `035:30`，塔底 `[新缠论:选择]`，参数不入正本）。

## 背景
#907 后裁：ROUNDTRIP 配对；第一层由「延伸前算出上限」收窄为「当前 L0 余量 + 延伸后立即复测」；中位数与下尾读法给出相反结论的张力移交 #853，ADR 0022 裁定三已答「用置信下界」。RESIDUAL G-029：历史 BTC/1m、两重叠前缀窗、无置信区间、误差只有代理下界、未计持有成本，不能作当前证据。SPEC C04.4/C04.5、A-ST-037-01/02、A-FG-011-01。

## 裁定
### 一、记录形状与读法
`tower_base_ref` 的值域与 `zhongshu.md` §2.1.1 一致；当前 `L0 = segment`，机读记录为 `tower-base/1`（#1626）。`kline3`／`trade3` 只在相应真实构件与数据 profile 具备时可签，缺位时显式拒绝，不以线段输入冒充。

政策 id 族 `#1354/cost-stop-policy/v1`。记录 ⟨policy_id, version, profile_id, symbol, granularity, tower_base_ref, inputs{fee(Known, 费率簿引用含 source_url/retrieved_at/tier/role), slippage(Known|ProxyLowerBound|Missing), latency_error(同), holding(funding/borrow 引用 | Missing)}, amplitude{pairing=ROUNDTRIP, method_id, evidence_gate_version, per_level[{level, windows[]}], probe_run_ref}, threshold{form=ratio_lb_ge_theta, theta 整数对(用户签署), authorizer, authorized_at}, evidence_gate(继承 ADR 0022 裁定六/七), valid_through, supersedes⟩。新记录按 `evidence_gate_version` 读取冻结置信度，逐窗保存 ROUNDTRIP 波幅单边下界 `A_{ℓ,w}` 及样本和月块资格；级别层的 `lower_bound_95` 仅保留供历史记录兼容，不用于新读数或准入。

全 Known 且往返总成本 `C = 2·fee + slippage + latency_error [+ holding]` 为正时，同级各窗共用 `C`，证据门合格且各窗 `A_{ℓ,w}/C ≥ θ` 才通过。逐窗算法、余量摘要及其余求值状态见文末 #2121 修订。交易成本政策的 θ 仍由用户授权签署；普通研发方法和离线参数按 ADR 0041「授权来源与生效边界」由代理独审裁定，不冒充用户签名、不自动启用交易。系统拒绝 θ < 1（约束，非默认值）。全部定点整数。

ADR 0035 `amplitude.pairing` 保持单值 ROUNDTRIP，不恢复 AMP_EXEC。依据 [#907 resolution 评论5194145006](https://github.com/xy7365527-lang/NewChanlun/issues/907#issuecomment-5194145006) 的三步：成本每趟往返支付；与其可比的波幅是同一趟往返能吃到的幅度；相邻同向点不对应完整交易。标签 `[新缠论:推论]`，排除类别为「违已裁推论」，不以拟合好坏作选择理由。该评论的否证口逐字为：“若能论证「成本也可以按单边逐点计而不按往返计」，则 AMP_EXEC 回到候选。”逐字原件见 #907 该 resolution。若将来满足否证口，仍按现行裁定变更流程处理；后一句是流程要求，不冒称 #907 原话。

### 二、缺项是状态不是 0
任一输入 Missing ⟹ `AwaitingPolicy{cost_input}`，成本门 `NotEvaluable`；此时停止判据只剩塔底（阶段一塔底 = L0，现役塔不受影响），阶段二任何延伸不得开启。ProxyLowerBound 代入只得 `UpperBoundOnly`：可判失败，不可判通过。holding Missing 只影响持有时间长于 funding 周期的级别列，记录须写明起始级别。

### 三、第一层 = L0 余量对象 + 复测协议
`L0Margin{policy_version, evidence_gate_version, windows[{window_ref, qualification, ratio_bound}], lb_r, theta, status}`。逐窗结果与可缺省的 `lb_r` 摘要按文末 #2121 修订。复测协议：延伸前冻结版本与塔底；延伸后立即以同一探针血统测新级；求值结果以 [ADR 0044 §三](0044-cost-stop-policy-signed-instance-v1.md#三已知总成本为零的求值21112026-11-20) 为准，仅 `Enabled` 通过本成本门，方可继续逐级复测；未放行（含错误）则维持或回退至冻结的塔底，保留延伸记录。当前在案材料（#907）按本记录评估为 `InsufficientEvidence`（中位数、窗重叠、滑点代理、无区间），可作 probe_run_ref，不可作通过证据。

### 四、第二层判据与逐层逐窗证据（#1598）

> 2026-10-26 用户批准 #1598：本节将合法选择落为具名版本字段；未签数值与未标定能力不因方法批准自动生效。

`second_layer.rule`。可选值 = {`order_relation`（默认，出处：ADR 0035 裁定四:21，序关系判据，无需签数），`share_threshold{theta2}`（待标定，前置 S4-a/S4-b 修完）}。两值语义差异：(1) `order_relation` = 「主因已转为到底」⟺ `share_lb_95(reached_bottom) > share_ub_95(divergence_not_judged)` ∧ 证据门（ADR 0035:21），判据形式完全由读数区间序关系决定、不需用户签数值阈值；(2) `share_threshold{theta2}` = 「逐层、逐窗的已到底占比单边置信下界 ≥ θ₂」∧ 下述具名证据门，θ₂ 为签署门字段（默认 AwaitingPolicy{theta2}，推荐值进签署单；用于真实交易时取得用户授权后生效，普通研发选择按 ADR 0041 的代理裁定合同记来源），须在读数前预登记版本；引用已授权的#1677/evidence-gate/v1不要求重签，改六字段才另签v2。两值共同前置：S4-a/S4-b 修完（到底分类器与延伸实例证据收集）。代价：`share_threshold` 多签一个数（θ₂ 整数对）、多一次签署版本预登记流程。占比阈值为 ADR 0041 允许的选择，不再列入被否方案。

Q6 的既裁部分：引用 `#1677/evidence-gate/v1`（origin/main 的 ADR0022 修订§1–4、§6，原件见 ADR 0022），v1 六值为 confidence=95/100、block_unit=CalendarMonthUTC、min_events=30、min_blocks=12、min_windows=3、min_coverage=1/2。方法仍为时间块 bootstrap；下界用分布的 (1−confidence) 分位；固定规则为单边下界而非点估计、互不重叠窗口、每窗各自过线、不以合计替代。窗口表及版本早于 run_started_at 冻结，覆盖按预登记数据集首末 bar 时间区间计。v1已获授权，不能误写其缺用户重签；改六值须另签v2。

Q6 新增方法（用户 2026-10-26 已批准；θ₂ 数值仍待签）：`share_threshold` 的比较量为每个预登记分层、每窗 `reached_bottom` 占比的单边置信下界，非点估计。分层固定为 `(profile_id, symbol, granularity, base_ref, evaluated_level)`；不跨级/跨标的/跨profile合并。每层每窗的分母为该层该窗全部合格且已分类的下钻判定事件（由 classification_set 具名版本确定，每事件唯一计数），分子为其中 reached_bottom 事件。缺失/无法归类事件单列，存在此类事件时该层窗为 InsufficientEvidence，不静默剔除后过门。

具体算法：按所引 block_unit 将该窗事件分块，保留块内全部事件及依赖；从该窗 m 个非空块有放回抽 m 块，每次取合并事件的分子总数/分母总数，不平均各块比例。method_id=`descent-share/block-bootstrap/1`、resamples=10000、seed=0；PRNG固定PCG-XSH-RR 64/32（stream=1），块索引用拒绝取模避免偏差。以上算法标识/次数/随机种子和实现版本均在读数前记录；它们属于Q6已批准方法，不加入或改写evidence_gate六字段。每次重采样按抽样块计重复，得B个精确有理占比；升序排列，取第 ceil((1−confidence)×B) 项（1-based）为下界，不作插值。固定种子仅保证可复现，不替代区间有效性；在#1441实现时以独立定义oracle和同seed双跑检验方法。

每层每窗分别须 events≥min_events、非空块数≥min_blocks；每层所报窗口数≥min_windows，窗口互不重叠、合计时长覆盖≥min_coverage数据集区间。有效窗各自比较 `share_lb(reached_bottom) ≥ θ₂`，所有窗全过才给该层通过；所有被宣称通过的层逐层满足，不能以合计或其他层补偿。门不足为InsufficientEvidence，不是Fail；完整门成立但任一窗下界<θ₂为Fail。θ₂保持AwaitingPolicy，未签不运行share_threshold。默认 `order_relation` 及其已裁比较式不改；两规则共同前置S4-a/S4-b。2026-10-26 用户批准完整方法及政策形式、未签 θ₂，这是历史事实；后续普通研发授权适用 ADR 0041「授权来源与生效边界」，真实交易阈值硬门保留。

原记录 `DescentBottomEvidence{run_ref, classification_set(#852), per_class{count, share_lb_95, share_ub_95}, windows[], base_ref}` 保留；新增事件分母只用于 share_threshold，不改既有 `(重,S稳定点)` 操作统计。当前 S4-a/S4-b 证据仍未齐，阶段二不启用。

### 五、有效域与回放
绑定 (profile_id, symbol, granularity, fee tier, tower_base_ref)；AsKnown 按请求时刻生效版本，缺版本即 NotEvaluable 不回填；跨域 Unsupported 不回落旧数；TB-08 只把输入来源升为 Known，不碰 θ 与波幅证据；experiment 证据不得被 production profile 直接引用。

## 被否方案
用中位数点估计充波幅下界；θ 固定为 1；AMP_EXEC 配对；缺项代 0；代理下界充 Known；未签 theta2 即启用占比阈值；引用 #852 旧 d≥2=0 读数。

## 受影响代码清单
见 `.chanlun/review-results/issue1323-grilling-20261013/1354-AFFECTED-CODE.md`（基线 main 3da0b2c8）。

## 下游票
#1441 TB-02-S；#1382/#1400/#1412 TB-08；#1366 TB-07（回放版本）。

## 溯源标签
成本门语义 `[旧缠论]`（`035:30`、`060:42`）；ROUNDTRIP `[新缠论:推论]`（#907）；其余 `[新缠论:选择]`。

## #1598 批复与受影响清单

本次修订沿用的 ADR 旧行号以获批草稿固定基线 `13ed4d45c8ff85175819ca987690328ab2a247a4` 为准；当前条款按标题定位。

用户 2026-10-26 批复 [resolution](https://github.com/xy7365527-lang/NewChanlun/issues/1598#issuecomment-6403277308)。本次字段修订为 `[新缠论:选择]`，ROUNDTRIP 沿用已裁推论。受影响文件、固定基线与候选承接见 [清单](../../.chanlun/review-results/issue1598-policy-20261026/affected-code.md)；政策批准不代表下游已接单或实现。

## 修订：第一层 ROUNDTRIP 波幅下界（[#2121](https://github.com/Newchanlun/NewChanlun/issues/2121)，2026-11-20）

本节细化裁定一的逐窗波幅下界 `A_{ℓ,w}`，保留 ROUNDTRIP 并规定合格样本的端点不得复用，不改阈值、适用成本项或塔底。教义入口仍是 [区间套 §4.5.3](../../.chanlun/definitions/qujiantao.md)；本节不改裁定四的下钻占比方法。方法及默认值为 `[新缠论:选择]`，按 [ADR 0041](0041-degrees-of-freedom-configurable-not-excluded.md) 走 #1909 代理独审裁定，不是 `UserSigned`。

### 方法记录和输入

在既有成本停止记录的 `amplitude.method_id` 冻结每次求值所用方法；预登记窗表、读数原件与结果都绑定同一方法、证据门版本、数据集和原有效域。默认方法是 `roundtrip-amplitude/month-block-bootstrap-median/1`。这是普通研发方法记录的默认值，不是在读数缺失时填默认值：求值时缺项、未知或不匹配均为 `InsufficientEvidence(Amplitude)`。同一有效记录与本轮逐级复测只用一个方法，不能由 run 自选、比较后换值或按级别分派。

方法记录固定配对与端点资格、取价与归一基准、估计量、重采样次数、种子、PRNG／流、块索引规则、分位与定点规则，并记录版本、前版、独审出处、生效域和生效时点；run 另记实际实现版本。具名候选包括事件算术均值的月块 bootstrap（研究「每趟期望毛波幅」，对上尾敏感）、更多重采样次数（如 20,000，减少蒙特卡洛误差、成本近翻倍）和不同种子（研究蒙特卡洛敏感性）。它们保留为事前新版本的选项，不是本版可混用的取值或备用值；估计量候选先以独立研究核准目标、证据及授权再赋予可消费 id。下文 v1 参数来自方法记录，不能用运行时参数覆盖，也不能拿已登记的旧 id 表示新参数。

**每趟波幅以入场价归一。** 对一层一窗内合格、唯一、完整的 ROUNDTRIP 事件，`p_entry`、`p_exit` 分别取预登记数据集中入场信号和配对的出场信号各自确认 bar 的收盘价，使用同一标的、同一报价单位的精确值，不取结构端点价或成交价。两价都须是可由原件核验的有限正数。无论买入后卖出还是卖出后买入，原比例均为 `|p_exit − p_entry| / p_entry`；单趟波幅为 `floor(10^9 × |p_exit − p_entry| / p_entry)` ppb（比例一的十亿分之一），不先转浮点。例如入场 100、出场 110，波幅为 10%（`100000000 ppb`），不以 110 作分母。

**成本门只读级别比例。** 本版只消费来源合格、已表示为无量纲比例（如 bp、ppb）的适用级别成本项及代理下界。按 ADR 0044 §三，单边签署费率 `fee` 计两次，滑点、延迟误差和适用的持有成本用同一往返尺度的合格读数；对齐表示单位后合计。同次求值、同一有效域内，一个级别只解析一次成本，各窗共用该级的分母。绝对金额须先按事前冻结且获适用授权的具名政策版本，用该项单一正参考名义额及换算规则生成级别往返比例，再提交来源核验。缺少这项合同或只有裸金额时，返回 `NotEvaluable(UnavailableCost(该项))`；求值器不按各趟入场名义额或各窗换算。

成本公式仍是裁定一与 ADR 0044 §三的政策线性往返近似。`2·fee` 是政策层的双边费率近似；回测[开仓](../../rust/src/theta_v0/backtest/fill.rs#L251)和[平仓](../../rust/src/theta_v0/backtest/fill.rs#L208)则各按该腿实际成交名义额收费。等量、同费率时，以入场成交名义额归一的实际手续费比例为 `fee × (1 + 出场成交价／入场成交价)`。若将成本门改为逐腿名义额计费，须另行裁定并出新版本，不回写 ADR 0044 两份 v1 签署记录。

**先配对，再分窗。** [#907 探针](../../rust/src/bin/p907_cost_gate_level.rs#L339-L360) 为每个入场独立找首个同级反向确认信号，可能复用出场 bar；本版保留「首个反向确认」而不复用端点。按预登记全史区间、同一有效域和级别的确认信号原件，用数据集内的 bar 序号分组并升序扫描。每组只记该 bar 有哪些确认方向，同向多个信号不增加端点。起始无待配入场；此时只在有唯一方向的 bar 开始一趟，双向同时确认的 bar 不开新趟。已有待配入场时，取严格较晚、首个含反向确认的 bar 出场；该 bar 只作出场，从下一 bar 才能开始下一趟。同向确认不替换待配入场，末尾未出场不计。两端以原件中的数据集和 bar 序号核查；同一 bar 的不同信号身份不能绕过不复用规则。

两端都在同一预登记窗内才计入（窗端点 bar 均包含）；跨窗不计，不在窗边界重开扫描或截断补样本。跨月但同窗的完整往返只归入场 UTC 日历月。逐窗核验读数与上述原件重建的配对集合一致；报告复用端点、漏报、多报或无法核验身份与覆盖，以及应计事件任一端价格缺失、非有限、非正或无法核对，均使该窗波幅证据不足，不挑子集、不填零。按合格配对重计样本与非空月块；任一计数低于所引门版本的门槛即为 `InsufficientEvidence(Amplitude)`。例如 12 个月的 30 个入场若共用一个反向出场 bar，报告 30 对会因复用被拒；按本版重建，这些入场最多贡献 1 对和 1 个月块，不能凭这批事件满足 v1 的 30 对、12 块门槛。中位数、样本数、非空块数、最大月簇和逐窗下界均由登记原件推导。

`evidence_gate_version` 是具名门版本引用；新读数按 [ADR 0022 版本规则](0022-acceptance-criterion-parameters.md#4-版本规则) 在读数头以 `evidence_gate_ref` 携带同一引用，须与成本政策所引门版本一致。从该版本读取已冻结的 `confidence`、`block_unit` 和四项最低门槛。`per_level[].windows[]` 按预登记窗分别保存单边下界 `A_{ℓ,w}`（ppb）、中位数、样本数、非空月块数、最大月簇及样本和月块资格；各窗资格由原件推导。`#1677/evidence-gate/v1` 为单边 95/100、UTC 日历月、每窗 ≥30 个事件且 ≥12 个非空块、≥3 个互不重叠窗、合计时长覆盖预登记全史区间 ≥1/2。这里的 v1 方法支持 UTC 日历月，遇不支持的块单位不改走其他算法。最大月簇用最大块事件数／窗内事件数报告，不自创最大簇阈值；12 个非空月块也不证明跨月独立。

### 计算：每窗独立重采样

1. 按进场月升序排该窗的 `m` 个非空块，索引从 0 起。不计空月，月内所有事件共同入样。每次独立有放回抽 `m` 块；某块抽到几次，它的全部事件就计几次。不同月块样本数可以不同。对抽中块合并后的**全部事件**排序取中位数：奇数取中间项，偶数取中间两项的算术平均。每次中位数保留精确半 ppb，用整数分子 `t = 2 × 中位数` 表示；不平均各块中位数，不给每个月或每个事件另设权重。
2. 新裁配置：`B=10000`，`seed=0`，`PCG-XSH-RR 64/32`，`stream=1`；借裁定四的工程先例，不借其占比分子、分母或 id。为唯一可复算，取 PCG set-sequence 语义：状态 `s` 为无符号 64 位，`inc=(2×stream+1) mod 2^64`。一步取旧状态 `u=s`，更新 `s=(6364136223846793005×u+inc) mod 2^64`；输出把 `(((u >> 18) XOR u) >> 27) mod 2^32` 右循环移位 `u >> 59` 位（32 位，转 0 位即原值）。每窗从 `s=0` 起，先走一步并丢弃输出，加 `seed`（模 `2^64`），再走一步丢弃输出；正式抽样才取下一个输出。每窗重新按同种子初始化，不混入级别、窗口 ID 或并行顺序。
3. 抽块用拒绝取模：对于 `2 ≤ m ≤ 2^32`，算 `d=2^32 mod m`；若下一无符号 32 位输出 `u32<d`，丢弃并继续取下一个；否则取索引 `u32 mod m`。接受域长度是 `m` 的倍数。一次重采样结束后继续消耗同一窗的流，直到 `B` 次；不得用裸取模、跳过拒绝输出消耗或让线程调度改变抽样序列。
4. 若置信度为 `p/q`，把 `B` 个 `t` 升序排序，取 1-based 第 `ceil((q−p)×B/q)` 项；用精确整数求秩，不插值。`#1677/evidence-gate/v1` 的 `95/100` 与 `B=10000` 给第 **500** 项。选中后才算 `A_{ℓ,w}=floor(t/2)` ppb：向上或就近取整会让边界上的不足量抬到过线；向下最多损失半 ppb。中间整数用足够宽的类型并检查溢出，不饱和、不截断（PRNG 明定的模运算除外）；无法复算是证据不足。取的是**重采样中位数分布**的分位，不是原波幅样本的分位或窗内中位数点估计。

采用中位数置信下界是新裁，目标是「典型完整往返」的保守估计。#907 的报告以中位数描述典型量，并明确建议补中位数区间；直接用点估计仍排除。等月权统计换成了「典型月份」，总和或总价差／总入场价分别混入事件数或价格权重；不作当前事件口径的替代。区块最小值不估计所要求的 bootstrap 置信下界。固定种子与次数定义了可复算口径，不替代区间适用性或合格来源。

### 消费、换代与授权

按 [ADR 0044 §三](0044-cost-stop-policy-signed-instance-v1.md#三已知总成本为零的求值21112026-11-20)（#2111）的顺序求值：

1. **成本先行。** 只合计来源合格的适用级别成本比例及代理下界，取非负定点值；适用项 Missing 或无合格输入为不可评估，不代零。负签署值按非法记录拒收；负实测值或负代理下界报越界并返回 `NotEvaluable(UnavailableCost(该项))`。若仍得到负合计，显式报成本定义域错误并停止。
2. **先核证据门记录，再核读数。** 具名门记录缺失、字段缺失或非法、版本未获有效授权，均报 `PolicyError`。若调用上下文提供 `run_started_at`，先用该时点校验门版本的 `authorized_at < run_started_at`；否则先确认读数存在、属于本次运行、引用同一门版本并带有有效时点，再校验该授权时序。授权时序不满足也报 `PolicyError`，显式报错并停止，不出四态或验收读数。读数不合格（含上下文与读数时点不一致）则返回 `InsufficientEvidence(Amplitude)`。
3. **再核波幅证据。** 按已确认的 `run_started_at` 核验方法绑定及窗表是否事前冻结，再按 `evidence_gate_version` 核验全部预登记窗的样本和覆盖，以该版本的置信度重算各窗 `A_{ℓ,w}`。方法绑定、冻结时序或任一窗不合格，整级为 `InsufficientEvidence(Amplitude)`；不因其他窗有结果或成本为零而提前判定。不跨窗汇样、平均下界或以合计补窗，也不以历史级别字段 `lower_bound_95` 代替任何窗的下界。置信度只针对各窗的下界。

波幅证据全部合格后，才按成本类型与分母求值。`C` 为全 Known 时的级别往返总成本；含代理项时以其下界代入同一总成本公式得到 `C_min`。同级所有预登记窗共用这一个 `C` 或 `C_min`：

| 成本证据 | 逐窗判据与结果 |
|---|---|
| 全部适用项为 Known，`C > 0` | 各窗用同一 `θ` 比较 `A_{ℓ,w}/C ≥ θ`，全过为 `Enabled`，任一窗不过为 `Disabled(Measured)`。 |
| 全部适用项为 Known，`C = 0` | 不作比值比较；波幅下界为零或为正均返回 `NotEvaluable(ZeroTotalCost)`。 |
| 含代理下界，`C_min > 0` | `A_{ℓ,w}/C_min` 只是比值上界。任一窗上界严格小于 `θ` 则为 `Disabled(UpperBoundOnly)`，否则为 `InsufficientEvidence(UpperBoundOnly)`。 |
| 含代理下界，`C_min = 0` | 不证明实际总成本为零，也不作比值比较；返回 `InsufficientEvidence(UpperBoundOnly)`。 |

**余量对象保留逐窗结果。** `L0Margin` 将窗清单绑到本次 `evidence_gate_version`：每项以预登记窗为键，记资格（合格、不合格及原因，或未核验）和可缺省的 `ratio_bound`。波幅证据全部合格且进入数值比较时，逐窗记 `Lower(A_{ℓ,w}/C)` 或 `Upper(A_{ℓ,w}/C_min)`，不混用；未进入数值比较则为 `None`。若前置条件未过而尚未解析窗表，不生成虚构窗项。`PolicyError` 或成本定义域错误按 ADR 0044 §三中止，不出四态余量结果。

仅在全部预登记窗证据合格且全部适用成本项为 Known、`C > 0` 时，`lb_r = min_w (A_{ℓ,w}/C)`，以精确整数比值记录。此时 `lb_r ≥ θ` 等价于全窗过线（`Enabled`），`lb_r < θ` 等价于至少一窗不过线（`Disabled(Measured)`）。其余结果（`InsufficientEvidence(...)`、`NotEvaluable(...)` 含 `ZeroTotalCost`，以及任何含代理项的 `UpperBoundOnly`）一律 `lb_r = None`；代理上界或历史级别下界不能填入。该摘要不产生新的波幅下界、联合置信度或替代逐窗证据。

改配对与端点资格、取价与归一基准、估计量、抽样规则／参数、分位或定点语义，须出新方法 id、新具名绑定版本（记 `supersedes`）；改变六项证据门参数仍按 ADR 0022 另出门版本。方法绑定和证据门的生效时刻、窗表冻结时刻均须严格早于 `run_started_at`（该 run 首次读取评价数据）。只有实现版本变化且规范与可接受输入输出不变时可保留方法 id，须对拍逐位一致。旧下界不改签、不迁移；AsKnown 只能用请求时点实际有效的历史绑定回放。给新方法用旧数据，须按新冻结合同从可核验的原始样本另跑、另登记新证据；只有旧摘要、原件不兼容或新 run 缺失时判证据不足，不降回旧方法。#907 的旧报告仅作来源血统，不升级为通过证据。

θ 仍表示「合格的逐窗波幅置信下界相对往返成本的最小倍数」。本次首次给未指定的估计量定义普通研发方法，不改 ADR 0044 两份 v1 的任何签署值、范围或结果，两份仍因滑点 Missing 不可评估；不得回写签署记录或以新方法激活旧交易授权。同一个 θ 在不同估计量下可以对应不同通过集合。真实交易首次以本方法作准入、或改用另一方法改变既有真实阈值所针对的量时，须让用户在对应政策版本、方法及有效域上确认阈值授权；无对应授权照 ADR 0041 继续等待，不默认迁移。

### 下游实现触点（本裁定不改代码）

- [#1441](https://github.com/Newchanlun/NewChanlun/issues/1441) / PR #2126 候选 `c2806071dec8d0669f478cec4df093781f691232`：[`amplitude.rs:205–255`](https://github.com/Newchanlun/NewChanlun/blob/c2806071dec8d0669f478cec4df093781f691232/rust/src/theta_v0/cost_stop/amplitude.rs#L205-L279) 解析原件，须能重建全史配对、核验两端确认 bar 的收盘价并重算 ppb；`:257–279,342–364` 方法入口现只收扁平样本，须绑定预登记方法并保留分块与置信度；`:28–71,107–144` 为逐窗报告。候选 [`qualifications.rs:59–149`](https://github.com/Newchanlun/NewChanlun/blob/c2806071dec8d0669f478cec4df093781f691232/rust/src/theta_v0/evidence_gate/qualifications.rs#L59-L149) 为取窗和块的入口；未支持的有效域仍失败关闭。
- 同一候选 [`cost_stop.rs:217–253`](https://github.com/Newchanlun/NewChanlun/blob/c2806071dec8d0669f478cec4df093781f691232/rust/src/theta_v0/cost_stop.rs#L217-L253) 消费逐窗下界，[`zero_total.rs:4–12`](https://github.com/Newchanlun/NewChanlun/blob/c2806071dec8d0669f478cec4df093781f691232/rust/src/theta_v0/cost_stop/zero_total.rs#L4-L12) 保留 #2111 检查次序；[`cost_stop_public_surface.rs`](https://github.com/Newchanlun/NewChanlun/blob/c2806071dec8d0669f478cec4df093781f691232/rust/tests/cost_stop_public_surface.rs#L10-L43) 是公开面测试入口。源基线 `b9d898dccf46c2a716115eaa1215bc39c458a959` 的 `rust/src/bin/p907_cost_gate_level.rs:93–109,128–178,339–376` 仅作探针血统，合格原始事件和预登记原件归 #1441 的探针片生产。
