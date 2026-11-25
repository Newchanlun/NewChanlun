# formal_math 纯静态预检（#2312 第一片）

`precheck.py` 判定一次合入是否只改了分支角色允许的路径、受信文件是否仍是基线那一份、被审提交里整棵 `formal_math/` 的形状是否合规。它是整套门禁里唯一承担**对抗断言**的自写代码：能构造出（基线、被审提交、分支名、放行开关）使它退 0、而某个受信文件与基线不同、或有角色之外的受管路径被改、或 `formal_math/` 下出现形状规则之外的条目，即为缺陷。

设计依据：`origin/evidence/2312-design-consult` @ `aedff2e010` 的备忘 3.1–3.4、3.7，#2312 评论 7175991382；第一轮独审 `origin/evidence/2312-precheck-review` @ `05c55cc941` 的 `precheck-review-r1.md`。

## 调用

```sh
python3 -I precheck.py [--trusted-change-approved] <仓库> <基线提交> <被审提交> <分支名>
```

- 只认这一种写法。放行开关只能是第一个参数且逐字相等；缩写、`--x=y`、重复、放在后面都算用法错误。仓库、基线、被审三个参数不得为空或以 `-` 开头，分支名不得以 `-` 开头。
- 放行开关只对 `infra` 角色有意义，其它角色给了也不起作用（有用例）。
- 不读暂存区与工作树，不检出，不写任何文件。用到的 git 命令只有三个：`rev-parse --verify --quiet --end-of-options`（把参数解析成提交与根树）、`merge-base --is-ancestor`、`cat-file --batch`（读树对象原始字节）。
- git 子进程的环境从零构造：`LC_ALL=C`、`GIT_NO_REPLACE_OBJECTS=1`、`GIT_GRAFT_FILE` 指向空设备、不读系统与全局配置，`PATH` 沿用调用方。

## 输出与退出码

| 退出码 | 含义 |
|---|---|
| 0 | 判定为绿，且绿行 `PRECHECK GREEN OK <被审提交> role=<角色或->` 已完整写到标准输出 |
| 1 | 判红。每条红行写到标准输出；红行写不出不改变结论 |
| 2 | 无法判定：参数无效、提交解析不出、基线不是祖先、基线树不规范、git 失败或输出无法解读、对象缺失、意外异常、绿行写不出。已查出的红行照样先写，再写一行 `PRECHECK FAULT` 到标准错误 |

- 行格式固定，一行一条：`PRECHECK RED <规则码> <路径或对象> <说明>`，`PRECHECK FAULT <故障码> <对象> <说明>`。根树本身的问题，对象一栏写 `-`。
- 路径或对象一栏按字节输出，空白、反斜杠、控制字符与非 ASCII 字节一律转义为 `\xNN`，所以一条一定只占一行。
- 编码：脚本自己写的绿行、红行与故障行按 UTF-8 字节直接写文件描述符，不经 Python 文本层，不随 locale 变。git 的诊断原样透传到标准错误。标准错误写不出时诊断丢失，退出码不变。

## 单一视图：受管清单

预检对基线与被审提交各取一份**受管清单**，此后所有判定只读这两份清单与它们的集合差。

- **范围**：`formal_math` 根节点及其下全部条目（文件与目录节点都在内），加仓库根下的两个受信文件 `scripts/fm_env.sh`、`.github/workflows/formal-math.yml` 及其祖先目录节点 `scripts`、`.github`、`.github/workflows`。
- **读法**：从提交的根树起逐层读树对象，每层一次 `git cat-file --batch`，按树对象的原始字节逐条解析「模式 空格 名字 NUL 对象名」。每条记下（路径、原始模式串、对象名）。只沿受管范围往下读，受管范围以外的子树不读。
- **为什么不用 `ls-tree`**：`ls-tree` 与 `cat-file -p` 会把模式规范化后再显示。实测（git 2.53）：一棵原始字节为 `100664 a` 的树，`ls-tree` 与 `cat-file -p` 都显示成 `100644`；审阅报告实测 `diff-tree` 同样如此，`040755` 显示成 `040000`。`cat-file --batch` 输出的是对象的原始内容，同一棵树在其输出里仍是 `100664 a\0…`，所以预检看到的模式就是对象里记录的模式。读取处逐个核对头行（对象名、类型、长度）、内容长度与结尾换行，并核对整段输出没有多余字节。
- **改动集合**：一条路径在两份清单里的（原始模式、对象名）不同，或只在一边出现，就是一条改动；目录节点的增删改同样算。仓库根下受信文件的三个祖先目录只核对形状，不算改动：它们的对象名会随无关文件变化。

