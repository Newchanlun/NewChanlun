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
    let change = json!({"kind":"submit","order":{"command_id":"a","family_id":"f-a","chong_id":"a","revision":"1","side":"buy",
        "quantity":"5","kind":{"kind":"limit","price":"100"},"eligibility_ref":"S:a","projection_manifest":"p-a"}});
    let certificate = json!({"rd11_policy":"controlled-fixture-rd11","responsibility_refs":["r"],"structure_dependencies":["s"],
        "market_dependencies":["m"],"rule_revision":"rule","conditions":conditions});
    json!({"command_id":"a","logical_order_family":"f-a","first_quantity":"5","allocation_id":"alloc-a","session_id":"session",
        "session_generation":"1","x_id":"X","x_epoch":"1","symbol":"TEST","projection_kind":"per_leg",
        "model_ref":super::super::tests::model().model_ref(),"plan_hash":hash(&change),
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

#[test]
fn model_ref_must_match_loaded_model_content_not_just_name() {
    let d = dir("model-ref");
    let p: Profile = parse(profile(&d, approved()));
    let c: ExactCommand = parse(command(approved()));
    c.validate(&p, 1).unwrap();

    // Same model_id and revision, only maker fee numerator 1 -> 10: must be rejected by X.
    let mut altered = p.clone();
    altered.model.fee_profile.maker.numerator = 10;
    assert_eq!(altered.model.model_id, p.model.model_id);
    assert_eq!(altered.model.revision, p.model.revision);
    assert_ne!(altered.model.content_hash(), p.model.content_hash());
    let e = c.validate(&altered, 1).unwrap_err();
    assert_eq!(
        e,
        "IdentityConflict：精确命令获准模型身份与 X 实际装载模型内容不符"
    );

    // Mismatched revision or model_id also rejected.
    let mut bad_rev = c.clone();
    bad_rev.model_ref.revision = "oracle-2".into();
    assert!(bad_rev
        .validate(&p, 1)
        .unwrap_err()
        .starts_with("IdentityConflict：精确命令获准模型身份"));

    // Legacy command without model_ref cannot deserialize into active ExactCommand.
    let mut legacy = command(approved());
    legacy.as_object_mut().unwrap().remove("model_ref");
    let err = serde_json::from_value::<ExactCommand>(legacy)
        .unwrap_err()
        .to_string();
    assert!(err.contains("model_ref"), "{err}");
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
                "state":"ReleasedExact","receipt_id":"E:a","release_receipt_id":null,"commit_ns":"0"});
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

#[test]
fn command_accepts_only_ic13_integers_and_binds_first_quantity_and_allocation() {
    let p: Profile = parse(profile(&dir("exact-wire"), approved()));
    let original = command(approved());
    for path in [
        "/first_quantity",
        "/x_epoch",
        "/change/order/quantity",
        "/change/order/revision",
        "/change/order/kind/price",
    ] {
        for bad in [
            json!(5),
            json!("05"),
            json!("+5"),
            json!("9223372036854775808"),
        ] {
            let mut wire = original.clone();
            *wire.pointer_mut(path).unwrap() = bad;
            assert!(
                serde_json::from_value::<ExactCommand>(wire).is_err(),
                "{path}"
            );
        }
    }
    for field in ["first_quantity", "allocation_id"] {
        let mut wire = original.clone();
        wire.as_object_mut().unwrap().remove(field);
        assert!(
            serde_json::from_value::<ExactCommand>(wire).is_err(),
            "{field}"
        );
    }
    let mut unknown = original.clone();
    unknown["change"]["order"]["extra"] = json!("1");
    assert!(serde_json::from_value::<ExactCommand>(unknown).is_err());
    let mut c: ExactCommand = parse(original.clone());
    assert_eq!(serde_json::to_value(&c).unwrap(), original);
    c.first_quantity += 1;
    assert!(c
        .validate(&p, 1)
        .unwrap_err()
        .starts_with("IdentityConflict"));
    c.first_quantity -= 1;
    c.allocation_id.clear();
    assert!(c
        .validate(&p, 1)
        .unwrap_err()
        .starts_with("MissingDependency"));
}

/// #1407 C3：封存的 `/2` 库（无 `model_ref` 的 14 字段 C2 命令）仍可只读审计（`audit_archived_v2`），
/// 不可被 `/3` 续写；损坏 E 回执或混入未知字段时拒绝审计。
#[test]
fn frozen_v2_archive_is_audited_readonly_and_refused_for_reopen() {
    let d = dir("archive-v2");
    let p: Profile = parse(profile(&d, approved()));
    let mut conn = rusqlite::Connection::open_in_memory().unwrap();
    {
        let tx = conn.transaction().unwrap();
        initialize_in_transaction(&tx, &p, 1).unwrap();
        // 切回封存 /2 标记并写入一条合法的 14 字段 /2 命令（无 model_ref）。
        tx.execute(
            "UPDATE x_sim_meta SET v='x-execution-profile/2' WHERE k='exact_profile_revision'",
            [],
        )
        .unwrap();
        let mut cmd_v2 = command(approved());
        cmd_v2.as_object_mut().unwrap().remove("model_ref");
        let cmd_hash = sha256_hex(canonical_json(&cmd_v2).as_bytes());
        let release = json!({
            "protocol": AUTHORITY_WIRE,
            "session_id": p.session_id,
            "session_generation": p.session_generation,
            "authority_id": p.e.authority_id,
            "authority_epoch": p.e.authority_epoch,
            "command_id": "a",
            "command_hash": cmd_hash,
            "command": cmd_v2,
            "state": "ReleasedExact",
            "receipt_id": "E:a",
            "release_receipt_id": null,
            "commit_ns": "0",
        });
        let clock = json!({"received_ns": "0", "first_known_ns": "0", "commit_ns": "0"});
        tx.execute(
            "INSERT INTO x_exact_commands(id,command,release_receipt,release_evidence,accept_clock,state) VALUES('a',?,'E:a',?,?,'Accepted')",
            rusqlite::params![canonical_json(&cmd_v2), canonical_json(&release), canonical_json(&clock)],
        )
        .unwrap();
        tx.commit().unwrap();
    }
    // /3 现役运行路径拒绝重开封存 /2 库。
    let tx = conn.transaction().unwrap();
    let reopen_err = initialize_in_transaction(&tx, &p, 1).unwrap_err();
    assert!(
        reopen_err.starts_with("VersionUnsupported"),
        "expected VersionUnsupported, got {reopen_err}"
    );
    // 只读归档审计 /2 通过。
    audit_archived_v2(&tx, &p, 1).unwrap();
    // 损坏 E 回执哈希必须被 /2 审计拒绝。
    tx.execute(
        "UPDATE x_exact_commands SET release_evidence = json_set(release_evidence, '$.command_hash', 'wrong') WHERE id='a'",
        [],
    )
    .unwrap();
    let corrupt_err = audit_archived_v2(&tx, &p, 1).unwrap_err();
    assert!(
        corrupt_err.contains("权威回执未绑定原命令"),
        "unexpected error: {corrupt_err}"
    );
    tx.rollback().unwrap();
}

/// #1407 C3 R4/R5：按真正冻结的写者代际核档：
/// - `/2`（12 键/6 键 + 十进制文本时钟）强制 `claimed_ns == attempt_batch.bar.index`；
/// - 早期 `/1`（`18446a3d35`–`d1c46577b1`：11 键无 `conditions` + 3 键 `e`/`s` + 3 项冻结条件，允许当年墙钟 `claimed_ns`）
///   标明 `archive_layout="v1_early"` 与 `raw_claim_only_non_retroactive_v1`，绝不把旧墙钟标成已验证等于 bar；
/// - 后期 `/1`（`1f0a42bc20`–`b66b61a0b0`：12 键 + 6 键）恒写 `bar.index`，标明 `archive_layout="v1_late"`
///   并强制 `claimed_ns == attempt_batch.bar.index`（墙钟或篡改均拒）。
#[test]
fn archived_v2_claimed_ns_must_equal_attempt_bar_and_v1_splits_early_vs_late() {
    let d = dir("r5-claimed-ns-and-v1-split");
    let p: Profile = parse(profile(&d, approved()));

    let mut cmd_v2 = command(approved());
    cmd_v2.as_object_mut().unwrap().remove("model_ref");
    let cmd_v2_hash = sha256_hex(canonical_json(&cmd_v2).as_bytes());
    let release_v2 = json!({
        "protocol": AUTHORITY_WIRE,
        "session_id": p.session_id,
        "session_generation": p.session_generation,
        "authority_id": p.e.authority_id,
        "authority_epoch": p.e.authority_epoch,
        "command_id": "a",
        "command_hash": cmd_v2_hash,
        "command": cmd_v2,
        "state": "ReleasedExact",
        "receipt_id": "E:a",
        "release_receipt_id": null,
        "commit_ns": "0",
    });
    let s_reply_v2 = json!({
        "protocol": AUTHORITY_WIRE,
        "session_id": p.session_id,
        "session_generation": p.session_generation,
        "authority_id": p.s.authority_id,
        "authority_epoch": p.s.authority_epoch,
        "command_id": "a",
        "command_hash": cmd_v2_hash,
        "command": cmd_v2,
        "state": "ExecuteCommitted",
        "receipt_id": "S:a",
        "release_receipt_id": "E:a",
        "commit_ns": "0",
    });
    let pending_batch = Batch {
        request_id: "b0".into(),
        known_frontier_cut: "cut-0".into(),
        bar: crate::history_simulation::model::Bar {
            index: 0,
            open: 100,
            high: 105,
            low: 95,
            close: 100,
        },
        capacity: crate::history_simulation::model::Capacity::Input {
            reference: "cap-0".into(),
            buy: 100,
            sell: 100,
        },
        close_changes: vec![serde_json::from_value(json!({
            "kind": "submit",
            "order": {
                "command_id": "a",
                "family_id": "f-a",
                "chong_id": "a",
                "revision": 1,
                "side": "buy",
                "quantity": 5,
                "kind": {"kind": "limit", "price": 100},
                "eligibility_ref": "S:a",
                "projection_manifest": "p-a"
            }
        }))
        .unwrap()],
        scenario_busts: vec![],
    };
    let mut normalized_batch = pending_batch.clone();
    normalized_batch.normalize();
    let batch_raw = canonical_json(&serde_json::to_value(&normalized_batch).unwrap());

    // 1) /2 MayHaveCalled 合法对照 vs 篡改反例
    let db_v2 = d.join("v2-mhc.sqlite");
    let _ = std::fs::remove_file(&db_v2);
    {
        let mut conn = rusqlite::Connection::open(&db_v2).unwrap();
        let tx = conn.transaction().unwrap();
        tx.execute_batch("CREATE TABLE x_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);")
            .unwrap();
        for (k, v) in [
            ("profile_revision", "x-execution-profile/2"),
            ("profile_mode", "simulation"),
            ("history_simulation", "true"),
            ("writer_epoch", "1"),
        ] {
            tx.execute("INSERT INTO x_meta VALUES(?1,?2)", rusqlite::params![k, v])
                .unwrap();
        }
        initialize_in_transaction(&tx, &p, 1).unwrap();
        tx.execute(
            "UPDATE x_sim_meta SET v='x-execution-profile/2' WHERE k='exact_profile_revision'",
            [],
        )
        .unwrap();
        tx.execute(
            "INSERT INTO x_sim_meta VALUES('pending_batch',?1),('pending_epoch','1')",
            [&batch_raw],
        )
        .unwrap();
        let clock = json!({"received_ns": "0", "first_known_ns": "0", "commit_ns": "0"});
        let exec_ok = json!({"reply": s_reply_v2, "claimed_ns": "0"});
        tx.execute(
            "INSERT INTO x_exact_commands(id,command,release_receipt,state,attempt_batch,accept_clock,release_evidence,execute_evidence) VALUES('a',?,'E:a','MayHaveCalled',?,?,?,?)",
            rusqlite::params![
                canonical_json(&cmd_v2),
                batch_raw,
                canonical_json(&clock),
                canonical_json(&release_v2),
                canonical_json(&exec_ok)
            ],
        )
        .unwrap();
        tx.commit().unwrap();
    }

    let ok_hist = inspect_history(&db_v2).unwrap();
    assert_eq!(ok_hist["archive_layout"], "v2");
    assert_eq!(
        ok_hist["execute_evidence_claimed_ns_audit_policy"],
        "verified_equal_to_attempt_bar"
    );
    assert_eq!(
        ok_hist["condition_audit_policy"],
        "verified_current_condition_semantics_and_completeness"
    );
    assert_eq!(ok_hist["condition_audit_unproven"], json!([]));
    let ok_cmd = inspect_command(&db_v2, "a").unwrap();
    assert_eq!(ok_cmd["state"], "MayHaveCalled");
    assert_eq!(ok_cmd["archive_layout"], "v2");
    assert_eq!(ok_cmd["attempt_batch_bar_index"], 0);
    assert_eq!(
        ok_cmd["execute_evidence_claimed_ns_audit"],
        "verified_equal_to_attempt_bar"
    );
    assert_eq!(
        ok_cmd["condition_audit_policy"],
        "verified_current_condition_semantics_and_completeness"
    );
    assert_eq!(ok_cmd["condition_audit_unproven"], json!([]));

    {
        let conn = rusqlite::Connection::open(&db_v2).unwrap();
        let exec_bad = json!({"reply": s_reply_v2, "claimed_ns": "999"});
        conn.execute(
            "UPDATE x_exact_commands SET execute_evidence=?1 WHERE id='a'",
            [canonical_json(&exec_bad)],
        )
        .unwrap();
    }
    let bad_err = inspect_command(&db_v2, "a").unwrap_err();
    assert!(
        bad_err.starts_with(
            "IdentityConflict：持久S执行证据调用占有时刻(999)与占有批bar.index(0)不符"
        ),
        "unexpected error: {bad_err}"
    );

    // 2) 真实冻结早期 /1（11 键无 conditions + 3 键 E/S + 3 项冻结条件 + 墙钟 claimed_ns）
    let early_conditions = json!([
        {
            "condition_id": "cond-release",
            "authority_revision": "released-exact/1",
            "validator_capability": "released-exact/1",
            "required_check_stages": ["E.ReleaseExact"],
            "dependency_set": ["e:1"],
            "evidence_refs": ["ev:e"],
            "invalidation_sources": ["inv:e"],
            "coverage_proof": "cov:e",
            "failure_result": "Denied"
        },
        {
            "condition_id": "cond-exec",
            "authority_revision": "execute-committed/1",
            "validator_capability": "execute-committed/1",
            "required_check_stages": ["S.RequestConditionalExecution"],
            "dependency_set": ["s:1"],
            "evidence_refs": ["ev:s"],
            "invalidation_sources": ["inv:s"],
            "coverage_proof": "cov:s",
            "failure_result": "Denied"
        },
        {
            "condition_id": "cond-x",
            "authority_revision": "simulation-local-transaction/1",
            "validator_capability": "simulation-local-transaction/1",
            "required_check_stages": ["X.OwnAttemptAndCall"],
            "dependency_set": ["x:1"],
            "evidence_refs": ["ev:x"],
            "invalidation_sources": ["inv:x"],
            "coverage_proof": "cov:x",
            "failure_result": "Denied"
        }
    ]);
    let early_profile = json!({
        "model": serde_json::to_value(&p.model).unwrap(),
        "session_id": p.session_id,
        "session_generation": p.session_generation,
        "x_id": p.x_id,
        "source_namespace": p.source_namespace,
        "source_epoch": p.source_epoch,
        "socket": p.socket,
        "e": {
            "socket": p.e.socket,
            "authority_id": p.e.authority_id,
            "authority_epoch": p.e.authority_epoch,
        },
        "s": {
            "socket": p.s.socket,
            "authority_id": p.s.authority_id,
            "authority_epoch": p.s.authority_epoch,
        },
        "timeout_ms": p.timeout_ms,
        "max_frame_bytes": p.max_frame_bytes,
    });
    let change_v1 = json!({
        "kind": "submit",
        "order": {
            "command_id": "a",
            "family_id": "f-a",
            "chong_id": "a",
            "revision": 1,
            "side": "buy",
            "quantity": 5,
            "kind": {"kind": "limit", "price": 100},
            "eligibility_ref": "S:a",
            "projection_manifest": "p-a"
        }
    });
    let cert_early = json!({
        "rd11_policy": "controlled-fixture-rd11",
        "responsibility_refs": ["r"],
        "structure_dependencies": ["s"],
        "market_dependencies": ["m"],
        "rule_revision": "rule",
        "conditions": early_conditions
    });
    let cmd_early = json!({
        "command_id": "a",
        "logical_order_family": "f-a",
        "session_id": p.session_id,
        "session_generation": p.session_generation,
        "x_id": p.x_id,
        "x_epoch": 1,
        "symbol": "TEST",
        "projection_kind": "per_leg",
        "change": change_v1,
        "certificate": cert_early,
        "plan_hash": hash(&change_v1),
        "certificate_hash": hash(&cert_early),
    });
    let cmd_early_hash = sha256_hex(canonical_json(&cmd_early).as_bytes());
    let release_early = json!({
        "protocol": AUTHORITY_WIRE,
        "session_id": p.session_id,
        "session_generation": p.session_generation,
        "authority_id": p.e.authority_id,
        "authority_epoch": p.e.authority_epoch,
        "command_id": "a",
        "command_hash": cmd_early_hash,
        "command": cmd_early,
        "state": "ReleasedExact",
        "receipt_id": "E:a",
        "release_receipt_id": null,
        "commit_ns": 100,
    });
    let s_reply_early = json!({
        "protocol": AUTHORITY_WIRE,
        "session_id": p.session_id,
        "session_generation": p.session_generation,
        "authority_id": p.s.authority_id,
        "authority_epoch": p.s.authority_epoch,
        "command_id": "a",
        "command_hash": cmd_early_hash,
        "command": cmd_early,
        "state": "ExecuteCommitted",
        "receipt_id": "S:a",
        "release_receipt_id": "E:a",
        "commit_ns": 100,
    });
    let db_v1_early = d.join("v1-early-wallclock.sqlite");
    let _ = std::fs::remove_file(&db_v1_early);
    {
        let mut conn = rusqlite::Connection::open(&db_v1_early).unwrap();
        let tx = conn.transaction().unwrap();
        tx.execute_batch("CREATE TABLE x_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);")
            .unwrap();
        for (k, v) in [
            ("profile_revision", "x-execution-profile/1"),
            ("profile_mode", "simulation"),
            ("history_simulation", "true"),
            ("writer_epoch", "1"),
        ] {
            tx.execute("INSERT INTO x_meta VALUES(?1,?2)", rusqlite::params![k, v])
                .unwrap();
        }
        initialize_in_transaction(&tx, &p, 1).unwrap();
        tx.execute(
            "DELETE FROM x_sim_meta WHERE k='exact_profile_revision'",
            [],
        )
        .unwrap();
        tx.execute(
            "UPDATE x_sim_meta SET v=?1 WHERE k='authority_profile'",
            [canonical_json(&early_profile)],
        )
        .unwrap();
        tx.execute(
            "INSERT INTO x_sim_meta VALUES('pending_batch',?1),('pending_epoch','1')",
            [&batch_raw],
        )
        .unwrap();
        let clock = json!({
            "received_ns": 1795111790971528899i64,
            "first_known_ns": 1795111790972359201i64,
            "commit_ns": 1795111790972359285i64
        });
        let exec_wall = json!({"reply": s_reply_early, "claimed_ns": 1795111790994769493i64});
        tx.execute(
            "INSERT INTO x_exact_commands(id,command,release_receipt,state,attempt_batch,accept_clock,release_evidence,execute_evidence) VALUES('a',?,'E:a','MayHaveCalled',?,?,?,?)",
            rusqlite::params![
                canonical_json(&cmd_early),
                batch_raw,
                canonical_json(&clock),
                canonical_json(&release_early),
                canonical_json(&exec_wall)
            ],
        )
        .unwrap();
        tx.commit().unwrap();
    }
    let early_hist = inspect_history(&db_v1_early).unwrap();
    assert_eq!(early_hist["profile_revision"], "x-execution-profile/1");
    assert_eq!(early_hist["archive_layout"], "v1_early");
    assert_eq!(
        early_hist["execute_evidence_claimed_ns_audit_policy"],
        "raw_claim_only_non_retroactive_v1"
    );
    assert_eq!(
        early_hist["condition_audit_policy"],
        "v1_early_frozen_three_conditions"
    );
    assert_eq!(
        early_hist["condition_audit_unproven"],
        json!([
            "model_coverage_condition_1f0a42bc20",
            "condition_semantics_pairing_table_2ed00abd6c",
            "required_four_capabilities_completeness_b66b61a0b0"
        ])
    );
    let early_cmd = inspect_command(&db_v1_early, "a").unwrap();
    assert_eq!(early_cmd["state"], "MayHaveCalled");
    assert_eq!(early_cmd["archive_layout"], "v1_early");
    assert_eq!(
        early_cmd["execute_evidence"]["claimed_ns"],
        1795111790994769493i64
    );
    assert_eq!(
        early_cmd["execute_evidence_claimed_ns_audit"],
        "raw_claim_only_non_retroactive_v1"
    );
    assert_eq!(
        early_cmd["condition_audit_policy"],
        "v1_early_frozen_three_conditions"
    );
    assert_eq!(
        early_cmd["condition_audit_unproven"],
        early_hist["condition_audit_unproven"]
    );
    // 早期 /1 坏档：claimed_ns < S.commit_ns(100) 必须拒绝。
    {
        let conn = rusqlite::Connection::open(&db_v1_early).unwrap();
        let exec_lt = json!({"reply": s_reply_early, "claimed_ns": 99});
        conn.execute(
            "UPDATE x_exact_commands SET execute_evidence=?1 WHERE id='a'",
            [canonical_json(&exec_lt)],
        )
        .unwrap();
    }
    let early_lt_err = inspect_command(&db_v1_early, "a").unwrap_err();
    assert!(
        early_lt_err.starts_with("IdentityConflict"),
        "unexpected error: {early_lt_err}"
    );
    // 早期 /1 坏档：即使重算哈希，塞入非当年冻结 3 项条件清单（如 4 项条件）也必须拒绝。
    {
        let cert_4 = json!({
            "rd11_policy": "controlled-fixture-rd11",
            "responsibility_refs": ["r"],
            "structure_dependencies": ["s"],
            "market_dependencies": ["m"],
            "rule_revision": "rule",
            "conditions": approved()
        });
        let cmd_4 = json!({
            "command_id": "a",
            "logical_order_family": "f-a",
            "session_id": p.session_id,
            "session_generation": p.session_generation,
            "x_id": p.x_id,
            "x_epoch": 1,
            "symbol": "TEST",
            "projection_kind": "per_leg",
            "change": change_v1,
            "certificate": cert_4,
            "plan_hash": hash(&change_v1),
            "certificate_hash": hash(&cert_4),
        });
        let cmd_4_hash = sha256_hex(canonical_json(&cmd_4).as_bytes());
        let rel_4 = json!({
            "protocol": AUTHORITY_WIRE,
            "session_id": p.session_id,
            "session_generation": p.session_generation,
            "authority_id": p.e.authority_id,
            "authority_epoch": p.e.authority_epoch,
            "command_id": "a",
            "command_hash": cmd_4_hash,
            "command": cmd_4,
            "state": "ReleasedExact",
            "receipt_id": "E:a",
            "release_receipt_id": null,
            "commit_ns": 100,
        });
        let s_4 = json!({
            "protocol": AUTHORITY_WIRE,
            "session_id": p.session_id,
            "session_generation": p.session_generation,
            "authority_id": p.s.authority_id,
            "authority_epoch": p.s.authority_epoch,
            "command_id": "a",
            "command_hash": cmd_4_hash,
            "command": cmd_4,
            "state": "ExecuteCommitted",
            "receipt_id": "S:a",
            "release_receipt_id": "E:a",
            "commit_ns": 100,
        });
        let exec_4 = json!({"reply": s_4, "claimed_ns": 1795111790994769493i64});
        let conn = rusqlite::Connection::open(&db_v1_early).unwrap();
        conn.execute(
            "UPDATE x_exact_commands SET command=?1, release_evidence=?2, execute_evidence=?3 WHERE id='a'",
            rusqlite::params![
                canonical_json(&cmd_4),
                canonical_json(&rel_4),
                canonical_json(&exec_4),
            ],
        )
        .unwrap();
    }
    let early_4cond_err = inspect_command(&db_v1_early, "a").unwrap_err();
    assert!(
        early_4cond_err.starts_with("Unsupported"),
        "unexpected error: {early_4cond_err}"
    );

    // 3) 真实冻结后期 /1（12 键含 conditions + 6 键 E/S）：claimed_ns == bar.index 通过，墙钟/篡改必拒。
    let cert_late = json!({
        "rd11_policy": "controlled-fixture-rd11",
        "responsibility_refs": ["r"],
        "structure_dependencies": ["s"],
        "market_dependencies": ["m"],
        "rule_revision": "rule",
        "conditions": approved()
    });
    let cmd_late = json!({
        "command_id": "a",
        "logical_order_family": "f-a",
        "session_id": p.session_id,
        "session_generation": p.session_generation,
        "x_id": p.x_id,
        "x_epoch": 1,
        "symbol": "TEST",
        "projection_kind": "per_leg",
        "change": change_v1,
        "certificate": cert_late,
        "plan_hash": hash(&change_v1),
        "certificate_hash": hash(&cert_late),
    });
    let cmd_late_hash = sha256_hex(canonical_json(&cmd_late).as_bytes());
    let release_late = json!({
        "protocol": AUTHORITY_WIRE,
        "session_id": p.session_id,
        "session_generation": p.session_generation,
        "authority_id": p.e.authority_id,
        "authority_epoch": p.e.authority_epoch,
        "command_id": "a",
        "command_hash": cmd_late_hash,
        "command": cmd_late,
        "state": "ReleasedExact",
        "receipt_id": "E:a",
        "release_receipt_id": null,
        "commit_ns": 0,
    });
    let s_reply_late = json!({
        "protocol": AUTHORITY_WIRE,
        "session_id": p.session_id,
        "session_generation": p.session_generation,
        "authority_id": p.s.authority_id,
        "authority_epoch": p.s.authority_epoch,
        "command_id": "a",
        "command_hash": cmd_late_hash,
        "command": cmd_late,
        "state": "ExecuteCommitted",
        "receipt_id": "S:a",
        "release_receipt_id": "E:a",
        "commit_ns": 0,
    });
    let db_v1_late = d.join("v1-late.sqlite");
    let _ = std::fs::remove_file(&db_v1_late);
    {
        let mut conn = rusqlite::Connection::open(&db_v1_late).unwrap();
        let tx = conn.transaction().unwrap();
        tx.execute_batch("CREATE TABLE x_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);")
            .unwrap();
        for (k, v) in [
            ("profile_revision", "x-execution-profile/1"),
            ("profile_mode", "simulation"),
            ("history_simulation", "true"),
            ("writer_epoch", "1"),
        ] {
            tx.execute("INSERT INTO x_meta VALUES(?1,?2)", rusqlite::params![k, v])
                .unwrap();
        }
        initialize_in_transaction(&tx, &p, 1).unwrap();
        tx.execute(
            "DELETE FROM x_sim_meta WHERE k='exact_profile_revision'",
            [],
        )
        .unwrap();
        tx.execute(
            "INSERT INTO x_sim_meta VALUES('pending_batch',?1),('pending_epoch','1')",
            [&batch_raw],
        )
        .unwrap();
        let clock = json!({"received_ns": 0, "first_known_ns": 0, "commit_ns": 0});
        let exec_ok = json!({"reply": s_reply_late, "claimed_ns": 0});
        tx.execute(
            "INSERT INTO x_exact_commands(id,command,release_receipt,state,attempt_batch,accept_clock,release_evidence,execute_evidence) VALUES('a',?,'E:a','MayHaveCalled',?,?,?,?)",
            rusqlite::params![
                canonical_json(&cmd_late),
                batch_raw,
                canonical_json(&clock),
                canonical_json(&release_late),
                canonical_json(&exec_ok)
            ],
        )
        .unwrap();
        tx.commit().unwrap();
    }
    let late_hist = inspect_history(&db_v1_late).unwrap();
    assert_eq!(late_hist["archive_layout"], "v1_late");
    assert_eq!(
        late_hist["execute_evidence_claimed_ns_audit_policy"],
        "verified_equal_to_attempt_bar"
    );
    assert_eq!(
        late_hist["condition_audit_policy"],
        "v1_late_common_12_6_invariants_only"
    );
    assert_eq!(
        late_hist["condition_audit_unproven"],
        json!([
            "condition_semantics_pairing_table_2ed00abd6c",
            "required_four_capabilities_completeness_b66b61a0b0"
        ])
    );
    let late_cmd = inspect_command(&db_v1_late, "a").unwrap();
    assert_eq!(late_cmd["archive_layout"], "v1_late");
    assert_eq!(
        late_cmd["execute_evidence_claimed_ns_audit"],
        "verified_equal_to_attempt_bar"
    );
    assert_eq!(
        late_cmd["condition_audit_policy"],
        "v1_late_common_12_6_invariants_only"
    );
    assert_eq!(
        late_cmd["condition_audit_unproven"],
        late_hist["condition_audit_unproven"]
    );
    // 后期 /1 不允许墙钟或篡改 claimed_ns（不能借早期 /1 通道放行）。
    {
        let conn = rusqlite::Connection::open(&db_v1_late).unwrap();
        let exec_wall = json!({"reply": s_reply_late, "claimed_ns": 1700000000000000000i64});
        conn.execute(
            "UPDATE x_exact_commands SET execute_evidence=?1 WHERE id='a'",
            [canonical_json(&exec_wall)],
        )
        .unwrap();
    }
    let late_bad = inspect_command(&db_v1_late, "a").unwrap_err();
    assert!(
        late_bad.starts_with(
            "IdentityConflict：持久S执行证据调用占有时刻(1700000000000000000)与占有批bar.index(0)不符"
        ),
        "unexpected error: {late_bad}"
    );
}

/// #1407 C3 R5 反降格回归：严禁将损坏的后期 `/1`、混合/非对称键集、或 `/2`/`/3` 降格成早期 `/1`。
#[test]
fn archived_profile_classification_refuses_downgrade_and_hybrid_layouts() {
    let d = dir("r5-anti-downgrade");
    let p: Profile = parse(profile(&d, approved()));
    let late_val = serde_json::to_value(&p).unwrap();

    let early_val = json!({
        "model": serde_json::to_value(&p.model).unwrap(),
        "session_id": p.session_id,
        "session_generation": p.session_generation,
        "x_id": p.x_id,
        "source_namespace": p.source_namespace,
        "source_epoch": p.source_epoch,
        "socket": p.socket,
        "e": {
            "socket": p.e.socket,
            "authority_id": p.e.authority_id,
            "authority_epoch": p.e.authority_epoch,
        },
        "s": {
            "socket": p.s.socket,
            "authority_id": p.s.authority_id,
            "authority_epoch": p.s.authority_epoch,
        },
        "timeout_ms": p.timeout_ms,
        "max_frame_bytes": p.max_frame_bytes,
    });

    let write_db = |name: &str, rev: &str, inner_rev: Option<&str>, prof: &Value| {
        let path = d.join(format!("{name}.sqlite"));
        let _ = std::fs::remove_file(&path);
        let mut conn = rusqlite::Connection::open(&path).unwrap();
        let tx = conn.transaction().unwrap();
        tx.execute_batch("CREATE TABLE x_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);")
            .unwrap();
        for (k, v) in [
            ("profile_revision", rev),
            ("profile_mode", "simulation"),
            ("history_simulation", "true"),
            ("writer_epoch", "1"),
        ] {
            tx.execute("INSERT INTO x_meta VALUES(?1,?2)", rusqlite::params![k, v])
                .unwrap();
        }
        initialize_in_transaction(&tx, &p, 1).unwrap();
        match inner_rev {
            Some(v) => {
                tx.execute(
                    "UPDATE x_sim_meta SET v=?1 WHERE k='exact_profile_revision'",
                    [v],
                )
                .unwrap();
            }
            None => {
                tx.execute(
                    "DELETE FROM x_sim_meta WHERE k='exact_profile_revision'",
                    [],
                )
                .unwrap();
            }
        }
        tx.execute(
            "UPDATE x_sim_meta SET v=?1 WHERE k='authority_profile'",
            [canonical_json(prof)],
        )
        .unwrap();
        tx.commit().unwrap();
        path
    };

    // 1) 损坏后期 /1：有 conditions（12 键），但 e 缺失 schema_revision（5 键）→ 拒（绝不降格）
    let mut late_missing_schema = late_val.clone();
    late_missing_schema["e"]
        .as_object_mut()
        .unwrap()
        .remove("schema_revision");
    let err = inspect_history(&write_db(
        "late-missing-schema",
        "x-execution-profile/1",
        None,
        &late_missing_schema,
    ))
    .unwrap_err();
    assert!(err.starts_with("InvalidDomain"), "unexpected: {err}");

    // 2) 混合布局：有 conditions（12 键）但 e/s 为早期 3 键 → 拒
    let mut mixed_12_with_3 = early_val.clone();
    mixed_12_with_3
        .as_object_mut()
        .unwrap()
        .insert("conditions".into(), late_val["conditions"].clone());
    let err = inspect_history(&write_db(
        "mixed-12-with-3",
        "x-execution-profile/1",
        None,
        &mixed_12_with_3,
    ))
    .unwrap_err();
    assert!(err.starts_with("InvalidDomain"), "unexpected: {err}");

    // 3) 混合布局：无 conditions（11 键）但 e/s 为后期 6 键 → 拒
    let mut mixed_11_with_6 = late_val.clone();
    mixed_11_with_6
        .as_object_mut()
        .unwrap()
        .remove("conditions");
    let err = inspect_history(&write_db(
        "mixed-11-with-6",
        "x-execution-profile/1",
        None,
        &mixed_11_with_6,
    ))
    .unwrap_err();
    assert!(err.starts_with("InvalidDomain"), "unexpected: {err}");

    // 4) 非对称：无 conditions（11 键），e 为 6 键、s 为 3 键 → 拒
    let mut asym = early_val.clone();
    asym["e"] = late_val["e"].clone();
    let err = inspect_history(&write_db(
        "asym-e6-s3",
        "x-execution-profile/1",
        None,
        &asym,
    ))
    .unwrap_err();
    assert!(err.starts_with("InvalidDomain"), "unexpected: {err}");

    // 5) 早期 /1 多出未知键 → 拒
    let mut early_extra = early_val.clone();
    early_extra
        .as_object_mut()
        .unwrap()
        .insert("extra".into(), json!(1));
    let err = inspect_history(&write_db(
        "early-extra-key",
        "x-execution-profile/1",
        None,
        &early_extra,
    ))
    .unwrap_err();
    assert!(err.starts_with("InvalidDomain"), "unexpected: {err}");

    // 6) 后期 /1 schema_revision 为空字符串 → 拒（绝不降格）
    let mut late_empty_schema = late_val.clone();
    late_empty_schema["e"]["schema_revision"] = json!("");
    let err = inspect_history(&write_db(
        "late-empty-schema",
        "x-execution-profile/1",
        None,
        &late_empty_schema,
    ))
    .unwrap_err();
    assert!(err.starts_with("InvalidDomain"), "unexpected: {err}");

    // 7) /2 与 /3 塞入早期 11+3 profile → 严格按 Profile 拒绝，绝不降格
    for rev in ["x-execution-profile/2", "x-execution-profile/3"] {
        let err = inspect_history(&write_db(
            &format!("downgrade-{}", rev.rsplit('/').next().unwrap()),
            rev,
            Some(rev),
            &early_val,
        ))
        .unwrap_err();
        assert!(
            err.starts_with("InvalidDomain") && err.contains("missing field"),
            "unexpected for {rev}: {err}"
        );
    }

    // 8) 早期 /1 混装内层 exact_profile_revision → VersionUnsupported
    let err = inspect_history(&write_db(
        "early-with-inner-rev",
        "x-execution-profile/1",
        Some("x-execution-profile/3"),
        &early_val,
    ))
    .unwrap_err();
    assert!(err.starts_with("VersionUnsupported"), "unexpected: {err}");
}

/// #1407 C3 R6 回归：区分 12+6+6 存储布局与条件准入世代。
/// - 后期 `/1` 历史正式库 `1f0a42bc20`（旧 E 配对 `released-exact-probe/1`）与 `2ed00abd6c`（仅 `model_coverage`、尚未要求四项齐全）
///   按 12+6+6 共同可证语义可读，且显式标明 `condition_audit_policy` 与 `condition_audit_unproven`；
/// - 后期 `/1` 的逻辑 bar、X 能力、E.ReleaseExact `model_coverage`、九字段非空、`condition_id` 唯一、命令/档案逐项相等均不削弱；
/// - `/2` 与 `/3` 维持完整语义配对表与四项完备闸，同样反例在 `/2`、`/3` 上必拒。
#[test]
fn late_v1_archive_audits_common_12_6_invariants_without_retroactive_gates() {
    let d = dir("r6-late-v1-generations");
    let p: Profile = parse(profile(&d, approved()));
    let base_profile = serde_json::to_value(&p).unwrap();
    let change_v1 = json!({
        "kind": "submit",
        "order": {
            "command_id": "a",
            "family_id": "f-a",
            "chong_id": "a",
            "revision": 1,
            "side": "buy",
            "quantity": 5,
            "kind": {"kind": "limit", "price": 100},
            "eligibility_ref": "S:a",
            "projection_manifest": "p-a"
        }
    });
    let mut attempt_batch = Batch {
        request_id: "b0".into(),
        known_frontier_cut: "cut-0".into(),
        bar: crate::history_simulation::model::Bar {
            index: 0,
            open: 100,
            high: 105,
            low: 95,
            close: 100,
        },
        capacity: crate::history_simulation::model::Capacity::Input {
            reference: "cap-0".into(),
            buy: 100,
            sell: 100,
        },
        close_changes: vec![serde_json::from_value(change_v1.clone()).unwrap()],
        scenario_busts: vec![],
    };
    attempt_batch.normalize();
    let batch_raw = canonical_json(&serde_json::to_value(&attempt_batch).unwrap());

    let cond = |id: &str, auth: &str, stage: &str, cap: &str, fail: &str| {
        json!({
            "condition_id": id,
            "authority_revision": auth,
            "dependency_set": ["dep"],
            "invalidation_sources": ["inv"],
            "required_check_stages": [stage],
            "evidence_refs": ["ref"],
            "coverage_proof": "proof",
            "validator_capability": cap,
            "failure_result": fail,
        })
    };

    // 1f0a42bc20 世代：允许自定义旧 E 能力配对（released-exact-probe/1），但带 model_coverage 且 X 能力有效。
    let conds_1f0a = json!([
        cond(
            "model_coverage",
            "released-exact-probe/1",
            "E.ReleaseExact",
            "released-exact-probe/1",
            "Denied"
        ),
        cond(
            "s_exec",
            "execute-committed/1",
            "S.RequestConditionalExecution",
            "execute-committed/1",
            "Denied"
        ),
        cond(
            "x_local",
            "simulation-local-transaction/1",
            "X.OwnAttemptAndCall",
            "simulation-local-transaction/1",
            "Denied"
        ),
    ]);

    // 2ed00abd6c 世代：每项满足配对表，但尚未要求四项必备能力齐全（仅 model_coverage）。
    let conds_2ed0 = json!([cond(
        "model_coverage",
        "model-coverage/1",
        "E.ReleaseExact",
        "model-coverage/1",
        "Denied"
    )]);

    let write_late_v1 = |name: &str, profile_conds: &Value, cmd_conds: &Value, claimed_ns: i64| {
        let path = d.join(format!("{name}.sqlite"));
        let _ = std::fs::remove_file(&path);
        let mut prof = base_profile.clone();
        prof["conditions"] = profile_conds.clone();
        let cert = json!({
            "rd11_policy": "controlled-fixture-rd11",
            "responsibility_refs": ["r"],
            "structure_dependencies": ["s"],
            "market_dependencies": ["m"],
            "rule_revision": "rule",
            "conditions": cmd_conds,
        });
        let cmd = json!({
            "command_id": "a",
            "logical_order_family": "f-a",
            "session_id": p.session_id,
            "session_generation": p.session_generation,
            "x_id": p.x_id,
            "x_epoch": 1,
            "symbol": "TEST",
            "projection_kind": "per_leg",
            "change": change_v1,
            "certificate": cert,
            "plan_hash": hash(&change_v1),
            "certificate_hash": hash(&cert),
        });
        let cmd_hash = sha256_hex(canonical_json(&cmd).as_bytes());
        let rel = json!({
            "protocol": AUTHORITY_WIRE,
            "session_id": p.session_id,
            "session_generation": p.session_generation,
            "authority_id": p.e.authority_id,
            "authority_epoch": p.e.authority_epoch,
            "command_id": "a",
            "command_hash": cmd_hash,
            "command": cmd,
            "state": "ReleasedExact",
            "receipt_id": "E:a",
            "release_receipt_id": null,
            "commit_ns": 0,
        });
        let s_reply = json!({
            "protocol": AUTHORITY_WIRE,
            "session_id": p.session_id,
            "session_generation": p.session_generation,
            "authority_id": p.s.authority_id,
            "authority_epoch": p.s.authority_epoch,
            "command_id": "a",
            "command_hash": cmd_hash,
            "command": cmd,
            "state": "ExecuteCommitted",
            "receipt_id": "S:a",
            "release_receipt_id": "E:a",
            "commit_ns": 0,
        });
        let mut conn = rusqlite::Connection::open(&path).unwrap();
        let tx = conn.transaction().unwrap();
        tx.execute_batch("CREATE TABLE x_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);")
            .unwrap();
        for (k, v) in [
            ("profile_revision", "x-execution-profile/1"),
            ("profile_mode", "simulation"),
            ("history_simulation", "true"),
            ("writer_epoch", "1"),
        ] {
            tx.execute("INSERT INTO x_meta VALUES(?1,?2)", rusqlite::params![k, v])
                .unwrap();
        }
        initialize_in_transaction(&tx, &p, 1).unwrap();
        tx.execute(
            "DELETE FROM x_sim_meta WHERE k='exact_profile_revision'",
            [],
        )
        .unwrap();
        tx.execute(
            "UPDATE x_sim_meta SET v=?1 WHERE k='authority_profile'",
            [canonical_json(&prof)],
        )
        .unwrap();
        tx.execute(
            "INSERT INTO x_sim_meta VALUES('pending_batch',?1),('pending_epoch','1')",
            [&batch_raw],
        )
        .unwrap();
        let clock = json!({"received_ns": 0, "first_known_ns": 0, "commit_ns": 0});
        let exec = json!({"reply": s_reply, "claimed_ns": claimed_ns});
        tx.execute(
            "INSERT INTO x_exact_commands(id,command,release_receipt,state,attempt_batch,accept_clock,release_evidence,execute_evidence) VALUES('a',?,'E:a','MayHaveCalled',?,?,?,?)",
            rusqlite::params![
                canonical_json(&cmd),
                batch_raw,
                canonical_json(&clock),
                canonical_json(&rel),
                canonical_json(&exec),
            ],
        )
        .unwrap();
        tx.commit().unwrap();
        path
    };

    let expected_unproven = json!([
        "condition_semantics_pairing_table_2ed00abd6c",
        "required_four_capabilities_completeness_b66b61a0b0"
    ]);

    // 1) 1f0a42bc20 旧配对库可读，且显式标明未证项与逻辑 bar 已核证。
    let db_1f0a = write_late_v1("late-1f0a-legacy-pair", &conds_1f0a, &conds_1f0a, 0);
    let h_1f0a = inspect_history(&db_1f0a).unwrap();
    assert_eq!(h_1f0a["archive_layout"], "v1_late");
    assert_eq!(
        h_1f0a["execute_evidence_claimed_ns_audit_policy"],
        "verified_equal_to_attempt_bar"
    );
    assert_eq!(
        h_1f0a["condition_audit_policy"],
        "v1_late_common_12_6_invariants_only"
    );
    assert_eq!(h_1f0a["condition_audit_unproven"], expected_unproven);
    let c_1f0a = inspect_command(&db_1f0a, "a").unwrap();
    assert_eq!(c_1f0a["state"], "MayHaveCalled");
    assert_eq!(
        c_1f0a["condition_audit_policy"],
        "v1_late_common_12_6_invariants_only"
    );
    assert_eq!(c_1f0a["condition_audit_unproven"], expected_unproven);
    // 1f0a42bc20 库篡改逻辑 bar 仍必拒（不削弱晚 /1 逻辑 bar）。
    let db_1f0a_bad_bar = write_late_v1("late-1f0a-bad-bar", &conds_1f0a, &conds_1f0a, 7);
    let err = inspect_command(&db_1f0a_bad_bar, "a").unwrap_err();
    assert!(err.starts_with("IdentityConflict"), "unexpected: {err}");

    // 2) 2ed00abd6c 缺四项完备（仅 model_coverage）库可读，且显式标明未证项。
    let db_2ed0 = write_late_v1("late-2ed0-incomplete", &conds_2ed0, &conds_2ed0, 0);
    let h_2ed0 = inspect_history(&db_2ed0).unwrap();
    assert_eq!(h_2ed0["archive_layout"], "v1_late");
    assert_eq!(
        h_2ed0["condition_audit_policy"],
        "v1_late_common_12_6_invariants_only"
    );
    assert_eq!(h_2ed0["condition_audit_unproven"], expected_unproven);
    let c_2ed0 = inspect_command(&db_2ed0, "a").unwrap();
    assert_eq!(c_2ed0["state"], "MayHaveCalled");
    assert_eq!(c_2ed0["condition_audit_unproven"], expected_unproven);

    // 3) 后期 /1 共同不变量负控仍必拒：
    // 3a) X.* 阶段未支持能力 → Unsupported
    let bad_x_cap = json!([
        cond(
            "model_coverage",
            "model-coverage/1",
            "E.ReleaseExact",
            "model-coverage/1",
            "Denied"
        ),
        cond(
            "x_bad",
            "venue-call/1",
            "X.OwnAttemptAndCall",
            "venue-call/1",
            "Denied"
        ),
    ]);
    let err =
        inspect_history(&write_late_v1("late-bad-x-cap", &bad_x_cap, &bad_x_cap, 0)).unwrap_err();
    assert!(err.starts_with("Unsupported"), "unexpected: {err}");

    // 3b) 缺 E.ReleaseExact 阶段的 model_coverage → MissingDependency
    let no_cov = json!([cond(
        "x_local",
        "simulation-local-transaction/1",
        "X.OwnAttemptAndCall",
        "simulation-local-transaction/1",
        "Denied"
    )]);
    let err = inspect_history(&write_late_v1("late-no-coverage", &no_cov, &no_cov, 0)).unwrap_err();
    assert!(err.starts_with("MissingDependency"), "unexpected: {err}");

    // 3c) 重复 condition_id → Unsupported
    let dup_id = json!([
        cond(
            "model_coverage",
            "model-coverage/1",
            "E.ReleaseExact",
            "model-coverage/1",
            "Denied"
        ),
        cond(
            "model_coverage",
            "released-exact/1",
            "E.ReleaseExact",
            "released-exact/1",
            "Denied"
        ),
    ]);
    let err = inspect_history(&write_late_v1("late-dup-id", &dup_id, &dup_id, 0)).unwrap_err();
    assert!(err.starts_with("Unsupported"), "unexpected: {err}");

    // 3d) 命令条件清单与档案 profile 不逐项相等 → Unsupported
    let err = inspect_command(
        &write_late_v1("late-cond-mismatch", &conds_1f0a, &conds_2ed0, 0),
        "a",
    )
    .unwrap_err();
    assert!(err.starts_with("Unsupported"), "unexpected: {err}");

    // 4) /2 与 /3 严禁削弱：塞入 1f0a42bc20 旧配对或 2ed00abd6c 缺四项清单必拒，合法 /3 报告空未证列表。
    for rev in ["x-execution-profile/2", "x-execution-profile/3"] {
        let tag = rev.rsplit('/').next().unwrap();
        let write_strict = |suffix: &str, conds: &Value| {
            let path = d.join(format!("strict-v{tag}-{suffix}.sqlite"));
            let _ = std::fs::remove_file(&path);
            let mut prof = serde_json::to_value(&p).unwrap();
            prof["conditions"] = conds.clone();
            let mut conn = rusqlite::Connection::open(&path).unwrap();
            let tx = conn.transaction().unwrap();
            tx.execute_batch("CREATE TABLE x_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);")
                .unwrap();
            for (k, v) in [
                ("profile_revision", rev),
                ("profile_mode", "simulation"),
                ("history_simulation", "true"),
                ("writer_epoch", "1"),
            ] {
                tx.execute("INSERT INTO x_meta VALUES(?1,?2)", rusqlite::params![k, v])
                    .unwrap();
            }
            initialize_in_transaction(&tx, &p, 1).unwrap();
            tx.execute(
                "UPDATE x_sim_meta SET v=?1 WHERE k='exact_profile_revision'",
                [rev],
            )
            .unwrap();
            tx.execute(
                "UPDATE x_sim_meta SET v=?1 WHERE k='authority_profile'",
                [canonical_json(&prof)],
            )
            .unwrap();
            tx.commit().unwrap();
            path
        };

        let err_legacy = inspect_history(&write_strict("legacy-pair", &conds_1f0a)).unwrap_err();
        assert!(
            err_legacy.starts_with("Unsupported"),
            "rev={rev} unexpected: {err_legacy}"
        );
        let err_incomplete = inspect_history(&write_strict("incomplete", &conds_2ed0)).unwrap_err();
        assert!(
            err_incomplete.starts_with("MissingDependency"),
            "rev={rev} unexpected: {err_incomplete}"
        );
        let ok = inspect_history(&write_strict("ok", &approved())).unwrap();
        assert_eq!(
            ok["condition_audit_policy"],
            "verified_current_condition_semantics_and_completeness"
        );
        assert_eq!(ok["condition_audit_unproven"], json!([]));
    }
}
