# 主线行为与兼容性：能启动不等于可作部署键名

固定主线 `b9d898dccf46c2a716115eaa1215bc39c458a959`。Boat `hc-ci-slim`，Linux x86_64、glibc 2.39、rustc 1.99.1（`58cf8f9c35b355199727627d07ae34a4e2846d67`），生产 feature `production_session`，真实 launcher / X / S / E / B / 系统 stat。测试从 Git 归档取 `rust/`、`s_session/`，仅在沙盒向现有集成测试追加探针；不改产品文件。Boat 前置 `boat limits` 显示 `canStart=true`，2/300 active，下一次启动额外收费 0。运行 `boat run --from hc-ci-slim --type large --no-env --timeout 900 --push /Users/silencehan/.t3/evidence/issue2134/probe-input -- bash run.sh`；复现脚本、原封包和原始日志在该输入目录及相邻 `boat-mainline.log`。日志 73–96 行共 24 次入口观测，99–101 行是测试成功和沙盒回收（`bx_evbx7g6h`）。

不传端点、不发请求，合成文件只含中性 marker 或系统路径清单；宿主环境不传入，入口仅提供系统 PATH 和可用的合成键。Launcher 一侧复用 `rust/tests/production_session_entry.rs:233–248,461–470` 的配置，S 预置已签 synthetic 锚；表中「launcher init」指 launcher 自己创建状态/初始化 E/B，S/E/B 的 spawn 以真实日志与 socket 见证，不把预置 S 误算为拒绝后的副作用。单启 X 不使用文件；`=`、NUL、空名及过长键不以普通环境 API 赋值。serving 由 X 日志与已提交的 `writer_epoch=1` 同时确认，launcher 成功后主动停止退出 0；单启 X 成功后主动 SIGTERM，信号不是故障。所有样本均未 panic。

| profile 键（原字节） | 主线 launcher | 主线单启 X `serve` | 正当使用与收窄处置 |
|---|---|---|---|
| `NC_X_VENUE_CREDENTIAL_SENTINEL` | 四域启动，X serving，epoch 1 | 正常注入，serving，epoch 1 | 合法正控；保留。 |
| `PATH` | 合成值含系统目录，四域和 X serving | 路径值同时满足 X 的非空凭据检查，serving | 现状能启动，不能当凭据键：一个键同时控制程序查找并会被 stat 保留。只搬键名与已授权的注入配置；PATH 恢复其路径用途。另见 #2113 作者原始 `r4/boat-baseline-collision.log:65–70`。 |
| `PATH=<串>` | experiment 和 simulation 都启动；experiment 还通过凭据存在性检查 | 未注入该键：experiment 已开库并提交，随后 `MissingDependency` / 2；simulation serving | **可运行但不正当。** 两个配置名可编码成同一个内核键，不能用 Rust/libc 某次能取值证明可安全部署；禁止任何位置的等号。 |
| `=` 开头（`=MARKER`） | experiment 和 simulation 都启动，X serving | 未注入该键：experiment 已提交后 `MissingDependency` / 2；simulation serving | **可运行但不正当。** 首分隔符前是空名；后续分隔符可能让某些枚举/查找把它当成别的键。拒绝键名，不声称清除了 X 外部的同类记录。 |
| 含 NUL（19 字节） | S/E/B spawn 后，在 X spawn 拒绝，`MissingDependency`（`nul byte found`）/ 2，X 未启动、未建库 | profile 解析通过，未注入该键；开库提交之后 `MissingDependency` / 2 | `exec` 环境项是 NUL 结尾，无法无损注入。没有正当凭据键用法；原生晚失败改为共同早拒绝。 |
| 空名 | 在 launcher 校验即 `InvalidDomain` / 2，未开始 init 或域 spawn | 在 profile 校验即 `InvalidDomain` / 2、无 X 库 | 既有非法；保留早拒绝。不是 B13 的「空名原始环境项」。 |
| 仅空白（3 字节，含 tab） | 启动，X serving | 普通 API 注入，serving | 可作 Linux 的不透明键，不能作稳定的可移植部署键；无法可靠辨认/抄写，不 trim 成另一键。无仓内正当用途，若私有配置在用则改名。 |
| 4096 字节单一 ASCII 字母 | 启动，X serving | 普通 API 注入，serving | 可运行，不把「所有长名字必失败」当理由。键名只需可辨的短后缀；统一 64 字节上限，保留仓内最长合规键 30 字节，避免把键长交给平台/环境总量决定；私有配置无豁免。 |
| 131072 字节单一 ASCII 字母 | S/E/B spawn 后，X spawn `E2BIG`（`Argument list too long`）/ 2；X 未启动、未建库 | 未注入该键；开库提交后 `MissingDependency` / 2 | 在本次系统上无法由 launcher 注入，不是所有平台的断点测量。64 字节是项目的键长约束，不是对任意凭据值或完整 envp 的 exec 成功保证。 |
| 非 ASCII（17 字节，合法 UTF-8） | 启动，X serving | 普通 API 注入，serving | Linux 可以保存 UTF-8；跨部署工具不把 Unicode 当可移植键名，也不做规范化或大小写合并。无仓内正当用途；如有私有使用，统一改名。 |

