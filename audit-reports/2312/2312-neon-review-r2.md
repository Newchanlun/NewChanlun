VERDICT: BLOCK

# NewChanlun 票 #2312（地图 #2293 / FM-04）第二轮独立非作者审阅与对抗复验报告

- 审阅工位：第二轮独立非作者静态审阅与对抗复验（只读，作者为 Codex GPT-6.2 Sol）
- 审阅日期：2026-11-24
- 被审分支与精确提交：`origin/infra/2312-b-env-gates` @ `0b991736774eaa4159baa75f2f3d35a10b67e015`
- 第一轮对照基准：`cd4b6c301d2f02847dd30da9db6a2e2e96e03e8a`
- 只读工作树：`/Users/silencehan/.t3/worktrees/NewChanlun/infra-2312-b-env-gates-2428b08ce810d112`（全程零写入、零 git 改动）
- 全量差异留档：`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/diff.patch`（115 个文件变更，937 行新增，131 行删除）
- 复跑与对抗产物目录：`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/`

## 一、审阅结论摘要

在精确提交 `0b991736774eaa4159baa75f2f3d35a10b67e015` 上，独立复跑 `lake build --wfail`（3,537 项）、`lake build fm_audit`（8 项）、12 道门禁逐门及三阶段执行、`selftest.py`（139 / 139 夹具，较第一轮 102 个新增 37 个），以及第一轮对抗脚本的 47 项实验，**基准与自测全部通过，第一轮 B1 至 B10 的直接复现点与第六节前 4 条非阻塞项均已真实修复，未见白名单或特判绕过**。特别是门 15（导入方向、非 `Chan*` 桥接拦截、`Chan/Audit/Literal` 隔离、`import all` 禁用、环境层 `publicView` 暴露校验）与门 6b（分支前缀与签注权限）本轮加固扎实。

但在第二轮仓外沙箱深度对抗实测（覆盖词法器、配置、声明锁、权限、定义依赖、抽象诊断、形状检查、未用前提、见证反例、垃圾值与模块隔离，共计执行 120 余组实证实验）中，**检出 7 项阻断级缺陷（R2-B1 至 R2-B7）**，包括 4 类可零警告编译并直接伪造绿灯的真实硬绕过、2 类必然阻塞真实开发（普通递归定理、`Chan/Exec` 可执行模型、带 `[LinearOrder P]` 的合法精化结构、`Int`/`Rat` 正除数）的系统性误杀，以及 1 类 `Chan/Hypotheses` 归纳命题触发门 7b 退出码 `2` 的崩溃。依据审阅裁决口径，本轮判 `BLOCK`。

## 二、精确提交基准复跑与一轮对抗复验（核查项 1 与 2）

全过程设 `TMPDIR=/Volumes/AgentStorage/fm/r2/2312-r2-tmp/tmp`，复跑前后工作树 `HEAD` 均为 `0b991736774eaa4159baa75f2f3d35a10b67e015`、`git status --short` 仅原有未跟踪目录 `?? gpt-with-taste/`，内置盘 `/` 可用空间始终大于 6 GiB（复跑前 9.2 GiB，全部实验结束后 6.7 GiB）。

| 检查项 | 命令或范围 | 实测结果 | 退出码 | 日志路径 |
| --- | --- | --- | --- | --- |
| 工具链核验 | `lean --version` / `lake --version` | Lean `4.36.0` (`611c117bfaf7b7ae1cfcf246ce6fba31e8f509e9`) / Lake `5.0.0` | 0 | `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/baseline_rerun.log` |
| 全包零警告构建 | `lake build --wfail` | `Build completed successfully (3537 jobs).` | 0 | `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/baseline_rerun.log` |
| 审计可执行构建 | `lake build fm_audit` | `Build completed successfully (8 jobs).` | 0 | `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/baseline_rerun.log` |
| 逐门运行 | `run_gates.py --repo-root . --gate <n>`（1, 2, 3, 6a, 6b, 7a, 7b, 8a, 8b, 9, 10, 15） | 12 道门全部无红行通过 | 全部 0 | `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/baseline_rerun.log` |
| 分阶段运行 | `run_gates.py --repo-root . --stage decl\|proof\|all` | 三阶段全部通过 | 全部 0 | `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/baseline_rerun.log` |
| 全量自测 | `python3 formal_math/verification/selftest.py` | 139 / 139 全部通过（107 `must_red` + 30 `must_green` + 2 `must_unknown`，较一轮 102 个新增 37 个：9 绿 + 28 红） | 0 | `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/selftest.log` |
| 一轮对抗复跑 | `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_adversarial_r1_replay.py`（逐字复刻 `/Volumes/AgentStorage/fm/r2/2312-review-tmp/run_adversarial.py`，仅重定向沙箱目录） | 47 / 47 项结果均按预期闭合 | 脚本退出 0 | `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r1_replay.log`、`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r1_replay_results.json` |

