# #1426 形成侧内核第三轮设计定稿

## 1 目标
内核从一份同级单元序列判定每对相邻中枢是否形成上涨或下跌趋势。证据按构造无法伪造，已形成的前缀在追加单元后逐字段不变，#2114 的确认时点只落在一处。

## 2 换掉的前提
两轮共用的前提是「先收调用方组装的证据，再校验」。读码证伪：第二轮最保守的 `judge_from_scan` 收 `CenterScanFacts`，它字段全 pub（center_scan.rs:107-118），入口只核长度（5e66d04f trend_formation.rs:940）。新前提是内核只收单元来源，自己跑共用扫描。中枢、结算、突破段、连接段、升级标记、对关系全部从同一份切片推出。证据类型没有构造器，也没有函数以证据为入参。

## 3 全部公开项（`classifier/trend_formation.rs`）
```rust
pub fn judge_trend_formation(unit_level: u32, units: &[UnitRange]) -> TrendFormation;

impl TrendFormation {
  pub fn unit_level(&self) -> u32; pub fn unit_count(&self) -> usize;
  pub fn centers(&self) -> Vec<&CenterNode>;
  pub fn pairs(&self) -> &[PairJudgment]; // 全部相邻对
  pub fn final_pairs(&self) -> &[PairJudgment]; // 右端已结算的前缀
  pub fn consolidation(&self) -> Option<&CenterNode>; // 全链恰一个窗口，且未被标升级
}
impl CenterNode {
  pub fn ordinal(&self) -> usize; pub fn members(&self) -> &UnitSpan;
  pub fn break_unit(&self) -> Option<(usize, &UnitRange)>; // None ⟺ 开放
  pub fn is_settled(&self) -> bool;
  pub fn center(&self) -> Option<Center>; // None ⟺ 扫描器标升级
}
impl PairJudgment {
  pub fn left(&self) -> &CenterNode; pub fn right(&self) -> &CenterNode;
  pub fn connectors(&self) -> &UnitSpan;
  pub fn outcome(&self) -> PairOutcome;
  pub fn state(&self) -> PairState;
  pub fn is_final(&self) -> bool; // 右端已结算
  pub fn formed(&self) -> Option<FormedTrend<'_>>;
}
impl UnitSpan { pub fn range(&self) -> Range<usize>; pub fn units(&self) -> &[UnitRange]; }
impl<'a> FormedTrend<'a> { pub fn direction(&self) -> Direction; pub fn pair(&self) -> &'a PairJudgment; }

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum PairState {
  TrendFormed { direction: Direction },
  ProvisionalSeparation { observed_direction: Direction },
  ExpansionHandoff, // 交上级（#1429）
  CoreNotStrictlySeparated,
  UpgradeDeferred, // 任一端被扫描器标记，本级不判
}
```
`unit_level` 是单元序列的塔级下标，0 表示 L0 已确认线段（pipeline.rs:959）。不带 `self` 的 `pub fn` 只有入口。下游要「已形成」凭据时收 `FormedTrend`、`&PairJudgment` 或 `&TrendFormation`，不收 `PairState` 或裸 `Direction`。

