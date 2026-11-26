# #2312 第二片（运行骨架）独立复审 r2

- 被审提交：`origin/infra/2312-f-skeleton` @ `1ea21f7206eb2f944d5e0a68dff915508fb83c87`（检出后 `git rev-parse HEAD` 相符）。上一轮被审 `be069d974f8f4539fbc6c087fa3a3e1bbb6736c5`。
- 审阅者：非作者、独立进程、只读。模型 Claude Fable 5.2（`claude-fable-5-2`），会话给定的推理档位参数为 30，没有显示具名档位。没有起子代理。
- 环境：SafeCode Linux，`bwrap` 0.11.1，Lean 4.36.0，Python 3.14.4，6 核。所有调用 `lake`、`lean` 的命令都包在 `flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh` 里，先 `source scripts/fm_env.sh`。
- 范围、已明示前提、阻断口径：沿用上一轮报告（`origin/evidence/2312-skeleton-review` @ `7ce9e02c01698b486ad036fd072f7b621344afde` 的 `audit-reports/2312/skeleton-review-r1.md`）。骨架的四类阻断：被审提交能影响哪个审计二进制被执行或受信代码内容；被审提交能经声明之外的通道使运行退 0 而某一步没按说明执行；退出码契约；说明不实。严重程度按本轮简报的定义标：能拿到退出码 0 或能改变哪个二进制被执行的标高，只影响 1 与 2 的区分、日志可读性或说明措辞的标低。
- 受审文件：`formal_math/verification/runner/` 的 `run.py`、`selftest.py`、`README.md`、`fixtures.tsv`、`selftest-cases/`。`git diff be069d974f..1ea21f7206 -- formal_math/verification/auditor` 为空，环境层没有动。`precheck/` 当黑盒。
- 夹具与日志：同目录 `skeleton-r2-fixtures/`，日志在其中的 `logs/`。

## 一、结论

| 项 | 结果 |
|---|---|
| 上一轮 B-1（输出注入） | 闭合 |
| 上一轮 B-2（输出函数抛异常后退 1） | 闭合 |
| 上一轮 B-3（`lake` 被信号杀死报成判红） | 闭合，留下一条说明比实际宽的问题，单列为 N-3 |
| 新的阻断缺陷 | 4 条：N-1、N-2 按口径标高，N-3、N-4 标低 |
| 非阻断建议 | 11 条 |

**骨架：BLOCK。**

送审主问题（被审提交能否影响哪个审计二进制被执行，或经声明之外的通道影响它的输入）仍然没有被击穿。受信目录与审计二进制的来源、取料、三步沙箱的挂载、模块数与结论的交叉核对、读环境不执行初始化器，这几项本轮改动都没有重新打开。

两条标高的缺陷都能让运行以 0 退出，但影响面都窄，各自在条目里写明：

- N-1 要调用方同时做错两件事（没带 `-I`，且标准错误或标准输出写不出），被审提交单独触发不了。
- N-2 被审提交单独就能触发，但它绕过的是第 6 步里两条纵深检查。要靠它改变任何内容判定，还得伪造某个内容模块的产物，而那是说明里已经声明不防的前提。

四条的修法都小。

## 二、上一轮三条阻断复验

### B-1：闭合

**原夹具。** 上一轮的 `case_inject.py` 原样重跑（`logs/r1_case_inject.txt`）。导入名与公理名里的换行都写成了 `\x0a`，标准输出没有以 `FM RESULT GREEN` 开头的行，被审提交自己的 `protocol()` 核对合规，退出码 1。

**新形状**（`case_output.py`、`case_precheck.py`、`case_usage_inject.sh`）：

| 入口 | 内容 | 结果 |
|---|---|---|
| 导入名 16 种 | `\r`、`\v`、`\f`、U+0085、U+2028、U+2029、ESC、U+202E、U+00A0、U+FEFF、U+E0001、字面的 `\x0a`、600 字符的名字等，后面都跟伪造的结果行 | 全部转义或截断，标准输出每行都以 `FM ` 开头 |
| `IMPORT_CLOSURE` 的说明栏 | `ChanChallenge` 经 `Chan.Defs.D` 间接导入 `Std.«x⏎FM RESULT GREEN…»` | 转义。这一项与下一行的 `ENV_PARTIAL` 源定义名是上一轮没单独跑的两个入口 |
| `ENV_PARTIAL` 的源定义名、`LOCK_UNLISTED` 与 `EXPOSE_SECTION` 的对象栏 | 名字带换行与伪造行 | 转义 |
| 构建日志 | 构建期直接往 `lake` 的标准输出管道写原始字节：`\xff\xfe`、整行 `FM RESULT GREEN`、`\r`、NUL、3000 字符的一行 | 只以 `FM LOG build …` 行出现在标准错误 |
| 预检输出（假预检，自举模式） | 未知红码、对象栏带转义、说明栏带 `\xff`、ESC、U+2028；绿行的 role 栏带 ESC 与 `\r` | 转义一次，没有二次转义 |
| 调用方参数与 git 报错 | 未知开关、仓库路径、`--until` 取值带换行与 ESC | 转义；git 报错里的换行被切成两行 `FM LOG git …` |

