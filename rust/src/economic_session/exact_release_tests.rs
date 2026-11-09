//! #1407 C1：E 侧精确命令生产者测试锁 L1–L9（`tb03b-finance/5`，TestOnly 已定域 slot）。
//! S/γ 仍是单位信任缝；X 侧 accept 与接纳时钟归 #1942，本文件只锁 E 的生产者与应答者。
//! 本文件只用 main 已有的符号与字符串操作名，故能在不含实现的 main 上编译并跑红。
use super::*;

const EXACT_OPS: [&str; 4] = [
    "MakeDispatchable",
    "ReleaseExact",
    "QueryCommand",
    "QueryReleasedExact",
];
const CONDITIONS: [(&str, &str, &str); 4] = [
    ("released-exact/1", "released-exact/1", "E.ReleaseExact"),
    (
        "execute-committed/1",
        "execute-committed/1",
        "S.RequestConditionalExecution",
    ),
    (
        "simulation-local-transaction/1",
        "simulation-local-transaction/1",
        "X.OwnAttemptAndCall",
    ),
    ("model_coverage", "model-coverage/1", "E.ReleaseExact"),
];
const CONDITION_FIELDS: [&str; 9] = [
    "condition_id",
    "authority_revision",
    "dependency_set",
    "invalidation_sources",
    "required_check_stages",
    "evidence_refs",
    "coverage_proof",
    "validator_capability",
    "failure_result",
];

/// 冻结原件 `/5` 增量：唯一目标 X、获准条件清单（含 ADR 0052 的 `model_coverage`）与模型覆盖域。
/// alpha 的并发形态在域内；beta 落在 `unsupported_domains`（L7）。
pub(super) fn decorate_input(data: &mut Value) {
    let conditions: Vec<Value> = CONDITIONS
        .iter()
        .map(|(id, capability, stage)| json!({"condition_id":id,"authority_revision":capability,"dependency_set":["controlled-dependency"],"invalidation_sources":["controlled-invalidation"],"required_check_stages":[stage],"evidence_refs":["controlled-evidence"],"coverage_proof":"controlled-coverage","validator_capability":capability,"failure_result":"Denied"}))
        .collect();
    let domain = |concurrency: &str| json!({"order_kind":"limit","concurrency":concurrency,"allocation_model":"#1349/atomic-slot-wait/v1"});
    data["exact_release"] = json!({"x_target":{"x_id":"X","x_epoch":"1"},"projection_kind":"per_leg","rd11_policy":"controlled-fixture-rd11","rule_revision":"TestOnly-rule/1407-c1","market_dependencies":["TestOnly-market/1407-c1"],"conditions":conditions,"model_coverage":{"model_ref":"history-sim/bar-batch-known-frontier/1","domain_id":"TestOnly-domain/1407-c1","input_domain":[domain("single")],"unsupported_domains":[domain("batched")]}});
    for q in data["plans"].as_array_mut().unwrap() {
        let name = q["decision_id"].as_str().unwrap().to_owned();
        q["exact"] = json!({"command_id":format!("cmd-{name}"),"logical_order_family":format!("family-{name}"),"chong_id":name,"revision":"1","first_quantity":q["quantity"],"allocation_id":format!("alloc-{name}"),"side":"buy","symbol":name,"projection_manifest":format!("TestOnly-projection/{name}"),"eligibility_ref":format!("S:cmd-{name}"),"concurrency":if name == "alpha" {"single"} else {"batched"}});
    }
}
pub(super) fn decorate_manifest(manifest: &mut Value) {
    manifest["authorized_sources"][0]["operations"]
        .as_array_mut()
        .unwrap()
        .extend(EXACT_OPS.iter().map(|op| json!(op)));
    let clocks = &mut manifest["clock"]["plan"]["messages"];
    for (message, t) in [
        ("MakeDispatchable-alpha", 140),
        ("MakeDispatchable-beta", 150),
        ("ReleaseExact-alpha", 160),
        ("ReleaseExact-beta", 170),
        ("capture-late", 180),
        ("ReleaseExact-alpha-late", 190),
    ] {
        clocks[message] = json!({"received_ns":t.to_string(),"first_known_ns":(t+1).to_string(),"commit_ns":(t+2).to_string()});
    }
}

