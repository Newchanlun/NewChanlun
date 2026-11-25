VERDICT: BLOCK

# NewChanlun 票 #2312（FM-04 机械门禁）第四轮独立非作者审阅报告

## 一、审阅绑定与范围

- **被审分支与提交**：`origin/infra/2312-d-perimeter`，精确提交 `5c52c92856bf4aac7661a66735faa99a9817c8b4`
- **对照基线（三审 BLOCK）**：`e429378e46b279392174787a4a3d4dd7fa41c4d5`
- **规格基准**：
  - 用户重划裁定（#2312 评论 `7164343103`）：阻断门收窄为可信边界（门 1、2、3 源码层、3 环境层、6a、6b、15），按封闭世界执行；陈述质量读数（S、7a、7b、8a、8b、9、10）降为不阻断的逐声明审阅报告（`--report`）。
  - 三审报告基线：`origin/evidence/2312-v3-review:audit-reports/2312/2312-neon-review-r3.md`。
- **裁决边界**：仅由**阻断门可绕过性（甲）**、**阻断门合法代码误杀（乙）**、**`--report` 的 `certified` 假阳性或崩溃/影响阻断门退出码**，以及 **`README.md` 对阻断门承诺的如实性**决定 PASS / BLOCK。所有结论严格区分「实测读数」与「严重度定性」。
- **本机环境与停线约束**：macOS，Lean 4.36.0，复用了与被审钉选一致的预编译 `.lake/packages`（全程未触发 Mathlib 重编），所有探测串行执行且在每次调用前后核查根分区 `/` 可用空间（6.0 GiB 停线）。
  - 批 1（`run_batch1.py`，日志 `r4-tmp/logs/batch1.log`）：`P1a`、`P1b`、`P2a`、`P3a`、`P3b`、`P3c`、`P4a` 实跑完成，至 `P5a` 后 `/` 降至 `5.959 GiB` 按纪律自动停线。
  - 磁盘恢复至 `7.095 GiB` 后，完成纯 Python 门 1 / 门 6b 探测（`run_gate1_pure.py`、`run_gate6b_pure.py`）、零 Mathlib 快批（`run_batch_fast.py`，20 组全跑完，退出 0，`/` 收于 `6.238 GiB`）与精准补测批（`run_batch_surgical.py`，含零导入 RCE、门 3 环境层修复版探针、`sudo set_option` 清洁版、W3 代表性综合证明等，详见各节实测读数）。

---

## 二、总体裁决与结构性核查

**结论：BLOCK。**

本轮实现将门 3 源码层从开放黑名单重写为封闭白名单 + 精化后信息树复核，将门 3 环境层改为全常量枚举 + 三类生成来源豁免，并把陈述质量读数完整拆入 `--report`（退出码恒 0），方向正确且扎实关闭了三审 R3-H1 / R3-H2 中的多项根因。

但实跑探测表明，阻断门仍存在 **6 项甲类可信边界绕过 BLOCK**（含纯零导入在 `fm_audit source` 审计期直接写宿主机文件且全阻断门零告警退 `0`、白名单 Mathlib `sudo set_option` 静默篡改所有受控与内核选项、`lakefile.toml` 绕过门 2、`#guard_msgs (substring := true)` 无 `drop` 吞一切错误/告警且放行 `deriving instance`、门 3 环境层压制 `ENV_EXTERN` 并可伪造豁免 1/3、以及 `_root_.sorryAx` 绕过单独门 3）、**2 项乙类合法 W3 代码误杀 BLOCK**（普通递归类型 `deriving Ord` 触发门 3 `ENV_PARTIAL`、`Chan/Defs/` 中任何类型 `deriving Repr`/`Hashable` 触发门 15 `EXPOSE_SECTION`）以及 **1 项其他 BLOCK**（`README.md` 对阻断门的多处承诺失实）。

### 旧阻断门 `must_red` 夹具未弱化核查

执行 `git diff --diff-filter=MDR e429378e46b279392174787a4a3d4dd7fa41c4d5..5c52c92856bf4aac7661a66735faa99a9817c8b4 -- formal_math/verification/must_red/{g1,g2,g3,g6a,g6b,g15}`：
- **实测读数**：输出为空（**0 个旧阻断门 `must_red` 文件被修改、删除或重命名**）。
- 新增改动中，`must_red/g3/private-proof/` 仅新增 `environment-only.txt` 与 `modules.txt`（因新表层预检已提前拦下 `sorryAx` 标识符，改为直调门 3 环境层继续锁定私有证明体的 `ENV_SORRY` 回归，期望红码 `ENV_SORRY` 未弱化）；原 `gS`/`g7a`/`g7b`/`g8a`/`g8b`/`g9`/`g10` 夹具按新裁定迁入 `report_cases/`。**本项核查通过。**

---

## 三、甲、阻断门可绕过性审阅（可信边界不变式 (a)–(f)）

### [R4-A1]（BLOCK）不变式 (c) & 审计期不执行被审代码：零额外导入经 `include_str (unsafe (unsafeIO ...))` 在 `fm_audit source` 审计期任意读写宿主机文件，且环境零残留、全阻断门零告警退 `0`

- **位置**：
  - `formal_math/verification/SourceGates.lean:78-81`（`forbidden` 仅含 `Lean.Parser.Command.unsafe`，未含项级 `Lean.Parser.Term.unsafe`）
  - `formal_math/verification/SourceGates.lean:115-158, 197-217`（未禁止在精化期对用户表达式求值的内置/库项精化器：`Init` 的 `include_str`、`by_elab`；`Mathlib` 的 `eval%`、`trace`、`success_if_fail_with_msg`、`from_lrat`）
  - 对照 Lean 4.36.0 源码：`Init/Notation.lean:744`、`Lean/Elab/BuiltinTerm.lean:431-446`（`elabIncludeStr` 调 `evalTerm System.FilePath`）、`Lean/Elab/BuiltinNotation.lean:555-580`（`elabUnsafe` 处理 `unsafe <term>`）、`Lean/Elab/Eval.lean:17`（`evalTerm` 在 `withoutModifyingEnv` 内编译并执行）。
