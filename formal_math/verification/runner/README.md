# formal_math 阻断门的运行骨架与独立审计程序（#2312 第二、三片）

`run.py` 按固定顺序跑七步，前一步不绿即停；`../auditor/` 是只依赖 Lean 核心的独立 Lake 包，源码与配置取自受信提交，在仓库检出目录之外构建，产物放在被审构建写不到的目录。门禁只审提交，不读工作树。

设计依据：`origin/evidence/2312-design-consult` @ `aedff2e010` 的备忘 3.0–3.4、3.6、3.7、第五节第 2、3 条；#2312 评论 7175991382。第一片（`../precheck/`）的输出与退出码风格在这里沿用。

**送审问题（第二片）**：被审提交能否影响哪个审计二进制被执行，或者经声明之外的通道影响它的输入。
**送审问题（第三片）**：环境层、声明锁与暴露检查相对第五轮核实过的实现是否原样搬来，差异见「搬家差异」。

> **在第四片合入之前，整条流水线的绿不含源码形状这一层。** 第 5 步目前直接通过并在输出里写 `SHAPE 未安装`。

## 调用

```sh
source scripts/fm_env.sh
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh \
  python3 -I formal_math/verification/runner/run.py [--trusted-change-approved] \
    [--bootstrap-trusted-from <提交>] [--until <1-7>] \
    --repo <仓库> --base <基线提交> --head <被审提交> --branch <分支名> \
    --workdir <工作目录> --packages <依赖目录>
```

- **必须带 `-I`**（隔离模式）。不带时脚本所在目录排在模块搜索路径最前面，同目录的 `json.py`、`re.py` 之类会顶替标准库。`run.py` 开头只用内建模块：`sys` 查 `sys.flags.isolated`；不满足时 `import posix`（`sys` 与 `posix` 都在 `sys.builtin_module_names` 里，由内建导入器在路径查找之前加载，路径上的同名文件顶替不了；`os` 不是内建模块，这段不用它），用 `posix.write` 尽力向两路各写一行（写不出就跳过，异常一律吞掉），然后 `posix._exit(2)`：不走异常处理与收尾钩子，解释器不会再为打印回溯或刷新流去导入任何模块。本机 Python 3.14.4 实测（自测 S24）：两路正常、标准输出关闭、标准错误关闭、两路都关闭、标准输出指向 `/dev/full`、标准错误指向 `/dev/full` 六种状态都退 2，同目录放的 `re`、`json`、`os`、`sitecustomize`、`traceback`、`posix`、`sys`、`signal`、`stat`、`time` 十个冒名模块都没有被执行。`-I` 管不到的：不带 `-I` 时若 `PYTHONPATH` 指向别人能写的目录，解释器在执行 `run.py` 第一行之前就会导入那里的 `sitecustomize`；`python3 -I -m run` 不受支持，只能按脚本路径调用。这两条交给 #2315 的工作流（调用一律 `python3 -I <路径>/run.py`，不设 `PYTHONPATH`）。
- 参数自己解析，不用 `argparse`：选项只认全名，每个最多一次，取值不得为空或以 `-` 开头；`--x=y`、缩写、未知开关、缺项都退 2。没有任何参数组合能在没做完整判定时退 0：`--until <n>`（n<7）跑完前 n 步且全绿时退 2（`FM RESULT PARTIAL`），遇红仍退 1。
- `--workdir`：调用方给，必须不存在或是空目录，且与仓库检出目录、git 目录、依赖目录互不包含。运行脚本不删除它。
- `--packages`：依赖目录（Mathlib 等，按基线 `lake-manifest.json` 的包名逐个取 `<依赖目录>/<包名>`）。由调用方准备好；运行脚本不联网、不下载。SafeCode 上是 `/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages`。
- `--trusted-change-approved`：原样转给预检（只对 `infra` 角色有意义）。
- 子进程的 git 环境与第一片相同：`LC_ALL=C`、不读系统与全局配置、屏蔽替换对象与 grafts。

### 受信代码从哪个提交来

- 默认取自**基线提交**：运行脚本、预检、审计程序包都要在基线的 `formal_math/verification/` 里。
- 正在运行的 `run.py` 必须与受信提交里的 `formal_math/verification/runner/run.py` 是同一个 blob（`git hash-object --no-filters` 比对），否则退 2（`RUNNER_MISMATCH`）。输出第二行 `FM RUNNER blob=<…> from=<受信提交>:<路径>` 写明这一点。门禁只审提交：本地有未提交改动时先提交再跑。
- **自举**：基线缺这三样（现在的 `main` 就是这样）时，没给 `--bootstrap-trusted-from` 一律退 2（`NO_TRUSTED_CODE`）。给了就从那个提交取受信代码，输出首行写 `FM MODE bootstrap …自举模式：受信代码取自调用方指定的提交，不保证来自主干`。**自举模式不提供「受信代码来自主干」这一保证**，结论只等于「调用方指定的那份门禁对被审提交的判定」。三个构建配置文件在自举模式下仍取自基线。

## 七步

