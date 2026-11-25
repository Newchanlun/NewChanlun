#!/usr/bin/env python3
"""将逐条人工判定的批次 JSON 编译为规格化的 tier1.jsonl。

每个批次 JSON 格式为列表，每条形如：
- 干净条目：{"id": 1, "verdict": "clean"}（可选填 "reason" 默认 "干净"）
- 裁剪条目：{
    "id": 1259,
    "verdict": "trimmed",
    "nonauthor_kind": "editor_note",
    "reason": "...",
    "remove_substrings": ["(后文改称自同构性结构）"]
    // 或者显式提供 "author_spans": [[a, b], ...] 或 "remove_spans": [[a, b], ...]
  }
- 拒收条目：{
    "id": ...,
    "verdict": "reject",
    "nonauthor_kind": "editor_note" | "quoted_other" | "reader" | "non_body" | "not_found",
    "reason": "...",
    "uncertain": true/false (可选，仅用于生成 README 清单，不写入 tier1.jsonl)
  }

用法：
  python3 fm09-admit/pass-b/tools/apply_batch.py \
      --decisions-dir /Volumes/AgentStorage/fm/tmp/2317-pass-b/decisions \
      --out fm09-admit/pass-b/tier1.jsonl
"""
import argparse
import glob
import hashlib
import json
import os
import sys

VALID_VERDICTS = {"clean", "trimmed", "reject"}
VALID_KINDS = {"none", "editor_note", "quoted_other", "reader", "non_body", "not_found"}


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


def subtract_spans(base_spans, remove_spans):
    """从 base_spans 中减去 remove_spans，返回不相交且递增的剩余区间列表。"""
    rem = sorted(remove_spans)
    # 合并重叠的删除区间
    merged_rem = []
    for a, b in rem:
        if a >= b:
            raise ValueError(f"Empty/invalid remove span [{a}, {b})")
        if merged_rem and a <= merged_rem[-1][1]:
            merged_rem[-1] = [merged_rem[-1][0], max(merged_rem[-1][1], b)]
        else:
            merged_rem.append([a, b])

    result = []
    for bs, be in base_spans:
        cur = bs
        for rs, re_ in merged_rem:
            if re_ <= cur:
                continue
            if rs >= be:
                break
            if rs > cur:
                result.append([cur, rs])
            cur = max(cur, re_)
        if cur < be:
            result.append([cur, be])
    return result


