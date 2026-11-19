//! #1425 方案 1：固定切面的只读经济投影（`economic-read-projection/1`）与同切面按需取证。
//!
//! 设计纪律：
//! - 复用现行 `economic-read-pages/1`（256 KiB 分片、1 MiB 物理帧帽、4 MiB 共享缓存帽、30s 截止）
//!   与原离线完整 `audit_with_deadline`，不改写协议、不改原 SQLite 表结构/根链/审计、不抬 4 MiB/1 MiB 上限。
//! - 严禁先加载整幅 `commits.image`（如 6.82 MB）再掐短：通过 `store::stored_image_bytes` 按
//!   `READ_CHUNK`（256 KiB）流式分块读取 `commits.image`，边流式计算完整原像 `SHA-256`（并与持久
//!   `cut.root_hash` 核对），边流式跳过并摘要 8 类跨 owner 嵌入全镜像证明子树（峰值读缓冲仅 256 KiB）。
//! - 严格区分权威原像与投影视图：`authoritative_image_hash`/`authoritative_image_bytes` 绑定全量原像与
//!   `cut.root_hash`，`projection_hash`/`projection_bytes` 仅绑定投影正文，不把截字段后的摘要当全镜像或包含证明。
//! - 原件精确字节不改：面向浏览器的整数精确表示单列在 `simulation_original_text_view` / `*_exact_text`
//!   （显式 `representation = "ExactDecimalIntegerTextProjection"`），不放松客户端严格 JSON 解析器，也不回退 `latest`。
use super::book::hash;
use super::service::{READ_CACHE, READ_CHUNK};
use super::store::{
    check_operation_deadline, cut, err, root_with_image_hash, row, stored_image_bytes,
    stored_image_meta, Config, StoredImage,
};
use super::voice::exact;
use crate::s_content::job::Job;
use crate::session_protocol::{canonical_json, nonnegative, required, sha256_hex, strict_json};
use rusqlite::Connection;
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use std::time::Instant;

pub(super) const PROJECTION_REVISION: &str = "economic-read-projection/1";
pub(super) const OP_READ_PROJECTION: &str = "ReadProjection";
pub(super) const OP_READ_ORIGINAL_AT_CUT: &str = "ReadOriginalAtCut";
pub(super) const KIND_PROJECTION_VIEW: &str = "EconomicProjectionView";
pub(super) const KIND_ORIGINAL_AT_CUT: &str = "EconomicOriginalAtCut";
const EXACT_TEXT_REPR: &str = "ExactDecimalIntegerTextProjection";
const MAX_JSON_DEPTH: usize = 128;

/// 为 `EconomicReadOpen` 中的投影/同切面取证校验原逻辑授权（不扩权、不改 `BASE_OPS`）。
pub(super) fn check_authorization(
    config: &Config,
    envelope: &Value,
    query: &Value,
) -> Result<(), String> {
    let op = required(query, "op")?;
    let check_op = |required_op: &str| -> Result<(), String> {
        let mut req = envelope.clone();
        req["payload"] = json!({"op": required_op});
        config.authorized(&req)
    };
    match op {
        OP_READ_PROJECTION => check_op("ReadView"),
        OP_READ_ORIGINAL_AT_CUT => {
            check_op("ReadView")?;
            match required(query, "kind")? {
                "fact" => check_op("QueryFact"),
                "allocation" => check_op("QueryAllocation"),
                "decision" => check_op("QueryDecision"),
                "grant" => check_op("QueryGrant"),
                "command" => check_op("QueryCommand"),
                "model" => {
                    if config.domain == "E" {
                        check_op("QueryCommand").or_else(|_| check_op("QueryFact"))
                    } else {
                        check_op("QueryFact")
                    }
                }
                _ => Err("SchemaUnsupported：未知同切面取证原件类型".into()),
            }
        }
        _ => Err("SchemaUnsupported：未知投影读取操作".into()),
    }
}

/// 选择固定 cut 的只读元数据（不施加 4 MiB 原像上限，因投影/取证流式构建且产物严格受 4 MiB 帽约束）。
/// 不存在、根不匹配或未来 cut 均当场拒绝，绝不回退 `latest`。
pub(super) fn select_projection_meta(
    c: &Connection,
    config: &Config,
    query: &Value,
    require_explicit_cut: bool,
) -> Result<StoredImage, String> {
    if require_explicit_cut {
        if query["cut"].is_null() {
            return Err("InvalidDomain：同切面原件查询必须指定固定 cut".into());
        }
    } else if !query["cut"].is_null() && !query["as_known_ns"].is_null() {
        return Err("InvalidDomain：cut与AsKnown不能同时指定".into());
    }
    let selected = if !query["cut"].is_null() {
        let wanted = &query["cut"];
        exact(wanted, &["domain_id", "commit_seq", "root_hash"])?;
        if wanted["domain_id"] != config.domain {
            return Err("IdentityConflict：跨域cut".into());
        }
        nonnegative(required(wanted, "commit_seq")?, "commit_seq")?
    } else if !query["as_known_ns"].is_null() {
        let ns = nonnegative(required(query, "as_known_ns")?, "as_known_ns")?;
        c.query_row(
            "SELECT max(seq) FROM commits WHERE CAST(commit_ns AS INTEGER)<=?",
            [ns],
            |r| r.get::<_, Option<i64>>(0),
        )
        .map_err(err)?
        .ok_or("MissingDependency：AsKnown早于域创世")?
    } else {
        c.query_row("SELECT max(seq) FROM commits", [], |r| {
            r.get::<_, Option<i64>>(0)
        })
        .map_err(err)?
        .ok_or("MissingDependency：域无创世cut")?
    };
    let meta = stored_image_meta(c, selected)?;
    if !query["cut"].is_null() && query["cut"] != cut(config, meta.seq, &meta.root) {
        return Err("IdentityConflict：cut根不匹配".into());
    }
    Ok(meta)
}

/// 分块流式读取器：每次仅从 SQLite 读至多 `READ_CHUNK`（256 KiB）字节，
/// 边读边推进全量原像 `Sha256` 并核截止期限与可选 `Job` 字节账。
struct ChunkedImageStream<'a> {
    c: &'a Connection,
    meta: &'a StoredImage,
    job: Option<&'a mut Job>,
    deadline: Instant,
    offset: usize,
    buf: Vec<u8>,
    pos: usize,
    hasher: Sha256,
    chunk_reads: usize,
    max_chunk_bytes: usize,
}

