//! #1407 C2 第 1、2 项的集成锁：E 经正式入口放行的命令，经共同信封查询真 E，被 X 的 AcceptExact 接纳，
//! 随后受控 S 条件执行、X 占有调用。E 与 X 都是生产 serve 循环；S 仍是受控夹具（真 S producer 归 TB04-D/E）。
//! 本批 E 仍是 TestOnly 时钟（alpha 放行读数 162）；E 改读 logical-bar/1 归 C2 第 4 项。在那之前，X 先走 162 根空 bar
//! 让接纳前沿追上放行读数，这里只锁条件清单与信封两处断点，不作时钟域证据。
use super::*;
use crate::economic_session::{capture_continuity, store};
use crate::history_simulation::runtime::Profile as XProfile;
use rusqlite::types::ValueRef;
use rusqlite::OptionalExtension;
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

const S_SCHEMA: &str = "s-authority-fixture/1";
const S_REPLIES: &str = "s-authority-fixture/replies";
const S_PRODUCER: &str = "S:fixture";

/// 全表逻辑转储：每表按首列序，每格原值（TEXT 原样，BLOB 十六进制）。
fn tables(db: &Path) -> Value {
    let c = rusqlite::Connection::open_with_flags(db, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)
        .unwrap();
    let names: Vec<String> = c
        .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        .unwrap()
        .query_map([], |r| r.get(0))
        .unwrap()
        .map(Result::unwrap)
        .collect();
    let mut out = serde_json::Map::new();
    for name in names {
        let mut q = c
            .prepare(&format!("SELECT * FROM \"{name}\" ORDER BY 1"))
            .unwrap();
        let width = q.column_count();
        let rows: Vec<Value> = q
            .query_map([], |r| {
                (0..width)
                    .map(|i| {
                        Ok(match r.get_ref(i)? {
                            ValueRef::Null => Value::Null,
                            ValueRef::Integer(n) => json!(n),
                            ValueRef::Real(x) => json!(x),
                            ValueRef::Text(t) => json!(std::str::from_utf8(t).unwrap()),
                            ValueRef::Blob(b) => {
                                json!(b.iter().map(|x| format!("{x:02x}")).collect::<String>())
                            }
                        })
                    })
                    .collect::<Result<Vec<_>, _>>()
                    .map(Value::Array)
            })
            .unwrap()
            .map(Result::unwrap)
            .collect();
        out.insert(name, Value::Array(rows));
    }
    Value::Object(out)
}
fn economic_tables(f: &Fixture) -> Value {
    json!(f
        .configs
        .iter()
        .map(|c| (c.domain.clone(), tables(&c.db)))
        .collect::<serde_json::Map<_, _>>())
}
/// 就绪是「在 listen」，不是「文件存在」：bind 先建出路径，listen 之前的连接会被拒。判据是一次连接成功，
/// 只用 std，Linux 与 macOS 同一份（ci-macos 跑这条用例）。
///
/// 只探走 `session_transport::serve_unix*` 的 E 与 X：那里空连接由 I/O 线程读到 EOF，回输送层自己的
/// `{"ok":false,…}` 后关闭，不入队、不到域 handler、不碰库。这里读到对端关闭才返回，并核回的正是这条
/// 输送层拒绝——探测没有变成一条请求。受控 S 不探：它 `bind` 返回时已在 listen，且把每条连接都当请求。
fn listening(path: &Path) -> bool {
    let Ok(mut s) = UnixStream::connect(path) else {
        return false;
    };
    // BSD/macOS 在对端已先接受并关闭连接时，shutdown(SHUT_WR) 可返回 ENOTCONN（ErrorKind::NotConnected）；
    // 与 history_simulation_entry.py:connect_probe 对齐：忽略 NotConnected，继续读取对端关闭前写入的回复；
    // 若对端未写任何字节即关闭（如连接数瞬时受限），返回 false 由 wait_for 重试直至期限耗尽。
    if let Err(err) = s.shutdown(std::net::Shutdown::Write) {
        assert_eq!(
            err.kind(),
            std::io::ErrorKind::NotConnected,
            "半关闭就绪探针失败：{err}"
        );
    }
    s.set_read_timeout(Some(std::time::Duration::from_secs(5)))
        .unwrap();
    let mut reply = String::new();
    match s.read_to_string(&mut reply) {
        Ok(_) => {}
        Err(err) if err.kind() == std::io::ErrorKind::NotConnected => return false,
        Err(err) => panic!("读取就绪探针回复失败：{err}"),
    }
    let trimmed = reply.trim_end();
    if trimmed.is_empty() {
        return false;
    }
    let reply = strict_json(trimmed.as_bytes()).unwrap();
    assert_eq!(reply["ok"], false, "空连接须止于输送层：{reply}");
    true
}

