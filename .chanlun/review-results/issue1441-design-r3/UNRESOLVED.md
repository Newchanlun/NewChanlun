# #1441 第三轮设计：未决项（设计工作流原文）

1. 波幅下界 A_ℓ 的方法没有条文。ADR 0035:14 只写「ROUNDTRIP 波幅单边 95% 下界（按月 block bootstrap）」，:34 的重采样次数、种子、PCG、分位取法只钉给 descent-share/block-bootstrap/1。统计量（均值只是推断）、取整方向、method_id 都未裁。我查了 tracker（「波幅 下界 bootstrap 统计量」「amplitude block bootstrap method_id」）和仓内 docs、.chanlun/definitions，没有对应裁定票。需要在 #1323 下新开一张 P 类决策票。裁定前非测试构建恒得 MethodNotRuled，实现者不得自选统计量。
2. 数据集身份原件不存在：BTC 1m 全史不在 git。dataset{id,sha256,first_bar,last_bar}、样本时间戳、run_started_at、frozen_at 都是登记原件的自述，求值器只能核原件之间相等和内部自洽，覆盖率的分母因此是声明值。run 引用预登记窗表的 sha256，能证明窗表先于 run 文件存在，证明不了时间戳本身。信任根是登记行加非作者独审出处（ADR 0022「统计结论的标注与引用」）。谁出数据集清单原件需要主控指派；最近的已裁形状是 ADR 0052 的 history-input-profile/1，#1536 已关。
3. 生产成本读数的 schema 和由观测行求 rate 的方法归 TB-08（#1367；#1382、#1400、#1412）。本设计只定了绑定方式（政策内 source:{key,sha256}）和封口。需要转达的要求：生产 schema 须按成本项分立并带观测行；只有 rate 加 component 标签的格式不得登记为生产读数，否则 R2-HIGH 会在登记环节重现。test-only/cost-reading/0 只证明绑定、basis 相等和合计算术。另外 P0 的延迟代理来源是 markdown 表（issue907 报告 :161-169），将来把滑点升为 Known 的版本必须同时给出类型化的代理读数原件。
4. ADR 0035:14 的记录形状把 amplitude.per_level{median, lower_bound_95, n, max_month_cluster, windows[]} 和 probe_run_ref 列为字段。本设计把这些量当作求值器的推导输出（CostStopOutcome::windows），原件只带原始样本。如果独审把该条读成「原件必须带这些字段」，需要一条 ADR 文字澄清，不由实现者裁。
5. 版本与 run 的选择。load(profile, revision) 仍由调用方点名修订，求值器不核 valid_through，这与第二轮已过审的分工相同，按请求时刻选版本归 TB-07（#1366）。但 ADR 0044 §二.6 写的是「读取当前生效版本」，是否在本票加一个「未被取代的唯一修订」入口需要主控确认。同一分层登记多份 run 时得 AmbiguousRuns，换新 run 等于在同一提交里替换登记行；run 的 AsKnown 规则同样归 TB-07。
6. #2111 仍是 BLOCK（只差引用专修）。草稿口径是「成本、波幅、零分母」的顺序，全 Known 零合计为 NotEvaluable(ZeroTotalCost)。落地后 settle 的实测零分支改为先调 amplitude 再返回该状态，并删掉 Err 变体和断言相反的测试；独审补充第 6 条要的四个网格格子届时一并加锁。裁定合入前不得照草稿实现。
7. 实现时需要实测的三处，我没有跑 cargo：编译负例的 rustc 错误码与条数（写进 check-compile-negatives-1394.sh 的白名单与期望数）；cost_stop 门控后 default、s_session、backtest_bin 三种构建都能编译；两份 v1 文件拆出后的 sha256。
8. 事件规则里有三条是本设计的保守选择，不是既裁条文：事件须 entry 与 exit 都落在窗内才计入该窗；entry ≤ exit 允许同 bar；块按 entry 所在 UTC 月归属（沿用 p907_cost_gate_level.rs 按起点 bar 的日历月分桶）。探针片落地时应把它们写进读数的统计口径行，要改须出 amplitude-run/2。
9. FixedBars1m 块单位和 1m 以外的粒度现在一律判证据不足。出 evidence-gate v2 或接入其他粒度时，样本要带 bar 序号，需另出 schema 版本。
10. 没有密钥就没有比已审提交更强的信任根。同一提交同时改记录文件、登记行摘要和 ADR 0044，代码拦不住，只会出现在登记表的 diff 和 v1_matches_adr_0044 的失败里。设计二的只增校验脚本（对照 origin/main）没有纳入本轮，是否加由主控定。
11. cost_stop 模块门控后，默认 cdylib 构建不再含 theta_v0::cost_stop（第二轮 mod.rs:61 无门控）。目前没有外部调用者。默认构建将来要调用时，须把 sha2 改为必选依赖。
12. 波幅原件会编进 s_session 和 backtest_bin 二进制。设计二估 L0 样本约 1.7 万条、1 MB 量级，我没有核实。体积不可接受时改紧凑编码，身份绑定方式不变。
13. 基线既有问题，不在本票：evidence_gate::parse_evidence_gate 对任意文本都返回带 Signed(n) 的 PolicyRef（evidence_gate.rs:156-179 配 policy_records.rs:212-216），回测入口仍走它。
