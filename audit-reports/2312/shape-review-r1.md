# #2312 第四片（源码形状门）非作者独立审阅 r1

| 项 | 值 |
|---|---|
| 被审提交 | `1acb400d631e6d4154a3ef4ebb779f7a781e2425`（分支 `origin/infra/2312-g-shape`，head 已核对相符） |
| 相对过审骨架 | `98c69ff109..1acb400d63` |
| 实际运行的模型与档位 | **Claude Opus 5（`claude-opus-5`），effort `high`**。会话中途由 Claude Fable 5.2 交接到本模型；前半段的夹具构造与跑数在 Fable 5.2 上做，发现的复核与本报告的结论在 Opus 5 上做。两段用的是同一套脚本与同一个被审提交 |
| 工具版本 | Lean 4.36.0（`611c117bfaf7b7ae1cfcf246ce6fba31e8f509e9`）、bubblewrap 0.11.1、Python 3.14.4、git 2.53.0 |
| 审阅方式 | 只读。没有改被审分支上的任何文件，没有评论或改动任何 issue，没有开 PR |
| 工作目录 | `/home/workspace/fm/tmp/review-g1/`；夹具与脚本随本报告推到 `audit-reports/2312/shape-r1-fixtures/` |
| 根分区 | 开工 249 GiB 可用，收工 248 GiB 可用，全程未触 5 GiB 红线 |

读过：设计备忘 `aedff2e010` 第一节前提二三、第二节责任表、3.4／3.5／3.6、第四节、第五节第 4 条与末段、第六节第二三处；#2312 评论 7175991382、7164343103；`runner/README.md` 全文；`runner/fixtures.tsv` 全部 258 行；骨架三轮独审 `origin/evidence/2312-skeleton-review-r3` @ `e56c2ca98c`；R5-B4（`FM-04-review-r5.md` 的 B4 与 `r5-fixtures/`）。

自己写了 537 个生成式变体（禁用清单 185、五张白名单与 `set_option`／`#guard_msgs`／`Chan/Defs` 311、配置项与未点名写法 41）加 14 组手写流水线夹具，另把仓内 54 个 must_green 夹具、`fixtures.tsv` 归「本片判红」的全部 74 行、R5-B4 的三份汇总各跑了一遍，并独立重跑了作者自测里与本片直接相关的 13 例。

---

## 甲、形状门本体（诚实作者断言）

### 阻断缺陷

#### 甲-1 点名禁用的「旧式 `(config := …)`」以明文出现却没判红

- **类别**：阻断条件 1（点名的写法以明文形式出现却没判红）。
- **影响面**：**一整类语法，不是冷门变体**。Lean 4.36 核心 `Init/Tactics.lean:34` 定义的旧式配置
  `syntax config := atomic(" (" &"config") " := " withoutPosition(term) ")"`（语法种类
  `Lean.Parser.Tactic.config`）完全不被检查，连同 Aesop 自己定义的同形写法
  `Aesop.Frontend.Parser.«tactic_clause(Config:=_)»` 与 `«tactic_clause(Simp_config:=_)»`。钉选库里用这条
  parser 的战术都能明文写出来，只要 `import Mathlib.Tactic.Common`：`aesop (config := …)`、
  `aesop (simp_config := …)`、`plausible (config := …)`。
- **根因**（`auditor/Auditor/Shape.lean:141-149`）：检查只匹配语法种类**末段**为 `posConfigItem`、
  `negConfigItem`、`valConfigItem` 的节点。新式 `optConfig` 把 `(config := x)` 解析成 `valConfigItem`，键是
  **标识符** `config`，所以 `simp (config := {})`、`decide (config := {})` 这些被抓到（实测 39 例全红）；
  旧式 `config` 种类里 `config` 是**记号**（atom）而不是标识符，整条节点不在 `match` 里。
  语法种类实测（`shape-r1-fixtures/tools/Kinds.lean`）：

  ```
  plausible: kind=Lean.Parser.Tactic.config nargs=5 arg0kind=«(» arg0atom=true arg1="config"
  aesop:     kind=Aesop.Frontend.Parser.«tactic_clause(Config:=_)» … arg1="config"
  aesopsimp: kind=Aesop.Frontend.Parser.«tactic_clause(Simp_config:=_)» … arg1="simp_config"
  simp:      kind=Lean.Parser.Tactic.valConfigItem … arg1=`config      ← 标识符，被抓到
  decide:    kind=Lean.Parser.Tactic.valConfigItem … arg1=`config      ← 标识符，被抓到
  ```

- **逐字命令与实际输出**：

  ```sh
  source scripts/fm_env.sh
  flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh \
    python3 -I audit-reports/2312/shape-r1-fixtures/tools/pipe.py \
      audit-reports/2312/shape-r1-fixtures/fx/a1-aesop-green
  ```

  夹具 `fx/a1-aesop-green/Chan/Thm/A.lean`：

  ```lean
  module

  public import Mathlib.Tactic.Common

  public section

  theorem probe : True := by
    aesop (config := { maxRuleApplications := 200, warnOnNonterminal := false })
  ```

  实际输出：

  ```
  rc 0 precheck:GREEN fetch:GREEN auditor:GREEN headers:GREEN shape:GREEN build:GREEN env:GREEN
      FM RESULT GREEN 七步全绿
  ```

  `fx/a1-plausible`（`plausible (config := { numInst := 5 })`）：第 5 步同样零命中
  （整次运行在第 6 步因 plausible 自身判红）。

