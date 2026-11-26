# #2312 第一片（纯静态预检）独立审阅报告 R2

- **被审分支与提交**：`origin/infra/2312-e-precheck` @ `5b6cc3ea1691077835ec02c5614720285b3b687b`（上一轮被审提交 `a1035da72789a8f99f8b8b7c66b8f2e543823464`，基点 `594e49b5ec034461f9196c6cfb0c58fe017e8dc5`）
- **受审范围**：仅 `formal_math/verification/precheck/` 下三个文件（`precheck.py` 249 行、`selftest.py` 536 行、`README.md` 167 行，合计 952 行；其余旧门禁代码不在范围）
- **审阅模型与档位**：Gemini 4 Neon (XHigh)（非作者独立复审，只读审阅，未改被审分支、未评论或修改任何 issue、未开 PR、未起子代理）
- **审阅环境**：macOS，`git version 2.50.1 (Apple Git-155)`，`Python 3.14.6`（临时文件、克隆与工作树均位于 `/Volumes/AgentStorage`）
- **设计依据**：`origin/evidence/2312-design-consult` @ `aedff2e010e639df3ff411b9d674b5bf62c3440c`（备忘 3.1、3.3、3.7 节与第六节第三处）；#2312 评论 `7175991382`、`7177053075`；上一轮报告 `origin/evidence/2312-precheck-review` @ `05c55cc941642549fce9abe4e55a55c4a03df6e0`
- **复现与核验夹具**：同分支 `audit-reports/2312/precheck-r2-fixtures/`（`repro_r2_blockers.py`、`verify_r1_closures.py`、`run_r2_probes.py`、`run_r2_mutants.py`）

---

## 一、上一轮五条阻断（R1 B1–B5）复验

逐字复现命令（在以 `5b6cc3ea1691077835ec02c5614720285b3b687b` 为基点的本分支工作树根目录执行）：

```sh
TMPDIR=/Volumes/AgentStorage/tmp python3 -I audit-reports/2312/precheck-r2-fixtures/verify_r1_closures.py
```

实测 31/31 项通过（另用上一轮 `precheck-r1-fixtures/repro_blockers.py --precheck formal_math/verification/precheck/precheck.py` 原样复跑亦全部吻合）。**上一轮 5 条阻断全部闭合**：

| 编号 | 状态 | 原样形状复验 | 本轮新增同类形状复验 |
|---|---|---|---|
| **R1-B1** | **已闭合** | B1a 四个变体（符号链接/可执行/子模块/非 `.lean` 与同名目录）全部退 `1`（均报 `TREE_FORM` + `MODE`/`CONTENT_SHAPE`）；B1b（根上 `120000 formal_math` + 原样 `40000 formal_math`）在 `main`、`proof/x` 下均退 `1`（报 `TREE_FORM` + `MODE` + `TRUSTED_DRIFT` 等）。 | 4 种新形状全退 `1`（`TREE_FORM`）：① `Chan/Thm/` 反序（`40000 Sub` 在 `120000 Sub` 之前）；② `scripts/` 内重名 `fm_env.sh`（blob+symlink，`main`）；③ `.github/workflows/` 内重名 `formal-math.yml`（blob+tree，`main`）；④ 根树重名 `scripts`（symlink+原树，`main`）。 |
| **R1-B2** | **已闭合** | B2a（基线无 `formal_math`，新增空 `formal_math`）在 `proof/x`、`infra/x` 无放行下均退 `1`（`EMPTY_TREE`）；B2b（删光留空 `formal_math`）退 `1`（`EMPTY_TREE`）。 | 2 种新形状全退 `1`（`EMPTY_TREE`）：① 仅含嵌套空目录 `formal_math/Chan/Thm` 且全树无文件（`proof/x`）；② 放行 `infra/x` 删光 `verification/` 留下空门禁目录。 |
| **R1-B3** | **已闭合** | B3a（无放行 `infra/x` 删门禁空子树）退 `1`（`TRUST_UNAPPROVED`）；B3b（`proof/x` 删 `Chan/Defs/Empty`）退 `1`（`PATH_SCOPE`）；B3c（无放行 `infra/x` 改门禁文件为 `100664`）退 `1`（`MODE` + `TRUST_UNAPPROVED`）。 | 3 种新形状全退 `1`：① 无放行 `infra/x` 改 `verification` 目录节点模式 `40000->040000`（`MODE` + `TRUST_UNAPPROVED`）；② `decl/x` 改 `lakefile.toml` 为 `100664`（`MODE` + `PATH_SCOPE` + `TRUSTED_DRIFT`）；③ 无放行 `infra/x` 新增 `verification/Empty`（`EMPTY_TREE` + `TRUST_UNAPPROVED`）。 |
| **R1-B4** | **已闭合** | `Chan/Thm/lakefile.lean`（`proof/x`）与 `sources/lakefile.lean`（`decl/x`）均退 `1`（`LAKE_FILE`）。 | 5 种新形状全退 `1`（`LAKE_FILE`）：① `Chan/Defs/Lakefile.Lean`（混合大小写，`decl/x`）；② `Chan/Audit/Math/LAKEFILE.lean`（全大写，`audit/x`）；③ `verification/auditor/Lakefile.toml`（例外路径大小写变体，放行 `infra/x`）；④ `verification/auditor/sub/lean-toolchain`（例外路径更深层，放行 `infra/x`）；⑤ `sources/lakefile.toml/` 目录（`decl/x`）。 |
| **R1-B5** | **已闭合** | `README.md:106-133`「与现有 `run_gates.py` 门 6b 的出入」已补齐 R1 漏列的 3 处并扩写为 18 行对照表，对照 `594e49b5ec` 的 `run_gates.py:31-32,504-582` 核对无漏列；原样 `proof/x` 仅改 `rust/lib.rs` 按新设计退 `0`。 | 2 种新形状均按新设计退 `0`：① `proof/x` 同改 `Chan/Thm/B.lean` + `rust/lib.rs` + `.github/workflows/ci.yml` + `scripts/other.sh`；② 无放行 `infra/x` 同改 `formal_math/README.md` + `scripts/other.sh` + `.github/workflows/ci.yml`。 |