## 规则

顺序固定。第 1 条不满足即退 2。被审清单的规范性（第 2 条）总是报告；改动集合为空时不论分支名直接绿，否则继续第 4–7 条。

| 码 | 规则 | 判什么 | 凭什么 |
|---|---|---|---|
| `NOT_ANCESTOR`（退 2） | 1 | 基线不是被审提交的祖先 | `merge-base --is-ancestor` 的退出码 |
| `TREE_FORM` | 2 | 被审提交里读到的某棵树（根树、受信文件的祖先目录、`formal_math` 下每一层）不规范：无法逐条解析（含空名、名字含 `/`、截断）；同一层条目名重复（不论同类异类）；未按 git 顺序严格递增；模式是目录的条目指向的对象不是树 | `cat-file --batch` 的原始字节 |
| `BASE_FORM`（退 2） | 2 | 基线清单有上一行的任一问题 | 同上 |
| `BRANCH_ROLE` | 2、4 | 分支名不合文法、解析不出角色，却改了受管路径 | 分支名参数对固定文法 `(decl\|proof\|audit\|infra)/W(/W)*` 全匹配，`W = [A-Za-z0-9]+([._-][A-Za-z0-9]+)*`。空后缀、`..`、首尾分隔符、空白、非 ASCII、多余前缀都不给角色 |
| `PATH_SCOPE` | 4、5 | 某条改动不在该角色的路径表里。两侧有一侧是文件时，路径须落在表项内（以 `/` 结尾的表项按字节前缀，其余逐字相等）；两侧都是目录或不存在时，目录须落在表项内或是某个表项的祖先目录 | 清单集合差 |
| `TRUST_UNAPPROVED` | 5 | `infra` 角色的改动集合碰了受信面（门禁目录节点本身或其下任一条目、五个受信文件），调用方没给放行开关 | 清单集合差 |
| `MODE` | 6 | `formal_math` 根节点不是 `40000` 目录，或其下有原始模式不是 `100644` 文件或 `40000` 目录的条目：符号链接、可执行位、子模块、`100664` 一类非规范文件模式、`040000` 一类带前导零的目录模式；两个仓库根下受信文件不是 `100644`；它们的祖先目录不是 `40000` | 被审清单的原始模式串 |
| `EMPTY_TREE` | 6 | `formal_math` 下（含根节点）有目录节点不是任何文件的祖先，即目录节点集合多于文件路径的祖先集合。空子树、只含空子树的目录、空的 `formal_math` 都在内 | 被审清单 |
| `PATH_GRAMMAR` | 6 | `formal_math/` 下某个路径段不合 `[A-Za-z0-9_]+([.-][A-Za-z0-9_]+)*`（隐藏名、空白、换行、非 ASCII、以点或连字符结尾、连续分隔符都进不来），或两条路径只差大小写 | 被审清单 |
| `TOP_LEVEL` | 6 | `formal_math/` 顶层出现固定名字表以外的名字，或名字对了类型不对 | 被审清单 |
| `CONTENT_SHAPE` | 6 | 内容根 `Chan/`、`ChanTest/`、`ChanChallenge/`、`ChanDyn/`、`ChanExplore/` 下出现不合模块名文法 `[A-Za-z][A-Za-z0-9_]*` 的目录，或不是 `<模块名>.lean` 的文件 | 被审清单 |
| `LAKE_FILE` | 6 | `formal_math/` 下任何层级出现名为 `lakefile.toml`、`lakefile.lean`、`lake-manifest.json`、`lean-toolchain`、`.lake` 的条目（按 ASCII 小写比较），例外只有六个逐字写死的路径：根上的 `lakefile.toml`、`lake-manifest.json`、`lean-toolchain`，以及 `verification/auditor/` 下同名的三个 | 被审清单 |
| `TRUSTED_DRIFT` | 7 | 非 `infra` 角色下，某个受信文件或门禁目录节点在两份清单里的（原始模式、对象名）不同，缺失也算 | 两份清单逐路径比对。与 `PATH_SCOPE` 互为冗余，不依赖角色表写对 |

其它故障码：`USAGE`（参数）、`BAD_REV`（解析不出提交）、`GIT`（git 启动失败、非预期退出码、对象缺失、`cat-file` 输出与请求对不上）、`OUTPUT`（绿行写不出）、`INTERNAL`（意外异常）。

一份被审清单出现重复条目时，预检报 `TREE_FORM`，并以先出现的那一条为准继续判定其余规则；结论已经是红，后续红行只供参考。

### 受信面