impl<'a> ChunkedImageStream<'a> {
    fn new(
        c: &'a Connection,
        meta: &'a StoredImage,
        job: Option<&'a mut Job>,
        deadline: Instant,
    ) -> Self {
        Self {
            c,
            meta,
            job,
            deadline,
            offset: 0,
            buf: Vec::new(),
            pos: 0,
            hasher: Sha256::new(),
            chunk_reads: 0,
            max_chunk_bytes: 0,
        }
    }

    fn refill(&mut self) -> Result<bool, String> {
        if self.pos < self.buf.len() {
            return Ok(true);
        }
        if self.offset >= self.meta.bytes {
            return Ok(false);
        }
        check_operation_deadline(None, Some(self.deadline))?;
        let take = READ_CHUNK.min(self.meta.bytes - self.offset);
        let chunk = stored_image_bytes(self.c, self.meta, self.offset, take)?;
        if let Some(job) = self.job.as_deref_mut() {
            job.charge_wire_bytes(u64::try_from(chunk.len()).map_err(err)?)
                .map_err(|e| format!("QueryBudgetExceeded：{e}"))?;
        }
        self.hasher.update(&chunk);
        self.offset += chunk.len();
        self.chunk_reads += 1;
        self.max_chunk_bytes = self.max_chunk_bytes.max(chunk.len());
        self.buf = chunk;
        self.pos = 0;
        Ok(true)
    }

    fn peek(&mut self) -> Result<Option<u8>, String> {
        if !self.refill()? {
            return Ok(None);
        }
        Ok(Some(self.buf[self.pos]))
    }

    fn next_byte(&mut self) -> Result<Option<u8>, String> {
        if !self.refill()? {
            return Ok(None);
        }
        let b = self.buf[self.pos];
        self.pos += 1;
        Ok(Some(b))
    }

    fn expect_byte(&mut self, expected: u8) -> Result<(), String> {
        match self.next_byte()? {
            Some(b) if b == expected => Ok(()),
            _ => Err("StorageUnavailable：持久图像非预期JSON分隔符".into()),
        }
    }

    fn skip_ws(&mut self) -> Result<(), String> {
        while let Some(b) = self.peek()? {
            if matches!(b, b' ' | b'\n' | b'\r' | b'\t') {
                self.pos += 1;
            } else {
                break;
            }
        }
        Ok(())
    }

    fn finish_and_verify_root(mut self, config: &Config) -> Result<String, String> {
        self.skip_ws()?;
        if self.peek()?.is_some() || self.offset != self.meta.bytes {
            return Err("StorageUnavailable：持久图像存在未消费尾字节".into());
        }
        let digest = self.hasher.finalize();
        let image_hash: String = digest.iter().map(|b| format!("{b:02x}")).collect();
        let expected_root = root_with_image_hash(
            config,
            self.meta.seq,
            &self.meta.previous_root,
            &self.meta.commit_ns,
            &image_hash,
        );
        if expected_root != self.meta.root {
            return Err("StorageUnavailable：流式完整原像摘要与持久cut根不符".into());
        }
        check_operation_deadline(None, Some(self.deadline))?;
        Ok(image_hash)
    }
}

fn charge_budget(remaining: &mut usize, bytes: usize) -> Result<(), String> {
    *remaining = remaining
        .checked_sub(bytes)
        .ok_or("QueryBudgetExceeded：投影正文超过4MiB逻辑预算")?;
    Ok(())
}

/// 零缓存跳过任意 JSON 子树并同步计算精确 `Sha256` 与字节数（仅 O(depth) 栈空间）。
fn skip_and_hash_value(
    stream: &mut ChunkedImageStream<'_>,
    depth: usize,
) -> Result<(String, usize), String> {
    let mut hasher = Sha256::new();
    let mut len = 0usize;
    skip_into_hasher(stream, &mut hasher, &mut len, depth)?;
    let digest = hasher.finalize();
    Ok((digest.iter().map(|b| format!("{b:02x}")).collect(), len))
}

fn skip_into_hasher(
    stream: &mut ChunkedImageStream<'_>,
    hasher: &mut Sha256,
    len: &mut usize,
    depth: usize,
) -> Result<(), String> {
    if depth > MAX_JSON_DEPTH {
        return Err("StorageUnavailable：JSON嵌套深度超限".into());
    }
    stream.skip_ws()?;
    let Some(first) = stream.peek()? else {
        return Err("StorageUnavailable：JSON值意外截断".into());
    };
    let push = |h: &mut Sha256, n: &mut usize, b: u8| {
        h.update([b]);
        *n += 1;
    };
    match first {
        b'"' => {
            let b = stream.next_byte()?.unwrap();
            push(hasher, len, b);
            let mut escaped = false;
            loop {
                let c = stream
                    .next_byte()?
                    .ok_or("StorageUnavailable：JSON字符串未闭合")?;
                push(hasher, len, c);
                if escaped {
                    escaped = false;
                } else if c == b'\\' {
                    escaped = true;
                } else if c == b'"' {
                    break;
                }
            }
            Ok(())
        }
        b'{' => {
            let b = stream.next_byte()?.unwrap();
            push(hasher, len, b);
            stream.skip_ws()?;
            if stream.peek()? == Some(b'}') {
                let c = stream.next_byte()?.unwrap();
                push(hasher, len, c);
                return Ok(());
            }
            loop {
                stream.skip_ws()?;
                if stream.peek()? != Some(b'"') {
                    return Err("StorageUnavailable：JSON对象键非字符串".into());
                }
                skip_into_hasher(stream, hasher, len, depth + 1)?;
                stream.skip_ws()?;
                let colon = stream
                    .next_byte()?
                    .filter(|&c| c == b':')
                    .ok_or("StorageUnavailable：JSON对象缺冒号")?;
                push(hasher, len, colon);
                skip_into_hasher(stream, hasher, len, depth + 1)?;
                stream.skip_ws()?;
                match stream.next_byte()? {
                    Some(b',') => push(hasher, len, b','),
                    Some(b'}') => {
                        push(hasher, len, b'}');
                        return Ok(());
                    }
                    _ => return Err("StorageUnavailable：JSON对象未闭合".into()),
                }
            }
        }
        b'[' => {
            let b = stream.next_byte()?.unwrap();
            push(hasher, len, b);
            stream.skip_ws()?;
            if stream.peek()? == Some(b']') {
                let c = stream.next_byte()?.unwrap();
                push(hasher, len, c);
                return Ok(());
            }
            loop {
                skip_into_hasher(stream, hasher, len, depth + 1)?;
                stream.skip_ws()?;
                match stream.next_byte()? {
                    Some(b',') => push(hasher, len, b','),
                    Some(b']') => {
                        push(hasher, len, b']');
                        return Ok(());
                    }
                    _ => return Err("StorageUnavailable：JSON数组未闭合".into()),
                }
            }
        }
        b't' | b'f' | b'n' => {
            let expected: &[u8] = match first {
                b't' => b"true",
                b'f' => b"false",
                _ => b"null",
            };
            for &e in expected {
                let c = stream
                    .next_byte()?
                    .filter(|&x| x == e)
                    .ok_or("StorageUnavailable：JSON字面量非法")?;
                push(hasher, len, c);
            }
            Ok(())
        }
        b'-' | b'0'..=b'9' => {
            while let Some(c) = stream.peek()? {
                if c.is_ascii_digit() || matches!(c, b'-' | b'+' | b'.' | b'e' | b'E') {
                    let b = stream.next_byte()?.unwrap();
                    push(hasher, len, b);
                } else {
                    break;
                }
            }
            Ok(())
        }
        _ => Err("StorageUnavailable：JSON非法起始字节".into()),
    }
}

