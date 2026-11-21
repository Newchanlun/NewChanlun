//! #1426 TB-02-G 形成侧内核：只接收同级单元来源，内部运行共用中枢扫描，给出每对相邻中枢的
//! CC-020 关系台账，形成侧只投影所属走势的起始首对（#2114）。
//!
//! ## 教义依据（只实现正本既有定义，不裁新判据）
//!
//! - 盘整：完成盘整见 `017-第17课.md:44`【正文】与 `.chanlun/definitions/qushi.md:78`；形成侧单中枢即可
//!   具备盘整结构见 `018-第18课.md:40`【正文】与 `qushi.md:234`；盘整无语义方向且计数按相应级别见
//!   `031-第31课.md:390`【答疑】。多中枢扩展块不得在本级标盘整，属标错级别，交上级（#1429）：
//!   `qushi.md:93-102`。
//! - 趋势形成与扩展二分（中心定理二，M-2）：`020-第20课.md:58`【正文】、`.chanlun/definitions/qushi.md:124-131`、
//!   `.chanlun/definitions/zhongshu.md:254-266`。仅相邻（与 `020-第20课.md:44`【正文】合读的连续前后两个同级别中枢）
//!   参与判定，跳过中间中枢的非相邻配对非法。外缘 `GG/DD` 遍历中枢中所有 `Zn`（`020-第20课.md:52`【正文】、
//!   `zhongshu.md:210-232`）。
//! - 连接段归属（Z-5）与中枢存在性（Z-6）：`.chanlun/definitions/zhongshu.md:398-410`（一个中枢结算后自
//!   `last + 2` 续扫，跳过突破段；连接段位于前枢末成员之后、后枢首成员之前，不属于任一中枢）、
//!   `zhongshu.md:416-420`。
//! - 升级标记（S-4）：`033-第33课.md:16`【正文】、`.chanlun/definitions/zhongshu.md:268-276,290-296`。本模块
//!   不数段、不设阈值、不出带计数的错误类型，只转述共用扫描器的升级标记为 [`PairState::UpgradeDeferred`]；
//!   S-4③ 无波动段不计入升级计数的修复归 #1429，本票不修、不硬化。
//!
//! ## 边界与裁定
//!
//! - **信任根**：构造调用方提供同级已完成单元及其同源角色（如有）。扫描事实不作为入参。
//!   内核无法判断切片是否为该级完整的已确认单元序列，或窗首中枢是否属于该走势。
//!   #1429 接入前，由构造调用方以 [`WindowOrigin`] 显式担保归属；
//!   无担保不签发首证。接入 #1429 后改读构造归属，不沿用临时担保。
//! - **0 级与其余级的种子分派（E1）**：私有 `seed_build` 是本模块唯一读取 `unit_level` 的位置，0 级返回
//!   [`center_from_segments`]，其余返回 [`center_from_window`]，照抄塔的分派
//!   （`recursive_tower.rs:409-416,706`）。该分派即 E1，已由 #812 Z-3 裁为伪分歧
//!   （`docs/agents/doctrine-rules.md:102-104`），不占总缝规则（#804）例外配额。
//! - **#2114 趋势正式确认**：归属有担保的首对须外缘严格分离，且两端各具同一次扫描的两段式 R5 见证。
//!   结算方向不改写配对方向；反向 R5 不充作 `c` 内同向三类点。
//! - **K 线级稳定性**：前缀单调性仅对单元前缀成立；调用方负责只传解析器的稳定前缀（见 #2114）。
//!   `layer.segments_valid_prefix()` 仅按段端失败截断、无标记时返回整本段表，不证明跨 bar 稳定
//!   （`parser/mod.rs:103-106,145-157`），不得据此承诺 K 线级单调。
//! - **下游接口与凭据约束**：需要「趋势已形成」依据的下游接口应接收 [`FormedTrend`]，或从真实
//!   [`PairJudgment`] / [`TrendFormation`] 读取并核实 [`PairJudgment::formed`]；不得接收 [`PairState`]
//!   标签或裸 [`Direction`] 作为凭据（任何调用方均可直接写出 `PairState::TrendFormed { .. }`，标签与裸方向
//!   仅作只读投影）。若需绑定特定级别或账本身份，下游须同步保留相应账本上下文。
//! - **凭据生命周期与方向计算**：[`FormedTrend`] 绑定的是签发它的 [`PairJudgment`] 而非原
//!   [`TrendFormation`] 账本——直接让借来的凭据逃出将释放的原账本会报 `E0515`，但克隆真对、释放原账本后再从
//!   克隆签发凭据可以成功且是允许的。[`PairJudgment::state`] 每次读叶现算，[`PairJudgment::formed`] 在签发
//!   凭据时取本次算出的方向并由 [`FormedTrend::direction`] 返回。
//! - **范围**：本模块只判形成侧，结果是全部节点加全部相邻对的台账，不做同向延续分组，不断言走势完成、
//!   不设中阴态、不改 `s_session` 发布面。

