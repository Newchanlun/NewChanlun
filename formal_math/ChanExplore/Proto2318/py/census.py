"""小模型穷举：每个候选政策下合法分解个数的分布。

用法：
  python3 census.py packed <N> [进程数=4] [输出.json] [起始段数=1]
      对段数 起始..N 的全部序型代表元（方向交替、取值恰为 {0..m-1}）穷举。
      谓词只比较价位大小，所以 n 段折线至多 n+1 个不同价位，
      序型穷举对任意线序价位域都完备；`Fin k` 上的原始条数按 C(k, m) 加权得到。
  python3 census.py raw <k> <N> [进程数=4] [输出.json]
      直接枚举 `Fin k` 上段数 1..N 的全部方向交替折线，不归并序型。

每条折线记录：各政策合法分解个数（0、1、多于 1）、唯一政策的完成覆盖与尾长、
唯一政策两两是否同切、上一级按同级别规则是否成块、去掉末段后已完成切点是否保持。
"""

import json
import sys
from math import comb
from multiprocessing import Pool

import model

KS = [2, 3, 4, 5, 6, 8, 10]
PAIRS = [(a, b) for i, a in enumerate(model.UNIQUE) for b in model.UNIQUE[i + 1 :]]


def new_stat():
    st = {"paths": 0}
    for p in model.POLICIES:
        st[p] = {
            "c": [0, 0, 0],
            "w": {k: [0, 0, 0] for k in KS},
            "max": 0,
            "multi_wit": None,
            "zero_wit": None,
        }
    for p in model.UNIQUE:
        st[p].update(
            {"cov": 0, "noblock": 0, "tail3": 0, "lvl2": 0, "unstable": 0, "unstable_wit": None}
        )
    st["segsum"] = 0
    st["pair"] = {f"{a}|{b}": [0, None] for a, b in PAIRS}
    return st


def keep_min(old, new):
    if old is None:
        return new
    return min(old, new)


def feed(st, w, m, weighted):
    S = model.segs(w)
    n = len(S)
    res = model.analyze(S)
    prev = model.analyze(S[:-1], want_global=False) if n >= 2 else None
    st["paths"] += 1
    st["segsum"] += n
    wt = tuple(w)
    for p in model.POLICIES:
        ds = res[p]
        cls = 0 if not ds else (1 if len(ds) == 1 else 2)
        ps = st[p]
        ps["c"][cls] += 1
        if weighted:
            for k in KS:
                if m <= k:
                    ps["w"][k][cls] += comb(k, m)
        if len(ds) > ps["max"]:
            ps["max"] = len(ds)
        if cls == 2:
            ps["multi_wit"] = keep_min(ps["multi_wit"], wt)
        elif cls == 0:
            ps["zero_wit"] = keep_min(ps["zero_wit"], wt)
    for p in model.UNIQUE:
        d = res[p][0]
        ps = st[p]
        ps["cov"] += d[-1]
        if len(d) == 1:
            ps["noblock"] += 1
        if n - d[-1] >= 3:
            ps["tail3"] += 1
        if len(d) >= 4 and model.b_same(model.coarsen(S, d), 0, 3):
            ps["lvl2"] += 1
        if prev is not None:
            d0 = prev[p][0]
            if d[: len(d0)] != d0:
                ps["unstable"] += 1
                ps["unstable_wit"] = keep_min(ps["unstable_wit"], wt)
    for a, b in PAIRS:
        if res[a][0] != res[b][0]:
            cell = st["pair"][f"{a}|{b}"]
            cell[0] += 1
            cell[1] = keep_min(cell[1], wt)


def merge(a, b):
    a["paths"] += b["paths"]
    a["segsum"] += b["segsum"]
    for p in model.POLICIES:
        x, y = a[p], b[p]
        for i in range(3):
            x["c"][i] += y["c"][i]
            for k in KS:
                x["w"][k][i] += y["w"][k][i]
        x["max"] = max(x["max"], y["max"])
        for key in ("multi_wit", "zero_wit", "unstable_wit"):
            if key in y and y[key] is not None:
                x[key] = keep_min(x[key], tuple(y[key]))
        for key in ("cov", "noblock", "tail3", "lvl2", "unstable"):
            if key in y:
                x[key] += y[key]
    for key, (cnt, wit) in b["pair"].items():
        a["pair"][key][0] += cnt
        if wit is not None:
            a["pair"][key][1] = keep_min(a["pair"][key][1], tuple(wit))
    return a


def work_packed(arg):
    state, L = arg
    st = new_stat()
    for w, m in model.packed_alt_from(state, L):
        feed(st, w, m, True)
    return st


def work_raw(arg):
    first, up, L, k = arg
    st = new_stat()
    stack = [([first], up)]
    while stack:
        w, u = stack.pop()
        if len(w) == L:
            feed(st, w, 0, False)
            continue
        last = w[-1]
        for v in range(last + 1, k) if u else range(last):
            stack.append((w + [v], not u))
    return st


