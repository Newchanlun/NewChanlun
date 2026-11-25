# #2312 FM-04 机械门禁：对 Gemini R2 BLOCK 七项的独立复核

- 复核对象：`0b991736774eaa4159baa75f2f3d35a10b67e015`（origin/infra/2312-b-env-gates），只读工作树 `/home/workspace/fm/wt/gates-r2`
- 复核方式：先读源码做静态判断，再在仓外实跑。工作树没有改动，没有推送，也没有发评论。
- 环境：Linux，Lean 4.36.0（commit 611c117b），`TMPDIR=/home/workspace/fm/tmp`。所有 lake/lean 命令都套了 `flock /home/workspace/fm/lean.lock` 和 `guard.sh`。Mathlib 复用 t3-f01a145b 的 `.lake/packages`，用的是符号链接，没有触发 Mathlib 重编。根分区跑前 259G 可用，跑后也是 259G。
- 实跑办法：把 `formal_math/` 和 `scripts/` 复制到 `/home/workspace/fm/tmp/audit2312/pkg/`，在其中建 `.lake/packages` 符号链接。单夹具运行器 `bin/probe.py` 直接 import `selftest.base_package`，装包方式和自测完全一样，然后调用真实入口 `run_gates.py --gate N`。
- 产物：夹具在 `/home/workspace/fm/tmp/audit2312/fx/<项>/`，日志是 `selftest.log`、`probes.log`、`probes2.log`，都在同一目录下。

## 0. 作者自述「139/139」

复现成立。`selftest.py` 共输出 139 行「通过」、0 行「失败」，`SELFTEST_EXIT=0`。

但要注意：自测全绿不覆盖下面 B4 至 B7 的样式。例如 g7a 的绿夹具 `compiler-auxiliaries` 只含非命题 `def` 的结构递归，没有 `deriving DecidableEq`、`termination_by`、`Prop` 类、结构递归定理；g7a 精化绿样也只有无参数结构。

## 1. 逐项判定总表

| 项 | 判定 | 依据 | 一句话 |
|---|---|---|---|
| R2-B1 词法脱同步 | 真病灶 | 实跑 | `s!"{'"'}"` 之后，八类禁用记号全部隐藏，门 2、门 3 均退 0 |
| R2-B2 包装击穿 8a/8b/9 | 真病灶（实现漏洞，修补便宜） | 实跑 + 对照组 | 三种包装使 7a/8a/8b/9 全退 0；去掉包装的对照组 8a/8b/9 全红 |
| R2-B3 proofHead 仅展开顶层 | 部分成立 | 实跑 | c1–c3 确实漏检；c4 的私有 helper 若放在节点通道内，会被 8b 自己抓到，整体退 1 |
| R2-B4 辅助常量误杀 | 真病灶（硬伤） | 实跑 | 实际命中 `_proof_1/_2`、`_flat_ctor`、`match_1_1`、`ofNat_ctorIdx`，7a 与 9 均退 1 |
| R2-B5 refines 强求 Sort | 真病灶（误杀部分）+ 部分成立（`False` 字段部分） | 实跑 | `[LT P]` 与 `(k : Nat)` 参数永久 FREE_PREDICATE；带 `bot : False` 的空结构退 0 |
| R2-B6 门 10 漏检与误杀 | 部分成立 | 实跑 | 四种漏检全部成立；「误杀」只是要求补签注，可以消除，不是永久红 |
| R2-B7 8a 绕过与 7b「崩溃」 | 部分成立 | 实跑 | 8 个 8a 变体全部漏检（对照组红）；7b 是有意的 fail-closed 退 2，不是崩溃，但与 README 的承诺不符 |

## 2. 逐项详述

### R2-B1：词法脱同步（真病灶）

**静态机理。** `run_gates.py:48-53` 的 `LEX` 把 `"…"` 当作不含插值的普通字符串。Lean 的 `s!"{…}"` 允许插值项里出现字符字面量 `'"'`。正则从第一个 `"` 匹配到 `'"'` 里的 `"` 就结束了，于是后面的 `'}"` 被拆成单字符记号，末尾的 `"` 又开启一段新的「字符串」，一直吞到下一个 `"`。此后字符串内外完全反转。