#[test]
fn listening_probe_tolerates_early_peer_close_and_verifies_transport_rejection() {
    let dir = tempfile::tempdir().unwrap();
    assert!(!listening(&dir.path().join("missing.sock")));

    let early_path = dir.path().join("early-close.sock");
    let early_listener = UnixListener::bind(&early_path).unwrap();
    let early_peer = std::thread::spawn(move || {
        let (stream, _) = early_listener.accept().unwrap();
        drop(stream);
    });
    assert!(!listening(&early_path));
    early_peer.join().unwrap();

    let ready_path = dir.path().join("ready.sock");
    let ready_listener = UnixListener::bind(&ready_path).unwrap();
    let ready_peer = std::thread::spawn(move || {
        let (mut stream, _) = ready_listener.accept().unwrap();
        let mut buf = [0u8; 1];
        assert_eq!(stream.read(&mut buf).unwrap(), 0);
        stream.write_all(b"{\"ok\":false}\n").unwrap();
    });
    assert!(listening(&ready_path));
    ready_peer.join().unwrap();
}
fn wait_for(path: &Path) {
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
    while !listening(path) {
        assert!(
            std::time::Instant::now() < deadline,
            "{} 未出现",
            path.display()
        );
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
}
fn exchange(socket: &Path, frame: &Value) -> Value {
    let mut s = UnixStream::connect(socket).unwrap();
    s.write_all(format!("{}\n", canonical_json(frame)).as_bytes())
        .unwrap();
    s.shutdown(std::net::Shutdown::Write).unwrap();
    let mut line = String::new();
    BufReader::new(s).read_line(&mut line).unwrap();
    strict_json(line.trim_end().as_bytes()).unwrap()
}
fn x(socket: &Path, op: &str, payload: Value) -> Value {
    exchange(
        socket,
        &json!({"protocol":"x-exact-simulation/1","op":op,"payload":payload}),
    )
}
/// 受控 S：只回 ExecuteCommitted。收据身份取命令冻结的 `eligibility_ref`（PR 正文的方案），
/// commit_ns 取 S 获准时的 bar 读数。
fn controlled_s(socket: PathBuf, bar: i64, calls: Arc<AtomicUsize>) {
    let listener = UnixListener::bind(&socket).unwrap();
    std::thread::spawn(move || {
        let mut records = std::collections::BTreeMap::<String, Value>::new();
        for stream in listener.incoming() {
            let mut stream = stream.unwrap();
            let mut line = String::new();
            BufReader::new(&stream).read_line(&mut line).unwrap();
            let e = strict_json(line.trim_end().as_bytes()).unwrap();
            crate::session_protocol::validate_envelope(e.clone(), S_SCHEMA).unwrap();
            let q = &e["payload"];
            let id = q["command_id"].as_str().unwrap().to_owned();
            let payload = match q["op"].as_str().unwrap() {
                "RequestConditionalExecution" => {
                    calls.fetch_add(1, Ordering::SeqCst);
                    let mut r = json!({});
                    for k in [
                        "protocol",
                        "session_id",
                        "session_generation",
                        "authority_id",
                        "authority_epoch",
                        "command_id",
                        "command_hash",
                        "command",
                        "release_receipt_id",
                    ] {
                        r[k] = q[k].clone();
                    }
                    r["state"] = json!("ExecuteCommitted");
                    r["receipt_id"] = q["command"]["change"]["order"]["eligibility_ref"].clone();
                    r["commit_ns"] = json!(bar);
                    records.insert(id, r.clone());
                    r
                }
                "QueryExecuteCommitted" => records[&id].clone(),
                other => panic!("受控 S 未知操作 {other}"),
            };
            let reply = crate::session_protocol::reply_envelope(
                &e,
                payload,
                S_SCHEMA,
                e["session_id"].as_str().unwrap(),
                e["session_generation"].as_str().unwrap(),
                S_REPLIES,
                S_PRODUCER,
                "1",
            );
            stream
                .write_all(format!("{}\n", canonical_json(&reply)).as_bytes())
                .unwrap();
        }
    });
}
fn x_profile(f: &Fixture) -> Value {
    let mut model = serde_json::to_value(crate::history_simulation::tests::model()).unwrap();
    model["symbol"] = json!("alpha");
    let (namespace, epoch, producer, _) = X_SOURCE;
    let e = &f.configs[0];
    json!({"model":model,"session_id":e.session,"session_generation":e.generation,"x_id":producer,
        "source_namespace":namespace,"source_epoch":epoch,"socket":f.dir.join("x.sock"),
        "e":{"socket":f.dir.join("e.sock"),"authority_id":"E","authority_epoch":"1","schema_revision":e.revision().unwrap(),"reply_namespace":"economic-session/replies","producer_id":e.producer},
        "s":{"socket":f.dir.join("s.sock"),"authority_id":"S","authority_epoch":"1","schema_revision":S_SCHEMA,"reply_namespace":S_REPLIES,"producer_id":S_PRODUCER},
        "conditions":f.data["exact_release"]["conditions"],"timeout_ms":5000,"max_frame_bytes":1048576})
}
fn bar(index: i64, changes: Value) -> Value {
    json!({"request_id":format!("b{index}"),"known_frontier_cut":format!("frontier{index}"),
        "bar":{"index":index,"open":14,"low":13,"high":15,"close":14},"capacity":{"kind":"none"},
        "close_changes":changes,"scenario_busts":[]})
}

const RELEASE_NS: i64 = 162;

#[test]
fn e_formal_release_is_accepted_by_x_over_the_common_envelope() {
    let mut f = fixture(None);
    committed(&mut f);
    dispatch(&mut f, "alpha");
    let released = f.handle(0, "ReleaseExact-alpha", release_payload(&f, "alpha"));
    assert_eq!(released["record"]["state"], "ReleasedExact", "{released}");
    assert_eq!(
        released["record"]["release_commit_ns"],
        RELEASE_NS.to_string()
    );
    let command = released["record"]["command"].clone();

    let profile: XProfile = serde_json::from_value(x_profile(&f)).unwrap();
    profile.validate().unwrap();
    let parsed: crate::history_simulation::runtime::ExactCommand =
        serde_json::from_value(command.clone()).unwrap();
    assert_eq!(serde_json::to_value(&parsed).unwrap(), command);

    let e_config = f.configs[0].clone();
    std::thread::spawn(move || service::serve(&e_config, 1, 1).unwrap());
    wait_for(&f.dir.join("e.sock"));
    let s_calls = Arc::new(AtomicUsize::new(0));
    controlled_s(f.dir.join("s.sock"), RELEASE_NS, s_calls.clone());
    let x_db = f.dir.join("x.sqlite");
    let db = x_db.clone();
    let serving = profile.clone();
    std::thread::spawn(move || {
        let (mut c, _) = crate::economic_session::open_durable_db(&db).unwrap();
        crate::history_simulation::runtime::serve(&mut c, &serving, 1).unwrap()
    });
    let xs = f.dir.join("x.sock");
    wait_for(&xs);
    for index in 0..RELEASE_NS {
        assert_eq!(
            x(&xs, "AdvanceBar", bar(index, json!([])))["kind"],
            "SimulationBatch"
        );
    }
    let before = economic_tables(&f);
    let accepted = x(&xs, "AcceptExact", command.clone());
    assert_eq!(accepted["state"], "Accepted", "{accepted}");
    assert_eq!(accepted["causal_refs"][0]["release_commit_ns"], RELEASE_NS);
    assert_eq!(s_calls.load(Ordering::SeqCst), 0, "接纳不产生调用权");
    assert_eq!(economic_tables(&f), before, "QueryReleasedExact 只读");
    let claimed = x(
        &xs,
        "AdvanceBar",
        bar(RELEASE_NS, json!([command["change"]])),
    );
    assert_eq!(claimed["kind"], "SimulationBatch", "{claimed}");
    assert_eq!(s_calls.load(Ordering::SeqCst), 1, "S 恰一次");
    assert_eq!(
        x(&xs, "QueryCommand", json!("cmd-alpha"))["state"],
        "Observed"
    );
}

fn build_bound_sim_fixture(x_db: &Path, with_alloc_tape: bool) -> (Fixture, XProfile) {
    let mut f = Fixture::build_with(
        "100",
        None,
        &[("slot", &["alpha", "beta"])],
        Some((false, false)),
        None,
        None,
        None,
        None,
        None,
        true,
    );
    let profile: XProfile = serde_json::from_value(x_profile(&f)).unwrap();
    profile.validate().unwrap();
    let model_hash = crate::session_protocol::sha256_hex(
        canonical_json(&serde_json::to_value(&profile.model).unwrap()).as_bytes(),
    );

    // 读取原 Fixture 初始化好的两份初始建账原件与两份 BindVoice 请求，复用同一套建账输入。
    let (_, _, _, old_e_img) = latest(&f.dbs[0]).unwrap();
    let alloc_docs: Vec<(String, String, String)> = ["alpha", "beta"]
        .iter()
        .map(|name| {
            let tok = format!("token-{name}");
            let rec = old_e_img["recorded"]
                .as_array()
                .unwrap()
                .iter()
                .find(|r| r["token"] == tok)
                .unwrap();
            (
                (*name).to_owned(),
                rec["raw_utf8"].as_str().unwrap().to_owned(),
                tok,
            )
        })
        .collect();
    let bind_payloads: Vec<Value> = ["alpha", "beta"]
        .iter()
        .map(|name| {
            let reference = |id: &str| {
                json!({
                    "authority_id": name,
                    "object_id": id,
                    "revision": "0",
                    "content_hash": hash(&json!(id))
                })
            };
            json!({
                "op": "BindVoice",
                "binding_id": format!("voice-{name}"),
                "evidence_id": name,
                "carrier_ref": reference("unit-carrier"),
                "gamma_ref": reference("unit-gamma"),
                "parent_voice_id": null,
                "sigma": "Long",
                "n": "0"
            })
        })
        .collect();

    // 令 beta 也在模型覆盖域内（`concurrency: "single"`），以便在 alpha 放行并落簿后，
    // 仍能对 beta 发起第二笔真实 `ReleasedExact` 测试（健康态与缺口态当次门）。
    for q in f.data["plans"].as_array_mut().unwrap() {
        q["exact"]["concurrency"] = json!("single");
    }
    let sim_input_path = f.dir.join("sim-finance-input.json");
    let sim_input_raw = canonical_json(&f.data);
    std::fs::write(&sim_input_path, &sim_input_raw).unwrap();

    let mut m = f.configs[0].manifest.clone();
    m["finance"]["input_path"] = json!(sim_input_path);
    m["finance"]["input_sha256"] = json!(crate::session_protocol::sha256_hex(
        sim_input_raw.as_bytes()
    ));
    m["book_revision"] = json!("tb03c-book/1");
    for auth in m["authorized_sources"].as_array_mut().unwrap() {
        if auth["producer_id"] == X_SOURCE.2 {
            auth["operations"] = json!(["CaptureExternal", "QueryReleasedExact", "ReadView"]);
        }
    }
    m["history_simulation_source"] = json!({
        "source_namespace": X_SOURCE.0,
        "source_epoch": X_SOURCE.1,
        "producer_id": X_SOURCE.2,
        "producer_epoch": X_SOURCE.3,
        "x_db": x_db,
        "model_content_hash": model_hash,
    });
    if with_alloc_tape {
        let tape = json!({
            "format": "test-only-economic-source/1",
            "session_id": f.configs[0].session,
            "session_generation": f.configs[0].generation,
            "source": {
                "source_namespace": "test",
                "source_epoch": "one",
                "producer_id": "unit",
                "producer_epoch": "1"
            },
            "documents": [
                {"emitted_ns": "5", "raw_utf8": alloc_docs[0].1, "tokens": [alloc_docs[0].2]},
                {"emitted_ns": "5", "raw_utf8": alloc_docs[1].1, "tokens": [alloc_docs[1].2]}
            ]
        });
        let tape_raw = canonical_json(&tape);
        let tape_path = f.dir.join("alloc-tape.json");
        std::fs::write(&tape_path, &tape_raw).unwrap();
        m["test_only_capture_tape"] = json!({
            "path": tape_path,
            "sha256": crate::session_protocol::sha256_hex(tape_raw.as_bytes()),
        });
    }
    let sim_e_db = f.dir.join("sim-e.db");
    let sim_a_db = f.dir.join("sim-alpha.db");
    let sim_b_db = f.dir.join("sim-beta.db");
    m["e"]["db"] = json!(sim_e_db);
    m["chongs"][0]["db"] = json!(sim_a_db);
    m["chongs"][1]["db"] = json!(sim_b_db);
    let clocks = m["clock"]["plan"]["messages"].as_object_mut().unwrap();
    clocks.insert(
        "ReleaseExact-beta".into(),
        json!({"received_ns": "1200", "first_known_ns": "1201", "commit_ns": "1202"}),
    );
    clocks.insert(
        "sim-cap-0".into(),
        json!({"received_ns": "1210", "first_known_ns": "1211", "commit_ns": "1212"}),
    );
    clocks.insert(
        "sim-cap-1".into(),
        json!({"received_ns": "1220", "first_known_ns": "1221", "commit_ns": "1222"}),
    );
    let manifest_path = f.dir.join("sim-bound-manifest.json");
    std::fs::write(&manifest_path, canonical_json(&m)).unwrap();

    let mut e_cfg = store::Config::load(&manifest_path, &sim_e_db, None).unwrap();
    let a_cfg = store::Config::load(&manifest_path, &sim_a_db, Some("alpha")).unwrap();
    let b_cfg = store::Config::load(&manifest_path, &sim_b_db, Some("beta")).unwrap();
    store::init(&e_cfg).unwrap();
    store::init(&a_cfg).unwrap();
    store::init(&b_cfg).unwrap();
    let (mut ec, _) = store::open(&sim_e_db, false).unwrap();
    let (ac, _) = store::open(&sim_a_db, false).unwrap();
    let (bc, _) = store::open(&sim_b_db, false).unwrap();
    e_cfg.intake = capture_continuity::start(&mut ec, &e_cfg, 1).unwrap();
    f.configs = vec![e_cfg, a_cfg, b_cfg];
    f.dbs = vec![ec, ac, bc];

    for (i, (name, raw_utf8, tok)) in alloc_docs.iter().enumerate() {
        let captured = f.handle(
            0,
            &format!("capture-{name}"),
            json!({
                "op": "CaptureExternal",
                "raw_utf8": raw_utf8,
                "json_pointer": "/events/0",
                "token": tok,
                "source_event_time": null
            }),
        );
        assert_eq!(captured["kind"], "Recorded", "{captured}");
        let applied = f.handle(
            i + 1,
            &format!("apply-{name}"),
            json!({
                "op": "ApplyAllocation",
                "fact_key": captured["fact_key"],
                "allocation_id": format!("allocation-{name}"),
                "expected_fact_hash": captured["fact_hash"]
            }),
        );
        assert_eq!(applied["kind"], "Applied", "{applied}");
        let mut bp = bind_payloads[i].clone();
        bp["opening_basis"] = json!({
            "fact_key": captured["fact_key"],
            "expected_fact_hash": captured["fact_hash"],
            "allocation_id": format!("allocation-{name}")
        });
        let bound = f.handle(i + 1, &format!("bind-{name}"), bp);
        assert_eq!(bound["kind"], "VoiceBound", "{bound}");
    }
    f.step(0, "ImportResponsibility", "existing20");
    (f, profile)
}

#[test]
fn healthy_bound_simulation_x_preserves_2078_reserve_and_release_conditions() {
    let dir = tempfile::tempdir().unwrap();
    let x_db = dir.path().join("x-not-yet-started.sqlite");
    let (mut f, profile) = build_bound_sim_fixture(&x_db, false);

    // 1) 健康已绑 X（source_gap == false）在 X 尚未启动/建库前，Reserve 与 ReleaseExact 须按原 #2078 条件放行。
    assert!(!x_db.exists());
    committed(&mut f);
    dispatch(&mut f, "alpha");
    dispatch(&mut f, "beta");
    let rel_alpha = f.handle(0, "ReleaseExact-alpha", release_payload(&f, "alpha"));
    assert_eq!(rel_alpha["record"]["state"], "ReleasedExact", "{rel_alpha}");

    // 2) X 启动后存在无关在途 pending_batch 与 ExecutionRequested 时，健康 E 的 ReleaseExact 不得新增拒绝。
    let (mut xc, _) = crate::economic_session::open_durable_db(&x_db).unwrap();
    {
        let xtx = xc.transaction().unwrap();
        xtx.execute_batch(
            "CREATE TABLE IF NOT EXISTS x_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;",
        )
        .unwrap();
        for (k, v) in [
            ("profile_revision", "x-execution-profile/1"),
            ("profile_mode", "simulation"),
            ("history_simulation", "true"),
            ("writer_epoch", "1"),
        ] {
            xtx.execute("INSERT INTO x_meta VALUES(?1,?2)", rusqlite::params![k, v])
                .unwrap();
        }
        crate::history_simulation::runtime::initialize_in_transaction(&xtx, &profile, 1).unwrap();
        xtx.commit().unwrap();
    }
    xc.execute("INSERT INTO x_sim_meta VALUES('pending_batch','{}')", [])
        .unwrap();
    xc.execute(
        "INSERT INTO x_exact_commands(id,command,release_receipt,state,attempt_batch,accept_clock,release_evidence,execute_evidence) VALUES('unrelated','{}','rcpt','ExecutionRequested','{}','{}','{}',NULL)",
        [],
    )
    .unwrap();
    let rel_beta = f.handle(0, "ReleaseExact-beta", release_payload(&f, "beta"));
    assert_eq!(rel_beta["record"]["state"], "ReleasedExact", "{rel_beta}");

    // 3) 原本的财务检查仍然生效：未获准超额 Reserve/重复不同身份等仍受原规则约束，且 E 库审计通过。
    store::audit(&f.dbs[0], &f.configs[0]).unwrap();
}

#[test]
fn gap_bound_simulation_x_orders_resting_order_advance_bar_with_this_e_commit() {
    let dir = tempfile::tempdir().unwrap();
    let x_db = dir.path().join("x-ordered.sqlite");
    let (mut f, profile) = build_bound_sim_fixture(&x_db, true);

    // 1) 健康态完成 alpha/beta 预留与 alpha 正式放行，让 cmd-alpha 经真实 E/S/X 挂到 X 订单簿上。
    committed(&mut f);
    dispatch(&mut f, "alpha");
    dispatch(&mut f, "beta");
    let released_alpha = f.handle(0, "ReleaseExact-alpha", release_payload(&f, "alpha"));
    assert_eq!(
        released_alpha["record"]["state"], "ReleasedExact",
        "{released_alpha}"
    );
    let command_alpha = released_alpha["record"]["command"].clone();

    let e_serve_cfg = f.configs[0].clone();
    let e_sock = f.dir.join("e.sock");
    let e_stop = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let e_stop_flag = e_stop.clone();
    let e_uncertain = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let e_server = std::thread::spawn(move || {
        // 仅用 serve 提供只读 QueryReleasedExact 给 X 的 AcceptExact，随后优雅停止再做 epoch 2 恢复。
        let (mut c, runtime) = store::open(&e_serve_cfg.db, false).unwrap();
        let bounds = crate::session_transport::TransportBounds {
            frame: 16 * 1024 * 1024,
            read: std::time::Duration::from_millis(1000),
            write: std::time::Duration::from_millis(1000),
            response: std::time::Duration::from_millis(3000),
            queue: 4,
            connections: 4,
        };
        crate::session_transport::serve_unix_with_deadline_until(
            &e_serve_cfg.socket,
            bounds,
            |v| Ok(v),
            Box::new(move || e_stop_flag.load(Ordering::SeqCst)),
            e_uncertain,
            |e, _| service::handle(&mut c, &e_serve_cfg, 1, 1, &runtime, e),
        )
        .unwrap();
    });
    wait_for(&e_sock);

    let s_calls = Arc::new(AtomicUsize::new(0));
    controlled_s(f.dir.join("s.sock"), RELEASE_NS, s_calls.clone());

    let x_db_for_serve = x_db.clone();
    let serving_profile = profile.clone();
    std::thread::spawn(move || {
        let _x_writer_lock =
            crate::history_simulation::runtime::acquire_simulation_writer_lock(&x_db_for_serve)
                .unwrap();
        let (mut c, _) = crate::economic_session::open_durable_db(&x_db_for_serve).unwrap();
        {
            let xtx = c.transaction().unwrap();
            xtx.execute_batch("CREATE TABLE IF NOT EXISTS x_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;")
                .unwrap();
            for (k, v) in [
                ("profile_revision", "x-execution-profile/1"),
                ("profile_mode", "simulation"),
                ("history_simulation", "true"),
                ("writer_epoch", "1"),
            ] {
                xtx.execute("INSERT INTO x_meta VALUES(?1,?2)", rusqlite::params![k, v])
                    .unwrap();
            }
            crate::history_simulation::runtime::initialize_in_transaction(
                &xtx,
                &serving_profile,
                1,
            )
            .unwrap();
            xtx.commit().unwrap();
        }
        crate::history_simulation::runtime::serve(&mut c, &serving_profile, 1).unwrap()
    });
    let xs = f.dir.join("x.sock");
    wait_for(&xs);

    for index in 0..RELEASE_NS {
        assert_eq!(
            x(&xs, "AdvanceBar", bar(index, json!([])))["kind"],
            "SimulationBatch"
        );
    }
    let accepted = x(&xs, "AcceptExact", command_alpha.clone());
    assert_eq!(accepted["state"], "Accepted", "{accepted}");
    let resting_batch = x(
        &xs,
        "AdvanceBar",
        bar(RELEASE_NS, json!([command_alpha["change"]])),
    );
    assert_eq!(resting_batch["kind"], "SimulationBatch", "{resting_batch}");
    assert_eq!(
        resting_batch["originals"].as_array().unwrap().len(),
        0,
        "挂单落簿的 bar b0 尚未成交，原件数为 0"
    );

    // 关闭临时 E 监听（不写 clean_handoff），recover 到 epoch 2 进入真实 source_gap == true。
    e_stop.store(true, Ordering::SeqCst);
    e_server.join().unwrap();
    let rec2 = recover(&f.configs[0]).unwrap();
    assert_eq!(rec2["writer_epoch"], "2", "{rec2}");
    let (mut ec2, runtime2) = store::open(&f.configs[0].db, false).unwrap();
    let mut cfg2 = f.configs[0].clone();
    cfg2.intake = capture_continuity::start(&mut ec2, &cfg2, 2).unwrap();

    // 2) 当次门实测：E 在缺口态执行 ReleaseExact-beta，于 check_new_risk 之后、tx.commit() 之前暂停；
    //    并发向正式 X 发送旧挂单撮合的 AdvanceBar(b0+1, close_changes=[])。
    let (entered_tx, entered_rx) = std::sync::mpsc::channel::<()>();
    let (release_tx, release_rx) = std::sync::mpsc::channel::<()>();
    let entered_tx = std::sync::Mutex::new(Some(entered_tx));
    let release_rx = std::sync::Mutex::new(release_rx);
    let _hook = crate::economic_session::finance::install_test_before_commit_hook(
        cfg2.db.clone(),
        "ReleaseExact-beta",
        move || {
            if let Some(tx) = entered_tx.lock().unwrap().take() {
                let _ = tx.send(());
            }
            let _ = release_rx.lock().unwrap().recv();
        },
    );

    let mut beta_payload = release_payload(&f, "beta");
    beta_payload["writer_epoch"] = json!("2");
    let mut beta_env = envelope("ReleaseExact-beta", beta_payload);
    beta_env["schema_revision"] = json!(cfg2.revision().unwrap());
    beta_env["session_id"] = json!(cfg2.session);
    beta_env["session_generation"] = json!(cfg2.generation);

    let cfg2_for_e = cfg2.clone();
    let runtime2_for_e = runtime2.clone();
    let e_thread = std::thread::spawn(move || {
        let out = service::handle(&mut ec2, &cfg2_for_e, 2, 1, &runtime2_for_e, &beta_env);
        (ec2, out["payload"].clone())
    });

    if let Err(err) = entered_rx.recv_timeout(std::time::Duration::from_secs(20)) {
        let (_, early_reply) = e_thread.join().unwrap();
        panic!("E 应进入 before_commit 暂停点 ({err:?})，实际提前返回：{early_reply}");
    }

    // E 正持 FrontierGuard 处于核对后、COMMIT 前窗口，此时并发推进旧挂单的 b0+1。
    let before_wb = crate::history_simulation::store::frontier_exclusive_would_block_count();
    let xs_for_adv = xs.clone();
    let (adv_tx, adv_rx) = std::sync::mpsc::channel::<Value>();
    let x_thread = std::thread::spawn(move || {
        let reply = x(&xs_for_adv, "AdvanceBar", bar(RELEASE_NS + 1, json!([])));
        let _ = adv_tx.send(reply);
    });

    // 因果见证：必须真实观测到 X 在 lock_frontier_exclusive 处撞上内核 WouldBlock，而非只睡固定时长。
    let wb_deadline = std::time::Instant::now() + std::time::Duration::from_secs(3);
    while crate::history_simulation::store::frontier_exclusive_would_block_count() <= before_wb {
        assert!(
            std::time::Instant::now() < wb_deadline,
            "X 的 AdvanceBar(b0+1) 未在限定时间内到达 frontier.lock 争用点"
        );
        std::thread::sleep(std::time::Duration::from_millis(5));
    }
    if let Ok(early) = adv_rx.try_recv() {
        panic!("X 的 AdvanceBar(b0+1) 不得在 E 当次 COMMIT 完成前返回，实际提前返回：{early}");
    }
    {
        let ro = rusqlite::Connection::open_with_flags(
            &x_db,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
        )
        .unwrap();
        let raw_state: String = ro
            .query_row("SELECT v FROM x_sim_meta WHERE k='state'", [], |r| r.get(0))
            .unwrap();
        let st: Value = strict_json(raw_state.as_bytes()).unwrap();
        assert_eq!(
            st["last_bar"],
            json!(RELEASE_NS),
            "E 当次提交落盘前 x_db 必须停留在 b0={RELEASE_NS}"
        );
        let pending: Option<String> = ro
            .query_row(
                "SELECT v FROM x_sim_meta WHERE k='pending_batch'",
                [],
                |r| r.get(0),
            )
            .optional()
            .unwrap();
        assert!(
            pending.is_none(),
            "E 持共享前沿锁期间 X 不得写入 pending_batch"
        );
    }

    // 放开 E 的 before_commit -> E 当次提交成功落盘，随后释放锁；X 立即推进 b0+1 并产出 fill+fee 原件。
    release_tx.send(()).unwrap();
    let (mut ec2, this_reply) = e_thread.join().unwrap();
    assert_eq!(
        this_reply["record"]["state"], "ReleasedExact",
        "当次门在 b0 严序先于 b0+1 落盘：{this_reply}"
    );
    let adv_reply = adv_rx
        .recv_timeout(std::time::Duration::from_secs(5))
        .expect("E 提交释放前沿锁后 X 应立即完成 b0+1");
    x_thread.join().unwrap();
    assert_eq!(adv_reply["kind"], "SimulationBatch", "{adv_reply}");
    let originals = adv_reply["originals"].as_array().unwrap();
    assert_eq!(
        originals.len(),
        2,
        "旧挂单 cmd-alpha 在 b0+1 (close_changes=[]) 撮合生成 fill+fee 原件"
    );

    // 3) 下次门实测：b0+1 已落盘且原件未补录 -> 立即拦截（且已处于 check 之前提交的新前沿必拒）。
    let (_, _, _, img_after_this) = latest(&ec2).unwrap();
    let next_rel_alpha = json!({
        "state": "ReleasedExact",
        "owner": "B:alpha",
        "command": {"x_id": X_SOURCE.2, "x_epoch": 1}
    });
    let next_err = cfg2
        .intake
        .check_new_risk(&cfg2, &img_after_this, &next_rel_alpha, "1205")
        .unwrap_err();
    assert!(
        next_err.contains("模拟 X 原件未补录"),
        "b0+1 落盘后的下次门必须立刻拦截未补录原件：{next_err}"
    );

    // 4) 走原 CaptureExternal 补录 b0+1 两件原件 -> 仍停在 #1381 Pending(economic_components)，
    //    不拿 Pending 冒充 AC3 正控放行。
    for (i, doc) in originals.iter().enumerate() {
        let cap_payload = json!({
            "op": "CaptureExternal",
            "raw_utf8": canonical_json(doc),
            "json_pointer": "/event",
            "token": format!("tok-sim-{i}"),
            "source_event_time": doc["event"]["source"]["source_event_time"]
        });
        let cap_env = json!({
            "schema_revision": cfg2.revision().unwrap(),
            "session_id": cfg2.session,
            "session_generation": cfg2.generation,
            "source_namespace": X_SOURCE.0,
            "source_epoch": X_SOURCE.1,
            "producer_id": X_SOURCE.2,
            "producer_epoch": X_SOURCE.3,
            "message_id": format!("sim-cap-{i}"),
            "causal_refs": [],
            "payload_hash": hash(&cap_payload),
            "payload": cap_payload,
        });
        let cap_out =
            service::handle(&mut ec2, &cfg2, 2, 1, &runtime2, &cap_env)["payload"].clone();
        assert_eq!(cap_out["kind"], "Recorded", "{cap_out}");
    }
    let (_, _, _, img_captured) = latest(&ec2).unwrap();
    assert_eq!(img_captured["pending"].as_array().unwrap().len(), 2);
    assert_eq!(
        img_captured["pending"][0]["reason"]["on"],
        "economic_components"
    );
    let pending_err = cfg2
        .intake
        .check_new_risk(&cfg2, &img_captured, &next_rel_alpha, "1230")
        .unwrap_err();
    assert!(
        pending_err.contains("Pending")
            || pending_err.contains("未覆盖")
            || pending_err.contains("economic_components"),
        "模拟 X 非空 fill/fee 补录后仍归 #1381 Pending，不得放行：{pending_err}"
    );
}

#[test]
fn gap_bound_simulation_x_rejects_uncooperative_writer_without_creating_lock_files() {
    let dir = tempfile::tempdir().unwrap();
    let x_db = dir.path().join("x-legacy.sqlite");
    let (mut f, profile) = build_bound_sim_fixture(&x_db, true);

    committed(&mut f);
    dispatch(&mut f, "alpha");
    dispatch(&mut f, "beta");
    let rel_alpha = f.handle(0, "ReleaseExact-alpha", release_payload(&f, "alpha"));
    assert_eq!(rel_alpha["record"]["state"], "ReleasedExact", "{rel_alpha}");

    // 模拟旧 X 直接初始化 x_db：仅建库（不创建 frontier.lock），且初始没有 writer.lock。
    {
        let (mut xc, _) = crate::economic_session::open_durable_db(&x_db).unwrap();
        let xtx = xc.transaction().unwrap();
        xtx.execute_batch(
            "CREATE TABLE IF NOT EXISTS x_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;",
        )
        .unwrap();
        for (k, v) in [
            ("profile_revision", "x-execution-profile/1"),
            ("profile_mode", "simulation"),
            ("history_simulation", "true"),
            ("writer_epoch", "1"),
        ] {
            xtx.execute("INSERT INTO x_meta VALUES(?1,?2)", rusqlite::params![k, v])
                .unwrap();
        }
        crate::history_simulation::runtime::initialize_in_transaction(&xtx, &profile, 1).unwrap();
        xtx.commit().unwrap();
    }
    let canonical = x_db.canonicalize().unwrap();
    let writer_lock_path = std::path::PathBuf::from(format!("{}.writer.lock", canonical.display()));
    let frontier_lock_path =
        std::path::PathBuf::from(format!("{}.frontier.lock", canonical.display()));
    // 清理 initialize_in_transaction 在旧测路径创建的 frontier.lock，还原旧 X 磁盘形态。
    let _ = std::fs::remove_file(&frontier_lock_path);
    assert!(!writer_lock_path.exists());
    assert!(!frontier_lock_path.exists());

    // E recover 到 epoch 2 进入真实 source_gap == true。
    let rec2 = recover(&f.configs[0]).unwrap();
    assert_eq!(rec2["writer_epoch"], "2", "{rec2}");
    let (mut ec2, runtime2) = store::open(&f.configs[0].db, false).unwrap();
    let mut cfg2 = f.configs[0].clone();
    cfg2.intake = capture_continuity::start(&mut ec2, &cfg2, 2).unwrap();

    let mut beta_payload = release_payload(&f, "beta");
    beta_payload["writer_epoch"] = json!("2");
    let mut beta_env = envelope("ReleaseExact-beta", beta_payload);
    beta_env["schema_revision"] = json!(cfg2.revision().unwrap());
    beta_env["session_id"] = json!(cfg2.session);
    beta_env["session_generation"] = json!(cfg2.generation);

    // 1) 缺少 writer.lock 时：E 必须拒绝且不得新建任何锁文件。
    let (cut_before, _, _, _) = latest(&ec2).unwrap();
    let err_missing =
        service::handle(&mut ec2, &cfg2, 2, 1, &runtime2, &beta_env)["payload"].clone();
    assert_eq!(err_missing["kind"], "Error", "{err_missing}");
    assert!(
        err_missing["error"]
            .as_str()
            .unwrap()
            .contains("单写者准入锁"),
        "{err_missing}"
    );
    assert!(!writer_lock_path.exists(), "E 不得新建 writer.lock");
    assert!(!frontier_lock_path.exists(), "E 不得新建 frontier.lock");
    assert_eq!(latest(&ec2).unwrap().0, cut_before);

    // 2) 旧 X 正在运行（独占 writer.lock，无 frontier.lock）：E 必须拒绝且不得新建 frontier.lock。
    let old_x_lock = crate::session_transport::process_lock(&x_db, "X").unwrap();
    assert!(
        crate::history_simulation::runtime::acquire_simulation_writer_lock(&x_db)
            .unwrap_err()
            .contains("StaleWriter"),
        "旧 X 独占期间新 X 不得并存"
    );
    let err_old_running =
        service::handle(&mut ec2, &cfg2, 2, 1, &runtime2, &beta_env)["payload"].clone();
    assert_eq!(err_old_running["kind"], "Error", "{err_old_running}");
    assert!(
        err_old_running["error"]
            .as_str()
            .unwrap()
            .contains("旧版或非协作 X"),
        "{err_old_running}"
    );
    assert!(
        !frontier_lock_path.exists(),
        "E 不得为旧 X 新建 frontier.lock"
    );
    assert_eq!(latest(&ec2).unwrap().0, cut_before);

    // 3) 即使磁盘上残留 frontier.lock，旧 X / R4 X 独占 writer.lock 仍必须被 E 拒绝。
    std::fs::write(&frontier_lock_path, b"").unwrap();
    let err_r4_running =
        service::handle(&mut ec2, &cfg2, 2, 1, &runtime2, &beta_env)["payload"].clone();
    assert_eq!(err_r4_running["kind"], "Error", "{err_r4_running}");
    assert!(
        err_r4_running["error"]
            .as_str()
            .unwrap()
            .contains("writer.lock 被独占持有"),
        "{err_r4_running}"
    );
    assert_eq!(latest(&ec2).unwrap().0, cut_before);

    // 4) 拒绝后 E 的已有只读/查询口仍可用。
    let mut read_env = envelope(
        "ReadView-after-refusal",
        json!({"op": "ReadView", "cut": null, "as_known_ns": null}),
    );
    read_env["schema_revision"] = json!(cfg2.revision().unwrap());
    read_env["session_id"] = json!(cfg2.session);
    read_env["session_generation"] = json!(cfg2.generation);
    let view = service::handle(&mut ec2, &cfg2, 2, 1, &runtime2, &read_env)["payload"].clone();
    assert_eq!(view["kind"], "EconomicView", "{view}");

    // 5) 释放旧 X 锁后，单写者互斥：新 X 之间互斥、新 X 与旧 X 互斥。
    drop(old_x_lock);
    let new_x_lock =
        crate::history_simulation::runtime::acquire_simulation_writer_lock(&x_db).unwrap();
    assert!(
        crate::history_simulation::runtime::acquire_simulation_writer_lock(&x_db)
            .unwrap_err()
            .contains("StaleWriter"),
        "两个新模拟 X 不得并存"
    );
    assert!(
        crate::session_transport::process_lock(&x_db, "X")
            .unwrap_err()
            .contains("StaleWriter"),
        "新模拟 X 运行期间旧 X / 非模拟 X 不得启动"
    );
    drop(new_x_lock);
}

#[cfg(target_os = "linux")]
struct LinuxDirWatcher {
    fd: std::os::fd::RawFd,
}

#[cfg(target_os = "linux")]
impl LinuxDirWatcher {
    fn new(dir: &Path) -> Self {
        Self::with_mask(
            dir,
            libc::IN_CREATE
                | libc::IN_MODIFY
                | libc::IN_DELETE
                | libc::IN_MOVED_FROM
                | libc::IN_MOVED_TO
                | libc::IN_ATTRIB,
        )
    }

    fn with_mask(dir: &Path, mask: u32) -> Self {
        use std::ffi::CString;
        use std::os::unix::ffi::OsStrExt;
        let fd = unsafe { libc::inotify_init1(libc::IN_NONBLOCK | libc::IN_CLOEXEC) };
        assert!(fd >= 0, "inotify_init1 failed");
        let c_dir = CString::new(dir.as_os_str().as_bytes()).unwrap();
        let wd = unsafe { libc::inotify_add_watch(fd, c_dir.as_ptr(), mask) };
        assert!(wd >= 0, "inotify_add_watch failed");
        Self { fd }
    }

    fn drain(&self) -> Vec<(String, u32)> {
        let mut events = Vec::new();
        let mut buf = [0u8; 65536];
        loop {
            let n =
                unsafe { libc::read(self.fd, buf.as_mut_ptr() as *mut libc::c_void, buf.len()) };
            if n <= 0 {
                break;
            }
            let n = n as usize;
            let mut off = 0;
            let hdr_len = std::mem::size_of::<libc::inotify_event>();
            while off + hdr_len <= n {
                let ev = unsafe {
                    std::ptr::read_unaligned(buf.as_ptr().add(off) as *const libc::inotify_event)
                };
                off += hdr_len;
                let name_len = ev.len as usize;
                let raw_name = &buf[off..off + name_len];
                let end = raw_name
                    .iter()
                    .position(|&b| b == 0)
                    .unwrap_or(raw_name.len());
                let name = String::from_utf8_lossy(&raw_name[..end]).into_owned();
                off += name_len;
                events.push((name, ev.mask));
            }
        }
        events
    }
}

#[cfg(target_os = "linux")]
impl Drop for LinuxDirWatcher {
    fn drop(&mut self) {
        unsafe {
            libc::close(self.fd);
        }
    }
}

fn dir_file_digests(dir: &Path) -> std::collections::BTreeMap<String, String> {
    let mut out = std::collections::BTreeMap::new();
    for entry in std::fs::read_dir(dir).unwrap() {
        let entry = entry.unwrap();
        let name = entry.file_name().to_string_lossy().into_owned();
        let bytes = std::fs::read(entry.path()).unwrap();
        out.insert(name, crate::session_protocol::sha256_hex(&bytes));
    }
    out
}

fn append_suffix(base: &Path, suffix: &str) -> std::path::PathBuf {
    let mut s = base.as_os_str().to_os_string();
    s.push(suffix);
    std::path::PathBuf::from(s)
}

#[test]
fn gap_bound_simulation_x_reads_uncheckpointed_wal_without_mutating_shm_or_sidecars() {
    let dir = tempfile::tempdir().unwrap();
    // 含 URI 特殊字符（#、?、%、&、=、空格、中文）的普通可写目录与库文件名，并经符号链接绑定。
    let special_dir = dir.path().join("dir #1?q=2&k=%20%25中文");
    std::fs::create_dir_all(&special_dir).unwrap();
    let x_real = special_dir.join("x#db?mode=rw&readonly_shm=0.sqlite");
    let x_link = dir.path().join("x-link.sqlite");
    std::os::unix::fs::symlink(&x_real, &x_link).unwrap();

    let (mut f, profile) = build_bound_sim_fixture(&x_link, true);

    committed(&mut f);
    dispatch(&mut f, "alpha");
    dispatch(&mut f, "beta");
    let rel_alpha = f.handle(0, "ReleaseExact-alpha", release_payload(&f, "alpha"));
    assert_eq!(rel_alpha["record"]["state"], "ReleasedExact", "{rel_alpha}");
    let command_alpha = rel_alpha["record"]["command"].clone();

    // 1) 在独立供体 X 实例上经真实 E/S/X 挂出旧单并构造两份未 checkpoint WAL 的停机磁盘快照：
    //    - x_real：主库停在 b0-1，b0（含已挂出旧单、0 条成交原件）仅在未 checkpoint 的 WAL 中；
    //    - x_uncap：主库停在 b0（0 条原件），b0+1（旧单撮合产出 2 条未补录 fill+fee）仅在未 checkpoint 的 WAL 中。
    let e_serve_cfg = f.configs[0].clone();
    let e_sock = f.dir.join("e.sock");
    let e_stop = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let e_stop_flag = e_stop.clone();
    let e_uncertain = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let e_server = std::thread::spawn(move || {
        let (mut c, runtime) = store::open(&e_serve_cfg.db, false).unwrap();
        let bounds = crate::session_transport::TransportBounds {
            frame: 16 * 1024 * 1024,
            read: std::time::Duration::from_millis(1000),
            write: std::time::Duration::from_millis(1000),
            response: std::time::Duration::from_millis(3000),
            queue: 4,
            connections: 4,
        };
        crate::session_transport::serve_unix_with_deadline_until(
            &e_serve_cfg.socket,
            bounds,
            |v| Ok(v),
            Box::new(move || e_stop_flag.load(Ordering::SeqCst)),
            e_uncertain,
            |e, _| service::handle(&mut c, &e_serve_cfg, 1, 1, &runtime, e),
        )
        .unwrap();
    });
    wait_for(&e_sock);

    let s_calls = Arc::new(AtomicUsize::new(0));
    controlled_s(f.dir.join("s.sock"), RELEASE_NS, s_calls.clone());

    let donor_dir = tempfile::tempdir().unwrap();
    let donor_db = donor_dir.path().join("donor.sqlite");
    let donor_db_for_serve = donor_db.clone();
    let donor_profile = profile.clone();
    std::thread::spawn(move || {
        let _x_writer_lock =
            crate::history_simulation::runtime::acquire_simulation_writer_lock(&donor_db_for_serve)
                .unwrap();
        let (mut c, _) = crate::economic_session::open_durable_db(&donor_db_for_serve).unwrap();
        c.execute_batch("PRAGMA wal_autocheckpoint = 0;").unwrap();
        {
            let xtx = c.transaction().unwrap();
            xtx.execute_batch(
                "CREATE TABLE IF NOT EXISTS x_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;",
            )
            .unwrap();
            for (k, v) in [
                ("profile_revision", "x-execution-profile/1"),
                ("profile_mode", "simulation"),
                ("history_simulation", "true"),
                ("writer_epoch", "1"),
            ] {
                xtx.execute("INSERT INTO x_meta VALUES(?1,?2)", rusqlite::params![k, v])
                    .unwrap();
            }
            crate::history_simulation::runtime::initialize_in_transaction(&xtx, &donor_profile, 1)
                .unwrap();
            xtx.commit().unwrap();
        }
        let _ = crate::history_simulation::runtime::serve(&mut c, &donor_profile, 1);
    });
    let xs = f.dir.join("x.sock");
    wait_for(&xs);

    for index in 0..RELEASE_NS {
        assert_eq!(
            x(&xs, "AdvanceBar", bar(index, json!([])))["kind"],
            "SimulationBatch"
        );
    }
    // 将 0..=b0-1 刷入供体主库并截断 WAL。
    {
        let ck = rusqlite::Connection::open(&donor_db).unwrap();
        let _: (i64, i64, i64) = ck
            .query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |r| {
                Ok((r.get(0)?, r.get(1)?, r.get(2)?))
            })
            .unwrap();
    }
    assert_eq!(
        x(&xs, "AcceptExact", command_alpha.clone())["state"],
        "Accepted"
    );
    let resting_batch = x(
        &xs,
        "AdvanceBar",
        bar(RELEASE_NS, json!([command_alpha["change"]])),
    );
    assert_eq!(resting_batch["kind"], "SimulationBatch", "{resting_batch}");
    assert_eq!(resting_batch["originals"].as_array().unwrap().len(), 0);

    // 复制快照 1（x_real）：b0 仅在未 checkpoint 的 WAL 中。
    std::fs::copy(&donor_db, &x_real).unwrap();
    std::fs::copy(
        append_suffix(&donor_db, "-wal"),
        append_suffix(&x_real, "-wal"),
    )
    .unwrap();
    std::fs::copy(
        append_suffix(&donor_db, "-shm"),
        append_suffix(&x_real, "-shm"),
    )
    .unwrap();
    std::fs::write(append_suffix(&x_real, ".writer.lock"), b"").unwrap();

    // 将 b0 刷入供体主库，再推进 b0+1（旧挂单撮合产出 2 条未补录 fill+fee 仅落于未 checkpoint WAL）。
    {
        let ck = rusqlite::Connection::open(&donor_db).unwrap();
        let _: (i64, i64, i64) = ck
            .query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |r| {
                Ok((r.get(0)?, r.get(1)?, r.get(2)?))
            })
            .unwrap();
    }
    let fill_batch = x(&xs, "AdvanceBar", bar(RELEASE_NS + 1, json!([])));
    assert_eq!(fill_batch["kind"], "SimulationBatch", "{fill_batch}");
    assert_eq!(fill_batch["originals"].as_array().unwrap().len(), 2);

    let x_uncap = special_dir.join("x#uncap?mode=rw.sqlite");
    std::fs::copy(&donor_db, &x_uncap).unwrap();
    std::fs::copy(
        append_suffix(&donor_db, "-wal"),
        append_suffix(&x_uncap, "-wal"),
    )
    .unwrap();
    std::fs::copy(
        append_suffix(&donor_db, "-shm"),
        append_suffix(&x_uncap, "-shm"),
    )
    .unwrap();
    std::fs::write(append_suffix(&x_uncap, ".writer.lock"), b"").unwrap();

    // 确认仅读主库（无 WAL）看不到 b0（x_real）与 b0+1 原件（x_uncap）。
    let check_main_only = |src: &Path, tag: &str| -> (i64, i64) {
        let copy = donor_dir.path().join(tag);
        std::fs::copy(src, &copy).unwrap();
        let mc = rusqlite::Connection::open_with_flags(
            &copy,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
        )
        .unwrap();
        let raw_state: String = mc
            .query_row("SELECT v FROM x_sim_meta WHERE k='state'", [], |r| r.get(0))
            .unwrap();
        let st: Value = serde_json::from_str(&raw_state).unwrap();
        let orig_cnt: i64 = mc
            .query_row("SELECT count(*) FROM x_sim_originals", [], |r| r.get(0))
            .unwrap();
        (st["last_bar"].as_i64().unwrap(), orig_cnt)
    };
    assert_eq!(
        check_main_only(&x_real, "main-clean.sqlite"),
        (RELEASE_NS - 1, 0)
    );
    assert_eq!(
        check_main_only(&x_uncap, "main-uncap.sqlite"),
        (RELEASE_NS, 0)
    );

    // 2) E 经 recover 进入真实 source_gap == true。
    e_stop.store(true, Ordering::SeqCst);
    e_server.join().unwrap();
    let rec2 = recover(&f.configs[0]).unwrap();
    assert_eq!(rec2["writer_epoch"], "2", "{rec2}");
    let (mut ec2, runtime2) = store::open(&f.configs[0].db, false).unwrap();
    let mut cfg2 = f.configs[0].clone();
    cfg2.intake = capture_continuity::start(&mut ec2, &cfg2, 2).unwrap();
    let (cut_before, _, _, _) = latest(&ec2).unwrap();

    let mut beta_payload = release_payload(&f, "beta");
    beta_payload["writer_epoch"] = json!("2");
    let mut beta_env = envelope("ReleaseExact-beta", beta_payload);
    beta_env["schema_revision"] = json!(cfg2.revision().unwrap());
    beta_env["session_id"] = json!(cfg2.session);
    beta_env["session_generation"] = json!(cfg2.generation);

    // 2a) 负向未 checkpoint WAL：x_uncap 主库只有 b0 且 0 原件，但未 checkpoint WAL 有 2 条未补录原件；
    //     缺口态 E 必须真实读出 WAL 并拒绝放行，绝不能漏看 WAL 后误放。
    let mut cfg2_uncap = cfg2.clone();
    cfg2_uncap.manifest["history_simulation_source"]["x_db"] = json!(x_uncap);
    let before_uncap = dir_file_digests(&special_dir);
    #[cfg(target_os = "linux")]
    let w_uncap = LinuxDirWatcher::new(&special_dir);
    let refused_uncap =
        service::handle(&mut ec2, &cfg2_uncap, 2, 1, &runtime2, &beta_env)["payload"].clone();
    assert_eq!(refused_uncap["kind"], "Error", "{refused_uncap}");
    assert!(
        refused_uncap["error"]
            .as_str()
            .unwrap()
            .contains("模拟 X 原件未补录"),
        "{refused_uncap}"
    );
    #[cfg(target_os = "linux")]
    assert!(w_uncap.drain().is_empty(), "负向 WAL 拒绝时不得写侧件");
    assert_eq!(before_uncap, dir_file_digests(&special_dir));
    assert_eq!(latest(&ec2).unwrap().0, cut_before);

    // 2b) 侧件不可安全读取时（有 -wal 缺 -shm / 有孤立 -shm 缺 -wal / -shm 或 -wal 无读权限），
    //     缺口态拒新风险且不新建侧件，绝不回落陈旧主库；E 既有只读查询与原已提交收据重送仍可用。
    let wal_path = append_suffix(&x_real, "-wal");
    let shm_path = append_suffix(&x_real, "-shm");
    let saved_shm = std::fs::read(&shm_path).unwrap();
    let saved_wal = std::fs::read(&wal_path).unwrap();

    std::fs::remove_file(&shm_path).unwrap();
    let digests_no_shm = dir_file_digests(&special_dir);
    #[cfg(target_os = "linux")]
    let w_no_shm = LinuxDirWatcher::new(&special_dir);
    let err_no_shm =
        service::handle(&mut ec2, &cfg2, 2, 1, &runtime2, &beta_env)["payload"].clone();
    assert_eq!(err_no_shm["kind"], "Error", "{err_no_shm}");
    #[cfg(target_os = "linux")]
    assert!(
        w_no_shm.drain().is_empty(),
        "有 -wal 缺 -shm 拒绝时不得写/建侧件"
    );
    assert_eq!(digests_no_shm, dir_file_digests(&special_dir));
    assert_eq!(latest(&ec2).unwrap().0, cut_before);

    // 还原 -shm、删 -wal（孤立 -shm）：必须拒绝且绝不得由 sqlite3WalOpen 建空 -wal。
    std::fs::write(&shm_path, &saved_shm).unwrap();
    std::fs::remove_file(&wal_path).unwrap();
    let digests_stray_shm = dir_file_digests(&special_dir);
    #[cfg(target_os = "linux")]
    let w_stray_shm = LinuxDirWatcher::new(&special_dir);
    let err_stray_shm =
        service::handle(&mut ec2, &cfg2, 2, 1, &runtime2, &beta_env)["payload"].clone();
    assert_eq!(err_stray_shm["kind"], "Error", "{err_stray_shm}");
    #[cfg(target_os = "linux")]
    assert!(
        w_stray_shm.drain().is_empty(),
        "孤立 -shm 拒绝时不得由 sqlite3WalOpen 建空 -wal"
    );
    assert_eq!(digests_stray_shm, dir_file_digests(&special_dir));
    assert_eq!(latest(&ec2).unwrap().0, cut_before);

    // 还原 -wal，再测 -shm 与 -wal 无读权限（非 root）。
    std::fs::write(&wal_path, &saved_wal).unwrap();
    if unsafe { libc::geteuid() } != 0 {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&shm_path, std::fs::Permissions::from_mode(0o000)).unwrap();
        #[cfg(target_os = "linux")]
        let w_perm = LinuxDirWatcher::new(&special_dir);
        let err_perm =
            service::handle(&mut ec2, &cfg2, 2, 1, &runtime2, &beta_env)["payload"].clone();
        assert_eq!(err_perm["kind"], "Error", "{err_perm}");
        #[cfg(target_os = "linux")]
        assert!(w_perm.drain().is_empty(), "-shm 不可读拒绝时不得写侧件");
        assert_eq!(latest(&ec2).unwrap().0, cut_before);
        std::fs::set_permissions(&shm_path, std::fs::Permissions::from_mode(0o600)).unwrap();

        std::fs::set_permissions(&wal_path, std::fs::Permissions::from_mode(0o000)).unwrap();
        #[cfg(target_os = "linux")]
        let w_wal_perm = LinuxDirWatcher::new(&special_dir);
        let err_wal_perm =
            service::handle(&mut ec2, &cfg2, 2, 1, &runtime2, &beta_env)["payload"].clone();
        assert_eq!(err_wal_perm["kind"], "Error", "{err_wal_perm}");
        #[cfg(target_os = "linux")]
        assert!(w_wal_perm.drain().is_empty(), "-wal 不可读拒绝时不得写侧件");
        assert_eq!(latest(&ec2).unwrap().0, cut_before);
        std::fs::set_permissions(&wal_path, std::fs::Permissions::from_mode(0o600)).unwrap();
    }

    // 拒绝后 E 既有读口（ReadView / QueryReleasedExact）仍可用。
    let mut read_env = envelope(
        "ReadView-after-sidecar-refusal",
        json!({"op": "ReadView", "cut": null, "as_known_ns": null}),
    );
    read_env["schema_revision"] = json!(cfg2.revision().unwrap());
    read_env["session_id"] = json!(cfg2.session);
    read_env["session_generation"] = json!(cfg2.generation);
    let view = service::handle(&mut ec2, &cfg2, 2, 1, &runtime2, &read_env)["payload"].clone();
    assert_eq!(view["kind"], "EconomicView", "{view}");

    let mut q_env = envelope(
        "QueryCommand-alpha-after-refusal",
        json!({
            "op": "QueryCommand",
            "command_id": command_alpha["command_id"],
            "cut": null,
            "as_known_ns": null
        }),
    );
    q_env["schema_revision"] = json!(cfg2.revision().unwrap());
    q_env["session_id"] = json!(cfg2.session);
    q_env["session_generation"] = json!(cfg2.generation);
    let q_reply = service::handle(&mut ec2, &cfg2, 2, 1, &runtime2, &q_env)["payload"].clone();
    assert_eq!(q_reply["state"], "ReleasedExact", "{q_reply}");

    // 2c) URI 特殊字符 + 符号链接路径的锁汇合：经符号链接持旧 writer.lock 时 E 必拒。
    let held_old = crate::session_transport::process_lock(&x_link, "X").unwrap();
    let refused_old =
        service::handle(&mut ec2, &cfg2, 2, 1, &runtime2, &beta_env)["payload"].clone();
    assert_eq!(refused_old["kind"], "Error", "{refused_old}");
    assert!(
        refused_old["error"]
            .as_str()
            .unwrap()
            .contains("旧版或非协作 X"),
        "{refused_old}"
    );
    drop(held_old);

    // 3) 正向未 checkpoint WAL + 可写目录零修改：读出未 checkpoint 的 b0 并返回真 ReleasedExact，
    //    且不创建/修改/删除主库、WAL/SHM 与既有锁文件（无 frontier.lock 创建）。
    let before_clean = dir_file_digests(&special_dir);
    #[cfg(target_os = "linux")]
    let w_clean = LinuxDirWatcher::new(&special_dir);
    let rel_beta = service::handle(&mut ec2, &cfg2, 2, 1, &runtime2, &beta_env)["payload"].clone();
    assert_eq!(rel_beta["record"]["state"], "ReleasedExact", "{rel_beta}");
    #[cfg(target_os = "linux")]
    {
        let evs = w_clean.drain();
        assert!(
            evs.is_empty(),
            "缺口态只读核清不得在可写 X 目录产生 CREATE/MODIFY/DELETE/ATTRIB 事件，实际：{evs:?}"
        );
    }
    assert_eq!(
        before_clean,
        dir_file_digests(&special_dir),
        "主库、WAL、SHM 与 writer.lock 必须逐字节不变且不得新建 frontier.lock"
    );
}

