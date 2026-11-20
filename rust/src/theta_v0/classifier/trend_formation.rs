//! #1426 TB-02-G 形成侧：由相邻同级别中枢对的结果判定走势形成（上涨形成 / 下跌形成 /
//! 盘整 / 交上级扩展 / 素材不足）。
//!
//! 教义依据（只实现正本既有定义，不裁新判据）：
//! - 盘整 = 恰好一个相应级别的中枢、无语义方向：`017-第17课.md:44`【正文】、`031-第31课.md:390`【答疑】、
//!   `.chanlun/definitions/qushi.md:78`。多中枢扩展块不得在本级标盘整，属标错级别，交上级（#1429）：
//!   `qushi.md:93-102`。
//! - 趋势形成与扩展二分 = 中心定理二：`020-第20课.md:58`【正文】、`qushi.md:128-129`、`zhongshu.md:254-266`。
//!   仅相邻（连续前后两个，`020-第20课.md:44`【正文】、`020-第20课.md:58`【正文】）同级别中枢对参与判定；
//!   跳过中间中枢的非相邻配对非法。
//! - 连接段不属于任一中枢：`028-第28课.md:770`【答疑】、`zhongshu.md:398-406`（Z-5）。
//! - 级别同判据（#804）：`level: usize` 只作为输入值传递；上涨与下跌两臂走同一判据函数，消费
//!   [`super::center_scan::PairOutcome`] 与 [`super::center::center_pair_facts`] 的唯一一份五叶判定。
//!
//! 本模块只判形成侧，不断言走势完成、不设中阴态、不改 `s_session` 发布面。

use std::ops::Range;

use super::super::types::{Center, Direction};
use super::center::{center_pair_facts, pair_domain_ok, CenterPairFacts, PairLeaf, UnitRange};
use super::center_scan::{CenterScanFacts, PairOutcome};

/// 形成侧五类判定的轻量标签（供分类索引与镜像对拍使用）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum FormationKind {
    UpTrendFormed,
    DownTrendFormed,
    Consolidation,
    HandoffToUpperLevel,
    InsufficientMaterial,
}

impl FormationKind {
    /// 价格镜像 `p' = M - p` 下的对偶映射（对齐 `Origin.TrendCompleteClassification.TrendClass.mirror`）。
    pub fn mirror(self) -> Self {
        match self {
            FormationKind::UpTrendFormed => FormationKind::DownTrendFormed,
            FormationKind::DownTrendFormed => FormationKind::UpTrendFormed,
            FormationKind::Consolidation => FormationKind::Consolidation,
            FormationKind::HandoffToUpperLevel => FormationKind::HandoffToUpperLevel,
            FormationKind::InsufficientMaterial => FormationKind::InsufficientMaterial,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            FormationKind::UpTrendFormed => "UP_TREND_FORMED",
            FormationKind::DownTrendFormed => "DOWN_TREND_FORMED",
            FormationKind::Consolidation => "CONSOLIDATION",
            FormationKind::HandoffToUpperLevel => "HANDOFF_TO_UPPER_LEVEL",
            FormationKind::InsufficientMaterial => "INSUFFICIENT_MATERIAL",
        }
    }
}

/// 单个中枢扫描窗口的结算态（只表达窗口是否已有离开冻结核心的突破段，不断言走势完成）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum CenterSettlement {
    /// 窗口仍在开放延伸；作为后中枢 B 时，其 Zn 外缘仍可能随后续延伸改写（#1424 W12）。
    Open,
    /// 窗口已结算，`break_unit` 为首个严格离开冻结核心的单元下标（两段式结算 R5 归 #1496）。
    Settled { break_unit: usize },
}

impl CenterSettlement {
    pub fn is_settled(self) -> bool {
        matches!(self, CenterSettlement::Settled { .. })
    }

    pub fn break_unit(self) -> Option<usize> {
        match self {
            CenterSettlement::Open => None,
            CenterSettlement::Settled { break_unit } => Some(break_unit),
        }
    }
}

