"""把 `census.py` 的 JSON 输出压成结论文档用的两张表。

用法：python3 summary.py <标题> <段数表或 all> <a.json> [b.json ...]
段数表形如 `9,10,11`。同一标题下的多个文件按段数合并（例如 packed9 与 packed10only）。
"""

import json
import sys

MULTI = ["ANY_FULL", "ANY_EXH", "EXT_EXH", "HIGH"]
UNIQUE = ["SAME", "MIN", "MAX", "NOCAP", "CARRY"]


def main():
    title = sys.argv[1]
    data = {}
    pick = None if sys.argv[2] == "all" else {int(x) for x in sys.argv[2].split(",")}
    for f in sys.argv[3:]:
        for n, st in json.load(open(f)).items():
            data[int(n)] = st
    ns = sorted(n for n in data if pick is None or n in pick)
    print(f"### {title}：合法分解个数分布\n")
    print("每格 `0 个 / 恰 1 个 / 多于 1 个`。末列是五个起点定终点政策是否在全部折线上恰有 1 个。\n")
    print("| 段数 | 条数 | " + " | ".join(MULTI) + " | LEXMIN_FULL 与 LEXMAX_FULL | 五个唯一政策 |")
    print("|---|---|" + "---|" * (len(MULTI) + 2))
    for n in ns:
        st = data[n]
        cells = ["{}/{}/{}".format(*st[p]["c"]) for p in MULTI]
        lex = "{}/{}/{}".format(*st["LEXMIN_FULL"]["c"])
        assert st["LEXMIN_FULL"]["c"] == st["LEXMAX_FULL"]["c"]
        allone = all(st[p]["c"] == [0, st["paths"], 0] for p in UNIQUE)
        print(f"| {n} | {st['paths']} | " + " | ".join(cells) + f" | {lex} | {'全部恰 1 个' if allone else '有例外'} |")
    print(f"\n### {title}：五个唯一政策的覆盖与稳定性\n")
    print("每格 `覆盖率 / 零块条数 / 尾部不短于三段的条数 / 上一级成块条数 / 改写条数`。\n")
    print("| 段数 | " + " | ".join(UNIQUE) + " |")
    print("|---|" + "---|" * len(UNIQUE))
    for n in ns:
        st = data[n]
        if n < 3:
            continue
        cells = []
        for p in UNIQUE:
            ps = st[p]
            cov = ps["cov"] / st["segsum"]
            cells.append(f"{cov:.2f} / {ps['noblock']} / {ps['tail3']} / {ps['lvl2']} / {ps['unstable']}")
        print(f"| {n} | " + " | ".join(cells) + " |")
    print()


if __name__ == "__main__":
    main()
