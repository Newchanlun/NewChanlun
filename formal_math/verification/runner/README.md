# formal_math 阻断门的运行骨架、独立审计程序与源码形状门（#2312 第二、三、四片；环境层豁免第 4 类）

`run.py` 按固定顺序跑七步，前一步不绿即停；`../auditor/` 是只依赖 Lean 核心的独立 Lake 包，源码与配置取自受信提交，在仓库检出目录之外构建，产物放在被审构建写不到的目录。门禁只审提交，不读工作树。

设计依据：`origin/evidence/2312-design-consult` @ `aedff2e010` 的备忘 3.0–3.7、第四节、第五节第 2–4 条、第六节；#2312 评论 7175991382、7164343103。第一片（`../precheck/`）的输出与退出码风格在这里沿用。

**送审问题（第二片）**：被审提交能否影响哪个审计二进制被执行，或者经声明之外的通道影响它的输入。
**送审问题（第三片）**：环境层、声明锁与暴露检查相对第五轮核实过的实现是否原样搬来，差异见「搬家差异」。
**送审问题（第四片）**：源码形状门是**诚实作者断言**（备忘第五节）。BLOCK 的条件只有三种：点名的写法以明文出现却没判红；必绿语料被误拒；「不防什么」或「谁接」写得不如实（写了由谁接，而接的那一层实际接不住）。用库里冷僻的精化器绕过形状门不构成 BLOCK，除非能说明后果没有人接。规则见「第 5 步：源码形状门」。
**送审问题（自动参数片）**：环境层 `ENV_META` 的第 4 类豁免是否只放行 Lean 为自动参数生成的战术载体，能否被手写声明冒用；豁免放行了什么。见「环境层豁免第 4 类：自动参数的战术载体」。

## 调用

```sh
source scripts/fm_env.sh
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh \
  python3 -I formal_math/verification/runner/run.py [--trusted-change-approved] \
    [--bootstrap-trusted-from <提交>] [--until <1-7>] \
    --repo <仓库> --base <基线提交> --head <被审提交> --branch <分支名> \
    --workdir <工作目录> --packages <依赖目录>
```

- **必须带 `-I`**（隔离模式）。不带时脚本所在目录排在模块搜索路径最前面，同目录的 `json.py`、`re.py` 之类会顶替标准库。`run.py` 开头只用内建模块：`sys` 查 `sys.flags.isolated`；不满足时 `import posix`（`sys` 与 `posix` 都在 `sys.builtin_module_names` 里，由内建导入器在路径查找之前加载，路径上的同名文件顶替不了；`os` 不是内建模块，这段不用它），用 `posix.write` 尽力向两路各写一行（写不出就跳过，异常一律吞掉），然后 `posix._exit(2)`：不走异常处理与收尾钩子，解释器不会再为打印回溯或刷新流去导入任何模块。本机 Python 3.14.4 实测（自测 S24）：两路正常、标准输出关闭、标准错误关闭、两路都关闭、标准输出指向 `/dev/full`、标准错误指向 `/dev/full` 六种状态都退 2，同目录放的 `re`、`json`、`os`、`sitecustomize`、`traceback`、`posix`、`sys`、`signal`、`stat`、`time` 十个冒名模块都没有被执行。`-I` 管不到的：不带 `-I` 时若 `PYTHONPATH` 指向别人能写的目录，解释器在执行 `run.py` 第一行之前就会导入那里的 `sitecustomize`；`python3 -I -m run` 不受支持；`python3 -c "exec(open('run.py').read())"` 之类以 `-c` 加 `exec` 运行也不受支持——不带 `-I` 时当前目录在搜索路径上，解释器在执行 `exec` 的内容之前就会导入当前目录里的冒名模块（本机 Python 3.14.4 实测：冒名目录里的 `linecache.py`、`re.py` 被执行），`run.py` 的隔离检查根本来不及运行。只能按脚本路径调用。这几条交给 #2315 的工作流（调用一律 `python3 -I <路径>/run.py`，不设 `PYTHONPATH`）。
- 参数自己解析，不用 `argparse`：选项只认全名，每个最多一次，取值不得为空或以 `-` 开头；`--x=y`、缩写、未知开关、缺项都退 2。没有任何参数组合能在没做完整判定时退 0：`--until <n>`（n<7）跑完前 n 步且全绿时退 2（`FM RESULT PARTIAL`），遇红仍退 1。
- `--workdir`：调用方给，必须不存在或是空目录，且与仓库检出目录、git 目录、依赖目录互不包含。运行脚本不删除它。
- `--packages`：依赖目录（Mathlib 等，按本次采用的 `lake-manifest.json` 的包名逐个取 `<依赖目录>/<包名>`）。由调用方准备好；运行脚本不联网、不下载。SafeCode 上是 `/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages`。
- `--trusted-change-approved`：原样转给预检。预检放行配置有改动的 `infra` 提交后，第 2 步用候选配置实测。
- 子进程的 git 环境与第一片相同：`LC_ALL=C`、不读系统与全局配置、屏蔽替换对象与 grafts；`GIT_NO_LAZY_FETCH=1` 禁止按需拉取对象，缺对象时退 2。

### 受信代码从哪个提交来

- 默认取自**基线提交**：运行脚本、预检、审计程序包都要在基线的 `formal_math/verification/` 里。
- 正在运行的 `run.py` 必须与受信提交里的 `formal_math/verification/runner/run.py` 是同一个 blob（`git hash-object --no-filters` 比对），否则退 2（`RUNNER_MISMATCH`）。输出第二行 `FM RUNNER blob=<…> from=<受信提交>:<路径>` 写明这一点。门禁只审提交：本地有未提交改动时先提交再跑。
- **自举**：基线缺这三样时，没给 `--bootstrap-trusted-from` 一律退 2（`NO_TRUSTED_CODE`）。给了就从那个提交取受信代码，输出首行写 `FM MODE bootstrap …自举模式：受信代码取自调用方指定的提交，不保证来自主干`。**自举模式不提供「受信代码来自主干」这一保证**，结论只等于「调用方指定的那份门禁对被审提交的判定」。构建配置仍按「取料」规则选取，自举开关不改变配置选择。

### 首次落地自举

#2309 基线 `a5cf477e00` 已有 `Chan/Smoke.lean`，没有门禁。#2312 同批引入受信门禁和基础内容：`ChanTest/Probe.lean`、`ChanDyn/BuildAnchor.lean`、`HISTORY.md`、`formalization.yaml`、`statement-lock.json`。普通 `infra` 放行不允许这些内容变更，`--bootstrap-trusted-from` 只指定受信代码来源，也不会放宽角色规则。首次跨越该基线须人工审批并记账；`Chan/Smoke.lean` 保持基线原样。

把候选提交作为落地后的基线，在 Linux 上用它自己的门禁、构建配置和已准备好的只读依赖运行：

```sh
head=$(git rev-parse HEAD)
python3 -I formal_math/verification/runner/run.py \
  --repo "$PWD" --base "$head" --head "$head" --branch infra/2312-main-landing \
  --workdir "$workdir" --packages "$packages"
```

`workdir` 须是仓库与依赖目录之外的空工作目录或未创建的路径，`packages` 指向预编译依赖。检查第 6 步构建 `Chan.Smoke`、`ChanTest.Probe`、`ChanDyn.BuildAnchor`，最终退出 0 且输出 `FM RESULT GREEN 七步全绿`。这份结果验证候选树落地后可运行；跨旧基线的放行依据仍是一次性人工审批。

## 七步

| 步 | 名字 | 做什么 | 判红码 | 无法判定（退 2）的码 |
|---|---|---|---|---|
| 1 | `precheck` | 从受信提交取出 `precheck.py` 写到 `<工作目录>/step1/`，`python3 -I` 运行，参数是解析后的基线、被审提交全名与分支名。输出逐行核对：退 0 须恰好一行绿行且提交名相符；退 1 须每行都是红行 | 第一片的全部规则码，原样转出 | `PRECHECK_EXIT`、`PRECHECK_OUTPUT`、`PRECHECK` |
| 2 | `fetch` | 受信目录 `<工作目录>/trusted/verification/` ← 受信提交的 `formal_math/verification/` 整棵树。被审工作区 `<工作目录>/audited/` ← 被审提交的内容文件（`Chan/`、`ChanTest/`、`ChanChallenge/`、`ChanDyn/`、`ChanExplore/` 下与顶层 `Chan.lean`、`ChanExplore.lean`）+ 按「取料」选出同一提交的 `lakefile.toml`、`lake-manifest.json`、`lean-toolchain`。见下「取料」 | `CONTENT_PATH`（内容根下有不合文法、不是 100644 普通 `.lean` 文件的条目，或顶层有别的 `.lean`）；`CONTENT_ENCODING`（内容文件不是合法 UTF-8） | `TRUSTED_TREE`、`BASE_CONFIG`、`HEAD_CONFIG`、`NO_PACKAGE`、`NO_CONTENT`、`GIT`、`INPUT`（构建清单）、`PACKAGES`（依赖目录缺清单里的包） |
| 3 | `auditor` | 核对受信 `auditor/lean-toolchain` 与被审工作区的工具链文件逐字节相同；`lean --print-prefix` 定位工具链并核对 `lean --version`；在受信目录里 `lake build`。输出审计二进制的路径与 sha256 | — | `TOOLCHAIN_MISMATCH`、`TOOLCHAIN`、`AUDITOR_BUILD`、`BUILD_OUTPUT_LIMIT` |
| 4 | `headers` | 沙箱里跑 `fm_audit headers <模块> <路径> …`：审计程序只解析文件头，不加载任何导入。头部白名单的发现由审计程序给出；目录方向表、传递闭包、整库导入 Mathlib 由运行脚本按审计程序给的导入列表判定 | `MODULE_FIRST`、`PRELUDE`、`IMPORT_ALL`、`META_IMPORT`、`IMPORT_PINNED`、`IMPORT_SOURCE`、`HEADER_PARSE`（审计程序）；`WHOLE_MATHLIB`、`IMPORT_EDGE`、`IMPORT_CLOSURE`（运行脚本） | `AUDITOR_OUTPUT`、`MODULE_COUNT`、`AUDITOR`、`SIGNAL` |
| 5 | `shape` | 沙箱里先跑 `fm_audit shape-plan`（只解析文件头，按模块制的导入规则算出每个文件在真实构建里加载的库模块），按库模块集合分组，每组一个沙箱进程跑 `fm_audit shape <库模块>… -- <模块> <路径> …`：只加载这组钉选库，逐条**解析**命令、不精化，过白名单与禁用清单。派生目标类语法节点的位置写成派生证书 `<工作目录>/trusted/derived.json`，交第 7 步。见「第 5 步：源码形状门」 | `SHAPE_PARSE`、`SHAPE_COMMAND`、`SHAPE_DECL`、`SHAPE_MODIFIER`、`SHAPE_ATTRIBUTE`、`SHAPE_DERIVING`、`SHAPE_GUARD_MSGS`、`SHAPE_OPTION`、`SHAPE_OPTION_CONTROLLED`、`SHAPE_FORBIDDEN`、`SHAPE_EXPOSE`、`SHAPE_IMPORT` | `AUDITOR_OUTPUT`、`MODULE_COUNT`、`AUDITOR`、`SIGNAL` |
| 6 | `build` | 先在同一沙箱里跑 `lean --version` 作探针，再 `lake build --wfail`（所选配置的默认目标）。之后把被审构建可写的整个 `.lake` 逐项过形状表，见下「产物形状表」 | `BUILD_WFAIL`、`NO_ARTIFACT`、`EXTRA_ARTIFACT`、`ARTIFACT_ROOT`、`ARTIFACT_FORM` | `SANDBOX`、`BUILD`（超时）、`BUILD_OUTPUT_LIMIT`、`SIGNAL`（沙箱顶层进程被信号终止，见「沙箱布局」） |
| 7 | `env` | 另起沙箱，只读挂载被审工作区（含构建产物）、依赖目录与受信目录，跑 `fm_audit env --derived <派生证书> <模块> …`：门 3 环境层、门 15 暴露检查、门 6a 声明锁的规范序列化。运行脚本对锁行求 sha256，与**被审提交**的 `formal_math/statement-lock.json` 逐项比对 | `ENV_AXIOM`、`ENV_AXIOM_DEP`、`ENV_SORRY`、`ENV_META`、`ENV_EXTERN`、`ENV_UNSAFE`、`ENV_PARTIAL`、`ENV_IMPLEMENTED_BY`、`EXPOSE_SECTION`、`LOCK_CHANGED`、`LOCK_REMOVED`、`LOCK_UNLISTED` | `AUDITOR_OUTPUT`、`MODULE_COUNT`、`INPUT`（锁文件缺失或不是严格 JSON 对象）、`NO_CERTIFICATE`（上下文里没有第 5 步写出的那份派生凭证）、`CERTIFICATE`、`AUDITOR`、`SIGNAL` |

运行前的准备（解析参数、解析提交、核对工作目录、受信代码是否齐全、`run.py` 是否就是受信那份）失败时步骤名记 `prepare`，退 2。任何意外异常（含输出函数自身的失败）都归入 `INTERNAL`，退 2，并尝试写结果行 `FM RESULT FAULT`（契约见「输出与退出码」）；`__main__` 外面还有一层兜底，连 `main` 的异常处理都失败时也退 2，不会落成 0 或 1。

