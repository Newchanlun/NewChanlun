use std::num::NonZeroU32;

use serde_json::{Map, Value};

use super::registry::{Authority, FetchError, OriginalKind, Store, Verified};
use super::{CostStopProfile, RecordIdentity};
use crate::theta_v0::policy_records::{
    invalid, PolicyError, PolicyRef, PolicyVersion, COST_STOP_ID,
};

#[derive(Debug, PartialEq, Eq)]
pub struct SourceRef(String);

impl SourceRef {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct OriginalRef {
    key: SourceRef,
    sha256: String,
}

impl OriginalRef {
    pub fn key(&self) -> &str {
        self.key.as_str()
    }
    pub fn sha256(&self) -> &str {
        &self.sha256
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct Domain {
    profile_id: String,
    symbol: String,
    granularity: String,
    tower_base_ref: String,
    fee_tier: String,
}

impl Domain {
    pub fn profile_id(&self) -> &str {
        &self.profile_id
    }
    pub fn symbol(&self) -> &str {
        &self.symbol
    }
    pub fn granularity(&self) -> &str {
        &self.granularity
    }
    pub fn tower_base_ref(&self) -> &str {
        &self.tower_base_ref
    }
    pub fn fee_tier(&self) -> &str {
        &self.fee_tier
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct Fraction {
    numerator: u32,
    denominator: NonZeroU32,
}

impl Fraction {
    pub fn numerator(&self) -> u32 {
        self.numerator
    }
    pub fn denominator(&self) -> NonZeroU32 {
        self.denominator
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct SignedFee {
    venue: String,
    tier: String,
    role: String,
    source_url: SourceRef,
    retrieved_at: String,
    record_ref: Option<SourceRef>,
    rate: Fraction,
}

impl SignedFee {
    pub fn venue(&self) -> &str {
        &self.venue
    }
    pub fn tier(&self) -> &str {
        &self.tier
    }
    pub fn role(&self) -> &str {
        &self.role
    }
    pub fn source_url(&self) -> &SourceRef {
        &self.source_url
    }
    pub fn retrieved_at(&self) -> &str {
        &self.retrieved_at
    }
    pub fn record_ref(&self) -> Option<&SourceRef> {
        self.record_ref.as_ref()
    }
    pub fn rate(&self) -> &Fraction {
        &self.rate
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum SourceBinding {
    Unbound(SourceRef),
    Bound(OriginalRef),
}

#[derive(Debug, PartialEq, Eq)]
pub enum CostTerm {
    Known(SourceBinding),
    ProxyLowerBound(SourceBinding),
    Missing,
}

#[derive(Debug, PartialEq, Eq)]
pub enum HoldingTerm {
    Known {
        source: SourceBinding,
        start_level: u32,
    },
    Missing {
        start_level: u32,
        designated_source: Option<SourceRef>,
    },
}

pub(super) struct Terms {
    domain: Domain,
    pub fee: SignedFee,
    pub slippage: CostTerm,
    pub latency_error: CostTerm,
    pub holding: HoldingTerm,
    theta: Fraction,
    evidence_gate_ref: SourceRef,
    supersedes: String,
    authorizer_ref: SourceRef,
    authorized_at: String,
    valid_through: String,
}

/// 只读政策。仅通过编内已登记原件装载，不接受调用方传入的版本正文。
pub struct CostStopPolicy {
    pub(super) store: Store,
    identity: RecordIdentity,
    version: PolicyVersion,
    pub(super) terms: Terms,
}

impl CostStopPolicy {
    pub fn load(profile: CostStopProfile, revision: NonZeroU32) -> Result<Self, PolicyError> {
        Self::load_from(Store::registered(), profile, revision)
    }

    pub(super) fn load_from(
        store: Store,
        profile: CostStopProfile,
        revision: NonZeroU32,
    ) -> Result<Self, PolicyError> {
        let key = format!("{COST_STOP_ID}/{}@{revision}", profile.label());
        let original = store
            .fetch(OriginalKind::Policy, &key)
            .map_err(|err| match err {
                FetchError::NotFound => PolicyError::RecordMissing { id: COST_STOP_ID },
                FetchError::Digest => bad("content_sha256", "与登记摘要不符"),
                FetchError::WrongKind | FetchError::DuplicateKey => {
                    bad("id", "登记键不唯一或类别不符")
                }
            })?;
        let terms = parse_terms(&original, profile, revision)?;
        let version = match original.authority() {
            Authority::AwaitingApproval => return Err(awaiting("approval_ref")),
            Authority::Registered { reference } => {
                if reference.trim().is_empty() || reference != terms.authorizer_ref.as_str() {
                    return Err(bad("authorizer_ref", "与登记批复不符"));
                }
                if store.is_registered() {
                    PolicyVersion::Signed(revision.get())
                } else {
                    PolicyVersion::ResearchOverride
                }
            }
            #[cfg(test)]
            Authority::TestOnly => PolicyVersion::ResearchOverride,
        };
        Ok(Self {
            store,
            identity: original.identity().copy_identity(),
            version,
            terms,
        })
    }

    pub fn record(&self) -> PolicyRef {
        PolicyRef {
            id: COST_STOP_ID,
            version: self.version,
        }
    }
    pub fn identity(&self) -> &RecordIdentity {
        &self.identity
    }
    pub fn cost_terms(&self) -> (&CostTerm, &CostTerm, &HoldingTerm) {
        (
            &self.terms.slippage,
            &self.terms.latency_error,
            &self.terms.holding,
        )
    }
    pub fn theta(&self) -> &Fraction {
        &self.terms.theta
    }
    pub fn fee(&self) -> &SignedFee {
        &self.terms.fee
    }
    pub fn domain(&self) -> &Domain {
        &self.terms.domain
    }
    pub fn evidence_gate_ref(&self) -> &str {
        self.terms.evidence_gate_ref.as_str()
    }
    pub fn supersedes(&self) -> &str {
        &self.terms.supersedes
    }
    pub fn authorization(&self) -> (&str, &str, &str) {
        (
            self.terms.authorizer_ref.as_str(),
            &self.terms.authorized_at,
            &self.terms.valid_through,
        )
    }
}

pub(super) fn bad(path: &str, reason: impl Into<String>) -> PolicyError {
    invalid(COST_STOP_ID, path, reason)
}

fn awaiting(path: &str) -> PolicyError {
    PolicyError::AwaitingPolicy {
        id: COST_STOP_ID,
        field: path.to_owned(),
    }
}

fn present<'a>(value: &'a Value, path: &str) -> Result<&'a Value, PolicyError> {
    if value.is_null() || value.as_str() == Some("AwaitingPolicy") {
        return Err(awaiting(path));
    }
    Ok(value)
}

pub(super) fn json(original: &Verified) -> Result<Value, PolicyError> {
    serde_json::from_slice(original.bytes()).map_err(|error| bad("<record>", error.to_string()))
}

pub(super) fn req<'a>(root: &'a Value, path: &str) -> Result<&'a Value, PolicyError> {
    let mut value = root;
    let mut end = 0;
    for key in path.split('.') {
        let parent = &path[..end];
        end += key.len() + usize::from(end != 0);
        let field = &path[..end];
        let obj = value
            .as_object()
            .ok_or_else(|| bad(parent, "须为 JSON 对象"))?;
        value = present(obj.get(key).ok_or_else(|| awaiting(field))?, field)?;
    }
    Ok(value)
}

pub(super) fn object<'a>(
    value: &'a Value,
    path: &str,
    keys: &[&str],
) -> Result<&'a Map<String, Value>, PolicyError> {
    let obj = value
        .as_object()
        .ok_or_else(|| bad(path, "须为 JSON 对象"))?;
    if let Some(unexpected) = obj.keys().find(|key| !keys.contains(&key.as_str())) {
        return Err(bad(path, format!("未知字段 `{unexpected}`")));
    }
    Ok(obj)
}

pub(super) fn string<'a>(root: &'a Value, path: &str) -> Result<&'a str, PolicyError> {
    req(root, path)?
        .as_str()
        .ok_or_else(|| bad(path, "须为字符串"))
}

pub(super) fn unsigned<T: TryFrom<u64>>(root: &Value, path: &str) -> Result<T, PolicyError> {
    req(root, path)?
        .as_u64()
        .and_then(|x| T::try_from(x).ok())
        .ok_or_else(|| bad(path, "须为有效非负整数"))
}

pub(super) fn reference(root: &Value, path: &str) -> Result<SourceRef, PolicyError> {
    let text = string(root, path)?;
    if text.trim().is_empty() {
        return Err(bad(path, "引用不得为空"));
    }
    Ok(SourceRef(text.to_owned()))
}

fn optional_ref(
    root: &Value,
    path: &str,
    obj: &Map<String, Value>,
    key: &str,
) -> Result<Option<SourceRef>, PolicyError> {
    obj.contains_key(key)
        .then(|| reference(root, path))
        .transpose()
}

pub(super) fn digest_string(root: &Value, path: &str) -> Result<String, PolicyError> {
    let digest = string(root, path)?;
    if digest.len() != 64
        || !digest
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(bad(path, "须为小写 SHA-256"));
    }
    Ok(digest.to_owned())
}

