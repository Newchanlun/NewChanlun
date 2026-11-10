//! #1407 C2 第 1、2 项的集成锁：E 经正式入口放行的命令，经共同信封查询真 E，被 X 的 AcceptExact 接纳，
//! 随后受控 S 条件执行、X 占有调用。E 与 X 都是生产 serve 循环；S 仍是受控夹具（真 S producer 归 TB04-D/E）。
//! 本批 E 仍是 TestOnly 时钟（alpha 放行读数 162）；E 改读 logical-bar/1 归 C2 第 4 项。在那之前，X 先走 162 根空 bar
//! 让接纳前沿追上放行读数，这里只锁条件清单与信封两处断点，不作时钟域证据。
use super::*;
use crate::history_simulation::runtime::Profile as XProfile;
use rusqlite::types::ValueRef;
use std::io::{BufRead, BufReader, Write};
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
/// 就绪是「在 listen」，不是「文件存在」：bind 先建出路径，listen 之前的连接会被拒（Linux /proc/net/unix）。
fn listening(path: &Path) -> bool {
    let target = path.to_str().unwrap();
    std::fs::read_to_string("/proc/net/unix")
        .unwrap()
        .lines()
        .skip(1)
        .any(|row| {
            let f: Vec<&str> = row.split_whitespace().collect();
            f.len() >= 8
                && f[7..].join(" ") == target
                && u32::from_str_radix(f[3], 16).is_ok_and(|flags| flags & 0x10000 != 0)
        })
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
