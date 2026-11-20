//! #1425 TB-04-F 单一明确原责任域：同会话 `tb03b-finance/6` `ReleasedExact` 现金买单的模拟成交与因果费用归属。
//!
//! 边界与约束（ADR 0060 裁定一、三、六、七；#1425 F1/F2；#2084 FIN/6+X/3 合同）：
//! - E 独占原件归属与派生分配，不读 B、不信调用方自报归属、不改写 X 原件，也不消费未交付的
//!   多腿净额/卖空已实现利润/bust/责任减法合同。
//! - 仅接受显式绑定 `ExactCommand.model_ref`（含 `content_hash`）的 `tb03b-finance/6` 域；
//!   `tb03b-finance/5` 显式按 `VersionUnsupported` 拒绝，不放宽版号也不借 `/5` 承接。
//! - F1：FIN/6 域下，E 已持久的 `ReleasedExact` 命令与其在 `finance.responsibilities` 中仍保留的
//!   对应 grant 责任构成该命令成交与因果费用的原责任覆盖，无需在冻结 baseline 中预填未来 `fact_key`。
//! - F2：E 按同会话 `ReleasedExact` 命令与保留 grant 核验 `command_id`、目标重、`logical_order_family`、
//!   标的、方向、限价、命令体内固化的 `command.model_ref`（`model_id`/`revision`/`content_hash`）、
//!   量纲、因果 bar、累计成交量（≤ grant.quantity）与累计金额（≤ grant.amount）。
//!   `plan_hash`（完整 FIN plan）与 `command_plan_hash`（`command.change`）分开核存，不混用。
//! - 费用不双计也不吞费：`fill` 仅导 `acquisition_cash`（`commission = "0"`），具名因果 `fee`
//!   须待前件 `fill` 已在 E 持久分配后单独导 `fee_only` 且与 `fill.fee` 相等，同一 `fill` 不可重复挂费。
//! - 责任不提前下降：本模块不修改 `finance.responsibilities`（ADR 0060 §3，缺不可再执行/累计完整证据保原潜量）。
use super::book::{add, array, hash, integer};
use super::store::Config;
use super::voice::digest;
use crate::history_simulation::{
    intake,
    model::{Fill, Model},
    store::RAW_FORMAT,
};
use crate::session_protocol::{nonnegative, positive, required, strict_json};
use serde_json::{json, Value};

pub(super) const SOURCE_FILL: &str = "history_sim_fill";
pub(super) const SOURCE_FEE: &str = "history_sim_fee";
const REQUIRED_FINANCE_REV: &str = "tb03b-finance/6";
const REQUIRED_X_PROFILE_REV: &str = crate::history_simulation::EXACT_PROFILE_REVISION;

pub(super) fn is_history_sim(event: &Value) -> bool {
    event["event"] == intake::EVENT
}

pub(super) fn parse_x_batch<'a>(
    payload: &'a Value,
) -> Result<(&'a str, i64, &'a str, &'a str), String> {
    let xb = payload
        .get("x_batch")
        .filter(|v| v.is_object())
        .ok_or("MissingDependency：模拟外部事实 Resolve 必须指定同会话 X/3 已提交原批（x_batch），Pending 保留")?;
    super::voice::exact(xb, &["x_id", "x_epoch", "batch_id", "batch_receipt_sha256"])?;
    let x_id = required(xb, "x_id")?;
    let x_epoch = positive(required(xb, "x_epoch")?, "x_batch.x_epoch")?;
    let batch_id = required(xb, "batch_id")?;
    let batch_digest = required(xb, "batch_receipt_sha256")?;
    digest(batch_digest)?;
    Ok((x_id, x_epoch, batch_id, batch_digest))
}

fn sim_fact_command_id(fact: &Value) -> Result<(String, Value), String> {
    let raw_utf8 = required(fact, "raw_utf8")?;
    let doc = strict_json(raw_utf8.as_bytes())?;
    if doc["format"] != RAW_FORMAT {
        return Err("SchemaUnsupported：非模拟原件格式".into());
    }
    let raw = &doc["event"];
    let kind = required(raw, "kind")?;
    if kind == "bust" {
        return Err("Unsupported：模拟 bust 更正尚缺单一明确原责任域更正合同，Pending 保留".into());
    }
    if kind != "fill" && kind != "fee" {
        return Err("SchemaUnsupported：未知模拟原件种类".into());
    }
    let command_id = if kind == "fill" {
        required(&raw["fill"], "command_id")?
    } else {
        required(raw, "command_id")?
    };
    Ok((command_id.to_owned(), doc))
}

