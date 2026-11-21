//! #1425 TB-04-F 单一明确原责任域测试：同会话 `tb03c-book/1` + `tb03b-finance/6` + 真实 X 模拟原件。
//! 覆盖 F1（不预列未来成交 key，由 E 保留 grant 责任与 FIN/6 ReleasedExact 命令覆盖）、
//! F2（命令/grant/命令体内固化 model_ref/限价/数量/金额/前件逐项核验，区分完整 FIN plan hash 与 command.change hash）、
//! 同游标双件不吞费不双计、B 唯一应用、冷恢复离线审计及完整负控集合（含拒绝 tb03b-finance/5）。
use super::tb03c_book_tests::Space;
use super::{book, service, store};
use crate::history_simulation::{
    model::{
        Bar, Batch, Capacity, Change, FeeProfile, FeeRole, Model, Order, OrderKind, Rate, Rounding,
        Side,
    },
    runtime as x_runtime, store as x_store, EXACT_PROFILE_REVISION,
};
use crate::session_protocol::{canonical_json, sha256_hex};
use serde_json::{json, Value};
use std::path::Path;

const SESSION: &str = "tb1425-single-owner";
const FIN6: &str = "tb03b-finance/6";
const E: usize = 0;
const ALPHA: usize = 1;
const BETA: usize = 2;

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

fn save(dir: &Path, name: &str, v: &Value) -> (String, String) {
    let p = dir.join(name);
    let raw = canonical_json(v);
    std::fs::write(&p, &raw).unwrap();
    (p.to_str().unwrap().into(), sha256_hex(raw.as_bytes()))
}

fn sim_model() -> Model {
    Model {
        model_id: "history-sim/bar-batch-known-frontier/1".into(),
        revision: "oracle-1".into(),
        symbol: "alpha".into(),
        currency: "TEST-CASH".into(),
        quantity_unit: "TEST-UNIT".into(),
        tick_value: 1,
        projection_kind: "per_leg".into(),
        rd11_policy: "controlled-fixture-rd11".into(),
        rd12_policy: "per-leg-source-attribution/1".into(),
        seed: "none".into(),
        fee_profile: FeeProfile {
            reference: "controlled-fee/1".into(),
            role_source: "controlled-role-map/1".into(),
            limit_role: FeeRole::Maker,
            market_role: FeeRole::Taker,
            market_slippage_ticks: 1,
            market_slippage_source: "controlled-oracle/1".into(),
            maker: Rate {
                numerator: 1,
                denominator: 100,
                rounding: Rounding::Ceiling,
            },
            taker: Rate {
                numerator: 2,
                denominator: 100,
                rounding: Rounding::Ceiling,
            },
        },
    }
}

struct Env {
    _space: Space,
    dir: std::path::PathBuf,
    configs: Vec<store::Config>,
    dbs: Vec<rusqlite::Connection>,
    epochs: Vec<i64>,
    x_conn: rusqlite::Connection,
    x_db_path: std::path::PathBuf,
    x_profile: Option<x_runtime::Profile>,
    data: Value,
    plans: [Value; 2],
    openings: [Value; 2],
    bindings: [Value; 2],
    next: usize,
}

impl Env {
    fn build(tag: &str, alpha_family: &str) -> Self {
        Self::build_with_x(tag, alpha_family, false, SESSION, "1")
    }

    fn build_bare_x(tag: &str, alpha_family: &str) -> Self {
        Self::build_with_x(tag, alpha_family, true, SESSION, "1")
    }

