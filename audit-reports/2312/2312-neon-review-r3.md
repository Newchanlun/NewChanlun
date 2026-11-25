VERDICT: BLOCK

# NewChanlun 票 #2312（地图 #2293 / FM-04 机械门禁）第三轮独立非作者审阅报告

## 一、绑定信息与审阅范围

- **审阅对象**：分支 `origin/infra/2312-c-gates-v3`，精确提交 `e429378e46b279392174787a4a3d4dd7fa41c4d5`
- **对照基线**：二审被判 `BLOCK` 提交 `0b991736774eaa4159baa75f2f3d35a10b67e015`
- **审阅依据**：v3 定稿（GitHub 评论 `7161329832`）、原定稿与补充（评论 `7140143526`、`7140911333`）、二审报告与主控复核（`origin/evidence/2316-2312-r2-audit-reports`）、以及实施期主控追加的两条裁定（门 3 环境层禁用属性仅查有源码声明范围常量；节点 = 有源码声明范围、类型为命题、种类为 `thmInfo | defnInfo | opaqueInfo` 且非投影）。
- **只读工作树**：`/Volumes/AgentStorage/wt-2312-v3-review`（detached HEAD `e429378e46`，仅 `source scripts/fm_env.sh` 并软链预编译 `.lake/packages`，零源码改动）；主共享检出 `/Users/silencehan/Projects/NewChanlun` 仅执行 `git fetch`。
- **探测夹具与日志目录**：`/Volumes/AgentStorage/fm/tmp/2312-v3-review/`（纯文本脚本、夹具、日志与 JSON 结果归档至证据分支 `evidence/2312-v3-review` 的 `audit-reports/2312/r3-tmp/`）。

### 实跑边界与未实跑项声明（内置盘 6 GiB 停线）

本次审阅全程在每个 Lean 批次与每条夹具前后核查内置盘 `/` 可用量（`df -h /` 与 `shutil.disk_usage("/")`），串行执行，Mathlib 全程命中预编译缓存，未触发从源码编译 Mathlib。实跑期间内置盘 `/` 可用量位于 `7.259–8.303 GiB`，在完成第 5 批 `D5b_g10_headI_fresh` 后降至 `5.815 GiB`（复查 `df -h /` 为 `5.8Gi`，低于 6 GiB 停线），随即停止一切 Lean 实跑并转为静态核验。

- **已实跑并拿到真实退出码的项**：
  - 精确提交 `e429378e46` 上 `lake build fm_audit`（11 个任务，退出码 `0`）；
  - 第 1 至第 5 批共 55 组独立对抗与合法写法探测夹具（其中所有核心 BLOCK 项均已用与 `selftest.py` 完全相同的 `selftest.base_package` 全新空包实跑并记录 `lake build --wfail` 及真实入口 `run_gates.py --gate <G>` 的标准输出、标准错误与退出码）。
- **因 6 GiB 停线未在本机实跑的项**：
  1. 被审工作树 `wt-2312-v3-review` 自身的完整 `lake build --wfail`（3,537 任务）与整套 `run_gates.py --stage all`（参考 brief 中主控 Linux 读数）；
  2. 238 项完整 `selftest.py`（`must_red=167`、`must_green=59`、`must_unknown=7`、`known_limits=5`；旧必红期望完整性已由 `git diff` 静态核对）；
  3. 两条补充验证夹具 `A1g_macro_stripinfo_all_green`（对 `@[macro]` 产出的语法树剥离 `SourceInfo` 使 `hiddenUnsafe`/`hiddenImplBy`/`hiddenVacuous` 同失声明范围，静态依据为 Lean 4.36.0 `Lean/Elab/DeclarationRange.lean:53` 与 `Audit.lean:32`、`EnvGates.lean:34,301`）与 `A1h_partial_env_only`（手写 `partial def` 直跑 `fm_audit 3`，已由 `A1f_macro_nuclear_success` 中 `hiddenPartial` 在 `fm_audit 3` 环境层零报错间接实证）；
  4. 门 6a 的 R2 历史建议项 M2（`letE` 的 `nondep` 标志与非 `Chan.Defs` 目录暴露状态，静态确认 `EnvGates.lean:70` 与 `run_gates.py:552` 未变）。

---

## 二、总体裁决与结构性核查

**结论：`BLOCK`**（硬门 BLOCK **7 项**，启发式门 BLOCK **1 项**，非阻塞建议 **9 项**）。

v3 的总体架构方向（硬门封闭世界、删掉 Python 词法正则改用 Lean 4.36.0 前端、启发式门如实降级并入库 `known_limits/`）较前两轮有显著进步，且四项专项核查结果如下：

1. **`run_gates.py` 词法正则核查（通过）**：`grep -n 're\.' formal_math/verification/run_gates.py` 仅余 6 处正则，分别用于解析 `lean --version`（`:59`）、`lakefile.toml` 的 `-D` 参数（`:90`）、工具链下载错误（`:116`）、红行格式校验（`:153`）及 `formalization.yaml` 正整数前提号（`:286, :292`），**确已无手写 Lean 词法正则**。
2. **旧必红期望是否放宽核查（通过）**：`git diff --diff-filter=MDR 0b99173677..e429378e46 -- formal_math/verification/must_red/` 仅有一处改动，即 `must_red/g2/unimported-child/formal_math/lakefile.toml` 补入 `fm_audit` 与 `FMEnvGates` 目标以适配新前端；**没有任何旧 `must_red/**/expect*.txt` 被修改或删除**，新增 72 个期望文件均为新入库样本。
3. **v3 定稿第五节三组自测补充核查（基本齐全，但有两处盲区）**：
   - 组 1（真实写法绿样本）：`deriving DecidableEq/Repr/Ord`、`termination_by`/`decreasing_by`、结构递归定理、命题类与 `instance`、`where`/`let rec`、`mutual`（`must_green/g{3,7a,9,S}/real-declarations`）、带类型类/值参数结构与精化定理（`fable-b5kill-with-residence`、`r2-d4-*`）、`Int`/`Rat` 的 `0 < dt` 除法（`real-guarded-int-rat`）、`Chan/Hypotheses` 多构造器归纳（`real-multi-constructor`）共 10 类已齐全；但**未测 `omit`、`mutual` 派生、以及带类型类参数的除法**，恰好漏过本轮 R3-H2 与 R3-H6。
   - 组 2（两轮审阅复现样本入库）：`fable-b1..b7b` 与 `r2-*` 样本已完整入库（`must_red`、`must_green`、`must_unknown`、`known_limits` 合计 238 项），但**未给 `Chan/Final` 的 `#guard_msgs` 建任何绿/红夹具**，导致 `SourceGates.lean:92` 的索引错位（`i == 3`）完全未被自测发现。
   - 组 3（`known_limits/`）：5 项（`g8a` 3 项、`g8b` 2 项）均附 `README.md`，写明了期望绿、未覆盖原因与封口层。