def build_record(ledger_rec, decision, lib):
    rid = ledger_rec["id"]
    les, ln_s = ledger_rec["cite"].split(":")
    ln = int(ln_s)
    lines, _mark, _fn = lib.load(les)
    orig = lines[ln - 1]
    quote = ledger_rec["quote"]

    pos = orig.find(quote)
    if pos < 0:
        quote_spans = []
    else:
        if orig.count(quote) != 1:
            raise ValueError(f"id={rid}: quote appears multiple times on {les}:{ln}")
        quote_spans = [[pos, pos + len(quote)]]

    verdict = decision["verdict"]
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"id={rid}: invalid verdict {verdict}")

    if verdict == "clean":
        if not quote_spans:
            raise ValueError(f"id={rid}: clean verdict with empty quote_spans")
        author_spans = [list(sp) for sp in quote_spans]
        nonauthor_kind = "none"
        reason = decision.get("reason", "干净")
    elif verdict == "reject":
        author_spans = []
        nonauthor_kind = decision["nonauthor_kind"]
        if nonauthor_kind not in VALID_KINDS or nonauthor_kind == "none":
            raise ValueError(f"id={rid}: invalid nonauthor_kind for reject: {nonauthor_kind}")
        reason = decision["reason"].strip()
        if not reason or reason == "干净":
            raise ValueError(f"id={rid}: reject requires explicit reason")
    else:  # trimmed
        if not quote_spans:
            raise ValueError(f"id={rid}: trimmed verdict with empty quote_spans")
        nonauthor_kind = decision["nonauthor_kind"]
        if nonauthor_kind not in VALID_KINDS or nonauthor_kind == "none":
            raise ValueError(f"id={rid}: invalid nonauthor_kind for trimmed: {nonauthor_kind}")
        reason = decision["reason"].strip()
        if not reason or reason == "干净":
            raise ValueError(f"id={rid}: trimmed requires explicit reason")

        if "author_spans" in decision:
            author_spans = [list(sp) for sp in decision["author_spans"]]
        elif "remove_spans" in decision:
            author_spans = subtract_spans(quote_spans, decision["remove_spans"])
        elif "remove_substrings" in decision:
            qs, qe = quote_spans[0]
            qtext = orig[qs:qe]
            rem_spans = []
            for sub in decision["remove_substrings"]:
                cnt = qtext.count(sub)
                if cnt != 1:
                    raise ValueError(
                        f"id={rid}: remove_substring matched {cnt} times in quote: {sub!r}"
                    )
                idx = qtext.find(sub)
                rem_spans.append([qs + idx, qs + idx + len(sub)])
            author_spans = subtract_spans(quote_spans, rem_spans)
        else:
            raise ValueError(f"id={rid}: trimmed must provide author_spans/remove_spans/remove_substrings")

        if not author_spans:
            raise ValueError(f"id={rid}: trimmed resulted in empty author_spans")
        if author_spans == quote_spans:
            raise ValueError(f"id={rid}: trimmed resulted in author_spans == quote_spans")

    if not author_spans:
        sha = ""
    else:
        author_text = "".join(orig[a:b] for a, b in author_spans)
        sha = hashlib.sha256(author_text.encode("utf-8")).hexdigest()

    # 严格按 SPEC.md 键序构造
    return {
        "id": rid,
        "lesson": les,
        "line": ln,
        "quote_spans": quote_spans,
        "author_spans": author_spans,
        "verdict": verdict,
        "nonauthor_kind": nonauthor_kind,
        "reason": reason,
        "author_text_sha256": sha,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--decisions-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    repo_root = get_repo_root()
    lib = load_lib(repo_root)
    ledger_path = os.path.join(repo_root, "fm09-register", "tmp", "ledger_final.jsonl")

    ledger_rows = []
    with open(ledger_path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("who") == "正文":
                ledger_rows.append(rec)

    decisions_by_id = {}
    dec_files = sorted(glob.glob(os.path.join(args.decisions_dir, "batch_*.json")))
    for fp in dec_files:
        with open(fp, encoding="utf-8") as f:
            items = json.load(f)
        for item in items:
            rid = item["id"]
            if rid in decisions_by_id:
                raise ValueError(f"Duplicate decision for id={rid} in {fp}")
            decisions_by_id[rid] = item

    out_records = []
    counts = {"clean": 0, "trimmed": 0, "reject": 0}
    uncertain_ids = []

    for rec in ledger_rows:
        rid = rec["id"]
        if rid not in decisions_by_id:
            if args.allow_partial:
                break
            raise ValueError(f"Missing decision for id={rid}")
        dec = decisions_by_id[rid]
        built = build_record(rec, dec, lib)
        out_records.append(built)
        counts[built["verdict"]] += 1
        if dec.get("uncertain"):
            uncertain_ids.append((rid, rec["cite"], built["verdict"], built["reason"]))

    # 如果不是 partial，确认没有多余未消费的 decision
    if not args.allow_partial and len(out_records) != len(ledger_rows):
        raise ValueError(f"Count mismatch: {len(out_records)} != {len(ledger_rows)}")
    extra = set(decisions_by_id.keys()) - {r["id"] for r in ledger_rows}
    if extra:
        raise ValueError(f"Unexpected decision ids not in body ledger: {sorted(extra)}")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as wf:
        for r in out_records:
            wf.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(
        f"Wrote {len(out_records)}/{len(ledger_rows)} rows to {args.out}: "
        f"clean={counts['clean']}, trimmed={counts['trimmed']}, reject={counts['reject']}, "
        f"uncertain={len(uncertain_ids)}"
    )
    if uncertain_ids:
        print("Uncertain entries:")
        for u in uncertain_ids:
            print(f"  id={u[0]} ({u[1]}) [{u[2]}]: {u[3]}")


if __name__ == "__main__":
    main()
