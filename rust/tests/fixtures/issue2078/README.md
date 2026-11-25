# #2078 的已提交模拟批 b1

三份输入来自发布头 734847be008c8393946a8056ec1566d71db19815 的 Linux 实跑目录
`capture-repair-4178995-1795042760031887757`。`x-profile-1.sql` 是关闭后的原
`x.sqlite` 的完整 SQLite iterdump，包含原命令、接纳钟、E 放行、S 资格、三批请求及回执和独立 fill/fee 表。
两份 QueryBatch 原回执直接复制自该次实跑：同为 b1，状态摘要相同，已知前沿不同。
保留原权威端点作为冻结数据；测试不连接它们，也不把 /1 字段改写成 /2。

在 Linux 的 `rust/` 运行：

```sh
cargo test --locked --features production_session --test history_simulation_entry \
  restage_frozen_profile_1_batch_without_reopening_x -- --exact --nocapture
```