- **机理**：
  1. **路径一（零额外导入任意宿主机 IO 读写 + 环境零残留，`P0_zero_import_io_rce_in_audit`）**：
     `SourceGates.lean:81` 只禁止命令修饰符 `Lean.Parser.Command.unsafe`（`unsafe def`），放行项级表达式 `unsafe <term>`（`Lean.Parser.Term.unsafe`；已在 `P7d_term_unsafe_expr` 单独实测 `fm_audit source ... 3` 返回 `rc=0, [false,[]]`）。同时 `Init` 内置的 `include_str <path>` 在精化期调用 `evalTerm` 编译并求值 `<path>`，且 `evalTerm` 运行在 `withoutModifyingEnv` 内。因此，仅凭标准 `module`（**零 `import`**）在 `include_str` 内嵌套 `unsafe (unsafeIO (do IO.FS.writeFile ...; return ...))`：
     - 在 `fm_audit source` 阶段（连 `lake build` 都尚未运行！）即执行任意宿主机 `IO.FS.writeFile`（同理可执行 `IO.Process.output`）并读取任意宿主机文件；
     - `evalTerm` 退出时把 `elabUnsafe` 生成的临时 `unsafe` / `implemented_by` 常量彻底回滚出环境，`include_str` 只留下一个普通 `String` 字面量；
     - 最终 `.olean` 环境中**零 `unsafe`、零 `implemented_by`、零额外公理**，全阻断门零告警通过！
  2. **路径二（即使封死 `Term.unsafe`，纯 `include_str` 仍可在审计期执行用户求值并读取宿主机任意文件，`P3b2_include_str_clean`）**：
     `include_str (dbgTrace "INCLUDE_STR_EVAL_RAN" fun _ => "<宿主机绝对路径>")` 不使用 `unsafe`，无需额外导入，仍在 `fm_audit source` 与构建期执行用户表达式，把宿主机机密文件内容读入常量并用 `:= rfl` 证明外泄，全阻断门零告警通过。
  3. **路径三（白名单 Mathlib 求值精化器在审计期执行用户代码，`P3a_eval_percent`、`P3d_mathlib_trace_and_siffwm_eval`）**：
     允许导入的 `Mathlib.Tactic.Eval`（`eval%`）、`Mathlib.Tactic.Trace`（`trace`）、`Mathlib.Tactic.SuccessIfFailWithMsg`（`success_if_fail_with_msg`）均在精化期调用 `evalExpr`/`evalTerm` 运行用户表达式；`P3a_eval_percent` 已实测在 `fm_audit source` 和构建期执行用户代码且全阻断门零告警退 `0`；`P3d_mathlib_trace_and_siffwm_eval` 实测 `trace` 与 `success_if_fail_with_msg` 均在审计/构建期执行用户求值代码（门 3=0、门 15=0，仅 `trace` 触发 `unusedTactic` 告警使门 2 退 1，`success_if_fail_with_msg` 自身零告警）。
  4. **路径四（`sudo set_option compiler.checkMeta false` + `Batteries.Lean.LawfulMonad` + `by_elab` 获取完整 `TermElabM` 元编程权限与宿主机 IO，`P1d_sudo_by_elab_io_audit`）**：
     白名单库 `Batteries.Lean.LawfulMonad` 公开导入 `Lean.Elab.Command`（使 `Lean.Elab.Term.TermElabM`、`Lean.mkNatLit` 等进入作用域）；原本模块相检查（`Lean/Compiler/LCNF/Visibility.lean:95`）会拒绝在 `by_elab` 内引用非 `meta` 导入的 `Lean` 符号（已在 `P1a_by_elab_io_audit` 实测确认），但叠加 `sudo set_option compiler.checkMeta false in`（`Visibility.lean:63` 直接跳过相检查）即可在 `by_elab do ...` 内执行完整 `TermElabM` 任意元编程与宿主机 `IO` 写入，且全阻断门零告警退 `0`！
- **最小复现与实测读数**：
  1. **`P0_zero_import_io_rce_in_audit`**（夹具 `r4-tmp/cases/P0_zero_import_io_rce_in_audit/`，日志 `r4-tmp/logs/batch_surgical.log:3-14`、`r4-tmp/batch_surgical.jsonl:1`）：
     ```lean
     module
     public section
     @[expose] def payload : String :=
       include_str (unsafe (
         match unsafeIO (do
           IO.FS.writeFile "/Volumes/AgentStorage/fm/tmp/2312-d-review/sentinel_zero_import_rce.txt"
             "ZERO_IMPORT_IO_EXECUTED_IN_AUDIT"
           return System.FilePath.mk "/Volumes/AgentStorage/fm/tmp/2312-d-review/host_secret_probe.txt") with
         | .ok p => p
         | .error _ => System.FilePath.mk ""))
     theorem exfiltrated : payload = "TOP_SECRET_HOST_CONTENT_42\n" := rfl
     ```
     - **实测读数**：
       - 构建前直调 `lake exe fm_audit source Chan.Thm.ZeroImportRCE Chan/Thm/ZeroImportRCE.lean 3`：退出码 **`0`**，输出 `[false,[]]`，且宿主机哨兵文件立即被写入 `"ZERO_IMPORT_IO_EXECUTED_IN_AUDIT"`；
       - `lake build --wfail +Chan.Thm.ZeroImportRCE:olean`：退出码 **`0`**（零警告）；
       - `run_gates.py --gate 2` / `--gate 3` / `--gate 15`：退出码均为 **`0`**，且哨兵文件再次被写入。
  2. **`P1d_sudo_by_elab_io_audit`**（夹具 `r4-tmp/cases/P1d_sudo_by_elab_io_audit/`，日志 `r4-tmp/logs/batch_surgical.log:55-66`、`r4-tmp/batch_surgical.jsonl:7`）：
     ```lean
     module
     import Mathlib.Tactic.SudoSetOption
     import Batteries.Lean.LawfulMonad
     public section
     def pwn : Nat :=
       sudo set_option compiler.checkMeta false in
       by_elab do
         IO.FS.writeFile "/Volumes/AgentStorage/fm/tmp/2312-d-review/sentinel_sudo_by_elab_pwned.txt"
           "SUDO_BY_ELAB_EXECUTED_IN_AUDIT"
         return Lean.mkNatLit 42
     ```
     - **实测读数**：
       - 构建前直调 `lake exe fm_audit source Chan.Thm.SudoByElab Chan/Thm/SudoByElab.lean 3`：退出码 **`0`**，输出 `[false,[]]`，且宿主机哨兵文件立即被写入 `"SUDO_BY_ELAB_EXECUTED_IN_AUDIT"`；
       - `lake build --wfail +Chan.Thm.SudoByElab:olean`：退出码 **`0`**（零警告）；
       - `run_gates.py --gate 2` / `--gate 3` / `--gate 15`：退出码均为 **`0`**，且哨兵文件再次被写入。
  3. **`P3b2_include_str_clean`**（夹具 `r4-tmp/cases/P3b2_include_str_clean/`，日志 `r4-tmp/logs/batch_fast.log:1-10`、`r4-tmp/batch_fast.jsonl:1`）：
     ```lean
     module
     public section
     @[expose] def leaked : String :=
       include_str (dbgTrace "INCLUDE_STR_EVAL_RAN" fun _ => "/Volumes/AgentStorage/fm/tmp/2312-d-review/host_secret_probe.txt")
     theorem leaked_eq : leaked = "TOP_SECRET_HOST_CONTENT_42\n" := rfl
     ```
     - **实测读数**：`lake build --wfail` 退出码 **`0`**（输出 `info: INCLUDE_STR_EVAL_RAN`），`--gate 2` / `--gate 3` / `--gate 15` 退出码均为 **`0`**。
  4. **`P3a_eval_percent`**（夹具 `r4-tmp/cases/P3a_eval_percent/`，日志 `r4-tmp/logs/batch1.log:78-85`）：
     `import Mathlib.Tactic.Eval` 下写 `def answer : Nat := eval% (dbgTrace "EVAL_PCT_USER_CODE_RAN" fun _ => 42)`：
     - **实测读数**：`lake build --wfail` 退出码 **`0`**（输出 `EVAL_PCT_USER_CODE_RAN`），`--gate 2` / `--gate 3` / `--gate 15` 退出码均为 **`0`**。
- **严重度定性**：**BLOCK（甲）**。零依赖、零告警、全阻断门退 `0` 下直接击穿不变式 (c) 与 `README.md:25, 82-89`「审计程序不执行被审代码」「精化期运行的代码只剩钉选库」的核心安全边界。

