#!/usr/bin/env python3
"""门禁 11 引文报告：扫 formal_math/ 下 git 跟踪的全部文本文件里的硬证据引文
`【归属 课号:行号】「…」`，逐条给读数：字面匹配状态、命中的准入表 id 与字符起止、归属词是否在封闭名单。

只报告，不阻断：成功生成报告时退出码恒 0；脚本自身跑不起来（缺准入表、缺扫描目录等）退 2，没有报告可读。
只认「正文归属」，不认摘句支持什么命题。
用法：python3 -I formal_math/verification/gate11/report_citations.py [--root R] [--scan DIR] [--json 文件|-] [--all]
"""
import argparse, importlib.util, json, os, re, subprocess, sys
from pathlib import Path

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("gate11_common", Path(__file__).resolve().parent / "_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

# 显式排除清单：路径前缀 -> 理由。被排除的文件数写进报告。
EXCLUDES = (
    ("formal_math/sources/admit/", "入库的准入材料原件：其中的 `【…】` 是标注规格与说明里的样例，不是被审引文，且须逐字节保留"),
    ("formal_math/verification/gate11/fixtures/", "引文报告自测夹具：故意含坏引文，用来检验本脚本"),
)
SKIP_WALK_DIRS = {".lake", ".git", "__pycache__"}  # 仅非 git 目录的回退遍历用
ACCEPTED_ATTR = ("缠师", "原文")  # 归属词封闭名单；其余（网友、正文、答疑、课间、解盘…）单列读数，不算通过

ANY_MARK = re.compile(r"【([^【】\n]*)】")
LOOKS_LIKE_CITE = re.compile(r"\d\s*[:：]\s*\d")
STRICT = re.compile(r"^([^\s\d:：【】]+)\s+(\d{3}):(\d+)$")  # 归属 + 必须的分隔 + 三位课号 + ASCII 冒号 + 行号
QUOTE = re.compile(r"\s*「([^「」\n]*)」")
ELLIPSIS = re.compile(r"……|…|\.{3,}|。。。")


def bad_marker_reason(inner):
    if "：" in inner:
        return "冒号是全角，只认 ASCII 冒号 ':'"
    m = re.search(r"(\d+)\s*:\s*(\d+)(.*)$", inner)
    if not m:
        return "形似课行标记但格式不合"
    pre = inner[:m.start()]
    if len(m.group(1)) != 3:
        return "课号不是三位数字（读到 %s 位：%s），不读成另一课" % (len(m.group(1)), m.group(1))
    if m.group(3).strip():
        return "课行之后还有 %r（多行号等写法不支持）" % m.group(3)
    if not pre.strip():
        return "缺归属词"
    if not pre[-1].isspace():
        return "归属词与课号之间无分隔"
    if re.search(r"\s", pre.strip()):
        return "归属词格式不合（含空白）"
    return "冒号两侧有空白或其他格式不合"


def merge_touching(spans):
    out = []
    for a, b in sorted(map(tuple, spans)):
        if out and out[-1][1] >= a:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def find_all(text, sub):
    out, i = [], text.find(sub)
    while i >= 0:
        out.append(i)
        i = text.find(sub, i + 1)
    return out


def squeeze(s):
    """去掉全部空白（含 NBSP、全角空格），返回 (去空白串, 各字符在原串的下标)。"""
    idx = [i for i, ch in enumerate(s) if not ch.isspace()]
    return "".join(s[i] for i in idx), idx


def judge(quote, lt, rows):
    """返回 (match, hits, outside_also, detail)。hits=[{id, span:[起,止)}]，只含真正单独支持这串字的 id。"""
    idspans = [(r["id"], merge_touching(r["author_spans"])) for r in rows]
    union = {i for _, sp in idspans for a, b in sp for i in range(a, b)}
    if not quote.strip():
        return "empty_quote", [], False, "引文为空"
    L = len(quote)
    occ = find_all(lt, quote)
    hits, in_some = [], set()
    for p in occ:
        for i, sp in idspans:
            if any(a <= p and p + L <= b for a, b in sp):
                hits.append({"id": i, "span": [p, p + L]})
                in_some.add(p)
    if hits:  # 整串原样、连续，落在某一个 id 的某一个作者区间内
        return "ok", hits, len(in_some) < len(occ), "整串逐字落在作者区间内"
    if occ:
        for p in occ:
            if all(k in union for k in range(p, p + L)):
                return "spans_multiple_ids", [], False, "字都在作者区间里，但没有任何单个 id 的单个区间完整包含这串（须跨 id 拼）"
        return "quote_overlaps_excluded_text", [], False, "逐字在原行里，但含未准入的字（被剔除，或不在任何作者区间）"
    # 整串原样找不到
    qs, qi = squeeze(quote)
    ls, li = squeeze(lt)
    if qs:
        for p in find_all(ls, qs):
            a, b = li[p], li[p + len(qs) - 1] + 1
            ids = [{"id": i, "span": [a, b]} for i, sp in idspans if any(x <= a and b <= y for x, y in sp)]
            if ids:
                return "whitespace_differs", ids, False, "只差空白（含 NBSP、全角空格）；供修稿，不算逐字通过"
    if ELLIPSIS.search(quote):
        segs = [s for s in ELLIPSIS.split(quote) if s != ""]
        found = []
        for i, sp in idspans:
            for a, b in sp:
                cur, first, ok = a, None, True
                for seg in segs:
                    p = lt.find(seg, cur)
                    if p < 0 or p + len(seg) > b:
                        ok = False
                        break
                    first = p if first is None else first
                    cur = p + len(seg)
                if ok and segs:
                    found.append({"id": i, "span": [first, cur]})
        if found:
            return "elided", found, False, "省略号引文：各片在同一 id 的同一作者区间内、按序且不重用位置；不算逐字通过"
        miss = [s for s in segs if s not in lt]
        return "elided_unsupported", [], False, ("有片段在原行里找不到: %s" % miss[0]) if miss else \
            "各片虽各在原行里，但不在同一 id 的同一作者区间内，或次序倒置，或重用了同一处字"
    for i, sp in idspans:
        cat = "".join(lt[a:b] for a, b in sp)
        if len(sp) > 1 and quote in cat:
            return "quote_spliced_across_spans", [], False, "原行里找不到，但等于把 id %s 的各作者区间拼起来再摘" % i
    ucat = "".join(lt[a:b] for a, b in merge_touching([(k, k + 1) for k in sorted(union)]))
    if quote in ucat:
        return "quote_spliced_across_spans", [], False, "原行里找不到，但等于把各作者区间拼起来再摘"
    return "quote_not_in_line", [], False, "原行里逐字找不到"


def list_files(root, scan):
    """git 跟踪的（外加未跟踪但未被忽略的）文件；root 不是 git 仓库根时回退为遍历。"""
    rel = os.path.relpath(scan, root).replace(os.sep, "/")
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if top.returncode == 0 and Path(top.stdout.strip()).resolve() == Path(root).resolve():
            p = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard",
                                "--", rel], capture_output=True)
            if p.returncode == 0:
                names = sorted(n for n in p.stdout.decode("utf-8", "surrogateescape").split("\0") if n)
                return "git", [n for n in names if os.path.isfile(os.path.join(root, n))]
    except OSError:
        pass
    out = []
    for dp, dn, fn in os.walk(scan):
        dn[:] = sorted(d for d in dn if d not in SKIP_WALK_DIRS)
        out += [os.path.relpath(os.path.join(dp, f), root).replace(os.sep, "/") for f in sorted(fn)]
    return "walk", sorted(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=None, help="仓库根；缺省按脚本位置推出")
    ap.add_argument("--scan", default=None, help="扫描目录，缺省 <根>/formal_math")
    ap.add_argument("--json", default=None, help="机读 JSON 输出文件；'-' 写标准输出（此时人读摘要写标准错误）")
    ap.add_argument("--all", action="store_true", help="人读输出也列出通过的条目")
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
    source, names = list_files(root, scan)
    excluded = {pre: 0 for pre, _ in EXCLUDES}
    todo = []
    for n in names:
        pre = next((p for p, _ in EXCLUDES if n.startswith(p)), None)
        if pre:
            excluded[pre] += 1
        else:
            todo.append(n)
    cites, unparsed, unscanned = [], [], []
    for rel in todo:
        data = (root / rel).read_bytes()
        if b"\0" in data:
            unscanned.append({"path": rel, "reason": "含 NUL 字节，按二进制处理"})
            continue
        try:
            body = data.decode("utf-8")
        except UnicodeDecodeError as e:
            unscanned.append({"path": rel, "reason": "非 UTF-8（%s）" % e.reason})
            continue
        for ln, text in enumerate(body.split("\n"), 1):
            for m in ANY_MARK.finditer(text):
                inner = m.group(1)
                if not LOOKS_LIKE_CITE.search(inner):
                    continue
                base = {"file": rel, "line": ln, "col": m.start() + 1}
                sm = STRICT.match(inner)
                if not sm:
                    unparsed.append(dict(base, text=m.group(0), reason=bad_marker_reason(inner)))
                    continue
                q = QUOTE.match(text, m.end())
                if not q:
                    unparsed.append(dict(base, text=m.group(0), reason="标记之后没有同行的「…」（跨行、含嵌套引号，或用了别的括号）"))
                    continue
                attr, lesson, lno = sm.group(1), sm.group(2), int(sm.group(3))
                accepted = attr in ACCEPTED_ATTR
                rec = dict(base, attribution=attr, attribution_accepted=accepted, lesson=lesson, lesson_line=lno,
                           quote=q.group(1), hits=[], outside_also=False)
                rs = by_line.get((lesson, lno))
                if not rs:
                    rec.update(match="lesson_line_not_in_table", detail="%s:%d 不在准入表内" % (lesson, lno))
                else:
                    try:
                        lt = corpus.line(lesson, lno)
                    except (KeyError, IndexError) as e:
                        rec.update(match="quote_not_in_line", detail="取不到原行: %s" % e)
                    else:
                        mt, hits, outside, dt = judge(q.group(1), lt, rs)
                        rec.update(match=mt, hits=hits, outside_also=outside, detail=dt)
                        if outside:
                            rec["detail"] += "；该行另有区间外出现"
                rec["status"] = rec["match"] if accepted or rec["match"] != "ok" else "attribution_not_accepted"
                if not accepted and rec["match"] == "ok":
                    rec["detail"] += "；归属词「%s」不在封闭名单 %s，不算通过" % (attr, list(ACCEPTED_ATTR))
                cites.append(rec)
    counts = {}
    for c in cites:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    report = {"file_source": source, "table_rows": len(rows), "scanned_files": len(todo) - len(unscanned),
              "excluded": [{"prefix": p, "reason": r, "files": excluded[p]} for p, r in EXCLUDES],
              "excluded_files": sum(excluded.values()), "unscanned": unscanned,
              "accepted_attributions": list(ACCEPTED_ATTR), "citations": cites, "unparsed_markers": unparsed,
              "summary": {"total": len(cites), "ok": counts.get("ok", 0), "by_status": counts,
                          "unparsed_markers": len(unparsed), "unscanned_files": len(unscanned)}}
    human = sys.stderr if a.json == "-" else sys.stdout
    print("引文报告（成功生成即退 0；跑不起来退 2）：文件来源 %s，扫描 %d 个，排除 %d 个，未扫描 %d 个；"
          "硬证据引文 %d 条，通过 %d，其余 %d；未能解析的标记 %d"
          % (source, report["scanned_files"], report["excluded_files"], len(unscanned), len(cites),
             counts.get("ok", 0), len(cites) - counts.get("ok", 0), len(unparsed)), file=human)
    for e in report["excluded"]:
        print("  [排除 %d 个] %s — %s" % (e["files"], e["prefix"], e["reason"]), file=human)
    for u in unscanned:
        print("  [未扫描] %s — %s" % (u["path"], u["reason"]), file=human)
    for c in cites:
        if a.all or c["status"] != "ok":
            print("  [%s] %s:%d:%d 【%s %s:%d】「%s」 hits=%s — %s" % (c["status"], c["file"], c["line"], c["col"],
                  c["attribution"], c["lesson"], c["lesson_line"], c["quote"][:40],
                  [(h["id"], h["span"]) for h in c["hits"]], c["detail"]), file=human)
    for u in unparsed:
        print("  [unparsed] %s:%d:%d %s — %s" % (u["file"], u["line"], u["col"], u["text"], u["reason"]), file=human)
    if a.json == "-":
        json.dump(report, sys.stdout, ensure_ascii=False, indent=1)
        print()
    elif a.json:
        Path(a.json).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