fn parse_string_token(
    stream: &mut ChunkedImageStream<'_>,
    budget: &mut usize,
) -> Result<String, String> {
    stream.skip_ws()?;
    stream.expect_byte(b'"')?;
    let mut raw = vec![b'"'];
    charge_budget(budget, 1)?;
    let mut escaped = false;
    loop {
        let c = stream
            .next_byte()?
            .ok_or("StorageUnavailable：JSON字符串未闭合")?;
        charge_budget(budget, 1)?;
        raw.push(c);
        if escaped {
            escaped = false;
        } else if c == b'\\' {
            escaped = true;
        } else if c == b'"' {
            break;
        }
    }
    serde_json::from_slice::<String>(&raw)
        .map_err(|e| format!("StorageUnavailable：JSON字符串解析失败：{e}"))
}

#[derive(Clone)]
enum PathSeg {
    Key(String),
    Index(usize),
}

fn path_to_string(path: &[PathSeg]) -> String {
    let mut out = String::new();
    for seg in path {
        match seg {
            PathSeg::Key(k) => {
                if !out.is_empty() {
                    out.push('.');
                }
                out.push_str(k);
            }
            PathSeg::Index(i) => {
                out.push('[');
                out.push_str(&i.to_string());
                out.push(']');
            }
        }
    }
    out
}

/// 仅对显式登记的 8 类跨 owner 内联全镜像字段执行零缓冲流式摘要省略，绝不按名字盲猜。
fn is_omitted_peer_image_path(path: &[PathSeg], key: &str) -> bool {
    if !matches!(key, "image" | "previous_image" | "current_image") {
        return false;
    }
    match path {
        // recorded[*].{e_commit_proof, e_resolution_proof, b_source_debit_proof}.{image, previous_image}
        [PathSeg::Key(root), PathSeg::Index(_), PathSeg::Key(proof)]
            if root == "recorded"
                && matches!(
                    proof.as_str(),
                    "e_commit_proof" | "e_resolution_proof" | "b_source_debit_proof"
                ) =>
        {
            true
        }
        // history[*].witness.{grant_proof, commit_proof}.{image, current_image}
        [PathSeg::Key(root), PathSeg::Index(_), PathSeg::Key(w), PathSeg::Key(proof)]
            if root == "history"
                && w == "witness"
                && matches!(proof.as_str(), "grant_proof" | "commit_proof") =>
        {
            true
        }
        // history[*].witness.prepared_proofs[*].{image, current_image}
        [PathSeg::Key(root), PathSeg::Index(_), PathSeg::Key(w), PathSeg::Key(p), PathSeg::Index(_)]
            if root == "history" && w == "witness" && p == "prepared_proofs" =>
        {
            true
        }
        _ => false,
    }
}

/// 仅对 `recorded[*].event.simulation_original` 与 `history[*].event.simulation_original`
/// 生成严格区分的精确十进制文本视图（保留 `original_sha256` 指向原字节，绝不伪装成原字节）。
fn is_simulation_original_path(path: &[PathSeg], key: &str) -> bool {
    if key != "simulation_original" {
        return false;
    }
    matches!(
        path,
        [PathSeg::Key(root), PathSeg::Index(_), PathSeg::Key(ev)]
            if (root == "recorded" || root == "history") && ev == "event"
    )
}

/// 精确整数转规范十进制文本；拒绝任何非整数浮点数，杜绝 JS Number 舍入。
pub(super) fn to_exact_decimal_text(value: &Value) -> Result<Value, String> {
    match value {
        Value::Null | Value::Bool(_) | Value::String(_) => Ok(value.clone()),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(Value::String(i.to_string()))
            } else if let Some(u) = n.as_u64() {
                Ok(Value::String(u.to_string()))
            } else {
                Err("InvalidDomain：投影整数精确文本视图拒绝非整数数值".into())
            }
        }
        Value::Array(items) => {
            let mut out = Vec::with_capacity(items.len());
            for item in items {
                out.push(to_exact_decimal_text(item)?);
            }
            Ok(Value::Array(out))
        }
        Value::Object(map) => {
            let mut out = Map::new();
            for (k, v) in map {
                out.insert(k.clone(), to_exact_decimal_text(v)?);
            }
            Ok(Value::Object(out))
        }
    }
}

fn assert_no_json_numbers(value: &Value) -> Result<(), String> {
    match value {
        Value::Null | Value::Bool(_) | Value::String(_) => Ok(()),
        Value::Number(_) => {
            Err("InvalidDomain：经济投影正文不得包含裸 JSON 数值，必须使用精确文本视图".into())
        }
        Value::Array(items) => {
            for item in items {
                assert_no_json_numbers(item)?;
            }
            Ok(())
        }
        Value::Object(map) => {
            for v in map.values() {
                assert_no_json_numbers(v)?;
            }
            Ok(())
        }
    }
}