fn fixture(fault: Option<(&str, &str)>) -> Fixture {
    Fixture::build_with(
        "100",
        fault,
        &[("slot", &["alpha", "beta"])],
        None,
        None,
        None,
        None,
        None,
        None,
        true,
    )
}
/// B Prepare → E Reserve → B Commit，全部经 `service::handle`。
fn committed(f: &mut Fixture) {
    for (n, name) in [(1, "alpha"), (2, "beta")] {
        let p = f.request("PrepareDecision", name)["payload"].clone();
        let r = f.handle(n, &format!("PrepareDecision-{name}"), p);
        assert_eq!(r["kind"], "PreparedReceipt", "{r}");
    }
    let r = reserve_now(f, "Reserve-slot");
    assert_eq!(r["record"]["state"], "Reserved", "{r}");
    for (n, name) in [(1, "alpha"), (2, "beta")] {
        let p = f.request("CommitDecision", name)["payload"].clone();
        let r = f.handle(n, &format!("CommitDecision-{name}"), p);
        assert_eq!(r["record"]["state"], "Committed", "{r}");
    }
}
fn plan_of(f: &Fixture, name: &str) -> Value {
    item(list(&f.data, "plans").unwrap(), "decision_id", name)
        .unwrap()
        .clone()
}
fn dispatch_payload(f: &Fixture, name: &str) -> Value {
    json!({"op":"MakeDispatchable","decision_id":name,"plan_hash":hash(&plan_of(f,name)),"writer_epoch":"1"})
}
fn dispatch(f: &mut Fixture, name: &str) -> Value {
    let p = dispatch_payload(f, name);
    let r = f.handle(0, &format!("MakeDispatchable-{name}"), p);
    assert_eq!(r["kind"], "DispatchableReceipt", "{r}");
    r
}
fn grant_id(f: &Fixture, name: &str) -> String {
    let r = row(
        &f.dbs[0],
        "receipts",
        &receipt_key_for(&f.configs[0], "Reserve", "slot").unwrap(),
    )
    .unwrap()
    .unwrap();
    r["record"]["grants"]
        .as_array()
        .unwrap()
        .iter()
        .find(|g| g["decision_id"] == name)
        .unwrap()["grant_id"]
        .as_str()
        .unwrap()
        .to_owned()
}
fn int(v: &Value) -> i64 {
    v.as_str().unwrap().parse().unwrap()
}
/// 测试侧独立组装的期望 ExactCommand（#1942 `runtime.rs:108-122` 字段集）。
fn expected_command(f: &Fixture, name: &str) -> Value {
    let q = plan_of(f, name);
    let s = &f.data["exact_release"];
    let x = &q["exact"];
    let change = json!({"kind":"submit","order":{"command_id":x["command_id"],"family_id":x["logical_order_family"],"chong_id":x["chong_id"],"revision":1,"side":"buy","quantity":int(&q["quantity"]),"kind":{"kind":"limit","price":int(&q["limit_price"])},"eligibility_ref":x["eligibility_ref"],"projection_manifest":x["projection_manifest"]}});
    let certificate = json!({"rd11_policy":s["rd11_policy"],"responsibility_refs":[grant_id(f,name)],"structure_dependencies":[format!("{}@{}",q["s_ref"]["object_id"].as_str().unwrap(),q["s_ref"]["object_hash"].as_str().unwrap())],"market_dependencies":s["market_dependencies"],"rule_revision":s["rule_revision"],"conditions":s["conditions"]});
    json!({"command_id":x["command_id"],"logical_order_family":x["logical_order_family"],"session_id":f.configs[0].session,"session_generation":f.configs[0].generation,"x_id":"X","x_epoch":1,"symbol":x["symbol"],"projection_kind":"per_leg","change":change,"plan_hash":hash(&change),"certificate_hash":hash(&certificate),"certificate":certificate})
}
fn release_payload(f: &Fixture, name: &str) -> Value {
    let c = expected_command(f, name);
    json!({"op":"ReleaseExact","decision_id":name,"command_id":c["command_id"],"plan_hash":c["plan_hash"],"certificate":c["certificate"],"x_id":"X","x_epoch":"1","writer_epoch":"1"})
}
/// #1942 `runtime.rs:433` X 向 E 发出的帧即本请求 payload。
fn authority_query(f: &Fixture, command: &Value, epoch: &str) -> Value {
    json!({"op":"QueryReleasedExact","protocol":"x-exact-authority/1","session_id":f.configs[0].session,"session_generation":f.configs[0].generation,"authority_id":"E","authority_epoch":epoch,"command_id":command["command_id"],"command_hash":hash(command),"command":command,"release_receipt_id":null})
}
fn query_command(f: &mut Fixture, name: &str) -> Value {
    f.handle(
        0,
        "query-command",
        json!({"op":"QueryCommand","command_id":format!("cmd-{name}"),"cut":null,"as_known_ns":null}),
    )
}
fn snapshot(f: &Fixture) -> Vec<(i64, String, String, String)> {
    (0..3)
        .map(|n| {
            let (s, h, ns, image) = latest(&f.dbs[n]).unwrap();
            (s, h, ns, canonical_json(&image))
        })
        .collect()
}
/// 拒绝时三个域的活跃版本与 E 图像逐字节不变，也不留该身份的回执。
fn assert_rejected(f: &mut Fixture, message: &str, payload: Value, kind: &str) -> Value {
    let before = snapshot(f);
    let r = f.handle(0, message, payload.clone());
    c4a_error(&r, kind);
    assert_eq!(before, snapshot(f), "拒绝不得改动任何域");
    assert!(row(
        &f.dbs[0],
        "receipts",
        &key_for(&f.configs[0], &payload).unwrap()
    )
    .unwrap()
    .is_none());
    r
}

