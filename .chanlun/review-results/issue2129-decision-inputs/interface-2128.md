# #2128 → #2129：S 恢复接口同步

来源：[NewChanlun 开发 #1323 主图（Mac Neon）](t3-thread://v2/7c88ea6d-c025-443f-87a2-64a29f187069/mcp:launch:682f3fd582fb23a11a986be6a2e0e77efd449467c0f691b830412b9324354cd8) 于 #2129 起草时转来的并行工位接口；票见 [#2128](https://github.com/Newchanlun/NewChanlun/issues/2128)。

- 只有 S 域复核并升代。沿用 #2082 的 NamedRecoveryReceipt 三项外壳：request、writer_epoch、recover_ns。
- S 请求版型 s-recovery/1，含 S 域、会话及会话代、from_epoch、精确旧 cut（generation、structure_cut、index_frontier）、冻结的业务配置、clock_event_id。
- 显式 current-recovery 才给 launcher 可核的当前代。S 恢复不改 E manifest 或 X 权威档；#2129 消费 S/E 各自已核原回执以及连续的旧→新关系，不裸接整数。
- 交接时拟追加 ADR 0039；实际候选追加在 [ADR 0050:80–85](https://github.com/Newchanlun/NewChanlun/blob/be2749f2996f8e928e72051193a693819c72fdbf/docs/adr/0050-s-resource-admission-contract-v1.md#L80-L85)，已逐项复核请求、回执外壳、current 与 query 的取证差异、launcher 转交及 serve 持锁复核。#2129 仍独立用经主控预留的 ADR 0073。
