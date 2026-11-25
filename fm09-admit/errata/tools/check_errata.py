#!/usr/bin/env python3
"""自检 ../errata.jsonl。

检查：格式与取值；eid 递增；related 互指；locator 按版本打开原件、行非空（或确认键缺失）；
history 报告行号不越界；对六份报告编号的覆盖（表内 labels ∪ README 排除块）；
第6轮实物审覆盖节的报告行与具体 id 可在表内查到；14 个被点名 eid 在 README「返修对照」逐个有记录。

用法（仓库根目录，需能访问 4b75e60e9e、36fc364aea、77c6aa6eb8 三个提交）：
  PYTHONDONTWRITEBYTECODE=1 python3 -I fm09-admit/errata/tools/check_errata.py
退出 0：全部通过；1：有错误或未覆盖项。
"""
import json
import pathlib
import re
import subprocess
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
    6: REP / "r6-FM-09a-data-review.md",
}
KEYS = ["eid", "labels", "kind", "object", "direction", "claim", "finding", "cites", "ids",
        "locator", "history", "status", "origin_status", "related", "closed_at", "residual",
        "evidence"]
KINDS = {"attribution", "semantic", "math", "consistency", "guard", "process"}
OBJECTS = {"doc_line", "record", "tool"}
DIRECTIONS = {"defect", "confirmed_fix"}
STATUSES = {"closed", "still_wrong", "partial", "recurred", "not_applicable"}
THEN = {"raised", "open", "closed", "partial", "relocated"}
CITE = re.compile(r"^\d{3}:\d+$")
LINES_SPEC = re.compile(r"^\d+(-\d+)?(;\d+(-\d+)?)*$")
VERSIONS = {"V1": "4b75e60e9e", "V2": "36fc364aea", "V3": "77c6aa6eb8"}
FILES = {
    "M": "fm09-register/FM-09-原典登记册.md",
    "H": "fm09-register/FM-MASTER-PLAN-v2.md",
    "附录1": "fm09-register/FM-09-附录1-全量台账.md",
    "附录2": "fm09-register/FM-09-附录2-四清单分类索引.md",
    "L": "fm09-register/tmp/ledger_final.jsonl",
    "J": "fm09-register/tmp/pool_375_recheck_r3.jsonl",
    "Jold": "fm09-register/tmp/pool_375_recheck.jsonl",
    "EX": "fm09-register/tmp/hard_cite_exclusions.json",
    "G": "fm09-register/guards/guard_register.py",
    "GM": "fm09-register/guards/g3_manual.json",
    "GR": "fm09-register/guards/README.md",
    "VF": "fm09-register/tmp/verify_final.py",
    "VR": "fm09-register/tmp/verify_report.py",
    "RM": "fm09-register/README.md",
}
LOC = re.compile(r"^(V[123]):([^:]+):(?:(\d+)(?:-(\d+))?|!(\w+)=(.+))$")

# 两次裁决独审中指向登记册或手册实物的发现：(标签, 轮次, 报告行, 该行须含的字样)
DECISION_FINDINGS = [
    ("裁一R3", 4, 37, "H129"), ("裁一R3", 4, 38, "106:168"),
    ("裁一R5", 4, 53, "018:26"), ("裁一R5", 4, 69, "1259"),
    ("裁一R7", 4, 81, "069:423"), ("裁一R7", 4, 82, "081:294"),
    ("裁一R1", 4, 15, "B-23"), ("裁一R1", 4, 25, "69/15/8"),
    ("裁二丙1", 5, 150, "B-23"), ("裁二丙1", 5, 150, "K3"),
    ("裁二乙1", 5, 29, "1259"), ("裁二乙1", 5, 31, "018:26"),
    ("裁二乙1", 5, 46, "017:14"), ("裁二乙2", 5, 56, ":1106"),
    ("裁二乙3", 5, 66, "H129"), ("裁二乙3", 5, 67, "M751"),
    ("裁二乙3", 5, 68, "093:26"), ("裁二乙3", 5, 69, "M17"),
    ("裁二乙3", 5, 70, "1524"), ("裁二乙4", 5, 129, "081:294"),
    ("裁二小项1", 5, 174, "051:246"), ("裁二小项2", 5, 175, "031:872"),
]
# 第6轮实物审：14 个被点名的 eid（报告行 67–80）
R6_NAMED = ["E012", "E017", "E021", "E027", "E036", "E044", "E052", "E058", "E061", "E062",
            "E065", "E080", "E081", "E082"]