4. **两条新增裁定的安全性评估（当前存在可利用闭环缺口）**：
   - 裁定 1（门 3 环境层禁用属性仅查有声明范围常量）与裁定 2（节点 = 有声明范围的命题 `thm/def/opaque` 且非投影）**本身依赖前置假设「命令白名单阻断一切绕开源码声明造常量的途径」**。实测证明该前提在 `e429378e46` 上**不成立**：`SourceGates.lean` 允许 `import Lean`、`meta def` 与 `@[macro]`/`@[init]` 属性，使合法代码可在宏展开期绕开源码层；且裁定 1 直接暴露了 `Audit.lean:35`（`if info.isPartial`）对 Lean 4 编译产物（`opaqueInfo` + 无范围 `._unsafe_rec`）失效的缺陷，使 `@[macro]` 产出的非终止 `partial def` 穿透门 3 源码与环境双层。

---

## 三、硬门审阅（门 1、2、3、6a、6b、S、7a、9、10、15）

**硬门结论：BLOCK（7 项 BLOCK）**。下面严格区分「实测读数」与「严重度定性」。

### [R3-H1] 门 2 / 门 3（源码层 + 环境层）与裁定 1/2：`@[macro]`、`@[init]` 与 `grind => set_option` 绕过门 2/3 并击穿 `partial` 检测

- **位置**：`formal_math/verification/SourceGates.lean:54-58, 73-84, 118-127, 140`；`formal_math/verification/Audit.lean:32-36`；`formal_math/verification/run_gates.py:458, 468`。
- **机理**：
  1. `SourceGates.lean` 对顶层命令用白名单，但对声明属性与元编程修饰却退回**开放黑名单**（仅拦 `implemented_by`/`command_elab`/`term_elab`/`tactic`/`builtin_*`），遗漏 `macro`/`builtin_macro`、`init`/`builtin_init`、`inductive_elab`、`grind_tactic`、`doElem_elab`、`command_parser`/`term_parser`/`tactic_parser`、`export` 以及 `meta` 修饰；同时门 15 的 `EXTERNAL` 允许普通 `Chan/*` 模块直接 `public meta import Lean`。
  2. `SourceGates.lean:118-127` 只对未展开的表面语法 `cmd` 运行 `inspect`，随后直接调用 `Frontend.elabCommandAtFrontend cmd`（且 `:140` 开启了 `enableInitializersExecution`）。因此在 `Chan/Thm/Helper.lean` 注册 `@[macro Lean.Parser.Command.check]` 后，在下游写一条白名单内的 `#check Nat`，即可在精化期注入任意禁用命令与选项，且 `Helper.lean` 通过修改白名单 `set_option pp.all ...` 节点与字符串拼接规避所有源码关键字检查。
  3. **裁定 1 叠加 `Audit.lean:35` 缺陷**：Lean 4 将 `partial def f` 编译为 `opaqueInfo`（`isUnsafe = false`，`isPartial = false`）加一个**无源码声明范围**的 `f._unsafe_rec`（`isUnsafe = true`）。因为 `Audit.lean:32` 按裁定 1 跳过无声明范围常量，`f._unsafe_rec` 被跳过，而 `f` 自身 `info.isPartial == false`，结果门 3 环境层对 `partial def` 实为死检查——一旦绕开源码层（例如经 `@[macro]` 注入），非终止 `partial def` 在门 3 源码层与环境层均绿灯放行，且可被安全函数直接调用。
  4. `SourceGates.lean:54-58` 的 `setting` 只识别 `Command/Term/Tactic.set_option`，遗漏 Lean 4.36.0 新增的 `Lean.Parser.Tactic.Grind.setOption`（`Init/Grind/Interactive.lean:270`），导致 `by grind => set_option debug.skipKernelTC true in set_option linter.unusedVariables false in skip` 同时绕过门 2 与门 3。
  5. **静态推论（未实跑）**：若在宏返回值上把语法节点的 `SourceInfo` 清零（`stripInfo`，见 `r3-tmp/run_probes_batch6.py` 中 `A1g_macro_stripinfo_all_green`），Lean `Lean/Elab/DeclarationRange.lean:53` 的 `addDeclarationRangesFromSyntax` 见 `stx.getRange? = none` 直接返回、不登记范围，将使 `@[macro]` 生成的 `unsafe`、`@[implemented_by]` 与未登记空真定理同步绕过裁定 1 与裁定 2。
- **最小复现代码与实测读数**：
  1. **`@[macro]` 绕过门 2（禁用未用变量检查 + 开启 `autoImplicit`）与门 3（注入可调用的 `partial def`）**：
     夹具 `r3-tmp/cases/A1f_macro_nuclear_success/`（全新 `selftest.base_package` 空包，核心为 `Chan/Thm/Helper.lean` 注册 `@[macro Lean.Parser.Command.check]` 展开 `set_option linter.unusedVariables false`、`set_option autoImplicit true`、`partial def hiddenPartial` 等；`Chan/Thm/Victim.lean` 仅写 `#check Nat` 与 `def useAll : Nat := hiddenUnused 1 + hiddenAutoImp 2 + hiddenPartial 0 + hiddenImplBy`）。
     - 命令：`lake build --wfail` 及 `run_gates.py --repo-root <repo> --gate <2|3|S|7a|8a|8b|9|15>`（脚本 `r3-tmp/run_probes_batch5.py`，日志 `r3-tmp/batch5.log:2-13`）。
     - **实测读数**：
       - `lake build --wfail`：**退出码 `0`**（未用参数 `hiddenUnused`、自动隐式参数 `hiddenAutoImp`、无限递归 `hiddenPartial` 零告警编译通过）；
       - 门 2：**退出码 `0`**（完全放行隐藏的 `set_option linter.unusedVariables false` 与 `set_option autoImplicit true`）；
       - 门 3：退出码 `1`，**源码层 0 条报警**；环境层仅报 `hiddenUnsafe`（`ENV_UNSAFE`）与 `hiddenImplBy`（`ENV_IMPLEMENTED_BY`），**`hiddenPartial` 完全未报**（若去掉 `hiddenUnsafe`/`hiddenImplBy`，门 2、3、15 全退 `0`）；
       - 门 15：**退出码 `0`**。
  2. **`@[init]` 在 `fm_audit source` 执行期实跑任意 IO**：
     夹具 `r3-tmp/cases/A2b_init_exec_on_import/`（`Chan/Thm/InitMod.lean` 写 `@[init runOnLoad] public meta def initTrigger : Unit := ()`，`runOnLoad` 向磁盘写文件；`Chan/Thm/Importer.lean` 写 `public meta import Chan.Thm.InitMod`）。
     - 命令：同上（`r3-tmp/run_probes_batch2.py`，日志 `r3-tmp/batch2.log:132-138`）。
     - **实测读数**：`lake build --wfail` 退出码 **`0`**，门 2 退出码 **`0`**，门 3 退出码 **`0`**，门 15 退出码 **`0`**；且宿主机文件 `/Volumes/AgentStorage/fm/tmp/2312-v3-review/init_pwned2.txt` 被真实写入 `"INIT_EXECUTED_IN_AUDIT"`（22 字节）。
  3. **`grind => set_option` 绕过门 2 与门 3**：
     夹具 `r3-tmp/cases/A5c_grind_skip_kernel_opt/`：
     ```lean
     module
     public section
     theorem t (x : Nat) : x = x := by
       grind =>
         set_option debug.skipKernelTC true in
         set_option linter.unusedVariables false in
         skip
     ```
     - 命令：同上（`r3-tmp/run_probes_batch3.py`，日志 `r3-tmp/batch3.log:36-41`）。
     - **实测读数**：`lake build --wfail` 退出码 **`0`**，门 2 退出码 **`0`**，门 3 退出码 **`0`**。
