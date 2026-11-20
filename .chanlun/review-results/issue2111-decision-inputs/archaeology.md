# #2111 考古原件：成本停止的零总成本边界

取证日期 2026-11-20；仓内源 `b9d898dccf46c2a716115eaa1215bc39c458a959`；#1441 候选 `b7e23c31bc353378b71b090499c6eeea91676c92`（只读抓取 `origin/impl/1441-cost-stop-policy`）。分级 P，[分级评论](https://github.com/Newchanlun/NewChanlun/issues/2111#issuecomment-7042010826)，`user_gate=[]`：不签实际资金、账户、量档、成本或风险阈值。

tracker 包括全部状态及评论索引；每点再换一组说法查。仓内命中数是行数，以下只列与问题直接有关的出处及区分项；动态 tracker 可有新增命中。命令里的仓内查询以源提交为准。

## Q1 · B：适用成本项均 Known 且总成本为零时，四态落哪一态？

- **Tracker**：命中 1：#2111 OPEN。

  ```bash
  gh issue list --repo Newchanlun/NewChanlun --search '"ZeroTotalCost" in:title,body,comments' --state all --limit 50 --json number,state,title --jq '.[]|[.number,.state,.title]|@tsv'
  ```

- **Tracker**：命中 6：#2111 OPEN、#1441 OPEN、#1559 CLOSED、#1323 OPEN、#1340 OPEN、#1677 CLOSED。

  ```bash
  gh issue list --repo Newchanlun/NewChanlun --search '"成本停止" "分母" in:title,body,comments' --state all --limit 50 --json number,state,title --jq '.[]|[.number,.state,.title]|@tsv'
  ```

- **仓内**：命中 17。

  ```bash
  rg -n --color never --max-columns 300 --max-columns-preview 'ZeroTotalCost|零分母|分母为零|总成本.{0,4}(为零|为 0|= ?0)' analysis/ docs/ .chanlun/
  ```

- **仓内**：命中 9。

  ```bash
  rg -n --color never --max-columns 300 --max-columns-preview 'ratio_lb_ge_theta|往返总成本|ROUNDTRIP.{0,20}(单边|波幅)' analysis/ docs/ .chanlun/
  ```

相关命中及其射程：

- `#2111 票面候选一；#1441 候选 b7e23c31bc353378b71b090499c6eeea91676c92:rust/src/theta_v0/cost_stop.rs:244-251`：候选读到 total == 0 返回 NotEvaluable(ZeroTotalCost)，未过裁定。
- `docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md:14,19,22；#1354 resolution 6153713798 Q1–Q3`：原式以往返总成本作分母，区分证据不足与失败；没有把零分母解释成通过。
- `docs/adr/0031-principal-batches-phase-predicate-corporate-actions.md:28-30；.chanlun/definitions/sanjieduan.md:7`：本金阶段的指标在非正基数输出类型化 NotComputable，不换分母；只作另一判断的类型化类比。

归类理由：A_ℓ/C 在 C=0 无定义，不是测得低于 θ，也不是因少样本没有下界。不以 +∞、交叉相乘或 ε 分母把未定义变成可放行。候选代码只说明现有提案，不在权威链上。

区分／冲突：不能把 #1354 同一 resolution 里另一条「零成本筹码转移生而过闸」读成本门豁免；该条明指 growth_eligible。

供起草的默认处置：波幅证据合格后，全 Known 且总成本为零记 NotEvaluable(ZeroTotalCost)。

## Q2 · B：适用成本来源已满足时，零分母与 ROUNDTRIP 波幅下界检查的先后是什么？

- **Tracker**：命中 7：#2111 OPEN、#1559 CLOSED、#1354 CLOSED、#1558 CLOSED、#1598 CLOSED、#1340 OPEN、#1677 CLOSED。

  ```bash
  gh issue list --repo Newchanlun/NewChanlun --search '"成本停止" "波幅" in:title,body,comments' --state all --limit 50 --json number,state,title --jq '.[]|[.number,.state,.title]|@tsv'
  ```

- **Tracker**：命中 14：#1441 OPEN、#1559 CLOSED、#1385 OPEN、#1558 CLOSED、#1354 CLOSED、#1774 CLOSED、#907 CLOSED、#853 CLOSED、#1598 CLOSED、#847 CLOSED、#817 CLOSED、#1557 CLOSED、#1323 OPEN、#787 CLOSED。

  ```bash
  gh issue list --repo Newchanlun/NewChanlun --search '"成本门" "下界" in:title,body,comments' --state all --limit 50 --json number,state,title --jq '.[]|[.number,.state,.title]|@tsv'
  ```

