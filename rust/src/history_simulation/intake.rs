use super::{
    model::{Fill, Model},
    store::RAW_FORMAT,
};
use crate::session_protocol::{canonical_json, nonnegative, required, sha256_hex, strict_json};
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::path::Path;

pub(crate) const EVENT: &str = "history-sim-unresolved/1";
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
    if x_meta("profile_revision")? != "x-execution-profile/1"
        || x_meta("profile_mode")? != "simulation"
        || x_meta("history_simulation")? != "true"
        || x_meta("writer_epoch")? != x_epoch.to_string()
    {
        return Err("IdentityConflict：指定 X 模型或当前 writer epoch 不符".into());
    }
    let raw_profile: String = tx
        .query_row(
            "SELECT v FROM x_sim_meta WHERE k='authority_profile'",
            [],
            |r| r.get(0),
        )
        .map_err(failure)?;
    let profile: super::runtime::Profile =
        serde_json::from_value(strict_json(raw_profile.as_bytes())?).map_err(failure)?;
    if profile.session_id != required(manifest, "session_id")?
        || profile.session_generation != required(manifest, "session_generation")?
    {
        return Err("IdentityConflict：X 与 E 的会话或化身不同".into());
    }
    if profile.source_namespace != required(binding, "source_namespace")?
        || profile.source_epoch != required(binding, "source_epoch")?
    {
        return Err("IdentityConflict：X 持久来源与 E 冻结来源不同".into());
    }
    if profile.x_id != x_id
        || digest(&serde_json::to_value(&profile.model).map_err(failure)?)
            != required(binding, "model_content_hash")?
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
    super::runtime::validate_existing(&tx, &profile, x_epoch)?;
    tx.commit().map_err(failure)?;
    Ok(receipt)
}

/// #1375：从 E 已冻结的模拟 X 只读库核验**全部**已提交批的原件并确认无未提交在途批。
/// 单一 QueryBatch 不能替代整段连续性证明：这里必须核对 `state.last_request_id` 对应的
/// 完整结束界、全量冷重放 `validate_existing` 与所有批的逐件原件。
pub(crate) fn committed_capture_history(
    manifest: &Value,
    x_id: &str,
    x_epoch: i64,
    end_batch_id: Option<&str>,
    end_receipt_digest: Option<&str>,
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
    if x_meta("profile_revision")? != "x-execution-profile/1"
        || x_meta("profile_mode")? != "simulation"
        || x_meta("history_simulation")? != "true"
        || x_meta("writer_epoch")? != x_epoch.to_string()
    {
        return Err("IdentityConflict：指定 X 模型或当前 writer epoch 不符".into());
    }
    let raw_profile: String = tx
        .query_row(
            "SELECT v FROM x_sim_meta WHERE k='authority_profile'",
            [],
            |r| r.get(0),
        )
        .map_err(failure)?;
    let profile: super::runtime::Profile =
        serde_json::from_value(strict_json(raw_profile.as_bytes())?).map_err(failure)?;
    if profile.session_id != required(manifest, "session_id")?
        || profile.session_generation != required(manifest, "session_generation")?
    {
        return Err("IdentityConflict：X 与 E 的会话或化身不同".into());
    }
    if profile.source_namespace != required(binding, "source_namespace")?
        || profile.source_epoch != required(binding, "source_epoch")?
    {
        return Err("IdentityConflict：X 持久来源与 E 冻结来源不同".into());
    }
    if profile.x_id != x_id
        || digest(&serde_json::to_value(&profile.model).map_err(failure)?)
            != required(binding, "model_content_hash")?
    {
        return Err("IdentityConflict：X 身份或模型与冻结范围不同".into());
    }
    super::runtime::validate_existing(&tx, &profile, x_epoch)?;
    if super::store::pending_batch(&tx)?.is_some() {
        return Err("MissingDependency：模拟 X 尚有未提交在途批，无法证明完整结束界".into());
    }
    let raw_state: String = tx
        .query_row("SELECT v FROM x_sim_meta WHERE k='state'", [], |r| r.get(0))
        .map_err(failure)?;
    let state: super::model::State =
        serde_json::from_value(strict_json(raw_state.as_bytes())?).map_err(failure)?;
    let state_hash = digest(&serde_json::to_value(&state).map_err(failure)?);
    let mut batches: Vec<(i64, Value)> = Vec::new();
    {
        let mut stmt = tx
            .prepare("SELECT id, result FROM x_sim_batches")
            .map_err(failure)?;
        let rows = stmt
            .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
            .map_err(failure)?;
        for row in rows {
            let (id, raw) = row.map_err(failure)?;
            let receipt = strict_json(raw.as_bytes())?;
            if canonical_json(&receipt) != raw || receipt["request_id"] != id {
                return Err("IdentityConflict：模拟 X 批回执不规范".into());
            }
            let bar = receipt["bar_index"]
                .as_i64()
                .ok_or("IdentityConflict：模拟 X 批缺 bar_index")?;
            batches.push((bar, receipt));
        }
    }
    match (end_batch_id, end_receipt_digest) {
        (Some(id), Some(expected_digest)) => {
            if state.last_request_id.as_deref() != Some(id) {
                return Err(
                    "MissingDependency：指定结束批不是模拟 X 当前完整前沿，单一 QueryBatch 不能证明整段无漏报"
                        .into(),
                );
            }
            let raw: String = tx
                .query_row("SELECT result FROM x_sim_batches WHERE id=?1", [id], |r| {
                    r.get(0)
                })
                .map_err(failure)?;
            if sha256_hex(raw.as_bytes()) != expected_digest {
                // DevSkim: ignore DS197836 内容寻址摘要
                return Err("IdentityConflict：指定 X 结束批的完整回执摘要不同".into());
            }
        }
        (None, None) => {
            if state.last_request_id.is_some() || !batches.is_empty() {
                return Err("MissingDependency：模拟 X 已有已提交批，须指定完整结束批".into());
            }
        }
        _ => {
            return Err("InvalidDomain：模拟 X 结束批号与回执摘要须成对提供".into());
        }
    }
    batches.sort_by_key(|(bar, _)| *bar);
    let mut originals = Vec::new();
    for (_, receipt) in &batches {
        let docs = receipt["originals"]
            .as_array()
            .ok_or("StorageUnavailable：模拟批缺原件列表")?;
        for doc in docs {
            originals.push(doc.clone());
        }
    }
    tx.commit().map_err(failure)?;
    Ok(json!({
        "x_id": x_id,
        "x_writer_epoch": x_epoch.to_string(),
        "last_bar": state.last_bar,
        "last_request_id": state.last_request_id,
        "state_content_hash": state_hash,
        "batch_count": batches.len().to_string(),
        "originals": originals
    }))
}