- **严重度定性**：**硬门 BLOCK**。这是零告警可复现的硬绕过，直接击穿门 2 受控选项不变式、门 3 无元编程/无 `partial`/无审计期代码执行不变式，并使裁定 1/2 的前置假设失效。

---

### [R3-H2] 门 3 源码白名单：`Chan/Final` 的 `#guard_msgs` 因索引错位永久不可用，且缺失无等价替代的 `deriving instance` 与 `omit`

- **位置**：`formal_math/verification/SourceGates.lean:31-36, 91-93`。
- **机理**：
  1. Lean 4.36.0 `Init/Notation.lean:954-955` 定义 `guardMsgsCmd` 为 `(plainDocComment)? "#guard_msgs" (ppSpace guardMsgsSpec)? " in" ppLine command`。5 个子节点索引依次为 `0: docComment?`、`1: "#guard_msgs"`、`2: spec?`、**`3: " in"`**、**`4: command`**。而 `SourceGates.lean:92` 写的是 `(kind == `Lean.guardMsgsCmd && i == 3)`，把原子 `" in"` 当命令校验白名单，必报 `命令不在白名单：in`；同时对真正位于 `i == 4` 的内嵌命令传入 `command = false`，既永久封死了所有合法 `#guard_msgs`，又未按命令校验子命令。自测树中零 `#guard_msgs` 夹具。
  2. `commandKinds` 放行了 `include` 却漏掉 `Lean.Parser.Command.omit`。在门 2 强制 `linter.unusedVariables = true` 的前提下，Lean 4 会把 `section` 中满足类型依赖的 `[DecidableEq α]` 等 `variable` 实例自动纳入定理签名（见 `Lean/Parser/Command.lean:414-417`），不用该实例的定理必须用 `omit [DecidableEq α] in` 排除，否则触发未用变量告警并被 `--wfail` 拒绝。
  3. `commandKinds` 漏掉 `Lean.Parser.Command.deriving`（`deriving instance ... for ...`）。对于 `mutual inductive`，Lean 4 语法禁止行内 `deriving`，独立 `deriving instance` 是唯一不用手写样板代码的派生机制。
- **最小复现代码与实测读数**：
  1. **`Chan/Final` 合法 `#guard_msgs` 永久误红**：
     夹具 `r3-tmp/cases/A4c_guard_msgs_legal_fresh/`（全新 `selftest.base_package` 空包，`Chan/Final/LegalGuard.lean`）：
     ```lean
     module
     public section
     /-- info: Nat : Type -/
     #guard_msgs in
     #check Nat
     ```
     - 命令：`lake build --wfail` 及 `run_gates.py --gate <2|3>`（`r3-tmp/run_probes_batch3.py`，日志 `r3-tmp/batch3.log:49-54`）。
     - **实测读数**：`lake build --wfail` 退出码 **`0`**；门 3 退出码 **`1`**（`GATE3 RED formal_math/Chan/Final/LegalGuard.lean:4 TOKEN 命令不在白名单：in`）；门 2 退出码 **`2`**。
  2. **`mutual inductive` 独立派生**：
     夹具 `r3-tmp/cases/A7b_mutual_deriving/`（`Chan/Exec/MutualDerive.lean`：`mutual inductive TreeA / TreeB end` + `deriving instance Repr for TreeA, TreeB`，`r3-tmp/batch2.log:61-68`）。
     - **实测读数**：`lake build --wfail` 退出码 **`0`**；门 3 退出码 **`1`**（`命令不在白名单：Lean.Parser.Command.deriving`）；门 2 退出码 **`2`**。
  3. **`omit` 排除自动纳入的 `variable` 实例与 `include` 变量**：
     夹具 `r3-tmp/cases/A7_legal_w3_omit/` 与 `r3-tmp/cases/A7c_omit_instance_needed/`（`variable {α : Type} [DecidableEq α]` + `omit [DecidableEq α] in theorem no_dec (a : α) : a = a := rfl`，日志 `r3-tmp/batch1.log:59-65`、`batch2.log:70-75`）。
     - **实测读数**：`lake build --wfail` 退出码 **`0`**；门 3 退出码 **`1`**（`命令不在白名单：Lean.Parser.Command.omit`）；门 2 退出码 **`2`**。
- **严重度定性**：**硬门 BLOCK**。`Chan/Final` 放行 `#guard_msgs` 是 v3 定稿第三节与 README 第 43 行的明确承诺，现实现为 100% 不可用；`deriving instance`（对 `mutual inductive`）与 `omit`（配合 `--wfail` + `linter.unusedVariables`）均属 W3 常见合法构造。

---

### [R3-H3] 硬门 S + 门 8a / 8b / 9：陈述骨架放行根部连接词与 `Prop` 末端黑盒原子，18 种合法写法直接伪造全绿