- **仓内**：命中 29。

  ```bash
  rg -n --color never --max-columns 300 --max-columns-preview '波幅.{0,20}(下界|证据门|不过|不足)|lb\(r\)' analysis/ docs/ .chanlun/
  ```

- **仓内**：命中 16。

  ```bash
  rg -n --color never --max-columns 300 --max-columns-preview '每窗各自过线|不算通过、不算失败|L0Margin' analysis/ docs/ .chanlun/
  ```

相关命中及其射程：

- `#1441 候选 b7e23c31bc353378b71b090499c6eeea91676c92:rust/src/theta_v0/cost_stop.rs:248-278,365-393`：代码先判合计为零，后查波幅证据门；正成本基线测试对证据不合格与合格下界不过线给不同状态。
- `docs/adr/0022-acceptance-criterion-parameters.md:47-64；#1441 评论 6326059290`：样本不足须明示判不出，逐窗各自过线；#1441 绑定等同的证据门。
- `docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md:14,22；#1354 resolution 6153713798 Q1、Q3`：一为合格证据前件，二为下界比值判据；#907 既有材料不足不能当第一层通过，原文没有零分母与它的并发优先级。

归类理由：成本来源先按原合同解析；在成本可用的路径上，先验证是否存在可用下界，再在正分母域做数值比较。缺波幅证据为 InsufficientEvidence；有合格下界且正分母，比值不过线才给 Disabled。零分母不构成可比较的失败。

区分／冲突：zero-first 会把同一零成本输入的波幅证据不足吞成 ZeroTotalCost；本门无独立绝对幅度门，故不遮掉已证明的 Disabled。

供起草的默认处置：先验波幅证据，后查分母、算 θ 比值；否决候选的零成本早返。

## Q3 · B：签署为零与运行实测为零如何等价，有来源的零费率可否进记录？

- **Tracker**：命中 2：#2111 OPEN、#363 CLOSED。

  ```bash
  gh issue list --repo Newchanlun/NewChanlun --search '"零费率" in:title,body,comments' --state all --limit 50 --json number,state,title --jq '.[]|[.number,.state,.title]|@tsv'
  ```

- **Tracker**：命中 5：#1559 CLOSED、#1602 CLOSED、#1323 OPEN、#1558 CLOSED、#1598 CLOSED。

  ```bash
  gh issue list --repo Newchanlun/NewChanlun --search '"成本输入" "签署" in:title,body,comments' --state all --limit 50 --json number,state,title --jq '.[]|[.number,.state,.title]|@tsv'
  ```

- **仓内**：命中 13。

  ```bash
  rg -n --color never --max-columns 300 --max-columns-preview '零费(率|用|场所)|费率.{0,12}(为零|为 0|= ?0)|费率簿引用|fee: Known' analysis/ docs/ .chanlun/
  ```

- **仓内**：命中 10。

  ```bash
  rg -n --color never --max-columns 300 --max-columns-preview '缺项代 0|来源升为 Known|跨域 Unsupported|KNOWN.{0,12}零' analysis/ docs/ .chanlun/
  ```

相关命中及其射程：

- `docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md:14,19,41；docs/adr/0044-cost-stop-policy-signed-instance-v1.md:24-28,55-58,77-80`：有效域、已知来源与缺项分开；P0/P1 v1 是正费率且滑点 Missing，未列费率严格大于零的约束。
- `#1441 候选 b7e23c31bc353378b71b090499c6eeea91676c92:rust/src/theta_v0/cost_stop.rs:69-86,136-151,227-248,282-301`：费率来自记录固定分数（分母非零，分子允许零）；其它实测使用非负定点数并要求来源匹配。
- `docs/adr/0057-p0-venue-profile-v2-signature.md:129-147；#1774 评论 6542854318、6723858747`：另族 synthetic／历史回放记录允许具名零参数但不得作为本成本门的实证。此为来源边界先例，不是成本门全零样本。
- `analysis/btc_vs_bh_structural_analysis.md:112；analysis/notional_exposure_leverage_research.md:233`：存在零费率假设的推论层材料；不是已签真实场所，不据此推出实况。