/// 构造 [`CenterEvidence`] 时的边界校验失败原因。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CenterEvidenceError {
    /// 违反 CC-020 域前件 `DD ≤ ZD < ZG ≤ GG`。
    InvalidDomain,
    /// 中枢成员少于 3 段（`017-第17课.md:38`）。
    FewerThanThreeMembers { count: usize },
    /// 结算突破段下标不等于末成员之后的紧邻单元下标。
    BreakUnitMismatch { expected: usize, actual: usize },
}

/// 单个未触发 ≥9 升级的本级中枢依据（核心 `[zd, zg]` + Zn 外缘 `[dd, gg]`）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CenterEvidence {
    window_index: usize,
    member_units: Range<usize>,
    center: Center,
    settlement: CenterSettlement,
}

impl CenterEvidence {
    pub fn try_new(
        window_index: usize,
        member_units: Range<usize>,
        center: Center,
        settlement: CenterSettlement,
    ) -> Result<Self, CenterEvidenceError> {
        if !pair_domain_ok(&center) {
            return Err(CenterEvidenceError::InvalidDomain);
        }
        let count = member_units.end.saturating_sub(member_units.start);
        if count < 3 {
            return Err(CenterEvidenceError::FewerThanThreeMembers { count });
        }
        if let CenterSettlement::Settled { break_unit } = settlement {
            if break_unit != member_units.end {
                return Err(CenterEvidenceError::BreakUnitMismatch {
                    expected: member_units.end,
                    actual: break_unit,
                });
            }
        }
        Ok(CenterEvidence {
            window_index,
            member_units,
            center,
            settlement,
        })
    }

    pub fn window_index(&self) -> usize {
        self.window_index
    }

    pub fn member_units(&self) -> Range<usize> {
        self.member_units.clone()
    }

    pub fn center(&self) -> Center {
        self.center
    }

    pub fn settlement(&self) -> CenterSettlement {
        self.settlement
    }

    pub fn is_settled(&self) -> bool {
        self.settlement.is_settled()
    }

    pub fn break_unit(&self) -> Option<usize> {
        self.settlement.break_unit()
    }
}

/// 连接两个相邻中枢的一个次级别走势单元（Z-5：不属于任一中枢，`028-第28课.md:770`）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ConnectorUnit {
    /// 单元在扫描输入切片中的绝对下标（例如 #1426 评论中的 u4 对应 `4`）。
    pub unit_index: usize,
    /// 该连接段的方向、价格区间与原始 K 坐标区间（例如 `49..61`）。
    pub unit: UnitRange,
}

/// 中枢链中的单个中枢节点输入：未触发 ≥9 升级的本级中枢，或 ≥9 待升级窗口（无外缘 DD/GG）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ChainCenterInput {
    Normal(CenterEvidence),
    PendingUpgrade {
        window_index: usize,
        member_units: Range<usize>,
        settlement: CenterSettlement,
    },
}

impl ChainCenterInput {
    pub fn window_index(&self) -> usize {
        match self {
            ChainCenterInput::Normal(c) => c.window_index,
            ChainCenterInput::PendingUpgrade { window_index, .. } => *window_index,
        }
    }

    pub fn is_settled(&self) -> bool {
        match self {
            ChainCenterInput::Normal(c) => c.is_settled(),
            ChainCenterInput::PendingUpgrade { settlement, .. } => settlement.is_settled(),
        }
    }

    pub fn is_upgrade_pending(&self) -> bool {
        matches!(self, ChainCenterInput::PendingUpgrade { .. })
    }
}

