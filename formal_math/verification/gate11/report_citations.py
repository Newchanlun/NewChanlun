#!/usr/bin/env python3
"""门禁 11 引文报告：扫 formal_math/ 下 .lean 与 .md 里的硬证据引文 `【归属 课号:行号】「…」`，
逐条核对：课行是否在准入表内；引的字是否逐字落在该课行的某一个作者连续段之内。

只报告，不阻断：退出码恒 0，除非脚本自身出错（退 2）。只认「正文归属」，不认摘句支持什么命题。
用法：python3 -I formal_math/verification/gate11/report_citations.py [--root R] [--scan DIR] [--json 文件|-]
"""
import argparse, importlib.util, json, os, re, sys
from pathlib import Path

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("gate11_common", Path(__file__).resolve().parent / "_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

# 扫描时跳过：构建产物；准入表与本门禁自己的目录（里面的引文样例是数据或自测夹具，不是被审引文）。
SKIP_DIRS = {".lake", "__pycache__"}
SKIP_REL = ("formal_math/sources/admit", "formal_math/verification/gate11")
EXTS = (".lean", ".md")
# 标记：【归属 课号:行号】；归属任意（不含括号与换行）。紧随其后（可隔空白）的「…」是被引文字。
MARKER = re.compile(r"【([^【】\n]*?)\s*(\d{3}):(\d{1,5})】")
QUOTE = re.compile(r"\s*「([^「」\n]*)」")
LOOSE = re.compile(r"【[^【】\n]*\d{3}:\d[^【】\n]*】")  # 形似课行标记，用来发现 MARKER 没吃进的
ELLIPSIS = re.compile(r"……|…|\.{3,}|。。。")


def norm(s):
    return s.replace("\xa0", " ")  # 与标注遍一致：NBSP 与空格视为同一字符，长度不变


def classify(quote, runs_by_line_text, line_text):
    """返回 (status, detail)。runs：该课行准入作者连续段 [(a,b)]。"""
    runs = runs_by_line_text
    ln = norm(line_text)
    if quote.strip():  # 先整串找：原文本身带省略号时（如 1059、1060）整串逐字就在作者区间里
        w = norm(quote)
        for p in (m.start() for m in re.finditer(re.escape(w), ln)):
            hit = next(((a, b) for (a, b) in runs if a <= p and p + len(w) <= b), None)
            if hit:
                return "ok", "全文逐字落在作者区间 %s 之内" % list(hit)
    segs = [s for s in ELLIPSIS.split(quote) if s.strip()]
    if not segs:
        return "empty_quote", "引文为空"
    where = []
    outside = []
    for s in segs:
        s = norm(s)
        pos = [m.start() for m in re.finditer(re.escape(s), ln)]
        if not pos:
            outside.append(("not_in_line", s))
            continue
        hit = next(((a, b) for p in pos for (a, b) in runs if a <= p and p + len(s) <= b), None)
        if hit:
            where.append(hit)
        else:
            outside.append(("overlaps_excluded", s))
    if not outside:
        if len(set(where)) > 1:
            # 逐段都在作者区间内，但分属不同连续段：省略号把被剔除的字跳过去了
            return "segments_in_different_runs", "各片段分属不同作者区间 %s，不许跨区间拼接" % sorted(set(where))
        return "ok", "全文逐字落在作者区间 %s 之内" % list(where[0])
    kinds = {k for k, _ in outside}
    if "overlaps_excluded" in kinds:
        return "quote_overlaps_excluded_text", "逐字在原行里，但含未准入的字（被剔除或不在任何作者区间）: %s" % outside[0][1]
    joined = norm("".join(line_text[a:b] for a, b in runs))
    if all(s in joined for _, s in outside) and len(runs) > 1:
        return "quote_spliced_across_spans", "原行里找不到，但等于把各作者区间的文字拼起来再摘: %s" % outside[0][1]
    return "quote_not_in_line", "原行里逐字找不到: %s" % outside[0][1]


def scan_files(scan_root, root):
    out = []
    for dp, dn, fn in os.walk(scan_root):
        rel_dp = os.path.relpath(dp, root).replace(os.sep, "/")
        dn[:] = sorted(d for d in dn if d not in SKIP_DIRS
                       and os.path.normpath(rel_dp + "/" + d).replace(os.sep, "/") not in SKIP_REL)
        for f in sorted(fn):
            if f.endswith(EXTS):
                out.append(Path(dp) / f)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=None, help="仓库根；缺省按脚本位置推出")
    ap.add_argument("--scan", default=None, help="扫描目录，缺省 <根>/formal_math")
    ap.add_argument("--json", default=None, help="机读 JSON 输出文件；'-' 写标准输出（此时人读摘要写标准错误）")
    a = ap.parse_args()
    root = Path(a.root).resolve() if a.root else C.default_root()
    scan = Path(a.scan).resolve() if a.scan else root / "formal_math"
    admit, blog = root / C.ADMIT_REL, root / C.BLOG_REL
    for p in (admit / C.TABLE_REL, blog, scan):
        if not p.exists():
            print("无法运行：缺 %s" % p, file=sys.stderr)
            return 2
    rows = C.load_table(admit / C.TABLE_REL)
    corpus = C.Corpus(blog)
    by_line = {}
    for r in rows:
        by_line.setdefault((r["lesson"], r["line"]), []).append(r)
    cites, unparsed = [], []
    files = scan_files(scan, root)
    for f in files:
        rel = os.path.relpath(f, root).replace(os.sep, "/")
        for ln, text in enumerate(f.read_text(encoding="utf-8", errors="replace").split("\n"), 1):
            consumed = set()
            for m in MARKER.finditer(text):
                q = QUOTE.match(text, m.end())
                if not q:
                    unparsed.append({"file": rel, "line": ln, "col": m.start() + 1, "text": m.group(0),
                                     "reason": "课行标记之后没有同行的「…」（可能跨行、改用别的括号或只是标记）"})
                    consumed.add(m.start())
                    continue
                consumed.add(m.start())
                lesson, lno = m.group(2), int(m.group(3))
                rec = {"file": rel, "line": ln, "col": m.start() + 1, "attribution": m.group(1).strip(),
                       "lesson": lesson, "lesson_line": lno, "quote": q.group(1)}
                rs = by_line.get((lesson, lno))
                if not rs:
                    rec.update(status="lesson_line_not_in_table", detail="%s:%d 不在准入表内" % (lesson, lno), row_ids=[])
                else:
                    try:
                        lt = corpus.line(lesson, lno)
                    except (KeyError, IndexError) as e:
                        rec.update(status="quote_not_in_line", detail="取不到原行: %s" % e, row_ids=[r["id"] for r in rs])
                    else:
                        runs = C.runs_of([tuple(x) for r in rs for x in r["author_spans"]])
                        st, dt = classify(q.group(1), runs, lt)
                        rec.update(status=st, detail=dt, row_ids=[r["id"] for r in rs])
                cites.append(rec)
            for m in LOOSE.finditer(text):
                if m.start() not in consumed:
                    unparsed.append({"file": rel, "line": ln, "col": m.start() + 1, "text": m.group(0),
                                     "reason": "形似课行标记但格式不合（如多行号或归属后课号不是三位）"})
    counts = {}
    for c in cites:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    report = {"table_rows": len(rows), "scanned_files": len(files), "citations": cites,
              "unparsed_markers": unparsed,
              "summary": {"total": len(cites), "ok": counts.get("ok", 0),
                          "flagged": len(cites) - counts.get("ok", 0), "by_status": counts,
                          "unparsed_markers": len(unparsed)}}
    human = sys.stderr if a.json == "-" else sys.stdout
    print("引文报告（只读报告，退出码恒 0）：扫描 %d 个文件，硬证据引文 %d 条，通过 %d，报出 %d，未能解析的标记 %d"
          % (len(files), len(cites), report["summary"]["ok"], report["summary"]["flagged"], len(unparsed)), file=human)
    for c in cites:
        if c["status"] != "ok":
            print("  [%s] %s:%d  【%s %s:%d】「%s」 — %s" % (c["status"], c["file"], c["line"], c["attribution"],
                  c["lesson"], c["lesson_line"], c["quote"][:40], c["detail"]), file=human)
    for u in unparsed:
        print("  [unparsed] %s:%d %s — %s" % (u["file"], u["line"], u["text"], u["reason"]), file=human)
    if a.json == "-":
        json.dump(report, sys.stdout, ensure_ascii=False, indent=1)
        print()
    elif a.json:
        Path(a.json).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
