# #2312 第一片（纯静态预检）独立审阅报告 R1

- **被审分支与提交**：`origin/infra/2312-e-precheck` @ `a1035da72789a8f99f8b8b7c66b8f2e543823464`（基点 `594e49b5ec034461f9196c6cfb0c58fe017e8dc5`）
- **受审范围**：仅 `formal_math/verification/precheck/` 下三个文件（`precheck.py`、`selftest.py`、`README.md`）
- **审阅模型与档位**：Gemini 4 Neon (XHigh)（非作者独立审阅，只读，未修改被审分支/issue/PR，未起子代理）
- **审阅环境**：macOS，`git version 2.50.1 (Apple Git-155)`，`Python 3.14.6`（临时文件与工作树均位于 `/Volumes/AgentStorage`）
- **设计依据**：`origin/evidence/2312-design-consult` @ `aedff2e010e639df3ff411b9d674b5bf62c3440c` 的 `audit-reports/2312/design-consult/2312-design-consult.md`（第 3.1、3.3、3.7 节与第六节第三处）；#2312 评论 `7175991382`
- **复现夹具**：同分支 `audit-reports/2312/precheck-r1-fixtures/`（`repro_blockers.py`、`run_custom_mutants.py`、`run_edge_probes.py`）

---

## 一、可复现的阻断缺陷

本轮共复现 **5 条阻断缺陷**（B1 同时踩中「1. 误绿」与「4. 说明不实」；B2、B3、B4 属「1. 误绿」；B5 属「4. 说明不实」）。以下所有命令均在以 `a1035da72789a8f99f8b8b7c66b8f2e543823464` 为基点的本分支工作树根目录下逐字可执行，不改动 `precheck/` 任何文件、不控制运行环境。

### B1：同目录同名异类重复树条目绕过 `BAD_TREE` 并覆盖 `entries[path]`，导致两类误绿

- **所属类别**：**1. 误绿** + **4. 说明不实**
- **位置与根因**：`formal_math/verification/precheck/precheck.py:78-82`
  ```python
  parent, _, name = path.rpartition(b"/")
  key = name + b"/" if kind == TREE else name
  if parent in last and key <= last[parent]:
      raise Fault("BAD_TREE", path, "树条目重复或未按 git 顺序排列")
  last[parent], entries[path] = key, (mode, kind, oid)
  ```
  当同一目录下先后存在同名非目录条目（`120000` 符号链接、`100755` 可执行文件、`160000` 子模块或 `100644` 普通文件）与目录条目（`040000 tree`）时，两者的排序键分别为 `b"X"` 与 `b"X/"`。按字节序 `b"X" < b"X/"` 严格递增（即使中间夹着 `X.lean`，因 `0x2E < 0x2F`，仍有 `b"X" < b"X.lean" < b"X/"`），因此 `key <= last[parent]` 不触发 `BAD_TREE`，随后 `entries[path] = ...` 静默覆盖前一条记录。
  - **B1a（误绿：在内容目录或门禁目录中藏匿非法条目）**：基线完全正常；被审提交在 `formal_math/Chan/Thm/` 下按 git 序写入 `(120000/100755/160000/100644, Sub)` + `(100644, Sub.lean)` + `(040000, Sub)`（含合法 `Sub/E.lean`）。`git diff-tree` 明确报告了新增的 `120000 formal_math/Chan/Thm/Sub`（位于 `proof` 允许的 `Chan/Thm/` 前缀下），但 `entries[b"formal_math/Chan/Thm/Sub"]` 被目录覆盖，`shape()` 完全看不到符号链接/可执行位/子模块/非 `.lean` 文件，预检退 `0`。同样手法在 `infra/x --trusted-change-approved` 下的 `formal_math/verification/` 中也可隐藏 `120000` 符号链接并退 `0`。
  - **B1b（误绿：绕过根节点受管路径变动比对）**：基线完全正常；被审提交在仓库根写入 `(120000, formal_math)` + 基线原样的 `(040000, formal_math)`，并同时改动 `rust/lib.rs`。`entries[b"formal_math"]` 被后一条原样树覆盖，`precheck.py:142` 的 `all(old.get(p) == new.get(p) for p in GOVERNED)` 判为真，不论分支是 `main` 还是 `proof/x` 均直接退 `0`——尽管 `git diff-tree` 明确输出 `A 120000 formal_math`。这直接击中了「有没有受管路径的变化能让根节点比对看不出来」与「`BAD_TREE` 是否漏掉 `diff-tree` 结果不可信的树」。
  - **说明不实**：`README.md:47,86` 明确宣称「预检拒收重复或乱序的树条目（`BAD_TREE`）」，仅对 `/`、`.git`、`..` 等「其它 fsck 级畸形对象」做了免责声明；实际对 `git fsck` 判为 `duplicateEntries` 的同名异类重复条目既不报 `BAD_TREE`，反而判绿退 `0`。

