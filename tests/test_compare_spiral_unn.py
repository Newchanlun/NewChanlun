"""#1323 / #1385 OE12：trading_system/compare_spiral_unn.py 三项判决、诊断与 provenance 回归。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / "trading_system" / "compare_spiral_unn.py"

TRADE_A = (2, 0, 100.0, 1, 101.0, 10.0, 1.0, 0, False, "exit", "long")
TRADE_B = (2, 0, 100.0, 1, 102.0, 10.0, 1.0, 0, False, "exit", "long")


def _install_stub_deps(monkeypatch, *, unn_factory, spiral_factory, bars_data=None, symbol_files=None):
    """只替换外部重依赖（NT/Rust/信号流）；被测 compare_spiral_unn 源码原样执行。"""
    if bars_data is None:
        bars_data = (
            [100.0, 101.0, 102.0],
            [101.0, 102.0, 103.0],
            [99.0, 100.0, 101.0],
            [100.5, 101.5, 102.5],
        )

    def _mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        monkeypatch.setitem(sys.modules, name, m)
        return m

    _mod("nautilus_trader")
    _mod("nautilus_trader.model")
    _mod(
        "nautilus_trader.model.data",
        BarType=type("BarType", (), {"from_str": staticmethod(lambda value: value)}),
    )
    _mod("newchan_rust", UnnStream=unn_factory, SpiralStream=spiral_factory)
    _mod("nested_recursive_fugue_final_backtest", FLOOR=2)

    class StubReader:
        def __init__(self, dir_flips=None, require_settled=True):
            self.dir_flips = dir_flips
            self.require_settled = require_settled
            self.seen_bars = []

        def process_bar(self, i, o, h, low, c):
            self.seen_bars.append((i, o, h, low, c))
            return NS(bar=i, close=c)

    _mod(
        "organic_signals",
        StreamingSignalReader=StubReader,
        push_signal=lambda stream, sig, flip_rows: stream.push(sig, flip_rows),
    )

    load_calls = []

    def fake_load_bars(sym, bar_type, price_precision, max_bars, size_precision=0):
        load_calls.append((sym, bar_type, price_precision, max_bars, size_precision))
        opens, highs, lows, closes = bars_data
        if max_bars is not None:
            opens, highs, lows, closes = (a[:max_bars] for a in (opens, highs, lows, closes))
        return [], list(opens), list(highs), list(lows), list(closes)

    bt_attrs = {"load_bars": fake_load_bars}
    if symbol_files is not None:
        bt_attrs["SYMBOL_FILES"] = symbol_files
    _mod("trading_system.backtest_unn", **bt_attrs)
    _mod(
        "trading_system.config.instruments",
        INSTRUMENTS={
            "OKLO": NS(price_precision=4),
            "CL": NS(price_precision=2),
        },
        make_instrument=lambda spec: NS(
            id="OKLO.XNAS" if spec.price_precision == 4 else "CL.GLBX",
            size_precision=0,
        ),
    )
    return load_calls


def _load_cli_module(monkeypatch, name="compare_spiral_unn_under_test"):
    spec = importlib.util.spec_from_file_location(name, CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


class _ScriptedStream:
    def __init__(
        self,
        *,
        per_bar: dict[int, list] | None = None,
        finish_trades: list | None = None,
        final_nav: float = 100_000.0,
        extra_finish: dict | None = None,
    ):
        self.per_bar = per_bar or {}
        self.finish_trades = list(finish_trades or [])
        self.final_nav = final_nav
        self.extra_finish = dict(extra_finish or {})
        self.bar_idx = 0

    def push(self, _sig, _flip_rows):
        out = list(self.per_bar.get(self.bar_idx, ()))
        self.bar_idx += 1
        return out

    def finish(self):
        res = {"trades": list(self.finish_trades), "final_nav": self.final_nav}
        res.update(self.extra_finish)
        return res


def test_bar_timing_divergence_exits_2_even_when_trades_and_nav_match(monkeypatch, capsys):
    """核心回归：逐 bar 吐单时序不同但 finish trade 表与 final_nav 相同时，必须判 MISMATCH 退出 2。"""
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")
    _install_stub_deps(
        monkeypatch,
        unn_factory=lambda floor_ladder, funding_profile: _ScriptedStream(
            per_bar={1: [TRADE_A]},
            finish_trades=[TRADE_A],
            final_nav=100_010.0,
            extra_finish={"records": "#1557@P0/v1 + #1558@P0/v1", "q_total": 100_000},
        ),
        spiral_factory=lambda floor_ladder, funding_profile: _ScriptedStream(
            per_bar={2: [TRADE_A]},
            finish_trades=[TRADE_A],
            final_nav=100_010.0,
            extra_finish={"funding_record": "#1557@P0/v1", "q_total": 100_000},
        ),
    )
    mod = _load_cli_module(monkeypatch, "csu_bar_div")

    rc = mod.main(["--symbol", "OKLO", "--bars", "3"])
    out = capsys.readouterr().out

    assert rc == 2
    assert "逐 bar 吐单分歧 : 2 bar  ❌ MISMATCH" in out
    assert "trade 表 bit-exact : ✅ PASS" in out
    assert "final_nav       : unn=100010.000000  spiral=100010.000000  ✅ PASS" in out
    assert "分歧项          : 逐 bar 吐单" in out
    assert "第一处分歧      : 逐 bar 吐单 @ bar 1" in out
    assert "第一处逐 bar 分歧 @ bar 1:" in out
    assert "判决: ❌ MISMATCH —— 分歧项: 逐 bar 吐单" in out
    assert "✅ BIT-EXACT" not in out


@pytest.mark.parametrize(
    ("unn_trades", "spiral_trades", "expected_idx", "expected_missing"),
    [
        ([TRADE_A, TRADE_A], [TRADE_A, TRADE_B], 1, None),
        ([TRADE_A], [TRADE_A, TRADE_B], 1, "unn   : <缺失 (len=1)>"),
    ],
)
def test_trade_table_divergence_only_exits_2(
    monkeypatch, capsys, unn_trades, spiral_trades, expected_idx, expected_missing
):
    """逐 bar 与 final_nav 均相等，但 finish trade 表不同（如 EOD 阶段差异）时必须退出 2。"""
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")
    _install_stub_deps(
        monkeypatch,
        unn_factory=lambda floor_ladder, funding_profile: _ScriptedStream(
            per_bar={0: [TRADE_A]},
            finish_trades=unn_trades,
            final_nav=100_000.0,
        ),
        spiral_factory=lambda floor_ladder, funding_profile: _ScriptedStream(
            per_bar={0: [TRADE_A]},
            finish_trades=spiral_trades,
            final_nav=100_000.0,
        ),
    )
    mod = _load_cli_module(monkeypatch, f"csu_trade_div_{expected_idx}_{bool(expected_missing)}")

    rc = mod.main(["--symbol", "OKLO", "--bars", "3"])
    out = capsys.readouterr().out

    assert rc == 2
    assert "逐 bar 吐单分歧 : 0 bar  ✅ PASS" in out
    assert "trade 表 bit-exact : ❌ MISMATCH" in out
    assert "final_nav       : unn=100000.000000  spiral=100000.000000  ✅ PASS" in out
    assert "分歧项          : finish trade 表" in out
    assert f"第一处分歧      : finish trade 表 @ index {expected_idx}" in out
    assert f"第一处 trade 表分歧 @ index {expected_idx}:" in out
    if expected_missing is not None:
        assert expected_missing in out


def test_nav_divergence_only_exits_2_even_for_sub_micro_delta(monkeypatch, capsys):
    """逐 bar 与 trade 表均相等，仅 final_nav 存在极小浮点差异时也必须退出 2 并给出精确值。"""
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")
    nav_u = 100_000.0
    nav_s = 100_000.0 + 1e-11
    _install_stub_deps(
        monkeypatch,
        unn_factory=lambda floor_ladder, funding_profile: _ScriptedStream(
            per_bar={1: [TRADE_A]},
            finish_trades=[TRADE_A],
            final_nav=nav_u,
        ),
        spiral_factory=lambda floor_ladder, funding_profile: _ScriptedStream(
            per_bar={1: [TRADE_A]},
            finish_trades=[TRADE_A],
            final_nav=nav_s,
        ),
    )
    mod = _load_cli_module(monkeypatch, "csu_nav_div")

    rc = mod.main(["--symbol", "OKLO", "--bars", "3"])
    out = capsys.readouterr().out

    assert rc == 2
    assert "逐 bar 吐单分歧 : 0 bar  ✅ PASS" in out
    assert "trade 表 bit-exact : ✅ PASS" in out
    assert "❌ MISMATCH" in out
    assert "分歧项          : final_nav" in out
    assert "第一处分歧      : final_nav" in out
    assert "final_nav 分歧:" in out
    assert repr(nav_s) in out


def test_multi_axis_divergence_reports_all_axes_and_earliest_first(monkeypatch, capsys):
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")
    _install_stub_deps(
        monkeypatch,
        unn_factory=lambda floor_ladder, funding_profile: _ScriptedStream(
            per_bar={1: [TRADE_A]},
            finish_trades=[TRADE_A],
            final_nav=100_010.0,
        ),
        spiral_factory=lambda floor_ladder, funding_profile: _ScriptedStream(
            per_bar={1: [TRADE_B]},
            finish_trades=[TRADE_B],
            final_nav=100_020.0,
        ),
    )
    mod = _load_cli_module(monkeypatch, "csu_multi_div")

    rc = mod.main(["--symbol", "OKLO", "--bars", "3"])
    out = capsys.readouterr().out

    assert rc == 2
    assert "分歧项          : 逐 bar 吐单, finish trade 表, final_nav" in out
    assert "第一处分歧      : 逐 bar 吐单 @ bar 1" in out
    assert "第一处逐 bar 分歧 @ bar 1:" in out
    assert "第一处 trade 表分歧 @ index 0:" in out
    assert "final_nav 分歧:" in out


def test_nonzero_trade_match_exits_0_and_marks_non_admission(monkeypatch, capsys):
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")
    _install_stub_deps(
        monkeypatch,
        unn_factory=lambda floor_ladder, funding_profile: _ScriptedStream(
            per_bar={1: [TRADE_A]},
            finish_trades=[TRADE_A],
            final_nav=100_010.0,
            extra_finish={"records": "#1557@P0/v1 + #1558@P0/v1", "q_total": 100_000},
        ),
        spiral_factory=lambda floor_ladder, funding_profile: _ScriptedStream(
            per_bar={1: [TRADE_A]},
            finish_trades=[TRADE_A],
            final_nav=100_010.0,
            extra_finish={"funding_record": "#1557@P0/v1", "q_total": 100_000},
        ),
    )
    mod = _load_cli_module(monkeypatch, "csu_nonzero_pass")

    rc = mod.main(["--symbol", "OKLO", "--bars", "3"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "逐 bar 吐单分歧 : 0 bar  ✅ PASS" in out
    assert "trade 表 bit-exact : ✅ PASS" in out
    assert "final_nav       : unn=100010.000000  spiral=100010.000000  ✅ PASS" in out
    assert "已观测 1 笔完成交易" in out
    assert "不构成生产准入" in out
    assert "空交易样本" not in out


def test_zero_trade_match_preserves_exit_0_and_reports_honest_scope(monkeypatch, capsys):
    """两边均无交易但三项一致时：保持退出码 0，同时诚实限定观测范围，不宣称验证全部操作。"""
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")
    _install_stub_deps(
        monkeypatch,
        unn_factory=lambda floor_ladder, funding_profile: _ScriptedStream(
            per_bar={},
            finish_trades=[],
            final_nav=100_000.0,
            extra_finish={"records": "#1557@P0/v1 + #1558@P0/v1", "q_total": 100_000},
        ),
        spiral_factory=lambda floor_ladder, funding_profile: _ScriptedStream(
            per_bar={},
            finish_trades=[],
            final_nav=100_000.0,
            extra_finish={"funding_record": "#1557@P0/v1", "q_total": 100_000},
        ),
    )
    mod = _load_cli_module(monkeypatch, "csu_zero_trade")

    rc = mod.main(["--symbol", "OKLO", "--bars", "3"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "空交易样本" in out
    assert "未覆盖交易操作" in out
    assert "未验证交易操作" in out
    assert "不构成生产准入" in out
    assert "操作=群作用 L2" not in out


@pytest.mark.parametrize(
    ("trades", "nav", "code", "first_difference"),
    [
        ([], 100_000.0, 0, None),
        ([TRADE_A], 100_000.0, 2, "finish trade 表 @ index 0"),
        ([], 99_999.0, 2, "final_nav ("),
    ],
)
def test_empty_bar_slice_compares_only_finish(monkeypatch, capsys, trades, nav, code, first_difference):
    unn = _ScriptedStream()
    spiral = _ScriptedStream(finish_trades=trades, final_nav=nav)
    _install_stub_deps(monkeypatch, unn_factory=lambda **_: unn, spiral_factory=lambda **_: spiral)
    cli = _load_cli_module(monkeypatch)

    assert cli.main(["--symbol", "OKLO", "--bars", "-3"]) == code
    out = capsys.readouterr().out
    assert "bars=0)" in out and unn.bar_idx == spiral.bar_idx == 0
    assert "逐 bar 吐单分歧 : 不适用" in out
    assert "无交易路径" not in out and "逐 bar 完成" not in out
    if first_difference is None:
        assert "判决: 收尾值相等" in out
    else:
        assert "判决: ❌ MISMATCH" in out and f"第一处分歧      : {first_difference}" in out


def test_provenance_arms_run_id_and_shared_input_hash(monkeypatch, capsys):
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")
    monkeypatch.delenv("BT_MAX_BARS", raising=False)
    sample_path = ROOT / "analysis" / "data_cache" / "oklo_1m_databento.json"
    bars_a = (
        [10.0, 11.0, 12.0],
        [10.5, 11.5, 12.5],
        [9.5, 10.5, 11.5],
        [10.2, 11.2, 12.2],
    )
    _install_stub_deps(
        monkeypatch,
        unn_factory=lambda floor_ladder, funding_profile: _ScriptedStream(
            finish_trades=[],
            final_nav=100_000.0,
            extra_finish={"records": "#1557@P0/v1 + #1558@P0/v1", "q_total": 100_000},
        ),
        spiral_factory=lambda floor_ladder, funding_profile: _ScriptedStream(
            finish_trades=[],
            final_nav=100_000.0,
            extra_finish={"funding_record": "#1557@P0/v1", "q_total": 100_000},
        ),
        bars_data=bars_a,
        symbol_files={"OKLO": sample_path},
    )
    mod = _load_cli_module(monkeypatch, "csu_prov")

    assert mod.compare("OKLO", 3) == 0
    out1 = capsys.readouterr().out
    assert mod.compare("OKLO", 3) == 0
    out2 = capsys.readouterr().out

    run_id_1 = re.search(r"^run_id\s*:\s*(\S+)$", out1, re.M).group(1)
    run_id_2 = re.search(r"^run_id\s*:\s*(\S+)$", out2, re.M).group(1)
    assert run_id_1 != run_id_2

    expected_digest = hashlib.sha256()
    for o, h, low, c in zip(*bars_a):
        expected_digest.update(struct.pack(">dddd", o, h, low, c))
    expected_hash = f"sha256:{expected_digest.hexdigest()}"

    for out in (out1, out2):
        assert "role            : frozen_shadow_research_comparison (admission_effect=none" in out
        assert "arm_unn core_id : trading::unified_necessity::UnnStreamCore (via newchan_rust.UnnStream)" in out
        assert "arm_spiral core_id: spiral::engine::SpiralEngineCore (via newchan_rust.SpiralStream)" in out
        assert "input_source    : analysis/data_cache/oklo_1m_databento.json" in out
        assert f"input_hash      : {expected_hash} (encoding=ohlc-f64be/1, bars=3)" in out
        assert "funding_profile=P0" in out
        assert "floor_ladder=2" in out
        assert "require_settled=True" in out
        assert "unn=(#1557@P0/v1 + #1558@P0/v1, q_total=100000)" in out
        assert "spiral=(#1557@P0/v1, q_total=100000)" in out

    # 改 1 根输入 ⇒ input_hash 必须改变；长度不一致 ⇒ 立即报错
    mutated = mod.hash_ohlc_series([10.0, 11.0, 12.1], bars_a[1], bars_a[2], bars_a[3])
    assert mutated != expected_hash
    with pytest.raises(ValueError, match="长度不一致"):
        mod.hash_ohlc_series([10.0], [10.5, 11.5], [9.5], [10.2])


def test_bars_zero_passes_none_for_full_dataset(monkeypatch, capsys):
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")
    load_calls = _install_stub_deps(
        monkeypatch,
        unn_factory=lambda floor_ladder, funding_profile: _ScriptedStream(),
        spiral_factory=lambda floor_ladder, funding_profile: _ScriptedStream(),
    )
    mod = _load_cli_module(monkeypatch, "csu_bars_zero")

    rc = mod.main(["--symbol", "CL", "--bars", "0"])
    out = capsys.readouterr().out

    assert rc == 0
    assert load_calls == [("CL", "CL.GLBX-1-MINUTE-LAST-EXTERNAL", 2, None, 0)]
    assert "max_bars=全量" in out


def test_missing_funding_profile_fails_without_default_before_loading_bars(monkeypatch):
    monkeypatch.delenv("NC_FUNDING_PROFILE", raising=False)
    received = []

    def fail_unn(floor_ladder, funding_profile):
        received.append(("unn", floor_ladder, funding_profile))
        if funding_profile is None:
            raise ValueError("AwaitingPolicy{funding_record, profile=<未指定 funding_profile>}")
        return _ScriptedStream()

    load_calls = _install_stub_deps(
        monkeypatch,
        unn_factory=fail_unn,
        spiral_factory=lambda floor_ladder, funding_profile: _ScriptedStream(),
    )
    mod = _load_cli_module(monkeypatch, "csu_missing_funding")

    with pytest.raises(ValueError, match=r"AwaitingPolicy\{funding_record"):
        mod.main(["--symbol", "OKLO", "--bars", "3"])

    assert received == [("unn", 2, None)]
    assert load_calls == []


def test_cli_subprocess_unknown_symbol_exits_1():
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{ROOT}:{ROOT / 'src'}"
    proc = subprocess.run(
        [sys.executable, str(CLI_PATH), "--symbol", "NO_SUCH_SYM", "--bars", "10"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "标的 NO_SUCH_SYM 未注册" in proc.stderr
    assert "未作两臂比较" in proc.stderr


def test_cli_subprocess_help_shows_funding_contracts_status_and_exit_semantics():
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{ROOT}:{ROOT / 'src'}"
    proc = subprocess.run(
        [sys.executable, str(CLI_PATH), "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "funding-record.json" in out
    assert "chong-derivation-input.json" in out
    assert "PENDING_LO = 3" in out
    assert "P0 / P1-hl-testnet / P0-acceptance-5m" in out
    assert "l_start=L0" in out
    assert "op_ladder=2" in out
    assert "非永久版本表" in out
    assert "不硬编码拒绝" in out
    assert "exit 1" in out and "未作两臂比较" in out
    assert "exit 2" in out and "MISMATCH" in out
    assert "exit 0" in out and "0 笔交易" in out
    assert "零根行情：逐 bar 无样本" in out
    assert "NC_FUNDING_PROFILE=<profile>" in out
    assert "NC_FUNDING_PROFILE=P0 " not in out


def test_unn_op_ladder_rejection_reports_no_comparison_and_no_hardcoding(monkeypatch, capsys):
    """构造拒绝时：stderr 明示未作两臂比较、保留原异常且不加载 OHLC；且不硬编码拒绝任何 profile。"""
    err_msg = "unified_necessity 要求 op_ladder（操作绑定级别）∈ [3=2+1, 11)（segment 非势源）；op_ladder=2"
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")

    def reject_unn(floor_ladder, funding_profile):
        raise ValueError(err_msg)

    load_calls = _install_stub_deps(
        monkeypatch,
        unn_factory=reject_unn,
        spiral_factory=lambda floor_ladder, funding_profile: _ScriptedStream(),
    )
    mod = _load_cli_module(monkeypatch, "csu_op_ladder_reject")

    with pytest.raises(ValueError, match=r"op_ladder=2"):
        mod.main(["--symbol", "OKLO", "--bars", "3"])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert load_calls == []
    assert "构造未成（未作两臂比较）" in captured.err
    assert "arm_init_rejected" in captured.err
    assert "rejected_arm    : arm_unn" in captured.err
    assert f"原异常原因      : ValueError: {err_msg}" in captured.err
    assert "区别于已完成比较的分歧 exit 2 与已完成但零交易的 exit 0" in captured.err
    assert "不硬编码拒绝" in captured.err

    # 验证不硬编码拒绝 P0：当运行时两臂构造器接纳同一 profile 时，脚本直接执行两臂比较。
    mod.nr = NS(
        UnnStream=lambda floor_ladder, funding_profile: _ScriptedStream(),
        SpiralStream=lambda floor_ladder, funding_profile: _ScriptedStream(),
    )
    rc = mod.main(["--symbol", "OKLO", "--bars", "3"])
    captured2 = capsys.readouterr()
    assert rc == 0
    assert captured2.err == ""
    assert "空交易样本" in captured2.out


def test_spiral_arm_rejection_reports_arm_spiral_and_preserves_exception(monkeypatch, capsys):
    monkeypatch.setenv("NC_FUNDING_PROFILE", "P0")
    load_calls = _install_stub_deps(
        monkeypatch,
        unn_factory=lambda floor_ladder, funding_profile: _ScriptedStream(),
        spiral_factory=lambda floor_ladder, funding_profile: (_ for _ in ()).throw(
            ValueError("AwaitingPolicy{funding_record, profile=P0}")
        ),
    )
    mod = _load_cli_module(monkeypatch, "csu_spiral_reject")

    with pytest.raises(ValueError, match=r"AwaitingPolicy\{funding_record, profile=P0\}"):
        mod.compare("OKLO", 3)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert load_calls == []
    assert "rejected_arm    : arm_spiral" in captured.err
    assert "构造未成（未作两臂比较）" in captured.err
    assert "原异常原因      : ValueError: AwaitingPolicy{funding_record, profile=P0}" in captured.err


def test_cli_subprocess_real_nt_load_bars_on_fixture_json(tmp_path):
    """子进程跑真实 CLI + 真实 trading_system.backtest_unn.load_bars（含 NT BarType/bars_from_dataframe）。"""
    fixture = tmp_path / "fixture_oklo.json"
    fixture.write_text(
        json.dumps(
            {
                "opens": [20.0, 20.5, 21.0, 20.8],
                "highs": [20.6, 21.1, 21.4, 21.2],
                "lows": [19.8, 20.2, 20.7, 20.4],
                "closes": [20.4, 20.9, 21.1, 20.7],
            }
        ),
        encoding="utf-8",
    )
    driver = r"""