- **它不只是记号问题：这条正是能求值任意被审项的那一条。** `fx/a1-aesop-eval` 把取值写成
  `{ maxRuleApplications := (dbgTrace "FM-LEGACY-CONFIG-RAN" fun _ => 200) }`，**七步全绿（rc=0）**，
  且构建日志里出现 `FM LOG build info: Chan/Thm/A.lean:9:0: FM-LEGACY-CONFIG-RAN` ——
  旧式 config 由 `declare_config_elab` 经 `evalExpr` 编译并运行被审文件给的项。
  反向对照 `fx/e-eval5`：**被放行的新式配置项没有这个能力**，核心用受限求值器，
  非字面量直接报 `Could not evaluate the expression: dbgTrace "FM-NEWCFG-RAN" fun x => 1000`（第 6 步红）。
  也就是说，被查的那一半没有求值能力，有求值能力的那一半没被查。
- **最小修法**：在 `inspect` 里按记号查，与同文件 `setting` 对 `set_option` 的做法一致——节点首子是记号
  `(`、次子是记号 `config` 或 `simp_config` 时报 `SHAPE_FORBIDDEN`（三种种类的 `stx[0]` 都是 atom `"("`、
  `stx[1]` 都是 atom，注意 `trimAscii`）。同时建议 README 的禁用清单行把 `simp_config` 一并点名，
  并把「旧式 `(config := …)`」改写成「旧式 `(config := …)`／`(simp_config := …)` 写法（语法种类
  `Lean.Parser.Tactic.config` 与库里的同形 clause）」，以免下一轮又只对上半句。

### 条件项

无。甲只有上面一条缺陷；修掉并补一个 `aesop (config := …)` 必红夹具（建议同时补 `plausible (config := …)`
与 `aesop (simp_config := …)`）即可。

### 核实正确的部分（甲）

**点名写法与白名单（阻断条件 1）**：537 个变体里只有甲-1 的 4 例该红没红，没有第二处漏。
下表的「实测」两列是逐文件量出来的（`shape-r1-fixtures/expect/*.tsv` 是期望，
`tools/shp.py` 的输出是实测），不是推断：

| 规则 | 期望红变体 | 实测红 | 期望绿对照 | 实测零命中 |
|---|---|---|---|---|
| 禁用清单：`sorry`／`admit` 各语法位置（项、战术、`by`／`exact`／`refine`、`have`／`let`／`where`／`calc`／`conv`、`match`／`cases`／`induction` 分支、`rcases`／`obtain`／`suffices`／`by_cases`、bullet／`case`／`next`、`all_goals`／`any_goals`／`repeat`／`try`／`first`／`<;>`、`instance`、`structure` 字段默认值与字段证明、结构实例、`termination_by`／`decreasing_by`、`mutual`、`namespace`／`section` 嵌套、`open … in`／`set_option … in`／`omit … in`、`example`、`#check`、`variable` 默认值、binder 默认值、autoParam、字符串插值、`do`、类型位置、`inductive` 字段、`abbrev`／`opaque`、`simp`／`rw`／`linarith`／`use` 参数、注释与文档注释夹在中间、嵌套块注释、`private`／`protected`／`noncomputable`／`@[simp]` 修饰） | 90 | **90** | 0 | — |
| 禁用清单：`sorryAx`（`_root_.`、`@`、`«»`、`.symm` 投影、`by exact`、`by apply`） | 7 | **7** | 0 | — |
| 禁用清单：`native_decide` 与 `decide` 的 native 配置（`exact`／`have`／`where`／`instance`／`first`／`<;>` 位置；`+native`／`-native`／`+kernel +native`／`(native := …)`／`(config := { native := true })`／`«native»`／换行与注释变体） | 19 | **19** | 1 | 1 |
| **禁用清单：旧式 `(config := …)`** | 43 | **39** | 0 | — |
| 禁用清单：求值入口与求值命令（`include_str`、`eval%`、`by_elab`、`run_tac`／`run_cmd`／`run_meta`／`run_elab`、`sudo set_option`、项级 `unsafe`、`trace`、`success_if_fail_with_msg`、`#eval`／`#eval!`、`#exit`，各含命令位置、`in` 两侧、`mutual` 内、`namespace` 内变体） | 48 | **47** | 1 | 1 |
| 命令白名单（`macro`／`macro_rules`／`syntax`／`declare_syntax_cat`／`notation`／`notation3`／`infix*`／`prefix`／`postfix`／`elab`／`elab_rules`／`initialize`／`builtin_initialize`／`#print`／`#reduce`／`#synth`／`#guard`／`#guard_expr`／`#check_failure`／`export`／`lemma`／`alias`／`simproc`／`simproc_decl`／`register_simp_attr`／`unif_hint`／`binder_predicate`／`class abbrev`／`seal`／`unseal`／`gen_injective_theorems%`／`grind_pattern`／`recommended_spelling`／`declare_simp_like_tactic`／`irreducible_def`／`proof_wanted`／`suppress_compilation`／`count_heartbeats`／文件头之后的 `import`；含 `local`／`scoped`／文档注释／`open … in`／`set_option … in`／`mutual` 内／嵌套命名空间变体） | 64 | **64** | 1 | 1 |
| 声明白名单（`axiom` 的各修饰符与位置变体、`coinductive`） | 17 | **17** | 0 | — |
| 修饰符白名单（`unsafe`、`partial`、`meta`、`meta section` 的各写法，含 `mutual` 内、`where`、结构体字段、构造子、`@[expose] public section` 内、换行与注释夹在中间） | 47 | **47** | 2 | 2 |
| 属性白名单（`implemented_by` 11 种写法含 `attribute [...]`、`attribute [...] … in`、`let rec`／`where`／`mutual` 内、`«»`；`extern`、`export`、`init`、`builtin_init`、`csimp`、`macro`／`local macro`／`scoped macro`、`term_elab`、`tactic`、`builtin_tactic`、`command_elab`、`term_parser`、`command_parser`、`builtin_derive_handler`、`app_unexpander`、`simproc`、`norm_num`、`positivity`、`aesop`、`to_additive`、`nolint`、`inherit_doc`、`default_instance`、`class`、`match_pattern`、`coe`、`noinline`、`macro_inline`、`never_extract`、`unbox`、`computed_field`、字段与构造子上的属性；`attribute [-x]` 三种） | 52 | **52** | 3 | 3 |
| 派生目标类白名单（行内、`deriving instance`、混排、换行与注释、`mutual` 内、`open … in` 后的短名、`def` 上的 `deriving`、`Std.*`、`Fintype`、括号写法） | 16 | **16** | 1 | 1 |
| `#guard_msgs` 三条限制与 `#print axioms`（带规格 9 种、内嵌非 `#check`／`#print axioms` 10 种、`Chan/Final` 之外含 `Chan/FinalX` 前缀仿冒、裸 `#print axioms` 4 种） | 30 | **30** | 1 | 1 |
| `set_option` 各语法位置与选项名单（命令、`… in` 嵌套、项层 11 种位置、战术层 8 种、`grind =>`、`«»` 书名号、换行与块注释夹在中间；受控 `autoImplicit`／`relaxedAutoImplicit`／`linter.*`，名单外 20 个选项含 `debug.skipKernelTC`、`compiler.checkMeta`、`warningAsError`、`smartUnfolding`、`hygiene`） | 64 | **64** | 1 | 1 |
| `Chan/Defs` 的 `@[expose] public section`（缺、只 `public`、只 `@[expose]`、普通 `section`、只 `namespace`、子目录、注释里写） | 7 | **7** | 5 | 5 |
| 未点名写法探针（期望绿，只记录实际行为：`stop`、`exact?`、裸 `plausible`、`bv_decide`、`decide +kernel`、`lcProof`、`dbgTrace`、`panic!`、`unreachable!`、`trace_state`、`says`、`unsafeCast`、`Lean.ofReduceBool`／`reduceBool`／`trustCompiler` 等） | 0 | — | 17 | 17 |