## 4 数据形状与可见性
```rust
pub struct UnitSpan { start: usize, units: Box<[UnitRange]> }
pub struct CenterNode { ordinal: usize, members: UnitSpan, break_unit: Option<UnitRange>, center: Option<Center> }
pub struct PairJudgment { left: CenterNode, right: CenterNode, connectors: UnitSpan, outcome: PairOutcome }
pub struct TrendFormation { unit_level: u32, unit_count: usize, chain: Chain }
enum Chain { NoCenter, Lone(CenterNode), Linked(Vec<PairJudgment>) } // 私有
pub struct FormedTrend<'a> { pair: &'a PairJudgment, direction: Direction }
```
前五个类型只派生 `Debug, Clone, PartialEq, Eq`，`FormedTrend` 只派生 `Debug, Clone, Copy`。字段全部模块私有，不写 `pub(crate)`、`pub(super)`、`new`、`try_new`、`Default`、`From`、`Deserialize`。值只在入口函数体里出生：
```rust
let scan = scan_center_facts_full(units, seed_build(unit_level));
// 节点 k：members = span(units, w.seed_at..w.exit)，break_unit = units.get(w.exit).copied()，
//   center = (!w.upgraded).then(|| scan.window_center(units, k))
// 对：逐项取 scan.pair_facts(units)，left/right 为节点克隆，connectors = span(units, pf.connectors)，outcome = pf.outcome
// chain：零个窗口 NoCenter，一个 Lone，其余 Linked
```
状态、方向、结算下标都不存储，突破段下标即 `members.range().end`。`state()` 每次现算：`PendingUpgrade` 给 `UpgradeDeferred`；对 `PairLeaf` 穷尽 match，新生两叶合成一臂，方向取 `leaf.direction()`（center.rs:187），再由 `confirmed` 分成已形成与临时分离；扩展两叶给 `ExpansionHandoff`；首叶给 `CoreNotStrictlySeparated`。`formed()` 只读 `state()`。模块内不出现 `Direction::Up`、`Direction::Down`、`UPGRADE_TOTAL_SEGMENTS`、`center_pair_facts`、`pair_domain_ok`。私有函数只有 `seed_build`、`span`、`confirmed`。

`seed_build` 在 0 级返回 `center_from_segments`，其余返回 `center_from_window`。这是唯一读 level 的地方，照抄塔的分派（recursive_tower.rs:409-416、:706）。注释写明它是 E1，已由 #812 Z-3 裁为伪分歧（doctrine-rules.md:102-104）。不改收 `SeedRule`，那会放出塔从不产生的组合（0 级配几何判据）。

## 5 权威输入（@9e57032b，只读）
- 信任根只有 `units`（center.rs:83）和 `unit_level`。L0 调用方传 `l0_units(layer.segments_valid_prefix())`（center_scan.rs:29，parser/mod.rs:150）。
- 扫描 `scan_center_facts_full`（center_scan.rs:121），窗口 `ScanWindow`（:60），结算即 `exit < len`（:326）。
- 中枢 `window_center`（:410）。对与连接段 `pair_facts`（:461，区间 :479，`PairOutcome` :288）。五叶 `PairLeaf`（center.rs:157），判据只在 `center_pair_facts`（:328）。
- 不作输入：`CenterScanFacts`、`ParseLayer`（字段全 pub）。不读 `scan.centers`、`scan.metas`（塔的重切子中枢）。
- 教义：M-2（qushi.md:124-131），Z-5（zhongshu.md:398），Z-6（:416），S-4③（:290-296，基座未实现）。第二轮模块头引文已过审，照搬，S-4 一条改写为「只转述扫描器标记」。

## 6 十一个反例
| 反例 | 排除方式 |
|---|---|
| R1-a | 入口没有结算参数。B 是否结算只来自 `units.get(B.exit)`，B 开放时只能是临时分离。 |
| R1-b | 连接段不是输入，只由 `pair_facts` 的区间从同一切片切出。重复、乱序、成员冒充都写不出来。 |
| R1-c | 没有中枢构造器。`center()` 为 Some 当且仅当扫描器未标升级，被标窗口所在的对只能是 `UpgradeDeferred`。 |
| R1-d | 方向不存储，不由调用方给，每次从该对的叶现算。`PairState` 不装证据，`FormedTrend` 字段私有。 |
| R1-e | 每对内嵌左右节点和连接段内容并派生 `Eq`，两对在序号、成员、连接段上必不相等。 |
| R2-1 | 没有整链判词和整链方向。右端已结算的对在追加后不变（M1），开放对只是 `pairs()` 的末项。 |
| R2-2 | 结算态存的是从来源读出的单元内容，不是可手填的下标。只有 u0..u7 时 `units.get(8)` 为 None。 |
| R2-3 | 连接段的下标和内容出自同一次读取。改 `units[4]` 等于换来源，整体重扫。 |
| R2-4 | 内核不数段，没有阈值和带计数的错误类型，只转述扫描器标记，不说「必须升级」。 |
| R2-5 | 内核只读 `windows`，被标窗口不产 `Center`，没有收 `Center` 或成员区间的入口。把 3..6 另传是独立扫描，核心由这三段自己算。 |
| R2-6 | `pairs()` 含全部相邻对。只改 A 时 `pairs()[0]` 的左节点、叶、状态都变。 |