/// 实时写路径（`service.rs::resolve_evidence`）使用：在 E 事务内核对真实持久 `ReleasedExactReceipt`，
/// 并通过 `intake::verify_execution_causal_chain` 核对同会话同化身 X/3 已占用命令与具名结果批，
/// 生成供 E/B 离线重放的自持见证（map: `fact_key -> witness`）。
pub(super) fn verify_live_x_witnesses(
    e_tx: &rusqlite::Connection,
    config: &Config,
    previous: &Value,
    payload: &Value,
    order: &[String],
) -> Result<Option<Value>, String> {
    let recorded = previous["recorded"]
        .as_array()
        .ok_or("StorageUnavailable：recorded 形状")?;
    let mut sim_facts = Vec::new();
    for k in order {
        let fact = recorded
            .iter()
            .find(|f| f["fact_key"] == k.as_str())
            .ok_or("MissingDependency：Resolve 缺持久原事实")?;
        if is_history_sim(&fact["event"]) {
            sim_facts.push((k.as_str(), fact));
        }
    }
    if sim_facts.is_empty() {
        return Ok(None);
    }
    if previous.get("finance").is_none()
        || !super::finance::exact_release_selected(&config.manifest)
    {
        return Err(
            "MissingDependency：模拟外部事实缺命令归属/成本/利润分量证明，Pending 保留".into(),
        );
    }
    if config.manifest["finance"]["schema_revision"] != REQUIRED_FINANCE_REV {
        return Err(
            "VersionUnsupported：单一明确原责任域模拟成交/费用归属仅接受 tb03b-finance/6（命令体固化 model_ref），拒绝 tb03b-finance/5"
                .into(),
        );
    }
    let (x_id, x_epoch, batch_id, batch_digest) = parse_x_batch(payload)?;
    let selector = intake::XBatchSelector {
        x_id,
        x_epoch,
        batch_id,
        batch_receipt_sha256: batch_digest,
    };
    let commands = previous["finance"]["commands"]
        .as_array()
        .ok_or("StorageUnavailable：财务命令集合缺失")?;
    let mut witnesses = serde_json::Map::new();
    for (fk, fact) in sim_facts {
        let (command_id, _doc) = sim_fact_command_id(fact)?;
        let matches: Vec<&Value> = commands
            .iter()
            .filter(|c| c["command_id"] == command_id.as_str())
            .collect();
        if matches.is_empty() {
            return Err(
                "MissingDependency：模拟外部事实缺命令归属/成本/利润分量证明，Pending 保留".into(),
            );
        }
        if matches.len() != 1 {
            return Err("StorageUnavailable：E 存在重复 command_id 记录".into());
        }
        let cmd = matches[0];
        if cmd["state"] != "ReleasedExact" {
            return Err("MissingDependency：原命令未处于 ReleasedExact 终态，Pending 保留".into());
        }
        if cmd["command"]["x_id"] != x_id || cmd["command"]["x_epoch"] != x_epoch.to_string() {
            return Err("IdentityConflict：x_batch 目标执行域与 E ReleasedExact 命令不符".into());
        }
        let e_release_key = super::finance::receipt_key_for(config, "ReleaseExact", &command_id)?;
        let e_release_receipt = super::store::row(e_tx, "receipts", &e_release_key)?
            .ok_or("MissingDependency：E 缺该命令持久 ReleasedExactReceipt，Pending 保留")?;
        if e_release_receipt["kind"] != "ReleasedExactReceipt"
            || e_release_receipt["receipt_key"] != e_release_key
            || e_release_receipt["record"] != *cmd
            || e_release_receipt["cut"]["domain_id"] != "E"
        {
            return Err("StorageUnavailable：E 持久 ReleasedExactReceipt 与命令状态不符".into());
        }
        let witness = intake::verify_execution_causal_chain(
            &config.manifest,
            &selector,
            &command_id,
            &cmd["command"],
            required(cmd, "command_hash")?,
            &e_release_key,
            required(cmd, "release_commit_ns")?,
            &e_release_receipt["cut"],
            required(fact, "raw_utf8")?,
            required(fact, "raw_sha256")?,
        )?;
        witnesses.insert(fk.to_owned(), witness);
    }
    Ok(Some(Value::Object(witnesses)))
}

fn assert_no_json_numbers(v: &Value) -> Result<(), String> {
    match v {
        Value::Null | Value::Bool(_) | Value::String(_) => Ok(()),
        Value::Number(_) => Err("InvalidDomain：X 执行见证不得包含裸 JSON 数值".into()),
        Value::Array(items) => {
            for item in items {
                assert_no_json_numbers(item)?;
            }
            Ok(())
        }
        Value::Object(map) => {
            for val in map.values() {
                assert_no_json_numbers(val)?;
            }
            Ok(())
        }
    }
}

