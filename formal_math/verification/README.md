# FM-04 数学包门禁

从仓库根目录加载钉选工具链后，可单查一门，或在声明封存时运行声明期组合：

```sh
source scripts/fm_env.sh
python3 formal_math/verification/run_gates.py --repo-root . --gate S
python3 formal_math/verification/run_gates.py --repo-root . --stage decl
python3 formal_math/verification/selftest.py
```

退出码为 **0 绿、1 红、2 无法判定**；CI 不接受 2。红行格式是
`GATE<编号> RED <文件>:<行或声明名> <代码> <说明>`。诊断写到标准错误。
`--stage decl` 加跑 7a、S、8a、10；`--stage proof` 加跑 7b、8b；
默认 `all` 跑两期。显式 `--gate` 只查所选门。门禁重算源码、Git 差异及本轮构建的 Lean 环境，不读回报告。

## 硬门

| 门 | 机械承诺 |
|---|---|
| 1 钉选 | 文件中的工具链、运行中的 Lean 与九个依赖的修订须符合钉选。 |
| 2 零告警 | 受控选项不得在源码或 Lake 目标中覆盖；`lake build --wfail` 构建默认目标和源码发现的模块（包括未被聚合文件导入的子模块）。 |
| 3 可信源码与环境 | 源码须符合下节命令白名单，整树不能有禁用项、战术及属性。环境对有源码范围的常量检查 `unsafe`、`partial`、`implemented_by`、`extern`；公理及公理闭包检查覆盖全部常量，包括私有项和无范围的生成项。包内不能声明公理，闭包只接受 `propext`、`Classical.choice`、`Quot.sound`。 |
| 6a 声明锁 | Defs、Hypotheses、Audit/Literal、ChanChallenge 按环境中的模块归属枚举，含私有声明。 `FM-lock-v2` 以序号表达绑定变量和宇宙参数，编码声明类别、可约性、类型与非定理的定义体。锁集多、少、变均红。 |
| 6b 路径权限 | 分别核对提交、暂存区与工作树的变更；不让差异相消。声明锁及非空签注由 `decl/` 维护；`infra/` 只能初始化空签注。分离 HEAD 用 `GITHUB_HEAD_REF`，缺失退 2。 |
| S 陈述范式 | 可信目录手写命题陈述的骨架只接受全称／蕴含、`And`、`Or`、`Not`、`Iff`、`Exists`、`ExistsUnique` 或原子。未锁定的项目命题别名先展开；原子以局部变量或声明末端字面为 `Prop` 的常量为头。不在骨架上用 `if`、`match`、`id`、投影或取默认值包装命题；`True` 及不含外层绑定变量的闭命题不能作前提或合取项。数据项不受骨架限制。 |
| 7a 定义依赖与居留 | 节点缺 `about`／`mode`、模式非法或所列常量不存在均红。Defs 的自由 `Bool`／`Prop` 判据要求精化定理：前缀逐个符合结构参数域，绑定种类不限，随后只绑定一个结构项；等式、等价或其合取把完整判据接到该项的原始数据。含命题字段的结构另需 ChanTest 中闭的具体实例（直接给出值，或给出 `Nonempty` 证明）。 |
| 9 联合证据 | 从范式望远镜逐个绑定数据，把前提联合为一个命题；ChanTest 须给出同类型的 `<全名>.witness`。主定理逐个登记必要或便利前提，必要前提还需 `<全名>.without_i`：在同一存在链满足其余各前提并否定结论。 |
| 10 垃圾值 | 从 Defs、ChanChallenge 的类型和非定理定义体计数，按签注逐项对账：除、模、逆，Nat 减法／前驱，带回退值或以 `!` 结尾的取值，`Inhabited.default`，不带撇的确界，以及 `panic!`。除法守卫只接受同一除数上的作用域内证据、同一结构字段或带证明的子类型；识别有序类型的 `0 < b` 和 `b ≠ 0`。安全查询如 `head?` 不计，`head!` 的元素是 `Option` 也照计。 |
| 15 模块边界 | 首条命令为 `module`；导入不能越过目录的直接或传递边界，不能整库导入 Mathlib。只有审计工具可 `import all`。Defs 须写 `@[expose] public section`，公开可计算定义也须真的有公开定义体。 |

### Lean 4.36.0 源码白名单

`fm_audit headers` 用 `Parser.parseHeader` 读取模块头和导入；`fm_audit source` 用加载本轮依赖后的 Lean 前端逐条解析、检查、再精化命令。解析或导入加载失败退 2；语法有效而声明精化被编译器拒绝时，门 2 报构建红、其余门不能加载该环境。已经发现硬反例时不执行禁用命令。Python 只编排这些步骤并核对 Lake 导入图。

单查一个文件的源码阶段：`lake exe fm_audit source Chan.Defs.Example Chan/Defs/Example.lean 3`（从 `formal_math/` 运行）。最后一项可选，可填 `2`、`3` 或 `15`；明确门编号时，源码阶段与 Python 调用方用同一退出码。模块依赖顺序、导入方向与环境检查仍由整门入口编排。

本机枚举后钉选的顶层命令 kind（以下省去共同前缀 `Lean.Parser.Command.`）：

- `moduleDoc`、`namespace`、`section`、`end`、`open`、`variable`、`universe`、`include`；
- `declaration`，其子类只接受 `definition`、`theorem`、`abbrev`、`opaque`、`example`、`inductive`、`structure`、`instance`；
- `mutual`、`in`（内部命令仍按同表验），`set_option`（只允许 `maxRecDepth`、`maxHeartbeats`、`pp.*`），`check`；
- `eval` 仅 `ChanExplore`；`Lean.guardMsgsCmd` 仅 `Chan/Final`。