归类理由：来源合法性与数值是两维；两个渠道都获得 Known 后同尺度的 0 代入同一式。费率为 0、合格滑点 > 0 时 C>0，记录拒零会错挡有定义的求值。缺项、跨域或未标定的 0 不能代替已授权来源。

区分／冲突：场所成交／synthetic 的零模型值不等于成本停止实测 Known。

供起草的默认处置：允许有效记录签署零和匹配来源的实测零等值，保留出处及适用域；费率仍从记录读取，运行值不替换已签值。

## Q4 · A：与 ADR 0044 的滑点 Missing、代理下界只能判失败条款的关系？

- **Tracker**：命中 3：#1559 CLOSED、#1354 CLOSED、#1774 CLOSED。

  ```bash
  gh issue list --repo Newchanlun/NewChanlun --search '"ProxyLowerBound" in:title,body,comments' --state all --limit 50 --json number,state,title --jq '.[]|[.number,.state,.title]|@tsv'
  ```

- **Tracker**：命中 7：#1441 OPEN、#1559 CLOSED、#1774 CLOSED、#1354 CLOSED、#1323 OPEN、#1598 CLOSED、#787 CLOSED。

  ```bash
  gh issue list --repo Newchanlun/NewChanlun --search '"成本门" "缺项" in:title,body,comments' --state all --limit 50 --json number,state,title --jq '.[]|[.number,.state,.title]|@tsv'
  ```

- **仓内**：命中 8。

  ```bash
  rg -n --color never --max-columns 300 --max-columns-preview 'ProxyLowerBound|UpperBoundOnly|只能判失败' analysis/ docs/ .chanlun/
  ```

- **仓内**：命中 11。

  ```bash
  rg -n --color never --max-columns 300 --max-columns-preview '滑点.{0,12}Missing|缺项是状态|缺项代 0|代理下界充 Known' analysis/ docs/ .chanlun/
  ```

相关命中及其射程：

- `docs/adr/0044-cost-stop-policy-signed-instance-v1.md:26-27,32,38；#1559 resolution 6311314201；#1441 评论 6311316938`：两 v1 的滑点 Missing 已定 NotEvaluable；P0 代理延迟不能证明通过，P1 不借域。
- `docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md:19,41,44；#1354 resolution 6153713798 Q2、Q5`：适用项 Missing 不代 0，代理只给比值上界；holding 按起始级，TB-08 仅升级来源。

归类理由：已裁 Missing、代理和有效域约束直接沿用；代理恰好合计为 0 的具体结果另列 Q6。

## Q5 · A：是否把零成本四态或证据优先级变为可调字段？

- **Tracker**：命中 24：#1818 OPEN、#1612 CLOSED、#1599 CLOSED、#1531 CLOSED、#1590 CLOSED、#1677 CLOSED、#1790 CLOSED、#1783 CLOSED、#1644 CLOSED、#1539 CLOSED、#1534 CLOSED、#1598 CLOSED、#1538 CLOSED、#1610 CLOSED、#1535 CLOSED、#1533 CLOSED、#1323 OPEN、#1532 CLOSED、#1340 OPEN、#1627 CLOSED、#1786 CLOSED、#812 CLOSED、#1557 CLOSED、#787 CLOSED。

  ```bash
  gh issue list --repo Newchanlun/NewChanlun --search '"同一判断" "可调" in:title,body,comments' --state all --limit 50 --json number,state,title --jq '.[]|[.number,.state,.title]|@tsv'
  ```

- **Tracker**：命中 8：#1323 OPEN、#1590 CLOSED、#1598 CLOSED、#1612 CLOSED、#1677 CLOSED、#1599 CLOSED、#1783 CLOSED、#1538 CLOSED。

  ```bash
  gh issue list --repo Newchanlun/NewChanlun --search '"自由度通则" "成本" in:title,body,comments' --state all --limit 50 --json number,state,title --jq '.[]|[.number,.state,.title]|@tsv'
  ```

- **仓内**：命中 140。

  ```bash
  rg -n --color never --max-columns 300 --max-columns-preview '宽严两档|备用值|改签即新版本' analysis/ docs/ .chanlun/
  ```

- **仓内**：命中 22。

  ```bash
  rg -n --color never --max-columns 300 --max-columns-preview 'second_layer\.rule|合法候选保留|可调字段.{0,16}默认值' analysis/ docs/ .chanlun/
  ```

相关命中及其射程：