| 步 | 名字 | 做什么 | 判红码 | 无法判定（退 2）的码 |
|---|---|---|---|---|
| 1 | `precheck` | 从受信提交取出 `precheck.py` 写到 `<工作目录>/step1/`，`python3 -I` 运行，参数是解析后的基线、被审提交全名与分支名。输出逐行核对：退 0 须恰好一行绿行且提交名相符；退 1 须每行都是红行 | 第一片的全部规则码，原样转出 | `PRECHECK_EXIT`、`PRECHECK_OUTPUT`、`PRECHECK` |
| 2 | `fetch` | 受信目录 `<工作目录>/trusted/verification/` ← 受信提交的 `formal_math/verification/` 整棵树。被审工作区 `<工作目录>/audited/` ← 被审提交的内容文件（`Chan/`、`ChanTest/`、`ChanChallenge/`、`ChanDyn/`、`ChanExplore/` 下与顶层 `Chan.lean`、`ChanExplore.lean`）+ **基线**的 `lakefile.toml`、`lake-manifest.json`、`lean-toolchain`。见下「取料」 | `CONTENT_PATH`（内容根下有不合文法、不是 100644 普通 `.lean` 文件的条目，或顶层有别的 `.lean`）；`CONTENT_ENCODING`（内容文件不是合法 UTF-8） | `TRUSTED_TREE`、`BASE_CONFIG`、`NO_PACKAGE`、`NO_CONTENT`、`GIT`、`INPUT`（基线清单）、`PACKAGES`（依赖目录缺基线清单里的包） |
| 3 | `auditor` | 核对受信 `auditor/lean-toolchain` 与被审工作区的（基线的）工具链文件逐字节相同；`lean --print-prefix` 定位工具链并核对 `lean --version`；在受信目录里 `lake build`。输出审计二进制的路径与 sha256 | — | `TOOLCHAIN_MISMATCH`、`TOOLCHAIN`、`AUDITOR_BUILD` |
| 4 | `headers` | 沙箱里跑 `fm_audit headers <模块> <路径> …`：审计程序只解析文件头，不加载任何导入。头部白名单的发现由审计程序给出；目录方向表、传递闭包、整库导入 Mathlib 由运行脚本按审计程序给的导入列表判定 | `MODULE_FIRST`、`PRELUDE`、`IMPORT_ALL`、`META_IMPORT`、`IMPORT_PINNED`、`IMPORT_SOURCE`、`HEADER_PARSE`（审计程序）；`WHOLE_MATHLIB`、`IMPORT_EDGE`、`IMPORT_CLOSURE`（运行脚本） | `AUDITOR_OUTPUT`、`MODULE_COUNT`、`AUDITOR`、`SIGNAL` |
| 5 | `shape` | **空位**，第四片实现。直接通过，输出 `SHAPE 未安装` | — | — |
| 6 | `build` | 先在同一沙箱里跑 `lean --version` 作探针，再 `lake build --wfail`（基线配置的默认目标）。之后把被审构建可写的整个 `.lake` 逐项过形状表，见下「产物形状表」 | `BUILD_WFAIL`、`NO_ARTIFACT`、`EXTRA_ARTIFACT`、`ARTIFACT_ROOT`、`ARTIFACT_FORM` | `SANDBOX`、`BUILD`（超时）、`SIGNAL`（沙箱顶层进程被信号终止，见「沙箱布局」） |
| 7 | `env` | 另起沙箱，只读挂载被审工作区（含构建产物）、依赖目录与受信目录，跑 `fm_audit env <模块> …`：门 3 环境层、门 15 暴露检查、门 6a 声明锁的规范序列化。运行脚本对锁行求 sha256，与**被审提交**的 `formal_math/statement-lock.json` 逐项比对 | `ENV_AXIOM`、`ENV_AXIOM_DEP`、`ENV_SORRY`、`ENV_META`、`ENV_EXTERN`、`ENV_UNSAFE`、`ENV_PARTIAL`、`ENV_IMPLEMENTED_BY`、`EXPOSE_SECTION`、`LOCK_CHANGED`、`LOCK_REMOVED`、`LOCK_UNLISTED` | `AUDITOR_OUTPUT`、`MODULE_COUNT`、`INPUT`（锁文件缺失或不是严格 JSON 对象）、`CERTIFICATE`、`AUDITOR`、`SIGNAL` |

运行前的准备（解析参数、解析提交、核对工作目录、受信代码是否齐全、`run.py` 是否就是受信那份）失败时步骤名记 `prepare`，退 2。任何意外异常（含输出函数自身的失败）都归入 `INTERNAL`，退 2，并尝试写结果行 `FM RESULT FAULT`（契约见「输出与退出码」）；`__main__` 外面还有一层兜底，连 `main` 的异常处理都失败时也退 2，不会落成 0 或 1。

### 取料

- 只用 `ls-tree -r -z <提交>:<路径>` 加 `cat-file --batch` 逐个取 blob 原始字节。不用 `git archive`、检出或 `git worktree`，所以被审树里的 `.gitattributes`（`export-ignore`、`filter`、`eol`）与仓库配置的过滤器都不起作用。
- 受信目录里每条路径段须合 `[A-Za-z0-9_][A-Za-z0-9_.-]*` 且是 100644 普通文件，否则退 2。内容文件的每个路径段（去掉 `.lean`）须合模块名文法 `[A-Za-z][A-Za-z0-9_]*`。
- 写文件用 `O_CREAT|O_EXCL|O_NOFOLLOW`，模式固定 0644，目录 0755（建好后再 `chmod`，不受 umask 影响）；已存在或遇到符号链接即失败。
- 基线清单 `lake-manifest.json` 在这一步从 git 对象严格解析，定下第 7 步搜索路径用的包名，并核对依赖目录里每个包都在（缺了退 2）；之后各步不再读被审工作区里的任何文件来决定输入。
- **与预检的交接**：模式是文件的条目必须指向 blob。预检（`d660582472` 起）自己核对这一点，不是则 `TREE_FORM` 判红；取料仍保留同一道检查作纵深防御：用 `cat-file --batch` 读每个对象时核对头行类型必须是 `blob`，不是就 `GIT` 故障退 2，这一步发生在建任何目录之前，被审工作区与受信目录都不会写出，更不会把它当空文件写出或跳过。自测 S16 两例（对象实为树、实为提交）各跑两次：经预检在第 1 步 `TREE_FORM`；绕过预检从第 2 步起跑则取料退 2。
- 第 1 步只接受两种预检输出：退 0 且恰好一行绿行；退 1 且每行都是 `PRECHECK RED <码> <对象> <说明>`。红码按 `[A-Z_]+` 原样转出，预检新增的码（`LAKE_FILE`、`TREE_FORM` 等）不需要改运行脚本；其它任何输出（未知格式、退 2 的 `BASE_FORM`、`NOT_ANCESTOR` 等，此时预检已写到标准输出的红行不转出）一律退 2。
- 被审提交里 `formal_math/` 下的其它文件（README、台账等）与它自己的三个构建配置文件都不进被审工作区。锁文件由运行脚本在第 7 步直接从被审提交的 git 对象读。

### 沙箱布局（第 4、6、7 步）

