//! #1374：固定 TestOnly 定义证据权威。请求只给引用；独评收据与完整原件均由 manifest 固定。
//! 此适配器不生产 γ，不调用旧 π，也不把 Closed/Strict 作为定义 γ 的前置。
#[cfg(test)]
use super::book::hash;
use super::deployment::{self, logical_name};
use super::store::Config;
use super::voice::{digest, exact};
use crate::session_protocol::{nonnegative, positive, required, sha256_hex, strict_json};
use serde_json::{json, Value};
use std::path::Path;
const V1: &str = "voice-binding/1";
const V2: &str = "voice-binding/2";
pub(super) fn bound_revision(c: &Config) -> Option<&'static str> {
    enabled(c).then(|| {
        if deployment::is_business(&c.manifest) {
            V2
        } else {
            V1
        }
    })
}
pub(super) const REQUIRED_ROLES: &[&str] = &[
    "input",
    "controlled_gammas",
    "carrier_objects",
    "instrument_declaration",
    "opening_raw",
];
const LIMIT: u64 = 64 * 1024 * 1024;

pub(super) struct VerifiedGammaEvidence {
    binding: Value,
    reference: Value,
    witness: Value,
    observation_ns: i64,
}
impl VerifiedGammaEvidence {
    pub(super) fn observation_ns(&self) -> i64 {
        self.observation_ns
    }
    pub(super) fn binding(&self) -> &Value {
        &self.binding
    }
    pub(super) fn reference(&self) -> Value {
        self.reference.clone()
    }
    pub(super) fn witness(&self) -> Value {
        self.witness.clone()
    }
}
pub(super) fn enabled(config: &Config) -> bool {
    config.domain.starts_with("B:")
        && config
            .manifest
            .get("voice_binding")
            .is_some_and(|v| !v.is_null())
}
pub(super) fn validate_config(manifest: &Value) -> Result<(), String> {
    let Some(v) = manifest.get("voice_binding").filter(|v| !v.is_null()) else {
        return Ok(());
    };
    exact(v, &["schema_revision", "authorities"])?;
    let split = deployment::is_business(manifest);
    if v["schema_revision"] != if split { V2 } else { V1 }
        || manifest["clock"]["kind"] != "TestOnly"
    {
        return Err("SchemaUnsupported：Voice 证据版本与 TestOnly 业务合同不符".into());
    }
    let authorities = v["authorities"]
        .as_array()
        .filter(|a| !a.is_empty())
        .ok_or("InvalidDomain：Voice 缺固定权威列表")?;
    let mut ids = std::collections::BTreeSet::new();
    for a in authorities {
        let mut keys = vec![
            "authority_id",
            "bundle_sha256",
            "verification_sha256",
            "max_bytes",
        ];
        if !split {
            keys.extend(["bundle_path", "verification_path"]);
        }
        exact(a, &keys)?;
        if !ids.insert(required(a, "authority_id")?) {
            return Err("IdentityConflict：重复 Voice 权威".into());
        }
        for k in ["bundle_sha256", "verification_sha256"] {
            digest(required(a, k)?)?;
        }
        if !split {
            for k in ["bundle_path", "verification_path"] {
                if !Path::new(required(a, k)?).is_absolute() {
                    return Err("InvalidDomain：Voice 固定原件路径须绝对路径".into());
                }
            }
        }
        let max = positive(required(a, "max_bytes")?, "evidence max_bytes")? as u64;
        if max > LIMIT {
            return Err("InvalidDomain：Voice 证据上限超过64MiB".into());
        }
    }
    Ok(())
}
fn authority<'a>(config: &'a Config, id: &str) -> Result<&'a Value, String> {
    if !enabled(config) {
        return Err("MissingDependency：未配置定义 γ 工作例权威".into());
    }
    validate_config(&config.manifest)?;
    config.manifest["voice_binding"]["authorities"]
        .as_array()
        .unwrap()
        .iter()
        .find(|a| a["authority_id"] == id)
        .ok_or_else(|| "MissingDependency：未配置该 γ 权威".into())
}
fn read_pinned(path: &str, expected: &str, max: u64) -> Result<String, String> {
    String::from_utf8(deployment::read_pinned(path, expected, max)?)
        .map_err(|_| "InvalidDomain：证据原件非 UTF8".into())
}