## 三、一轮 B1 至 B10 及第六节非阻塞项闭合核验表（核查项 3）

| 编号 | 一轮问题 | 代码与夹具核查 | 一轮复现实验结果 | 本轮闭合状态 |
| --- | --- | --- | --- | --- |
| B1 | 门 1 漏查运行期 `lean --version` | `run_gates.py:104-111` 实跑 `lean --version` 比对版本；新增 `must_red/g1/runtime-pin` | Exp 1A 退出 `1`（`RUNTIME_TOOLCHAIN_PIN`） | 已闭合（见 Minor M1） |
| B2 | `LEX` 词法器 `r"\"` 脱同步击穿门 2/3/15 | `run_gates.py:49, 71-77` 改用显式定界符 `find` 消费 `r#*"..."#*`；新增 4 个夹具 | Exp 2C/3A/3B/15D-desync 全部退出 `1` | 局部闭合；新对抗发现插值字符串 `s!"{'"'}"` 同类脱同步击穿门 2/3（见 R2-B1） |
| B3 | 门 2 缺 `Chan` globs、未查子目标 `leanOptions`、未禁 `relaxedAutoImplicit` | `lakefile.toml:17` 补 `globs = ["Chan.*"]`；`run_gates.py:129, 138-150, 166-169` 检查子目标覆写并全量构建源码模块；新增 3 个红夹具 | Exp 2A/2B/2D/2E 全部退出 `1`；`A5/A6/A6b/A6c/A6d/A6e` 均被拦截 | 已闭合 |
| B4 | `node` 仅收 `.thmInfo` 漏 `def` 证明，且误杀 `Chan/Exec` 自动定理 | `EnvGates.lean:28-41` 改按 `isProp` 收 `thmInfo`/`defnInfo`/`opaqueInfo`，加 `isReservedName` 与构造器白名单过滤；新增 2 个夹具 | Exp 7a-C 均红（7a/8a/9 退出 `1`）；Exp 7a-D 退出 `0` | 未彻底闭合；`._proof_1`、`match_1_1`、`._f`、`._flat_ctor` 仍大面积误杀（见 R2-B4） |
| B5 | 门 7a `refines` 可被字面量 `dummy` 与 `Empty` 参数伪造 | `EnvGates.lean:169-188` 限定望远镜长度 `nparams + 1`、参数均为 `Sort` 且左右同变量 `x` 整投影；新增 2 个红夹具 | Exp 7a-A/7a-B 退出 `1`（`FREE_PREDICATE`）；`D3-g7a`（`def Flag := Bool` / `Id Bool`）退出 `1` | 局部闭合；`isSort` 过严永久误杀 `[LinearOrder P]` 与值参数结构（见 R2-B5） |
| B6 | 门 8a/9 `forallTelescope` 不展开别名；守卫前提与 `ExistsUnique` 漏检 | `EnvGates.lean:222-301` 引入 `statementHead`/`telescope`/`stripTrue`/`graphEq`/`functionGraph`；新增 4 个红夹具 | Exp 8a-A/8a-B/8a-C/9A 全部退出 `1` | 未彻底闭合；`Option.getD`/`Function.const`/`True ∧` 击穿 8a/8b/9，另有 7 种 8a 绕过（见 R2-B2、R2-B7） |
| B7 | 门 8b 默认全跳过（反转 opt-out）；eta 收缩与哑 `let` 绕过 | `EnvGates.lean:338-370` 改为默认全查前提、仅 `doc_only` 豁免，并加 `proofHead` 与 `zetaReduce`；新增 3 个夹具 | Exp 8b-A/8b-B 全部退出 `1`；`X3-doc-only-partial` 仅豁免登记项 | 未彻底闭合；4 种常见证明手法独立绕过门 8b（见 R2-B3） |
| B8 | 门 6a `opaqueInfo` 提前 `return` 且未区分类别与可约性 | `EnvGates.lean:82-110` 升至 `FM-lock-v2`，内层 `do` 修复早退，编码种类、safety、reducibility 与结构元信息；新增 6 个夹具 | Exp 6a-A/B/C 均产生不同序列化与哈希；`B4/B6/B7/B8/B9/B10` 全部敏感 | 已闭合（见 Minor M2） |
| B9 | 门 15 四条导入隧道、`import all`、空 `@[expose]` | `run_gates.py:471-573` 封堵未分层本地模块、收紧 `Chan.Audit.Literal`、禁 `Chan` 导 `ChanDyn`、禁普通源码 `import all`、全分层闭包校验；`EnvGates.lean:669-675` 环境层核查 `publicView`；新增 6 个红夹具 | Exp 15A/15B/15C/15D-empty/15D-desync/15E 及 R2 变体 `G3/G4/G5/G6` 全部退出 `1` | 已闭合 |
| B10 | 门 6b/10 死锁、门 7b `Chan/Hypotheses` 结构崩溃、门 10 漏检/误杀 | `run_gates.py:367-440` 补齐 `decl/`/`proof/`/`infra/` 路径与空签注初始化规则；`EnvGates.lean:446-470` 名义保留假设结构；`EnvGates.lean:526-620` 删除 `Option` 误豁免并扩充除法与垃圾运算；新增 6 个夹具 | Exp 6b-A 退出 `0`；Exp 7b-B 退出 `0`；Exp 10A/10B/10C 退出 `1`；Exp 10D 退出 `0` | 6b 已闭合；7b 遇非结构归纳假设仍退 2（见 R2-B7）；10 漏 `Rat.inv`/`Inv.inv`/`headD` 且误杀 `Int`/`Rat` 的 `0 < dt`（见 R2-B6） |
| Minor 1 | 门 3 漏禁 `run_cmd` / `run_meta` / `initialize` | `run_gates.py:187` 补齐四项；新增 `must_red/g3/run-cmd` | Exp 3C 退出 `1`（`TOKEN`） | 已闭合 |
| Minor 2 | 门 7b `hiddenDependency` 入栈不去重耗 fuel | `EnvGates.lean:385-387` 入栈前即检查并插入 `seen` | 静态核验确认 | 已闭合 |
| Minor 3 | 门 1 JSON 解析未拒重复键 | `run_gates.py:95-96` 统一改用 `load_data` | 静态核验确认 | 已闭合 |
| Minor 4 | `formal_math/README.md:12` 仍停留在第一片 5 门描述 | 已更新为 12 道门与 `--stage` 分期说明 | 静态核验确认 | 已闭合 |
| Minor 5 | 门 12/13/14/16（及待 FM-09b 的门 11）与 `ACCEPTED_LAYOUT` 清理 | 本分支定位仍为 12 门（1,2,3,6a,6b,7a,7b,8a,8b,9,10,15） | 属跨片范围提醒 | 非本轮阻断 |