use std::ops::Range;

use super::super::types::{Center, Direction};
use super::center::{center_from_segments, center_from_window, PairLeaf, UnitRange};
use super::center_scan::{
    scan_center_facts_with_r5, PairOutcome, R5Boundary, R5DirectionSource, R5Gap, R5Witness,
    RoleProvider,
};

/// #2114 过渡期：由构造调用方担保输入窗首枢是本走势的首枢（#1429 接入前）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WindowOrigin {
    /// 已核定首枢归属，不借前一走势的末枢。
    MoveStartGuaranteed,
    /// 首枢归属未核定，或输入可能从前一走势的末枢起算。
    UnverifiedOrPriorTail,
}

/// 起始首对的形成侧只读投影标签，不能作为凭据。
///
/// 任何调用方均可直接手写 `PairState::TrendFormed { .. }`，故本枚举**不得作为下游接口的「已形成」凭据入参**；
/// 需要「已形成」依据时应接收 [`FormedTrend`]，或从真实 [`PairJudgment`] / [`TrendFormation`] 调用
/// [`PairJudgment::formed`]。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum PairState {
    /// 趋势已形成：外缘严格分离且满足 `confirmed()` 确认点（#2114 唯一落点）。
    TrendFormed { direction: Direction },
    /// 开放期严格分离：外缘严格分离但未达 `confirmed()` 确认点，后续延伸仍可翻转。
    ProvisionalSeparation { observed_direction: Direction },
    /// 扩展关系交上级（#1429）：核心严格分离且外缘重叠或相切，不得在本级标盘整。
    ExpansionHandoff,
    /// 核心未严格分离：不进中心定理二，两段式结算归 #1496。
    CoreNotStrictlySeparated,
    /// 任一端被共用扫描器标记升级，本级不判（转述扫描器标记，归 #1429）。
    UpgradeDeferred,
}

impl PairState {
    pub fn label(&self) -> &'static str {
        match self {
            Self::TrendFormed { .. } => "趋势已形成",
            Self::ProvisionalSeparation { .. } => "开放期严格分离（当下读法；TrendFormed 未发）",
            Self::ExpansionHandoff => "扩展交上级",
            Self::CoreNotStrictlySeparated => "核心未严格分离",
            Self::UpgradeDeferred => "待升级暂缓",
        }
    }
}

/// 来自同一次扫描来源切片的连续单元区间及其单元内容副本。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnitSpan {
    start: usize,
    units: Box<[UnitRange]>,
}

impl UnitSpan {
    pub fn range(&self) -> Range<usize> {
        self.start..self.start + self.units.len()
    }

    pub fn units(&self) -> &[UnitRange] {
        &self.units
    }
}

/// 共用扫描产出的单个中枢窗口节点（字段私有，由形成入口产出）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CenterNode {
    ordinal: usize,
    members: UnitSpan,
    break_unit: Option<UnitRange>,
    r5_witness: R5Witness,
    center: Option<Center>,
}

