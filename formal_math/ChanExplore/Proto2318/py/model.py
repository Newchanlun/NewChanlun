"""#2318 FM-10a 预搜模型：区间序列上的候选规范谓词。

只用标准库。两套实现互相独立：

- `valid(policy, S, cuts)`：照定义直写的声明式检查器，判断给定的 `cuts` 是否满足规范；
  它不产生分解，只判定关系 `ValidDecomp policy S cuts`。Lean 侧的谓词逐条对应它。
- `analyze(S)`：带预计算的枚举器，列出每个政策下全部合法分解。
  `selfcheck.py` 用穷举全部切点子集的办法核对两者一致。

记号：`S` 是区间序列（每项 `(lo, hi)`），第 0 级由折线相邻端点生成。
`cuts` 是严格递增的切点下标表，首项恒为 0；末项到 `len(S)` 之间是未完成尾部。
块 `(s, e)` 指 `S[s:e]`。
"""

from itertools import combinations

# ---------------------------------------------------------------- 基本对象


def segs(points):
    """折线端点表 → 第 0 级区间序列。"""
    return [(min(a, b), max(a, b)) for a, b in zip(points, points[1:])]


def ov3(S, i):
    """`S[i], S[i+1], S[i+2]` 有公共重叠（闭区间，单点也算）。"""
    if i < 0 or i + 3 > len(S):
        return False
    return max(S[i][0], S[i + 1][0], S[i + 2][0]) <= min(S[i][1], S[i + 1][1], S[i + 2][1])


def core(S, i):
    return (max(S[i][0], S[i + 1][0], S[i + 2][0]), min(S[i][1], S[i + 1][1], S[i + 2][1]))


def touch(x, c):
    return x[0] <= c[1] and c[0] <= x[1]


def hull(items):
    return (min(x[0] for x in items), max(x[1] for x in items))


def coarsen(S, cuts):
    """已完成块的实际值域序列；尾部不进上一级。"""
    return [hull(S[a:b]) for a, b in zip(cuts, cuts[1:])]


def wf(cuts, n):
    return (
        len(cuts) >= 1
        and cuts[0] == 0
        and all(a < b for a, b in zip(cuts, cuts[1:]))
        and cuts[-1] <= n
    )


# ---------------------------------------------------------------- 块语言（照定义直写）


def b_same(S, s, e):
    """同级别：恰三项且有公共重叠（038:22、041:259）。"""
    return e == s + 3 and ov3(S, s)


def b_any(S, s, e):
    """接口律下限：奇数项、至少三项、不到九项、块内某处有三项重叠。"""
    n = len(S)
    L = e - s
    return e <= n and L % 2 == 1 and 3 <= L <= 7 and any(ov3(S, i) for i in range(s, e - 2))


def b_ext(S, s, e):
    """单中枢块：块首三项成核，其后各项都触及该核，不到九项。"""
    n = len(S)
    L = e - s
    if not (e <= n and L % 2 == 1 and 3 <= L <= 7 and ov3(S, s)):
        return False
    c = core(S, s)
    return all(touch(S[j], c) for j in range(s + 3, e))


def _broken_at(S, s, e):
    """存在首个不触核项 f，且 f 为 e 或 e+1（018:64 的离开加不回）。"""
    n = len(S)
    if not ov3(S, s):
        return False
    c = core(S, s)
    for f in (e, e + 1):
        if f < n and not touch(S[f], c) and all(touch(S[j], c) for j in range(s + 3, f)):
            return True
    return False


def b_nocap(S, s, e):
    """不设上限：核被破坏才成块，块长任意奇数（018:40、020:34 对照实例）。"""
    L = e - s
    return e <= len(S) and L % 2 == 1 and L >= 3 and _broken_at(S, s, e)


def b_brk(S, s, e):
    """进位有界下的普通块：核被破坏才成块，且不到九项。"""
    return b_ext(S, s, e) and _broken_at(S, s, e)


def nine(S, s):
    """块首三项成核，其后六项都触及原核：延伸满九项（066:186）。"""
    if s + 9 > len(S) or not ov3(S, s):
        return False
    c = core(S, s)
    return all(touch(S[j], c) for j in range(s + 3, s + 9))


# ---------------------------------------------------------------- 尾部与选择条款


def t_full(S, c):
    return c == len(S)


def t_exh(B):
    """尾部穷尽：尾部起点上不再有任何已完成块。"""
    return lambda S, c: not any(B(S, c, e) for e in range(c + 1, len(S) + 1))


def sel_min(B):
    """最早成块：块没有同起点的更短合法块。"""
    return lambda S, s, e: B(S, s, e) and not any(B(S, s, x) for x in range(s + 1, e))


