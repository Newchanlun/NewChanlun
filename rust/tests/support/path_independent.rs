//! #2127：正式 launcher → 真 E/B/X 独占进程。S 的精确授权与 FIN basis 明示为受控源，
//! X 原始成交和费用从真 X 捕获；独立 TestOnly 归属源显式提供现有 B 合同所需经济分量。
use super::*;
use newchan_rust::session_protocol::{canonical_json, reply_envelope, validate_envelope};
use rusqlite::types::ValueRef;
use std::io::{BufRead, BufReader};
use std::os::unix::net::UnixListener;

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
fn econ_frame(source: &str, id: &str, payload: Value) -> Value {
    let producer = if source == "x-sim" { "X" } else { "fixture" };
    json!({"schema_revision":"economic-session/1","session_id":SESSION_ID,"session_generation":"1",
        "source_namespace":source,"source_epoch":"one","producer_id":producer,"producer_epoch":"1",
        "message_id":id,"payload_hash":digest(&payload),"payload":payload,"causal_refs":[]})
}
fn econ(space: &Space, owner: &str, id: &str, payload: Value) -> Value {
    exchange(&space.path(owner), &econ_frame("test", id, payload))["payload"].clone()
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

fn inputs(space: &Space, s_db: &Path, split: bool) -> Input {
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
        "exact_release":{"x_target":{"x_id":"X","x_epoch":"1"},"projection_kind":"per_leg","rd11_policy":"controlled-fixture-rd11",
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
    let x_binding = json!({"source_namespace":"x-sim","source_epoch":"one","producer_id":"X","producer_epoch":"1","model_content_hash":digest(&x_model)});
    let mut business = json!({"schema_revision":format!("economic-manifest/{ver}"),"protocol_revision":"economic-session/1",
        "session_id":SESSION_ID,"session_generation":"1","book_revision":"tb03c-book/1",
        "chongs":[{"chong_id":"alpha","symbol":"alpha","operation_level":"2","fixed_q":"12"}],
        "authorized_sources":[rights,{"source_namespace":"x-sim","source_epoch":"one","producer_id":"X","producer_epoch":"1",
            "operations":["QueryReleasedExact","CaptureExternal"]}],
        "resources":{"max_frame_bytes":"16777216","read_timeout_ms":"2000","write_timeout_ms":"2000","response_timeout_ms":"30000","queue_capacity":"4","max_connections":"4"},
        "clock":{"kind":"TestOnly","plan":{"init_ns":"1","recover_ns":["1000"],"messages":clocks}},
        "voice_binding":{"schema_revision":format!("voice-binding/{ver}"),"authorities":[authority]},"finance":fin,
        "history_simulation_source":x_binding});
    let mut x_profile = json!({"model":x_model,"session_id":SESSION_ID,"session_generation":"1","x_id":"X",
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

struct Launcher(Child);
impl Drop for Launcher {
    fn drop(&mut self) {
        if self.0.try_wait().ok().flatten().is_none() {
            let _ = stop(&mut self.0);
        }
    }
}
fn controlled_s(path: &Path) -> std::thread::JoinHandle<()> {
    let listener = UnixListener::bind(path).unwrap();
    std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut line = String::new();
        BufReader::new(&stream).read_line(&mut line).unwrap();
        let env = validate_envelope(serde_json::from_str(&line).unwrap(), S_SCHEMA).unwrap();
        let request = &env["payload"];
        assert_eq!(request["op"], "RequestConditionalExecution");
        let mut response = request.clone();
        response.as_object_mut().unwrap().remove("op");
        response["state"] = json!("ExecuteCommitted");
        response["receipt_id"] = json!("S:cmd-alpha");
        response["commit_ns"] = json!(RELEASE_NS);
        let reply = reply_envelope(
            &env, response, S_SCHEMA, SESSION_ID, "1", S_RESP, S_PRODUCER, "1",
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
    let exe = if b {
        env!("CARGO_BIN_EXE_b_chong_session")
    } else {
        env!("CARGO_BIN_EXE_e_economic_session")
    };
    let mut command = Command::new(exe);
    command
        .arg("audit")
        .arg("--manifest")
        .arg(manifest)
        .arg("--db")
        .arg(db);
    if b {
        command.args(["--chong", "alpha"]);
    }
    run(command.args(extra))
}
fn successful_json(out: Output) -> Value {
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}

fn workload(space: &Space, split: bool, neg: bool) -> [(String, Option<String>); 3] {
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
    let source = controlled_s(&space.path("condition.sock"));
    let mut service = Launcher(spawn_launcher(&launcher));
    wait_domains(&mut service.0);
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
        "plan_hash":digest(&submit),"certificate":certificate,"x_id":"X","x_epoch":"1","writer_epoch":"1"}),
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
    let accepted = x(space, "AcceptExact", command.clone());
    assert_eq!(accepted["state"], "Accepted", "{accepted}");
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
        let frame = econ_frame("x-sim", id, captures(doc, "/event", id));
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
    assert!(
        stop(&mut service.0).success(),
        "{}",
        launcher_stderr(&mut service.0)
    );

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

#[test]
fn path_independent_e_b_x_full_business_tables_and_offline_archives() {
    let a = workload(&Space::new(), true, true);
    let b = workload(&Space::new(), true, false);
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
    let a = workload(&first, false, false);
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
    let same = workload(&first, false, false);
    assert_eq!(a, same);
    let moved = workload(&Space::new(), false, false);
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

    let mut service = Launcher(spawn_launcher(&launcher));
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
