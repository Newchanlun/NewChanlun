"""#1986：删卷后的 VM fstrim——注入执行器验证节流、互斥、失败折叠与 Colima 判定。"""
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

from pilot1742 import vm_trim
from pilot1742.vm_trim import (
    LOCK_NAME,
    STAMP_NAME,
    TRIM_INTERVAL_SECONDS,
    colima_profile,
    trim_vm_disk,
)

FSTRIM = ["colima", "--profile", "default", "ssh", "--", "sudo", "-n", "fstrim", "-v", "/var/lib/docker"]


class Runner:
    def __init__(self, context="colima", trim_code=0):
        self.context, self.trim_code, self.calls = context, trim_code, []

    def __call__(self, argv, timeout):
        self.calls.append((argv, timeout))
        if argv[:2] == ["docker", "context"]:
            return subprocess.CompletedProcess(argv, 0, self.context + "\n", "")
        return subprocess.CompletedProcess(argv, self.trim_code, "/var/lib/docker: 5.8 GiB (6227000000 bytes) trimmed\n",
                                           "load key /fixture/key-path: denied")


def test_trims_colima_vm_with_timeout_and_records_amount(tmp_path):
    run = Runner()
    result = trim_vm_disk(tmp_path, run=run, now=lambda: 1000.0)
    assert result["state"] == "trimmed" and "5.8 GiB" in result["output"] and result["profile"] == "default"
    assert run.calls == [(["docker", "context", "show"], vm_trim.CONTEXT_TIMEOUT_SECONDS), (FSTRIM, 60)]
    assert (tmp_path / STAMP_NAME).stat().st_mtime == 1000.0


def test_throttles_within_interval_even_after_failure(tmp_path):
    run = Runner(trim_code=1)
    first = trim_vm_disk(tmp_path, run=run, now=lambda: 1000.0)
    assert first == {"state": "failed", "reason": "fstrim", "returncode": 1, "profile": "default"}
    assert "key-path" not in json.dumps(first), "不记 stderr（ssh 报错可能带登录密钥路径）"
    run.calls.clear()
    assert trim_vm_disk(tmp_path, run=run, now=lambda: 1000.0 + TRIM_INTERVAL_SECONDS - 1) == {
        "state": "throttled", "seconds_since_last": TRIM_INTERVAL_SECONDS - 1}
    assert run.calls == []
    run.trim_code = 0
    assert trim_vm_disk(tmp_path, run=run, now=lambda: 1000.0 + TRIM_INTERVAL_SECONDS)["state"] == "trimmed"


def test_only_one_trim_at_a_time(tmp_path):
    run = Runner()
    holder = os.open(tmp_path / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX)
        assert trim_vm_disk(tmp_path, run=run) == {"state": "busy"}
        assert run.calls == [] and not (tmp_path / STAMP_NAME).exists()
    finally:
        os.close(holder)
    assert trim_vm_disk(tmp_path, run=run)["state"] == "trimmed"


def test_timeout_and_missing_docker_are_failures_not_errors(tmp_path):
    def timed_out(argv, timeout):
        if argv[0] == "docker":
            return subprocess.CompletedProcess(argv, 0, "colima-work\n", "")
        return subprocess.CompletedProcess(argv, 124, "", "")
    assert trim_vm_disk(tmp_path, run=timed_out) == {"state": "failed", "reason": "timeout", "returncode": 124,
                                                     "profile": "work"}
    other = tmp_path / "other"
    other.mkdir()
    assert trim_vm_disk(other, run=lambda argv, t: subprocess.CompletedProcess(argv, 127, "", "")) == {
        "state": "failed", "reason": "docker_context", "returncode": 127}


def test_not_colima_or_missing_root_skips(tmp_path):
    run = Runner(context="desktop-linux")
    assert trim_vm_disk(tmp_path, run=run) == {"state": "skipped", "reason": "not_colima"}
    assert [argv for argv, _ in run.calls] == [["docker", "context", "show"]]
    assert trim_vm_disk(tmp_path / "missing", run=run) == {"state": "skipped", "reason": "no_root"}
    assert colima_profile("colima") == "default" and colima_profile("colima-a.b") == "a.b"
    assert colima_profile("colima-") is None and colima_profile("colima-x y") is None and colima_profile("default") is None


def test_run_command_kills_whole_group_on_timeout():
    # sh 起的孙进程握着 stdout；只杀直接子进程时 communicate 会一直等到孙进程结束。
    result = vm_trim.run_command(["sh", "-c", "sleep 30 & sleep 30"], 0.5)
    assert result.returncode == 124
    assert vm_trim.run_command(["/nonexistent-binary-1986"], 1).returncode == 127


def test_cli_prints_one_json_record(tmp_path):
    script = Path(vm_trim.__file__)
    out = subprocess.run([sys.executable, "-I", str(script), str(tmp_path / "missing")], capture_output=True, text=True,
                         check=True)
    assert json.loads(out.stdout) == {"state": "skipped", "reason": "no_root"}
