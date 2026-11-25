#!/usr/bin/env python3
"""FM-60a 甲批：从仓外原始数据切出每条判例的窗口，写 windows/*.csv、compare/*、cases-digitized.jsonl。

用法：  python3 build.py --raw-dir /path/to/raw
只用标准库。先跑 fetch.py 得到原始数据与 raw-manifest.json。
本脚本只做：聚合周、月线；切窗口；附收盘 5、10 均线数值；对原文字面给出的日期与价位逐项对照。
不做分型、笔、线段、中枢、背驰、买卖点等结构判定，也不评价原文断言。
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check as ck  # noqa: E402  复用同一套字面核对实现

THR = 0.011  # 两来源同一字段差超过此值才算「不一致」（BaoStock 4 位、新浪 3 位或 2 位、yfinance float32：小于此值属小数位级差）
TZ = "Asia/Shanghai"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ---------------- 载入原始数据 ----------------
class Raw:
    def __init__(self, raw_dir, manifest):
        self.dir = raw_dir
        self.entries = {e["file"]: e for e in manifest["files"]}

    def rows(self, rel):
        e = self.entries[rel]
        path = os.path.join(self.dir, rel)
        real = sha256_file(path)
        if real != e["sha256"]:
            sys.exit(f"原始文件 {rel} 的 sha256 与清单不符：现算 {real}，清单 {e['sha256']}。先重跑 fetch.py。")
        with open(path, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))


def bars_from_baostock(rows):
    out = []
    for r in rows:
        out.append({"t": r["date"], "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]),
                    "c": float(r["close"]), "v": float(r["volume"]),
                    "susp": r.get("tradestatus", "1") == "0"})
    return out


def aggregate(bars, unit):
    """日线 → 周（ISO 周）/月线。停牌行不参与；时间标记 = 区间内最后一个交易日，起始日 = 第一个。"""
    groups = defaultdict(list)
    for b in bars:
        if b["susp"]:
            continue
        d = dt.date.fromisoformat(b["t"])
        key = d.isocalendar()[:2] if unit == "w" else (d.year, d.month)
        groups[key].append(b)
    out = []
    for key in sorted(groups, key=lambda k: groups[k][0]["t"]):
        g = groups[key]
        out.append({"t": g[-1]["t"], "start": g[0]["t"], "o": g[0]["o"], "h": max(x["h"] for x in g),
                    "l": min(x["l"] for x in g), "c": g[-1]["c"], "v": sum(x["v"] for x in g), "susp": False})
    return out


def with_ma(bars):
    """对非停牌 bar 的收盘价算 5、10 期简单均线（用整段序列算，不因窗口截断而缺值）。"""
    closes = []
    for b in bars:
        if b["susp"]:
            b["ma5"] = b["ma10"] = None
            continue
        closes.append(b["c"])
        b["ma5"] = sum(closes[-5:]) / 5 if len(closes) >= 5 else None
        b["ma10"] = sum(closes[-10:]) / 10 if len(closes) >= 10 else None
    return bars


def f4(x):
    return "" if x is None else f"{x:.4f}"


def write_window(rel, bars, tf, stock):
    path = os.path.join(HERE, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if tf == "d":
        head = [f"时间[{TZ}|日线:该交易日]", "开", "高", "低", "收", "量(BaoStock原值)"]
    else:
        head = [f"时间[{TZ}|标记=结束:区间末个交易日]", "起始日[区间首个交易日]", "开", "高", "低", "收", "量(BaoStock原值,区间合计)"]
    if stock:
        head += ["状态", "MA5(收盘)", "MA10(收盘)"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(head)
        for b in bars:
            row = [b["t"]] + ([b["start"]] if tf != "d" else []) + [f4(b["o"]), f4(b["h"]), f4(b["l"]), f4(b["c"]), f"{b['v']:.0f}"]
            if stock:
                row += ["停牌" if b["susp"] else "正常", f4(b.get("ma5")), f4(b.get("ma10"))]
            w.writerow(row)
    return path


def cut(bars, frm, to):
    return [b for b in bars if frm <= b["t"] <= to]


# ---------------- 两来源比对 ----------------
def load_simple(rows):
    return {r["date"]: r for r in rows}


def diff_pair(a, b, fields=("open", "high", "low", "close"), lo=None, hi=None):
    """返回 (仅在a的日期, 仅在b的日期, 不一致项列表[(date,field,a,b,diff)], 小数位级差项数, 共有日期数)。"""
    ds = [d for d in set(a) | set(b) if (lo is None or d >= lo) and (hi is None or d <= hi)]
    only_a = sorted(d for d in ds if d in a and d not in b)
    only_b = sorted(d for d in ds if d in b and d not in a)
    diffs, small, n = [], 0, 0
    for d in sorted(ds):
        if d in a and d in b:
            n += 1
            for f in fields:
                x, y = float(a[d][f]), float(b[d][f])
                dd = x - y
                if abs(dd) > THR:
                    diffs.append((d, f, x, y, round(dd, 4)))
                elif abs(dd) > 0.0011:
                    small += 1
    return only_a, only_b, diffs, small, n


def summarize(only_a, only_b, diffs, small, n, name_a, name_b):
    return {
        "比对": f"{name_a} vs {name_b}", "共有日期数": n,
        f"仅在{name_a}": only_a[:30], f"仅在{name_b}": only_b[:30],
        f"仅在{name_a}_条数": len(only_a), f"仅在{name_b}_条数": len(only_b),
        "字段差大于0.011的项数": len(diffs),
        "最大绝对差": max((abs(x[4]) for x in diffs), default=0),
        "不一致日期": sorted({x[0] for x in diffs})[:30],
        "不一致日期_条数": len({x[0] for x in diffs}),
        "小数位级差项数(0.0011至0.011)": small,
    }


# ---------------- 判例定义 ----------------
def S(kind, literal, cite, window="primary", note=None, **params):
    return {"kind": kind, "literal": literal, "cite": cite, "window": window, "params": params, "note": note}


def date_s(literal, cite, date, note=None, window="primary"):
    return S("date", literal, cite, window, note, date=date)


NB = "\xa0"
YR_INF = "原文只写月日；年份 2004 由 014:36「2004年6月4日那周…6月18日创下低点后」推断（推断，非字面）"

CASES = [
    dict(id=1, kind="stock", sym="600519", tf="w", frm="2002-04-01", to="2003-12-31",
         specs=[date_s("2003年6月27日", 0, "2003-06-27")]),
    dict(id=2, kind="stock", sym="600519", tf="w", frm="2002-04-01", to="2003-12-31",
         specs=[date_s("2003年9月26日", 0, "2003-09-26")]),
    dict(id=3, kind="stock", sym="600519", tf="d", frm="2004-04-01", to="2006-12-31",
         specs=[date_s("6月18日", 0, "2004-06-18", YR_INF), date_s("10月27日", 0, "2004-10-27", YR_INF),
                date_s("12月22日", 0, "2004-12-22", YR_INF), date_s("2005年4月26日", 0, "2005-04-26"),
                date_s("2005年12月13日", 0, "2005-12-13"), date_s("6月18日", 1, "2004-06-18", YR_INF)]),
    dict(id=4, kind="stock", sym="600497", tf="d", frm="2004-04-20", to="2006-01-31",
         specs=[date_s("2004年6月2日", 0, "2004-06-02"), date_s("2005年7月27日", 0, "2005-07-27"),
                date_s("2005年3月14日", 0, "2005-03-14"),
                date_s("2004年6月2日", 1, "2004-06-02"), date_s("2004年9月10日", 1, "2004-09-10"),
                date_s("2004年9月10日", 2, "2004-09-10"), date_s("2005年3月14日", 2, "2005-03-14"),
                date_s("2005年3月14日", 3, "2005-03-14"), date_s("2005年7月27日", 3, "2005-07-27")]),
    dict(id=5, kind="stock", sym="600497", tf="d", frm="2004-09-01", to="2006-01-31",
         specs=[date_s("2004年9月10日", 0, "2004-09-10"), date_s("2005年3月14日", 0, "2005-03-14"),
                date_s("2005年12月8日", 0, "2005-12-08")]),
    dict(id=6, kind="stock", sym="600497", tf="d", frm="2004-04-20", to="2005-08-31",
         specs=[date_s("05年3月14日", 1, "2005-03-14", "引文为网友（非作者）；「05年」按字面取 2005"),
                date_s("05年7月27日", 1, "2005-07-27", "引文为网友（非作者）；「05年」按字面取 2005"),
                date_s("2004年6月2日", 2, "2004-06-02"), date_s("2005年7月27日", 2, "2005-07-27")]),
    dict(id=9, kind="stock", sym="601628", tf="d", frm="2007-01-05", to="2007-01-19",
         aux_daily_only=True,
         specs=[date_s("11日", 0, "2007-01-11", "原文只写日；月、年由 024:8 署时间 2007-01-18 推断为 2007-01（推断，非字面）"),
                date_s(f"15{NB}日", 0, "2007-01-15", "同上，月年为推断"),
                date_s("16日", 0, "2007-01-16", "同上，月年为推断"),
                date_s(f"16{NB}日", 1, "2007-01-16", "同上，月年为推断"),
                date_s(f"17{NB}日", 1, "2007-01-17", "同上，月年为推断"),
                S("unavailable", f"11{NB}点30{NB}分", 0, reason="需要 5 分钟线；BaoStock 的 601628 五分钟线自 2020-01-02 起，2007 年无数据"),
                S("unavailable", f"10{NB}点35{NB}分", 0, reason="同上"),
                S("unavailable", f"10{NB}点25{NB}分", 0, reason="同上"),
                S("unavailable", f"10{NB}点10{NB}分", 1, reason="同上")]),
    dict(id=10, kind="stock", sym="601628", tf="d", frm=None, to=None, specs=[], no_window=True),
    dict(id=29, kind="index", tf="m", frm="1990-12-01", to="2008-12-31",
         specs=[S("extreme", "2245", 0, None, "取月线最高价的最大值；区间取 1990-12 至 2005-12（2006 年起指数已超过 2245，故截到 998 点低点之后）",
                  field="高", **{"from": "1990-12-01", "to": "2005-12-31"}, value=2245),
                S("extreme", "998点", 0, None, "取 2245 所在月（2001-06）之后至 2007-08 的月线最低价的最小值",
                  field="低", **{"from": "2001-06-01", "to": "2007-08-31"}, value=998)]),
    dict(id=38, kind="index", tf="d", frm="2005-01-01", to="2008-02-29",
         specs=[S("touched", "4335点", 0, None, "起点 2007-10-16 取自 period_basis「自 6124 点下来」，不在引文内；终点为帖日 2008-01-31",
                  **{"from": "2007-10-16", "to": "2008-01-31"}, value=4335),
                S("extreme", "1000点", 0, None, "「从1000点上来」：取 2005 年以来日线最低价的最小值",
                  field="低", **{"from": "2005-01-01", "to": "2008-02-29"}, value=1000),
                S("extreme", "6124点(不在本条引文，取自清点表 period_basis)", None, None, "仅作背景：2007-10 至 2008-01 日线最高价的最大值",
                  field="高", **{"from": "2007-10-01", "to": "2008-01-31"}, value=6124)]),
    dict(id=49, kind="index", tf="w", frm="2008-01-01", to="2008-04-18",
         specs=[S("nearest_level", "3840点", 0, None, "取 2008-02-01 至 2008-04-18 各周K线最高、最低价中离 3840 最近的一个",
                  **{"from": "2008-02-01", "to": "2008-04-18"}, value=3840),
                S("price_in_bar", "3840点", 0, None, "帖日 2008-04-11 所在周", bar="2008-04-11", value=3840),
                S("price_in_bar", "3840点", 0, None, "帖日次周", bar="2008-04-18", value=3840)]),
    dict(id=55, kind="index", tf="m", frm="2008-06-01", to="2008-12-31", month_specs=True, specs=[]),
    dict(id=56, kind="index", tf="w", frm="2008-08-18", to="2008-09-19", extra_daily=True,
         specs=[S("price_in_bar", "2284", 0, None, "本周（含 2008-08-29 的一周）", bar="2008-08-29", value=2284),
                S("price_in_bar", "2601", 0, None, "本周", bar="2008-08-29", value=2601),
                S("price_in_bar", "2284", 0, None, "上周", bar="2008-08-22", value=2284),
                S("price_in_bar", "2601", 0, None, "上周", bar="2008-08-22", value=2601),
                S("price_in_bar", "2523点", 0, "daily", "「今天，本周最后一天」按帖日取 2008-08-29 的日线", bar="2008-08-29", value=2523),
                S("date", "本周最后一天", 0, None, "日期 2008-08-29 取自 period_basis 的课文署时间，不在引文内", date="2008-08-29")]),
    dict(id=59, kind="index", tf="w", frm="2007-10-01", to="2008-09-26",
         specs=[S("extreme", "6124点", 0, None, "取 2007-10 至 2008-09 各周K线最高价的最大值",
                  field="高", **{"from": "2007-10-01", "to": "2008-09-26"}, value=6124)]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    a = ap.parse_args()
    man_path = os.path.join(HERE, "raw-manifest.json")
    with open(man_path, encoding="utf-8") as f:
        manifest = json.load(f)
    raw = Raw(a.raw_dir, manifest)
    inv = {}
    with open(os.path.join(HERE, "..", "fm60a-inventory", "cases.jsonl"), encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                d = json.loads(ln)
                inv[d["case_id"]] = d

    # 原始序列
    idx_bs = raw.rows("baostock/index_sh000001_d.csv")
    idx_sn = raw.rows("akshare/index_sh000001_sina_d.csv")
    idx_yf = raw.rows("yfinance/index_000001SS_d.csv")
    idx_bars = bars_from_baostock(idx_bs)
    series = {"index": {"d": idx_bars, "w": aggregate(idx_bars, "w"), "m": aggregate(idx_bars, "m")}}
    stock_raw = {}
    for sym in ("600519", "600497", "601628"):
        stock_raw[sym] = {}
        for tag in ("none", "qfq"):
            rows = raw.rows(f"baostock/stock_{sym}_d_{tag}.csv")
            sn = raw.rows(f"akshare/stock_{sym}_d_{tag}_sina.csv")
            d = with_ma(bars_from_baostock(rows))
            w = with_ma(aggregate(d, "w"))
            stock_raw[sym][tag] = {"d": d, "w": w, "bs_rows": rows, "sina_rows": sn}

    # ---- 全局比对文件 ----（先清掉旧产物，避免残留）
    for sub in ("compare", "windows"):
        d = os.path.join(HERE, sub)
        os.makedirs(d, exist_ok=True)
        for fn in os.listdir(d):
            os.remove(os.path.join(d, fn))
    gsum = {}
    bsd, snd, yfd = load_simple(idx_bs), load_simple(idx_sn), load_simple(idx_yf)
    oa, ob, df1, sm1, n1 = diff_pair(bsd, snd)
    gsum["index_daily_BaoStock_vs_新浪"] = summarize(oa, ob, df1, sm1, n1, "BaoStock", "新浪")
    oa2, ob2, df2, sm2, n2 = diff_pair(bsd, yfd, lo="1997-07-02")
    gsum["index_daily_BaoStock_vs_yfinance"] = summarize(oa2, ob2, df2, sm2, n2, "BaoStock", "yfinance")
    gsum["index_daily_BaoStock_vs_yfinance"]["说明"] = "yfinance 自 1997-07-02 起，只比对该日之后"
    oa3, ob3, df3, sm3, n3 = diff_pair(snd, yfd, lo="1997-07-02")
    gsum["index_daily_新浪_vs_yfinance"] = summarize(oa3, ob3, df3, sm3, n3, "新浪", "yfinance")
    with open(os.path.join(HERE, "compare", "index-daily-diffs.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["比对", "日期", "字段", "前者", "后者", "差(前-后)"])
        for tag, dl in (("BaoStock-新浪", df1), ("BaoStock-yfinance", df2), ("新浪-yfinance", df3)):
            for r in dl:
                w.writerow([tag, *r])
    with open(os.path.join(HERE, "compare", "index-daily-dateset-diffs.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["比对", "日期", "仅在"])
        for tag, (x, y, nx, ny) in (("BaoStock-新浪", (oa, ob, "BaoStock", "新浪")), ("BaoStock-yfinance", (oa2, ob2, "BaoStock", "yfinance")),
                                     ("新浪-yfinance", (oa3, ob3, "新浪", "yfinance"))):
            for d in x:
                w.writerow([tag, d, nx])
            for d in y:
                w.writerow([tag, d, ny])
    # 聚合 vs BaoStock 原生周、月
    agg_rows = []
    for unit in ("w", "m"):
        nat = bars_from_baostock(raw.rows(f"baostock/index_sh000001_{unit}.csv"))
        mine = {b["t"]: b for b in series["index"][unit]}
        natd = {b["t"]: b for b in nat}
        for t in sorted(set(mine) | set(natd)):
            if t not in mine:
                agg_rows.append([unit, t, "仅原生有", "", "", ""])
            elif t not in natd:
                agg_rows.append([unit, t, "仅聚合有", "", "", ""])
            else:
                for fld, nm in (("o", "开"), ("h", "高"), ("l", "低"), ("c", "收")):
                    dd = mine[t][fld] - natd[t][fld]
                    if abs(dd) > THR:
                        agg_rows.append([unit, t, nm, mine[t][fld], natd[t][fld], round(dd, 4)])
    with open(os.path.join(HERE, "compare", "agg-vs-native.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["周期", "标记日", "字段", "自己聚合", "BaoStock原生", "差"])
        w.writerows(agg_rows)
    gsum["index_agg_vs_baostock_native"] = {"不一致项数": len(agg_rows), "按周期": {u: sum(1 for r in agg_rows if r[0] == u) for u in ("w", "m")}}
    # 个股
    stock_cmp = {}
    srows = []
    for sym in stock_raw:
        for tag in ("none", "qfq"):
            a_, b_ = load_simple(stock_raw[sym][tag]["bs_rows"]), load_simple(stock_raw[sym][tag]["sina_rows"])
            # 比对只取 BaoStock 正常交易日（停牌日新浪本就没有）
            a_ok = {d: r for d, r in a_.items() if r["tradestatus"] == "1"}
            a_susp = sorted(d for d, r in a_.items() if r["tradestatus"] == "0")
            oa_, ob_, dd_, sm_, n_ = diff_pair(a_ok, b_)
            s = summarize(oa_, ob_, dd_, sm_, n_, "BaoStock正常日", "新浪")
            s["BaoStock停牌日数(tradestatus=0,新浪无此行)"] = len(a_susp)
            if dd_:
                rel = [abs(x[4]) / abs(x[3]) for x in dd_ if x[3]]
                s["最大相对差"] = round(max(rel), 4) if rel else None
            stock_cmp[f"{sym}_{tag}"] = s
            if tag == "none":
                for r in dd_:
                    srows.append([sym, tag, *r])
    gsum["stock_daily"] = stock_cmp
    with open(os.path.join(HERE, "compare", "stock-daily-diffs.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["代码", "复权", "日期", "字段", "BaoStock", "新浪", "差"])
        w.writerows(srows)  # 不复权：全部不一致项；前复权两家算法不同，差异太多，只在 summary 里给统计
    with open(os.path.join(HERE, "compare", "summary.json"), "w", encoding="utf-8") as f:
        json.dump(gsum, f, ensure_ascii=False, indent=1)
        f.write("\n")

    # ---- 窗口与判例记录 ----
    committed = {}
    out_recs = []
    for cs in CASES:
        cid = f"FM60A-{cs['id']:03d}"
        base = inv[cid]
        rec = {"case_id": cid}
        for k in ("cites", "assertion", "asserted_values", "base_and_pen"):
            rec[k] = base[k]
        stock = cs["kind"] == "stock"
        sym = cs.get("sym")
        wins = {}      # role -> (rel, tf, bars, meta)
        extra = []

        def mk(role, rel, tf, bars, adjust_label, src_desc, with_ma_cols):
            path = write_window(rel, bars, tf, with_ma_cols)
            sha = sha256_file(path)
            committed[rel] = sha
            meta = {"tf": tf, "时区": TZ, "adjust": adjust_label, "行数": len(bars),
                    "首个时间": bars[0]["t"] if bars else None, "末个时间": bars[-1]["t"] if bars else None,
                    "时间列含义": "日线：该交易日（日期，无时分）" if tf == "d" else "周/月线：区间内最后一个交易日，标记的是该根K线的结束；另列「起始日」为区间首个交易日",
                    "来源": src_desc, "含MA列": with_ma_cols}
            wins[role] = (rel, tf, bars, meta, sha)
            return meta, sha

        if cs.get("no_window"):
            rec.update({"window_file": None, "window_sha256": None, "window_meta": None, "extra_windows": []})
        else:
            if stock:
                bs_none_file = f"baostock/stock_{sym}_d_none.csv"
                bs_qfq_file = f"baostock/stock_{sym}_d_qfq.csv"
                bars_none = stock_raw[sym]["none"][cs["tf"]]
                bars_qfq = stock_raw[sym]["qfq"][cs["tf"]]
                desc = ("BaoStock query_history_k_data_plus 日线 adjustflag=3（不复权）" +
                        ("，周线由日线按 ISO 周聚合（停牌日不参与）" if cs["tf"] == "w" else ""))
                desc_q = desc.replace("adjustflag=3（不复权）", "adjustflag=2（前复权）")
                if cs.get("aux_daily_only"):
                    desc += "；本窗口是日线，仅用于核对日期是否为交易日，原文所需的 5 分钟线取不到"
                    desc_q += "；同上"
                mk("primary", f"windows/{cid}.csv", cs["tf"], cut(bars_none, cs["frm"], cs["to"]), "不复权", desc, True)
                mk("qfq", f"windows/{cid}.qfq.csv", cs["tf"], cut(bars_qfq, cs["frm"], cs["to"]), "前复权", desc_q, True)
            else:
                bars = series["index"][cs["tf"]]
                desc = "BaoStock query_history_k_data_plus sh.000001 日线 adjustflag=3" + (
                    "，周线由日线按 ISO 周聚合" if cs["tf"] == "w" else "，月线由日线按自然月聚合" if cs["tf"] == "m" else "")
                mk("primary", f"windows/{cid}.csv", cs["tf"], cut(bars, cs["frm"], cs["to"]), "指数无复权", desc, False)
                if cs.get("extra_daily"):
                    mk("daily", f"windows/{cid}.daily.csv", "d", cut(series["index"]["d"], cs["frm"], cs["to"]), "指数无复权",
                       "BaoStock query_history_k_data_plus sh.000001 日线 adjustflag=3", False)
            p = wins["primary"]
            rec.update({"window_file": p[0], "window_sha256": p[4], "window_meta": p[3],
                        "extra_windows": [{"role": r, "file": w[0], "sha256": w[4], "meta": w[3]} for r, w in wins.items() if r != "primary"]})

        # 月线判例 055：K 线标记取自数据
        specs = list(cs["specs"])
        if cs.get("month_specs"):
            mb = {b["t"][:7]: b["t"] for b in wins["primary"][2]}
            aug, sep = mb["2008-08"], mb["2008-09"]
            specs = [S("price_in_bar", "2284点", 0, None, f"2008 年 8 月月线（标记 {aug}）", bar=aug, value=2284),
                     S("price_in_bar", "2952", 0, None, f"2008 年 8 月月线（标记 {aug}）", bar=aug, value=2952),
                     S("price_in_bar", "2284点", 0, None, f"原文问「9月是否破 2284」：取 2008 年 9 月月线（标记 {sep}）", bar=sep, value=2284)]
        lcs = []
        wmap = {r: (w[1], ck.read_window(os.path.join(HERE, w[0]))) for r, w in wins.items()}  # 与 check.py 同一读法：从落盘的窗口文件读
        for n, sp in enumerate(specs, 1):
            item = {"id": f"{cid}-L{n:02d}", "kind": sp["kind"], "literal": sp["literal"], "cite": sp["cite"],
                    "window": sp["window"] or "primary", "params": sp["params"], "note": sp["note"]}
            item["result"] = ck.compute(item, wmap)
            lcs.append(item)
        rec["literal_checks"] = lcs

        # 来源与比对（窗口覆盖的日期范围内）
        if cs.get("no_window"):
            rec["source"] = {"说明": "无窗口：原文所需的 601628 五分钟线取不到（见 FM60A-009）", "原始文件": []}
            rec["cross_source"] = []
            rec["adjust"] = {"口径": "不适用（无窗口）"}
        else:
            lo = wins["primary"][2][0].get("start", wins["primary"][2][0]["t"])
            hi = wins["primary"][2][-1]["t"]
            if stock:
                fl = []
                cross = []
                for tag, rel in (("none", bs_none_file), ("qfq", bs_qfq_file)):
                    e = raw.entries[rel]
                    fl.append({"文件": rel, "sha256": e["sha256"], "接口": e["interface"], "参数": e["params"], "取数时刻UTC": e["fetched_at_utc"]})
                    sl = f"akshare/stock_{sym}_d_{tag}_sina.csv"
                    e2 = raw.entries[sl]
                    fl.append({"文件": sl, "sha256": e2["sha256"], "接口": e2["interface"], "参数": e2["params"], "取数时刻UTC": e2["fetched_at_utc"], "角色": "交叉核对，未进窗口"})
                    a_ = {d: r for d, r in load_simple(stock_raw[sym][tag]["bs_rows"]).items() if r["tradestatus"] == "1"}
                    b_ = load_simple(stock_raw[sym][tag]["sina_rows"])
                    cross.append({"复权": "不复权" if tag == "none" else "前复权",
                                  **summarize(*diff_pair(a_, b_, lo=lo, hi=hi), "BaoStock正常日", "新浪")})
                rec["source"] = {"主来源": "BaoStock", "原始文件": fl}
                rec["cross_source"] = cross
                rec["adjust"] = {
                    "原文给的价位": [],
                    "对得上的一份": None,
                    "结论": "本判例引文只有日期，没有价位，无从判定原文看的是不复权还是前复权；两份都留（windows/%s.csv 不复权，windows/%s.qfq.csv 前复权）。" % (cid, cid),
                    "附注": "前复权口径随取数时刻与供应商而变：BaoStock 用涨跌幅复权法，新浪的前复权数值与之不同（见 compare/summary.json 与 README）；前复权窗口只对「取数当日」有意义。",
                }
            else:
                fl = []
                for rel in ("baostock/index_sh000001_d.csv", "akshare/index_sh000001_sina_d.csv", "yfinance/index_000001SS_d.csv"):
                    e = raw.entries[rel]
                    fl.append({"文件": rel, "sha256": e["sha256"], "接口": e["interface"], "参数": e["params"], "取数时刻UTC": e["fetched_at_utc"],
                               "角色": "窗口来源" if rel.startswith("baostock") else "交叉核对，未进窗口"})
                cross = []
                for nm, other in (("新浪", snd), ("yfinance", yfd)):
                    lo_ = max(lo, "1997-07-02") if nm == "yfinance" else lo  # yfinance 自 1997-07-02 起
                    cross.append(summarize(*diff_pair(bsd, other, lo=lo_, hi=hi), "BaoStock", nm))
                if cs["tf"] in ("w", "m"):
                    nat = bars_from_baostock(raw.rows(f"baostock/index_sh000001_{cs['tf']}.csv"))
                    natw = {b["t"]: b for b in cut(nat, cs["frm"], cs["to"])}
                    mine = {b["t"]: b for b in wins["primary"][2]}
                    bad = [(t, f) for t in sorted(set(natw) & set(mine)) for f in ("o", "h", "l", "c") if abs(mine[t][f] - natw[t][f]) > THR]
                    cross.append({"比对": "自己聚合 vs BaoStock 原生" + ("周线" if cs["tf"] == "w" else "月线"),
                                  "共有K线数": len(set(natw) & set(mine)), "仅原生有": sorted(set(natw) - set(mine)), "仅聚合有": sorted(set(mine) - set(natw)),
                                  "字段差大于0.011的项数": len(bad), "不一致K线": sorted({t for t, _ in bad})})
                rec["source"] = {"主来源": "BaoStock", "原始文件": fl}
                rec["cross_source"] = cross
                rec["adjust"] = {"口径": "指数不涉及复权", "原文给的价位": [sp["literal"] for sp in specs if sp["kind"] != "date"]}

        # 状态
        if cid in ("FM60A-009", "FM60A-010"):
            rec["status"] = "需补数据"
            rec["status_reason"] = ("原文是 601628 的 5 分钟走势（含时分）；BaoStock 的 601628 五分钟线最早自 2020-01-02，2007 年没有数据，"
                                    "按约定不换来源硬凑。" + ("日线窗口只用来核对 11、15、16、17 日是否为交易日，时分无法核对。" if cid.endswith("009") else
                                                          "本条原文没有可字面核对的日期或价位，无窗口。"))
        else:
            rec["status"] = "已数字化"
            rec["status_reason"] = {"w": "周线窗口（BaoStock 日线聚合）已落盘，原文的日期与价位已字面核对；", "m": "月线窗口（BaoStock 日线聚合）已落盘，原文的价位已字面核对；",
                                    "d": "日线窗口（BaoStock）已落盘，原文的日期与价位已字面核对；"}[cs["tf"]] + "不含 MACD 与任何结构量，那些属于后续步骤。"
        out_recs.append(rec)

    # 写 jsonl 与 committed_files
    with open(os.path.join(HERE, "cases-digitized.jsonl"), "w", encoding="utf-8") as f:
        for r in out_recs:
            ordered = {k: r[k] for k in ck.CASE_KEYS}
            f.write(json.dumps(ordered, ensure_ascii=False) + "\n")
    for fn in sorted(os.listdir(os.path.join(HERE, "compare"))):
        committed[f"compare/{fn}"] = sha256_file(os.path.join(HERE, "compare", fn))
    manifest["committed_files"] = dict(sorted(committed.items()))
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"判例 {len(out_recs)} 条；窗口文件 {sum(1 for k in committed if k.startswith('windows/'))} 个；compare 文件 {sum(1 for k in committed if k.startswith('compare/'))} 个")


if __name__ == "__main__":
    main()