pub(super) fn bound_ref(root: &Value, path: &str) -> Result<OriginalRef, PolicyError> {
    object(req(root, path)?, path, &["key", "sha256"])?;
    Ok(OriginalRef {
        key: reference(root, &format!("{path}.key"))?,
        sha256: digest_string(root, &format!("{path}.sha256"))?,
    })
}

pub(super) fn read_domain(root: &Value) -> Result<Domain, PolicyError> {
    object(
        req(root, "domain")?,
        "domain",
        &[
            "profile_id",
            "symbol",
            "granularity",
            "tower_base_ref",
            "fee_tier",
        ],
    )?;
    Ok(Domain {
        profile_id: string(root, "domain.profile_id")?.to_owned(),
        symbol: string(root, "domain.symbol")?.to_owned(),
        granularity: string(root, "domain.granularity")?.to_owned(),
        tower_base_ref: string(root, "domain.tower_base_ref")?.to_owned(),
        fee_tier: string(root, "domain.fee_tier")?.to_owned(),
    })
}

fn fraction(root: &Value, path: &str) -> Result<Fraction, PolicyError> {
    object(req(root, path)?, path, &["numerator", "denominator"])?;
    let numerator = unsigned(root, &format!("{path}.numerator"))?;
    let den_path = format!("{path}.denominator");
    let denominator = NonZeroU32::new(unsigned(root, &den_path)?)
        .ok_or_else(|| bad(&den_path, "分母不得为零"))?;
    Ok(Fraction {
        numerator,
        denominator,
    })
}

