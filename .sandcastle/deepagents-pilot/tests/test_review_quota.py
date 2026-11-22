"""每日额度闸：超出上限时暂停新派发并显式报出；未设上限时不启用。"""
import json
import os
import sys
import time
from pathlib import Path

import pytest
from conftest import git
from test_external_review import (
    Gateway,
    _fake_preflight_pass,
    _make_fake_session_receipt,
)

from pilot1742 import external_review as module
from pilot1742.delivery import EffectPending
from pilot1742.external_review import (
    DAILY_INPUT_CAP_ENV,
    MODELS,
    UNREPORTED_TOKENS_PER_COMMAND,
    ExternalReview,
    ReviewTarget,
    validate_review,
)


def _receipt(root, run, model, tokens=None, *, usage=None, age=0.0):
    folder = root / "runs" / run / model
    folder.mkdir(parents=True, mode=0o700)
    path = folder / "receipt.json"
    path.write_text(json.dumps({"status": "completed", "usage": usage if usage is not None else {"input_tokens": tokens}}))
    os.chmod(path, 0o600)
    if age:
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
    return path


def test_quota_gate_pauses_with_explicit_reason(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    _receipt(root, "r1", "claude-opus-5-5", 4_000_000)
    _receipt(root, "r1", "kimi-k3.1-pro", 1_500_000)
    lane = ExternalReview(None, state_root=root)
    assert lane.recent_input_tokens() == 5_500_000
    monkeypatch.delenv(DAILY_INPUT_CAP_ENV, raising=False)
    lane.admit_quota()  # 未设上限：不启用
    monkeypatch.setenv(DAILY_INPUT_CAP_ENV, "10000000")
    lane.admit_quota()  # 未触顶
    monkeypatch.setenv(DAILY_INPUT_CAP_ENV, "5000000")
    with pytest.raises(EffectPending, match="quota-paused"):
        lane.admit_quota()


def test_window_and_unreadable_receipts(tmp_path):
    root = tmp_path.resolve()
    _receipt(root, "r1", "claude-opus-5-5", 1_000)
    _receipt(root, "r0", "claude-opus-5-5", 9_000_000, age=86400 + 60)  # 窗口外
    bad = _receipt(root, "r2", "claude-opus-5-5", 7_000_000)
    os.chmod(bad, 0o666)  # 权限不符的回执读不了：跳过，不让闸报错
    legacy = root / "runs" / "r3" / "kimi-k3.1-pro"
    legacy.mkdir(parents=True, mode=0o700)
    (legacy / "receipt.json").write_text(json.dumps({"status": "failed"}))  # 闸上线前的旧回执：无 usage
    os.chmod(legacy / "receipt.json", 0o600)
    assert ExternalReview(None, state_root=root).recent_input_tokens() == 1_000


def test_stopped_review_without_reported_usage_is_estimated_not_zero(tmp_path):
    """被关停的独审（触顶、超时）没收到 turn.completed：worker 记 reported=false，闸按命令数估算。"""
    root = tmp_path.resolve()
    _receipt(root, "r1", "claude-opus-5-5", usage={"input_tokens": 0, "commands": 251, "reported": False})
    lane = ExternalReview(None, state_root=root)
    assert lane.recent_input_tokens() == 251 * UNREPORTED_TOKENS_PER_COMMAND  # 无样本：取实测每请求约 10 万
    _receipt(root, "r2", "kimi-k3.1-pro", usage={"input_tokens": 2_000_000, "commands": 40, "reported": True})
    assert lane.recent_input_tokens() == 2_000_000 + 251 * 50_000  # 有样本：用窗口内实测的「输入/命令」
    _receipt(root, "r3", "kimi-k3.1-pro", usage={"input_tokens": 0, "commands": 0, "reported": False})
    assert lane.recent_input_tokens() == 2_000_000 + 252 * 50_000  # 零命令就被停的也至少记一次请求


@pytest.mark.parametrize("raw", ["0", "-5", "1e9", "0.5G", "abc"])
def test_invalid_cap_fails_closed_with_variable_name(tmp_path, monkeypatch, raw):
    monkeypatch.setenv(DAILY_INPUT_CAP_ENV, raw)
    with pytest.raises(ValueError, match=DAILY_INPUT_CAP_ENV):
        ExternalReview(None, state_root=tmp_path.resolve()).admit_quota()


def test_cap_accepts_underscore_grouping(tmp_path, monkeypatch):
    monkeypatch.setenv(DAILY_INPUT_CAP_ENV, "400_000_000")
    ExternalReview(None, state_root=tmp_path.resolve()).admit_quota()


@pytest.fixture
def lane(env, monkeypatch):
    for i in range(2):
        (env.source / f"changed-{i}").write_text(str(i))
        git(env.source, "add", ".")
        git(env.source, "commit", "-qm", f"change-{i}")
    monkeypatch.setattr(module, "SOURCE_REPO", env.source)
    return ExternalReview(Gateway(env), source=env.source, state_root=env.home / "review",
                          checkout_root=env.home / "clones", poll_seconds=0.01,
                          launcher=[sys.executable, str(Path(__file__).with_name("external_review_child.py"))],
                          preflight=_fake_preflight_pass,
                          session_receipt=_make_fake_session_receipt(env.home / "review"))


def _launches(lane):
    path = lane.state_root / "runs" / "launches"
    return path.read_text().splitlines() if path.exists() else []


def test_recovery_with_worker_dir_but_no_launch_still_passes_quota_gate(lane, monkeypatch):
    """恢复路径：worker 目录在（prepare 中断）不等于已派发；本 run 仍要派新模型，必须先过额度闸。"""
    target = lane.target(1810, 1)
    (lane.state_root / "runs" / target.key / MODELS[0]).mkdir()
    _receipt(lane.state_root, "r-earlier", MODELS[1], 9_000_000)
    monkeypatch.setenv(DAILY_INPUT_CAP_ENV, "1000000")
    with pytest.raises(EffectPending, match="quota-paused"):
        lane.review_pr(1810)
    assert _launches(lane) == []  # 未派任何模型
    monkeypatch.delenv(DAILY_INPUT_CAP_ENV)
    assert lane.review_pr(1810)["verdict"] == "PASS"  # 额度回落后同一 attempt 续跑
    assert sorted(_launches(lane)) == sorted(MODELS)


def test_recovery_after_first_reviewer_dispatched_pauses_second(lane, monkeypatch):
    """第一位已派发并完成、第二位尚未派发：额度触顶时不派第二位（kimi 回执的场景）。"""
    real = lane.run_review
    def first_only(target, model, folder):
        if model == MODELS[1]:
            raise KeyboardInterrupt("中断在第二位派发前")
        return real(target, model, folder)
    monkeypatch.setattr(lane, "run_review", first_only)
    target = lane.target(1810, 1)
    folder = lane.state_root / "runs" / target.key
    (folder / MODELS[0]).mkdir(parents=True)  # 以恢复（串行）方式跑，第一位真实派发
    with pytest.raises(KeyboardInterrupt):
        lane.review_pr(1810)
    assert _launches(lane) == [MODELS[0]]
    assert (folder / MODELS[0] / "launch.json").exists() and not (folder / MODELS[1] / "launch.json").exists()
    monkeypatch.setattr(lane, "run_review", real)
    _receipt(lane.state_root, "r-earlier", MODELS[1], 9_000_000)
    monkeypatch.setenv(DAILY_INPUT_CAP_ENV, "1000000")
    with pytest.raises(EffectPending, match="quota-paused"):
        lane.review_pr(1810)
    assert _launches(lane) == [MODELS[0]]  # 第二位没有被派发


def test_failure_code_is_visible_in_review_outcome(lane):
    """触顶、超时的原因码要进 outcome 的 reason（status 子命令可见），不折成笼统的「监督失败」。"""
    result = lane.review_pr(1810)
    target = ReviewTarget(**result["target"])
    folder = lane.state_root / "runs" / target.key / MODELS[0]
    launch = json.loads((folder / "launch.json").read_text())
    receipt = json.loads((folder / "receipt.json").read_text())
    receipt.update(status="failed", failure_code="budget_exceeded")
    outcome = validate_review(target, launch, receipt, folder, lane.source)
    assert outcome.verdict == "FAILED" and "failure_code=budget_exceeded" in outcome.reason


def test_quota_gate_blocks_before_paid_preflight_on_new_attempt(lane, monkeypatch):
    """每日额度已触顶时，新 PR 在付费预检前即被拦下：零预检请求、不占 attempt、不发状态。"""
    _receipt(lane.state_root, "r-earlier", MODELS[0], 9_000_000)
    monkeypatch.setenv(DAILY_INPUT_CAP_ENV, "1000000")
    preflight_calls = []
    lane.preflight = lambda t: (preflight_calls.append(t.head_sha), _fake_preflight_pass(t))[1]
    with pytest.raises(EffectPending, match="quota-paused"):
        lane.review_pr(1810, 1)
    assert preflight_calls == [] and lane.status(1810) == [] and lane.gateway.sent == []


def test_failed_preflight_probes_accumulate_into_recent_input_tokens_and_trip_quota(lane, monkeypatch):
    """R19（Astra P2）：预检发出上游往返探针后因封存/收据等后续项失败时，仍须折算输入 token 计入 24h 额度并在触顶后触发 quota-paused；
    未发出探针（not_sent 或前置检查失败）的预检记 0。"""
    no_send_report = {
        "returncode": 2,
        "image_id": "sha256:" + "1" * 64,
        "report": {
            "kind": "review-preflight", "is_review_result": False, "ready": False,
            "checks": [
                {"name": "models", "ok": False, "detail": {"reason": "down"}},
                {"name": "roundtrip:gpt-6.2-sol", "ok": False, "detail": {"error": {"not_sent": "总时限已到"}}},
            ],
        },
    }
    lane.preflight = lambda _t: no_send_report
    with pytest.raises(EffectPending, match="preflight-blocked"):
        lane.target(1810, 1)
    assert lane.recent_input_tokens() == 0

    sent_then_seal_failed = {
        "returncode": 2,
        "image_id": "sha256:" + "1" * 64,
        "report": {
            "kind": "review-preflight", "is_review_result": False, "ready": False,
            "checks": [
                {"name": "roundtrip:gpt-6.2-sol", "ok": True, "detail": {"http_status": 200, "returned_model": "gpt-6.2-sol"}},
                {"name": "roundtrip:gpt-6.2-astra", "ok": True, "detail": {"http_status": 200, "returned_model": "gpt-6.2-astra"}},
                {"name": "seal:gpt-6.2-sol", "ok": False, "detail": {"reason": "unavailable"}},
            ],
        },
    }
    calls = []
    lane.preflight = lambda t: (calls.append(t.head_sha), sent_then_seal_failed)[1]
    cap = 3 * 2 * module.PREFLIGHT_TOKENS_PER_PROBE
    monkeypatch.setenv(DAILY_INPUT_CAP_ENV, str(cap))
    for _ in range(3):
        with pytest.raises(EffectPending, match="preflight-blocked"):
            lane.target(1810, 1)
    assert len(calls) == 3
    assert lane.recent_input_tokens() == cap
    with pytest.raises(EffectPending, match="quota-paused"):
        lane.target(1810, 1)
    assert len(calls) == 3


def test_real_preflight_missing_creds_charges_zero_and_internal_error_preserves_probes_sent(lane, monkeypatch, capsys):
    """R20（Sol P2 / Astra P2）：用 review_preflight.main 真实输出报告回归两条路径：
    1) 凭据缺失未启动探针时，预检报告带 sent=False/not_sent，额度记 0，绝不因重试耗尽本地额度；
    2) 已启动探针后主流程抛内部异常（preflight_internal）时，报告保留 probes_sent，额度照实计入。"""
    import review_preflight

    head = lane.gateway.pr["head"]["sha"]
    base = lane.gateway.pr["base"]["sha"]
    argv = [
        "--source", str(lane.source),
        "--base", base, "--head", head, "--merge-base", base,
        "--checkout-root", str(lane.checkout_root),
        "--credential-mode", "worker-env",
        "--deadline", "10",
    ]
    monkeypatch.setattr(review_preflight, "check_credential", lambda _a, _d: (
        {"name": "credential", "class": "credential", "ok": False, "detail": "missing"}, None
    ))
    monkeypatch.setattr(review_preflight, "check_space", lambda _a, _d: {
        "name": "checkout_root_free_space", "class": "space", "ok": True, "detail": {},
    })
    monkeypatch.setattr(review_preflight, "check_mount", lambda _a, _d: (
        {"name": "mount", "class": "mount", "ok": True, "detail": {}}, []
    ))
    rc = review_preflight.main(argv)
    assert rc == 2
    missing_report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    lane.preflight = lambda _t: {"returncode": rc, "report": missing_report, "image_id": "sha256:" + "1" * 64}
    for _ in range(3):
        with pytest.raises(EffectPending, match="preflight-blocked"):
            lane.target(1810, 1)
    assert lane.recent_input_tokens() == 0

    # 模拟凭据有效、已启动两路探针线程，随后 check_mount 抛出未预期内部异常进入 preflight_internal
    monkeypatch.setattr(review_preflight, "check_credential", lambda _a, _d: (
        {"name": "credential", "class": "credential", "ok": True, "detail": {}}, "fake-key"
    ))
    monkeypatch.setattr(review_preflight, "probe_model", lambda _a, m, _k, _d, _c=None: [
        {"name": f"roundtrip:{m}", "class": "roundtrip", "ok": True, "detail": {"http_status": 200, "sent": True}}
    ])
    monkeypatch.setattr(review_preflight, "check_mount", lambda _a, _d: (_ for _ in ()).throw(RuntimeError("boom")))
    rc2 = review_preflight.main(argv)
    assert rc2 == 2
    crash_report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert crash_report["checks"][0]["name"] == "preflight_internal"
    assert crash_report["checks"][0]["detail"]["probes_sent"] == len(MODELS)
    lane.preflight = lambda _t: {"returncode": rc2, "report": crash_report, "image_id": "sha256:" + "1" * 64}
    with pytest.raises(EffectPending, match="preflight-blocked"):
        lane.target(1810, 1)
    assert lane.recent_input_tokens() == len(MODELS) * module.PREFLIGHT_TOKENS_PER_PROBE


def test_container_start_failure_marks_not_sent_and_charges_zero_tokens(lane, monkeypatch):
    """R21（Astra P2）：docker run 退出码 125/126/127 或 OSError 表示容器探针确定未启动，
    round_trip 须报 error.not_sent，额度统计计 0，反复重试不会耗尽当日审阅额度。"""
    import subprocess

    import review_preflight

    for exit_code in (125, 126, 127):
        monkeypatch.setattr(
            review_preflight, "run_bounded",
            lambda _cmd, _t, ec=exit_code, **kw: subprocess.CompletedProcess([], ec, b"", b"docker failed"),
        )
        trip = review_preflight.round_trip(
            module.FORMAL_PROXY_URL, "k", MODELS[0], "preflight-12345678-1234-4234-8234-123456789abc",
            review_preflight.Deadline(10), container_image="sha256:" + "1" * 64,
        )
        assert trip["ok"] is False and "not_sent" in trip["error"]
        report = {
            "kind": "review-preflight", "is_review_result": False, "ready": False,
            "checks": [{"name": f"roundtrip:{MODELS[0]}", "class": "roundtrip", "ok": False,
                        "detail": {**trip, "sent": False}}],
        }
        lane.preflight = lambda _t, rep=report: {"returncode": 2, "report": rep, "image_id": "sha256:" + "1" * 64}
        with pytest.raises(EffectPending, match="preflight-blocked"):
            lane.target(1810, 1)
    assert lane.recent_input_tokens() == 0

    def raise_oserror(_cmd, _t, **kw):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(review_preflight, "run_bounded", raise_oserror)
    trip_os = review_preflight.round_trip(
        module.FORMAL_PROXY_URL, "k", MODELS[0], "preflight-12345678-1234-4234-8234-123456789abc",
        review_preflight.Deadline(10), container_image="sha256:" + "1" * 64,
    )
    assert trip_os["ok"] is False and "not_sent" in trip_os["error"]


def test_preflight_usage_ledger_fails_closed_when_daily_cap_enabled(tmp_path, monkeypatch):
    """R22（Astra P2）：启用 DAILY_INPUT_CAP_ENV 时，预检用量账本缺失计 0；但一旦存在且权限不符、为符号链接、
    损坏或写入失败，admit_quota / _record_preflight_usage 必须以 quota-unverifiable 失败闭合，绝不静默折算为 0。"""
    root = tmp_path.resolve()
    lane = ExternalReview(None, state_root=root)
    monkeypatch.setenv(DAILY_INPUT_CAP_ENV, "1000000")
    lane.admit_quota()  # 文件不存在时正常按 0 放行

    usage_path = root / module.PREFLIGHT_USAGE_FILE
    # 1. 权限过宽（0o644）-> admit_quota 与 _record_preflight_usage 均失败闭合
    usage_path.write_text(json.dumps({"at": time.time(), "probes": 2, "tokens": 8192}) + "\n", encoding="utf-8")
    os.chmod(usage_path, 0o644)
    with pytest.raises(EffectPending, match="quota-unverifiable"):
        lane.admit_quota()
    with pytest.raises(EffectPending, match="quota-unverifiable"):
        lane._record_preflight_usage(2)

    # 2. 损坏 JSON 行 -> 失败闭合
    os.chmod(usage_path, 0o600)
    usage_path.write_text("{corrupt\n", encoding="utf-8")
    with pytest.raises(EffectPending, match="quota-unverifiable"):
        lane.admit_quota()

    # 3. 符号链接 -> 失败闭合
    target_file = root / "real.jsonl"
    target_file.write_text(json.dumps({"at": time.time(), "probes": 1, "tokens": 4096}) + "\n", encoding="utf-8")
    os.chmod(target_file, 0o600)
    usage_path.unlink()
    usage_path.symlink_to(target_file)
    with pytest.raises(EffectPending, match="quota-unverifiable"):
        lane.admit_quota()
    with pytest.raises(EffectPending, match="quota-unverifiable"):
        lane._record_preflight_usage(1)

    # 4. 未启用每日额度闸时，不因损坏账本阻断主流程
    monkeypatch.delenv(DAILY_INPUT_CAP_ENV)
    lane._record_preflight_usage(1)
    lane.admit_quota()
