# #2312 第四片（源码形状门）非作者独立审阅 r2（定点复审）

| 项 | 值 |
|---|---|
| 被审提交 | `8369643028747b172b5a39a52a67bf67c09ab7f0`（分支 `origin/infra/2312-g-shape`，head 已核对相符） |
| 上一轮被审提交 | `1acb400d631e6d4154a3ef4ebb779f7a781e2425`（报告 `origin/evidence/2312-shape-review` @ `b97bb7f836`） |
| 本轮受审面 | 只有 `git diff 1acb400d63..8369643028`（9 个文件，增 124 删 16）。上一轮已审而本轮未变的部分不重审 |
| 实际运行的模型与档位 | **会话中途换过模型**：前半段 **Claude Fable 5.2（`claude-fable-5-2`）**——检出与 diff 核对、夹具构造（141 个变体）、甲-1 复验、误拒探针、自做弱化、流水线探针；后半段 **Claude Opus 5（`claude-opus-5`）**——README 三段的如实性核对、N1 夹具端到端实测、回归抽查、537 变体重跑比对、结论与本报告。两段用同一套脚本、同一个被审提交、同一个依赖目录。effort 档位会话没有向我暴露，不代填 |
| 工具版本 | Lean 4.36.0（`611c117bfaf7b7ae1cfcf246ce6fba31e8f509e9`）、Python 3.14.4、bubblewrap（经 `run.py` 调用）、git 2.53.0 |
| 审阅方式 | 只读。没有改被审分支上的任何文件，没有评论或改动任何 issue，没有开 PR |
| 工作目录 | `/home/workspace/fm/tmp/review-g2/`；夹具与脚本随本报告推到 `audit-reports/2312/shape-r2-fixtures/` |
| 根分区 | 开工 247 GiB 可用，收工 246 GiB 可用，全程未触 5 GiB 红线 |

读过：上一轮报告 `audit-reports/2312/shape-review-r1.md` 全文与 `shape-r1-fixtures/`；本轮 diff 全文；`runner/README.md` 的「第 5 步：源码形状门」「不防什么」「已知问题」「自测」各节；`auditor/Auditor/Shape.lean`、`runner/run.py` 的 `step_shape`／`step_env`／`main`、`runner/selftest.py` 的 `SHAPE_RED`／`S32`／`MUTANTS`／`corpus_case`；Lean 4.36 `Init/Tactics.lean`、`Lean/Parser/Term.lean`、`Lean/Elab/Tactic/Config.lean`、`Lean/Elab/ConfigEval.lean`、`Lean/Elab/Binders.lean`；钉选库 `aesop/Aesop/Frontend/Tactic.lean`、`plausible/Plausible/{Tactic,Testable}.lean`、`batteries/Batteries/Tactic/Congr.lean`、`mathlib/Mathlib/Tactic/Linarith/Frontend.lean`、`mathlib/Mathlib/Tactic/Simps/Basic.lean`。

自己写了 **141 个新变体**（出现位置 42、空白与注释 15、旧新式混写 18、名字判据 21、误拒探针 23、`native` 回归 19、linarith 子句 3）加 **9 组流水线夹具**，重跑了上一轮全部 **537 个变体**、仓内 **55 个 must_green 夹具**、`fixtures.tsv` 归「本片判红」**75 行中的 24 行**，并自做 **7 种弱化**。

**先说结论的差别**：上一轮的阻断缺陷甲-1 **确已修好**（我按六类新变体复验，没有发现第二处漏，也没有发现必绿语料被误拒）。但 README 这一轮新写的「已知不防」里有一句与实测相反，按上一轮沿用的阻断条件 3（「不防什么／谁接」不如实）成立，所以甲仍是 BLOCK——**只需改一句说明，不需要改代码**。

---

## 一、甲-1 复验与新变体表

### 1.1 上一轮三份夹具

三份都已判红，整次运行停在第 5 步（逐字命令：`source scripts/fm_env.sh`；
`flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh python3 -I tools/pipe.py <夹具>`）：

| 夹具（r1） | 上一轮实测 | 本轮实测 |
|---|---|---|
| `fx/a1-aesop-green`（`aesop (config := …)`） | 七步全绿 rc=0 | `rc=1 … shape:RED`，`FM RED shape SHAPE_FORBIDDEN formal_math/Chan/Thm/A.lean:10 禁用旧式配置子句 (config := …)` |
| `fx/a1-aesop-eval`（取值带 `dbgTrace`） | 七步全绿，标记进构建日志 | 同上，第 5 步即红，第 6 步没跑 |
| `fx/a1-plausible`（`plausible (config := …)`） | 第 5 步零命中 | 同上，第 5 步 `SHAPE_FORBIDDEN` |

仓内新夹具 `must_red/g3/r1-legacy-config`（三个文件）经作者自己的语料断言复跑：
`通过 语料 must_red/g3/r1-legacy-config（第四片） rc=1 红码=SHAPE_FORBIDDEN 期望 rc=1 步=shape 码=SHAPE_FORBIDDEN`。

### 1.2 出现位置（42 个变体，全部 `SHAPE_FORBIDDEN`，期望与实测 42/42 相符）

`<;>`、`all_goals`、`any_goals`、`repeat`、`try`、`iterate`、嵌套 `by`（`exact (by exact (by …))`）、
`show … from by`、`calc` 步骤（两步各一条子句）、`match` 分支、`have … := by`、`where` 定义、
`suffices`（战术与项两种）、`let … := by`、`induction … with` 分支、`rcases` 后的 bullet、
bullet `·`、`case`／`next`、`first | … | …`（含括起来的战术序列）、`conv =>` 内（`simp (config := …)` 与
`tactic => aesop (config := …)`）、`fun _ => by`、匿名构造子 `⟨by …, by …⟩`、`instance : … := ⟨by …⟩`、
`decreasing_by`、绑定器自动参数 `(h : True := by aesop (config := {}))`、`structure` 字段默认证明、
`set_option … in` 之下、多层 `namespace`、`mutual` 内、`#check (by … : True)`、`example`、
`simp (disch := aesop (config := …))`（判别式里）、`aesop?`、`aesop (add …) (config := …)`（子句在 `add` 之后）。
战术来源覆盖核心 `Lean.Parser.Tactic.config`（`simp`／`decide`／`rw`／`omega`…）、Aesop 的 `config` 与
`simp_config`、`plausible`、Batteries 的 `congr`／`rcongr`。

