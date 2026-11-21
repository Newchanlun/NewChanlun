//! #1419 TB-02-E：共用中枢扫描的事实侧车（PLAN S4，#804 L2）。
//!
//! 生产塔与 S 事实层取中枢数据只走一份扫描：[`super::recursive_tower::scan_center_facts`]。塔配
//! [`NoopSink`]（不算事实、不分配），S 写者配 [`FactSink`] 收集每次 seed 评估与每个成立窗口，再由
//! 本模块派生发布所需的事实：中枢六变量与贡献成员（[`CenterWindowFacts`]）、每单元归属
//! （[`UnitFacts`]）、扫描游标（[`ScanState`]）。派生只读扫描报出的窗口与 [`super::center`] 的同一组
//! 判据函数，不另写 seed、延伸或 Zn 判据。
//!
//! 归属规则来自根裁定（`ROOT-RULINGS-1419.md` D9/D-G/D-I 与 r2 第 6 条 R2/R3/R6），原文未讲到这一层：
//!
//! - 成员 ⟹ `CENTER_MEMBER`；≥9 成员窗口内的单元 ⟹ `NOT_YET_ASSIGNED/UPGRADE_PENDING_TB02H`（R3，D-I）。
//! - 已证破坏的 A 与已成立的 B 之间为 `CONNECTOR(A→B)`；B 尚未成立时，唯已证突破段为
//!   `CONNECTOR(A→pending)`。挂起边界与升级不发 R5 连接（#2141）。
//! - 首个中枢之前，以及尚无任何中枢时 ⟹ `NOT_YET_ASSIGNED/NO_LEFT_CENTER_IN_WINDOW`（R2），区分信息放
//!   `seed_from_self`；突破段的 `seed_from_self` 记 `NOT_EVALUATED`（R6）。
//! - 进行中单元（不在扫描输入里）由调用方记 `NOT_YET_ASSIGNED/UNIT_NOT_COMPLETED`。
//!
//! 等待原因 `UNIT_NOT_COMPLETED`/`SEED_NOT_YET_EVALUABLE` 是 S0 oracle 提议名，按 r2 R1 并入 D-J schema 独审定名。

use super::super::types::{Center, Direction, Segment, Tick};
use super::center::{
    center_pair_facts, is_zn, r5_joint, r5_pullback, unit_core_position, CenterPairFacts,
    CenterRoles, R5Joint, RoleVar, SeedFacts, UnitCorePosition, UnitRange,
};
use super::recursive_tower::{
    scan_center_facts_with_r5 as scan_with_sink, WinMeta, WindowScanCursor,
};

/// 生产塔 L0 的单元列表：同一层已确认线段逐个经塔同一投影（`pipeline::segment_to_unit`）。S 事实层用它与
/// 已发布的 `CC-013.segment` 逐位对账（schema v1 §1 输入合同），保证与塔扫描同一输入（#804 L3）。
pub fn l0_units(segments: &[Segment]) -> Vec<UnitRange> {
    segments
        .iter()
        .map(super::pipeline::segment_to_unit)
        .collect()
}

/// 扫描事件接收方。`WANTS_FACTS == false` 时扫描不计算 [`SeedFacts`]。
pub trait ScanSink {
    /// 是否需要 seed 事实。
    const WANTS_FACTS: bool;

    /// 以 `at` 为起点评估了一次 seed；`formed` 为扫描所用 build 的判定。
    #[inline]
    fn seed(&mut self, _at: usize, _facts: &SeedFacts, _formed: bool) {}

    /// 一个成立窗口扫完（结算或延伸到输入末尾）。
    #[inline]
    fn window(&mut self, _window: ScanWindow) {}
}

/// 塔路径：什么都不收。
#[derive(Debug, Clone, Copy, Default)]
pub struct NoopSink;

impl ScanSink for NoopSink {
    const WANTS_FACTS: bool = false;
}

/// 一个成立窗口：成员 = `units[seed_at..exit]`，结算与读域由边界见证决定。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ScanWindow {
    /// seed 第一单元下标（首成员）。
    pub seed_at: usize,
    /// 末成员之后的下标（不蕴含突破）。
    pub exit: usize,
    /// 成员数达到 `UPGRADE_TOTAL_SEGMENTS`（≥9），塔按第33课重切子中枢。
    pub upgraded: bool,
    /// 本窗口塔侧产出的中枢数（<9 为 1）。
    pub emitted: usize,
    pub boundary: R5Boundary,
    /// 最近一次已证返回（含因 Zn 归属未决而未获准接纳的返回）。
    pub last_return: Option<R5Proof>,
}