#[test]
fn readonly_source_vfs_survives_writer_close_interleaving_without_creating_wal() {
    use crate::history_simulation::intake::open_readonly_source_db;

    let dir = tempfile::tempdir().unwrap();
    let db_dir = dir.path().join("x-close-race");
    std::fs::create_dir_all(&db_dir).unwrap();
    let x_db = db_dir.join("x.db");
    let x_wal = append_suffix(&x_db, "-wal");
    let x_shm = append_suffix(&x_db, "-shm");

    // 1) 写者打开 WAL 库并写入未 checkpoint 提交；E 在 SQLite 取得 SHARED 锁之前打开只读句柄；
    //    随后写者走正常末连接析构 checkpoint 并删除 -wal/-shm（主库头仍为 WAL [2,2]）；
    //    仅剩 E 活动时发起只读事务，必须直接读出已落主库事实，且绝不创建空 x.db-wal/-shm，
    //    亦无任何目录变更或 IN_CLOSE_WRITE。
    let writer = rusqlite::Connection::open(&x_db).unwrap();
    writer
        .execute_batch(
            "PRAGMA journal_mode = WAL;
             PRAGMA wal_autocheckpoint = 0;
             CREATE TABLE t(v INTEGER);
             INSERT INTO t VALUES (10);",
        )
        .unwrap();
    assert!(x_wal.exists() && x_shm.exists(), "写者应已生成 WAL/SHM");

    let mut reader = open_readonly_source_db(&x_db).unwrap();
    drop(writer);
    assert!(
        !x_wal.exists() && !x_shm.exists(),
        "写者正常末连接关闭应已删除 WAL/SHM"
    );

    let before_close_race = dir_file_digests(&db_dir);
    #[cfg(target_os = "linux")]
    let w_race = LinuxDirWatcher::with_mask(
        &db_dir,
        libc::IN_CREATE
            | libc::IN_MODIFY
            | libc::IN_DELETE
            | libc::IN_MOVED_FROM
            | libc::IN_MOVED_TO
            | libc::IN_ATTRIB
            | libc::IN_CLOSE_WRITE,
    );
    {
        let tx = reader.transaction().unwrap();
        let v: i64 = tx.query_row("SELECT v FROM t", [], |r| r.get(0)).unwrap();
        assert_eq!(v, 10, "正常闭库双缺 WAL/SHM 须可读出已 checkpoint 事实");
    }
    drop(reader);
    assert!(
        !x_wal.exists() && !x_shm.exists(),
        "E 读毕正常闭库后绝不得新建空 WAL/SHM"
    );
    #[cfg(target_os = "linux")]
    {
        let evs = w_race.drain();
        assert!(
            evs.is_empty(),
            "写者关库清理后仅 E 活动不得产生任何创建/修改/删除/CLOSE_WRITE 事件，实际：{evs:?}"
        );
    }
    assert_eq!(before_close_race, dir_file_digests(&db_dir));

    // 2) E 已通过只读事务持有 SHARED 锁后写者关闭：写者末连接析构无法获取 EXCLUSIVE 锁，
    //    不得删除 WAL/SHM，且 E 后续读与关闭均零副作用（不回写、不清理侧件）。
    let writer2 = rusqlite::Connection::open(&x_db).unwrap();
    writer2
        .execute_batch(
            "PRAGMA wal_autocheckpoint = 0;
             INSERT INTO t VALUES (20);",
        )
        .unwrap();
    assert!(x_wal.exists() && x_shm.exists());

    let mut reader2 = open_readonly_source_db(&x_db).unwrap();
    let tx2 = reader2.transaction().unwrap();
    let cnt: i64 = tx2
        .query_row("SELECT count(*) FROM t", [], |r| r.get(0))
        .unwrap();
    assert_eq!(cnt, 2);
    drop(writer2);
    assert!(
        x_wal.exists() && x_shm.exists(),
        "E 持 SHARED 锁时写者关闭不得删除 WAL/SHM"
    );

    let before_after_shared = dir_file_digests(&db_dir);
    // 同进程内 SQLite POSIX 锁会延迟到最后一个句柄关闭时才 close(writer2) 遗留的 O_RDWR fd
    // （触发无写入的 IN_CLOSE_WRITE），此处按物理副作用契约监测创建/修改/删除/改名/属性变更。
    #[cfg(target_os = "linux")]
    let w_shared = LinuxDirWatcher::new(&db_dir);
    let total: i64 = tx2
        .query_row("SELECT sum(v) FROM t", [], |r| r.get(0))
        .unwrap();
    assert_eq!(total, 30);
    drop(tx2);
    drop(reader2);
    assert!(
        x_wal.exists() && x_shm.exists(),
        "E 自身关闭绝不得 checkpoint 或删除 WAL/SHM"
    );
    #[cfg(target_os = "linux")]
    {
        let evs = w_shared.drain();
        assert!(
            evs.is_empty(),
            "E 持 SHARED 锁读毕并关闭不得产生目录写事件，实际：{evs:?}"
        );
    }
    assert_eq!(before_after_shared, dir_file_digests(&db_dir));

    // 3) 0 字节主库配遗留 -wal：ro_delete 阻断 pagerOpenWalIfPresent 删除 -wal。
    let zero_dir = dir.path().join("zero-main");
    std::fs::create_dir_all(&zero_dir).unwrap();
    let zero_db = zero_dir.join("zero.db");
    let zero_wal = append_suffix(&zero_db, "-wal");
    std::fs::write(&zero_db, b"").unwrap();
    std::fs::write(&zero_wal, b"stray-wal-payload").unwrap();
    let before_zero = dir_file_digests(&zero_dir);
    #[cfg(target_os = "linux")]
    let w_zero = LinuxDirWatcher::with_mask(
        &zero_dir,
        libc::IN_CREATE
            | libc::IN_MODIFY
            | libc::IN_DELETE
            | libc::IN_MOVED_FROM
            | libc::IN_MOVED_TO
            | libc::IN_ATTRIB
            | libc::IN_CLOSE_WRITE,
    );
    let mut zero_reader = open_readonly_source_db(&zero_db).unwrap();
    {
        let tx = zero_reader.transaction().unwrap();
        assert!(tx
            .query_row("SELECT count(*) FROM sqlite_master", [], |r| r
                .get::<_, i64>(0))
            .is_err());
    }
    drop(zero_reader);
    assert!(zero_wal.exists(), "0 字节主库下不得删除遗留 -wal");
    #[cfg(target_os = "linux")]
    {
        let evs = w_zero.drain();
        assert!(evs.is_empty(), "0 字节主库拒绝时不得产生事件：{evs:?}");
    }
    assert_eq!(before_zero, dir_file_digests(&zero_dir));

    // 4) 物理只读来源（chmod 555 目录 + chmod 444 文件，非 root）保留完整读取能力。
    if unsafe { libc::geteuid() } != 0 {
        use std::os::unix::fs::PermissionsExt;
        for f in [&x_db, &x_wal, &x_shm] {
            std::fs::set_permissions(f, std::fs::Permissions::from_mode(0o444)).unwrap();
        }
        std::fs::set_permissions(&db_dir, std::fs::Permissions::from_mode(0o555)).unwrap();
        let mut ro_reader = open_readonly_source_db(&x_db).unwrap();
        let tx = ro_reader.transaction().unwrap();
        let sum_ro: i64 = tx
            .query_row("SELECT sum(v) FROM t", [], |r| r.get(0))
            .unwrap();
        assert_eq!(sum_ro, 30);
        drop(tx);
        drop(ro_reader);
        std::fs::set_permissions(&db_dir, std::fs::Permissions::from_mode(0o755)).unwrap();
        for f in [&x_db, &x_wal, &x_shm] {
            std::fs::set_permissions(f, std::fs::Permissions::from_mode(0o644)).unwrap();
        }
    }
}

