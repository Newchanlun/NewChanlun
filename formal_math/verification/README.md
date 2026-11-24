# FM-04 数学包门禁

从仓库根目录运行：

```sh
source scripts/fm_env.sh
python3 formal_math/verification/run_gates.py --repo-root . --gate 3
python3 formal_math/verification/selftest.py
```

门禁退出码为 **0 绿、1 红、2 无法判定**。红行格式为
`GATE<编号> RED <文件>:<行或声明名> <代码> <说明>`；诊断和工具错误写到标准错误。Python 入口需要 3.11 或更新版本，仅用标准库。

不指定编号时，`--stage decl` 跑声明期专用门 7a、8a、10，`--stage proof` 跑证明期专用门 7b、8b；两期都跑其余门。默认 `--stage all` 跑全部。显式 `--gate` 只跑所选门。

- **1、2**：逐项比对工具链和九个依赖的修订；读取 Lake 选项、扫描局部覆盖并实际运行 `lake build --wfail`。
- **3**：忽略注释与字面量，扫描禁用记号；用 Lake 构建源码模块，运行 `fm_audit`。审计先读一个私有定理的证明体，再按环境中的模块归属枚举常量，从内核中的类型和定义或证明体现算公理闭包。若文本已判红，只构建并读取独立探针，不构建故意写坏的文件。
- **6a 声明锁**：按模块归属枚举 Defs、Hypotheses、Audit/Literal、ChanChallenge 的常量，含私有声明。对常量全名、宇宙参数个数、内核类型和定义体生成 `FM-lock-v1` JSON 数组（定理不收证明体）；绑定变量用 de Bruijn 编号、宇宙形参用次序编号，不收元数据。逐项比对紧凑 UTF-8 序列化的 SHA-256；多、少、变均硬红。
- **6b 路径权限**：比较已提交差异、暂存区与工作树。基线通常是与 `origin/main` 的共同祖先；若 #2312 已验收的布局提交严格介于共同祖先和当前 HEAD 之间，则从该提交接续。没有分支特批，只有 `decl/` 能改声明锁。本地符号引用优先；分离 HEAD 用 `GITHUB_HEAD_REF`，缺失返回 2。
- **7a 定义依赖声明**：从环境枚举 Thm、Proofs、Exec、ChanChallenge 中的定理；缺 `about` 或 `mode`、模式无效、`about` 指向不存在的常量均硬红。Defs 结构中的自由 `Bool` 或 `Prop` 字段（含返回两者的字段）需要登记精化定理；定理结论用等式、等价或其合取，把每个判据接到原始数据，而非另一个自由判据。
- **7b 抽象诊断**：对登记为依赖具体定义的定理，把所列 D 在类型、原证明、命名假设和获准辅助接口中一致替换为任意同类型参数。若临时内核环境接受，硬红 `GENERALIZES`。类型重放被拒绝只记「该证明未推广」；读不到证明、依赖无法展开或超时返回 2。没有向工程环境写入声明。
- **8a 形状检查**：打开望远镜，从定理的数据参数给每个全称前提选类型匹配的实例。实例与结论在可约透明度下定义相等，硬红 `PREMISE_INSTANCE`。标记为声明式唯一性的节点，若结论只是 `∃! y, y = t` 或 `∃! y, t = y`（`t` 不含 `y`），硬红 `FUNCTION_GRAPH`。
- **8b 必要前提**：逐个删去 `necessary` 中的前提，用原证明项在临时内核环境里重放；接受才硬红 `DROPPABLE_PREMISE`。后续参数或结论类型仍依赖该前提时只记录不能直接删去；其他未列前提不参加此项诊断。
- **9 联合证据**：从同一望远镜生成一个存在命题，按绑定顺序把数据量化、把前提合取（依赖前提证明的后续类型仍绑定在同一存在链）。在 ChanTest 找 `<全名>.witness`。若 `needs_necessity` 为真，再找 `<全名>.without_1` 等逐前提的反例，要求其余前提与结论的否定同时成立；序号从 1 起，只数命题前提。缺见证或类型不定义相等均硬红。若删去前提后无法构造闭反例命题，返回 2。
- **10 垃圾值**：在 Defs、ChanChallenge 的声明类型及定义体计数自然数减法、无正除数证据的自然数除法、`head!`、`get!`（包括 `getElem!`）、`getD`、`Inhabited.default`、`Finset.sup`、`Finset.inf`、`sSup`、`sInf`。返回 `Option` 的安全接口（如 `head?`）不在风险运算表内。按声明和运算逐项比对签注；缺签注或多签注均硬红。
- **15**：检查首条命令、导入、定义区段；将源码中的导入边与 Lake 模块图对照，并检查到 `ChanExplore` 与从 `Chan.Final` 出发的受限传递路径。
- **自测**：将每个夹具覆盖到 `TMPDIR` 下的独立最小包，调用真实入口，逐例比对退出码与代码。6b 夹具真实创建 Git 分支或分离 HEAD；3 的 `private-proof` 夹具还校验报告定位到 `_private.` 声明。环境夹具仅在临时包里编译。