# 第6轮覆盖节（报告行 88–97、99）须在某行 round-6 history 或指定行里出现
R6_COVER_LINES = {88: "E086", 89: "E087", 90: "E088", 91: "E089", 92: "E090", 93: None,
                  94: None, 95: None, 96: None, 97: None, 99: None}
R6_IDS = [155, 160, 167, 325, 478, 479, 600, 774, 747, 216, 219, 226, 229, 421, 439, 470,
          670, 381, 480, 686, 687, 312, 313, 512]
R6_NONPHYSICAL_IDS = [304, 270, 124, 391, 414]

_cache = {}


def git_lines(ver, key):
    k = (ver, key)
    if k not in _cache:
        res = subprocess.run(["git", "show", f"{VERSIONS[ver]}:{FILES[key]}"],
                             capture_output=True, cwd=ROOT)
        _cache[k] = res.stdout.decode("utf-8").splitlines() if res.returncode == 0 else None
    return _cache[k]


def check_locator(loc):
    m = LOC.match(loc)
    if not m:
        return "形状不符"
    ver, key, a, b, fld, val = m.groups()
    if key not in FILES:
        return f"未知文件 {key}"
    lines = git_lines(ver, key)
    if lines is None:
        return f"{ver} 无 {FILES[key]}"
    if fld:
        hits = [1 for ln in lines if ln.strip() and json.loads(ln).get(fld) == val]
        return f"{fld}={val} 实有 {len(hits)} 条" if hits else None
    a = int(a)
    b = int(b) if b else a
    if not (1 <= a <= b <= len(lines)):
        return "行号越界"
    for n in {a, b}:
        if not lines[n - 1].strip():
            return f"第 {n} 行为空"
    return None


def read(n):
    return REPORTS[n].read_text(encoding="utf-8").splitlines()


def extract_labels():
    found = {}

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


def readme_text():
    return (ROOT / "README.md").read_text(encoding="utf-8")


def readme_block(text, name):
    m = re.search(rf"```{name}\n(.*?)```", text, re.S)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            if line.strip():
                lab, _, why = line.partition("\t")
                out[lab.strip()] = why.strip()
    return out


def readme_section(text, title):
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1) if m else ""


