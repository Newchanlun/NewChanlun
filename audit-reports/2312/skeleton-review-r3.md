# #2312 第二片（运行骨架）独立复审 r3

- 被审提交：`origin/infra/2312-f-skeleton` @ `14fc96c4b236c468ce57c3427e4b78ceeb29f9fe`（从 main 起检出后 `git rev-parse HEAD` 相符）。上一轮被审 `1ea21f7206eb2f944d5e0a68dff915508fb83c87`。
- 审阅者：非作者、独立进程、只读审阅（没有改被审分支，没有评论或修改任何 issue，没有开 PR）。模型 Claude Fable 5.2（`claude-fable-5-2`），会话给定的推理档位参数为 30，没有显示具名档位。没有起子代理。
- 环境：SafeCode Linux（内核 7.0.0-38-generic，xfs，6 核），`bwrap` 0.11.1，Lean 4.36.0，Python 3.14.4。所有调用 `lake`、`lean` 的命令都包在 `flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh` 里，先 `source scripts/fm_env.sh`。工作目录 `/home/workspace/fm/tmp/review-f3/`。
- 范围、已明示前提、阻断四类与高低档的定义沿用前两轮报告（`origin/evidence/2312-skeleton-review` @ `7ce9e02c01698b486ad036fd072f7b621344afde` 的 `skeleton-review-r1.md`，`origin/evidence/2312-skeleton-review-r2` @ `913b5a5dc31c60d66b9384b405b944740232e5e3` 的 `skeleton-review-r2.md`）。本轮严重程度按简报：**高** = 能拿到退出码 0、能改变哪个审计二进制被执行、或能让被审内容写到声明范围之外；**低** = 只影响 1 与 2 的区分、日志可读性、极端环境下结果行缺失、说明措辞与计数。
- 受审文件：`formal_math/verification/runner/` 的 `run.py`、`selftest.py`、`README.md`、`fixtures.tsv`、`selftest-cases/`。本轮改动 `git diff --numstat 1ea21f7206..14fc96c4b2 -- formal_math/verification/runner`：`README.md` 44/13、`run.py` 147/57、`selftest.py` 209/42（增/删），`fixtures.tsv` 与 `selftest-cases/` 未动。
- 范围外已核：`git diff 1ea21f7206 14fc96c4b2 -- formal_math/verification/auditor` 为空（环境层没有动，维持 r1 的 PASS）；`git diff 59504398f4 14fc96c4b2 -- formal_math/verification/precheck` 为空（本轮合并进来的就是四轮独审 PASS 的那一版，当黑盒）。
- 夹具与日志：同目录 `skeleton-r3-fixtures/`，日志在其中的 `logs/`。

## 一、结论

| 项 | 结果 |
|---|---|
| 上一轮 N-1（不带 `-I` 且某路写不出时冒名模块被执行、可退 0） | 闭合 |
| 上一轮 N-2（第 6 步产物核对可绕过） | 闭合 |
| 上一轮 N-3（信号归类的说明比实际宽） | 闭合（只改说明，改后的说明与实际逐例相符） |
| 上一轮 N-4（结果行契约在两条路径上不成立） | 闭合；新契约的三句话在我能构造的路径上都成立，只剩两处极端环境下的残留，列为条件项 |
| 新的高项 | **0 条** |
| 条件项（低） | 3 条：C-1、C-2、C-3（说明细节清单） |
| 非阻断建议 | 7 条 |

**骨架：PASS（带条件）。**

送审主问题（被审提交能否影响哪个审计二进制被执行，或经声明之外的通道影响它的输入）第三轮仍然没有被击穿。本轮最大的新增面——第 6 步的产物形状表——我两头都查了：

- **漏**：表内合法名字能承载的东西我试了九类（内容替换、`.olean.private` 换成另一个模块的产物、`.ilean`/`.trace`/`.c`/`.setup.json` 内容替换、硬链接、3 GB 稀疏文件、`.lake/config` 下自造合法名字、表内硬链接、只读与 0600 模式）。形状表确实不查内容、大小与链接数，这正是说明已明示不防的那一条；但没有一类能让被审内容流到声明范围之外，也没有一类能让第 7 步读到 `ctx.modules` 之外的模块。硬链接出不去 `.lake`（`EXDEV`，errno 18），沙箱里 `CapEff` 全零、`mount` 与 `unshare` 都被拒。
- **误红**：八种真实构建情形（单模块、多级目录、`deriving`/`instance`/`structure`、`@[expose] public section`、增量构建、无改动重建、构建失败后重跑、`--wfail` 告警）产出的 16 种后缀全部在表内，零误红；另有 38 项单元矩阵逐项核对（第六节）。
- **遍历与第 7 步之间没有时间窗**：`--die-with-parent` 下沙箱里刻意留下的后台进程在 `sandbox()` 返回前后数百微秒内即止，而遍历只要约 0.3 ms；遍历结束后不再有写入，没有残留进程。

三条条件项都不改变判定方向：两条是「极端环境下没有结果行」（标准错误阻塞；绿行写完到进程退完之间的信号窗），一条是说明细节与计数。前两条都拿不到退出码 0——C-1 根本产生不出退出码（进程卡住），C-2 的退出状态是「被信号 15 终止」。

## 二、上一轮四条复验

每条都用上一轮的夹具加至少两种新形状。

### N-1：闭合

**改法**（`run.py:11-19`）：`import posix`，两行诊断各包在 `try/except BaseException` 里，然后 `posix._exit(2)`。

**上一轮的夹具**（`case_not_isolated_stderr.sh` 的六种状态）在新的 `case_isolate3.sh`、`case_isolate3b.py` 里重做并扩到 **12 种流状态**，退出码用 `fork` + `execv` + `waitpid` 直接取（上一轮我用 shell 包装，管道与 `echo` 会吃掉 `$?`；本轮先踩了同一个坑，日志 `case_isolate3.txt` 里那几个 `rc=0` 是 shell 的，不是 `run.py` 的，`case_isolate3b.txt` 才是准的）。同目录放了 **21 个冒名模块**（`re`、`json`、`os`、`sitecustomize`、`usercustomize`、`traceback`、`posix`、`sys`、`signal`、`stat`、`time`、`hashlib`、`subprocess`、`unicodedata`、`codecs`、`encodings/__init__.py`、`io`、`abc`、`warnings`、`linecache`），每个被执行就记一笔并往标准输出写一行伪造的 `FM RESULT GREEN` 再以 0 退出。