/// 一次 seed 评估。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct SeedAttempt {
    /// seed 第一单元下标。
    pub at: usize,
    /// 三单元几何事实。
    pub facts: SeedFacts,
    /// 是否成立（扫描所用 build 的判定）。
    pub formed: bool,
}

/// 收集全部事件。
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct FactSink {
    pub attempts: Vec<SeedAttempt>,
    pub windows: Vec<ScanWindow>,
}

impl ScanSink for FactSink {
    const WANTS_FACTS: bool = true;

    fn seed(&mut self, at: usize, facts: &SeedFacts, formed: bool) {
        self.attempts.push(SeedAttempt {
            at,
            facts: *facts,
            formed,
        });
    }

    fn window(&mut self, window: ScanWindow) {
        self.windows.push(window);
    }
}

/// 一次全量扫描（自下标 0 起）的输出与事实。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CenterScanFacts {
    /// 输入单元数（全部已完成）。
    pub len: usize,
    /// 塔侧输出（与 `detect_centers_windowed_resume(units, build, 0)` 逐位相同）。
    pub centers: Vec<(Center, (usize, usize))>,
    pub metas: Vec<WinMeta>,
    pub cursor: WindowScanCursor,
    /// 每次 seed 评估，按扫描顺序。
    pub attempts: Vec<SeedAttempt>,
    /// 每个成立窗口，按扫描顺序。
    pub windows: Vec<ScanWindow>,
}

/// #1496：成立窗口的 R5 见证，按 #2114 已裁的关节分支取证。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum R5Witness {
    Proven(R5Proof),
    Absent(R5Gap),
}

/// 缺席不授权换判据（#799、#2141）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum R5Gap {
    Open,
    UpgradePending,
    BreakUnitOutward,
    AwaitingFirstPullback,
    FirstPullbackUnproven,
    DirectionUnproven,
    ReturnedMembershipUnresolved,
    DirectionNotAlternating,
    JointNotConnected,
}

/// 本窗最终边界。升级不是破坏；未决不能启用续扫。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum R5Boundary {
    Open,
    Pending { gap: R5Gap, tested: usize },
    Destroyed(R5Proof),
    Upgrade,
}

impl R5Boundary {
    pub(super) fn read_end_src(self, units: &[UnitRange], exit: usize) -> usize {
        match self {
            Self::Destroyed(proof) => units[proof.pullback_unit()].end_index,
            Self::Upgrade => units[exit - 1].end_index,
            Self::Open | Self::Pending { .. } => usize::MAX,
        }
    }
}

/// 首个不重叠单元自身担当离开时的独立同源角色证据。
/// 输入者已经核验中心、构造流、完成、首次性及关节（非投影极值推测）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct R5AttestedLegs {
    pub seed: usize,
    pub leave: usize,
    pub side: Direction,
    pub first_pullback: Option<usize>,
    /// 已核实离开是否为 Zn；None 保留成员未决。独立角色不改变走势本体方向。
    pub leave_is_zn: Option<bool>,
}

/// 已完成单元的方向出处及该构造流的外段角色证据。不读取级别。
#[derive(Debug, Clone, Copy)]
pub enum R5DirectionSource<'a> {
    Native,
    Verified(&'a [Option<Direction>]),
    Unproven,
}

