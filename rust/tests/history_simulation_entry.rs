#![cfg(feature = "production_session")]

#[path = "fixtures/issue1407_ce_s07/profile.rs"]
mod ce_s07_profile;

#[test]
fn x_refuses_duplicate_fx_revision_before_writer_lock() {
    use ce_s07_profile::{duplicate_revision, x_fx2_profile, FX1, FX2};
    use std::{fs, process::Command};

    let space = tempfile::tempdir().unwrap();
    let dir = space.path();
    let sockets = dir.join("uncreated-sockets");
    let profile = x_fx2_profile(&sockets);
    let path = dir.join("x-profile.json");
    let db = dir.join("x.db");
    let run = |epoch| {
        Command::new(env!("CARGO_BIN_EXE_x_execution_session"))
            .args(["serve", "--db"])
            .arg(&db)
            .arg("--profile")
            .arg(&path)
            .args(["--writer-epoch", epoch])
            .output()
            .unwrap()
    };

    // 单一 FX/2 合法，确实能通过 profile 解析到达 epoch 门。
    fs::write(&path, profile.to_string()).unwrap();
    let control = run("0");
    assert_eq!(control.status.code(), Some(2));
    let stderr = String::from_utf8_lossy(&control.stderr);
    assert!(stderr.contains("writer_epoch"), "{stderr}");

    for (first, last) in [(FX1, FX2), (FX2, FX1)] {
        fs::write(
            &path,
            duplicate_revision(&profile, "fx_valuation_revision", first, last),
        )
        .unwrap();
        // 给有效 epoch；若错误启动，缺失的 socket 父目录让进程退出而不是一直监听。
        let out = run("1");
        let stderr = String::from_utf8_lossy(&out.stderr);
        assert_eq!(out.status.code(), Some(2), "{first} → {last}: {stderr}");
        assert!(
            stderr.contains("duplicate key fx_valuation_revision"),
            "{first} → {last}: {stderr}"
        );
        assert!(out.stdout.is_empty());
        assert!(!sockets.exists());
        assert!(!db.exists());
        assert!(!dir.join("x.db.writer.lock").exists());
    }
}

/// 受控 E/S Unix authority 只证明 X 接口，不冒称完整业务 producer。
#[test]
fn real_x_process_authority_restart_and_double_replay() {
    run_fixture(&[]);
}

#[test]
fn restage_missing_x_originals_through_real_e_capture() {
    run_fixture(&["capture-repair", env!("CARGO_BIN_EXE_e_economic_session")]);
}

#[test]
fn restage_frozen_profile_1_batch_without_reopening_x() {
    run_fixture(&["archive-repair", env!("CARGO_BIN_EXE_e_economic_session")]);
}

fn run_fixture(extra_args: &[&str]) {
    let directory = std::env::temp_dir().join(format!(
        "issue1381-x-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir(&directory).unwrap();
    let output = std::process::Command::new("python3")
        .arg(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/tests/history_simulation_entry.py"
        ))
        .arg(env!("CARGO_BIN_EXE_x_execution_session"))
        .arg(&directory)
        .args(extra_args)
        .output()
        .expect("python3 standard-library process fixture");
    assert!(
        output.status.success(),
        "stdout={}\nstderr={}\nevidence={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
        directory.display()
    );
    println!("{}", String::from_utf8_lossy(&output.stdout));
    std::fs::remove_dir_all(&directory).unwrap();
}
