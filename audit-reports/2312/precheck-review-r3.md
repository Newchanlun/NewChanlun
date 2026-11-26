# #2312 第一片（纯静态预检）独立审阅报告 R3

- **被审分支与提交**：`origin/infra/2312-e-precheck` @ `d6605824729f45015c6c3ff309c593c8292a38ad`（上一轮被审提交 `5b6cc3ea1691077835ec02c5614720285b3b687b`，基点 `594e49b5ec034461f9196c6cfb0c58fe017e8dc5`，本轮仅 1 个提交、`+160/-43`）
- **受审范围**：仅 `formal_math/verification/precheck/` 下三个文件（`precheck.py` 264 行、`selftest.py` 637 行、`README.md` 168 行，合计 1069 行）
- **审阅模型与档位**：Gemini 4 Neon (XHigh)（非作者独立复审，只读审阅：未改被审分支、未评论或修改任何 issue、未开 PR、未起子代理）
- **审阅环境**：macOS，`git version 2.50.1 (Apple Git-155)`，`Python 3.14.6`（临时文件、克隆与工作树均位于 `/Volumes/AgentStorage`）
- **设计依据与前两轮报告**：
  - `origin/evidence/2312-design-consult` @ `aedff2e010e639df3ff411b9d674b5bf62c3440c`（备忘 3.1、3.3、3.7 节）
  - #2312 评论 `7175991382`、`7177053075`、`7179030623`
  - R1 报告：`origin/evidence/2312-precheck-review` @ `05c55cc941642549fce9abe4e55a55c4a03df6e0`
  - R2 报告：`origin/evidence/2312-precheck-review-r2` @ `db71f917c4fb4cc7bf82f6268518d031b52b4f73`
- **本轮复现与核验夹具**：同分支 `audit-reports/2312/precheck-r3-fixtures/`（`verify_r2_b1_closure.py`、`repro_r3_blockers.py`、`run_r3_probes.py`、`run_r3_mutants.py`）

---

## 一、R2-B1 复验

**结论：R2-B1 已彻底闭合。**

1. **原 R2 14 个复现形状全部转退 `1`**：在 `d660582472` 上直接重跑 R2 夹具 `repro_r2_blockers.py`（7 个 R2-B1a 形状 + 7 个 R2-B1b 形状），全部 14 例均稳定退 `1`：
   - R2-B1a：`scripts 40000->040000`（`main` 报 `BRANCH_ROLE` + `MODE`；`proof/x` 报 `MODE` + `PATH_SCOPE`；`infra/x` 报 `MODE`）、`scripts 40000->40755`（`proof/x` 报 `MODE` + `PATH_SCOPE`）、`.github 40000->040000`（`proof/x` 报 `MODE` + `PATH_SCOPE`）、`.github/workflows 40000->040000`（`proof/x` 报 `MODE` + `PATH_SCOPE`）及对照例全部退 `1`；
   - R2-B1b：`.github/workflows -> 120000` 符号链接（`main`、`proof/x`、`infra/x`）、`scripts -> 120000 / 100644 / 160000`（`proof/x`）及后续无辜 PR 全部退 `1`（均报 `MODE` 及对应的 `BRANCH_ROLE` / `PATH_SCOPE`）。
