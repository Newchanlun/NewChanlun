# #1425 R6 非作者裁定：BLOCK

绑定头 `76187c7a219d00fb499585eb7dbbe5c86dcb9a9f`，对照基线 `304dff8edb4778f79ea91790df5c3b6947919d0d`。

目标是三层读侧在固定切面向量下不带出未来事实、不越读权、合法读能成功。R6 修好了 R5 的四条过度拦截，但把“任意深度找 cut”换成手写位置清单时写错了键名，R4(a) 在转入事实上重开。一条 HIGH 成立，所以拦。

## 阻断项 F1（HIGH）

写入方只写 `b_source_debit_proof`（`rust/src/economic_session/tb03c_transfer.rs:432`，`store.rs:1724`；`read_projection.rs:491` 自己的省略路径也用这个名）。三层检查器查的是 `source_debit_proof`：

- `s_session/economic_query.py:346`
- `s_session/browser/tb03a-client.js:794`
- `rust/src/economic_session/read_projection.rs:1209`

目标 B 镜像里 `recorded[].b_source_debit_proof.receipt` 是源 B 域的 Applied 回执，现在没有任何一层核对它的 cut。

本机实跑（经 `economic_http.post` 走公开入口，复用仓内测试夹具 owner）。向量 E:10 / B:alpha:6 / B:beta:4，B:beta 的记录带 B:alpha:9 的回执。

| 输入 | R5 | R6 |
|---|---|---|
| 真实键，回执 B:alpha:9 | projection、snapshot 单帧与分页均拒 MissingDependency | 三者均放行，应答含 commit_seq 9 |
| 真实键，回执 B:alpha:6（对照） | 过 | 过 |
| 错键 `source_debit_proof`，B:alpha:9（对照） | 拒 | 拒 |
| 浏览器 `verifyProjection`，真实键 B:alpha:9 | 拒 | 放行 |

两个对照说明检查逻辑本身是好的，漏掉只因键名。触发不需要出错的 owner：读者选了目标 B 领先于源 B 的向量，诚实数据就带出源域的未来回执。Rust 层的 `check_protocol_cut` 只约束本域 cut（`read_projection.rs:1037`），跨域界限本来就靠 Q 和浏览器，而这两层都实跑放行。

修法：三层的检查与白名单改用 `b_source_debit_proof`。补三语言同输入的转入反例。加差分测试，跳过来源数据子树的任意深度遍历找到的每个 cut 都必须被结构访问器访问到。

## 七项状态

- **R4(a) 固定切面不带未来事实：REOPENED。** 原复现（E:6 带 E:8/E:10）仍被拦，断言仍在。转入路径重开，见 F1。Voice 位置同类漏检，见下。
- **R4(b) 仅分配读权不得拿完整命令：CLOSED。** `test_enumerates_three_single_permissions_for_invariant_b` 在 R6 头实跑通过。Rust `serialize_authority_evidence_object` 只在有 QueryCommand 时拷贝 command，为读码。
- **R4(c) 历史根缓存计入共享预算：CLOSED。** R6 差异里 `_admit_locked`、`_remember_verified_cut`、`MAX_VERIFIED_CUTS`、`metadata_bytes`、`cached_bytes` 的增删行数为 0，`economic_http.py` 未改，对应测试通过。
- **R5-H1 双域 Watch 卡 0/0：CLOSED。** 把 R6 测试文件配 R5 客户端实跑，`R6 #1` 红在 `MissingDependency 回执(E:1)晚于固定切面(E:0)`；配 R6 客户端为绿。选同伴切面的代码在 `tb03a-client.js:937` 与 `:1350-1368`，Q 的拒绝未动。依赖闭包走同一访问器，受 F1 影响会漏掉跨 B 域依赖。
- **R5-H2 来源数据里的同名字段：CLOSED。** R6 测试通过。代价是位置清单与写入方不符，即 F1 的来源。
- **R5-M3 回执归属域：CLOSED。** R6 测试通过。Python 对缺 `domain_id` 的回执比另两层宽（`economic_query.py:295`），实跑确认，不泄露。
- **R5-M4 五层正向白名单：CLOSED（就 R5 的反例）。** 白名单内容与写入方不符，属非阻断。

## 需同轮修的非阻断项

1. Voice 开局依据：三层查 `book.voice.identity.opening_basis.e_cut`（`economic_query.py:372`、`tb03a-client.js:748`、`read_projection.rs:1255`），真实位置是 `book.voice.records[].opening_basis.e_cut`（`voice.rs:170`、`:262`）。实跑：records[] 带 E:12、向量 E:10，R6 三个入口放行，R5 拒。诚实 owner 会把同一 cut 写进仍受检的 `recorded[].cut`，所以定 MED。
2. `projected_record` 白名单同一错键（`economic_query.py:208`）。实跑：带界内真实键的事实原件 R5 接受，R6 Python 拒“未声明字段”。Rust 侧按表拷贝会静默丢证明（读码）。
3. 权威回执白名单缺 `authority_epoch`（真实结构 `history_simulation/runtime.rs:404`）。
4. 测试弱化：R5 的未列举位置诱饵（`e_future_proof.cut`、`leaked_receipt`）被挪到已列举位置，F1 因此没被测到。

其余 MED/LOW 见 non_blocking 清单。

## 在此运行了什么