fn parse_projected_value(
    stream: &mut ChunkedImageStream<'_>,
    budget: &mut usize,
    path: &mut Vec<PathSeg>,
    omitted: &mut Vec<Value>,
    depth: usize,
) -> Result<Value, String> {
    if depth > MAX_JSON_DEPTH {
        return Err("StorageUnavailable：JSON嵌套深度超限".into());
    }
    stream.skip_ws()?;
    let Some(first) = stream.peek()? else {
        return Err("StorageUnavailable：JSON值意外截断".into());
    };
    match first {
        b'"' => Ok(Value::String(parse_string_token(stream, budget)?)),
        b'{' => {
            stream.expect_byte(b'{')?;
            charge_budget(budget, 2)?;
            stream.skip_ws()?;
            let mut map = Map::new();
            if stream.peek()? == Some(b'}') {
                stream.next_byte()?;
                return Ok(Value::Object(map));
            }
            loop {
                let key = parse_string_token(stream, budget)?;
                stream.skip_ws()?;
                stream.expect_byte(b':')?;
                charge_budget(budget, 2)?;
                if is_omitted_peer_image_path(path, &key) {
                    let (sub_hash, sub_len) = skip_and_hash_value(stream, depth + 1)?;
                    path.push(PathSeg::Key(key.clone()));
                    let full_path = path_to_string(path);
                    path.pop();
                    let anchor = json!({
                        "omitted_kind": "EmbeddedPeerImage",
                        "sha256": sub_hash,
                        "byte_len": sub_len.to_string(),
                    });
                    omitted.push(json!({
                        "path": full_path,
                        "omitted_kind": "EmbeddedPeerImage",
                        "sha256": sub_hash,
                        "byte_len": sub_len.to_string(),
                    }));
                    let new_key = format!("{key}_omitted");
                    charge_budget(budget, new_key.len() + 128)?;
                    map.insert(new_key, anchor);
                } else if is_simulation_original_path(path, &key) {
                    let mut raw_orig = Vec::new();
                    collect_raw_value(stream, &mut raw_orig, budget, depth + 1)?;
                    let parsed = strict_json(&raw_orig)?;
                    let orig_sha = sha256_hex(canonical_json(&parsed).as_bytes());
                    let text_view = json!({
                        "representation": EXACT_TEXT_REPR,
                        "original_sha256": orig_sha,
                        "value": to_exact_decimal_text(&parsed)?,
                    });
                    charge_budget(budget, 128)?;
                    map.insert("simulation_original_text_view".into(), text_view);
                } else {
                    path.push(PathSeg::Key(key.clone()));
                    let val = parse_projected_value(stream, budget, path, omitted, depth + 1)?;
                    path.pop();
                    map.insert(key, val);
                }
                stream.skip_ws()?;
                match stream.next_byte()? {
                    Some(b',') => continue,
                    Some(b'}') => break,
                    _ => return Err("StorageUnavailable：JSON对象未闭合".into()),
                }
            }
            Ok(Value::Object(map))
        }
        b'[' => {
            stream.expect_byte(b'[')?;
            charge_budget(budget, 2)?;
            stream.skip_ws()?;
            let mut arr = Vec::new();
            if stream.peek()? == Some(b']') {
                stream.next_byte()?;
                return Ok(Value::Array(arr));
            }
            let mut idx = 0usize;
            loop {
                path.push(PathSeg::Index(idx));
                let val = parse_projected_value(stream, budget, path, omitted, depth + 1)?;
                path.pop();
                arr.push(val);
                idx += 1;
                stream.skip_ws()?;
                match stream.next_byte()? {
                    Some(b',') => {
                        charge_budget(budget, 1)?;
                        continue;
                    }
                    Some(b']') => break,
                    _ => return Err("StorageUnavailable：JSON数组未闭合".into()),
                }
            }
            Ok(Value::Array(arr))
        }
        b't' | b'f' | b'n' => {
            let expected: &[u8] = match first {
                b't' => b"true",
                b'f' => b"false",
                _ => b"null",
            };
            for &e in expected {
                stream
                    .next_byte()?
                    .filter(|&x| x == e)
                    .ok_or("StorageUnavailable：JSON字面量非法")?;
            }
            charge_budget(budget, expected.len())?;
            Ok(match first {
                b't' => Value::Bool(true),
                b'f' => Value::Bool(false),
                _ => Value::Null,
            })
        }
        b'-' | b'0'..=b'9' => {
            let mut raw = Vec::new();
            while let Some(c) = stream.peek()? {
                if c.is_ascii_digit() || matches!(c, b'-' | b'+' | b'.' | b'e' | b'E') {
                    let b = stream.next_byte()?.unwrap();
                    charge_budget(budget, 1)?;
                    raw.push(b);
                } else {
                    break;
                }
            }
            strict_json(&raw)
        }
        _ => Err("StorageUnavailable：JSON非法起始字节".into()),
    }
}

fn collect_raw_value(
    stream: &mut ChunkedImageStream<'_>,
    out: &mut Vec<u8>,
    budget: &mut usize,
    depth: usize,
) -> Result<(), String> {
    if depth > MAX_JSON_DEPTH {
        return Err("StorageUnavailable：JSON嵌套深度超限".into());
    }
    stream.skip_ws()?;
    let Some(first) = stream.peek()? else {
        return Err("StorageUnavailable：JSON值意外截断".into());
    };
    let push = |out: &mut Vec<u8>, budget: &mut usize, b: u8| -> Result<(), String> {
        charge_budget(budget, 1)?;
        out.push(b);
        Ok(())
    };
    match first {
        b'"' => {
            let b = stream.next_byte()?.unwrap();
            push(out, budget, b)?;
            let mut escaped = false;
            loop {
                let c = stream
                    .next_byte()?
                    .ok_or("StorageUnavailable：JSON字符串未闭合")?;
                push(out, budget, c)?;
                if escaped {
                    escaped = false;
                } else if c == b'\\' {
                    escaped = true;
                } else if c == b'"' {
                    break;
                }
            }
            Ok(())
        }
        b'{' => {
            let b = stream.next_byte()?.unwrap();
            push(out, budget, b)?;
            stream.skip_ws()?;
            if stream.peek()? == Some(b'}') {
                let c = stream.next_byte()?.unwrap();
                return push(out, budget, c);
            }
            loop {
                collect_raw_value(stream, out, budget, depth + 1)?;
                stream.skip_ws()?;
                let colon = stream
                    .next_byte()?
                    .filter(|&c| c == b':')
                    .ok_or("StorageUnavailable：JSON对象缺冒号")?;
                push(out, budget, colon)?;
                collect_raw_value(stream, out, budget, depth + 1)?;
                stream.skip_ws()?;
                match stream.next_byte()? {
                    Some(b',') => push(out, budget, b',')?,
                    Some(b'}') => return push(out, budget, b'}'),
                    _ => return Err("StorageUnavailable：JSON对象未闭合".into()),
                }
            }
        }
        b'[' => {
            let b = stream.next_byte()?.unwrap();
            push(out, budget, b)?;
            stream.skip_ws()?;
            if stream.peek()? == Some(b']') {
                let c = stream.next_byte()?.unwrap();
                return push(out, budget, c);
            }
            loop {
                collect_raw_value(stream, out, budget, depth + 1)?;
                stream.skip_ws()?;
                match stream.next_byte()? {
                    Some(b',') => push(out, budget, b',')?,
                    Some(b']') => return push(out, budget, b']'),
                    _ => return Err("StorageUnavailable：JSON数组未闭合".into()),
                }
            }
        }
        b't' | b'f' | b'n' => {
            let expected: &[u8] = match first {
                b't' => b"true",
                b'f' => b"false",
                _ => b"null",
            };
            for &e in expected {
                let c = stream
                    .next_byte()?
                    .filter(|&x| x == e)
                    .ok_or("StorageUnavailable：JSON字面量非法")?;
                push(out, budget, c)?;
            }
            Ok(())
        }
        b'-' | b'0'..=b'9' => {
            while let Some(c) = stream.peek()? {
                if c.is_ascii_digit() || matches!(c, b'-' | b'+' | b'.' | b'e' | b'E') {
                    let b = stream.next_byte()?.unwrap();
                    push(out, budget, b)?;
                } else {
                    break;
                }
            }
            Ok(())
        }
        _ => Err("StorageUnavailable：JSON非法起始字节".into()),
    }
}

