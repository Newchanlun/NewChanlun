#!/usr/bin/env python3
"""FM-60a 甲批（#2324）取数脚本：只用不需注册、不需令牌的公开接口。

用法（需装 baostock、yfinance、akshare、pandas 的虚拟环境）：
    python fetch.py --raw-dir /path/to/raw [--manifest fm60a-batch-a/raw-manifest.json]

对外请求只带标的代码与日期范围。原始数据写到 --raw-dir（仓外），清单写到 --manifest（入库）。
每个文件记 sha256、来源接口、请求参数、取数时刻（UTC）。接口失败不静默：错误写进清单。
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import sys
import time

D_END = "2008-12-31"

# 指数全史（BaoStock 日线自 1990-12-19）
INDEX_START = "1990-12-01"
# 个股：只取判例所需的年段，另留余量
STOCKS = {
    "600519": {"name": "贵州茅台", "start": "2001-08-01", "end": "2007-12-31"},
    "600497": {"name": "驰宏锌锗", "start": "2004-04-01", "end": "2006-12-31"},
    "601628": {"name": "中国人寿", "start": "2007-01-01", "end": "2007-03-31"},
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def now_utc():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


class Recorder:
    def __init__(self, raw_dir):
        self.raw = raw_dir
        self.entries = []
        self.failures = []

    def add(self, rel, header, rows, source, interface, params, note=""):
        path = os.path.join(self.raw, rel)
        write_csv(path, header, rows)
        dates = [r[0] for r in rows]
        self.entries.append({
            "file": rel,
            "sha256": sha256(path),
            "bytes": os.path.getsize(path),
            "rows": len(rows),
            "first_date": min(dates) if dates else None,
            "last_date": max(dates) if dates else None,
            "source": source,
            "interface": interface,
            "params": params,
            "fetched_at_utc": now_utc(),
            "note": note,
        })
        print(f"ok  {rel}  rows={len(rows)}  {self.entries[-1]['first_date']}..{self.entries[-1]['last_date']}", flush=True)

    def fail(self, rel, source, interface, params, err):
        self.failures.append({"file": rel, "source": source, "interface": interface, "params": params,
                              "error": repr(err)[:400], "at_utc": now_utc()})
        print(f"ERR {rel}  {err!r}"[:300], flush=True)


# ---------------- BaoStock ----------------
def bs_query(bs, code, fields, start, end, freq, adjust):
    rs = bs.query_history_k_data_plus(code, fields, start_date=start, end_date=end,
                                      frequency=freq, adjustflag=adjust)
    if rs.error_code != "0":
        raise RuntimeError(f"baostock {rs.error_code} {rs.error_msg}")
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    return rs.fields, rows


def fetch_baostock(rec):
    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        rec.fail("baostock/*", "BaoStock", "login", {}, lg.error_msg)
        return
    try:
        dfields = "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg"
        wfields = "date,code,open,high,low,close,volume,amount,adjustflag,turn,pctChg"
        # 指数日、周、月（指数不复权；周、月是接口原生，用来交叉核对自己的聚合）
        for freq, fields in (("d", dfields), ("w", wfields), ("m", wfields)):
            p = {"code": "sh.000001", "start_date": INDEX_START, "end_date": D_END, "frequency": freq, "adjustflag": "3"}
            rel = f"baostock/index_sh000001_{freq}.csv"
            try:
                h, rows = bs_query(bs, "sh.000001", fields, INDEX_START, D_END, freq, "3")
                rec.add(rel, h, rows, "BaoStock", "query_history_k_data_plus", p)
            except Exception as e:
                rec.fail(rel, "BaoStock", "query_history_k_data_plus", p, e)
        # 个股日线：不复权(3)与前复权(2)
        for sym, meta in STOCKS.items():
            for adj, tag in (("3", "none"), ("2", "qfq")):
                p = {"code": "sh." + sym, "start_date": meta["start"], "end_date": meta["end"], "frequency": "d", "adjustflag": adj}
                rel = f"baostock/stock_{sym}_d_{tag}.csv"
                try:
                    h, rows = bs_query(bs, "sh." + sym, dfields, meta["start"], meta["end"], "d", adj)
                    rec.add(rel, h, rows, "BaoStock", "query_history_k_data_plus", p,
                            note="adjustflag 3=不复权，2=前复权（涨跌幅复权法）")
                except Exception as e:
                    rec.fail(rel, "BaoStock", "query_history_k_data_plus", p, e)
        # 601628 五分钟线：先验证 2007-01 有没有；再按年探查最早起点
        probes = []
        for (s, e) in (("2007-01-09", "2007-01-19"), ("2007-01-01", "2007-12-31"), ("2008-01-01", "2008-12-31")):
            p = {"code": "sh.601628", "start_date": s, "end_date": e, "frequency": "5", "adjustflag": "3"}
            try:
                h, rows = bs_query(bs, "sh.601628", "date,time,open,high,low,close,volume,amount", s, e, "5", "3")
                probes.append({"params": p, "rows": len(rows), "first": rows[0] if rows else None, "last": rows[-1] if rows else None})
            except Exception as ex:
                probes.append({"params": p, "error": repr(ex)[:300]})
        for y in range(2009, 2022):
            p = {"code": "sh.601628", "start_date": f"{y}-01-01", "end_date": f"{y}-12-31", "frequency": "5", "adjustflag": "3"}
            try:
                h, rows = bs_query(bs, "sh.601628", "date,time", p["start_date"], p["end_date"], "5", "3")
                probes.append({"params": p, "rows": len(rows), "first": rows[0] if rows else None})
                if rows:
                    break  # 找到最早有数据的年份即止
            except Exception as ex:
                probes.append({"params": p, "error": repr(ex)[:300]})
        rec.probes = {"baostock_601628_5min": probes, "at_utc": now_utc()}
    finally:
        bs.logout()


# ---------------- yfinance ----------------
def fetch_yfinance(rec):
    import yfinance as yf
    p = {"ticker": "000001.SS", "start": "1990-12-01", "end": "2009-01-01(exclusive)", "interval": "1d", "auto_adjust": False}
    rel = "yfinance/index_000001SS_d.csv"
    try:
        df = yf.Ticker("000001.SS").history(start="1990-12-01", end="2009-01-01", interval="1d", auto_adjust=False)
        rows = [[ix.strftime("%Y-%m-%d"), r["Open"], r["High"], r["Low"], r["Close"], r["Volume"]] for ix, r in df.iterrows()]
        rec.add(rel, ["date", "open", "high", "low", "close", "volume"], rows, "yfinance", "Ticker.history", p,
                note="Open 等为 float32 量级的小数，原样记录；日期为 Asia/Shanghai 本地日")
    except Exception as e:
        rec.fail(rel, "yfinance", "Ticker.history", p, e)


# ---------------- AKShare ----------------
def retry(fn, tries=3, wait=5):
    """网络超时重试（仅对超时、连接类瞬时错误；不用于被限流的接口）。"""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == tries - 1 or "Timeout" not in repr(e) and "Connection" not in repr(e):
                raise
            time.sleep(wait)



def fetch_akshare(rec, with_em=False):
    import akshare as ak
    p = {"symbol": "sh000001"}
    rel = "akshare/index_sh000001_sina_d.csv"
    try:
        df = retry(lambda: ak.index_zh_daily_sina(symbol="sh000001"))
        rows = [[str(r["date"]), r["open"], r["high"], r["low"], r["close"], r["volume"]] for _, r in df.iterrows()
                if str(r["date"]) <= D_END]
        rec.add(rel, ["date", "open", "high", "low", "close", "volume"], rows, "AKShare(新浪)", "index_zh_daily_sina", p,
                note="接口返回全史，仅截取至 2008-12-31 后落盘")
    except Exception as e:
        rec.fail(rel, "AKShare(新浪)", "index_zh_daily_sina", p, e)
    for sym, meta in STOCKS.items():
        s, e_ = meta["start"].replace("-", ""), meta["end"].replace("-", "")
        mk = ("sh" + sym)
        for adj, tag in (("", "none"), ("qfq", "qfq")):
            # 东方财富（默认关闭：首次取数即被 push2 限流，不绕过、不重试，见 README）
            p = {"symbol": sym, "period": "daily", "start_date": s, "end_date": e_, "adjust": adj}
            rel = f"akshare/stock_{sym}_d_{tag}_em.csv"
            if not with_em:
                continue_em = True
            else:
                continue_em = False
            try:
                if continue_em:
                    raise StopIteration

                df = ak.stock_zh_a_hist_em(symbol=sym, period="daily", start_date=s, end_date=e_, adjust=adj)
                rows = [[str(r["日期"]), r["开盘"], r["最高"], r["最低"], r["收盘"], r["成交量"]] for _, r in df.iterrows()]
                rec.add(rel, ["date", "open", "high", "low", "close", "volume_lots"], rows, "AKShare(东方财富)",
                        "stock_zh_a_hist_em", p, note="成交量单位为手")
            except StopIteration:
                pass
            except Exception as ex:
                rec.fail(rel, "AKShare(东方财富)", "stock_zh_a_hist_em", p, ex)
            if with_em:
                time.sleep(1)
            # 新浪
            p = {"symbol": mk, "start_date": s, "end_date": e_, "adjust": adj}
            rel = f"akshare/stock_{sym}_d_{tag}_sina.csv"
            try:
                df = retry(lambda: ak.stock_zh_a_hist_sina(symbol=mk, start_date=s, end_date=e_, adjust=adj))
                rows = [[str(r["date"]), r["open"], r["high"], r["low"], r["close"], r["volume"]] for _, r in df.iterrows()]
                rec.add(rel, ["date", "open", "high", "low", "close", "volume"], rows, "AKShare(新浪)",
                        "stock_zh_a_hist_sina", p)
            except Exception as ex:
                rec.fail(rel, "AKShare(新浪)", "stock_zh_a_hist_sina", p, ex)
            time.sleep(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--with-em", action="store_true", help="同时取东方财富个股日线（易被限流，默认不取）")
    ap.add_argument("--manifest", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw-manifest.json"))
    a = ap.parse_args()
    rec = Recorder(a.raw_dir)
    rec.probes = {}
    fetch_baostock(rec)
    fetch_yfinance(rec)
    fetch_akshare(rec, a.with_em)
    import importlib.metadata as md
    out = {
        "note": "原始数据在仓外；本清单入库。sha256 为仓外原始文件的哈希，仓内不含原始文件。",
        "python": sys.version.split()[0],
        "packages": {k: md.version(k) for k in ("baostock", "yfinance", "akshare", "pandas")},
        "files": sorted(rec.entries, key=lambda e: e["file"]),
        "failures": rec.failures,
        "notes": ["东方财富个股日线(stock_zh_a_hist_em)：首次取数即被 push2 限流（Push2RateLimitError），按其提示未重试、未绕过，本批个股第二来源改用 AKShare 的新浪接口 stock_zh_a_hist_sina。"],
        "probes": rec.probes,
        "committed_files": {},
    }
    old = {}
    if os.path.exists(a.manifest):
        with open(a.manifest, encoding="utf-8") as f:
            old = json.load(f)
        out["committed_files"] = old.get("committed_files", {})  # build.py 写的部分保留
    with open(a.manifest, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"manifest -> {a.manifest}; files={len(rec.entries)} failures={len(rec.failures)}")
    return 1 if rec.failures else 0


if __name__ == "__main__":
    sys.exit(main())
