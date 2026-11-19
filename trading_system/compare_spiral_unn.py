"""螺旋引擎 v2（spiral）× 统一必然性引擎（unn）逐 bar bit-exact 对账（架构 §2.4 判据2）。

═══════════════ 验证命题（架构 §2.4 判据2）═══════════════

"操作 = 群作用" 的 L2 否证测试：两臂共享同一 `StreamingSignalReader` 增量信号，
核心差异在群作用路由层（spiral 的 C 翻转走 `GroupAction::ChiralSeam`、E spawn 走
`σ⁻¹∘τ`，复用成本门机件）。两臂在 ADR 0040 资金/级别输入上的实际契约如下：

  - arm_unn（`trading::unified_necessity::UnnStreamCore` / `newchan_rust.UnnStream`）：
    同时读取 `funding-record.json`（`Q_total`）与 `chong-derivation-input.json`
    （`l_start` → `op_ladder = 2 + ℓ`），且引擎约束 `op_ladder ∈ [3, 11)`（segment 非势源）。
  - arm_spiral（`spiral::engine::SpiralEngineCore` / `newchan_rust.SpiralStream`）：
    仅读取 `funding-record.json`（`Q_total`），不消费 `chong-derivation-input.json`
    （其 `PENDING_LO = 3` 为引擎内结构常量）。

角色边界（ADR 0039 §四·4 / ADR 0048 一·C）：本脚本为冻结影子研究对账，不读凭据、
不开域库、不回退默认资金（须经 `NC_FUNDING_PROFILE` 指定签署记录）、不抬升操作级别；
相等仅作研究读数，不构成生产准入、交易许可、资金放行或 TStage 触闸依据。

═══════════════ 退出码与观测范围 ═══════════════

  - exit 1（构造未成 / 未作两臂比较）：标的未注册、未设置 `NC_FUNDING_PROFILE`，或任一臂
    被运行时底层引擎拒绝（如 `AwaitingPolicy`、`op_ladder` 不满足）。尚未加载 OHLC，
    未执行两臂对账，不产生任何对账判决。
  - exit 2（已完成两臂比较，存在分歧）：三项（逐 bar 吐单 / finish trade 表 / final_nav）
    中至少一项不等，输出 `❌ MISMATCH`、全部 `分歧项` 与 `第一处分歧`。
  - exit 0（零根行情）：两臂未步进，只比较 finish trade 表与 final_nav；两者均相等才返回 0。
  - exit 0（有行情，空交易样本）：三项全等但两臂均为 0 笔交易、逐 bar 吐单均为 0；
    仅声明无交易路径上的观测等价，未覆盖交易操作，不得据此宣称验证全部操作。
  - exit 0（已完成两臂比较，有交易样本）：三项全等且有完成交易；仅研究读数，不构成生产准入。

当前仓库基线现状说明（非永久版本表；实际可否构造由运行时引擎与生效签署记录决定）：
  截至当前基线，库内三份生效 ADR 0040 签署记录（`P0` / `P1-hl-testnet` /
  `P0-acceptance-5m`）在 `chong-derivation-input.json` 中均签署 `l_start=L0`
  （`op_ladder=2`），运行时在加载 OHLC 前即会被 `UnnStream` 构造器拒绝（仅 `SpiralStream`
  可完成单臂构造）。本入口不硬编码拒绝任何 profile，也不预设或覆盖级别/资金。

═══════════════ 方法（apples-to-apples）═══════════════

单个 `StreamingSignalReader` 逐 bar 产出 sig（缠论增量信号），**同一 sig** 喂给
`UnnStream` 与 `SpiralStream`（`push_signal` 因两者 `push_bar` 签名相同而通用）。
有行情时逐 bar 比对吐单；无论有无行情，finish 后均比对完整 trade 表与 final_nav。

调用格式（仓库根目录；需提供被两臂运行时共同接纳的 ADR 0040 签署 profile）：
    NC_FUNDING_PROFILE=<profile> PYTHONPATH=src .venv/bin/python trading_system/compare_spiral_unn.py --symbol OKLO --bars 30000
    （注意：截至当前基线，若传入 `P0` / `P1-hl-testnet` / `P0-acceptance-5m`，因
    `chong-derivation-input.json` 签 `l_start=L0 → op_ladder=2`，运行时会在加载数据前
    被 `UnnStream` 拒绝并退出 1，不会执行两臂比较。）
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "analysis"))

import time  # noqa: E402

import newchan_rust as nr  # noqa: E402

# #1601：期初资金/操作级别读 ADR 0040 签署记录的 profile；未设 ⟹ 运行时引擎报
# AwaitingPolicy{funding_record}，不回退任何默认资金，本脚本也不硬编码拒绝列表。
FUNDING_PROFILE = os.environ.get("NC_FUNDING_PROFILE")

from nautilus_trader.model.data import BarType  # noqa: E402

from nested_recursive_fugue_final_backtest import FLOOR  # noqa: E402
from organic_signals import StreamingSignalReader, push_signal  # noqa: E402

from trading_system.backtest_unn import load_bars  # noqa: E402
from trading_system.config.instruments import INSTRUMENTS, make_instrument  # noqa: E402

ROLE = "frozen_shadow_research_comparison"
ADMISSION_EFFECT = "none"
UNN_CORE_ID = "trading::unified_necessity::UnnStreamCore"
SPIRAL_CORE_ID = "spiral::engine::SpiralEngineCore"
SIGNAL_UPSTREAM_ID = "analysis.organic_signals.StreamingSignalReader"
LOADER_ID = "trading_system.backtest_unn.load_bars"
INPUT_ENCODING = "ohlc-f64be/1"
REQUIRE_SETTLED = True


def hash_ohlc_series(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> str:
    """计算两臂共享实际 OHLC 序列的 SHA-256（大端 binary64，每根 32 字节）。"""
    n = len(closes)
    if not (len(opens) == len(highs) == len(lows) == n):
        raise ValueError(
            f"OHLC 序列长度不一致: opens={len(opens)}, highs={len(highs)}, "
            f"lows={len(lows)}, closes={n}"
        )
    digest = hashlib.sha256()
    for o, h, low, c in zip(opens, highs, lows, closes):
        digest.update(struct.pack(">dddd", float(o), float(h), float(low), float(c)))
    return f"sha256:{digest.hexdigest()}"


def _resolve_input_source(sym: str) -> str:
    backtest_mod = sys.modules.get("trading_system.backtest_unn")
    if backtest_mod is not None and load_bars is not getattr(backtest_mod, "load_bars", None):
        return "<custom load_bars>"
    symbol_files = getattr(backtest_mod, "SYMBOL_FILES", None)
    if isinstance(symbol_files, dict) and sym in symbol_files:
        path = Path(symbol_files[sym])
        try:
            return str(path.resolve().relative_to(REPO_ROOT.resolve()))
        except ValueError:
            return str(path)
    return "<unmapped-by-SYMBOL_FILES>"


def _format_bt_max_bars() -> str:
    raw = os.environ.get("BT_MAX_BARS")
    if raw is None or raw == "":
        return "未设"
    try:
        val = int(raw)
    except ValueError:
        return raw
    return f"{val} (清洗前截断)" if val > 0 else f"{val} (未生效)"


def _print_arm_init_rejection(
    *,
    rejected_arm: str,
    core_id: str,
    ctor: str,
    sym: str,
    instrument_id: str,
    max_bars_label: str,
    run_id: str,
    funding_profile: str | None,
    exc: Exception,
) -> None:
    print("========== spiral × unn 构造未成（未作两臂比较） ==========", file=sys.stderr)
    print(f"run_id          : {run_id}", file=sys.stderr)
    print(
        f"role            : {ROLE} (admission_effect={ADMISSION_EFFECT}；ADR 0039 §四·4 / ADR 0048 一·C)",
        file=sys.stderr,
    )
    print(
        "status          : arm_init_rejected（构造未成，未加载 OHLC，未作两臂比较；"
        "CLI 退出 1，区别于已完成比较的分歧 exit 2 与已完成但零交易的 exit 0）",
        file=sys.stderr,
    )
    print(f"rejected_arm    : {rejected_arm} ({core_id} via {ctor})", file=sys.stderr)
    print(
        "两臂 funding 契约: arm_unn 读 ADR 0040 funding-record + chong-derivation-input(l_start→op_ladder)；"
        "arm_spiral 仅读 funding-record（PENDING_LO=3）",
        file=sys.stderr,
    )
    print(
        f"所选条件        : symbol={sym}({instrument_id}), max_bars={max_bars_label}, "
        f"bt_max_bars={_format_bt_max_bars()}, floor_ladder={FLOOR}, "
        f"require_settled={REQUIRE_SETTLED}, funding_profile={funding_profile}",
        file=sys.stderr,
    )
    print(f"原异常原因      : {type(exc).__name__}: {exc}", file=sys.stderr)
    print(
        "说明            : 实际可否构造由运行时引擎与生效 ADR 0040 签署记录决定"
        "（本入口不硬编码拒绝、不设默认资金、不抬升级别，也不构成模型分歧判决）。",
        file=sys.stderr,
    )


def compare(sym: str, max_bars: int | None, *, run_id: str | None = None) -> int:
    spec = INSTRUMENTS[sym]
    instrument = make_instrument(spec)
    bar_type = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")
    actual_run_id = run_id or str(uuid4())
    funding_profile = FUNDING_PROFILE
    max_bars_label = "全量" if max_bars is None else str(max_bars)

    # 两臂在加载数据前交由运行时 Rust 引擎校验 ADR 0040 签署记录（不硬编码拒绝、无默认资金、不抬升级别）。
    try:
        unn = nr.UnnStream(floor_ladder=FLOOR, funding_profile=funding_profile)
    except Exception as exc:
        _print_arm_init_rejection(
            rejected_arm="arm_unn",
            core_id=UNN_CORE_ID,
            ctor="newchan_rust.UnnStream",
            sym=sym,
            instrument_id=str(instrument.id),
            max_bars_label=max_bars_label,
            run_id=actual_run_id,
            funding_profile=funding_profile,
            exc=exc,
        )
        raise

    try:
        spiral = nr.SpiralStream(floor_ladder=FLOOR, funding_profile=funding_profile)
    except Exception as exc:
        _print_arm_init_rejection(
            rejected_arm="arm_spiral",
            core_id=SPIRAL_CORE_ID,
            ctor="newchan_rust.SpiralStream",
            sym=sym,
            instrument_id=str(instrument.id),
            max_bars_label=max_bars_label,
            run_id=actual_run_id,
            funding_profile=funding_profile,
            exc=exc,
        )
        raise

    print(f"加载 {sym}（max_bars={max_bars_label}）...")
    t0 = time.time()
    _bars, opens, highs, lows, closes = load_bars(
        sym, bar_type, spec.price_precision, max_bars, instrument.size_precision)
    input_hash = hash_ohlc_series(opens, highs, lows, closes)
    input_source = _resolve_input_source(sym)
    n = len(closes)
    print(f"  {n:,} bar  {time.time() - t0:.1f}s")

    dir_flips: list = []
    reader = StreamingSignalReader(dir_flips=dir_flips, require_settled=REQUIRE_SETTLED)

    first_div = None       # 第一处逐 bar 吐单分歧 (bar, unn_trades, spiral_trades)
    n_bar_div = 0          # 逐 bar 吐单分歧次数
    n_unn_pushed = 0
    n_spiral_pushed = 0

    if n:
        print("逐 bar 流式对账（同一 sig → UnnStream + SpiralStream）...")
    t0 = time.time()
    for i in range(n):
        n_before = len(dir_flips)
        sig = reader.process_bar(
            i, float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i]))
        flip_rows = [(lad, d) for (_b, lad, d) in dir_flips[n_before:]]
        tu = push_signal(unn, sig, flip_rows)
        ts = push_signal(spiral, sig, flip_rows)
        n_unn_pushed += len(tu)
        n_spiral_pushed += len(ts)
        if tu != ts:
            n_bar_div += 1
            if first_div is None:
                first_div = (i, tu, ts)
    if n:
        print(f"  逐 bar 完成 {time.time() - t0:.1f}s")

    ru = unn.finish()
    rs = spiral.finish()
    tu_all = ru["trades"]
    ts_all = rs["trades"]

    # ── 三项 bit-exact 核对：逐 bar 吐单、finish trade 表、final_nav ──
    bar_match = n_bar_div == 0
    trade_match = tu_all == ts_all
    n_first_trade_div = None
    if not trade_match:
        m = min(len(tu_all), len(ts_all))
        for j in range(m):
            if tu_all[j] != ts_all[j]:
                n_first_trade_div = j
                break
        if n_first_trade_div is None:
            n_first_trade_div = m  # 一方更长

    nav_u = ru["final_nav"]
    nav_s = rs["final_nav"]
    nav_match = nav_u == nav_s
    verdict = bar_match and trade_match and nav_match

    failed_axes: list[str] = []
    if not bar_match:
        failed_axes.append("逐 bar 吐单")
    if not trade_match:
        failed_axes.append("finish trade 表")
    if not nav_match:
        failed_axes.append("final_nav")

    first_divergence_summary: str | None = None
    if first_div is not None:
        first_divergence_summary = f"逐 bar 吐单 @ bar {first_div[0]}"
    elif n_first_trade_div is not None:
        first_divergence_summary = f"finish trade 表 @ index {n_first_trade_div}"
    elif not nav_match:
        first_divergence_summary = (
            f"final_nav (unn={nav_u!r}, spiral={nav_s!r}, Δ={nav_s - nav_u:.17g})"
        )

    zero_trade_sample = (
        len(tu_all) == 0
        and len(ts_all) == 0
        and n_unn_pushed == 0
        and n_spiral_pushed == 0
    )

    unn_records = ru.get("records", "<未返回>")
    spiral_funding_record = rs.get("funding_record", "<未返回>")
    unn_q_total = ru.get("q_total", "<未返回>")
    spiral_q_total = rs.get("q_total", "<未返回>")

    print("\n========== spiral × unn bit-exact 对账 ==========")
    print(f"run_id          : {actual_run_id}")
    print(f"role            : {ROLE} (admission_effect={ADMISSION_EFFECT}；ADR 0039 §四·4 / ADR 0048 一·C)")
    print(f"arm_unn core_id : {UNN_CORE_ID} (via newchan_rust.UnnStream)")
    print(f"arm_spiral core_id: {SPIRAL_CORE_ID} (via newchan_rust.SpiralStream)")
    print(f"shared_signal   : {SIGNAL_UPSTREAM_ID} (require_settled={REQUIRE_SETTLED})")
    print(f"input_source    : {input_source} (loader={LOADER_ID}, bar_type={bar_type})")
    print(f"input_hash      : {input_hash} (encoding={INPUT_ENCODING}, bars={n})")
    print(
        f"所选条件        : symbol={sym}({instrument.id}), max_bars={max_bars_label}, "
        f"bt_max_bars={_format_bt_max_bars()}, floor_ladder={FLOOR}, "
        f"require_settled={REQUIRE_SETTLED}, funding_profile={funding_profile}"
    )
    print(
        f"资金记录        : unn=({unn_records}, q_total={unn_q_total}) | "
        f"spiral=({spiral_funding_record}, q_total={spiral_q_total})"
    )
    print(f"标的            : {sym}（{instrument.id}）")
    print(f"bars            : {n:,}")
    print(f"unn   trades    : {len(tu_all)}  (逐 bar 吐 {n_unn_pushed})")
    print(f"spiral trades   : {len(ts_all)}  (逐 bar 吐 {n_spiral_pushed})")
    if n:
        print(f"逐 bar 吐单分歧 : {n_bar_div} bar  {'✅ PASS' if bar_match else '❌ MISMATCH'}")
    else:
        print("逐 bar 吐单分歧 : 不适用（零根行情，两臂均未步进）；只比较 finish trade 表与 final_nav")
    print(f"trade 表 bit-exact : {'✅ PASS' if trade_match else '❌ MISMATCH'}")
    print(
        f"final_nav       : unn={nav_u:.6f}  spiral={nav_s:.6f}  "
        f"{'✅ PASS' if nav_match else '❌ MISMATCH (Δ=%.6f)' % (nav_s - nav_u)}"
    )

    if first_divergence_summary is not None:
        print(f"分歧项          : {', '.join(failed_axes)}")
        print(f"第一处分歧      : {first_divergence_summary}")
    if first_div is not None:
        bar, tud, tsd = first_div
        print(f"\n第一处逐 bar 分歧 @ bar {bar}:")
        print(f"  unn    吐: {tud}")
        print(f"  spiral 吐: {tsd}")
    if n_first_trade_div is not None:
        print(f"\n第一处 trade 表分歧 @ index {n_first_trade_div}:")
        if n_first_trade_div < len(tu_all):
            print(f"  unn   : {tu_all[n_first_trade_div]}")
        else:
            print(f"  unn   : <缺失 (len={len(tu_all)})>")
        if n_first_trade_div < len(ts_all):
            print(f"  spiral: {ts_all[n_first_trade_div]}")
        else:
            print(f"  spiral: <缺失 (len={len(ts_all)})>")
    if not nav_match:
        print("\nfinal_nav 分歧:")
        print(f"  unn   : {nav_u!r}")
        print(f"  spiral: {nav_s!r}")
        print(f"  delta : {nav_s - nav_u:.17g}")

    if verdict and n == 0:
        print("\n判决: 收尾值相等（零根行情，逐 bar 无样本；仅研究读数，不构成生产准入）")
    elif verdict and zero_trade_sample:
        print(
            "观测等价范围    : 空交易样本（两臂均为 0 笔交易、逐 bar 吐单均为 0）；"
            "仅观测到无交易路径上的三项等价，未覆盖交易操作，不得据此宣称验证全部操作"
        )
        print(
            "\n判决: ✅ BIT-EXACT（空交易样本）—— 仅观测到无交易路径三项等价，"
            "未验证交易操作（仅研究读数，不构成生产准入）"
        )
    elif verdict:
        print(
            f"观测等价范围    : 已观测 {len(tu_all)} 笔完成交易（逐 bar 吐 {n_unn_pushed}），"
            "逐 bar 吐单 / finish trade 表 / final_nav 三项全等（仅研究对账，不构成生产准入）"
        )
        print(
            "\n判决: ✅ BIT-EXACT —— 三项（逐 bar / trade 表 / final_nav）全通过"
            "（操作=群作用 L2 对账，除 A 强平非群 gap G2；仅研究读数，不构成生产准入）"
        )
    else:
        print(
            f"\n判决: ❌ MISMATCH —— 分歧项: {', '.join(failed_axes)}；"
            "须逐处归因（群作用层=否证 / 已知 gap=标注；仅研究读数，不构成生产准入）"
        )
    return 0 if verdict else 2


CLI_HELP_EPILOG = """\
两臂 funding / domain 契约（运行时校验，不硬编码拒绝、无默认资金、不抬升级别）：
  - arm_unn（trading::unified_necessity::UnnStreamCore / newchan_rust.UnnStream）：
    读取 ADR 0040 funding-record.json（Q_total）与 chong-derivation-input.json（l_start → op_ladder = 2 + ℓ），
    且引擎约束 op_ladder ∈ [3, 11)（segment 非势源）。
  - arm_spiral（spiral::engine::SpiralEngineCore / newchan_rust.SpiralStream）：
    仅读取 ADR 0040 funding-record.json（Q_total），不消费 chong-derivation-input.json（PENDING_LO = 3）。
  - 须经环境变量 NC_FUNDING_PROFILE=<profile> 指定签署记录；实际可否构造由运行时引擎与生效签署记录决定。

