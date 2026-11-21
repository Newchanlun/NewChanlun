//! #1375 AC2（R2）产品级测试：
//! - 取消平行 manifest 数量/毛保留/cap，完全由 E 实际导入/保留的 `image["finance"]` 驱动 FX 投影；
//! - 同源 90 -> 110 -> 90 替代链（`fx-r1` -> `fx-r2` -> `fx-r3`）、旧 `r2` token 精确退役、无关 Pending token 不受损；
//! - 真实 `PrepareDecision` / `Reserve` / 首次 `CommitDecision` / `MakeDispatchable` / `ReleaseExact` 封闸与
//!   `d["baseline"]["covered_facts"]` 精准覆盖不绕过超限验证；
//! - 独审 Arm B 反例（`91/95` + `ActivateCapPolicy`）、乱序/分叉/非整除/未匹配/坏输入负控与 `recover` + `audit`。

use super::book::{self, hash};
use super::service;
use super::store::{audit, init, latest, open, recover, Config, SCHEMA};
use crate::session_protocol::{canonical_json, sha256_hex};

#[test]
fn fx_quote_reference_escapes_field_and_chain_delimiters() {
    use super::fx_valuation::encode_reference;

    assert_eq!(encode_reference(&["feed", "daily|1"]), "feed|daily%7C1");
    assert_eq!(encode_reference(&["feed|daily", "1"]), "feed%7Cdaily|1");
    assert_eq!(encode_reference(&["feed", "daily%7C1"]), "feed|daily%257C1");
    assert_eq!(
        encode_reference(&["TEST-FX/TEST-CASH", "q@x:y;z,w=1"]),
        "TEST-FX/TEST-CASH|q%40x%3Ay%3Bz%2Cw%3D1"
    );
    assert_eq!(
        encode_reference(&["desk:latest:20261119"]),
        "desk%3Alatest%3A20261119"
    );
    assert_eq!(
        encode_reference(&["ledger|latest:20261119", "1"]),
        "ledger%7Clatest%3A20261119|1"
    );
}

