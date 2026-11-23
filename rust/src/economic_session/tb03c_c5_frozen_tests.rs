//! #1406 C5：独立冻结原件经真实 service::handle；不注入模型 source_observation。
//! 期望来自独立手算。这里只投影字段，不重算金额/资格；完整 G 仍不在本片。
use super::tb03c_book_tests::Space;
use super::{book, service, store};
use crate::session_protocol::{canonical_json, sha256_hex};
use serde_json::{json, Value};

const HAND: &str = include_str!("../../../s_session/tests/fixtures/tb03c_c5/HAND-ORACLE.json");
const PLAN: &str = include_str!("../../../s_session/tests/fixtures/tb03c_c5/RUN-PLAN.json");
const MANIFEST: &str = include_str!("../../../s_session/tests/fixtures/tb03c_c5/MANIFEST.json");
const CARRY: &str =
    include_str!("../../../s_session/tests/fixtures/tb03c_c5/CARRYING-COST-CASE.json");
const RAW: [(&str, &str); 5] = [
    (
        "chong-G1",
        include_str!("../../../s_session/tests/fixtures/tb03c_c5/raw/chong-G1.json"),
    ),
    (
        "chong-G2",
        include_str!("../../../s_session/tests/fixtures/tb03c_c5/raw/chong-G2.json"),
    ),
    (
        "chong-G3",
        include_str!("../../../s_session/tests/fixtures/tb03c_c5/raw/chong-G3.json"),
    ),
    (
        "chong-W1",
        include_str!("../../../s_session/tests/fixtures/tb03c_c5/raw/chong-W1.json"),
    ),
    (
        "latch-counterexample",
        include_str!("../../../s_session/tests/fixtures/tb03c_c5/raw/latch-counterexample.json"),
    ),
];
fn raw(name: &str) -> &'static str {
    RAW.iter().find(|(n, _)| *n == name).unwrap().1
}
struct ParsedRaw {
    doc: Value,
    sha256: String,
}
fn parsed_raw(name: &str) -> &'static ParsedRaw {
    parsed_raw_map().get(name).unwrap()
}
fn session(tag: &str, clock_len: usize) -> FrozenSession {
    FrozenSession::with_routes(
        tag,
        "testonly-tb1406-c5",
        "fixture-epoch-1",
        &[
            ("chong-G1", "TEST-G", "1", "10"),
            ("chong-G2", "TEST-G", "2", "5"),
            ("chong-G3", "TEST-G", "3", "3"),
        ],
        clock_len,
    )
}
fn number(value: &Value) -> Value {
    value
        .as_str()
        .map_or(Value::Null, |s| json!(s.parse::<i64>().unwrap()))
}
fn phase_event(image: &Value, event: &Value) -> String {
    let record = image["recorded"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["fact_key"] == event["fact_key"])
        .unwrap();
    let id = record["event"]["source"]["external_fact_id"]
        .as_str()
        .unwrap();
    let kind = event["kind"].as_str().unwrap();
    if event.get("from").is_some() {
        format!(
            "{id}:{kind}:{}->{}",
            event["from"].as_str().unwrap(),
            event["to"].as_str().unwrap()
        )
    } else {
        format!("{id}:{kind}")
    }
}
/// 仅字段重命名、整数文本转换与事件身份展示；不以生产结果生成期望。
fn project(image: &Value) -> Value {
    let b = &image["book"];
    let phase = &b["phase"];
    let mut unit = json!({"K":number(&b["unit_cost"]["K"]),"q":number(&b["unit_cost"]["q"])});
    if b["unit_cost"]["status"] != "Known" {
        unit["status"] = b["unit_cost"]["status"].clone();
        unit["reason"] = b["unit_cost"]["reason"].clone();
    }
    let mut enabled = json!({"kind":phase["growth_enabled"]["status"]});
    if let Some(slot) = phase["growth_enabled"].get("slot") {
        enabled["slot"] = slot.clone();
    }
    let history: Vec<_> = phase["events"]
        .as_array()
        .unwrap()
        .iter()
        .map(|e| phase_event(image, e))
        .collect();
    let gates: Vec<_> = phase["gate"]
        .as_object()
        .into_iter()
        .map(|_| phase_event(image, &phase["gate"]))
        .collect();
    json!({"q":number(&b["actual_quantity"]),"fixed_q":number(&b["fixed_q"]),
        "K":number(&b["cost_basis"]["K"]),"P":number(&b["principal"]["P"]),
        "P_recovered":number(&b["principal"]["P_recovered"]),
        "Pi":number(&b["income_book"]["Pi"]),"A":number(&b["income_book"]["A"]),
        "W":number(&b["income_book"]["W"]),"R":number(&b["income_book"]["R"]),
        "principal_batch_count":b["principal"]["batches"].as_array().unwrap().len(),
        "growth_eligible":phase["growth_eligible"]["status"],"phase_latch":phase["latch"],
        "growth_enabled":enabled,"unit_cost":unit,"phase_history":history,"gate_events":gates})
}
fn assert_snapshot(image: &Value, expected: &Value, label: &str) {
    let got = project(image);
    for (field, value) in got.as_object().unwrap() {
        assert_eq!(value, &expected[field], "{label}: {field}");
    }
    // available_growth_lots 是独立模型的来源批消费账，不冒充本片已有完整 G 投影。
    // 正式路径的同批超额消费拒绝另由 c5_transfer_claim_conflict... 锁验证。
}
fn captured_parsed(
    s: &mut FrozenSession,
    original: &str,
    doc: &Value,
    expected_sha: &str,
    index: usize,
) -> Value {
    let receipt = s.capture_raw_parsed(original, doc, index);
    assert_eq!(receipt["kind"], "Recorded", "{receipt}");
    let image = s.image(0);
    let stored = image["recorded"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["fact_key"] == receipt["fact_key"])
        .unwrap();
    assert_eq!(stored["raw_utf8"], original);
    assert_eq!(stored["raw_sha256"], expected_sha);
    receipt
}
fn captured_named(s: &mut FrozenSession, name: &str, index: usize) -> Value {
    let original = raw(name);
    let parsed = parsed_raw(name);
    captured_parsed(s, original, &parsed.doc, &parsed.sha256, index)
}
fn apply_step_parsed(
    s: &mut FrozenSession,
    owner: usize,
    original: &str,
    doc: &Value,
    expected_sha: &str,
    index: usize,
) -> Value {
    let receipt = captured_parsed(s, original, doc, expected_sha, index);
    let applied = s.apply(owner, &receipt);
    assert_eq!(applied["kind"], "Applied", "{applied}");
    assert_eq!(s.apply(owner, &receipt), applied, "原 allocation 必须幂等");
    receipt
}
fn apply_step_named(s: &mut FrozenSession, owner: usize, name: &str, index: usize) -> Value {
    let original = raw(name);
    let parsed = parsed_raw(name);
    apply_step_parsed(s, owner, original, &parsed.doc, &parsed.sha256, index)
}
fn capacity_wait_named(s: &mut FrozenSession, name: &str, index: usize) {
    let before = s.image(1);
    let receipt = captured_named(s, name, index);
    let waiting = s.apply(1, &receipt);
    assert!(
        waiting["error"]
            .as_str()
            .unwrap()
            .starts_with("AwaitingPolicy：capacity"),
        "{waiting}"
    );
    let resolved = s.send(0, json!({"op":"ResolveEvidence","evidence_id":"frozen-capacity-wait",
        "covered":[{"fact_key":receipt["fact_key"],"fact_hash":receipt["fact_hash"],"token":receipt["token"]}],
        "frontier":{"source_namespace":"testonly-tb1406-c5","source_epoch":"fixture-epoch-1","cursor":"10"},"dependency_version":"testonly/1"}));
    assert!(
        resolved["error"]
            .as_str()
            .unwrap()
            .starts_with("AwaitingPolicy：capacity"),
        "{resolved}"
    );
    assert_eq!(s.image(1), before);
    assert!(!s.has_receipt(1, receipt["allocation_id"].as_str().unwrap()));
    let e = s.image(0);
    let pending = e["pending"]
        .as_array()
        .unwrap()
        .iter()
        .find(|p| p["fact_key"] == receipt["fact_key"])
        .unwrap();
    assert_eq!(
        pending["reason"],
        json!({"kind":"AwaitingPolicy","slot":"capacity"})
    );
}

