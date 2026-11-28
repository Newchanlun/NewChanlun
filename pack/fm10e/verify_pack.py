#!/usr/bin/env python3
"""Verify `pack/fm10e` against #2317 admit table, docs/chanlun/text/blog/, and zero Lean signature leakage."""
import sys

if not sys.flags.isolated:
    import posix
    try:
        posix.write(2, b"verify_pack.py must run with python3 -I\n")
    except BaseException:  # noqa: BLE001
        pass
    posix._exit(2)

import glob  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402

PACK_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = sys.argv[1] if len(sys.argv) > 1 else "/Users/silencehan/Projects/NewChanlun"
BLOG = os.path.join(REPO, "docs/chanlun/text/blog")

blog_files = {}
for p in glob.glob(os.path.join(BLOG, "*.md")):
    bn = os.path.basename(p)
    if len(bn) >= 3 and bn[:3].isdigit():
        blog_files[bn[:3]] = p


def get_line(les, ln):
    with open(blog_files[les], encoding="utf-8") as f:
        return f.read().splitlines()[ln - 1]


admit_raw = subprocess.check_output(
    ["git", "-C", REPO, "show", "origin/infra/2317-admit-table:formal_math/sources/admit/candidate/tier1_candidate.jsonl"],
    text=True,
)
admit_by_id = {json.loads(l)["id"]: json.loads(l) for l in admit_raw.splitlines() if l.strip()}

with open(os.path.join(PACK_DIR, "citations.jsonl"), encoding="utf-8") as f:
    rows = [json.loads(l) for l in f if l.strip()]

t1 = t2 = 0
for r in rows:
    les, ln_s = r["cite"].split(":")
    ln = int(ln_s)
    raw = get_line(les, ln)
    if r["tier"] == 1:
        t1 += 1
        h = admit_by_id[r["admit_id"]]
        assert f"{h['lesson']}:{h['line']}" == r["cite"], f"cite mismatch id={r['admit_id']}"
        assert h["verdict"] in ("clean", "trimmed"), f"rejected verdict in tier1: {h}"
        extracted = "".join(raw[a:b] for a, b in h["author_spans"])
        assert extracted == r["text"], f"text drift id={r['admit_id']}"
        sha = hashlib.sha256(extracted.encode("utf-8")).hexdigest()
        assert sha == h["author_text_sha256"] == r["author_text_sha256"], f"sha mismatch id={r['admit_id']}"
    elif r["tier"] == 2:
        t2 += 1
        assert r["verdict"] == "secondary_only"
        sha = hashlib.sha256(r["text"].encode("utf-8")).hexdigest()
        assert sha == r["text_sha256"], f"tier2 sha mismatch {r['cite']}"
        # For non-ellipsized tier2 quotes, verify substring appears in blog line
        for part in [s.strip() for s in r["text"].split("…") if s.strip()]:
            assert part in raw, f"tier2 quote fragment not found in {r['cite']}: {part[:40]}"
    else:
        raise AssertionError(f"bad tier: {r['tier']}")

# Verify zero Lean signature/declaration leakage in pack markdown files
lean_leak_re = re.compile(
    r"(?m)^\s*(?:public\s+|private\s+|noncomputable\s+|protected\s+)*(?:def|structure|inductive|theorem|lemma|abbrev|class|instance|axiom|opaque)\s+[A-Za-z_]"
)
code_fence_lean_re = re.compile(r"```lean\b")
for md in ("01-rulings.md", "02-citations.md", "03-informal-specs.md", "04-interface-constraints.md"):
    path = os.path.join(PACK_DIR, md)
    text = open(path, encoding="utf-8").read()
    assert not lean_leak_re.search(text), f"Lean declaration leaked in {md}"
    assert not code_fence_lean_re.search(text), f"Lean code fence leaked in {md}"

print(f"PACK_FM10E_VERIFY_OK tier1={t1} tier2={t2} zero_lean_leak=true")