/// 流式构建 `EconomicProjectionView`（不加载完整 6.82 MB 原像；输出严格受 `READ_CACHE` 4 MiB 约束）。
pub(super) fn build_projection_document(
    c: &Connection,
    config: &Config,
    epoch: i64,
    runtime: &Value,
    selected: &StoredImage,
    job: Option<&mut Job>,
    deadline: Instant,
) -> Result<Vec<u8>, String> {
    let mut stream = ChunkedImageStream::new(c, selected, job, deadline);
    let mut budget = READ_CACHE;
    let mut path = Vec::new();
    let mut omitted = Vec::new();
    let projection = parse_projected_value(&mut stream, &mut budget, &mut path, &mut omitted, 0)?;
    if !projection.is_object() {
        return Err("StorageUnavailable：持久图像顶层非对象".into());
    }
    assert_no_json_numbers(&projection)?;
    let authoritative_image_hash = stream.finish_and_verify_root(config)?;
    let projection_canonical = canonical_json(&projection);
    let projection_bytes = projection_canonical.len();
    if projection_bytes > READ_CACHE {
        return Err("QueryBudgetExceeded：投影正文超过4MiB逻辑预算".into());
    }
    let projection_hash = sha256_hex(projection_canonical.as_bytes());
    let doc = json!({
        "kind": KIND_PROJECTION_VIEW,
        "projection_revision": PROJECTION_REVISION,
        "domain_id": config.domain,
        "session_id": config.session,
        "session_generation": config.generation,
        "cut": cut(config, selected.seq, &selected.root),
        "commit_ns": selected.commit_ns,
        "writer_epoch": epoch.to_string(),
        "audit_verified": true,
        "authoritative_image_hash": authoritative_image_hash,
        "authoritative_image_bytes": selected.bytes.to_string(),
        "projection_hash": projection_hash,
        "projection_bytes": projection_bytes.to_string(),
        "omitted_peer_images": omitted,
        "projection": projection,
        "runtime": runtime,
    });
    assert_no_json_numbers(&doc)?;
    let encoded = canonical_json(&doc).into_bytes();
    if encoded.len() > READ_CACHE {
        return Err("QueryBudgetExceeded：完整投影文档超过4MiB逻辑预算".into());
    }
    check_operation_deadline(None, Some(deadline))?;
    Ok(encoded)
}

fn check_receipt_not_after_cut(receipt: &Value, domain: &str, max_seq: i64) -> Result<(), String> {
    let rcut = &receipt["cut"];
    if rcut["domain_id"] != domain {
        return Err("StorageUnavailable：原回执域不匹配".into());
    }
    let rseq = nonnegative(required(rcut, "commit_seq")?, "receipt.cut.commit_seq")?;
    if rseq > max_seq {
        return Err("MissingDependency：回执晚于请求固定cut，拒绝泄漏未来状态".into());
    }
    Ok(())
}

/// 同切面按需取证：流式扫描指定 `cut` 的 `commits.image`（同样峰值 256 KiB 缓冲，核对全量原像根），
/// 仅取出目标 `kind` + `object_id` 在该切面实际存在的原件、精确 `raw_utf8`（原字节不动）、
/// 严格区分的精确文本视图与不超过 `cut.commit_seq` 的持久回执。
pub(super) fn build_original_at_cut_document(
    c: &Connection,
    config: &Config,
    epoch: i64,
    selected: &StoredImage,
    kind: &str,
    object_id: &str,
    job: Option<&mut Job>,
    deadline: Instant,
) -> Result<Vec<u8>, String> {
    if !matches!(
        kind,
        "fact" | "allocation" | "decision" | "grant" | "command" | "model"
    ) {
        return Err("SchemaUnsupported：未知同切面原件类型".into());
    }
    let mut stream = ChunkedImageStream::new(c, selected, job, deadline);
    let mut budget = READ_CACHE;
    let mut path = Vec::new();
    let mut omitted = Vec::new();
    let projected = parse_projected_value(&mut stream, &mut budget, &mut path, &mut omitted, 0)?;
    let authoritative_image_hash = stream.finish_and_verify_root(config)?;
    let at_cut = cut(config, selected.seq, &selected.root);

    let payload = match kind {
        "fact" => extract_fact_at_cut(c, config, selected, &projected, object_id)?,
        "allocation" => extract_allocation_at_cut(c, config, selected, &projected, object_id)?,
        "model" => extract_model_at_cut(config, &projected, object_id)?,
        "decision" => extract_decision_at_cut(c, config, selected, &projected, object_id)?,
        "grant" => extract_grant_at_cut(c, config, selected, &projected, object_id)?,
        "command" => extract_command_at_cut(c, config, selected, &projected, object_id)?,
        _ => unreachable!(),
    };

    let doc = json!({
        "kind": KIND_ORIGINAL_AT_CUT,
        "projection_revision": PROJECTION_REVISION,
        "domain_id": config.domain,
        "session_id": config.session,
        "session_generation": config.generation,
        "cut": at_cut,
        "commit_ns": selected.commit_ns,
        "writer_epoch": epoch.to_string(),
        "audit_verified": true,
        "authoritative_image_hash": authoritative_image_hash,
        "authoritative_image_bytes": selected.bytes.to_string(),
        "original_kind": kind,
        "object_id": object_id,
        "original": payload,
    });
    assert_no_json_numbers(&doc)?;
    let encoded = canonical_json(&doc).into_bytes();
    if encoded.len() > READ_CACHE {
        return Err("QueryBudgetExceeded：同切面原件文档超过4MiB逻辑预算".into());
    }
    check_operation_deadline(None, Some(deadline))?;
    Ok(encoded)
}

