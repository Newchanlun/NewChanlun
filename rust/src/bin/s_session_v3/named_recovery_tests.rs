// S 本体的进程夹具：真实 Driver 在子进程处理输入，不改夹具库的 epoch 或业务行。
use super::{tests::Fixture, *};
use crate::v3::{
    admission::{Lock, WriterScope},
    admission_anchor::test_prepare,
    admission_provider::sidecar,
    named_recovery::{self, Action, FrozenConfig, Request, TestTransition},
};
use std::{
    io::{BufRead, BufReader, Write},
    os::unix::process::ExitStatusExt,
    process::{Child, Command, Stdio},
    sync::mpsc,
    time::Duration,
};

fn declaration() -> newchan_rust::structure_source::Declaration {
    newchan_rust::structure_source::Declaration::parse(
        &json!({"category":"TestOnlyStructure","namespaces":["testonly.ohlc"]}),
    )
    .unwrap()
}

fn fixture() -> Fixture {
    let clock = json!({
        "schema_revision":"s-clock-plan/1","clock_plan_id":"s-named-recovery","origin_utc":"2026-09-18T00:00:00Z","unit":"ns","events":{
            "input-1":{"accept_ns":"10","attempts":[{"begin_ns":"11","commit_ns":"12"}]},
            "input-2":{"accept_ns":"20","attempts":[{"begin_ns":"21","commit_ns":"22"},{"begin_ns":"24","commit_ns":"25"}]},
            "recover-1":{"recover_ns":"23"},"recover-2":{"recover_ns":"33"}
        }
    });
    Fixture::with_clock_declared(clock, Some(&declaration()))
}

fn config(f: &Fixture) -> FrozenConfig {
    let value: Value = strict_json(&std::fs::read(&f.profile).unwrap()).unwrap();
    FrozenConfig {
        profile_hash: sha256_hex(canonical_json(&value).as_bytes()),
        source: declaration(),
        clock: f.clock.clone(),
    }
}

fn run(f: &Fixture, action: Action, request: Option<&Request>) -> Result<Value, String> {
    let admission = test_prepare(&f.db);
    let mut result = None;
    // 命令本体会消费真实 Job、固定源并显式关闭；只拦截最终 stdout。
    named_recovery::run(&f.db, admission, action, config(f), request, |body, _| {
        result = Some(body.clone());
        Ok(())
    })?;
    Ok(result.expect("成功时必须发出一个完整结果"))
}

fn request_document(snapshot: &Value, id: &str, event: &str) -> Value {
    json!({"schema_revision":"s-recovery/1","recovery_id":id,"domain_id":"S",
          "session_id":snapshot["session_id"],"session_generation":snapshot["session_generation"],
          "from_epoch":snapshot["from_epoch"],"cut":snapshot["cut"],"config":snapshot["config"],
          "clock_event_id":event})
}
fn request(value: &Value) -> Request {
    Request::parse(canonical_json(value).as_bytes()).unwrap()
}
fn publish_initial(f: &Fixture) {
    let mut s = f.open("1").unwrap();
    let result = s.handle(Fixture::ingest(1)).unwrap();
    assert_eq!(result["kind"], "Committed", "{result}");
}

struct CrashChild(Child);
impl Drop for CrashChild {
    fn drop(&mut self) {
        if self.0.try_wait().ok().flatten().is_none() {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}
fn crash(f: &Fixture, phase: &str, epoch: &str) {
    let mut child = CrashChild(
        Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "v3::driver::named_recovery_tests::named_recovery_crash_child",
                "--nocapture",
            ])
            .env("S_NAMED_CRASH_DB", &f.db)
            .env("S_NAMED_CRASH_PROFILE", &f.profile)
            .env("S_NAMED_CRASH_PHASE", phase)
            .env("S_NAMED_CRASH_EPOCH", epoch)
            .stdout(Stdio::piped())
            .spawn()
            .unwrap(),
    );
    let stdout = child.0.stdout.take().unwrap();
    let (notify, wait) = mpsc::sync_channel(1);
    let output = std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if line == "S_RECOVERY_CRASH_CUT_DURABLE" {
                notify.send(()).unwrap();
                return;
            }
        }
    });
    let reached = wait.recv_timeout(Duration::from_secs(45));
    child.0.kill().unwrap();
    assert_eq!(child.0.wait().unwrap().signal(), Some(9));
    output.join().unwrap();
    reached.expect("子进程必须在强杀前跨过持久边界");
}

