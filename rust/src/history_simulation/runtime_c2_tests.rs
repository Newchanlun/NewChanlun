//! #1407 C2 第 1、2 项：X 侧的获准条件清单与 `x-exact-authority/1` 共同信封。
use super::*;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixListener;
use std::path::PathBuf;

fn condition(id: &str, capability: &str, stage: &str) -> Value {
    json!({"condition_id":id,"authority_revision":capability,"dependency_set":["d"],"invalidation_sources":["i"],
        "required_check_stages":[stage],"evidence_refs":["e"],"coverage_proof":"c","validator_capability":capability,"failure_result":"Denied"})
}
fn approved() -> Value {
    json!([
        condition("released-exact/1", "released-exact/1", "E.ReleaseExact"),
        condition(
            "execute-committed/1",
            "execute-committed/1",
            "S.RequestConditionalExecution"
        ),
        condition(
            "simulation-local-transaction/1",
            "simulation-local-transaction/1",
            "X.OwnAttemptAndCall"
        ),
        condition("model_coverage", "model-coverage/1", "E.ReleaseExact"),
    ])
}
fn profile(dir: &Path, conditions: Value) -> Value {
    let authority = |name: &str| {
        json!({"socket":dir.join(name),"authority_id":name.to_uppercase(),"authority_epoch":"1",
        "schema_revision":format!("{name}-schema/1"),"reply_namespace":format!("{name}/replies"),"producer_id":format!("{name}:session")})
    };
    json!({"model":super::super::tests::model(),"session_id":"session","session_generation":"1","x_id":"X",
        "source_namespace":"x-sim","source_epoch":"epoch1","socket":dir.join("x"),"e":authority("e"),"s":authority("s"),
        "conditions":conditions,"timeout_ms":2000,"max_frame_bytes":65536})
}
fn command(conditions: Value) -> Value {
    let change = json!({"kind":"submit","order":{"command_id":"a","family_id":"f-a","chong_id":"a","revision":1,"side":"buy",
        "quantity":5,"kind":{"kind":"limit","price":100},"eligibility_ref":"S:a","projection_manifest":"p-a"}});
    let certificate = json!({"rd11_policy":"controlled-fixture-rd11","responsibility_refs":["r"],"structure_dependencies":["s"],
        "market_dependencies":["m"],"rule_revision":"rule","conditions":conditions});
    json!({"command_id":"a","logical_order_family":"f-a","session_id":"session",
        "session_generation":"1","x_id":"X","x_epoch":1,"symbol":"TEST","projection_kind":"per_leg","plan_hash":hash(&change),
        "certificate_hash":hash(&certificate),"change":change,"certificate":certificate})
}
fn parse<T: serde::de::DeserializeOwned>(v: Value) -> T {
    serde_json::from_value(v).unwrap()
}
fn dir(tag: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("i1407c2-{tag}-{}", std::process::id()));
    std::fs::create_dir_all(&d).unwrap();
    d
}

#[test]
fn conditions_equal_the_approved_list_including_model_coverage() {
    let d = dir("cond");
    let p: Profile = parse(profile(&d, approved()));
    p.validate().unwrap();
    let ok: ExactCommand = parse(command(approved()));
    ok.validate(&p, 1).unwrap();

    let mut three = approved();
    three.as_array_mut().unwrap().pop();
    let mut reordered = approved();
    reordered.as_array_mut().unwrap().swap(0, 3);
    for list in [three.clone(), reordered] {
        let c: ExactCommand = parse(command(list));
        let e = c.validate(&p, 1).unwrap_err();
        assert!(e.starts_with("Unsupported：条件清单与获准"), "{e}");
    }
    let without_coverage: Profile = parse(profile(&d, three));
    let e = without_coverage.validate().unwrap_err();
    assert!(
        e.starts_with("MissingDependency：获准条件清单缺 E-Release"),
        "{e}"
    );
    let mut unknown_x = approved();
    unknown_x[2]["validator_capability"] = json!("venue-call/1");
    let e = parse::<Profile>(profile(&d, unknown_x))
        .validate()
        .unwrap_err();
    assert!(
        e.starts_with("Unsupported：ConditionEvidence 核验能力不在已知配对表"),
        "{e}"
    );
    let mut missing_field = approved();
    missing_field[1]["evidence_refs"] = json!([]);
    let e = parse::<Profile>(profile(&d, missing_field))
        .validate()
        .unwrap_err();
    assert!(e.starts_with("Unsupported：获准条件缺"), "{e}");
}

