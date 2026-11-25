#!/usr/bin/env python3
"""FM-60a 甲批（#2324 第二步）的机械核对。

用法（仓库内任意目录）：  python3 -I fm60a-batch-a/check.py

只用标准库。核对内容：
  1. cases-digitized.jsonl 字段齐全、枚举合法、case_id 唯一，且与清点表同名判例的
     cites / assertion / asserted_values / base_and_pen 逐字一致；
  2. 每条 cites 的 quote 逐字等于语料对应课、对应行 char_span 处的字符；
  3. 每个窗口文件的 sha256 与记录、与 raw-manifest.json 的 committed_files 三处一致；
     窗口目录里没有未登记的文件；
  4. literal_checks 全部由窗口文件重算，结果与记录一致（只做日期与价位的字面核对，不做结构判定）；
  5. 窗口文件的表头、行序、数值可解析。

退出码：0 全过；1 有不符（逐条列出）；2 环境问题（不在 git 仓库、语料或清点表缺）。
"""
import csv
import datetime as dt
import glob
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATUSES = {"已数字化", "需补数据", "不可回归"}
KINDS = {"date", "price_in_bar", "extreme", "touched", "nearest_level", "unavailable"}
CASE_KEYS = [
    "case_id", "cites", "assertion", "asserted_values", "base_and_pen",
    "window_file", "window_sha256", "window_meta", "extra_windows", "source", "adjust",
    "literal_checks", "cross_source", "status", "status_reason",
]
INHERITED = ["cites", "assertion", "asserted_values", "base_and_pen"]
WEEKDAY = "一二三四五六日"


# ---------------- 窗口读取 ----------------
def _col(header, prefix):
    for i, h in enumerate(header):
        if h.startswith(prefix):
            return i
    return None


def read_window(path):
    """返回 bar 列表，每个是 dict：t,o,h,l,c,v,start,status。"""
    with open(path, encoding="utf-8", newline="") as f:
        rd = csv.reader(f)
        header = next(rd)
        ix = {k: _col(header, k) for k in ("时间", "开", "高", "低", "收", "量", "起始日", "状态")}
        for k in ("时间", "开", "高", "低", "收", "量"):
            if ix[k] is None:
                raise ValueError(f"{path}: 表头缺列 {k}")
        bars = []
        for r in rd:
            bars.append({
                "t": r[ix["时间"]],
                "o": float(r[ix["开"]]), "h": float(r[ix["高"]]), "l": float(r[ix["低"]]),
                "c": float(r[ix["收"]]), "v": float(r[ix["量"]]),
                "start": r[ix["起始日"]] if ix["起始日"] is not None else None,
                "status": r[ix["状态"]] if ix["状态"] is not None else "正常",
            })
    return bars


def _r(x):
    return round(x, 4)


def _wd(date):
    return "周" + WEEKDAY[dt.date.fromisoformat(date).weekday()]


# ---------------- 字面核对：只比对日期与价位 ----------------
def k_date(bars, tf, p):
    d = p["date"]
    out = {"星期": _wd(d)}
    if tf == "d":
        for b in bars:
            if b["t"] == d:
                out["结果"] = "停牌" if b["status"] == "停牌" else "交易日"
                return out
        out["结果"] = "非交易日" if bars and bars[0]["t"] <= d <= bars[-1]["t"] else "窗外"
        return out
    for b in bars:
        if b["start"] <= d <= b["t"]:
            out.update({"结果": "落在该根K线", "K线时间": b["t"], "区间起": b["start"], "是否区间末个交易日": d == b["t"]})
            return out
    out["结果"] = "非交易日" if bars and bars[0]["start"] <= d <= bars[-1]["t"] else "窗外"
    return out


def k_price_in_bar(bars, tf, p):
    v = p["value"]
    for b in bars:
        if b["t"] == p["bar"]:
            inside = b["l"] <= v <= b["h"]
            over = 0.0 if inside else (v - b["h"] if v > b["h"] else v - b["l"])
            fields = {"开": b["o"], "高": b["h"], "低": b["l"], "收": b["c"]}
            nf = min(fields, key=lambda k: (abs(v - fields[k]), k))
            return {"K线": {"开": b["o"], "高": b["h"], "低": b["l"], "收": b["c"]},
                    "在最高最低之间": inside, "超出量": _r(over), "最近价位字段": nf, "原文值减该价位": _r(v - fields[nf])}
    return {"结果": "窗口内无此K线"}


def _range(bars, p):
    return [b for b in bars if p["from"] <= b["t"] <= p["to"]]