#[test]
fn readonly_source_vfs_preserves_zero_byte_readonly_sidecar_modes_without_fchmod() {
    use crate::history_simulation::intake::open_readonly_source_db;
    use std::os::unix::fs::{MetadataExt, PermissionsExt};

    let dir = tempfile::tempdir().unwrap();
    let db_dir = dir.path().join("x-mode-preserve");
    std::fs::create_dir_all(&db_dir).unwrap();
    let x_db = db_dir.join("x.db");
    let x_wal = append_suffix(&x_db, "-wal");
    let x_shm = append_suffix(&x_db, "-shm");

    // 1) 主库 0644 + checkpoint(TRUNCATE) 后的 0 字节 WAL 设为 0444（复现 R7 probe.py 元数据反例）：
    //    只读打开与查询必须成功，且绝不调用 fchmod 改写 WAL mode/ctime（零 IN_ATTRIB）。
    let writer = rusqlite::Connection::open(&x_db).unwrap();
    writer
        .execute_batch(
            "PRAGMA journal_mode = WAL;
             CREATE TABLE t(v INTEGER);
             INSERT INTO t VALUES (42);",
        )
        .unwrap();
    let ck: (i64, i64, i64) = writer
        .query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |r| {
            Ok((r.get(0)?, r.get(1)?, r.get(2)?))
        })
        .unwrap();
    assert_eq!(ck, (0, 0, 0));
    assert_eq!(std::fs::metadata(&x_wal).unwrap().len(), 0);
    std::fs::set_permissions(&x_db, std::fs::Permissions::from_mode(0o644)).unwrap();
    std::fs::set_permissions(&x_wal, std::fs::Permissions::from_mode(0o444)).unwrap();
    let wal_meta_before = std::fs::metadata(&x_wal).unwrap();
    assert_eq!(wal_meta_before.mode() & 0o777, 0o444);

    #[cfg(target_os = "linux")]
    let w_wal_mode = LinuxDirWatcher::with_mask(
        &db_dir,
        libc::IN_CREATE
            | libc::IN_MODIFY
            | libc::IN_DELETE
            | libc::IN_MOVED_FROM
            | libc::IN_MOVED_TO
            | libc::IN_ATTRIB
            | libc::IN_CLOSE_WRITE,
    );
    {
        let mut reader = open_readonly_source_db(&x_db).unwrap();
        let tx = reader.transaction().unwrap();
        let val: i64 = tx.query_row("SELECT v FROM t", [], |r| r.get(0)).unwrap();
        assert_eq!(val, 42);
    }
    let wal_meta_after = std::fs::metadata(&x_wal).unwrap();
    assert_eq!(
        wal_meta_after.mode() & 0o777,
        0o444,
        "0 字节 0444 WAL 不得被 fchmod 改为 0644"
    );
    assert_eq!(
        (wal_meta_before.ctime(), wal_meta_before.ctime_nsec()),
        (wal_meta_after.ctime(), wal_meta_after.ctime_nsec()),
        "0 字节 0444 WAL ctime 不得变化"
    );
    #[cfg(target_os = "linux")]
    {
        let evs = w_wal_mode.drain();
        assert!(
            evs.is_empty(),
            "读取 0 字节 0444 WAL 不得触发 IN_ATTRIB 或任何目录写事件：{evs:?}"
        );
    }
    drop(writer);

    // 2) 停机快照中主库 0644 + 0 字节 0444 SHM + 0 字节 0444 WAL：
    //    同样不得触发 unixOpenSharedMemory/robust_open 的 fchmod 改写 SHM mode/ctime。
    std::fs::write(&x_wal, b"").unwrap();
    std::fs::write(&x_shm, b"").unwrap();
    std::fs::set_permissions(&x_db, std::fs::Permissions::from_mode(0o644)).unwrap();
    std::fs::set_permissions(&x_wal, std::fs::Permissions::from_mode(0o444)).unwrap();
    std::fs::set_permissions(&x_shm, std::fs::Permissions::from_mode(0o444)).unwrap();
    let shm_meta_before = std::fs::metadata(&x_shm).unwrap();
    let wal2_meta_before = std::fs::metadata(&x_wal).unwrap();
    assert_eq!(shm_meta_before.len(), 0);
    assert_eq!(shm_meta_before.mode() & 0o777, 0o444);

    #[cfg(target_os = "linux")]
    let w_shm_mode = LinuxDirWatcher::with_mask(
        &db_dir,
        libc::IN_CREATE
            | libc::IN_MODIFY
            | libc::IN_DELETE
            | libc::IN_MOVED_FROM
            | libc::IN_MOVED_TO
            | libc::IN_ATTRIB
            | libc::IN_CLOSE_WRITE,
    );
    {
        let mut reader = open_readonly_source_db(&x_db).unwrap();
        let tx = reader.transaction().unwrap();
        let val: i64 = tx.query_row("SELECT v FROM t", [], |r| r.get(0)).unwrap();
        assert_eq!(val, 42);
    }
    let shm_meta_after = std::fs::metadata(&x_shm).unwrap();
    let wal2_meta_after = std::fs::metadata(&x_wal).unwrap();
    assert_eq!(
        shm_meta_after.mode() & 0o777,
        0o444,
        "0 字节 0444 SHM 不得被 fchmod 改为 0644"
    );
    assert_eq!(
        (shm_meta_before.ctime(), shm_meta_before.ctime_nsec()),
        (shm_meta_after.ctime(), shm_meta_after.ctime_nsec()),
        "0 字节 0444 SHM ctime 不得变化"
    );
    assert_eq!(wal2_meta_after.mode() & 0o777, 0o444);
    assert_eq!(
        (wal2_meta_before.ctime(), wal2_meta_before.ctime_nsec()),
        (wal2_meta_after.ctime(), wal2_meta_after.ctime_nsec())
    );
    #[cfg(target_os = "linux")]
    {
        let evs = w_shm_mode.drain();
        assert!(
            evs.is_empty(),
            "读取 0 字节 0444 SHM/WAL 不得触发 IN_ATTRIB 或任何目录写事件：{evs:?}"
        );
    }

    // 恢复权限以便 tempdir 清理。
    std::fs::set_permissions(&x_wal, std::fs::Permissions::from_mode(0o644)).unwrap();
    std::fs::set_permissions(&x_shm, std::fs::Permissions::from_mode(0o644)).unwrap();
}