/// 语义闸与 E 冻结原件共用 `check_condition_semantics`；同一组反例在 E 侧见
/// `frozen_conditions_refuse_unpaired_or_non_denied_semantics`。
#[test]
fn profile_conditions_refuse_unpaired_or_non_denied_semantics() {
    let d = dir("semantics");
    for (case, index, field, value, expected) in [
        (
            "failure-not-denied",
            1,
            "failure_result",
            json!("Ignore"),
            "Unsupported：ConditionEvidence 失败语义须为 Denied",
        ),
        (
            "coverage-failure-not-denied",
            3,
            "failure_result",
            json!("Ignore"),
            "Unsupported：ConditionEvidence 失败语义须为 Denied",
        ),
        (
            "unknown-e-capability",
            0,
            "capability",
            json!("venue-precheck/1"),
            "Unsupported：ConditionEvidence 核验能力不在已知配对表",
        ),
        (
            "unknown-stage-prefix",
            1,
            "required_check_stages",
            json!(["Q.Inspect"]),
            "Unsupported：ConditionEvidence 检查阶段前缀未知",
        ),
        (
            "mispaired-stage",
            1,
            "required_check_stages",
            json!(["E.ReleaseExact"]),
            "Unsupported：ConditionEvidence 能力与阶段",
        ),
        (
            "coverage-wrong-capability",
            3,
            "capability",
            json!("released-exact/1"),
            "Unsupported：model_coverage 须且只能",
        ),
    ] {
        let mut list = approved();
        if field == "capability" {
            list[index]["validator_capability"] = value.clone();
            list[index]["authority_revision"] = value;
        } else {
            list[index][field] = value;
        }
        let e = parse::<Profile>(profile(&d, list)).validate().unwrap_err();
        assert!(e.starts_with(expected), "{case}: {e}");
    }
}

/// 完备闸：配对表里 E/S/X 各阶段的能力缺任何一项，profile 即被拒；同一组反例在 E 侧见
/// `frozen_conditions_refuse_a_missing_or_repeated_required_capability`。只含 model_coverage 的清单曾能通过。
#[test]
fn profile_conditions_refuse_a_missing_or_repeated_required_capability() {
    let d = dir("required");
    for (index, capability) in [
        (0, "released-exact/1 @ E.ReleaseExact"),
        (1, "execute-committed/1 @ S.RequestConditionalExecution"),
        (2, "simulation-local-transaction/1 @ X.OwnAttemptAndCall"),
    ] {
        let mut list = approved();
        list.as_array_mut().unwrap().remove(index);
        let e = parse::<Profile>(profile(&d, list)).validate().unwrap_err();
        assert_eq!(
            e,
            format!("MissingDependency：获准条件清单缺必备核验能力 {capability}")
        );
    }
    let coverage_only = json!([approved()[3].clone()]);
    let e = parse::<Profile>(profile(&d, coverage_only))
        .validate()
        .unwrap_err();
    assert!(
        e.starts_with("MissingDependency：获准条件清单缺必备核验能力 released-exact/1"),
        "{e}"
    );
    let mut repeated = approved();
    let mut again = repeated[1].clone();
    again["condition_id"] = json!("execute-committed/1#again");
    repeated.as_array_mut().unwrap().push(again);
    let e = parse::<Profile>(profile(&d, repeated))
        .validate()
        .unwrap_err();
    assert_eq!(
        e,
        "Unsupported：获准条件清单重复核验能力 execute-committed/1"
    );
}

