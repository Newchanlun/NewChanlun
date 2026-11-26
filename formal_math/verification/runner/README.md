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
| 2 | `fetch` | 受信目录 `<工作目录>/trusted/verification/` ← 受信提交的 `formal_math/verification/` 整棵树。被审工作区 `<工作目录>/audited/` ← 被审提交的内容文件（`Chan/`、`ChanTest/`、`ChanChallenge/`、`ChanDyn/`、`ChanExplore/` 下与顶层 `Chan.lean`、`ChanExplore.lean`）+ **基线**的 `lakefile.toml`、`lake-manifest.json`、`lean-toolchain`。见下「取料」 | `CONTENT_PATH`（内容根下有不合文法、不是 100644 普通 `.lean` 文件的条目，或顶层有别的 `.lean`） | `TRUSTED_TREE`、`BASE_CONFIG`、`NO_PACKAGE`、`NO_CONTENT`、`GIT` |
| 3 | `auditor` | 核对受信 `auditor/lean-toolchain` 与被审工作区的（基线的）工具链文件逐字节相同；`lean --print-prefix` 定位工具链并核对 `lean --version`；在受信目录里 `lake build`。输出审计二进制的路径与 sha256 | — | `TOOLCHAIN_MISMATCH`、`TOOLCHAIN`、`AUDITOR_BUILD` |
| 4 | `headers` | 沙箱里跑 `fm_audit headers <模块> <路径> …`：审计程序只解析文件头，不加载任何导入。头部白名单的发现由审计程序给出；目录方向表、传递闭包、整库导入 Mathlib 由运行脚本按审计程序给的导入列表判定 | `MODULE_FIRST`、`PRELUDE`、`IMPORT_ALL`、`META_IMPORT`、`IMPORT_PINNED`、`IMPORT_SOURCE`、`HEADER_PARSE`（审计程序）；`WHOLE_MATHLIB`、`IMPORT_EDGE`、`IMPORT_CLOSURE`（运行脚本） | `AUDITOR_OUTPUT`、`MODULE_COUNT`、`AUDITOR` |
| 5 | `shape` | **空位**，第四片实现。直接通过，输出 `SHAPE 未安装` | — | — |
| 6 | `build` | 先在同一沙箱里跑 `lean --version` 作探针，再 `lake build --wfail`（基线配置的默认目标）。之后核对每个内容文件都有 `.olean`（对照 git 树数出的模块数），且产物目录顶层只有内容根 | `BUILD_WFAIL`、`NO_ARTIFACT`、`ARTIFACT_ROOT` | `SANDBOX`、`BUILD`（被信号终止或超时） |
| 7 | `env` | 另起沙箱，只读挂载被审工作区（含构建产物）、依赖目录与受信目录，跑 `fm_audit env <模块> …`：门 3 环境层、门 15 暴露检查、门 6a 声明锁的规范序列化。运行脚本对锁行求 sha256，与**被审提交**的 `formal_math/statement-lock.json` 逐项比对 | `ENV_AXIOM`、`ENV_AXIOM_DEP`、`ENV_SORRY`、`ENV_META`、`ENV_EXTERN`、`ENV_UNSAFE`、`ENV_PARTIAL`、`ENV_IMPLEMENTED_BY`、`EXPOSE_SECTION`、`LOCK_CHANGED`、`LOCK_REMOVED`、`LOCK_UNLISTED` | `AUDITOR_OUTPUT`、`MODULE_COUNT`、`INPUT`、`CERTIFICATE`、`AUDITOR` |

运行前的准备（解析参数、解析提交、核对工作目录、受信代码是否齐全、`run.py` 是否就是受信那份）失败时步骤名记 `prepare`，退 2。任何意外异常都归入 `INTERNAL`，退 2，不会落成 0 或 1。

### 取料