/// 构造 [`AdjacentPairInput`] 时的边界校验失败原因。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AdjacentPairError {
    /// 非相邻中枢对（`right != left + 1`；只有前后相邻中枢对参与判定，`020-第20课.md:44,58`）。
    NonAdjacent { left: usize, right: usize },
    /// 前中枢尚未结算，不可能已有后继相邻中枢。
    LeftCenterUnsettled { left: usize },
    /// 连接段为空（按 Z-5 跳过突破段，相邻中枢间至少存在 1 个连接段）。
    EmptyConnectors,
    /// 两端升级待定状态与 `PairOutcome` 变体矛盾。
    PendingStatusMismatch,
    /// 传入的 [`CenterPairFacts`] 与 `center_pair_facts(A, B)` 唯一判定不一致。
    OutcomeMismatch {
        expected: PairLeaf,
        actual: PairLeaf,
    },
}

/// 已通过相邻性与同源关系校验的相邻中枢对输入。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AdjacentPairInput {
    inner: ValidatedPair,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum ValidatedPair {
    Evaluated(AdjacentPairEvidence),
    PendingUpgrade { upgraded_windows: Vec<usize> },
}

impl AdjacentPairInput {
    /// 校验相邻性、左枢已结算、连接段非空，并核对 `outcome` 与两端中枢的唯一判定一致。
    pub fn try_new(
        left: ChainCenterInput,
        right: ChainCenterInput,
        connectors: Vec<ConnectorUnit>,
        outcome: PairOutcome,
    ) -> Result<Self, AdjacentPairError> {
        let left_idx = left.window_index();
        let right_idx = right.window_index();
        if right_idx != left_idx + 1 {
            return Err(AdjacentPairError::NonAdjacent {
                left: left_idx,
                right: right_idx,
            });
        }
        if !left.is_settled() {
            return Err(AdjacentPairError::LeftCenterUnsettled { left: left_idx });
        }
        if connectors.is_empty() {
            return Err(AdjacentPairError::EmptyConnectors);
        }
        match (left, right, outcome) {
            (
                ChainCenterInput::Normal(center_a),
                ChainCenterInput::Normal(center_b),
                PairOutcome::Evaluated(pair_facts),
            ) => {
                let expected = center_pair_facts(&center_a.center, &center_b.center);
                if pair_facts != expected {
                    return Err(AdjacentPairError::OutcomeMismatch {
                        expected: expected.leaf,
                        actual: pair_facts.leaf,
                    });
                }
                Ok(AdjacentPairInput {
                    inner: ValidatedPair::Evaluated(AdjacentPairEvidence {
                        center_a,
                        center_b,
                        connectors,
                        pair_facts,
                    }),
                })
            }
            (left_node, right_node, PairOutcome::PendingUpgrade)
                if left_node.is_upgrade_pending() || right_node.is_upgrade_pending() =>
            {
                let mut upgraded_windows = Vec::new();
                if left_node.is_upgrade_pending() {
                    upgraded_windows.push(left_idx);
                }
                if right_node.is_upgrade_pending() {
                    upgraded_windows.push(right_idx);
                }
                Ok(AdjacentPairInput {
                    inner: ValidatedPair::PendingUpgrade { upgraded_windows },
                })
            }
            _ => Err(AdjacentPairError::PendingStatusMismatch),
        }
    }

    pub fn outcome(&self) -> PairOutcome {
        match &self.inner {
            ValidatedPair::Evaluated(ev) => PairOutcome::Evaluated(ev.pair_facts),
            ValidatedPair::PendingUpgrade { .. } => PairOutcome::PendingUpgrade,
        }
    }
}

/// 一对已求值相邻中枢（A、B、连接段与 CC-020 五叶事实）的完整依据。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AdjacentPairEvidence {
    center_a: CenterEvidence,
    center_b: CenterEvidence,
    connectors: Vec<ConnectorUnit>,
    pair_facts: CenterPairFacts,
}

impl AdjacentPairEvidence {
    pub fn center_a(&self) -> &CenterEvidence {
        &self.center_a
    }

    pub fn center_b(&self) -> &CenterEvidence {
        &self.center_b
    }

