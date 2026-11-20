//! #1407 C1：E 侧精确命令（INTERFACE-CONTRACTS「ExactCommand」「ConditionEvidence」；SPEC C07.1–2；
//! ADR 0052 裁定二 `model_coverage`）。只属 `tb03b-finance/5`。
//! wire 形状与 #1942 `history_simulation::runtime::{ExactCommand, Certificate, Condition, AuthorityReply}`
//! 逐字段对齐。首次量和分配身份在签封前固定；IC:13 精确整数以十进制字符串进入摘要。
use super::book::hash;
use super::voice::{digest, exact};
use crate::session_protocol::{positive, required};
use serde_json::{json, Value};
use std::collections::BTreeSet;

pub(super) const AUTHORITY_WIRE: &str = "x-exact-authority/1";
/// #1407 C3 CE-S07：冻结财务原件与 X profile 显式选择“由 E 在真实 ReleaseExact 切面动态绑定可核证 FX 依赖”的唯一标记
/// （仅搭配 `tb03b-finance/6` + `fx-valuation/2`）。纯非 FX 与既有静态 `fx-valuation/1` 合同不使用该标记；
/// 真实放行交付的 `ReleasedExact` 证书中也绝不得残留该标记。
pub(crate) const FX_RELEASE_BOUND_MARKER: &str = "fx-valuation/2:release-bound";
pub(crate) const FX_COVERAGE_PROOF_PREFIX: &str = "fx-valuation/2:";

/// 拒绝在 FX 精确命令/条件中使用历史控制占位名、全局 latest 或布尔 admissible 代替真实依赖。
pub(crate) fn is_fx_placeholder_text(s: &str) -> bool {
    s.starts_with("TestOnly-market/")
        || s == "TestOnly-market"
        || matches!(
            s,
            "controlled-dependency"
                | "controlled-invalidation"
                | "controlled-evidence"
                | "controlled-coverage"
                | "fx-valuation/1:release-bound"
        )
        || s == "latest"
        || s.contains(":latest")
        || s == "admissible"
        || s.starts_with("admissible:")
        || s.starts_with("admissible=")
}
/// 冻结财务原件里获准的条件清单项：IC「ConditionEvidence」九字段。
const CONDITION_FIELDS: [&str; 9] = [
    "condition_id",
    "authority_revision",
    "dependency_set",
    "invalidation_sources",
    "required_check_stages",
    "evidence_refs",
    "coverage_proof",
    "validator_capability",
    "failure_result",
];
const CERTIFICATE_FIELDS: [&str; 6] = [
    "rd11_policy",
    "responsibility_refs",
    "structure_dependencies",
    "market_dependencies",
    "rule_revision",
    "conditions",
];
/// ADR 0052 裁定二：E-Release 前唯一判定点的条件名。
const MODEL_COVERAGE: &str = "model_coverage";
/// 已知「核验能力 ↔ 检查阶段」配对，E 与 X 共用这一张表（#1407 C2）。阶段前缀决定由谁执行：
/// E.* 只能是 E 真会执行的能力（E-Release 核与 model_coverage 判定点），S.*、X.* 同理。
/// 表外能力、未知阶段前缀或失败结果不是 Denied，整份清单 Unsupported（SPEC C07.2，IC:51）。
pub(crate) const CONDITION_PAIRS: [(&str, &str); 4] = [
    ("released-exact/1", "E.ReleaseExact"),
    ("model-coverage/1", "E.ReleaseExact"),
    ("execute-committed/1", "S.RequestConditionalExecution"),
    ("simulation-local-transaction/1", "X.OwnAttemptAndCall"),
];
const STAGE_PREFIXES: [&str; 3] = ["E.", "S.", "X."];
/// 一项条件的语义闸：阶段前缀已知、能力与阶段是表内配对、authority_revision 即该能力、失败结果为 Denied；
/// `model_coverage` 只能是 model-coverage/1 @ E.ReleaseExact。
pub(crate) fn check_condition_semantics(
    condition_id: &str,
    authority_revision: &str,
    stages: &[&str],
    validator_capability: &str,
    failure_result: &str,
) -> Result<(), String> {
    if stages
        .iter()
        .any(|s| !STAGE_PREFIXES.iter().any(|p| s.starts_with(p)))
    {
        return Err("Unsupported：ConditionEvidence 检查阶段前缀未知".into());
    }
    let Some((_, stage)) = CONDITION_PAIRS
        .iter()
        .find(|(c, _)| *c == validator_capability)
    else {
        return Err("Unsupported：ConditionEvidence 核验能力不在已知配对表".into());
    };
    if stages != [*stage] || authority_revision != validator_capability {
        return Err("Unsupported：ConditionEvidence 能力与阶段/权威修订不是已知配对".into());
    }
    if failure_result != "Denied" {
        return Err("Unsupported：ConditionEvidence 失败语义须为 Denied".into());
    }
    if (condition_id == MODEL_COVERAGE) != (validator_capability == "model-coverage/1") {
        return Err(
            "Unsupported：model_coverage 须且只能由 model-coverage/1 在 E.ReleaseExact 判定".into(),
        );
    }
    Ok(())
}
/// 清单整体的完备闸，E 冻结原件与 X profile 共用：配对表里 E/S/X 各阶段的每项能力都必须在场且只出现一次。
/// 逐项语义闸只管「出现的项都对」；少了这一步，只含 model_coverage 的清单也能过，证书就不再声明
/// E 放行核、S 条件执行、X 占有调用这三个阶段的条件（#1407 C2，#2021 审查 opus findings[2]）。
pub(crate) fn check_required_capabilities<'a>(
    capabilities: impl IntoIterator<Item = &'a str>,
) -> Result<(), String> {
    let given: Vec<&str> = capabilities.into_iter().collect();
    for (capability, stage) in CONDITION_PAIRS {
        match given.iter().filter(|c| **c == capability).count() {
            1 => {}
            0 => {
                return Err(format!(
                    "MissingDependency：获准条件清单缺必备核验能力 {capability} @ {stage}"
                ))
            }
            _ => {
                return Err(format!(
                    "Unsupported：获准条件清单重复核验能力 {capability}"
                ))
            }
        }
    }
    Ok(())
}
const MODEL_DOMAIN_FIELDS: [&str; 3] = ["order_kind", "concurrency", "allocation_model"];

