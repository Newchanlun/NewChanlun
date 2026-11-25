# NewChanlun 地图 #2293 / 票 #2312（FM-04）机械门禁独立跨家族审阅报告

- **审阅工位**：Gemini 4 Neon（跨家族独立非作者审阅，作者为 GPT-6.2 Sol）
- **审阅日期**：2026-11-24
- **被审分支与精确提交**：`origin/infra/2312-b-env-gates` @ `cd4b6c301d2f02847dd30da9db6a2e2e96e03e8a`（基线 `38f65e920a`，叠加第一片 `c97fe37cdf`）
- **被审工作树（只读）**：`/Users/silencehan/.t3/worktrees/NewChanlun/infra-2312-b-env-gates-2428b08ce810d112`
- **对照基准**：
  - GitHub Issue `#2312` 评论「门禁数据形状（主控定稿，实现以此为准）」（2026-11-24）
  - GitHub Issue `#2312` 评论「数据形状补充（第二份 Astra 审计，供第二片使用）」与「主控验收第一片：通过」
  - 总计划 `/Volumes/AgentStorage/fm/r2/orig_fm09/FM-MASTER-PLAN-v2.md` §2.2、§2.3、§3.2
- **审阅结论**：**`VERDICT: BLOCK`**（绑定精确 head `cd4b6c301d2f02847dd30da9db6a2e2e96e03e8a`）

---

## 一、执行摘要与结论

在精确 head `cd4b6c301d2f02847dd30da9db6a2e2e96e03e8a` 上，独立复跑 `lake build --wfail`（3,537 项）、`lake build fm_audit`（8 项）、12 道门禁逐门及三阶段执行、以及 102 个自测夹具（`selftest.py`）**全部退出码为 0**。实现在多个核心基础架构上打底扎实：

- 门 3 环境层改用 `Lean.importModules (level := .private)` 并在 `CollectAxioms.collectAndGet (fun _ _ => none)` 下禁用预存公理缓存、从内核 `env.checked.get` 现算公理闭包，实测即使绕过文本层也能可靠兜住 `partial`、`unsafe`、`extern`、`implemented_by`、`axiom` 与 `_private.` 中的 `sorryAx`；
- 门 6b 正确实现本地符号引用优先、分离 HEAD 读取 `GITHUB_HEAD_REF`、两者皆无退出码 `2`；
- 门 7b 正确处理 Astra 经典定义展开例（`def D n := n = 0; theorem t : D 0 := Eq.refl 0` 记注「该证明未推广」且退出 `0`，不误杀），并对未获准隐藏依赖退出 `2`；
- 门 9 使用联合存在链生成见证与逐前提反例命题，且支持多态类型参数 `{P : Type} [MyOrd P]`。

但经静态代码审计与独立沙箱对抗实测（共执行 50+ 组对抗实验，脚本与原始日志留存于 `/Volumes/AgentStorage/fm/r2/2312-review-tmp/`），**在 12 道门中检出 10 类阻断级（BLOCK）缺陷**，涵盖可直接伪造绿灯的硬绕过漏洞、与定稿及 Astra 补充口径的直接冲突、以及必然触发的误杀/流程死锁：

1. **门 1 漏查运行期 Lean 版本**（违背 Astra 补充 #4，实测假冒 `lean --version 4.35.0` 返回 `0`）。
2. **`run_gates.py:49` `LEX` 词法器原始字符串脱同步漏洞**（`r(?P<hash>#+)?"..."(?P=hash)` 导致无 `#` 的合法 `r"\"` 反转引号边界），实测**一举击穿门 2（压制 `linter.unusedVariables`）、门 3（注入 `#eval`/`syntax`/`macro_rules`）、门 15（字符串内伪造 `@[expose] public section` 绕过 M-4）**。
3. **门 2 三处构建与配置绕过**：真实 `formal_math/lakefile.toml` 的 `Chan` 库未设 `globs = ["Chan.+"]` 导致未导入子模块即使有编译错误也判绿；未查 `[[lean_lib]]` 级 `leanOptions` 覆盖；未禁源码内 `set_option relaxedAutoImplicit`。
4. **门 7a/7b/8a/8b/9 定理枚举漏洞与误杀**：`node` 仅收 `.thmInfo`，用 `def` 代替 `theorem` 写命题证明可一键绕过五道环境门禁；同时 `Chan/Exec` 定义普通 `structure` 会因编译器自动生成的 `mk.inj`/`mk.injEq`/`sizeOf_spec` 被门 7a/9 误杀。
5. **门 7a 精化定理校验可被伪造**：未要求对全称 `e : Struct` 成立且未排除 `Empty` 等空数据参数，原封不动的旧库病灶 `BspEndpoint`（四个自由 `Bool`）配一个 `dummy` 字面量 `rfl` 定理或 `Empty` 参数 `nomatch` 定理即可返回 `0`。
6. **门 8a / 门 9 `forallTelescope` 不展开 `abbrev`/`def`**：用 `abbrev` 包装全称实例化或前提矛盾的空真定理即可直接绕过门 8a 与门 9（仅需 `True := trivial` 且跳过全部 `needs_necessity`）；门 8a 同时存在带 `Prop` 守卫的全称前提漏检与 `ExistsUnique` 多种平凡绕过（`∧ True`、`abbrev`、`id y`）。
7. **门 8b 默认全跳过（反转规格）+ eta-收缩证明项假绿灯**：`necessary` 为空即跳过违背定稿「默认全检、仅作文档才豁免」；且即使填入 `necessary`，Lean 常见的 eta-收缩证明项经 `body.beta xs` 会留下自由变量触发 `declHasFVars` 被当成不可删，直接放行旧库 `divergence_creates_bsp` 病灶。
8. **门 6a `opaqueInfo` 提前 `return` 编码 bug**：`EnvGates.lean:69` 误写 `return` 丢弃 `FM-lock-v1` 头、常量全名、宇宙参数个数和 `info.type`，实测修改 `opaque` 类型或改名后 SHA-256 逐比特不变、门 6a 返回 `0`；且未区分 `def`/`abbrev` 与 `theorem`/`axiom`。
9. **门 15 导入方向表四条绕过隧道（同时击穿门 6a 依赖面隔离）**：非 `Chan*` 顶层中转模块让 `Chan/Defs` 间接导入 `ChanDyn`；`ChanChallenge` 经 `Chan/Audit/Literal` 传递导入未锁定的 `Chan/Proofs`；`Chan.lean` 直接导入 `ChanDyn`；空 `@[expose] public section` 绕过 M-4；普通源码写 `import all` 打破 `module` 封装被静默放行。
10. **门 6b / 10 声明期流程死锁 + 门 7b 遇 `Chan/Hypotheses` 结构崩溃（退出码 2）+ 门 10 漏检/误杀**：`decl/` 分支更新 `verification/garbage-signoffs.yaml` 被门 6b 拦截；`Chan/Hypotheses` 按总计划写全 `Prop` `structure` 使门 7b 报 `不能展开辅助接口` 返回 `2`；门 10 对返回 `Option` 的 `head!`/`getD` 静默豁免、对 `Int`/`Rat` 总化除零与 `Nat.pred`/`panic!`/`getLast!` 漏检，并对合法 `dt ≠ 0`、`dt + 1`、`{ n : Nat // 0 < n }` 误杀。