/// 权威请求是 IC:9 共同信封（同一 `validate_envelope` 判据）；回复须由原请求经 `reply_envelope` 重建得到。
#[test]
fn authority_request_is_a_common_envelope_and_reply_must_bind_it() {
    let d = dir("envelope");
    let p: Profile = parse(profile(&d, approved()));
    let c: ExactCommand = parse(command(approved()));
    let frame = authority_frame(&p, &p.e, 1, "QueryReleasedExact", &c, None).unwrap();
    let sent = crate::session_protocol::strict_json(&frame.bytes[..frame.bytes.len() - 1]).unwrap();
    assert_eq!(sent, frame.envelope);
    crate::session_protocol::validate_envelope(sent.clone(), "e-schema/1").unwrap();
    assert_eq!(
        (
            &sent["source_namespace"],
            &sent["producer_id"],
            &sent["producer_epoch"]
        ),
        (&json!("x-sim"), &json!("X"), &json!("1"))
    );
    let again = authority_frame(&p, &p.e, 1, "QueryReleasedExact", &c, None).unwrap();
    assert_eq!(again.bytes, frame.bytes, "同一请求重试不换 message_id");

    for (case, bind_original) in [("bound", true), ("foreign", false)] {
        let socket = d.join("e");
        let _ = std::fs::remove_file(&socket);
        let listener = UnixListener::bind(&socket).unwrap();
        let reply_for = c.clone();
        let server = std::thread::spawn(move || {
            let (mut s, _) = listener.accept().unwrap();
            let mut line = String::new();
            BufReader::new(&s).read_line(&mut line).unwrap();
            let mut e: Value = serde_json::from_str(&line).unwrap();
            let q = e["payload"].clone();
            let payload = json!({"protocol":AUTHORITY_WIRE,"session_id":q["session_id"],"session_generation":q["session_generation"],
                "authority_id":"E","authority_epoch":"1","command_id":"a","command_hash":hash(&reply_for),"command":reply_for,
                "state":"ReleasedExact","receipt_id":"E:a","release_receipt_id":null,"commit_ns":0});
            if !bind_original {
                e["message_id"] = json!("someone-else");
            }
            let r = reply_envelope(
                &e,
                payload,
                "e-schema/1",
                "session",
                "1",
                "e/replies",
                "e:session",
                "1",
            );
            s.write_all(format!("{}\n", canonical_json(&r)).as_bytes())
                .unwrap();
        });
        let result = authority(&p, &p.e, 1, "QueryReleasedExact", &c, None);
        server.join().unwrap();
        match case {
            "bound" => assert_eq!(result.unwrap().receipt_id, "E:a"),
            _ => assert!(
                result
                    .unwrap_err()
                    .starts_with("IdentityConflict：权威回复信封"),
                "{case}"
            ),
        }
    }
}

#[cfg(target_os = "linux")]
#[test]
fn authority_rebind_commit_boundary_child() {
    let Some(root) = std::env::var_os("X_REBIND_BOUNDARY_FIXTURE") else {
        return;
    };
    let root = PathBuf::from(root);
    let db = root.join("x.db");
    let _lock = crate::session_transport::process_lock(&db, "X").unwrap();
    let cfg = ConfiguredProfile::parse(
        serde_json::from_slice(&std::fs::read(root.join("profile.json")).unwrap()).unwrap(),
    )
    .unwrap();
    let input = RebindInput::parse(&std::fs::read(root.join("input.json")).unwrap()).unwrap();
    let (mut c, _) = crate::economic_session::open_durable_db(&db).unwrap();
    let tx = c
        .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .unwrap();
    cfg.rebind_in_transaction(&tx, 1, &input).unwrap();
    if std::env::var_os("X_REBIND_BOUNDARY_COMMIT").is_some() {
        tx.commit().unwrap();
    }
    // 让主测试真杀本进程；未提交臂的事务仍持锁，已提交臂尚未发布 socket 或应答。
    println!("X_REBIND_BOUNDARY_REACHED");
    std::thread::park();
}

