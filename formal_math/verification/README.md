# FM-04 数学包门禁

门禁分两部分：**阻断门**只管可判定的可信边界，红即不得合入；**审阅报告**汇总陈述质量的语义读数，
不阻断，交给声明评审 PR 的非作者独审逐条处置。划分依据是 #2312 的用户裁定（评论 `7164343103`）。

```sh
source scripts/fm_env.sh
python3 formal_math/verification/run_gates.py --repo-root .              # 全部阻断门
python3 formal_math/verification/run_gates.py --repo-root . --gate 3     # 单查一道阻断门
python3 formal_math/verification/run_gates.py --repo-root . --report --report-dir <目录>
python3 formal_math/verification/selftest.py --jobs 3                    # 阻断门自测 + 报告回归
python3 formal_math/verification/inventory.py <产物.json>                 # 维护：重收精化器候选
python3 formal_math/verification/make_lists.py <产物.json>                # 维护：重生成两份名单
```

阻断门退出码为 **0 绿、1 红、2 无法判定**；CI 不接受 2。红行格式是
`GATE<编号> RED <文件>:<行或声明名> <代码> <说明>`，诊断写到标准错误。默认运行（含 `--stage`
的任何取值）只跑阻断门 1、2、3、6a、6b、15。报告的退出码恒为 0，只有工具自身出错
（构建失败、环境加载失败、台账无法解码）才退 2。

## 一、阻断门

| 门 | 机械承诺 |
|---|---|
| 1 钉选 | 文件中的工具链、运行中的 Lean 与九个依赖须符合 `pins.json`：修订、来源类型（`git`）与来源地址都要对上。 |
| 2 受控选项与零告警 | `lakefile.toml` 的键与取值走白名单（下文），能向 Lean 传选项或参数的入口一律不在名单里；源码里**经 `set_option` 关键字或 `Lean.Elab.elabSetOption`** 设置的受控选项（`autoImplicit`、`relaxedAutoImplicit`、`linter.*`）判红；每条命令前后生效的受控选项须一致；`lake build --wfail` 构建默认目标和源码发现的全部模块。 |
| 3 源码层 | 可信目录 `Chan`、`ChanChallenge`、`ChanDyn`、`ChanTest`（`ChanExplore` 同规则）里的命令、声明、修饰符、属性、派生目标类、选项、导入，以及**每个语法节点的种类与承担精化的精化器**全部走白名单，名单外即红。名单外的语法在精化之前就被拒。 |
| 3 环境层 | 公理与公理闭包查全部常量，闭包只接受 `propext`、`Classical.choice`、`Quot.sound`。`unsafe`、`partial`、`implemented_by`、`extern`、`meta` 查全部常量；`extern`、`meta` 没有豁免，其余只有下文三类能复核的生成项豁免。 |
| 6a 声明锁 | Defs、Hypotheses、Audit/Literal、ChanChallenge 按环境中的模块归属枚举，含私有声明。`FM-lock-v3` 以序号表达绑定变量和宇宙参数，编码声明类别、可约性、类型与非定理的定义体；v3 比 v2 多编码 `let` 的 `nondep` 位（`have` 与 `let` 不再同码），旧锁文件须按 v3 重算。锁集多、少、变均红。 |
| 6b 路径权限 | 分别核对提交、暂存区、工作树与**整个仓库**的未跟踪文件；不让差异相消。分支名须有 `前缀/` 之后的非空后缀；改动里不得有符号链接。声明锁及非空签注由 `decl/` 维护；`infra/` 只能初始化空签注。分离 HEAD 用 `GITHUB_HEAD_REF`，缺失退 2。 |
| 15 模块边界 | 首条命令为 `module`；导入不能越过目录的直接或传递边界，不能整库导入 Mathlib。只有审计工具可 `import all`。Defs 须写 `@[expose] public section`，公开可计算定义也须真的有公开定义体；派生处理器给 `Repr`、`Hashable` 辅助函数贴的 `@[no_expose]` 按源码层的派生证书放行。 |

单跑一道门（`--gate`）时入口会提示：单门结论只覆盖该门的承诺，合入以全部阻断门为准。门 3 单跑也能
判出占位证明（见下），与全部一起跑的结论一致。