---

## 二、精确 head 独立复跑实证（必做项 1）

在只读工作树 `/Users/silencehan/.t3/worktrees/NewChanlun/infra-2312-b-env-gates-2428b08ce810d112` 中复跑（全过程 `TMPDIR=/Volumes/AgentStorage/fm/tmp`，内置盘可用空间复跑前 15 GiB、复跑后 13 GiB，远高于 6 GiB 停线；原始日志见 `/Volumes/AgentStorage/fm/r2/2312-review-tmp/rerun.log`）：

| 检查项 | 命令 / 范围 | 实测结果 | 退出码 |
|---|---|---|---|
| 复跑前状态核验 | `git rev-parse HEAD` / `git status --short` | `cd4b6c301d2f02847dd30da9db6a2e2e96e03e8a`，仅 `?? gpt-with-taste/` | 0 |
| 工具链实测 | `lean --version` / `lake --version` | Lean `4.36.0` (`611c117bfaf7b7ae1cfcf246ce6fba31e8f509e9`) / Lake `5.0.0` | 0 |
| 全包零警告构建 | `lake build --wfail` | `Build completed successfully (3537 jobs).` | 0 |
| 审计目标构建 | `lake build fm_audit` | `Build completed successfully (8 jobs).` | 0 |
| 逐门运行 | `run_gates.py --repo-root . --gate <n>`（1, 2, 3, 6a, 6b, 7a, 7b, 8a, 8b, 9, 10, 15） | 12 道门全部无红行、全部通过 | 全部 0 |
| 分阶段运行 | `run_gates.py --repo-root . --stage decl\|proof\|all` | 三阶段全部通过 | 全部 0 |
| 全量自测 | `python3 formal_math/verification/selftest.py` | **102 / 102** 夹具全部「通过」（红/绿/未知退出码与错误码全部匹配） | 0 |
| 复跑后状态核验 | `git rev-parse HEAD` / `git status --short` | 精确 head 与工作树零新增改动，仅 `?? gpt-with-taste/` | 0 |

---

## 三、七条共用合同核验表

| # | 共用合同要求（#2312 定稿 §0） | 核验结论 | 依据与说明 |
|---|---|---|---|
| 1 | 只收原件来源（仓根、git 现算 diff、自建 Lean 环境） | **PASS** | `run_gates.py` 仅收 `--repo-root`、`--gate`、`--stage`，不接受调用方传入报告/清单/日志。 |
| 2 | 结论每次现算，不存储，不读回旧报告 | **PASS** | `Audit.lean:26` 传 `extFind? := fun _ _ => none` 强制不信 `.olean` 预存公理缓存；所有门禁均现算。 |
| 3 | 枚举来自环境（含 `_private.`），漏列为红而非跳过 | **FAIL** | ① `EnvGates.lean:21-23` `node` 仅收 `.thmInfo`，`def` 写的命题证明被跳过（**B4**）；② `EnvGates.lean:224` 门 8b 在 `necessary` 漏列时默认跳过（**B7**）。 |
| 4 | 三值退出码（0 绿 / 1 红标准格式 / 2 无法判定） | **PASS** | 退出码语义与红行正则验证（`run_gates.py:181`）实现规范；未知异常统一归退出码 2。 |
| 5 | 能看见证明体才算查过（先读仓内探针，读不到退 2） | **PASS** | `Audit.lean:58-64` 用 `importModules (level := .private)` 并在门 3/7b/8b 先验 `_private.ChanTest.Probe.0.gateProofProbe` 证明体非空，读不到退 2。 |
| 6 | 必红样本是夹具树，复制到临时目录重算，自测进 CI | **PASS** | `selftest.py` 为 12 道门均提供 `must_red` 与 `must_green`（及 6b/7b 的 `must_unknown`）共 102 个夹具，全部复制到 `$TMPDIR` 独立运行。注意 `selftest.py:54` 统一写入 `globs = ["{lib}.*"]` 与真实 `lakefile.toml` 不一致（见 **B3**）。 |
| 7 | 分声明期与证明期（`--stage decl\|proof\|all`） | **PARTIAL** | `run_gates.py:489-490, 505-507` 正确分离 `DECL_ONLY = {"7a","8a","10"}`、`PROOF_ONLY = {"7b","8b"}`；但 `formal_math/README.md:12` 仍停留在第一片旧描述，且门 6b 阻止 `decl/` 更新门 10 的 `garbage-signoffs.yaml`（**B10**）。 |

---

## 四、逐门核验表（12 道门）

