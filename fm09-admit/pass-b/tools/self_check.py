#!/usr/bin/env python3
"""fm09-admit/SPEC.md 全部自检项验证脚本。

用法（在仓库根目录）：
  python3 fm09-admit/pass-b/tools/self_check.py fm09-admit/pass-b/tier1.jsonl
"""
import hashlib
import json
import os
import sys

EXPECTED_KEYS = [
    "id",
    "lesson",
    "line",
    "quote_spans",
    "author_spans",
    "verdict",
    "nonauthor_kind",
    "reason",
    "author_text_sha256",
]
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


def check_spans(spans, max_len, label, rid, errs):
    if not isinstance(spans, list):
        errs.append(f"id={rid}: {label} is not a list")
        return False
    prev_end = -1
    for sp in spans:
        if (
            not isinstance(sp, list)
            or len(sp) != 2
            or type(sp[0]) is not int
            or type(sp[1]) is not int
        ):
            errs.append(f"id={rid}: {label} invalid span element {sp!r}")
            return False
        a, b = sp
        if not (0 <= a < b <= max_len):
            errs.append(f"id={rid}: {label} span [{a},{b}) out of bounds [0,{max_len})")
            return False
        if a < prev_end:
            errs.append(f"id={rid}: {label} spans not disjoint/increasing at [{a},{b}) after {prev_end}")
            return False
        prev_end = b
    return True


def span_covered_by(sp, containers):
    a, b = sp
    for ca, cb in containers:
        if ca <= a and b <= cb:
            return True
    return False


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: self_check.py <path/to/tier1.jsonl>")
    target = sys.argv[1]
    repo_root = get_repo_root()
    lib = load_lib(repo_root)
    ledger_path = os.path.join(repo_root, "fm09-register", "tmp", "ledger_final.jsonl")

    expected = []
    with open(ledger_path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("who") == "正文":
                expected.append(rec)

    errs = []
    if len(expected) != 790:
        errs.append(f"Ledger body count is {len(expected)}, expected 790")

    raw_lines = open(target, encoding="utf-8").read().splitlines()
    if len(raw_lines) != 790:
        errs.append(f"Output has {len(raw_lines)} lines, expected 790")

    records = []
    for idx, raw in enumerate(raw_lines, start=1):
        try:
            obj = json.loads(raw)
        except Exception as e:
            errs.append(f"Line {idx}: invalid JSON: {e}")
            continue
        if list(obj.keys()) != EXPECTED_KEYS:
            errs.append(f"Line {idx} (id={obj.get('id')}): keys {list(obj.keys())} != {EXPECTED_KEYS}")
        records.append(obj)

    if len(records) == len(expected):
        got_ids = [r["id"] for r in records]
        exp_ids = [e["id"] for e in expected]
        if got_ids != exp_ids:
            errs.append("ID sequence does not match ledger who=='正文' order/set")

    counts = {"clean": 0, "trimmed": 0, "reject": 0}
    by_id = {}

    for rec, exp in zip(records, expected):
        rid = rec["id"]
        by_id[rid] = rec
        exp_les, exp_ln_s = exp["cite"].split(":")
        exp_ln = int(exp_ln_s)

        if rec["lesson"] != exp_les or rec["line"] != exp_ln:
            errs.append(f"id={rid}: lesson/line {rec['lesson']}:{rec['line']} != {exp['cite']}")
            continue

        lines, _mark, _fn = lib.load(exp_les)
        orig = lines[exp_ln - 1]
        max_len = len(orig)

        qspans = rec["quote_spans"]
        aspans = rec["author_spans"]
        verdict = rec["verdict"]
        kind = rec["nonauthor_kind"]
        reason = rec["reason"]
        sha = rec["author_text_sha256"]

        q_ok = check_spans(qspans, max_len, "quote_spans", rid, errs)
        a_ok = check_spans(aspans, max_len, "author_spans", rid, errs)

        if q_ok and qspans:
            q_reconstructed = "".join(orig[a:b] for a, b in qspans)
            if len(qspans) == 1 and q_reconstructed != exp["quote"]:
                errs.append(f"id={rid}: quote_spans text does not match ledger quote")

        if q_ok and a_ok:
            for sp in aspans:
                if not span_covered_by(sp, qspans):
                    errs.append(f"id={rid}: author_span {sp} not contained in any quote_span {qspans}")

        if verdict not in VALID_VERDICTS:
            errs.append(f"id={rid}: invalid verdict {verdict!r}")
        else:
            counts[verdict] += 1

        if kind not in VALID_KINDS:
            errs.append(f"id={rid}: invalid nonauthor_kind {kind!r}")

        if not isinstance(reason, str) or not reason.strip():
            errs.append(f"id={rid}: empty reason")

        q_len = sum(b - a for a, b in qspans) if q_ok else 0
        a_len = sum(b - a for a, b in aspans) if a_ok else 0

        if verdict == "clean":
            if aspans != qspans or not qspans:
                errs.append(f"id={rid}: clean must have author_spans == quote_spans (non-empty)")
            if kind != "none":
                errs.append(f"id={rid}: clean must have nonauthor_kind == 'none', got {kind!r}")
        elif verdict == "reject":
            if aspans != []:
                errs.append(f"id={rid}: reject must have empty author_spans")
            if kind == "none":
                errs.append(f"id={rid}: reject must not have nonauthor_kind == 'none'")
            if reason.strip() == "干净":
                errs.append(f"id={rid}: reject reason cannot be '干净'")
        elif verdict == "trimmed":
            if not aspans:
                errs.append(f"id={rid}: trimmed must have non-empty author_spans")
            if not (0 < a_len < q_len):
                errs.append(f"id={rid}: trimmed author_spans length {a_len} not strictly less than quote_spans {q_len}")
            if kind == "none":
                errs.append(f"id={rid}: trimmed must not have nonauthor_kind == 'none'")
            if reason.strip() == "干净":
                errs.append(f"id={rid}: trimmed reason cannot be '干净'")

        if a_ok:
            if not aspans:
                exp_sha = ""
            else:
                author_text = "".join(orig[a:b] for a, b in aspans)
                exp_sha = hashlib.sha256(author_text.encode("utf-8")).hexdigest()
            if sha != exp_sha:
                errs.append(f"id={rid}: author_text_sha256 mismatch ({sha} != {exp_sha})")

    # 已知实例检查
    r1259 = by_id.get(1259)
    if r1259 is None:
        errs.append("Missing known example id=1259")
    else:
        if r1259["verdict"] == "clean":
            errs.append("Known example id=1259 (081:42) must NOT be clean")
        lines_081, _, _ = lib.load("081")
        orig_081 = lines_081[42 - 1]
        a1259 = "".join(orig_081[a:b] for a, b in r1259["author_spans"])
        if "后文改称自同构性结构" in a1259:
            errs.append("Known example id=1259 still includes editor note in author_spans")

    r265 = by_id.get(265)
    if r265 is None:
        errs.append("Missing known example id=265")
    else:
        if r265["verdict"] != "clean":
            errs.append(f"Known example id=265 (020:56) must be clean, got {r265['verdict']}")

    if errs:
        print(f"SELF-CHECK FAILED with {len(errs)} error(s):")
        for e in errs[:50]:
            print("  -", e)
        sys.exit(1)

    print(
        f"SELF-CHECK PASSED: {len(records)} rows "
        f"(clean={counts['clean']}, trimmed={counts['trimmed']}, reject={counts['reject']})"
    )


if __name__ == "__main__":
    main()
