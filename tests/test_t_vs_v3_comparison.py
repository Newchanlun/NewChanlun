"""#1385 / #951：analysis/t_vs_v3_comparison.py 合同测试。

覆盖：
- 仅向需资金记录的 v3 核（OE10 FugueV3Stream）显式透传签署资金，不为缺资金选默认，不为纯 T 路径（OE11 run_recursive_t）造资金前置；
- 保留旧位置参数 symbols/max_bars 与 --diag 不写报告；
- 默认调用在显式提供资金后直接可用，新报告落 runs/<run_id>/T_vs_v3_comparison.md，不改历史原件且他次运行互不覆盖；
- 新报告携带 ADR 0039 §四.4 观察出处（两核身份、单次 run_id、清洗/截断后两臂共享输入 hash、已选条件、无准入效力）；
- 缺输入、缺资金、未映射或部分标的失败时明确区分成功/失败并以非 0 退出，不把陈旧报告当新结果。
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
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


def _load_comparison_module(
    monkeypatch,
    tmp_path: Path,
    *,
    nf_fires_fn=None,
    t_bsps_fn=None,
):
    """在隔离 stub 下加载真实 analysis/t_vs_v3_comparison.py 源码。"""
    records = {
        "P0": ("#1557/funding-authorization/v1@P0/v1", 100_000),
        "P1-hl-testnet": ("#1557/funding-authorization/v1@P1-hl-testnet/v1", 500),
    }
    state = {
        "t_inputs": [],
        "t_orch_kwargs": [],
        "v3_inputs": [],
        "v3_init_calls": [],
        "organic_calls": 0,
        "organic_kwargs": [],
    }

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            self.kwargs = dict(kwargs)
            state["t_orch_kwargs"].append(dict(kwargs))
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
        if t_bsps_fn is not None:
            return t_bsps_fn(seg_in)
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
            if nf_fires_fn is not None:
                fires = nf_fires_fn(self.pushed)
            else:
                high = max(self.pushed) if self.pushed else 0.0
                low = min(self.pushed) if self.pushed else 0.0
                fires = [
                    (0, 3, False, low),
                    (max(len(self.pushed) - 1, 0), 3, True, high),
                ]
            return {
                "nf_fires": fires,
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
        state["organic_kwargs"].append({"require_settled": require_settled})
        state["v3_inputs"].append(list(zip(opens, highs, lows, closes)))
        return list(closes)

    def fake_push_signal(stream, s, flips):
        stream.pushed.append(s)

    fake_org = types.ModuleType("organic_signals")
    fake_org.MAX_LEVELS = 8
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
    data_tail_bad = tmp_path / "tail_bad.json"
    data_tail_bad.write_text(
        json.dumps(
            {
                "bars": [
                    {"ts": "2025-01-01T00:00:00Z", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5},
                    {"ts": "2025-01-01T00:01:00Z", "open": -1.0, "high": 11.0, "low": 9.5, "close": 10.5},
                    {"ts": "2025-01-01T00:02:00Z", "open": 10.5, "high": 12.0, "low": 10.0, "close": 11.5},
                    {"ts": "2025-01-01T00:03:00Z", "open": 11.5, "high": 12.5, "low": 11.0, "close": 12.0},
                    {"ts": "2025-01-01T00:04:00Z", "open": 12.0, "high": 13.0, "low": 11.5, "close": 12.5},
                    {"ts": "2025-01-01T00:05:00Z", "open": -2.0, "high": 14.0, "low": 12.5, "close": 13.5},
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
        _max = int(os.environ.get("BT_MAX_BARS", "0"))
        if _max > 0:
            o_in, h_in, l_in, c_in = o_in[:_max], h_in[:_max], l_in[:_max], c_in[:_max]
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
        "TAIL_BAD": data_tail_bad,
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


def test_two_stage_input_limits_distinguish_pre_and_post_clean(monkeypatch, tmp_path):
    mod, _state, _hist = _load_comparison_module(monkeypatch, tmp_path)
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")

    # 1) 仅设 BT_MAX_BARS（清洗前），未设位置参数 max_bars（清洗后）：绝不可打印“全量（env BT_MAX_BARS=…）”
    monkeypatch.setenv("BT_MAX_BARS", "42")
    assert mod.main(["OKLO"]) == 0
    # 2) 同时设 BT_MAX_BARS（清洗前）与位置参数 max_bars（清洗后）
    assert mod.main(["OKLO", "5"]) == 0
    # 3) BT_MAX_BARS=0 / -3 与 max_bars=0 / "" 均不生效，应显示“未生效”而非“未设”
    monkeypatch.setenv("BT_MAX_BARS", "0")
    assert mod.main(["OKLO", "0"]) == 0
    monkeypatch.setenv("BT_MAX_BARS", "-3")
    assert mod.main(["OKLO", ""]) == 0

    reports = sorted((tmp_path / "runs").glob("*/T_vs_v3_comparison.md"))
    assert len(reports) == 4

    by_limits: dict[tuple, list[tuple[str, dict]]] = {}
    for rep in reports:
        md = rep.read_text(encoding="utf-8")
        prov = _extract_provenance_json(md)
        lim = prov["selected_conditions"]["input_limits"]
        key = (
            lim["pre_clean_raw_max_bars_env"],
            lim["post_clean_max_bars_arg"],
            lim["post_clean_slice_mode"],
        )
        by_limits.setdefault(key, []).append((md, prov))

    md_pre, _ = by_limits[(42, None, "none")][0]
    assert "全量（env BT_MAX_BARS" not in md_pre
    assert "清洗前原始上限 env BT_MAX_BARS=42；清洗后无截断（位置参数 max_bars 未生效）" in md_pre

    md_both, _ = by_limits[(42, 5, "head")][0]
    assert "清洗前原始上限 env BT_MAX_BARS=42；清洗后截断前 5 bar（位置参数 max_bars=5）" in md_both

    inactive_reports = by_limits[(None, None, "none")]
    assert len(inactive_reports) == 2
    for md_none, prov_none in inactive_reports:
        assert "清洗前无原始上限（env BT_MAX_BARS 未生效）；清洗后无截断（位置参数 max_bars 未生效）" in md_none
        assert prov_none["inputs"]["OKLO"]["input_count"] == 6


def test_negative_max_bars_drops_tail_after_cleaning_and_distinguishes_cleaning_order(
    monkeypatch, tmp_path, capsys
):
    """恢复基线 x[:max_bars] 负数语义，并区分清洗顺序：
    TAIL_BAD 原始 6 根为 [B0, BAD1, B2, B3, B4, BAD5]。
    - 先清洗后 x[:-1]：先删 BAD1/BAD5 得 4 根 [B0,B2,B3,B4]，再去末根 B4 得 3 根 [B0,B2,B3]；
      （若误在清洗前切片 [:-1]，只会删掉 BAD5 而保留 4 根，数量与 hash 均可区分。）
    - 清洗前 BT_MAX_BARS=4 与清洗后 max_bars=-1 叠加：先取前 4 根原始 [B0,BAD1,B2,B3]，
      清洗得 3 根 [B0,B2,B3]，再去尾 1 根得 2 根 [B0,B2]。
    """
    mod, state, hist_md = _load_comparison_module(monkeypatch, tmp_path)
    hist_before = hist_md.read_bytes()
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")

    b0 = (10.0, 11.0, 9.5, 10.5)
    b2 = (10.5, 12.0, 10.0, 11.5)
    b3 = (11.5, 12.5, 11.0, 12.0)

    # 1) 真实 CLI：TAIL_BAD -1（无 BT_MAX_BARS）
    assert mod.main(["TAIL_BAD", "-1"]) == 0
    assert state["t_inputs"][-1] == [b0, b2, b3]
    assert state["v3_inputs"][-1] == [b0, b2, b3]

    # 2) 真实 CLI：BT_MAX_BARS=4（清洗前）+ TAIL_BAD -1（清洗后去尾）
    monkeypatch.setenv("BT_MAX_BARS", "4")
    assert mod.main(["TAIL_BAD", "-1"]) == 0
    assert state["t_inputs"][-1] == [b0, b2]
    assert state["v3_inputs"][-1] == [b0, b2]

    reports = sorted((tmp_path / "runs").glob("*/T_vs_v3_comparison.md"))
    assert len(reports) == 2

    by_pre = {}
    for rep in reports:
        md = rep.read_text(encoding="utf-8")
        prov = _extract_provenance_json(md)
        by_pre[prov["selected_conditions"]["input_limits"]["pre_clean_raw_max_bars_env"]] = (md, prov)

    md_neg, prov_neg = by_pre[None]
    expected_hash_3 = hashlib.sha256(b"".join(struct.pack(">dddd", *bar) for bar in (b0, b2, b3))).hexdigest()
    assert prov_neg["inputs"]["TAIL_BAD"]["input_count"] == 3
    assert prov_neg["inputs"]["TAIL_BAD"]["input_hash"] == f"sha256:{expected_hash_3}"
    assert prov_neg["selected_conditions"]["input_limits"] == {
        "pre_clean_raw_max_bars_env": None,
        "post_clean_max_bars_arg": -1,
        "post_clean_slice_mode": "drop_tail",
    }
    assert prov_neg["cores"]["t_arm"]["upstream_orchestrator"]["max_levels"] == 6
    assert prov_neg["cores"]["v3_arm"]["upstream_orchestrator"]["max_levels"] == 8
    assert "清洗前无原始上限（env BT_MAX_BARS 未生效）；清洗后去尾 1 bar（切片 x[:-1]，位置参数 max_bars=-1）" in md_neg
    assert "前 -1 bar" not in md_neg
    assert "T侧重合率 | v3侧重合率" in md_neg

    md_combo, prov_combo = by_pre[4]
    expected_hash_2 = hashlib.sha256(b"".join(struct.pack(">dddd", *bar) for bar in (b0, b2))).hexdigest()
    assert prov_combo["inputs"]["TAIL_BAD"]["input_count"] == 2
    assert prov_combo["inputs"]["TAIL_BAD"]["input_hash"] == f"sha256:{expected_hash_2}"
    assert prov_combo["selected_conditions"]["input_limits"] == {
        "pre_clean_raw_max_bars_env": 4,
        "post_clean_max_bars_arg": -1,
        "post_clean_slice_mode": "drop_tail",
    }
    assert "清洗前原始上限 env BT_MAX_BARS=4；清洗后去尾 1 bar（切片 x[:-1]，位置参数 max_bars=-1）" in md_combo
    assert "前 -1 bar" not in md_combo

    # 3) --diag 与负数位置参数混排，退出 0 且不新增报告
    monkeypatch.delenv("BT_MAX_BARS", raising=False)
    assert mod.main(["--diag", "TAIL_BAD", "-1"]) == 0
    assert state["t_inputs"][-1] == [b0, b2, b3]
    assert mod.main(["TAIL_BAD", "-1", "--diag"]) == 0
    assert state["v3_inputs"][-1] == [b0, b2, b3]
    assert len(list((tmp_path / "runs").glob("*/T_vs_v3_comparison.md"))) == 2

    # 4) 去尾后变空（-4 / -99）沿用空输入失败合同：退出 1、不写新报告、历史原件不变
    assert mod.main(["TAIL_BAD", "-4"]) == 1
    assert mod.main(["TAIL_BAD", "-99"]) == 1
    assert len(list((tmp_path / "runs").glob("*/T_vs_v3_comparison.md"))) == 2
    assert hist_md.read_bytes() == hist_before

    # 5) --help 明确说明去尾与 BT_MAX_BARS 顺序
    with pytest.raises(SystemExit) as exc_info:
        mod.parse_args(["--help"])
    assert exc_info.value.code == 0
    help_out = capsys.readouterr().out
    assert "去尾" in help_out
    assert "BT_MAX_BARS" in help_out


def test_real_source_arm_max_levels_are_t6_and_v3_8():
    """直接从仓库真实源码 AST 验证：T 臂 MAX_LEVELS=6，v3 经 organic_signals 使用 fugue_version_i.MAX_LEVELS=8。"""
    def _extract_int_const(path: Path, name: str) -> int:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, int)
                        return node.value.value
        raise AssertionError(f"{path} 缺少整型常量 {name}")

    assert _extract_int_const(ROOT / "analysis" / "t_vs_v3_comparison.py", "MAX_LEVELS") == 6
    assert _extract_int_const(ROOT / "analysis" / "fugue_version_i.py", "MAX_LEVELS") == 8

    org_src = (ROOT / "analysis" / "organic_signals.py").read_text(encoding="utf-8")
    org_tree = ast.parse(org_src)
    imported_max_levels = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "fugue_version_i"
        and any(alias.name == "MAX_LEVELS" for alias in node.names)
        for node in ast.walk(org_tree)
    )
    assert imported_max_levels, "organic_signals.py 应从 fugue_version_i 导入 MAX_LEVELS"
    assert "RecursiveOrchestrator(max_levels=MAX_LEVELS" in org_src
    assert "enable_macd_divergence=True" in org_src
    assert "require_settled_subseg=require_settled" in org_src


def test_per_arm_actual_configs_and_scope_shared_between_json_and_prose(monkeypatch, tmp_path):
    mod, state, _hist = _load_comparison_module(monkeypatch, tmp_path)
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")

    assert mod.main(["OKLO", "5"]) == 0
    reports = list((tmp_path / "runs").glob("*/T_vs_v3_comparison.md"))
    assert len(reports) == 1
    md = reports[0].read_text(encoding="utf-8")
    prov = _extract_provenance_json(md)

    # 运行参数保持原样（未为迎合报告而改成统一值）
    assert state["t_orch_kwargs"] == [
        {"max_levels": 6, "enable_macd_divergence": True, "require_settled_subseg": True}
    ]
    assert state["organic_kwargs"] == [{"require_settled": True}]
    assert state["v3_init_calls"] == [{"floor_ladder": 2, "funding_profile": "P0"}]

    # JSON 分臂记录 T=6、v3=8，无失真全局 max_levels
    t_arm = prov["cores"]["t_arm"]
    v3_arm = prov["cores"]["v3_arm"]
    assert t_arm["operator_uses_macd"] is False
    assert t_arm["upstream_orchestrator"] == {
        "max_levels": 6,
        "enable_macd_divergence": True,
        "require_settled_subseg": True,
    }
    assert v3_arm["upstream_signal_require_settled"] is True
    assert v3_arm["upstream_orchestrator"] == {
        "max_levels": 8,
        "enable_macd_divergence": True,
        "require_settled_subseg": True,
    }
    assert "max_levels" not in prov["selected_conditions"]
    assert "enable_macd_divergence_orchestrator" not in prov["selected_conditions"]

    # 正文与 JSON 一致，且明确“纯结构、零 MACD”仅限定 T 算子本体
    assert "# T 算子（算子本体纯结构、零 MACD）vs v3 nf 信号 L2 对照" in md
    assert "“纯结构、零 MACD”仅限定于 T 算子本体" in md
    assert "`operator_uses_macd=False`" in md
    assert "`max_levels=6`" in md
    assert "`max_levels=8`" in md


def test_empty_reference_zero_fire_report_is_neutral_and_distinct_from_failure(
    monkeypatch, tmp_path
):
    mod, _state, _hist = _load_comparison_module(
        monkeypatch, tmp_path, nf_fires_fn=lambda _pushed: []
    )
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")

    rc = mod.main(["OKLO", "5"])
    assert rc == 0, "零 fire 是执行成功的空参照样本，不应改成非零退出"

    reports = list((tmp_path / "runs").glob("*/T_vs_v3_comparison.md"))
    assert len(reports) == 1
    md = reports[0].read_text(encoding="utf-8")
    prov = _extract_provenance_json(md)

    assert prov["run_status"] == "complete"
    obs = prov["observations"]["OKLO"]
    assert obs["execution_status"] == "succeeded"
    assert obs["reference_status"] == "empty_v3_reference"
    assert obs["n_nf_fires"] == 0
    assert obs["n_nf_dedup"] == 0
    assert obs["n_t_compared"] == 2
    assert obs["n_t_only"] == 2
    assert obs["n_nf_only"] == 0
    assert obs["t_overlap_rate"] == 0.0
    assert obs["v3_overlap_rate"] is None

    # 中性表头与显式分母/不适用说明：无误判/漏判表头，无裸 None
    assert "T_only(仅T侧) | nf_only(仅v3侧) | T侧重合率 | v3侧重合率" in md
    assert "T_only(误判?)" not in md
    assert "nf_only(漏判?)" not in md
    assert "| None |" not in md
    assert "0/1 (0.0%) | 不适用（无 v3 样本）" in md
    assert "execution_status=succeeded" in md
    assert "reference_status=empty_v3_reference" in md
    assert "无参照样本 / 空参照" in md
    assert obs["interpretation"] in md
    assert "## 失败标的" not in md


def test_non_empty_reference_report_preserves_matching_dedup_and_both_denominators(
    monkeypatch, tmp_path
):
    # T 产出：ladder 3 sell 2 个点（1 个命中、1 个仅T侧），ladder 3 buy 1 个命中点，外加 1 个 type2
    def custom_t(seg_in):
        high = seg_in[0][3]
        low = seg_in[0][4]
        return [
            ("type1_sell", 1, high, 0),
            ("type3_sell", 2, high + 5.0, 0),
            ("type1_buy", 0, low, 0),
            ("type2_buy", 1, low, 0),
        ]

    # v3 产出：ladder 3 sell 重复 fire 2 次（去重后 1 点命中 high=13.5），ladder 3 buy 1 点命中 low=9.5，
    # 外加 ladder 4 buy 1 点（仅 v3 侧，T 侧分母 0 -> 不适用（无 T 样本））
    def custom_nf(_pushed):
        return [
            (0, 3, False, 9.5),
            (1, 3, True, 13.5),
            (2, 3, True, 13.5),
            (3, 4, False, 8.5),
        ]

    mod, _state, _hist = _load_comparison_module(
        monkeypatch, tmp_path, nf_fires_fn=custom_nf, t_bsps_fn=custom_t
    )
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")

    assert mod.main(["OKLO", "5"]) == 0
    reports = list((tmp_path / "runs").glob("*/T_vs_v3_comparison.md"))
    assert len(reports) == 1
    md = reports[0].read_text(encoding="utf-8")
    prov = _extract_provenance_json(md)

    obs = prov["observations"]["OKLO"]
    assert obs["execution_status"] == "succeeded"
    assert obs["reference_status"] == "non_empty_v3_reference"
    assert obs["n_nf_fires"] == 4
    assert obs["n_nf_dedup"] == 3
    assert obs["n_t_compared"] == 3
    assert obs["n_t_type2"] == 1
    assert obs["n_matched"] == 2
    assert obs["n_t_only"] == 1
    assert obs["n_nf_only"] == 1
    assert obs["t_overlap_rate"] == round(2 / 3, 3)
    assert obs["v3_overlap_rate"] == round(2 / 3, 3)

    assert "T_only(仅T侧) | nf_only(仅v3侧) | T侧重合率 | v3侧重合率" in md
    assert "| None |" not in md
    # ladder 3 sell: n_T=2, n_nf=1 (去重), n_nf_raw=2, matched=1, t_only=1, nf_only=0
    assert "| 3 | move/L1 | sell | 2 | 1 | 2 | 1 | 1 | 0 | 1/2 (50.0%) | 1/1 (100.0%) |" in md
    # ladder 3 buy: 1/1 & 1/1
    assert "| 3 | move/L1 | buy | 1 | 1 | 1 | 1 | 0 | 0 | 1/1 (100.0%) | 1/1 (100.0%) |" in md
    # ladder 4 buy: n_T=0 -> T侧不适用，v3侧 0/1 (0.0%)
    assert "| 4 | recL2 | buy | 0 | 1 | 1 | 0 | 0 | 1 | 不适用（无 T 样本） | 0/1 (0.0%) |" in md
    assert obs["interpretation"] in md


def test_real_run05_zero_fire_anchor_renders_neutral_report(monkeypatch, tmp_path):
    """以 run-05 A 真实 OKLO 零 fire 观测为验收锚点，验证新版报告格式与出处一致性。"""
    mod, _state, _hist = _load_comparison_module(monkeypatch, tmp_path)
    run05_result = {
        "symbol": "OKLO",
        "n_bars": 343_282,
        "n_segs": 2_844,
        "n_t_bsps": 529,
        "n_nf_fires": 0,
        "n_type2": 20,
        "source_file": "analysis/data_cache/oklo_1m_databento.json",
        "input_hash": "sha256:7adfa0884eadd9e4d5ad4a78af6cb18cb803beef7c9d7e1b95d23ec5803438e5",
        "input_encoding": "ohlc-f64be/1",
        "input_count": 343_282,
        "t_mode": "structure",
        "t_operator_uses_macd": False,
        "t_upstream_orchestrator": {
            "max_levels": 6,
            "enable_macd_divergence": True,
            "require_settled_subseg": True,
        },
        "v3_funding_profile": "P0",
        "v3_funding_record": "#1557/funding-authorization/v1@P0/v1",
        "v3_q_total": 100_000,
        "v3_floor_ladder": 2,
        "v3_upstream_signal_require_settled": True,
        "v3_upstream_orchestrator": {
            "max_levels": 8,
            "enable_macd_divergence": True,
            "require_settled_subseg": True,
        },
        "rows": [
            {"ladder": 3, "level": 0, "name": "move/L1", "side": "sell", "n_T": 218, "n_nf": 0, "n_nf_raw": 0, "matched": 0, "t_only": 218, "nf_only": 0, "t_match_rate": 0.0, "nf_match_rate": None},
            {"ladder": 3, "level": 0, "name": "move/L1", "side": "buy", "n_T": 213, "n_nf": 0, "n_nf_raw": 0, "matched": 0, "t_only": 213, "nf_only": 0, "t_match_rate": 0.0, "nf_match_rate": None},
            {"ladder": 4, "level": 1, "name": "recL2", "side": "sell", "n_T": 37, "n_nf": 0, "n_nf_raw": 0, "matched": 0, "t_only": 37, "nf_only": 0, "t_match_rate": 0.0, "nf_match_rate": None},
            {"ladder": 4, "level": 1, "name": "recL2", "side": "buy", "n_T": 30, "n_nf": 0, "n_nf_raw": 0, "matched": 0, "t_only": 30, "nf_only": 0, "t_match_rate": 0.0, "nf_match_rate": None},
            {"ladder": 5, "level": 2, "name": "recL3", "side": "sell", "n_T": 4, "n_nf": 0, "n_nf_raw": 0, "matched": 0, "t_only": 4, "nf_only": 0, "t_match_rate": 0.0, "nf_match_rate": None},
            {"ladder": 5, "level": 2, "name": "recL3", "side": "buy", "n_T": 5, "n_nf": 0, "n_nf_raw": 0, "matched": 0, "t_only": 5, "nf_only": 0, "t_match_rate": 0.0, "nf_match_rate": None},
            {"ladder": 6, "level": 3, "name": "recL4", "side": "sell", "n_T": 1, "n_nf": 0, "n_nf_raw": 0, "matched": 0, "t_only": 1, "nf_only": 0, "t_match_rate": 0.0, "nf_match_rate": None},
            {"ladder": 6, "level": 3, "name": "recL4", "side": "buy", "n_T": 1, "n_nf": 0, "n_nf_raw": 0, "matched": 0, "t_only": 1, "nf_only": 0, "t_match_rate": 0.0, "nf_match_rate": None},
        ],
        "regime": [
            {"bar_lo": 0, "bar_hi": 68_656, "ret_pct": 1.2, "regime": "range", "n_nf": 0},
            {"bar_lo": 68_656, "bar_hi": 137_312, "ret_pct": 111.8, "regime": "bull", "n_nf": 0},
            {"bar_lo": 137_312, "bar_hi": 205_968, "ret_pct": 226.4, "regime": "bull", "n_nf": 0},
            {"bar_lo": 205_968, "bar_hi": 274_624, "ret_pct": -45.2, "regime": "bear", "n_nf": 0},
            {"bar_lo": 274_624, "bar_hi": 343_282, "ret_pct": -20.0, "regime": "bear", "n_nf": 0},
        ],
    }

    report_path = mod.write_report(
        [run05_result],
        None,
        run_id="anchor-run05-oklo",
        output_dir=tmp_path,
        requested_symbols=["OKLO"],
        failed=[],
        funding_profile="P0",
    )
    md = report_path.read_text(encoding="utf-8")
    prov = _extract_provenance_json(md)

    assert prov["cores"]["t_arm"]["upstream_orchestrator"]["max_levels"] == 6
    assert prov["cores"]["v3_arm"]["upstream_orchestrator"]["max_levels"] == 8
    obs = prov["observations"]["OKLO"]
    assert obs["n_t_compared"] == 509
    assert obs["n_t_only"] == 509
    assert obs["n_nf_fires"] == 0
    assert obs["t_overlap_rate"] == 0.0
    assert obs["v3_overlap_rate"] is None
    assert obs["reference_status"] == "empty_v3_reference"

    assert "| 3 | move/L1 | sell | 218 | 0 | 0 | 0 | 218 | 0 | 0/218 (0.0%) | 不适用（无 v3 样本） |" in md
    assert "0/509 = 0.0%" in md
    assert "| None |" not in md
    assert "T_only(误判?)" not in md
    assert "nf_only(漏判?)" not in md

