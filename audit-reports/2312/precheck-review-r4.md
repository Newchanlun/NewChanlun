# #2312 第一片（纯静态预检）独立审阅报告 R4

- **被审分支与提交**：`origin/infra/2312-e-precheck` @ `59504398f4acc85a08a312624ee000f08cbb5db5`（上一轮被审提交 `d6605824729f45015c6c3ff309c593c8292a38ad`，本轮共 2 个提交：`99a768bd400ad078e19da343ef684328fda02ce9`、`59504398f4acc85a08a312624ee000f08cbb5db5`，仅改动 `formal_math/verification/precheck/` 下三个文件）
- **受审范围**：仅 `formal_math/verification/precheck/` 下三个文件（`precheck.py` 270 行、`selftest.py` 684 行、`README.md` 169 行，合计 1123 行）
- **审阅模型与档位**：Gemini 4 Neon (XHigh)（非作者独立复审，只读审阅：未改被审分支、未评论或修改任何 issue、未开 PR、未起子代理）
- **审阅环境**：macOS，`git version 2.50.1 (Apple Git-155)`，`Python 3.14.6`（临时文件、克隆与工作树均位于 `/Volumes/AgentStorage`，未触碰共享检出工作树）
- **设计依据与前三轮报告**：
  - `origin/evidence/2312-design-consult` @ `aedff2e010e639df3ff411b9d674b5bf62c3440c`（备忘 3.1–3.4、3.7 节与原型 `expT/preflight_proto.py`）
  - R1 报告：`origin/evidence/2312-precheck-review` @ `05c55cc941642549fce9abe4e55a55c4a03df6e0`
  - R2 报告：`origin/evidence/2312-precheck-review-r2` @ `db71f917c4fb4cc7bf82f6268518d031b52b4f73`
  - R3 报告：`origin/evidence/2312-precheck-review-r3` @ `4d2e3d8107020162780563df2bb9370ebcc36709`
- **本轮复现与核验夹具**：同分支 `audit-reports/2312/precheck-r4-fixtures/`（`verify_r3_closures.py`、`run_r4_probes.py`、`replay_origin_main.py`、`run_r4_mutants.py`、`run_extra_edges.py`、`fuzz_oracle.py`）

---

## 一、R3 两条阻断复验

**结论：R3-B1 与 R3-B2 均已彻底闭合。**

### 1. R3-B1（基线清单走 `normative()` 核对文件条目对象类型）

1. **原 R3 夹具全数闭合**：重跑 R3 `repro_r3_blockers.py --case R3-B1` 全部 8 例均稳定退 `2`：
   - 基线 `formal_math/sources/evil.md` 指向 `tree` / `commit` / `tag` 且被审删除之（`decl/x`）：3 例均报 `PRECHECK FAULT BASE_FORM` 退 `2`；
   - `base == head` 均含 `sources/evil.md` 指向 `tree` / `commit` / `tag`（`main`）：3 例均先在 stdout 报 `PRECHECK RED TREE_FORM`，再在 stderr 报 `PRECHECK FAULT BASE_FORM` 并退 `2`；
   - 基线 `sources/evil.md` 指向缺失对象且被审删除之（`decl/x`）：按 `README.md:47` 报 `PRECHECK FAULT GIT` 退 `2`；
   - 基线 `scripts/fm_env.sh` 指向 `tree` 且 `infra/x` 放行修复之：报 `PRECHECK FAULT BASE_FORM` 退 `2`。
2. **新构造 8 组共 17 例 R3-B1 新形状全过**（`verify_r3_closures.py` `[R3-B1-NEW]` 17/17 PASS）：
   - 基线 `formal_math/Chan/Thm/B.lean` 为 `120000` 符号链接指向 `tree` / `commit` / `tag` / `missing`、被审修复（`proof/x`）：前 3 例退 `2 BASE_FORM`，缺失例退 `2 GIT`；
   - 基线 `.github/workflows/formal-math.yml` 指向 `commit` / `tag` / `missing`、`infra/x` 放行修复或删除（6 例）：4 例退 `2 BASE_FORM`，2 例缺失退 `2 GIT`；
   - 基线 `formal_math/verification/run_gates.py` 为 `100755` 指向 `tree`、`infra/x` 放行修复：退 `2 BASE_FORM`；
   - 基线祖先 `scripts` 本身为 `120000` 符号链接指向 `tree` / `missing`、被审恢复为正常 `40000` 目录（`main`）：分别退 `2 BASE_FORM` 与 `2 GIT`；
   - **对照**：基线 `formal_math/sources/sub` 为 `160000` 子模块指向不存在 OID、`decl/x` 删除之：退 `0`（验证基线侧同样豁免 `0o160000`，不误报 `BASE_FORM`/`GIT`）；
   - SHA-256 仓库基线 `sources/evil.md` 指向 `tree` / `missing`、`decl/x` 删除之：分别退 `2 BASE_FORM` 与 `2 GIT`；
   - 基线 `file_objects` 非 `blob` 且被审同时含 `MODE` + `LAKE_FILE`：先在 stdout 报出 `LAKE_FILE` 与 `MODE`，再在 stderr 报 `BASE_FORM` 并退 `2`。