    fn build_with_x(
        tag: &str,
        alpha_family: &str,
        bare_x: bool,
        x_session: &str,
        x_generation: &str,
    ) -> Self {
        let space = Space::new(tag);
        let dir = space.0.clone();
        let model = sim_model();
        let model_val = serde_json::to_value(&model).unwrap();
        let model_hash = book::hash(&model_val);

        let x_db = dir.join("x.db");
        let mut x_conn = rusqlite::Connection::open(&x_db).unwrap();
        let x_profile = if bare_x {
            // 裸撮合 store：只有 x_sim_* 表，没有 X/3 x_meta、authority_profile 或 x_exact_commands
            x_store::initialize(&mut x_conn, &model, "x-sim", "epoch1").unwrap();
            None
        } else {
            let conds: Vec<x_runtime::Condition> = CONDITIONS
                .iter()
                .map(|(id, cap, stage)| x_runtime::Condition {
                    condition_id: (*id).into(),
                    authority_revision: (*cap).into(),
                    dependency_set: vec!["controlled-dependency".into()],
                    invalidation_sources: vec!["controlled-invalidation".into()],
                    required_check_stages: vec![(*stage).into()],
                    evidence_refs: vec!["controlled-evidence".into()],
                    coverage_proof: "controlled-coverage".into(),
                    validator_capability: (*cap).into(),
                    failure_result: "Denied".into(),
                })
                .collect();
            let profile = x_runtime::Profile {
                model: model.clone(),
                session_id: x_session.into(),
                session_generation: x_generation.into(),
                x_id: "X".into(),
                source_namespace: "x-sim".into(),
                source_epoch: "epoch1".into(),
                socket: dir.join("x.sock").to_str().unwrap().into(),
                e: x_runtime::Authority {
                    socket: dir.join("e.sock").to_str().unwrap().into(),
                    authority_id: "E".into(),
                    authority_epoch: "1".into(),
                    schema_revision: "economic-session/1".into(),
                    reply_namespace: "economic-session/replies".into(),
                    producer_id: format!("E:{x_session}"),
                },
                s: x_runtime::Authority {
                    socket: dir.join("s.sock").to_str().unwrap().into(),
                    authority_id: "S".into(),
                    authority_epoch: "1".into(),
                    schema_revision: "s-session/1".into(),
                    reply_namespace: "s-session/replies".into(),
                    producer_id: format!("S:{x_session}"),
                },
                conditions: conds,
                timeout_ms: 5000,
                max_frame_bytes: 16_777_216,
            };
            let tx = x_conn.transaction().unwrap();
            tx.execute_batch(
                "CREATE TABLE IF NOT EXISTS x_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);",
            )
            .unwrap();
            for (k, v) in [
                ("profile_revision", EXACT_PROFILE_REVISION),
                ("profile_mode", "simulation"),
                ("history_simulation", "true"),
                ("writer_epoch", "1"),
            ] {
                tx.execute(
                    "INSERT INTO x_meta(key, value) VALUES(?1, ?2)",
                    rusqlite::params![k, v],
                )
                .unwrap();
            }
            x_runtime::initialize_in_transaction(&tx, &profile, 1).unwrap();
            tx.commit().unwrap();
            Some(profile)
        };

        let s_object =
            json!({"object_id":"unit-S-object","kind":"UnitStructuralTrustRoot","branch":"RISING"});
        let s_basis = json!({"kind":"FinancialBasis","session_id":SESSION,"session_generation":"1","writer_epoch":"1","pending_revision":false,"commit_ns":"1","snapshot":{"profile_id":"unit","objects":[s_object.clone()]}});
        let (basis_path, _) = save(&dir, "s-basis.json", &s_basis);
        let stub = dir.join("s-stub.sh");
        let script = format!("#!/bin/sh\nexec cat '{basis_path}'\n");
        crate::economic_session::write_test_executable(&stub, &script, 0o755);

        let mut covered = vec![];
        let mut authorities = vec![];
        let mut rights = vec![];
        let mut plans = vec![];
        let mut openings = vec![];
        let mut bindings = vec![];
        let mut routes = vec![];

        for (name, family, fixed, qty, cash, new_qty, price, fee, concurrency) in [
            (
                "alpha",
                alpha_family,
                "12",
                "4",
                "40",
                "2",
                "14",
                "2",
                "single",
            ),
            (
                "beta",
                "family-beta",
                "20",
                "15",
                "50",
                "3",
                "12",
                "4",
                "batched",
            ),
        ] {
            let mut doc = book::tests::document();
            let ev = &mut doc["events"][0];
            ev["family_id"] = json!(family);
            ev["book_identity"] = json!({
                "chong_id": name,
                "symbol": name,
                "op_level": "2",
                "fixed_q": fixed,
                "side": "long"
            });
            ev["observed_existing_book"]["units"] = json!(qty);
            ev["source"]["external_fact_id"] = json!(format!("opening-{name}"));
            ev["allocation_id"] = json!(format!("allocation-{name}"));
            ev["stable_point"] = json!({"profile":"TestOnly","seq":"1","source_ref":"sp"});
            doc["evidence_index"]["fragments"]["sp"] =
                json!([{"json_pointer":"/events/0/stable_point"}]);

            let raw_hash = sha256_hex(canonical_json(&doc).as_bytes());
            let event = &doc["events"][0];
            let fk = book::fact_key(event).unwrap();
            let fh = book::hash(&json!({
                "raw_sha256": raw_hash,
                "json_pointer": "/events/0",
                "event": event,
                "units": doc["units"]
            }));
            // F1：baseline 只覆盖开账，不预列任何未来成交或费用！
            covered
                .push(json!({"fact_key": fk, "fact_hash": fh, "token": format!("token-{name}")}));

            let reference = |id: &str| json!({"authority_id":name,"object_id":id,"revision":"0","content_hash":book::hash(&json!(id))});
            let bind = json!({
                "op":"BindVoice",
                "binding_id":format!("voice-{name}"),
                "evidence_id":name,
                "carrier_ref":reference("unit-carrier"),
                "gamma_ref":reference("unit-gamma"),
                "parent_voice_id":null,
                "sigma":"Long",
                "n":"0",
                "opening_basis":{"fact_key":fk,"expected_fact_hash":fh,"allocation_id":format!("allocation-{name}")}
            });
            let b = json!({
                "evidence_id":name,
                "instrument":name,
                "chong_id":name,
                "operation_level":"2",
                "carrier_ref":bind["carrier_ref"],
                "gamma_ref":bind["gamma_ref"],
                "sigma":"Long",
                "n":"0",
                "parent_voice_id":null,
                "structure_view":{"profile_id":"unit","execution_level":"2","confirmation_level":"3","nest_depth":"1"},
                "opening_source":{"fact_key":fk,"fact_hash":fh,"allocation_id":format!("allocation-{name}"),"raw_sha256":raw_hash,"json_pointer":"/events/0","quantity":qty,"units":doc["units"]}
            });
            let mut artifacts = vec![];
            for artifact in [
                "input",
                "controlled_gammas",
                "carrier_objects",
                "instrument_declaration",
                "opening_raw",
            ] {
                let val = if artifact == "opening_raw" {
                    doc.clone()
                } else {
                    json!({"scope":"unit trust root only, not formal gamma proof","name":artifact})
                };
                let (path, sha) = save(&dir, &format!("{name}-{artifact}.json"), &val);
                artifacts.push(json!({"name":artifact,"path":path,"sha256":sha,"bytes":canonical_json(&val).len().to_string()}));
            }
            let bundle = json!({
                "schema":"voice-binding-authority/1",
                "authority_id":name,
                "source":{"instrument":name,"input_sha256":artifacts[0]["sha256"],"profile_id":"unit","first_confirming_observation_source":"1","clock_mapping":{"kind":"TestOnlyAffineOrdinalToNs","source_origin":"0","nanosecond_origin":"0","nanoseconds_per_ordinal":"1"}},
                "artifacts":artifacts,
                "bindings":[b]
            });
            let (bp, bh) = save(&dir, &format!("{name}-authority.json"), &bundle);
            let (rp, rh) = save(
                &dir,
                &format!("{name}-unit-review.json"),
                &json!({"schema":"voice-binding-independent-verification/1","verdict":"APPROVE_CONTROLLED_VOICE_BINDING","authority_id":name,"bundle_sha256":bh,"artifacts":bundle["artifacts"],"verified_evidence_ids":[name],"scope":"unit trust fixture only; no independent acceptance"}),
            );
            authorities.push(json!({"authority_id":name,"bundle_path":bp,"bundle_sha256":bh,"verification_path":rp,"verification_sha256":rh,"max_bytes":"1048576"}));
            rights.push(json!({"right_id":name,"owner":format!("B:{name}"),"version":"1","amount":cash,"currency":"TEST-CASH","source_ref":format!("TestOnly-privately-owned-cash-original/{name}")}));
            plans.push(json!({
                "decision_id":name,
                "attempt_id":format!("attempt-{name}"),
                "plan_id":format!("plan-{name}"),
                "owner":format!("B:{name}"),
                "voice_binding_id":format!("voice-{name}"),
                "right_id":name,
                "expected_book_version":"2",
                "expected_rights_version":"1",
                "applicant_epoch":"1",
                "applicant_generation":"1",
                "slot_id":"slot",
                "quantity":new_qty,
                "limit_price":price,
                "fee_tail":fee,
                "quantity_source":format!("TestOnly-quantity/{name}"),
                "price_source":format!("TestOnly-price/{name}"),
                "fee_source":format!("TestOnly-tail/{name}"),
                "s_ref":{"object_id":"unit-S-object","object_hash":book::hash(&s_object),"profile_id":"unit"},
                "o_ref":{"operation_id":format!("TestOnly-operation-{name}"),"kind":"TestOnlyCashBuy","source_ref":format!("TestOnly-operation-sheet/{name}"),"s_object_id":"unit-S-object","quantity":new_qty},
                "exact":{
                    "command_id":format!("cmd-{name}"),
                    "logical_order_family":format!("family-{name}"),
                    "chong_id":name,
                    "revision":"1",
                    "first_quantity":new_qty,
                    "allocation_id":format!("alloc-{name}"),
                    "side":"buy",
                    "symbol":name,
                    "projection_manifest":format!("TestOnly-projection/{name}"),
                    "eligibility_ref":format!("S:cmd-{name}"),
                    "concurrency":concurrency
                }
            }));
            routes.push(json!({"chong_id":name,"symbol":name,"operation_level":"2","fixed_q":fixed,"db":dir.join(format!("{name}.db")),"socket":dir.join(format!("{name}.sock"))}));
            openings.push(doc);
            bindings.push(bind);
        }

        let conditions: Vec<Value> = CONDITIONS
            .iter()
            .map(|(id, cap, stage)| {
                json!({
                    "condition_id":id,
                    "authority_revision":cap,
                    "dependency_set":["controlled-dependency"],
                    "invalidation_sources":["controlled-invalidation"],
                    "required_check_stages":[stage],
                    "evidence_refs":["controlled-evidence"],
                    "coverage_proof":"controlled-coverage",
                    "validator_capability":cap,
                    "failure_result":"Denied"
                })
            })
            .collect();
        let domain = |c: &str| json!({"order_kind":"limit","concurrency":c,"allocation_model":"#1349/atomic-slot-wait/v1"});
        let applicants = json!(["alpha", "beta"]);
        let data = json!({
            "schema_revision": FIN6,
            "kind": "TestOnly",
            "source_id": "tb1425-fixture",
            "source_epoch": "1",
            "policy": {
                "policy_id": "TestOnly-cash-cap-100",
                "allocation_policy_id": "#1349/atomic-slot-wait/v1",
                "cap": "100",
                "currency": "TEST-CASH",
                "money_unit": "TEST-CASH",
                "quantity_unit": "TEST-UNIT",
                "quantum": "1",
                "capability_id": "TestOnly-no-leverage-no-venue",
                "model": "TestOnlyUnleveragedCashBuy",
                "valid_through_ns": "100000"
            },
            "baseline": {
                "responsibility_id": "existing20",
                "amount": "20",
                "source_ref": "TestOnly-existing-full-liability-original",
                "covered_facts": covered
            },
            "rights": rights,
            "plans": plans,
            "slots": [{
                "slot_id": "slot",
                "applicants": applicants,
                "input_end": {
                    "kind": "ControlledInputEnd",
                    "source_id": "tb1425-fixture",
                    "source_epoch": "1",
                    "watermark": "2",
                    "complete_request_hash": book::hash(&applicants)
                }
            }],
            "exact_release": {
                "x_target": {"x_id": "X", "x_epoch": "1"},
                "projection_kind": "per_leg",
                "rd11_policy": "controlled-fixture-rd11",
                "rule_revision": "TestOnly-rule/1425",
                "market_dependencies": ["TestOnly-market/1425"],
                "conditions": conditions,
                "model_coverage": {
                    "model_ref": {
                        "model_id": model.model_id,
                        "revision": model.revision,
                        "content_hash": model_hash
                    },
                    "domain_id": "TestOnly-domain/1425",
                    "input_domain": [domain("single")],
                    "unsupported_domains": [domain("batched")]
                }
            }
        });
        let (ip, ih) = save(&dir, "fin-input.json", &data);

        let src_biz = json!({"source_namespace":"test","source_epoch":"one","producer_id":"unit","producer_epoch":"1"});
        let mut auth_biz = src_biz.clone();
        auth_biz["operations"] = json!([
            "ImportResponsibility",
            "CaptureExternal",
            "ApplyAllocation",
            "BindVoice",
            "ReadView",
            "Watch",
            "QueryFact",
            "QueryAllocation",
            "QueryDecision",
            "QueryGrant",
            "QueryVoice",
            "PrepareDecision",
            "Reserve",
            "CommitDecision",
            "MakeDispatchable",
            "ReleaseExact",
            "QueryCommand",
            "QueryReleasedExact"
        ]);
        // X 来源只获准 QueryReleasedExact + CaptureExternal；具名工作方 resolver 独占 ResolveEvidence
        let auth_x = json!({
            "source_namespace":"x-sim",
            "source_epoch":"epoch1",
            "producer_id":"X",
            "producer_epoch":"1",
            "operations":["QueryReleasedExact","CaptureExternal"]
        });
        let auth_resolver = json!({
            "source_namespace":"x-sim",
            "source_epoch":"epoch1",
            "producer_id":"resolver",
            "producer_epoch":"1",
            "operations":["ResolveEvidence"]
        });

        let mut bars = serde_json::Map::new();
        for i in 0..256 {
            let bar = if i < 14 {
                "1"
            } else if i == 14 {
                "2"
            } else {
                "3"
            };
            bars.insert(format!("m-{i}"), json!(bar));
        }
        for name in [
            "release-alpha",
            "capture-fill",
            "capture-fee",
            "resolve-fill",
            "resolve-fee",
            "resolve-batch",
            "apply-fill",
            "apply-fee",
            "apply-wrong-chong",
            "apply-before-resolve",
            "apply-fee-early",
            "resolve-fee-early",
            "resolve-bad",
            "apply-bad-hash",
            "apply-bad-id",
            "capture-extra",
            "resolve-extra",
            "retry-capture-fill",
            "retry-resolve-fill",
            "retry-apply-fill",
            "retry-apply-fee",
            "query",
        ] {
            bars.insert(
                name.into(),
                json!(if name == "release-alpha" { "2" } else { "3" }),
            );
        }

        let manifest = json!({
            "schema_revision": "economic-manifest/1",
            "session_id": SESSION,
            "session_generation": "1",
            "book_revision": book::TB03C_BOOK_V1,
            "e": {"db": dir.join("e.db"), "socket": dir.join("e.sock")},
            "chongs": routes,
            "authorized_sources": [auth_biz, auth_x, auth_resolver],
            "history_simulation_source": {
                "source_namespace": "x-sim",
                "source_epoch": "epoch1",
                "producer_id": "X",
                "producer_epoch": "1",
                "x_db": x_db,
                "model_content_hash": model_hash
            },
            "resources": {
                "max_frame_bytes": "16777216",
                "read_timeout_ms": "1000",
                "write_timeout_ms": "1000",
                "response_timeout_ms": "3000",
                "queue_capacity": "4",
                "max_connections": "4"
            },
            "clock": {
                "kind": "logical-bar/1",
                "bars": {
                    "init": "0",
                    "recover": ["3", "3", "3", "3"],
                    "messages": bars
                }
            },
            "voice_binding": {
                "schema_revision": "voice-binding/1",
                "authorities": authorities
            },
            "finance": {
                "schema_revision": FIN6,
                "input_path": ip,
                "input_sha256": ih,
                "coordinator_source": src_biz,
                "structure": {
                    "binary": stub,
                    "binary_sha256": sha256_hex(script.as_bytes()),
                    "db": dir.join("s.db"),
                    "session_id": SESSION,
                    "session_generation": "1",
                    "writer_epoch": "1"
                }
            }
        });
        let manifest_path = dir.join("manifest.json");
        std::fs::write(&manifest_path, canonical_json(&manifest)).unwrap();
        let configs = vec![
            store::Config::load(&manifest_path, &dir.join("e.db"), None).unwrap(),
            store::Config::load(&manifest_path, &dir.join("alpha.db"), Some("alpha")).unwrap(),
            store::Config::load(&manifest_path, &dir.join("beta.db"), Some("beta")).unwrap(),
        ];
        let mut epochs = vec![];
        let dbs = configs
            .iter()
            .map(|c| {
                epochs.push(book::integer(&store::init(c).unwrap(), "writer_epoch").unwrap());
                store::open(&c.db, false).unwrap().0
            })
            .collect();

        Self {
            _space: space,
            dir,
            configs,
            dbs,
            epochs,
            x_conn,
            x_db_path: x_db,
            x_profile,
            data,
            plans: [plans[0].clone(), plans[1].clone()],
            openings: [openings[0].clone(), openings[1].clone()],
            bindings: [bindings[0].clone(), bindings[1].clone()],
            next: 0,
        }
    }