    pub fn connectors(&self) -> &[ConnectorUnit] {
        &self.connectors
    }

    /// 连接段单元下标区间 `[first, last + 1)`（非空）。
    pub fn connector_unit_range(&self) -> Range<usize> {
        let first = self
            .connectors
            .first()
            .expect("已校验相邻对连接段非空")
            .unit_index;
        let last = self
            .connectors
            .last()
            .expect("已校验相邻对连接段非空")
            .unit_index;
        first..last + 1
    }

    /// 连接段在原始 K 序上的起止坐标 `(start_index, end_index)`（例如 #1426 中的 `(49, 61)`）。
    pub fn connector_coord_span(&self) -> (usize, usize) {
        let first = self.connectors.first().expect("已校验相邻对连接段非空");
        let last = self.connectors.last().expect("已校验相邻对连接段非空");
        (first.unit.start_index, last.unit.end_index)
    }

    pub fn pair_facts(&self) -> CenterPairFacts {
        self.pair_facts
    }

    /// 两个相邻中枢是否均已结算（A 恒已结算；B 开放时为 `false`，B 结算后为 `true`）。
    pub fn is_settled(&self) -> bool {
        self.center_a.is_settled() && self.center_b.is_settled()
    }
}

/// 上涨形成 / 下跌形成的依据（必含至少一对同向新生相邻中枢，非法空趋势不可表示）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TrendFormationEvidence {
    level: usize,
    forming_pair: AdjacentPairEvidence,
    continuation_pairs: Vec<AdjacentPairEvidence>,
}

impl TrendFormationEvidence {
    pub fn level(&self) -> usize {
        self.level
    }

    /// 首次确立趋势形成的相邻新生中枢对（含中枢 A、中枢 B 与连接段）。
    pub fn forming_pair(&self) -> &AdjacentPairEvidence {
        &self.forming_pair
    }

    /// 超过 2 个中枢时的后续同向新生相邻对（2 中枢趋势为空）。
    pub fn continuation_pairs(&self) -> &[AdjacentPairEvidence] {
        &self.continuation_pairs
    }

    /// 按顺序遍历全部同向新生相邻对。
    pub fn all_pairs(&self) -> impl Iterator<Item = &AdjacentPairEvidence> {
        std::iter::once(&self.forming_pair).chain(self.continuation_pairs.iter())
    }

    /// 趋势链末中枢是否已结算（第 111 根 B 开放时为 `false`，第 123 根 B 结算后为 `true`）。
    pub fn is_settled(&self) -> bool {
        self.continuation_pairs
            .last()
            .unwrap_or(&self.forming_pair)
            .is_settled()
    }

    pub fn center_count(&self) -> usize {
        2 + self.continuation_pairs.len()
    }
}

/// 单一本级中枢构成的盘整形成依据（无语义方向字段：`031-第31课.md:390`「盘整哪里有什么方向」）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConsolidationEvidence {
    level: usize,
    center: CenterEvidence,
}

impl ConsolidationEvidence {
    pub fn level(&self) -> usize {
        self.level
    }

    pub fn center(&self) -> &CenterEvidence {
        &self.center
    }

    pub fn is_settled(&self) -> bool {
        self.center.is_settled()
    }
}

/// 扩展关系交由上级（#1429）的依据：必含至少一对 `UpExpansion`/`DownExpansion` 相邻中枢对，
/// 不得在本级标盘整（`020-第20课.md:58`、`qushi.md:93-102`）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UpperLevelExpansionEvidence {
    level: usize,
    first_pair: AdjacentPairEvidence,
    additional_pairs: Vec<AdjacentPairEvidence>,
}

impl UpperLevelExpansionEvidence {
    pub fn level(&self) -> usize {
        self.level
    }

    pub fn target_upper_level(&self) -> usize {
        self.level + 1
    }

    pub fn first_pair(&self) -> &AdjacentPairEvidence {
        &self.first_pair
    }

