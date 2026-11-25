# NewChanlun 票 #2312（FM-04 机器门禁）第五轮独立非作者审阅报告

- **被审分支与提交**：`origin/infra/2312-d-perimeter` @ `594e49b5ec034461f9196c6cfb0c58fe017e8dc5`
- **对照基线**：第四轮被审提交 `5c52c92856bf4aac7661a66735faa99a9817c8b4`；第四轮审阅报告 `origin/evidence/2312-d-review` @ `6a700b4255123f44a955c190a1d7296a8b7643c2`
- **审阅范围**：仅阻断门（用户裁定 #2312 评论 `7164343103`：门 1 钉选、门 2 受控选项与零告警、门 3 源码层与环境层白名单、门 6a 声明锁 v3、门 6b 路径权限、门 15 模块边界）。已核对 `git diff 5c52c92856..594e49b5ec -- formal_math/verification/EnvGates.lean`（仅改 11 行：门 6a `letE` 编码 `nondep` 升级 `FM-lock-v3`、门 15 放行派生证书），未改动 `--report` 语义报告实现。
- **审阅模型与思考强度**：`Gemini 4 Neon (XHigh)`
- **本机磁盘空间与方法边界**：macOS，Lean 4.36.0；开工 `df -h /` 可用 **`3.6 GiB`**（审阅全程 `/` 在 **`2.9–5.8 GiB`** 间波动，低于 6 GiB 阈值；`/Volumes/AgentStorage` 可用 `16–20 GiB`）。遵循磁盘约束：**未执行**全量 `lake build`、**未执行**全量 `selftest.py`（253+131），未下载或复制 Mathlib（复用 `/Volumes/AgentStorage/fm/lake/infra-2312-b-env-gates-2428b08ce810d112/packages` 符号链接）。全部结论均基于：一次靶向预编 `fm_audit` + 独立最小夹具实跑验证、Lean 4.36.0/Mathlib 环境静态图扫描、以及被审提交逐行读码。所有阻断缺陷均有本机实跑复现证据，未依赖未实跑推论。

---

## 一、第四轮九项复验表

所有复验夹具均由审阅者独立构造并在独立临时仓库中实跑（最小样本归档于 `audit-reports/2312/r5-fixtures/r4-recheck/`）。

| 第四轮编号 | 原缺陷概要 | 本轮状态 | 独立复验夹具与执行命令 | 实测退出码与关键输出 |
|---|---|---|---|---|
| **R4-A1** | 精化期求值/RCE（零导入 `include_str (unsafe (unsafeIO ...))`、`include_str`、`sudo`+`by_elab`、`eval%`、`trace`、`success_if_fail_with_msg`、项级 `unsafe`） | **已闭合** | `r4-recheck/a1-include-str-unsafe-io.lean` 及 6 组独立单文件变体；`lake exe fm_audit source ... 3` 与 `run_gates.py --repo-root . --gate 3` | 全部 **`rc=1`**（精化前 `kindIssues` 拒绝：`Lean.includeStr`、`Lean.Parser.Term.unsafe`、`Lean.byElab`、`Mathlib.Meta.eval_expr`、`Mathlib.Tactic.successIfFailWithMsg`、`Lean.Parser.Tactic.trace`）；宿主机哨兵文件 **`sentinel_exists=false`**，被审代码未执行。 |
| **R4-A2** | `Mathlib.Tactic.SudoSetOption`（经 `Mathlib.Tactic.Common` 再导出）篡改受控/内核选项 | **已闭合**（附带门 2 退出码回归见 R5-B5） | `r4-recheck/a2-sudo-common.lean`；`run_gates.py --repo-root . --gate 3` 与 `--gate 2` | `--gate 3`：**`rc=1`**，`GATE3 RED ... TOKEN 语法种类不在白名单：termSudoSet_option___In_`。（注：单跑 `--gate 2` 退 **`2`**，属新缺陷 R5-B5 同一根因。） |
| **R4-A3** | `lakefile.toml` 的 `moreLeanArgs`/包级 `leanOptions` 绕过门 2 | **原选项入口已闭合**（但新白名单与 `lakefile.lean` 引入致命缺陷 R5-B1/R5-B2） | 3 组独立 `lakefile.toml`（`moreLeanArgs`、包级多写 `linter.deprecated`/`debug.skipKernelTC`、重复键非法 TOML）；`run_gates.py --repo-root . --gate 2` | 3 组均 **`rc=1`**，分别输出 `LAKEFILE_KEY`：`lean_lib 键不在白名单：moreLeanArgs`、`包级 leanOptions 只许 ... 三项`、`lakefile.toml 无法解析`。 |
| **R4-A4** | `#guard_msgs (substring := true)` 无 `drop` 吞错误/告警，且内嵌放行 `deriving instance` / `attribute` | **已闭合** | `r4-recheck/a4-guard-msgs-substring.lean` 及内嵌 `deriving instance Repr`、`attribute [simp]` 共 3 组；`run_gates.py --repo-root . --gate 3` | 3 组均 **`rc=1`**，输出 `#guard_msgs 只许不带规格的精确匹配写法` 与 `#guard_msgs 内只许 #check 与 #print axioms：Lean.Parser.Command.{deriving,attribute}`。 |
| **R4-A5** | 环境层 `generatedBy` 压制 `ENV_EXTERN`，且豁免 1（`ctorIdx`）与豁免 3（派生 `partial`）可伪造 | **已闭合** | `r4-recheck/a5-extern-on-exempt.lean`、`MyProp.ctorIdx` 伪造、单构造子 `Single.ctorIdx._impl` 伪造、`instReprTree.repr` 发散伪造共 4 组；先 `lake build` 再直调 `lake exe fm_audit 3 <mod> ChanTest.Probe` | 4 组均 **`rc=1`**：`ENV_EXTERN`（不再被豁免压制）、`ENV_IMPLEMENTED_BY`+`ENV_UNSAFE`（`MyProp` 与单构造子 `Single` 均拒）、`ENV_PARTIAL`（无源码派生证书即拒）。 |
| **R4-A6** | `_root_.sorryAx` 绕过 `example` 占位证明封堵（单跑门 3 退 0） | **已闭合**（对 `example` 及所有声明；非声明位置见 R5-B5） | `r4-recheck/a6-root-sorryax-example.lean` 及结构默认值/可选参数/`where`/`mutual`/`instance`/`decreasing_by` 共 7 组；`run_gates.py --repo-root . --gate 3` | 7 组全部 **`rc=1`**，`GATE3 RED ... TOKEN 声明使用了占位证明（sorry）`（经 Lean `hasSorry` 标签捕获）。 |
| **R4-B1** | 普通递归归纳类型 `deriving Ord` 被门 3 `ENV_PARTIAL` 误杀 | **已闭合** | `r4-recheck/b1-b2-rec-ord-and-defs-deriving.lean`（及单独 `BinTree deriving Ord`）；`run_gates.py --repo-root . --gate 2/3/15` | `--gate 2` / `3` / `15` 全部 **`rc=0`**（源码派生证书传递给环境层，普通递归 `Ord` 正常豁免）。 |
| **R4-B2** | `Chan/Defs/` 内 `deriving Repr`/`Hashable` 被门 15 `EXPOSE_SECTION` 误杀 | **已闭合** | `r4-recheck/b1-b2-rec-ord-and-defs-deriving.lean` + 增量/互递归/普通递归/`@[expose]` 派生/私有归纳派生共 5 组；`run_gates.py --repo-root . --gate 2/3/15` | 5 组在 `--gate 2` / `3` / `15` 全部 **`rc=0`**；对照手写缺失 `@[expose]` 定义在 `Chan/Defs/` 仍准确报门 15 `rc=1` `EXPOSE_SECTION`。 |
| **R4-O1** | `README.md` 对阻断门的承诺多处失实 | **未闭合** | 逐行核对 `formal_math/verification/README.md` 与实测行为 | 第四轮指出的旧条目已改写，但本轮新增至少 5 处与实测直接冲突的阻断门承诺（退出码 0/1/2、`open`/修饰符/`class inductive`/属性/字面量配置白名单、`sealTables` 防护边界、整树禁 `sorryAx`、`rfl'` 展开描述），详见 **R5-B4**、**R5-B5**。 |

