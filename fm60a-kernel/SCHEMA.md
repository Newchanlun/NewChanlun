# FM-60a 原典作者陈述库机读格式说明（`fm60a-author-statements-v1`）

> **交付物定位（R3 改定）**：本目录的正式内核交付物是**纯作者陈述库**——每条记录只保存缠师在原文里说过的具体命题及其完整语境、语气、条件限定、对象指代、依存关系与说话人确认依据，力求**不回读博文也能准确读懂、不会读错**。
>
> **本交付物不是什么**：本交付物**不包含任何整理者建模（`organizer_models`）、合成数值实例（`instances`）、额外补入前提（`added_premises`）或预期输出**。怎样把这些陈述落成可计算条件、补哪些前提、用什么数去测试，留给后续编写形式化定义与回归测试的作者，在他们自己的名下、带着他们自己列出的前提去做。

---

## 一、文件划分：正式交付物 vs 隔离草稿/旧格式

| 分类 | 文件 | 状态与用途 |
|---|---|---|
| **正式交付物** | `classification.jsonl` | 61 条判例四分类映射（与 `fm60a-inventory/cases.jsonl` 严格双射；四类计数不变：`3 / 27 / 26 / 5`） |
| **正式交付物** | `kernel-cases.jsonl` | **9 条示范判例的纯作者陈述库**（`schema_version: "fm60a-author-statements-v1"`：`011, 012, 020, 021, 026, 027, 028, 031, 043`，共 63 条作者陈述） |
| **正式交付物** | `check.py` | 纯标准库机械核对脚本（只机检作者陈述库与隔离边界，详见 §四） |
| **正式交付物** | `SCHEMA.md`, `JUDGMENT.md`, `LIMITATIONS.md`, `REVISION-R1.md`, `REVISION-R2.md`, `README.md` | 格式契约、四分类判断、机检盲区与对读记录、两轮独审返修对照表 |
| **隔离区（非交付物）** | `draft-models-unreviewed.jsonl` + `DRAFT-MODELS-WARNING.md` + `drafts/non_normative_probe.py` | R2 移出的 9 条整理者建模与合成实例草稿（原样移出、未过审，仅供参考，使用者须自行核对前提） |
| **隔离区（非交付物）** | `legacy-v1-unreviewed.jsonl` + `LEGACY-V1-WARNING.md` | R1 移出的其余 20 条旧格式 `fm60a-kernel-v1` 记录（原样隔离、未经忠实性审查，不得使用） |

---

## 二、`kernel-cases.jsonl` 字段契约（`fm60a-author-statements-v1`）

每条判例仅含**元信息**、**逐字引文（`cites`）**与**作者陈述（`author_statements`）**三部分，`check.py` 机械禁止出现 `organizer_models`、`instances`、`added_premises`、`synthetic_witnesses`、`structure_spec`、`assertions`、`counterfactuals` 等任何建模/实例字段。

### 1. 顶层元信息
- `schema_version`：固定 `"fm60a-author-statements-v1"`
- `case_id`、`group`、`category`（`kernel_only` / `both`）、`exemplar`（`true`）、`target_concepts`、`evidence_grade`（按全条 `author_statements[*].refs` 现算）、`base_and_pen`（准确写明各引文实际准入等级与笔期，不把正文二级冒充硬证据）、`paired_cases`、`real_market_dependency`。

### 2. 逐字引文锚点（`cites[]`）
每条含：`cite_index`, `lesson`, `line`, `speaker`, **`speaker_basis`**, `quote`, `char_span`, `zone`, `in_admit_table`, `admit_id`, `tier`, `from_inventory`。
- **原清点表作者引文 100% 保留**（`from_inventory=true`）；
- **`speaker_basis`（必填非空）**：尤其对未命中 `7d0082ff` 准入表 `author_spans` 的二级材料，逐条写明确认该段确系缠师本人说话而非网友原话或行内编者注的依据（帖头与发文时间、`↑正文` 界标、`==` 答疑分隔符、无行内编注与外层引语），供非作者人审直接核查。

### 3. 作者陈述（`author_statements[]`）
每条陈述对应原文中作者说的一件事，包含以下必填字段：

