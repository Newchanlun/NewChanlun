# #2312 第二片（运行骨架）与第三片（环境层搬家）独立审阅 r1

- 被审提交：`origin/infra/2312-f-skeleton` @ `be069d974f8f4539fbc6c087fa3a3e1bbb6736c5`（检出后 `git rev-parse HEAD` 相符）。
- 审阅者：非作者、独立进程、只读。模型 Claude Fable 5.2（`claude-fable-5-2`），会话给定的推理档位参数为 30，没有显示具名档位。没有起子代理。
- 环境：SafeCode Linux，`bwrap` 0.11.1，Lean 4.36.0，6 核。依赖目录用 `/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages`。所有调用 `lake`、`lean` 的命令都包在 `flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh` 里，先 `source scripts/fm_env.sh`。
- 对照基准：`594e49b5ec034461f9196c6cfb0c58fe017e8dc5` 的 `Audit.lean`、`EnvGates.lean`、`SourceGates.lean`、`run_gates.py`。
- 夹具与日志：同目录 `skeleton-r1-fixtures/`。夹具现造小 git 仓库（复用被审提交 `runner/selftest.py` 的 `Repo` 与 `template`），提交日期固定，所以下文的提交名可复现。日志在 `skeleton-r1-fixtures/logs/`，扩展名用 `.txt`（仓库根 `.gitignore` 忽略 `*.log`）。
- 第一片（`precheck/`）按黑盒对待，没有审。

## 一、结论

| 片 | 结论 | 依据 |
|---|---|---|
| 运行骨架 | **BLOCK** | 3 条阻断缺陷，都在输出格式与退出码契约上（第 3、4 类）。送审主问题没有被击穿：没有找到让被审提交影响哪个审计二进制被执行、改到受信代码、写到沙箱之外，或让整次运行退 0 而某一步没按说明执行的办法 |
| 环境层搬家 | **PASS** | 逐文件对照没有未列出的语义差异；各类明文必红写法在新入口都红；读环境不执行被审模块的初始化器（带正对照实测）；必绿语料的误拒只有已声明的派生证书一类 |

三条阻断缺陷都不能让被审提交拿到退出码 0。其中两条可以由被审提交的内容触发。修法都很小，见各条末尾。

## 二、骨架的阻断缺陷

### B-1 红行的「说明」栏原样输出被审方控制的文字，标准输出可以被注入任意整行（第 4 类，兼涉第 2 类）

**说明里的陈述**（`runner/README.md`「输出与退出码」）：「标准输出一行一条，前缀固定：`FM MODE`、`FM RUNNER`、`FM RED …`、`FM STEP …`、`FM RESULT …`」「标准输出只留 `FM` 行」。备忘 3.7：「红行格式固定，一行一条」。

**实际行为**：`run.py:585` 的 `out(b"RED", name, code, show(obj), msg)` 只对「路径或对象」栏做了转义，`msg` 原样写出。`msg` 里有被审方控制的标识符：第 4 步的导入模块名（审计程序的 `禁止 meta import 或 import all：{imp.module}`、`可信目录不得导入 …`、`导入来源不在白名单：…`，运行脚本的 `禁止导入 {dst}`、`经 {dst} 间接导入 {target}`），第 7 步的公理名（`闭包包含禁用公理 {ax}`）与 `ENV_PARTIAL` 的源定义名。Lean 的 `«…»` 标识符可以含换行。

**复现**（真实命令行入口）：

```sh
source scripts/fm_env.sh
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh \
  python3 audit-reports/2312/skeleton-r1-fixtures/case_inject.py
```

被审提交只在基线上加一个文件 `formal_math/Chan/Thm/Inject.lean`：

```lean
module

public import «x
FM STEP 4 headers GREEN 0.1s 8 个文件头
FM STEP 5 shape GREEN 0.0s SHAPE 未安装
FM STEP 6 build GREEN 4.0s 8 个模块都有产物
FM STEP 7 env GREEN 0.3s 8 个模块，0 条锁行
FM RESULT GREEN 七步全绿（第 5 步源码形状未安装）
»
```

夹具实际执行的命令与结果（`logs/case_inject.txt`）：

