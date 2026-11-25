"""判别例读数：每个政策下的全部合法分解，以及 3+5、5+3 两种切法是否合法。

用法：python3 cases.py
"""

import model

CASES = [
    ("八段来回 0,1", [0, 1, 0, 1, 0, 1, 0, 1, 0]),
    ("九段来回 0,1", [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]),
    ("十一段来回 0,1", [0, 1] * 6),
    ("十二段来回 0,1", [0, 1] * 6 + [0]),
    ("九段折线（设计输入）", [0, 20, 2, 22, 12, 18, 16, 19, 4, 8]),
    ("七段阶梯上行", [0, 3, 2, 5, 4, 7, 6, 9]),
    ("首三段不重叠", [5, 6, 0, 1, 0, 1, 0, 1]),
]


def fmt(d, n):
    parts = [str(b - a) for a, b in zip(d, d[1:])]
    tail = n - d[-1]
    body = "+".join(parts) if parts else "无完成块"
    return f"{body}|尾{tail}"


def main():
    for name, pts in CASES:
        S = model.segs(pts)
        n = len(S)
        res = model.analyze(S)
        print(f"== {name}  端点 {pts}  段数 {n}")
        for p in model.POLICIES:
            ds = sorted(res[p])
            print(f"  {p:12s} {len(ds)} 个: " + "  ".join(fmt(d, n) for d in ds))
        if n == 8:
            for label, d in (("3+5", (0, 3, 8)), ("5+3", (0, 5, 8))):
                ok = [p for p in model.POLICIES if model.valid(p, S, d)]
                print(f"  切法 {label} 合法于: {', '.join(ok) if ok else '无'}")
        if n >= 9:
            for p in model.UNIQUE:
                for d in res[p]:
                    T = model.coarsen(S, d)
                    r2 = model.analyze(T, want_global=False)["SAME"]
                    print(f"  {p:6s} 上一级值域 {T} 同级别再分 {[fmt(x, len(T)) for x in r2]}")
    # 两个三段种子：端点与核相同，外缘不同
    for pts in ([0, 4, 2, 3], [0, 7, 2, 3]):
        S = model.segs(pts)
        print(f"种子 {pts}: 端点 ({pts[0]},{pts[-1]}) 核 {model.core(S, 0)} 值域 {model.hull(S)}")


if __name__ == "__main__":
    main()