### 取料

- 只用 `ls-tree -r -z <提交>:<路径>` 加 `cat-file --batch` 逐个取 blob 原始字节。不用 `git archive`、检出或 `git worktree`，所以被审树里的 `.gitattributes`（`export-ignore`、`filter`、`eol`）与仓库配置的过滤器都不起作用。
- 受信目录里每条路径段须合 `[A-Za-z0-9_][A-Za-z0-9_.-]*` 且是 100644 普通文件，否则退 2。内容文件的每个路径段（去掉 `.lean`）须合模块名文法 `[A-Za-z][A-Za-z0-9_]*`。
- 写文件用 `O_CREAT|O_EXCL|O_NOFOLLOW`，模式固定 0644，目录 0755（建好后再 `chmod`，不受 umask 影响）；已存在或遇到符号链接即失败。
- 默认三份构建配置都取自基线。只有第 1 步实跑判绿、绿行确认 `role=infra`、调用方传入 `--trusted-change-approved`，且三份配置中至少一份实际变化时，才全部取自候选提交。第 2 步摘要写明「配置取自已批准的 infra 候选提交」；缺配置退 2（`HEAD_CONFIG`），无效配置不得按旧配置放行。内容角色与未获放行的运行不使用候选配置；审计程序始终取自受信提交。
- 所选清单从 git 对象严格解析，定下第 7 步搜索路径用的包名，并逐一核对依赖目录（缺了退 2）。第 3 步在被审代码运行前读取取料写出的 `lean-toolchain`，须与受信审计程序的工具链文件一致。第 6 步之后不再读被审工作区里的配置来决定输入。
- **与预检的交接**：模式是文件的条目必须指向 blob。预检（`d660582472` 起）自己核对这一点，不是则 `TREE_FORM` 判红；取料仍保留同一道检查作纵深防御：用 `cat-file --batch` 读每个对象时核对头行类型必须是 `blob`，不是就 `GIT` 故障退 2，这一步发生在建任何目录之前，被审工作区与受信目录都不会写出，更不会把它当空文件写出或跳过。自测 S16 两例（对象实为树、实为提交）各跑两次：经预检在第 1 步 `TREE_FORM`；绕过预检从第 2 步起跑则取料退 2。
- 第 1 步只接受两种预检输出：退 0 且恰好一行绿行；退 1 且每行都是 `PRECHECK RED <码> <对象> <说明>`。红码按 `[A-Z_]+` 原样转出，预检新增的码（`LAKE_FILE`、`TREE_FORM` 等）不需要改运行脚本；其它任何输出（未知格式、退 2 的 `BASE_FORM`、`NOT_ANCESTOR` 等，此时预检已写到标准输出的红行不转出）一律退 2。
- 被审提交里 `formal_math/` 下的其它文件（README、台账等）不进被审工作区。锁文件由运行脚本在第 7 步直接从被审提交的 git 对象读。

### 沙箱布局（第 4–7 步）

`bwrap --ro-bind / /`，`/home`、`/root`、`/run`、`/var`、`/tmp` 与**整个工作目录**先盖成空 tmpfs，再按步回绑；`--clearenv` 后只放回 `HOME=/tmp/home`、`TMPDIR=/tmp`、`LANG=C.UTF-8`、`PATH=<工具链>/bin:/usr/bin:/bin`（第 5、7 步另加 `LEAN_PATH`、`LEAN_SYSROOT`；第 5 步的 `LEAN_PATH` 只有依赖包的 `.lake/build/lib/lean`，没有被审产物）；`--unshare-all`（断网）、`--die-with-parent`、`--new-session`。`bwrap` 进程本身也只拿到 `PATH` 一个环境变量（两层：调用 `bwrap` 时的环境与 `--clearenv`）。**信号**：`bwrap` 只转出它直接启动的那个进程（第 4、5、7 步的审计程序，第 6 步的 `lake` 与探针 `lean --version`）的退出状态。沙箱里由运行脚本直接启动的那个进程以大于等于 128 或负的退出码结束时，归入 `SIGNAL` 退 2（自测 S18、S27）。`lake` 启动的 `lean` 工作进程被杀时，`lake` 把它记成一次构建失败、自己以 1 退出，运行脚本报 `BUILD_WFAIL` 退 1：运行脚本分不清「`lean` 被内核杀掉」与「被审代码自己搞死 `lean`」，构建日志又是被审方可写的。两种情形退出码都非零。超时由运行脚本杀掉 `bwrap` 所在的整个进程组，`--die-with-parent` 带走沙箱里的进程（自测 S19 核对超时后再无写入）。

| 步 | 被审工作区 | `.lake` | 依赖目录 | 受信目录 | 工具链 |
|---|---|---|---|---|---|
| 4 | 只读 | — | 不挂 | 只读 | 只读 |
| 5 | 只读（此时还没有 `.lake`） | — | 只读，挂在原路径 | 只读 | 只读 |
| 6 | 只读 | **可写** | 只读挂到 `.lake/packages` | 不挂（被 tmpfs 盖住） | 只读 |
| 7 | 只读（含产物） | 只读 | 只读，挂在原路径 | 只读 | 只读 |

审计二进制永远是第 3 步在受信目录里构建的那一个，运行脚本按绝对路径执行它，不对被审包调用 `lake exe`。第 7 步的搜索路径由运行脚本按所选构建清单拼出：依赖包的 `.lake/build/lib/lean` 在前，被审产物在后，工具链自带的库由 Lean 追加在最后；第 6 步因此逐项核对 `.lake`（见下）；第 7 步的搜索路径里被审方的部分只有 `.lake/build/lib/lean`，它是核对过的那一部分，审计程序也只经搜索路径读产物。

### 产物形状表（第 6 步，`artifact_reds()`）

被审构建在**宿主机上**只能写到 `.lake`。沙箱里 `/tmp`（含 `HOME=/tmp/home`）、`/dev`、`/dev/shm`、`/var`、`/run`、`/home`、`/root` 也可写，但它们都是 `bwrap` 建的 tmpfs，写进去的东西随沙箱消失、落不到宿主机。构建结束后运行脚本从 `.lake` 起递归遍历每一个目录项：用 `lstat`，不跟随符号链接；每个目录都必须列得出，列不出不跳过而是判红。形状表按 Lake 4.36.0 实际放的东西列（真实仓库与自测构建实测）：

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

真实仓库（3 个内容模块）一次完整构建后 `.lake` 共 64 个目录项，全部在表内：目录 12 个（`build`；`build/lib`、`build/lib/lean`、`lib/lean/Chan`、`lib/lean/ChanTest`；`build/ir`、`ir/Chan`、`ir/ChanTest`；`config`、`config/1`、`config/5`；`packages`），`build/lib/lean` 下文件 39 个（13 个后缀各 3 个），`build/ir` 下文件 9 个（3 个后缀各 3 个），`config` 下文件 4 个；没有符号链接、管道或套接字。

## 输出与退出码

| 退出码 | 含义 |
|---|---|
| 0 | 七步都跑完且全绿，最后一行 `FM RESULT GREEN` |
| 1 | 某一步判红。该步的红行之后是 `FM STEP <n> <名字> RED` 与 `FM RESULT RED`，后面的步骤不跑也不报 |
| 2 | 无法判定，包括参数、前置条件、工具缺失、构建审计程序失败、沙箱探针失败、审计程序输出无法解读或与 git 树对不上、超时、意外异常、`--until` 提前停下。诊断行 `FM FAULT <步骤> <码> <对象> <说明>` 写标准错误 |

- **行协议**。标准输出只有 `FM MODE`、`FM RUNNER`、`FM RED <步骤> <规则码> <路径或对象> <说明>`、`FM STEP <n> <名字> <GREEN|RED> <秒> <备注>` 与 `FM STEP <n> <名字> FAULT <秒>`（`FAULT` 的步骤行没有备注栏）、`FM RESULT <GREEN|RED|FAULT|PARTIAL> …` 五种行；标准错误只有 `FM FAULT <步骤> <码> <对象> <说明>` 与 `FM LOG <来源> <行>` 两种行。**结果行的契约**：标准输出至多一行结果行；**退出码为 0 则恰有一行绿结果行且它是标准输出最后一行**。反过来不成立：出现绿结果行不保证退出码为 0——结果行写出之后、进程退出之前，进程仍可能被信号终止（见下）。**调用方一律以退出码（退出状态）为准，退出码不是 0 时不得因为看到绿结果行而当作通过。**实现：最终状态与退出码先定下来，结果行整次运行只尝试写一次，用一次 `os.write` 写整行（不超过 `PIPE_BUF`，管道上要么整行写出要么一字未写）；写不出就把退出码改成 2，不补写第二行。绿的结论另要求前面每一行都写出去了：前面有任何一行没写出，就不写绿而写 `FM RESULT FAULT output OUTPUT`、退 2（自测 S25）。被 SIGINT、SIGTERM 打断时，处理函数杀掉正在运行的子进程组，先写一行 `FM FAULT` 到标准错误、再写 `FM RESULT FAULT <步骤> SIGNAL`，以 2 退出（自测 S26）。以下情形可能没有结果行或没有 0、1、2 这样的退出码：
  - 被别的信号（如 SIGKILL）终止，或结果行写不出：可能没有结果行，退出码非零。
  - 绿结果行写出之后、进程退完之前到达的 SIGINT、SIGTERM：这时主路径已经返回、解释器在收尾，处理函数不再执行（独审 r3 实测：标准错误里没有 `FM FAULT`，进程以「被 SIGTERM 终止」的状态结束），退出状态既不是 0 也不是 2，绿结果行已留在标准输出。按上面的契约，这不算通过。
  - **两路输出都是阻塞写。** 标准错误是满的、没有人读的管道时，运行脚本会卡在写标准错误上；处理函数也是先写标准错误再写结果行，所以这时发信号同样卡住：既没有结果行，进程也不退出、不产生退出码。**调用方必须持续读取标准错误（或把它重定向到文件），否则运行可能挂起而不退出；调用方应当自己设总超时，超时按失败处理。**
- **一条转义规则，一个函数**（`safe()`）。写进标准输出或标准错误的每一个字段都先经它，不分来源：可见 ASCII（反斜杠除外）与 Unicode 字母、数字、标点、符号原样保留；空格只在最后一栏（说明、日志行）保留；其余一律写成可见形式——ASCII 控制字符、非 UTF-8 字节写 `\xNN`，换行以外的其它码点（行与段分隔符、方向控制符、零宽字符、组合符、孤立代理项、未分配码点）写 `\uNNNN`，大于 U+FFFF 的写 `\UNNNNNNNN`；每个字段最多 400 个字符，超出截断并注明。`emit()` 是唯一写两路输出的函数，它不抛异常。
- **子进程的输出不透传**。git、预检、`lake`（构建审计程序与第 6 步构建）、审计程序的标准错误（构建时连同标准输出）逐行写成 `FM LOG <来源> <行>`。两次 `lake build` 的合并输出按块读取，保留长行的开头，其余字节仍计入限额。每次构建超过 64 MiB 就杀掉进程组，报 `BUILD_OUTPUT_LIMIT` 退 2；读管道和等待进程退出共用同一个单调时钟期限。被审代码在构建期打印的任何文字（包括形似 `FM RESULT GREEN` 的行）因此只能以转义后的日志行出现在标准错误里（自测 E10）。预检红行的对象栏它自己已转义过，运行脚本先还原成原字节再经 `safe()`，不会二次转义。
- **进入输出的外来片段**（逐个有自测）：模块路径（E11）；导入名（E1）；声明名与公理名（E2）；锁文件的键与值（E3–E7）；分支名（E8、E9）；提交名参数（E9）；预检转出的红行（E8、E11a、S2）；`lake` 构建输出（E10、S17）；审计程序的标准错误（S17）；异常消息与调用方路径参数（E13）；审计程序发现行里的说明文字（E1、E2，其中含被审名字）。
- **JSON 一律严格解析**（`strict_json()`）：字节须是合法 UTF-8；重复键、`NaN`/`Infinity`、任何字符串（含键）里的孤立代理项都拒收。锁文件与构建清单不合格退 2（`INPUT`），审计程序输出不合格退 2（`AUDITOR_OUTPUT`）。审计程序用 Lean 的 `Json.compress` 输出，字符串里的换行与控制字符本来就转义成 `\n`、`\u00XX`，名字里的换行打不破它的逐行格式；运行脚本按 `\n` 切行后逐行严格解析，任何一行不合格整次退 2。
- 全部按 UTF-8 字节 `os.write`，不用 `print`（原因同第一片）。
- **运行脚本不凭审计程序的退出码下结论**。审计程序每个子命令在标准输出逐行给 JSON，最后一行是 `["result", 子命令, "red"|"green", 审过的模块数]`。运行脚本核对：每行都能解析且形状对；结果行恰好一条且在最后；判定为红当且仅当有发现行；退出码与判定一致（红 1、绿 0）；模块数与运行脚本从 git 树数出的内容文件数相等；第 4 步还核对头部记录与请求的文件一一对应。任何一条不符都退 2。

## 第 5 步：源码形状门