## 四、第二轮新检出阻断级缺陷详情（核查项 4 与 5）

以下 7 项阻断级缺陷均在仓外独立沙箱中对真实 `formal_math` 门禁代码实测复现，附最小复现代码、脚本路径、日志与真实退出码。

### [R2-B1] 插值字符串 `s!"{'"'}"` 再次造成 `LEX` 词法脱同步，直接击穿门 2 与门 3

- 位置：`formal_math/verification/run_gates.py:48-86`
- 根因：`LEX` 仅修复了 `r#*"..."#*` 原始字符串，未处理 Lean 4 合法的字符串插值语法 `s!"{...}"`（及 `m!"{...}"`）。当插值表达式 `{...}` 中包含字符字面量 `'"'` 时，外层开双引号会与 `'"'` 内的双引号被 `"(?:\\.|[^"\\])*"` 提前配对，导致外层闭双引号被误判为新字符串的起始引号，将后续整段真实 Lean 命令全部吞入字符串字面量，直至遇到 `def _b : Char := '"'` 重新奇偶对齐。更甚者，当隐藏区内包含成对双引号的 `syntax "my_secret_syn" : term` 时，第一个双引号临时闭合脱同步串、暴露无害标识符 `my_secret_syn`，第二个双引号重新进入脱同步吞掉 `: term` 与 `macro_rules`。
- 最小复现代码（门 2 + 门 3 同文件击穿）：
  ```lean
  module
  import Lean
  def _a : String := s!"{'"'}"
  set_option linter.unusedVariables false
  set_option autoImplicit true
  #eval 1 + 1
  run_cmd Lean.logInfo (toString (1 + 1))
  declare_syntax_cat sneaky_cat
  infixl:65 " +++ " => Nat.add
  def _b : Char := '"'
  def useOp (ignored : α) : Nat := 2 +++ 3
  ```
  另单独验证带双引号的 `syntax` 与 `macro_rules`：
  ```lean
  module
  def _a : String := s!"{'"'}"
  syntax "my_secret_syn" : term
  macro_rules | `(my_secret_syn) => `(42)
  def _b : Char := '"'
  def useSecret : Nat := my_secret_syn
  ```
