# FM-60a 内核判例机读格式说明（`fm60a-kernel-v2`）

> 本格式为 R1 忠实性独审（`origin/evidence/2324-kernel-review` @ `ab339d74`）后的结构性重设计。核心原则：**把「作者字面说了什么」「整理者如何把它落成可计算条件」「拿什么合成数值来实例化」在结构上分成彼此独立的三层，而不是放在同一层靠自贴标签区分。**
>
> **下游测试语义（必读）**：下游 FM-60b（`ChanTest`）若拿本格式中的建模与实例作为回归测试，**测到的是「在某一套整理者建模 `M*` 的前提下，待测定义与作者陈述 `AS*` 是否相容」**——既不宣称 `M*` 是作者唯一指定的算法或读法，也不替待测定义或作者陈述下对错裁决。

---

## 一、文件组织与旧格式隔离

1. **`classification.jsonl`**（61 行，与 `fm60a-inventory/cases.jsonl` 严格双射）：
   - 字段：`case_id`、`group`、`category`（`kernel_only` / `market_only` / `both` / `unusable`）、`digitized_in_kernel`（布尔）、`kernel_digitization_status`（`v2_exemplar` / `v1_legacy_unreviewed` / `not_kernel`）、`batch_a_status`、`inventory_status`、`inventory_image_dependent`、`reason`。
   - 四分类计数保持不变：`kernel_only` 3 条、`market_only` 27 条、`both` 26 条、`unusable` 5 条。
2. **`kernel-cases.jsonl`**（**9 行**，`schema_version: "fm60a-kernel-v2"`）：
   - 本轮只按新三层格式重做并受审 5 组共 9 条示范判例：`FM60A-011, 012, 020, 021, 026, 027, 028, 031, 043`。
3. **`legacy-v1-unreviewed.jsonl`**（**20 行**，`schema_version: "fm60a-kernel-v1"`）与 **`LEGACY-V1-WARNING.md`**：
   - 其余 20 条内核判例从 R1 提交 `950ca9d2` **原封不动**移入此隔离文件，**旧格式，未经忠实性审查，不得用于下游回归**。

---

## 二、回答下游两个不同问题（修复 B21）

旧格式（v1）只给断言和反事实挂了 `refs / evidence_tier`，导致下游无法区分「**谁主张了这个命题**」与「**所引语料处于什么准入等级**」（例如 `FM60A-026` 作者亲口反事实与 `FM60A-012` 整理者构造反事实都挂硬证据）。v2 用两个正交维度彻底分开：

1. **谁主张这个具体命题**：由所在结构层与字段决定——
   - `author_statements[]`（含 `mood`、`antecedent`、`literal_values`）：作者字面命题；
   - `organizer_models[]`（含 `depends_on_statements`、`added_premises`、`alternative_models`）：整理者将作者陈述落成可计算条件的建模与前提；
   - `instances[]`（含 `literal_bindings`、`free_parameters`、`counterfactual_proposer`）：全部合成的数值实例，并强制区分作者提出的反事实与整理者构造的反事实。
2. **所引语料获什么准入等级**：仍由 `cites[*]` 相对准入表 `7d0082ff` 单一 `author_spans` 区间现场重算（`硬证据` / `二级，未提升`），并逐条投影到每条 `author_statements[*].evidence_tier`（本批 9 条共 53 条作者陈述均按纯等级分拆，避免把硬证据与二级句段混压在同一条陈述里）。

---

## 三、`kernel-cases.jsonl` 三层结构契约

### 公共元信息与逐字锚点
- 顶层身份字段：`schema_version`（`"fm60a-kernel-v2"`）、`case_id`、`group`、`category`、`exemplar`（`true`）、`input_kind`、`target_concepts`、`evidence_grade`（按全部 `author_statements[*].refs` 现算）、`base_and_pen`、`paired_cases`、`real_market_dependency`。
- `cites[]`：每条含 `cite_index, lesson, line, speaker, quote, char_span, zone, in_admit_table, admit_id, tier, from_inventory`。原清点表作者引文 100% 保留；所有 `refs` 严禁引用非作者（`网友` / `编者`）。

### 第一层：作者陈述层（`author_statements[]`）
只收作者字面说出的命题，**不含任何算法、不含任何整理者自选符号或原文未出现的数值**。每条必填字段：
- `statement_id`：`AS1`, `AS2`, ...
- `mood`：**7 值封闭枚举**（必填非空）：
  1. `直陈事实`
  2. `条件句`
  3. `假设或反事实`
  4. `预测`
  5. `事后回顾`
  6. `设问或留作作业`
  7. `引述他人`
- `antecedent`：条件部分。当 `mood` 为 `条件句` 或 `假设或反事实` 时**必填非空字符串**，原样保留前置条件、不得合并进结论；其他语气时必须为 `null`。
- `statement`：逐词可对回 `refs` 的精简转写。不得夹带引文未出现的数值，不得私自加入引文未出现的限定词（`严格`、`唯一`、`必然`、`已`）。
- `literal_values[]`：作者字面给出的数值清单，每项含：
  - `value_id`（`LV*`，判例内唯一）、`value`（机检必出现在 `refs` 中）、`unit_or_role`、`author_target`（**精确记录作者将该数字绑定到什么对象**，例如「1分钟中枢区间下沿」或「前一分钟数值点，原文未指明高点或低点」）、`binds_instance_target_literally`（布尔：**仅当作者既给了数值又字面指明了目标对象/字段时才为 `true`**；若对象有歧义如 `081:30` 的 `5386.39`，必须为 `false`，禁止实例层放入 `literal_bindings`）。
