# #1496 第一片实施简报：共用 R5 见证（只实现 #2114 的字面分支）与中枢正本两处措辞订正

## 1 目标

交付三样东西：

- 一个共用的「R5 结算见证」。它回答的问题是：共用中枢扫描里每个已结算窗口，「离开，加首次回抽不回」这件事有没有被 #2114 已裁的那条规则证实。下游 #1426 以后只读它来决定能否发 `TrendFormed`。
- 中枢正本 `zhongshu.md` §5.2 与 §9 R5 行的措辞订正，与见证放在同一个 PR。
- Lean 侧同一谓词的定义、定理与机器导出夹具，由 Rust 对拍。

本片不改塔的任何结算行为。不勾 #1496 的任何验收项，PR 里写「Part of #1496」，不写 Closes。

## 2 基线与分支

- 从 PR #1855 的头 `9e57032bcd08399b0a90189402be07200d95a857`（分支 `sandcastle/issue-1419`）切出新分支，建议名 `impl/1496-s1-r5-witness`。`center_scan.rs` 在 origin/main 上不存在，只能叠在这里。
- 教义依据引 `origin/decision/2114-r3 @ ba74fd6344df5d03d3a8c5b6a5a2c9d8bef7a8b6` 的 `.chanlun/definitions/qushi.md:244`（「#2114 裁定」一节的「R5 段角色」条）。动手前先读这一条全文、`zhongshu.md` §4.1（:250、:252）、§5（:322-362）、§9 R5 行（:536）以及 `docs/agents/doctrine-rules.md`。
- 不要把 `qushi.md` 带进本片的改动。
- PR 对 main 开，开成 draft，并在正文写明原因：分支叠在未合入的 #1855 上，标 ready 会让合入巡检把 #1855 的提交一并带进 main。等 #1855 与 #2140 合入、分支追平 main 后，由主控标 ready。

## 3 写集

只动下面七个文件：

1. `rust/src/theta_v0/classifier/center.rs`：新增关节纯函数，放在 `unit_core_position`（:917）旁边；文件内联测试里加一条单向锁（见第 6 节第 12 条）。
2. `rust/src/theta_v0/classifier/center_scan.rs`：新增按窗口派生见证的方法。
3. `rust/tests/r5_witness_1496.rs`：新文件，集成测试，只用公开接口。Cargo 没有关自动发现，不必改 `Cargo.toml` 和 `ci.yml`。
4. `rust/tests/fixtures/r5_witness_1496_lean.json`：新文件，只由 Lean 导出，不手编。
5. `formal/Origin/R5WitnessFixtureExport.lean`：新文件，不进 lake roots，先例是 `formal/Origin/CenterPairFixtureExport.lean`。
6. `scripts/check_fixture_drift.py`：在 `FIXTURES` 字典末尾追加一项。
7. `.chanlun/definitions/zhongshu.md`：§5.2、§9 R5 行、头部「最后裁定」行、一段 046:152 的读法。

不许改的文件：

- `recursive_tower.rs`，包括延伸循环（:571）、续扫（:646）和 `WinMeta`
- `signal.rs`、`ref_v1.rs`、`classifier/mod.rs`、`classifier/tests/mod.rs`
- `formal/Origin/CenterConstruct.lean`、`formal/lakefile.toml`
- `rust/tests/fixtures/theta_v0_center_parity.json`
- `content_structure.rs`、`q3-center.js`
- `qushi.md`、`CONTEXT.md`、`rust/Cargo.toml`、`.github/`

不给 `UnitRange`、`ScanWindow`、`CenterWindowFacts` 加字段。

## 4 共用 R5 见证是什么

### 4.1 关节纯函数（`center.rs`）

签名只吃核心与相邻两个单元：`r5_joint(zd, zg, prev: &UnitRange, cur: &UnitRange) -> R5Joint`。不带级别参数，也不带 build 参数。

按下面顺序判，先命中先返回：

1. `cur` 没有严格在核心外（`unit_core_position(cur).leave_side()` 为空，含相切）：返回 `NotOutside`。
2. 记 `side` 为 `cur` 所在的一侧（核心上方为 Up，下方为 Down）。`cur.direction == side`，即突破段自己朝外走：返回 `BreakUnitOutward`。这是 #2114 说的「首不重叠段本身为离开、尚缺回抽见证」的挂起情形。
3. `prev.direction != side`，即两段同向、不交替：返回 `DirectionNotAlternating`。
4. `prev` 与核心不是闭区间相交：返回 `PrevOutsideCore`。扫描不会传入这种情况，写它是为了让函数对所有输入都有定义。
5. 关节相连，即同时满足：
   - `prev.end_index == cur.start_index`；
   - `side` 为 Up 时 `prev.hi == cur.hi`，为 Down 时 `prev.lo == cur.lo`。

   满足则返回 `Proven { side }`，否则返回 `JointNotConnected`。