2. **新构造 6 组共 38 例同类新形状全部通过**：
   ```sh
   TMPDIR=/Volumes/AgentStorage/tmp python3 -I audit-reports/2312/precheck-r3-fixtures/verify_r2_b1_closure.py
   ```
   实测 `R2-B1 CLOSURE SUMMARY: 38 total, 0 failed`：
   - **基线无祖先目录时直接引入非法祖先节点（12 例）**：基线既无 `scripts` 也无 `.github` 时新增 `scripts` 为 `120000` 符号链接、`160000` 子模块、`100644` 普通文件、`040000` 非规范目录，在 `main`、`proof/x`、放行 `infra/x` 下全部退 `1`（均含 `MODE`）；
   - **`.github` 自身为符号链接或子模块（12 例）**：无论基线是否含 `.github/workflows/formal-math.yml`，将 `.github` 换为 `120000` 或 `160000`，在 `main`、`proof/x`、放行 `infra/x` 下全部退 `1`（均含 `MODE` + 对应角色/漂移码）；
   - **祖先节点下受管外兄弟文件同时变化（9 例）**：在同时修改 `ci.yml`、`scripts/other.sh`、`rust/lib.rs` 时将 `scripts` 改为 `040000` 或将 `.github/workflows` 改为 `40755`，全部退 `1`（均含 `MODE`）；对照仅改上述兄弟文件而祖先保持 `40000`，在 `main`/`proof/x`/`decl/x`/`audit/x`/`infra/x` 五种分支下全部退 `0`；
   - **`scripts` 与 `.github` 一合法一不合法（2 例）**：`scripts` 合法 + `.github` 为 `040000`（`main`），以及 `scripts` 为 `120000` + `.github` 合法（无 `fm_env.sh`，`proof/x`），均退 `1`；
   - **祖先模式保持 `40000` 但对象异常、`changed` 为空（2 例）**：无 `fm_env.sh` 时 `scripts` 保持 `40000` 但指向 blob，或树对象内部非受管文件重名（`signature` 前后均为 `(b"40000",)`、`changed` 为空），均被无条件 `inventory()` 判 `TREE_FORM` 退 `1`；
   - **基线已有非法祖先且被审未触及（1 例）**：基线 `scripts` 已是 `120000`，被审提交仅改 `rust/lib.rs`（`main`），无条件 `shape()` 仍判 `MODE` 退 `1`。
3. **真实仓库克隆验证**：在 `d660582472` 共享克隆上将 `scripts` 改为 `040000`（`proof/x`），以及在 `origin/main`（无 `formal_math/`）共享克隆上将 `.github/workflows` 改为 `120000` 符号链接（`main` 与 `proof/x`），实测均退 `1`（报 `MODE` + `BRANCH_ROLE`/`PATH_SCOPE`）。

---

## 二、新的可复现阻断缺陷

**核心安全边界声明：本轮未发现任何「误绿」（对抗绕过）类缺陷。** 经对 R2-B1 闭合、无条件形状/对象类型检查次序、`signature()` 完备性及 `cat-file --batch-check` 协议边界的全量对抗验证，未构造出任何能使不合规的被审提交退 `0` 的样本。

但本轮新增代码引入了 **2 条新的可复现非误绿类阻断缺陷**（分别踩中「4. 说明不实 + 3. 退出码契约」与「2. 误红 + 4. 说明不实」）。

### R3-B1：`BASE_FORM` 未对基线清单执行 `file_objects()`，违背 `README.md:46-47` 规范与退出码契约

- **所属类别**：**4. 说明不实** + **3. 退出码契约**
- **位置与根因**：`formal_math/verification/precheck/precheck.py:203-209` 与 `README.md:46-47`
  - `README.md:46` 在 `TREE_FORM` 行新增了「清单里模式是文件的条目（子模块除外）指向的对象不是 blob」，凭据栏写「`cat-file --batch` 的原始字节；文件条目的类型取自 `cat-file --batch-check`」；
  - `README.md:47` 的 `BASE_FORM`（退 2）行明文承诺：「**基线清单有上一行的任一问题**」｜「**同上**」；
  - 但 `precheck.py:206-209` 对基线 `base` 只调用了 `inventory(repo, base, ...)`，**漏掉了 `file_objects(repo, old, ...)`**。
  - 结果：当基线清单里含有 `100644` 文件条目指向 `tree` / `commit` / `tag`（或缺失对象）时：
    1. 被审提交将其修复或删除时，不报 `BASE_FORM`（也不报缺失对象的 `GIT`），直接**退 `0`（GREEN）**；
    2. `base == head`（或被审提交原样保留该条目）时，仅报被审提交的 `TREE_FORM` **退 `1`**，不报 `BASE_FORM`、不退 `2`（与基线含乱序/重名条目时 `base == head` 同时报 `TREE_FORM` + `BASE_FORM` 退 `2` 的行为不一致）。
- **逐字复现命令**（在以 `d660582472` 为基点的本分支工作树根目录执行）：
  ```sh
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I audit-reports/2312/precheck-r3-fixtures/repro_r3_blockers.py --case R3-B1
  ```