---

### [R4-A2]（BLOCK）不变式 (a)(b)：`Mathlib.Tactic.SudoSetOption`（由 `Mathlib.Tactic.Common` 再导出）绕过门 2/3 全部选项检查，可在任意项/战术位置篡改受控选项与内核选项

- **位置**：
  - `formal_math/verification/SourceGates.lean:96-99`（`setting` 仅检查 `stx[0] == "set_option"`）
  - `formal_math/verification/SourceGates.lean:197-217`（`elaborated` 仅依赖信息树 `OptionInfo`）
  - 对照钉选库：`Mathlib/Tactic/SudoSetOption.lean:50-54`（`elab "sudo " "set_option " n:ident val " in " body:term : term` 直接修改 `Core.Context.options`，不经 `Lean.Elab.elabSetOption`，不写入 `OptionInfo`），且由 `Mathlib/Tactic/Common.lean` 公开再导出。
- **机理**：
  语法首原子为 `"sudo"` 而非 `"set_option"`，表层 `setting` 漏检；精化器直接 `withReader (fun ctx => { ctx with options := opts.insert ... })`，信息树产生 **0 条 `OptionInfo`**，精化后复核漏检。用户可借此在可信源码中任意设置 `linter.unusedVariables false`、`autoImplicit true`、`relaxedAutoImplicit true`、`debug.skipKernelTC true`、`smartUnfolding false`、`compiler.checkMeta false` 等所有受控/禁用选项，并可在 `by` 战术块外层实效压制未用变量告警（`Lean/Linter/UnusedVariables.lean:431-433`）。
- **最小复现与实测读数**：
  - 夹具 `r4-tmp/cases/P2b_sudo_set_option_clean/`（日志 `r4-tmp/logs/batch_surgical.log`、`r4-tmp/batch_surgical.jsonl:6`）：
    ```lean
    module
    import Mathlib.Tactic.SudoSetOption
    public section
    def setControlledOpts : Nat :=
      sudo set_option debug.skipKernelTC true in
      sudo set_option autoImplicit true in
      sudo set_option relaxedAutoImplicit true in
      sudo set_option smartUnfolding false in
      sudo set_option linter.unusedVariables false in
      0

    theorem silenceUnusedInTactic : True :=
      sudo set_option linter.unusedVariables false in
      by
        have unusedLocal : Nat := 42
        trivial
    ```
  - **实测读数**：`lake build --wfail +Chan.Thm.SudoClean:olean` 退出码 **`0`**（未用变量 `unusedLocal` 零告警通过），`run_gates.py --gate 2` 退出码 **`0`**，`--gate 3` 退出码 **`0`**，`--gate 15` 退出码 **`0`**。
- **严重度定性**：**BLOCK（甲）**。尽管 `README.md:116` 声明「库代码用 `withOptions` 改选项看不到」，但 `sudo set_option` 并非库内部固定逻辑，而是向被审源码直接暴露任意 `set_option` 能力的通用项精化器；允许它存在使门 2「任何语法位置不得设置受控选项」与不变式 (a) 形同虚设。

---

### [R4-A3]（BLOCK）不变式 (a) & 门 2：`lakefile.toml` 的目标 `moreLeanArgs` 与包级 `[leanOptions]` 绕过门 2，可静默关闭 `linter.unusedVariables.funArgs`、`linter.deprecated` 及开启 `debug.skipKernelTC`

- **位置**：`formal_math/verification/run_gates.py:83-105`。
- **机理**：
  1. 第 89–91 行对 `moreLeanArgs`/`weakLeanArgs` 仅用正则匹配 `(autoImplicit|relaxedAutoImplicit|linter\.unusedVariables)=`，遗漏所有子键（如 `-Dlinter.unusedVariables.funArgs=false`、`-Dlinter.unusedVariables.patternVars=false`、`-Dlinter.unusedVariables.analyzeTactics=false`）、其他 `linter.*`（如 `-Dlinter.deprecated=false`）以及内核/编译器开关（`-Ddebug.skipKernelTC=true`）。
  2. 第 86–87 行对 `package` 级清空 `overrides = set()`，导致包级 `[leanOptions]` 中可直接设置 `linter.deprecated = false`、`debug.skipKernelTC = true` 等非三项核心键而零报警（同样，目标级 `leanOptions` 设置 `debug.skipKernelTC = true` 也不命中 `controlled | {"linter"}`）。
- **最小复现与实测读数**：
  1. **`P6b_lakefile_moreLeanArgs_bypass`**（夹具 `r4-tmp/cases/P6b_lakefile_moreLeanArgs_bypass/`，日志 `r4-tmp/logs/batch_fast.log:33-36`、`r4-tmp/batch_fast.jsonl:4`）：
     在 `[[lean_lib]] name = "Chan"` 下添加 `moreLeanArgs = ["-Dlinter.unusedVariables.funArgs=false", "-Ddebug.skipKernelTC=true"]`，源码含未用形参 `def hasUnusedArg (unusedParam : Nat) : Nat := 0`：
     - **实测读数**：`run_gates.py --gate 2` 退出码 **`0`**，`--gate 3` 退出码 **`0`**。
  2. **`P6c_lakefile_pkg_leanOptions_bypass`**（夹具 `r4-tmp/cases/P6c_lakefile_pkg_leanOptions_bypass/`，日志 `r4-tmp/logs/batch_surgical.log:41-45`、`r4-tmp/batch_surgical.jsonl:5`）：
     在包级 `[leanOptions]` 添加 `linter.deprecated = false` 与 `debug.skipKernelTC = true`，源码调用 `@[deprecated]` 函数 `def useOld : Nat := oldFn`：
     - **实测读数**：`run_gates.py --gate 2` 退出码 **`0`**，`--gate 3` 退出码 **`0`**。
- **严重度定性**：**BLOCK（甲）**。直接违背不变式 (a) 与 `README.md:24`「`autoImplicit`、`relaxedAutoImplicit`、`linter.*` 不得在 Lake 目标或源码的任何语法位置设置」（也是门 2 独立防御职责，同自测 `must_red/g2/r2-a5-build-config`、`r2-a6*-build-config`）。

---

### [R4-A4]（BLOCK）不变式 (a)(b) & 门 3 源码层：`Chan/Final` 中 `#guard_msgs (substring := true)` 无需 `drop` 即吞掉一切错误与告警，且 `#guard_msgs` 内放行 `deriving instance`

- **位置**：
  - `formal_math/verification/SourceGates.lean:132-134, 143-145, 208`
  - 对照 Lean 4.36.0 源码：`Lean/Elab/GuardMsgs.lean:210, 231-239`。
- **机理**：
  1. 当 `#guard_msgs (substring := true) in <cmd>` 不附 docstring 时，`expected = ""`，`Lean/Elab/GuardMsgs.lean:231-239` 判定 `(whitespace.apply res).contains ""` 恒真，从而把内嵌命令产生的所有 `info`、`warning` 乃至 `error` 全部清空，完全不需要出现被禁原子 `"drop"`（`SourceGates.lean:143-145`）。
  2. `SourceGates.lean:132-134` 仅在 `#guard_msgs` 内禁止 `declaration` 与 `mutual`，遗漏同样往环境写入声明的 `Lean.Parser.Command.deriving`（`deriving instance ...`）以及 `attribute`；同时 `elaborated`（`:208`）检查展开后命令时把 `guarded` 硬编码为 `false`，导致派生处理器在 `#guard_msgs` 内生成的声明同样逃过「`#guard_msgs` 内不得出现声明」约束。
