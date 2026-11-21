# AT-18 登记与复跑

新增检查时，先从 crosswalk 展开 `(slice,kind,id)`，再按 ADR 0064 R03 选择对应切片账中的全部 basis。登记检查源文件的原始字节 SHA-256、适用域、精确选择器和正整数期望次数。提交前运行：

```sh
python -m pip install -r scripts/at18/requirements.txt
scripts/at18/at18-registry-lint
```

PR 上的同一入口额外计算真正的 merge-base，禁止原有键、basis 或域消失，也不允许把已有运行域改成延期。当前登记册只钉住 r5 入口摘要；正式清册、历史 cure 和 PRE 由 #2132 登记，骨架通过不等于 R10 已满足。

## 登记一条检查

对非键感知检查，把每个键的独立 `@at18 <slice> <kind> <id>` 注释挨着放在测试定义（含装饰器或属性）上方。运行器只接受在被钉住的源文件内能定位的定义：

| runner | selector 示例 | 执行口径 |
|---|---|---|
| `pytest` | `TestContract::test_retry` | 相对登记文件的节点 ID；未指定参数 ID 时包括该定义的全部参数实例。 |
| `node-test` | `restarts and resumes` | 文件内唯一的顶层字面 `test` 或 `it` 名，按原名匹配；Node 22。 |
| `cargo-test` | `x_execution+production_session/replay::resumes` | `target[+feature,feature]/完整用例路径`；`lib` 选库，其他 target 选同名顶层集成测试文件。Linux 上用 Cargo 锁文件及 libtest 精确运行。 |
| `command` | `scripts/check-example` | 直接执行登记的可执行文件，不经 shell 拼接，不接受额外参数。期望一次运行，必须键感知。 |

键感知检查从 `AT18_KEYS_FILE` 读数组，按 `kind,id,slice_id,basis_path,basis_pointer` 的 UTF-8 字节序排列；在 `AT18_WITNESS_FILE` 写 `{"schema_version":"at18-key-witness/1","entries":[...]}`。每行逐值回写身份及 `ok:true`，仅在该键实际断言成立后写成功。遗漏、重复、选择器不符、任何忽略或跳过、或非零退出均使组失败。

登记了 `record` 的检查在 `AT18_RECORD_DIR` 写业务原件。外层身份读 `AT18_RECORD`、`AT18_PROFILE_ID`（空表示 null）、`AT18_CHECK_ID`、`AT18_F`、`AT18_RUN_ID`、`AT18_RUN_ATTEMPT`；payload 的版本、来源字段及引用角色见 F 上的适配器合同。只写适合归档的业务数据，不写凭据或终端日志。

## 调用与消费

从 `main` 无输入触发对应 workflow。组作业为 `at18 <group> <registry_sha256>`，上传同 run attempt 的 `execution.json`（实际命令、测试身份、执行/跳过/忽略数、退出码和原件摘要清单）。独立托管作业在组成功且清单一致后，以 `at18-seal <record> <profile-token> <registry_sha256> <record_sha256>` 封印实际字节。只取最新 attempt；缺件需全量重跑，不跨组、跨 attempt 补原件。

空登记册走 `at18-scaffold <class> <registry_sha256>`。它封存空清单；`at18-seal-scaffold <class> <registry_sha256> <execution_sha256>` 核字节并出具 `scaffold-seal.json`。这两个名字供 #1391 辨认骨架；它们不是 R06 业务组，也不是 R07 运行记录。

experiment 的真实作业在托管预检完成后才进入 #2133 指定的专用 runner。用户签署原件须与受审适配器中已登记的评论 ID、原始正文 SHA-256、版本、profile、runner group/label、时限与动作全部一致；发送还须独立匹配 #1412。签署删除、编辑或后续未核评论均停止。专用 runner 必须配置为只接受本仓 `main` 上的对应 workflow，并预装 `gh` 和所需框架；不向 GitHub 上传场所凭据。现在两张授权 pin 都为空，实际实验不可启动。

`adapter-contract.json` 给 #1391、#1403 各自实现的单一字段定位和专用槽投影；两端应独立核 F 上的摘要、R09 锚与服务端原件，再消费相同的合约和夹具。#1279 完整评论中如出现未识别原件，先重新核准来源与归属，不猜有没有提前放行。
