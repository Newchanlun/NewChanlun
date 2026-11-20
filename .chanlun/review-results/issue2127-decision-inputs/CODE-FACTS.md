# 代码事实：从 artifact 定位到持久根

主线：`origin/main` = `b9d898dccf46c2a716115eaa1215bc39c458a959`；候选实查：`origin/candidate/1425-single-owner-r4` = `0afe42e2e9f83855552c9e9c5a5894805d5ee594`。下文路径省略 `rust/src/economic_session/` 前缀时用文件名表示；X 单列 `rust/src/history_simulation/runtime.rs`。链接可用 `git show <SHA>:<仓内路径> | nl -ba` 复核。运行原件来自同候选线**较早** R6 `76187c7a219d00fb499585eb7dbbe5c86dcb9a9f` 的证据，不是最新候选或主线的实跑。

| 字段 / 数据 | `origin/main` 写入点与读口 | 怎么进根 | #1425 候选是否相同 |
|---|---|---|---|
| artifact 的 `name/path/sha256/bytes`；两份文档中的 `artifacts` | 主线的消费方不生成权威或独评；输入生产形状见 `voice_tests.rs:260–285`：夹具按文件生成带 path 的条目，bundle 收进去，独评复制条目并绑定 bundle 摘要。生产 `evidence.rs:141–161` 读取承诺的原始两份文件，不生成、不修剪 path | 两份见证原始字节及其各自摘要都受路径影响；文件内容摘要本身不因位置变化而变 | 消费链相同。候选另有驱动 `rust/tests/tb04f_single_owner_entry.py:42–80,217–239,269–289`（R6 对应 :42–80,214–236,266–286）：`--out` 解析为绝对目录；子跑均用同一个 `case`，实际写出五类 artifact 和两份含路径的文档；manifest 固定两份文档的位置与各自字节摘要。候选该入口不存在于主线；见证是明标的 TestOnly 信任夹具，不是真实 γ 独评 |
| `bundle_path` / `verification_path`；artifact 内 `path` | `evidence.rs:46–80,95–126,129–175`：前两者定位文档；先核 manifest 固定的文档摘要和独评关系，再按 artifact.path 读本机普通文件，核摘要与精确长度（受大小界约束）；候选与主线同为严格绝对路径 | 前两者直接进入旧混合 manifest 的摘要；内层 path 在 bundle/独评的原字节中进 B 图像。两组路径不是一回事 | :95–175 完全相同。:45 组件时钟门从仅 TestOnly 变为 `component_clock`；不改变任何 path 校验或根输入 |
| 旧独评、闭包与 `evidence` 引用 | `evidence.rs:178–263` 核两份精确字节、authority、批准判定、独评绑定的 bundle 摘要、条目逐项相等、闭集/长度/五种角色、唯一 evidence ID 全部覆盖；:285–354 核标的/载体/γ、来源输入、开局原件摘要、时钟，并生成 `{authority_id,bundle_sha256,verification_sha256}` | `voice.rs:262–265` 把两个摘要作为 Voice record.evidence 纳入 `book.voice.records`；这一步即使不内嵌原文也会受 path 影响。不等于 `voice_id` 自身用文档摘要：其配方见 :227–237，绑定引用和会话等 | `evidence.rs` 同行同字；`voice.rs:234–244,269–272` 同义，候选把 JSON 键提为常量，未换配方 |
| `BindVoice.evidence_witness`，B 原图与回执 | `service.rs:1213–1224,1240–1263`：B 先载入已验证对象，事务内把 record 写进图像，在 `history` 附 `voice::history_event`，更新 book，`append` 后将带 cut 的回执和原消息同事务持久提交。事件见 `voice.rs:272–278`；调度仅 B，`service.rs:1472–1474` | **直接进 B 根两次**：见证内原字节和 book/history record 内文档摘要均随图像哈希承诺（不是说恰有两份物理拷贝） | `service.rs:1375–1386,1402–1425`、`voice.rs:279–286`；同链 |
| B 的 `image/current_image` → E 图像 | `finance.rs:829–855` 读 B 原回执 cut 的提交图和当前图，随 previous_root、epoch 等返回；:1948–1965、:2103–2117 形成 Reserve.witness.prepared_proofs，:1291–1308 验；:890–950 对两图和回执算根；:2221–2239 witness 进 E history 再 append（`commit_proof` 另见 :1985–1989） | **间接进 E 根**。E 不拥有 Voice，不接受直接 BindVoice；是持久 proof 内嵌真实 B 图，不是 E 再跑 B 的绑定。路径让早期根改变后还由 previous_root 传给后继 | `finance.rs:904–943,978–1038,1379–1396,2046–2059,2202–2218,2319–2338` 同机制；候选新增 FIN/6 与读投影不替代此链 |
| E 原事实/e_commit_proof/解析分配证明 → B | `service.rs:930–948` 把 E 历史提交图与 cut/回执附到 B 副本；:1115–1137 将副本送入 book reducer 并写 B facts；`store.rs:1612–1633` 重算 E 原根；本地 `append` 见 `service.rs:1149–1168`。融资侧 CommitDecision 对 E grant 亦内嵌证明（`finance.rs:1970–1975,1391–1397`） | 受影响的 E 切面一旦成为依赖，连带传入 B 的 facts 与提交图，不止初次绑定的重。R6 里 beta 的差异与跨重传播相符；不逐项归因到某个 beta 事件 | 候选 `service.rs:1092–1111,1277–1299,1311–1330`、`store.rs:1689–1709`；解析另加字段/核验，原 proof 和根传播保留 |
| E/B `commits.{seq,prev_root,commit_ns,image,root}` | `store.rs:665–682,766–776,1099–1114`；`book.rs:55–57`、`session_protocol.rs:135–158` | 摘要式为 `SHA256(canonical_json({domain_id,session_id,session_generation,commit_seq,previous_root,commit_ns,image_hash}))`，`image_hash=SHA256(canonical_json(image))`；对象排序、数组保序、字符串保持其内容，故原文串不是注释。图像全量入根，依赖 cut、receipt 里承诺真实根；数据库表直接不全是顶层哈希参数 | `store.rs:709–726,837–852,1175–1190` 与 `book.rs:55–57` 同算法与字段。写根和审计同式 |
| E/B `meta.manifest_hash` | `store.rs:281–301,797–805,993–1003`：由完整混合 manifest 计算，初始化持久化，audit 逐值要求与配置同一；`service.rs:333–350,470–482` 亦作 Transfer 证明匹配/查询回显 | **不是根公式的直接字段**；路径不能据此归因为每个根不同。任何真正进入图像的 manifest 派生字段仍由全图像承诺，新格式同时切断部署摘要的间接流，不削配置门 | `store.rs:294–314,873–881,1069–1080`；`service.rs:433–451,587–599`；同区分 |
| B 的旧见证审计 | `voice.rs:280–321,332–384` 从 messages 核原请求与摘要、按事件内见证走 `verify_witness`，复演比较事件；`evidence.rs:179–354` 使用原始两文档及固定 manifest，不从路径重新读取 5 类 payload | B 重放核原证据摘要/结构及事件同值；外部 artifact 在初次 live load 读过，现有重放不重读。只有原根通过并不证明归档已补齐所有被独评的字节 | `voice.rs:287–328,339–391`、`evidence.rs:179–354` 同机制 |
| X `x_sim_meta.v` 中的 `authority_profile` | `rust/src/history_simulation/runtime.rs:28–95,790–864`：在初始化事务写整个序列化 Profile，含 `socket`、`e.socket`、`s.socket`；未枚举剔除。先 audit，整份规范字节不等报 `IdentityConflict`。X 实际 bind/使用路径（:866 起，`authority_connect` :486–489），而对方身份与代依 :506–517 核原信封 | **X 持久启动准入绑定**，不是说明文字；不是 E/B 根公式的直接输入。位置与真正的 E/S 权威身份、代、来源与 schema 同居一行。R6 观察独立的 X v 变化，不把它当 B→E 根传播原因 | `runtime.rs:31–59,666–696,1176–1208,1215–1243,1267+`，同样保存整份并拒变化；候选外/内版本选择更严 (:1096 起)，增加 X 旧版本只读审计按版本解释 (:1344–1366)，不是去路径 |