- **位置**：`formal_math/verification/EnvGates.lean:260-317`（`unfoldStatement`、`skeleton`、`telescope`）。
- **机理**：
  v3 引入门 S 的初衷是关闭 R2-B2（防止用外层包装隐藏前提与结论以致盲门 8a/8b/9）。但现有 `skeleton` 与 `telescope` 存在两处结构性失配：
  1. **逻辑连接词包装**：`skeleton`（`:284-291`）在 `And`、`Or`、`Iff`、`Not`、`Exists` 下允许继续递归嵌套 `∀`/`→`（且 `Or`/`Iff`/`Not` 还将 `parallel` 置为 `false`，使 `True ↔ (...)`、`False ∨ (...)`、`¬ ¬ (...)` 连闭前提检查都不触发），但门 8a、8b、9 共用的 `telescope`（`:306-317`）**只剥离最外层的 `.forallE`**。因此把任意矛盾/镜像/冗余前提定理装进 `(x = x) ∧ (...)`、`False ∨ (...)`、`True ↔ (...)`、`¬ ¬ (...)`、`∃ _ : Nat, (...)`，门 S 全绿，而门 8a/8b/9 读到的前提数为 **0**，门 9 只需 `True` 或 `∃ x, True` 见证且无需任何 `without_i`（即便登记 `main_theorem: true`）。
  2. **`Prop` 末端黑盒原子与局部变量头**：`skeleton`（`:292-295`）遇到头为 `.fvar` 或声明末端字面为 `Prop`（`mkSort .zero`）的常量直接 `return none`，**完全不检查其 `Prop` 实参**。这使得：
     - `Eq (...) True`（`propext` 在白名单内）、`HEq (...) True`、`Nonempty (...)`（零公理！）、`Nonempty { _u : Unit // ... }`、`decide (...) = true` 全部被视为原子命题直接过门 S，甚至可以在 `Eq (...) True` 内部重新塞入被门 S 禁止的 `Option.getD`（`vac_hidden_getd`）；
     - `Chan/Thm` 内局部声明的 `inductive WrapInd (P : Prop) : Prop | mk : P → WrapInd P` 与 `structure WrapBox (n : Nat) : Prop where claim : ...` 不是 `.defnInfo`，不被 `unfoldStatement` 展开且末端为 `Prop`，直接过门 S 并让门 7a/8a/8b/9 全绿；
     - `Chan/Defs` 中锁定的 `def LockedWrap (P : Prop) : Prop := P` 因 `unfoldStatement` 跳过锁定常量而同理绕过；
     - 局部变量头 `(W : Prop → Prop) (h : W = id) : W (∀ x, x = 0 → x = 1 → False)` 与 `(P : Prop) (h : P ↔ (∀ x, x = 0 → x = 1 → False)) : P` 不仅过门 S/8a/8b，连门 9 的 `witness` 与 `without_1` 都能被平凡构造（`⟨id, rfl⟩` / `⟨fun _ => False, id⟩` 与 `⟨_, Iff.rfl⟩` / `⟨False, id⟩`）。
- **最小复现代码与实测读数**：
  夹具 `r3-tmp/cases/B1_gateS_connective_bypasses/`（7 项连接词包装）、`r3-tmp/cases/B2_gateS_atom_wrappers/`（10 项原子/变量包装）、`r3-tmp/cases/B4_locked_alias_bypass/`（1 项锁定别名），以及全新 `selftest.base_package` 复验 `r3-tmp/cases/F_B1_B2_gateS_fresh/`（精简 7 项，全部登记 `main_theorem: true`）：
  ```lean
  module
  public section
  inductive WrapInd (P : Prop) : Prop where | mk : P → WrapInd P
  theorem vac_and (x : Nat) : (x = x) ∧ (x = 0 → x = 1 → False) :=
    ⟨rfl, fun h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩
  theorem mirror_and (P : Nat → Prop) (k : Nat) : (k = k) ∧ ((∀ n, P n) → P k) :=
    ⟨rfl, fun h => h k⟩
  theorem unused_and (x : Nat) : (x = x) ∧ (x = 0 → x + 0 = x) :=
    ⟨rfl, fun _ => rfl⟩
  theorem vac_iff : True ↔ (∀ x : Nat, x = 0 → x = 1 → False) :=
    ⟨fun _ _ h0 h1 => Nat.noConfusion (h0.symm.trans h1), fun _ => trivial⟩
  theorem vac_eq : (∀ x : Nat, x = 0 → x = 1 → False) = True :=
    propext ⟨fun _ => trivial, fun _ _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩
  theorem vac_nonempty : Nonempty (∀ x : Nat, x = 0 → x = 1 → False) :=
    ⟨fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩
  theorem vac_ind : WrapInd (∀ x : Nat, x = 0 → x = 1 → False) :=
    ⟨fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩
  ```
  - 命令：`lake build --wfail` 及 `run_gates.py --gate <2|3|S|7a|8a|8b|9>`（日志 `r3-tmp/batch1.log:123-145`、`batch2.log:100-110`、`batch4.log:32-42`）。
  - **实测读数**：`B1`、`B2`、`B4` 及全新空包 `F_B1_B2_gateS_fresh` 全部 18 种写法上，**`lake build --wfail`、门 2、门 3、门 S、门 7a、门 8a、门 8b、门 9 均退出码 `0`（无任何红行）**。
- **严重度定性**：**硬门 BLOCK**。门 S 是 v3 为替代 R2-B2 所设的硬门防线，现实现可被零公理、零告警的标准写法轻松击穿，并连带致盲硬门 9 与启发式门 8a/8b。

---

### [R3-H4] 硬门 S 系统性误杀：合法闭前提、具体合取定理、Gate 16 反例与无参数 `Prop` 结构投影全部永久判红

- **位置**：`formal_math/verification/EnvGates.lean:276, 297-304`。
- **机理**：
  1. `EnvGates.lean:276` 规定 `if parallel && !e.hasFVar then return some "闭命题不能作前提或合取项"`。在 Lean 表达式中，引用顶层 `Chan/Defs` 常量的全称/命名假设（如 `PositivePrices := ∀ n, 0 < price n`）内部仅有 de Bruijn `.bvar`、**没有任何 `.fvar`**；具体实例的合取定理（如本仓 `Chan/Smoke.lean:76` 的 `20 ∈ ... ∧ 20 ∉ ...`，以及原定稿门 16 明确要求的 `Chan/Audit` 反例陈述「字面量对象满足全部前提而结论不成立」`Premise 0 ∧ ¬ Concl 0`）也同样没有 `.fvar`；带具体类型类约束 `[Pos 2]` 的定理前提也没有 `.fvar`。以上全部被门 S 永久判红，且**不存在不扭曲陈述的等价写法**。
  2. `gateS`（`:297-304`）相比 `node`（`:28-35`）**遗漏了 `(env.getProjectionStructureName? e.name).isSome` 过滤**。因此在 `Chan/Hypotheses` 定义无参数命题结构 `structure GlobalMarket : Prop where pos : ∀ n, 0 < price n` 时，Lean 自动生成的投影 `GlobalMarket.pos : GlobalMarket → ∀ n, 0 < price n` 会被送进 `gateS`，其前提 `GlobalMarket` 不含 `.fvar` 而触发 `STATEMENT_FORM` 误红。
