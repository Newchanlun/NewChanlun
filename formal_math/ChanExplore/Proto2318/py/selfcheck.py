"""核对 `analyze`（带预计算的枚举器）与 `brute`（照定义穷举全部切点子集）逐条一致。

用法：python3 selfcheck.py [局部政策的最大段数=7] [全局政策的最大段数=5] [抽样条数=3000]

- 局部政策：对段数不超过上界的全部序型代表元逐条比对。
- 全局政策（LEX、HIGH）：`brute` 的代价是切点子集数的平方，只查到较小的段数。
- 另对段数 8 至 12 的折线做定种子抽样，覆盖九项进位与上一级计分的分支。
"""

import random
import sys

import model


def check(points, policies):
    S = model.segs(points)
    fast = model.analyze(S)
    for p in policies:
        a = sorted(fast[p])
        b = model.brute(p, S)
        if a != b:
            print("MISMATCH", p, points, a, b)
            return False
    return True


def random_path(rng, n, k):
    while True:
        w = [rng.randrange(k)]
        up = rng.random() < 0.5
        ok = True
        for _ in range(n):
            last = w[-1]
            choices = list(range(last + 1, k)) if up else list(range(last))
            if not choices:
                ok = False
                break
            w.append(rng.choice(choices))
            up = not up
        if ok:
            return w


def main():
    nl = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    ng = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    samples = int(sys.argv[3]) if len(sys.argv) > 3 else 3000
    total = 0
    for n in range(1, nl + 1):
        pol = model.POLICIES if n <= ng else model.LOCAL
        c = 0
        for w, _m in model.packed_alt(n + 1):
            if not check(w, pol):
                sys.exit(1)
            c += 1
        total += c
        print(f"n={n} 序型 {c} 条，政策 {len(pol)} 个：一致")
    rng = random.Random(2318)
    c = 0
    for i in range(samples):
        n = 8 + i % 5
        k = 2 + i % 4
        w = random_path(rng, n, k)
        pol = model.LOCAL if n > 10 else model.LOCAL + ["HIGH"]
        if not check(w, pol):
            sys.exit(1)
        c += 1
    print(f"抽样（种子 2318，段数 8..12，价位 2..5）{c} 条：一致")
    print(f"SELFCHECK OK，共 {total + c} 条")


if __name__ == "__main__":
    main()
