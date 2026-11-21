//! ADR 0073：每条历史事件核当时唯一权威绑定；当前查询不能重写原执行证明。
use super::{
    authority_binding::History, authority_frame, authority_reply, error, hash, logical_now,
    query_execution_frame, store, validate_accept_clock, validate_execution_record, AcceptClock,
    Batch, ExactCommand, Profile,
};
use crate::session_protocol::{canonical_json, strict_json};
use rusqlite::{params, Connection, OptionalExtension};
use serde::Deserialize;
use serde_json::{json, Value};

pub(super) fn record(
    c: &Connection,
    history: Option<&History>,
    id: &str,
    phase: &str,
    original: Value,
) -> Result<(), String> {
    if let Some(h) = history {
        c.execute(
            "INSERT INTO x_authority_events(command_id,phase,binding_seq,original) VALUES(?1,?2,?3,?4)",
            params![id, phase, h.current_seq(), canonical_json(&original)],
        ).map_err(error)?;
    }
    Ok(())
}

pub(super) struct Event {
    seq: i64,
    pub(super) binding_seq: i64,
    phase: String,
    pub(super) original: Value,
}

impl Event {
    fn decode(
        h: &History,
        seq: i64,
        phase: String,
        binding_seq: i64,
        raw: String,
    ) -> Result<Self, String> {
        let original = strict_json(raw.as_bytes())?;
        if h.seq_at_event(seq) != binding_seq || raw != canonical_json(&original) {
            return Err(conflict("历史事件与发生时的绑定或规范原件不符"));
        }
        Ok(Self {
            seq,
            binding_seq,
            phase,
            original,
        })
    }

    fn parts(&self) -> Vec<(&'static str, &Value)> {
        let doc = &self.original;
        let mut parts = match self.phase.as_str() {
            "accept" => vec![("request", &doc["request"]), ("reply", &doc["reply"])],
            "request" => vec![("request", &doc["request"]), ("batch", &doc["batch"])],
            "evidence" => vec![("original_reply", &doc["original_reply"])],
            "claim" | "observe" | "publish" => vec![("batch", &doc["batch"])],
            _ => vec![],
        };
        if self.phase == "evidence" && !doc["observed_query"].is_null() {
            let q = &doc["observed_query"];
            parts.extend([
                ("query_request", &q["request"]),
                ("query_reply", &q["reply"]),
            ]);
        }
        parts
    }