- 只用 `ls-tree -r -z <提交>:<路径>` 加 `cat-file --batch` 逐个取 blob 原始字节。不用 `git archive`、检出或 `git worktree`，所以被审树里的 `.gitattributes`（`export-ignore`、`filter`、`eol`）与仓库配置的过滤器都不起作用。
- 受信目录里每条路径段须合 `[A-Za-z0-9_][A-Za-z0-9_.-]*` 且是 100644 普通文件，否则退 2。内容文件的每个路径段（去掉 `.lean`）须合模块名文法 `[A-Za-z][A-Za-z0-9_]*`。
- 写文件用 `O_CREAT|O_EXCL|O_NOFOLLOW`，模式固定 0644，目录 0755；已存在或遇到符号链接即失败。
- **与预检的交接**：预检不查「模式是文件的条目指向的对象是不是 blob」（第一片 README「不防什么」）。取料用 `cat-file --batch` 读每个对象时逐个核对头行的类型必须是 `blob`，不是就 `GIT` 故障退 2；这一步发生在建任何目录之前，被审工作区与受信目录都不会写出，更不会把它当空文件写出或跳过。自测 S16 用模式 `100644`、对象实为树或提交的条目核对。
- 第 1 步只接受两种预检输出：退 0 且恰好一行绿行；退 1 且每行都是 `PRECHECK RED <码> <对象> <说明>`。红码按 `[A-Z_]+` 原样转出，预检新增的码（`LAKE_FILE`、`TREE_FORM` 等）不需要改运行脚本；其它任何输出（未知格式、退 2 的 `BASE_FORM`、`NOT_ANCESTOR` 等，此时预检已写到标准输出的红行不转出）一律退 2。
- 被审提交里 `formal_math/` 下的其它文件（README、台账等）与它自己的三个构建配置文件都不进被审工作区。锁文件由运行脚本在第 7 步直接从被审提交的 git 对象读。

### 沙箱布局（第 4、6、7 步）

`bwrap --ro-bind / /`，`/home`、`/root`、`/run`、`/var`、`/tmp` 与**整个工作目录**先盖成空 tmpfs，再按步回绑；`--clearenv` 后只放回 `HOME=/tmp/home`、`TMPDIR=/tmp`、`LANG=C.UTF-8`、`PATH=<工具链>/bin:/usr/bin:/bin`（第 7 步另加 `LEAN_PATH`、`LEAN_SYSROOT`）；`--unshare-all`（断网）、`--die-with-parent`、`--new-session`。

| 步 | 被审工作区 | `.lake` | 依赖目录 | 受信目录 | 工具链 |
|---|---|---|---|---|---|
| 4 | 只读 | — | 不挂 | 只读 | 只读 |
| 6 | 只读 | **可写** | 只读挂到 `.lake/packages` | 不挂（被 tmpfs 盖住） | 只读 |
| 7 | 只读（含产物） | 只读 | 只读，挂在原路径 | 只读 | 只读 |

审计二进制永远是第 3 步在受信目录里构建的那一个，运行脚本按绝对路径执行它，不对被审包调用 `lake exe`。第 7 步的搜索路径由运行脚本按基线清单拼出：依赖包的 `.lake/build/lib/lean` 在前，被审产物在后，工具链自带的库由 Lean 追加在最后；第 6 步因此另查产物目录顶层只许内容根，免得被审构建在那里放一个 `Init` 或别的库根去遮住真库（`ARTIFACT_ROOT`）。

## 输出与退出码

| 退出码 | 含义 |
|---|---|
| 0 | 七步都跑完且全绿，最后一行 `FM RESULT GREEN` |
| 1 | 某一步判红。该步的红行之后是 `FM STEP <n> <名字> RED` 与 `FM RESULT RED`，后面的步骤不跑也不报 |
| 2 | 无法判定，包括参数、前置条件、工具缺失、构建审计程序失败、沙箱探针失败、审计程序输出无法解读或与 git 树对不上、超时、意外异常、`--until` 提前停下。诊断行 `FM FAULT <步骤> <码> <对象> <说明>` 写标准错误 |

- 标准输出一行一条，前缀固定：`FM MODE`、`FM RUNNER`、`FM RED <步骤> <规则码> <路径或对象> <说明>`、`FM STEP <n> <名字> <GREEN|RED|FAULT> <秒> <备注>`、`FM RESULT …`。首行恒为 `FM MODE`。
- 路径或对象一栏按字节输出，空白、反斜杠、控制字符与非 ASCII 字节转义成 `\xNN`；全部按 UTF-8 字节 `os.write`，不用 `print`（原因同第一片：不随 locale 变，写不出时能察觉）。绿的结论要求全部标准输出都写出去了，否则退 2。
- 子进程（预检、`lake`、审计程序）的诊断原样转到标准错误；`lake` 的构建日志也写标准错误，标准输出只留 `FM` 行。
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

### 读环境不跑被审代码（核对后保留）

`Lean.importModules … (level := .private)` 不传 `loadExts`，默认不加载环境扩展，因此 `[init]` 声明不运行；按私有层级加载才看得见证明体里的公理依赖（`env.checked`）。审计程序在沙箱里只读挂载产物，即使有缺陷也写不到宿主机。

## 不防什么（本片）