**断言类别：诚实作者断言。** 它防的是为了让检查变绿而走捷径的作者用明文写出的禁用构造，不承诺挡住蓄意对手用库里冷僻机制的绕过；那些由沙箱、环境层与 #2315 的内核重放（`lake check`、`lake comparator`）承担。两条纪律：**只解析、不精化**；**每条规则写明不防什么、谁来接**。

### 怎么做（备忘 3.5「为什么只解析就够」）

1. `fm_audit shape-plan` 只解析文件头，按 Lean 4.36.0 模块制的加载规则（`Lean.importModulesCore`）算出每个文件在真实构建里会加载的**库**模块：文件自己的直接导入全部算；经被审模块传下来的只算 `public import`（被审模块只以私有级别被加载，它的非公开导入不往下传）。被审模块本身不算。
2. 运行脚本按库模块集合分组（集合完全相同才同组，不用并集环境），每组一个沙箱进程。进程只加载这一组钉选库（`importModules … (loadExts := true) (level := .exported)`，与真实构建的级别相同；隐式的 `Init` 照 `HeaderSyntax.imports` 补上）。加载会运行钉选库的初始化器，它们是受信代码；**被审模块一个都不加载，搜索路径上没有被审产物**（此时 `.lake` 还不存在）。库里没有的模块判 `SHAPE_IMPORT`（只有导入名写错这一种来源；`.olean` 存在却加载失败归无法判定）。
3. 逐条 `Parser.parseCommand`。只有作用域命令 `namespace`、`section`（含 `public section`、`@[expose] public section`、`noncomputable section`）、`end`、`open` 交给 Lean 处理，以维持当前命名空间、`open` 声明与作用域内的语法扩展；`open` 整条失败时（被审命名空间在库环境里不存在）逐个名字重试，其余失败忽略，真实构建会在同一处报错。声明、项、战术一律不精化。`#exit` 与文件头之后的 `import` 是终止命令，判红后停。解析失败即红（`SHAPE_PARSE`），报第一条错误后停。
4. 每条命令的语法树过下表的规则；每个派生目标类语法节点（`Lean.Parser.Command.derivingClass`，行内 `deriving` 与 `deriving instance` 都在内）记下文件与起止位置。

**此时被审代码仍未执行。** 自测 H3：被审文件带 `initialize`、`#eval`、宏定义、`run_cmd` 与宏的使用，第 5 步红（`SHAPE_COMMAND`、`SHAPE_FORBIDDEN`、`SHAPE_PARSE`），这些代码打印的标记不出现在任何日志里，构建目录没有建；正对照：跳过第 5 步时同一个 `#eval` 在第 6 步构建期执行，标记出现在构建日志里。

### 规则（每条一行）

| 断言（红码） | 针对的对手 | 不防什么 | 谁接 |
|---|---|---|---|
| 解析失败即红（`SHAPE_PARSE`） | 只解析的结论与真实构建对不上；写坏的源码 | 作用域跟踪与 Lean 不一致但两边都解析成功的情形（例如被审命名空间与库命名空间同名时 `open` 的相对解析）。自测 H2 与语料的命令数比对覆盖已知写法 | 第 6 步真实构建；解析差异导致的漏判由其余各步与 #2315 接 |
| 命令白名单（`SHAPE_COMMAND`）：`moduleDoc`、`namespace`、`section`、`end`、`open`、`variable`、`universe`、`include`、`omit`、`in`、`declaration`、`mutual`、`set_option`、`check`、`attribute`、`deriving`；`#guard_msgs` 与 `#print axioms` 只许在 `Chan/Final`。`in` 两侧、`mutual` 内、`#guard_msgs` 内的命令照样按命令验 | 本地元编程（`macro`、`syntax`、`elab`、`notation`、`initialize`、`run_cmd`）、`#eval`、`#print`、`export`、Mathlib 的 `lemma` | 白名单内的命令经库精化器在精化期做的任何事（备忘 3.5：库里有通用解释器） | 沙箱（第 6 步）、环境层、#2315 的内核重放 |
| 声明白名单（`SHAPE_DECL`）：`def`、`theorem`、`abbrev`、`opaque`、`example`、`inductive`、`class inductive`、`structure`、`instance` | `axiom` 等不在名单的声明 | 名单内的声明产生什么常量 | 环境层（公理闭包、包内公理声明） |
| 修饰符白名单（`SHAPE_MODIFIER`）：文档注释、属性、`private`、`public`、`protected`、`noncomputable`、`nonrec`；`meta`、`unsafe`、`partial` 与 `meta section` 必红 | 手写 `partial`、`unsafe`、`meta` 定义 | Lean 自动生成的 `partial`／`unsafe` 辅助项（派生处理器、编译影子、`ctorIdx`）；自动参数生成的 `meta` 战术载体 | 环境层按生成来源豁免（三类，含派生证书）；载体按第 4 类豁免 `ENV_META` |
| 属性白名单（`SHAPE_ATTRIBUTE`）：`simp`、`ext`、`instance`、`reducible`、`irreducible`、`inline`、`specialize`、`expose`、`no_expose`、`grind`、`norm_cast`、`push_cast`、`refl`、`symm`、`trans`、`gcongrAttr`、`mono`、`congr`、`elab_as_elim`、`induction_eliminator`、`cases_eliminator`、`deprecated`、`simps`、`method_specs`；按 Lean `elabAttr` 的取名规则（`Attr.simple` 取标识符，其余取语法种类末段），`attribute [-x]` 同样查 | 注册宏、精化器、解析器、初始化器、派生处理器的属性；`implemented_by`、`extern`、`csimp`、`init` | 名单内属性的处理器在精化期做什么；属性宏不展开（见出入表） | 环境层（`implemented_by`、`extern`、`meta` 查全部常量）、内核 |
| 派生目标类白名单（`SHAPE_DERIVING`）：`DecidableEq`、`BEq`、`ReflBEq`、`LawfulBEq`、`Hashable`、`Ord`、`Repr`、`Inhabited`、`Nonempty`，按写出来的标识符比对（去掉 `_root_`） | 名单外的派生处理器 | 名单内派生处理器生成的代码 | 环境层（派生证书只豁免证书位置上的 `partial` 辅助函数）、内核 |
| `#guard_msgs` 的限制（`SHAPE_GUARD_MSGS`）：只许不带规格的精确匹配，内嵌命令只许 `#check` 与 `#print axioms`，只许在 `Chan/Final`（不在时报 `SHAPE_COMMAND`）；`#print axioms` 只许在 `#guard_msgs` 内 | 用期望消息吞掉告警或占位证明 | — | 第 6 步 `--wfail` |
| 任何语法位置的 `set_option` 写法（凡首个子节点是 `set_option` 关键字的节点：命令、`… in`、项、战术、`grind =>` 内）：`autoImplicit`、`relaxedAutoImplicit`、`linter.*` 报 `SHAPE_OPTION_CONTROLLED`（门 2 的源码部分）；其余只许 `maxRecDepth`、`maxHeartbeats`、`synthInstance.maxHeartbeats`、`synthInstance.maxSize`、`match.ignoreUnusedAlts`、`pp.*`，名单外报 `SHAPE_OPTION` | 关告警、关内核检查（`debug.skipKernelTC`）、开 `autoImplicit` | 库宏展开时设置的选项（`rfl'` 展开出 `smartUnfolding`）；库里换了名字的选项设置器 | 构建选项来自第 2 步选定的配置；`smartUnfolding` 之类只影响精化，不影响健全性，证明仍由内核检查（自测语料 `known-not-covered/rfl-prime-false`：用 `rfl'` 证假命题，构建判红）；`debug.skipKernelTC` 之类经冷僻入口的后果由 #2315 的内核重放接 |
| 点名的禁用清单（`SHAPE_FORBIDDEN`），按表层记号查：`sorry`、`admit`、`native_decide`、`include_str`、`eval%`、`by_elab`、`run_tac`、`run_cmd`、`run_meta`、`run_elab`、`sudo`、`trace`、`success_if_fail_with_msg`、`#eval`、`#eval!`、`#exit`；配置项 `+native`／`-native`／`(native := …)`；**旧式配置子句**：任何语法节点，只要前三个子节点依次是记号 `(`、一个名字以 `config` 结尾的记号或标识符、记号 `:=`，就判红（不按语法种类列名单，同 `set_option` 的判法）。钉选库里实际存在的这类子句只有两个名字：`config`（核心 `Lean.Parser.Tactic.config`，被 `plausible`、Batteries 的 `congr`／`rcongr` 复用；Aesop 的 `Aesop.Frontend.Parser.«tactic_clause(Config:=_)»`；新式 `optConfig` 里键为 `config` 的 `valConfigItem`）与 `simp_config`（Aesop 的 `«tactic_clause(Simp_config:=_)»`）；检索方法见下。新式字面量配置项（`(maxSteps := 1000)`、`+contextual`、`-zeta`、`+kernel`）不受影响；项级 `unsafe`（语法种类）；标识符 `sorryAx`（含 `_root_.sorryAx`） | **给走捷径的作者看的提示，不是防线。** 明文的占位证明与精化期求值入口。旧式配置子句的取值在精化期经 `declare_config_elab` 编译求值（独审 r1 甲-1） | 清单外的求值入口：名字不以 `config` 结尾、但库在精化期替被审代码对其中的项求值的子句或战术，本片没有逐个列出；任何经库宏展开出来的同类构造。独审 r1 的调查结论见「已知不防」 | 占位证明与 `native_decide` 落在环境层公理闭包（`ENV_SORRY`、`ENV_AXIOM_DEP`）；构建期的宿主机读写由第 6 步沙箱接；伪造产物由 #2315 的内核重放接 |
| `Chan/Defs` 下的文件须用 `@[expose] public section`（`SHAPE_EXPOSE`，旧门 15 的源码层） | 定义体不对外暴露、下游只能当黑箱用 | 节里的个别定义另加 `@[no_expose]` | 环境层门 15 查公开定义确有公开定义体（`EXPOSE_SECTION`） |
| 库导入存在（`SHAPE_IMPORT`） | 导入名写错 | — | — |

### 派生证书

环境层对「派生处理器生成的 `partial` 辅助函数」的豁免要一份证书（豁免第 3 类）。第 5 步在解析时记下每个派生目标类语法节点的位置，运行脚本校验后写成 `<工作目录>/trusted/derived.json`（`[[模块, 起行, 起列, 止行, 止列], …]`，受信目录，被审构建写不到：第 6 步整个工作目录被 tmpfs 盖住，只回绑被审工作区与 `.lake`）。第 7 步把它交给 `fm_audit env --derived`。运行上下文里凭证的初始值是 `None`（`Run.certificate`）；第 7 步要求它恰是第 5 步写出的 `<工作目录>/trusted/derived.json`，否则 `NO_CERTIFICATE` 退 2（独审 r1 乙条件项 2，自测 S32）。

判据与旧实现一致（旧 `SourceGates.derivedBy`）：常量的声明范围起点（`findDeclarationRanges?`，读的是第 6 步构建产物里的声明范围）落在**同一模块**某个派生目标类语法节点之内，就算派生产物。派生处理器在 `withRef` 该节点下精化生成的命令，手写声明的范围在它自己的语法上。旧实现逐命令只看本命令新增的常量；新实现对全部常量比位置，结果相同（一个位置只属于一条命令）。

对已过审 Lean 文件的改动（只有 `auditor/Main.lean`，`Auditor/EnvGates.lean` 与 `Auditor/Headers.lean` 未动）：

| 位置 | 旧 | 新 |
|---|---|---|
| 导入 | — | 加 `import Auditor.Shape` |
| 新增 `certificate` | — | 读证书文件，严格解码为 `(模块, 起点, 止点)` 数组，格式不合抛错（整次退 2） |
| 新增 `derivedBy` | — | 对每个常量：所在模块有证书条目时取声明范围起点，落在同模块某个区间内（按行、列比较，与旧 `derivedBy` 的 `le` 相同）就放进 `NameSet` |
| `main` 的 `--derived` 分支 | 把证书当作常量名数组读成 `NameSet` | 读成位置数组（`certificate`）；加载环境后由 `derivedBy` 算出同一个 `NameSet`，`gate3` 与门 15 收到的参数类型与用法不变 |
| `main` 的子命令分派 | `headers`、`env` | 另加 `shape-plan`、`shape`（同 `headers` 的异常处理：抛错即退 2） |
| `main` 的文档注释 | — | 加一行子命令说明 |

验收：骨架 README 里因证书缺失被误拒的 12 个旧必绿夹具（`ENV_PARTIAL`）的现状见「旧夹具归属」；手写同名 `partial def` 伪装派生辅助函数的 `r4-p7a2-deriving-spoof*` 仍红（源码在第 5 步 `SHAPE_MODIFIER`；只审环境层的那份在第 7 步 `ENV_PARTIAL`）。自测 D1（合法派生转绿；同一提交证书为空时 `ENV_PARTIAL`）、D2（同一模块里有合法派生，再手写一个 `partial def`，驱动脚本放行第 5 步：只有手写的那个 `ENV_PARTIAL`）。

### 性能

本机（SafeCode，Lean 4.36.0，依赖目录只读）实测，`/usr/bin/time` 读数：

