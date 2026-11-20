//! #1425 方案 1：固定切面的只读经济投影（`economic-read-projection/1`）与同切面按需取证。
//!
//! 适用合同与三类读取成本边界：
//! - 合同收口：仅适用于 `economic-session/1` + `tb03b-finance/6` + `tb03c-book/*`，不向 `/2` 或旧财务/旧书账开放；
//!   不改写协议、不改原 SQLite 表结构/根链/审计、不抬 4 MiB/1 MiB 上限，不为旧 `/1` 用法新增 Job 前置。
//! - 成本 1（完整离线重放 `audit_with_budget`）：每次 `EconomicReadOpen` 沿既有完整离线审计逐提交重放
//!   `commits.image`（见 `store.rs::audit_with_budget`），这是全历史完整性重放开销，并非 256 KiB 分片缓冲。
//! - 成本 2（256 KiB 分片投影扫描 `build_projection_document`）：通过 `store::stored_image_bytes_metered`
//!   按 `READ_CHUNK`（256 KiB）流式分块读取目标 cut 的 `commits.image`，边算完整原像 `SHA-256` 并核对
//!   `cut.root_hash`，边零缓冲跳过并摘要 8 类跨 owner 嵌入全镜像证明子树；投影输出严格 ≤ 4 MiB 共享缓存帽，
//!   传输帧 ≤ 1 MiB。
//! - 成本 3（同切面按需取证 `build_original_at_cut_document`）：同 256 KiB 流式扫描 + `ReadBudget` 计量
//!   `receipts`/`applications` 查询，按调用方实际获准权限一一绑定返回证据类别，绝不借命令/分配读未授权原字节。
//! - 所有新 SQL 均沿 `ReadBudget` 在 I/O 前后同时守 Job 与最早绝对期限，并在适用 Job 时先记实读字节。
//! - 严格区分权威原像与投影视图：`authoritative_image_hash`/`authoritative_image_bytes` 绑定全量原像与
//!   `cut.root_hash`，`projection_hash`/`projection_bytes` 仅绑定投影正文，不把截字段后的摘要当全镜像或包含证明。
//! - 原件精确字节不改：面向浏览器的整数精确表示单列在 `simulation_original_text_view` / `*_exact_text`
//!   （显式 `representation = "ExactDecimalIntegerTextProjection"`），不放松客户端严格 JSON 解析器，也不回退 `latest`。
use super::book::hash;
use super::service::{READ_CACHE, READ_CHUNK};
use super::store::{
    cut, metered_row, root_with_image_hash, stored_image_bytes_metered, stored_image_meta_metered,
    Config, ReadBudget, StoredImage, SCHEMA_V1,
};
use super::voice::exact;
use crate::session_protocol::{canonical_json, nonnegative, required, sha256_hex, strict_json};
use rusqlite::Connection;
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

pub(super) const PROJECTION_REVISION: &str = "economic-read-projection/1";
pub(super) const OP_READ_PROJECTION: &str = "ReadProjection";
pub(super) const OP_READ_ORIGINAL_AT_CUT: &str = "ReadOriginalAtCut";
pub(super) const KIND_PROJECTION_VIEW: &str = "EconomicProjectionView";
pub(super) const KIND_ORIGINAL_AT_CUT: &str = "EconomicOriginalAtCut";
const EXACT_TEXT_REPR: &str = "ExactDecimalIntegerTextProjection";
const MAX_JSON_DEPTH: usize = 128;

/// 同切面取证的实际获准权限快照：每项证据类别与所授只读权限一一绑定，不扩权。
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub(super) struct ReadPermissions {
    pub query_fact: bool,
    pub query_allocation: bool,
    pub query_decision: bool,
    pub query_grant: bool,
    pub query_command: bool,
}

/// 明确收口 `economic-read-projection/1` 适用合同：仅 `economic-session/1` + `tb03b-finance/6` + `tb03c-book/*`。
pub(super) fn check_projection_contract(config: &Config) -> Result<(), String> {
    if config.revision()? != SCHEMA_V1
        || !config.book_rules()?.is_tb03c()
        || config.manifest["finance"]["schema_revision"] != "tb03b-finance/6"
    {
        return Err(
            "SchemaUnsupported：economic-read-projection/1 仅适用于 economic-session/1 + tb03b-finance/6 + tb03c-book/* 合同"
                .into(),
        );
    }
    Ok(())
}