    fn summary(&self) -> Value {
        let parts: serde_json::Map<String, Value> = self
            .parts()
            .into_iter()
            .map(|(name, doc)| (name.into(), json!(hash(doc))))
            .collect();
        let doc = &self.original;
        let mut summary = json!({
            "event_seq":self.seq, "binding_seq":self.binding_seq, "phase":self.phase,
            "record_sha256":hash(doc), "parts":parts
        });
        if !doc["evidence_event_seq"].is_null() {
            summary["caused_by_event_seq"] = doc["evidence_event_seq"].clone();
        } else if !doc["claim_event_seq"].is_null() {
            summary["caused_by_event_seq"] = doc["claim_event_seq"].clone();
        }
        if !doc["observed_query"].is_null() {
            let q = &doc["observed_query"];
            summary["observed_query"] = json!({
                "s_authority_epoch":q["reply"]["producer_epoch"], "read_ns":q["read_ns"]
            });
        }
        summary
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalRef {
    event_seq: i64,
    part: String,
}

pub(super) fn query_original(
    c: &Connection,
    h: &History,
    reference: OriginalRef,
) -> Result<Value, String> {
    let (id, phase, seq, raw) = c.query_row(
        "SELECT command_id,phase,binding_seq,original FROM x_authority_events WHERE event_seq=?1",
        [reference.event_seq], |r| Ok((r.get::<_, String>(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
    ).optional().map_err(error)?.ok_or("MissingDependency：历史事件不存在")?;
    let event = Event::decode(h, reference.event_seq, phase, seq, raw)?;
    let original = match reference.part.as_str() {
        "record" => event.original,
        "result" if event.phase == "publish" => store::read_batch(c, &id)?,
        part => event
            .parts()
            .into_iter()
            .find(|(name, _)| *name == part)
            .map(|(_, value)| value.clone())
            .ok_or("MissingDependency：该事件没有指定原件")?,
    };
    Ok(json!({"kind":"AuthorityOriginal","event_seq":event.seq,
        "binding_seq":event.binding_seq,"part":reference.part,"original":original}))
}

fn read_events(
    c: &Connection,
    h: &History,
    id: &str,
    publication: bool,
) -> Result<Vec<Event>, String> {
    let mut q = c.prepare(
        "SELECT event_seq,phase,binding_seq,original FROM x_authority_events WHERE command_id=?1 AND (phase='publish')=?2 ORDER BY event_seq",
    ).map_err(error)?;
    let rows = q
        .query_map(params![id, publication], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, i64>(2)?,
                r.get::<_, String>(3)?,
            ))
        })
        .map_err(error)?;
    let mut events = Vec::new();
    for row in rows {
        let (seq, phase, binding_seq, raw) = row.map_err(error)?;
        events.push(Event::decode(h, seq, phase, binding_seq, raw)?);
    }
    Ok(events)
}

pub(super) fn attempt(c: &Connection, h: &History, id: &str) -> Result<Event, String> {
    read_events(c, h, id, false)?
        .into_iter()
        .find(|e| e.phase == "request")
        .ok_or_else(|| conflict("原 S 尝试不存在"))
}

fn conflict(s: &str) -> String {
    format!("IdentityConflict：{s}")
}

fn check_original_shape(value: &Value, fields: &[&str]) -> Result<(), String> {
    if value
        .as_object()
        .is_some_and(|o| o.len() == fields.len() && fields.iter().all(|f| o.contains_key(*f)))
    {
        Ok(())
    } else {
        Err(conflict("缺原交换或因果字段"))
    }
}
struct CommandRow {
    id: String,
    raw: String,
    state: String,
    release: String,
    accept_clock: String,
    release_evidence: String,
    attempt: Option<String>,
    execution: Option<String>,
}

fn command_row(r: &rusqlite::Row<'_>) -> rusqlite::Result<CommandRow> {
    Ok(CommandRow {
        id: r.get(0)?,
        raw: r.get(1)?,
        state: r.get(2)?,
        release: r.get(3)?,
        accept_clock: r.get(4)?,
        release_evidence: r.get(5)?,
        attempt: r.get(6)?,
        execution: r.get(7)?,
    })
}

const COMMANDS: &str = "SELECT id,command,state,release_receipt,accept_clock,release_evidence,attempt_batch,execute_evidence FROM x_exact_commands";

fn verify(
    c: &Connection,
    genesis: &Profile,
    h: &History,
    epoch: i64,
    row: &CommandRow,
) -> Result<Vec<Event>, String> {
    let events = read_events(c, h, &row.id, false)?;
    let expected: &[&str] = match row.state.as_str() {
        "Accepted" => &["accept"],
        "ExecutionRequested" => &["accept", "request"],
        "ExecutionReady" => &["accept", "request", "evidence"],
        "MayHaveCalled" => &["accept", "request", "evidence", "claim"],
        "Observed" => &["accept", "request", "evidence", "claim", "observe"],
        _ => return Err(conflict("命令状态未知")),
    };
    if !events
        .iter()
        .map(|e| e.phase.as_str())
        .eq(expected.iter().copied())
    {
        return Err(conflict("命令阶段与不可变事件不相符"));
    }
    let command: ExactCommand = serde_json::from_str(&row.raw).map_err(error)?;
    let accept = &events[0];
    let p = h.profile_at(genesis, accept.binding_seq)?;
    command.validate(&p, epoch)?;
    if command.command_id != row.id || super::encode(&command)? != row.raw {
        return Err(conflict("接纳原命令身份或规范字节不符"));
    }
    let doc = &accept.original;
    check_original_shape(doc, &["request", "reply", "clock"])?;
    let frame = authority_frame(&p, &p.e, epoch, "QueryReleasedExact", &command, None)?;
    if doc["request"] != frame.envelope {
        return Err(conflict("原 E 请求不符"));
    }
    let released = authority_reply(
        &p,
        &p.e,
        "QueryReleasedExact",
        &command,
        None,
        &frame,
        &doc["reply"],
    )?;
    let clock: AcceptClock = serde_json::from_value(doc["clock"].clone()).map_err(error)?;
    validate_accept_clock(&clock, released.commit_ns)?;
    if released.receipt_id != row.release
        || super::encode(&released)? != row.release_evidence
        || super::encode(&clock)? != row.accept_clock
    {
        return Err(conflict("接纳原回执或接纳时钟不符"));
    }
    let Some(attempt) = events.get(1) else {
        if row.attempt.is_some() || row.execution.is_some() {
            return Err(conflict("未请求的接纳记录混入原尝试或执行证据"));
        }
        return Ok(events);
    };
    let original = &attempt.original;
    check_original_shape(original, &["request", "batch"])?;
    let old = h.profile_at(genesis, attempt.binding_seq)?;
    let request = authority_frame(
        &old,
        &old.s,
        epoch,
        "RequestConditionalExecution",
        &command,
        Some(&row.release),
    )?;
    if original["request"] != request.envelope
        || Some(canonical_json(&original["batch"]).as_str()) != row.attempt.as_deref()
        || original["batch"]["bar"]["index"]
            .as_i64()
            .is_none_or(|t| t < clock.commit_ns)
    {
        return Err(conflict("原 S 尝试的请求/归属批/时钟不符"));
    }
    let batch: Batch = serde_json::from_value(original["batch"].clone()).map_err(error)?;
    if row.state == "Observed" {
        if store::replay_batch(c, &batch)?.is_none() {
            return Err(conflict("已观察命令缺原批收据"));
        }
    } else if store::pending_batch(c)? != row.attempt {
        return Err(conflict("原请求脱离仍待办的批次"));
    }
    let Some(evidence) = events.get(2) else {
        if row.execution.is_some() {
            return Err(conflict("尚未取得资格但持久记录混入证据"));
        }
        return Ok(events);
    };
    let doc = &evidence.original;
    check_original_shape(doc, &["original_reply", "observed_query", "claimed_ns"])?;
    let executed = authority_reply(
        &old,
        &old.s,
        "RequestConditionalExecution",
        &command,
        Some(&row.release),
        &request,
        &doc["original_reply"],
    )?;
    if doc["observed_query"].is_null() {
        if evidence.binding_seq != attempt.binding_seq {
            return Err(conflict("直接执行的证据不能跨绑定"));
        }
    } else {
        let query = &doc["observed_query"];
        check_original_shape(query, &["request", "reply", "read_ns"])?;
        let active = h.profile_at(genesis, evidence.binding_seq)?;
        let current =
            query_execution_frame(&active, epoch, &command, &row.release, &request.envelope)?;
        if query["request"] != current.envelope
            || super::verified_query_original(&active, &current, &query["reply"])?
                != &doc["original_reply"]
            || query["read_ns"] != doc["claimed_ns"]
        {
            return Err(conflict("当前查询不是原 S 请求的已提交证据"));
        }
    }
    let execution = json!({"reply":executed,"claimed_ns":doc["claimed_ns"]});
    validate_execution_record(&old, &command, &row.release, &execution)?;
    if doc["claimed_ns"] != original["batch"]["bar"]["index"]
        || Some(canonical_json(&execution).as_str()) != row.execution.as_deref()
    {
        return Err(conflict("执行原件/时钟与原批次不符"));
    }
    if let Some(claim) = events.get(3) {
        if claim.original != json!({"batch":original["batch"],"evidence_event_seq":evidence.seq}) {
            return Err(conflict("调用占有未绑定原批及资格"));
        }
        if let Some(observed) = events.get(4) {
            let publication = publication(c, h, &batch.request_id, &original["batch"])?;
            if observed.binding_seq != publication.binding_seq
                || publication.seq <= claim.seq
                || publication.seq >= observed.seq
                || observed.original
                    != json!({"batch":original["batch"],"claim_event_seq":claim.seq})
            {
                return Err(conflict("批次提交未绑定唯一调用占有"));
            }
        }
    }
    Ok(events)
}

fn publication(c: &Connection, h: &History, id: &str, batch: &Value) -> Result<Event, String> {
    let mut events = read_events(c, h, id, true)?;
    let event = events
        .pop()
        .ok_or_else(|| conflict("模型批收据缺发生时的绑定"))?;
    if !events.is_empty() || event.original != json!({"batch":batch}) {
        return Err(conflict("模型批收据与原发布批不符"));
    }
    Ok(event)
}

pub(super) fn audit(
    c: &Connection,
    genesis: &Profile,
    h: &History,
    epoch: i64,
) -> Result<(), String> {
    let mut q = c.prepare(COMMANDS).map_err(error)?;
    let rows = q.query_map([], command_row).map_err(error)?;
    let mut expected = 0i64;
    for row in rows {
        expected += verify(c, genesis, h, epoch, &row.map_err(error)?)?.len() as i64;
    }
    let mut batches = c
        .prepare("SELECT id,request FROM x_sim_batches")
        .map_err(error)?;
    let rows = batches
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
        .map_err(error)?;
    for row in rows {
        let (id, request) = row.map_err(error)?;
        publication(c, h, &id, &strict_json(request.as_bytes())?)?;
        expected += 1;
    }
    let (count, min, max): (i64, i64, i64) = c.query_row(
        "SELECT COUNT(*),COALESCE(MIN(event_seq),1),COALESCE(MAX(event_seq),0) FROM x_authority_events",
        [], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
    ).map_err(error)?;
    if count != expected || min != 1 || max != count {
        return Err(conflict("有缺失、游离或不连续的权威事件"));
    }
    Ok(())
}

/// 极长的原收据 ID 按原回包引用读取；在线摘要从不复制无界字段。
fn receipt_id(id: &Value) -> Value {
    if canonical_json(id).len() <= 512 {
        id.clone()
    } else {
        Value::Null
    }
}

pub(super) fn query(
    c: &Connection,
    genesis: &Profile,
    h: &History,
    epoch: i64,
    id: &str,
) -> Result<Value, String> {
    let current = h.profile_at(genesis, h.current_seq())?;
    let mut response = json!({
        "kind":"ExactCommandState","command_id":id,"state":"NoRecord",
        "current_binding_seq":h.current_seq(),"x_writer_epoch":epoch,
        "current_e_authority_epoch":current.e.authority_epoch,
        "current_s_authority_epoch":current.s.authority_epoch,"read_ns":logical_now(c)?
    });
    let Some(row) = c
        .query_row(&format!("{COMMANDS} WHERE id=?1"), [id], command_row)
        .optional()
        .map_err(error)?
    else {
        return Ok(response);
    };
    let events = verify(c, genesis, h, epoch, &row)?;
    let accept = &events[0];
    let reply = &accept.original["reply"]["payload"];
    response["state"] = json!(row.state);
    response["x_accept"] = accept.original["clock"].clone();
    response["causal_refs"] = json!([{
        "authority_id":reply["authority_id"], "authority_epoch":reply["authority_epoch"],
        "receipt_id":receipt_id(&reply["receipt_id"]), "command_hash":reply["command_hash"],
        "release_commit_ns":reply["commit_ns"], "event_seq":accept.seq, "part":"reply"
    }]);
    response["authority_history"] = json!(events.iter().map(Event::summary).collect::<Vec<_>>());
    if let Some(request) = events.get(1) {
        let original = &request.original["request"]["payload"];
        let mut execution = json!({
            "binding_seq":request.binding_seq,"s_authority_epoch":original["authority_epoch"],
            "request_event_seq":request.seq
        });
        if let Some(evidence) = events.get(2) {
            let reply = &evidence.original["original_reply"]["payload"];
            execution["receipt"] = json!({
                "event_seq":evidence.seq,"part":"original_reply",
                "receipt_id":receipt_id(&reply["receipt_id"]),"commit_ns":reply["commit_ns"]
            });
        }
        response["s_execution"] = execution;
        let batch = &request.original["batch"];
        let mut result = json!({
            "state":"Pending","request_event_seq":request.seq,"request_sha256":hash(batch)
        });
        if row.state == "Observed" {
            let id = batch["request_id"]
                .as_str()
                .ok_or_else(|| conflict("原批身份缺失"))?;
            let event = publication(c, h, id, batch)?;
            result["state"] = json!("Published");
            result["result_event_seq"] = json!(event.seq);
            result["binding_seq"] = json!(event.binding_seq);
            result["result_sha256"] = json!(hash(&store::read_batch(c, id)?));
        }
        response["batch_result"] = result;
    }
    Ok(response)
}

pub(super) fn link(c: &Connection, id: &str, phase: &str) -> Result<i64, String> {
    c.query_row(
        "SELECT event_seq FROM x_authority_events WHERE command_id=?1 AND phase=?2",
        [id, phase],
        |r| r.get(0),
    )
    .map_err(error)
}