#[test]
fn named_recovery_crash_child() {
    let Some(db) = std::env::var_os("S_NAMED_CRASH_DB").map(PathBuf::from) else {
        return;
    };
    let profile = PathBuf::from(std::env::var_os("S_NAMED_CRASH_PROFILE").unwrap());
    let clock = v2::ClockPlan::load(&db.with_file_name("clock.json")).unwrap();
    let epoch = std::env::var("S_NAMED_CRASH_EPOCH").unwrap();
    let phase = std::env::var("S_NAMED_CRASH_PHASE").unwrap();
    let mut s = Driver::open(&db, &profile, &epoch, clock, test_prepare(&db).into()).unwrap();
    let held = match phase.as_str() {
        "before" => {
            s.stop_after = Some("begin");
            assert!(s
                .handle(Fixture::ingest(2))
                .unwrap_err()
                .contains("stop_after_begin"));
            None
        }
        "after" => {
            assert_eq!(s.handle(Fixture::ingest(2)).unwrap()["kind"], "Committed");
            None
        }
        "zero" => {
            let conn = Connection::open(&db).unwrap();
            // 只在夹具读数点让 SQLite 自己生成 0 字节 WAL + SHM；不按名删除或编辑侧件。
            let status: (i32, i32, i32) = conn
                .query_row("PRAGMA main.wal_checkpoint(TRUNCATE)", [], |r| {
                    Ok((r.get(0)?, r.get(1)?, r.get(2)?))
                })
                .unwrap();
            assert_eq!(status, (0, 0, 0));
            assert_eq!(std::fs::metadata(sidecar(&db, "-wal")).unwrap().len(), 0);
            Some(conn)
        }
        _ => panic!("未知夹具切面"),
    };
    println!("S_RECOVERY_CRASH_CUT_DURABLE");
    std::io::stdout().flush().unwrap();
    loop {
        std::hint::black_box((&s, &held));
        std::thread::park();
    }
}

fn media_bytes(f: &Fixture) -> Vec<Option<Vec<u8>>> {
    ["", "-wal", "-shm", "-journal", ".control-owner.json"]
        .into_iter()
        .map(|suffix| match std::fs::read(sidecar(&f.db, suffix)) {
            Ok(value) => Some(value),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => None,
            Err(e) => panic!("{e}"),
        })
        .collect()
}

fn dirty_case(phase: &str, generation: &str, unresolved: bool, wal_is_empty: bool) {
    let f = fixture();
    publish_initial(&f);
    crash(&f, phase, "1");
    let before = media_bytes(&f);
    assert_eq!(before[1].as_ref().unwrap().is_empty(), wal_is_empty);
    assert!(!before[2].as_ref().unwrap().is_empty());
    let ordinary = f.open("1").err().expect("R4 必须拒绝脏介质");
    assert!(
        ordinary.contains("UnsupportedWalShmJournalCombination"),
        "{ordinary}"
    );
    let snapshot = run(&f, Action::Inspect, None).unwrap();
    assert_eq!(snapshot["cut"]["generation"], generation);
    assert_eq!(snapshot["unresolved_begin"], unresolved);
    assert_eq!(snapshot["has_shm"], true);
    let raw = request_document(&snapshot, "first", "recover-1");
    let request = request(&raw);
    let error = run(&f, Action::Current, Some(&request)).unwrap_err();
    assert!(
        error.contains("UnsupportedWalShmJournalCombination"),
        "{error}"
    );
    let error = run(&f, Action::Recover, Some(&request)).unwrap_err();
    assert!(
        error.contains("AdmissionNamedRecoveryContractUnregistered"),
        "{error}"
    );
    assert_eq!(before, media_bytes(&f), "只读审计和拒绝不得更改任一原件");
}

#[test]
fn tb07_s_named_recovery_observe_before_commit() {
    dirty_case("before", "1", true, false);
}
#[test]
fn tb07_s_named_recovery_observe_after_commit_before_reply() {
    dirty_case("after", "2", false, false);
}
#[test]
fn tb07_s_named_recovery_observe_zero_wal_present() {
    dirty_case("zero", "1", false, true);
}

fn commit_receipt_fixture(f: &Fixture, request: &Request) -> Result<Value, String> {
    // 双锁、R4 和原 Recover 事务不替换；仅在隔离测试使用已知普通连接，
    // 此夹具只认证事务，不把它当成 EXCLUSIVE 写者或受控 checkpoint 证据。
    let scope = WriterScope::admit_named(&f.db, test_prepare(&f.db))?;
    let _guard = scope.enter()?;
    let conn = crate::v3::audit_owner::AuditConnection::open(&f.db)?;
    conn.recover_named_transaction_for_test(TestTransition {
        request,
        config: &config(f),
    })
}

