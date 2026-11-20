# #1425 R7 非作者裁定：PASS

绑定头 `0afe42e2e9f83855552c9e9c5a5894805d5ee594`，对照 `76187c7a`。

目标是三层读侧在固定切面向量下不带出未来事实、不越读权、合法读能成功。三个镜头没有 HIGH 存活。我逐项开码并在 Q 公开入口实跑，也没有找到 HIGH，所以放行。R6 的 F1 与三条 MED 已关闭。剩余问题是锁的覆盖面和潜在项，列为非阻断。Rust 结论全部是读码。

## 在此实跑（Python 3.14.4、Node 22.22.1，临时工作树）

- R7 头：`test_economic_read_projection` 16、`test_tb03a_query` 9、`test_tb03b_query` 16、`test_tb03c_query` 30、`test_c6a_economic_pagination` 14 全过。`test_tb03a_projection_client.cjs` 12 过 0 败。R6 头同套为 13/9/16/30/14 与 4 过。
- R7 测试文件配 R6 代码：cjs 2 过 10 败，Python 16 失败 3 错误。
- 自写探针经 `economic_http.post`，向量 E:10 / B:alpha:6 / B:beta:4，走 projection 分页、snapshot 分页、snapshot 单帧，两头各跑：

| 输入 | R6 | R7 |
|---|---|---|
| `b_source_debit_proof.receipt` 为 B:alpha:9 | 三入口放行 | 三入口拒 MissingDependency |
| 同上 B:alpha:6（对照） | 过 | 过 |
| 证明内 `image.recorded[].cut` 为 E:12 | 放行 | 拒 |
| `book.voice.records[].opening_basis.e_cut` 为 E:12 | 放行 | 拒 |
| 同上 E:10（对照） | 过 | 过 |
| 未列举位置 `e_future_proof.cut` 为 E:12 | 放行 | 拒 |
| `event`、`raw_exact_text` 内 cut 形状的 E:12 | 过 | 过 |

- Watch 探针（单帧与分页，E:4→E:5）：变化镜像带 B:alpha:9 回执或未列举 E:12，R7 拒、R6 放行。界内对照与来源子树对照两头都过。
- 变异五种，每次还原，结果见锁一节。
- 未运行 cargo、rustc、`tb04f_single_owner_entry.py --read-coverage`。镜头评审的 1500 与 8568 例对拍未复跑。工作树与探针已删，主仓干净，未编辑、提交、推送、评论。

## 逐项状态

- **R4(a) 固定切面不带未来事实：CLOSED。** 上表与 Watch 探针。结构检查在 `s_session/economic_query.py:401`、`:429`，兜底在 `:567-579`。浏览器在 `s_session/browser/tb03a-client.js:824`、`:777`、`:991`。
- **R4(b) 仅分配读权不得拿完整命令：CLOSED。** `economic_query.py:619` 的读权校验本轮未改，`test_enumerates_three_single_permissions_for_invariant_b` 与 `r4_3` 通过。
- **R4(c) 历史根缓存计入共享预算：CLOSED。** `economic_http.py` 不在差异内，`economic_query.py` 的差异不触及缓存函数，预算用例通过。
- **R5-H1 双域 Watch：CLOSED。** cjs 的 R6 #1 用例与新增的客户端自检负控通过。
- **R5-H2 来源数据同名字段：CLOSED（原反例）。** 同类的窄化残留见非阻断第 1 条。
- **R5-M3 回执归属域：CLOSED。** 对应用例通过。缺 `domain_id` 的回执 Python 现在也拒（`economic_query.py:348`）。
- **R5-M4 五层正向白名单：CLOSED。** 对应用例通过，白名单补了 `authority_epoch` 与真实键。
- **R6-F1（HIGH）：CLOSED。** Q 与浏览器实跑关闭。Rust 读码：读写双方共用常量（`tb03c_transfer.rs:10`、`read_projection.rs:1264`）。
- **R6-MED Voice 位置：CLOSED。** 实跑如上。Rust 读码：`read_projection.rs:1311-1318` 用 `voice.rs:9-11` 的常量。
- **R6-MED projected_record 错键：CLOSED。** `test_r7_writer_fields_survive_original_exit` 通过。
- **R6-MED authority_epoch：CLOSED。** 一致性用例把三层白名单与 `history_simulation/runtime.rs:399` 的 Receipt 结构逐键比对，通过。

