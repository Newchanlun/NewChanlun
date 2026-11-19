"""统一递归算子 T（纯结构, 零 MACD）vs v3(fugue_v3) nf 信号 L2 对照 — §6.6 阶段2。

设计依据: docs/unified_recursive_operator_T.md §6.6/§6.7（编排者裁决: 纯结构优先渐进,
阶段2 与 v3 nf 对照实测纯拓扑替代率, L2, 否定性结果定位缺口）。

对照轴（关键设计决策, 见模块末 NOTE）:
  - **price 匹配**（坐标无关）: T BSP 与 nf fire 的 price 都是同一段极值。Stroke.i0/i1
    是 K线合并坐标, nf_fires.bar 是 raw bar 序号——两者坐标系不同, bar 不可直接相减
    （记忆 current_strokes_i1_merged_coord）。price 是买卖点本质标识且坐标无关 ⇒ 主匹配轴。
  - **level 映射**: T.level+3 == v3.ladder（segment=ladder2 不在 T 递归序列中,
    T 从 move/L1=ladder3 起; 设计文档 §5.2 bug-a）。脚本输出实测分布验证此映射, 不硬编码。
  - **极性**: T type1_sell/type3_sell ↔ nf is_sell=True; buy ↔ is_sell=False。
  - nf fire 来自 candidate(type1/type3)武装+次级别证据 ⇒ 主对照用 T 的 type1+type3;
    type2(跨级投影)单列为 T 特有。

a₀ 一致性: T 用 orchestrator.current_segments()(confirmed+settled 过滤在 run_recursive_t 内),
  v3 用同配置 orchestrator(compute_organic_signals 内部)。同款 wide 笔 + strict 段 ⇒ a₀ 同源。

认识论等级: L2（真实数据, 可否证）。否定性结果 = 纯结构在某 level/regime 漏判(nf_only)
  或误判(t_only) 的具体位置 = 阶段3 加 MACD 的定位器。

用法:
  NC_FUNDING_PROFILE=P0 .venv/bin/python analysis/t_vs_v3_comparison.py [symbols] [max_bars] [--diag] [--funding-profile PROFILE] [--output-dir DIR]
  symbols: 逗号分隔（默认 8 标的）; max_bars: 采样上限（默认全量，0=全量）; --diag: 只跑诊断不写报告
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
from organic_signals import compute_organic_signals, push_signal  # noqa: E402
from fugue_v2_full_backtest import SYMBOL_FILES, load_ohlc  # noqa: E402

MAX_LEVELS = 6
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
    "纯研究对照产物（ADR 0039 §四.4 / C11.4）；研究匹配率不构成生产准入、"
    "交易许可、资金放行或 TStage 触闸依据，不得被 E/B 读为事实。"
)
_UNSET = object()


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
    """加载、清洗并按 max_bars 截断 OHLC，返回供 T/v3 两臂共享的同一不可变序列。"""
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


def extract_t_bsps(opens, highs, lows, closes):
    """orchestrator 产段（= v3 同款 a₀）→ run_recursive_t → T 全塔买卖点。

    纯结构路径，不要求也不读取资金记录。
    返回 (bsps, n_segs)，bsps 行 = (kind, bar, price, level)。
    kind ∈ {type1_buy/sell, type2_*, type3_*}; level 0 = 最低走势级别（线段构成）。
    """
    orch = R.RecursiveOrchestrator(
        max_levels=MAX_LEVELS, enable_macd_divergence=True, require_settled_subseg=True
    )
    for o, h, l, c in zip(opens, highs, lows, closes):
        orch.process_bar(o, h, l, c)
    segs = orch.current_segments()
    # SegmentTuple[0] = (s0, s1, i0, i1, dir, high, low, confirmed, kind)
    seg_in = [
        (s[0][2], s[0][3], s[0][4], s[0][5], s[0][6], s[0][7], s[0][8] == "settled")
        for s in segs
    ]
    bsps = R.run_recursive_t(seg_in)  # [(kind, bar, price, level)]
    return bsps, len(segs)


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
    tape = compute_organic_signals(
        opens, highs, lows, closes, dir_flips=dir_flips, require_settled=True
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
    print("  T 算子（纯结构）by level:")
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
    t_bsps, n_segs = extract_t_bsps(opens, highs, lows, closes)
    print(f"[{sym}] T: {time.time() - t0:.1f}s segs={n_segs:,} BSPs={len(t_bsps):,}", flush=True)

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
    cmp["v3_funding_profile"] = v3_meta["funding_profile"]
    cmp["v3_funding_record"] = v3_meta["funding_record"]
    cmp["v3_q_total"] = v3_meta["q_total"]
    cmp["v3_floor_ladder"] = v3_meta["floor_ladder"]
    return cmp


def resolve_report_path(output_dir: Path, run_id: str) -> Path:
    """为单次运行分配独立报告路径，物理隔离历史原件及其他运行。"""
    target = output_dir / RUNS_DIR_NAME / run_id / OUT_MD.name
    if target.resolve() == OUT_MD.resolve():
        raise ValueError(f"新报告路径不得指向历史原件: {OUT_MD}")
    return target


def build_provenance(
    results: Sequence[dict],
    max_bars: int | None,
    *,
    run_id: str,
    requested_symbols: Sequence[str] | None = None,
    failed: Sequence[dict[str, str]] | None = None,
    funding_profile: str | None = None,
) -> dict:
    """构造 ADR 0039 §四.4 观察出处与已选条件记录。"""
    valid = [r for r in results if r is not None]
    failed_list = list(failed or [])
    succeeded_syms = [r["symbol"] for r in valid]
    req_syms = (
        list(requested_symbols)
        if requested_symbols is not None
        else [*succeeded_syms, *(f["symbol"] for f in failed_list)]
    )
    first = valid[0] if valid else {}
    bt_max_raw = os.environ.get("BT_MAX_BARS")
    bt_max_env = bt_max_raw if bt_max_raw not in (None, "", "0") else None
    v3_funding_profile = (
        funding_profile if funding_profile is not None else first.get("v3_funding_profile")
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
                "upstream_segment_core_id": UPSTREAM_SEG_CORE_ID,
                "mode": "structure",
                "funding_required": False,
            },
            "v3_arm": {
                "arm_id": "OE10",
                "core_id": V3_CORE_ID,
                "pyo3_entry": "newchan_rust.FugueV3Stream",
                "upstream_signal_entry": "analysis.organic_signals.compute_organic_signals",
                "upstream_segment_core_id": UPSTREAM_SEG_CORE_ID,
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
            "max_bars": max_bars if max_bars else None,
            "bt_max_bars_env": bt_max_env,
            "max_levels": MAX_LEVELS,
            "enable_macd_divergence_orchestrator": True,
            "require_settled_subseg": True,
            "require_settled_signals": True,
            "floor_ladder": first.get("v3_floor_ladder", FLOOR_LADDER),
            "ladder_move": LADDER_MOVE,
            "price_rel_tol": PRICE_REL_TOL,
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
    v3_info = provenance["cores"]["v3_arm"]
    cond = provenance["selected_conditions"]
    sampling_desc = "全量" if not max_bars else f"前 {max_bars:,} bar"
    if cond["bt_max_bars_env"] is not None:
        sampling_desc += f"（env BT_MAX_BARS={cond['bt_max_bars_env']}）"
    lines = [
        "# T 算子（纯结构, 零 MACD）vs v3 nf 信号 L2 对照\n",
        "**设计依据**: `docs/unified_recursive_operator_T.md` §6.6 阶段2"
        "（纯结构优先渐进, 否定性结果定位缺口）。",
        "**认识论等级**: L2（真实数据, 可否证）。",
        f"**采样**: {sampling_desc}。",
        "**对照轴**: price 匹配（坐标无关）+ level 映射(T.level+3=v3.ladder) + 极性。",
        "**口径边界**: nf fire = 区间套(candidate type1/3 武装+次级别证据触发); T 对照用 "
        "type1+type3; type2(跨级投影)为 T 特有单列。",
        f"**研究边界**: {AUTHORITY_NOTE}\n",
        "## 观察出处与运行条件（ADR 0039 §四.4）\n",
        f"- **run_id**: `{actual_run_id}`（状态: `{provenance['run_status']}`）",
        f"- **T 臂（OE11）**: `{T_CORE_ID}` via `newchan_rust.run_recursive_t`（a₀: `{UPSTREAM_SEG_CORE_ID}`, mode=`structure`, 无需资金记录）",
        f"- **v3 臂（OE10）**: `{V3_CORE_ID}` via `newchan_rust.FugueV3Stream`（signals: `organic_signals.compute_organic_signals` / `{UPSTREAM_SEG_CORE_ID}`, `floor_ladder={v3_info['floor_ladder']}`, `funding_record={v3_info['funding_record']}`, `q_total={v3_info['q_total']}`）",
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
        lines.append(f"\n## {r['symbol']}  (bars={r['n_bars']:,}, segs={r['n_segs']:,}, "
                     f"T BSP={r['n_t_bsps']:,}, nf fire={r['n_nf_fires']:,}, T type2={r['n_type2']:,})\n")
        if r.get("input_hash"):
            lines.append(
                f"**输入出处**: `input_hash={r['input_hash']}`, "
                f"`input_count={r.get('input_count', r['n_bars'])}`, "
                f"`encoding={r.get('input_encoding', INPUT_ENCODING)}`, "
                f"`shared_by=T+v3`, `source={r.get('source_file', '')}`, "
                f"`v3_funding={r.get('v3_funding_record')}` (`q_total={r.get('v3_q_total')}`)\n"
            )
        lines.append("| ladder | 级别 | side | n_T(t1+t3) | n_nf(去重) | n_nf_raw(fire) | matched | "
                     "T_only(误判?) | nf_only(漏判?) | T匹配率 | nf匹配率 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for row in r["rows"]:
            lines.append(f"| {row['ladder']} | {row['name']} | {row['side']} | {row['n_T']} | "
                         f"{row['n_nf']} | {row['n_nf_raw']} | {row['matched']} | {row['t_only']} | "
                         f"{row['nf_only']} | {row['t_match_rate']} | {row['nf_match_rate']} |")
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
        help="采样 bar 上限（0 或留空表示全量）",
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