---

## 二、新的阻断缺陷（共 6 项，均为 BLOCK）

### [R5-B1]（致命 / BLOCK）`lakefile.toml` 白名单未钉选 `fm_audit` 的入口模块：`infra/*` 分支可劫持审计程序，在宿主机任意落盘且全 6 道阻断门（含默认全跑）全部退出 `0`

- **位置**：
  - `formal_math/verification/run_gates.py:142-183`（`LAKEFILE_KEYS["lean_exe"] = {"name", "root", "supportInterpreter"}` 只检查键名与 `supportInterpreter` 类型，**从未核验 `fm_audit` 的 `root == "verification.Audit"`**，也未钉选 `[[lean_lib]]` 的 `roots`/`globs`）。
  - `formal_math/verification/run_gates.py:515-516`（门 6b 的 `PATHS["infra"]` 允许 `infra/*` 分支同时修改 `formal_math/lakefile.toml` 与 `formal_math/ChanExplore/`）。
- **机理**：
  在 `infra/hijack` 分支上，完全无需修改 `formal_math/verification/` 下任何文件：只需在 `formal_math/ChanExplore/FakeAudit.lean` 写入一段零警告、无 `meta`/`unsafe`、不导入 `Lean` 的纯 Lean `public def main (args : List String) : IO UInt32`（对 `headers` 返回匹配的导入列表、对 `source` 返回 `[true,[],[]]`、对其他子命令返回 `0`，同时执行任意 `IO.FS.writeFile` / `IO.Process.spawn`），并将 `formal_math/lakefile.toml` 中 `[[lean_exe]] name = "fm_audit"` 的 `root` 改为 `"ChanExplore.FakeAudit"`（另在 `FMEnvGates` 的 `roots` 补上 `"verification.Audit"` 以通过门 15 的 `lake query`）。随后 `run_gates.py` 每次执行 `lake exe fm_audit ...` 时，Lake 自动编译并运行攻击者的 `FakeAudit`：
  1. 门 1 通过（未改工具链与 manifest）；
  2. 门 2 通过（`lakefile.toml` 全在白名单键内，`FakeAudit.lean` 零告警，`lake build --wfail` 退出 0）；
  3. 门 3、门 6a、门 15 全部由 `FakeAudit` 伪造绿灯返回 `0`；
  4. 门 6b 通过（改动仅在 `infra/*` 允许的 `formal_math/lakefile.toml` 与 `formal_math/ChanExplore/FakeAudit.lean`）。