    pub fn additional_pairs(&self) -> &[AdjacentPairEvidence] {
        &self.additional_pairs
    }

    pub fn all_pairs(&self) -> impl Iterator<Item = &AdjacentPairEvidence> {
        std::iter::once(&self.first_pair).chain(self.additional_pairs.iter())
    }
}

/// 无法在本级作出单一走势形成或 `020:58` 扩展判定的具体原因。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InsufficientReason {
    /// 零中枢（`018-第18课.md:32`：任何走势类型至少包含一个中枢）。
    NoCenter,
    /// 存在 ≥9 段待升级窗口（`UPGRADE_PENDING_TB02H` / `PairOutcome::PendingUpgrade`，缺外缘，归 #1429）。
    PendingUpgrade { window_indices: Vec<usize> },
    /// 相邻对核心未严格分离（`PairLeaf::CoreNotStrictlySeparated`，不进 `020:58`，两段式结算归 #1496）。
    CoreNotStrictlySeparated { pairs: Vec<AdjacentPairEvidence> },
    /// ≥3 中枢的相邻对跨越不同关系族（例如先涨后跌或扩展与新生混排），需完成侧切分，不在形成侧猜边界。
    MixedAdjacentRelations { leaves: Vec<PairLeaf> },
}

/// 素材不足（无法在本级作出单一走势形成判定）的依据。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InsufficientMaterialEvidence {
    level: usize,
    reason: InsufficientReason,
}

impl InsufficientMaterialEvidence {
    pub fn level(&self) -> usize {
        self.level
    }

    pub fn reason(&self) -> &InsufficientReason {
        &self.reason
    }
}

/// 走势形成侧五分支判定（#1426 TB-02-G 形成侧；不断言走势完成）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TrendFormation {
    /// 上涨趋势形成：相邻同级别中枢满足 `B.DD > A.GG`（`PairLeaf::UpNewbirth`）。
    UpTrendFormed(TrendFormationEvidence),
    /// 下跌趋势形成：相邻同级别中枢满足 `B.GG < A.DD`（`PairLeaf::DownNewbirth`）。
    DownTrendFormed(TrendFormationEvidence),
    /// 本级盘整形成：恰好一个未触发 ≥9 升级的相应级别中枢（无语义方向）。
    Consolidation(ConsolidationEvidence),
    /// 扩展交上级：相邻中枢核心严格分离且外缘重叠（`PairLeaf::UpExpansion | DownExpansion`），归 #1429。
    HandoffToUpperLevel(UpperLevelExpansionEvidence),
    /// 素材不足：零中枢、待 ≥9 升级、核心未严格分离或需完成侧切分的混合多段链。
    InsufficientMaterial(InsufficientMaterialEvidence),
}

impl TrendFormation {
    pub fn level(&self) -> usize {
        match self {
            TrendFormation::UpTrendFormed(ev) | TrendFormation::DownTrendFormed(ev) => ev.level,
            TrendFormation::Consolidation(ev) => ev.level,
            TrendFormation::HandoffToUpperLevel(ev) => ev.level,
            TrendFormation::InsufficientMaterial(ev) => ev.level,
        }
    }

    pub fn kind(&self) -> FormationKind {
        match self {
            TrendFormation::UpTrendFormed(_) => FormationKind::UpTrendFormed,
            TrendFormation::DownTrendFormed(_) => FormationKind::DownTrendFormed,
            TrendFormation::Consolidation(_) => FormationKind::Consolidation,
            TrendFormation::HandoffToUpperLevel(_) => FormationKind::HandoffToUpperLevel,
            TrendFormation::InsufficientMaterial(_) => FormationKind::InsufficientMaterial,
        }
    }

