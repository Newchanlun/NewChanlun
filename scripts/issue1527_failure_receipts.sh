#!/usr/bin/env bash
# Linux 复核 #1527：先在 rust/ 构建 release --features s_session --bin s_structure_session。
# 用法：scripts/issue1527_failure_receipts.sh <已构建二进制> <尚不存在的仓外证据目录>
set -eu

if [[ $# != 2 ]]; then
    echo "用法：$0 <s_structure_session 二进制> <尚不存在的仓外证据目录>" >&2
    exit 2
fi
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
exec python3 -I - "$repo" "$@" <<'PY'
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys
import tempfile

if not sys.platform.startswith("linux"):
    sys.exit("须在 Linux 重放 #1527（依赖 Linux 资源限制与准入路径）")

repo, binary, out = (Path(arg).resolve() for arg in sys.argv[1:])
if not binary.is_file() or not os.access(binary, os.X_OK):
    sys.exit(f"二进制不存在或不可执行：{binary}")
if out.is_relative_to(repo):
    sys.exit("证据目录须在仓外")
out.mkdir()
session = repo / "s_session"
fixtures = session / "tests/fixtures/tb01c"
catalog = session / "catalog/signed-catalog.json"
profile, clock = (fixtures / name for name in ("profile.json", "clock-plan.json"))
environment = {"PATH": os.defpath, "LC_ALL": "C.UTF-8"}
# main b9d898dccf 的 strace 扫描（3–8）：3/4 止于 Python 启动，5 首次在 R4 内
# 触发 EMFILE（固定库父目录）；8 到达 owner 后得到 ENOENT，不构成耗尽。
R4_NOFILE = 5


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(name, command, limits=None):
    receipt = out / name
    receipt.mkdir()
    write_json(receipt / "run.json", {
        "command": shlex.join(map(str, command)), "cwd": str(work),
        "env": environment, "os": platform.platform(), "python": platform.python_version(),
        "uid": os.geteuid(), "limits": limits or {},
    })
    # 用管道接收原始字节：子进程的 RLIMIT_FSIZE 不限制证据文件。
    result = subprocess.run(command, cwd=work, env=environment, capture_output=True)
    (receipt / "stdout").write_bytes(result.stdout)
    (receipt / "stderr").write_bytes(result.stderr)
    (receipt / "rc").write_text(f"{result.returncode}\n", encoding="ascii")
    return result


def check(name, command, field, expected, reason, limits=None):
    result = run(name, command, limits)
    try:
        error = json.loads(result.stderr)
    except (ValueError, UnicodeError):
        error = None
    observed = error.get(field) if isinstance(error, dict) else None
    if field == "error" and isinstance(observed, str):
        match = re.fullmatch(r"R4准入拒绝：(\w+)；阶段=(E\d+)；实读字节=\d+；限额可信=(?:true|false)", observed)
        if match:
            observed = "/".join(match.groups())
    ok = result.returncode > 0 and observed == expected
    write_json(out / name / "result.json", {
        "expected": expected, "observed": observed, "rc": result.returncode,
        "match": ok, "stimulus": reason,
    })
    print(f"{name}: rc={result.returncode}; 预期 {expected}；实测 {observed!r}；"
          f"{'符合' if ok else '不符'}")
    return ok


with tempfile.TemporaryDirectory(prefix="i1-1527-", dir="/tmp") as directory:
    work = Path(directory).resolve()
    db, state = work / "s.sqlite", work / "state"
    state.mkdir()
    revision = ["--protocol-revision", "s-session/3"]

    def init(path):
        return [binary, "init", *revision, "--db", path, "--session", "r1527-fail",
                "--catalog", catalog, "--profile", profile, "--session-generation", "1",
                "--clock-plan", clock, "--delivery-retain-generations", "1"]

    setup = run("setup", init(db))
    if setup.returncode != 0:
        sys.exit(f"夹具初始化失败（rc={setup.returncode}），参见 {out / 'setup/stderr'}")

    launcher = work / "launcher.json"
    config = {
        "schema_revision": "s-launcher/3", "db": str(db), "socket": str(work / "s.sock"),
        "binary": str(binary), "python": sys.executable, "catalog": str(catalog),
        "profile": str(profile), "clock_plan": str(clock), "browser": str(work / "browser"),
        "query_resource_config": str(fixtures / "query-resources.json"),
        "session_id": "r1527-fail", "session_generation": "1", "source_namespace": "r1527",
        "source_epoch": "1", "producer_id": "r1527", "producer_epoch": "1",
        "writer_epoch": "1", "query_epoch": "1", "port": "18881",
        "startup_timeout_ms": "10000", "delivery_retain_generations": "1",
        "s_resources": {
            "max_frame_bytes": "1048576", "read_timeout_ms": "5000",
            "write_timeout_ms": "5000", "response_timeout_ms": "5000",
            "audit_cache_source_bytes": "1048576", "queue_capacity": "8", "max_connections": "8",
        },
    }
    write_json(launcher, config)
    write_json(out / "launcher.json", config)
    start = [sys.executable, "-B", session / "s_service_control.py", "start-s",
             "--config", launcher, "--state-dir", state]
    forged = work / "forged-limits.json"
    write_json(forged, {"max_elapsed_ms": "1"})
    forged.chmod(0o600)
    (out / forged.name).write_bytes(forged.read_bytes())

    results = [
        check("F1-no-anchor", start, "code", "AnchorMissing",
              "正式 Python CLI 在未签锚库读取 owner 侧车；侧车不存在。"),
        check("F1b-forged-limits", [
            binary, "recover", *revision, "--db", db, "--new-epoch", "2",
            "--clock-plan", clock, "--clock-event-id", "e1", "--admission-job-limits", forged,
        ], "error", "AnchorMissing/E1", "直接调用 Rust recover；未签锚，不信任传入的 limits。"),
        check("F2-init-fsize", [
            "/bin/bash", "-c", 'trap "" XFSZ; ulimit -f 64 && exec "$@"', "fsize",
            *init(work / "full.sqlite"),
        ], "error", "init commit 失败：disk I/O error", "以文件大小上限模拟 init 写入失败。",
              {"RLIMIT_FSIZE_bytes": 65536, "SIGXFSZ": "ignored"}),
    ]
    # S3 init 在隐藏路径建库（atomic_init.rs）；异常退出也不该留下其 SQLite 旁文件。
    init_entries = sorted([*work.glob("full.sqlite*"), *work.glob(".full.sqlite.s3-init.*.tmp*")])
    init_residual_bytes = {p.name: p.lstat().st_size for p in init_entries}
    init_clean = all(
        p.name == "full.sqlite.writer.lock" and not p.is_symlink()
        and p.is_file() and init_residual_bytes[p.name] == 0
        for p in init_entries
    )
    if not init_clean:
        print("F2-init-fsize：失败后留下目标库、暂存库或旁文件", file=sys.stderr)
    # F1 已留下正常控制锁；资源不足的重试只可复用这些锁，不得新增文件或改库。
    before = {p.relative_to(work) for p in work.rglob("*")}
    db_before = db.read_bytes()
    results.append(check("F2b-nofile", [
        "/bin/bash", "-c", 'ulimit -n "$1" && shift && exec "$@"',
        "nofile", str(R4_NOFILE), *start,
    ], "code", "IO", "在 R4 固定库路径时触发 EMFILE。", {"RLIMIT_NOFILE": R4_NOFILE}))
    after = {p.relative_to(work) for p in work.rglob("*")}
    fd_effects = {
        "added": sorted(map(str, after - before)), "removed": sorted(map(str, before - after)),
        "db_unchanged": db.is_file() and db.read_bytes() == db_before,
    }
    write_json(out / "F2b-nofile/side-effects.json", fd_effects)
    fd_clean = not fd_effects["added"] and not fd_effects["removed"] and fd_effects["db_unchanged"]
    if not fd_clean:
        print("F2b-nofile：失败后夹具文件集合或库字节改变", file=sys.stderr)
    write_json(out / "post-state.json", {
        "init_residual_bytes": init_residual_bytes,
        "init_clean": init_clean,
        "owner_exists": db.with_name(db.name + ".control-owner.json").exists(),
        "state_entries": sorted(p.name for p in state.iterdir()),
    })
    print(f"收据：{out}")
    sys.exit(0 if all(results) and init_clean and fd_clean else 1)
PY