| 门 | 名称 | 复跑结果 | 审阅判定 | 核心通过项与阻断缺陷摘要 |
|---|---|---|---|---|
| 1 | 版本钉死 | 0（3 夹具全过） | **BLOCK** | 文件级工具链与 9 包 rev 比对正常；**缺运行期 `lean --version` 比对**（违背 Astra 补充 #4，**B1**）。 |
| 2 | 构建零警告 | 0（5 夹具全过） | **BLOCK** | `lake build --wfail` 本身对 `set_option warningAsError false` 有效；但存在 **`r"\"` 词法脱同步绕过 `set_option linter`**（**B2**）、**真实 `lakefile.toml` 缺 `Chan` globs 漏编未导入文件**、**未查 `[[lean_lib]]` 级 `leanOptions` 覆盖**、**未禁 `set_option relaxedAutoImplicit`**（**B3**）。 |
| 3 | 禁用构造与公理 | 0（14 夹具全过） | **BLOCK** | 环境层对 `partial`/`unsafe`/`extern`/`implemented_by`/`axiom`/`_private.sorryAx` 全部有效兜底；但 **`r"\"` 词法脱同步可彻底绕过文本层向 `Chan` 注入 `#eval`、`syntax`、`macro_rules`、`set_option linter`**（**B2**），且 `run_cmd` 未列入禁用集（Minor）。 |
| 6a | 声明锁 | 0（5 夹具全过） | **BLOCK** | de Bruijn 与宇宙参数序号归一化对 alpha 重命名不敏感、对常量语义改动敏感；但 **`EnvGates.lean:69` `opaqueInfo` 误写 `return` 提前返回丢弃名称与类型**（改类型哈希不变），且未区分 `def`/`abbrev` 与 `theorem`/`axiom`（**B8**）；跨门层面与门 15 联动导致 `Chan/Audit/Literal` 与 `ChanChallenge` 依赖面未锁住（**B9**）。 |
| 6b | 路径权限 | 0（7 夹具全过） | **BLOCK** | 分离 HEAD 读 `GITHUB_HEAD_REF`、本地符号引用优先、缺参考退 2、三阶段 git diff 均正确；但 **`decl/` 分支无法修改 `verification/garbage-signoffs.yaml` 与门 10 死锁**，且 `Chan/Proxy`、`Chan/Exec`、`Chan/Final.lean`、`ChanExplore`、`sources/` 无归属分支前缀（**B10**）。 |
| 7a | 定义依赖声明 | 0（5 夹具全过） | **BLOCK** | 能抓未登记私有定理、非法 `about`、旧版 `BspEndpoint` 与自反伪精化；但 **`refines` 可被字面量 `dummy` `rfl` 或 `Empty` 参数轻松伪造**（**B5**），**`def` 写定理绕过节点枚举**，且 **`Chan/Exec` 普通 `structure` 触发自动 `thmInfo` 误杀**（**B4**）。 |
| 7b | 抽象诊断 | 0（4 夹具全过） | **BLOCK** | 实测不误杀 Astra 经典例 `def D n := n = 0; theorem t : D 0 := Eq.refl 0`，正确捕获未获准 helper 退 2；但 **`EnvGates.lean:272-274` 强制展开 `Chan/Hypotheses` 常量导致总计划要求的全 `Prop` `structure` 假设直接崩溃退 2**（**B10**），且 `hiddenDependency` 未去重压栈有大库耗尽 fuel 风险（Minor）。 |
| 8a | 形状硬检查 | 0（5 夹具全过） | **BLOCK** | 正确捕获旧库 `main_mirror_equivariant` 与正反 `ExistsUnique` 夹具、使用局部 `FVarId` 与受控 `withReducible` 且不改状态；但 **`forallTelescope` 不展开 `abbrev`/`def` 可一键绕过**、带 `Prop` 守卫全称前提漏检、`ExistsUnique` 被 `∧ True` / `abbrev` / `id y` 轻易绕过（**B6**）。 |
| 8b | 未用前提诊断 | 0（2 夹具全过） | **BLOCK** | 确实经内核 `addDeclCore` 临时环境重放；但 **将规格 opt-out 反转为 opt-in（不写 `necessary` 直接全跳过）**，且 **eta-收缩证明项与哑 `let` 经 `body.beta xs` 产生悬空 FVar 被误判为不可删**（**B7**）。 |
| 9 | 见证与反例 | 0（4 夹具全过） | **BLOCK** | 联合存在链、拆开反例判红、多态 `{P : Type} [MyOrd P]` 见证均正常；但 **`forallTelescope` 不展开 `abbrev`/`def` 导致前提矛盾的空真定理只需 `True := trivial` 即可跳过全部见证与必要性反例**（**B6**），且受 `node` 仅枚举 `.thmInfo` 影响（**B4**）。 |
| 10 | 垃圾值检查 | 0（6 夹具全过） | **BLOCK** | 签注计数双向精确比对（缺/过期均红），且对直接 `0 < dt` 与 `1 ≤ dt` 放行；但 **返回 `Option` 的 `head!`/`getD` 被静默豁免**、**`Int`/`Rat` 总化除零与 `Nat.pred`/`panic!`/`getLast!` 漏检**、**`def Price := Nat` 包装漏扫调用点**，且 **误杀 `dt ≠ 0`、`dt + 1`、`{ n : Nat // 0 < n }`**（**B10**）。 |
| 15 | `module` 与导入方向 | 0（42 夹具全过） | **BLOCK** | 直接禁止边与 Lake 模块图核对框架良好；但存在 **非 `Chan*` 中转模块隧道**、**`ChanChallenge -> Chan/Audit/Literal -> Chan/Proofs` 隧道**、**`Chan.lean -> ChanDyn` 放行**、**空 `@[expose] public section` 及 `r"\"` 伪造绕过 M-4**、**普通源码 `import all` 放行**（**B2、B9**）。 |

---

## 五、阻断级缺陷详情（精确文件:行号 + 复现输入 + 实测证据）

所有对抗实验由 `/Volumes/AgentStorage/fm/r2/2312-review-tmp/run_adversarial.py` 与补测命令在独立沙箱运行，原始输出保存在 `/Volumes/AgentStorage/fm/r2/2312-review-tmp/adversarial.log` 与 `/Volumes/AgentStorage/fm/r2/2312-review-tmp/adversarial_fixup.log`。