/// 纯离线校验证据中自持的 X/3 执行因果见证（不打开 x.db、不连活 E/X，供 E/B 冷恢复重放）。
pub(super) fn verify_offline_witness(
    config: &Config,
    previous: &Value,
    payload: &Value,
    fact: &Value,
    cmd: &Value,
    doc: &Value,
    witness: &Value,
) -> Result<(), String> {
    assert_no_json_numbers(witness)?;
    super::voice::exact(
        witness,
        &[
            "witness_revision",
            "x_profile_revision",
            "x_id",
            "x_epoch",
            "session_id",
            "session_generation",
            "source_namespace",
            "source_epoch",
            "model_content_hash",
            "command_id",
            "command_hash",
            "e_release_receipt_key",
            "e_release_cut",
            "e_release_commit_ns",
            "x_release_evidence",
            "x_accept_clock",
            "x_command_state",
            "x_execute_evidence",
            "attempt_batch_id",
            "attempt_batch_bar_index",
            "attempt_batch_request_sha256",
            "attempt_batch_receipt_sha256",
            "originals_batch_id",
            "originals_batch_bar_index",
            "originals_batch_receipt_sha256",
            "fact_raw_sha256",
        ],
    )?;
    let (x_id, x_epoch, batch_id, batch_digest) = parse_x_batch(payload)?;
    if witness["witness_revision"] != intake::X_EXECUTION_WITNESS_REVISION
        || witness["x_profile_revision"] != REQUIRED_X_PROFILE_REV
    {
        return Err("VersionUnsupported：X 执行见证版本非 X/3".into());
    }
    if witness["session_id"] != config.session
        || witness["session_generation"] != config.generation
        || witness["x_id"] != x_id
        || witness["x_epoch"] != x_epoch.to_string()
        || witness["x_id"] != cmd["command"]["x_id"]
        || witness["x_epoch"] != cmd["command"]["x_epoch"]
    {
        return Err("IdentityConflict：X 执行见证会话、化身或目标 X 身份不符".into());
    }
    if let Some(binding) = config
        .manifest
        .get("history_simulation_source")
        .filter(|v| v.is_object())
    {
        if witness["source_namespace"] != binding["source_namespace"]
            || witness["source_epoch"] != binding["source_epoch"]
            || witness["model_content_hash"] != binding["model_content_hash"]
        {
            return Err("IdentityConflict：X 执行见证来源或模型摘要与冻结配置不符".into());
        }
    }
    if witness["source_namespace"] != fact["event"]["source"]["source_namespace"]
        || witness["source_epoch"] != fact["event"]["source"]["source_epoch"]
        || witness["model_content_hash"] != doc["model_content_hash"]
        || witness["fact_raw_sha256"] != fact["raw_sha256"]
    {
        return Err("IdentityConflict：X 执行见证与事实来源、模型或原件摘要不符".into());
    }
    let command_id = required(cmd, "command_id")?;
    let command_hash = required(cmd, "command_hash")?;
    let expected_release_key = super::finance::receipt_key_for(config, "ReleaseExact", command_id)?;
    let release_commit_ns = required(cmd, "release_commit_ns")?;
    let release_bar = nonnegative(release_commit_ns, "release_commit_ns")?;
    if witness["command_id"] != command_id
        || witness["command_hash"] != command_hash
        || witness["e_release_receipt_key"] != expected_release_key
        || witness["e_release_commit_ns"] != release_commit_ns
    {
        return Err("IdentityConflict：X 执行见证未绑定本笔 E 原放行命令与回执键".into());
    }
    let e_cut = &witness["e_release_cut"];
    super::voice::exact(e_cut, &["domain_id", "commit_seq", "root_hash"])?;
    if e_cut["domain_id"] != "E" {
        return Err("IdentityConflict：e_release_cut 域非 E".into());
    }
    digest(required(e_cut, "root_hash")?)?;
    let e_cut_seq = nonnegative(required(e_cut, "commit_seq")?, "e_release_cut.commit_seq")?;
    // 离线核 E 历史中确有同序号、同提交时刻、同命令的 ReleaseExact 事件。
    let rel_event = previous["history"]
        .as_array()
        .ok_or("StorageUnavailable：E history 缺失")?
        .iter()
        .find(|ev| {
            ev["kind"] == "ReleaseExact"
                && ev["record"]["command_id"] == command_id
                && ev["commit_seq"] == e_cut_seq.to_string()
                && ev["commit_ns"] == release_commit_ns
        })
        .ok_or("IdentityConflict：E 历史中无与见证 e_release_cut 匹配的 ReleaseExact 提交")?;
    if rel_event["record"] != *cmd {
        return Err("IdentityConflict：E 历史 ReleaseExact 记录与当前命令不符".into());
    }
    // 核 X release_evidence（x-exact-authority/1，本条 release_receipt_id 恒为 null）。
    let x_rel = &witness["x_release_evidence"];
    if x_rel["protocol"] != "x-exact-authority/1"
        || x_rel["session_id"] != config.session
        || x_rel["session_generation"] != config.generation
        || x_rel["authority_id"] != "E"
        || x_rel["command_id"] != command_id
        || x_rel["command_hash"] != command_hash
        || x_rel["command"] != cmd["command"]
        || x_rel["state"] != "ReleasedExact"
        || x_rel["receipt_id"] != expected_release_key
        || !x_rel["release_receipt_id"].is_null()
        || x_rel["commit_ns"] != release_commit_ns
    {
        return Err("IdentityConflict：离线 X release_evidence 与 E 原放行回执不符".into());
    }
    // 核 X accept_clock 因果序。
    let clock = &witness["x_accept_clock"];
    let recv_ns = nonnegative(
        required(clock, "received_ns")?,
        "x_accept_clock.received_ns",
    )?;
    let first_ns = nonnegative(
        required(clock, "first_known_ns")?,
        "x_accept_clock.first_known_ns",
    )?;
    let commit_ns = nonnegative(required(clock, "commit_ns")?, "x_accept_clock.commit_ns")?;
    if recv_ns > first_ns || first_ns > commit_ns || first_ns < release_bar {
        return Err("InvalidDomain：X 接纳时钟早于 E 放行或内部倒退".into());
    }
    if witness["x_command_state"] != "Observed" {
        return Err("MissingDependency：X 命令见证非 Observed 占有终态".into());
    }
    // 核占有批与结果批（允许 b2 占有、b3 产原件，不强制两批 ID 相等）。
    required(witness, "attempt_batch_id")?;
    let attempt_bar = nonnegative(
        required(witness, "attempt_batch_bar_index")?,
        "attempt_batch_bar_index",
    )?;
    digest(required(witness, "attempt_batch_request_sha256")?)?;
    digest(required(witness, "attempt_batch_receipt_sha256")?)?;
    if witness["originals_batch_id"] != batch_id
        || witness["originals_batch_receipt_sha256"] != batch_digest
    {
        return Err("IdentityConflict：X 执行见证结果批与 Resolve 请求 x_batch 不符".into());
    }
    let originals_bar = nonnegative(
        required(witness, "originals_batch_bar_index")?,
        "originals_batch_bar_index",
    )?;
    let doc_bar = doc["bar"]["index"]
        .as_i64()
        .filter(|&v| v >= 0)
        .ok_or("InvalidDomain：模拟原件 bar.index 非法")?;
    if originals_bar != doc_bar || attempt_bar < release_bar || originals_bar < attempt_bar {
        return Err("IdentityConflict：X 占有批、结果批与原件 bar 因果序不成立".into());
    }
    // 核 S 执行证明 execute_evidence。
    let x_exec = &witness["x_execute_evidence"];
    let s_reply = &x_exec["reply"];
    let claimed_ns = nonnegative(
        required(x_exec, "claimed_ns")?,
        "x_execute_evidence.claimed_ns",
    )?;
    let s_commit_ns = nonnegative(
        required(s_reply, "commit_ns")?,
        "x_execute_evidence.reply.commit_ns",
    )?;
    let eligibility = required(&cmd["command"]["change"]["order"], "eligibility_ref")?;
    if s_reply["protocol"] != "x-exact-authority/1"
        || s_reply["session_id"] != config.session
        || s_reply["session_generation"] != config.generation
        || s_reply["command_id"] != command_id
        || s_reply["command_hash"] != command_hash
        || s_reply["command"] != cmd["command"]
        || s_reply["state"] != "ExecuteCommitted"
        || s_reply["release_receipt_id"] != expected_release_key
        || s_reply["receipt_id"] != eligibility
        || claimed_ns != attempt_bar
        || claimed_ns < s_commit_ns
    {
        return Err("IdentityConflict：离线 X execute_evidence 未绑定 S 执行或占有批时刻".into());
    }
    Ok(())
}

