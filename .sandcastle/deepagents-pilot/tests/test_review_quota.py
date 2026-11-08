"""每日额度闸：超出上限时暂停新派发并显式报出；未设上限时不启用。"""
import json
import os
import sys
import time
from pathlib import Path

import pytest
from conftest import git
from test_external_review import Gateway

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
                          launcher=[sys.executable, str(Path(__file__).with_name("external_review_child.py"))])


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
    outcome = validate_review(target, launch, receipt, folder)
    assert outcome.verdict == "FAILED" and "failure_code=budget_exceeded" in outcome.reason