| 不带 `-I` 的流状态 | `run.py` 自己的退出码 | 冒名模块 |
|---|---|---|
| 两路正常 | 2 | 一个都没执行 |
| 标准输出关闭 / 标准错误关闭 / 两路都关 | 2 / 2 / 2 | 一个都没执行 |
| 标准输出 `/dev/full` / 标准错误 `/dev/full` / 两路 `/dev/full` | 2 / 2 / 2 | 一个都没执行 |
| 标准输出读端已关管道 / 标准错误读端已关管道 / 两路都是 | 2 / 2 / 2 | 一个都没执行 |
| 标准输出关 + 标准错误管道 / 标准输出 `/dev/full` + 标准错误关 | 2 / 2 | 一个都没执行 |

**冻结模块与内建模块的区别**（简报问的那一点）：`"sys" in sys.builtin_module_names` 与 `"posix" in sys.builtin_module_names` 都为真，`"os"` 为假；`posix.__spec__.origin` 与 `sys.__spec__.origin` 都是 `built-in`，`posix.__loader__` 是 `_frozen_importlib.BuiltinImporter`，所以同目录的 `posix.py`、`sys.py` 顶替不了它们——这与作者自述一致，我直接问解释器核实过。

**其它启动方式**：`-m run`（不带 `-I`）、`-P`、`PYTHONSAFEPATH=1`、`-E -s`、经符号链接路径运行（链接所在目录干净）、绝对路径且当前目录是冒名目录，都是 `NOT_ISOLATED` 退 2，冒名模块没有被执行。

**带 `-I` 时脚本目录在不在 `sys.path`（简报特别问的）**：不在。实测 `python3 -I` 的 `sys.path[0]` 是 `/usr/lib/python314.zip`，`sys.path` 里没有脚本目录也没有当前目录。所以「受信目录里取出的 `run.py` 旁边有哪些文件」这一问在带 `-I` 时不成立：那些文件进不了模块搜索路径。顺带核过受信目录的来源——第 2 步只写受信提交 `formal_math/verification/` 整棵树，每条路径段须合 `[A-Za-z0-9_][A-Za-z0-9_.-]*`、模式须是 `100644` blob，全部来自受信提交，没有被审一侧的东西。第 1 步取出的 `precheck.py` 写在 `<工作目录>/step1/`，也以 `python3 -I` 运行，同理。

**检查通过之后、`RUNNER_MISMATCH` 之前这段导入了什么**：`hashlib`、`json`、`os`、`re`、`signal`、`stat`、`subprocess`、`time`、`unicodedata` 九个，全在 `sys.flags.isolated` 为真之后，搜索路径里已没有脚本目录与当前目录；这段只读 `os.environ`、`sys.argv` 与 `__file__`，被审内容还没有被解析过。

**仍留在 `-I` 之外的（不是本片能兜的，与上一轮建议 9 同类）**：`python3 -c "import sys"` 或 `python3 -c "exec(open('run.py').read())"` 在冒名目录里跑时，解释器启动阶段就从当前目录取了 `linecache.py` 并执行它（`PYTHONVERBOSE` 显示 `__pycache__/linecache.cpython-314.pyc matches …/dir/linecache.py`），发生在 `run.py` 第一行之前。按脚本路径调用（`python3 run.py`）则一个冒名模块都不执行。README 已写明「只能按脚本路径调用」「`python3 -I -m run` 不受支持」，建议把 `-c`/`exec` 也并进那一句（见建议 5）。

### N-2：闭合

**改法**：第 6 步对被审构建可写的整个 `.lake` 用 `lstat` 递归遍历、不跟随链接、不可列出判红，逐项过形状表（`run.py:551-609`）。

**上一轮的两个绕过原样重做**（`case_shape3.py` 的 B 组，真实命令行入口、lite 基线配自建假依赖目录）：

| 上一轮的绕过 | 本轮结果 |
|---|---|
| 名字带多余点的 `.olean`（`Chan/Base.olean.hash.hash`） | `EXTRA_ARTIFACT` |
| 模式 0111 的目录（`ChanDyn` 改 0111，自测 S20 覆盖） | `ARTIFACT_FORM` + 该模块 `NO_ARTIFACT` |

**新形状**（B 组一次运行里八项，逐项比对（红码，路径））：只差大小写的 `Chan/base.olean`、西里尔同形名 `Chan/Bаse.olean`、后缀叠加 `Chan/Base.olean.hash.hash`、隐藏名 `Chan/.Base.olean`、不是模块前缀的目录 `Chan/Base/`（其下的 `Inner.olean` 不再单独报，与说明「表外的目录不再往下走」一致）、`.lake` 内硬链接到表外名字 `Chan/Hard.olean`、`config/88/other.olean`、`build/lib/extra` —— 八项全部 `EXTRA_ARTIFACT`，退 1。

**漏的那一头（表内合法名字能承载什么）**，`case_shape3.py` A 组 + `case_shape3b.py` + `case_hardlink_exact.py`：

| 试的东西 | 形状表 | 后果 |
|---|---|---|
| `.ilean`、`.trace`、`.c`、`.setup.json` 内容换成任意字节 | 放行（退 0） | 第 7 步不读这些文件，无后果 |
| `.olean.private` 换成另一个内容模块的产物 | 放行（退 0） | 第 7 步按私有层级读它，属**已明示不防**的「产物内容伪造」 |
| 硬链接到宿主机只读根上的文件（`/etc/hostname`、`/usr/bin/env`） | — | `link()` 返回 `EXDEV`（errno 18），建不成 |
| 硬链接到被审工作区（只读绑定）的源码 | — | 同样 `EXDEV` |
| 硬链接到宿主机工作目录里的金丝雀 | — | 路径在沙箱里不存在（被 tmpfs 盖住） |
| `.lake` 之内互相硬链接（表内合法名） | 放行 | 同一挂载，建得成，但没有新能力 |
| 3 GB 稀疏的表内合法名 | 放行 | 实占 8 块，不吃盘；形状表不查大小 |
| `.lake/config/77/lakefile.olean` 由被审构建自造、内容伪造 | 放行 | 本次运行没有读它的一方（第 7 步不读 `.lake/config`），而 `--workdir` 必须不存在或为空，所以不会有下一次构建把它读进来 |
| 表内合法名改成 0400、0600；表内目录改 0700 | 放行 | 与真实构建一致 |