禁用的构造在项、战术、修饰符及属性语法树里同样检查，包括 `sorry`、`admit`、`native_decide`、`unsafe`、`partial`、`extern`、`implemented_by` 及局部受控选项。审计工具允许元编程，不允许占位证明。

### 节点来自声明范围，不按名字猜

门 7a、9 在 Thm、Proofs、Exec、ChanChallenge 枚举**有 Lean 源码声明范围、类型为命题、且种类为定理、定义或 opaque** 的常量。结构字段投影、构造器、递归子和归纳类型不算节点。用 Lean 4.36.0（`611c117b`）按审计实际路径以 `.private` 加载夹具对象，逐个读取 `findDeclarationRangesCore?`：

| 写法 | 有范围 | 无范围的代表项 |
|---|---|---|
| `deriving DecidableEq, Repr, Ord` | `Dir`、手写构造器、派生实例及 `instReprDir.repr`、`instOrdDir.ord`；这些类型都不是命题 | `instDecidableEqDir._proof_1/_proof_2`、`Dir.ofNat_ctorIdx`、`Dir.ctorIdx`、`Dir.ctorIdx._impl` |
| `termination_by`／`decreasing_by` | `countdown` | `countdown._proof_1`、`countdown.eq_def`、`countdown._unsafe_rec` |
| 模式匹配的结构递归定理 | `recThm` | `recThm._f`、私有 `recThm.match_1_1` |
| `where`、`let rec` | 外层声明和手写的局部助手；私有名称也查到 | 局部递归助手的 `_f` |
| `mutual` | 两个手写定理 `mutualA`、`mutualB` | 两个 `_f` 及私有匹配辅助项 |
| 命题类与 `instance` | `Pos.mk`、`Pos.pos`、命名及匿名实例 `posOne`、`instPosOfNatNat` 都是命题常量 | `Pos.mk._flat_ctor` |

原样 b4 无须为 `Pos.mk` 或 `Pos.pos` 登记或写见证；b5kill 原件没有居留见证，故为红，自测另保留补闭项的绿样。

门 3 不会把无范围的 `Dir.ctorIdx`（带 `implemented_by`）与 `Dir.ctorIdx._impl`（带 `unsafe`）当成手写禁用构造。这个区别依赖门 2、3 的源码命令白名单：用户代码不能绕开源码声明直接造常量；安全定理不能引用 `unsafe` 常量，全部常量仍检查公理闭包，包括 `sorryAx`、`Lean.ofReduceBool` 和 `Lean.trustCompiler`。手写 `unsafe def` 和 `@[implemented_by]` 在源码层与环境层均有必红夹具。

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

此处需提供 `Chan.step.witness` 和 `Chan.step.without_1`；第 2 前提进入门 9 的独审清单。辅助引理不用给逐前提登记；旧台账中的 `needs_necessity` 仍要求所有反例。私有定理见证保留 `_private`、模块名和数字组件，Lean 源码中将数字写作 `«0»`。签注样例：`{"Chan.gap":{"Nat.sub":{"count":1,"review":"#票号／独审记录"}}}`。

## 启发式门：红必带证书，绿不代表安全

| 门 | 能签发的红证书 | 绿仍待检查 |
|---|---|---|
| 7b 抽象诊断 | 一致替换陈述、辅助接口、原证明中的具体定义后，内核接受泛化命题。 | 保留与具体定义绑定的 Hypotheses 归纳名义接口（含多构造器）时不签发正证书；内核拒绝也不证明依赖必要。不获准展开的普通依赖、无法读取或超时退 2。 |
| 8a 形状诊断 | 拆开前提合取，用默认透明度以元变量实例化全称前提；得到与结论定义相等的实例即 `PREMISE_INSTANCE`。展开 `ExistsUnique` 后，按任一合取顺序识别裸等式函数图，记 `FUNCTION_GRAPH`。 | 不为投影反向构造积类型见证，不用逻辑等价证明去化简重写过或重复的函数图，亦不做任意命题搜索。声明式唯一性用 `declarative_unique: true` 登记。 |
| 8b 未用前提 | 全树做 beta、eta、zeta、投影归约并内联未锁定的项目证明体。删前提后重建类型并由内核接受原证明，才报 `DROPPABLE_PREMISE`。 | 不替换锁定证明，不为依赖删除项的后续类型或剩余证明另找证明。旧台账中附理由的 `doc_only` 保留豁免。 |

`known_limits/` 的案例期望对应启发式门为绿，并写明限制的封口：范式 S、门 9 的必要性反例或非作者审阅。

## 自测与构建

自测把每个夹具装入独立最小包，重算退出码、代码和指定声明名。macOS 上夹具与子进程临时文件都放在 `/Volumes/AgentStorage/fm/tmp/`；Linux 上用 `TMPDIR`。夹具结束时删除独立的 `.lake/build` 和临时文件，不清理共享预编译包。报告分开计数 `must_red`、`must_green`、`must_unknown`、`known_limits`。紧凑复跑可传门编号；macOS 内置盘低于 6 GiB 时停止派发，默认串行。

门 3、7b、8b 装载 `.olean` 私有分片，并先读 ChanTest 的私有探针证明体；可见性不足返回 2。原先用 `import all` 也读到了探针正文，但只读基础 `.olean` 拿不到这个私有名称。

M-4 的本机实测：定义只写 `public section` 时，跨模块 `decide` 卡在不可展开的 `probeFlag`；改成 `@[expose] public section` 后，同一计算通过。对应夹具是 [no-expose](must_red/g15/no-expose) 和 [expose](must_green/g15/expose)。