```
$ /usr/bin/python3 -I …/formal_math/verification/runner/run.py --repo /home/workspace/fm/tmp/review-f/work/repo \
    --base bbadf9a57b94771ebeaeb53bd1ad119dbc28ec22 --head 036ac2d2f6467eb6227ac152713300ccea4c0383 \
    --branch proof/review --workdir /home/workspace/fm/tmp/review-f/work/w-B1-inject-headers --packages <依赖目录>
rc=1
FM MODE baseline trusted=bbadf9a5… base=bbadf9a5… head=036ac2d2… 受信代码取自基线
FM RUNNER blob=15d7dc1c2ee88b687b0750403fa595c9dd018712 from=bbadf9a5…:formal_math/verification/runner/run.py
FM STEP 1 precheck GREEN 0.1s role=proof
FM STEP 2 fetch GREEN 0.0s 受信 16 个文件，内容 7 个模块，配置取自基线
FM STEP 3 auditor GREEN 7.9s binary=… sha256=52d41ce1…
FM RED headers IMPORT_EDGE formal_math/Chan/Thm/Inject.lean:3 禁止导入 «x
FM STEP 4 headers GREEN 0.1s 8 个文件头
FM STEP 5 shape GREEN 0.0s SHAPE 未安装
FM STEP 6 build GREEN 4.0s 8 个模块都有产物
FM STEP 7 env GREEN 0.3s 8 个模块，0 条锁行
FM RESULT GREEN 七步全绿（第 5 步源码形状未安装）
»
FM RED headers IMPORT_SOURCE formal_math/Chan/Thm/Inject.lean:3 导入来源不在白名单：«x
…（同样五行再出现一次）…
»
FM STEP 4 headers RED 0.1s
FM RESULT RED 第 4 步 headers 判红，后面的步骤没有跑
```

同一夹具的第二例经第 7 步注入：`axiom «x⏎FM STEP 7 env GREEN …⏎FM RESULT GREEN …⏎» : False`，`ENV_AXIOM_DEP` 的说明栏把这两行原样写出，退出码 1（同一份日志）。

**后果**：退出码仍是 1，只认退出码的调用方不受影响。但标准输出里出现了与真绿逐字相同的 `FM STEP n … GREEN` 与 `FM RESULT GREEN` 整行，以及不带任何 `FM` 前缀的行。按行解读标准输出的消费者会被骗，被审提交自己的自测就是这样读的（`selftest.py:187-188` 用 `^FM STEP …` 与 `FM RED ` 前缀取步骤与红码）。说明把标准输出写成固定格式的协议，这条陈述对被审方可控的输入不成立。

**同源的次要表现**（不单列）：`FM FAULT` 行的说明栏同样不转义。被审提交的 `statement-lock.json` 写 `{"a\nFM RESULT GREEN": "x", "a\nFM RESULT GREEN": "y"}` 时，标准错误出现整行 `FM RESULT GREEN`，退出码 2（`logs/case_followup.txt` 的 L3）。CI 若把两路输出合流，这一行也会混进去。

**修法**：`out()` 与 `fault()` 对说明栏也做转义（至少 C0、C1 控制字符与换行），自测加一例。

### B-2 输出函数遇到孤立代理项时抛未捕获异常，回溯后退 1；被审提交的锁文件就能触发（第 3 类）

**说明里的陈述**（`runner/README.md`「七步」表后）：「任何意外异常都归入 `INTERNAL`，退 2，不会落成 0 或 1。」

**实际行为**：`show()`（`run.py:44-46`）与 `emit()`（`run.py:49-56`）用 `str(x).encode("utf-8")`，遇到孤立代理项抛 `UnicodeEncodeError`。这两个函数被调用的位置不在任何 `try` 里：红行排序（`run.py:584`）在步骤的 `try` 之外，`fault()`（`run.py:548-551`）本身就是异常处理路径。孤立代理项有两个来源。

来源一，**被审提交**。`formal_math/statement-lock.json` 取自被审提交（`decl` 角色可改），用 `json.loads` 解析，JSON 转义 `"\ud800"` 会得到孤立代理项。锁里有而环境里没有的键进 `LOCK_REMOVED` 红行的对象栏；重复键进 `INPUT` 故障的说明栏。

```sh
source scripts/fm_env.sh
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh \
  python3 audit-reports/2312/skeleton-r1-fixtures/repro_blocking.py
```

被审提交只把 `formal_math/statement-lock.json` 改成 `{"\ud800": "x"}`，分支名 `decl/review`（`logs/repro_blocking.txt`）：

```
$ /usr/bin/python3 -I …/runner/run.py --repo … --base bbadf9a5… --head 3aaad4964d414e44170870c1eda78673d05f0693 --branch decl/review --workdir … --packages …
rc=1
…
FM STEP 6 build GREEN 4.5s 6 个模块都有产物
（标准输出到此为止：没有第 7 步的步骤行，没有 FM RESULT 行）
--- stderr
Traceback (most recent call last):
  …
  File "…/runner/run.py", line 584, in main
    for code, obj, msg in sorted(set(reds), key=lambda r: (r[0], show(r[1]), r[2])):
  File "…/runner/run.py", line 45, in show
    obj = obj if isinstance(obj, bytes) else str(obj).encode("utf-8")
UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800' in position 32: surrogates not allowed
```