| 读数 | 值 |
|---|---|
| 一组库导入的加载（`Mathlib.Tactic.Common`、`GCongr`、`Linarith`、`Push`、`Tauto`）+ 解析 1 个文件 | 墙钟 1.51 s，最大常驻 951 MiB |
| 同一组 + 50 个文件（每个 18 条命令） | 墙钟 1.63 s，最大常驻 952 MiB：每个文件约 2.4 ms |
| 一组库导入（`Mathlib.Data.Finset.Basic`、`Mathlib.Data.Rat.Defs`）+ 1 个文件 | 墙钟 1.50 s，最大常驻 853 MiB |
| 只有 `Init` + 1 个文件 | 墙钟 0.31 s，最大常驻 288 MiB |
| 真实仓库第 5 步总耗时（3 个文件分 2 组，32 条命令；含 `shape-plan` 与沙箱启动） | 2.8 s（七步：0.3、0.2、11.1、0.1、2.8、6.8、2.4 s） |

备忘 3.5 报的「常驻内存约 3.1 GiB」是原型按私有级别加载；这里按真实构建的 `.exported` 级别加载，常驻不到 1 GiB。时间主要在每组一次的库加载上，组数等于不同的库导入集合数。

### 与设计备忘的出入

1. **分组按模块制的真实加载集合，不是传递导入的全部库模块。** 备忘 3.4 写「只加载该文件传递导入的钉选库环境」，原型 `expB/corpus.py` 把被审模块的全部导入都往下传。Lean 4.36.0 在模块制下只把被审上游的 `public import` 往下传（`importModulesCore` 的 `needsData := needsData && (i.isExported || importAll)`）。按原型的并集会多加载真实构建看不见的库，多出的记号可能把合法标识符解析成关键字而误拒。分组规则因此放在审计程序里（`shape-plan`），运行脚本只按结果分组。
2. **`#exit` 判红**（原型漏的那条，备忘 3.5 已点出）；文件头之后的 `import` 同样判 `SHAPE_COMMAND`。
3. **禁用清单按记号查，另加项级 `unsafe` 的种类与 `sorryAx` 标识符**；原型按种类与记号双查，同一处会报两次。`#eval`、`run_cmd` 等同时不在命令白名单里，一处报 `SHAPE_COMMAND` 与 `SHAPE_FORBIDDEN` 两条。
4. **`SHAPE_IMPORT`**：备忘没有这一条。导入名写错时库环境加载失败，原型记为扫描失败；这里判红，因为来源只能是被审文件。
5. 解析失败后不再继续扫描同一文件（Lean 会恢复并继续，原型也停）。

### 与旧实现（`594e49b5ec` 的 `SourceGates.lean`）的出入

| 项 | 旧 | 新 | 理由 |
|---|---|---|---|
| 机制 | 加载依赖后逐命令精化；精化前查名单与 `Perimeter` 的语法种类、精化器表，精化中封表，精化后复核信息树 | 只解析；只处理作用域命令 | 备忘 3.5、第四节 |
| 项与战术层的语法种类、精化器名单（`syntax-kinds.tsv`、`elaborators.tsv`） | 封闭名单 | 删除 | R5-B4 大面积误拒；备忘第四节 |
| 宏展开后的再检查、`OptionInfo` 复核、命令前后受控选项一致、`hasSorry` 标签 | 有 | 删除 | 只解析看不见；占位证明由禁用清单与环境层 `ENV_SORRY` 接；用户裁定与主控定稿接受这两处字面出入 |
| 属性名 | 先 `expandMacros` 再取名 | 不展开，直接取名 | 只解析。后果：属性宏（如 `simps!`、`simps?`、`to_additive?`）的种类末段不在名单里，判红；名单本身未改 |
| 派生目标类 | 在作用域里 `resolveGlobalConstNoOverload` 后比全名 | 比写出来的标识符（去掉 `_root_`） | 只解析。后果：`deriving Std.Hashable` 这类写法判红；真名单内的类写法放行 |
| 修饰符 | `meta`、`unsafe` 在禁用种类里，`partial` 在源码层另判 | 修饰符槽位白名单（文档注释、属性、`private`、`public`、`protected`、`noncomputable`、`nonrec`） | 任务要求的白名单形状；判红集合与旧实现相同 |
| 禁用项 | 种类：`Term.sorry`、`tacticAdmit`、`tacticSorry`、`nativeDecide`、`runTac`、`Term.runMeta`、`Attr.extern`、`Command.meta`、`Command.unsafe`；记号：`implemented_by`、`native_decide`、`run_tac`、`run_meta`；标识符 `sorryAx`；`include_str` 等由精化器名单挡 | 点名清单（上表）；`implemented_by`、`extern` 只由属性白名单管 | 精化器名单删除后，原先靠它挡的求值入口要点名 |
| 配置项 | `Perimeter.configIssues`：只许 `+名`、`-名` 与字面量取值，`native` 与旧式 `config` 不许 | 查 `native`；旧式配置子句按记号形状查（`(`、以 `config` 结尾的名字、`:=`），覆盖核心 `config` 种类、Aesop 的 `config`／`simp_config` 子句与新式 `valConfigItem` | 字面量限制属于项层名单，随之删除；旧实现靠精化器名单挡 Aesop 子句，名单删除后要点名（独审 r1 甲-1） |
| `ChanExplore` | 注释写「另外只多放行 `#eval`」，实际不放行 | 同一套规则 | 注释过时（R5 建议 3） |
| 选项名单、命令名单、声明名单、属性名单、派生名单、`#guard_msgs` 限制、`exposure` 判据 | — | 原样 | — |

## 审计程序包 `../auditor/`

| 文件 | 来源 | 内容 |
|---|---|---|
| `lakefile.toml`、`lake-manifest.json`、`lean-toolchain` | 新写 | 包名 `fm_auditor`，库 `Auditor`，可执行 `fm_audit`（`supportInterpreter = true` 照旧），无依赖；工具链与被审包相同，第 3 步核对 |
| `Main.lean` | `../Audit.lean`（旧文件已删，最后一版在 `594e49b5ec`） | 门 3 环境层（`allowedAxioms`、`expectedCtorIdx`、`ctorIdxImpl`、`generatedBy`、`gate3`）原样；`main` 分派 `headers`、`shape-plan`、`shape`、`env` 四个子命令；第四片在这里接派生证书（`certificate`、`derivedBy`，见「派生证书」） |
| `Auditor/EnvGates.lean` | `../EnvGates.lean` 第 1–108、814–838 行 | `Entry`、`within`、`locked`、声明锁 v3 的规范序列化（`statement`）、`run` 的 `6a` 与 `15` 分支 |
| `Auditor/Headers.lean` | `../SourceGates.lean` 第 13–29、37–45、361–385 行 | 文件头解析（`Parser.parseHeader`，不加载导入）、三张库根表、`headerIssues` |
| `Auditor/Shape.lean` | 第四片新写；名单内容搬自 `../SourceGates.lean` 第 47–131、225–229 行，作用域处理与命令循环以备忘原型 `expB/Shape.lean` 为起点 | 源码形状门：`shape-plan`、`shape` 两个子命令 |

子命令：

- `fm_audit headers <模块> <路径> …`：每个文件一行 `["header", 路径, 模块, isModule, [[导入, 行, importAll, isMeta], …]]`，头部白名单的发现一行 `["finding", "headers", 路径, 行号, 红码, 说明]`，最后 `["result", "headers", 判定, 文件数]`。
- `fm_audit shape-plan <模块> <路径> …`：每个文件一行 `["plan", 路径, 模块, [库模块, …]]`，最后 `["result", "shape-plan", "green", 文件数]`。不加载任何环境。
- `fm_audit shape <库模块>… -- <模块> <路径> …`：每个文件一行 `["file", 路径, 模块, 命令数]`，每个派生目标类语法节点一行 `["derive", 路径, 模块, 起行, 起列, 止行, 止列]`，发现一行 `["finding", "shape", 路径, 行号, 红码, 说明]`，最后 `["result", "shape", 判定, 文件数]`。运行脚本核对：分组行与内容文件一一对应；每组的文件行与请求一一对应、发现只落在本组文件上、模块数等于本组文件数；所有组合起来覆盖全部内容文件。任何一条不符都退 2。
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
| 派生证书 | `run_gates.py` 把源码层精化时观察到的派生产物（常量名）写到被审包 `.lake/fm-derived.json`（被审构建可写） | 第四片：第 5 步写到受信目录的 `derived.json`，内容是派生目标类语法节点的位置；环境层用常量的声明范围比对，见「派生证书」。运行脚本只接受受信目录下的路径（`CERTIFICATE`） | 备忘 3.4：证书改由只解析的源码形状门按派生语法节点位置产生。没给证书时合法派生的辅助函数判红（`ENV_PARTIAL`、门 15 的 `EXPOSE_SECTION`），现状如此、已接受 |
| `headerIssues` 的码 | 第二元是门号 `"3"`，旧运行脚本统一记 `TOKEN` | 改成具体红码 `MODULE_FIRST`、`PRELUDE`、`IMPORT_ALL`/`META_IMPORT`、`IMPORT_PINNED`、`IMPORT_SOURCE` | 一行一条红码；判据与说明文字不变 |
| `readHeader` | 解析失败时抛异常（旧运行脚本退 2） | 返回 `none`，`headers` 记 `HEADER_PARSE` 红 | 被审文件头写坏是被审提交的问题，能判定 |
| 头部方向表（Python） | `run_gates.py` 的 `lane`、`allowed_edge`、`gate15` | 原样搬进 `run.py`；删去 `AUDIT_TOOLS` 两处（审计程序已不在被审包里）；`MODULE_FIRST` 与 `IMPORT_ALL` 改由审计程序报，避免一处两报 | — |
| `lake query` 核对 | 旧门 15 用 `lake query` 核对 Lake 解析的导入与头部一致 | 删去 | 第 4 步在任何 `lake` 调用之前；头部由 Lean 自己的头部解析器读，导入解析不一致会让第 6 步构建失败 |

第三片返修（独审 r1 之后）没有改 `auditor/` 下任何 Lean 文件。第四片对已过审 Lean 文件的改动只在 `Main.lean`，逐处见「派生证书」；`Auditor/EnvGates.lean`、`Auditor/Headers.lean` 一字未改。自动参数片的改动见「环境层豁免第 4 类」的「对已过审 Lean 文件的改动」。

### 旧门 15 的源码层规则（第四片已搬）

「`Chan/Defs` 下的文件须用 `@[expose] public section`」（旧 `SourceGates.lean` 的 `exposure`，旧码 `EXPOSE_SECTION`）现由第 5 步报 `SHAPE_EXPOSE`，判据原样：顶层命令里有一条 `section`，其头部带 `@[expose]` 与 `public`。环境层的门 15 仍查另一半「公开定义确有公开定义体」（`EXPOSE_SECTION`）。

### 读环境不跑被审代码（核对后保留）

`Lean.importModules … (level := .private)` 不传 `loadExts`，默认不加载环境扩展，因此 `[init]` 声明不运行；按私有层级加载才看得见证明体里的公理依赖（`env.checked`）。审计程序在沙箱里只读挂载产物，即使有缺陷也写不到宿主机。自测 S17 用 `meta initialize` 把进程名写到标准错误：第 6 步构建时 `lean` 运行了它（正对照），第 7 步审计程序的日志里没有；弱化自测把审计程序改成加载扩展并运行初始化器，S17 即失败。

## 环境层豁免第 4 类：自动参数的战术载体

独审 r1 N1：`ok : pos ≤ size := by omega` 这类写法前六步全绿、第 7 步 `ENV_META`。原因：Lean 4.36.0 `Lean/Elab/Binders.lean:92` 的 `declareTacticSyntax` 把 `:= by tac` 的战术块存成一个 `Lean.Syntax` 类型的辅助定义（值由 `quoteAutoTactic` 引号化而成）并 `markMeta`。本片给 `ENV_META` 加一类窄豁免，其余红码不动。

### 生成点（实测，Lean 4.36.0）

生成出来的载体都是：普通定义、`safe`、提示 `opaque`、无宇宙参数、类型 `Lean.Syntax`、带 `meta`、无 `implemented_by`／`extern`、没有声明范围；值只由 `Syntax.node`、`SourceInfo.none`、`Name.mkStrN`（超过 8 段或含数字段的名称用 `Name.anonymous`/`Name.str`/`Name.num`，数字按 `OfNat.ofNat Nat` 编码）、`Array.push`、`Array.empty`、`mkAtom`（标识符另有 `Syntax.ident`、`String.toRawSubstring`、`List` 及 `Syntax.Preresolved.namespace`/`Syntax.Preresolved.decl` 构造）组成。除 `ENV_META` 外不触发环境层任何红码（公理闭包为空；门 15 因没有声明范围跳过；`mutual` 的 `_unsafe_rec` 引用载体，由第 2 类豁免照常放行）。

