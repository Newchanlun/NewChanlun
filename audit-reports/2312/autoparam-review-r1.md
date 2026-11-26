# #2312 第四片 r2 合入核销与环境层第 4 类豁免（自动参数）独立非作者审阅 r1

| 项 | 值 |
|---|---|
| 被审提交 | `82d40a314656cf1cd35bc4d56baf97487082fe1b`（分支 `origin/infra/2312-h-autoparam`） |
| 对比基线 | `8369643028747b172b5a39a52a67bf67c09ab7f0`（r2 已审） |
| 独立审阅者 | Mac `gemini-4-neon-xhigh`（Swarm 独立会话 `fm2312-h-reviewer`，只读审阅 + OrbStack Ubuntu `bwrap` / Lean 4.36.0 实跑 16 项探针） |
| 日期 | 2026-11-26 |

`#2312`（FM-04 阻断门）独立非作者审阅完成，目标提交 `origin/infra/2312-h-autoparam` @ `82d40a314656cf1cd35bc4d56baf97487082fe1b`（对比基线 `8369643028747b172b5a39a52a67bf67c09ab7f0`；双父合并 `f4a816f275` + `7c9ddaa754`，27 文件 +861/-27）。

---

## 总裁决

- **VERDICT: BLOCK**
- **VERDICT-块一（第四片独审 r2 订正合入核销）: PASS**
- **VERDICT-块二（环境层 `ENV_META` 第 4 类豁免）: BLOCK**（防冒用/健全性维度 **通过**，无绕过漏洞；阻断来自合法自动参数误拒面的**两条实测坐实的源码缺陷**——仅扫 `e.info.type` 漏掉 `e.info.value?` 中的 `autoParam`，以及 `carrierName` 漏掉 Lean 4.36.0 异步证明精化实际生成的双数字后缀 `_auto_<d>_<d>`；两者合计最小修法约 8 行且不弱化任何防冒用保证。）

---

## 块一：第四片独审 r2（`shape-review-r2.md`）全部项合入核销 — **PASS**

逐项核对 `8369643028..82d40a3146` 与 `shape-review-r2.md`：

1. **甲-2（BLOCK，说明层）— 已核销**：
   - `git grep "没有求值能力" 82d40a3146 -- formal_math/verification` 为 0 命中。
   - `runner/README.md:459-460` 已改写为按库区分：核心 `simp` 受限求值器报 `Could not evaluate the expression`（`fx/e-eval5`），钉选 Mathlib 对 `LinarithConfig`/`CertificateOracle`/`GlobalBranchingPreprocessor` 用 `derive_eval_expr_instance_using_meta_eval` 打开 `Meta.evalExpr'`（`Mathlib/Tactic/Linarith/Frontend.lean:511-515`），`linarith (oracle := …)` 构建期被求值且归「不防什么」与 #2315；同步采纳了 r2 建议 **S3**（「下面列出的通往宿主机读写的通道都被堵住（这是枚举，不是全集）」）、**S4**（语料 `must_green/known-not-covered/linarith-oracle-eval` + 骨架 `H4`）、**S5**（给 #2315 的 `derive_eval_expr_instance_using_meta_eval`/`ensure_eval_expr_instance` 检索线索）。
2. **甲-C1（命名参数代价）— 已核销**：
   - `runner/README.md:466` 如实写明参数名以 `config` 结尾的函数应用命名参数会判 `SHAPE_FORBIDDEN`（说明栏仍写「旧式配置子句」）、方向为多挡、规避法为改位置参数或改名如 `cfg`，并说明为何不按 `namedArgument` 种类排除。
   - `runner/selftest.py:429-431`（`FbCfgNamedArg.lean`）、`:441-442`（`CfgNewStyleGreen.lean` 的 `(cfg := 1)`）与必绿语料 `must_green/g3/r2-config-shaped-green`（`fixtures.tsv:268`）完整覆盖。
3. **甲-C2（`:=` 要件弱化撤下与必绿对照）— 已核销**：
   - `runner/README.md:468` 对撤下等价弱化的技术解释经对照 `Auditor/Shape.lean:99-105` 核实准确：括号/类型标注/元组左括号为 `hygienicLParen` 节点（`stx[0].isAtom` 为假），显式绑定器第二子为标识符列表 `null` 节点（`stx[1].isAtom`/`isIdent` 均为假），确与原规则在钉选库允许语法上等价。
   - 必绿对照已按要求补入 `(my_config : Nat)` 与 `(config, config)`（`selftest.py:443-444`、`must_green/g3/r2-config-shaped-green`）。