### 1.3 记号之间的空白、换行、注释（15 个变体，全部 `SHAPE_FORBIDDEN`，15/15 相符）

`( config := {} )`、`(config:={})`、`(`／`config`／`:=`／取值各自换行、`(` 后接行注释、
`(/- 块 -/ config /- 块 -/ := /- 块 -/ {})`、`config` 与 `:=` 之间夹行注释、嵌套块注释
`(/- 外 /- 内 -/ 外 -/ simp_config := {})`、子句整条写在下一行、取值前后夹块注释，
以及 plausible／Batteries `congr`／核心 `simp` 的同类写法。
`trimAscii` 这一层是必要的：去掉「认记号形式的键」那一支时 Aesop／plausible／`congr` 四例立刻漏（见第七节 m5）。

### 1.4 旧式子句与新式配置项混写（18 个变体，全部 `SHAPE_FORBIDDEN`，18/18 相符）

`simp (config := {}) +contextual`、`simp +contextual (config := …)`、`simp (maxSteps := 10) (config := {})`、
`simp -zeta (config := {}) [Nat.add_zero]`、`simp (config := {}) (maxSteps := 10) at h ⊢`、
`simp +arith (maxSteps := 5) (config := {}) -zeta only [Nat.add_zero]`、
`aesop (config := {}) (simp_config := {})`、`aesop (add …) (simp_config := {}) (rule_sets := [builtin])`、
`decide +kernel (config := {})`、`decide +native (config := {})`、
`simp_all`／`dsimp`／`rw`／`simpa`／`omega`／`constructor`／`norm_num`／`ring_nf` 的 `(config := …)`。
**混写不会互相掩盖**：同一条战术里新式项按设计放行、旧式子句照样判红。

### 1.5 名字判据（21 个变体）——与 README 写的「名字以 `config` 结尾」逐字一致

| 写法 | 实测 | 与 README 判据 |
|---|---|---|
| `aesop (simp_config := {})` | `SHAPE_FORBIDDEN (simp_config := …)` | 一致 |
| `simp (my_config := 1)` | `SHAPE_FORBIDDEN (my_config := …)` | 一致（假想名字，以 `config` 结尾） |
| `simp (reconfig := 1)` | `SHAPE_FORBIDDEN (reconfig := …)` | 一致 |
| `simp («config» := {})` | `SHAPE_FORBIDDEN (config := …)` | 一致（书名号被 `getId` 去掉） |
| `simp (X.config := 1)`、`simp (_root_.config := {})` | `SHAPE_FORBIDDEN (X.config := …)`／`(_root_.config := …)` | 一致（点名以 `config` 结尾；注意这一条没有去 `_root_`，与 `sorryAx` 那条的 `stripRoot` 不同，不影响判定方向） |
| `simp (Config := 1)`、`(CONFIG := 1)`、`(config' := 1)`、`(configs := 1)`、`(config_ := 1)` | GREEN | 一致（大小写敏感、不以 `config` 结尾） |
| `simp («my config» := 1)`、`simp («x.config» := 1)` | GREEN | 一致。机理：`getId.toString` 对需要转义的名字会把书名号加回去，字符串成了 `«my config»`／`«x.config»`，结尾是 `»` 不是 `config`；而 `«config»` 不需要转义，`toString` 就是 `config`，所以它红（上一行） |
| `simp (config.zeta := false)` | GREEN | 一致（名字以 `zeta` 结尾；这是新式字段路径写法，取值不走整体求值） |
| `aesop (Config := …)`、`(my_config := …)`、`(config' := …)`、`(X.config := …)`、`(«config» := …)` | `SHAPE_PARSE`（`expected 'add', 'config', 'erase', 'rule_sets' or 'simp_config'`） | Aesop 的 parser 只认两个记号，别的名字根本解析不过去——红，且是解析失败红 |
| `plausible («config» := …)`、`plausible (simp_config := …)` | `SHAPE_PARSE` | 同上（核心 `config` 只认记号 `config`） |

即：**旧式子句的真实语法只认 `config`／`simp_config` 两个记号，写别的名字在解析阶段就红**；
形状规则的「以 `config` 结尾」只在新式 `valConfigItem` 与函数应用命名参数这类「键是标识符」的节点上才可能比真实语法更宽
（见第二节）。

---

## 二、新规则会不会误拒（23 个探针 + 3 个 linarith 子句）