/// 单次读取并保留原字节。运行时只在此处读外部文件，审计重放使用已提交 witness。
pub(super) fn load(
    config: &Config,
    evidence_id: &str,
    authority_id: &str,
) -> Result<VerifiedGammaEvidence, String> {
    if !enabled(config) {
        return Err("MissingDependency：未配置定义 γ 工作例权威".into());
    }
    let a = authority(config, authority_id)?;
    let max = positive(required(a, "max_bytes")?, "max_bytes")? as u64;
    let mapping = config
        .deployment
        .as_ref()
        .map(|d| &d["voice"][authority_id]);
    let raw = read_pinned(
        if let Some(m) = mapping {
            required(m, "bundle")?
        } else {
            required(a, "bundle_path")?
        },
        required(a, "bundle_sha256")?,
        max,
    )?;
    let bundle = strict_json(raw.as_bytes())?;
    if !bundle["bindings"]
        .as_array()
        .ok_or("SchemaUnsupported：权威 bindings 须数组")?
        .iter()
        .any(|b| b["evidence_id"] == evidence_id)
    {
        return Err("MissingDependency：固定权威不存在该 evidence_id".into());
    }
    let verification = read_pinned(
        if let Some(m) = mapping {
            required(m, "verification")?
        } else {
            required(a, "verification_path")?
        },
        required(a, "verification_sha256")?,
        max,
    )?;
    let mut witness = json!({"authority_id":a["authority_id"],"evidence_id":evidence_id,"bundle_raw_utf8":raw,"verification_raw_utf8":verification});
    // 先核受信清单/独评绑定，后读有界原件。新版保存摘要键控的原件闭包。
    let verified = verify_binding(config, &witness)?;
    let artifacts = bundle["artifacts"].as_array().unwrap();
    let mut objects = serde_json::Map::new();
    let locations = mapping
        .map(|m| {
            m["artifacts"]
                .as_array()
                .ok_or("MissingDependency：缺 Voice 部署原件列表")
        })
        .transpose()?;
    if locations.is_some_and(|list| list.len() != artifacts.len()) {
        return Err("IdentityConflict：Voice 闭包与部署映射的原件集合不同".into());
    }
    for artifact in artifacts {
        let n = positive(required(artifact, "bytes")?, "artifact bytes")? as u64;
        let sha = required(artifact, "sha256")?;
        if let Some(list) = locations {
            let name = required(artifact, "name")?;
            let location = list
                .iter()
                .find(|loc| loc["name"] == name && loc["sha256"] == sha)
                .ok_or("MissingDependency：逻辑角色和内容摘要无对应原件")?;
            if let Some(prior) = objects.get(sha) {
                let prior: &Value = prior;
                if prior
                    .as_str()
                    .is_none_or(|encoded| encoded.len() as u64 != n * 2)
                {
                    return Err("IdentityConflict：同一内容地址有不同精确长度".into());
                }
                // 仍读取此角色绑定的位置；不能以另一角色的成功掩盖缺件。
            }
            let bytes = deployment::read_pinned(required(location, "path")?, sha, n)?;
            if bytes.len() as u64 != n {
                return Err("IdentityConflict：原件精确长度与清单不同".into());
            }
            objects.insert(sha.to_owned(), json!(encode_hex(&bytes)));
        } else {
            let actual = read_pinned(required(artifact, "path")?, sha, n)?;
            if actual.len() as u64 != n {
                return Err("IdentityConflict：原件精确长度与清单不同".into());
            }
        }
    }
    if locations.is_some() {
        witness["artifacts_by_sha256"] = Value::Object(objects);
        Ok(VerifiedGammaEvidence {
            witness,
            ..verified
        })
    } else {
        Ok(verified)
    }
}

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push(HEX[(b >> 4) as usize] as char);
        s.push(HEX[(b & 15) as usize] as char);
    }
    s
}
fn decode_hex(raw: &str, bytes: u64) -> Result<Vec<u8>, String> {
    if raw.len() as u64 != bytes * 2 {
        return Err("IdentityConflict：持久原件精确长度不符".into());
    }
    let nibble = |b: u8| match b {
        b'0'..=b'9' => Ok(b - b'0'),
        b'a'..=b'f' => Ok(b - b'a' + 10),
        _ => Err("SchemaUnsupported：持久原件非小写 hex".to_owned()),
    };
    raw.as_bytes()
        .chunks_exact(2)
        .map(|pair| Ok(nibble(pair[0])? << 4 | nibble(pair[1])?))
        .collect()
}

