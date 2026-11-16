//! #1407 C1：E 侧精确命令（INTERFACE-CONTRACTS「ExactCommand」「ConditionEvidence」；SPEC C07.1–2；
//! ADR 0052 裁定二 `model_coverage`）。只属 `tb03b-finance/5`。
//! wire 形状与 #1942 `history_simulation::runtime::{ExactCommand, Certificate, Condition, AuthorityReply}`
//! 逐字段对齐：命令体内的量、价、revision、x_epoch 与回复的 commit_ns 是 JSON 整数，不是十进制字符串。
//! 首次量 L 与分配身份不在 #1942 的命令体里，留在 E 的 Release 记录（主控 #1407 切片裁定第 3 条）。
use super::book::hash;
use super::voice::exact;
use crate::session_protocol::{positive, required};
use serde_json::{json, Value};
use std::collections::BTreeSet;

pub(super) const AUTHORITY_WIRE: &str = "x-exact-authority/1";
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
/// `/5` 冻结原件顶层 `exact_release`：唯一目标 X/epoch、投影、规则与市场依赖、获准条件清单、模型覆盖域。
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
fn integer(v: &Value, k: &str) -> Result<i64, String> {
    positive(required(v, k)?, k)
}
/// 由冻结原件与 E 持有的 grant 组装 ExactCommand；同输入逐字节同输出。
pub(super) fn command(
    session_id: &str,
    session_generation: &str,
    d: &Value,
    q: &Value,
    grant_id: &str,
) -> Result<Value, String> {
    let s = &d["exact_release"];
    let x = &q["exact"];
    let change = json!({"kind":"submit","order":{
        "command_id":x["command_id"],
        "family_id":x["logical_order_family"],
        "chong_id":x["chong_id"],
        "revision":integer(x, "revision")?,
        "side":x["side"],
        "quantity":integer(q, "quantity")?,
        "kind":{"kind":"limit","price":integer(q, "limit_price")?},
        "eligibility_ref":x["eligibility_ref"],
        "projection_manifest":x["projection_manifest"],
    }});
    let s_ref = &q["s_ref"];
    let certificate = json!({
        "rd11_policy":s["rd11_policy"],
        "responsibility_refs":[grant_id],
        "structure_dependencies":[format!("{}@{}", required(s_ref, "object_id")?, required(s_ref, "object_hash")?)],
        "market_dependencies":s["market_dependencies"],
        "rule_revision":s["rule_revision"],
        "conditions":s["conditions"],
    });
    Ok(json!({
        "command_id":x["command_id"],
        "logical_order_family":x["logical_order_family"],
        "session_id":session_id,
        "session_generation":session_generation,
        "x_id":s["x_target"]["x_id"],
        "x_epoch":integer(&s["x_target"], "x_epoch")?,
        "symbol":x["symbol"],
        "projection_kind":s["projection_kind"],
        "plan_hash":hash(&change),
        "certificate_hash":hash(&certificate),
        "change":change,
        "certificate":certificate,
    }))
}
/// SPEC C07.2：请求证书逐项对照获准清单。缺条件、多条件或任一条件缺九字段之一 → Unsupported；
/// 形状完整但内容与 E 自行组装的证书不同 → IdentityConflict。
pub(super) fn check_certificate(given: &Value, expected: &Value) -> Result<(), String> {
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
    let approved = expected["conditions"]
        .as_array()
        .map_or(&[][..], Vec::as_slice);
    if conditions.len() != approved.len() || ids(conditions) != ids(approved) {
        return Err("Unsupported：条件清单与获准 manifest 展开不逐项相等".into());
    }
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
        "commit_ns":commit_ns,
    })
}
