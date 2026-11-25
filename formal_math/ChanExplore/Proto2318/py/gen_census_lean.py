"""由 Python 读数生成 `../Census.lean` 的 `#guard`，让 Lean 构建直接核对两侧一致。

用法：python3 gen_census_lean.py out/raw3_18.json out/raw4_13.json out/packed9.json > ../Census.lean

- `Fin 3`、`Fin 4` 的读数取自 `census.py raw` 的直接枚举。
- `Fin 5` 的读数取自 `census.py packed` 按 C(k, m) 加权的结果，
  所以 Lean 的直接枚举同时核对了序型加权这条路。
"""

import json
import sys

ORDER = ["ANY_FULL", "ANY_EXH", "SAME", "MIN", "MAX", "EXT_EXH", "NOCAP", "CARRY"]
PLAN = [(3, [3, 5, 7, 8, 9]), (4, [1, 2, 3, 4, 5, 6]), (5, [5])]


def main():
    raw3 = json.load(open(sys.argv[1]))
    raw4 = json.load(open(sys.argv[2]))
    packed = json.load(open(sys.argv[3]))

    def reading(k, n):
        if k == 3:
            return [tuple(raw3[str(n)][p]["c"]) for p in ORDER]
        if k == 4:
            return [tuple(raw4[str(n)][p]["c"]) for p in ORDER]
        return [tuple(packed[str(n)][p]["w"][str(k)]) for p in ORDER]

    print("module")
    print()
    print("meta import ChanExplore.Proto2318.Enum")
    print()
    print("/-!")
    print("# Lean 与 Python 读数的逐格比对")
    print()
    print("本文件由 `py/gen_census_lean.py` 生成，不手改。每条 `#guard` 的右端是 Python 读数，")
    print("左端由 Lean 对 `Fin k` 上恰 `n` 段的全部方向交替折线穷举全部良构切点表算出。")
    print("三元组依次是合法分解个数为 0、恰为 1、多于 1 的折线条数；")
    print("政策顺序是 anyFull、anyExh、same、minimal、maximal、extExh、noCap、carry。")
    print("-/")
    print()
    print("namespace ChanExplore.Proto2318")
    print()
    for k, ns in PLAN:
        for n in ns:
            r = reading(k, n)
            body = ", ".join(f"({a}, {b}, {c})" for a, b, c in r)
            print(f"-- Fin {k}，{n} 段，共 {sum(r[0])} 条折线")
            print(f"#guard allPolicies.map (fun p => census p {k} {n}) ==")
            print(f"  [{body}]")
            print()
    print("end ChanExplore.Proto2318")


if __name__ == "__main__":
    main()