### [B1] 门 1 未校验运行期 Lean 版本（违背 Astra 补充 #4）
- **位置**：`formal_math/verification/run_gates.py:86-104`
- **根因**：`gate1` 仅静态读取 `lean-toolchain` 与 `lake-manifest.json`，从未执行 `lean --version` 核对当前实际运行的工具链版本（当 `ELAN_TOOLCHAIN` 或 `PATH` 覆盖导致运行期与文件不一致时完全无感知）。
- **复现输入（Exp 1A）**：保持 `lean-toolchain` 为 `leanprover/lean4:v4.36.0`，在 `PATH` 最前放置输出 `Lean (version 4.35.0, fake)` 的 `lean` 可执行文件，运行 `run_gates.py --gate 1`。
- **实测结果**：退出码 **`0`**（假绿灯）。
- **修复要求**：在 `gate1` 中运行 `lean --version`（cwd 为 `formal_math/`），解析实际版本号（及可选 commit hash）并与 `pins.json` 钉选版本严格比对；工具缺失退 `2`，版本不符报 `RUNTIME_TOOLCHAIN_PIN` 退 `1`。

### [B2] `LEX` 词法器 `r"\"` 原始字符串脱同步，同时击穿门 2、门 3、门 15
- **位置**：`formal_math/verification/run_gates.py:48-79`（关键行 `:49`：`r'r(?P<hash>#+)?"[\s\S]*?"(?P=hash)'`）
- **根因**：Python 正则中，当可选捕获组 `(?P<hash>#+)?` 未参与匹配（即 Lean 合法的无 `#` 原始字符串 `r"..."`）时，反向引用 `(?P=hash)` **恒定失败**。结果 `r"\"` 回退匹配为标识符 `r` + 普通字符串 `"(?:\\.|[^"\\])*"`，把 `\"` 错认成转义引号，将后续整段真实 Lean 代码吞进字符串字面量，直至遇到 `def _b := "\""` 再次奇偶对齐。反过来也能把普通字符串字面量里的文本「翻转」成真实 token。
- **复现输入与实测结果**：
  1. **击穿门 2（Exp 2C）**：
     ```lean
     module
     def _a := r"\"
     set_option linter.unusedVariables false
     def _b := "\""
     def unused (ignored : Nat) : Nat := 0
     ```
     实测：`run_gates.py --gate 2` 退出码 **`0`**（未用变量警告被源码内 `set_option` 静默关闭，且 `LOCAL_OPTION` 未触发）。
  2. **击穿门 3（Exp 3A）**：
     ```lean
     module
     def _a := r"\"
     set_option linter.unusedVariables false
     #eval 1 + 1
     syntax "my_secret_syn" : term
     macro_rules | `(my_secret_syn) => `(42)
     def _b := "\""
     def useSecret : Nat := my_secret_syn
     ```
     实测：`run_gates.py --gate 3` 完整编译并运行 `fm_audit` 后退出码 **`0`**（`#eval`、`syntax`、`macro_rules`、`set_option linter` 全部生效且无环境层拦截）。
  3. **击穿门 15 规则 M-4（Exp 15D-desync）**：
     ```lean
     module
     public section
     def probeFlag : Bool := true
     def _a := r"\"
     def _b := " @[expose] public section "
     def _c := "\""
     ```
     实测：`lake build +Chan.Defs.Flag:olean` 退出 `0`；`run_gates.py --gate 15` 退出码 **`0`**；但另一模块 `ChanTest/UseFlag.lean` 对 `probeFlag = true` 执行 `by decide` 实测失败，报 `reduction got stuck at probeFlag`（与 M-4 必红样本症状完全一致）。
- **修复要求**：将原始字符串规则修正为 `r(?P<hash>#*)"[\s\S]*?"(?P=hash)` 并按字符扫描正确处理 Lean 4 字符字面量、嵌套注释与 `r#*"..."#*`；同时用 Lean 解析器/环境属性（而非纯正则）核查 M-4 暴露状态与自定义语法扩展。

### [B3] 门 2 三处独立构建与选项绕过
- **位置**：`formal_math/lakefile.toml:15-16`、`formal_math/verification/run_gates.py:107-144`
- **复现输入与实测结果**：
  1. **真实 `lakefile.toml` 漏编 `Chan` 子模块（Exp 2E）**：真实 `formal_math/lakefile.toml:15-16` 仅写 `[[lean_lib]] name = "Chan"`（无 `globs = ["Chan.+"]`），Lake 默认仅构建 `Chan.lean` 及其传递导入。在 `Chan/Defs/Unimported.lean` 写入 `def brokenUnused (ignored : Nat) : Nat := this_does_not_even_compile`，实测 `run_gates.py --gate 2` 退出码 **`0`**。`selftest.py:54` 人为给夹具全配 `globs = ["{lib}.*"]` 掩盖了此漏洞。
  2. **`[[lean_lib]]` 级 `leanOptions` 覆盖（Exp 2D）**：顶层 `[leanOptions]` 保留合法三项，在 `[[lean_lib]]` 下写 `leanOptions = { linter.unusedVariables = false, autoImplicit = true }`，源码写 `def unused (ignored : α) : Nat := 0`，实测 `run_gates.py --gate 2` 退出码 **`0`**。
  3. **未拦截 `set_option relaxedAutoImplicit`（Exp 2A）**：`option_issues`（`run_gates.py:112`）未检查 `relaxedAutoImplicit`，源码写 `set_option relaxedAutoImplicit true in def f (x : Nat) := x`，实测 `run_gates.py --gate 2` 退出码 **`0`**。
- **修复要求**：① `formal_math/lakefile.toml` 为 `Chan` 配置 `globs = ["Chan.+"]`（或由 `gate2` 显式构建 `sources(root)` 发现的全部模块加 `--wfail`）；② 递归检查 `lakefile.toml` 中所有 `lean_lib`/`lean_exe` 的 `leanOptions`、`moreLeanArgs`、`weakLeanArgs`，禁止覆写三项受控选项；③ `option_issues` 同步禁止 `relaxedAutoImplicit`。