#[test]
fn l1_formal_entry_releases_exact_in_the_e_sequence() {
    let mut f = fixture(None);
    committed(&mut f);
    let liability = responsibility_total(&latest(&f.dbs[0]).unwrap().3);
    assert_eq!(liability, 90);
    let d = dispatch(&mut f, "alpha");
    assert_eq!(d["record"]["state"], "Dispatchable");
    assert_eq!(d["record"]["execution_eligibility"], "None");
    let r = f.handle(0, "ReleaseExact-alpha", release_payload(&f, "alpha"));
    assert_eq!(r["kind"], "ReleasedExactReceipt", "{r}");
    let record = &r["record"];
    assert_eq!(record["state"], "ReleasedExact");
    assert_eq!(record["release_commit_ns"], "162");
    assert_eq!(record["command"], expected_command(&f, "alpha"));
    assert_eq!(record["command_hash"], hash(&expected_command(&f, "alpha")));
    assert_eq!(record["first_quantity"], "2");
    assert_eq!(record["allocation_id"], "alloc-alpha");
    assert_eq!(record["responsibility_ref"], grant_id(&f, "alpha"));
    let (seq, _, ns, image) = latest(&f.dbs[0]).unwrap();
    assert_eq!(r["cut"]["commit_seq"], seq.to_string());
    assert_eq!(ns, "162");
    let history = image["history"].as_array().unwrap();
    let seqs: Vec<String> = history
        .iter()
        .map(|e| e["commit_seq"].as_str().unwrap().to_owned())
        .collect();
    let expected: Vec<String> = (1..=seq).map(|n| n.to_string()).collect();
    assert_eq!(seqs, expected, "Capture、Reserve、Release 同一 E 提交序列");
    assert!(history.iter().any(|e| e["kind"] == "CaptureExternal"));
    assert_eq!(history.last().unwrap()["kind"], "ReleaseExact");
    assert_eq!(responsibility_total(&image), liability, "Release 不改责任");
    let reply = f.handle(
        0,
        "query-released",
        authority_query(&f, &expected_command(&f, "alpha"), "1"),
    );
    assert_eq!(reply["state"], "ReleasedExact", "{reply}");
    assert_eq!(reply["commit_ns"], 162);
    f.audit();
}