fn binding(
    root: &Value,
    path: &str,
    obj: &Map<String, Value>,
) -> Result<SourceBinding, PolicyError> {
    match (obj.contains_key("source_ref"), obj.contains_key("source")) {
        (true, false) => Ok(SourceBinding::Unbound(reference(
            root,
            &format!("{path}.source_ref"),
        )?)),
        (false, true) => Ok(SourceBinding::Bound(bound_ref(
            root,
            &format!("{path}.source"),
        )?)),
        (false, false) => Err(awaiting(&format!("{path}.source"))),
        (true, true) => Err(bad(path, "source_ref 和 source 只能选一项")),
    }
}

fn cost_term(root: &Value, path: &str) -> Result<CostTerm, PolicyError> {
    let value = req(root, path)?;
    let kind = string(root, &format!("{path}.kind"))?;
    if kind == "Missing" {
        object(value, path, &["kind"])?;
        return Ok(CostTerm::Missing);
    }
    let obj = object(value, path, &["kind", "source_ref", "source"])?;
    match kind {
        "Known" => Ok(CostTerm::Known(binding(root, path, obj)?)),
        "ProxyLowerBound" => Ok(CostTerm::ProxyLowerBound(binding(root, path, obj)?)),
        _ => Err(bad(path, "未知成本来源状态")),
    }
}