- **最小复现代码与实测读数**：
  夹具 `r3-tmp/cases/B3_gateS_false_positives/`、`r3-tmp/cases/B3c_gateS_audit_class_proj_fp/`、`r3-tmp/cases/B3d_smoke_in_thm_gateS/`：
  ```lean
  -- Chan/Defs/Model.lean: def price (n : Nat) : Nat := n + 1
  -- Chan/Hypotheses/Market.lean:
  def PositivePrices : Prop := ∀ n : Nat, 0 < price n
  structure GlobalMarket : Prop where pos : ∀ n : Nat, 0 < price n
  -- Chan/Thm/Normal.lean:
  theorem use_named_hyp (h : PositivePrices) (k : Nat) : 0 < price k := h k
  theorem use_inline_hyp (h : ∀ n : Nat, 0 < price n) (k : Nat) : 0 < price k := h k
  theorem concrete_conj : price 0 = 1 ∧ price 1 = 2 := ⟨rfl, rfl⟩
  -- Chan/Audit/Math/Counter.lean:
  theorem counterexample : Premise 0 ∧ ¬ Concl 0 := ⟨rfl, fun h => Nat.noConfusion h⟩
  -- Chan/Thm/UseClass.lean:
  theorem with_pos [Pos 2] (n : Nat) : 0 < n + 2 := Nat.succ_pos _
  -- Chan/Thm/SmokeLike.lean:
  theorem sample_bounds : 20 ∈ sample ∧ 99 ∉ sample := by decide
  ```
  - 命令：`lake build --wfail` 及 `run_gates.py --gate S`（日志 `r3-tmp/batch1.log:147-153`、`batch3.log:20-34`）。
  - **实测读数**：三组夹具 `lake build --wfail`、门 2、门 3 均退出码 `0`；门 S 均退出码 **`1`**，逐条误报 `STATEMENT_FORM 闭命题不能作前提或合取项`，命中：`use_named_hyp`、`use_inline_hyp`、`GlobalMarket.pos`、`concrete_conj`、`counterexample`、`with_pos`、`sample_bounds`。
- **严重度定性**：**硬门 BLOCK**。这是大面积且无等价替代的永久误红，直接封死了 `Chan/Hypotheses` 闭假设在 `Chan/Thm` 中的正常引用、`Chan/Audit` 反例的标准合取形式以及无参数 `Prop` 结构定义。

---

### [R3-H5] 门 7a 居留见证绕过：把空/矛盾类型装入 `Type` 级字段即可跳过 `resident` 并空真通过 `refines`

- **位置**：`formal_math/verification/EnvGates.lean:221-241`。
- **机理**：`gate7a` 仅在结构存在直接字段满足 `proofField || isPredicate`（即字段本身是 `Prop` 证明或返回 `Prop`）时才将 `hasProp` 置 `true` 并检查 `ChanTest` 居留见证（`:233`）。若结构把矛盾放进 `Type` 级字段（如 `raw : { _n : Nat // False }`、`raw : Empty`、`raw : Fin 0`），同时带自由 `flag : Bool` 字段，则 `hasProp == false`，**完全跳过 `resident` 检查**，随后可用 `False.elim e.raw.property` / `Empty.elim e.raw` / `Fin.elim0 e.raw` 空真证明精化定理 `e.flag = (fun _ => false) e.raw`，满足 `refines` 对 `clean` 的全部要求。
- **最小复现代码与实测读数**：
  夹具 `r3-tmp/cases/C1_g7a_vacuous_subtype_bypass/`（含 `VacSub`/`VacEmpty`/`VacFin`）及全新空包 `r3-tmp/cases/F_C1_g7a_vac_fresh/`：
  ```lean
  module
  @[expose] public section
  structure VacSub where
    raw : { _n : Nat // False }
    flag : Bool
  end
  public section
  theorem vacSub_ref (e : VacSub) : e.flag = (fun _ : { _n : Nat // False } => false) e.raw :=
    False.elim e.raw.property
  ```
  `formalization.yaml` 仅登记 `refinements: {"VacSub": "vacSub_ref"}`，`ChanTest` 无任何居留见证。
  - 命令：`lake build --wfail` 及 `run_gates.py --gate <2|3|S|7a|9>`（日志 `r3-tmp/batch1.log:155-163`、`batch4.log:44-52`）。
  - **实测读数**：`C1` 与全新空包 `F_C1_g7a_vac_fresh` 上，`lake build --wfail`、门 2、门 3、门 S、**门 7a**、门 9 均退出码 **`0`**。
- **严重度定性**：**硬门 BLOCK**。门 7a v3 新增居留见证正是为了封堵空结构空真精化（`fable-b5vac`），只要把 `bot : False` 换壳为 `{ _n : Nat // False }` / `Fin 0` / `Empty` 即可原样绕过（修复方案很直接：任何需要 `refines` 的结构无条件要求 `resident`，不以 `hasProp` 为前提）。

---

### [R3-H6] 门 10 严重崩溃（退 2）：`Chan/Defs` 中带任意类型类参数的除法必然触发 `mkAppM` 异常并永久阻断

- **位置**：`formal_math/verification/EnvGates.lean:696-706`。
- **机理**：`safeDivisor` 遍历当前局部上下文 `LCtx` 中每个声明 `d`，若其类型头是结构（`getStructureInfo? env n`），便对所有字段调用 `mkAppM projFn #[x]` 检查该投影是否为除数守卫。但 Lean 4 中**所有 `class` 都是 `structure`**，其字段投影的 `self` 参数是实例隐式 `[self : C α]` 而非显式参数。于是：
  - 对无显式参数的方法或父投影（如 `Field.toCommRing`、`Inhabited.default`），`mkAppM projFn #[x]` 抛 `AppBuilder for mkAppM, too many explicit arguments provided`；
  - 对带显式参数的方法（如 `Div.div`），`mkAppM` 把 `x : Div α` 当第一个显式实参传入，引发 `type class instance expected: Div (Div α)`。
  异常被 `Audit.lean:95` 捕成**退出码 `2`（`GATE10: 无法判定`）**。因为类型类参数在签名中通常先于守卫 `_h : 0 < b` 出现，即便有合法守卫甚至已在 `garbage-signoffs.yaml` 签注，门 10 也会在抵达守卫前先崩溃，**没有任何签注或局部改写能绕开**。
- **最小复现代码与实测读数**：
  1. Mathlib 有序域除法（夹具 `r3-tmp/cases/A8_mathlib_w3_checks/`，日志 `r3-tmp/batch2.log:148-157`）：
     `def genericPosDiv {K : Type} [Field K] [LinearOrder K] (a b : K) (_h : 0 < b) : K := a / b`
     - **实测读数**：`build --wfail` 退出码 `0`，门 2/3/S 退出码 `0`，**门 10 退出码 `2`**（`AppBuilder for mkAppM, too many explicit arguments provided to @Field.toCommRing`）。
  2. 纯核心类型类除法（夹具 `r3-tmp/cases/D3_g10_typeclass_mkAppM_crash/`，日志 `r3-tmp/batch3.log:56-62`）：
     `def divWithClass {α : Type} [Div α] [LT α] [OfNat α 0] (a b : α) (_h : 0 < b) : α := a / b`
     - **实测读数**：`build --wfail` 退出码 `0`，门 2/3 退出码 `0`，**门 10 退出码 `2`**（`type class instance expected: Div (Div α)`）。
  3. 含任意无关类型类参数的 `Rat` 守卫除法（全新空包 `r3-tmp/cases/F_D3_g10_class_crash_fresh/`，日志 `r3-tmp/batch4.log:62-68`）：
     ```lean
     module
     @[expose] public section
     def divWithClass {α : Type} [Inhabited α] (_x : α) (a b : Rat) (_h : 0 < b) : Rat := a / b
     ```
     - **实测读数**：`build --wfail` 退出码 `0`，门 2/3 退出码 `0`，**门 10 退出码 `2`**（`AppBuilder for mkAppM, too many explicit arguments provided to @Inhabited.default`）。
