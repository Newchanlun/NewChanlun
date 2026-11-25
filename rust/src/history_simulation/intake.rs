use super::{
    model::{Fill, Model},
    store::RAW_FORMAT,
};
use crate::session_protocol::{canonical_json, nonnegative, required, sha256_hex, strict_json};
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::path::Path;

pub(crate) const EVENT: &str = "history-sim-unresolved/1";
pub(crate) const X_EXECUTION_WITNESS_REVISION: &str = "x-sim-execution-witness/1";
fn digest(v: &Value) -> String {
    sha256_hex(canonical_json(v).as_bytes())
}
fn failure(e: impl std::fmt::Display) -> String {
    format!("MissingDependency：X 原件不可核：{e}")
}

/// 只规范事实身份和路由。金额分量仍待 E 的命令/成本证据，不生成 Pi/A/W。
pub(crate) fn decode(doc: &Value, pointer: &str) -> Result<(Value, Value), String> {
    if pointer != "/event" || doc["format"] != RAW_FORMAT {
        return Err("SchemaUnsupported：模拟原件须定位 /event".into());
    }
    let model: Model = serde_json::from_value(doc["model"].clone()).map_err(failure)?;
    model.validate()?;
    if doc["model_content_hash"] != digest(&doc["model"]) || doc["intra_batch_order"] != "Unknown" {
        return Err("IdentityConflict：模拟模型摘要或批顺序声明错误".into());
    }
    required(doc, "known_frontier_cut")?;
    let raw = &doc["event"];
    let source = &raw["source"];
    for key in [
        "source_namespace",
        "source_epoch",
        "external_fact_id",
        "source_cursor",
        "received_time",
        "source_event_time",
        "claimed_origin",
    ] {
        required(source, key)?;
    }
    nonnegative(required(source, "source_cursor")?, "source_cursor")?;
    let (chong, family, command) = match required(raw, "kind")? {
        "fill" => {
            let fill: Fill = serde_json::from_value(raw["fill"].clone()).map_err(failure)?;
            if fill.quantity <= 0
                || fill.price <= 0
                || fill.fee < 0
                || fill.amount
                    != fill
                        .quantity
                        .checked_mul(fill.price)
                        .and_then(|x| x.checked_mul(model.tick_value))
                        .ok_or("InvalidDomain：成交金额溢出")?
                || source["external_fact_id"] != fill.exec_id
            {
                return Err("IdentityConflict：模拟 fill 数量/价格/金额/身份不符".into());
            }
            (fill.chong_id, fill.family_id, fill.command_id)
        }
        "fee" | "bust" => {
            if raw["cause"]["kind"] != "fill" {
                return Err("InvalidDomain：模拟更正/费用须绑定原 fill".into());
            }
            required(&raw["cause"], "exec_id")?;
            if raw["kind"] == "fee" {
                if raw["amount"].as_i64().is_none_or(|x| x < 0)
                    || raw["fee_profile"] != model.fee_profile.reference
                {
                    return Err("InvalidDomain：费用额或费用合同不符".into());
                }
            } else if raw["quantity"].as_i64().is_none_or(|x| x <= 0)
                || doc["capacity"]["kind"] != "scenario"
                || doc["capacity"]["reference"] != raw["scenario_ref"]
            {
                return Err("InvalidDomain：bust 数量或场景合同不符".into());
            }
            (
                required(raw, "chong_id")?.into(),
                required(raw, "family_id")?.into(),
                required(raw, "command_id")?.into(),
            )
        }
        _ => return Err("SchemaUnsupported：未知模拟原件种类".into()),
    };
    if chong.is_empty() || family.is_empty() || command.is_empty() {
        return Err("InvalidDomain：模拟原件归属缺失".into());
    }
    let mut normalized = json!({"event":EVENT,"allocation_id":source["external_fact_id"],"source":source,"chong_id":chong,"family_id":family,"command_id":command,"simulation_original":raw});
    if raw["kind"] != "fill" {
        normalized["depends_on"] = json!({"source_namespace":source["source_namespace"],"source_epoch":source["source_epoch"],"external_fact_id":raw["cause"]["exec_id"]});
    }
    let mut document = doc.clone();
    document["units"] = json!({"quantity":{"unit":model.quantity_unit,"quantum":"1"},"money":{"unit":model.currency,"currency":model.currency,"quantum":"1"},"numeric_encoding":"exact_decimal_integer_text"});
    Ok((document, normalized))
}

