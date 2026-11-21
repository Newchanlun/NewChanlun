//! #2127：正式 launcher → 真 E/B/X 独占进程。S 的精确授权与 FIN basis 明示为受控源，
//! X 原始成交和费用从真 X 捕获；独立 TestOnly 归属源显式提供现有 B 合同所需经济分量。
use super::*;
use newchan_rust::session_protocol::{canonical_json, reply_envelope, validate_envelope};
use rusqlite::types::ValueRef;
use std::io::{BufRead, BufReader};
use std::os::unix::{fs::MetadataExt, net::UnixListener};

const S_SCHEMA: &str = "s-authority-fixture/1";
const S_RESP: &str = "s-authority-fixture/replies";
const S_PRODUCER: &str = "S:fixture";
const SESSION_ID: &str = "tb2127";
const BIND: &str = "voice-alpha";
const FIN_POLICY: &str = "TestOnly-2127-cap";
const RELEASE_NS: i64 = 122;
const SIG: &str = "TestOnly-synthetic-signature/#2127";

fn digest(value: &Value) -> String {
    sha256_hex(canonical_json(value).as_bytes())
}
fn save(path: &Path, value: &Value) -> String {
    let raw = canonical_json(value);
    std::fs::write(path, &raw).unwrap();
    sha256_hex(raw.as_bytes())
}
fn read(path: &Path) -> Value {
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}
fn exchange(path: &Path, value: &Value) -> Value {
    let mut socket = UnixStream::connect(path).unwrap();
    let timeout = Some(Duration::from_secs(10));
    socket.set_read_timeout(timeout).unwrap();
    socket.set_write_timeout(timeout).unwrap();
    writeln!(socket, "{}", canonical_json(value)).unwrap();
    socket.shutdown(std::net::Shutdown::Write).unwrap();
    let mut raw = String::new();
    socket.read_to_string(&mut raw).unwrap();
    serde_json::from_str(&raw).unwrap_or_else(|e| panic!("{path:?}: {e}: {raw}"))
}
fn econ_frame(source: &str, producer: &str, id: &str, payload: Value) -> Value {
    json!({"schema_revision":"economic-session/1","session_id":SESSION_ID,"session_generation":"1",
        "source_namespace":source,"source_epoch":"one","producer_id":producer,"producer_epoch":"1",
        "message_id":id,"payload_hash":digest(&payload),"payload":payload,"causal_refs":[]})
}
fn econ(space: &Space, owner: &str, id: &str, payload: Value) -> Value {
    exchange(
        &space.path(owner),
        &econ_frame("test", "fixture", id, payload),
    )["payload"]
        .clone()
}
fn expect(v: Value, kind: &str) -> Value {
    assert_eq!(v["kind"], kind, "{v}");
    v
}
fn error(v: Value, class: &str) {
    expect(v.clone(), "Error");
    assert!(v["error"].as_str().unwrap().starts_with(class), "{v}");
}
fn captures(doc: &Value, pointer: &str, token: &str) -> Value {
    json!({"op":"CaptureExternal","raw_utf8":canonical_json(doc),"json_pointer":pointer,
        "token":token,"source_event_time":doc.pointer(pointer).unwrap()["source"]["source_event_time"]})
}
fn apply(space: &Space, msg: &str, fact: &Value, allocation: &Value) -> Value {
    expect(
        econ(
            space,
            "b.sock",
            msg,
            json!({"op":"ApplyAllocation","fact_key":fact["fact_key"],
        "expected_fact_hash":fact["fact_hash"],"allocation_id":allocation}),
        ),
        "Applied",
    )
}
fn x(space: &Space, op: &str, payload: Value) -> Value {
    exchange(
        &space.path("x.sock"),
        &json!({"protocol":"x-exact-simulation/1","op":op,"payload":payload}),
    )
}
fn bar(index: i64, changes: Vec<Value>, capacity: Value) -> Value {
    json!({"request_id":format!("bar-{index}"),"known_frontier_cut":format!("cut-{index}"),
        "bar":{"index":index,"open":14,"low":13,"high":15,"close":14},"capacity":capacity,
        "close_changes":changes,"scenario_busts":[]})
}
fn conditions() -> Vec<Value> {
    [
        ("released-exact/1", "released-exact/1", "E.ReleaseExact"),
        ("execute-committed/1", "execute-committed/1", "S.RequestConditionalExecution"),
        ("simulation-local-transaction/1", "simulation-local-transaction/1", "X.OwnAttemptAndCall"),
        ("model_coverage", "model-coverage/1", "E.ReleaseExact"),
    ].map(|(id, cap, stage)| json!({"condition_id":id,"authority_revision":cap,"dependency_set":["controlled-dependency"],
        "invalidation_sources":["controlled-invalidation"],"required_check_stages":[stage],"evidence_refs":["controlled-evidence"],
        "coverage_proof":"controlled-coverage","validator_capability":cap,"failure_result":"Denied"})).into()
}

fn opening() -> Value {
    json!({"format":"neutral TestOnly economic raw originals; not production transport wire",
        "units":{"quantity":{"unit":"TEST-UNIT","quantum":"1"},"money":{"unit":"TEST-CASH","currency":"TEST-CASH","quantum":"1"},"numeric_encoding":"exact_decimal_integer_text"},
        "events":[{"event":"known-opening","source":{"source_namespace":"test","source_epoch":"one","source_cursor":"1","external_fact_id":"opening-alpha","received_time":"1","claimed_origin":"TestOnly source","source_event_time":null},
            "allocation_id":"opening-alpha","family_id":"family-alpha","book_identity":{"chong_id":"alpha","symbol":"alpha","op_level":"2","fixed_q":"12","side":"long"},
            "stable_point":{"profile":"TestOnly","seq":"1","source_ref":"sp"},
            "observed_existing_book":{"units":"4","Pi":"900","A":"200","W":"100","witness_refs":{"units":"u","Pi":"p","A":"a","W":"w"}},
            "known_cost_components":[{"kind":"acquisition_cash","amount_text":"56","canonical_amount":"56","source_ref":"cash","currency":"TEST-CASH","quantum":"1"}]}],
        "evidence_index":{"fragments":{"sp":[{"json_pointer":"/events/0/stable_point"}],"u":[{"json_pointer":"/events/0/observed_existing_book/units"}],
            "p":[{"json_pointer":"/events/0/observed_existing_book/Pi"}],"a":[{"json_pointer":"/events/0/observed_existing_book/A"}],
            "w":[{"json_pointer":"/events/0/observed_existing_book/W"}],"cash":[{"json_pointer":"/events/0/known_cost_components/0"}]}}})
}

struct Input {
    opening: Value,
    binding: Value,
    plan: Value,
    finance: Value,
    caps: Vec<(&'static str, Value, String)>,
    voice_archive: Value,
}

fn signed(cap: &str) -> Value {
    json!({"schema_revision":"funding-cap-policy-record/1","kind":"TestOnly","profile_id":"TestOnly-2127",
        "policy_id":FIN_POLICY,"version":"2","supersedes":"1","cap":cap,"currency":"TEST-CASH","money_unit":"TEST-CASH",
        "valid_through_ns":"100000","authorizer":"TestOnly controlled signer","authorized_at_ns":"1","signature_ref":SIG})
}

fn x_producer(split: bool) -> &'static str {
    if split {
        "X:sim-p4"
    } else {
        "X"
    }
}