    fn send_as(
        &mut self,
        owner: usize,
        source: (&str, &str, &str, &str),
        msg: &str,
        payload: Value,
    ) -> Value {
        let e = json!({
            "schema_revision": "economic-session/1",
            "session_id": SESSION,
            "session_generation": "1",
            "source_namespace": source.0,
            "source_epoch": source.1,
            "producer_id": source.2,
            "producer_epoch": source.3,
            "message_id": msg,
            "payload_hash": book::hash(&payload),
            "causal_refs": [],
            "payload": payload
        });
        service::handle(
            &mut self.dbs[owner],
            &self.configs[owner],
            self.epochs[owner],
            self.epochs[E],
            &json!({}),
            &e,
        )["payload"]
            .clone()
    }

    fn biz(&mut self, owner: usize, payload: Value) -> Value {
        let id = format!("m-{}", self.next);
        self.next += 1;
        self.send_as(owner, ("test", "one", "unit", "1"), &id, payload)
    }

    fn biz_named(&mut self, owner: usize, msg: &str, payload: Value) -> Value {
        self.send_as(owner, ("test", "one", "unit", "1"), msg, payload)
    }

    fn x_capture(&mut self, msg: &str, doc: &Value, token: &str) -> Value {
        let p = json!({
            "op": "CaptureExternal",
            "raw_utf8": canonical_json(doc),
            "json_pointer": "/event",
            "token": token,
            "source_event_time": doc["event"]["source"]["source_event_time"]
        });
        self.send_as(E, ("x-sim", "epoch1", "X", "1"), msg, p)
    }

    fn resolve_with_batch(
        &mut self,
        msg: &str,
        evidence_id: &str,
        records: &[&Value],
        cursor: &str,
        x_batch: Option<Value>,
    ) -> Value {
        let covered: Vec<Value> = records
            .iter()
            .map(|r| {
                json!({
                    "fact_key": r["fact_key"],
                    "fact_hash": r["fact_hash"],
                    "token": r["token"]
                })
            })
            .collect();
        let mut p = json!({
            "op": "ResolveEvidence",
            "evidence_id": evidence_id,
            "covered": covered,
            "frontier": {"source_namespace": "x-sim", "source_epoch": "epoch1", "cursor": cursor},
            "dependency_version": "tb1425-deps/1"
        });
        if let Some(xb) = x_batch {
            p["x_batch"] = xb;
        }
        self.send_as(E, ("x-sim", "epoch1", "resolver", "1"), msg, p)
    }

    fn resolve(
        &mut self,
        msg: &str,
        evidence_id: &str,
        records: &[&Value],
        cursor: &str,
        batch_id: &str,
        batch_digest: &str,
    ) -> Value {
        self.resolve_with_batch(
            msg,
            evidence_id,
            records,
            cursor,
            Some(json!({
                "x_id": "X",
                "x_epoch": "1",
                "batch_id": batch_id,
                "batch_receipt_sha256": batch_digest
            })),
        )
    }

    fn batch_receipt_sha256(&self, batch_id: &str) -> String {
        let raw: String = self
            .x_conn
            .query_row(
                "SELECT result FROM x_sim_batches WHERE id=?1",
                [batch_id],
                |r| r.get(0),
            )
            .unwrap();
        sha256_hex(raw.as_bytes())
    }

    fn image(&self, owner: usize) -> Value {
        store::latest(&self.dbs[owner]).unwrap().3
    }

    fn liability_total(&self) -> i64 {
        self.image(E)["finance"]["responsibilities"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| r["amount"].as_str().unwrap().parse::<i64>().unwrap())
            .sum()
    }