宿主机一侧逐项核对：金丝雀文件内容未变、`/etc/hostname` 未变、被审工作区的源码未变、`/etc/fm-probe` 不存在、依赖挂载点写不进。沙箱里 `CapEff:0000000000000000`，`mount -t tmpfs` 报「must be superuser」，`unshare -m` 报「Operation not permitted」。

**遍历与第 7 步之间的时间窗**（简报问的）：没有。`race_probe.py` 用被审 `run.py` 自己的 `sandbox()` 与 `artifact_reds()`，顺序与 `step_build` 相同，沙箱里的「构建」摆好合法产物后留一个 `setsid` 并关掉三路的后台进程不停写表内文件。八次实测：遍历耗时 250–381 µs；后台进程最后一次写入相对 `sandbox()` 返回为 −1394 µs 到 +512 µs、相对遍历结束全部为负（最接近的一次 +148 µs 仍在遍历期间）；0.5 秒后一律不再写。沙箱用了 `--unshare-all`（含 pid 命名空间）与 `--die-with-parent`，`bwrap` 一退出整个 pid 命名空间被内核回收。另核八次运行后没有残留进程。

### N-3：闭合（只改说明）

**改后的说明**（`README.md` 第 62 行「沙箱布局」与第 45 行表）：只有运行脚本在沙箱里直接启动的那个进程以 ≥128 或负退出码结束才归 `SIGNAL` 退 2；`lake` 启动的 `lean` 工作进程被杀时 `lake` 记成构建失败自己以 1 退出，运行脚本报 `BUILD_WFAIL` 退 1。

逐例实测（`case_signal3b.py`，真实命令行入口）：

| 构建期做什么 | 结果 | 与改后的说明 |
|---|---|---|
| `kill -KILL $PPID`（杀正在编译自己的 `lean`） | `BUILD_WFAIL` 退 1，日志 `FM LOG build error: Lean exited with code 137` | 相符 |
| `kill -KILL 2`（杀沙箱顶层的 `lake`） | `FM FAULT build SIGNAL lake 沙箱内进程被信号终止（退出 137）`，退 2 | 相符 |

两例都恰好一条结果行。

### N-4：闭合，剩两处极端环境下的残留（条件项 C-1、C-2）

**改法**：`finish()` 整次运行至多写一次、单次 `os.write`、长度上限 4096（= Linux 的 `PIPE_BUF`）；写不出则退出码改 2 且不补写；绿之前先查 `STATE["output"]`；装了 SIGINT、SIGTERM 处理函数；子进程 `start_new_session=True` 各自成组，超时与信号都按组杀。

**新契约三句在我能构造的路径上**（`case_signal3.py`、`case_signal3b.py`，每次运行都逐条核对三句）：

| 路径 | rc | 结果行 | 至多一条 | 绿则 0 | 0 则恰一条绿且在最后 |
|---|---|---|---|---|---|
| 第 1 步（`prepare`）期间 SIGTERM | 2 | `FM RESULT FAULT prepare SIGNAL` | ✓ | ✓ | ✓ |
| 第 1 步判红期间 SIGINT（信号晚于判红） | 1 | `FM RESULT RED 第 1 步 …` | ✓ | ✓ | ✓ |
| 第 6 步构建期间 SIGTERM / SIGINT | 2 / 2 | `FM RESULT FAULT build SIGNAL` | ✓ | ✓ | ✓ |
| 处理函数里再被打断（第二次 SIGINT 紧随其后） | 2 | 仍只一条 `FM RESULT FAULT build SIGNAL`，标准错误也只一条 `FM FAULT` | ✓ | ✓ | ✓ |
| 超时与信号同时（第 6 步时限改 10 秒，第 12.4 秒 SIGTERM） | 2 | `FM RESULT FAULT build BUILD`（超时先到） | ✓ | ✓ | ✓ |

**子进程组与孤儿**：以上各例运行后都没有残留进程（`ps` 比对前后差集为空；日志里出现的 `bwrap` 是宿主机上无关的 glycin 图片加载器，不是流水线起的）；第 6 步被打断后 `.lake/tick` 字节数不再增长（SIGTERM 5→5、SIGINT 10→10、双信号 10→10、超时 225→225）。`on_signal` 杀的是 `STATE["child"]` 的进程组，也就是 `bwrap` 那一组；`--new-session` 让沙箱里的进程另成会话，但 `--unshare-all` 的 pid 命名空间加 `--die-with-parent` 保证 `bwrap` 一死整个命名空间被回收，所以不需要再追着杀。

**处理函数的可重入性**：`finish()` 在写之前就把 `STATE["result"]` 置真，所以处理函数里再被打断、或处理函数与主路径竞争时都不会出现第二条结果行——这一点是对的，次序没写反。

剩下的两处残留见第四节 C-1、C-2。

## 三、新的高项

**0 条。** 本轮没有找到能拿到退出码 0、能改变哪个审计二进制被执行、或能让被审内容写到声明范围之外的缺陷。

上一轮两条高项的位置都重点查过：隔离检查扩到 12 种流状态 × 21 个冒名模块仍然退 2 且一个冒名模块都不执行；形状表的漏与误红两头各试了九类与八种情形加 38 项单元矩阵，没有一类能让第 7 步读到 `ctx.modules` 之外的模块、也没有一类能把内容写出 `.lake`（硬链接 `EXDEV`、`CapEff` 全零、`mount`/`unshare` 被拒）。

## 四、条件项（低）

三条都不构成 BLOCK。按简报，列为放行前须修正的条件项，逐条写明修正后是否需要再审。

### C-1 标准错误写不出去时整次运行卡死，连结果行与退出码都没有

**类别**：极端环境下结果行缺失。**档**：低（拿不到退出码 0——根本产生不出退出码）。**谁可控**：调用方（给了一个没人读的标准错误）。**是否还需伪造产物**：无关。

**说明里的陈述**（`README.md` 第 105 行）：「被 SIGINT、SIGTERM 打断时，处理函数杀掉正在运行的子进程组，**尽力写**一行 `FM FAULT` 与 `FM RESULT FAULT <步骤> SIGNAL`，以 2 退出」。

**实际行为**：`emit()` 的写循环（`run.py:101-102`）是阻塞的 `os.write`。标准错误是满的、读端不读的管道时它永远返回不了。第 3 步的 `FM LOG auditor Build completed successfully` 就能把运行脚本钉在那里。更要紧的是 `on_signal()`（`run.py:739-745`）**先** `emit(2, "FAULT", …)`、**后** `finish(…)`：这时发信号，处理函数本身也卡在 `emit` 上，结果行写不出去，进程既不结束也没有退出码；再发第二次信号同样卡住。