fn inputs(space: &Space, s_db: &Path, split: bool) -> Input {
    let x_id = x_producer(split);
    let voice_dir = space.path("voice");
    let caps_dir = space.path("caps");
    std::fs::create_dir_all(&voice_dir).unwrap();
    std::fs::create_dir_all(&caps_dir).unwrap();
    let opening = opening();
    let fact = &opening["events"][0];
    let fact_key = digest(&json!(["test", "one", "opening-alpha"]));
    let opening_sha = digest(&opening);
    let fact_hash = digest(
        &json!({"raw_sha256":opening_sha,"json_pointer":"/events/0","event":fact,"units":opening["units"]}),
    );
    let reference = |id: &str| json!({"authority_id":"fixture","object_id":id,"revision":"0","content_hash":digest(&json!(id))});
    let binding = json!({"op":"BindVoice","binding_id":BIND,"evidence_id":"opening","carrier_ref":reference("carrier"),
        "gamma_ref":reference("gamma"),"parent_voice_id":null,"sigma":"Long","n":"0",
        "opening_basis":{"fact_key":fact_key,"expected_fact_hash":fact_hash,"allocation_id":fact["allocation_id"]}});
    let opening_source = json!({"fact_key":fact_key,"fact_hash":fact_hash,"allocation_id":fact["allocation_id"],
        "raw_sha256":opening_sha,"json_pointer":"/events/0","quantity":"4","units":opening["units"]});
    let mut artifacts = Vec::new();
    let mut locations = Vec::new();
    let mut archive = serde_json::Map::new();
    for role in [
        "input",
        "controlled_gammas",
        "carrier_objects",
        "instrument_declaration",
        "opening_raw",
    ] {
        let value = if role == "opening_raw" {
            opening.clone()
        } else {
            json!({"fixture_role":role})
        };
        let path = voice_dir.join(format!("{role}.json"));
        let sha = save(&path, &value);
        let size = std::fs::metadata(&path).unwrap().len().to_string();
        let mut item = json!({"name":role,"bytes":size,"sha256":sha});
        if !split {
            item["path"] = json!(path);
        }
        locations.push(json!({"name":role,"sha256":sha,"path":path}));
        artifacts.push(item);
        archive.insert(
            sha,
            json!(space.path("voice-archive").join(path.file_name().unwrap())),
        );
    }
    let ver = if split { 2 } else { 1 };
    let bundle = json!({"schema":format!("voice-binding-authority/{ver}"),"authority_id":"fixture",
        "source":{"instrument":"alpha","input_sha256":artifacts[0]["sha256"],"profile_id":"unit","first_confirming_observation_source":"1",
            "clock_mapping":{"kind":"TestOnlyAffineOrdinalToNs","source_origin":"0","nanosecond_origin":"0","nanoseconds_per_ordinal":"1"}},
        "artifacts":artifacts,"bindings":[{"evidence_id":"opening","instrument":"alpha","chong_id":"alpha","operation_level":"2",
            "carrier_ref":binding["carrier_ref"],"gamma_ref":binding["gamma_ref"],"parent_voice_id":null,"sigma":"Long","n":"0",
            "structure_view":{"profile_id":"unit","execution_level":"2","confirmation_level":"3","nest_depth":"1"},"opening_source":opening_source}]});
    let bundle_path = voice_dir.join("bundle.json");
    let bundle_sha = save(&bundle_path, &bundle);
    let review_path = voice_dir.join("review.json");
    let mut review = json!({"schema":format!("voice-binding-independent-verification/{ver}"),
        "authority_id":"fixture","bundle_sha256":bundle_sha,"artifacts":artifacts,"verified_evidence_ids":["opening"],
        "verdict":"APPROVE_CONTROLLED_VOICE_BINDING"});
    if !split {
        review["scope"] = json!("TestOnly controlled evidence closure");
    }
    let review_sha = save(&review_path, &review);
    let mut authority = json!({"authority_id":"fixture","bundle_sha256":bundle_sha,"verification_sha256":review_sha,"max_bytes":"1048576"});
    if !split {
        authority["bundle_path"] = json!(bundle_path);
        authority["verification_path"] = json!(review_path);
    }

    let basis_object =
        json!({"object_id":"unit-S-object","kind":"UnitStructuralTrustRoot","branch":"RISING"});
    let s_ref = json!({"object_id":"unit-S-object","object_hash":digest(&basis_object),"profile_id":"unit"});
    let basis = json!({"kind":"FinancialBasis","session_id":SESSION_ID,"session_generation":"1","writer_epoch":"1",
        "pending_revision":false,"commit_ns":"1","snapshot":{"profile_id":"unit","objects":[basis_object]}});
    let s_binary = space.path("financial-basis.sh");
    let script = format!(
        "#!/bin/sh\ncat <<'FIXTURE'\n{}\nFIXTURE\n",
        canonical_json(&basis)
    );
    std::fs::write(&s_binary, &script).unwrap();
    std::fs::set_permissions(&s_binary, std::fs::Permissions::from_mode(0o700)).unwrap();
    let plan = json!({"decision_id":"alpha","attempt_id":"attempt-alpha","plan_id":"plan-alpha","owner":"B:alpha","voice_binding_id":BIND,
        "right_id":"alpha","expected_book_version":"2","expected_rights_version":"1","applicant_epoch":"1","applicant_generation":"1",
        "slot_id":"slot","quantity":"2","limit_price":"14","fee_tail":"2","quantity_source":"TestOnly-quantity",
        "price_source":"TestOnly-price","fee_source":"TestOnly-fee","s_ref":s_ref,
        "o_ref":{"operation_id":"operation-alpha","kind":"TestOnlyCashBuy","source_ref":"TestOnly-operation","s_object_id":"unit-S-object","quantity":"2"},
        "exact":{"command_id":"cmd-alpha","logical_order_family":"family-alpha","chong_id":"alpha","revision":"1","first_quantity":"2",
            "allocation_id":"alloc-alpha","side":"buy","symbol":"alpha","projection_manifest":"TestOnly-projection/alpha",
            "eligibility_ref":"S:cmd-alpha","concurrency":"single"}});
    let domain = |concurrency| json!({"order_kind":"limit","concurrency":concurrency,"allocation_model":"#1349/atomic-slot-wait/v1"});
    let fin_rev = if split {
        "tb03b-finance/7"
    } else {
        "tb03b-finance/5"
    };
    let mut finance = json!({"schema_revision":fin_rev,"kind":"TestOnly","source_id":"fixture","source_epoch":"1",
        "policy":{"policy_id":FIN_POLICY,"allocation_policy_id":"#1349/atomic-slot-wait/v1","cap":"100","currency":"TEST-CASH",
            "money_unit":"TEST-CASH","quantity_unit":"TEST-UNIT","quantum":"1","capability_id":"TestOnly-no-venue",
            "model":"TestOnlyUnleveragedCashBuy","valid_through_ns":"100000"},
        "baseline":{"responsibility_id":"opening-liability","amount":"20","source_ref":"TestOnly-existing-full-liability",
            "covered_facts":[{"fact_key":fact_key,"fact_hash":fact_hash,"token":"opening-token"}]},
        "rights":[{"right_id":"alpha","owner":"B:alpha","version":"1","amount":"40","currency":"TEST-CASH","source_ref":"TestOnly-privately-owned-cash"}],
        "plans":[plan],"slots":[{"slot_id":"slot","applicants":["alpha"],"input_end":{"kind":"ControlledInputEnd",
            "source_id":"fixture","source_epoch":"1","watermark":"1","complete_request_hash":digest(&json!(["alpha"]))}}],
        "exact_release":{"x_target":{"x_id":x_id,"x_epoch":"1"},"projection_kind":"per_leg","rd11_policy":"controlled-fixture-rd11",
            "rule_revision":"TestOnly-rule/2127","market_dependencies":["TestOnly-market/2127"],"conditions":conditions(),
            "model_coverage":{"model_ref":{"model_id":"history-sim/bar-batch-known-frontier/1","revision":"oracle-1",
            "content_hash":digest(&json!("history-sim/bar-batch-known-frontier/1@oracle-1"))},"domain_id":"TestOnly-domain/2127",
            "input_domain":[domain("single")],"unsupported_domains":[domain("batched")]}}});
    if split {
        finance["policy"]["profile_id"] = json!("TestOnly-2127");
    }
    let fin_path = space.path("fin.json");
    let fin_sha = save(&fin_path, &finance);
    let source = json!({"source_namespace":"test","source_epoch":"one","producer_id":"fixture","producer_epoch":"1"});
    let mut fin = json!({"schema_revision":fin_rev,"input_sha256":fin_sha,"coordinator_source":source,
        "structure":{"session_id":SESSION_ID,"session_generation":"1","writer_epoch":"1","binary_sha256":sha256_hex(script.as_bytes())}});
    if !split {
        fin["input_path"] = json!(fin_path);
        fin["structure"]["binary"] = json!(s_binary);
        fin["structure"]["db"] = json!(s_db);
    }
    let mut cap_paths = serde_json::Map::new();
    let mut caps = Vec::new();
    if split {
        let mut cross = signed("120");
        cross["profile_id"] = json!("TestOnly-other-profile");
        let mut unit = signed("120");
        unit["money_unit"] = json!("OTHER-CASH");
        let mut signature = signed("120");
        signature["signature_ref"] = json!("/fixture/local-reference");
        let mut unsigned = signed("120");
        unsigned["authorizer"] = json!("");
        let mut early = signed("120");
        early["authorized_at_ns"] = json!("99999");
        let local_references = [
            (
                "cap-file-upper",
                format!("FILE://{}", caps_dir.join("cap.json").display()),
            ),
            (
                "cap-file-lower",
                format!("file://{}", caps_dir.join("cap.json").display()),
            ),
            (
                "cap-file-mixed",
                format!("FiLe://{}", caps_dir.join("cap.json").display()),
            ),
            ("cap-relative", "caps/cap.json".to_owned()),
            ("cap-parent", "../caps/cap.json".to_owned()),
            ("cap-windows", r"C:\caps\cap.json".to_owned()),
            ("cap-unc", r"\\host\caps\cap.json".to_owned()),
            (
                "cap-namespace-path",
                "TestOnly-synthetic-signature/#2127/cap.json".to_owned(),
            ),
        ];
        for (id, record) in [
            ("cap-low", signed("19")),
            ("cap-cross", cross),
            ("cap-unit", unit),
            ("cap-local-signature", signature),
            ("cap-no-signer", unsigned),
            ("cap-late-signature", early),
            ("cap-missing", signed("121")),
            ("cap-replaced", signed("122")),
        ]
        .into_iter()
        .chain(local_references.map(|(id, reference)| {
            let mut record = signed("120");
            record["signature_ref"] = json!(reference);
            (id, record)
        }))
        .chain([("cap", signed("120"))])
        {
            let path = caps_dir.join(format!("{id}.json"));
            let hash = digest(&record);
            if id != "cap-missing" {
                save(
                    &path,
                    if id == "cap-replaced" {
                        &Value::Null
                    } else {
                        &record
                    },
                );
            }
            cap_paths.insert(hash.clone(), json!(path));
            caps.push((id, record, hash));
        }
    }
    let mut rights = source;
    rights["operations"] = json!([
        "CaptureExternal",
        "ResolveEvidence",
        "ApplyAllocation",
        "BindVoice",
        "ReadView",
        "ImportResponsibility",
        "PrepareDecision",
        "Reserve",
        "CommitDecision",
        "ActivateCapPolicy",
        "MakeDispatchable",
        "ReleaseExact"
    ]);
    let clock = |ns: i64| json!({"received_ns":ns.to_string(),"first_known_ns":(ns+1).to_string(),"commit_ns":(ns+2).to_string()});
    let clocks = [
        ("open", 10),
        ("apply-open", 20),
        ("bind", 30),
        ("import", 40),
        ("prepare", 50),
        ("cap", 60),
        ("reserve", 80),
        ("commit", 90),
        ("dispatch", 100),
        ("release", 120),
        ("x-fill", 130),
        ("x-fee", 140),
        ("capture-attribution", 150),
        ("apply-fill", 170),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_owned(), clock(v)))
    .chain(
        caps.iter()
            .filter(|(id, _, _)| *id != "cap")
            .map(|(id, _, _)| ((*id).to_owned(), clock(60))),
    )
    .collect::<serde_json::Map<_, _>>();
    let x_model = json!({"model_id":"history-sim/bar-batch-known-frontier/1","revision":"oracle-1","symbol":"alpha","quantity_unit":"TEST-UNIT",
        "currency":"TEST-CASH","tick_value":1,"rd11_policy":"controlled-fixture-rd11","rd12_policy":"per-leg-source-attribution/1",
        "projection_kind":"per_leg","seed":"none","fee_profile":{"reference":"controlled-fee/1","role_source":"controlled-role-map/1",
            "limit_role":"maker","market_role":"taker","maker":{"numerator":1,"denominator":100,"rounding":"ceiling"},
            "taker":{"numerator":2,"denominator":100,"rounding":"ceiling"},"market_slippage_ticks":1,"market_slippage_source":"controlled-oracle/1"}});
    let e = json!({"db":space.path("e.db"),"socket":space.path("e.sock")});
    let b = json!({"db":space.path("b.db"),"socket":space.path("b.sock")});
    let xdb = space.path("x.db");
    let x_binding = json!({"source_namespace":"x-sim","source_epoch":"one","producer_id":x_id,"producer_epoch":"1","model_content_hash":digest(&x_model)});
    let mut business = json!({"schema_revision":format!("economic-manifest/{ver}"),"protocol_revision":"economic-session/1",
        "session_id":SESSION_ID,"session_generation":"1","book_revision":"tb03c-book/1",
        "chongs":[{"chong_id":"alpha","symbol":"alpha","operation_level":"2","fixed_q":"12"}],
        "authorized_sources":[rights,{"source_namespace":"x-sim","source_epoch":"one","producer_id":x_id,"producer_epoch":"1",
            "operations":["QueryReleasedExact","CaptureExternal"]}],
        "resources":{"max_frame_bytes":"16777216","read_timeout_ms":"2000","write_timeout_ms":"2000","response_timeout_ms":"30000","queue_capacity":"4","max_connections":"4"},
        "clock":{"kind":"TestOnly","plan":{"init_ns":"1","recover_ns":["1000"],"messages":clocks}},
        "voice_binding":{"schema_revision":format!("voice-binding/{ver}"),"authorities":[authority]},"finance":fin,
        "history_simulation_source":x_binding});
    let mut x_profile = json!({"model":x_model,"session_id":SESSION_ID,"session_generation":"1","x_id":x_id,
        "source_namespace":"x-sim","source_epoch":"one",
        "e":{"authority_id":"E","authority_epoch":"1","schema_revision":"economic-session/1","reply_namespace":"economic-session/replies","producer_id":format!("E:{SESSION_ID}")},
        "s":{"authority_id":"S","authority_epoch":"1","schema_revision":S_SCHEMA,"reply_namespace":S_RESP,"producer_id":S_PRODUCER},
        "conditions":conditions(),"timeout_ms":5000,"max_frame_bytes":1048576});
    let x_local = json!({"schema_revision":"x-simulation-deployment/1","db":xdb,"socket":space.path("x.sock"),
        "e_socket":e["socket"],"s_socket":space.path("condition.sock")});
    let economic = if split {
        x_profile["schema_revision"] = json!("x-simulation-authority/2");
        x_profile = json!({"business":x_profile,"deployment":x_local});
        json!({"schema_revision":"economic-session-config/2","business":business,
            "deployment":{"schema_revision":"economic-deployment/1","domains":{"E":e,"B:alpha":b},
                "voice":{"fixture":{"bundle":bundle_path,"verification":review_path,"artifacts":locations}},
                "finance":{"input":fin_path,"s":{"binary":s_binary,"db":s_db},"cap_records":cap_paths},"fault_markers":[],"x_db":xdb}})
    } else {
        x_profile["socket"] = x_local["socket"].clone();
        x_profile["e"]["socket"] = x_local["e_socket"].clone();
        x_profile["s"]["socket"] = x_local["s_socket"].clone();
        business["e"] = e;
        business["chongs"][0]["db"] = b["db"].clone();
        business["chongs"][0]["socket"] = b["socket"].clone();
        business["history_simulation_source"]["x_db"] = json!(xdb);
        business
    };
    save(&space.path("economic.json"), &economic);
    save(
        &space.path("x-profile.json"),
        &json!({"profile_revision":"x-execution-profile/1","mode":"simulation",
        "credential_scope":{"env":"UNUSED_SIMULATION_CREDENTIAL"},"history_simulation":x_profile}),
    );
    Input {
        opening,
        binding,
        plan,
        finance,
        caps,
        voice_archive: json!({"schema_revision":"voice-archive-index/1","objects":archive}),
    }
}