- **构建产物与源码是否对应、产物里的常量有没有经过内核**：第 6 步执行了被审代码，它能改写自己 `.lake` 里的任何产物；第 7 步对「这批产物」如实，诚实作者断言（备忘 3.6）。蓄意对手由 `lake check` 与 `lake comparator` 接（#2315）。
- **畸形 `.olean` 对审计进程本身的影响**：审计程序把产物映射进内存（备忘 3.6 第 5 条，未核实）。沙箱把后果限制在只读视图与标准输出里；输出被伪造成什么样，运行脚本都只认合规的结构化结果。
- **依赖目录的内容**：调用方给的依赖目录被信任；本片只保证被审构建写不到它（只读挂载）。内容可信与否归 `lake check`（#2315）。
- **调用方**：工作目录、依赖目录、git 可执行文件与对象库、`bwrap`、工具链由调用方提供并被信任。由主干版本工作流触发、设为必需检查归 #2315。
- **源码形状**：第 5 步未安装。在第四片合入之前，`sorry`、`native_decide`、受控选项、本地元编程、`#eval` 等只要能通过 `lake build --wfail` 与环境层就不会被拦。
- **自举模式**：见上。

## 与设计备忘的偏离

1. **`--packages` 是新增的必填输入**。任务列的输入里没有依赖目录；运行脚本不联网，必须由调用方指出 Mathlib 等的位置。备忘 3.2 要求「沙箱里依赖目录只读挂载」，这里照做。
2. **`--until` 提前停下退 2**。备忘 3.7「0：七步都跑完且全绿」；部分运行不是完整判定。
3. **运行脚本核对自己与受信提交同一 blob**（`RUNNER_MISMATCH`）。备忘 3.1 只要求「在输出里写明代码来自哪个提交」，写明的前提是能核对。
4. **`ARTIFACT_ROOT`**：第 6 步多一条形状检查（产物目录顶层只许内容根、不许符号链接）。它属于送审问题「经声明之外的通道影响审计程序的输入」：搜索路径上被审产物在库之后、工具链库之前，被审构建可以在产物目录里放 `Init/…` 遮住工具链的库。
5. **头部规则分在两处**：白名单类在审计程序（Lean），方向表与闭包在运行脚本（Python），各自原样搬自旧实现。
6. **`HEADER_PARSE` 判红而非无法判定**，见搬家差异。
7. **`formal_math/.gitignore`**：按任务并入仓库根 `.gitignore` 并删除。预检返修（`5b6cc3ea16`）后它是 `infra` 的受信文件，获放行可删；仓库根 `.gitignore` 在受管范围以外，不再判红。
8. **门禁目录里不能有 Lake 配置名的文件**（预检 `LAKE_FILE`）：R5-B1 自测夹具里的 `lakefile.toml` 存为 `selftest-cases/r5-b1/hijack-lakefile.toml`，自测造提交时改回原名放到被审树里。

## 自测

```sh
source scripts/fm_env.sh
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh \
  python3 -I formal_math/verification/runner/selftest.py --packages <依赖目录> [--jobs 4] [--only 子串] [--skip-corpus]
```

用临时目录（跟随 `TMPDIR`）现造 git 仓库，仓库路径含空格与非 ASCII；提交用 `hash-object -w`、`mktree`、`commit-tree` 造，不检出。每个用例经 `run.py` 跑整条流水线，断言**整次运行**的退出码与红码集合；运行结束删除各自的工作目录。

骨架用例：