#[test]
fn l2_commit_only_cannot_release_and_dispatchable_is_not_released() {
    let mut f = fixture(None);
    committed(&mut f);
    let p = release_payload(&f, "alpha");
    let r = assert_rejected(&mut f, "ReleaseExact-alpha", p, "InvalidDomain");
    assert!(r["error"].as_str().unwrap().contains("Dispatchable"), "{r}");
    dispatch(&mut f, "alpha");
    let command = expected_command(&f, "alpha");
    let reply = f.handle(0, "query-released", authority_query(&f, &command, "1"));
    assert_eq!(reply["state"], "NoRecord", "{reply}");
    assert_eq!(query_command(&mut f, "alpha")["state"], "Dispatchable");
    let released = f.handle(0, "ReleaseExact-alpha", release_payload(&f, "alpha"));
    assert_eq!(released["record"]["state"], "ReleasedExact", "{released}");
    let reply = f.handle(0, "query-released", authority_query(&f, &command, "1"));
    assert_eq!(reply["state"], "ReleasedExact", "{reply}");
    assert_eq!(query_command(&mut f, "alpha")["state"], "ReleasedExact");
}

#[test]
fn l3_missing_condition_or_condition_field_is_unsupported_and_e_unchanged() {
    let mut f = fixture(None);
    committed(&mut f);
    dispatch(&mut f, "alpha");
    let full = release_payload(&f, "alpha");
    for i in 0..CONDITIONS.len() {
        let mut p = full.clone();
        p["certificate"]["conditions"]
            .as_array_mut()
            .unwrap()
            .remove(i);
        assert_rejected(&mut f, "ReleaseExact-alpha", p, "Unsupported：");
    }
    for field in CONDITION_FIELDS {
        for i in 0..CONDITIONS.len() {
            let mut p = full.clone();
            p["certificate"]["conditions"][i]
                .as_object_mut()
                .unwrap()
                .remove(field);
            let r = assert_rejected(&mut f, "ReleaseExact-alpha", p, "Unsupported：");
            assert!(!r["error"].as_str().unwrap().is_empty(), "{field}");
        }
    }
    let r = f.handle(0, "ReleaseExact-alpha", full);
    assert_eq!(r["record"]["state"], "ReleasedExact", "{r}");
}

#[test]
fn l4_same_command_changed_content_conflicts_and_replay_is_byte_identical() {
    let mut f = fixture(None);
    committed(&mut f);
    dispatch(&mut f, "alpha");
    let full = release_payload(&f, "alpha");
    let mut wrong_epoch = full.clone();
    wrong_epoch["x_epoch"] = json!("2");
    assert_rejected(
        &mut f,
        "ReleaseExact-alpha",
        wrong_epoch.clone(),
        "IdentityConflict",
    );
    let original = f.handle(0, "ReleaseExact-alpha", full.clone());
    assert_eq!(original["kind"], "ReleasedExactReceipt", "{original}");
    let before = snapshot(&f);
    let same = f.handle(0, "ReleaseExact-alpha", full.clone());
    assert_eq!(canonical_json(&same), canonical_json(&original));
    let resent = f.handle(0, "ReleaseExact-alpha-resend", full.clone());
    assert_eq!(canonical_json(&resent), canonical_json(&original));
    assert_eq!(before, snapshot(&f), "重放不增加提交");
    let mut changed_plan = full.clone();
    changed_plan["plan_hash"] = json!(hash(&json!("another plan")));
    let mut changed_certificate = full.clone();
    changed_certificate["certificate"]["rule_revision"] = json!("TestOnly-rule/other");
    for (message, p) in [
        ("conflict-plan", changed_plan),
        ("conflict-certificate", changed_certificate),
        ("conflict-epoch", wrong_epoch),
    ] {
        let r = f.handle(0, message, p);
        c4a_error(&r, "IdentityConflict");
        assert_eq!(before, snapshot(&f), "{message}");
    }
    assert_eq!(
        canonical_json(
            &row(
                &f.dbs[0],
                "receipts",
                &key_for(&f.configs[0], &full).unwrap()
            )
            .unwrap()
            .unwrap()
        ),
        canonical_json(&original)
    );
    f.audit();
}

