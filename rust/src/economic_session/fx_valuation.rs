//! #1375 AC2（R2）：市场 FX 报价原件的 E 侧规范接纳、替代链精确退役、真实财务责任联动投影与影响封闸。
//!
//! 设计纪律：
//! - 仅在 manifest 显式选择并列 TestOnly 子合同 `fx-valuation/1` 时激活；未选择时旧现金路径与旧库零改动。
//! - 取消平行 manifest 数量/毛保留/cap 清单：权威财务真值唯一来自 E 持久的 `image["finance"]`
//!   （`responsibilities` 含导入基线与真实 `Reserve` grant、`foreign_responsibilities` 含正式导入的 TestOnly 外币义务、
//!   以及生效 `cap_policy` / 冻结财务 `policy`）。
//! - `image["fx_valuation"]` 是在同一事务中由 `(image["finance"], recorded, pending, coverages)` 确定的派生投影；
//!   任一财务写口（`ImportResponsibility`、`ImportFxResponsibility`、`Reserve`、`ActivateCapPolicy`）与行情写口
//!   （`CaptureExternal`、`ResolveEvidence`）提交时同步刷新，旧 cut 完整保留历史 Pending 与超限史。
//! - 已被合法替代且当前回到限内的旧版 token，仅允许通过正式 `ResolveEvidence` 协议（精确指名原 `fact_key` /
//!   `fact_hash` / `token` 与有效前沿，且同替代链活动头已 `Covered` 或在同批有效核清）精确退役为
//!   `RetiredBySupersession`；绝不在查询时隐藏未决 token，绝不用旧版核清新版，绝不连带清除无关 token。

use super::book::{fact_key, hash};
use super::service::select_cut;
use super::store::{cut, rows, Config};
use super::voice::{digest, exact};
use crate::session_protocol::{nonnegative, positive, required, sha256_hex, strict_json};
use rusqlite::Connection;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::io::Read;
use std::path::Path;

pub(super) const SCHEMA: &str = "fx-valuation/1";
pub(super) const QUOTE_SCHEMA: &str = "testonly-fx-quote/1";
pub(super) const OBLIGATION_INPUT_SCHEMA: &str = "testonly-fx-obligation-input/1";
pub(super) const META_KEY: &str = "fx_valuation_revision";
pub(super) const CONTRACT_FIELD: &str = "fx_valuation";
pub(super) const QUERY: &str = "QueryFxValuation";
pub(super) const IMPORT_OP: &str = "ImportFxResponsibility";
const CAP_GATE_SLOT: &str = "fx_cap_gate";
const VALUATION_GATE_SLOT: &str = "fx_valuation_gate";
const LIMIT: usize = 16 * 1024 * 1024;

pub(super) fn enabled(config: &Config) -> bool {
    config
        .manifest
        .get(CONTRACT_FIELD)
        .is_some_and(|v| !v.is_null())
}

pub(super) fn bound_revision(config: &Config) -> Result<Option<&'static str>, String> {
    if validate_config(&config.manifest)? {
        Ok(Some(SCHEMA))
    } else {
        Ok(None)
    }
}

pub(super) fn validate_config(manifest: &Value) -> Result<bool, String> {
    let Some(fx) = manifest.get(CONTRACT_FIELD).filter(|v| !v.is_null()) else {
        return Ok(false);
    };
    if !super::store::component_clock(manifest) {
        return Err(
            "UnsupportedCapability：fx-valuation/1 仅支持显式 TestOnly 或精确放行 logical-bar/1 模拟会话"
                .into(),
        );
    }
    if !manifest.get("finance").is_some_and(|v| !v.is_null()) {
        return Err(
            "MissingDependency：启用 fx-valuation/1 须同时配置 finance 子合同，不得使用平行 manifest 财务清单"
                .into(),
        );
    }
    if !super::book::rules(manifest)?.is_tb03c() {
        return Err(
            "SchemaUnsupported：启用 fx-valuation/1 须同时启用 tb03c-book/1 或 /2 以支持正式 ResolveEvidence"
                .into(),
        );
    }
    exact(
        fx,
        &[
            "schema_revision",
            "kind",
            "obligation_input_path",
            "obligation_input_sha256",
        ],
    )?;
    if fx["schema_revision"] != SCHEMA || fx["kind"] != "TestOnly" {
        return Err("SchemaUnsupported：fx_valuation 须为 TestOnly 的 fx-valuation/1".into());
    }
    if !Path::new(required(fx, "obligation_input_path")?).is_absolute() {
        return Err("InvalidDomain：外币义务原件路径须绝对路径".into());
    }
    digest(required(fx, "obligation_input_sha256")?)?;
    Ok(true)
}