---

## 二、新的可复现阻断缺陷

本轮共复现 **1 条新的阻断缺陷**（同时踩中「1. 误绿」与「4. 说明不实」）。

### R2-B1：受管祖先目录（`scripts`、`.github`、`.github/workflows`）被无条件排除出改动集合且空改动跳过 `shape()`，导致模式或类型篡改在未改其它受管路径时退 0

- **所属类别**：**1. 误绿** + **4. 说明不实**
- **位置与根因**：`formal_math/verification/precheck/precheck.py:18,98,154-157,191-194`
  ```python
  ANCESTORS = {p[:i] for p in OUTSIDE for i in range(len(p)) if p[i:i + 1] == b"/"}
  ...
  def managed(path):
      return path == FM_ROOT or path.startswith(FM) or path in OUTSIDE or path in ANCESTORS
  ...
  # 第 3 条：改动集合是两份清单的集合差；仓库根下受信文件的祖先目录只核对形状，不算改动。
  changed = sorted(p for p in set(old) | set(new) if p not in ANCESTORS and old.get(p) != new.get(p))
  if not changed:
      return head, role
  ```
  `scripts`、`.github`、`.github/workflows` 明确在受管范围（`README.md:34`、`managed()`）且受 `MODE` 规则约束（`README.md:51`：「它们的祖先目录不是 `40000`」）。但第 192 行将 `p in ANCESTORS` **整条无条件剔除**，把「无关文件导致的 `40000` 树对象 OID 漂移」与「祖先目录自身的原始模式/类型篡改」混为一谈，紧接着第 193–194 行因 `changed` 为空提前返回，**完全跳过第 204 行的 `shape(new, red)`**。由此直接产生两类可复现误绿：
  - **R2-B1a（即使基线与被审提交完整存在 `scripts/fm_env.sh` 与 `.github/workflows/formal-math.yml` 仍可触发）**：将 `scripts`、`.github` 或 `.github/workflows` 的原始模式从 `40000` 改为 `040000`（带前导零）或 `40755`（非规范目录位），树对象 OID 与其下受信文件不变。由于 `is_tree(b"040000")` 与 `is_tree(b"40755")` 均为真，`inventory()` 照常下探并读出与基线一致的受信文件，`changed` 为空跳过 `shape()`，在 `main`、`proof/x`、无放行 `infra/x` 下全部退 `0`。作为对照，同一提交只要顺带改一处合法 `formal_math/Chan/Thm/B.lean`，立即因 `changed` 非空进入 `shape()` 而判 `MODE` 红（退 `1`）。在真实被审提交 `5b6cc3ea16` 的共享克隆上将 `scripts`（内含真实 `scripts/fm_env.sh`）由 `40000` 改为 `040000`，`proof/x` 实测同样退 `0`（`PRECHECK GREEN OK cc12cd8334f06a1f79448089ef81ff3228e415c6 role=proof`）。
  - **R2-B1b（`git fsck --strict --full` 退 `0` 零错零警，直接命中当前 `origin/main` 与 `5b6cc3ea16` 的真实状态）**：当前 `origin/main` 不含 `scripts/fm_env.sh` 与 `.github/workflows/formal-math.yml`，当前被审提交 `5b6cc3ea16` 亦不含 `.github/workflows/formal-math.yml`。在此状态下，将 `.github/workflows`、`.github` 或 `scripts` 替换为 `120000` 符号链接、`100644` 普通文件或 `160000` 子模块（100% 合法 git 对象，`git fsck --strict --full` 退 `0` 零错零警），因无子受信文件条目消失、`ANCESTORS` 被过滤，`changed` 为空跳过 `shape()`，在 `main`、`proof/x`、无放行 `infra/x` 下全部退 `0`（在真实被审提交 `5b6cc3ea16` 共享克隆上将 `.github/workflows` 改为 `120000` 符号链接，`proof/x` 实测退 `0`：`PRECHECK GREEN OK 263884e210c2174130ed004535126e3520c4997a role=proof`）。进一步，该提交合入成新基线后，**后续所有完全合法的 `formal_math/` PR（只要改了受管路径）全部被 `MODE .github/workflows 原始模式为 120000` 阻断**，形成二段投毒。
  - **说明不实**：`README.md:37` 宣称「仓库根下受信文件的三个祖先目录只核对形状，不算改动：它们的对象名会随无关文件变化」，`README.md:51` 宣称 `MODE` 拦截「它们的祖先目录不是 `40000`」；实际上只要 `changed` 为空，三个祖先目录的形状完全不核对。