fn holding(
    root: &Value,
    profile: CostStopProfile,
    revision: NonZeroU32,
) -> Result<HoldingTerm, PolicyError> {
    let value = req(root, "holding")?;
    let start_level = unsigned(root, "holding.start_level")?;
    match string(root, "holding.kind")? {
        "Known" => {
            let obj = object(
                value,
                "holding",
                &["kind", "source_ref", "source", "start_level"],
            )?;
            Ok(HoldingTerm::Known {
                source: binding(root, "holding", obj)?,
                start_level,
            })
        }
        "Missing" => {
            let obj = object(
                value,
                "holding",
                &["kind", "start_level", "designated_source"],
            )?;
            let designated_source =
                optional_ref(root, "holding.designated_source", obj, "designated_source")?;
            if profile == CostStopProfile::P1HlTestnet
                && revision.get() == 1
                && designated_source.is_none()
            {
                return Err(awaiting("holding.designated_source"));
            }
            Ok(HoldingTerm::Missing {
                start_level,
                designated_source,
            })
        }
        _ => Err(bad("holding.kind", "未知持有来源状态")),
    }
}

fn parse_terms(
    original: &Verified,
    profile: CostStopProfile,
    revision: NonZeroU32,
) -> Result<Terms, PolicyError> {
    let root = json(original)?;
    object(
        &root,
        "<record>",
        &[
            "id",
            "profile_id",
            "version",
            "supersedes",
            "symbol",
            "granularity",
            "tower_base_ref",
            "fee",
            "slippage",
            "latency_error",
            "holding",
            "theta",
            "evidence_gate_ref",
            "authorizer_ref",
            "authorized_at",
            "valid_through",
        ],
    )?;
    for (field, expected) in [("id", COST_STOP_ID), ("profile_id", profile.label())] {
        if string(&root, field)? != expected {
            return Err(bad(field, "与登记身份不符"));
        }
    }
    if unsigned::<u32>(&root, "version")? != revision.get() {
        return Err(bad("version", "与登记修订不符"));
    }

    let fee_fields = object(
        req(&root, "fee")?,
        "fee",
        &[
            "venue",
            "tier",
            "role",
            "source_url",
            "retrieved_at",
            "record_ref",
            "rate",
        ],
    )?;
    let record_ref = optional_ref(&root, "fee.record_ref", fee_fields, "record_ref")?;
    if profile == CostStopProfile::P0 && revision.get() == 1 && record_ref.is_none() {
        return Err(awaiting("fee.record_ref"));
    }
    let fee = SignedFee {
        venue: string(&root, "fee.venue")?.to_owned(),
        tier: string(&root, "fee.tier")?.to_owned(),
        role: string(&root, "fee.role")?.to_owned(),
        source_url: reference(&root, "fee.source_url")?,
        retrieved_at: string(&root, "fee.retrieved_at")?.to_owned(),
        record_ref,
        rate: fraction(&root, "fee.rate")?,
    };
    let theta = fraction(&root, "theta")?;
    if theta.numerator < theta.denominator.get() {
        return Err(bad("theta", "ADR 0035：分子不得小于分母"));
    }
    Ok(Terms {
        domain: Domain {
            profile_id: profile.label().to_owned(),
            symbol: string(&root, "symbol")?.to_owned(),
            granularity: string(&root, "granularity")?.to_owned(),
            tower_base_ref: string(&root, "tower_base_ref")?.to_owned(),
            fee_tier: fee.tier.clone(),
        },
        fee,
        slippage: cost_term(&root, "slippage")?,
        latency_error: cost_term(&root, "latency_error")?,
        holding: holding(&root, profile, revision)?,
        theta,
        evidence_gate_ref: reference(&root, "evidence_gate_ref")?,
        supersedes: string(&root, "supersedes")?.to_owned(),
        authorizer_ref: reference(&root, "authorizer_ref")?,
        authorized_at: string(&root, "authorized_at")?.to_owned(),
        valid_through: string(&root, "valid_through")?.to_owned(),
    })
}