impl R5DirectionSource<'_> {
    fn matches(self, at: usize, direction: Direction) -> bool {
        match self {
            Self::Native => true,
            Self::Verified(values) => values.get(at).copied().flatten() == Some(direction),
            Self::Unproven => false,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum R5Step {
    Pending(R5Gap),
    Destroyed(R5Proof),
    Returned { proof: R5Proof, admit: bool },
}

/// 首个不重叠边界的唯一角色分派。独立同源见证不是字面关节失败后的重试。
pub(super) fn r5_step(
    core: (Tick, Tick),
    units: &[UnitRange],
    seed: usize,
    j: usize,
    directions: R5DirectionSource<'_>,
    attested: Option<&R5AttestedLegs>,
) -> R5Step {
    let (zd, zg) = core;
    if let Some(legs) = attested {
        if unit_core_position(&units[j], zd, zg).leave_side() != Some(legs.side) {
            return R5Step::Pending(R5Gap::FirstPullbackUnproven);
        }
        let Some(pullback) = units.get(j + 1) else {
            return R5Step::Pending(R5Gap::AwaitingFirstPullback);
        };
        if legs.first_pullback != Some(j + 1) {
            return R5Step::Pending(R5Gap::FirstPullbackUnproven);
        }
        let proof = R5Proof::new(j, j + 1, legs.side, core, pullback);
        return match r5_pullback(zd, zg, legs.side, pullback) {
            Some(true) => R5Step::Returned {
                proof,
                admit: legs.leave_is_zn == Some(false) && !is_zn(&units[j], &units[seed]),
            },
            Some(false) => R5Step::Destroyed(proof),
            None => R5Step::Pending(R5Gap::FirstPullbackUnproven),
        };
    }
    let (prev, cur) = (&units[j - 1], &units[j]);
    if !directions.matches(j - 1, prev.direction) || !directions.matches(j, cur.direction) {
        return R5Step::Pending(R5Gap::DirectionUnproven);
    }
    match r5_joint(zd, zg, prev, cur) {
        R5Joint::Proven { side } => R5Step::Destroyed(R5Proof::new(j - 1, j, side, core, cur)),
        R5Joint::BreakUnitOutward => R5Step::Pending(R5Gap::BreakUnitOutward),
        R5Joint::DirectionNotAlternating => R5Step::Pending(R5Gap::DirectionNotAlternating),
        R5Joint::JointNotConnected => R5Step::Pending(R5Gap::JointNotConnected),
        R5Joint::NotOutside | R5Joint::PrevOutsideCore => {
            R5Step::Pending(R5Gap::FirstPullbackUnproven)
        }
    }
}

/// 共用扫描证实的离开和首次回抽；下标均相对于本次输入。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct R5Proof {
    leave_unit: usize,
    pullback_unit: usize,
    side: Direction,
    core: (Tick, Tick),
    pullback_extreme: Tick,
}

impl R5Proof {
    fn new(
        leave_unit: usize,
        pullback_unit: usize,
        side: Direction,
        core: (Tick, Tick),
        u: &UnitRange,
    ) -> Self {
        Self {
            leave_unit,
            pullback_unit,
            side,
            core,
            pullback_extreme: match side {
                Direction::Up => u.lo,
                Direction::Down => u.hi,
            },
        }
    }

    pub fn leave_unit(&self) -> usize {
        self.leave_unit
    }

    pub fn pullback_unit(&self) -> usize {
        self.pullback_unit
    }

    pub fn side(&self) -> Direction {
        self.side
    }

    /// 冻结核心 `(ZD, ZG)`。
    pub fn core(&self) -> (Tick, Tick) {
        self.core
    }

    /// 回抽段朝核心一侧的极值：向上破取低、向下破取高。
    pub fn pullback_extreme(&self) -> Tick {
        self.pullback_extreme
    }
}

/// 对已完成单元做一次全量扫描并收集事实。`build` 取塔同级所用的判据（L0 = `center_from_segments`）。
pub fn scan_center_facts_full(
    units: &[UnitRange],
    build: fn(&UnitRange, &UnitRange, &UnitRange) -> Option<Center>,
) -> CenterScanFacts {
    scan_center_facts_with_r5(units, build, R5DirectionSource::Native, &[])
}

/// 扫描已完成的单一构造流；`attested` 以来自该流的 (seed, leave) 升序提供。
pub fn scan_center_facts_with_r5(
    units: &[UnitRange],
    build: fn(&UnitRange, &UnitRange, &UnitRange) -> Option<Center>,
    direction_source: R5DirectionSource<'_>,
    attested: &[R5AttestedLegs],
) -> CenterScanFacts {
    let mut sink = FactSink::default();
    let (centers, metas, cursor) =
        scan_with_sink(units, build, 0, direction_source, attested, &mut sink);
    CenterScanFacts {
        len: units.len(),
        centers,
        metas,
        cursor,
        attempts: sink.attempts,
        windows: sink.windows,
    }
}

/// 一个角色变量的发布事实（下标为单元在输入中的绝对下标）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RoleFact {
    pub var: RoleVar,
    pub value: Tick,
    /// 取到该值的成员，升序。
    pub contributors: Vec<usize>,
}

