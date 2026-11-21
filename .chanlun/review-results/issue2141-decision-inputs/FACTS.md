# 固定源码、真实夹具及旧反例

## 代码事实（不是裁定来源）

固定 #2105 `4402c64d1ca78fbab9c3649b000e4c91178f60c0`（`candidate/1419-cut71-query-read`）。图谱 `search_graph` 用于定位 make_segment、segment_to_unit、judge_third_cert；其既存索引不是这个提交，且无 scan_center_facts，以下均以 `git show 4402c64d:<文件> | nl -ba` 定行。

| Git 路径及行号 | 观测事实 | 能证明／不能证明 |
|---|---|---|
| rust/src/theta_v0/parser/segment.rs:901–944 | 对成员笔的起末价取 min/max，按段方向排起终价；start/end_index 来自首笔 start、末笔 end，见 937–943。 | 几何边界坐标与投影价域分源；逐段保留真实区间不保证相邻极值相等。 |
| rust/src/theta_v0/classifier/pipeline.rs:136–153 | segment_to_unit 将起终价排序为 lo/hi，沿用方向及 K 序。 | 传递投影，不找共享转折价、不做缝合。 |
| rust/src/theta_v0/classifier/recursive_tower.rs:534–579、580–592、633–646 | seed 之后逐段闭相交；首不相交 j 切断（j<len）；不足 9 段终成员 j−1，Zn 聚合 [i,j)；j 为位置扫描出口，下一 seed 试位 j+1；j=len 仅开放。 | j 是停扫哨兵，不固有离开/回抽角色；不能窥探 j+1。read_end_src 只锚到旧哨兵 start，变更影响 497–512 所述增量保留前缀。 |
| 同文件 :594–631 | ≥9 段整窗重切，过渡实现对子窗聚合全单元。 | 继承 #1429 与正本 §9.5，不是另一条 R5 口径。 |
| 同文件 :794–824、840–867 | 趋势 ownership 可提供方向；盘整/首项用 fold_direction。上级区间由真实子走势包络构造（不是 Zn 外缘），全量与增量均以一个枚举投影。 | 枚举丢 origin；一个 Up/Down 不能区别走势语义、角色方向和占位。不是「所有上级方向都是占位」。 |
| [center_scan.rs:326–334](https://github.com/Newchanlun/NewChanlun/blob/4402c64d1ca78fbab9c3649b000e4c91178f60c0/rust/src/theta_v0/classifier/center_scan.rs#L326-L334)、[401–405](https://github.com/Newchanlun/NewChanlun/blob/4402c64d1ca78fbab9c3649b000e4c91178f60c0/rust/src/theta_v0/classifier/center_scan.rs#L401-L405) | `exit < len` 同时生成结算、突破和续扫锚；后段连接角色可由出口位置或自身试种失败直接获得。 | 两处均须消费 #1496 的共用事实，不能让 S 提前报连接、结算。 |
| [center_scan.rs:424–447](https://github.com/Newchanlun/NewChanlun/blob/4402c64d1ca78fbab9c3649b000e4c91178f60c0/rust/src/theta_v0/classifier/center_scan.rs#L424-L447)、[q3-center.js:463–470](https://github.com/Newchanlun/NewChanlun/blob/4402c64d1ca78fbab9c3649b000e4c91178f60c0/s_session/browser/q3-center.js#L463-L470) | Rust 断言非突破角色必有闭重叠，浏览器以位置等价校验 `BREAK_UNIT`。 | 接纳的外侧非 Zn 会触发断言或 `ROLE` 拒收；#1496 同拍分离 CC-018 五叶与构造角色。 |
| [content_structure.rs:1996–2007](https://github.com/Newchanlun/NewChanlun/blob/4402c64d1ca78fbab9c3649b000e4c91178f60c0/rust/src/bin/s_session_v3/content_structure.rs#L1996-L2007) | S 写者依 `wf.settled` 生成或复用 `settled_known_at`。 | #1496 要把新代际结算钟锚到实际获知切面，未证的边界不报时，旧史不回写。 |
| rust/src/theta_v0/classifier/signal.rs:295–344、365–389 | 旧证书比较 leave_anchor、retest 方向和端点价；趋势 c 历史另有去 anchor 和扫相邻对的逻辑。 | 旧输出只作差异对照，不代 CC-019 首回抽；本票不改点类。 |
| formal/Origin/CenterConstruct.lean:423–443、451–492、609–629 | extendWeak 的非 Zn 相交仍进成员、四指标按方向；refStep 旧单哨兵和 endE+2；refSeg4Break 手填离开 [22,25]。 | Z-5、S-7 的形式判例；settled=true 定理是旧扫描刻画，不是两段裁定或真实 L0。 |
| formal/Origin/CenterComplete.lean:83–97、137–160、261–286；BspClassification.lean:73–83、111–128 | 前者 DirAlternates/严格三段核心及 seed 反例，后者三类字段有 firstRetrace。 | seed 交替不能证明扩展流首回抽相接；Lean 点分类接已供给证据，并没有由占位、包络重建腿角色。 |
| src/newchan/a_zhongshu_v1.py:100–113、153–166 | 旧扫描吸收闭相交、全段聚合；旧 A 口径复用。 | 旧线 TB-10 账；不能作 #1496 备选生产口径。 |

## 实夹具重算

运行 `python3 joint_fixture.py`（完整输出见 `fixture.txt`）。固定提交的 `s_session/tests/fixtures/tb02e-real/btc-tail50k-first600.json` 自述来源 BTCUSDT 1m 尾 50,000、start_offset=5、前 600 根；冻结自组合树 #1419 `9cd64da5cd` + #1405 未合入 `199b820c9d`，是已成线段的合同输出，不是这次在 #2105 头重新运行解析。夹具 provenance 还说明当时工作分支缺 #1405，故不能把该片断当任意代码头的 parser 基准。

- 5 个下标关节全接，交替方向；价端相等依次 **否、是、是、否、是**。从每段实际成员首笔/末笔提取的源关节价五处全等（两个失配点分别 7759246000000、7796680000000）。这区分了「记录的边界结构相连」和「方向极值能首尾拼接」，并不证明遇到不等的出界候选时哪一个是首回抽。
- seed u0–u2 核心 [7762000000000,7773905000000]，u3/u4 仍重叠；u5 高 7709591000000 < ZD，正是 u4 向下离开后的相接向上回抽，唯一结算窗在此符合 #2114。前枢 [u0,u4]、Zn u0/u2/u4、连接首段 u5、续扫 6（到尾）。不存在本夹具里的「首不重叠且关节价不等」。
- **Q4 实际反例**：内部非 Zn u1 的低点 7755323000000 小于 u0 的 7756973000000 与 u2 的 7762000000000；所以在 u0..u2 种子前缀上，全成员 DD 较 Zn DD 少 1650000000。到整个 u0..u4 窗，u4 更低（7656433000000），两种错误/正确结果在 DD 上碰巧一致，不能用全窗相等证明原括注。u3 的高端与 u4 不相等，但 u2/u4 覆盖其完整价域；否的是「必被覆盖」，不是「缺一处等式必不覆盖」。

## C@u29 的恢复与替代

- `ls -la /private/tmp/goal1323-native-20261012/tb1424-prep-r2/` 和父目录均报 `No such file or directory`。#1419 [当时已记录父目录丢失](https://github.com/Newchanlun/NewChanlun/issues/1419#issuecomment-6224860070)。检查了本地 1424 prep/候选 Git 清单、各分支的对应路径和 `/Volumes/AgentStorage` 可读备料（未写），未发现这份末切面逐单元原件。组合树的另一份旧 BTC 尾窗还有 [#1419 自报错划段](https://github.com/Newchanlun/NewChanlun/issues/1419#issuecomment-6158963674)，不可把同数据集的旧绝对段数直接当现役读数。
- [#1424 的备料评论](https://github.com/Newchanlun/NewChanlun/issues/1424#issuecomment-6160553615) 内根裁 5 记 C@u29 在非 Zn u32 结算，下个 Zn u33 回核心；[#1496 正文](https://github.com/Newchanlun/NewChanlun/issues/1496) 转述「9 次结算中 2 次突破段是离开段本身」。源层级、方向、K 关节、极值、次数分母/分子，**均未独立核实**。别把 #1419「L3 读数」编号误当塔级，也别从 u29 的序号猜 L0。
- 替代证据各管一件事：上面 BTC 冻结夹具负责证明**真实 L0 关节价可失配、内部非 Zn 可超边**；`fixture.txt` 的 u29/u32/u33 同形**合成判别组**与 Lean refSeg4Break 负责算角色/成员/游标不同的结果，不达成 C@u29 的真实入锁。另读 #1424 公开给出的复验材料 `/Volumes/AgentStorage/issue1424-newbirth-witness-20261119/RESULT.md`：从合成 OHLC 由生产解析得到 L0、u4 连接（49→61）与 u8 退出，支持 #2114 方向相反的正常正控；数据不是旧 BTC 末切面，也不是公开写者 cut-111/123 的验收。
- 上级负例边界另见 [#1429 交棒](https://github.com/Newchanlun/NewChanlun/issues/1429#issuecomment-6445108239)：`/Volumes/AgentStorage/issue1419-div1605-probe-20261027/oracle-4934-from-cand-segments.txt` 的候选一侧在 bar4934 只列出一个 L1 枢（33→2357），其后上级窗口与回抽不能靠给旧/new 单元补方向猜出来。该 oracle 省略连接、方向全是问号、重切沿母核心（`/Volumes/AgentStorage/issue1709-pstack-orchestrate-20261025/1419-1605-REVIEW27BJ.md:48–55,92–94`）；只说明为何须等待真实上级血缘，非 C@u29，也非「已证明无首回抽」。
- #1496 后续片负责从合入版生产解析记录输入修订、级别、全部逐切面完成单元、关节源和方向出处，再核「9/2」与 C 的归属；若旧输入已不可恢复，保留原读数为未验证，改用**另一个带同一判别条件的真实例**证明验收，不能用本组人工 tick 顶替。