/// Capture 的首次写入验证冻结 X 库中的原字节；请求不能自行提供来源路径或升级格式。
pub(crate) fn verify_capture(manifest: &Value, envelope: &Value, raw: &str) -> Result<(), String> {
    let doc = strict_json(raw.as_bytes())?;
    let binding = &manifest["history_simulation_source"];
    if doc["format"] != RAW_FORMAT {
        if binding.is_object()
            && binding["source_namespace"] == envelope["source_namespace"]
            && binding["source_epoch"] == envelope["source_epoch"]
        {
            return Err("IdentityConflict：同一执行来源不得混用模拟与场所原件".into());
        }
        return Ok(());
    }
    for key in [
        "source_namespace",
        "source_epoch",
        "producer_id",
        "producer_epoch",
    ] {
        if required(binding, key)? != required(envelope, key)? {
            return Err("IdentityConflict：模拟原件不是冻结 X 来源".into());
        }
    }
    if binding["model_content_hash"] != doc["model_content_hash"] {
        return Err("IdentityConflict：模拟模型不是本会话冻结版本".into());
    }
    let db = Path::new(required(binding, "x_db")?);
    if !db.is_absolute() {
        return Err("InvalidDomain：X 原件库须为冻结绝对路径".into());
    }
    let c = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(failure)?;
    // 与 economic_session::store 的打开取值一致：X 正在提交时等锁，而非立即报原件不可核。
    c.busy_timeout(std::time::Duration::from_secs(2))
        .map_err(failure)?;
    let contract: String = c
        .query_row("SELECT v FROM x_sim_meta WHERE k='contract'", [], |r| {
            r.get(0)
        })
        .map_err(failure)?;
    let contract = strict_json(contract.as_bytes())?;
    if digest(&contract["model"]) != binding["model_content_hash"]
        || contract["source_namespace"] != binding["source_namespace"]
        || contract["source_epoch"] != binding["source_epoch"]
    {
        return Err("IdentityConflict：冻结 X 库合同与会话来源不符".into());
    }
    let stored: String = c
        .query_row(
            "SELECT raw FROM x_sim_originals WHERE id=?1",
            [required(&doc["event"]["source"], "external_fact_id")?],
            |r| r.get(0),
        )
        .map_err(failure)?;
    if stored != raw {
        return Err("IdentityConflict：模拟原件不等于 X 持久原字节".into());
    }
    Ok(())
}

/// #1375：从 E 已冻结的 X 只读库核验一批已提交原件。调用者须指定批身份，
/// 不能用最新读数主张故障结束；此结果也不证明任何事实已经济核清。
pub(crate) fn committed_capture_batch(
    manifest: &Value,
    batch_id: &str,
    receipt_digest: &str,
    x_id: &str,
    x_epoch: i64,
) -> Result<Value, String> {
    let binding = &manifest["history_simulation_source"];
    if !binding.is_object() {
        return Err("SchemaUnsupported：本会话未冻结模拟 X 原件来源".into());
    }
    let db = Path::new(required(binding, "x_db")?);
    if !db.is_absolute() {
        return Err("InvalidDomain：X 原件库须为冻结绝对路径".into());
    }
    let mut c =
        Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(failure)?;
    c.busy_timeout(std::time::Duration::from_secs(2))
        .map_err(failure)?;
    let tx = c.transaction().map_err(failure)?;
    let x_meta = |key| -> Result<String, String> {
        tx.query_row("SELECT value FROM x_meta WHERE key=?1", [key], |r| r.get(0))
            .map_err(failure)
    };
    let revision = x_meta("profile_revision")?;
    if x_meta("profile_mode")? != "simulation"
        || x_meta("history_simulation")? != "true"
        || x_meta("writer_epoch")? != x_epoch.to_string()
    {
        return Err("IdentityConflict：指定 X 模型或当前 writer epoch 不符".into());
    }
    super::runtime::check_inner_revision(&tx, &revision)?;
    let raw_profile: String = tx
        .query_row(
            "SELECT v FROM x_sim_meta WHERE k='authority_profile'",
            [],
            |r| r.get(0),
        )
        .map_err(failure)?;
    let parsed = super::runtime::parse_archive_profile(&revision, &raw_profile)?;
    let identity = parsed.identity(revision, x_epoch);
    if identity.session_id != required(manifest, "session_id")?
        || identity.session_generation != required(manifest, "session_generation")?
    {
        return Err("IdentityConflict：X 与 E 的会话或化身不同".into());
    }
    if identity.source_namespace != required(binding, "source_namespace")?
        || identity.source_epoch != required(binding, "source_epoch")?
    {
        return Err("IdentityConflict：X 持久来源与 E 冻结来源不同".into());
    }
    if identity.x_id != x_id
        || identity.model_content_hash != required(binding, "model_content_hash")?
    {
        return Err("IdentityConflict：X 身份或模型与冻结范围不同".into());
    }
    let raw: String = tx
        .query_row(
            "SELECT result FROM x_sim_batches WHERE id=?1",
            [batch_id],
            |r| r.get(0),
        )
        .map_err(failure)?;
    let receipt = strict_json(raw.as_bytes())?;
    if canonical_json(&receipt) != raw
        || receipt["request_id"] != batch_id
        || sha256_hex(raw.as_bytes()) != receipt_digest
    // DevSkim: ignore DS197836 内容寻址摘要
    {
        return Err("IdentityConflict：指定 X 批的完整回执摘要不同".into());
    }
    // 复用正式 X 恢复入口的只读部分：批重演之外，还核接纳、原 Release 与
    // S 执行证据。只核原件相符不能证明该批由正式命令产生。
    parsed.audit(&tx, x_epoch)?;
    tx.commit().map_err(failure)?;
    Ok(receipt)
}