### 2. R3-B2（祖先目录不进改动集合，出现/消失不误红）

1. **原 R3 夹具全数闭合**：重跑 R3 `repro_r3_blockers.py --case R3-B2` 全部 16 例（12 例合成仓无 `formal_math/` 时首次新增或删光 `scripts/other.sh`、`.github/workflows/ci.yml` + 4 例真实 `origin/main` 历史首次引入 `scripts/` 的 `f6ad9b6362..6d221b2f21` 与首次引入 `.github/workflows/ci.yml` 的 `2abaf54559..9560db2d08`）全部稳定退 `0` 且绿行精确匹配。
2. **新构造 6 组共 58 例 R3-B2 新形状全过**（`verify_r3_closures.py` `[R3-B2-NEW]` + `[R3-B2-REAL]` 58/58 PASS）：
   - 仅 `.github` 出现/消失（增删 `.github/README.md`，完全不含 `workflows/`），在无 `formal_math/` 与有 `formal_math/` 两种基线下，覆盖 `main`/`proof/x`/`decl/x`/`audit/x`/`infra/x` 共 20 例全退 `0`；
   - `.github` 已存在时仅 `.github/workflows` 出现/消失（8 例）全退 `0`；
   - 同一提交里 `scripts` 出现 + `.github/workflows` 消失 + 合法 `proof/x` 或 `decl/x` 受管改动（2 例）全退 `0`；
   - 基线 `scripts` 为 `120000` 符号链接（指向 `blob`、无 `fm_env.sh`），被审恢复为正常 `40000` 目录或直接删除（`main`/`proof/x`/`infra/x` 6 例）全退 `0`（验证 `README.md:102`「受信文件的祖先目录不过路径权限，恢复它们不受此限」）；
   - 三个祖先同时出现与同时消失（覆盖 `""`/`main`/`proof/x`/`decl/x`/`audit/x`/`infra/x` 共 12 例）全退 `0`；
   - **真实清理仓库**：在 `59504398f4` 删去 17 处现状后的真实树（含 `scripts/fm_env.sh` 与 13 个非受信工作流、无 `formal-math.yml`）上，删光全部 13 个非受信工作流使 `.github/workflows` 消失再重建，覆盖五种分支共 10 例全退 `0`。

---

## 二、新的阻断缺陷

**无。**

本轮未发现任何「误绿」（第 1 类）、「会影响真实仓库日常使用的误红」（第 2 类），亦未发现会导致调用方做出错误决定的退出码契约或说明不实（第 3、4 类）缺陷。

---

## 三、放行前须修正的条件项

**无。**

---

## 四、非阻断建议

1. **修正 `README.md:101-102` 末尾错位句与恢复边界措辞**：
   - **尾句错位**：`README.md:102`（「基线里本就不是目录的受管节点无法经预检恢复」）末尾黏连了原属 `README.md:101`（「受管范围以外的改动」）的一句「`工作流能否影响 formal-math 作业归 #2315；.gitattributes 对检出的影响由取料片按 git 对象取料来规避（备忘 3.3 实现约束第一条）。`」，建议移回第 101 行末尾。
   - **恢复边界精确表述**：第 102 行写「若基线里 `formal_math` 或其下某个目录位置已经是符号链接、普通文件或子模块，任何角色（含放行的 `infra`）把它改回目录时，该节点报 `PATH_SCOPE`」。实测（`run_r4_probes.py` `[2B-LEGIT-BASE]`）：当非目录节点位于 `formal_math` 根、角色前缀规则的祖先目录、或前缀规则本身的目录边界（如 `formal_math/Chan`、`formal_math/Chan/Thm`、`formal_math/verification`）时确实报 `PATH_SCOPE` 退 `1`；但若位于**严格落在某角色目录前缀规则内部的子目录**（如 `proof` 下的 `formal_math/Chan/Thm/Sub`），`within(path, rules)` 为真，对应角色把它改回合法目录实际退 `0`（安全合法恢复，非误绿）。建议将「其下某个目录位置」改写为「其下角色表前缀边界及以上的目录位置」，更精确且免生歧义。