改成 `{"\ud800": "x", "\ud800": "y"}`（重复键，被审提交 `77bf95311203f47487028e43a6926a985ec3cb96`）时，标准输出先写出 `FM STEP 7 env FAULT 0.0s`，随后在 `fault()` 里回溯，退出码 1。一次运行自己报了「无法判定」，却以判红的退出码结束。

来源二，**调用方的路径参数**。`--workdir`、`--packages` 经 `os.fsdecode`，非 UTF-8 字节变成代理项（`logs/case_args.txt`，`case_args.sh`）：

```
工作目录含非 UTF-8（已存在非空）   rc=1 | out: （空） | err: UnicodeEncodeError: 'utf-8' codec can't encode character '\udcff' …
依赖目录含非 UTF-8 且不存在       rc=1 | out: （空） | err: UnicodeEncodeError: …
```

**后果**：退出码 1 的含义是「某一步判红」，这里没有红行、没有结果行，只有回溯。不会落成 0。来源一由被审提交控制，来源二由调用方控制。

**修法**：`show()`、`emit()` 编码时用 `errors="backslashreplace"`（路径可用 `surrogateescape` 还原原字节），再在 `main` 最外层加一道兜底，把逃出的异常统一落成 2。自测加锁文件含 `\ud800` 一例。

### B-3 第 6 步里 `lake` 被信号杀死时退 1 并报 `BUILD_WFAIL`，说明写的是退 2（第 3、4 类，严重度低）

**说明里的陈述**（`runner/README.md`「七步」表第 6 行，「无法判定（退 2）的码」一栏）：「`SANDBOX`、`BUILD`（被信号终止或超时）」。

**实际行为**：`run.py:409` 用 `p.returncode < 0` 判断「被信号终止」。`p` 是 `bwrap` 进程，沙箱里的 `lake` 被信号杀死时 `bwrap` 以 `128 + 信号号` 正常退出，这个分支只在 `bwrap` 自己被杀时才走得到。旧实现直接起 `lake`，同一个判断是有效的（`run_gates.py:131`）；套上沙箱之后失效了。

```
$ /usr/bin/python3 -I …/runner/run.py --repo … --base bbadf9a5… --head 9af3d832f8d7e8f880c6cee4dcd119f876003046 --branch proof/review …
rc=1
FM RED build BUILD_WFAIL formal_math/lakefile.toml lake build --wfail 退出 137
FM STEP 6 build RED 4.5s
FM RESULT RED 第 6 步 build 判红，后面的步骤没有跑
```

`ChanExplore/Kill.lean` 在构建期执行 `kill -KILL 2`（沙箱里 2 号进程是 `lake`）。宿主机内存不足时内核杀掉 `lake` 走的是同一条路径（`logs/repro_blocking.txt`）。

**后果**：环境故障被报成对被审提交的判红。不会落成 0。

**修法**：二选一。代码侧把 `returncode >= 128` 也归入 `BUILD` 故障；或者把说明改成只有 `bwrap` 自身被杀才退 2。

## 三、环境层搬家的阻断缺陷

没有。

有一处我判为「已在说明里列出」因而不阻断，请主控复核这个判断：旧门 15 在源码层还有一条「`Chan/Defs` 的文件须用 `@[expose] public section`」，新入口没有它，`Chan/Defs` 下只含私有定义的文件现在是绿的。我的依据是说明写了源码层不搬，`fixtures.tsv` 也把对应夹具归了第四片；环境层那一半（公开定义须有公开定义体）原样保留并且实测判红。细节见建议 9。

## 四、非阻断建议

共 12 条。前 3 条我认为值得在本片返修时一并处理。