fn derived_units(model: &Model) -> Value {
    json!({
        "quantity": {"unit": model.quantity_unit, "quantum": "1"},
        "money": {"unit": model.currency, "currency": model.currency, "quantum": "1"},
        "numeric_encoding": "exact_decimal_integer_text"
    })
}

/// Resolve 前置检查：非精确放行域沿用 #2078 原拒绝文案；`tb03b-finance/5` 不绑定命令内模型摘要，显式拒于 `VersionUnsupported`。
pub(super) fn check_pending(
    config: &Config,
    previous: &Value,
    covered: &[Value],
    fact: &Value,
    frontier: &Value,
    cursor: i64,
) -> Result<(), String> {
    if previous.get("finance").is_none()
        || !super::finance::exact_release_selected(&config.manifest)
    {
        return Err(
            "MissingDependency：模拟外部事实缺命令归属/成本/利润分量证明，Pending 保留".into(),
        );
    }
    if config.manifest["finance"]["schema_revision"] != REQUIRED_FINANCE_REV {
        return Err(
            "VersionUnsupported：单一明确原责任域模拟成交/费用归属仅接受 tb03b-finance/6（命令体固化 model_ref），拒绝 tb03b-finance/5"
                .into(),
        );
    }
    let key = required(fact, "fact_key")?;
    if previous
        .get("fill_allocations")
        .map(|v| v.as_array().ok_or("StorageUnavailable：分配记录形状"))
        .transpose()?
        .is_some_and(|rows| rows.iter().any(|r| r["fact_key"] == key))
    {
        return Err("IdentityConflict：模拟外部事实已经持久分配".into());
    }
    let pending = previous["pending"]
        .as_array()
        .ok_or("StorageUnavailable：pending 形状")?
        .iter()
        .find(|p| p["fact_key"] == key)
        .ok_or("MissingDependency：证据覆盖的模拟外部事实无现存 Pending")?;
    if pending["scope"] == "account:*" {
        return Err("MissingDependency：账户范围 Pending 尚缺归属与影响范围证明".into());
    }
    let entry = covered
        .iter()
        .find(|c| c["fact_key"] == pending["fact_key"] && c["token"] == pending["token"])
        .ok_or("MissingDependency：相关 Pending 未被证据覆盖")?;
    if entry["fact_hash"] != fact["fact_hash"] {
        return Err("IdentityConflict：证据覆盖的模拟事实内容不同".into());
    }
    let source = &fact["event"]["source"];
    if frontier["source_namespace"] != source["source_namespace"]
        || frontier["source_epoch"] != source["source_epoch"]
        || cursor < nonnegative(required(source, "source_cursor")?, "source_cursor")?
    {
        return Err("MissingDependency：证据来源前沿未到达该事实".into());
    }
    Ok(())
}