impl CenterNode {
    pub fn ordinal(&self) -> usize {
        self.ordinal
    }

    pub fn members(&self) -> &UnitSpan {
        &self.members
    }

    /// 首个不重叠单元的下标与内容；待决退出也可有值，升级边界不是突破。
    pub fn break_unit(&self) -> Option<(usize, &UnitRange)> {
        self.break_unit
            .as_ref()
            .map(|u| (self.members.range().end, u))
    }

    /// 扫描退出的浅层标记；正式 R5 结算须读 [`Self::r5_witness`]。
    pub fn is_settled(&self) -> bool {
        self.break_unit.is_some()
    }

    /// 本窗口在同一次共用扫描中的 R5 结算见证（或缺席原因）。
    pub fn r5_witness(&self) -> R5Witness {
        self.r5_witness
    }

    /// 窗口中枢几何（核心 + Zn 外缘）；`None` 当且仅当共用扫描器标记了升级。
    pub fn center(&self) -> Option<Center> {
        self.center
    }
}

/// 一对相邻中枢窗口及其连接段、同源关系结果（字段私有，由形成入口产出）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PairJudgment {
    left: CenterNode,
    right: CenterNode,
    connectors: UnitSpan,
    outcome: PairOutcome,
    origin: WindowOrigin,
}

impl PairJudgment {
    pub fn left(&self) -> &CenterNode {
        &self.left
    }

    pub fn right(&self) -> &CenterNode {
        &self.right
    }

    pub fn connectors(&self) -> &UnitSpan {
        &self.connectors
    }

    pub fn outcome(&self) -> PairOutcome {
        self.outcome
    }

    /// 只有窗首 A→B 有形成侧值；其余相邻对仅保留 [`Self::outcome`]。
    pub fn state(&self) -> Option<PairState> {
        if self.left.ordinal != 0 {
            return None;
        }
        Some(match self.outcome {
            PairOutcome::PendingUpgrade => PairState::UpgradeDeferred,
            PairOutcome::Evaluated(facts) => match facts.leaf {
                PairLeaf::UpNewbirth | PairLeaf::DownNewbirth => {
                    let Some(direction) = facts.leaf.direction() else {
                        unreachable!("新生叶恒携带方向");
                    };
                    if confirmed(self) {
                        PairState::TrendFormed { direction }
                    } else {
                        PairState::ProvisionalSeparation {
                            observed_direction: direction,
                        }
                    }
                }
                PairLeaf::UpExpansion | PairLeaf::DownExpansion => PairState::ExpansionHandoff,
                PairLeaf::CoreNotStrictlySeparated => PairState::CoreNotStrictlySeparated,
            },
        })
    }

    /// 本对在后续追加单元时不再变化：右端共用扫描已结算或已固定为待升级。
    /// 这是台账的前缀边界，不是首证。
    pub fn is_final(&self) -> bool {
        matches!(
            self.right.r5_witness,
            R5Witness::Proven(_) | R5Witness::Absent(R5Gap::UpgradePending)
        )
    }

    /// 已形成趋势凭据：当且仅当 [`Self::state`]（每次读叶现算）为 [`PairState::TrendFormed`] 时
    /// 签发 [`FormedTrend`]，并在签发时取本次方向。凭据生命周期绑定本 `PairJudgment` 而非原
    /// [`TrendFormation`] 账本：直接借出将释放的原账本报 `E0515`，克隆真对、释放原账本后再从克隆签发允许。
    pub fn formed(&self) -> Option<FormedTrend<'_>> {
        match self.state() {
            Some(PairState::TrendFormed { direction }) => Some(FormedTrend {
                pair: self,
                direction,
            }),
            _ => None,
        }
    }
}