2. **（可选，低优先级）`README.md:167` 弱化名称顺序列举对齐**：第 167 行列举的 26 种弱化名称与 `selftest.py` 的 `MUTANTS` 集合完全一致，仅「对象类型核对先于形状检查」一项在文档中排第 24、在 `selftest.py` 中排第 20；如需逐项对照顺序可顺手对齐。

---

## 五、核实正确的部分

### 1. 受审对象与本轮改动核对
- `origin/infra/2312-e-precheck` 精确位于 `59504398f4acc85a08a312624ee000f08cbb5db5`，相对 R3（`d660582472`）仅 2 个提交，仅改动 `formal_math/verification/precheck/{precheck.py,selftest.py,README.md}`（270 / 684 / 169 行，合计 1123 行）。
- 规则码集合不变：11 个 `RED` 码（`BRANCH_ROLE`、`CONTENT_SHAPE`、`EMPTY_TREE`、`LAKE_FILE`、`MODE`、`PATH_GRAMMAR`、`PATH_SCOPE`、`TOP_LEVEL`、`TREE_FORM`、`TRUSTED_DRIFT`、`TRUST_UNAPPROVED`）与 7 个 `FAULT` 码（`BAD_REV`、`BASE_FORM`、`GIT`、`INTERNAL`、`NOT_ANCESTOR`、`OUTPUT`、`USAGE`），全部与 `README.md` 一一对应。
- AST 全量控制流核对：`main()` 唯一 `return 0` 在 L261（须 `fault is None and not reds` 且绿行完整写完）；`check()` 无任何提前 `return`；`file_objects()` L141 空清单短路仅在 `not files` 时跳过空 `--batch-check` 子进程。

### 2. 本轮新增面三重点实测（`run_r4_probes.py` 181/181 PASS + `run_extra_edges.py` 9/9 PASS）
1. **祖先目录完全不进改动集合后的安全面（`2A-*`，116 项全过）**：
   - R2-B1 全量攻击面（含原 R2 `repro_r2_blockers.py` 14 例与 R3 `verify_r2_b1_closure.py` 的 33 例负面形状）仍无一逃逸：所有非法祖先模式/类型（31 例）全部稳定退 `1` 报 `MODE`，另 2 例保持 `40000` 但指向非树或树内重名稳定退 `1` 报 `TREE_FORM`（0 例误退 `0`；5 例仅改兄弟文件对照全退 `0`）。
   - 受信文件（`scripts/fm_env.sh`、`.github/workflows/formal-math.yml`）在基线不存在时，于「祖先原已存在」与「祖先同时新建」两种前提下，以合法 `100644` 或 8 种非规范形态（`100755`、`100664`、`120000`、`160000`、空目录、非空目录、`100644->tree`、`100644->missing`）引入，覆盖 `infra` 放行/无放行、`proof/x`、`main`，全部由受管文件自身条目准确触发对应红码/故障码（注：基线不存在时把受信文件以目录形态新增，`allowed()` 走目录分支额外报 `PATH_SCOPE`，连同 `MODE` 退 `1`）。
   - 基线存在受信文件时删之（连同删光兄弟使祖先一起消失），`infra` 放行退 `0`、`infra` 无放行报 `TRUST_UNAPPROVED`、`proof/x` 报 `PATH_SCOPE` + `TRUSTED_DRIFT`、`main` 报 `BRANCH_ROLE` + `TRUSTED_DRIFT`。
   - 祖先被替换为非目录时：有受信文件且 `infra` 无放行报 `MODE` + `TRUST_UNAPPROVED`、`infra` 放行只报 `MODE`；无受信文件且 `infra` 无放行只报 `MODE`。
   - 结构闭环确认：`ANCESTORS = {scripts, .github, .github/workflows}`，`OUTSIDE = (scripts/fm_env.sh, .github/workflows/formal-math.yml)`，`managed()` 下不存在落于 `ANCESTORS` 之下的任何其它受管路径。