| 写法 | 实测 | 判断 |
|---|---|---|
| **函数应用命名参数 `run (config := 1) 2`** | **`SHAPE_FORBIDDEN (config := …)`** | **被判红，README 没有写明这个代价**（见 2.1） |
| `S.mk (config := 1) (n := 2)`（构造子命名参数） | `SHAPE_FORBIDDEN` | 同上 |
| `s.go (cfg_config := 1)`、`re (reconfig := 1) (simp_config := 2)` | `SHAPE_FORBIDDEN`（一行两条发现） | 同上，任何以 `config` 结尾的参数名 |
| `exact run_eq (config := 1) (n := 2)`、`rw [run_eq (config := 1)]` | `SHAPE_FORBIDDEN` | 同上（战术里引用引理时一样） |
| `id <| run (config := 1) 2` | `SHAPE_FORBIDDEN` | 同上 |
| `run2 (cfg := 1) (n := 2)`、`run3 (configN := 1) (config' := 2)` | GREEN | 名字不以 `config` 结尾，不命中 |
| 结构实例 `{ config := 1, n := 2 }`、`{ s with config := 3 }`、`⟨1, 2⟩`、`where config := 1` | GREEN | 不是「`(`…`:=`」形状 |
| 结构模式 `⟨config, n⟩`、`{ config := c, n := _ }`、`let ⟨config, _⟩ := s` | GREEN | 同上 |
| 类型标注与绑定器 `(cfg_config : Nat)`、`(config)`、`(config, config)`、`fun (config : Nat) =>`、`∀ (config : Nat)`、`∃ config : Nat` | GREEN | 第三个子节点不是 `:=`（这一条靠的正是 `stx[2] == ":="`，见第七节 m1） |
| 绑定器默认值 `def a (config := 5) (n : Nat := config)`、`(config : Nat := 5)`、`variable (simp_config := 3)`、`structure` 字段 `(config : Nat := 5)`、`(simp_config := 3)` | GREEN | `explicitBinder` 的第二个子节点是 null 节点，不是记号／标识符 |
| 绑定器自动参数 `(h : config = config := by rfl)` | GREEN | 同上 |
| `let (config := 5) := 1`、`fun (config := 5) =>`、`(config := 5)` 当项 | `SHAPE_PARSE`／GREEN | 不存在的写法，真实编译器同样拒；照实记 |
| 新式配置项 11 条（`(maxSteps := 1000)`、`+contextual`、`-zeta`、`+kernel`、`(maxDischargeDepth := 3)`、`(singlePass := true)`、`(occs := .pos [1])`、`(disch := omega)`、`(discharger := simp)`、`(rule_sets := [builtin])`、`+arith`、`+splitDisjunctions`） | GREEN | 与 README 「新式字面量配置项不受影响」一致 |
| 字符串、`s!` 插值、行注释、块注释、嵌套块注释、文档注释、模块注释、原始字符串里的同形文字 | GREEN | 不误命中 |
| 名为 `config` 的局部变量在 `obtain`／`rcases`／`calc`／`induction` 分支／`intro (config : Nat)`／`let`／`have` 等 9 条命令里 | GREEN | 不误命中 |
| `@[simps (config := { fullyApplied := false })]` | `SHAPE_FORBIDDEN` | 属性上的旧式子句，规则内，设计内判红 |
| `@[simps -fullyApplied]`、`@[simps (attr := simp) a]` | GREEN | 新式项与 `(attr := …)` 不受影响 |
| `linarith (config := {})` | `SHAPE_FORBIDDEN` | 规则内 |
| `linarith (oracle := .simplexAlgorithmSparse)`、`linarith (transparency := …) (exfalso := true)` | GREEN | 名字不以 `config` 结尾，按 README 不在规则内（**但这类取值确实会被库求值，见第三节**） |

### 2.1 函数应用命名参数这一条：我的判断

**事实**：形如 `f (config := x)` 的命名参数（`Lean.Parser.Term.namedArgument`，语法是
`atomic("(" >> ident >> " := ") >> term >> ")"`，子节点依次是 `(`、标识符、`:=`、取值、`)`）与旧式配置子句同形，
只要参数名以 `config` 结尾就判 `SHAPE_FORBIDDEN`，说明栏写的是「禁用旧式配置子句」。
这在项位置、战术位置（`exact`／`rw` 的引理实参）、构造子调用上都成立。

**README 有没有如实写明**：**判据写明了，代价没有写明。** 禁用清单那一行把判据写成
「任何语法节点，只要前三个子节点依次是记号 `(`、一个名字以 `config` 结尾的记号或标识符、记号 `:=`，就判红
（不按语法种类列名单）」——照这句话逐字推，命名参数当然在内。但紧接着的叙述是
「钉选库里实际存在的这类子句只有两个名字」，通篇只谈「库里的子句」，没有一处说
「被审源码里普通的函数应用命名参数也会被挡」。「不防什么」一栏按定义只写漏掉的，不写多挡的。
一个只读 README 的作者会以为这条规则只碰战术配置。

**归类与定档**：按上一轮沿用的口径，这**不是**阻断条件 2（必绿语料被误拒）——仓内 55 个 must_green 夹具、
R5-B4 的三份汇总、上一轮自写的必绿语料本轮**全部第 5 步零命中**，当前仓里 `formal_math/Chan*` 也没有任何
`(…config := …)` 命名参数（`rg` 零命中）；也不是阻断条件 3，因为「不防什么／谁接」谈的是漏，不是多挡。
**定为条件项（乙类低档，归甲）**：README 要补一句代价。

**代价可否接受**：**可以接受。** 理由四条。
(1) 方向安全：失败方向是多挡，不是放过，形状门又是诚实作者断言，多挡只会挡住作者自己。
(2) 规避成本接近零且就在本地：改用位置参数，或把参数名从 `config` 换成 `cfg`（实测 `(cfg := 1)` 绿）。
被审语料是本项目自己写的小集合，不是第三方代码。
(3) 当前零影响：仓内与全部必绿语料都不含这种写法。
(4) 换成窄办法要付的代价更贵：见下。

**不依赖精化的窄办法有，但我不建议用**。最窄的一种是在 `legacyConfig` 里排除语法种类
`Lean.Parser.Term.namedArgument`（解析期就知道种类，不需要精化）；钉选集合里四种真子句的种类分别是
`Lean.Parser.Tactic.config`、`Aesop.Frontend.Parser.«tactic_clause(Config:=_)»`、
`«tactic_clause(Simp_config:=_)»`、`Lean.Parser.Tactic.valConfigItem`，都不会被解析成 `namedArgument`，
所以这个排除在今天是精确的。但它把刚刚因「按种类列名单」而漏掉一整类的规则，重新变成种类敏感的规则——
甲-1 的教训正是这一点，而核心 `ConfigEval` 的 `foldConfigM` 明说它把
「`"(" (atom<|>ident) ":=" syntax ")"` 的五子节点节点」一律当配置项（`Lean/Elab/ConfigEval.lean:60-62`），
将来库换个种类重用这个形状，排除名单就可能连带放过真子句。
「只在战术位置应用这条规则」更贵：`inspect` 现在只跟踪 `command`／`guarded` 两个标志，要判「战术位置」
得沿祖先链认种类（`conv`、`grind =>`、`disch :=`、属性里的 `simps` 配置都要算），
机器复杂度与被绕过的面都比现在大。**建议保持现规则不动，只补说明**（见第八节条件项甲-C1）。

