@coordinator [done] `#2315`（FM-06 `formal_math/` CI 流水线 v2，`origin/infra/2315-ci-v2` @ `25c4841e1f`，基线 `e277af4a55`）第 1 轮独立对抗审阅报告：

# VERDICT: BLOCK

整体架构与安全主线扎实：6 条硬要求均已结构化落地，22 个新增文件全部 `100644`、零改动 `#2312` 与 `ci.yml`、全链路 `python3 -I`；对抗探针 P1/P4.2/P4.3/P5 已确认 Lean 4.36.0 `FromJson` 正确映射 `external_kernels`/`enable_nanoda`（被拦截）、真实 Mathlib 下正式 `comparator.sh` 两段隔离可跑通（349 jobs 退 0）、特殊分支名与双 `merge-base` 均 fail-closed。
但对抗实测（P2、P3）与静态审查发现 **3 项可复现阻断项（B1–B3）**，须修复后进入 R2 复审。

---

## 一、阻断项（BLOCK）

### B1：`comparator.sh` 中 `build_and_export_challenge ... || rc=$?` 禁用函数体内 `set -e`，且 `defhole-control` 在构建失败时假绿（P2 实证复现）
- **位置**：`formal_math/verification/ci/comparator.sh:58-112`、`157`、`171-174`、`279`
- **攻击/失效复现路径**：
  1. 行 157 与行 279 以 `build_and_export_challenge ... || rc=$?` 调用该函数。按 Bash 语义，命令处于 `||` 左侧时会**在整个函数动态作用域内关闭 `set -e`**，导致函数内行 64（`lean --print-prefix`）、行 65（`cd -P`）、行 68/71（`mkdir`）及行 75–87（`lake build "$chal_mod"`）失败时**全部被吞掉**，脚本继续向下执行行 89–111 的 `leanexport`。
  2. 在 `defhole-control`（行 190，`want=1`）中，若挑战构建/导出失败（如 P2 将 `ChallengeFalse.lean.in` 破坏为语法错误），`lake build` 失败后仍跑 `leanexport` 并因缺 `.olean` 退 `1`，行 171 判定 `rc == want`（`1 == 1`），`comparator.sh` **从未执行 `lake comparator` 却判绿并整体退出 `0`（`P2_RC=0`）**。
  3. 正式比对（行 279）同样吞掉 `lake build` 退出码（例如超时/构建中途报错但目标 `.olean` 残留或前缀解析失败时，可能被后续命令退出码掩盖）。
- **最小修法**：
  1. 在 `build_and_export_challenge` 内每条关键命令显式失败返回：`prefix=$(cd "$chal_dir" && lean --print-prefix) || return 2`、`prefix=$(cd -P -- "$prefix" && pwd) || return 2`、`mkdir -p ... || return 2`、`timeout ... lake build "$chal_mod" || return $?`、`timeout ... leanexport ... || return $?`。
  2. 在 `run_sample_case` 中拆分挑战构建/导出退出码与 `lake comparator` 退出码：`build_and_export_challenge` 非 `0` 一律判失败（`status=1`，即使 `want=1` 也不得放行）；`defhole-control` 须捕获 `lake comparator` 输出并核对确实因陈述/常量不匹配退出 `1`（如包含 `Const does not match`），而非配置或环境故障。

### B2：`run_pr_gate.sh` 在 `--mode main --before` 下对非快进/回退推送误走快速路径跳过全量门禁（P3 实证复现）
- **位置**：`formal_math/verification/ci/run_pr_gate.sh:108-129`
- **攻击/失效复现路径**：
  - `mode=main` 时若传入 `--before`（来自 `push` 事件的 `github.event.before`），行 116–122 取 `mb = merge-base --all $before $head` 并拿 `mb..head` 喂给 `precheck.py`。
  - 当 `main` 发生非快进回退（如 `M1 -> M2` 且 `M2` 改过 `formal_math/`，回退到 `M1`）或历史改写时，`merge-base(M2, M1) = M1 = head`，`precheck.py` 以 `M1` 对 `M1` 比较报零改动。**P3 实测**：输出 `FM_CI FAST_PATH_GREEN`、`need_heavy=false`、`P3_RC=0`，即使 `formal_math/` 相对 `before` 已发生变化仍跳过 `run.py`、`lake check` 与 `comparator.sh`。