- 复现脚本与日志：`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_r2_fixup.py`（日志 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_fixup.log`）
- 实测退出码：
  - `A1-clean-build`（`lake build --wfail`）：退出码 `0`；`A1-clean-g2`（门 2）：退出码 `0`（成功关闭未用变量检查并启用 `autoImplicit` 与 `relaxedAutoImplicit`）。
  - `A2-clean-g2`（门 2）：退出码 `0`；`A2-clean-g3`（门 3）：退出码 `0`（`#eval`、`run_cmd`、`declare_syntax_cat`、`infixl`、`set_option linter` 全部生效且零告警）。
  - `A2-syn-build`（`lake build --wfail`）：退出码 `0`；`A2-syn-g3`（门 3）：退出码 `0`（`syntax` 与 `macro_rules` 生效且绕过门 3）。
- 备注：门 15 的 M-4 校验因本轮已接入 `publicView` 环境层兜底，同款 `s!"{'"'}"` 伪造 `@[expose] public section`（用例 `G5-g15`）已被环境层正确拦截（退出码 `1`）。
- 修复建议：放弃正则切分，使用手写状态机扫描 Lean 词法（正确递归处理插值字符串 `s!"..."` / `m!"..."` 的 `{...}` 括号深度、嵌套 `/- -/`、原始字符串 `r#*"..."#*`、字符字面量含 `\x`/`\u` 转义），或直接在 Lean 审计工具中用 `Lean.Parser.runParserCategory` 读真实源码语法树做命令与选项扫描（一劳永逸消除词法脱同步类漏洞）。

### [R2-B2] `statementHead` 仅展开 `projectModule` 与 `.reducible`，非项目半可约包装与 `True ∧ P` 一举击穿门 8a、8b、9

- 位置：`formal_math/verification/EnvGates.lean:222-247`
- 根因：
  1. `statementHead` 第 230 至 235 行仅对 `owner env n` 属于 `projectModule` 的 `.defnInfo` 做强制展开，对其余常量仅调用 `withReducible <| whnf e`。但 Lean 内核类型检查使用 `.default` 透明度，标准库 `Init` 中大量半可约定义（如 `Option.getD`、`Function.const`）在 `.default` 下与内部命题完全定义相等，却在 `.reducible` 下停止展开。
  2. `statementHead` 在遇到 `And` 时停止展开，而 `telescope` 与 `gate8a`/`gate8b`/`gate9` 仅在顶层剥离 `forallE`，对 `True ∧ (∀ ...)` 形式的合取包裹不拆解子命题。
- 最小复现代码：
  ```lean
  module
  public section
  theorem mirror_getd : Option.getD (some (∀ (P : Nat → Prop), (∀ x, P x) → ∀ x, P x)) True :=
    fun _ h x => h x
  theorem bsp_getd : Option.getD (some (∀ (d lvl side : Nat) (_hdiv : d > 0), ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side)) True :=
    fun _ lvl side _ => ⟨(lvl, side), rfl, rfl⟩
  theorem vac_getd : Option.getD (some (∀ (x : Nat), x = 0 → x = 1 → False)) True :=
    fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
  theorem vac_const : Function.const Unit (∀ (x : Nat), x = 0 → x = 1 → False) () :=
    fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
  ```
  `ChanTest/Evidence.lean` 对四条定理仅提供 `theorem <name>.witness : True := trivial`，`formalization.yaml` 均登记 `needs_necessity: true` 且不提供任何 `without_i`。
- 复现脚本与日志：
  - `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_r2_last_probe.py`（日志 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_last_probe.log`，用例 `L1-*`）
  - `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_r2_clean_verify.py`（日志 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_clean_verify.log`，用例 `E2-and_wrap-g9`、`E2-and-8a`、`E2-and-8b`）
- 实测退出码：
  - `L1-build`（`lake build --wfail`）：退出码 `0`；`L1-g7a`：退出码 `0`；`L1-g8a`：退出码 `0`；`L1-g8b`：退出码 `0`；`L1-g9`：退出码 `0`（四道环境门全部假绿灯）。
  - `E2-and_wrap-build`：退出码 `0`；`E2-and_wrap-g9`：退出码 `0`；`E2-and-8a`：退出码 `0`；`E2-and-8b`：退出码 `0`。
- 修复建议：`statementHead` 应在 `.default` 透明度下持续做头归约（遇到 `Not`/`Exists`/`And`/`Iff`/`Eq`/`ExistsUnique`/`False`/`True` 等逻辑连接词常量立即停手，不依赖是否属于 `projectModule`），并对顶层 `And` 分量递归执行门 8a/8b/9 检查（或拒绝用平凡 `True ∧` 包装全称定理）。

### [R2-B3] 门 8b `proofHead` 仅展开顶层项目常量，四种常见证明写法独立绕过门 8b