---

## 三、甲-2（阻断）README 新写的「已知不防」里有一句与实测相反

- **类别**：阻断条件 3（「不防什么／谁接」不如实）。**只在说明层，代码不用改。**
- **位置**：`runner/README.md:374`（本轮新增的「**独审实测的结论**」一段的末句）：

  > 被放行的新式配置项没有求值能力（`fx/e-eval5`：`Could not evaluate the expression`）。

- **实测反例**：钉选 Mathlib 的 `linarith` 为它的配置**显式**打开了通用求值器
  （`mathlib/Mathlib/Tactic/Linarith/Frontend.lean:511-515`）：

  ```lean
  private local derive_eval_expr_instance_using_meta_eval Linarith.LinarithConfig
  -- Enable using Meta.evalExpr' for `(oracle := ...)` option
  private local derive_eval_expr_instance_using_meta_eval Linarith.CertificateOracle
  private local derive_eval_expr_instance_using_meta_eval Linarith.GlobalBranchingPreprocessor
  ```

  夹具 `fx/ev-linarith-trace`（**不**跳过第 5 步，逐字命令
  `flock … guard.sh python3 -I tools/pipe.py fx/ev-linarith-trace`）：

  ```lean
  theorem probe (a b : Nat) (h : a < b) : a ≤ b := by
    linarith (oracle := (dbgTrace "FM-R2-LINARITH-ORACLE-RAN" fun _ => .simplexAlgorithmSparse))
  ```

  ```
  rc=0 steps=precheck:GREEN fetch:GREEN auditor:GREEN headers:GREEN shape:GREEN build:GREEN env:GREEN
  FM RESULT GREEN 七步全绿
  FM LOG build info: Chan/Thm/A.lean:7:0: FM-R2-LINARITH-ORACLE-RAN
  ```

  `(oracle := …)` 是**被放行的新式配置项**（键不以 `config` 结尾，第 5 步 GREEN，见 2.1 表末两行），
  而它的取值在第 6 步精化期被编译并运行了——与甲-1 同一机制（`Meta.evalExpr'`），
  不是 `fx/e-eval5` 里核心 `simp` 那种受限求值器。
- **影响面**：**说明层，一句话**；规则与代码按设计工作，禁用清单那一行的「不防什么」一栏本身写得对
  （它明说不防「名字不以 `config` 结尾、但库在精化期替被审代码对其中的项求值的子句或战术，本片没有逐个列出」）。
  问题在于同一节的叙述把上一轮的一个探针（核心 `simp`，`fx/e-eval5`）升格成了对「被放行的新式配置项」整类的
  能力否定。**这正是本轮要我查的那种失真**：上一轮写的是「这一个没有求值能力」，README 写成了「这一类没有」。
  按本句字面读，读者（含 #2315 的评估者）会以为门禁放行的配置项都不可能运行被审代码，从而低估残余面；
  实际上残余面就是「不防什么」一栏已经点明的那一类，而且在钉选库里**有现成的实例**。
  这条失真是上一轮我方报告先写错、本轮被原样搬进正式说明的；责任我这边也有一半，但本轮它落在受审面里。
- **最小修法**（说明订正，不动代码）：把该句改成按库区分的陈述，例如
  「核心 `simp` 一类用受限求值器，非字面量取值直接报 `Could not evaluate the expression`（`fx/e-eval5`）；
  但有的库为自己的配置显式打开通用求值器——`linarith` 用
  `derive_eval_expr_instance_using_meta_eval` 给 `LinarithConfig`／`CertificateOracle`／
  `GlobalBranchingPreprocessor` 开了 `Meta.evalExpr'`，于是 `linarith (oracle := …)` 的取值在精化期被求值
  （独审 r2 实测 `fx/ev-linarith-trace`，能力上界同甲-1：纯计算加 `dbgTrace`／`panic!` 往标准错误打字）。
  这类子句名字不以 `config` 结尾，按设计不在本规则内，归「不防什么」一栏与 #2315。」
  顺带建议把同段「通往宿主机读写的通道**都**被堵住」的「都」改成「下表列出的通道」，
  避免把枚举结论写成全集结论。
- **再审**：纯说明订正，**无需再审，由主控核对差异即可**；若借此改动了 `Shape.lean` 或规则本身，则要再审。

---

## 四、乙：`run.py` 的 3 行

