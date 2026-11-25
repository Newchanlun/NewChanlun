# formal_math 的 CI：PR 门与主干门（#2315 草稿）

> **状态：草稿，没有在 GitHub 上实跑过。** 工作流 `.github/workflows/formal-math.yml` 的每一步都还没有
> 在托管 runner 上执行过；下文「本机读数」是 SafeCode（Ubuntu 26.04.1，x86_64）上的实测，不能当作 CI
> 读数。工作流没有挂进 `ci-ok` 的必需集合，`ci.yml` 未改。

门禁划分以 #2312 的用户裁定为准（评论 `7164343103`），取代 #2315 票面「PR 门跑门禁 1 至 3 与 6 至 16」：
阻断门只有可信边界 1、2、3（源码层与环境层）、6a、6b、15；S、7a、7b、8a、8b、9、10 是不阻断的审阅报告。

## 文件

| 文件 | 作用 |
|---|---|
| `.github/workflows/formal-math.yml` | 三个作业：`pr-gate`、`main-gate`、`paranoid`（手动） |
| `prefetch_check.py` | 联网取依赖之前的边界检查：门 1、门 2 的 lakefile 白名单、`require` 与 manifest 一致 |
| `install_elan.sh` | 装钉选版本的 elan（`v4.4.0`，发行包按 sha256 核对） |
| `sandbox_setup.sh` | 装 bubblewrap，放开非特权用户命名空间，探针确认 `--unshare-all` 能拆网络 |
| `offline.sh` | 在无网络、无凭据的 bwrap 沙箱里跑命令（构建、全部门禁、审阅报告） |
| `comparator.sh` | 主干门的 comparator 一步：样板自检，再跑正式配置（存在时） |
| `comparator/` | comparator 样板：一个 Challenge 与解答对、`definition_names` 必红样本与对照 |

## 两道门各跑什么

### PR 门（`pr-gate`，`pull_request` 到 main，路径过滤 `formal_math/**` 与本工作流）

| 步骤 | 对应门禁 | 网络 | 阻断 |
|---|---|---|---|
| 检出（`persist-credentials: false`，`fetch-depth: 0`） | — | 有 | — |
| elan 缓存与安装 | — | 有 | — |
| `prefetch_check.py` | 门 1；门 2 的 lakefile 白名单；本脚本补的 `require` 钉选 | 无（只读文件；门 1 会调 `lean --version`，工具链未缓存时由 elan 按已核对的钉选下载） | 是 |
| `sandbox_setup.sh` | 沙箱前提 | 有（apt） | 是（探针失败即红，不退回无沙箱） |
| Mathlib 缓存与 `lake exe cache get` | — | 有，**最后一个联网步骤** | 是 |
| `offline.sh run_gates.py --repo-root .` | 阻断门 1、2、3、6a、6b、15 全部 | 无 | 是 |
| `offline.sh run_gates.py --report` | 审阅报告 S、7a、7b、8a、8b、9、10 | 无 | 否（`continue-on-error`，报告作为产物上传，人读表写进步骤摘要） |

### 主干门（`main-gate`，push 到 main 或手动触发）

PR 门的全部前置步骤，加：

| 步骤 | 对应门禁 | 说明 |
|---|---|---|
| `offline.sh run_gates.py --gate {1,2,3,6a,15}` 逐门 | 阻断门，去掉 6b | 门 6b 管 PR 分支的路径权限；在 main 上分支名没有可交付前缀，按设计判红。逐门跑会重复加载环境；建议 #2312 加「跳过 6b」的开关后改成一次调用 |
| `lake check` | 门 4（内核重放与公理闭包） | Lake 自己的 bwrap 沙箱 |
| `comparator.sh` | 门 5（陈述比对） | 样板自检；`formal_math/comparator.json` 存在时先拒收非空 `definition_names`，再比对 |
| 审阅报告 | 同 PR 门 | 不阻断 |

### `paranoid`（手动触发并勾选 `paranoid`）

`lake check --paranoid`：Lean 4.36.0 的帮助写的是五个外部检查器（`leanchecker-paranoid`、`lean4lean`、
`nanoda`、`con-leche`、`con-ron`），不是票面写的四个。耗时与资源没有读数，作业 `continue-on-error`，
超时 6 小时。

## 无网络、无凭据怎么落实

- 全工作流 `permissions: contents: read`，不引用任何 secret；检出不保留令牌。
- 构建与门禁跑在 `offline.sh` 里：`--ro-bind / /` 后把 `/home`、`/root`、`/run`、`/var`、`/tmp` 换成空
  tmpfs，只回绑仓库（只读）、`formal_math/.lake`（可写）、`~/.elan`（只读），`--clearenv` 后只放回
  `PATH`、`HOME`、`TMPDIR`、`ELAN_HOME`、`LANG` 与 `GITHUB_HEAD_REF` 等几个分支名变量，
  `--unshare-all` 拆掉网络。runner 的 `.credentials`、`_temp` 下的事件文件都在 `/home` 下，看不见。