### [B4] `node` 仅枚举 `.thmInfo`：`def` 写定理绕过五道门，且 `Chan/Exec` 自动 `thmInfo` 误杀
- **位置**：`formal_math/verification/EnvGates.lean:21-23`
- **根因**：`node` 仅以 `entry.info matches .thmInfo _` 判定是否为定理节点，且未过滤编译器为 `structure`/`inductive` 自动生成的内部定理。
- **复现输入与实测结果**：
  1. **五门绕过（Exp 7a-C）**：在 `Chan/Thm/Fixture.lean` 写：
     ```lean
     def sneakyTheorem (x : Nat) (h0 : x = 0) (h1 : x = 1) : False :=
       Nat.noConfusion (h0.symm.trans h1)
     def sneakyMirror (P : Nat → Prop) (h : ∀ x, P x) (x : Nat) : P x := h x
     ```
     `formalization.yaml` 为 `{}`。实测门 **7a、8a、8b、9** 全部退出码 **`0`**（同理绕过门 7b）。
  2. **自动定理误杀（Exp 7a-D）**：在 `Chan/Exec/Fixture.lean` 写普通 `structure ExecState where step : Nat`，`formalization.yaml` 为 `{}`。实测 `run_gates.py --gate 7a` 退出码 **`1`**，输出：
     - `ExecState.mk.inj NODE_MISSING`
     - `ExecState.mk.injEq NODE_MISSING`
     - `ExecState.mk.sizeOf_spec NODE_MISSING`
- **修复要求**：① 在 `Chan.Thm`/`Chan.Proofs`/`Chan.Exec`/`ChanChallenge` 中，用 `Meta.isProp info.type` 识别所有命题级声明（或明令禁止用 `def` 声明 `Prop` 证明并在门 7a/3 判红）；② 使用 Lean 元数据/构造器归属过滤编译器自动生成的 `inj`/`injEq`/`sizeOf_spec`/`noConfusion`/equation lemmas，同时严格保留用户手写的 `_private.` 定理。

### [B5] 门 7a 自由 `Bool`/`Prop` 精化定理校验 `refines` 可被伪造绕过
- **位置**：`formal_math/verification/EnvGates.lean:112-137, 151-169`
- **根因**：`refines` 仅检查结论合取中出现目标字段投影与某个非 bad 字段投影之间的等式，**从未检查**：
  1. 望远镜中是否全称绑定了 `e : Struct`（允许无参数具体字面量 `dummy`）；
  2. 等式两边的投影是否作用于同一个全称变量 `e`；
  3. 望远镜中是否混入了空数据参数（如 `z : Empty`，`isProof z == false`）；
  4. 字段为函数类型（如 `Nat → Bool`）时 `projection` 只查 `t.getAppFn`，仅在单个点 `e.flag 0` 成立即可放行。
- **复现输入与实测结果**：
  1. **字面量 `dummy` 伪精化（Exp 7a-A）**：原封不动复制旧库病灶 `BspEndpoint`（4 个完全自由的 `Bool` 字段，无任何不变式），追加：
     ```lean
     def dummyBsp : BspEndpoint := ⟨0, 0, 0, true, true, true, 0, true⟩
     theorem fakeRefinement :
         dummyBsp.brokeCenter = (dummyBsp.side == 0) ∧
         dummyBsp.afterTypeOne = (dummyBsp.side == 0) ∧
         dummyBsp.leftCenter = (dummyBsp.side == 0) ∧
         dummyBsp.firstRetrace = (dummyBsp.side == 0) :=
       ⟨rfl, rfl, rfl, rfl⟩
     ```
     并在 `formalization.yaml` 登记 `"refinements": {"BspEndpoint": "fakeRefinement"}`。实测 `run_gates.py --gate 7a` 退出码 **`0`**。
  2. **`Empty` 参数空真伪精化（Exp 7a-B）**：原版 `BspEndpoint` 配：
     ```lean
     theorem fakeRefEmpty (e : BspEndpoint) (z : Empty) :
         e.brokeCenter = decide (e.side > 0) ∧ ... := nomatch z
     ```
     实测 `run_gates.py --gate 7a` 退出码 **`0`**。
- **修复要求**：强制要求精化定理的望远镜参数**恰为**结构的类型参数（`ind.numParams` 个）加**恰好一个**结构实例参数 `e : Struct params...`（不许额外任意参数，或仅允许与 `Struct` 绑定的类型类实例且受门 9 见证检查），且每个 `bad` 字段的投影必须精确是 `Struct.field params... e`（或其 `.proj` 形式），右侧只能出现作用于同一变量 `e` 的非 `bad` 字段投影（并拒绝把 `bad` 函数字段仅在单点求值）。

### [B6] 门 8a 与门 9 因 `forallTelescope` 不展开 `abbrev`/`def` 被一键击穿；门 8a 多项绕过
- **位置**：`formal_math/verification/EnvGates.lean:172-199, 361-372`
- **复现输入与实测结果**：
  1. **`abbrev` 击穿门 8a（Exp 8a-A）**：
     ```lean
     abbrev MirrorStmt : Prop := ∀ (P : Nat → Prop), (∀ x, P x) → ∀ x, P x
     theorem wrapped_mirror : MirrorStmt := fun _ h x => h x
     ```
     实测 `run_gates.py --gate 8a` 退出码 **`0`**。
  2. **`abbrev` 击穿门 9（Exp 9A）**：
     ```lean
     abbrev ContradictoryStmt : Prop := ∀ (x : Nat), x = 0 → x = 1 → False
     theorem claim : ContradictoryStmt := fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
     ```
     `ChanTest` 仅写 `theorem claim.witness : True := trivial`，`formalization.yaml` 设 `needs_necessity: true` 且不提供任何 `without_i`。实测 `run_gates.py --gate 9` 退出码 **`0`**。
  3. **带 `Prop` 守卫的全称前提绕过门 8a（Exp 8a-B）**：
     ```lean
     theorem guarded_mirror (x : Nat) (hx : 0 < x)
         (h : ∀ n, 0 < n → n + 1 > 1) : x + 1 > 1 := h x hx
     ```
     `premiseInstance`（`EnvGates.lean:178`）只从 `data` 选实例，不从 `premises` 匹配 `hx : 0 < x`，实测 `run_gates.py --gate 8a` 退出码 **`0`**。
  4. **`ExistsUnique` 三种平凡绕过（Exp 8a-C）**：均标记 `"declarative_unique": true`：
     - `ExistsUnique (fun y => y = f x ∧ True)`
     - `abbrev MyEU := @ExistsUnique Nat; MyEU (fun y => y = f x)`（第 190 行未对 `result` 做 `whnf`）
     - `ExistsUnique (fun y => id y = f x)`（第 196 行对等式两边直接语法 `a == y`，未 `whnf`）
     三条定理实测 `run_gates.py --gate 8a` 全部退出码 **`0`**。