### TB04F 与 #1406 的适用域

Mac 原报告 [`tb04f-size-diff.md`](file:///Users/silencehan/.t3/evidence/issue1425-r7/tb04f-size-diff.md) 与下表是同一个读数。固定 R6、同一 Boat Linux 环境及二进制，输入 `input.json` 同值，分别只换 `--out`。各自的 `--twice` 两臂仍顺次复用其各自同一个 `case` 位置，均逐字节相同、exit 0；这不是跨目录对拍。对两种位置各保留一份完整导出做表差分，行数不变。

| 域 / 表 | 总行数 | 变化列（变化行） | 增量 B | 路径次数 |
|---|---:|---|---:|---:|
| B:alpha / commits | 7 | prev_root 4；root 5；image 5 | 97,610 | 2,270 |
| B:alpha / facts | 3 | json 2 | 56,760 | 1,320 |
| B:beta / commits | 5 | prev_root 2；root 3；image 3 | 4,730 | 110 |
| E / commits | 11 | prev_root 6；root 7；image 7 | 58,480 | 1,360 |
| X / x_sim_meta | 4 | v 1（authority_profile） | 129 | 3 |

两处各为 28,813,475 B 与 29,031,184 B；相差 217,709 B，等于路径前缀差 43 B × 5,063。等长变化另见 B:alpha / B:beta 的 book.json 各 1 行、meta.v 各 1 行、receipts.json 5/3 行，E 的 meta.v 1 行、receipts.json 7 行。报告的注意事项：第一次表差分错选 B:alpha 库，修正后的两位置差分 exit 0。候选驱动的 “business” 是 SQLite 逻辑导出，并不宣称 SQLite 文件页字节可比（主线/候选代码事实与已有 R6 实测分别计证）。

`origin/main:.chanlun/review-results/issue1406-owner-20261020/S3-REPORT.md:127–139,212–224` 是同路径先例：提到复用绝对目录只为 `meta.manifest_hash`；投影比较受恢复时钟等条件限制，且 S3 没覆盖 BindVoice，不能把这段话推广为「去掉 meta 就能异目录全表相同」。#1425 这次已经直接观察到 commits.root/prev_root 变化。