fn text_list(v: &Value, what: &str) -> Result<(), String> {
    let a = v
        .as_array()
        .filter(|a| !a.is_empty())
        .ok_or_else(|| format!("MissingDependency：{what} 须非空数组"))?;
    if a.iter().any(|x| x.as_str().is_none_or(str::is_empty)) {
        return Err(format!("MissingDependency：{what} 含空项或非文本"));
    }
    Ok(())
}
fn condition(c: &Value) -> Result<(), String> {
    exact(c, &CONDITION_FIELDS)?;
    for k in [
        "condition_id",
        "authority_revision",
        "coverage_proof",
        "validator_capability",
        "failure_result",
    ] {
        required(c, k)?;
    }
    for k in [
        "dependency_set",
        "invalidation_sources",
        "required_check_stages",
        "evidence_refs",
    ] {
        text_list(&c[k], k)?;
    }
    let stages: Vec<&str> = c["required_check_stages"]
        .as_array()
        .map_or(vec![], |a| a.iter().filter_map(Value::as_str).collect());
    check_condition_semantics(
        required(c, "condition_id")?,
        required(c, "authority_revision")?,
        &stages,
        required(c, "validator_capability")?,
        required(c, "failure_result")?,
    )
}
fn model_domain(v: &Value) -> Result<(), String> {
    let a = v
        .as_array()
        .ok_or("SchemaUnsupported：model_coverage 域须数组")?;
    for d in a {
        exact(d, &MODEL_DOMAIN_FIELDS)?;
        for k in MODEL_DOMAIN_FIELDS {
            required(d, k)?;
        }
    }
    Ok(())
}
/// `/5`、`/6` 冻结原件顶层 `exact_release`：唯一目标 X/epoch、投影、规则与市场依赖、获准条件清单、模型覆盖域。
pub(super) fn validate_section(d: &Value) -> Result<(), String> {
    let s = &d["exact_release"];
    exact(
        s,
        &[
            "x_target",
            "projection_kind",
            "rd11_policy",
            "rule_revision",
            "market_dependencies",
            "conditions",
            "model_coverage",
        ],
    )?;
    exact(&s["x_target"], &["x_id", "x_epoch"])?;
    required(&s["x_target"], "x_id")?;
    positive(required(&s["x_target"], "x_epoch")?, "x_epoch")?;
    for k in ["projection_kind", "rd11_policy", "rule_revision"] {
        required(s, k)?;
    }
    text_list(&s["market_dependencies"], "market_dependencies")?;
    let conditions = s["conditions"]
        .as_array()
        .filter(|a| !a.is_empty())
        .ok_or("MissingDependency：获准条件清单为空")?;
    let mut ids = BTreeSet::new();
    for c in conditions {
        condition(c)?;
        if !ids.insert(required(c, "condition_id")?) {
            return Err("IdentityConflict：获准条件 condition_id 重复".into());
        }
    }
    if !conditions.iter().any(|c| {
        c["condition_id"] == MODEL_COVERAGE
            && c["required_check_stages"]
                .as_array()
                .is_some_and(|a| a.iter().any(|x| x == "E.ReleaseExact"))
    }) {
        return Err("MissingDependency：获准条件清单缺 E-Release 阶段的 model_coverage".into());
    }
    check_required_capabilities(
        conditions
            .iter()
            .filter_map(|c| c["validator_capability"].as_str()),
    )?;
    let m = &s["model_coverage"];
    exact(
        m,
        &[
            "model_ref",
            "domain_id",
            "input_domain",
            "unsupported_domains",
        ],
    )?;
    // domain-event/1 的 model_ref 形状（domain_event.rs validate），终态外壳原样引用。
    exact(&m["model_ref"], &["model_id", "revision", "content_hash"])?;
    for k in ["model_id", "revision", "content_hash"] {
        required(&m["model_ref"], k)?;
    }
    required(m, "domain_id")?;
    model_domain(&m["input_domain"])?;
    model_domain(&m["unsupported_domains"])?;
    // ADR 0052:266：input_domain 必填且与 unsupported_domains 互斥。
    let supported = m["input_domain"].as_array().map_or(&[][..], Vec::as_slice);
    if supported.is_empty() {
        return Err("MissingDependency：model_coverage.input_domain 不得为空".into());
    }
    let unsupported = m["unsupported_domains"]
        .as_array()
        .map_or(&[][..], Vec::as_slice);
    if supported.iter().any(|x| unsupported.contains(x)) {
        return Err("InvalidDomain：input_domain 与 unsupported_domains 须互斥".into());
    }
    let mut commands = BTreeSet::new();
    let mut revisions = BTreeSet::new();
    let mut allocations = BTreeSet::new();
    let mut eligibilities = BTreeSet::new();
    for q in d["plans"].as_array().into_iter().flatten() {
        let x = &q["exact"];
        if !commands.insert(required(x, "command_id")?)
            || !revisions.insert((
                required(x, "logical_order_family")?,
                required(x, "revision")?,
            ))
        {
            return Err("IdentityConflict：command_id 或（逻辑族, revision）跨计划重复".into());
        }
        if !allocations.insert(required(x, "allocation_id")?)
            || !eligibilities.insert(required(x, "eligibility_ref")?)
        {
            return Err("IdentityConflict：allocation_id 或 eligibility_ref 跨计划重复".into());
        }
    }
    Ok(())
}
/// `/6` 模型绑定合同：冻结 `model_ref.content_hash` 须为规范 64 位小写十六进制 SHA-256 摘要。
pub(super) fn validate_model_binding(d: &Value) -> Result<(), String> {
    digest(required(
        &d["exact_release"]["model_coverage"]["model_ref"],
        "content_hash",
    )?)
}
/// `/5` 计划的 `exact`：逻辑族、首次量 L 与物理 revision、分配身份、方向与场所投影引用。
/// C1 只产首次提交：revision 1 且 L 等于计划量；现金买入模型只有 buy。
pub(super) fn validate_plan(q: &Value) -> Result<(), String> {
    let x = &q["exact"];
    exact(
        x,
        &[
            "command_id",
            "logical_order_family",
            "chong_id",
            "revision",
            "first_quantity",
            "allocation_id",
            "side",
            "symbol",
            "projection_manifest",
            "eligibility_ref",
            "concurrency",
        ],
    )?;
    for k in [
        "command_id",
        "logical_order_family",
        "chong_id",
        "allocation_id",
        "side",
        "symbol",
        "projection_manifest",
        "eligibility_ref",
        "concurrency",
    ] {
        required(x, k)?;
    }
    // 生命周期事件身份 `ReleaseExact:<command_id>` 与回执键 `<revision>:<op>:<hash>` 都含冒号；
    // command_id 不含冒号，与二者在 domain-event/1 的身份命名空间里不会同形。
    if required(x, "command_id")?.contains(':') {
        return Err("IdentityConflict：command_id 不得含冒号（保留给阶段身份与回执键）".into());
    }
    // domain-event/1 的 identity_key 先取 fact_key 再取 command_id，二者共用一个去重命名空间；fact_key 是
    // 64 位小写十六进制摘要，command_id 不取这个形状就不会与任何事实身份同形。
    let id = required(x, "command_id")?;
    if id.len() == 64
        && id
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(
            "IdentityConflict：command_id 不得取 64 位十六进制摘要形状（保留给 fact_key）".into(),
        );
    }
    positive(required(x, "revision")?, "revision")?;
    positive(required(x, "first_quantity")?, "first_quantity")?;
    if q["owner"].as_str().and_then(|o| o.strip_prefix("B:")) != x["chong_id"].as_str() {
        return Err("IdentityConflict：命令 chong_id 不是计划 owner".into());
    }
    if x["revision"] != "1" || x["first_quantity"] != q["quantity"] {
        return Err(
            "UnsupportedCapability：C1 只产首次提交（revision 1，首次量等于计划量）".into(),
        );
    }
    if x["side"] != "buy" {
        return Err("UnsupportedCapability：TestOnly 现金买入模型只有 buy".into());
    }
    Ok(())
}
fn condition_uses_fx_marker(c: &Value) -> bool {
    let marker_list = json!([FX_RELEASE_BOUND_MARKER]);
    c["dependency_set"] == marker_list
        && c["invalidation_sources"] == marker_list
        && c["evidence_refs"] == marker_list
        && c["coverage_proof"] == FX_RELEASE_BOUND_MARKER
}

