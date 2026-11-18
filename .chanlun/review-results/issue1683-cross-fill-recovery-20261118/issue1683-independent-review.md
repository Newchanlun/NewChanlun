VERDICT: PASS

# #1683 独立源码验收：跨多笔净额成交的总量反冲

**算法与红对照通过；原合入点 CI 非绿。** 本记录签署 #1683 的跨 fill 反冲算法及旧实现负控；新进程恢复复用已有实证。原合入点的三项 CI 失败均有后续修复证据，详见下文。范围仅限 [#1683](https://github.com/Newchanlun/NewChanlun/issues/1683)，不代签 #1406 其他 AC。

审查 [PR #1685](https://github.com/Newchanlun/NewChanlun/pull/1685) 固定头 `c707a509a736a2f8a40d1235152c70330b1d65be`，生产提交 `3f7b2a6c4637edac9e3a7b5446440a1152cd3e6a`。合入 `3ca3a362795cce29edbdf49424828b9009e2b779` 的第二父是该 PR 头；两个改动文件在 PR 头和合入点间逐字节相同。合入点是恢复实证头 `b9d898dccf46c2a716115eaa1215bc39c458a959` 的祖先；三个算法文件（corrections、allocation、tb03c_allocation）在两点间无差异。

## 源码判决

依据 [ADR 0032 裁定五、六及修订后的裁定二](https://github.com/Newchanlun/NewChanlun/blob/c707a509a736a2f8a40d1235152c70330b1d65be/docs/adr/0032-fill-allocation-policy.md#L31-L43)：

- **数量与分段原价。** [corrections:151–245](https://github.com/Newchanlun/NewChanlun/blob/c707a509a736a2f8a40d1235152c70330b1d65be/rust/src/economic_session/tb03c_corrections.rs#L151-L245) 从同一冻结清单的原回报和分配重建连续存续栈，每段携带原 `unit_price`；历史 bust 和新 bust 走同一个 `rewind`。它只从当前前沿 F 截到 F−b，保留切点以下的原段，而不是按具名 fill 全部定价。对每个撤销段 (l,r]，[corrections:299–326](https://github.com/Newchanlun/NewChanlun/blob/c707a509a736a2f8a40d1235152c70330b1d65be/rust/src/economic_session/tb03c_corrections.rs#L299-L326) 计算同一配额函数的 A(r)−A(l)，相邻端点相消得 A(F)−A(F−b)；现金逐段乘原价再按重累加，乘加均检查溢出，数量合计须等于 −b。[allocation:50–117](https://github.com/Newchanlun/NewChanlun/blob/c707a509a736a2f8a40d1235152c70330b1d65be/rust/src/economic_session/allocation.rs#L50-L117) 实施上配额、精确商比较、冻结请求量及 manifest 并列顺序，与正向共用。
- **独立手算。** 权重 (1,3,3)、并列顺序 N1/N2/N3 给出单位 1–7 归属 N2、N3、N2、N3、N2、N3、N1。7→2 撤回单位 3–7，依次是 (N2,100)、(N3,101)、(N2,102)、(N3,102)、(N1,102)，单位 3、5 由并列顺序决出。各重结果为数量 (−1,−2,−2)、反冲采购现金 (102,202,203)，合计 −5 单位、507 现金计量单位。[原测试:520–568](https://github.com/Newchanlun/NewChanlun/blob/c707a509a736a2f8a40d1235152c70330b1d65be/rust/src/economic_session/tb03c_c4b_tests.rs#L520-L568) 用同一配额函数逐单位检验，并把上述归属、价格和结果写成常量断言；手算不依赖该函数。
- **因果费用。** [corrections:280–345](https://github.com/Newchanlun/NewChanlun/blob/c707a509a736a2f8a40d1235152c70330b1d65be/rust/src/economic_session/tb03c_corrections.rs#L280-L345) 区分数量 bust 与费用原件：数量 bust 佣金为零；迟到 fill 费依原分配数量分摊；具名 `reverse_component:commission` 读原分配中已经落账的各重佣金，全额、零数量、拒绝同一原件换标识重复退费。原测试 N1 的独立退款为 (0,2,1)，q 不变，K 从 (102,304,303) 到 (102,302,302)；没有拿本次撤销量重算原费，也没有隐式退三笔。裁定五规定费用如何归属，裁定六区分总量更正和原子分量更正；该区别保留。
- **留存与重放。** [E 分配:349–377](https://github.com/Newchanlun/NewChanlun/blob/c707a509a736a2f8a40d1235152c70330b1d65be/rust/src/economic_session/tb03c_allocation.rs#L349-L377) 只追加新更正行，[B 入账:844–869、897–963](https://github.com/Newchanlun/NewChanlun/blob/c707a509a736a2f8a40d1235152c70330b1d65be/rust/src/economic_session/tb03c_book.rs#L844-L963) 要求冻结投影的前序分配先 Apply，以同一成分入口反冲，追加原件、Applied 和历史。[原测试:569–643](https://github.com/Newchanlun/NewChanlun/blob/c707a509a736a2f8a40d1235152c70330b1d65be/rust/src/economic_session/tb03c_c4b_tests.rs#L569-L643) 对拍旧 Applied、原分配和原回报前缀，确认 7→2 后剩余 2→0 仍按 100 反冲，并在 E 离线时审计及恢复 B。PR 用例的 reopen 为同进程；真正进程边界复用既有 RESULT.md、boat.log:122–144、fixture.rs：进程 7866→7983，四个规范业务镜像和重送的十张业务收据逐字节相同。未复跑。
- **适域与边界。** [入口](https://github.com/Newchanlun/NewChanlun/blob/c707a509a736a2f8a40d1235152c70330b1d65be/rust/src/economic_session/tb03c_allocation.rs#L126-L231) 限冻结净额 TestOnly 多头购入，不借 per-leg 回落。数量须满足 0≤to<from、b=from−to；当前前沿、连续栈、具名前件的身份/标的及冻结政策三元组均校验（corrections:38–49、86–130、157–188、257–275、299–321）。具名是因果锚，不是价格代表：7→4 具名 N1 返回 IdentityConflict 且不改 E 镜像，7→3 具名 N2（被撤回但非栈顶原件）通过，[原测试:647–674](https://github.com/Newchanlun/NewChanlun/blob/c707a509a736a2f8a40d1235152c70330b1d65be/rust/src/economic_session/tb03c_c4b_tests.rs#L647-L674)。B 拒绝反冲后负仓。累计分配仍受 2²⁴ 单位技术界；费用入口不扩展到 command/period、部分佣金或其他分量。没有发现适域内算法反例。

## 旧实现负控

原 [#1683 验收退回](https://github.com/Newchanlun/NewChanlun/issues/1683#issuecomment-6364378663) 和宿主 `.sandcastle/logs/sandcastle-issue-1683-reviewer.log` 仅能支持新头的 9 项绿；原评审关于旧实现会红是读码推断，所列命令没有旧实现配新用例的执行记录。原 PR 的 [Linux extras 日志](https://github.com/Newchanlun/NewChanlun/actions/runs/39679045296/job/119496392321) 有具名绿，但也不是旧实现负控。

本次 Boat Linux `bx_jds9ey3v`：以修复提交的第一父 `e4c634e1f7b544b7538da868273f456883359ca4` 导出 `rust s_session`；只用 `git show c707a509a736a2f8a40d1235152c70330b1d65be:rust/src/economic_session/tb03c_c4b_tests.rs` 整文件替换导出树里的测试文件。用 `cmp` 确认测试等于 PR 原件、corrections 等于旧对象；其余代码和夹具均来自旧对象。恢复输入时可对 Git 对象重复同样的导出及替换，在 Linux 的导出树下执行：

```sh
cd rust
cargo test --locked --lib --features s_session economic_session::tb03c_allocation_tests::c4b_total_bust_across_three_fills_reverses_per_unit_from_range_stack_and_recovers -- --exact --nocapture
```

`tb03c_allocation_tests.rs:435` include 该文件，所以精确测试名的模块是 `tb03c_allocation_tests`。编译完成，命中 **1 项、失败 1 项、退出 101**。在测试 :551 的 Resolve 断言失败，即三笔原成交和账本前置校验已通过、bust 已 Capture 为 Recorded，但 E 返回 `Error / Unsupported：跨多个原 fill 的 bust 现金对应尚未支持`，期望为 `Resolved`。这条错误来自 [旧 corrections:272–274](https://github.com/Newchanlun/NewChanlun/blob/e4c634e1f7b544b7538da868273f456883359ca4/rust/src/economic_session/tb03c_corrections.rs#L272-L274)。原始片段：[issue1683-red.txt](issue1683-red.txt)。

## CI：原 PR、实际合入与后续分开

- **原 PR 头：** [CI 39679045296](https://github.com/Newchanlun/NewChanlun/actions/runs/39679045296) 与 [DevSkim 39679045130](https://github.com/Newchanlun/NewChanlun/actions/runs/39679045130) 成功；PR 的 macos-session 跳过。Linux extras 原日志中跨三笔具名测试为 ok。
- **合入点 3ca3a362：** [Linux CI 的 rust-test-s-session-extras](https://github.com/Newchanlun/NewChanlun/actions/runs/40003451021/job/120585240133) 和 [CI macOS 的 macos-session](https://github.com/Newchanlun/NewChanlun/actions/runs/40003450931/job/120585238351) 同在 economic_session / session_transport / session_protocol 库测试步失败。两端跨三笔具名测试均 **ok**；红的是 `tb03c_funding_tests.rs:439 each_signed_record_window_gates_alone`（PolicyNotYetEffective 而非 Applied）、`:410 opening_batch_negative_controls_are_typed_and_deterministic`（预期错误却 Applied）、`:678 v2_domain_binds_revision_waits_in_e_and_replays`（观察日落到 1970-01-01）。合入一父已经包含 [#1691 时钟合同](https://github.com/Newchanlun/NewChanlun/commit/31cdcdf2adeccc82da8dd4301458d4c14155e0cf)；#1685 合入只动两个 C4b 文件。随后 [#1688 / 13ed4d45](https://github.com/Newchanlun/NewChanlun/commit/13ed4d45c8ff85175819ca987690328ab2a247a4) 将 TestOnly 时钟搬至签署有效期内、让观察/提交时钟一致，并按权威观察时间重写负控；后续 [Linux extras](https://github.com/Newchanlun/NewChanlun/actions/runs/40135530860/job/120996133858)、[macOS](https://github.com/Newchanlun/NewChanlun/actions/runs/40135530846/job/120996133285) 日志逐名确认三项均 ok，跨三笔也 ok。这是资金生效时钟与测试输入的失败，不是跨 fill 算法失败。
- **合入点 DevSkim：** [40003450872](https://github.com/Newchanlun/NewChanlun/actions/runs/40003450872/job/120585237548) 的 zero-findings gate 拒绝相对基线新增的 `DS162092|.github/scripts/run-1406-c6a.py|788`。该 C6a 离线验收脚本不在 #1685 差异中；后续 [#1741 / 67e9c422](https://github.com/Newchanlun/NewChanlun/commit/67e9c42205e4b98af137f203cdbc0cae66fe3d30) 精确登记该 loopback 误报，未放宽扫描门；[b9d898dc 的 push DevSkim](https://github.com/Newchanlun/NewChanlun/actions/runs/43853928206) 成功。
- 两个修复均是 b9d898dc 祖先。b9d898dc 自身 [push CI](https://github.com/Newchanlun/NewChanlun/actions/runs/43853928501) 与 [CI macOS](https://github.com/Newchanlun/NewChanlun/actions/runs/43853928258) 成功；前者跳过 Rust 作业，因此资金三项的修复证据以 #1688 的具名日志为准。历史合入点仍记为红。

同一实例的两进程验证及复跑材料见[恢复验收报告](REVIEW.md)。