受信文件逐个列全名：`formal_math/lakefile.toml`、`formal_math/lake-manifest.json`、`formal_math/lean-toolchain`、`scripts/fm_env.sh`、`.github/workflows/formal-math.yml`。外加门禁目录 `formal_math/verification/`，第 7 条按目录节点的对象名比较。

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

`verification/`、`sources/`、`blueprint/` 内部查模式、空目录、路径段文法、大小写与 Lake 配置名。

## 信任前提

- **运行的必须是基线版本的脚本，并由主干版本的工作流触发。** 若由 PR 自己的工作流或 PR 自己的 `precheck.py` 执行，被审方可以直接改掉判定，本片的一切断言不成立。这一条归 #2315（`pull_request_target` 或宿主侧发布必需检查）。
- **放行开关的载体未定。** 本片只认命令行开关。谁有权给、如何保证它独立于写代码的代理（备忘 3.1：标签若能由执行器令牌打上就不独立），由后续片与 #2315 决定。
- **角色是分支名自报的。** 任何人都能起任一角色前缀的分支，预检只保证「声称是 X 角色的改动确实只碰了 X 的受管路径」。角色之间的约束（谁能开 `decl/*`）靠各自的评审流程。
- **基线由调用方给出**，应当是合入目标 `main` 的当前提交。基线本身的形状问题（如现有的 `formal_math/.gitignore`）不阻止判定；基线的树对象不规范则退 2。
- git 可执行文件、仓库的 `.git` 目录（对象库、仓库级配置、shallow 信息）可信。预检屏蔽了替换对象、grafts、系统与全局配置，但仓库级配置仍由 git 读取。
- git 须支持 `rev-parse --end-of-options`（本机实测 git 2.53，审阅者实测 2.50.1）；不支持时 git 报错，预检退 2。

## 不防什么

- **能改受信文件的人**（`infra` 作者与放行者）。放行之后受信文件的改动正确与否，靠非作者对抗评审与制度。
- **文件内容。** 预检不读任何 blob：Lean 源码、`lake-manifest.json` 的字段、锁文件是否正确，都归后续片或评审。模式是文件的条目指向的对象是不是 blob 也不查；指错了，后续按对象取料时会失败。
- **受管范围以外的改动。** 无论分支名有没有角色，改其它工作流（如 `ci.yml`）、其它脚本、仓库根 `.gitattributes` 都不判红。工作流能否影响 formal-math 作业归 #2315；`.gitattributes` 对检出的影响由取料片按 git 对象取料来规避（备忘 3.3 实现约束第一条）。
- **大小写不敏感的文件系统。** 预检按字节判定。`FORMAL_MATH/x` 不算受管路径；在 macOS 上检出时它会与 `formal_math/` 合流。`formal_math/` 内部只差大小写的两条路径、大小写变体的 Lake 配置名会判红，但仓库根上的变体不查。后续片取料按 git 对象路径取，不经检出，不受影响；本地检出不在承诺内。
- **受管范围以外的树对象畸形。** 根树与受信文件的祖先目录逐层核对，`formal_math` 整棵逐层核对；受管范围以外的子树不读。
- **中间提交。** 只比两端提交，中间提交里出现又删掉的东西不进被审树，不影响判定。
- **shallow 克隆或安全目录检查导致的误判。** 祖先关系查不到或 git 拒绝打开仓库时退 2，结论偏向失败，不会放行。

## 与现有 `run_gates.py` 门 6b 的出入

对照 `origin/infra/2312-d-perimeter` @ `594e49b5ec` 的 `formal_math/verification/run_gates.py:503-582`（`PATHS`、`initializes_empty_signoffs`、`gate6b`），逐行重核过一遍。