fn value_contains_str(v: &Value, needle: &str) -> bool {
    match v {
        Value::String(s) => s == needle,
        Value::Array(a) => a.iter().any(|x| value_contains_str(x, needle)),
        Value::Object(m) => m.values().any(|x| value_contains_str(x, needle)),
        _ => false,
    }
}

pub(super) fn uses_fx_release_bound_marker(d: &Value) -> bool {
    value_contains_str(&d["exact_release"], FX_RELEASE_BOUND_MARKER)
}

/// 当 E 显式选择 `tb03b-finance/6` + `fx-valuation/2` 时，冻结 `exact_release` 必须显式声明 `fx-valuation/2:release-bound`，
/// 不得在冻结原件中携带 `TestOnly-market/*` 或 `controlled-*` 占位名。
pub(super) fn validate_fx_section(d: &Value) -> Result<(), String> {
    let s = &d["exact_release"];
    if s["market_dependencies"] != json!([FX_RELEASE_BOUND_MARKER]) {
        return Err(format!(
            "Unsupported：启用 fx-valuation/2 时 exact_release.market_dependencies 须显式声明 [{FX_RELEASE_BOUND_MARKER}]，不得使用静态占位名"
        ));
    }
    let conditions = s["conditions"]
        .as_array()
        .ok_or("MissingDependency：获准条件清单为空")?;
    for c in conditions {
        if !condition_uses_fx_marker(c) {
            return Err(format!(
                "Unsupported：启用 fx-valuation/2 时获准条件清单各项须统一声明 {FX_RELEASE_BOUND_MARKER}，不得残留 controlled-* 占位名"
            ));
        }
    }
    Ok(())
}