`bwrap --ro-bind / /`，`/home`、`/root`、`/run`、`/var`、`/tmp` 与**整个工作目录**先盖成空 tmpfs，再按步回绑；`--clearenv` 后只放回 `HOME=/tmp/home`、`TMPDIR=/tmp`、`LANG=C.UTF-8`、`PATH=<工具链>/bin:/usr/bin:/bin`（第 7 步另加 `LEAN_PATH`、`LEAN_SYSROOT`）；`--unshare-all`（断网）、`--die-with-parent`、`--new-session`。`bwrap` 进程本身也只拿到 `PATH` 一个环境变量（两层：调用 `bwrap` 时的环境与 `--clearenv`）。**信号**：`bwrap` 只转出它直接启动的那个进程（第 4、7 步的审计程序，第 6 步的 `lake` 与探针 `lean --version`）的退出状态。沙箱里由运行脚本直接启动的那个进程以大于等于 128 或负的退出码结束时，归入 `SIGNAL` 退 2（自测 S18、S27）。`lake` 启动的 `lean` 工作进程被杀时，`lake` 把它记成一次构建失败、自己以 1 退出，运行脚本报 `BUILD_WFAIL` 退 1：运行脚本分不清「`lean` 被内核杀掉」与「被审代码自己搞死 `lean`」，构建日志又是被审方可写的。两种情形退出码都非零。超时由运行脚本杀掉 `bwrap` 所在的整个进程组，`--die-with-parent` 带走沙箱里的进程（自测 S19 核对超时后再无写入）。

| 步 | 被审工作区 | `.lake` | 依赖目录 | 受信目录 | 工具链 |
|---|---|---|---|---|---|
| 4 | 只读 | — | 不挂 | 只读 | 只读 |
| 6 | 只读 | **可写** | 只读挂到 `.lake/packages` | 不挂（被 tmpfs 盖住） | 只读 |
| 7 | 只读（含产物） | 只读 | 只读，挂在原路径 | 只读 | 只读 |

审计二进制永远是第 3 步在受信目录里构建的那一个，运行脚本按绝对路径执行它，不对被审包调用 `lake exe`。第 7 步的搜索路径由运行脚本按基线清单拼出：依赖包的 `.lake/build/lib/lean` 在前，被审产物在后，工具链自带的库由 Lean 追加在最后；第 6 步因此逐项核对 `.lake`（见下）；第 7 步的搜索路径里被审方的部分只有 `.lake/build/lib/lean`，它是核对过的那一部分，审计程序也只经搜索路径读产物。

### 产物形状表（第 6 步，`artifact_reds()`）

被审构建在沙箱里只能写 `.lake`。构建结束后运行脚本从 `.lake` 起递归遍历每一个目录项：用 `lstat`，不跟随符号链接；每个目录都必须列得出，列不出不跳过而是判红。形状表按 Lake 4.36.0 实际放的东西列（真实仓库与自测构建实测）：

| 位置 | 允许的目录项 |
|---|---|
| `.lake/` | 目录 `build`、`packages`、`config` |
| `.lake/packages/` | 空（依赖目录在沙箱里只读挂在这里，宿主机这一侧的挂载点不会有东西） |
| `.lake/config/` | 目录 `<数字>`，其中只有文件 `lakefile.olean`、`lakefile.olean.trace`（Lake 为依赖包的 `lakefile.lean` 缓存的配置，依赖目录只读时写在这里） |
| `.lake/build/` | 目录 `lib`、`ir` |
| `.lake/build/lib/` | 目录 `lean` |
| `.lake/build/lib/lean/` | 对每个内容模块 `A.B.C`：目录 `A`、`A/B`（只许是内容模块路径的前缀），文件 `A/B/C` 加下列 13 个后缀之一：`.olean`、`.olean.hash`、`.olean.private`、`.olean.private.hash`、`.olean.server`、`.olean.server.hash`、`.ilean`、`.ilean.hash`、`.ir`、`.ir.hash`、`.ir.sig`、`.ir.sig.hash`、`.trace`。只有 `.olean` 是每个模块必须有的 |
| `.lake/build/ir/` | 同样的目录前缀；文件 `A/B/C` 加 `.c`、`.c.hash`、`.setup.json` |

判定，按顺序，每个目录项只报一条：

| 码 | 条件 |
|---|---|
| `ARTIFACT_ROOT` | `build/lib/lean` 顶层目录项的名字（第一个点之前）不是内容根。第 7 步的搜索路径上被审产物排在工具链库之前，`Init` 之类会遮住真库 |
| `ARTIFACT_FORM` | 不是普通文件或目录（符号链接、设备、管道、套接字）；目录模式不是属主可读写进入或带特殊位；文件带执行位或特殊位、属主不可读；目录列不出；读不到目录项 |
| `EXTRA_ARTIFACT` | 不在上表里：名字带多余的点（`Chan/Thm.Ok.olean` 是另一个模块 `Chan.«Thm.Ok»`）、隐藏名、没有源码的模块、名字合法但类型不对（名为 `X.olean` 的目录）、`.lake` 或 `build` 下多出的东西、依赖挂载点下有东西。表外的目录不再往下走 |
| `NO_ARTIFACT` | 某个内容模块的 `build/lib/lean/A/B/C.olean` 不存在或没有通过上面的检查 |

真实仓库（3 个内容模块）一次完整构建后 `.lake` 共 73 个目录项，全部在表内，见交接汇报里的分类计数。

## 输出与退出码

| 退出码 | 含义 |
|---|---|
| 0 | 七步都跑完且全绿，最后一行 `FM RESULT GREEN` |
| 1 | 某一步判红。该步的红行之后是 `FM STEP <n> <名字> RED` 与 `FM RESULT RED`，后面的步骤不跑也不报 |
| 2 | 无法判定，包括参数、前置条件、工具缺失、构建审计程序失败、沙箱探针失败、审计程序输出无法解读或与 git 树对不上、超时、意外异常、`--until` 提前停下。诊断行 `FM FAULT <步骤> <码> <对象> <说明>` 写标准错误 |

