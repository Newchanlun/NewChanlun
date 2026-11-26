# FM-60a 内核判例机读格式说明（`fm60a-kernel-v1`）

> 本格式面向 FM-60b（`ChanTest`）的 Lean 4 测试作者设计：**不必回读博文即可写出回归测试**，同时**每一个结构数值与断言都能由 `check.py` 机械追溯到语料正本的逐字区间与准入表状态**，且不预设任何尚未定稿的 Lean 定义。

---

## 一、文件组织

1. **`classification.jsonl`**（61 行，每行 1 条，与 `fm60a-inventory/cases.jsonl` 严格双射）：
   - `case_id`、`group`、`category`（`kernel_only` / `market_only` / `both` / `unusable`）、`digitized_in_kernel`（布尔，等于 `category ∈ {kernel_only, both}`）、`batch_a_status`、`inventory_status`、`inventory_image_dependent`、`reason`。
2. **`kernel-cases.jsonl`**（29 行，每行 1 条，覆盖全部 `kernel_only` + `both` 判例）：
   - 按 `case_id` 升序排列；`exemplar: true` 标记 5 组共 9 条代表性示范判例（第 54 课 `026–028`、第 24 课 ABC `011–012`、第 57 课 530 `020–021`、第 102 课四段零中枢 `043`、第 81 课 0.08 临界包含 `031`）。

---

## 二、`kernel-cases.jsonl` 字段契约

每条记录分为 **五层严格隔离**，防止把原文事实、结构抽象、合成见证与解释性选择混为一谈：

| 层 | 字段 | 职责与机检约束 |
|---|---|---|
| **1. 身份与证据元信息** | `schema_version`, `case_id`, `group`, `category`, `exemplar`, `input_kind`, `target_concepts`, `evidence_grade`, `base_and_pen`, `paired_cases`, `real_market_dependency` | `input_kind` 取四值之一：`polyline_segments`（14 条）、`polyline_with_strength`（10 条）、`kbar_fractal_pen`（4 条）、`multilevel_tower_state`（1 条）。`evidence_grade` 由 `assertions` 引用的 `cites` 现场重算（`硬证据` / `混合（含硬证据与二级）` / `二级，未提升`）。 |
| **2. 逐字语料锚点** | `cites[]`, `literal_facts[]` | 每条 `cite` 含 `cite_index, lesson, line, speaker, quote, char_span, zone, in_admit_table, admit_id, tier, from_inventory`。原清点表内全部作者引文均以 `from_inventory=true` 原样保留；为补全同课结构上下文而新增的作者引文标 `from_inventory=false`，同样逐字核对并相对准入表 `7d0082ff` 现场重算 `admit_id/tier`。**严禁在任何 `refs` 中引用网友或编者。** |
| **3. 符号结构与约束** | `structure_spec`（含 `domain`, `vertices`/`segments`/`kbars`/`levels` 与 `constraints[]`） | 只表达原文确定的符号拓扑与代数/序关系。每条约束必须标 `provenance`：`literal`（字面明写，其中所有裸数值必出现在 `refs` 原文中）、`derived_from_text`（由原文结构断言代数推出，必带 `rationale`）、`structural_default`（标准交替/高低价合法性）。 |
| **4. 作者断言与反事实** | `assertions[]`, `counterfactuals[]` | 表达「作者断言了什么结构」（及原文给出的反事实或自然边界对照），每条带 `evidence_tier` 与 `refs`；其中 `subject`/`expected` 内的所有字面数值均由 `check.py` 递归核对必须出现在 `refs` 原文中。 |
| **5. 合成见证与局限声明** | `synthetic_witnesses[]`, `interpretive_choices[]` | **所有具体数值实例全部隔离在 `synthetic_witnesses` 内**，每条必带 `synthetic: true`、`variant`（`primary` / `freedom_coverage` / `counterfactual`）、`determined_by_text`、`free_parameters`、`freedom_justification`（说明多实例覆盖或严格保序不变性）、`locked_values`（锚定到原文的精确数值）、`data` 与 `check_constraints`。`check.py` 机械求值所有 `check_constraints`，确保无错数、无自相矛盾。 |

---

## 三、约束表达式（`constraints[*].expr`）微型语法

供 `check.py` 与下游测试脚本直接解析（仅纯算术与序谓词，**不含任何缠论业务定义**）：

- **数值操作数**：裸数字（`4087`、`0.08`）；符号名（查 `vertex_prices` → `strengths` → `scalars`）；K 线字段（`"b5_1017.low"`）；聚合函数 `{"fn": "sum"|"min"|"max"|"sub"|"abs_sub"|"len", "args": [...]}`。
- **布尔算子**：
  - 标量序：`eq`, `ne`, `lt`, `le`, `gt`, `ge`, `in_closed`；
  - 区间交：`overlap_eq`, `overlap_nonempty`, `overlap_empty`（统一按闭区间 `[min, max]` 算术求交，供见证自检）；
  - 折线与 K 线几何：`seg_alternating`（验证严格上下交替）、`kbar_valid`、`kbar_contains`、`kbar_no_inclusion`、`kbar_bottom_fractal`、`kbar_top_fractal`；
  - 显式布尔状态与逻辑组合：`flag_eq`, `not`, `and`, `or`。

---

## 四、给 Lean 4 `ChanTest` 作者的对接指引

1. **按 `evidence_grade` 分栏入库**：全硬证据 7 条（`FM60A-012, 017, 020, 026, 029, 055, 056`）与混合 8 条中的硬证据断言（`FM60A-009, 010, 021, 024, 027, 028, 031, 041`，具体以每条 `assertion.evidence_tier` 为准）可直接作为一级硬证据测试；`二级，未提升`（14 条）与混合条目的二级断言在 #2336/#2337 提升前仅作参考回归，不作硬证据阻断。
2. **用 `synthetic_witnesses` 区分多实例与反事实**：
   - `variant = "primary"`：满足作者全部主断言的最小基准实例；
   - `variant = "freedom_coverage"`：改变原文未锁定的自由度（如中枢上下沿由不同端点提供、总计 9 段 vs 3+9=12 段、`g7` 是否低于 `d3`），用于检验定义是否对自由度鲁棒或暴露口径分叉；
   - `variant = "counterfactual"`（带 `counterfactual_id`）：单变量扰动临界边界（如 `d1>g2`、`-0.08`、`p4>=p1`、`rebound==4087`），用于防「恒真定义」误过测试。
3. **绝对不把 `synthetic_witnesses` 当成真实历史行情**：任何 `data` 均带 `synthetic: true`，仅作抽象核输入；真实历史行情回归请继续读取 `fm60a-batch-a/`（及未来如补齐的分钟行情）。
