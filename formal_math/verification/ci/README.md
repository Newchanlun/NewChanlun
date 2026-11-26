# formal_math CI 门禁流水线（#2315 FM-06 v2）

> **状态：本地 Linux `bwrap` + Lean 4.36.0 全套自测与实包验通，尚未在 GitHub Actions 托管 runner 上实跑。**
> `.github/workflows/ci.yml` 与现有分支保护必需检查（`deepagents/review`、`ci-ok`、`DevSkim`）均未修改。

本目录落地 `#2315` 评论 `7176006564` 的六条硬要求，并完全对齐 `#2312` 过审版（`origin/infra/2312-h-autoparam` @ `e277af4a55`）的 `precheck.py` 与 `run.py` 契约。

## 文件清单（仓内一律 100644 模式）

按 `precheck.py` 的 `MODE` 与 `LAKE_FILE` 规则，`formal_math/` 下所有文件均为 `100644` 普通文件（无执行位），且除包根与 `verification/auditor/` 外不出现 `lakefile.toml`、`lake-manifest.json`、`lean-toolchain` 等 Lake 配置原名。

| 文件 | 作用 | 调用方式 |
|---|---|---|
| `.github/workflows/formal-math.yml` | 四个作业：`formal-math-pr`、`formal-math-trusted-release`、`formal-math-main`、`formal-math-paranoid` | GitHub Actions |
| `run_pr_gate.sh` | 统一受信入口，分 `preflight`（快速路径 + 静态预检）与 `heavy`（`run.py` + 门 4 + 门 5）两段 | `bash formal_math/verification/ci/run_pr_gate.sh ...` |
| `materialize.py` | 纯 git 原始对象取料器（`ls-tree` + `cat-file --batch`，无视 `.gitattributes`）与门 5 配置严格校验器 | `python3 -I formal_math/verification/ci/materialize.py ...` |
| `prepare_packages.sh` | 联网段末步：仅取 `main` 基线三配置下载 Mathlib 缓存并 `chmod -R a-w` 设为只读目录 | `bash formal_math/verification/ci/prepare_packages.sh ...` |
| `bwrap_pkgbind.sh` | 在仓外临时目录写出 `0700` 可执行 `COMPARATOR_BWRAP` 包装脚本（只读回绑依赖 + 剥除 `--share-net`） | `bash formal_math/verification/ci/bwrap_pkgbind.sh ...` |
| `run_lake_check.sh` | 门 4：在独立干净目录离线运行 `lake check`（或 `--paranoid`），验证宿主机 `.lake/packages` 保持空挂载点 | `bash formal_math/verification/ci/run_lake_check.sh ...` |
| `comparator.sh` | 门 5：样板两段隔离自检 + 正式配置两段隔离比对（挑战目录物理不含任何证明文件） | `bash formal_math/verification/ci/comparator.sh ...` |
| `install_elan.sh` | 钉选版本 `elan` 安装（`v4.4.0` + sha256 校验） | `bash formal_math/verification/ci/install_elan.sh` |
| `sandbox_setup.sh` | 安装 `bubblewrap`、必要时放开非特权 userns、运行断网与清环境探针（失败即红，绝不降级） | `bash formal_math/verification/ci/sandbox_setup.sh` |
| `comparator/` | comparator 样板（`*.in` 模板与三份 JSON 配置，运行期复制到仓外临时目录） | 由 `comparator.sh` 调用 |
| `selftest_ci.py` | 端到端离线 CI 自测套件（覆盖全部六条硬要求、必绿与必红场景） | `python3 -I formal_math/verification/ci/selftest_ci.py ...` |

## 六条硬要求逐条对照

