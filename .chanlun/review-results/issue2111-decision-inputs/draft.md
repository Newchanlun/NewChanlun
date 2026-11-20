# #2111 · 成本停止的零总成本边界（送审稿）

## 问题

[#2111](https://github.com/Newchanlun/NewChanlun/issues/2111) 补齐 #1323 / SPEC #1340 的 TB-02-S（#1441）：适用的往返成本都有可信数值、相加为零时，四态归属是什么？与 ROUNDTRIP 波幅下界证据和 θ 检查怎样衔接？候选代码先判零，连波幅证据不合格或总和只是代理下界为零时也返回同一个原因。新增真实 profile、费率／成本或风险阈值的实际取值、资金、账户与量档均不在本票；`user_gate=[]`。

## 权威依据

- `docs/chanlun/text/blog/035-第35课.md:30`【正文，界在 :38】：「那些太小的级别，不足以让交易成本、交易误差等相对买卖点间波幅足够小，这样的操作，从长期的角度看，是没有意义的」。信号是相对大小，不是一个零分母算法（`[旧缠论]`）。`.chanlun/definitions/qujiantao.md:427-441,468,518-534` 把参数留给场所和执行系统，区分经济门与塔底。
- [ADR 0035 裁定一至三及五](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md)（取证基线 :12–22、:40–44）与 [#1354 resolution](https://github.com/Newchanlun/NewChanlun/issues/1354#issuecomment-6153713798) Q1–Q3、Q5：往返比值、证据门和四项来源；缺项不是零，代理不能证明通过；`InsufficientEvidence` 与测得失败分开。裁定三「否则 Disabled」在可求值的余量复测里读，不能吞并裁定二的不可评估或同段对 #907 材料单列的证据不足。
- ADR 0022 裁定六／七及记录修订（`docs/adr/0022-acceptance-criterion-parameters.md:47-64,97-111,124`）规定样本不足须明示「判不出」，合格窗各自比较；[#1441 的 #1677 接口评论](https://github.com/Newchanlun/NewChanlun/issues/1441#issuecomment-6326059290) 确认共享证据门。ADR 0044 §一、二（:23–28、:32–41）及 [#1559 resolution](https://github.com/Newchanlun/NewChanlun/issues/1559#issuecomment-6311314201) 明定 P0/P1 滑点 Missing 与代理下界限制，未定全 Known 的零分母。
- 边界先例：`docs/adr/0031-principal-batches-phase-predicate-corporate-actions.md:28-30` 对另一比值在零基数时保留类型化不可计算，不换分母；只借此说明「数已知、式无定义」应与缺证据分开，不搬本金判据或状态名。ADR 0057（`docs/adr/0057-p0-venue-profile-v2-signature.md:129-147`）允许 synthetic 模型在其字段写 0，却不把其滑点升为本成本门 Known；可签零与本门证据成立是两件事。
- `docs/agents/doctrine-rules.md:43-55,61-77`（[#799](https://github.com/Newchanlun/NewChanlun/issues/799#issuecomment-5138056638)、[#804](https://github.com/Newchanlun/NewChanlun/issues/804#issuecomment-5138190089)）与 `docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md:9-30,39-48`：同一准入不能用宽档接管，不能把宽严两档录成可选值；同一版本和同输入不得按级别分派。

## 候选

1. **全部 Known、总成本为零 → `NotEvaluable(ZeroTotalCost)`，先于波幅检查。** 采纳具名状态，不采纳早返顺序。ADR 0035 只定义有分母的比值；ADR 0031 的另一比值支持把无定义与数据缺失分开。若波幅样本或窗口不足，早返会掩盖 ADR 0022 要报告的证据不足。若「波幅不足」指合格但过不了 θ，则要区分域：有正总成本时，任一合格窗比值不过线仍是 `Disabled`；全 Known 零总成本时没有可比较的 θ 比值，也没有另一个已裁的绝对幅度下限。即使合格下界为 0，也不能先按 `0/0` 或移项后的 `0 ≥ 0` 判过线或不过线。因此早返会错换 `InsufficientEvidence`，不会覆盖一条已成立的 `Disabled`；下游必须保留三种未通过状态的区别。
2. **成本趋零时任一正波幅过门 → `Enabled`，仍须证据门。** 对固定 `A_ℓ > 0`，从 `C > 0` 趋向 0，`A_ℓ/C` 趋向正无穷；这是极限，不是 `C = 0` 读数。所提分支在同一个成本准入上、只因原比值不可算就换另一判据放行，构成 #799 禁止的接管。把它预选成 policy 字段，也只会在同一输入上多放行、不会新增拒绝，是宽严两档。全域另立一个不依赖比值的统一判据，逻辑上不是运行时兜底，但会改 ADR 0035 的比值定义域与余量对象，不作为本票可选值。
3. **有零读数即 `InsufficientEvidence`，复核来源。** 否决把数值 0 当作证据质量。可疑来源按既有来源门退回；来源相符、全部 Known、窗口合格时，再多零样本也不能使分母非零。只有明确的窗口不足或代理无法证明失败才用 `InsufficientEvidence`。
4. **记录层拒绝零费率，求值不可达。** 否决。两份现有 v1 均是正费率，改成拒收不会让它们失效，滑点 Missing 也不能因此消失；但 ADR 0035 对 θ 有正下界、对 Known 费率没有严格正约束。零费率不等于总成本为零，例如合法签署的 `fee = 0` 加上同域实测正滑点，仍是有定义且应按 θ 比较的正分母。拒绝会误伤零费场所的合法 profile，既不是来源核验也不是修复零分母。无需在案场所或实际费率才能判这个逻辑边界。
5. **代理下界合计也为零（Q6）**：不套 Known 零分母，也不凭代理零放行。若 `C_min=0`，真实 `C` 可以为 0 或大于 0；对合格正波幅无可用的比值上界，对合格零波幅也不能排除 `C=0` 的不可评估。无法证明是有定义且不过线的失败，推荐 `InsufficientEvidence(UpperBoundOnly)`。正代理下界的原判据照旧。

## 裁定

正本落点：docs/adr/0044-cost-stop-policy-signed-instance-v1.md

先解析成本来源和适用项。Missing 或无合格来源沿用 `NotEvaluable` 及缺项原因；holding 未到生效级别不纳入。签署零与合格实测零同为数值零但保留各自来源、有效域；费率继续只从获授权记录读取，运行读数不覆盖签署值。成本来源可用后，先查波幅证据：不足返回 `InsufficientEvidence(Amplitude)`；证据合格后才检查比较定义域。全 Known 且总成本为零返回 `NotEvaluable(ZeroTotalCost)`，不做 θ 比较；含代理且合计下界为零返回 `InsufficientEvidence(UpperBoundOnly)`。正分母沿用逐窗比较；含代理只在可证明失败时返回 `Disabled(UpperBoundOnly)`。

零不是额外阈值：它是既有比值的定义域边界。将早返作为生产可选顺序会改变单一四态输出、掩盖已定的证据不足；将「零→放行」作为可选值会给同一判断加宽档。Q1–Q6 不新增字段；θ、成本值及来源继续使用已有具名版本记录与原授权，无隐含备用值，不改 P0/P1 v1、不扩有效域。各级同规则；只有 Enabled 可以通过本成本门，三种非 Enabled 状态不合并为「测得失败」，L0 与阶段二其他条件不改。

## 验收清单

- 命令（送审文档）：在 `decision/2111` 候选 HEAD 执行 `test "$(git diff-tree --no-commit-id --name-only -r HEAD)" = docs/adr/0044-cost-stop-policy-signed-instance-v1.md && git diff --check HEAD^ HEAD`。
- 命令（原件完整）：从证据分支切到原件目录执行 `shasum -a 256 -c <(grep -v '^#' MANIFEST.txt)`（bash/zsh）。
- #1441 测试名 `known_zero_total_is_not_evaluable_with_qualified_windows`：合格下界全正、以及含合格 0 各一例；全 Known 总成本为 0，两例均精确为 `NotEvaluable(ZeroTotalCost)`。
- #1441 测试名 `insufficient_amplitude_precedes_known_zero_total`：全 Known 总成本为 0，波幅证据不足、空窗或门版本不符均精确为 `InsufficientEvidence(Amplitude)`；复用现有 `disabled_when_a_qualified_window_fails` 作正成本、合格但任一窗数值不过线的 `Disabled(Measured)` 对照。
- #1441 测试名 `signed_and_measured_zero_keep_their_sources`：用非生产夹具从记录加载有来源的 `fee=0`，运行 Known 来源实测全零得到 `NotEvaluable(ZeroTotalCost)`；只把一个实测项改成正值、保持费率为零，在已知阈值的合格窗得到 `Enabled`；只把零读数的来源改成不匹配得到对应输入的 `NotEvaluable(UnavailableCost(...))`。另以实际 P0/P1 v1 的 `p0_missing_slippage_is_not_evaluable`、`p1_missing_slippage_is_not_evaluable` 锁：传入滑点 0 不能补齐签署记录的 Missing。
- #1441 测试名 `zero_proxy_lower_bound_is_not_known_zero`：合计下界为 0、有至少一条代理证据，合格正波幅与合格零波幅均为 `InsufficientEvidence(UpperBoundOnly)`；复用 `proxy_lower_bound_can_only_prove_failure` 锁正代理上界不过线或不能证明失败的两个方向。
- #1441 测试名 `zero_cost_rule_is_level_invariant`：保持 holding 在两级均适用，提供相同 policy、已知零成本与同份波幅证据；两个级别的四态和原因相同。
- 票状态：#2111 在所审版本非作者异家族独审 PASS、ADR 入 main 前保持 OPEN；#1441 在正式收口门及上述测试锁未通过前保持 OPEN。

## 受影响票与 blocking 边变化

- #1441 负责实现与测试。候选取证头 `b7e23c31bc353378b71b090499c6eeea91676c92`（`origin/impl/1441-cost-stop-policy`）：`rust/src/theta_v0/cost_stop.rs:69-86,136-161` 费率与读数类型，`:171-195` 四态及原因，`:209-278` 来源、分母域和逐窗求值（零短路在 `:249-251`），`:282-301` 来源匹配，`:322-452,499-516` 现有夹具及测试插入点；`rust/src/theta_v0/policy_records.rs:76-87,625-647` 及 `rust/src/theta_v0/policy_records/cost-stop.json:4-56` 核对两份 v1 保持原样。该头仅观察到求值器和测试消费；实际下游接线由 #1441 按原票完成，不在本裁定分支修改 Rust／Lean／Python。
- #1360 TB-02 汇总接 #1441 的原义务；#1443、#1444 继续等 #1441 对各片的原成功前置。#1366 TB-07 保持 AsKnown 按有效版本及既有回放规则；#1367 TB-08 及 #1382／#1400／#1412 只在原域提供实际来源，升级仍另出版本。#1602 的历史场所记录不重开；不把其它回放、synthetic 假设借为 Known 成本。#1323 的 Destination 与 SPEC #1340 验收不变。
- 已有原生边「#1441 blocked by #2111」。不增删 blocking 边；仅在 #2111 按原流程关闭后解除其阻塞效果，#1441 另有 #1440（OPEN）、#1359／#1354（CLOSED）不动。保留「#1443／#1444 blocked by #1441」，以及 TB-02→TB-07→TB-08 的既有边。不把局部成本边界加成整个 TB 的新开工门。

## 授权引用

本条依 #1909 代理独审裁定

[#1909](https://github.com/Newchanlun/NewChanlun/issues/1909) 与 ADR 0041「授权来源与生效边界」约束普通 P 类获审版本。本稿交异家族非作者按 R1–R8 审查，未登记 PASS；获审后记为「代理独审裁定」，不是现有签署记录的 `UserSigned`，也不签新的真实阈值或权限。

## 引用自证

| 引用 | 核实命令 | 结果摘要 |
|---|---|---|
| `docs/chanlun/text/blog/035-第35课.md:30,38` | `nl -ba docs/chanlun/text/blog/035-第35课.md` | 逐字与正文相符，30 在 38 前；行首非注，摘句无行内注；相对波幅方向而非端点算法。 |
| `.chanlun/definitions/qujiantao.md:427-441,468,518-534` | `rg -n 'ROUNDTRIP|成本门|波幅' .chanlun/definitions/qujiantao.md` | 两道界分开，场所数据不入教义正本；逐级按同探针复测。 |
| ADR 0035 :12–22、:40–44 | `nl -ba docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md` | 比值、证据门、Missing、代理下界方向、ROUNDTRIP 余量及 AsKnown。 |
| ADR 0044 :23–28、:32–41 | `nl -ba docs/adr/0044-cost-stop-policy-signed-instance-v1.md`（源提交） | 两份 v1 滑点 Missing；§二.6 输出四态，未定零分母。 |
| ADR 0022 :47–64、:97–111、:124 | `nl -ba docs/adr/0022-acceptance-criterion-parameters.md` | 样本不足明示判不出；逐窗、非点估计与版本字段。 |
| ADR 0031 :28–30 | `nl -ba docs/adr/0031-principal-batches-phase-predicate-corporate-actions.md` | 本金另一比值非正基数给 Typed NotComputable。 |
| ADR 0057 :129–147 | `nl -ba docs/adr/0057-p0-venue-profile-v2-signature.md` | synthetic 已签 0 是模型假设，不升级成本门滑点。 |
| ADR 0041 :9–30、:39–48 | `nl -ba docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md` | 可选值条件与真实阈值硬门、不得冒充 UserSigned。 |
| `docs/agents/doctrine-rules.md:43-55,61-77` | `cat -n docs/agents/doctrine-rules.md` | 同判断不设宽严档，跨级须同输入同输出。 |
| #1354 评论 6153713798 | `gh api repos/Newchanlun/NewChanlun/issues/comments/6153713798` | Q1–Q3、Q5 区分比值、证据、不适用及回放；不签数值。 |
| #1559 评论 6311314201 | `gh api repos/Newchanlun/NewChanlun/issues/comments/6311314201` | P0、P1 v1 费率为正、滑点 Missing、其余来源所列如实。 |
| #1441 评论 6326059290 | `gh api repos/Newchanlun/NewChanlun/issues/comments/6326059290` | #1677 evidence-gate v1 与 A_ℓ 既裁读法等同。 |
| #799 评论 5138056638；#804 评论 5138190089 | `gh api repos/Newchanlun/NewChanlun/issues/comments/5138056638`；`gh api repos/Newchanlun/NewChanlun/issues/comments/5138190089` | 收敛通则与每级同判据的 resolution。 |
| #2111、#1441、#1323、#1340、#1909 | `gh issue view <票号> --repo Newchanlun/NewChanlun --comments`（#1909 同仓以 JSON 取正文及评论） | 前者未裁边界；实施片、主图与 SPEC 现行范围；#1909 独审代普通人工审批。 |
| #1360／#1366／#1367、#1382／#1400／#1412、#1443／#1444、#1602 | `gh issue view <票号> --repo Newchanlun/NewChanlun --json number,state,title,url,body,comments` | 各 TB、实施叶、历史场所记录；非本裁定改写对象。 |
| #2111、#1441、#1360、#1366 的 blocking 边；#1440、#1359／#1354 的边状态 | `gh api --paginate 'repos/Newchanlun/NewChanlun/issues/<票号>/dependencies/<blocked_by或blocking>?per_page=100'` | #2111 仅阻 #1441；#1441 阻 #1443／#1444；TB-02 阻 TB-07，TB-07 阻 TB-08。 |
| #1441 候选代码与机读记录（以上逐项行号） | `git show b7e23c31bc353378b71b090499c6eeea91676c92:<文件路径> \| nl -ba` | 四态、来源、定点比较、零早返、v1 费率及 Missing、基线测试均在该头。 |

## 考古对照

| 点 | 归类 | 出处 | 草稿处置 |
|---|---|---|---|
| Q1 | B | #2111 候选一、#1441 候选头、ADR 0035 裁定一；ADR 0031 裁定四为类比 | 保留类型化无定义：证据合格且全 Known 零总成本 → `NotEvaluable(ZeroTotalCost)`。 |
| Q2 | B | #1441 候选头；ADR 0022 裁定六／七、ADR 0035 裁定一至三 | 纠正零早返，先判波幅证据，再判比较定义域；正成本比较失败仍为 `Disabled`。 |
| Q3 | B | ADR 0035 裁定一、二、五；ADR 0057 synthetic 模型先例；#1441 来源匹配代码 | 合格的两种零值同算，来源分记；允许合法零费率，不把签署／回报跨域代用。 |
| Q4 | A | ADR 0035 裁定二、ADR 0044 §二.3、#1559 resolution | 沿用缺项不代零、代理只能证失败、holding 适用级别不改。 |
| Q5 | A | ADR 0041 裁定一、二、四；#799／#804 | 宽严两档不设字段；已有合法版本字段保持原样。 |
| Q6 | C · decision | ADR 0035 裁定二约束一侧证据；候选头的短路只有合计值，未设计零代理的独立证据归属 | 有合格窗且代理下界总和为 0 时报告 `InsufficientEvidence(UpperBoundOnly)`。 |

```canonical_edit
{
  "version": 1,
  "operation": "edit",
  "path": "docs/adr/0044-cost-stop-policy-signed-instance-v1.md",
  "replacements": [
    {
      "before": "> 正本：本文件是 `#1354/cost-stop-policy/v1` 在 `P0` 与 `P1-hl-testnet` 两个 profile 上的签署值（θ 与四项成本输入的状态、来源与有效域）的正本。\n> 最后裁定：#1559（2026-10-21，用户批复）\n> 受影响代码清单：见「下游与受影响票」节（本 ADR 只登记数值，读取实现归 #1441 TB-02-S）",
      "after": "> 正本：本文件登记 `#1354/cost-stop-policy/v1` 在 P0 与 P1-hl-testnet 的签署值；§三规定成本停止求值的零总成本边界。\n> 最后裁定：#2111（2026-11-20，P 类方法修订）；P0／P1-hl-testnet 的签署值沿用 #1559（2026-10-21，用户批复）。\n> 受影响代码清单：见「下游与受影响票」节（#2111 候选行号及基线；实现归 #1441）。"
    },
    {
      "before": "6. TB-02-S [#1441](https://github.com/xy7365527-lang/NewChanlun/issues/1441) 读取当前生效版本，输出 Enabled / Disabled / InsufficientEvidence / NotEvaluable 之一；机读文件路径与格式归 #1441 实施，本 ADR 是唯一数值来源。",
      "after": "6. TB-02-S [#1441](https://github.com/xy7365527-lang/NewChanlun/issues/1441) 读取当前生效版本，输出 Enabled / Disabled / InsufficientEvidence / NotEvaluable 之一；机读文件路径与格式归 #1441 实施，本 ADR 是唯一数值来源。\n\n### 三、已知总成本为零的求值（[#2111](https://github.com/Newchanlun/NewChanlun/issues/2111)，2026-11-20）\n\n记 `C = 2·fee + slippage + latency_error [+ holding]`，与 [ADR 0035](0035-cost-stop-policy-instance-and-base-extension-evidence.md) 裁定一同尺度、同往返口径。先按请求时刻的有效记录、有效域、级别及来源解析成本；只合计适用项。适用项 Missing 或无合格输入仍按 §二与 ADR 0035 裁定二处理为不可评估，不用 0 占位；未到生效级别的 holding 不适用。获授权的已知零值与匹配已登记 Known 来源的运行实测零值，在各自来源门通过后同为 0；来源及有效域各自保留。零费率可进入合法记录，不代表其余成本为零；运行读数不得覆盖已签值或将 Missing、代理下界改成 Known。\n\n成本来源可用后，先查 ROUNDTRIP 波幅证据是否符合所引证据门（[ADR 0022](0022-acceptance-criterion-parameters.md) 裁定六／七和版本记录）。不满足时为 `InsufficientEvidence(Amplitude)`，即使所有适用成本项均已知且 `C = 0`。合格下界与下界数值过线是两件事：\n\n| 成本证据 | 合格波幅下界的读法 | 输出 |\n|---|---|---|\n| 所有适用成本项为 Known，`C > 0` | 逐窗比较 `A_ℓ/C ≥ θ` | 全过为 `Enabled`；任一窗不过为 `Disabled(Measured)` |\n| 所有适用成本项为 Known，`C = 0` | 比值无定义，不做 θ 数值比较 | `NotEvaluable(ZeroTotalCost)`；合格下界为 0 或为正均如此 |\n| 含 ProxyLowerBound，合成下界 `C_min > 0` | `A_ℓ/C_min` 只给比值上界 | 任一窗口上界严格小于 θ 为 `Disabled(UpperBoundOnly)`；否则 `InsufficientEvidence(UpperBoundOnly)` |\n| 含 ProxyLowerBound，合成下界 `C_min = 0` | 未证明实际总成本为 0，也不能据该下界作上界的 θ 比较 | `InsufficientEvidence(UpperBoundOnly)` |\n\n`Disabled` 表示证据已证明门槛不满足，不表示比值无定义。此门没有独立的绝对波幅最低值；正成本比较上的不过线仍为 `Disabled`，零总成本时不得用交叉相乘的等价式越出正分母定义域，也不填极限值、最小分母或备用判据。三种非 Enabled 结果均不放行本门；调用方保留四态及原因，不把「缺证据／不可评估」记成测得不过线，不改现有塔底和进阶复测协议。\n\n零分母处置和证据先决关系是对既有比值及证据契约的边界补全，不设可调字段（[ADR 0041](0041-degrees-of-freedom-configurable-not-excluded.md) 裁定一、二、四；#799、#804）。同一规则用于各级和各有效 profile；继续按已授权版本读取 θ 与成本来源，变动成本值或来源仍须按原合同另出版本。P0、P1-hl-testnet 两份 v1 签署值、来源与有效域不变；两版滑点仍为 Missing，按原合同输出 `NotEvaluable`。本条只定求值方法，不签任何实际取值。"
    },
    {
      "before": "- [#1441](https://github.com/xy7365527-lang/NewChanlun/issues/1441) TB-02-S：读本 ADR 的版本输出四态之一（不加边，票面验收允许「未定参数准确缺项」输出）。",
      "after": "- [#1441](https://github.com/xy7365527-lang/NewChanlun/issues/1441) TB-02-S：读本 ADR 的版本输出四态之一（不加边，票面验收允许「未定参数准确缺项」输出）。\n- [#2111](https://github.com/Newchanlun/NewChanlun/issues/2111) 补全 §三；实现与测试仍归 #1441。以下行号据 `impl/1441-cost-stop-policy` 取证头 `b7e23c31bc353378b71b090499c6eeea91676c92`：\n  - `rust/src/theta_v0/cost_stop.rs:69-86,136-161,171-195,209-278,282-301`：签署费率和实测来源、四态、波幅证据与分母检查（旧零早返 :249-251）、来源匹配；测试 seam `:322-452,499-516`。\n  - `rust/src/theta_v0/policy_records.rs:76-87,625-647`、`rust/src/theta_v0/policy_records/cost-stop.json:4-56`：继续读既有 v1，不改签值；零值用非生产夹具覆盖。"
    }
  ]
}
```