| 项 | 旧 | 新 | 理由 |
|---|---|---|---|
| `infra` 的脚本 | `scripts/` 整个目录 | 只有 `scripts/fm_env.sh` | 受信文件逐个列全名，不用宽前缀（备忘第六节第三处） |
| `infra` 的工作流 | `.github/workflows/` 整个目录，连 `ci.yml` 也在内 | 只有 `.github/workflows/formal-math.yml` | 同上 |
| `ChanExplore/`、`ChanExplore.lean` | `infra` | `proof` | R5-B1 的入口：`infra` 能同时改 `lakefile.toml` 与 `ChanExplore/` 下的 Lean 文件。`infra` 现在只能改受信面 |
| `lake-manifest.json`、`lean-toolchain` | 不属于任何角色 | `infra`，需放行 | 旧表下升级工具链或依赖无路可走；它们属于受信文件 |
| `decl` 改 `verification/garbage-signoffs.yaml` | 允许 | 不允许 | 门禁目录不给内容角色开口（备忘 3.3） |
| `infra` 改 `verification/garbage-signoffs.yaml` | 只在基线缺此文件时可新建为空 `{}`；基线已有时不许改删 | 获放行即可改删，与门禁目录其它文件一样 | 该文件归受信面后，它的改动走受信文件流程；特例逻辑 `initializes_empty_signoffs` 删去。见「待后续片处理」 |
| `formal_math/garbage-signoffs.yaml` | 无 | `decl`，并列入顶层固定名字 | 给上一项预留的新家，沿用备忘原型 |
| 改受信面 | `infra` 直接通过 | `infra` 需放行开关 | 备忘 3.1 受信文件流程 |
| 分支名来源 | 读 `git symbolic-ref HEAD`；分离 HEAD 时读环境变量 `GITHUB_HEAD_REF`，两者都没有退 2 | 第 4 个命令行参数；不读 `HEAD` 也不读环境变量；空串合法，只是解析不出角色 | 门禁只审提交，输入显式化 |
| 分支名文法 | `前缀/` 后去掉空白非空即可 | 固定文法 | 备忘 3.3 第 2 条 |
| 无角色分支 | 一律红（`BRANCH_PREFIX`），不再做其它检查 | 只在改了受管路径时红（`BRANCH_ROLE`），并照常做形状与第 7 条 | 预检只管受管范围 |
| 有角色分支改受管范围以外的路径 | 每条都判 `PATH_SCOPE`（如 `proof/x` 只改 `rust/lib.rs` 也红） | 不看：只改受管范围以外的路径直接绿，与受管改动一起改时也不报 | 预检只管受管范围；其它路径归各自的检查 |
| 改动集合 | 提交、暂存区、工作树三层 `diff --name-only`，再加全仓未跟踪文件 | 两端提交的受管清单集合差，目录节点与原始模式都在内 | 门禁只审提交；R5-B6 出在四层没对齐；R1-B1 至 B3 出在 `diff-tree` 看不见目录节点与非规范模式 |
| 基线 | `merge-base refs/remotes/origin/main HEAD`，可被 `ACCEPTED_LAYOUT` 覆盖 | 调用方给出，必须是祖先 | 备忘 3.3 第 1 条 |
| 符号链接 | 只查改动路径在工作树与暂存区里是不是链接 | 查被审提交整棵 `formal_math` 的原始模式 | R5-B6 |
| 整树形状 | 不查 | 第 2 条与第 6 条 | R5-B2、R5-B3、R1-B1、R1-B2、R1-B4 |
| 输出 | `GATE6b RED <路径>:1 <码> <说明>`，码为 `BRANCH_PREFIX`、`SYMLINK`、`PATH_SCOPE` | `PRECHECK RED <码> <路径> <说明>`，码见上表 | 本片的固定行格式 |

`decl`、`proof` 其余表项与 `audit` 整张表与旧表相同。

和备忘原型 `expT/preflight_proto.py` 的出入：原型把 `formal_math/README.md` 列为受信文件，这里按票面清单不列，只归 `infra`；原型的形状规则放行 `100755` 并跳过 `verification/` 内部，这里只放行 `100644`，`verification/` 内部也查；原型用 `ls-tree` 与 `diff-tree`，这里读原始树对象。

## 自举问题

`main` 上现在没有 `formal_math/`，所以本片合入时没有基线版本的预检可用，只能靠评审。同理，基线里没有 `formal_math/` 时，一次性引入整个包的 PR 必然同时含受信文件与内容文件，任何单一角色都过不了预检：要么按角色拆成多个 PR（先 `infra` 引入受信面并放行，再各内容角色），要么由主控对首批引入记账放行。

在真实仓库上试跑（被审 `594e49b5ec`），现有文件里有 17 处不合形状规则，规则不为它们放宽，见下一节：

- `formal_math/.gitignore`（顶层隐藏名，`PATH_GRAMMAR`）。
- `formal_math/verification/must_green/` 与 `must_red/` 下旧门 1、门 2 夹具里的 16 个 Lake 配置名文件（`LAKE_FILE`）：`must_green/g1/pins/formal_math/lean-toolchain`；`must_red/g1/` 下 `r4-manifest-path-source`、`r4-manifest-url`、`revision` 三处 `lake-manifest.json` 与 `toolchain` 一处 `lean-toolchain`；`must_red/g2/` 下 `lib-option`、`missing-option`、`r2-a5-build-config`、`r2-a6-build-config`、`r2-a6b-build-config`、`r2-a6c-build-config`、`r2-a6d-build-config`、`r4-p6a-lakefile-invalid-toml`、`r4-p6b-lakefile-more-lean-args`、`r4-p6c-lakefile-package-options`、`unimported-child` 十一处 `lakefile.toml`（均在各自的 `formal_math/` 子目录下）。