另外，未闭合的单个 `"` 走的是 `[^\s]` 分支，作为普通记号产出（`tokens()` 第 80 行要求 `len(token) > 1` 才视作字面量），**不会**触发 `Undetermined`。所以这里没有任何 fail-closed 的余地。

**实跑。** 夹具是 `fx/b1/formal_math/Chan/Thm/Fixture.lean`，在 `def quoteChar : String := s!"{'"'}"` 之后依次写：
- `set_option linter.unusedVariables false in` 加一个未用参数的 def
- `set_option autoImplicit true in` 加一个使用自动隐式参数的 def
- `#eval`、`run_cmd`、`declare_syntax_cat`、`syntax`、`infixl`、`macro`

最后用 `def resync : Char := '"'` 把引号重新对齐。纯 Python 调用 `run_gates.tokens` 的结果是：`option_issues=[]`，`banned=[]`。

经真实入口：门 2 **exit=0**（`lake build --wfail` 零警告通过），门 3 **exit=0**。

第一版夹具因缺 `import Lean.Elab.Command` 编译失败，已修正后重跑；`probes.log` 里那次失败读数作废，以 `probes2.log` 为准。

**影响。** 门 3 的环境层（公理闭包、unsafe、partial、extern）仍然有效，所以 `sorry` 和公理照样会被抓。被击穿的是「源码级禁用记号」与「局部选项」两层：
- 隐藏的 `autoImplicit true` 会改变定理陈述的含义；
- 隐藏的 `macro_rules` 或 `run_cmd` 能改写战术或环境。

这是实现漏洞，不是对抗上无法穷尽的问题。修法有两种：
- 治标：词法器识别 `s!`、`m!`、`f!` 等插值字符串，并对未闭合的 `"` 返回 2；
- 治本：由 Lean 前端（`Lean.Elab.Frontend` 或命令语法树）枚举命令，不再手写正则。

### R2-B2：statementHead 漏展开非项目包装（真病灶）

**静态机理。** `EnvGates.lean:222-235`：
- 项目常量才做 delta 展开；
- 其余常量只做 `withReducible whnf`。`Option.getD` 和 `Function.const` 都不是 reducible，所以停住；
- `And` 被列为逻辑边界，原样返回。

结果是 `telescope` 看不到 ∀ 与前提，门 8a、8b、9 都以为该定理「无前提」。门 9 期望的见证退化为 `True`。

**实跑。** 被测夹具 `fx/b2`，对照组 `fx/b2ctl` 的陈述去掉了包装：

| 定理 | 包装 | 7a | 8a | 8b | 9 |
|---|---|---|---|---|---|
| `vac`：`Option.getD (some (∀ x, x < 0 → x = 5)) True`（前提空真） | Option.getD | 0 | 0 | 0 | 0 |
| `mirror`：`Function.const Unit (∀ x, x = 0 → x = 0) ()`（镜像前提） | Function.const | 0 | 0 | 0 | 0 |
| `redundant`：`True ∧ (∀ x, x = 0 → x + 0 = x)`（冗余前提） | `True ∧` | 0 | 0 | 0 | 0 |
| 对照组（无包装） | — | 0 | **1**（mirror PREMISE_INSTANCE） | **1**（redundant DROPPABLE） | **1**（三条 WITNESS） |

三个定理都只配了 `witness : True := trivial`。

**评价。** 要利用这个漏洞，需要证明者有意写出怪异的陈述。但 Chan.Thm 的陈述不在 6a 锁内，由证明者自己写。修补成本很低：对非逻辑连接词的头部改用 default 透明度做 whnf，并在 `telescope` 中剥掉 `True ∧`。因此判为真病灶，属于实现漏洞，不是「对抗混淆无法穷尽」。

### R2-B3：proofHead 仅展开顶层项目常量（部分成立）

**静态机理。** `proofHead`（`EnvGates.lean:338-347`）只展开头部的项目常量。8b 的判据实际上是「删掉 h 之后，证明项里是否还出现 h 这个 fvar」：只要还出现，`mkLambdaFVars` 就会产生 `declHasFVars`，`replay` 返回 false，于是不报红。任何在死位置提到 h 的写法都能绕过。

**实跑**（`fx/b3`，只跑门 8b，exit=1）：