def main():
    errs = []
    rows = []
    lens = {n: len(read(n)) for n in REPORTS}
    for ln, raw in enumerate((ROOT / "errata.jsonl").read_text(encoding="utf-8").splitlines(), 1):
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError as e:
            errs.append(f"行{ln} 非法 JSON：{e}")
            continue
        if list(rec) != KEYS:
            errs.append(f"行{ln} 键序或键集不符：{list(rec)}")
            continue
        rows.append(rec)
    by_eid = {}
    prev = 0
    for rec in rows:
        eid = rec["eid"]
        m = re.match(r"^E(\d{3})$", eid)
        if not m or int(m.group(1)) <= prev:
            errs.append(f"{eid} 不是递增的 Ennn")
        else:
            prev = int(m.group(1))
        by_eid[eid] = rec
        if not rec["labels"] or not all(isinstance(x, str) and x for x in rec["labels"]):
            errs.append(f"{eid} labels 为空")
        if rec["kind"] not in KINDS:
            errs.append(f"{eid} kind 非法")
        if rec["object"] not in OBJECTS:
            errs.append(f"{eid} object 非法")
        if rec["direction"] not in DIRECTIONS:
            errs.append(f"{eid} direction 非法")
        for k in ("claim", "finding", "evidence"):
            if not rec[k].strip():
                errs.append(f"{eid} {k} 为空")
        for k in ("closed_at", "residual", "origin_status"):
            if not isinstance(rec[k], str):
                errs.append(f"{eid} {k} 不是字符串")
        if not all(CITE.match(c) for c in rec["cites"]):
            errs.append(f"{eid} cites 形状不符")
        if not all(isinstance(i, int) for i in rec["ids"]):
            errs.append(f"{eid} ids 须为整数")
        if not rec["locator"]:
            errs.append(f"{eid} locator 为空")
        for loc in rec["locator"]:
            bad = check_locator(loc)
            if bad:
                errs.append(f"{eid} locator {loc}：{bad}")
        rounds = [x.get("round") for x in rec["history"]]
        if not rounds or rounds != sorted(rounds) or len(set(rounds)) != len(rounds):
            errs.append(f"{eid} history 为空、未按序或重复")
        for x in rec["history"]:
            if list(x) != ["round", "report_lines", "status_then"] or x["round"] not in REPORTS:
                errs.append(f"{eid} history 元素不符")
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
        if (st == "closed") != bool(rec["closed_at"]):
            errs.append(f"{eid} closed 与 closed_at 不对应")
        if st in ("partial", "recurred", "not_applicable") and not rec["residual"]:
            errs.append(f"{eid} {st} 须写 residual")
        if st == "recurred" and (rec["origin_status"] not in STATUSES or not rec["related"]):
            errs.append(f"{eid} recurred 须有 origin_status 与 related")
        if st != "recurred" and rec["origin_status"]:
            errs.append(f"{eid} 非 recurred 不写 origin_status")
        if rec["direction"] == "confirmed_fix" and st != "closed":
            errs.append(f"{eid} confirmed_fix 须为 closed")
    for eid, rec in by_eid.items():
        for r in rec["related"]:
            if r not in by_eid:
                errs.append(f"{eid} related 指向不存在的 {r}")
            elif eid not in by_eid[r]["related"]:
                errs.append(f"{eid} related {r} 未互指")

    # 编号覆盖
    text = readme_text()
    in_table = {lab for r in rows for lab in r["labels"]}
    found = extract_labels()
    for lab, n, line, token in DECISION_FINDINGS:
        if token not in read(n)[line - 1]:
            errs.append(f"裁决发现定位失效：{lab} r{n}:{line} 不含 {token}")
        found.setdefault(lab, set()).add(f"r{n}:{line}")
    excluded = readme_block(text, "excluded")
    uncovered = sorted(l for l in found if l not in in_table and l not in excluded)
    readme_only = sorted(l for l in found if l not in in_table and l in excluded)

    # 第6轮覆盖节
    r6 = read(6)
    r6_lines_in_table = set()
    for r in rows:
        for x in r["history"]:
            if x["round"] == 6:
                for a, b in re.findall(r"(\d+)(?:-(\d+))?", x["report_lines"]):
                    r6_lines_in_table.update(range(int(a), int(b or a) + 1))
    for line, eid in R6_COVER_LINES.items():
        if line not in r6_lines_in_table:
            errs.append(f"第6轮覆盖节第 {line} 行未在任何行 history 中承接")
        if eid and not any(x["round"] == 6 and str(line) in x["report_lines"]
                           for x in by_eid.get(eid, {}).get("history", [])):
            errs.append(f"第6轮覆盖节第 {line} 行应由 {eid} 承接")
    ids_in_table = {i for r in rows for i in r["ids"]}
    cover_text = "\n".join(r6[87:99])
    for i in R6_IDS:
        if str(i) not in cover_text:
            errs.append(f"id {i} 不在第6轮覆盖节原文里（清单写错）")
        if i not in ids_in_table:
            errs.append(f"第6轮覆盖节 id {i} 在表内查不到")
    nonphys = readme_section(text, "非实物事项")
    for i in R6_NONPHYSICAL_IDS:
        if str(i) not in nonphys:
            errs.append(f"非实物事项未列 id {i}")

    # 返修对照
    fix = readme_section(text, "返修对照")
    fixed_rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| (E\d{3}) \|.*$", fix, re.M)}
    for eid in R6_NAMED:
        row = fixed_rows.get(eid)
        if not row:
            errs.append(f"返修对照缺 {eid}")
            continue
        if not re.search(r"r6:\d+", row) or not re.search(r"V[123] [MHJL]|V[123] 附录|V[123] README|r[1-5]:\d+", row):
            errs.append(f"返修对照 {eid} 未写依据行或对读位置")
        if eid not in by_eid and "非实物事项" not in row:
            errs.append(f"{eid} 已删却未写明移入非实物事项")

    print(f"rows {len(rows)}")
    print("status", dict(Counter(r["status"] for r in rows)))
    print("direction", dict(Counter(r["direction"] for r in rows)))
    print("object", dict(Counter(r["object"] for r in rows)))
    print("kind", dict(Counter(r["kind"] for r in rows)))
    print("with related", sum(1 for r in rows if r["related"]))
    print(f"report labels {len(found)}; in table {len(set(found) & in_table)}; "
          f"README-excluded {len(readme_only)}; uncovered {len(uncovered)}")
    print(f"r6 named eids recorded {sum(1 for e in R6_NAMED if e in fixed_rows)}/14; "
          f"r6 cover lines {sum(1 for l in R6_COVER_LINES if l in r6_lines_in_table)}/{len(R6_COVER_LINES)}; "
          f"r6 ids {sum(1 for i in R6_IDS if i in ids_in_table)}/{len(R6_IDS)}")
    if uncovered:
        print("UNCOVERED:", " ".join(f"{l}({','.join(sorted(found[l]))})" for l in uncovered))
    for e in errs:
        print("ERR", e)
    sys.exit(1 if errs or uncovered else 0)


if __name__ == "__main__":
    main()
