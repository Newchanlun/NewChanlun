# formal_math 纯静态预检（#2312 第一片）

`precheck.py` 判定一次合入是否只改了分支角色允许的路径、受信文件是否仍是基线那一份、被审提交里整棵 `formal_math/` 的形状是否合规。它是整套门禁里唯一承担**对抗断言**的自写代码：能构造出（基线、被审提交、分支名、放行开关）使它退 0、而某个受信文件与基线不同、或有角色之外的路径被改、或 `formal_math/` 下出现形状规则之外的条目，即为缺陷。

设计依据：`origin/evidence/2312-design-consult` @ `aedff2e010` 的备忘 3.1–3.4、3.7，#2312 评论 7175991382。

## 调用

```sh
python3 -I precheck.py [--trusted-change-approved] <仓库> <基线提交> <被审提交> <分支名>
```

- 只认这一种写法。放行开关只能是第一个参数且逐字相等；缩写、`--x=y`、重复、放在后面都算用法错误。仓库、基线、被审三个参数不得为空或以 `-` 开头，分支名不得以 `-` 开头。
- 只读 git 对象，用到的命令只有 `rev-parse --verify --end-of-options <x>^{commit}`、`merge-base --is-ancestor`、`diff-tree -r -z --no-renames --raw`、`ls-tree -r -t -z --full-tree`。不读暂存区与工作树，不检出，不写任何文件。
- git 子进程的环境从零构造：`LC_ALL=C`、`GIT_NO_REPLACE_OBJECTS=1`、`GIT_GRAFT_FILE` 指向空设备、不读系统与全局配置，`PATH` 沿用调用方。
- 放行开关只对 `infra` 角色有意义，其它角色给了也不起作用。

## 输出与退出码

| 退出码 | 含义 |
|---|---|
| 0 | 判定为绿，且绿行 `PRECHECK GREEN OK <被审提交> role=<角色或->` 已完整写到标准输出 |
| 1 | 判红。每条红行写到标准输出；红行写不出不改变结论 |
| 2 | 无法判定：参数无效、提交解析不出、基线不是祖先、git 失败、树对象畸形、意外异常、绿行写不出。已查出的红行照样先写，再写一行 `PRECHECK FAULT` 到标准错误 |

- 行格式固定，一行一条：`PRECHECK RED <规则码> <路径或对象> <说明>`，`PRECHECK FAULT <故障码> <对象> <说明>`。
- 路径或对象一栏按字节输出，空白、反斜杠、控制字符与非 ASCII 字节一律转义为 `\xNN`，所以一条一定只占一行。
- 编码：脚本自己写的绿行、红行与故障行按 UTF-8 字节直接写文件描述符，不经 Python 文本层，不随 locale 变。git 的诊断原样透传到标准错误。标准错误写不出时诊断丢失，退出码不变。

## 规则

顺序固定。第 1 条不满足即退 2，不再往下查。第 4 条起只在「受管路径有改动」时进行：`formal_math` 根节点、`scripts/fm_env.sh`、`.github/workflows/formal-math.yml` 三者在两端提交里的（模式、类型、对象）全都相同时，不论分支名直接绿。