#[test]
fn tb07_s_named_recovery_receipt_lost_reply_and_switch() {
    let f = fixture();
    publish_initial(&f);
    let snap = run(&f, Action::Inspect, None).unwrap();
    let mut raw = request_document(&snap, "first", "recover-1");
    let first = request(&raw);
    assert!(run(&f, Action::Query, Some(&first))
        .unwrap_err()
        .contains("MissingDependency"));
    let one = commit_receipt_fixture(&f, &first).unwrap();
    // 丢弃首次返回路径；之后每次都关闭并重新打开已钉住的只读源。
    let original = run(&f, Action::Query, Some(&first)).unwrap();
    assert_eq!(original, one);
    assert_eq!(original["writer_epoch"], "2");
    assert_eq!(original["recover_ns"], "23");
    assert_eq!(run(&f, Action::Current, Some(&first)).unwrap(), original);
    assert_eq!(run(&f, Action::Recover, Some(&first)).unwrap(), original);

    raw["clock_event_id"] = json!("recover-2");
    assert!(run(&f, Action::Recover, Some(&request(&raw)))
        .unwrap_err()
        .contains("IdentityConflict"));
    raw["recovery_id"] = json!("second");
    assert!(run(&f, Action::Recover, Some(&request(&raw)))
        .unwrap_err()
        .contains("StaleWriter"));
    raw["from_epoch"] = json!("2");
    assert_eq!(
        commit_receipt_fixture(&f, &request(&raw)).unwrap()["writer_epoch"],
        "3"
    );
    assert_eq!(run(&f, Action::Query, Some(&first)).unwrap(), original);
    assert!(run(&f, Action::Current, Some(&first))
        .unwrap_err()
        .contains("StaleWriter"));

    crash(&f, "zero", "3");
    let before = media_bytes(&f);
    assert_eq!(run(&f, Action::Query, Some(&first)).unwrap(), original);
    assert!(run(&f, Action::Recover, Some(&first))
        .unwrap_err()
        .contains("SRecoveryMediumUnproven"));
    assert_eq!(before, media_bytes(&f));
}

#[test]
fn tb07_s_named_recovery_observe_media_refusals() {
    let f = fixture();
    publish_initial(&f);
    let before = media_bytes(&f);
    let writer = Lock::acquire_existing(&f.db, ".writer.lock").unwrap();
    assert!(run(&f, Action::Inspect, None)
        .unwrap_err()
        .contains("StaleWriter"));
    drop(writer);
    let maintenance = Lock::acquire_existing(&f.db, ".maintenance.lock").unwrap();
    assert!(run(&f, Action::Inspect, None)
        .unwrap_err()
        .contains("MaintenanceBusy"));
    drop(maintenance);
    assert_eq!(before, media_bytes(&f));

    let shm = sidecar(&f.db, "-shm");
    assert!(before[1].is_none() && before[2].is_none());
    // 孤立 SHM 负控不删除 WAL：在无侧件的新状态放入孤立文件。
    std::fs::write(&shm, [0u8; 32]).unwrap();
    let residue = media_bytes(&f);
    assert!(run(&f, Action::Inspect, None)
        .unwrap_err()
        .contains("SRecoveryMediumUnproven"));
    assert_eq!(residue, media_bytes(&f));
    // WAL 确实存在但字节不是合法头；不可退到旧主库。
    std::fs::write(sidecar(&f.db, "-wal"), [1u8; 32]).unwrap();
    let corrupt = media_bytes(&f);
    assert!(run(&f, Action::Inspect, None)
        .unwrap_err()
        .contains("SRecoveryMediumUnproven"));
    assert_eq!(corrupt, media_bytes(&f));
}

#[test]
fn tb07_s_named_recovery_request_is_closed_and_canonical() {
    let f = fixture();
    publish_initial(&f);
    let before = media_bytes(&f);
    let snap = run(&f, Action::Inspect, None).unwrap();
    let mut raw = request_document(&snap, "first", "recover-1");
    let canonical = canonical_json(&raw);
    assert!(Request::parse(canonical.as_bytes()).is_ok());
    assert!(Request::parse(format!("{canonical}\n").as_bytes()).is_err());
    assert!(
        Request::parse(format!("{{\"domain_id\":\"S\",{}", &canonical[1..]).as_bytes()).is_err()
    );
    assert!(Request::parse(&[b' '; 4097]).is_err());
    raw["from_epoch"] = json!("01");
    assert!(Request::parse(canonical_json(&raw).as_bytes()).is_err());
    raw["from_epoch"] = json!("1");
    raw["cut"]["extra"] = json!("invalid");
    assert!(Request::parse(canonical_json(&raw).as_bytes()).is_err());
    assert_eq!(before, media_bytes(&f));
}