    /// 语义方向：只有上涨/下跌趋势形成带方向，盘整与非趋势分支一律为 `None`（`031-第31课.md:390`）。
    pub fn direction(&self) -> Option<Direction> {
        match self {
            TrendFormation::UpTrendFormed(_) => Some(Direction::Up),
            TrendFormation::DownTrendFormed(_) => Some(Direction::Down),
            TrendFormation::Consolidation(_)
            | TrendFormation::HandoffToUpperLevel(_)
            | TrendFormation::InsufficientMaterial(_) => None,
        }
    }
}

/// 校验合成或上级中枢链输入时的错误。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChainInputError {
    /// 相邻连接段槽位数不等于 `centers.len().saturating_sub(1)`。
    ConnectorCountMismatch {
        centers: usize,
        connector_slots: usize,
    },
    /// 中枢窗口序号不连续，无法构成连续相邻链。
    NonContiguousWindowIndex {
        position: usize,
        expected: usize,
        actual: usize,
    },
    Pair(AdjacentPairError),
}

impl From<AdjacentPairError> for ChainInputError {
    fn from(err: AdjacentPairError) -> Self {
        ChainInputError::Pair(err)
    }
}

/// 唯一一份单对形成判定（#804：上涨与下跌两臂共用本函数，级别只作输入值）。
pub fn judge_adjacent_pair(level: usize, pair: &AdjacentPairInput) -> TrendFormation {
    match &pair.inner {
        ValidatedPair::PendingUpgrade { upgraded_windows } => {
            TrendFormation::InsufficientMaterial(InsufficientMaterialEvidence {
                level,
                reason: InsufficientReason::PendingUpgrade {
                    window_indices: upgraded_windows.clone(),
                },
            })
        }
        ValidatedPair::Evaluated(ev) => match ev.pair_facts.leaf {
            PairLeaf::UpNewbirth => TrendFormation::UpTrendFormed(TrendFormationEvidence {
                level,
                forming_pair: ev.clone(),
                continuation_pairs: Vec::new(),
            }),
            PairLeaf::DownNewbirth => TrendFormation::DownTrendFormed(TrendFormationEvidence {
                level,
                forming_pair: ev.clone(),
                continuation_pairs: Vec::new(),
            }),
            PairLeaf::UpExpansion | PairLeaf::DownExpansion => {
                TrendFormation::HandoffToUpperLevel(UpperLevelExpansionEvidence {
                    level,
                    first_pair: ev.clone(),
                    additional_pairs: Vec::new(),
                })
            }
            PairLeaf::CoreNotStrictlySeparated => {
                TrendFormation::InsufficientMaterial(InsufficientMaterialEvidence {
                    level,
                    reason: InsufficientReason::CoreNotStrictlySeparated {
                        pairs: vec![ev.clone()],
                    },
                })
            }
        },
    }
}

/// 从 `center_scan::scan_center_facts_full` 的扫描结果直接判本级形成侧结果。
///
/// 直接消费 `scan.pair_facts(units)` 的 [`PairOutcome`]，不重写中枢或外缘判据。
pub fn judge_from_scan(
    level: usize,
    scan: &CenterScanFacts,
    units: &[UnitRange],
) -> TrendFormation {
    let (nodes, pairs) = extract_scan_chain(scan, units);
    judge_sequence_core(level, &nodes, &pairs)
}

/// 对扫描结果中的每一对相邻中枢逐对判定形成侧结果（仅相邻对，不跨中枢配对）。
pub fn judge_scan_pairs(
    level: usize,
    scan: &CenterScanFacts,
    units: &[UnitRange],
) -> Vec<TrendFormation> {
    let (_, pairs) = extract_scan_chain(scan, units);
    pairs
        .iter()
        .map(|p| judge_adjacent_pair(level, p))
        .collect()
}

/// 从已构造的中枢链（例如合成中枢级夹具或上级中枢序列）判本级形成侧结果。
///
/// 只对连续相邻中枢 `(i, i + 1)` 经 [`center_pair_facts`] 求 [`PairOutcome`]，绝不跳过中间中枢配对。
pub fn judge_from_center_chain(
    level: usize,
    centers: &[ChainCenterInput],
    connectors_between: &[Vec<ConnectorUnit>],
) -> Result<TrendFormation, ChainInputError> {
    let pairs = build_validated_chain_pairs(centers, connectors_between)?;
    Ok(judge_sequence_core(level, centers, &pairs))
}