- `lake check` 与 `lake comparator` **不套** `offline.sh`：Lake 4.36.0 自己用 bwrap 隔离构建、导出与内核
  （`Lake/CLI/Check.lean` 的 `buildSandboxArgs`，同样 `--tmpfs /home`、`--clearenv`、`--unshare-all`），
  只有依赖解析一步（`lake env` / `lake resolve-deps`）放网络——依赖已在 `.lake` 里，解析不再下载。
  外面再套一层 bwrap 在 SafeCode 上起不来（见读数「嵌套沙箱」），在 CI 上没有试过。
- 做不到的：联网段里 `lake exe cache get` 运行的是钉选的 Mathlib 缓存工具，并读取 PR 的 `lakefile.toml`
  与 manifest。TOML 是数据，`lakefile.lean` 由 `prefetch_check.py` 先拒；PR 能影响的只剩钉选内的包，
  `prefetch_check.py` 拦住改钉选和 lakefile 里多出的 `require`。`sandbox_setup.sh` 用 `sudo` 改 sysctl、
  装包，发生在检出 PR 代码之后，但不执行 PR 里的任何文件（脚本本身来自 PR，这是工作流文件同等的信任级别；
  `pull_request` 事件对 fork PR 本就不给写令牌）。

## 红绿怎么触发（尚未在 GitHub 上做）

票面验收要求两道门各红绿一次并记 run 链接。建议做法：

- **PR 门绿**：本分支挂入 #2312 合入后的 main，开一个只改 `formal_math/verification/ci/` 的 `infra/` 草稿 PR。
- **PR 门红**：在一个丢弃用的 `proof/` 分支上，把 #2312 的必红样本 `verification/must_red/g3/admit/formal_math/Chan.lean`
  覆盖到 `formal_math/Chan.lean`（`theorem bad : False := by admit`），预期门 3 `TOKEN` 红、退出 1。
  路径权限的红可用 `must_red/g6b/proof-edits-defs`（`proof/` 分支改 `Chan/Defs`）。
- **主干门绿**：合入后 push 到 main 自动触发；或在任意分支 `workflow_dispatch`。
- **主干门红**：在丢弃分支上手动触发（`workflow_dispatch`），同样放入 `must_red/g3/admit`；或把
  `comparator/comparator-defhole.json` 复制为 `formal_math/comparator.json`，预期 `comparator.sh` 以门 5
  「definition_names 必须为空」判红。主干门不在 PR 上跑，所以红样本只能走手动触发。

## comparator 样板

`comparator/` 是一个只依赖 Lean 核心的独立 Lake 包。Lean 源存为 `*.lean.in`：`run_gates.py` 的
`sources()` 会把 `formal_math/` 下全部 `.lean` 当包源码审（只跳过以点开头的目录与 `verification/` 下四个
夹具目录），样板放进去会让门 2、3、6a、15 判红或无法判定（本机实测，见读数）。`comparator.sh` 把它复制到
`formal_math/.lake/fm-comparator-sample/` 再改回 `.lean`。若 #2312 愿意把 `verification/ci` 加进跳过集，
可以改回普通 `.lean` 文件。

| 配置 | Challenge | 解答 | `definition_names` | 期望 |
|---|---|---|---|---|
| `comparator.json` | `Sample.Challenge`：`double n = 2 * n`（留空） | `Sample.Solution`：导入锁定的 `Sample.Defs` 后证明 | `[]` | 退 0 |
| `comparator-defhole-control.json` | `Sample.ChallengeFalse`：`double 1 = 0`（原定义下为假） | `Sample.SolutionSwap`：不导入 Defs，自己声明 `double _ := 0` | `[]` | 退 1 |
| `comparator-defhole.json` | 同上 | 同上 | `["Sample.double"]` | 记录实际退出码 |

Lake 4.36.0 `Lake/Check/Compare.lean` 对 `definition_names` 里的常量只比较类型与安全性
（`definitionHoleMatches`），不比较定义体；比较循环遇到它也只把类型里的常量加进待查表。

## 本机读数（SafeCode，2026-11-25）

基点 `origin/infra/2312-d-perimeter` `594e49b5ec`。日志全部在 `/home/workspace/fm/r2/audit/2315/`。所有
Lean 命令经 `flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh` 包裹，`TMPDIR=/home/workspace/fm/tmp`。