- **逐字复现命令**：
  ```sh
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I audit-reports/2312/precheck-r2-fixtures/repro_r2_blockers.py --case R2-B1a
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I audit-reports/2312/precheck-r2-fixtures/repro_r2_blockers.py --case R2-B1b
  ```
- **实际退出码与输出**（`precheck.py` 实测误绿退出码均为 `0`）：
  ```text
  === R2-B1a ===
    [scripts 40000->040000 (main)] rc=0 head=a4ed26a36875ef4ad221a56e53f7615101212d07
      stdout: PRECHECK GREEN OK a4ed26a36875ef4ad221a56e53f7615101212d07 role=-
      extra:  scripts/fm_env.sh 存在且未变
    [scripts 40000->040000 (proof/x)] rc=0 head=a4ed26a36875ef4ad221a56e53f7615101212d07
      stdout: PRECHECK GREEN OK a4ed26a36875ef4ad221a56e53f7615101212d07 role=proof
      extra:  scripts/fm_env.sh 存在且未变
    [scripts 40000->040000 (infra/x)] rc=0 head=a4ed26a36875ef4ad221a56e53f7615101212d07
      stdout: PRECHECK GREEN OK a4ed26a36875ef4ad221a56e53f7615101212d07 role=infra
      extra:  scripts/fm_env.sh 存在且未变
    [scripts 40000->40755 (proof/x)] rc=0 head=bd819f30e14ed0c9e5ceba425bd1ce514b03f25f
      stdout: PRECHECK GREEN OK bd819f30e14ed0c9e5ceba425bd1ce514b03f25f role=proof
      extra:  scripts/fm_env.sh 存在且未变
    [.github 40000->040000 (proof/x)] rc=0 head=956846de17343b07051dbbe55c62b20b54767da4
      stdout: PRECHECK GREEN OK 956846de17343b07051dbbe55c62b20b54767da4 role=proof
      extra:  formal-math.yml 存在且未变
    [.github/workflows 40000->040000 (proof/x)] rc=0 head=58b990a60e915af58551abe0ada44173342671bd
      stdout: PRECHECK GREEN OK 58b990a60e915af58551abe0ada44173342671bd role=proof
      extra:  formal-math.yml 存在且未变
    [对照：scripts 40000->040000 + 合法 Thm 改动 (proof/x)] rc=1 head=48589c39f449834a45a289fe87573b93756d30ee
      stdout: PRECHECK RED MODE scripts 原始模式为 040000，只许 100644 文件与 40000 目录
      extra:  changed 非空则判 MODE 红
  === R2-B1b ===
    [.github/workflows dir->120000 symlink (main)] rc=0 head=8991e7b8ba88447f9f593cb06edc3f455ff1d163
      stdout: PRECHECK GREEN OK 8991e7b8ba88447f9f593cb06edc3f455ff1d163 role=-
      extra:  fsck_rc=0
    [.github/workflows dir->120000 symlink (proof/x)] rc=0 head=8991e7b8ba88447f9f593cb06edc3f455ff1d163
      stdout: PRECHECK GREEN OK 8991e7b8ba88447f9f593cb06edc3f455ff1d163 role=proof
      extra:  fsck_rc=0
    [.github/workflows dir->120000 symlink (infra/x)] rc=0 head=8991e7b8ba88447f9f593cb06edc3f455ff1d163
      stdout: PRECHECK GREEN OK 8991e7b8ba88447f9f593cb06edc3f455ff1d163 role=infra
      extra:  fsck_rc=0
    [scripts dir->120000 symlink (proof/x)] rc=0 head=7601b09e653833c3c60a42347382854008c7734d
      stdout: PRECHECK GREEN OK 7601b09e653833c3c60a42347382854008c7734d role=proof
      extra:  fsck_rc=0
    [scripts dir->100644 file (proof/x)] rc=0 head=27127fd797858308086cc1a791f4e28f754755f5
      stdout: PRECHECK GREEN OK 27127fd797858308086cc1a791f4e28f754755f5 role=proof
      extra:  fsck_rc=0
    [scripts dir->160000 gitlink (proof/x)] rc=0 head=82114f6edc535c02f69a29fd66cf5d09dbf548f0
      stdout: PRECHECK GREEN OK 82114f6edc535c02f69a29fd66cf5d09dbf548f0 role=proof
      extra:  fsck_rc=0
    [后续无辜 proof/x PR（仅改 Chan/Thm/B.lean）] rc=1 head=4f52f19181d122506a6ef56abeb9abafd357e478
      stdout: PRECHECK RED MODE .github/workflows 原始模式为 120000，只许 100644 文件与 40000 目录
      extra:  被前一步合入的符号链接阻断
  ```

