# #2312 运行骨架独审 r2 的夹具

报告在上级目录 `skeleton-review-r2.md`。被审提交 `1ea21f7206eb2f944d5e0a68dff915508fb83c87`。上一轮的夹具在 `origin/evidence/2312-skeleton-review` @ `7ce9e02c01` 的 `audit-reports/2312/skeleton-r1-fixtures/`，本轮原样重跑了其中的 `case_inject.py` 与 `repro_blocking.py`（日志 `logs/r1_*.txt`）。

## 怎么跑

```sh
source scripts/fm_env.sh
# 调用 lean、lake 的夹具：
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh \
  python3 audit-reports/2312/skeleton-r2-fixtures/<脚本>.py
# 不调用 lean、lake 的夹具直接跑：
python3 audit-reports/2312/skeleton-r2-fixtures/case_precheck.py
bash audit-reports/2312/skeleton-r2-fixtures/case_not_isolated_stderr.sh <被审检出>
```

环境变量：`RF_SRC`（被审检出，含 `formal_math/`）、`RF_WORK`（工作根目录，默认 `/home/workspace/fm/tmp/review-f2/work`）、`RF_ERR`（打印的标准错误尾部字节数）。

**共享依赖目录**：本轮自己写的夹具全部用 lite 基线（清单里没有依赖包）配 `RF_WORK/fake-packages` 这个自建的空目录，不碰共享依赖目录。只有三处用到共享依赖目录，都是只读挂载、没有任何改沙箱挂载的弱化：上一轮的两个夹具重跑；被审提交自己的骨架自测（对照）；`mutants2.py` 在副本里跑骨架自测时的非 lite 用例 S1、S2、S3、S10。

夹具自身不带 `-I` 运行（要导入同目录的 `rf2.py`）；它们调用被审的 `run.py` 时一律带 `-I`，除非该夹具测的就是不带 `-I` 的行为。命令行里带 `driver.py` 的运行复用预编译的审计程序产物（源码与被审提交逐字相同），只为省第 3 步的时间；四条新阻断的逐字复现都走真实命令行入口（`case_not_isolated_stderr.sh`、`case_artifacts_cli.py`、`case_signal.py` 的 `G-kill-own-lean`、`case_stream.py` 的 T1、T8、T9）。

## 文件

| 文件 | 用 lean | 内容 |
|---|---|---|
| `rf2.py` | — | 公共驱动。复用被审提交 `runner/selftest.py` 的 `Repo`、`template`、`parse_result`、`protocol` |
| `case_not_isolated_stderr.sh` | 否 | **N-1**：不带 `-I` 且标准错误或标准输出写不出时，同目录的 `re.py` 被执行并以 0 退出 |
| `case_artifacts_cli.py` | 是 | **N-2**（真实命令行入口）：名字带点的 `.olean` 与不可列出的目录绕过产物集合核对，七步全绿 |
| `case_artifacts.py` | 是 | 产物集合核对的其它边界：合法构建的产物清单、伴生文件、FIFO、顶层带点的目录、产物目录之外的东西 |
| `case_signal.py` | 是 | B-3 新形状与 **N-3**：TERM 杀 `lake`、杀自己的 `lean`、杀沙箱 1 号进程、`kill -1`、`lean` 自己以 137 退出 |
| `case_stream.py` | 是 | **N-4** 与输出失败路径：非阻塞且写满的标准输出、各路关闭或指向 `/dev/full`、构建期间 SIGINT 与 SIGTERM |
| `case_output.py` | 是 | B-1 新形状：16 种导入名、间接导入说明、声明名（含 `ENV_PARTIAL` 源定义名、`LOCK_UNLISTED`）、直接写进管道的原始字节 |
| `case_lock.py` | 是 | B-2 新形状（整条流水线）：锁文件深嵌套、浮点溢出、BOM、非对象、重复键、非 UTF-8 |
| `case_json_unit.py` | 否 | `strict_json()`、`safe()`、`unescape()` 的边界矩阵（`python3 -I case_json_unit.py <run.py>`） |
| `case_b2_caller.py` | 否 | B-2 的调用方来源：上一轮 `case_args.sh` 两例重做，另加六种 |
| `case_precheck.py` | 否 | 第 1 步转出：真预检的 11 个规则码与 2 个故障码；自举模式下 18 种假预检输出 |
| `case_usage_inject.sh` | 否 | 调用方参数与 git 报错进输出：未知开关、仓库路径、`--until` 取值带换行与 ESC |
| `case_step4_sandbox.py` | 否（只起 `bwrap`） | 第 4 步的挂载表探针，用被审 `run.py` 自己的 `sandbox()`（`python3 -I case_step4_sandbox.py <run.py> <工作根目录>`） |
| `case_fetch.py` | 否 | 取料：依赖目录缺包、基线清单不合格、umask |
| `case_isolated.sh` | 否 | 14 种启动方式（`-E -s`、`-P`、`PYTHONPATH`、`PYTHONSTARTUP`、`-m`、符号链接、相对路径、标准输入）与两路输出状态 |
| `mutants2.py` | 是 | 弱化测试 17 种，与作者 `--mutants` 的 18 种不重复 |
| `run_lean_cases.sh` | — | 依次在 `flock` + `guard.sh` 里跑若干夹具并把输出落到 `../logs/` |
| `logs/` | — | 以上各项在本次审阅中的实际输出（扩展名 `.txt`，仓库根 `.gitignore` 忽略 `*.log`），另有被审提交骨架自测的对照 `selftest_skeleton_control.txt`、依赖目录前后比对 `deps-*.txt` |
