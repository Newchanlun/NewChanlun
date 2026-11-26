# ADR 0044：成本停止 policy 签署记录 v1（P0 / P1-hl-testnet）

> 正本：本文件是 `#1354/cost-stop-policy/v1` 在 `P0` 与 `P1-hl-testnet` 两个 profile 上的签署值（θ 与四项成本输入的状态、来源与有效域）的正本。
> 最后裁定：#2111（2026-11-20，P 类方法修订，依 #1909 代理独审裁定，非 UserSigned；获审版本及独审原件由主控在 PASS 后登记）；P0／P1-hl-testnet 的签署值沿用 #1559（2026-10-21，用户批复）。
> 受影响代码清单：见「下游与受影响票」节（#2111 候选行号及基线；实现归 #1441）。

**日期**：2026-10-21
**裁定人**：用户（2026-10-21 批复 [#1559 评论 6310844461](https://github.com/xy7365527-lang/NewChanlun/issues/1559#issuecomment-6310844461)，原话「不重要你自己定吧」，委托主控按推荐默认值逐项确认）；代理起草，非作者独审
**状态**：已采纳（待 PR 合入）。签署单、考古与独审：`/Volumes/AgentStorage/decisions/1559/{draft.md,archaeology.md,review.attempt3.json}`；落地独审 `.chanlun/review-results/pbatch-land-20261021/`。

## 背景

[ADR 0035](0035-cost-stop-policy-instance-and-base-extension-evidence.md) 定了成本停止 policy 的记录形状、读法、缺项状态与有效域（`:12`/`:15`/`:24`），θ 与四项输入的值留给用户签。签署前系统恒为 `AwaitingPolicy{cost_input}`、成本门 `NotEvaluable`、停止判据只剩塔底 L0（ADR 0035:15）。本 ADR 是第一份签署记录。

教义依据：`035-第35课.md:30`【正文】「那些太小的级别，不足以让交易成本、交易误差等相对买卖点间波幅足够小，这样的操作，从长期的角度看，是没有意义的」——原文只给方向「足够小」，不给数；`.chanlun/definitions/qujiantao.md:467`「参数（费率、滑点、延迟、该级平均波幅）按场所与执行系统给，不入正本」，`:519`「终止 ＝ 成本门 ∧ 塔底；塔底 ＝ 现有 L0（线段层）」。

## 裁定

### 一、签署值与出处

| 项 | 签署值 | 出处与推理链 |
|---|---|---|
| θ | 两版均 `2/1`（下界比值至少是往返总成本的 2 倍才允许往该级延伸） | 1 是存在论下界、余量归部署层（`rust/src/trading/axiom_voice.rs:69-70`；ADR 0035:12 拒收 θ < 1；ADR 0035:27 否「θ 固定为 1」）。本仓在册的部署余量全部是 2：`theta_cost_k = 2.0`（`rust/src/trading/config.rs:668`，断言 `:1677-1680`「门槛常数沿用在册预注册值」）、`sub_cost_k = 2.0`（`:692`）。只继承倍数，不继承旧门的中位数读法（ADR 0035:27 已否）与 10 bps 常数分母。继承倍数是 `[新缠论:选择]`；同一个 2 在新读法下更严（95% 下界对四项实测成本） |
| P0 费率 | `Known`；BINANCE_SPOT、VIP0、taker、10 bps/side（定点 `1/1000`） | `analysis/data_cache/venue_fee_binance_spot_20260726.json:3-13`（含 `.sha256`）；同域费率簿仅此一份；VIP0 在两档中取较高费率、方向保守（`[新缠论:选择]`）；role 取 taker：`rust/src/theta_v0/venue_fee.rs:41`/`:112` 生产恒 Taker |
| P1 费率 | `Known`；Hyperliquid 主 DEX 永续、Tier 0 Base rate、taker、0.045%（定点 `45/100000`） | 官方页 `https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees`（抓取 2026-10-20T02:42:29Z，快照 sha256 `75e55504b1b887a89e1668a9544d09b013242747bcc29f8648a5410142a71258`）Perps Tier 0 表；新账户 14 日量为 0 ⟹ Tier 0；无 HYPE 质押与推荐码 ⟹ Base rate；官方页明写加密永续不适用 growth mode。官方页不单列 testnet 费率，按同表是 `[新缠论:选择]`；TB-08 回报 fee 字段与本值不一致即出新版本 |
| 滑点 | 两版 `Missing` | 仓内无逐笔滑点落盘（`.chanlun/review-results/issue907-cost-gate-level-20260805.md:282`）；`rust/src/theta_v0/venue_fee.rs:36` 明文 `slippage_bps` 未标定（字段 `rust/src/theta_v0/config.rs:309`，默认 `:366` 为 2.0），不作输入（ADR 0035:27 否「代理下界充 Known」「缺项代 0」） |
| 延迟误差 | P0 `ProxyLowerBound`（只能判失败）；P1 `Missing` | P0：#907 报告 `:104` DELAYERR「是真实交易误差的下界」、`:161-169` 逐级表，测量域（Binance 现货 BTC 1m）与 P0 一致；ADR 0035:18 允许作 probe_run_ref。P1 跨域不得借（ADR 0035:24） |
| 持有成本 | P0 `Missing`（起始级别 L0）；P1 `Missing`（起始级别 L0），指定来源 = Hyperliquid 官方 funding 规则 + BTC 逐小时 funding 历史序列 | P1：官方 funding 页 `https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding`（抓取同上，快照 sha256 `126d1a0489517bad351787542d555a0de25339c69fd544a0d8d283ae172d234c`）每小时结算；L0 往返中位持有 553 根 1m（#907 报告 `:239`）> 1 h；funding 按整条序列计（[#62 评论 5029790605](https://github.com/xy7365527-lang/NewChanlun/issues/62#issuecomment-5029790605)）。序列按 #62 datum 格式落盘（带 sha256）后出 v2 升为 `Known`；落盘前照实为 `Missing`。P0：现货无 funding 周期，借币利率无在册来源（#62：需认证端点）；起始级别取最保守的 L0 是 `[新缠论:选择]` |
| 标的 / 粒度 | 两版 BTC / `1m` | 已签正本 [ADR 0040](0040-funding-signature-and-chong-derivation.md):39（symbol BTC）；Binance 簿 `analysis/data_cache/venue_fee_provenance.md:48` 为 BTC 现货 1m；P1 标的 = BTC（[#1283 评论 5465238861](https://github.com/xy7365527-lang/NewChanlun/issues/1283#issuecomment-5465238861)） |
| 有效期 | 签署日 + 365 天 | 已签正本 ADR 0040:45（有效期签署日 + 365 天）同批对齐 |

后果照实：两版滑点均为 `Missing`，成本门 `NotEvaluable`，阶段二不开，L0 照常（ADR 0035:15）。θ 要等 TB-08 把 P1 的滑点、延迟、持有成本升为 `Known` 后才第一次参与判定。

### 二、记录与读法

1. 两版互不引用（ADR 0035:24 跨域 Unsupported）；P2 不在本记录（#1561 已批不做 P2 真钱首发，见 [ADR 0028](0028-first-capability-verification-profile.md)「P2 处置」）。
2. #907 材料只作 `probe_run_ref`（ADR 0035:18 = `InsufficientEvidence`）；θ 不得由 2.59× 反推（`CONTEXT.md` 成本停止 policy 词条 _Avoid_）。
3. 签署记录沿用 ADR 0035 的输入规则：Missing 不代 0、Proxy 不充 Known、θ < 1 拒收；不新增第二套判据或兜底。
4. TB-08 升级任一输入来源即出新版本（`supersedes` 指向旧版），不改 θ 与波幅证据（ADR 0035:24）。
5. 波幅证据（`amplitude`）由探针按 ADR 0035:12 产出，不由签署填写；本记录不含波幅数值。
6. TB-02-S [#1441](https://github.com/xy7365527-lang/NewChanlun/issues/1441) 读取当前生效版本；求值结果为 Enabled / Disabled / InsufficientEvidence / NotEvaluable 之一，契约错误另行报告（见 §三）；机读文件路径与格式归 #1441 实施，本 ADR 是唯一数值来源。

### 三、已知总成本为零的求值（[#2111](https://github.com/Newchanlun/NewChanlun/issues/2111)，2026-11-20）

**先解析成本。** 记 `C = 2·fee + slippage + latency_error [+ holding]`，与 [ADR 0035](0035-cost-stop-policy-instance-and-base-extension-evidence.md) 裁定一同尺度、同往返口径；含代理项时，以其下界代入得到 `C_min`。按请求时刻的有效记录、有效域、级别及来源解析，只合计适用项；未到生效级别的 holding 不适用。适用项 Missing 或无合格输入仍按 §二与 ADR 0035 裁定二处理为不可评估，不用 0 占位。获授权的已知零值与匹配已登记 Known 来源的运行实测零值，在各自来源门通过后同为 0；来源及有效域各自保留。零费率可进入合法记录，不代表其余成本为零；运行读数不得覆盖已签值或将 Missing、代理下界改成 Known。

**各适用成本项及代理下界只接受非负定点值。** P1 的资金费在完整持有区间按仓位方向计提并汇总净额（`funding_accrual_signed`：正为付费，负为收入）。来源合格且净额非负，才可换算到同一往返成本尺度作为 holding。净收入在账务上仍为收入，即使其他成本足以抵销它，也不得作为负的 holding 入门；不得逐期丢弃收入、取绝对值或截零。

负的签署值按非法记录拒收；负的实测值或代理下界按该项无合格输入返回 `NotEvaluable(UnavailableCost(该项))`（持有项为 `Holding`），并报告负值越界。合格输入不会得到 `C < 0` 或 `C_min < 0`；若仍得到负合计，显式报成本定义域错误并停止，不进入求值表。

**成本输入可用后，依序校验证据门与 ROUNDTRIP 波幅证据。** 依据 [ADR 0022](0022-acceptance-criterion-parameters.md)「版本规则」「缺失语义」及裁定六／七：

1. **门记录本身。** 成本政策引用的具名门记录缺失、字段缺失或非法（含越界），或该版本本身未获有效授权，均报 `PolicyError`。
2. **本次运行的时点。** `run_started_at` 是本次运行首次读取评价数据的时点。调用上下文给出该时点时，直接据此校验 `authorized_at < run_started_at`，不满足则报 `PolicyError`。读数必须存在、属于本次运行、引用同一具名门版本，并自带有效的 `run_started_at`；上下文已给出时点时，两处时点须一致。任一条件不满足，返回 `InsufficientEvidence(Amplitude)`。仅由读数提供时点时，先确认读数满足上述条件，再用其时点校验 `authorized_at < run_started_at`，不满足同样报 `PolicyError`。
3. **窗口与样本。** 以已确认的 `run_started_at` 校验 `prereg_frozen_at < run_started_at`，再按所引门版本核验预登记窗口、样本与覆盖。任一条件不满足，返回 `InsufficientEvidence(Amplitude)`。

遇 `PolicyError` 须显式报错并停止，不出四态或验收读数，不回退常数或其他版本。无论已知总成本 `C` 为正还是为零，波幅证据合格后才查下表：

| 成本证据 | 合格波幅下界的读法 | 输出 |
|---|---|---|
| 所有适用成本项为 Known，`C > 0` | 逐窗比较 `A_ℓ/C ≥ θ` | 全过为 `Enabled`；任一窗不过为 `Disabled(Measured)` |
| 所有适用成本项为 Known，`C = 0` | 比值无定义，不做 θ 数值比较 | `NotEvaluable(ZeroTotalCost)`；合格下界为 0 或为正均如此 |
| 含 ProxyLowerBound，合成下界 `C_min > 0` | `A_ℓ/C_min` 只给比值上界 | 任一窗口上界严格小于 θ 为 `Disabled(UpperBoundOnly)`；否则 `InsufficientEvidence(UpperBoundOnly)` |
| 含 ProxyLowerBound，合成下界 `C_min = 0` | 未证明实际总成本为 0，也不能据该下界作上界的 θ 比较 | `InsufficientEvidence(UpperBoundOnly)` |

`Disabled` 表示证据已证明门槛不满足，不表示比值无定义。此门没有独立的绝对波幅最低值；正成本比较上的不过线仍为 `Disabled`，零总成本时不得用交叉相乘的等价式越出正分母定义域，也不填极限值、最小分母或备用判据。

**进阶复测：求值结果与塔底动作分开。** 按 [ADR 0035 裁定三](0035-cost-stop-policy-instance-and-base-extension-evidence.md#三第一层--l0-余量对象--复测协议)，延伸前冻结政策版本和生效塔底，试延伸后立即以同一探针血统复测新级。

- `Enabled`：通过本次复测的成本门；其余进阶条件仍按 ADR 0035 执行。
- `Disabled(...)`、`InsufficientEvidence(...)`、`NotEvaluable(...)`：均不放行本级进阶，原样返回各自状态及原因。后两态不得改写为 `Disabled`。
- `PolicyError` 或负合计成本定义域错误（`C < 0` 或 `C_min < 0`）：均不放行。按 ADR 0022 的停止语义，显式报错并中止本次进阶复测，不再逐级推进，不产出四态或验收读数。

所有未放行路径（含错误）在返回状态或传播错误前，均须维持复测前冻结的生效塔底；试延伸若已临时切换塔底，先回退至该塔底。不得提交新塔底，须保留既有及本次已形成的延伸记录。

上述输入域、零分母处置和证据先决关系在各级和各有效 profile 使用同一规则（#804）。将净额口径做成 v1 的开关，会让同一成本门对同一笔负 holding 在「拒收」和「准许抵扣」两套准入判据间选择，而不是为同一判据选参数；即使事前单选也不符合 [ADR 0041](0041-degrees-of-freedom-configurable-not-excluded.md) 裁定二、四（#799）。净额保留为独立方法候选；若采用，须另行裁定并在具名新版本中事前冻结输入域、非正分母和代理下界的处置，按新口径重新推导，不作 v1 的失败兜底。

继续按已授权版本读取 θ 与成本来源，变动成本值或来源仍须按原合同另出版本。P0、P1-hl-testnet 两份 v1 签署值、来源与有效域不变；两版滑点仍为 Missing，按原合同输出 `NotEvaluable`。本条只定求值方法，不签任何实际取值。

## 签署记录

### P0（确定性回放）

```cost-stop-record
policy_id: #1354/cost-stop-policy/v1
profile_id: P0
version: v1
supersedes: none
symbol: BTC
granularity: 1m
tower_base_ref: L0 = segment（qujiantao.md:519 塔底；ADR 0035:15；机读 `tower-base/1`，#1626）
fee: Known  ref: analysis/data_cache/venue_fee_binance_spot_20260726.json  source_url: https://www.binance.com/en/fee/trading  retrieved_at: 2026-07-26  tier: VIP0  role: taker  rate: 1/1000
slippage: Missing
latency_error: ProxyLowerBound  probe_run_ref: .chanlun/review-results/issue907-cost-gate-level-20260805.md:161-169（DELAYERR，只能判失败）
holding: Missing  start_level: L0
theta: 2/1
evidence_gate: ADR 0022 裁定六/七
gate_status: AwaitingPolicy{cost_input} / NotEvaluable
authorizer: 用户（#1559 2026-10-21 批复）
authorized_at: 2026-10-21
valid_through: 2027-10-21
```

### P1-hl-testnet（能力验证）

```cost-stop-record
policy_id: #1354/cost-stop-policy/v1
profile_id: P1-hl-testnet
version: v1
supersedes: none
symbol: BTC
granularity: 1m
tower_base_ref: L0 = segment（qujiantao.md:519 塔底；ADR 0035:15；机读 `tower-base/1`，#1626）
fee: Known  source_url: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees  retrieved_at: 2026-10-20  tier: Tier 0 Base rate  role: taker  rate: 45/100000
slippage: Missing
latency_error: Missing
holding: Missing  start_level: L0  designated_source: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding（BTC 逐小时 funding 序列，落盘后升 Known）
theta: 2/1
evidence_gate: ADR 0022 裁定六/七
gate_status: AwaitingPolicy{cost_input} / NotEvaluable
authorizer: 用户（#1559 2026-10-21 批复）
authorized_at: 2026-10-21
valid_through: 2027-10-21
```

## 被否方案

- **θ 取 1**：ADR 0035:27 已否「θ 固定为 1」；1 是下界不是默认值（#1354 resolution 6153713798）。
- **连同旧引擎的中位数读法与 10 bps 常数分母一起继承 k = 2**：ADR 0035:27 已否中位数读法；新分母由四项输入构成（ADR 0035:12）。
- **拿 #907 的 2.59× 反推 θ**：ADR 0035:18 判 #907 为 `InsufficientEvidence`。
- **P1 费率取推论层的「growth mode 0.45–0.9 bp」**：[#853 评论 5224634834](https://github.com/xy7365527-lang/NewChanlun/issues/853#issuecomment-5224634834) 自陈无落盘；官方页明写加密永续不适用 growth mode。
- **滑点用未标定常数凑数**：`venue_fee.rs:36`、`venue_fee_provenance.md:46` 明文未标定。
- **P0 借用 P1 的 Hyperliquid 费率或 funding（或反之）**：ADR 0035:24 跨域 Unsupported。

## 下游与受影响票

- [#1360](https://github.com/xy7365527-lang/NewChanlun/issues/1360) TB-02、[#1366](https://github.com/xy7365527-lang/NewChanlun/issues/1366) TB-07、[#1367](https://github.com/xy7365527-lang/NewChanlun/issues/1367) TB-08：#1559 关票后 blocking 边解除；#1366 回放按「请求时刻生效版本」引本 ADR；#1367 升级 P1 滑点/延迟/funding 来源即出新版本。
- [#1441](https://github.com/xy7365527-lang/NewChanlun/issues/1441) TB-02-S：按 §三区分四态与契约错误（不加边，票面验收允许「未定参数准确缺项」输出）。
- [#2111](https://github.com/Newchanlun/NewChanlun/issues/2111) 补全 §三；实现与测试仍归 #1441。以下行号据 `impl/1441-cost-stop-policy` 取证头 `b7e23c31bc353378b71b090499c6eeea91676c92`：
  - [`cost_stop.rs:69-86,136-161,171-195,209-278,282-301`](https://github.com/Newchanlun/NewChanlun/blob/b7e23c31bc353378b71b090499c6eeea91676c92/rust/src/theta_v0/cost_stop.rs#L69)：签署费率和实测来源、四态、波幅证据与分母检查（旧零早返 :249-251）、来源匹配；测试 seam `:322-452,499-516`。
  - [`policy_records.rs:76-87,625-647`](https://github.com/Newchanlun/NewChanlun/blob/b7e23c31bc353378b71b090499c6eeea91676c92/rust/src/theta_v0/policy_records.rs#L76) 与取证快照中的 [`cost-stop.json:4-56`](https://github.com/Newchanlun/NewChanlun/blob/b7e23c31bc353378b71b090499c6eeea91676c92/rust/src/theta_v0/policy_records/cost-stop.json#L4-L56)：继续读既有 v1，不改签值；零值用非生产夹具覆盖。[#2126](https://github.com/Newchanlun/NewChanlun/pull/2126) 将两份记录分置于 [`P0.v1.json`](https://github.com/Newchanlun/NewChanlun/blob/c2806071dec8d0669f478cec4df093781f691232/rust/src/theta_v0/policy_records/cost-stop/P0.v1.json) 与 [`P1-hl-testnet.v1.json`](https://github.com/Newchanlun/NewChanlun/blob/c2806071dec8d0669f478cec4df093781f691232/rust/src/theta_v0/policy_records/cost-stop/P1-hl-testnet.v1.json)。
  - 行号取自 `impl/1441-cost-stop-policy` 的 `5a4033fd9083aafaea580ef56c050c1e21ef29df`，#1441 第三轮重写后以其新头为准：[`cost_stop.rs:418-420`](https://github.com/Newchanlun/NewChanlun/blob/5a4033fd9083aafaea580ef56c050c1e21ef29df/rust/src/theta_v0/cost_stop.rs#L418-L420) 移除了 `ZeroTotalCost`；`:442-454` 定义待裁错误，`:549-551` 在证据门前返回 `Err(CostStopError::ZeroMeasuredCostAwaitingRuling2111)`；`:1054-1068` 的 `zero_measured_total_never_produces_a_four_state_result` 断言与本裁定相反；`:561-564` 在证据门后已按 §三处理零代理下界。
  - #1441 须分开传播门记录错误与波幅不足，并在有向资金费转成非负成本输入前校验值域。当前基线的参照为 [`backtest/evidence_gate.rs:155-175`](../../rust/src/theta_v0/backtest/evidence_gate.rs#L155-L175)（`PolicyError`）和 [`strategy/risk.rs:998-1026`](../../rust/src/theta_v0/strategy/risk.rs#L998-L1026)（有向计提，原符号语义不改）。
  - 文档已同步：[ADR 0035 裁定三](0035-cost-stop-policy-instance-and-base-extension-evidence.md#三第一层--l0-余量对象--复测协议)已将原「否则 Disabled」的结果映射改为引用本 ADR §三；冻结、立即复测、塔底回退和延伸记录保留仍按原协议。
- [#1602](https://github.com/xy7365527-lang/NewChanlun/issues/1602)：成本参数版本化记录以本 ADR 为数值来源。

## 溯源标签

θ 倍数、VIP0 档、testnet 按主网同表、P0 holding 起始级别 L0 为 `[新缠论:选择]`；成本门方向 `[旧缠论]`（`035:30`）；原签署记录其余条款为已裁沿用（ADR 0035、ADR 0040）。

§三（#2111）的**非负成本输入域**为 `[新缠论:选择]`：本版衡量波幅能否覆盖各适用成本项的支出，不用一项的收入冲减其他项。ADR 0035 裁定一、二规定同趟往返成本之和与代理下界的用途，未规定各分项必须非负。例：其余已知成本合计 10 bp，资金费净收入 1 bp（[有向计提](../../rust/src/theta_v0/strategy/risk.rs#L998-L1010)为 −1 bp），按净额会得到正分母 9 bp；本版则返回 `NotEvaluable(UnavailableCost(Holding))`。差别在输入域，不在零分母或代理下界。

§三以下三条为 `[新缠论:推论]`：

- **全 Known 零总成本归 `NotEvaluable(ZeroTotalCost)`**：ADR 0035 裁定一的 `r = A_ℓ/C` 在 `C=0` 时无定义；已有合格波幅证据，故这是不可求值，不是证据不足或已证明不过线。
- **无效门记录与波幅不足不同**：ADR 0035 裁定一继承 ADR 0022 裁定六／七和具名版本的缺失语义。没有有效门记录就不能核验证据；记录有效但波幅证据不足时也没有可用于判定的 `A_ℓ`，不能以零分母的结果替代波幅证据不足。
- **零代理下界归 `InsufficientEvidence(UpperBoundOnly)`**：ADR 0035 裁定二只许以比值上界证明失败；合成下界为零不证明实际成本为零，也不能从该下界证明一个有效的比值低于 θ。