- **最小复现夹具**：`audit-reports/2312/r5-fixtures/b1-lakefile-fm-audit-hijack/`（含 `formal_math/lakefile.toml`、`formal_math/ChanExplore/FakeAudit.lean`、以及附加的 `formal_math/Chan/Thm/Bogus.lean`）。
- **复现命令与实测输出**：
  1. 仅改动 `lakefile.toml` + `ChanExplore/FakeAudit.lean`（分支 `infra/hijack`）：
     ```sh
     python3 formal_math/verification/run_gates.py --repo-root .
     ```
     - **实测退出码**：**`0`**（标准输出为空、标准错误为空；宿主机哨兵文件被写入 `PERFECT_6_OF_6_HOST_RCE`）。
     - 逐门单跑 `--gate 1` / `2` / `3` / `6a` / `6b` / `15`：6 道阻断门**全部退出 `0`**。
  2. 在同一 `lakefile.toml` 下向 `formal_math/Chan/Thm/Bogus.lean` 写入 `axiom evil : False; theorem boom : False := evil`：
     ```sh
     for g in 1 2 3 6a 15; do python3 formal_math/verification/run_gates.py --repo-root . --gate "$g"; done
     ```
     - **实测退出码**：门 1、门 2、门 3、门 6a、门 15 **全部退出 `0`**，且门 2/3/6a/15 均触发宿主机哨兵写入。
- **严重度定性**：**BLOCK（致命）**。这是可信计算基（TCB）的直接自举劫持：被审配置文件可以替换审计二进制本身，使所有 6 道阻断门形同虚设并在审计期获得宿主机任意代码执行。

---

### [R5-B2]（致命 / BLOCK）`gate2` 检出 `lakefile.lean` 后未提前返回，门 3/6a/15 完全不检查 `lakefile.lean`，导致审计期直接执行宿主机 `run_cmd` IO

- **位置**：
  - `formal_math/verification/run_gates.py:120-125, 163-164`：`lakefile_whitelist` 在第 163–164 行检出 `(fm / "lakefile.lean").exists()` 后只打印 `GATE2 RED ... LAKEFILE_KEY` 并设 `failed = True`，但 `gate2` 在第 122 行之后**未 `return 1`**，紧接着第 123 行调用 `audit_sources(root, "2")` → `lake exe fm_audit headers ...`。
  - `formal_math/verification/run_gates.py:232-238, 309-315, 495-501, 630-631`：门 3、门 6a、门 15 调用 `lake` 前均未检查 `lakefile.lean` 是否存在。
- **机理**：
  Lake 4.36.0 在同目录同时存在 `lakefile.lean` 与 `lakefile.toml` 时优先加载并精化 `lakefile.lean`（输出 `info: [root]: lakefile.lean and lakefile.toml are both present; using lakefile.lean`）。只要仓库放入含 `run_cmd do IO.FS.writeFile ...` 的 `formal_math/lakefile.lean`，运行 `--gate 2`、`--gate 3`、或默认全跑 `run_gates.py --repo-root .` 时：
  1. 尽管 `gate2` 已经把 `lakefile.lean` 判红，仍立即启动 `lake` 编译并执行 `lakefile.lean` 中的 `run_cmd` 宿主机 IO；
  2. 默认全跑还会继续运行 `gate3`、`gate6a`、`gate15`，反复触发 `lake`；
  3. 同时因后续 `lake exe fm_audit` 报错抛出 `Undetermined`，使 `--gate 2` 与默认全跑的退出码从 `1`（红）退化为 **`2`（无法判定）**。
  - **同类延伸**：`run_gates.py:120-129` 的注释明写「名单外即红，构建照跑以便读数」——这意味着 `lakefile.toml` 中任何触发 `LAKEFILE_KEY`（但未触发前面 `LEAN_OPTION_OVERRIDE` 早退）的危险键（如 `plugins`、`dynlibs`、`moreLeancArgs`、`precompileModules` 等）同样在被判红后**照常传给 `lake` 执行**。
- **最小复现夹具**：`audit-reports/2312/r5-fixtures/b2-lakefile-lean-rce/formal_math/lakefile.lean`。
- **复现命令与实测输出**：
  ```sh
  python3 formal_math/verification/run_gates.py --repo-root . --gate 2
  python3 formal_math/verification/run_gates.py --repo-root . --gate 3
  python3 formal_math/verification/run_gates.py --repo-root .
  ```
  - **实测退出码**：三者均退出 **`2`**；三者均在宿主机成功写下哨兵文件，内容为 **`LAKEFILE_LEAN_EXECUTED_IN_AUDIT`**。
  - `--gate 2` 节选输出：
    ```text
    stdout: GATE2 RED formal_math/lakefile.toml:1 LAKEFILE_KEY 不许 lakefile.lean（Lake 会优先读它，绕开本白名单）
    stderr: GATE2: 无法判定：lake exe fm_audit headers ...: info: [root]: lakefile.lean and lakefile.toml are both present; using lakefile.lean
            error: unknown executable fm_audit
    ```
- **严重度定性**：**BLOCK（致命）**。直接违背「审计期不执行被审代码」的核心安全目标：明知存在禁用的 `lakefile.lean` 却依然启动 `lake` 执行它，且把确定性红灯降级为退出码 `2`。

---

### [R5-B3]（高危 / BLOCK）门 1 未钉选 `lake-manifest.json` 的 `packagesDir` 与各依赖 `configFile`/`subDir`：修改 `Cli.configFile` 指向仓库内隐藏文件即可在门 1/2/3/6a/15 全绿（`rc=0`）下执行宿主机 `run_cmd` IO