期望红却实测零命中的共 5 例：4 例是甲-1（`aesop (config := …)`、`aesop (simp_config := …)`、
`plausible (config := …)` 两种），第 5 例 `EvalPctNoImport` 是我自己的期望写错了——不导入
`Mathlib.Tactic.Eval` 时 `eval%` 不是记号，`eval% 1 + 1` 按 `eval % 1 + 1`（`HMod`）解析，
根本没有 `eval%` 可查，真实构建会因未知标识符 `eval` 失败，不是门禁的问题。

六处我自己写错的夹具（期望写成红而实际是 `SHAPE_PARSE`，或我多写了一个 `SHAPE_PARSE`）逐个用真实
`lean` 复核过：**真实编译器在同一行同一列报同一句错**，不是形状门的问题。例如
`where aux : T := by` 换行后缩进不足，形状门报 `L7 SHAPE_PARSE unexpected identifier; expected command`，
真实 `lean` 报 `W.lean:7:2: error: unexpected identifier; expected command`（`fx/w-where`）；
`def 笔宽 …` 这种裸 CJK 标识符两边都报 `expected token`；文档注释放在 `mutual` 之前两边都报
`unexpected token 'mutual'`。

**必绿语料（阻断条件 2）**：没有发现任何第 5 步误拒。

- 仓内 **54 个 must_green 夹具**（`g2` 9、`g3` 30、`g15` 7、`g6a` 6、`known-not-covered` 2）第 5 步**全部零命中**，
  包括两个「已知不防」的 `rfl'` 夹具（按设计为绿）。
- **R5-B4 的 41 条命令**（三份汇总文件）第 5 步**零命中**，与作者自述一致。作者对「三份在第 6 步构建红、
  原因都在夹具自身」的解释我抽查了 `-everyday-tactics`：第 5 步零命中，构建失败点确实在夹具自身
  （`tSuffices` 的 `simpa` 已关目标后又跟一个 `rfl`），不是门禁拒的。
- 我自己写的日常语料 `fx/g-green`（5 个文件 65 条命令，分 3 组库导入）：第 5 步零命中、**第 6 步构建绿**。
  覆盖 `structure`（含字段文档、默认值、字段证明）、`inductive`、`class`、`instance`（`where` 与匿名构造子）、
  `deriving` 七个白名单类、良基递归（`termination_by`／`decreasing_by`）、互递归 `mutual`、`@[simp]` 定理、
  `by_cases`／`rcases`／`obtain`／`conv`／`calc`／`funext`／`use`／`refine`／`induction`／`match`、
  `simp` 带配置与引理列表、`omega`／`linarith`／`nlinarith`／`positivity`／`norm_num`／`ring`／`decide`、
  `Finset` 与 `List` 记号、`open scoped`／`open … in`、`variable`／`universe`、模块注释与文档注释、
  `«»` 引号标识符、`set_option` 白名单选项的命令与 `… in` 位置、`Chan/Final` 的 `#guard_msgs`。