| 码 | 规则 | 判什么 | 凭什么 |
|---|---|---|---|
| `NOT_ANCESTOR`（退 2） | 1 | 基线不是被审提交的祖先 | `merge-base --is-ancestor` 的退出码 |
| `BRANCH_ROLE` | 2、4 | 分支名不合文法、解析不出角色，却改了受管路径 | 分支名参数对固定文法 `(decl\|proof\|audit\|infra)/W(/W)*` 全匹配，`W = [A-Za-z0-9]+([._-][A-Za-z0-9]+)*`。空后缀、`..`、首尾分隔符、空白、非 ASCII、多余前缀都不给角色 |
| `PATH_SCOPE` | 4、5 | 某条改动（含删除、类型变化、模式变化）不在该角色的路径表里 | `diff-tree -r -z --no-renames --raw <基线> <被审>` 的每条记录。以 `/` 结尾的表项按字节前缀匹配，其余逐字相等，所以 `Chan/Thm2/`、`verification-x/` 这类同名前缀兄弟不算在内 |
| `TRUST_UNAPPROVED` | 5 | `infra` 角色改了受信面，调用方没给放行开关 | 同上的 `diff-tree` 输出 |
| `MODE` | 6 | `formal_math/` 下有模式不是 `100644` 普通文件或 `040000` 目录的条目（符号链接、可执行位、子模块）；`formal_math` 本身不是目录；`scripts/fm_env.sh` 或 `.github/workflows/formal-math.yml` 不是 `100644` | `ls-tree -r -t -z --full-tree <被审>` |
| `EMPTY_TREE` | 6 | 提交里记录了空子树 | 同上，目录节点在列表里却没有任何子条目 |
| `PATH_GRAMMAR` | 6 | `formal_math/` 下某个路径段不合 `[A-Za-z0-9_][A-Za-z0-9_.-]*`（隐藏名、空白、换行、非 ASCII 都进不来），或两条路径只差大小写 | 同上 |
| `TOP_LEVEL` | 6 | `formal_math/` 顶层出现固定名字表以外的名字，或名字对了类型不对。`formal_math/lakefile.lean` 在任何角色下都由此判红 | 同上 |
| `CONTENT_SHAPE` | 6 | 内容根 `Chan/`、`ChanTest/`、`ChanChallenge/`、`ChanDyn/`、`ChanExplore/` 下出现不合模块名文法 `[A-Za-z][A-Za-z0-9_]*` 的目录，或不是 `<模块名>.lean` 的文件 | 同上 |
| `TRUSTED_DRIFT` | 7 | 非 `infra` 角色下，某个受信文件或整个门禁目录与基线不是同一对象（模式、类型、对象名三者逐一比较，缺失也算） | 两端提交各一次 `ls-tree -r -t -z --full-tree`，按路径逐字查表。与 `PATH_SCOPE` 互为冗余，不依赖角色表写对 |

无法判定的故障码：`USAGE`（参数）、`BAD_REV`（解析不出提交）、`NOT_ANCESTOR`、`BAD_TREE`（树对象里同一目录的条目重复或未按 git 顺序排列；`diff-tree` 在这种树上的结果不可信）、`GIT`（git 启动失败、非预期退出码或输出无法解读）、`OUTPUT`（绿行写不出）、`INTERNAL`（意外异常）。

### 受信面

受信文件逐个列全名：`formal_math/lakefile.toml`、`formal_math/lake-manifest.json`、`formal_math/lean-toolchain`、`scripts/fm_env.sh`、`.github/workflows/formal-math.yml`。外加门禁目录 `formal_math/verification/`，第 7 条按整棵树对象比较。

### 角色路径表（前缀均在 `formal_math/` 下，除另注）

| 角色 | 可改的路径 |
|---|---|
| `decl` | `Chan/Defs/`、`Chan/Hypotheses/`、`Chan/Audit/Literal/`、`Chan/Proxy/`、`ChanChallenge/`、`sources/`、`blueprint/`、`statement-lock.json`、`formalization.yaml`、`garbage-signoffs.yaml`、`HISTORY.md` |
| `proof` | `Chan/Thm/`、`Chan/Proofs/`、`Chan/Exec/`、`Chan/Final/`、`Chan/Final.lean`、`Chan.lean`、`ChanTest/`、`ChanDyn/`、`ChanExplore/`、`ChanExplore.lean` |
| `audit` | `Chan/Audit/Math/`、`Chan/Audit/Separation/`、`Chan/Audit/Cases/`、`ChanTest/` |
| `infra` | 受信面全部（五个受信文件，含仓库根下的两个，加 `verification/`），外加 `README.md`。`README.md` 不是受信文件，只改它不需要放行 |

内容角色的表与受信面不相交，`infra` 的表里没有任何内容路径；`selftest.py` 对此有结构断言。

### `formal_math/` 顶层固定名字

目录：`Chan`、`ChanTest`、`ChanChallenge`、`ChanDyn`、`ChanExplore`、`verification`、`sources`、`blueprint`。
文件：`Chan.lean`、`ChanExplore.lean`、`lakefile.toml`、`lake-manifest.json`、`lean-toolchain`、`README.md`、`HISTORY.md`、`formalization.yaml`、`statement-lock.json`、`garbage-signoffs.yaml`。

`verification/`、`sources/`、`blueprint/` 内部只查模式、空子树、路径段文法与大小写。

## 信任前提