def run(mode, args, procs, nmin=1):
    out = {}
    with Pool(procs) as pool:
        if mode == "packed":
            N = args[0]
            for n in range(nmin, N + 1):
                L = n + 1
                jobs = [(s, L) for s in model.packed_alt_prefixes(L, min(L, 5))]
                st = new_stat()
                for part in pool.imap_unordered(work_packed, jobs, chunksize=4):
                    merge(st, part)
                out[n] = st
                print(f"# packed n={n} 序型 {st['paths']} 条", file=sys.stderr, flush=True)
        else:
            k, N = args
            for n in range(1, N + 1):
                jobs = [(v, up, n + 1, k) for v in range(k) for up in (True, False)]
                st = new_stat()
                for part in pool.imap_unordered(work_raw, jobs):
                    merge(st, part)
                out[n] = st
                print(f"# raw k={k} n={n} 折线 {st['paths']} 条", file=sys.stderr, flush=True)
    return out


def table(out, mode, k=None):
    ns = sorted(out)
    print(f"## 合法分解个数分布（{'序型代表元' if mode == 'packed' else f'Fin {k} 原始折线'}）")
    print("每格为 `0 个 / 恰 1 个 / 多于 1 个`，括号内是单条折线上的最大个数。\n")
    print("| 段数 | 条数 | " + " | ".join(model.POLICIES) + " |")
    print("|---|---|" + "---|" * len(model.POLICIES))
    for n in ns:
        st = out[n]
        cells = [
            "{}/{}/{} ({})".format(*st[p]["c"], st[p]["max"]) for p in model.POLICIES
        ]
        print(f"| {n} | {st['paths']} | " + " | ".join(cells) + " |")
    print("\n## 唯一政策的覆盖与稳定性\n")
    print("覆盖率是已完成块覆盖的段数占全部段数的比例；零块是没有任何已完成块的条数；")
    print("尾≥3 是未完成尾部不短于三段的条数；上级成块是上一级按同级别规则至少成一块的条数；")
    print("改写是去掉末段后的已完成切点不再是现切点前缀的条数。\n")
    print("| 段数 | 政策 | 覆盖率 | 零块 | 尾≥3 | 上级成块 | 改写 |")
    print("|---|---|---|---|---|---|---|")
    for n in ns:
        st = out[n]
        for p in model.UNIQUE:
            ps = st[p]
            cov = ps["cov"] / st["segsum"] if st["segsum"] else 0
            print(
                f"| {n} | {p} | {cov:.3f} | {ps['noblock']} | {ps['tail3']} | {ps['lvl2']} | {ps['unstable']} |"
            )
    print("\n## 唯一政策两两不同切的条数\n")
    print("| 段数 | " + " | ".join(f"{a}≠{b}" for a, b in PAIRS) + " |")
    print("|---|" + "---|" * len(PAIRS))
    for n in ns:
        print(
            f"| {n} | "
            + " | ".join(str(out[n]["pair"][f"{a}|{b}"][0]) for a, b in PAIRS)
            + " |"
        )
    print("\n## 最小见证（按段数、再按端点表字典序）\n")
    for p in model.POLICIES:
        for key, label in (("multi_wit", "多于一个"), ("zero_wit", "零个"), ("unstable_wit", "改写")):
            for n in ns:
                wit = out[n][p].get(key)
                if wit is not None:
                    print(f"- {p} {label}: n={n} 端点 {list(wit)}")
                    break
    for a, b in PAIRS:
        for n in ns:
            wit = out[n]["pair"][f"{a}|{b}"][1]
            if wit is not None:
                print(f"- {a}≠{b}: n={n} 端点 {list(wit)}")
                break
    if mode == "packed":
        print("\n## 按 C(k, m) 加权得到的 `Fin k` 原始条数\n")
        print("| 段数 | k | " + " | ".join(model.POLICIES) + " |")
        print("|---|---|" + "---|" * len(model.POLICIES))
        for n in ns:
            for kk in KS:
                cells = ["{}/{}/{}".format(*out[n][p]["w"][kk]) for p in model.POLICIES]
                print(f"| {n} | {kk} | " + " | ".join(cells) + " |")


def main():
    mode = sys.argv[1]
    if mode == "packed":
        args = [int(sys.argv[2])]
        rest = sys.argv[3:]
        k = None
    else:
        args = [int(sys.argv[2]), int(sys.argv[3])]
        rest = sys.argv[4:]
        k = args[0]
    procs = int(rest[0]) if rest else 4
    nmin = int(rest[2]) if len(rest) > 2 else 1
    out = run(mode, args, procs, nmin)
    if len(rest) > 1:
        with open(rest[1], "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
    table(out, mode, k)


if __name__ == "__main__":
    main()
