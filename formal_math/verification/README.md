# FM-04 数学包门禁

门禁分两部分：**阻断门**只管可判定的可信边界，红即不得合入；**审阅报告**汇总陈述质量的语义读数，
不阻断，交给声明评审 PR 的非作者独审逐条处置。划分依据是 #2312 的用户裁定（评论 `7164343103`）。

```sh
source scripts/fm_env.sh
python3 formal_math/verification/run_gates.py --repo-root .              # 全部阻断门
python3 formal_math/verification/run_gates.py --repo-root . --gate 3     # 单查一道阻断门
python3 formal_math/verification/run_gates.py --repo-root . --report --report-dir <目录>
python3 formal_math/verification/selftest.py --jobs 3                    # 阻断门自测 + 报告回归
```

阻断门退出码为 **0 绿、1 红、2 无法判定**；CI 不接受 2。红行格式是
`GATE<编号> RED <文件>:<行或声明名> <代码> <说明>`，诊断写到标准错误。默认运行（含 `--stage`
的任何取值）只跑阻断门 1、2、3、6a、6b、15。报告的退出码恒为 0，只有工具自身出错
（构建失败、环境加载失败、台账无法解码）才退 2。

## 一、阻断门

| 门 | 机械承诺 |
|---|---|
| 1 钉选 | 文件中的工具链、运行中的 Lean 与九个依赖的修订须符合钉选。 |
| 2 受控选项与零告警 | `autoImplicit`、`relaxedAutoImplicit`、`linter.*` 不得在 Lake 目标或源码的**任何语法位置**设置（见下文「选项设置的判定」）；`lake build --wfail` 构建默认目标和源码发现的全部模块。 |
| 3 源码层 | 可信目录 `Chan`、`ChanChallenge`、`ChanDyn`、`ChanTest`（及 `ChanExplore`，另多放行 `#eval`）里的命令、声明、修饰符、属性、派生目标类、选项与导入全部走白名单，名单外即红；Lean 实际精化的命令（宏展开与精化器生成的命令）同样过白名单。审计程序不执行被审代码。 |
| 3 环境层 | 公理与公理闭包查全部常量，闭包只接受 `propext`、`Classical.choice`、`Quot.sound`。`unsafe`、`partial`、`implemented_by`、`extern`、`meta` 查**全部**常量；只有能机械复核为 Lean 自动生成的三类辅助项才豁免（见下文）。不按有无声明范围豁免，不按名字后缀匹配。 |
| 6a 声明锁 | Defs、Hypotheses、Audit/Literal、ChanChallenge 按环境中的模块归属枚举，含私有声明。`FM-lock-v2` 以序号表达绑定变量和宇宙参数，编码声明类别、可约性、类型与非定理的定义体。锁集多、少、变均红。 |
| 6b 路径权限 | 分别核对提交、暂存区与工作树的变更；不让差异相消。声明锁及非空签注由 `decl/` 维护；`infra/` 只能初始化空签注。分离 HEAD 用 `GITHUB_HEAD_REF`，缺失退 2。 |
| 15 模块边界 | 首条命令为 `module`；导入不能越过目录的直接或传递边界，不能整库导入 Mathlib。只有审计工具可 `import all`。Defs 须写 `@[expose] public section`，公开可计算定义也须真的有公开定义体。 |

### 门 3 源码层的白名单（Lean 4.36.0 本机枚举）

`fm_audit source` 用加载本轮依赖后的 Lean 前端逐条解析、检查、再精化命令。每条命令分两步查：

1. **表层预检**（精化之前）：命令语法树整树过下列白名单；有门 3 红即不精化该命令，文件到此为止。
2. **精化结果复核**（精化之后）：读这条命令留下的信息树。Lean 每精化一条命令（含宏展开产物、
   派生处理器等精化器生成的命令）都留一个 `CommandInfo`，每次设置选项都经
   `Lean.Elab.elabSetOption` 留一个 `OptionInfo`。逐个 `CommandInfo` 的语法树按同一白名单查，
   逐个 `OptionInfo` 按选项规则查。唯一差别：生成命令里的 `partial` 不在此处判，交给环境层按
   生成来源判（Lean 的 `Repr`、`BEq`、`Hashable`、`Ord` 派生处理器对递归类型会生成 `partial def`）。

名单如下（省去前缀 `Lean.Parser.Command.`）：