fn change_for(q: &Value) -> Value {
    let x = &q["exact"];
    json!({"kind":"submit","order":{
        "command_id":x["command_id"],
        "family_id":x["logical_order_family"],
        "chong_id":x["chong_id"],
        "revision":x["revision"],
        "side":x["side"],
        "quantity":q["quantity"],
        "kind":{"kind":"limit","price":q["limit_price"]},
        "eligibility_ref":x["eligibility_ref"],
        "projection_manifest":x["projection_manifest"],
    }})
}

pub(super) fn plan_hash_for(q: &Value) -> String {
    hash(&change_for(q))
}

fn format_bound_quote_dep(q: &super::fx_valuation::FxBoundQuote) -> String {
    let supersedes = q.supersedes_revision.as_deref().unwrap_or("none");
    format!(
        "fx-quote:{}@rev={};coord={};supersedes={};rate={}/{};raw_sha256={};fact_key={}",
        q.chain_id,
        q.revision,
        q.source_coord,
        supersedes,
        q.price_numerator,
        q.price_denominator,
        q.raw_sha256,
        q.fact_key
    )
}

fn build_fx_certificate(
    session_id: &str,
    session_generation: &str,
    d: &Value,
    q: &Value,
    structure_dep: &str,
    fx: &super::fx_valuation::FxReleaseBinding,
) -> Result<Value, String> {
    let s = &d["exact_release"];
    let x = &q["exact"];
    let m = &s["model_coverage"];
    let mref = &m["model_ref"];

    let e_cut_ref = format!("e-cut:E:{}:{}", fx.e_prev_seq, fx.e_prev_root);
    let policy_ref = format!(
        "cap-policy:{}@v{}:cap={}:{}:valid_through={}",
        fx.policy_id, fx.policy_version, fx.cap_amount, fx.cap_currency, fx.valid_through_ns
    );
    let boundary_ref = format!(
        "fx-boundary:{}|{}:input_sha256={}",
        fx.boundary_source_id, fx.boundary_source_epoch, fx.boundary_input_sha256
    );
    let empty_boundary_dep = format!(
        "fx-boundary-empty:{}|{}:input_sha256={}",
        fx.boundary_source_id, fx.boundary_source_epoch, fx.boundary_input_sha256
    );
    let exposure_ref = format!(
        "e-exposure:cash={};foreign={};total={};cap={};currency={}",
        fx.cash_subtotal, fx.foreign_subtotal, fx.evaluated_total, fx.cap_amount, fx.cap_currency
    );
    let model_ref_str = format!(
        "{}@{}#{}",
        required(mref, "model_id")?,
        required(mref, "revision")?,
        required(mref, "content_hash")?
    );
    let domain_id = required(m, "domain_id")?;
    let x_id = required(&s["x_target"], "x_id")?;
    let x_epoch = required(&s["x_target"], "x_epoch")?;
    let command_id = required(x, "command_id")?;
    let allocation_id = required(x, "allocation_id")?;
    let first_quantity = required(x, "first_quantity")?;
    let projection_manifest = required(x, "projection_manifest")?;
    let eligibility_ref = required(x, "eligibility_ref")?;
    let concurrency = required(x, "concurrency")?;
    let allocation_policy_id = required(&d["policy"], "allocation_policy_id")?;

    let quote_deps: Vec<String> = fx
        .active_quotes
        .iter()
        .map(format_bound_quote_dep)
        .collect();
    let market_dependencies: Vec<String> = if quote_deps.is_empty() {
        vec![empty_boundary_dep.clone()]
    } else {
        quote_deps.clone()
    };
    let quote_invs: Vec<String> = fx
        .active_quotes
        .iter()
        .map(|bq| {
            format!(
                "market-supersession:{}:after_rev={}",
                bq.chain_id, bq.revision
            )
        })
        .collect();
    let quote_covs: Vec<String> = fx
        .active_quotes
        .iter()
        .map(|bq| {
            format!(
                "e-quote-coverage:{}@rev={}:evidence_id={}:evidence_hash={}",
                bq.chain_id, bq.revision, bq.evidence_id, bq.evidence_hash
            )
        })
        .collect();
    let quote_raws: Vec<String> = fx
        .active_quotes
        .iter()
        .map(|bq| {
            format!(
                "market-raw:{}@rev={}:raw_sha256={}",
                bq.chain_id, bq.revision, bq.raw_sha256
            )
        })
        .collect();
    let retired_refs: Vec<String> = fx
        .retired_quotes
        .iter()
        .map(|rq| {
            format!(
                "fx-retired:{}@rev={}:retired_by_rev={}:evidence_id={}:evidence_hash={}",
                rq.chain_id, rq.revision, rq.retired_by_revision, rq.evidence_id, rq.evidence_hash
            )
        })
        .collect();
    let ob_deps: Vec<String> = fx
        .foreign_obligations
        .iter()
        .map(|ob| {
            format!(
                "foreign-responsibility:{}:owner={}:qty={}:{}:instrument={}:source={}|{}:input_sha256={}",
                ob.responsibility_id,
                ob.owner,
                ob.quantity,
                ob.unit,
                ob.valuation_instrument,
                ob.quote_source_namespace,
                ob.quote_source_epoch,
                ob.input_sha256
            )
        })
        .collect();
    let chain_proof_summary = if fx.active_quotes.is_empty() {
        "empty-boundary".to_owned()
    } else {
        fx.active_quotes
            .iter()
            .map(|bq| format!("{}@rev={}", bq.chain_id, bq.revision))
            .collect::<Vec<_>>()
            .join(",")
    };

    let approved = s["conditions"]
        .as_array()
        .ok_or("MissingDependency：获准条件清单为空")?;
    let mut built_conditions = Vec::with_capacity(approved.len());
    for tpl in approved {
        let cap = required(tpl, "validator_capability")?;
        let (dep_set, inv_sources, ev_refs, cov_proof) = match cap {
            "released-exact/1" => {
                let mut deps = vec![
                    format!(
                        "grant:{}:owner={}:amount={}:{}",
                        fx.grant_id, fx.grant_owner, fx.grant_amount, fx.cap_currency
                    ),
                    policy_ref.clone(),
                    boundary_ref.clone(),
                ];
                deps.extend(ob_deps.iter().cloned());
                deps.extend(market_dependencies.iter().cloned());
                let mut invs = vec![
                    format!("e-pending:E:{}:{}", fx.policy_id, fx.cap_currency),
                    format!("cap-policy-change:{}@v{}", fx.policy_id, fx.policy_version),
                    format!(
                        "fx-boundary-change:{}|{}:{}",
                        fx.boundary_source_id, fx.boundary_source_epoch, fx.boundary_input_sha256
                    ),
                ];
                invs.extend(quote_invs.iter().cloned());
                let mut evs = vec![e_cut_ref.clone(), exposure_ref.clone()];
                if quote_covs.is_empty() {
                    evs.push(format!(
                        "e-empty-fx-boundary:{}|{}:{}",
                        fx.boundary_source_id, fx.boundary_source_epoch, fx.boundary_input_sha256
                    ));
                } else {
                    evs.extend(quote_covs.iter().cloned());
                }
                evs.extend(retired_refs.iter().cloned());
                let proof = format!(
                    "{FX_COVERAGE_PROOF_PREFIX}e-release-cut=E:{}:{};cap={}@v{}:{}/{};chains={}",
                    fx.e_prev_seq,
                    fx.e_prev_root,
                    fx.policy_id,
                    fx.policy_version,
                    fx.evaluated_total,
                    fx.cap_amount,
                    chain_proof_summary
                );
                (deps, invs, evs, proof)
            }
            "execute-committed/1" => {
                let mut deps = vec![format!("structure-object:{structure_dep}")];
                deps.extend(market_dependencies.iter().cloned());
                let mut invs = vec![format!("structure-withdrawal:{structure_dep}")];
                if quote_invs.is_empty() {
                    invs.push(format!(
                        "fx-boundary-change:{}|{}:{}",
                        fx.boundary_source_id, fx.boundary_source_epoch, fx.boundary_input_sha256
                    ));
                } else {
                    invs.extend(quote_invs.iter().cloned());
                }
                let mut evs = vec![e_cut_ref.clone(), format!("structure-ref:{structure_dep}")];
                if quote_raws.is_empty() {
                    evs.push(boundary_ref.clone());
                } else {
                    evs.extend(quote_raws.iter().cloned());
                    evs.extend(quote_covs.iter().cloned());
                }
                let proof = format!(
                    "{FX_COVERAGE_PROOF_PREFIX}s-market-closure:e-cut=E:{}:{};structure={};chains={}",
                    fx.e_prev_seq, fx.e_prev_root, structure_dep, chain_proof_summary
                );
                (deps, invs, evs, proof)
            }
            "simulation-local-transaction/1" => (
                vec![
                    format!("x-target:{x_id}@epoch={x_epoch}"),
                    format!("session:{session_id}@gen={session_generation}"),
                    format!(
                        "command:{command_id}:alloc={allocation_id}:first_qty={first_quantity}"
                    ),
                    format!("model-ref:{model_ref_str}"),
                ],
                vec![
                    format!("x-epoch-change:{x_id}:after={x_epoch}"),
                    format!("command-identity:{command_id}:alloc={allocation_id}"),
                ],
                vec![
                    e_cut_ref.clone(),
                    format!("projection-manifest:{projection_manifest}"),
                    format!("eligibility-ref:{eligibility_ref}"),
                ],
                format!(
                    "{FX_COVERAGE_PROOF_PREFIX}x-local-tx:{x_id}@{x_epoch}:e-cut=E:{}:{}",
                    fx.e_prev_seq, fx.e_prev_root
                ),
            ),
            "model-coverage/1" => (
                vec![
                    format!("model-ref:{model_ref_str}"),
                    format!("domain-id:{domain_id}"),
                    format!("order-domain:limit:{concurrency}:{allocation_policy_id}"),
                ],
                vec![
                    format!("model-ref-change:{model_ref_str}"),
                    format!("domain-id-change:{domain_id}"),
                ],
                vec![e_cut_ref.clone(), format!("model-ref:{model_ref_str}")],
                format!(
                    "{FX_COVERAGE_PROOF_PREFIX}model-coverage:{domain_id}:{model_ref_str}:e-cut=E:{}:{}",
                    fx.e_prev_seq, fx.e_prev_root
                ),
            ),
            other => return Err(format!("Unsupported：FX 证书绑定遇到未知核验能力 {other}")),
        };
        built_conditions.push(json!({
            "condition_id": tpl["condition_id"],
            "authority_revision": tpl["authority_revision"],
            "dependency_set": dep_set,
            "invalidation_sources": inv_sources,
            "required_check_stages": tpl["required_check_stages"],
            "evidence_refs": ev_refs,
            "coverage_proof": cov_proof,
            "validator_capability": tpl["validator_capability"],
            "failure_result": tpl["failure_result"],
        }));
    }

    let cert = json!({
        "rd11_policy": s["rd11_policy"],
        "responsibility_refs": fx.responsibility_refs,
        "structure_dependencies": [structure_dep],
        "market_dependencies": market_dependencies,
        "rule_revision": s["rule_revision"],
        "conditions": built_conditions,
    });
    reject_fx_placeholders_in_certificate(&cert)?;
    Ok(cert)
}