- **实际退出码与输出**：
  ```text
  === R3-B1 ===
    [基线 sources/evil.md -> tree，被审删除之 (decl/x)] rc=0 head=d5158ebf10cfeebc5d73626ca38d169a0c5e9ac9
      stdout: PRECHECK GREEN OK d5158ebf10cfeebc5d73626ca38d169a0c5e9ac9 role=decl
      extra:  按 README:47 应退 2 (BASE_FORM/GIT)，实际退 0
    [基线==被审均含 sources/evil.md -> tree (main)] rc=1 head=1a75216b3ae38291bed4bc65ebf8e7b3b2b2cca1
      stdout: PRECHECK RED TREE_FORM formal_math/sources/evil.md 文件条目指向的不是 blob，而是 tree
      extra:  按 README:47 应同时报 BASE_FORM 并退 2，实际仅退 1
    [基线 sources/evil.md -> commit，被审删除之 (decl/x)] rc=0 head=7dba45d99fda88264d1c06ff142a26993baf31f9
      stdout: PRECHECK GREEN OK 7dba45d99fda88264d1c06ff142a26993baf31f9 role=decl
      extra:  按 README:47 应退 2 (BASE_FORM/GIT)，实际退 0
    [基线==被审均含 sources/evil.md -> commit (main)] rc=1 head=3168ce065084e6654388c687614358ef0632585b
      stdout: PRECHECK RED TREE_FORM formal_math/sources/evil.md 文件条目指向的不是 blob，而是 commit
      extra:  按 README:47 应同时报 BASE_FORM 并退 2，实际仅退 1
    [基线 sources/evil.md -> tag，被审删除之 (decl/x)] rc=0 head=55939087749f1d73028cd2d0d0b5650e0e504324
      stdout: PRECHECK GREEN OK 55939087749f1d73028cd2d0d0b5650e0e504324 role=decl
      extra:  按 README:47 应退 2 (BASE_FORM/GIT)，实际退 0
    [基线==被审均含 sources/evil.md -> tag (main)] rc=1 head=7c8cc5054e1c85d7c34b7498948c9657e9c90d6f
      stdout: PRECHECK RED TREE_FORM formal_math/sources/evil.md 文件条目指向的不是 blob，而是 tag
      extra:  按 README:47 应同时报 BASE_FORM 并退 2，实际仅退 1
    [基线 sources/evil.md -> missing，被审删除之 (decl/x)] rc=0 head=0218dd3b2228ddd8b9858b212782fa9ff2dae0a5
      stdout: PRECHECK GREEN OK 0218dd3b2228ddd8b9858b212782fa9ff2dae0a5 role=decl
      extra:  按 README:47 应退 2 (BASE_FORM/GIT)，实际退 0
    [基线 scripts/fm_env.sh -> tree，infra 放行修复之] rc=0 head=79e48206cf7375bcece0fcd8a15154c71526b883
      stdout: PRECHECK GREEN OK 79e48206cf7375bcece0fcd8a15154c71526b883 role=infra
      extra:  按 README:47 应退 2 BASE_FORM，实际退 0
  ```

### R3-B2：`ANCESTORS` 将正常的 `None <-> 40000` 变化计入改动集合，导致无 `formal_math/` 仓库及仅改受管外脚本/工作流时误红，且与 `README.md:94,101,125` 矛盾