| 写法 | 常量名 | 被谁的类型或定义体／证明体以 `autoParam _ <载体>` 引用 |
|---|---|---|
| 结构体字段 `f : p := by tac` | `S.f._autoParam` | `S.mk`、`S.mk._flat_ctor`、`injEq`／`inj`／`noConfusion`／`sizeOf_spec`；继承它的子结构的 `_flat_ctor` |
| 子结构覆写 `f := by tac` | `Child.f._autoParam` | `Child.mk._flat_ctor` |
| `class` 字段 | `C.f._autoParam` | `C.mk`、`_flat_ctor`、`noConfusion` |
| `def`、`theorem`、`abbrev` 的绑定器（含 `private`、`protected`、`mutual`） | `<声明>._auto_<n>`；私有为 `_private.<模块>.0.<声明>._auto_<n>` | 声明本身；`mutual` 时另有 `_unsafe_rec`、`_sunfold` |
| 类型里的 `∀ (h : p := by tac)`（含 `abbrev` 类型别名体） | `<声明>._auto_<n>` | 声明本身的类型或定义体与它的 `_proof_` 辅助 |
| `def`／`theorem` 局部 `let`、`have` 绑定器 | `_private.<模块>.0.<声明>._auto_<n>`（`theorem` 异步证明块内可生成多段数字后缀，如 `_auto_1_1`） | 宿主声明的定义体或证明体 |
| `structure` 参数 | `S._auto_<n>` | `S`、`S.mk`、投影、`ctorIdx` 等 |
| `inductive` 构造子参数 | `I._auto_<n>` | `I.mk` 等 |
| `variable` 绑定器 | `_private.<模块>.0._auto_<N>`，一处 `variable` 会生成多个（实测 1 条定理时 2 个），N 是模块内计数 | **没有任何引用**（见「已知问题」） |
| `example` 绑定器 | 不留下常量 | — |
| `instance` 绑定器 | Lean 自己拒绝（无法由类型类推断） | — |
| `optParam`（`:= 值`） | 不生成常量 | — |
| 类型里直接写 `autoParam p c`，`c` 是手写的非 `meta` 定义 | 使用处 Lean 报 `Cannot evaluate constant … neither marked nor imported as meta` | — |

`deriving`（`Repr`、`DecidableEq`、`BEq`、`Hashable`、`Ord`、`Inhabited`）用在带自动参数的类型上，不多出 `meta` 常量（`deriving Nonempty` 是 Lean 自己失败）。派生处理器只在类型本身是 `meta` 时给产物打 `meta`（`Deriving/Basic.lean:263`、`Deriving/Inhabited.lean:133`）。`notation`、`macro` 第 5 步禁止，与本类无关。

### 判据（`Auditor/EnvGates.lean` 的 `autoParamCarriers`）

带 `meta` 的常量同时满足下列各条才不报 `ENV_META`，判据全部从构建产物的环境现算，不用源码层给的任何信息：

1. 名字末段是 `_autoParam` 或 `_auto_<数字>`（可多段，如 `_auto_1_1`；附加条件，不是唯一依据）；
2. 普通定义（`defnInfo`）、`safe`，无 `implemented_by`、无 `extern`；无宇宙参数、提示为 `opaque`；
3. 类型恰为 `Lean.Syntax`（定义上相等的别名不算）；
4. 同一模块里另有常量的**类型或定义体／证明体**含 `autoParam _ <该常量>`；
5. 值按 `quoteAutoTactic` 的输出形状解码成语法树，再用 Lean 自己的 `Lean.Elab.Term.quoteAutoTactic` 重算，与值逐字相等（`==`）。同第 1 类豁免「按生成器重算后逐字相同」的做法；这里调用的就是同一工具链里的生成函数，不另抄一份。

`extern` 仍无任何豁免；`unsafe`、`partial`、`implemented_by` 的判定不受本类影响，照旧由前三类管。

### 为什么冒用不了

- **手写声明满足不了第 2 条**：源码写的 `def` 的提示一律是 `regular`（`abbrev` 是 `abbrev`，`opaque` 关键字产出的是 `opaqueInfo`、不是普通定义），写不出提示为 `opaque` 的普通定义。所以逐字照抄生成值、名字和引用都对的手写 `meta def` 也判红（夹具 `Copy.lean`）。另外 `meta` 修饰符本身第 5 步就判 `SHAPE_MODIFIER`；下面的夹具按「只审环境层」跑，证明环境层自己也拦得住。
- 第 3、5 条对**源码写得出的冒用**是冗余的（已被第 2 条挡住）。它们防的是产物被伪造时载体形态不符的情形。单元自测 U1 证明的是「判定函数按所写判据工作」，**不**证明流水线能防伪造产物；伪造产物归 #2315 的内核重放与 `lake comparator`。
- 冒用夹具 `must_red/autoparam/spoofs`（语料用例与骨架 A2，跳过第 5 步）：

| 文件 | 形态 | 结果 |
|---|---|---|
| `Copy.lean` | 手写 `meta def`，名字、类型、值都与 `by omega` 生成的逐字相同，被 `autoParam` 引用 | `ENV_META`（第 2 条：提示 `regular`） |
| `Orphan.lean` | 同形值，没有任何引用 | `ENV_META` |
| `Call.lean` | 值里有函数调用 `mkAtom ("om" ++ "ega")` | `ENV_META` |
| `Ref.lean` | 值里引用别的 `meta` 常量 | 两个都 `ENV_META` |
| `Alias.lean` | 类型是 `abbrev SpSyn := Lean.Syntax` | `ENV_META` |
| `Name.lean` | 名字形态不对 | `ENV_META` |
| `Unsafe.lean` | `meta unsafe def`，由 `unsafe def` 引用 | `ENV_META`、`ENV_UNSAFE`（引用者另报 `ENV_UNSAFE`） |
| `Impl.lean` | `@[implemented_by …] meta def` | `ENV_META`、`ENV_IMPLEMENTED_BY`（目标另报 `ENV_META`） |
| `PostImpl.lean` | 给真生成的载体事后 `attribute [implemented_by …]` | `ENV_META`、`ENV_IMPLEMENTED_BY` |
| `PostExtern.lean` | 给真生成的载体事后 `attribute [extern …]` | `ENV_META`、`ENV_EXTERN` |
| `Legit.lean` | 对照：合法的字段默认证明 | 不出现在红行里 |

`partial` 的同形定义用源码写不出：不递归的 `meta partial def` 被 Lean 降成普通安全定义（就是 `Copy.lean` 的形态）；递归的 `partial def` 产出 `opaqueInfo` 与 `_unsafe_rec`，不是普通定义。第 2 条的「无宇宙参数」与「提示 `opaque`」的反例、类型与值的反例由单元自测 U1 覆盖（用 `addDecl` 直接造，属于伪造产物一类，只用来测判定函数）。

### 这条豁免放行了什么（不防什么）

被豁免的常量是一段战术的语法树。别处使用这个结构体或函数、省略该参数时，精化器经 `evalSyntaxConstant` 取出它、再把战术插进使用处执行（`Lean/Elab/App.lean:832`、`StructInst.lean:1122`）。

- **战术文字本身在被审源码里，已被第 5 步逐节点查过**。实测：战术块里写 `sorry`、`admit`、`native_decide`、`decide +native`、`(config := …)` 报 `SHAPE_FORBIDDEN`，`set_option debug.skipKernelTC true in …` 报 `SHAPE_OPTION`；名单内的 `set_option maxRecDepth … in` 照常放行。使用处插进去的战术在第 6 步构建时运行（沙箱内），证明照常由内核检查，占位证明与 `native_decide` 的后果落在公理闭包（`ENV_SORRY`、`ENV_AXIOM_DEP`）。
- **形状门看不到的两种情形**：
  1. 手写 `autoParam p <库里的某个 meta 载体>`：形状门绿。执行的是受信库里的语法，不在被审模块里生成常量，与本豁免无关。
  2. 运行时取载体用的是编译后的代码（`evalConstCheck`），不是内核里的值；产物被伪造时两者可以不一致。归 #2315。

### 对已过审 Lean 文件的改动

| 文件 | 改动 |
|---|---|
| `Auditor/EnvGates.lean` | 只加本类的判定 `autoParamCarriers` 与它的辅助函数（`quotedName`、`quotedList`、`quotedPreresolved`、`quotedSyntax`、`carrierName`），既有代码一字未改 |
| `Main.lean` | 3 处：`gate3` 循环前取 `let carriers ← FM.autoParamCarriers entries`；`ENV_META` 的判断加 `&& !carriers.contains name`；`generatedBy` 文档注释里「`extern`、`meta` 不在任何豁免之内」改为「`extern` 不在任何豁免之内；`meta` 只豁免自动参数的战术载体」 |

## 不防什么（骨架与环境层）

- **构建产物与源码是否对应、产物里的常量有没有经过内核**：第 6 步执行了被审代码，它能改写自己 `.lake` 里的任何产物；第 7 步对「这批产物」如实，诚实作者断言（备忘 3.6）。蓄意对手由 `lake check` 与 `lake comparator` 接（#2315）。
- **伪造 `.olean` 骗到派生豁免**（独审 r1 乙条件项 1）：派生凭证比对的声明范围读自被审构建的产物。能伪造 `.olean` 的一方可以把手写常量的声明范围安排进某个 `deriving` 区间，骗到第 3 类豁免（只掩盖一个 `partial` 标记，不涉及陈述）。前提是产物被伪造，归 #2315 的内核重放与 `lake comparator`。
- **畸形 `.olean` 对审计进程本身的影响**：审计程序把产物映射进内存（备忘 3.6 第 5 条，未核实）。沙箱把后果限制在只读视图与标准输出里；输出被伪造成什么样，运行脚本都只认合规的结构化结果。
- **依赖目录的内容**：调用方给的依赖目录被信任；本片只保证被审构建写不到它（只读挂载）。内容可信与否归 `lake check`（#2315）。
- **调用方**：工作目录、依赖目录、git 可执行文件与对象库、`bwrap`、工具链由调用方提供并被信任。由主干版本工作流触发、设为必需检查归 #2315。
- **构建日志的内容**：被审代码能在第 6 步往构建日志里写任何文字，运行脚本只保证它们以转义后的 `FM LOG build …` 行出现在标准错误。给 #2315：不要把两路输出合流后再按行解读；沙箱里只读可见的宿主机路径（`/etc`、`/opt` 等）上的东西可以经构建日志带出，CI 上凡是运行用户可读的凭据必须落在被遮住的 `/home`、`/root`、`/run`、`/var`、`/tmp` 之内。
- **源码形状**：第 5 步是诚实作者断言，逐条的「不防什么、谁接」见「第 5 步：源码形状门」。
- **自动参数的战术载体**（第 4 类豁免）：见「环境层豁免第 4 类」的「这条豁免放行了什么」。
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
9. **内容文件须是合法 UTF-8**（`CONTENT_ENCODING`）：第 2 步取料时判红。此前非 UTF-8 的内容文件让审计程序读文件头时抛异常、整次退 2（独审 r1 建议 4）；新入口把它当被审提交的问题，且不改审计程序（`auditor/` 的 Lean 已过审）。
10. **必须以 `python3 -I` 运行**（`NOT_ISOLATED`）：备忘没有提调用方式。运行脚本取自受信提交，但同目录或搜索路径上的冒名模块能在它的任何检查之前被执行，隔离模式是这条前提的唯一保障，见「调用」。
11. **`SIGNAL` 归类**：沙箱里由运行脚本直接启动的那个进程被信号终止时归入无法判定退 2，`lean` 工作进程被杀仍表现为构建失败退 1（见「沙箱布局」）；运行脚本自己收到 SIGINT、SIGTERM 时写 `FM RESULT FAULT … SIGNAL` 退 2（见「输出与退出码」）。备忘 3.7 只列了「工具缺失、崩溃、超时」等无法判定的情形。

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

骨架用例。标 † 的用例要让被审代码在构建期执行（`#eval`、`meta initialize`、`axiom` 等第 5 步会拒的写法），经驱动脚本跳过第 5 步（`FM_SELFTEST_SKIP_SHAPE`，派生证书为空）；命令行入口没有这个口子。