| 字段 | 契约说明 |
|---|---|
| `statement_id` | 判例内唯一编号（`AS1`, `AS2`, ...） |
| `context` | 说话场景对象：`scene_kind`（8 值枚举：`事后复盘` / `当日更正复盘` / `当日盘后分析` / `一般规则与举例` / `图例分析` / `课后答疑` / `布置作业` / `后续规则调整`）、`post_timestamp`（原博文发表时间戳）、`time_anchor`（相对时间词「昨天」「今天」「目前」「以后」指向的具体日期）、`summary`（该句所处的具体上下文）。 |
| `mood` + `mood_note` | 7 值封闭枚举（`直陈事实` / `条件句` / `假设或反事实` / `预测` / `事后回顾` / `设问或留作作业` / `引述他人`）加非空 `mood_note`。采用**保守标法**：复盘旧日行情标 `事后回顾`，含尺度/范围/操作提醒/例外条件标 `条件句`，自设反问标 `设问或留作作业`，拿不准是否为无条件直陈的一律不标 `直陈事实` 并在 `mood_note` 写明理由。 |
| `antecedent` | 当 `mood` 为 `条件句` 或 `假设或反事实` 时必填非空字符串，完整保留外层与内层条件，**严禁把操作指示（「就在……回补」）搬入前件**；其他语气时必须为 `null`。 |
| `scope_qualifiers` | 原样保留的尺度、许可与外层限定语列表（如「可以看成」「可以当下地等待」「在1分钟级别显微镜下」「以后可以把笔的成立条件略微放松一下」），严禁改写为「是」「都是」「已经」。 |
| `statement` | 逐词可对回 `refs` 的忠实转写；若原文有相对时间锚点，在对应词后以 `（YYYY-MM-DD）` 保留所指日期（该日期须登记在 `context.time_anchor` 中）；除此类时间锚点日期外，**不得出现任何不在 `refs` 里的数值**，也不得私自添加引文未出现的限定词（`严格`、`唯一`、`必然`、`已`）。 |
| `objects_and_values[]` | 逐项登记陈述中的字面数值（`kind="literal_number"`）与关键对象（`kind="symbolic_object"`）：`item_id`、`literal_value`、`author_target`（原文指称的对象，如「56段反抽到达的价位」「1017的低点」）、`precise_point_or_field`（若原文未点明对应哪个顶点、哪根 K 线或高点/低点，**必须写精确字符串 `"原文未指明"`** 并填写 `unspecified_note`）。 |
| `depends_on_statements[]` | 本条成立所依赖的同判例其他陈述列表（每项 `{statement_id, relation, note}`，`relation` 取 `语境前提` / `分解前提` / `指代前文` / `图设条件` / `规则例外配对` / `规则依据`），构成**有向无环图（DAG）**。 |
| `qualified_by_statements[]` | 指向同判例中对本条加以限定、补充例外或约束实现状态的陈述编号（例如 `026.AS9` 禁相邻同级中枢规则指向同句例外 `AS10`；`012.AS5` 指向 `024:50` MACD 局限 `AS6`；`043.AS2` 标准跌法预测指向 `AS3/AS4`）。 |
| `evidence_tier` | 仅按本条自身 `refs` 现场重算的准入等级（本批 63 条全部为纯 `硬证据` 或纯 `二级，未提升`，零混合）。 |
| `effective_tier_with_dependencies` | 按本条 `refs` **并上全部传递 `depends_on_statements` 的 `refs`** 现场重算的有效等级。**下游按等级筛选时必须同时看此字段与 `depends_on_statements`**：例如 `028.AS7`（`054:58` 硬证据）依赖 `028.AS6`（`054:56` 二级分解二），其有效等级为 `混合（含硬证据与二级）`，从而杜绝按单条硬级筛选时把成立前提裁掉。 |
| `refs[]` | 指向 `cites[]` 的非空逐字切片。 |

---

## 三、下游（FM-60b / 定义作者）如何使用本库

1. **先读陈述与依存，再自行建模**：按 `case_id` 读取 `author_statements`，沿 `depends_on_statements` 与 `qualified_by_statements` 一并读全语境、分解前提与作者明说的例外。
2. **尊重「原文未指明」**：凡 `precise_point_or_field == "原文未指明"` 之处（本批 9 例共 33 项），代表原文未给出该顶点、字段、算法或高低次序；定义作者若要构造具体测试数据，须在自己的测试代码里显式声明自己补入的前提，并把测试失败如实归因为「在该前提下与作者陈述不相容」，不得当作作者字面报错。
3. **按有效等级分栏**：单条纯硬证据 31 条中，含传递依存后仍为纯硬证据的共 **12 条**，其余 **19 条**依赖二级语境/分解陈述（有效等级为 `混合`），纯二级陈述 **15 条**（含依存计数见 `check.py` 输出）。需要提升二级语境/规则时请走 #2336 / #2337，不越权提级。
4. **草稿文件不作真值**：`draft-models-unreviewed.jsonl` 仅作灵感或对照参考，不得直接导入回归测试。

---

## 四、`check.py` 机检范围与证明不了的事

- **`check.py` 机械检查的**：`classification.jsonl` 61 条双射、隔离文件对齐、禁止建模/实例字段、逐字引文与准入表 `7d0082ff` 现场重算、`↑正文` 界标、原清点表作者引文保留、`speaker_basis` 非空、拒绝已标非作者的 cite 入 `refs`、语气 7 值枚举、`条件句`/`假设或反事实` 必带 `antecedent`、陈述/前件/数值对象中的数值逐字回溯至 `refs`（仅放行已在 `time_anchor` 登记的 `（YYYY-MM-DD）`）、高风险未引限定词拦截、`原文未指明` 必带说明、`depends_on_statements` 指向存在且无环、`evidence_tier` / `effective_tier_with_dependencies` / `evidence_grade` 现场重算一致。
- **`check.py` 证明不了、必须靠非作者人审的**（详见 `LIMITATIONS.md` §一）：
  1. **二级文本的实际说话人**：未命中准入表 `author_spans` 时，机检只查 `speaker=="作者"` 且 `speaker_basis` 非空，**不能证明**该切片确实不是网友原话、转述他人或行内编者注；
  2. **转写忠实性与语境完整度**：机检无法判断是否删掉了外层条件、是否误把操作指示搬入前件、是否把「可以看成/可以等待」改写成已发生事实；
  3. **语气判定与适用时间**：机检无法判断 `mood` 是否判准、相对时间锚点日期解析是否正确、跨日规则（如 `081:110`）是否被误套用到前一日；
  4. **跨句指代与依存是否漏连**：机检只查已写出的 `depends_on_statements` 合法无环，无法发现漏写的分解前提、漏配的作者例外或指代错位；
  5. **「原文未指明」标注是否遗漏或错标**：机检无法判断某个对象究竟是原文点明的还是整理者替作者补的。