## 四把锁是否把清单绑到写入方、是否进 CI

- **A 差分：绑定成立，自动运行的只有一小块。** 探针取自真检查器的 `checked` 集，不是平行实现。全语料版要 Rust 二进制加 `--read-coverage`，Rust 对应用例带 `#[ignore]`（`read_projection.rs:3604`），没有工作流引用。镜头评审说“没有任何自动门”不准确：`tb03c_c5_tests.rs:417` 的非 ignore 用例对真实转入写入方产物调 `assert_writer_cut_coverage`（`:485-486`），落在 `ci.yml:609-611` 的 `economic_session` 过滤器内。这一条是读码。作者的 201/447→0 无法复核。
- **B 键名绑定：部分成立。** Rust 四个名字靠共享常量在编译期绑定。Python 与 JS 只有两张白名单被用例绑到 Rust 源。变异：改写入方转入常量值，Python 用例红。改 `voice.rs` 的 `OPENING_BASIS`，Python 16 与 cjs 12 全绿。
- **C 诱饵回到未列举位置：成立**于 projection、snapshot 与假入口。original 与 watch 入口的诱饵仍在已列举位置。
- **D 三语言同输入反例：Python 与 JS 成立，Rust 一腿走生产不用的入口。** 变异：Python 结构键改回 `source_debit_proof`，85 条全绿，公开入口仍拒，因为兜底接住。JS 同样改键则 1 败。
- **CI：** `ci.yml` 本轮零改动。本区 Python 与 Node 用例都不在 CI。按 s-observer（`:1267`）的 discover 写法直接跑报 ModuleNotFoundError，要加 `PYTHONPATH=s_session`。CI 里只有 Rust 库测试会带上非 ignore 的 r7 用例。

## 非阻断项

全文见 non_blocking。两条建议同票跟进：`history[].source` 这类来源拷贝位置的形状误拦，以及 Q 不发送 `fixed_cuts` 使 Rust 跨域界限在生产路径不生效。前者本人实跑复现，仓内来源生产方今天不会触发。后者不泄漏，因为 Q 和浏览器已实跑拦住。

## Rust

`read_projection.rs`、`service.rs`、`voice.rs`、`tb03c_transfer.rs`、`tb03c_c5_tests.rs` 的结论全部来自读码。r7 用例与 C5 转入用例是否通过是作者的 Linux 声明，未经独立复跑。合入前须在这个精确头上由 CI 或独立 Linux 运行确认。

## 非阻断项全文

