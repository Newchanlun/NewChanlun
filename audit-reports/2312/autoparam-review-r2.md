# #2312 自动参数第 4 类 ENV_META 豁免独立非作者定点复审 r2

| 项 | 值 |
|---|---|
| 被审提交 | `e277af4a55d7448d8023f72606955015a9e5e77d`（分支 `origin/infra/2312-h-autoparam`） |
| 上一轮被审提交 | `82d40a314656cf1cd35bc4d56baf97487082fe1b`（报告 `origin/evidence/2312-autoparam-review-r1` @ `0e269fb1fe`） |
| 独立复审者 | Mac `gemini-4-neon-xhigh`（Swarm 独立会话 `fm2312-h-r2`，只读定点复审） |
| 日期 | 2026-11-26 |

**VERDICT: PASS**

---

### 被审对象与范围核对
- 被审分支与提交：`origin/infra/2312-h-autoparam` @ `e277af4a55d7448d8023f72606955015a9e5e77d`
- 基线（r1 被审提交）：`82d40a314656cf1cd35bc4d56baf97487082fe1b`（r1 报告归档 `origin/evidence/2312-autoparam-review-r1` @ `0e269fb1fe`）
- 改动面：`82d40a3146..e277af4a55`，精确 7 文件、`+107/-22`（`Auditor/EnvGates.lean`、`ApBinders.lean`、`PostExtern.lean`、`runner/README.md`、`runner/fixtures.tsv`、`autoparam/Forge.lean`、`runner/selftest.py`）。
- 未改动受信文件零差异：`Auditor/Shape.lean`、`Auditor/Headers.lean`、`Main.lean`、`precheck/`、`runner/run.py` 相对 `82d40a3146` 均为零差异（`git_meta.txt` 空 diff + `UNTOUCHED_FILES_ZERO_DIFF_OK`）。

---

### r1 核销表

| r1 编号 | 级别 | 复审核销结论 | 源码与实跑证据 |
|---|---|---|---|
| **阻断-1**（仅扫 `e.info.type` 漏 `e.info.value?`） | BLOCK | **已核销** | `EnvGates.lean:172-181` 抽出 `scan`，对所有 `entries` 同时扫 `e.info.type` 与 `e.info.value? true`（覆盖 `defnInfo`/`thmInfo`/`opaqueInfo`）。安全面复核通过：① 自引用仍被 `c != e.name` 与判据 5（`quoteAutoTactic` 像集不含 `autoParam`）双重封死；② 载体互引用同样被判据 5 封死；③ 跨模块引用仍被 `(env.getModuleIdxFor? c).isSome && env.getModuleIdxFor? c == env.getModuleIdxFor? e.name` 拦住；④ 非载体常量引用不能绕过判据 1/2/3/5（源码仍写不出 `hints == .opaque` 的 `defnInfo`），且与原有通过 `type` 引用能力等价；⑤ `Orphan.lean`、`A3`（`Var.lean`）、`U.orphan._auto_1` 均维持判红。回归验证：`ApBinders.lean:30-48`（`abbrev AutoArrow`、`apLocalLet`、`apDefByHave`、`apLocalHave`）七步全绿（4 文件 29 命令解析=精化一致）；`U1` 新增 `U.valRef._auto_1`（`useInVal` 仅定义体含 `autoParam`）通过。 |
| **阻断-2**（`carrierName` 漏多段数字后缀） | BLOCK | **已核销** | `EnvGates.lean:151-157` 改为 `s == "_autoParam" || (s.startsWith "_auto_" && let parts := (s.splitOn "_").drop 2; !parts.isEmpty && parts.all fun p => !p.isEmpty && p.toList.all Char.isDigit)`。对 `s = "_auto_" ++ rest`，`(s.splitOn "_").drop 2` 精确等于 `rest.splitOn "_"`，配合 `!p.isEmpty` 与 `Char.isDigit`（ASCII `'0'..'9'`），接受语言严格等价于 `^(_autoParam|_auto_[0-9]+(_[0-9]+)*)$`。合法 `_auto_1` / `_auto_1_1` / `_auto_1_3` 接受；非法 `_auto_` / `_auto_1_` / `_auto__1` / `_auto_1__2` / `_auto_1a` / `badName` 及非 `.str` 名一律拒绝。`U1` 实测 `U.multi._auto_1_1` 通过，4 条后缀反例（`noDigits`、`trailUnder`、`badAlpha`、`doubleUnder`）全部判拒；`ApBinders.lean` `theorem apLocalHave` 七步全绿。 |
| **块二-C1**（`!isExtern` 无单点用例，`U1` 缺 `Name.num`/`Preresolved`/9 段名） | 条件 | **已核销** | ① 新增 `must_red/autoparam/spoofs/.../PostExtern.lean`（对真载体事后挂 `attribute [extern ...]`）；`A2`（`selftest.py:1186-1188, 1218`）扩至 18 条，断言 `SpExt.h._autoParam` 同报 `ENV_META` 与 `ENV_EXTERN`；`fixtures.tsv:265` 同步加入 `ENV_EXTERN`；`MUTANTS` 新增第 53 项「第 4 类豁免去掉 `!isExtern` 条件」（改弱点 `!isExtern env e.name && ` 在 `EnvGates.lean:186` 唯一出现）并实测被 `A2` 抓到。② `Forge.lean:46-59` 与 `selftest.py:1225-1253` 将 `U1` 扩至 25 项（正例 7、反例 18），涵盖 `U.hyg._auto_1`（`Name.num` + `.namespace`/`.decl`）、`U.long._auto_1`（9 段 `Name.str` 退化链）、`U.multi._auto_1_1`、`U.valRef._auto_1` 及 3 条多段后缀反例，实测 25/25 通过。 |
| **建议 S1**（`README.md:253` 值构造子清单补全） | 建议 | **已核销** | `README.md:253` 已补注超 8 段/含数字段用 `Name.anonymous`/`Name.str`/`Name.num`（`OfNat.ofNat Nat` 编码）与 `Syntax.Preresolved.namespace`/`.decl`，与 `EnvGates.lean:99-149` 完整一致。 |
| **建议 S2**（`README.md:456` 措辞微调） | 建议 | **已核销** | `README.md:458` 已改为「没有穷尽做成独立夹具」。 |
| **文档/计数一致性** | 核查 | **已核销** | 逐项核对全部对齐：`EnvGates.lean:161,165` 与 `README.md:255,261-262,277,280` 判据 1/4 及生成点表一致；`PostExtern.lean` 已入 `README.md:302`；`A2` = 18 条（`README.md:415`、`AUTOPARAM_SPOOFS` 18 项、`selftest_r2_output.txt` `多出=[] 缺少=[]`）；`U1` = 25 = 7 正 + 18 反（`README.md:418`、`Forge.lean`、`UNIT_CARRIERS`/`UNIT_REJECTED`）；`MUTANTS` = 53 = 28 + 18 + 7（`README.md:420,424`、`selftest.py:1436-1559`、实跑 53/53 全抓）；`fixtures.tsv` = 266 数据行；真实仓库七步自举全绿 + `PKG_UNCHANGED_OK`。 |