def sel_max(B):
    """最晚成块：块没有同起点的更长合法块。"""
    return lambda S, s, e: B(S, s, e) and not any(B(S, s, x) for x in range(e + 1, len(S) + 1))


def chain_ok(B, T, S, cuts):
    return all(B(S, a, b) for a, b in zip(cuts, cuts[1:])) and T(S, cuts[-1])


def t_carry(S, c):
    return (not any(b_brk(S, c, e) for e in range(c + 1, len(S) + 1))) and not nine(S, c)


def carry_ok(S, cuts):
    """规范进位：普通块按破坏成块；延伸满九项时按 3+3+3 连切三块。

    状态 0 是普通位置，1、2 是九项组里的第二、第三块。
    """
    st = 0
    for a, b in zip(cuts, cuts[1:]):
        if st == 0:
            if b_brk(S, a, b):
                continue
            if nine(S, a) and b == a + 3:
                st = 1
                continue
            return False
        if b != a + 3:
            return False
        st = (st + 1) % 3
    return st == 0 and t_carry(S, cuts[-1])


CHAIN = {
    "ANY_FULL": (b_any, t_full),
    "ANY_EXH": (b_any, t_exh(b_any)),
    "SAME": (b_same, t_exh(b_same)),
    "MIN": (sel_min(b_any), t_exh(b_any)),
    "MAX": (sel_max(b_any), t_exh(b_any)),
    "EXT_EXH": (b_ext, t_exh(b_ext)),
    "NOCAP": (b_nocap, t_exh(b_nocap)),
}
LOCAL = list(CHAIN) + ["CARRY"]
GLOBAL = ["LEXMIN_FULL", "LEXMAX_FULL", "HIGH"]
POLICIES = LOCAL + GLOBAL
# 每个起点至多一个终点的块语言，可谈前缀稳定与逐级复合。
UNIQUE = ["SAME", "MIN", "MAX", "NOCAP", "CARRY"]


def all_cuts(n):
    """全部良构切点表：首项 0，其余取自 1..n 的任意子集。"""
    for r in range(n + 1):
        for rest in combinations(range(1, n + 1), r):
            yield (0,) + rest


def level2_score(S, cuts):
    """上一级按同级别规则能成几块（高级别中枢优先的比较量）。"""
    T = coarsen(S, cuts)
    k = 0
    while b_same(T, 3 * k, 3 * k + 3):
        k += 1
    return k


def valid(policy, S, cuts):
    """声明式规范 `ValidDecomp policy S cuts`。"""
    cuts = tuple(cuts)
    if not wf(cuts, len(S)):
        return False
    if policy in CHAIN:
        B, T = CHAIN[policy]
        return chain_ok(B, T, S, cuts)
    if policy == "CARRY":
        return carry_ok(S, cuts)
    if policy in ("LEXMIN_FULL", "LEXMAX_FULL"):
        if not valid("ANY_FULL", S, cuts):
            return False
        others = [d for d in all_cuts(len(S)) if valid("ANY_FULL", S, d)]
        if policy == "LEXMIN_FULL":
            return all(cuts <= d for d in others)
        return all(d <= cuts for d in others)
    if policy == "HIGH":
        if not valid("ANY_EXH", S, cuts):
            return False
        mine = level2_score(S, cuts)
        return all(
            level2_score(S, d) <= mine for d in all_cuts(len(S)) if valid("ANY_EXH", S, d)
        )
    raise KeyError(policy)


def brute(policy, S):
    """穷举全部切点子集后按规范筛。只用于小规模核对。"""
    return sorted(d for d in all_cuts(len(S)) if valid(policy, S, d))


# ---------------------------------------------------------------- 带预计算的枚举器


def _pre(S):
    n = len(S)
    ov = [ov3(S, i) for i in range(n)]
    run = [0] * n  # 首个不触核项的下标；一直触核则为 n
    for s in range(n):
        if ov[s]:
            c = core(S, s)
            f = s + 3
            while f < n and S[f][0] <= c[1] and c[0] <= S[f][1]:
                f += 1
            run[s] = f
    return n, ov, run