- **所属类别**：**2. 误红** + **4. 说明不实**
- **位置与根因**：`formal_math/verification/precheck/precheck.py:146-148, 210-217` 与 `README.md:37, 94, 101, 125`
  ```python
  def signature(path, entry):
      return None if entry is None else entry[:1] if path in ANCESTORS else entry
  ```
  - 当基线与被审均不含 `formal_math/`（或不含 `scripts/fm_env.sh` / `.github/workflows/formal-math.yml`——注：当前 `origin/main` 与 `d660582472` 均不含 `.github/workflows/formal-math.yml`）时，在 git 树里**新增首个**非受信文件 `scripts/other.sh` 或 `.github/workflows/ci.yml` 会使祖先目录从 `None` 变为 `(b"40000", oid)`；**删除最后一个**非受信文件会使祖先目录从 `(b"40000", oid)` 变为 `None`。
  - 因为 `signature()` 对 `None` 返回 `None`、对正常目录返回 `(b"40000",)`，二者不等导致 `scripts`、`.github`、`.github/workflows` 进入 `changed`，进而使 **所有非 `infra` 分支（`main`、`feature/*`、`proof/*`、`decl/*`、`audit/*`）全部判红**（`BRANCH_ROLE` 甚至报「却改了 `formal_math` 或受信文件」，`proof/decl/audit` 报 `PATH_SCOPE`），而无放行开关的 `infra/x` 却退 `0`。
  - 这直接在**真实 `origin/main` 历史提交**（不含 `formal_math/`，首次引入 `scripts/` 的 `f6ad9b6362..6d221b2f21` 与首次引入 `.github/workflows/ci.yml` 的 `2abaf54559..9560db2d08`）以及**清理 17 处现状后的真实 `d660582472` 树**（不含 `formal-math.yml`，删除现有 13 个非受信工作流使 `.github/workflows` 消失时，`main` 与 `proof/x` 退 `1`、`infra/x` 退 `0`）上触发误红；同时也构成 `README.md` 内部自相矛盾：`README.md:37` 写「它们出现、消失……都进改动集合」，而本轮新增的 `README.md:94` 写「`.github/workflows/` 下除 `formal-math.yml` 之外的工作流，`scripts/` 下除 `fm_env.sh` 之外的脚本，都不在预检的受管范围内，**任何分支改它们预检都不判红**」，`README.md:101` 写「无论分支名有没有角色，改其它工作流（如 `ci.yml`）、其它脚本……都不判红」，`README.md:125` 写「受管范围以外的路径不进改动集合，不做角色判断；被审清单形状无误时只改它们为绿」。
  - 安全面确认：把 `ANCESTORS` 的 `None` 与 `(b"40000",)` 在 `signature()` 里视为等价**不会引入任何误绿**：① 若涉及受信文件 `scripts/fm_env.sh` 或 `.github/workflows/formal-math.yml` 的增删改，受信文件条目自身必进 `changed` 与 `TRUSTED_DRIFT`；② 若祖先节点变为任何非 `40000` 模式（`040000`/`40755`/`120000`/`100644`/`160000`），其签名 `(mode,) != None`，照样进 `changed` 并触发 `MODE`；③ 若祖先节点为 `40000` 但指向非树对象或树对象内部畸形，无条件 `inventory()` 照样报 `TREE_FORM`。
- **逐字复现命令**：
  ```sh
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I audit-reports/2312/precheck-r3-fixtures/repro_r3_blockers.py --case R3-B2
  ```
- **实际退出码与输出**（节选完整关键项，全部 16 项见夹具输出）：
  ```text
  === R3-B2 ===
    [无 formal_math：新增首个 scripts/other.sh (main)] rc=1 head=c210791c1eafdccb93b49c82a5a44a33ef981d20
      stdout: PRECHECK RED BRANCH_ROLE main 分支名解析不出角色，却改了 formal_math 或受信文件
    [无 formal_math：新增首个 scripts/other.sh (proof/x)] rc=1 head=c210791c1eafdccb93b49c82a5a44a33ef981d20
      stdout: PRECHECK RED PATH_SCOPE scripts proof 角色不得改此路径（A）
    [无 formal_math：新增首个 scripts/other.sh (infra/x)] rc=0 head=c210791c1eafdccb93b49c82a5a44a33ef981d20
      stdout: PRECHECK GREEN OK c210791c1eafdccb93b49c82a5a44a33ef981d20 role=infra
    [无 formal_math：新增首个 .github/workflows/ci.yml (main)] rc=1 head=cd89b53ba5ff7897d778c52b1c8d205999837ad7
      stdout: PRECHECK RED BRANCH_ROLE main 分支名解析不出角色，却改了 formal_math 或受信文件
    [无 formal_math：新增首个 .github/workflows/ci.yml (proof/x)] rc=1 head=cd89b53ba5ff7897d778c52b1c8d205999837ad7
      stdout: PRECHECK RED PATH_SCOPE .github proof 角色不得改此路径（A）
  PRECHECK RED PATH_SCOPE .github/workflows proof 角色不得改此路径（A）
    [无 formal_math：删除最后一个 scripts/other.sh (main)] rc=1 head=a30d70c224c15483633e837745991ebf7183e4f8
      stdout: PRECHECK RED BRANCH_ROLE main 分支名解析不出角色，却改了 formal_math 或受信文件
    [无 formal_math：删除最后一个 .github/workflows/ci.yml (proof/x)] rc=1 head=aac0497a0fcc4af78ff770b02f05bcf9268ae805
      stdout: PRECHECK RED PATH_SCOPE .github proof 角色不得改此路径（D）
  PRECHECK RED PATH_SCOPE .github/workflows proof 角色不得改此路径（D）
    [真实 origin/main 首次新增 scripts/（无 formal_math） (main)] rc=1 head=6d221b2f216f08b38be656a7b3fd8ba4d02b0f24
      stdout: PRECHECK RED BRANCH_ROLE main 分支名解析不出角色，却改了 formal_math 或受信文件
      extra:  real repo f6ad9b6362..6d221b2f21
    [真实 origin/main 首次新增 scripts/（无 formal_math） (proof/x)] rc=1 head=6d221b2f216f08b38be656a7b3fd8ba4d02b0f24
      stdout: PRECHECK RED PATH_SCOPE scripts proof 角色不得改此路径（A）
      extra:  real repo f6ad9b6362..6d221b2f21
    [真实 origin/main 首次新增 .github/workflows/ci.yml（无 formal_math） (main)] rc=1 head=9560db2d08ddd0ca2e2810cf2d915d9fe2a2dd9e
      stdout: PRECHECK RED BRANCH_ROLE main 分支名解析不出角色，却改了 formal_math 或受信文件
      extra:  real repo 2abaf54559..9560db2d08
    [真实 origin/main 首次新增 .github/workflows/ci.yml（无 formal_math） (proof/x)] rc=1 head=9560db2d08ddd0ca2e2810cf2d915d9fe2a2dd9e
      stdout: PRECHECK RED PATH_SCOPE .github proof 角色不得改此路径（A）
  PRECHECK RED PATH_SCOPE .github/workflows proof 角色不得改此路径（A）
      extra:  real repo 2abaf54559..9560db2d08
  ```