2. **`normative()` 对基线与被审提交共用（`2B-*`，22 项全过）**：
   - 15 种含历史形状问题但树结构与 `blob` 类型合规的基线（含 `formal_math/.gitignore`、`100755`、`120000->blob`、`160000->missing`、空目录、大小写冲突、`lakefile.lean`、顶层未知文件、非模块名、`100664`、`040000`、以及 `README.md:102` 恢复边界三例）均不误触 `BASE_FORM` 退 `2`。
   - 基线受管外子树（`rust/`）树内重名或指向缺失对象时按契约不读、忽略退 `0`。
   - 基线 `scripts` `40000->blob` 退 `2 BASE_FORM`、根树截断退 `2 BASE_FORM` 且对象栏写 `-`。
   - 基线受管子树缺失、文件对象缺失、树乱序与文件缺失并存三组情形下，被审红项均先输出到 stdout，随后 stderr 报 `GIT` 并退 `2`，与 `README.md:24,41,47` 完全一致。
3. **「先形状、后对象类型」次序改动（`2C-*`，13 项全过）**：
   - 被审仅 `100644->missing`：无红行，stderr 报 `GIT` 退 `2`；
   - 7 类形状违规（`120000`、`100755`、`100664`、`LAKE_FILE`、`PATH_GRAMMAR`、`CONTENT_SHAPE`、`TOP_LEVEL`）伴随对象缺失：全部先在 stdout 报出对应形状红码，再在 stderr 报 `GIT` 退 `2`；
   - 3 类形状违规伴随对象类型不符（`120000->tree`、`100755->commit`、`lakefile.lean->tag`）：全部退 `1` 且同时报形状码与 `TREE_FORM`；
   - 三者并存（`a.md->tree` + `b.md->missing` + `c.md` `100755`）：先报 `MODE`，随后 `objects()` 在缺失对象处抛 `GIT` 退 `2`（符合 `README.md:24`「已查出的红行照样先写」）；
   - 根树乱序 + `formal_math` 子树缺失：先报根树 `TREE_FORM` 再退 `2 GIT`。
4. **三种小仓库拓扑与真实仓下游提交无误红（`3B-*`，24 项全过 + 真实分支实测）**：
   - 无 `formal_math/`（14 例）、只有 `formal_math/`（6 例）、两者都有（4 例）全部常规改动均退 `0`；
   - `origin/infra/2312-e-precheck` 全部 7 个分支提交（`594e49b5ec..59504398f4`）逐个实跑均精确只报已知的 17 处现状（16 `LAKE_FILE` + 1 `PATH_GRAMMAR`）；全仓 `--all` 涉及 `formal_math` 的 40 次提交转移逐一实跑 0 崩溃、0 次退 `2`；在仓库现存下游清理提交 `be069d974f`（已删除 `.gitignore` 与 16 个旧夹具并引入 `verification/auditor/` 三个允许配置）上实跑 `be069d974f~1..be069d974f`：放行 `infra/2312-f-skeleton` 直接退 `0`（`PRECHECK GREEN OK be069d974f... role=infra`），无放行退 `1`（`TRUST_UNAPPROVED`）。
5. **退出码、输出契约、空清单短路与独立规格预言机对拍（`7-*` 6 项 + `run_extra_edges.py` 9 项 + `fuzz_oracle.py` 120 项全过）**：
   - 计数 wrapper 实测：无受管文件的小仓库上 `cat-file --batch-check` 实际调用 **0 次**（空清单短路生效）；
   - 关闭 fd 2、关闭 fd 1（绿例退 `2 OUTPUT`）、断管红例（仍退 `1`）、ASCII locale 非 UTF-8 分支名（正确转义 `\xff\xfe`）、裸仓、全只读打包仓（`git repack -ad` + `commit-graph` + `chmod 555/444` 实测绿例、`100664` `MODE`、被审 `100644->tree` `TREE_FORM`、基线 `100644->tree` `BASE_FORM`、`scripts 040000` `MODE` 5/5 全过）、0 字节空 `blob`、10 层深目录、仓库级 `git config`（`quotepath`/`ignorecase`/`diff.renames`）、注释标签、简短 SHA、合并提交双父、无关孤儿历史、反斜杠/制表符/中文分支名单行转义、空根树提交、大写十六进制提交串、`formal_math/.` 与 `formal_math/..` 条目、`commit.tree` 指向 `blob`（退 `2 GIT`）、目录 `a` 与文件 `a-b` 的 git 排序边界（`TREE_FORM`）、`git replace` 与 `.git/info/grafts` 伪造抵抗、恶意调用方 `GIT_*` 环境变量隔离、基线与被审 `040755` 目录模式、以及正反次序重复受管条目（`TREE_FORM`）全部实测通过；
   - **独立规格预言机随机对拍（`fuzz_oracle.py`）**：按 `README.md` 规则独立推导预期结果，随机生成 120 组含历史遗留形状、四角色受管改动、受管外兄弟文件与祖先出现/消失、及随机模式/类型变异的 `(base, head, branch, approved)` 场景（15 绿 / 105 红），与 `precheck.py` 实测结果 **120/120 完全一致（0 失配）**。