- **运行的必须是基线版本的脚本，并由主干版本的工作流触发。** 若由 PR 自己的工作流或 PR 自己的 `precheck.py` 执行，被审方可以直接改掉判定，本片的一切断言不成立。这一条归 #2315（`pull_request_target` 或宿主侧发布必需检查）。
- **放行开关的载体未定。** 本片只认命令行开关。谁有权给、如何保证它独立于写代码的代理（备忘 3.1：标签若能由执行器令牌打上就不独立），由后续片与 #2315 决定。
- **角色是分支名自报的。** 任何人都能起任一角色前缀的分支，预检只保证「声称是 X 角色的改动确实只碰了 X 的路径」。角色之间的约束（谁能开 `decl/*`）靠各自的评审流程。
- **基线由调用方给出**，应当是合入目标 `main` 的当前提交。
- git 须支持 `rev-parse --end-of-options`（本机实测 git 2.53）；不支持时 git 报错，预检退 2。
- git 可执行文件、仓库的 `.git` 目录（对象库、仓库级配置、shallow 信息）可信。预检屏蔽了替换对象、grafts、系统与全局配置，但仓库级配置仍由 git 读取。

## 不防什么

- **能改受信文件的人**（`infra` 作者与放行者）。放行之后受信文件的改动正确与否，靠非作者对抗评审与制度。
- **文件内容。** 预检不读任何 blob 的内容：Lean 源码、`lake-manifest.json` 的字段、锁文件是否正确，都归后续片或评审。它只保证内容角色拿不到这些受信文件的写权。
- **受管路径以外的改动。** 无角色分支改其它工作流（如 `ci.yml`）、其它脚本、仓库根 `.gitattributes` 一律绿。工作流能否影响 formal-math 作业归 #2315；`.gitattributes` 对检出的影响由取料片按 git 对象取料来规避（备忘 3.3 实现约束第一条）。
- **大小写不敏感的文件系统。** 预检按字节判定，不折叠大小写。`FORMAL_MATH/x` 不算受管路径；在 macOS 上检出时它会与 `formal_math/` 合流。`formal_math/` 内部只差大小写的两条路径会判红，但仓库根上的变体不查。后续片取料按 git 对象路径取，不经检出，不受影响；本地检出不在承诺内。
- **其它 fsck 级畸形对象。** 预检拒收重复或乱序的树条目（`BAD_TREE`），但不查条目名里含 `/`、`.git`、`..` 之类，这些依赖对象库在收包时做过 fsck〔未核实 GitHub 对 PR 推送是否全量 fsck〕。
- **中间提交。** 只比两端提交，中间提交里出现又删掉的东西不进被审树，不影响判定。
- **shallow 克隆或安全目录检查导致的误判。** 祖先关系查不到或 git 拒绝打开仓库时退 2，结论偏向失败，不会放行。

## 与现有 `run_gates.py` 门 6b 角色表的出入

对照 `origin/infra/2312-d-perimeter` @ `594e49b5ec` 的 `formal_math/verification/run_gates.py:503-517`（`PATHS`）及其后的 `gate6b`。

| 项 | 旧 | 新 | 理由 |
|---|---|---|---|
| `infra` 的脚本 | `scripts/` 整个目录 | 只有 `scripts/fm_env.sh` | 受信文件逐个列全名，不用宽前缀（备忘第六节第三处） |
| `infra` 的工作流 | `.github/workflows/` 整个目录，连 `ci.yml` 也在内 | 只有 `.github/workflows/formal-math.yml` | 同上 |
| `ChanExplore/`、`ChanExplore.lean` | `infra` | `proof` | R5-B1 的入口：`infra` 能同时改 `lakefile.toml` 与 `ChanExplore/` 下的 Lean 文件。`infra` 现在只能改受信面 |
| `lake-manifest.json`、`lean-toolchain` | 不属于任何角色 | `infra`，需放行 | 旧表下升级工具链或依赖无路可走；它们属于受信文件 |
| `verification/garbage-signoffs.yaml` | `decl` 可改；`infra` 在基线缺此文件时可初始化为空（`initializes_empty_signoffs`） | 不给任何内容角色开门禁目录的口子；特例删去 | 门禁目录里不放别的角色的数据（备忘 3.3）。见「待后续片处理」 |
| `formal_math/garbage-signoffs.yaml` | 无 | `decl`，并列入顶层固定名字 | 给上一项预留的新家，沿用备忘原型 |
| 改 `verification/` 等受信面 | `infra` 直接通过 | `infra` 需放行开关 | 备忘 3.1 受信文件流程 |
| 分支名 | `前缀/` 后去掉空白非空即可 | 固定文法 | 备忘 3.3 第 2 条 |
| 改动集合 | 提交、暂存区、工作树、未跟踪文件四层拼起来 | 只有两端提交 | 门禁只审提交；R5-B6 出在四层没对齐 |
| 基线 | `merge-base origin/main HEAD`，可被 `ACCEPTED_LAYOUT` 覆盖 | 调用方给出，必须是祖先 | 备忘 3.3 第 1 条 |
| 符号链接 | 只查工作树与暂存区 | 查被审提交整棵 `formal_math/` 的模式 | R5-B6 |
| 整树形状 | 不查 | 第 6 条 | R5-B2、R5-B3 |
| 无角色分支 | 一律红 | 只在碰了受管路径时红 | 预检只管 `formal_math/` 与受信文件 |

