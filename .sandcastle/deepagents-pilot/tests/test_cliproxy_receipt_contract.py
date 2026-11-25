"""#1742 CLIProxy Go 生产者收据与 Python `_review_preflight_log` / `review_preflight` 跨语言契约回归。"""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import _review_preflight_log as log_mod
import review_preflight as preflight

SOL = "gpt-6.2-sol"
ASTRA = "gpt-6.2-astra"
PREFLIGHT_SESSION = "preflight-12345678-1234-4234-8234-123456789abc"


def _write_private_receipt(root: Path, subdir: str, payload: dict) -> tuple[Path, str]:
    os.chmod(root, 0o700)
    directory = root / subdir
    directory.mkdir(exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    path = directory / "receipt.json"
    raw = json.dumps(payload).encode("utf-8")
    path.write_bytes(raw)
    os.chmod(path, 0o600)
    return path, hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("model", [SOL, ASTRA])
def test_preflight_receipt_accepts_codex_model_scoped_routes_via_preflight_entrypoint(tmp_path: Path, model: str):
    """Astra P2 #2: 经由实际 review_preflight.route_from_host_receipt 入口读取带模型名 Codex 路由，不得映射为 other。"""
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
    expected = [(f"codex:{model}", "chatgpt.com")]
    assert log_mod.route_from_receipt(tmp_path, PREFLIGHT_SESSION, time.time() - 2, 0) == expected
    assert preflight.route_from_host_receipt(
        str(tmp_path), PREFLIGHT_SESSION, time.time() - 2, 1, preflight.Deadline(3)
    ) == expected


@pytest.mark.parametrize("model", [SOL, ASTRA])
def test_formal_review_receipt_and_preflight_receipt_cli_separation(tmp_path: Path, model: str):
    """Sol P2: 正式验收 --review-receipt 必须核验独立响应 ID、输出摘要与请求数；预检探针走 --review-preflight-receipt 且限定命名空间。"""
    formal_launch = "review-12345678-1234-4234-8234-123456789ab1"
    preflight_launch = "review-preflight-12345678-1234-4234-8234-123456789ab1"
    session = "019d0000-0000-7000-8000-000000000ab1"
    now = time.time_ns()
    rid1, rid2, out_sha = "1" * 64, "a" * 64, "b" * 64
    base = {
        "schema": "cliproxy-review-v1",
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
    _, formal_sha = _write_private_receipt(tmp_path, formal_launch, {**base, "launch": formal_launch})
    _, preflight_sha = _write_private_receipt(
        tmp_path, preflight_launch, {**base, "launch": preflight_launch, "last_output_sha256": ""}
    )
    known = json.dumps([[f"codex:{model}", "chatgpt.com"]])
    script = str(Path(log_mod.__file__).resolve())

    # 1. Formal --review-receipt succeeds with full 11 args (receipt_sha + rid + out_sha + min_requests).
    got = log_mod.review_from_receipt(
        tmp_path, formal_launch, session, time.time() - 5, 0,
        expected_receipt_sha256=formal_sha,
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
    proc = subprocess.run(
        [
            sys.executable, "-I", script,
            "--review-receipt", str(tmp_path), formal_launch, session,
            str(time.time() - 5), str(time.time() + 5), "10", known, formal_sha, rid2, out_sha, "2",
        ],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert proc.returncode == 0 and proc.stderr == ""
    assert json.loads(proc.stdout) == {
        "launch": formal_launch,
        "session": session,
        "complete_stable": True,
        "sealed": True,
        "routes": [f"codex:{model}@chatgpt.com"],
        "requests": 2,
        "response_id_sha256s": [rid1, rid2],
        "last_response_id_sha256": rid2,
        "last_output_sha256": out_sha,
    }

    # 2. Short 8-arg --review-receipt is rejected (rc=2); empty rid/out_sha or tool-only receipt fails closed.
    short_proc = subprocess.run(
        [
            sys.executable, "-I", script,
            "--review-receipt", str(tmp_path), formal_launch, session,
            str(time.time() - 5), str(time.time() + 5), "10", known, formal_sha,
        ],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert short_proc.returncode == 2
    assert log_mod.review_from_receipt(
        tmp_path, formal_launch, session, time.time() - 5, 0,
        expected_receipt_sha256=formal_sha,
    ) is None
    assert log_mod.review_from_receipt(
        tmp_path, preflight_launch, session, time.time() - 5, 0,
        expected_receipt_sha256=preflight_sha,
        expected_response_id_sha256=rid2, expected_output_sha256="", min_requests=1,
    ) is None

    # 3. Formal --review-receipt MUST reject review-preflight-<uuid4> even when text & all hashes match.
    _, preflight_with_text_sha = _write_private_receipt(
        tmp_path, preflight_launch, {**base, "launch": preflight_launch}
    )
    assert log_mod.review_from_receipt(
        tmp_path, preflight_launch, session, time.time() - 5, 0,
        expected_receipt_sha256=preflight_with_text_sha,
        expected_response_id_sha256=rid2, expected_output_sha256=out_sha, min_requests=2,
        require_content_match=True,
    ) is None
    formal_on_pf_proc = subprocess.run(
        [
            sys.executable, "-I", script,
            "--review-receipt", str(tmp_path), preflight_launch, session,
            str(time.time() - 5), str(time.time() + 5), "10", known, preflight_with_text_sha, rid2, out_sha, "2",
        ],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert formal_on_pf_proc.returncode == 0
    formal_on_pf_out = json.loads(formal_on_pf_proc.stdout)
    assert formal_on_pf_out["complete_stable"] is False and formal_on_pf_out["sealed"] is False

    # Restore tool-only preflight receipt and verify --review-preflight-receipt accepts review-preflight-<uuid4>
    # (returns preflight_sealed, NOT complete_stable) and refuses formal review-<uuid4> launches.
    _, preflight_sha = _write_private_receipt(
        tmp_path, preflight_launch, {**base, "launch": preflight_launch, "last_output_sha256": ""}
    )
    pf_proc = subprocess.run(
        [
            sys.executable, "-I", script,
            "--review-preflight-receipt", str(tmp_path), preflight_launch, session,
            str(time.time() - 5), str(time.time() + 5), "10", known, preflight_sha,
        ],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert pf_proc.returncode == 0 and pf_proc.stderr == ""
    pf_out = json.loads(pf_proc.stdout)
    assert "complete_stable" not in pf_out and pf_out["preflight_sealed"] is True and pf_out["routes"] == [f"codex:{model}@chatgpt.com"]

    pf_formal_proc = subprocess.run(
        [
            sys.executable, "-I", script,
            "--review-preflight-receipt", str(tmp_path), formal_launch, session,
            str(time.time() - 5), str(time.time() + 5), "10", known, formal_sha,
        ],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert pf_formal_proc.returncode == 0 and json.loads(pf_formal_proc.stdout)["preflight_sealed"] is False


def test_review_receipt_rejects_mismatched_hashes_min_requests_and_unconfirmed_seal(tmp_path: Path):
    """Sol P1 #1/#2 & Astra P1 #1/#3: 已封存收据若响应 ID/输出摘要/请求数不符，或缺少/不匹配封存确认摘要，立即拒绝。"""
    launch = "review-12345678-1234-4234-8234-123456789ab3"
    session = "019d0000-0000-7000-8000-000000000ab3"
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
        "routes": [f"codex:{SOL}@chatgpt.com"],
        "response_id_sha256s": [rid1, rid2],
        "last_response_id_sha256": rid2,
        "last_output_sha256": out_sha,
    }
    _, receipt_sha = _write_private_receipt(tmp_path, launch, payload)
    known = json.dumps([[f"codex:{SOL}", "chatgpt.com"]])

    # 1. Missing or mismatched expected_receipt_sha256 (e.g. disk visible after SealUnavailable) MUST fail closed.
    assert log_mod.review_from_receipt(
        tmp_path, launch, session, time.time() - 5, 0,
        expected_response_id_sha256=rid2, expected_output_sha256=out_sha, min_requests=2,
    ) is None
    assert log_mod.review_from_receipt(
        tmp_path, launch, session, time.time() - 5, 0,
        expected_receipt_sha256="0" * 64,
        expected_response_id_sha256=rid2, expected_output_sha256=out_sha, min_requests=2,
    ) is None

    # 2. Mismatched response_id, mismatched output_sha256, or insufficient requests MUST fail closed (even at wait=0).
    for exp_rid, exp_out, min_reqs in (
        ("c" * 64, out_sha, 2),
        (rid2, "d" * 64, 2),
        (rid2, out_sha, 3),
        ("", out_sha, 2),
        (rid2, "", 2),
    ):
        assert log_mod.review_from_receipt(
            tmp_path, launch, session, time.time() - 5, 0,
            expected_receipt_sha256=receipt_sha,
            expected_response_id_sha256=exp_rid,
            expected_output_sha256=exp_out,
            min_requests=min_reqs,
        ) is None
        started = time.monotonic()
        assert log_mod.review_from_receipt(
            tmp_path, launch, session, time.time() - 5, 1.0,
            expected_receipt_sha256=receipt_sha,
            expected_response_id_sha256=exp_rid,
            expected_output_sha256=exp_out,
            min_requests=min_reqs,
        ) is None
        assert time.monotonic() - started < 0.3
        proc = subprocess.run(
            [
                sys.executable, "-I", str(Path(log_mod.__file__).resolve()),
                "--review-receipt", str(tmp_path), launch, session,
                str(time.time() - 5), str(time.time() + 5), "10", known, receipt_sha,
                exp_rid, exp_out, str(min_reqs),
            ],
            capture_output=True, text=True, timeout=10, check=False,
        )
        assert proc.returncode == 0 and proc.stderr == ""
        out = json.loads(proc.stdout)
        assert out["complete_stable"] is False and out["sealed"] is False and out["routes"] == []


def test_review_receipt_reader_waits_on_initial_reservation_placeholder_and_rejects_bad_states(tmp_path: Path):
    """Sol P2 & Astra P2 #1: 正确等待 Go 初始预留占位（session=""/complete=false/requests=0）与未封存中间态，拒绝污染与坏权限。"""
    launch = "review-12345678-1234-4234-8234-123456789ab2"
    session = "019d0000-0000-7000-8000-000000000ab2"
    now = time.time_ns()
    rid, out_sha = "a" * 64, "b" * 64
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
        "response_id_sha256s": [rid],
        "last_response_id_sha256": rid,
        "last_output_sha256": out_sha,
    }
    sealed_bytes = json.dumps(base).encode("utf-8")
    sealed_sha = hashlib.sha256(sealed_bytes).hexdigest()

    # 1. Go ReserveReview initial placeholder: session="", complete=False, sealed=False, requests=0, routes=["other"].
    placeholder = {
        "schema": "cliproxy-review-v1",
        "launch": launch,
        "session": "",
        "started_ns": now - 2_000_000,
        "finished_ns": now - 2_000_000,
        "sealed_at_ns": 0,
        "complete": False,
        "sealed": False,
        "tainted": False,
        "requests": 0,
        "routes": ["other"],
        "response_id_sha256s": [],
        "last_response_id_sha256": "",
        "last_output_sha256": "",
    }
    path, _ = _write_private_receipt(tmp_path, launch, placeholder)
    assert log_mod.review_from_receipt(
        tmp_path, launch, session, time.time() - 5, 0,
        expected_receipt_sha256=sealed_sha,
        expected_response_id_sha256=rid, expected_output_sha256=out_sha,
    ) is None

    def seal_later() -> None:
        pending = path.parent / "pending"
        pending.write_bytes(sealed_bytes)
        os.chmod(pending, 0o600)
        pending.replace(path)

    timer = threading.Timer(0.03, seal_later)
    timer.start()
    try:
        got = log_mod.review_from_receipt(
            tmp_path, launch, session, time.time() - 5, 0.5,
            expected_receipt_sha256=sealed_sha,
            expected_response_id_sha256=rid, expected_output_sha256=out_sha,
        )
        assert got is not None and got["sealed"] is True
    finally:
        timer.join()

    # 2. Unsealed progress state also waits cleanly until sealed.
    unsealed = {**base, "sealed": False, "sealed_at_ns": 0}
    _write_private_receipt(tmp_path, launch, unsealed)
    assert log_mod.review_from_receipt(
        tmp_path, launch, session, time.time() - 5, 0,
        expected_receipt_sha256=sealed_sha,
        expected_response_id_sha256=rid, expected_output_sha256=out_sha,
    ) is None

    timer2 = threading.Timer(0.03, seal_later)
    timer2.start()
    try:
        assert log_mod.review_from_receipt(
            tmp_path, launch, session, time.time() - 5, 0.5,
            expected_receipt_sha256=sealed_sha,
            expected_response_id_sha256=rid, expected_output_sha256=out_sha,
        ) is not None
    finally:
        timer2.join()

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
        _, bad_sha = _write_private_receipt(tmp_path, launch, {**base, **bad})
        assert log_mod.review_from_receipt(
            tmp_path, launch, session, time.time() - 5, 0,
            expected_receipt_sha256=bad_sha,
            expected_response_id_sha256=rid, expected_output_sha256=out_sha,
        ) is None

    # Permissive root/dir/file modes and symlinks MUST fail closed.
    path, receipt_sha = _write_private_receipt(tmp_path, launch, base)
    os.chmod(path, 0o644)
    assert log_mod.review_from_receipt(
        tmp_path, launch, session, time.time() - 5, 0,
        expected_receipt_sha256=receipt_sha, expected_response_id_sha256=rid, expected_output_sha256=out_sha,
    ) is None
    os.chmod(path, 0o600)
    os.chmod(path.parent, 0o755)
    assert log_mod.review_from_receipt(
        tmp_path, launch, session, time.time() - 5, 0,
        expected_receipt_sha256=receipt_sha, expected_response_id_sha256=rid, expected_output_sha256=out_sha,
    ) is None
    os.chmod(path.parent, 0o700)
    os.chmod(tmp_path, 0o755)
    assert log_mod.review_from_receipt(
        tmp_path, launch, session, time.time() - 5, 0,
        expected_receipt_sha256=receipt_sha, expected_response_id_sha256=rid, expected_output_sha256=out_sha,
    ) is None
    os.chmod(tmp_path, 0o700)

    target = tmp_path / "other.json"
    target.write_bytes(sealed_bytes)
    os.chmod(target, 0o600)
    path.unlink()
    path.symlink_to(target)
    assert log_mod.review_from_receipt(
        tmp_path, launch, session, time.time() - 5, 0,
        expected_receipt_sha256=receipt_sha, expected_response_id_sha256=rid, expected_output_sha256=out_sha,
    ) is None


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
        expected = [(f"codex:{model}", "chatgpt.com")]
        assert log_mod.route_from_receipt(root / name, session, since, 0.5) == expected
        assert preflight.route_from_host_receipt(
            str(root / name), session, since, 1, preflight.Deadline(3)
        ) == expected

    for name, launch, session, model in (
        ("review-codex-sol", "review-12345678-1234-4234-8234-123456789aa1", "019d0000-0000-7000-8000-000000000aa1", SOL),
        ("review-codex-astra", "review-12345678-1234-4234-8234-123456789aa2", "019d0000-0000-7000-8000-000000000aa2", ASTRA),
    ):
        raw = (root / name / launch / "receipt.json").read_bytes()
        payload = json.loads(raw)
        seal_resp = json.loads((root / name / launch / "seal-response.json").read_text(encoding="utf-8"))
        assert seal_resp == {
            "status": "sealed",
            "launch": launch,
            "session": session,
            "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        }
        assert payload["sealed"] is True
        since = payload["started_ns"] / 1e9
        got = log_mod.review_from_receipt(
            root / name, launch, session, since, 0.5,
            expected_receipt_sha256=seal_resp["receipt_sha256"],
            expected_response_id_sha256=payload["last_response_id_sha256"],
            expected_output_sha256=payload["last_output_sha256"],
            min_requests=2,
        )
        assert got is not None and got["routes"] == [(f"codex:{model}", "chatgpt.com")]
        assert got["requests"] == 2 and got["sealed"] is True
        assert len(got["response_id_sha256s"]) == 2 and got["response_id_sha256s"][-1] == got["last_response_id_sha256"]
        assert log_mod.review_from_receipt(
            root / name, launch, "019d0000-0000-7000-8000-000000000fff", since, 0,
            expected_receipt_sha256=seal_resp["receipt_sha256"],
            expected_response_id_sha256=payload["last_response_id_sha256"],
            expected_output_sha256=payload["last_output_sha256"],
            min_requests=2,
        ) is None
        assert log_mod.review_from_receipt(
            root / name, launch, session, since, 0,
            expected_response_id_sha256=payload["last_response_id_sha256"],
            expected_output_sha256=payload["last_output_sha256"],
            min_requests=2,
        ) is None

    tainted_launch = "review-12345678-1234-4234-8234-123456789aa3"
    tainted_session = "019d0000-0000-7000-8000-000000000aa3"
    tainted_raw = (root / "review-codex-tainted" / tainted_launch / "receipt.json").read_bytes()
    tainted_payload = json.loads(tainted_raw)
    assert tainted_payload["tainted"] is True and tainted_payload["complete"] is False and tainted_payload["sealed"] is False
    assert log_mod.review_from_receipt(
        root / "review-codex-tainted", tainted_launch, tainted_session, tainted_payload["started_ns"] / 1e9, 0,
        expected_receipt_sha256=hashlib.sha256(tainted_raw).hexdigest(),
        expected_response_id_sha256="a" * 64,
        expected_output_sha256="b" * 64,
    ) is None


def test_round_trip_http_accepts_multiline_sse_json_event(monkeypatch):
    """Go 严格 SSE 支持按空行拼接多行 JSON data，Python 往返探针必须保持同构。"""
    payload = (
        b"event: response.completed\n"
        b'data: {"type":"response.completed",\n'
        b'data: "response":{"status":"completed"}}\n'
        b"\n"
    )

    class _FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return payload

    monkeypatch.setattr(preflight.urllib.request, "urlopen", lambda *a, **kw: _FakeResp())
    result = preflight._round_trip_http("https://proxy.invalid", "k", SOL, "preflight-multiline", preflight.Deadline(5))
    assert result["ok"] is True
    assert result["terminal"] == "response.completed"
    assert result["status"] == "completed"


def test_round_trip_http_rejects_unclosed_multiline_sse_event(monkeypatch):
    payload = (
        b"event: response.completed\n"
        b'data: {"type":"response.completed",\n'
        b'data: "response":{"status":"completed"}}\n'
    )

    class _FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return payload

    monkeypatch.setattr(preflight.urllib.request, "urlopen", lambda *a, **kw: _FakeResp())
    result = preflight._round_trip_http("https://proxy.invalid", "k", SOL, "preflight-unclosed", preflight.Deadline(5))
    assert result["ok"] is False
    assert result["terminal"] is None


def test_round_trip_http_rejects_unclosed_trailing_event_after_completed(monkeypatch):
    payload = (
        b"event: response.completed\n"
        b'data: {"type":"response.completed","response":{"status":"completed"}}\n'
        b"\n"
        b'data: {"type":"response.failed","response":{"status":"failed"}}\n'
    )

    class _FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return payload

    monkeypatch.setattr(preflight.urllib.request, "urlopen", lambda *a, **kw: _FakeResp())
    result = preflight._round_trip_http("https://proxy.invalid", "k", SOL, "preflight-unclosed-tail", preflight.Deadline(5))
    assert result["ok"] is False


def test_round_trip_http_rejects_mismatched_event_header_and_orphan_event_at_eof(monkeypatch):
    """Sol P2 #3 + Astra P2 #4 (PR #2280 R12): 显式 event: 与 JSON type 冲突、或终态后残留未闭合 event: 头均拒绝。"""
    for payload in (
        (
            b"event: response.failed\n"
            b'data: {"type":"response.completed",\n'
            b'data: "response":{"status":"completed"}}\n\n'
        ),
        (
            b"event: response.completed\n"
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
            b"event: response.failed\n"
        ),
        (
            b"event: response.completed\n"
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
            b"event: response.failed\n"
            b"data: [DONE]\n\n"
        ),
        (
            b"event: response.completed\n"
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
            b"event: response.output_text.delta\n"
            b'data: {"type":"response.output_text.delta","delta":"trailing"}\n\n'
        ),
        (
            b"event: response.completed\n"
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
            b"data: [1]\n\n"
        ),
        (
            b"event: response.completed\n"
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
            b"data: extra\n\n"
        ),
        (
            b"event: response.completed\n"
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
            b'{"type":"error","error":{"message":"bare json tail"}}\n'
        ),
        (
            b"data: garbage-before-completed\n\n"
            b"event: response.completed\n"
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        ),
        (
            b"data: [1]\n\n"
            b"event: response.completed\n"
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        ),
        (
            b"data: [DONE]\n\n"
            b"event: response.completed\n"
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        ),
        (
            b'data: {"type":"response.failed","type":"response.completed","response":{"status":"completed"}}\n\n'
        ),
        (
            b'data: {"type":"response.completed","response":{"status":"failed","status":"completed"}}\n\n'
        ),
        (
            b'data: {"type":"response.in_progress","score":NaN}\n\n'
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        ),
        (
            b'data: {"type":"response.completed","response":{"status":"completed","score":Infinity}}\n\n'
        ),
        (
            b'data: {"type":"response.completed","response":{"status":"completed"}}\r\n\r\n'
            b': keepalive\rdata: {"type":"error","error":{"message":"cr-smuggled"}}\r\r'
        ),
        (
            b'data: {"type":"response.cancelled","response":{"status":"cancelled"}}\n\n'
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        ),
        (
            b'data: {"type":"response.canceled","response":{"status":"canceled"}}\n\n'
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        ),
        b'data: {"type":"response.completed","response":{"status":"in_progress"}}\n\n',
        b'data: {"type":"response.completed","response":{"status":"queued"}}\n\n',
        b'data: {"type":"response.completed","response":{"status":"unexpected"}}\n\n',
        b'data: {"type":"response.completed"}\n\n',
        b'data: {"type":"response.incomplete","response":{"status":"in_progress"}}\n\n',
        b'data: {"type":"response.completed","response":{"status":"completed","error":{}}}\n\n',
        b'data: {"type":"response.completed","error":{},"response":{"status":"completed"}}\n\n',
        b'data: {"type":"response.completed","response":{"status":"completed","error":""}}\n\n',
        (
            b'data: {"type":"response.in_progress","response":{"status":"in_progress","error":{}}}\n\n'
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        ),
        (
            b'data: {"type":"response.in_progress","error":{"message":"mid-stream"},"response":{"status":"in_progress"}}\n\n'
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        ),
        (
            b'data: {"type":"response.in_progress","response":{"status":"failed"}}\n\n'
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        ),
        (
            b'data: {"type":"response.in_progress","response":{"status":"incomplete"}}\n\n'
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        ),
        (
            b'data: {"type":"response.in_progress","response":{"status":"queued"}}\n\n'
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        ),
        (
            b'data: {"type":"response.created","response":{"status":"completed"}}\n\n'
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        ),
    ):
        class _FakeResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, _p=payload):
                return _p

        monkeypatch.setattr(preflight.urllib.request, "urlopen", lambda *a, **kw: _FakeResp())
        result = preflight._round_trip_http("https://proxy.invalid", "k", SOL, "preflight-ev-mismatch", preflight.Deadline(5))
        assert result["ok"] is False, payload

    # 允许合法 SSE 注释、id:、retry: 行
    valid_meta = (
        b": keepalive\n"
        b"id: 1\n"
        b"retry: 1000\n"
        b"event: response.completed\n"
        b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
    )

    class _ValidMetaResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return valid_meta

    monkeypatch.setattr(preflight.urllib.request, "urlopen", lambda *a, **kw: _ValidMetaResp())
    assert preflight._round_trip_http("https://proxy.invalid", "k", SOL, "preflight-valid-meta", preflight.Deadline(5))["ok"] is True


def test_receipt_readers_reject_symlinked_ancestor_directory(tmp_path):
    """Astra P2 #4 (PR #2280 R37): Python 收据读取端须与 Go 生产端一致，逐段 O_NOFOLLOW 拒绝祖先符号链接。"""
    import time

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    real_root = real_parent / "receipts"
    real_root.mkdir(mode=0o700)
    os.chmod(real_root, 0o700)

    sym_parent = tmp_path / "sym-parent"
    sym_parent.symlink_to(real_parent)
    sym_root = sym_parent / "receipts"

    now_ns = time.time_ns()
    since = now_ns / 1e9 - 5.0

    # 1. Legacy preflight receipt: succeeds via real_root, rejected via sym_root.
    pf_session = "preflight-aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeee1"
    pf_dir = real_root / pf_session
    pf_dir.mkdir(mode=0o700)
    os.chmod(pf_dir, 0o700)
    pf_path = pf_dir / "receipt.json"
    pf_path.write_bytes(json.dumps({
        "schema": log_mod.SCHEMA,
        "session": pf_session,
        "started_ns": now_ns,
        "finished_ns": now_ns,
        "complete": True,
        "routes": ["codex:gpt-6.2-sol@chatgpt.com"],
    }).encode("utf-8"))
    os.chmod(pf_path, 0o600)

    assert log_mod.route_from_receipt(real_root, pf_session, since, 0) == [("codex:gpt-6.2-sol", "chatgpt.com")]
    assert log_mod.route_from_receipt(sym_root, pf_session, since, 0) is None

    # 2. Sealed review receipt: succeeds via real_root, rejected via sym_root.
    rev_launch = "review-aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeee2"
    rev_session = "019d0000-0000-7000-8000-aaaaaaaaaaa2"
    resp_sha = hashlib.sha256(b"resp-sym-test").hexdigest()
    out_sha = hashlib.sha256(b"VERDICT: PASS").hexdigest()
    rev_dir = real_root / rev_launch
    rev_dir.mkdir(mode=0o700)
    os.chmod(rev_dir, 0o700)
    rev_raw = json.dumps({
        "schema": log_mod.REVIEW_SCHEMA,
        "launch": rev_launch,
        "session": rev_session,
        "started_ns": now_ns,
        "finished_ns": now_ns,
        "sealed_at_ns": now_ns,
        "complete": True,
        "sealed": True,
        "tainted": False,
        "requests": 1,
        "routes": ["codex:gpt-6.2-sol@chatgpt.com"],
        "response_id_sha256s": [resp_sha],
        "last_response_id_sha256": resp_sha,
        "last_output_sha256": out_sha,
    }).encode("utf-8")
    rev_path = rev_dir / "receipt.json"
    rev_path.write_bytes(rev_raw)
    os.chmod(rev_path, 0o600)
    rev_sha = hashlib.sha256(rev_raw).hexdigest()

    assert log_mod.review_from_receipt(
        real_root, rev_launch, rev_session, since, 0,
        expected_receipt_sha256=rev_sha,
        expected_response_id_sha256=resp_sha,
        expected_output_sha256=out_sha,
    ) is not None
    assert log_mod.review_from_receipt(
        sym_root, rev_launch, rev_session, since, 0,
        expected_receipt_sha256=rev_sha,
        expected_response_id_sha256=resp_sha,
        expected_output_sha256=out_sha,
    ) is None


def test_route_from_host_receipt_accepts_relative_path_and_rejects_symlink_ancestor(tmp_path, monkeypatch):
    """Astra P2 #4 (PR #2280 R38): --proxy-receipt-dir 传入 ./receipts 相对路径须正常工作，仍拒绝符号链接祖先。"""
    import time

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    real_root = real_parent / "receipts"
    real_root.mkdir(mode=0o700)
    os.chmod(real_root, 0o700)

    sym_parent = tmp_path / "sym-parent"
    sym_parent.symlink_to(real_parent)

    now_ns = time.time_ns()
    since = now_ns / 1e9 - 5.0
    pf_session = "preflight-bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeee1"
    pf_dir = real_root / pf_session
    pf_dir.mkdir(mode=0o700)
    os.chmod(pf_dir, 0o700)
    pf_path = pf_dir / "receipt.json"
    pf_path.write_bytes(json.dumps({
        "schema": log_mod.SCHEMA,
        "session": pf_session,
        "started_ns": now_ns,
        "finished_ns": now_ns,
        "complete": True,
        "routes": ["codex:gpt-6.2-sol@chatgpt.com"],
    }).encode("utf-8"))
    os.chmod(pf_path, 0o600)

    monkeypatch.chdir(real_parent)
    assert preflight.route_from_host_receipt(
        "./receipts", pf_session, since, 1.0, preflight.Deadline(5)
    ) == [("codex:gpt-6.2-sol", "chatgpt.com")]

    monkeypatch.chdir(tmp_path)
    assert preflight.route_from_host_receipt(
        "./sym-parent/receipts", pf_session, since, 1.0, preflight.Deadline(5)
    ) is None
    assert preflight.route_from_host_receipt(
        "./sym-parent/../real-parent/receipts", pf_session, since, 1.0, preflight.Deadline(5)
    ) is None
