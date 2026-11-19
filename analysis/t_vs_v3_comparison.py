"""统一递归算子 T（算子本体纯结构、零 MACD）vs v3(fugue_v3) nf 信号 L2 对照 — §6.6 阶段2。

设计依据: docs/unified_recursive_operator_T.md §6.6/§6.7（T 算子本体纯结构买卖点与
v3 nf 信号集的对称差集对照，L2 真实数据、可否证）。

对照轴（关键设计决策, 见模块末 NOTE）:
  - **price 匹配**（坐标无关）: T BSP 与 nf fire 的 price 都是同一段极值。Stroke.i0/i1
    是 K线合并坐标, nf_fires.bar 是 raw bar 序号——两者坐标系不同, bar 不可直接相减
    （记忆 current_strokes_i1_merged_coord）。price 是买卖点本质标识且坐标无关 ⇒ 主匹配轴。
  - **level 映射**: T.level+3 == v3.ladder（segment=ladder2 不在 T 递归序列中,
    T 从 move/L1=ladder3 起; 设计文档 §5.2 bug-a）。脚本输出实测分布验证此映射, 不硬编码。
  - **极性**: T type1_sell/type3_sell ↔ nf is_sell=True; buy ↔ is_sell=False。
  - nf fire 来自 candidate(type1/type3)武装+次级别证据 ⇒ 主对照用 T 的 type1+type3;
    type2(跨级投影)单列为 T 特有。

上游配置范围与 a₀ 来源:
  - T 算子本体（`run_recursive_t`）纯结构、零 MACD、无需资金记录；其上游段由本模块以
    `RecursiveOrchestrator(max_levels=6, enable_macd_divergence=True, require_settled_subseg=True)`
    生成（confirmed+settled 过滤在 `run_recursive_t` 内）。
  - v3 信号由 `organic_signals.compute_organic_signals(require_settled=True)` 生成，其内部
    `RecursiveOrchestrator` 使用 `organic_signals.MAX_LEVELS`（来自 `fugue_version_i.py`，值为 8）、
    `enable_macd_divergence=True`、`require_settled_subseg=True`。两臂上游实际层数不同，报告按臂如实分列。

指标语义与空参照边界:
  - `T_only(仅T侧)` 与 `nf_only(仅v3侧)` 均为对称差集计数，不自动等价于误判或漏判。
  - 若某标的正常完成但 v3 产出 0 条 nf fire，属于无参照样本（空参照）：非空 T 侧重合率按
    `0/n_T = 0.0%` 计算（仅描述 T 与空集之差集），v3 侧 0 分母记作“不适用（无 v3 样本）”；
    空参照不可用于判错或估计结构替代率，且与标的执行失败（非零退出）及 `--diag`（不写报告）区分。

用法:
  NC_FUNDING_PROFILE=P0 .venv/bin/python analysis/t_vs_v3_comparison.py [symbols] [max_bars] [--diag] [--funding-profile PROFILE] [--output-dir DIR]
  symbols: 逗号分隔（默认 8 标的）; max_bars: 清洗后截断上限（0 或留空表示清洗后不截断；清洗前原始上限见 env BT_MAX_BARS）
  --diag: 只跑诊断不写报告
  --funding-profile: 显式签署资金 profile（覆盖 NC_FUNDING_PROFILE；仅传给需它的 v3 核，无默认）
  --output-dir: 新报告根目录（默认 analysis/，每次运行写入 <output-dir>/runs/<run_id>/T_vs_v3_comparison.md，不覆写历史原件）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
import time
import traceback
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import newchan_rust as R  # noqa: E402
import organic_signals as _organic_signals  # noqa: E402
from organic_signals import compute_organic_signals, push_signal  # noqa: E402
from fugue_v2_full_backtest import SYMBOL_FILES, load_ohlc  # noqa: E402

MAX_LEVELS = 6
T_UPSTREAM_ENABLE_MACD_DIVERGENCE = True
T_UPSTREAM_REQUIRE_SETTLED_SUBSEG = True
V3_REQUIRE_SETTLED = True
FLOOR_LADDER = 2
LADDER_MOVE = 3          # v3 move/L1 = T.level 0 的对照层（设计文档 §5.2 bug-a）
PRICE_REL_TOL = 1e-4     # 相对价格容差（同段极值应 bit-exact, 留浮点裕度）
LAD_NAME = {2: "seg", 3: "move/L1", 4: "recL2", 5: "recL3", 6: "recL4", 7: "recL5",
            8: "L6", 9: "L7", 10: "L8"}
DEFAULT_SYMS = ["CL", "BRN", "DX", "GC", "ES", "QQQ", "BTC", "OKLO"]
OUT_MD = Path(__file__).parent / "T_vs_v3_comparison.md"
RUNS_DIR_NAME = "runs"
INPUT_ENCODING = "ohlc-f64be/1"
PROVENANCE_SCHEMA = "shadow-comparison-provenance/1"
T_CORE_ID = "recursive_t::iterate"
V3_CORE_ID = "fugue_v3::engine::FugueEngineCore"
UPSTREAM_SEG_CORE_ID = "newchan_rust::RecursiveOrchestrator"
AUTHORITY_NOTE = (
    "纯研究对照产物（ADR 0039 §四.4 / C11.4）；研究重合率与差集不构成生产准入、"
    "交易许可、资金放行或 TStage 触闸依据，不得被 E/B 读为事实。"
)
_UNSET = object()


def _t_upstream_orchestrator_config() -> dict[str, int | bool]:
    """T 臂上游 RecursiveOrchestrator 的实际构造实参（直接用于实例化并写入出处）。"""
    return {
        "max_levels": MAX_LEVELS,
        "enable_macd_divergence": T_UPSTREAM_ENABLE_MACD_DIVERGENCE,
        "require_settled_subseg": T_UPSTREAM_REQUIRE_SETTLED_SUBSEG,
    }


def _v3_upstream_orchestrator_config(
    require_settled: bool = V3_REQUIRE_SETTLED,
) -> dict[str, int | bool | None]:
    """v3 臂上游 organic_signals.StreamingSignalReader 内部构造 RecursiveOrchestrator 的实际实参。"""
    return {
        "max_levels": getattr(_organic_signals, "MAX_LEVELS", None),
        "enable_macd_divergence": True,
        "require_settled_subseg": require_settled,
    }


def _read_pre_clean_raw_max_bars() -> int | None:
    """读取 fugue_v2_full_backtest.load_ohlc 在清洗前生效的原始 bar 上限（BT_MAX_BARS）。"""
    raw = os.environ.get("BT_MAX_BARS")
    if raw is None or raw.strip() == "":
        return None
    try:
        val = int(raw)
    except ValueError:
        return None
    return val if val > 0 else None


def resolve_funding_profile(cli_value: str | None = None) -> str | None:
    """读取显式选择的签署资金 profile（--funding-profile 优先于 NC_FUNDING_PROFILE；无默认）。"""
    if cli_value is not None:
        return cli_value
    return os.environ.get("NC_FUNDING_PROFILE")


def _display_source_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path)


def load_symbol_ohlc(
    path: Path, max_bars: int | None
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    """加载、清洗（清洗前受 env BT_MAX_BARS 限制）并按位置参数 max_bars 清洗后截断 OHLC。"""
    if max_bars is not None and max_bars < 0:
        raise ValueError(f"max_bars 须为非负整数，得 {max_bars}")
    opens, highs, lows, closes, _years = load_ohlc(path)
    if max_bars:
        opens, highs, lows, closes = (x[:max_bars] for x in (opens, highs, lows, closes))
    n = len(closes)
    if not (len(opens) == len(highs) == len(lows) == n):
        raise ValueError(
            f"OHLC 序列长度不一致: opens={len(opens)} highs={len(highs)} "
            f"lows={len(lows)} closes={n}"
        )
    if n == 0:
        raise ValueError(f"清洗/截断后无有效 OHLC bar（source={_display_source_path(path)}）")
    return tuple(opens), tuple(highs), tuple(lows), tuple(closes)


def hash_ohlc_series(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> tuple[str, int]:
    """按实际送入两臂的顺序对清洗/截断后 OHLC 计算大端 IEEE-754 binary64 SHA-256。"""
    n = len(closes)
    if not (len(opens) == len(highs) == len(lows) == n):
        raise ValueError("OHLC 序列长度不一致")
    digest = hashlib.sha256()
    for o, h, l, c in zip(opens, highs, lows, closes):
        o_f, h_f, l_f, c_f = float(o), float(h), float(l), float(c)
        if not (
            math.isfinite(o_f)
            and math.isfinite(h_f)
            and math.isfinite(l_f)
            and math.isfinite(c_f)
        ):
            raise ValueError("OHLC 含非有限值")
        digest.update(struct.pack(">dddd", o_f, h_f, l_f, c_f))
    return f"sha256:{digest.hexdigest()}", n


def extract_t_bsps(opens, highs, lows, closes, *, return_meta: bool = False):
    """orchestrator 产段（a₀）→ run_recursive_t → T 全塔买卖点。

    T 算子本体为纯结构路径（零 MACD），不要求也不读取资金记录；
    上游 RecursiveOrchestrator 按 _t_upstream_orchestrator_config() 构造。
    默认返回 (bsps, n_segs)，bsps 行 = (kind, bar, price, level)；
    return_meta=True 时返回 (bsps, n_segs, t_meta)。
    kind ∈ {type1_buy/sell, type2_*, type3_*}; level 0 = 最低走势级别（线段构成）。
    """
    orch_cfg = _t_upstream_orchestrator_config()
    orch = R.RecursiveOrchestrator(**orch_cfg)
    for o, h, l, c in zip(opens, highs, lows, closes):
        orch.process_bar(o, h, l, c)
    segs = orch.current_segments()
    # SegmentTuple[0] = (s0, s1, i0, i1, dir, high, low, confirmed, kind)
    seg_in = [
        (s[0][2], s[0][3], s[0][4], s[0][5], s[0][6], s[0][7], s[0][8] == "settled")
        for s in segs
    ]
    bsps = R.run_recursive_t(seg_in)  # [(kind, bar, price, level)]
    if not return_meta:
        return bsps, len(segs)
    meta = {
        "mode": "structure",
        "operator_uses_macd": False,
        "upstream_orchestrator": dict(orch_cfg),
    }
    return bsps, len(segs), meta


def extract_v3_nf(
    opens,
    highs,
    lows,
    closes,
    *,
    funding_profile: str | None | object = _UNSET,
    return_meta: bool = False,
):
    """compute_organic_signals → FugueV3Stream → nf fire 明细。

    仅此处将显式选择的签署资金 profile 传给 FugueV3Stream；未提供时由 FFI 报
    AwaitingPolicy{funding_record}，不选默认资金。
    默认返回 (nf_fires, n_bars)，nf_fires 行 = (bar, ladder, is_sell, price)；
    return_meta=True 时返回 (nf_fires, n_bars, v3_meta)。
    """
    effective_profile = (
        resolve_funding_profile() if funding_profile is _UNSET else funding_profile
    )
    stream = R.FugueV3Stream(
        floor_ladder=FLOOR_LADDER, funding_profile=effective_profile
    )
    dir_flips: list = []
    require_settled = V3_REQUIRE_SETTLED
    tape = compute_organic_signals(
        opens, highs, lows, closes, dir_flips=dir_flips, require_settled=require_settled
    )
    flips_by_bar: dict = {}
    for (bar, lad, d) in dir_flips:
        flips_by_bar.setdefault(bar, []).append((lad, d))
    for i, s in enumerate(tape):
        push_signal(stream, s, flips_by_bar.get(i, []))
    res = stream.finish()
    if not return_meta:
        return res["nf_fires"], len(tape)
    meta = {
        "funding_profile": effective_profile,
        "funding_record": res.get("funding_record"),
        "q_total": res.get("q_total"),
        "floor_ladder": FLOOR_LADDER,
        "upstream_signal_require_settled": require_settled,
        "upstream_orchestrator": _v3_upstream_orchestrator_config(require_settled),
    }
    return res["nf_fires"], len(tape), meta


def _price_dist(prices):
    """价格分布摘要（count/min/max/样本）。"""
    if not prices:
        return {"n": 0}
    sp = sorted(prices)
    return {"n": len(sp), "min": round(sp[0], 4), "max": round(sp[-1], 4),
            "sample": [round(p, 4) for p in sp[:5]]}


def diagnose(sym, t_bsps, nf_fires):
    """诊断: T levels / nf ladders 的 price 分布 + level 映射验证。"""
    print(f"\n===== [{sym}] 诊断 =====", flush=True)
    # T by level（type1+type3 分 buy/sell；type2 单列）
    print("  T 算子（本体纯结构）by level:")
    t_levels = sorted({b[3] for b in t_bsps})
    for lv in t_levels:
        for tag, pred in (("t1+t3 sell", lambda k: k in ("type1_sell", "type3_sell")),
                          ("t1+t3 buy", lambda k: k in ("type1_buy", "type3_buy")),
                          ("type2", lambda k: k.startswith("type2"))):
            pr = [b[2] for b in t_bsps if b[3] == lv and pred(b[0])]
            if pr:
                print(f"    level{lv}(↔ladder{lv + LADDER_MOVE}) {tag:11} {_price_dist(pr)}")
    # nf by ladder
    print("  v3 nf fire by ladder:")
    nf_ladders = sorted({f[1] for f in nf_fires})
    if not nf_ladders:
        print("    (无 v3 nf fire：执行成功，空参照样本)")
    for lad in nf_ladders:
        for tag, sell in (("nf_sell", True), ("nf_buy", False)):
            pr = [f[3] for f in nf_fires if f[1] == lad and f[2] == sell]
            if pr:
                print(f"    ladder{lad}({LAD_NAME.get(lad, '?')}) {tag:7} {_price_dist(pr)}")


def _match_prices(t_prices, nf_prices, rel_tol):
    """贪心双指针 price 匹配（升序）。返回 (n_matched, t_only_prices, nf_only_prices）。

    同段极值应 bit-exact ⇒ rel_tol 极小; 双指针对于近重合集合无歧义。
    """
    t = sorted(t_prices)
    n = sorted(nf_prices)
    i = j = 0
    matched = 0
    t_only: list = []
    nf_only: list = []
    while i < len(t) and j < len(n):
        denom = max(abs(n[j]), 1e-9)
        if abs(t[i] - n[j]) <= rel_tol * denom:
            matched += 1
            i += 1
            j += 1
        elif t[i] < n[j]:
            t_only.append(t[i])
            i += 1
        else:
            nf_only.append(n[j])
            j += 1
    t_only.extend(t[i:])
    nf_only.extend(n[j:])
    return matched, t_only, nf_only


def compare(sym, t_bsps, nf_fires):
    """by (ladder, side) price 匹配对照矩阵。返回结构化结果。"""
    rows = []
    nf_ladders = {f[1] for f in nf_fires}
    t_ladders = {b[3] + LADDER_MOVE for b in t_bsps if b[0].startswith(("type1", "type3"))}
    all_ladders = sorted(nf_ladders | t_ladders)
    for lad in all_ladders:
        lv = lad - LADDER_MOVE
        for side_tag, is_sell in (("sell", True), ("buy", False)):
            t_kinds = ("type1_sell", "type3_sell") if is_sell else ("type1_buy", "type3_buy")
            t_pr = [b[2] for b in t_bsps if b[3] == lv and b[0] in t_kinds]
            nf_pr_raw = [f[3] for f in nf_fires if f[1] == lad and f[2] == is_sell]
            # nf 去重（范畴对齐）: nf fire 是逐 bar 事件流(同结构点可多次 fire), T BSP 是去重
            # 结构点集。按 price 去重把 nf 投影回点集范畴, 才与 T 可比; n_nf_raw 另列保留频率维度。
            nf_pr = sorted(set(nf_pr_raw))
            if not t_pr and not nf_pr:
                continue
            matched, t_only, nf_only = _match_prices(t_pr, nf_pr, PRICE_REL_TOL)
            rows.append({
                "ladder": lad, "level": lv, "name": LAD_NAME.get(lad, "?"), "side": side_tag,
                "n_T": len(t_pr), "n_nf": len(nf_pr), "n_nf_raw": len(nf_pr_raw),
                "matched": matched, "t_only": len(t_only), "nf_only": len(nf_only),
                "t_match_rate": round(matched / len(t_pr), 3) if t_pr else None,
                "nf_match_rate": round(matched / len(nf_pr), 3) if nf_pr else None,
            })
    # type2（T 特有）计数
    n_type2 = sum(1 for b in t_bsps if b[0].startswith("type2"))
    return {"rows": rows, "n_type2": n_type2}


def regime_segments(closes, n_seg=5):
    """价格序列按等长 bar 窗口分段, 每段标 bull/bear/range（首尾涨跌幅 ±10% 阈值）。"""
    n = len(closes)
    if n < n_seg:
        return []
    out = []
    w = n // n_seg
    for s in range(n_seg):
        lo = s * w
        hi = (s + 1) * w if s < n_seg - 1 else n
        ret = closes[hi - 1] / closes[lo] - 1 if closes[lo] else 0.0
        kind = "bull" if ret > 0.10 else "bear" if ret < -0.10 else "range"
        out.append({"bar_lo": lo, "bar_hi": hi, "ret_pct": round(ret * 100, 1), "regime": kind})
    return out


def regime_nf_breakdown(nf_fires, regimes):
    """nf fire 按 raw bar 落入 regime 段统计（nf 有 raw bar, 可定位）。"""
    if not regimes:
        return []
    out = []
    for rg in regimes:
        cnt = sum(1 for f in nf_fires if rg["bar_lo"] <= f[0] < rg["bar_hi"])
        out.append({**rg, "n_nf": cnt})
    return out


def run_symbol(
    sym,
    max_bars,
    diag_only,
    *,
    funding_profile: str | None | object = _UNSET,
):
    path = SYMBOL_FILES[sym]
    opens, highs, lows, closes = load_symbol_ohlc(path, max_bars)
    input_hash, n = hash_ohlc_series(opens, highs, lows, closes)
    print(f"\n[{sym}] bars={n:,} input_hash={input_hash}", flush=True)

    t0 = time.time()
    t_bsps, n_segs, t_meta = extract_t_bsps(
        opens, highs, lows, closes, return_meta=True
    )
    print(
        f"[{sym}] T: {time.time() - t0:.1f}s segs={n_segs:,} BSPs={len(t_bsps):,} "
        f"upstream_max_levels={t_meta['upstream_orchestrator']['max_levels']}",
        flush=True,
    )

    t1 = time.time()
    nf_fires, n_tape, v3_meta = extract_v3_nf(
        opens,
        highs,
        lows,
        closes,
        funding_profile=funding_profile,
        return_meta=True,
    )
    if n_tape != n:
        raise RuntimeError(
            f"[{sym}] T/v3 输入条数不一致: cleaned={n}, v3_tape={n_tape}"
        )
    print(
        f"[{sym}] v3 nf: {time.time() - t1:.1f}s fires={len(nf_fires):,} "
        f"upstream_max_levels={v3_meta['upstream_orchestrator']['max_levels']} "
        f"funding={v3_meta['funding_record']} q_total={v3_meta['q_total']}",
        flush=True,
    )

    diagnose(sym, t_bsps, nf_fires)
    if diag_only:
        return None

    cmp = compare(sym, t_bsps, nf_fires)
    regimes = regime_segments(closes)
    cmp["regime"] = regime_nf_breakdown(nf_fires, regimes)
    cmp["symbol"] = sym
    cmp["n_bars"] = n
    cmp["n_segs"] = n_segs
    cmp["n_t_bsps"] = len(t_bsps)
    cmp["n_nf_fires"] = len(nf_fires)
    cmp["source_file"] = _display_source_path(path)
    cmp["input_hash"] = input_hash
    cmp["input_encoding"] = INPUT_ENCODING
    cmp["input_count"] = n
    cmp["t_mode"] = t_meta["mode"]
    cmp["t_operator_uses_macd"] = t_meta["operator_uses_macd"]
    cmp["t_upstream_orchestrator"] = t_meta["upstream_orchestrator"]
    cmp["v3_funding_profile"] = v3_meta["funding_profile"]
    cmp["v3_funding_record"] = v3_meta["funding_record"]
    cmp["v3_q_total"] = v3_meta["q_total"]
    cmp["v3_floor_ladder"] = v3_meta["floor_ladder"]
    cmp["v3_upstream_signal_require_settled"] = v3_meta["upstream_signal_require_settled"]
    cmp["v3_upstream_orchestrator"] = v3_meta["upstream_orchestrator"]
    return cmp


def resolve_report_path(output_dir: Path, run_id: str) -> Path:
    """为单次运行分配独立报告路径，物理隔离历史原件及其他运行。"""
    target = output_dir / RUNS_DIR_NAME / run_id / OUT_MD.name
    if target.resolve() == OUT_MD.resolve():
        raise ValueError(f"新报告路径不得指向历史原件: {OUT_MD}")
    return target


def _format_input_limits(input_limits: dict[str, int | None]) -> str:
    """将两阶段输入上限（清洗前 BT_MAX_BARS 与清洗后 max_bars）格式化为中性说明。"""
    pre = input_limits.get("pre_clean_raw_max_bars_env")
    post = input_limits.get("post_clean_max_bars_arg")
    pre_part = (
        f"清洗前原始上限 env BT_MAX_BARS={pre:,}"
        if pre is not None
        else "清洗前无原始上限（env BT_MAX_BARS 未设）"
    )
    post_part = (
        f"清洗后截断前 {post:,} bar（位置参数 max_bars={post}）"
        if post is not None
        else "清洗后无截断（未设位置参数 max_bars）"
    )
    return f"{pre_part}；{post_part}"


def _format_rate(
    matched: int, denom: int, rate: float | None, *, empty_label: str
) -> str:
    """将单向重合率格式化为“分子/分母 (百分比)”或显式不适用说明（不输出裸 None）。"""
    if denom <= 0 or rate is None:
        return empty_label
    pct = matched / denom * 100.0
    return f"{matched}/{denom} ({pct:.1f}%)"


def _build_symbol_observation(r: dict) -> dict:
    """构造单标的的中性观测摘要（正文与 JSON 元数据共用同一来源）。"""
    rows = r.get("rows", [])
    n_t_compared = sum(row["n_T"] for row in rows)
    n_nf_dedup = sum(row["n_nf"] for row in rows)
    n_matched = sum(row["matched"] for row in rows)
    n_t_only = sum(row["t_only"] for row in rows)
    n_nf_only = sum(row["nf_only"] for row in rows)
    n_nf_fires = r["n_nf_fires"]
    n_t_type2 = r["n_type2"]

    t_overlap_rate = round(n_matched / n_t_compared, 3) if n_t_compared > 0 else None
    v3_overlap_rate = round(n_matched / n_nf_dedup, 3) if n_nf_dedup > 0 else None

    if n_nf_fires == 0:
        reference_status = "empty_v3_reference"
        if n_t_compared > 0:
            interpretation = (
                f"执行成功（无参照样本 / 空参照）：v3 臂产出 0 条 nf fire；"
                f"T 臂产出 {n_t_compared} 个可对照结构点（type1+type3，不含 {n_t_type2} 个 type2），"
                f"非空 T 侧重合率按 0/{n_t_compared} = 0.0% 计（仅描述 T 与空参照集之差集），"
                f"v3 侧因 0 分母记作“不适用（无 v3 样本）”。"
                f"空参照不可用于判定 T 误判/漏判或估计结构替代率，且与标的运行失败（非零退出）及 --diag 模式区分。"
            )
        else:
            interpretation = (
                f"执行成功（无参照样本 / 空参照）：v3 臂产出 0 条 nf fire 且 T 臂产出 0 个 type1+type3 对照点"
                f"（type2={n_t_type2}），两侧分母均为 0，重合率均不适用；与标的运行失败及 --diag 模式区分。"
            )
    else:
        reference_status = "non_empty_v3_reference"
        if n_t_compared > 0:
            t_pct = n_matched / n_t_compared * 100.0
            v3_pct = n_matched / n_nf_dedup * 100.0 if n_nf_dedup > 0 else 0.0
            interpretation = (
                f"执行成功（非空参照样本）：v3 臂产出 {n_nf_fires} 条 nf fire（去重后 {n_nf_dedup} 个参照点），"
                f"T 臂产出 {n_t_compared} 个可对照结构点（不含 {n_t_type2} 个 type2）；"
                f"合计重合 {n_matched} 个（T 侧重合率 {n_matched}/{n_t_compared} = {t_pct:.1f}%，"
                f"v3 侧重合率 {n_matched}/{n_nf_dedup} = {v3_pct:.1f}%），"
                f"仅T侧={n_t_only}、仅v3侧={n_nf_only}（均为对称差集计数，非误判/漏判判定）。"
            )
        else:
            interpretation = (
                f"执行成功（非空参照样本，T 侧无 type1+type3 对照点）：v3 臂产出 {n_nf_fires} 条 nf fire"
                f"（去重后 {n_nf_dedup} 个参照点），T 臂产出 0 个 type1+type3 对照点（type2={n_t_type2}）；"
                f"T 侧因 0 分母记作“不适用（无 T 样本）”，v3 侧重合率为 0/{n_nf_dedup} = 0.0%（仅描述差集）。"
            )

    return {
        "execution_status": "succeeded",
        "reference_status": reference_status,
        "n_bars": r["n_bars"],
        "n_segs": r["n_segs"],
        "n_t_bsps": r["n_t_bsps"],
        "n_t_compared": n_t_compared,
        "n_t_type2": n_t_type2,
        "n_nf_fires": n_nf_fires,
        "n_nf_dedup": n_nf_dedup,
        "n_matched": n_matched,
        "n_t_only": n_t_only,
        "n_nf_only": n_nf_only,
        "t_overlap_rate": t_overlap_rate,
        "v3_overlap_rate": v3_overlap_rate,
        "interpretation": interpretation,
    }


def build_provenance(
    results: Sequence[dict],
    max_bars: int | None,
    *,
    run_id: str,
    requested_symbols: Sequence[str] | None = None,
    failed: Sequence[dict[str, str]] | None = None,
    funding_profile: str | None = None,
) -> dict:
    """构造 ADR 0039 §四.4 观察出处与分臂实际运行条件记录。"""
    valid = [r for r in results if r is not None]
    failed_list = list(failed or [])
    succeeded_syms = [r["symbol"] for r in valid]
    req_syms = (
        list(requested_symbols)
        if requested_symbols is not None
        else [*succeeded_syms, *(f["symbol"] for f in failed_list)]
    )
    first = valid[0] if valid else {}
    v3_funding_profile = (
        funding_profile if funding_profile is not None else first.get("v3_funding_profile")
    )
    t_orch = dict(first.get("t_upstream_orchestrator") or _t_upstream_orchestrator_config())
    v3_require_settled = first.get("v3_upstream_signal_require_settled", V3_REQUIRE_SETTLED)
    v3_orch = dict(
        first.get("v3_upstream_orchestrator")
        or _v3_upstream_orchestrator_config(v3_require_settled)
    )
    return {
        "schema": PROVENANCE_SCHEMA,
        "role": "frozen_shadow_research_comparison",
        "admission_effect": "none",
        "authority_note": AUTHORITY_NOTE,
        "run_id": run_id,
        "run_status": "partial" if failed_list else "complete",
        "historical_original": _display_source_path(OUT_MD),
        "cores": {
            "t_arm": {
                "arm_id": "OE11",
                "core_id": T_CORE_ID,
                "pyo3_entry": "newchan_rust.run_recursive_t",
                "mode": first.get("t_mode", "structure"),
                "operator_uses_macd": first.get("t_operator_uses_macd", False),
                "funding_required": False,
                "upstream_segment_core_id": UPSTREAM_SEG_CORE_ID,
                "upstream_orchestrator": t_orch,
            },
            "v3_arm": {
                "arm_id": "OE10",
                "core_id": V3_CORE_ID,
                "pyo3_entry": "newchan_rust.FugueV3Stream",
                "upstream_signal_entry": "analysis.organic_signals.compute_organic_signals",
                "upstream_signal_require_settled": v3_require_settled,
                "upstream_segment_core_id": UPSTREAM_SEG_CORE_ID,
                "upstream_orchestrator": v3_orch,
                "floor_ladder": first.get("v3_floor_ladder", FLOOR_LADDER),
                "funding_required": True,
                "funding_profile": v3_funding_profile,
                "funding_record": first.get("v3_funding_record"),
                "q_total": first.get("v3_q_total"),
            },
        },
        "selected_conditions": {
            "requested_symbols": req_syms,
            "succeeded_symbols": succeeded_syms,
            "failed_symbols": failed_list,
            "input_limits": {
                "pre_clean_raw_max_bars_env": _read_pre_clean_raw_max_bars(),
                "post_clean_max_bars_arg": max_bars if max_bars else None,
            },
            "comparison": {
                "ladder_move": LADDER_MOVE,
                "price_rel_tol": PRICE_REL_TOL,
            },
        },
        "inputs": {
            r["symbol"]: {
                "source_file": r.get("source_file"),
                "shared_by_arms": ["t_arm", "v3_arm"],
                "input_encoding": r.get("input_encoding", INPUT_ENCODING),
                "input_count": r.get("input_count", r["n_bars"]),
                "input_hash": r.get("input_hash"),
            }
            for r in valid
        },
        "observations": {
            r["symbol"]: _build_symbol_observation(r)
            for r in valid
        },
    }


def write_report(
    results,
    max_bars,
    *,
    run_id: str | None = None,
    output_dir: Path | None = None,
    requested_symbols: Sequence[str] | None = None,
    failed: Sequence[dict[str, str]] | None = None,
    funding_profile: str | None = None,
) -> Path:
    valid = [r for r in results if r is not None]
    if not valid:
        raise ValueError("无成功标的，拒绝写入空报告")
    actual_run_id = run_id or str(uuid4())
    actual_output_dir = Path(output_dir) if output_dir is not None else OUT_MD.parent
    provenance = build_provenance(
        valid,
        max_bars,
        run_id=actual_run_id,
        requested_symbols=requested_symbols,
        failed=failed,
        funding_profile=funding_profile,
    )
    t_info = provenance["cores"]["t_arm"]
    t_orch = t_info["upstream_orchestrator"]
    v3_info = provenance["cores"]["v3_arm"]
    v3_orch = v3_info["upstream_orchestrator"]
    cond = provenance["selected_conditions"]
    limits_desc = _format_input_limits(cond["input_limits"])
    cmp_cfg = cond["comparison"]
    inputs = provenance["inputs"]
    observations = provenance["observations"]

    lines = [
        "# T 算子（算子本体纯结构、零 MACD）vs v3 nf 信号 L2 对照\n",
        "**设计依据**: `docs/unified_recursive_operator_T.md` §6.6/§6.7"
        "（T 算子本体纯结构买卖点与 v3 nf 信号集的对称差集对照）。",
        "**认识论等级**: L2（真实数据、可否证）。",
        f"**输入上限**: {limits_desc}。",
        f"**对照轴**: price 匹配（坐标无关，`price_rel_tol={cmp_cfg['price_rel_tol']}`）"
        f"+ level 映射（`T.level+{cmp_cfg['ladder_move']}=v3.ladder`）+ 极性。",
        "**口径边界**: nf fire = 区间套（candidate type1/3 武装+次级别证据触发，按 price 去重后与 T 点集对齐，`n_nf_raw` 另列保留频率）；"
        "T 对照用 type1+type3；type2（跨级投影）为 T 特有单列。"
        "`T_only(仅T侧)` 与 `nf_only(仅v3侧)` 均为对称差集计数，不作误判/漏判判定。",
        f"**上游参数范围**: “纯结构、零 MACD”仅限定于 T 算子本体（`{t_info['pyo3_entry']}`, "
        f"`operator_uses_macd={t_info['operator_uses_macd']}`）；"
        f"T 臂上游 `{t_info['upstream_segment_core_id']}` 实参 "
        f"`max_levels={t_orch['max_levels']}`/`enable_macd_divergence={t_orch['enable_macd_divergence']}`/"
        f"`require_settled_subseg={t_orch['require_settled_subseg']}`，"
        f"v3 臂上游 `{v3_info['upstream_segment_core_id']}` 实参 "
        f"`max_levels={v3_orch['max_levels']}`/`enable_macd_divergence={v3_orch['enable_macd_divergence']}`/"
        f"`require_settled_subseg={v3_orch['require_settled_subseg']}`（分臂实录见下方出处块）。",
        f"**研究边界**: {provenance['authority_note']}\n",
        "## 观察出处与运行条件（ADR 0039 §四.4）\n",
        f"- **run_id**: `{provenance['run_id']}`（状态: `{provenance['run_status']}`）",
        f"- **T 臂（{t_info['arm_id']}）**: `{t_info['core_id']}` via `{t_info['pyo3_entry']}`"
        f"（算子本体: `mode={t_info['mode']}`, `operator_uses_macd={t_info['operator_uses_macd']}`, "
        f"`funding_required={t_info['funding_required']}`；"
        f"上游 a₀: `{t_info['upstream_segment_core_id']}` 实参 "
        f"`max_levels={t_orch['max_levels']}`, "
        f"`enable_macd_divergence={t_orch['enable_macd_divergence']}`, "
        f"`require_settled_subseg={t_orch['require_settled_subseg']}`）",
        f"- **v3 臂（{v3_info['arm_id']}）**: `{v3_info['core_id']}` via `{v3_info['pyo3_entry']}`"
        f"（`floor_ladder={v3_info['floor_ladder']}`, `funding_required={v3_info['funding_required']}`, "
        f"`funding_profile={v3_info['funding_profile']}`, "
        f"`funding_record={v3_info['funding_record']}`, `q_total={v3_info['q_total']}`；"
        f"上游信号: `{v3_info['upstream_signal_entry']}` "
        f"`require_settled={v3_info['upstream_signal_require_settled']}` / "
        f"`{v3_info['upstream_segment_core_id']}` 实参 "
        f"`max_levels={v3_orch['max_levels']}`, "
        f"`enable_macd_divergence={v3_orch['enable_macd_divergence']}`, "
        f"`require_settled_subseg={v3_orch['require_settled_subseg']}`）",
        f"- **输入上限**: {limits_desc}",
        f"- **历史原件**: `{provenance['historical_original']}`（原位保留，本运行未修改）",
        f"- **标的汇总**: 成功 {len(cond['succeeded_symbols'])}/{len(cond['requested_symbols'])} "
        f"({', '.join(cond['succeeded_symbols']) or '无'})；失败 {len(cond['failed_symbols'])} "
        f"({', '.join(f['symbol'] for f in cond['failed_symbols']) or '无'})\n",
        "```json",
        json.dumps(provenance, ensure_ascii=False, indent=2),
        "```\n",
    ]
    if cond["failed_symbols"]:
        lines.append("## 失败标的（本次未产出对照行）\n")
        lines.append("| 标的 | 错误类型 | 原因 |")
        lines.append("|---|---|---|")
        for item in cond["failed_symbols"]:
            reason = item["reason"].replace("\n", " ").replace("|", "\\|")
            lines.append(f"| {item['symbol']} | {item['error_type']} | {reason} |")
        lines.append("")
    for r in valid:
        sym = r["symbol"]
        obs = observations[sym]
        inp = inputs[sym]
        lines.append(
            f"\n## {sym}  (bars={obs['n_bars']:,}, segs={obs['n_segs']:,}, "
            f"T BSP={obs['n_t_bsps']:,}, nf fire={obs['n_nf_fires']:,}, "
            f"T type2={obs['n_t_type2']:,})\n"
        )
        if inp.get("input_hash"):
            lines.append(
                f"**输入出处**: `input_hash={inp['input_hash']}`, "
                f"`input_count={inp['input_count']}`, "
                f"`encoding={inp['input_encoding']}`, "
                f"`shared_by={'+'.join(inp['shared_by_arms'])}`, "
                f"`source={inp['source_file'] or ''}`, "
                f"`v3_funding={v3_info['funding_record']}` (`q_total={v3_info['q_total']}`)\n"
            )
        lines.append(
            f"**样本状态**: `execution_status={obs['execution_status']}`, "
            f"`reference_status={obs['reference_status']}` — {obs['interpretation']}\n"
        )
        if r["rows"]:
            lines.append(
                "| ladder | 级别 | side | n_T(t1+t3) | n_nf(去重) | n_nf_raw(fire) | matched | "
                "T_only(仅T侧) | nf_only(仅v3侧) | T侧重合率 | v3侧重合率 |"
            )
            lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
            for row in r["rows"]:
                t_rate_str = _format_rate(
                    row["matched"],
                    row["n_T"],
                    row["t_match_rate"],
                    empty_label="不适用（无 T 样本）",
                )
                v3_rate_str = _format_rate(
                    row["matched"],
                    row["n_nf"],
                    row["nf_match_rate"],
                    empty_label="不适用（无 v3 样本）",
                )
                lines.append(
                    f"| {row['ladder']} | {row['name']} | {row['side']} | {row['n_T']} | "
                    f"{row['n_nf']} | {row['n_nf_raw']} | {row['matched']} | {row['t_only']} | "
                    f"{row['nf_only']} | {t_rate_str} | {v3_rate_str} |"
                )
        else:
            lines.append("（无可对照行：T 臂 type1+type3 与 v3 nf fire 均为空）")
        if r["regime"]:
            lines.append("\n**regime 分布（nf fire by raw-bar 段）**:")
            lines.append("| 段 | bar 区间 | 收益% | regime | nf fire 数 |")
            lines.append("|---|---|---|---|---|")
            for i, rg in enumerate(r["regime"]):
                lines.append(f"| {i} | [{rg['bar_lo']:,},{rg['bar_hi']:,}) | {rg['ret_pct']} | "
                             f"{rg['regime']} | {rg['n_nf']} |")
    report_path = resolve_report_path(actual_output_dir, actual_run_id)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\n报告已写入 {report_path.resolve()}", flush=True)
    return report_path


def _parse_max_bars(raw: str) -> int | None:
    if raw == "":
        return None
    try:
        val = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"max_bars 须为整数，得 {raw!r}") from exc
    if val < 0:
        raise argparse.ArgumentTypeError(f"max_bars 须为非负整数，得 {val}")
    return val if val > 0 else None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="T 算子（OE11 run_recursive_t）vs v3 nf 信号（OE10 FugueV3Stream）L2 纯研究对照"
    )
    parser.add_argument(
        "symbols",
        nargs="?",
        default=None,
        help="逗号分隔标的（默认 8 标的）",
    )
    parser.add_argument(
        "max_bars",
        nargs="?",
        default=None,
        type=_parse_max_bars,
        help="清洗后截断 bar 上限（0 或留空表示清洗后不截断；清洗前原始上限见 env BT_MAX_BARS）",
    )
    parser.add_argument(
        "--diag",
        action="store_true",
        help="只跑诊断不写报告",
    )
    parser.add_argument(
        "--funding-profile",
        default=None,
        help="ADR 0040 签署资金 profile（如 P0；覆盖 NC_FUNDING_PROFILE；仅传给 v3 核，无默认）",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUT_MD.parent,
        help="新报告根目录（默认 analysis/，每次写入 runs/<run_id>/T_vs_v3_comparison.md）",
    )
    return parser.parse_intermixed_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    ns = parse_args(argv)
    if ns.symbols is None:
        syms = list(DEFAULT_SYMS)
    else:
        syms = list(
            dict.fromkeys(
                s.strip().upper() for s in ns.symbols.split(",") if s.strip()
            )
        )
        if not syms:
            print("错误: 未指定有效标的", file=sys.stderr)
            return 1

    max_bars = ns.max_bars
    diag_only = ns.diag
    funding_profile = resolve_funding_profile(ns.funding_profile)
    run_id = str(uuid4())

    results: list[dict] = []
    succeeded: list[str] = []
    failed: list[dict[str, str]] = []

    for sym in syms:
        if sym not in SYMBOL_FILES:
            reason = f"标的 {sym} 无数据映射"
            print(f"[{sym}] 失败: UnmappedSymbol: {reason}", file=sys.stderr)
            failed.append({"symbol": sym, "error_type": "UnmappedSymbol", "reason": reason})
            continue
        try:
            res = run_symbol(
                sym,
                max_bars,
                diag_only,
                funding_profile=funding_profile,
            )
            succeeded.append(sym)
            if res is not None:
                results.append(res)
        except Exception as e:  # noqa: BLE001
            print(f"[{sym}] 失败: {type(e).__name__}: {e}", file=sys.stderr)
            traceback.print_exc()
            failed.append({"symbol": sym, "error_type": type(e).__name__, "reason": str(e)})

    ok_str = ",".join(succeeded) if succeeded else "无"
    fail_str = ",".join(f["symbol"] for f in failed) if failed else "无"
    print(
        f"\n[run_id={run_id}] 完成: 成功={len(succeeded)}/{len(syms)} ({ok_str}), "
        f"失败={len(failed)}/{len(syms)} ({fail_str})",
        flush=True,
    )

    if diag_only:
        print(f"[run_id={run_id}] --diag 模式：未写入报告", flush=True)
    elif results:
        saved = write_report(
            results,
            max_bars,
            run_id=run_id,
            output_dir=ns.output_dir,
            requested_symbols=syms,
            failed=failed,
            funding_profile=funding_profile,
        )
        if failed:
            print(
                f"[run_id={run_id}] 部分成功：报告仅含成功标的（{saved.resolve()}），"
                f"失败标的见报告与 stderr，退出码 1",
                file=sys.stderr,
            )
    else:
        print(
            f"[run_id={run_id}] 无成功标的，未写入新报告"
            f"（历史原件 {_display_source_path(OUT_MD)} 未修改，不可当作本次结果）",
            file=sys.stderr,
        )

    return 0 if (not failed and succeeded) else 1


if __name__ == "__main__":
    sys.exit(main())