#[test]
fn l6_uncovered_pending_after_reserve_blocks_release_and_keeps_liability() {
    let mut control = fixture(None);
    committed(&mut control);
    dispatch(&mut control, "alpha");
    let p = release_payload(&control, "alpha");
    let ok = control.handle(0, "ReleaseExact-alpha-late", p);
    assert_eq!(ok["record"]["state"], "ReleasedExact", "{ok}");

    let mut f = fixture(None);
    committed(&mut f);
    dispatch(&mut f, "alpha");
    let doc = extra_opening_doc("late-opening", "allocation-late");
    let captured = f.handle(
        0,
        "capture-late",
        json!({"op":"CaptureExternal","raw_utf8":canonical_json(&doc),"json_pointer":"/events/0","token":"token-late","source_event_time":null}),
    );
    assert_eq!(captured["kind"], "Recorded", "{captured}");
    let p = release_payload(&f, "alpha");
    let r = assert_rejected(&mut f, "ReleaseExact-alpha-late", p, "MissingDependency");
    assert!(r["error"].as_str().unwrap().contains("Pending"), "{r}");
    assert_eq!(responsibility_total(&latest(&f.dbs[0]).unwrap().3), 90);
    assert_eq!(query_command(&mut f, "alpha")["state"], "Dispatchable");
}

#[test]
fn l7_model_coverage_out_of_domain_persists_unsupported_without_release() {
    let mut f = fixture(None);
    committed(&mut f);
    dispatch(&mut f, "alpha");
    dispatch(&mut f, "beta");
    let ok = f.handle(0, "ReleaseExact-alpha", release_payload(&f, "alpha"));
    assert_eq!(ok["record"]["state"], "ReleasedExact", "{ok}");
    let seq = latest(&f.dbs[0]).unwrap().0;
    let r = f.handle(0, "ReleaseExact-beta", release_payload(&f, "beta"));
    assert_eq!(r["kind"], "ReleaseUnsupportedReceipt", "{r}");
    assert_eq!(r["record"]["state"], "Unsupported");
    assert_eq!(
        r["record"]["unsupported"],
        json!({"reason":"ModelOrderUnspecified","model_ref":"history-sim/bar-batch-known-frontier/1","domain_id":"TestOnly-domain/1407-c1","command_id":"cmd-beta"})
    );
    assert!(r["record"].get("release_commit_ns").is_none());
    assert_eq!(latest(&f.dbs[0]).unwrap().0, seq + 1, "终态持久");
    assert_eq!(query_command(&mut f, "beta")["state"], "Unsupported");
    let command = expected_command(&f, "beta");
    let reply = f.handle(0, "query-released", authority_query(&f, &command, "1"));
    assert_eq!(reply["state"], "Unsupported", "{reply}");
    let again = f.handle(0, "ReleaseExact-beta", release_payload(&f, "beta"));
    assert_eq!(canonical_json(&again), canonical_json(&r));
    assert_eq!(responsibility_total(&latest(&f.dbs[0]).unwrap().3), 90);
    f.audit();
}

/// #1942 head 40bf421fc3 `rust/src/history_simulation/{runtime.rs:85-122,210-222, model.rs:7-31,186-198}`
/// 的线上类型原样镜像（含 `deny_unknown_fields`）。E 的回复必须能被它们严格解码，且再编码后逐字段相等。
mod wire_1942 {
    use serde::{Deserialize, Serialize};
    #[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
    #[serde(rename_all = "snake_case")]
    pub enum Side {
        Buy,
        Sell,
    }
    #[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
    #[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
    pub enum OrderKind {
        Limit { price: i64 },
        Market { exec_index: i64 },
    }
    #[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
    #[serde(deny_unknown_fields)]
    pub struct Order {
        pub command_id: String,
        pub family_id: String,
        pub chong_id: String,
        pub revision: i64,
        pub side: Side,
        pub quantity: i64,
        pub kind: OrderKind,
        pub eligibility_ref: String,
        pub projection_manifest: String,
    }
    #[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
    #[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
    pub enum Change {
        Submit {
            order: Order,
        },
        Cancel {
            family_id: String,
            command_id: String,
            eligibility_ref: String,
        },
        Replace {
            order: Order,
        },
    }
    #[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
    #[serde(deny_unknown_fields)]
    pub struct Condition {
        pub condition_id: String,
        pub authority_revision: String,
        pub dependency_set: Vec<String>,
        pub invalidation_sources: Vec<String>,
        pub required_check_stages: Vec<String>,
        pub evidence_refs: Vec<String>,
        pub coverage_proof: String,
        pub validator_capability: String,
        pub failure_result: String,
    }
    #[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
    #[serde(deny_unknown_fields)]
    pub struct Certificate {
        pub rd11_policy: String,
        pub responsibility_refs: Vec<String>,
        pub structure_dependencies: Vec<String>,
        pub market_dependencies: Vec<String>,
        pub rule_revision: String,
        pub conditions: Vec<Condition>,
    }
    #[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
    #[serde(deny_unknown_fields)]
    pub struct ExactCommand {
        pub command_id: String,
        pub logical_order_family: String,
        pub session_id: String,
        pub session_generation: String,
        pub x_id: String,
        pub x_epoch: i64,
        pub symbol: String,
        pub projection_kind: String,
        pub change: Change,
        pub plan_hash: String,
        pub certificate_hash: String,
        pub certificate: Certificate,
    }
    #[derive(Debug, Serialize, Deserialize)]
    #[serde(deny_unknown_fields)]
    pub struct AuthorityReply {
        pub protocol: String,
        pub session_id: String,
        pub session_generation: String,
        pub authority_id: String,
        pub authority_epoch: String,
        pub command_id: String,
        pub command_hash: String,
        pub command: ExactCommand,
        pub state: String,
        pub receipt_id: String,
        pub release_receipt_id: Option<String>,
        pub commit_ns: i64,
    }
}