### 门 3 源码层：四道检查

`fm_audit source` 用加载本轮依赖后的 Lean 前端逐条解析、检查、再精化命令。

1. **精化前，命令层**：命令语法树整树过命令、声明、修饰符、属性、派生目标类、选项、配置项的名单。
2. **精化前，语法种类与精化器**（`Perimeter.kindIssues`）：每个节点的种类须在
   `syntax-kinds.tsv` 里，各处理表（项、战术、命令、宏、`do` 元素、`grind` 战术、归纳精化、`try?`）
   为该种类登记的**每个**处理器须在 `elaborators.tsv` 里。`include_str`、项级 `unsafe`、`by_elab`、
   `eval%`、`trace`、`success_if_fail_with_msg`、`sudo set_option`、`#eval` 等都在这一步被拒，
   被审代码一行不跑。
3. **精化中**（`Perimeter.sealTables`）：每条命令精化前，把项、战术、命令、`do` 元素四个用户类别里
   名单外的处理器登记为已擦除（`KeyedDeclsAttribute.ExtensionState.erased`）；宏展开出名单外的语法
   时，Lean 找不到处理器，不会调用它。`open` 会重新激活作用域内的处理器，所以每条命令前都重做。
   `prio`、`prec`、`attr` 类别的宏由库在求属性参数时内部展开（不承载用户项），不擦除。
4. **精化后**（`Perimeter.infoIssues` 与命令层复核）：信息树里每个 `TermInfo`、`TacticInfo`、命令类
   `CommandInfo` 记录的精化器名须在名单里（宏即宏声明名）；记录为匿名的节点按语法种类兜底，种类同样
   走名单；每个宏展开的产物逐节点再过第 2 道。另核对：`OptionInfo` 的选项、本命令新增常量里的
   `partial`（只许派生证书里的辅助函数与结构／良基递归的编译影子）、Lean 打了 `hasSorry` 标签的
   「声明使用了 sorry」警告（不看占位证明的名字怎么写，`_root_.sorryAx`、`export` 别名都在内），以及
   命令前后受控选项是否一致。

名单（Lean 4.36.0 本机枚举；省去前缀 `Lean.Parser.Command.`）：

- **命令**：`moduleDoc`、`namespace`、`section`、`end`、`open`、`variable`、`universe`、`include`、
  `omit`、`in`、`declaration`、`mutual`、`set_option`、`check`、`attribute`、`deriving`（独立的
  `deriving instance`）；`Lean.guardMsgsCmd` 仅 `Chan/Final`。生成命令另允许 `cmd in` 展开出的内部
  命令 `InternalSyntax.end_local_scope`。`in`、`mutual`、`#guard_msgs` 内的命令照样按命令验。
  不放行 Mathlib 的 `lemma`，一律写 `theorem`。`#eval` 已不再放行（含 `ChanExplore`）：它在精化期编译并
  运行用户项。
- **`#guard_msgs`**：只许不带规格的精确匹配写法（`substring`、`drop`、`whitespace`、`ordering`、
  按严重度过滤都不许），内嵌命令只许 `#check` 与 `#print axioms`。`#print axioms` 只许出现在这里。
- **声明**：`definition`、`theorem`、`abbrev`、`opaque`、`example`、`inductive`、`classInductive`、
  `structure`、`instance`。
- **修饰符**：`meta`、`unsafe`、`partial` 必红；`meta section` 必红；其余（可见性、`protected`、
  `noncomputable`、`nonrec`）放行。
- **属性**：按 Lean `elabAttr` 的取名规则比对（先展开属性宏）。白名单为 `simp`、`ext`、`instance`、
  `reducible`、`irreducible`、`inline`、`specialize`、`expose`、`no_expose`、`grind`、`norm_cast`、
  `push_cast`、`refl`、`symm`、`trans`、`gcongrAttr`、`mono`、`congr`、`elab_as_elim`、
  `induction_eliminator`、`cases_eliminator`、`deprecated`、`simps`、`method_specs`。注册宏、精化器、
  解析器、初始化器、派生处理器以及改写编译产物的属性都不在名单里。