**复现**（单元级，不跑 `lean`，`case_blocked_stderr.py`）：

```
emit                 **8 秒内没有结束（卡住）**，此前的标准输出=''
signal               **8 秒内没有结束（卡住）**，此前的标准输出=''
signal-reordered     8 秒内结束：rc=0 标准输出='FM RESULT FAULT build SIGNAL\n（对照）先写结果行后它出来了\n'
```

第三行是对照：同样的阻塞标准错误下，只要先写结果行，结果行就能出来。整条流水线上也撞到过——`case_signal3.py` 最后一例（标准错误是满管道 + 第 6 步 SIGTERM）把运行脚本挂住，我手动停掉的。

**后果**：调用方拿不到任何结论，也等不到进程结束。方向是安全的（不会落成 0 或 1），但「尽力写」这个词现在并不成立：卡住不是「写不出就跳过」。

**修法**（二选一）：
- 改代码：`on_signal()` 里把 `finish()` 挪到 `emit(2, …)` 之前；或 `emit` 对标准错误改用非阻塞写/带上限的重试。**需要再审**（改的是新装的信号处理路径，范围可限于 `on_signal` 与 `emit`）。
- 只改说明：写明标准错误写不出去（阻塞）时运行脚本可能卡死、不产生退出码，调用方须自己设超时。**无需再审，由主控核对差异即可。**

### C-2 绿结果行写完之后、进程退完之前收到 SIGINT/SIGTERM：处理函数已不生效，进程被信号终止，绿结果行留在标准输出

**类别**：退出码契约、说明不实。**档**：低（**拿不到退出码 0**，退出状态是「被信号 15 终止」；方向安全）。**谁可控**：调用方（在这个时刻发信号）。**是否还需伪造产物**：不需要，但也改变不了任何内容判定。

**说明里的陈述**（`README.md` 第 105 行）：「**有绿结果行则退出码为 0**」；以及「被 SIGINT、SIGTERM 打断时……以 2 退出」。

**实际行为**：主路径写完绿结果行后 `main` 返回 0，`__main__` 走 `raise SystemExit(0)` 进解释器收尾。收尾阶段 Python 已把信号处置交还默认值，这时到达的 SIGTERM 既不触发 `on_signal`（标准错误上没有 `FM FAULT`），也不走 `finish`，而是按默认处置直接终止进程。

**复现**（`case_green_signal.py`，真实命令行入口，只用调用方一侧的手段）：标准输出接管道，父进程读到 `FM RESULT GREEN` 那一行的瞬间立刻 `kill(SIGTERM)`——写已经完成，所以信号必定落在绿行之后。**16 次里 15 次**：

```
第  0 次：rc=-15 绿结果行=1 结果行共 1 条 发信号=打中 → 「有绿则退 0」**不成立**
     标准输出末两行=['FM STEP 7 env GREEN 0.3s 7 个模块，0 条锁行', 'FM RESULT GREEN 七步全绿（第 5 步源码形状未安装）']
     标准错误里的 FM FAULT=[]
```

剩下 1 次是子进程已经退完、没打中（`rc=0`）。

**与上一轮的关系**：N-4 之前 SIGTERM 在**整个运行期间**都是默认处置（上一轮 T9），本轮装上处理函数把窗口收窄到「结果行写完之后的收尾阶段」。这个窗口里结论其实已经定下并写出去了，丢的只是退出码的保真度：本该 0，变成「被信号终止」。「至多一条结果行」在这条路径上仍然成立。

**修法**（二选一）：
- 只改说明（我倾向这个）：把「有绿结果行则退出码为 0」改成可检验且成立的说法，例如「退出码为 0 则恰有一条绿结果行且是标准输出最后一行；反过来不成立——绿结果行写出后进程仍可能被信号终止，此时退出状态是被信号终止而不是 0，所以**调用方以退出码/退出状态为准**」；并在信号那一句里写明收尾阶段的信号不再经处理函数。**无需再审，由主控核对差异即可。**
- 改代码：写结果行之前用 `signal.pthread_sigmask` 把这两个信号屏蔽到进程退出，或在 `finish` 成功后直接 `os._exit(0)`。**需要再审**（改的是退出路径）。

### C-3 说明细节与计数（清单）

**档**：低，纯说明。其中第 1–4 项是上一轮建议 7 指出、作者按主控指示本轮未改的；第 5–8 项是我这一轮新发现的。**全部无需再审，由主控核对差异即可。**

| # | 位置 | 问题 |
|---|---|---|
| 1 | 第 256 行 | 「13 个环境层夹具在第 7 步判出旧期望的码；另 3 个（`private-proof`、`r4-p7a-deriving-spoof`、`r3-a1f/a1g-environment`）」——我重算 `fixtures.tsv`：环境层 16 行里判红步骤是 `env` 的是 **12** 行，括号里列的本来就是 **4** 个夹具（`a1f` 与 `a1g` 是两个）。应为「12 个……另 4 个」。上一轮就有，两轮都没改 |
| 2 | 第 55 行 | 「之后各步不再读被审工作区里的任何文件来决定输入」——第 3 步读了 `audited/lean-toolchain`（`run.py:394`）。它是基线那份的副本、此时被审代码还没运行过，没有后果，但句子说满了 |
| 3 | 第 106 行 | 转义规则只写了 `\xNN` 与 `\uNNNN`，没写码点大于 U+FFFF 时用的 `\UNNNNNNNN`（`run.py:91`） |
| 4 | 第 105 行 | 行协议写 `FM STEP <n> <名字> <GREEN\|RED\|FAULT> <秒> <备注>`，但 `FAULT` 的步骤行没有备注栏（`run.py:792`） |
| 5 | 第 74 行 | 「被审构建在沙箱里只能写 `.lake`」——沙箱里 `/tmp`（含 `HOME=/tmp/home`）、`/dev/shm`、`/dev`、`/var`、`/run`、`/home`、`/root` 都可写，只是都在 bwrap 的 tmpfs 里、落不到宿主机。应为「**宿主机上**只能写到 `.lake`」 |
| 6 | 「与设计备忘的偏离」 | 上一轮建议 7 列了四处没进这一节：`.lake` 形状表**已补**（第 4 条），`CONTENT_ENCODING`、「必须带 `-I`」、`SIGNAL` 归类仍没列 |
| 7 | 第 23 行 | `-I` 管不到的那一句列了 `PYTHONPATH` 与 `sitecustomize`、`-m run`，没列 `-c`/`exec`：`python3 -c "exec(open('run.py').read())"` 在冒名目录里跑时解释器启动阶段就执行了当前目录的 `linecache.py`（见第二节 N-1） |
| 8 | 第 105 行 | 「被别的信号（如 SIGKILL）终止，或连这一行都写不出时，可能没有结果行」——漏了 C-1（标准错误阻塞时卡死、不产生退出码）与 C-2（收尾阶段的 SIGINT/SIGTERM 不经处理函数）两种 |