- **位置**：`formal_math/verification/run_gates.py:66-82`。
- **机理**：
  本轮门 1 补上了 `type == "git"` 与 `url` 核对，但仍未核对顶层 `packagesDir` 以及每个依赖项的 `configFile`、`subDir`、`scope`、`inputRev`、`inherited`、`manifestFile`。Lake 读取 `lake-manifest.json` 时，按各依赖的 `configFile`（相对 `<packagesDir>/<pkg>/`）加载其配置文件；若后缀为 `.lean`，Lake 直接精化并执行其中的 `run_cmd`。同时 `run_gates.py:38` 的 `sources()` 跳过以 `.` 开头的目录（`not d.startswith(".")`）。
  因此，保持全部 9 个依赖的 `name`、`rev`、`type`、`url` 与 `pins.json` 逐字一致，仅在仓库内放一份 `formal_math/.cfg/cli_lakefile.lean` 并把 `lake-manifest.json` 中 `Cli` 的 `"configFile"` 改为 `"../../../.cfg/cli_lakefile.lean"`（在标准 Lake 目录结构 `.lake/packages/Cli` 下恰好回指 `formal_math/.cfg/cli_lakefile.lean`）：
  1. 门 1 退 **`0`**；
  2. 门 2 首次调用 `lake` 时精化并执行 `cli_lakefile.lean` 中的 `run_cmd` 写宿主机文件，且因 `Chan` 不导入 `Cli`，`lake build --wfail` 顺利通过，门 2 退 **`0`**；
  3. 门 3、门 6a、门 15 均因 `.cfg` 被 `sources()` 忽略且 Lake 已缓存配置，全部退 **`0`**。
- **最小复现夹具**：`audit-reports/2312/r5-fixtures/b3-manifest-configfile-rce/`（`formal_math/.cfg/cli_lakefile.lean` + `manifest-patch.json`；另验证了改动 `mathlib.configFile` 指向绝对路径同样门 1 退 `0`、门 2 退 `0` 并落盘）。
- **复现命令与实测输出**（`adv3g_manifest_inrepo_cli`，真实 `.lake/packages/Cli` 目录结构）：
  ```sh
  for g in 1 2 3 6a 15; do python3 formal_math/verification/run_gates.py --repo-root . --gate "$g"; done
  ```
  - **实测结果**：
    - `--gate 1`：**`rc=0`**，stdout 为空；
    - `--gate 2`：**`rc=0`**，stdout 为空，宿主机哨兵文件被写入 **`INREPO_CLI_MANIFEST_CONFIGFILE_RCE`**；
    - `--gate 3` / `6a` / `15`：全部 **`rc=0`**，stdout 为空。
  - 另测仅改顶层 `packagesDir = "evil_pkgs"`：`--gate 1` 同样退 **`0`**。
- **边界说明与严重度定性**：**BLOCK（高危）**。需如实说明：当前门 6b 的四类分支路径白名单均不包含 `formal_math/lake-manifest.json`，常规 PR 直接修改 manifest 会在门 6b 被拒；但（1）门 1 自身独立承诺「九个依赖须符合 `pins.json`」已被击穿，单门或依赖维护流程中完全放行；（2）在默认全跑顺序（`GATES` 依次跑 `1 → 2 → 3 → 6a → 6b → 15`）中，**门 2 在门 6b 之前运行**，即便门 6b 最终判红，恶意 `run_cmd` 也已在门 2 期间于宿主机执行完毕！

---

### [R5-B4]（高危 / BLOCK）语料派生 `syntax-kinds.tsv` 导致大面积日常合法 Lean 4 / Mathlib 写法被误拒，并直接违背 `README.md` 多条明文白名单承诺

- **位置**：
  - `formal_math/verification/syntax-kinds.tsv`（308 条允许种类，仅从当前小语料经验采集）、`formal_math/verification/Perimeter.lean:88-103`（`kindIssues` 拒绝一切不在 `syntax-kinds.tsv` 内的语法节点）。
  - 对照 `formal_math/verification/README.md:59-83` 与 `formal_math/verification/SourceGates.lean:47-75`、`Perimeter.lean:72-85`。
- **机理**：
  `SourceGates.lean` 与 `README.md` 声明了一套较完整的命令、声明、修饰符、属性与字面量配置白名单，但本轮新增的 `Perimeter.kindIssues` 在精化前要求整棵语法树的每个节点种类都出现在语料采集的 `syntax-kinds.tsv` 中。实查 `syntax-kinds.tsv` 可确认：
  - `open` 家族仅录入了 `open` 与 `openScoped`，缺失 `openSimple` / `openOnly` / `openHiding` / `openRenaming`；
  - 命令/声明/修饰符缺失 `classInductive`、`protected`、`nonrec`、`public`；
  - 属性家族仅录入了 `ext`、`instance`、`simp`、`simple`、`specialize`、`gcongrAttr`，凡带专用解析器种类的白名单属性（`grind`、`norm_cast`、`simps`、`mono`）全部缺失；
  - 配置项家族仅录入了 `posConfigItem`/`negConfigItem`，缺失 `valConfigItem` 与 `scientific`（尽管 `Perimeter.lean:76-84` 专门写了 `valConfigItem` 和 `scientific` 的校验分支！）；
  - 大量核心 Lean 4 / Mathlib 基础项与战术（如一元负号、数组字面量、`by_cases`、`split`、`conv`、`funext`、`ext`、`use`、`by_contra`、`push_neg`、`nlinarith`、`tauto` 等）因未在 `Common.lean` 116 行语料中出现而被全部封杀。