/// 为 `EconomicReadOpen` 中的投影/同切面取证校验合同边界与原逻辑授权（不扩权、不改 `BASE_OPS`）。
pub(super) fn check_authorization(
    config: &Config,
    envelope: &Value,
    query: &Value,
) -> Result<ReadPermissions, String> {
    check_projection_contract(config)?;
    let op = required(query, "op")?;
    let check_op = |required_op: &str| -> Result<(), String> {
        let mut req = envelope.clone();
        req["payload"] = json!({"op": required_op});
        config.authorized(&req)
    };
    let perms = ReadPermissions {
        query_fact: check_op("QueryFact").is_ok(),
        query_allocation: check_op("QueryAllocation").is_ok(),
        query_decision: check_op("QueryDecision").is_ok(),
        query_grant: check_op("QueryGrant").is_ok(),
        query_command: check_op("QueryCommand").is_ok(),
    };
    match op {
        OP_READ_PROJECTION => {
            check_op("ReadView")?;
            Ok(perms)
        }
        OP_READ_ORIGINAL_AT_CUT => {
            check_op("ReadView")?;
            match required(query, "kind")? {
                "fact" => check_op("QueryFact")?,
                "allocation" => check_op("QueryAllocation")?,
                "decision" => check_op("QueryDecision")?,
                "grant" => check_op("QueryGrant")?,
                "command" => check_op("QueryCommand")?,
                "model" => {
                    if config.domain == "E" {
                        if !perms.query_command && !perms.query_fact {
                            return Err("InvalidDomain：来源未获准执行该操作".into());
                        }
                    } else {
                        check_op("QueryFact")?;
                    }
                }
                _ => return Err("SchemaUnsupported：未知同切面取证原件类型".into()),
            }
            Ok(perms)
        }
        _ => Err("SchemaUnsupported：未知投影读取操作".into()),
    }
}

/// 选择固定 cut 的只读元数据（走 `ReadBudget` 计量与最早截止检查；不施加 4 MiB 原像上限）。
/// 不存在、根不匹配或未来 cut 均当场拒绝，绝不回退 `latest`。
pub(super) fn select_projection_meta(
    c: &Connection,
    config: &Config,
    query: &Value,
    require_explicit_cut: bool,
    budget: &mut ReadBudget<'_>,
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
        budget
            .one(
                c,
                "SELECT max(seq) FROM commits WHERE CAST(commit_ns AS INTEGER)<=?",
                [ns],
                |r| r.get::<_, Option<i64>>(0),
            )?
            .ok_or("MissingDependency：AsKnown早于域创世")?
    } else {
        budget
            .one(c, "SELECT max(seq) FROM commits", [], |r| {
                r.get::<_, Option<i64>>(0)
            })?
            .ok_or("MissingDependency：域无创世cut")?
    };
    let meta = stored_image_meta_metered(c, selected, budget)?;
    if !query["cut"].is_null() && query["cut"] != cut(config, meta.seq, &meta.root) {
        return Err("IdentityConflict：cut根不匹配".into());
    }
    Ok(meta)
}

/// 分块流式读取器：每次仅从 SQLite 读至多 `READ_CHUNK`（256 KiB）字节，
/// 全程经由共同 `ReadBudget` 在 I/O 前后检查 Job 与最早截止、先计实读字节，并推进全量原像 `Sha256`。
struct ChunkedImageStream<'a, 'b> {
    c: &'a Connection,
    meta: &'a StoredImage,
    budget: &'a mut ReadBudget<'b>,
    offset: usize,
    buf: Vec<u8>,
    pos: usize,
    hasher: Sha256,
    chunk_reads: usize,
    max_chunk_bytes: usize,
}

