#!/usr/bin/env python3
"""FM-60a 原典作者陈述库（#2324，fm60a-author-statements-v1）机械核对脚本。

用法（仓库内任意目录）：
    python3 -I fm60a-kernel/check.py

仅使用 Python 标准库；通过 `git rev-parse --show-toplevel` 定位仓库根，不含任何机器绝对路径。

核对范围（仅针对作者陈述库与隔离边界；不含任何建模、合成实例或定义预期）：
  1. classification.jsonl 与 fm60a-inventory/cases.jsonl 逐一双射（61 条齐全、类别与
     kernel_digitization_status 合法）；
  2. kernel-cases.jsonl 仅含 9 条示范判例的作者陈述（schema_version="fm60a-author-statements-v1"），
     机械禁止出现任何建模/实例/预期字段（organizer_models / instances / added_premises /
     synthetic_witnesses / structure_spec / assertions / counterfactuals）；
  3. 隔离文件对齐：legacy-v1-unreviewed.jsonl 恰含其余 20 条旧格式未审查记录（与 9 条示范不相交，
     并集恰等于 classification.jsonl 的 29 条 kernel_only+both）；draft-models-unreviewed.jsonl
     恰含 9 条示范移出的未过审整理者草稿；
  4. 逐字引文（cites）：每条 quote 逐字等于 docs/chanlun/text/blog/<lesson>-*.md 对应行 char_span
     （不做字符归一化）；相对准入表对象 7d0082ff 现场重算 in_admit_table / admit_id / tier；
     校验 ↑正文 界标、from_inventory 逐字一致、原清点表作者引文 100% 保留、speaker_basis 非空、
     禁止已标非作者的 cite 进入 refs；
  5. 作者陈述层（author_statements）：
     - context（scene_kind 合法、post_timestamp / time_anchor / summary 非空）；
     - mood 属于 7 值封闭枚举且 mood_note 非空；
     - mood 为「条件句」或「假设或反事实」时 antecedent 必填非空，其余语气必须为 null；
     - statement、antecedent 与 objects_and_values[*].literal_value 中的每一个数值都逐字
       （或等价中文数字）出现在对应 refs 引文中；
     - 高风险限定词（「严格」「唯一」「必然」「已」）若出现在 statement 或 antecedent 中，
       必须也出现在对应 refs 引文中；
     - objects_and_values 字段完整，标为「原文未指明」时必带非空 unspecified_note；
     - depends_on_statements 指向同判例合法陈述且构成无环图（DAG，不成环）；
       qualified_by_statements 指向同判例其他合法陈述；
     - evidence_tier（本条）、effective_tier_with_dependencies（含传递依存）与记录级
       evidence_grade 全部按 refs 现场重算一致。

退出码：
  0  全部通过
  1  发现不符（逐条列出）
  2  环境问题（不在 git 仓库、语料/清点表缺失、准入表对象取不到）
"""
import glob
import json
import os
import re
import subprocess
import sys
from collections import Counter

ADMIT_COMMIT = "7d0082ff6f8b1d7d9b7b98eb24712723d0a95d9c"
ADMIT_PATH = "formal_math/sources/admit/candidate/tier1_candidate.jsonl"

CATEGORIES = {"kernel_only", "market_only", "both", "unusable"}
DIG_STATUSES = {"author_statements_v1", "v1_legacy_unreviewed", "not_kernel"}
ZONES = {"正文", "答疑", "课间", "解盘", "拿不准"}
TIERS = {"硬证据", "二级，未提升", "非作者，不作证据"}
SPEAKERS = {"作者", "网友", "编者"}

SCENE_KINDS = {
    "事后复盘",
    "当日更正复盘",
    "当日盘后分析",
    "一般规则与举例",
    "图例分析",
    "课后答疑",
    "布置作业",
    "后续规则调整",
}

MOODS = {
    "直陈事实",
    "条件句",
    "假设或反事实",
    "预测",
    "事后回顾",
    "设问或留作作业",
    "引述他人",
}
CONDITIONAL_MOODS = {"条件句", "假设或反事实"}
FORBIDDEN_UNQUOTED_QUALIFIERS = ("严格", "唯一", "必然", "已")

