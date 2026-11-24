# FM-04 第一片门禁

从仓库根目录运行：

```sh
source scripts/fm_env.sh
python3 formal_math/verification/run_gates.py --repo-root . --gate 3
python3 formal_math/verification/selftest.py
```

门禁退出码为 **0 绿、1 红、2 无法判定**。红行格式为
`GATE<编号> RED <文件>:<行或声明名> <代码> <说明>`；工具或环境错误写到标准错误。本片五道门在声明期和证明期均运行。Python 入口需要 3.11 或更新版本，仅用标准库。

- **1、2**：逐项比对工具链和九个依赖的修订；读取 Lake 选项、扫描局部覆盖并实际运行 `lake build --wfail`。
- **3**：忽略注释与字面量，扫描禁用记号；用 Lake 构建源码模块，运行 `fm_audit`。审计先读一个私有定理的证明体，再按环境中的模块归属枚举常量，从内核中的类型和定义或证明体现算公理闭包。若文本已判红，只构建并读取独立探针，不构建故意写坏的文件。
- **6b**：从当前分支与 `origin/main` 的共同祖先计算已提交差异，再检查暂存区和工作树。对依赖 FM-02 的 #2312 第一片，若共同祖先早于简报指定的 FM-02 提交，就以该提交为基线。本分支仅额外放行交付物所需的冒烟、测试库和台账路径；声明锁只准初始化为空对象。一般 `infra/` 分支不能改声明锁。
- **15**：检查首条命令、导入、定义区段；将源码中的导入边与 Lake 模块图对照，并检查到 `ChanExplore` 与从 `Chan.Final` 出发的受限传递路径。
- **自测**：将每个夹具覆盖到 `TMPDIR` 下的独立最小包，调用真实入口，逐例比对退出码与代码。6b 夹具真实创建 `proof/` 分支并提交差异。3 的 `private-proof` 夹具还校验报告定位到 `_private.` 声明。

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