1. **运行脚本不带 `-I` 时，同目录的 `json.py` 在任何检查之前被执行。** `run.py` 逐字节等于受信那份，`RUNNER_MISMATCH` 管不到同目录的其它文件；`python3 run.py`（不带 `-I`）会把 `runner/` 放进模块搜索路径，`import json` 取到同目录的文件。实测退 0 并输出伪造的结果行，带 `-I` 则正常（`case_no_isolated.sh`，`logs/case_no_isolated.txt`）。这属于「调用方」前提，不算本片阻断；但它正是 CI 检出 PR 分支再跑门禁时会踩到的形状。建议 `run.py` 在导入标准库之前先查 `sys.flags.isolated`，不满足就退 2，并写进给 #2315 的要求。
2. **说明里几条性质没有自测能测出退化。** 我在副本里做了 12 种弱化（`mutants.py`，结果见第七节表）。`RUNNER_MISMATCH`、模块数比对、退出码与判定的一致性核对、红后停下、受信目录在构建沙箱里只读，这 5 种自测都变红。下面几种自测照样通过：去掉 `ARTIFACT_ROOT` 两处检查；去掉 `NO_ARTIFACT`；第 6 步把被审工作区整个挂成可写；不断网；不清环境；不遮 `/home` 等目录；审计程序改成加载扩展并运行初始化器。`ARTIFACT_ROOT`、`NO_ARTIFACT` 在 `selftest.py` 与 `fixtures.tsv` 里都检索不到。我的 `case_protocol.py`（P7、P7b、P12）、`case_followup.py`（P9b）与 `case_probe.py` 可以直接改成自测用例。
3. **S7 对「初始化器不运行」的核对是空的。** 模块制下不带 `meta` 的 `initialize` 只在 `meta import` 时由导入者运行，头部规则不许这种导入，所以它在第 6 步就不会运行；S7 的哨兵路径在第 7 步的沙箱里又是写不到的。我把审计程序改成 `enableInitializersExecution` 加 `importModules (loadExts := true)`，S7 仍然通过（MU6）。性质本身成立，我另行验证过（第六节第 5 条）。建议改用 `meta initialize`，并以标准错误里的进程名或直跑审计二进制来判定。
4. **非 UTF-8 的内容文件退 2 而不是判红。** `fm_audit headers` 读文件时抛异常，运行脚本报 `AUDITOR_OUTPUT 缺少结果行`（`logs/case_protocol.txt` 的 P2）。说明把「被审文件头写坏」归为 `HEADER_PARSE` 红，这一种没走到那里，诊断文字也指向了审计程序而不是被审文件。建议读文件失败同样记 `HEADER_PARSE`。
5. **依赖目录缺包时判红。** 给一个空的依赖目录，第 6 步 `lake build` 失败，报 `BUILD_WFAIL` 退 1（`logs/case_args.txt`）。这是环境问题。建议在准备阶段按基线清单逐个核对 `<依赖目录>/<包名>` 存在，缺了退 2。
6. **第 7 步的搜索路径取自工作区里的 `lake-manifest.json`，读它的时刻在被审构建之后。** 这个文件所在的目录在第 6 步是只读挂载，现在没有问题；但第 2 条里「被审工作区挂成可写」的弱化自测测不出来，两者叠加就是一条通道。建议在第 2 步取料时就从 git 对象解析好包名，第 7 步不再读工作区。
7. **模块数比对几乎恒真。** 审计程序报的是「请求的模块里有几个在已加载环境里」，`importModules` 成功后它必然等于参数个数。它能挡输出被截断或篡改，挡不了产物目录里多出没有源码的模块。建议第 6 步之后比对产物目录里的 `.olean` 集合与内容模块集合，多出即红。
8. **`Main.lean` 的文档注释写「退出码 2 无法判定」，但 `importModules` 在 `try` 之外，读不了产物时以未捕获异常退 1。** 运行脚本因为不凭退出码下结论，仍然正确地退 2（`logs/case_protocol.txt` 的 P11，`logs/case_followup.txt` 的 P11c）。与旧实现相同，不是搬家差异。建议把导入也包进 `try`。
9. **`Chan/Defs` 下的文件不用 `@[expose] public section` 时现在是绿的。** 旧实现在源码层判 `EXPOSE_SECTION`（`run_gates.py:293`，判据来自 `SourceGates.lean:224`）。新入口只留了环境层那一半，私有名被跳过：`Chan/Defs/X1.lean` 只写 `def hidden : Nat := 1`，锁文件登记现算哈希后七步全绿（`logs/case_followup.txt` 的 X1c）。`fixtures.tsv` 把 `must_red/g15/no-expose` 归了第四片，这是如实的；但备注「现状由 build 一步兜住」只对那个夹具成立（它的另一个文件碰巧编译不过）。建议在「搬家差异」表里加一行，并把它计入第四片合入前的已知漏洞。
10. **预检红行的对象栏被转义了两次**，例如分支名里的换行显示成 `\x5cx0a`。只影响可读性。
11. **说明写目录模式固定 0755**，实际受 umask 影响（`os.mkdir(d, 0o755)`）。文件模式因为有 `fchmod` 是固定的。
12. **第 6 步构建日志走标准错误，被审代码可以在里面写任何文字**，包括形似 `FM …` 的行。标准输出与标准错误分开时没有影响。给 #2315：不要把两路合流后再解读。