- **最小复现与实测读数**：
  - 夹具 `r4-tmp/cases/P5b_guard_msgs_clean_swallow/`（日志 `r4-tmp/logs/batch_surgical.log:29-39`、`r4-tmp/batch_surgical.jsonl:4`）：
    ```lean
    -- Chan/Final/GuardSwallow.lean
    module
    import Chan.Thm.Dep
    public section
    #guard_msgs (substring := true) in
    #check (1 : String)
    #guard_msgs (substring := true) in
    #check oldFn
    #guard_msgs (substring := true) in
    deriving instance Repr for PairTag
    ```
  - **实测读数**：
    - `lake build --wfail +Chan.Final.GuardSwallow:olean +Chan.Thm.Dep:olean`：退出码 **`0`**（类型错误 `1 : String`、废弃告警 `oldFn` 与派生失败错误均被静默吞掉）；
    - `run_gates.py --gate 2`：退出码 **`0`**；`--gate 15`：退出码 **`0`**；
    - `run_gates.py --gate 3`：源码层 **0 条报警**（仅门 3 环境层因 `PairTag` 私有导入导致派生出错产出含 `sorryAx` 的占位实例而报 `ENV_SORRY`；对于前两条 `#check` 或成功/带告警的 `deriving instance`，门 2/3/15 全退 `0`）。
- **严重度定性**：**BLOCK（甲）**。直接绕过 `README.md:49` 对 `#guard_msgs` 的两条机械封堵（「内嵌命令不得是声明」「规格不得含 `drop`」），使 `Chan/Final` 可在不触发 `--wfail` 的情况下屏蔽错误、告警并嵌套生成声明。

---

### [R4-A5]（BLOCK）不变式 (d) & 门 3 环境层：`generatedBy` 豁免压制 `ENV_EXTERN`（直接违背 README），且豁免 1（`ctorIdx`）与豁免 3（派生辅助函数）均可被手写 `unsafe`/`partial`/`implemented_by` 伪造通过 `fm_audit 3`

- **位置**：`formal_math/verification/Audit.lean:29-42, 55-93, 117-128`。
- **机理**：
  1. **`ENV_EXTERN` 被豁免压制（`:117-128`）**：`isExtern env name` 被并入 `flagged` 并在 `(← generatedBy name info implTargets).isNone` 门后检查，因此给任何满足 `generatedBy` 的常量（如 `Color.ctorIdx`、`Color.ctorIdx._impl`、`myRec._unsafe_rec`）附加 `@[extern "..."]`，`ENV_EXTERN` 被完全跳过——直接违背 `README.md:95`「`extern` 与 `meta` 没有豁免」。
  2. **豁免 1（`ctorIdxImpl`，`:29-42`）可伪造**：`isCtorIdxCore?` 仅查常量名形如 `T.ctorIdx` 且 `T` 为归纳类型，未核验 `T` 非 `Prop`（Lean 不为 `Prop` 归纳类型生成 `ctorIdx._impl`）、未核验多构造子、未核验实现名必须为 `mkCtorIdxImplName T`、未核验参数类型与 `T` 的绑定关系。手写任意名字的 `unsafe def fakeImpl (n : Nat) : Nat := @getObjTagNat Nat n` 与 `@[implemented_by fakeImpl] def MyProp.ctorIdx (n : Nat) : Nat := 0` 即可命中豁免 1。
  3. **豁免 3（派生辅助函数，`:71-92`）可伪造**：仅校验辅助函数与实例名字前缀吻合、重算的 `Deriving.mkContext` 有 `usePartial = true`，以及实例体字面「出现」了辅助函数名（哪怕是丢弃绑定 `let _ := @instReprTree.repr`）；既未核验 `inst` 确由派生生成，也未核验辅助函数的类型签名或函数体。手写任意发散的 `partial def instReprTree.repr (n : Nat) : Nat := repr (n + 1)` 与引用它的 `instance instReprTree : Repr Tree`，即可令该手写发散函数通过环境层并被同/下游安全函数直接调用。
- **最小复现与实测读数**（按自测 `environment-only` 同一口径直调 `lake exe fm_audit 3`，测环境层独立纵深防御）：
  1. **`P7c_env_extern_on_exempt`**（夹具 `r4-tmp/cases/P7c_env_extern_on_exempt/`，日志 `r4-tmp/logs/batch_fast.log:54-59`、`r4-tmp/batch_fast.jsonl:7`）：
     给 `Color.ctorIdx`、`Color.ctorIdx._impl`、`myRec._unsafe_rec` 分别挂 `attribute [extern "evil_c_*"]`：
     - **实测读数**：`lake build` 零告警退 **`0`**，`lake exe fm_audit 3 Chan.Thm.ExternExempt ChanTest.Probe` 退出码 **`0`**（0 条红行）。
  2. **`P7b2_env_ctoridx_spoof_fixed`**（夹具 `r4-tmp/cases/P7b2_env_ctoridx_spoof_fixed/`，日志 `r4-tmp/logs/batch_surgical.log:15-20`、`r4-tmp/batch_surgical.jsonl:2`）：
     `inductive MyProp : Prop | mk` + `unsafe def fakeImpl (n : Nat) : Nat := @getObjTagNat Nat n` + `@[implemented_by fakeImpl] def MyProp.ctorIdx (n : Nat) : Nat := 0`：
     - **实测读数**：`lake build` 零告警退 **`0`**，`lake exe fm_audit 3 Chan.Thm.SpoofCtorIdx ChanTest.Probe` 退出码 **`0`**。
  3. **`P7a2_env_deriving_spoof_clean`**（夹具 `r4-tmp/cases/P7a2_env_deriving_spoof_clean/`，日志 `r4-tmp/logs/batch_surgical.log:22-27`、`r4-tmp/batch_surgical.jsonl:3`）：
     在 `inductive Tree | leaf | node (cs : List Tree)` 下手写发散 `partial def instReprTree.repr (n : Nat) : Nat := repr (n + 1)`、`instance instReprTree : Repr Tree`（含 `let _ := @instReprTree.repr`）与 `def callPartial (n : Nat) : Nat := instReprTree.repr n`：
     - **实测读数**：`lake build` 零告警退 **`0`**，`lake exe fm_audit 3 Chan.Thm.SpoofDeriveClean ChanTest.Probe` 退出码 **`0`**。
- **边界说明与严重度定性**：**BLOCK（甲）**。上述三例走完整 `run_gates.py --gate 3` 时会被源码层白名单拦截（源码层禁止手写 `extern`/`unsafe`/`partial`/`implemented_by`）；但它们直接击穿了**门 3 环境层的独立不变式**与 `README.md:26, 95-108` 的机械复核承诺（尤其是 `ENV_EXTERN` 被豁免压制，属于明确代码缺陷且与文档自相矛盾）。

---

### [R4-A6]（BLOCK）门 3 源码层：`_root_.sorryAx` 绕过 `example` 占位证明封堵，单跑 `--gate 3` 与 `--gate 15` 均退 `0`