### 对「单一视图」做法的架构定性判断

**R2-B1 是实现上的遗漏，不是「单一视图」做法本身的问题。**

本轮改用原始树对象单视图后，第 1 轮的三视图分歧已从根上消除：`old` 与 `new` 两份清单已经完整、忠实地记录了受管范围内（含 `ANCESTORS`）每一项的原始模式字节与对象名。实测与穷举分析（按 `changed` 空/非空拆解）表明，在 `changed` 非空路径上未发现新的对抗绕过；R2-B1 仅源于第 192 行构造集合差时过度排除了 `ANCESTORS`——在过滤无关文件引起的 `40000` 树 OID 变化时，顺手过滤掉了 `ANCESTORS` 的**模式/类型变化**并跳过了 `shape()`。

最小修复不需改动单一视图架构，有两种等价且简洁的改法（2–4 行）：
- **方式 A（保持 `README.md:37`「祖先目录只核对形状，不算改动」原口径与 `selftest.py:246` 期望码集合不变）**：在 `if not changed:` 之前，对 `ANCESTORS` 中在 `new` 里出现且 `mode != TREE_MODE`（且 `old.get(p) != new.get(p)`，放过基线固有形状问题）的项直接报 `MODE` 红（在临时副本实测中，方式 A 使 `R2-B1a`/`R2-B1b` 全部转退 `1`，同时在现有 `selftest.py` 170/170、`verify_r1_closures.py` 31/31 与 `run_r2_probes.py` 43/43 上 0 失败）。
- **方式 B（同时对祖先目录的非 `40000` 变更施加角色/分支校验）**：仅当 `old.get(p)` 与 `new.get(p)` 均为 `None` 或 `TREE_MODE` 时才将 `p in ANCESTORS` 排除出 `changed`（在临时副本实测中，方式 B 使 `R2-B1a`/`R2-B1b` 全部转退 `1`，`verify_r1_closures.py` 31/31 与 `run_r2_probes.py` 42/42 全过，仅需同步将 `selftest.py:246` 的期望集合更新为 `{"MODE", "PATH_SCOPE"}` 并微调 `README.md:37`）。

---

## 三、两项专项交接与边界评估

### 3.1 「受管范围之外不管」后的逃逸面与责任归属

