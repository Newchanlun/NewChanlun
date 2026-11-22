# AT-18 的逐票归属、收编与图外重测证据

## 将产品归到实际交付的票

新合入用 `at18-product-delivery/1`：票面登记合入 SHA 与路径，PR 和 R09 获审 head 的提交消息分别登记同一条「票 → 路径」归属。路径必须在第一父差异中。单独写 `Closes` 不构成产品。

兼容旧合入的上界是 `b9d898dccf46c2a716115eaa1215bc39c458a959`。旧 R09 核实际 PR 差异，再取逐路径提交标题或交付 trailer、原件首行声明，或由不可变合入分支与实际差异共同限定的代码命名空间。旧 R10 清册只认证「票 → 合入」；还须有文件首部归属、该票评审原件目录或逐路径提交证据。同批合入不能代替归属。

## 证明 #1319 的旧能力由 TB-08 接管

沿用 `feed-wire-inventory/1` 清点五条旧路径；`RETIRED` 要求路径不在最终树 F。每条 `INCORPORATED` 引用在获审差异中的 `feed-wire-disposition/2`：逐旧路径声明替代模块、F 中接入点、TB-08 `check_id` 与承接理由。裁定与替代源码在 F 保持获审字节。Rust 从 F 的 Cargo 特性闭包、模块声明和公开接入关系核验替代物；用 `rustfmt` 解析相关 F 源码，不执行 Cargo，测试通过仍取自已登记作业。Python 从 F 提取受验包、登记测试和 pytest 配置，先核生产入口可达，再用 `python3 -I -B` 执行精确选择器。所有登记用例须通过，且测试体的调用轨迹须至少进入一次替代实现；只检查 `callable`、只创建生成器或仅在导入时执行都不算覆盖。

运行 Python 重验的 `python3` 须已安装 pytest。macOS 使用系统沙盒，Linux 使用支持独立网络命名空间的 `bwrap`；只提供冻结源码、可信运行时及临时目录，不继承凭据或连接场所、账户。隔离不可用、超时或缺少测试依赖时不得判定收编。

## 登记 #1320 的十年分钟数据与两次重放

`at18-heavy-preregistration/2` 计划必须在开跑前完成 Git 提交、正式 App 批准和合入。它附上每标的冻结窗口、完整性总 bar 数、按序的分块首末／计数／数据 SHA-256，以及 UTC 交易周日历和带理由的已批缺口。沿用旧窗口时，首末日期及总量必须与冻结原表一致；BRN、DX 原表不足十年，只有另行冻结并审批的十年快照才能重测。替换快照须在获审计划中写明来源及原因。

- 每标的用 `at18-heavy-input-series/1` 按顺序登记实际分块原件 SHA-256；每个 `at18-heavy-input-chunk/1` 最多 100,000 根分钟 OHLCV。连续同值分钟可无损地以 `runs` 中的起点及分钟数登记，不能用首末时间推定区间内的数据。每块的冻结摘要取 JCS 编码的 `{symbol, interval, rows}`（普通 bar 的 `minutes=1`；不含事后才能得知的 F）；实际分块还必须由其外部 manifest 按原字节登记。
- 按分段交易周重建应有分钟区间，扣除获批的假日、休市或缺失窗，与实际块逐项对账：首末须跨满十个 UTC 日历年，块序、区间、每块摘要及总数必须完全一致。周末和正常维护不算缺失；多日异常缺口必须预先列入获批表。标的结果、回放与对照均用 `input_sha256` 绑定实际分块索引。
- 两次重放分别登记 `at18-heavy-replay-run/1` 与 `at18-heavy-replay-output/1`，独立的运行 ID 与输出原件才能比较交易、声部生命周期和中枢转换。
- 尚未完成且未正式废弃时，#1320 保持 OPEN，重测列为 `required=false`；提前关闭使报告 FAIL。损坏的图外原件仍生成 #1320 诊断，#1279 和 DST-06 继续读取图内前因。

合法废弃只能由同一决策票的 OWNER 在后续 `at18-heavy-retirement-change/1` fence 中撤销或替代。记录须绑定 `decision_ticket`、`ticket: 1320`、`obligation: ISSUE_1320_HEAVY_MEASUREMENT`、原 `decision_sha256` 与 `approval_comment_id`；`disposition` 为 `REVOKE` 或 `REPLACE`，后者还须登记不同的 `replacement_sha256`。普通评论不改变授权。