### 3. 前三轮回归复验（逐项核对差异）
| 轮次与脚本 | 实跑结果 | 差异定性说明 |
|---|---|---|
| R1 `repro_blockers.py` | B1a(4)/B1b(2)/B2(3)/B3(3)/B4(2) 全退 `1`；B5(1) 退 `0` | 无回归（B5 为 R2 已文档化的新设计行为，`README.md:126`） |
| R1 `run_edge_probes.py` | **26/26 OK** | 无回归 |
| R2 `verify_r1_closures.py` | **31/31 PASS** | 无回归 |
| R2 `repro_r2_blockers.py` | **14/14 退 `1`**（均报 `MODE`，0 例退 `0`） | 按 R4 设计：祖先不再进改动集合，故不再附带 `BRANCH_ROLE`/`PATH_SCOPE` |
| R2 `run_r2_probes.py` | **41/43 PASS** | 2 项失败为 R3 预期收紧（`verification/auditor/lakefile.toml` 作目录报 `LAKE_FILE`；`sources/evil.md->tree` 报 `TREE_FORM`），无回归 |
| R3 `repro_r3_blockers.py` | R3-B1 **8/8 退 `2`**；R3-B2 **16/16 退 `0`** | R3 两条阻断全部闭合 |
| R3 `run_r3_probes.py` | **80/80 PASS**（且观察项均已闭合） | 无回归 |
| R3 `verify_r2_b1_closure.py` | 17 PASS / 21 规则码集合差异 | **全部 21 项均退 `1` 且报 `MODE`（0 例退 `0`）**：其中 19 项因祖先不再进 `changed` 而不再附加 `BRANCH_ROLE`/`PATH_SCOPE`，2 项（有 `formal-math.yml` 时 `.github` 换 symlink/gitlink 且 `infra` 放行）因 `.github` 不再进 `changed` 而不再附加 `PATH_SCOPE`（`formal-math.yml` 消失对放行 `infra` 合法）；全部属 R4 按设计改变，非回归 |