## 五、「被审构建内部伪造」类路径与交接评估

这一节列的都不构成本片阻断。

| 路径 | 由谁接 | 接得住吗 |
|---|---|---|
| 第 6 步的被审代码改写自己 `.lake` 里的产物，例如把含公理或 `unsafe` 的模块产物换成干净的一份，或者在 `lib/lean/Chan/…` 下放没有源码的额外模块 | `lake check` 与 `lake comparator`（#2315） | 对写在锁定目录里的陈述，接得住，前提是备忘 3.6 的三条硬要求落实（挑战模块在被审代码没写过的构建目录里先构建；`definition_names` 留空；依赖目录只读）。其余定理只有「构建诚实时成立」。额外模块这一种本片可以顺手挡掉，见建议 7 |
| 用 `debug.skipKernelTC` 之类的入口往环境里塞没过内核的常量，公理闭包为空 | `lake check` 的重放（#2315） | 接得住（备忘测 A2）。本次没有重跑 |
| 畸形 `.olean` 破坏读取它的审计进程，让它输出一份合规的绿结果 | 本片没有层来接。靠 `lake check`，它不映射被审 `.olean` | 我只试了随机字节：审计程序报 `invalid header` 退出，整次运行退 2。没有构造能劫持控制流的样本。风险是真实的，接手层在 #2315，在它合入前这条没有人接 |
| 第 6 步留后台进程，等运行脚本核对完产物目录再改写 | 沙箱的进程命名空间 | 接得住。实测 `setsid` 起的后台循环每 0.2 秒往 `.lake` 追加一行时间戳：构建期间写了 11 行，末行时间戳落在第 6 步结束的时刻，整次运行结束后再等 3 秒没有新行（`logs/case_protocol.txt` 末尾的 P10 重跑） |
| 第 6 步在产物目录顶层放 `Init`、把 `lib/lean` 换成符号链接、放别名符号链接 | 第 6 步的 `ARTIFACT_ROOT` | 接得住。实测三种都红（P7、P7b、P9b）。但没有自测，见建议 2 |
| 第 6 步读宿主机文件，再经构建日志带出去 | 沙箱布局与 #2315 的 runner 布局 | 见下一段 |
| 第 6 步耗尽磁盘（`.lake` 可写）、内存（沙箱里的 tmpfs）或时间（超时 4 小时） | #2315 | 可用性问题，不在送审问题内。本机靠 `guard.sh` |

**宿主机可读面**（`logs/case_probe_step6.txt`）。沙箱里 `/home`、`/root`、`/run`、`/var`、`/tmp` 与整个工作目录是空的，网络只有回环，环境变量只有 `HOME`、`TMPDIR`、`LANG`、`PATH` 加 `lake` 自己设的 `LEAN_PATH`。其余宿主机路径只读可见：`/etc`（`/etc/passwd`、`/etc/environment`、主机公钥可读；`/etc/shadow`、主机私钥不可读）、`/opt`、`/mnt`、`/snap`、`/usr/local`、`/boot`。`/proc/1/environ` 可读，但那是沙箱里的 `bwrap`，环境只有 `PATH`。可写的只有 `.lake` 与沙箱自己的 tmpfs；`/etc`、`/usr`、`/opt`、`/srv`、`/mnt`、`/sys`、受信目录、依赖目录、工具链、被审工作区源码都写不了。嵌套 `unshare` 被拒。本机没有读到凭据。

我认为这不算本片阻断：说明对沙箱布局的每一句都与实测相符，「能读到什么」取决于宿主机把凭据放在哪里，而这是 #2315 的事。给 #2315 的输入有两条。第一，CI runner 上凡是运行用户可读的凭据，都必须落在那五个被遮住的目录之内；检出目录如果不在 `/home` 之下，它的 `.git/config`（`actions/checkout` 会在里面留令牌）对被审构建就是可读的。第二，带出通道是构建日志，日志对谁可见要按这个前提来定。

## 六、核实正确的部分

**骨架。**