#[test]
fn l8_released_exact_reply_decodes_as_1942_authority_reply() {
    let mut f = fixture(None);
    committed(&mut f);
    dispatch(&mut f, "alpha");
    let released = f.handle(0, "ReleaseExact-alpha", release_payload(&f, "alpha"));
    assert_eq!(released["record"]["state"], "ReleasedExact", "{released}");
    let command = expected_command(&f, "alpha");
    let reply = f.handle(0, "query-released", authority_query(&f, &command, "1"));
    let decoded: wire_1942::AuthorityReply = serde_json::from_value(reply.clone())
        .unwrap_or_else(|e| panic!("#1942 AuthorityReply 严格解码失败：{e}: {reply}"));
    assert_eq!(
        serde_json::to_value(&decoded).unwrap(),
        reply,
        "十二字段逐项相等"
    );
    assert_eq!(decoded.protocol, "x-exact-authority/1");
    assert_eq!(decoded.state, "ReleasedExact");
    assert_eq!(decoded.authority_id, "E");
    assert_eq!(decoded.authority_epoch, "1");
    assert_eq!(decoded.release_receipt_id, None);
    assert_eq!(decoded.commit_ns, 162);
    assert_eq!(
        decoded.command_hash,
        sha256_hex(canonical_json(&reply["command"]).as_bytes())
    );
    assert_eq!(reply["command"], command);
    for (message, mut q, kind) in [
        (
            "query-stale",
            authority_query(&f, &command, "2"),
            "StaleWriter",
        ),
        (
            "query-hash",
            authority_query(&f, &command, "1"),
            "IdentityConflict",
        ),
        (
            "query-content",
            authority_query(&f, &command, "1"),
            "IdentityConflict",
        ),
    ] {
        if message == "query-hash" {
            q["command_hash"] = json!(hash(&json!("other")));
        }
        if message == "query-content" {
            q["command"]["symbol"] = json!("other");
            q["command_hash"] = json!(hash(&q["command"]));
        }
        c4a_error(&f.handle(0, message, q), kind);
    }
}