**绕过 `emit()` 的路径。** `run.py` 里写这两路的只有 `emit()` 的 `os.write`（第 87 行）和隔离检查那两行 `sys.stderr.write`、`sys.stdout.write`（第 8、9 行，固定文字，问题见 N-1）。子进程只在 `call()` 一处起（第 107 行），它的六个调用点的标准输出与标准错误都接管道，标准输入是 `/dev/null` 或管道，没有子进程继承这两路的描述符。

**残留**（不阻断，建议 1）：`safe()` 把显示为空白的字母与符号当可见字符原样保留，例如 U+3164 韩文填充符、U+2800 盲文空格。对象栏因此可以显示成 `…N.lean:«q FM RESULT GREEN 七步全绿…»` 的样子。按空格切字段的程序不受影响，行首也伪造不了。

### B-2：闭合

**原夹具。** 上一轮的 `repro_blocking.py` 原样重跑（`logs/r1_repro_blocking.txt`）。锁文件 `{"\ud800": "x"}` 与重复键那一例都在第 7 步 `INPUT`，退出码 2，标准输出最后一行 `FM RESULT FAULT env INPUT`，没有回溯。调用方来源的两例（`case_b2_caller.py`）：已存在且非空的非 UTF-8 工作目录 `WORKDIR` 退 2，不存在的非 UTF-8 依赖目录 `PACKAGES` 退 2。

**新形状：**

- `strict_json()` 的 44 种输入直接调用（`case_json_unit.py`）：重复键（含嵌套、转义后相同的键）、`NaN`、`Infinity`、`-Infinity`、五种孤立代理项、原始字节形式的代理项、非 UTF-8、过长编码、BOM、UTF-16、字符串里的原始控制字符、尾随逗号、尾部多余内容、5000 位整数、10 万层嵌套都拒收。
- 整条流水线上的锁文件 8 种（`case_lock.py`）：全部落在 1 或 2，都有结果行，没有回溯。
- 调用方参数另 6 种（`case_b2_caller.py`）：全部退 2 且协议合规。

两处与说明的小出入，不阻断：600 层嵌套的锁文件以 `INTERNAL` 而不是 `INPUT` 退 2（建议 2）；`1e999` 被接受成无穷大（建议 3）。

同一类毛病（输出代码自己抛异常、没有被接住）在本轮新加的隔离检查分支里又出现了一次，后果更重，单列为 N-1。

### B-3：闭合，说明仍比实际宽

**原夹具。** 上一轮的构建期 `kill -KILL 2` 现在报 `FM FAULT build SIGNAL lake 沙箱内进程被信号终止（退出 137）`，退出码 2（`logs/r1_repro_blocking.txt`）。

**新形状**（`case_signal.py`）：

| 构建期做什么 | 结果 |
|---|---|
| `kill -TERM 2`（用别的信号杀 `lake`） | `SIGNAL` 退 2 |
| `kill -KILL -1`（杀掉沙箱里所有进程） | `SIGNAL` 退 2 |
| `kill -KILL 1`、`kill -SEGV 2` | 杀不掉或被忽略，七步全绿 |
| `kill -KILL $PPID`（杀掉正在编译自己的 `lean`） | `BUILD_WFAIL` 退 1，见 N-3 |
| `IO.Process.exit 137`（`lean` 自己以 137 退出） | `BUILD_WFAIL` 退 1。这一种是被审代码自己的行为，判红合理 |

## 三、新的阻断缺陷

### N-1 不带 `-I` 且标准错误或标准输出写不出时，同目录的模块被执行，可以退 0

**类别**：第 4 类（说明不实）、第 3 类（退出码契约）。**严重程度**：按口径标高（能拿到退出码 0）。触发条件全在调用方一侧。

**说明里的陈述**（`runner/README.md`「调用」）：「`run.py` 开头只用内建的 `sys` 查 `sys.flags.isolated`，不满足就写 `FM FAULT prepare NOT_ISOLATED` 退 2，在这之前不导入任何标准库模块（自测 S24）。」「输出与退出码」一节：「`emit()` 是唯一写两路输出的函数，它不抛异常。」

**实际行为**：`run.py:7-10` 用 `sys.stderr.write`、`sys.stdout.write` 各写一行，再 `raise SystemExit(2)`，外面没有任何 `try`。标准错误已关闭时 `sys.stderr` 是 `None`，写不出时 `write` 抛 `OSError`；标准输出已关闭时 `sys.stdout` 是 `None`。本机的 Python 3.14 在处理这个未捕获异常时会从模块搜索路径导入标准库模块。这时不是隔离模式，脚本所在目录排在搜索路径最前面，同目录的同名文件就被执行了：实测先取到的是 `re`，标准输出关闭那一种还有 `traceback`。