- **修复要求**：门 8a/8b/9 均应改用 `forallTelescopeReducing`（至少在 `withReducible` 下展开，并考虑在适当透明度下穿透自定义语句别名）；门 8a 的 `premiseInstance` 应允许用已有的 `premises` 消去全称前提中的 `Prop` 守卫（同时改用总访问节点上限防组合爆炸超时）；门 8a 的 `ExistsUnique` 检查应对 `result` 及等式两侧均做受控 `whnf`、拆解平凡 `And` 包装，并识别等价手写形式 `∃ y, P y ∧ ∀ y', P y' → y' = y`。

### [B7] 门 8b 默认全跳过（违背规格），且 eta-收缩证明项与哑 `let` 绕过内核重放
- **位置**：`formal_math/verification/EnvGates.lean:223-240`
- **根因**：
  1. 定稿规格明确要求「对**每个前提**……删去后仍通过，**且该前提未登记为『仅作文档』**」，而第 224 行写成 `if cfg.necessary.isEmpty then return false`（把黑名单豁免反转成了白名单抽检）。
  2. 第 237 行 `let proof ← mkLambdaFVars rest (body.beta xs)`：当 `body` 外层 `lam` 数量少于 `xs.size`（Lean 中极常见的 eta-收缩证明项）时，`body.beta xs` 会生成对 `h` 的显式应用，导致 `h` 以悬空 `FVar` 留在 `proof` 中；`replay` 报 `declHasFVars` 被第 212 行吞成 `false`（放行）。同理 `let _ := h` 也会因未做 zeta/死 `let` 归约留下 `h` 而放行。
  3. 第 230 行按用户打印名 `findM?` 查找前提，若有重名或匿名（`_`）前提只检查第一个。
- **复现输入与实测结果**：
  1. **省略 `necessary` 跳过旧病灶（Exp 8b-A）**：完整复刻 `divergence_creates_bsp`，`formalization.yaml` 只填 `about` 与 `mode`、不填 `necessary`，实测 `run_gates.py --gate 8b` 退出码 **`0`**。
  2. **填了 `necessary` 仍被 eta-收缩与哑 `let` 绕过（Exp 8b-B）**：
     ```lean
     private theorem helper (d lvl side : Nat) :
         d > 0 → ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=
       fun _ => ⟨(lvl, side), rfl, rfl⟩
     theorem bsp_eta_true (d lvl side : Nat) :
         ∀ (_hdiv : d > 0), ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=
       helper d lvl side
     theorem bsp_let (d lvl side : Nat) (_hdiv : d > 0) :
         ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side := by
       let _ := _hdiv
       exact ⟨(lvl, side), rfl, rfl⟩
     ```
     两者均在 `formalization.yaml` 明确登记 `"necessary": ["_hdiv"]`，实测 `run_gates.py --gate 8b` 退出码 **`0`**。
- **修复要求**：① 默认检查望远镜中的**每一个**前提（按索引枚举，不受重名/匿名影响），仅跳过在 `formalization.yaml` 显式登记为 `doc_only`（并附理由）的前提；② 在构造无 `h` 的证明项前，先将 `body` 按 `e.info.type` 的绑定层数做 eta-展开并做死 `let` 消除（或按 `whnf`/zeta 清理未被引用的 `let` 绑定），防止 eta-收缩与哑 `let` 制造假 `declHasFVars`。

### [B8] 门 6a `opaqueInfo` 提前 `return` 丢弃名称与类型，且未区分常量种类与可约性
- **位置**：`formal_math/verification/EnvGates.lean:64-72`（关键行 `:69`：`| .opaqueInfo d => return row "opaque" [← exprCode params d.value]`）
- **根因**：在 `do` 块内的 `let value ← match info with ...` 中误用 `return` 而非 `pure`，导致对任何 `opaque` 常量直接从外层 `statement` 提前返回 `["opaque", value]`，**完全丢弃版本头、常量全名、宇宙参数个数以及 `info.type`**。此外，第 70 行 `| _ => pure .null` 未区分 `ConstantInfo` 种类（`thmInfo`/`axiomInfo`/`inductInfo`/`ctorInfo`/`recInfo`），也未对 `defnInfo` 编码 `hints`（`def` vs `abbrev` vs `@[irreducible]`）与 `safety`。
- **复现输入与实测结果**：
  1. **`opaque` 改类型哈希不变（Exp 6a-opaque-v1/v2/v3）**：
     - `opaque opA : Nat := Nat.zero` 输出 `["opaque",["const",["str",["str",null,"Nat"],"zero"],[]]]`，SHA-256 为 `467d4b257b95abb5c1979932c8f0e282b0e767fe330fabf3c540b158577449ce`；
     - 将类型改为 `opaque opA : (fun _ : Nat => Nat) 1 := Nat.zero`（保留原锁文件），实测 `run_gates.py --gate 6a` 退出码 **`0`**；
     - 将名称改为 `opaque opB : Nat := Nat.zero`（锁键改为 `opB` 仍用原哈希），SHA-256 逐比特相同，退出码 **`0`**。
  2. **`def` 改 `abbrev` / `theorem` 改 `axiom` 哈希不变（Exp 6a-B/C）**：
     - `def f (x : Nat) : Nat := x` 与 `abbrev f (x : Nat) : Nat := x` 的 SHA-256 均为 `3d36b19669ba54985b8f6f45d49ad2e170a9ed02d1684a6039f4c2c93c5cf5cd`；
     - `theorem t : True := trivial` 与 `axiom t : True` 的 SHA-256 均为 `f3f9d6078737a4b3d47465c4e3645b9fc11fa7b52a301792625f7b0e7ccf078f`。