/// 子进程入口：只由下方 kill 矩阵与 L9 新进程重放调用。
#[test]
#[ignore = "仅供 #1407 具名子进程调度调用"]
fn exact_child() {
    let job_path = PathBuf::from(std::env::var_os("I1407_CHILD_JOB").expect("child job required"));
    let job = strict_json(&std::fs::read(&job_path).unwrap()).unwrap();
    let config = Config::load(
        Path::new(required(&job, "manifest").unwrap()),
        Path::new(required(&job, "db").unwrap()),
        None,
    )
    .unwrap();
    let result = match required(&job, "action").unwrap() {
        "recover" => recover(&config).unwrap(),
        "audit" => {
            let (c, _) = open(&config.db, false).unwrap();
            audit(&c, &config).unwrap();
            row(&c, "receipts", required(&job, "receipt_key").unwrap())
                .unwrap()
                .unwrap()
        }
        _ => {
            let epoch = positive(required(&job, "epoch").unwrap(), "epoch").unwrap();
            let (mut c, _) = open(&config.db, false).unwrap();
            service::handle(&mut c, &config, epoch, epoch, &json!({}), &job["request"])
        }
    };
    save(
        job_path.parent().unwrap(),
        &format!("{}-result.json", required(&job, "label").unwrap()),
        &result,
    );
}
fn run_child(f: &Fixture, label: &str, mut job: Value) -> std::process::Child {
    job["label"] = json!(label);
    job["manifest"] = json!(f.dir.join("manifest.json"));
    job["db"] = json!(f.configs[0].db);
    let (path, _) = save(&f.dir, &format!("{label}-job.json"), &job);
    std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "economic_session::finance::tests::exact_release::exact_child",
            "--ignored",
            "--nocapture",
        ])
        .env("I1407_CHILD_JOB", path)
        .stdout(std::fs::File::create(f.dir.join(format!("{label}.stdout"))).unwrap())
        .stderr(std::fs::File::create(f.dir.join(format!("{label}.stderr"))).unwrap())
        .spawn()
        .unwrap()
}
fn child_result(f: &Fixture, label: &str, job: Value) -> Value {
    assert!(
        run_child(f, label, job).wait().unwrap().success(),
        "{label}: {}",
        f.dir.display()
    );
    strict_json(&std::fs::read(f.dir.join(format!("{label}-result.json"))).unwrap()).unwrap()
}
fn wire(f: &Fixture, message: &str, payload: Value) -> Value {
    let mut e = envelope(message, payload);
    e["schema_revision"] = json!(f.configs[0].revision().unwrap());
    e["session_id"] = json!(f.configs[0].session);
    e["session_generation"] = json!(f.configs[0].generation);
    e
}