| 编号 | 断言 |
|---|---|
| S1 | 阴性对照：证明角色加一个定理，七步全绿，输出含 `SHAPE 未安装`，首行 `FM MODE baseline` |
| S2 | R5-B1 原样（`infra/hijack`，放行）：第 1 步 `PATH_SCOPE` 判红，只有一行步骤行，受信目录没有建 |
| S3 | 同一提交绕过预检（自测驱动脚本以模块方式载入 `run.py`，从第 2 步起跑；命令行入口没有这个口子）：被审工作区的 `lakefile.toml` 与基线逐字节相同、第 3 步报的审计二进制在本次工作目录的受信目录里、`Bogus.lean` 的 `axiom` 在第 7 步判 `ENV_AXIOM`、`ENV_AXIOM_DEP`、假审计程序的哨兵文件在临时目录与仓库里都不存在 |
| S4 | 基线带仓库根 `.gitattributes`（`export-ignore`、`filter=fmevil`、`eol=crlf`，并给仓库配了会改内容的 smudge 过滤器）：被审文件在工作区里、逐字节等于 blob、模式 0644；对照：`git archive` 的输出里没有它 |
| S5 | 五种篡改（自测驱动脚本包一层沙箱函数改审计程序的输出）：`env` 模块数加一 → `MODULE_COUNT`；`headers` 插一行非 JSON、删一行头部记录 → `AUDITOR_OUTPUT`；`env` 无发现却报红、绿却退 1 → `AUDITOR_OUTPUT`。全部退 2 |
| S6 | 第 4 步红：后面没有步骤行、`.lake` 没建；第 6 步红：没有第 7 步行 |
| S7 | 哨兵：被审文件在构建期 `#eval` 依次尝试写临时目录、本次受信目录、另一个仓库目录、`.lake/packages`（只读挂载的依赖目录），以及 `initialize` 写临时目录；同时写工作区内 `.lake/inside-ok` 作正对照。期望：全绿、正对照存在、五个哨兵都不存在、仓库目录快照（路径与 mtime）不变 |
| S8 | 参数与前置条件：缩写、`--until=3`、重复、缺 `--packages`、`--until 8`、未知开关、工作目录在仓库里、工作目录非空，都退 2 且没有结果行 |
| S9–S10 | `--until 3` 全绿退 2；`--until 1` 遇红退 1 |
| S11–S12 | 基线缺受信代码：没给自举开关退 2（`NO_TRUSTED_CODE`）；给了则首行写自举、全绿 |
| S13 | 受信提交里的 `run.py` 与正在运行的不同：退 2（`RUNNER_MISMATCH`） |
| S14 | 被审提交在 `Chan/Thm/` 下放 `lakefile.lean`：第 1 步 `LAKE_FILE`，只有一行步骤行 |
| S15 | 用 `hash-object -t tree --literally` 造一棵含两条同名 `Ok.lean` 的 `Chan/Thm` 树：第 1 步 `TREE_FORM` |
| S16 | `Chan/Thm/Ok.lean` 的模式是 `100644`、对象实为树（另一例为提交）：预检绿（它不查），第 2 步 `GIT` 故障退 2，被审工作区没有建 |

语料用例：`fixtures.tsv` 列出全部旧夹具的归属与本片的实测期望（见下）。只含内容的夹具，基线与被审是同一提交（预检因受管路径无改动而绿），构建配置按夹具实有的内容根生成；改了构建配置或门禁目录的夹具，基线是模板、被审提交叠上夹具，按证明角色送审。`--discover` 只打印实测结果，供更新表格。

## 旧夹具归属

`fixtures.tsv` 每行：夹具、归属、期望退出码、判红的步骤、红码集合、说明。归属取值：`预检`（第一片）、`取料`、`头部`、`沙箱构建`、`环境层`、`声明锁`、`第四片`（源码形状）、`#2315`、`不再检查`（只靠已删除机制，如工作树与未跟踪文件扫描、运行期版本钉选）。期望列是本片在新入口上的实测，**不是**归属门的承诺：归第四片的夹具现在可能是绿的，表里照实写，第四片合入时改这一列。

汇总（252 个旧夹具；g6b 的 11 个是工作树与分支名来源类，没有在新入口上跑；另有 16 个旧门 1、门 2 的 Lake 配置名夹具已删除，见下）：

| 归属 | 夹具数 | must_red / must_green / must_unknown | 新入口实测：退 1 / 退 0 / 未跑 |
|---|---|---|---|
| 预检 | 7 | 4 / 3 / 0 | 0 / 0 / 7 |
| 预检（规则 `TRUSTED_DRIFT`、`LAKE_FILE`）取代，夹具已删除 | 16 | 15 / 1 / 0 | — / — / 16 |
| 取料 | 1 | 1 / 0 / 0 | 1 / 0 / 0 |
| 头部 | 79 | 71 / 7 / 1 | 78 / 1 / 0 |
| 沙箱构建 | 13 | 1 / 9 / 3 | 8 / 5 / 0 |
| 环境层 | 16 | 16 / 0 / 0 | 16 / 0 / 0 |
| 声明锁 | 12 | 6 / 6 / 0 | 6 / 6 / 0 |
| 第四片 | 103 | 76 / 27 / 0 | 60 / 43 / 0 |
| 不再检查 | 5 | 2 / 2 / 1 | 0 / 1 / 4 |

要点：

- 归第四片的 76 个必红夹具里，26 个现在整次运行为绿（源码选项写法、`#eval`、`eval%`、`#guard_msgs` 吞告警、`rfl'` 等），其余 50 个由构建（`--wfail`）、头部或环境层兜住。在第四片合入之前这 26 个是已知漏洞。
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
