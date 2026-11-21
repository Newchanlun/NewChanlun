// S 本体的进程夹具：真实 Driver 在子进程处理输入，不改夹具库的 epoch 或业务行。
use super::{tests::Fixture, *};
use crate::v3::{
    admission::{Lock, WriterScope},
    admission_anchor::{
        issuance::Contract, load_named_for_db, test_prepare, CommandAccounting, ControlEnv,
        NamedContract, PreparedAdmission,
    },
    admission_provider::sidecar,
    named_recovery::{self, Action, FrozenConfig, Request, TestTransition},
};
use std::{
    io::{BufRead, BufReader, Write},
    os::unix::{
        fs::{OpenOptionsExt, PermissionsExt},
        process::ExitStatusExt,
    },
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
    let f = Fixture::with_clock_declared(clock, Some(&declaration()));
    // 夹具显式使用合格部署权限，不继承 Boat 登录 shell 的组可写 umask。
    let chmod = |path: &Path, mode| {
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode)).unwrap();
    };
    chmod(&f.path, 0o700);
    chmod(&f.db, 0o600);
    chmod(&sidecar(&f.db, ".writer.lock"), 0o600);
    drop(test_prepare(&f.db));
    let limits = limits_path(&f);
    chmod(limits.parent().unwrap().parent().unwrap(), 0o700);
    f
}

const TEST_CONTRACT: &str = "s-admission-named-test/1";
const AWAITING_CONTRACT: &str = "s-admission-small/1-awaiting-measurement";

fn fixture_catalog(f: &Fixture) -> PathBuf {
    f.profile
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("catalog/signed-catalog.json")
}

fn limits_path(f: &Fixture) -> PathBuf {
    let owner = std::fs::read(sidecar(&f.db, ".control-owner.json")).unwrap();
    PathBuf::from(
        strict_json(&owner).unwrap()["admission"]["path"]
            .as_str()
            .unwrap(),
    )
}

fn test_registry(limits: &str) -> Contract<'_> {
    Contract::test_named_contract(TEST_CONTRACT, limits)
}

fn binding<'a>(registry: &'a Contract<'a>) -> NamedContract<'a> {
    NamedContract {
        version: TEST_CONTRACT,
        registry,
    }
}

fn prepare_named(
    f: &Fixture,
    registry: &Contract<'_>,
) -> Result<(PreparedAdmission, crate::v3::admission::DomainLocks), String> {
    load_named_for_db(
        &f.db,
        &limits_path(f),
        ControlEnv::capture(),
        binding(registry),
    )
}

fn named_scope(f: &Fixture, registry: &Contract<'_>) -> Result<WriterScope, String> {
    let (prepared, locks) = prepare_named(f, registry)?;
    WriterScope::admit_named(&f.db, prepared, locks)
}

fn config(f: &Fixture) -> FrozenConfig {
    let (catalog, _, _) = crate::v3::load_catalog_strict(&fixture_catalog(f)).unwrap();
    let value: Value = strict_json(&std::fs::read(&f.profile).unwrap()).unwrap();
    FrozenConfig {
        profile_hash: sha256_hex(canonical_json(&value).as_bytes()),
        catalog_hash: crate::v3::catalog_definition_hash(&catalog),
        source: declaration(),
        clock: f.clock.clone(),
    }
}