- **位置**：`formal_math/verification/SourceGates.lean:86, 141`（均只比对 `stx.getId.eraseMacroScopes == `sorryAx`）。
- **机理**：`example` 不向环境写入常量，环境层看不到它；本轮针对三审 `r3-a5a-example-sorryax` 在源码层加了 `== `sorryAx` 检查，但加了 `_root_.` 前缀后标识符为 `` `_root_.sorryAx ``，完全绕过该比对。
- **最小复现与实测读数**：
  - 夹具 `r4-tmp/cases/P7e_root_sorryAx_example/`（日志 `r4-tmp/logs/batch_fast.log:73-84`、`r4-tmp/batch_fast.jsonl:9`）：
    ```lean
    module
    public section
    example : False := _root_.sorryAx False false
    ```
  - **实测读数**：`run_gates.py --gate 3` 退出码 **`0`**，`run_gates.py --gate 15` 退出码 **`0`**（全组合下被门 2 `lake build --wfail` 报 `declaration uses sorry` 拦下，退出 `1`）。
- **严重度定性**：**BLOCK（甲）**。单独运行门 3 时直接放行 `sorryAx`，破坏了针对 `r3-a5a-example-sorryax` 的专项修复与不变式 (b)(d) 的独立闭环。

---

### 甲类其余攻防核查记录（已确认守住或归入建议项）

1. **信息树空洞 `decreasing_by`（`P4a_decreasing_by_rfl_prime`，日志 `r4-tmp/logs/batch1.log:162-172`）——已守住**：
   在 `decreasing_by` 中写库宏 `rfl'`（展开 `smartUnfolding`）与 `unhygienic`（展开 `tactic.hygienic`），实测 `SourceGates.lean:262-265` 的 `substituteLazy` + `t.substitute infos.assignment` 成功展开了异步子树，门 3 退出 **`1`** 并同时抓出两条 `选项不在白名单：smartUnfolding` / `tactic.hygienic`！（说明作者在 `README.md:114` 里反而低估了 `substituteLazy` 对 `decreasing_by` 的覆盖能力。）
2. **门 6a 声明锁（`P9a_gate6a_let_vs_have`、`P9b_gate6a_hyp_no_expose`，日志 `r4-tmp/logs/batch_fast.log:136-150`）——欠编码观察（归入建议项，见下文）**：
   - `EnvGates.lean:72` 序列化 `.letE _ t v b _` 时丢弃 `nondep : Bool`，实测把 `Chan/Defs/V.lean` 中锁定定义从 `let x := n + 1; x + x` 改为 `have x := n + 1; x + x` 后，门 6a 返回 **`0`**；
   - `Chan/Hypotheses/` 去掉 `@[expose]` 后，门 6a 与门 15 均返回 **`0`**（门 6a 读私有环境且未编码可见性/暴露态，门 15 仅查 `Chan/Defs`）。
3. **门 6b 路径权限（`run_gate6b_pure.py` + `P9c_gate6b_probes`，结果 `r4-tmp/gate6b_pure.json`、`r4-tmp/batch_fast.jsonl:17`）——核心防线守住，3 处边缘观察归入建议项**：
   - 已守住：`proof/*` 提交改 `Chan/Defs` 再在工作树撤回仍红（rc=1）；`proof/*` 未跟踪 `Chan/Defs/Sneak.lean` 判红（rc=1）；`infra/*` 写非空签注判红（rc=1）；`infra/*` 仅允许从无到有初始化空 `{}` 签注（rc=0，写入非空即 rc=1）。
   - 边缘观察（建议项）：`decl/` 空后缀（`GITHUB_HEAD_REF=decl/`）退出 `0`；仓根未跟踪文件（`stray.txt`）被 `ls-files -- formal_math scripts .github/workflows` 忽略（rc=0）；`Chan/Thm/` 内符号链接可进入 `proof/*`（rc=0）。
4. **门 15 模块方向（`P9d1`、`P9d2`，日志 `r4-tmp/logs/batch_fast.log:158-174`）——边界守住**：
   - `ChanChallenge` 经 `Chan/Defs` 间接导入 `Std.Data.HashMap` 实测触发门 15 退 **`1`**（`IMPORT_CLOSURE`）；`Chan/Defs` 中 `noncomputable def` 正常放行（rc=0）。
5. **门 1 钉选（`run_gate1_pure.py`，结果 `r4-tmp/gate1_pure.json`）——如实披露**：
   - 篡改 `lake-manifest.json` 中 `Cli` 的 `type` 为 `"path"`、`url` 为恶意地址而保留 `rev` 不变，门 1 退出 **`0`**；该缺口已在 `README.md:117` 明确披露（R3-S7），不重复判 BLOCK，记为建议项。
6. **允许的声明级机制 `local instance (priority := high)` / `@[simp]` / `attribute [-simp]`（`P8a_instance_priority_and_simp`，日志 `r4-tmp/logs/batch_fast.log:127-135`）**：
   - 实测 `local instance (priority := high) fakeLT : LT Nat := ⟨fun _ _ => True⟩; theorem looks_absurd : 10 < 1 := trivial` 及 `attribute [-simp]` 零告警通过门 2/3/15（rc=0）。此机制不破坏内核健全性，但说明表面记号含义仍须由声明锁（门 6a 编码已解析常量全名 `fakeLT`）与声明评审独审共同收口。

---

## 四、乙、阻断门误杀合法 W3 代码审阅

### [R4-B1]（BLOCK）门 3 环境层：普通递归归纳类型 `deriving Ord` 被 `ENV_PARTIAL` 永久误杀

- **位置**：`formal_math/verification/Audit.lean:18-20, 84-90`；对照 Lean 4.36.0 源码 `Lean/Elab/Deriving/Ord.lean:166`。
- **机理**：
  Lean 4.36.0 的 `Ord` 派生处理器调用 `mkContext ``Ord "ord" declName (supportsRec := false)`（`Ord.lean:166`），因此对**任何递归归纳类型**（即使是非嵌套、非互递归的普通递归类型，如二叉树 `BinTree`）都固定令 `usePartial = true` 并生成 `partial def instOrdBinTree.ord` + `_unsafe_rec`。但 `Audit.lean:85` 重算时调用 `(Elab.Deriving.mkContext cls pre ty).run'`，沿用了默认参数 `supportsRec := true`，对非嵌套、非互递归的普通递归类型算得 `ctx.usePartial = false`，因而豁免 3 恒失败，永久误报 `ENV_PARTIAL`！（自测 `must_green/g3/generated-auxiliaries` 仅测了嵌套归纳与互递归，恰好遗漏了最常见的普通递归类型。）
- **最小复现与实测读数**：
  - 夹具 `r4-tmp/cases/W1a_plain_rec_deriving_ord/`（日志 `r4-tmp/logs/batch_fast.log:86-95`、`r4-tmp/batch_fast.jsonl:10`）：
    ```lean
    module
    public section
    inductive BinTree where
      | leaf (v : Nat)
      | node (l r : BinTree)
    deriving Ord
    ```
  - **实测读数**：
    - `lake build --wfail +Chan.Exec.BinTreeOrd:olean`：退出码 **`0`**
    - `run_gates.py --gate 2`：退出码 **`0`**
    - `run_gates.py --gate 3`：退出码 **`1`**（`GATE3 RED formal_math/Chan/Exec/BinTreeOrd.lean:instOrdBinTree.ord._unsafe_rec ENV_PARTIAL 部分定义（源定义 instOrdBinTree.ord 不是结构／良基递归或白名单派生）`）
    - `run_gates.py --gate 15`：退出码 **`0`**
  - 对照（`W1b_plain_rec_deriving_others`，`r4-tmp/batch_fast.jsonl:11`）：同一 `BinTree` 派生 `DecidableEq, BEq, ReflBEq, LawfulBEq, Hashable, Repr, Inhabited, Nonempty` 全部通过（门 2/3/15 均为 `0`），确认问题精准出在 `Ord` 的 `supportsRec := false`。