## 五、非阻断建议

1. **自测缺口：产物文件模式那一条规则没有任何用例。** 我做的弱化 Q2「去掉文件模式检查（执行位、特殊位、属主可读）」跑**全部 52 个骨架用例全过**（122 秒），没被抓到。规则本身是对的——单元矩阵里 0755、4644、0244 的合法 `.olean` 都判 `ARTIFACT_FORM`（第六节）——缺的只是用例。S20 现在只在目录模式上有样本（`ChanDyn` 改 0111），文件模式一侧空着。建议 S20 再加一项：把某个模块的 `.olean` 改成 0755 或 0244。
2. **自测缺口：`finish()` 的「至多写一次」守卫没有任何用例。** 弱化 Q5「去掉 `STATE["result"]` 守卫」同样全部 52 个骨架用例全过。这条守卫只在「信号与主路径竞争」时起作用，而现有用例里信号总是落在某一步中间（主路径还没写结果行），所以测不出。建议 S26 再加一例：读到结果行的那一刻再发信号（做法见 `case_green_signal.py`），断言结果行仍只有一条。
3. **我做的 Q6 不算缺口，是我出的坏弱化。** Q6「把隔离检查的出口从 `posix._exit(2)` 改成 `raise SystemExit(2)`」没被 S24 抓到，但我随后用 12 种流状态比对了原件与 Q6 副本（`case_isolate3c.py`），两者的退出码与「冒名模块有没有被执行」**逐例相同**，所以这个弱化在本机这台解释器上观察不到行为差异，不能算自测漏掉了什么。`posix._exit` 仍是更稳的写法（完全不进解释器收尾），只是优势在本机测不出来。
4. **README「被审构建在沙箱里只能写 `.lake`」说满了。** 实测沙箱里 `/tmp`（含 `HOME=/tmp/home`）、`/dev/shm`、`/dev`、`/var`、`/run`、`/home`、`/root` 都可写——它们都是 bwrap 建的 tmpfs，写进去的东西落不到宿主机。准确的说法是「**宿主机上**只能写到 `.lake`」。构建本来就需要可写的 `/tmp`，所以这只是措辞。
5. **README 的 `-I` 注意事项可以把 `-c`/`exec` 并进去。** 现在列了 `PYTHONPATH` 指向别人能写的目录会让解释器在第一行之前导入 `sitecustomize`，以及 `-m run` 不受支持。实测 `python3 -c "exec(open('run.py').read())"` 与 `python3 -c "import sys"` 在冒名目录里跑时，解释器启动阶段就执行了当前目录的 `linecache.py`（同样在 `run.py` 第一行之前）。按脚本路径调用不受影响。这一条与建议 9（上一轮）同类，都归 #2315 的工作流约束。
6. **调用方的 umask 屏蔽属主写位时，构建自己会失败。** `run.py` 不设 umask，自己建的目录靠 `mkdir` + `chmod` 不受影响，但 Lake 在 `.lake` 里建的目录随 umask。实测：umask 0022 → 目录 0755、无红；umask 0077 → 目录 0700、无红（目录模式规则的 `mode & 0o700 != 0o700` 正好容得下）；umask 0277 → Lake 建的 `build` 是 0500，`lake build` 自己退 1，流水线报 `BUILD_WFAIL` **退 1**（不是退 2）。也就是说一个合法提交会因为调用方的 umask 被判红。建议运行脚本在起沙箱前显式 `os.umask(0o022)`，或在说明的调用一节写明对 umask 的要求。
7. **上一轮的建议里仍未做的几条**（作者已按主控指示声明本轮不做，我没有重测，只确认仍在）：建议 1（`safe()` 原样保留 U+3164、U+2800 这类显示为空白的字母与符号）、2（深嵌套 JSON 以 `INTERNAL` 而非 `INPUT` 退 2）、3（`1e999` 被接受成无穷大）、5（第 6 步显示：判红时步骤行备注现在已改成空，这一条**部分已做**；`EXTRA_ARTIFACT` 的路径栏现在是遍历得到的真实相对路径，不再按模块名重拼，这一条**已做**）、6（构建日志整个捕获进内存、4 小时无输出）、8（`lean --version` 那次调用继承调用方全部环境）、10（审计程序里 `importModules` 不在 `try` 内）、11（异常消息里的非 UTF-8 路径显示成 `\x5cudcff`）。

## 六、实测到的真实构建产物后缀与形状表的对照

### 真实 Lake 构建产出的后缀（八种情形，`case_suffixes.py`）

每种情形都是一个最小 Lake 包（无依赖、与被审包同一份 `lean-toolchain` 即 Lean 4.36.0、同一套 `[leanOptions]`），直接 `lake build --wfail`，再用被审 `run.py` 自己的 `artifact_reds()` 判这堆真实产物。

| 情形 | `lake` 退出码 | 目录项 | 形状表判定 |
|---|---|---|---|
| 单模块 `Chan`（被审提交只有一个模块） | 0 | 20（目录 4、文件 16） | 无红 |
| 多级目录 `Chan/A/B/C`，带 `deriving DecidableEq, Repr, Inhabited`、`instance`、`structure … deriving Repr` | 0 | 42（目录 10、文件 32） | 无红 |
| `@[expose] public section` 的模块 | 0 | 40（目录 8、文件 32） | 无红 |
| 增量构建（建好后改一个文件再建） | 0 | 42 | 无红；与首次构建的目录项集合逐项相同（新增 0、消失 0） |
| 无改动再建一次 | 0 | 42 | 无红 |
| 构建失败后（一个模块 `rfl` 证不成） | 1 | 7（目录 6、文件 1，只有 `.setup.json`） | 两条 `NO_ARTIFACT`（真实流水线里 `BUILD_WFAIL` 先判红，走不到这一步） |
| 失败后修好重跑 | 0 | 38 | 无红 |
| 带 `linter.unusedVariables` 告警、`--wfail` | 1 | 38（产物齐全） | 无红（真实流水线里 `BUILD_WFAIL` 先判红） |