- **最小修法**：
  - 在 `mode=main` 分支中，仅当 `sgit merge-base --is-ancestor -- "$before_sha" "$head_sha"` 成立（快进推送）时才允许走快速路径，且直接以 `$before_sha` 为基线调 `precheck.py`；若 `before` 不是 `head` 祖先，禁止快速路径，强制执行完整重型门。

### B3：`formal-math.yml` 跨作业 `concurrency.group` 碰撞与 `workflow_dispatch` 分支约束缺口
- **位置**：`.github/workflows/formal-math.yml:46-48`、`174`、`303`、`318`、`400`、`406`
- **失效/风险复现路径**：
  1. 顶层 `concurrency.group: formal-math-${{ github.event.pull_request.number || github.ref }}` 使 `push: main`（`formal-math-main`）、`workflow_dispatch`（`formal-math-trusted-release`）与耗时最长 6 小时的非阻断 `formal-math-paranoid` **共用同一并发组 `formal-math-refs/heads/main`**。一旦启动 `formal-math-paranoid`，期间的主干门与受信放行门会被阻塞数小时，且 GitHub 并发队列只保留 1 个 pending，后续合并或第二个 `infra/*` PR 的 `trusted-release` 会**静默取消**排队的阻断作业。
  2. `formal-math-main`（行 303/318）与 `formal-math-paranoid`（行 400/406）接受 `workflow_dispatch`，但未校验 `github.ref == 'refs/heads/main'` 且 `actions/checkout` 未钉 `ref: main`（与行 64/182 不一致），从非 `main` 分支手动触发会直接执行该分支未合入脚本；`formal-math-trusted-release`（行 174）也仅依赖外部受保护环境策略而未在工作流内加 `github.ref == 'refs/heads/main'` 纵深检查。
- **最小修法**：
  1. 将 `concurrency` 拆到作业级或按事件/目标分桶：PR 门 `formal-math-pr-${{ github.event.pull_request.number }}`（`cancel-in-progress: true`）、受信放行门 `formal-math-trusted-${{ inputs.pr_number }}`（`false`）、主干门 `formal-math-main`（`false`）、paranoid 作业 `formal-math-paranoid`（`false`）。
  2. 对三个 `workflow_dispatch` 路径统一加 `github.ref == 'refs/heads/main'` 条件，并在 `formal-math-main` 与 `formal-math-paranoid` 的 `actions/checkout` 显式钉 `ref: main`。

---

## 二、条件项（建议本轮修 B1–B3 时一并闭合）

- **C1：`materialize.py validate-comparator-config` 补封闭顶层键白名单（`formal_math/verification/ci/materialize.py:334-381`）**
  - P1 已证实 Lean 4.36.0 `FromJson` 去掉字段尾 `?`，只认 `"external_kernels"` / `"enable_nanoda"`（均已被拦），`"external_kernels?"` / `"enable_nanoda?"` / `"unknown_key"` 不会被 Lake 执行，但校验器目前放行任意未知键（`RC=0`），且放行 `"enable_nanoda": false` / `"external_kernels": {}`。建议收紧为严格顶层键集合 `{"challenge_module", "solution_module", "theorem_names", "definition_names", "permitted_axioms"}`，未知键及任何 `enable_nanoda`/`external_kernels` 键一律退 `1`，防范上游新增配置字段。