1. **受信代码的来源。** 受信目录的每个文件由 `ls-tree -r -z <受信提交>:formal_math/verification` 加 `cat-file --batch` 取出，对象类型逐个核对为 `blob`。基线模式下受信提交就是基线。三个构建配置文件恒取自基线。被审提交自己的配置文件、`formal_math/` 下的非内容文件都不进被审工作区（读代码；真实仓库实跑时受信 1061 个文件、内容 3 个模块）。
2. **被执行的审计二进制。** 第 4、7 步按绝对路径执行 `<工作目录>/trusted/verification/auditor/.lake/build/bin/fm_audit`，它由第 3 步在沙箱之外、只用受信目录的源码与配置构建，环境只有 `PATH`、`HOME`（工作目录下新建的空目录）、`LANG`。被审提交没有任何字节进入这次构建。
3. **第 6 步写不到的地方**（实测，`case_probe.py`）：受信目录（被 tmpfs 盖住，不可见）、依赖目录（只读挂在 `.lake/packages`）、被审工作区的源码与配置、工具链、宿主机其余路径。构建结束后宿主机上 `/dev/shm`、`/var/tmp`、`/tmp`、工作目录顶层、受信目录、依赖目录里都没有哨兵。
4. **第 4、7 步的挂载表**与说明的表一致（`case_step7_sandbox.py`，用 `run.py` 自己的 `sandbox()` 加各步的挂载清单跑探针）：被审工作区、`.lake`、受信目录、依赖目录、工具链全部只读，断网。
5. **取料。** 路径文法、`O_CREAT|O_EXCL|O_NOFOLLOW`、受信目录与被审工作区各自 `os.mkdir` 新建（已存在即失败）。内容根下非 `100644` 普通 `.lean` 文件、不合模块名文法的路径段、顶层多余的 `.lean`（含 `lakefile.lean`）判 `CONTENT_PATH`；内容根之外的条目不取。
6. **输出协议的结构校验。** 结果行必须恰好一条且在最后；红当且仅当有发现；退出码须与判定一致；头部记录须与请求的文件一一对应；锁行的模块须在内容模块里；声明名重复、门号不认识都退 2。被审方控制的名字经 Lean 的 JSON 编码后不能在审计程序的输出里另起一行（P1、P4：换行被转义成 `\n`，运行脚本解析出的是完整字符串）。审计程序以未捕获异常退 1 而没有结果行时，整次运行退 2（P11、P11c）。
7. **快速失败。** 第 1、4、6 步判红后没有后续步骤行（P 系列与自测 S2、S6、S14；弱化 MU5 被 5 个用例抓到）。
8. **参数与前置条件。** 36 种写法逐条实测（`logs/case_args.txt`）：缩写、等号、重复、空值、以 `-` 开头、`--until` 的 `0`、`07`、全角数字、未知开关、仓库不存在、提交解析不出、基线是树对象、依赖目录不存在或是文件、工作目录是 `/`、是文件、是符号链接、在仓库里、在 git 目录里、在依赖目录里、包含仓库、父目录不存在、分支名含换行或非 UTF-8 字节。结果都落在说明的契约内：用法与前置条件错误退 2，预检判红退 1，`--until 1`、`--until 2` 全绿时退 2 并写 `FM RESULT PARTIAL`。例外只有 B-2 的两例，以及建议 5 的缺包一例。
9. **输出通道。** 标准输出指向 `/dev/full`、被关闭、管道提前关闭，七步全绿时都退 2（`OUTPUT`）。
10. **`RUNNER_MISMATCH`** 生效（S13；弱化 MU1 被抓到）。
11. **说明里的数字。** `git diff --no-index --numstat` 三组读数 6/720、30/47、59/17 与说明一致。`fixtures.tsv` 252 行，九类归属的夹具数、必红必绿分布、新入口实测分布与说明的汇总表逐格相符；归第四片的必红夹具现为绿的是 26 个；九个环境层红码各至少有一个夹具判出；删除的旧夹具文件是 46 个。
12. **真实仓库。** 自举模式，基线 `594e49b5ec`，带放行开关，受信提交取被审提交：七步全绿，退 0（`logs/real_repo_bootstrap.stdout.txt`）。`Chan/Smoke.lean` 导入 Mathlib，第 7 步经依赖目录的搜索路径读到了它。

**环境层搬家。**