DEP_RELATIONS = {
    "语境前提",
    "分解前提",
    "指代前文",
    "图设条件",
    "规则例外配对",
    "规则依据",
}
OBJ_KINDS = {"literal_number", "symbolic_object"}

FORBIDDEN_CASE_KEYS = {
    "organizer_models",
    "instances",
    "added_premises",
    "synthetic_witnesses",
    "structure_spec",
    "assertions",
    "counterfactuals",
    "expected_under_model",
    "expected_under_instance",
}

CLASS_KEYS = [
    "case_id",
    "group",
    "category",
    "digitized_in_kernel",
    "kernel_digitization_status",
    "batch_a_status",
    "inventory_status",
    "inventory_image_dependent",
    "reason",
]

CASE_KEYS = [
    "schema_version",
    "case_id",
    "group",
    "category",
    "exemplar",
    "target_concepts",
    "evidence_grade",
    "base_and_pen",
    "paired_cases",
    "real_market_dependency",
    "cites",
    "author_statements",
]

CITE_KEYS = [
    "cite_index",
    "lesson",
    "line",
    "speaker",
    "speaker_basis",
    "quote",
    "char_span",
    "zone",
    "in_admit_table",
    "admit_id",
    "tier",
    "from_inventory",
]

STMT_KEYS = [
    "statement_id",
    "context",
    "mood",
    "mood_note",
    "antecedent",
    "scope_qualifiers",
    "statement",
    "objects_and_values",
    "depends_on_statements",
    "qualified_by_statements",
    "evidence_tier",
    "effective_tier_with_dependencies",
    "refs",
]

ZH_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
ISO_DATE_ANCHOR_RE = re.compile(r"（(\d{4}-\d{2}-\d{2})）")
CN_DIGIT_MAP = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}
EPS = 1e-9


def die(code, msg):
    print(msg, file=sys.stderr)
    sys.exit(code)


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True)


def extract_numbers_from_text(text):
    nums = set()
    for m in ZH_NUM_RE.findall(text):
        try:
            nums.add(float(m))
        except ValueError:
            pass
    for ch, val in CN_DIGIT_MAP.items():
        if ch in text:
            nums.add(float(val))
    return nums


def extract_arabic_numbers(text):
    out = []
    for m in ZH_NUM_RE.findall(text):
        try:
            out.append((m, float(m)))
        except ValueError:
            pass
    return out


def num_in_refs(num, refs):
    target = float(num)
    for r in refs:
        lit = r.get("literal", "")
        for cand in extract_numbers_from_text(lit):
            if abs(cand - target) <= EPS:
                return True
    return False


def compute_tier_from_refs(refs, cites):
    tiers = {cites[r["cite"]]["tier"] for r in refs}
    if not tiers:
        return "无引用"
    if tiers == {"硬证据"}:
        return "硬证据"
    if "硬证据" in tiers and "二级，未提升" in tiers:
        return "混合（含硬证据与二级）"
    if tiers == {"二级，未提升"}:
        return "二级，未提升"
    return "含非作者引用"


def check_refs_list(refs, cites, tag, bad, require_nonempty=True):
    if not isinstance(refs, list):
        bad.append(f"{tag}: refs 须为数组")
        return False
    if require_nonempty and not refs:
        bad.append(f"{tag}: refs 不能为空")
        return False
    ok = True
    for j, r in enumerate(refs):
        rtag = f"{tag}.refs[{j}]"
        if not isinstance(r, dict) or "cite" not in r or "literal" not in r:
            bad.append(f"{rtag}: 须含 cite 与 literal")
            ok = False
            continue
        idx = r["cite"]
        lit = r["literal"]
        if not isinstance(idx, int) or isinstance(idx, bool) or not (0 <= idx < len(cites)):
            bad.append(f"{rtag}: cite 索引越界 {idx!r}")
            ok = False
            continue
        ct = cites[idx]
        if ct["speaker"] != "作者":
            bad.append(f"{rtag}: 禁止引用已标非作者（{ct['speaker']}）的 cite[{idx}]")
            ok = False
        if not isinstance(lit, str) or not lit:
            bad.append(f"{rtag}: literal 须为非空字符串")
            ok = False
        elif lit not in ct["quote"]:
            bad.append(f"{rtag}: literal {lit!r} 未逐字出现在 cites[{idx}].quote 中")
            ok = False
    return ok