### 定性判断与「离可放行还差什么」

1. **定性**：**两条阻断均是本轮新增代码带出的极小实现遗漏，不是「单一视图」静态预检做法本身的问题，且均不属于误绿（对抗绕过）类阻断。**
2. **离可放行还差什么**（仅两处单行级修补 + 文档与自测对齐）：
   - **修 R3-B1**：在 `precheck.py:207` 读完 `old` 后补一行 `file_objects(repo, old, lambda *r: base_form.append(r))`（并在 `selftest.py` 补「基线含 `100644 -> tree`、被审修复/保留均退 2 `BASE_FORM`」用例）；若主控明确决定不查基线文件对象类型，则须把 `README.md:47` 明确改写为仅覆盖 `inventory()` 树结构规范性。
   - **修 R3-B2**：将 `precheck.py:148` 改为 `return None if entry is None or (path in ANCESTORS and entry[0] == TREE_MODE) else entry[:1] if path in ANCESTORS else entry`，同步将 `README.md:37` 的「出现、消失」收紧为「改为非 `40000` 模式或换了类型时进改动集合」（与 `README.md:94,101,125` 完全一致），并在 `selftest.py` 补「无 `formal_math/` 时首次新增/删光 `scripts/other.sh` 与 `ci.yml` 均退 0」用例。
   - 我们在临时副本上实测了上述 **2 行最小修补**：`repro_r3_blockers.py` 的 R3-B1 全部 8 项转退 `2`、R3-B2 全部 16 项转退 `0`；`repro_r2_blockers.py` 原 14 项全退 `1`；`verify_r2_b1_closure.py` 38/38 全过；`verify_r1_closures.py` 31/31 全过；`run_r3_probes.py` 80/80 全过；`selftest.py` 原 192 项 `192/192` 全过（零回归）。

---

## 三、非阻断建议