- `evidence_tier`：按本条 `refs` 现场重算（`硬证据` / `二级，未提升` / `混合（含硬证据与二级）`）。
- `refs[]`：指向 `cites[]` 的非空逐字切片。

### 第二层：整理者建模层（`organizer_models[]`）
把作者陈述落成可计算条件的每一步都放这里。**同一条作者陈述若存在多种合理读法、候选解释或条件分支，必须在 `organizer_models[]` 中并列给出多个 `M*`，各自配齐实例，绝不单选其一。** 每条模型必填字段：
- `model_id`（`M1`, `M2`, ...）、`title`、`reading_group`（标明同组并列读法分叉的维度）。
- `depends_on_statements[]`：必填非空，指向本模型所依赖的 `AS*`。
- `symbol_schema`：本模型引入的符号与数据结构声明（`domain` 须等于 `input_kind`）。
- `added_premises[]`：必填非空数组，每项 `{premise_id: "P*", category, statement}` 逐条列出整理者补入的原文未明说前提（如成核规则、端点与顶点对应、等号边界选支、力度比较代理、7 根无前置包含布局、读法选择等）。
- `alternative_models[]`：必填非空字符串数组，说明别的合理落法或指向同记录的并列 `M*`。
- `computable_conditions[]`：每条 `{cond_id: "C*", depends_on_statements, uses_premises, description, expr}`，逐条绑定所依赖的作者陈述 `AS*` 与所用的整理者前提 `P*`。
- `expected_under_model[]`：每条 `{expect_id: "E*", depends_on_statements, uses_premises, subject, expected, compatibility_note}`，明示在「本模型 `M*` + 前提 `P*`」下待测定义与作者陈述相容时应满足的输出。

### 第三层：实例层（`instances[]`，全部合成）
每条实例均为合成数据，彻底删除旧版 `determined_by_text` 中间态。每条必填字段：
- `instance_id`（`I1`, `I2`, ...）、`model_id`（指向合法 `M*`）、`synthetic: true`。
- `data`：对象，**内部必须同样显式包含 `"synthetic": true`**（响应 S10，使独立导出 `data` 时仍自带合成标记）。
- `instance_role`：`"positive"` | `"counterfactual"`。
- 反事实来源三件套：
  - `counterfactual_proposer`：正例必为 `null`；反事实**必填** `"author"` 或 `"organizer"`；
  - `counterfactual_statement_id`：当 `counterfactual_proposer == "author"` 时**必填**，且所指 `AS*` 的 `mood` 必须为 `"假设或反事实"`；当为 `"organizer"` 或正例时必为 `null`；
  - `counterfactual_rationale`：反事实必填非空说明，正例为 `null`。
- `expected_under_instance`：正例为 `model_id` 下非空 `E*` 列表；反事实为 `{scope_note, expected}` 对象（仅写由该扰动实际能推出的最小结论）。
- **数值严格二分（不重不漏）**：
  - `literal_bindings[]`：每项 `{target, value, statement_id, value_id}`，所指 `LV*` 的 `binds_instance_target_literally` 必为 `true`，且同时锁定「原文数值 + 原文所指对象」（例如 `reported_1m_zd=4087`、`v6=4077`、`g0=18.5`、`b5_1017.low=5386.47`、`p0=6124`；反事实中被替换的值如 `v6=4087` 或 `b5_1017.low=5386.39` 一律不得放这里）。
  - `free_parameters[]`：每项 `{target, value, note}`，包含全部整理者自选坐标、力度、等号边界、扰动值与读法映射值。
  - **机检不变式**：`literal_bindings` 与 `free_parameters` 的目标集合互不相交，且其并集严格等于 `data` 中全部数值叶节点集合（零遗漏、零重叠）。
- `check_conditions[]`（及仅允许在反事实中出现的 `condition_overrides`）：每条在 `data` 上由 `check.py` 机械求值为真。

---

## 四、条件表达式（`computable_conditions[*].expr`）微型语法

仅包含纯算术与序谓词，**不含任何缠论业务定义**：
- **数值操作数**：裸数字；符号名（查 `vertex_prices` / `strengths` / `scalars`）；K 线字段（`"b5_1017.low"`）；聚合函数 `sum` / `min` / `max` / `sub` / `abs_sub` / `len`。
- **布尔算子**：`eq`, `ne`, `lt`, `le`, `gt`, `ge`, `in_closed`, `overlap_eq`, `overlap_nonempty`, `overlap_empty`, `seg_alternating`, `kbar_valid`, `kbar_contains`, `kbar_no_inclusion`, `kbar_bottom_fractal`, `kbar_top_fractal`, `flag_eq`, `not`, `and`, `or`。

---

## 五、`check.py` 机检边界与人审边界

- **`check.py` 能机械保证的**：逐字语料切片、准入表重算、禁止非作者入 `refs`、语气枚举合法性、条件句 `antecedent` 非空、作者陈述层阿拉伯数值与 `LV*` 逐字回溯、未引高风险限定词拦截、建模层必指 `AS*` 且无悬空模型、实例外层与 `data.synthetic` 双重标记、反事实提出者必填且 `author` 必指 `假设或反事实` 语气、`data` 全数值在 `literal_bindings` 与 `free_parameters` 间不重不漏二分、全部 `check_conditions` 求值为真。
- **`check.py` 无法判断、必须靠非作者人审的**（详见 `LIMITATIONS.md` §一）：转写 `statement` 是否忠实于原文语境、语气 `mood` 归类是否准确、`binds_instance_target_literally` 是否错标、`added_premises` 是否漏列隐含前提、并列读法是否遗漏其他合理分支，以及反事实 `expected_under_instance` 是否超推。