- **最小复现夹具**：`audit-reports/2312/r5-fixtures/b4-false-positives-and-readme/` 下 3 份汇总文件（所有项均已在独立单文件夹具中逐一实测 `run_gates.py --repo-root . --gate 3`）。
- **实测读数（41 组独立单特性探针中 36 组门 3 退 `1`，另 4 项白名单属性专项实测退 `1`）**：
  1. **直接违背 `README.md` 明文白名单承诺（全部实测 `--gate 3` 退 `1`，`--gate 2/15` 退 `2`）**：
     - `open Nat`（`README.md:59`）→ `语法种类不在白名单：Lean.Parser.Command.openSimple`；`open Foo (a)` / `hiding` / `renaming` → `openOnly` / `openHiding` / `openRenaming`
     - `protected def` / `nonrec def` / `public def`（`README.md:69-70`）→ `Lean.Parser.Command.{protected,nonrec,public}`
     - `class inductive`（`README.md:67`）→ `Lean.Parser.Command.classInductive`
     - `@[grind]` / `@[norm_cast]` / `@[simps]` / `@[mono]`（`README.md:71-74`）→ `Lean.Parser.Attr.{grind,norm_cast,simps}`、`Mathlib.Tactic.Monotonicity.Attr.mono`
     - `simp (maxSteps := 1000)` / `simp (zeta := false)`（`README.md:82`、`Perimeter.lean:76-84`）→ `Lean.Parser.Tactic.valConfigItem`
  2. **日常基础 Lean 4 / Mathlib 项语法误拒（全部实测 `--gate 3` 退 `1`）**：
     - 一元负号 `-x`（`«term-_»`）、数组字面量 `#[1, 2]`（`«term#[_,]»`）、倒数 `q⁻¹`（`«term_⁻¹»`）、有界存在 `∃ x ∈ xs, ...`（`Lean.«term∃__,_»`）、项级 `calc`（`Lean.calc`）、`show ... from ...`（`Lean.Parser.Term.{show,fromTerm}`）、`do` 内 `if`（`doIf`/`doIfProp`）与 `let x ← o`（`doLetArrow`/`doIdDecl`/`doExpr`）、`Type*`（`Lean.Elab.Term.«termType*»`）、`Finset` 集合操作 `∪` 与 `{1, 2}`（`Mathlib.Meta.SetNotationForOrder.unionStx'`、`«term{_}»`）。
  3. **日常基础 Lean 4 / Mathlib 战术误拒（全部实测 `--gate 3` 退 `1`）**：
     - 核心战术：`by_cases`（`«tacticBy_cases_:_»`）、`split`、`conv` / `conv_lhs`（`Lean.Parser.Tactic.Conv.*` / `Mathlib.Tactic.Conv.convLHS`）、`exfalso`、`suffices`、`let`（`tacticLet__`）、`case`、`funext`、`simp_all`、`revert`、`specialize`；
     - Mathlib/Batteries 常用战术：`by_contra`、`push_neg`、`use`、`ext`、`gcongr`、`nlinarith`、`tauto`。
- **严重度定性**：**BLOCK（乙类误拒 + 文档失实）**。不仅直接否定 `README.md` 明确列出的白名单特性（连 `open Nat` 和 `protected` 都无法写），而且连一元负号 `-x`、`by_cases`、`funext`、`ext`、`use` 等最基本的形式化证明原语均被封死，实际无法承接日常数学形式化开发。

---

### [R5-B5]（中高危 / BLOCK）默认全跑退出码契约破坏、`open scoped ... in` 绕过 `sealTables` 封表，以及 `README.md` 多处与实测矛盾

本项汇总三处已实测坐实的机制/契约缺口及对 `README.md`「防什么、不防什么」交接边界的核验：

1. **任何门 3 源码违例都导致默认合入命令退出 `2`（无法判定）而非 `1`（红）**：
   - **位置**：`formal_math/verification/SourceGates.lean:426-431`、`formal_math/verification/run_gates.py:123, 275-276, 682, 714-720`。
   - **机理**：`gate2` 与 `gate15` 分别调用 `audit_sources(root, "2")` 与 `audit_sources(root, "15")`。当被审文件存在任意门 3 源码红点（如 `axiom evil : False`）时，`SourceGates.lean:428, 430` 因 `blocked = has "3" || has "build"` 对门 2 与门 15 返回退出码 **`2`**；`run_gates.py:275` 捕获非 `(0, 1)` 抛出 `Undetermined`；`main()` 对各门退出码取 `max`，最终整套阻断门返回 **`2`**！`selftest.py` 仅单跑 `--gate 3` 而从未测过默认全跑，因此漏检。
   - **复现夹具与实测输出**：`audit-reports/2312/r5-fixtures/b5-fullrun-exit2-and-sealtables/BadAx.lean`；执行 `python3 formal_math/verification/run_gates.py --repo-root .`：
     - **实测退出码**：**`2`**（违背 `README.md:16`「阻断门退出码为 0 绿、1 红、2 无法判定；CI 不接受 2」）；
     - stdout 报 `GATE3 RED ... 声明不在白名单：Lean.Parser.Command.axiom`，但 stderr 报 `GATE2: 无法判定：[false,[["3",3,...]],[]]` 与 `GATE15: 无法判定：...`。