def k_extreme(bars, tf, p):
    rs = _range(bars, p)
    if not rs:
        return {"结果": "区间内无K线"}
    if p["field"] == "高":
        _, best = max(((b["h"], -i), b) for i, b in enumerate(rs))
        val = best["h"]
    else:
        _, best = min(((b["l"], i), b) for i, b in enumerate(rs))
        val = best["l"]
    return {"极值": val, "K线时间": best["t"], "原文值减极值": _r(p["value"] - val), "区间K线数": len(rs)}


def k_touched(bars, tf, p):
    v = p["value"]
    rs = _range(bars, p)
    hit = [b for b in rs if b["l"] <= v <= b["h"]]
    out = {"区间K线数": len(rs), "触及K线数": len(hit), "首次触及K线": hit[0]["t"] if hit else None}
    if rs:
        lo = min(enumerate(rs), key=lambda ib: (ib[1]["l"], ib[0]))[1]
        hi = max(enumerate(rs), key=lambda ib: (ib[1]["h"], -ib[0]))[1]
        out.update({"区间最低": lo["l"], "区间最低K线": lo["t"], "区间最高": hi["h"], "区间最高K线": hi["t"]})
    return out


def k_nearest_level(bars, tf, p):
    v = p["value"]
    rs = _range(bars, p)
    cand = [(abs(v - b[k]), i, f, b["t"], b[k]) for i, b in enumerate(rs) for f, k in (("高", "h"), ("低", "l"))]
    if not cand:
        return {"结果": "区间内无K线"}
    d, _, f, t, lv = min(cand)
    return {"最近价位": lv, "字段": f, "K线时间": t, "原文值减最近价位": _r(v - lv),
            "含该值的K线数": sum(1 for b in rs if b["l"] <= v <= b["h"]), "区间K线数": len(rs)}


def k_unavailable(bars, tf, p):
    return {"结果": "无法核对", "原因": p["reason"]}


KIND_FN = {"date": k_date, "price_in_bar": k_price_in_bar, "extreme": k_extreme, "touched": k_touched,
           "nearest_level": k_nearest_level, "unavailable": k_unavailable}


def compute(spec, windows):
    """spec 里的 window 取 'primary' 或 extra_windows 的 role；windows: role -> (tf, bars)。"""
    if spec["kind"] == "unavailable":
        return k_unavailable(None, None, spec["params"])
    tf, bars = windows[spec["window"]]
    res = KIND_FN[spec["kind"]](bars, tf, spec["params"])
    return json.loads(json.dumps(res, ensure_ascii=False))  # 与 jsonl 往返后的形态一致