fn extract_fact_at_cut(
    c: &Connection,
    config: &Config,
    selected: &StoredImage,
    projected: &Value,
    fact_key: &str,
) -> Result<Value, String> {
    let recorded = projected["recorded"]
        .as_array()
        .ok_or("StorageUnavailable：recorded 缺失")?;
    let rec = recorded
        .iter()
        .find(|r| r["fact_key"] == fact_key)
        .ok_or("MissingDependency：指定固定切面不存在该事实原件")?;
    let raw_utf8 = required(rec, "raw_utf8")?;
    let raw_sha256 = required(rec, "raw_sha256")?;
    if sha256_hex(raw_utf8.as_bytes()) != raw_sha256 {
        return Err("StorageUnavailable：事实原件 raw_utf8 与 raw_sha256 不符".into());
    }
    let parsed_raw = strict_json(raw_utf8.as_bytes())?;
    let raw_exact_text = to_exact_decimal_text(&parsed_raw)?;

    let mut receipts = Vec::new();
    if config.domain == "E" {
        let receipt =
            row(c, "receipts", fact_key)?.ok_or("StorageUnavailable：E 事实缺持久回执")?;
        check_receipt_not_after_cut(&receipt, "E", selected.seq)?;
        receipts.push(receipt);
    } else {
        if let Some(e_receipt) = rec.get("e_receipt") {
            receipts.push(e_receipt.clone());
        }
        let app_id = super::tb03c_allocation::application_id(rec)?;
        if let Some(b_receipt) = row(c, "receipts", app_id)? {
            check_receipt_not_after_cut(&b_receipt, &config.domain, selected.seq)?;
            receipts.push(b_receipt);
        }
    }
    let fill_allocation_row = if config.domain == "E" {
        projected
            .get("fill_allocations")
            .and_then(Value::as_array)
            .and_then(|rows| rows.iter().find(|r| r["fact_key"] == fact_key).cloned())
    } else {
        None
    };
    Ok(json!({
        "kind": "EconomicFactAtCut",
        "domain_id": config.domain,
        "fact_key": fact_key,
        "fact_hash": rec["fact_hash"],
        "raw_sha256": raw_sha256,
        "json_pointer": rec["json_pointer"],
        "raw_utf8": raw_utf8,
        "raw_exact_text": {
            "representation": EXACT_TEXT_REPR,
            "raw_sha256": raw_sha256,
            "value": raw_exact_text,
        },
        "projected_record": rec,
        "fill_allocation_row": fill_allocation_row,
        "receipts": receipts,
    }))
}

fn extract_allocation_at_cut(
    c: &Connection,
    config: &Config,
    selected: &StoredImage,
    projected: &Value,
    allocation_id: &str,
) -> Result<Value, String> {
    if config.domain == "E" {
        let rows = projected
            .get("fill_allocations")
            .and_then(Value::as_array)
            .ok_or("MissingDependency：指定固定切面无 E 派生分配记录")?;
        let row_match = rows
            .iter()
            .find(|r| {
                r["allocations"]
                    .as_array()
                    .is_some_and(|al| al.iter().any(|a| a["allocation_id"] == allocation_id))
            })
            .ok_or("MissingDependency：指定固定切面不存在该 E 分配记录")?;
        let fact_key = required(row_match, "fact_key")?;
        let evidence_id = required(row_match, "evidence_id")?;
        let resolve_receipt = row(c, "receipts", &super::tb03c_e::receipt_key(evidence_id))?
            .ok_or("StorageUnavailable：E 分配缺 Resolve 持久回执")?;
        check_receipt_not_after_cut(&resolve_receipt, "E", selected.seq)?;
        let fact_detail = extract_fact_at_cut(c, config, selected, projected, fact_key)?;
        return Ok(json!({
            "kind": "EconomicAllocationAtCut",
            "domain_id": "E",
            "allocation_id": allocation_id,
            "fill_allocation_row": row_match,
            "resolve_receipt": resolve_receipt,
            "fact": fact_detail,
        }));
    }
    let applied = projected["applied"]
        .as_array()
        .ok_or("StorageUnavailable：applied 缺失")?;
    let app_entry = applied
        .iter()
        .find(|a| a["allocation_id"] == allocation_id)
        .ok_or("MissingDependency：指定固定切面不存在该 B 应用分配")?;
    let fact_key = required(app_entry, "fact_key")?;
    let application =
        row(c, "applications", allocation_id)?.ok_or("StorageUnavailable：B 应用记录缺失")?;
    let receipt = row(c, "receipts", allocation_id)?.ok_or("StorageUnavailable：B 应用回执缺失")?;
    check_receipt_not_after_cut(&receipt, &config.domain, selected.seq)?;
    let fact_detail = extract_fact_at_cut(c, config, selected, projected, fact_key)?;
    Ok(json!({
        "kind": "EconomicAllocationAtCut",
        "domain_id": config.domain,
        "allocation_id": allocation_id,
        "applied_entry": app_entry,
        "application": application,
        "receipt": receipt,
        "fact": fact_detail,
    }))
}