- **命令**：`moduleDoc`、`namespace`、`section`、`end`、`open`、`variable`、`universe`、`include`、
  `omit`、`in`、`declaration`、`mutual`、`set_option`、`check`、`attribute`、`deriving`（独立的
  `deriving instance`）；`Lean.guardMsgsCmd` 仅 `Chan/Final`；`eval` 仅 `ChanExplore`。生成命令另允许
  `cmd in` 展开出的内部命令 `InternalSyntax.end_local_scope`。`in`、`mutual`、`#guard_msgs`
  内的命令照样按命令验（`#guard_msgs` 的内嵌命令是第 4 号子节点）。
- **`#guard_msgs`**：内嵌命令不得是声明（否则可用期望消息吞掉告警），规格不得含 `drop`。
- **声明**：`definition`、`theorem`、`abbrev`、`opaque`、`example`、`inductive`、`classInductive`、
  `structure`、`instance`。
- **修饰符**：`meta`、`unsafe`、`partial` 必红；`meta section` 必红；其余（可见性、`protected`、
  `noncomputable`、`nonrec`）放行。
- **属性**：按 Lean `elabAttr` 的取名规则比对（先展开属性宏；`Attr.simple` 取标识符，其余取语法
  种类末段）。白名单为 `simp`、`ext`、`instance`、`reducible`、`irreducible`、`inline`、`specialize`、
  `expose`、`no_expose`、`grind`、`norm_cast`、`push_cast`、`refl`、`symm`、`trans`、`gcongrAttr`、
  `mono`、`congr`、`elab_as_elim`、`induction_eliminator`、`cases_eliminator`、`deprecated`、`simps`、
  `method_specs`（派生处理器为结构生成）。注册宏、精化器、解析器、初始化器、派生处理器以及改写
  编译产物的属性（`macro`、`*_elab`、`*_parser`、`init`、`builtin_*`、`implemented_by`、`extern`、
  `export`、`csimp` 等）都不在名单里。`attribute [-x]` 的擦除同样按此名单。
- **派生目标类**（行内 `deriving` 与独立 `deriving instance`，按解析后的全名）：`DecidableEq`、`BEq`、
  `ReflBEq`、`LawfulBEq`、`Hashable`、`Ord`、`Repr`、`Inhabited`、`Nonempty`。
- **选项**：受控选项归门 2；其余只许 `maxRecDepth`、`maxHeartbeats`、`synthInstance.maxHeartbeats`、
  `synthInstance.maxSize`、`match.ignoreUnusedAlts`（派生处理器生成）与 `pp.*`。库宏在展开时设置的
  选项同样受此名单约束，例如 `rfl'` 展开出 `smartUnfolding`，判红。
- **导入**：只许可信目录模块与 `Init`、`Std`、`Mathlib`、`Batteries`；`Lean`、`Lake`、`Qq`、`Aesop`
  等钉选库判红（只加载库代码，红后仍继续精化以便门 2 继续读数）；`meta import`、`import all`、
  `prelude`、非 `module` 文件、`ChanExplore`／`verification` 等其他来源判红并立即停止，不加载导入。
- **其余禁用项**（整树）：`sorry`、`admit`、`native_decide`、`run_tac`、`run_meta`、`sorryAx` 标识符。

#### 选项设置的判定

不列节点名单，按类收：

- 表层：凡**首个子节点是 `set_option` 关键字**的语法节点都按选项设置处理，选项名取第二个子节点里的
  全部标识符。命令、项、战术、`grind =>` 内的 `set_option`，以及今后任何沿用这个关键字的新语法位置
  都在此列。
- 精化后：Lean 4.36.0 的四个 `set_option` 精化器（命令、项、战术、`grind`）都调用
  `Lean.Elab.elabSetOption`，它为每次设置推一个 `OptionInfo`。读信息树里的全部 `OptionInfo`，
  宏展开出的选项（表层看不到）也在其中。新语法若复用 `elabSetOption`，自动覆盖。

#### 审计期不执行被审代码

- 精化前先不运行任何初始化器读入导入闭包（`importModules (loadExts := false)`），按 `.olean` 的
  真实路径分出被审代码：不在工具链 `lib/lean` 或 `.lake/packages`（门 1 钉选）之下的模块都算。
  这些模块登记进 Lean 的 `interpretedModInits`，随后的 `processHeader` 不运行它们的 `[init]`。
- 若被审代码的任一导入模块含 `meta` 声明，拒绝精化（门 3 红）。在模块制下，只有 `meta` 声明能在
  精化期被解释执行，宏、精化器、初始化器都必须是 `meta`；`module` 又不能导入非 `module` 文件。
  因此精化期运行的代码只剩钉选库。
