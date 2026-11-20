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

#[test]
fn authority_shutdown_write_tolerates_early_peer_close_and_rejects_empty_close() {
    let dir = tempfile::Builder::new()
        .prefix("i1407-")
        .tempdir_in("/tmp")
        .unwrap();
    let p: Profile = parse(profile(dir.path(), approved()));
    let c: ExactCommand = parse(command(approved()));
    let frame = authority_frame(&p, &p.e, 1, "QueryReleasedExact", &c, None).unwrap();
    let payload = json!({
        "protocol": AUTHORITY_WIRE,
        "session_id": p.session_id,
        "session_generation": p.session_generation,
        "authority_id": "E",
        "authority_epoch": "1",
        "command_id": "a",
        "command_hash": hash(&c),
        "command": c,
        "state": "ReleasedExact",
        "receipt_id": "E:a",
        "release_receipt_id": null,
        "commit_ns": 0
    });
    let signed = reply_envelope(
        &frame.envelope,
        payload,
        "e-schema/1",
        "session",
        "1",
        "e/replies",
        "e:session",
        "1",
    );

    // 对端先写完回复并关闭连接后，客户端半关闭在 BSD/macOS 上返回 ENOTCONN，
    // 但本端仍须读到缓冲区里的已签回复，而非误报 AuthorityUnavailable。
    let (mut client, mut server) = UnixStream::pair().unwrap();
    server
        .write_all(format!("{}\n", canonical_json(&signed)).as_bytes())
        .unwrap();
    drop(server);
    #[cfg(target_os = "macos")]
    assert_eq!(
        client
            .shutdown(std::net::Shutdown::Write)
            .unwrap_err()
            .kind(),
        std::io::ErrorKind::NotConnected
    );
    shutdown_request_write(&client).unwrap();
    let deadline = Instant::now() + Duration::from_secs(2);
    let got = read_frame(&mut client, p.max_frame_bytes, deadline, json_frame).unwrap();
    assert_eq!(got, signed);

    // 对端不等待客户端 EOF、读完换行即写回回复并关闭：端到端 authority() 须稳定成功。
    let socket = dir.path().join("e");
    let listener = UnixListener::bind(&socket).unwrap();
    let reply_bytes = format!("{}\n", canonical_json(&signed)).into_bytes();
    let fast_server = std::thread::spawn(move || {
        for _ in 0..8 {
            let (mut s, _) = listener.accept().unwrap();
            let mut line = String::new();
            BufReader::new(&s).read_line(&mut line).unwrap();
            s.write_all(&reply_bytes).unwrap();
            drop(s);
        }
        // 最后一轮不写任何字节即关闭：必须失败关闭。
        let (s, _) = listener.accept().unwrap();
        let mut line = String::new();
        BufReader::new(&s).read_line(&mut line).unwrap();
        drop(s);
    });
    for _ in 0..8 {
        let reply = authority(&p, &p.e, 1, "QueryReleasedExact", &c, None).unwrap();
        assert_eq!(reply.receipt_id, "E:a");
    }
    let empty_err = authority(&p, &p.e, 1, "QueryReleasedExact", &c, None).unwrap_err();
    assert!(
        empty_err.starts_with("SchemaUnsupported：只接收一个LF终止帧与请求EOF"),
        "{empty_err}"
    );
    fast_server.join().unwrap();
}