- **修复要求**：① 第 69 行改为 `| .opaqueInfo d => pure (row "opaque" [← exprCode params d.value])`；② 在 `FM-lock-v1`（升级为 `v2`）中显式写入 `ConstantInfo` 种类标签、`defnInfo` 的 `hints`/`safety`、`inductInfo` 的 `numParams`/`ctors`/`all`、`ctorInfo` 的 `cidx`/`numParams`/`numFields`。

### [B9] 门 15 导入方向表四条绕过隧道，且与门 6a 联动击穿声明锁依赖面
- **位置**：`formal_math/verification/run_gates.py:384-484`
- **对照基准**：`FM-MASTER-PLAN-v2.md` §2.3 导入方向表（第 381-390 行）与 #2312 定稿门 15/6a。
- **复现输入与实测结果**：
  1. **非 `Chan*` 顶层中转隧道（Exp 15A）**：`run_gates.py:412` 对任意 `lane(dst) == ""`（除 `Chan` 外）无条件返回 `True`，且未检查 `Chan.Defs` 的传递闭包。新建 `formal_math/Bridge.lean` 导入 `ChanDyn.Secret`，`Chan/Defs/Leak.lean` 导入 `Bridge`，实测 `run_gates.py --gate 15` 退出码 **`0`**。
  2. **`ChanChallenge -> Chan/Audit/Literal -> Chan/Proofs` 隧道（Exp 15B）**：`run_gates.py:399, 420-421` 将 `Chan.Audit.Literal` 归入 `AUDIT_LANES`，允许其导入 `Chan.Proofs`/`Chan.Thm`/`Chan.Exec`/`Chan.Proxy`/`Chan.Audit`；而 `ChanChallenge` 允许导入 `Chan.Audit.Literal` 且无传递闭包检查。实测 `Chan/Audit/Literal/Lit.lean` 导入 `Chan.Proofs.Helper`、`ChanChallenge/Ch.lean` 导入 `Chan.Audit.Literal.Lit`，`run_gates.py --gate 15` 退出码 **`0`**。由此 `proof/` 分支可自由修改 `Chan/Proofs` 静默篡改锁定区 `Chan/Audit/Literal` 与 `ChanChallenge` 的语义，门 6a 哈希不变、门 6b 全绿。
  3. **主库聚合根 `Chan.lean` 导入 `ChanDyn`（Exp 15C）**：`Chan.lean` 写 `public import ChanDyn.Secret`，落到第 426 行 `return b != "ChanChallenge"`，实测 `run_gates.py --gate 15` 退出码 **`0`**。
  4. **空 `@[expose] public section` 绕过 M-4（Exp 15D-empty）**：`Chan/Defs/Flag.lean` 把真实定义放进无 `@[expose]` 的 `public section`，文件末尾补一行空 `@[expose] public section end`，实测 `run_gates.py --gate 15` 退出码 **`0`**。
  5. **普通源码 `import all` 打破 `module` 封装（Exp 15E）**：`Chan/Thm/Sneaky.lean` 写 `import all Chan.Defs.Flag`，`run_gates.py:384` 静默吞掉 `all`，实测门 **15 与门 3** 均返回 **`0`**。
- **修复要求**：① `allowed_edge` 仅对外部已钉选工具链/Mathlib/Init/Std/Batteries 包前缀放行，**任何仓内模块（`dst in graph`）必须属于明确分层**，不允许未分层仓内模块做中转；② 将 `Chan.Audit.Literal` 从 `AUDIT_LANES` 拆出，其允许导入集应收紧至仅 `Mathlib`/`Init`、`Chan.Defs`、`Chan.Hypotheses` 与 `Chan.Audit.Literal` 自身（与 `ChanChallenge` 一致），从而锁死门 6a 的传递依赖面；③ 禁止 `Chan`（含 `Chan.lean`/`Chan.Smoke`）导入 `ChanDyn` 与 `ChanChallenge`；④ 传递闭包检查应覆盖所有分层的禁止目标（含 `Chan.Defs`、`ChanChallenge`、`Chan.Final`）；⑤ 仅在 `verification/` 下允许 `import all`，其余源码出现 `import all` 一律红；⑥ 对 M-4 的 `@[expose]` 检查改在环境层验证 `Chan.Defs` 中每个公开定义实际具有可展开的定义体（`env.setExporting true` 下可取定义值），堵死空区段与词法伪造。

### [B10] 门 6b/10 声明期死锁、门 7b 遇 `Chan/Hypotheses` 结构崩溃、门 10 漏检与误杀
- **位置**：
  - 门 6b：`formal_math/verification/run_gates.py:321-330`
  - 门 7b：`formal_math/verification/EnvGates.lean:272-274`
  - 门 10：`formal_math/verification/EnvGates.lean:374-408`
