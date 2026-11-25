#!/usr/bin/env python3
"""自检 ../errata.jsonl：格式、取值、版本行号与对五份报告编号的覆盖。

用法：python3 -I fm09-admit/errata/tools/check_errata.py
退出 0：全部通过；1：有格式错误或未覆盖的编号。
覆盖口径：表内 labels ∪ README「未入表的编号」代码块（```excluded）。
"""
import json
import pathlib
import re
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
REP = ROOT / "reports"
REPORTS = {
    1: REP / "r1-FM-09a-audit.md",
    2: REP / "r2-FM-09a-audit-r2.md",
    3: REP / "r3-FM-09a-audit-r3.md",
    4: REP / "r4-FM-09a-decision-review.md",
    5: REP / "r5-FM-09a-decision-review-v2.md",
}
KEYS = ["eid", "labels", "kind", "claim", "finding", "cites", "locator",
        "history", "status", "closed_at", "residual", "evidence"]
KINDS = {"attribution", "semantic", "math", "consistency", "guard", "process"}
STATUSES = {"closed", "still_wrong", "partial", "recurred", "not_applicable"}
THEN = {"raised", "open", "closed", "partial", "relocated"}
CITE = re.compile(r"^\d{3}:\d+$")
LINES_SPEC = re.compile(r"^\d+(-\d+)?(;\d+(-\d+)?)*$")

# 两次裁决独审中指向登记册或手册实物的发现：(标签, 轮次, 报告行, 该行须含的字样)
DECISION_FINDINGS = [
    ("裁一R3", 4, 37, "H129"), ("裁一R3", 4, 38, "106:168"),
    ("裁一R5", 4, 53, "018:26"), ("裁一R5", 4, 69, "1259"),
    ("裁一R7", 4, 81, "069:423"), ("裁一R7", 4, 82, "081:294"),
    ("裁二丙1", 5, 150, "B-23"), ("裁二丙1", 5, 150, "K3"),
    ("裁二乙1", 5, 29, "1259"), ("裁二乙1", 5, 31, "018:26"),
    ("裁二乙1", 5, 46, "017:14"), ("裁二乙2", 5, 56, ":1106"),
    ("裁二乙3", 5, 66, "H129"), ("裁二乙3", 5, 67, "M751"),
    ("裁二乙3", 5, 68, "093:26"), ("裁二乙3", 5, 69, "M17"),
    ("裁二乙3", 5, 70, "1524"), ("裁二乙4", 5, 129, "081:294"),
    ("裁二小项1", 5, 174, "051:246"), ("裁二小项2", 5, 175, "031:872"),
    ("裁一R1", 4, 25, "69/15/8"),
]


def read(n):
    return REPORTS[n].read_text(encoding="utf-8").splitlines()


def extract_labels():
    found = {}  # label -> set of "r<n>:<line>"

    def add(lab, n, i):
        found.setdefault(lab, set()).add(f"r{n}:{i}")

    for n in (1, 2, 3):
        for i, line in enumerate(read(n), 1):
            for m in re.finditer(r"(?<![A-Za-z])K(\d{1,2})(?!\d)", line):
                if 1 <= int(m.group(1)) <= 12:
                    add(f"K{m.group(1)}", n, i)
            for m in re.finditer(r"(?<![A-Za-z])N(\d)(?!\d)", line):
                add(f"N{m.group(1)}", n, i)
            for m in re.finditer(r"(?<![A-Za-z])R(\d{1,2})(?![\d(])", line):
                if 1 <= int(m.group(1)) <= 14:
                    add(f"R{m.group(1)}", n, i)
            if n in (2, 3):
                for m in re.finditer(r"B-(\d{1,2})(?!\d)", line):
                    add(f"B-{m.group(1)}", n, i)
            if n == 2 and 124 <= i <= 134:
                for m in re.finditer(r"(?<![A-Za-z-])B(\d{1,2})(?!\d)", line):
                    add(f"B-{m.group(1)}", n, i)
            if n == 3:
                for m in re.finditer(r"\*\*A(\d)｜", line):
                    add(f"A{m.group(1)}", n, i)
                if 102 <= i <= 116:
                    for m in re.finditer(r"\*\*B(\d{1,2})　", line):
                        add(f"乙B{m.group(1)}", n, i)
                if 149 <= i <= 157:
                    m = re.match(r"^\| (\d)　", line)
                    if m:
                        add(f"披露{m.group(1)}", n, i)
    return found