**本机与 CI 的差别**：SafeCode 上 `formal_math/.lake/packages` 是指向另一工作树的符号链接（不复制 Mathlib）。
`offline.sh` 用 `FM_OFFLINE_EXTRA_RO` 把链接目标只读回绑；Lake 自己的沙箱只回绑项目目录，看不到链接目标，所以
`lake check` 实测时用 `COMPARATOR_BWRAP` 指向一个包装脚本（`bwrap-pkgbind.sh`，副本在日志目录），在 Lake 的
bwrap 参数里 `--unshare-all` 之前插一条同样的只读回绑，其余参数原样。CI 上依赖是 `.lake` 里的实体目录，两者都不需要。

| 项 | 命令（逐字见日志首行） | 退出码 | 关键数字 | 日志 |
|---|---|---|---|---|
| bwrap 探针 | `bwrap --version`；`--unshare-net` 读 `/proc/net/dev`；`--unshare-all` 内 `curl`；`unshare -Ur id` | 见右 | bubblewrap 0.11.1，`/usr/bin/bwrap` 非 setuid（`-rwxr-xr-x root`）。`kernel.apparmor_restrict_unprivileged_userns=1`，但 AppArmor 的 `bwrap-userns-restrict` 配置放行 `/usr/bin/bwrap`：`--unshare-net` 退 0，沙箱内只有 `lo`；`curl` 直连 IP 与经代理都退 7；裸 `unshare -Ur` 退 1（`uid_map` 无权写）。即非特权用户命名空间只对 bwrap 开放 | `bwrap-probe.log` |
| 嵌套沙箱 | 外层 `bwrap --unshare-all` 内再起 `bwrap --unshare-all` | 1 | `No permissions to create a new namespace`。所以 `lake check`/`comparator` 不套 `offline.sh` | `nested-and-offline-probe.log` |
| `offline.sh` 隔离 | 沙箱内 `env`、`ls /home/workspace`、`curl`、写仓库、写 `.lake` | 见右 | 注入的 `GITHUB_TOKEN=probe-secret` 不在 `env` 输出里；`/home/workspace/fm` 不存在；`curl` 退 7；写仓库 `Read-only file system`；写 `.lake` 成功 | `nested-and-offline-probe.log` |
| 阻断门（全部，离线沙箱） | `offline.sh python3 formal_math/verification/run_gates.py --repo-root .` | **0** | 墙钟 3:14（含 `lake build --wfail`；Chan 已构建、锁外排队不计）。峰值内存读不到：`/usr/bin/time` 只看到 bwrap 本身（7,856 KiB），沙箱在独立 PID 命名空间里收子进程 | `gates-offline-2.log` |
| 阻断门首跑（样板为 `.lean` 时） | 同上 | 2 | 门 3、15 对 `verification/ci/comparator/Sample/*.lean` 判红（`MODULE_FIRST`），门 2、6a 无法判定（`unknown module`）；门 6b 因工作树 `.git` 在沙箱外无法判定。前者促成 `*.lean.in`，后者促成 `offline.sh` 回绑 git 公共目录 | `gates-offline-1.log` |
| 阻断门红样本（离线沙箱） | 把 `must_red/g3/admit/formal_math/Chan.lean` 覆盖到 `formal_math/Chan.lean` 后同上，跑完 `git checkout` 还原 | **2** | 门 3 `TOKEN` ×3 红，门 6b `PATH_SCOPE` 红（`infra/` 分支改了 `Chan.lean`），**门 2、15 无法判定**——它们复用源码审计，审计失败时报「无法判定」而不是跳过，所以整体退 2 而非 1。CI 上非零即红，结论不变；但 #2312 的自测断言该样本退 1，是在最小包里只跑门 3 | `gates-offline-red-admit.log` |
| 审阅报告（离线沙箱） | `offline.sh … run_gates.py --repo-root . --report --report-dir formal_math/.lake/fm-report` | 0 | 墙钟 6 秒；`report.json`、`report.md` 写进 `.lake/fm-report/`（沙箱内唯一可写处） | `report-offline.log` |
| 取依赖前检查，绿 | `python3 formal_math/verification/ci/prefetch_check.py --repo-root .` | 0 | — | `prefetch-check.log` |
| 取依赖前检查，红 | 同上，`--repo-root` 指向一份在 `lakefile.toml` 末尾加了 `require evil` 的副本 | 1 | `REQUIRE_UNPINNED manifest 里没有这个直接依赖`；门 1 本身对该副本是绿的 | `prefetch-check.log` |
| `lake comparator` 样板（绿） | `comparator.sh` 中 `lake comparator --config comparator.json` | **0** | `Lean default kernel accepts the solution` / `Your solution is okay!`。整个 `comparator.sh`（样板构建 + 三次比对）墙钟 9.2 秒、`/usr/bin/time` 峰值 485,856 KiB（只含沙箱外的 Lake）；样板目录 264 KiB。样板只依赖 Lean 核心，**不代表带 Mathlib 的正式比对的开销** | `comparator-1.log` |
| `definition_names` 对照 | `--config comparator-defhole-control.json`（`[]`） | **1** | `Const does not match between challenge and target 'Sample.double'` | `comparator-1.log` |
| `definition_names` 必红样本 | `--config comparator-defhole.json`（`["Sample.double"]`） | **0** | Lake **接受**：解答把锁定的 `double` 换成 `fun _ => 0`，证明了原定义下为假的 `double 1 = 0`。这种配置被 comparator 接受，门 5 必须拒收非空 `definition_names` | `comparator-1.log` |
| `lake check` | `COMPARATOR_BWRAP=…/bwrap-pkgbind.sh … timeout 1800 /usr/bin/time -v lake check`（`formal_math/`） | **0** | `Lean default kernel accepts the solution`，`Uses axioms: propext, Quot.sound, Classical.choice`。墙钟 10:12，峰值常驻 2,017,572 KiB；根分区可用最低比开跑前少 2,096,572 KiB（含别的租户）；项目 `.lake`（不含 packages）258 MiB。三个 bwrap 调用里只有依赖解析一个带 `--share-net` | `lake-check-1.log`、`lake-check-1.minavail` |
| `lake check --paranoid` | 同上加 `--paranoid`，外包 `systemd-run --user --scope -p MemoryMax=10G -p MemorySwapMax=0` | **143**（未跑完） | 20:51:34 开始导出后：`Lean paranoid` 8:07 **接受**；`lean4lean` 8:34 **接受**（281,164 条声明）；`nanoda` 开跑约 2 分钟后在 10 GiB 上限处被内核 OOM 杀掉（systemd：`Failed with result 'oom-kill'`，`10G memory peak`）；`con-leche`、`con-ron` 未开始。共 21 分钟。被杀后 Lake 留下 1.25 GiB 的导出 `tmp.XXOJ48QJ`，已手工删除 | `lake-check-paranoid-1.log` |