| 编号 | 断言 |
|---|---|
| S1 | 阴性对照：证明角色加一个定理，七步全绿，第 5 步是真的形状检查（输出里没有「未安装」），首行 `FM MODE baseline` |
| S2 | R5-B1 原样（`infra/hijack`，放行）：第 1 步 `PATH_SCOPE` 判红，只有一行步骤行，受信目录没有建 |
| S3 † | 同一提交绕过预检（自测驱动脚本以模块方式载入 `run.py`，从第 2 步起跑；命令行入口没有这个口子）：被审工作区的 `lakefile.toml` 与基线逐字节相同、第 3 步报的审计二进制在本次工作目录的受信目录里、`Bogus.lean` 的 `axiom` 在第 7 步判 `ENV_AXIOM`、`ENV_AXIOM_DEP`、假审计程序的哨兵文件在临时目录与仓库里都不存在 |
| S4 | 基线带仓库根 `.gitattributes`（`export-ignore`、`filter=fmevil`、`eol=crlf`，并给仓库配了会改内容的 smudge 过滤器）：被审文件在工作区里、逐字节等于 blob、模式 0644；对照：`git archive` 的输出里没有它 |
| S5a–h | 八种篡改（驱动脚本包一层沙箱函数改审计程序的输出）：`env` 模块数加一 → `MODULE_COUNT`；`headers` 插一行非 JSON、删一行头部记录 → `AUDITOR_OUTPUT`；`env` 无发现却报红、绿却退 1 → `AUDITOR_OUTPUT`；`shape` 模块数加一 → `MODULE_COUNT`；`shape` 删一行文件行、`shape-plan` 插一行不存在的文件 → `AUDITOR_OUTPUT`。全部退 2 |
| S6a–b | 第 4 步红：后面没有步骤行、`.lake` 没建；第 6 步红：没有第 7 步行 |
| S7 † | 哨兵：被审文件在构建期 `#eval` 尝试写临时目录、本次受信目录、另一个仓库目录、`.lake/packages`（假依赖目录）、被审工作区的 `lake-manifest.json` 与一个源码文件；同时写 `.lake/inside-ok` 作正对照。期望：整次运行恰好因正对照文件报一条 `EXTRA_ARTIFACT`（它不在形状表里）、正对照存在、四个哨兵都不存在、工作区的配置与源码逐字节未变、仓库目录快照（路径与 mtime）不变 |
| S8 | 参数与前置条件：缩写、`--until=3`、重复、缺 `--packages`、`--until 8`、未知开关、工作目录在仓库里、工作目录非空，都退 2、没有步骤行、输出协议合规 |
| S9–S10 | `--until 3` 全绿退 2；`--until 1` 遇红退 1 |
| S11–S12 | 基线缺受信代码：没给自举开关退 2（`NO_TRUSTED_CODE`）；给了则首行写自举、全绿 |
| S13 | 受信提交里的 `run.py` 与正在运行的不同：退 2（`RUNNER_MISMATCH`） |
| S14 | 被审提交在 `Chan/Thm/` 下放 `lakefile.lean`：第 1 步 `LAKE_FILE`，只有一行步骤行 |
| S15 | 用 `hash-object -t tree --literally` 造一棵含两条同名 `Ok.lean` 的 `Chan/Thm` 树：第 1 步 `TREE_FORM` |
| S16a–b | `Chan/Thm/Ok.lean` 的模式是 `100644`、对象实为树（另一例为提交）：经预检在第 1 步 `TREE_FORM`；绕过预检从第 2 步起跑，取料 `GIT` 故障退 2，被审工作区没有建 |
| S17 † | 被审模块带 `meta initialize`（把进程名写到标准错误），另一个模块导入它：构建日志里有 `…/bin/lean` 运行它的记录（正对照），第 4、7 步审计程序的日志里没有；整次运行在第 7 步 `ENV_META` |
| S18 † | 构建期 `kill -KILL 2`（沙箱里 2 号进程是 `lake`）：第 6 步 `SIGNAL` 退 2，不报 `BUILD_WFAIL` |
| S19 † | 构建期无限循环、每 0.2 秒往 `.lake/tick` 追加一行；驱动脚本把第 6 步时限改成 30 秒：`BUILD` 超时退 2；运行结束后再等 2 秒，`tick` 不再增长 |
| S20 † | 构建期在 `.lake` 里放 `Init/Fake.olean`、没有源码的 `Chan/Ghost.olean`、名字带多余点的 `Chan/Base.x.olean`、名为 `Chan/Dir.olean` 的目录、指向 `/etc/hostname` 的符号链接、命名管道、`.lake/stray`、`.lake/build/bin/x`，并把 `build/lib/lean/ChanDyn` 改成 0111、把合法名文件 `Chan/Base.ilean` 改成 0755：逐项比对（红码，路径）集合，十一项各报其码（`ChanDyn` 与 0755 的 `Base.ilean` 报 `ARTIFACT_FORM`，其中模块因此 `NO_ARTIFACT`） |
| S21 | 基线配置不构建 `ChanDyn`，被审提交加 `ChanDyn/X.lean`：第 6 步 `NO_ARTIFACT` |
| S22 | 沙箱探针：驱动脚本在第 5、6、7 步各用**同一份挂载与环境**先跑一段 shell（第 5 步与第 7 步的断言相同：受信目录只读可见、什么都写不进）。断言两步都只有回环网卡；环境变量只在 `HOME`、`TMPDIR`、`LANG`、`PATH`、`PWD`、`SHLVL`、`_`、`OLDPWD`、`LEAN_PATH`、`LEAN_SYSROOT` 之内（运行脚本自己的环境里放了金丝雀变量）；宿主机临时目录里的金丝雀文件与仓库 `.git` 都不可见；第 6 步受信目录不可见，第 7 步只读可见；第 6 步只有 `.lake` 可写，被审源码、假依赖目录、受信目录都写不进；第 7 步什么都写不进 |
| S31 | 绿结果行写出之后、主路径返回之前，驱动脚本让运行脚本给自己发 SIGTERM：处理函数里的 `finish()` 被「整次运行至多写一次」挡住，标准输出仍只有那一行绿结果行，`FM FAULT … SIGNAL` 写到标准错误，退 2（单向契约下允许；不套用 `protocol()` 的双向核对）。骨架复审 r3 的缺口 Q5 |
| S32 | 驱动脚本跳过第 5 步且不写派生凭证：第 7 步 `NO_CERTIFICATE` 退 2（不靠 `INTERNAL` 兜底）。其余跳过第 5 步的用例（†）与环境层、声明锁语料由驱动脚本有意写一份空凭证 `[]` 到同一路径，照常走到第 7 步 |
| S33 | 派生凭证非空但不是第 5 步写出的那一份（驱动脚本把它指向受信目录里另一个存在的文件 `verification/runner/run.py`）：第 7 步 `NO_CERTIFICATE` 退 2（独审 r2 乙-C1，钉住条件的路径比对那一半） |
| S34a、S34b | 已批准的纯配置 `infra` 提交：无效 TOML 在第 6 步判红；合法 TOML 逐字取自候选提交，七步全绿 |
| S35 | 第 6 步合并输出越过测试上限，已读的短行照常写出；进程组立即中止，报 `BUILD_OUTPUT_LIMIT` 退 2 |
| S24 | 把 `run.py` 复制到一个放了 `re`、`json`、`os`、`sitecustomize`、`traceback`、`posix`、`sys`、`signal`、`stat`、`time` 十个冒名模块的目录，不带 `-I` 运行，两路正常、标准输出关闭、标准错误关闭、两路都关闭、标准输出写满、标准错误写满各一次：都退 2，冒名模块一个都没有被执行 |
| S25 | 标准输出是满的非阻塞管道，0.6 秒后读端才开始读（开头几行因 `EAGAIN` 写不出，后来又写得出）：退 2，至多一行结果行，没有绿结果行 |
| S26a–b † | 第 6 步期间给运行脚本发 SIGINT、SIGTERM：标准输出最后一行是 `FM RESULT FAULT build SIGNAL`，退 2，沙箱里的进程随之结束、没有残留进程 |
| S27a–c | 第 4、7、5 步的审计程序被信号杀死（驱动脚本把审计程序换成 `kill -KILL $$`）：`SIGNAL` 退 2 |
| S28 † | 构建期把 `build/lib/lean` 换成指向别处的符号链接：`ARTIFACT_FORM`，不跟随它去核对 |
| S29 | 基线清单列了依赖目录里没有的包：取料 `PACKAGES` 退 2 |
| S30 | umask 077 下取料写出的目录仍是 0755、文件 0644 |
| E1 | 导入名带换行、行分隔符、方向控制符，内容是伪造的 `FM STEP …`、`FM RESULT GREEN` 行：第 4 步红，输出协议不破 |
| E2 † | 公理名、定理名、`unsafe def` 名带换行或制表符：第 7 步 `ENV_AXIOM`、`ENV_AXIOM_DEP`、`ENV_UNSAFE`，输出协议不破 |
| E3–E7、E14–E15 | 锁文件：键带换行 → `LOCK_REMOVED` 红；键是孤立代理项、重复的孤立代理项键、值是孤立代理项、`NaN`、普通的重复键、非 UTF-8 字节 → `INPUT` 退 2，没有回溯 |
| E8 | 分支名带换行与 ESC：预检 `BRANCH_ROLE` 红行转出，只转义一次 |
| E9 | 提交名参数带换行、分支名参数非 UTF-8：`BAD_REV` 退 2 |
| E10 † | 构建期 `#eval` 打印伪造的 `FM RESULT GREEN`、`FM STEP`、ESC 与行分隔符：整次运行仍是唯一一行真绿，伪造内容只以转义后的 `FM LOG` 行出现在标准错误 |
| E11a–b | 内容路径带换行：经预检 `PATH_GRAMMAR`；绕过预检取料 `CONTENT_PATH` |
| E12 | 内容文件不是 UTF-8：取料 `CONTENT_ENCODING` |
| E16 | 形状门发现的说明栏含被审文字（选项名带换行、行分隔符与方向控制符；解析错误消息）：`SHAPE_OPTION`、`SHAPE_PARSE`，输出协议不破 |
| H1 | 形状门红例目录（`selftest.py` 的 `SHAPE_RED`，一个提交里 66 个文件，每个文件只放一种写法，其中 1 个是必绿对照）：逐文件比对（红码，文件）集合，多一个少一个都算失败。覆盖：命令白名单 8 例（`macro`、`syntax`、`notation`、`elab`、`initialize`、`#print`、`export`、`lemma`）；声明 `axiom`；修饰符 `meta`、`unsafe`、`partial`、`meta section`；属性 `implemented_by`、`extern`、`init`、`csimp`、`attribute [-x]`、`local macro`；派生行内与 `deriving instance`；`#guard_msgs` 带规格、内嵌非 `#check`、在 `Chan/Final` 之外，裸 `#print axioms`；`set_option` 的命令、`… in`、项、战术、`grind =>` 五种位置与书名号写法、`trace.*`；禁用清单每一项（`sorry` 项与战术、`admit`、`native_decide`、`+native`、`(native := true)`、`(config := …)`、旧式配置子句（`aesop (config := …)` 在战术块里、`aesop (simp_config := …)` 在 `by` 项里、`plausible (config := …)` 在 `first` 分支里、Batteries `congr (config := …)`、`conv` 里的 `simp (config := …)`；参数名以 `config` 结尾的函数应用命名参数 `fmRun (config := 1) 2`，钉住按形状判的代价）、`include_str`、`eval%`、`by_elab`、`run_tac`、`run_cmd`、`run_meta`、`run_elab`、`sudo set_option`、项级 `unsafe`、`trace`、`success_if_fail_with_msg`、`#eval`、`#eval!`、`#exit`、`sorryAx`、`_root_.sorryAx` 在 `#check`、`variable` 默认值与 `#guard_msgs` 里）；解析失败；导入钉选库里没有的模块；必绿对照 `CfgNewStyleGreen.lean`（`simp (maxSteps := 1000)`、`+contextual`、`-zeta`、`decide +kernel`、`conv` 与 `first` 里的新式配置、命名参数 `(cfg := 1)`、类型标注 `(my_config : Nat)`、元组 `(config, config)`）不得出现在红行里 |
| H1b | `decl` 角色的提交：`Chan/Defs` 下不用 `@[expose] public section` 的文件 `SHAPE_EXPOSE`，用了的文件不报 |
| H2a–c | 作用域跟踪（`selftest-cases/shape/scope/`，以 Mathlib 的作用域记号 `n !` 为探针）：阴性对照里有 `namespace`/`section`/`end` 嵌套、`open … in`、`mutual … end`、`public section`、文件末尾未闭合的节，七步全绿，且只解析与真实精化的命令数逐文件相等；三个红例（`end Nat` 之后、`section` 内 `open` 再 `end` 之后、`open … in` 的下一条命令）第 5 步 `SHAPE_PARSE`；同一红例提交跳过第 5 步时真实构建同样拒绝 |
| H3a–b | 不执行被审代码：带 `initialize`、`#eval`、宏定义、`run_cmd` 与宏使用的文件第 5 步红，这些代码打印的标记不出现在任何日志里、构建目录没建；正对照：跳过第 5 步时同一个 `#eval` 在构建期执行，标记出现在构建日志里 |
| H4 | 已知不防 `linarith (oracle := …)`（独审 r2 甲-2，夹具 `must_green/known-not-covered/linarith-oracle-eval`）：第 5 步按设计放行、七步全绿，取值在构建期被求值；标记只出现在 `FM LOG build` 行里（标准输出里没有），临时目录与仓库里没有带标记的文件 |
| D1a–b | 派生证书正例：递归类型 `deriving Repr, BEq, Hashable, Ord`（生成 `partial` 辅助函数）七步全绿；同一提交证书为空时第 7 步 `ENV_PARTIAL` |
| D2 | 派生证书反例：同一模块里有合法派生，再手写 `partial def Spoof.loop`，驱动脚本去掉第 5 步的发现（放行）：第 7 步只有 `Spoof.loop._unsafe_rec` 一条 `ENV_PARTIAL` |
| E13 | 调用方的 `--workdir`、`--packages` 含非 UTF-8 字节与换行：`INTERNAL`（父目录不存在时建目录失败）、`PACKAGES`，退 2，异常消息经转义 |
| A2 | 第 4 类豁免的冒用形态（`must_red/autoparam/spoofs`，跳过第 5 步）：逐声明比对第 7 步红行，恰为「为什么冒用不了」表里的 18 条，合法载体不在其中 |
| A3 | `variable` 绑定器上的自动参数（`must_green/known-issue/autoparam-variable-binder`，完整流水线）：第 7 步只有 `ENV_META`，红行对象都是 `_private.Chan.Thm.Var.0._auto_<N>` |