| 写法 | 结果 |
|---|---|
| `c0 := rfl`（对照） | 红 |
| `c1 := Function.const (x ≠ 0) rfl _hdiv` | **未报** |
| `c2 := (fun _ => rfl) _hdiv` | **未报** |
| `c3 := And.left ⟨rfl, _hdiv⟩` | **未报** |
| `c4 := Eq.trans (mkEq _hdiv) rfl` | c4 本身未报，但 helper `_private…mkEq` 被 8b 报 DROPPABLE |

审阅者说「四项门 8b 退 0」，对 c4 不准确：helper 与 c4 同在 Chan.Thm，自身就是节点，会被抓到。只有把 helper 放到非节点通道（Chan.Defs、Hypotheses 等，节点只认 Thm、Proofs、Exec、ChanChallenge），c4 才能真正退 0。这一点我没有实跑，属静态推断。

**评价。** c1–c3 都是 beta、proj-iota 或非项目 delta 就能消掉的写法，对证明项做完整归一（`Meta.reduce`，或对子项做 headBeta、proj 归约后再查 fvar）就能抓到，这一部分是实现漏洞。

但「判断前提在证明中是否必要」一般是不可判定的。`absurd`、`cast`、`if h then` 这类死用法静态上无法穷尽，8b 只能作为启发式；语义后盾应当是门 9 的 `needs_necessity` 反例。所以判部分成立：机理属实，但严重程度应按「启发式门的可加强点」计，不宜作为 BLOCK 级硬伤。

### R2-B4：编译器、派生辅助常量误杀（真病灶，硬伤）

**静态机理。** `node()`（`EnvGates.lean:28-41`）排除了投影、辅助递归子、noConfusion，以及「无声明范围且是保留名」或「构造器的 inj/injEq/sizeOf_spec/elim」。但编译器生成的 `_proof_N`、`match_N_M`、`_flat_ctor`、`ofNat_ctorIdx` 既不是保留名，也不在白名单里，类型又是 Prop，于是被当成手写节点。

**实跑**（`fx/b4`：Chan/Exec 里有 `deriving DecidableEq` 的 inductive、`termination_by`/`decreasing_by` 函数、`class Pos (n : Nat) : Prop`；Chan/Thm 里有一个用模式匹配做结构递归的定理，已登记并配好见证）：
- 门 7a exit=1，NODE_MISSING 命中：`instDecidableEqDir._proof_1`、`instDecidableEqDir._proof_2`、`countdown._proof_1`、`Pos.mk._flat_ctor`、`Dir.ofNat_ctorIdx`、`_private.Chan.Thm.Fixture.0.le_sumTo.match_1_1`
- 门 9 exit=1，上面六个名字同样报 WITNESS 缺失

审阅者没有列出 `ofNat_ctorIdx`，实际也命中了。

**W3 常见度。** 旧仓 `formal/` 中 `deriving DecidableEq` 在 106 个文件里出现 424 次，`termination_by` 在 7 个文件里出现 16 次。按总计划，`Chan/Exec` 是「纯函数可执行模型」（M20），这类写法几乎必然出现。

理论上可以把这些自动生成的名字逐个登记，再配 `.witness`，私有名还要写 `«0»`。但名字随 Lean 版本漂移，不现实。所以判为硬伤：属实，且会大面积阻塞 W3。修法是按 Lean 的辅助名谓词（`isAuxRecursor`、`Lean.Meta.isMatcher`、`isPrivateName` 加 `_proof_` 后缀、`isReservedName` 的扩展、`_flat_ctor`、`ctorIdx` 等）过滤，或改为只认带 `findDeclarationRanges` 的常量。

### R2-B5：refines 强求结构参数为 Sort（误杀部分为真病灶，`False` 字段部分成立）

**静态机理。** `EnvGates.lean:177-178` 要求结构的所有参数的类型都 whnf 成 Sort，否则 `refines` 直接返回 false，精化定理就永远登记不上。

**实跑一：误杀**（`fx/b5kill`）。`structure Above (P : Type) [LT P]` 和 `structure Bounded (k : Nat)` 各自配了形状完全正确的精化定理，门 7a 仍然 exit=1，两者都报 FREE_PREDICATE。

这里用 `[LT P]` 代替 `[LinearOrder P]`，机理相同：实例参数的类型不是 Sort。这种红没有任何台账出口，是**永久红**。总计划 FM-MASTER-PLAN-v2 第 329 行本身就写了 `{P : Type} [LinearOrder P]` 的定义风格，所以 W3 的 Defs 结构几乎必然带类型类参数，属硬伤。