impl RoleFact {
    /// 同价见证：贡献成员 ≥2 时为其全体，否则空。
    pub fn same_price_witness(&self) -> &[usize] {
        if self.contributors.len() >= 2 {
            &self.contributors
        } else {
            &[]
        }
    }
}

/// 一个成立窗口的发布事实（CC-016/017/022 的数据源）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CenterWindowFacts {
    /// 首成员 = seed 第一单元。
    pub first: usize,
    /// 末成员。
    pub last: usize,
    /// 是否已结算（有突破段）。
    pub settled: bool,
    pub settlement: Option<R5Proof>,
    pub pending_boundary: Option<usize>,
    /// 突破段（结算时）。
    pub break_unit: Option<usize>,
    /// 离开方向（结算时；未结算无定义，根裁定 r2 R4）。
    pub break_up: Option<bool>,
    /// 续扫锚 = last+2（结算时，R8）。
    pub resume_anchor: Option<usize>,
    /// 下一个待测延伸的单元（开放时 = 输入长度）。
    pub next_tested_unit: Option<usize>,
    /// ≥9 成员：已发布对象标 `UPGRADE_PENDING_TB02H`，DD/GG/D/G 不发布（R3）。
    pub upgrade_pending: bool,
    /// 与 seed 第一单元同向的成员，升序。
    pub zn_members: Vec<usize>,
    /// 六变量，顺序同 [`RoleVar::ALL`]。
    pub roles: Vec<RoleFact>,
}

impl CenterWindowFacts {
    /// 成员数。
    pub fn count(&self) -> usize {
        self.last - self.first + 1
    }

    /// 取某一角色变量。
    pub fn role(&self, var: RoleVar) -> &RoleFact {
        self.roles
            .iter()
            .find(|r| r.var == var)
            .expect("六变量齐全")
    }
}

/// 某单元以自身为起点的 seed 评估结果。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SeedFromSelf {
    Formed,
    Failed,
    NotEvaluated,
}

impl SeedFromSelf {
    pub fn as_str(self) -> &'static str {
        match self {
            SeedFromSelf::Formed => "FORMED",
            SeedFromSelf::Failed => "FAILED",
            SeedFromSelf::NotEvaluated => "NOT_EVALUATED",
        }
    }
}

/// `NOT_YET_ASSIGNED` 的等待原因。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum WaitReason {
    NoLeftCenterInWindow,
    SeedNotYetEvaluable,
    UpgradePendingTb02h,
    UnitNotCompleted,
}

impl WaitReason {
    pub fn as_str(self) -> &'static str {
        match self {
            WaitReason::NoLeftCenterInWindow => "NO_LEFT_CENTER_IN_WINDOW",
            WaitReason::SeedNotYetEvaluable => "SEED_NOT_YET_EVALUABLE",
            WaitReason::UpgradePendingTb02h => "UPGRADE_PENDING_TB02H",
            WaitReason::UnitNotCompleted => "UNIT_NOT_COMPLETED",
        }
    }
}

/// 单元归属三值（恰一）。中枢以窗口序号（[`CenterScanFacts::windows`] 下标）指称。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum UnitAssignment {
    Member {
        center: usize,
    },
    /// `right == None` ⟹ 右端中枢尚未成立（pending）。
    Connector {
        left: usize,
        right: Option<usize>,
    },
    NotYetAssigned(WaitReason),
}

/// 一个单元的归属与 seed 记录。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct UnitFacts {
    pub assignment: UnitAssignment,
    pub seed_from_self: SeedFromSelf,
}

/// CC-018 延伸测试单元在构造中的角色（★#1424）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum TestedRole {
    /// <9 窗口的延伸成员（seed 之后）。
    ExtensionMember,
    /// 共用扫描证明破坏后的连接单元；角色与位置独立。
    BreakUnit,
    /// 有位置证据、尚无构造归属的边界。
    UnresolvedBoundary,
    /// ≥9 窗口的延伸成员（归属待 #1429，`UPGRADE_PENDING_TB02H`）。
    UpgradePendingMember,
}

impl TestedRole {
    pub fn as_str(self) -> &'static str {
        match self {
            TestedRole::ExtensionMember => "EXTENSION_MEMBER",
            TestedRole::BreakUnit => "BREAK_UNIT",
            TestedRole::UnresolvedBoundary => "UNRESOLVED_BOUNDARY",
            TestedRole::UpgradePendingMember => "UPGRADE_PENDING_MEMBER",
        }
    }
}