impl<'a, 'b> ChunkedImageStream<'a, 'b> {
    fn new(c: &'a Connection, meta: &'a StoredImage, budget: &'a mut ReadBudget<'b>) -> Self {
        Self {
            c,
            meta,
            budget,
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
        let take = READ_CHUNK.min(self.meta.bytes - self.offset);
        let chunk = stored_image_bytes_metered(self.c, self.meta, self.offset, take, self.budget)?;
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
        self.budget.before()?;
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
    stream: &mut ChunkedImageStream<'_, '_>,
    depth: usize,
) -> Result<(String, usize), String> {
    let mut hasher = Sha256::new();
    let mut len = 0usize;
    skip_into_hasher(stream, &mut hasher, &mut len, depth)?;
    let digest = hasher.finalize();
    Ok((digest.iter().map(|b| format!("{b:02x}")).collect(), len))
}

fn skip_into_hasher(
    stream: &mut ChunkedImageStream<'_, '_>,
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
                if !stream.refill()? {
                    return Err("StorageUnavailable：JSON字符串未闭合".into());
                }
                let start = stream.pos;
                let slice = &stream.buf[start..];
                let mut i = 0usize;
                let mut closed = false;
                while i < slice.len() {
                    let c = slice[i];
                    i += 1;
                    if escaped {
                        escaped = false;
                    } else if c == b'\\' {
                        escaped = true;
                    } else if c == b'"' {
                        closed = true;
                        break;
                    }
                }
                hasher.update(&slice[..i]);
                *len += i;
                stream.pos = start + i;
                if closed {
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
    stream: &mut ChunkedImageStream<'_, '_>,
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
    stream: &mut ChunkedImageStream<'_, '_>,
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
    stream: &mut ChunkedImageStream<'_, '_>,
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

/// 流式构建 `EconomicProjectionView`（投影扫描峰值读缓冲 256 KiB；输出严格受 `READ_CACHE` 4 MiB 约束；
/// 所有分片 SQL 沿 `ReadBudget` 计量并守最早绝对期限）。
pub(super) fn build_projection_document(
    c: &Connection,
    config: &Config,
    epoch: i64,
    runtime: &Value,
    selected: &StoredImage,
    budget: &mut ReadBudget<'_>,
) -> Result<Vec<u8>, String> {
    let mut stream = ChunkedImageStream::new(c, selected, budget);
    let mut doc_budget = READ_CACHE;
    let mut path = Vec::new();
    let mut omitted = Vec::new();
    let projection =
        parse_projected_value(&mut stream, &mut doc_budget, &mut path, &mut omitted, 0)?;
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
    budget.before()?;
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

/// 同切面按需取证：流式扫描指定 `cut` 的 `commits.image`（峰值 256 KiB 缓冲，核对全量原像根），
/// 严格按 `perms` 将每项返回原件与获准读权一一绑定；所有 SQL 经由同一 `ReadBudget` 计量并守截止。
#[allow(clippy::too_many_arguments)]
pub(super) fn build_original_at_cut_document(
    c: &Connection,
    config: &Config,
    epoch: i64,
    selected: &StoredImage,
    kind: &str,
    object_id: &str,
    perms: &ReadPermissions,
    budget: &mut ReadBudget<'_>,
) -> Result<Vec<u8>, String> {
    if !matches!(
        kind,
        "fact" | "allocation" | "decision" | "grant" | "command" | "model"
    ) {
        return Err("SchemaUnsupported：未知同切面原件类型".into());
    }
    let authoritative_image_hash;
    let projected = {
        let mut stream = ChunkedImageStream::new(c, selected, budget);
        let mut doc_budget = READ_CACHE;
        let mut path = Vec::new();
        let mut omitted = Vec::new();
        let val = parse_projected_value(&mut stream, &mut doc_budget, &mut path, &mut omitted, 0)?;
        authoritative_image_hash = stream.finish_and_verify_root(config)?;
        val
    };
    let at_cut = cut(config, selected.seq, &selected.root);

    let payload = match kind {
        "fact" => extract_fact_at_cut(c, config, selected, &projected, object_id, perms, budget)?,
        "allocation" => {
            extract_allocation_at_cut(c, config, selected, &projected, object_id, perms, budget)?
        }
        "model" => extract_model_at_cut(config, &projected, object_id, perms)?,
        "decision" => extract_decision_at_cut(c, config, selected, &projected, object_id, budget)?,
        "grant" => extract_grant_at_cut(c, config, selected, &projected, object_id, budget)?,
        "command" => extract_command_at_cut(c, config, selected, &projected, object_id, budget)?,
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
    budget.before()?;
    Ok(encoded)
}

fn extract_fact_at_cut(
    c: &Connection,
    config: &Config,
    selected: &StoredImage,
    projected: &Value,
    fact_key: &str,
    perms: &ReadPermissions,
    budget: &mut ReadBudget<'_>,
) -> Result<Value, String> {
    if !perms.query_fact {
        return Err("InvalidDomain：来源未获准 QueryFact，不能读取事实原件".into());
    }
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
        let receipt = metered_row(c, "receipts", fact_key, budget)?
            .ok_or("StorageUnavailable：E 事实缺持久回执")?;
        check_receipt_not_after_cut(&receipt, "E", selected.seq)?;
        receipts.push(receipt);
    } else {
        if let Some(e_receipt) = rec.get("e_receipt") {
            receipts.push(e_receipt.clone());
        }
        let app_id = super::tb03c_allocation::application_id(rec)?;
        if let Some(b_receipt) = metered_row(c, "receipts", app_id, budget)? {
            check_receipt_not_after_cut(&b_receipt, &config.domain, selected.seq)?;
            receipts.push(b_receipt);
        }
    }
    let fill_allocation_row = if config.domain == "E" && perms.query_allocation {
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
    perms: &ReadPermissions,
    budget: &mut ReadBudget<'_>,
) -> Result<Value, String> {
    if !perms.query_allocation {
        return Err("InvalidDomain：来源未获准 QueryAllocation，不能读取分配原件".into());
    }
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
        let fact_hash = required(row_match, "fact_hash")?;
        let evidence_id = required(row_match, "evidence_id")?;
        let resolve_receipt = metered_row(
            c,
            "receipts",
            &super::tb03c_e::receipt_key(evidence_id),
            budget,
        )?
        .ok_or("StorageUnavailable：E 分配缺 Resolve 持久回执")?;
        check_receipt_not_after_cut(&resolve_receipt, "E", selected.seq)?;
        // 仅当同时获准 QueryFact 才连带事实原字节与原回执；否则只留具名引用，不读不返回原件字节。
        let fact_detail = if perms.query_fact {
            extract_fact_at_cut(c, config, selected, projected, fact_key, perms, budget)?
        } else {
            Value::Null
        };
        return Ok(json!({
            "kind": "EconomicAllocationAtCut",
            "domain_id": "E",
            "allocation_id": allocation_id,
            "fill_allocation_row": row_match,
            "resolve_receipt": resolve_receipt,
            "fact_ref": {"fact_key": fact_key, "fact_hash": fact_hash},
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
    let fact_hash = required(app_entry, "fact_hash")?;
    let application = metered_row(c, "applications", allocation_id, budget)?
        .ok_or("StorageUnavailable：B 应用记录缺失")?;
    let receipt = metered_row(c, "receipts", allocation_id, budget)?
        .ok_or("StorageUnavailable：B 应用回执缺失")?;
    check_receipt_not_after_cut(&receipt, &config.domain, selected.seq)?;
    // 仅当同时获准 QueryFact 才连带事实原字节与原回执；否则只留具名引用。
    let fact_detail = if perms.query_fact {
        extract_fact_at_cut(c, config, selected, projected, fact_key, perms, budget)?
    } else {
        Value::Null
    };
    Ok(json!({
        "kind": "EconomicAllocationAtCut",
        "domain_id": config.domain,
        "allocation_id": allocation_id,
        "applied_entry": app_entry,
        "application": application,
        "receipt": receipt,
        "fact_ref": {"fact_key": fact_key, "fact_hash": fact_hash},
        "fact": fact_detail,
    }))
}

fn extract_model_at_cut(
    config: &Config,
    projected: &Value,
    object_id: &str,
    perms: &ReadPermissions,
) -> Result<Value, String> {
    let recorded = projected["recorded"]
        .as_array()
        .ok_or("StorageUnavailable：recorded 缺失")?;
    // 授权与查找/返回分支严格一一绑定：
    // - QueryCommand 仅可按命令查找并读取命令固化的 model_ref，无 QueryFact 时绝不遍历 recorded 或返回事实模型原字节；
    // - QueryFact 仅可按 fact_key 从事实原件读取 model_raw_utf8，无 QueryCommand 时绝不遍历 finance.commands。
    let mut command_model_ref: Option<Value> = None;
    let mut matched_fact: Option<&Value> = if perms.query_fact {
        recorded.iter().find(|r| r["fact_key"] == object_id)
    } else {
        None
    };
    if config.domain == "E" && perms.query_command {
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
                if perms.query_fact && matched_fact.is_none() {
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
        if config.domain == "E" && !perms.query_fact {
            return Err("InvalidDomain：来源未获准 QueryFact，不能按事实原件读取模型原字节".into());
        }
        if config.domain == "E" && !perms.query_command {
            return Err(
                "InvalidDomain：来源未获准 QueryCommand，且指定切面不存在该事实模型原件".into(),
            );
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
    budget: &mut ReadBudget<'_>,
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
        let r =
            metered_row(c, "receipts", &rk, budget)?.ok_or("StorageUnavailable：决定缺原回执")?;
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
    budget: &mut ReadBudget<'_>,
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
            let receipt = metered_row(c, "receipts", &rk, budget)?
                .ok_or("StorageUnavailable：grant 缺原回执")?;
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
    budget: &mut ReadBudget<'_>,
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
        let r =
            metered_row(c, "receipts", &rk, budget)?.ok_or("StorageUnavailable：命令缺原回执")?;
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
    use crate::s_content::job::{Existing, Job, JobLimits, DEADLINE, LIMIT_EXCEEDED};
    use rusqlite::params;
    use std::cell::Cell;
    use std::rc::Rc;
    use std::time::{Duration, Instant};

    fn test_conn_with_commit(
        config: &Config,
        seq: i64,
        prev: &str,
        ns: &str,
        image: &Value,
    ) -> (Connection, StoredImage) {
        let c = Connection::open_in_memory().unwrap();
        c.execute_batch(
            "CREATE TABLE commits(seq INTEGER PRIMARY KEY, prev_root TEXT NOT NULL, root TEXT NOT NULL, commit_ns TEXT NOT NULL, image TEXT NOT NULL);
             CREATE TABLE receipts(k TEXT PRIMARY KEY, json TEXT NOT NULL);
             CREATE TABLE applications(k TEXT PRIMARY KEY, fact_key TEXT NOT NULL UNIQUE, json TEXT NOT NULL);",
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
        let meta = super::super::store::stored_image_meta(&c, seq).unwrap();
        (c, meta)
    }

    fn fin6_config(domain: &str, ops: &[&str]) -> Config {
        Config {
            domain: domain.into(),
            session: "sess-proj-test".into(),
            generation: "1".into(),
            manifest_hash: "0".repeat(64),
            manifest: json!({
                "schema_revision": "economic-manifest/1",
                "protocol_revision": "economic-session/1",
                "book_revision": "tb03c-book/1",
                "finance": {"schema_revision": "tb03b-finance/6"},
                "authorized_sources": [{
                    "source_namespace": "q-test",
                    "source_epoch": "1",
                    "producer_id": "Q:sess-proj-test",
                    "producer_epoch": "1",
                    "operations": ops
                }]
            }),
            producer: format!("{domain}:sess-proj-test"),
            db: std::path::PathBuf::from("/tmp/dummy.db"),
            socket: std::path::PathBuf::from("/tmp/dummy.sock"),
        }
    }

    fn dummy_config() -> Config {
        fin6_config("B:alpha", &["ReadView", "QueryFact", "QueryAllocation"])
    }

    fn q_envelope() -> Value {
        json!({
            "session_id": "sess-proj-test",
            "session_generation": "1",
            "source_namespace": "q-test",
            "source_epoch": "1",
            "producer_id": "Q:sess-proj-test",
            "producer_epoch": "1",
            "payload": {}
        })
    }

    fn big_image_with_peer_proof() -> (Value, String, usize) {
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
        (image, expected_peer_hash, expected_peer_len)
    }

    #[test]
    fn streams_multi_chunk_peer_image_without_full_load_and_verifies_root() {
        let cfg = dummy_config();
        let (image, expected_peer_hash, expected_peer_len) = big_image_with_peer_proof();
        let (c, meta) = test_conn_with_commit(&cfg, 6, &"9".repeat(64), "10", &image);
        assert!(meta.bytes > 600_000);
        let deadline = Instant::now() + Duration::from_secs(10);
        let mut budget = ReadBudget::new(None, Some(deadline));
        let mut stream = ChunkedImageStream::new(&c, &meta, &mut budget);
        let mut doc_budget = READ_CACHE;
        let mut path = Vec::new();
        let mut omitted = Vec::new();
        let projected =
            parse_projected_value(&mut stream, &mut doc_budget, &mut path, &mut omitted, 0)
                .unwrap();
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

        let mut budget2 = ReadBudget::new(None, Some(deadline));
        let doc_bytes =
            build_projection_document(&c, &cfg, 1, &json!({}), &meta, &mut budget2).unwrap();
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
        c.execute(
            "UPDATE commits SET root=? WHERE seq=1",
            [format!("f{}", &"0".repeat(63))],
        )
        .unwrap();
        let bad_meta = super::super::store::stored_image_meta(&c, 1).unwrap();
        assert_ne!(bad_meta.root, meta.root);
        let mut budget = ReadBudget::new(None, Some(Instant::now() + Duration::from_secs(10)));
        let err_msg =
            build_projection_document(&c, &cfg, 1, &json!({}), &bad_meta, &mut budget).unwrap_err();
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

    fn test_job_limits(max_wire: u64, max_ms: u64) -> JobLimits {
        JobLimits {
            max_total_wire_bytes: max_wire,
            max_total_node_bytes: 16_777_216,
            max_total_nodes: 100_000,
            max_total_records: 100_000,
            max_total_requests: 100,
            max_elapsed_ms: max_ms,
            max_staged_bytes: 16_777_216,
            max_store_bytes: 16_777_216,
        }
    }

    #[test]
    fn job_wire_byte_cap_stops_chunked_projection_without_extra_reads_or_success() {
        let cfg = dummy_config();
        let (image, _, _) = big_image_with_peer_proof();
        let (c, meta) = test_conn_with_commit(&cfg, 6, &"9".repeat(64), "10", &image);
        // 3 chunks (~600KB > 524,288B): cap allows chunk 1 (262,144) but trips right on chunk 2 (524,288 > 400,000).
        let clock = Rc::new(Cell::new(Instant::now()));
        let clock_job = clock.clone();
        let mut job = Job::new(
            test_job_limits(400_000, 10_000),
            Existing {
                store_bytes: 0,
                staged_bytes: 0,
            },
            Box::new(move || clock_job.get()),
        )
        .unwrap();
        let mut budget = ReadBudget::new(
            Some(&mut job),
            Some(Instant::now() + Duration::from_secs(30)),
        );
        let err =
            build_projection_document(&c, &cfg, 1, &json!({}), &meta, &mut budget).unwrap_err();
        assert!(
            err.starts_with("Incomplete：SQL 实读累计"),
            "unexpected: {err}"
        );
        let snap = job.snapshot();
        assert_eq!(snap.stopped, Some(LIMIT_EXCEEDED));
        // Stopped immediately after chunk 2 was charged; chunk 3 was NEVER read!
        assert_eq!(snap.wire_bytes, u128::from((READ_CHUNK * 2) as u64));
    }

    #[test]
    fn job_earlier_deadline_stops_before_next_chunk_even_when_ingress_deadline_is_far() {
        let cfg = dummy_config();
        let (image, _, _) = big_image_with_peer_proof();
        let (c, meta) = test_conn_with_commit(&cfg, 6, &"9".repeat(64), "10", &image);
        let clock = Rc::new(Cell::new(Instant::now()));
        let clock_job = clock.clone();
        let mut job = Job::new(
            test_job_limits(16_777_216, 1),
            Existing {
                store_bytes: 0,
                staged_bytes: 0,
            },
            Box::new(move || clock_job.get()),
        )
        .unwrap();
        // Advance job clock on return of SQL #1 (chunk 1), while ingress deadline is 60s in the future!
        let _guard = super::super::tb03c_c5_read_tests::expire_after_sql_returns(clock, 1);
        let mut budget = ReadBudget::new(
            Some(&mut job),
            Some(Instant::now() + Duration::from_secs(60)),
        );
        let err =
            build_projection_document(&c, &cfg, 1, &json!({}), &meta, &mut budget).unwrap_err();
        assert!(err.starts_with("Incomplete"), "unexpected: {err}");
        let snap = job.snapshot();
        assert_eq!(snap.stopped, Some(DEADLINE));
        // Chunk 1 returned and was accounted, then stopped before chunk 2 ever ran!
        assert_eq!(snap.wire_bytes, u128::from(READ_CHUNK as u64));
    }

    #[test]
    fn job_meters_select_meta_and_original_receipt_sql_rows() {
        let cfg = fin6_config("E", &["ReadView", "QueryFact", "QueryAllocation"]);
        let raw_orig = canonical_json(&json!({
            "format": "history-sim-economic-originals/1",
            "model": {"model_id": "m1", "revision": "r1"},
            "model_content_hash": sha256_hex(canonical_json(&json!({"model_id": "m1", "revision": "r1"})).as_bytes()),
            "event": {"kind": "fill", "fill": {"command_id": "cmd-1", "amount": 28}}
        }));
        let fk = "a".repeat(64);
        let image = json!({
            "book": null,
            "recorded": [{
                "fact_key": fk,
                "fact_hash": "b".repeat(64),
                "raw_sha256": sha256_hex(raw_orig.as_bytes()),
                "json_pointer": "/event",
                "raw_utf8": raw_orig,
                "event": {"event": "history-sim-unresolved/1", "simulation_original": {"kind": "fill"}}
            }],
            "pending": [],
            "applied": [],
            "unmatched": [],
            "history": []
        });
        let (c, meta) = test_conn_with_commit(&cfg, 3, &"9".repeat(64), "10", &image);
        let receipt = json!({"kind": "Recorded", "domain_id": "E", "fact_key": fk, "cut": cut(&cfg, 3, &meta.root)});
        c.execute(
            "INSERT INTO receipts(k, json) VALUES(?, ?)",
            params![fk, canonical_json(&receipt)],
        )
        .unwrap();
        let clock = Rc::new(Cell::new(Instant::now()));
        let clock_job = clock.clone();
        let mut job = Job::new(
            test_job_limits(16_777_216, 10_000),
            Existing {
                store_bytes: 0,
                staged_bytes: 0,
            },
            Box::new(move || clock_job.get()),
        )
        .unwrap();
        let mut budget = ReadBudget::new(
            Some(&mut job),
            Some(Instant::now() + Duration::from_secs(10)),
        );
        let selected = select_projection_meta(
            &c,
            &cfg,
            &json!({"op": OP_READ_ORIGINAL_AT_CUT, "projection_revision": PROJECTION_REVISION, "cut": cut(&cfg, 3, &meta.root), "kind": "fact", "object_id": fk}),
            true,
            &mut budget,
        )
        .unwrap();
        let bytes_after_select = budget.job.as_deref().unwrap().snapshot().wire_bytes;
        assert!(
            bytes_after_select > 0,
            "select_projection_meta must charge ReadBudget"
        );
        let perms = ReadPermissions {
            query_fact: true,
            ..ReadPermissions::default()
        };
        let doc = build_original_at_cut_document(
            &c,
            &cfg,
            1,
            &selected,
            "fact",
            &fk,
            &perms,
            &mut budget,
        )
        .unwrap();
        assert!(!doc.is_empty());
        let bytes_after_orig = job.snapshot().wire_bytes;
        assert!(
            bytes_after_orig >= bytes_after_select + u128::from(meta.bytes as u64) + u128::from(canonical_json(&receipt).len() as u64),
            "chunk scan + receipt row must both be metered in ReadBudget: {bytes_after_orig} vs {bytes_after_select}"
        );
    }

    #[test]
    fn authorization_isolation_binds_model_and_allocation_to_granted_evidence_kind() {
        let model = json!({"model_id": "m1", "revision": "r1"});
        let model_raw = canonical_json(&model);
        let model_hash = sha256_hex(model_raw.as_bytes());
        let raw_orig = canonical_json(&json!({
            "format": "history-sim-economic-originals/1",
            "model": model,
            "model_content_hash": model_hash,
            "event": {"kind": "fill", "fill": {"command_id": "cmd-alpha", "amount": 28}}
        }));
        let fk = "a".repeat(64);
        let aid = "sim-command:1";
        let ev_id = "ev-1";
        let image = json!({
            "book": null,
            "recorded": [{
                "fact_key": fk,
                "fact_hash": "b".repeat(64),
                "raw_sha256": sha256_hex(raw_orig.as_bytes()),
                "json_pointer": "/event",
                "raw_utf8": raw_orig,
                "event": {"event": "history-sim-unresolved/1", "simulation_original": {"kind": "fill", "fill": {"command_id": "cmd-alpha", "amount": 28}}}
            }],
            "pending": [],
            "applied": [],
            "unmatched": [],
            "fill_allocations": [{
                "fact_key": fk,
                "fact_hash": "b".repeat(64),
                "source_kind": "history_sim_fill",
                "evidence_id": ev_id,
                "allocations": [{"allocation_id": aid, "chong_id": "alpha"}]
            }],
            "finance": {
                "schema_revision": "tb03b-finance/6",
                "commands": [{
                    "command_id": "cmd-alpha",
                    "state": "ReleasedExact",
                    "command": {
                        "model_ref": {"model_id": "m1", "revision": "r1", "content_hash": model_hash}
                    }
                }]
            },
            "history": []
        });
        let cfg_all = fin6_config(
            "E",
            &["ReadView", "QueryFact", "QueryAllocation", "QueryCommand"],
        );
        let (c, meta) = test_conn_with_commit(&cfg_all, 5, &"9".repeat(64), "10", &image);
        let fact_receipt = json!({"kind": "Recorded", "domain_id": "E", "fact_key": fk, "cut": cut(&cfg_all, 5, &meta.root)});
        let res_receipt = json!({"kind": "Resolved", "domain_id": "E", "evidence_id": ev_id, "cut": cut(&cfg_all, 5, &meta.root)});
        c.execute(
            "INSERT INTO receipts(k, json) VALUES(?, ?), (?, ?)",
            params![
                fk,
                canonical_json(&fact_receipt),
                super::super::tb03c_e::receipt_key(ev_id),
                canonical_json(&res_receipt)
            ],
        )
        .unwrap();

        let env = q_envelope();
        let deadline = Instant::now() + Duration::from_secs(10);

        // 1. QueryCommand-only: querying model by command_id returns ONLY model_ref (no model_raw_utf8!);
        //    querying model by fact_key is REJECTED.
        let cfg_cmd_only = fin6_config("E", &["ReadView", "QueryCommand"]);
        let perms_cmd = check_authorization(
            &cfg_cmd_only,
            &env,
            &json!({"op": OP_READ_ORIGINAL_AT_CUT, "kind": "model", "object_id": "cmd-alpha"}),
        )
        .unwrap();
        assert!(perms_cmd.query_command && !perms_cmd.query_fact);
        let mut b1 = ReadBudget::new(None, Some(deadline));
        let cmd_model_doc = strict_json(
            &build_original_at_cut_document(
                &c,
                &cfg_cmd_only,
                1,
                &meta,
                "model",
                "cmd-alpha",
                &perms_cmd,
                &mut b1,
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(
            cmd_model_doc["original"]["model_ref"]["content_hash"],
            model_hash
        );
        assert!(cmd_model_doc["original"]["model_raw_utf8"].is_null());
        assert!(cmd_model_doc["original"]["model_exact_text"].is_null());
        assert!(cmd_model_doc["original"]["source_fact_key"].is_null());
        let mut b2 = ReadBudget::new(None, Some(deadline));
        let err_fk = build_original_at_cut_document(
            &c,
            &cfg_cmd_only,
            1,
            &meta,
            "model",
            &fk,
            &perms_cmd,
            &mut b2,
        )
        .unwrap_err();
        assert!(err_fk.contains("QueryFact"), "unexpected: {err_fk}");

        // 2. QueryFact-only: querying model by fact_key returns model_raw_utf8;
        //    querying model by command_id is REJECTED (cannot traverse finance.commands without QueryCommand).
        let cfg_fact_only = fin6_config("E", &["ReadView", "QueryFact"]);
        let perms_fact = check_authorization(
            &cfg_fact_only,
            &env,
            &json!({"op": OP_READ_ORIGINAL_AT_CUT, "kind": "model", "object_id": fk}),
        )
        .unwrap();
        assert!(perms_fact.query_fact && !perms_fact.query_command);
        let mut b3 = ReadBudget::new(None, Some(deadline));
        let fact_model_doc = strict_json(
            &build_original_at_cut_document(
                &c,
                &cfg_fact_only,
                1,
                &meta,
                "model",
                &fk,
                &perms_fact,
                &mut b3,
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(fact_model_doc["original"]["model_raw_utf8"], model_raw);
        let mut b4 = ReadBudget::new(None, Some(deadline));
        let err_cmd = build_original_at_cut_document(
            &c,
            &cfg_fact_only,
            1,
            &meta,
            "model",
            "cmd-alpha",
            &perms_fact,
            &mut b4,
        )
        .unwrap_err();
        assert!(err_cmd.contains("QueryCommand"), "unexpected: {err_cmd}");

        // 3. QueryAllocation-only: returns allocation + resolve_receipt + named fact_ref ONLY (fact is null, NO raw_utf8!).
        let cfg_alloc_only = fin6_config("E", &["ReadView", "QueryAllocation"]);
        let perms_alloc = check_authorization(
            &cfg_alloc_only,
            &env,
            &json!({"op": OP_READ_ORIGINAL_AT_CUT, "kind": "allocation", "object_id": aid}),
        )
        .unwrap();
        assert!(perms_alloc.query_allocation && !perms_alloc.query_fact);
        let mut b5 = ReadBudget::new(None, Some(deadline));
        let alloc_doc = strict_json(
            &build_original_at_cut_document(
                &c,
                &cfg_alloc_only,
                1,
                &meta,
                "allocation",
                aid,
                &perms_alloc,
                &mut b5,
            )
            .unwrap(),
        )
        .unwrap();
        assert!(alloc_doc["original"]["fact"].is_null());
        assert_eq!(alloc_doc["original"]["fact_ref"]["fact_key"], fk);
        assert!(!canonical_json(&alloc_doc).contains("raw_utf8"));

        // 4. Full permissions (QueryAllocation + QueryFact): embeds full fact detail as before.
        let perms_all = check_authorization(
            &cfg_all,
            &env,
            &json!({"op": OP_READ_ORIGINAL_AT_CUT, "kind": "allocation", "object_id": aid}),
        )
        .unwrap();
        let mut b6 = ReadBudget::new(None, Some(deadline));
        let full_alloc = strict_json(
            &build_original_at_cut_document(
                &c,
                &cfg_all,
                1,
                &meta,
                "allocation",
                aid,
                &perms_all,
                &mut b6,
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(full_alloc["original"]["fact"]["raw_utf8"], raw_orig);
    }

    #[test]
    fn contract_gate_rejects_non_fin6_non_tb03c_and_v2() {
        for mut cfg in [
            fin6_config("E", &["ReadView"]),
            fin6_config("E", &["ReadView"]),
            fin6_config("E", &["ReadView"]),
        ]
        .into_iter()
        .enumerate()
        .map(|(i, mut c)| {
            match i {
                0 => c.manifest["finance"]["schema_revision"] = json!("tb03b-finance/5"),
                1 => c.manifest["book_revision"] = Value::Null,
                _ => c.manifest["protocol_revision"] = json!("economic-session/2"),
            }
            c
        }) {
            let err = check_projection_contract(&cfg).unwrap_err();
            assert!(err.starts_with("SchemaUnsupported"), "unexpected: {err}");
            let _ = &mut cfg;
        }
    }
}
