#![cfg(feature = "production_session")]

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
