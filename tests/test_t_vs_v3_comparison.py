"""#1385 / #951：analysis/t_vs_v3_comparison.py 合同测试。

覆盖：
- 仅向需资金记录的 v3 核（OE10 FugueV3Stream）显式透传签署资金，不为缺资金选默认，不为纯 T 路径（OE11 run_recursive_t）造资金前置；
- 保留旧位置参数 symbols/max_bars 与 --diag 不写报告；
- 默认调用在显式提供资金后直接可用，新报告落 runs/<run_id>/T_vs_v3_comparison.md，不改历史原件且他次运行互不覆盖；
- 新报告携带 ADR 0039 §四.4 观察出处（两核身份、单次 run_id、清洗/截断后两臂共享输入 hash、已选条件、无准入效力）；
- 缺输入、缺资金、未映射或部分标的失败时明确区分成功/失败并以非 0 退出，不把陈旧报告当新结果。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import struct
import sys
import types
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "analysis" / "t_vs_v3_comparison.py"


def _extract_provenance_json(md_text: str) -> dict:
    match = re.search(r"```json\n(.*?)\n```", md_text, flags=re.DOTALL)
    assert match is not None, "报告缺少 JSON 出处块"
    return json.loads(match.group(1))


def _load_comparison_module(monkeypatch, tmp_path: Path):
    """在隔离 stub 下加载真实 analysis/t_vs_v3_comparison.py 源码。"""
    records = {
        "P0": ("#1557/funding-authorization/v1@P0/v1", 100_000),
        "P1-hl-testnet": ("#1557/funding-authorization/v1@P1-hl-testnet/v1", 500),
    }
    state = {
        "t_inputs": [],
        "v3_inputs": [],
        "v3_init_calls": [],
        "organic_calls": 0,
    }

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.bars = []

        def process_bar(self, o, h, l, c):
            self.bars.append((o, h, l, c))

        def current_segments(self):
            state["t_inputs"].append(list(self.bars))
            if not self.bars:
                return []
            high = max(b[1] for b in self.bars)
            low = min(b[2] for b in self.bars)
            return [((0, 1, 0, len(self.bars) - 1, "up", high, low, True, "settled"),)]

    def fake_run_recursive_t(seg_in):
        assert len(seg_in) >= 1
        high = seg_in[0][3]
        low = seg_in[0][4]
        return [
            ("type1_sell", 1, high, 0),
            ("type1_buy", 0, low, 0),
            ("type2_buy", 1, low, 0),
        ]

    class FakeFugueV3Stream:
        def __init__(self, floor_ladder=2, funding_profile=None):
            state["v3_init_calls"].append(
                {"floor_ladder": floor_ladder, "funding_profile": funding_profile}
            )
            if funding_profile not in records:
                profile = "<未指定 funding_profile>" if funding_profile is None else funding_profile
                raise ValueError(
                    f"AwaitingPolicy{{funding_record, profile={profile}}}：无签署记录，停止（不回退任何备用值）"
                )
            self.floor_ladder = floor_ladder
            self.funding_record, self.q_total = records[funding_profile]
            self.pushed = []

        def finish(self):
            high = max(self.pushed) if self.pushed else 0.0
            low = min(self.pushed) if self.pushed else 0.0
            return {
                "nf_fires": [(0, 3, False, low), (max(len(self.pushed) - 1, 0), 3, True, high)],
                "funding_record": self.funding_record,
                "q_total": self.q_total,
            }

    fake_rust = types.ModuleType("newchan_rust")
    fake_rust.RecursiveOrchestrator = FakeOrchestrator
    fake_rust.run_recursive_t = fake_run_recursive_t
    fake_rust.FugueV3Stream = FakeFugueV3Stream
    monkeypatch.setitem(sys.modules, "newchan_rust", fake_rust)

    def fake_compute_organic_signals(opens, highs, lows, closes, *, dir_flips=None, require_settled=True):
        state["organic_calls"] += 1
        state["v3_inputs"].append(list(zip(opens, highs, lows, closes)))
        return list(closes)

    def fake_push_signal(stream, s, flips):
        stream.pushed.append(s)

    fake_org = types.ModuleType("organic_signals")
    fake_org.compute_organic_signals = fake_compute_organic_signals
    fake_org.push_signal = fake_push_signal
    monkeypatch.setitem(sys.modules, "organic_signals", fake_org)

    data_oklo = tmp_path / "oklo.json"
    data_oklo.write_text(
        json.dumps(
            {
                "bars": [
                    {"ts": "2025-01-01T00:00:00Z", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5},
                    {"ts": "2025-01-01T00:01:00Z", "open": -1.0, "high": 11.0, "low": 9.5, "close": 10.5},
                    {"ts": "2025-01-01T00:02:00Z", "open": 10.5, "high": 12.0, "low": 10.0, "close": 11.5},
                    {"ts": "2025-01-01T00:03:00Z", "open": 11.5, "high": 12.5, "low": 11.0, "close": 12.0},
                    {"ts": "2025-01-01T00:04:00Z", "open": 12.0, "high": 13.0, "low": 11.5, "close": 12.5},
                    {"ts": "2025-01-01T00:05:00Z", "open": 12.5, "high": 13.5, "low": 12.0, "close": 13.0},
                    {"ts": "2025-01-01T00:06:00Z", "open": 13.0, "high": 14.0, "low": 12.5, "close": 13.5},
                ]
            }
        ),
        encoding="utf-8",
    )
    data_empty = tmp_path / "empty.json"
    data_empty.write_text(
        json.dumps({"opens": [-1.0, 0.0], "highs": [1.0, 1.0], "lows": [1.0, 1.0], "closes": [1.0, 1.0]}),
        encoding="utf-8",
    )
    data_missing = tmp_path / "missing_es.json"

    def fake_load_ohlc(path: Path):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if "bars" in raw:
            bars = raw["bars"]
            o_in = [b["open"] for b in bars]
            h_in = [b["high"] for b in bars]
            l_in = [b["low"] for b in bars]
            c_in = [b["close"] for b in bars]
        else:
            o_in, h_in, l_in, c_in = raw["opens"], raw["highs"], raw["lows"], raw["closes"]
        opens, highs, lows, closes = [], [], [], []
        for o, h, l, c in zip(o_in, h_in, l_in, c_in):
            if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                continue
            opens.append(float(o))
            highs.append(float(h))
            lows.append(float(l))
            closes.append(float(c))
        return opens, highs, lows, closes, None

    fake_v2 = types.ModuleType("fugue_v2_full_backtest")
    fake_v2.SYMBOL_FILES = {
        "OKLO": data_oklo,
        "EMPTY": data_empty,
        "ES": data_missing,
    }
    fake_v2.load_ohlc = fake_load_ohlc
    monkeypatch.setitem(sys.modules, "fugue_v2_full_backtest", fake_v2)

    spec = importlib.util.spec_from_file_location("_test_t_vs_v3_comparison", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # 将历史原件路径指向 tmp_path 下隔离副本，防止测试写入真实仓库目录。
    hist_md = tmp_path / "T_vs_v3_comparison.md"
    hist_md.write_text("# 历史 8 标的归档原件（未签名）\n", encoding="utf-8")
    monkeypatch.setattr(mod, "OUT_MD", hist_md)
    monkeypatch.delenv("NC_FUNDING_PROFILE", raising=False)
    monkeypatch.delenv("BT_MAX_BARS", raising=False)
    return mod, state, hist_md


def test_pure_t_arm_has_no_funding_prerequisite(monkeypatch, tmp_path):
    mod, state, _hist = _load_comparison_module(monkeypatch, tmp_path)
    bsps, n_segs = mod.extract_t_bsps((10.0, 11.0), (11.0, 12.0), (9.5, 10.5), (10.5, 11.5))
    assert n_segs == 1
    assert len(bsps) == 3
    assert state["v3_init_calls"] == []


def test_missing_funding_fails_v3_without_default_and_exits_nonzero(monkeypatch, tmp_path, capsys):
    mod, state, hist_md = _load_comparison_module(monkeypatch, tmp_path)
    hist_before = hist_md.read_bytes()

    rc = mod.main(["OKLO", "5"])
    out = capsys.readouterr()

    assert rc == 1
    assert state["v3_init_calls"] == [{"floor_ladder": 2, "funding_profile": None}]
    assert state["organic_calls"] == 0, "缺资金应在构造 FugueV3Stream 时立即失败"
    assert "AwaitingPolicy{funding_record" in out.err
    assert "未写入新报告" in out.err
    assert hist_md.read_bytes() == hist_before
    assert not (tmp_path / "runs").exists()


def test_default_cli_with_funding_preserves_historical_and_separates_runs(
    monkeypatch, tmp_path, capsys
):
    mod, state, hist_md = _load_comparison_module(monkeypatch, tmp_path)
    hist_before = hist_md.read_bytes()
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")

    rc1 = mod.main(["OKLO", "5"])
    out1 = capsys.readouterr()
    rc2 = mod.main(["OKLO", "5"])
    out2 = capsys.readouterr()

    assert rc1 == 0
    assert rc2 == 0
    assert hist_md.read_bytes() == hist_before

    reports = sorted((tmp_path / "runs").glob("*/T_vs_v3_comparison.md"))
    assert len(reports) == 2
    assert reports[0].parent.name != reports[1].parent.name

    for report, captured in zip(reports, (out1, out2)):
        assert str(report.resolve()) in captured.out or any(
            str(r.resolve()) in captured.out for r in reports
        )

    p1 = _extract_provenance_json(reports[0].read_text(encoding="utf-8"))
    p2 = _extract_provenance_json(reports[1].read_text(encoding="utf-8"))

    assert UUID(p1["run_id"]).version == 4
    assert UUID(p2["run_id"]).version == 4
    assert p1["run_id"] != p2["run_id"]
    assert p1["run_id"] == reports[0].parent.name
    assert p2["run_id"] == reports[1].parent.name

    # 两臂使用同一份清洗/截断后输入，且两次运行除 run_id 外出处与报告正文全等。
    assert state["t_inputs"][0] == state["v3_inputs"][0]
    assert len(state["t_inputs"][0]) == 5

    expected_digest = hashlib.sha256(
        b"".join(struct.pack(">dddd", *bar) for bar in state["t_inputs"][0])
    ).hexdigest()
    assert p1["inputs"]["OKLO"]["input_hash"] == f"sha256:{expected_digest}"
    assert p1["inputs"]["OKLO"]["input_count"] == 5
    assert p1["inputs"]["OKLO"]["input_encoding"] == "ohlc-f64be/1"
    assert p1["inputs"]["OKLO"]["shared_by_arms"] == ["t_arm", "v3_arm"]
    assert p1["cores"]["t_arm"]["core_id"] == "recursive_t::iterate"
    assert p1["cores"]["t_arm"]["funding_required"] is False
    assert p1["cores"]["v3_arm"]["core_id"] == "fugue_v3::engine::FugueEngineCore"
    assert p1["cores"]["v3_arm"]["funding_record"] == "#1557/funding-authorization/v1@P0/v1"
    assert p1["cores"]["v3_arm"]["q_total"] == 100_000
    assert p1["role"] == "frozen_shadow_research_comparison"
    assert p1["admission_effect"] == "none"
    assert p1["run_status"] == "complete"

    t1 = reports[0].read_text(encoding="utf-8").replace(p1["run_id"], "<RUN_ID>")
    t2 = reports[1].read_text(encoding="utf-8").replace(p2["run_id"], "<RUN_ID>")
    assert t1 == t2


def test_changed_input_changes_input_hash(monkeypatch, tmp_path):
    mod, _state, _hist = _load_comparison_module(monkeypatch, tmp_path)
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")

    assert mod.main(["OKLO", "6"]) == 0
    assert mod.main(["OKLO", "5"]) == 0

    reports = sorted((tmp_path / "runs").glob("*/T_vs_v3_comparison.md"))
    assert len(reports) == 2
    provs = [_extract_provenance_json(r.read_text(encoding="utf-8")) for r in reports]
    counts = {p["inputs"]["OKLO"]["input_count"]: p["inputs"]["OKLO"]["input_hash"] for p in provs}
    assert set(counts.keys()) == {5, 6}
    assert counts[5] != counts[6]


def test_diag_mode_writes_no_report_and_respects_intermixed_positionals(
    monkeypatch, tmp_path, capsys
):
    mod, _state, hist_md = _load_comparison_module(monkeypatch, tmp_path)
    hist_before = hist_md.read_bytes()

    rc = mod.main(["--diag", "OKLO", "5", "--funding-profile", "P1-hl-testnet"])
    out = capsys.readouterr()

    assert rc == 0
    assert "--diag 模式：未写入报告" in out.out
    assert "q_total=500" in out.out
    assert not (tmp_path / "runs").exists()
    assert hist_md.read_bytes() == hist_before


def test_partial_failure_identifies_success_and_failure_and_exits_nonzero(
    monkeypatch, tmp_path, capsys
):
    mod, _state, hist_md = _load_comparison_module(monkeypatch, tmp_path)
    hist_before = hist_md.read_bytes()
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")

    rc = mod.main(["OKLO,ES,NO_SUCH_SYM", "5"])
    out = capsys.readouterr()

    assert rc == 1
    assert hist_md.read_bytes() == hist_before
    assert "成功=1/3 (OKLO)" in out.out
    assert "失败=2/3 (ES,NO_SUCH_SYM)" in out.out
    assert "部分成功" in out.err

    reports = list((tmp_path / "runs").glob("*/T_vs_v3_comparison.md"))
    assert len(reports) == 1
    md_text = reports[0].read_text(encoding="utf-8")
    prov = _extract_provenance_json(md_text)
    assert prov["run_status"] == "partial"
    assert prov["selected_conditions"]["succeeded_symbols"] == ["OKLO"]
    assert [f["symbol"] for f in prov["selected_conditions"]["failed_symbols"]] == [
        "ES",
        "NO_SUCH_SYM",
    ]
    assert "## 失败标的（本次未产出对照行）" in md_text
    assert "## OKLO" in md_text


def test_empty_input_and_unmapped_and_empty_symbols_fail_nonzero(monkeypatch, tmp_path):
    mod, _state, hist_md = _load_comparison_module(monkeypatch, tmp_path)
    hist_before = hist_md.read_bytes()
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")

    assert mod.main(["EMPTY", "5"]) == 1
    assert mod.main(["NO_SUCH_SYM", "5"]) == 1
    assert mod.main([","]) == 1
    assert not (tmp_path / "runs").exists()
    assert hist_md.read_bytes() == hist_before


def test_explicit_empty_cli_funding_profile_does_not_fallback_to_env(monkeypatch, tmp_path):
    mod, state, _hist = _load_comparison_module(monkeypatch, tmp_path)
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")

    rc = mod.main(["OKLO", "5", "--funding-profile", ""])
    assert rc == 1
    assert state["v3_init_calls"] == [{"floor_ladder": 2, "funding_profile": ""}]
    assert not (tmp_path / "runs").exists()


def test_bt_max_bars_env_recorded_in_selected_conditions(monkeypatch, tmp_path):
    mod, _state, _hist = _load_comparison_module(monkeypatch, tmp_path)
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")
    monkeypatch.setenv("BT_MAX_BARS", "42")

    assert mod.main(["OKLO", "5"]) == 0
    reports = list((tmp_path / "runs").glob("*/T_vs_v3_comparison.md"))
    assert len(reports) == 1
    md = reports[0].read_text(encoding="utf-8")
    assert "BT_MAX_BARS=42" in md
    prov = _extract_provenance_json(md)
    assert prov["selected_conditions"]["bt_max_bars_env"] == "42"
