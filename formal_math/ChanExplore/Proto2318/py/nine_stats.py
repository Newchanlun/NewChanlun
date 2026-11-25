"""九段延伸的读数：延伸满九段的折线里，按 3+3+3 重切后各组自身有没有三段重叠。

用法：python3 nine_stats.py [段数=9]
"""

import sys

import model


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    total = nine = g2 = g3 = both = lvl2 = 0
    wit = None
    for w, _m in model.packed_alt(n + 1):
        total += 1
        S = model.segs(w)
        if not model.nine(S, 0):
            continue
        nine += 1
        a, b = model.ov3(S, 3), model.ov3(S, 6)
        if not a:
            g2 += 1
        if not b:
            g3 += 1
        if not a and not b:
            both += 1
        if (not a or not b) and (wit is None or w < wit):
            wit = list(w)
        if model.b_same(model.coarsen(S, (0, 3, 6, 9)), 0, 3):
            lvl2 += 1
    print(f"{n} 段序型代表元 {total} 条，其中自首段起延伸满九段 {nine} 条")
    print(f"第二组（第 4 至 6 段）自身无三段重叠：{g2} 条")
    print(f"第三组（第 7 至 9 段）自身无三段重叠：{g3} 条")
    print(f"第二、三组都没有：{both} 条")
    print(f"按 3+3+3 取三组实际值域后有公共部分：{lvl2} 条")
    print(f"字典序最小的缺种子见证：{wit}")


if __name__ == "__main__":
    main()