#[test]
fn c5_frozen_originals_and_hand_expectations_keep_independent_hashes() {
    let manifest: Value = serde_json::from_str(MANIFEST).unwrap();
    for (name, original) in RAW {
        assert_eq!(
            sha256_hex(original.as_bytes()),
            manifest["files"][format!("raw/{name}.json")]
        );
    }
    for (name, original) in [
        ("HAND-ORACLE.json", HAND),
        ("RUN-PLAN.json", PLAN),
        ("CARRYING-COST-CASE.json", CARRY),
    ] {
        assert_eq!(sha256_hex(original.as_bytes()), manifest["files"][name]);
    }
}

#[test]
fn c5_frozen_we3_we6_fifteen_checkpoints_use_real_owner_handle() {
    run_we3_we6_fifteen_checkpoints();
}

#[test]
fn c5_frozen_nonzero_cost_is_not_zero_cost_principal_or_realized_profit() {
    let case: Value = serde_json::from_str(CARRY).unwrap();
    let mut s = session("c5-frozen-carry", 32);
    for i in 0..5 {
        apply_step_named(&mut s, 1, "chong-G1", i);
    }
    for (name, owner) in [("completed", 1), ("out", 1), ("in", 2)] {
        // 子文档已由独立作者冻结在 JSON 内；canonical_json 只编码原字段，不改值或造 proof。
        let doc = &case["documents"][name];
        let original = canonical_json(doc);
        let sha = sha256_hex(original.as_bytes());
        apply_step_parsed(&mut s, owner, &original, doc, &sha, 0);
        assert_snapshot(&s.image(owner), &case["hand_expected"][name], name);
    }
    s.recover_all();
    assert_snapshot(&s.image(2), &case["hand_expected"]["in"], "carry recovered");
}