- **逐字复现命令**：
  ```sh
  TMPDIR=/Volumes/AgentStorage/review-2312-precheck-r1/tmp python3 -I audit-reports/2312/precheck-r1-fixtures/repro_blockers.py --case B1a
  TMPDIR=/Volumes/AgentStorage/review-2312-precheck-r1/tmp python3 -I audit-reports/2312/precheck-r1-fixtures/repro_blockers.py --case B1b
  ```
- **实际退出码与输出**（`precheck.py` 实测退出码均为 `0`）：
  ```text
  === B1a ===
    [symlink+tree] rc=0 head=fdbb5189009604fba2675630e8037e3405c848de
      stdout: PRECHECK GREEN OK fdbb5189009604fba2675630e8037e3405c848de role=proof
      extra:  :000000 120000 0000000000000000000000000000000000000000 3594e94c04db171e2767224db355f514b13715c5 A	formal_math/Chan/Thm/Sub
  :000000 100644 0000000000000000000000000000000000000000 0cca093d7af2d97bfa250fceb954297d68a6f246 A	formal_math/Chan/Thm/Sub.lean
  :000000 100644 0000000000000000000000000000000000000000 0cca093d7af2d97bfa250fceb954297d68a6f246 A	formal_math/Chan/Thm/Sub/E.lean
    [exec+tree] rc=0 head=cc780b324b7a5f7a5183afd7acbdd6e978dab0be
      stdout: PRECHECK GREEN OK cc780b324b7a5f7a5183afd7acbdd6e978dab0be role=proof
    [gitlink+tree] rc=0 head=8bb51d81ae91afa212229a6cab78352db506740e
      stdout: PRECHECK GREEN OK 8bb51d81ae91afa212229a6cab78352db506740e role=proof
    [non-lean-blob+tree] rc=0 head=65b8ff208da98e887095ae45e358392edea9ce76
      stdout: PRECHECK GREEN OK 65b8ff208da98e887095ae45e358392edea9ce76 role=proof
  === B1b ===
    [main] rc=0 head=934b82716819c8bad411a638eaea0ae10841e082
      stdout: PRECHECK GREEN OK 934b82716819c8bad411a638eaea0ae10841e082 role=-
      extra:  :000000 120000 0000000000000000000000000000000000000000 3594e94c04db171e2767224db355f514b13715c5 A	formal_math
  :100644 100644 4286f428e3b19fe84de503916ce0e7dc8deefea1 53c74cd6c8f3911ae716f60f9b79f575aab0e975 M	rust/lib.rs
    [proof/x] rc=0 head=934b82716819c8bad411a638eaea0ae10841e082
      stdout: PRECHECK GREEN OK 934b82716819c8bad411a638eaea0ae10841e082 role=proof
  ```
  （同手法在 `formal_math/verification/` 下放 `(120000, Sub)` + `(040000, Sub)`，`infra/x --trusted-change-approved` 实测同样退 `0`：`PRECHECK GREEN OK 9012e2b7d48bdc4bb51925a179eaf0a62b3ffb94 role=infra`。）

---

### B2：`formal_math` 自身为空树时逃逸 `EMPTY_TREE`，在角色分支下退 0