1. **仓库根的 `lakefile.toml`、`lakefile.lean`、`lake-manifest.json`、`lean-toolchain`、`.lake/`**：有角色或无角色分支在仓库根添加这些文件，本片退 `0`。**不属于本片误绿，归第二片（取料片）与 #2315**——按设计（备忘 3.3 第 8 条），取料片必须按 git 对象把 `formal_math/` 与基线配置写出到仓库检出之外的独立临时工作区，绝不在 PR 仓库根检出内直接调用 `lake`/`lean`，否则 `elan` 向上搜寻 `lean-toolchain` 或根上配置可能干扰构建。
2. **`.github/workflows/` 下其它文件（如 `ci.yml`、新增 `evil.yml`）与 `.github/actions/`**：已核 `5b6cc3ea16` 的 `.github/workflows/`，尚无 `formal-math.yml`，且现有 13 个工作流均不引用 `formal_math` 或 `fm_env.sh`。PR 若新增恶意工作流伪造同名必需检查，或在 `formal-math.yml` 引用 PR 树下 `./.github/actions/`，**归 #2315 负责**（必需检查须由主干工作流或宿主侧产生，且 `formal-math.yml` 不可执行 PR 树内任何脚本/本地 action），`README.md:89,100` 已如实划界。
3. **`scripts/` 下其它文件、`.gitattributes`、`.gitmodules`、根上大小写变体 `FORMAL_MATH/`**：已逐行核查 `scripts/fm_env.sh`（52 行），仅调用 shell 内建与系统命令，不 `source`/执行 `scripts/` 下任何其它文件；`.gitattributes`（如 `export-ignore`）与 macOS 上 `FORMAL_MATH/` 合流**归第二片（取料片）负责**（按对象提取，不经 `git archive` / `git checkout`），`README.md:100-101` 已如实说明。
4. **唯一落在第一片责任内的受管边界缺口**：即上述 **R2-B1**（`scripts`、`.github`、`.github/workflows` 本身已在受管范围与 `MODE` 承诺内）。

### 3.2 `README.md:99`「文件模式不查目标是否为 blob，由取料片失败来接」的交接评估

我们在 `git 2.50.1` 上构造了 `100644` 条目指向 `tree` 与 `commit` 对象的提交并实测各 git 命令：
- `git ls-tree -r` 仍伪报为 `100644 blob`（退出 `0`）；
- `git cat-file -p <oid>` 与 `git show <commit>:<path>` **退出 `0`** 并输出树列表/提交元信息文本；
- `git checkout <commit>` 报错但**仍退出 `0`** 并跳过该文件；
- 只有 `git cat-file blob <oid>` 退出 `128`（`bad file`）、`git cat-file --batch` 返回真实非 `blob` 类型、`git fsck --strict` 退出 `3`。

**评估结论：对抗断言层面总体接得住（不构成本片阻断），但存在两条必须落到第二片（取料片）或文档里的硬前提**：
1. 取料片按对象读取文件时，**必须**用 `git cat-file blob <oid>` 或 `git cat-file --batch` 并显式断言对象类型为 `blob`，禁止使用 `git show`、`git cat-file -p`、`git checkout` 或 `git archive`；
2. 对取料片实际读取的文件（`.lean`、`statement-lock.json`、`formalization.yaml`、`garbage-signoffs.yaml` 及受信文件——且内容角色无法改受信文件 OID），上述方式能可靠拦截；但对非代码文档路径（`sources/`、`blueprint/`、`HISTORY.md`、`README.md`），实测 `decl/x` 写入 `100644 sources/evil.md -> <tree_oid>` 预检退 `0`（见 `run_r2_probes.py`），若取料片不物化这些文档文件，则 `README.md:99`「指错了，后续按对象取料时会失败」的字面说法对这类文件不会触发（虽不涉及 Lean 构建与受信文件，不会破坏对抗断言，但会使该仓库路径无法正常 `git checkout` 且推送到开启严格 `fsck` 的远端会被拒）。建议见下节第 3 条。

---

## 四、非阻断建议