#[test]
fn c5_frozen_capture_rejects_missing_sources_and_invalid_opening_metadata() {
    let mut s = session("c5-frozen-negative", 16);
    let mut opening = parsed_raw("chong-G1").doc.clone();
    opening["events"][0]["known_cost_components"][0]
        .as_object_mut()
        .unwrap()
        .remove("source_ref");
    let before = s.image(0);
    let rejected = s.capture_raw(&canonical_json(&opening), 0);
    assert!(rejected["error"].is_string(), "{rejected}");
    assert_eq!(s.image(0), before);
    assert!(!s.has_receipt(1, "alloc-G1"));
    for pointer in [
        "/events/0/transfer/source_ref",
        "/events/0/transfer_opening/source_ref",
    ] {
        let mut doc = parsed_raw("chong-G2").doc.clone();
        *doc.pointer_mut(pointer).unwrap() = Value::Null;
        let before = s.image(0);
        let rejected = s.capture_raw(&canonical_json(&doc), 0);
        assert!(rejected["error"].is_string(), "{pointer}: {rejected}");
        assert_eq!(s.image(0), before);
    }
    for (field, value) in [("op_level", "-1"), ("op_level", "invalid"), ("symbol", "")] {
        let mut doc = parsed_raw("chong-G2").doc.clone();
        doc["events"][0]["transfer_opening"][field] = json!(value);
        let before = s.image(0);
        let rejected = s.capture_raw(&canonical_json(&doc), 0);
        assert!(rejected["error"].is_string(), "{field}: {rejected}");
        assert_eq!(s.image(0), before);
        assert!(!s.has_receipt(2, "alloc-T1-in"));
    }
    s.audit();
}

const H1_RAW: &str =
    include_str!("../../../s_session/tests/fixtures/tb03c_c5_depth/H1-source-depth-original.json");