/// 一个延伸测试单元相对所属中枢冻结核心的位置（CC-018）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct TestedPosition {
    /// 单元在输入中的绝对下标。
    pub unit: usize,
    pub position: UnitCorePosition,
    pub role: TestedRole,
}

/// 一对扫描相邻中枢的关系结果（CC-020）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum PairOutcome {
    /// 两端都是 <9 窗口：按 Zn 外缘判五叶。
    Evaluated(CenterPairFacts),
    /// 任一端是 ≥9 窗口（S 不发外缘，#1419 R3）：叶待 #1429（#1424 根裁定第 2 问）。
    PendingUpgrade,
}

/// 一对扫描相邻中枢（窗口序号 `left`、`right = left + 1`）。
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PairFact {
    pub left: usize,
    pub right: usize,
    /// 两中枢之间的连接段（A 末成员之后、B 首成员之前的全部单元）。
    pub connectors: std::ops::Range<usize>,
    pub outcome: PairOutcome,
}

/// 扫描停在哪里。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ScanState {
    /// 自 `seed_start` 起的 seed 还缺单元，下一个需要完成的是 `awaiting_unit`。
    SeekingSeed {
        seed_start: usize,
        awaiting_unit: usize,
    },
    /// 末个中枢（窗口序号 `center`）开放，下一个待测延伸的是 `next_unit`。
    Extending { center: usize, next_unit: usize },
}

impl CenterScanFacts {
    /// 每个窗口一项，按扫描顺序。须传共用扫描本次的完整输入；不证明输入窗起点之前的结算。
    pub fn r5_witnesses(&self, units: &[UnitRange]) -> Vec<R5Witness> {
        assert_eq!(units.len(), self.len, "units 必须是本次扫描的输入");
        self.windows
            .iter()
            .map(|w| match w.boundary {
                R5Boundary::Open => R5Witness::Absent(R5Gap::Open),
                R5Boundary::Pending { gap, .. } => R5Witness::Absent(gap),
                R5Boundary::Destroyed(proof) => R5Witness::Proven(proof),
                R5Boundary::Upgrade => R5Witness::Absent(R5Gap::UpgradePending),
            })
            .collect()
    }

    /// 每个成立窗口的发布事实。`units` 必须是本次扫描的输入。
    pub fn window_facts(&self, units: &[UnitRange]) -> Vec<CenterWindowFacts> {
        assert_eq!(units.len(), self.len, "units 必须是本次扫描的输入");
        self.windows
            .iter()
            .map(|w| {
                let members = &units[w.seed_at..w.exit];
                let roles = CenterRoles::of_members(members);
                let proof = match w.boundary {
                    R5Boundary::Destroyed(proof) => Some(proof),
                    _ => None,
                };
                let next_tested_unit = match w.boundary {
                    R5Boundary::Open => Some(w.exit),
                    R5Boundary::Pending {
                        gap: R5Gap::AwaitingFirstPullback,
                        ..
                    } => Some(w.exit + 1),
                    R5Boundary::Pending { .. } => Some(w.exit),
                    _ => None,
                };
                CenterWindowFacts {
                    first: w.seed_at,
                    last: w.exit - 1,
                    settled: proof.is_some(),
                    settlement: proof,
                    pending_boundary: match w.boundary {
                        R5Boundary::Pending { tested, .. } => Some(tested),
                        _ => None,
                    },
                    break_unit: proof.map(|_| w.exit),
                    break_up: proof.map(|p| p.side() == Direction::Up),
                    resume_anchor: proof.map(|_| w.exit + 1),
                    next_tested_unit,
                    upgrade_pending: w.upgraded,
                    zn_members: members
                        .iter()
                        .enumerate()
                        .filter(|(_, u)| is_zn(u, &members[0]))
                        .map(|(k, _)| w.seed_at + k)
                        .collect(),
                    roles: RoleVar::ALL
                        .iter()
                        .map(|&var| RoleFact {
                            var,
                            value: roles.value(var),
                            contributors: roles
                                .contributors(members, var)
                                .into_iter()
                                .map(|k| w.seed_at + k)
                                .collect(),
                        })
                        .collect(),
                }
            })
            .collect()
    }