- **行协议**。标准输出只有 `FM MODE`、`FM RUNNER`、`FM RED <步骤> <规则码> <路径或对象> <说明>`、`FM STEP <n> <名字> <GREEN|RED|FAULT> <秒> <备注>`、`FM RESULT <GREEN|RED|FAULT|PARTIAL> …` 五种行；标准错误只有 `FM FAULT <步骤> <码> <对象> <说明>` 与 `FM LOG <来源> <行>` 两种行。**结果行的契约**：标准输出至多一行结果行；有绿结果行则退出码为 0；退出码为 0 则恰有一行绿结果行且它是标准输出最后一行。实现：最终状态与退出码先定下来，结果行整次运行只尝试写一次，用一次 `os.write` 写整行（不超过 `PIPE_BUF`，管道上要么整行写出要么一字未写）；写不出就把退出码改成 2，不补写第二行。绿的结论另要求前面每一行都写出去了：前面有任何一行没写出，就不写绿而写 `FM RESULT FAULT output OUTPUT`、退 2（自测 S25）。被 SIGINT、SIGTERM 打断时，处理函数杀掉正在运行的子进程组，尽力写一行 `FM FAULT` 与 `FM RESULT FAULT <步骤> SIGNAL`，以 2 退出（自测 S26）；被别的信号（如 SIGKILL）终止，或连这一行都写不出时，可能没有结果行，退出码非零。**调用方以退出码为准。**
- **一条转义规则，一个函数**（`safe()`）。写进标准输出或标准错误的每一个字段都先经它，不分来源：可见 ASCII（反斜杠除外）与 Unicode 字母、数字、标点、符号原样保留；空格只在最后一栏（说明、日志行）保留；其余一律写成可见形式——ASCII 控制字符、非 UTF-8 字节写 `\xNN`，换行以外的其它码点（行与段分隔符、方向控制符、零宽字符、组合符、孤立代理项、未分配码点）写 `\uNNNN`；每个字段最多 400 个字符，超出截断并注明。`emit()` 是唯一写两路输出的函数，它不抛异常。
- **子进程的输出不透传**。git、预检、`lake`（构建审计程序与第 6 步构建）、审计程序的标准错误（构建时连同标准输出）都先捕获，再逐行写成 `FM LOG <来源> <行>`。被审代码在构建期打印的任何文字（包括形似 `FM RESULT GREEN` 的行）因此只能以转义后的日志行出现在标准错误里（自测 E10）。预检红行的对象栏它自己已转义过，运行脚本先还原成原字节再经 `safe()`，不会二次转义。
- **进入输出的外来片段**（逐个有自测）：模块路径（E11）；导入名（E1）；声明名与公理名（E2）；锁文件的键与值（E3–E7）；分支名（E8、E9）；提交名参数（E9）；预检转出的红行（E8、E11a、S2）；`lake` 构建输出（E10、S17）；审计程序的标准错误（S17）；异常消息与调用方路径参数（E13）；审计程序发现行里的说明文字（E1、E2，其中含被审名字）。
- **JSON 一律严格解析**（`strict_json()`）：字节须是合法 UTF-8；重复键、`NaN`/`Infinity`、任何字符串（含键）里的孤立代理项都拒收。锁文件与基线清单不合格退 2（`INPUT`），审计程序输出不合格退 2（`AUDITOR_OUTPUT`）。审计程序用 Lean 的 `Json.compress` 输出，字符串里的换行与控制字符本来就转义成 `\n`、`\u00XX`，名字里的换行打不破它的逐行格式；运行脚本按 `\n` 切行后逐行严格解析，任何一行不合格整次退 2。
- 全部按 UTF-8 字节 `os.write`，不用 `print`（原因同第一片）。
- **运行脚本不凭审计程序的退出码下结论**。审计程序每个子命令在标准输出逐行给 JSON，最后一行是 `["result", 子命令, "red"|"green", 审过的模块数]`。运行脚本核对：每行都能解析且形状对；结果行恰好一条且在最后；判定为红当且仅当有发现行；退出码与判定一致（红 1、绿 0）；模块数与运行脚本从 git 树数出的内容文件数相等；第 4 步还核对头部记录与请求的文件一一对应。任何一条不符都退 2。

## 审计程序包 `../auditor/`

| 文件 | 来源 | 内容 |
|---|---|---|
| `lakefile.toml`、`lake-manifest.json`、`lean-toolchain` | 新写 | 包名 `fm_auditor`，库 `Auditor`，可执行 `fm_audit`（`supportInterpreter = true` 照旧），无依赖；工具链与被审包相同，第 3 步核对 |
| `Main.lean` | `../Audit.lean` | 门 3 环境层（`allowedAxioms`、`expectedCtorIdx`、`ctorIdxImpl`、`generatedBy`、`gate3`）原样；`main` 只剩 `headers` 与 `env` 两个子命令 |
| `Auditor/EnvGates.lean` | `../EnvGates.lean` 第 1–108、814–838 行 | `Entry`、`within`、`locked`、声明锁 v3 的规范序列化（`statement`）、`run` 的 `6a` 与 `15` 分支 |
| `Auditor/Headers.lean` | `../SourceGates.lean` 第 13–29、37–45、361–385 行 | 文件头解析（`Parser.parseHeader`，不加载导入）、三张库根表、`headerIssues` |

子命令：

- `fm_audit headers <模块> <路径> …`：每个文件一行 `["header", 路径, 模块, isModule, [[导入, 行, importAll, isMeta], …]]`，头部白名单的发现一行 `["finding", "headers", 路径, 行号, 红码, 说明]`，最后 `["result", "headers", 判定, 文件数]`。
- `fm_audit env [--derived <证书>] <模块> …`：按私有层级（`level := .private`）读这批模块的产物，不加载环境扩展（`importModules` 默认），被审模块的初始化器不运行（备忘测 A1；自测 S7 用 `initialize` 写哨兵核对）。先确认能读到 `ChanTest.Probe` 私有定理的证明体，读不到退 2（与旧实现相同）。发现一行 `["finding", 门, 路径, 声明, 红码, 说明]`（门为 `3` 或 `15`），锁行 `["lock", 声明, 模块, 序列化]`，最后 `["result", "env", 判定, 审过的模块数]`。门 15 只审 `Chan.Defs` 下的模块，对外可见环境只导入这些模块（与旧实现相同）。

### 搬家差异（逐处）

环境层逻辑与第五轮核实时相同。`git diff --no-index --numstat`（增 / 删）：`EnvGates.lean → Auditor/EnvGates.lean` 6 / 720（删的是审阅报告各门与只服务报告的辅助函数，保留部分只改 6 行）；`Audit.lean → Main.lean` 30 / 47（全部在导入、一行红行输出与 `main` 分派）；`SourceGates.lean` 第 13–29、37–45、361–385 行 → `Auditor/Headers.lean` 59 / 17（`headers` 子命令重写、`readHeader` 改返回值、`headerIssues` 换红码）。不得不改的地方：

