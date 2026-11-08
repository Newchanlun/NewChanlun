"""每日额度闸：超出上限时暂停新派发并显式报出；未设上限时不启用。"""
import json
import os

import pytest

from pilot1742.delivery import EffectPending
from pilot1742.external_review import DAILY_INPUT_CAP_ENV, ExternalReview


def _receipt(root, run, model, tokens):
    folder = root / "runs" / run / model
    folder.mkdir(parents=True, mode=0o700)
    path = folder / "receipt.json"
    path.write_text(json.dumps({"status": "completed", "usage": {"input_tokens": tokens}}))
    os.chmod(path, 0o600)


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
