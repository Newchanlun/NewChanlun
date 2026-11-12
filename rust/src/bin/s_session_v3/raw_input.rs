//! #1394：S2/S3 共用同一原始事件接纳规则。
//!
//! 本模块只操作调用方已经开启的事务；域、写者、profile、完整旧状态与消息/clock
//! 必须先由对应协议入口核验。它不提交事务，不绕过各域的控制记录，也不重做另一套判据。
use super::*;
use crate::v3::audit_owner::owner_tx::{OwnerOps, OwnerTx};
use crate::v3::business_json;
use newchan_rust::s_content::{capture_allocation::scratch::WorkScope, ContextError};
use rusqlite::Transaction;

/// S2/S3 共用冻结输入 profile 与原始 schema 的绑定门；接纳任何原始事件前调用。
pub(super) fn validate_profile_binding(
    input: &RawInputFile,
    profile_id: &str,
) -> Result<(), String> {
    if (input.schema_revision == tb02a::RAW_SCHEMA) != (profile_id == tb02a::PROFILE) {
        return Err("SchemaUnsupported：绑定profile/schema不一致".into());
    }
    if input.profile != profile_id {
        return Err(format!(
            "InvalidDomain：输入 profile=`{}` 与 --profile 的 profile_id=`{profile_id}` 不一致",
            input.profile
        ));
    }
    Ok(())
}

pub(super) fn accept_events(
    tx: &Transaction<'_>,
    input: &RawInputFile,
    volume_unit: Option<&str>,
) -> Result<Vec<Value>, String> {
    let owner = accept_events_on(OwnerTx::Legacy(tx), input, volume_unit, None)
        .map_err(ContextError::into_message)?;
    match owner {
        business_json::JsonOwner::Plain(value) => match value.into_unscoped()? {
            Value::Array(rows) => Ok(rows),
            _ => unreachable!("接纳结果只构造数组"),
        },
        #[cfg(feature = "s_allocation_json_testonly")]
        business_json::JsonOwner::Owned(_) => unreachable!("旧入口不构造 Owned"),
    }
}

pub(super) fn accept_events_on(
    tx: OwnerTx<'_>,
    input: &RawInputFile,
    volume_unit: Option<&str>,
    work: Option<&WorkScope>,
) -> Result<business_json::JsonOwner, ContextError> {
    tx.with_ops(work, |ops| accept_events_in(&ops, input, volume_unit, work))
}

