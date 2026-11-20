//! #1719 I4 组件：严格 Broken 原件、精确 B 绑定及第二层清账审计。
//! 尚未接正式 S 解码、持久事务或 launcher。

use super::super::center_lifecycle::{CenterId, CenterLifecycleEvent};
use super::entry::LifecycleRevision;
use super::key::LifecycleKey;

/// ADR 0003 §1 登记的完成政策版本字符串（精确匹配）。
pub const CENTER_BREAK_COMPLETION_POLICY_V1: &str = "#1719/center-break-completion/v1";
pub const CENTER_BREAK_COMPLETION_POLICY_V2: &str = "#1719/center-break-completion/v2";

/// ADR 0003 §1 具名完成政策版本；字符串只在边界解析一次，内部按本枚举分派。
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum CompletionPolicyVersion {
    /// PR #1833 现行语义（冻结，仅服务历史 v1 回放/恢复与既有夹具）。
    V1,
    /// v1 加 U1 出生当步规则（新独立 center_break 运行只绑定本版）。
    V2,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnknownCompletionPolicyVersion {
    pub raw: String,
}

impl CompletionPolicyVersion {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::V1 => CENTER_BREAK_COMPLETION_POLICY_V1,
            Self::V2 => CENTER_BREAK_COMPLETION_POLICY_V2,
        }
    }

    /// 生产版本解析器：只接受 ADR 0003 §1 已登记的具名版本。签名由生产调用方核验。
    pub fn parse(raw: &str) -> Result<Self, UnknownCompletionPolicyVersion> {
        match raw {
            CENTER_BREAK_COMPLETION_POLICY_V1 => Ok(Self::V1),
            CENTER_BREAK_COMPLETION_POLICY_V2 => Ok(Self::V2),
            _ => Err(UnknownCompletionPolicyVersion {
                raw: raw.to_string(),
            }),
        }
    }

    /// 旧组件绑定合同接受非空 opaque 版本；保留原串，不把它登记为具名 v1。
    /// 新生产输入须经过严格的 `parse`，不能以组件接纳结果代替版本校验。
    pub(super) fn for_component_binding(raw: &str) -> Option<Self> {
        if raw.trim().is_empty() {
            None
        } else if raw == Self::V2.as_str() {
            Some(Self::V2)
        } else {
            Some(Self::V1)
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CompletionAnchor {
    ChannelSwitch,
    CenterBreak,
}

/// 生产调用方提供已签具名版本；组件保留调用方的原版本字符串。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompletionPolicy {
    pub version: String,
    pub anchor: CompletionAnchor,
}

impl CompletionPolicy {
    pub fn new(version: CompletionPolicyVersion, anchor: CompletionAnchor) -> Self {
        Self {
            version: version.as_str().to_string(),
            anchor,
        }
    }

    pub fn v1(anchor: CompletionAnchor) -> Self {
        Self::new(CompletionPolicyVersion::V1, anchor)
    }

    pub fn v2(anchor: CompletionAnchor) -> Self {
        Self::new(CompletionPolicyVersion::V2, anchor)
    }

    pub fn parse_version(&self) -> Result<CompletionPolicyVersion, UnknownCompletionPolicyVersion> {
        CompletionPolicyVersion::parse(&self.version)
    }
}

/// 只接受真实事件机输出中的 Broken。三类点确认源坐标保存在原件中；
/// physical_bar 由调用方按原输入映射提供，不能用消费钟冒充。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CenterBreakFact {
    event: CenterLifecycleEvent,
    physical_bar: usize,
    known_at: usize,
}

impl CenterBreakFact {
    pub fn from_event(
        event: &CenterLifecycleEvent,
        physical_bar: usize,
        known_at: usize,
    ) -> Option<Self> {
        match event {
            CenterLifecycleEvent::Broken { .. } => Some(Self {
                event: *event,
                physical_bar,
                known_at,
            }),
            _ => None,
        }
    }

    pub fn event(&self) -> &CenterLifecycleEvent {
        &self.event
    }

    pub fn physical_bar(&self) -> usize {
        self.physical_bar
    }

    pub fn known_at(&self) -> usize {
        self.known_at
    }