**实测到的全部文件后缀（16 种，去重）**：`.olean`、`.olean.hash`、`.olean.private`、`.olean.private.hash`、`.olean.server`、`.olean.server.hash`、`.ilean`、`.ilean.hash`、`.ir`、`.ir.hash`、`.ir.sig`、`.ir.sig.hash`、`.trace`（以上 13 种在 `build/lib/lean`）与 `.c`、`.c.hash`、`.setup.json`（3 种在 `build/ir`）。

**与形状表逐项对照**：`LIB_SUFFIXES` 13 种、`IR_SUFFIXES` 3 种，与实测的 13 + 3 **一一相等，没有多也没有少**。实测后缀里不在形状表的：无。

**锁文件与临时文件**：正常结束后 `.lake` 顶层只有 `build`（无依赖的包不产生 `config`，也不产生 `packages`——`packages` 是运行脚本自己先建的挂载点）；`.lake` 里没有任何名字含 `lock` 或 `tmp` 的目录项；包目录 `.lake` 之外也没有残留。

**真实仓库的 64 项**：真实被审包的内容模块是 `Chan`、`Chan.Smoke`、`ChanTest.Probe` 三个（`git ls-tree HEAD formal_math`）。我没有重建真实仓库（归主控读数），但独立复现了这个计数：`case_shape_unit.py` 按形状表给这三个模块造一份「合法的完整构建」，目录项恰好 **64 个**——目录 12（`build`；`build/lib`、`build/lib/lean`、`lib/lean/Chan`、`lib/lean/ChanTest`；`build/ir`、`ir/Chan`、`ir/ChanTest`；`config`、`config/1`、`config/5`；`packages`）、`build/lib/lean` 下文件 39（13 × 3）、`build/ir` 下文件 9（3 × 3）、`config` 下文件 4（两个 `config/<数字>` 各两个文件），12 + 39 + 9 + 4 = 64，与 README 第 95 行的分类逐格相符，形状表判定无红。

### 形状表的单元矩阵（38 项，`case_shape_unit.py`）

在磁盘上造各种 `.lake` 形状后直接调用被审的 `artifact_reds()`，不跑 `lean`。合法构建基线为上面那 64 项。

| 类 | 项 | 结果 |
|---|---|---|
| 文件模式 | 合法 `.olean` 带执行位 0755、带 setuid 4644、属主不可读 0244；合法 `.trace` 带执行位 | 四项都 `ARTIFACT_FORM`（前三项另带该模块的 `NO_ARTIFACT`） |
| 文件模式（应放行） | 合法 `.olean` 模式 0400、0600 | 无红 |
| 目录模式 | 内容目录 0111、0500、setgid 2755、sticky 1755 | 四项都 `ARTIFACT_FORM` + 该模块 `NO_ARTIFACT` |
| 目录模式（应放行） | 内容目录 0755、0700 | 无红 |
| 顶层 | `build/lib/lean/Init/` 目录、`build/lib/lean/Init.olean` 文件 | 都 `ARTIFACT_ROOT` |
| 名字 | 没有源码的模块、名字带多余点、隐藏名、只差大小写、西里尔同形名、非 UTF-8 名字、名为 `X.olean` 的目录 | 七项都 `EXTRA_ARTIFACT` |
| 类型 | 符号链接（指向表内名字与指向 `/etc/hostname`）、把合法 `.olean` 换成符号链接、命名管道占用合法名、把 `build/lib/lean` 换成符号链接 | 都 `ARTIFACT_FORM`（最后一项另报 `build/lib/real` 的 `EXTRA_ARTIFACT` 与三条 `NO_ARTIFACT`，不跟随链接） |
| 位置 | `.lake/stray`、`.lake/build/bin/x`、依赖挂载点下有东西、`config/<非数字>`、`config/9/other.olean` | 五项都 `EXTRA_ARTIFACT` |
| 位置（应放行） | `config/007` | 无红 |
| 缺失 | 缺某模块的 `.olean` | `NO_ARTIFACT` |
| 缺失（应放行） | 缺某模块的 `.trace`、缺整个 `build/ir`、缺 `packages` 目录 | 无红 |
| 不查的（已明示不防） | 表内硬链接、3 GB 稀疏的合法 `.olean`、合法 `.olean` 内容换成另一个模块的产物 | 无红（形状表不查链接数、大小与内容） |

38 项全部与说明里的判定表相符，没有一项判错码。

## 七、核实正确的部分