1. **补齐本轮新增代码对应的 `selftest.py` 弱化覆盖缺口（见 R3 独立弱化自测）**：
   我们对本轮新增代码做了 8 种独立弱化（`audit-reports/2312/precheck-r3-fixtures/run_r3_mutants.py`），结果如下：
   | 编号 | 弱化内容 | `selftest.py` 失败数 | 结果 |
   |---|---|---|---|
   | R3-M1 | 无条件 `shape(new, red)` 改回仅在 `changed` 非空时执行 | 1/192 | 抓住（KILLED） |
   | R3-M2 | `signature()` 对祖先目录也比对象名（`return entry`） | 3/192 | 抓住（KILLED） |
   | R3-M3 | 去掉 `file_objects(repo, new, red)` 调用（不做 blob 类型核对） | 2/192 | 抓住（KILLED） |
   | R3-M4 | `LAKE_FILE` 例外不再限制为 `BLOB` 文件 | 1/192 | 抓住（KILLED） |
   | R3-M5 | `file_objects()` 漏排除 `0o160000` 子模块条目 | 3/192 | 抓住（KILLED） |
   | R3-M6 | `shape()` 不检查 `ANCESTORS` 的 `TREE_MODE`（仅查 `FM_ROOT`） | 2/192 | 抓住（KILLED） |
   | R3-M7 | 将 `shape()`/`file_objects()` 移到 `BASE_FORM` 之后（破坏「先报被审红项」次序） | 0/192 | **逃逸（SURVIVED）** |
   | R3-M8 | `objects()` 仅在 `body=True` 时核对尾随多余字节（漏 `--batch-check`） | 0/192 | **逃逸（SURVIVED）** |

   建议在 `selftest.py` 补两条用例：① 基线树不规范同时被审含 `MODE`/`TREE_FORM` 时，断言退 `2` 且同时输出被审红码与 `BASE_FORM`（封住 R3-M7）；② `wrapped-git` 另测 `--batch-check` 尾随多余字节（封住 R3-M8）。
2. **微调 `precheck.py:202` 行内注释**：原文「先于一切可能退 2 的步骤」略宽（`resolve()` 的 `BAD_REV`/`GIT`、`merge-base` 的 `NOT_ANCESTOR` 以及 `inventory(head)`/`file_objects(head)` 自身的 `GIT` 都在其前或其中）；`README.md:41` 的「在读基线清单之前做完，所以基线树不规范退 2 时，被审提交的红项已先报出」表述更准确，注释可与文档对齐。
3. **`file_objects()` 空清单短路**：当被审清单里没有任何非目录/非子模块条目时（如当前无 `formal_math/`、无 `fm_env.sh`、无 `formal-math.yml` 的 `origin/main`），`file_objects()` 仍以空列表调用一次 `git cat-file --batch-check` 子进程；首行加 `if not files: return` 可省一次空子进程启动。
4. **记录 `allowed()` 在基线已损坏目录变文件时的恢复边界**：若基线已存在 `scripts`/`formal_math` 为 `120000` 符号链接（非树），因 `allowed()` 要求两侧皆为 `None` 或目录节点才走祖先目录放行，连带 `--trusted-change-approved` 的 `infra/x` 将其改回 `40000` 目录也会报 `PATH_SCOPE`（仅在异常基线恢复时出现，正常主干不会命中）。

---

## 四、核实正确的部分

1. **受审提交与改动面核对**：
   - `origin/infra/2312-e-precheck` 精确为 `d6605824729f45015c6c3ff309c593c8292a38ad`，相对 R2（`5b6cc3ea16`）仅 1 个提交，只改 `formal_math/verification/precheck/{precheck.py,selftest.py,README.md}`（264 / 637 / 168 行，共 1069 行）。
   - 规则码集合不变：11 个 `RED` 码（`BRANCH_ROLE`、`CONTENT_SHAPE`、`EMPTY_TREE`、`LAKE_FILE`、`MODE`、`PATH_GRAMMAR`、`PATH_SCOPE`、`TOP_LEVEL`、`TREE_FORM`、`TRUSTED_DRIFT`、`TRUST_UNAPPROVED`）与 7 个 `FAULT` 码（`BAD_REV`、`BASE_FORM`、`GIT`、`INTERNAL`、`NOT_ANCESTOR`、`OUTPUT`、`USAGE`），全部与 `README.md` 一一对应。