| 位置 | 旧 | 新 | 理由 |
|---|---|---|---|
| `Main.lean` 导入 | `verification.EnvGates`、`verification.SourceGates`、`verification.Inventory` | `Auditor.EnvGates`、`Auditor.Headers` | 拆包；源码层（`SourceGates` 的精化、信息树复核、封表）、`Inventory`、`Perimeter` 不搬 |
| `gate3` 的红行 | `IO.println s!"GATE3 RED formal_math/{path}:{name} {code} {detail}"` | `FM.emitFinding "3" s!"formal_math/{path}" name.toString code detail` | 结构化输出 |
| `EnvGates.run` 的 `6a` 行 | `[声明, 模块, 序列化]` | `["lock", 声明, 模块, 序列化]` | 结构化输出加标签；序列化本身与 v3 一字不差，自测 g6a 夹具的锁哈希原样通过 |
| `EnvGates.finding` | 门 15 打 `GATE15 RED …`，其余门打报告 JSON | 只剩门 15，经 `emitFinding` 输出 | 报告各门不搬 |
| `main` | 每次调用只跑一个门：`3`、`6a`、`15`、`report`、`headers`、`source`、`selfcheck`、`inventory*` | `env` 在一个进程里依次跑门 3、6a、15，共用同一份私有层级环境；任一门内部出错整次退 2；`headers` 见上 | 七步里环境层是一步；旧实现三个门本来就各自加载同一组模块的私有环境 |
| `ChanTest.Probe` 证明体检查 | 只在门 `3`、`report` 前做 | 每次 `env` 都做 | `env` 包含门 3 |
| 派生证书 | `run_gates.py` 把源码层精化时观察到的派生产物写到被审包 `.lake/fm-derived.json`（被审构建可写） | 审计程序仍收 `--derived <文件>`；运行脚本只接受受信目录下的路径（`CERTIFICATE`），**本片没有产生它的一侧，从不传**，第四片接上 | 备忘 3.4：证书改由只解析的源码形状门按派生语法节点位置产生。没给证书时合法派生的辅助函数判红（`ENV_PARTIAL`、门 15 的 `EXPOSE_SECTION`），现状如此、已接受 |
| `headerIssues` 的码 | 第二元是门号 `"3"`，旧运行脚本统一记 `TOKEN` | 改成具体红码 `MODULE_FIRST`、`PRELUDE`、`IMPORT_ALL`/`META_IMPORT`、`IMPORT_PINNED`、`IMPORT_SOURCE` | 一行一条红码；判据与说明文字不变 |
| `readHeader` | 解析失败时抛异常（旧运行脚本退 2） | 返回 `none`，`headers` 记 `HEADER_PARSE` 红 | 被审文件头写坏是被审提交的问题，能判定 |
| 头部方向表（Python） | `run_gates.py` 的 `lane`、`allowed_edge`、`gate15` | 原样搬进 `run.py`；删去 `AUDIT_TOOLS` 两处（审计程序已不在被审包里）；`MODULE_FIRST` 与 `IMPORT_ALL` 改由审计程序报，避免一处两报 | — |
| `lake query` 核对 | 旧门 15 用 `lake query` 核对 Lake 解析的导入与头部一致 | 删去 | 第 4 步在任何 `lake` 调用之前；头部由 Lean 自己的头部解析器读，导入解析不一致会让第 6 步构建失败 |

本次返修（独审 r1 之后）**没有改 `auditor/` 下任何 Lean 文件**：B-1 要求核对的审计程序输出编码已经是 JSON 字符串转义，见「输出与退出码」。

### 未搬的源码层规则

旧门 15 在源码层还有一条「`Chan/Defs` 下的文件须用 `@[expose] public section`」（判据在 `SourceGates.lean` 的 `exposure`，由旧 `run_gates.py` 报 `EXPOSE_SECTION`）。它属于源码形状，**本片不搬，归第四片**。现状：`Chan/Defs` 下只含私有定义、或公开定义都已有公开定义体的文件，不用这个写法也七步全绿；环境层只查「公开定义确有公开定义体」那一半。`fixtures.tsv` 里 `must_red/g15/no-expose` 一行写明了这一点（它现在由构建一步红，只因夹具的另一个文件编译不过）。

### 读环境不跑被审代码（核对后保留）

`Lean.importModules … (level := .private)` 不传 `loadExts`，默认不加载环境扩展，因此 `[init]` 声明不运行；按私有层级加载才看得见证明体里的公理依赖（`env.checked`）。审计程序在沙箱里只读挂载产物，即使有缺陷也写不到宿主机。自测 S17 用 `meta initialize` 把进程名写到标准错误：第 6 步构建时 `lean` 运行了它（正对照），第 7 步审计程序的日志里没有；弱化自测把审计程序改成加载扩展并运行初始化器，S17 即失败。

## 不防什么（本片）

- **构建产物与源码是否对应、产物里的常量有没有经过内核**：第 6 步执行了被审代码，它能改写自己 `.lake` 里的任何产物；第 7 步对「这批产物」如实，诚实作者断言（备忘 3.6）。蓄意对手由 `lake check` 与 `lake comparator` 接（#2315）。
- **畸形 `.olean` 对审计进程本身的影响**：审计程序把产物映射进内存（备忘 3.6 第 5 条，未核实）。沙箱把后果限制在只读视图与标准输出里；输出被伪造成什么样，运行脚本都只认合规的结构化结果。
- **依赖目录的内容**：调用方给的依赖目录被信任；本片只保证被审构建写不到它（只读挂载）。内容可信与否归 `lake check`（#2315）。
- **调用方**：工作目录、依赖目录、git 可执行文件与对象库、`bwrap`、工具链由调用方提供并被信任。由主干版本工作流触发、设为必需检查归 #2315。
- **构建日志的内容**：被审代码能在第 6 步往构建日志里写任何文字，运行脚本只保证它们以转义后的 `FM LOG build …` 行出现在标准错误。给 #2315：不要把两路输出合流后再按行解读；沙箱里只读可见的宿主机路径（`/etc`、`/opt` 等）上的东西可以经构建日志带出，CI 上凡是运行用户可读的凭据必须落在被遮住的 `/home`、`/root`、`/run`、`/var`、`/tmp` 之内。
- **源码形状**：第 5 步未安装。在第四片合入之前，`sorry`、`native_decide`、受控选项、本地元编程、`#eval` 等只要能通过 `lake build --wfail` 与环境层就不会被拦。
- **自举模式**：见上。

## 与设计备忘的偏离

