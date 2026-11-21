# AT-18 登记与复跑

新增检查时，先从 crosswalk 展开 `(slice,kind,id)`，再按 ADR 0064 R03 选择对应切片账中的全部 basis。登记检查源文件的原始字节 SHA-256、适用域、精确选择器和正整数期望次数。提交前运行：

```sh
python -m pip install -r scripts/at18/requirements.txt
scripts/at18/at18-registry-lint
pytest -p no:cacheprovider scripts/at18/tests/test_at18_harness.py -v
```

PR 上的同一入口额外计算真正的 merge-base，禁止原有键、basis 或域消失，也不允许把已有运行域改成延期。闸前清册与历史 cure 的来源及复跑见[闸前清册](../../.chanlun/at18/pregate/README.md)。PRE 是独立非作者复审原件。骨架允许键尚未登记；一个键一旦加入，必须同时交齐 R03 的全部 basis，缺任何一项报 `BASIS_INCOMPLETE`。正式验收还要核所有必需键和域，不把骨架通过当成覆盖。

## 登记一条检查

对非键感知检查，把每个键的独立 `@at18 <slice> <kind> <id>` 注释挨着放在测试定义（含装饰器或属性）上方。运行器只接受在被钉住的源文件内能定位的定义：

| runner | selector 示例 | 执行口径 |
|---|---|---|
| `pytest` | `TestContract::test_retry` | 相对登记文件的节点 ID；未指定参数 ID 时包括该定义的全部参数实例，实例须使用稳定的 ASCII 标识（不要将参数值写入 ID）。 |
| `node-test` | `restarts and resumes` | 文件内唯一的顶层字面 `test` 或 `it` 名，按原名匹配；Node 22，TypeScript 源用原生 `--experimental-transform-types`，保留实际测试定义的行身份。 |
| `cargo-test` | `x_execution+production_session/replay::resumes` | `target[+feature,feature]/完整用例路径`；`lib` 选库，`bin:<name>` 选二进制，`test:<name>` 或裸名称选集成测试。从 Cargo target 根沿普通模块声明定位实际定义文件，只接受直接 `#[test]`；不接受路径重写、item 宏展开或自定义 harness。Linux 用锁文件和 libtest 精确运行。 |
| `command` | `scripts/check-example` | 直接执行登记的可执行文件，不经 shell 拼接，不接受额外参数。期望一次运行，必须键感知。 |

键感知检查从 `AT18_KEYS_FILE` 读数组，按 `kind,id,slice_id,basis_path,basis_pointer` 的 UTF-8 字节序排列；在 `AT18_WITNESS_FILE` 写 `{"schema_version":"at18-key-witness/1","entries":[...]}`。每行逐值回写身份及 `ok:true`，仅在该键实际断言成立后写成功。遗漏、重复、选择器不符、任何忽略或跳过、或非零退出均使组失败。每次启动前核源文件是 F 上的普通文件且字节等于 pin；Rust 同时核 target 配置及模块链。见证、运行原件、临时文件和 Rust 构建输出写到 checkout 外。

登记了 `record` 的检查在 `AT18_RECORD_DIR` 写业务原件。外层身份读 `AT18_RECORD`、`AT18_PROFILE_ID`（空表示 null）、`AT18_CHECK_ID`、`AT18_F`、`AT18_RUN_ID`、`AT18_RUN_ATTEMPT`；payload 的版本、来源字段及引用角色见 F 上的适配器合同。上传前递归拒绝未知字段、诊断上下文和自由文本；TB 的 `conditions` 只收正整数 `processes`，`output` 只收数值数组 `samples`（均可省略其中字段）。后续 TB 如需新增业务度量，随生产者同审新增固定字段及类型。experiment 失败时只上传当前运行新建的封闭诊断 JSON，不上传原件、执行清单或进程日志。

TB 业务原件的 `keys` 必须非空且五元组不重复。每条键须逐值匹配 F 登记册中本 TB、本证据类、本 profile 下绑定到**该原件的生产检查**的键，包括 `basis_path` 和 `basis_pointer`；指针不能含控制字符。`payload.tests` 声明的检查、测试名称和源码路径须对应本组本次实际通过的该检查。生产组归档前与末级封印共用此校验。单个分件可以只带该检查的部分登记键，整套覆盖仍由下游验收。

## 调用与消费

从 `main` 无输入触发对应 workflow。组作业为 `at18 <group> <registry_sha256>`，上传同 run attempt 的 `execution.json`（实际命令、测试身份、执行/跳过/忽略数、退出码和原件摘要清单）。生产组把清单的 SHA-256 写入本次成功上传步骤的服务端名称 `at18-anchor <execution_sha256>`，避开 GitHub 矩阵同名 job output 互相覆盖。独立托管作业从本 attempt 的分页 Jobs API 按成功组取锚；只有下载的清单字节与锚一致、每个原件实算摘要与清单一致才以 `at18-seal <record> <profile-token> <registry_sha256> <record_sha256>` 封印实际字节。只取最新 attempt；缺件需全量重跑，不跨组、跨 attempt 补原件。

空登记册走 `at18-scaffold <class> <registry_sha256>`。它封存空清单；`at18-seal-scaffold <class> <registry_sha256> <execution_sha256>` 核字节并出具 `scaffold-seal.json`。这两个名字供 #1391 辨认骨架；它们不是 R06 业务组，也不是 R07 运行记录。

experiment 的真实作业在托管预检完成后才进入 #2133 指定的专用 runner。用户签署原件须与受审适配器中已登记的评论 ID、原始正文 SHA-256、版本、profile、runner group/label、时限与动作全部一致。取 GitHub GraphQL 完整评论页；签署评论必须存在且 `lastEditedAt` 为 null。其他评论必须在签署秒之前创建，若编辑过，最后编辑也必须早于签署秒；时间缺失或同秒无法确认先后时停止。当前仅接收 `query`；即使两个授权 pin 都已填写，发送、取消、改单或平仓退出等外效也保持硬关闭，直至接入 #1412 的实际逐动作授权门。专用 runner 只接受本仓 `main` 上的对应 workflow，预装 `gh`、AT-18 requirements 和所需框架，并只配场所读权限；不向 GitHub 上传场所凭据。当前两张授权 pin 均为空，业务实验不可启动。

`adapter-contract.json` 给 #1391、#1403 各自实现的单一字段定位和专用槽投影；两端应独立核 F 上的摘要、R09 锚与服务端原件，再消费相同的合约和夹具。#1279 完整评论中如出现未识别原件，先重新核准来源与归属，不猜有没有提前放行。
