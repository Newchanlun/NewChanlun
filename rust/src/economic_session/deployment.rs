//! #2127：部署映射独立于业务清单和提交图像。同一事务登记，绝不参与业务摘要。
use super::voice::{digest, exact};
use crate::session_protocol::{nonnegative, required, sha256_hex};
use serde_json::Value;
use std::collections::BTreeSet;
use std::io::Read;
use std::path::Path;

pub(super) const BUSINESS: &str = "economic-manifest/2";
pub(super) const PACKAGE: &str = "economic-session-config/2";
pub(super) const DEPLOYMENT: &str = "economic-deployment/1";
pub(super) const SQL: &str = "CREATE TABLE deployment(singleton INTEGER PRIMARY KEY CHECK(singleton=1), mapping TEXT NOT NULL, fingerprint TEXT NOT NULL) STRICT;";

pub(super) fn is_business(m: &Value) -> bool {
    m["schema_revision"] == BUSINESS
}

pub(super) fn closed(v: &Value, required_keys: &[&str], optional: &[&str]) -> Result<(), String> {
    let fields = v.as_object().ok_or("SchemaUnsupported：配置须为对象")?;
    if required_keys.iter().any(|key| !fields.contains_key(*key))
        || fields
            .keys()
            .any(|key| !required_keys.contains(&key.as_str()) && !optional.contains(&key.as_str()))
    {
        return Err("SchemaUnsupported：配置缺项或包含未知字段".into());
    }
    Ok(())
}

pub(super) fn path(v: &Value, key: &str) -> Result<(), String> {
    let s = required(v, key)?;
    if !Path::new(s).is_absolute() || s.contains('\0') {
        return Err("InvalidDomain：部署位置须为绝对路径".into());
    }
    Ok(())
}

fn validate_clock(m: &Value) -> Result<(), String> {
    let c = &m["clock"];
    match required(c, "kind")? {
        "System" => exact(c, &["kind"]),
        "TestOnly" => {
            exact(c, &["kind", "plan"])?;
            let plan = &c["plan"];
            exact(plan, &["init_ns", "recover_ns", "messages"])?;
            let time = |value: &Value| {
                nonnegative(
                    value.as_str().ok_or("InvalidDomain：时钟值须文本")?,
                    "clock tick",
                )
                .map(|_| ())
            };
            time(&plan["init_ns"])?;
            for tick in plan["recover_ns"]
                .as_array()
                .ok_or("InvalidDomain：恢复时钟须数组")?
            {
                time(tick)?;
            }
            for phase in plan["messages"]
                .as_object()
                .ok_or("InvalidDomain：消息时钟须对象")?
                .values()
            {
                closed(phase, &[], &["received_ns", "first_known_ns", "commit_ns"])?;
                for tick in phase.as_object().unwrap().values() {
                    match tick {
                        Value::Array(ticks) if !ticks.is_empty() => {
                            for tick in ticks {
                                time(tick)?;
                            }
                        }
                        _ => time(tick)?,
                    }
                }
            }
            Ok(())
        }
        _ => Err("InvalidDomain：必须显式指定时钟 adapter".into()),
    }
}

pub(super) const RESOURCES: &[&str] = &[
    "max_frame_bytes",
    "read_timeout_ms",
    "write_timeout_ms",
    "response_timeout_ms",
    "queue_capacity",
    "max_connections",
];

