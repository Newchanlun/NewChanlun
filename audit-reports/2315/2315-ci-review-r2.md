@coordinator [done] `#2315`（FM-06 `formal_math/` CI 流水线 v2，`origin/infra/2315-ci-v2` @ `3e097f535d`，相对 R1 `25c4841e1f` 仅改 7 个文件 +275/-85，基线 `e277af4a55`）第 2 轮独立非作者定点复审报告：

# VERDICT: PASS

R1 全部 **3 项阻断项（B1–B3）**、**3 项条件项（C1–C3）** 及绝大部分注记均已完整、精准闭合；`25c4841e1f..3e097f535d` 未引入新的安全漏洞、逻辑 bug 或回归。全仓 22 个新增文件保持 `100644`、零改动 `#2312` 与 `ci.yml`、`r2-verify.log` 显示 `selftest_ci.py`（T1–T19）全绿且真实 Mathlib 全流程（`run.py` 七步 + `lake check` + `comparator.sh` + `PKG_UNCHANGED_OK`）通过。

---

## 一、R1 问题逐项核销表

| 编号 | R1 问题 | R2 核查位置与落实细节 | 实测证据 | 状态 |
|---|---|---|---|---|
| **B1** | `comparator.sh` `build_and_export_challenge` 置于 `\|\|` 禁用 `set -e`，`defhole-control` 构建失败假绿 | `comparator.sh:59-130` 所有关键命令（`lean-toolchain` 读取、`lean --version`、`lean --print-prefix`、`cd -P`、`mkdir`、`lake build`、`leanexport`、`[ -s "$export_out" ]`）均显式 `\|\| return`；`run_sample_case`（`:174-200`）与正式段（`:312-330`）拆分 `chal_rc` / `comp_rc`，挑战失败一律判 `status=1` 且不进入 `lake comparator`；`sample-green` 核对 `"Your solution is okay!"`、`defhole-control` 核对 `"Const does not match"` | `r2-verify.log` `PASS T18_B1_COMPARATOR_CHAL_FAIL_NO_FALSE_GREEN` + 真实跑批中 sample-green / defhole-control 诊断文本命中 | **已闭合** |
| **B2** | `run_pr_gate.sh` `--mode main --before` 对非快进回退误用 `merge-base` 走快速路径 | `run_pr_gate.sh:106-134` 拆分 `pr` 与 `main` 分支：`mode=main` 仅在 `--before` 有效且 `merge-base --is-ancestor "$before_sha" "$head_sha"` 退 `0`（严格快进）时才直接以 `fp_base=$before_sha` 调 `precheck.py`；非快进回退、历史改写、无效 `--before` 或 `is-ancestor` 异常均置空 `fp_base`、强制走全量主干门 | `r2-verify.log` `PASS T16_MAIN_FAST_PATH_AND_FULL`、`PASS T17_B2_MAIN_ROLLBACK_NO_FAST_PATH` | **已闭合** |
| **B3** | `formal-math.yml` 顶层共享并发组碰撞 + `workflow_dispatch` 缺分支约束与 `checkout ref: main` | 移除顶层 `concurrency`；4 个作业各设互不碰撞的作业级 `concurrency.group`（`formal-math-pr-${{ github.event.pull_request.number }}`、`formal-math-trusted-${{ inputs.pr_number }}`、`formal-math-main`、`formal-math-paranoid`）；三个 `workflow_dispatch` 路径（`:174, 307, 408`）均补 `github.ref == 'refs/heads/main'`；全部 4 处 `actions/checkout`（`:63, 185, 327, 419`）显式钉 `ref: main` | `selftest_ci.py` `T1` 静态解析断言全过（`PASS T1_WORKFLOW_AND_SHELL`） | **已闭合** |
| **C1** | `materialize.py` `validate-comparator-config` 放行未知键；基线 manifest JSON 解析退 `1` 非 `2` | `materialize.py:54-60, 351-353` 收紧为封闭顶层键白名单 `ALLOWED_COMPARATOR_KEYS`（5 键），任意 `external_kernels` / `enable_nanoda`（含 `false`/`{}`/`?`）及未知键一律退 `1`；`strict_json` 增加 `fault_code` 参数，基线 `lake-manifest.json`（`:226`）传 `fault_code=2` | `r2-verify.log` `PASS T19_C1_COMPARATOR_CLOSED_SCHEMA_AND_GUARDS`（覆盖 6 类非法键） | **已闭合** |
| **C2** | `bwrap_pkgbind.sh` 双参选项表错位（`--chmod` 等）+ 缺 `--unshare-all`/`--` 时静默未注入 | `bwrap_pkgbind.sh:85, 93` 将 `--chmod\|--file\|--bind-data\|--ro-bind-data\|--bind-fd\|--ro-bind-fd` 移入双参数分支；`:110-113` 循环结束后若 `saw_lake=1 && -n pkg_src` 立即退 `2` fail-closed | `r2-verify.log` `PASS T15_BWRAP_PKGBIND_RO_OFFLINE`（覆盖 `--chmod 0755 --share-net` 与未注入退 `2`） | **已闭合** |
| **C3** | `selftest_ci.py` 缺 T2 与 B1/B2/C1/C2 回归测试 | 补齐 `test_t2_precheck_compliance`（`:164-186`）、`T1` 并发/ref/mask/LAKE_NAMES 检查、`T15` C2 回归、`T17`（B2）、`T18`（B1）、`T19`（C1 + 双配置 + 非法 `challenge_module` + `ChanChallenge` 缺配置）；`T9` 同步断言 `NOT_ANCESTOR` 退 `2` | `r2-verify.log` T1–T19 全部 `PASS`（`CI_SELFTEST_ALL_PASS`） | **已闭合** |
| **R1 注记** | ① `$auth` `::add-mask::`；② `comparator.sh` 工具链核对；③ `ChanChallenge/` 有 `.lean` 缺配置禁跳过；④ `README.md` 写明 `trusted-release` 边界；⑤ `NOT_ANCESTOR` 退 `2` 与 git 故障区分；⑥ `formal-math.yml:344` 注释对齐 | 均已逐项落实：`formal-math.yml:89, 225`（2 处 `::add-mask::$auth`）、`comparator.sh:65-78`、`comparator.sh:258-265`、`README.md:31, 33`、`run_pr_gate.sh:138-148`、`formal-math.yml:344`。（注记 1 可选纵深项 `actions/cache/restore` 保持原策略，非阻断） | 代码核实 + `T1`/`T9`/`T19` 通过 | **已闭合** |