**复现**（不调用 `lean`、`lake`、`git`）：

```sh
source scripts/fm_env.sh
bash audit-reports/2312/skeleton-r2-fixtures/case_not_isolated_stderr.sh <被审检出>
```

夹具把被审提交的 `run.py` 逐字节复制到一个临时目录，旁边放 `re.py` 与 `traceback.py`。这两个文件记下自己被执行，往标准输出写一行伪造的绿结果，然后以 0 退出。实际输出（`logs/case_not_isolated_stderr.txt`）：

```
run.py 逐字节等于被审提交那份：5cf75c7e6529f05694da7bfd9eabf10f95cddcfd
$ python3 run.py --repo x                      # 对照：两路输出正常
FM FAULT prepare NOT_ISOLATED - run.py 必须以 python3 -I 运行
FM RESULT FAULT prepare NOT_ISOLATED
rc=2 | 顶替模块被执行：否
$ python3 run.py --repo x 2>&-                 # 标准错误已关闭
FM RESULT GREEN 七步全绿（第 5 步源码形状未安装）
rc=0 | 顶替模块被执行：re,
$ python3 run.py --repo x 2>/dev/full          # 标准错误写不出
FM RESULT GREEN 七步全绿（第 5 步源码形状未安装）
rc=0 | 顶替模块被执行：re,
$ python3 run.py --repo x 2>&1 | true 之类：标准错误是读端已关的管道
FM RESULT GREEN 七步全绿（第 5 步源码形状未安装）
rc=0 | 顶替模块被执行：re,
$ python3 run.py --repo x >&-                  # 标准输出已关闭
FM FAULT prepare NOT_ISOLATED - run.py 必须以 python3 -I 运行
rc=0 | 顶替模块被执行：re,
$ python3 -I run.py --repo x 2>&-              # 对照：带 -I
FM RESULT FAULT prepare USAGE
rc=2 | 顶替模块被执行：否
```

同目录没有任何顶替模块时，这几种状态下的退出码也不是 2（同一份日志末尾）：标准错误或标准输出已关闭退 1，指向 `/dev/full` 退 120。

**实际影响**：要同时满足三件事。调用方没带 `-I`；标准错误或标准输出写不出；脚本所在目录里有别人能放进去的文件，而 `run.py` 本身没被改。被审提交单独做不到，带 `-I` 时没有这个问题。但这条检查存在的唯一用途就是兜住「调用方漏了 `-I`」，说明把它写成无条件成立，自测 S24 也只测了两路输出都正常的情形。

**版本范围**：只在本机的 Python 3.14.4 上测了。别的版本在这条路径上导入哪些模块，我没有环境验证。

**修法**：两行输出各包进 `try … except BaseException`，随后 `import posix; posix._exit(2)`。`posix` 是内建模块，路径上的同名文件顶替不了它；不用 `sys.exit` 是因为解释器收尾时还会再刷一次流。我在副本里按这个改法试过：两路正常、标准错误关闭、标准错误指向 `/dev/full`、标准输出关闭、标准输出指向 `/dev/full`、两路都关，六种状态都退 2，同目录放了 `re.py`、`traceback.py`、`posix.py`、`sys.py` 也都没有被执行。自测 S24 加标准错误关闭、标准输出关闭两例。

### N-2 第 6 步的产物集合核对可以被绕过，产物目录里多出 `.olean` 与符号链接时七步全绿

**类别**：第 2 类（退 0 而第 6 步没按说明执行）、第 4 类。**严重程度**：按口径标高（被审提交单独即可触发，退出码 0）。

**说明里的陈述**（`runner/README.md`「七步」表第 6 行）：「之后核对产物目录：`.olean` 的模块集合恰好等于 git 树数出的内容模块（少了 `NO_ARTIFACT`，多了 `EXTRA_ARTIFACT`），顶层只有内容根、任何层级都没有符号链接（`ARTIFACT_ROOT`）。」

**实际行为**（`run.py:532-539`）有两个口子：

1. 模块名是把相对路径去掉 `.olean` 后把 `/` 换成 `.` 得到的。`Chan/Thm.Ok.olean` 与 `Chan/Thm/Ok.olean` 因此算成同一个名字 `Chan.Thm.Ok`。前者其实是另一个 Lean 模块 `Chan.«Thm.Ok»`，没有源码，核对看不出多了它。
2. `os.walk` 默认吞掉列目录失败。模式 0111 的目录可进入、不可列出，里面的东西不进核对，但按路径照样读得到。

**复现**（真实命令行入口）：

```sh
source scripts/fm_env.sh
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh \
  python3 audit-reports/2312/skeleton-r2-fixtures/case_artifacts_cli.py
```

被审提交在基线上加两个文件：`Chan/Thm/Ok.lean`（一条 `rfl` 定理）和 `ChanExplore/Plant.lean`。后者在构建期执行一段 shell：