- **严重度定性**：**硬门 BLOCK**。W3 数学包在 `Chan/Defs` 中普遍参数化于 `[LinearOrder P]` / `[Field K]` / `[IsStrictOrderedRing K]`，此缺陷会导致所有泛型有序域与带类型类约束的合法除法永久退 `2`（CI 当红且不可签注消除）。

---

### [R3-H7] 门 10 除法守卫与总化运算硬绕过：伪造 `LT`/`OfNat` 实例放行 `a / 0`，漏检 `Rat.divInt`/`mkRat`/`List.headI`/`List.getLastI`

- **位置**：`formal_math/verification/EnvGates.lean:642-671, 709-748`。
- **机理**：
  1. **伪 `LT` 实例零改动绕过守卫**：`guards`（`:666-667`）只判断 `p.isAppOfArity `LT.lt 4`、`numeral args[2]! == some 0` 和 `equal b args[3]!`，**完全不校验 `args[1]`（`LT` 实例）**。在函数体内部插一行 `let _h : @LT.lt Nat ⟨fun _ _ => True⟩ 0 b := trivial`（或对 `Rat`/`Int` 同法），`scan` 通过 `withLetDecl` 把 `_h` 放入 `LCtx`，`safeDivisor` 立刻命中并放行 `a / b`——**无需修改任何函数签名、实算 `a / 0 = 0`**。
  2. **`Int`/`Rat` 伪 `OfNat` 实例绕过**：`numeral`（`:645-649`）仅在类型为 `Nat` 时核验 `equal e (mkNatLit n)`，对 `Int` 与 `Rat` 直接信任第 2 个字面量参数。因此 `a / @OfNat.ofNat Int (nat_lit 1) ⟨0⟩` 与 `a / @OfNat.ofNat Rat (nat_lit 1) ⟨0⟩` 实为除以 `0`，而 `numeral` 误认其为 `1` 直接放行；同理 `(_h : b ≠ @OfNat.ofNat Int (nat_lit 0) ⟨1⟩)` 对 `b = 0` 成立却被当成 `b ≠ 0` 守卫放行。
  3. **漏检总化返回 `0`/`default` 的标准与 Mathlib 运算**：`operation` 漏掉了 `Rat.divInt`（`Rat.divInt a 0 = 0`）、`mkRat`（`mkRat a 0 = 0`）以及 Mathlib 中返回 `Inhabited.default` 的 `List.headI` / `List.getLastI`（不以 `!` 或 `D` 结尾，且不展开库常量）。
- **最小复现代码与实测读数**：
  夹具 `r3-tmp/cases/D1b_g10_isolated_bypasses/`、全新空包 `r3-tmp/cases/F_D1_g10_bypass_fresh/` 与全新空包 `r3-tmp/cases/D5b_g10_headI_fresh/`：
  ```lean
  module
  @[expose] public section
  def fakeLTNat (a b : Nat) : Nat :=
    let _h : @LT.lt Nat ⟨fun _ _ => True⟩ 0 b := trivial
    a / b
  def fakeLTRat (a b : Rat) : Rat :=
    let _h : @LT.lt Rat ⟨fun _ _ => True⟩ 0 b := trivial
    a / b
  def fakeOneInt (a : Int) : Int := a / @OfNat.ofNat Int (nat_lit 1) ⟨0⟩
  def fakeZeroGuard (a b : Int) (_h : b ≠ @OfNat.ofNat Int (nat_lit 0) ⟨1⟩) : Int := a / b
  def junkDivInt (a b : Int) : Rat := Rat.divInt a b
  def junkMkRat (a : Int) (b : Nat) : Rat := mkRat a b
  -- D5b_g10_headI_fresh (import Mathlib.Data.List.Basic):
  def listHeadI (l : List Nat) : Nat := l.headI
  def listGetLastI (l : List Nat) : Nat := l.getLastI
  ```
  - 命令：`lake build --wfail` 及 `run_gates.py --gate <2|3|10>`（日志 `r3-tmp/batch2.log:140-146`、`batch4.log:54-60`、`batch5.log:15-20`）。
  - **实测读数**：三组夹具上 `lake build --wfail`、门 2、门 3、**门 10 均退出码 `0`（零红行）**。
- **严重度定性**：**硬门 BLOCK**。门 10 是硬门，`fakeLTNat`/`fakeLTRat` 甚至不改函数签名就能在 `Chan/Defs` 中静默引入除零垃圾值并通过全部门禁。

---

## 四、启发式门审阅（门 7b、8a、8b）

**启发式门结论：BLOCK（1 项 BLOCK）**。按 v3 规则仅审「红的证书是否真实（无假阳性）」与「README / `known_limits/` 覆盖声明是否如实」。

### 1. 红证书真实性（假阳性核查）：通过

- **门 7b**：仅在临时内核环境 `env.addDeclCore` 接受泛化命题 `∀ F, S(F)` 且 `nominal.isEmpty` 时才签发 `GENERALIZES`，未检出假阳性。
- **门 8a**：经 Lean 4.36.0 `Lean/Meta/ExprDefEq.lean:641-682`（`checkTypesAndAssign`）静态核对与 `E1_g8a_syllogism_fp` 实跑（三段论 `P → Q, Q → R, P ⊢ R`、`5 < n → Q n` 配 `10 < k`、`0 < n → Q n` 配 `Q (k + 1)`），`isDefEq v a` 确实先校验类型定义相等再赋值，门 8a 退出码 `0`，未检出假阳性；`functionGraph` 仅对 `declarative_unique: true` 且字面裸等式生效，未检出假阳性。
- **门 8b**：仅在删除前提后经内核 `env.addDeclCore` 重放原证明成功时签发 `DROPPABLE_PREMISE`，且实测 `E3b_g8b_real_and_limits` 中正常用前提的 `by omega` 退出码 `0`，红证书真实。

### 2. README 与 `known_limits/` 覆盖如实性：发现 1 项 BLOCK（门 7b）+ 1 项建议（门 8b）

#### [R3-E1] 门 7b：`Chan/Hypotheses` 别名或辅助定理包装同目录归纳接口时门 7b 退 2，与 README 声明不符

- **位置**：`formal_math/verification/EnvGates.lean:512-520, 552-560`；`formal_math/verification/README.md:90`。
- **机理**：README 第 90 行声称「保留与具体定义绑定的 Hypotheses 归纳名义接口（含多构造器）时不签发正证书……不获准展开的普通依赖、无法读取或超时退 2」。且 `expand`（`:514`）自动展开 `Chan/Hypotheses` 中带定义体的常量（`inHyp && hasBody`）。然而 `gate7b`（`:552-558`）**仅在 `expand` 之前**从 `e.info.type` 与 `body` 采集 `nominal`。当 `Chan/Thm` 通过同属 `Chan/Hypotheses` 的别名 `PullbackAlias` 与辅助定理 `extractPullback` 间接拆解 `PullbackInd` 时，展开前 `e.info.type` 与 `body` 中尚未出现 `PullbackInd`，故 `nominal` 为空；`expand` 展开 `PullbackAlias`/`extractPullback` 暴露出 `PullbackInd` 后，第 519 行立即报错 `未获准展开的依赖 PullbackInd 隐藏了具体定义`，退出码 **`2`**（CI 视为红）。
- **最小复现代码与实测读数**：
  夹具 `r3-tmp/cases/E2_g7b_hyp_helper/`：
  ```lean
  -- Chan/Hypotheses/Fixture.lean:
  inductive PullbackInd (n : Nat) : Prop where
    | mk : D n = 1 → PullbackInd n
    | other : D n = 1 → PullbackInd n
  def PullbackAlias (n : Nat) : Prop := PullbackInd n
  theorem extractPullback {n : Nat} (h : PullbackAlias n) : D n = 1 := by
    cases h with | mk e => exact e | other e => exact e
  -- Chan/Thm/Fixture.lean:
  theorem claim (h : PullbackAlias 0) : D 0 = 1 := extractPullback h
  ```
  - 命令：`lake build --wfail` 及 `run_gates.py --gate 7b`（日志 `r3-tmp/batch1.log:181-185`）。
  - **实测读数**：`lake build --wfail` 退出码 **`0`**；门 7b 退出码 **`2`**，stderr：`GATE7b: 无法判定：未获准展开的依赖 PullbackInd 隐藏了具体定义`。
- **严重度定性**：**启发式门 BLOCK**。这是极自然的 `Chan/Hypotheses` 写法（假设族配抽取引理），却因 `nominal` 采集时机早于 `expand` 而触发未在 README 声明的退 `2` 阻断；修法廉价（在 `expand` 遇到 `owner env n` 属 `Chan.Hypotheses` 且有 `inductiveOwner` 时动态并入 `nominal`）。

---

## 五、二审 R2-B1 至 R2-B7 逐项状态核对

| 编号 | 二审病灶 | v3 (`e429378e46`) 状态 | 核对依据（实跑 / 源码） |
|---|---|---|---|
| **R2-B1** | Python 正则词法脱同步击穿门 2/3/15 | **旧病灶已修；但前端白名单出现新绕过** | Python 词法器已删，改用 `fm_audit headers/source`；`fable-b1` / `r2-a1..a4d` 已入 `must_red`。但 `@[macro]` / `@[init]` / `grind => set_option` 可零告警绕过（R3-H1），`#guard_msgs` 索引错位（R3-H2）。 |
| **R2-B2** | 非项目包装与 `True ∧ P` 击穿门 8a/8b/9 | **旧样本已拦；根问题未闭合** | 新增硬门 S 拦截 `Option.getD`、`Function.const`、`True ∧`、`let`/`have`/`fun` 并入 `must_red/gS`。但连接词外包与 `Prop` 末端原子/局部变量头仍可 18 种方式全绿绕过 S+8a+8b+9（R3-H3），且 `!hasFVar` 误杀正常闭前提与具体合取（R3-H4）。 |
| **R2-B3** | 门 8b `proofHead` 仅展开顶层致四种死用法绕过 | **已按启发式规格闭合** | `normalizeProof` 全树做 `whnfCore`/`.eta` 并展开未锁定项目常量与 `Function.const`/`And.left`/`And.right`；`fable-b3` 与 `r2-e4-*` 全部入 `must_red/g8b`，不可行边界入 `known_limits/g8b/`。仅留 `PProd.fst`/`id` 措辞建议（R3-S6）。 |
| **R2-B4** | `node` 过滤编译器辅助项不完整致误杀 | **旧误杀已修；衍生两处缺口** | 改用 `findDeclarationRangesCore?` + 种类与投影过滤，原 `b4` 与 `real-declarations` 转绿。但 `gateS` 漏掉投影过滤致 `GlobalMarket.pos` 误红（R3-H4），且 `@[macro]` 危及「用户无法造无范围常量」的前置前提（R3-H1）。 |
| **R2-B5** | 门 7a `refines` 强求 `Sort` 误杀 + `bot : False` 空结构 | **误杀已修；空结构封堵不完整** | `refines` 已放开类型类与值参数（`fable-b5kill-with-residence`、`r2-d4-*` 转绿）；`resident` 拦住 `bot : False`。但 `Type` 级空字段（`{ _n : Nat // False }` / `Empty` / `Fin 0`）仍跳过 `resident` 空真通过（R3-H5）。 |
| **R2-B6** | 门 10 漏检 `inv`/`headD`/`getLastD` 且误杀 `Int`/`Rat` 正除数 | **旧四类漏检与单调 `Int`/`Rat` 守卫已修；新引入崩溃与绕过** | `fable-b6`、`r2-f1/f2` 入 `must_red/g10`，`real-guarded-int-rat` 入 `must_green/g10`。但 `safeDivisor` 遇任意类型类参数必退 `2`（R3-H6），且伪 `LT`/`OfNat` 实例与 `Rat.divInt`/`mkRat`/`List.headI`/`List.getLastI` 绕过门 10（R3-H7）。 |
| **R2-B7** | 门 8a 漏检与门 7b 普通 `inductive` 退 2 | **门 8a 已按启发式闭合；门 7b 留有一处间接引用退 2** | 门 8a 拆 `And`、默认透明度匹配、合取无序化，其余入 `known_limits/g8a/`；门 7b 推广到全部 `Chan/Hypotheses` 归纳类型。但经 `Chan/Hypotheses` 别名/辅助定理间接使用归纳接口仍退 `2`（R3-E1）。 |

