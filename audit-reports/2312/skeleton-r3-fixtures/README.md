# #2312 运行骨架独审 r3 的夹具

报告在上级目录 `skeleton-review-r3.md`。被审提交 `14fc96c4b236c468ce57c3427e4b78ceeb29f9fe`。
前两轮的夹具在 `origin/evidence/2312-skeleton-review` @ `7ce9e02c01` 的 `skeleton-r1-fixtures/` 与
`origin/evidence/2312-skeleton-review-r2` @ `913b5a5dc3` 的 `skeleton-r2-fixtures/`；本轮原样重跑了 r2 的
`case_precheck.py`、`case_json_unit.py`、`case_b2_caller.py`、`case_step4_sandbox.py`（日志 `logs/*_rerun.txt`）。

## 怎么跑

```sh
source scripts/fm_env.sh
# 调用 lean、lake 的夹具：
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh \
  python3 audit-reports/2312/skeleton-r3-fixtures/<脚本>.py
# 不调用 lean、lake 的夹具直接跑：
python3 -I audit-reports/2312/skeleton-r3-fixtures/case_shape_unit.py <run.py> <工作根>
bash audit-reports/2312/skeleton-r3-fixtures/case_isolate3.sh <被审检出>
```

环境变量：`RF_SRC`（被审检出，含 `formal_math/`）、`RF_WORK`（工作根目录，默认 `/home/workspace/fm/tmp/review-f3/work`）。

**共享依赖目录**：自己写的夹具全部用 lite 基线（清单里没有依赖包）配 `RF_WORK/fake-packages` 这个自建的空目录，
不碰共享依赖目录。只有三处用到共享依赖目录、都是只读挂载：被审提交骨架用例的对照跑（`case_control3.py`）、
`mutants3.py` 在副本里跑骨架自测时的非 lite 用例、Q2 与 Q5 两种弱化的骨架全量。

夹具自身不带 `-I` 运行（要导入同目录的 `rf3.py`）；它们调用被审的 `run.py` 时一律带 `-I`，除非该夹具测的就是不带
`-I` 的行为。命令行里带 `driver.py` 的运行复用预编译的审计程序产物（源码与被审提交逐字相同），只为省第 3 步的时间。

## 文件

| 文件 | 用 lean | 内容 |
|---|---|---|
| `rf3.py` | — | 公共驱动，自 r2 的 `rf2.py` 改路径而来；复用被审 `runner/selftest.py` 的 `Repo`、`template`、`parse_result`、`protocol` |
| `case_isolate3.sh` | 否 | **N-1**：21 个冒名模块、不带 `-I` 的九种流状态与七种启动方式、带 `-I` 的四种对照；另打印 `sys.path`（注意：其中几个 `rc=0` 是 shell 包装的退出码，不是 `run.py` 的，准的在下一行那个夹具） |
| `case_isolate3b.py` | 否 | **N-1**：用 `fork` + `execv` + `waitpid` 精确取 `run.py` 自己的退出码，12 种流状态；另查 `-c exec(...)` 一例里 `linecache` 从哪来、内建模块能否被顶替 |
| `case_isolate3c.py` | 否 | 同上，可用 `ISO_DIR`、`ISO_HIT` 指到别的副本（用来比对 Q6 弱化副本与原件） |
| `case_shape3.py` | 是 | **N-2**：A 组只用表内合法名字（期望退 0，查有没有逃出声明范围）、B 组八种近似名字（期望逐项判红） |
| `case_shape3b.py` | 是 | **N-2**：硬链接与能力探测重做（先删再链，诊断经 `IO.eprintln` 进 `FM LOG`） |
| `case_hardlink_exact.py` | 否（只起 `bwrap`） | 第 6 步挂载下硬链接的确切 errno 与 `CapEff` |
| `case_shape_unit.py` | 否 | **形状表的单元矩阵 38 项**：在磁盘上造各种 `.lake` 形状后直接调 `artifact_reds()`；另复现「3 个内容模块的合法完整构建恰 64 个目录项」 |
| `case_suffixes.py` | 是 | **形状表的误红一半**：八种真实构建情形产出的全部后缀与形状表对照 |
| `race_probe.py` | 否（只起 `bwrap`） | 沙箱结束与形状表遍历之间有没有时间窗（`measure` 模式；`crowd` 模式只开过一次就停手，没有用于结论） |
| `case_cover.py` | 否（只起 `bwrap`） | README「`/home`、`/root`、`/run`、`/var`、`/tmp` 与整个工作目录盖成空 tmpfs」在第 6、7 步两套挂载下是否成立 |
| `case_shm.py` | 否（只起 `bwrap`） | 沙箱里哪些地方可写、写进去的东西会不会出现在宿主机上 |
| `case_signal3.py` | 是 | **N-4**：各步被 SIGTERM/SIGINT 打断、处理函数里再被打断、残留进程、`tick` 是否停；最后一例（标准错误是满管道）会把运行脚本挂住，见 C-1，本轮是手动停掉的 |
| `case_signal3b.py` | 是 | **N-3** 与 **N-4**：`lean` 工作进程被杀、沙箱顶层 `lake` 被杀、超时与信号同时发生 |
| `case_blocked_stderr.py` | 否 | **C-1**：标准错误阻塞时 `emit()` 与 `on_signal()` 的行为（单元级，带「先写结果行」的对照） |
| `case_green_signal.py` | 是 | **C-2**：读到绿结果行的那一刻立刻发 SIGTERM，看「有绿结果行则退出码为 0」有没有时间窗 |
| `case_control3.py` | 是 | 回归抽查：被审提交自己的 21 个主问题相关骨架用例作为对照；另测 umask 0022/0077/0277 下真实构建会不会被目录模式规则误红 |
| `mutants3.py` | 是 | 我自己的弱化 6 种（Q1–Q6），与作者 `--mutants` 的 28 种不重复 |
| `logs/` | — | 以上各项在本次审阅中的实际输出（扩展名 `.txt`，仓库根 `.gitignore` 忽略 `*.log`），另有依赖目录前后比对 `deps-*.txt` |