**实跑二：空结构**（`fx/b5vac`）。`structure Bogus` 带字段 `bot : False`，精化定理 `:= False.elim e.bot`，门 7a exit=0。

这一点机理属实：`refines` 只检查精化定理类型的形状，不检查结构能否构造。但更一般地说，任何矛盾字段（如 `h : x < x`）都有同样效果，所以这属于设计层的缺口，不是单点 bug。可以要求结构提供一个居留见证（类似门 9），从而低成本地补上。判部分成立。

### R2-B6：门 10 漏检与误杀（部分成立）

**实跑**（`fx/b6`，Chan/Defs 只用 core，无 Mathlib），门 10 exit=1：

| 定义 | 输出 | 评价 |
|---|---|---|
| `invR q := q⁻¹`（`Inv.inv`，`0⁻¹ = 0`） | 无 | 漏检，成立 |
| `invRaw q := Rat.inv q` | 无 | 漏检，成立 |
| `firstD l := l.headD 0` | 无 | 漏检，成立。与已计入的 `getD` 口径不一致 |
| `lastD l := l.getLastD 0` | 无 | 漏检，成立 |
| `rate (dx dt : Rat) (_h : 0 < dt) := dx / dt` | SIGNOFF_MISSING Rat.div | 误报，成立 |
| `irate (dx dt : Int) (_h : 0 < dt) := dx / dt` | SIGNOFF_MISSING Int.div | 误报，成立 |
| `srate (dt : {q : Rat // 0 < q}) := dx / dt.val` | SIGNOFF_MISSING Rat.div | 误报，成立 |
| `neRate (_h : dt ≠ 0)` | 无 | 对照：`≠ 0` 守卫被识别 |
| `rawRate`（无守卫） | SIGNOFF_MISSING | 对照：应报 |
| `natRate (_h : 0 < b)`（Nat） | 无 | 对照：Nat 的 `0 < b` 被识别 |

**机理。** `guards`（`EnvGates.lean:542-556`）只对 Nat 接受 `0 < b` 和 `1 ≤ b`；`operation` 的名单里没有 `Inv.inv`、`Rat.inv`、`headD`、`getLastD`。

**评价。**
- 漏检是实在的缺口，补名单的成本很低。`Inv.inv` 尤其重要，旧仓 `formal/` 中 `⁻¹` 出现 27 次。
- 「误杀」与 B5 性质不同：门 10 是签注计数门，补一条 `garbage-signoffs.yaml` 签注就能转绿，不是永久红。不过 Int、Rat 上的 `0 < dt` 恰恰是价格和时间差的自然写法，噪声会很高，建议把守卫识别推广到有序类型上的 `0 < b`。
- 综合判部分成立：漏检属实，「误杀退 1」的措辞夸大了严重度。

### R2-B7：8a 七类绕过与 7b「崩溃」（部分成立）

**8a 实跑**（`fx/b7a`，导入 `Mathlib.Basic.ExistsUnique`），门 8a exit=1，只有三个对照报红：
- `m0`：`(h : ∀ n : Nat, P n) (k) : P k`，PREMISE_INSTANCE
- `u0`：`∃! y, y = f x`，FUNCTION_GRAPH
- `u4`：`∃ y, y = f x ∧ ∀ z, z = f x → z = y`，FUNCTION_GRAPH

下面 8 个变体**全部未报**：

| 编号 | 写法 |
|---|---|
| m1 | `(h : x = 1 ∧ 0 = 0) : x = 1` |
| m2 | `(h : x = 1 ∧ x = 1) : x = 1` |
| m3 | `(h : ∀ n : AliasNat, P n) (k : Nat) : P k`，其中 `def AliasNat := Nat` |
| m4 | `(h : ∀ n, P n ∧ Q n) : P k` |
| m5 | `(h : ∀ p : Nat × Nat, P p.1) : P k` |
| u1 | `… ∀ z, z = f x → id z = y` |
| u2 | 唯一性合取的左右次序对调 |
| u3 | `∃! y, y = f x ∧ 0 = 0` |

**机理。**
- `premiseInstance` 用 reducible 透明度比较，并且不拆 `And` 前提；
- `stripTrue` 只剥 `True`；
- `functionGraph` 对目标 `z = y` 做的是语法比较，并且固定了合取的次序。