### 4. 自测、内置弱化与独立弱化自测
- 未修改的 `selftest.py`（正常 UTF-8 与 `LC_ALL=C -X utf8=0`）：均为 `SELFTEST 229 例，失败 0 例 / SELFTEST PASS`（退 `0`）。
- 抽核本轮新增的 11 条 `selftest.py` 用例（R3-B1 五条、R3-B2 四条、R3-M7 一条、被审符号链接指向缺失对象一条）：11/11 全部通过且 stdout/stderr 流与规则码逐项匹配。
- 未修改的 `selftest.py --mutants`（26 种内置弱化）：未改弱副本 `0/229` 失败，**26/26 种内置弱化全部被抓住**，最终输出 `SELFTEST PASS` 并退 `0`。26 种弱化依次失败例数为：`27, 36, 12, 2, 7, 3, 3, 2, 7, 1, 12, 1, 2, 3, 1, 1, 2, 1, 2, 1, 35, 9, 3, 1, 9, 1`（其中本轮新增 5 种：`对象类型核对先于形状检查` 1/229、`祖先目录的出现与消失进改动集合` 35/229、`基线不核文件条目的对象类型` 9/229、`基线不规范先于被审红项退 2` 3/229、`--batch-check 不核尾随多余字节` 1/229）。
- 本轮独立弱化自测（`run_r4_mutants.py`，10 种针对 R4 新增代码的弱化，未改弱副本 `0/229` 失败）：**9 种行为/安全弱化全部被 `selftest.py` 抓住（9/9 KILLED）**，另 1 种为行为等价性能探针（`R4-M10` 去掉空清单短路，已另由 `run_r4_probes.py` `[7-SHORT]` 计数 wrapper 实证生效）：

  | 编号 | 弱化内容 | `selftest.py` 失败数 | 结果 |
  |---|---|---|---|
  | R4-M1 | 祖先重新进入改动集合（去掉 `p not in ANCESTORS`） | 35/229 | 抓住（KILLED） |
  | R4-M2 | `p not in ANCESTORS` 误写成前缀匹配（连带放掉其下受信文件） | 9/229 | 抓住（KILLED） |
  | R4-M3 | 基线不走 `normative()`（只走 `inventory`，漏基线文件对象类型） | 9/229 | 抓住（KILLED） |
  | R4-M4 | `normative()` 里把 `shape` 与 `file_objects` 顺序调换 | 1/229 | 抓住（KILLED） |
  | R4-M5 | `normative()` 对基线也错做 `shape()`（`with_shape` 默认 `True`） | 9/229 | 抓住（KILLED） |
  | R4-M6 | 被审调用 `normative()` 漏传 `with_shape=True` | 84/229 | 抓住（KILLED） |
  | R4-M7 | `base_form` 收集后被吞掉不抛 `BASE_FORM` | 9/229 | 抓住（KILLED） |
  | R4-M8 | 基线 `normative()` 错传 head 的 `red` 回调（退 2 退化成退 1） | 9/229 | 抓住（KILLED） |
  | R4-M9 | `shape()` 漏查 `ANCESTORS` 的 `TREE_MODE`（重开 R2-B1） | 2/229 | 抓住（KILLED） |
  | R4-M10 | 去掉 `file_objects()` 空清单短路（纯性能行为等价探针） | 0/229 | 等价（已另测 0 次 `--batch-check`） |

### 5. `README.md` 逐句对照
除第四节所列第 101–102 行尾句错位与恢复边界措辞两处非阻断编辑建议外，其余全部可检验陈述（CLI 规则、3 个 git 命令与干净环境、退出码与行格式、受管清单与改动集合、11 个红码与 7 个故障码、受信面与 `.gitignore` 清理口子、角色路径表、顶层固定名字表、与 `run_gates.py:503-582` @ `594e49b5ec` 的 18 行对照表、与 `expT/preflight_proto.py` 的出入、`594e49b5ec` 实测 17 处现状清单、自测与 26 种弱化清单）均经逐项核实准确。

---

## 六、主干回放的范围与统计

在共享检出 `/Users/silencehan/Projects/NewChanlun` 上只读回放 `origin/main`（`30dfe1d9862975ccf83bbb14916b8458ec6836e3`，全历史共 6901 个提交、第一父链 3031 个提交、676 个合并提交、746 个改动 `.github/` 或 `scripts/` 的提交、两个根提交 `f39aa48138e38dea57b6c13a6d48fb4927a59b86` 与 `a901e436f1ca79c8e5210f262342975c8d1d5ae1`；全历史不含 `formal_math/`、`scripts/fm_env.sh` 或 `.github/workflows/formal-math.yml`，且第一父链上仅有 `6d221b2f21` 首次引入 `scripts/` 与 `9560db2d08` 首次引入 `.github` + `.github/workflows/` 两处祖先出现切换）：

1. **多维度回放（`replay_origin_main.py`）**：
   ```sh
   TMPDIR=/Volumes/AgentStorage/tmp python3 -I audit-reports/2312/precheck-r4-fixtures/replay_origin_main.py --real-repo /Users/silencehan/Projects/NewChanlun
   ```
   - 覆盖范围（去重后共 **874** 对 `(base, head)`）：
     - 第一父链最近 250 个提交（`first_parent_recent`：250 对）；
     - 两个根提交自身 `base == head`（`root_self`：2 对）及根附近最早提交（`near_root`：120 对）；
     - 合并提交最近 80 个 + 最早 80 个，对第一父与第二父分别回放（`merge_p1`：160 对，`merge_p2`：160 对）；
     - 改动 `.github/` 或 `scripts/` 的提交最早 120 个 + 最近 120 个（`github_scripts`：240 对，含首次引入 `scripts/` 的 `6d221b2f21` 与首次引入 `.github/workflows/` 的 `9560db2d08`）。
   - 分支名组合：全部 874 对均跑 `main` 与 `proof/x`；其中每第 5 对、两处根提交及两处首次引入祖先的关键提交另加跑 `decl/x`、`audit/x`、`infra/x` 与空串 `""`。
   - **实测结果**：总计调用 `precheck.py` **2460 次**，耗时 `559.75s`，**2460/2460 全部退 `0`（0 次误红、0 次退 2）**。