    pub(super) fn identity(&self) -> BreakIdentity {
        match self.event {
            CenterLifecycleEvent::Broken {
                level,
                center,
                chain_index,
                breaker_source_index,
                breaker_side,
            } => BreakIdentity {
                level,
                center_id: CenterId::of(&center),
                chain_index,
                breaker_source_index,
                side: super::key::side_tag(breaker_side),
            },
            _ => unreachable!("构造口只接受 Broken"),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub(super) struct BreakIdentity {
    pub level: u32,
    pub center_id: CenterId,
    pub chain_index: usize,
    pub breaker_source_index: usize,
    pub side: u8,
}

/// map 键是当前账本键；原对象/原注册钟/原政策永不覆盖。
/// binding_key 与 center_id 是最近一次由 provider 精确选中的 B，升级期间
/// 没有新的精确绑定时暂不清账，禁止按新 start 反查。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HypothesisBridge {
    pub lifecycle_key: LifecycleKey,
    pub original_center_id: CenterId,
    pub center_id: CenterId,
    pub binding_key: LifecycleKey,
    pub policy: CompletionPolicy,
    pub registered_at: usize,
}

impl HypothesisBridge {
    pub(super) fn selected(
        key: LifecycleKey,
        center_id: CenterId,
        policy: CompletionPolicy,
        registered_at: usize,
    ) -> Self {
        Self {
            lifecycle_key: key,
            original_center_id: center_id,
            center_id,
            binding_key: key,
            policy,
            registered_at,
        }
    }
}

/// 首次留档的合法 Broken 原件及留档先后证据；同身份重送不改写原件或首次留档时点。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ArchivedCenterBreakFact {
    pub fact: CenterBreakFact,
    pub archived_at: usize,
    pub archived_seq: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BreakApplicationMode {
    /// 常规清账（v1 与 v2 共有）：`application_at == fact.known_at()`。
    KnownAt,
    /// v2 出生当步清账：对象首次出生登记的同一步消费出生前已留档事实，
    /// `application_at == target_registered_at`，保留原 `fact_known_at`。
    BirthStep,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub(super) struct BreakApplicationKey {
    pub fact: BreakIdentity,
    pub original_key: LifecycleKey,
    pub policy_version: CompletionPolicyVersion,
}

/// 独立于原生命周期修订的清账凭证。分开保留原件、四钟（physical_bar / fact_known_at /
/// target_registered_at / application_at）、留档因果证据、原对象及原政策，
/// 不伪造 StructureCompleted、交易否证或成交。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CenterBreakAudit {
    pub fact: CenterBreakFact,
    pub bridge: HypothesisBridge,
    pub settled_key: LifecycleKey,
    pub policy_version: CompletionPolicyVersion,
    pub application_at: usize,
    pub fact_archived_at: usize,
    pub fact_archived_seq: u64,
    pub target_registered_seq: u64,
    pub mode: BreakApplicationMode,
    pub consumed_at: usize,
    pub physical_before_registration: bool,
}

/// #1719 重送绑定须显式报告冻结政策，不能把新政策报为已接纳。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BridgeRegistration {
    Accepted,
    PolicyFrozen,
    Rejected,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CenterBreakOutcome {
    Applied,
    NoTarget,
    NotReady,
    LatePendingRecovery,
    FactConflict,
    PolicyDisallowed,
    Preserved,
    AlreadyApplied,
    InvalidClock,
}

/// 每次消费的目标快照；迟到时保留拒绝所依据的门卫钟，供恢复按原钟重放。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CenterBreakTarget {
    pub key: LifecycleKey,
    pub bridge: HypothesisBridge,
    pub last_as_of: Option<usize>,
    pub physical_before_registration: bool,
}

/// 与实际清账凭证分开的追加审计，包含无目标、冲突和迟到待恢复。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CenterBreakAttempt {
    pub fact: CenterBreakFact,
    pub consumed_at: usize,
    pub target: Option<CenterBreakTarget>,
    pub outcome: CenterBreakOutcome,
}

/// 多目标可有不同结果；调用方须逐项消费 attempts，不能只看修订数。
#[derive(Debug, Clone, PartialEq)]
pub struct CenterBreakResult {
    pub revisions: Vec<LifecycleRevision>,
    pub attempts: Vec<CenterBreakAttempt>,
}