1. **`--packages` 是新增的必填输入**。任务列的输入里没有依赖目录；运行脚本不联网，必须由调用方指出 Mathlib 等的位置。备忘 3.2 要求「沙箱里依赖目录只读挂载」，这里照做。
2. **`--until` 提前停下退 2**。备忘 3.7「0：七步都跑完且全绿」；部分运行不是完整判定。
3. **运行脚本核对自己与受信提交同一 blob**（`RUNNER_MISMATCH`）。备忘 3.1 只要求「在输出里写明代码来自哪个提交」，写明的前提是能核对。
4. **`.lake` 的形状表**（`ARTIFACT_ROOT`、`ARTIFACT_FORM`、`EXTRA_ARTIFACT`、`NO_ARTIFACT`）：第 6 步多出的核对。它属于送审问题「经声明之外的通道影响审计程序的输入」：搜索路径上被审产物在库之后、工具链库之前，被审构建可以在产物目录里放 `Init/…` 遮住工具链的库。
5. **头部规则分在两处**：白名单类在审计程序（Lean），方向表与闭包在运行脚本（Python），各自原样搬自旧实现。
6. **`HEADER_PARSE` 判红而非无法判定**，见搬家差异。
7. **`formal_math/.gitignore`**：按任务并入仓库根 `.gitignore` 并删除。预检返修（`5b6cc3ea16`）后它是 `infra` 的受信文件，获放行可删；仓库根 `.gitignore` 在受管范围以外，不再判红。
8. **门禁目录里不能有 Lake 配置名的文件**（预检 `LAKE_FILE`）：R5-B1 自测夹具里的 `lakefile.toml` 存为 `selftest-cases/r5-b1/hijack-lakefile.toml`，自测造提交时改回原名放到被审树里。

## 自测

```sh
source scripts/fm_env.sh
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh \
  python3 -I formal_math/verification/runner/selftest.py --packages <依赖目录> [--jobs 4] [--cases S1,E2,…] [--skip-corpus]
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh \
  python3 -I formal_math/verification/runner/selftest.py --packages <依赖目录> --mutants [--jobs 4]
```

用临时目录（跟随 `TMPDIR`）现造 git 仓库，仓库路径含空格与非 ASCII；提交用 `hash-object -w`、`mktree`、`commit-tree` 造（畸形树用 `hash-object -t tree --literally`），不检出。每个用例经 `run.py` 跑整条流水线，断言**整次运行**的退出码与红码集合，另对每次运行核对输出协议（`protocol()`：两路都是合法 UTF-8、每行只含可见字符与空格、行前缀合规、恰好一行 `FM RESULT` 且在最后、状态与退出码一致）；运行结束删除各自的工作目录。

**共享依赖目录只读使用。** 骨架用例除 S1、S2、S3、S10 外都用 lite 基线（清单里没有依赖包、配置不 `require`）配临时目录里自建的空「假依赖目录」；凡是尝试往依赖目录写的用例（S7、S22）只会碰到假目录。弱化自测里没有「依赖目录可写」这一种。

骨架用例：