2. **全量 `.github/` 与 `scripts/` 历史提交补充回放（100% 覆盖）**：
   - 对应可复现命令：`replay_origin_main.py --mode gh-scripts --workers 4 --real-repo /Users/silencehan/Projects/NewChanlun`。
   - 扫描 `origin/main` 全部 **746** 个改动 `.github/` 或 `scripts/` 的提交，展开其前两个父提交（去重后共 **897** 对 `(parent, commit)`），在 `main` 与 `proof/x` 下各跑一次，共 **1794 次**调用（耗时 `115.91s`），**1794/1794 全部退 `0`（0 次误红）**。
3. **全量合并提交补充回放（100% 覆盖）**：
   - 对应可复现命令：`replay_origin_main.py --mode merges --workers 4 --real-repo /Users/silencehan/Projects/NewChanlun`。
   - 扫描 `origin/main` 全部 **676** 个合并提交，展开其全部父提交（去重后共 **1352** 对 `(parent, merge)`），在 `main` 与 `proof/x` 下各跑一次，共 **2704 次**调用（耗时 `179.25s`），**2704/2704 全部退 `0`（0 次误红）**。
4. **全量第一父链历史提交补充回放（100% 覆盖）**：
   - 对应可复现命令：`replay_origin_main.py --mode first-parent --workers 2 --real-repo /Users/silencehan/Projects/NewChanlun`。
   - 从根提交 `f39aa48138` 沿第一父链逐一走到 `origin/main` 末端 `30dfe1d986`，全部 **3030** 对相邻第一父提交转移按 `main` / `proof/x` / `decl/x` / `audit/x` / `infra/x` 轮询回放，共 **3030 次**调用（耗时 `338.90s`），**3030/3030 全部退 `0`（0 次误红）**。
   - **合计**：四组主干回放去重覆盖 **4806** 对真实 `(base, head)`，累计调用 `precheck.py` **9988 次**（覆盖 `origin/main` 100% 第一父链、100% 合并提交全部父边、100% `.github/` 与 `scripts/` 历史提交及两个根提交自身与近根提交），**9988/9988 全部退 `0`（0 误红、0 故障）**。

---

## 七、没覆盖的部分

1. **真实磁盘非 UTF-8 仓库路径**：macOS APFS 拒绝创建非 UTF-8 目录名，未能在本地测得「真实存在的非 UTF-8 仓库路径」判绿情形。
2. **低版本 git**：本机为 `git 2.50.1`，未在低于 2.24（不支持 `rev-parse --end-of-options`）的旧版 git 上实测退 `2`。
3. **`safe.directory` 跨 UID 拒绝**：未在跨用户所有权仓库上实测 git 拒绝打开时退 `2`。
4. **Windows 平台文件描述符行为**：仅在 macOS POSIX 环境下验证 `os.write(1/2, ...)` 与断管/关闭描述符。
5. **十万级超大树 / 极端 DAG 共享子树炸弹上限**：实测大清单规模为 2000 独立文件（`0.45s`），未测十万级文件或深层 DAG 指数展开的内存/时间上限。
6. **GitHub 远端 `receive.fsckObjects` 策略**：只读审阅未向远端推送畸形对象。

---

VERDICT: PASS（范围：仅 `formal_math/verification/precheck/{precheck.py,selftest.py,README.md}` @ `59504398f4acc85a08a312624ee000f08cbb5db5`；与 R1 `05c55cc941`、R2 `db71f917c4`、R3 `4d2e3d8107` 三轮报告合并评估：四轮累计发现的全部 8 条阻断缺陷 R1-B1 至 B5、R2-B1、R3-B1、R3-B2 均已彻底闭合且无回归，本轮新增面经抗绕过、对称性、次序、独立预言机对拍、26 种内置弱化与 9 种独立弱化自测及真实 `origin/main` 9988 次历史回放核验零误绿、零误红、退出码契约严谨，整体判定这三个文件在该提交上可放行，仅留两处非阻断文档措辞建议。）