    /// 走到 E.ReleaseExact(cmd-alpha) @ bar 2，返回 (release_receipt, grant_alpha_id)
    fn setup_released_alpha(&mut self) -> (Value, String) {
        for (idx, name) in [(ALPHA, "alpha"), (BETA, "beta")] {
            let doc = self.openings[idx - 1].clone();
            let cap = self.biz(
                E,
                json!({"op":"CaptureExternal","raw_utf8":canonical_json(&doc),"json_pointer":"/events/0","token":format!("token-{name}"),"source_event_time":null}),
            );
            assert_eq!(cap["kind"], "Recorded", "{cap}");
            let app = self.biz(
                idx,
                json!({"op":"ApplyAllocation","fact_key":cap["fact_key"],"allocation_id":format!("allocation-{name}"),"expected_fact_hash":cap["fact_hash"]}),
            );
            assert_eq!(app["kind"], "Applied", "{app}");
            let bind = self.bindings[idx - 1].clone();
            let vb = self.biz(idx, bind);
            assert_eq!(vb["kind"], "VoiceBound", "{vb}");
        }
        let imp = self.biz(
            E,
            json!({"op":"ImportResponsibility","responsibility_id":"existing20","writer_epoch":"1"}),
        );
        assert_eq!(imp["record"]["state"], "ResponsibilityImported", "{imp}");
        for (idx, name) in [(ALPHA, "alpha"), (BETA, "beta")] {
            let plan = self.plans[idx - 1].clone();
            let prep = self.biz(
                idx,
                json!({"op":"PrepareDecision","decision_id":name,"plan_hash":book::hash(&plan),"writer_epoch":"1"}),
            );
            assert_eq!(prep["record"]["state"], "Prepared", "{prep}");
        }
        let res = self.biz(
            E,
            json!({"op":"Reserve","slot_id":"slot","request_set_hash":book::hash(&json!(["alpha","beta"])),"writer_epoch":"1"}),
        );
        assert_eq!(res["record"]["state"], "Reserved", "{res}");
        let grants = res["record"]["grants"].as_array().unwrap().clone();
        let grant_of = |d: &str| {
            grants.iter().find(|g| g["decision_id"] == d).unwrap()["grant_id"]
                .as_str()
                .unwrap()
                .to_owned()
        };
        let grant_alpha = grant_of("alpha");
        for (idx, name) in [(ALPHA, "alpha"), (BETA, "beta")] {
            let plan = self.plans[idx - 1].clone();
            let cm = self.biz(
                idx,
                json!({"op":"CommitDecision","decision_id":name,"plan_hash":book::hash(&plan),"grant_id":grant_of(name),"writer_epoch":"1"}),
            );
            assert_eq!(cm["record"]["state"], "Committed", "{cm}");
        }
        let plan_alpha = self.plans[0].clone();
        let disp = self.biz(
            E,
            json!({"op":"MakeDispatchable","decision_id":"alpha","plan_hash":book::hash(&plan_alpha),"writer_epoch":"1"}),
        );
        assert_eq!(disp["record"]["state"], "Dispatchable", "{disp}");

        // 构造 ReleaseExact 请求（与 exact_release_tests 一致）
        let q = &self.plans[0];
        let x = &q["exact"];
        let s = &self.data["exact_release"];
        let change = json!({"kind":"submit","order":{
            "command_id":x["command_id"],"family_id":x["logical_order_family"],"chong_id":x["chong_id"],
            "revision":"1","side":"buy","quantity":q["quantity"],
            "kind":{"kind":"limit","price":q["limit_price"]},
            "eligibility_ref":x["eligibility_ref"],"projection_manifest":x["projection_manifest"]
        }});
        let certificate = json!({
            "rd11_policy": s["rd11_policy"],
            "responsibility_refs": [grant_alpha],
            "structure_dependencies": [format!("{}@{}", q["s_ref"]["object_id"].as_str().unwrap(), q["s_ref"]["object_hash"].as_str().unwrap())],
            "market_dependencies": s["market_dependencies"],
            "rule_revision": s["rule_revision"],
            "conditions": s["conditions"]
        });
        let rel = self.biz_named(
            E,
            "release-alpha",
            json!({
                "op": "ReleaseExact",
                "decision_id": "alpha",
                "command_id": "cmd-alpha",
                "plan_hash": book::hash(&change),
                "certificate": certificate,
                "x_id": "X",
                "x_epoch": "1",
                "writer_epoch": "1"
            }),
        );
        assert_eq!(rel["kind"], "ReleasedExactReceipt", "{rel}");
        assert_eq!(rel["record"]["state"], "ReleasedExact");
        assert_eq!(rel["record"]["release_commit_ns"], "2");
        assert_eq!(self.liability_total(), 90);
        (rel, grant_alpha)
    }

    /// X/3 推进 bar 0..3：通过真实 E `QueryReleasedExact` 接纳放行命令、在 b2（claimed_ns=2，0 经济原件）占用并提交、
    /// 在 b3 产出 (fill, fee) 两件原件；返回 `(fill_doc, fee_doc, b3_receipt_sha256, b2_receipt_sha256)`。
    fn run_x3_to_bar3(&mut self, rel: &Value, order: Order) -> (Value, Value, String, String) {
        let mk_bar = |idx: i64, o: i64, h: i64, l: i64, c: i64| Bar {
            index: idx,
            open: o,
            high: h,
            low: l,
            close: c,
        };
        for idx in [0, 1] {
            x_store::commit_batch(
                &mut self.x_conn,
                &Batch {
                    request_id: format!("b{idx}"),
                    known_frontier_cut: format!("frontier{idx}"),
                    bar: mk_bar(idx, 16, 17, 15, 16),
                    close_changes: vec![],
                    capacity: Capacity::None,
                    scenario_busts: vec![],
                },
            )
            .unwrap();
        }
        let mut b2 = Batch {
            request_id: "b2".into(),
            known_frontier_cut: "frontier2".into(),
            bar: mk_bar(2, 16, 17, 15, 16),
            close_changes: vec![Change::Submit {
                order: order.clone(),
            }],
            capacity: Capacity::None,
            scenario_busts: vec![],
        };
        b2.normalize();
        if let Some(profile) = self.x_profile.clone() {
            // 向 E 走真实 QueryReleasedExact 取得权威放行应答（本条 release_receipt_id 恒为 null）。
            let cmd_val = rel["record"]["command"].clone();
            let cmd_hash = rel["record"]["command_hash"].as_str().unwrap().to_owned();
            let qrel = self.send_as(
                E,
                ("x-sim", "epoch1", "X", "1"),
                "query",
                json!({
                    "op": "QueryReleasedExact",
                    "protocol": x_runtime::AUTHORITY_WIRE,
                    "session_id": profile.session_id,
                    "session_generation": profile.session_generation,
                    "authority_id": "E",
                    "authority_epoch": "1",
                    "command_id": order.command_id,
                    "command_hash": cmd_hash,
                    "command": cmd_val,
                    "release_receipt_id": null
                }),
            );
            let rel_reply = if qrel.get("kind") == Some(&json!("Error")) {
                // 异会话/异化身负控中，X 自己的 DB 持该异会话自洽的 release_evidence
                json!({
                    "protocol": x_runtime::AUTHORITY_WIRE,
                    "session_id": profile.session_id,
                    "session_generation": profile.session_generation,
                    "authority_id": "E",
                    "authority_epoch": "1",
                    "command_id": order.command_id,
                    "command_hash": book::hash(&json!({
                        "command_id": cmd_val["command_id"],
                        "logical_order_family": cmd_val["logical_order_family"],
                        "first_quantity": cmd_val["first_quantity"],
                        "allocation_id": cmd_val["allocation_id"],
                        "session_id": profile.session_id,
                        "session_generation": profile.session_generation,
                        "x_id": cmd_val["x_id"],
                        "x_epoch": cmd_val["x_epoch"],
                        "symbol": cmd_val["symbol"],
                        "projection_kind": cmd_val["projection_kind"],
                        "model_ref": cmd_val["model_ref"],
                        "change": cmd_val["change"],
                        "plan_hash": cmd_val["plan_hash"],
                        "certificate_hash": cmd_val["certificate_hash"],
                        "certificate": cmd_val["certificate"],
                    })),
                    "command": {
                        "command_id": cmd_val["command_id"],
                        "logical_order_family": cmd_val["logical_order_family"],
                        "first_quantity": cmd_val["first_quantity"],
                        "allocation_id": cmd_val["allocation_id"],
                        "session_id": profile.session_id,
                        "session_generation": profile.session_generation,
                        "x_id": cmd_val["x_id"],
                        "x_epoch": cmd_val["x_epoch"],
                        "symbol": cmd_val["symbol"],
                        "projection_kind": cmd_val["projection_kind"],
                        "model_ref": cmd_val["model_ref"],
                        "change": cmd_val["change"],
                        "plan_hash": cmd_val["plan_hash"],
                        "certificate_hash": cmd_val["certificate_hash"],
                        "certificate": cmd_val["certificate"],
                    },
                    "state": "ReleasedExact",
                    "receipt_id": rel["receipt_key"],
                    "release_receipt_id": null,
                    "commit_ns": "2"
                })
            } else {
                assert_eq!(qrel["state"], "ReleasedExact", "{qrel}");
                assert!(qrel["release_receipt_id"].is_null(), "{qrel}");
                assert_eq!(qrel["receipt_id"], rel["receipt_key"], "{qrel}");
                qrel
            };
            let rel_cmd = rel_reply["command"].clone();
            let rel_hash = rel_reply["command_hash"].as_str().unwrap().to_owned();
            let rel_rid = rel_reply["receipt_id"].as_str().unwrap().to_owned();
            let s_exec_reply = json!({
                "protocol": x_runtime::AUTHORITY_WIRE,
                "session_id": profile.session_id,
                "session_generation": profile.session_generation,
                "authority_id": "S",
                "authority_epoch": "1",
                "command_id": order.command_id,
                "command_hash": rel_hash,
                "command": rel_cmd,
                "state": "ExecuteCommitted",
                "receipt_id": order.eligibility_ref,
                "release_receipt_id": rel_rid,
                "commit_ns": "2"
            });
            let exec_ev = json!({"reply": s_exec_reply, "claimed_ns": "2"});
            let accept_clock = json!({"received_ns": "2", "first_known_ns": "2", "commit_ns": "2"});
            let b2_raw = canonical_json(&serde_json::to_value(&b2).unwrap());
            self.x_conn
                .execute(
                    "INSERT INTO x_exact_commands(id,command,release_receipt,state,attempt_batch,accept_clock,release_evidence,execute_evidence) VALUES(?1,?2,?3,'Observed',?4,?5,?6,?7)",
                    rusqlite::params![
                        order.command_id,
                        canonical_json(&rel_cmd),
                        rel_rid,
                        b2_raw,
                        canonical_json(&accept_clock),
                        canonical_json(&rel_reply),
                        canonical_json(&exec_ev),
                    ],
                )
                .unwrap();
        }
        let b2_res = x_store::commit_batch(&mut self.x_conn, &b2).unwrap();
        assert_eq!(b2_res["originals"].as_array().unwrap().len(), 0, "{b2_res}");
        let b3 = x_store::commit_batch(
            &mut self.x_conn,
            &Batch {
                request_id: "b3".into(),
                known_frontier_cut: "frontier3".into(),
                bar: mk_bar(3, 14, 15, 13, 14),
                close_changes: vec![],
                capacity: Capacity::None,
                scenario_busts: vec![],
            },
        )
        .unwrap();
        let originals = b3["originals"].as_array().unwrap();
        assert_eq!(originals.len(), 2, "{b3}");
        if self.x_profile.is_some() {
            // 确认该 X/3 库通过正式冷审（全批重演 + accept + execute_evidence + claimed_ns=2）
            let summary = x_runtime::inspect_history(&self.x_db_path).unwrap();
            assert_eq!(summary["profile_revision"], EXACT_PROFILE_REVISION);
        }
        let b2_sha = self.batch_receipt_sha256("b2");
        let b3_sha = self.batch_receipt_sha256("b3");
        (originals[0].clone(), originals[1].clone(), b3_sha, b2_sha)
    }