- `fm_audit selfcheck` 用一段固定样例（不走表层预检，样例在审计程序源码里，命令行不可改）核对
  精化结果复核确实看到宏生成的受控选项、`implemented_by` 属性、非白名单命令与库宏展开出的选项。

### 门 3 环境层的生成来源判据

常量带 `unsafe`、`partial`、`implemented_by` 时，只有能机械复核为下列三类之一才豁免；`extern` 与
`meta` 没有豁免。判据都在 `Audit.lean` 的 `generatedBy`：

1. **归纳类型的 `ctorIdx` 运行期实现**：`T.ctorIdx` 由 Lean 的 `isCtorIdxCore?` 认定（同模块的安全
   归纳类型），其 `implemented_by` 目标是同模块的 `unsafe` 定义，类型、宇宙参数与 `T.ctorIdx` 逐字
   相同，值是逐参数抽象后的 `getObjTagNat _ x`（即 `mkCtorIdxImpl` 生成的形状）。
2. **结构递归或良基递归的编译影子**：`partial` 定义经 `Compiler.isUnsafeRecName?` 指向源定义，源定义
   是同模块、内核检查过的安全 `def`，`isRecursiveDefinition` 登记它为结构或良基递归（Lean 的
   `recExt`），类型与宇宙参数逐字相同。
3. **派生处理器的辅助函数**：源定义是同模块的 `opaque`，其名字前缀是同模块的实例常量，实例类型为
   `C (T …)`（`C` 为 `Repr`、`BEq`、`Hashable`、`Ord`、`DecidableEq` 之一，`T` 为同模块归纳类型）；
   用 Lean 自己的 `Deriving.mkContext C 前缀 T` 在空的探针命名空间里重算，得到 `usePartial` 为真，
   实例名与辅助函数名恰与重算结果一致，且实例体引用重算出的辅助函数。

手写 `partial def` 被编译成 `opaque` 加 `_unsafe_rec`：源定义不是 `def`，也不满足第 3 类，判
`ENV_PARTIAL`。原处若因撞名给实例加过后缀，第 3 类重算对不上，按不豁免处理（误红方向）。

### 阻断门的已知不覆盖

- 信息树里 Lean 未保留内容的空洞（例如 `decreasing_by` 证明的战术信息）无从复核；其中手写的部分已
  过表层预检，库宏在其中生成的选项看不到。
- 库代码用 `withOptions` 等方式直接改选项而不经 `elabSetOption`，看不到；这类代码只来自钉选库。
- 门 1 不核包来源 `type`／`url`（第三轮 R3-S7），本轮未改。

## 二、审阅报告（不阻断）

`--report` 对可信目录逐常量输出 S、7a、7b、8a、8b、9、10 的读数：标准输出是 JSON
（`schema: fm-review-v1`），标准错误是 Markdown 表；给 `--report-dir` 时另写 `report.json`、
`report.md`。每条读数有：

- `status`：`finding`（命中）、`unknown`（拿不到读数，`detail` 写原因，如门 10 遇到类型类参数时
  `mkAppM` 失败）、`signed`（门 10 已签注且次数相符）、`no_finding`（未命中或不适用）。
- `evidence`：`certified` 只用于有内核可复核证书的发现——门 7b `GENERALIZES`（内核接受了泛化命题）、
  门 8b `DROPPABLE_PREMISE`（删前提后内核重放原证明成功）；其余一律 `hint`。

各项读数的含义：

| 读数 | 含义 | 已知不覆盖（第三轮夹具在 `report_cases/`） |
|---|---|---|
| S 陈述范式 | 骨架只接受全称／蕴含、`And`、`Or`、`Not`、`Iff`、`Exists`、`ExistsUnique` 或原子；不在骨架上用 `if`、`match`、`id`、投影或取默认值包装命题；`True` 不能作前提或合取项。已删除「闭命题不能作前提或合取项」。 | 连接词外包（`(x = x) ∧ …`、`True ↔ …`、`¬¬…`、`∃ _, …`），`Prop` 末端原子与局部变量头包装（`Eq … True`、`Nonempty …`、本地 `Prop` 归纳或结构、锁定别名）：`known_limits/gS`。 |
| 7a 定义依赖与居留 | 节点登记、自由判据的精化定理、含命题字段结构的 ChanTest 居留见证。 | 用 `Type` 级空字段（`{_n // False}`、`Empty`、`Fin 0`）跳过居留检查：`known_limits/g7a`。函数型判据的逐点精化不被接受：`finding/g7a/r3-c2-*`。 |
| 7b 抽象诊断 | 一致替换后内核接受泛化命题即 `GENERALIZES`（certified）。 | 经 Hypotheses 别名间接用归纳接口时读不出：`unknown/g7b/r3-e2-*`。 |
| 8a 形状诊断 | 前提实例化出结论（`PREMISE_INSTANCE`），函数图（`FUNCTION_GRAPH`）。 | 见 `known_limits/g8a`。 |
| 8b 未用前提 | 删前提后内核重放原证明成功即 `DROPPABLE_PREMISE`（certified）。 | `PProd.fst`、`id` 包装等：`known_limits/g8b`。 |
| 9 联合证据 | 见证定理、必要性反例与前提登记；便利前提列为 `CONVENIENCE` 提示。 | 依赖型前提生成不了闭见证命题时读不出：`unknown/g9/r3-e4-*`。 |
| 10 垃圾值 | Defs、ChanChallenge 中除、模、逆、Nat 减法等计数与签注对账（`SIGNOFF_MISSING`／`SIGNOFF_STALE`）。 | 伪造 `LT`／`OfNat` 实例的守卫、`Rat.divInt`、`mkRat`、`List.headI`／`getLastI`：`known_limits/g10`；带类型类参数的声明读不出：`unknown/g10`；`b⁻¹` 等偏严读数：`finding/g10/r3-d2-*`。 |

