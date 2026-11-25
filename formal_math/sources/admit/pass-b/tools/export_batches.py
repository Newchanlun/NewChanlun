#!/usr/bin/env python3
"""导出台账中 who == '正文' 的全部 790 条记录及其原文上下文，供逐条人工审读。

只读 docs/chanlun/text/blog/ 与 fm09-register/tmp/ledger_final.jsonl；
不调用 lib.note_spans 或任何既有准入/禁引结论。
"""
import argparse
import json
import os
import re
import sys


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
    parser.add_argument(
        "--out-dir",
        default="/Volumes/AgentStorage/fm/tmp/2317-pass-b/review_batches",
        help="输出批次文本的目录",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=38000,
        help="每个批次文件的目标最大 UTF-8 字节数",
    )
    args = parser.parse_args()

    repo_root = get_repo_root()
    lib = load_lib(repo_root)
    ledger_path = os.path.join(repo_root, "fm09-register", "tmp", "ledger_final.jsonl")
    os.makedirs(args.out_dir, exist_ok=True)

    rows = []
    with open(ledger_path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("who") == "正文":
                rows.append(rec)

    assert len(rows) == 790, f"Expected 790 body rows, got {len(rows)}"

    manifest = []
    batch_idx = 1
    cur_blocks = []
    cur_ids = []
    cur_bytes = 0

    def flush():
        nonlocal batch_idx, cur_blocks, cur_ids, cur_bytes
        if not cur_blocks:
            return
        fname = f"batch_{batch_idx:02d}.txt"
        fpath = os.path.join(args.out_dir, fname)
        text = "\n".join(cur_blocks)
        with open(fpath, "w", encoding="utf-8") as wf:
            wf.write(text)
        manifest.append({
            "batch": batch_idx,
            "file": fpath,
            "count": len(cur_ids),
            "first_id": cur_ids[0],
            "last_id": cur_ids[-1],
            "ids": cur_ids[:],
            "bytes": len(text.encode("utf-8")),
        })
        batch_idx += 1
        cur_blocks = []
        cur_ids = []
        cur_bytes = 0

    for seq, rec in enumerate(rows, start=1):
        les, ln_s = rec["cite"].split(":")
        ln = int(ln_s)
        lines, mark, fn = lib.load(les)
        orig = lines[ln - 1]
        q = rec["quote"]
        pos = orig.find(q)
        end = pos + len(q) if pos >= 0 else -1

        # 保证至少读取原行前后各 4 行（满足规格 >= 3 行），且前后各至少 2 个非空行（上限 +-6 行）
        lo = ln - 1
        ne = 0
        while lo > 1 and (ln - lo < 4 or ne < 2) and (ln - lo < 6):
            lo -= 1
            if lines[lo - 1].strip():
                ne += 1
        hi = ln + 1
        ne = 0
        while hi < len(lines) and (hi - ln < 4 or ne < 2) and (hi - ln < 6):
            if lines[hi - 1].strip():
                ne += 1
            hi += 1
        lo = max(1, min(lo, ln - 4))
        hi = min(len(lines), max(hi, ln + 4))

        hints = []
        if re.search(r"[（(\[【〔]", q):
            hints.append("PAREN_IN_Q")
        elif re.search(r"[（(\[【〔]", orig):
            hints.append("PAREN_IN_LINE")
        if re.search(r"[“”\"「」『』]", q):
            hints.append("QUOTEMARK_IN_Q")
        if re.search(r"……|\.{3,}|…", q):
            hints.append("ELLIPSIS_IN_Q")
        if re.search(r"注|娇|旁观|编者|整理|缠师|禅师|缠主|禅主|博主|楼主|老师|请教|问[:：]|答[:：]|网友|同学", orig):
            hints.append("KW_IN_LINE")
        if "缠中说禅" in q:
            hints.append("CZSC_IN_Q")
        if ln <= 10:
            hints.append("NEAR_TOP")
        if mark is None:
            hints.append("NO_MARK")
        elif mark - ln <= 5:
            hints.append("NEAR_MARK")
        if re.search(r"!\[|<img|图\s*\d|附图|上图|下图|^#", orig):
            hints.append("HDR_IMG")

        block_lines = [
            f"=== #{seq:03d}/790 | id={rec['id']} | {les}:{ln} (lines={len(lines)}, mark={mark}, file={fn}) ===",
        ]
        if hints:
            block_lines.append(f"HINTS: {', '.join(hints)}")
        block_lines.append(f"QUOTE [{pos}:{end}] ({len(q)}/{len(orig)}): {q}")
        for k in range(lo, hi + 1):
            t = lines[k - 1]
            if k == ln:
                block_lines.append(f">>> L{k:03d}: {t}")
            elif t.strip():
                block_lines.append(f"    L{k:03d}: {t}")
        block_lines.append("")
        block_text = "\n".join(block_lines)
        block_bytes = len(block_text.encode("utf-8"))

        if cur_blocks and (cur_bytes + block_bytes > args.max_bytes):
            flush()
        cur_blocks.append(block_text)
        cur_ids.append(rec["id"])
        cur_bytes += block_bytes

    flush()

    manifest_path = os.path.join(args.out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as mf:
        json.dump(manifest, mf, ensure_ascii=False, indent=2)

    print(f"Exported {len(rows)} entries into {len(manifest)} batches in {args.out_dir}")
    print(f"Max batch bytes: {max(m['bytes'] for m in manifest)}, min count: {min(m['count'] for m in manifest)}, max count: {max(m['count'] for m in manifest)}")
    ell = [r["id"] for r in rows if re.search(r"……|\.{3,}|…", r["quote"])]
    print(f"Entries with ellipsis inside quote: {ell}")


if __name__ == "__main__":
    main()