4. **乙-C1（`S33` 与 `NO_CERTIFICATE` 路径比对弱化，`SKELETON_FIXTURES`）— 已核销**：
   - `selftest.py:121-125`（`othercert` 分支指向 `trusted_dir/verification/runner/run.py`）、`selftest.py:927-932`（`S33`）、`selftest.py:1529-1531`（弱化 `run.py:706` 只留 `if certificate is None:`，改弱点恰出现 1 次）到位。
   - `selftest.py:1204-1208` `SKELETON_FIXTURES` 同时涵盖 `must_red/autoparam/spoofs`（A2）、`must_green/known-issue/autoparam-variable-binder`（A3）、`must_green/known-not-covered/linarith-oracle-eval`（H4），且所有骨架用例无遗漏夹具依赖。
5. **一致性与未变动面 — 已核销**：
   - 全部人工逐行复核：`SHAPE_RED` = 66（`README.md:405`）、`MUTANTS` = 52 = 骨架 28 + 第四片 18 + 自动参数 6（`README.md:418-422`）、`fixtures.tsv` = 266 数据行且汇总表 12 行合计 266 与逐项收支完全一致（`README.md:430-445`）、`AUTOPARAM_SPOOFS` = 16（`README.md:413`）、`U1` = 18 候选（正 3 + 反 15，`README.md:416`）。
   - `git diff 8369643028..82d40a3146` 对 `Auditor/Shape.lean`、`Auditor/Headers.lean`、`precheck/`、`runner/run.py` 为空；`git diff f4a816f275..82d40a3146` 对 `auditor/`、`precheck/`、`runner/run.py` 为空。

---

## 块二：环境层 `ENV_META` 第 4 类豁免深度独立审查 — **BLOCK**

### 审阅通过面（健全性与已覆盖合法场景）
1. **防冒用 / 放行面无漏洞**：
   - 5 条判据严密：手写源码的 `def`/`@[irreducible] meta def` 提示恒为 `.regular`（`Copy.lean` 与实测探针 `11_ProbeSpoofIrred` 均判 `ENV_META`），`abbrev` 为 `.abbrev`，`opaque` 为 `opaqueInfo`，源码无法写出 `hints == .opaque` 的 `defnInfo`。
   - 即使跳过第 5 步或通过 `addDecl` 伪造，判据 5 先解码再调 Lean 4.36.0 自身纯函数 `Elab.Term.quoteAutoTactic` 重算并做 `Expr` 精确相等 `== d.value`（`EnvGates.lean:183-184`），彻底钉死了 `quotedSyntax`/`quotedList`/`quotedName` 中全部通配位与 `Name.mkStr*` 长度/数字后缀，确保 `d.value` 严格落在 `quoteAutoTactic` 像集内（纯 `Lean.Syntax` 数据，无函数调用、无常量引用、无反引号/missing）。
   - `Main.lean:135,148` 集成极窄：`carriers` 仅作用于 `ENV_META`，不影响 `ENV_AXIOM`/`ENV_AXIOM_DEP`/`ENV_SORRY`/`ENV_UNSAFE`/`ENV_PARTIAL`/`ENV_EXTERN`/`ENV_IMPLEMENTED_BY`。实测 `12_ProbePostExtern`（给合法载体事后挂 `attribute [extern ...]`）同时报 `ENV_EXTERN` 与 `ENV_META`。
2. **`quotedName`/`quotedPreresolved`/`quotedSyntax` 对 Lean 4.36.0 `ToExpr` 完整匹配**：
   - 单元探针 `10_ProbeUnitHyg` 实测证实：`Name.num`（编码为 `OfNat.ofNat Nat (.lit (.natVal n)) (instOfNatNat _)`，可被 `n.nat?` 正确解出）、非空 `Syntax.Preresolved`（`.namespace` 与 `.decl`）、以及 >8 段全字符串名触发的 `Name.str` 退化链，3/3 均被 `FM.autoParamCarriers` 识别为合法载体。
3. **复杂合法场景与门 15 验证通过**：
   - `5_ProbeWhereLetRec`（`where`/`let rec`）、`6_ProbeExample`（`example` 绑定器与体内 `have`，核实 README「不留下常量」）、`8d_ProbeComplex`（9 段名、书名号空格名、`simp (maxSteps := 500); linarith`、多绑定器、`private` 结构字段、带绑定器的结构字段、`extends` 覆写非自动参数父字段、`inductive` 类型参数）均**七步全绿**。
   - `9_ProbeDefsExpose` 证实 `Chan/Defs` 下 `def` 与 `structure` 的自动参数均不触发 `ENV_META` 和门 15 `EXPOSE_SECTION`（无声明范围）。