1. **送审主问题的几条支柱，本轮改动都没有重新打开。** 对照跑了被审提交自己的骨架用例里与主问题有关的 21 个（`case_control3.txt`，**23/23 通过、退 0**）：S1（阴性对照全绿）、S3（绕过预检从第 2 步起跑：配置仍取自基线、执行的是受信目录里的审计二进制、假 `main` 的哨兵没出现）、S4（`.gitattributes` 与过滤器不影响取料）、S5a–e（审计程序输出被篡改五种，全退 2）、S7（哨兵：被审工作区源码与配置逐字节未变、工作区之外四个哨兵都不存在、仓库快照不变，整次运行恰好因正对照的 `.lake/inside-ok` 报一条 `EXTRA_ARTIFACT`）、S13（`RUNNER_MISMATCH`）、S16a–b（模式是文件的条目实为树/提交：经预检 `TREE_FORM`；绕过预检取料 `GIT` 退 2，不写出被审工作区）、S17（读环境不运行被审模块的初始化器，带正对照）、S22（第 6、7 步同挂载同环境的探针）、S27a–b（第 4、7 步审计程序被信号杀死 → `SIGNAL` 退 2，这是上一轮我没造出样本、只读了代码的那一项，本轮由作者新增的用例覆盖并通过）、E1、E2、E3、E8、E10（输出注入五类）。
2. **第 1 步对已过审预检（`59504398f4`）的转出。** `case_precheck_rerun.txt`（不调用 `lean`）：真预检的 **11 个红码**（`TREE_FORM`、`EMPTY_TREE`、`MODE`、`LAKE_FILE`、`PATH_GRAMMAR`〔另跑了「两条路径只差大小写」那一例〕、`TOP_LEVEL`、`CONTENT_SHAPE`、`BRANCH_ROLE`、`PATH_SCOPE`、`TRUST_UNAPPROVED`、`TRUSTED_DRIFT`）逐例与直跑预检的红码集合相同、退 1；两个故障码 `NOT_ANCESTOR`、`BASE_FORM` 转成 `PRECHECK_EXIT` 退 2；绿行与 `infra` 放行绿行走到 `--until 1` 的 `PARTIAL` 退 2。假预检 **18 种不合规输出全部退 2**（绿行两条、提交名不符、绿行后多一行、没有输出、没有换行结尾〔`PRECHECK_OUTPUT`〕、退 0 却是红行、退 1 却是绿行、红行夹杂项、红码小写、缺说明栏、空行、红绿混排、退 2 带红行、被信号杀死等）；未知红码 `BRAND_NEW_RULE` 原样转出退 1 且只转义一次。预检那一版的规则码集合取自它自己的 README（11 个红码 + `NOT_ANCESTOR`、`BASE_FORM`、`USAGE`、`BAD_REV`、`GIT`、`OUTPUT`、`INTERNAL`），与运行脚本的 `PRECHECK_RED` 正则 `[A-Z_]+` 相容，不需要改运行脚本。
3. **沙箱覆盖面与 README「沙箱布局」逐格相符。** `case_cover.py` 用被审 `run.py` 自己的 `sandbox()` 在第 6、7 步两套挂载下探测：`/root`、`/run`、`/var` 条目数都是 0，`/home` 只剩通往工作目录的 `workspace`、`/tmp` 只剩 `home`，`/run/user`、`/var/log` 不存在，`HOME=/tmp/home` 为空；宿主机工作目录里的金丝雀不可读；受信目录第 6 步不可读、第 7 步只读可读。挂载表里仍列着宿主机的 `/run`、`/tmp` 是被 tmpfs 遮住的旧挂载（`/proc/self/mountinfo` 里 `/run` 那一支的最后一条是 bwrap 新建的 `tmpfs rw … uid=1002`），不是泄漏。
4. **被审构建写不到宿主机。** `case_shm.py`：沙箱里可写的是 `/dev/shm`、`/tmp`、`/tmp/home`、`/dev`、`/var`、`/run`、`/home`、`.lake`，不可写的是 `/etc`、`/usr`、`/proc`；运行结束后宿主机的 `/dev/shm/fm-write-probe`、`/tmp/fm-write-probe` 都不存在，只有 `.lake` 下那一个在（预期）。也就是说那些「可写」的都是沙箱自己的 tmpfs，落不到宿主机（README 的措辞见建议 4）。
5. **`call()` 的新写法确实不让子进程继承两路输出。** 六个调用点逐个读过：`merge` 为真时 `stdout`、`stderr` 都接管道；`merge` 为假且调用方把 `stdout` 显式给成 `None` 时（只有 `sandbox()` 这一处）`kw.get("stdout") is None` 为真，仍改成管道；其余调用点本来就给了 `subprocess.PIPE`。`stdin` 恒为 `DEVNULL` 或管道。E10（构建期打印伪造的绿行）与 S17 对照通过，印证没有直通路径。
6. **`finish()` 的长度上限与原子性。** 上限 4096 正是本机 Linux 的 `PIPE_BUF`；结果行的四种状态文字都是定长字面量（`GREEN`、`RED`、`PARTIAL` 与 `FAULT <步骤> <码>`，码全是源码里的字面量），实测最长一条 `FM RESULT RED 第 n 步 … 判红，后面的步骤没有跑` 远在上限内，所以「长度超限导致写不出」在现有代码里构造不出来。
7. **说明里的计数与 `fixtures.tsv` 逐格相符。** 我用脚本重算：`fixtures.tsv` 数据行 252；八类归属的夹具数（预检 9、被取代已删除 16、头部 78、沙箱构建 13、环境层 16、声明锁 12、第四片 103、不再检查 5）、每类的 must_red/must_green/must_unknown 分布、每类的「退 1 / 退 0 / 未跑」分布，与 README 汇总表 **逐格相同**；归第四片的 76 个必红夹具里现为绿的恰 24 个；红码含 `TOP_LEVEL` 的恰 22 行；九个环境层红码都至少有一个夹具在第 7 步判出（`ENV_SORRY` 只有 `r4-p5b-guard-msgs-swallow` 一个，与说明一致）。骨架用例 **52 个**（装饰器 34 + 循环生成 18，无重名），有期望的语料用例 **225 个**，合计 **277**，与主控读数一致。`MUTANTS` 恰 **28 项**，与说明「18 + 7 + 3 = 28」相符。
8. **形状表不误红、也不漏判**：见第六节的八种真实构建与 38 项单元矩阵。
9. **依赖目录缺包、基线清单不合格等取料面**沿用上一轮结论（本轮 `step_fetch` 未改动——`git diff 1ea21f7206..14fc96c4b2` 里没有这一段），对照用例 S29、S30 在 Q0 控制组通过。

## 八、依赖目录前后比对

共享依赖目录 `/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages`，按简报要求**严格只读**。

- 开工时（跑任何东西之前）与收工时（全部运行结束之后）各记一次顶层的 `stat`（名字、mtime 秒、mtime 全精度、模式），两份**逐字节相同**。
- 顶层目录自身的修改时间仍是 `2026-11-26 08:42:22.839258931 +0800`，与前两轮报告记下的同一时刻；九个包目录（`Cli`、`LeanSearchClient`、`Qq`、`aesop`、`batteries`、`importGraph`、`mathlib`、`plausible`、`proofwidgets`）的修改时间都在 `2026-11-24`。
- `find <依赖目录> -maxdepth 1 -newer <开工时的记录文件>` 列出 **0 项**。
- 凡是涉及「依赖目录是否可写」的试验**一律用自建的假依赖目录**：我自己写的夹具全部用 lite 基线（清单里没有依赖包）配临时目录里自建的空 `fake-packages`。用到共享依赖目录的只有三处，都是只读挂载、都没有改沙箱挂载的弱化：被审提交骨架用例的对照跑（`case_control3.py` 的 21 个用例里 S1、S3、S4、S5a–e、S7 等非 lite 用例）；`mutants3.py` 在副本里跑骨架自测时的非 lite 用例；Q2、Q5 两种弱化的骨架全量。

## 九、弱化测试

