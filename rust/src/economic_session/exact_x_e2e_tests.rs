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

    entered_rx
        .recv_timeout(std::time::Duration::from_secs(5))
        .expect("E 应进入 before_commit 暂停点");

    // E 正持 FrontierGuard 处于核对后、COMMIT 前窗口，此时并发推进旧挂单的 b0+1。
    let xs_for_adv = xs.clone();
    let (adv_tx, adv_rx) = std::sync::mpsc::channel::<Value>();
    let x_thread = std::thread::spawn(move || {
        let reply = x(&xs_for_adv, "AdvanceBar", bar(RELEASE_NS + 1, json!([])));
        let _ = adv_tx.send(reply);
    });

    // 观察窗口：150ms 内 X 的 AdvanceBar(b0+1) 必须被前沿顺序锁阻挡，不能在 E COMMIT 前落盘。
    std::thread::sleep(std::time::Duration::from_millis(150));
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