`decl`、`proof` 其余表项与 `audit` 整张表与旧表相同。

和备忘原型 `expT/preflight_proto.py` 的出入：原型把 `formal_math/README.md` 列为受信文件，这里按票面清单不列，只归 `infra`；原型的形状规则放行 `100755` 并跳过 `verification/` 内部，这里只放行 `100644`，`verification/` 内部也查文法；原型不查空子树、大小写与树条目顺序。

## 自举问题

`main` 上现在没有 `formal_math/`，所以本片合入时没有基线版本的预检可用，只能靠评审。同理，基线里没有 `formal_math/` 时，一次性引入整个包的 PR 必然同时含受信文件与内容文件，任何单一角色都过不了预检：要么按角色拆成多个 PR（先 `infra` 引入受信面并放行，再各内容角色），要么由主控对首批引入记账放行。

在真实仓库上试跑（基线 `e3336ee721`，被审 `594e49b5ec`，分支 `infra/2312-d-perimeter`），现有文件里有一处不合形状规则：`formal_math/.gitignore`（顶层隐藏名，`PATH_GRAMMAR`）。规则不为它放宽，见下一节。

## 待后续片处理

- `formal_math/verification/garbage-signoffs.yaml` 搬出门禁目录，建议落到 `formal_math/garbage-signoffs.yaml`（`decl`）。搬家本身同时动门禁目录与 `decl` 路径，要拆两步或记账放行。
- `formal_math/.gitignore` 不合形状规则。它只影响未跟踪文件，对按提交审的门禁没有作用，建议并入仓库根 `.gitignore`（`formal_math/.lake/`）后删除。
- `formal_math/Chan/Smoke.lean` 及 `Chan/` 根下的其它文件不属于任何角色，改它们在任何角色下都是 `PATH_SCOPE`（旧表同样如此）。
- 放行开关的载体与发布通道。
- 取料（备忘 3.3 第 8 条）、夹具单调（备忘 3.1 第 2 条）、运行骨架与七步顺序。
- 由主干版本工作流触发并设为必需检查（#2315）。

## 自测

```sh
TMPDIR=<有空间的目录> python3 -I selftest.py            # 全部用例
TMPDIR=<有空间的目录> python3 -I selftest.py --mutants  # 弱化自测
```

- 用例在临时目录（跟随 `TMPDIR`）里现造 git 仓库，仓库路径含非 ASCII 字符与空格。提交用 `mktree`、`commit-tree`、`hash-object --literally` 造，所以能造出空子树、子模块、符号链接、重复或乱序的树条目、含换行的路径。暂存区与工作树里故意放了会被判红的东西（暂存的 `formal_math/lakefile.lean`、掩盖提交里符号链接的普通文件），预检必须不受影响。
- 每个用例断言退出码与规则码集合，绿例还断言绿行。参数、祖先、输出类用例另断言失败原因：管道断开时标准错误里确有 `Broken pipe`，标准输出关闭时确有 `Bad file descriptor`，ASCII locale（`LC_ALL=C` 加 `-X utf8=0`）下绿行按 UTF-8 解出后逐字相符，红行按 UTF-8 解出后含预期的中文说明；含换行的路径在红行里转义成 `\x0a`，整行仍只占一行。
- `--mutants` 先断言未改弱的副本全过，再把预检在副本里分别改弱：去掉第 7 步、去掉模式判断、去掉目录节点核对、角色表前缀放宽一项（`infra` 的门禁目录放宽为 `formal_math/`；`proof` 的 `Chan/Thm/` 放宽为 `Chan/`），每种弱化都必须有用例失败。改弱点在源码里找不到或不唯一时自测判失败。
- 自测的合同：正常环境与 ASCII locale 下，预检正确时退 0，被改弱时退非 0。自测自己的输出按 UTF-8 字节写文件描述符。自测在被破坏的输出环境下如何退出不在合同内。