作者的 `--mutants` 28 种主控已跑（全部被抓到），我没有重跑；我逐条读了清单，没有「依赖目录可写」这一种，各种弱化下沙箱的根仍是只读、依赖目录仍是只读挂载。本轮另加的 3 种（目录模式异常或列不出时跳过、不装 SIGINT 与 SIGTERM 处理函数、隔离检查失败时的诊断经 `sys` 的流写且不兜异常）各对应 S20、S26a/b、S24，与上一轮我指出的缺口相符；上一轮我做而自测没抓到的 10 种里收进了 7 个新改弱点，剩下的「`.olean` 不要求是文件」确实不再适用（形状表按目录项类型分查目录表与文件表，名为 `X.olean` 的目录从来查不到文件表，S20 的 `Chan/Dir.olean` 覆盖这个形状——我在单元矩阵里核过）。

我自己另做 **6 种**（`mutants3.py`，与作者 28 种不重复，重点在形状表、隔离检查、结果行三处），在被审树的副本里改一处，用副本自己的自测跑：

| 弱化 | 跑的用例 | 结果 |
|---|---|---|
| Q0 不改（对照） | S20,S21,S24,S25,S26a,S26b,S28 | 7/7 通过 |
| Q1 形状表只查文件表，目录一律放过 | S20,S21,S28 | 抓到（S20、S28） |
| Q2 去掉文件模式检查（执行位、特殊位、属主可读） | **骨架全量 52** | **没抓到**（52/52 全过，122 秒） |
| Q3 `ARTIFACT_ROOT` 的层级判断 `==3` 改成 `==4` | S20,S21,S28 | 抓到（S20、S21） |
| Q4 `NO_ARTIFACT` 只看路径存在，不要求通过形状检查 | S20,S21,S28 | 抓到（S20、S28） |
| Q5 `finish()` 去掉「整次运行至多写一次」的守卫 | **骨架全量 52** | **没抓到**（52/52 全过，124 秒） |
| Q6 隔离检查的出口改成 `raise SystemExit(2)` | S24 | 没抓到，但**这是我出的坏弱化**：我随后用 12 种流状态比对原件与 Q6 副本（`case_isolate3c.py`），退出码与「冒名模块有没有被执行」逐例相同，观察不到行为差异，所以不算缺口 |

抓到 3 种，没抓到 3 种，其中 Q6 不算缺口。Q2 与 Q5 是真缺口，但两者改掉的性质我都另行实测过在被审提交上成立——文件模式规则见第六节单元矩阵（0755、4644、0244 都判 `ARTIFACT_FORM`），`finish()` 的守卫见第二节 N-4（处理函数里再被打断仍只一条结果行）。缺的只是用例，见建议 1、2。

## 十、没覆盖的部分

- **全量自测 277 例没有重跑**（简报说不必）。跑的是 21 个主问题相关用例的对照（23/23）、Q0 控制组的 7 个、以及 Q2、Q5 两种弱化的骨架全量 52 个（对照组在未改弱副本上 52/52）。语料 225 例本轮没有跑，汇总表只核了与 `fixtures.tsv` 的算术一致。
- **作者的 `--mutants` 28 种没有重跑**，以主控读数为准；我逐条读了清单，没有「依赖目录可写」这一种，各种弱化下沙箱的根仍是只读、依赖目录仍是只读挂载。
- **真实仓库的完整流水线没有重跑**（要动共享依赖目录与长时构建），以主控读数为准。真实 `.lake` 的 64 项我是用形状表为真实的三个内容模块重建一份合法构建来独立复现计数的，不是读真实产物。
- **N-1 只在本机 Python 3.14.4 上测了**；别的解释器版本在这条路径上导入哪些模块没有环境验证。
- **「绿结果行 + 退出码 2」那个时间窗**（C-2）只在本机、只用「读到绿行立刻发信号」这一种打法试了 14 次；没有用别的方式（例如高频喷信号）去扩大命中率，也没有量出窗口的实际宽度。
- **大小写不敏感的文件系统**上「只差大小写」的产物名会与真名冲撞，本机是 xfs（区分大小写），这种文件系统没有测；macOS 没有测。
- **畸形 `.olean` 对审计进程本身的影响**（说明已明示不防）没有测；3 GB 稀疏的 `.olean` 只验证了形状表放行，没有看第 7 步读它时的表现。
- **内核层面的沙箱逃逸**没有测；只测了沙箱里拿不到能力（`CapEff` 全零）、`mount`/`unshare` 被拒、硬链接跨不出挂载。
- **SHA-256 对象格式的仓库**没有测。
- **第一片预检、`auditor/`、CI 工作流、同目录待删的旧门禁代码**，按范围没有审（只确认了范围外两个 `git diff` 为空）。
- 进程数压测类的试验（用大批占位进程去扩大「沙箱结束到遍历开始」的窗口）我开了一次就停手了，没有继续；时间窗的结论来自 `--die-with-parent` 加 pid 命名空间的机制与八次常规实测。

---

VERDICT-骨架: PASS（带条件）（范围：`formal_math/verification/runner/` 的 `run.py`、`selftest.py`、`README.md`、`fixtures.tsv`、`selftest-cases/`，提交 `14fc96c4b236c468ce57c3427e4b78ceeb29f9fe`。新的高项 0 条；条件项 3 条，均为低档：C-1 标准错误阻塞时卡死、不产生退出码；C-2 绿结果行写完后到进程退完之间的信号不经处理函数、进程被信号终止而非退 0；C-3 说明细节与计数清单 8 项。C-3 与 C-1、C-2 的「只改说明」选项都无需再审，由主控核对差异即可；若对 C-1 或 C-2 改代码，改动落在 `on_signal`/`emit`/退出路径，建议再审这几处。与前两轮报告合起来对 `runner/` 在该提交上的整体判断：r1 的 B-1、B-2、B-3 与 r2 的 N-1、N-2、N-3、N-4 全部闭合；送审主问题「被审提交能否影响哪个审计二进制被执行，或经声明之外的通道影响它的输入」三轮都没有被击穿；环境层搬家维持 r1 的 PASS 且相对 r2 无改动；第一片预检是四轮独审 PASS 的那一版、相对 `59504398f4` 无改动。本轮最大的新增面——第 6 步的 `.lake` 形状表——漏与误红两头都查过且没有发现缺口：16 种真实后缀与表一一相等、八种真实构建情形零误红、38 项单元矩阵逐项判对，表内合法名字承载别的东西时也出不了声明范围（硬链接 `EXDEV`、`CapEff` 全零）。`runner/` 可以放行，条件是修正上列三条低档条件项。）