- **所属类别**：**1. 误绿**
- **位置与根因**：`formal_math/verification/precheck/precheck.py:106-118`
  ```python
  root = tree.get(FM_ROOT)
  if root and root[0] != b"040000":
      red("MODE", FM_ROOT, "formal_math 必须是目录，实为 %s" % root[0].decode())
  entries = [(path[len(FM):], mode, kind) for path, (mode, kind, _) in tree.items() if path.startswith(FM)]
  ```
  `shape()` 只对 `entries`（即 `formal_math/` 严格后代）检查 `kind == TREE and rel not in parents`，未检查 `formal_math` 根节点本身是否为空树（`040000 tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904`）。同时 `git diff-tree -r` 对空树无任何输出。
  - **B2a**：基线无 `formal_math/`（与当前 `origin/main` 一致），被审提交新增空树 `formal_math`，`proof/x` 或未放行的 `infra/x` 均退 `0`。
  - **B2b**：基线仅有 `formal_math/README.md`，未放行的 `infra/x` 删除该文件后保留空树 `formal_math`，退 `0`。
  - 两例均通过 `git fsck --strict --full`（退出码 `0`，零错误零警告），属于完全合规的 git 对象，不涉任何 fsck 畸形前提。

- **逐字复现命令**：
  ```sh
  TMPDIR=/Volumes/AgentStorage/review-2312-precheck-r1/tmp python3 -I audit-reports/2312/precheck-r1-fixtures/repro_blockers.py --case B2
  ```
- **实际退出码与输出**（`precheck.py` 实测退出码均为 `0`）：
  ```text
  === B2 ===
    [B2a-proof] rc=0 head=4a96c6d64e5e48cd6d839217806d2d1f66433353
      stdout: PRECHECK GREEN OK 4a96c6d64e5e48cd6d839217806d2d1f66433353 role=proof
      extra:  fsck_rc=0
    [B2a-infra-unapproved] rc=0 head=4a96c6d64e5e48cd6d839217806d2d1f66433353
      stdout: PRECHECK GREEN OK 4a96c6d64e5e48cd6d839217806d2d1f66433353 role=infra
      extra:  fsck_rc=0
    [B2b-infra-unapproved] rc=0 head=c989ac109d0afb4a941a7abe69cea06268311a83
      stdout: PRECHECK GREEN OK c989ac109d0afb4a941a7abe69cea06268311a83 role=infra
      extra:  fsck_rc=0
  ```

---

### B3：`TRUST_UNAPPROVED` 与 `PATH_SCOPE` 仅依赖对空子树和非规范模式盲视的 `diff-tree -r`，导致未放行 `infra` 改门禁树对象、内容角色改别的角色目录树对象均退 0

- **所属类别**：**1. 误绿**
- **位置与根因**：`formal_math/verification/precheck/precheck.py:147-151` 对比 `157-159`
  - `git diff-tree -r` 只比较叶节点（blob / gitlink），对**空子树的删除**以及 git `canon_mode()` 规范化后等价的模式变动（如 `100644` -> `100664`）输出完全为空，即便所在目录的 git 树对象 OID 已切实改变。
  - 第 7 步 `TRUSTED_DRIFT`（第 157–159 行）对 `TRUSTED` 逐项比对 `old.get(path) != new.get(path)`（含整棵 `formal_math/verification` 树对象），但第 4 步 `PATH_SCOPE` 与第 5 步 `TRUST_UNAPPROVED`（第 147–151 行）只检查 `diff`，导致三类误绿：
    - **B3a（`git fsck --strict --full` 退 0 零警）**：基线 `formal_math/verification/` 下含空子树 `Empty`，被审提交将其删除，使受信目录 `formal_math/verification` 的树对象 OID 发生改变；在未给 `--trusted-change-approved` 的 `infra/x` 分支下，`diff` 为空跳过 `TRUST_UNAPPROVED`，`role == b"infra"` 跳过第 7 步，预检退 `0`（对照：同样提交在 `proof/x` 下会被 `TRUSTED_DRIFT` 判红退 `1`）。
    - **B3b（`git fsck --strict --full` 退 0 零警）**：基线 `formal_math/Chan/Defs/`（`decl` 辖区）含空子树 `Empty`，`proof/x` 将其删除，改动了角色表之外的 `Chan/Defs/` 树对象，却因 `diff` 为空跳过 `PATH_SCOPE` 而退 `0`。
    - **B3c（`git fsck --strict --full` 仅警告 `badFilemode`、退 0）**：`formal_math/verification/run_gates.py` 模式由 `100644` 改为 `100664`，改变了 `formal_math/verification` 树对象 OID，因 `diff-tree` 规范化模式输出为空，未放行 `infra/x` 退 `0`（对照：`proof/x` 会被 `TRUSTED_DRIFT` 判红退 `1`）。