#[test]
fn readonly_source_vfs_clean_close_wal_safety_and_same_process_shm_lock_ownership() {
    use crate::history_simulation::intake::open_readonly_source_db;
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;
    use std::os::unix::fs::PermissionsExt;

    // 外部子进程 F_GETLK 探测指定文件 byte 128 (UNIX_SHM_DMS) 的锁类型：
    // 只有跨进程探测才能看到父进程在 -shm 上持有的 POSIX F_RDLCK。
    fn probe_external_dms_lock(shm: &Path) -> libc::c_short {
        let cpath = CString::new(shm.as_os_str().as_bytes()).unwrap();
        let mut pipefd = [-1i32; 2];
        assert_eq!(unsafe { libc::pipe(pipefd.as_mut_ptr()) }, 0);
        let pid = unsafe { libc::fork() };
        assert!(pid >= 0, "fork failed");
        if pid == 0 {
            unsafe {
                libc::close(pipefd[0]);
                let fd = libc::open(cpath.as_ptr(), libc::O_RDONLY | libc::O_CLOEXEC);
                let mut res: i32 = -1;
                if fd >= 0 {
                    let mut fl: libc::flock = std::mem::zeroed();
                    fl.l_type = libc::F_WRLCK as libc::c_short;
                    fl.l_whence = libc::SEEK_SET as libc::c_short;
                    fl.l_start = 128;
                    fl.l_len = 1;
                    if libc::fcntl(fd, libc::F_GETLK, &mut fl) == 0 {
                        res = fl.l_type as i32;
                    }
                    libc::close(fd);
                }
                let bytes = res.to_ne_bytes();
                let _ = libc::write(pipefd[1], bytes.as_ptr().cast(), bytes.len());
                libc::close(pipefd[1]);
                libc::_exit(0);
            }
        }
        unsafe {
            libc::close(pipefd[1]);
            let mut buf = [0u8; 4];
            let n = libc::read(pipefd[0], buf.as_mut_ptr().cast(), buf.len());
            libc::close(pipefd[0]);
            let mut status = 0i32;
            libc::waitpid(pid, &mut status, 0);
            assert_eq!(n, 4, "failed to read child F_GETLK probe");
            i32::from_ne_bytes(buf) as libc::c_short
        }
    }

    let dir = tempfile::tempdir().unwrap();
    let db_dir = dir.path().join("x-r9");
    std::fs::create_dir_all(&db_dir).unwrap();
    let x_db = db_dir.join("x.db");
    let x_wal = append_suffix(&x_db, "-wal");
    let x_shm = append_suffix(&x_db, "-shm");

    // 1) 同进程 POSIX SHM 锁归属：默认 unix VFS 写者持有 -shm DMS 锁，
    //    同进程 open_readonly_source_db 读取并关闭后，写者外部可见的 DMS F_RDLCK 必须保持不变。
    let writer = rusqlite::Connection::open(&x_db).unwrap();
    writer
        .execute_batch(
            "PRAGMA journal_mode = WAL;
             PRAGMA wal_autocheckpoint = 0;
             CREATE TABLE t(v INTEGER);
             INSERT INTO t VALUES (1);",
        )
        .unwrap();
    assert!(x_wal.exists() && x_shm.exists());
    assert_eq!(
        probe_external_dms_lock(&x_shm),
        libc::F_RDLCK as libc::c_short,
        "写者建库后外部 F_GETLK 应见 DMS=F_RDLCK"
    );

    {
        let mut reader = open_readonly_source_db(&x_db).unwrap();
        let tx = reader.transaction().unwrap();
        let v: i64 = tx
            .query_row("SELECT sum(v) FROM t", [], |r| r.get(0))
            .unwrap();
        assert_eq!(v, 1);
    }
    assert_eq!(
        probe_external_dms_lock(&x_shm),
        libc::F_RDLCK as libc::c_short,
        "关闭同进程只读连接后绝不得误释写者的 -shm POSIX DMS 锁"
    );

    // 写者追加未 checkpoint 行，同进程只读连接必须读出最新 WAL 行且关闭后仍不丢写者 DMS 锁。
    writer.execute("INSERT INTO t VALUES (2)", []).unwrap();
    {
        let mut reader = open_readonly_source_db(&x_db).unwrap();
        let tx = reader.transaction().unwrap();
        let v: i64 = tx
            .query_row("SELECT sum(v) FROM t", [], |r| r.get(0))
            .unwrap();
        assert_eq!(v, 3);
    }
    assert_eq!(
        probe_external_dms_lock(&x_shm),
        libc::F_RDLCK as libc::c_short,
        "二次关闭同进程只读连接后写者 DMS 锁仍须完好"
    );

    // 2) 停机遗留未 checkpoint WAL 快照：必须读出 WAL 中的最新行（+40 => 43），绝不回落陈旧主库。
    writer.execute("INSERT INTO t VALUES (40)", []).unwrap();
    let stopped_dir = dir.path().join("x-stopped-wal");
    std::fs::create_dir_all(&stopped_dir).unwrap();
    let s_db = stopped_dir.join("x.db");
    let s_wal = append_suffix(&s_db, "-wal");
    let s_shm = append_suffix(&s_db, "-shm");
    std::fs::copy(&x_db, &s_db).unwrap();
    std::fs::copy(&x_wal, &s_wal).unwrap();
    std::fs::copy(&x_shm, &s_shm).unwrap();
    let before_stopped = dir_file_digests(&stopped_dir);
    #[cfg(target_os = "linux")]
    let w_stopped = LinuxDirWatcher::with_mask(
        &stopped_dir,
        libc::IN_CREATE
            | libc::IN_MODIFY
            | libc::IN_DELETE
            | libc::IN_MOVED_FROM
            | libc::IN_MOVED_TO
            | libc::IN_ATTRIB
            | libc::IN_CLOSE_WRITE,
    );
    {
        let mut reader = open_readonly_source_db(&s_db).unwrap();
        let tx = reader.transaction().unwrap();
        let v: i64 = tx
            .query_row("SELECT sum(v) FROM t", [], |r| r.get(0))
            .unwrap();
        assert_eq!(v, 43, "停机遗留 WAL 须完整读出未 checkpoint 最新行");
    }
    #[cfg(target_os = "linux")]
    assert!(w_stopped.drain().is_empty(), "停机 WAL 只读不得产生写事件");
    assert_eq!(before_stopped, dir_file_digests(&stopped_dir));

    // 3) 有 WAL 但缺 SHM：必须显式拒绝，绝不可跳过 WAL 读陈旧主库，且不得建 SHM。
    std::fs::remove_file(&s_shm).unwrap();
    let before_no_shm = dir_file_digests(&stopped_dir);
    {
        let mut reader = open_readonly_source_db(&s_db).unwrap();
        let tx = reader.transaction().unwrap();
        assert!(
            tx.query_row("SELECT sum(v) FROM t", [], |r| r.get::<_, i64>(0))
                .is_err(),
            "存在 -wal 但缺 -shm 时必须拒绝而非跳过 WAL"
        );
    }
    assert!(!s_shm.exists(), "拒绝时绝不得创建 -shm");
    assert_eq!(before_no_shm, dir_file_digests(&stopped_dir));

    // 4) 不可读 WAL（0000，非 root）与符号链接 WAL：必须显式拒绝，绝不可回落双缺主库路径。
    if unsafe { libc::geteuid() } != 0 {
        std::fs::set_permissions(&s_wal, std::fs::Permissions::from_mode(0o000)).unwrap();
        let mut reader = open_readonly_source_db(&s_db).unwrap();
        let tx = reader.transaction().unwrap();
        assert!(
            tx.query_row("SELECT sum(v) FROM t", [], |r| r.get::<_, i64>(0))
                .is_err(),
            "不可读 -wal 必须显式拒绝，不得视作正常闭库"
        );
        drop(tx);
        drop(reader);
        std::fs::set_permissions(&s_wal, std::fs::Permissions::from_mode(0o644)).unwrap();
    }
    let symlink_target = stopped_dir.join("real.wal");
    std::fs::rename(&s_wal, &symlink_target).unwrap();
    std::os::unix::fs::symlink(&symlink_target, &s_wal).unwrap();
    {
        let mut reader = open_readonly_source_db(&s_db).unwrap();
        let tx = reader.transaction().unwrap();
        assert!(
            tx.query_row("SELECT sum(v) FROM t", [], |r| r.get::<_, i64>(0))
                .is_err(),
            "符号链接 -wal 必须显式拒绝"
        );
    }
    std::fs::remove_file(&s_wal).unwrap();

    // 5) 写者正常关闭（checkpoint 并删 -wal/-shm）后：
    //    5a) 只读目录（chmod 555 + chmod 444）下双缺 WAL/SHM 必须成功读出 43 且零建文件；
    //    5b) 若残留孤立 -shm（缺 -wal），必须显式拒绝。
    drop(writer);
    assert!(!x_wal.exists() && !x_shm.exists());
    let hdr = &std::fs::read(&x_db).unwrap()[18..20];
    assert_eq!(hdr, &[2, 2], "正常闭库后主库头应保持 WAL [2,2]");
    if unsafe { libc::geteuid() } != 0 {
        std::fs::set_permissions(&x_db, std::fs::Permissions::from_mode(0o444)).unwrap();
        std::fs::set_permissions(&db_dir, std::fs::Permissions::from_mode(0o555)).unwrap();
        let mut reader = open_readonly_source_db(&x_db).unwrap();
        let tx = reader.transaction().unwrap();
        let v: i64 = tx
            .query_row("SELECT sum(v) FROM t", [], |r| r.get(0))
            .unwrap();
        assert_eq!(v, 43, "物理只读目录下正常闭库 WAL DB 须成功读出 43");
        drop(tx);
        drop(reader);
        assert!(!x_wal.exists() && !x_shm.exists());
        std::fs::set_permissions(&db_dir, std::fs::Permissions::from_mode(0o755)).unwrap();
        std::fs::set_permissions(&x_db, std::fs::Permissions::from_mode(0o644)).unwrap();
    }

    // 孤立 -shm（无 -wal）必须拒绝。
    std::fs::write(&x_shm, b"").unwrap();
    {
        let mut reader = open_readonly_source_db(&x_db).unwrap();
        let tx = reader.transaction().unwrap();
        assert!(
            tx.query_row("SELECT sum(v) FROM t", [], |r| r.get::<_, i64>(0))
                .is_err(),
            "孤立 -shm（无 -wal）必须显式拒绝"
        );
    }
    assert!(!x_wal.exists(), "孤立 -shm 拒绝时不得创建 -wal");
    std::fs::remove_file(&x_shm).unwrap();
}