pub(super) fn pinned_obligation_raw(config: &Config) -> Result<String, String> {
    if !enabled(config) {
        return Err("SchemaUnsupported：未启用 fx-valuation/1 子合同".into());
    }
    let path = required(&config.manifest[CONTRACT_FIELD], "obligation_input_path")?;
    let mut bytes = Vec::new();
    let f = std::fs::File::open(path)
        .map_err(|e| format!("MissingDependency：外币义务原件不可读：{e}"))?;
    if !f.metadata().map_err(|e| e.to_string())?.is_file() {
        return Err("InvalidDomain：外币义务原件须普通文件".into());
    }
    f.take((LIMIT + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() > LIMIT {
        return Err("InvalidDomain：外币义务原件超限".into());
    }
    String::from_utf8(bytes).map_err(|e| e.to_string())
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct DeclaredBoundary {
    obligation_input_sha256: String,
    source_id: String,
    source_epoch: String,
    declared_foreign_responsibility_ids: Vec<String>,
}

fn parse_obligation_doc(
    config: &Config,
    raw: &str,
    cap_currency: Option<&str>,
) -> Result<Value, String> {
    if !enabled(config) {
        return Err("SchemaUnsupported：未启用 fx-valuation/1 子合同".into());
    }
    let expected_sha = required(&config.manifest[CONTRACT_FIELD], "obligation_input_sha256")?;
    if raw.len() > LIMIT || sha256_hex(raw.as_bytes()) != expected_sha {
        return Err("IdentityConflict：外币义务原件不等于冻结摘要".into());
    }
    let doc = strict_json(raw.as_bytes())?;
    exact(
        &doc,
        &[
            "schema_revision",
            "kind",
            "source_id",
            "source_epoch",
            "obligations",
        ],
    )?;
    if doc["schema_revision"] != OBLIGATION_INPUT_SCHEMA || doc["kind"] != "TestOnly" {
        return Err(
            "UnsupportedCapability：外币义务原件须为 TestOnly 的 testonly-fx-obligation-input/1"
                .into(),
        );
    }
    required(&doc, "source_id")?;
    required(&doc, "source_epoch")?;
    let arr = doc["obligations"]
        .as_array()
        .ok_or("SchemaUnsupported：obligations 须数组")?;
    let mut seen_ids = BTreeSet::new();
    for ob in arr {
        exact(
            ob,
            &[
                "responsibility_id",
                "owner",
                "account_ref",
                "quantity",
                "unit",
                "valuation_instrument",
                "quote_source",
                "source_ref",
            ],
        )?;
        let rid = required(ob, "responsibility_id")?;
        if !seen_ids.insert(rid) {
            return Err(format!("IdentityConflict：重复的外币责任身份 {rid}"));
        }
        let owner = required(ob, "owner")?;
        let chong_id = owner
            .strip_prefix("B:")
            .ok_or("InvalidDomain：外币义务 owner 须具名 B 路由")?;
        config.route(chong_id)?;
        required(ob, "account_ref")?;
        required(ob, "source_ref")?;
        positive(required(ob, "quantity")?, "foreign obligation quantity")?;
        let unit = required(ob, "unit")?;
        if let Some(cc) = cap_currency {
            if unit == cc {
                return Err(
                    "InvalidDomain：外币义务单位不得与现金 cap 币种相同（不得给旧现金义务改标签）"
                        .into(),
                );
            }
        }
        let instrument = required(ob, "valuation_instrument")?;
        let Some((base, quote)) = instrument.split_once('/') else {
            return Err(format!(
                "InvalidDomain：外币义务估值工具 {instrument} 须为 BASE/QUOTE 形式"
            ));
        };
        if base != unit || quote.is_empty() || quote.contains('/') || base == quote {
            return Err(format!(
                "InvalidDomain：外币义务估值工具 {instrument} 与单位 {unit} 不一致"
            ));
        }
        if let Some(cc) = cap_currency {
            let expected_inst = format!("{unit}/{cc}");
            if instrument != expected_inst {
                return Err(format!(
                    "InvalidDomain：外币义务估值工具 {instrument} 须与 {expected_inst} 一致"
                ));
            }
        }
        exact(&ob["quote_source"], &["source_namespace", "source_epoch"])?;
        let qns = required(&ob["quote_source"], "source_namespace")?;
        let qep = required(&ob["quote_source"], "source_epoch")?;
        let authorized = config.manifest["authorized_sources"]
            .as_array()
            .is_some_and(|sources| {
                sources.iter().any(|s| {
                    s["source_namespace"] == qns
                        && s["source_epoch"] == qep
                        && s["operations"]
                            .as_array()
                            .is_some_and(|ops| ops.iter().any(|o| o == "CaptureExternal"))
                })
            });
        if !authorized {
            return Err(format!(
                "InvalidDomain：外币义务引用未获 CaptureExternal 授权的报价来源 {qns}/{qep}"
            ));
        }
    }
    Ok(doc)
}

pub(super) fn parse_obligation_input(
    config: &Config,
    raw: &str,
    finance_policy: &Value,
) -> Result<Value, String> {
    let cap_currency = required(finance_policy, "currency")?;
    parse_obligation_doc(config, raw, Some(cap_currency))
}

fn parse_declared_boundary(config: &Config) -> Result<DeclaredBoundary, String> {
    let raw = pinned_obligation_raw(config)?;
    let doc = parse_obligation_doc(config, &raw, None)?;
    let expected_sha = required(&config.manifest[CONTRACT_FIELD], "obligation_input_sha256")?;
    let declared_ids = doc["obligations"]
        .as_array()
        .ok_or("SchemaUnsupported：obligations 须数组")?
        .iter()
        .map(|ob| required(ob, "responsibility_id").map(ToOwned::to_owned))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(DeclaredBoundary {
        obligation_input_sha256: expected_sha.to_owned(),
        source_id: required(&doc, "source_id")?.to_owned(),
        source_epoch: required(&doc, "source_epoch")?.to_owned(),
        declared_foreign_responsibility_ids: declared_ids,
    })
}

fn extract_boundary(image: &Value, config: Option<&Config>) -> Result<DeclaredBoundary, String> {
    let b = image
        .get(CONTRACT_FIELD)
        .and_then(|fx| fx.get("boundary"))
        .filter(|v| v.is_object())
        .ok_or("StorageUnavailable：持久图像缺失 fx_valuation.boundary 共同界声明")?;
    let sha = required(b, "obligation_input_sha256")?.to_owned();
    if let Some(cfg) = config {
        let expected_sha = required(&cfg.manifest[CONTRACT_FIELD], "obligation_input_sha256")?;
        if sha != expected_sha {
            return Err("IdentityConflict：持久共同界声明与冻结外币义务摘要不符".into());
        }
    }
    let declared_ids = b["declared_foreign_responsibility_ids"]
        .as_array()
        .ok_or("StorageUnavailable：boundary.declared_foreign_responsibility_ids 形状")?
        .iter()
        .map(|v| {
            v.as_str()
                .filter(|s| !s.is_empty())
                .map(ToOwned::to_owned)
                .ok_or_else(|| "StorageUnavailable：boundary 声明责任 ID 非字符串".to_owned())
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(DeclaredBoundary {
        obligation_input_sha256: sha,
        source_id: required(b, "source_id")?.to_owned(),
        source_epoch: required(b, "source_epoch")?.to_owned(),
        declared_foreign_responsibility_ids: declared_ids,
    })
}

pub(super) fn import_obligation(
    config: &Config,
    previous: &Value,
    next: &mut Value,
    finance_policy: &Value,
    raw: &str,
    responsibility_id: &str,
    seq: i64,
    ns: &str,
) -> Result<Value, String> {
    if config.domain != "E" {
        return Err("InvalidDomain：ImportFxResponsibility 仅 E".into());
    }
    let doc = parse_obligation_input(config, raw, finance_policy)?;
    let ob = doc["obligations"]
        .as_array()
        .unwrap()
        .iter()
        .find(|x| x["responsibility_id"] == responsibility_id)
        .ok_or_else(|| {
            format!("IdentityConflict：外币责任 {responsibility_id} 不在冻结外币义务原件中")
        })?;
    let existing = previous["finance"]
        .get("foreign_responsibilities")
        .and_then(Value::as_array)
        .ok_or("StorageUnavailable：缺少 foreign_responsibilities 集合")?;
    if existing
        .iter()
        .any(|x| x["responsibility_id"] == responsibility_id)
    {
        return Err(format!(
            "IdentityConflict：外币责任 {responsibility_id} 已导入 E，不能重复导入"
        ));
    }
    let input_sha256 = sha256_hex(raw.as_bytes());
    let entry = json!({
        "kind": "ForeignObligation",
        "responsibility_id": ob["responsibility_id"],
        "owner": ob["owner"],
        "account_ref": ob["account_ref"],
        "quantity": ob["quantity"],
        "unit": ob["unit"],
        "valuation_instrument": ob["valuation_instrument"],
        "quote_source": ob["quote_source"],
        "source_ref": ob["source_ref"],
        "input_sha256": input_sha256,
        "imported_seq": seq.to_string(),
        "imported_ns": ns,
        "source": ob
    });
    next["finance"]["foreign_responsibilities"]
        .as_array_mut()
        .ok_or("StorageUnavailable：foreign_responsibilities 形状")?
        .push(entry.clone());
    refresh_from_finance(config, next)?;
    Ok(json!({
        "responsibility_id": responsibility_id,
        "state": "FxResponsibilityImported",
        "original": entry
    }))
}

pub(super) fn is_fx_quote_event(event: &Value) -> bool {
    event.get("event").and_then(Value::as_str) == Some("fx_quote")
}

/// 严格解码 `testonly-fx-quote/1` 市场原字节（仅接受 RFC 6901 根指针 `""`）。
pub(super) fn decode(doc: &Value, pointer: &str) -> Result<(Value, Value), String> {
    if !pointer.is_empty() {
        return Err("SchemaUnsupported：FX 市场报价原件须在文档根（json_pointer=\"\"）".into());
    }
    exact(
        doc,
        &[
            "schema_revision",
            "source_namespace",
            "source_epoch",
            "instrument",
            "event_id",
            "source_coord",
            "revision",
            "supersedes_revision",
            "price_numerator",
            "price_denominator",
            "base_unit",
            "quote_unit",
            "timestamp",
            "received_at",
        ],
    )?;
    if doc["schema_revision"] != QUOTE_SCHEMA {
        return Err("SchemaUnsupported：FX 市场报价版本须 testonly-fx-quote/1".into());
    }
    let source_namespace = required(doc, "source_namespace")?;
    let source_epoch = required(doc, "source_epoch")?;
    let instrument = required(doc, "instrument")?;
    let event_id = required(doc, "event_id")?;
    let source_coord = required(doc, "source_coord")?;
    let revision = required(doc, "revision")?;
    let price_numerator = required(doc, "price_numerator")?;
    let price_denominator = required(doc, "price_denominator")?;
    let base_unit = required(doc, "base_unit")?;
    let quote_unit = required(doc, "quote_unit")?;
    let timestamp = required(doc, "timestamp")?;
    let received_at = required(doc, "received_at")?;

    nonnegative(source_coord, "source_coord")?;
    let rev_num = positive(revision, "revision")?;
    positive(price_numerator, "price_numerator")?;
    positive(price_denominator, "price_denominator")?;
    if base_unit == quote_unit {
        return Err("InvalidDomain：FX 报价 base_unit 与 quote_unit 相同".into());
    }
    let expected_instrument = format!("{base_unit}/{quote_unit}");
    if instrument != expected_instrument {
        return Err(format!(
            "InvalidDomain：FX 报价 instrument={instrument} 与 {expected_instrument} 不一致"
        ));
    }

    let supersedes_revision = match doc.get("supersedes_revision") {
        Some(Value::Null) => None,
        Some(Value::String(s)) if !s.is_empty() => {
            let prev_num = positive(s, "supersedes_revision")?;
            if prev_num >= rev_num {
                return Err("InvalidDomain：supersedes_revision 须严格小于 revision".into());
            }
            Some(s.as_str())
        }
        _ => return Err("SchemaUnsupported：supersedes_revision 须为 null 或正整数文本".into()),
    };

    let external_fact_id = quote_external_fact_id(instrument, event_id, revision);
    let depends_on = supersedes_revision.map(|prev_rev| {
        let prev_event = json!({
            "source": {
                "source_namespace": source_namespace,
                "source_epoch": source_epoch,
                "external_fact_id": quote_external_fact_id(instrument, event_id, prev_rev)
            }
        });
        let dep_key = fact_key(&prev_event).expect("synthesized predecessor fact_key");
        json!({
            "fact_key": dep_key,
            "revision": prev_rev,
            "source_namespace": source_namespace,
            "source_epoch": source_epoch,
            "external_fact_id": quote_external_fact_id(instrument, event_id, prev_rev)
        })
    });

    let event = json!({
        "event": "fx_quote",
        "allocation_id": external_fact_id,
        "source": {
            "source_namespace": source_namespace,
            "source_epoch": source_epoch,
            "external_fact_id": external_fact_id,
            "source_cursor": source_coord,
            "received_time": received_at,
            "claimed_origin": format!("market-fx:{source_namespace}:{source_epoch}"),
            "source_event_time": timestamp
        },
        "quote": {
            "schema_revision": QUOTE_SCHEMA,
            "instrument": instrument,
            "event_id": event_id,
            "source_coord": source_coord,
            "revision": revision,
            "supersedes_revision": supersedes_revision,
            "price_numerator": price_numerator,
            "price_denominator": price_denominator,
            "base_unit": base_unit,
            "quote_unit": quote_unit,
            "timestamp": timestamp
        },
        "depends_on": depends_on
    });
    let wrapper = json!({
        "format": QUOTE_SCHEMA,
        "units": {
            "base": base_unit,
            "quote": quote_unit
        },
        "document": doc
    });
    Ok((wrapper, event))
}

fn quote_external_fact_id(instrument: &str, event_id: &str, revision: &str) -> String {
    format!("fx-quote:{instrument}:{event_id}:rev:{revision}")
}

pub(super) fn check_capture(config: &Config, event: &Value) -> Result<(), String> {
    if !is_fx_quote_event(event) {
        return Ok(());
    }
    if config.domain != "E" {
        return Err("InvalidDomain：FX 市场报价仅由 E 接纳".into());
    }
    if !enabled(config) {
        return Err("SchemaUnsupported：当前经济会话未启用 fx-valuation/1 子合同".into());
    }
    Ok(())
}

/// 创世空投影：不预载任何 manifest 假数量/假 cap，只持久绑定冻结外币义务清单的身份边界，等待真实 FIN 导入。
pub(super) fn empty(config: &Config) -> Result<Option<Value>, String> {
    if config.domain != "E" || !enabled(config) {
        return Ok(None);
    }
    let boundary = parse_declared_boundary(config)?;
    let dummy_image = json!({
        "finance": {
            "responsibilities": [],
            "foreign_responsibilities": []
        }
    });
    let derived = derive_state(
        Some(config),
        &dummy_image,
        &boundary,
        &[],
        &[],
        &BTreeMap::new(),
    )?;
    Ok(Some(derived.json))
}

#[derive(Clone)]
struct ParsedQuote {
    fact_key: String,
    fact_hash: String,
    raw_sha256: String,
    source_namespace: String,
    source_epoch: String,
    instrument: String,
    event_id: String,
    source_coord: String,
    revision: String,
    revision_num: i64,
    supersedes_revision: Option<String>,
    supersedes_fact_key: Option<String>,
    price_numerator: i64,
    price_denominator: i64,
    base_unit: String,
    quote_unit: String,
    timestamp: String,
    recorded_seq: String,
}

#[derive(Clone)]
struct ForeignObligationRow {
    responsibility_id: String,
    owner: String,
    account_ref: String,
    source_ref: String,
    input_sha256: String,
    imported_seq: String,
    quantity: i64,
    unit: String,
    valuation_instrument: String,
    quote_source_namespace: String,
    quote_source_epoch: String,
}

fn parse_quote_record(record: &Value) -> Result<Option<ParsedQuote>, String> {
    let event = &record["event"];
    if !is_fx_quote_event(event) {
        return Ok(None);
    }
    let q = &event["quote"];
    let src = &event["source"];
    let revision = required(q, "revision")?.to_owned();
    let revision_num = positive(&revision, "revision")?;
    let supersedes_revision = q
        .get("supersedes_revision")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    let supersedes_fact_key = event
        .get("depends_on")
        .and_then(|d| d.get("fact_key"))
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    Ok(Some(ParsedQuote {
        fact_key: required(record, "fact_key")?.to_owned(),
        fact_hash: required(record, "fact_hash")?.to_owned(),
        raw_sha256: required(record, "raw_sha256")?.to_owned(),
        source_namespace: required(src, "source_namespace")?.to_owned(),
        source_epoch: required(src, "source_epoch")?.to_owned(),
        instrument: required(q, "instrument")?.to_owned(),
        event_id: required(q, "event_id")?.to_owned(),
        source_coord: required(q, "source_coord")?.to_owned(),
        revision,
        revision_num,
        supersedes_revision,
        supersedes_fact_key,
        price_numerator: positive(required(q, "price_numerator")?, "price_numerator")?,
        price_denominator: positive(required(q, "price_denominator")?, "price_denominator")?,
        base_unit: required(q, "base_unit")?.to_owned(),
        quote_unit: required(q, "quote_unit")?.to_owned(),
        timestamp: required(q, "timestamp")?.to_owned(),
        recorded_seq: record
            .get("recorded_seq")
            .and_then(Value::as_str)
            .unwrap_or("0")
            .to_owned(),
    }))
}

fn parse_foreign_responsibilities(image: &Value) -> Result<Vec<ForeignObligationRow>, String> {
    let Some(arr) = image
        .get("finance")
        .and_then(|f| f.get("foreign_responsibilities"))
        .and_then(Value::as_array)
    else {
        return Ok(Vec::new());
    };
    let mut out = Vec::with_capacity(arr.len());
    for row in arr {
        out.push(ForeignObligationRow {
            responsibility_id: required(row, "responsibility_id")?.to_owned(),
            owner: required(row, "owner")?.to_owned(),
            account_ref: required(row, "account_ref")?.to_owned(),
            source_ref: required(row, "source_ref")?.to_owned(),
            input_sha256: required(row, "input_sha256")?.to_owned(),
            imported_seq: required(row, "imported_seq")?.to_owned(),
            quantity: positive(required(row, "quantity")?, "foreign quantity")?,
            unit: required(row, "unit")?.to_owned(),
            valuation_instrument: required(row, "valuation_instrument")?.to_owned(),
            quote_source_namespace: required(&row["quote_source"], "source_namespace")?.to_owned(),
            quote_source_epoch: required(&row["quote_source"], "source_epoch")?.to_owned(),
        });
    }
    Ok(out)
}

fn quote_matches_foreign(quote: &ParsedQuote, ob: &ForeignObligationRow) -> bool {
    quote.source_namespace == ob.quote_source_namespace
        && quote.source_epoch == ob.quote_source_epoch
        && quote.instrument == ob.valuation_instrument
}

fn matched_foreign_obligations(
    image: &Value,
    fact: &Value,
) -> Result<Vec<ForeignObligationRow>, String> {
    let Some(quote) = parse_quote_record(fact)? else {
        return Ok(Vec::new());
    };
    let foreign_obs = parse_foreign_responsibilities(image)?;
    Ok(foreign_obs
        .into_iter()
        .filter(|ob| quote_matches_foreign(&quote, ob))
        .collect())
}

/// 同一切面上检验 `account:*` 的 FX 报价 Pending 是否已在 E 持久外币责任中获得归属证明。
/// 非 FX 事实一律返回 `false`，绝不放松无关 `account:*` Pending。
pub(super) fn has_persisted_attribution(previous: &Value, fact: &Value) -> Result<bool, String> {
    if !is_fx_quote_event(&fact["event"]) {
        return Ok(false);
    }
    Ok(!matched_foreign_obligations(previous, fact)?.is_empty())
}

fn extract_coverages(image: &Value) -> BTreeMap<String, Value> {
    let mut map = BTreeMap::new();
    let Some(revs) = image
        .get(CONTRACT_FIELD)
        .and_then(|fx| fx.get("revisions"))
        .and_then(Value::as_array)
    else {
        return map;
    };
    for r in revs {
        let status = r.get("coverage_status").and_then(Value::as_str);
        if matches!(status, Some("Covered" | "RetiredBySupersession")) {
            if let Some(fk) = r.get("fact_key").and_then(Value::as_str) {
                map.insert(
                    fk.to_owned(),
                    json!({
                        "status": r["coverage_status"],
                        "evidence_id": r["evidence_id"],
                        "evidence_hash": r["evidence_hash"],
                        "retired_by_fact_key": r.get("retired_by_fact_key").cloned().unwrap_or(Value::Null),
                        "retired_by_revision": r.get("retired_by_revision").cloned().unwrap_or(Value::Null),
                        "initial_pending_scope": r.get("initial_pending_scope").cloned().unwrap_or(Value::Null),
                        "resolved_scope": r.get("resolved_scope").cloned().unwrap_or(Value::Null),
                        "attributed_responsibility_ids": r.get("attributed_responsibility_ids").cloned().unwrap_or(Value::Null)
                    }),
                );
            }
        }
    }
    map
}

struct LiveCapPolicy {
    policy_id: String,
    policy_version: String,
    amount: i64,
    currency: String,
    json: Value,
}

fn extract_live_cap_policy(
    config: Option<&Config>,
    image: &Value,
) -> Result<Option<LiveCapPolicy>, String> {
    let Some(fin) = image.get("finance") else {
        return Ok(None);
    };
    let Some(resps) = fin.get("responsibilities").and_then(Value::as_array) else {
        return Ok(None);
    };
    let Some(baseline) = resps.iter().find(|r| r["owner"] == "E:baseline") else {
        return Ok(None);
    };
    let base_policy = &baseline["policy"];
    let currency = required(base_policy, "currency")?.to_owned();
    let finance_input_sha256 = config
        .and_then(|cfg| cfg.manifest.get("finance"))
        .and_then(|f| f.get("input_sha256"))
        .and_then(Value::as_str)
        .or_else(|| {
            image
                .get(CONTRACT_FIELD)
                .and_then(|fx| fx.get("cap_policy"))
                .and_then(|cp| cp.get("finance_input_sha256"))
                .and_then(Value::as_str)
        })
        .unwrap_or("")
        .to_owned();
    if let Some(cap_pol) = fin.get("cap_policy").filter(|v| !v.is_null()) {
        let amount = nonnegative(required(cap_pol, "cap")?, "active cap_policy cap")?;
        let policy_id = required(cap_pol, "policy_id")?.to_owned();
        let policy_version = required(cap_pol, "policy_version")?.to_owned();
        Ok(Some(LiveCapPolicy {
            policy_id: policy_id.clone(),
            policy_version: policy_version.clone(),
            amount,
            currency: currency.clone(),
            json: json!({
                "source": "finance.cap_policy",
                "policy_id": policy_id,
                "policy_version": policy_version,
                "cap": cap_pol["cap"],
                "currency": currency,
                "money_unit": base_policy["money_unit"],
                "quantum": base_policy["quantum"],
                "allocation_policy_id": base_policy["allocation_policy_id"],
                "model": base_policy["model"],
                "valid_through_ns": cap_pol["valid_through_ns"],
                "activation_id": cap_pol.get("activation_id").cloned().unwrap_or(Value::Null),
                "finance_input_sha256": finance_input_sha256
            }),
        }))
    } else {
        let amount = nonnegative(required(base_policy, "cap")?, "finance policy cap")?;
        let policy_id = required(base_policy, "policy_id")?.to_owned();
        let policy_version = "1".to_owned();
        Ok(Some(LiveCapPolicy {
            policy_id: policy_id.clone(),
            policy_version: policy_version.clone(),
            amount,
            currency: currency.clone(),
            json: json!({
                "source": "finance.policy",
                "policy_id": policy_id,
                "policy_version": policy_version,
                "cap": base_policy["cap"],
                "currency": currency,
                "money_unit": base_policy["money_unit"],
                "quantum": base_policy["quantum"],
                "allocation_policy_id": base_policy["allocation_policy_id"],
                "model": base_policy["model"],
                "valid_through_ns": base_policy["valid_through_ns"],
                "activation_id": Value::Null,
                "finance_input_sha256": finance_input_sha256
            }),
        }))
    }
}

struct DerivedFxState {
    baseline_imported: bool,
    live_cap: Option<LiveCapPolicy>,
    missing_foreign_ids: Vec<String>,
    initial_foreign_responsibilities_complete: bool,
    foreign_subtotal_i64: Option<i64>,
    evaluated_total_i64: Option<i64>,
    within_cap: Option<bool>,
    gate_status: &'static str,
    json: Value,
}

/// 纯函数：从 E 实际持久 `image["finance"]`、`boundary`、`recorded`、`pending` 与已核覆盖推导完整 FX 估值态。
fn derive_state(
    config: Option<&Config>,
    image: &Value,
    boundary: &DeclaredBoundary,
    recorded: &[Value],
    pending: &[Value],
    coverages: &BTreeMap<String, Value>,
) -> Result<DerivedFxState, String> {
    let live_cap = extract_live_cap_policy(config, image)?;
    let baseline_imported = live_cap.is_some();
    let cap_currency = live_cap
        .as_ref()
        .map(|c| c.currency.as_str())
        .unwrap_or("TEST-CASH");

    // 1. 投影 E 实际导入/保留的现金责任（基线 + Reserve 真实 grant）。
    let mut cash_rows = Vec::new();
    let mut cash_subtotal: i128 = 0;
    let mut grant_ids = Vec::new();
    let mut all_responsibility_ids = Vec::new();
    let mut common_cap_owners = BTreeSet::new();
    if let Some(resps) = image
        .get("finance")
        .and_then(|f| f.get("responsibilities"))
        .and_then(Value::as_array)
    {
        for r in resps {
            let rid = required(r, "responsibility_id")?.to_owned();
            let owner = required(r, "owner")?.to_owned();
            let amount = nonnegative(required(r, "amount")?, "cash responsibility amount")?;
            cash_subtotal = cash_subtotal
                .checked_add(i128::from(amount))
                .ok_or("InvalidDomain：现金责任汇总溢出")?;
            all_responsibility_ids.push(rid.clone());
            common_cap_owners.insert(owner.clone());
            if let Some(grant) = r.get("grant").filter(|g| g.is_object()) {
                let gid = required(grant, "grant_id")?.to_owned();
                grant_ids.push(gid.clone());
                cash_rows.push(json!({
                    "responsibility_id": rid,
                    "owner": owner,
                    "kind": "ReservedGrant",
                    "amount": amount.to_string(),
                    "currency": cap_currency,
                    "source_ref": Value::Null,
                    "grant_id": gid,
                    "decision_id": grant["decision_id"],
                    "plan_hash": grant["plan_hash"],
                    "reserved_seq": grant["reserved_seq"]
                }));
            } else {
                cash_rows.push(json!({
                    "responsibility_id": rid,
                    "owner": owner,
                    "kind": "ImportedBaseline",
                    "amount": amount.to_string(),
                    "currency": cap_currency,
                    "source_ref": r.get("source").and_then(|s| s.get("source_ref")).cloned().unwrap_or(Value::Null),
                    "grant_id": Value::Null,
                    "decision_id": Value::Null,
                    "plan_hash": Value::Null,
                    "reserved_seq": Value::Null
                }));
            }
        }
    }

    // 2. 读取正式导入的 TestOnly 外币义务，并与共同界声明核对期初完整性。
    let foreign_obs = parse_foreign_responsibilities(image)?;
    let mut imported_foreign_ids = Vec::new();
    let mut imported_foreign_set = BTreeSet::new();
    for ob in &foreign_obs {
        all_responsibility_ids.push(ob.responsibility_id.clone());
        imported_foreign_ids.push(ob.responsibility_id.clone());
        imported_foreign_set.insert(ob.responsibility_id.as_str());
        common_cap_owners.insert(ob.owner.clone());
    }
    let missing_foreign_ids: Vec<String> = boundary
        .declared_foreign_responsibility_ids
        .iter()
        .filter(|id| !imported_foreign_set.contains(id.as_str()))
        .cloned()
        .collect();
    let initial_foreign_responsibilities_complete = missing_foreign_ids.is_empty();

    // 3. 解析所有已接纳的 FX 报价原件，并按 (namespace, epoch, instrument, event_id) 组链。
    let mut quotes = Vec::new();
    for rec in recorded {
        if let Some(q) = parse_quote_record(rec)? {
            quotes.push(q);
        }
    }
    let pending_by_key: BTreeMap<String, &Value> = pending
        .iter()
        .filter_map(|p| p["fact_key"].as_str().map(|k| (k.to_owned(), p)))
        .collect();

    type ChainKey = (String, String, String, String);
    let mut chains_map: BTreeMap<ChainKey, Vec<ParsedQuote>> = BTreeMap::new();
    for q in &quotes {
        chains_map
            .entry((
                q.source_namespace.clone(),
                q.source_epoch.clone(),
                q.instrument.clone(),
                q.event_id.clone(),
            ))
            .or_default()
            .push(q.clone());
    }

    let mut superseded_by: BTreeMap<String, (String, String)> = BTreeMap::new();
    let mut chain_summaries = Vec::new();
    let mut active_by_source_inst: BTreeMap<(String, String, String), Vec<(ParsedQuote, bool)>> =
        BTreeMap::new();
    let mut chain_incomplete = false;
    let mut blocking_reasons = Vec::new();
    let mut active_fact_keys = Vec::new();

    if !initial_foreign_responsibilities_complete {
        blocking_reasons.push(format!(
            "ForeignResponsibilitiesNotImported: missing initial foreign obligation(s) {}",
            missing_foreign_ids.join(",")
        ));
    }

    for ((ns, ep, inst, eid), mut list) in chains_map {
        list.sort_by_key(|q| q.revision_num);
        let mut by_rev: BTreeMap<String, &ParsedQuote> = BTreeMap::new();
        for q in &list {
            by_rev.insert(q.revision.clone(), q);
        }
        let mut seen_supersedes: BTreeMap<String, String> = BTreeMap::new();
        let mut missing_revisions = Vec::new();
        for q in &list {
            if let Some(prev) = &q.supersedes_revision {
                if let Some(other) = seen_supersedes.insert(prev.clone(), q.revision.clone()) {
                    return Err(format!(
                        "IdentityConflict：FX 替代链 {eid} 分叉（修订 {} 与 {} 均声称替代修订 {}）",
                        other, q.revision, prev
                    ));
                }
                if let Some(prev_q) = by_rev.get(prev) {
                    superseded_by.insert(
                        prev_q.fact_key.clone(),
                        (q.revision.clone(), q.fact_key.clone()),
                    );
                } else {
                    missing_revisions.push(prev.clone());
                }
            }
        }
        let complete = missing_revisions.is_empty();
        if !complete {
            chain_incomplete = true;
            blocking_reasons.push(format!(
                "IncompleteSupersessionChain: {ns}/{ep}/{inst}/{eid} missing predecessor revision(s) {}",
                missing_revisions.join(",")
            ));
        }
        let active = list.last().unwrap().clone();
        active_fact_keys.push(active.fact_key.clone());
        active_by_source_inst
            .entry((ns.clone(), ep.clone(), inst.clone()))
            .or_default()
            .push((active.clone(), complete));
        chain_summaries.push(json!({
            "chain_id": format!("{ns}|{ep}|{inst}|{eid}"),
            "source_namespace": ns,
            "source_epoch": ep,
            "instrument": inst,
            "event_id": eid,
            "ordered_revisions": list.iter().map(|q| q.revision.clone()).collect::<Vec<_>>(),
            "active_revision": active.revision,
            "active_fact_key": active.fact_key,
            "complete": complete,
            "missing_revisions": missing_revisions
        }));
    }

    // 4. 构建每版修订行，保留全部原件元数据、替代链与归属/核清/退役状态。
    let mut revision_rows = Vec::new();
    let mut active_pending_fact_keys = Vec::new();
    let mut has_unmatched_quote = false;
    let mut has_superseded_covered = false;
    let mut has_uncovered_active = false;
    let mut has_superseded_pending = false;

    for q in &quotes {
        let matched_obs: Vec<&ForeignObligationRow> = foreign_obs
            .iter()
            .filter(|ob| quote_matches_foreign(q, ob))
            .collect();
        let matched_ids: Vec<String> = matched_obs
            .iter()
            .map(|ob| ob.responsibility_id.clone())
            .collect();
        let is_attributed = !matched_ids.is_empty();
        let effective_scope = if is_attributed {
            format!("E:fx:{}", q.instrument)
        } else {
            "account:*".to_owned()
        };
        let attribution_status = if is_attributed {
            "Attributed"
        } else {
            "Unattributed"
        };
        let pending_entry = pending_by_key.get(&q.fact_key).copied();
        let is_pending = pending_entry.is_some();
        if is_pending {
            active_pending_fact_keys.push(q.fact_key.clone());
        }
        // 只在当前切面仍无持久外币责任归属时判为未归属；先于责任到达、后来归属获证的报价保留其初始
        // `account:*` 捕获史，同时按当前切面的权威归属允许正式 ResolveEvidence 核清或退役。
        if !is_attributed {
            has_unmatched_quote = true;
            blocking_reasons.push(format!(
                "UnmatchedQuoteScope: {}/{} rev {} cannot be attributed to imported foreign obligations",
                q.instrument, q.event_id, q.revision
            ));
        }
        let sup = superseded_by.get(&q.fact_key);
        let is_active = sup.is_none();
        let cov = coverages.get(&q.fact_key);
        let coverage_status = if is_pending {
            "Pending"
        } else if let Some(c) = cov {
            c.get("status").and_then(Value::as_str).unwrap_or("Covered")
        } else {
            "Uncovered"
        };
        if !is_active && coverage_status == "Covered" {
            has_superseded_covered = true;
        }
        if !is_active && is_pending {
            has_superseded_pending = true;
            blocking_reasons.push(format!(
                "FxQuoteSupersededPending: {} rev {} pending exact retirement",
                q.instrument, q.revision
            ));
        }
        if is_active && (is_pending || coverage_status != "Covered") {
            has_uncovered_active = true;
            blocking_reasons.push(format!(
                "FxQuoteUncovered: {} rev {} pending evidence coverage",
                q.instrument, q.revision
            ));
        }
        let initial_pending_scope = pending_entry
            .and_then(|p| p.get("scope"))
            .cloned()
            .or_else(|| cov.and_then(|c| c.get("initial_pending_scope")).cloned())
            .unwrap_or(Value::Null);
        revision_rows.push(json!({
            "fact_key": q.fact_key,
            "fact_hash": q.fact_hash,
            "raw_sha256": q.raw_sha256,
            "source_namespace": q.source_namespace,
            "source_epoch": q.source_epoch,
            "instrument": q.instrument,
            "event_id": q.event_id,
            "source_coord": q.source_coord,
            "revision": q.revision,
            "supersedes_revision": q.supersedes_revision,
            "supersedes_fact_key": q.supersedes_fact_key,
            "price_numerator": q.price_numerator.to_string(),
            "price_denominator": q.price_denominator.to_string(),
            "base_unit": q.base_unit,
            "quote_unit": q.quote_unit,
            "timestamp": q.timestamp,
            "recorded_seq": q.recorded_seq,
            "status": if is_active { "Active" } else { "Superseded" },
            "active": is_active,
            "superseded_by_revision": sup.map(|(r, _)| r.clone()),
            "superseded_by_fact_key": sup.map(|(_, k)| k.clone()),
            "coverage_status": coverage_status,
            "evidence_id": cov.and_then(|c| c.get("evidence_id")).cloned().unwrap_or(Value::Null),
            "evidence_hash": cov.and_then(|c| c.get("evidence_hash")).cloned().unwrap_or(Value::Null),
            "retired_by_fact_key": cov.and_then(|c| c.get("retired_by_fact_key")).cloned().unwrap_or(Value::Null),
            "retired_by_revision": cov.and_then(|c| c.get("retired_by_revision")).cloned().unwrap_or(Value::Null),
            "initial_pending_scope": initial_pending_scope,
            "effective_scope": effective_scope,
            "attribution_status": attribution_status,
            "resolved_scope": cov.and_then(|c| c.get("resolved_scope")).cloned().unwrap_or(Value::Null),
            "attributed_responsibility_ids": cov.and_then(|c| c.get("attributed_responsibility_ids")).cloned().unwrap_or(Value::Null),
            "matched_responsibility_ids": matched_ids
        }));
    }

    // 5. 逐笔精确估值已导入的外币义务（无截断整数有理数算术）。
    let mut foreign_rows = Vec::new();
    let mut foreign_subtotal: i128 = 0;
    let mut all_foreign_valued = true;
    let mut has_no_quote = false;
    let mut has_unverifiable_ob = false;
    let mut affected_ids = Vec::new();
    let mut affected_owners = BTreeSet::new();
    let mut instruments = BTreeSet::new();

    for ob in &foreign_obs {
        affected_ids.push(ob.responsibility_id.clone());
        affected_owners.insert(ob.owner.clone());
        instruments.insert(ob.valuation_instrument.clone());
        let key = (
            ob.quote_source_namespace.clone(),
            ob.quote_source_epoch.clone(),
            ob.valuation_instrument.clone(),
        );
        let candidates = active_by_source_inst.get(&key);
        match candidates.map(Vec::as_slice) {
            None | Some([]) => {
                all_foreign_valued = false;
                has_no_quote = true;
                blocking_reasons.push(format!(
                    "NoQuote: {} ({}) awaiting market quote for {}",
                    ob.responsibility_id, ob.owner, ob.valuation_instrument
                ));
                foreign_rows.push(foreign_row_json(ob, None, None, "NoQuote", None));
            }
            Some([(active_q, complete)]) => {
                let cov = coverages.get(&active_q.fact_key);
                if !*complete {
                    all_foreign_valued = false;
                    has_unverifiable_ob = true;
                    foreign_rows.push(foreign_row_json(
                        ob,
                        Some(active_q),
                        None,
                        "IncompleteSupersessionChain",
                        cov,
                    ));
                } else {
                    match exact_convert(
                        ob.quantity,
                        active_q.price_numerator,
                        active_q.price_denominator,
                    ) {
                        Ok(val) => {
                            foreign_subtotal = foreign_subtotal
                                .checked_add(i128::from(val))
                                .ok_or("InvalidDomain：外币估值汇总溢出")?;
                            foreign_rows.push(foreign_row_json(
                                ob,
                                Some(active_q),
                                Some(val),
                                "Evaluated",
                                cov,
                            ));
                        }
                        Err(reason) => {
                            all_foreign_valued = false;
                            has_unverifiable_ob = true;
                            blocking_reasons.push(format!(
                                "UnverifiableConversion: {} ({reason})",
                                ob.responsibility_id
                            ));
                            foreign_rows.push(foreign_row_json(
                                ob,
                                Some(active_q),
                                None,
                                "UnverifiableConversion",
                                cov,
                            ));
                        }
                    }
                }
            }
            Some(_) => {
                all_foreign_valued = false;
                has_unverifiable_ob = true;
                blocking_reasons.push(format!(
                    "AmbiguousActiveQuotes: {} has multiple concurrent quote chains for {}",
                    ob.responsibility_id, ob.valuation_instrument
                ));
                foreign_rows.push(foreign_row_json(
                    ob,
                    None,
                    None,
                    "AmbiguousActiveQuotes",
                    None,
                ));
            }
        }
    }

    // 6. 合成总敞口与封闸裁决（严格基于 E 实际财务基线/保留/完整外币义务与生效 cap）。
    if !baseline_imported {
        blocking_reasons.push(
            "FinanceBaselineNotImported: awaiting ImportResponsibility before FX cap evaluation"
                .into(),
        );
    }

    let foreign_subtotal_i64: Option<i64> =
        if initial_foreign_responsibilities_complete && all_foreign_valued {
            i64::try_from(foreign_subtotal).ok()
        } else {
            None
        };
    let cash_subtotal_i64 = i64::try_from(cash_subtotal).ok();
    let evaluated_total_i64: Option<i64> =
        if baseline_imported && initial_foreign_responsibilities_complete {
            match (cash_subtotal_i64, foreign_subtotal_i64) {
                (Some(c), Some(f)) => c.checked_add(f),
                _ => None,
            }
        } else {
            None
        };

    let (within_cap, headroom_or_excess) = match (&live_cap, evaluated_total_i64) {
        (Some(cap), Some(total)) => {
            let diff = i128::from(cap.amount) - i128::from(total);
            let ok = total <= cap.amount;
            if !ok {
                blocking_reasons.push(format!(
                    "FxQuoteCapExceeded: evaluated_total={total} {} > cap={} {}",
                    cap.currency, cap.amount, cap.currency
                ));
            }
            (Some(ok), Some(diff.to_string()))
        }
        _ => (None, None),
    };

    let evidence_coverage_status = if baseline_imported
        && initial_foreign_responsibilities_complete
        && !has_uncovered_active
        && active_pending_fact_keys.is_empty()
        && !has_no_quote
        && !has_unmatched_quote
    {
        "Covered"
    } else if !has_uncovered_active && has_superseded_pending {
        "PendingRetirement"
    } else if has_uncovered_active && has_superseded_covered {
        "SupersededAndUncovered"
    } else {
        "Uncovered"
    };

    let gate_status = if !baseline_imported
        || !initial_foreign_responsibilities_complete
        || has_unmatched_quote
        || chain_incomplete
        || has_unverifiable_ob
    {
        "BlockedUnverifiable"
    } else if has_no_quote {
        "BlockedNoQuote"
    } else if within_cap == Some(false) {
        "BlockedExceedsCap"
    } else if within_cap.is_none() {
        "BlockedUnverifiable"
    } else if !active_pending_fact_keys.is_empty() || has_uncovered_active {
        "BlockedPendingEvidence"
    } else {
        "AdmissibleWithinCap"
    };
    let admissible = gate_status == "AdmissibleWithinCap";

    let boundary_json = json!({
        "domain_id": "E",
        "obligation_input_sha256": boundary.obligation_input_sha256,
        "source_id": boundary.source_id,
        "source_epoch": boundary.source_epoch,
        "declared_foreign_responsibility_ids": boundary.declared_foreign_responsibility_ids,
        "imported_foreign_responsibility_ids": imported_foreign_ids,
        "missing_foreign_responsibility_ids": missing_foreign_ids,
        "initial_foreign_responsibilities_complete": initial_foreign_responsibilities_complete
    });

    let json = json!({
        "schema_revision": SCHEMA,
        "kind": "TestOnly",
        "baseline_imported": baseline_imported,
        "initial_foreign_responsibilities_complete": initial_foreign_responsibilities_complete,
        "boundary": boundary_json,
        "cap_policy": live_cap.as_ref().map(|c| c.json.clone()).unwrap_or(Value::Null),
        "cash_responsibilities": cash_rows,
        "foreign_responsibilities": foreign_rows,
        "revisions": revision_rows,
        "supersession_chains": chain_summaries,
        "applicable_scope": {
            "domain_id": "E",
            "common_cap_policy_id": live_cap.as_ref().map(|c| c.policy_id.clone()),
            "common_cap_policy_version": live_cap.as_ref().map(|c| c.policy_version.clone()),
            "cap_currency": cap_currency,
            "declared_foreign_responsibility_ids": boundary.declared_foreign_responsibility_ids,
            "imported_foreign_responsibility_ids": imported_foreign_ids,
            "missing_foreign_responsibility_ids": missing_foreign_ids,
            "initial_foreign_responsibilities_complete": initial_foreign_responsibilities_complete,
            "instruments": instruments.into_iter().collect::<Vec<_>>(),
            "all_responsibility_ids": all_responsibility_ids,
            "affected_responsibility_ids": affected_ids,
            "affected_owners": affected_owners.into_iter().collect::<Vec<_>>(),
            "common_cap_owners": common_cap_owners.into_iter().collect::<Vec<_>>(),
            "grant_ids": grant_ids
        },
        "summary": {
            "currency": cap_currency,
            "cap": live_cap.as_ref().map(|c| c.amount.to_string()),
            "cash_subtotal": cash_subtotal_i64.map(|v| v.to_string()),
            "foreign_evaluated_subtotal": foreign_subtotal_i64.map(|v| v.to_string()),
            "evaluated_total": evaluated_total_i64.map(|v| v.to_string()),
            "within_cap": within_cap,
            "headroom_or_excess": headroom_or_excess,
            "evidence_coverage_status": evidence_coverage_status,
            "gate_status": gate_status,
            "admissible": admissible,
            "active_fact_keys": active_fact_keys,
            "active_pending_fact_keys": active_pending_fact_keys,
            "blocking_reasons": blocking_reasons
        }
    });

    Ok(DerivedFxState {
        baseline_imported,
        live_cap,
        missing_foreign_ids,
        initial_foreign_responsibilities_complete,
        foreign_subtotal_i64,
        evaluated_total_i64,
        within_cap,
        gate_status,
        json,
    })
}

fn derive_state_from_image(
    config: Option<&Config>,
    image: &Value,
    recorded: &[Value],
    pending: &[Value],
    coverages: &BTreeMap<String, Value>,
) -> Result<DerivedFxState, String> {
    let boundary = extract_boundary(image, config)?;
    derive_state(config, image, &boundary, recorded, pending, coverages)
}

fn build_state_from_image(
    config: &Config,
    image: &Value,
    recorded: &[Value],
    pending: &[Value],
    coverages: &BTreeMap<String, Value>,
) -> Result<Value, String> {
    Ok(derive_state_from_image(Some(config), image, recorded, pending, coverages)?.json)
}

fn foreign_row_json(
    ob: &ForeignObligationRow,
    quote: Option<&ParsedQuote>,
    evaluated: Option<i64>,
    status: &str,
    coverage: Option<&Value>,
) -> Value {
    json!({
        "responsibility_id": ob.responsibility_id,
        "owner": ob.owner,
        "account_ref": ob.account_ref,
        "source_ref": ob.source_ref,
        "input_sha256": ob.input_sha256,
        "imported_seq": ob.imported_seq,
        "quantity": ob.quantity.to_string(),
        "unit": ob.unit,
        "valuation_instrument": ob.valuation_instrument,
        "quote_source": {
            "source_namespace": ob.quote_source_namespace,
            "source_epoch": ob.quote_source_epoch
        },
        "applied_fact_key": quote.map(|q| q.fact_key.clone()),
        "applied_fact_hash": quote.map(|q| q.fact_hash.clone()),
        "applied_revision": quote.map(|q| q.revision.clone()),
        "applied_source_coord": quote.map(|q| q.source_coord.clone()),
        "applied_price_numerator": quote.map(|q| q.price_numerator.to_string()),
        "applied_price_denominator": quote.map(|q| q.price_denominator.to_string()),
        "evaluated_amount": evaluated.map(|v| v.to_string()),
        "evaluated_unit": quote.map(|q| q.quote_unit.clone()),
        "valuation_status": status,
        "evidence_id": coverage.and_then(|c| c.get("evidence_id")).cloned().unwrap_or(Value::Null),
        "evidence_hash": coverage.and_then(|c| c.get("evidence_hash")).cloned().unwrap_or(Value::Null)
    })
}

fn exact_convert(qty: i64, num: i64, den: i64) -> Result<i64, String> {
    let product = i128::from(qty)
        .checked_mul(i128::from(num))
        .ok_or("overflow")?;
    let den_128 = i128::from(den);
    if product % den_128 != 0 {
        return Err(format!("non-integer rational conversion {qty}*{num}/{den}"));
    }
    i64::try_from(product / den_128).map_err(|_| "overflow".into())
}

/// CaptureExternal 同事务第一步：基于实际已导入的外币义务与财务态生成保守 Pending。
pub(super) fn pending_entry(
    config: &Config,
    previous: &Value,
    record: &Value,
    seq: i64,
) -> Result<Value, String> {
    if !enabled(config) {
        return Err("SchemaUnsupported：未启用 fx-valuation/1 子合同".into());
    }
    let incoming = parse_quote_record(record)?.ok_or("SchemaUnsupported：非 FX 市场报价事件")?;
    let recorded = previous["recorded"]
        .as_array()
        .ok_or("StorageUnavailable：recorded 形状")?;
    let pending = previous["pending"]
        .as_array()
        .ok_or("StorageUnavailable：pending 形状")?;

    // 阻断替代链分叉（双根或两版声称替代同一前驱）。
    let mut existing_chain = Vec::new();
    for rec in recorded {
        if let Some(q) = parse_quote_record(rec)? {
            if q.source_namespace == incoming.source_namespace
                && q.source_epoch == incoming.source_epoch
                && q.instrument == incoming.instrument
                && q.event_id == incoming.event_id
            {
                existing_chain.push(q);
            }
        }
    }
    for q in &existing_chain {
        if q.revision == incoming.revision {
            return Err("IdentityConflict：同源 FX 修订号已存在".into());
        }
        if incoming.supersedes_revision.is_none() && q.supersedes_revision.is_none() {
            return Err("IdentityConflict：同源 FX 替代链不允许两个无前驱根修订".into());
        }
        if incoming.supersedes_revision.is_some()
            && incoming.supersedes_revision == q.supersedes_revision
        {
            return Err(format!(
                "IdentityConflict：FX 替代链分叉（修订 {} 与 {} 均声称替代修订 {}）",
                q.revision,
                incoming.revision,
                incoming.supersedes_revision.as_deref().unwrap_or("")
            ));
        }
    }

    let foreign_obs = parse_foreign_responsibilities(previous)?;
    let matched: Vec<&ForeignObligationRow> = foreign_obs
        .iter()
        .filter(|ob| quote_matches_foreign(&incoming, ob))
        .collect();

    let (scope, reason) = if matched.is_empty() {
        (
            json!("account:*"),
            json!({
                "kind": "FxQuoteUnmatchedObligation",
                "slot": VALUATION_GATE_SLOT,
                "instrument": incoming.instrument,
                "event_id": incoming.event_id,
                "revision": incoming.revision,
                "source_coord": incoming.source_coord
            }),
        )
    } else if let Some(prev_rev) = &incoming.supersedes_revision {
        let prev_present = existing_chain.iter().any(|q| q.revision == *prev_rev);
        if !prev_present {
            (
                json!(format!("E:fx:{}", incoming.instrument)),
                json!({
                    "kind": "AwaitingDependency",
                    "on": incoming.supersedes_fact_key,
                    "missing_revision": prev_rev,
                    "instrument": incoming.instrument,
                    "event_id": incoming.event_id,
                    "revision": incoming.revision
                }),
            )
        } else {
            let mut next_recorded = recorded.clone();
            next_recorded.push(record.clone());
            let mut next_pending = pending.clone();
            next_pending.push(json!({"fact_key": record["fact_key"], "scope": format!("E:fx:{}", incoming.instrument)}));
            let state = build_state_from_image(
                config,
                previous,
                &next_recorded,
                &next_pending,
                &extract_coverages(previous),
            )?;
            (
                json!(format!("E:fx:{}", incoming.instrument)),
                classify_quote_pending_reason(&incoming, &state),
            )
        }
    } else {
        let mut next_recorded = recorded.clone();
        next_recorded.push(record.clone());
        let mut next_pending = pending.clone();
        next_pending.push(json!({"fact_key": record["fact_key"], "scope": format!("E:fx:{}", incoming.instrument)}));
        let state = build_state_from_image(
            config,
            previous,
            &next_recorded,
            &next_pending,
            &extract_coverages(previous),
        )?;
        (
            json!(format!("E:fx:{}", incoming.instrument)),
            classify_quote_pending_reason(&incoming, &state),
        )
    };

    Ok(json!({
        "fact_key": record["fact_key"],
        "token": record["token"],
        "target_domain": record["target_domain"],
        "status": "Pending",
        "reason": reason,
        "scope": scope,
        "first_known_ns": record["first_known_ns"],
        "recorded_seq": seq.to_string()
    }))
}

fn classify_quote_pending_reason(incoming: &ParsedQuote, state: &Value) -> Value {
    let summary = &state["summary"];
    match summary["within_cap"].as_bool() {
        Some(true) => json!({
            "kind": "FxQuotePending",
            "instrument": incoming.instrument,
            "event_id": incoming.event_id,
            "revision": incoming.revision,
            "supersedes_revision": incoming.supersedes_revision,
            "supersedes_fact_key": incoming.supersedes_fact_key,
            "evaluated_total": summary["evaluated_total"],
            "cap": summary["cap"],
            "currency": summary["currency"]
        }),
        Some(false) => json!({
            "kind": "FxQuoteCapExceeded",
            "slot": CAP_GATE_SLOT,
            "instrument": incoming.instrument,
            "event_id": incoming.event_id,
            "revision": incoming.revision,
            "supersedes_revision": incoming.supersedes_revision,
            "supersedes_fact_key": incoming.supersedes_fact_key,
            "evaluated_total": summary["evaluated_total"],
            "cap": summary["cap"],
            "currency": summary["currency"]
        }),
        None => json!({
            "kind": "FxQuoteUnverifiable",
            "slot": VALUATION_GATE_SLOT,
            "instrument": incoming.instrument,
            "event_id": incoming.event_id,
            "revision": incoming.revision,
            "supersedes_revision": incoming.supersedes_revision,
            "supersedes_fact_key": incoming.supersedes_fact_key,
            "blocking_reasons": summary["blocking_reasons"]
        }),
    }
}

/// CaptureExternal 同事务第二步：更新持久 `image["fx_valuation"]`。
pub(super) fn apply_capture(
    config: &Config,
    image: &mut Value,
    record: &Value,
) -> Result<(), String> {
    if config.domain != "E" || !is_fx_quote_event(&record["event"]) {
        return Ok(());
    }
    refresh_from_finance(config, image)
}

/// 任一财务状态变化（`ImportResponsibility`、`ImportFxResponsibility`、`Reserve`、`ActivateCapPolicy`）
/// 或行情捕获后，在同一事务内从 `image["finance"]` + `recorded` + `pending` 同步重算 `image["fx_valuation"]`。
pub(super) fn refresh_from_finance(config: &Config, image: &mut Value) -> Result<(), String> {
    if config.domain != "E" || !enabled(config) {
        return Ok(());
    }
    let recorded = image["recorded"]
        .as_array()
        .ok_or("StorageUnavailable：recorded 形状")?
        .clone();
    let pending = image["pending"]
        .as_array()
        .ok_or("StorageUnavailable：pending 形状")?
        .clone();
    let coverages = extract_coverages(image);
    image[CONTRACT_FIELD] = build_state_from_image(config, image, &recorded, &pending, &coverages)?;
    Ok(())
}

/// ResolveEvidence 校验 FX 报价核清与被替代旧版 token 的精确退役：
/// - 同一切面上按 E 已持久的 `finance.foreign_responsibilities` 核定本条报价的真实归属；
///   若仍无归属证明（含真未知的 `account:*`），严格拒绝；若先前以 `account:*` 捕获、现归属已获证，
///   仅重新核定这一已证明项的有效影响范围并保留历史 cut 原貌。
/// - 活动头修订：要求基线已导入、共同界期初外币责任已完整导入、替代链完整、且基于真实财务责任的当前总敞口 `<= cap`。
/// - 同替代链中被替代的旧版修订：
///   - 若该链活动头尚未 `Covered` 且不在本批 `ResolveEvidence` 中有效覆盖，拒绝（旧证据不能核清新修订）。
///   - 若该链活动头已 `Covered` 或在本批同核清、替代链完整、当前总敞口 `<= cap` 且前沿覆盖活动头，
///     允许将本条旧版 token 精确退役为 `RetiredBySupersession`（仅移出本条 token，不动其他责任/token）。
pub(super) fn validate_resolve_fx_quote(
    config: &Config,
    previous: &Value,
    fact: &Value,
    pending: &Value,
    payload: &Value,
    batch_fact_keys: &[String],
) -> Result<Value, String> {
    if !enabled(config) {
        return Err("SchemaUnsupported：未启用 fx-valuation/1 子合同".into());
    }
    let matched_obs = matched_foreign_obligations(previous, fact)?;
    if matched_obs.is_empty() {
        return Err("MissingDependency：账户范围 Pending 尚缺归属与影响范围证明".into());
    }
    let attributed_ids: Vec<String> = matched_obs
        .iter()
        .map(|ob| ob.responsibility_id.clone())
        .collect();
    let instrument = required(&fact["event"]["quote"], "instrument")?;
    let resolved_scope = format!("E:fx:{instrument}");
    let initial_pending_scope = pending["scope"].clone();

    let recorded = previous["recorded"]
        .as_array()
        .ok_or("StorageUnavailable：recorded 形状")?;
    let all_pending = previous["pending"]
        .as_array()
        .ok_or("StorageUnavailable：pending 形状")?;
    let coverages = extract_coverages(previous);
    let derived =
        derive_state_from_image(Some(config), previous, recorded, all_pending, &coverages)?;

    let fk = required(fact, "fact_key")?;
    let fx = &derived.json;
    let revs = fx["revisions"]
        .as_array()
        .ok_or("StorageUnavailable：fx_valuation.revisions 形状")?;
    let rev = revs
        .iter()
        .find(|r| r["fact_key"] == fk)
        .ok_or("StorageUnavailable：fx_valuation 缺失对应报价修订")?;
    let chain = fx["supersession_chains"]
        .as_array()
        .and_then(|a| {
            a.iter().find(|c| {
                c["source_namespace"] == rev["source_namespace"]
                    && c["source_epoch"] == rev["source_epoch"]
                    && c["instrument"] == rev["instrument"]
                    && c["event_id"] == rev["event_id"]
            })
        })
        .ok_or("StorageUnavailable：fx_valuation 缺失对应替代链")?;
    let evidence_hash = hash(&super::tb03c_e::evidence_body(payload));

    if let Some(next_rev) = rev["superseded_by_revision"].as_str() {
        let active_fk = required(chain, "active_fact_key")?;
        let active_rev_num = required(chain, "active_revision")?;
        let active_rev = revs
            .iter()
            .find(|r| r["fact_key"] == active_fk)
            .ok_or("StorageUnavailable：替代链活动头缺失")?;
        let active_already_covered = active_rev["coverage_status"] == "Covered";
        let active_in_batch = batch_fact_keys.iter().any(|k| k == active_fk);
        if !active_already_covered && !active_in_batch {
            return Err(format!(
                "IdentityConflict：FX 报价修订 {} 已被修订 {} 替代，旧证据不能核清当前状态",
                rev["revision"].as_str().unwrap_or(""),
                next_rev
            ));
        }
        // 前沿也必须覆盖同链活动头坐标，防止旧前沿退役新替代链遗留 token。
        let cursor = nonnegative(required(&payload["frontier"], "cursor")?, "frontier cursor")?;
        let active_coord = nonnegative(
            required(active_rev, "source_coord")?,
            "active revision source_coord",
        )?;
        if payload["frontier"]["source_namespace"] != active_rev["source_namespace"]
            || payload["frontier"]["source_epoch"] != active_rev["source_epoch"]
            || cursor < active_coord
        {
            return Err("MissingDependency：退役证据前沿未到达同链活动修订".into());
        }
        check_fx_resolvable_now(&derived, rev)?;
        if chain["complete"] != json!(true) {
            return Err("AwaitingDependency：FX 报价替代链缺失前序修订，无法退役旧 token".into());
        }
        return Ok(json!({
            "status": "RetiredBySupersession",
            "evidence_id": payload["evidence_id"],
            "evidence_hash": evidence_hash,
            "frontier": payload["frontier"],
            "dependency_version": payload["dependency_version"],
            "retired_by_fact_key": active_fk,
            "retired_by_revision": active_rev_num,
            "initial_pending_scope": initial_pending_scope,
            "resolved_scope": resolved_scope,
            "attributed_responsibility_ids": attributed_ids
        }));
    }

    if chain["complete"] != json!(true) {
        return Err("AwaitingDependency：FX 报价替代链缺失前序修订，无法核清".into());
    }
    check_fx_resolvable_now(&derived, rev)?;
    Ok(json!({
        "status": "Covered",
        "evidence_id": payload["evidence_id"],
        "evidence_hash": evidence_hash,
        "frontier": payload["frontier"],
        "dependency_version": payload["dependency_version"],
        "retired_by_fact_key": Value::Null,
        "retired_by_revision": Value::Null,
        "initial_pending_scope": initial_pending_scope,
        "resolved_scope": resolved_scope,
        "attributed_responsibility_ids": attributed_ids
    }))
}

fn check_fx_resolvable_now(derived: &DerivedFxState, rev: &Value) -> Result<(), String> {
    if !derived.baseline_imported {
        return Err("MissingDependency：既有财务责任尚未规范导入 E，不能核清 FX 报价".into());
    }
    if !derived.initial_foreign_responsibilities_complete {
        return Err(format!(
            "MissingDependency：适用共同界的期初外币责任尚未完整导入 E（缺少 {}），不能核清 FX 报价",
            derived.missing_foreign_ids.join(",")
        ));
    }
    match derived.within_cap {
        None => Err("MissingDependency：FX 外币义务尚不可精确核验，不能放行".into()),
        Some(false) => {
            let cap = derived
                .live_cap
                .as_ref()
                .map(|c| (c.amount.to_string(), c.currency.as_str()))
                .unwrap_or_else(|| ("?".into(), "?"));
            let total = derived
                .evaluated_total_i64
                .map(|v| v.to_string())
                .unwrap_or_else(|| "?".into());
            Err(format!(
                "AwaitingPolicy：{CAP_GATE_SLOT}；FX 报价修订 {} 评估总敞口 {} {} 超过上限 {} {}，已补录原件不能替代超限放行",
                rev["revision"].as_str().unwrap_or(""),
                total,
                cap.1,
                cap.0,
                cap.1
            ))
        }
        Some(true) => Ok(()),
    }
}

/// ResolveEvidence 同事务刷新 `image["fx_valuation"]`。
pub(super) fn refresh_after_resolve(
    config: &Config,
    next: &mut Value,
    new_coverages: &BTreeMap<String, Value>,
) -> Result<(), String> {
    if config.domain != "E" || new_coverages.is_empty() {
        return Ok(());
    }
    let recorded = next["recorded"]
        .as_array()
        .ok_or("StorageUnavailable：recorded 形状")?
        .clone();
    let pending = next["pending"]
        .as_array()
        .ok_or("StorageUnavailable：pending 形状")?
        .clone();
    let mut coverages = extract_coverages(next);
    for (k, v) in new_coverages {
        coverages.insert(k.clone(), v.clone());
    }
    next[CONTRACT_FIELD] = build_state_from_image(config, next, &recorded, &pending, &coverages)?;
    Ok(())
}

/// 阻止 `finance::Reserve` / `CommitDecision` / `ReleaseExact` 通过基线 `covered_facts` 旁路 FX 报价 Pending。
pub(super) fn forbid_reserve_bypass(pending: &Value) -> Result<(), String> {
    let is_fx_scope = pending["scope"]
        .as_str()
        .is_some_and(|s| s.starts_with("E:fx:"));
    let is_fx_reason = matches!(
        pending["reason"]["kind"].as_str(),
        Some(
            "FxQuotePending"
                | "FxQuoteCapExceeded"
                | "FxQuoteUnverifiable"
                | "FxQuoteUnmatchedObligation"
        )
    ) || pending["reason"]
        .get("instrument")
        .and_then(Value::as_str)
        .is_some();
    if is_fx_scope || is_fx_reason {
        return Err(format!(
            "AwaitingPolicy：{CAP_GATE_SLOT}；FX 报价 Pending（{}）不能由财务基线覆盖旁路清除",
            pending["fact_key"].as_str().unwrap_or("")
        ));
    }
    Ok(())
}

pub(super) enum GateSubject<'a> {
    ReserveSlot {
        slot_id: &'a str,
        policy_id: &'a str,
        cap_currency: &'a str,
    },
    CommitGrant {
        grant_id: &'a str,
        owner: &'a str,
        policy_id: &'a str,
        cap_currency: &'a str,
    },
    ReleaseCommand {
        command_id: &'a str,
        grant_id: &'a str,
        owner: &'a str,
        policy_id: &'a str,
        cap_currency: &'a str,
    },
}

/// 财务授权闸口检查（`Reserve`、`CommitDecision`、`ReleaseExact` 共用）；未启用 fx-valuation/1 时透传。
/// 不信赖旧布尔缓存，直接从同一切面的共同界、生效 policy、成员责任与实际修订重算推导是否放行。
pub(super) fn check_gate(image: &Value, subject: GateSubject<'_>) -> Result<(), String> {
    if image.get(CONTRACT_FIELD).is_none_or(Value::is_null) {
        return Ok(());
    }
    let recorded = image["recorded"]
        .as_array()
        .ok_or("StorageUnavailable：recorded 形状")?;
    let pending = image["pending"]
        .as_array()
        .ok_or("StorageUnavailable：pending 形状")?;
    let coverages = extract_coverages(image);
    let derived = derive_state_from_image(None, image, recorded, pending, &coverages)?;
    check_gate_derived(image, &derived, subject)
}

fn check_gate_derived(
    image: &Value,
    derived: &DerivedFxState,
    subject: GateSubject<'_>,
) -> Result<(), String> {
    let (subject_policy_id, subject_currency) = match subject {
        GateSubject::ReserveSlot {
            slot_id,
            policy_id,
            cap_currency,
        } => {
            if slot_id.is_empty() {
                return Err("InvalidDomain：Reserve 缺少 slot_id".into());
            }
            (policy_id, cap_currency)
        }
        GateSubject::CommitGrant {
            grant_id,
            owner,
            policy_id,
            cap_currency,
        } => {
            verify_grant_member(image, grant_id, owner)?;
            (policy_id, cap_currency)
        }
        GateSubject::ReleaseCommand {
            command_id,
            grant_id,
            owner,
            policy_id,
            cap_currency,
        } => {
            if command_id.is_empty() {
                return Err("InvalidDomain：ReleaseExact 缺少 command_id".into());
            }
            verify_grant_member(image, grant_id, owner)?;
            (policy_id, cap_currency)
        }
    };

    if !derived.baseline_imported {
        return Err("MissingDependency：既有财务责任尚未规范导入 E，拒绝放行".into());
    }
    if let Some(cap) = &derived.live_cap {
        if cap.policy_id != subject_policy_id || cap.currency != subject_currency {
            return Err(format!(
                "IdentityConflict：目标动作所属资金政策（{subject_policy_id}/{subject_currency}）与 E 生效共同界（{}/{}）不符",
                cap.policy_id, cap.currency
            ));
        }
    }
    if !derived.initial_foreign_responsibilities_complete {
        return Err(format!(
            "MissingDependency：适用共同界的期初外币责任尚未完整导入 E（缺少 {}），拒绝放行",
            derived.missing_foreign_ids.join(",")
        ));
    }

    match derived.gate_status {
        "AdmissibleWithinCap" => Ok(()),
        "BlockedExceedsCap" => {
            let cap = derived
                .live_cap
                .as_ref()
                .map(|c| (c.amount.to_string(), c.currency.as_str()))
                .unwrap_or_else(|| ("?".into(), "?"));
            let total = derived
                .evaluated_total_i64
                .map(|v| v.to_string())
                .unwrap_or_else(|| "?".into());
            Err(format!(
                "AwaitingPolicy：{CAP_GATE_SLOT}；FX 评估总敞口 {} {} 超过上限 {} {}，拒绝放行",
                total, cap.1, cap.0, cap.1
            ))
        }
        "BlockedPendingEvidence" => Err(
            "MissingDependency：FX 报价修订或其被替代遗留 token 尚未完成证据核清/退役，拒绝放行"
                .into(),
        ),
        "BlockedNoQuote" => {
            Err("MissingDependency：已导入 FX 外币义务尚缺市场报价，拒绝放行".into())
        }
        other => Err(format!(
            "MissingDependency：FX 估值处于不可核状态（{other}），拒绝放行"
        )),
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct FxBoundQuote {
    pub(super) chain_id: String,
    pub(super) revision: String,
    pub(super) source_coord: String,
    pub(super) supersedes_revision: Option<String>,
    pub(super) price_numerator: String,
    pub(super) price_denominator: String,
    pub(super) raw_sha256: String,
    pub(super) fact_key: String,
    pub(super) evidence_id: String,
    pub(super) evidence_hash: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct FxRetiredQuote {
    pub(super) chain_id: String,
    pub(super) revision: String,
    pub(super) retired_by_revision: String,
    pub(super) evidence_id: String,
    pub(super) evidence_hash: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct FxBoundObligation {
    pub(super) responsibility_id: String,
    pub(super) owner: String,
    pub(super) quantity: String,
    pub(super) unit: String,
    pub(super) valuation_instrument: String,
    pub(super) quote_source_namespace: String,
    pub(super) quote_source_epoch: String,
    pub(super) input_sha256: String,
}

/// #1407 C3 CE-S07：E 在真实 `ReleaseExact` 原子事务内从同一切面重算推导的可核证依赖集合。
/// 绑定具体 E cut、生效 cap 政策、共同界责任、已导入外币义务、实际适用市场修订及退役证据；
/// 不使用全局 `latest`、`admissible` 布尔或静态占位名。
#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct FxReleaseBinding {
    pub(super) e_prev_seq: i64,
    pub(super) e_prev_root: String,
    pub(super) grant_id: String,
    pub(super) grant_owner: String,
    pub(super) grant_amount: String,
    pub(super) policy_id: String,
    pub(super) policy_version: String,
    pub(super) cap_amount: String,
    pub(super) cap_currency: String,
    pub(super) valid_through_ns: String,
    pub(super) cash_subtotal: String,
    pub(super) foreign_subtotal: String,
    pub(super) evaluated_total: String,
    pub(super) boundary_source_id: String,
    pub(super) boundary_source_epoch: String,
    pub(super) boundary_input_sha256: String,
    pub(super) responsibility_refs: Vec<String>,
    pub(super) foreign_obligations: Vec<FxBoundObligation>,
    pub(super) active_quotes: Vec<FxBoundQuote>,
    pub(super) retired_quotes: Vec<FxRetiredQuote>,
}

#[allow(clippy::too_many_arguments)]
pub(super) fn release_binding(
    config: &Config,
    previous: &Value,
    prev_seq: i64,
    prev_root: &str,
    command_id: &str,
    grant_id: &str,
    owner: &str,
    policy_id: &str,
    cap_currency: &str,
) -> Result<FxReleaseBinding, String> {
    if !enabled(config) {
        return Err("SchemaUnsupported：未启用 fx-valuation/1 子合同".into());
    }
    if prev_seq <= 0 || prev_root.is_empty() {
        return Err("StorageUnavailable：ReleaseExact 缺少前序 E 提交切面".into());
    }
    let recorded = previous["recorded"]
        .as_array()
        .ok_or("StorageUnavailable：recorded 形状")?;
    let pending = previous["pending"]
        .as_array()
        .ok_or("StorageUnavailable：pending 形状")?;
    let coverages = extract_coverages(previous);
    let derived = derive_state_from_image(Some(config), previous, recorded, pending, &coverages)?;
    check_gate_derived(
        previous,
        &derived,
        GateSubject::ReleaseCommand {
            command_id,
            grant_id,
            owner,
            policy_id,
            cap_currency,
        },
    )?;
    release_binding_from_fx_json(&derived.json, prev_seq, prev_root, grant_id, owner)
}

#[cfg(test)]
pub(super) fn release_binding_from_query(
    query_reply: &Value,
    grant_id: &str,
    owner: &str,
) -> Result<FxReleaseBinding, String> {
    let prev_seq = positive(
        required(&query_reply["cut"], "commit_seq")?,
        "query commit_seq",
    )?;
    let prev_root = required(&query_reply["cut"], "root_hash")?;
    release_binding_from_fx_json(
        &query_reply[CONTRACT_FIELD],
        prev_seq,
        prev_root,
        grant_id,
        owner,
    )
}

fn release_binding_from_fx_json(
    fx: &Value,
    prev_seq: i64,
    prev_root: &str,
    grant_id: &str,
    owner: &str,
) -> Result<FxReleaseBinding, String> {
    let cap = &fx["cap_policy"];
    if !cap.is_object() {
        return Err("MissingDependency：FX 放行绑定缺少生效 cap 政策".into());
    }
    let boundary = &fx["boundary"];
    let summary = &fx["summary"];
    let cash_rows = fx["cash_responsibilities"]
        .as_array()
        .ok_or("StorageUnavailable：fx_valuation.cash_responsibilities 形状")?;
    let foreign_rows = fx["foreign_responsibilities"]
        .as_array()
        .ok_or("StorageUnavailable：fx_valuation.foreign_responsibilities 形状")?;
    let revision_rows = fx["revisions"]
        .as_array()
        .ok_or("StorageUnavailable：fx_valuation.revisions 形状")?;

    let grant_row = cash_rows
        .iter()
        .find(|r| r["responsibility_id"] == grant_id && r["owner"] == owner)
        .ok_or("MissingDependency：FX 放行绑定未找到对应 grant 责任")?;
    let grant_amount = required(grant_row, "amount")?.to_owned();

    let mut other_resps = BTreeSet::new();
    for r in cash_rows {
        let rid = required(r, "responsibility_id")?;
        if rid != grant_id {
            other_resps.insert(rid.to_owned());
        }
    }
    let mut foreign_obligations = Vec::with_capacity(foreign_rows.len());
    let mut applied_fact_keys = BTreeSet::new();
    for ob in foreign_rows {
        let rid = required(ob, "responsibility_id")?.to_owned();
        if rid != grant_id {
            other_resps.insert(rid.clone());
        }
        if ob["valuation_status"] != "Evaluated" {
            return Err(format!(
                "MissingDependency：外币责任 {rid} 尚未完成精确估值"
            ));
        }
        let applied_fk = required(ob, "applied_fact_key")?.to_owned();
        applied_fact_keys.insert(applied_fk);
        foreign_obligations.push(FxBoundObligation {
            responsibility_id: rid,
            owner: required(ob, "owner")?.to_owned(),
            quantity: required(ob, "quantity")?.to_owned(),
            unit: required(ob, "unit")?.to_owned(),
            valuation_instrument: required(ob, "valuation_instrument")?.to_owned(),
            quote_source_namespace: required(&ob["quote_source"], "source_namespace")?.to_owned(),
            quote_source_epoch: required(&ob["quote_source"], "source_epoch")?.to_owned(),
            input_sha256: required(ob, "input_sha256")?.to_owned(),
        });
    }
    foreign_obligations.sort_by(|a, b| a.responsibility_id.cmp(&b.responsibility_id));

    let mut responsibility_refs = Vec::with_capacity(1 + other_resps.len());
    responsibility_refs.push(grant_id.to_owned());
    responsibility_refs.extend(other_resps);

    let mut active_quotes_by_chain: BTreeMap<String, FxBoundQuote> = BTreeMap::new();
    for fk in &applied_fact_keys {
        let rev = revision_rows
            .iter()
            .find(|r| r["fact_key"].as_str() == Some(fk.as_str()))
            .ok_or("StorageUnavailable：fx_valuation.revisions 缺失已适用报价原件")?;
        if rev["status"] != "Active" || rev["coverage_status"] != "Covered" {
            return Err("MissingDependency：已适用 FX 报价修订未处于 Active+Covered 状态".into());
        }
        let chain_id = format!(
            "{}|{}|{}|{}",
            required(rev, "source_namespace")?,
            required(rev, "source_epoch")?,
            required(rev, "instrument")?,
            required(rev, "event_id")?
        );
        let bound = FxBoundQuote {
            chain_id: chain_id.clone(),
            revision: required(rev, "revision")?.to_owned(),
            source_coord: required(rev, "source_coord")?.to_owned(),
            supersedes_revision: rev
                .get("supersedes_revision")
                .and_then(Value::as_str)
                .map(ToOwned::to_owned),
            price_numerator: required(rev, "price_numerator")?.to_owned(),
            price_denominator: required(rev, "price_denominator")?.to_owned(),
            raw_sha256: required(rev, "raw_sha256")?.to_owned(),
            fact_key: fk.clone(),
            evidence_id: required(rev, "evidence_id")?.to_owned(),
            evidence_hash: required(rev, "evidence_hash")?.to_owned(),
        };
        active_quotes_by_chain.insert(chain_id, bound);
    }

    let participating_chains: BTreeSet<String> = active_quotes_by_chain.keys().cloned().collect();
    let mut retired_quotes: Vec<(String, i64, FxRetiredQuote)> = Vec::new();
    for rev in revision_rows {
        if rev["coverage_status"] != "RetiredBySupersession" {
            continue;
        }
        let chain_id = format!(
            "{}|{}|{}|{}",
            required(rev, "source_namespace")?,
            required(rev, "source_epoch")?,
            required(rev, "instrument")?,
            required(rev, "event_id")?
        );
        if !participating_chains.contains(&chain_id) {
            continue;
        }
        let revision = required(rev, "revision")?.to_owned();
        let rev_num = positive(&revision, "retired revision")?;
        retired_quotes.push((
            chain_id.clone(),
            rev_num,
            FxRetiredQuote {
                chain_id,
                revision,
                retired_by_revision: required(rev, "retired_by_revision")?.to_owned(),
                evidence_id: required(rev, "evidence_id")?.to_owned(),
                evidence_hash: required(rev, "evidence_hash")?.to_owned(),
            },
        ));
    }
    retired_quotes.sort_by(|a, b| a.0.cmp(&b.0).then_with(|| a.1.cmp(&b.1)));

    Ok(FxReleaseBinding {
        e_prev_seq: prev_seq,
        e_prev_root: prev_root.to_owned(),
        grant_id: grant_id.to_owned(),
        grant_owner: owner.to_owned(),
        grant_amount,
        policy_id: required(cap, "policy_id")?.to_owned(),
        policy_version: required(cap, "policy_version")?.to_owned(),
        cap_amount: required(cap, "cap")?.to_owned(),
        cap_currency: required(cap, "currency")?.to_owned(),
        valid_through_ns: required(cap, "valid_through_ns")?.to_owned(),
        cash_subtotal: required(summary, "cash_subtotal")?.to_owned(),
        foreign_subtotal: required(summary, "foreign_evaluated_subtotal")?.to_owned(),
        evaluated_total: required(summary, "evaluated_total")?.to_owned(),
        boundary_source_id: required(boundary, "source_id")?.to_owned(),
        boundary_source_epoch: required(boundary, "source_epoch")?.to_owned(),
        boundary_input_sha256: required(boundary, "obligation_input_sha256")?.to_owned(),
        responsibility_refs,
        foreign_obligations,
        active_quotes: active_quotes_by_chain.into_values().collect(),
        retired_quotes: retired_quotes.into_iter().map(|(_, _, q)| q).collect(),
    })
}

fn verify_grant_member(image: &Value, grant_id: &str, owner: &str) -> Result<(), String> {
    let resps = image
        .get("finance")
        .and_then(|f| f.get("responsibilities"))
        .and_then(Value::as_array)
        .ok_or("StorageUnavailable：缺少 responsibilities 集合")?;
    let member = resps
        .iter()
        .find(|r| r["responsibility_id"] == grant_id)
        .ok_or("MissingDependency：E 未先保留该 grant 的完整责任")?;
    if member["owner"] != owner {
        return Err("IdentityConflict：grant 归属与当前共同界成员不符".into());
    }
    Ok(())
}

/// 供 `finance::Reserve` 与 `ActivateCapPolicy` 计入外币义务的当前已估值金额；未启用 fx-valuation/1 时为 0。
/// 直接由同一切面的共同界与持久外币责任重算，未完整导入声明的期初外币义务时明确拒绝。
pub(super) fn evaluated_foreign_total(image: &Value) -> Result<i64, String> {
    if image.get(CONTRACT_FIELD).is_none_or(Value::is_null) {
        return Ok(0);
    }
    let recorded = image["recorded"]
        .as_array()
        .ok_or("StorageUnavailable：recorded 形状")?;
    let pending = image["pending"]
        .as_array()
        .ok_or("StorageUnavailable：pending 形状")?;
    let coverages = extract_coverages(image);
    let derived = derive_state_from_image(None, image, recorded, pending, &coverages)?;
    if !derived.initial_foreign_responsibilities_complete {
        return Err(format!(
            "MissingDependency：适用共同界的期初外币责任尚未完整导入 E（缺少 {}），不能按缺漏外币敞口核验额度",
            derived.missing_foreign_ids.join(",")
        ));
    }
    derived.foreign_subtotal_i64.ok_or_else(|| {
        "MissingDependency：FX 外币义务尚不可精确估值，不能按缺漏外币敞口核验额度".into()
    })
}

/// 正式只读查询 `QueryFxValuation`：返回同一 `cut` 的持久 `fx_valuation`、FX 原件回执、证据回执与责任回执。
pub(super) fn query(
    c: &Connection,
    config: &Config,
    epoch: i64,
    p: &Value,
) -> Result<Value, String> {
    if config.domain != "E" || !enabled(config) {
        return Err("SchemaUnsupported：当前域未启用 fx-valuation/1 子合同".into());
    }
    exact(p, &["op", "cut", "as_known_ns"])?;
    let (seq, root, ns, image) = select_cut(c, config, p)?;
    let fx = image
        .get(CONTRACT_FIELD)
        .ok_or("StorageUnavailable：目标 cut 缺少 fx_valuation 对象")?;

    let mut fx_fact_keys = BTreeSet::new();
    if let Some(revs) = fx["revisions"].as_array() {
        for r in revs {
            if let Some(fk) = r["fact_key"].as_str() {
                fx_fact_keys.insert(fk.to_owned());
            }
        }
    }
    let all_receipts = rows(c, "receipts")?;
    let mut receipts = Vec::new();
    let mut evidence_receipts = Vec::new();
    let mut responsibility_receipts = Vec::new();
    for r in all_receipts {
        let r_seq = r["cut"]["commit_seq"]
            .as_str()
            .and_then(|s| s.parse::<i64>().ok())
            .unwrap_or(i64::MAX);
        if r_seq > seq {
            continue;
        }
        match r["kind"].as_str() {
            Some("Recorded") => {
                if r["fact_key"]
                    .as_str()
                    .is_some_and(|k| fx_fact_keys.contains(k))
                {
                    receipts.push(r);
                }
            }
            Some("Resolved") => {
                if r["covered"].as_array().is_some_and(|arr| {
                    arr.iter()
                        .any(|k| k.as_str().is_some_and(|s| fx_fact_keys.contains(s)))
                }) {
                    evidence_receipts.push(r);
                }
            }
            Some(
                "ResponsibilityImportedReceipt"
                | "FxResponsibilityImportedReceipt"
                | "ReserveReceipt"
                | "CapPolicyActivatedReceipt",
            ) => {
                responsibility_receipts.push(r);
            }
            _ => (),
        }
    }
    receipts.sort_by_key(|r| {
        r["cut"]["commit_seq"]
            .as_str()
            .and_then(|s| s.parse::<i64>().ok())
            .unwrap_or(0)
    });
    evidence_receipts.sort_by_key(|r| {
        r["cut"]["commit_seq"]
            .as_str()
            .and_then(|s| s.parse::<i64>().ok())
            .unwrap_or(0)
    });
    responsibility_receipts.sort_by_key(|r| {
        r["cut"]["commit_seq"]
            .as_str()
            .and_then(|s| s.parse::<i64>().ok())
            .unwrap_or(0)
    });

    Ok(json!({
        "kind": "EconomicFxValuation",
        "domain_id": config.domain,
        "cut": cut(config, seq, &root),
        "commit_ns": ns,
        "writer_epoch": epoch.to_string(),
        "fx_valuation": fx,
        "receipts": receipts,
        "evidence_receipts": evidence_receipts,
        "responsibility_receipts": responsibility_receipts
    }))
}