1. **`Audit.lean → Main.lean`。** 逐行对照：`allowedAxioms`、`probeName`、`sameModule`、`expectedCtorIdx`、`ctorIdxImpl`、`generatedBy`、`gate3` 的判定逻辑一字未改（`generatedBy` 的文档注释改了一行），`gate3` 只有输出那一行换成 `emitFinding`。`main` 的差异全在分派上，与说明的「搬家差异」表逐条对得上。
2. **`EnvGates.lean`。** 保留部分（旧文件第 1–108、814–838 行）与新文件的差异：删去 `projectModule`、`owner`、`node` 三个只服务报告的辅助函数；新增 `emitFinding`；`finding` 只剩门 15 一路；锁行多一个 `"lock"` 标签。从 `row` 到 `FM-lock-v3` 的序列化代码两边 sha256 相同（`f7ba3fbc…`）。旧 g6a 夹具 12 个连同它们旧的锁哈希在新入口全部按期望通过（`logs/selftest_only_g6a.txt`）。
3. **`Headers.lean`。** `headerIssues` 与旧实现逐行相同，只是五处门号 `"3"` 换成了具体红码。`readHeader` 改成返回 `none`、`headers` 输出多了模块名与 `isMeta` 两栏，都在说明里。
4. **方向表。** `lane` 与旧实现相同；`allowed_edge` 只少了 `AUDIT_TOOLS` 两行；传递闭包的循环相同。`import all` 的导入现在还要过方向表，比旧实现严。
5. **读环境不执行被审代码**（`case_init.py`，`logs/case_init.txt`）。被审模块 `ChanExplore/Sentinel.lean` 带 `meta initialize`，把进程名写到标准错误并尝试在 `.lake/` 下落哨兵。
   - 正对照一：第 6 步构建导入它的模块时，标准错误出现 `RF-INIT-RAN app=…/bin/lean`，`.lake/rf-init-ran-lean` 存在。
   - 流水线第 7 步：标准错误里没有 `app=…/fm_audit` 的行，审计程序正常判出 `ENV_META`。
   - 流水线外直跑同一个受信二进制、同一批产物，`.lake` 可写：`rf-init-ran-fm_audit` 不存在。
   - 正对照二：对同一批产物用 `enableInitializersExecution` 加 `importModules (loadExts := true)`，哨兵出现，带与不带 `meta` 的两个初始化器都运行了。
   - 读工具链源码：`importModules` 的 `loadExts` 默认 `false`（`Lean/Environment.lean:2809`），`runInitAttrs` 只在 `finalizePersistentExtensions` 里调用；`Meta/WHNF.lean` 在 4.36.0 没有原生求值分支，所以 `expectedCtorIdx` 里对被审类型做的 `whnf`、`inferType` 也不执行被审代码。
6. **明文必红写法**（`case_migrate.py`，`logs/case_migrate.txt`），整次运行的退出码都是 1：

   | 写法 | 红码 |
   |---|---|
   | `set_option warn.sorry false in theorem … := sorry`；直接写 `sorryAx False false` | `ENV_SORRY` |
   | 不关告警的 `sorry` | `BUILD_WFAIL` |
   | `by native_decide`；`by decide +native` | `ENV_AXIOM`、`ENV_AXIOM_DEP` |
   | `unsafe def` | `ENV_UNSAFE` |
   | `partial def` | `ENV_PARTIAL` |
   | `@[implemented_by]` | `ENV_IMPLEMENTED_BY` |
   | `@[extern] opaque` | `ENV_EXTERN` |
   | `meta def` | `ENV_META` |
   | `private axiom` 加引用它的定理；`ChanExplore` 里的公理；实例证明里用公理 | `ENV_AXIOM`、`ENV_AXIOM_DEP` |
   | 锁定陈述被改、被删、未登记（旧 g6a 夹具） | `LOCK_CHANGED`、`LOCK_REMOVED`、`LOCK_UNLISTED` |
   | `prelude` | `PRELUDE` |
   | `meta import`、`public meta import` | `META_IMPORT`（被导入的 `Chan.Base` 不合方向表，另带 `IMPORT_EDGE`） |
   | `import all` | `IMPORT_ALL`（同上，另带 `IMPORT_EDGE`） |
   | `import Lean`；`import Foo.Bar`；`Chan/Thm` 导入 `ChanExplore`；`Chan/Defs` 导入 `Chan.Base`；`import Mathlib` | `IMPORT_PINNED`；`IMPORT_SOURCE` 加 `IMPORT_EDGE`；`IMPORT_EDGE` 加 `IMPORT_SOURCE`；`IMPORT_EDGE`；`WHOLE_MATHLIB` |
   | 不以 `module` 开头；文件头写坏 | `MODULE_FIRST`；`HEADER_PARSE` |

7. **必绿。** 我自己写的对照（多构造子归纳类型、结构递归、良基递归、实例、私有定义与定理、`decide`、`omega`、`cases`、`noncomputable def`）七步全绿，说明豁免 1、2 没有搬坏。`fixtures.tsv` 里新入口判 `ENV_PARTIAL` 或 `EXPOSE_SECTION` 的 12 个旧必绿夹具，我逐个把被判的名字写成证书、直接交给审计二进制重跑：被判的全是派生处理器的辅助函数（`inst…​.beq`、`.hash`、`.ord`、`.repr` 及其 `_unsafe_rec`），给了证书后 12 个全部零发现（`logs/case_followup_D1.txt`）。所以这批误拒确实只来自「没有证书的产生方」，判据与旧实现一致。其余变红的旧必绿夹具是 `LOCK_UNLISTED`（夹具不带锁文件）与 `attributes-whitelist`（夹具自身有告警），都在说明里。