fn extract_model_at_cut(
    config: &Config,
    projected: &Value,
    object_id: &str,
) -> Result<Value, String> {
    let recorded = projected["recorded"]
        .as_array()
        .ok_or("StorageUnavailable：recorded 缺失")?;
    // 1. 先按 fact_key 找模拟原件；若在 E 上且按 command_id 查，则绑定该命令的 model_ref 并定位同命令模拟原件。
    let mut command_model_ref: Option<Value> = None;
    let mut matched_fact: Option<&Value> = recorded.iter().find(|r| r["fact_key"] == object_id);
    if config.domain == "E" {
        if let Some(cmds) = projected
            .get("finance")
            .and_then(|f| f.get("commands"))
            .and_then(Value::as_array)
        {
            if let Some(cmd) = cmds.iter().find(|c| c["command_id"] == object_id) {
                if cmd["state"] != "ReleasedExact" {
                    return Err("MissingDependency：指定切面该命令尚未 ReleasedExact".into());
                }
                let mr = cmd["command"]["model_ref"].clone();
                if !mr.is_object() {
                    return Err("MissingDependency：指定切面命令不含固化 model_ref".into());
                }
                command_model_ref = Some(mr);
                if matched_fact.is_none() {
                    matched_fact = recorded.iter().find(|r| {
                        r["event"]["event"] == crate::history_simulation::intake::EVENT
                            && (r["event"]["simulation_original_text_view"]["value"]["fill"]
                                ["command_id"]
                                == object_id
                                || r["event"]["simulation_original_text_view"]["value"]
                                    ["command_id"]
                                    == object_id)
                    });
                }
            }
        }
    }
    let Some(rec) = matched_fact else {
        if let Some(mr) = command_model_ref {
            return Ok(json!({
                "kind": "EconomicModelAtCut",
                "domain_id": config.domain,
                "object_id": object_id,
                "model_ref": mr,
                "model_raw_utf8": Value::Null,
                "model_exact_text": Value::Null,
                "source_fact_key": Value::Null,
            }));
        }
        return Err("MissingDependency：指定固定切面不存在对应模型原件或命令".into());
    };
    let raw_utf8 = required(rec, "raw_utf8")?;
    let doc = strict_json(raw_utf8.as_bytes())?;
    let model = &doc["model"];
    if !model.is_object() {
        return Err("MissingDependency：指定原件不含模拟模型对象".into());
    }
    let model_raw_utf8 = canonical_json(model);
    let model_hash = sha256_hex(model_raw_utf8.as_bytes());
    if doc["model_content_hash"] != model_hash {
        return Err("IdentityConflict：模拟原件内嵌 model 与 model_content_hash 不符".into());
    }
    let model_ref = json!({
        "model_id": required(model, "model_id")?,
        "revision": required(model, "revision")?,
        "content_hash": model_hash,
    });
    if let Some(ref cmd_mr) = command_model_ref {
        if cmd_mr != &model_ref {
            return Err("IdentityConflict：命令固化 model_ref 与模拟原件模型不符".into());
        }
    }
    Ok(json!({
        "kind": "EconomicModelAtCut",
        "domain_id": config.domain,
        "object_id": object_id,
        "source_fact_key": rec["fact_key"],
        "source_raw_sha256": rec["raw_sha256"],
        "model_ref": model_ref,
        "model_raw_utf8": model_raw_utf8,
        "model_exact_text": {
            "representation": EXACT_TEXT_REPR,
            "content_hash": model_hash,
            "value": to_exact_decimal_text(model)?,
        },
    }))
}

fn extract_decision_at_cut(
    c: &Connection,
    config: &Config,
    selected: &StoredImage,
    projected: &Value,
    decision_id: &str,
) -> Result<Value, String> {
    if config.domain == "E" {
        return Err("SchemaUnsupported：decision 仅属于 B 重".into());
    }
    let decisions = projected["finance"]["decisions"]
        .as_array()
        .ok_or("MissingDependency：指定切面无 decisions")?;
    let d = decisions
        .iter()
        .find(|x| x["decision_id"] == decision_id)
        .ok_or("MissingDependency：指定固定切面不存在该 decision")?;
    let mut receipts = Vec::new();
    for event in projected["history"]
        .as_array()
        .ok_or("StorageUnavailable：history 缺失")?
        .iter()
        .filter(|x| super::finance::is_event(x) && x["record"]["decision_id"] == decision_id)
    {
        let rk = super::finance::key_for(config, &event["request"]["payload"])?;
        let r = row(c, "receipts", &rk)?.ok_or("StorageUnavailable：决定缺原回执")?;
        check_receipt_not_after_cut(&r, &config.domain, selected.seq)?;
        receipts.push(r);
    }
    Ok(json!({
        "kind": "EconomicDecision",
        "domain_id": config.domain,
        "decision": d,
        "receipts": receipts,
    }))
}

fn extract_grant_at_cut(
    c: &Connection,
    config: &Config,
    selected: &StoredImage,
    projected: &Value,
    grant_id: &str,
) -> Result<Value, String> {
    if config.domain != "E" {
        return Err("SchemaUnsupported：grant 仅属于 E".into());
    }
    let slots = projected["finance"]["slots"]
        .as_array()
        .ok_or("MissingDependency：指定切面无 slots")?;
    for slot in slots {
        if let Some(g) = slot["grants"]
            .as_array()
            .and_then(|gs| gs.iter().find(|g| g["grant_id"] == grant_id))
        {
            let rk =
                super::finance::receipt_key_for(config, "Reserve", required(slot, "slot_id")?)?;
            let receipt = row(c, "receipts", &rk)?.ok_or("StorageUnavailable：grant 缺原回执")?;
            check_receipt_not_after_cut(&receipt, "E", selected.seq)?;
            return Ok(json!({
                "kind": "EconomicGrant",
                "domain_id": "E",
                "grant": g,
                "receipt": receipt,
            }));
        }
    }
    Err("MissingDependency：指定固定切面尚无该 grant".into())
}