fn container_depth(v: &Value) -> usize {
    match v {
        Value::Object(m) => 1 + m.values().map(container_depth).max().unwrap_or(0),
        Value::Array(a) => 1 + a.iter().map(container_depth).max().unwrap_or(0),
        _ => 0,
    }
}
#[test]
fn c5_h1_real_handle_depth_inside_boundary_and_overflow_are_recoverable() {
    let h1_sha = sha256_hex(H1_RAW.as_bytes());
    assert_eq!(
        h1_sha,
        "38d4e9756b09cec00d104c6d4658c9a013df2d46c41fa34af639840a9ab46027"
    );
    let h1_doc: Value = serde_json::from_str(H1_RAW).unwrap();
    std::thread::scope(|sc| {
        let handles: Vec<_> = [114usize, 115, 116]
            .into_iter()
            .map(|note_depth| {
                let h1_doc = &h1_doc;
                let h1_sha = &h1_sha;
                sc.spawn(move || {
                    let (original, encoded, encoded_sha) = if note_depth == 116 {
                        (h1_doc.clone(), H1_RAW.to_owned(), h1_sha.clone())
                    } else {
                        let mut original = h1_doc.clone();
                        let mut note = original["events"][7]["source_note"].clone();
                        for _ in note_depth..116 {
                            note = note.as_object().unwrap().values().next().unwrap().clone();
                        }
                        original["events"][7]["source_note"] = note;
                        // 越界例保留独审原字节；界内两例只剥 note 包装，不改经济字段。
                        let encoded = canonical_json(&original);
                        let sha = sha256_hex(encoded.as_bytes());
                        (original, encoded, sha)
                    };
                    let mut s = session(&format!("c5-h1-depth-{note_depth}"), 40);
                    for i in 0..8 {
                        apply_step_parsed(&mut s, 1, &encoded, &original, &encoded_sha, i);
                    }
                    let incoming = captured_named(&mut s, "chong-G2", 0);
                    let before = s.image(2);
                    let rows = s.row_counts(2);
                    let result = s.apply(2, &incoming);
                    if note_depth < 116 {
                        assert_eq!(result["kind"], "Applied", "depth {note_depth}: {result}");
                        assert_eq!(container_depth(&s.image(2)), note_depth + 12);
                        assert_eq!(s.apply(2, &incoming), result);
                    } else {
                        assert!(
                            result["error"]
                                .as_str()
                                .unwrap()
                                .starts_with("SchemaUnsupported：完整持久图像超出统一可读安全域"),
                            "{result}"
                        );
                        assert_eq!(s.image(2), before);
                        assert_eq!(s.row_counts(2), rows);
                        // 同一健康目标仍能接后续合法已发生开局；失败源扣账不撤销、不退款。
                        let mut healthy = parsed_raw("chong-G1").doc.clone();
                        let event = &mut healthy["events"][0];
                        event["source"]["external_fact_id"] =
                            json!("healthy-after-depth-rejection");
                        event["allocation_id"] = json!("alloc-healthy-after-depth-rejection");
                        event["book_identity"]["chong_id"] = json!("chong-G2");
                        event["book_identity"]["op_level"] = json!("2");
                        event["book_identity"]["fixed_q"] = json!("5");
                        event["observed_existing_book"]["units"] = json!("5");
                        let healthy_raw = canonical_json(&healthy);
                        let healthy_sha = sha256_hex(healthy_raw.as_bytes());
                        apply_step_parsed(&mut s, 2, &healthy_raw, &healthy, &healthy_sha, 0);
                    }
                    let target = s.image(2);
                    s.recover_all();
                    assert_eq!(s.image(2), target);
                })
            })
            .collect();
        for h in handles {
            h.join().unwrap();
        }
    });
}