1. **补齐独立弱化自测暴露的 `selftest.py` 覆盖缺口**：
   我们使用独立脚本 `audit-reports/2312/precheck-r2-fixtures/run_r2_mutants.py` 对 `precheck.py` 做了 **10 种区别于作者内置 15 种的弱化**（聚焦原始树解析与集合差，先验未改弱副本 `0/170` 失败），结果如下（7 项被抓住，3 项逃逸）：

   | 编号 | 弱化内容 | `selftest.py` 失败数 | 结果 |
   |---|---|---|---|
   | R2-M1 | 原始树排序键去掉目录结尾 `/`（`key = name`） | 151/170 | 抓住（KILLED） |
   | R2-M2 | 原始树解析去掉哈希截断边界检查（`m.end() + hash_len > len(body)`） | 0/170 | **逃逸（SURVIVED）** |
   | R2-M3 | `is_tree()` 只认字面 `40000` 而不按位掩码判目录 | 1/170 | 抓住（KILLED） |
   | R2-M4 | `objects()` 去掉 `cat-file --batch` 尾随多余字节检查（`pos != len(data)`） | 0/170 | **逃逸（SURVIVED）** |
   | R2-M5 | 集合差忽略原始模式差异、只比对象名 | 3/170 | 抓住（KILLED） |
   | R2-M6 | 集合差漏掉仅存在于基线的路径（忽略纯删除） | 10/170 | 抓住（KILLED） |
   | R2-M7 | 忽略基线树规范性检查 `BASE_FORM` | 1/170 | 抓住（KILLED） |
   | R2-M8 | `LAKE_FILE` 去掉 ASCII 小写折叠 | 1/170 | 抓住（KILLED） |
   | R2-M9 | 重名条目允许后条覆盖前条（去掉 `sub not in found`） | 8/170 | 抓住（KILLED） |
   | R2-M10 | `TRUST_UNAPPROVED` 去掉 `p == GATE_DIR` 目录节点自身判断 | 0/170 | **逃逸（SURVIVED）** |

   （复现命令：`TMPDIR=/Volumes/AgentStorage/tmp python3 -I audit-reports/2312/precheck-r2-fixtures/run_r2_mutants.py`）
   建议补充对应红例：
   - 树对象 NUL 后截断（如 19 字节哈希）、空条目名、七位/非八进制模式的 `TREE_FORM` 用例（封住 R2-M2）；
   - 无放行 `infra/x` 仅修改 `formal_math/verification` 目录节点自身模式（如 `40000 -> 040000`，内部条目不变）须同时报 `MODE` 与 `TRUST_UNAPPROVED` 的用例（封住 R2-M10）；
   - R2-B1 修复后，补充 `scripts` / `.github` / `.github/workflows` 单独改模式为 `040000` / `40755` 以及在不含对应受信文件时替换为 `120000` / `100644` / `160000` 的必红用例（并可把 `R2-M4` 留作防御性不变量，因真实 `git cat-file --batch` 不会产生尾随多余字节）。

2. **收紧 `LAKE_ALLOWED` 的对象类型检查（`precheck.py:162`）**：
   `if parts[-1].lower() in LAKE_NAMES and path not in LAKE_ALLOWED:` 未要求 `kind == BLOB`。实测放行 `infra/x` 可在 `formal_math/verification/auditor/lakefile.toml/`（以及 `lake-manifest.json/`、`lean-toolchain/`）下建目录并放文件且预检退 `0`（而根上 `formal_math/lakefile.toml/` 会被 `TOP_LEVEL` + `PATH_SCOPE` 拒收）。建议改为 `and (kind != BLOB or path not in LAKE_ALLOWED)`，使六个例外路径全部只允许普通文件。

3. **加固「文件条目指向 blob」的交接或补一次 `--batch-check`**：
   如 3.2 节所述，建议二选一：① 在 `precheck.py` 的 `shape()` 前对被审清单全部非目录条目的 OID 做一次轻量 `git cat-file --batch-check`（不读任何 blob 正文，仅核对象存在且类型为 `blob`，约 6 行代码），使 `sources/`/`blueprint/`/`HISTORY.md`/`README.md` 亦闭环；或 ② 保持不查，但在 `README.md:99` 明确写清「仅对取料片实际读取的文件生效，且取料片须校验对象类型为 `blob`（不得用 `git show` / `cat-file -p`）」。

4. **微调 `README.md:41` 措辞**：
   原文「被审清单的规范性（第 2 条）总是报告；改动集合为空时不论分支名直接绿，否则继续第 4–7 条」在「改动集合为空但根树/祖先目录存在 `TREE_FORM`」时实际退 `1`（正确安全行为，例如 `selftest.py:275`）；建议改为「改动集合为空且第 2 条无红项时不论分支名直接绿」。

5. **优化 `selftest.py --mutants` 运行效率并统一绿行角色校验正则**：
   - `selftest.py:510` 对 16 次运行每次重新 `build(tmp)` 造 147 个提交（约 2000 次 `git` 子进程），在 macOS 外置卷 `/Volumes/AgentStorage` 上单次 `build` 约需 80–110 秒、整轮 16 次需半小时以上；夹具仓库对 `precheck.py` 只读，复用同一份 `build(tmp)` 并在每次 `special()` 前清理 `corrupt` 目录即可提速 4–5 倍。
   - `selftest.py:462` 断言绿行角色所用的近似正则 `(decl|proof|audit|infra)/\S+` 与 `precheck.py:42` 的 `BRANCH` 文法不一致（例如无改动且分支名为 `proof/a..b` 时，`precheck.py` 实际输出 `role=-`，该正则却会期望 `role=proof`）；建议直接复用 `BRANCH`。

6. **关于「受管范围之外不管」的设计权衡**：
   本轮按设计允许 `proof/*` 等内容角色分支在同一次 PR 中夹带受管外路径（如 `rust/lib.rs`、`.github/workflows/ci.yml`）并退 `0`，使预检边界高度内聚；但这也意味着 PR 层面的跨轨道隔离完全交给上层 CI/审阅纪律（#2315），后续若需禁止内容分支顺带改其它工作流，需在 #2315 的门禁策略里补齐。