fn extract_command_at_cut(
    c: &Connection,
    config: &Config,
    selected: &StoredImage,
    projected: &Value,
    command_id: &str,
) -> Result<Value, String> {
    if config.domain != "E" {
        return Err("SchemaUnsupported：command 仅属于 E".into());
    }
    let at = cut(config, selected.seq, &selected.root);
    let commands = projected["finance"]["commands"]
        .as_array()
        .ok_or("MissingDependency：指定切面无 commands")?;
    let Some(cmd) = commands.iter().find(|x| x["command_id"] == command_id) else {
        return Ok(json!({
            "kind": "EconomicCommand",
            "domain_id": "E",
            "command_id": command_id,
            "state": "NoRecord",
            "cut": at,
        }));
    };
    let mut receipts = Vec::new();
    for event in projected["history"]
        .as_array()
        .ok_or("StorageUnavailable：history 缺失")?
        .iter()
        .filter(|x| {
            matches!(
                x["kind"].as_str(),
                Some("MakeDispatchable" | "ReleaseExact")
            ) && x["record"]["decision_id"] == cmd["decision_id"]
        })
    {
        let rk = super::finance::key_for(config, &event["request"]["payload"])?;
        let r = row(c, "receipts", &rk)?.ok_or("StorageUnavailable：命令缺原回执")?;
        check_receipt_not_after_cut(&r, "E", selected.seq)?;
        receipts.push(r);
    }
    let _ = hash(cmd);
    Ok(json!({
        "kind": "EconomicCommand",
        "domain_id": "E",
        "command_id": command_id,
        "state": cmd["state"],
        "record": cmd,
        "receipts": receipts,
        "cut": at,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::params;
    use std::time::Duration;

    fn test_conn_with_commit(
        config: &Config,
        seq: i64,
        prev: &str,
        ns: &str,
        image: &Value,
    ) -> (Connection, StoredImage) {
        let c = Connection::open_in_memory().unwrap();
        c.execute(
            "CREATE TABLE commits(seq INTEGER PRIMARY KEY, prev_root TEXT NOT NULL, root TEXT NOT NULL, commit_ns TEXT NOT NULL, image TEXT NOT NULL)",
            [],
        )
        .unwrap();
        let raw = canonical_json(image);
        let img_hash = sha256_hex(raw.as_bytes());
        let r = root_with_image_hash(config, seq, prev, ns, &img_hash);
        c.execute(
            "INSERT INTO commits(seq, prev_root, root, commit_ns, image) VALUES(?,?,?,?,?)",
            params![seq, prev, r, ns, raw],
        )
        .unwrap();
        let meta = stored_image_meta(&c, seq).unwrap();
        (c, meta)
    }

    fn dummy_config() -> Config {
        Config {
            domain: "B:alpha".into(),
            session: "sess-proj-test".into(),
            generation: "1".into(),
            manifest_hash: "0".repeat(64),
            manifest: json!({"schema_revision": "economic-session/1"}),
            producer: "B:alpha:sess-proj-test".into(),
            db: std::path::PathBuf::from("/tmp/dummy.db"),
            socket: std::path::PathBuf::from("/tmp/dummy.sock"),
        }
    }

    #[test]
    fn streams_multi_chunk_peer_image_without_full_load_and_verifies_root() {
        let cfg = dummy_config();
        let big_pad = "x".repeat(600_000);
        let peer_img = json!({"book": null, "padding": big_pad});
        let expected_peer_hash = sha256_hex(canonical_json(&peer_img).as_bytes());
        let expected_peer_len = canonical_json(&peer_img).len();
        let raw_orig = canonical_json(&json!({
            "format": "history-sim-economic-originals/1",
            "event": {"fill": {"amount": 28, "price": 14, "quantity": 2, "fee": 1, "revision": 1}}
        }));
        let image = json!({
            "book": null,
            "pending": [],
            "applied": [],
            "unmatched": [],
            "recorded": [{
                "fact_key": "a".repeat(64),
                "fact_hash": "b".repeat(64),
                "raw_sha256": sha256_hex(raw_orig.as_bytes()),
                "json_pointer": "/event",
                "raw_utf8": raw_orig,
                "event": {
                    "event": "history-sim-unresolved/1",
                    "simulation_original": {"fill": {"amount": 28, "price": 14, "quantity": 2, "fee": 1, "revision": 1}}
                },
                "e_commit_proof": {
                    "previous_root": "1".repeat(64),
                    "commit_ns": "10",
                    "image": peer_img
                }
            }],
            "history": []
        });
        let (c, meta) = test_conn_with_commit(&cfg, 6, &"9".repeat(64), "10", &image);
        assert!(meta.bytes > 600_000);
        let deadline = Instant::now() + Duration::from_secs(10);
        // First confirm chunked streaming parameters directly.
        let mut stream = ChunkedImageStream::new(&c, &meta, None, deadline);
        let mut budget = READ_CACHE;
        let mut path = Vec::new();
        let mut omitted = Vec::new();
        let projected =
            parse_projected_value(&mut stream, &mut budget, &mut path, &mut omitted, 0).unwrap();
        assert!(stream.chunk_reads >= 3, "must stream in <=256KiB chunks");
        assert!(stream.max_chunk_bytes <= READ_CHUNK);
        let auth_hash = stream.finish_and_verify_root(&cfg).unwrap();
        assert_eq!(auth_hash, sha256_hex(canonical_json(&image).as_bytes()));
        assert_eq!(omitted.len(), 1);
        assert_eq!(omitted[0]["sha256"], expected_peer_hash);
        assert_eq!(omitted[0]["byte_len"], expected_peer_len.to_string());
        assert_eq!(
            projected["recorded"][0]["e_commit_proof"]["image_omitted"]["sha256"],
            expected_peer_hash
        );
        assert!(projected["recorded"][0]["e_commit_proof"]
            .get("image")
            .is_none());
        assert_eq!(
            projected["recorded"][0]["event"]["simulation_original_text_view"]["representation"],
            EXACT_TEXT_REPR
        );
        assert_eq!(
            projected["recorded"][0]["event"]["simulation_original_text_view"]["value"]["fill"]
                ["amount"],
            "28"
        );
        assert!(projected["recorded"][0]["event"]
            .get("simulation_original")
            .is_none());
        assert_no_json_numbers(&projected).unwrap();

        // Also check full build_projection_document + separate hashes.
        let doc_bytes =
            build_projection_document(&c, &cfg, 1, &json!({}), &meta, None, deadline).unwrap();
        let doc = strict_json(&doc_bytes).unwrap();
        assert_eq!(doc["kind"], KIND_PROJECTION_VIEW);
        assert_eq!(doc["projection_revision"], PROJECTION_REVISION);
        assert_eq!(doc["authoritative_image_hash"], auth_hash);
        assert_ne!(doc["projection_hash"], doc["authoritative_image_hash"]);
        assert!(doc_bytes.len() < 4096);
    }

    #[test]
    fn rejects_tampered_stored_image_against_cut_root() {
        let cfg = dummy_config();
        let image = json!({"book": null, "recorded": [], "pending": [], "applied": [], "unmatched": [], "history": []});
        let (c, meta) = test_conn_with_commit(&cfg, 1, &"9".repeat(64), "5", &image);
        // Tamper root in meta so stored bytes no longer match root_with_image_hash.
        c.execute(
            "UPDATE commits SET root=? WHERE seq=1",
            [format!("f{}", &"0".repeat(63))],
        )
        .unwrap();
        let bad_meta = stored_image_meta(&c, 1).unwrap();
        assert_ne!(bad_meta.root, meta.root);
        let err_msg = build_projection_document(
            &c,
            &cfg,
            1,
            &json!({}),
            &bad_meta,
            None,
            Instant::now() + Duration::from_secs(10),
        )
        .unwrap_err();
        assert!(
            err_msg.contains("原像摘要与持久cut根不符"),
            "unexpected: {err_msg}"
        );
    }

    #[test]
    fn rejects_non_integer_number_in_exact_decimal_text() {
        let err_msg = to_exact_decimal_text(&json!({"x": 1.25})).unwrap_err();
        assert!(err_msg.contains("非整数"), "unexpected: {err_msg}");
    }
}