1. **必需检查由主干版本工作流产生**：`formal-math-pr` 挂在 `pull_request_target` 上（工作流与脚本永远取自 `main`），拒绝 fork PR，仅通过一次性 `http.extraheader` 拉取 `refs/pull/<N>/head` 的 git 对象并校验 SHA，绝不检出、绝不在沙箱外执行 PR 任何文件。`proof/*` 分支修改 `.github/workflows/formal-math.yml` 会在 `preflight` 阶段 2 秒内以 `PATH_SCOPE` + `TRUSTED_DRIFT` 判红。
2. **对每个 PR 给出明确结果、不并入 `ci.yml`**：工作流不设 `paths:` 过滤。`preflight` 用受信提交的 `precheck.py` 以空分支名核对唯一 `merge-base..head`；当且仅当受管范围（`formal_math/` 与两个仓根受信文件）零改动且整树形状合法时，走快速路径直接绿，不下载 `elan` 与 Mathlib。重型检查留在受信文件 `.github/workflows/formal-math.yml` 内，不改动 `.github/workflows/ci.yml`。
3. **沙箱依赖只读挂载、审计与构建目录互不共享**：`prepare_packages.sh` 仅用 `main` 的三配置拉取依赖并去写位；`run.py` 内部自带受信目录与被审工作区隔离；`run_lake_check.sh` 与 `comparator.sh` 各自从 git 原始对象现造独立干净目录，并用 `COMPARATOR_BWRAP` 将依赖目录只读回绑到 `.lake/packages`，同时剥除 `--share-net` 保持全程断网。
4. **`lake comparator` 挑战隔离与空 `definition_names`**：`materialize.py validate-comparator-config` 拒收非空 `definition_names`、标准三公理之外的公理、非声明目录的 `challenge_module` 以及配置内的 `external_kernels` / `enable_nanoda`。正式配置文件默认落在受信目录 `formal_math/verification/comparator.json`（兼容未来列入 `decl` 角色的 `formal_math/comparator.json`，二者不可并存）。挑战模块先在物理上不含任何证明目录（仅含基线三配置与 `Chan/Defs`、`Chan/Hypotheses`、`Chan/Audit/Literal`、`ChanChallenge`）的 `chal/` 中离线构建，并在纯只读沙箱中通过 `leanexport` 导出 `challenge.export`，再交给独立目录 `sol/` 内的 `lake comparator --challenge-from-export`。
5. **`lake check` 在 PR 上运行**：`formal-math-pr` 与 `formal-math-main` 均在 `run.py`（第 6 步已验证所有内容模块均落在 `defaultTargets` 产物内）之后运行 `run_lake_check.sh`。
6. **放行标记独立于写码代理与 PR 标签**：自动触发的 `formal-math-pr` 永不读取 PR 标签、正文或评论，永不传 `--trusted-change-approved`，改受信文件的 PR 默认以 `TRUST_UNAPPROVED` 判红。放行仅走独立作业 `formal-math-trusted-release`（`workflow_dispatch` + GitHub 受保护环境 `formal-math-trusted-change` 人工批准 + 强制绑定 `pr_number` 与 40 位 `pr_head_sha`）。

## 上线到 GitHub 后的实跑核对清单（未核实项）

以下项目依赖 `.github/workflows/formal-math.yml` 合入 `main` 后在 GitHub 托管环境实跑确认：

1. **受保护环境配置**：在 GitHub 仓库 Settings 中创建环境 `formal-math-trusted-change`，配置必需审批人（仓库维护者）并限定仅 `main` 分支可部署。
2. **`pull_request_target` 必需检查行为**：开测试 PR 实测 `formal-math-pr` 能否设为 `main` 分支保护的必需检查，并核对检查挂载在哪个提交上（`head.sha` 或 `base.sha`）。若 GitHub 限制 `pull_request_target` 检查无法作为必需检查挂到 PR head，退路是由宿主侧审查通道（与 `deepagents/review` 同通道）代发 commit status。
3. **`enforce_admins` 下放行 `infra/*` PR 的合入闭环**：若 `formal-math-pr` 成为分支保护必需检查且 `enforce_admins: true` 保持开启，修改受信文件的 `infra/*` PR 在自动 `formal-math-pr` 上会保持红灯，届时需要决定由宿主侧通道发布可验证放行状态，还是由受保护环境审批后的通道发状态。
4. **红绿各一次验收（留存 run 链接）**：
   - 非 `formal_math/` PR：触发 `formal-math-pr` 快速路径绿；
   - `proof/*` 改动 `.github/workflows/formal-math.yml`：触发 `formal-math-pr` 红（`PATH_SCOPE` + `TRUSTED_DRIFT`）；
   - `proof/*` 写入 `#2312` 必红样本（如 `sorry`/`admit`）：触发 `formal-math-pr` 红；
   - 合法 `proof/*` 改动：触发 `formal-math-pr` 全流程绿（`run.py` + `lake check` + `comparator.sh`）；
   - `push: main` 与 `workflow_dispatch`（含可选 `paranoid`）：记录实测耗时、峰值内存与磁盘（特别是 `ubuntu-24.04` 16 GiB 内存下 `nanoda` 是否 OOM）。