# ---------------- 主流程 ----------------
def die(code, msg):
    print(msg, file=sys.stderr)
    sys.exit(code)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def repo_root():
    r = subprocess.run(["git", "-C", HERE, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode != 0:
        die(2, "不在 git 仓库内：" + r.stderr.strip())
    return r.stdout.strip()


def main():
    root = repo_root()
    blog = os.path.join(root, "docs", "chanlun", "text", "blog")
    corpus = {}

    def lines(k):
        if k not in corpus:
            fs = sorted(glob.glob(os.path.join(blog, f"{k}-*.md")))
            if len(fs) != 1:
                die(2, f"语料里找不到唯一的第 {k} 课文件：{fs}")
            with open(fs[0], encoding="utf-8", newline="") as f:
                corpus[k] = f.read().split("\n")
        return corpus[k]

    inv_path = os.path.join(root, "fm60a-inventory", "cases.jsonl")
    if not os.path.exists(inv_path):
        die(2, "缺清点表 fm60a-inventory/cases.jsonl")
    with open(inv_path, encoding="utf-8") as f:
        inv = {json.loads(x)["case_id"]: json.loads(x) for x in f if x.strip()}

    try:
        with open(os.path.join(HERE, "raw-manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError) as e:
        die(2, f"读不到 raw-manifest.json：{e}")
    committed = manifest.get("committed_files", {})

    recs = []
    with open(os.path.join(HERE, "cases-digitized.jsonl"), encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            if raw.strip():
                try:
                    recs.append(json.loads(raw))
                except ValueError as e:
                    die(1, f"cases-digitized.jsonl 第 {n} 行不是合法 JSON：{e}")

    bad = []
    seen = set()
    used_files = set()
    n_checks = 0
    for c in recs:
        cid = c.get("case_id", "?")
        miss = [k for k in CASE_KEYS if k not in c]
        if miss:
            bad.append(f"{cid}: 缺字段 {miss}")
            continue
        if cid in seen:
            bad.append(f"{cid}: case_id 重复")
        seen.add(cid)
        if c["status"] not in STATUSES:
            bad.append(f"{cid}: status 非法 {c['status']!r}")
        if not c["status_reason"]:
            bad.append(f"{cid}: status_reason 为空")
        if cid not in inv:
            bad.append(f"{cid}: 清点表里没有这条判例")
        else:
            for k in INHERITED:
                if c[k] != inv[cid][k]:
                    bad.append(f"{cid}: 字段 {k} 与清点表不一致")
        # 引文逐字
        for i, ct in enumerate(c["cites"]):
            k, n = ct["lesson"], ct["line"]
            L = lines(k)
            if not (1 <= n <= len(L)):
                bad.append(f"{cid}.cites[{i}]: 行号 {k}:{n} 超出（共 {len(L)} 行）")
                continue
            a, b = ct["char_span"]
            if not (0 <= a < b <= len(L[n - 1])) or L[n - 1][a:b] != ct["quote"]:
                bad.append(f"{cid}.cites[{i}]: quote 与语料 {k}:{n}[{a}:{b}] 不逐字相等")
        # 窗口：主窗口与附加窗口
        wins = {}
        wlist = []
        if c["window_file"] is not None:
            wlist.append(("primary", c["window_file"], c["window_sha256"], c["window_meta"]))
        elif c["window_sha256"] is not None or c["window_meta"] is not None:
            bad.append(f"{cid}: window_file 为空但 sha256 或 meta 非空")
        for ew in c["extra_windows"]:
            wlist.append((ew.get("role"), ew.get("file"), ew.get("sha256"), ew.get("meta")))
        for role, fn, sha, meta in wlist:
            path = os.path.join(HERE, fn)
            used_files.add(os.path.normpath(path))
            if not os.path.exists(path):
                bad.append(f"{cid}: 窗口文件缺失 {fn}")
                continue
            real = sha256_file(path)
            if real != sha:
                bad.append(f"{cid}: {fn} 的 sha256 与 jsonl 记录不一致（现算 {real[:12]}…，记录 {str(sha)[:12]}…）")
            if committed.get(fn) != real:
                bad.append(f"{cid}: {fn} 的 sha256 与 raw-manifest.json committed_files 不一致")
            try:
                wins[role] = (meta["tf"], read_window(path))
            except (ValueError, KeyError, IndexError) as e:
                bad.append(f"{cid}: {fn} 读不出来：{e}")
        # literal_checks 重算
        for j, spec in enumerate(c["literal_checks"]):
            tag = f"{cid}.literal_checks[{j}]"
            for k in ("id", "kind", "literal", "cite", "window", "params", "result"):
                if k not in spec:
                    bad.append(f"{tag}: 缺字段 {k}")
            if spec.get("kind") not in KINDS:
                bad.append(f"{tag}: kind 非法 {spec.get('kind')!r}")
                continue
            ci = spec.get("cite")
            if ci is not None and not (isinstance(ci, int) and 0 <= ci < len(c["cites"])):
                bad.append(f"{tag}: cite 越界 {ci!r}")
            elif ci is not None and spec["kind"] != "unavailable" and spec["literal"] not in c["cites"][ci]["quote"]:
                bad.append(f"{tag}: literal {spec['literal']!r} 不在 cites[{ci}].quote 中")
            if spec["kind"] != "unavailable" and spec["window"] not in wins:
                bad.append(f"{tag}: 找不到窗口 {spec['window']!r}")
                continue
            try:
                want = compute(spec, wins)
            except (KeyError, ValueError, TypeError) as e:
                bad.append(f"{tag}: 重算出错 {e!r}")
                continue
            n_checks += 1
            if want != spec["result"]:
                bad.append(f"{tag}: 记录的结果与窗口重算不一致\n      记录 {spec['result']}\n      重算 {want}")
        if c["status"] == "已数字化" and c["window_file"] is None:
            bad.append(f"{cid}: 已数字化但没有窗口文件")

    # 窗口目录里不得有未登记文件，committed_files 里不得有悬空项
    for p in glob.glob(os.path.join(HERE, "windows", "*")):
        if os.path.normpath(p) not in used_files:
            bad.append(f"windows/{os.path.basename(p)}: 未被任何判例登记")
    for fn, sha in committed.items():
        path = os.path.join(HERE, fn)
        if not os.path.exists(path):
            bad.append(f"committed_files 登记的 {fn} 不存在")
        elif sha256_file(path) != sha:
            bad.append(f"committed_files 登记的 {fn} sha256 不符")

    if bad:
        print(f"不符 {len(bad)} 处：")
        for s in bad:
            print("  -", s)
        sys.exit(1)
    from collections import Counter
    print(f"全部通过：{len(recs)} 条判例，{n_checks} 项字面核对重算一致，{len(used_files)} 个窗口文件")
    print("status：", dict(Counter(c["status"] for c in recs)))
    sys.exit(0)


if __name__ == "__main__":
    main()