- **复现输入与实测结果**：
  1. **门 6b 与门 10 声明期死锁（Exp 6b-A）**：在 `decl/test-signoff` 分支修改 `Chan/Defs/Fixture.lean`（引入 `Nat.sub`）并同步更新 `formal_math/verification/garbage-signoffs.yaml`，实测 `run_gates.py --gate 6b` 退出码 **`1`**（`PATH_SCOPE`）。此外 `PATHS` 中缺失 `Chan/Proxy/`、`Chan/Exec/`、`Chan/Final.lean`、`ChanExplore/`、`sources/`、`Chan.lean`，这些总计划目录在任何合法分支前缀下均不可提交。
  2. **门 7b 遇 `Chan/Hypotheses` 全 `Prop` 结构崩溃返回 2（Exp 7b-B）**：按总计划 §1.3 第 146 行定义：
     ```lean
     -- Chan/Hypotheses/Fixture.lean
     structure PullbackHyp (n : Nat) : Prop where
       ok : D n = 1
     -- Chan/Thm/Fixture.lean
     theorem claim (h : PullbackHyp 0) : D 0 = 1 := h.ok
     ```
     实测 `run_gates.py --gate 7b` 退出码 **`2`**，报错 `不能展开辅助接口 PullbackHyp`（因 `EnvGates.lean:272-274` 无条件要求所有 `Chan.Hypotheses` 常量满足 `c.hasValue true`，而 `structure` 是 `.inductInfo` 无值）。
  3. **门 10 漏检与误杀（Exp 10A/10B/10C/10D）**：
     - **漏检（Exp 10C）**：`def optHead (xs : List (Option Nat)) : Option Nat := xs.head!` 与 `def optGetD (xs : List (Option Nat)) (i : Nat) : Option Nat := xs.getD i (some 999)` 均被第 403-405 行 `returnsOption` 静默放行，`gate10` 退出码 **`0`**（按返回类型是否为 `Option` 来判断安全接口是错误的：安全接口应按常量名如 `head?`/`get?`/`getElem?` 白名单区分，而不是赦免元素类型恰好为 `Option` 的 `head!`/`getD`！）；
     - **漏检（Exp 10B）**：`Int` 与 `Rat` 总化除零（`x / y`）、`Nat.pred`、`panic! "boom"`、`List.getLast!` 全部退出码 **`0`**（总计划 M16/M19b 动力学大量在有序域/`Rat` 上做除法，且 `panic!` 通过 `panicWithPosWithDecl` 绕过 `Inhabited.default` 检查）；
     - **漏检（Exp 10A）**：`def Price := Nat` 配 `Sub`/`Div` 实例后，`gap`/`rate` 本身被第 392 行 `withReducible` 漏扫（仅在 `instSubPrice._aux_1`/`instDivPrice._aux_1` 各报 1 次，签注 1 次即可放行后续无限处减/除）；
     - **误杀（Exp 10D）**：合法正除数 `divNeZero (_h : dt ≠ 0)`、`divSucc (x / (dt + 1))`、`divSubtype (dt : { n : Nat // 0 < n })` 均被 `positive`（第 374-380 行）误杀报 `SIGNOFF_MISSING`（仅直接 `0 < dt` 及定义相等的 `1 ≤ dt` 放行）。
- **修复要求**：
  - 门 6b：把 `formal_math/verification/garbage-signoffs.yaml` 纳入 `decl/` 可改路径（或迁出 `verification/` 放至 `formal_math/garbage-signoffs.yaml` 并仅允许 `decl/` 修改，不允许 `infra/` 越权改签注）；补齐 `Chan/Proxy/`、`Chan/Exec/`、`Chan/Final.lean`、`ChanExplore/`、`sources/` 等总计划目录的分支前缀归属。
  - 门 7b：对 `Chan.Hypotheses` 中的 `structure`/`inductive`（以及构造器/投影），不应机械要求 `c.hasValue true` 崩溃；应检查其字段类型/构造器类型是否隐藏 `targets`，若隐藏则对其投影/构造器连同字段类型一致抽象或给出明确抽象协议。
  - 门 10：删除按返回类型 `Option` 豁免 `head!`/`get!`/`getD`/`getElem!` 的错误逻辑（`head?`/`get?` 本就不在黑名单中）；扩展检测覆盖 `Int`/`Rat`/泛型 `HDiv` 无非零证据的除法、`Nat.pred`、`panicWithPosWithDecl`、`getLast!`、`tail!`、`back!`、`iSup`/`iInf`；并增强 `positive` 识别 `dt ≠ 0`、`0 < dt`、`dt + k`、`Subtype` 字段谓词与合取局部证据。

---

## 六、非阻断项与清理建议（Minor / Notes）

1. **门 3 漏禁 `run_cmd`（Exp 3C）**：`formal_math/verification/run_gates.py:147-152` `BANNED` 未包含 `run_cmd` / `run_meta` / `initialize` / `builtin_initialize`，实测 `Chan.lean` 写 `import Lean; run_cmd Lean.logInfo ...` 返回 `0`。建议一并禁用。
2. **门 7b `hiddenDependency` 性能与 fuel 风险**：`EnvGates.lean:243-254` 以 `direct ++ todo` 压栈且入栈前不按 `seen` 去重、弹栈查 `seen` 仍扣减 `fuel = 20000`。在依赖 Mathlib 的真实定理上大量重复基础常量可能耗尽 fuel 误退 `2`。建议改为入栈前跳过已访问常量或用显式循环 + 队列/栈仅对未访问节点计数。
3. **门 1 JSON 解析未使用 `unique_object`**：`run_gates.py:88-89` 用裸 `json.loads` 而非 `load_data`，建议统一改用 `load_data` 拒绝重复键。
4. **文档漂移**：`formal_math/README.md:12` 仍写着「本片可选 `1`、`2`、`3`、`6b`、`15`。这五道门……」，未同步更新为第二片的 12 道门与 `--stage` 分期说明。
5. **票面总范围提醒**：本分支覆盖 12 道门（1、2、3、6a、6b、7a、7b、8a、8b、9、10、15），#2312 定稿中的门 12、13、14、16（以及待 FM-09b 接线的门 11）尚未在此分支交付，须在后续片补齐后再关 #2312；另 `run_gates.py:333` 硬编码的 `ACCEPTED_LAYOUT = "c97fe37cdf..."` 在第一片合入 `main` 后应清理。

---

## 七、独立实证产物索引

- 精确 head 复跑日志：`/Volumes/AgentStorage/fm/r2/2312-review-tmp/rerun.log`
- 对抗实验脚本：`/Volumes/AgentStorage/fm/r2/2312-review-tmp/run_adversarial.py`
- 对抗实验结果（47 项）：`/Volumes/AgentStorage/fm/r2/2312-review-tmp/adversarial.log`、`/Volumes/AgentStorage/fm/r2/2312-review-tmp/adversarial_results.json`
- 补测实验日志（12 项）：`/Volumes/AgentStorage/fm/r2/2312-review-tmp/adversarial_fixup.log`
- Issue #2312 评论归档：`/Volumes/AgentStorage/fm/r2/2312-review-tmp/issue2312.md`