---

## 六、非阻塞建议与观察清单（9 项，不构成 BLOCK）

1. **`R3-S1`（门 3 误红名为 `tactic` 的普通变量）**：`SourceGates.lean:75-76` 对整树任何 `isIdent` 命中 `"tactic"` 即判红，实测 `A7_legal_w3_tactic_var`（`def score (tactic : Nat) : Nat := tactic + 1`，`batch1.log:116-121`）门 3 退 `1`、门 2 退 `2`。可重命名规避，建议收紧为仅检查属性语法节点（并改属性检查为白名单）。
2. **`R3-S2`（门 3 `example` 含 `sorryAx` 与 `#guard_msgs (drop warning)`）**：实测 `A5a_example_sorryAx`（`example : False := sorryAx False false`，`batch2.log:27-34`）门 2 靠 `--wfail` 报红（退 `1`），但门 3 自身退 `0`；且修复 `guardMsgsCmd` 后，需同步禁止 `#guard_msgs (drop warning)` / `(drop all)` 在 `Chan/Final` 中吞掉未用变量等编译告警（见 `Lean/Elab/GuardMsgs.lean:219-240`）。
3. **`R3-S3`（有替代写法但增加 W3 摩擦的偏严限制）**：
   - `attribute [simp] f`（`A7_legal_w3_open_scoped_and_attr`，`batch1.log:74-79`）与 Mathlib `lemma`（`A8b_mathlib_lemma`，`batch2.log:159-164`）被门 3 白名单拒绝，可分别改写为声明处 `@[simp]` 与 `theorem`；
   - `deriving Nonempty`（`A7d_deriving_nonempty`，`batch2.log:77-85`）生成带范围的命题实例 `instNonemptyPt`，门 7a/9 要求登记与写 `True` 见证（可登记消除，非永久红）；
   - 函数型自由判据 `isPivot : Nat → Prop`（`C2_g7a_func_pred_ref`，`batch2.log:112-116`）在门 7a 拒收逐点精化 `(s : BarSeq) (i : Nat) : s.isPivot i ↔ ...`，需改写函数等式 `s.isPivot = fun i => ...`。