```sh
for e in olean olean.server olean.private; do cp $L/Chan/Thm/Ok.$e $L/Chan/Thm.Ok.$e; done
mkdir $L/Chan/Hidden && for e in olean olean.server olean.private; do cp $L/Chan/Thm/Ok.$e $L/Chan/Hidden/Ghost.$e; done &&
ln -s /etc/hostname $L/Chan/Hidden/Link.olean && chmod 111 $L/Chan/Hidden      # L=.lake/build/lib/lean
```

实际输出（`logs/case_artifacts_cli.txt`）：

```
$ /usr/bin/python3 -I …/formal_math/verification/runner/run.py --repo /home/workspace/fm/tmp/review-f2/work/repo \
    --base bf6a0a16219a1ed85e2b803d503b7e0414031ff6 --head 20cf4f040afe624663b01eb9bbff01a1c3524451 \
    --branch proof/review --workdir /home/workspace/fm/tmp/review-f2/work/w-N2-artifacts \
    --packages /home/workspace/fm/tmp/review-f2/work/fake-packages
rc=0
…
FM STEP 6 build GREEN 1.1s 8 个模块都有产物
FM STEP 7 env GREEN 0.4s 8 个模块，0 条锁行
FM RESULT GREEN 七步全绿（第 5 步源码形状未安装）

运行后宿主机上：Chan/Thm.Ok.olean 存在=True；Chan/Hidden 模式=111
os.listdir(Hidden) → PermissionError（os.walk 默认吞掉这个错误，目录内容不进核对）
$ echo 'import Chan.Hidden.Ghost' | LEAN_PATH=<产物目录> lean --stdin → rc=0 ok : 1 + 1 = 2
$ echo 'import Chan.«Thm.Ok»' | LEAN_PATH=<产物目录> lean --stdin → rc=0 ok : 1 + 1 = 2
$ echo 'import Chan.Hidden.Missing' | LEAN_PATH=<产物目录> lean --stdin → rc=1 … does not exist
符号链接：Chan/Hidden/Link.olean -> /etc/hostname
```

两个没有源码的模块按名字都能被 Lean 导入，产物目录里还有一个不在顶层的符号链接，整次运行退 0。

**实际影响**：

- 多出来的模块只有被某个产物导入时才会进第 7 步的环境。诚实构建产出的 `.olean` 只导入通过了第 4 步头部规则的模块，所以这两种绕过单独不会改变任何内容判定。要用上它，还得伪造某个内容模块的产物，那是说明「不防什么」已经声明的前提。
- 「顶层只许内容根」不受影响。顶层用 `os.listdir` 按名字查，列不了顶层会抛异常退 2，所以 `Init` 之类的库根仍然放不进去。
- 受影响的是表里写明的另外两条判据：多出的 `.olean`，任何层级的符号链接。它们只对蓄意构造有意义，而蓄意构造绕得过。

**修法**（二选一）：

- 改代码。`os.walk` 加 `onerror`，列不了就 `Fault`；产物目录下每个目录名须合模块名文法，文件名须是「模块名文法 + 已知后缀」，否则 `ARTIFACT_ROOT`。自测加这两例。
- 改说明。把这两条写成尽力而为的形状检查，不承担对蓄意构造的保证。

### N-3 信号归类只覆盖沙箱的顶层进程，`lean` 工作进程被杀仍判红退 1

**类别**：第 4 类、第 3 类。**严重程度**：低（只影响 1 与 2 的区分）。

**说明里的陈述**：「七步」表第 6 行的无法判定码「`SIGNAL`（沙箱内进程被信号终止）」；「沙箱布局」一节「沙箱里的进程被信号杀死时 `bwrap` 以 `128+n` 退出：第 4、6、7 步（含探针）凡是退出码 ≥128 或为负，一律 `SIGNAL` 退 2，不当作判红。」

**实际行为**：`bwrap` 只转出它直接起的那个进程的退出状态。第 6 步里被杀的若是 `lean` 工作进程，`lake` 把它记成一条构建错误后自己以 1 退出，运行脚本报 `BUILD_WFAIL`。

```
$ /usr/bin/python3 -I …/runner/run.py --repo /home/workspace/fm/tmp/review-f2/work/repo \
    --base bf6a0a16219a1ed85e2b803d503b7e0414031ff6 --head 4fbe999309b7e5162d296ee5e9af9bf606ba0619 \
    --branch proof/review --workdir /home/workspace/fm/tmp/review-f2/work/w-G-kill-own-lean \
    --packages /home/workspace/fm/tmp/review-f2/work/fake-packages
rc=1
FM RED build BUILD_WFAIL formal_math/lakefile.toml lake build --wfail 退出 1
FM STEP 6 build RED 0.9s -
FM RESULT RED 第 6 步 build 判红，后面的步骤没有跑
--- stderr
FM LOG build error: Lean exited with code 137
```

夹具 `case_signal.py` 的 `G-kill-own-lean`：`ChanExplore/Kill.lean` 在构建期执行 `kill -KILL $PPID`（`logs/case_signal.txt`）。