1. MED 来源拷贝位置的形状误拦（R5-H2 同类，面更窄）：兜底跳过表只认 5 个键名（s_session/economic_query.py:220、s_session/browser/tb03a-client.js:737、rust/src/economic_session/read_projection.rs:1522-1531），但 history[].source 由写入方原样拷贝（tb03c_book.rs:878、:1023、:1175，book.rs:543），来源只查必填键。本人实跑：B:beta 的 history[].source 内放一个恰好三键 {domain_id:'vendor-ledger',commit_seq,root_hash} 的对象，R7 的 projection 分页、snapshot 分页与单帧都拒“回执所属域 vendor-ledger 不在固定向量中”，R6 放行；同位置普通对象两头都过。仓内来源生产方的 source 是扁平文本（history_simulation/store.rs:276、:310），今天不会触发；book.units 被写入方校验为数值文本（tb03c_book.rs:416），够不到。修法：按写入方位置把 history[].source 与 event 同等视为来源数据，三层同改并补同输入用例。
2. MED Rust 跨域界限在生产路径不生效：check_protocol_cut 只在拿到向量时约束他域切面（read_projection.rs:1084-1094），向量来自可选的 fixed_cuts（service.rs:758），而 Q 的两处 owner 请求不带它（economic_query.py:1997-2002、:2195-2201；grep 确认 s_session 里 fixed_cuts 只出现在分页描述符）。跨域界限仍由 Q 和浏览器把守，这两层已实跑确认，不构成泄漏。Rust 的转入反例测的是生产不走的入口。修法：Q 把已核向量作为 fixed_cuts 传给 owner 并加端到端用例，或删掉未用入口并写明分工。读码，未运行。
3. MED 锁 A 的全语料版只能手动跑，且语料取在 B 应用成交和费用之前：tb04f_single_owner_entry.py:1291-1296 在第 6b 步取语料，Apply 在其后；rust/tests/tb04f_read_cut_coverage.py:51 需要 Rust 二进制与 --read-coverage，Rust 对应用例带 #[ignore]（read_projection.rs:3604）。本票主体之后才出现的位置（recorded[].e_resolution_proof 三项、派生成本分量的 resolve_cut、B 域 fact 与 allocation 原件）只被手写夹具覆盖。按读码这些位置已在结构清单内，e_resolution_proof.request（tb03c_allocation.rs:449）的载荷里没有 cut 形状。修法：在终态 Applied 切面再调一次 check()，并把语料落成仓内 fixture 或接进有二进制的 CI 作业。
4. MED Python 结构访问器的修复没有自动用例钉住：本人实跑变异，把 economic_query.py:401 改回 source_debit_proof，5 个 Python 套件 85 条全绿，公开入口仍拒 B:alpha:9，因为兜底接住了。丢的是该位置的回执归属域核对。JS 同样改键则 1 败（断言 unlisted 为空）。修法：test_economic_read_projection.py:1193 的转入与 Voice 正例传 unlisted_paths 并断言为空。
5. MED 锁 B 只绑了两张白名单：test_economic_read_projection.py:1299 比对 X 权威回执结构和 B 记录剥离表。本人实跑变异：改 tb03c_transfer.rs:10 的常量值，Python 用例红；改 voice.rs:10 的 OPENING_BASIS，Python 16 与 cjs 12 全绿。Python 与 JS 访问器取的键、Voice 位置名、E 记录键（service.rs:908）、见证键（tb03c_sim_resolve.rs:206）没有绑定。镜头评审另报读侧访问的 book.cost_events 在写入方无写入点，Rust 的 copy_whitelisted_fields 对白名单外字段静默丢弃，本人未复跑。
6. MED 本区 Python 与 Node 用例不在 CI：.github/workflows/ci.yml 本轮零改动，s-observer（:1267）不含 test_economic_read_projection.py 与 test_tb03a_projection_client.cjs。本人实跑：按 s-observer 的 discover 写法直接跑报 ModuleNotFoundError: economic_query，加 PYTHONPATH=s_session 后 16 条通过。R6 已记为基线。
7. MED 浏览器白名单只对 command 与 command_ref 按读权二选一：tb03a-client.js:1128 推出 hasCommand，但 PROJECTED_RECORD_ALLOWED（:693）同时放行 resolved_allocation 与 resolved_allocation_ref，无分配读权时也接受 fill_allocation_row。Python 出口按读权拒绝（economic_query.py:645-658），所以不泄露。R6 头同样如此。读码确认；三例分歧为镜头评审实跑。
8. LOW 兜底与差分锁共用的遍历器有两个盲区：只认恰好三键的 cut，且任意深度跳过名为 event 的键。本人实跑：未列举位置放四键的 E:12，或把 E:12 回执挂在名为 event 的键下，R7 三入口都放行。写入方唯一的 cut 构造点 store.rs:710 恒为三键，所以现在不泄漏，但文档串里“新增位置也无法带出未来切面”的保证不成立。
9. LOW 原件外壳缺 domain_id 时 Python 放行，JS 与 Rust 拒（economic_query.py:489-532）。基线已有，Rust 序列化器固定写出该字段。镜头评审实跑，本人未复跑。
10. LOW 锁 C 在 original 与 watch 入口未恢复：决定原件的诱饵仍在已列举位置 grant.e_cut（test_economic_read_projection.py:706、:739）。行为本身正确：本人的 Watch 探针里未列举 E:12 被拒。
11. LOW Watch 的依赖闭包只走结构访问器（tb03a-client.js:1000 起），兜底才看得到的跨域依赖会让成对推进卡住。失败方向是拒读。镜头评审的三域探针实跑，本人未复跑。
12. LOW 若干浏览器新行为无用例钉住：watch() 末尾的整份变化核对与逐批快照核对互为冗余，经回执取依赖、缺 domain_id 的拒绝、verifySnapshot 的 tb03c cost_totals 分支都没有专门用例。镜头评审变异实跑。cost_totals 分支按读码是放宽：旧书账无 book_revision，仍走 known_cost_totals。
13. 基线已有、本轮未变：拒绝应答的 detail 带出越界回执的域与序号（economic_query.py:287、:296）。
