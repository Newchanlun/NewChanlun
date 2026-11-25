"""接口律的小模型读数：镜像等变、保序变换不变。

用法：python3 invariance.py [最大段数=7]

对段数不超过上界的全部序型代表元：
- 镜像（价位取反）后各局部政策的合法分解集合应当不变；
- 保序拉伸（价位换成另一组保序取值）后应当不变。
"""

import sys

import model


def cuts_set(points):
    res = model.analyze(model.segs(points), want_global=False)
    return {p: sorted(res[p]) for p in model.LOCAL}


def main():
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    stretch = [3, 4, 9, 10, 11, 17, 30, 31, 40, 41, 50]
    total = 0
    mirror_bad = 0
    stretch_bad = 0
    for n in range(1, N + 1):
        for w, m in model.packed_alt(n + 1):
            total += 1
            base = cuts_set(w)
            if cuts_set([m - 1 - v for v in w]) != base:
                mirror_bad += 1
            if cuts_set([stretch[v] for v in w]) != base:
                stretch_bad += 1
    print(f"序型代表元 {total} 条（段数 1..{N}）")
    print(f"镜像后合法分解集合改变的条数：{mirror_bad}")
    print(f"保序拉伸后合法分解集合改变的条数：{stretch_bad}")


if __name__ == "__main__":
    main()