| 查项 | 实测 |
|---|---|
| `Run.certificate = None` 类属性 | `run.py:67` 有，注释写明「第 5 步写出的派生凭证路径；第 7 步要求它就是第 5 步写的那一份」。上一轮条件项 2 所指的 `AttributeError → INTERNAL` 兜底不再是唯一依赖 |
| `NO_CERTIFICATE` 判定 | `run.py:706-707`：`certificate is None or certificate != os.path.join(ctx.trusted_dir, "derived.json")` → `Fault("NO_CERTIFICATE", …)` 退 2。能堵住「第 7 步用了不是第 5 步产出的凭证」这一类：第 5 步是唯一给 `ctx.certificate` 赋值的地方（`run.py:594`，赋的正是这个路径），凭证路径不可由被审提交或被审构建影响——它由 `--workdir` 派生，`prepare()` 已要求工作目录在仓库检出、git 目录、依赖目录之外且互不包含（`WORKDIR`），第 6 步整个工作目录被 tmpfs 盖住、只回绑被审工作区与 `.lake`（上一轮 S22 实测、本轮未重跑） |
| 两道检查的分工 | `NO_CERTIFICATE`（恰是第 5 步那一份）在前，原有 `CERTIFICATE`（`inside(realpath, trusted_dir)`）在后。后者现在实际上是死路（路径已被钉成常量），留着不碍事；两者都退 2 |
| 生产入口能否跳过第 5 步却到第 7 步 | **不能。** `STEP_FUNCS` 是固定七元组（`run.py:734`），`main` 顺序遍历；`--until` 只在 `n > ctx.until` 时写 `FM RESULT PARTIAL` 并 `return 2`（`run.py:840-841`），**只能截短不能跳步**，而且提前停下本身就是退 2。`parse()` 的选项表只有 8 个（`--trusted-change-approved`／`--bootstrap-trusted-from`／`--until`／`--repo`／`--base`／`--head`／`--branch`／`--workdir`／`--packages`），没有任何跳步开关；`main(argv, steps=STEP_FUNCS, start=1)` 的 `steps`／`start` 只能由进程内调用方给，命令行入口恒用默认值（`run.py:866`） |
| 跳过第 5 步的那些自测用例 | 旁路在 `selftest.py:115-125` 的驱动脚本里（`FM_SELFTEST_SKIP_SHAPE`），不在 `run.py` 里；`run.py` 全文没有这个环境变量。`!= "nocert"` 时写一份空凭证 `[]` 到同一路径并设 `ctx.certificate`，`== "nocert"` 时两者都不做（S32）。**测试设施，不在生产路径上** |
| S32 | 复跑通过：`rc=2`，`faults=["NO_CERTIFICATE"]`，最后一步 `env FAULT`（见第七节对照行） |

**乙的阻断缺陷：无。** 一条条件项（自测缺口）见第八节乙-C1。

---

## 五、README 改写的三段是否如实

### 5.1 「已知不防」的三段

| 段 | 核对结果 |
|---|---|
| **独审实测的结论** | 框架如实：开头就标「（不是证明不存在）」，主句用的是「审阅者**没有再找到**」，没有把「没找到」写成「不存在」；对 Aesop 规则战术那条写的是「结构性地触达不到」并给了编译器报错与两个夹具编号，与上一轮实测相符。**但末句失真（甲-2）**，另有「通往宿主机读写的通道**都**被堵住」一处把枚举写成全集（建议 S3） |
| **仍未穷尽、归 #2315** | 如实。写明「库在精化期替被审代码求值的入口没有逐个穷举（约 208 处）」、伪造产物与冷僻入口归 #2315、宿主机读写由第 6 步沙箱接并指明 S7 是跳过第 5 步的正对照。这一段恰恰已经把甲-2 的那一类包住了——两段互相矛盾，要改的是前一段 |
| **甲-1 修复前的行为** | 如实，且可复核：我重跑了同一夹具的「取值带 `dbgTrace`」版本（经自测驱动跳过第 5 步模拟修复前的情形，`fx/ev-aesop`），`FM LOG build info: Chan/Thm/A.lean:7:0: FM-R2-AESOP-RAN`，与 README 记的现象一致；修复后同一文件在第 5 步 `SHAPE_FORBIDDEN`（1.1 表） |

### 5.2 「名字不以 `config` 结尾的同形子句不防」这一句

**准确。** 我独立做了检索（正则扫工具链 `src/lean` 与依赖目录全部 `.lean`，另单独扫复用
`Parser.Tactic.config` 的语法），结论与 README 的「检索方法」一节逐项相符：

- 名字以 `config` 结尾的只有核心 `Init/Tactics.lean:34` 的 `config`、Aesop `Aesop/Frontend/Tactic.lean:31-32`
  的 `config` 与 `simp_config`；复用核心 `config` 的只有 `plausible/Plausible/Tactic.lean:158`、
  `batteries/Batteries/Tactic/Congr.lean:35,59,121`。**我没有找到第五处。**
- 同形而名字不以 `config` 结尾的确有二十余处，我数到的有
  `(occs := …)`（`Init/Conv.lean:41`）、`(iff := …)`／`(flat := …)`（`Init/Ext.lean:19,24`）、
  `(all := …)`／`(dsimp := …)`（`Init/Meta.lean:43,44`）、`(internalize := …)`、`(typeChanged := …)`、
  `(since := …)`、`(priority := …)`、`(motive := …)`、`(generalizing := …)`、`(kind := …)`、`(name := …)`、
  `(behavior := …)`、`(dependent := …)`、`(meta := …)`、`(eq := …)`、`(withAnonymousAntiquot := …)`、
  Aesop 的 `(add …)`／`(erase …)`／`(rule_sets := …)`／`(immediate := …)`／`(index := …)`／`(pattern := …)`／
  `(cases_patterns := …)`／`(transparency := …)`／`(transparency! := …)`、
  Mathlib 的 `(lemma := …)`／`(norm := …)`／`(exp := …)`／`(attr := …)`／`(prettyPrint := …)`。
  这些按 README 不在规则内，实测一致（`(occs := …)`、`(disch := …)`、`(rule_sets := …)`、
  `(transparency := …)`、`(attr := …)` 都 GREEN）。
- 补一条 README 没提、不影响判定的事实：Mathlib `Mathlib/Tactic/ExtractGoal.lean:116` 另有一个**名叫**
  `config` 的局部语法（`syntax config := star <|> (colGt ppSpace ident)*`），它没有 `(`／`:=` 形状，不命中本规则。

**不过「不防」这一句准确，不等于它的后果写得够清楚**——`linarith (oracle := …)` 正是这一类里会求值的实例，
README 却在同一节的另一段否认这类能求值（甲-2）。

### 5.3 「已知问题」N1 的描述与夹具期望

**与实际一致。** 夹具 `must_green/known-issue/autoparam-default-proof` 实测（作者自己的语料断言 + 我单跑一次拿步骤行）：