---

## 五、核实正确的部分

1. **受审对象与提交核对**：`origin/infra/2312-e-precheck` 精确为 `5b6cc3ea1691077835ec02c5614720285b3b687b`，相对 R1（`a1035da727`）共 3 个提交（`ea57c236fe`、`c1fc702fd5`、`5b6cc3ea16`），仅改动 `formal_math/verification/precheck/{precheck.py,selftest.py,README.md}`（249 / 536 / 167 行，共 952 行）。在真实仓 `594e49b5ec..5b6cc3ea16` 上（正常与 ASCII 环境）实跑仅报 `README.md:139-142` 列明的 17 处现状（16 处 `LAKE_FILE` + 1 处 `formal_math/.gitignore` 的 `PATH_GRAMMAR`），逐一吻合；在共享克隆上模拟由放行 `infra/cleanup` 删除这 17 处后，整棵真实 `formal_math/` 树实测直接退 `0`（无放行退 `1` 报 `TRUST_UNAPPROVED`，`proof/cleanup` 退 `1` 报 `PATH_SCOPE` + `TRUSTED_DRIFT`），证实整仓无其余误红。
2. **作者自测复跑与规则码逐例核验**：
   - 未修改的 `selftest.py` 在 macOS 正常 UTF-8 与 `LC_ALL=C -X utf8=0` 两种环境下均跑出 `SELFTEST 170 例，失败 0 例 / SELFTEST PASS`（退 `0`）。
   - 独立审计脚本全量遍历 `selftest.py` 的全部 170 项（`CASES=147`、`special=22`、`tables=1`），核实覆盖全部 11 个 `RED` 规则码与 6 个 `FAULT` 故障码（`INTERNAL` 除外），每类抽查均确为声称的规则码、输出流（`RED`→stdout、`FAULT`→stderr）无错位、中文说明准确。
   - 作者内置 15 种 `MUTANTS` 在 macOS 上经共享只读夹具仓等价驱动全量复验全部通过（未改弱副本 `0/170` 失败，15 种弱化全部抓住，失败例数依次为 `25 / 22 / 8 / 2 / 7 / 3 / 3 / 2 / 7 / 1 / 11 / 1 / 2 / 3 / 1`；未修改的 `selftest.py --mutants` 实跑前 6 轮结果完全一致）。
3. **原始树对象解析健壮性（`run_r2_probes.py` 43/43 通过）**：
   - 空条目名、NUL 后截断（0B / 19B / SHA-256 下 20B）、尾随垃圾字节、七位模式（`0100644`/`0040000`）、非八进制模式（`100684`/`10064a`）、空模式、条目名含 `/` 均判 `TREE_FORM` 退 `1`；
   - `mode = 0`、`mode = 240000` 在受管路径下判 `MODE` 退 `1`；
   - 目录条目指向 `commit` / `tag` / `blob`（含内容酷似树的 blob）均判 `TREE_FORM` 退 `1`；指向缺失对象、全零 OID、损坏 zlib 对象均判 `GIT` 退 `2`；
   - `objects()` 对 `cat-file --batch` 的 16 项协议边界直测（合法空树/双对象、`missing`、`ambiguous`、空输出、头行缺换行、OID 不符、负数/非十进制长度、四字段头行、长度越界、正文缺结尾换行、尾随多余字节/换行、正文含伪造头行）全部符合预期；
   - 根树非受管条目含前导空格、换行、伪造 `cat-file --batch` 头行、高位字节 `0x80`/`0xff`、10KB 超长名以及 `formal_math/` 内 5000 字符合法模块名均正常解析无崩溃、无 ReDoS、无误红；500 文件单层目录树耗时约 `0.27s`，120 层深嵌套树（迭代 BFS 无递归栈问题）与同层共享同一树 OID 的 DAG 子树均正确处理；
   - SHA-256 对象格式仓库（64 字符 OID / 32 字节原始哈希）在绿例、跨角色红、原始模式 `100664` 红、20B 截断 `TREE_FORM` 红上全部正确。