pub(super) fn reject_fx_placeholders_in_certificate(cert: &Value) -> Result<(), String> {
    fn walk(v: &Value) -> Result<(), String> {
        match v {
            Value::String(s) => {
                if s == FX_RELEASE_BOUND_MARKER || is_fx_placeholder_text(s) {
                    return Err(format!(
                        "IdentityConflict：FX 精确命令证书不得含占位名/模板标记/latest/admissible（{s}）"
                    ));
                }
            }
            Value::Array(a) => {
                for item in a {
                    walk(item)?;
                }
            }
            Value::Object(m) => {
                for item in m.values() {
                    walk(item)?;
                }
            }
            _ => {}
        }
        Ok(())
    }
    walk(cert)
}

/// `fx-valuation/2` 域外命令（`model_coverage == Some(ModelOrderUnspecified)`）在进入 FX 政策门前
/// 即判定为持久 `Unsupported`（永不放行）：此处核固定计划字段与不含静态占位名，允许未实例化的模板标记
/// `FX_RELEASE_BOUND_MARKER` 或调用方按先前切面组装的非占位动态证书。
pub(super) fn check_fx_unsupported_certificate(
    given: &Value,
    template_cert: &Value,
    grant_id: &str,
) -> Result<(), String> {
    if given["rd11_policy"] != template_cert["rd11_policy"]
        || given["rule_revision"] != template_cert["rule_revision"]
        || given["structure_dependencies"] != template_cert["structure_dependencies"]
        || !given["responsibility_refs"]
            .as_array()
            .is_some_and(|a| a.iter().any(|x| x == grant_id))
    {
        return Err(
            "IdentityConflict：域外命令证书的固定政策/结构/grant 责任与冻结计划不符".into(),
        );
    }
    fn walk_no_placeholder(v: &Value) -> Result<(), String> {
        match v {
            Value::String(s) => {
                if is_fx_placeholder_text(s) {
                    return Err(format!(
                        "IdentityConflict：FX 精确命令证书不得含占位名/latest/admissible（{s}）"
                    ));
                }
            }
            Value::Array(a) => {
                for item in a {
                    walk_no_placeholder(item)?;
                }
            }
            Value::Object(m) => {
                for item in m.values() {
                    walk_no_placeholder(item)?;
                }
            }
            _ => {}
        }
        Ok(())
    }
    walk_no_placeholder(given)
}