/// 对已构造中枢链中的每一对相邻中枢逐对判定形成侧结果。
pub fn judge_center_chain_pairs(
    level: usize,
    centers: &[ChainCenterInput],
    connectors_between: &[Vec<ConnectorUnit>],
) -> Result<Vec<TrendFormation>, ChainInputError> {
    let pairs = build_validated_chain_pairs(centers, connectors_between)?;
    Ok(pairs
        .iter()
        .map(|p| judge_adjacent_pair(level, p))
        .collect())
}

fn extract_scan_chain(
    scan: &CenterScanFacts,
    units: &[UnitRange],
) -> (Vec<ChainCenterInput>, Vec<AdjacentPairInput>) {
    assert_eq!(units.len(), scan.len, "units 必须是本次扫描的输入");
    let nodes: Vec<ChainCenterInput> = scan
        .windows
        .iter()
        .enumerate()
        .map(|(w_idx, w)| {
            let settlement = if w.exit < scan.len {
                CenterSettlement::Settled { break_unit: w.exit }
            } else {
                CenterSettlement::Open
            };
            if w.upgraded {
                ChainCenterInput::PendingUpgrade {
                    window_index: w_idx,
                    member_units: w.seed_at..w.exit,
                    settlement,
                }
            } else {
                let center = scan.window_center(units, w_idx);
                let ev = CenterEvidence::try_new(w_idx, w.seed_at..w.exit, center, settlement)
                    .expect("scan_center_facts_full 产出的 <9 窗口恒满足中枢域与成员不变量");
                ChainCenterInput::Normal(ev)
            }
        })
        .collect();

    let pairs = scan
        .pair_facts(units)
        .into_iter()
        .map(|pf| {
            let connectors: Vec<ConnectorUnit> = pf
                .connectors
                .map(|u_idx| ConnectorUnit {
                    unit_index: u_idx,
                    unit: units[u_idx],
                })
                .collect();
            AdjacentPairInput::try_new(
                nodes[pf.left].clone(),
                nodes[pf.right].clone(),
                connectors,
                pf.outcome,
            )
            .expect("scan.pair_facts 产出的相邻对恒满足相邻性、连接段非空与 PairOutcome 一致性")
        })
        .collect();

    (nodes, pairs)
}

fn build_validated_chain_pairs(
    centers: &[ChainCenterInput],
    connectors_between: &[Vec<ConnectorUnit>],
) -> Result<Vec<AdjacentPairInput>, ChainInputError> {
    let expected_slots = centers.len().saturating_sub(1);
    if connectors_between.len() != expected_slots {
        return Err(ChainInputError::ConnectorCountMismatch {
            centers: centers.len(),
            connector_slots: connectors_between.len(),
        });
    }
    if let Some(first) = centers.first() {
        let base = first.window_index();
        for (pos, node) in centers.iter().enumerate() {
            let expected = base + pos;
            let actual = node.window_index();
            if actual != expected {
                return Err(ChainInputError::NonContiguousWindowIndex {
                    position: pos,
                    expected,
                    actual,
                });
            }
        }
    }

    let mut pairs = Vec::with_capacity(expected_slots);
    for (idx, win) in centers.windows(2).enumerate() {
        let left = win[0].clone();
        let right = win[1].clone();
        let outcome = match (&left, &right) {
            (ChainCenterInput::Normal(a), ChainCenterInput::Normal(b)) => {
                PairOutcome::Evaluated(center_pair_facts(&a.center, &b.center))
            }
            _ => PairOutcome::PendingUpgrade,
        };
        let pair =
            AdjacentPairInput::try_new(left, right, connectors_between[idx].clone(), outcome)?;
        pairs.push(pair);
    }
    Ok(pairs)
}