**后果**：上一轮 B-3 担心的是「环境故障被报成对被审提交的判红」。宿主机内存不足时，内核更可能杀的是占内存最多的 `lean` 工作进程，而不是 `lake`，那种情形现在仍然退 1。不会落成 0。

**修法**：运行脚本从外面分不清「`lean` 被内核杀掉」与「被审代码自己搞死 `lean`」，构建日志又是被审方可写的，所以我建议只改说明。把两处写成：只有沙箱的顶层进程（`lake`、审计程序、探针）被信号终止才归入 `SIGNAL`；`lean` 工作进程被杀时 `lake` 以 1 退出，仍报 `BUILD_WFAIL`。

### N-4 结果行「恒为唯一且在最后」在两条路径上不成立

**类别**：第 4 类。**严重程度**：低（最后一行与退出码仍然正确）。

**说明里的陈述**（「输出与退出码」）：「最后一行恒为唯一的 `FM RESULT`，状态与退出码一一对应。」「七步」表后：「任何意外异常（含输出函数自身的失败）都归入 `INTERNAL`，退 2，并照样写出结果行 `FM RESULT FAULT`。」

**实际行为**：

1. **输出一度写不出、后来又写得出。** `run.py:708-711` 先写 `FM RESULT GREEN`，再查前面有没有哪一行没写出去，有就由 `fault()` 再写一行 `FM RESULT FAULT`。标准输出是非阻塞描述符且一度写满时，前几行因 `EAGAIN` 丢掉，后面两行都写了出去（`case_stream.py` 的 T1，真实命令行入口，`logs/case_stream.txt`）：

   ```
   rc=2
   FM STEP 3 auditor GREEN 8.5s binary=… sha256=52d41ce1…
   FM STEP 4 headers GREEN 0.1s 7 个文件头
   FM STEP 5 shape GREEN 0.0s SHAPE 未安装：源码形状门归第四片，本次的绿不含这一层
   FM STEP 6 build GREEN 1.0s 7 个模块都有产物
   FM STEP 7 env GREEN 0.4s 7 个模块，0 条锁行
   FM RESULT GREEN 七步全绿（第 5 步源码形状未安装）
   FM RESULT FAULT output OUTPUT
   --- stderr
   FM FAULT output OUTPUT stdout 输出写不出：BlockingIOError
   ```

   只取最后一行的消费者得到的是对的。按「有没有一行 `FM RESULT GREEN`」取结论的会被骗。

2. **SIGINT。** `KeyboardInterrupt` 不是 `Exception`，`main` 的两层 `except` 都接不住，由 `__main__` 的兜底退 2。标准输出停在 `FM STEP 5 …`，没有 `FM FAULT`，也没有 `FM RESULT`（T8）。

SIGTERM 按默认处置直接结束，退出状态是被信号终止，同样没有结果行（T9）。这两种信号下沙箱里的进程都随 `--die-with-parent` 结束：`.lake/tick` 不再增长，没有残留进程。

其它输出失败路径与说明一致：标准输出已关闭或指向 `/dev/full` 时，绿退 2、红退 1，三路全关退 2，标准错误已关闭不影响结论（T2 至 T7）。

**修法**：写 `FM RESULT GREEN` 之前先查 `state["output"]`；`main` 接住 `KeyboardInterrupt` 后走 `fault()`；说明里写明被 SIGTERM 结束时没有结果行。

## 四、非阻断建议