/// 由冻结原件与 E 持有的 grant 组装 ExactCommand；同输入逐字节同输出。
/// `/6`（`bind_model_ref = true`）将冻结的 `model_coverage.model_ref` 固化进命令体并进入 `command_hash`。
/// `fx-valuation/2` 放行时传入 `fx_binding = Some(...)`，固化同切面 E cut、责任、政策与市场修订。
pub(super) fn command(
    session_id: &str,
    session_generation: &str,
    d: &Value,
    q: &Value,
    grant_id: &str,
    bind_model_ref: bool,
    fx_binding: Option<&super::fx_valuation::FxReleaseBinding>,
) -> Result<Value, String> {
    let s = &d["exact_release"];
    let x = &q["exact"];
    let change = change_for(q);
    let s_ref = &q["s_ref"];
    let structure_dep = format!(
        "{}@{}",
        required(s_ref, "object_id")?,
        required(s_ref, "object_hash")?
    );
    let certificate = match fx_binding {
        Some(fx) => build_fx_certificate(session_id, session_generation, d, q, &structure_dep, fx)?,
        None => json!({
            "rd11_policy":s["rd11_policy"],
            "responsibility_refs":[grant_id],
            "structure_dependencies":[structure_dep],
            "market_dependencies":s["market_dependencies"],
            "rule_revision":s["rule_revision"],
            "conditions":s["conditions"],
        }),
    };
    let mut cmd = json!({
        "command_id":x["command_id"],
        "logical_order_family":x["logical_order_family"],
        "first_quantity":x["first_quantity"],
        "allocation_id":x["allocation_id"],
        "session_id":session_id,
        "session_generation":session_generation,
        "x_id":s["x_target"]["x_id"],
        "x_epoch":s["x_target"]["x_epoch"],
        "symbol":x["symbol"],
        "projection_kind":s["projection_kind"],
        "plan_hash":hash(&change),
        "certificate_hash":hash(&certificate),
        "change":change,
        "certificate":certificate,
    });
    if bind_model_ref {
        cmd["model_ref"] = model_ref(d);
    }
    Ok(cmd)
}
/// 校验请求证书的固定结构、获准条件九字段与 condition_id 集合；不比对动态依赖内容。
pub(super) fn check_certificate_shape(
    given: &Value,
    approved_conditions: &[Value],
) -> Result<(), String> {
    let unsupported = |e: String| format!("Unsupported：{e}");
    exact(given, &CERTIFICATE_FIELDS).map_err(unsupported)?;
    let conditions = given["conditions"]
        .as_array()
        .ok_or_else(|| unsupported("条件清单须数组".into()))?;
    for c in conditions {
        condition(c).map_err(unsupported)?;
    }
    let ids = |a: &[Value]| -> BTreeSet<String> {
        a.iter()
            .filter_map(|c| c["condition_id"].as_str().map(str::to_owned))
            .collect()
    };
    if conditions.len() != approved_conditions.len() || ids(conditions) != ids(approved_conditions)
    {
        return Err("Unsupported：条件清单与获准 manifest 展开不逐项相等".into());
    }
    Ok(())
}
/// SPEC C07.2：请求证书逐项对照获准清单。缺条件、多条件或任一条件缺九字段之一 → Unsupported；
/// 形状完整但内容与 E 自行组装的证书不同 → IdentityConflict。
pub(super) fn check_certificate(given: &Value, expected: &Value) -> Result<(), String> {
    let approved = expected["conditions"]
        .as_array()
        .map_or(&[][..], Vec::as_slice);
    check_certificate_shape(given, approved)?;
    if given != expected {
        return Err("IdentityConflict：证书内容与 E 组装的责任/依赖/条件不同".into());
    }
    Ok(())
}
/// 本次对照的模型引用；ReleasedExact 与 Unsupported 记录都带它，domain-event/1 外壳从记录读出。
pub(super) fn model_ref(d: &Value) -> Value {
    d["exact_release"]["model_coverage"]["model_ref"].clone()
}
/// ADR 0052 裁定二：命令的订单种类、并发形态与分配模型对照 profile 的 `input_domain`；落在
/// `unsupported_domains` 或两边都不含即域外，返回需持久的 `Unsupported{ModelOrderUnspecified,…}`。
pub(super) fn model_coverage(d: &Value, q: &Value) -> Option<Value> {
    let m = &d["exact_release"]["model_coverage"];
    let key = json!({"order_kind":"limit","concurrency":q["exact"]["concurrency"],"allocation_model":d["policy"]["allocation_policy_id"]});
    let listed = |k: &str| m[k].as_array().is_some_and(|a| a.contains(&key));
    if listed("input_domain") && !listed("unsupported_domains") {
        return None;
    }
    Some(
        json!({"reason":"ModelOrderUnspecified","model_ref":m["model_ref"],"domain_id":m["domain_id"],"command_id":q["exact"]["command_id"]}),
    )
}
/// #1942 `AuthorityReply` 的十二字段，键集逐项相等（X 端 `deny_unknown_fields`）。
pub(super) fn authority_reply(
    request: &Value,
    command: &Value,
    authority_epoch: &str,
    state: &str,
    receipt_id: &str,
    commit_ns: i64,
) -> Value {
    json!({
        "protocol":AUTHORITY_WIRE,
        "session_id":request["session_id"],
        "session_generation":request["session_generation"],
        "authority_id":"E",
        "authority_epoch":authority_epoch,
        "command_id":command["command_id"],
        "command_hash":hash(command),
        "command":command,
        "state":state,
        "receipt_id":receipt_id,
        "release_receipt_id":Value::Null,
        "commit_ns":commit_ns.to_string(),
    })
}