/// #1425 R4：E 在经济分配前核对同会话同化身 X/3 的已提交原批、实际占用批与 E 原放行回执因果链。
/// 不把占用批（如 b2，可能无经济原件）与产生成交/费用原件的结果批（如 b3）强制要求同一批 ID。
/// 复用 `committed_capture_batch` 同一套 X 身份与只读全审计，并返回供 E/B 离线重放的自持见证。
pub(crate) struct XBatchSelector<'a> {
    pub x_id: &'a str,
    pub x_epoch: i64,
    pub batch_id: &'a str,
    pub batch_receipt_sha256: &'a str,
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn verify_execution_causal_chain(
    manifest: &Value,
    selector: &XBatchSelector<'_>,
    command_id: &str,
    expected_command: &Value,
    expected_command_hash: &str,
    expected_e_release_receipt_key: &str,
    expected_e_release_commit_ns: &str,
    expected_e_release_cut: &Value,
    expected_fact_raw_utf8: &str,
    expected_fact_raw_sha256: &str,
) -> Result<Value, String> {
    let binding = &manifest["history_simulation_source"];
    if !binding.is_object() {
        return Err("MissingDependency：本会话未冻结模拟 X 原件来源，Pending 保留".into());
    }
    let db = Path::new(required(binding, "x_db")?);
    if !db.is_absolute() {
        return Err("InvalidDomain：X 原件库须为冻结绝对路径".into());
    }
    let mut c =
        Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(failure)?;
    c.busy_timeout(std::time::Duration::from_secs(2))
        .map_err(failure)?;
    let tx = c.transaction().map_err(failure)?;
    let x_meta = |key: &str| -> Result<String, String> {
        tx.query_row("SELECT value FROM x_meta WHERE key=?1", [key], |r| r.get(0))
            .map_err(|e| {
                format!("MissingDependency：X/3 元数据缺失（裸 store 不能替代 X/3 执行因果）：{e}")
            })
    };
    let revision = x_meta("profile_revision")?;
    if revision != super::EXACT_PROFILE_REVISION {
        return Err(format!(
            "VersionUnsupported：单一明确原责任域模拟分配仅接受 {}（实际为 {}）",
            super::EXACT_PROFILE_REVISION,
            revision
        ));
    }
    if x_meta("profile_mode")? != "simulation"
        || x_meta("history_simulation")? != "true"
        || x_meta("writer_epoch")? != selector.x_epoch.to_string()
    {
        return Err("IdentityConflict：指定 X/3 模型或当前 writer epoch 不符".into());
    }
    super::runtime::check_inner_revision(&tx, &revision)?;
    let raw_profile: String = tx
        .query_row(
            "SELECT v FROM x_sim_meta WHERE k='authority_profile'",
            [],
            |r| r.get(0),
        )
        .map_err(|e| {
            format!("MissingDependency：X/3 缺权威 profile（裸 store 不能替代 X/3）：{e}")
        })?;
    let parsed = super::runtime::parse_archive_profile(&revision, &raw_profile)?;
    let identity = parsed.identity(revision.clone(), selector.x_epoch);
    if identity.session_id != required(manifest, "session_id")?
        || identity.session_generation != required(manifest, "session_generation")?
    {
        return Err("IdentityConflict：X/3 与 E 的会话或化身不同".into());
    }
    if identity.source_namespace != required(binding, "source_namespace")?
        || identity.source_epoch != required(binding, "source_epoch")?
    {
        return Err("IdentityConflict：X/3 持久来源与 E 冻结来源不同".into());
    }
    if identity.x_id != selector.x_id
        || identity.model_content_hash != required(binding, "model_content_hash")?
        || identity.e_authority_id != "E"
    {
        return Err("IdentityConflict：X/3 身份、模型或 E 权威绑定与冻结范围不同".into());
    }
    // 复用正式 X/3 冷审：核全批重演、接纳时钟、E Release 证据、S ExecuteCommitted 及占有批 claimed_ns。
    parsed.audit(&tx, selector.x_epoch)?;

    // 1. 核对具名结果批（如 b3），确认包含本件模拟原件精确原字节。
    let raw_batch_result: String = tx
        .query_row(
            "SELECT result FROM x_sim_batches WHERE id=?1",
            [selector.batch_id],
            |r| r.get(0),
        )
        .map_err(|e| format!("MissingDependency：指定 X/3 已提交结果批不存在：{e}"))?;
    let batch_receipt = strict_json(raw_batch_result.as_bytes())?;
    if canonical_json(&batch_receipt) != raw_batch_result
        || batch_receipt["request_id"] != selector.batch_id
        || sha256_hex(raw_batch_result.as_bytes()) != selector.batch_receipt_sha256
    {
        return Err("IdentityConflict：指定 X/3 结果批的完整回执摘要不符".into());
    }
    let originals_bar_index = batch_receipt["bar_index"]
        .as_i64()
        .filter(|&v| v >= 0)
        .ok_or("InvalidDomain：X/3 结果批 bar_index 非法")?;
    let originals = batch_receipt["originals"]
        .as_array()
        .ok_or("StorageUnavailable：X/3 结果批缺 originals 列表")?;
    if !originals
        .iter()
        .any(|doc| canonical_json(doc) == expected_fact_raw_utf8)
    {
        return Err(
            "MissingDependency：指定 X/3 结果批不包含该模拟原件精确字节，Pending 保留".into(),
        );
    }
    if sha256_hex(expected_fact_raw_utf8.as_bytes()) != expected_fact_raw_sha256 {
        return Err("IdentityConflict：原件字节摘要不符".into());
    }

    // 2. 核对 X/3 持久命令占用记录：必须为 Observed，绑定真实 E ReleasedExactReceipt 与占有批（如 b2）。
    let cmd_row: Option<(
        String,
        String,
        String,
        Option<String>,
        String,
        String,
        Option<String>,
    )> = tx
        .query_row(
            "SELECT command, release_receipt, state, attempt_batch, accept_clock, release_evidence, execute_evidence FROM x_exact_commands WHERE id=?1",
            [command_id],
            |r| {
                Ok((
                    r.get(0)?,
                    r.get(1)?,
                    r.get(2)?,
                    r.get(3)?,
                    r.get(4)?,
                    r.get(5)?,
                    r.get(6)?,
                ))
            },
        )
        .map(Some)
        .or_else(|e| {
            if matches!(e, rusqlite::Error::QueryReturnedNoRows) {
                Ok(None)
            } else {
                Err(failure(e))
            }
        })?;
    let (
        x_cmd_raw,
        x_release_receipt,
        x_state,
        x_attempt_raw,
        x_clock_raw,
        x_rel_ev_raw,
        x_exec_ev_raw,
    ) = cmd_row.ok_or("MissingDependency：X/3 未接纳该精确命令，Pending 保留")?;
    if x_state != "Observed" {
        return Err(format!(
            "MissingDependency：X/3 命令处于 {x_state}（需 Observed 终态占有并提交批次），Pending 保留"
        ));
    }
    if x_release_receipt != expected_e_release_receipt_key {
        return Err("IdentityConflict：X/3 接纳记录未绑定本笔 E 原放行回执键".into());
    }
    let x_cmd_val = strict_json(x_cmd_raw.as_bytes())?;
    if &x_cmd_val != expected_command || digest(&x_cmd_val) != expected_command_hash {
        return Err("IdentityConflict：X/3 持久命令体或摘要与 E ReleasedExact 不符".into());
    }
    let x_release_evidence = strict_json(x_rel_ev_raw.as_bytes())?;
    if x_release_evidence["protocol"] != super::runtime::AUTHORITY_WIRE
        || x_release_evidence["session_id"] != identity.session_id
        || x_release_evidence["session_generation"] != identity.session_generation
        || x_release_evidence["authority_id"] != "E"
        || x_release_evidence["command_id"] != command_id
        || x_release_evidence["command_hash"] != expected_command_hash
        || &x_release_evidence["command"] != expected_command
        || x_release_evidence["state"] != "ReleasedExact"
        || x_release_evidence["receipt_id"] != expected_e_release_receipt_key
        || !x_release_evidence["release_receipt_id"].is_null()
        || x_release_evidence["commit_ns"] != expected_e_release_commit_ns
    {
        return Err("IdentityConflict：X/3 release_evidence 与 E 原放行回执因果链不符".into());
    }
    let x_attempt_raw =
        x_attempt_raw.ok_or("MissingDependency：X/3 已占用命令缺 attempt_batch，Pending 保留")?;
    let attempt_batch: super::model::Batch =
        serde_json::from_str(&x_attempt_raw).map_err(failure)?;
    let attempt_batch_id = attempt_batch.request_id.clone();
    let attempt_bar_index = attempt_batch.bar.index;
    if attempt_bar_index < 0 || originals_bar_index < attempt_bar_index {
        return Err("IdentityConflict：X/3 结果批 bar 早于命令占有批 bar".into());
    }
    let (stored_attempt_req, stored_attempt_res): (String, String) = tx
        .query_row(
            "SELECT request, result FROM x_sim_batches WHERE id=?1",
            [&attempt_batch_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .map_err(|e| format!("MissingDependency：X/3 命令占有批尚未提交：{e}"))?;
    if stored_attempt_req != x_attempt_raw {
        return Err("IdentityConflict：X/3 命令占有批内容与已提交批次不符".into());
    }
    let attempt_batch_request_sha256 = sha256_hex(stored_attempt_req.as_bytes());
    let attempt_batch_receipt_sha256 = sha256_hex(stored_attempt_res.as_bytes());

    let x_accept_clock = strict_json(x_clock_raw.as_bytes())?;
    let x_exec_ev_raw = x_exec_ev_raw
        .ok_or("MissingDependency：X/3 命令缺 S 执行证明 execute_evidence，Pending 保留")?;
    let x_execute_evidence = strict_json(x_exec_ev_raw.as_bytes())?;
    if x_execute_evidence["reply"]["protocol"] != super::runtime::AUTHORITY_WIRE
        || x_execute_evidence["reply"]["session_id"] != identity.session_id
        || x_execute_evidence["reply"]["session_generation"] != identity.session_generation
        || x_execute_evidence["reply"]["command_id"] != command_id
        || x_execute_evidence["reply"]["command_hash"] != expected_command_hash
        || &x_execute_evidence["reply"]["command"] != expected_command
        || x_execute_evidence["reply"]["state"] != "ExecuteCommitted"
        || x_execute_evidence["reply"]["release_receipt_id"] != expected_e_release_receipt_key
        || x_execute_evidence["claimed_ns"] != attempt_bar_index.to_string()
    {
        return Err(
            "IdentityConflict：X/3 execute_evidence 未绑定同会话 E 原放行或占有批 bar".into(),
        );
    }
    tx.commit().map_err(failure)?;

    Ok(json!({
        "witness_revision": X_EXECUTION_WITNESS_REVISION,
        "x_profile_revision": revision,
        "x_id": identity.x_id,
        "x_epoch": selector.x_epoch.to_string(),
        "session_id": identity.session_id,
        "session_generation": identity.session_generation,
        "source_namespace": identity.source_namespace,
        "source_epoch": identity.source_epoch,
        "model_content_hash": identity.model_content_hash,
        "command_id": command_id,
        "command_hash": expected_command_hash,
        "e_release_receipt_key": expected_e_release_receipt_key,
        "e_release_cut": expected_e_release_cut,
        "e_release_commit_ns": expected_e_release_commit_ns,
        "x_release_evidence": x_release_evidence,
        "x_accept_clock": x_accept_clock,
        "x_command_state": x_state,
        "x_execute_evidence": x_execute_evidence,
        "attempt_batch_id": attempt_batch_id,
        "attempt_batch_bar_index": attempt_bar_index.to_string(),
        "attempt_batch_request_sha256": attempt_batch_request_sha256,
        "attempt_batch_receipt_sha256": attempt_batch_receipt_sha256,
        "originals_batch_id": selector.batch_id,
        "originals_batch_bar_index": originals_bar_index.to_string(),
        "originals_batch_receipt_sha256": selector.batch_receipt_sha256,
        "fact_raw_sha256": expected_fact_raw_sha256,
    }))
}
