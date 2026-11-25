# 门禁 11：正文区引文核对（#2317）

输入只有一份：`formal_math/sources/admit/` 里的正文区准入表 `candidate/tier1_candidate.jsonl`（790 条，已过非作者实物审，范围仅限**正文归属**；记录见 #2316 评论 7166555103）。本目录不接入 `run_gates.py`，接入总入口等 #2312 过审后由主控做。

只用标准库，一律 `python3 -I` 运行；仓库根按脚本位置推出（`--root` 可覆盖），脚本里没有机器路径。

## 两个脚本

| 脚本 | 性质 | 退出码 |
|---|---|---|
| `check_admit_table.py` | **阻断**：准入表完整性与语料指纹 | 0 全过；1 有不符（红行逐项写到标准错误，点名文件或 id）；2 工具自身无法运行 |
| `report_citations.py` | **报告**：`formal_math/` 里每条硬证据引文的读数 | 恒 0；只有脚本自身出错退 2 |

```sh
python3 -I formal_math/verification/gate11/check_admit_table.py
python3 -I formal_math/verification/gate11/report_citations.py [--json 报告.json | --json -]
python3 -I formal_math/verification/gate11/selftest.py
```

### 阻断检查查什么

1. **摘要清单**：`sources/admit/SHA256SUMS` 里每个文件现算相符；目录里没有清单之外的文件（`__pycache__`、`.pyc` 除外）。
2. **行数**：恰 790 行；键序与约定一致；id 不重复。
3. **逐行自洽**：区间在原行长度内、递增、不相交；`author_spans` 全在 `quote_spans` 内；`verdict` 与区间一致；按每条的 `lesson`、`line`、`author_spans` 从语料取字，复算 `author_text_sha256`。
4. **重建零差分**：在临时目录里用入库的 `merge.py`，从 `pass-a/`、`pass-b/` 原件与 `adjudications.json` 重建，与入库准入表**逐字节**相同。
5. **语料指纹**：`docs/chanlun/text/blog/*.md` 的指纹（`sha256sum *.md | sha256sum`，文件名按字节序）等于基线 `b6a35574…a0d`，且入库的 `CORPUS_FINGERPRINT` 与基线一致。基线同时写在脚本常量与该文件里；真要换语料，两处与 `SHA256SUMS` 须同改并经独审。

**重建的做法与限制**：`merge.py` 写死了 `fm09-admit/…`、`fm09-register/tmp/lib.py`、`ledger_final.jsonl` 的相对布局，而登记册按票面不入库。所以脚本不改 `merge.py` 一字，而是在临时目录里搭出它要的布局：

- 两遍原件、`adjudications.json`、`merge.py` 从仓内拷入，语料拷入；
- `lib.py` 用本目录 `merge_shim/lib.py` 代替，它只含 `merge.py` 用到的 `BLOG` 与 `load()`，取文逻辑与正本一致；
- `ledger_final.jsonl` 不可得，用**甲遍原件的 id 序**写一份只含 `id` 与 `who: 正文` 的替身。因此 `merge.py` 里「id 集合等于台账中 `who == 正文` 的 id」这一句，在仓内退化为「甲、乙两遍 id 序相同」。台账本身的核对只能回到 `evidence/2317-tier1-candidate` 上做，仓内做不到。

### 阻断检查不查什么

不查摘句支持什么命题，不查标注者的判断对不对（那是非作者实物审的事），不查台账。`nonauthor_kind` 只是标注者分类，不是事实认定。

### 引文报告查什么

扫 `formal_math/` 下的 `.lean` 与 `.md`（跳过 `.lake`、`sources/admit`、本目录），抽出每条 `【归属 课号:行号】「…」`，每条给一个读数：

| 读数 | 含义 |
|---|---|
| `ok` | 课行在表内，引的字逐字落在该课行的**同一个**作者连续段内 |
| `lesson_line_not_in_table` | 表外课行 |
| `quote_overlaps_excluded_text` | 字在原行里逐字存在，但含未准入的字（被剔除的，如 017:40 的「“一分为二”」，或不在任何作者区间） |
| `quote_spliced_across_spans` | 原行里找不到，但等于把该行各作者区间的文字拼起来再摘（裁剪条目的跨段拼接） |
| `segments_in_different_runs` | 引文用省略号断成几片，每片都在作者区间，但分属不同连续段 |
| `quote_not_in_line` | 原行里逐字找不到 |
| `empty_quote` | 引号内为空 |

