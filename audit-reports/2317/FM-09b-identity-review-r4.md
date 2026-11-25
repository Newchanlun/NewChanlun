# #2317 身份检查：第四轮非作者复审

被审提交：`b5492c8d7031e7f2e621152a8787bb6ffac32c92`（核对时与 `origin/infra/2317-admit-table` 一致）。模型与档位：`gpt-6.2-astra / xhigh`。

**阻断原因不在材料判定。** 上轮两个原始反例在检查器上都已闭合；未发现只改提交材料、不动 `gate11/` 就能让正常身份检查误绿的情形。本轮有三个可区分的问题：参数解析错误仍能退 120；正确提交的自测在合法 ASCII 环境中途崩溃；README 对 UTF-8 的承诺覆盖了事实上并不按 UTF-8 写出的输出。

依据：[票面「验收」](https://github.com/Newchanlun/NewChanlun/issues/2317)、[第三轮报告](https://github.com/Newchanlun/NewChanlun/blob/b011345e4402a1e9421057b592f7da1765ef7b78/audit-reports/2317/FM-09b-identity-review-r3.md)。下列命令从**本证据分支根目录**运行。夹具中的 `rc` 是父进程取得的被测命令退出码。复跑自测时使用精确候选的独立检出：

```sh
export TMPDIR="$(mktemp -d /Volumes/AgentStorage/identity-r4.XXXXXXXX)"
F=audit-reports/2317/identity-fixtures-r4
G=formal_math/verification/gate11
REV=b5492c8d7031e7f2e621152a8787bb6ffac32c92
git worktree add --detach "$TMPDIR/candidate" "$REV"
```

## 上一轮两条现状

| 上轮阻断 | 本轮在同一场景取得的结果 |
|---|---|
| R3-1：有效命令的 stdout 断管，退 120 | **闭合。** 普通检查与 `--print-pin` 均在子进程启动前关闭管道读端；两者都退 **2**，stderr 都是 `无法运行：[Errno 32] Broken pipe`，无二次刷新报错。stderr 断管时，真正的材料不符仍退 **1**。错误参数走另一条输出路径，见 R4-1。 |
| R3-2：ASCII 编码把正确提交判为 1 | **闭合。** 在上轮的 `en_US.US-ASCII`、普通 `python3 -I` 下，stdout 文本编码确为 ASCII、UTF-8 模式为 0；被审提交退 **0**，stdout 仍可严格按 UTF-8 解出中文 GREEN。同环境下打印钉选与原 blob 逐字节相同，坏版本退 **2**。自测自身的输出另见 R4-2。 |

## 新的可复现阻断缺陷：3 项

### R4-1　错误选项遇到不可写的 stderr，退 120 而非 2

```sh
python3 -IB "$F/process_io.py" parser
```

固定传入不存在的 `--no-such-option`。实际输出：

```text
错误选项 / stderr 普通: rc=2 stdout=b''
错误选项 / stderr 关闭: rc=2 stdout=b'usage: check_admit_identity.py [--root ROOT] [--rev REV] [--print-pin]\n'
错误选项 / stderr 断管: rc=120 stdout=b''
错误选项 / stderr 只读: rc=120 stdout=b''
错误选项 / stderr 满: rc=120 stdout=b''
```

**类别：受审 README:14 明写「命令行参数写错由参数解析器退 2」。** `check_admit_identity.py:109–116` 的 `parse_args()` 在业务处理之前；解析器自行写 Python 文本流，并不经过 `emit/note`。去掉中文帮助不改变这条路径。断管时只给被测解释器加 `-u`，结果从 120 变回 2，区分了参数错误本身与文本流收尾失败。应让解析错误使用可靠的诊断出口，保留文档约定的 2；不能以调用方“反正会阻断”代替这个退出码合同。

### R4-2　自测在可写的 ASCII stdout 上中途抛异常

```sh
LC_ALL=en_US.US-ASCII python3 -I "$TMPDIR/candidate/$G/selftest_identity.py"
echo $?
```

实际 stdout 只有这两项：

```text
ok   worktree-only-changes      rc=0 []
ok   pin-checked-out-crlf       rc=0 []
```

随后 stderr 回溯指向 `selftest_identity.py:164`，末行与 shell 取得的状态为：

```text
UnicodeEncodeError: 'ascii' codec can't encode characters in position 43-54: ordinal not in range(128)
1
```

**类别：未变更的合法提交，在合法环境下运行 README:11 的自测命令不退 0。** 同提交、同一 Python 的 UTF-8 对照运行完整 21 项，不符 0。ASCII 下第三项的预期结果正是带中文诊断的 RED；自测在把该结果打印到自身 stdout 时崩溃，尚未到新增的四项环境测试。这里退 1 的是**自测进程**，不是身份检查器。修复对象是自测进度与总结输出；复验须让外层自测自身处于 ASCII 环境，并实际跑完。

### R4-3　README 把所有输出都描述成了与 locale 无关的 UTF-8

```sh
python3 -IB "$F/process_io.py" encoding
```

前三行是**同一个**错误选项 `--café`，其后是原始参数字节和合法 Git 路径的对照。实际输出：

```text
en_US.UTF-8 错误选项: rc=2 stderr 尾=b'--caf\xc3\xa9'
en_US.ISO8859-1 错误选项: rc=2 stderr 尾=b'--caf\xe9'
en_US.US-ASCII 错误选项: rc=2 stderr 尾=b'--caf\\xe9'
原始 ff 坏选项: rc=2 stderr 含裸 ff=False 含回溯=False
原始 ff 坏版本: rc=2 stderr 含裸 ff=False 含回溯=False
原始 ff 不存在的根: rc=2 stderr 含裸 ff=True 含回溯=False
原始 ff 路径: 普通检查 rc=1; 打印钉选 rc=0; 含原路径=True; 合法 UTF-8=False
```

**类别：受审 README:14「输出按 UTF-8 字节直接写出，与 locale 无关」不成立。** 这里 stderr 可正常写出、退出码也正确，与 R4-1 不同。检查器自己生成的文本经 `emit` 编 UTF-8，孤立代理字符使用反斜杠转义；但解析器按 stderr 的编码写，Git 子进程继承 stderr（检查器:24–26），而 `pin_text` 刻意保留 Git 路径原字节（72–79、93–98）。本机 POSIX 参数中的 `ff` 经 `os.fsdecode` 是 `\udcff`；错误根的 Git 诊断仍可含裸 `ff`。最后一例仅在私有仓库索引加一个文件名含 `ff` 的普通文件，没有修改门禁文件；普通检查正确报红，辅助命令正确保留路径。**首选保留规范钉选的逐字节格式**，把文档的 UTF-8 承诺限定于检查器自己的文本诊断和 GREEN，分别说明 Git 诊断与原始钉选字节；不要为了统一显示而转码路径。

## 非阻断建议：2 项

1. **让四个 I/O 自测区分失败原因。** `selftest_identity.py:168–182` 只判退出码；普通断管又与 ASCII 共用环境。实测换回文本输出后，这一项仍以 2“通过”，原因却是**还没写管道就发生了编码错误**。断管用明确可编码的环境，断言诊断是 EPIPE；ASCII 正例核 GREEN 真能解成 UTF-8，坏版本核运行诊断。详见下表。
2. **检查器可关闭长选项自动缩写。** 当前 `--print-pi` 被解析为合法缩写，实测退 0，stdout 是 49 行钉选而非 GREEN。合同约定参数来自可信调用方而非提交材料；关闭缩写可避免人工误入辅助模式。

## 核实正确的部分

### Git 对象判定没换，重排改变的是故障处理与辅助命令

`git diff 58627d62b2..b5492c8d70 -- formal_math/verification/gate11` 中，`ls_tree`、`tree`、`pin_text`、`corpus_fingerprint` 的函数体、Git 调用和指纹常量均未改。两版 pin blob 为 `a6015b03cbb9bb6565aaea52875d2074b5ac1e4f`，准入树为 `75322d08bfc76ca8ee75387793a2695940467216`，语料树为 `94bf6d7d21c5550d979de20b369dc3a92c6d2e55`。49 项内容和基线指纹复用第三轮对同一对象的证据。

```sh
python3 -IB "$F/control_flow.py"
```

| 私有对象仓库的实际条件 | 普通检查结果 |
|---|---|
| 准入清单、语料指纹同时不符 | 退 1，两条 RED，先准入后语料。 |
| 准入模式非法，语料指纹不符；或两边均有非法模式 | 各退 1、各有两条 RED。第一处 `ValueError` 不妨碍检查第二棵树。两个空子树自测也各退 1；普通检查的局部捕获优先于外层捕获。 |
| 准入已红，随后语料树对象不可读 | 退 2，仍有先前准入的 RED 以及运行故障诊断。 |
| 准入 blob 先不可读，后面的语料有非法模式 | 退 2，没有 RED；恢复同一 blob，不改提交，退 1 并报告语料非法模式。**运行故障会停止后续检查**；每侧也只报首先发现的结构异常，不保证列全坏文件。 |

在仅语料不符的同一提交上，R3、R4 的 `--print-pin` 均退 0，stdout 均逐字节等于候选 pin。准入树本身不能制成清单时，两版**不等价**：准入模式和语料同时有错，R3 辅助命令退 1、两条 RED；R4 直接退 2、只报无法生成及其「非普通文件」原因，stdout 都为空。这个 2 是生成失败，不是把普通门禁的材料不符吞成 2。

### 有效命令的描述符、locale 与自测覆盖

```sh
python3 -IB "$F/process_io.py" status
python3 -IB "$F/process_io.py" locale
python3 -IB "$F/process_io.py" four
python3 -I "$TMPDIR/candidate/$G/selftest_identity.py"
python3 -IB "$F/sensitivity.py"
```

- **输出不可写。** 关闭 stdout、没有读端的管道、以只读方式打开的 fd、容量为零的普通文件、只容许先写 8 字节的普通文件：普通 GREEN 和打印 pin 各五种全退 2，分别报告 EBADF、EPIPE 或 EFBIG，无回溯。macOS 无 `/dev/full`；容量实验只给子进程设 `RLIMIT_FSIZE`，核对落盘字节为 0 或 8，没有填满卷。stderr 在正常、关闭、断管、只读、满五种条件下，相符/不符/坏版本始终分别退 0/1/2；不符且 stdout 关闭也仍退 1。
- **可写但非 UTF-8。** `C -X utf8=0`、`en_US.US-ASCII`、`en_US.ISO8859-1`、`zh_CN.GBK` 下实际 stdout 编码分别为 ASCII、ASCII、ISO-8859-1、GBK；GREEN/pin/坏版本均退 0/0/2，GREEN 为 UTF-8、pin 等于原 blob。在 UTF-8 locale 下另设 `PYTHONIOENCODING=ascii:strict`、`latin-1:replace`、`utf-16`、`not-a-codec`，结果一致：规定入口 `-I` 忽略这个环境变量，实测文本流仍是 UTF-8。
- **候选的 21 项。** 在 UTF-8 下实跑自测，不符 0、外层退 0。另按四项子进程的实际 locale 与 `-X utf8=0` 捕获原始输出：ASCII 正例有 UTF-8 GREEN，退 0；坏版本有 `rev-parse` 运行诊断，退 2；普通断管和 pin 断管都有 `Broken pipe` 诊断，均退 2。四例在**未弱化的候选**上确实由各自声称的原因得到对应状态。

弱化实验从固定提交提取同一对材料树、pin 与自测，重新入库后先比 Git 对象名；只改临时检查器，每个实验从原文重新开始。下表的「自测退 1」均来自具名断言失败而非自测崩溃：

| 单处改动 | 原自测捕获的实际差异 | 自测结果 |
|---|---|---|
| 不比目录集合 | 准入、语料的空子树都误绿 | 2 项不符，退 1 |
| 不查叶文件模式 | 可执行位误绿；同内容链接仍红但诊断错成清单不符 | 2 项不符，退 1 |
| 不比指纹 | 改语料、加语料文件均误绿 | 2 项不符，退 1 |
| 不比钉选 | 改表、在缓存目录加文件、子目录加文件、删文件、pin 加注释均误绿 | 5 项不符，退 1 |
| `emit` 的文本改回 `print`、原始字节改回 `stdout.buffer.write` | ASCII GREEN 退 2；pin 断管退 120。普通 GREEN 断管在自测的 C 环境先因编码失败退 2，切到 UTF-8 后同一弱化才显出断管退 120 | 2 项不符，退 1 |

### README 开头到「两个脚本」之前的逐项对照

| 行 | 主张与核对 |
|---|---|
| 1–7 | 标题是总门禁名称；状态段区分三个身份检查文件与未过审辅助工具。旧 BLOCK 和例子沿用既有证据，本轮不把辅助读数当放行依据。 |
| 9–14 | 两条入口存在。检查器默认 HEAD；`--root` 可覆盖而不认证仓库；自测按脚本位置找根，不解析参数，传 `--root` 也不会改仓库。需要系统 Git 和 Python 标准库。普通检查的 0/1/2 与辅助命令的用途见上；错误参数的 2、输出编码和自测的合法运行环境分别有 R4-1/3/2 的反例。 |
| 16 | 核根为 tree、所有叶为 100644 blob、目录集合恰为实际祖先；按路径字节排序后与**同提交** pin blob 逐字节比，不忽略空行或注释。链接、子模块、执行位、增删文件和空子树均不符。 |
| 17 | 语料目录须平坦，叶为普通 `.md`；指纹常量和计算未动。与所列 shell 命令同值指这份冻结语料，不是任意新文件名的 shell 规范。 |
| 18–19 | 读提交对象，不核磁盘行尾、权限、未跟踪文件；所有检查器 Git 调用都禁用替换引用。下游要读相同字节须选同一完整提交并关闭替换引用，文档已补齐。 |
| 21、23 | 790 条、重建零差分与正文归属是旧审证据；46 个原件加 3 个另列文件为 49 项。未改同一对象，这里不重新证明旧审性质。打印命令复算的是清单。 |
| 25–29 | 同步改 pin 与材料的信任例外有自测；比较内容和模式，不比较 Git 未记录的属主或时间。选库/选版本由可信调用方给定；子进程环境显式固定替换开关与 locale。正常判定不核引文，门禁文件的路径保护是外部条件。 |
| 31、33 | “唯一输入”指引文核对所用的准入表，不是身份检查只读一个文件。与 R3 相比只有检查器、自测、README 变动，总入口未新增接入。两脚本无机器绝对路径；末句关于覆盖根须按第 14 行理解为**检查器**，不适用于自测。 |

上一轮三项建议的实质均已写入第 14、18 行：只把正常检查的 0 当通过；下游固定同一提交和替换开关；根参数只对检查器有效。

## 没覆盖的部分

实测平台为 macOS 26.6.2、Python 3.14.6、Apple Git 2.50.1。没有在 Windows 或托管 CI 上复跑，未重审引文、790 条与重建零差分、权限部署，也未执行或审阅「两个脚本」以下的辅助工具。裁决仅及 `b5492c8d70` 的身份检查器、钉选、自测和上述 README 段。

VERDICT: BLOCK