- **C2：`bwrap_pkgbind.sh` 修复双参数选项表并加未注入 fail-closed（`formal_math/verification/ci/bwrap_pkgbind.sh:85, 93, 110`）**
  - P4.4 实测确认 `bwrap` 中 `--chmod`（以及 `--file`、`--bind-data`、`--ro-bind-data`）吃 **2 个参数**而非 1 个，当前落在行 93 单参数分支导致 `--chmod 0755 --share-net` 参数错位；且若入参无 `--unshare-all` 也无 `--`（P4.4 `case B`），`saw_lake=1` 不会刷新，依赖只读挂载会被静默跳过。虽 Lake 4.36.0 当前调用不受影响，但作为通用包装脚本建议把 `--chmod|--file|--bind-data|--ro-bind-data|--bind-fd|--ro-bind-fd` 移入双参数分支，并在循环结束后加 `[ "$saw_lake" = 0 ] || { echo "...未注入只读依赖绑定" >&2; exit 2; }`。
- **C3：`selftest_ci.py` 补齐缺失的 T2 与对抗回归用例（`formal_math/verification/ci/selftest_ci.py:5-22, 455-528`）**
  - 文档头列了 `T2` 但代码中实际缺失；建议补齐 `T2` 以及 B1（损坏 `ChallengeFalse.lean.in` 必红）、B2（`mode=main` 非快进 `--before` 必走重型门）、C1（`external_kernels`/`enable_nanoda`/未知键/双配置共存/非法 `challenge_module`）、C2（`bwrap_pkgbind.sh` `--ro-bind` 与 `--chmod` 边界）的回归测试。

---

## 三、七大维度核验摘要与建议/注记

1. **`pull_request_target` 安全性（硬要求 1）**：除 B3 外整体严密。拒绝 fork PR、校验 `base.ref == main`、`persist-credentials: false`、一次性 `-c http.https://github.com/.extraheader=...` + 立即 `unset`、拉取后复核 `fetched == PR_HEAD_SHA`、全流程不检出 PR 代码、无表达式注入进 `run:`、`$GITHUB_OUTPUT` 仅写校验后的 SHA/枚举值、全 Action 40 位 SHA 钉选、`permissions: contents: read`、`actions/cache` 路径被 `bwrap --tmpfs /home` 隔离。
   - **注记**：建议在 `fetch_pr` 对 `$auth` 补 `echo "::add-mask::$auth"`；`formal-math-pr` 可视首跑缓存策略考虑改为 `actions/cache/restore`（仅由 `formal-math-main` 写 `main` 缓存）作为纵深防御。
2. **每个 PR 均有明确结果与快速路径（硬要求 2）**：无 `paths:` 过滤，`ci.yml` 未改。PR 模式快速路径经 P5 实测（`--branch "--trusted-change-approved"` 退 2、`--branch ""` 退 1、双 merge-base criss-cross 退 1）均 fail-closed；`mode=main` 快速路径见 **B2**。
3. **只读依赖与目录隔离（硬要求 3）**：`prepare_packages.sh` 仅取基线三配置并校验 `require` 钉选、`chmod -R a-w`；`run.py`、`run_lake_check.sh`、`comparator.sh`（`chal/` 与 `sol/`）各自独立 `mktemp -d` 且用完即删 `runner_workdir`；`real-mathlib-run.log` 证 `PKG_UNCHANGED_OK`。`bwrap_pkgbind.sh` 见 **C2**。
4. **`lake comparator` 隔离与门 5（硬要求 4）**：`chal/` 物理隔离证明文件且在独立目录先构建并只读 `leanexport`，`PRIMITIVE_TARGETS`（26 项）与 `QUOT_TARGETS`（4 项）与 `Lake-CLI-Check.lean:474-532` 逐项一致；P4.2 实测真实 Mathlib 正式比对退 `0`，P4.3 实测双配置共存与非法 `challenge_module` 均退 `1`。缺陷见 **B1**、**C1**。
   - **注记**：① `comparator.sh` 建议像 `run_lake_check.sh:50-64` 一样显式核对 `lean --version` 与 `chal/lean-toolchain`；② 待将来 `ChanChallenge/` 落地 `.lean` 文件后，应禁止在无 `comparator.json` 时静默跳过正式比对（行 231–233）。