2. **本轮新增面三重点实测核验（`run_r3_probes.py` 80/80 通过）**：
   - **提前返回点与次序审计（AST 全量枚举）**：`precheck.py` 全文 `return` / `raise` / `break` / `continue` 逐条核对如下：
     - `main()`：`L244`（`USAGE` 退 2）、`L255`（**全脚本唯一 `return 0`**，须 `fault is None and not reds` 且绿行完整写完）、`L259`（退 2）、`L260`（退 1）；
     - `check()`：无任何提前 `return`，仅有 `L199`（`NOT_ANCESTOR` 退 2）、`L209`（`BASE_FORM` 退 2）两处 `raise` 与末尾 `L224` 一处 `return head, role`；任何到达 `return 0` 的执行路径必然已完整执行 `resolve(base/head)` → `merge-base` → `inventory(head)` → `shape(new)` → `file_objects(new)` → `inventory(base)` → `changed` → 角色/放行 → `TRUSTED_DRIFT`；
     - `inventory()` `L114 continue` / `L120 break`、`shape()` `L173 continue` / `L182 continue` 均在调用 `red(...)` 之后发生（已锁定非 0）；`shape()` `L175 continue` 仅在 `MODE` 通过后跳过非 `formal_math/` 条目的内部文法规则；
     - `BASE_FORM` 次序实测：基线树乱序且被审同时含 `TREE_FORM`（`100644 -> tree`）+ `LAKE_FILE` + `MODE` 时，三条 `PRECHECK RED` 均先写到 stdout，随后 `PRECHECK FAULT BASE_FORM` 写到 stderr 并退 `2`；
     - `formal_math/` 存在性四象限：双方均无 `formal_math/`（含 `scripts/` 与 `.github/workflows/` 正常改动）六种分支全退 `0`；仅基线含时非 `infra` 删光均退 `1`，仅含 `infra` 文件时放行 `infra` 删光退 `0`、无放行退 `1`；仅被审含时单角色引入合法路径退 `0`、混入受信+内容退 `1`。
   - **`signature()` 完备性全矩阵**：逐一构造 `scripts/fm_env.sh` 与 `.github/workflows/formal-math.yml` 在祖先目录保持 `40000`（且伴随兄弟文件同时修改）下的**新增、删除（兄弟留存）、改内容、改模式 `100755`、换 `120000` 符号链接、换 `160000` 子模块、换 `40000` 目录**共 28 组组合，`proof/x` 与无放行 `infra/x`（及放行 `infra/x` 对非法模式）全部准确判红；经核 `managed()` 下不存在任何其它落在 `ANCESTORS` 之下的受管路径。
   - **`cat-file --batch-check` 与 `file_objects()` 边界**：
     - 协议直测 18 项边界（空列表、单/多对象去重排序、`missing`、`ambiguous`、空输出、少行、多行、乱序、缺尾换行、尾随多余字节/换行、四字段、两字段、负数/非十进制/空大小、OID 不符）全过，并确认请求载荷严格为纯 40/64 位十六进制 OID 行，绝不含路径；
     - 端到端：`sources/`、`Chan/Thm/`、`verification/auditor/lakefile.toml`、`scripts/fm_env.sh`、`.github/workflows/formal-math.yml` 的 `100644` 指向 `tree`/`commit`/`tag` 均退 `1`（`TREE_FORM`）；指向缺失对象退 `2`（`GIT`）；`120000` 指向 `tree` 报 `MODE` + `TREE_FORM` 退 `1`，指向缺失对象先报 `MODE` 再报 `GIT` 退 `2`；`160000`/`160755` 子模块指向不存在 OID 跳过 `--batch-check` 只报 `MODE` 退 `1`；根上非受管 `160000` 子模块忽略退 `0`；含空格/换行/伪造 `batch-check` 头行的文件名正常报 `PATH_GRAMMAR` + `TREE_FORM`；损坏 zlib blob 退 `2`（`GIT`）；SHA-256 仓库下 `100644 -> tree` 报 `TREE_FORM` 退 `1`；2000 个不同 blob 大清单耗时 `0.28s` 无死锁退 `0`，混入 1 个 `100644 -> tree` 准确退 `1`（`TREE_FORM`）。
3. **前两轮回归复验**：
   - `verify_r1_closures.py`（R1 B1–B5 共 31 项）：**31/31 通过**，无回归；
   - `run_r2_probes.py`（R2 43 项探针）：**41/43 结果完全不变**，仅作者声明的 2 项因本轮收紧而按预期由 `0` 转 `1`（`verification/auditor/lakefile.toml` 作目录报 `LAKE_FILE`；`sources/evil.md` 指向树对象报 `TREE_FORM`）。