    /// 单元 `k` 以自身为起点的 seed 记录。
    pub fn seed_from_self(&self, k: usize) -> SeedFromSelf {
        match self.attempts.iter().find(|a| a.at == k) {
            Some(a) if a.formed => SeedFromSelf::Formed,
            Some(_) => SeedFromSelf::Failed,
            None => SeedFromSelf::NotEvaluated,
        }
    }

    /// 每个已完成单元的归属（下标 0..len）。进行中单元不在其内，由调用方记 `UNIT_NOT_COMPLETED`。
    pub fn unit_facts(&self) -> Vec<UnitFacts> {
        (0..self.len)
            .map(|k| UnitFacts {
                assignment: self.assignment_of(k),
                seed_from_self: self.seed_from_self(k),
            })
            .collect()
    }

    fn assignment_of(&self, k: usize) -> UnitAssignment {
        if let Some((idx, w)) = self
            .windows
            .iter()
            .enumerate()
            .find(|(_, w)| w.seed_at <= k && k < w.exit)
        {
            return if w.upgraded {
                UnitAssignment::NotYetAssigned(WaitReason::UpgradePendingTb02h)
            } else {
                UnitAssignment::Member { center: idx }
            };
        }
        // 左邻中枢 = 末成员在 k 之前的最后一个窗口；没有 ⟹ 首中枢之前或尚无中枢（R2）。
        let Some(left) = self.windows.iter().rposition(|w| w.exit <= k) else {
            return UnitAssignment::NotYetAssigned(WaitReason::NoLeftCenterInWindow);
        };
        if !matches!(self.windows[left].boundary, R5Boundary::Destroyed(_)) {
            return UnitAssignment::NotYetAssigned(WaitReason::SeedNotYetEvaluable);
        }
        if let Some(right) = (left + 1 < self.windows.len()).then_some(left + 1) {
            return UnitAssignment::Connector {
                left,
                right: Some(right),
            };
        }
        if self.windows[left].exit == k {
            UnitAssignment::Connector { left, right: None }
        } else {
            UnitAssignment::NotYetAssigned(WaitReason::SeedNotYetEvaluable)
        }
    }

    /// 窗口 `w` 的中枢（S 口径：核心取 seed 三单元，外缘取全部成员中的 Zn；与塔 <9 窗口的中枢逐位相同）。
    pub fn window_center(&self, units: &[UnitRange], w: usize) -> Center {
        let win = &self.windows[w];
        let members = &units[win.seed_at..win.exit];
        let roles = CenterRoles::of_members(members);
        Center {
            zd: roles.zd,
            zg: roles.zg,
            dd: roles.zn.dd,
            gg: roles.zn.gg,
            start_index: members[0].start_index,
            end_index: members[members.len() - 1].end_index,
        }
    }

    /// CC-018（★#1424）：每个窗口的延伸测试单元（seed 之后的成员 + 突破段）相对冻结核心的位置，按窗口序。
    /// 位置与塔延伸循环读同一个 [`unit_core_position`]。
    pub fn tested_positions(&self, units: &[UnitRange]) -> Vec<Vec<TestedPosition>> {
        assert_eq!(units.len(), self.len, "units 必须是本次扫描的输入");
        self.windows
            .iter()
            .map(|w| {
                let roles = CenterRoles::of_members(&units[w.seed_at..w.exit]);
                let last_tested = match w.boundary {
                    R5Boundary::Destroyed(_) | R5Boundary::Pending { .. } => w.exit,
                    R5Boundary::Open | R5Boundary::Upgrade => w.exit - 1,
                };
                (w.seed_at + 3..=last_tested)
                    .map(|k| {
                        let position = unit_core_position(&units[k], roles.zd, roles.zg);
                        let role = if k == w.exit {
                            match w.boundary {
                                R5Boundary::Destroyed(_) => TestedRole::BreakUnit,
                                _ => TestedRole::UnresolvedBoundary,
                            }
                        } else if w.upgraded {
                            TestedRole::UpgradePendingMember
                        } else {
                            TestedRole::ExtensionMember
                        };
                        TestedPosition {
                            unit: k,
                            position,
                            role,
                        }
                    })
                    .collect()
            })
            .collect()
    }

