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
