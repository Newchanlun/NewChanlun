#!/usr/bin/env python3
"""由 errata_src.ROWS 生成 ../errata.jsonl：按顺序分配 eid，键序固定。

用法：python3 -I fm09-admit/errata/tools/build_errata.py
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import errata_src  # noqa: E402

KEYS = ["eid", "labels", "kind", "claim", "finding", "cites", "locator",
        "history", "status", "closed_at", "residual", "evidence"]


def main():
    out = HERE.parent / "errata.jsonl"
    lines = []
    for i, row in enumerate(errata_src.ROWS, 1):
        rec = {"eid": f"E{i:03d}"}
        for k in KEYS[1:]:
            rec[k] = row[k]
        extra = set(row) - set(KEYS)
        if extra:
            raise SystemExit(f"E{i:03d} 多余键 {sorted(extra)}")
        lines.append(json.dumps(rec, ensure_ascii=False))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out} rows={len(lines)}")


if __name__ == "__main__":
    main()
