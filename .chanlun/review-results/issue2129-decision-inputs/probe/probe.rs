// 附加在 #2082 原件 exact_x_e2e_tests.rs 的测试夹具；不替换生产逻辑。
#[test]
fn issue2129_real_e_named_recovery_then_x_next_exchange() {
    use std::os::unix::process::ExitStatusExt;
    use std::process::{Child, Command, ExitStatus, Stdio};

    struct Proc(Child, &'static str);
    impl Proc {
        fn kill_and_log(&mut self) -> ExitStatus {
            if self.0.try_wait().unwrap().is_none() {
                self.0.kill().unwrap();
            }
            let status = self.0.wait().unwrap();
            let mut stderr = String::new();
            self.0.stderr.take().unwrap().read_to_string(&mut stderr).unwrap();
            println!("{} pid={} status={status} stderr-begin\n{stderr}stderr-end", self.1, self.0.id());
            status
        }
    }
    impl Drop for Proc {
        fn drop(&mut self) {
            if self.0.stderr.is_some() {
                self.kill_and_log();
            }
        }
    }
    fn launch(bin: &mut Command, label: &'static str, socket: &Path) -> Proc {
        println!("{label} argv={bin:?}");
        let mut p = Proc(bin.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::piped()).spawn().unwrap(), label);
        let until = std::time::Instant::now() + std::time::Duration::from_secs(10);
        while !listening(socket) {
            assert!(p.0.try_wait().unwrap().is_none(), "{label} 退出");
            assert!(std::time::Instant::now() < until, "{label} 未监听");
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        println!("{label} ready pid={}", p.0.id());
        p
    }
    fn raw(socket: &Path, label: &str, frame: &Value) -> Value {
        let mut s = UnixStream::connect(socket).unwrap();
        s.set_read_timeout(Some(std::time::Duration::from_secs(8))).unwrap();
        let request = canonical_json(frame);
        s.write_all(format!("{request}\n").as_bytes()).unwrap();
        s.shutdown(std::net::Shutdown::Write).unwrap();
        let mut reply = String::new();
        BufReader::new(s).read_line(&mut reply).unwrap();
        println!("{label} request={request}\n{label} reply={}", reply.trim_end());
        strict_json(reply.trim_end().as_bytes()).unwrap()
    }

    let mut f = fixture(None);
    committed(&mut f);
    dispatch(&mut f, "alpha");
    let exact = expected_command(&f, "alpha");
    let release_payload = release_payload(&f, "alpha");
    let x_profile = x_profile(&f);
    let Fixture { dir, configs, dbs, .. } = f;
    drop(dbs);
    let e = &configs[0];
    let manifest = dir.join("manifest.json");
    let x_db = dir.join("x.sqlite");
    let x_path = dir.join("x.sock");
    let e_path = dir.join("e.sock");
    let profile_path = dir.join("x.json");
    let outer_profile = |p: Value| json!({"profile_revision":"x-execution-profile/1","mode":"simulation","credential_scope":{"env":"ISSUE2129_UNUSED_FIXTURE_CREDENTIAL"},"history_simulation":p});
    save(&dir, "x.json", &outer_profile(x_profile.clone()));
    let bin = PathBuf::from(std::env::var_os("PROBE_BIN_DIR").unwrap());
    let e_cmd = |op: &str| {
        let mut c = Command::new(bin.join("e_economic_session"));
        c.arg(op).arg("--manifest").arg(&manifest).arg("--db").arg(&e.db);
        c
    };
    let x_cmd = |profile: &Path| {
        let mut c = Command::new(bin.join("x_execution_session"));
        c.arg("serve").arg("--db").arg(&x_db).arg("--profile").arg(profile).arg("--writer-epoch").arg("1").env_remove("ISSUE2129_UNUSED_FIXTURE_CREDENTIAL");
        c
    };
    let mut e1 = launch(e_cmd("serve").arg("--epoch").arg("1"), "E1", &e_path);
    let mut xp = launch(&mut x_cmd(&profile_path), "X1", &x_path);
    for i in 0..RELEASE_NS {
        assert_eq!(x(&x_path, "AdvanceBar", bar(i, json!([])))["kind"], "SimulationBatch");
    }
    let accept_request = json!({"protocol":"x-exact-simulation/1","op":"AcceptExact","payload":exact});
    let pre = raw(&x_path, "X→E1 before release", &accept_request);
    assert_eq!(pre["kind"], "Error");
    assert_eq!(pre["error"], "MissingDependency：权威结果为NoRecord，需要ReleasedExact");
    let release = raw(&e_path, "E1 release", &envelope("ReleaseExact-alpha", release_payload));
    assert_eq!(release["payload"]["record"]["state"], "ReleasedExact");
    assert_eq!(release["payload"]["record"]["command"], exact);
    assert_eq!(e1.kill_and_log().signal(), Some(libc::SIGKILL));
    // #2079 尚未实装：测试只移动自己启动的 E1 的残留 socket，绝不把此动作算作产品功能。
    std::fs::rename(&e_path, dir.join("e-killed.sock")).unwrap();
    println!("fixture moved its own stopped E1 socket aside; E2 reuses e.sock; X PID remains {}", xp.0.id());
    let recovery = json!({"schema_revision":"economic-recovery/1","recovery_id":"probe-2129-e","domain_id":e.domain,
        "session_id":e.session,"session_generation":e.generation,"manifest_hash":e.manifest_hash,
        "from_epoch":"1","cut":release["payload"]["cut"]});
    save(&dir, "recovery.json", &recovery);
    let receipt = |op: &str| {
        let out = e_cmd(op).arg("--recovery-request").arg(dir.join("recovery.json")).output().unwrap();
        println!("E {op} status={} stdout-begin\n{}stdout-end stderr-begin\n{}stderr-end",
            out.status, String::from_utf8_lossy(&out.stdout), String::from_utf8_lossy(&out.stderr));
        assert!(out.status.success());
        strict_json(out.stdout.strip_suffix(b"\n").unwrap(),).unwrap()
    };
    let r = receipt("recover-named");
    assert_eq!(r["kind"], "NamedRecoveryReceipt");
    assert_eq!(r["writer_epoch"], "2");
    assert_eq!(r["request"], recovery);
    assert_eq!(receipt("current-recovery"), r);
    let mut e2 = launch(e_cmd("serve").arg("--epoch").arg("2"), "E2", &e_path);
    assert!(xp.0.try_wait().unwrap().is_none());
    let before = tables(&x_db);
    let post = raw(&x_path, "X→E2 first post-recovery authority exchange", &accept_request);
    assert_eq!(post, json!({"kind":"Error","error":"IdentityConflict：权威回复信封的身份/epoch/因果/规范字节不符"}));
    assert_eq!(tables(&x_db), before, "失败不改 X 业务或绑定");
    // 同样的授权来源与精确命令，直接读取 E2 的旧/新代信封，核实 X 对外错误前 E 说了什么。
    let e_frame = |epoch| {
        let p = authority_query_for_probe(e, &exact, epoch);
        let (ns, source_epoch, producer_id, producer_epoch) = X_SOURCE;
        json!({"schema_revision":e.revision().unwrap(),"session_id":e.session,"session_generation":e.generation,
            "source_namespace":ns,"source_epoch":source_epoch,"producer_id":producer_id,"producer_epoch":producer_epoch,
            "message_id":format!("x-authority-{}",hash(&p)),"payload_hash":hash(&p),"causal_refs":[],"payload":p})
    };
    let old = raw(&e_path, "direct E2 old authority epoch", &e_frame("1"));
    assert_eq!(old["producer_epoch"], "2");
    assert_eq!(old["source_epoch"], "2");
    assert_eq!(old["payload"]["kind"], "Error");
    assert!(old["payload"]["error"].as_str().unwrap().starts_with("StaleWriter"));
    let current = raw(&e_path, "direct E2 current authority epoch", &e_frame("2"));
    assert_eq!(current["payload"]["state"], "ReleasedExact");
    assert_eq!(current["payload"]["command"], exact);
    assert_eq!(current["payload"]["receipt_id"], release["payload"]["receipt_key"]);
    assert_eq!(xp.kill_and_log().signal(), Some(libc::SIGKILL));
    let mut next = x_profile;
    next["e"]["authority_epoch"] = json!("2");
    save(&dir, "x-next.json", &outer_profile(next));
    let out = x_cmd(&dir.join("x-next.json")).output().unwrap();
    println!("X cold edit status={} stdout-begin\n{}stdout-end stderr-begin\n{}stderr-end",
        out.status, String::from_utf8_lossy(&out.stdout), String::from_utf8_lossy(&out.stderr));
    assert_eq!(out.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&out.stderr).contains("IdentityConflict：X 权威端点合同已冻结"));
    assert_eq!(tables(&x_db), before);
    e2.kill_and_log();
    std::fs::remove_dir_all(&dir).unwrap();
}

fn authority_query_for_probe(e: &Config, command: &Value, epoch: &str) -> Value {
    json!({"op":"QueryReleasedExact","protocol":"x-exact-authority/1","session_id":e.session,"session_generation":e.generation,
        "authority_id":"E","authority_epoch":epoch,"command_id":command["command_id"],"command_hash":hash(command),"command":command,"release_receipt_id":null})
}