**「不防什么」与「谁接」的如实性（阻断条件 3）**：逐行核对下来**写得如实**，另见下面「清单外求值入口」一节。
两处单独验过：

- `SHAPE_EXPOSE` 行只查「文件里存在一条 `@[expose] public section`」，空的
  `@[expose] public section` + `end` 再在节外写 `public def` 能过第 5 步；README 写的「谁接」成立——
  第 7 步门 15 报 `EXPOSE_SECTION 公开定义未暴露定义体`（`fx/x-expose` 实测）。
- `set_option` 行的「不防：库宏展开时设置的选项（`rfl'` 展开出 `smartUnfolding`）」与接手对照
  `must_red/known-not-covered/rfl-prime-false` 第 6 步构建判红——两个「已知不防」夹具第 5 步零命中、
  接手对照第 6 步 `BUILD_WFAIL`，与表里写的一致（`redcheck.py` 与 sweep 实测）。
- README 对作者没做成的那一项写的是「本片没有构造出……」「没有找到第二个」「本票不实测」，
  没有把「没实测」写成「接住了」。我的独立调查支持这个写法，并把其中一条收紧成了结构性结论（见下）。

**只解析与真实构建的理解差异（阻断条件 4）**：没有发现方向是漏的差异。

- **解析失败一律红、且是整个文件红**：`walk` 在首条 error 处 push `SHAPE_PARSE` 后 `break`，文件红、
  整次运行红，不存在「跳过一段继续、只报别的」。实测 `#exit` 之后写 `axiom bad : False` 仍报
  `SHAPE_COMMAND`＋`SHAPE_FORBIDDEN`（红）。
- **终止命令不能用来截断扫描**：`Parser.isTerminalCommand`（`Lean/Parser/Module.lean:119-120`）只有
  `Command.exit`、`Command.import`、`Command.eoi` 三种，前两种都不在命令白名单里，必红。
  也就是说没有「白名单内的终止命令」可以用来让扫描提前停下而文件仍为绿。
- **作用域跟踪**：作者的 H2a／H2b／H2c 我独立重跑通过（阴性对照七步全绿且命令数逐文件相等；三个红例
  `SHAPE_PARSE`；同一红例跳过第 5 步时真实构建同样拒绝）。我另外测了 `namespace`／`section`／`end` 多层
  嵌套、`open … in`、`mutual`、`public section`、未闭合的节、`section` 内 `open` 再 `end`，没有新差异。
- **`shape-plan` 的分组与真实构建一致**，而且是用真实编译器两个方向都量过的：上游 `public import` 传下来时
  下游用得到那组记号（`fx/z-prop1` 七步全绿）；上游是非公开 `import` 时传不下来，形状门报
  `SHAPE_PARSE unknown tactic`，而跳过第 5 步让真实构建跑，编译器在**同一行同一列报同一句
  `unknown tactic`**（`fx/z-prop2`）。方向上也只能收紧不能放松：组里少一个库只会少一批记号，
  结果是解析失败（红）或解析结果不变，不会把禁用记号解析成别的东西——`sorry`、`admit`、`unsafe`
  这些记号来自恒被加载的 `Init`。
- **字符串与注释里的假命令、嵌套块注释、`«»` 标识符、文件头之后首条命令之前的内容**：
  `must_green/g3/comments`、`raw-comments`、`r2-a4c-guillemet` 零命中，我另加的嵌套块注释与
  `«»` 变体也按预期（注释里的 `sorry` 不报、真的 `sorry` 报）。

---

## 乙、对已过审代码的改动（沿用骨架的对抗口径）

### 阻断缺陷

无。

### 核实正确的部分（乙）

- **作者称一字未改的三处确实为空**：`git diff --stat 98c69ff109..1acb400d63 -- auditor/Auditor/EnvGates.lean
  auditor/Auditor/Headers.lean precheck/` 输出 0 行。
- **`Main.lean` 的改动就是作者列的 6 处**（导入、`certificate`、`derivedBy`、`--derived` 分支、
  子命令分派、一行文档注释），`gate3` 与 `generatedBy` 的判据本体没动，`certificate` 严格解码、
  格式不合即抛错（整次退 2）。
- **派生凭证写在哪、谁能写**：由 `run.py` 的父进程写进受信目录（`<工作目录>/trusted/derived.json`，模式 0644），
  第 7 步再核对一次 `inside(realpath, trusted_dir)`（否则 `CERTIFICATE` 退 2）。第 6 步**看不见受信目录**——
  我独立重跑作者的 S22 探针，读数是：第 5 步 `(['lo'], {LEAN_PATH,PATH,HOME,LANG,PWD,LEAN_SYSROOT,TMPDIR},
  可见={trusted}, 可写=∅)`、第 6 步 `(…, 可见=∅, 可写={lake})`、第 7 步与第 5 步相同。
  即第 5 步的挂载与环境和第 7 步**逐项相同、什么都写不进**，受信目录在第 6 步被 tmpfs 盖住。
  S7 也重跑通过（构建期的写入不落宿主机，工作区源码与配置逐字节未变）。