- 位置：`formal_math/verification/EnvGates.lean:338-370`
- 根因：`gate8b` 仅对 `body.beta xs` 顶层调用 `proofHead`（只展开外层 `p.getAppFn` 且要求其属于 `projectModule`），随后把得到的 `applied` 直接塞进 `mkLambdaFVars rest applied` 送内核重放。结果只要冗余前提 `_hdiv` 出现在以下任一位置，就会在 `applied` 中残留悬空 `FVarId`，触发 `replay` 返回 `.error (.declHasFVars ..)` 并被第 326 行吞成 `false`（判绿放行）：
  1. 证明项 eta 收缩到非项目常量（如 `Function.const`）；
  2. 证明体子项中存在未归约的 beta 项（如 `(fun _ => rfl) _hdiv`）；
  3. 证明体子项中经投影丢弃（如 `And.left ⟨rfl, _hdiv⟩`）；
  4. 证明体子项中调用私有辅助定理（如 `mkEq _hdiv`，因外层构造器 `Exists.intro` 属于 `Init`，`proofHead` 根本不进入参数）。
- 复现脚本与日志：`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_r2_clean_verify.py`（日志 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_clean_verify.log`，用例 `E4-const`、`E4-sub-beta`、`E4-and-left`、`E4-sub-helper`）
- 实测退出码（四项均为独立单文件包，先验 `lake build --wfail` 再跑门 8b）：
  - `E4-const`（`Function.const (d > 0) ⟨(lvl, side), rfl, rfl⟩`）：构建退出 `0`，门 8b 退出码 `0`。
  - `E4-sub-beta`（`⟨(lvl, side), (fun _ => rfl) _hdiv, rfl⟩`）：构建退出 `0`，门 8b 退出码 `0`。
  - `E4-and-left`（`⟨(lvl, side), And.left ⟨rfl, _hdiv⟩, rfl⟩`）：构建退出 `0`，门 8b 退出码 `0`。
  - `E4-sub-helper`（`⟨(lvl, side), mkEq _hdiv, rfl⟩`）：构建退出 `0`，门 8b 退出码 `0`。
- 修复建议：在删去前提 `h` 并送内核重放前，应对 `applied` 进行全树归一化（至少包含全树 `zetaReduce`、全树 beta 归约、iota 投影归约如 `And.left ⟨a, b⟩ -> a`，并在含 `h` 的子项上按需按 `.default` 透明度展开头部常量或私有辅助引理），不能仅归约最外层 `projectModule` 头部。

### [R2-B4] `node` 对编译器自动生成辅助定理过滤不完整，真实 `Chan/Exec` 与普通递归定理在门 7a 与门 9 必然误杀

- 位置：`formal_math/verification/EnvGates.lean:28-41`
- 根因：B4 修复仅通过 `isReservedName` 与构造器子名列表 `["inj", "injEq", "sizeOf_spec", "elim"]` 过滤自动项，未覆盖 Lean 4 编译器大量自动生成且类型为 `Prop`、但不在 `isReservedName` 内的内部定理与辅助项，实测至少包括：
  1. 任何带 `deriving DecidableEq`、数组下标证明或 `termination_by` 良基递归的 `Chan/Exec` 函数自动抽象出的 `._proof_1`、`._proof_2`、`._proof_4`；
  2. `Chan/Thm` 中任何最基础的结构递归定理自动生成的 `_private.<Mod>.0.<thm>.match_1_1` 与 `<thm>._f`；
  3. `Prop` 类/结构自动生成的 `<Class>.mk._flat_ctor`。
- 最小复现代码（普通递归定理，已完整登记 `formalization.yaml` 并提供 `rec_thm.witness`）：
  ```lean
  module
  public section
  theorem rec_thm (n : Nat) : n + 0 = n :=
    match n with
    | 0 => rfl
    | k + 1 => congrArg Nat.succ (rec_thm k)
  ```
- 复现脚本与日志：
  - `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_r2_clean_verify.py`（日志 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_clean_verify.log`，用例 `E5-rec-g7a`、`E5-rec-g9`）
  - `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_adversarial_r2.py`（日志 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_adversarial.log`，用例 `D1-g7a`、`D2-g7a`、`D2-g9`）
- 实测退出码：
  - `E5-rec-build`：退出码 `0`；`E5-rec-g7a`（门 7a）：退出码 `1`，误报 `_private.Chan.Thm.Fixture.0.rec_thm.match_1_1` 与 `rec_thm._f` `NODE_MISSING`；`E5-rec-g9`（门 9）：退出码 `1`，要求在 `ChanTest` 为这两个编译器内部项编写 `.witness`。
  - `D2-g7a`（门 7a）与 `D2-g9`（门 9）在 `Chan/Exec` 中仅定义 `inductive Dir deriving DecidableEq`、`structure Bar deriving DecidableEq`、`def countdown`（`termination_by`）和 `def firstElem`（`arr[0]`）：均退出码 `1`，误报 `instDecidableEqBar.decEq._proof_1`、`instDecidableEqDir._proof_1`、`countdown._proof_1` 等全部为未登记节点及缺见证。
  - `D1-g7a`：对 `class MyPropClass : Prop` 误报 `MyPropClass.mk._flat_ctor NODE_MISSING`。
- 修复建议：结合 `(← findDeclarationRangesCore? entry.name).isNone` 条件（确保手写任何同名恶意定理绝不被跳过），统一使用 Lean 内置的 `Lean.isAuxRecursor`、`Lean.isMatcher`、`Lean.Meta.isAuxLemma` / `Lean.isInternalDetail`（并覆盖 `._proof_`、`._f`、`._flat_ctor`、`.match_`、`._sunfold`、`.eq_`、`._unary` 等无源范围编译器合成项）。

### [R2-B5] 门 7a `refines` 强求全部 `nparams` 参数类型为 `Sort`，永久误杀带 `[LinearOrder P]` 或值参数的合法精化结构

- 位置：`formal_math/verification/EnvGates.lean:177-178`
- 根因：B5 修复在 `refines` 中加入：
  ```lean
  for p in xs.extract 0 nparams do
    unless (← whnf (← inferType p)).isSort do return false
  ```
  该约束假设结构体的所有 `ind.numParams` 个参数都是纯类型参数（`Sort`）。然而总计划 `Chan/Defs` 中几乎所有核心结构均带类型类实例参数（如 `structure GoodBar (P : Type) [LinearOrder P]`，其中 `[LinearOrder P]` 的类型是 `LinearOrder P`，不是 `Sort`）或值参数（如 `structure Window (k : Nat)`）。对这类合法结构体，即使已内置不变式字段并写了完美的精化定理，第 178 行也必然返回 `false`，造成永久误杀。
  此外，用例 `D5a-g7a` 表明，若结构体内人为混入 `bot : False` 字段并用 `False.elim e.bot` 证明 `e.flag = (e.raw == 0)`，门 7a 退出码 `0`（虽会被下游门 9 见证拦截，但在纯声明期 `--stage decl` 不含定理引用该结构时不会被 7a 单独发现）。
- 复现脚本与日志：`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_adversarial_r2.py`（日志 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_adversarial.log`，用例 `D4-g7a`、`D4b-g7a`、`D5a-g7a`）
- 实测退出码：
  - `D4-g7a`（`structure GoodBar (P : Type) [LinearOrder P]` + `theorem goodBar_ref`）：退出码 `1`（误报 `GoodBar FREE_PREDICATE`）。
  - `D4b-g7a`（`structure Window (k : Nat)` + `theorem window_ref`）：退出码 `1`（误报 `Window FREE_PREDICATE`）。
  - `D5a-g7a`（结构含 `bot : False` + `False.elim e.bot`）：退出码 `0`。
