# #2312 骨架与环境层搬家独审 r1 的夹具

报告在上级目录 `skeleton-review-r1.md`。被审提交 `be069d974f8f4539fbc6c087fa3a3e1bbb6736c5`。

## 怎么跑

```sh
source scripts/fm_env.sh
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh \
  python3 audit-reports/2312/skeleton-r1-fixtures/<脚本> [用例名…]
```

三个环境变量可改默认值：`RF_SRC`（被审检出，含 `formal_math/`）、`RF_WORK`（工作根目录，默认 `/home/workspace/fm/tmp/review-f/work`）、`RF_PACKAGES`（依赖目录，只读使用）。`RF_ERR` 是每次运行打印的标准错误尾部字节数。

夹具不带 `-I` 运行（要导入同目录的 `rf.py`）；它们调用被审的 `run.py` 时一律带 `-I`。

## 文件

| 文件 | 内容 |
|---|---|
| `rf.py` | 公共驱动。复用被审提交 `runner/selftest.py` 的 `Repo`、`template` 现造 git 仓库；`run()` 跑整条流水线并打印命令、退出码、标准输出与标准错误尾部。`warm=True` 时复用预编译的审计程序产物（源码与被审提交逐字相同），只为省第 3 步的时间 |
| `case_green.py` | 阴性对照，真实命令行入口 |
| `case_inject.py` | **B-1**：经导入名、公理名向标准输出注入整行 |
| `repro_blocking.py` | **B-2**（锁文件键里的孤立代理项）、**B-3**（构建期杀掉 `lake`），真实命令行入口 |
| `case_args.sh` | 参数、前置条件与输出通道共 40 条；含 B-2 的调用方来源两例。参数：基线提交、被审提交（用 `case_green.py` 打印的那两个） |
| `case_probe.py` | 第 6 步沙箱探针：可读、可写、网络、环境、进程、嵌套命名空间 |
| `case_step7_sandbox.py` | 第 4、7 步的挂载表探针（不调用 `lean`、`lake`；复用 `case_green.py` 留下的工作目录） |
| `case_protocol.py` | 输出协议与产物目录：导入名与声明名里的换行、非 UTF-8、NUL、空文件、产物顶层放 `Init` 或符号链接、杀 `lake`、后台进程、截断或删除上游 `.olean` |
| `case_followup.py` | 锁文件的畸形键、`lib/lean` 换成符号链接、垃圾 `.olean`、`Chan/Defs` 不用 `public section`；`D1` 是派生证书等价性 |
| `case_migrate.py` | 环境层与头部各类明文必红写法，外加必绿对照 |
| `case_init.py` | 初始化器哨兵，带两个正对照 |
| `case_no_isolated.sh` | 不带 `-I` 运行时同目录 `json.py` 被导入（不调用 `lean`、`lake`） |
| `mutants.py` | 弱化测试：在被审树的副本里改一处，跑骨架自测 |
| `logs/` | 以上各项在本次审阅中的实际输出，扩展名 `.txt` |

## 注意

`mutants.py` 里不要加「把依赖目录在沙箱里挂成可写」的变异。自测 S7 的被审代码会真的往共享依赖目录里写哨兵。本次审阅的第一版就犯了这个错，经过见报告第九节。