## 七、弱化测试结果

`mutants.py` 在被审树的副本里改一处，再跑骨架自测。标「全量」的跑了全部 22 个骨架用例，其余只跑了与该弱化相关的用例子集，语料用例都没有跑。

| 弱化 | 跑的用例 | 自测结果 |
|---|---|---|
| MU0 不改（对照） | 全量 | 22/22 通过 |
| MU1 去掉 `RUNNER_MISMATCH` | 全量 | 变红（S13） |
| MU2 去掉模块数比对 | 全量 | 变红（S5 env-count） |
| MU5 判红后继续跑下一步 | S2、S6a、S6b、S10、S14 | 5 个全红 |
| MU10 不核对判定、发现与退出码的一致 | S5 五例 | 变红（env-verdict、env-exit） |
| MU3b 第 6 步把受信目录挂成可写 | S3、S7 | 变红（S7） |
| MU3c 第 6 步把被审工作区整个挂成可写 | S1、S3、S7 | **通过** |
| MU7 不断网（`--unshare-all` 换成不含网络的五项） | S1、S7 | **通过** |
| MU8 去掉 `--clearenv` | S1、S7 | **通过** |
| MU9 去掉每个模块都有 `.olean` 的核对 | S1、S6b | **通过** |
| MU11 只遮 `/tmp`，不遮 `/home` 等与工作目录 | S1、S3、S7 | **通过** |
| MU4 去掉 `ARTIFACT_ROOT` 两处检查 | 全量 | **通过**（22/22） |
| MU6 审计程序加载扩展并运行初始化器 | 全量 | **通过**（22/22） |

## 八、没覆盖的部分

- 第一片预检、CI 工作流、同目录待删的旧门禁代码，按送审范围没有审。
- 全量自测（247 例）没有重跑。我跑的是骨架 22 例（弱化对照那一次）、g6a 语料 12 例、12 个派生夹具，以及自己的夹具约 80 次整条流水线。
- 弱化测试大多只跑了相关用例子集，语料用例没有在弱化副本上跑；表里的「通过」只说明我跑的那几个用例测不出。
- 超时路径（各步 60 秒到 4 小时）只读了代码，没有实测。
- 对沙箱本身只做了探针级的检查，没有尝试内核层面的逃逸。
- 没有构造能劫持审计进程的畸形 `.olean`，只试了截断与随机字节。
- 没有实做「被审构建伪造产物骗过环境层」的端到端样本；它属于已明示的前提，交接评估是按代码与备忘推的。
- SHA-256 对象格式的仓库、大小写不敏感的文件系统、macOS，都没有测。
- 自举模式只在真实仓库上跑了一次绿路径。
- B-1 的注入只实测了导入名与公理名两个入口。`ENV_PARTIAL` 的源定义名与 `IMPORT_CLOSURE` 的说明栏按代码判断同样不转义，没有单独跑。

## 九、审阅过程中的一处失误

弱化测试的第一版里有一个「把依赖目录在沙箱里挂成可写」的变异。它运行到自测 S7 时，S7 的被审代码真的在共享依赖目录顶层写下了哨兵文件 `sentinel-packages`，随后由 S7 自己删除。这违反了「依赖目录只读使用」的约束。我发现后立即终止了那次运行并做了核对：依赖目录顶层的修改时间变为 2026-11-26 08:42:22（+08），`find <依赖目录> \( -mmin -60 -o -cmin -60 \)` 只列出顶层目录自身，九个包目录及其下所有条目的修改时间与状态变更时间都没有变化，哨兵文件已不存在。该变异已从 `mutants.py` 删除，并在脚本头部写了警示。

---

VERDICT-骨架: BLOCK（范围：`formal_math/verification/runner/` 的 `run.py`、`selftest.py`、`README.md`、`fixtures.tsv`、`selftest-cases/`，以及本片对 `formal_math/lakefile.toml`、`run_gates.py`、旧 `selftest.py`、仓库根 `.gitignore` 的改动；阻断 3 条，B-1 属第 4 类兼涉第 2 类，B-2 属第 3 类，B-3 属第 3、4 类）
VERDICT-环境层搬家: PASS（范围：`formal_math/verification/auditor/` 独立 Lake 包相对 `594e49b5ec` 的 `Audit.lean`、`EnvGates.lean`、`SourceGates.lean` 头部部分的搬家，含运行脚本里的头部方向表与声明锁比对；派生证书缺失导致的误拒按已明示前提不计）