fn accept_events_in(
    tx: &OwnerOps<'_>,
    input: &RawInputFile,
    volume_unit: Option<&str>,
    work: Option<&WorkScope>,
) -> Result<business_json::JsonOwner, ContextError> {
    let declaration = tx
        .query_optional(
            newchan_rust::structure_source::STORED_SQL,
            [&newchan_rust::structure_source::META_KEY],
            |r| Ok(r.text_admitted(0, work)),
        )
        .map_err(|e| e.context("StorageUnavailable：读 meta.structure_source 失败：", work))?
        .transpose()?;
    // 原解析同时存活 serde Value 和 Declaration 的 String/BTreeSet；分配前覆盖两者上界。
    // 词法计数不是语法资格，合法性仍只由原 decode_stored/Declaration 判据决定。
    let declaration_memory = match (declaration.as_ref(), work) {
        (Some(text), Some(work)) => {
            let shape = business_json::json_layout::JsonShape::scan(text.as_str().as_bytes());
            let bytes = shape
                .parse_peak()
                .saturating_add(shape.text)
                .saturating_add(business_json::json_layout::tree_slots::<String, ()>(
                    shape.values,
                ));
            Some(
                work.reserve_native(bytes)
                    .map_err(|error| ContextError::from_codec(error, ""))?,
            )
        }
        _ => None,
    };
    if let Some(declaration) = newchan_rust::structure_source::decode_stored(
        declaration.as_ref().map(|text| text.as_str()),
    )? {
        declaration.admits(&input.source_namespace)?;
    }
    drop(declaration_memory);
    drop(declaration);
    let mut results = business_json::ScopedJsonArray::new(None, work)?;
    let mut qrev = tx
        .prepare("SELECT receipt_id, payload_hash, source_coord, seq FROM raw_events WHERE identity_key=?1 AND revision=?2")
        .map_err(|e| e.context("prepare 查询失败：", work))?;
    let mut qmax = tx
        .prepare("SELECT COALESCE(MAX(revision), 0) FROM raw_events WHERE identity_key=?1")
        .map_err(|e| e.context("prepare 查询失败：", work))?;
    let mut insert = tx
        .prepare(
            "INSERT INTO raw_events(identity_key, revision, input_revision, payload_hash, receipt_id, seq,
               source_namespace, source_epoch, instrument, event_id, received_at,
               raw_text, price, ts, volume, source_coord, supersedes_revision)
             VALUES(?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17)",
        )
        .map_err(|e| e.context("prepare insert 失败：", work))?;

    let mut next_seq: i64 = tx
        .query_row("SELECT COALESCE(MAX(seq), -1) FROM raw_events", [], |r| {
            r.get(0)
        })
        .map_err(|e| e.context("读 max seq 失败：", work))?;

    for e in &input.events {
        parse_source_coord(&e.seq).map_err(|e| format!("InvalidDomain：{e}"))?;
        parse_canonical_i64(&e.price, "price")?;
        parse_canonical_i64(&e.timestamp, "timestamp")?;
        parse_canonical_i64(&e.volume, "volume")?;
        let rev = parse_canonical_i64(&e.revision, "revision")?;
        if let Some(vu) = &volume_unit {
            if e.volume != *vu {
                return Err(format!(
                    "InvalidDomain：profile volume_unit=`{vu}`，事件 `{}` volume=`{}` 不在单位成交量域（本片不擅自改成交量类型）",
                    e.event_id, e.volume
                ).into());
            }
        }
        let ikey = identity_key(
            &input.source_namespace,
            &input.source_epoch,
            &input.instrument,
            &e.event_id,
        );
        // 同一计算序的坐标只能归一个业务身份；该身份的历史 revision 可共享坐标。
        let occupied: bool = tx
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM raw_events WHERE source_coord=?1 AND identity_key<>?2)",
                [&e.seq as &dyn rusqlite::ToSql, &ikey],
                |row| row.get(0),
            )
            .map_err(|e| e.context("查询源坐标归属失败：", work))?;
        if occupied {
            return Err(format!(
                "IdentityConflict：source_coord `{}` 已属于另一业务身份（不覆盖原始事件或见证）",
                e.seq
            )
            .into());
        }
        let content = canonical_event_content(e);
        let payload_hash = sha256_hex(content.as_bytes());

        let existing = qrev
            .query_optional([&ikey as &dyn rusqlite::ToSql, &rev], |r| {
                Ok((|| -> Result<_, ContextError> {
                    Ok((
                        r.text_admitted(0, work)?,
                        r.text_admitted(1, work)?,
                        r.text_admitted(2, work)?,
                        r.get::<i64>(3).map_err(|e| {
                            crate::v3::audit_owner::owner_tx::OwnerSqlError::Sqlite(e)
                                .context("", work)
                        })?,
                    ))
                })())
            })
            .map_err(|e| e.context("查询 identity 失败：", work))?
            .transpose()?;

        if let Some((rec, ph, coord, seq)) = existing {
            if ph.as_str() == payload_hash {
                push_receipt(
                    &mut results,
                    work,
                    &[
                        (Field::Status, ReceiptValue::Text("replay")),
                        (Field::IdentityKey, ReceiptValue::Text(&ikey)),
                        (Field::EventId, ReceiptValue::Text(&e.event_id)),
                        (Field::Revision, ReceiptValue::Integer(rev)),
                        (Field::ReceiptId, ReceiptValue::Text(rec.as_str())),
                        (Field::PayloadHash, ReceiptValue::Text(&payload_hash)),
                        (Field::Seq, ReceiptValue::Integer(seq)),
                        (Field::SourceCoord, ReceiptValue::Text(coord.as_str())),
                    ],
                )?;
            } else {
                push_receipt(
                    &mut results,
                    work,
                    &[
                        (Field::Status, ReceiptValue::Text("IdentityConflict")),
                        (Field::IdentityKey, ReceiptValue::Text(&ikey)),
                        (Field::EventId, ReceiptValue::Text(&e.event_id)),
                        (Field::Revision, ReceiptValue::Integer(rev)),
                        (Field::ExistingReceiptId, ReceiptValue::Text(rec.as_str())),
                        (Field::ExistingPayloadHash, ReceiptValue::Text(ph.as_str())),
                        (Field::NewPayloadHash, ReceiptValue::Text(&payload_hash)),
                    ],
                )?;
            }
            continue;
        }

        // 该 (identity, revision) 未见过。
        let max_rev: i64 = qmax
            .query_row([&ikey as &dyn rusqlite::ToSql], |r| r.get(0))
            .map_err(|e| e.context("读 max revision 失败：", work))?;
        if rev <= max_rev {
            // 旧版（已有更高 revision）且该 revision 无记录：晚到/跳号旧版不复活、不新接纳。
            push_receipt(
                &mut results,
                work,
                &[
                    (Field::Status, ReceiptValue::Text("InvalidDomain")),
                    (Field::IdentityKey, ReceiptValue::Text(&ikey)),
                    (Field::EventId, ReceiptValue::Text(&e.event_id)),
                    (Field::Revision, ReceiptValue::Integer(rev)),
                    (Field::MaxRevision, ReceiptValue::Integer(max_rev)),
                    (
                        Field::Reason,
                        ReceiptValue::Text("out_of_order_revision_after_later_accepted"),
                    ),
                ],
            )?;
            continue;
        }
        // 新 revision：supersedes = 上一 revision（如有）。
        let supersedes = if max_rev == 0 { None } else { Some(max_rev) };
        // 源坐标一致性：同一业务身份的新 revision 必须落在同一源坐标。
        if let Some(prev_rev) = supersedes {
            let prev_coord = tx
                .query_row(
                    "SELECT source_coord FROM raw_events WHERE identity_key=?1 AND revision=?2",
                    [&ikey as &dyn rusqlite::ToSql, &prev_rev],
                    |r| Ok(r.text_admitted(0, work)),
                )
                .map_err(|e| e.context("读前一 revision 源坐标失败：", work))??;
            if prev_coord.as_str() != e.seq {
                return Err(format!(
                    "IdentityConflict：事件 `{}` 新 revision=`{rev}` 源坐标 `{}` 与已接纳 revision=`{prev_rev}` 源坐标 `{prev_coord}` 不一致（同一业务身份不得换源位置）",
                    e.event_id, e.seq
                ).into());
            }
        }

        next_seq += 1;
        let receipt_id = format!(
            "rcpt-{}",
            &sha256_hex(format!("{ikey}|{payload_hash}").as_bytes())[..16]
        );
        insert
            .execute([
                &ikey as &dyn rusqlite::ToSql,
                &rev,
                &e.revision,
                &payload_hash,
                &receipt_id,
                &next_seq,
                &input.source_namespace,
                &input.source_epoch,
                &input.instrument,
                &e.event_id,
                &e.received_at,
                &e.raw_text,
                &e.price,
                &e.timestamp,
                &e.volume,
                &e.seq,
                &supersedes,
            ])
            .map_err(|e| e.context("insert raw_events 失败：", work))?;
        if let Some(prices) = &e.ohlc {
            tb02a::save_raw_on(tx, &ikey, rev, prices, work)?;
        }
        push_receipt(
            &mut results,
            work,
            &[
                (Field::Status, ReceiptValue::Text("accepted")),
                (Field::IdentityKey, ReceiptValue::Text(&ikey)),
                (Field::EventId, ReceiptValue::Text(&e.event_id)),
                (Field::Revision, ReceiptValue::Integer(rev)),
                (Field::ReceiptId, ReceiptValue::Text(&receipt_id)),
                (Field::PayloadHash, ReceiptValue::Text(&payload_hash)),
                (Field::Seq, ReceiptValue::Integer(next_seq)),
                (Field::SourceCoord, ReceiptValue::Text(&e.seq)),
                (
                    Field::SupersedesRevision,
                    ReceiptValue::OptionalInteger(supersedes),
                ),
            ],
        )?;
    }

    Ok(results.finish())
}