4. **真实仓库与无误红验证**：
   - 当前 `origin/main`（无 `formal_math/`）近 100 对相邻主线提交（`origin/main~100..origin/main`）在 `main` 及 `origin/main~1..origin/main` 在 `proof/x` 下全部退 `0`（历史首次引入 `scripts/` 与 `.github/workflows/ci.yml` 的两处早期提交见 R3-B2）；
   - `594e49b5ec..d660582472` 实跑精确报出 `README.md:142-143` 列明的 17 处现状（16 处 `LAKE_FILE` + 1 处 `formal_math/.gitignore` 的 `PATH_GRAMMAR`）；
   - 在共享克隆上由放行 `infra/cleanup` 删除该 17 处后，清理提交本身退 `0`（无放行退 `1` 报 `TRUST_UNAPPROVED`，`proof/cleanup` 退 `1` 报 `PATH_SCOPE` + `TRUSTED_DRIFT`）；在其上的干净真实树验证 `decl`、`proof`、`audit`、`infra`（含无放行改 `README.md`、放行改 `lakefile.toml` 与新增 `formal-math.yml`）以及 `main`/`proof`/`decl` 仅改 `rust/`、`ci.yml`、`scripts/other_r3.sh` 共 11 项常规改动全部退 `0`。
5. **作者自测与弱化自测复跑**：
   - 未修改的 `selftest.py` 在 macOS 正常 UTF-8 与 `LC_ALL=C -X utf8=0` 环境下均跑出 `SELFTEST 192 例，失败 0 例 / SELFTEST PASS`（退 `0`）；
   - 抽核 11 条本轮新增用例（`R2` 前缀、`R2-M2`、`R2-M10`、`file_objects`、`LAKE_FILE` 目录例外等），全部确因声称规则码而红且输出流无错位；
   - 未修改的 `selftest.py --mutants` 全量 22 种内置弱化在 macOS 上完整实跑通过（`SELFTEST PASS`，退 `0`；未改弱副本 `0/192` 失败，22 种弱化失败例数依次为 `27 / 34 / 12 / 4 / 7 / 3 / 3 / 2 / 7 / 1 / 12 / 1 / 2 / 3 / 1 / 1 / 1 / 1 / 8 / 1 / 2 / 1`）。
6. **`README.md` 逐句核对与退出码/输出契约**：除上述 R3-B1（`README.md:47`）与 R3-B2（`README.md:37` vs `94/101/125`）两处不符外，其余 CLI 参数规则、3 个 git 命令与干净环境、18 行旧门 6b 对照表、`LAKE_FILE` 6 例外、角色表与顶层名字表、自举 17 处清单、22 种弱化说明，以及关闭 stderr（绿例仍退 0、故障例仍退 2）、断管/关闭 stdout、UTF-8 字节直写与转义契约均经逐项核实准确。

---

## 五、没覆盖的部分

1. **真实磁盘非 UTF-8 仓库路径**：macOS APFS 拒绝创建非 UTF-8 目录名，未能在本地测得「真实存在的非 UTF-8 仓库路径」判绿情形。
2. **低版本 git**：本机为 `git 2.50.1`，未在低于 2.24（不支持 `rev-parse --end-of-options`）的旧版 git 上实测退 `2`。
3. **`safe.directory` 跨 UID 拒绝**：未在跨用户所有权仓库上实测 git 拒绝打开时退 `2`。
4. **Windows 平台文件描述符行为**：仅在 macOS POSIX 环境下验证 `os.write(1/2, ...)` 与断管/关闭描述符。
5. **十万级超大树 / 极端 DAG 共享子树炸弹上限**：本轮大清单实测规模为 2000 独立文件（`0.28s`），未测十万级文件或深层 DAG 指数展开的内存/时间上限。
6. **GitHub 远端 `receive.fsckObjects` 策略**：只读审阅未向远端推送畸形对象（注：R3-B2 复现对象 100% 合法，已在真实 `origin/main` 历史上直接命中）。

---

VERDICT: BLOCK — 范围：#2312 第一片纯静态预检（`formal_math/verification/precheck/{precheck.py,selftest.py,README.md}` @ `d6605824729f45015c6c3ff309c593c8292a38ad`）；结合 R1、R2 与本轮 R3 三份报告的整体判断：前两轮全部 6 条阻断（R1 B1–B5、R2-B1）均已彻底闭合，三轮对抗审查未发现任何残余「误绿」（对抗绕过）缺陷，单一视图静态预检主干稳固，当前仅因本轮新增代码带出的 2 条非误绿单行级遗漏（R3-B1 `BASE_FORM` 漏核基线文件对象类型、R3-B2 `ANCESTORS` 的 `None <-> 40000` 引发无 `formal_math/` 误红与文档冲突）暂缓放行。