#[cfg(target_os = "linux")]
#[test]
fn authority_rebind_reopens_at_commit_boundary() {
    use std::os::unix::process::ExitStatusExt;
    use std::process::{Command, Stdio};
    let space = tempfile::tempdir().unwrap();
    let root = space.path();
    let db = root.join("x.db");
    let sdb = root.join("s.db");
    let mut business = profile(root, approved());
    business["e"]["producer_id"] = json!("E:session");
    business["s"]["producer_id"] = json!("S:session");
    for key in ["e", "s"] {
        business[key].as_object_mut().unwrap().remove("socket");
    }
    business.as_object_mut().unwrap().remove("socket");
    let s_config = json!({"rule_revision":"rule/1","profile_hash":"1".repeat(64),
        "catalog_hash":"2".repeat(64),"clock_plan_hash":"3".repeat(64),
        "structure_source":{"category":"TestOnlyStructure","namespaces":["testonly.ohlc"]}});
    business["schema_revision"] = json!(X_BUSINESS);
    business["recovery_identity"] = json!({"e_manifest_hash":"a".repeat(64),"s_config":s_config});
    let profile = json!({"business":business,"deployment":{
        "schema_revision":X_DEPLOYMENT,"db":db,"socket":root.join("x"),
        "e_socket":root.join("e"),"s_socket":root.join("s"),
        "recovery_domains":{"e_db":root.join("e.db"),"e_manifest":root.join("e.json"),"s_db":sdb},
    }});
    let handoff = json!({"schema_revision":"x-authority-rebind-input/1","s":{
        "verification":"current-recovery","db":sdb,
        "receipt":{"kind":"NamedRecoveryReceipt","writer_epoch":"2","recover_ns":"100",
            "request":{"schema_revision":"s-recovery/1","domain_id":"S","session_id":"session",
                "session_generation":"1","recovery_id":"r1","clock_event_id":"recover-one",
                "from_epoch":"1","config":s_config,
                "cut":{"generation":"0","structure_cut":"cut-0","index_frontier":""}}}
    }});
    std::fs::write(root.join("profile.json"), canonical_json(&profile)).unwrap();
    std::fs::write(root.join("input.json"), canonical_json(&handoff)).unwrap();
    let cfg = ConfiguredProfile::parse(profile).unwrap();
    {
        let (mut c, _) = crate::economic_session::open_durable_db(&db).unwrap();
        let tx = c.transaction().unwrap();
        cfg.initialize_in_transaction(&tx, 1).unwrap();
        tx.commit().unwrap();
    }
    let kill_at = |after: bool| {
        let mut cmd = Command::new(std::env::current_exe().unwrap());
        cmd.args([
            "--exact",
            "history_simulation::runtime::c2_tests::authority_rebind_commit_boundary_child",
            "--nocapture",
        ])
        .env("X_REBIND_BOUNDARY_FIXTURE", root)
        .stdout(Stdio::piped());
        if after {
            cmd.env("X_REBIND_BOUNDARY_COMMIT", "1");
        }
        let mut child = cmd.spawn().unwrap();
        let out = child.stdout.take().unwrap();
        let reached = BufReader::new(out)
            .lines()
            .any(|line| line.unwrap() == "X_REBIND_BOUNDARY_REACHED");
        assert!(reached);
        child.kill().unwrap();
        assert_eq!(child.wait().unwrap().signal(), Some(libc::SIGKILL));
    };
    let records = || {
        let c =
            Connection::open_with_flags(&db, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
        let mut q = c
            .prepare("SELECT record FROM x_authority_bindings ORDER BY binding_seq")
            .unwrap();
        q.query_map([], |r| r.get::<_, String>(0))
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap()
    };
    let genesis = records();
    assert_eq!(genesis.len(), 1);
    kill_at(false);
    assert_eq!(genesis, records());
    println!("binding insert before commit, SIGKILL: zero new rows");
    kill_at(true);
    let sealed = records();
    assert_eq!(sealed.len(), 2);
    assert_eq!(genesis, sealed[..1]);
    println!("after commit before first acknowledgment, SIGKILL: one new row");

    let (mut c, _) = crate::economic_session::open_durable_db(&db).unwrap();
    let tx = c.transaction().unwrap();
    cfg.rebind_in_transaction(
        &tx,
        1,
        &RebindInput::parse(canonical_json(&handoff).as_bytes()).unwrap(),
    )
    .unwrap();
    tx.commit().unwrap();
    let mut changed = handoff;
    changed["s"]["receipt"]["recover_ns"] = json!("101");
    let tx = c.transaction().unwrap();
    assert!(cfg
        .rebind_in_transaction(
            &tx,
            1,
            &RebindInput::parse(canonical_json(&changed).as_bytes()).unwrap()
        )
        .unwrap_err()
        .starts_with("IdentityConflict"));
    drop(tx);
    let tx = c.transaction().unwrap();
    cfg.initialize_in_transaction(&tx, 1).unwrap();
    tx.commit().unwrap();
    assert_eq!(sealed, records());
    println!("same receipt retry and regular restart do not append; changed receipt conflicts");
}