**单元自测**（与流水线自测分开报数，随全量与 `--skip-corpus` 一起跑，`--cases U1` 单跑）：U1 在临时目录起一个最小 Lean 包，只依赖工具链自带的 Lean（不碰 Mathlib，不写共享依赖目录），用 `selftest-cases/autoparam/Forge.lean` 以 `addDecl` 直接造 25 个候选常量（正例 7：生成器本身产出、逐字照抄的字段名形态、多段数字后缀 `_auto_1_1`、仅被定义体引用、含 `Name.num` 与非空 `Syntax.Preresolved`、9 段全字符串名、含标识符的语法树；反例 18：每个只在一条判据上与正例不同——名字 5、安全性 2、提示 2、宇宙参数 1、类型 1、引用 1、值 4、对照 2），再由 `Check.lean` 按私有层级读回、调用审计程序库里的 `FM.autoParamCarriers`，逐个比对判定。它是测试设施，不是被审内容，不经过流水线；它证明判定函数按所写判据工作，不证明流水线能防伪造产物。

**弱化自测**（`--mutants`）：把 `runner/`、`precheck/`、`auditor/` 与骨架用例依赖的夹具目录（`SKELETON_FIXTURES`）复制到临时目录，先断言未改弱的副本骨架全过，再逐一在副本里改弱一处、用副本自己的自测跑相关骨架用例，每种弱化都必须有用例失败；改弱点在源码里找不到或不唯一时也判失败。第四片另加 18 种（见下），自动参数片另加 7 种（见下），本轮另加两种（S34a/S34b 抓到仍取基线配置，S35 抓到取消构建日志上限），共 55 种，清单见 `selftest.py` 的 `MUTANTS`。骨架片的 28 种：上一轮的 18 种（其中三种产物核对的改弱点随形状表改写）；独审 r2 另做而自测没抓到的 10 种，除不再适用的一种外都已收进来，共 7 个新改弱点——JSON 接受重复键（R2）、去掉目录项类型检查（R3 产物目录本身是符号链接与 R15 任意层级符号链接是同一处）、绿的结论不再要求标准输出都写出去了（R4）、信号判定只对第 6 步生效（R5b）、JSON 不要求合法 UTF-8（R7）、不核对依赖目录里的包（R8）、建目录后不 `chmod`（R14），R16「去掉顶层只许内容根」与上一轮的「去掉 ARTIFACT_ROOT」是同一处；本轮另加 3 种：目录模式异常或列不出时跳过、不装 SIGINT 与 SIGTERM 处理函数、隔离检查失败时的诊断经 `sys` 的流写且不兜异常（N-1 的旧形）。r2 的「`.olean` 不要求是文件」不再适用：形状表按目录项类型分别查目录表与文件表，名为 `X.olean` 的目录从来查不到文件表，没有单独的「须是文件」一步可改弱（S20 的 `Chan/Dir.olean` 覆盖这个形状）。沙箱不清环境一种同时去掉 `--clearenv` 与「调用 `bwrap` 时只给 `PATH`」两层，只去掉一层时另一层仍挡住、观察不到。

第四片的 18 种（括号里是抓它的用例）。独审 r2 后加的一种：`NO_CERTIFICATE` 只查为空不比路径（S33）；「`legacyConfig` 不要求第三个子节点是 `:=`」与原规则等价、抓不到，没有加，原因见「按形状判的代价」后一段。独审 r1 后加的两种：去掉旧式配置子句规则（H1）、第 7 步不要求第 5 步产出的派生凭证（S32）。骨架复审 r3 指出的两个自测缺口：去掉产物文件模式检查（S20 的 0755 文件）、`finish()` 去掉「至多写一次」的守卫（S31）。形状门的 13 种：去掉命令白名单、声明白名单、修饰符白名单、属性白名单、派生目标类白名单、`#guard_msgs` 规格限制（H1）；禁用清单去掉 `native_decide`（H1）；`set_option` 只查命令位置（H1 的项、战术、`grind` 三例）；解析失败不判红（H1、H2）；去掉 `Chan/Defs` 规则（H1b）；派生证书不比对位置、同模块即豁免（D2）；形状检查的沙箱里被审工作区可写（S22）；不核对每组的文件行（S5g）。另有两种原有弱化的改弱点随本片更新：「去掉模块数比对」现在同时由 S5a、S5f 抓；「第 7 步被审工作区可写」的改弱点加了上下文以区分第 5 步的同形挂载。

自动参数片的 7 种（括号里是抓它的用例）：第 4 类豁免去掉名字形态（U1）、去掉安全性条件（A2 的 `PostImpl.lean` 与 `PostExtern.lean`、U1）、去掉 `!isExtern` 条件（A2 的 `PostExtern.lean`）、去掉 `opaque` 提示（A2 的 `Copy.lean`、U1）、去掉「类型恰为 `Lean.Syntax`」（U1）、去掉「被 `autoParam` 引用」（A3、U1）、去掉「值按生成器重算逐字相等」（U1）。类型与值两种只有 U1 抓得到：源码写得出的冒用都先被 `opaque` 提示那一条挡住。语料用例 `corpus_case` 在没有预编译审计程序时（`--skip-corpus`，弱化自测即如此）改走普通模式，A2、A3 借它跑夹具。

语料用例：`fixtures.tsv` 列出全部旧夹具的归属与本片的实测期望（见下）。期望且实跑全绿、又没有跳过第 5 步的夹具才做命令数比对。比对复用 runner 的 `bwrap`：断网、清环境、遮住宿主家目录，只读挂载被审工作区、依赖、审计程序和 `ElabCount.lean`。先用 `shape-plan`、`shape` 数解析命令，再用 `lean --run` 精化同一文件（一进程一文件，被审产物只在精化时加入搜索路径）。逐文件比较，命令数不等即失败。归环境层、声明锁的夹具经驱动脚本跳过第 5 步跑（`SKIP_SHAPE_OWNERS`）。只含内容的夹具，基线与被审是同一提交（预检的改动类规则不触发，形状规则照常检查），构建配置按夹具实有的内容根生成；改了构建配置或门禁目录的夹具，基线是模板、被审提交叠上夹具，按证明角色送审。`--discover` 只打印实测结果，供更新表格。`--only` 或 `--cases` 没有匹配到用例时，打印错误并退 2。

## 旧夹具归属

`fixtures.tsv` 每行：夹具、归属、期望退出码、判红的步骤、红码集合、说明。归属取值：`预检`（第一片）、`取料`、`头部`、`沙箱构建`、`环境层`、`声明锁`、`第四片`（源码形状）、`#2315`、`不再检查`（只靠已删除机制，如工作树与未跟踪文件扫描、运行期版本钉选）。期望列是本片在新入口上的实测，**不是**归属门的承诺：归第四片的夹具现在可能是绿的，表里照实写，第四片合入时改这一列。

汇总（252 个旧夹具；g6b 的 11 个是工作树与分支名来源类，没有在新入口上跑，夹具目录已在第四片删除；另有 16 个旧门 1、门 2 的 Lake 配置名夹具已删除，见下）。第四片另加 4 行：R5-B4 的 3 个误拒汇总、1 个「已知不防」的接手对照；独审 r1 后另加 2 行：甲-1 的必红夹具 `must_red/g3/r1-legacy-config`、N1 的已知问题夹具；独审 r2 后另加 2 行：已知不防 `must_green/known-not-covered/linarith-oracle-eval`、必绿对照 `must_green/g3/r2-config-shaped-green`。自动参数片：N1 的夹具移到 `must_green/autoparam/default-proof` 并改为必绿，另加 6 行（必绿 3、冒用 1、`variable` 的已知问题 1、声明锁现状 1）。表里共 266 行：

| 归属 | 夹具数 | must_red / must_green / must_unknown | 新入口实测：退 1 / 退 0 / 未跑 |
|---|---|---|---|
| 预检 | 9 | 6 / 3 / 0 | 2 / 0 / 7 |
| 预检（规则 `TRUSTED_DRIFT`、`LAKE_FILE`）取代，夹具已删除 | 16 | 15 / 1 / 0 | — / — / 16 |
| 头部 | 78 | 70 / 7 / 1 | 77 / 1 / 0 |
| 沙箱构建 | 13 | 1 / 9 / 3 | 5 / 8 / 0 |
| 环境层（语料用例跳过第 5 步） | 17（含自动参数冒用 1） | 17 / 0 / 0 | 17 / 0 / 0 |
| 声明锁（语料用例跳过第 5 步） | 13（含自动参数现状 1） | 7 / 6 / 0 | 7 / 6 / 0 |
| 第四片 | 101 + 3（R5-B4）+ 1（独审 r1 甲-1）+ 1（独审 r2 必绿对照） | 75 / 27+3+1 / 0 | 83 / 23 / 0 |
| 第四片（已知不防） | 2 + 1（独审 r2 `linarith (oracle := …)`） | 0 / 3 / 0 | 0 / 3 / 0 |
| 第四片（已知不防的接手对照） | 1（新） | 1 / 0 / 0 | 1 / 0 / 0 |
| 不再检查 | 5 | 2 / 2 / 1 | 0 / 1 / 4 |
| 自动参数（环境层豁免第 4 类） | 4（N1 移来 1，新 3） | 0 / 4 / 0 | 0 / 4 / 0 |
| 已知问题（环境层误拒） | 1（`variable` 绑定器） | 0 / 1 / 0 | 1 / 0 / 0 |

### 骨架表里归第四片的 103 行，逐行落到三种之一

| 落点 | 行数 | 说明 |
|---|---|---|
| 本片判红 | 74（全部是 must_red） | 第 5 步判红，红码见表的第 5 列，规则名写在说明列（`本片判红：…`）。按红码计（一行可含多条）：`SHAPE_FORBIDDEN` 35、`SHAPE_OPTION_CONTROLLED` 13、`SHAPE_COMMAND` 11、`SHAPE_MODIFIER` 8、`SHAPE_ATTRIBUTE` 8、`SHAPE_GUARD_MSGS` 5、`SHAPE_OPTION` 3、`SHAPE_DERIVING` 2、`SHAPE_DECL` 1、`SHAPE_EXPOSE` 1 |
| 本片按设计不判红（已知不防） | 2 | `library-macro-option`、`r4-p4a-decreasing-by-rfl-prime`：库宏 `rfl'` 展开时设置 `smartUnfolding`。从 `must_red/g3/` 移到 `must_green/known-not-covered/`，期望七步全绿。谁接：它只影响精化期展开，不影响健全性，证明仍由内核检查；接手对照 `must_red/known-not-covered/rfl-prime-false`（用 `rfl'` 证 `2 = 3`）第 6 步构建判红，实测接住 |
| 归属有误 | 0 | — |
| （阴性对照） | 27（全部是 must_green） | 第 5 步零命中。22 个七步全绿；`attributes-whitelist` 第 6 步因夹具自身告警（`@[no_expose]` has no effect）判红；`r3-a7-named-expose-section`、`r3-a8-mathlib`、`r4-w1d-defs-deriving`、`r4-w2-w3-proofs` 不带锁文件，第 7 步 `LOCK_UNLISTED` |

「已知不防」里还有两类没有穷尽做成独立夹具，照实写：