```
步骤: precheck:GREEN fetch:GREEN auditor:GREEN headers:GREEN shape:GREEN build:GREEN env:RED
FM RED env ENV_META formal_math/Chan/Thm/Auto.lean:Win.ok._autoParam 声明是 meta 元程序
FM RESULT RED 第 7 步 env 判红，后面的步骤没有跑
通过  语料 must_green/known-issue/autoparam-default-proof（已知问题（环境层误拒））  rc=1 红码=ENV_META  期望 rc=1 步=env 码=ENV_META
```

前六步绿、第 7 步 `ENV_META`、常量名 `Win.ok._autoParam`——与 README 和 `fixtures.tsv` 第 260 行逐字相符，
且 README 明写「**这是误拒，待后续片修，届时期望改为绿**」，没有把误拒写成设计。
作者给的原因判断我也核了：`Lean/Elab/Binders.lean:92-102` 的 `declareTacticSyntax` 确实把战术块存成
类型为 `Lean.Syntax` 的辅助定义、`modifyEnv (markMeta · name)` 后 `compileDecl`；
环境层那一侧是 `auditor/Main.lean:147-148` 的 `if isMarkedMeta env name then … ENV_META`，
对全部常量无豁免（紧邻的 `partial`／`unsafe`／`implemented_by` 才走 `generatedBy` 豁免）。
README 标为「推测、未实测」的那半句（绑定器自动参数 `(h : p := by tac)` 同样被误拒，辅助常量名形如 `…_auto…`）
我实测**成立**：夹具 `fx/n1-binder-auto`（`theorem probe (n : Nat) (h : n ≤ n := by omega) : n ≤ n := h`）
前六步绿、第 7 步 `FM RED env ENV_META formal_math/Chan/Thm/BinderAuto.lean:probe._auto_1 声明是 meta 元程序`。
README 在这里是偏保守的写法，如实。

---

## 六、回归抽查

| 抽查项（上一轮「核实正确的部分」里与甲有关的） | 本轮实测 |
|---|---|
| **上一轮 537 个变体全量重跑**（`cases_a/b/c` 重新落盘，与上一轮记录的实测逐文件 `diff`） | `a-forbidden`（185）**无差异**、`b-lists`（311）**无差异**、`c-probe`（41）**只有 4 行变化**，全是甲-1：`AesopConfig`、`AesopSimpConfig`、`PlausibleConfig`、`PlausibleConfig2` 由 `GREEN` 变 `SHAPE_FORBIDDEN`。**没有第五处变化，没有新的误拒** |
| 仓内 must_green 夹具第 5 步零命中 | **55/55 GREEN**（上一轮 54 个 + 本轮新增的 `known-issue/autoparam-default-proof`），含两个 `rfl'`「已知不防」夹具 |
| **R5-B4 的 41 条** | 三份汇总 `r5-b4-everyday-tactics`（18 条命令）、`-everyday-terms`（11 条）、`-readme-promised`（12 条）= **41 条，第 5 步零命中**，与上一轮一致 |
| 上一轮自写的必绿语料 `fx/g-green` | 4 个文件 **65 条命令**（20+6+38+1），**第 5 步零命中** |
| `fixtures.tsv` 归「本片判红」的行 | 总数由 74 变 **75**（新增甲-1 必红行）。抽查前 24 行逐行比对「退 1／判红步骤 `shape`／红码集合」：**0 行不符** |
| `native` 相关回归（原 `valConfigItem` 分支改动后） | 19 个变体：`decide +native`／`-native`／`(native := true)`／`(native := false)`／`+kernel +native`／`«native»`／`+«native»`／换行／块注释、`simp +native`、`native_decide`、`@[simps +native]`、`decide (config := { native := true })` **全部 `SHAPE_FORBIDDEN`**；`decide +kernel`、`nat (native := true)`（名为 `native` 的命名参数）GREEN。**`config` 键从 `valConfigItem` 支移走后没有两边都不管的写法**：`simp (config := {})`、`decide (config := {})` 由新规则接住（说明栏从「禁用配置项 config」变成「禁用旧式配置子句 (config := …)」），`+config`／`-config` 本来两边都不管、现在也不管（`posConfigItem`／`negConfigItem` 只查 `native`）——但那是**布尔开关写法，没有取值、不触发求值**，与旧实现一致，不是新开的口子 |
| 两个新夹具经作者自己的语料断言 | `must_red/g3/r1-legacy-config` 通过、`must_green/known-issue/autoparam-default-proof` 通过 |

---

## 七、我自己做的弱化（7 种，含对照）

每种都是「在副本里改一处 → 用副本自己的自测跑相关骨架用例」，逐字命令见
`shape-r2-fixtures/tools/mutants_r2.py`，原始输出见 `expect/mutants-r2.txt`。

| 弱化 | 改动 | 跑的用例 | 结果 |
|---|---|---|---|
| 对照 | 不改 | H1,S32 | 2/2 通过（基线干净） |
| m1 | `legacyConfig` 去掉「第三个子节点是 `:=`」的要求（只看前两个） | H1,H1b,H2,D1 | **4/4 通过 → 没被抓到**（见乙-C2／甲-C2） |
| m2 | 名字判据 `endsWith "config"` → `== "config"` | H1 | 抓到（缺 `FbCfgAesopSimpByTerm`） |
| m3 | `NO_CERTIFICATE` 去掉路径比对、只留 `is None` | S32,S22,D1,D2 | **4/4 通过 → 没被抓到**（见乙-C1） |
| m4 | `legacyConfig` 不认标识符形式的键 | H1 | 抓到（缺 `FbCfgConv`、`FbOldConfig`） |
| m5 | `legacyConfig` 不认记号形式的键 | H1 | 抓到（缺 `FbCfgAesop`、`FbCfgAesopSimpByTerm`、`FbCfgCongr`、`FbCfgPlausibleFirst`） |
| m6 | `valConfigItem` 支不再查 `native` | H1 | 抓到（缺 `FbDecideNativeVal`） |
| m7 | `NO_CERTIFICATE` 去掉 `is None`、只留路径比对 | S32 | 抓到（S32 变 rc=0） |