const WITNESS: &[&str] = &[
    "authority_id",
    "evidence_id",
    "bundle_raw_utf8",
    "verification_raw_utf8",
];

pub(super) fn verify_witness(
    config: &Config,
    witness: &Value,
) -> Result<VerifiedGammaEvidence, String> {
    if bound_revision(config) != Some(V2) {
        exact(witness, WITNESS)?;
        return verify_binding(config, witness);
    }
    let mut keys = WITNESS.to_vec();
    keys.push("artifacts_by_sha256");
    exact(witness, &keys)?;
    let verified = verify_binding(config, witness)?;
    let bundle = strict_json(required(witness, "bundle_raw_utf8")?.as_bytes())?;
    let objects = witness["artifacts_by_sha256"]
        .as_object()
        .ok_or("MissingDependency：缺 Voice 原件闭包")?;
    let mut checked = std::collections::BTreeMap::new();
    for a in bundle["artifacts"].as_array().unwrap() {
        let sha = required(a, "sha256")?;
        let n = positive(required(a, "bytes")?, "artifact bytes")? as u64;
        if let Some(prior) = checked.insert(sha, n) {
            if prior != n {
                return Err("IdentityConflict：同一内容地址有不同精确长度".into());
            }
        } else {
            let raw = objects
                .get(sha)
                .and_then(Value::as_str)
                .ok_or("MissingDependency：闭包缺少独评原件")?;
            let bytes = decode_hex(raw, n)?;
            deployment::verify_bytes(&bytes, sha, n)?;
        }
    }
    if objects.len() != checked.len() {
        return Err("IdentityConflict：持久 Voice 闭包含未独评原件".into());
    }
    Ok(verified)
}

/// 跨域证明携带的是原图像；直接消费其原件闭包，不向原部署路径求证。
pub(super) fn verify_image_closure(config: &Config, image: &Value) -> Result<(), String> {
    if !deployment::is_business(&config.manifest) {
        return Ok(());
    }
    for event in image["history"]
        .as_array()
        .ok_or("SchemaUnsupported：证明图像缺历史")?
    {
        if event["kind"] == "BindVoice" {
            let v = verify_witness(config, &event["evidence_witness"])?;
            if event["record"]["evidence"] != v.reference() {
                return Err("IdentityConflict：证明中的 Voice 记录未绑定原件".into());
            }
        }
    }
    Ok(())
}

/// 旧见证中的原始路径仍参与原摘要，不重写；归档只按独评绑定的摘要定位副本。
pub(super) fn verify_legacy_archive(
    config: &Config,
    image: &Value,
    index: &Value,
) -> Result<(), String> {
    if deployment::is_business(&config.manifest) {
        if !index.is_null() {
            return Err("SchemaUnsupported：新版 Voice 不接受外部归档索引".into());
        }
        return Ok(());
    }
    if !index.is_null() {
        exact(index, &["schema_revision", "objects"])?;
        if index["schema_revision"] != "voice-archive-index/1" || !index["objects"].is_object() {
            return Err("SchemaUnsupported：未知 Voice 归档索引".into());
        }
    }
    visit_archived_voice(config, image, index, &mut std::collections::BTreeSet::new())
}