- **清单外的求值入口**。分两部分写，出处是第四片独审 r1（`origin/evidence/2312-shape-review` @ `b97bb7f836` 的 `audit-reports/2312/shape-review-r1.md`「清单外求值入口的调查」一节）。
  - **独审实测的结论**（不是证明不存在）：独审 r1 在修掉甲-1 之后没有再找到能过第 5 步、又在构建期对被审文件给的项求值的入口；独审 r2 找到一例，见下面「仍未穷尽」里的 `linarith (oracle := …)`。下面列出的通往宿主机读写的通道都被堵住（这是枚举，不是全集）：项级与声明级 `unsafe`（`unsafeBaseIO` 等也要先有 `unsafe`）、`include_str`、`eval%`、`by_elab`、`run_tac`／`run_cmd`／`run_meta`／`run_elab`、`sudo` 已点名，第 5 步判红；用到 `IO`／`CoreM`／`TacticM` 这类元层类型要 `meta`，`meta def` 第 5 步红，改用 `import Lean.*` 第 4 步 `IMPORT_PINNED` 红。Aesop 规则战术按名字求值从被审源码结构性地触达不到：规则体是元层类型，构建报 `may not access declaration … imported as meta`（审阅夹具 `fx/e-eval4`、`fx/e-eval3`）。甲-1 那条入口（旧式配置子句）的能力上界是纯计算加往标准错误打字（`dbgTrace`、`panic!`）：取值是非元层类型的项，后果只到构建日志。
  - **仍未穷尽、归 #2315**：库在精化期替被审代码求值的入口没有逐个穷举（备忘 3.5 文本检索约 208 处求值调用点）。新式配置项里，键不以 `config` 结尾的不在旧式配置子句这条规则内；其中确有会在构建期对被审文件给的项求值的。核心 `simp` 一类用受限求值器，非字面量取值直接报 `Could not evaluate the expression`（独审 r1 `fx/e-eval5`），但有的库为自己的配置显式打开通用求值器：钉选 Mathlib 用 `derive_eval_expr_instance_using_meta_eval` 给 `LinarithConfig`、`CertificateOracle`、`GlobalBranchingPreprocessor` 开了 `Meta.evalExpr'`（`Mathlib/Tactic/Linarith/Frontend.lean:511-515`），`linarith (oracle := …)` 的取值因此在第 6 步构建期被求值。已知一例就是它（独审 r2 实测 `fx/ev-linarith-trace`，七步全绿，标记只进构建日志），能力上界同甲-1：纯计算加往标准错误输出。语料夹具 `must_green/known-not-covered/linarith-oracle-eval` 期望七步全绿，自测 H4 断言标记只出现在 `FM LOG build` 行里、沙箱外没有哨兵。**这一类按设计不往禁用清单里补键名**：形状门是诚实作者断言，清单外的求值入口由沙箱与内核重放承担，逐个补键名正是旧实现封闭名单走不通的那条路。给 #2315 的检索线索（独审 r2 建议 S5）：`derive_eval_expr_instance_using_meta_eval`、`ensure_eval_expr_instance` 是可检索的开关，钉选集合里命中 `Mathlib/Tactic/Linarith/Frontend.lean:511-515`、`Lean/Elab/Tactic/Simp.lean:71,83`、`Lean/Elab/Tactic/Grind/Config.lean:29`。伪造产物与经冷僻入口关掉内核检查的后果由 #2315 的内核重放接，本票不实测。宿主机读写这一后果由第 6 步沙箱接：它不看代码经哪个入口执行，自测 S7 用 `#eval`（跳过第 5 步）在构建期往临时目录、受信目录、另一个仓库、依赖目录、被审源码与配置写哨兵，全部不存在。
  - **甲-1 修复前的行为**（`1acb400d63`）记一笔：夹具 `must_red/g3/r1-legacy-config/…/AesopEval.lean`（取值带 `dbgTrace "FM-LEGACY-CONFIG-RAN"`）七步全绿，标记出现在第 6 步构建日志（`FM LOG build info: …: FM-LEGACY-CONFIG-RAN`），沙箱外没有哨兵——当时是沙箱那一层接住了宿主机一侧（独审 r1 实测）。修复后它在第 5 步 `SHAPE_FORBIDDEN`。
- **库里换了名字的选项设置器**：`sudo set_option` 已点名；没有找到第二个。后果（如关掉内核检查）同样归 #2315 的内核重放，本票不实测。

**旧式配置子句的检索方法**：在工具链源码与依赖目录全部 `.lean` 里按正则 `" ?\(" … &?"<名字>" … " ?:= ?"` 检索形如「`(`、记号、`:=`」的语法定义，再单独检索复用 `Parser.Tactic.config` 的语法（`(config)?`）。名字以 `config` 结尾的只有核心 `Init/Tactics.lean:34` 的 `config` 与 Aesop `Aesop/Frontend/Tactic.lean:31-32` 的 `config`、`simp_config`；复用核心 `config` 的有 `plausible`（`Plausible/Tactic.lean:158`）、Batteries `congr`／`rcongr`（`Batteries/Tactic/Congr.lean:35,59,121`）。同形但名字不以 `config` 结尾的子句（`(occs := …)`、`(iff := false)`、`(rule_sets := …)`、`(pattern := …)`、`(norm := …)`、`(attr := …)` 等）不在这条规则内。

**按形状判的代价：命名参数也会被判红。** 函数应用里的命名参数只要参数名以 `config` 结尾（`f (config := x)`、`S.mk (config := 1)`、`(cfg_config := 1)`、`(reconfig := 1)`，出现在 `exact`、`rw […]` 里也一样），同样判 `SHAPE_FORBIDDEN`，说明栏仍写「旧式配置子句」（独审 r2 甲-C1 实测）。这是有意保留的多挡，方向是多挡不是放过；规避办法是改用位置参数，或把参数名换成不以 `config` 结尾的（如 `cfg`，`(cfg := 1)` 绿）。不按语法种类把命名参数排除出去，原因有二：按种类列名单正是上一轮漏掉一整类的原因；库里把「括号、名字、赋值号」这个形状一律当配置项处理，将来换种类重用同一形状时，按种类的排除会连带放过真子句。自测 H1 的 `FbCfgNamedArg.lean` 钉住这一行为，必绿对照里有 `(cfg := 1)`、类型标注 `(my_config : Nat)` 与元组 `(config, config)`。

**「第三个子节点须是 `:=`」这一要件没有自测能钉住**（独审 r2 甲-C2 要求补对照与弱化，没做成）。弱化掉这个要件后自测仍全绿：类型标注、元组、括号项的左括号是 `hygienicLParen` 节点而不是记号 `(`，显式绑定器 `(config : Nat)` 的第二个子节点是标识符列表节点而不是标识符，都到不了这条判定。我在钉选库全部语法定义里检索「记号 `(` 紧跟标识符或名字以 `config` 结尾的记号」，第三个子节点不是 `:=` 的只有 `clear_value` 的 `clearValueHyp`（第二个子节点是 `binderIdent` 节点）与 Mathlib `Notation3` 内部的两条命令语法（命令白名单外）；另用解析探针扫了独审 r2 的 23 个误拒探针（其中 21 个在探针只加载 `Mathlib.Tactic.Common`、`Mathlib.Tactic.Linarith` 时能解析）与 5 个自写写法（结构字段绑定器、`clear_value`、`fun` 绑定器、`generalize`、`set … with`），命中这一形状的节点全部带 `:=`。也就是说，在钉选库里这个要件观察不到，去掉它的弱化与原规则等价；要件本身保留，作为将来出现同形非赋值语法时的防误拒。

## 已知问题

- **已修（自动参数片）：`structure` 字段的自动证明默认值被第 7 步误拒**（独审 r1 N1）。见「环境层豁免第 4 类」；夹具移到 `must_green/autoparam/default-proof`，七步全绿。
- **`variable` 绑定器上的自动参数仍被第 7 步误拒（刻意保留的窄误拒）**。写法 `variable (n : Nat) (hv : n ≤ n + 1 := by omega)`：Lean 为它生成的载体 `_private.<模块>.0._auto_<N>`（一处 `variable` 会生成多个）没有任何声明以 `autoParam` 引用，按第 4 条「必须被引用」判 `ENV_META`；不为它放宽这一条。夹具 `must_green/known-issue/autoparam-variable-binder`（期望按现状：第 7 步 `ENV_META`；自测 A3）。绕开办法：把自动参数写在用到它的 `def` 或 `theorem` 自己的绑定器上。
- **锁定目录里的自动参数载体进入声明锁**（只记录，不修）。载体是锁定模块里的常量，照常进入锁行；名字稳定（字段名、按声明计数、私有前缀带模块名），在前面加无关定义不改变它的锁行；值是战术的语法树（`quoteAutoTactic` 丢掉了位置信息），所以**只改默认证明的战术文字**（如 `by omega` 改 `by (omega)` 或 `by simp`）会让载体那一行 `LOCK_CHANGED`，结构体、构造子与声明本身的锁行不变（它们只按名字引用载体）。最小复现夹具 `must_red/g6a/autoparam-tactic-edit`（期望按现状：第 7 步 `LOCK_CHANGED`）。载体该不该算锁定内容，留给以后定。

### 旧门 3 源码类必红夹具（`must_red/g3/`，103 个）

不跳过第 5 步时：第 4 步头部判红 25 个（导入 `Lean`、`Aesop`、`meta import`、`prelude` 等）、第 5 步判红 75 个；没有判红的 3 个，原因逐个是：

1. `environment-derived-without-certificate`：只测环境层的夹具（「不带派生证书时派生的 `partial` 辅助函数不豁免」）。完整流水线有证书，正确地转绿；表里按环境层跳过第 5 步跑，证书为空，第 7 步 `ENV_PARTIAL`，与自测 D1b 一致。
2. `library-macro-option`、3. `r4-p4a-decreasing-by-rfl-prime`：`rfl'`，已知不防，见上。

备忘原型漏的 `#exit`（`exit-command`）本片判 `SHAPE_COMMAND`、`SHAPE_FORBIDDEN`；导入 `ChanExplore` 的那个归第 4 步方向表。

### R5-B4

三份误拒汇总（`must_green/g3/r5-b4-everyday-tactics`、`-everyday-terms`、`-readme-promised`，共 41 条命令：18 + 11 + 12，各含一条 `public section`，`readme-promised` 另含 `open Nat`）在第 5 步**零命中**。三份在第 6 步构建判红，原因都在夹具自身，审阅者当时只跑了门 3、没有构建：`tSuffices` 里 `simpa` 已关闭目标后又多一个 `rfl`；`Finset` 未解析与 `polyType.{u}` 的宇宙参数未用；`protected def` 不在命名空间里、`@[grind]`／`@[norm_cast]`／`@[simps]` 用在不合适的定理上。表里照实记为 `build BUILD_WFAIL`。

### 其余变化

- 骨架表里因没有派生证书判 `ENV_PARTIAL` 的 12 个必绿夹具（`g15/r4-w1d-defs-deriving`、`g2/` 4 个、`g3/` 7 个）全部不再报 `ENV_PARTIAL`：8 个七步全绿，4 个只剩 `LOCK_UNLISTED`（夹具不带锁文件）；`r4-w1d-defs-deriving` 的门 15 `EXPOSE_SECTION` 也随证书消失。
- 手写同名 `partial def` 伪装派生辅助函数的 `r4-p7a2-deriving-spoof`（环境层，跳过第 5 步）仍是第 7 步 `ENV_PARTIAL`；`-source` 版本第 5 步 `SHAPE_MODIFIER`。
- 20 个 `r4-p*` 夹具删去了 `formal_math` 顶层的模拟宿主机文件 `host_secret_probe.txt`：它让预检先判 `TOP_LEVEL`，夹具的源码层意图测不到；新流水线里宿主机文件本来就在沙箱外。删去后这 20 个都在第 5 步判红。
- 16 个环境层夹具（语料用例跳过第 5 步）：12 个在第 7 步判出旧期望的码；另 4 个（`private-proof`、`r4-p7a-deriving-spoof`、`r3-a1f/a1g-environment`）整次运行先在构建或头部一步红（与骨架过审版的计数相同）。第 5 步不跳过时，其中 12 个先在第 5 步判红（`axiom`、`partial`、`unsafe`、`implemented_by`、`extern`、`meta` 都是第 5 步的白名单外写法）。九个环境层红码由这些夹具与骨架用例 S3、S17、E2、D1b、D2（跳过第 5 步或在第 5 步放行）判出。
- `must_unknown` 的写坏源码现在由第 5 步 `SHAPE_PARSE` 判红（原先在构建一步）。
- 夹具目录里只服务旧 `selftest.py` 的元数据文件（`expect.txt` 177 个、`expect_detail.txt`、`environment-only.txt`、`source-only.txt` 各 13 个、`forbid-file.txt` 9 个、`modules.txt` 7 个、`branch.txt` 6 个等，共 247 个）已删除；旧期望保留在 `fixtures.tsv` 的说明列（`旧期望 …`）。
- 删除的 16 个夹具目录（46 个文件）：`must_green/g1/pins`，`must_red/g1/` 的 `r4-manifest-path-source`、`r4-manifest-url`、`revision`、`toolchain`，`must_red/g2/` 的 `lib-option`、`missing-option`、`r2-a5-build-config`、`r2-a6-build-config`、`r2-a6b-build-config`、`r2-a6c-build-config`、`r2-a6d-build-config`、`r4-p6a-lakefile-invalid-toml`、`r4-p6b-lakefile-more-lean-args`、`r4-p6c-lakefile-package-options`、`unimported-child`（第二片删）。第四片另删 `must_red/g6b/`、`must_green/g6b/`、`must_unknown/g6b/` 共 11 个目录，表里保留行、期望列为 `-`。
- 只解析与真实精化的命令数：语料里所有期望全绿、且不跳过第 5 步的夹具，跑完后逐文件比较（见「自测」的语料用例）。

## 待后续片

- 审阅报告（S、7a、7b、8a、8b、9、10）**没有搬**：旧入口 `run_gates.py --report` 已删除，报告暂时不可用。它不阻断，由第五片决定搬去哪里；回归样本 `../report_cases/` 按用户裁定（评论 7164343103）保留。
- 真实被审包的 `lakefile.toml` 已包含 `Chan`、`ChanTest`、`ChanDyn` 三个库（`ChanDyn/` 附最小占位模块 `BuildAnchor.lean` 供空树期扫描）：`ChanChallenge/`、`ChanExplore/` 一旦有文件，第 6 步会因 `NO_ARTIFACT` 判红，需要 `infra` 先补库。
- #2315：由主干版本工作流触发并设为必需检查；CI 上依赖目录的准备与只读挂载；调用一律 `python3 -I <路径>/run.py`；**持续读取运行脚本的标准错误（或重定向到文件），并给整次运行设总超时、超时按失败处理**（两路输出都是阻塞写，标准错误没人读时运行可能挂起而不退出，见「输出与退出码」）；以退出码为准，不以看到的结果行为准。