fn cap_payload(record: &Value, digest: &str) -> Value {
    json!({"op":"ActivateCapPolicy","activation_id":format!("activation-{digest}"),"policy_id":record["policy_id"],
        "from_version":record["supersedes"],"to_version":record["version"],"cap":record["cap"],
        "valid_through_ns":record["valid_through_ns"],"policy_record":{"sha256":digest},"writer_epoch":"1"})
}

struct Service(Child);
impl Drop for Service {
    fn drop(&mut self) {
        if self.0.try_wait().ok().flatten().is_none() {
            let _ = stop(&mut self.0);
        }
    }
}
fn controlled_s(path: &Path, epoch: &'static str) -> std::thread::JoinHandle<()> {
    let listener = UnixListener::bind(path).unwrap();
    std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut line = String::new();
        BufReader::new(&stream).read_line(&mut line).unwrap();
        let env = validate_envelope(serde_json::from_str(&line).unwrap(), S_SCHEMA).unwrap();
        let request = &env["payload"];
        assert_eq!(request["op"], "RequestConditionalExecution");
        assert_eq!(request["authority_epoch"], epoch);
        let mut response = request.clone();
        response.as_object_mut().unwrap().remove("op");
        response["state"] = json!("ExecuteCommitted");
        response["receipt_id"] = json!("S:cmd-alpha");
        response["commit_ns"] = json!(RELEASE_NS);
        let reply = reply_envelope(
            &env, response, S_SCHEMA, SESSION_ID, "1", S_RESP, S_PRODUCER, epoch,
        );
        writeln!(stream, "{}", canonical_json(&reply)).unwrap();
    })
}