type SeenProofs = std::collections::BTreeSet<(String, String)>;
fn visit_archive_cut(
    config: &Config,
    domain: &str,
    root: &Value,
    image: &Value,
    index: &Value,
    seen: &mut SeenProofs,
) -> Result<(), String> {
    let root = root
        .as_str()
        .ok_or("MissingDependency：归档跨域证明缺提交根")?;
    if seen.insert((domain.to_owned(), root.to_owned())) {
        visit_archived_voice(&config.for_domain(domain)?, image, index, seen)?;
    }
    Ok(())
}
fn visit_archived_voice(
    config: &Config,
    image: &Value,
    index: &Value,
    seen: &mut SeenProofs,
) -> Result<(), String> {
    for event in image["history"]
        .as_array()
        .ok_or("SchemaUnsupported：离线图像缺历史")?
    {
        if event["kind"] == "BindVoice" {
            let witness = &event["evidence_witness"];
            verify_witness(config, witness)?;
            let bundle = strict_json(required(witness, "bundle_raw_utf8")?.as_bytes())?;
            for artifact in bundle["artifacts"].as_array().unwrap() {
                let sha = required(artifact, "sha256")?;
                let length = positive(required(artifact, "bytes")?, "artifact bytes")? as u64;
                let path = index["objects"][sha].as_str().ok_or_else(|| {
                    format!(
                        "MissingDependency：历史 Voice 归档缺角色 {} 摘要 {sha}",
                        artifact["name"]
                    )
                })?;
                if read_pinned(path, sha, length)?.len() as u64 != length {
                    return Err("IdentityConflict：归档原件精确长度不符".into());
                }
            }
        }
        let witness = &event["witness"];
        let prepared = witness["prepared_proofs"].as_array().into_iter().flatten();
        for proof in prepared.chain(
            [&witness["grant_proof"], &witness["commit_proof"]]
                .into_iter()
                .filter(|p| !p.is_null()),
        ) {
            let domain = required(proof, "domain_id")?;
            visit_archive_cut(
                config,
                domain,
                &proof["receipt"]["cut"]["root_hash"],
                &proof["image"],
                index,
                seen,
            )?;
            visit_archive_cut(
                config,
                domain,
                &proof["current_cut"]["root_hash"],
                &proof["current_image"],
                index,
                seen,
            )?;
        }
    }
    for record in image["recorded"]
        .as_array()
        .ok_or("SchemaUnsupported：离线图像缺原件列表")?
    {
        if let Some(proof) = record.get("e_commit_proof") {
            visit_archive_cut(
                config,
                "E",
                &record["cut"]["root_hash"],
                &proof["image"],
                index,
                seen,
            )?;
        }
        if let Some(proof) = record.get("b_source_debit_proof") {
            let domain = required(proof, "domain_id")?;
            visit_archive_cut(
                config,
                domain,
                &proof["receipt"]["cut"]["root_hash"],
                &proof["image"],
                index,
                seen,
            )?;
        }
        if let Some(proof) = record.get("e_resolution_proof") {
            visit_archive_cut(
                config,
                "E",
                &proof["receipt"]["cut"]["root_hash"],
                &proof["image"],
                index,
                seen,
            )?;
        }
    }
    Ok(())
}