1. **`safe()` 原样保留显示为空白的字母与符号。** U+3164、U+115F、U+1160、U+FFA0（类别 Lo）与 U+2800（类别 So）按「字母、符号」放行，在不该有空格的对象栏里看起来就是空格。实测 U+3164、U+2800（`logs/case_output.txt` 的 O1、O3）。被审提交自测的 `printable()` 用的是同一条规则，所以测不出。建议把这几个码点列入转义。
2. **深嵌套的 JSON 以 `INTERNAL` 而不是 `INPUT` 退 2。** `no_surrogates()` 在 `strict_json()` 的 `try` 之外递归，600 层嵌套的锁文件在这里抛 `RecursionError`（`logs/case_lock.txt` 的 `L-nest600`）。退出码与结果行都对，只是故障码与说明的「锁文件不合格退 2（`INPUT`）」不符。把那次调用挪进 `try` 即可。
3. **`1e999` 被接受成无穷大。** `parse_constant` 只管 `NaN`、`Infinity` 字面量，浮点溢出走 `parse_float`。现在没有任何地方用到 JSON 里的浮点数，没有后果；要名副其实可以加 `parse_float` 拒非有限值。
4. **自测测不出的弱化有 10 种**（第六节表）。最值得补的四种：标准输出没写全时绿仍退 0（R4，说明里「绿的结论要求全部标准输出都写出去了」这句没有任何用例）；「顶层只许内容根」与「任何层级不许符号链接」各自单独去掉（R16、R15，S20 的三样东西会互相顶替着报出同一组红码）；第 4、7 步审计程序与探针的信号死亡（R5b）；依赖目录缺包（R8）。
5. **第 6 步两处显示不准。** 因 `EXTRA_ARTIFACT`、`ARTIFACT_ROOT`、`NO_ARTIFACT` 判红时，步骤行的备注仍是「N 个模块都有产物」。`EXTRA_ARTIFACT` 的路径栏是按模块名重新拼的，`Chan.Evil/X.olean` 显示成 `Chan/Evil/X.olean`（`logs/case_artifacts.txt` 的 A4）。
6. **构建日志整个捕获进内存，步骤结束才写出。** 4 小时的构建期间两路都没有任何输出。行数不设上限。每行截到 400 字符，长的 Lean 报错行会被截掉后半（实测 3000 字符的一行只留前 400）。给 #2315：CI 上看不到构建进度。
7. **说明的几处细节。**
   - 「与设计备忘的偏离」没有列本轮新增的 `EXTRA_ARTIFACT`、`CONTENT_ENCODING`、必须带 `-I`、`SIGNAL` 归类。
   - 「13 个环境层夹具在第 7 步判出旧期望的码；另 3 个」应为 12 个与 4 个。`fixtures.tsv` 里环境层 16 行，判红步骤是 `env` 的 12 行；括号里列的本来就是 4 个夹具。这句上一轮就有，我上一轮没有查出来。
   - 「之后各步不再读被审工作区里的任何文件来决定输入」：第 3 步读了 `audited/lean-toolchain`。它是基线那份的副本，此时被审代码还没运行过，没有后果，但句子说满了。
   - 转义规则没写 `\UNNNNNNNN` 这种形式；`FAULT` 的步骤行没有备注栏。
8. **`lean --version` 那次调用没有给环境。** `run.py:376` 继承调用方的全部环境变量，其余子进程都给了最小环境。执行的是工具链里的二进制，没有后果；建议与别处一致。
9. **给 #2315：`-I` 是 `run.py` 自己兜不住的。** 不带 `-I` 时若 `PYTHONPATH` 指向别人能写的目录，解释器启动阶段就会导入那里的 `sitecustomize`，发生在 `run.py` 第一行之前（`logs/case_isolated.txt`）。另外 `python3 -I -m run` 由解释器自己以 1 退出（找不到模块），只支持按脚本路径调用。
10. **上一轮建议 8 仍未做**（审计程序里 `importModules` 不在 `try` 内）。作者已声明；`auditor/` 本轮没有改动，运行脚本那一侧的处理也没变，我没有重测。
11. **异常消息里的非 UTF-8 路径显示成 `\x5cudcff`。** Python 先把那个字节写成字面的 `\udcff`，`safe()` 再把反斜杠转义一次（`logs/case_b2_caller.txt` 第三例）。只影响可读性。

## 五、核实正确的部分