- **派生目标类**（按解析后的全名）：`DecidableEq`、`BEq`、`ReflBEq`、`LawfulBEq`、`Hashable`、`Ord`、
  `Repr`、`Inhabited`、`Nonempty`。
- **选项**：受控选项归门 2；其余只许 `maxRecDepth`、`maxHeartbeats`、`synthInstance.maxHeartbeats`、
  `synthInstance.maxSize`、`match.ignoreUnusedAlts` 与 `pp.*`。库宏展开时设置的选项同样受约束，例如
  `rfl'` 展开出 `smartUnfolding`，判红（`decreasing_by` 里的也能看到）。
- **配置项**（`Perimeter.configIssues`）：战术配置在精化期求值，部分配置类型（Mathlib 的
  `LinarithConfig`）用 `Meta.evalExpr'` 编译运行。只许 `+名`、`-名` 与字面量取值；`native` 与旧式
  `(config := …)` 不许。
- **导入**：只许可信目录模块与 `Init`、`Std`、`Mathlib`、`Batteries`；`Lean`、`Lake`、`Qq`、`Aesop`
  等判红（红后仍继续精化以便门 2 读数）；`meta import`、`import all`、`prelude`、非 `module` 文件、
  `ChanExplore`／`verification` 等其他来源判红并立即停止。注意 `Batteries.Lean.*`、`Mathlib.Lean.*`
  等白名单模块会公开再导出 `Lean` 的接口：「不导入 `Lean`」挡不住 `Lean` 的名字进入作用域，真正的
  边界是第 2–4 道的精化器白名单与模块制的 `meta` 相位检查。
- **其余禁用项**（整树）：`sorry`、`admit`、`native_decide`、`run_tac`、`run_meta`、`sorryAx` 标识符。

#### 精化器白名单怎么来的

`elaborators.tsv`（286 条：允许 278、拒收 8（语料候选里拒收 1 条 `#eval`，其余 7 条是语料外、第四轮指出的求值入口，列出只为留依据））与 `syntax-kinds.tsv`（309 条：允许 308、拒收 1（`#eval` 的种类））由
`inventory.py` 与 `make_lists.py` 生成，可重跑：

- 语料：`must_green/` 全部夹具、`report_cases/clean/` 全部夹具、`Chan/` 现有源码（含第四轮的 W3
  代表性证明文件 `must_green/g3/r4-w2-w3-proofs`）。`fm_audit inventory` 逐文件精化，收集表层与信息树
  里的语法种类、信息树记录的精化器，并给四张用户类别处理表的每个处理器套一层记录，收集**实际被调用过**
  的处理器（信息树看不到库内部的精化，例如派生处理器证明里的 `by injection`）。
- 判断：每个候选取钉选版本里的声明位置（文件:行），在私有分片的环境里算静态调用闭包，看能否到达精化期
  求值（`evalTerm`、`evalExpr`、`evalConst`…）、宿主机读写（`IO.FS.*`、`IO.Process.*`、
  `unsafeBaseIO`）与白名单外公理（`Lean.ofReduceBool` 等）。闭包干净的判「允许」；命中的按最短调用链
  逐条归类（格式化器、文档渲染器、simproc 按名求值、剖析计时、只在已被挡住的配置子句里求值），归不了类
  的判「拒收」。结论与依据逐行写在名单里。
- 名单外的精化器一律红，错误信息给出精化器名、处理表与语法种类，评审后按同一流程补入。
- 直接改 `Core.Context.options` 而不留信息树记录的精化器（如 `sudo set_option`），静态闭包识别不出；
  这类只能靠「名单外即红」挡住——它们不在语料里，也就不在名单里。补入新精化器时须人工读源码确认这一点。

#### 选项设置的判定

- 表层：凡首个子节点是 `set_option` 关键字的语法节点都按选项设置处理（命令、项、战术、`grind =>` 内）。
- 精化后：四个 `set_option` 精化器都调用 `Lean.Elab.elabSetOption`，它为每次设置推一个 `OptionInfo`；
  信息树里的全部 `OptionInfo` 都查，宏展开出的选项也在其中。