fn run(f: &Fixture, action: Action, request: Option<&Request>) -> Result<Value, String> {
    let limits = std::fs::read_to_string(limits_path(f)).unwrap();
    let registry = test_registry(&limits);
    let (admission, locks) = if action == Action::Query {
        (test_prepare(&f.db), None)
    } else {
        let (prepared, locks) = prepare_named(f, &registry)?;
        (prepared, Some(locks))
    };
    let mut result = None;
    // 命令本体会消费真实 Job、固定源并显式关闭；只拦截最终 stdout。
    named_recovery::run(
        &f.db,
        admission,
        action,
        config(f),
        request,
        locks,
        |body, _| {
            result = Some(body.clone());
            Ok(())
        },
    )?;
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
    let limits = std::fs::read_to_string(limits_path(f)).unwrap();
    let registry = test_registry(&limits);
    let scope = named_scope(f, &registry)?;
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

fn write_test_sidecar(path: &Path, bytes: &[u8]) {
    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .unwrap()
        .write_all(bytes)
        .unwrap();
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
    write_test_sidecar(&shm, &[0; 32]);
    let residue = media_bytes(&f);
    assert!(run(&f, Action::Inspect, None)
        .unwrap_err()
        .contains("SRecoveryMediumUnproven"));
    assert_eq!(residue, media_bytes(&f));
    // WAL 确实存在但字节不是合法头；不可退到旧主库。
    write_test_sidecar(&sidecar(&f.db, "-wal"), &[1; 32]);
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

    let cli = RecoveryCli::new(&f, &raw);
    let limits = std::fs::read_to_string(limits_path(&f)).unwrap();
    let registry = test_registry(&limits);
    let error =
        crate::v3::writer_cli::test_run_named_cli(&cli.serve("2", Some(TEST_CONTRACT)), &registry)
            .err()
            .expect("旧回执不得开服");
    assert!(error.contains("StaleWriter"), "{error}");
    assert!(!cli.socket.exists());
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
        let limits = std::fs::read_to_string(limits_path(&f)).unwrap();
        let registry = test_registry(&limits);
        let scope = named_scope(&f, &registry).unwrap();
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

struct RecoveryCli<'a> {
    fixture: &'a Fixture,
    catalog: PathBuf,
    request: PathBuf,
    source: PathBuf,
    socket: PathBuf,
    resources: PathBuf,
}

impl<'a> RecoveryCli<'a> {
    fn new(fixture: &'a Fixture, request: &Value) -> Self {
        let path = &fixture.path;
        let files = Self {
            fixture,
            catalog: path.join("manifest-catalog.json"),
            request: path.join("s-recovery.json"),
            source: path.join("source.json"),
            socket: path.join("s.sock"),
            resources: path.join("resources.json"),
        };
        std::fs::copy(fixture_catalog(fixture), &files.catalog).unwrap();
        std::fs::write(&files.request, canonical_json(request)).unwrap();
        std::fs::write(&files.source, declaration().canonical()).unwrap();
        let values: serde_json::Map<String, Value> = crate::v3::writer_cli::GATE_FIELDS
            .into_iter()
            .map(|field| (field.to_owned(), json!("1048576")))
            .collect();
        std::fs::write(
            &files.resources,
            canonical_json(&json!({
                "schema_revision":crate::v3::writer_cli::RESOURCES_REVISION,"s_resources":values
            })),
        )
        .unwrap();
        files
    }

    fn base_args(&self, action: &str) -> Vec<String> {
        let f = self.fixture;
        [
            "s_structure_session",
            action,
            "--protocol-revision",
            "s-session/3",
            "--db",
            f.db.to_str().unwrap(),
            "--admission-job-limits",
            limits_path(f).to_str().unwrap(),
            "--profile",
            f.profile.to_str().unwrap(),
            "--clock-plan",
            f.path.join("clock.json").to_str().unwrap(),
            "--structure-source",
            self.source.to_str().unwrap(),
        ]
        .map(str::to_owned)
        .to_vec()
    }

    fn named_args(&self, args: &mut Vec<String>, contract: Option<&str>, needs_request: bool) {
        args.extend(["--catalog", self.catalog.to_str().unwrap()].map(str::to_owned));
        if let Some(version) = contract {
            args.extend(["--contract-version", version].map(str::to_owned));
        }
        if needs_request {
            args.extend(
                ["--s-recovery-request", self.request.to_str().unwrap()].map(str::to_owned),
            );
        }
    }

    fn command(&self, action: &str, contract: Option<&str>) -> Vec<String> {
        let mut args = self.base_args(action);
        self.named_args(&mut args, contract, action != "inspect-recovery");
        args
    }

    fn serve(&self, epoch: &str, contract: Option<&str>) -> Vec<String> {
        let mut args = self.base_args("serve");
        args.extend(
            [
                "--writer-epoch",
                epoch,
                "--socket",
                self.socket.to_str().unwrap(),
                "--resource-config",
                self.resources.to_str().unwrap(),
            ]
            .map(str::to_owned),
        );
        if contract.is_some() {
            self.named_args(&mut args, contract, true);
        }
        args
    }
}

// 仅隔离夹具：原 inode 不变，重新绑定实际原件摘要（待实测原件不能由正式签发器发布）。
fn set_anchor_bytes(f: &Fixture, raw: &[u8]) -> u64 {
    let limits = limits_path(f);
    let binding = limits.with_file_name("binding.json");
    let owner = sidecar(&f.db, ".control-owner.json");
    let mut document = strict_json(&std::fs::read(&owner).unwrap()).unwrap();
    document["admission"]["sha256"] = json!(sha256_hex(raw));
    let binding_raw = canonical_json(&document["admission"]);
    let owner_raw = canonical_json(&document);
    std::fs::write(limits, raw).unwrap();
    std::fs::write(binding, &binding_raw).unwrap();
    std::fs::write(owner, &owner_raw).unwrap();
    (raw.len() + binding_raw.len() + owner_raw.len()) as u64
}

#[test]
fn tb07_s_named_recovery_authorizes_pinned_contract_before_payload() {
    let f = fixture();
    publish_initial(&f);
    let cut = run(&f, Action::Inspect, None).unwrap();
    let raw = request_document(&cut, "first", "recover-1");
    let cli = RecoveryCli::new(&f, &raw);
    let mut numeric = strict_json(&std::fs::read(limits_path(&f)).unwrap()).unwrap();
    numeric["max_total_wire_bytes"] = json!("122000");
    let numeric = canonical_json(&numeric);
    let pending = strict_json(include_bytes!(
        "../../../../s_session/contracts/admission-small-v1.json"
    ))
    .unwrap();
    let pending = canonical_json(&pending);
    let catalog = std::fs::read(&cli.catalog).unwrap();
    let mut padded = catalog.clone();
    padded.extend([b' '; 8192]);
    for (anchor, catalog, version, expected) in [
        (
            &numeric,
            &catalog,
            "retired",
            "AdmissionContractSupersededOrUnknown",
        ),
        (
            &numeric,
            &padded,
            "retired",
            "AdmissionContractSupersededOrUnknown",
        ),
        (
            &pending,
            &catalog,
            AWAITING_CONTRACT,
            "AdmissionContractAwaitingMeasurement",
        ),
    ] {
        let wire = set_anchor_bytes(&f, anchor.as_bytes());
        std::fs::write(&cli.catalog, catalog).unwrap();
        let before = media_bytes(&f);
        for args in [
            cli.command("inspect-recovery", Some(version)),
            cli.command("current-recovery", Some(version)),
            cli.command("recover-named", Some(version)),
            cli.serve("1", Some(version)),
        ] {
            let accounting = CommandAccounting::begin();
            let error = crate::run_with(&args).unwrap_err();
            assert_eq!(error, expected, "{}", args[1]);
            let receipt = accounting.report(&error, &mut std::io::sink());
            assert!(receipt.job.is_none());
            let prelude = receipt.prelude.unwrap();
            assert!(!prelude.budget_trusted);
            assert_eq!(prelude.wire_bytes, wire, "{}", args[1]);
        }
        assert!(!cli.socket.exists());
        assert_eq!(before, media_bytes(&f));
    }
}

#[test]
fn tb07_s_named_recovery_production_requires_original_anchor_contract() {
    let f = fixture();
    publish_initial(&f);
    let cut = run(&f, Action::Inspect, None).unwrap();
    let raw = request_document(&cut, "first", "recover-1");
    let first = request(&raw);
    commit_receipt_fixture(&f, &first).unwrap();
    let cli = RecoveryCli::new(&f, &raw);
    let limits = std::fs::read_to_string(limits_path(&f)).unwrap();
    let registry = test_registry(&limits);
    let before = media_bytes(&f);

    // 数值锚可正常加载且符合独立测试登记，不等于它的摘要已在真实构建获批。
    for (version, expected) in [
        (TEST_CONTRACT, "AdmissionContractSupersededOrUnknown"),
        (AWAITING_CONTRACT, "AdmissionContractUnapproved"),
    ] {
        for action in ["inspect-recovery", "current-recovery", "recover-named"] {
            let args = cli.command(action, Some(version));
            assert_eq!(crate::run_with(&args).unwrap_err(), expected, "{action}");
        }
        assert_eq!(
            crate::run_with(&cli.serve("2", Some(version))).unwrap_err(),
            expected
        );
        assert!(!cli.socket.exists());
    }

    // 同版本、不同有效额度：即便测试注册表可生效，也只能核准该锚原摘要。
    let mut changed = strict_json(limits.as_bytes()).unwrap();
    changed["max_total_requests"] = json!("999999");
    let other_limits = canonical_json(&changed);
    let other_registry = test_registry(&other_limits);
    let err = crate::v3::writer_cli::test_run_named_cli(
        &cli.command("current-recovery", Some(TEST_CONTRACT)),
        &other_registry,
    )
    .err()
    .unwrap();
    assert_eq!(err, "AdmissionContractUnapproved");

    for action in ["inspect-recovery", "current-recovery", "recover-named"] {
        crate::v3::writer_cli::test_run_named_cli(
            &cli.command(action, Some(TEST_CONTRACT)),
            &registry,
        )
        .unwrap();
    }
    let scope = named_scope(&f, &registry).unwrap();
    scope
        .verify_named_startup(&config(&f), &first, "2")
        .unwrap();
    drop(scope);
    // 不给写合同，历史查询仍经生产分派取得同一原件。
    crate::run_with(&cli.command("query-recovery", None)).unwrap();
    assert_eq!(before, media_bytes(&f));

    crash(&f, "zero", "2");
    let ordinary = crate::run_with(&cli.serve("2", None)).unwrap_err();
    assert!(
        ordinary.contains("UnsupportedWalShmJournalCombination"),
        "{ordinary}"
    );
}

#[test]
fn tb07_s_named_recovery_compares_callers_frozen_catalog() {
    let f = fixture();
    publish_initial(&f);
    let cut = run(&f, Action::Inspect, None).unwrap();
    let raw = request_document(&cut, "first", "recover-1");
    let first = request(&raw);
    let original = commit_receipt_fixture(&f, &first).unwrap();
    let cli = RecoveryCli::new(&f, &raw);
    let limits = std::fs::read_to_string(limits_path(&f)).unwrap();
    let registry = test_registry(&limits);
    let before = media_bytes(&f);
    let request_bytes = std::fs::read(&cli.request).unwrap();

    // 同一规范目录换空白仍成功，证明不是直接哈希文件原字节。
    let mut catalog = strict_json(&std::fs::read(&cli.catalog).unwrap()).unwrap();
    let pretty = serde_json::to_vec_pretty(&catalog).unwrap();
    let measured_wire = || {
        let accounting = CommandAccounting::begin();
        // 合同和目录有效；故意不给当前写者代，以便在 Job 内拒绝而不创建服务。
        let error = crate::v3::writer_cli::test_run_named_cli(
            &cli.serve("1", Some(TEST_CONTRACT)),
            &registry,
        )
        .err()
        .unwrap();
        assert_eq!(error, "StaleWriter：具名恢复当前回执与配置写者代不一致");
        let receipt = accounting.report(&error, &mut std::io::sink());
        assert!(receipt.job.is_some());
        let prelude = receipt.prelude.unwrap();
        assert!(prelude.budget_trusted);
        prelude.wire_bytes
    };
    std::fs::write(&cli.catalog, &pretty).unwrap();
    let wire = measured_wire();
    let mut padded = pretty;
    padded.extend([b' '; 513]);
    std::fs::write(&cli.catalog, padded).unwrap();
    // 同一原锚、同一规范目录，仅增加的非语义输入字节也进原前导账。
    assert_eq!(measured_wire(), wire + 513);
    for action in ["inspect-recovery", "current-recovery", "recover-named"] {
        crate::v3::writer_cli::test_run_named_cli(
            &cli.command(action, Some(TEST_CONTRACT)),
            &registry,
        )
        .unwrap();
    }
    crate::run_with(&cli.command("query-recovery", None)).unwrap();

    // 只变更 manifest 所指的目录内容；不动库、锚、请求或原回执。
    catalog["items"][0]["title"] = json!("目录冻结配置已变");
    std::fs::write(&cli.catalog, canonical_json(&catalog)).unwrap();
    let expected = "IdentityConflict：S恢复冻结 catalog_hash 与库不一致";
    for action in ["inspect-recovery", "current-recovery", "recover-named"] {
        let err = crate::v3::writer_cli::test_run_named_cli(
            &cli.command(action, Some(TEST_CONTRACT)),
            &registry,
        )
        .err()
        .unwrap();
        assert_eq!(err, expected, "{action}");
    }
    assert_eq!(
        crate::run_with(&cli.command("query-recovery", None)).unwrap_err(),
        expected
    );
    let err =
        crate::v3::writer_cli::test_run_named_cli(&cli.serve("2", Some(TEST_CONTRACT)), &registry)
            .err()
            .unwrap();
    assert_eq!(err, expected);
    assert!(!cli.socket.exists());
    assert_eq!(std::fs::read(&cli.request).unwrap(), request_bytes);
    assert_eq!(before, media_bytes(&f));
    assert_eq!(run(&f, Action::Query, Some(&first)).unwrap(), original);
}

#[test]
fn tb07_s_named_recovery_holds_both_locks_through_failure_accounting() {
    // 第一次和最后一次真实管道写分别同步；第二次 write 只能在上一笔 wire 已记账后进入。
    struct SynchronizedStderr {
        pipe: std::io::PipeWriter,
        written: mpsc::SyncSender<usize>,
        resume: mpsc::Receiver<()>,
        first: bool,
    }
    impl Write for SynchronizedStderr {
        fn write(&mut self, data: &[u8]) -> std::io::Result<usize> {
            let len = if self.first { 1 } else { data.len() };
            self.first = false;
            self.pipe.write_all(&data[..len])?;
            self.written.send(len).unwrap();
            self.resume.recv_timeout(Duration::from_secs(30)).unwrap();
            Ok(len)
        }
        fn flush(&mut self) -> std::io::Result<()> {
            self.pipe.flush()
        }
    }

    for (action, fixture_registry, wrong_catalog, expected) in [
        (
            "recover-named",
            true,
            false,
            "AdmissionNamedRecoveryContractUnregistered",
        ),
        ("query-recovery", false, false, "MissingDependency"),
        (
            "serve",
            false,
            false,
            "AdmissionContractSupersededOrUnknown",
        ),
        (
            "serve",
            true,
            true,
            "IdentityConflict：S恢复冻结 catalog_hash 与库不一致",
        ),
    ] {
        let f = fixture();
        publish_initial(&f);
        let cut = run(&f, Action::Inspect, None).unwrap();
        let raw = request_document(&cut, "first", "recover-1");
        let cli = RecoveryCli::new(&f, &raw);
        if wrong_catalog {
            let mut catalog = strict_json(&std::fs::read(&cli.catalog).unwrap()).unwrap();
            catalog["items"][0]["title"] = json!("目录冻结配置已变");
            std::fs::write(&cli.catalog, canonical_json(&catalog)).unwrap();
        }
        let args = match action {
            "serve" => cli.serve("1", Some(TEST_CONTRACT)),
            "query-recovery" => cli.command(action, None),
            _ => cli.command(action, Some(TEST_CONTRACT)),
        };
        let limits = std::fs::read_to_string(limits_path(&f)).unwrap();
        let (reader, pipe) = std::io::pipe().unwrap();
        let (written, observe) = mpsc::sync_channel(0);
        let (proceed, resume) = mpsc::sync_channel(0);
        let db = f.db.clone();
        let task = std::thread::spawn(move || {
            let accounting = CommandAccounting::begin();
            let error = if fixture_registry {
                let registry = test_registry(&limits);
                crate::v3::writer_cli::test_run_named_cli(&args, &registry)
                    .err()
                    .unwrap()
            } else {
                crate::run_with(&args).unwrap_err()
            };
            let mut sink = SynchronizedStderr {
                pipe,
                written,
                resume,
                first: true,
            };
            let receipt = accounting.report(&error, &mut sink);
            // report 已返回，但同一个 CommandAccounting 还活着；双锁应已释放。
            drop(Lock::acquire_existing(&db, ".writer.lock").unwrap());
            drop(Lock::acquire_existing(&db, ".maintenance.lock").unwrap());
            (error, receipt)
        });

        let mut reader = BufReader::new(reader);
        let mut raw = Vec::new();
        for _ in 0..2 {
            use std::io::Read;
            let len = observe.recv_timeout(Duration::from_secs(30)).unwrap();
            let mut bytes = vec![0; len];
            reader.read_exact(&mut bytes).unwrap();
            raw.extend(bytes);
            for (suffix, code) in [
                (".writer.lock", "StaleWriter"),
                (".maintenance.lock", "MaintenanceBusy"),
            ] {
                let err = Lock::acquire_existing(&f.db, suffix).err().unwrap();
                assert!(err.contains(code), "{action}: {err}");
            }
            proceed.send(()).unwrap();
        }
        let (error, receipt) = task.join().unwrap();
        assert!(error.starts_with(expected), "{action}: {error}");
        assert_eq!(raw.iter().filter(|&&byte| byte == b'\n').count(), 1);
        let body: Value = serde_json::from_slice(&raw).unwrap();
        assert_eq!(body["error"], error);
        assert_eq!(receipt.actual_stderr_bytes, raw.len() as u128);
        assert!(receipt.write_error.is_none());
        assert!(receipt.accounting_error.is_none());
        if expected != "AdmissionContractSupersededOrUnknown" {
            let stderr = body["admission_accounting"]["before_stderr"]
                .as_str()
                .unwrap();
            let job_wire = receipt.job.unwrap().wire_bytes;
            assert!(job_wire > receipt.actual_stderr_bytes);
            assert!(stderr.contains(&format!(
                "wire_bytes: {}",
                job_wire - receipt.actual_stderr_bytes
            )));
            assert_eq!(receipt.unaccepted_stderr_bytes, 0);
        } else {
            // 合同在进入实测 Job 前拒绝；保留前导账和原首错。
            assert!(receipt.prelude.is_some());
            assert!(receipt.job.is_none());
        }
    }
}