## 7 整链语义与单调性
结果是一本账：全部节点加全部相邻对。内核不做同向延续分组。中心定理二按相邻对陈述，S 上待替换的 `NOT_ASSERTED_DEFERRED_1426` 是对上的字段，分组在塔里已有一份（recursive_tower.rs:373）。多中枢从不回落成盘整。
设 P 是 Q 的单元前缀，级别相同，F、G 为两者的结果，s 为 F 中已结算节点数。
- M1：`G.pairs()` 的前 `F.final_pairs().len()` 项与 `F.final_pairs()` 逐项相等。
- M2：`G.centers()` 的前 s 项与 F 的逐项相等。
- M3：F 中 `TrendFormed` 的对在 G 同位置整项相等。
- M4：只有末节点可以开放。

不单调的只有三处：右端开放的末对、`consolidation()`、开放窗口的升级标记。临时分离的后继只有四种：同向已形成、同向临时分离、同向扩展、`UpgradeDeferred`。保证只对单元前缀成立，按 K 线追加的测试先断言单元前缀未变。

## 8 确认点
唯一位置是私有函数 `fn confirmed(pair: &PairJudgment) -> bool { pair.left.is_settled() && pair.right.is_settled() }`，只被 `state()` 的新生臂调用。`is_final()` 表示这一项在追加后不再变，#2114 不改它。#2114 若裁开放期即确认，只改这个函数体和测试 12 对照表的两行，M3 按裁定重述。

## 9 从第二轮删除（行号指 5e66d04f）
在 `impl/1426-trend-formation` 上续提交，不改写历史。`trend_formation.rs` 整文件重写，不留兼容入口。删除 `:32-849` 的全部标签、证据类型、错误枚举与校验函数（含三个 `try_new`），五个 `judge_*` 入口（:852-934），`build_validated_chain_pairs`（:988），`judge_sequence_core`（:1032）。`extract_scan_chain`（:936-986）去掉 `try_new` 后就是入口函数体。仓内测试 `classifier/tests/trend_formation_1426.rs` 和 `tests/mod.rs` 那一行一并删。夹具删 `chain_9011_synthetic`，schema 升 `/3`。`classifier/mod.rs:86` 保留。