- `docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md:9-30,39-48；docs/agents/doctrine-rules.md:43-55,61-77；#799、#804 已关 resolution`：真正自由度才落版本字段；事先选定也不能选择同一判断宽严档。各级同判据。
- `docs/adr/0022-acceptance-criterion-parameters.md:103-124；docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md:28`：真正可选的统计参数、第二层规则有版本字段；下界而非点估计及逐窗而非合计保持单一固定规则。

归类理由：极限开门在相同准入输入上严格扩张通过集合，不能藏进字段；重排并屏蔽已裁证据不足不是合法的输出选项；把已知 0 当缺失或拒绝合法费率也不成立。阈值与合法来源仍走原版本签署规则。

## Q6 · C / decision：有合格波幅证据，但至少一项为代理且总成本下界恰为零时如何报告？

- **Tracker**：命中 2：#2111 OPEN、#1340 OPEN。

  ```bash
  gh issue list --repo Newchanlun/NewChanlun --search '"代理下界" "为零" in:title,body,comments' --state all --limit 50 --json number,state,title --jq '.[]|[.number,.state,.title]|@tsv'
  ```

- **Tracker**：命中 1：#1559 CLOSED。

  ```bash
  gh issue list --repo Newchanlun/NewChanlun --search '"UpperBoundOnly" in:title,body,comments' --state all --limit 50 --json number,state,title --jq '.[]|[.number,.state,.title]|@tsv'
  ```

- **仓内**：命中 0。

  ```bash
  rg -n --color never --max-columns 300 --max-columns-preview '(代理下界|ProxyLowerBound|UpperBoundOnly).{0,24}(为零|为 0|= ?0|零分母)|零.{0,16}代理下界' analysis/ docs/ .chanlun/
  ```

- **仓内**：命中 3。

  ```bash
  rg -n --color never --max-columns 300 --max-columns-preview '只能判失败|可判失败.{0,6}不可判通过|上界低于门槛' analysis/ docs/ .chanlun/
  ```

相关命中及其射程：

- `docs/adr/0035-cost-stop-policy-instance-and-base-extension-evidence.md:19；docs/adr/0044-cost-stop-policy-signed-instance-v1.md:27,38；#1559 resolution 6311314201`：给了代理只可证失败的方向，未单列零代理合计。
- `#1441 候选 b7e23c31bc353378b71b090499c6eeea91676c92:rust/src/theta_v0/cost_stop.rs:244-278,427-456`：通用零早返尚未设计独立的零代理处理；代理测试使用正下界，无零代理断言。

归类理由：C_min=0 只知真实 C≥0；对正幅度不存在可供比较的有限比值上界。幅度为 0 且真实 C>0 才可证明不过线，代理不能排除真实 C=0 时比值未定义。由逻辑边界即可推得，非缺外部场所事实或读数。

区分／冲突：候选早返混同 Known 0 与代理下界 0。

建议裁定：证据合格且代理合计下界为 0 时 InsufficientEvidence(UpperBoundOnly)，不得归实际总成本为零或判通过。

## 附：复核与边快照

- 原评论按 `gh api repos/Newchanlun/NewChanlun/issues/comments/<id>` 逐条取正文和作者；已关 #1354、#1559 和在用 #1441 的相关评论没有零分母／优先级决议。#1774 是另外的场所 profile 模型，不是成本停止 P0 v2。
- 检查 `formal/Origin/` 中 `cost.stop|roundtrip|交易成本|成本门` 只命中其它用途（字典序目标及净值），未发现本部署比值的退化定义；#1354 的仓内受影响清单也标注该成本门没有 Lean 定义式。
- #35 课原文取 `docs/chanlun/text/blog/035-第35课.md:30`，界在 :38，行首无注，摘句无行内注。:32 的「只有当成本为0时」同段在谈降低持仓成本，不是本票往返费率/误差分母，也不作为极限算法的依据。
- `gh api --paginate "repos/Newchanlun/NewChanlun/issues/<号>/dependencies/<blocked_by或blocking>?per_page=100"`：#2111 无上游、仅阻 #1441；#1441 上游为 #1440（open）、#1359/#1354（closed）、#2111（open），下游 #1443、#1444（open）。#1360 阻 #1366，#1366 阻 #1367；TB-08 叶的 #1382→#1400→#1412 已有。无新边。
- 无 `research` 或 `probe` 缺口：零与缺失的区分、定义域和代理上界由既有合同及反例直接推出，不需要认定任何真实零费场所或新增采样。