def excluded_from_readme():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"```excluded\n(.*?)```", text, re.S)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            if line.strip():
                lab, _, why = line.partition("\t")
                out[lab.strip()] = why.strip()
    return out


def main():
    errs = []
    rows = []
    lens = {n: len(read(n)) for n in REPORTS}
    path = ROOT / "errata.jsonl"
    for ln, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError as e:
            errs.append(f"行{ln} 非法 JSON：{e}")
            continue
        rows.append(rec)
        if list(rec) != KEYS:
            errs.append(f"行{ln} 键序或键集不符：{list(rec)}")
            continue
        eid = rec["eid"]
        if eid != f"E{ln:03d}":
            errs.append(f"行{ln} eid {eid} 不连续")
        if not rec["labels"] or not all(isinstance(x, str) and x for x in rec["labels"]):
            errs.append(f"{eid} labels 为空")
        if rec["kind"] not in KINDS:
            errs.append(f"{eid} kind 非法")
        for k in ("claim", "finding"):
            if not rec[k].strip():
                errs.append(f"{eid} {k} 为空")
        for k in ("closed_at", "residual", "evidence"):
            if not isinstance(rec[k], str):
                errs.append(f"{eid} {k} 不是字符串")
        if not all(CITE.match(c) for c in rec["cites"]):
            errs.append(f"{eid} cites 形状不符")
        if not rec["locator"]:
            errs.append(f"{eid} locator 为空")
        if not rec["cites"] and not rec["locator"]:
            errs.append(f"{eid} 无语料时须有 locator")
        if not rec["history"]:
            errs.append(f"{eid} history 为空")
        rounds = [x.get("round") for x in rec["history"]]
        if rounds != sorted(rounds) or len(set(rounds)) != len(rounds):
            errs.append(f"{eid} history 轮次未按序或重复")
        for x in rec["history"]:
            if list(x) != ["round", "report_lines", "status_then"]:
                errs.append(f"{eid} history 元素键不符")
                continue
            if x["round"] not in REPORTS:
                errs.append(f"{eid} round 非法")
                continue
            if x["status_then"] not in THEN:
                errs.append(f"{eid} status_then 非法")
            if not LINES_SPEC.match(x["report_lines"]):
                errs.append(f"{eid} report_lines 形状不符")
                continue
            for part in re.findall(r"\d+", x["report_lines"]):
                if not 1 <= int(part) <= lens[x["round"]]:
                    errs.append(f"{eid} 第{x['round']}轮行号 {part} 越界")
        st = rec["status"]
        if st not in STATUSES:
            errs.append(f"{eid} status 非法")
        if st == "closed" and not rec["closed_at"]:
            errs.append(f"{eid} closed 但 closed_at 为空")
        if st != "closed" and rec["closed_at"]:
            errs.append(f"{eid} 非 closed 却有 closed_at")
        if st in ("partial", "recurred", "not_applicable") and not rec["residual"]:
            errs.append(f"{eid} {st} 须写 residual")

    in_table = {lab for r in rows if isinstance(r, dict) for lab in r.get("labels", [])}
    found = extract_labels()
    for lab, n, line, token in DECISION_FINDINGS:
        text = read(n)[line - 1] if line <= lens[n] else ""
        if token not in text:
            errs.append(f"裁决发现定位失效：{lab} r{n}:{line} 不含 {token}")
        found.setdefault(lab, set()).add(f"r{n}:{line}")
    excluded = excluded_from_readme()
    uncovered = sorted(l for l in found if l not in in_table and l not in excluded)
    readme_only = sorted(l for l in found if l not in in_table and l in excluded)
    stray = sorted(l for l in excluded if l in in_table)

    print(f"rows {len(rows)}")
    print("status", dict(Counter(r.get("status") for r in rows)))
    print("kind", dict(Counter(r.get("kind") for r in rows)))
    print(f"report labels {len(found)}; in table {len(set(found) & in_table)}; "
          f"README-excluded {len(readme_only)}; uncovered {len(uncovered)}")
    if readme_only:
        print("README-excluded:", " ".join(readme_only))
    if uncovered:
        print("UNCOVERED:", " ".join(f"{l}({','.join(sorted(found[l]))})" for l in uncovered))
    if stray:
        print("NOTE 已入表又列在 README 排除块：", " ".join(stray))
    for e in errs:
        print("ERR", e)
    sys.exit(1 if errs or uncovered else 0)


if __name__ == "__main__":
    main()