/// 纯函数：从 E 自身持久图像中的 `tb03b-finance/6` `ReleasedExact` 命令、保留 grant 责任与
/// 自持 X/3 执行因果见证推导单一明确原责任域的逐重分配。
/// 不碰 SQLite/磁盘，供 E 审计与 `tb03c_allocation::verify_resolution` 在 B 冷恢复时离线重放。
pub(super) fn resolve(
    config: &Config,
    next: &mut Value,
    fact: &Value,
    evidence_id: &str,
    payload: &Value,
    witness: Option<&Value>,
) -> Result<(), String> {
    let raw_utf8 = required(fact, "raw_utf8")?;
    let doc = strict_json(raw_utf8.as_bytes())?;
    if doc["format"] != RAW_FORMAT {
        return Err("SchemaUnsupported：非模拟原件格式".into());
    }
    let model: Model = serde_json::from_value(doc["model"].clone())
        .map_err(|e| format!("MissingDependency：模拟模型不可解析：{e}"))?;
    model.validate()?;
    if doc["model_content_hash"] != hash(&doc["model"]) {
        return Err("IdentityConflict：模拟原件模型摘要不符".into());
    }
    if let Some(binding) = config
        .manifest
        .get("history_simulation_source")
        .filter(|v| v.is_object())
    {
        if binding["model_content_hash"] != doc["model_content_hash"] {
            return Err("IdentityConflict：模拟原件模型与冻结来源模型不符".into());
        }
    }
    if model.projection_kind != "per_leg" || model.rd12_policy != super::tb03c_per_leg::POLICY {
        return Err("Unsupported：单一明确原责任域仅支持 per_leg 逐腿归属模型".into());
    }
    let bar_index = doc["bar"]["index"]
        .as_i64()
        .filter(|&v| v >= 0)
        .ok_or("InvalidDomain：模拟原件 bar.index 非法")?;
    let raw = &doc["event"];
    let kind = required(raw, "kind")?;
    if kind == "bust" {
        return Err("Unsupported：模拟 bust 更正尚缺单一明确原责任域更正合同，Pending 保留".into());
    }
    if kind != "fill" && kind != "fee" {
        return Err("SchemaUnsupported：未知模拟原件种类".into());
    }
    let command_id = if kind == "fill" {
        required(&raw["fill"], "command_id")?
    } else {
        required(raw, "command_id")?
    };

    let finance = next
        .get("finance")
        .filter(|v| v.is_object())
        .ok_or("MissingDependency：模拟外部事实缺命令归属/成本/利润分量证明，Pending 保留")?;
    if finance["schema_revision"] != REQUIRED_FINANCE_REV {
        return Err(
            "VersionUnsupported：单一明确原责任域模拟成交/费用归属仅接受 tb03b-finance/6（命令体固化 model_ref），拒绝旧版财务域"
                .into(),
        );
    }
    let commands = finance["commands"]
        .as_array()
        .ok_or("StorageUnavailable：财务命令集合缺失")?;
    let matches: Vec<&Value> = commands
        .iter()
        .filter(|c| c["command_id"] == command_id)
        .collect();
    if matches.is_empty() {
        return Err(
            "MissingDependency：模拟外部事实缺命令归属/成本/利润分量证明，Pending 保留".into(),
        );
    }
    if matches.len() != 1 {
        return Err("StorageUnavailable：E 存在重复 command_id 记录".into());
    }
    let cmd = matches[0].clone();
    if cmd["state"] != "ReleasedExact" {
        return Err("MissingDependency：原命令未处于 ReleasedExact 终态，Pending 保留".into());
    }

    let grant_id = required(&cmd, "responsibility_ref")?.to_owned();
    if required(&cmd, "grant_id")? != grant_id {
        return Err("StorageUnavailable：命令 responsibility_ref 与 grant_id 不符".into());
    }
    let owner = required(&cmd, "owner")?.to_owned();
    let cmd_chong = owner
        .strip_prefix("B:")
        .ok_or("StorageUnavailable：命令归属域非 B 重")?
        .to_owned();
    let exact_cmd = &cmd["command"];
    if exact_cmd["command_id"] != command_id
        || exact_cmd["session_id"] != config.session
        || exact_cmd["session_generation"] != config.generation
    {
        return Err("IdentityConflict：E 原命令会话或身份不符".into());
    }
    if exact_cmd["projection_kind"] != "per_leg" {
        return Err("Unsupported：单一明确原责任域仅支持 per_leg 精确命令".into());
    }
    if exact_cmd["change"]["kind"] != "submit" {
        return Err("Unsupported：单一明确原责任域当前仅支持 submit 命令归属".into());
    }
    let order = &exact_cmd["change"]["order"];
    if order["chong_id"] != cmd_chong
        || order["command_id"] != command_id
        || order["family_id"] != exact_cmd["logical_order_family"]
    {
        return Err("StorageUnavailable：命令订单身份与归属重不自洽".into());
    }
    if order["side"] != "buy" {
        return Err("Unsupported：单一明确原责任域当前仅支持多头现金买单归属".into());
    }
    if order["kind"]["kind"] != "limit" {
        return Err("Unsupported：单一明确原责任域当前仅支持限价现金买单".into());
    }
    let limit_price = positive(required(&order["kind"], "price")?, "limit_price")?;
    let cmd_qty = positive(required(order, "quantity")?, "command.quantity")?;
    if cmd_qty != positive(required(&cmd, "first_quantity")?, "first_quantity")? {
        return Err("StorageUnavailable：命令 first_quantity 与订单数量不符".into());
    }
    let cmd_symbol = required(exact_cmd, "symbol")?.to_owned();
    let cmd_family = required(order, "family_id")?.to_owned();
    let cmd_revision = required(order, "revision")?.to_owned();
    let cmd_proj_manifest = required(order, "projection_manifest")?.to_owned();
    let release_bar = nonnegative(required(&cmd, "release_commit_ns")?, "release_commit_ns")?;
    if bar_index < release_bar {
        return Err("InvalidDomain：模拟成交/费用 bar 早于 E ReleaseExact 提交时刻".into());
    }
    // #2084 FIN/6：强制核对命令体内固化的 ExactCommand.model_ref（带 64 位 SHA-256 content_hash）
    let cmd_model_ref = &exact_cmd["model_ref"];
    if !cmd_model_ref.is_object() || cmd_model_ref != &cmd["model_ref"] {
        return Err("IdentityConflict：E ReleasedExact 命令体缺少或不一致的 model_ref".into());
    }
    digest(required(cmd_model_ref, "content_hash")?)?;
    if cmd_model_ref["model_id"] != model.model_id
        || cmd_model_ref["revision"] != model.revision
        || cmd_model_ref["content_hash"] != doc["model_content_hash"]
    {
        return Err("IdentityConflict：模拟原件模型与 E FIN/6 授权命令体 model_ref 不符".into());
    }
    if model.symbol != cmd_symbol || config.route(&cmd_chong)?["symbol"] != cmd_symbol {
        return Err("IdentityConflict：模拟原件标的与原命令或目标重路由不符".into());
    }

    // F1：核 E 当前仍保留对应 grant 责任（非从 baseline.covered_facts 预列）
    let responsibilities = finance["responsibilities"]
        .as_array()
        .ok_or("StorageUnavailable：完整责任集合缺失")?;
    let resp = responsibilities
        .iter()
        .find(|r| r["responsibility_id"] == grant_id)
        .ok_or("MissingDependency：E 未保留该命令对应 grant 完整责任，Pending 保留")?;
    let grant = &resp["grant"];
    if resp["owner"] != owner
        || !grant.is_object()
        || grant["grant_id"] != grant_id
        || grant["decision_id"] != cmd["decision_id"]
        || grant["owner"] != owner
        || grant["plan_hash"] != cmd["plan_hash"]
        || grant["quantity"] != cmd["first_quantity"]
        || resp["amount"] != grant["amount"]
    {
        return Err("IdentityConflict：E 保留责任与原命令 grant 不符".into());
    }
    if grant["policy"]["model"] != "TestOnlyUnleveragedCashBuy" {
        return Err("Unsupported：单一明确原责任域仅支持无杠杆现金买单责任模型".into());
    }
    let grant_amount = positive(required(grant, "amount")?, "grant.amount")?;
    if derived_units(&model) != grant["units"] {
        return Err("InvalidDomain：模拟原件量纲与原 grant 量纲不符".into());
    }
    let witness =
        witness.ok_or("MissingDependency：模拟外部事实缺 X/3 执行因果见证，Pending 保留")?;
    verify_offline_witness(config, next, payload, fact, &cmd, &doc, witness)?;

    // 汇总同 (command_id, grant_id) 已持久分配的累计数量与累计成本金额
    let mut cum_qty = 0i64;
    let mut cum_cost = 0i64;
    if let Some(rows) = next.get("fill_allocations").and_then(Value::as_array) {
        for row in rows {
            if row["command_id"] != command_id || row["grant_id"] != grant_id {
                continue;
            }
            for a in array(row, "allocations")? {
                match a["source_kind"].as_str() {
                    Some(SOURCE_FILL) => {
                        cum_qty = add(cum_qty, integer(a, "units")?)?;
                        cum_cost = add(cum_cost, integer(a, "acquisition_cash")?)?;
                    }
                    Some(SOURCE_FEE) => {
                        cum_cost = add(cum_cost, integer(a, "fee_only")?)?;
                    }
                    _ => {}
                }
            }
        }
    }

    let row = if kind == "fill" {
        let fill: Fill = serde_json::from_value(raw["fill"].clone())
            .map_err(|e| format!("InvalidDomain：模拟 fill 不可解析：{e}"))?;
        if fill.command_id != command_id
            || fill.chong_id != cmd_chong
            || fill.family_id != cmd_family
            || fill.revision.to_string() != cmd_revision
            || fill.projection_manifest != cmd_proj_manifest
        {
            return Err("IdentityConflict：模拟 fill 归属身份与原 ReleasedExact 命令不符".into());
        }
        if !matches!(fill.side, crate::history_simulation::model::Side::Buy) {
            return Err("IdentityConflict：模拟 fill 方向与原买单命令不符".into());
        }
        if fill.price > limit_price {
            return Err("IdentityConflict：买单成交价超出原命令限价".into());
        }
        if add(cum_qty, fill.quantity)? > cmd_qty {
            return Err("IdentityConflict：模拟成交累计数量超出原 grant 授权数量".into());
        }
        if add(cum_cost, fill.amount)? > grant_amount {
            return Err("IdentityConflict：模拟成交累计金额超出原 grant 责任额度".into());
        }
        let alloc_id = format!(
            "sim-command:{}",
            hash(&json!([fact["fact_key"], grant_id, command_id, cmd_chong]))
        );
        let allocation = json!({
            "allocation_id": alloc_id,
            "source_kind": SOURCE_FILL,
            "chong_id": cmd_chong,
            "command_id": command_id,
            "grant_id": grant_id,
            "responsibility_ref": grant_id,
            "family_id": cmd_family,
            "revision": cmd_revision,
            "symbol": cmd_symbol,
            "units": fill.quantity.to_string(),
            "acquisition_cash": fill.amount.to_string(),
            "commission": "0",
            "fee_deferred_to_cause_fact": true,
            "reported_fill_fee": fill.fee.to_string(),
            "income_changes": {"Pi": "0", "A": "0", "W": "0"},
            "fill_allocation_policy_id": super::tb03c_per_leg::POLICY,
            "policy_revision": model.revision,
        });
        json!({
            "fact_key": fact["fact_key"],
            "fact_hash": fact["fact_hash"],
            "projection_kind": "per_leg",
            "source_kind": SOURCE_FILL,
            "command_id": command_id,
            "grant_id": grant_id,
            "responsibility_ref": grant_id,
            "plan_hash": cmd["plan_hash"],
            "command_plan_hash": exact_cmd["plan_hash"],
            "command_hash": cmd["command_hash"],
            "symbol": cmd_symbol,
            "fill_allocation_policy_id": super::tb03c_per_leg::POLICY,
            "policy_revision": model.revision,
            "evidence_id": evidence_id,
            "x_execution_witness": witness,
            "allocations": [allocation],
        })
    } else {
        // kind == "fee"
        if raw["cause"]["kind"] != "fill" {
            return Err("InvalidDomain：模拟费用须绑定原 fill".into());
        }
        let fee_amount = raw["amount"]
            .as_i64()
            .filter(|&v| v >= 0)
            .ok_or("InvalidDomain：模拟费用金额非法")?;
        let fee_profile = required(raw, "fee_profile")?;
        if fee_profile != model.fee_profile.reference {
            return Err("IdentityConflict：模拟费用合同与模型不符".into());
        }
        if required(raw, "chong_id")? != cmd_chong
            || required(raw, "family_id")? != cmd_family
            || required(raw, "projection_manifest")? != cmd_proj_manifest
        {
            return Err("IdentityConflict：模拟费用归属身份与原 ReleasedExact 命令不符".into());
        }
        let dep_key = super::tb03c_e::dependency_key(&fact["event"])?
            .ok_or("MissingDependency：模拟费用缺前件 fill 依赖")?;
        let pred_fact = array(next, "recorded")?
            .iter()
            .find(|f| f["fact_key"] == dep_key)
            .ok_or("AwaitingDependency：模拟费用前件 fill 尚未 Recorded")?
            .clone();
        let prior_rows = next
            .get("fill_allocations")
            .and_then(Value::as_array)
            .ok_or("AwaitingDependency：模拟费用前件 fill 尚未在 E 持久分配")?;
        let pred_row = prior_rows
            .iter()
            .find(|r| r["fact_key"] == dep_key && r["source_kind"] == SOURCE_FILL)
            .ok_or("AwaitingDependency：模拟费用前件 fill 尚未在 E 持久分配")?
            .clone();
        if pred_row["command_id"] != command_id || pred_row["grant_id"] != grant_id {
            return Err("IdentityConflict：模拟费用前件 fill 属于其他命令或责任".into());
        }
        if prior_rows
            .iter()
            .any(|r| r["source_kind"] == SOURCE_FEE && r["original_fact_key"] == dep_key)
        {
            return Err("IdentityConflict：该模拟 fill 已有持久费用分配，不得重复计费".into());
        }
        let pred_alloc = array(&pred_row, "allocations")?
            .first()
            .ok_or("StorageUnavailable：前件 fill 缺逐重分配")?;
        let pred_doc = strict_json(required(&pred_fact, "raw_utf8")?.as_bytes())?;
        if pred_doc["model_content_hash"] != doc["model_content_hash"] {
            return Err("IdentityConflict：模拟费用与前件 fill 模型摘要不同".into());
        }
        let pred_fee = pred_doc["event"]["fill"]["fee"]
            .as_i64()
            .ok_or("StorageUnavailable：前件 fill 缺费用字段")?;
        if fee_amount != pred_fee || pred_alloc["reported_fill_fee"] != fee_amount.to_string() {
            return Err("IdentityConflict：模拟费用额与前件 fill 记录的费用不符".into());
        }
        if add(cum_cost, fee_amount)? > grant_amount {
            return Err("IdentityConflict：模拟成交与费用累计金额超出原 grant 责任额度".into());
        }
        let orig_alloc_id = required(pred_alloc, "allocation_id")?.to_owned();
        let alloc_id = format!(
            "sim-command-fee:{}",
            hash(&json!([
                fact["fact_key"],
                dep_key,
                grant_id,
                command_id,
                cmd_chong
            ]))
        );
        let allocation = json!({
            "allocation_id": alloc_id,
            "source_kind": SOURCE_FEE,
            "chong_id": cmd_chong,
            "command_id": command_id,
            "grant_id": grant_id,
            "responsibility_ref": grant_id,
            "family_id": cmd_family,
            "revision": cmd_revision,
            "symbol": cmd_symbol,
            "units": "0",
            "fee_only": fee_amount.to_string(),
            "fee_type": fee_profile,
            "cause": "fill",
            "original_fact_key": dep_key,
            "original_allocation_id": orig_alloc_id,
            "income_changes": {"Pi": "0", "A": "0", "W": "0"},
            "fill_allocation_policy_id": super::tb03c_per_leg::POLICY,
            "policy_revision": model.revision,
        });
        json!({
            "fact_key": fact["fact_key"],
            "fact_hash": fact["fact_hash"],
            "projection_kind": "per_leg",
            "source_kind": SOURCE_FEE,
            "command_id": command_id,
            "grant_id": grant_id,
            "responsibility_ref": grant_id,
            "original_fact_key": dep_key,
            "original_allocation_id": orig_alloc_id,
            "symbol": cmd_symbol,
            "fill_allocation_policy_id": super::tb03c_per_leg::POLICY,
            "policy_revision": model.revision,
            "evidence_id": evidence_id,
            "x_execution_witness": witness,
            "allocations": [allocation],
        })
    };

    if next.get("fill_allocations").is_none() {
        next["fill_allocations"] = json!([]);
    }
    next["fill_allocations"].as_array_mut().unwrap().push(row);
    Ok(())
}