2. **`open scoped <NS> in <cmd>` 在单条命令内解除 `Perimeter.sealTables` 擦除并实际执行非白名单作用域宏；且 `sealTables` 漏封 7 张表中的非用户类别处理器**：
   - **位置**：`formal_math/verification/Perimeter.lean:110-128`、`formal_math/verification/SourceGates.lean:320-322`、`README.md:46-49`。
   - **机理与实测**：
     - `open scoped Vector3 in def v : Vector3 Nat 2 := [1, 2]` 是**单条** `Lean.Parser.Command.in` 命令。`sealTables` 在命令精化前擦除了 `Vector3` 作用域内的非白名单宏；但精化 `open scoped Vector3` 时，Lean 的 `ScopedEnvExtension.activateScoped` 调用 `ExtensionState.insert` 把这些条目**从 `erased` 中移除**，随即同一命令内的 `[1, 2]`（表层种类 `«term[_,]»` 在白名单内，已过 `kindIssues`）便**实际执行了 `Vector3` 的非白名单作用域宏**并展开出 `Mathlib.Notation3.expandFoldr`！（`expandNamespacedDeclaration` 在 `def NS.foo` 上亦有同类命令内 `activateScoped`。）
     - 最小夹具 `audit-reports/2312/r5-fixtures/b5-fullrun-exit2-and-sealtables/OpenScopedV3.lean`，执行 `lake exe fm_audit source Chan.Thm.OpenScopedV3 Chan/Thm/OpenScopedV3.lean 3`：
       - **实测输出**：`rc=1`，stderr 明确打印 `error: elaboration function for 'Mathlib.Notation3.expandFoldr' has not been implemented: expand_foldr% (h✝ t✝ => cons✝ h✝ t✝) nil✝ [1, 2]`——坐实 `Vector3` 的非白名单作用域宏确实已被执行（仅因展开产物落到被封的 `expandFoldr` 才报错，而非 `README.md:47-48` 宣称的「不会调用它」）。
     - 另经 Lean 环境内省（按 `SourceGates.lean:436-437` 同一方式启用 `enableInitializersExecution` + `processHeader` 加载标准库与 Mathlib 后执行 `Perimeter.sealTables`），确认因 `userCategories = [command, term, tactic, doElem]` 过滤，仍有大量非白名单处理器未被擦除：`grind` 表 **61** 条、`tactic` 表（主要为 `conv`）**66** 条、`macro` 表 **107** 条、`term` 表 **15** 条（含 `Qq.termBy_elabq_`）、`command` 表 **8** 条（含 `Lean.Elab.ConfigEval.deriveEvalExprUsingMeta`）、`doElem` 表 **1** 条、`inductive` 表 **1** 条（`coinductive`）。（注：经静态核查，当前钉选库中未发现经此可直接触发 RCE 的允许种类作用域处理器，但明确击穿 `README.md:46-49` 的第二道防线承诺。）
3. **`README.md` 其余两处与实测直接冲突**：
   - **`README.md:89` 整树禁 `sorryAx` 标识符**：`SourceGates.lean:146` 仍只比对裸标识符 `` == `sorryAx ``。虽然声明/example 由 `hasSorry` 兜底，但 `audit-reports/2312/r5-fixtures/b5-fullrun-exit2-and-sealtables/RootSorryCheckAndVar.lean`（`#check (_root_.sorryAx False false)` 与未用 `variable (h : False := _root_.sorryAx False false)`）以及 `RootSorryGuardMsgs.lean`（`#guard_msgs in #check _root_.sorryAx False false`）实测 `--gate 2` 与 `--gate 3` 均退出 **`0`**。
   - **`README.md:79-80` 的 `rfl'` 展开描述**：`README.md:79-80` 宣称「`rfl'` 展开出 `smartUnfolding`，判红（`decreasing_by` 里的也能看到）」，但实测 `rfl'` 已在精化前被 `syntax-kinds.tsv` 拒绝，根本不会展开出 `smartUnfolding`（且作者自己在本轮把 `must_red/g3/library-macro-option/expect_detail.txt` 从 `选项不在白名单：smartUnfolding` 改成了 `语法种类不在白名单：Lean.Parser.Tactic.tacticRfl'`）。
4. **对 `README.md:162-171`「这套门禁防什么、不防什么」三项交接的独立评估**：
   - 交接 1（健全性 → 门 4 独立内核重放）与交接 3（陈述含义 → 门 6a + 非作者独审 + `lake comparator`）：边界划分本身清晰合理。
   - **交接 2（审计与构建期碰宿主机 → 精化前拒求值 + CI 沙箱 #2315）在当前实现下不能掩盖 R5-B1/B2/B3**：文档将「`lake build` 编译被审代码 / 库精化器未知路径」交给 CI 沙箱是合理的，但 **R5-B1** 让被审 `lakefile.toml` 直接替换审计程序 `fm_audit` 本身（即便放进无网络只读沙箱，门禁依然全部返回 `0` 放行任意 `axiom : False`！），而 **R5-B2** 与 **R5-B3** 是审计器自身在调用 `lake` 之前未做好基础文件/manifest 校验就主动执行被审 `lakefile.lean` / `configFile`，属于门禁自身失职，不属于应当推给沙箱的外部风险。
- **严重度定性**：**BLOCK**。默认合入命令遇门 3 红灯退 `2` 直接使 CI 无法区分「代码违规」与「工具故障」；连同上述多处文档失实，第四轮 R4-O1 亦未完全闭合。

---

### [R5-B6]（中高危 / BLOCK）门 6b 符号链接检查仅查工作树与暂存区、未查 `HEAD` 提交树：`HEAD` 含符号链接时可被暂存区普通文件掩盖而退 `0`