- 不经这两条路改选项的写法（如 `sudo set_option`），由精化器白名单挡住。
- 兜底：每条命令精化前后比较作用域里生效的受控选项，不一致即门 2 红。**这条只看得见命令级、持续到命令
  结束的改动**；项内或战术内局部改了又在返回前恢复的选项（`withOptions` 一类）在命令前后看不出差别，
  不能声称覆盖，只能靠上面三条。

#### 审计期不执行被审代码

- 精化前先不运行任何初始化器读入导入闭包，按 `.olean` 的真实路径分出被审代码，登记进
  `interpretedModInits`，随后的 `processHeader` 不运行它们的 `[init]`；任一被审模块含 `meta` 声明即拒绝精化。
- 用户写出的会在精化期求值用户项的语法（`include_str`、`by_elab`、`eval%`、`#eval` 等），在第 2 道
  就被拒，不进入精化。第四轮 `P0`、`P1a`、`P1d`、`P3a`、`P3b2`、`P3d`、`P7d` 的夹具同时以「只审该
  文件」方式跑，核对标记文件没有被写下。
- `fm_audit selfcheck` 用一段固定样例核对精化后复核确实看到宏生成的受控选项、`implemented_by` 属性、
  非白名单命令与库宏展开出的选项。

### 门 3 环境层的生成来源判据

常量带 `unsafe`、`partial`、`implemented_by` 时，只有能机械复核为下列三类之一才豁免；`extern`、`meta`
不在任何豁免之内（先于豁免判定）。判据在 `Audit.lean`：

1. **`ctorIdx` 与其运行期实现**：照 `Lean.Meta.Constructions.CtorIdx.mkCtorIdx`／`mkCtorIdxImpl` 重算
   归纳类型 `T` 本应生成的 `T.ctorIdx` 类型、定义体与 `T.ctorIdx._impl` 的值，两者须与环境里的逐字相同
   （`==`），名字、安全性、宇宙参数与 `implemented_by` 指向一致；命题族、单构造子类型、运行期内建类型
   生成器本就不生成运行期实现，不豁免。手写声明要命中，必须与 Lean 生成的那份逐字相同。
2. **结构递归或良基递归的编译影子**：`partial` 定义经 `Compiler.isUnsafeRecName?` 指向源定义，源定义
   是同模块、内核检查过的安全 `def`，且 Lean 的 `recExt` 登记它为结构或良基递归，类型逐字相同。
   手写 `partial def f` 的源定义是 `opaque`，不满足。
3. **派生处理器的辅助函数**：源定义是同模块的 `opaque`，且在**本轮源码层的派生证书**里。源码层逐命令
   观察新增常量，声明范围落在某个派生目标类语法节点（`derivingClass`）之内的才进证书（派生处理器在
   `withRef` 该节点下精化）；`run_gates.py` 把证书交给门 3 环境层与门 15。环境层单独运行
   （`fm_audit 3` 直调）时没有证书，派生的 `partial` 辅助函数一律红——这是取消「按名字与形状重算」后
   的代价，完整门 3 不受影响。第四轮 R4-B1 的普通递归类型 `deriving Ord` 由此转绿。

### 门 2：`lakefile.toml` 白名单

依据 Lake 4.36.0 `Lake/Load/Toml.lean` 的解码器（`PackageConfig`、`LeanLibConfig`、`LeanExeConfig`
等由 `genDecodeToml` 生成，接受数十个键，含 `moreLeanArgs`、`weakLeanArgs`、`moreServerOptions`、
`moreLeancArgs`、`plugins`、`dynlibs` 等）。名单只留：

- 包级：`name`、`version`、`defaultTargets`、`leanOptions`、`require`、`lean_lib`、`lean_exe`；
  包级 `leanOptions` 须恰为 `autoImplicit=false`、`relaxedAutoImplicit=false`、
  `linter.unusedVariables=true` 三项；
- `require`：`name`、`git`、`rev`、`scope`；`lean_lib`：`name`、`globs`、`roots`；
  `lean_exe`：`name`、`root`、`supportInterpreter`；
- 不许 `lakefile.lean`（Lake 会优先读它）。