---

### 阻断项（BLOCK）

#### 阻断-1：`autoParamCarriers` 仅扫描 `e.info.type`，误拒合法的 `abbrev`/类型别名与 `def`/`theorem` 局部 `let`/`have` 自动参数
- **位置**：`formal_math/verification/auditor/Auditor/EnvGates.lean:169-174`（及对应文档 `formal_math/verification/runner/README.md:260-261, 279`）
- **实测证据**（OrbStack Ubuntu `bwrap` + Lean 4.36.0，均前六步全绿、零告警，第 7 步判红）：
  1. `4_ProbeAbbrevType`：`abbrev AutoArrow := ∀ (n : Nat) (_h : n ≤ n := by omega), Nat`（以及使用它的 `useAutoArrow`、`callAutoArrow`）→ 第 7 步 `ENV_META`：`AutoArrow._auto_1`（与 `README.md:261` 声称支持「类型里的 `∀ (h : p := by tac)`」直接矛盾）。
  2. `1_ProbeLocalLet`：`def localLet : Nat := let g (n : Nat) (_h : n ≤ n := by omega) : Nat := n; g 3` → 第 7 步 `ENV_META`：`_private.Chan.Thm.ProbeLocalLet.0.localLet._auto_1`。
  3. `13b_ProbeNestedAuto` 的 `defByHave`：`def defByHave : Nat := by have g (n : Nat) (_h : n ≤ n := by omega) : Nat := n; exact g 3` → 第 7 步 `ENV_META`：`_private.Chan.Thm.ProbeNestedAuto.0.defByHave._auto_1`。
  4. `2_ProbeLocalHave` / `13b_ProbeNestedAuto` 的 `thmTwoHaves`：`theorem` 证明块内 `have g (n : Nat) (_h : n ≤ n := by omega) ...` → 第 7 步 `ENV_META`（同时命中阻断-2）。
  - `13c_InspectMetaAndRefs` 坐实根因：上述三类的 `autoParam _ <载体>` 引用均精确出现在同模块宿主常量的 **`e.info.value? (allowOpaque := true)`**（`valRefs` 非空、`typeRefs` 为空）；而 `variable` 已知问题（`ProbeVarRef`/`Var.lean`）的 `typeRefs` 与 `valRefs` 均为空。
- **安全性分析**：将 `refs` 扫描扩展到 `e.info.value? true` **不削弱任何防冒用保证**——① 自引用已有 `c != e.name` 排除且载体值必过 `quoteAutoTactic` 重算（不含 `autoParam`）；② 载体间互引用同理不可能；③ 能改 `value` 塞 `autoParam` 的对手本就能改 `type` 塞 `autoParam`，载体仍须过判据 1/2/3/5；④ `A3`（`Var.lean`）、`A2`（`Orphan.lean`）、`U1`（`U.orphan._auto_1`）均保持判红。
- **最小修法**：
  ```lean
  let scan (e : Entry) (expr : Expr) : MetaM Unit :=
    expr.forEachWhere (·.isAppOfArity ``autoParam 2) fun x => do
      if let .const c [] := x.appArg! then
        if c != e.name && (env.getModuleIdxFor? c).isSome &&
            env.getModuleIdxFor? c == env.getModuleIdxFor? e.name then
          refs.modify (·.insert c)
  for e in entries do
    scan e e.info.type
    if let some v := e.info.value? true then
      scan e v
  ```
  同步更新 `EnvGates.lean:162` 注释与 `README.md:279`（「类型或定义体/证明体含 `autoParam _ <该常量>`」），并把 `abbrev AutoArrow`、`let`/`have` 纳入必绿语料（如 `must_green/autoparam/binders`）。

#### 阻断-2：`carrierName` 仅认单段 `_auto_<数字>`，误拒 Lean 4.36.0 `theorem` 异步精化实际生成的双数字后缀 `_auto_<数字>_<数字>`
- **位置**：`formal_math/verification/auditor/Auditor/EnvGates.lean:151-154`（及对应文档 `EnvGates.lean:158`、`runner/README.md:260, 276`）
- **实测证据**：
  - `2_ProbeLocalHave` 生成的真实载体名为 `_private.Chan.Thm.ProbeLocalHave.0.localHave._auto_1_1`。
  - `13b_ProbeNestedAuto` 的 `thmTwoHaves` 生成的真实载体名为 `_private.Chan.Thm.ProbeNestedAuto.0.thmTwoHaves._auto_1_1` 与 `_private.Chan.Thm.ProbeNestedAuto.0.thmTwoHaves._auto_1_3`。
  - 当前 `carrierName` 用 `(s.toList.drop 6 |>.all Char.isDigit)`，遇到第二个 `_` 直接返回 `false`，导致即便修完阻断-1，任何 `theorem` 证明块内 `have` 含自动参数仍会被判 `ENV_META`。