    /// 裸 store 推进（仅用于负控：无 X/3 命令接纳与占有链）
    fn run_bare_x_to_bar3(&mut self, order: Order) -> (Value, Value, String) {
        let mk_bar = |idx: i64, o: i64, h: i64, l: i64, c: i64| Bar {
            index: idx,
            open: o,
            high: h,
            low: l,
            close: c,
        };
        for idx in [0, 1] {
            x_store::commit_batch(
                &mut self.x_conn,
                &Batch {
                    request_id: format!("b{idx}"),
                    known_frontier_cut: format!("frontier{idx}"),
                    bar: mk_bar(idx, 16, 17, 15, 16),
                    close_changes: vec![],
                    capacity: Capacity::None,
                    scenario_busts: vec![],
                },
            )
            .unwrap();
        }
        x_store::commit_batch(
            &mut self.x_conn,
            &Batch {
                request_id: "b2".into(),
                known_frontier_cut: "frontier2".into(),
                bar: mk_bar(2, 16, 17, 15, 16),
                close_changes: vec![Change::Submit { order }],
                capacity: Capacity::None,
                scenario_busts: vec![],
            },
        )
        .unwrap();
        let b3 = x_store::commit_batch(
            &mut self.x_conn,
            &Batch {
                request_id: "b3".into(),
                known_frontier_cut: "frontier3".into(),
                bar: mk_bar(3, 14, 15, 13, 14),
                close_changes: vec![],
                capacity: Capacity::None,
                scenario_busts: vec![],
            },
        )
        .unwrap();
        let originals = b3["originals"].as_array().unwrap();
        assert_eq!(originals.len(), 2, "{b3}");
        let b3_sha = self.batch_receipt_sha256("b3");
        (originals[0].clone(), originals[1].clone(), b3_sha)
    }
}

fn alpha_order() -> Order {
    Order {
        command_id: "cmd-alpha".into(),
        family_id: "family-alpha".into(),
        chong_id: "alpha".into(),
        revision: 1,
        side: Side::Buy,
        quantity: 2,
        kind: OrderKind::Limit { price: 14 },
        eligibility_ref: "S:cmd-alpha".into(),
        projection_manifest: "TestOnly-projection/alpha".into(),
    }
}