比较全部严格，等号不成点。这一点由 `unit_core_position` 的相切叶保证，不另写比较。

### 4.2 按窗口派生（`center_scan.rs`）

新增 `CenterScanFacts::r5_witnesses(&self, units) -> Vec<R5Witness>`，每个窗口一项，按扫描顺序。

每项二选一：

- `Proven(R5Proof)`
- `Absent(R5Gap)`，其中 `R5Gap` 取 `Open`、`UpstreamUnproven { window }`、`UpgradePending`、`BreakUnitOutward`、`DirectionNotAlternating`、`JointNotConnected` 之一。

判定顺序：

1. 窗口未结算（`exit == len`）：`Open`。
2. 本次扫描里，更早的已结算窗口中只要有一个的关节（该窗口的 `units[exit-1]` 与 `units[exit]`，对它自己的冻结核心）不是 `Proven`：`UpstreamUnproven`，`window` 填第一个这样的窗口序号。这里只看关节，不看那个窗口是否升级。
3. 本窗口是升级窗（`upgraded`）：`UpgradePending`。
4. 其余情况照搬本窗口关节的结果。

`R5Proof` 的字段设为私有，只给读取方法，只在 `center_scan.rs` 内构造。它带：离开段下标（`exit-1`）、回抽段下标（`exit`）、`side`、冻结核心 `(zd, zg)`、回抽段朝核心一侧的极值（向上破取 `lo`，向下破取 `hi`）。

不带时钟。不输出「回到核心」或「未回到核心」的后果。不看 `exit` 之后的任何单元。不调用也不回落到 `judge_third_cert`、裸 `settled` 或 `break_unit`。

### 4.3 为什么这样写

- `qushi.md@ba74fd63:244` 的推导以「端点相连、方向交替」为前件。真实 L0 单元的区间取成员笔的方向极值，关节处极值并不总相等。夹具 `s_session/tests/fixtures/tb02e-real/btc-tail50k-first600.json` 的 5 个关节里有 2 个不相等。
- 所以前件必须从单元数据逐个核对，不能按级别假设。
- 反向但关节极值不等、突破段朝外、上游未证，这三类都还没有裁定，一律缺席并写明原因。缺席不是放宽档，也没有任何回落通道（#799）。
- 谓词不读级别（#804）。

注释里凡是登记「未裁」的地方都要带票号：用主控随派工给的裁定票号；没给就写 #1496，并在 PR 正文列为待换号，不要自己编号。

## 5 Lean 侧

`formal/Origin/R5WitnessFixtureExport.lean` 里做三件事：

1. 用 Lean 定义同一个关节谓词，判定顺序与 4.1 相同。

2. 证明一条定理，对应 #2114 的推导。
   - 前提：`zd < zg`；`prev` 与核心闭区间相交；`cur` 严格在核心的 `side` 一侧；两段方向相反；关节极值按 `prev` 的方向相等（`prev` 向上则 `prev.hi = cur.hi`，向下则 `prev.lo = cur.lo`）。
   - 结论：`prev.direction = side`，且 `cur.direction` 与 `side` 相反。也就是相连交替时突破段不可能朝外。
   - 证明分情况后用 `omega` 之类的核心战术即可，不引 Mathlib。定理不得以 L0 为前提。

3. 对至少下面 9 个例子求值并导出 JSON（schema 建议 `tb1496-r5-joint/1`）。核心取 [20,35] 的例子里 `prev` 都与核心相交。

| 例子 | 期望 |
|---|---|
| 相连，向下破 | `Proven`，Down |
| 相连，向上破 | `Proven`，Up |
| 突破段朝外，在核心上方。取 `CenterConstruct.lean:611` 的 refSeg4Break 形状：核心 [12,15]，`prev` 向下 [13,16]，`cur` 向上 [22,25] | `BreakUnitOutward` |
| 突破段朝外，在核心下方 | `BreakUnitOutward` |
| 反向、整段在外，但关节极值不等 | `JointNotConnected` |
| 极值相等，但 `end_index` 不等于 `start_index` | `JointNotConnected` |
| 两段同向 | `DirectionNotAlternating` |
| `cur.lo` 等于 ZG | `NotOutside` |
| `prev` 也在核心外 | `PrevOutsideCore` |

其余要求：

- 夹具用 `cd formal && lake env lean Origin/R5WitnessFixtureExport.lean > ../rust/tests/fixtures/r5_witness_1496_lean.json` 落盘。
- 在 `scripts/check_fixture_drift.py` 的 `FIXTURES` 里登记这一对。
- 文件内不得有 sorry、admit、axiom。
- 不动 `refStep`、`extendWeak`。

