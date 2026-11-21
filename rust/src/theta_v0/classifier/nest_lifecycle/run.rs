//! #1719 I4 运行级接缝：先冻结单一完成政策，再喂入本次运行的全部对象。

use super::feed::feed_replay_bar_with_birth_evidence;
use super::*;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum I4RunAdmissionError {
    UnknownVersion(UnknownCompletionPolicyVersion),
    NewCenterBreakRequiresV2,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct I4RunPolicyMismatch {
    pub key: LifecycleKey,
    pub expected: CompletionPolicy,
    pub supplied: CompletionPolicy,
}

/// I4 账本的运行级入口。账本只对外提供只读借用，逐对象绑定不能绕过运行政策。
#[derive(Debug)]
pub struct I4CompletionRun {
    policy: CompletionPolicy,
    book: NestLifecycleBook,
}

impl I4CompletionRun {
    /// 调用方核验已签政策；新独立 center_break 运行显式拒绝 v1，不换档。
    pub fn start_new(policy: CompletionPolicy) -> Result<Self, I4RunAdmissionError> {
        let version = policy
            .parse_version()
            .map_err(I4RunAdmissionError::UnknownVersion)?;
        if policy.anchor == CompletionAnchor::CenterBreak && version != CompletionPolicyVersion::V2
        {
            return Err(I4RunAdmissionError::NewCenterBreakRequiresV2);
        }
        Ok(Self::with_policy(policy))
    }

    /// 从原运行已持久的政策绑定重建 I4 账本；即使在新进程，也不走新运行准入。
    /// 调用方负责从原运行读取绑定与事实，并按原序回放；本组件不另要求存量证明。
    pub fn replay_history(persisted_policy: CompletionPolicy) -> Result<Self, I4RunAdmissionError> {
        persisted_policy
            .parse_version()
            .map_err(I4RunAdmissionError::UnknownVersion)?;
        Ok(Self::with_policy(persisted_policy))
    }

    fn with_policy(policy: CompletionPolicy) -> Self {
        Self {
            policy,
            book: NestLifecycleBook::new(),
        }
    }

    /// provider 生成每一份伴随绑定时都使用此处的冻结政策。
    pub fn policy(&self) -> &CompletionPolicy {
        &self.policy
    }

    pub fn book(&self) -> &NestLifecycleBook {
        &self.book
    }

    /// 接收来源 owner 交付的 Broken，保留首次留档与普通消费结果。
    /// 重送不改变已记录的来源撤回状态。
    pub fn apply_center_break(
        &mut self,
        fact: &CenterBreakFact,
        as_of: usize,
    ) -> CenterBreakResult {
        self.book.apply_center_break(fact, as_of)
    }

    /// 先校验整批政策；混版或换锚整批拒绝，不修改账本。
    /// v2 自动清账须同时提供本步的来源有效性证据；缺失时仍正常观察和登记。
    /// 来源也可在后续喂入中更新原件状态；后来的确认不能倒填原已知钟。
    pub fn feed_bar(
        &mut self,
        feed: &ReplayBarFeed<'_>,
        material: &ForceMaterial,
        bindings: &[HypothesisBridge],
        birth_evidence: Option<&CenterBreakBirthEvidence<'_>>,
    ) -> Result<
        (
            Vec<LifecycleRevision>,
            ReplayFeedStats,
            Vec<BridgeRegistration>,
        ),
        I4RunPolicyMismatch,
    > {
        if let Some(binding) = bindings
            .iter()
            .find(|binding| binding.policy != self.policy)
        {
            return Err(I4RunPolicyMismatch {
                key: binding.lifecycle_key,
                expected: self.policy.clone(),
                supplied: binding.policy.clone(),
            });
        }
        let birth_evidence = birth_evidence.filter(|_| {
            self.policy.anchor == CompletionAnchor::CenterBreak
                && self.policy.version == CompletionPolicyVersion::V2.as_str()
        });
        Ok(feed_replay_bar_with_birth_evidence(
            &mut self.book,
            feed,
            material,
            bindings,
            birth_evidence,
        ))
    }
}