/// 独评结果必须由 manifest 事先固定，且覆盖完整 bundle 与其中每一原件；绝不相信请求的布尔值。
fn verify_binding(config: &Config, witness: &Value) -> Result<VerifiedGammaEvidence, String> {
    let split = bound_revision(config) == Some(V2);
    let a = authority(config, required(witness, "authority_id")?)?;
    let raw = required(witness, "bundle_raw_utf8")?;
    let review_raw = required(witness, "verification_raw_utf8")?;
    let max = positive(required(a, "max_bytes")?, "max_bytes")? as usize;
    if raw.len() > max
        || review_raw.len() > max
        || sha256_hex(raw.as_bytes()) != a["bundle_sha256"]
        || sha256_hex(review_raw.as_bytes()) != a["verification_sha256"]
    {
        return Err("IdentityConflict：持久 γ 证据不等于固定原始字节".into());
    }
    let bundle = strict_json(raw.as_bytes())?;
    let review = strict_json(review_raw.as_bytes())?;
    exact(
        &bundle,
        &["schema", "authority_id", "source", "artifacts", "bindings"],
    )?;
    let (bundle_schema, review_schema) = if split {
        deployment::closed(
            &review,
            &[
                "schema",
                "verdict",
                "authority_id",
                "bundle_sha256",
                "artifacts",
                "verified_evidence_ids",
            ],
            &["scope"],
        )?;
        if let Some(scope) = review.get("scope") {
            if !scope.is_string() {
                return Err("SchemaUnsupported：独评 scope 须文本".into());
            }
        }
        exact(
            &bundle["source"],
            &[
                "instrument",
                "input_sha256",
                "profile_id",
                "first_confirming_observation_source",
                "clock_mapping",
            ],
        )?;
        (
            "voice-binding-authority/2",
            "voice-binding-independent-verification/2",
        )
    } else {
        (
            "voice-binding-authority/1",
            "voice-binding-independent-verification/1",
        )
    };
    if bundle["schema"] != bundle_schema
        || bundle["authority_id"] != a["authority_id"]
        || review["schema"] != review_schema
        || review["verdict"] != "APPROVE_CONTROLLED_VOICE_BINDING"
        || review["authority_id"] != a["authority_id"]
        || review["bundle_sha256"] != a["bundle_sha256"]
        || review["artifacts"] != bundle["artifacts"]
    {
        return Err("IdentityConflict：定义 γ 独立核验未绑定完整原件".into());
    }
    let artifacts = bundle["artifacts"]
        .as_array()
        .filter(|a| !a.is_empty())
        .ok_or("MissingDependency：γ 缺独立原件")?;
    let mut names = std::collections::BTreeSet::new();
    let mut total = 0u64;
    for f in artifacts {
        if split {
            exact(f, &["name", "sha256", "bytes"])?;
            logical_name(required(f, "name")?)?;
        } else {
            exact(f, &["name", "path", "sha256", "bytes"])?;
        }
        if !names.insert(required(f, "name")?) {
            return Err("IdentityConflict：γ 原件名重复".into());
        }
        digest(required(f, "sha256")?)?;
        if !split && !Path::new(required(f, "path")?).is_absolute() {
            return Err("InvalidDomain：证据原件须固定绝对路径".into());
        }
        let n = positive(required(f, "bytes")?, "artifact bytes")? as u64;
        total = total.checked_add(n).ok_or("InvalidDomain：原件总长溢出")?;
        if n > LIMIT || total > 2 * LIMIT {
            return Err("InvalidDomain：权威原件集合超过明确上限".into());
        }
    }
    for &name in REQUIRED_ROLES {
        if !names.contains(name) {
            return Err(format!("MissingDependency：γ 绑定缺原件 {name}"));
        }
    }
    let bindings = bundle["bindings"]
        .as_array()
        .filter(|a| !a.is_empty())
        .ok_or("MissingDependency：γ 权威绑定集合为空")?;
    let ids = bindings
        .iter()
        .map(|b| required(b, "evidence_id").map(str::to_owned))
        .collect::<Result<Vec<_>, _>>()?;
    let mut unique = ids.clone();
    unique.sort();
    unique.dedup();
    if unique.len() != ids.len() || review["verified_evidence_ids"] != json!(ids) {
        return Err("IdentityConflict：独评未逐一覆盖唯一绑定全集".into());
    }
    let b = bindings
        .iter()
        .find(|b| b["evidence_id"] == witness["evidence_id"])
        .ok_or("MissingDependency：权威证据 ID 缺失")?;
    exact(
        b,
        &[
            "evidence_id",
            "instrument",
            "chong_id",
            "operation_level",
            "carrier_ref",
            "gamma_ref",
            "structure_view",
            "sigma",
            "n",
            "parent_voice_id",
            "opening_source",
        ],
    )?;
    if b["carrier_ref"]["authority_id"] != a["authority_id"]
        || b["gamma_ref"]["authority_id"] != a["authority_id"]
        || b["instrument"] != bundle["source"]["instrument"]
    {
        return Err("IdentityConflict：γ/载体/标的不属于同一固定权威".into());
    }
    let input = artifacts.iter().find(|f| f["name"] == "input").unwrap();
    if bundle["source"]["input_sha256"] != input["sha256"] {
        return Err("IdentityConflict：instrument 声明未绑定实际输入".into());
    }
    exact(
        &b["opening_source"],
        &[
            "fact_key",
            "fact_hash",
            "allocation_id",
            "raw_sha256",
            "json_pointer",
            "quantity",
            "units",
        ],
    )?;
    let opening = artifacts
        .iter()
        .find(|f| f["name"] == "opening_raw")
        .unwrap();
    if b["opening_source"]["raw_sha256"] != opening["sha256"] {
        return Err("IdentityConflict：Voice 开局来源未绑定独立原件".into());
    }
    let source = &bundle["source"];
    if source["profile_id"] != b["structure_view"]["profile_id"] {
        return Err("IdentityConflict：Voice 操作/γ profile 未绑定来源".into());
    }
    let mapping = &source["clock_mapping"];
    exact(
        mapping,
        &[
            "kind",
            "source_origin",
            "nanosecond_origin",
            "nanoseconds_per_ordinal",
        ],
    )?;
    if mapping["kind"] != "TestOnlyAffineOrdinalToNs" {
        return Err("SchemaUnsupported：缺显式具名 source ordinal 到纳秒映射".into());
    }
    let source_ordinal = nonnegative(
        required(source, "first_confirming_observation_source")?,
        "γ observation ordinal",
    )?;
    let source_origin = nonnegative(required(mapping, "source_origin")?, "clock source_origin")?;
    let ns_origin = nonnegative(
        required(mapping, "nanosecond_origin")?,
        "clock nanosecond_origin",
    )?;
    let step = positive(required(mapping, "nanoseconds_per_ordinal")?, "clock step")?;
    let delta = source_ordinal
        .checked_sub(source_origin)
        .filter(|n| *n >= 0)
        .ok_or("InvalidDomain：γ 观察序号早于映射原点")?;
    let observation_ns = delta
        .checked_mul(step)
        .and_then(|n| n.checked_add(ns_origin))
        .ok_or("InvalidDomain：γ 观察时钟映射溢出")?;
    Ok(VerifiedGammaEvidence {
        binding: b.clone(),
        observation_ns,
        reference: json!({"authority_id":a["authority_id"],"bundle_sha256":a["bundle_sha256"],"verification_sha256":a["verification_sha256"]}),
        witness: witness.clone(),
    })
}

#[cfg(test)]
pub(super) fn unit_verified(binding: Value) -> VerifiedGammaEvidence {
    // 仅内部纯算子单位测试；不是生产 adapter 的认证分支，不用于正式成功证据。
    VerifiedGammaEvidence {
        binding,
        observation_ns: 0,
        reference: json!({"authority_id":"unit","bundle_sha256":hash(&json!("unit bundle")),"verification_sha256":hash(&json!("unit verifier"))}),
        witness: Value::Null,
    }
}