- **凭证能否被撑大或伪造**：凭证区间是**单个派生目标类标识符**的位置，实测一份真实凭证的区间形如
  `["Chan.Defs.Core", 28, 9, 28, 13]`（同一行 4 列）、`[…, 34, 9, 34, 20]`（11 列），
  手写声明的声明范围起点不可能落在某个 `deriving` 子句的标识符文本里面。
  更关键的是：要让手写声明走到第 7 步，得先过第 5 步，而 `partial`／`unsafe`／`meta` 修饰符在第 5 步必红
  （我测的 48 个修饰符变体全红，含 `mutual` 内、`where` 子句、结构体字段、构造子、
  `@[expose] public section` 内、换行与注释夹在中间）。作者的 D2 从另一侧确认：驱动脚本放行第 5 步后，
  手写的 `Spoof.loop._unsafe_rec` 仍是第 7 步 `ENV_PARTIAL`，豁免确实按位置比对。
  D1a／D1b 也重跑通过（合法派生全绿；同一提交凭证为空时 `ENV_PARTIAL`）。
  我自己的 `fx/g-green` 从正面验了一遍：递归类型 `Tree` 的 `deriving Repr, BEq` 生成的
  `instReprTree.repr._unsafe_rec`、`instBEqTree.beq._unsafe_rec` 与良基／结构递归的
  `count._unsafe_rec`、`even?._unsafe_rec`、`half._unsafe_rec` 全部正确豁免，一条 `ENV_PARTIAL` 都没有。
- **第 5 步的沙箱与输出解析和骨架其它步同样严格**：`run_auditor` 对第 5 步的两个子命令同样做
  「每行严格 JSON、结果行恰一条且在最后、判定与发现一致、退出码与判定一致」；
  S5f（`shape` 模块数加一 → `MODULE_COUNT`）、S5g（删一行文件行 → `AUDITOR_OUTPUT`）、
  S5h（`shape-plan` 插一行不存在的文件 → `AUDITOR_OUTPUT`）、S27c（第 5 步审计程序被信号杀死 → `SIGNAL`）
  四例我都重跑通过。
- **`expect` 参数没有削弱交叉核对**。新加的 `expect` 只把「这一组应审的模块数」从全量改成本组文件数，
  而**全集覆盖另有三道锁**：`planned != set(ctx.content)` 时退 2（分组行必须与内容文件一一对应，
  且每个路径只许出现一次：`row[1] not in planned`）；每组内 `sorted(file 行) != sorted(files)` 或
  发现落在组外文件上时退 2；全部组跑完后 `seen != set(ctx.content)` 时退 2。
  所以**没有文件能不属于任何组而不被发现**，也不能让运行脚本少跑一组。
- **`shape-plan` 的输出不是无条件可信，但它能被被审方影响的部分都收口了**：它读被审文件头来分组，
  被审方因此能影响自己落在哪一组；可这只能**减少**组里的库，结果是 `SHAPE_IMPORT`（钉选库里没有该模块）
  或 `SHAPE_PARSE`，两者都是红，不存在「解析失败之外的方式逃过检查」（上面条件 4 一节的两个方向实测）。
  运行脚本对分组行的形状另有严格校验（四元组、路径在内容集合内、模块与路径对应、库名非空且不以 `-` 开头、
  无 `\0`）。
- **「第 5 步不执行被审代码」成立**。作者的 H3a／H3b 重跑通过（带 `initialize`、`#eval`、宏定义、`run_cmd`
  的文件第 5 步红，标记不出现在任何日志、构建目录没建；跳过第 5 步时同一个 `#eval` 在第 6 步执行、
  标记出现在构建日志里）。被审产物不在第 5 步的搜索路径上：`step_shape` 的 `LEAN_PATH` 只有
  `<依赖目录>/<包名>/.lake/build/lib/lean`，被审 `.lake` 此时还不存在，也没有被加进去；
  被审模块的 `.olean` 因此不可能被加载（`shape` 只 `importModules` 那一组库模块加隐式 `Init`）。

### 条件项（乙）

1. **伪造产物这一前提**（不阻断，已明示）：`derivedBy` 比对的声明范围来自被审构建的产物
   （`findDeclarationRanges?` 读 `.olean`）。能伪造 `.olean` 内容的一方可以把手写常量的声明范围
   安排进某个 `deriving` 区间里，从而骗到第 3 类豁免。这正是备忘 3.6 第 1、4 条与 README
   「不防什么」第一条已经写明交给 #2315（`lake check`／`lake comparator` 内核重放）的范围，
   本片不承诺，我也没有把它算作缺陷。给 #2315 记一笔：凭证豁免的是 `partial` 标记，
   不是陈述，所以这条路的收益只在于掩盖一个 `partial`，比伪造定理本身弱。
2. **`ctx.certificate` 只由第 5 步设置**（非阻断建议）：`class Run` 是空类，`step_env` 直接读
   `ctx.certificate`。现在七步固定顺序下不会出问题，万一将来有路径跳过第 5 步，
   这里会抛 `AttributeError` 落进 `INTERNAL` 退 2（失败方向是安全的，但靠的是兜底而不是显式契约）。
   建议在 `Run` 里给个 `certificate = None` 的类属性，或在 `step_env` 开头显式断言。

---

## 丙、删除

### 阻断缺陷

无。

### 核实正确的部分（丙）