def detect_dep_cycles(dep_graph, cid, bad):
    """三色 DFS 检查 depends_on_statements 是否成环。"""
    color = {}  # 0=unvisited, 1=visiting, 2=done

    def dfs(u, path):
        color[u] = 1
        for v in dep_graph.get(u, []):
            if v not in dep_graph:
                continue
            if color.get(v, 0) == 1:
                bad.append(f"{cid}: depends_on_statements 存在环路：{' -> '.join(path + [v])}")
                return
            if color.get(v, 0) == 0:
                dfs(v, path + [v])
        color[u] = 2

    for node in dep_graph:
        if color.get(node, 0) == 0:
            dfs(node, [node])


def transitive_deps(sid, dep_graph):
    seen = set()
    stack = list(dep_graph.get(sid, []))
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in dep_graph:
            continue
        seen.add(cur)
        stack.extend(dep_graph.get(cur, []))
    return seen


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    r = subprocess.run(["git", "-C", here, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode != 0:
        die(2, "不在 git 仓库内：" + r.stderr.strip())
    root = r.stdout.strip()

    # 1. 准入表（必须从 git 对象读）
    g = git(root, "show", f"{ADMIT_COMMIT}:{ADMIT_PATH}")
    if g.returncode != 0:
        die(
            2,
            f"取不到准入表 {ADMIT_COMMIT}:{ADMIT_PATH}（请先 git fetch origin infra/2317-admit-table）："
            + g.stderr.decode("utf-8", "replace").strip(),
        )
    admit = {}
    n_admit = 0
    for raw in g.stdout.decode("utf-8").split("\n"):
        if raw.strip():
            d = json.loads(raw)
            admit.setdefault((d["lesson"], d["line"]), []).append(d)
            n_admit += 1
    if n_admit != 790:
        die(2, f"准入表条数 {n_admit} != 790，对象不对")

    # 2. 清点表与甲批结果
    inv_path = os.path.join(root, "fm60a-inventory", "cases.jsonl")
    if not os.path.exists(inv_path):
        die(2, "缺清点表 fm60a-inventory/cases.jsonl")
    inv = {}
    with open(inv_path, encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                d = json.loads(raw)
                inv[d["case_id"]] = d

    batch_a_path = os.path.join(root, "fm60a-batch-a", "cases-digitized.jsonl")
    batch_a = {}
    if os.path.exists(batch_a_path):
        with open(batch_a_path, encoding="utf-8") as f:
            for raw in f:
                if raw.strip():
                    d = json.loads(raw)
                    batch_a[d["case_id"]] = d["status"]

    # 3. 语料加载器
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

    # 4. 读取产物与隔离文件
    class_path = os.path.join(here, "classification.jsonl")
    kernel_path = os.path.join(here, "kernel-cases.jsonl")
    legacy_path = os.path.join(here, "legacy-v1-unreviewed.jsonl")
    draft_path = os.path.join(here, "draft-models-unreviewed.jsonl")
    for p in (class_path, kernel_path, legacy_path, draft_path):
        if not os.path.exists(p):
            die(1, f"缺少文件：{os.path.basename(p)}")

    bad = []

    # 5. 核对 classification.jsonl
    cls_rows = []
    with open(class_path, encoding="utf-8") as f:
        for ln, raw in enumerate(f, 1):
            if raw.strip():
                try:
                    cls_rows.append(json.loads(raw))
                except ValueError as e:
                    die(1, f"classification.jsonl 第 {ln} 行不是合法 JSON：{e}")

    cls_by_id = {}
    for row in cls_rows:
        cid = row.get("case_id", "?")
        miss = [k for k in CLASS_KEYS if k not in row]
        if miss:
            bad.append(f"classification[{cid}]: 缺字段 {miss}")
            continue
        if cid in cls_by_id:
            bad.append(f"classification[{cid}]: case_id 重复")
        cls_by_id[cid] = row
        if row["category"] not in CATEGORIES:
            bad.append(f"classification[{cid}]: category 非法 {row['category']!r}")
        if row["kernel_digitization_status"] not in DIG_STATUSES:
            bad.append(f"classification[{cid}]: kernel_digitization_status 非法 {row['kernel_digitization_status']!r}")
        if not isinstance(row["digitized_in_kernel"], bool):
            bad.append(f"classification[{cid}]: digitized_in_kernel 须为布尔值")
        want_dig = row["category"] in ("kernel_only", "both")
        if row["digitized_in_kernel"] != want_dig:
            bad.append(f"classification[{cid}]: digitized_in_kernel 与 category 不符")
        if want_dig and row["kernel_digitization_status"] == "not_kernel":
            bad.append(f"classification[{cid}]: category={row['category']} 但状态为 not_kernel")
        if not want_dig and row["kernel_digitization_status"] != "not_kernel":
            bad.append(f"classification[{cid}]: category={row['category']} 但状态为 {row['kernel_digitization_status']!r}")
        if cid not in inv:
            bad.append(f"classification[{cid}]: 不在清点表中")
        else:
            if row["group"] != inv[cid]["group"]:
                bad.append(f"classification[{cid}]: group 与清点表不一致")
            if row["inventory_status"] != inv[cid]["status"]:
                bad.append(f"classification[{cid}]: inventory_status 与清点表不一致")
            if row["inventory_image_dependent"] != inv[cid]["image_dependent"]["value"]:
                bad.append(f"classification[{cid}]: inventory_image_dependent 与清点表不一致")
            want_ba = batch_a.get(cid, "未纳入甲批")
            if row["batch_a_status"] != want_ba:
                bad.append(f"classification[{cid}]: batch_a_status={row['batch_a_status']!r} 现算 {want_ba!r}")
        if not row.get("reason"):
            bad.append(f"classification[{cid}]: reason 为空")

    inv_ids = set(inv.keys())
    cls_ids = set(cls_by_id.keys())
    if inv_ids != cls_ids:
        bad.append(f"classification 覆盖不齐：漏 {sorted(inv_ids - cls_ids)}，多 {sorted(cls_ids - inv_ids)}")

    # 6. 核对隔离文件（只验边界与身份，不审核其内容）
    legacy_ids = set()
    with open(legacy_path, encoding="utf-8") as f:
        for ln, raw in enumerate(f, 1):
            if raw.strip():
                try:
                    rec = json.loads(raw)
                except ValueError as e:
                    die(1, f"legacy-v1-unreviewed.jsonl 第 {ln} 行不是合法 JSON：{e}")
                lcid = rec.get("case_id", "?")
                if lcid in legacy_ids:
                    bad.append(f"legacy[{lcid}]: case_id 重复")
                legacy_ids.add(lcid)
                if rec.get("schema_version") != "fm60a-kernel-v1" or rec.get("exemplar") is not False:
                    bad.append(f"legacy[{lcid}]: 隔离文件只应含 fm60a-kernel-v1 且 exemplar=false")

    draft_ids = set()
    with open(draft_path, encoding="utf-8") as f:
        for ln, raw in enumerate(f, 1):
            if raw.strip():
                try:
                    rec = json.loads(raw)
                except ValueError as e:
                    die(1, f"draft-models-unreviewed.jsonl 第 {ln} 行不是合法 JSON：{e}")
                dcid = rec.get("case_id", "?")
                if dcid in draft_ids:
                    bad.append(f"draft[{dcid}]: case_id 重复")
                draft_ids.add(dcid)
                if rec.get("draft_status") != "unreviewed_organizer_draft":
                    bad.append(f"draft[{dcid}]: draft_status 须为 'unreviewed_organizer_draft'")
                if "organizer_models" not in rec or "instances" not in rec:
                    bad.append(f"draft[{dcid}]: 缺 organizer_models 或 instances")

    # 7. 核对 kernel-cases.jsonl（纯作者陈述库）
    kcases = []
    with open(kernel_path, encoding="utf-8") as f:
        for ln, raw in enumerate(f, 1):
            if raw.strip():
                try:
                    kcases.append(json.loads(raw))
                except ValueError as e:
                    die(1, f"kernel-cases.jsonl 第 {ln} 行不是合法 JSON：{e}")

    seen_k = set()
    n_cites = 0
    n_stmts = 0
    n_unspecified = 0
    mood_cnt = Counter()
    tier_cnt = Counter()
    eff_tier_cnt = Counter()

    for kc in kcases:
        cid = kc.get("case_id", "?")
        for fk in FORBIDDEN_CASE_KEYS:
            if fk in kc:
                bad.append(f"{cid}: 作者陈述库严禁包含建模/实例字段 {fk!r}")
        miss = [k for k in CASE_KEYS if k not in kc]
        if miss:
            bad.append(f"{cid}: 缺顶层字段 {miss}")
            continue
        if cid in seen_k:
            bad.append(f"{cid}: case_id 重复")
        seen_k.add(cid)
        if kc["schema_version"] != "fm60a-author-statements-v1":
            bad.append(f"{cid}: schema_version 须为 'fm60a-author-statements-v1'，实际 {kc['schema_version']!r}")
        if kc["exemplar"] is not True:
            bad.append(f"{cid}: 当前交付物仅收 9 条示范判例（exemplar=true）")
        if kc["category"] not in ("kernel_only", "both"):
            bad.append(f"{cid}: category 非法 {kc['category']!r}")
        if cid in cls_by_id and kc["category"] != cls_by_id[cid]["category"]:
            bad.append(f"{cid}: category 与 classification.jsonl 不一致")
        if cid in inv and kc["group"] != inv[cid]["group"]:
            bad.append(f"{cid}: group 与清点表不一致")
        if not isinstance(kc["target_concepts"], list) or not kc["target_concepts"]:
            bad.append(f"{cid}: target_concepts 须为非空数组")

        # 7a. 核对 cites
        cites = kc["cites"]
        if not isinstance(cites, list) or not cites:
            bad.append(f"{cid}: cites 不能为空")
            continue

        inv_cite_tuples = set()
        if cid in inv:
            for ict in inv[cid]["cites"]:
                inv_cite_tuples.add((ict["lesson"], ict["line"], tuple(ict["char_span"]), ict["quote"]))

        for i, ct in enumerate(cites):
            tag = f"{cid}.cites[{i}]"
            cmiss = [k for k in CITE_KEYS if k not in ct]
            if cmiss:
                bad.append(f"{tag}: 缺字段 {cmiss}")
                continue
            if ct["cite_index"] != i:
                bad.append(f"{tag}: cite_index={ct['cite_index']} != {i}")
            if ct["zone"] not in ZONES:
                bad.append(f"{tag}: zone 非法 {ct['zone']!r}")
            if ct["tier"] not in TIERS:
                bad.append(f"{tag}: tier 非法 {ct['tier']!r}")
            if ct["speaker"] not in SPEAKERS:
                bad.append(f"{tag}: speaker 非法 {ct['speaker']!r}")
            if not isinstance(ct["speaker_basis"], str) or not ct["speaker_basis"].strip():
                bad.append(f"{tag}: speaker_basis 不能为空（须写出说话人确认依据供人审）")
            if not isinstance(ct["from_inventory"], bool):
                bad.append(f"{tag}: from_inventory 须为布尔值")
            k, n = ct["lesson"], ct["line"]
            L = lesson_lines(k)
            if not (1 <= n <= len(L)):
                bad.append(f"{tag}: 行号 {k}:{n} 越界（共 {len(L)} 行）")
                continue
            a, b = ct["char_span"]
            line = L[n - 1]
            if not (0 <= a < b <= len(line)) or line[a:b] != ct["quote"]:
                bad.append(f"{tag}: quote 与语料 {k}:{n}[{a}:{b}] 不逐字相等")
                continue
            if ct["from_inventory"]:
                tup = (k, n, (a, b), ct["quote"])
                if tup not in inv_cite_tuples:
                    bad.append(f"{tag}: 标了 from_inventory=true，但清点表 {cid} 无此逐字引文")
            recs = admit.get((k, n), [])
            want_in = bool(recs)
            hits = sorted(d["id"] for d in recs for sa, sb in d["author_spans"] if sa <= a and b <= sb)
            want_id = hits[0] if hits else None
            if len(hits) > 1:
                bad.append(f"{tag}: 命中多条准入记录 {hits}")
            if ct["in_admit_table"] != want_in:
                bad.append(f"{tag}: in_admit_table={ct['in_admit_table']} 现算 {want_in}")
            if ct["admit_id"] != want_id:
                bad.append(f"{tag}: admit_id={ct['admit_id']} 现算 {want_id}")
            want_tier = "非作者，不作证据" if ct["speaker"] != "作者" else ("硬证据" if want_id is not None else "二级，未提升")
            if ct["tier"] != want_tier:
                bad.append(f"{tag}: tier={ct['tier']!r} 现算 {want_tier!r}")
            m = marker(k)
            if ct["zone"] == "正文":
                if m is None or n >= m:
                    bad.append(f"{tag}: zone=正文 但 {k}:{n} 不在 ↑正文 界标（{m}）之前")
            elif m is not None and n < m and ct["speaker"] == "作者":
                bad.append(f"{tag}: zone={ct['zone']!r} 但作者行 {k}:{n} 在 ↑正文 界标（{m}）之前")
            if want_tier == "硬证据" and ct["zone"] != "正文":
                bad.append(f"{tag}: 硬证据但 zone 不是正文")
            n_cites += 1

        # 确认清点表作者引文 100% 保留
        if cid in inv:
            kept = {(ct["lesson"], ct["line"], tuple(ct["char_span"])) for ct in cites}
            for ict in inv[cid]["cites"]:
                if ict["speaker"] == "作者":
                    key = (ict["lesson"], ict["line"], tuple(ict["char_span"]))
                    if key not in kept:
                        bad.append(f"{cid}: 遗漏了清点表原作者引文 {ict['lesson']}:{ict['line']}{ict['char_span']}")

        # 7b. 核对 author_statements
        stmts = kc["author_statements"]
        if not isinstance(stmts, list) or not stmts:
            bad.append(f"{cid}: author_statements 不能为空")
            continue

        as_map = {}
        ov_ids = set()
        dep_graph = {}
        all_as_refs = []

        for j, st in enumerate(stmts):
            sid = st.get("statement_id", f"#{j}")
            tag = f"{cid}.author_statements[{sid}]"
            smiss = [k for k in STMT_KEYS if k not in st]
            if smiss:
                bad.append(f"{tag}: 缺字段 {smiss}")
                continue
            if sid in as_map:
                bad.append(f"{tag}: statement_id 重复")
            as_map[sid] = st
            dep_graph[sid] = []

            # context
            ctx = st["context"]
            if not isinstance(ctx, dict):
                bad.append(f"{tag}: context 须为对象")
            else:
                if ctx.get("scene_kind") not in SCENE_KINDS:
                    bad.append(f"{tag}.context: scene_kind 非法 {ctx.get('scene_kind')!r}")
                for ck in ("post_timestamp", "time_anchor", "summary"):
                    if not isinstance(ctx.get(ck), str) or not ctx[ck].strip():
                        bad.append(f"{tag}.context.{ck}: 不能为空")

            # mood & mood_note & antecedent
            mood = st["mood"]
            if not isinstance(mood, str) or mood not in MOODS:
                bad.append(f"{tag}: mood 非法或为空 {mood!r}")
            else:
                mood_cnt[mood] += 1
            if not isinstance(st["mood_note"], str) or not st["mood_note"].strip():
                bad.append(f"{tag}: mood_note 不能为空")

            ant = st["antecedent"]
            if mood in CONDITIONAL_MOODS:
                if not isinstance(ant, str) or not ant.strip():
                    bad.append(f"{tag}: mood={mood!r} 必须填写非空 antecedent")
            else:
                if ant is not None:
                    bad.append(f"{tag}: mood={mood!r} 时 antecedent 须为 null")

            if not isinstance(st["scope_qualifiers"], list) or any(not isinstance(q, str) or not q.strip() for q in st["scope_qualifiers"]):
                bad.append(f"{tag}: scope_qualifiers 须为非空字符串数组（可为空数组 []）")

            stmt_text = st["statement"]
            if not isinstance(stmt_text, str) or not stmt_text.strip():
                bad.append(f"{tag}: statement 不能为空")

            # refs & evidence_tier & 数值/限定词逐字检查
            refs_ok = check_refs_list(st["refs"], cites, tag, bad, require_nonempty=True)
            if refs_ok:
                want_tier = compute_tier_from_refs(st["refs"], cites)
                if st["evidence_tier"] != want_tier:
                    bad.append(f"{tag}: evidence_tier={st['evidence_tier']!r} 现算 {want_tier!r}")
                tier_cnt[want_tier] += 1
                all_as_refs.extend(st["refs"])
                refs_concat = "".join(r["literal"] for r in st["refs"])
                ta_str = ctx.get("time_anchor", "") if isinstance(ctx, dict) else ""
                for fname, ftxt in (("statement", stmt_text), ("antecedent", ant or "")):
                    # 仅放行已在 context.time_anchor 中登记的「（YYYY-MM-DD）」时间锚点日期，其余所有阿拉伯数字须在 refs 中
                    def _check_date_anchor(m):
                        d_str = m.group(1)
                        if d_str not in ta_str:
                            bad.append(f"{tag}.{fname}: 时间锚点日期 {d_str!r} 未在 context.time_anchor 中登记")
                        return ""
                    stripped = ISO_DATE_ANCHOR_RE.sub(_check_date_anchor, ftxt)
                    for raw_num, fval in extract_arabic_numbers(stripped):
                        if not num_in_refs(fval, st["refs"]):
                            bad.append(f"{tag}.{fname}: 含数值 {raw_num!r} 未出现在 refs 引文中")
                    for q in FORBIDDEN_UNQUOTED_QUALIFIERS:
                        if q in stripped and q not in refs_concat:
                            bad.append(f"{tag}.{fname}: 含引文未出现的限定词 {q!r}")

            # objects_and_values
            ovs = st["objects_and_values"]
            if not isinstance(ovs, list):
                bad.append(f"{tag}: objects_and_values 须为数组")
            else:
                for ovi, ov in enumerate(ovs):
                    ovtag = f"{tag}.objects_and_values[{ovi}]"
                    req_ov = ("item_id", "kind", "literal_value", "author_target", "precise_point_or_field", "unspecified_note")
                    if any(k not in ov for k in req_ov):
                        bad.append(f"{ovtag}: 缺字段 {[k for k in req_ov if k not in ov]}")
                        continue
                    iid = ov["item_id"]
                    if iid in ov_ids:
                        bad.append(f"{ovtag}: item_id {iid!r} 在本判例内重复")
                    ov_ids.add(iid)
                    if ov["kind"] not in OBJ_KINDS:
                        bad.append(f"{ovtag}: kind 非法 {ov['kind']!r}")
                    elif ov["kind"] == "literal_number":
                        lv = ov["literal_value"]
                        if isinstance(lv, bool) or not isinstance(lv, (int, float)):
                            bad.append(f"{ovtag}: kind=literal_number 时 literal_value 须为数值，实际 {lv!r}")
                        elif refs_ok and not num_in_refs(lv, st["refs"]):
                            bad.append(f"{ovtag}: literal_value {lv} 未出现在 refs 引文中")
                    else:
                        if ov["literal_value"] is not None:
                            bad.append(f"{ovtag}: kind=symbolic_object 时 literal_value 须为 null")
                    if not isinstance(ov["author_target"], str) or not ov["author_target"].strip():
                        bad.append(f"{ovtag}: author_target 不能为空")
                    ppf = ov["precise_point_or_field"]
                    if not isinstance(ppf, str) or not ppf.strip():
                        bad.append(f"{ovtag}: precise_point_or_field 不能为空")
                    elif ppf == "原文未指明":
                        n_unspecified += 1
                        if not isinstance(ov["unspecified_note"], str) or not ov["unspecified_note"].strip():
                            bad.append(f"{ovtag}: precise_point_or_field='原文未指明' 时 unspecified_note 不能为空")
                    else:
                        if ov["unspecified_note"] is not None:
                            bad.append(f"{ovtag}: 已指明精确对象时 unspecified_note 应为 null")

            n_stmts += 1

        # 7c. 核对依存图（存在性、无环、传递有效等级）与 qualified_by_statements
        for sid, st in as_map.items():
            tag = f"{cid}.author_statements[{sid}]"
            deps = st["depends_on_statements"]
            if not isinstance(deps, list):
                bad.append(f"{tag}: depends_on_statements 须为数组")
            else:
                for di, dep in enumerate(deps):
                    dtag = f"{tag}.depends_on_statements[{di}]"
                    if not isinstance(dep, dict) or not dep.get("statement_id") or dep.get("relation") not in DEP_RELATIONS or not dep.get("note"):
                        bad.append(f"{dtag}: 须含合法 statement_id / relation / 非空 note")
                        continue
                    target_sid = dep["statement_id"]
                    if target_sid == sid:
                        bad.append(f"{dtag}: 不允许自依存 {sid}")
                    elif target_sid not in as_map:
                        bad.append(f"{dtag}: 指向不存在的陈述 {target_sid!r}")
                    else:
                        dep_graph[sid].append(target_sid)

            qby = st["qualified_by_statements"]
            if not isinstance(qby, list):
                bad.append(f"{tag}: qualified_by_statements 须为数组")
            else:
                for qsid in qby:
                    if qsid == sid:
                        bad.append(f"{tag}.qualified_by_statements: 不允许自指向 {sid}")
                    elif qsid not in as_map:
                        bad.append(f"{tag}.qualified_by_statements: 指向不存在的陈述 {qsid!r}")

        detect_dep_cycles(dep_graph, cid, bad)

        for sid, st in as_map.items():
            tag = f"{cid}.author_statements[{sid}]"
            tdeps = transitive_deps(sid, dep_graph)
            combined_refs = list(st["refs"])
            for dsid in tdeps:
                combined_refs.extend(as_map[dsid]["refs"])
            if all(isinstance(r.get("cite"), int) and 0 <= r["cite"] < len(cites) for r in combined_refs):
                want_eff = compute_tier_from_refs(combined_refs, cites)
                if st["effective_tier_with_dependencies"] != want_eff:
                    bad.append(
                        f"{tag}: effective_tier_with_dependencies={st['effective_tier_with_dependencies']!r} "
                        f"现算 {want_eff!r}（含传递依存 {sorted(tdeps)}）"
                    )
                eff_tier_cnt[want_eff] += 1

        if all_as_refs:
            want_grade = compute_tier_from_refs(all_as_refs, cites)
            if kc["evidence_grade"] != want_grade:
                bad.append(f"{cid}: evidence_grade={kc['evidence_grade']!r} 现算 {want_grade!r}")

        rmd = kc["real_market_dependency"]
        if not isinstance(rmd, dict) or rmd.get("needs_historical_data_for_kernel") is not False or not rmd.get("historical_data_meaning"):
            bad.append(f"{cid}: real_market_dependency 字段不完整或 needs_historical_data_for_kernel 不为 false")

    # 8. 核对四方集合对齐（classification / 9条作者陈述 / 20条旧格式 / 9条草稿）
    want_v1_as = {r["case_id"] for r in cls_rows if r["kernel_digitization_status"] == "author_statements_v1"}
    want_legacy = {r["case_id"] for r in cls_rows if r["kernel_digitization_status"] == "v1_legacy_unreviewed"}
    if seen_k & legacy_ids:
        bad.append(f"kernel-cases.jsonl 与 legacy-v1-unreviewed.jsonl 重叠：{sorted(seen_k & legacy_ids)}")
    if seen_k != want_v1_as:
        bad.append(f"kernel-cases.jsonl 与 classification(author_statements_v1) 不一致：漏 {sorted(want_v1_as - seen_k)}，多 {sorted(seen_k - want_v1_as)}")
    if legacy_ids != want_legacy:
        bad.append(f"legacy-v1-unreviewed.jsonl 与 classification(v1_legacy_unreviewed) 不一致")
    if draft_ids != seen_k:
        bad.append(f"draft-models-unreviewed.jsonl 与 9 条示范判例不一致：漏 {sorted(seen_k - draft_ids)}，多 {sorted(draft_ids - seen_k)}")

    if bad:
        print(f"FAIL: 共 {len(bad)} 处不符：", file=sys.stderr)
        for m in bad:
            print(" -", m, file=sys.stderr)
        sys.exit(1)

    cat_cnt = Counter(r["category"] for r in cls_rows)
    print(
        f"OK: classification={len(cls_rows)} 条 "
        f"(kernel_only={cat_cnt['kernel_only']}, market_only={cat_cnt['market_only']}, "
        f"both={cat_cnt['both']}, unusable={cat_cnt['unusable']}) | "
        f"作者陈述库={len(kcases)} 条 | 旧格式隔离={len(legacy_ids)} 条 | 草稿隔离={len(draft_ids)} 条 | "
        f"cites={n_cites} | 作者陈述={n_stmts} (单条等级={dict(tier_cnt)}, 含依存有效等级={dict(eff_tier_cnt)}) | "
        f"语气={dict(mood_cnt)} | 标原文未指明对象={n_unspecified}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