- **严重度定性**：**BLOCK（乙）**。`Ord` 在派生白名单内，且对普通递归树结构没有等价的自动派生替代写法。

---

### [R4-B2]（BLOCK）门 15：`Chan/Defs/` 内任何类型使用白名单 `deriving Repr` 或 `deriving Hashable` 均被 `EXPOSE_SECTION` 永久误杀

- **位置**：`formal_math/verification/EnvGates.lean:823-829`；对照 Lean 4.36.0 源码 `Lean/Elab/Deriving/Repr.lean:105`、`Lean/Elab/Deriving/Hashable.lean:75`、`Lean/Elab/Deriving/Basic.lean:330`、`Lean/Elab/MutualDef.lean:1262`。
- **机理**：
  门 15 要求 `Chan/Defs/` 内写 `@[expose] public section`，并由 `EnvGates.lean:825-828` 检查所有满足 `!isPrivateName && (e.info matches .defnInfo _) && (findDeclarationRangesCore? e.name).isSome` 的声明在公开视图中也必须仍是 `.defnInfo`。然而 Lean 4.36.0 内置的 `Repr` 和 `Hashable` 派生处理器显式给生成的 `instReprT.repr` / `instHashableT.hash` 贴上 `@[no_expose]`，且在 `withRef view.ref` 下精化从而带有源码声明范围。结果在 `Chan/Defs/` 中哪怕定义最普通的枚举或记录结构并派生 `Repr` 或 `Hashable`，公开视图里的 `.repr`/`.hash` 必为 `.opaqueInfo`，门 15 必然判红 `EXPOSE_SECTION`！
- **最小复现与实测读数**：
  - 夹具 `r4-tmp/cases/W1d_defs_deriving_expose/`（日志 `r4-tmp/logs/batch_fast.log:114-126`、`r4-tmp/batch_fast.jsonl:13`）：
    ```lean
    module
    @[expose] public section
    inductive Dir | up | down deriving DecidableEq, BEq, ReflBEq, LawfulBEq, Hashable, Ord, Repr, Inhabited, Nonempty
    structure Bar where
      lo : Nat
      hi : Nat
    deriving DecidableEq, BEq, Hashable, Ord, Repr, Inhabited
    ```
  - **实测读数**：
    - `lake build --wfail +Chan.Defs.Types:olean`：退出码 **`0`**
    - `run_gates.py --gate 2`：退出码 **`0`**；`--gate 3`：退出码 **`0`**
    - `run_gates.py --gate 15`：退出码 **`1`**（输出 4 条 `EXPOSE_SECTION`：`instHashableDir.hash`、`instHashableBar.hash`、`instReprDir.repr`、`instReprBar.repr`）。
- **严重度定性**：**BLOCK（乙）**。核心数据结构均定义在 `Chan/Defs/`，`Repr` 与 `Hashable` 均为白名单明确允许的日常派生类，现实现使之在 `Chan/Defs/` 完全不可用。

---

### 乙类其余 W3 代表性场景实测记录（未发现额外误杀）

1. **命名空间 / 私有归纳 / 参数化嵌套归纳派生（`W1c_ns_and_private_deriving`、`W1e_ns_param_deriving_visitNamespace`，日志 `r4-tmp/logs/batch_fast.log:105-113`、`r4-tmp/logs/batch_surgical.log:80-88`）——通过**：
   - 在与类型同名的 `namespace Bar` 内定义嵌套归纳 `Rose`（含参数化 `Tree (b : Bar)`）与 `private inductive PrivRose`、`inductive ParamRose (α : Type)` 并派生 `Repr, BEq, Hashable, Ord`，实测 `lake build --wfail`、门 2、门 3、门 15 均退出 **`0`**。
2. **W3 代表性综合小证明文件（`W2_comprehensive_w3_proof`，夹具 `r4-tmp/cases/W2_comprehensive_w3_proof/`，日志 `r4-tmp/logs/batch_surgical.log:89-121`）——前段源码审查通过，后段因自身笔误与 6 GiB 停线未补跑**：
   - 文件覆盖：`Chan/Defs/Model.lean`（`IntervalBar [LinearOrder P]`、`@[ext] structure Pt deriving DecidableEq, BEq, Inhabited`、`@[reducible] def Pt.sum`）与 `Chan/Thm/W3Proofs.lean`（导入 `Mathlib.Tactic.Common` / `Linarith` / `NormNum` / `Positivity` / `Ring` / `Finset` / `Rat.Defs`，含 `open scoped BigOperators`、WF 递归 `steps` + `termination_by`/`decreasing_by omega`、`where`、`let rec`、`mutual inductive` + `deriving instance Repr, BEq, DecidableEq, Hashable, Ord`、`mutual def`、`section` + `include`/`omit`、`@[simp]`、`calc`、`omega`、`decide`、`grind`、`aesop`、`linarith`、`norm_num`、`positivity`、`rcases`/`obtain`、`induction ... with`、`Finset.sum` 与 `List.sum`）。
   - **实测读数**：`Chan/Defs/Model.lean` 零告警编译通过（`✔ Built Chan.Defs.Model`）；`Chan/Thm/W3Proofs.lean` 前 71 行（上述所有 W3 语法、互递归五类派生与 Mathlib 战术）均零告警通过 `fm_audit source` 表层与精化后检查，未出现任何门 2/3 误红；至第 75 行因探针脚本 `use_rcases_obtain` 缺少 `simp only at hx hy` 导致 `omega` 精化报错；该用例结束后根分区 `/` 降至 `5.901 GiB`（随后 `5.6 GiB`）触发 6 GiB 停线，故未重跑修正后的完整环境层端到端校验（见第八节「未实跑项说明」）。

---

## 五、审阅报告（`--report`）与 `README.md` 核查

### 1. `--report` 核查：未发现 `certified` 假阳性，稳健性通过

- **静态核查**：审查 `EnvGates.lean:413-583` 与 Lean 4.36.0 `Lean/Util/FoldConsts.lean:67-75`（确认 `.inductInfo` 的 `getUsedConstantsAsSet` 遍历所有构造子 `val.ctors`，故 `hiddenDependency` 覆盖经构造子类型引入的名义依赖）。`certified` 仅赋予经内核接受泛化命题的 `GENERALIZES`（门 7b）与经内核重放原证明成功的 `DROPPABLE_PREMISE`（门 8b），未发现可构造的 `certified` 假阳性。
- **实测读数**（夹具 `r4-tmp/cases/R1_report_certified_and_robustness/`，日志 `r4-tmp/logs/batch_fast.log:175-end`、`r4-tmp/batch_fast.jsonl:20`）：
  - 在同一包内同时放置：真泛化定理 `generalizes_D`、真依赖定理 `depends_on_D`、结构隐藏依赖 `uses_carryD`、多构造子名义依赖 `uses_nom`、未用前提 `unused_prem`、真用前提 `uses_prem_omega`、依赖型前提 `dep_prem`（触发门 9 `UNKNOWN`）、带类型类参数的除法 `divWithClass`（触发门 10 `mkAppM` 异常 `UNKNOWN`）。
  - **实测结果**：`run_gates.py --gate 2/3/15` 全部退 **`0`**；`run_gates.py --report` 退出码 **`0`**（未因门 9/10 `unknown` 崩溃，也不影响阻断门）；`generalizes_D` 报 `certified/finding GENERALIZES`，`unused_prem` 报 `certified/finding DROPPABLE_PREMISE`，`depends_on_D` / `uses_nom` / `uses_prem_omega` / `dep_prem` 均未误报 `certified`，`divWithClass`（门 10）与 `dep_prem`（门 9）与 `uses_carryD`（门 7b）均优雅降级为 `hint/unknown`。

