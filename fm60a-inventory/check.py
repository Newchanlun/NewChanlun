#!/usr/bin/env python3
"""FM-60a 判例清点（#2324 第一步）的机械核对。

用法（仓库内任意目录）：  python3 -I fm60a-inventory/check.py

只用标准库；从 `git rev-parse --show-toplevel` 定位仓库根。
核对内容：
  1. 字段齐全、枚举合法、case_id 唯一；
  2. 每条 cite 的 quote 逐字等于语料对应课、对应行 char_span 处的字符（不做任何归一）；
  3. in_admit_table / admit_id / tier 与准入表现算一致
     （准入表从 git 对象读，取不到即退 2，不静默跳过）；
  4. zone 与「↑正文」界标一致（界标之前才可标正文；硬证据必须是正文）；
  5. asserted_values 每个值都以字面形式出现在它指向的 cite 的 quote 里。

退出码：0 全过；1 有不符（逐条列出）；2 环境问题（不在 git 仓库、语料缺、准入表取不到）。
"""
import glob
import json
import os
import subprocess
import sys
from collections import Counter

ADMIT_COMMIT = "7d0082ff6f8b1d7d9b7b98eb24712723d0a95d9c"
ADMIT_PATH = "formal_math/sources/admit/candidate/tier1_candidate.jsonl"

ZONES = {"正文", "答疑", "课间", "解盘", "拿不准"}
TIERS = {"硬证据", "二级，未提升", "非作者，不作证据"}
STATUSES = {"可数字化", "需补数据", "依赖图片", "不可回归"}
SPEAKERS = {"作者", "网友", "编者"}
DATA_STATUS = {"仓内已有", "仓内没有"}
CASE_KEYS = [
    "case_id", "group", "instrument", "timeframe", "period", "period_basis",
    "cites", "assertion", "asserted_values", "base_and_pen", "data_needed",
    "data_status", "data_paths", "data_note", "external_availability",
    "image_dependent", "status", "status_reason", "register_discrepancy", "uncertain",
]
CITE_KEYS = [
    "lesson", "line", "speaker", "quote", "char_span", "zone", "zone_certain",
    "zone_basis", "register_zone", "zone_candidates", "in_admit_table", "admit_id", "tier",
]