- **没有仍被引用的删除物**。对 `SourceGates`、`Perimeter`、`Inventory`、`run_gates`、`inventory.py`、
  `make_lists`、`pins.json`、`syntax-kinds`、`elaborators.tsv`、`verification/selftest.py`、
  `verification/Audit`、顶层 `EnvGates.lean`、`g6b`、`forbid-file`、`expect_detail`、`environment-only`、
  `source-only`、`modules.txt`、`host_secret_probe` 十九个名字全仓 grep：命中的全是
  (a) README／`fixtures.tsv` 里描述历史与出入的**叙述文字**，(b) 故意保留的 R5-B1 劫持夹具正文
  （`selftest-cases/r5-b1/`），(c) 无关命中（`rust/` 里的 `Inventory`、pstack 的 `expect_detail`）。
  `inventory.py`、`make_lists`、`pins.json`、`verification/selftest.py` 零引用。
  `garbage-signoffs.yaml` 仍被预检引用、仍在用。顶层 `verification/README.md` 在本片同一提交里重写过，
  没有留下指向已删入口的陈述。
- **`fixtures.tsv` 的归属表与实际一致**。任务只要求抽查 20 行，我把归「本片判红」的**全部 74 行**
  都跑了（`tools/redcheck.py`）：逐行比对「退出码 1 ／ 判红步骤 `shape` ／ 红码集合」，
  **0 行不符**。红码分布与 README 写的计数一致（`SHAPE_FORBIDDEN` 占多数，其次
  `SHAPE_OPTION_CONTROLLED`、`SHAPE_COMMAND`、`SHAPE_MODIFIER`、`SHAPE_ATTRIBUTE`、`SHAPE_GUARD_MSGS`、
  `SHAPE_OPTION`、`SHAPE_DERIVING`、`SHAPE_DECL`、`SHAPE_EXPOSE`）。
- **没有未列出的「旧必红现在端到端为绿」**。`fixtures.tsv` 里 `must_red/` 且期望退 0 的只有一行
  `must_red/g1/runtime-pin`，归属写的是「不再检查」并说明了去处（运行期 Lean 版本不符改为第 3 步
  `TOOLCHAIN` 环境故障退 2，自测不伪造 `lean` 故全绿）。另外 2 个 `rfl'` 夹具明确归「已知不防」
  并配了接手对照，4 个 `g6b` 类与 `runtime-pin` 归「不再检查」且逐行写了理由。
- **删掉的检查都有去处**：项与战术层封闭名单（R5-B4 误拒，备忘第四节决定删）、宏展开后再检查与
  `OptionInfo` 复核与命令前后受控选项一致与 `hasSorry` 标签（主控定稿与用户裁定的两处字面出入，
  评论 7175991382 已确认）、`lakefile` 逐键白名单与 `pins.json`（归预检）、门 6b 三层比对与工作树扫描
  （门禁只审提交，归预检）、报告各门（按用户裁定降为不阻断，`report_cases/` 保留）。
  README 的两张出入表把这些逐条写了，我没有发现「删了却没人接、也没在说明里列出」的检查。

---

## 清单外求值入口的调查

任务要求我独立判断作者自报没做成的那一项。结论：**找到了一条能过第 5 步并在构建期求值被审项的入口，
它就是甲-1；但宿主机读写这一后果我同样没有构造出来，而且现在能说清为什么——不是碰巧没找到，
是被三层结构性地堵住了。**

**(a) 有没有现成的库入口能过第 5 步、在第 6 步构建期运行被审文件给的代码**

有一条，备忘 3.5 没点到：**旧式 `(config := …)` 的配置求值**。`declare_config_elab` 把配置语法里的项
编译后运行（`evalExpr`），所以 `aesop (config := { maxRuleApplications := (dbgTrace "…" fun _ => 200) })`
在第 6 步真的执行了被审文件给的项，标记出现在构建日志，而整次运行**七步全绿**（`fx/a1-aesop-eval`）。
这同时就是甲-1 的阻断缺陷。被放行的新式配置项**没有**这个能力（`fx/e-eval5`：`Could not evaluate the
expression`），所以这条入口与「门禁按设计放行的东西」无关，纯粹是漏查。

备忘 3.5 点名要我试的几条，逐条核实：

- **Aesop 规则战术按名字对声明求值**（备忘附录 B 列为「未核实」）：**从被审源码根本触达不到**，
  这比作者写的「没构造出来」更强。规则体必须是 `TacticM`／`RuleTac` 这类元层类型，而 Lean 4.36 的模块制
  不许非 `meta` 的 `def` 访问 `meta` 导入的声明，构建期直接报
  `Invalid definition 'fmRule', may not access declaration 'Lean.Elab.Term.instMonadTermElabM' imported as meta;
  consider adding import Lean.Elab.Term.TermElabM`（`fx/e-eval4`，连只做纯计算的规则体都写不出来）。
  按编译器的建议补 `import Lean.CoreM` → **第 4 步 `IMPORT_PINNED` 判红**
  （`fx/e-eval3`：`FM RED headers IMPORT_PINNED formal_math/Chan/Thm/WithLean.lean:4 可信目录不得导入 Lean.CoreM`）。
  改成 `meta def` → **第 5 步 `SHAPE_MODIFIER` 判红**。三层互相堵住。
- **`plausible`**：裸 `plausible` 过第 5 步（它确实会 `evalExpr` 检验程序），但它对目标 `admitGoal`，
  落 `sorryAx`，**第 7 步 `ENV_SORRY` 接住**，这是设计内的。它的 `(config := …)` 属甲-1。
- **`decide +native` 之外的写法**：`(native := true)`、`(config := { native := true })`、`+native`、`-native`、
  `+kernel +native`、`«native»`、换行与注释变体共 10 种**全部判红**。