- 修复建议：第 177 至 178 行不需要拒绝非 `Sort` 的结构参数；因为第 172、175 行已强制 `xs.size == nparams + 1` 且 `x : Struct xs[0..nparams)`，已完全排除了外部追加的 `z : Empty` 参数！只要逐项校验 `xs[0..nparams)` 的类型与结构体构造器声明的 `nparams` 个参数类型一致（不含额外自由假设且不把额外空类型塞进定理望远镜），即可同时防住 `Empty` 伪精化并正确放行 `[LinearOrder P]` 与 `(k : Nat)` 参数化结构。

### [R2-B6] 门 10 漏检 `Rat.inv` / `Inv.inv`（`y⁻¹`）与 `List.headD` / `List.getLastD`，且误杀 `Int`/`Rat` 上的合法正除数 `0 < dt`

- 位置：`formal_math/verification/EnvGates.lean:553-556, 588-620`
- 根因：
  1. `operation`（第 588 行）列入了 `Nat.div`、`Int.ediv`、`Int.tdiv`、`Int.fdiv`、`Rat.div`、`HDiv.hDiv`、`Div.div`，却完全遗漏了总化求逆运算 `Rat.inv`（`Init.Data.Rat.Basic`，`0.inv = 0`）和 Mathlib 域求逆 `Inv.inv`（`y⁻¹`，`0⁻¹ = 0`，等价于 `1 / y`，`x * y⁻¹` 等价于 `x / y`）。同时第 617 行仅检查 `getD`，遗漏了同类默认值回退查询 `headD`、`getLastD`、`backD`。
  2. `guards`（第 553 至 555 行）仅在 `inferType b == Nat` 时识别 `0 < b` 与 `1 ≤ b`，对 `Int`、`Rat` 或有序域 `K` 上的正除数证据 `(_h : 0 < dt)`、`(_h : dt > 0)`、`(dt : { q : Rat // 0 < q })` 一律返回 `false`。这与第二份 Astra 审计第 6 条（"有 `Δt > 0` 证据的除法放行"）以及总计划 M16/M19b 在 `Rat`/有序域上大量使用 `0 < dt` 的实际需求冲突。