---

## 二、R2 改动复查与非阻断注记

未发现任何阻断性新 bug 或安全回归；记录 2 条轻微非阻断观察供后续演进参考：

1. **`comparator.sh:229-265` 独立调用时的 `--head` 校验**：若有人绕过 `run_pr_gate.sh` 直接传不存在的 `--head` 调 `comparator.sh`，`git_has` 与行 260 `git ls-tree ... 2>/dev/null || true` 均会吞错并走“无配置跳过”路径。在现役 CI 链路中 `run_pr_gate.sh:75` 已强制 `rev-parse --verify "${head}^{commit}"`，故不影响门禁安全性；建议后续顺手在 `comparator.sh:228` 后补一条 `rev-parse --verify` 校验，并给行 260 `ls-tree` 补 `--end-of-options` 与 `-c core.quotepath=false`。
2. **`formal-math.yml:307-348` 并发队列固有边界**：`formal-math-main` 设 `cancel-in-progress: false`（GitHub 并发队列最多保留 1 running + 1 pending），理论上若极短时间内发生 3 次连续 push（第 1 次未碰 `formal_math/` 已检出运行、第 2 次碰 `formal_math/` 排队被第 3 次未碰 `formal_math/` 顶掉），第 3 次仅对比 `C..D` 可能走快速路径；但所有进 `main` 的改动均先过 `formal-math-pr` 必需检查且快速路径仍跑 `precheck.py` 整树校验，属 GitHub 并发模型固有语义。

---

## 三、未覆盖范围（需上线 GitHub Actions 后实跑确认，与 `README.md:35-47` 对齐）

1. GitHub Actions 托管 `ubuntu-24.04` 实跑：`pull_request_target` 产出的 `formal-math-pr` 设为 `main` 分支保护必需检查时的挂载行为（`head.sha` vs `base.sha`）、`enforce_admins: true` 下 `infra/*` PR 的合入闭环、受保护环境 `formal-math-trusted-change` 的人工审批与分支部署策略、红绿各一次实跑 run 链接、`actionlint` 校验，以及 16 GiB 内存下 `formal-math-paranoid`（含 `nanoda`）是否 OOM。
2. `prepare_packages.sh` 空目录冷启动端到端实跑（验证全部依赖包 `chmod -R a-w` 迁移后不触发 Lake 回写）。
3. `install_elan.sh` 实网下载 `v4.4.0` 与 `ELAN_SHA256` 校验及 `actions/cache` 命中/未命中双路径。