- **`simp` 的 simproc、`norm_num` 扩展**：注册它们的属性（`@[simproc]`、`@[norm_num]`、`@[positivity]`、
  `@[aesop]`、`@[to_additive]`、`@[builtin_derive_handler]`、`@[app_unexpander]` 等 30 余个）**全部
  `SHAPE_ATTRIBUTE` 判红**；`simproc`／`simproc_decl`／`register_simp_attr`／`declare_simp_like_tactic`
  等命令**全部 `SHAPE_COMMAND` 判红或解析失败**。被审文件因此注册不了自己的 simproc／扩展。
- **`#print` 之类命令是否在白名单里**：`#print`、`#reduce`、`#synth`、`#guard`、`#guard_expr`、
  `#check_failure`、`#eval`、`#eval!` **都不在**，全部判红；白名单里只有 `#check`，
  而 `#print axioms` 只许出现在 `Chan/Final` 的 `#guard_msgs` 内（三条限制 27 个变体全红）。
  `#check` 本身只做精化、不求值，我没有找到经它做副作用的写法。

**(b) 宿主机一侧**

我没有构造出能过第 5 步又做宿主机读写的入口，与作者自述一致；但可以把理由写成结构性的：
从被审源码到 `IO` 的通道只有这几条，全被堵住——

| 通道 | 状态 |
|---|---|
| 项级 `unsafe`、`unsafe def` | 第 5 步 `SHAPE_FORBIDDEN`／`SHAPE_MODIFIER` |
| `unsafeBaseIO`／`unsafeIO`／`unsafeEIO` | 它们是 `unsafe def`，从安全代码调用要先有 `unsafe`，同上判红 |
| `include_str`、`eval%`、`by_elab`、`run_tac`／`run_cmd`／`run_meta`／`run_elab`、`sudo` | 已点名，第 5 步判红（46 个变体全红） |
| 元层类型（`IO`／`CoreM`／`TacticM` 的 monad 实例） | 需要 `meta` 导入 → `meta def` 第 5 步红，或 `import Lean.*` 第 4 步红 |
| 旧式 config 求值（甲-1） | 取值是非元层类型的项，能力上界是**纯计算加 `dbgTrace`／`panic!` 往标准错误打字** |

也就是说甲-1 这条入口的后果**只到构建日志**，而「构建日志的内容」README 已经在「不防什么」里写明，
并给 #2315 留了告知（不要把两路输出合流后按行解读；凭据必须落在被遮住的目录里）。
沙箱一侧由作者的 S7、S22 承担，我独立重跑两例均通过：S7 的四个哨兵在宿主机侧都不存在、
工作区源码与配置逐字节未变、仓库目录快照不变；S22 显示第 5／7 步什么都写不进、第 6 步只有 `.lake` 可写、
只有回环网卡、环境变量只在白名单内。**我没有在沙箱外看到任何哨兵。**

**(c) 能否进一步让第 7 步给出错误的绿**

没有看到。旧式 config 的求值能力限于纯计算，改不了产物、改不了公理闭包，也动不了声明范围。
真正能让第 7 步错误地绿的仍然是伪造 `.olean`（备忘 3.6 第 1、4 条），那条路本票已明示交给 #2315
的内核重放与 comparator，不算本片阻断。给 #2315 的两条实测补充：
(1) 旧式 config 这条入口在**产物诚实**的前提下只能污染构建日志；
(2) 4.36 的模块制相位检查（`meta` 导入屏障）在本项目的头部规则加修饰符白名单之下，
实际上把「库里的求值入口」能被被审源码直接调用的那一类基本关掉了，
剩下的是**库自己在精化期替被审代码求值**这一类（旧式 config 就是），
#2315 评估 `lake check` 的覆盖面时可以按这条分界来算。

---

## 非阻断发现与建议

1. **N1（第三片既有行为，建议另开票）：`structure` 字段的 autoParam 默认证明在第 7 步被 `ENV_META` 判红。**
   最小夹具 `fx/y-auto`：

   ```lean
   structure Win where
     size : Nat
     pos : Nat
     ok : pos ≤ size := by omega
   ```

   第 1–6 步全绿，第 7 步 `FM RED env ENV_META formal_math/Chan/Thm/Auto.lean:Win.ok._autoParam 声明是 meta 元程序`。
   Lean 把 autoParam 的战术块生成为 `meta` 常量（`Win.ok._autoParam`），而 `gate3` 的 `isMarkedMeta`
   无条件查、没有豁免路径。这**不是本片引入的**（`gate3` 本体未动，属已过审的第三片），
   但它是日常写法，而且语料里没有夹具覆盖——`must_green/g3/r3-a7-default-prop-field` 用的是**项**默认值
   `ok : n = n := rfl`，不生成 `_autoParam`，所以这条一直没被量到。
   正文一旦用 `:= by omega`／`:= by simp` 这类字段默认证明就会被挡住，建议单独挂票评估
   （要么给 autoParam 一条按生成来源的豁免，要么在文档里明确禁止这种写法并补必红夹具）。
2. **N2：`SHAPE_EXPOSE` 的存在性判据可以被空节满足**（`fx/x-expose`），但第 7 步门 15 接住了，
   README 的「谁接」如实。若想在第 5 步就给出更准的诊断，可以要求文件里至少有一条声明落在该节之内；
   不改也不影响结论。
3. **N3：`fixtures.tsv` 建议给甲-1 补一行必红**（修好之后），并把 `aesop (config := …)`、
   `aesop (simp_config := …)`、`plausible (config := …)` 三种写法都放进 `selftest.py` 的 `SHAPE_RED`，
   再加一种弱化（去掉旧式 config 的记号检查）以免回归。