- **逐字复现命令**：
  ```sh
  TMPDIR=/Volumes/AgentStorage/review-2312-precheck-r1/tmp python3 -I audit-reports/2312/precheck-r1-fixtures/repro_blockers.py --case B3
  ```
- **实际退出码与输出**（`precheck.py` 实测退出码均为 `0`）：
  ```text
  === B3 ===
    [B3a-infra-no-approve-del-verif-empty] rc=0 head=0d64ae2c6fdbaafc6cf18e86c7f7fe85bfbba4aa
      stdout: PRECHECK GREEN OK 0d64ae2c6fdbaafc6cf18e86c7f7fe85bfbba4aa role=infra
      extra:  fsck_rc=0
    [B3b-proof-del-decl-defs-empty] rc=0 head=479ff3c9b72558baba7f6244d08a451030e4bffe
      stdout: PRECHECK GREEN OK 479ff3c9b72558baba7f6244d08a451030e4bffe role=proof
      extra:  fsck_rc=0
    [B3c-infra-no-approve-verif-100664] rc=0 head=7ce2b769679ea562e39cba2cc0ef30af4a2b4910
      stdout: PRECHECK GREEN OK 7ce2b769679ea562e39cba2cc0ef30af4a2b4910 role=infra
      extra:  verif_oid_changed=True
  ```

---

### B4：`formal_math/` 子目录下的 `lakefile.lean` 退 0，未兑现「任何位置的 `lakefile.lean`」判红口径

- **所属类别**：**1. 误绿**
- **位置与根因**：`formal_math/verification/precheck/precheck.py:38,125-132`
  - 顶层 `formal_math/lakefile.lean` 确被 `TOP` 判 `TOP_LEVEL` 红；
  - 但在内容根（如 `formal_math/Chan/Thm/lakefile.lean`）下，模块名文法 `MODULE = [A-Za-z][A-Za-z0-9_]*` 接受小写 `lakefile`，因此 `proof/x` 放入 `formal_math/Chan/Thm/lakefile.lean` 退 `0`；
  - 在非内容根 `sources/`、`blueprint/`、`verification/` 下不限制文件名，因此 `decl/x` 放入 `formal_math/sources/lakefile.lean` 或 `formal_math/blueprint/lakefile.lean`、`infra/x --trusted-change-approved` 放入 `formal_math/verification/lakefile.lean` 均退 `0`。
  - **口径溯源**：设计备忘 `3.3`（`2312-design-consult.md:123`）写道「内容根下只许模块名合法的 `.lean` 文件，`lakefile.lean`、隐藏目录、`.gitattributes` 因此都进不来」，忽略了 `lakefile` 本身合法且 `sources/`/`blueprint/` 不走内容根校验；`README.md:43,69` 随后将其收窄为仅禁顶层 `formal_math/lakefile.lean`，但这直接违背本次审阅的对抗阻断口径「任何位置的 `lakefile.lean`」。经查当前仓库 `formal_math/` 全树不含任何 `lakefile.lean`（`verification/` 夹具中均为 `lakefile.toml`），在 `shape()` 中按段名 `lakefile.lean` 全域禁入无任何误红代价。

- **逐字复现命令**：
  ```sh
  TMPDIR=/Volumes/AgentStorage/review-2312-precheck-r1/tmp python3 -I audit-reports/2312/precheck-r1-fixtures/repro_blockers.py --case B4
  ```