/// 整链形成侧唯一核心：零中枢→素材不足，单中枢→盘整（未升级）或待升级，多中枢→逐相邻对聚合。
fn judge_sequence_core(
    level: usize,
    nodes: &[ChainCenterInput],
    pairs: &[AdjacentPairInput],
) -> TrendFormation {
    match nodes {
        [] => TrendFormation::InsufficientMaterial(InsufficientMaterialEvidence {
            level,
            reason: InsufficientReason::NoCenter,
        }),
        [ChainCenterInput::Normal(center)] => {
            TrendFormation::Consolidation(ConsolidationEvidence {
                level,
                center: center.clone(),
            })
        }
        [ChainCenterInput::PendingUpgrade { window_index, .. }] => {
            TrendFormation::InsufficientMaterial(InsufficientMaterialEvidence {
                level,
                reason: InsufficientReason::PendingUpgrade {
                    window_indices: vec![*window_index],
                },
            })
        }
        _ => {
            let upgraded_windows: Vec<usize> = nodes
                .iter()
                .filter(|n| n.is_upgrade_pending())
                .map(ChainCenterInput::window_index)
                .collect();
            if !upgraded_windows.is_empty() {
                return TrendFormation::InsufficientMaterial(InsufficientMaterialEvidence {
                    level,
                    reason: InsufficientReason::PendingUpgrade {
                        window_indices: upgraded_windows,
                    },
                });
            }
            if pairs.len() == 1 {
                return judge_adjacent_pair(level, &pairs[0]);
            }

            let evaluated: Vec<AdjacentPairEvidence> = pairs
                .iter()
                .map(|p| match &p.inner {
                    ValidatedPair::Evaluated(ev) => ev.clone(),
                    ValidatedPair::PendingUpgrade { .. } => {
                        unreachable!("已排除待升级节点")
                    }
                })
                .collect();

            if evaluated
                .iter()
                .all(|e| e.pair_facts.leaf == PairLeaf::UpNewbirth)
            {
                let mut iter = evaluated.into_iter();
                let forming_pair = iter.next().expect("至少 2 对");
                return TrendFormation::UpTrendFormed(TrendFormationEvidence {
                    level,
                    forming_pair,
                    continuation_pairs: iter.collect(),
                });
            }
            if evaluated
                .iter()
                .all(|e| e.pair_facts.leaf == PairLeaf::DownNewbirth)
            {
                let mut iter = evaluated.into_iter();
                let forming_pair = iter.next().expect("至少 2 对");
                return TrendFormation::DownTrendFormed(TrendFormationEvidence {
                    level,
                    forming_pair,
                    continuation_pairs: iter.collect(),
                });
            }
            if evaluated.iter().all(|e| {
                matches!(
                    e.pair_facts.leaf,
                    PairLeaf::UpExpansion | PairLeaf::DownExpansion
                )
            }) {
                let mut iter = evaluated.into_iter();
                let first_pair = iter.next().expect("至少 2 对");
                return TrendFormation::HandoffToUpperLevel(UpperLevelExpansionEvidence {
                    level,
                    first_pair,
                    additional_pairs: iter.collect(),
                });
            }
            if evaluated
                .iter()
                .all(|e| e.pair_facts.leaf == PairLeaf::CoreNotStrictlySeparated)
            {
                return TrendFormation::InsufficientMaterial(InsufficientMaterialEvidence {
                    level,
                    reason: InsufficientReason::CoreNotStrictlySeparated { pairs: evaluated },
                });
            }

            let leaves = evaluated.iter().map(|e| e.pair_facts.leaf).collect();
            TrendFormation::InsufficientMaterial(InsufficientMaterialEvidence {
                level,
                reason: InsufficientReason::MixedAdjacentRelations { leaves },
            })
        }
    }
}