/// 已形成趋势的只读凭据（字段私有，仅由 [`PairJudgment::formed`] 签发）。
///
/// 生命周期绑定签发它的 [`PairJudgment`]（而非原 [`TrendFormation`] 账本）；方向在签发时自叶读取并随凭据保存，
/// [`Self::direction`] 返回该签发方向。下游需要「已形成」依据时应收本类型或真 [`PairJudgment`] / [`TrendFormation`]，
/// 不得收 [`PairState`] 或裸 [`Direction`]。
#[derive(Debug, Clone, Copy)]
pub struct FormedTrend<'a> {
    pair: &'a PairJudgment,
    direction: Direction,
}

impl<'a> FormedTrend<'a> {
    pub fn direction(&self) -> Direction {
        self.direction
    }

    pub fn pair(&self) -> &'a PairJudgment {
        self.pair
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Chain {
    centers: Vec<CenterNode>,
    pairs: Vec<PairJudgment>,
}

/// 同一份同级单元序列的走势形成侧判定台账（全部节点 + 全部相邻对）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TrendFormation {
    unit_level: u32,
    unit_count: usize,
    origin: WindowOrigin,
    chain: Chain,
}

impl TrendFormation {
    pub fn unit_level(&self) -> u32 {
        self.unit_level
    }

    pub fn unit_count(&self) -> usize {
        self.unit_count
    }

    pub fn centers(&self) -> Vec<&CenterNode> {
        self.chain.centers.iter().collect()
    }

    /// 全部共用扫描给出的相邻关系。扫描因升级续扫时，不补造未给出的连接。
    pub fn pairs(&self) -> &[PairJudgment] {
        &self.chain.pairs
    }

    /// 扫描边界已固定的前缀对（在追加单元后逐项不变）。
    pub fn final_pairs(&self) -> &[PairJudgment] {
        let pairs = self.pairs();
        let settled_prefix = pairs.iter().take_while(|p| p.is_final()).count();
        &pairs[..settled_prefix]
    }

    /// 本级盘整：当且仅当全链恰有一个中枢窗口且未被扫描器标升级时返回 `Some`。
    pub fn consolidation(&self) -> Option<&CenterNode> {
        match self.chain.centers.as_slice() {
            [node] if node.center.is_some() => Some(node),
            _ => None,
        }
    }

    /// 开放实例保持 CC-025 `FORMED_OPEN` 的形成侧单枢依据。
    /// 在首证发出前保留原首枢，扩展交接不创建上级对象。本方法不判实例生命周期。
    pub fn formed_open_center(&self) -> Option<&CenterNode> {
        if self.origin != WindowOrigin::MoveStartGuaranteed
            || self
                .pairs()
                .first()
                .is_some_and(|pair| pair.formed().is_some())
        {
            return None;
        }
        self.chain
            .centers
            .first()
            .filter(|node| node.center.is_some())
    }
}

/// 从方向真实且没有额外角色证据的同级已完成单元运行共用扫描。输入窗归属必须显式传入。
/// `unit_level` 为单元序列的塔级下标，`0` 表示 L0 已确认线段（`pipeline.rs:959`）。
pub fn judge_trend_formation(
    unit_level: u32,
    units: &[UnitRange],
    origin: WindowOrigin,
) -> TrendFormation {
    judge_trend_formation_with_roles(
        unit_level,
        units,
        RoleProvider {
            directions: R5DirectionSource::Native,
            attested: &[],
        },
        origin,
    )
}