- 复现脚本与日志：
  - `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_r2_clean_verify.py`（日志 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_clean_verify.log`，用例 `F1-ratinv-g10`、`F1-clean-g10`）
  - `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_r2_last_probe.py`（日志 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_last_probe.log`，用例 `L2-invField-g10`）
  - `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_adversarial_r2.py`（日志 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_adversarial.log`，用例 `F3-g10`）
- 实测退出码：
  - `F1-ratinv-build`：退出码 `0`；`F1-ratinv-g10`（`y.inv` 与 `x * y.inv`）：退出码 `0`（完全漏检）。
  - `L2-invField-build`：退出码 `0`；`L2-invField-g10`（`y⁻¹` 与 `x * y⁻¹`）：退出码 `0`（完全漏检）。
  - `F1-clean-g10`：`headD_fn`（`xs.headD 0`）与 `getLastD_fn`（`xs.getLastD 0`）均未出现在红行输出中（漏检）。
  - `F3-g10`（合法安全写法集）：`Nat` 上全部 11 项（含 `dt ≠ 0`、`0 ≠ dt`、`dt > 0`、`dt + 1`、`1 + dt`、`Subtype`、`dite`、`Fin` 下标）与 `x / (2 : Rat)` 均正确放行；但 `safeIntPos`（`0 < dt : Int`）、`safeRatPos`（`0 < dt : Rat`）、`safeRatSubPos`（`{ q : Rat // 0 < q }`）三项被误杀，退出码 `1`（`SIGNOFF_MISSING`）。
- 修复建议：在 `operation` 中把 `Rat.inv`、`Inv.inv` 纳入无非零证据求逆检查（复用 `safeDivisor`），把 `headD`、`getLastD`、`backD` 加入回退查询集；在 `guards` 中对任意类型（含 `Int`、`Rat` 及泛型 `LT.lt`/`GT.gt`）识别 `0 < b`、`b > 0`（及 `b < 0`、`0 > b`）作为非零证据。

### [R2-B7] 门 8a `ExistsUnique` 归一化与 `premiseInstance` 存在 7 类绕过；门 7b 遇 `Chan/Hypotheses` 普通 `inductive` 命题崩溃退 2

- 位置：
  - 门 8a：`formal_math/verification/EnvGates.lean:249-301`
  - 门 7b：`formal_math/verification/EnvGates.lean:449-456`
- 根因与实测结果：
  1. 门 8a（用例 `E3-clean-g8a`，复现脚本 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_r2_clean_verify.py`，日志 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_clean_verify.log`）：以下 7 条定理零警告编译通过（`E3-clean-build` 退出 `0`），跑 `run_gates.py --gate 8a` 全部未触发报警，退出码 `0`：
     - `eu_eq_zero`：`ExistsUnique (fun y => y = f x ∧ 0 = 0)`（`stripTrue` 仅剥 `True`，不剥平凡自反等式 `a = a`）；
     - `eu_dup`：`ExistsUnique (fun y => y = f x ∧ y = f x)`（未剥重复合取项）；
     - `eu_manual_rev`：`∃ y, (∀ z, z = f x → z = y) ∧ y = f x`（`functionGraph` 第 291 行假设存在性子句必须在合取左侧）；
     - `eu_manual_id`：`∃ y, y = f x ∧ ∀ z, z = f x → id z = y`（第 299 至 300 行未对 `goal` 两侧做 `whnf`）；
     - `eu_pair`：`ExistsUnique (fun y => (y, ()) = (f x, ()))`（元组/恒等包装）；
     - `alias_mirror`：`def AliasNat := Nat; theorem alias_mirror (P : Nat → Prop) (x : AliasNat) (h : ∀ n : Nat, P n) : P x := h x`（`premiseInstance` 的 `same` 用 `withReducible`，不展开同包 `def` 类型别名）；
     - `conj_mirror`：`theorem conj_mirror (P : Nat → Prop) (h : (∀ n, P n) ∧ True) (x : Nat) : P x := h.1 x`（`premiseInstance` 不拆解 `And` 合取前提）。
  2. 门 7b（用例 `D6b-g7b`，复现脚本 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_adversarial_r2.py`，日志 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_adversarial.log`）：`gate7b` 第 450 至 456 行仅在 `getStructureInfo?` 非空时把 `Chan/Hypotheses` 归纳类型加入 `nominal` 集合（且未收录其 `rec`/`casesOn`）。在 `Chan/Hypotheses/Fixture.lean` 定义普通归纳命题 `inductive PullbackInd (n : Nat) : Prop where | mk (ok : D n = 1)` 时，门 7b 报错 `未获准展开的依赖 PullbackInd 隐藏了具体定义`，退出码 `2`。
- 修复建议：
  - 门 8a：`stripTrue` 同步化简自反等式 `a = a` 与重复合取项；`functionGraph` 对合取两序对称检查并在第 299 行对 `goal` 两侧做受控 `whnf`；`premiseInstance` 拆解 `And` 前提并使用 `.default`（或先展开同包类型别名）比较域类型。
  - 门 7b：对 `Chan/Hypotheses` 中所有 `.inductInfo`（不仅限 `structure`）统一识别为名义假设接口，并将该归纳类型的构造器、`rec`、`casesOn`、`recOn` 同步加入 `nominal`。

## 五、非阻塞观察与改进建议（Minor / Notes）

1. **M1（门 1 未校验 `lake-manifest.json` 包来源类型与 URL）**：用例 `A7-g1`（`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_adversarial_r2.py`）将 `lake-manifest.json` 中 `Cli` 的 `type` 篡改为 `"path"` 指向本地目录 `../evil_pkg` 但保留原 `rev`，`run_gates.py --gate 1` 返回退出码 `0`。建议门 1 同步校验每个钉选包的 `type == "git"` 与 `url`。
2. **M2（门 6a 若干次要语义标记未进锁哈希）**：实测以下改动在 `FM-lock-v2` 下保持哈希不变（脚本 `run_adversarial_r2.py` 与 `run_r2_extra.py`）：
   - `B1_let_vs_have`：`def` 中 `let y := ...` 改 `have y := ...`（`exprCode` 第 76 行丢弃了 `letE` 的 `nondep` 标志）；
   - `B2_hyp_unexpose`：`Chan/Hypotheses` 中公开定义去掉 `@[expose]`（门 15 仅查 `Chan/Defs` 的 `publicView`，故 `Chan/Hypotheses`/`Chan/Audit/Literal`/`ChanChallenge` 去掉 `@[expose]` 时门 6a 与门 15 均不感知，却会破坏下游展开可见性）；
   - `X1-protected-6a`（`protected` 修饰）与 `B5_noncomputable`（`noncomputable` 修饰）。
   建议至少在 `exprCode` 保留 `letE` 的 `nondep` 布尔值，并在 `statement` 编码该声明在导出视图中的暴露状态。
3. **M3（门 3 对法语引号标识符的保守误报）**：`A4c-g3` 中合法定义 `def «axiom» : Nat := 2` 因 `tokens()` 第 84 行无条件剥离 `«»` 而被门 3 误报 `TOKEN 禁用记号 axiom`。
4. **M4（门 6b 根级配置文件无归属前缀）**：`C6-g6b` 实测 `formal_math/lean-toolchain`、`formal_math/lake-manifest.json` 与 `formal_math/Chan/Smoke.lean` 当前不在任何分支前缀允许路径内；待未来工具链升级时需明确是否划入 `infra/`。
5. **M5（门 10 可选扩展项）**：`F1-clean-g10` 实测 `Nat.mod`（`x % 0 = x`）与 `Int.toNat`（负数截断为 0）未纳入检测；若后续定义中禁止静默截断，建议一并加入。

## 六、独立实证产物索引

所有脚本、沙箱与原始日志均存放于 `/Volumes/AgentStorage/fm/r2/2312-r2-tmp/`（未触碰主仓、只读工作树及一轮目录）：

- 全量提交差异：`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/diff.patch`
- 精确提交基准复跑日志：`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/baseline_rerun.log`
- 139 夹具全量自测日志：`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/selftest.log`
- 一轮 47 项对抗复跑脚本与结果：`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_adversarial_r1_replay.py`、`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r1_replay.log`、`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r1_replay_results.json`
- 第二轮主对抗脚本与结果（73 项）：`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_adversarial_r2.py`、`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_adversarial.log`、`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_results.json`
- 干净 `lakefile` 词法与配置复验（16 项）：`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_r2_fixup.py`、`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_fixup.log`、`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_fixup_results.json`
- 第二轮核心阻断项干净独立复现（29 项）：`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_r2_clean_verify.py`、`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_clean_verify.log`、`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_clean_verify_results.json`
- `statementHead` 非项目包装与 `Inv.inv` 探测（7 项）：`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_r2_last_probe.py`、`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_last_probe.log`
- 门 6a/8b/10/15 补充边界探测（6 项）：`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/run_r2_extra.py`、`/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_extra.log`