当前仓库基线实测现状（非永久版本表）：
  截至当前基线，库内现行三份 ADR 0040 签署记录（P0 / P1-hl-testnet / P0-acceptance-5m）在
  chong-derivation-input.json 中均签署 l_start=L0（op_ladder=2），在加载 OHLC 数据前会被
  UnnStream 构造器拒绝（仅 SpiralStream 可完成单臂构造）。因此当前直接以这三者调用会构造未成并退出 1，
  不会执行两臂比较；本入口不把现状固化为版本表，后续若生效签署记录更新则按运行时实际结果执行。

退出码与观测范围：
  exit 1  构造未成 / 未作两臂比较（标的未注册、未设 NC_FUNDING_PROFILE、或任一臂被底层引擎拒绝；无对账判决）
  exit 2  已完成两臂比较，但三项（逐 bar 吐单 / finish trade 表 / final_nav）至少一项分歧（❌ MISMATCH）
  exit 0  零根行情：逐 bar 无样本，只比较 finish trade 表与 final_nav；任一不等仍返回 2
  exit 0  有行情且三项全等，两臂均 0 笔交易：仅声明无交易路径等价，未覆盖交易操作
  exit 0  已完成两臂比较且三项全等，有完成交易：仅研究对账读数（admission_effect=none，不构成生产准入）

调用格式：
  NC_FUNDING_PROFILE=<profile> PYTHONPATH=src .venv/bin/python trading_system/compare_spiral_unn.py --symbol OKLO --bars 30000
"""


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "spiral × unn 逐 bar bit-exact 研究对账"
            "（ADR 0039 §四·4 / ADR 0048 一·C；仅研究读数，不构成生产准入）"
        ),
        epilog=CLI_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--symbol", default="OKLO", help="已注册标的代码（默认: OKLO）")
    p.add_argument("--bars", type=int, default=30000, help="最大 bar 数（0=全量，默认: 30000）")
    args = p.parse_args(argv)
    if args.symbol not in INSTRUMENTS:
        print(
            f"标的 {args.symbol} 未注册（可用: {list(INSTRUMENTS)}）；"
            "构造未成，未作两臂比较（退出 1，区别于已完成比较的分歧 exit 2 与零交易等价 exit 0）",
            file=sys.stderr,
        )
        return 1
    return compare(args.symbol, args.bars or None)


if __name__ == "__main__":
    raise SystemExit(main())