1. **输出协议。** 带 `-I` 时，本轮夹具里用被审提交自己的 `protocol()` 核对过的 82 次运行（整条流水线或 `--until` 截断）全部合规：标准输出每行都是五种 `FM` 行之一，标准错误每行都是 `FM FAULT` 或 `FM LOG`，恰好一行结果行且在最后。不合规的只有 N-4 的两条路径。两路合流时也成立：`FM LOG` 行带固定前缀，`fault()` 先写标准错误再写标准输出。说明「不防什么」里写了不要合流后按行解读。
2. **「进入输出的外来片段」清单。** 说明列的 11 类之外，我找到并实测了这些入口：预检绿行的 role 栏、git 的标准错误（含回显的仓库路径）、`USAGE` 故障回显的参数、`BAD_REV` 回显的提交参数、第 3 步备注里的工作目录路径、`bwrap` 与工具链探针的标准错误。它们都经 `emit()`，没有漏网的。清单可以补上这几项，但不构成缺口。
3. **严格 JSON 与审计程序输出的校验。** 行形状逐条读过：结果行恰 4 项且在最后，发现行恰 6 项且全是字符串，头部记录恰 5 项且逐项查类型（`type(x) is int`，布尔值与浮点数冒充不了），锁行恰 4 项，重复的头部记录与重复的声明名都退 2，第 7 步发现行的门号只收 `3` 与 `15`。没有行数与总大小的上限，只受内存限制。
4. **预检输出先还原再转义。** 预检把反斜杠也写成 `\x5c`，所以还原是它的精确逆运算，7 组往返一致（`logs/case_json_unit.txt`）。预检红行的说明栏里没有被审方可控的自由文字：唯一带路径的「与 … 只差大小写」只在路径已过 ASCII 文法之后才产生。
5. **第 1 步的转出**（`case_precheck.py`，不调用 `lean`）。真预检的 11 个规则码（`TREE_FORM`、`EMPTY_TREE`、`MODE`、`LAKE_FILE`、`PATH_GRAMMAR`、`TOP_LEVEL`、`CONTENT_SHAPE`、`BRANCH_ROLE`、`PATH_SCOPE`、`TRUST_UNAPPROVED`、`TRUSTED_DRIFT`）：运行脚本的红码集合与直跑预检逐例相同，退 1。故障 `NOT_ANCESTOR`、`BASE_FORM` 退 2（`PRECHECK_EXIT`）。假预检 18 种：16 种不合规输出全部退 2（绿行两条、提交名不符、绿行后多一行、没有输出、没有换行结尾、退 0 却是红行、退 1 却是绿行、红行夹杂项、红码小写、缺说明栏、空行、红绿混排、退 2 带红行、退 3、被信号杀死等），未知红码原样转出退 1，合规绿行通过。
6. **取料的新增面**（`case_fetch.py`，`--until 2`）。依赖目录缺包、包名是普通文件：`PACKAGES` 退 2，发生在建受信目录之前。基线清单重复键、包名带路径穿越或换行、`packages` 不是数组、不是对象、不是 UTF-8、缺键：`INPUT` 退 2。umask 取 000、077、777 时目录模式都是 0700 或 0755，文件 0644。
7. **产物集合核对不误判合法构建。** 合法构建的产物目录里，每个模块有 `.olean`、`.olean.server`、`.olean.private`、`.ilean`、`.ir`、`.ir.sig` 六个文件与各自的 `.hash`，另有一个 `.trace`，只有 `.olean` 参与比对；`.lake` 顶层只有 `build` 与 `packages`。伴生文件多出、名为 `X.olean` 的目录、产物目录之外的任何东西（`.lake/build/lib/extra/Init/…`、`.lake/link`、`.lake/build/bin/fm_audit`）都不影响结论，第 7 步也不读它们。FIFO、顶层的 `chan.olean`、没有源码的 `ChanDyn.olean` 判红。目录可列出的常规情形下，符号链接两条也各自单独成立：把 `lib/lean` 换成符号链接判 `ARTIFACT_ROOT`（A8）；只在深处放一个文件符号链接与一个目录符号链接、别的都不动，判 `ARTIFACT_ROOT` 两条（A9）。以上见 `logs/case_artifacts.txt`。
8. **隔离检查在两路输出正常时。** 14 种启动方式（`logs/case_isolated.txt`）：不带 `-I`、`-E -s`、`-P`、`PYTHONSAFEPATH=1`、不带 `-I` 的 `-m run` 都是 `NOT_ISOLATED` 退 2，同目录的 `json.py`、`os.py`、`re.py` 等 9 个顶替模块都没有被执行。带 `-I` 时，`PYTHONPATH`、`PYTHONSTARTUP`、`PYTHONHOME`、经符号链接运行（链接所在目录有顶替模块）、相对路径运行、脚本从标准输入读，都正常走到参数检查，顶替模块没有被执行。
9. **回归。**
   - 被审提交骨架自测对照 42/42（`logs/selftest_skeleton_control.txt`）。其中与送审主问题有关的 S3（配置取自基线、执行的是受信目录里的审计二进制、假 `main` 没跑）、S4、S5a–e、S7、S13、S16、S17、S22 都通过。
   - 第 4 步的挂载表另写了探针（`case_step4_sandbox.py`，用被审 `run.py` 自己的 `sandbox()`）：被审工作区、受信目录、工具链只读，工作目录其余部分不可见，只有回环网卡，环境变量只有 `HOME`、`LANG`、`PATH`、`PWD`、`TMPDIR`。
   - `sandbox()` 相对上一轮的改动只有三处：参数编码改用 `os.fsencode`、输出改为捕获、加了信号判定。挂载清单没有变。
10. **说明里的数字。** `fixtures.tsv` 252 行，八类归属的夹具数、必红必绿分布、新入口实测分布与汇总表逐格相符。归第四片的 76 个必红夹具里 24 个现为绿。`TOP_LEVEL` 共 22 行（20 个 `r4-p*` 加 `g15/bridge`、`g15/r2-g6-bridge-subdir`）。九个环境层红码都有夹具在第 7 步判出。有期望的语料 225 例加骨架 42 例，合计 267，与主控读数一致。作者弱化清单恰 18 种。只有建议 7 的那一处计数不对。
11. **「未搬的源码层规则」与「旧夹具归属」。** 与 `fixtures.tsv` 的 `must_red/g15/no-expose` 一行、上一轮的实测一致。

## 六、弱化测试结果

作者的 18 种（`selftest.py --mutants`）主控已跑，我没有重跑。我逐条读了清单：没有依赖目录可写的弱化，各种弱化下沙箱的根仍是只读，依赖目录仍是只读挂载。

我另做了 17 种（`mutants2.py`，`logs/mutants2.txt`），在被审树的副本里改一处，用副本自己的自测跑。标「全量」的跑了全部 42 个骨架用例，其余只跑了相关用例；语料用例都没有跑。