import importlib.util, sys
from pathlib import Path
from types import SimpleNamespace as NS

cli_path, fixture_path, mode = sys.argv[1], sys.argv[2], sys.argv[3]
spec = importlib.util.spec_from_file_location("compare_cli_real_nt", cli_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

import trading_system.backtest_unn as bt_unn
bt_unn.SYMBOL_FILES["OKLO"] = Path(fixture_path)

TRADE = (2, 0, 20.4, 1, 20.9, 10.0, 1.0, 0, False, "exit", "long")

class Reader:
    def __init__(self, dir_flips=None, require_settled=True):
        pass
    def process_bar(self, i, o, h, l, c):
        return NS(bar=i, close=c)

class Arm:
    def __init__(self, emit_at):
        self.emit_at = emit_at
        self.i = 0
    def step(self):
        out = [TRADE] if self.i == self.emit_at else []
        self.i += 1
        return out
    def finish(self):
        return {"trades": [TRADE], "final_nav": 100005.0, "records": "P0/v1", "funding_record": "P0/v1", "q_total": 100000}

mod.StreamingSignalReader = Reader
mod.push_signal = lambda stream, sig, flips: stream.step()
mod.nr = NS(
    UnnStream=lambda floor_ladder, funding_profile: Arm(emit_at=1),
    SpiralStream=lambda floor_ladder, funding_profile: Arm(emit_at=1 if mode == "match" else 2),
)
mod.FUNDING_PROFILE = "P0"
raise SystemExit(mod.main(["--symbol", "OKLO", "--bars", "0"]))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{ROOT}:{ROOT / 'src'}"
    env["NC_FUNDING_PROFILE"] = "P0"
    env.pop("BT_MAX_BARS", None)

    p_match = subprocess.run(
        [sys.executable, "-c", driver, str(CLI_PATH), str(fixture), "match"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert p_match.returncode == 0, p_match.stderr
    assert f"input_source    : {fixture}" in p_match.stdout
    assert "bars=4)" in p_match.stdout
    assert "max_bars=全量" in p_match.stdout
    assert "逐 bar 吐单分歧 : 0 bar  ✅ PASS" in p_match.stdout

    p_div = subprocess.run(
        [sys.executable, "-c", driver, str(CLI_PATH), str(fixture), "bar_div"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert p_div.returncode == 2, p_div.stderr
    assert "逐 bar 吐单分歧 : 2 bar  ❌ MISMATCH" in p_div.stdout
    assert "第一处分歧      : 逐 bar 吐单 @ bar 1" in p_div.stdout
    h_match = re.search(r"input_hash\s*:\s*(sha256:[0-9a-f]{64})", p_match.stdout).group(1)
    h_div = re.search(r"input_hash\s*:\s*(sha256:[0-9a-f]{64})", p_div.stdout).group(1)
    assert h_match == h_div


def test_line_1_docstring_preserved_for_adr_0039_and_honest_usage():
    src = CLI_PATH.read_text(encoding="utf-8")
    first_line = src.splitlines()[0]
    assert first_line.startswith('"""螺旋引擎 v2（spiral）× 统一必然性引擎（unn）逐 bar bit-exact 对账')
    assert "NC_FUNDING_PROFILE=P0 PYTHONPATH=" not in src
    assert "NC_FUNDING_PROFILE=<profile>" in src
    assert "非永久版本表" in src
