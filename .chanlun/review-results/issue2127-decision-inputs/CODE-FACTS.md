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

### 独审补核：FIN 另一路入根、E 正式恢复升代

| 关注点 | 固定主线证据及结论 | 候选或证据边界 |
|---|---|---|
| `ActivateCapPolicy.policy_record.path`（原始搜索 `repo-hits.tsv:305`） | `finance.rs:45–121,765–790,1860–1931`：FIN/3、/4 启用受控激活；业务请求精确要求 `{path,sha256}` 且路径为绝对路径。两个写载体分别在 :1977–1981、:2080–2085 取签署原件；:335–348 要求普通文件、有界、UTF-8。:2221–2247 把完整请求及见证放进历史，写 E 根与回执；`service.rs:642–674` 核原消息并持久化请求和 payload 摘要。换绝对路径会改业务消息与 E 图像，不能只改导出 | `0afe42e2` 的 `finance.rs:874–879,2072–2077,2179–2186,2319–2338` 仍同链。静态可达证据，不改变 R6 的 Voice/X 差异归因 |
| 签署、版本、责任与原件 | `finance.rs:124–174` 按原 UTF-8 字节核摘要及签署记录类型、签署者/引用、资金 profile/政策/量纲、版本和时点。:1476–1521 在当前 E 政策版本及原子点核有效期、既有公共责任和 cap。:1811–1849、:1891–1917 核原回执、原消息及重送身份；同身份原回执查回先于读取外部件 | `finance_tests.rs:1555–1565` 在夹具目录写 TestOnly 合成签署件，:1741–1772 用 E 入口验证 cap 等于责任仍可激活、原消息重送返回原回执；不涉及真实资金 |
| `writer_epoch`、`epochs` 与恢复切面 | `store.rs:797–805,829–835` 初始化代 1 与 `init` 行；:1075–1086 审计行数和最大代；:1694–1725 审计库，按恢复时钟升一代、加 `recover` 行、返回原切面；:659–664 核当前代。E 从 1 正式恢复一次与未中断臂必有 2/1 和两行/一行之差 | 正式原址和锁见 [#2079 裁定](https://github.com/Newchanlun/NewChanlun/issues/2079#issuecomment-7051663296) 与其 ADR 0065:54–64。写者履历不从正式验收删除 |
| 纪元、时刻进入 E/B proof | `finance.rs:829–855` 将被引用域的 `current_epoch`、`current_epoch_at_ns` 与原回执、原/当前 cut 和图像送入 proof；:890–952 核原/当前根与原回执，:2184–2207 写事务核代和最后提交/恢复时点的时钟下限，再进 :2221–2239 的历史和根 | H2 对连续臂按逐臂真实有效纪元、获知时点和实际根链核证，不丢弃代/时间/根。S3 的投影是组件试验条件，不直接沿用 |

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

`origin/main:.chanlun/review-results/issue1406-owner-20261020/S3-REPORT.md:95–151,212–224` 区分同一故障轨迹重复两次的完整表（含 `meta`、`epochs`、根和时刻）等值，以及对无崩溃参照的投影。前者为控制旧 `meta.manifest_hash` 而复用同一绝对路径，后者是特定时钟的组件记录。S3 没覆盖 BindVoice，既不证明异目录全表等值，也不证明 #1411 正式 H2。#1425 这次已经直接观察到 commits.root/prev_root 变化。
