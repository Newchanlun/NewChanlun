"""Journal.converge 写后读回的退避补读：只补读，不重发（#2027/#2028 状态读回滞后）。"""
import json

import pytest

from pilot1742.delivery import READBACK_DELAYS, EffectPending, Journal
from pilot1742.github_app import OutcomeUnknown


class Remote:
    """第 visible_from 次读回起才看得见效果；visible_from=None 表示一直看不见。"""

    def __init__(self, visible_from: int | None, *, fault: Exception | None = None):
        self.visible_from, self.fault = visible_from, fault
        self.probes = 0
        self.sends = 0

    def probe(self):
        self.probes += 1
        if self.sends and self.visible_from is not None and self.probes >= self.visible_from:
            return {"id": 7}
        return None

    def send(self):
        self.sends += 1
        if self.fault is not None:
            raise self.fault


def journal(tmp_path, slept):
    return Journal(tmp_path / "effects", sleep=slept.append)


def test_late_readback_converges_with_one_send(tmp_path):
    slept: list[float] = []
    remote = Remote(visible_from=4)  # 发前 1 次 + 写后第 1、2 次读回空，第 3 次读到
    result = journal(tmp_path, slept).converge("status-pending", remote.probe, remote.send,
                                               idempotent=False, what={})
    assert result == {"id": 7}
    assert remote.sends == 1 and remote.probes == 4
    assert slept == list(READBACK_DELAYS[:2])
    assert json.loads((tmp_path / "effects" / "status-pending.json").read_text())["state"] == "done"


def test_readback_never_visible_stays_pending_with_one_send(tmp_path):
    slept: list[float] = []
    remote = Remote(visible_from=None)
    with pytest.raises(EffectPending, match="已发出"):
        journal(tmp_path, slept).converge("status-pending", remote.probe, remote.send,
                                          idempotent=False, what={})
    assert remote.sends == 1 and remote.probes == 2 + len(READBACK_DELAYS)
    assert slept == list(READBACK_DELAYS) and sum(slept) <= 15
    assert json.loads((tmp_path / "effects" / "status-pending.json").read_text())["state"] == "pending"
    with pytest.raises(EffectPending, match="不自动重发"):
        journal(tmp_path, slept).converge("status-pending", remote.probe, remote.send,
                                          idempotent=False, what={})
    assert remote.sends == 1


def test_outcome_unknown_reads_back_once_without_backoff(tmp_path):
    slept: list[float] = []
    remote = Remote(visible_from=3, fault=OutcomeUnknown("模拟 5xx"))
    with pytest.raises(EffectPending, match="已发出"):
        journal(tmp_path, slept).converge("status-pending", remote.probe, remote.send,
                                          idempotent=False, what={})
    assert remote.sends == 1 and remote.probes == 2 and slept == []