## 登记一个待验节点

`formalization.yaml` 与 `verification/garbage-signoffs.yaml` 使用 YAML 1.2 的 JSON 子集，键不能重复。空台账使用 `{}`，原有 `[]` 也表示无节点。下面的节点登记既要求 7b 重放，也要求 9 提供逐前提反例：

```json
{
  "nodes": {
    "Chan.step": {
      "about": ["Chan.transition"],
      "mode": "依赖具体定义",
      "helpers": ["Chan.stepAux"],
      "necessary": ["hLegal"],
      "needs_necessity": true
    }
  },
  "refinements": {"Chan.Endpoint": "Chan.endpointCriterion"}
}
```

`mode` 的另一取值是「对任意实现成立」。`helpers` 写允许展开的常量全名，缺省为空；多个 `about` 对象按依赖顺序登记。`necessary` 写 8b 要删的绑定名；仅作说明的前提不要列入。对声明式唯一性设 `"declarative_unique": true`。私有定理见证保留 `_private`、模块名和数字组件，Lean 源码里将数字写成 `«0»` 这样的标识符。签注按声明、运算键、次数登记，例如 `{"Chan.gap":{"Nat.sub":{"count":1,"review":"#票号／独审记录"}}}`。

## M-4：跨模块计算需要暴露定义体

在 Lean **4.36.0**（`611c117bfaf7b7ae1cfcf246ce6fba31e8f509e9`）上编译红夹具
[`g15/no-expose`](must_red/g15/no-expose)：`Chan/Defs/Flag.lean` 只写
`public section`，定义 `probeFlag : Bool := true`。定义文件退出 0；使用文件导入定义后执行
`example : probeFlag = true := by decide`，退出 1，编译器原文：

```text
ChanTest/UseFlag.lean:5:33: error: Tactic `decide` failed to reduce
  @decide (probeFlag = true) (instDecidableEqBool probeFlag true)
to `true` or `false`.

After unfolding the instances `instDecidableEqBool` and `Bool.decEq`, reduction got stuck at
  probeFlag
```

[`g15/expose`](must_green/g15/expose) 只把定义区段换成 `@[expose] public section`，两文件均退出 0。因此保留门禁 15 的 M-4 检查。复测时将任一夹具的 `formal_math/` 内容和包的 `lean-toolchain` 复制到 `TMPDIR` 下，进入该目录，设置 `LEAN_PATH=$PWD`，分别运行：

```sh
lean -o Chan/Defs/Flag.olean Chan/Defs/Flag.lean
lean ChanTest/UseFlag.lean
```

## 读证明体：加载私有层，不能只读公共分片

用仓内探针 `ChanTest.Probe` 实测：

| 通道 | `_private.ChanTest.Probe.0.gateProofProbe` |
| --- | --- |
| 审计模块 `import all ChanTest.Probe` 后查询环境 | 名称、证明体都可读；打印为 `of_decide_eq_true (id (Eq.refl true))` |
| `Lean.readModuleData` 只读取基础 `.olean` | `constNames` 不含该私有名称 |
| `Lean.importModules (level := .private)` 直接加载模块对象及分片 | 名称、完整证明体都可读 |

门禁选第三条：它可一次加载本轮从源码发现的模块，不需要维护静态审计导入清单。私有层缺失或探针的证明体取不到，返回 2；成功加载后，私有定理对占位公理的依赖报 `ENV_SORRY`。