#[test]
fn tb07_s_named_recovery_handoff_refuses_epoch_changed_after_current() {
    let f = fixture();
    publish_initial(&f);
    let cut = run(&f, Action::Inspect, None).unwrap();
    let raw = request_document(&cut, "first", "recover-1");
    let first = request(&raw);
    commit_receipt_fixture(&f, &first).unwrap();
    assert_eq!(
        run(&f, Action::Current, Some(&first)).unwrap()["writer_epoch"],
        "2"
    );

    let cut = run(&f, Action::Inspect, None).unwrap();
    let second = request(&request_document(&cut, "second", "recover-2"));
    commit_receipt_fixture(&f, &second).unwrap();
    let original = media_bytes(&f);

    let owner_path = sidecar(&f.db, ".control-owner.json");
    let owner = strict_json(&std::fs::read(owner_path).unwrap()).unwrap();
    let request_file = f.path.join("s-recovery.json");
    std::fs::write(&request_file, canonical_json(&raw)).unwrap();
    let source_file = f.path.join("source.json");
    std::fs::write(&source_file, declaration().canonical()).unwrap();
    let resources = f.path.join("resources.json");
    let values: serde_json::Map<String, Value> = crate::v3::writer_cli::GATE_FIELDS
        .into_iter()
        .map(|field| (field.to_owned(), json!("1048576")))
        .collect();
    std::fs::write(
        &resources,
        serde_json::to_vec(&json!({
            "schema_revision":crate::v3::writer_cli::RESOURCES_REVISION,"s_resources":values
        }))
        .unwrap(),
    )
    .unwrap();
    let socket = f.path.join("s.sock");
    let flag = |path: &Path| path.to_str().unwrap().to_string();
    let args = vec![
        "s_structure_session".into(),
        "serve".into(),
        "--protocol-revision".into(),
        "s-session/3".into(),
        "--db".into(),
        flag(&f.db),
        "--admission-job-limits".into(),
        owner["admission"]["path"].as_str().unwrap().into(),
        "--profile".into(),
        flag(&f.profile),
        "--clock-plan".into(),
        flag(&f.path.join("clock.json")),
        "--writer-epoch".into(),
        "2".into(),
        "--structure-source".into(),
        flag(&source_file),
        "--s-recovery-request".into(),
        flag(&request_file),
        "--socket".into(),
        flag(&socket),
        "--resource-config".into(),
        flag(&resources),
    ];
    let error = crate::v3::writer_cli::run_fixture(&args)
        .err()
        .expect("旧回执不得开服");
    assert!(error.contains("StaleWriter"), "{error}");
    assert!(!socket.exists());
    assert_eq!(original, media_bytes(&f));
    // 同一健康库未带恢复标志的旧入口仍能按当前配置的代打开。
    assert_eq!(f.open("3").unwrap().identity().unwrap().2, "3");
}

#[cfg(feature = "s_incremental")]
#[test]
fn tb07_s_named_recovery_transaction_failure_rolls_back_receipt_and_epoch() {
    let f = fixture();
    publish_initial(&f);
    let cut = run(&f, Action::Inspect, None).unwrap();
    let named = request(&request_document(&cut, "first", "recover-1"));
    let before = media_bytes(&f);
    {
        let scope = WriterScope::admit_named(&f.db, test_prepare(&f.db)).unwrap();
        let _guard = scope.enter().unwrap();
        let owner = crate::v3::audit_owner::AuditConnection::open(&f.db).unwrap();
        owner.set_recover_after_write_for_test(|tx| {
            assert_eq!(
                crate::meta_get_opt(tx, "writer_epoch")?.as_deref(),
                Some("2")
            );
            assert!(crate::meta_get_opt(tx, "s-recovery/1:first")?.is_some());
            Err("TestOnly：具名恢复写后失败".into())
        });
        let err = owner
            .recover_named_transaction_for_test(TestTransition {
                request: &named,
                config: &config(&f),
            })
            .unwrap_err();
        assert!(err.contains("具名恢复写后失败"), "{err}");
    }
    assert_eq!(before, media_bytes(&f));
    assert_eq!(run(&f, Action::Inspect, None).unwrap(), cut);
    assert!(run(&f, Action::Query, Some(&named))
        .unwrap_err()
        .contains("MissingDependency"));
}