fn image(db: &Path) -> Value {
    let c = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
    let raw: String = c
        .query_row(
            "SELECT image FROM commits ORDER BY seq DESC LIMIT 1",
            [],
            |r| r.get(0),
        )
        .unwrap();
    serde_json::from_str(&raw).unwrap()
}
fn table_bytes(db: &Path, local_table: &str) -> (String, Option<String>) {
    let c = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
    let tables = c
        .prepare("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name")
        .unwrap()
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    let mut business = serde_json::Map::new();
    let mut deployment = None;
    for (table, schema) in tables {
        assert!(table
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_'));
        let mut stmt = c
            .prepare(&format!("SELECT * FROM \"{table}\" ORDER BY 1"))
            .unwrap();
        let n = stmt.column_count();
        let rows = stmt
            .query_map([], |r| {
                (0..n)
                    .map(|i| {
                        Ok(match r.get_ref(i)? {
                            ValueRef::Null => json!(["null"]),
                            ValueRef::Integer(v) => json!(["int", v]),
                            ValueRef::Real(v) => json!(["real", v.to_bits().to_string()]),
                            ValueRef::Text(v) => json!(["text", std::str::from_utf8(v).unwrap()]),
                            ValueRef::Blob(v) => json!(["blob", v]),
                        })
                    })
                    .collect::<rusqlite::Result<Vec<_>>>()
            })
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        let table_content = json!({"schema":schema,"count":rows.len(),"rows":rows});
        if table == local_table {
            deployment = Some(canonical_json(&table_content));
        } else {
            business.insert(table, table_content);
        }
    }
    (canonical_json(&Value::Object(business)), deployment)
}

fn audit_domain(db: &Path, manifest: &Path, b: bool, extra: &[&str]) -> Output {
    run(domain_command("audit", db, manifest, b).args(extra))
}
fn domain_command(action: &str, db: &Path, manifest: &Path, b: bool) -> Command {
    command_for_chong(action, db, manifest, b.then_some("alpha"))
}

fn command_for_chong(action: &str, db: &Path, manifest: &Path, chong: Option<&str>) -> Command {
    let exe = if chong.is_some() {
        env!("CARGO_BIN_EXE_b_chong_session")
    } else {
        env!("CARGO_BIN_EXE_e_economic_session")
    };
    let mut command = Command::new(exe);
    command
        .arg(action)
        .arg("--manifest")
        .arg(manifest)
        .arg("--db")
        .arg(db);
    if let Some(chong) = chong {
        command.args(["--chong", chong]);
    }
    command
}
fn successful_json(out: Output) -> Value {
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}

fn workload(
    space: &Space,
    split: bool,
    neg: bool,
    recovery: Option<RecoveryArm>,
) -> [(String, Option<String>); 3] {
    let declared = declaration("TestOnlyStructure", DECLARED_NS);
    let sdb = s_init_v3(space, Some(&declared));
    let limits = anchor(&sdb);
    let launcher = launcher_manifest(
        space,
        "simulation",
        &declared,
        &sdb,
        &limits,
        &space.path("x-profile.json"),
    );
    let mut control = read(&launcher);
    control["economic"]["b"][0]["chong"] = json!("alpha");
    save(&launcher, &control);
    let f = inputs(space, &sdb, split);
    let ec_manifest = space.path("economic.json");
    let edb = space.path("e.db");
    let bdb = space.path("b.db");
    let xdb = space.path("x.db");
    if neg {
        let manifest = read(&ec_manifest);
        for (field, replacement) in [
            ("/business/schema_revision", json!("economic-manifest/999")),
            (
                "/deployment/schema_revision",
                json!("economic-deployment/999"),
            ),
            (
                "/business/finance/schema_revision",
                json!("tb03b-finance/3"),
            ),
            (
                "/business/voice_binding/schema_revision",
                json!("voice-binding/1"),
            ),
        ] {
            let mut mixed = manifest.clone();
            *mixed.pointer_mut(field).unwrap() = replacement;
            let path = space.path("mixed.json");
            save(&path, &mixed);
            let out = run(Command::new(env!("CARGO_BIN_EXE_e_economic_session"))
                .arg("init")
                .arg("--manifest")
                .arg(path)
                .arg("--db")
                .arg(&edb));
            assert!(!out.status.success());
            assert!(!edb.exists());
        }
    }
    let profile = space.path("x-profile.json");
    if recovery.is_some() {
        let mut configured = read(&profile);
        let manifest = read(&ec_manifest);
        let sim = &mut configured["history_simulation"];
        sim["business"]["recovery_identity"] = json!({
            "e_manifest_hash":digest(&manifest["business"]),"s_config":s_recovery_config(),
        });
        sim["deployment"]["recovery_domains"] = json!({
            "e_db":edb,"e_manifest":ec_manifest,"s_db":sdb,
        });
        save(&profile, &configured);
    }
    let s_epoch = if recovery == Some(RecoveryArm::Both) {
        "2"
    } else {
        "1"
    };
    let source = controlled_s(&space.path("condition.sock"), s_epoch);
    let mut launcher_service = None;
    let mut standalone = None;
    if recovery.is_some() {
        successful_json(run(&mut domain_command("init", &edb, &ec_manifest, false)));
        successful_json(run(&mut domain_command("init", &bdb, &ec_manifest, true)));
        standalone = Some((
            spawn_domain(&edb, &ec_manifest, false, "1", "1"),
            spawn_domain(&bdb, &ec_manifest, true, "1", "1"),
            start_owner(&mut serve_x(&xdb, &profile)),
        ));
    } else {
        let mut service = Service(spawn_launcher(&launcher));
        wait_domains(&mut service.0);
        launcher_service = Some(service);
    }
    for name in ["e.sock", "b.sock", "x.sock"] {
        eventually(name, || UnixStream::connect(space.path(name)).is_ok());
    }
    let captured = expect(
        econ(
            space,
            "e.sock",
            "open",
            captures(&f.opening, "/events/0", "opening-token"),
        ),
        "Recorded",
    );
    apply(space, "apply-open", &captured, &json!("opening-alpha"));
    if neg {
        let p = space.path("voice/carrier_objects.json");
        let absent = space.path("carrier-away.json");
        let before = table_bytes(&bdb, "deployment");
        std::fs::rename(&p, &absent).unwrap();
        error(
            econ(space, "b.sock", "bind", f.binding.clone()),
            "MissingDependency",
        );
        std::fs::write(&p, b"wrong").unwrap();
        error(
            econ(space, "b.sock", "bind", f.binding.clone()),
            "IdentityConflict",
        );
        std::fs::rename(absent, p).unwrap();
        let review = space.path("voice/review.json");
        let replaced = space.path("review-away.json");
        std::fs::rename(&review, &replaced).unwrap();
        std::fs::write(&review, b"wrong review").unwrap();
        error(
            econ(space, "b.sock", "bind", f.binding.clone()),
            "IdentityConflict",
        );
        std::fs::rename(replaced, review).unwrap();
        assert_eq!(table_bytes(&bdb, "deployment"), before);
    }
    let voice = expect(
        econ(space, "b.sock", "bind", f.binding.clone()),
        "VoiceBound",
    );
    if split {
        let committed = image(&bdb);
        let events = committed["history"].as_array().unwrap();
        let persisted = events.iter().find(|e| e["kind"] == "BindVoice").unwrap();
        assert_eq!(
            persisted["evidence_witness"]["artifacts_by_sha256"]
                .as_object()
                .unwrap()
                .len(),
            5
        );
    }
    let archive = space.path("voice-archive");
    std::fs::rename(space.path("voice"), &archive).unwrap();
    expect(
        econ(
            space,
            "e.sock",
            "import",
            json!({"op":"ImportResponsibility","writer_epoch":"1","responsibility_id":"opening-liability"}),
        ),
        "ResponsibilityImportedReceipt",
    );
    let prepare = json!({"op":"PrepareDecision","decision_id":"alpha","plan_hash":digest(&f.plan),"writer_epoch":"1"});
    expect(econ(space, "b.sock", "prepare", prepare), "PreparedReceipt");

    if neg {
        let before = table_bytes(&edb, "deployment");
        let cap = f.caps.last().unwrap();
        let valid = cap_payload(&cap.1, &cap.2);
        let mut old = valid.clone();
        old["policy_record"]["path"] = json!(space.path("caps/cap.json"));
        error(econ(space, "e.sock", "cap", old), "SchemaUnsupported");
        let mut mixed = valid.clone();
        mixed["policy_record"]["schema_revision"] = json!("tb03b-finance/3");
        error(econ(space, "e.sock", "cap", mixed), "SchemaUnsupported");
        let bad = cap_payload(&cap.1, &digest(&Value::Null));
        error(econ(space, "e.sock", "cap", bad), "MissingDependency");
        for (id, record, sha) in &f.caps[..f.caps.len() - 1] {
            let expected = match *id {
                "cap-cross" | "cap-unit" | "cap-replaced" => "IdentityConflict",
                "cap-low"
                | "cap-local-signature"
                | "cap-file-upper"
                | "cap-file-lower"
                | "cap-file-mixed"
                | "cap-relative"
                | "cap-parent"
                | "cap-windows"
                | "cap-unc"
                | "cap-namespace-path" => "InvalidDomain",
                "cap-no-signer" => "SchemaUnsupported",
                "cap-missing" | "cap-late-signature" => "MissingDependency",
                _ => unreachable!(),
            };
            let result = econ(space, "e.sock", id, cap_payload(record, sha));
            assert_eq!(result["kind"], "Error", "{id}: {result}");
            error(result, expected);
            assert_eq!(table_bytes(&edb, "deployment"), before, "{id}");
        }
    }
    if split {
        let (_, record, sha) = f.caps.last().unwrap();
        let payload = cap_payload(record, sha);
        let first = expect(
            econ(space, "e.sock", "cap", payload.clone()),
            "CapPolicyActivatedReceipt",
        );
        std::fs::rename(space.path("caps"), space.path("caps-archive")).unwrap();
        let before = table_bytes(&edb, "deployment");
        assert_eq!(first, econ(space, "e.sock", "cap", payload.clone()));
        let mut conflict = payload;
        conflict["cap"] = json!("121");
        error(econ(space, "e.sock", "cap", conflict), "IdentityConflict");
        assert_eq!(before, table_bytes(&edb, "deployment"));
        let cap_image = image(&edb);
        let event = cap_image["history"].as_array().unwrap().last().unwrap();
        assert_eq!(event["witness"]["cap_policy_raw"], canonical_json(record));
        assert_eq!(
            event["request"]["payload"]["policy_record"],
            json!({"sha256":sha})
        );
        assert_eq!(event["record"]["to"]["policy_record_sha256"], *sha);
    }

    let reserve = econ(
        space,
        "e.sock",
        "reserve",
        json!({"op":"Reserve","slot_id":"slot","writer_epoch":"1",
        "request_set_hash":digest(&f.finance["slots"][0]["applicants"])}),
    );
    assert_eq!(reserve["record"]["state"], "Reserved", "{reserve}");
    let grant = &reserve["record"]["grants"][0]["grant_id"];
    let commit = econ(
        space,
        "b.sock",
        "commit",
        json!({"op":"CommitDecision","decision_id":"alpha","plan_hash":digest(&f.plan),"grant_id":grant,"writer_epoch":"1"}),
    );
    assert_eq!(commit["record"]["state"], "Committed", "{commit}");
    expect(
        econ(
            space,
            "e.sock",
            "dispatch",
            json!({"op":"MakeDispatchable","decision_id":"alpha","plan_hash":digest(&f.plan),"writer_epoch":"1"}),
        ),
        "DispatchableReceipt",
    );
    let fin = &f.finance["exact_release"];
    let certificate = json!({"rd11_policy":fin["rd11_policy"],"responsibility_refs":[grant],
        "structure_dependencies":[format!("unit-S-object@{}",f.plan["s_ref"]["object_hash"].as_str().unwrap())],
        "market_dependencies":fin["market_dependencies"],"rule_revision":fin["rule_revision"],"conditions":fin["conditions"]});
    let submit = json!({"kind":"submit","order":{"command_id":"cmd-alpha","family_id":"family-alpha","chong_id":"alpha",
        "revision":1,"side":"buy","quantity":2,"kind":{"kind":"limit","price":14},"eligibility_ref":"S:cmd-alpha","projection_manifest":"TestOnly-projection/alpha"}});
    let release = expect(
        econ(
            space,
            "e.sock",
            "release",
            json!({"op":"ReleaseExact","decision_id":"alpha","command_id":"cmd-alpha",
        "plan_hash":digest(&submit),"certificate":certificate,"x_id":fin["x_target"]["x_id"],"x_epoch":"1","writer_epoch":"1"}),
        ),
        "ReleasedExactReceipt",
    );
    let command = &release["record"]["command"];
    for i in 0..RELEASE_NS {
        expect(
            x(space, "AdvanceBar", bar(i, vec![], json!({"kind":"none"}))),
            "SimulationBatch",
        );
    }
    if let Some(arm) = recovery {
        let (e_service, b_service, x_service) = standalone.as_mut().unwrap();
        let ebefore = business(&edb, "deployment");
        let bbefore = table_bytes(&bdb, "deployment");
        let original_profile = business(&xdb, "x_sim_deployment")["x_sim_meta"].clone();
        let manifest_bytes = std::fs::read(&ec_manifest).unwrap();
        stop_at(space, "e.sock", e_service);
        stop_at(space, "b.sock", b_service);
        let e_request = space.path("e-recovery.json");
        let manifest = read(&ec_manifest);
        save(
            &e_request,
            &json!({
                "schema_revision":"economic-recovery/1","domain_id":"E","recovery_id":"recovered-e",
                "session_id":SESSION_ID,"session_generation":"1","from_epoch":"1",
                "manifest_hash":digest(&manifest["business"]),"cut":release["cut"],
            }),
        );
        let recovery_call = |op| {
            successful_json(run(domain_command(op, &edb, &ec_manifest, false)
                .arg("--recovery-request")
                .arg(&e_request)))
        };
        let received = recovery_call("recover-named");
        let current = recovery_call("current-recovery");
        assert_eq!(current, received);
        assert_eq!(current["writer_epoch"], "2");
        let after = business(&edb, "deployment");
        for t in ["commits", "receipts", "facts", "tokens"] {
            assert_eq!(after[t], ebefore[t], "{t} changed during E recovery");
        }
        assert_eq!(std::fs::read(&ec_manifest).unwrap(), manifest_bytes);
        *e_service = spawn_domain(&edb, &ec_manifest, false, "2", "2");
        *b_service = spawn_domain(&bdb, &ec_manifest, true, "1", "2");
        eventually("E2", || UnixStream::connect(space.path("e.sock")).is_ok());
        eventually("B1→E2", || {
            UnixStream::connect(space.path("b.sock")).is_ok()
        });
        assert_eq!(bbefore, table_bytes(&bdb, "deployment"));
        let before = table_bytes(&xdb, "x_sim_deployment");
        error(x(space, "AcceptExact", command.clone()), "IdentityConflict");
        assert_eq!(table_bytes(&xdb, "x_sim_deployment"), before);
        stop_at(space, "x.sock", x_service);
        let p = space.path("rebind.json");
        let mut handoff = json!({"schema_revision":"x-authority-rebind-input/1",
            "e":{"verification":"current-recovery","db":edb,"receipt":current}});
        if arm == RecoveryArm::Both {
            handoff["s"] = json!({"verification":"current-recovery","db":sdb,
                "receipt":s_recovery(1)});
            let mut invalid = handoff.clone();
            invalid["s"]["receipt"]["request"]["from_epoch"] = json!("2");
            private_json(&p, &invalid);
            assert_refused(serve_x(&xdb, &profile).arg("--authority-rebind").arg(&p));
            assert_eq!(
                table_bytes(&xdb, "x_sim_deployment"),
                before,
                "dual vector split commit"
            );
        } else {
            for (field, replacement) in [
                ("/e/verification", json!("query-recovery")),
                ("/e/db", json!(bdb)),
                ("/e/receipt/writer_epoch", json!("3")),
                ("/e/receipt/request/domain_id", json!("S")),
                ("/e/receipt/request/session_id", json!("other")),
                ("/e/receipt/request/manifest_hash", json!("8".repeat(64))),
                ("/e/receipt/request/cut/root_hash", json!("7".repeat(64))),
                ("/e/receipt/recover_ns", json!("1001")),
            ] {
                let mut invalid = handoff.clone();
                *invalid.pointer_mut(field).unwrap() = replacement;
                private_json(&p, &invalid);
                assert_refused(serve_x(&xdb, &profile).arg("--authority-rebind").arg(&p));
                assert_eq!(table_bytes(&xdb, "x_sim_deployment"), before, "{field}");
            }
            private_json(&p, &current);
            assert_refused(serve_x(&xdb, &profile).arg("--authority-rebind").arg(&p));
            assert_eq!(table_bytes(&xdb, "x_sim_deployment"), before);
        }
        private_json(&p, &handoff);
        *x_service = start_owner(serve_x(&xdb, &profile).arg("--authority-rebind").arg(&p));
        eventually("X rebound", || {
            UnixStream::connect(space.path("x.sock")).is_ok()
        });
        let xnow = business(&xdb, "x_sim_deployment");
        assert_eq!(original_profile, xnow["x_sim_meta"]);
        let rows = xnow["x_authority_bindings"]["rows"].as_array().unwrap();
        assert_eq!(rows.len(), 2);
        let binding: Value = serde_json::from_str(rows[1][1][1].as_str().unwrap()).unwrap();
        assert_eq!(
            binding["old_vector"],
            json!({"e_authority_epoch":1,"s_authority_epoch":1})
        );
        assert_eq!(
            binding["new_vector"],
            json!({"e_authority_epoch":2,"s_authority_epoch":s_epoch.parse::<i64>().unwrap()})
        );
        assert_eq!(
            binding["receipts"][0],
            json!({"domain_id":"E","original":current})
        );
        if arm == RecoveryArm::Both {
            assert_eq!(
                binding["receipts"][1],
                json!({"domain_id":"S","original":s_recovery(1)})
            );
        }
        println!("E1 SIGKILL; E CLI original cut unchanged; binding seq 1 vector={}; E/B cuts and E manifest unchanged",
            binding["new_vector"]);
    }
    let accepted = x(space, "AcceptExact", command.clone());
    assert_eq!(accepted["state"], "Accepted", "{accepted}");
    if recovery.is_some() {
        let q = &accepted["authority_history"][0];
        assert_eq!(q["binding_seq"], 1);
        assert_eq!(q["original"]["reply"]["producer_epoch"], "2");
        assert_eq!(q["original"]["request"]["producer_epoch"], "1");
        assert_eq!(q["original"]["request"]["source_epoch"], "one");
        assert_eq!(q["original"]["reply"]["payload"]["command"], *command);
        assert_eq!(
            q["original"]["reply"]["payload"]["receipt_id"],
            release["receipt_key"]
        );
        assert_eq!(q["original"]["reply"]["payload"]["commit_ns"], RELEASE_NS);
        println!(
            "X first E2 exchange binds current E envelope, original ReleaseExact receipt and clock"
        );
    }
    expect(
        x(
            space,
            "AdvanceBar",
            bar(RELEASE_NS, vec![submit], json!({"kind":"none"})),
        ),
        "SimulationBatch",
    );
    source.join().unwrap();
    let batch = expect(
        x(
            space,
            "AdvanceBar",
            bar(
                RELEASE_NS + 1,
                vec![],
                json!({"kind":"scenario","reference":"TestOnly-liquidity","buy":2,"sell":0}),
            ),
        ),
        "SimulationBatch",
    );
    let originals = batch["originals"].as_array().unwrap();
    assert_eq!(originals.len(), 2, "{batch}");
    for (doc, id) in originals.iter().zip(["x-fill", "x-fee"]) {
        let frame = econ_frame("x-sim", x_producer(split), id, captures(doc, "/event", id));
        expect(
            exchange(&space.path("e.sock"), &frame)["payload"].clone(),
            "Recorded",
        );
    }
    let fill = &originals[0]["event"]["fill"];
    let quantity = fill["quantity"].as_i64().unwrap().to_string();
    let cash = fill["amount"].as_i64().unwrap().to_string();
    let fee = originals[1]["event"]["amount"]
        .as_i64()
        .unwrap()
        .to_string();
    assert_eq!(quantity, "2");
    assert_eq!(fee, "1");
    // 原 X 事实与具名经济分量是两个来源；原样 Capture X，不伪称 X 已生成 TB03C 分量。
    let fill_ref = format!("{}:quantity", digest(&originals[0]));
    let cash_ref = format!("{}:cash", digest(&originals[0]));
    let fee_ref = format!("{}:fee", digest(&originals[1]));
    let attribute = json!({"format":f.opening["format"],"units":f.opening["units"],
        "events":[{"event":"fixture-attribution","allocation_id":"attribution","chong_id":"alpha","family_id":"family-alpha",
            "source":{"source_namespace":"test","source_epoch":"one","source_cursor":"2","external_fact_id":"derived-attribution",
                "received_time":"2","claimed_origin":"TestOnly distinct allocation authority","source_event_time":null},
            "stable_point":{"profile":"TestOnly","seq":"2","source_ref":"sp"},
            "deltas":{"units":quantity,"Pi":"0","A":"0","W":"0"},
            "component_witnesses":[{"kind":"settled_quantity_increase","source_ref":fill_ref,"value":quantity},
                {"kind":"no_other_income_book_changes_in_this_allocation","source_ref":"unchanged","fields":["Pi","A","W"]}],
            "known_cost_components":[{"kind":"acquisition_cash","source_ref":cash_ref,"amount_text":cash,"canonical_amount":cash,"currency":"TEST-CASH","quantum":"1"},
                {"kind":"commission","source_ref":fee_ref,"amount_text":fee,"canonical_amount":fee,"currency":"TEST-CASH","quantum":"1"}]}],
        "evidence_index":{"fragments":{"sp":[{"json_pointer":"/events/0/stable_point"}],"unchanged":[{"json_pointer":"/events/0/component_witnesses/1"}],
            (fill_ref):[{"json_pointer":"/events/0/component_witnesses/0"}],(cash_ref):[{"json_pointer":"/events/0/known_cost_components/0"}],
            (fee_ref):[{"json_pointer":"/events/0/known_cost_components/1"}]}}});
    let attributed = expect(
        econ(
            space,
            "e.sock",
            "capture-attribution",
            captures(&attribute, "/events/0", "attribute-token"),
        ),
        "Recorded",
    );
    apply(space, "apply-fill", &attributed, &json!("attribution"));
    let book = image(&bdb)["book"].clone();
    assert_eq!(book["actual_quantity"], "6", "{book}");
    assert_eq!(book["cost_totals"]["commission"], "1", "{book}");
    if let Some(mut service) = launcher_service {
        assert!(
            stop(&mut service.0).success(),
            "{}",
            launcher_stderr(&mut service.0)
        );
    } else if let Some((mut e, mut b, mut x)) = standalone {
        // ApplyAllocation above has fetched new authoritative facts at B's configured E2.
        println!("true B ApplyAllocation used E2; resulting quantity=6, commission=1");
        stop_at(space, "x.sock", &mut x);
        stop_at(space, "b.sock", &mut b);
        stop_at(space, "e.sock", &mut e);
    }

    let all = [
        table_bytes(&edb, "deployment"),
        table_bytes(&bdb, "deployment"),
        table_bytes(&xdb, "x_sim_deployment"),
    ];
    let index = space.path("voice-archive-index.json");
    save(&index, &f.voice_archive);
    let mut args = vec!["--as-known-ns", "32"];
    if !split {
        let no_archive = audit_domain(&bdb, &ec_manifest, true, &[]);
        assert!(!no_archive.status.success());
        assert!(String::from_utf8_lossy(&no_archive.stderr).contains("归档缺角色"));
        args.extend(["--voice-archive-index", index.to_str().unwrap()]);
    }
    let at = successful_json(audit_domain(&bdb, &ec_manifest, true, &args));
    assert_eq!(at["cut"], voice["cut"]);
    let archive_args = if split {
        vec![]
    } else {
        vec!["--voice-archive-index", index.to_str().unwrap()]
    };
    let e = successful_json(audit_domain(&edb, &ec_manifest, false, &archive_args));
    let bx = successful_json(run(Command::new(x_bin())
        .arg("audit")
        .arg("--db")
        .arg(&xdb)));
    assert_eq!(bx["profile_mode"], "simulation");
    if recovery.is_some() {
        let archive = tempfile::tempdir().unwrap();
        for suffix in ["", "-wal", "-shm"] {
            let path = space.path(&format!("x.db{suffix}"));
            if path.exists() {
                std::fs::rename(path, archive.path().join(format!("x.db{suffix}"))).unwrap();
            }
        }
        let relocated = archive.path().join("x.db");
        assert_eq!(
            successful_json(run(Command::new(x_bin())
                .arg("audit")
                .arg("--db")
                .arg(&relocated))),
            bx
        );
        assert_eq!(table_bytes(&relocated, "x_sim_deployment"), all[2]);
        println!("relocated X audit passed against original bytes");
    }
    if neg {
        let unchanged = read(&space.path("x-profile.json"));
        let mut moved = unchanged.clone();
        moved["history_simulation"]["deployment"]["e_socket"] = json!(space.path("wrong-e.sock"));
        let mut wrong_identity = unchanged.clone();
        wrong_identity["history_simulation"]["business"]["e"]["authority_epoch"] = json!("2");
        let mut mix = unchanged;
        mix["history_simulation"]["business"]["e"]["socket"] = json!(space.path("e.sock"));
        let before = table_bytes(&xdb, "x_sim_deployment");
        for (profile, refusal) in [
            (moved, "X 部署位置已冻结"),
            (wrong_identity, "X 权威端点合同已冻结"),
            (mix, "unknown field"),
        ] {
            let profile_path = space.path("altered-x-profile.json");
            save(&profile_path, &profile);
            let rejected = run_refusal(
                Command::new(x_bin())
                    .arg("serve")
                    .arg("--db")
                    .arg(&xdb)
                    .arg("--profile")
                    .arg(profile_path)
                    .args(["--writer-epoch", "1"]),
            );
            assert!(!rejected.status.success());
            assert!(
                String::from_utf8_lossy(&rejected.stderr).contains(refusal),
                "{}",
                String::from_utf8_lossy(&rejected.stderr)
            );
            assert_eq!(table_bytes(&xdb, "x_sim_deployment"), before);
        }
        let mut moved_eb = read(&ec_manifest);
        moved_eb["deployment"]["domains"]["E"]["socket"] = json!(space.path("wrong-e.sock"));
        let altered = space.path("altered-economic.json");
        save(&altered, &moved_eb);
        let before = table_bytes(&edb, "deployment");
        let refused = run(Command::new(env!("CARGO_BIN_EXE_e_economic_session"))
            .arg("recover")
            .arg("--manifest")
            .arg(altered)
            .arg("--db")
            .arg(&edb));
        assert!(!refused.status.success());
        assert!(String::from_utf8_lossy(&refused.stderr).contains("部署映射已冻结"));
        assert_eq!(table_bytes(&edb, "deployment"), before);
        let copied = space.path("archive");
        std::fs::create_dir(&copied).unwrap();
        for path in [&edb, &bdb, &xdb] {
            for suffix in ["", "-wal", "-shm"] {
                let actual = PathBuf::from(format!("{}{suffix}", path.display()));
                if actual.exists() {
                    std::fs::rename(&actual, copied.join(actual.file_name().unwrap())).unwrap();
                }
            }
        }
        let offline = successful_json(audit_domain(&copied.join("e.db"), &ec_manifest, false, &[]));
        assert_eq!(offline, e);
        assert_eq!(
            successful_json(audit_domain(
                &copied.join("b.db"),
                &ec_manifest,
                true,
                &args
            )),
            at
        );
        assert_eq!(
            successful_json(run(Command::new(x_bin())
                .arg("audit")
                .arg("--db")
                .arg(copied.join("x.db")))),
            bx
        );
        let tampered = Connection::open(copied.join("b.db")).unwrap();
        tampered
            .execute("UPDATE commits SET root='changed-root' WHERE seq=1", [])
            .unwrap();
        drop(tampered);
        assert!(
            !audit_domain(&copied.join("b.db"), &ec_manifest, true, &args)
                .status
                .success()
        );
    }
    all
}

fn funding_package(space: &Space, book: u32, symbol: &str, instrument: &str) -> Value {
    let mut route = json!({"chong_id":"alpha","symbol":symbol,"operation_level":"0","fixed_q":"1",
        "funding":{"Q":"100","policy_record":{"profile_id":"TestOnly","policy_id":"#1355/quantity-tier-policy/v1",
        "version":"v1","supersedes":"none","symbol":symbol,"operation_level":"L0",
        "q_ref":"#1557/funding-authorization/v1@TestOnly","tiers":"none",
        "capacities":[{"level":"L0","C":"100","source":"UserSigned(#917)","valid_through":"2027-10-20"}],
        "frequency_evidence_ref":"#915 报告 :153","authorizer":"合成签署（#2127）",
        "authorized_at":"2026-10-20","valid_through":"2027-10-20"}}});
    let mut funding = json!({"funding_record":{"profile_id":"TestOnly",
        "policy_id":"#1557/funding-authorization/v1","version":"v1","supersedes":"none","cap":"100",
        "currency":"USDC","authorizer":"合成签署（#2127）","authorized_at":"2026-10-20",
        "valid_through":"2027-10-20"},"margin_leverage":{"value":"1","source":"ADR 0040 裁定三"}});
    if book == 3 {
        let mut quote = json!({"source":"synthetic-feed","market":"SYNTH","instrument":instrument,"price_field":"last"});
        let unit = json!({"unit":"BTC-UNIT","quantum":{"num":"1","den":"1"}});
        let mut calibration = json!({"policy_id":"#1610/quantity-calibration/v1","version":"qc-v1","supersedes":"none",
            "binding":{"profile_id":"TestOnly","funding_version":"v1","symbol":symbol,"operation_level":"L0",
                "q_ref":"#1557/funding-authorization/v1@TestOnly"},"quantity_unit":unit,"tiers":[],
            "quantity_basis":{"kind":"frozen_quote","quote_time_policy":"activation_request_asof",
                "max_quote_age":"100","currency_scale":{"from":"USDC","to":"USDC","num":"1","den":"1"},
                "selector":quote,"rounding":"floor"}});
        let sha = digest(&calibration);
        calibration["signature"] = json!({"signature_ref":"fixture://signature/qc-v1","version":"qc-v1",
            "authorizer":"合成签署（#2127）","signed_ns":"1","content_sha256":sha});
        route["funding"]["quantity_calibration"] = calibration;
        route["funding"]["quote_snapshot"] = json!("sealed-1");
        quote.as_object_mut().unwrap().extend(
            json!({"quote_id":"quote-1","price_unit":{"money":"USDC","quantity":unit},
                "t_occurred":"1","t_first_observed":"1","price":{"num":"1","den":"1"},
                "original_ref":"fixture://quotes/quote-1"})
            .as_object()
            .unwrap()
            .clone(),
        );
        funding["quote_snapshots"] =
            json!([{"snapshot_id":"sealed-1","sealed_ns":"2","quotes":[quote]}]);
    }
    json!({"schema_revision":"economic-session-config/2",
        "business":{"schema_revision":"economic-manifest/2","protocol_revision":"economic-session/1",
            "book_revision":format!("tb03c-book/{book}"),"session_id":"tb2127","session_generation":"1","chongs":[route],
            "authorized_sources":[{"source_namespace":"test.feed","source_epoch":"one","producer_id":"X:fixture",
                "producer_epoch":"1","operations":["CaptureExternal"]}],
            "resources":{"max_frame_bytes":"1048576","read_timeout_ms":"1000","write_timeout_ms":"1000",
                "response_timeout_ms":"2000","queue_capacity":"2","max_connections":"2"},
            "clock":{"kind":"TestOnly","plan":{"init_ns":"1","recover_ns":[],
                "messages":{"trade-01":{"received_ns":"2","first_known_ns":"3","commit_ns":"4"}}}},
            "funding":funding},
        "deployment":{"schema_revision":"economic-deployment/1",
            "domains":{"E":{"db":space.path("e.db"),"socket":space.path("e.sock")},
            "B:alpha":{"db":space.path("b.db"),"socket":space.path("b.sock")}},
            "voice":{},"finance":null,"fault_markers":[],"x_db":null}})
}

#[test]
fn signed_market_identifiers_round_trip_without_deployment_bytes() {
    for (book, symbol, instrument) in [
        (2, "000001.SZ", "000001.SZ"),
        (2, "BTC/USDT", "BTC/USDT"),
        (3, "BTC", "BTC/USDT"),
        (3, "BTC", "^GSPC"),
        (3, "BTC", "GC=F"),
        (3, "BTC", "EURUSD=X"),
    ] {
        let arms = [Space::new(), Space::new()].map(|space| {
            let package = funding_package(&space, book, symbol, instrument);
            let manifest = write_json(&space.path("manifest.json"), &package);
            [("e.db", None), ("b.db", Some("alpha"))].map(|(file, chong)| {
                let db = space.path(file);
                let init =
                    successful_json(run(&mut command_for_chong("init", &db, &manifest, chong)));
                assert_eq!(init["kind"], "Initialized");
                let audit =
                    successful_json(run(&mut command_for_chong("audit", &db, &manifest, chong)));
                assert_eq!(audit["kind"], "Audited");
                assert_eq!(audit["cut"], init["cut"]);
                assert_eq!(audit["manifest_hash"], digest(&package["business"]));
                let connection =
                    Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
                let raw: String = connection
                    .query_row("SELECT v FROM meta WHERE k='business_manifest'", [], |r| {
                        r.get(0)
                    })
                    .unwrap();
                assert_eq!(raw, canonical_json(&package["business"]));
                (
                    raw,
                    audit["manifest_hash"].clone(),
                    audit["cut"]["root_hash"].as_str().unwrap().to_owned(),
                )
            })
        });
        assert_eq!(arms[0], arms[1], "book/{book}: {symbol} {instrument}");
    }
}

#[test]
fn real_b_reply_and_s_browser_namespace_are_valid_read_sources() {
    let space = Space::new();
    let mut manifest = funding_package(&space, 2, "BTC", "BTC");
    manifest["business"]["authorized_sources"][0]["operations"] = json!(["ReadView"]);
    let input = write_json(&space.path("source.json"), &manifest);
    successful_json(run(&mut domain_command(
        "init",
        &space.path("e.db"),
        &input,
        false,
    )));
    let db = space.path("b.db");
    successful_json(run(&mut domain_command("init", &db, &input, true)));
    let mut service = Service(
        domain_command("serve", &db, &input, true)
            .args(["--epoch", "1", "--e-epoch", "1"])
            .spawn()
            .unwrap(),
    );
    let sock = space.path("b.sock");
    eventually("B ReadView", || UnixStream::connect(&sock).is_ok());
    let reply = exchange(
        &sock,
        &econ_frame(
            "test.feed",
            "X:fixture",
            "read-producer",
            json!({"op":"ReadView","cut":null,"as_known_ns":null}),
        ),
    );
    let _ = stop(&mut service.0);
    assert_eq!(reply["payload"]["kind"], "EconomicView", "{reply}");
    assert_eq!(reply["source_namespace"], "economic-session/replies");
    assert_eq!(reply["producer_id"], "B:alpha:tb2127");

    let target = Space::new();
    let mut registered = funding_package(&target, 2, "BTC", "BTC");
    registered["business"]["authorized_sources"] = json!([
        {"source_namespace":reply["source_namespace"],"source_epoch":reply["source_epoch"],
            "producer_id":reply["producer_id"],"producer_epoch":reply["producer_epoch"],
            "operations":["ReadView"]},
        {"source_namespace":"s-observe/browser","source_epoch":"one","producer_id":"browser",
            "producer_epoch":"1","operations":["ReadView"]}
    ]);
    let config = write_json(&target.path("registered.json"), &registered);
    for (file, b) in [("e.db", false), ("b.db", true)] {
        let db = target.path(file);
        let init = expect(
            successful_json(run(&mut domain_command("init", &db, &config, b))),
            "Initialized",
        );
        let audit = expect(
            successful_json(audit_domain(&db, &config, b, &[])),
            "Audited",
        );
        assert_eq!(audit["cut"], init["cut"]);
        assert_eq!(audit["manifest_hash"], digest(&registered["business"]));
    }
}

#[test]
fn local_economic_identities_are_rejected_before_any_db_or_lock() {
    for book in [2, 3] {
        let space = Space::new();
        let baseline = funding_package(&space, book, "BTC", "BTC/USDT");
        let db = space.path("e.db");
        let socket = space.path("e.sock");
        let manifest = space.path("manifest.json");
        let b = space.path("b.db");
        for (field, value) in [
            ("chong_id", json!(socket)),
            ("chong_id", json!("data/chong")),
            ("clock.plan.messages", json!(db)),
            ("session_id", json!(db)),
            ("producer_id", json!(db)),
            ("producer_id", json!("C:db")),
            ("producer_id", json!("B:a:/tmp/x")),
            ("source_namespace", json!("data/db")),
            ("source_namespace", json!("local/e")),
            ("source_namespace", json!("/tmp/x")),
            ("test_only_fault.message_id", json!(db)),
            ("symbol", json!("X/STATE.SOCK")),
        ] {
            let mut m = baseline.clone();
            let business = &mut m["business"];
            let mut chong = "alpha";
            match field {
                "chong_id" => {
                    business["chongs"][0]["chong_id"] = value.clone();
                    chong = value.as_str().unwrap();
                    let domains = m["deployment"]["domains"].as_object_mut().unwrap();
                    let layout = domains.remove("B:alpha").unwrap();
                    domains.insert(format!("B:{chong}"), layout);
                }
                "clock.plan.messages" => {
                    let messages = business["clock"]["plan"]["messages"]
                        .as_object_mut()
                        .unwrap();
                    let plan = messages["trade-01"].clone();
                    messages.insert(value.as_str().unwrap().to_owned(), plan);
                }
                "producer_id" | "source_namespace" => {
                    business["authorized_sources"][0][field] = value
                }
                "test_only_fault.message_id" => {
                    business["test_only_fault"] =
                        json!([{"message_id":value,"phase":"before_commit"}]);
                    m["deployment"]["fault_markers"] = json!([
                        {"message_id":value,"phase":"before_commit","marker_path":space.path("fault.marker")}
                    ]);
                }
                "symbol" => {
                    business["chongs"][0]["symbol"] = value.clone();
                    business["chongs"][0]["funding"]["policy_record"]["symbol"] = value;
                }
                _ => business[field] = value,
            }
            write_json(&manifest, &m);
            for (target, chong) in [(&db, None), (&b, Some(chong))] {
                for op in ["init", "audit"] {
                    let out = run(&mut command_for_chong(op, target, &manifest, chong));
                    let err = String::from_utf8_lossy(&out.stderr);
                    assert_eq!(out.status.code(), Some(1), "{op} {field}: {err}");
                    assert!(
                        out.stdout.is_empty() && err.contains(field),
                        "{op} {field}: {err}"
                    );
                }
            }
            let mut files = space.0.path().read_dir().unwrap();
            assert_eq!(files.next().unwrap().unwrap().path(), manifest);
            assert!(files.next().is_none(), "book/{book} {field} 留下部署文件");
        }
    }
}

#[test]
fn path_independent_e_b_x_full_business_tables_and_offline_archives() {
    let a = workload(&Space::new(), true, true, None);
    let b = workload(&Space::new(), true, false, None);
    for (left, right) in a.iter().zip(&b) {
        assert_eq!(
            left.0.as_bytes(),
            right.0.as_bytes(),
            "业务表（含原根、精确图像、回执）逐字节比较"
        );
        assert_ne!(
            left.1.as_ref().unwrap(),
            right.1.as_ref().unwrap(),
            "两套实际部署位置须不同"
        );
    }
}

#[test]
fn legacy_same_path_repeats_but_different_paths_keep_different_roots() {
    let first = Space::new();
    let a = workload(&first, false, false, None);
    let original = first.0.path().to_owned();
    let archive = tempfile::tempdir().unwrap();
    let relocated = archive.path().join("original-deployment");
    std::fs::rename(&original, &relocated).unwrap();
    assert!(!original.exists());
    let mut index = read(&relocated.join("voice-archive-index.json"));
    for p in index["objects"].as_object_mut().unwrap().values_mut() {
        let original_file = Path::new(p.as_str().unwrap())
            .strip_prefix(&original)
            .unwrap();
        *p = json!(relocated.join(original_file));
    }
    let new_index = relocated.join("relocated-index.json");
    save(&new_index, &index);
    let offline = successful_json(audit_domain(
        &relocated.join("b.db"),
        &relocated.join("economic.json"),
        true,
        &[
            "--voice-archive-index",
            new_index.to_str().unwrap(),
            "--as-known-ns",
            "32",
        ],
    ));
    assert_eq!(
        offline["image"]["history"]
            .as_array()
            .unwrap()
            .last()
            .unwrap()["kind"],
        "BindVoice"
    );
    successful_json(run(Command::new(x_bin())
        .arg("audit")
        .arg("--db")
        .arg(relocated.join("x.db"))));
    std::fs::create_dir(&original).unwrap();
    let same = workload(&first, false, false, None);
    assert_eq!(a, same);
    let moved = workload(&Space::new(), false, false, None);
    let tip = |bytes: &str| {
        serde_json::from_str::<Value>(bytes).unwrap()["commits"]["rows"]
            .as_array()
            .unwrap()
            .last()
            .unwrap()[2]
            .clone()
    };
    assert_ne!(tip(&a[0].0), tip(&moved[0].0), "旧 E 根引用了旧 B 证明");
    assert_ne!(tip(&a[1].0), tip(&moved[1].0), "旧 B 根仍承诺 Voice 原路径");
}

#[test]
fn r2_b3_voice_rejects_pinned_review_with_deployment_scope_without_b_write() {
    let space = Space::new();
    let declared = declaration("TestOnlyStructure", DECLARED_NS);
    let sdb = s_init_v3(&space, Some(&declared));
    let launcher = launcher_manifest(
        &space,
        "simulation",
        &declared,
        &sdb,
        &anchor(&sdb),
        &space.path("x-profile.json"),
    );
    let mut control = read(&launcher);
    control["economic"]["b"][0]["chong"] = json!("alpha");
    save(&launcher, &control);
    let f = inputs(&space, &sdb, true);

    let path = space.path("voice/review.json");
    let mut review = read(&path);
    review["scope"] = json!(format!(
        "verification inputs at {}",
        space.path("voice/bundle.json").display()
    ));
    let sha = save(&path, &review);
    let manifest = space.path("economic.json");
    let mut pinned = read(&manifest);
    pinned["business"]["voice_binding"]["authorities"][0]["verification_sha256"] = json!(sha);
    save(&manifest, &pinned);

    let mut service = Service(spawn_launcher(&launcher));
    wait_domains(&mut service.0);
    for name in ["e.sock", "b.sock"] {
        eventually(name, || UnixStream::connect(space.path(name)).is_ok());
    }
    let captured = expect(
        econ(
            &space,
            "e.sock",
            "open",
            captures(&f.opening, "/events/0", "opening-token"),
        ),
        "Recorded",
    );
    apply(&space, "apply-open", &captured, &json!("opening-alpha"));
    let bdb = space.path("b.db");
    let before = table_bytes(&bdb, "deployment");
    error(
        econ(&space, "b.sock", "bind", f.binding),
        "SchemaUnsupported",
    );
    assert_eq!(table_bytes(&bdb, "deployment"), before);
}

fn serve_x(db: &Path, profile: &Path) -> Command {
    let mut cmd = Command::new(x_bin());
    cmd.arg("serve")
        .arg("--db")
        .arg(db)
        .arg("--profile")
        .arg(profile)
        .args(["--writer-epoch", "1"]);
    cmd
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum RecoveryArm {
    E,
    Both,
}

fn s_recovery_config() -> Value {
    json!({"rule_revision":"rule/1","profile_hash":"1".repeat(64),"catalog_hash":"2".repeat(64),
        "clock_plan_hash":"3".repeat(64),"structure_source":{"category":"TestOnlyStructure","namespaces":[DECLARED_NS]}})
}
fn s_recovery(from: i64) -> Value {
    json!({"kind":"NamedRecoveryReceipt","recover_ns":"1000","writer_epoch":(from+1).to_string(),
        "request":{"schema_revision":"s-recovery/1","domain_id":"S","session_id":SESSION_ID,
            "session_generation":"1","recovery_id":"recovered-s","from_epoch":from.to_string(),
            "cut":{"generation":"0","structure_cut":"cut-0","index_frontier":""},
            "config":s_recovery_config(),"clock_event_id":"recover-one"}})
}
fn private_json(path: &Path, value: &Value) {
    save(path, value);
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)).unwrap();
}
fn assert_refused(cmd: &mut Command) {
    let result = run_refusal(cmd);
    assert_eq!(
        result.status.code(),
        Some(2),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
}
fn business(db: &Path, local: &str) -> Value {
    serde_json::from_str(&table_bytes(db, local).0).unwrap()
}
fn start_owner(command: &mut Command) -> Service {
    Service(
        command
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .spawn()
            .unwrap(),
    )
}
fn spawn_domain(db: &Path, manifest: &Path, b: bool, epoch: &str, e_epoch: &str) -> Service {
    let mut cmd = domain_command("serve", db, manifest, b);
    cmd.args(["--epoch", epoch]);
    if b {
        cmd.args(["--e-epoch", e_epoch]);
    }
    start_owner(&mut cmd)
}
fn stop_at(space: &Space, socket: &str, child: &mut Service) -> std::process::ExitStatus {
    use std::os::unix::process::ExitStatusExt;
    child.0.kill().unwrap();
    let status = child.0.wait().unwrap();
    assert_eq!(status.signal(), Some(libc::SIGKILL));
    // 仅隔离本夹具刚杀进程的 socket；产品端点再服务仍由 owner 合同负责。
    let old = space.path(socket);
    if old.exists() {
        std::fs::rename(
            old,
            space.path(&format!("{socket}.stopped-{}", child.0.id())),
        )
        .unwrap();
    }
    status
}

#[test]
fn authority_rebind_e_named_recovery() {
    let a = workload(&Space::new(), true, false, Some(RecoveryArm::E));
    let b = workload(&Space::new(), true, false, Some(RecoveryArm::E));
    for (left, right) in a.iter().zip(&b) {
        assert_eq!(left.0.as_bytes(), right.0.as_bytes());
        assert_ne!(left.1, right.1);
    }
    println!(
        "two independent E/B/X deployments: full business bytes (including binding records) equal"
    );
}

#[test]
fn authority_rebind_dual_domain_vector_real_e() {
    workload(&Space::new(), true, false, Some(RecoveryArm::Both));
}
#[test]
fn local_x_authority_model_and_condition_identity_are_rejected_before_serve() {
    let space = Space::new();
    inputs(&space, &space.path("s.db"), true);
    let profile = space.path("x-profile.json");
    let valid = read(&profile);
    let db = space.path("x.db");
    let entries = || {
        space
            .0
            .path()
            .read_dir()
            .unwrap()
            .map(|e| e.unwrap().file_name())
            .collect::<std::collections::BTreeSet<_>>()
    };
    let before = entries();
    for (pointer, field) in [
        ("/session_id", "session_id"),
        ("/x_id", "x_id"),
        ("/source_epoch", "source_epoch"),
        ("/e/authority_id", "authority_id"),
        ("/s/producer_id", "producer_id"),
        ("/model/symbol", "model.symbol"),
        ("/model/fee_profile/role_source", "fee_profile.role_source"),
        ("/conditions/0/evidence_refs/0", "evidence_refs"),
        ("/conditions/0/condition_id", "condition_id"),
    ] {
        let mut bad = valid.clone();
        *bad["history_simulation"]["business"]
            .pointer_mut(pointer)
            .unwrap() = json!(db);
        save(&profile, &bad);
        let out = run_refusal(&mut serve_x(&db, &profile));
        let err = String::from_utf8_lossy(&out.stderr);
        assert_eq!(out.status.code(), Some(2), "{field}: {err}");
        assert!(
            out.stdout.is_empty() && err.contains(field),
            "{field}: {err}"
        );
        assert_eq!(entries(), before);
    }
}

#[test]
fn r2_b5_x_rejects_socket_aliases_before_any_db_or_bind() {
    let space = Space::new();
    inputs(&space, &space.path("s.db"), true);
    let profile_path = space.path("x-profile.json");
    let profile = read(&profile_path);
    std::os::unix::fs::symlink(space.path("voice"), space.path("aliased-parent")).unwrap();
    let db = space.path("x.db");
    let socket = space.path("x.sock");
    let _peer = UnixListener::bind(space.path("voice/live.sock")).unwrap();
    std::os::unix::fs::symlink(space.path("voice/live.sock"), space.path("alias.sock")).unwrap();
    for (e, s) in [
        ("voice/../x.sock", "condition.sock"),
        ("aliased-parent//./../x.sock", "condition.sock"),
        ("voice/e.sock", "aliased-parent//./e.sock"),
        ("e.sock", "voice/../x.sock"),
        ("voice/live.sock", "alias.sock"),
    ] {
        let mut p = profile.clone();
        p["history_simulation"]["deployment"]["e_socket"] = json!(space.path(e));
        p["history_simulation"]["deployment"]["s_socket"] = json!(space.path(s));
        save(&profile_path, &p);
        let mut child = serve_x(&db, &profile_path)
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        eventually("X 应拒绝启动", || {
            child.try_wait().unwrap().is_some() || (db.exists() && socket.exists())
        });
        let running = child.try_wait().unwrap().is_none();
        if running {
            child.kill().unwrap();
        }
        let out = child.wait_with_output().unwrap();
        assert!(!running, "X 服务已接受别名：{e} / {s}");
        assert!(!out.status.success());
        let stderr = String::from_utf8_lossy(&out.stderr);
        assert!(
            stderr.contains("socket 实际目标重复"),
            "{e} / {s}: {stderr}"
        );
        assert!(!db.exists());
        assert!(!space.path("x.db.writer.lock").exists());
        assert!(!socket.exists());
    }
}

#[test]
fn r3_b2_e_and_b_reject_nested_deployment_before_first_write() {
    for revision in ["tb03c-book/2", "tb03c-book/3"] {
        let space = Space::new();
        inputs(&space, &space.path("s.db"), true);
        let path = space.path("economic.json");
        let mut package = read(&path);
        for key in ["voice_binding", "finance", "history_simulation_source"] {
            package["business"].as_object_mut().unwrap().remove(key);
        }
        let deploy = &mut package["deployment"];
        deploy["voice"] = json!({});
        deploy["finance"] = Value::Null;
        deploy["x_db"] = Value::Null;
        let business = &mut package["business"];
        business["book_revision"] = json!(revision);
        business["authorized_sources"]
            .as_array_mut()
            .unwrap()
            .truncate(1);
        business["authorized_sources"][0]["operations"] = json!(["CaptureExternal"]);
        let funding_id = "#1557/funding-authorization/v1";
        let q_ref = format!("{funding_id}@P0-acceptance-5m");
        let policy = json!({"policy_id":"#1355/quantity-tier-policy/v1","profile_id":"P0-acceptance-5m",
            "version":"v1","supersedes":"none","scope":"evidence_only","symbol":"alpha","operation_level":"L2","q_ref":q_ref,
            "tiers":[{"d":"1","w":"Unmeasured","source":"none"}],
            "capacities":[{"level":"L2","C":"9630000","source":"UserSigned(#917)","valid_through":"2027-10-20"}],
            "frequency_evidence_ref":"#915 报告 :153","authorizer":"用户（#1557/#1558 2026-10-20 批复）",
            "authorized_at":"2026-10-20","valid_through":"2027-10-20"});
        business["funding"] = json!({"funding_record":{"policy_id":funding_id,"profile_id":"P0-acceptance-5m",
            "version":"v1","supersedes":"none","scope":"evidence_only","cap":"5000000","currency":"USDC",
            "authorizer":"用户（#1557/#1558 2026-10-20 批复）","authorized_at":"2026-10-20","valid_through":"2027-10-20"},
            "margin_leverage":{"value":"1","source":"ADR 0040 裁定三"}});
        business["chongs"][0]["funding"] = json!({"Q":"690000","policy_record":policy});
        if revision == "tb03c-book/3" {
            business["funding"]["quote_snapshots"] = json!([]);
            let cf = &mut business["chongs"][0]["funding"];
            cf["quote_snapshot"] = json!("pending");
            cf["quantity_calibration"] = json!({
                "policy_id":"#1610/quantity-calibration/v1","version":"v1","supersedes":"none",
                "binding":{"profile_id":"P0-acceptance-5m","funding_version":"v1",
                    "symbol":"alpha","operation_level":"L2","q_ref":q_ref},
                "quantity_unit":{"unit":"lot","quantum":{"num":"1","den":"1"}},
                "signature":"AwaitingPolicy","quantity_basis":"AwaitingPolicy","tiers":[]
            });
        }
        let mut malformed = package.clone();
        malformed["business"]["chongs"][0]["funding"]["policy_record"]["scope"] =
            package["deployment"]["domains"]["E"].clone();
        save(&path, &malformed);
        for (owner, b) in [("e", false), ("b", true)] {
            let db = space.path(&format!("{owner}.db"));
            let out = run(&mut domain_command("init", &db, &path, b));
            assert!(
                !out.status.success() && out.stdout.is_empty(),
                "{revision} {owner}"
            );
            let error = String::from_utf8_lossy(&out.stderr);
            assert!(
                error.contains("scope 只允许 evidence_only"),
                "{revision} {owner}: {error}"
            );
            for name in [".db", ".db.writer.lock", ".db-wal", ".db-shm", ".sock"] {
                assert!(
                    !space.path(&format!("{owner}{name}")).exists(),
                    "{revision} {owner}{name}"
                );
            }
        }
        save(&path, &package);
        for (owner, b) in [("e", false), ("b", true)] {
            let db = space.path(&format!("{owner}.db"));
            expect(
                successful_json(run(&mut domain_command("init", &db, &path, b))),
                "Initialized",
            );
            let audit = expect(successful_json(audit_domain(&db, &path, b, &[])), "Audited");
            assert_eq!(audit["manifest_hash"], digest(&package["business"]));
        }
    }
}

#[test]
fn r3_b5_x_rejects_existing_socket_hard_links_before_lock_db_or_bind() {
    let mut failures = Vec::new();
    for (first, second) in [("e", "s"), ("x", "e"), ("x", "s")] {
        let space = Space::new();
        inputs(&space, &space.path("s.db"), true);
        let profile_path = space.path("x-profile.json");
        let mut profile = read(&profile_path);
        let a = space.path(&format!("{first}.sock"));
        let b = space.path(&format!("{second}.sock"));
        let _peer = UnixListener::bind(&a).unwrap();
        std::fs::hard_link(&a, &b).unwrap();
        let object = |path: &Path| {
            let m = std::fs::metadata(path).unwrap();
            (m.dev(), m.ino())
        };
        let id = object(&a);
        assert_eq!(id, object(&b));
        assert_ne!(a.canonicalize().unwrap(), b.canonicalize().unwrap());
        let db = space.path("x.db");
        let socket = space.path("x.sock");
        let cfg = &mut profile["history_simulation"];
        cfg["deployment"]["socket"] = json!(socket);
        cfg["deployment"]["e_socket"] = json!(space.path("e.sock"));
        cfg["deployment"]["s_socket"] = json!(space.path("s.sock"));
        let parsed =
            newchan_rust::history_simulation::runtime::ConfiguredProfile::parse(cfg.clone())
                .unwrap();
        let prelock = parsed.check_serve_deployment(&db);
        save(&profile_path, &profile);

        let list = || {
            std::fs::read_dir(&space.path("."))
                .unwrap()
                .map(|entry| entry.unwrap().file_name())
                .collect::<std::collections::BTreeSet<_>>()
        };
        let before = list();
        let lock = space.path("x.db.writer.lock");
        let mut child = serve_x(&db, &profile_path)
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        eventually("X 应退出或已打开数据库", || {
            child.try_wait().unwrap().is_some() || db.exists()
        });
        let running = child.try_wait().unwrap().is_none();
        if running {
            let _ = child.kill();
        }
        let out = child.wait_with_output().unwrap();
        let stderr = String::from_utf8_lossy(&out.stderr);
        if !matches!(&prelock, Err(e) if e.contains("socket 实际目标重复"))
            || out.status.success()
            || !stderr.contains("socket 实际目标重复")
            || db.exists()
            || lock.exists()
            || (first != "x" && socket.exists())
        {
            failures.push(format!(
                "{first}/{second}: prelock={prelock:?}, status={}, db={}, lock={}, x_socket={}, stderr={stderr}",
                out.status, db.exists(), lock.exists(), socket.exists()
            ));
        }
        assert_eq!(object(&a), id);
        assert_eq!(object(&b), id);
        if list() != before {
            failures.push(format!("{first}/{second}: 启动拒绝时生成了本地文件"));
        }
    }
    assert!(failures.is_empty(), "硬链接通过取锁前门禁：{failures:#?}");
}

#[test]
fn r2_b6_x_offline_audit_requires_registered_outer_and_inner_contracts() {
    let space = Space::new();
    inputs(&space, &space.path("s.db"), true);
    let src = space.path("x.db");
    let profile = space.path("x-profile.json");
    let mut p = read(&profile);
    p["history_simulation"]["deployment"]["e_socket"] = json!(space.path("voice/e.sock"));
    save(&profile, &p);
    let mut child = serve_x(&src, &profile).spawn().unwrap();
    eventually("X live", || {
        UnixStream::connect(space.path("x.sock")).is_ok()
    });
    let batch = bar(0, vec![], json!({"kind":"none"}));
    let original = expect(x(&space, "AdvanceBar", batch.clone()), "SimulationBatch");
    child.kill().unwrap();
    child.wait().unwrap();
    let socket = space.path("x.sock");
    // 独立进程被杀后保留 stale socket；按原合同先腾出同一端点，再原址重开。
    std::fs::rename(&socket, space.path("stale-x.sock")).unwrap();
    let mut child = serve_x(&src, &profile).spawn().unwrap();
    eventually("X 原址续服", || UnixStream::connect(&socket).is_ok());
    assert_eq!(x(&space, "AdvanceBar", batch), original);
    child.kill().unwrap();
    child.wait().unwrap();
    // 归档核证不能要求原部署的父目录仍然存在。
    std::fs::rename(space.path("voice"), space.path("old-deployment-absent")).unwrap();
    let source = Connection::open_with_flags(&src, OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
    let audit = |db: &Path| run(Command::new(x_bin()).arg("audit").arg("--db").arg(db));
    let good = successful_json(audit(&src));
    assert_eq!(good["profile_revision"], "x-execution-profile/1");
    let backup = |name: &str| {
        let db = space.path(name);
        source
            .execute("VACUUM INTO ?1", [db.to_str().unwrap()])
            .unwrap();
        db
    };
    for (key, value, reason) in [
        (
            "profile_revision",
            "x-execution-profile/999",
            "VersionUnsupported",
        ),
        (
            "profile_mode",
            "production",
            "history_simulation 仅允许 simulation",
        ),
        ("profile_mode", "unknown", "profile mode 必须是"),
        (
            "history_simulation",
            "false",
            "离线 audit 仅用于 simulation X",
        ),
    ] {
        let db = backup(&format!("archive-{key}-{value}.db").replace('/', "-"));
        let c = Connection::open(&db).unwrap();
        assert_eq!(
            c.execute("UPDATE x_meta SET value=?1 WHERE key=?2", [value, key])
                .unwrap(),
            1
        );
        drop(c);
        let out = audit(&db);
        assert!(!out.status.success(), "{key}={value} 被离线 audit 接纳");
        assert!(out.stdout.is_empty());
        assert!(
            String::from_utf8_lossy(&out.stderr).contains(reason),
            "{out:?}"
        );
    }

    let db = backup("archive-invalid-inner.db");
    let c = Connection::open(&db).unwrap();
    let mut wrong = p["history_simulation"]["business"].clone();
    wrong["schema_revision"] = json!("x-simulation-authority/999");
    assert_eq!(
        c.execute(
            "UPDATE x_sim_meta SET v=?1 WHERE k='authority_profile'",
            [canonical_json(&wrong)]
        )
        .unwrap(),
        1
    );
    drop(c);
    let out = audit(&db);
    assert!(!out.status.success());
    assert!(
        String::from_utf8_lossy(&out.stderr).contains("未知模拟 X 业务或部署版本"),
        "{out:?}"
    );
}