use business_json::scoped_legacy::{Field, ProjectionKind, ScopedLegacyRecord};
enum ReceiptValue<'a> {
    Text(&'a str),
    Integer(i64),
    OptionalInteger(Option<i64>),
}
fn push_receipt(
    results: &mut business_json::ScopedJsonArray<'_>,
    work: Option<&WorkScope>,
    fields: &[(Field, ReceiptValue<'_>)],
) -> Result<(), ContextError> {
    let receipt = if let Some(work) = work {
        let map_error = |e| match e {
            business_json::MixedJsonError::Resource(e) => ContextError::from_codec(e, ""),
            business_json::MixedJsonError::Business(e) => ContextError::from(e),
        };
        let mut receipt =
            ScopedLegacyRecord::object(ProjectionKind::AcceptReceipt, work).map_err(map_error)?;
        for (field, value) in fields {
            match value {
                ReceiptValue::Text(text) => receipt.text(*field, text),
                ReceiptValue::Integer(n) | ReceiptValue::OptionalInteger(Some(n)) => {
                    receipt.integer(*field, *n)
                }
                ReceiptValue::OptionalInteger(None) => receipt.null(*field),
            }
            .map_err(map_error)?;
        }
        receipt.finish()
    } else {
        let mut object = serde_json::Map::new();
        for (field, value) in fields {
            let value = match value {
                ReceiptValue::Text(text) => Value::String((*text).to_owned()),
                ReceiptValue::Integer(n) | ReceiptValue::OptionalInteger(Some(n)) => {
                    Value::String(n.to_string())
                }
                ReceiptValue::OptionalInteger(None) => Value::Null,
            };
            object.insert(field.name().to_owned(), value);
        }
        Value::Object(object).into()
    };
    results.push(receipt.as_ref().into())
}