**评价。** 镜像前提和平凡唯一性的检测在一般情形下是开放问题：任何有限模式表都能被重言式混淆绕过，这部分属于「静态门禁无法穷尽」。但 m3、m4、u2 等是相当自然的写法，花很少的成本就能收窄：
- 拆 `And` 前提；
- 用 default 透明度比较；
- 合取次序无关化；
- 或者对每个前提跑一个固定的弱战术（如 `simp_all`/`tauto` 限时），看它能否单独推出结论。

所以判部分成立：现象属实，但它不是「规格承诺被违反」级别的硬伤。README 对 8a 的承诺只是「实例与结论定义相等即硬红」。

**7b 实跑**（`fx/b7b`）。Chan/Hypotheses 中定义普通 `inductive PullbackInd (n : Nat) : Prop | mk : D n = 1 → …`，Thm 用 `cases` 证明，about 为 D。门 7b **exit=2**，stderr：`未获准展开的依赖 PullbackInd 隐藏了具体定义`。

这不是崩溃，而是 `expand` 主动 `throwError` 后被 `Audit.main` 捕获，返回「无法判定」，属于有意的 fail-closed。但 README 写的是「归纳式命名假设保留名义接口重放」，而代码（`EnvGates.lean:446-456`）只对 `getStructureInfo?` 命中的**结构**建立名义接口。普通的 Prop inductive 在 Hypotheses 中很自然（多构造器的假设族就只能这样写），这时 7b 会恒退 2 并阻塞合入。所以这一子项判为与文档不符的真缺口，但「崩溃」的定性不对。

## 3. 审阅者漏掉或说错的地方

1. **B1 少说了一层。** 未闭合的 `"` 不会触发 `Undetermined`，词法器没有任何自检。此外，`--wfail` 构建通过并不能兜底，因为被隐藏的 `set_option` 本身就是用来消灭警告的。
2. **B3 的 c4 说错。** 同通道的私有 helper 会被 8b 单独抓到，整体退 1；只有把 helper 移出节点通道才会退 0。另外，8b 本质上是启发式，审阅者没有区分「可归一消除的死用法」和「不可穷尽的死用法」。
3. **B4 少列了 `Dir.ofNat_ctorIdx`**（`deriving DecidableEq` 生成）。另外，审阅者没有指出自测为什么没发现这个问题：g7a 的绿夹具只覆盖非命题 def。
4. **B6 的「误杀」是可签注消除的红**，与 B5 的永久红不是一个等级，审阅者混为一谈。
5. **B7 的 7b「崩溃」定性错误。** 实际是有意的 fail-closed 退 2。真正的问题是名义接口只覆盖 structure，与 README「归纳式命名假设」的表述不一致。
6. **审阅者未提但值得一并处理：**
   - 6a 声明锁不覆盖 Chan.Thm 的陈述，所以 B2 这类包装式陈述在锁层面也拦不住。如果按设计 Thm 陈述只由证明者负责，那么 7a/8a/8b/9 就是唯一的机械防线，B2 的修补优先级应当上调。
   - 139/139 的自测矩阵里，B4 和 B5 的真实写法（类型类参数结构、派生、良基递归）一个都没有，建议各补绿夹具作为回归锁。

## 4. 总体结论

七项中：
- **B1、B2、B4、B5（误杀部分）是真病灶**。其中 B4 和 B5 会在 W3 的真实代码里大面积、甚至永久误杀，B1 和 B2 是修补便宜的实现漏洞，四项都足以维持 BLOCK。
- **B3、B6、B7 部分成立**：机理和读数属实，但部分属于启发式门禁无法穷尽的对抗混淆，或者属于可签注消除、fail-closed 的情形，审阅者对严重度和定性有夸大或误述。

建议的返修优先级：
1. B4（辅助名过滤）
2. B5（refines 放开非 Sort 参数，只要求结构参数与定理前缀一致）
3. B1（改用 Lean 前端枚举命令，或至少支持插值并让未闭合引号 fail-closed）
4. B2（default 透明度展开头部并剥 `True ∧`）
5. 7b 支持非结构的命名假设 inductive
6. B6 补名单、推广有序守卫
7. B3/B7 的 8a/8b 做低成本加强，并在文档里写明它们是启发式
