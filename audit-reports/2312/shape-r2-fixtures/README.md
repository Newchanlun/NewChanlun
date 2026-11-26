# #2312 第四片独审 r2（定点复审）的夹具与脚本

被审提交 `8369643028747b172b5a39a52a67bf67c09ab7f0`（上一轮 `1acb400d631e6d4154a3ef4ebb779f7a781e2425`）。
全部只读审阅，没有改被审分支上的任何文件。报告见同目录 `../shape-review-r2.md`。

## 布局

| 位置 | 内容 |
|---|---|
| `tools/gen_r2.py` | 本轮 141 个变体的生成器（六批，期望写进各批的 `EXPECT.tsv`）。`python3 tools/gen_r2.py <输出根>` 重新落盘 |
| `tools/mutants_r2.py` | 本轮自做的 7 种弱化（含对照）：在副本里改一处，用副本自己的自测跑指定骨架用例。`python3 tools/mutants_r2.py all` |
| `tools/one_corpus.py` | 跑单个仓内语料夹具并打印步骤行与 `FM RED` 行（复用 `selftest.py` 的 `Suite`／`corpus_case`） |
| `tools/shp.py`、`cmp.py`、`sweep.py`、`redcheck.py`、`pipe.py` | 上一轮 `shape-r1-fixtures/tools/` 的同名脚本，只把本机绝对路径改到本轮的工作目录与被审检出，逻辑未改 |
| `expect/actual-r2-*.txt` | 本轮六批变体的逐文件实测 |
| `expect/actual-r1-*-rerun.txt` | 上一轮 537 个变体与 `fx/g-green` 在本提交上的重跑实测（与上一轮 `shape-r1-fixtures/expect/actual-*.txt` 直接 `diff`） |
| `expect/sweep-must-green.txt` | 仓内 55 个 must_green 夹具的第 5 步实测（全 GREEN） |
| `expect/mutants-r2.txt` | 7 种弱化的原始输出 |
| `expect/pipeline-*.txt` | 几个流水线夹具的完整输出 |
| `packages-before.txt`、`packages-after.txt` | 共享依赖目录开工与收工的顶层列表与修改时间，`diff` 为空 |

## 变体批（`fx/r2-*`，共 141 个文件）

| 批 | 个数 | 用途 | 结果 |
|---|---|---|---|
| `fx/r2-pos` | 42 | 旧式配置子句的出现位置（`<;>`、`all_goals`、`any_goals`、`repeat`、`try`、`iterate`、嵌套 `by`、`show … from by`、`calc`、`match`、`have := by`、`where`、`suffices`、`let`、`induction`、bullet、`case`／`next`、`conv`、`first`、匿名构造子、`decreasing_by`、绑定器自动参数、结构字段默认证明、`set_option … in`、`namespace`、`mutual`、`#check`、`example`、判别式；核心／Aesop／plausible／Batteries 四种来源） | 42/42 `SHAPE_FORBIDDEN` |
| `fx/r2-ws` | 15 | 记号之间的空白、换行、行注释、块注释、嵌套块注释 | 15/15 `SHAPE_FORBIDDEN` |
| `fx/r2-mix` | 18 | 旧式子句与新式配置项混写在同一条战术里 | 18/18 `SHAPE_FORBIDDEN` |
| `fx/r2-name` | 21 | 名字判据（`simp_config`、`my_config`、`reconfig`、`Config`、`CONFIG`、`config'`、`configs`、`config_`、`«config»`、`«my config»`、`«x.config»`、`X.config`、`_root_.config`、`config.zeta`，以及 Aesop／plausible 写别的名字时的 `SHAPE_PARSE`） | 与 README 判据逐项一致 |
| `fx/r2-fp` | 23 | 新规则的误拒探针（函数应用命名参数、结构实例与模式、类型标注、绑定器默认值、自动参数、新式配置项 11 条、字符串与各类注释、名为 `config` 的局部变量 9 条命令、`@[simps]` 两种） | 命名参数判红（报告 2.1、条件项甲-C1）；其余全 GREEN |
| `fx/r2-native` | 19 | 原 `valConfigItem` 分支改动后的 `native` 回归 | 该红全红，`+kernel`／命名参数 `native` 绿 |
| `fx/r2-lin` | 3 | `linarith (config := …)` 红、`(oracle := …)`／`(transparency := …)` 绿 | 甲-2 的判定前提 |

## 流水线夹具（`fx/ev-*`、`fx/n1-binder-auto`）

| 目录 | 用途 | 实测 |
|---|---|---|
| `fx/ev-linarith-trace` | **甲-2 的证据**：`linarith (oracle := (dbgTrace "FM-R2-LINARITH-ORACLE-RAN" fun _ => …))`，**不跳过第 5 步** | 七步全绿 rc=0，`FM LOG build info: Chan/Thm/A.lean:7:0: FM-R2-LINARITH-ORACLE-RAN` |
| `fx/ev-aesop`、`fx/ev-aesop-simpcfg` | 旧式子句的取值确实在精化期被求值（为复核上一轮「甲-1 修复前的行为」那段记述）。**经自测驱动 `--skip-shape` 跳过第 5 步跑**，否则它们在第 5 步就红 | 标记进构建日志 |
| `fx/ev-plausible`、`fx/ev-congr`、`fx/ev-simp-whole`、`fx/ev-simp-field` | 同类写法在别的库／核心上的表现（同样跳过第 5 步） | 第 6 步 `Could not evaluate the expression`，受限求值器拒非字面量 |
| `fx/n1-binder-auto` | README 标「推测、未实测」的那半句：绑定器自动参数 `(h : n ≤ n := by omega)` | 前六步绿，第 7 步 `ENV_META … probe._auto_1`，推测成立 |

`fx/ev-*` 里凡标「跳过第 5 步」的，都是用自测驱动脚本的旁路（测试设施，不在生产路径上）；
不标的只有 `fx/ev-linarith-trace`，它是在完整七步下测出来的。

## 复现

```sh
source scripts/fm_env.sh
# 第 5 步单测（批目录当作 formal_math 根）
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh python3 tools/cmp.py fx/<批名> -a
# 完整七步
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh python3 -I tools/pipe.py fx/<目录>
# 仓内 must_green 夹具的第 5 步
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh python3 tools/sweep.py must_green/g3/...
# 单个语料夹具的步骤行
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh python3 -I tools/one_corpus.py must_green/known-issue/autoparam-default-proof
# 自做弱化
python3 tools/mutants_r2.py all      # 每种弱化内部自带 flock + guard.sh
```

`tools/*.py` 里的审计程序路径、被审检出与依赖目录是本机绝对路径，换机器要改。依赖目录
`/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages`
全程只读使用（`shp.py` 经 `bwrap --ro-bind`；`pipe.py`／`selftest.py` 交给 `run.py --packages`），
开工收工列表 `diff` 为空。