---

### 新发现（均不阻断）
无安全漏洞、无功能缺陷、无计数漂移。仅记三处轻微文档/测试注记：
1. `Auditor/EnvGates.lean:96` 文件中段概述注释仍简写为「`<声明>._auto_<数字>`」（`:161` 正式文档注释与 `README.md:277` 已完整标明多段数字后缀）。
2. `runner/fixtures.tsv:261`（`must_green/autoparam/binders`）说明栏未顺带列出本次新增的 `abbrev` 类型别名与局部 `let`/`have`（`ApBinders.lean:28` 已有回归说明）。
3. `runner/README.md:301`（`PostImpl.lean` 行，沿自 r1）仅列 `ENV_META`、`ENV_IMPLEMENTED_BY`，未像 `Impl.lean` 一样括注「（目标另报 `ENV_META`）」（实际 `AUTOPARAM_SPOOFS` 含 `spPostTarget` 共 3 条，使总计 18 条）。

---

### 未覆盖范围
- 本轮为针对 `82d40a3146..e277af4a55` 的只读定点复审，未重审 r1 已核销的块一及零改动受信模块（`Shape.lean`、`Headers.lean`、`Main.lean`、`precheck/`、`run.py`）。
- 实跑验证采信审阅包内 OrbStack Ubuntu `bwrap` + Lean 4.36.0 原始输出（`U1` 25/25、`A2`/`A3` 2/2、自动参数语料 7/7、骨架对照 69/69 + 53/53 mutants、真实仓库七步自举全绿），未在本次重跑其余 259 条非自动参数语料。
- r1 C1 原因段顺带提及但最小修法未强求的「跨模块引用孤立载体」（同模块条件 `getModuleIdxFor? c == getModuleIdxFor? e.name`）仍无单点用例或对应 mutant；`_auto_1__2` 中间双下划线反例未单列（逻辑与已测 `_auto__1` 同由 `!p.isEmpty` 拒）。
- 产物伪造（`.olean`/`.ir` 篡改）仍按设计归 `#2315`。