- **实际退出码与输出**（`precheck.py` 实测退出码均为 `0`）：
  ```text
  === B4 ===
    [Chan/Thm/lakefile.lean] rc=0 head=24f790f5b75786ca5aa7e48a66b4e49c1321a828
      stdout: PRECHECK GREEN OK 24f790f5b75786ca5aa7e48a66b4e49c1321a828 role=proof
    [sources/lakefile.lean] rc=0 head=467096c418221f451c8154da6cbc318c17bad830
      stdout: PRECHECK GREEN OK 467096c418221f451c8154da6cbc318c17bad830 role=decl
  ```
  （另已实测 `formal_math/blueprint/sub/lakefile.lean` 在 `decl/x` 下退 `0`，`formal_math/verification/lakefile.lean` 在放行 `infra/x` 下退 `0`。）

---

### B5：`README.md`「与现有 `run_gates.py` 门 6b 角色表的出入」一节漏列实际存在的出入

- **所属类别**：**4. 说明不实**
- **位置与对照**：`formal_math/verification/precheck/README.md:90-110` 对照 `594e49b5ec` 的 `formal_math/verification/run_gates.py:504-582`
  1. **有角色分支仅改受管外路径从红变绿（漏列）**：旧 `gate6b`（`run_gates.py:569-581`）对任何带角色前缀的分支（如 `proof/x`）逐条校验全仓变动，因此 `proof/x` 只改 `rust/lib.rs` 必判 `PATH_SCOPE` 红；新 `precheck.py:142-143` 因三项受管对象均未变动而直接退 `0`。`README.md:108` 仅写了「无角色分支：一律红 → 只在碰了受管路径时红」，漏列了有角色分支的同类反转。
  2. **分支名来源与分离 HEAD 语义变化（漏列）**：旧 `gate6b`（`run_gates.py:545-550`）读取 `git symbolic-ref HEAD` 与 `GITHUB_HEAD_REF` 环境变量（分离 HEAD 缺变量退 `2`）；新 `precheck.py` 不读仓库 `HEAD` 也不读环境变量，改为由第 4 命令行参数显式传入（且未碰受管路径时允许传空串 `""` 退 `0`）。`README.md:103`「分支名」一行仅列了文法变化。
  3. **`infra` 对已有 `verification/garbage-signoffs.yaml` 的写权由禁变许（未写清）**：旧 `gate6b`（`run_gates.py:575-578`）禁止 `infra` 修改基线已存在的 `formal_math/verification/garbage-signoffs.yaml`（仅基线缺失时允许初始化为空 `{}`）；新 `precheck.py:27` 删去该条件后，`infra` 获放行即可任意改删已存在的该文件。`README.md:100` 仅写「不给任何内容角色开门禁目录的口子；特例删去」，未指出 `infra` 侧对已有签注文件的权限同步放宽。

- **逐字复现命令**（验证第 1 项新预检退 `0`）：
  ```sh
  TMPDIR=/Volumes/AgentStorage/review-2312-precheck-r1/tmp python3 -I audit-reports/2312/precheck-r1-fixtures/repro_blockers.py --case B5
  ```
- **实际退出码与输出**：
  ```text
  === B5 ===
    [proof/x only rust/lib.rs] rc=0 head=983c3361ab4b7c88eeb0d46524e7a989299aa40b
      stdout: PRECHECK GREEN OK 983c3361ab4b7c88eeb0d46524e7a989299aa40b role=proof
  ```

---

## 二、非阻断建议