#[test]
fn l5_sigkill_before_and_after_commit_recovers_by_original_identity() {
    let mut observations = vec![];
    for op in ["MakeDispatchable", "ReleaseExact"] {
        for phase in ["before_commit", "after_commit"] {
            let mut two = vec![];
            for repetition in 0..2 {
                let message = format!("{op}-alpha");
                let mut f = fixture(Some((&message, phase)));
                committed(&mut f);
                let payload = if op == "MakeDispatchable" {
                    dispatch_payload(&f, "alpha")
                } else {
                    dispatch(&mut f, "alpha");
                    release_payload(&f, "alpha")
                };
                let request = wire(&f, &message, payload.clone());
                let previous = latest(&f.dbs[0]).unwrap();
                let liability = responsibility_total(&previous.3);
                let mut process = run_child(
                    &f,
                    "write",
                    json!({"action":"handle","epoch":"1","request":request}),
                );
                let deadline = std::time::Instant::now() + std::time::Duration::from_secs(30);
                while !f.dir.join("fault-marker.json").exists() {
                    if let Some(status) = process.try_wait().unwrap() {
                        panic!("子进程未到故障缝即退出 {status}: {}", f.dir.display())
                    }
                    assert!(
                        std::time::Instant::now() < deadline,
                        "故障 marker 超时：{}",
                        f.dir.display()
                    );
                    std::thread::sleep(std::time::Duration::from_millis(10));
                }
                process.kill().unwrap();
                let killed = process.wait().unwrap();
                use std::os::unix::process::ExitStatusExt;
                assert_eq!(killed.signal(), Some(9));
                let durable = phase == "after_commit";
                let current = latest(&f.dbs[0]).unwrap();
                assert_eq!(current.0, previous.0 + i64::from(durable));
                let original = row(
                    &f.dbs[0],
                    "receipts",
                    &key_for(&f.configs[0], &payload).unwrap(),
                )
                .unwrap();
                assert_eq!(original.is_some(), durable);
                child_result(&f, "recover", json!({"action":"recover"}));
                assert_eq!(meta(&f.dbs[0], "writer_epoch").unwrap(), "2");
                let query = wire(
                    &f,
                    "query-after-kill",
                    json!({"op":"QueryCommand","command_id":"cmd-alpha","cut":null,"as_known_ns":null}),
                );
                let state = child_result(
                    &f,
                    "query",
                    json!({"action":"handle","epoch":"2","request":query}),
                )["payload"]["state"]
                    .clone();
                let expected_state = match (op, durable) {
                    ("MakeDispatchable", false) => "NoRecord",
                    ("MakeDispatchable", true) | ("ReleaseExact", false) => "Dispatchable",
                    _ => "ReleasedExact",
                };
                assert_eq!(state, expected_state);
                let authority = if op == "ReleaseExact" {
                    let q = wire(
                        &f,
                        "authority-after-kill",
                        authority_query(&f, &expected_command(&f, "alpha"), "2"),
                    );
                    let reply = child_result(
                        &f,
                        "authority",
                        json!({"action":"handle","epoch":"2","request":q}),
                    )["payload"]
                        .clone();
                    assert_eq!(
                        reply["state"],
                        if durable { "ReleasedExact" } else { "NoRecord" },
                        "{reply}"
                    );
                    if durable {
                        assert_eq!(reply["commit_ns"], 162);
                    }
                    reply["state"].clone()
                } else {
                    Value::Null
                };
                let retried =
                    service::handle(&mut f.dbs[0], &f.configs[0], 2, 2, &json!({}), &request)
                        ["payload"]
                        .clone();
                if durable {
                    assert_eq!(
                        canonical_json(&retried),
                        canonical_json(original.as_ref().unwrap())
                    );
                } else {
                    c4a_error(&retried, "StaleWriter");
                }
                assert_eq!(
                    latest(&f.dbs[0]).unwrap(),
                    current,
                    "查询与重试不增加经济动作"
                );
                assert_eq!(responsibility_total(&current.3), liability, "责任不变");
                audit(&f.dbs[0], &f.configs[0]).unwrap();
                let comparison = json!({"op":op,"phase":phase,"durable":durable,"state":state,"authority":authority,"retained_liability":liability.to_string(),"restored_writer_epoch":"2"});
                two.push(comparison.clone());
                observations.push(json!({"repetition":repetition,"signal":killed.signal(),"comparison":comparison,"original_receipt":original,"raw_dir":f.dir}));
            }
            assert_eq!(two[0], two[1]);
        }
    }
    let root = std::env::var_os("TB03B_TEST_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    save(
        &root,
        &format!("issue1407-c1-kill-matrix-{}.json", std::process::id()),
        &json!({"scenarios":observations,"count":"8","scope":"MakeDispatchable/ReleaseExact × before/after commit × 2 fresh processes; unit S/gamma trust roots"}),
    );
}

/// L9 独立 oracle：`exact_command_oracle.py` 用 Python 标准库从手写字段算出 alpha 的 ExactCommand 规范字节与
/// sha256，落成 `exact_command_oracle.json`。E 产出的命令须逐字节相等；新进程全量重放后收据逐字节不变。
#[test]
fn l9_worked_example_matches_independent_oracle_and_fresh_replay() {
    let oracle = strict_json(include_str!("exact_command_oracle.json").as_bytes()).unwrap();
    let mut f = fixture(None);
    committed(&mut f);
    dispatch(&mut f, "alpha");
    let receipt = f.handle(0, "ReleaseExact-alpha", release_payload(&f, "alpha"));
    assert_eq!(receipt["record"]["state"], "ReleasedExact", "{receipt}");
    let command = &receipt["record"]["command"];
    assert_eq!(
        canonical_json(command),
        oracle["command_canonical"].as_str().unwrap()
    );
    assert_eq!(
        sha256_hex(canonical_json(command).as_bytes()),
        oracle["command_sha256"]
    );
    assert_eq!(receipt["record"]["command_hash"], oracle["command_sha256"]);
    assert_eq!(command["plan_hash"], oracle["plan_hash"]);
    assert_eq!(command["certificate_hash"], oracle["certificate_hash"]);
    let key = key_for(&f.configs[0], &release_payload(&f, "alpha")).unwrap();
    let replayed = child_result(&f, "replay", json!({"action":"audit","receipt_key":key}));
    assert_eq!(canonical_json(&replayed), canonical_json(&receipt));
}