## 待后续片处理

- `formal_math/verification/garbage-signoffs.yaml` 搬出门禁目录，建议落到 `formal_math/garbage-signoffs.yaml`（`decl`）。搬家本身同时动门禁目录与 `decl` 路径，要拆两步或记账放行。
- `formal_math/.gitignore` 不合形状规则。它只影响未跟踪文件，对按提交审的门禁没有作用，建议并入仓库根 `.gitignore`（`formal_math/.lake/`）后删除。
- 门禁目录里旧门 1、门 2 的 16 个 Lake 配置名夹具：旧门 1、门 2 在第四片随旧门禁一并删除；若届时仍需配置类夹具，改为在自测里现造，不入库。
- 审计程序包落地时只能用 `verification/auditor/` 下那三个逐字写死的配置路径。
- `formal_math/Chan/Smoke.lean` 及 `Chan/` 根下的其它文件不属于任何角色，改它们在任何角色下都是 `PATH_SCOPE`（旧表同样如此）。
- 放行开关的载体与发布通道。
- 取料（备忘 3.3 第 8 条）、夹具单调（备忘 3.1 第 2 条）、运行骨架与七步顺序。
- 由主干版本工作流触发并设为必需检查（#2315）。

## 自测

```sh
TMPDIR=<有空间的目录> python3 -I selftest.py            # 全部用例
TMPDIR=<有空间的目录> python3 -I selftest.py --mutants  # 弱化自测
```

- 用例在临时目录（跟随 `TMPDIR`）里现造 git 仓库，仓库路径含非 ASCII 字符与空格。树对象全部用 `hash-object -t tree --literally` 直接写原始字节，所以能造出空子树、子模块、符号链接、非规范模式、重复或乱序的条目、名字含 `/` 的条目、目录条目指向 blob、含换行的路径。暂存区与工作树里故意放了会被判红的东西（暂存的 `formal_math/lakefile.lean`、掩盖提交里符号链接的普通文件），预检必须不受影响。
- 每个用例断言退出码与规则码集合；绿例逐字断言绿行。标准输出只许出现 `PRECHECK RED`、`PRECHECK GREEN` 行，标准错误里的 `PRECHECK` 行只许是故障行，错位即失败。参数、祖先、输出类用例另断言失败原因：管道断开时标准错误里确有 `Broken pipe`，标准输出关闭时确有 `Bad file descriptor`，ASCII locale（`LC_ALL=C` 加 `-X utf8=0`）下绿行按 UTF-8 解出后逐字相符，红行按 UTF-8 解出后含预期的中文说明；含换行的路径在红行里转义成 `\x0a`，整行仍只占一行。
- 第一轮独审 B1 至 B5 的每个复现形状都有同名前缀 `R1-` 的用例；五个受信文件各有「内容角色改它」「内容角色删它」两条用例。
- `--mutants` 先断言未改弱的副本全过，再把预检在副本里逐一改弱，每种弱化都必须有用例失败；改弱点在源码里找不到或不唯一时自测判失败。弱化清单见 `selftest.py` 的 `MUTANTS`：去掉第 7 步、去掉模式判断、去掉空目录核对、目录节点的改动不过路径权限、`infra` 门禁目录前缀放宽为 `formal_math/`、`proof` 的 `Chan/Thm/` 放宽为 `Chan/`、第 7 步漏比 `lean-toolchain`、放行开关让内容角色跳过第 7 步、去掉树条目重名检查、去掉树条目次序检查、Lake 配置名只查顶层、去掉大小写冲突判断、祖先检查恒真、分支名文法放宽、目录条目不核对对象类型。
- 第一轮独审另做的 8 种弱化里，M1、M2、M3、M4、M7 已收进上面的清单；M8（去掉空子树检查）对应「去掉空目录核对」。M5（去掉 `diff-tree` 的 `--no-renames`）不再适用：预检不用 `diff-tree`，改动集合是两份清单按路径做的集合差，没有重命名或复制检测这回事。M6（受信文件模式检查漏掉 `formal-math.yml`）不再适用：模式检查对整份清单一视同仁，没有逐个文件的列表可漏；`formal-math.yml` 改成可执行、符号链接、目录各有用例。
- 自测的合同：正常环境与 ASCII locale 下，预检正确时退 0，被改弱时退非 0。自测自己的输出按 UTF-8 字节写文件描述符。自测在被破坏的输出环境下如何退出不在合同内。