1. **补齐 `selftest.py` 弱化自测暴露的 4 处覆盖缺口**：
   我们使用独立脚本 `audit-reports/2312/precheck-r1-fixtures/run_custom_mutants.py` 对 `precheck.py` 做了 8 种不同于作者内置 5 种的弱化，结果如下（4 项被抓住，4 项未变红逃逸）：

   | 编号 | 弱化内容 | `selftest.py` 失败数 | 结果 |
   |---|---|---|---|
   | M1 | 去掉大小写冲突判断（`if twin != rel:` → `if False:`） | 1/110 | 抓住（KILLED） |
   | M2 | 第 7 步 `TRUSTED` 去掉 `formal_math/lean-toolchain` | 0/110 | **逃逸（SURVIVED）** |
   | M3 | 祖先检查 `merge-base --is-ancestor` 改成恒真 | 2/110 | 抓住（KILLED） |
   | M4 | 分支名文法放宽（允许 `..` 与首尾分隔符） | 3/110 | 抓住（KILLED） |
   | M5 | 去掉 `diff-tree` 的 `--no-renames` | 0/110 | **逃逸（SURVIVED）** |
   | M6 | 受信文件模式检查（`GOVERNED[1:]`）漏掉 `.github/workflows/formal-math.yml` | 0/110 | **逃逸（SURVIVED）** |
   | M7 | 放行开关在非 `infra` 角色下跳过 `TRUSTED_DRIFT` | 0/110 | **逃逸（SURVIVED）** |
   | M8 | 去掉空子树检查（`EMPTY_TREE`） | 2/110 | 抓住（KILLED） |

   （复现命令：`TMPDIR=/Volumes/AgentStorage/review-2312-precheck-r1/tmp python3 -I audit-reports/2312/precheck-r1-fixtures/run_custom_mutants.py`）
   建议在 `selftest.py` 中补充对应红例：
   - 内容角色（如 `proof/x`）改/删 `formal_math/lean-toolchain`（覆盖第 7 步全部 6 项受信对象）；
   - 在测试仓 `.git/config` 写入 `diff.renames = copies` 后测试跨角色重命名（须判 `PATH_SCOPE` 红）与合法同角色复制（须判绿，不触发 `GIT` 解析错误）；
   - `.github/workflows/formal-math.yml` 设为 `100755` / `120000` / 目录的 `MODE` 测例；
   - 内容角色（如 `proof/x`）带 `--trusted-change-approved` 改受信文件仍判 `PATH_SCOPE` + `TRUSTED_DRIFT` 红的测例（验证 `README.md:16`）。
2. **修正 `selftest.py` 注释与断言粒度**：
   - `selftest.py:5` 文档注释写「断言四种弱化」，实际 `MUTANTS` 有五种（`README.md:138` 正确）；
   - `codes(stdout, stderr)`（`selftest.py:207-208`）将标准输出与标准错误拼接后统一匹配，且 `LINE` 未锚定行首，无法区分 `RED` 写错到 stderr 或 `FAULT` 写错到 stdout；建议分别校验 stdout 的 `RED` 与 stderr 的 `FAULT`。
3. **非规范 git 模式（`100664`、`100600`、`100655`、`040755`）的 git 规范化特性**：
   实测 `git ls-tree` 与 `git diff-tree` 均通过 git 内部 `canon_mode()` 将 `100664`/`100600`/`100655`/`100645` 规范化输出为 `100644`，将 `040755`/`040777` 规范化输出为 `040000`（且 `git fsck --strict` 对 `badFilemode` 仅报 warning、仍退 `0`）。除已列为 B3c 的门禁目录树 OID 漂移外，单文件如 `formal_math/Chan/Thm/B.lean` 或 `formal_math/lakefile.toml` 改为 `100664` 时，`precheck.py` 同样退 `0`（git 检出时也按 `100644` 处理）。若团队希望连非规范模式位也拒收，需在「不防什么」写明依赖 `fsck`，或直接解析原始树对象字节。
4. **`sources/` 与 `blueprint/` 下的构建文件名与尾点文件名**：
   除 B4 的 `lakefile.lean` 外，`decl/x` 目前可在 `sources/` 与 `blueprint/` 下放入 `lakefile.toml`、`lake-manifest.json` 及带尾点的名字（如 `sources/foo.`，符合 `[A-Za-z0-9_][A-Za-z0-9_.-]*`）。建议评估是否在 `sources/`/`blueprint/` 中同步禁掉尾点/双点以及 `lakefile.toml`/`lake-manifest.json` 同名文件（保留 `verification/` 内现有 `lakefile.toml` 测试夹具）。
5. **`tree_at()` 对尾部 NUL 的一致性校验**：
   `changes()`（`precheck.py:89`）校验了 `fields[-1] != b""`，但 `tree_at()`（`precheck.py:73`）直接用 `.split(b"\0")[:-1]`，若输出异常截断会静默丢弃末条；建议对齐 `changes()` 先检查末尾为空字节串。