「作者连续段」＝该课行上所有表内条目的 `author_spans` 取并集后的极大连续字符段（同一行有几条记录时合并；相邻或重叠的并为一段，被剔除字符把段隔开）。NBSP 与空格视为同一字符，与标注遍一致。机读 JSON 含每条的文件、行、列、归属、课行、引文、读数、命中的表内 id，以及未能解析的标记清单；人读摘要列出所有非 `ok` 项。

只有 `【缠师逐字】「…」` 这一种括号归引文核对管；`『…』`（网友或编者文字）与 `〈…〉`（概括）不抽。归属字样不做校验，只原样记录。

### 引文报告的已知局限（抽取靠模式匹配）

- **跨行引文**：`「` 与 `」` 不在同一物理行的，抽不到，记入 `unparsed_markers`，不进读数。
- **嵌套引号**：引文内部再含 `「` 或 `」` 的抽不到或会被截短，同样靠 `unparsed_markers` 暴露，不保证每次都能暴露。
- **一行多条**：能抽，每条各自读数。
- **多行号写法**（`017:40、41`、`017:40-41`）与课号不是三位的：不当作引文，只进未解析清单。
- **省略号**：先整串逐字找；找不到再按 `……`、`…`、`...` 切片，每片都须在作者区间内且同属一个连续段。这不检查片间顺序或距离，片与片之间是否真是原文省略无从核。
- **只看课行，不看全文**：引文落在该课行之外（引的是邻行的字）报 `quote_not_in_line`，不会替你找邻行。
- **前后文与编辑环境**：不理解 Lean 注释前缀（`--`、`/-`）、Markdown 代码块或表格；标记后的 `「」` 与标记之间只许隔空白。
- 编码有问题的文件以替换字符读入，不报错。
- 扫描只覆盖当前文件系统上的 `.lean` 与 `.md`；其他后缀不扫。
- 对当前 `formal_math/` 实跑，硬证据引文为 0 条（正文区引文尚未落进该目录）；这个 0 不说明抽取器已被真实样本检验，检验靠 `selftest.py` 的夹具。

升为阻断的条件：经非作者独审后另行裁定（#2317 票面）。

## 自测

`selftest.py` 在临时目录里拷一份准入表与语料，逐项改坏再跑：

- 阻断检查：正常通过；语料多一字（指纹不符）；准入表改一个字节；改表并同步重算清单（只动 `passes_agree`，须靠重建差分抓）；删一行；把 017:40 的剔除字放回作者区间；改甲遍原件的区间或 verdict 并同步清单；找不到准入表（退 2）。
- 引文报告：`fixtures/cites.md` 逐行带 `expect:`——正常引用、子串、被剔除的字（017:40「“一分为二”」）、裁剪条目跨段拼接成一句（081:42）、引被剔除括注本身、省略号跳过剔除处、表外课行、字不在原行、一行两条、跨行与多行号（只进未解析）；并验证退出码恒 0、扫描目录不存在时退 2。

## 维护

- 改动 `sources/admit/` 任一文件后，须重算 `SHA256SUMS`：在该目录里
  `find . -type f ! -name SHA256SUMS | LC_ALL=C sort | xargs sha256sum > SHA256SUMS`。
- 入库文件与 `origin/evidence/2317-tier1-candidate` @ `2031547003290e1692c0c397f34566b59c596245` 的 `fm09-admit/` 逐字节一致，唯一例外是 `candidate/README.md`（标题与文末新增的两处说明）；新增 `SHA256SUMS`、`CORPUS_FINGERPRINT`。未入库：`errata/`、登记册主册、总计划手册、旧台账。
- `sources/admit/pass-b/tools/` 里的两个原件含标注当时的机器路径，按「逐字节一致」未改；它们只是历史标注工具，不被本目录的任何脚本调用。