fn run_we3_we6_fifteen_checkpoints() {
    let hand: Value = serde_json::from_str(HAND).unwrap();
    let plan: Value = serde_json::from_str(PLAN).unwrap();
    let steps = plan["steps"].as_array().unwrap();
    let (w_steps, s_steps): (Vec<_>, Vec<_>) = steps
        .iter()
        .partition(|st| st["document"].as_str().unwrap() == "chong-W1");
    let count = std::thread::scope(|sc| {
        let w_handle = sc.spawn(|| {
            let mut w = FrozenSession::with_routes(
                "c5-frozen-w1",
                "testonly-tb1406-c5",
                "fixture-epoch-1",
                &[("chong-W1", "TEST-G", "1", "3")],
                8,
            );
            let mut w_count = 0;
            for step in &w_steps {
                let name = step["document"].as_str().unwrap();
                let label = step["id"].as_str().unwrap();
                let index = usize::try_from(step["index"].as_u64().unwrap()).unwrap();
                apply_step_named(&mut w, 1, name, index);
                assert_snapshot(&w.image(1), &hand["snapshots"][label], label);
                w_count += 1;
            }
            w.recover_all();
            assert_snapshot(&w.image(1), &hand["snapshots"]["W1"], "W1 recovered");
            w_count
        });

        let mut s = session("c5-frozen-main", 48);
        let mut s_count = 0;
        let mut idx = 0;
        while idx < s_steps.len() {
            let step = s_steps[idx];
            let name = step["document"].as_str().unwrap();
            let label = step["id"].as_str().unwrap();
            let index = usize::try_from(step["index"].as_u64().unwrap()).unwrap();
            if label == "T1-in"
                && idx + 1 < s_steps.len()
                && s_steps[idx + 1]["id"].as_str().unwrap() == "T2-in"
            {
                let step2 = s_steps[idx + 1];
                let name2 = step2["document"].as_str().unwrap();
                let label2 = step2["id"].as_str().unwrap();
                let index2 = usize::try_from(step2["index"].as_u64().unwrap()).unwrap();

                let r1 = captured_named(&mut s, name, index);
                let m1_a = s.alloc_msg_id();
                let m1_b = s.alloc_msg_id();
                let r2 = captured_named(&mut s, name2, index2);
                let m2_a = s.alloc_msg_id();
                let m2_b = s.alloc_msg_id();

                let ns = s.source_namespace.as_str();
                let ep = s.source_epoch.as_str();
                let cfg2 = &s.configs[2];
                let cfg3 = &s.configs[3];
                let (_, rest) = s.connections.split_at_mut(2);
                let (c2_slice, c3_slice) = rest.split_at_mut(1);
                let c2 = &mut c2_slice[0];
                let c3 = &mut c3_slice[0];
                std::thread::scope(|apply_sc| {
                    let h1 = apply_sc.spawn(|| {
                        let p = FrozenSession::apply_payload(&r1);
                        let applied =
                            FrozenSession::send_with_conn(c2, cfg2, ns, ep, m1_a, p.clone());
                        assert_eq!(applied["kind"], "Applied", "{applied}");
                        assert_eq!(
                            FrozenSession::send_with_conn(c2, cfg2, ns, ep, m1_b, p),
                            applied,
                            "原 allocation 必须幂等"
                        );
                        let img = store::latest(c2).unwrap().3;
                        assert_snapshot(&img, &hand["snapshots"][label], label);
                    });
                    let h2 = apply_sc.spawn(|| {
                        let p = FrozenSession::apply_payload(&r2);
                        let applied =
                            FrozenSession::send_with_conn(c3, cfg3, ns, ep, m2_a, p.clone());
                        assert_eq!(applied["kind"], "Applied", "{applied}");
                        assert_eq!(
                            FrozenSession::send_with_conn(c3, cfg3, ns, ep, m2_b, p),
                            applied,
                            "原 allocation 必须幂等"
                        );
                        let img = store::latest(c3).unwrap().3;
                        assert_snapshot(&img, &hand["snapshots"][label2], label2);
                    });
                    h1.join().unwrap();
                    h2.join().unwrap();
                });
                s_count += 2;
                idx += 2;
                continue;
            }
            let owner = match name {
                "chong-G2" => 2,
                "chong-G3" => 3,
                _ => 1,
            };
            if label == "Q12" {
                capacity_wait_named(&mut s, name, index);
            } else {
                apply_step_named(&mut s, owner, name, index);
            }
            assert_snapshot(&s.image(owner), &hand["snapshots"][label], label);
            s_count += 1;
            idx += 1;
        }
        let before: Vec<_> = (0..4).map(|i| s.image(i)).collect();
        s.recover_all();
        for (i, image) in before.iter().enumerate() {
            assert_eq!(&s.image(i), image);
        }
        s_count + w_handle.join().unwrap()
    });
    assert_eq!(count, 15);
}