6. **对 B1–B5 的最小修复参考**：
   - B1：`tree_at()` 增加 `if path in entries: raise Fault("BAD_TREE", path, "树条目重复或未按 git 顺序排列")`；
   - B2：`shape()` 增加 `if root and root[0] == b"040000" and not entries: red("EMPTY_TREE", FM_ROOT, "提交里记录了空子树")`；
   - B3：`TRUST_UNAPPROVED` 同时检查 `any(old.get(p) != new.get(p) for p in TRUSTED)`；`PATH_SCOPE` 对空子树目录节点增删（`old`/`new` 仅目录差集）同步做路径表校验；
   - B4：`shape()` 对 `formal_math/` 下所有条目增加 `if parts[-1] == b"lakefile.lean":` 判红（或与主控正式书面收窄口径）；
   - B5：补全 `README.md` 90–112 行的出入对照表。

---

## 三、核实正确的部分

1. **受审对象与基点核对**：`origin/infra/2312-e-precheck` 精确为 `a1035da72789a8f99f8b8b7c66b8f2e543823464`，相对基点 `594e49b5ec034461f9196c6cfb0c58fe017e8dc5` 仅新增 `formal_math/verification/precheck/{precheck.py,selftest.py,README.md}` 三个文件（共 707 行，`precheck.py` 精确 200 行）。在真实仓 `594e49b5ec..a1035da727` 与 `e3336ee721..594e49b5ec` 上实跑均仅报已声明的 `formal_math/.gitignore`（`PATH_GRAMMAR`，退 `1`）；仓内 `scripts/fm_env.sh` 实测确为 `100644`。
2. **作者自测与弱化自测全量复跑（macOS）**：在正常 UTF-8 与 `LC_ALL=C` + `-X utf8=0` 两种环境下，分别运行 `selftest.py`（110/110 通过）与 `selftest.py --mutants`（未改弱 0 失败，5 种作者弱化分别有 10/5/7/6/2 例失败），全部退 `0`。抽查全部 9 种 `RED` 规则码与 `BAD_TREE` 红例的实际输出，确认触发的规则码、输出流（RED→stdout，FAULT→stderr）与中文说明均与声称一致，未见恒真断言。
3. **规则顺序、快速失败与规则码清单**：
   - 第 1 条（`BAD_REV` / `NOT_ANCESTOR`）先于第 3–7 条执行，失败即退 `2` 且不继续判定；无关根提交、兄弟提交、基线为被审后代均退 `2`（`NOT_ANCESTOR`），基线等于被审（含空根提交）退 `0`。
   - `precheck.py` 中的 9 个 `RED` 规则码（`BRANCH_ROLE`、`PATH_SCOPE`、`TRUST_UNAPPROVED`、`MODE`、`EMPTY_TREE`、`PATH_GRAMMAR`、`TOP_LEVEL`、`CONTENT_SHAPE`、`TRUSTED_DRIFT`）与 7 个 `FAULT` 码（`USAGE`、`BAD_REV`、`NOT_ANCESTOR`、`BAD_TREE`、`GIT`、`OUTPUT`、`INTERNAL`）与 `README.md` 逐一完全一致。
   - `ROLES` 除出入表已列变更外，`decl`、`proof` 其余表项与 `audit` 整张表确与 `run_gates.py:504-517` 一致；内容角色与受信面互不相交。
4. **正向无误红核验（`run_edge_probes.py` 26/26 通过）**：
   - `decl`、`proof`、`audit`、`infra`（放行）各自修改其路径表全部条目均退 `0`；`infra` 无放行仅改 `formal_math/README.md` 退 `0`；
   - 深层目录、200 字符合法模块名、小写首字母合法模块名（`a.lean`）、`Chan.lean` 与 `Chan/` 并存、`Chan/Final.lean` 与 `Chan/Final/` 并存、`ChanExplore.lean` 与 `ChanExplore/` 并存均退 `0`；
   - 裸仓、仓库子目录、SHA-256 对象格式仓库、带附注标签指向提交、短 SHA、含空格与非 ASCII 字符的仓库路径、含 160000 子模块与其 `-`/`.` 前缀兄弟文件的仓库根、仅改仓库受管外路径（含受管外换行路径、非 UTF-8 分支名、空分支名）均退 `0`。
