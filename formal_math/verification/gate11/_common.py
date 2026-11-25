"""gate11 两个脚本共用：定位仓库根、读语料、读准入表、算语料指纹。只用标准库。"""
import hashlib, json, os, re
from pathlib import Path

ADMIT_REL = Path("formal_math/sources/admit")
TABLE_REL = Path("candidate/tier1_candidate.jsonl")
BLOG_REL = Path("docs/chanlun/text/blog")
# 语料指纹基线：进入语料目录后 `sha256sum *.md | sha256sum` 的值（#2317 票面）。
CORPUS_BASELINE = "b6a35574ed6db3625da6d18f4e11c8976874ba66b0e888362e1769483f0c0a0d"
EXPECTED_ROWS = 790
ROW_KEYS = ("id", "lesson", "line", "quote_spans", "author_spans", "verdict", "passes_agree",
            "adjudicated", "pass_a", "pass_b", "author_text_sha256")


def default_root():
    # 脚本在 <根>/formal_math/verification/gate11/ 下
    return Path(__file__).resolve().parents[3]


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def corpus_fingerprint(blog_dir):
    """等价于在语料目录里跑 `sha256sum *.md | sha256sum`（文件名按字节序）。"""
    names = sorted(f for f in os.listdir(blog_dir) if f.endswith(".md"))
    out = []
    for n in names:
        if "\\" in n or "\n" in n:
            raise ValueError("语料文件名含反斜杠或换行，指纹算法不覆盖: %r" % n)
        out.append(sha256_bytes((Path(blog_dir) / n).read_bytes()) + "  " + n + "\n")
    return sha256_bytes("".join(out).encode("utf-8")), len(names)


class Corpus:
    """按「课号:行号」取原行。取文规则与 merge.py 所用 lib.load 相同：按 '\\n' 切分，行号从 1 起。"""

    def __init__(self, blog_dir):
        self.dir = Path(blog_dir)
        self.names = sorted(f for f in os.listdir(self.dir) if re.match(r"^\d{3}-", f))
        self._cache = {}

    def lines(self, lesson):
        if lesson not in self._cache:
            fn = [f for f in self.names if f.startswith(lesson + "-")]
            if len(fn) != 1:
                raise KeyError("课号 %s 在语料里匹配到 %d 个文件" % (lesson, len(fn)))
            self._cache[lesson] = (self.dir / fn[0]).read_text(encoding="utf-8").split("\n")
        return self._cache[lesson]

    def line(self, lesson, line_no):
        ls = self.lines(lesson)
        if not 1 <= line_no <= len(ls):
            raise IndexError("%s:%d 超出该课行数 %d" % (lesson, line_no, len(ls)))
        return ls[line_no - 1]


def load_table(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, l in enumerate(f, 1):
            if l.strip():
                rows.append(json.loads(l))
    return rows


def runs_of(spans):
    """区间列表 -> 字符集合的极大连续段（相邻或重叠的并为一段）。"""
    cs = sorted({i for a, b in spans for i in range(a, b)})
    out = []
    for i in cs:
        if out and out[-1][1] == i:
            out[-1][1] = i + 1
        else:
            out.append([i, i + 1])
    return [tuple(x) for x in out]