/// 已完成单元的构造方通过 [`RoleProvider`] 提供同一构造流的方向出处与外段角色。
/// 输入窗归属仍须单独传入。窗口、见证、连接与 CC-020 关系均从本次共用扫描生成。
pub fn judge_trend_formation_with_roles(
    unit_level: u32,
    units: &[UnitRange],
    roles: RoleProvider<'_>,
    origin: WindowOrigin,
) -> TrendFormation {
    let scan = scan_center_facts_with_r5(
        units,
        seed_build(unit_level),
        roles.directions,
        roles.attested,
    );
    let centers: Vec<CenterNode> = scan
        .windows
        .iter()
        .zip(scan.r5_witnesses(units))
        .enumerate()
        .map(|(k, (w, r5_witness))| CenterNode {
            ordinal: k,
            members: span(units, w.seed_at..w.exit),
            break_unit: match w.boundary {
                R5Boundary::Pending { tested, .. } => Some(units[tested]),
                R5Boundary::Destroyed(_) => Some(units[w.exit]),
                R5Boundary::Open | R5Boundary::Upgrade => None,
            },
            r5_witness,
            center: (!w.upgraded).then(|| scan.window_center(units, k)),
        })
        .collect();
    let pairs = scan
        .pair_facts(units)
        .into_iter()
        .map(|pf| PairJudgment {
            left: centers[pf.left].clone(),
            right: centers[pf.right].clone(),
            connectors: span(units, pf.connectors),
            outcome: pf.outcome,
            origin,
        })
        .collect();
    TrendFormation {
        unit_level,
        unit_count: units.len(),
        origin,
        chain: Chain { centers, pairs },
    }
}

/// 照抄塔的分派（`recursive_tower.rs:409-416,706`）：0 级用完整判据，其余用几何判据。
/// 这是本模块唯一读取 `unit_level` 的位置；该分派即 E1，已由 #812 Z-3 裁为伪分歧
/// （`docs/agents/doctrine-rules.md:102-104`），不占总缝规则（#804）例外配额。
fn seed_build(unit_level: u32) -> fn(&UnitRange, &UnitRange, &UnitRange) -> Option<Center> {
    if unit_level == 0 {
        center_from_segments
    } else {
        center_from_window
    }
}

fn span(units: &[UnitRange], range: Range<usize>) -> UnitSpan {
    let start = range.start;
    UnitSpan {
        start,
        units: units[range].to_vec().into_boxed_slice(),
    }
}

/// 仅在首对的新生叶分支调用。待升级由共用关系先行排除，方向仍取新生叶。
fn confirmed(pair: &PairJudgment) -> bool {
    pair.origin == WindowOrigin::MoveStartGuaranteed
        && matches!(pair.left.r5_witness, R5Witness::Proven(_))
        && matches!(pair.right.r5_witness, R5Witness::Proven(_))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::theta_v0::classifier::center_scan::l0_units;
    use crate::theta_v0::classifier::signal::{T3InCScan, T3InCSource};
    use crate::theta_v0::types::Segment;
    use Direction::{Down, Up};

    #[test]
    fn reverse_b_r5_is_not_the_trends_same_direction_t3_in_c() {
        let prices = [40, 10, 35, 20, 60, 55, 65, 51, 60, 50, 61, 44, 47];
        let segments: Vec<_> = prices
            .windows(2)
            .enumerate()
            .map(|(k, w)| Segment {
                start_index: k * 4,
                end_index: k * 4 + 4,
                direction: if w[1] > w[0] { Up } else { Down },
                start_price: w[0],
                end_price: w[1],
            })
            .collect();
        let tf = judge_trend_formation(0, &l0_units(&segments), WindowOrigin::MoveStartGuaranteed);
        let pair = &tf.pairs()[0];
        let direction = pair.formed().unwrap().direction();
        assert_eq!(direction, Up);
        let b = pair.right().center().unwrap();
        let R5Witness::Proven(proof) = pair.right().r5_witness() else {
            panic!("后枢应有反向 R5 结算");
        };
        let source = T3InCSource::Scanned(Some(proof));
        let start = segments[proof.leave_unit()].start_index;
        let end = segments[proof.pullback_unit()].end_index;
        assert_eq!(
            source.grade(&segments, &b, direction, start, end),
            T3InCScan::Missing
        );
        assert!(matches!(
            source.grade(&segments, &b, Down, start, end),
            T3InCScan::Present { .. }
        ));
    }
}
