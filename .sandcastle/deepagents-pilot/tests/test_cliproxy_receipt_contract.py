"""#1742 CLIProxy Go 生产者收据与 Python `_review_preflight_log` 消费端跨语言契约回归。"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import _review_preflight_log as log_mod

SOL = "gpt-6.2-sol"
ASTRA = "gpt-6.2-astra"
PREFLIGHT_SESSION = "preflight-12345678-1234-4234-8234-123456789abc"


def _write_private_receipt(root: Path, subdir: str, payload: dict) -> Path:
    os.chmod(root, 0o700)
    directory = root / subdir
    directory.mkdir(exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    path = directory / "receipt.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(path, 0o600)
    return path


@pytest.mark.parametrize("model", [SOL, ASTRA])
def test_preflight_receipt_accepts_codex_model_scoped_routes(tmp_path: Path, model: str):
    now = time.time_ns()
    payload = {
        "schema": "cliproxy-preflight-v1",
        "session": PREFLIGHT_SESSION,
        "started_ns": now - 1_000_000,
        "finished_ns": now,
        "complete": True,
        "routes": [f"codex:{model}@chatgpt.com"],
    }
    _write_private_receipt(tmp_path, PREFLIGHT_SESSION, payload)
    assert log_mod.route_from_receipt(tmp_path, PREFLIGHT_SESSION, time.time() - 2, 0) == [
        (f"codex:{model}", "chatgpt.com")
    ]


@pytest.mark.parametrize("model,launch_prefix", [
    (SOL, "review-"),
    (ASTRA, "review-"),
    (SOL, "review-preflight-"),
    (ASTRA, "review-preflight-"),
])
def test_review_receipt_reader_and_cli_accept_sealed_codex_receipt(tmp_path: Path, model: str, launch_prefix: str):
    launch = f"{launch_prefix}12345678-1234-4234-8234-123456789ab1"
    session = "019d0000-0000-7000-8000-000000000ab1"
    now = time.time_ns()
    rid1, rid2, out_sha = "1" * 64, "a" * 64, "b" * 64
    payload = {
        "schema": "cliproxy-review-v1",
        "launch": launch,
        "session": session,
        "started_ns": now - 2_000_000,
        "finished_ns": now - 1_000_000,
        "sealed_at_ns": now,
        "complete": True,
        "sealed": True,
        "tainted": False,
        "requests": 2,
        "routes": [f"codex:{model}@chatgpt.com"],
        "response_id_sha256s": [rid1, rid2],
        "last_response_id_sha256": rid2,
        "last_output_sha256": out_sha,
    }
    _write_private_receipt(tmp_path, launch, payload)
    got = log_mod.review_from_receipt(
        tmp_path, launch, session, time.time() - 5, 0,
        expected_response_id_sha256=rid2, expected_output_sha256=out_sha, min_requests=2,
    )
    assert got == {
        "routes": [(f"codex:{model}", "chatgpt.com")],
        "requests": 2,
        "sealed": True,
        "response_id_sha256s": [rid1, rid2],
        "last_response_id_sha256": rid2,
        "last_output_sha256": out_sha,
    }

    # Verify CLI --review-receipt subprocess contract matches Go JSON schema.
    known = json.dumps([[f"codex:{model}", "chatgpt.com"]])
    proc = subprocess.run(
        [
            sys.executable, "-I", str(Path(log_mod.__file__).resolve()),
            "--review-receipt", str(tmp_path), launch, session,
            str(time.time() - 5), str(time.time() + 5), "10", known, rid2, out_sha, "2",
        ],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert proc.returncode == 0 and proc.stderr == ""
    out = json.loads(proc.stdout)
    assert out == {
        "launch": launch,
        "session": session,
        "complete_stable": True,
        "sealed": True,
        "routes": [f"codex:{model}@chatgpt.com"],
        "requests": 2,
        "response_id_sha256s": [rid1, rid2],
        "last_response_id_sha256": rid2,
        "last_output_sha256": out_sha,
    }


def test_review_receipt_reader_rejects_unsealed_tainted_bad_perms_and_symlinks(tmp_path: Path):
    launch = "review-12345678-1234-4234-8234-123456789ab2"
    session = "019d0000-0000-7000-8000-000000000ab2"
    now = time.time_ns()
    base = {
        "schema": "cliproxy-review-v1",
        "launch": launch,
        "session": session,
        "started_ns": now - 1_000_000,
        "finished_ns": now,
        "sealed_at_ns": now,
        "complete": True,
        "sealed": True,
        "tainted": False,
        "requests": 1,
        "routes": [f"codex:{SOL}@chatgpt.com"],
        "response_id_sha256s": ["a" * 64],
        "last_response_id_sha256": "a" * 64,
        "last_output_sha256": "b" * 64,
    }
    path = _write_private_receipt(tmp_path, launch, base)
    assert log_mod.review_from_receipt(tmp_path, launch, session, time.time() - 5, 0) is not None

    # Unsealed receipt waits within wait budget and accepts once atomically sealed.
    unsealed = {**base, "sealed": False, "sealed_at_ns": 0}
    _write_private_receipt(tmp_path, launch, unsealed)
    assert log_mod.review_from_receipt(tmp_path, launch, session, time.time() - 5, 0) is None

    def seal_later() -> None:
        pending = path.parent / "pending"
        pending.write_text(json.dumps(base), encoding="utf-8")
        os.chmod(pending, 0o600)
        pending.replace(path)

    timer = threading.Timer(0.03, seal_later)
    timer.start()
    try:
        assert log_mod.review_from_receipt(tmp_path, launch, session, time.time() - 5, 0.5) is not None
    finally:
        timer.join()

    for bad in (
        {"tainted": True},
        {"complete": False},
        {"sealed": False, "sealed_at_ns": 0},
        {"sealed_at_ns": now - 2_000_000},
        {"routes": ["claude@api.anthropic.com"]},
        {"routes": ["other"]},
        {"requests": 0},
        {"extra": True},
    ):
        _write_private_receipt(tmp_path, launch, {**base, **bad})
        assert log_mod.review_from_receipt(tmp_path, launch, session, time.time() - 5, 0) is None

    # Permissive root/dir/file modes and symlinks MUST fail closed.
    _write_private_receipt(tmp_path, launch, base)
    os.chmod(path, 0o644)
    assert log_mod.review_from_receipt(tmp_path, launch, session, time.time() - 5, 0) is None
    os.chmod(path, 0o600)
    os.chmod(path.parent, 0o755)
    assert log_mod.review_from_receipt(tmp_path, launch, session, time.time() - 5, 0) is None
    os.chmod(path.parent, 0o700)
    os.chmod(tmp_path, 0o755)
    assert log_mod.review_from_receipt(tmp_path, launch, session, time.time() - 5, 0) is None
    os.chmod(tmp_path, 0o700)

    target = tmp_path / "other.json"
    target.write_text(json.dumps(base), encoding="utf-8")
    os.chmod(target, 0o600)
    path.unlink()
    path.symlink_to(target)
    assert log_mod.review_from_receipt(tmp_path, launch, session, time.time() - 5, 0) is None


def test_generated_go_codex_and_review_receipts_consumed_by_python():
    root_env = os.environ.get("CLIPROXY_OFFLINE_RECEIPTS")
    if not root_env:
        pytest.skip("需要 cliproxy/build.py 导出的离线生产者收据")
    root = Path(root_env)

    for name, session, model in (
        ("native-codex-sol", "preflight-12345678-1234-4234-8234-123456789abd", SOL),
        ("native-codex-astra", "preflight-12345678-1234-4234-8234-123456789abe", ASTRA),
    ):
        payload = json.loads((root / name / session / "receipt.json").read_text(encoding="utf-8"))
        since = payload["started_ns"] / 1e9
        assert log_mod.route_from_receipt(root / name, session, since, 0.5) == [(f"codex:{model}", "chatgpt.com")]

    for name, launch, session, model in (
        ("review-codex-sol", "review-12345678-1234-4234-8234-123456789aa1", "019d0000-0000-7000-8000-000000000aa1", SOL),
        ("review-codex-astra", "review-12345678-1234-4234-8234-123456789aa2", "019d0000-0000-7000-8000-000000000aa2", ASTRA),
    ):
        payload = json.loads((root / name / launch / "receipt.json").read_text(encoding="utf-8"))
        assert payload["sealed"] is True
        since = payload["started_ns"] / 1e9
        got = log_mod.review_from_receipt(root / name, launch, session, since, 0.5)
        assert got is not None and got["routes"] == [(f"codex:{model}", "chatgpt.com")]
        assert got["requests"] == 2 and got["sealed"] is True
        assert len(got["response_id_sha256s"]) == 2 and got["response_id_sha256s"][-1] == got["last_response_id_sha256"]
        assert log_mod.review_from_receipt(root / name, launch, "019d0000-0000-7000-8000-000000000fff", since, 0) is None

    tainted_launch = "review-12345678-1234-4234-8234-123456789aa3"
    tainted_session = "019d0000-0000-7000-8000-000000000aa3"
    tainted_payload = json.loads((root / "review-codex-tainted" / tainted_launch / "receipt.json").read_text(encoding="utf-8"))
    assert tainted_payload["tainted"] is True and tainted_payload["complete"] is False and tainted_payload["sealed"] is False
    assert log_mod.review_from_receipt(
        root / "review-codex-tainted", tainted_launch, tainted_session, tainted_payload["started_ns"] / 1e9, 0
    ) is None