- **位置**：`formal_math/verification/run_gates.py:559-574`；对照 `README.md:30`（「分别核对提交、暂存区、工作树与整个仓库的未跟踪文件；不让差异相消……改动里不得有符号链接」）。
- **机理**：
  第 559–561 行虽然分别收集了 `(base, head)`、`("--cached", head)` 和工作树三层的变更路径 `changes`，但第 571 行检查符号链接时只写了：
  ```python
  if (root / path).is_symlink() or command(root, "git", "ls-files", "-s", "--", path).stdout.startswith("120000"):
  ```
  两者仅检查**工作树**（`is_symlink()`）和**暂存区索引**（`git ls-files -s`），漏查 **`HEAD` 提交树**（如 `git ls-tree HEAD -- <path>` 或 `git diff --raw base head`）！若用户在 `proof/*` 分支提交了一个符号链接 `120000` 到 `HEAD`，随后在工作树与暂存区用同名普通文件覆盖（或 `git rm --cached`），`gate6b` 退出 **`0`**，但 `HEAD` 中依然保留 `120000` 符号链接（本地验收绿灯后执行 `git push` 即把符号链接推上远端）。
- **最小复现夹具**：`audit-reports/2312/r5-fixtures/b6-gate6b-symlink-head-masked/repro.sh`。
- **复现命令与实测输出**（`adv9b_6b_symlink_committed` vs `adv9b_6b_symlink_replaced_in_index`）：
  1. 提交符号链接 `formal_math/Chan/Thm/link.lean -> Ok.lean` 后运行 `run_gates.py --repo-root . --gate 6b`：**`rc=1`**，`GATE6b RED formal_math/Chan/Thm/link.lean:1 SYMLINK 改动不得包含符号链接`。
  2. 在工作树删除该链接并写入普通文件后执行 `git add formal_math/Chan/Thm/link.lean`（此时 `HEAD` 仍为 `120000`），再次运行 `run_gates.py --repo-root . --gate 6b`：**`rc=0`**（stdout 为空）。
- **严重度定性**：**BLOCK**。直接打破门 6b「三层独立核对、不让差异相消」及「改动里不得有符号链接」的机械不变式；修复仅需同时核对 `git ls-tree HEAD`（及 `base..head` 中新出现的 `120000`）。

---

## 三、非阻断建议（共 6 项）

1. **`Inventory.lean:199` 与 `make_lists.py:99-105` 的单条最短链归类存在「短安全链遮蔽长危险链」隐患**：
   `Inventory.scan` 对每个 `(精化器, 危险常量)` 只计算 BFS **一条最短路径** `pathTo`；若某精化器既经短链命中 `profileitIO`（匹配 `PATH_RULES`），又经另一条更长路径调用 `unsafeBaseIO` 执行危险逻辑，`make_lists.py` 只看到前者就会放行。建议改为在移除已审屏障节点后的子图上重算可达性（本轮我们已独立按该口径扫描了全部 278 条允许精化器与 24 个白名单属性，确认当前钉选版本中未发现被遮蔽的 `evalTerm`/`evalExpr`/`evalConst`/`IO.FS.*`/`IO.Process.*`/`unsafeBaseIO`/`ofReduceBool` 路径，仅见 Lean 核内与 `linarith` 辅助的 `dbgTrace`）。
2. **`must_red` 自测抽查发现 2 处「因前置规则提前拦截而未覆盖宣称路径」**：
   本轮对 31 组 `must_red`（覆盖 g1/g2/g3/g6b）逐一核查实际红因，发现：
   - `must_red/g3/sorry-via-export`：第 4 行死于 `命令不在白名单：Lean.Parser.Command.export` 与裸 `sorryAx`，根本未进入精化，从未测到第 6 行 `Hole.sorryAx` 的 `hasSorry` 路径；
   - `must_red/g3/r4-p4a-decreasing-by-rfl-prime`（以及 `library-macro-option`）：在精化前死于 `tacticRfl'` / `tacticUnhygienic_` 不在 `syntax-kinds.tsv`，不再覆盖 `decreasing_by` 异步信息树 `substituteLazy` 展开路径。
   - 另建议 `selftest.py` 增设不带 `--gate` 的默认全跑回归用例（覆盖所有门联动，避免 R5-B5 这类全跑退 `2` 的回归漏网）。
3. **`SourceGates.lean:37` 残留过时注释**：
   注释仍写「`ChanExplore` 按同一白名单审，另外只多放行 `#eval`」，但实际代码与 `README.md:63` 均已禁止 `ChanExplore` 使用 `#eval`（本轮 `adv8h_explore_eval` 已实测退 `1`）。建议删除该句避免误导。
4. **`SourceGates.lean:303-304` 预检阶段无条件调用 `scopedIssues`**：
   当 `inspect` 或 `Perimeter.kindIssues` 已经拒绝某命令时，第 304 行仍会执行 `scopedIssues cmd`（内含 `expandMacros attr`）。建议在 `inspect`/`kindIssues` 命中门 3 阻断后跳过 `scopedIssues`，严格遵守「被拒命令零展开」。
5. **`elaborators.tsv` 归类条目计数口径与 `README.md` / 说明对齐**：
   实数 `elaborators.tsv` 共 286 条（允许 278、拒收 8），其中允许项包含：静态闭包干净 **215** 条、静态闭包命中危险入口并经 `PATH_RULES` 归类 **62** 条（并非实现者自述中的 52 条）、以及 `EXTRA` 手工白名单 **1** 条（`Lean.Elab.Command.elabPrintAxioms`）；`syntax-kinds.tsv` 共 309 条（允许 308、拒收 1）。