| 编号 | 断言 |
|---|---|
| S1 | 阴性对照：证明角色加一个定理，七步全绿，输出含 `SHAPE 未安装`，首行 `FM MODE baseline` |
| S2 | R5-B1 原样（`infra/hijack`，放行）：第 1 步 `PATH_SCOPE` 判红，只有一行步骤行，受信目录没有建 |
| S3 | 同一提交绕过预检（自测驱动脚本以模块方式载入 `run.py`，从第 2 步起跑；命令行入口没有这个口子）：被审工作区的 `lakefile.toml` 与基线逐字节相同、第 3 步报的审计二进制在本次工作目录的受信目录里、`Bogus.lean` 的 `axiom` 在第 7 步判 `ENV_AXIOM`、`ENV_AXIOM_DEP`、假审计程序的哨兵文件在临时目录与仓库里都不存在 |
| S4 | 基线带仓库根 `.gitattributes`（`export-ignore`、`filter=fmevil`、`eol=crlf`，并给仓库配了会改内容的 smudge 过滤器）：被审文件在工作区里、逐字节等于 blob、模式 0644；对照：`git archive` 的输出里没有它 |
| S5a–e | 五种篡改（驱动脚本包一层沙箱函数改审计程序的输出）：`env` 模块数加一 → `MODULE_COUNT`；`headers` 插一行非 JSON、删一行头部记录 → `AUDITOR_OUTPUT`；`env` 无发现却报红、绿却退 1 → `AUDITOR_OUTPUT`。全部退 2 |
| S6a–b | 第 4 步红：后面没有步骤行、`.lake` 没建；第 6 步红：没有第 7 步行 |
| S7 | 哨兵：被审文件在构建期 `#eval` 尝试写临时目录、本次受信目录、另一个仓库目录、`.lake/packages`（假依赖目录）、被审工作区的 `lake-manifest.json` 与一个源码文件；同时写 `.lake/inside-ok` 作正对照。期望：整次运行恰好因正对照文件报一条 `EXTRA_ARTIFACT`（它不在形状表里）、正对照存在、四个哨兵都不存在、工作区的配置与源码逐字节未变、仓库目录快照（路径与 mtime）不变 |
| S8 | 参数与前置条件：缩写、`--until=3`、重复、缺 `--packages`、`--until 8`、未知开关、工作目录在仓库里、工作目录非空，都退 2、没有步骤行、输出协议合规 |
| S9–S10 | `--until 3` 全绿退 2；`--until 1` 遇红退 1 |
| S11–S12 | 基线缺受信代码：没给自举开关退 2（`NO_TRUSTED_CODE`）；给了则首行写自举、全绿 |
| S13 | 受信提交里的 `run.py` 与正在运行的不同：退 2（`RUNNER_MISMATCH`） |
| S14 | 被审提交在 `Chan/Thm/` 下放 `lakefile.lean`：第 1 步 `LAKE_FILE`，只有一行步骤行 |
| S15 | 用 `hash-object -t tree --literally` 造一棵含两条同名 `Ok.lean` 的 `Chan/Thm` 树：第 1 步 `TREE_FORM` |
| S16a–b | `Chan/Thm/Ok.lean` 的模式是 `100644`、对象实为树（另一例为提交）：经预检在第 1 步 `TREE_FORM`；绕过预检从第 2 步起跑，取料 `GIT` 故障退 2，被审工作区没有建 |
| S17 | 被审模块带 `meta initialize`（把进程名写到标准错误），另一个模块导入它：构建日志里有 `…/bin/lean` 运行它的记录（正对照），第 4、7 步审计程序的日志里没有；整次运行在第 7 步 `ENV_META` |
| S18 | 构建期 `kill -KILL 2`（沙箱里 2 号进程是 `lake`）：第 6 步 `SIGNAL` 退 2，不报 `BUILD_WFAIL` |
| S19 | 构建期无限循环、每 0.2 秒往 `.lake/tick` 追加一行；驱动脚本把第 6 步时限改成 30 秒：`BUILD` 超时退 2；运行结束后再等 2 秒，`tick` 不再增长 |
| S20 | 构建期在 `.lake` 里放 `Init/Fake.olean`、没有源码的 `Chan/Ghost.olean`、名字带多余点的 `Chan/Base.x.olean`、名为 `Chan/Dir.olean` 的目录、指向 `/etc/hostname` 的符号链接、命名管道、`.lake/stray`、`.lake/build/bin/x`，并把 `build/lib/lean/ChanDyn` 改成 0111：逐项比对（红码，路径）集合，十项各报其码（`ChanDyn` 报 `ARTIFACT_FORM`，其中模块因此 `NO_ARTIFACT`） |
| S21 | 基线配置不构建 `ChanDyn`，被审提交加 `ChanDyn/X.lean`：第 6 步 `NO_ARTIFACT` |
| S22 | 沙箱探针：驱动脚本在第 6、7 步各用**同一份挂载与环境**先跑一段 shell。断言两步都只有回环网卡；环境变量只在 `HOME`、`TMPDIR`、`LANG`、`PATH`、`PWD`、`SHLVL`、`_`、`OLDPWD`、`LEAN_PATH`、`LEAN_SYSROOT` 之内（运行脚本自己的环境里放了金丝雀变量）；宿主机临时目录里的金丝雀文件与仓库 `.git` 都不可见；第 6 步受信目录不可见，第 7 步只读可见；第 6 步只有 `.lake` 可写，被审源码、假依赖目录、受信目录都写不进；第 7 步什么都写不进 |
| S24 | 把 `run.py` 复制到一个放了 `re`、`json`、`os`、`sitecustomize`、`traceback`、`posix`、`sys`、`signal`、`stat`、`time` 十个冒名模块的目录，不带 `-I` 运行，两路正常、标准输出关闭、标准错误关闭、两路都关闭、标准输出写满、标准错误写满各一次：都退 2，冒名模块一个都没有被执行 |
| S25 | 标准输出是满的非阻塞管道，0.6 秒后读端才开始读（开头几行因 `EAGAIN` 写不出，后来又写得出）：退 2，至多一行结果行，没有绿结果行 |
| S26a–b | 第 6 步期间给运行脚本发 SIGINT、SIGTERM：标准输出最后一行是 `FM RESULT FAULT build SIGNAL`，退 2，沙箱里的进程随之结束、没有残留进程 |
| S27a–b | 第 4、7 步的审计程序被信号杀死（驱动脚本把审计程序换成 `kill -KILL $$`）：`SIGNAL` 退 2 |
| S28 | 构建期把 `build/lib/lean` 换成指向别处的符号链接：`ARTIFACT_FORM`，不跟随它去核对 |
| S29 | 基线清单列了依赖目录里没有的包：取料 `PACKAGES` 退 2 |
| S30 | umask 077 下取料写出的目录仍是 0755、文件 0644 |
| E1 | 导入名带换行、行分隔符、方向控制符，内容是伪造的 `FM STEP …`、`FM RESULT GREEN` 行：第 4 步红，输出协议不破 |
| E2 | 公理名、定理名、`unsafe def` 名带换行或制表符：第 7 步 `ENV_AXIOM`、`ENV_AXIOM_DEP`、`ENV_UNSAFE`，输出协议不破 |
| E3–E7、E14–E15 | 锁文件：键带换行 → `LOCK_REMOVED` 红；键是孤立代理项、重复的孤立代理项键、值是孤立代理项、`NaN`、普通的重复键、非 UTF-8 字节 → `INPUT` 退 2，没有回溯 |
| E8 | 分支名带换行与 ESC：预检 `BRANCH_ROLE` 红行转出，只转义一次 |
| E9 | 提交名参数带换行、分支名参数非 UTF-8：`BAD_REV` 退 2 |
| E10 | 构建期 `#eval` 打印伪造的 `FM RESULT GREEN`、`FM STEP`、ESC 与行分隔符：整次运行仍是唯一一行真绿，伪造内容只以转义后的 `FM LOG` 行出现在标准错误 |
| E11a–b | 内容路径带换行：经预检 `PATH_GRAMMAR`；绕过预检取料 `CONTENT_PATH` |
| E12 | 内容文件不是 UTF-8：取料 `CONTENT_ENCODING` |
| E13 | 调用方的 `--workdir`、`--packages` 含非 UTF-8 字节与换行：`INTERNAL`（父目录不存在时建目录失败）、`PACKAGES`，退 2，异常消息经转义 |

**弱化自测**（`--mutants`）：把 `runner/`、`precheck/`、`auditor/` 复制到临时目录，先断言未改弱的副本骨架全过，再逐一在副本里改弱一处、用副本自己的自测跑相关骨架用例，每种弱化都必须有用例失败；改弱点在源码里找不到或不唯一时也判失败。共 28 种，清单见 `selftest.py` 的 `MUTANTS`：上一轮的 18 种（其中三种产物核对的改弱点随形状表改写）；独审 r2 另做而自测没抓到的 10 种，除不再适用的一种外都已收进来，共 7 个新改弱点——JSON 接受重复键（R2）、去掉目录项类型检查（R3 产物目录本身是符号链接与 R15 任意层级符号链接是同一处）、绿的结论不再要求标准输出都写出去了（R4）、信号判定只对第 6 步生效（R5b）、JSON 不要求合法 UTF-8（R7）、不核对依赖目录里的包（R8）、建目录后不 `chmod`（R14），R16「去掉顶层只许内容根」与上一轮的「去掉 ARTIFACT_ROOT」是同一处；本轮另加 3 种：目录模式异常或列不出时跳过、不装 SIGINT 与 SIGTERM 处理函数、隔离检查失败时的诊断经 `sys` 的流写且不兜异常（N-1 的旧形）。r2 的「`.olean` 不要求是文件」不再适用：形状表按目录项类型分别查目录表与文件表，名为 `X.olean` 的目录从来查不到文件表，没有单独的「须是文件」一步可改弱（S20 的 `Chan/Dir.olean` 覆盖这个形状）。沙箱不清环境一种同时去掉 `--clearenv` 与「调用 `bwrap` 时只给 `PATH`」两层，只去掉一层时另一层仍挡住、观察不到。