fn parsed_raw_map() -> &'static std::collections::HashMap<&'static str, ParsedRaw> {
    static CACHE: std::sync::OnceLock<std::collections::HashMap<&'static str, ParsedRaw>> =
        std::sync::OnceLock::new();
    CACHE.get_or_init(|| {
        RAW.iter()
            .map(|(name, text)| {
                (
                    *name,
                    ParsedRaw {
                        doc: serde_json::from_str(text).unwrap(),
                        sha256: sha256_hex(text.as_bytes()),
                    },
                )
            })
            .collect()
    })
}

struct FrozenSession {
    _space: Space,
    configs: Vec<store::Config>,
    connections: Vec<rusqlite::Connection>,
    next: usize,
    source_namespace: String,
    source_epoch: String,
}

impl FrozenSession {
    fn with_routes(
        tag: &str,
        source_namespace: &str,
        source_epoch: &str,
        routes: &[(&str, &str, &str, &str)],
        clock_len: usize,
    ) -> Self {
        let space = Space::new(tag);
        let mut clocks = serde_json::Map::with_capacity(clock_len);
        for i in 0..clock_len {
            let t = 1000 + 10 * i;
            clocks.insert(
                format!("m-{i}"),
                json!({
                    "received_ns": t.to_string(),
                    "first_known_ns": (t + 1).to_string(),
                    "commit_ns": (t + 2).to_string()
                }),
            );
        }
        let chongs: Vec<Value> = routes
            .iter()
            .map(|(id, symbol, level, q)| {
                json!({
                    "chong_id": id,
                    "symbol": symbol,
                    "operation_level": level,
                    "fixed_q": q,
                    "db": space.0.join(format!("{id}.db")),
                    "socket": space.0.join(format!("{id}.sock"))
                })
            })
            .collect();
        let manifest = json!({
            "schema_revision": "economic-manifest/1",
            "session_id": "c5",
            "session_generation": "1",
            "book_revision": "tb03c-book/1",
            "e": {"db": space.0.join("e.db"), "socket": space.0.join("e.sock")},
            "chongs": chongs,
            "authorized_sources": [{
                "source_namespace": source_namespace,
                "source_epoch": source_epoch,
                "producer_id": "c5",
                "producer_epoch": "1",
                "operations": ["CaptureExternal", "ResolveEvidence", "ApplyAllocation", "ReadView"]
            }],
            "resources": {
                "max_frame_bytes": "1048576",
                "read_timeout_ms": "1000",
                "write_timeout_ms": "1000",
                "response_timeout_ms": "2000",
                "queue_capacity": "2",
                "max_connections": "2"
            },
            "clock": {"kind": "TestOnly", "plan": {"init_ns": "1", "recover_ns": ["90000"], "messages": clocks}}
        });
        let path = space.0.join("manifest.json");
        std::fs::write(&path, canonical_json(&manifest)).unwrap();
        let owners: Vec<Option<&str>> = std::iter::once(None)
            .chain(routes.iter().map(|(id, _, _, _)| Some(*id)))
            .collect();
        let mut pairs: Vec<(store::Config, rusqlite::Connection)> = std::thread::scope(|sc| {
            let handles: Vec<_> = owners
                .into_iter()
                .map(|id| {
                    let path = &path;
                    let root = &space.0;
                    sc.spawn(move || {
                        let db = root.join(id.map_or("e.db".to_owned(), |id| format!("{id}.db")));
                        let cfg = store::Config::load(path, &db, id).unwrap();
                        store::init(&cfg).unwrap();
                        let conn = store::open(&cfg.db, false).unwrap().0;
                        (cfg, conn)
                    })
                })
                .collect();
            handles.into_iter().map(|h| h.join().unwrap()).collect()
        });
        let mut configs = Vec::with_capacity(pairs.len());
        let mut connections = Vec::with_capacity(pairs.len());
        for (cfg, conn) in pairs.drain(..) {
            configs.push(cfg);
            connections.push(conn);
        }
        Self {
            _space: space,
            configs,
            connections,
            next: 0,
            source_namespace: source_namespace.to_owned(),
            source_epoch: source_epoch.to_owned(),
        }
    }