### 2. [R4-O1]（BLOCK）`README.md` 对阻断门的承诺存在多处失实

- **位置与逐项对照**：
  1. `README.md:24`：「`autoImplicit`、`relaxedAutoImplicit`、`linter.*` 不得在 Lake 目标或源码的任何语法位置设置」——**失实**，见 [R4-A2]（`sudo set_option`）与 [R4-A3]（`lakefile.toml` 的 `moreLeanArgs` 与包级 `[leanOptions]`）。
  2. `README.md:25, 82-89`：「审计程序不执行被审代码」「因此精化期运行的代码只剩钉选库」——**失实**，见 [R4-A1]（纯零导入 `include_str (unsafe (unsafeIO ...))`、`include_str (dbgTrace ...)`、`eval%` 等在 `fm_audit source` 阶段即执行用户代码与宿主机 IO）。
  3. `README.md:26, 95`：「`extern` 与 `meta` 没有豁免」——**失实**，见 [R4-A5]（`Audit.lean:117-128` 逻辑错误使 `generatedBy` 豁免压制 `ENV_EXTERN`，`P7c` 实测 `fm_audit 3` 退 `0`）。
  4. `README.md:49`：「`#guard_msgs`：内嵌命令不得是声明，规格不得含 `drop`」——**失实/不完整**，见 [R4-A4]（`(substring := true)` 无 docstring 等效 `drop`，且 `deriving instance` 绕过「不得是声明」）。
  5. `README.md:66`：「可信目录不得导入 `Lean`」——实际白名单内的 `Batteries.Lean.*` 与 `Mathlib.Lean.*` 公开再导出 `Lean.*` 接口（已作为 `P1d` 跳板之一验证）。
- **严重度定性**：**BLOCK（其他）**。上述 1–4 均属于对**阻断门边界**的直接不实承诺。

---

## 六、三审 R3-H1 与 R3-H2 逐项修复核对

| 三审编号与子项 | 本轮实现处置 | 实测 / 源码核查状态 |
|---|---|---|
| **R3-H1.1** `@[macro]` / `@[init]` / 元编程属性开放黑名单 | 改为封闭白名单 `attributeNames`（`SourceGates.lean:69-72`），禁 `meta`/`unsafe`/`partial` 修饰与 `meta section`；入库 `r3-a1*`/`r3-a2*`/`r3-a3*` 夹具 | **部分关闭**：命令级元编程属性与 `meta` 已封；但遗漏项级 `Term.unsafe` 与 `include_str`/`eval%` 等求值器（见 **R4-A1**） |
| **R3-H1.2** 仅查表层语法、宏展开注入禁用命令/选项 | 新增 `elaborated` 遍历 `InfoTree` 的 `CommandInfo`/`OptionInfo`（`SourceGates.lean:197-217`），并增 `fm_audit selfcheck` | **部分关闭**：经 `elabSetOption` 的宏展开（含 `decreasing_by` 内 `rfl'`/`unhygienic`，`P4a` 实测抓到）已封；但 `sudo set_option` 不经 `elabSetOption` 绕过（**R4-A2**），`elaborated` 对 `#guard_msgs` 丢 `guarded` 标志（**R4-A4**） |
| **R3-H1.3** 裁定 1 跳过无声明范围常量致 `partial def` 漏检 | 门 3 环境层改枚举全部常量，不再看声明范围，改按 `generatedBy` 三类豁免（`Audit.lean:55-128`） | **部分关闭（引入新回归与缺陷）**：手写 `partial def`（含 `stripInfo`）已被环境层拦截；但新 `generatedBy` 压制了 `ENV_EXTERN`、豁免 1/3 可伪造（**R4-A5**），且误杀普通递归 `deriving Ord`（**R4-B1**） |
| **R3-H1.4** `grind => set_option` 与 `example` 中 `sorryAx` | `setting` 改按首原子 `"set_option"` 匹配（`SourceGates.lean:96-99`），新增 `== `sorryAx` 检查（`:141`）；入库 `r3-a5a`/`r3-a5b`/`r3-a5c` | **部分关闭**：`grind => set_option` 已封；但 `sudo set_option` 同型绕过（**R4-A2**），`_root_.sorryAx` 绕过单门 3（**R4-A6**） |
| **R3-H1.5** `@[init]` 在 `fm_audit source` 审计期执行 IO | `quarantine` 先无初始化器读闭包，将本地模块记入 `interpretedModInits`，含 `meta` 即拒精化（`SourceGates.lean:314-327`） | **部分关闭**：本地 `@[init]` / `meta` 已隔离；但「审计期不执行被审代码」总体仍被 `include_str (unsafe (unsafeIO ...))` 零导入击穿（**R4-A1**） |
| **R3-H2.1** `Chan/Final` `#guard_msgs` 子节点索引错位（`i == 3`） | 修正为 `i == 4`（`SourceGates.lean:153`），入库 `must_green/g3/r3-a4c-guard-msgs` | **已修合法用例，遗留新绕过**：合法 `#guard_msgs` 可用；但 `(substring := true)` 无 docstring 吞消息及 `deriving instance` 未封（**R4-A4**） |
| **R3-H2.2** 源码白名单缺 `omit` | 已将 `Lean.Parser.Command.omit` 加入 `commandKinds`（`:48`），入库 `r3-a7-omit`/`r3-a7c-omit-instance` | **已关闭** |
| **R3-H2.3** 源码白名单缺 `deriving instance` | 已将 `Lean.Parser.Command.deriving` 加入 `commandKinds`（`:51`），入库 `r3-a7b-mutual-deriving` | **已关闭**（但 `#guard_msgs` 内放行它带来 **R4-A4** 绕过） |

---

## 七、BLOCK 清单与非阻塞建议清单

### BLOCK 清单（共 9 项：甲 6 项、乙 2 项、其他 1 项）

