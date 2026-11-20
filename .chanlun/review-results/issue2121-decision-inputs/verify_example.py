"""#2121 arithmetic oracle. No product code and no external dependencies."""
from collections import Counter
from fractions import Fraction
from itertools import product

MASK32 = (1 << 32) - 1
MASK64 = (1 << 64) - 1


def pcg(seed, stream):
    inc = (2 * stream + 1) & MASK64
    # Two discarded initialization outputs.
    state = (6364136223846793005 * ((inc + seed) & MASK64) + inc) & MASK64
    while True:
        word = (((state >> 18) ^ state) >> 27) & MASK32
        rot = state >> 59
        yield ((word >> rot) | (word << ((-rot) & 31))) & MASK32
        state = (6364136223846793005 * state + inc) & MASK64


def indices(words, m):
    cut = (1 << 32) % m
    for word in words:
        if word >= cut:
            yield word % m


def doubled_median(values):
    a = sorted(values)
    return a[(len(a) - 1) // 2] + a[len(a) // 2]


def samples(blocks, draws):
    out = []
    for _ in range(10000):
        selected = [blocks[next(draws)] for _ in blocks]
        out.append(doubled_median(x for b in selected for x in b))
    return out


def bound(vals, p=95, q=100):
    rank = ((q - p) * len(vals) + q - 1) // q
    return rank, sorted(vals)[rank - 1], sorted(vals)[rank - 1] // 2


def take(items, n):
    return [next(items) for _ in range(n)]


if __name__ == "__main__":
    assert take(pcg(42, 54), 6) == [
        0xA15C02B7, 0x7B47F409, 0xBA1D3330, 0x83D2F293, 0xBFA4784B, 0xCBED606E]
    words = take(pcg(0, 1), 8)
    print("default first u32:", words)
    ids = list(indices(words, 2))
    print("default first m=2 pairs:", list(zip(ids[::2], ids[1::2])))
    assert list(indices([0, 1, 2, 3, 0xffffffff], 3)) == [1, 2, 0, 0]
    tiny = [[1, 2], [9]]
    assert [doubled_median(tiny[i] + tiny[j]) for i, j in product(range(2), repeat=2)] == [3, 4, 4, 18]
    vals = samples(tiny, indices(pcg(0, 1), 2))
    print("toy first t:", vals[:4])
    print("toy counts(t):", dict(sorted(Counter(vals).items())))
    print("toy rank,t,A(ppb):", bound(vals))
    assert bound(vals) == (500, 3, 1)

    blocks = [[1, 2, 3]] * 6 + [[9, 10, 11]] * 6
    real_shape = samples(blocks, indices(pcg(0, 1), 12))
    print("12-block first indices:", take(indices(pcg(0, 1), 12), 12))
    print("12-block counts(t):", dict(sorted(Counter(real_shape).items())))
    print("12-block rank,t,A(ppb):", bound(real_shape))
    assert bound(real_shape) == (500, 5, 2)
    # Independent order-count identity for this fixture. For k low blocks, each
    # low value occurs k times and each high value (12-k) times, without sorting.
    by_k = [20, 20, 20, 19, 18, 18, 12, 6, 6, 5, 4, 4, 4]
    draw = indices(pcg(0, 1), 12)
    assert real_shape == [by_k[sum(next(draw) < 6 for _ in range(12))]
                          for _ in range(10000)]
    offsets = [1, 0, 3]
    per_window = [bound([t + 2 * shift for t in real_shape])[2] for shift in offsets]
    print("three windows:", per_window)
    c, theta = 1, 3  # Synthetic regression fixture only.
    assert per_window == [3, 2, 5]
    assert not all(Fraction(a, c) >= theta for a in per_window)
    assert Fraction(sum(per_window), len(per_window) * c) >= theta
    x, y = [1, 1, 100], [0, 8, 8]
    assert Fraction(sum(x), 3) > Fraction(doubled_median(x), 2)
    assert Fraction(sum(y), 3) < Fraction(doubled_median(y), 2)
    print("PASS: exact arithmetic and replay fixtures")