def die(code, msg):
    print(msg, file=sys.stderr)
    sys.exit(code)


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    r = subprocess.run(["git", "-C", here, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode != 0:
        die(2, "不在 git 仓库内：" + r.stderr.strip())
    root = r.stdout.strip()

    # 准入表：只从 git 对象读
    g = git(root, "show", f"{ADMIT_COMMIT}:{ADMIT_PATH}")
    if g.returncode != 0:
        die(2, f"取不到准入表 {ADMIT_COMMIT}:{ADMIT_PATH}（先 git fetch origin infra/2317-admit-table）：{g.stderr.decode('utf-8', 'replace').strip()}")
    admit = {}
    n_admit = 0
    for raw in g.stdout.decode("utf-8").split("\n"):
        if raw.strip():
            d = json.loads(raw)
            admit.setdefault((d["lesson"], d["line"]), []).append(d)
            n_admit += 1
    if n_admit != 790:
        die(2, f"准入表条数 {n_admit} != 790，对象不对")

    # 语料
    blog = os.path.join(root, "docs", "chanlun", "text", "blog")
    corpus = {}

    def lesson_lines(k):
        if k not in corpus:
            fs = sorted(glob.glob(os.path.join(blog, f"{k}-*.md")))
            if len(fs) != 1:
                die(2, f"语料里找不到唯一的第 {k} 课文件：{fs}")
            with open(fs[0], encoding="utf-8", newline="") as f:
                corpus[k] = f.read().split("\n")
        return corpus[k]

    def marker(k):
        for i, s in enumerate(lesson_lines(k), 1):
            if "↑正文" in s:
                return i
        return None

    path = os.path.join(here, "cases.jsonl")
    cases = []
    with open(path, encoding="utf-8") as f:
        for ln, raw in enumerate(f, 1):
            if raw.strip():
                try:
                    cases.append(json.loads(raw))
                except ValueError as e:
                    die(1, f"cases.jsonl 第 {ln} 行不是合法 JSON：{e}")

    bad = []
    seen = set()
    for c in cases:
        cid = c.get("case_id", "?")
        for k in CASE_KEYS:
            if k not in c:
                bad.append(f"{cid}: 缺字段 {k}")
        if cid in seen:
            bad.append(f"{cid}: case_id 重复")
        seen.add(cid)
        if c.get("status") not in STATUSES:
            bad.append(f"{cid}: status 非法 {c.get('status')!r}")
        if c.get("data_status") not in DATA_STATUS:
            bad.append(f"{cid}: data_status 非法 {c.get('data_status')!r}")
        if c.get("external_availability") != "未查":
            bad.append(f"{cid}: external_availability 本步应为「未查」")
        img = c.get("image_dependent") or {}
        if not isinstance(img.get("value"), bool) or not img.get("note"):
            bad.append(f"{cid}: image_dependent 须含布尔 value 与 note")
        if c.get("status") == "依赖图片" and img.get("value") is not True:
            bad.append(f"{cid}: status=依赖图片 但 image_dependent.value 非 true")
        if not c.get("status_reason"):
            bad.append(f"{cid}: status_reason 为空")
        if not isinstance(c.get("register_discrepancy"), list):
            bad.append(f"{cid}: register_discrepancy 须为数组")
        cites = c.get("cites") or []
        if not cites:
            bad.append(f"{cid}: cites 为空")
        for i, ct in enumerate(cites):
            tag = f"{cid}.cites[{i}]"
            miss = [k for k in CITE_KEYS if k not in ct]
            if miss:
                bad.append(f"{tag}: 缺字段 {miss}")
                continue
            if ct["zone"] not in ZONES:
                bad.append(f"{tag}: zone 非法 {ct['zone']!r}")
            if ct["tier"] not in TIERS:
                bad.append(f"{tag}: tier 非法 {ct['tier']!r}")
            if ct["speaker"] not in SPEAKERS:
                bad.append(f"{tag}: speaker 非法 {ct['speaker']!r}")
            if not ct["zone_basis"]:
                bad.append(f"{tag}: zone_basis 为空")
            if (ct["zone"] == "拿不准") != bool(ct["zone_candidates"]):
                bad.append(f"{tag}: zone=拿不准 与 zone_candidates 不一致")
            if ct["zone"] == "拿不准" and ct["zone_certain"] is not False:
                bad.append(f"{tag}: zone=拿不准 时 zone_certain 须为 false")
            k, n = ct["lesson"], ct["line"]
            L = lesson_lines(k)
            if not (1 <= n <= len(L)):
                bad.append(f"{tag}: 行号 {k}:{n} 超出（共 {len(L)} 行）")
                continue
            a, b = ct["char_span"]
            line = L[n - 1]
            if not (0 <= a < b <= len(line)) or line[a:b] != ct["quote"]:
                bad.append(f"{tag}: quote 与 {k}:{n}[{a}:{b}] 的原文不逐字相等")
                continue
            # 准入表复算
            recs = admit.get((k, n), [])
            want_in = bool(recs)
            hits = sorted(d["id"] for d in recs for sa, sb in d["author_spans"] if sa <= a and b <= sb)
            want_id = hits[0] if hits else None
            if len(hits) > 1:
                bad.append(f"{tag}: 命中多条准入记录 {hits}，需人工看")
            if ct["in_admit_table"] != want_in:
                bad.append(f"{tag}: in_admit_table={ct['in_admit_table']} 现算 {want_in}")
            if ct["admit_id"] != want_id:
                bad.append(f"{tag}: admit_id={ct['admit_id']} 现算 {want_id}")
            if ct["speaker"] != "作者":
                want_tier = "非作者，不作证据"
            else:
                want_tier = "硬证据" if want_id is not None else "二级，未提升"
            if ct["tier"] != want_tier:
                bad.append(f"{tag}: tier={ct['tier']} 现算 {want_tier}")
            # 区与界标
            m = marker(k)
            if ct["zone"] == "正文":
                if m is None or n >= m:
                    bad.append(f"{tag}: zone=正文 但 {k}:{n} 不在 ↑正文 界标（{m}）之前")
            elif m is not None and n < m and ct["speaker"] == "作者":
                bad.append(f"{tag}: zone={ct['zone']} 但 {k}:{n} 在 ↑正文 界标（{m}）之前")
            if want_tier == "硬证据" and ct["zone"] != "正文":
                bad.append(f"{tag}: 硬证据 但 zone 不是正文")
            if want_in and ct["zone"] != "正文":
                bad.append(f"{tag}: 该行在准入表内（仅收正文区）但 zone={ct['zone']}")
        for j, av in enumerate(c.get("asserted_values") or []):
            idx = av.get("cite")
            if not isinstance(idx, int) or not (0 <= idx < len(cites)):
                bad.append(f"{cid}.asserted_values[{j}]: cite 指向越界 {idx!r}")
                continue
            if av.get("value") not in cites[idx].get("quote", ""):
                bad.append(f"{cid}.asserted_values[{j}]: 值 {av.get('value')!r} 不在 cites[{idx}].quote 中")
        if not c.get("asserted_values"):
            bad.append(f"{cid}: asserted_values 为空")

    if bad:
        print(f"不符 {len(bad)} 处：")
        for s in bad:
            print("  -", s)
        sys.exit(1)

    cs = [ct for c in cases for ct in c["cites"]]
    print(f"全部通过：{len(cases)} 条判例，{len({c['group'] for c in cases})} 个 group，{len(cs)} 条 cite；准入表 {n_admit} 条")
    print("status：", dict(Counter(c["status"] for c in cases)))
    print("tier：  ", dict(Counter(ct["tier"] for ct in cs)))
    print("zone：  ", dict(Counter(ct["zone"] for ct in cs)))
    print("zone（仅作者 cite）：", dict(Counter(ct["zone"] for ct in cs if ct["speaker"] == "作者")))
    print("登记册出入条数：", sum(len(c["register_discrepancy"]) for c in cases),
          "（涉及判例 %d 条）" % sum(1 for c in cases if c["register_discrepancy"]))
    print("标拿不准的判例：", sum(1 for c in cases if c["uncertain"]))
    print("image_dependent=true：", sum(1 for c in cases if c["image_dependent"]["value"]))
    sys.exit(0)


if __name__ == "__main__":
    main()