#[test]
fn tb04f_single_owner_fresh_db_fill_and_fee_resolve_apply_recover_and_negatives() {
    let mut env = Env::build("tb04f-single-owner-ok", "family-alpha");
    let (rel, grant_alpha) = env.setup_released_alpha();
    let (fill_doc, fee_doc, b3_sha, b2_sha) = env.run_x3_to_bar3(&rel, alpha_order());

    // 确认 X 两件原件同游标 3，fill 2*14=28 带 fee=1，独立 fee=1 前件为该 fill
    assert_eq!(fill_doc["event"]["source"]["source_cursor"], "3");
    assert_eq!(fee_doc["event"]["source"]["source_cursor"], "3");
    assert_eq!(fill_doc["event"]["fill"]["amount"], 28);
    assert_eq!(fill_doc["event"]["fill"]["fee"], 1);
    assert_eq!(fee_doc["event"]["amount"], 1);
    assert_eq!(fee_doc["event"]["cause"]["exec_id"], "3:family-alpha:1");

    // 1. E.CaptureExternal 两件（不预列任何未来 fact_key）+ 重试幂等
    let fill_rec = env.x_capture("capture-fill", &fill_doc, "tok-fill");
    assert_eq!(fill_rec["kind"], "Recorded", "{fill_rec}");
    assert_eq!(
        env.x_capture("retry-capture-fill", &fill_doc, "tok-fill"),
        fill_rec
    );
    let fee_rec = env.x_capture("capture-fee", &fee_doc, "tok-fee");
    assert_eq!(fee_rec["kind"], "Recorded", "{fee_rec}");
    assert_eq!(env.image(E)["pending"].as_array().unwrap().len(), 2);

    // 负控 1：Resolve 前 B:alpha.ApplyAllocation 必须被拒且无提交
    let b_before = store::latest(&env.dbs[ALPHA]).unwrap();
    let early_apply = env.biz_named(
        ALPHA,
        "apply-before-resolve",
        json!({"op":"ApplyAllocation","fact_key":fill_rec["fact_key"],"allocation_id":"alloc-alpha","expected_fact_hash":fill_rec["fact_hash"]}),
    );
    assert_eq!(early_apply["kind"], "Error", "{early_apply}");
    assert!(
        early_apply["error"]
            .as_str()
            .unwrap()
            .starts_with("AwaitingDependency"),
        "{early_apply}"
    );
    assert_eq!(store::latest(&env.dbs[ALPHA]).unwrap(), b_before);

    // 负控 1b：缺 x_batch 或指定无经济原件的占有批 b2 或错摘要均被拒，保 Pending
    let e_before = store::latest(&env.dbs[E]).unwrap();
    let no_batch = env.resolve_with_batch("resolve-bad", "ev-no-batch", &[&fill_rec], "3", None);
    assert_eq!(no_batch["kind"], "Error", "{no_batch}");
    assert!(
        no_batch["error"].as_str().unwrap().contains("x_batch"),
        "{no_batch}"
    );
    let wrong_b2 = env.resolve("resolve-bad", "ev-b2", &[&fill_rec], "3", "b2", &b2_sha);
    assert_eq!(wrong_b2["kind"], "Error", "{wrong_b2}");
    assert!(
        wrong_b2["error"]
            .as_str()
            .unwrap()
            .contains("不包含该模拟原件"),
        "{wrong_b2}"
    );
    let bad_digest = env.resolve(
        "resolve-bad",
        "ev-bad-sha",
        &[&fill_rec],
        "3",
        "b3",
        &"0".repeat(64),
    );
    assert_eq!(bad_digest["kind"], "Error", "{bad_digest}");
    assert!(
        bad_digest["error"]
            .as_str()
            .unwrap()
            .starts_with("IdentityConflict"),
        "{bad_digest}"
    );
    assert_eq!(store::latest(&env.dbs[E]).unwrap(), e_before);

    // 负控 2：fill 尚未 Resolve 时先 Resolve fee 必须被拒（AwaitingDependency）
    let early_fee_res = env.resolve(
        "resolve-fee-early",
        "ev-fee-early",
        &[&fee_rec],
        "3",
        "b3",
        &b3_sha,
    );
    assert_eq!(early_fee_res["kind"], "Error", "{early_fee_res}");
    assert!(
        early_fee_res["error"]
            .as_str()
            .unwrap()
            .starts_with("AwaitingDependency"),
        "{early_fee_res}"
    );
    assert_eq!(store::latest(&env.dbs[E]).unwrap(), e_before);

    // 2. E.ResolveEvidence：先 fill 后 fee（占有批 b2 ≠ 结果批 b3；同游标 3 不吞费！）
    let res_fill = env.resolve("resolve-fill", "ev-fill", &[&fill_rec], "3", "b3", &b3_sha);
    assert_eq!(res_fill["kind"], "Resolved", "{res_fill}");
    assert_eq!(
        env.resolve(
            "retry-resolve-fill",
            "ev-fill",
            &[&fill_rec],
            "3",
            "b3",
            &b3_sha
        ),
        res_fill
    );
    let res_fee = env.resolve("resolve-fee", "ev-fee", &[&fee_rec], "3", "b3", &b3_sha);
    assert_eq!(res_fee["kind"], "Resolved", "{res_fee}");

    // 核验 E 分配行及自持 X/3 执行见证（占有批 b2、结果批 b3、E 原放行回执键、release_receipt_id=null）
    let e_img = env.image(E);
    assert!(e_img["pending"].as_array().unwrap().is_empty());
    let rows = e_img["fill_allocations"].as_array().unwrap();
    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0]["source_kind"], "history_sim_fill");
    assert_eq!(rows[0]["command_id"], "cmd-alpha");
    assert_eq!(rows[0]["grant_id"], grant_alpha);
    assert_eq!(rows[0]["responsibility_ref"], grant_alpha);
    assert_eq!(rows[0]["plan_hash"], rel["record"]["plan_hash"]);
    assert_eq!(
        rows[0]["command_plan_hash"],
        rel["record"]["command"]["plan_hash"]
    );
    assert_ne!(rows[0]["plan_hash"], rows[0]["command_plan_hash"]);
    let w0 = &rows[0]["x_execution_witness"];
    assert_eq!(w0["attempt_batch_id"], "b2");
    assert_eq!(w0["attempt_batch_bar_index"], "2");
    assert_eq!(w0["originals_batch_id"], "b3");
    assert_eq!(w0["originals_batch_bar_index"], "3");
    assert_eq!(w0["e_release_receipt_key"], rel["receipt_key"]);
    assert!(w0["x_release_evidence"]["release_receipt_id"].is_null());
    assert_eq!(w0["x_command_state"], "Observed");
    let fill_alloc = &rows[0]["allocations"][0];
    let fill_alloc_id = fill_alloc["allocation_id"].as_str().unwrap().to_owned();
    assert!(fill_alloc_id.starts_with("sim-command:"), "{fill_alloc}");
    assert_ne!(fill_alloc_id, "alloc-alpha");
    assert_ne!(fill_alloc_id, "allocation-alpha");
    assert_eq!(fill_alloc["units"], "2");
    assert_eq!(fill_alloc["acquisition_cash"], "28");
    assert_eq!(fill_alloc["commission"], "0");
    assert_eq!(fill_alloc["fee_deferred_to_cause_fact"], true);

    assert_eq!(rows[1]["source_kind"], "history_sim_fee");
    assert_eq!(rows[1]["original_fact_key"], fill_rec["fact_key"]);
    assert_eq!(rows[1]["original_allocation_id"], fill_alloc_id);
    let fee_alloc = &rows[1]["allocations"][0];
    let fee_alloc_id = fee_alloc["allocation_id"].as_str().unwrap().to_owned();
    assert!(fee_alloc_id.starts_with("sim-command-fee:"), "{fee_alloc}");
    assert_eq!(fee_alloc["units"], "0");
    assert_eq!(fee_alloc["fee_only"], "1");
    assert_eq!(fee_alloc["cause"], "fill");

    // 负控 3：B:alpha 先 Apply fee（前件 fill 尚未 Applied）被拒
    let b_before = store::latest(&env.dbs[ALPHA]).unwrap();
    let early_fee_app = env.biz_named(
        ALPHA,
        "apply-fee-early",
        json!({"op":"ApplyAllocation","fact_key":fee_rec["fact_key"],"allocation_id":fee_alloc_id,"expected_fact_hash":fee_rec["fact_hash"]}),
    );
    assert_eq!(early_fee_app["kind"], "Error", "{early_fee_app}");
    assert!(
        early_fee_app["error"]
            .as_str()
            .unwrap()
            .starts_with("AwaitingDependency"),
        "{early_fee_app}"
    );
    assert_eq!(store::latest(&env.dbs[ALPHA]).unwrap(), b_before);

    // 负控 4：错误重 B:beta 试图 Apply alpha 的成交被拒且 B:beta 完全不动
    let beta_before = store::latest(&env.dbs[BETA]).unwrap();
    let wrong_chong = env.biz_named(
        BETA,
        "apply-wrong-chong",
        json!({"op":"ApplyAllocation","fact_key":fill_rec["fact_key"],"allocation_id":fill_alloc_id,"expected_fact_hash":fill_rec["fact_hash"]}),
    );
    assert_eq!(wrong_chong["kind"], "Error", "{wrong_chong}");
    assert!(
        wrong_chong["error"]
            .as_str()
            .unwrap()
            .starts_with("IdentityConflict"),
        "{wrong_chong}"
    );
    assert_eq!(store::latest(&env.dbs[BETA]).unwrap(), beta_before);

    // 负控 5：用 alloc-alpha / 错 hash 申请被拒
    let bad_id = env.biz_named(
        ALPHA,
        "apply-bad-id",
        json!({"op":"ApplyAllocation","fact_key":fill_rec["fact_key"],"allocation_id":"alloc-alpha","expected_fact_hash":fill_rec["fact_hash"]}),
    );
    assert_eq!(bad_id["kind"], "Error", "{bad_id}");
    assert!(bad_id["error"]
        .as_str()
        .unwrap()
        .starts_with("IdentityConflict"));
    let bad_hash = env.biz_named(
        ALPHA,
        "apply-bad-hash",
        json!({"op":"ApplyAllocation","fact_key":fill_rec["fact_key"],"allocation_id":fill_alloc_id,"expected_fact_hash":"0".repeat(64)}),
    );
    assert_eq!(bad_hash["kind"], "Error", "{bad_hash}");
    assert!(bad_hash["error"]
        .as_str()
        .unwrap()
        .starts_with("IdentityConflict"));

    // 3. B:alpha 唯一应用 fill，再唯一应用 fee
    let fill_app = env.biz_named(
        ALPHA,
        "apply-fill",
        json!({"op":"ApplyAllocation","fact_key":fill_rec["fact_key"],"allocation_id":fill_alloc_id,"expected_fact_hash":fill_rec["fact_hash"]}),
    );
    assert_eq!(fill_app["kind"], "Applied", "{fill_app}");
    let book_mid = env.image(ALPHA)["book"].clone();
    assert_eq!(book_mid["actual_quantity"], "6");
    assert_eq!(book_mid["cost_totals"]["acquisition_cash"], "80028");
    assert_eq!(book_mid["cost_totals"]["commission"], "0");
    assert_eq!(book_mid["cost_totals"]["fee_only"], "0");
    assert_eq!(book_mid["cost_basis"]["K"], "80028");
    assert_eq!(
        book_mid["stable_point"],
        json!({"profile": "logical-bar/1", "seq": "3"})
    );

    let fee_app = env.biz_named(
        ALPHA,
        "apply-fee",
        json!({"op":"ApplyAllocation","fact_key":fee_rec["fact_key"],"allocation_id":fee_alloc_id,"expected_fact_hash":fee_rec["fact_hash"]}),
    );
    assert_eq!(fee_app["kind"], "Applied", "{fee_app}");
    let book_after = env.image(ALPHA)["book"].clone();
    assert_eq!(book_after["actual_quantity"], "6");
    assert_eq!(book_after["cost_totals"]["acquisition_cash"], "80028");
    assert_eq!(book_after["cost_totals"]["commission"], "0");
    assert_eq!(book_after["cost_totals"]["fee_only"], "1");
    assert_eq!(book_after["cost_basis"]["K"], "80029");
    assert_eq!(
        book_after["cost_remaining"],
        json!({"status":"Known","value":"80029"})
    );
    assert_eq!(book_after["principal"]["status"], "NotEvaluable");
    assert_eq!(
        book_after["phase"]["growth_enabled"]["status"],
        "NotEvaluable"
    );

    // B:beta 全程不动；E 总责任维持 90（ADR 0060 §3，不从 28+1 提前减责）
    assert_eq!(store::latest(&env.dbs[BETA]).unwrap(), beta_before);
    assert_eq!(env.liability_total(), 90);

    // 4. 重试幂等：返回完全相同的原回执，不增量
    assert_eq!(
        env.biz_named(
            ALPHA,
            "retry-apply-fill",
            json!({"op":"ApplyAllocation","fact_key":fill_rec["fact_key"],"allocation_id":fill_alloc_id,"expected_fact_hash":fill_rec["fact_hash"]}),
        ),
        fill_app
    );
    assert_eq!(
        env.biz_named(
            ALPHA,
            "retry-apply-fee",
            json!({"op":"ApplyAllocation","fact_key":fee_rec["fact_key"],"allocation_id":fee_alloc_id,"expected_fact_hash":fee_rec["fact_hash"]}),
        ),
        fee_app
    );
    assert_eq!(env.image(ALPHA)["book"], book_after);
    assert_eq!(env.image(ALPHA)["applied"].as_array().unwrap().len(), 3);

    // 5. 关库冷恢复 + 彻底离线重放（先删除 x.db 验证 E/B 冷恢复不依赖活 X，再删除 e.db 验证 B 离线重放不依赖活 E/X！）
    let snap_before: Vec<Value> = (0..3).map(|i| env.image(i)).collect();
    for i in 0..3 {
        store::audit(&env.dbs[i], &env.configs[i]).unwrap();
    }
    env.dbs.clear();
    // 删除 x.db，证明 E 与 B 冷恢复完全离线、不依赖活 X！
    drop(std::mem::replace(
        &mut env.x_conn,
        rusqlite::Connection::open_in_memory().unwrap(),
    ));
    std::fs::remove_file(&env.x_db_path).unwrap();
    for i in 0..3 {
        let rec = store::recover(&env.configs[i]).unwrap();
        assert_eq!(rec["kind"], "Recovered", "{rec}");
        env.epochs[i] = book::integer(&rec, "writer_epoch").unwrap();
        let (db, _) = store::open(&env.configs[i].db, false).unwrap();
        store::audit(&db, &env.configs[i]).unwrap();
        env.dbs.push(db);
    }
    let snap_after: Vec<Value> = (0..3).map(|i| env.image(i)).collect();
    assert_eq!(snap_before, snap_after, "冷恢复后三域业务镜像逐值相等");
    // 进一步删除 e.db（及 WAL/SHM），证明 B:alpha 完整离线重放既不依赖活 X 也不依赖活 E！
    env.dbs.clear();
    for suffix in ["", "-wal", "-shm"] {
        let p = env.dir.join(format!("e.db{suffix}"));
        if p.exists() {
            std::fs::remove_file(&p).unwrap();
        }
    }
    let rec_alpha = store::recover(&env.configs[ALPHA]).unwrap();
    assert_eq!(rec_alpha["kind"], "Recovered", "{rec_alpha}");
    let (alpha_db, _) = store::open(&env.configs[ALPHA].db, false).unwrap();
    store::audit(&alpha_db, &env.configs[ALPHA]).unwrap();
    assert_eq!(store::latest(&alpha_db).unwrap().3, snap_before[ALPHA]);
}