名单外的键或取值判 `LAKEFILE_KEY`；原有的 `LEAN_OPTION_OVERRIDE`、`LEAN_OPTION` 检查保留在前。

### 这套门禁防什么、不防什么

1. **伪定理被接受**（健全性）：最终由门 4 的独立内核重放与公理闭包兜住。本票的源码层与环境层检查是前置
   防线，作用是让禁用构造在合入前就被看见，不是健全性的最后一道。
2. **审计与构建期间被审代码碰宿主机**：本票尽力在精化前拒绝一切会在精化期求值用户项的语法，并隔离本地
   初始化器与 `meta` 代码；但 `lake build` 仍会编译被审代码，库精化器的实现细节也可能有未发现的路径。
   审计与构建应当在无网络、无凭据、只读挂载的沙箱里运行——这是 CI 票 #2315 的要求，本票依赖它。
3. **陈述含义**：局部实例改写记号含义（如 `local instance (priority := high) : LT Nat := ⟨fun _ _ => True⟩`
   下的 `10 < 1`）、`attribute [-simp]` 之类不破坏健全性，阻断门不管；由声明锁（门 6a 编码已解析的常量
   全名）、声明评审 PR 的非作者独审与 `lake comparator` 负责。

### 阻断门的已知不覆盖与现状

- 信息树里 Lean 未写回赋值表的空洞无从复核（`decreasing_by` 的子树经 `substituteLazy` 已能展开）；其中
  手写的部分已过精化前的两道检查。
- 项内局部改选项又恢复的情形，命令前后比较看不见（见上）。
- `Chan/Hypotheses/` 的暴露态：门 15 只要求 `Chan/Defs/` 写 `@[expose] public section`；Hypotheses 去掉
  `@[expose]` 时门 6a（读私有环境，不编码暴露态）与门 15 都不红。下游若依赖其定义展开，构建会失败；
  是否另锁暴露态留待后续票定。

## 二、审阅报告（不阻断）

`--report` 对可信目录逐常量输出 S、7a、7b、8a、8b、9、10 的读数。门 7a、7b、8a、8b、9 的「节点」是
Thm、Proofs、Exec、ChanChallenge 中有源码声明范围、类型为命题的定理、定义或 opaque（不含结构投影）；
门 3 已封住本地元编程，没有声明范围的常量只能是 Lean 生成的辅助项（方程引理、`_proof_i`、`match`
辅助等），报告不把它们当节点。阻断门不依赖声明范围。标准输出是 JSON
（`schema: fm-review-v1`），标准错误是 Markdown 表；给 `--report-dir` 时另写 `report.json`、
`report.md`。人读表只列至少有一条非 `no_finding` 读数的声明，全部读数仍在 JSON 里。每条读数有：

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
  `symlinks.txt`（`链接 目标` 每行一条）在夹具里建符号链接；`root-files.txt` 列出门 6b 夹具提交后在仓根
  另建的未跟踪文件；`lean-version.txt`、`branch.txt`、`head.txt` 同前。
- **报告回归**：`report_cases/{finding,clean,unknown,known_limits}/g<门>/` 跑 `--report`，断言该门读数：
  `finding` 的命中代码集合等于 `expect.txt`（可配 `expect_decls.txt`、`expect_certified.txt`）；`clean`
  与 `known_limits` 无命中也无 `unknown`（后者须附 `README.md` 写明为何漏、由谁收口）；`unknown`
  至少一条 `unknown`。报告退出码须为 0；夹具本身不能构建时用 `report-exit.txt` 写 2，只断言退出码。

macOS 上夹具与子进程临时文件放在 `/Volumes/AgentStorage/fm/tmp/`；Linux 上用 `TMPDIR`。根分区可用
低于 6 GiB 时停止派发。门 3 与报告装载 `.olean` 私有分片，并先读 ChanTest 的私有探针证明体；
可见性不足返回 2。

M-4 的本机实测：定义只写 `public section` 时，跨模块 `decide` 卡在不可展开的 `probeFlag`；改成
`@[expose] public section` 后，同一计算通过。对应夹具是 [no-expose](must_red/g15/no-expose) 和
[expose](must_green/g15/expose)。