- **甲（阻断门可绕过性，6 项）**：
  1. **[R4-A1]** 零额外导入 `include_str (unsafe (unsafeIO ...))`、`sudo set_option compiler.checkMeta false` + `Batteries.Lean.LawfulMonad` + `by_elab`（以及纯 `include_str`、`eval%` 等）在 `fm_audit source` 审计期任意读写宿主机文件并获取元编程权限，且全阻断门零告警退 `0`。
  2. **[R4-A2]** `Mathlib.Tactic.SudoSetOption`（由 `Mathlib.Tactic.Common` 再导出）绕过门 2/3 全部选项检查，可在任意项/战术位置静默设置 `linter.unusedVariables false`、`debug.skipKernelTC true` 等并全阻断门退 `0`。
  3. **[R4-A3]** `lakefile.toml` 的目标级 `moreLeanArgs`/`weakLeanArgs` 与包级 `[leanOptions]` 绕过门 2，可关闭 `linter.unusedVariables.funArgs`/`linter.deprecated` 及开启 `debug.skipKernelTC`。
  4. **[R4-A4]** `Chan/Final` 中 `#guard_msgs (substring := true)` 无 `drop` 吞掉一切错误与告警，且 `#guard_msgs` 内放行 `deriving instance`。
  5. **[R4-A5]** 门 3 环境层 `generatedBy` 豁免错误压制 `ENV_EXTERN`（直违 README），且豁免 1（`ctorIdx`）与豁免 3（派生辅助函数）均可被手写 `unsafe`/`partial`/`implemented_by` 伪造通过 `fm_audit 3`。
  6. **[R4-A6]** `_root_.sorryAx` 在 `example` 中绕过单独门 3（`--gate 3` 退 `0`）。
- **乙（阻断门误杀合法 W3 代码，2 项）**：
  1. **[R4-B1]** 普通递归归纳类型 `deriving Ord` 因 `Audit.lean:85` 漏传 `supportsRec := false` 被门 3 `ENV_PARTIAL` 永久误杀。
  2. **[R4-B2]** `Chan/Defs/` 内任何类型使用 `deriving Repr` 或 `deriving Hashable` 被门 15 `EXPOSE_SECTION` 永久误杀。
- **其他（1 项）**：
  1. **[R4-O1]** `README.md` 第 24、25、26、49、66、82–89、95 行对阻断门的多处机械承诺与实测不符。

### 非阻塞建议清单（7 项）

1. **门 6a 序列化补充 `letE` 的 `nondep` 布尔位**（`EnvGates.lean:72`）：当前 `let` 改为 `have` 仍通过门 6a（`P9a` 实测 rc=0），建议编码 `nondep` 以保持内核表达式逐位锁定。
2. **门 6a / 门 15 明确 `Chan/Hypotheses/` 的暴露态锁定策略**：当前去掉 `Chan/Hypotheses/` 的 `@[expose]` 后门 6a 与门 15 均退 `0`（`P9b`），若下游依赖其定义展开，建议门 6a 编码 `isExposed` 或门 15 纳入检查。
3. **门 1 补齐 `lake-manifest.json` 包来源校验**（`run_gates.py:66-75`，R3-S7 延续）：`run_gate1_pure.py` 实测改 `type: "path"` + `url` 仍退 `0`，建议锁定 `type == "git"` 与预期 `url`。
4. **门 6b 三处边缘收紧**（`run_gates.py:480-496`）：拒绝空后缀分支名（如 `decl/`）、决定是否纳入仓库根部未跟踪文件、禁止在受管目录下提交符号链接（`gate6b_pure.json`）。
5. **明确 Mathlib `lemma` 命令的文档说明**：`must_red/g3/r3-a8b-mathlib-lemma` 明确拒绝 `Mathlib.Tactic.Lemma` 的 `lemma`（可用 `theorem` 等价替代，不构成误杀 BLOCK），建议在 README 命令白名单中明示「不放行 Mathlib `lemma`，统一用 `theorem`」。
6. **修正 `README.md:114` 关于 `decreasing_by` 信息树空洞的描述**：`P4a` 实测 `SourceGates.lean:262-265` 的 `substituteLazy` 已能抓出 `decreasing_by` 内的库宏选项，文档描述可按实测收紧为「仅 Lean 确实未写回赋值表的空洞不可复核」。
7. **精简 `--report` 中的编译器辅助常量空行**：`R1` 实测报告 Markdown/JSON 为每个结构/归纳自动生成的 `_sizeOf_1`、`ctorIdx`、`noConfusion`、`_proof_1_1` 等输出了全 `—` 行，建议折叠或默认隐藏全 `no_finding` 的编译器辅助项以减轻独审阅读噪音。

---

## 八、未实跑项说明

1. **`W2_comprehensive_w3_proof` 修正后全文件端到端复跑（未实跑）**：首次运行中 `Chan/Defs/Model.lean` 编译通过、`Chan/Thm/W3Proofs.lean` 前 71 行无误杀，但第 75 行 `use_rcases_obtain` 因探针自身漏写 `simp only at hx hy` 精化报错；随后根分区 `/` 降至 `5.901 GiB`（继而 `5.6 GiB`）触发 6.0 GiB 停线，按纪律停止后续 Lean/Lake 运行，故末尾 4 个定理（`use_rcases_obtain`、`use_induction`、`use_big_ops`、`use_list_big_op`）及 `W2` 完整门 3 环境层回归未补跑。
2. **`P5b_guard_msgs_clean_swallow` 拆出仅含 `#check` 与合法 `deriving instance` 的门 2/3/15 全 0 单例（未实跑）**：原 `P5b` 已实跑证实 `lake build --wfail` 退 `0`、门 2 退 `0`、门 15 退 `0`、门 3 源码层 0 报警（仅第 3 条因 `PairTag` 私有导入派生失败生成 `sorryAx` 触发环境层 `ENV_SORRY`）；因 6.0 GiB 停线未再单拆补跑。
3. **本机全量 `selftest.py`（未实跑）**：遵审阅磁盘约束未在本机重跑全部 325 例自测；已通过 `git diff` 核验旧阻断门 `must_red` 期望未被弱化，并人工通读 `selftest.py` 确认阻断门与报告回归断言逻辑严谨。

> 所有 9 项 BLOCK 结论（甲 6 项、乙 2 项、其他 1 项）均基于本机实跑复现证据或已核对源码/文档原件，无一例依赖未实跑推论。

---

## 九、实证产物索引

所有可复现文本夹具、探测脚本、原始 JSONL 与日志均归档于证据分支 `evidence/2312-d-review` 的 `audit-reports/2312/r4-tmp/`：
- `r4-tmp/probe_lib.py`：串行探测框架（含 6.0 GiB 停线与 Mathlib 重编熔断）
- `r4-tmp/run_batch1.py` / `r4-tmp/logs/batch1.log`：批 1（`P1a`–`P5a`）
- `r4-tmp/run_batch_fast.py` / `r4-tmp/batch_fast.jsonl` / `r4-tmp/logs/batch_fast.log`：零 Mathlib 20 组全批（`P3b2`、`P5a`、`P6a/b`、`P7a–e`、`W1a–d`、`P8a`、`P9a–d2`、`R1`）
- `r4-tmp/run_batch_surgical.py` / `r4-tmp/batch_surgical.jsonl` / `r4-tmp/logs/batch_surgical.log`：精准补测批（`P0`、`P7b2`、`P7a2`、`P5b`、`P6c`、`P2b`、`P1d`、`P3d`、`W1e`、`W2`）
- `r4-tmp/run_gate1_pure.py` / `r4-tmp/gate1_pure.json`：门 1 manifest 来源篡改探测
- `r4-tmp/run_gate6b_pure.py` / `r4-tmp/gate6b_pure.json`：门 6b 纯 git 9 组边界探测
- `r4-tmp/cases/*`：各探测用例的完整 Lean / TOML / YAML 源码夹具