4. **N4：建议在 README 的禁用清单行把判据写成语法种类级别的说明**（哪些写法属于「旧式 config」），
   因为这一轮的漏就出在「名字对了、判据只覆盖了一半」。

---

## 依赖目录前后比对

严格只读使用 `/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages`：
`shp.py` 经 `bwrap --ro-bind` 挂载，`pipe.py` 把它交给 `run.py --packages`（第 5、7 步只读挂载，
第 6 步只读挂到 `.lake/packages`）。涉及「依赖目录是否可写」的试验我没有做（作者的 S7、S22 用的是
自测自建的假依赖目录，我重跑的也是那两例）。

开工与收工各记一次顶层列表与修改时间（`shape-r1-fixtures/packages-before.txt`、`packages-after.txt`）：

```
$ diff packages-before.txt packages-after.txt
（无输出）
依赖目录：前后无差异
```

十个包目录（`Cli`、`LeanSearchClient`、`Qq`、`aesop`、`batteries`、`importGraph`、`mathlib`、`plausible`、
`proofwidgets` 与父目录）的 mtime 全部保持 2026-11-24 的原值。

---

## 没覆盖的部分

- **全量自测（293 例）与弱化自测（43 种）没有重跑**（任务说明不必重跑来确认主控读数）。
  我重跑了与本片直接相关的 13 例：H1、H1b、H2（a/b/c）、H3（a/b）、D1（a/b）、D2、S22、S7、S5f、S5g、S5h、
  S27c、E16，**13/13 通过**（106 s）。43 种弱化我只做了代码阅读，没有逐一改弱复跑。
- **「只解析 vs 真实精化命令数」的比对**：我只独立验了 H2a 的 7 个文件 18 条命令，
  以及我自己语料的命令数（第 5 步报 65 条、构建绿）；作者自述的「34 个全绿夹具 97 个文件 271 条命令
  逐文件一致」没有逐一复算。
- **性能读数**（1.5 s 加载、951 MiB 常驻、每文件 2.4 ms、真实仓库第 5 步 2.7 s）**没有复测**；
  我观察到的第 5 步耗时在 1.5–5.4 s（1–5 个文件、1–3 组），量级相符。
- **主控在真实仓库上的那次自举七步全绿没有复跑**（需要真实仓库基线 `594e49b5ec` 与放行开关）。
- 按范围未审：预检、取料、构建审计程序、头部规则、第 6 步产物形状表、环境层与声明锁的本体逻辑
  （骨架与环境层已过审），CI 工作流（#2315），`report_cases/`（按用户裁定保留、当前无人运行，未看）。
- **畸形 `.olean` 对审计进程的影响**（备忘 3.6 第 5 条、附录 B）未构造样本，沿用「未核实」。

---

VERDICT-甲形状门: BLOCK（范围：`auditor/Auditor/Shape.lean` 的禁用清单检查与 `runner/README.md` 的对应规则行。一条阻断缺陷甲-1：点名禁用的旧式 `(config := …)`／`(simp_config := …)` 写法以明文出现而未判红，影响面是整条旧式 config 语法种类及库里的同形 clause（`aesop`、`plausible` 可直接写出），实测七步全绿 rc=0，且这条正是能在构建期求值被审项的入口；最小修法见报告。白名单五张、`set_option` 各位置、`#guard_msgs` 三条限制、`Chan/Defs` 规则、禁用清单其余各项共 537 个变体无第二处漏；必绿语料零误拒（仓内 54 个 must_green 夹具、R5-B4 的 41 条、自写 5 文件 65 命令语料均第 5 步零命中、第 6 步可构建）；「不防什么／谁接」如实；只解析与真实构建未发现方向是漏的差异）

VERDICT-乙已过审代码的改动: PASS（带条件）（范围：`auditor/Main.lean` 6 处与 `runner/run.py` 的第 5 步实现与派生凭证接线；`Auditor/EnvGates.lean`、`Auditor/Headers.lean`、`precheck/` 相对 `98c69ff109` 的 diff 实测为空。无高项：拿不到错误的退出码 0、改不了审计二进制、写不到声明范围之外、手写的禁用标记拿不到豁免；凭证在受信目录、第 6 步看不见它、第 7 步再校验路径；`expect` 没有削弱全集覆盖（三道锁）；`shape-plan` 可被影响的部分只能收紧；第 5 步不执行被审代码且搜索路径上没有被审产物。两条条件项：伪造产物仍可骗到第 3 类豁免（已明示前提，owner #2315）；建议给 `ctx.certificate` 一个显式默认值，别只靠 `INTERNAL` 兜底）

VERDICT-丙删除: PASS（范围：旧 `SourceGates.lean`、`Perimeter.lean`、`Inventory.lean`、`Audit.lean`、顶层 `EnvGates.lean`、`run_gates.py`、旧 `selftest.py`、`inventory.py`、`make_lists.py`、两份名单、`pins.json`、`g6b` 夹具、247 个旧元数据文件、20 个 `host_secret_probe.txt` 与 16 个 Lake 配置名夹具。十九个名字全仓 grep 无活引用；删掉的检查都有去处或已在两张出入表里列明；`fixtures.tsv` 归「本片判红」的全部 74 行逐行实测，红码与声称完全一致、0 行不符；唯一端到端转绿的旧必红夹具 `must_red/g1/runtime-pin` 已归「不再检查」并写明理由）