即：新规则的四个要件里，**三个（记号键、标识符键、名字判据）被 H1 钉住，第四个（`:=`）没有**；
`NO_CERTIFICATE` 的两半里，**`is None` 那半被 S32 钉住，路径比对那半没有**。

---

## 八、条件项

### 甲-C1 README 没写明「以 `config` 结尾的函数应用命名参数也会被判红」（低，说明）

见 2.1。实测 `run (config := 1) 2`、`S.mk (config := 1)`、`(cfg_config := 1)`、`(reconfig := 1)`、
`exact lemma (config := 1)`、`rw [lemma (config := 1)]` 全部 `SHAPE_FORBIDDEN`，说明栏还写成「旧式配置子句」。
当前仓内与全部必绿语料零影响，代价我判为可接受（理由四条见 2.1），窄办法不建议采用（种类敏感会重走甲-1 的坑）。
**修法**：在禁用清单那一行或「检索方法」段补一句，例如
「这条规则按形状判，因此被审源码里形如 `f (config := x)` 的函数应用命名参数（参数名以 `config` 结尾，
含 `simp_config`、`my_config` 这类）也会判红，说明栏仍写「旧式配置子句」；正文改用位置参数或把参数名换成
`cfg` 即可（实测 `(cfg := 1)` 绿）。这是按形状判必然带的代价，方向是多挡不是放过。」
**修正后无需再审，由主控核对差异即可。**

### 甲-C2 新规则的「`:=`」要件没有自测钉住（低，测试）

m1 把 `stx[2].isAtom && … == ":="` 改成 `true` 后，H1／H1b／H2／D1 全过。
这一改使规则覆盖到「`(`、以 `config` 结尾的名字、任意第三子节点」，会把
`(config : Nat)`、`(config, config)`、`(cfg_config : T)` 这类类型标注／元组误判红（我的 `fx/r2-fp/FTypeAscription`
在现版本是绿的，在 m1 下应当变红）。方向是多挡，不是漏，所以定低档。
**修法**：把 `CfgNewStyleGreen.lean` 那条必绿对照加两行（`(config : Nat)` 的类型标注与 `(config, config)` 元组），
并在 `MUTANTS` 里加一种「`legacyConfig` 不要求第三子节点是 `:=`」，由 H1 抓。
**修正后无需再审，由主控核对差异即可**（纯测试与必绿对照的增补）。

### 乙-C1 `NO_CERTIFICATE` 的路径比对那一半没有自测钉住（低，测试）

m3 只留 `certificate is None` 后，S32／S22／D1／D2 全过。
今天这一半是死路（只有第 5 步会赋值，赋的就是那个常量路径），所以不阻断；
但它正是本轮加这 3 行要防的那一半（「第 7 步用了不是第 5 步产出的凭证」），没有用例钉住就等于没锁。
失败方向仍安全：真要走到那一步，还有 `CERTIFICATE`（必须在受信目录内）兜一层，
再不行审计程序对非法凭证严格解码失败整次退 2。
**修法**：加一个用例——驱动脚本把 `ctx.certificate` 设成受信目录里的另一个存在的文件
（例如 `<trusted>/verification/runner/run.py`）、不写 `derived.json`，断言第 7 步 `NO_CERTIFICATE` 退 2；
再把它登记成一种弱化的抓手。
**修正后无需再审，由主控核对差异即可。**

---

## 九、建议（不阻断）

1. **S1**：`legacyConfig` 的键没有去 `_root_`（`simp (_root_.config := {})` 的说明栏打印 `(_root_.config := …)`），
   而同文件 `sorryAx` 那条用了 `stripRoot`。判定方向不受影响（都红），但两处判据风格不一致，顺手统一更好读。
2. **S2**：说明栏对「名字以 `config` 结尾但不是任何库子句」的写法（`my_config`、`reconfig`、命名参数）
   一律打印「禁用旧式配置子句」，容易让作者找错方向。建议说明栏改成
   「禁用「`(` 以 config 结尾的名字 `:=`」形状（规则见 README）」一类的中性措辞。
3. **S3**：README 同段「通往宿主机读写的通道**都**被堵住」把枚举结论写成全集结论，建议改为
   「下表列出的通道都被堵住」（与上一轮报告里那张通道表对齐）。
4. **S4**：`fixtures.tsv` 建议给 `linarith (oracle := …)` 这类「被放行但库会求值」的写法补一行
   必绿夹具（期望七步全绿）并在说明里注明归 #2315，这样甲-2 订正后的陈述有语料钉住，不只是文字。
5. **S5**（给 #2315 的实测补充，不属本片）：「库自己在精化期替被审代码求值」这一类里，
   `derive_eval_expr_instance_using_meta_eval`／`ensure_eval_expr_instance` 是可检索的开关
   （钉选集合里命中 `mathlib/Mathlib/Tactic/Linarith/Frontend.lean:511-515`、
   `Lean/Elab/Tactic/Simp.lean:71,83`、`Lean/Elab/Tactic/Grind/Config.lean:29`），
   评估覆盖面时可以按这条线索算，比按 208 处求值调用点全量扫更省。

---

## 十、依赖目录前后比对

严格只读使用 `/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages`：
`tools/shp.py` 经 `bwrap --ro-bind` 挂载，`tools/pipe.py`／`selftest.py` 把它交给 `run.py --packages`
（第 5、7 步只读挂载，第 6 步只读挂到 `.lake/packages`）。涉及「依赖目录是否可写」的试验没有做
（作者的 S7、S22 用自测自建的假依赖目录，本轮也没有重跑这两例）。

开工与收工各记一次顶层列表与修改时间（`shape-r2-fixtures/packages-before.txt`、`packages-after.txt`）：