- R6 头：`test_economic_read_projection` 13 通过，`test_tb03a_projection_client.cjs` 4 通过，`test_tb03a_query` 9、`test_tb03b_query` 16、`test_tb03c_query` 30、`test_c6a_economic_pagination` 14 通过。R5 头：`test_economic_read_projection` 10 通过。
- 自写 Python 探针（两头各跑）：转入回执、Voice、缺 domain_id、projected_record 真实键。自写 Node 探针（两头各跑）：`verifyProjection` 的转入回执四例。
- R6 测试文件配 R5 客户端：2 过 2 败。
- 分镜头评审的变异测试、2665 次 Watch 随机历史、78 个位置覆盖统计，本人未复跑，引用时已标明。
- 未运行 cargo 或 rustc。凡涉及 Rust 的结论都是读码。作者声称的 Linux Rust 运行结果未经独立复跑，待补。
- 两个临时工作树 `/tmp/rev1425-verdict`、`/tmp/rev1425-verdict-r5` 与探针脚本已删除，主仓工作区干净，未编辑、提交、推送或评论。

## 阻断项原文

F1（HIGH，R4(a) 重开）：转入事实的源扣账证明真实键是 b_source_debit_proof（写入方 rust/src/economic_session/tb03c_transfer.rs:432，键清单 store.rs:1724），三层结构检查器查的都是不存在的 source_debit_proof（s_session/economic_query.py:346、s_session/browser/tb03a-client.js:794、rust/src/economic_session/read_projection.rs:1209）。目标 B 镜像里 recorded[].b_source_debit_proof.receipt 的 cut 不再被任何一层核对。本机实跑：向量 E:10/B:alpha:6/B:beta:4，B:beta 的记录带 B:alpha:9 的 Applied 回执，R6 的 projection（分页）、snapshot（单帧与分页）全部放行且应答含 commit_seq 9，浏览器 verifyProjection 同样放行；R5 同输入全部拒绝 MissingDependency。对照：回执改为 B:alpha:6 两头都过；键名改成 source_debit_proof 时 R6 拒绝。诚实 owner 下即可触发，只需读者选了目标 B 领先于源 B 的向量。修法：三层的检查与白名单改用 b_source_debit_proof，补一条三语言同输入的转入反例，并加差分测试（跳过来源数据子树的任意深度遍历找到的每个 cut 都必须被结构访问器访问到）。

## 非阻断项原文

1. MED Voice 开局依据位置写错：三层查的是 book.voice.identity.opening_basis.e_cut（economic_query.py:372-375、tb03a-client.js:748、read_projection.rs:1255），真实位置是 book.voice.records[].opening_basis.e_cut（voice.rs:170、:262）。本机实跑：records[] 带 E:12、向量 E:10，R6 三个入口放行，R5 拒绝。诚实 owner 会把同一 cut 写进仍被检查的 recorded[].cut，所以需要镜像不自洽才泄露。与 F1 同根因，应同轮修。
2. MED projected_record 白名单用了同一个错键（economic_query.py:208、tb03a-client.js:689、read_projection.rs:988）。本机实跑：事实原件的 projected_record 带界内的 b_source_debit_proof，R5 接受，R6 Python 以“未声明字段”拒绝。Rust 侧 copy_whitelisted_fields（read_projection.rs:1631）按表拷贝会静默丢掉该证明，此为读码。
3. MED 执行见证的权威回执白名单缺 authority_epoch：真实结构 rust/src/history_simulation/runtime.rs:404 固定带此字段，X_AUTHORITY_EVIDENCE_BASE_ALLOWED（read_projection.rs:948、economic_query.py:196）没有它，Rust 会丢字段。读码确认结构与白名单；Python/JS 拒绝带该键应答为分镜头评审实跑，本人未复跑。
4. MED 测试弱化：R5 放在未列举位置的未来 cut 诱饵（finance.decisions[].e_future_proof.cut、顶层 leaked_receipt）被挪到已列举位置（grant.e_cut、recorded[].e_receipt），见 s_session/tests/test_economic_read_projection.py 的 R5→R6 差异。未列举位置不再有覆盖，这正是 F1 没被测到的原因。
5. MED H1 的负控由测试里的假 Q 抛拒绝，客户端自身检查未被测到（test_tb03a_projection_client.cjs:311、:421）。变异测试结果来自分镜头评审，本人未复跑。
6. MED JS 白名单不按读权二选一（tb03a-client.js:677-691），无 QueryCommand 时仍接受带完整 command 的见证；Python 与 Rust 两层服务端拒绝，实际不泄露。分镜头评审实跑，本人未复跑。
7. MED known_cost_components[] 的 derivation.resolve_cut 一律当协议 cut（economic_query.py:364-371），来源拷贝分量若带同名普通字段会被误拒。写入方是否接受该字段只是读码推断。
8. LOW 回执缺 domain_id 时 Python 放行（economic_query.py:295-296），Rust（read_projection.rs:1110）与 JS（tb03a-client.js:916）拒绝。本机实跑确认 Python 两头都接受；cut 的域仍被核对，不泄露。
9. LOW collectPeerCutDependencies 对未校验的 commit_seq 直接 BigInt（tb03a-client.js:942），非规范文本抛原生 SyntaxError。
10. 基线已有：CI 不跑 test_economic_read_projection.py 与 test_tb03a_projection_client.cjs；拒绝应答的 detail 带出越界回执的域与序号（economic_query.py:245）。