## 10 测试
全部放 `rust/tests/trend_formation_1426.rs`。它是外部 crate，由现有 `cargo test --all-targets`（ci.yml:473）执行。合成单元由端点序列生成，相邻两端点一段。单调性与 5、8 到 11、13、14 的期望值已在仓外 Python 扫描模型上核过（919,916 个前缀切面无反例，两处植入缺陷均被报出），不是 Rust 实测。
1. `down_123_provisional_at_111_formed_at_123`：111 根时临时分离 Down，连接段 4..5 且内容等于 `units[4]`。123 根时已形成 Down，B 突破段下标 8，左节点与连接段不变。
2. `up_mirror_123`：`8500 - p`，方向翻转。
3. `open_b_fork_202_never_formed`（R1-a）：111..=202 每个前缀都没有已形成，末切面为 `ExpansionHandoff`。
4. `append_monotone_final_prefix`：固定种子，级别取 0、1、6，逐前缀断言 M1 到 M4 和四种后继。
5. `formed_pair_survives_open_continuation`（R2-1）：`[40,10,35,20,60,55,65,45,55,48,90,80,105,85,100]`。11 到 13 个单元时已形成 Up，14 个时为 `[已形成 Up, 临时分离 Up]`，`pairs()[0]` 不变。
6. `settlement_is_read_from_source`（R2-2）：只有 u0..u7 时 B 的 `break_unit()` 为 None，没有已形成。
7. `evidence_content_equals_source`（R2-3、R1-b）：每个 `units()` 等于来源同区间切片。连接段区间等于左成员末到右成员首，非空，首项等于左突破段。把 `units[4]` 换成 50→60、Down、[3140,3240] 后仍成立。
8. `upgrade_flag_mirrors_scanner`（R1-c、R2-4）：`[10,40,20,35,25,34,22,33,24,32]` 与 `[11,42,22,37,37,37,37,37,37,37]`。断言 `center().is_none()` 等于 `scan.windows[k].upgraded`，不写死真值。
9. `subwindow_is_its_own_source`（R2-5）：上例第一条的 `units[3..6]` 单独传入，核心等于这三段自己的 seed 核心，不等于母核心。
10. `chain_keeps_evaluated_pair_beside_deferred`（R2-6）：X 为测试 5 的序列后接 `86,99,87,98,88,97`，Y 把首端点改成 46。两结果不等，`pairs()[0]` 分别为已形成 Up 与 `ExpansionHandoff`，`pairs()[1]` 都是 `UpgradeDeferred`。
11. `distinct_pairs_are_distinct`（R1-e）：`[40,10,35,20,60,55,80,60,78,61,77,62,76,63,75,64,120,100,130,110,125]` 的两个 `UpgradeDeferred` 对不相等。
12. `state_table`（R1-d，#2114 的锁）：每对的 `state()` 等于测试内对照表按（叶、右端是否结算、是否被标）查出的值，各行都要出现。`formed()` 为 Some 当且仅当已形成，方向等于叶方向。
13. `non_adjacent_never_pairs`：`[30,53,36,65,36,66,57,87,69,98,91,118,103,108,94,98,85]`。两对都是 `UP_EXPANSION`，C.DD=91 > A.GG=66，没有已形成，右序号恒为左序号加一。
14. `tangency_and_single_center`：`[40,10,35,20,60,55,65,40,55,48,90,80]` 外缘恰等给 `ExpansionHandoff`，第二个 40 改 41 给已形成 Up，`100 - p` 镜像同判。`[16,37,29,57,47,53,37,41,37,55,41,59,54]` 给 `CoreNotStrictlySeparated`。单窗口给盘整。
15. `rule_804_level_and_mirror_lock`：1 级与 6 级在任意输入上除 `unit_level()` 外相等。0 级与 1 级在方向交替输入上相等，在同向三段 `[10,20]`、`[18,25]`、`[18,22]` 上不同（E1）。镜像输入得镜像结果。
16. `parity_with_shared_scan`：节点与对等于独立调用 `scan_center_facts_full` 后 `window_facts`、`window_center`、`pair_facts` 的结果，0 级配 `center_from_segments`，其余配 `center_from_window`。
17. `public_surface_lock`：`include_str!` 读模块源码，按非注释行断言第 3、4 节的禁用项和唯一入口。
18. 编译负例：同文件末尾放 `#[cfg(issue1426_fabricated_evidence_refusal)]` 块，逐行写五个结构体的字面量。`check-compile-negatives-1394.sh` 的 `check` 加目标参数（默认不变），新增一条 `--test trend_formation_1426`、只许 E0451 的用例。Cargo.toml 的 check-cfg 加此名，ci.yml 在 :473 后加一步。

## 11 范围外
不改 `recursive_tower.rs`、`center.rs`、`center_scan.rs`、`parser/`、s_session 发布面。不裁 #2114。不做完成侧、中阴、同向分组、增量续扫、S-4③ 修复、带封印的单元来源类型。