语料用例：`fixtures.tsv` 列出全部旧夹具的归属与本片的实测期望（见下）。只含内容的夹具，基线与被审是同一提交（预检的改动类规则不触发，形状规则照常检查），构建配置按夹具实有的内容根生成；改了构建配置或门禁目录的夹具，基线是模板、被审提交叠上夹具，按证明角色送审。`--discover` 只打印实测结果，供更新表格。

## 旧夹具归属

`fixtures.tsv` 每行：夹具、归属、期望退出码、判红的步骤、红码集合、说明。归属取值：`预检`（第一片）、`取料`、`头部`、`沙箱构建`、`环境层`、`声明锁`、`第四片`（源码形状）、`#2315`、`不再检查`（只靠已删除机制，如工作树与未跟踪文件扫描、运行期版本钉选）。期望列是本片在新入口上的实测，**不是**归属门的承诺：归第四片的夹具现在可能是绿的，表里照实写，第四片合入时改这一列。

汇总（252 个旧夹具；g6b 的 11 个是工作树与分支名来源类，没有在新入口上跑；另有 16 个旧门 1、门 2 的 Lake 配置名夹具已删除，见下）：

| 归属 | 夹具数 | must_red / must_green / must_unknown | 新入口实测：退 1 / 退 0 / 未跑 |
|---|---|---|---|
| 预检 | 9 | 6 / 3 / 0 | 2 / 0 / 7 |
| 预检（规则 `TRUSTED_DRIFT`、`LAKE_FILE`）取代，夹具已删除 | 16 | 15 / 1 / 0 | — / — / 16 |
| 头部 | 78 | 70 / 7 / 1 | 77 / 1 / 0 |
| 沙箱构建 | 13 | 1 / 9 / 3 | 8 / 5 / 0 |
| 环境层 | 16 | 16 / 0 / 0 | 16 / 0 / 0 |
| 声明锁 | 12 | 6 / 6 / 0 | 6 / 6 / 0 |
| 第四片 | 103 | 76 / 27 / 0 | 62 / 41 / 0 |
| 不再检查 | 5 | 2 / 2 / 1 | 0 / 1 / 4 |

要点：

- 归第四片的 76 个必红夹具里，24 个现在整次运行为绿（源码选项写法、`#eval`、`#guard_msgs` 吞告警、`rfl'` 等）；另有 `r4-p3a-eval-percent` 两个现在只因夹具在 `formal_math` 顶层放了模拟宿主机文件 `host_secret_probe.txt` 而被预检判 `TOP_LEVEL`，去掉那个文件仍是绿，所以按漏洞计是 26 个。其余由预检形状、构建（`--wfail`）、头部或环境层兜住。在第四片合入之前这 26 个是已知漏洞，另加「`Chan/Defs` 须用 `@[expose] public section`」这条未搬的规则（见「未搬的源码层规则」）。
- 预检 `d660582472` 起形状规则无条件执行，语料里 22 个夹具因此改由第 1 步 `TOP_LEVEL` 判红：20 个 `r4-p*` 夹具在 `formal_math` 顶层放了 `host_secret_probe.txt`，`g15/bridge` 放了顶层 `Bridge.lean`，`g15/r2-g6-bridge-subdir` 放了顶层 `Helper/` 目录。后两个归属改为预检，前 20 个归属仍是第四片。
- 13 个环境层夹具在第 7 步判出旧期望的码；另 3 个（`private-proof`、`r4-p7a-deriving-spoof`、`r3-a1f/a1g-environment`）整次运行先在构建或头部一步红，它们的环境层码由其它夹具覆盖（`ENV_SORRY` 由 `r4-p5b-guard-msgs-swallow` 覆盖）。九个环境层红码 `ENV_AXIOM`、`ENV_AXIOM_DEP`、`ENV_SORRY`、`ENV_META`、`ENV_EXTERN`、`ENV_UNSAFE`、`ENV_PARTIAL`、`ENV_IMPLEMENTED_BY`、`EXPOSE_SECTION` 都至少有一个夹具在新入口上判出。
- 夹具本身不带锁文件、却有 `Chan/Defs` 等锁定目录里的声明时，全跑会在声明锁一步判 `LOCK_UNLISTED`；含派生的阴性夹具因为没有派生证书判 `ENV_PARTIAL`（已接受）。表里逐行写明。
- 删除的 16 个夹具目录（46 个文件）：`must_green/g1/pins`，`must_red/g1/` 的 `r4-manifest-path-source`、`r4-manifest-url`、`revision`、`toolchain`，`must_red/g2/` 的 `lib-option`、`missing-option`、`r2-a5-build-config`、`r2-a6-build-config`、`r2-a6b-build-config`、`r2-a6c-build-config`、`r2-a6d-build-config`、`r4-p6a-lakefile-invalid-toml`、`r4-p6b-lakefile-more-lean-args`、`r4-p6c-lakefile-package-options`、`unimported-child`。它们服务的 `lakefile` 逐键白名单与门 1 钉选已由「构建配置与基线同一对象」取代；这些形状由预检自测覆盖。`fixtures.tsv` 保留这 16 行，期望列为 `-`。
- `must_green/g3/attributes-whitelist` 自身有告警（`@[no_expose]` has no effect），`--wfail` 判红；旧自测只跑门 3，不构建。
- `must_unknown` 的写坏源码从「无法判定」变成构建或头部一步判红（`HEADER_PARSE`）。

## 待后续片

- 第四片：源码形状门；派生证书的产生一侧（写到受信目录，经 `step_env(ctx, certificate=…)` 交给审计程序）；删除 `run_gates.py`、`selftest.py`、`SourceGates.lean`、`Perimeter.lean`、`Inventory.lean`、`inventory.py`、`make_lists.py`、两份名单、`pins.json` 与旧夹具里只服务已删机制的部分。
- 审阅报告（S、7a、7b、8a、8b、9、10）**没有搬**：旧入口 `run_gates.py --report` 随本片停用，报告暂时不可用。它不阻断，由第四或第五片决定搬去哪里。
- 真实被审包的 `lakefile.toml` 只有 `Chan`、`ChanTest` 两个库：`ChanChallenge/`、`ChanDyn/`、`ChanExplore/` 一旦有文件，第 6 步会因 `NO_ARTIFACT` 判红，需要 `infra` 先补库。
- #2315：由主干版本工作流触发并设为必需检查；CI 上依赖目录的准备与只读挂载。
