#!/usr/bin/env python3
"""复核辅助脚本：列举 tier1.jsonl 中全部非 clean 条目及含括号/引号/关键词/边界位置的 clean 条目，供人工二次抽查。

用法（在仓库根目录）：
  python3 fm09-admit/pass-b/tools/audit_review.py fm09-admit/pass-b/tier1.jsonl
"""
import argparse
import json
import os
import re
import sys

PAREN_RE = re.compile(r"[()（）\[\]【】]")
QUOTE_RE = re.compile(r"[“”\"‘’「」『』《》]")
KW_RE = re.compile(
    r"(缠中说禅|缠师|禅师|缠主|娇|注[:：]|编者|网友|下图|上图|配图|后文|前文|解盘|回复|问题|匿名|问[:：]|答[:：]|云[:：]|曰[:：]|所说|说过|引用|原话)"
)


def get_repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


def load_lib(repo_root):
    tmp_dir = os.path.join(repo_root, "fm09-register", "tmp")
    blog_dir = os.path.join(repo_root, "docs", "chanlun", "text", "blog")
    sys.path.insert(0, tmp_dir)
    import lib
    lib.BLOG = blog_dir
    lib._cache.clear()
    return lib


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tier1", help="tier1.jsonl 路径")
    parser.add_argument("--out", help="可选：写入详细报告的文件路径")
    args = parser.parse_args()

    repo_root = get_repo_root()
    lib = load_lib(repo_root)
    rows = [json.loads(line) for line in open(args.tier1, encoding="utf-8")]

    non_clean = []
    flagged_parens = []
    flagged_quotes = []
    flagged_kw = []
    flagged_pos = []

    for r in rows:
        lines, mark, _ = lib.load(r["lesson"])
        orig = lines[r["line"] - 1]
        q = "".join(orig[a:b] for a, b in r["quote_spans"])
        at = "".join(orig[a:b] for a, b in r["author_spans"])

        if r["verdict"] != "clean":
            non_clean.append((r, q, at))
            continue

        if PAREN_RE.search(q):
            flagged_parens.append((r, q))
        if QUOTE_RE.search(q):
            flagged_quotes.append((r, q))
        if KW_RE.search(q):
            flagged_kw.append((r, q))
        if (
            r["line"] <= 15
            or mark is None
            or (mark is not None and mark - r["line"] <= 2)
            or q.lstrip().startswith(("#", ">", "!", "-", "=", "(", "（", "，", "。", "；"))
        ):
            flagged_pos.append((r, q, mark))

    summary = (
        f"total={len(rows)}, non_clean={len(non_clean)}, "
        f"clean_parens={len(flagged_parens)}, clean_quotes={len(flagged_quotes)}, "
        f"clean_kw={len(flagged_kw)}, clean_edge_pos={len(flagged_pos)}"
    )
    print(summary)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as wf:
            wf.write(summary + "\n\n=== NON-CLEAN ===\n")
            for r, q, at in non_clean:
                wf.write(
                    f"id={r['id']} {r['lesson']}:{r['line']} [{r['verdict']}/{r['nonauthor_kind']}]\n"
                    f"  quote_spans={r['quote_spans']} author_spans={r['author_spans']}\n"
                    f"  QUOTE : {q!r}\n"
                    f"  AUTHOR: {at!r}\n"
                    f"  REASON: {r['reason']}\n\n"
                )
            wf.write("\n=== CLEAN WITH PARENS ===\n")
            for r, q in flagged_parens:
                wf.write(f"id={r['id']} {r['lesson']}:{r['line']} | {q}\n")
            wf.write("\n=== CLEAN WITH QUOTES ===\n")
            for r, q in flagged_quotes:
                wf.write(f"id={r['id']} {r['lesson']}:{r['line']} | {q}\n")
            wf.write("\n=== CLEAN WITH KEYWORDS ===\n")
            for r, q in flagged_kw:
                wf.write(f"id={r['id']} {r['lesson']}:{r['line']} | {q}\n")
            wf.write("\n=== CLEAN EDGE POS ===\n")
            for r, q, mark in flagged_pos:
                wf.write(f"id={r['id']} {r['lesson']}:{r['line']} (mark={mark}) | {q}\n")


if __name__ == "__main__":
    main()