- **最小修法**：
  ```lean
  private def carrierName : Name → Bool
    | .str _ s =>
      s == "_autoParam" ||
        (s.startsWith "_auto_" &&
          let parts := (s.splitOn "_").drop 2
          !parts.isEmpty && parts.all fun p => !p.isEmpty && p.toList.all Char.isDigit)
    | _ => false
  ```
  验证边界：`_auto_1` / `_auto_1_1` / `_auto_1_3` 为真；`_auto_` / `_auto_1_` / `_auto__1` / `_auto_1a` / `badName` 仍为假。同步更新 `EnvGates.lean:158` 与 `README.md:260, 276` 措辞，并在 `U1` 与必绿语料补正例与反例（`_auto_1_`、`_auto_1a`）。

---

### 条件项（可在修复上述阻断项时一并落地）

1. **块二-C1（自测盲区：`!isExtern` 无单点用例，`U1` 未覆盖 `Name.num`/`Syntax.Preresolved`/超 8 段名与跨模块孤立引用）**
   - **位置**：`runner/selftest-cases/autoparam/Forge.lean`、`must_red/autoparam/spoofs/`、`runner/selftest.py:1211-1245, 1535-1537`
   - **原因**：`EnvGates.lean:179` 的 `!isExtern env e.name` 在 `A2` 和 `U1` 里均无对应样例（若只删 `!isExtern`，现有 `A2`/`U1` 不会失败；虽因 `Main.lean:151` 无条件报 `ENV_EXTERN` 不构成放行漏洞，但该子句未钉住）；`U1` 仅测了单段 `mkStr1` + 空 `preresolved`，未覆盖 `quotedName` 的 `Name.num` / >8 段 `Name.str` 与 `quotedPreresolved` 的 `.namespace`/`.decl`，也未测同模块判定（跨模块引用孤立载体）。
   - **最小修法**：在 `must_red/autoparam/spoofs/` 增加 `PostExtern.lean`（如探针 12）或向 `U1` 补充 `extern` 反例，同时把探针 10 的 `Name.num` + 非空 `Preresolved` + 9 段名正例并入 `U1`。

---

### 建议项（不阻断）

1. **`README.md:253` 值构造子清单补全**：当前写「值只由 `Syntax.node`、`SourceInfo.none`、`Name.mkStrN`、`Array.push`、`Array.empty`、`mkAtom`（标识符另有 `Syntax.ident`、`String.toRawSubstring`、`List` 构造）组成」，建议补注「超过 8 段或含数字段的名称用 `Name.anonymous`/`Name.str`/`Name.num`（数字按 `OfNat.ofNat Nat` 编码），预解析列表用 `Syntax.Preresolved.namespace`/`.decl`」，与 `EnvGates.lean:99-149` 及 `ToExpr.lean` 一致。
2. **`README.md:456` 措辞微调**：「『已知不防』里还有两类没有做成独立夹具」如今「清单外的求值入口」一类已新增代表夹具 `linarith-oracle-eval`，可顺手改为「没有穷尽做成独立夹具」。

---

### 未覆盖范围
- 本次审阅未重跑全量 266 条语料自测及全部 52 项 `--mutants` 弱化自测（仅静态逐行核对了全部改弱点唯一性与映射关系，并对 16 个针对性探针做了真实 `bwrap` + Lean 4.36.0 沙箱实测）。
- 未重新审计 `8369643028` 之前已过审且在 `8369643028..82d40a3146` 零改动的模块本体（`precheck/`、`Auditor/Headers.lean`、`Auditor/Shape.lean`、`runner/run.py`、`report_cases/`）。
- 产物被蓄意篡改（`.olean`/`.ir` 伪造，包括载体内核值与编译码不一致）按设计归 `#2315`（`lake check`/`lake comparator`），不在本片审阅范围内。

修复阻断-1 与阻断-2（涉及 `Auditor/EnvGates.lean` 代码改动）后需定点复审改动 diff 及新增正/反例实测结果。
