# #1683 跨三笔总量反冲：GPT‑6.2 Sol 非作者验收（2026-11-18）

受测生产代码：`b9d898dccf46c2a716115eaa1215bc39c458a959`（按对象导出，不用共享工作树内容）。#1685 的合入提交 `3ca3a362795cce29edbdf49424828b9009e2b779` 是该头的祖先。诊断只在导出的测试文件末尾追加夹具；E/B 生产实现、冻结 manifest 和原件未改。

## 原证据能绑定什么

- [#1406 原验收记录](https://github.com/xy7365527-lang/NewChanlun/issues/1406#issuecomment-6324262170) 把跨原 fill 记为 typed Unsupported；冻结净额政策的已有成功例是另一例，不能代替跨三笔成功。[N-2 裁定](https://github.com/xy7365527-lang/NewChanlun/issues/1406#issuecomment-6326122151) 将跨 fill 纳入 AC3。
- [#1685](https://github.com/Newchanlun/NewChanlun/pull/1685) 合入的正例已走实际 E/B，含原价、留证和单独 net-fill-1 commission 退款；但 [验收退回](https://github.com/xy7365527-lang/NewChanlun/issues/1683#issuecomment-6364378663) 指出的恢复调用仍是同进程 drop/open。受测头的 [c4b_reopen:29](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/rust/src/economic_session/tb03c_c4b_tests.rs#L29) 及 [正例:588](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/rust/src/economic_session/tb03c_c4b_tests.rs#L588) 证实这一点。[原 PR CI](https://github.com/Newchanlun/NewChanlun/actions/runs/39679045296) 的绿色状态属于原 PR；归档 shard 摘录没有具名跨三笔测试行，不能据此绑定新进程证据。
- [#1674 / PR #1684](https://github.com/xy7365527-lang/NewChanlun/pull/1684) 确有子进程和 SIGKILL；[build:401](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/rust/src/economic_session/tb03c_v2_kill_tests.rs#L401) 的输入是 `tb03c-book/2` 三 profile 开局及 `AwaitingPolicy(funding_revision/q_rebase)`，没有该 `/1` 跨三笔反冲。未重跑 #1674 矩阵。

## 手账：先按单位归属，再沿存续区间取价

单位和现金均为测试原件的整数计量。权重 `(1,3,3)`，同权同商按 `N1,N2,N3` 的 manifest 顺序。按 ADR 0032 修订后的上配额及最大商逐项手排：

| 累计单位 | 归属 | A(F) | 来源原 fill | 单价 |
|---:|---|---|---|---:|
| 1 | N2 | (0,1,0) | net-fill-1 [0,3] | 100 |
| 2 | N3 | (0,1,1) | net-fill-1 [0,3] | 100 |
| 3 | N2（与 N3 并列） | (0,2,1) | net-fill-1 [0,3] | 100 |
| 4 | N3 | (0,2,2) | net-fill-2 [3,4] | 101 |
| 5 | N2（与 N3 并列） | (0,3,2) | net-fill-3 [4,7] | 102 |
| 6 | N3 | (0,3,3) | net-fill-3 [4,7] | 102 |
| 7 | N1 | (1,3,3) | net-fill-3 [4,7] | 102 |

同一个 `bust-cross-7-2`（cursor 8，具名 `net-fill-3`）：`A(7)-A(2)=(1,2,2)`；应用单位 `(-1,-2,-2)`，逐重反冲原价总额 `(102,202,203)`，总量 -5、现金 507。栈从尾向前撤掉 [4,7]、[3,4]、[2,3]，留下 net-fill-1 [0,2]。

| 原 fill | 该 fill 分配单位 | 原 commission 总额 | 原 commission 分配 |
|---|---|---:|---|
| net-fill-1 | (0,2,1) | 3 | (0,2,1) |
| net-fill-2 | (0,0,1) | 1 | (0,0,1) |
| net-fill-3 | (1,1,1) | 5 | (2,2,1) |

数量反冲收据的 commission 为零。另送 cursor 9 的原子 commission 反冲，按原正例将退款前件和 fill_ref 指到 `net-fill-1`，冲回其全额原分配 `(0,2,1)`，数量不动。`q/K` 预期从 `(2,5,5)/(204,506,506)` 到 `(1,3,3)/(102,304,303)`，退款后到 `(1,3,3)/(102,302,302)`。原报、原 fill 分配和旧 Applied 保留。正式 [修正规则](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/rust/src/economic_session/tb03c_corrections.rs#L288) 分开处理数量反冲和原子费用；本例没有把跨三笔数量 bust 解释为自动按撤销数量退三笔手续费，也没有验 net-fill-2/3 单独退款或其它费用种类。

## 在 Linux 复跑

从包含受测提交和本报告的仓库根运行。只向临时导出树追加[验收夹具](fixture.rs)；共享工作树和生产源不改。使用项目原 Linux Rust/Python 构建环境，不在 macOS 执行。

```sh
proof=.chanlun/review-results/issue1683-cross-fill-recovery-20261118
work=$(mktemp -d)
git archive b9d898dccf46c2a716115eaa1215bc39c458a959 rust s_session | tar -x -C "$work"
cat "$proof/fixture.rs" >> "$work/rust/src/economic_session/tb03c_c4b_tests.rs"
cp "$proof/run.sh" "$work/run.sh"
bash "$work/run.sh"
```

[原运行脚本](run.sh)依次启动 forward 和 recover。每个过滤必须恰好执行一个测试。第一次运行保存四个非空库、对照值与库路径后关闭所有连接并退出；第二次从同一库及 manifest 恢复。以新的消息 ID 重送原操作，允许消息身份索引绑定，不得增加经济应用。

## 运行结果：两个 OS 进程，四个原库

[Boat 原始运行日志](boat.log)，Linux sandbox `bx_psmq52st`，退出码 0。两个具名测试各命中并通过 1 项，分别耗时 19.11 s 和 10.36 s。进程 **7866** 完成正向、检查原分配/原报/旧 Applied 前缀不变，并显式关闭数据库连接后退出。进程 **7983** 没有调用 init，在同一路径 `/tmp/nc1406-c4b-xproc-7866-0/` 打开已有数据库：

| 域 | 既有 SQLite 文件 | 恢复前文件大小（字节） | writer epoch | 全量规范业务镜像对拍（字节） |
|---|---|---:|---|---:|
| E | e.db | 1,474,560 | 1→2 | 139,944 |
| B:N1 | b0.db | 6,332,416 | 1→2 | 1,675,572 |
| B:N2 | b1.db | 6,426,624 | 1→2 | 1,690,149 |
| B:N3 | b2.db | 6,529,024 | 1→2 | 1,704,725 |

对拍的是 `store::latest` 的整个规范业务镜像，含 E 的已记录原件、分配、历史及 B 的 book/Applied；不裁字段、不只比净仓，也不要求 SQLite 物理页或恢复管理记录相同。恢复后分别重送跨三笔数量反冲与 net-fill-1 的 commission 反冲，各自 1 张 Capture、1 张 Resolve、3 张 Apply，共 **10 张原业务收据逐字节相同**。重送后四个完整镜像仍逐字节相同，E/B 均通过审计：没有重复经济应用。正向运行实得原 commission 分配 `[[0,2,1],[0,0,1],[2,2,1]]`，与手账一致。

## 验收结论

- **#1406 AC3 的跨三笔成功实例：通过。#1683 的同一实例新进程恢复：通过。** 可绑定本次受测头、夹具与运行日志。这里是已提交的非空库由另一进程恢复；SIGKILL 边界不属本次 #1683 证明，也未借用 #1674 的结果。
- [ADR 0032 裁定五、六](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0032-fill-allocation-policy.md#L31-L37) 区分数量和费用的因果原件。本例只向 net-fill-1 提交了费用退款；该原件按其原分配冲回。三笔数量一起减少这一事实，本身没有给出三笔退款金额。
- [独立源码审阅与修前红对照](issue1683-independent-review.md)核对了原价算法、适用范围，以及原 PR、实际合入点和修复后 CI 的区别。
