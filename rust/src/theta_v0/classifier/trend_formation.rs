//! #1426 TB-02-G 形成侧内核：只接收同级单元来源，内部运行共用中枢扫描，给出每对相邻中枢的
//! 走势形成判定台账（趋势已形成 / 开放期严格分离 / 扩展交上级 / 核心未严格分离 / 待升级暂缓）。
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
//! ## 边界与主控裁定（r3）
//!
//! - **信任根**：传入的 `units` 切片与 `unit_level` 即信任根。内核无法判断切片是否为该级完整的已确认单元
//!   序列；把九段窗口的局部子区间当作独立来源传入，结果仅对该份来源为真。带封印的单元来源类型须改动塔，
//!   归 #1429，本票不做。
//! - **0 级与其余级的种子分派（E1）**：私有 `seed_build` 是本模块唯一读取 `unit_level` 的位置，0 级返回
//!   [`center_from_segments`]，其余返回 [`center_from_window`]，照抄塔的分派
//!   （`recursive_tower.rs:409-416,706`）。该分派即 E1，已由 #812 Z-3 裁为伪分歧
//!   （`docs/agents/doctrine-rules.md:102-104`），不占总缝规则（#804）例外配额。
//! - **#2114 趋势正式确认时点**：唯一落点在私有函数 `confirmed()`；#2114 裁定落地前取保守口径（左右两端
//!   均已结算才输出 [`PairState::TrendFormed`]，否则输出 [`PairState::ProvisionalSeparation`]）。
//! - **K 线级稳定性**：前缀单调性仅对单元前缀成立；调用方负责只传解析器的稳定前缀（见 #2114）。L0 调用方
//!   通常传 `l0_units(layer.segments_valid_prefix())`。
//! - **范围**：本模块只判形成侧，结果是全部节点加全部相邻对的台账，不做同向延续分组，不断言走势完成、
//!   不设中阴态、不改 `s_session` 发布面。

use std::ops::Range;

use super::super::types::{Center, Direction};
use super::center::{center_from_segments, center_from_window, PairLeaf, UnitRange};
use super::center_scan::{scan_center_facts_full, PairOutcome};

/// 相邻中枢对的形成侧状态（由该对的 [`PairOutcome`] 与结算态现算，不存储、不装载证据）。
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

/// 共用扫描产出的单个中枢窗口节点（字段私有，只能由 [`judge_trend_formation`] 产出）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CenterNode {
    ordinal: usize,
    members: UnitSpan,
    break_unit: Option<UnitRange>,
    center: Option<Center>,
}

impl CenterNode {
    pub fn ordinal(&self) -> usize {
        self.ordinal
    }

    pub fn members(&self) -> &UnitSpan {
        &self.members
    }

    /// 突破段下标与单元内容；`None` 当且仅当窗口仍开放未结算。
    pub fn break_unit(&self) -> Option<(usize, &UnitRange)> {
        self.break_unit
            .as_ref()
            .map(|u| (self.members.range().end, u))
    }

    pub fn is_settled(&self) -> bool {
        self.break_unit.is_some()
    }

    /// 窗口中枢几何（核心 + Zn 外缘）；`None` 当且仅当共用扫描器标记了升级。
    pub fn center(&self) -> Option<Center> {
        self.center
    }
}

/// 一对相邻中枢窗口及其连接段、同源关系结果（字段私有，只能由 [`judge_trend_formation`] 产出）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PairJudgment {
    left: CenterNode,
    right: CenterNode,
    connectors: UnitSpan,
    outcome: PairOutcome,
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

    pub fn state(&self) -> PairState {
        match self.outcome {
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
        }
    }

    /// 本对在后续追加单元时不再变化（右端中枢已结算）。#2114 不改本方法语义。
    pub fn is_final(&self) -> bool {
        self.right.is_settled()
    }

    /// 已形成趋势凭据：当且仅当 `state()` 为 [`PairState::TrendFormed`] 时返回 `Some`。
    pub fn formed(&self) -> Option<FormedTrend<'_>> {
        match self.state() {
            PairState::TrendFormed { direction } => Some(FormedTrend {
                pair: self,
                direction,
            }),
            _ => None,
        }
    }
}

/// 已形成趋势的只读凭据（字段私有，仅由 [`PairJudgment::formed`] 签发）。
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
enum Chain {
    NoCenter,
    Lone(CenterNode),
    Linked(Vec<PairJudgment>),
}

/// 同一份同级单元序列的走势形成侧判定台账（全部节点 + 全部相邻对）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TrendFormation {
    unit_level: u32,
    unit_count: usize,
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
        match &self.chain {
            Chain::NoCenter => Vec::new(),
            Chain::Lone(node) => vec![node],
            Chain::Linked(pairs) => {
                let mut out = Vec::with_capacity(pairs.len() + 1);
                if let Some(first) = pairs.first() {
                    out.push(&first.left);
                    out.extend(pairs.iter().map(|p| &p.right));
                }
                out
            }
        }
    }

    /// 全部相邻中枢对的判定结果。
    pub fn pairs(&self) -> &[PairJudgment] {
        match &self.chain {
            Chain::NoCenter | Chain::Lone(_) => &[],
            Chain::Linked(pairs) => pairs,
        }
    }

    /// 右端已结算的前缀对（在追加单元后逐项不变）。
    pub fn final_pairs(&self) -> &[PairJudgment] {
        let pairs = self.pairs();
        let settled_prefix = pairs.iter().take_while(|p| p.is_final()).count();
        &pairs[..settled_prefix]
    }

    /// 本级盘整：当且仅当全链恰有一个中枢窗口且未被扫描器标升级时返回 `Some`。
    pub fn consolidation(&self) -> Option<&CenterNode> {
        match &self.chain {
            Chain::Lone(node) if node.center.is_some() => Some(node),
            _ => None,
        }
    }
}

/// 唯一公开入口：从同级单元序列运行共用扫描并产出走势形成侧台账。
///
/// `unit_level` 为单元序列的塔级下标，`0` 表示 L0 已确认线段（`pipeline.rs:959`）。
pub fn judge_trend_formation(unit_level: u32, units: &[UnitRange]) -> TrendFormation {
    let scan = scan_center_facts_full(units, seed_build(unit_level));
    let nodes: Vec<CenterNode> = scan
        .windows
        .iter()
        .enumerate()
        .map(|(k, w)| CenterNode {
            ordinal: k,
            members: span(units, w.seed_at..w.exit),
            break_unit: units.get(w.exit).copied(),
            center: (!w.upgraded).then(|| scan.window_center(units, k)),
        })
        .collect();
    let chain = if nodes.is_empty() {
        Chain::NoCenter
    } else if nodes.len() == 1 {
        let Some(only) = nodes.into_iter().next() else {
            unreachable!("len == 1");
        };
        Chain::Lone(only)
    } else {
        let pairs = scan
            .pair_facts(units)
            .into_iter()
            .map(|pf| PairJudgment {
                left: nodes[pf.left].clone(),
                right: nodes[pf.right].clone(),
                connectors: span(units, pf.connectors),
                outcome: pf.outcome,
            })
            .collect();
        Chain::Linked(pairs)
    };
    TrendFormation {
        unit_level,
        unit_count: units.len(),
        chain,
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

/// #2114 趋势正式确认时点的唯一落点（未裁前取保守口径：左右两端均已结算才确认已形成）。
fn confirmed(pair: &PairJudgment) -> bool {
    pair.left.is_settled() && pair.right.is_settled()
}