4. **`R3-S4`（门 9 依赖前提登记为 `necessary` 退 2）**：实测 `E4_g9_dep_premise_nec`（`theorem dep_get (l : List Nat) (i : Nat) (h1 : i < l.length) (h2 : l[i] = 0) : l[i] + 1 = 1`，`batch2.log:126-130`）在 `necessary: [1, 2]` 下门 9 退出码 `2`（`无法生成闭见证命题 dep_get.without_1`）。主定理可将其标 `convenience` 绕过（但语义失真），建议文档明确依赖前提的处理口径或增加类型依赖豁免类别。
5. **`R3-S5`（门 10 可签注消除的偏严项）**：实测 `D2_g10_legal_guards`（`batch1.log:173-179`）中带 `0 < b` 的 `b⁻¹`（`Inv.inv` 不走 `safeDivisor`）与带 `b < 0` 的负除数 `a / b` 触发 `SIGNOFF_MISSING`（可签注或改 `1 / b` / `b ≠ 0` 消除，不属永久红）。另 `gtInt`/`gtRat`（`b > 0`）实测已正确放行。
6. **`R3-S6`（门 8b `README` 措辞与 `PProd.fst`/`id` 边界）**：实测 `E3b_g8b_real_and_limits`（`batch3.log:43-47`）中 `PProd.fst ⟨rfl, h⟩`、`(PProd.mk rfl h).1` 与 `(id (fun _ => rfl)) h` 在门 8b 均退 `0`（而正常用前提的 `by omega` 退 `0` 无假阳性）。`normalizeProof` 仅硬编码展开 `And.left`/`And.right`，建议补充投影函数与 `@[reducible]` 展开，或在 README 第 92 行把「投影归约」如实写明仅限 `.proj` 与 `And.left`/`And.right`。
7. **`R3-S7`（门 1 仍未校验包来源 `type` 与 `url`）**：延续 R2 M1，实测 `M1_g1_manifest_path`（`batch4.log:70-73`）把 `lake-manifest.json` 中 `Cli` 改为 `"type": "path"` 指向本地目录、保留原 `rev`，门 1 仍退出码 `0`。建议同时校验 `type == "git"` 与 `url`。
8. **`R3-S8`（门 6a 仍未编码 `letE` `nondep` 与非 `Chan.Defs` 暴露状态）**：延续 R2 M2，静态核对 `EnvGates.lean:70` 仍忽略 `letE` 的 `nondep` 布尔值，且 `run_gates.py:552` 的 `publicView` 暴露检查仅覆 `Chan.Defs`、不覆 `Chan.Hypotheses`/`Chan.Audit.Literal`/`ChanChallenge`（未在本轮实跑）。
9. **`R3-S9`（门 15 对数学目录收缩外部导入与 `meta` 边界）**：`run_gates.py:458` 的 `EXTERNAL` 向 `Chan/Defs`/`Chan/Thm`/`Chan/Proofs`/`Chan/Exec` 开放了 `Lean` 与 `Lake` 编译器内部包，是 `@[macro]` / `@[init]` 攻击面的源头。建议非 `verification.*` 目录（至多除 `ChanExplore` 外）禁止导入 `Lean`/`Lake`、禁止 `meta` 修饰与 `meta import`，从根上封闭元编程面。

---

## 七、实证产物索引

所有探测脚本、纯文本夹具、原始日志与 JSON 读数已保存于 `/Volumes/AgentStorage/fm/tmp/2312-v3-review/`，并完整归档至证据分支 `evidence/2312-v3-review` 的 `audit-reports/2312/r3-tmp/`（已排除 `.lake`、`scratch/` 及一切二进制文件）：

- `setup_and_build.sh`（环境初始化与 `lake build fm_audit` 验证）
- `run_probes_batch1.py` / `batch1.log` / `batch1.json`（E1、A1/A1b、A2、A4、A7 系列、B1、B2、B3、C1、D1、D2、E2）
- `run_probes_batch2.py` / `batch2.log` / `batch2.json`（A1c、A2b、A3/A3b、A4b、A5a/A5b、A7b/c/d、B3b、B4、C2、D1b、E3、E4、A8/A8b）
- `run_probes_batch3.py` / `batch3.log` / `batch3.json`（A1d、B3c、B3d、A5c、E3b、A4c 全新空包、D3、D4）
- `run_probes_batch4.py` / `batch4.log` / `batch4.json`（A1e、D5、全新空包 `F_B1_B2_gateS_fresh` / `F_C1_g7a_vac_fresh` / `F_D1_g10_bypass_fresh` / `F_D3_g10_class_crash_fresh`、M1）
- `run_probes_batch5.py` / `batch5.log`（全新空包 `A1f_macro_nuclear_success` 与 `D5b_g10_headI_fresh`，执行完 `D5b` 后触发 5.815 GiB 停线）
- `run_probes_batch6.py`（未实跑补充脚本，留作静态参考）
- `init_pwned2.txt`（`A2b_init_exec_on_import` 在 `fm_audit` 执行期真实写入的落盘证据）
- `cases/`（全部 55 组实跑探测夹具的纯文本 `.lean` / `.yaml` / `.json` 源码）