6. **两处细小稳健性与文档精确度打磨**：
   - **畸形类型 `lakefile.toml` 退 `2`**：当 `lakefile.toml` 合法解析但字段类型错误（如 `lean_lib = "bad"`），`run_gates.py:97` 在 `lakefile_whitelist` 之前即因 `'str' object has no attribute 'get'` 抛异常使门 2 退 **`2`**（`adv4b_bad_toml_type` 实测），建议在 `gate2` 入口先做类型校验并归入 `LAKEFILE_KEY` 退 `1`。
   - **`README.md:29` 对 `FM-lock-v3` `let`/`have` 的措辞**：`README.md:29` 写「`have` 与 `let` 不再同码」，但同提交的 `must_green/g6a/r4-p9a-let-vs-have/README.md` 已注明 Lean 4.36.0 把普通非依赖 `let` 与 `have` 精化为同一个 `letE (nondep := true)` 内核项，建议 `README.md:29` 改为「当内核表达式的 `nondep` 位不同时不再同码」。

---

## 四、核实正确的部分

1. **项/战术层封闭世界静态调用图（去屏障复核）干净**：审阅者独立编写 Lean 静态图扫描器，在**移除 `make_lists.py` 全部 9 个 `PATH_RULES` 屏障节点**后，对 `elaborators.tsv` 全部 278 条允许精化器与 `SourceGates.lean` 全部 24 个白名单属性做可达性验证，确认：**0 条**新增路径可达 `evalTerm`、`evalExpr`、`evalExpr'`、`evalExprCore`、`evalConst`、`IO.FS.*`、`IO.Process.*`、`IO.getEnv`、`unsafeBaseIO`、`unsafeIO`、`Lean.ofReduceBool`、`Lean.ofReduceNat`、`Lean.trustCompiler`。
2. **精化期求值入口与配置求值封堵有效**：实测证实 `include_str`（含零导入 `unsafe (unsafeIO ...)`）、`by_elab`、`eval%`、`trace`、`success_if_fail_with_msg`、项级 `unsafe`、`sudo set_option`、`#eval`（含 `ChanExplore`）、`decide +native`、`decide (native := true)`、`linarith (config := {})`、`aesop (config := {})`、`grind => sorry` 全部在精化前被门 3 拒绝（`rc=1`），无宿主机落盘。
3. **门 3 环境层与派生证书机制扎实**：
   - `ENV_EXTERN` 已移至 `generatedBy` 豁免判定之前，`Audit.lean:127-128` 实测无豁免；
   - `ctorIdxImpl` 逐字重算类型、定义体与实现体，成功拦截 `Prop` 归纳类型伪造与单构造子 `Single.ctorIdx._impl` 伪造；
   - 基于源码层声明范围的派生证书同时修复了 R4-B1（普通递归 `deriving Ord`）与 R4-B2（`Chan/Defs/` 内 `deriving Repr`/`Hashable`），并在增量派生、互递归派生、普通递归派生、`deriving @[expose] Repr`、私有归纳派生 5 种场景下全部门 2/3/15 退 `0`，同时手写缺失 `@[expose]` 定义仍准确被门 15 判红，直调 `fm_audit 3` 时手写发散 `instReprTree.repr` 仍被 `ENV_PARTIAL` 拒绝。
4. **`#guard_msgs` 收紧完整**：精确拒绝 `(substring := true)` 等任意规格参数，且内嵌命令严格限于 `#check` 与 `#print axioms`（`deriving instance` 与 `attribute` 均拒）。
5. **门 6a 声明锁 v3 `nondep` 编码生效**：实测 `fm_audit 6a` 输出 `FM-lock-v3` 并在 `let` 节点显式编码了布尔位 `nondep`。
6. **门 6b 新边缘修复（除 R5-B6 外）有效**：空后缀分支名（`decl/`、`decl/   `）、仓根未跟踪文件（`stray_root.txt`）、工作树/暂存区直接存在的符号链接均已实测退 `1`。
7. **旧阻断门 `must_red` 未被弱化**：核对 `git diff 5c52c92856..594e49b5ec -- formal_math/verification/must_red/`，旧阻断门期望码均未放松（`g2` 的 `r2-a5/a6*` 新增期望码 `LAKEFILE_KEY` 为加强，`g6a` 同步更新为 v3 哈希，仅 `g3/library-macro-option/expect_detail.txt` 因 `rfl'` 被提前在种类名单拦截而更新提示语，已记入建议 2）。

---

## 五、未覆盖的部分

1. **全量 `lake build --wfail` 与全量 `selftest.py`（253 阻断 + 131 报告）**：因本机根分区 `/` 可用空间持续低于 6 GiB（`2.9–5.8 GiB`），遵磁盘纪律未执行全量构建与全量自测，仅执行了 31 组 `must_red` 抽查与 100+ 次独立靶向对抗/误拒夹具实跑。
2. **语义审阅报告（`--report`：S、7a、7b、8a、8b、9、10）**：按本轮用户范围裁定不纳入审阅；已通过 `EnvGates.lean` diff 确认本轮未改动 `--report` 逻辑。
3. **未导入 Mathlib 子模块的 `scoped` 处理器穷举**：`Perimeter.sealTables` 审计加载了基础 `Lean` + 常用 `Mathlib` 战术与数据结构模块（如 `Vector3`、`Common`、`Linarith`、`Aesop`、`Simps`、`GCongr`、`Finset` 等），未对整个 Mathlib 数千个模块逐一加载并穷举所有 `scoped` 宏/精化器。
4. **仓库外防线**：门 4 独立内核重放、CI 沙箱隔离（#2315）、`lake comparator` 不在本次提交代码范围内，本报告仅评判 `README.md` 与之划定的职责交接边界。

VERDICT: BLOCK（作用域：阻断门 1/2/3/6a/6b/15；因根分区可用空间低于 6 GiB 未跑全量构建与全量自测，上述 6 项新阻断缺陷与第四轮 9 项复验结论均基于本机靶向夹具实跑复现及源码/静态图核验）