pub(super) fn validate_business(m: &Value) -> Result<(), String> {
    if !is_business(m) {
        return Err("SchemaUnsupported：缺经济业务清单版本".into());
    }
    closed(
        m,
        &[
            "schema_revision",
            "protocol_revision",
            "session_id",
            "session_generation",
            "chongs",
            "authorized_sources",
            "resources",
            "clock",
        ],
        &[
            "book_revision",
            "voice_binding",
            "finance",
            "test_only_fault",
            "sr_expansion",
            "domain_event_withdrawal",
            "fill_allocation_policy",
            "fill_manifests",
            "funding",
            "history_simulation_source",
        ],
    )?;
    required(m, "protocol_revision")?;
    exact(&m["resources"], RESOURCES)?;
    let book = super::book::rules(m)?;
    let route_fields: &[&str] = match book {
        super::book::Rules::Tb03cV2 | super::book::Rules::Tb03cV3 => &[
            "chong_id",
            "symbol",
            "operation_level",
            "fixed_q",
            "funding",
        ],
        _ => &["chong_id", "symbol", "operation_level", "fixed_q"],
    };
    // 重资金的内部形状与政策交叉约束由 tb03c_funding 按同一书账版本验证。
    for c in m["chongs"].as_array().ok_or("InvalidDomain：重须数组")? {
        exact(c, route_fields)?;
    }
    for a in m["authorized_sources"]
        .as_array()
        .ok_or("InvalidDomain：获准来源须数组")?
    {
        exact(
            a,
            &[
                "source_namespace",
                "source_epoch",
                "producer_id",
                "producer_epoch",
                "operations",
            ],
        )?;
    }
    for f in super::store::fault_plans(&m["test_only_fault"]) {
        exact(f, &["message_id", "phase"])?;
    }
    if let Some(x) = m.get("history_simulation_source") {
        exact(
            x,
            &[
                "source_namespace",
                "source_epoch",
                "producer_id",
                "producer_epoch",
                "model_content_hash",
            ],
        )?;
        for field in ["source_namespace", "source_epoch", "producer_id"] {
            required(x, field)?;
        }
        crate::session_protocol::positive(required(x, "producer_epoch")?, "X producer epoch")?;
        digest(required(x, "model_content_hash")?)?;
        if !m["authorized_sources"].as_array().unwrap().iter().any(|a| {
            [
                "source_namespace",
                "source_epoch",
                "producer_id",
                "producer_epoch",
            ]
            .iter()
            .all(|k| a[k] == x[k])
                && a["operations"]
                    .as_array()
                    .is_some_and(|ops| ops.iter().any(|op| op == "CaptureExternal"))
        }) {
            return Err("IdentityConflict：X 事实来源未获正式 CaptureExternal 权限".into());
        }
        if !book.is_tb03c() {
            return Err("SchemaUnsupported：模拟事实来源须选择 TB03C 书账合同".into());
        }
    }
    validate_clock(m)
}