## 6 测试（`rust/tests/r5_witness_1496.rs`）

下面的期望值来自手算和一个仓外 Python 模型，不是 Rust 实跑。如果真实扫描给出的窗口与这里不同，停下来报告，不要改期望值去迁就。

构造相连单元时，单元 k 由端点 P_k 到 P_{k+1} 生成，`start_index = 4k`、`end_index = 4k+4`，做法同 `classifier/tests/center_scan_1419.rs:36-50`。

1. `connected_down_break_k8_proves_first_pullback`
   - 输入：端点 [10,40,20,35,30,38,21,25,5,15]，build 用 `center_from_segments`。
   - 期望：一个窗口，seed 0、exit 8、核心 [20,35]；见证 `Proven`，离开段 7、回抽段 8、side Down、回抽极值 15。

2. `connected_up_break_k8_proves_first_pullback`
   - 输入：上例端点逐个取 45 减去它。
   - 期望：核心 [10,25]；`Proven`，离开段 7、回抽段 8、side Up、回抽极值 30。

3. `outward_break_unit_has_no_witness`
   - 输入：u0 上 [10,40]、u1 下 [20,40]、u2 上 [20,35]、u3 下 [30,37]、u4 上 [36,50]，下标依次相接。
   - 期望：窗口 seed 0、exit 4、核心 [20,35]；见证 `Absent(BreakUnitOutward)`。
   - 再追加 u5 下 [33,50]（回到核心）：窗口不变，见证仍是 `BreakUnitOutward`。这条刻画的是塔现状，同时锁住不拿晚段顶替。

4. `reverse_break_with_unequal_joint_extremes_has_no_witness`
   - 输入：u0 上 [10,40]、u1 下 [20,40]、u2 上 [20,35]、u3 下 [25,36]、u4 上 [22,45]、u5 下 [38,50]。
   - 期望：窗口 seed 0、exit 5；`Absent(JointNotConnected)`。

5. `tangent_unit_is_member_not_pullback`
   - 输入：u0 到 u2 同上，u3 下 [25,35]、u4 上 [25,45]、u5 下 [35,45]。
   - 期望：窗口开放（exit 6），`Absent(Open)`。
   - 另外直接调用 `r5_joint(20, 35, u4, u5)`，期望 `NotOutside`。

6. `upstream_unproven_blocks_later_windows`
   - 输入：第 3 条的前五个单元，后面接第 1 条的九个单元（价格整体加 100，下标顺延）。
   - 期望：两个窗口，(seed 0, exit 4) 和 (seed 5, exit 13)；见证依次为 `BreakUnitOutward`、`UpstreamUnproven { window: 0 }`。
   - 对照组：把前半段换成第 1 条的九个单元。期望两个窗口都是 `Proven`。

7. `non_alternating_units_have_no_witness`
   - 输入：build 用 `center_from_window`；u0 上 [10,40]、u1 上 [20,40]、u2 上 [20,35]、u3 下 [30,45]、u4 下 [40,50]。
   - 期望：`Absent(DirectionNotAlternating)`。
   - 这条同时说明上级形状的输入靠几何落空，没有级别闸门。

8. `connected_alternating_streams_prove_every_settled_window`
   - 输入：把 `center_scan_1419.rs:147` 的伪随机端点生成器抄进测试，跑若干种子。
   - 期望：每个已结算且未升级的窗口都是 `Proven`，离开段等于 exit-1，回抽段等于 exit；已结算的升级窗是 `Absent(UpgradePending)`；全程不出现 `UpstreamUnproven`。
   - 测试名和说明里不得出现「L0 等价」。

9. `settled_witness_is_stable_under_append`
   - 输入：对相连流和人为打乱关节的流逐前缀扫描。
   - 期望：某窗口一旦结算，它在任何更长前缀下的见证都与结算那一刻相同。

10. `real_l0_fixture_joints_are_not_all_connected`
    - 输入：读 `s_session/tests/fixtures/tb02e-real/btc-tail50k-first600.json` 的 `tower_units`。
    - 期望：5 个关节的相连读数依次为 否、是、是、否、是；扫描得一个窗口，seed 0、exit 5、核心 [7762000000000, 7773905000000]；见证 `Proven`，离开段 4、回抽段 5、side Down。

11. `r5_joint_matches_lean_fixture`
    - 输入：读第 5 节导出的夹具，逐例调用生产函数 `r5_joint`。
    - 期望：与 Lean 的结论逐例相同，例数不少于 9。