def _ends(n, ov, run):
    """每个政策下起点 s 的合法终点表。"""
    any_e = [[] for _ in range(n + 1)]
    ext_e = [[] for _ in range(n + 1)]
    brk_e = [[] for _ in range(n + 1)]
    nocap_e = [[] for _ in range(n + 1)]
    same_e = [[] for _ in range(n + 1)]
    nine_s = [False] * (n + 1)
    for s in range(n):
        first = None  # 自 s 起首个重叠三项的下标
        for i in range(s, min(n - 2, s + 5)):
            if ov[i]:
                first = i
                break
        if first is not None:
            for e in (s + 3, s + 5, s + 7):
                if e <= n and first + 3 <= e:
                    any_e[s].append(e)
        if ov[s]:
            f = run[s]
            same_e[s].append(s + 3)
            for e in (s + 3, s + 5, s + 7):
                if e <= f:
                    ext_e[s].append(e)
            if f < n:
                e = f if (f - s) % 2 == 1 else f - 1
                nocap_e[s].append(e)
                if e - s <= 7:
                    brk_e[s].append(e)
            if f >= s + 9:
                nine_s[s] = True
    return any_e, ext_e, brk_e, nocap_e, same_e, nine_s


def _walk(ends, tail_ok, n):
    """沿终点表列出全部分解。"""
    out = []

    def rec(s, acc):
        if tail_ok(s):
            out.append(tuple(acc))
        for e in ends[s]:
            acc.append(e)
            rec(e, acc)
            acc.pop()

    rec(0, [0])
    return out


def analyze(S, want_global=True):
    """返回 {政策: 合法分解列表}。"""
    n, ov, run = _pre(S)
    any_e, ext_e, brk_e, nocap_e, same_e, nine_s = _ends(n, ov, run)
    res = {}
    res["ANY_FULL"] = _walk(any_e, lambda s: s == n, n)
    res["ANY_EXH"] = _walk(any_e, lambda s: not any_e[s], n)
    res["SAME"] = _walk(same_e, lambda s: not same_e[s], n)
    res["MIN"] = _walk([e[:1] for e in any_e], lambda s: not any_e[s], n)
    res["MAX"] = _walk([e[-1:] for e in any_e], lambda s: not any_e[s], n)
    res["EXT_EXH"] = _walk(ext_e, lambda s: not ext_e[s], n)
    res["NOCAP"] = _walk(nocap_e, lambda s: not nocap_e[s], n)

    carry = []

    def rec(s, acc):
        if not brk_e[s] and not nine_s[s]:
            carry.append(tuple(acc))
        for e in brk_e[s]:
            acc.append(e)
            rec(e, acc)
            acc.pop()
        if nine_s[s]:
            acc.extend((s + 3, s + 6, s + 9))
            rec(s + 9, acc)
            del acc[-3:]

    rec(0, [0])
    res["CARRY"] = carry

    if want_global:
        full = res["ANY_FULL"]
        res["LEXMIN_FULL"] = [min(full)] if full else []
        res["LEXMAX_FULL"] = [max(full)] if full else []
        exh = res["ANY_EXH"]
        if n >= 9 and exh:
            sc = [level2_score(S, d) for d in exh]
            top = max(sc)
            res["HIGH"] = [d for d, x in zip(exh, sc) if x == top]
        else:
            res["HIGH"] = list(exh)
    return res


# ---------------------------------------------------------------- 枚举折线


def packed_alt_prefixes(L, depth):
    """方向交替、取值恰为 {0..m-1} 的词（序型代表元）的前缀状态。"""
    out = []

    def rec(w, m, up):
        if len(w) == depth or len(w) == L:
            out.append((tuple(w), m, up))
            return
        last = w[-1]
        for v in range(m):
            if (v > last) if up else (v < last):
                rec(w + [v], m, not up)
        for g in range(m + 1):
            if (g > last) if up else (g <= last):
                rec([x + 1 if x >= g else x for x in w] + [g], m + 1, not up)

    rec([0], 1, True)
    rec([0], 1, False)
    return out


def packed_alt_from(state, L):
    """从前缀状态展开到长度 L。产出 (词, 不同取值个数)。"""
    w0, m0, up0 = state
    stack = [(list(w0), m0, up0)]
    while stack:
        w, m, up = stack.pop()
        if len(w) == L:
            yield w, m
            continue
        last = w[-1]
        for v in range(m):
            if (v > last) if up else (v < last):
                stack.append((w + [v], m, not up))
        for g in range(m + 1):
            if (g > last) if up else (g <= last):
                stack.append(([x + 1 if x >= g else x for x in w] + [g], m + 1, not up))


def packed_alt(L):
    for st in packed_alt_prefixes(L, 1):
        yield from packed_alt_from(st, L)


def raw_alt(L, k):
    """`Fin k` 上长度 L 的全部方向交替词（不做序型归并）。"""
    stack = [([v], up) for v in range(k) for up in (True, False)]
    while stack:
        w, up = stack.pop()
        if len(w) == L:
            yield w
            continue
        last = w[-1]
        rng = range(last + 1, k) if up else range(last)
        for v in rng:
            stack.append((w + [v], not up))