#[test]
fn tb04f_bare_store_and_cross_session_x_keep_pending_and_block_b_applied() {
    // 反例 1（REVIEW #1）：裸撮合 store（无 X/3 x_meta / authority_profile / x_exact_commands）
    // 首件 CaptureExternal 仍按原合同记录事实为 Pending，但 ResolveEvidence 必须被拒、保 Pending、B 不可 Applied！
    let mut bare = Env::build_bare_x("tb04f-bare-store-neg", "family-alpha");
    let _ = bare.setup_released_alpha();
    let (fill_doc, fee_doc, b3_sha) = bare.run_bare_x_to_bar3(alpha_order());
    let fill_rec = bare.x_capture("capture-fill", &fill_doc, "tok-fill");
    assert_eq!(fill_rec["kind"], "Recorded", "{fill_rec}");
    let fee_rec = bare.x_capture("capture-fee", &fee_doc, "tok-fee");
    assert_eq!(fee_rec["kind"], "Recorded", "{fee_rec}");
    assert_eq!(bare.image(E)["pending"].as_array().unwrap().len(), 2);

    let e_before = store::latest(&bare.dbs[E]).unwrap();
    let rej = bare.resolve("resolve-fill", "ev-bare", &[&fill_rec], "3", "b3", &b3_sha);
    assert_eq!(rej["kind"], "Error", "{rej}");
    assert!(
        rej["error"]
            .as_str()
            .unwrap()
            .starts_with("MissingDependency"),
        "bare store resolve must fail MissingDependency: {rej}"
    );
    assert_eq!(store::latest(&bare.dbs[E]).unwrap(), e_before);
    assert_eq!(bare.image(E)["pending"].as_array().unwrap().len(), 2);

    let b_before = store::latest(&bare.dbs[ALPHA]).unwrap();
    let app = bare.biz_named(
        ALPHA,
        "apply-before-resolve",
        json!({"op":"ApplyAllocation","fact_key":fill_rec["fact_key"],"allocation_id":"alloc-alpha","expected_fact_hash":fill_rec["fact_hash"]}),
    );
    assert_eq!(app["kind"], "Error", "{app}");
    assert!(
        app["error"]
            .as_str()
            .unwrap()
            .starts_with("AwaitingDependency"),
        "{app}"
    );
    assert_eq!(store::latest(&bare.dbs[ALPHA]).unwrap(), b_before);

    // 反例 2：异会话 X/3 库（虽有完整 X/3 表和相同 command_id，但 session_id 不同）必须被拒、保 Pending！
    let mut other_sess = Env::build_with_x(
        "tb04f-cross-session-neg",
        "family-alpha",
        false,
        "other-session",
        "1",
    );
    let (rel_os, _) = other_sess.setup_released_alpha();
    let (os_fill, _, os_b3_sha, _) = other_sess.run_x3_to_bar3(&rel_os, alpha_order());
    let os_rec = other_sess.x_capture("capture-fill", &os_fill, "tok-fill");
    assert_eq!(os_rec["kind"], "Recorded", "{os_rec}");
    let os_rej = other_sess.resolve(
        "resolve-fill",
        "ev-other-sess",
        &[&os_rec],
        "3",
        "b3",
        &os_b3_sha,
    );
    assert_eq!(os_rej["kind"], "Error", "{os_rej}");
    assert!(
        os_rej["error"].as_str().unwrap().contains("会话或化身不同"),
        "cross-session X must reject: {os_rej}"
    );
    assert_eq!(other_sess.image(E)["pending"].as_array().unwrap().len(), 1);

    // 反例 3：同会话但 X/3 中该命令绑定了另一笔 E 放行回执键，必须被拒、保 Pending！
    let mut wrong_rel = Env::build("tb04f-wrong-release-neg", "family-alpha");
    let (rel_wr, _) = wrong_rel.setup_released_alpha();
    let (wr_fill, _, wr_b3_sha, _) = wrong_rel.run_x3_to_bar3(&rel_wr, alpha_order());
    // 篡改 X 中该命令的 release_receipt 与 release_evidence.receipt_id 为另一放行回执键
    let fake_rid = "tb03b-finance/6:ReleaseExact:0000000000000000000000000000000000000000000000000000000000000000";
    let (rel_ev_raw, exec_ev_raw): (String, String) = wrong_rel
        .x_conn
        .query_row(
            "SELECT release_evidence, execute_evidence FROM x_exact_commands WHERE id='cmd-alpha'",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    let mut rel_ev: Value = serde_json::from_str(&rel_ev_raw).unwrap();
    let mut exec_ev: Value = serde_json::from_str(&exec_ev_raw).unwrap();
    rel_ev["receipt_id"] = json!(fake_rid);
    exec_ev["reply"]["release_receipt_id"] = json!(fake_rid);
    wrong_rel
        .x_conn
        .execute(
            "UPDATE x_exact_commands SET release_receipt=?1, release_evidence=?2, execute_evidence=?3 WHERE id='cmd-alpha'",
            rusqlite::params![fake_rid, canonical_json(&rel_ev), canonical_json(&exec_ev)],
        )
        .unwrap();
    let wr_rec = wrong_rel.x_capture("capture-fill", &wr_fill, "tok-fill");
    assert_eq!(wr_rec["kind"], "Recorded", "{wr_rec}");
    let wr_rej = wrong_rel.resolve(
        "resolve-fill",
        "ev-wrong-rel",
        &[&wr_rec],
        "3",
        "b3",
        &wr_b3_sha,
    );
    assert_eq!(wr_rej["kind"], "Error", "{wr_rej}");
    assert!(
        wr_rej["error"]
            .as_str()
            .unwrap()
            .starts_with("IdentityConflict"),
        "wrong E release receipt must reject: {wr_rej}"
    );
    assert_eq!(wrong_rel.image(E)["pending"].as_array().unwrap().len(), 1);
}

#[test]
fn tb04f_single_owner_batch_resolve_and_wrong_command_over_qty_family_mismatch_negatives() {
    // 子例 A：裸 store 构造超出 grant 数量的模拟成交被拒（并由 X/3 因果链 + grant 数量上限双重保护）
    let mut env = Env::build_bare_x("tb04f-batch-and-bounds", "family-alpha");
    let _ = env.setup_released_alpha();
    let mut over_order = alpha_order();
    over_order.quantity = 3;
    let (over_fill, _over_fee, over_b3_sha) = env.run_bare_x_to_bar3(over_order);
    let rec = env.x_capture("capture-fill", &over_fill, "tok-over");
    assert_eq!(rec["kind"], "Recorded", "{rec}");
    let e_before = store::latest(&env.dbs[E]).unwrap();
    let rej = env.resolve("resolve-bad", "ev-over", &[&rec], "3", "b3", &over_b3_sha);
    assert_eq!(rej["kind"], "Error", "{rej}");
    assert_eq!(store::latest(&env.dbs[E]).unwrap(), e_before);

    // 子例 B：未知 command_id（无 ReleasedExact 记录）必须保留 Pending 并返回原 MissingDependency
    let mut env_cmd = Env::build_bare_x("tb04f-unknown-cmd", "family-alpha");
    let _ = env_cmd.setup_released_alpha();
    let mut foreign = alpha_order();
    foreign.command_id = "cmd-not-released".into();
    let (foreign_fill, _, foreign_b3_sha) = env_cmd.run_bare_x_to_bar3(foreign);
    let frec = env_cmd.x_capture("capture-fill", &foreign_fill, "tok-foreign");
    assert_eq!(frec["kind"], "Recorded", "{frec}");
    let frej = env_cmd.resolve(
        "resolve-bad",
        "ev-foreign",
        &[&frec],
        "3",
        "b3",
        &foreign_b3_sha,
    );
    assert_eq!(frej["kind"], "Error", "{frej}");
    assert!(
        frej["error"]
            .as_str()
            .unwrap()
            .starts_with("MissingDependency：模拟外部事实缺命令归属"),
        "{frej}"
    );

    // 子例 C：真实 X/3 同批 ResolveEvidence([fill, fee]) + B:alpha 开账 family_id 与命令不符 → Unmatched(family_mismatch)，
    // 且后续费用因前件未 Applied 被 AwaitingDependency 挡住
    let mut env_fam = Env::build("tb04f-family-mismatch", "family-other");
    let (rel_fam, _) = env_fam.setup_released_alpha();
    let (fill_doc, fee_doc, fam_b3_sha, _) = env_fam.run_x3_to_bar3(&rel_fam, alpha_order());
    let fill_rec = env_fam.x_capture("capture-fill", &fill_doc, "tok-fill");
    let fee_rec = env_fam.x_capture("capture-fee", &fee_doc, "tok-fee");
    let batch = env_fam.resolve(
        "resolve-batch",
        "ev-batch",
        &[&fill_rec, &fee_rec],
        "3",
        "b3",
        &fam_b3_sha,
    );
    assert_eq!(batch["kind"], "Resolved", "{batch}");
    let rows = env_fam.image(E)["fill_allocations"]
        .as_array()
        .unwrap()
        .clone();
    let fill_aid = rows[0]["allocations"][0]["allocation_id"]
        .as_str()
        .unwrap()
        .to_owned();
    let fee_aid = rows[1]["allocations"][0]["allocation_id"]
        .as_str()
        .unwrap()
        .to_owned();
    let unmatched = env_fam.biz_named(
        ALPHA,
        "apply-fill",
        json!({"op":"ApplyAllocation","fact_key":fill_rec["fact_key"],"allocation_id":fill_aid,"expected_fact_hash":fill_rec["fact_hash"]}),
    );
    assert_eq!(unmatched["kind"], "Unmatched", "{unmatched}");
    assert_eq!(env_fam.image(ALPHA)["book"]["actual_quantity"], "4");
    assert_eq!(
        env_fam.image(ALPHA)["unmatched"][0]["reason_code"],
        "family_mismatch"
    );
    let fee_blocked = env_fam.biz_named(
        ALPHA,
        "apply-fee",
        json!({"op":"ApplyAllocation","fact_key":fee_rec["fact_key"],"allocation_id":fee_aid,"expected_fact_hash":fee_rec["fact_hash"]}),
    );
    assert_eq!(fee_blocked["kind"], "Error", "{fee_blocked}");
    assert!(
        fee_blocked["error"]
            .as_str()
            .unwrap()
            .starts_with("AwaitingDependency"),
        "{fee_blocked}"
    );
    store::audit(&env_fam.dbs[ALPHA], &env_fam.configs[ALPHA]).unwrap();
}

#[test]
fn tb04f_single_owner_refuses_fin5_without_version_relaxation() {
    let mut env = Env::build("tb04f-fin5-refused", "family-alpha");
    let (rel, _) = env.setup_released_alpha();
    let expected_hash = book::hash(&serde_json::to_value(sim_model()).unwrap());
    assert_eq!(
        rel["record"]["command"]["model_ref"]["content_hash"],
        expected_hash
    );
    let (fill_doc, _, b3_sha, _) = env.run_x3_to_bar3(&rel, alpha_order());
    let fill_rec = env.x_capture("capture-fill", &fill_doc, "tok-fill");
    assert_eq!(fill_rec["kind"], "Recorded", "{fill_rec}");

    // 模拟将配置/图像降格为 tb03b-finance/5：check_pending 与 resolve 均必须显式按 VersionUnsupported 拒绝，
    // 绝不放宽版号或承接无命令内 model_ref 绑定的 /5 域。
    let mut fin5_cfg = env.configs[E].clone();
    fin5_cfg.manifest["finance"]["schema_revision"] = json!("tb03b-finance/5");
    let e_img = env.image(E);
    let fact = store::row(&env.dbs[E], "facts", fill_rec["fact_key"].as_str().unwrap())
        .unwrap()
        .unwrap();
    let covered = vec![json!({
        "fact_key": fill_rec["fact_key"],
        "fact_hash": fill_rec["fact_hash"],
        "token": "tok-fill"
    })];
    let frontier = json!({"source_namespace":"x-sim","source_epoch":"epoch1","cursor":"3"});
    let err_pending =
        super::tb03c_sim_resolve::check_pending(&fin5_cfg, &e_img, &covered, &fact, &frontier, 3)
            .unwrap_err();
    assert!(
        err_pending.starts_with("VersionUnsupported"),
        "expected VersionUnsupported from check_pending, got: {err_pending}"
    );

    let mut fin5_img = e_img.clone();
    fin5_img["finance"]["schema_revision"] = json!("tb03b-finance/5");
    let dummy_payload = json!({
        "x_batch": {"x_id": "X", "x_epoch": "1", "batch_id": "b3", "batch_receipt_sha256": b3_sha}
    });
    let err_resolve = super::tb03c_sim_resolve::resolve(
        &fin5_cfg,
        &mut fin5_img,
        &fact,
        "ev-fin5",
        &dummy_payload,
        None,
    )
    .unwrap_err();
    assert!(
        err_resolve.starts_with("VersionUnsupported"),
        "expected VersionUnsupported from resolve, got: {err_resolve}"
    );
}