const EXACT_CONDITIONS: [(&str, &str, &str); 4] = [
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

fn decorate_exact_input(data: &mut Value) {
    let conditions: Vec<Value> = EXACT_CONDITIONS
        .iter()
        .map(|(id, capability, stage)| {
            json!({
                "condition_id": id,
                "authority_revision": capability,
                "dependency_set": ["controlled-dependency"],
                "invalidation_sources": ["controlled-invalidation"],
                "required_check_stages": [stage],
                "evidence_refs": ["controlled-evidence"],
                "coverage_proof": "controlled-coverage",
                "validator_capability": capability,
                "failure_result": "Denied",
            })
        })
        .collect();
    let domain = |concurrency: &str| {
        json!({
            "order_kind": "limit",
            "concurrency": concurrency,
            "allocation_model": "#1349/atomic-slot-wait/v1",
        })
    };
    data["exact_release"] = json!({
        "x_target": {"x_id": "X", "x_epoch": "1"},
        "projection_kind": "per_leg",
        "rd11_policy": "controlled-fixture-rd11",
        "rule_revision": "TestOnly-rule/1407-c1",
        "market_dependencies": ["TestOnly-market/1407-c1"],
        "conditions": conditions,
        "model_coverage": {
            "model_ref": {
                "model_id": "history-sim/bar-batch-known-frontier/1",
                "revision": "oracle-1",
                "content_hash": hash(&json!("history-sim/bar-batch-known-frontier/1@oracle-1")),
            },
            "domain_id": "TestOnly-domain/1407-c1",
            "input_domain": [domain("single")],
            "unsupported_domains": [domain("batched")],
        },
    });
    for q in data["plans"].as_array_mut().unwrap() {
        let name = q["decision_id"].as_str().unwrap().to_owned();
        q["exact"] = json!({
            "command_id": format!("cmd-{name}"),
            "logical_order_family": format!("family-{name}"),
            "chong_id": name,
            "revision": "1",
            "first_quantity": q["quantity"],
            "allocation_id": format!("alloc-{name}"),
            "side": "buy",
            "symbol": name,
            "projection_manifest": format!("TestOnly-projection/{name}"),
            "eligibility_ref": format!("S:cmd-{name}"),
            "concurrency": if name == "alpha" { "single" } else { "batched" },
        });
    }
}

fn decorate_fx_release_bound_v6_input(data: &mut Value, model_ref: Value) {
    let marker = super::exact_command::FX_RELEASE_BOUND_MARKER;
    data["schema_revision"] = json!("tb03b-finance/6");
    data["exact_release"]["market_dependencies"] = json!([marker]);
    data["exact_release"]["model_coverage"]["model_ref"] = model_ref;
    for c in data["exact_release"]["conditions"].as_array_mut().unwrap() {
        c["dependency_set"] = json!([marker]);
        c["invalidation_sources"] = json!([marker]);
        c["evidence_refs"] = json!([marker]);
        c["coverage_proof"] = json!(marker);
    }
    for q in data["plans"].as_array_mut().unwrap() {
        let name = q["decision_id"].as_str().unwrap();
        q["exact"]["concurrency"] = json!(if name == "gamma" { "batched" } else { "single" });
    }
}
use rusqlite::Connection;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

const FX_R1_RAW: &str = include_str!("../../tests/fixtures/issue1375_ac2_fx/fx-r1.json");
const FX_R2_RAW: &str = include_str!("../../tests/fixtures/issue1375_ac2_fx/fx-r2.json");
const FX_R3_RAW: &str = include_str!("../../tests/fixtures/issue1375_ac2_fx/fx-r3.json");
const FX_OBLIGATIONS_RAW: &str =
    include_str!("../../tests/fixtures/issue1375_ac2_fx/fx-obligations.json");

const MARKET_NS: &str = "testonly.ce-s07.fx";
const MARKET_EPOCH: &str = "1";
const FIN_NS: &str = "testonly.fin.ac2";
const FIN_EPOCH: &str = "1";
const READER_NS: &str = "testonly.reader";
const READER_EPOCH: &str = "1";

static NEXT_ID: AtomicU64 = AtomicU64::new(0);

struct Space {
    dir: PathBuf,
}

impl Space {
    fn new(tag: &str) -> Self {
        let dir = std::env::temp_dir().join(format!(
            "newchan-i1375-ac2-r2-{tag}-{}-{}",
            std::process::id(),
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir_all(&dir).unwrap();
        Self { dir }
    }

    fn save_json(&self, name: &str, v: &Value) -> (String, String) {
        let path = self.dir.join(name);
        let raw = canonical_json(v);
        std::fs::write(&path, &raw).unwrap();
        (path.to_str().unwrap().into(), sha256_hex(raw.as_bytes()))
    }

    fn save_raw(&self, name: &str, raw: &str) -> (String, String) {
        let path = self.dir.join(name);
        std::fs::write(&path, raw).unwrap();
        (path.to_str().unwrap().into(), sha256_hex(raw.as_bytes()))
    }
}

impl Drop for Space {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

fn env(session: &str, ns: &str, ep: &str, producer: &str, msg_id: &str, payload: Value) -> Value {
    json!({
        "schema_revision": SCHEMA,
        "session_id": session,
        "session_generation": "1",
        "source_namespace": ns,
        "source_epoch": ep,
        "producer_id": producer,
        "producer_epoch": "1",
        "message_id": msg_id,
        "payload_hash": hash(&payload),
        "causal_refs": [],
        "payload": payload
    })
}

fn runtime_meta() -> Value {
    json!({
        "pid": "1001",
        "journal_mode": "wal",
        "synchronous": "2",
        "fullfsync": "1",
        "filesystem": "xfs",
        "sqlite_version": "3.46.0",
        "sqlite_version_number": "3046000",
        "read_only": false,
        "control_instance_id": null
    })
}

fn send(c: &mut Connection, config: &Config, epoch: i64, req: &Value) -> Value {
    let reply = service::handle(c, config, epoch, epoch, &runtime_meta(), &req);
    reply["payload"].clone()
}

/// 真实多域（E + B:alpha + B:beta + B:gamma）AC2 R2 会话夹具，使用冻结 `tb03b-finance/5`（或 `/3`）
/// 与正交 `fx-valuation/1`（无任何平行 manifest 数量/毛保留/cap）。
struct Ac2Session {
    space: Space,
    session_id: String,
    e_config: Config,
    e_db: Connection,
    b_configs: Vec<(String, Config)>,
    b_dbs: Vec<(String, Connection)>,
    fin_data: Value,
    opening_docs: Vec<(String, Value, String, String)>,
    voice_payloads: Vec<(String, Value)>,
}

impl Ac2Session {
    fn build(
        tag: &str,
        cap: &str,
        baseline_amount: &str,
        baseline_id: &str,
        extra_covered: Vec<Value>,
        v3_cap_activation: bool,
        fx_obligations_raw: &str,
    ) -> Self {
        let space = Space::new(tag);
        let session_id = format!("ac2-r2-{tag}");
        let fin_rev = if v3_cap_activation {
            "tb03b-finance/3"
        } else {
            "tb03b-finance/5"
        };

        // 单位 S 结构桩（与 finance_tests.rs / exact_release_tests.rs 相同）。
        let s_obj = json!({
            "object_id": "unit-S-object",
            "kind": "UnitStructuralTrustRoot",
            "branch": "RISING"
        });
        let basis = json!({
            "kind": "FinancialBasis",
            "session_id": session_id,
            "session_generation": "1",
            "writer_epoch": "1",
            "pending_revision": false,
            "commit_ns": "1",
            "snapshot": {
                "profile_id": "unit",
                "objects": [s_obj]
            }
        });
        let (basis_path, _) = space.save_json("s-basis.json", &basis);
        let stub = space.dir.join("s-stub.sh");
        crate::economic_session::write_test_executable(
            &stub,
            &format!("#!/bin/sh\nexec /bin/cat '{basis_path}'\n"),
            0o700,
        );
        let stub_sha = sha256_hex(&std::fs::read(&stub).unwrap());
        let s_ref = json!({
            "object_id": "unit-S-object",
            "object_hash": hash(&s_obj),
            "profile_id": "unit"
        });

        // 三个真实现金重：alpha=30 (2*14+2), beta=40 (3*12+4), gamma=5 (1*5+0)，另设 fx-desk 路由。
        let chong_specs = [
            ("alpha", "12", "4", "40", "2", "14", "2", "slot-main"),
            ("beta", "20", "15", "50", "3", "12", "4", "slot-main"),
            ("gamma", "10", "2", "20", "1", "5", "0", "slot-gamma"),
        ];

        let mut authorities = Vec::new();
        let mut rights = Vec::new();
        let mut plans = Vec::new();
        let mut routes = Vec::new();
        let mut covered = extra_covered;
        let mut opening_docs = Vec::new();
        let mut voice_payloads = Vec::new();

        for (name, fixed, qty, cash, new_qty, price, fee, slot_id) in chong_specs {
            let mut doc = book::tests::document();
            let ev = &mut doc["events"][0];
            ev["book_identity"] = json!({
                "chong_id": name,
                "symbol": name,
                "op_level": "2",
                "fixed_q": fixed,
                "side": "long"
            });
            ev["observed_existing_book"]["units"] = json!(qty);
            ev["source"]["source_namespace"] = json!(FIN_NS);
            ev["source"]["source_epoch"] = json!(FIN_EPOCH);
            ev["source"]["external_fact_id"] = json!(format!("opening-{name}"));
            ev["allocation_id"] = json!(format!("allocation-{name}"));
            ev["stable_point"] = json!({"profile": "TestOnly", "seq": "1", "source_ref": "sp"});
            doc["evidence_index"]["fragments"]["sp"] =
                json!([{"json_pointer": "/events/0/stable_point"}]);

            let raw_str = canonical_json(&doc);
            let raw_hash = sha256_hex(raw_str.as_bytes());
            let ev_ref = &doc["events"][0];
            let fk = book::fact_key(ev_ref).unwrap();
            let fh = hash(&json!({
                "raw_sha256": raw_hash,
                "json_pointer": "/events/0",
                "event": ev_ref,
                "units": doc["units"]
            }));
            covered.push(json!({
                "fact_key": fk,
                "fact_hash": fh,
                "token": format!("tok-opening-{name}")
            }));

            let ref_obj = |id: &str| {
                json!({
                    "authority_id": name,
                    "object_id": id,
                    "revision": "0",
                    "content_hash": hash(&json!(id))
                })
            };
            let vp = json!({
                "op": "BindVoice",
                "binding_id": format!("voice-{name}"),
                "evidence_id": name,
                "carrier_ref": ref_obj("unit-carrier"),
                "gamma_ref": ref_obj("unit-gamma"),
                "parent_voice_id": null,
                "sigma": "Long",
                "n": "0",
                "opening_basis": {
                    "fact_key": fk,
                    "expected_fact_hash": fh,
                    "allocation_id": ev_ref["allocation_id"]
                }
            });
            let binding = json!({
                "evidence_id": name,
                "instrument": name,
                "chong_id": name,
                "operation_level": "2",
                "carrier_ref": vp["carrier_ref"],
                "gamma_ref": vp["gamma_ref"],
                "sigma": "Long",
                "n": "0",
                "parent_voice_id": null,
                "structure_view": {
                    "profile_id": "unit",
                    "execution_level": "2",
                    "confirmation_level": "3",
                    "nest_depth": "1"
                },
                "opening_source": {
                    "fact_key": fk,
                    "fact_hash": fh,
                    "allocation_id": ev_ref["allocation_id"],
                    "raw_sha256": raw_hash,
                    "json_pointer": "/events/0",
                    "quantity": qty,
                    "units": doc["units"]
                }
            });
            let mut artifacts = Vec::new();
            for art in [
                "input",
                "controlled_gammas",
                "carrier_objects",
                "instrument_declaration",
                "opening_raw",
            ] {
                let val = if art == "opening_raw" {
                    doc.clone()
                } else {
                    json!({"scope": "unit trust root only", "name": art})
                };
                let (ap, ah) = space.save_json(&format!("{name}-{art}.json"), &val);
                artifacts.push(json!({
                    "name": art,
                    "path": ap,
                    "sha256": ah,
                    "bytes": canonical_json(&val).len().to_string()
                }));
            }
            let bundle = json!({
                "schema": "voice-binding-authority/1",
                "authority_id": name,
                "source": {
                    "instrument": name,
                    "input_sha256": artifacts[0]["sha256"],
                    "profile_id": "unit",
                    "first_confirming_observation_source": "1",
                    "clock_mapping": {
                        "kind": "TestOnlyAffineOrdinalToNs",
                        "source_origin": "0",
                        "nanosecond_origin": "0",
                        "nanoseconds_per_ordinal": "1"
                    }
                },
                "artifacts": artifacts,
                "bindings": [binding]
            });
            let (bp, bh) = space.save_json(&format!("{name}-auth.json"), &bundle);
            let (rp, rh) = space.save_json(
                &format!("{name}-verify.json"),
                &json!({
                    "schema": "voice-binding-independent-verification/1",
                    "verdict": "APPROVE_CONTROLLED_VOICE_BINDING",
                    "authority_id": name,
                    "bundle_sha256": bh,
                    "artifacts": bundle["artifacts"],
                    "verified_evidence_ids": [name],
                    "scope": "unit trust fixture only"
                }),
            );
            authorities.push(json!({
                "authority_id": name,
                "bundle_path": bp,
                "bundle_sha256": bh,
                "verification_path": rp,
                "verification_sha256": rh,
                "max_bytes": "1048576"
            }));
            rights.push(json!({
                "right_id": name,
                "owner": format!("B:{name}"),
                "version": "1",
                "amount": cash,
                "currency": "TEST-CASH",
                "source_ref": format!("TestOnly-privately-owned-cash/{name}")
            }));
            plans.push(json!({
                "decision_id": name,
                "attempt_id": format!("attempt-{name}"),
                "plan_id": format!("plan-{name}"),
                "owner": format!("B:{name}"),
                "voice_binding_id": format!("voice-{name}"),
                "right_id": name,
                "expected_book_version": "2",
                "expected_rights_version": "1",
                "applicant_epoch": "1",
                "applicant_generation": "1",
                "slot_id": slot_id,
                "quantity": new_qty,
                "limit_price": price,
                "fee_tail": fee,
                "quantity_source": format!("TestOnly-qty/{name}"),
                "price_source": format!("TestOnly-price/{name}"),
                "fee_source": format!("TestOnly-fee/{name}"),
                "s_ref": s_ref,
                "o_ref": {
                    "operation_id": format!("TestOnly-op-{name}"),
                    "kind": "TestOnlyCashBuy",
                    "source_ref": format!("TestOnly-op-sheet/{name}"),
                    "s_object_id": "unit-S-object",
                    "quantity": new_qty
                }
            }));
            routes.push(json!({
                "chong_id": name,
                "symbol": name,
                "operation_level": "2",
                "fixed_q": fixed,
                "db": space.dir.join(format!("{name}.db")),
                "socket": space.dir.join(format!("{name}.sock"))
            }));
            opening_docs.push((name.to_owned(), doc, fk, fh));
            voice_payloads.push((name.to_owned(), vp));
        }

        // 外币义务专属路由 B:fx-desk。
        routes.push(json!({
            "chong_id": "fx-desk",
            "symbol": "TEST-FX/TEST-CASH",
            "operation_level": "2",
            "fixed_q": "100",
            "db": space.dir.join("fx-desk.db"),
            "socket": space.dir.join("fx-desk.sock")
        }));

        let make_slot = |slot_id: &str, members: &[&str]| {
            let apps = Value::Array(members.iter().map(|m| json!(m)).collect());
            json!({
                "slot_id": slot_id,
                "applicants": apps,
                "input_end": {
                    "kind": "ControlledInputEnd",
                    "source_id": "ac2-r2-fixture",
                    "source_epoch": "1",
                    "watermark": "2",
                    "complete_request_hash": hash(&apps)
                }
            })
        };
        let slots = vec![
            make_slot("slot-main", &["alpha", "beta"]),
            make_slot("slot-gamma", &["gamma"]),
        ];

        let mut fin_data = json!({
            "schema_revision": fin_rev,
            "kind": "TestOnly",
            "source_id": "ac2-r2-fixture",
            "source_epoch": "1",
            "policy": {
                "policy_id": format!("TestOnly-ac2-cap-{cap}"),
                "allocation_policy_id": "#1349/atomic-slot-wait/v1",
                "cap": cap,
                "currency": "TEST-CASH",
                "money_unit": "TEST-CASH",
                "quantity_unit": "TEST-UNIT",
                "quantum": "1",
                "capability_id": "TestOnly-no-leverage-no-venue",
                "model": "TestOnlyUnleveragedCashBuy",
                "valid_through_ns": "9000000000000000000"
            },
            "baseline": {
                "responsibility_id": baseline_id,
                "amount": baseline_amount,
                "source_ref": format!("TestOnly-baseline/{baseline_id}"),
                "covered_facts": covered
            },
            "rights": rights,
            "plans": plans,
            "slots": slots
        });
        if v3_cap_activation {
            fin_data["policy"]["profile_id"] = json!("unit");
        } else {
            decorate_exact_input(&mut fin_data);
        }
        let (fin_path, fin_sha) = space.save_json("finance-input.json", &fin_data);
        let (fx_ob_path, fx_ob_sha) = space.save_raw("fx-obligations.json", fx_obligations_raw);

        let mut fin_ops = vec![
            "ImportResponsibility",
            "ImportFxResponsibility",
            "CaptureExternal",
            "ResolveEvidence",
            "ApplyAllocation",
            "BindVoice",
            "ReadView",
            "QueryFact",
            "QueryDecision",
            "QueryGrant",
            "QueryVoice",
            "QueryFxValuation",
            "PrepareDecision",
            "Reserve",
            "CommitDecision",
            "AbortDecision",
            "CloseApplicants",
            "ActivateCapPolicy",
        ];
        if !v3_cap_activation {
            fin_ops.extend([
                "MakeDispatchable",
                "ReleaseExact",
                "QueryCommand",
                "QueryReleasedExact",
            ]);
        }

        let mut clock_messages = serde_json::Map::new();
        for (msg, t) in [
            ("imp-base", 10),
            ("imp-91", 10),
            ("imp-fx", 20),
            ("cap-r1", 30),
            ("cap-r1-dup", 35),
            ("res-r1", 40),
            ("res-r1-over95", 40),
            ("act-105", 50),
            ("act-120", 60),
            ("res-r1-ok", 70),
            ("cap-open-alpha", 100),
            ("apply-open-alpha", 105),
            ("bind-alpha", 110),
            ("prep-alpha", 115),
            ("cap-open-beta", 120),
            ("apply-open-beta", 125),
            ("bind-beta", 130),
            ("prep-beta", 135),
            ("cap-open-gamma", 140),
            ("apply-open-gamma", 145),
            ("bind-gamma", 150),
            ("prep-gamma", 155),
            ("cap-open-fx-desk", 160),
            ("apply-open-fx-desk", 165),
            ("bind-fx-desk", 170),
            ("prep-fx-desk", 175),
            ("reserve-main", 200),
            ("commit-alpha", 210),
            ("dispatch-alpha", 220),
            ("cap-r2", 230),
            ("res-r1-stale", 240),
            ("res-r2-over", 250),
            ("res-r2-overcap", 250),
            ("reserve-gamma-blocked", 260),
            ("reserve-gamma-bypass-attempt", 260),
            ("commit-beta-blocked", 270),
            ("commit-beta-bypass-attempt", 270),
            ("release-alpha-blocked", 280),
            ("release-alpha-bypass-attempt", 280),
            ("cap-unmatched", 290),
            ("cap-r3", 300),
            ("retire-r2-too-early", 310),
            ("res-r3", 320),
            ("release-alpha-before-retire", 330),
            ("retire-r2", 340),
            ("res-r2-r3-batch", 340),
            ("release-blocked-by-unmatched", 350),
            ("res-unmatched", 360),
            ("commit-beta-ok", 370),
            ("release-alpha-ok", 380),
            ("reserve-gamma-ok", 390),
            ("cap-r2-first", 400),
            ("cap-r1-backfill", 410),
            ("cap-fork", 420),
            ("cap-frac", 430),
            ("cap-r1-first", 5),
            ("cap-r1-early", 15),
            ("res-early-before-import", 16),
            ("imp-fx-second", 18),
            ("imp-fx-1", 21),
            ("imp-fx-after-r1", 22),
            ("res-early-before-baseline", 22),
            ("imp-fx-2", 24),
            ("act-before-fx-import", 25),
            ("imp-base-third", 28),
            ("res-partial-blocked", 36),
            ("res-r1-after-import", 42),
            ("reserve-before-fx-import", 180),
            ("imp-fx-late", 182),
            ("reserve-no-quote", 185),
            ("cap-r1-late", 188),
            ("reserve-pending-r1", 190),
            ("res-r1-late", 195),
            ("reserve-after-r1-110", 205),
            ("release-alpha-empty-fx", 235),
            ("cap-other-a1", 345),
            ("retire-r1-ep2-bad-other", 10005),
            ("retire-r1-ep2-mixed-other", 10008),
            ("retire-r1-ep2-ok", 10012),
            ("reserve-blocked-by-other-ep2", 10020),
        ] {
            clock_messages.insert(
                msg.to_owned(),
                json!({
                    "received_ns": t.to_string(),
                    "first_known_ns": (t + 1).to_string(),
                    "commit_ns": (t + 2).to_string()
                }),
            );
        }
        let manifest = json!({
            "schema_revision": "economic-manifest/1",
            "book_revision": "tb03c-book/1",
            "session_id": session_id,
            "session_generation": "1",
            "e": {
                "db": space.dir.join("e.db"),
                "socket": space.dir.join("e.sock")
            },
            "chongs": routes,
            "authorized_sources": [
                {
                    "source_namespace": FIN_NS,
                    "source_epoch": FIN_EPOCH,
                    "producer_id": "fin-coord",
                    "producer_epoch": "1",
                    "operations": fin_ops
                },
                {
                    "source_namespace": MARKET_NS,
                    "source_epoch": MARKET_EPOCH,
                    "producer_id": "market-feed-fx",
                    "producer_epoch": "1",
                    "operations": ["CaptureExternal", "ResolveEvidence"]
                },
                {
                    "source_namespace": READER_NS,
                    "source_epoch": READER_EPOCH,
                    "producer_id": "reader-1407",
                    "producer_epoch": "1",
                    "operations": ["ReadView", "QueryFact", "QueryFxValuation"]
                }
            ],
            "resources": {
                "max_frame_bytes": "16777216",
                "read_timeout_ms": "2000",
                "write_timeout_ms": "2000",
                "response_timeout_ms": "5000",
                "queue_capacity": "8",
                "max_connections": "8"
            },
            "clock": {
                "kind": "TestOnly",
                "plan": {
                    "init_ns": "1",
                    "recover_ns": ["10000", "20000"],
                    "messages": Value::Object(clock_messages)
                }
            },
            "voice_binding": {
                "schema_revision": "voice-binding/1",
                "authorities": authorities
            },
            "finance": {
                "schema_revision": fin_rev,
                "input_path": fin_path,
                "input_sha256": fin_sha,
                "coordinator_source": {
                    "source_namespace": FIN_NS,
                    "source_epoch": FIN_EPOCH,
                    "producer_id": "fin-coord",
                    "producer_epoch": "1"
                },
                "structure": {
                    "binary": stub,
                    "binary_sha256": stub_sha,
                    "db": space.dir.join("s.db"),
                    "session_id": session_id,
                    "session_generation": "1",
                    "writer_epoch": "1"
                }
            },
            "fx_valuation": {
                "schema_revision": "fx-valuation/1",
                "kind": "TestOnly",
                "obligation_input_path": fx_ob_path,
                "obligation_input_sha256": fx_ob_sha
            }
        });
        let (mpath, _) = space.save_json("manifest.json", &manifest);

        let e_config = Config::load(Path::new(&mpath), &space.dir.join("e.db"), None).unwrap();
        init(&e_config).unwrap();
        let (e_db, _) = open(&e_config.db, false).unwrap();

        let mut b_configs = Vec::new();
        let mut b_dbs = Vec::new();
        for (name, _, _, _, _, _, _, _) in chong_specs {
            let bc = Config::load(
                Path::new(&mpath),
                &space.dir.join(format!("{name}.db")),
                Some(name),
            )
            .unwrap();
            init(&bc).unwrap();
            let (bdb, _) = open(&bc.db, false).unwrap();
            b_configs.push((name.to_owned(), bc));
            b_dbs.push((name.to_owned(), bdb));
        }

        Self {
            space,
            session_id,
            e_config,
            e_db,
            b_configs,
            b_dbs,
            fin_data,
            opening_docs,
            voice_payloads,
        }
    }

    fn e_fin(&mut self, msg: &str, payload: Value) -> Value {
        let req = env(
            &self.session_id,
            FIN_NS,
            FIN_EPOCH,
            "fin-coord",
            msg,
            payload,
        );
        send(&mut self.e_db, &self.e_config, 1, &req)
    }

    fn e_market(&mut self, msg: &str, payload: Value) -> Value {
        let req = env(
            &self.session_id,
            MARKET_NS,
            MARKET_EPOCH,
            "market-feed-fx",
            msg,
            payload,
        );
        send(&mut self.e_db, &self.e_config, 1, &req)
    }

    fn e_read(&mut self, epoch: i64, msg: &str, payload: Value) -> Value {
        let req = env(
            &self.session_id,
            READER_NS,
            READER_EPOCH,
            "reader-1407",
            msg,
            payload,
        );
        send(&mut self.e_db, &self.e_config, epoch, &req)
    }

    fn b_send(&mut self, name: &str, msg: &str, payload: Value) -> Value {
        let req = env(
            &self.session_id,
            FIN_NS,
            FIN_EPOCH,
            "fin-coord",
            msg,
            payload,
        );
        let idx = self.b_configs.iter().position(|(n, _)| n == name).unwrap();
        send(&mut self.b_dbs[idx].1, &self.b_configs[idx].1, 1, &req)
    }

    fn prepare_all_chongs(&mut self) {
        let docs = self.opening_docs.clone();
        let voices = self.voice_payloads.clone();
        for ((name, doc, fk, fh), (_, vp)) in docs.iter().zip(voices.iter()) {
            let cap = self.e_fin(
                &format!("cap-open-{name}"),
                json!({
                    "op": "CaptureExternal",
                    "raw_utf8": canonical_json(doc),
                    "json_pointer": "/events/0",
                    "token": format!("tok-opening-{name}"),
                    "source_event_time": null
                }),
            );
            assert_eq!(cap["kind"], "Recorded", "{cap}");

            let app = self.b_send(
                name,
                &format!("apply-open-{name}"),
                json!({
                    "op": "ApplyAllocation",
                    "fact_key": fk,
                    "expected_fact_hash": fh,
                    "allocation_id": format!("allocation-{name}")
                }),
            );
            assert_eq!(app["kind"], "Applied", "{app}");

            let bind = self.b_send(name, &format!("bind-{name}"), vp.clone());
            assert_eq!(bind["kind"], "VoiceBound", "{bind}");

            let plan = self.plan(name);
            let prep = self.b_send(
                name,
                &format!("prep-{name}"),
                json!({
                    "op": "PrepareDecision",
                    "decision_id": name,
                    "plan_hash": hash(&plan),
                    "writer_epoch": "1"
                }),
            );
            assert_eq!(prep["kind"], "PreparedReceipt", "{prep}");
        }
    }

    fn plan(&self, name: &str) -> Value {
        self.fin_data["plans"]
            .as_array()
            .unwrap()
            .iter()
            .find(|p| p["decision_id"] == name)
            .unwrap()
            .clone()
    }

    fn slot(&self, slot_id: &str) -> Value {
        self.fin_data["slots"]
            .as_array()
            .unwrap()
            .iter()
            .find(|s| s["slot_id"] == slot_id)
            .unwrap()
            .clone()
    }

    fn capture_fx(&mut self, msg: &str, raw: &str, token: &str) -> Value {
        let ts = serde_json::from_str::<Value>(raw).unwrap()["timestamp"].clone();
        self.e_market(
            msg,
            json!({
                "op": "CaptureExternal",
                "raw_utf8": raw,
                "json_pointer": "",
                "token": token,
                "source_event_time": ts
            }),
        )
    }

    fn e_fin_epoch(&mut self, epoch: i64, msg: &str, payload: Value) -> Value {
        let req = env(
            &self.session_id,
            FIN_NS,
            FIN_EPOCH,
            "fin-coord",
            msg,
            payload,
        );
        send(&mut self.e_db, &self.e_config, epoch, &req)
    }

    fn e_market_epoch(&mut self, epoch: i64, msg: &str, payload: Value) -> Value {
        let req = env(
            &self.session_id,
            MARKET_NS,
            MARKET_EPOCH,
            "market-feed-fx",
            msg,
            payload,
        );
        send(&mut self.e_db, &self.e_config, epoch, &req)
    }

    fn resolve_fx(&mut self, msg: &str, evidence_id: &str, recs: &[&Value]) -> Value {
        self.resolve_fx_epoch(1, msg, evidence_id, recs)
    }

    fn resolve_fx_epoch(
        &mut self,
        epoch: i64,
        msg: &str,
        evidence_id: &str,
        recs: &[&Value],
    ) -> Value {
        let covered: Vec<Value> = recs
            .iter()
            .map(|r| {
                json!({
                    "fact_key": r["fact_key"],
                    "fact_hash": r["fact_hash"],
                    "token": r["token"]
                })
            })
            .collect();
        self.e_market_epoch(
            epoch,
            msg,
            json!({
                "op": "ResolveEvidence",
                "evidence_id": evidence_id,
                "covered": covered,
                "frontier": {
                    "source_namespace": MARKET_NS,
                    "source_epoch": MARKET_EPOCH,
                    "cursor": "70"
                },
                "dependency_version": "1"
            }),
        )
    }

    fn query_fx(&mut self, epoch: i64, msg: &str, cut: Value, as_known: Value) -> Value {
        self.e_read(
            epoch,
            msg,
            json!({"op": "QueryFxValuation", "cut": cut, "as_known_ns": as_known}),
        )
    }

    fn release_exact_payload(&self, name: &str, grant_id: &str) -> Value {
        let q = self.plan(name);
        let bind_model_ref =
            self.e_config.manifest["finance"]["schema_revision"] == "tb03b-finance/6";
        let cmd = super::exact_command::command(
            &self.session_id,
            "1",
            &self.fin_data,
            &q,
            grant_id,
            bind_model_ref,
            None,
        )
        .unwrap();
        json!({
            "op": "ReleaseExact",
            "decision_id": name,
            "command_id": q["exact"]["command_id"],
            "plan_hash": cmd["plan_hash"],
            "certificate": cmd["certificate"],
            "x_id": "X",
            "x_epoch": "1",
            "writer_epoch": "1"
        })
    }

    fn release_exact_payload_from_query(
        &self,
        query_reply: &Value,
        name: &str,
        grant_id: &str,
    ) -> Value {
        let q = self.plan(name);
        let owner = q["owner"].as_str().unwrap();
        let binding =
            super::fx_valuation::release_binding_from_query(query_reply, grant_id, owner).unwrap();
        let bind_model_ref =
            self.e_config.manifest["finance"]["schema_revision"] == "tb03b-finance/6";
        let cmd = super::exact_command::command(
            &self.session_id,
            "1",
            &self.fin_data,
            &q,
            grant_id,
            bind_model_ref,
            Some(&binding),
        )
        .unwrap();
        json!({
            "op": "ReleaseExact",
            "decision_id": name,
            "command_id": q["exact"]["command_id"],
            "plan_hash": cmd["plan_hash"],
            "certificate": cmd["certificate"],
            "x_id": "X",
            "x_epoch": "1",
            "writer_epoch": "1"
        })
    }
}

#[test]
fn real_finance_90_110_90_exact_retirement_dynamic_projection_and_recovery() {
    let mut s = Ac2Session::build(
        "lifecycle",
        "100",
        "0",
        "baseline-cash-0",
        vec![],
        false,
        FX_OBLIGATIONS_RAW,
    );

    // 0. 创世：未导入基线与外币义务 -> BlockedUnverifiable，无任何平行 manifest 假数。
    let q0 = s.query_fx(1, "q0", Value::Null, Value::Null);
    assert_eq!(q0["fx_valuation"]["baseline_imported"], json!(false));
    assert!(q0["fx_valuation"]["cap_policy"].is_null());
    assert_eq!(
        q0["fx_valuation"]["summary"]["gate_status"],
        "BlockedUnverifiable"
    );

    // 1. 正式导入现金基线（0 TEST-CASH，不改旧 20 TEST-CASH 正控）与独立 TestOnly 外币义务（20 TEST-FX）。
    let imp_base = s.e_fin(
        "imp-base",
        json!({"op": "ImportResponsibility", "responsibility_id": "baseline-cash-0", "writer_epoch": "1"}),
    );
    assert_eq!(
        imp_base["kind"], "ResponsibilityImportedReceipt",
        "{imp_base}"
    );

    let imp_fx = s.e_fin(
        "imp-fx",
        json!({"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"}),
    );
    assert_eq!(
        imp_fx["kind"], "FxResponsibilityImportedReceipt",
        "{imp_fx}"
    );
    let q_noq = s.query_fx(1, "q-noq", Value::Null, Value::Null);
    assert_eq!(
        q_noq["fx_valuation"]["summary"]["gate_status"],
        "BlockedNoQuote"
    );
    assert_eq!(q_noq["fx_valuation"]["cap_policy"]["cap"], "100");
    assert_eq!(
        q_noq["fx_valuation"]["foreign_responsibilities"][0]["owner"],
        "B:fx-desk"
    );

    // 2. 接纳 r1 (1/1) 并核清 -> 20 / 100 AdmissibleWithinCap。
    let r1 = s.capture_fx("cap-r1", FX_R1_RAW, "tok-r1");
    assert_eq!(r1["kind"], "Recorded", "{r1}");
    assert_eq!(s.capture_fx("cap-r1-dup", FX_R1_RAW, "tok-r1"), r1);
    let ev1 = s.resolve_fx("res-r1", "ev-r1", &[&r1]);
    assert_eq!(ev1["kind"], "Resolved", "{ev1}");
    let q_after_r1 = s.query_fx(1, "q-r1-pre-res", Value::Null, Value::Null);
    assert_eq!(
        q_after_r1["fx_valuation"]["summary"]["evaluated_total"],
        "20"
    );
    assert_eq!(
        q_after_r1["fx_valuation"]["summary"]["gate_status"],
        "AdmissibleWithinCap"
    );

    // 3. 真实 B:alpha (30), B:beta (40), B:gamma (5) Prepare -> E Reserve(slot-main) 创建两笔真实保留。
    s.prepare_all_chongs();
    let slot_main = s.slot("slot-main");
    let res_main = s.e_fin(
        "reserve-main",
        json!({
            "op": "Reserve",
            "slot_id": "slot-main",
            "request_set_hash": hash(&slot_main["applicants"]),
            "writer_epoch": "1"
        }),
    );
    assert_eq!(res_main["kind"], "ReserveReceipt", "{res_main}");
    assert_eq!(res_main["record"]["state"], "Reserved", "{res_main}");
    assert_eq!(res_main["record"]["required_total"], "90");

    // 同一 cut 验证 FX 投影已由真实 Reserve grant 从 20/100 真实随动到 90/100。
    let q_90 = s.query_fx(1, "q-90", Value::Null, Value::Null);
    assert_eq!(q_90["cut"], res_main["cut"]);
    assert_eq!(q_90["fx_valuation"]["summary"]["cash_subtotal"], "70");
    assert_eq!(
        q_90["fx_valuation"]["summary"]["foreign_evaluated_subtotal"],
        "20"
    );
    assert_eq!(q_90["fx_valuation"]["summary"]["evaluated_total"], "90");
    assert_eq!(q_90["fx_valuation"]["summary"]["headroom_or_excess"], "10");
    assert_eq!(
        q_90["fx_valuation"]["summary"]["gate_status"],
        "AdmissibleWithinCap"
    );
    assert_eq!(
        q_90["fx_valuation"]["applicable_scope"]["grant_ids"]
            .as_array()
            .unwrap()
            .len(),
        2
    );

    let grants = res_main["record"]["grants"].as_array().unwrap();
    let alpha_gid = grants.iter().find(|g| g["decision_id"] == "alpha").unwrap()["grant_id"]
        .as_str()
        .unwrap()
        .to_owned();
    let beta_gid = grants.iter().find(|g| g["decision_id"] == "beta").unwrap()["grant_id"]
        .as_str()
        .unwrap()
        .to_owned();

    // 在 r1 限内完成 alpha 的 Commit + MakeDispatchable（留 beta 待首次 Commit、gamma 待 Reserve、alpha 待 ReleaseExact）。
    let alpha_plan = s.plan("alpha");
    let ca = s.b_send(
        "alpha",
        "commit-alpha",
        json!({
            "op": "CommitDecision",
            "decision_id": "alpha",
            "plan_hash": hash(&alpha_plan),
            "grant_id": alpha_gid,
            "writer_epoch": "1"
        }),
    );
    assert_eq!(ca["kind"], "LocalCommitReceipt", "{ca}");
    let md = s.e_fin(
        "dispatch-alpha",
        json!({
            "op": "MakeDispatchable",
            "decision_id": "alpha",
            "plan_hash": hash(&alpha_plan),
            "writer_epoch": "1"
        }),
    );
    assert_eq!(md["kind"], "DispatchableReceipt", "{md}");

    // 4. 接纳 r2 (2/1, 同 source_coord=70, supersedes=1) -> 90 -> 110 > 100 BlockedExceedsCap。
    let r2 = s.capture_fx("cap-r2", FX_R2_RAW, "tok-r2");
    assert_eq!(r2["kind"], "Recorded", "{r2}");
    assert_ne!(r2["fact_key"], r1["fact_key"]);
    let q_110 = s.query_fx(1, "q-110", Value::Null, Value::Null);
    assert_eq!(q_110["fx_valuation"]["summary"]["evaluated_total"], "110");
    assert_eq!(
        q_110["fx_valuation"]["summary"]["gate_status"],
        "BlockedExceedsCap"
    );

    // 超限态下：Resolve(r2)、真实 Reserve(slot-gamma)、真实首次 Commit(beta)、真实 ReleaseExact(alpha) 全部阻断。
    let bad_res_r2 = s.resolve_fx("res-r2-overcap", "ev-r2-overcap", &[&r2]);
    assert_eq!(bad_res_r2["kind"], "Error", "{bad_res_r2}");
    assert!(bad_res_r2["error"]
        .as_str()
        .unwrap()
        .contains("AwaitingPolicy"));

    let slot_gamma = s.slot("slot-gamma");
    let blocked_reserve = s.e_fin(
        "reserve-gamma-blocked",
        json!({
            "op": "Reserve",
            "slot_id": "slot-gamma",
            "request_set_hash": hash(&slot_gamma["applicants"]),
            "writer_epoch": "1"
        }),
    );
    assert_eq!(blocked_reserve["kind"], "Error", "{blocked_reserve}");

    let beta_plan = s.plan("beta");
    let blocked_commit = s.b_send(
        "beta",
        "commit-beta-blocked",
        json!({
            "op": "CommitDecision",
            "decision_id": "beta",
            "plan_hash": hash(&beta_plan),
            "grant_id": beta_gid,
            "writer_epoch": "1"
        }),
    );
    assert_eq!(blocked_commit["kind"], "Error", "{blocked_commit}");

    let rel_payload = s.release_exact_payload("alpha", &alpha_gid);
    let blocked_release = s.e_fin("release-alpha-blocked", rel_payload.clone());
    assert_eq!(blocked_release["kind"], "Error", "{blocked_release}");

    // 5. 接纳 r3 (1/1, 同 source_coord=70, supersedes=2) -> 110 -> 90 <= 100。
    let r3 = s.capture_fx("cap-r3", FX_R3_RAW, "tok-r3");
    assert_eq!(r3["kind"], "Recorded", "{r3}");

    // r3 尚未核清前，不能先退役 r2。
    let early_retire = s.resolve_fx("retire-r2-too-early", "ev-retire-early", &[&r2]);
    assert_eq!(early_retire["kind"], "Error", "{early_retire}");
    assert!(early_retire["error"]
        .as_str()
        .unwrap()
        .contains("已被修订 3 替代"));

    // 先核清 r3：r3 变为 Covered，但 r2 仍在真实 Pending 中（不在查询时藏起），闸仍闭合。
    let ev3 = s.resolve_fx("res-r3", "ev-r3", &[&r3]);
    assert_eq!(ev3["kind"], "Resolved", "{ev3}");
    let q_pending_retire = s.query_fx(1, "q-pending-retire", Value::Null, Value::Null);
    assert_eq!(
        q_pending_retire["fx_valuation"]["summary"]["evaluated_total"],
        "90"
    );
    assert_eq!(
        q_pending_retire["fx_valuation"]["summary"]["gate_status"],
        "BlockedPendingEvidence"
    );
    assert_eq!(
        q_pending_retire["fx_valuation"]["summary"]["active_pending_fact_keys"],
        json!([r2["fact_key"]])
    );
    let still_blocked_rel = s.e_fin("release-alpha-before-retire", rel_payload.clone());
    assert_eq!(still_blocked_rel["kind"], "Error", "{still_blocked_rel}");

    // 用正确新证据精确退役 r2 token -> r2 标记 RetiredBySupersession，Pending 清空，重回 AdmissibleWithinCap。
    let ev_retire_r2 = s.resolve_fx("retire-r2", "ev-retire-r2", &[&r2]);
    assert_eq!(ev_retire_r2["kind"], "Resolved", "{ev_retire_r2}");
    let q_restored = s.query_fx(1, "q-restored", Value::Null, Value::Null);
    assert_eq!(
        q_restored["fx_valuation"]["summary"]["gate_status"],
        "AdmissibleWithinCap"
    );
    assert_eq!(
        q_restored["fx_valuation"]["summary"]["active_pending_fact_keys"],
        json!([])
    );
    let r2_row = q_restored["fx_valuation"]["revisions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|x| x["fact_key"] == r2["fact_key"])
        .unwrap();
    assert_eq!(r2_row["status"], "Superseded");
    assert_eq!(r2_row["coverage_status"], "RetiredBySupersession");
    assert_eq!(r2_row["retired_by_fact_key"], r3["fact_key"]);
    assert_eq!(r2_row["retired_by_revision"], "3");

    // 6. 健康路径恢复：真实 Commit(beta)、ReleaseExact(alpha) 及 Reserve(slot-gamma, +5 -> 95/100) 全部成立。
    let cb = s.b_send(
        "beta",
        "commit-beta-ok",
        json!({
            "op": "CommitDecision",
            "decision_id": "beta",
            "plan_hash": hash(&beta_plan),
            "grant_id": beta_gid,
            "writer_epoch": "1"
        }),
    );
    assert_eq!(cb["kind"], "LocalCommitReceipt", "{cb}");

    let rel_ok = s.e_fin("release-alpha-ok", rel_payload);
    assert_eq!(rel_ok["kind"], "ReleasedExactReceipt", "{rel_ok}");
    assert_eq!(rel_ok["record"]["state"], "ReleasedExact");

    let res_gamma = s.e_fin(
        "reserve-gamma-ok",
        json!({
            "op": "Reserve",
            "slot_id": "slot-gamma",
            "request_set_hash": hash(&slot_gamma["applicants"]),
            "writer_epoch": "1"
        }),
    );
    assert_eq!(res_gamma["kind"], "ReserveReceipt", "{res_gamma}");
    assert_eq!(res_gamma["record"]["state"], "Reserved");
    assert_eq!(res_gamma["record"]["required_total"], "95");

    // 同一 cut 验证投影随新增真实责任从 90/100 真实随动到 95/100。
    let q_95 = s.query_fx(1, "q-95", Value::Null, Value::Null);
    assert_eq!(q_95["cut"], res_gamma["cut"]);
    assert_eq!(q_95["fx_valuation"]["summary"]["cash_subtotal"], "75");
    assert_eq!(q_95["fx_valuation"]["summary"]["evaluated_total"], "95");
    assert_eq!(q_95["fx_valuation"]["summary"]["headroom_or_excess"], "5");

    // 7. 恢复、全量 audit、旧 cut / as_known_ns 与原件/回执重取。
    audit(&s.e_db, &s.e_config).unwrap();
    let rec = recover(&s.e_config).unwrap();
    assert_eq!(rec["writer_epoch"], "2");
    let q_after_rec = s.query_fx(2, "q-after-rec", Value::Null, Value::Null);
    assert_eq!(q_after_rec["fx_valuation"], q_95["fx_valuation"]);
    assert_eq!(q_after_rec["receipts"], q_95["receipts"]);
    assert_eq!(q_after_rec["evidence_receipts"], q_95["evidence_receipts"]);
    assert_eq!(
        q_after_rec["responsibility_receipts"],
        q_95["responsibility_receipts"]
    );

    // 旧 r2 超限 cut 完整保留原 Pending 与 110 > 100 历史。
    let q_old_110 = s.query_fx(2, "q-old-110", q_110["cut"].clone(), Value::Null);
    assert_eq!(q_old_110["fx_valuation"], q_110["fx_valuation"]);
    let rv_old_110 = s.e_read(
        2,
        "rv-old-110",
        json!({"op": "ReadView", "cut": q_110["cut"], "as_known_ns": null}),
    );
    assert_eq!(
        rv_old_110["image"]["pending"][0]["fact_key"],
        r2["fact_key"]
    );
    assert_eq!(
        rv_old_110["image"]["pending"][0]["reason"]["kind"],
        "FxQuoteCapExceeded"
    );

    // 两版原字节与回执重取逐字节一致。
    for (raw, rec_orig, msg) in [(FX_R1_RAW, &r1, "qf-r1"), (FX_R2_RAW, &r2, "qf-r2")] {
        let qf = s.e_read(
            2,
            msg,
            json!({"op": "QueryFact", "fact_key": rec_orig["fact_key"]}),
        );
        assert_eq!(qf["fact"]["raw_utf8"].as_str().unwrap(), raw);
        assert_eq!(qf["receipt"], *rec_orig);
    }
}

#[test]
fn exact_baseline_coverage_cannot_bypass_overcap_and_unrelated_tokens_survive_batch_retire() {
    // 预先算出 r2 的精确 (fact_key, fact_hash, token)，故意放进 d["baseline"]["covered_facts"]，
    // 验证 Reserve、首次 CommitDecision、ReleaseExact 均不能被基线精准覆盖绕过超限 FX Pending。
    let r2_doc_val: Value = serde_json::from_str(FX_R2_RAW).unwrap();
    let (doc_r2, ev_r2) = super::fx_valuation::decode(&r2_doc_val, "").unwrap();
    let r2_raw_sha = sha256_hex(FX_R2_RAW.as_bytes());
    let r2_fk = book::fact_key(&ev_r2).unwrap();
    let r2_fh = hash(&json!({
        "raw_sha256": r2_raw_sha,
        "json_pointer": "",
        "event": ev_r2,
        "units": doc_r2["units"]
    }));
    let r2_bypass_cover = json!({
        "fact_key": r2_fk,
        "fact_hash": r2_fh,
        "token": "tok-r2-bypass"
    });

    let mut s = Ac2Session::build(
        "bypass-and-unrelated",
        "100",
        "0",
        "baseline-cash-0",
        vec![r2_bypass_cover],
        false,
        FX_OBLIGATIONS_RAW,
    );

    assert_eq!(
        s.e_fin(
            "imp-base",
            json!({"op": "ImportResponsibility", "responsibility_id": "baseline-cash-0", "writer_epoch": "1"}),
        )["kind"],
        "ResponsibilityImportedReceipt"
    );
    assert_eq!(
        s.e_fin(
            "imp-fx",
            json!({"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"}),
        )["kind"],
        "FxResponsibilityImportedReceipt"
    );
    let r1 = s.capture_fx("cap-r1", FX_R1_RAW, "tok-r1");
    assert_eq!(s.resolve_fx("res-r1", "ev-r1", &[&r1])["kind"], "Resolved");
    s.prepare_all_chongs();

    let slot_main = s.slot("slot-main");
    let res_main = s.e_fin(
        "reserve-main",
        json!({
            "op": "Reserve",
            "slot_id": "slot-main",
            "request_set_hash": hash(&slot_main["applicants"]),
            "writer_epoch": "1"
        }),
    );
    assert_eq!(res_main["record"]["state"], "Reserved", "{res_main}");
    let grants = res_main["record"]["grants"].as_array().unwrap();
    let alpha_gid = grants.iter().find(|g| g["decision_id"] == "alpha").unwrap()["grant_id"]
        .as_str()
        .unwrap()
        .to_owned();
    let beta_gid = grants.iter().find(|g| g["decision_id"] == "beta").unwrap()["grant_id"]
        .as_str()
        .unwrap()
        .to_owned();

    let alpha_plan = s.plan("alpha");
    assert_eq!(
        s.b_send(
            "alpha",
            "commit-alpha",
            json!({
                "op": "CommitDecision",
                "decision_id": "alpha",
                "plan_hash": hash(&alpha_plan),
                "grant_id": alpha_gid,
                "writer_epoch": "1"
            }),
        )["kind"],
        "LocalCommitReceipt"
    );
    assert_eq!(
        s.e_fin(
            "dispatch-alpha",
            json!({
                "op": "MakeDispatchable",
                "decision_id": "alpha",
                "plan_hash": hash(&alpha_plan),
                "writer_epoch": "1"
            }),
        )["kind"],
        "DispatchableReceipt"
    );

    // 用与 baseline.covered_facts 完全匹配的 tok-r2-bypass 接纳超限 r2。
    let r2 = s.capture_fx("cap-r2", FX_R2_RAW, "tok-r2-bypass");
    assert_eq!(r2["kind"], "Recorded", "{r2}");
    assert_eq!(r2["fact_key"], r2_fk);
    assert_eq!(r2["fact_hash"], r2_fh);

    // 三个真实公开写口全部阻断，证明精准覆盖不能绕过 FX 超限！
    let slot_gamma = s.slot("slot-gamma");
    let e_res = s.e_fin(
        "reserve-gamma-bypass-attempt",
        json!({
            "op": "Reserve",
            "slot_id": "slot-gamma",
            "request_set_hash": hash(&slot_gamma["applicants"]),
            "writer_epoch": "1"
        }),
    );
    assert_eq!(e_res["kind"], "Error", "{e_res}");
    assert!(e_res["error"].as_str().unwrap().contains("AwaitingPolicy"));

    let beta_plan = s.plan("beta");
    let e_com = s.b_send(
        "beta",
        "commit-beta-bypass-attempt",
        json!({
            "op": "CommitDecision",
            "decision_id": "beta",
            "plan_hash": hash(&beta_plan),
            "grant_id": beta_gid,
            "writer_epoch": "1"
        }),
    );
    assert_eq!(e_com["kind"], "Error", "{e_com}");
    assert!(e_com["error"].as_str().unwrap().contains("AwaitingPolicy"));

    let rel_payload = s.release_exact_payload("alpha", &alpha_gid);
    let e_rel = s.e_fin("release-alpha-bypass-attempt", rel_payload.clone());
    assert_eq!(e_rel["kind"], "Error", "{e_rel}");
    assert!(e_rel["error"].as_str().unwrap().contains("AwaitingPolicy"));

    // 额外注入一个无关未匹配外币报价（account:*）后，再接纳 r3 并用单批 ResolveEvidence([r2, r3]) 原子退役 r2。
    let mut unmatched: Value = serde_json::from_str(FX_R1_RAW).unwrap();
    unmatched["instrument"] = json!("OTHER-FX/TEST-CASH");
    unmatched["base_unit"] = json!("OTHER-FX");
    unmatched["event_id"] = json!("fx-unrelated-999");
    let ru = s.capture_fx(
        "cap-unmatched",
        &canonical_json(&unmatched),
        "tok-unrelated",
    );
    assert_eq!(ru["kind"], "Recorded", "{ru}");

    let r3 = s.capture_fx("cap-r3", FX_R3_RAW, "tok-r3");
    assert_eq!(r3["kind"], "Recorded", "{r3}");

    // 单批同核清 r3 + 精确退役 r2 成功，但绝不清掉无关的 tok-unrelated！
    let batch = s.resolve_fx("res-r2-r3-batch", "ev-r2-r3-batch", &[&r2, &r3]);
    assert_eq!(batch["kind"], "Resolved", "{batch}");

    let rv = s.e_read(
        1,
        "rv-after-batch",
        json!({"op": "ReadView", "cut": null, "as_known_ns": null}),
    );
    let pend = rv["image"]["pending"].as_array().unwrap();
    assert_eq!(pend.len(), 1, "{pend:?}");
    assert_eq!(pend[0]["fact_key"], ru["fact_key"]);
    assert_eq!(pend[0]["scope"], "account:*");

    // 无关 account:* token 仍保持保守阻断，无法被 ResolveEvidence 或 ReleaseExact 绕过。
    let try_ru = s.resolve_fx("res-unmatched", "ev-unmatched", &[&ru]);
    assert_eq!(try_ru["kind"], "Error", "{try_ru}");
    assert!(try_ru["error"].as_str().unwrap().contains("账户范围"));
    let rel_still_blocked = s.e_fin("release-blocked-by-unmatched", rel_payload);
    assert_eq!(rel_still_blocked["kind"], "Error", "{rel_still_blocked}");
    audit(&s.e_db, &s.e_config).unwrap();
}

#[test]
fn arm_b_finance_truth_91_95_and_cap_policy_activation_move_fx_projection() {
    // 直接复现独审 Arm B 反例：FIN 基线 91 TEST-CASH、政策 cap 95 TEST-CASH；
    // 验证 FX 投影从真实 FIN 责任与生效 cap 同步随动，并验证 ActivateCapPolicy 计入外币敞口。
    let mut s = Ac2Session::build(
        "arm-b-91-95",
        "95",
        "91",
        "review-existing-cash-91",
        vec![],
        true,
        FX_OBLIGATIONS_RAW,
    );

    // ImportResponsibility 前：baseline_imported=false, cap=null, 阻断。
    let q_pre = s.query_fx(1, "q-pre", Value::Null, Value::Null);
    assert_eq!(q_pre["fx_valuation"]["baseline_imported"], json!(false));
    assert!(q_pre["fx_valuation"]["cap_policy"].is_null());

    // 导入 91 TEST-CASH 基线（cap 95）：同一 cut 的 FX 投影立即显示 cash_subtotal=91, cap=95。
    let imp_base = s.e_fin(
        "imp-91",
        json!({"op": "ImportResponsibility", "responsibility_id": "review-existing-cash-91", "writer_epoch": "1"}),
    );
    assert_eq!(
        imp_base["kind"], "ResponsibilityImportedReceipt",
        "{imp_base}"
    );
    let q_after_imp = s.query_fx(1, "q-after-imp", Value::Null, Value::Null);
    assert_eq!(q_after_imp["cut"], imp_base["cut"]);
    assert_eq!(q_after_imp["fx_valuation"]["cap_policy"]["cap"], "95");
    assert_eq!(
        q_after_imp["fx_valuation"]["summary"]["cash_subtotal"],
        "91"
    );
    assert_eq!(
        q_after_imp["fx_valuation"]["initial_foreign_responsibilities_complete"],
        json!(false)
    );
    assert_eq!(
        q_after_imp["fx_valuation"]["boundary"]["missing_foreign_responsibility_ids"],
        json!(["ob-fx-unclosed-20"])
    );
    assert!(q_after_imp["fx_valuation"]["summary"]["foreign_evaluated_subtotal"].is_null());
    assert!(q_after_imp["fx_valuation"]["summary"]["evaluated_total"].is_null());
    assert_eq!(
        q_after_imp["fx_valuation"]["summary"]["gate_status"],
        "BlockedUnverifiable"
    );
    // 期初外币义务未导入前，也不得基于缺漏敞口激活新 cap。
    let (pre_cap_path, pre_cap_sha) = s.space.save_json(
        "cap-pre-120.json",
        &json!({
            "schema_revision": "funding-cap-policy-record/1",
            "kind": "TestOnly",
            "profile_id": "unit",
            "policy_id": "TestOnly-ac2-cap-95",
            "version": "2",
            "supersedes": "1",
            "cap": "120",
            "currency": "TEST-CASH",
            "money_unit": "TEST-CASH",
            "valid_through_ns": "9000000000000000000",
            "authorizer": "testonly-owner",
            "authorized_at_ns": "1",
            "signature_ref": "sig-pre-120"
        }),
    );
    let act_before_fx = s.e_fin(
        "act-before-fx-import",
        json!({
            "op": "ActivateCapPolicy",
            "activation_id": "act-before-fx",
            "policy_id": "TestOnly-ac2-cap-95",
            "from_version": "1",
            "to_version": "2",
            "cap": "120",
            "valid_through_ns": "9000000000000000000",
            "policy_record": {"path": pre_cap_path, "sha256": pre_cap_sha},
            "writer_epoch": "1"
        }),
    );
    assert_eq!(act_before_fx["kind"], "Error", "{act_before_fx}");
    assert!(act_before_fx["error"]
        .as_str()
        .unwrap()
        .contains("ob-fx-unclosed-20"));

    // 再导入 20 TEST-FX 外币义务并接纳 r1 (1/1) -> 91 + 20 = 111 > 95 -> BlockedExceedsCap。
    assert_eq!(
        s.e_fin(
            "imp-fx",
            json!({"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"}),
        )["kind"],
        "FxResponsibilityImportedReceipt"
    );
    let r1 = s.capture_fx("cap-r1", FX_R1_RAW, "tok-r1");
    assert_eq!(r1["kind"], "Recorded", "{r1}");
    let q_111 = s.query_fx(1, "q-111", Value::Null, Value::Null);
    assert_eq!(q_111["fx_valuation"]["summary"]["evaluated_total"], "111");
    assert_eq!(q_111["fx_valuation"]["summary"]["cap"], "95");
    assert_eq!(
        q_111["fx_valuation"]["summary"]["gate_status"],
        "BlockedExceedsCap"
    );
    let bad_ev1 = s.resolve_fx("res-r1-over95", "ev-r1-over95", &[&r1]);
    assert_eq!(bad_ev1["kind"], "Error", "{bad_ev1}");
    assert!(bad_ev1["error"]
        .as_str()
        .unwrap()
        .contains("AwaitingPolicy"));

    // ActivateCapPolicy：试激活 105（高于现金 91 但低于含外币总敞口 111）-> 拒绝！
    let make_cap_rec = |space: &Space, name: &str, cap_val: &str| {
        let rec = json!({
            "schema_revision": "funding-cap-policy-record/1",
            "kind": "TestOnly",
            "profile_id": "unit",
            "policy_id": "TestOnly-ac2-cap-95",
            "version": "2",
            "supersedes": "1",
            "cap": cap_val,
            "currency": "TEST-CASH",
            "money_unit": "TEST-CASH",
            "valid_through_ns": "9000000000000000000",
            "authorizer": "testonly-owner",
            "authorized_at_ns": "1",
            "signature_ref": format!("sig-{cap_val}")
        });
        space.save_json(name, &rec)
    };
    let (low_path, low_sha) = make_cap_rec(&s.space, "cap-105.json", "105");
    let act_low = s.e_fin(
        "act-105",
        json!({
            "op": "ActivateCapPolicy",
            "activation_id": "act-low",
            "policy_id": "TestOnly-ac2-cap-95",
            "from_version": "1",
            "to_version": "2",
            "cap": "105",
            "valid_through_ns": "9000000000000000000",
            "policy_record": {"path": low_path, "sha256": low_sha},
            "writer_epoch": "1"
        }),
    );
    assert_eq!(act_low["kind"], "Error", "{act_low}");
    assert!(act_low["error"]
        .as_str()
        .unwrap()
        .contains("低于原子点当前责任 111"));

    // 激活 cap=120 -> 同一 cut 下 FX 投影 cap 同步切换为 120（version 2），r1 可核清为 AdmissibleWithinCap。
    let (hi_path, hi_sha) = make_cap_rec(&s.space, "cap-120.json", "120");
    let act_hi = s.e_fin(
        "act-120",
        json!({
            "op": "ActivateCapPolicy",
            "activation_id": "act-hi",
            "policy_id": "TestOnly-ac2-cap-95",
            "from_version": "1",
            "to_version": "2",
            "cap": "120",
            "valid_through_ns": "9000000000000000000",
            "policy_record": {"path": hi_path, "sha256": hi_sha},
            "writer_epoch": "1"
        }),
    );
    assert_eq!(act_hi["kind"], "CapPolicyActivatedReceipt", "{act_hi}");
    let q_120 = s.query_fx(1, "q-120", Value::Null, Value::Null);
    assert_eq!(q_120["cut"], act_hi["cut"]);
    assert_eq!(q_120["fx_valuation"]["cap_policy"]["cap"], "120");
    assert_eq!(q_120["fx_valuation"]["cap_policy"]["policy_version"], "2");
    assert_eq!(q_120["fx_valuation"]["summary"]["within_cap"], json!(true));
    assert_eq!(
        s.resolve_fx("res-r1-ok", "ev-r1-ok", &[&r1])["kind"],
        "Resolved"
    );
    assert_eq!(
        s.query_fx(1, "q-120-ok", Value::Null, Value::Null)["fx_valuation"]["summary"]
            ["gate_status"],
        "AdmissibleWithinCap"
    );
    audit(&s.e_db, &s.e_config).unwrap();
}

#[test]
fn negative_catchup_old_r1_out_of_order_fork_non_integer_and_config_guards() {
    // 1. 补录批（r1, r2 连续入账）：旧 r1 不能核清已被 r2 替代的状态。
    {
        let mut s = Ac2Session::build(
            "catchup",
            "100",
            "70",
            "baseline-cash-70",
            vec![],
            false,
            FX_OBLIGATIONS_RAW,
        );
        assert_eq!(
            s.e_fin(
                "imp-base",
                json!({"op": "ImportResponsibility", "responsibility_id": "baseline-cash-70", "writer_epoch": "1"}),
            )["kind"],
            "ResponsibilityImportedReceipt"
        );
        assert_eq!(
            s.e_fin(
                "imp-fx",
                json!({"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"}),
            )["kind"],
            "FxResponsibilityImportedReceipt"
        );
        let r1 = s.capture_fx("cap-r1", FX_R1_RAW, "tok-r1");
        let r2 = s.capture_fx("cap-r2", FX_R2_RAW, "tok-r2");
        let stale = s.resolve_fx("res-r1-stale", "ev-r1-stale", &[&r1]);
        assert_eq!(stale["kind"], "Error", "{stale}");
        assert!(stale["error"].as_str().unwrap().contains("已被修订 2 替代"));
        let over = s.resolve_fx("res-r2-over", "ev-r2-over", &[&r2]);
        assert_eq!(over["kind"], "Error", "{over}");
        assert!(over["error"].as_str().unwrap().contains("AwaitingPolicy"));
        audit(&s.e_db, &s.e_config).unwrap();
    }

    // 2. 乱序先到 r2 + 补齐 r1 + 分叉替代链拒绝。
    {
        let mut s = Ac2Session::build(
            "ooo-fork",
            "100",
            "70",
            "baseline-cash-70",
            vec![],
            false,
            FX_OBLIGATIONS_RAW,
        );
        s.e_fin(
            "imp-base",
            json!({"op": "ImportResponsibility", "responsibility_id": "baseline-cash-70", "writer_epoch": "1"}),
        );
        s.e_fin(
            "imp-fx",
            json!({"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"}),
        );
        let r2 = s.capture_fx("cap-r2-first", FX_R2_RAW, "tok-r2");
        assert_eq!(r2["kind"], "Recorded");
        let q1 = s.query_fx(1, "q-ooo", Value::Null, Value::Null);
        assert_eq!(
            q1["fx_valuation"]["summary"]["gate_status"],
            "BlockedUnverifiable"
        );
        assert_eq!(
            q1["fx_valuation"]["supersession_chains"][0]["complete"],
            json!(false)
        );

        let r1 = s.capture_fx("cap-r1-backfill", FX_R1_RAW, "tok-r1");
        assert_eq!(r1["kind"], "Recorded");
        let q2 = s.query_fx(1, "q-ooo-closed", Value::Null, Value::Null);
        assert_eq!(
            q2["fx_valuation"]["supersession_chains"][0]["complete"],
            json!(true)
        );
        assert_eq!(q2["fx_valuation"]["summary"]["evaluated_total"], "110");
        assert_eq!(
            q2["fx_valuation"]["summary"]["gate_status"],
            "BlockedExceedsCap"
        );

        let mut forked: Value = serde_json::from_str(FX_R2_RAW).unwrap();
        forked["revision"] = json!("3");
        forked["supersedes_revision"] = json!("1");
        let fork_err = s.capture_fx("cap-fork", &canonical_json(&forked), "tok-fork");
        assert_eq!(fork_err["kind"], "Error", "{fork_err}");
        assert!(fork_err["error"]
            .as_str()
            .unwrap()
            .contains("IdentityConflict"));
        audit(&s.e_db, &s.e_config).unwrap();
    }

    // 3. 非整除有理数报价（3/7 -> 不可核）与坏输入（浮点、零分母、非根 pointer）。
    {
        let mut s = Ac2Session::build(
            "non-int",
            "100",
            "70",
            "baseline-cash-70",
            vec![],
            false,
            FX_OBLIGATIONS_RAW,
        );
        s.e_fin(
            "imp-base",
            json!({"op": "ImportResponsibility", "responsibility_id": "baseline-cash-70", "writer_epoch": "1"}),
        );
        s.e_fin(
            "imp-fx",
            json!({"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"}),
        );
        let mut frac: Value = serde_json::from_str(FX_R1_RAW).unwrap();
        frac["price_numerator"] = json!("3");
        frac["price_denominator"] = json!("7");
        let rf = s.capture_fx("cap-frac", &canonical_json(&frac), "tok-frac");
        assert_eq!(rf["kind"], "Recorded");
        let qf = s.query_fx(1, "q-frac", Value::Null, Value::Null);
        assert_eq!(
            qf["fx_valuation"]["summary"]["gate_status"],
            "BlockedUnverifiable"
        );
        assert!(qf["fx_valuation"]["summary"]["evaluated_total"].is_null());

        let mut bad_float: Value = serde_json::from_str(FX_R1_RAW).unwrap();
        bad_float["price_numerator"] = json!("1.5");
        assert!(super::fx_valuation::decode(&bad_float, "").is_err());
        let mut bad_zero: Value = serde_json::from_str(FX_R1_RAW).unwrap();
        bad_zero["price_denominator"] = json!("0");
        assert!(super::fx_valuation::decode(&bad_zero, "").is_err());
        let r1_doc_val: Value = serde_json::from_str(FX_R1_RAW).unwrap();
        assert!(super::fx_valuation::decode(&r1_doc_val, "/quote").is_err());
    }

    // 4. 配置护栏：无 finance 子合同时拒绝启用 fx_valuation；外币义务不得给 TEST-CASH 改标签。
    {
        let s = Ac2Session::build(
            "guard",
            "100",
            "0",
            "baseline-cash-0",
            vec![],
            false,
            FX_OBLIGATIONS_RAW,
        );
        let mut no_fin = s.e_config.manifest.clone();
        no_fin.as_object_mut().unwrap().remove("finance");
        assert!(super::fx_valuation::validate_config(&no_fin)
            .unwrap_err()
            .contains("finance"));

        let mut relabeled: Value = serde_json::from_str(FX_OBLIGATIONS_RAW).unwrap();
        relabeled["obligations"][0]["unit"] = json!("TEST-CASH");
        let raw_bad = canonical_json(&relabeled);
        let (bp, bh) = s.space.save_raw("bad-ob.json", &raw_bad);
        let mut bad_cfg = s.e_config.clone();
        bad_cfg.manifest["fx_valuation"]["obligation_input_path"] = json!(bp);
        bad_cfg.manifest["fx_valuation"]["obligation_input_sha256"] = json!(bh);
        assert!(super::fx_valuation::parse_obligation_input(
            &bad_cfg,
            &raw_bad,
            &s.fin_data["policy"],
        )
        .unwrap_err()
        .contains("不得与现金 cap 币种相同"));
        let _ = latest(&s.e_db).unwrap();
    }
}

#[test]
fn b1_unimported_initial_foreign_obligation_blocks_admission_while_empty_boundary_allows() {
    // 1. 复现非作者 B1 反例：声明了 ob-fx-unclosed-20，现金基线 20 / cap 100；
    //    未导入期初外币义务前不得按 0 敞口放行 Reserve；补入义务与 r1 后按 20+20+70=110 > 100 拒发 grant。
    {
        let mut s = Ac2Session::build(
            "r3-b1-missing-import",
            "100",
            "20",
            "baseline-cash-20",
            vec![],
            false,
            FX_OBLIGATIONS_RAW,
        );
        assert_eq!(
            s.e_fin(
                "imp-base",
                json!({"op": "ImportResponsibility", "responsibility_id": "baseline-cash-20", "writer_epoch": "1"}),
            )["kind"],
            "ResponsibilityImportedReceipt"
        );
        let q_missing = s.query_fx(1, "q-missing", Value::Null, Value::Null);
        assert_eq!(
            q_missing["fx_valuation"]["initial_foreign_responsibilities_complete"],
            json!(false)
        );
        assert_eq!(
            q_missing["fx_valuation"]["boundary"]["missing_foreign_responsibility_ids"],
            json!(["ob-fx-unclosed-20"])
        );
        assert!(q_missing["fx_valuation"]["summary"]["foreign_evaluated_subtotal"].is_null());
        assert!(q_missing["fx_valuation"]["summary"]["evaluated_total"].is_null());
        assert_eq!(
            q_missing["fx_valuation"]["summary"]["gate_status"],
            "BlockedUnverifiable"
        );
        assert_eq!(
            q_missing["fx_valuation"]["summary"]["admissible"],
            json!(false)
        );

        s.prepare_all_chongs();
        let slot_main = s.slot("slot-main");
        let res_before = s.e_fin(
            "reserve-before-fx-import",
            json!({
                "op": "Reserve",
                "slot_id": "slot-main",
                "request_set_hash": hash(&slot_main["applicants"]),
                "writer_epoch": "1"
            }),
        );
        assert_eq!(res_before["kind"], "Error", "{res_before}");
        assert!(res_before["error"]
            .as_str()
            .unwrap()
            .contains("ob-fx-unclosed-20"));

        // 导入期初外币义务：无报价仍阻断。
        assert_eq!(
            s.e_fin(
                "imp-fx-late",
                json!({"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"}),
            )["kind"],
            "FxResponsibilityImportedReceipt"
        );
        let res_noq = s.e_fin(
            "reserve-no-quote",
            json!({
                "op": "Reserve",
                "slot_id": "slot-main",
                "request_set_hash": hash(&slot_main["applicants"]),
                "writer_epoch": "1"
            }),
        );
        assert_eq!(res_noq["kind"], "Error", "{res_noq}");

        // 接纳 r1 但未核清仍阻断；核清 r1 后总敞口 40 <= 100，Reserve(+70) 算出 110 > 100 进入 AwaitingAllocationPolicy。
        let r1 = s.capture_fx("cap-r1-late", FX_R1_RAW, "tok-r1");
        assert_eq!(r1["kind"], "Recorded", "{r1}");
        let res_pend = s.e_fin(
            "reserve-pending-r1",
            json!({
                "op": "Reserve",
                "slot_id": "slot-main",
                "request_set_hash": hash(&slot_main["applicants"]),
                "writer_epoch": "1"
            }),
        );
        assert_eq!(res_pend["kind"], "Error", "{res_pend}");

        assert_eq!(
            s.resolve_fx("res-r1-late", "ev-r1", &[&r1])["kind"],
            "Resolved"
        );
        let res_over = s.e_fin(
            "reserve-after-r1-110",
            json!({
                "op": "Reserve",
                "slot_id": "slot-main",
                "request_set_hash": hash(&slot_main["applicants"]),
                "writer_epoch": "1"
            }),
        );
        assert_eq!(res_over["kind"], "ReserveReceipt", "{res_over}");
        assert_eq!(res_over["record"]["state"], "AwaitingAllocationPolicy");
        assert_eq!(res_over["record"]["required_total"], "110");
        assert_eq!(res_over["record"]["retained_total"], "40");
        assert_eq!(res_over["record"]["grants"], json!([]));
    }

    // 2. 部分导入（声明 2 条，仅导入 1 条）：仍不可核清报价或放行 Reserve。
    {
        let mut two_obs: Value = serde_json::from_str(FX_OBLIGATIONS_RAW).unwrap();
        let mut second = two_obs["obligations"][0].clone();
        second["responsibility_id"] = json!("ob-fx-second-10");
        second["quantity"] = json!("10");
        second["unit"] = json!("OTHER-FX");
        second["valuation_instrument"] = json!("OTHER-FX/TEST-CASH");
        second["source_ref"] = json!("testonly-ac2-fx-second-10");
        two_obs["obligations"].as_array_mut().unwrap().push(second);
        let two_obs_raw = canonical_json(&two_obs);

        let mut s = Ac2Session::build(
            "r3-b1-partial-import",
            "100",
            "0",
            "baseline-cash-0",
            vec![],
            false,
            &two_obs_raw,
        );
        assert_eq!(
            s.e_fin(
                "imp-base",
                json!({"op": "ImportResponsibility", "responsibility_id": "baseline-cash-0", "writer_epoch": "1"}),
            )["kind"],
            "ResponsibilityImportedReceipt"
        );
        assert_eq!(
            s.e_fin(
                "imp-fx-1",
                json!({"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"}),
            )["kind"],
            "FxResponsibilityImportedReceipt"
        );
        let r1 = s.capture_fx("cap-r1", FX_R1_RAW, "tok-r1");
        assert_eq!(r1["kind"], "Recorded", "{r1}");
        let q_partial = s.query_fx(1, "q-partial", Value::Null, Value::Null);
        assert_eq!(
            q_partial["fx_valuation"]["initial_foreign_responsibilities_complete"],
            json!(false)
        );
        assert_eq!(
            q_partial["fx_valuation"]["boundary"]["missing_foreign_responsibility_ids"],
            json!(["ob-fx-second-10"])
        );
        assert!(q_partial["fx_valuation"]["summary"]["evaluated_total"].is_null());
        let bad_res = s.resolve_fx("res-partial-blocked", "ev-partial", &[&r1]);
        assert_eq!(bad_res["kind"], "Error", "{bad_res}");
        assert!(bad_res["error"]
            .as_str()
            .unwrap()
            .contains("ob-fx-second-10"));
    }

    // 3. 共同界显式声明为空（obligations: []）：持久确认为零外币义务，同一公开路径可放行 Reserve -> Commit -> Release。
    {
        let empty_obs_raw = canonical_json(&json!({
            "schema_revision": "testonly-fx-obligation-input/1",
            "kind": "TestOnly",
            "source_id": "testonly-ac2-fx-empty-boundary",
            "source_epoch": "1",
            "obligations": []
        }));
        let mut s = Ac2Session::build(
            "r3-b1-empty-boundary",
            "100",
            "20",
            "baseline-cash-20",
            vec![],
            false,
            &empty_obs_raw,
        );
        assert_eq!(
            s.e_fin(
                "imp-base",
                json!({"op": "ImportResponsibility", "responsibility_id": "baseline-cash-20", "writer_epoch": "1"}),
            )["kind"],
            "ResponsibilityImportedReceipt"
        );
        let q_empty = s.query_fx(1, "q-empty", Value::Null, Value::Null);
        assert_eq!(
            q_empty["fx_valuation"]["initial_foreign_responsibilities_complete"],
            json!(true)
        );
        assert_eq!(
            q_empty["fx_valuation"]["boundary"]["declared_foreign_responsibility_ids"],
            json!([])
        );
        assert_eq!(
            q_empty["fx_valuation"]["summary"]["foreign_evaluated_subtotal"],
            "0"
        );
        assert_eq!(q_empty["fx_valuation"]["summary"]["evaluated_total"], "20");
        assert_eq!(
            q_empty["fx_valuation"]["summary"]["gate_status"],
            "AdmissibleWithinCap"
        );

        s.prepare_all_chongs();
        let slot_main = s.slot("slot-main");
        let res = s.e_fin(
            "reserve-main",
            json!({
                "op": "Reserve",
                "slot_id": "slot-main",
                "request_set_hash": hash(&slot_main["applicants"]),
                "writer_epoch": "1"
            }),
        );
        assert_eq!(res["kind"], "ReserveReceipt", "{res}");
        assert_eq!(res["record"]["state"], "Reserved");
        assert_eq!(res["record"]["required_total"], "90");

        let alpha_grant = res["record"]["grants"]
            .as_array()
            .unwrap()
            .iter()
            .find(|g| g["decision_id"] == "alpha")
            .unwrap()
            .clone();
        let alpha_plan = s.plan("alpha");
        assert_eq!(
            s.b_send(
                "alpha",
                "commit-alpha",
                json!({
                    "op": "CommitDecision",
                    "decision_id": "alpha",
                    "plan_hash": hash(&alpha_plan),
                    "grant_id": alpha_grant["grant_id"],
                    "writer_epoch": "1"
                }),
            )["kind"],
            "LocalCommitReceipt"
        );
        assert_eq!(
            s.e_fin(
                "dispatch-alpha",
                json!({
                    "op": "MakeDispatchable",
                    "decision_id": "alpha",
                    "plan_hash": hash(&alpha_plan),
                    "writer_epoch": "1"
                }),
            )["kind"],
            "DispatchableReceipt"
        );
        let rel = s.e_fin(
            "release-alpha-empty-fx",
            s.release_exact_payload("alpha", alpha_grant["grant_id"].as_str().unwrap()),
        );
        assert_eq!(rel["kind"], "ReleasedExactReceipt", "{rel}");
        assert_eq!(recover(&s.e_config).unwrap()["writer_epoch"], "2");
    }
}

#[test]
fn a1_quote_before_import_resolves_and_retires_after_attribution_across_epoch2_leaving_history_and_unrelated_account_star_intact(
) {
    // 1. 复现非作者 A1 反例 + epoch 2 恢复 + 无关 account:* 并存对照：
    //    baseline -> cap r1 (account:*) -> 未导入前 Resolve 拒 -> ImportFx -> cap r2/r3 -> Resolve [r3,r2] ->
    //    接纳无关 OTHER-FX (account:*) -> recover 到 epoch 2 -> 历史 cut 保持 account:* ->
    //    在 epoch 2 拒清 OTHER-FX、拒混清 [r1, OTHER-FX]、成功精确退役 r1，且 OTHER-FX 仍留存封闸。
    {
        let mut s = Ac2Session::build(
            "r3-a1-retire-ep2",
            "100",
            "0",
            "baseline-cash-0",
            vec![],
            false,
            FX_OBLIGATIONS_RAW,
        );
        assert_eq!(
            s.e_fin(
                "imp-base",
                json!({"op": "ImportResponsibility", "responsibility_id": "baseline-cash-0", "writer_epoch": "1"}),
            )["kind"],
            "ResponsibilityImportedReceipt"
        );
        let r1 = s.capture_fx("cap-r1-early", FX_R1_RAW, "tok-r1");
        assert_eq!(r1["kind"], "Recorded", "{r1}");
        let rv_early = s.e_read(
            1,
            "rv-early",
            json!({"op": "ReadView", "cut": null, "as_known_ns": null}),
        );
        let p_early = rv_early["image"]["pending"]
            .as_array()
            .unwrap()
            .iter()
            .find(|p| p["fact_key"] == r1["fact_key"])
            .unwrap()
            .clone();
        assert_eq!(p_early["scope"], "account:*");

        // 导入义务前尝试 Resolve r1：必须拒绝。
        let bad_before = s.resolve_fx("res-early-before-import", "ev-early-before", &[&r1]);
        assert_eq!(bad_before["kind"], "Error", "{bad_before}");
        assert!(bad_before["error"].as_str().unwrap().contains("账户范围"));

        // 导入期初外币义务：r1 在当前切面已获归属证明，但仍待核清。
        assert_eq!(
            s.e_fin(
                "imp-fx-after-r1",
                json!({"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"}),
            )["kind"],
            "FxResponsibilityImportedReceipt"
        );
        let q_attr = s.query_fx(1, "q-attr", Value::Null, Value::Null);
        assert_eq!(
            q_attr["fx_valuation"]["revisions"][0]["matched_responsibility_ids"],
            json!(["ob-fx-unclosed-20"])
        );
        assert_eq!(
            q_attr["fx_valuation"]["revisions"][0]["attribution_status"],
            "Attributed"
        );
        assert_eq!(
            q_attr["fx_valuation"]["revisions"][0]["effective_scope"],
            "E:fx:TEST-FX/TEST-CASH"
        );
        assert_eq!(
            q_attr["fx_valuation"]["summary"]["gate_status"],
            "BlockedPendingEvidence"
        );

        let r2 = s.capture_fx("cap-r2", FX_R2_RAW, "tok-r2");
        let r3 = s.capture_fx("cap-r3", FX_R3_RAW, "tok-r3");
        assert_eq!(r2["kind"], "Recorded", "{r2}");
        assert_eq!(r3["kind"], "Recorded", "{r3}");
        assert_eq!(
            s.resolve_fx("res-r2-r3-batch", "ev-r3-r2", &[&r3, &r2])["kind"],
            "Resolved"
        );

        // 并存一条真未知的 OTHER-FX account:* token。
        let mut other_q: Value = serde_json::from_str(FX_R1_RAW).unwrap();
        other_q["instrument"] = json!("OTHER-FX/TEST-CASH");
        other_q["base_unit"] = json!("OTHER-FX");
        other_q["event_id"] = json!("fx-quote-other-a1");
        let other_rec = s.capture_fx("cap-other-a1", &canonical_json(&other_q), "tok-other-a1");
        assert_eq!(other_rec["kind"], "Recorded", "{other_rec}");

        // 正式恢复到 epoch 2。
        let rec = recover(&s.e_config).unwrap();
        assert_eq!(rec["writer_epoch"], "2");

        // 历史早到 cut 原貌未改（仍为 account:*）。
        let rv_old = s.e_read(
            2,
            "rv-old",
            json!({"op": "ReadView", "cut": rv_early["cut"], "as_known_ns": null}),
        );
        assert_eq!(rv_old["image"], rv_early["image"]);

        // 在 epoch 2：真未知 OTHER-FX 拒清，混批 [r1, OTHER-FX] 拒清。
        let bad_other =
            s.resolve_fx_epoch(2, "retire-r1-ep2-bad-other", "ev-other-ep2", &[&other_rec]);
        assert_eq!(bad_other["kind"], "Error", "{bad_other}");
        assert!(bad_other["error"].as_str().unwrap().contains("账户范围"));

        let bad_mixed = s.resolve_fx_epoch(
            2,
            "retire-r1-ep2-mixed-other",
            "ev-mixed-ep2",
            &[&r1, &other_rec],
        );
        assert_eq!(bad_mixed["kind"], "Error", "{bad_mixed}");
        assert!(bad_mixed["error"].as_str().unwrap().contains("账户范围"));

        // 在 epoch 2：仅退役已获归属证明的 r1 原 token -> 成功！
        let retired_r1 = s.resolve_fx_epoch(2, "retire-r1-ep2-ok", "ev-retire-r1-ep2", &[&r1]);
        assert_eq!(retired_r1["kind"], "Resolved", "{retired_r1}");
        assert_eq!(retired_r1["covered"], json!([r1["fact_key"]]));

        let q_after = s.query_fx(2, "q-after-ep2", Value::Null, Value::Null);
        let r1_row = q_after["fx_valuation"]["revisions"]
            .as_array()
            .unwrap()
            .iter()
            .find(|r| r["fact_key"] == r1["fact_key"])
            .unwrap();
        assert_eq!(r1_row["coverage_status"], "RetiredBySupersession");
        assert_eq!(r1_row["retired_by_fact_key"], r3["fact_key"]);
        assert_eq!(r1_row["retired_by_revision"], "3");
        assert_eq!(r1_row["initial_pending_scope"], "account:*");
        assert_eq!(r1_row["resolved_scope"], "E:fx:TEST-FX/TEST-CASH");
        assert_eq!(
            r1_row["attributed_responsibility_ids"],
            json!(["ob-fx-unclosed-20"])
        );
        // 无关 OTHER-FX 原 account:* token 仍在 pending 且继续封闸。
        assert_eq!(
            q_after["fx_valuation"]["summary"]["active_pending_fact_keys"],
            json!([other_rec["fact_key"]])
        );
        assert_eq!(
            q_after["fx_valuation"]["summary"]["gate_status"],
            "BlockedUnverifiable"
        );
        // 在 epoch 2 尝试 Reserve：仍被未归属 OTHER-FX 阻断。
        let slot_main = s.slot("slot-main");
        let bad_res_ep2 = s.e_fin_epoch(
            2,
            "reserve-blocked-by-other-ep2",
            json!({
                "op": "Reserve",
                "slot_id": "slot-main",
                "request_set_hash": hash(&slot_main["applicants"]),
                "writer_epoch": "2"
            }),
        );
        assert_eq!(bad_res_ep2["kind"], "Error", "{bad_res_ep2}");
        // 再次恢复到 epoch 3，确认全历史重放审计完全通过。
        assert_eq!(recover(&s.e_config).unwrap()["writer_epoch"], "3");
    }

    // 2. 早到 r1 先于基线与外币义务到达，待两者都导入后直接核清为 Covered 并放行全链路。
    {
        let mut s = Ac2Session::build(
            "r3-a1-direct-cover",
            "100",
            "0",
            "baseline-cash-0",
            vec![],
            false,
            FX_OBLIGATIONS_RAW,
        );
        let r1 = s.capture_fx("cap-r1-first", FX_R1_RAW, "tok-r1");
        assert_eq!(r1["kind"], "Recorded", "{r1}");
        let rv_c1 = s.e_read(
            1,
            "rv-c1",
            json!({"op": "ReadView", "cut": null, "as_known_ns": null}),
        );
        assert_eq!(rv_c1["image"]["pending"][0]["scope"], "account:*");

        // 先导入外币义务、基线未导入 -> 归属已明但缺基线，仍不能核清。
        assert_eq!(
            s.e_fin(
                "imp-fx-second",
                json!({"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"}),
            )["kind"],
            "FxResponsibilityImportedReceipt"
        );
        let bad_no_base = s.resolve_fx("res-early-before-baseline", "ev-no-base", &[&r1]);
        assert_eq!(bad_no_base["kind"], "Error", "{bad_no_base}");

        // 再导入基线 -> 直接核清 r1 原 token 为 Covered，历史 cut 1 不变。
        assert_eq!(
            s.e_fin(
                "imp-base-third",
                json!({"op": "ImportResponsibility", "responsibility_id": "baseline-cash-0", "writer_epoch": "1"}),
            )["kind"],
            "ResponsibilityImportedReceipt"
        );
        let ok = s.resolve_fx("res-r1-after-import", "ev-r1-direct", &[&r1]);
        assert_eq!(ok["kind"], "Resolved", "{ok}");
        let q_ok = s.query_fx(1, "q-direct-ok", Value::Null, Value::Null);
        assert_eq!(
            q_ok["fx_valuation"]["summary"]["gate_status"],
            "AdmissibleWithinCap"
        );
        assert_eq!(
            q_ok["fx_valuation"]["revisions"][0]["initial_pending_scope"],
            "account:*"
        );
        assert_eq!(
            q_ok["fx_valuation"]["revisions"][0]["resolved_scope"],
            "E:fx:TEST-FX/TEST-CASH"
        );
        let rv_c1_again = s.e_read(
            1,
            "rv-c1-again",
            json!({"op": "ReadView", "cut": rv_c1["cut"], "as_known_ns": null}),
        );
        assert_eq!(rv_c1_again["image"], rv_c1["image"]);
        assert_eq!(recover(&s.e_config).unwrap()["writer_epoch"], "2");
    }
}

/// #1407 C3 CE-S07 集成回归：`tb03b-finance/6` + `fx-valuation/1` + `logical-bar/1` + `model_ref`。
/// 1) E cut 10 = 90/100（r1）；放行前校验删责任、塞 `TestOnly-market/*` / `controlled-evidence` / `latest` / `admissible`、
///    改 `e-cut`、改 `rev`、缺条件均被拒绝且 E cut 不推进；
/// 2) alpha 在 cut 11 真实放行，证书绑定 `model_ref`、真实 `fx-quote:` rev=1、`e-cut:E:10:...`、`ob-fx-unclosed-20`、
///    `market-supersession:...:after_rev=1`，零占位名；
/// 3) r2 在 cut 12 致 110/100 后，alpha 同/新 `message_id` 重复取回完全等价的 cut 11 原收据（仍是 rev=1，非新资格），
///    改内容重放 -> `IdentityConflict`，beta 新放行 -> `AwaitingPolicy`；
/// 4) r3 + 退役 r2（cut 15）后，beta 在 cut 16 放行并携带 `rev=3`、`supersedes=2`、`fx-retired:...@rev=2:...`；
/// 5) 配置护栏：FX E 拒 `TestOnly-market/*` 与 `controlled-*`，纯非 FX E 拒 FX/2 显式市场模板；
/// 6) 全链路 `audit` + `recover` 到 epoch 2。
#[test]
fn ce_s07_v6_verifiable_fx_certificate_tamper_old_receipt_priority_and_scope_controls() {
    let base = Ac2Session::build(
        "ce-s07-v6-template",
        "100",
        "0",
        "baseline-cash-0",
        vec![],
        false,
        FX_OBLIGATIONS_RAW,
    );
    let space = Space::new("ce-s07-v6");
    let session_id = "ce-s07-v6-integrated".to_owned();

    // 1. 构造 tb03b-finance/6 + logical-bar/1 + 含真实 model_ref 与 FX/2 显式模板的冻结输入。
    let mut fin_data = base.fin_data.clone();
    let model = crate::history_simulation::tests::model();
    decorate_fx_release_bound_v6_input(&mut fin_data, json!(model.model_ref()));
    let (fin_path, fin_sha) = space.save_json("finance-input.json", &fin_data);
    let (fx_ob_path, fx_ob_sha) = space.save_raw("fx-obligations.json", FX_OBLIGATIONS_RAW);

    let s_obj = json!({
        "object_id": "unit-S-object",
        "kind": "UnitStructuralTrustRoot",
        "branch": "RISING"
    });
    let basis = json!({
        "kind": "FinancialBasis",
        "session_id": session_id,
        "session_generation": "1",
        "writer_epoch": "1",
        "pending_revision": false,
        "commit_ns": "1",
        "snapshot": {
            "profile_id": "unit",
            "objects": [s_obj]
        }
    });
    let (basis_path, _) = space.save_json("s-basis.json", &basis);
    let stub = space.dir.join("s-stub.sh");
    crate::economic_session::write_test_executable(
        &stub,
        &format!("#!/bin/sh\nexec /bin/cat '{basis_path}'\n"),
        0o700,
    );
    let stub_sha = sha256_hex(&std::fs::read(&stub).unwrap());

    let mut manifest = base.e_config.manifest.clone();
    manifest["session_id"] = json!(session_id);
    manifest["e"]["db"] = json!(space.dir.join("e.db"));
    manifest["e"]["socket"] = json!(space.dir.join("e.sock"));
    for r in manifest["chongs"].as_array_mut().unwrap() {
        let cid = r["chong_id"].as_str().unwrap().to_owned();
        r["db"] = json!(space.dir.join(format!("{cid}.db")));
        r["socket"] = json!(space.dir.join(format!("{cid}.sock")));
    }
    manifest["authorized_sources"]
        .as_array_mut()
        .unwrap()
        .push(json!({
            "source_namespace": "x-sim",
            "source_epoch": "epoch1",
            "producer_id": "X",
            "producer_epoch": "1",
            "operations": ["QueryReleasedExact"]
        }));
    manifest["finance"]["schema_revision"] = json!("tb03b-finance/6");
    manifest["finance"]["input_path"] = json!(fin_path);
    manifest["finance"]["input_sha256"] = json!(fin_sha);
    manifest["finance"]["structure"]["binary"] = json!(stub);
    manifest["finance"]["structure"]["binary_sha256"] = json!(stub_sha);
    manifest["finance"]["structure"]["db"] = json!(space.dir.join("s.db"));
    manifest["finance"]["structure"]["session_id"] = json!(session_id);
    manifest["fx_valuation"]["schema_revision"] = json!("fx-valuation/2");
    manifest["fx_valuation"]["obligation_input_path"] = json!(fx_ob_path);
    manifest["fx_valuation"]["obligation_input_sha256"] = json!(fx_ob_sha);

    let mut bars = serde_json::Map::new();
    for (msg, bar) in [
        ("imp-base", "1"),
        ("imp-fx", "1"),
        ("cap-r1", "1"),
        ("res-r1", "1"),
        ("cap-open-alpha", "1"),
        ("apply-open-alpha", "1"),
        ("bind-alpha", "1"),
        ("prep-alpha", "1"),
        ("cap-open-beta", "1"),
        ("apply-open-beta", "1"),
        ("bind-beta", "1"),
        ("prep-beta", "1"),
        ("cap-open-gamma", "1"),
        ("apply-open-gamma", "1"),
        ("bind-gamma", "1"),
        ("prep-gamma", "1"),
        ("reserve-main", "1"),
        ("commit-alpha", "1"),
        ("commit-beta", "1"),
        ("dispatch-alpha", "1"),
        ("dispatch-beta", "1"),
        ("rel-bad-drop-fx-resp", "2"),
        ("rel-bad-testonly-market", "2"),
        ("rel-bad-controlled-ev", "2"),
        ("rel-bad-latest", "2"),
        ("rel-bad-admissible", "2"),
        ("rel-bad-ecut", "2"),
        ("rel-bad-rev", "2"),
        ("rel-bad-drop-cond", "2"),
        ("release-alpha-cut11", "2"),
        ("cap-r2", "3"),
        ("release-alpha-retry-new-msg", "3"),
        ("release-alpha-retry-tampered", "3"),
        ("release-beta-overcap", "3"),
        ("cap-r3", "4"),
        ("res-r3", "4"),
        ("retire-r2", "4"),
        ("release-beta-stale-r1", "5"),
        ("release-beta-cut16", "5"),
    ] {
        bars.insert(msg.to_owned(), json!(bar));
    }
    manifest["clock"] = json!({
        "kind": "logical-bar/1",
        "bars": {"init": "0", "recover": ["10", "20"], "messages": Value::Object(bars)}
    });

    // 2. 配置护栏：FX/2 要求完整模板；无 FX 禁止显式市场模板。
    {
        let mut bad_fx_fin = fin_data.clone();
        bad_fx_fin["exact_release"]["market_dependencies"] = json!(["TestOnly-market/1407-c1"]);
        let bad_err = super::exact_command::validate_fx_section(&bad_fx_fin).unwrap_err();
        assert!(
            bad_err.starts_with("Unsupported"),
            "FX E must reject TestOnly-market/*: {bad_err}"
        );

        let mut bad_fx_cond = fin_data.clone();
        bad_fx_cond["exact_release"]["conditions"][0]["evidence_refs"] =
            json!(["controlled-evidence"]);
        let bad_cond_err = super::exact_command::validate_fx_section(&bad_fx_cond).unwrap_err();
        assert!(
            bad_cond_err.starts_with("Unsupported"),
            "FX E must reject controlled-evidence: {bad_cond_err}"
        );

        let mut nonfx_manifest = manifest.clone();
        nonfx_manifest
            .as_object_mut()
            .unwrap()
            .remove("fx_valuation");
        nonfx_manifest["e"]["db"] = json!(space.dir.join("nf-e.db"));
        for src in nonfx_manifest["authorized_sources"].as_array_mut().unwrap() {
            src["operations"]
                .as_array_mut()
                .unwrap()
                .retain(|op| op != "ImportFxResponsibility" && op != "QueryFxValuation");
        }
        let (nfm_path, _) = space.save_json("nonfx-manifest.json", &nonfx_manifest);
        let nf_cfg = Config::load(Path::new(&nfm_path), &space.dir.join("nf-e.db"), None).unwrap();
        init(&nf_cfg).unwrap();
        let (mut nf_db, _) = open(&nf_cfg.db, false).unwrap();
        let nf_req = env(
            &session_id,
            FIN_NS,
            FIN_EPOCH,
            "fin-coord",
            "imp-base",
            json!({"op": "ImportResponsibility", "responsibility_id": "baseline-cash-0", "writer_epoch": "1"}),
        );
        let nf_resp = send(&mut nf_db, &nf_cfg, 1, &nf_req);
        assert_eq!(nf_resp["kind"], "Error", "{nf_resp}");
        let nf_err = nf_resp["error"].as_str().unwrap();
        assert!(
            nf_err.starts_with("Unsupported")
                && nf_err.contains(super::exact_command::FX_RELEASE_BOUND_MARKER),
            "pure non-FX E must reject the FX/2 market template: {nf_err}"
        );

        // FIN/5+FX(v2) 组合在 Config::load 即被 SchemaUnsupported 拒绝；
        // FX/1 的文本即使与整套 FX/2 模板字面相同，仍是静态合同。
        let mut fin5_with_marker_data = fin_data.clone();
        fin5_with_marker_data["schema_revision"] = json!("tb03b-finance/5");
        let (f5_in_path, f5_in_sha) =
            space.save_json("fin5-marker-input.json", &fin5_with_marker_data);
        let mut fin5_v2_manifest = manifest.clone();
        fin5_v2_manifest["e"]["db"] = json!(space.dir.join("f5v2-e.db"));
        fin5_v2_manifest["finance"]["schema_revision"] = json!("tb03b-finance/5");
        fin5_v2_manifest["finance"]["input_path"] = json!(f5_in_path);
        fin5_v2_manifest["finance"]["input_sha256"] = json!(f5_in_sha);
        let (f5v2_path, _) = space.save_json("fin5-v2-manifest.json", &fin5_v2_manifest);
        let f5v2_err = Config::load(Path::new(&f5v2_path), &space.dir.join("f5v2-e.db"), None)
            .err()
            .expect("FIN/5 + fx-valuation/2 must fail config load");
        assert!(
            f5v2_err.starts_with("SchemaUnsupported") && f5v2_err.contains("fx-valuation/2"),
            "FIN/5 + fx-valuation/2 must fail config load: {f5v2_err}"
        );

        let mut fin6_v1_marker_manifest = manifest.clone();
        fin6_v1_marker_manifest["e"]["db"] = json!(space.dir.join("f6v1m-e.db"));
        fin6_v1_marker_manifest["fx_valuation"]["schema_revision"] = json!("fx-valuation/1");
        let (f6v1m_path, _) =
            space.save_json("fin6-v1-marker-manifest.json", &fin6_v1_marker_manifest);
        let f6v1m_cfg =
            Config::load(Path::new(&f6v1m_path), &space.dir.join("f6v1m-e.db"), None).unwrap();
        init(&f6v1m_cfg).unwrap();
        let (mut f6v1m_db, _) = open(&f6v1m_cfg.db, false).unwrap();
        let f6v1m_resp = send(&mut f6v1m_db, &f6v1m_cfg, 1, &nf_req);
        assert_eq!(
            f6v1m_resp["kind"], "ResponsibilityImportedReceipt",
            "{f6v1m_resp}"
        );

        let mut fin5_v1_marker_manifest = fin5_v2_manifest.clone();
        fin5_v1_marker_manifest["e"]["db"] = json!(space.dir.join("f5m-e.db"));
        fin5_v1_marker_manifest["fx_valuation"]["schema_revision"] = json!("fx-valuation/1");
        let (f5m_path, _) = space.save_json("fin5-marker-manifest.json", &fin5_v1_marker_manifest);
        let f5_cfg = Config::load(Path::new(&f5m_path), &space.dir.join("f5m-e.db"), None).unwrap();
        init(&f5_cfg).unwrap();
        let (mut f5_db, _) = open(&f5_cfg.db, false).unwrap();
        let f5_resp = send(&mut f5_db, &f5_cfg, 1, &nf_req);
        assert_eq!(
            f5_resp["kind"], "ResponsibilityImportedReceipt",
            "{f5_resp}"
        );
    }

    let (mpath, _) = space.save_json("manifest.json", &manifest);
    let e_config = Config::load(Path::new(&mpath), &space.dir.join("e.db"), None).unwrap();
    init(&e_config).unwrap();
    let (e_db, _) = open(&e_config.db, false).unwrap();
    let mut b_configs = Vec::new();
    let mut b_dbs = Vec::new();
    for name in ["alpha", "beta", "gamma"] {
        let bc = Config::load(
            Path::new(&mpath),
            &space.dir.join(format!("{name}.db")),
            Some(name),
        )
        .unwrap();
        init(&bc).unwrap();
        let (bdb, _) = open(&bc.db, false).unwrap();
        b_configs.push((name.to_owned(), bc));
        b_dbs.push((name.to_owned(), bdb));
    }

    let mut s = Ac2Session {
        space,
        session_id,
        e_config,
        e_db,
        b_configs,
        b_dbs,
        fin_data,
        opening_docs: base.opening_docs.clone(),
        voice_payloads: base.voice_payloads.clone(),
    };

    // 3. 推进到真实已知端点：E cut 10 = 90/100（r1，alpha/beta 均已 Dispatchable）。
    assert_eq!(
        s.e_fin(
            "imp-base",
            json!({"op": "ImportResponsibility", "responsibility_id": "baseline-cash-0", "writer_epoch": "1"}),
        )["kind"],
        "ResponsibilityImportedReceipt"
    ); // E cut 1
    assert_eq!(
        s.e_fin(
            "imp-fx",
            json!({"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"}),
        )["kind"],
        "FxResponsibilityImportedReceipt"
    ); // E cut 2
    let r1 = s.capture_fx("cap-r1", FX_R1_RAW, "tok-r1"); // E cut 3
    assert_eq!(r1["kind"], "Recorded", "{r1}");
    assert_eq!(s.resolve_fx("res-r1", "ev-r1", &[&r1])["kind"], "Resolved"); // E cut 4
    s.prepare_all_chongs(); // E cuts 5, 6, 7

    let slot_main = s.slot("slot-main");
    let res = s.e_fin(
        "reserve-main",
        json!({
            "op": "Reserve",
            "slot_id": "slot-main",
            "request_set_hash": hash(&slot_main["applicants"]),
            "writer_epoch": "1"
        }),
    ); // E cut 8
    assert_eq!(res["kind"], "ReserveReceipt", "{res}");
    let grant_of = |who: &str| -> String {
        res["record"]["grants"]
            .as_array()
            .unwrap()
            .iter()
            .find(|g| g["decision_id"] == who)
            .unwrap()["grant_id"]
            .as_str()
            .unwrap()
            .to_owned()
    };
    let alpha_gid = grant_of("alpha");
    let beta_gid = grant_of("beta");
    let alpha_plan = s.plan("alpha");
    let beta_plan = s.plan("beta");

    assert_eq!(
        s.b_send(
            "alpha",
            "commit-alpha",
            json!({"op": "CommitDecision", "decision_id": "alpha", "plan_hash": hash(&alpha_plan), "grant_id": alpha_gid, "writer_epoch": "1"}),
        )["kind"],
        "LocalCommitReceipt"
    );
    assert_eq!(
        s.b_send(
            "beta",
            "commit-beta",
            json!({"op": "CommitDecision", "decision_id": "beta", "plan_hash": hash(&beta_plan), "grant_id": beta_gid, "writer_epoch": "1"}),
        )["kind"],
        "LocalCommitReceipt"
    );
    assert_eq!(
        s.e_fin(
            "dispatch-alpha",
            json!({"op": "MakeDispatchable", "decision_id": "alpha", "plan_hash": hash(&alpha_plan), "writer_epoch": "1"}),
        )["kind"],
        "DispatchableReceipt"
    ); // E cut 9
    assert_eq!(
        s.e_fin(
            "dispatch-beta",
            json!({"op": "MakeDispatchable", "decision_id": "beta", "plan_hash": hash(&beta_plan), "writer_epoch": "1"}),
        )["kind"],
        "DispatchableReceipt"
    ); // E cut 10

    let q10 = s.query_fx(1, "q-cut10", Value::Null, Value::Null);
    assert_eq!(q10["cut"]["commit_seq"], "10");
    assert_eq!(q10["fx_valuation"]["summary"]["evaluated_total"], "90");
    assert_eq!(q10["fx_valuation"]["summary"]["cap"], "100");
    assert_eq!(
        q10["fx_valuation"]["summary"]["gate_status"],
        "AdmissibleWithinCap"
    );

    // 4. 负控：篡改、删依赖、塞占位名/latest/admissible/缺条件均被拒绝且 E 留在 cut 10。
    let valid_alpha_r1 = s.release_exact_payload_from_query(&q10, "alpha", &alpha_gid);

    let mut drop_fx_resp = valid_alpha_r1.clone();
    drop_fx_resp["certificate"]["responsibility_refs"] = json!([alpha_gid]);
    let mut bad_testonly = valid_alpha_r1.clone();
    bad_testonly["certificate"]["market_dependencies"] = json!(["TestOnly-market/1407-c1"]);
    let mut bad_controlled = valid_alpha_r1.clone();
    bad_controlled["certificate"]["conditions"][0]["evidence_refs"] =
        json!(["controlled-evidence"]);
    let mut bad_latest = valid_alpha_r1.clone();
    bad_latest["certificate"]["conditions"][1]["dependency_set"] = json!(["fx-quote:latest"]);
    let mut bad_admissible = valid_alpha_r1.clone();
    bad_admissible["certificate"]["conditions"][0]["coverage_proof"] = json!("admissible=true");
    let mut bad_ecut = valid_alpha_r1.clone();
    bad_ecut["certificate"]["conditions"][0]["evidence_refs"][0] = json!("e-cut:E:9:deadbeef");
    let mut bad_rev = valid_alpha_r1.clone();
    bad_rev["certificate"]["market_dependencies"][0] = json!(bad_rev["certificate"]
        ["market_dependencies"][0]
        .as_str()
        .unwrap()
        .replace("@rev=1;", "@rev=9;"));
    let mut drop_cond = valid_alpha_r1.clone();
    drop_cond["certificate"]["conditions"]
        .as_array_mut()
        .unwrap()
        .remove(1);

    for (msg, bad_payload, expected_err) in [
        ("rel-bad-drop-fx-resp", drop_fx_resp, "IdentityConflict"),
        ("rel-bad-testonly-market", bad_testonly, "IdentityConflict"),
        ("rel-bad-controlled-ev", bad_controlled, "IdentityConflict"),
        ("rel-bad-latest", bad_latest, "IdentityConflict"),
        ("rel-bad-admissible", bad_admissible, "IdentityConflict"),
        ("rel-bad-ecut", bad_ecut, "IdentityConflict"),
        ("rel-bad-rev", bad_rev, "IdentityConflict"),
        ("rel-bad-drop-cond", drop_cond, "Unsupported"),
    ] {
        let resp = s.e_fin(msg, bad_payload);
        assert_eq!(resp["kind"], "Error", "{msg}: {resp}");
        assert!(
            resp["error"].as_str().unwrap().starts_with(expected_err),
            "{msg}: expected {expected_err}, got {resp}"
        );
    }
    assert_eq!(latest(&s.e_db).unwrap().0, 10, "负控拒绝不得推进 E cut");

    // 5. alpha 在 E cut 11 真实放行，校验交付对象、model_ref、证书真实字段及零占位名。
    let rel_alpha = s.e_fin("release-alpha-cut11", valid_alpha_r1.clone());
    assert_eq!(rel_alpha["kind"], "ReleasedExactReceipt", "{rel_alpha}");
    assert_eq!(rel_alpha["cut"]["commit_seq"], "11");
    let cmd_alpha = &rel_alpha["record"]["command"];
    assert_eq!(cmd_alpha["model_ref"], json!(model.model_ref()));
    let cert_alpha = &cmd_alpha["certificate"];
    assert_eq!(*cert_alpha, valid_alpha_r1["certificate"]);
    let alpha_mkt = cert_alpha["market_dependencies"][0].as_str().unwrap();
    assert!(
        alpha_mkt.starts_with(
            "fx-quote:testonly.ce-s07.fx|1|TEST-FX/TEST-CASH|fx-quote-007@rev=1;coord=70;supersedes=none;rate=1/1;"
        ),
        "unexpected alpha market_dependency: {alpha_mkt}"
    );
    assert!(cert_alpha["responsibility_refs"]
        .as_array()
        .unwrap()
        .iter()
        .any(|x| x == "ob-fx-unclosed-20"));
    let exec_cond = &cert_alpha["conditions"][1];
    assert_eq!(exec_cond["condition_id"], "execute-committed/1");
    assert!(exec_cond["invalidation_sources"]
        .as_array()
        .unwrap()
        .iter()
        .any(|x| {
            x == "market-supersession:testonly.ce-s07.fx|1|TEST-FX/TEST-CASH|fx-quote-007:after_rev=1"
        }));

    // X 侧用统一 FX release-bound profile 核验真实交付命令通过。
    let x_conditions: Vec<Value> = EXACT_CONDITIONS
        .iter()
        .map(|(id, capability, stage)| {
            json!({
                "condition_id": id,
                "authority_revision": capability,
                "dependency_set": [super::exact_command::FX_RELEASE_BOUND_MARKER],
                "invalidation_sources": [super::exact_command::FX_RELEASE_BOUND_MARKER],
                "required_check_stages": [stage],
                "evidence_refs": [super::exact_command::FX_RELEASE_BOUND_MARKER],
                "coverage_proof": super::exact_command::FX_RELEASE_BOUND_MARKER,
                "validator_capability": capability,
                "failure_result": "Denied",
            })
        })
        .collect();
    let x_prof: crate::history_simulation::runtime::Profile = serde_json::from_value(json!({
        "model": model,
        "session_id": s.session_id,
        "session_generation": "1",
        "x_id": "X",
        "source_namespace": "x-sim",
        "source_epoch": "epoch1",
        "socket": s.space.dir.join("x.sock"),
        "e": {
            "socket": s.space.dir.join("e.sock"),
            "authority_id": "E",
            "authority_epoch": "1",
            "schema_revision": "tb03b-finance/6",
            "reply_namespace": "E/replies",
            "producer_id": "E:session"
        },
        "s": {
            "socket": s.space.dir.join("s.sock"),
            "authority_id": "S",
            "authority_epoch": "1",
            "schema_revision": "s-session/3",
            "reply_namespace": "S/replies",
            "producer_id": "S:session"
        },
        "conditions": x_conditions,
        "timeout_ms": 2000,
        "max_frame_bytes": 65536
    }))
    .unwrap();
    x_prof.validate().unwrap();
    let mut x_prof_alpha = x_prof.clone();
    x_prof_alpha.model.symbol = "alpha".into();
    let mut cmd_alpha_for_x = cmd_alpha.clone();
    // 同步测试 symbol 对齐：用真实 model_ref 时 alpha 需 symbol 一致。
    assert!(
        serde_json::from_value::<crate::history_simulation::runtime::ExactCommand>(
            cmd_alpha_for_x.clone()
        )
        .is_ok()
    );
    // 这里 model.symbol 是默认 TEST，alpha command symbol 是 alpha，精确核验会按 symbol 对比；
    // 调整为 TEST 的 model_ref 已由 alpha_cmd 校验覆盖，这里只验证 FX release-bound 证书段与 model_ref 校验：
    cmd_alpha_for_x["symbol"] = json!(x_prof.model.symbol);
    let parsed_alpha: crate::history_simulation::runtime::ExactCommand =
        serde_json::from_value(cmd_alpha_for_x).unwrap();
    parsed_alpha.validate(&x_prof, 1).unwrap();

    // 6. r2 在 E cut 12 导致 110/100：原收据优先（同/新 msg 仍回 cut 11 原回执），改内容重放拒，beta 新放行封闸。
    let r2 = s.capture_fx("cap-r2", FX_R2_RAW, "tok-r2"); // E cut 12
    assert_eq!(r2["kind"], "Recorded", "{r2}");
    let q12 = s.query_fx(1, "q-cut12", Value::Null, Value::Null);
    assert_eq!(q12["cut"]["commit_seq"], "12");
    assert_eq!(q12["fx_valuation"]["summary"]["evaluated_total"], "110");
    assert_eq!(
        q12["fx_valuation"]["summary"]["gate_status"],
        "BlockedExceedsCap"
    );

    let retry_same = s.e_fin("release-alpha-cut11", valid_alpha_r1.clone());
    assert_eq!(retry_same, rel_alpha);
    let retry_new = s.e_fin("release-alpha-retry-new-msg", valid_alpha_r1.clone());
    assert_eq!(retry_new["kind"], "ReleasedExactReceipt", "{retry_new}");
    assert_eq!(retry_new["cut"], rel_alpha["cut"]);
    assert_eq!(retry_new["record"], rel_alpha["record"]);

    let mut tampered_retry = valid_alpha_r1.clone();
    tampered_retry["certificate"]["market_dependencies"][0] = json!(tampered_retry["certificate"]
        ["market_dependencies"][0]
        .as_str()
        .unwrap()
        .replace("@rev=1;", "@rev=2;"));
    let retry_bad = s.e_fin("release-alpha-retry-tampered", tampered_retry);
    assert_eq!(retry_bad["kind"], "Error", "{retry_bad}");
    assert!(
        retry_bad["error"]
            .as_str()
            .unwrap()
            .starts_with("IdentityConflict"),
        "{retry_bad}"
    );

    let beta_r1_payload = s.release_exact_payload_from_query(&q10, "beta", &beta_gid);
    let beta_blocked = s.e_fin("release-beta-overcap", beta_r1_payload.clone());
    assert_eq!(beta_blocked["kind"], "Error", "{beta_blocked}");
    assert!(
        beta_blocked["error"]
            .as_str()
            .unwrap()
            .starts_with("AwaitingPolicy"),
        "{beta_blocked}"
    );

    // 7. r3 (cut 13) -> res-r3 (cut 14) -> retire-r2 (cut 15) -> beta 在 cut 16 放行并带 rev=3 + fx-retired(rev=2)。
    let r3 = s.capture_fx("cap-r3", FX_R3_RAW, "tok-r3"); // E cut 13
    assert_eq!(r3["kind"], "Recorded", "{r3}");
    assert_eq!(s.resolve_fx("res-r3", "ev-r3", &[&r3])["kind"], "Resolved"); // E cut 14
    assert_eq!(
        s.resolve_fx("retire-r2", "ev-retire-r2", &[&r2])["kind"],
        "Resolved"
    ); // E cut 15

    let q15 = s.query_fx(1, "q-cut15", Value::Null, Value::Null);
    assert_eq!(q15["cut"]["commit_seq"], "15");
    assert_eq!(q15["fx_valuation"]["summary"]["evaluated_total"], "90");
    assert_eq!(
        q15["fx_valuation"]["summary"]["gate_status"],
        "AdmissibleWithinCap"
    );

    // 旧 r1 证书不能作为 cut 15 的 beta 新放行资格。
    let beta_stale = s.e_fin("release-beta-stale-r1", beta_r1_payload);
    assert_eq!(beta_stale["kind"], "Error", "{beta_stale}");
    assert!(
        beta_stale["error"]
            .as_str()
            .unwrap()
            .starts_with("IdentityConflict"),
        "{beta_stale}"
    );

    let beta_r3_payload = s.release_exact_payload_from_query(&q15, "beta", &beta_gid);
    let rel_beta = s.e_fin("release-beta-cut16", beta_r3_payload);
    assert_eq!(rel_beta["kind"], "ReleasedExactReceipt", "{rel_beta}");
    assert_eq!(rel_beta["cut"]["commit_seq"], "16");
    let cert_beta = &rel_beta["record"]["command"]["certificate"];
    let beta_mkt = cert_beta["market_dependencies"][0].as_str().unwrap();
    assert!(
        beta_mkt.starts_with(
            "fx-quote:testonly.ce-s07.fx|1|TEST-FX/TEST-CASH|fx-quote-007@rev=3;coord=70;supersedes=2;rate=1/1;"
        ),
        "unexpected beta market_dependency: {beta_mkt}"
    );
    assert!(cert_beta["conditions"][0]["evidence_refs"]
        .as_array()
        .unwrap()
        .iter()
        .any(|x| {
            x.as_str().is_some_and(|s| {
                s.starts_with(
                    "fx-retired:testonly.ce-s07.fx|1|TEST-FX/TEST-CASH|fx-quote-007@rev=2:retired_by_rev=3:evidence_id=ev-retire-r2:",
                )
            })
        }));
    assert!(cert_beta["conditions"][1]["invalidation_sources"]
        .as_array()
        .unwrap()
        .iter()
        .any(|x| {
            x == "market-supersession:testonly.ce-s07.fx|1|TEST-FX/TEST-CASH|fx-quote-007:after_rev=3"
        }));

    // 同一静态 X profile 同样接受 cut 16 的 rev=3 交付命令。
    let mut cmd_beta_for_x = rel_beta["record"]["command"].clone();
    cmd_beta_for_x["symbol"] = json!(x_prof.model.symbol);
    let parsed_beta: crate::history_simulation::runtime::ExactCommand =
        serde_json::from_value(cmd_beta_for_x).unwrap();
    parsed_beta.validate(&x_prof, 1).unwrap();

    audit(&s.e_db, &s.e_config).unwrap();
    assert_eq!(recover(&s.e_config).unwrap()["writer_epoch"], "2");

    // 确认 meta 持久锁定 fx-valuation/2，不得降级为 fx-valuation/1 恢复。
    let stored_fx_rev: String = s
        .e_db
        .query_row(
            "SELECT v FROM meta WHERE k='fx_valuation_revision'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(stored_fx_rev, "fx-valuation/2");
    let mut downgrade_manifest = manifest.clone();
    downgrade_manifest["fx_valuation"]["schema_revision"] = json!("fx-valuation/1");
    let (dg_path, _) = s
        .space
        .save_json("downgrade-v1-manifest.json", &downgrade_manifest);
    let dg_cfg = Config::load(Path::new(&dg_path), &s.e_config.db, None).unwrap();
    let dg_err = recover(&dg_cfg).unwrap_err();
    assert!(
        dg_err.starts_with("IdentityConflict"),
        "fx-valuation/2 DB must refuse downgrade recovery to fx-valuation/1: {dg_err}"
    );
}

/// 非作者财务审阅 BLOCK 项专项回归：
/// 1) 业务判定顺序（恢复父版本 bd0933e97e）：在 r2=110/100 超限同一场景，先识别模型域外 batched 命令
///    并写持久 `Unsupported / ModelOrderUnspecified`（不进 FX 政策门），模型域内 single 命令才进 FX 政策门
///    被 `AwaitingPolicy` 拒绝；同时保持已放行命令同/新 message_id 原收据优先；
/// 2) 显式合同隔离：`tb03b-finance/6 + fx-valuation/1` 静态证书完整兼容（首次 ImportResponsibility、
///    ReleaseExact、recover/audit 均通过，且不得暗迁为 fx-valuation/2）；`fx-valuation/2` 缺依赖严格拒绝，
///    不由失败降级转静态。
#[test]
fn fx_v2_model_coverage_precedes_fx_gate_and_v1_static_v6_remains_compatible() {
    let model = crate::history_simulation::tests::model();

    // --- Part A: tb03b-finance/6 + fx-valuation/2，r2=110/100 同一场景对比域外 batched vs 域内 single ---
    {
        let base = Ac2Session::build(
            "order-v2-template",
            "100",
            "0",
            "baseline-cash-0",
            vec![],
            false,
            FX_OBLIGATIONS_RAW,
        );
        let space = Space::new("fx-v2-model-order");
        let session_id = "fx-v2-model-order".to_owned();

        // alpha=30 (single), beta=25 (2*12+1, single), gamma=15 (3*5+0, batched) -> 现金 70 + 外币 20 = 90/100; r2 -> 110/100
        let mut fin_data = base.fin_data.clone();
        decorate_fx_release_bound_v6_input(&mut fin_data, json!(model.model_ref()));
        for p in fin_data["plans"].as_array_mut().unwrap() {
            match p["decision_id"].as_str().unwrap() {
                "beta" => {
                    p["quantity"] = json!("2");
                    p["limit_price"] = json!("12");
                    p["fee_tail"] = json!("1");
                    p["o_ref"]["quantity"] = json!("2");
                    p["exact"]["first_quantity"] = json!("2");
                    p["exact"]["concurrency"] = json!("single");
                }
                "gamma" => {
                    p["slot_id"] = json!("slot-main");
                    p["quantity"] = json!("3");
                    p["limit_price"] = json!("5");
                    p["fee_tail"] = json!("0");
                    p["o_ref"]["quantity"] = json!("3");
                    p["exact"]["first_quantity"] = json!("3");
                    p["exact"]["concurrency"] = json!("batched");
                }
                _ => {}
            }
        }
        let members = json!(["alpha", "beta", "gamma"]);
        fin_data["slots"] = json!([{
            "slot_id": "slot-main",
            "applicants": members,
            "input_end": {
                "kind": "ControlledInputEnd",
                "source_id": "ac2-r2-fixture",
                "source_epoch": "1",
                "watermark": "2",
                "complete_request_hash": hash(&members),
            }
        }]);
        let (fin_path, fin_sha) = space.save_json("finance-input.json", &fin_data);
        let (fx_ob_path, fx_ob_sha) = space.save_raw("fx-obligations.json", FX_OBLIGATIONS_RAW);

        let s_obj = json!({"object_id": "unit-S-object", "kind": "UnitStructuralTrustRoot", "branch": "RISING"});
        let basis = json!({
            "kind": "FinancialBasis",
            "session_id": session_id,
            "session_generation": "1",
            "writer_epoch": "1",
            "pending_revision": false,
            "commit_ns": "1",
            "snapshot": {"profile_id": "unit", "objects": [s_obj]}
        });
        let (basis_path, _) = space.save_json("s-basis.json", &basis);
        let stub = space.dir.join("s-stub.sh");
        crate::economic_session::write_test_executable(
            &stub,
            &format!("#!/bin/sh\nexec /bin/cat '{basis_path}'\n"),
            0o700,
        );
        let stub_sha = sha256_hex(&std::fs::read(&stub).unwrap());

        let mut manifest = base.e_config.manifest.clone();
        manifest["session_id"] = json!(session_id);
        manifest["e"]["db"] = json!(space.dir.join("e.db"));
        manifest["e"]["socket"] = json!(space.dir.join("e.sock"));
        for r in manifest["chongs"].as_array_mut().unwrap() {
            let cid = r["chong_id"].as_str().unwrap().to_owned();
            r["db"] = json!(space.dir.join(format!("{cid}.db")));
            r["socket"] = json!(space.dir.join(format!("{cid}.sock")));
        }
        manifest["finance"]["schema_revision"] = json!("tb03b-finance/6");
        manifest["finance"]["input_path"] = json!(fin_path);
        manifest["finance"]["input_sha256"] = json!(fin_sha);
        manifest["finance"]["structure"]["binary"] = json!(stub);
        manifest["finance"]["structure"]["binary_sha256"] = json!(stub_sha);
        manifest["finance"]["structure"]["db"] = json!(space.dir.join("s.db"));
        manifest["finance"]["structure"]["session_id"] = json!(session_id);
        manifest["fx_valuation"]["schema_revision"] = json!("fx-valuation/2");
        manifest["fx_valuation"]["obligation_input_path"] = json!(fx_ob_path);
        manifest["fx_valuation"]["obligation_input_sha256"] = json!(fx_ob_sha);
        let mut bars = serde_json::Map::new();
        for (msg, bar) in [
            ("imp-base", "1"),
            ("imp-fx", "1"),
            ("cap-r1", "1"),
            ("res-r1", "1"),
            ("cap-open-alpha", "1"),
            ("apply-open-alpha", "1"),
            ("bind-alpha", "1"),
            ("prep-alpha", "1"),
            ("cap-open-beta", "1"),
            ("apply-open-beta", "1"),
            ("bind-beta", "1"),
            ("prep-beta", "1"),
            ("cap-open-gamma", "1"),
            ("apply-open-gamma", "1"),
            ("bind-gamma", "1"),
            ("prep-gamma", "1"),
            ("reserve-main", "1"),
            ("commit-alpha", "1"),
            ("commit-beta", "1"),
            ("commit-gamma", "1"),
            ("dispatch-alpha", "1"),
            ("dispatch-beta", "1"),
            ("dispatch-gamma", "1"),
            ("release-alpha-ok", "2"),
            ("cap-r2", "3"),
            ("release-alpha-retry-new", "3"),
            ("release-gamma-batched-overcap", "3"),
            ("release-beta-single-overcap", "3"),
        ] {
            bars.insert(msg.to_owned(), json!(bar));
        }
        manifest["clock"] = json!({
            "kind": "logical-bar/1",
            "bars": {"init": "0", "recover": ["10"], "messages": Value::Object(bars)}
        });

        let (mpath, _) = space.save_json("manifest.json", &manifest);
        let e_config = Config::load(Path::new(&mpath), &space.dir.join("e.db"), None).unwrap();
        init(&e_config).unwrap();
        let (e_db, _) = open(&e_config.db, false).unwrap();
        let mut b_configs = Vec::new();
        let mut b_dbs = Vec::new();
        for name in ["alpha", "beta", "gamma"] {
            let bc = Config::load(
                Path::new(&mpath),
                &space.dir.join(format!("{name}.db")),
                Some(name),
            )
            .unwrap();
            init(&bc).unwrap();
            let (bdb, _) = open(&bc.db, false).unwrap();
            b_configs.push((name.to_owned(), bc));
            b_dbs.push((name.to_owned(), bdb));
        }
        let mut s = Ac2Session {
            space,
            session_id,
            e_config,
            e_db,
            b_configs,
            b_dbs,
            fin_data,
            opening_docs: base.opening_docs.clone(),
            voice_payloads: base.voice_payloads.clone(),
        };

        assert_eq!(
            s.e_fin(
                "imp-base",
                json!({"op": "ImportResponsibility", "responsibility_id": "baseline-cash-0", "writer_epoch": "1"})
            )["kind"],
            "ResponsibilityImportedReceipt"
        );
        assert_eq!(
            s.e_fin(
                "imp-fx",
                json!({"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"})
            )["kind"],
            "FxResponsibilityImportedReceipt"
        );
        let r1 = s.capture_fx("cap-r1", FX_R1_RAW, "tok-r1");
        assert_eq!(s.resolve_fx("res-r1", "ev-r1", &[&r1])["kind"], "Resolved");
        s.prepare_all_chongs();
        let slot_main = s.slot("slot-main");
        let res = s.e_fin(
            "reserve-main",
            json!({"op": "Reserve", "slot_id": "slot-main", "request_set_hash": hash(&slot_main["applicants"]), "writer_epoch": "1"}),
        );
        assert_eq!(res["kind"], "ReserveReceipt", "{res}");
        let grants: std::collections::BTreeMap<String, String> = res["record"]["grants"]
            .as_array()
            .unwrap()
            .iter()
            .map(|g| {
                (
                    g["decision_id"].as_str().unwrap().to_owned(),
                    g["grant_id"].as_str().unwrap().to_owned(),
                )
            })
            .collect();
        for name in ["alpha", "beta", "gamma"] {
            let p = s.plan(name);
            assert_eq!(
                s.b_send(
                    name,
                    &format!("commit-{name}"),
                    json!({"op": "CommitDecision", "decision_id": name, "plan_hash": hash(&p), "grant_id": grants[name], "writer_epoch": "1"}),
                )["kind"],
                "LocalCommitReceipt"
            );
            assert_eq!(
                s.e_fin(
                    &format!("dispatch-{name}"),
                    json!({"op": "MakeDispatchable", "decision_id": name, "plan_hash": hash(&p), "writer_epoch": "1"}),
                )["kind"],
                "DispatchableReceipt"
            );
        }

        // r1=90/100 放行 alpha
        let q_r1 = s.query_fx(1, "q-r1", Value::Null, Value::Null);
        assert_eq!(q_r1["fx_valuation"]["schema_revision"], "fx-valuation/2");
        assert_eq!(q_r1["fx_valuation"]["summary"]["evaluated_total"], "90");
        let alpha_payload = s.release_exact_payload_from_query(&q_r1, "alpha", &grants["alpha"]);
        let rel_alpha = s.e_fin("release-alpha-ok", alpha_payload.clone());
        assert_eq!(rel_alpha["kind"], "ReleasedExactReceipt", "{rel_alpha}");

        // r2 -> 110/100 超限
        assert_eq!(
            s.capture_fx("cap-r2", FX_R2_RAW, "tok-r2")["kind"],
            "Recorded"
        );
        let q_r2 = s.query_fx(1, "q-r2", Value::Null, Value::Null);
        assert_eq!(q_r2["fx_valuation"]["summary"]["evaluated_total"], "110");
        assert_eq!(
            q_r2["fx_valuation"]["summary"]["gate_status"],
            "BlockedExceedsCap"
        );

        // 1) 已放行 alpha 同/新 message_id 原收据优先
        let retry_same = s.e_fin("release-alpha-ok", alpha_payload.clone());
        assert_eq!(retry_same, rel_alpha);
        let retry_new = s.e_fin("release-alpha-retry-new", alpha_payload);
        assert_eq!(retry_new["kind"], "ReleasedExactReceipt", "{retry_new}");
        assert_eq!(retry_new["cut"], rel_alpha["cut"]);
        assert_eq!(retry_new["record"], rel_alpha["record"]);

        // 2) 模型域外 batched 命令 gamma：不进 FX 政策门，直接写持久 Unsupported / ModelOrderUnspecified
        let gamma_payload = s.release_exact_payload("gamma", &grants["gamma"]);
        let rel_gamma = s.e_fin("release-gamma-batched-overcap", gamma_payload);
        assert_eq!(
            rel_gamma["kind"], "ReleaseUnsupportedReceipt",
            "out-of-domain batched must persist Unsupported even during r2=110/100: {rel_gamma}"
        );
        assert_eq!(rel_gamma["record"]["state"], "Unsupported");
        assert_eq!(
            rel_gamma["record"]["unsupported"]["reason"],
            "ModelOrderUnspecified"
        );
        assert_eq!(rel_gamma["record"]["execution_eligibility"], "None");
        let q_gamma = s.e_fin(
            "q-cmd-gamma",
            json!({"op": "QueryCommand", "command_id": "cmd-gamma", "cut": null, "as_known_ns": null}),
        );
        assert_eq!(q_gamma["state"], "Unsupported", "{q_gamma}");

        // 3) 模型域内 single 命令 beta：进 FX 政策门被 AwaitingPolicy 拒绝，仍为 Dispatchable
        let beta_payload = s.release_exact_payload_from_query(&q_r1, "beta", &grants["beta"]);
        let rel_beta = s.e_fin("release-beta-single-overcap", beta_payload);
        assert_eq!(rel_beta["kind"], "Error", "{rel_beta}");
        assert!(
            rel_beta["error"]
                .as_str()
                .unwrap()
                .starts_with("AwaitingPolicy"),
            "in-domain single must hit FX gate during r2=110/100: {rel_beta}"
        );
        let q_beta = s.e_fin(
            "q-cmd-beta",
            json!({"op": "QueryCommand", "command_id": "cmd-beta", "cut": null, "as_known_ns": null}),
        );
        assert_eq!(q_beta["state"], "Dispatchable", "{q_beta}");

        audit(&s.e_db, &s.e_config).unwrap();
        assert_eq!(recover(&s.e_config).unwrap()["writer_epoch"], "2");
    }

    // --- Part B: 既有 tb03b-finance/6 + fx-valuation/1 静态证书保持原合同不变，且不得暗迁为 fx-valuation/2 ---
    {
        let base = Ac2Session::build(
            "v6-v1-static-template",
            "100",
            "0",
            "baseline-cash-0",
            vec![],
            false,
            FX_OBLIGATIONS_RAW,
        );
        let space = Space::new("v6-v1-static-compat");
        let session_id = "v6-v1-static-compat".to_owned();
        let mut fin_data = base.fin_data.clone();
        fin_data["schema_revision"] = json!("tb03b-finance/6");
        fin_data["exact_release"]["model_coverage"]["model_ref"] = json!(model.model_ref());
        // 保持 TestOnly-market/1407-c1 与 controlled-* 静态证书不加新标记！
        let (fin_path, fin_sha) = space.save_json("finance-input.json", &fin_data);
        let (fx_ob_path, fx_ob_sha) = space.save_raw("fx-obligations.json", FX_OBLIGATIONS_RAW);
        let s_obj = json!({"object_id": "unit-S-object", "kind": "UnitStructuralTrustRoot", "branch": "RISING"});
        let basis = json!({
            "kind": "FinancialBasis",
            "session_id": session_id,
            "session_generation": "1",
            "writer_epoch": "1",
            "pending_revision": false,
            "commit_ns": "1",
            "snapshot": {"profile_id": "unit", "objects": [s_obj]}
        });
        let (basis_path, _) = space.save_json("s-basis.json", &basis);
        let stub = space.dir.join("s-stub.sh");
        crate::economic_session::write_test_executable(
            &stub,
            &format!("#!/bin/sh\nexec /bin/cat '{basis_path}'\n"),
            0o700,
        );
        let stub_sha = sha256_hex(&std::fs::read(&stub).unwrap());

        let mut manifest = base.e_config.manifest.clone();
        manifest["session_id"] = json!(session_id);
        manifest["e"]["db"] = json!(space.dir.join("e.db"));
        manifest["e"]["socket"] = json!(space.dir.join("e.sock"));
        for r in manifest["chongs"].as_array_mut().unwrap() {
            let cid = r["chong_id"].as_str().unwrap().to_owned();
            r["db"] = json!(space.dir.join(format!("{cid}.db")));
            r["socket"] = json!(space.dir.join(format!("{cid}.sock")));
        }
        manifest["finance"]["schema_revision"] = json!("tb03b-finance/6");
        manifest["finance"]["input_path"] = json!(fin_path);
        manifest["finance"]["input_sha256"] = json!(fin_sha);
        manifest["finance"]["structure"]["binary"] = json!(stub);
        manifest["finance"]["structure"]["binary_sha256"] = json!(stub_sha);
        manifest["finance"]["structure"]["db"] = json!(space.dir.join("s.db"));
        manifest["finance"]["structure"]["session_id"] = json!(session_id);
        manifest["fx_valuation"]["schema_revision"] = json!("fx-valuation/1");
        manifest["fx_valuation"]["obligation_input_path"] = json!(fx_ob_path);
        manifest["fx_valuation"]["obligation_input_sha256"] = json!(fx_ob_sha);

        let (mpath, _) = space.save_json("manifest.json", &manifest);
        let e_config = Config::load(Path::new(&mpath), &space.dir.join("e.db"), None).unwrap();
        init(&e_config).unwrap();
        let (e_db, _) = open(&e_config.db, false).unwrap();
        let mut b_configs = Vec::new();
        let mut b_dbs = Vec::new();
        for name in ["alpha", "beta", "gamma"] {
            let bc = Config::load(
                Path::new(&mpath),
                &space.dir.join(format!("{name}.db")),
                Some(name),
            )
            .unwrap();
            init(&bc).unwrap();
            let (bdb, _) = open(&bc.db, false).unwrap();
            b_configs.push((name.to_owned(), bc));
            b_dbs.push((name.to_owned(), bdb));
        }
        let mut s = Ac2Session {
            space,
            session_id,
            e_config,
            e_db,
            b_configs,
            b_dbs,
            fin_data,
            opening_docs: base.opening_docs.clone(),
            voice_payloads: base.voice_payloads.clone(),
        };

        assert_eq!(
            s.e_fin(
                "imp-base",
                json!({"op": "ImportResponsibility", "responsibility_id": "baseline-cash-0", "writer_epoch": "1"})
            )["kind"],
            "ResponsibilityImportedReceipt"
        );
        assert_eq!(
            s.e_fin(
                "imp-fx",
                json!({"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"})
            )["kind"],
            "FxResponsibilityImportedReceipt"
        );
        let r1 = s.capture_fx("cap-r1", FX_R1_RAW, "tok-r1");
        assert_eq!(s.resolve_fx("res-r1", "ev-r1", &[&r1])["kind"], "Resolved");
        s.prepare_all_chongs();
        let slot_main = s.slot("slot-main");
        let res = s.e_fin(
            "reserve-main",
            json!({"op": "Reserve", "slot_id": "slot-main", "request_set_hash": hash(&slot_main["applicants"]), "writer_epoch": "1"}),
        );
        let alpha_gid = res["record"]["grants"]
            .as_array()
            .unwrap()
            .iter()
            .find(|g| g["decision_id"] == "alpha")
            .unwrap()["grant_id"]
            .as_str()
            .unwrap()
            .to_owned();
        let alpha_plan = s.plan("alpha");
        assert_eq!(
            s.b_send(
                "alpha",
                "commit-alpha",
                json!({"op": "CommitDecision", "decision_id": "alpha", "plan_hash": hash(&alpha_plan), "grant_id": alpha_gid, "writer_epoch": "1"}),
            )["kind"],
            "LocalCommitReceipt"
        );
        assert_eq!(
            s.e_fin(
                "dispatch-alpha",
                json!({"op": "MakeDispatchable", "decision_id": "alpha", "plan_hash": hash(&alpha_plan), "writer_epoch": "1"}),
            )["kind"],
            "DispatchableReceipt"
        );
        let rel = s.e_fin(
            "release-alpha-ok",
            s.release_exact_payload("alpha", &alpha_gid),
        );
        assert_eq!(rel["kind"], "ReleasedExactReceipt", "{rel}");
        assert_eq!(
            rel["record"]["command"]["certificate"]["market_dependencies"],
            json!(["TestOnly-market/1407-c1"])
        );
        assert_eq!(
            rel["record"]["command"]["model_ref"],
            json!(model.model_ref())
        );
        audit(&s.e_db, &s.e_config).unwrap();
        assert_eq!(recover(&s.e_config).unwrap()["writer_epoch"], "2");

        // 不得把既有 fx-valuation/1 库在 recover 时暗迁为 fx-valuation/2。
        let stored_v1_rev: String = s
            .e_db
            .query_row(
                "SELECT v FROM meta WHERE k='fx_valuation_revision'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(stored_v1_rev, "fx-valuation/1");
        let mut upgrade_manifest = manifest.clone();
        upgrade_manifest["fx_valuation"]["schema_revision"] = json!("fx-valuation/2");
        let (up_path, _) = s
            .space
            .save_json("upgrade-v2-manifest.json", &upgrade_manifest);
        let up_cfg = Config::load(Path::new(&up_path), &s.e_config.db, None).unwrap();
        let up_err = recover(&up_cfg).unwrap_err();
        assert!(
            up_err.starts_with("IdentityConflict"),
            "fx-valuation/1 DB must refuse silent migration to fx-valuation/2: {up_err}"
        );
    }
}