5. **`lake check` 在 PR 与主干运行及默认目标覆盖（硬要求 5）**：PR 门与主干门均运行 `run_lake_check.sh`；P4.1 核实基线 `defaultTargets = ["Chan", "ChanTest"]`，`run.py` 第 6 步 `NO_ARTIFACT` 保证全部内容文件落入默认目标构建产物；工具链核对、超时、退出码与挂载点空目录复核完整。
6. **放行标记独立性（硬要求 6）**：自动 `formal-math-pr` 永不读 PR 标签/评论且永不传 `--trusted-change-approved`；`formal-math-trusted-release` 绑定 `workflow_dispatch` + `environment: formal-math-trusted-change` + 正整数 `pr_number` + 40 位 `pr_head_sha` + 拉取后二次比对 SHA（无 TOCTOU）。并发与 ref 约束见 **B3**。
   - **注记**：按设计 `formal-math-trusted-release` 仍以 `main` 的配置与脚本跑 `prepare_packages.sh` / `run.py`，故对改动 `lakefile.toml`/`lake-manifest.json`/`lean-toolchain`/`ci/*` 的 `infra/*` PR，它核验的是预检与基线回归而非新配置本身（后者依赖非作者评审、`selftest_ci.py` 与合入后 `formal-math-main`），建议在 `README.md` 明写此边界。
7. **与 `#2312` 契约对齐**：全 `100644`、无 `LAKE_NAMES`、全 `python3 -I`、`run.py` stderr 重定向与末行 `FM RESULT GREEN ` 核对、未在 GitHub 实跑项已在 `README.md:35-47` 如实列出。
   - **注记**：① `run_pr_gate.sh:136` 对 `NOT_ANCESTOR` 返回 `1`（`precheck.py:206` 契约为 `2`），且未区分 `git merge-base` 退 `1` 与故障退 `128`；② `materialize.py:219` 解析基线 `lake-manifest.json` 失败经 `strict_json` 返回 `1` 而非故障码 `2`；③ `formal-math.yml:336` 注释「不跳过门禁」与 `push` 带 `--before` 走快速路径的实际行为略出入，建议改准确。

---

## 四、未覆盖范围（需后续实跑核验）

1. **GitHub Actions 托管 `ubuntu-24.04` 实跑项**（与 `README.md:35-47` 对齐）：
   - `pull_request_target` 产出的 `formal-math-pr` 能否设为 `main` 分支保护必需检查、实际挂载在 `head.sha` 还是 `base.sha`；
   - `enforce_admins: true` 开启时，`infra/*` 改动受信文件 PR 在 `formal-math-pr` 保持红灯情况下的合入闭环；
   - 受保护环境 `formal-math-trusted-change` 的人工审批与分支部署策略实测；
   - 红绿各一次真实 PR run 链接、`actionlint` 检查，以及 `ubuntu-24.04`（16 GiB 内存）上 `formal-math-paranoid`（含 `nanoda`）是否 OOM。
2. **`prepare_packages.sh` 冷启动端到端实测**：本轮 `selftest_ci.py`（空依赖）与 `real-mathlib-run.log`（复用已有只读依赖目录）均未从空目录冷跑 `prepare_packages.sh`（`lake exe cache get` -> 移出目录 -> `chmod -R a-w` -> 跑 `run.py` + `lake check` + `comparator.sh`），需在首跑确认全部 9 个依赖包在只读迁移后不会触发 Lake 回写。
3. **`install_elan.sh` 真实下载与 `ELAN_SHA256` 校验**：离线审阅未实网下载 `v4.4.0` 发行包复核哈希与 `actions/cache` 命中/未命中双路径。