5. **对抗与边界核验通过项**：
   - 同名前缀兄弟（`Chan/Thm2`、`ChanTestX`、`verification-x`、`scripts/fm_env.sh.bak`）、目录/文件大小写冲突（同目录文件、跨目录目录、文件与目录）、Unicode NFC/NFD、制表符/空格/换行/反斜杠/非 UTF-8 字节/首字符 `-` 或 `.`（含 `.git`、`.lake`、`.gitattributes`）、文件↔目录替换、同 blob 仅改 `120000` 符号链接或 `100755` 可执行位、合并提交夹带跨角色改动、基线缺失时新增 `scripts/fm_env.sh` 或 `.github/workflows/formal-math.yml`、非 `infra` 角色带放行开关改受信文件、分支名畸形（空段、`..`、双连字符、首尾分隔符、非 ASCII、`refs/heads/` 前缀）、5000 字符超长分支名（无 ReDoS）、树条目同类型重复与逆序（含 `tree` 在 `blob` 前），均按预期判红（退 `1`）或退 `2`。
   - 实测仓库级配置 `diff.renames=copies` 下跨角色重命名仍判 `PATH_SCOPE` 红、合法复制仍退 `0`；`git replace` 与 `.git/info/grafts` 均被环境变量成功屏蔽。
6. **命令行参数、退出码与输出环境契约**：
   - 22 项畸形参数组合（缺参、多参、缩写、带值、重复、后置、`--`、`--help`、空串、`-` 开头等）全部退 `2`（`USAGE`），无任何组合未做判定即退 `0`；
   - 无效/树对象/blob 对象/带范围语法/含换行 rev、浅克隆缺基线、缺失树对象、空 `PATH` 均退 `2`；
   - 绿例遇 stdout 断管或关闭退 `2`（`OUTPUT`）；红例遇 stdout 断管仍退 `1`；绿/红/故障三类在 stderr 关闭或断管下退出码均保持不变（0/1/2），且无任何未捕获回溯；
   - 本机 `git version 2.50.1 (Apple Git-155)` 实测支持 `rev-parse --verify --quiet --end-of-options`，传入 `--all^{commit}` 正确退 `1`（由预检转为 `BAD_REV` 退 `2`）。

---

## 四、没覆盖的部分

1. **非 UTF-8 真实磁盘仓库路径**：macOS APFS 文件系统拒绝创建非 UTF-8 目录名，未能在本地测得「真实存在的非 UTF-8 路径仓库」判绿情形（仅测了不存在路径退 `2` 及非 UTF-8 分支名/树内路径）。
2. **低版本 git 行为**：本机为 `git 2.50.1`，未在低于 2.24（不支持 `rev-parse --end-of-options`）的旧版 git 上实测退 `2` 路径。
3. **`safe.directory` 跨用户所有权拒绝**：未在跨 UID 所有权仓库上实测 git 拒绝打开时退 `2`。
4. **GitHub 服务端推送侧 fsck 策略**：`README.md:86` 标注「未核实 GitHub 对 PR 推送是否全量 fsck」，本次只读审阅未向远端推送畸形树对象以核验 GitHub 服务端是否拦截 B1 的 `duplicateEntries` 或 B3c 的 `badFilemode`（注：B2、B3a、B3b 与 B4 均通过本地 `git fsck --strict --full` 退 `0` 零警告，不依赖服务端 fsck 是否放行）。
5. **Windows 平台行为**：未在 Windows 下测路径/文件描述符行为（本项目 CI 与开发面为 Linux / macOS）。

---

VERDICT: BLOCK — 范围：#2312 第一片纯静态预检（`formal_math/verification/precheck/{precheck.py,selftest.py,README.md}` @ `a1035da72789a8f99f8b8b7c66b8f2e543823464`）