    /// CC-020（★#1424）：每对扫描相邻中枢的关系。两端都 <9 ⟹ [`center_pair_facts`]（与塔 `classify_relation`
    /// 同一判定）；任一端 ≥9 ⟹ [`PairOutcome::PendingUpgrade`]，不照抄塔在该处的过渡态子中枢关系。
    pub fn pair_facts(&self, units: &[UnitRange]) -> Vec<PairFact> {
        assert_eq!(units.len(), self.len, "units 必须是本次扫描的输入");
        self.windows
            .windows(2)
            .enumerate()
            .filter(|(_, pair)| matches!(pair[0].boundary, R5Boundary::Destroyed(_)))
            .map(|(left, pair)| {
                let (a, b) = (&pair[0], &pair[1]);
                let outcome = if a.upgraded || b.upgraded {
                    PairOutcome::PendingUpgrade
                } else {
                    PairOutcome::Evaluated(center_pair_facts(
                        &self.window_center(units, left),
                        &self.window_center(units, left + 1),
                    ))
                };
                PairFact {
                    left,
                    right: left + 1,
                    connectors: a.exit..b.seed_at,
                    outcome,
                }
            })
            .collect()
    }

    /// 扫描停止处。
    pub fn scan_state(&self) -> ScanState {
        match self.windows.last() {
            Some(w) if matches!(w.boundary, R5Boundary::Open | R5Boundary::Pending { .. }) => {
                ScanState::Extending {
                    center: self.windows.len() - 1,
                    next_unit: if matches!(
                        w.boundary,
                        R5Boundary::Pending {
                            gap: R5Gap::AwaitingFirstPullback,
                            ..
                        }
                    ) {
                        w.exit + 1
                    } else {
                        w.exit
                    },
                }
            }
            _ => ScanState::SeekingSeed {
                seed_start: self.cursor.consumed,
                awaiting_unit: self.cursor.consumed + 2,
            },
        }
    }
}

#[cfg(test)]
mod r5_resume_tests {
    use super::*;
    use crate::theta_v0::classifier::center::center_from_segments;

    #[test]
    fn r5_full_and_resumed_windows_share_the_pullback_dependency() {
        let units: Vec<_> = [
            (Direction::Down, 20, 40),
            (Direction::Up, 20, 35),
            (Direction::Down, 25, 35),
            (Direction::Up, 36, 50),
            (Direction::Down, 37, 50),
            (Direction::Up, 38, 50),
            (Direction::Down, 39, 49),
        ]
        .into_iter()
        .enumerate()
        .map(|(k, (direction, lo, hi))| UnitRange {
            start_index: k,
            end_index: k + 1,
            direction,
            lo,
            hi,
        })
        .collect();
        let roles = [R5AttestedLegs {
            seed: 0,
            leave: 3,
            side: Direction::Up,
            first_pullback: Some(4),
            leave_is_zn: Some(false),
        }];
        let mut old =
            scan_center_facts_with_r5(&[], center_from_segments, R5DirectionSource::Native, &roles);
        for len in 1..=units.len() {
            let input = &units[..len];
            let full = scan_center_facts_with_r5(
                input,
                center_from_segments,
                R5DirectionSource::Native,
                &roles,
            );
            let mut sink = FactSink::default();
            let (tail, metas, cursor) = scan_with_sink(
                input,
                center_from_segments,
                old.cursor.resume_from,
                R5DirectionSource::Native,
                &roles,
                &mut sink,
            );
            let keep = old.centers.len() - old.cursor.last_window_emitted;
            assert_eq!([&old.centers[..keep], &tail].concat(), full.centers);
            assert_eq!([&old.metas[..keep], &metas].concat(), full.metas);
            let keep_windows = old.windows.len().saturating_sub(1);
            assert_eq!(
                [&old.windows[..keep_windows], &sink.windows].concat(),
                full.windows
            );
            assert_eq!(cursor, full.cursor);
            old = full;
        }
        assert_eq!(old.metas[0].read_end_src, units[4].end_index);
        assert_eq!(old.metas[0].settlement.unwrap().pullback_unit(), 4);
        let mut revised = units;
        revised[4].lo = 33;
        let new = scan_center_facts_with_r5(
            &revised,
            center_from_segments,
            R5DirectionSource::Native,
            &roles,
        );
        let first_dirty = revised[4].start_index;
        assert_eq!(
            old.metas.partition_point(|m| m.read_end_src < first_dirty),
            0
        );
        assert!(!new.window_facts(&revised)[0].settled);
    }
}