```
$ diff packages-before.txt packages-after.txt
（无输出）
依赖目录：前后无差异
```

十个包目录（`Cli`、`LeanSearchClient`、`Qq`、`aesop`、`batteries`、`importGraph`、`mathlib`、`plausible`、
`proofwidgets` 与父目录）的 mtime 全部保持 2026-11-24 的原值，父目录保持 2026-11-26 08:42:22 的原值。
根分区开工 247 GiB、收工 246 GiB 可用。

---

## 十一、没覆盖的部分

- **构建期求值可达性的探查本轮没有再做**，沿用上一轮结论（上一轮的通道表与「宿主机读写没构造出来」照旧）。
  甲-2 是在核对 README 文字时由库源码与一个最小标记夹具确认的，不是新一轮可达性搜索的结果；
  甲-2 那条入口的能力上界我只测到「纯计算 + `dbgTrace` 往标准错误打字」，没有继续往下探。
- **全量自测（296 例）与全部 45 种弱化没有重跑**（任务说明不必重跑）。我只跑了与本轮受审面相关的
  骨架用例：H1、H1b、H2、D1、S32、S22、D2（经 7 次弱化副本运行，对照 2/2、各弱化批 1–4 例），
  外加两个新语料用例。作者自述的「296/296 退 0、45 种弱化全抓到、真实仓库七步全绿、共享依赖目录前后无差异」
  我没有复跑。
- `fixtures.tsv` 归「本片判红」的 75 行只抽了 24 行（上一轮跑过全部 74 行）。
- 上一轮「只解析 vs 真实精化命令数」的比对本轮没有再做（新语料用例由作者的 `corpus_case` 自带该比对，
  我只看它的通过结论）。
- **性能读数没有复测。**
- 按范围未审：预检、取料、构建审计程序、头部规则、第 6 步产物形状表、环境层与声明锁本体
  （骨架与环境层已过审，且本轮 diff 为空：`Auditor/EnvGates.lean`、`Auditor/Headers.lean`、`auditor/Main.lean`、
  `precheck/` 在 `1acb400d63..8369643028` 之间**实测无改动**）；CI 工作流（#2315）；`report_cases/`。
- **丙（删除）**：本轮 `git diff --diff-filter=D 1acb400d63..8369643028` **为空**，没有新的删除，
  上一轮的 PASS 原样成立，本轮不另审。
- N1 的修法没有评估（本片不改环境层，README 已写明待后续片）。

---

VERDICT-甲形状门: BLOCK（范围：`runner/README.md` 的「已知不防 → 独审实测的结论」一段，**代码不用改**。一条阻断缺陷甲-2：本轮新增的「被放行的新式配置项没有求值能力」与实测相反——`linarith (oracle := …)` 是按设计放行的新式配置项，钉选 Mathlib 用 `derive_eval_expr_instance_using_meta_eval` 为它打开了 `Meta.evalExpr'`，夹具 `fx/ev-linarith-trace` 在不跳过第 5 步时七步全绿且取值在第 6 步被求值、标记进构建日志；这把上一轮「这一个探针没有求值能力」升格成了对整类的能力否定，低估残余面，而同节「仍未穷尽、归 #2315」一段其实已经把这一类写对了，要改的是前一段。属阻断条件 3，最小修法见报告第三节。上一轮的甲-1 **已修好并复验**：三份旧夹具与新夹具 `must_red/g3/r1-legacy-config` 均第 5 步 `SHAPE_FORBIDDEN`；我另写 141 个变体（出现位置 42、空白与注释 15、旧新式混写 18、名字判据 21、误拒探针 23、`native` 回归 19、linarith 3）无一处该红没红；上一轮 537 个变体全量重跑与上一轮记录逐文件比对**只有 4 行变化、全是甲-1 转红**；必绿侧零误拒（仓内 55 个 must_green 夹具、R5-B4 的 41 条、上一轮自写 65 条命令语料均第 5 步零命中）；README 的名字判据、检索方法、N1 已知问题三处与实测逐项相符。两条条件项：命名参数被判红的代价未写明（甲-C1，可接受，建议只补说明）、新规则的 `:=` 要件没有自测钉住（甲-C2））

VERDICT-乙已过审代码的改动: PASS（带条件）（范围：`runner/run.py` 的 3 行（`Run.certificate = None`、`step_env` 的 `NO_CERTIFICATE`）与 `runner/selftest.py` 的 S32、必红／必绿对照与两种新弱化；`Auditor/EnvGates.lean`、`Auditor/Headers.lean`、`auditor/Main.lean`、`precheck/` 在两个提交之间实测无改动。无高项：`NO_CERTIFICATE` 把「第 7 步用的凭证必须恰是第 5 步写出的那一份」钉成路径常量比对，凭证路径由 `--workdir` 派生、被审提交与被审构建都影响不到；生产入口没有任何开关能跳过第 5 步却到第 7 步（`--until` 只能截短且提前停下即退 2，`STEP_FUNCS` 固定，`steps`／`start` 只对进程内调用方开放），跳过第 5 步的旁路只存在于 `selftest.py` 的驱动脚本里；S32 复跑 `rc=2 faults=[NO_CERTIFICATE] env FAULT`。一条条件项：`NO_CERTIFICATE` 的路径比对那一半没有用例钉住（乙-C1，低档，失败方向仍安全，`CERTIFICATE` 与严格解码兜底））

与上一轮合起来，对第四片在 `8369643028` 上的整体判断：**甲 BLOCK（仅一句说明失真，无需改代码）、乙 PASS（带条件，1 条低档条件项）、丙 PASS（上一轮结论，本轮无新删除，`--diff-filter=D` 实测为空）。本片在这个提交上还不能放行，但剩下的阻断面只有 `runner/README.md` 一句话；三条条件项全属说明与自测增补，按口径修正后都无需再审，由主控核对差异即可。**