两组含等号的「单启」按普通启动器环境语义，**不**伪造 raw envp。glibc 2.39 经 launcher 自己序列化后，experiment 的 serving 证明 X 读到非空值；不承诺其他运行时如此。独审 `env-api.log:6–9` 的中性标签实测和报告 `REPORT.md:9–13,38–41` 进一步区分了底层编码、可枚举性与生产可达性；这些记录不能代替 #2113 的最终修复验收。字面 `PATH` 的非路径合成负例和可运行路径正例也见该报告 `:65–67`。

命名空间外还包括两类未运行的候选：`LD_PRELOAD`、`LD_LIBRARY_PATH` 等是运行时保留的控制键，使用属于另一种配置行为，不是正当凭据键；没有用合成载荷试改动态加载。普通、可移植、非控制的域外键则**可能有正当用途**，会被这次命名空间收窄影响；仓内唯一实例是下面不用凭据值的模拟占位。其余私有部署实例如有，按同一规则改名，无需为改名启用新凭据或重新给权限。

### 整仓有效名字

按 `origin/main` 全仓追 `credential_scope|credential_source|x-execution-profile`，再追 profile 生成点、字符串拼装与样例（考古 G1/G6）。这里只列实际填入 `env` 的值，不把变量类型、shell PATH、凭据文件路径当键名。

| 键 | 位置和用途 | 新域 |
|---|---|---|
| `NC_X_VENUE_CREDENTIAL` | `docs/runbook_production_session.md:67–77` 的唯一部署样例 | 合法；保留为推荐示例。 |
| `NC_X_VENUE_CREDENTIAL_SENTINEL` | `rust/tests/production_session_entry.rs:29,233–248`，生产入口样例构造器；#1383 B13 提交 `2de3a469` 同文件 `:29,247` 沿用 | 合法；保留，不放宽 B13。 |
| `UNUSED_SIMULATION_CREDENTIAL` | `rust/tests/history_simulation_entry.py:123`，history simulation 必填空占位，不供应凭据 | **不合法**。#2113 同步改为 `NC_X_VENUE_CREDENTIAL_SIMULATION`，测试仍不供应凭据，历史回放本身不变。 |
| 无字面值 | `docs/adr/0062-fu18-venue-account-permission-binding.md:147` 只有 /2 形状；`rust/src/history_simulation/README.md:4` 只有 /1 版本说明 | 不构成额外在用键或 /2 的实现证据。 |

`HYPERLIQUID_PRIVATE_KEY` 是 ADR 0048 `:311,464–466` 明确不收编的旧 Python 路径；#2113 R4 `store.rs:531,559` 附近 `NEWCHAN_2113_STAT_ENV_SENTINEL`、`NEWCHAN_2113_VENUE_CREDENTIAL` 是过滤测试的父环境，不是 X profile 字段。它们不算部署迁移对象，也不通过新域。

部署证据：`CONTEXT.md:370`、ADR 0028 `:28,99`、[#1561 落地评论](https://github.com/Newchanlun/NewChanlun/issues/1561#issuecomment-6315084208) 确认 P2 不激活、真实场所记录在部署状态目录；[#1383 B13 进展](https://github.com/Newchanlun/NewChanlun/issues/1383#issuecomment-7040986467) 证明当前收据是合成夹具。未发现仓内或 tracker 有私有部署使用任何被剔除名字的证据；未访问部署宿主、私有 profile、凭据文件或进程环境，不能把「未发现」外推为「未使用」。部署负责人在升级前按 [收口要求](2113-closeout.md) 只核已知的配置字段与注入配置，不读、复制或提交值。