| 弱化 | 跑的用例 | 结果 |
|---|---|---|
| R0 不改（对照） | 全量 | 42/42 |
| R1 `emit()` 对最后一栏是字符串时跳过 `safe()` | E1、E2、E3、E8、E10 | 抓到（E1、E2） |
| R5a 信号判定阈值改成 `>= 138` | S18 | 抓到 |
| R6 `fault()` 不写 `FM RESULT FAULT` 行 | S8、S11、S13、E4 | 抓到（4 个全红） |
| R10 子进程日志原样透传到标准错误 | E10、S17 | 抓到 |
| R11 `main` 不再兜住意外异常 | E13 | 抓到 |
| R12 严格 JSON 不拒 `NaN` | E7 | 抓到 |
| R13 判红时结果行写成 `GREEN` | S6a | 抓到 |
| R2 `strict_json` 接受重复键 | 全量 | **没抓到**（E5 的重复键同时是孤立代理项，另一道检查替它报了） |
| R3 产物目录本身是或经由符号链接时不判 `ARTIFACT_ROOT` | 全量 | **没抓到** |
| R4 绿的结论不再要求标准输出都写出去了 | 全量 | **没抓到** |
| R5b 信号判定只对第 6 步构建生效 | 全量 | **没抓到** |
| R7 JSON 不要求合法 UTF-8 | 全量 | **没抓到** |
| R8 不核对依赖目录里有没有基线清单的包 | 全量 | **没抓到** |
| R9 `.olean` 不要求是文件 | S20、S21 | **没抓到** |
| R14 建目录后不 `chmod` | 全量 | **没抓到** |
| R15 只去掉「任何层级不许符号链接」 | 全量 | **没抓到** |
| R16 只去掉「顶层只许内容根」 | 全量 | **没抓到** |

抓到 7 种，没抓到 10 种。没抓到的 10 种里，R5b 改掉的性质（审计程序与探针的信号死亡）我没有造出样本，只读了代码；其余 9 种改掉的性质我都另行实测过在被审提交上成立（第二、五节），其中 R9、R15 涉及的两条判据另有 N-2 的绕过。缺的是自测。

## 七、依赖目录前后比对

共享依赖目录 `/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages`。

- 开工时（跑任何东西之前）与收工时（全部运行结束之后）各记一次 `stat` 与 `ls -la --time-style=full-iso`，两份逐字节相同（`logs/deps-before.txt`、`logs/deps-after.txt`）。
- 顶层目录自身的修改时间仍是 2026-11-26 08:42:22.839258931 +0800，也就是上一轮报告第九节记下的那一次。九个包目录的修改时间都在 2026-11-24。
- `find <依赖目录> -newer <开工时的记录文件>` 列出 0 项。

本轮没有任何往依赖目录写的试验。我自己写的夹具全部用 lite 基线配自建的空假依赖目录。用到共享依赖目录的只有三处，都是只读挂载：上一轮两个夹具的重跑；被审提交骨架自测的对照；`mutants2.py` 在副本里跑骨架自测时的非 lite 用例 S1、S2、S3、S10。`mutants2.py` 里没有任何改沙箱挂载的弱化。

## 八、没覆盖的部分

- 全量自测 267 例没有重跑。骨架 42 例跑了对照；语料 225 例本轮没有跑，汇总表只核了与 `fixtures.tsv` 的算术一致。
- 作者的 `--mutants` 18 种、真实仓库的完整流水线，都没有重跑，以主控读数为准。
- N-1 只在 Python 3.14.4 上测了。
- 超时路径只看了对照里的 S19 通过，没有另造样本。第 4、7 步审计程序被信号杀死没有造出样本，只读了代码：三步共用同一个 `sandbox()`，判定在同一处。
- 第 7 步的挂载表靠对照里的 S22，没有另写探针。
- 非阻塞的标准输出只测了管道一种。
- 自举模式只在假预检的测试里用过。
- 我自己的弱化大多只跑了骨架用例；标了用例子集的那几种只说明那几个用例的结果。
- 第一片预检、`auditor/`、CI 工作流、同目录待删的旧门禁代码，按范围没有审。
- 畸形 `.olean` 对审计进程的影响、内核层面的沙箱逃逸、SHA-256 对象格式的仓库、大小写不敏感的文件系统、macOS，都没有测。

---

VERDICT-骨架: BLOCK（范围：`formal_math/verification/runner/` 的 `run.py`、`selftest.py`、`README.md`、`fixtures.tsv`、`selftest-cases/`，提交 `1ea21f7206eb2f944d5e0a68dff915508fb83c87`。新阻断 4 条：N-1 属第 4、3 类，N-2 属第 2、4 类，按口径标高；N-3 属第 4、3 类，N-4 属第 4 类，标低。与上一轮报告合起来对 `runner/` 在该提交上的整体判断：上一轮的 B-1、B-2、B-3 均已闭合，送审主问题两轮都没有被击穿，环境层搬家维持上一轮的 PASS 且本轮未改动；`runner/` 仍不能放行，原因是本轮新增的隔离检查与产物集合核对各有一处与说明不符并能退 0，另有两处说明比实际宽。）