4. **git 树排序规则一致性**：
   - 对照 git 源码 `base_name_compare()`，验证 `key = name + b"/" if is_tree(mode) else name` 与 `is_tree(mode) = (int(mode, 8) & 0o170000 == 0o040000)` 在普通文件、目录、`160000` 子模块（按非目录排序，实测与 `git mktree` / `git write-tree` 一致）、无符号高位字节及前缀混排（`p-1` < `p.1` < `p.d/` < `p/` < `p0` < `p_1`）上与 git 完全一致；目录/文件顺序颠倒均报 `TREE_FORM` 退 `1`。
   - 基线树不规范（`BASE_FORM`）无论被审提交规范、应红还是 `base == head` 均稳定退 `2`，不存在落成 `0` 的路径。
5. **`LAKE_FILE` 与无误红验证**：
   - ASCII 大小写折叠（`Lakefile.toml`、`LAKEFILE.lean`、`LAKE-MANIFEST.JSON`、`.LAKE`）及 `verification/auditor/` 大小写变体/更深层级全部判 `LAKE_FILE` 退 `1`；Unicode 同形字（西里尔 `а`）、尾点、尾空格均被 `PATH_GRAMMAR` 拒收退 `1`。
   - 四角色全表合法改动、带点/连字符/下划线的合法文件名（`README.md`、`v1.2-notes.md`、`_private.md`、`__init__.py`、`foo_.md`、`foo._bar`、`foo-_bar`、`01-intro.tar.gz`）、放行 `infra` 删除 `formal_math/.gitignore`、裸仓、全只读仓库（`chmod 555`/`444` 零写入且支持含空格/引号/非 ASCII 路径）、打包仓库（`git repack -ad` + `commit-graph`，packfile 中原始模式 `100664` 照常捕获）、子目录、嵌套附注标签、`garbage-signoffs.yaml` 两步搬家（`decl` 新增 + 放行 `infra` 删除）均按预期工作（无误红）；`Chan/Smoke.lean` 在四角色下均如实报 `PATH_SCOPE`。
   - 隔离与环境抗干扰：`git replace` 替换**树对象**与提交对象、`.git/info/grafts`、仓库级 `diff.renames=copies`、宿主环境注入的 `GIT_DIR` 与 `GIT_CONFIG_PARAMETERS` 全部被有效屏蔽。
6. **退出码契约、CLI 与文档一致性**：
   - R1 26 项边界探针（含 22 项 CLI 参数矩阵、断管/关闭 stdout & stderr、空 `PATH`、浅克隆、附注标签指向树、空分支名、非 UTF-8 分支名在 ASCII 环境下转义输出）全部在新代码上复验通过（26/26）。
   - `precheck.py` 全部 11 个 `RED` 码与 7 个 `FAULT` 码与 `README.md` 一一对应；`README.md:106-133` 与旧 `run_gates.py` 门 6b 及备忘原型 `expT/preflight_proto.py` 的出入逐行核实准确。

---

## 六、没覆盖的部分

1. **真实磁盘非 UTF-8 仓库路径**：macOS APFS 拒绝创建非 UTF-8 目录名，未能在本地测得「真实存在的非 UTF-8 仓库路径」判绿情形（已测非 UTF-8 分支名与树内路径在 ASCII 环境下正常工作）。
2. **低版本 git**：本机为 `git 2.50.1`，未在低于 2.24（不支持 `rev-parse --end-of-options`）的旧版 git 上实测退 `2` 路径。
3. **`safe.directory` 跨用户所有权拒绝**：未在跨 UID 所有权仓库上实测 git 拒绝打开时退 `2`。
4. **GitHub 远端 `receive.fsckObjects` 策略**：只读审阅未向远端推送畸形树对象，未实测 GitHub 服务端是否拦截 R2-B1a 的 `040000`/`40755`（注：R2-B1b 全部通过本地 `git fsck --strict --full` 退 `0` 零错零警，不依赖服务端放宽 fsck）。
5. **未修改 `selftest.py --mutants` 在 macOS 的全量 32 轮串行复跑**：受 macOS 外置卷每次重建 147 提交夹具仓约 2 分钟的 I/O 开销影响，未修改的 `selftest.py --mutants` 仅跑过前 6 轮（未改弱副本 0 失败 + 前 5 个弱化分别 25/22/8/2/7 例失败）后中止，作者全部 15 种弱化改由复用同一只读夹具仓的等价驱动在 macOS 全量复跑验证（Linux 上正常与 ASCII 的全量 `--mutants` 已由主控在送审前复跑通过）。
6. **Windows 平台行为与极端 DAG 树炸弹性能上限**：未在 Windows 下测文件描述符行为，未测百万级共享子树 DAG 展开时的内存/时间上限。

---

VERDICT: BLOCK — 范围：#2312 第一片纯静态预检（`formal_math/verification/precheck/{precheck.py,selftest.py,README.md}` @ `5b6cc3ea1691077835ec02c5614720285b3b687b`）
