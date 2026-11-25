# #2317 FM-09b 正文区准入表与引文核对 · 第二轮独立复审

- 被审提交：`01cdc3a32a6cbf9ccb9d29529d4218eb3171ff7e`（已核远端 `infra/2317-admit-table`），基点 `594e49b5ec034461f9196c6cfb0c58fe017e8dc5`。
- 非作者审阅者：OpenAI `gpt-6.2-astra`，`xhigh`。
- 实测语料指纹：`b6a35574ed6db3625da6d18f4e11c8976874ba66b0e888362e1769483f0c0a0d`（110 个 Markdown 文件）。
- 合同：[票 #2317](https://github.com/Newchanlun/NewChanlun/issues/2317)。冻结实物：`2031547003290e1692c0c397f34566b59c596245:fm09-admit/`。首审：`1345e4f8a1439af35dcc8616cf27cb2a20d10c37:audit-reports/2317/FM-09b-admit-review.md`，审的是 `8411fa93d5613dccda81c72e89d58a7c9f24632e`。

**当前提交里的表是过审原表，790 行可逐字节重建。验收仍应阻断。** 首轮具体反例已全部纠正，但 B2 保护的入库身份还没闭合：磁盘上读到的内容相同，不等于 Git 入库的文件相同。另有一种禁止入库的材料能逃过清点，以及两种可复现的引文读数错误。共 4 项，均不要求把引文报告改为非零退出。

## 复现约定

在证据分支的仓库根执行以下两行。Git 对象库需含上述冻结实物提交。夹具 [probe_r2.py](probe_r2.py) 在专用临时目录里创建副本，追踪、改写及符号链接测试均只涉及副本。下面的 `rc` 指被测入口，不是夹具进程。

```sh
export TMPDIR="$(mktemp -d /Volumes/AgentStorage/fm09b-r2-replay.XXXXXX)"
export F=audit-reports/2317/probe_r2.py
```

下文的 `check`、`report`、`selftest`、`README` 分别指 `formal_math/verification/gate11/` 下的 `check_admit_table.py`、`report_citations.py`、`selftest.py`、`README.md`。行号均属被审提交。

## 第一轮六项：五项闭合，一项的原反例已拦但合同未闭合

| 首审项 | 结论 | 独立实测 |
|---|---|---|
| B1 · id 743 的最终结果 | **已闭合** | `fidelity`：`743 intersection [[0, 6], [15, 86]] final [[15, 86]]`；760、778 的交集各自等于最终区间。`candidate/README.md:72` 现在写对了。 |
| B2 · 冻结身份 | **未闭合** | `first-b2`：`swap-id rc 1`、`restore-votes rc 1`、`no-cut-synced rc 1`。三组都从改过的输入独立重建并重算入库清单，前两组红行点名表和甲遍，末组点名处置和表。**首轮三例都已拦**；不改钉选清单仍可换掉 Git 原件而绿，见 R2-1。 |
| B3 · 按 id、按区间 | **已闭合** | `cites`：011:26「湿吻。把短期均线」为 `spans_multiple_ids`、无命中；011:16「技术分」为 `ok`，仅 id 13 `[0,3)`。790 条中同一 id 的相邻作者区间对数为 0。 |
| B4 · 省略号误过 | **已闭合** | 倒序、重复均为 `elided_unsupported`；不存在的尾省略号为 `elided`，不是 `ok`。按序两片同区间为 `elided`；跨 081:42 剔除处为 `elided_unsupported`。端点样本中 4 条含原文省略号的整串确实为 `ok`。 |
| B5 · 空格替换 NBSP | **已闭合** | 014:44「析如下：〈空格〉在周线2」，原 U+00A0 得 `ok`、id 46 `[6,15)`；换 U+0020、U+3000 均为 `whitespace_differs`。R2-4 是相反方向：单个原样字符被错读为空。 |
| B6 · 漏扫普通文本 | **已闭合** | 在临时 Git 仓默认扫描：`sources/note.txt` 与 `sources/note.lean` 中同一条 054:60「*」均为 `quote_overlaps_excluded_text`，无后缀的 `sources/free` 也报同值。 |

```sh
python3 -I "$F" fidelity
python3 -I "$F" first-b2
python3 -I "$F" cites
python3 -I "$F" oracle
```

## 新的可复现阻断缺陷（4 项）

### R2-1 · Git 里已经不是原件，磁盘目标相同仍给绿灯

**违反**“入库文件与 `2031547003` 逐字节一致”及冻结原件的阻断检查。夹具在临时仓分别暂存普通 `SPEC.md` 和指向同仓等内容文档的符号链接；链接目标也已暂存。直接用 `git show :formal_math/sources/admit/SPEC.md` 比较要入库的 blob，而不是再次打开文件。两个清单、准入表、语料、门禁代码均未改。

```sh
python3 -I "$F" inventory
```

```text
regular-control git_mode 100644 blob_equals_upstream True indexed_files 49
regular-control rc 0 | GATE11 阻断检查 GREEN：摘要清单、790 行、重建零差分、作者文字摘要、语料指纹均相符
linked-document git_mode 120000 blob_equals_upstream False indexed_files 49
linked-document rc 0 | GATE11 阻断检查 GREEN：摘要清单、790 行、重建零差分、作者文字摘要、语料指纹均相符
```

`check:45–50,90–95` 的 `is_file()` 与 `read_bytes()` 都沿链接走。冻结的 Git 普通文件应仍为普通文件；需核实路径组件和文件类型，不能只核目标内容。这是 B2 的新反例，只记一次。

### R2-2 · 已跟踪的勘误表不在清单里，目录清点仍绿

**违反**“不入库：……勘误表”与入库清单的完整性。用的是真实上游 `fm09-admit/errata/errata.jsonl`，不是 Python 缓存。它在副本中作为 `formal_math/sources/admit/__pycache__/errata.jsonl` 进入 Git 索引；没有重算任何清单。与 R2-1 不同，此例保留全部原件且没有符号链接。

```sh
python3 -I "$F" inventory
```

```text
extra-document git_mode 100644 blob_equals_upstream True indexed_files 50
extra-document rc 0 | GATE11 阻断检查 GREEN：摘要清单、790 行、重建零差分、作者文字摘要、语料指纹均相符
```

上行的 mode 和 blob 比较指对照文件 `SPEC.md`；原有 49 个条目均仍在。`check:51–58,96–106` 两遍清点都不进入名为 `__pycache__` 的目录，还一律跳过 `.pyc`。普通位置多放 `reader-note.txt` 则两层都报红。可以忽略未入库的本地缓存，不能按名称从**已跟踪材料**中删掉一整类路径。

### R2-3 · 单 CR 换行把两行拼成一条硬证据，还标错合法引文的位置

**违反**报告对 `formal_math/` 内每条硬证据引文的逐条读数：下面只有第 2 行是一条完整引文；第 3 行的标记和第 4 行的引号不在同一物理行。三个 UTF-8 文件内容相同，只改 LF、CRLF、CR 行结束符。README:82,86 明说跨行只进未解析。

```text
前言
【缠师 000:26】「而市场的波动」
【原文 000:26】
「明白了这一点」
```

```sh
python3 -I "$F" newlines
```

```text
lf cites [(2, 1, 'ok')] unparsed [(3, 1)]
crlf cites [(2, 1, 'ok')] unparsed [(3, 1)]
cr cites [(1, 4, 'ok'), (1, 24, 'ok')] unparsed []
```

`report:195` 只按 LF 切行，`:28` 的空白匹配又吞了 CR。应在分物理行时识别 CRLF、LF、CR，而不是靠引号正则跨过 CR。不改变同一行里真正的 NBSP 或其他被引字符。

### R2-4 · 逐字命中的非空引文被报为“引号内为空”

**违反**“引的字须逐字落在该条的作者区间内，读数逐条列出”。014:44 id 46 的 `[10,11)` 是一个 U+00A0。夹具把这个**单一原字符**放入引号，并另设零字符对照。报告的原始 `quote` 字段保留了 NBSP，但两者的字面结果和位置均相同：

```sh
python3 -I "$F" cites
python3 -I "$F" oracle
```

```text
space-only [('empty_quote', 'empty_quote', [], True, False)]
empty [('empty_quote', 'empty_quote', [], True, False)]
014:44 white [('empty_quote', [(46, 10, 11)])]
```

最后一行左侧是实得 `match`，右侧是独立按原字符枚举的命中。`report:80–81` 在查找前先 `strip()`；与 README:59,67,76 的“当且仅当”“不做任何归一”“引号内为空”都不符。应保留真实字面结果和命中。若不希望纯空白成为可用证据，可另列政策读数；无需把非空说成空，也不必评价摘句支持什么命题。

## 非阻断建议（6 条）

1. **让反向自测证明是目标断言变红。** 外层实跑确是“自测：90 项，不符 0”。但 `selftest:345–348,355–385` 在**没有 Git 的临时副本**里跑子自测，却要求文件来源为 Git。连未改的子副本都红；四项外层判据用整份输出找关键词，未改副本也全部满足。把子副本变成 Git 仓后，四种弱化各自确实触发了**一个相关失败**，所以不能把问题说成“四种弱化并不会红”。另把所有精确命中的坐标改成 `[0,0]`，86 项仍绿；`:300–304` 只验坐标有两个数。建议先断言同布局阴性对照为绿，再核具体失败项和坐标值。票面点名的四类必红或必报样本本身均有效。
2. **两种清单采用同一套规范路径规则。** `probe_r2.py pins`：钉选清单允许首列 `#` 注释；重复同名项仍退 0（字典后项覆盖），含父目录组件的路径会被解析器保留（只调用解析器，未读取该路径）。删掉 `SPEC.md` 一项或只改其大小写，均退 1。入库摘要清单加注释、重复原路径、加父目录项、删项、更改大小写均退 1；另加同一文件的 `././SPEC.md` 路径写法却退 0。当前 47 项路径规范、各自唯一；这些清单编辑不另算“原件内容改变仍绿”。
3. **把宽松标记识别的实际边界写准。** `cites` 实测四位/两位课号、全角冒号、缺分隔、缺归属、多行号、嵌套引号及另一种引号均进未解析，有行列和原因；制表符分隔的合规标记为 `ok`。但 `【缠师 011:26【注】】「湿吻」` 静默丢失（只取最内层方括号）；`【缠师 ０１１:２６】「湿吻」` 过严格语法，课号却以原字符串查表，报表外。建议明确数字字符集，并收窄 README:82 的“一律”或报告受损标记。这两例不据以声称漏掉了规范 ASCII 完整引文。
4. **说明非精确匹配的坐标是示例还是全集。** `oracle` 实测 011:16 的“技术”在 0、23（id 13）与 91、121（id 14）均命中；查询“技 术”时 `whitespace_differs` 只给 id 13 的 `[0,2)`，因为 `report:101–105` 首次命中就返回。省略号的坐标则是首片到末片的包围区间，不是整串命中的位置。建议与精确 `hits` 区分，并在消费统计时分别看 `match` 和 `attribution_accepted`。例如名单外归属加跨 id，`status=spans_multiple_ids`、`attribution_accepted=false`；名单外归属加原样命中才是 `status=attribution_not_accepted`。两者都不会误绿。
5. **把运行说明与错误分支对齐。** README:12 所述缺输入退 2 属实，但“脚本跑不起来退 2”并不普遍：`inputs` 给损坏的表得到 `bad-report-input rc 1 report False error json.decoder.JSONDecodeError`；缺扫描目录则退 2 且无报告。README:45 非 Git 遍历还漏列 `__pycache__`；独立 `walk-scope` 在该目录、`.git`、`.lake` 与普通目录各放一份文本，只有普通目录入报告。当前候选的默认 Git 模式与成功出报告恒 0 均成立。冻结的 `candidate/README.md:11` 说合并“只读”原件、语料、处置，实际 `merge.py:13–15` 还读台账校验 id 序；现行门禁 README:34 的替身说明才是准确的使用指引，不建议改写冻结历史段落。
6. **身份检查已经失败时，不再执行失配的合并脚本。** `check:220–225` 在钉选红后仍调用 `rebuild`，后者在 `:169–183` 拷贝并运行当前的 `candidate/merge.py`。错摘要的良性样本已按合同退非零；这里建议把运行**已确认的**合并工具作为重建前提，而非新增票外阻断或放宽摘要要求。

反向自测的独立对照（仅子层 86 项，不递归套用四个外层断言）：

```sh
python3 -I "$F" meta
```

```text
plain-walk rc 1 自测：86 项，不符 1
unmodified child satisfies four outer verdicts: [True, True, True, True]
plain-git rc 0 自测：86 项，不符 0
no-cross rc 1 自测：85 项，不符 1
bad-reason rc 1 自测：86 项，不符 1
weak-137 rc 1 自测：86 项，不符 1
skip-file-comparison rc 1 自测：86 项，不符 1
wrong-hits rc 0 自测：86 项，不符 0
```

## 核实正确的部分与 README 对照

- **入库忠实性。** 相对指定基点是 59 个 `A`：准入材料 49 个、门禁 10 个，未动 #2312 入口。上游 `SHA256SUMS` 摘要为 `98c4a4db9548d5d162da0ff44c3ef5db43768a4a691e2b43625815b9564b04b0`；剔除 11 个 `errata/` 项后，路径集合恰等于钉选的 47 项。46 项摘要、原始 Git blob 和入库字节均同；`candidate/README.md` 是唯一摘要例外，改标题、原正文逐行不变、末尾追加两处说明。48 项本地摘要均复算相符。当前提交没有带回勘误表或台账。两遍的 README 是逐字节保留的历史原件，不据本审重新判定当时的归属。
- **表和重建。** `fidelity` 独立用区间交集减处置逐行序列化，`rebuilt 790 byte_equal True`。`inputs` 另以冻结提交中的**真台账和原 lib**运行原合并脚本，输出 `rows 790 {'clean': 781, 'trimmed': 9} disputes [743, 760, 778] byte_equal True`。入库门禁的替身也重建零差分。两段裁剪为 137、138、760、778、877、929、1259；单段为 132、743。两字段组合数“分歧未再裁/分歧再裁/一致未再裁/一致再裁”为 2/1/784/3。`candidate/README.md:50–75` 与数据相符。
- **完整性与环境。** README:3–35,37–39 所述正常入口、行数、结构、作者文字摘要、指纹和替身用途与代码相符；身份和目录完整性有 R2-1、R2-2 的例外。独立更改语料文件集合后，`wrong-corpus rc 1`，红行单列语料指纹。钉选与原件同改的剩余信任前提已披露，不列缺陷。两入口及自测均以 `python3 -I` 运行；Python 依赖只有标准库及随附的本地模块，Git 清单模式调用系统 Git。新增门禁脚本无机器绝对路径；历史原件 `pass-b/tools/apply_batch.py:24`（用例）、`export_batches.py:33`（默认值）各保留一处，均与冻结 blob 一致，不在门禁调用链。
- **扫描。** README:43–54 的 Git 模式实跑：扫描 1109，排除准入目录 49、夹具目录 3，未扫描 0，引文 0、未解析 0。在临时 Git 仓，已跟踪和未跟踪未忽略文本均有读数；相似目录 `admit-extra/`、`fixtures2/` 不会搭便车，忽略的文件不入报告。非 UTF-8 和含 NUL 的文件各自列在 `unscanned`，原因为“非 UTF-8”和“含 NUL 字节”。非 Git 回退差异见建议 5。
- **引文读数。** 对 README:56–93，从冻结表的作者区间、边界邻字、同字多现和原文省略号造了 3503 条原样样本，以原行重算每个命中 id 与字符位置。3502 条与独立判据一致，唯一不同是 R2-4。另用非原样样本验证：017:40 被剔除的「“一分为二”」报 `quote_overlaps_excluded_text`，081:42 拼接报 `quote_spliced_across_spans`，表外 017:1 报 `lesson_line_not_in_table`；存在异常时报告仍退 0。同一行两条独立列出。000:26「，归根」给 id 1 `[55,58)` 且 `outside_also=true`；名单外归属字面正确也不计通过。实测边界见 R2-3、R2-4、建议 3–4。
- **自测与维护。** README:97–105 的原样 90 项可运行；四类必红/必报都有独立证据，四个反向断言本身的鉴别力见建议 1。README:107–111 所述本地清单覆盖和原件例外与本提交一致；上游也有同名 `SHA256SUMS`，此处“新增”指目标目录中加入重新生成的清单，并非照搬上游清单。维护 `sources/admit/` 时不应把写了新摘要理解成已获准更新冻结原件。

```sh
python3 -I "$F" pins
python3 -I "$F" inputs
python3 -I formal_math/verification/gate11/check_admit_table.py
python3 -I formal_math/verification/gate11/report_citations.py
python3 -I formal_math/verification/gate11/selftest.py
```

裁决范围：仅 `01cdc3a32a6cbf9ccb9d29529d4218eb3171ff7e` 相对指定基点的入库身份、门禁 11、README 与自测；不重审正文归属，不评判摘句支持何种命题。引文报告保留非阻断定位。

VERDICT: BLOCK
