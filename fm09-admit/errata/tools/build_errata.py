#!/usr/bin/env python3
"""由 errata_src 生成 ../errata.jsonl。

errata_src.ROWS 是初版各行（eid 显式给定）；PATCH 按 eid 覆盖字段，DROP 删除移入
README「非实物事项」的行，NEW 追加新行。eid 稳定、不复用，允许有空号。
缺省值：direction=defect，ids=[]，origin_status=""，related=[]；
object 未给时按 locator 推断（护栏或脚本→tool，全为台账或明细→record，其余→doc_line）。

用法：PYTHONDONTWRITEBYTECODE=1 python3 -I fm09-admit/errata/tools/build_errata.py
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import errata_src as S  # noqa: E402

KEYS = ["eid", "labels", "kind", "object", "direction", "claim", "finding", "cites", "ids",
        "locator", "history", "status", "origin_status", "related", "closed_at", "residual",
        "evidence"]
DEFAULTS = {"direction": "defect", "ids": [], "origin_status": "", "related": [],
            "closed_at": "", "residual": "", "evidence": "", "cites": []}
TOOL = {"G", "GR", "VF", "VR"}
RECORD = {"L", "J", "Jold", "GM", "EX"}


def infer_object(locs):
    files = {loc.split(":")[1] for loc in locs}
    if files & TOOL:
        return "tool"
    if files and files <= RECORD:
        return "record"
    return "doc_line"


def main():
    rows = {r["eid"]: dict(r) for r in S.ROWS}
    for eid, patch in S.PATCH.items():
        if eid not in rows:
            raise SystemExit(f"PATCH 指向不存在的 {eid}")
        rows[eid].update(patch)
    for eid in S.DROP:
        rows.pop(eid)
    for r in S.NEW:
        if r["eid"] in rows or r["eid"] in S.DROP:
            raise SystemExit(f"NEW 复用了 {r['eid']}")
        rows[r["eid"]] = dict(r)
    for eid, (lines, st) in S.R6_HISTORY.items():
        hist = rows[eid]["history"]
        if all(x["round"] != 6 for x in hist):
            rows[eid]["history"] = hist + [S.h(6, lines, st)]
    out_lines = []
    for eid in sorted(rows):
        row = {**DEFAULTS, **rows[eid]}
        row.setdefault("object", infer_object(row["locator"]))
        extra = set(row) - set(KEYS)
        if extra:
            raise SystemExit(f"{eid} 多余键 {sorted(extra)}")
        out_lines.append(json.dumps({k: row[k] for k in KEYS}, ensure_ascii=False))
    out = HERE.parent / "errata.jsonl"
    out.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"wrote {out} rows={len(out_lines)}")


if __name__ == "__main__":
    main()
