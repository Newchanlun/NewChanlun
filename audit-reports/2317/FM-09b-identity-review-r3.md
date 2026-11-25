# #2317 准入材料身份检查：第三轮非作者复审

被审提交：`58627d62b25b5be91081205b82b96907d9a11330`，与远端 `infra/2317-admit-table` 分支头一致。模型与档位：`gpt-6.2-astra`，`xhigh`。

**对象比对保留，输出合同未兑现。** 上轮两项工作区误红在原场景中都已转绿；未发现不改 `gate11/`、仅改提交材料而误绿的情形。阻断本轮的是两个可区分的输出问题：断管使进程退 120；合法 ASCII 环境使相同材料退 1。后者会被误读成材料变了。裁决依据是 [#2317 现行验收](https://github.com/Newchanlun/NewChanlun/issues/2317)和受审 README:14 的明确承诺。

以下命令从**本证据分支根目录**执行。夹具用固定被审提交，不拿后来提交的报告作基线。`rc` 是被测子进程的实际退出码，不是夹具自身的退出码。

```sh
export TMPDIR="$(mktemp -d /Volumes/AgentStorage/fm09b-r3.XXXXXXXX)"
F=audit-reports/2317/identity-fixtures-r3
G=formal_math/verification/gate11
REV=58627d62b25b5be91081205b82b96907d9a11330
```

## 前两轮各条现状

| 历史问题 | 本轮判定与区分证据 |
|---|---|
| 首轮 B1：钉选被检出转换干扰 | 已闭合。`check_admit_identity.py:104–106` 从解析后的提交取 pin blob。只提交根属性时，磁盘钉选为 CRLF、对象为 LF，仍退 0；提交钉选本身多一行注释则退 1。 |
| 首轮 B2：空子树漏检 | 已闭合。准入和语料各添一个只有目录节点的 `archive`，都退 1 并点名各自目录。只撤目录集合核对，两例都意外转绿，原自测随即失败。 |
| 首轮 B3：磁盘执行位；B4：磁盘根或祖先链接 | 两条旧合同均已撤销，不计作仍在保护的能力。`disk_problems`、其调用、`stat`、路径分量检查、目录遍历、读盘及 `--no-worktree` 全部删除；剩余文件类型和模式检查只处理 Git 条目。自动找仓库根不是遍历材料。已提交的执行位或链接仍各退 1。 |
| 二轮 R2-1：组执行位误红 | 已闭合。完整分离检出，`core.filemode=true`；同一个 `SPEC.md` 从 0644 到 0654，Git 状态仍空、索引仍是 100644、磁盘字节等于 blob，检查两次都退 0。 |
| 二轮 R2-2：普通 CRLF 克隆误红 | 已闭合。完整新克隆首次按 `core.autocrlf=true` 检出精确被审提交，状态为空，`SPEC.md` 显示 `i/lf w/crlf`，磁盘字节确实不等于 blob，检查仍退 0。它证明的是**提交**相同。 |

二轮四条建议的去向：① 不可读对象和启动时无 stdout 已归到 2，输出错误仍未完全归类，见下节；② 工作区路径缺失随合同撤销，**提交里**少叶文件或整个受检根则实测都退 1；③ 自测现在和检查器一样只剥一个终止换行、用 `os.fsdecode`，在目录名以换行收尾的真实分离关联工作树，两条入口实跑均退 0，自测 17 项全过；④ README:10、14 已列系统 Git 和受信任的根参数，第 33 行的适用对象仍可说准。

原报告：[首轮](https://github.com/Newchanlun/NewChanlun/blob/b15311d14720c4d4e3c71f8a70f8c9f23ef06398/audit-reports/2317/FM-09b-identity-review.md)、[二轮](https://github.com/Newchanlun/NewChanlun/blob/d0e923ed1b6720e4e8046b3c9fa8bb934dd79285/audit-reports/2317/FM-09b-identity-review-r2.md)。复验检出条件与四个应绿用例的实际状态：

```sh
python3 -IB "$F/checkouts.py"
python3 -IB "$F/green_controls.py"
```

## 新的可复现阻断缺陷：2 项

### R3-1　写入断管，进程实际退 120，不是 2

```sh
python3 -IB "$F/output_status.py" green print-pin no-stdout
```

夹具在启动子进程**之前**关闭输出管道的读端，避免与读者退出的时序竞争。实际输出：

```text
green: rc=120
无法运行：[Errno 32] Broken pipe
Exception ignored while flushing sys.stdout:
BrokenPipeError: [Errno 32] Broken pipe
print-pin: rc=120
无法运行：[Errno 32] Broken pipe
Exception ignored while flushing sys.stdout:
BrokenPipeError: [Errno 32] Broken pipe
no-stdout: rc=2
无法运行：标准输出不可用
```

`check_admit_identity.py:136–145` 捕获了第一次错误并设置 2，却把仍有待写内容的损坏输出流留给解释器关机时再次刷新；父进程实际收到 120。启动时没有 stdout 的对照能退 2，说明新分支有效，但不能处理已经打开而后不可写的流。另用 `python3 -IB "$F/object_errors.py"` 对确实少文件的提交关闭 **stderr** 读端：正常诊断退 1，断管时输出 `同一不符，stderr 只有写端: rc=120, stdout=b''`。错误处理也不能依赖再次写同一条已损坏的诊断流。

**类别：README:14 明写“输出写不出”退 2，实际未做到。** 断管退 120 是二轮建议 1 已记录的症状；本轮修改了实现并在 README 明确承诺了该场景，故升级为阻断，不是新发现的材料漏检。应让输出失败后的清理不能覆盖进程退出码；验收读父进程拿到的状态，同时覆盖普通输出与二进制钉选输出。

### R3-2　stdout 可写但编码为 ASCII，正确提交被报成身份不符

在本机已安装的 `en_US.US-ASCII` locale 下，使用 README 的普通 `python3 -I`，没有替换 Git、注入 Python 模块或关闭描述符：

```sh
LC_ALL=en_US.US-ASCII python3 -I -c 'import sys; print(sys.stdout.encoding, sys.flags.utf8_mode)'
LC_ALL=en_US.US-ASCII python3 -I "$G/check_admit_identity.py" --rev "$REV"
echo $?
```

第一条输出 `ascii 0`。检查器的回溯末行和随后的退出码：

```text
UnicodeEncodeError: 'ascii' codec can't encode characters in position 7-10: ordinal not in range(128)
1
```

同一提交在普通 UTF-8 输出下退 0，报 49 个准入文件、110 个语料文件。`check_admit_identity.py:131–132` 是所有比对通过后才走到的 GREEN 输出；生成中文提示时失败，异常既不在两个材料判定的 `try` 内，也不属于外层捕获的 `OSError/CalledProcessError`。给 Git 子进程固定 `LC_ALL=C` 并不改变 Python 自己的输出编码。

**类别：合法环境把未变提交判成 1，同时违反 README:14 的退出码划分。** 首选让合法可写输出能表达结果，正确提交仍退 0；如果消息确实无法输出，也只能归运行错误 2，不能以未捕获的回溯退 1。

## 非阻断建议：3 项

1. **给调用方一句可执行的规则：正常检查只有 0 放行，所有非零都阻断；`--print-pin` 不是放行命令。** 实测仅缺准入文件退 1；在同一提交上再让语料树对象不可读，退 2 且不输出之前积累的 RED 行。后者确有运行故障，2 不代表“材料没问题，可以跳过”。
2. **把下游读数绑定到同一个完整提交号，并关闭替换引用。** README:18 已写明检出字节不受保障；仍可能误以为普通 `git cat-file` 就足够。原自测的替换样本里，普通 Git 和磁盘读到同一份替换字节，检查器却正确认定原对象。第 18–19 行应把这个条件也交给下游，而不是恢复磁盘检查。
3. **把 README:33 的 `--root` 明确限定为检查器参数。** 第 10–11 行的命令已作区分；自测按脚本位置定位，不解析命令行，给它传 `--root` 不会换仓库。

## 核实正确的部分

**提交一侧没有换判据。** `git diff 106ace51a1..58627d62b2 -- formal_math/verification/gate11` 显示检查器增 10 行、删 55 行；`ls_tree`、`tree`、`pin_text`、`corpus_fingerprint` 函数体逐行未变。`main:99–130` 中版本解析、同提交取 pin、两个 `tree` 调用、规范文本和指纹的比较、`ValueError` 归红及输出顺序均未变。删去的是这些判定之后的工作区核对和它的开关。入口另加 stdout 可用性检查、显式刷新与外层运行错误处理；这会改变进程退出行为，不是纯删除。

两版的 pin blob 均为 `a6015b03cbb9bb6565aaea52875d2074b5ac1e4f`，准入树均为 `75322d08bfc76ca8ee75387793a2695940467216`，语料树均为 `94bf6d7d21c5550d979de20b369dc3a92c6d2e55`，指纹常量无差异。49 项内容及基线值复用原审，不重算。二轮对同一对象逻辑的深度 1 分离合并检出、子模块、路径边界证据仍适用。

**返回状态。** 除上列输出缺陷，实际可区分“提交少了材料”和“对象库读不到已有对象”。在私有对象库中分别暂时移开 pin blob、准入 blob、语料 tree，调用方取得的都是 2；不存在的 `--rev`、启动时无 stdout 也退 2。反之，在可读的提交中少 `SPEC.md`、少准入目录、钉选文本或指纹不符均退 1；显式选择之前的正常提交退 0。没见到纯材料变化被当成 2。混合故障见建议 1。`--print-pin` 正常时输出的字节与 pin blob 相同，它在准入树处理后即返回，不验语料，也不证明钉选匹配。

```sh
python3 -IB "$F/object_errors.py"
python3 -IB "$F/output_status.py" bad-rev
```

### 原版 17 项：不是靠无关失败变红

在完整被审检出运行 `python3 -I "$G/selftest_identity.py"`：**17 项，不符 0，进程退 0**。下表中红例均为 1、绿例均为 0。四个具名绿例另用 `green_controls.py` 检查了实际状态及 GREEN 输出。

| 用例 | 实际原因 |
|---|---|
| 干净阴性对照 | 两棵提交树与基线相同。 |
| worktree-only-changes | 表字节、`SPEC.md` 磁盘模式、未跟踪 `.DS_Store` 都变了；HEAD 没变。 |
| pin-checked-out-crlf | 实际提交仅改根属性；磁盘 pin 是 CRLF，同提交 pin blob 仍是 LF。 |
| empty-subtree-corpus；empty-subtree-admit | 分别点名语料、准入根下“不含文件的目录” `archive`。 |
| table-byte | 表的首字节改变，报准入材料“与钉选”不同。 |
| symlink-same-content | 目标文件字节相同；报的是 `120000 blob …/SPEC.md` 非普通文件。原样本另在门禁目录放目标副本；首轮已有目标放在门禁外的对照，本轮类型判断未改。 |
| tracked-in-pycache；extra-tracked | 分别新增受跟踪的 `__pycache__/errata.jsonl` 和 `candidate/extra.md`；两者都报准入清单不符。 |
| delete-file | 提交少了 `SPEC.md`，报准入清单不符。 |
| exec-bit | 报 `100755 blob …/candidate/merge.py` 非普通文件。 |
| corpus-byte；corpus-extra-file | 分别改一份课文、增加 `999-x.md`；两者都报语料指纹不等于基线。 |
| corpus-subdir | 报语料目录意外条目，具体为 `sub/a.md`，不是空树判断。 |
| pin-comment-line | pin 新增注释行，规范文本逐字节比较失败。 |
| git-replace-object | 替换生效且检出字节也变了；检查器显式关闭替换，看见真实提交。 |
| table-and-pin-synced | 只改表的父提交退 1，随后同步钉选退 0；两个步骤合计只改表与 pin，符合已声明的信任边界。 |

**四次独立弱化都被原自测抓到。** `python3 -IB "$F/sensitivity.py"` 每次从同一检查器原文只撤一项判断；固定两棵树和原 pin，自测脚本不改。每次原自测进程都退 1：

| 撤掉的判断 | 失败用例 | 不符数 |
|---|---|---:|
| 目录集合 | empty-subtree-corpus、empty-subtree-admit 都意外转绿 | 2 |
| 模式判定 | exec-bit 意外转绿；symlink-same-content 仍红，但错报成清单差异 | 2 |
| 指纹比较 | corpus-byte、corpus-extra-file 意外转绿 | 2 |
| 钉选比对 | table-byte、tracked-in-pycache、extra-tracked、delete-file、pin-comment-line 意外转绿 | 5 |

### README 开头至「两个脚本」之前

| 行 | 对照结果 |
|---|---|
| 1–5、7 | 标题是门禁总题，状态段明确只有三个身份检查文件送审。旧工具的 BLOCK 和已知问题对应既有报告；未把旧工具当作验收依据。 |
| 9–14 | 两条命令存在。默认 HEAD、系统 Git、可覆盖且受信任的根均与实现相符；第 14 行的输出错误承诺有 R3-1、R3-2 两个反例。 |
| 16 | 先验根为树；列全条目，叶必须是 100644 普通 blob；目录集合须等于叶路径所需祖先。清单按路径字节序，逐字节比较同一提交的 pin，注释和空行不被忽略。 |
| 17 | 语料同样取对象；须平坦、仅 .md，空子树也红。与所列 shell 指纹的等价性是对这份冻结语料的既有证据。 |
| 18–19 | 明写不保证磁盘字节；新检出指检出的是哪个提交，不等于磁盘字节未转换。更换行尾、权限、未跟踪物不改提交结论；所有检查器 Git 子进程确实关闭替换引用。下游取同一版本的要求见建议 2。 |
| 21、23 | [#2316 实物审记录](https://github.com/Newchanlun/NewChanlun/issues/2316#issuecomment-7166555103)指明 790 条可重建、PASS 只及正文归属。46 个原件加 3 个说明或摘要文件的 49 项口径沿用同 blob 的原审；打印命令是准入清单复算，不是独立放行。 |
| 25–29 | 同步换 pin 与材料的信任前提有正对照；比 Git 模式和内容、不比时间或属主。CI 提供选库和版本，脚本仅覆盖 Git 子进程的替换开关和 locale。不核引文，路径权限也是外部前提。 |
| 31、33 | “唯一”限定在引文工具的准入表。未接总入口，`run_gates.py` 不是此次改动；运行方式、标准库依赖和脚本内无机器路径均相符。`--root` 的适用范围见建议 3。 |

## 没覆盖的部分

实测平台为 macOS、Apple Git 2.50.1、Python 3.14.6；没有在 Windows 或托管 PR runner 上复跑。没有重审引文、重算 790 条与重建零差分、审路径权限的部署，或执行 README「两个脚本」以下的辅助工具。未把磁盘被改后仍绿列为缺陷。

**裁决范围：**仅限 `58627d62b2` 的 #2317 身份检查、pin、自测和上述 README 段。修复两个输出分支后，可保留本轮的对象比对和材料证据；复审以合法输出环境、关闭的管道及父进程拿到的退出码为准。

VERDICT: BLOCK
