#!/usr/bin/env python3
"""门禁 11 阻断检查：正文区准入表的完整性与语料指纹（#2317）。

退出码：0 全部通过；1 有不符（逐项打到标准错误，写明哪一条）；2 工具自身无法运行。
用法：python3 -I formal_math/verification/gate11/check_admit_table.py [--root <仓库根>]
"""
import argparse, importlib.util, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("gate11_common", Path(__file__).resolve().parent / "_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

FAILS = []


def fail(check, msg):
    FAILS.append((check, msg))
    print("GATE11 RED [%s] %s" % (check, msg), file=sys.stderr)


PIN_FILE = Path(__file__).resolve().parent / "pinned_admit.sha256"
# 清单与指纹是入库时新增的两个文件，不在冻结原件之列
UNPINNED_OK = {"SHA256SUMS", "CORPUS_FINGERPRINT"}


def read_pins():
    pins = {}
    for l in PIN_FILE.read_text(encoding="utf-8").splitlines():
        if l.strip() and not l.startswith("#"):
            h, rel = l.split("  ", 1)
            pins[rel] = h
    return pins


def check_pins(admit):
    """身份：入库文件须逐个等于门禁侧钉选的冻结摘要（过审的那一份），不是「任一套自洽的」。
    钉选清单与被钉文件若在同一次改动里一起换，本检查拦不住，那由路径权限（门 6b）与评审负责。"""
    try:
        pins = read_pins()
    except (OSError, ValueError) as e:
        fail("钉选", "无法读取钉选清单 %s: %s" % (PIN_FILE.name, e))
        return
    for rel, want in sorted(pins.items()):
        p = admit / rel
        if not p.is_file():
            fail("钉选", "冻结原件缺失: %s" % rel)
        elif C.sha256_bytes(p.read_bytes()) != want:
            fail("钉选", "%s 不是过审的那一份（钉选 %s…）" % (rel, want[:12]))
    on_disk = set()
    for dp, dn, fn in os.walk(admit):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if not f.endswith(".pyc"):
                on_disk.add(os.path.relpath(os.path.join(dp, f), admit).replace(os.sep, "/"))
    for rel in sorted(on_disk - set(pins) - UNPINNED_OK):
        fail("钉选", "目录里有钉选清单之外的文件: %s" % rel)
    sums = admit / "SHA256SUMS"
    if sums.is_file():
        listed = {}
        for l in sums.read_text(encoding="utf-8").splitlines():
            if "  " in l:
                h, r = l.split("  ", 1)
                listed[r[2:] if r.startswith("./") else r] = h
        for rel, want in sorted(pins.items()):
            if listed.get(rel) != want:
                fail("钉选", "SHA256SUMS 里 %s 的摘要与钉选清单不一致（SHA256SUMS 只是人查的副本）" % rel)


def check_sums(admit):
    """摘要清单复算：清单里每个文件现算相符，目录里没有清单之外的文件。"""
    sums = admit / "SHA256SUMS"
    if not sums.is_file():
        fail("摘要清单", "缺 SHA256SUMS")
        return
    listed = {}
    for n, l in enumerate(sums.read_text(encoding="utf-8").splitlines(), 1):
        if not l.strip():
            continue
        parts = l.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            fail("摘要清单", "SHA256SUMS 第 %d 行格式不对: %r" % (n, l))
            continue
        rel = parts[1][2:] if parts[1].startswith("./") else parts[1]
        if rel.startswith("/") or ".." in Path(rel).parts or rel in listed:
            fail("摘要清单", "SHA256SUMS 第 %d 行路径不合法或重复: %r" % (n, rel))
            continue
        listed[rel] = parts[0]
    for rel, want in sorted(listed.items()):
        p = admit / rel
        if not p.is_file():
            fail("摘要清单", "清单里的文件不存在: %s" % rel)
        elif C.sha256_bytes(p.read_bytes()) != want:
            fail("摘要清单", "摘要不符: %s（清单 %s…）" % (rel, want[:12]))
    on_disk = set()
    for dp, dn, fn in os.walk(admit):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if f.endswith(".pyc"):
                continue
            rel = os.path.relpath(os.path.join(dp, f), admit).replace(os.sep, "/")
            if rel != "SHA256SUMS":
                on_disk.add(rel)
    for rel in sorted(on_disk - set(listed)):
        fail("摘要清单", "目录里有清单之外的文件: %s" % rel)


def check_fingerprint(admit, blog):
    fp, n = C.corpus_fingerprint(blog)
    if fp != C.CORPUS_BASELINE:
        fail("语料指纹", "现算 %s（%d 个 .md）≠ 基线 %s" % (fp, n, C.CORPUS_BASELINE))
    f = admit / "CORPUS_FINGERPRINT"
    stored = f.read_text(encoding="utf-8").split()[:1] if f.is_file() else []
    if stored != [C.CORPUS_BASELINE]:
        fail("语料指纹", "入库的 CORPUS_FINGERPRINT 首项 %s ≠ 基线" % (stored or "缺文件"))


def check_rows(table_path, blog, rows):
    """行数与逐行自洽：区间合法、判定与区间一致、author_text_sha256 现算相符。"""
    if len(rows) != C.EXPECTED_ROWS:
        fail("行数", "准入表 %d 行，应为 %d" % (len(rows), C.EXPECTED_ROWS))
    corpus = C.Corpus(blog)
    seen = set()
    for r in rows:
        i = r.get("id")
        if tuple(r.keys()) != C.ROW_KEYS:
            fail("行结构", "id %s 的键不是约定的 %s" % (i, list(C.ROW_KEYS)))
            continue
        if i in seen:
            fail("行结构", "id %s 重复" % i)
        seen.add(i)
        try:
            text = corpus.line(r["lesson"], r["line"])
        except (KeyError, IndexError) as e:
            fail("原行", "id %s %s:%s 取不到原行: %s" % (i, r["lesson"], r["line"], e))
            continue
        q, a = r["quote_spans"], r["author_spans"]
        ok = True
        for name, sp in (("quote_spans", q), ("author_spans", a)):
            prev = 0
            for x, y in sp:
                if not (0 <= x < y <= len(text)) or x < prev:
                    fail("区间", "id %s %s:%s 的 %s %s 越界、反向或不递增（行长 %d）"
                         % (i, r["lesson"], r["line"], name, [x, y], len(text)))
                    ok = False
                prev = y
        if not ok:
            continue
        qc = {k for x, y in q for k in range(x, y)}
        ac = {k for x, y in a for k in range(x, y)}
        if not ac <= qc:
            fail("区间", "id %s %s:%s 的 author_spans 不全在 quote_spans 之内" % (i, r["lesson"], r["line"]))
        v = r["verdict"]
        if v == "clean" and ac != qc or v == "reject" and a or v == "trimmed" and not (a and ac < qc) \
                or v not in ("clean", "trimmed", "reject"):
            fail("判定", "id %s %s:%s 的 verdict=%s 与区间不一致" % (i, r["lesson"], r["line"], v))
        want = C.sha256_bytes("".join(text[x:y] for x, y in a).encode("utf-8")) if a else ""
        if r["author_text_sha256"] != want:
            fail("作者文字摘要", "id %s %s:%s 的 author_text_sha256 与按 author_spans 从语料取字复算不符"
                 % (i, r["lesson"], r["line"]))


def rebuild(admit, blog, table_path):
    """在临时目录里搭 merge.py 要的目录布局，用入库的合并脚本从两遍原件重建，与入库准入表逐行比对。"""
    here = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="gate11-rebuild-") as tmp:
        t = Path(tmp)
        for rel in ("pass-a/tier1.jsonl", "pass-b/tier1.jsonl", "candidate/adjudications.json", "candidate/merge.py"):
            dst = t / "fm09-admit" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(admit / rel, dst)
        shutil.copytree(blog, t / "docs/chanlun/text/blog")
        (t / "fm09-register/tmp").mkdir(parents=True)
        shutil.copyfile(here / "merge_shim/lib.py", t / "fm09-register/tmp/lib.py")
        # 台账不入库；merge.py 只用它取「who == 正文」的 id 序，这里取甲遍原件的 id 序代替。
        with open(admit / "pass-a/tier1.jsonl", encoding="utf-8") as f, \
                open(t / "fm09-register/tmp/ledger_final.jsonl", "w", encoding="utf-8") as g:
            for l in f:
                if l.strip():
                    g.write(json.dumps({"id": json.loads(l)["id"], "who": "正文"}, ensure_ascii=False) + "\n")
        p = subprocess.run([sys.executable, "-I", str(t / "fm09-admit/candidate/merge.py")],
                           cwd=tmp, capture_output=True, text=True, encoding="utf-8")
        if p.returncode != 0:
            fail("重建", "merge.py 退出 %d: %s" % (p.returncode, (p.stderr or p.stdout).strip()[-600:]))
            return
        built = (t / "fm09-admit/candidate/tier1_candidate.jsonl").read_bytes()
    stored = table_path.read_bytes()
    if built == stored:
        return
    bl, sl = built.decode("utf-8").splitlines(), stored.decode("utf-8").splitlines()
    n = 0
    for k in range(max(len(bl), len(sl))):
        b = bl[k] if k < len(bl) else None
        s = sl[k] if k < len(sl) else None
        if b != s:
            n += 1
            if n <= 5:
                rid = (json.loads(s) if s else json.loads(b)).get("id")
                fail("重建差分", "第 %d 行（id %s）与重建结果不同" % (k + 1, rid))
    fail("重建差分", "重建 %d 行，入库 %d 行，共 %d 行不同（最多列 5 行）" % (len(bl), len(sl), n))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=None, help="仓库根；缺省按脚本位置推出")
    a = ap.parse_args()
    root = Path(a.root).resolve() if a.root else C.default_root()
    admit, blog = root / C.ADMIT_REL, root / C.BLOG_REL
    table = admit / C.TABLE_REL
    for p in (admit, blog, table):
        if not p.exists():
            print("无法运行：缺 %s（%s）" % (p.relative_to(root), "目录" if p.is_dir() or p in (admit, blog) else "文件"), file=sys.stderr)
            return 2
    try:
        rows = C.load_table(table)
    except (ValueError, OSError) as e:
        fail("准入表", "无法解析 %s: %s" % (C.TABLE_REL, e))
        rows = None
    check_pins(admit)
    check_sums(admit)
    check_fingerprint(admit, blog)
    if rows is not None:
        check_rows(table, blog, rows)
        rebuild(admit, blog, table)
    if FAILS:
        print("GATE11 阻断检查 RED：%d 项不符" % len(FAILS), file=sys.stderr)
        return 1
    print("GATE11 阻断检查 GREEN：摘要清单、%d 行、重建零差分、作者文字摘要、语料指纹均相符" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
