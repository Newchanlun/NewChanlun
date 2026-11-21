#![cfg(feature = "production_session")]

/// 受控 E/S Unix authority 只证明 X 接口，不冒称完整业务 producer。
#[test]
fn real_x_process_authority_restart_and_double_replay() {
    run_x_fixture(None);
}

#[test]
fn authority_rebind_preserves_original_attempts() {
    run_x_fixture(Some("authority-rebind"));
}
fn run_x_fixture(mode: Option<&str>) {
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
        .args(mode)
        .env("X_FIXTURE_E_BIN", env!("CARGO_BIN_EXE_e_economic_session"))
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