12. `r5_joint_proven_implies_third_cert`（放在 `center.rs` 的内联测试里）
    - 断言：`r5_joint` 为 `Proven` 的例子上，`signal.rs` 的 `judge_third_cert` 也成立；在第 4 条的输入上两者结论不同，注释里把这个分歧挂上票号。
    - 如果不改可见性或别的文件就调不到 `judge_third_cert`，这条不做，在 PR 正文登记原因。

必须演示变红的两个改动。各跑一次，贴出失败输出，再还原：

- 删掉 4.1 第 5 步里的极值相等条件：第 4 条和第 11 条必须变红。
- 删掉 4.2 的上游规则：第 6 条必须变红。

## 7 中枢正本订正（`.chanlun/definitions/zhongshu.md`，与代码同一个 PR）

§5.2（:340-350）改写成按输入条件表述，不按级别表述。要写到的内容：

- 在端点相连（前段终点极值等于后段起点极值）、方向交替的已完成单元流里，首个整段不重叠的单元就是朝核心的反向回抽，它整段在外即已证「不回」，塔在此结算是完整的。
- 只有首不重叠段本身为离开、尚缺回抽见证时才挂起等首回抽。「端点不相连的上级输入」只作例子，不要写成「上级才挂起、L0 不挂起」。
- 首回抽回到核心则继续延伸，按既有 Zn 更新外缘；不回则破坏。
- 失败的首回抽不得被晚一段顶替。
- 塔的挂起分支尚未落码；该分支的成员集、连接段与续扫锚待裁，写上票号。
- :350 的反例限定到挂起情形。

§9 R5 行（:536）：

- 处置栏写成同样的意思。
- 把「该段进 GG/DD」改成「按既有 Zn 更新外缘」。
- 注明共用见证的落点。

机械判据：

- 订正后，固定字符串「首不重叠段本身为离开、尚缺回抽见证」在两处各出现一次。
- `rg -F -c '首不重叠段本身为离开、尚缺回抽见证' .chanlun/definitions/zhongshu.md` 应输出 2（现在是 0）。把这条命令和输出写进 PR。

046:152 的读法，写在 §5 里：

- 引文只取 `docs/chanlun/text/blog/046-第46课.md:152` 中「==」之后缠师的话，标【缠师答】，与 `020:60`【正文】并列。
- 写明：见证只取本级扫描输入里已完成的单元；次次级别回试按原话构成的是次级别的第三类买卖点，可作操作提示，不充当本级见证，也不设提前档。
- 标 `[新缠论:推论]`。
- 在 PR 正文把这一段单列，请非作者独审点名表态。独审不认这一读法时，只把这一段退成裁定票，代码不动。

不许改的地方：:250 端点条款、:252 退场条件、§5.4（:360）、其它清单行的行号，以及「L0 上等价」那句。

头部「最后裁定」行按文件自己的惯例补上 #2114。

## 8 留给后续片，不在本片

- 塔延伸循环的挂起分支，以及随之而来的增量游标读域变化。
- 「越出后返回」的塔行为锁和 C@u29 真实例入锁。
- S 写者事实、Q/JS 合同、正式会话与浏览器核对。
- Lean `refStep` 和 `extendWeak` 的两段式改写，`ref_v1.rs` 与 `theta_v0_center_parity.json` 重落。
- #1426 的 `confirmed()` 改读见证，由 #2124 变基后做。本片只保证它能按窗口读到见证或缺席原因。
- `signal.rs` 的三类点判据收编到同一份谓词，归 #1432、#1433、#1434、#1437。

## 9 验证路线

主控所在的那台 VPS 上 PATH 里没有 cargo 和 lake。验证在装有工具链的远端 Linux 工位或 Boat 上做，以 PR 精确头上的 CI 为准。macOS 本机不跑 cargo。

本地靶向命令：

- `cd rust && cargo test --release --test r5_witness_1496`
- `cd rust && cargo test --release --lib r5_joint`
- `python3 scripts/check_fixture_drift.py`，要求 exit 0；附输出。
- `rg -n "sorry|admit|axiom" formal/Origin/R5WitnessFixtureExport.lean`，要求零命中；附输出。CI 不自动查这一项。
- 第 7 节的 `rg -F -c` 命令，要求输出 2。

CI 上要看的三项：

- 默认目标的 `cargo test --all-targets`（`ci.yml@9e57032b:473`）。
- `fixture-drift` 作业（`:1466-1521`）。
- rust-check 的 `-D warnings`。

改 `rust/src/theta_v0/classifier` 会触发 S 写者路径的四条冷锁，耗时长，属预期。

交付时报告：

- 精确提交号。
- 上述命令的输出。
- 两次变红演示的输出。
- 基线上既有测试是否零变化。
- 没有跑成的项，照实写。