    fn alloc_msg_id(&mut self) -> String {
        let id = format!("m-{}", self.next);
        self.next += 1;
        id
    }

    fn send_with_conn(
        conn: &mut rusqlite::Connection,
        config: &store::Config,
        source_namespace: &str,
        source_epoch: &str,
        message_id: String,
        payload: Value,
    ) -> Value {
        let request = json!({
            "schema_revision": "economic-session/1",
            "session_id": "c5",
            "session_generation": "1",
            "message_id": message_id,
            "source_namespace": source_namespace,
            "source_epoch": source_epoch,
            "producer_id": "c5",
            "producer_epoch": "1",
            "payload_hash": book::hash(&payload),
            "payload": payload,
            "causal_refs": []
        });
        service::handle(conn, config, 1, 1, &json!({}), &request)["payload"].clone()
    }

    fn send(&mut self, owner: usize, payload: Value) -> Value {
        let msg_id = self.alloc_msg_id();
        Self::send_with_conn(
            &mut self.connections[owner],
            &self.configs[owner],
            &self.source_namespace,
            &self.source_epoch,
            msg_id,
            payload,
        )
    }

    fn capture_raw_parsed(&mut self, raw: &str, doc: &Value, index: usize) -> Value {
        self.send(
            0,
            json!({
                "op": "CaptureExternal",
                "raw_utf8": raw,
                "json_pointer": format!("/events/{index}"),
                "token": format!("tok-{}", doc["events"][index]["allocation_id"].as_str().unwrap()),
                "source_event_time": doc["events"][index]["source"]["source_event_time"]
            }),
        )
    }

    fn capture_raw(&mut self, raw: &str, index: usize) -> Value {
        let doc: Value = serde_json::from_str(raw).unwrap();
        self.capture_raw_parsed(raw, &doc, index)
    }

    fn apply_payload(receipt: &Value) -> Value {
        json!({
            "op": "ApplyAllocation",
            "fact_key": receipt["fact_key"],
            "allocation_id": receipt["allocation_id"],
            "expected_fact_hash": receipt["fact_hash"]
        })
    }

    fn apply(&mut self, owner: usize, receipt: &Value) -> Value {
        self.send(owner, Self::apply_payload(receipt))
    }

    fn image(&self, owner: usize) -> Value {
        store::latest(&self.connections[owner]).unwrap().3
    }

    fn audit(&mut self) {
        std::thread::scope(|sc| {
            let handles: Vec<_> = self
                .connections
                .iter_mut()
                .zip(&self.configs)
                .map(|(c, config)| sc.spawn(move || store::audit(c, config).unwrap()))
                .collect();
            for h in handles {
                h.join().unwrap();
            }
        });
    }

    fn has_receipt(&self, owner: usize, allocation_id: &str) -> bool {
        store::row(&self.connections[owner], "receipts", allocation_id)
            .unwrap()
            .is_some()
    }

    fn recover_all(&mut self) {
        std::thread::scope(|sc| {
            let handles: Vec<_> = self
                .connections
                .iter_mut()
                .zip(&self.configs)
                .map(|(c, config)| {
                    sc.spawn(move || {
                        store::recover(config).unwrap();
                        store::audit(c, config).unwrap();
                    })
                })
                .collect();
            for h in handles {
                h.join().unwrap();
            }
        });
    }

    fn row_counts(&self, owner: usize) -> Vec<i64> {
        [
            "facts",
            "book",
            "applications",
            "receipts",
            "commits",
            "messages",
        ]
        .into_iter()
        .map(|table| {
            self.connections[owner]
                .query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r.get(0))
                .unwrap()
        })
        .collect()
    }
}