**独审者必须读这份报告并逐条处置**：每条 `finding` 与 `unknown` 都要在声明评审 PR 的审阅记录里写明
接受、改写陈述或驳回的理由；`certified` 发现驳回须给出内核证书为何不构成问题的说明。报告里的
`no_finding` 不代表安全：上表的不覆盖项靠独审、声明锁（门 6a）与 `lake comparator` 收口。

### 登记主定理的前提

台账使用 YAML 1.2 的 JSON 子集，不允许重复键。前提编号从 1 起，只数命题绑定：

```json
{
  "nodes": {
    "Chan.step": {
      "about": ["Chan.transition"],
      "mode": "依赖具体定义",
      "helpers": ["Chan.stepAux"],
      "main_theorem": true,
      "necessary": [1],
      "convenience": {"2": "记录调用协议，交非作者审阅"}
    }
  },
  "refinements": {"Chan.Endpoint": "Chan.endpointCriterion"}
}
```

此处需提供 `Chan.step.witness` 和 `Chan.step.without_1`；第 2 前提在报告中列为 `CONVENIENCE`。
私有定理见证保留 `_private`、模块名和数字组件，Lean 源码中将数字写作 `«0»`。签注样例：
`{"Chan.gap":{"Nat.sub":{"count":1,"review":"#票号／独审记录"}}}`。

## 三、自测

`selftest.py` 把每个夹具装入独立最小包（先预编译一次 `fm_audit` 供各夹具复用），从入口重算。
两类分开计数：

- **阻断门**：`must_red/g<门>/`、`must_green/g<门>/`、`must_unknown/g<门>/` 断言退出码 1／0／2 与红码集合，
  另跑一例 `fm_audit selfcheck`。夹具约定：`expect.txt` 红码；`expect_decls.txt` 声明名；
  `expect_detail.txt` 每行须出现在输出里（用来钉住是哪条规则判的）；`environment-only.txt`（配
  `modules.txt`）直调门 3 环境层；`source-only.txt`（模块名、路径、需先构建的依赖）跳过依赖顺序直审
  一个文件；`forbid-file.txt` 列出跑完后不得存在的文件（核对审计期没有执行被审代码）；
  `lean-version.txt`、`branch.txt`、`head.txt` 同前。
- **报告回归**：`report_cases/{finding,clean,unknown,known_limits}/g<门>/` 跑 `--report`，断言该门读数：
  `finding` 的命中代码集合等于 `expect.txt`（可配 `expect_decls.txt`、`expect_certified.txt`）；`clean`
  与 `known_limits` 无命中也无 `unknown`（后者须附 `README.md` 写明为何漏、由谁收口）；`unknown`
  至少一条 `unknown`。报告退出码须为 0。

macOS 上夹具与子进程临时文件放在 `/Volumes/AgentStorage/fm/tmp/`；Linux 上用 `TMPDIR`。根分区可用
低于 6 GiB 时停止派发。门 3 与报告装载 `.olean` 私有分片，并先读 ChanTest 的私有探针证明体；
可见性不足返回 2。

M-4 的本机实测：定义只写 `public section` 时，跨模块 `decide` 卡在不可展开的 `probeFlag`；改成
`@[expose] public section` 后，同一计算通过。对应夹具是 [no-expose](must_red/g15/no-expose) 和
[expose](must_green/g15/expose)。
