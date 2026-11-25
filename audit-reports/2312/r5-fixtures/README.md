# FM-04（#2312）第五轮独立审阅复现夹具索引

对应审阅报告：`audit-reports/2312/FM-04-review-r5.md`
被审提交：`origin/infra/2312-d-perimeter` @ `594e49b5ec034461f9196c6cfb0c58fe017e8dc5`

## 目录说明

- `b1-lakefile-fm-audit-hijack/`：**[R5-B1]** `lakefile.toml` 未钉选 `fm_audit` 的 `root`，在 `infra/*` 分支仅改 `lakefile.toml` 与 `ChanExplore/FakeAudit.lean` 即可劫持审计入口，全 6 道阻断门（含默认全跑与逐门单跑）退出 `0` 并在宿主机落盘；附加 `Chan/Thm/Bogus.lean`（含 `axiom evil : False`）门 1/2/3/6a/15 全退 `0`。
- `b2-lakefile-lean-rce/`：**[R5-B2]** `gate2` 检出 `formal_math/lakefile.lean` 后未提前返回，紧接着调用 `lake` 执行其中的 `run_cmd` 宿主机 IO（且 `--gate 3`/`6a`/`15` 与默认全跑同样触发）；门 2 与默认全跑退出码变为 `2` 而非 `1`。
- `b3-manifest-configfile-rce/`：**[R5-B3]** 门 1 未钉选 `lake-manifest.json` 的 `packagesDir` 与每包 `configFile`/`subDir`；保持 9 包 `name`/`rev`/`type`/`url` 全符 `pins.json`，仅将 `Cli` 的 `configFile` 改为 `../../../.cfg/cli_lakefile.lean` 指向仓库内点目录文件，门 1/2/3/6a/15 全部退 `0` 且在门 2 首次调用 `lake` 时执行 `run_cmd` 宿主机 IO。
- `b4-false-positives-and-readme/`：**[R5-B4]** 语料派生 `syntax-kinds.tsv` 导致的日常 Lean 4 / Mathlib 误拒样本，分为：
  - `readme-promised-blocked.lean`：`README.md` 明文承诺放行但实测门 3 退 `1` 的写法（`open Nat`、`protected`/`nonrec`/`public`、`class inductive`、`@[grind]`/`@[norm_cast]`/`@[simps]`/`@[mono]`、`simp (maxSteps := 1000)`）。
  - `everyday-terms-blocked.lean`：日常基础项语法误拒（`-x`、`#[1, 2]`、`q⁻¹`、`∃ x ∈ xs`、项级 `calc`、`show ... from`、`do` `if`/`←`、`Finset` 字面量与 `∪`、`Type*`）。
  - `everyday-tactics-blocked.lean`：日常基础战术误拒（`by_cases`、`split`、`conv`、`exfalso`、`suffices`、`let`、`funext`、`simp_all`、`revert`、`specialize`、`by_contra`、`push_neg`、`use`、`ext`、`gcongr`、`nlinarith`、`tauto`）。
- `b5-fullrun-exit2-and-sealtables/`：**[R5-B5]** 契约与封表缺陷样本：
  - `BadAx.lean`：任意门 3 源码违例导致默认合入命令 `run_gates.py --repo-root .` 退出 **`2`**（无法判定）而非 **`1`**（红）。
  - `OpenScopedV3.lean`：`open scoped Vector3 in def v : Vector3 Nat 2 := [1, 2]` 在单命令内解除 `sealTables` 擦除并实际执行非白名单作用域宏。
  - `RootSorryCheckAndVar.lean` / `RootSorryGuardMsgs.lean`：`#check (_root_.sorryAx False false)`、未用 `variable (h : False := _root_.sorryAx False false)` 与 `#guard_msgs in #check _root_.sorryAx False false` 绕过 `README.md:89` 整树禁 `sorryAx` 标识符声明（门 2/3 均退 `0`）。
- `b6-gate6b-symlink-head-masked/`：**[R5-B6]** `repro.sh` 复现门 6b 当 `HEAD` 提交了符号链接而暂存区/工作树以普通文件覆盖时返回 `0`（仅查工作树与暂存区，未查 `HEAD` 树对象）。
- `r4-recheck/`：第四轮 9 项 BLOCK（A1–A6、B1–B2）的独立复验最小样本。