`--paranoid` 的结论：本机 22 GiB 内存（可用约 16 GiB，与他人共用）给不起 nanoda；10 GiB 是本工位自设的上限，
不是 nanoda 的需求读数。GitHub 托管 `ubuntu-24.04` 是 16 GiB，能否跑完未知。

## 只写了、没跑过的

- 整个工作流在 GitHub 上一次都没有跑过；`actionlint` 不在本机，只做了 YAML 解析与 `bash -n`。
- `sandbox_setup.sh` 在托管 runner 上能否装上 bubblewrap、`sysctl` 放开后 bwrap 能否起：未测。本仓 #2071
  的分支名 `hillclimb/isolation-apparmor-absent` 提示隔离出过问题。
- `lake exe cache get` 在 CI 上的耗时、`~/.cache/mathlib` 的体积（会不会挤掉仓库 10 GB 的 Actions 缓存额度）、
  runner 根分区够不够放 7.3 GiB 的 `.lake/packages` 加 1.25 GiB 的导出：未测。
- 检出 `refs/pull/N/merge` 时门 6b 的读数：本机是在分支上跑的（`symbolic-ref` 取到分支名），没有走
  `GITHUB_HEAD_REF` 那条路。
- `install_elan.sh` 的下载与 sha256 只在本机核对过一次。
- 带 Mathlib 的正式 `lake comparator`：要等 `ChanChallenge` 与 `formal_math/comparator.json` 落地。

## 过审后怎么接进 `ci-ok`（留给主控）

`ci-ok` 在 `ci.yml` 里，`needs` 只能引用同一工作流的作业，所以有两条路：

1. **并入 `ci.yml`（推荐）**：把 `pr-gate`、`main-gate` 两个作业原样搬进 `ci.yml`，名字改成
   `formal-math-pr`、`formal-math-main`；路径过滤改成作业内判断（`ci.yml` 是全量触发）——在 `changes`
   作业里加一个 `formal_math` 输出（改动含 `formal_math/**` 或这两个作业的脚本时为 `true`），两个作业加
   `needs: changes` 与 `if: needs.changes.outputs.formal_math == 'true' && …`。然后在 `ci-ok` 的 `needs`
   加上两个作业名，并在它的判定脚本里把二者加进「允许 skipped」的集合，条件是
   `changes.outputs.formal_math == 'false'`（PR 上 `formal-math-main` 总是 skipped，push 上
   `formal-math-pr` 总是 skipped，也要放行）。`paranoid` 不进 `ci-ok`。
2. **保留独立工作流**：在分支保护里把 `formal-math / pr-gate` 加成必需检查。缺点是路径过滤后不触发的 PR
   上该检查永远 pending，必需检查会卡住合入；需要再加一个总是运行的占位作业。所以不推荐。

两条路都不放宽 `deepagents/review` 与 `ci-ok`，不取消 strict。