pub(super) fn validate_mapping(m: &Value, d: &Value) -> Result<(), String> {
    exact(
        d,
        &[
            "schema_revision",
            "domains",
            "voice",
            "finance",
            "fault_markers",
            "x_db",
        ],
    )?;
    if d["schema_revision"] != DEPLOYMENT {
        return Err("SchemaUnsupported：未知经济部署清单版本".into());
    }
    let mut domains = BTreeSet::from(["E".to_owned()]);
    for route in m["chongs"].as_array().unwrap() {
        if !domains.insert(format!("B:{}", required(route, "chong_id")?)) {
            return Err("IdentityConflict：重复经济域".into());
        }
    }
    let layouts = d["domains"]
        .as_object()
        .ok_or("InvalidDomain：域布局须对象")?;
    if !layouts.keys().eq(domains.iter()) {
        return Err("IdentityConflict：部署与业务域划分不符".into());
    }
    for r in layouts.values() {
        exact(r, &["db", "socket"])?;
        path(r, "db")?;
        path(r, "socket")?;
    }
    let mut voice_ids = BTreeSet::new();
    if let Some(authorities) = m["voice_binding"]["authorities"].as_array() {
        for a in authorities {
            voice_ids.insert(required(a, "authority_id")?);
        }
    }
    let voice = d["voice"]
        .as_object()
        .ok_or("InvalidDomain：Voice 映射须对象")?;
    if !voice.keys().map(String::as_str).eq(voice_ids.into_iter()) {
        return Err("IdentityConflict：Voice 业务权威与部署不符".into());
    }
    for a in voice.values() {
        exact(a, &["bundle", "verification", "artifacts"])?;
        path(a, "bundle")?;
        path(a, "verification")?;
        let mut roles = BTreeSet::new();
        for item in a["artifacts"]
            .as_array()
            .ok_or("InvalidDomain：原件映射须数组")?
        {
            exact(item, &["name", "sha256", "path"])?;
            let role = required(item, "name")?;
            logical_name(role)?;
            if !roles.insert(role) {
                return Err("IdentityConflict：原件角色定位不唯一".into());
            }
            digest(required(item, "sha256")?)?;
            path(item, "path")?;
        }
        if !super::evidence::REQUIRED_ROLES
            .iter()
            .all(|role| roles.contains(role))
        {
            return Err("MissingDependency：Voice 部署未覆盖必备原件角色".into());
        }
    }
    let f = &d["finance"];
    if m["finance"].is_null() {
        if !f.is_null() {
            return Err("IdentityConflict：未选择 FIN 业务合同".into());
        }
    } else {
        exact(f, &["input", "s", "cap_records"])?;
        path(f, "input")?;
        let s = &f["s"];
        if super::store::domain_revision(m)? == super::store::SCHEMA_V2 {
            exact(s, &["binary", "db", "reader_socket"])?;
            if m["finance"]["structure"]["reading"] == "SessionClosure" {
                super::financial_content::Reading::from_json(&s["reader_socket"])?;
                path(s, "reader_socket")?;
            } else if !s["reader_socket"].is_null() {
                return Err("IdentityConflict：冷读法不得配置 reader socket".into());
            }
        } else {
            exact(s, &["binary", "db"])?;
        }
        path(s, "binary")?;
        path(s, "db")?;
        for (sha, v) in f["cap_records"]
            .as_object()
            .ok_or("InvalidDomain：cap 原件须按摘要定位")?
        {
            digest(sha)?;
            let s = v.as_str().ok_or("InvalidDomain：cap 部署位置须文本")?;
            if !Path::new(s).is_absolute() || s.contains('\0') {
                return Err("InvalidDomain：cap 部署位置须为绝对路径".into());
            }
        }
    }
    if m.get("history_simulation_source").is_some() {
        path(d, "x_db")?;
    } else if !d["x_db"].is_null() {
        return Err("IdentityConflict：未选择 X 事实来源".into());
    }
    let markers = d["fault_markers"]
        .as_array()
        .ok_or("InvalidDomain：故障标记须数组")?;
    let faults = super::store::fault_plans(&m["test_only_fault"]);
    if faults.len() != markers.len() {
        return Err("IdentityConflict：业务故障计划和部署标记不符".into());
    }
    let mut marker_paths = BTreeSet::new();
    for (f, marker) in faults.into_iter().zip(markers) {
        exact(marker, &["message_id", "phase", "marker_path"])?;
        if marker["message_id"] != f["message_id"] || marker["phase"] != f["phase"] {
            return Err("IdentityConflict：业务故障顺序和部署标记不符".into());
        }
        path(marker, "marker_path")?;
        if !marker_paths.insert(required(marker, "marker_path")?) {
            return Err("IdentityConflict：故障标记路径重复".into());
        }
    }
    Ok(())
}

pub(super) fn logical_name(name: &str) -> Result<(), String> {
    if name.is_empty()
        || name == "."
        || name == ".."
        || !name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-' | b'.'))
    {
        return Err("InvalidDomain：原件名须为逻辑角色而非路径".into());
    }
    Ok(())
}

/// 原件可能是二进制。先读到上界，再用独立受信摘要比较；非普通文件不阻塞写者。
pub(super) fn read_pinned(path: &str, sha: &str, max: u64) -> Result<Vec<u8>, String> {
    if !Path::new(path).is_absolute() {
        return Err("InvalidDomain：原件须为绝对路径".into());
    }
    let mut opts = std::fs::OpenOptions::new();
    opts.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        opts.custom_flags(libc::O_NONBLOCK);
    }
    let file = opts
        .open(path)
        .map_err(|e| format!("MissingDependency：原件不可读：{e}"))?;
    if !file.metadata().map_err(super::store::err)?.is_file() {
        return Err("InvalidDomain：原件须普通文件".into());
    }
    let mut raw = Vec::new();
    file.take(max + 1)
        .read_to_end(&mut raw)
        .map_err(super::store::err)?;
    verify_bytes(&raw, sha, max)?;
    Ok(raw)
}

pub(super) fn verify_bytes(raw: &[u8], sha: &str, max: u64) -> Result<(), String> {
    if raw.len() as u64 > max {
        return Err("InvalidDomain：原件超限".into());
    }
    if sha256_hex(raw) != sha {
        return Err("IdentityConflict：原件摘要不符".into());
    }
    Ok(())
}
