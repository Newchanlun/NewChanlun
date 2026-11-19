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

    fn resolve_fx(&mut self, msg: &str, evidence_id: &str, recs: &[&Value]) -> Value {
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
        self.e_market(
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
        let cmd =
            super::exact_command::command(&self.session_id, "1", &self.fin_data, &q, grant_id)
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
        q_after_imp["fx_valuation"]["summary"]["evaluated_total"],
        "91"
    );

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
