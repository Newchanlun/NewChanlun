#!/usr/bin/env python3
"""FM-60a 内核判例数字化（#2324，fm60a-kernel-v2 三层格式）机械核对脚本。

用法（仓库内任意目录）：
    python3 -I fm60a-kernel/check.py

仅使用 Python 标准库；通过 `git rev-parse --show-toplevel` 定位仓库根，不含任何机器绝对路径。

核对内容：
  1. classification.jsonl 与 fm60a-inventory/cases.jsonl 逐一双射（61 条齐全、类别枚举与
     kernel_digitization_status 合法）；
  2. kernel-cases.jsonl 仅包含当前受审的 9 条 v2 示范判例（schema_version="fm60a-kernel-v2"），
     legacy-v1-unreviewed.jsonl 包含其余 20 条旧格式未审查记录（schema_version="fm60a-kernel-v1"、
     exemplar=false），两者不相交且并集恰等于 classification.jsonl 的 29 条 kernel_only+both；
  3. 逐字引文（cites）：每条 quote 逐字等于 docs/chanlun/text/blog/<lesson>-*.md 对应行 char_span
     （不做字符归一化），相对准入表对象 7d0082ff 现场重算 in_admit_table / admit_id / tier，
     校验 ↑正文 界标、from_inventory 逐字一致、原清点表作者引文 100% 保留、严禁非作者入 refs；
  4. 第一层（作者陈述层 author_statements）：
     - mood 必须属于 7 值封闭枚举且非空；
     - mood 为「条件句」或「假设或反事实」时 antecedent 必填非空，其余语气必须为 null；
     - statement、antecedent 与 literal_values[*].value 中的每一个数值都必须逐字（或等价数字）
       出现在对应 refs 引文中；
     - 高风险限定词（「严格」「唯一」「必然」「已」）若出现在 statement 或 antecedent 中，
       必须也出现在对应 refs 引文中；
     - evidence_tier 与记录级 evidence_grade 按 refs 现场重算一致；
  5. 第二层（整理者建模层 organizer_models）：
     - 每条模型、每条 computable_conditions、每条 expected_under_model 都必须指向至少一条合法的
       作者陈述（depends_on_statements 非空且全合法）；
     - added_premises 与 alternative_models 必填非空；uses_premises 指向本模型合法前提；
     - 每个模型至少关联 1 条实例（无悬空模型）；
  6. 第三层（实例层 instances，全部合成）：
     - 外层 synthetic=true 且 data.synthetic=true；严禁残留旧字段 determined_by_text；
     - data 中每一个数值叶节点（vertex_prices / strengths / scalars / kbars 全部数值字段）必须且只能
       出现在 literal_bindings 或 free_parameters 之一：两者互不相交、并集不漏一数；
     - literal_bindings 必须指向作者陈述层中 binds_instance_target_literally=true 的 LV*，
       且 data 数值与 LV.value 相等；free_parameters 须带非空 note 且数值与 data 一致；
     - 反事实实例（instance_role="counterfactual"）必须填写 counterfactual_proposer
       （"author" 或 "organizer"）：写 "author" 时 counterfactual_statement_id 必填且所指作者陈述
       的 mood 必须是「假设或反事实」；写 "organizer" 时 counterfactual_statement_id 必须为 null；
     - check_conditions（含反事实覆盖）在 data 上全部机械求值为真。

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
DIG_STATUSES = {"v2_exemplar", "v1_legacy_unreviewed", "not_kernel"}
INPUT_KINDS = {
    "polyline_segments",
    "polyline_with_strength",
    "multilevel_tower_state",
    "kbar_fractal_pen",
}
ZONES = {"正文", "答疑", "课间", "解盘", "拿不准"}
TIERS = {"硬证据", "二级，未提升", "非作者，不作证据"}
SPEAKERS = {"作者", "网友", "编者"}

# 作者陈述层封闭语气枚举（7 项）
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

INSTANCE_ROLES = {"positive", "counterfactual"}
CF_PROPOSERS = {"author", "organizer"}

ALLOWED_DATA_KEYS = {
    "synthetic",
    "vertex_prices",
    "strengths",
    "scalars",
    "flags",
    "kbars",
    "segments",
    "notes",
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

CASE_V2_KEYS = [
    "schema_version",
    "case_id",
    "group",
    "category",
    "exemplar",
    "input_kind",
    "target_concepts",
    "evidence_grade",
    "base_and_pen",
    "paired_cases",
    "real_market_dependency",
    "cites",
    "author_statements",
    "organizer_models",
    "instances",
]

CITE_KEYS = [
    "cite_index",
    "lesson",
    "line",
    "speaker",
    "quote",
    "char_span",
    "zone",
    "in_admit_table",
    "admit_id",
    "tier",
    "from_inventory",
]

ZH_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
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
    """提取文本中所有数值（阿拉伯数字及简单中文数字）。"""
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
    """仅提取文本中的阿拉伯数字（供作者陈述层转写防补数核对）。"""
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


def collect_data_numeric_targets(data, tag, bad):
    """枚举 instance.data 中全部数值叶节点，杜绝任何未入账数值。"""
    targets = {}
    if not isinstance(data, dict):
        bad.append(f"{tag}: data 须为对象")
        return targets
    for k in data:
        if k not in ALLOWED_DATA_KEYS:
            bad.append(f"{tag}.data: 未登记的数据字段 {k!r}（请归入标准数据桶以免绕过数值核对）")
    for bucket in ("vertex_prices", "strengths", "scalars"):
        if bucket in data and data[bucket] is not None:
            d = data[bucket]
            if not isinstance(d, dict):
                bad.append(f"{tag}.data.{bucket}: 须为字典")
                continue
            for sym, val in d.items():
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    bad.append(f"{tag}.data.{bucket}.{sym}: 须为数值，实际 {val!r}")
                    continue
                if sym in targets:
                    bad.append(f"{tag}.data: 数值符号 {sym!r} 在多个数据桶重名")
                targets[sym] = float(val)
    if "kbars" in data and data["kbars"] is not None:
        bars = data["kbars"]
        if not isinstance(bars, list):
            bad.append(f"{tag}.data.kbars: 须为列表")
        else:
            seen_bar = set()
            for bi, b in enumerate(bars):
                if not isinstance(b, dict) or not b.get("id"):
                    bad.append(f"{tag}.data.kbars[{bi}]: 须含非空 id")
                    continue
                bid = b["id"]
                if bid in seen_bar:
                    bad.append(f"{tag}.data.kbars: 重复 bar id {bid!r}")
                seen_bar.add(bid)
                for fk, fv in b.items():
                    if fk == "id":
                        continue
                    if isinstance(fv, bool) or not isinstance(fv, (int, float)):
                        bad.append(f"{tag}.data.kbars[{bid}].{fk}: 须为数值，实际 {fv!r}")
                        continue
                    tkey = f"{bid}.{fk}"
                    targets[tkey] = float(fv)
    if "flags" in data and data["flags"] is not None:
        fl = data["flags"]
        if not isinstance(fl, dict):
            bad.append(f"{tag}.data.flags: 须为字典")
        else:
            for fk, fv in fl.items():
                if not isinstance(fv, (bool, str)):
                    bad.append(f"{tag}.data.flags.{fk}: 只允许布尔或枚举字符串，禁止藏匿数值 {fv!r}")
    return targets


# ---------------- 实例条件求值器（纯算术/序关系自检，不是缠论定义） ----------------
def _bar_map(data):
    bars = data.get("kbars") or []
    return {b["id"]: b for b in bars}


def eval_val(operand, data):
    if isinstance(operand, bool):
        raise ValueError(f"布尔值不能作为数值操作数: {operand!r}")
    if isinstance(operand, (int, float)):
        return float(operand)
    if isinstance(operand, str):
        if "." in operand:
            bid, field = operand.split(".", 1)
            bm = _bar_map(data)
            if bid not in bm or field not in bm[bid]:
                raise KeyError(f"找不到 K 线字段 {operand!r}")
            return float(bm[bid][field])
        for bucket in ("vertex_prices", "strengths", "scalars"):
            d = data.get(bucket) or {}
            if operand in d:
                return float(d[operand])
        raise KeyError(f"找不到符号 {operand!r}")
    if isinstance(operand, dict) and "fn" in operand:
        fn = operand["fn"]
        args = operand["args"]
        if fn == "sum":
            return sum(eval_val(a, data) for a in args)
        if fn == "min":
            return min(eval_val(a, data) for a in args)
        if fn == "max":
            return max(eval_val(a, data) for a in args)
        if fn == "sub":
            return eval_val(args[0], data) - eval_val(args[1], data)
        if fn == "abs_sub":
            return abs(eval_val(args[0], data) - eval_val(args[1], data))
        if fn == "len":
            key = args[0]
            if key not in data:
                raise KeyError(f"data 中无列表字段 {key!r}")
            return float(len(data[key]))
        raise ValueError(f"未知函数 {fn!r}")
    raise ValueError(f"非法操作数 {operand!r}")


def _interval_vals(iv, data):
    lo = eval_val(iv[0], data)
    hi = eval_val(iv[1], data)
    if lo > hi + EPS:
        lo, hi = hi, lo
    return lo, hi


def _bar_contains(outer, inner):
    return outer["high"] >= inner["high"] - EPS and outer["low"] <= inner["low"] + EPS


def eval_expr(expr, data):
    op = expr["op"]
    if op == "eq":
        return abs(eval_val(expr["lhs"], data) - eval_val(expr["rhs"], data)) <= EPS
    if op == "ne":
        return abs(eval_val(expr["lhs"], data) - eval_val(expr["rhs"], data)) > EPS
    if op == "lt":
        return eval_val(expr["lhs"], data) < eval_val(expr["rhs"], data) - EPS
    if op == "le":
        return eval_val(expr["lhs"], data) <= eval_val(expr["rhs"], data) + EPS
    if op == "gt":
        return eval_val(expr["lhs"], data) > eval_val(expr["rhs"], data) + EPS
    if op == "ge":
        return eval_val(expr["lhs"], data) >= eval_val(expr["rhs"], data) - EPS
    if op == "in_closed":
        v = eval_val(expr["val"], data)
        lo, hi = _interval_vals(expr["interval"], data)
        return lo - EPS <= v <= hi + EPS
    if op in ("overlap_eq", "overlap_nonempty", "overlap_empty"):
        ivs = [_interval_vals(iv, data) for iv in expr["intervals"]]
        ov_lo = max(lo for lo, _ in ivs)
        ov_hi = min(hi for _, hi in ivs)
        if op == "overlap_empty":
            return ov_lo > ov_hi + EPS
        if op == "overlap_nonempty":
            return ov_lo <= ov_hi + EPS
        exp_lo = eval_val(expr["expected"][0], data)
        exp_hi = eval_val(expr["expected"][1], data)
        return ov_lo <= ov_hi + EPS and abs(ov_lo - exp_lo) <= EPS and abs(ov_hi - exp_hi) <= EPS
    if op == "seg_alternating":
        vs = [eval_val(v, data) for v in expr["vertices"]]
        d = expr["first_dir"]
        if d not in ("up", "down"):
            raise ValueError(f"非法 first_dir: {d!r}")
        for i in range(len(vs) - 1):
            want_down = (d == "down") if (i % 2 == 0) else (d == "up")
            if want_down:
                if not (vs[i] > vs[i + 1] + EPS):
                    return False
            else:
                if not (vs[i] < vs[i + 1] - EPS):
                    return False
        return True
    if op == "kbar_valid":
        bars = data.get("kbars") or []
        if not bars:
            return False
        for b in bars:
            if b["high"] < b["low"] - EPS:
                return False
            for k in ("open", "close"):
                if k in b and not (b["low"] - EPS <= b[k] <= b["high"] + EPS):
                    return False
        return True
    if op == "kbar_contains":
        bm = _bar_map(data)
        return _bar_contains(bm[expr["outer"]], bm[expr["inner"]])
    if op == "kbar_no_inclusion":
        bm = _bar_map(data)
        ba, bb = bm[expr["a"]], bm[expr["b"]]
        return not _bar_contains(ba, bb) and not _bar_contains(bb, ba)
    if op == "kbar_bottom_fractal":
        bm = _bar_map(data)
        b1, b2, b3 = (bm[x] for x in expr["bars"])
        return (
            b2["low"] < b1["low"] - EPS
            and b2["low"] < b3["low"] - EPS
            and b2["high"] < b1["high"] - EPS
            and b2["high"] < b3["high"] - EPS
        )
    if op == "kbar_top_fractal":
        bm = _bar_map(data)
        b1, b2, b3 = (bm[x] for x in expr["bars"])
        return (
            b2["high"] > b1["high"] + EPS
            and b2["high"] > b3["high"] + EPS
            and b2["low"] > b1["low"] + EPS
            and b2["low"] > b3["low"] + EPS
        )
    if op == "flag_eq":
        flags = data.get("flags") or {}
        return flags.get(expr["key"]) == expr["value"]
    if op == "not":
        return not eval_expr(expr["arg"], data)
    if op == "and":
        return all(eval_expr(a, data) for a in expr["args"])
    if op == "or":
        return any(eval_expr(a, data) for a in expr["args"])
    raise ValueError(f"未知条件算子 {op!r}")


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
            bad.append(f"{rtag}: 禁止引用非作者（{ct['speaker']}）cite[{idx}] 作为依据")
            ok = False
        if not isinstance(lit, str) or not lit:
            bad.append(f"{rtag}: literal 须为非空字符串")
            ok = False
        elif lit not in ct["quote"]:
            bad.append(f"{rtag}: literal {lit!r} 未逐字出现在 cites[{idx}].quote 中")
            ok = False
    return ok


def walk_all_refs(obj, cites, path, bad):
    if isinstance(obj, dict):
        if "refs" in obj:
            check_refs_list(obj["refs"], cites, path, bad, require_nonempty=False)
        for k, v in obj.items():
            if k == "refs":
                continue
            walk_all_refs(v, cites, f"{path}.{k}", bad)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            walk_all_refs(item, cites, f"{path}[{i}]", bad)


def check_depends_on(dep_ids, as_map, tag, bad):
    if not isinstance(dep_ids, list) or not dep_ids:
        bad.append(f"{tag}: depends_on_statements 须为非空数组")
        return False
    ok = True
    for sid in dep_ids:
        if sid not in as_map:
            bad.append(f"{tag}: depends_on_statements 含未知作者陈述 {sid!r}")
            ok = False
    return ok


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

    # 4. 读取产物文件
    class_path = os.path.join(here, "classification.jsonl")
    kernel_path = os.path.join(here, "kernel-cases.jsonl")
    legacy_path = os.path.join(here, "legacy-v1-unreviewed.jsonl")
    for p in (class_path, kernel_path, legacy_path):
        if not os.path.exists(p):
            die(1, f"缺少产物文件：{os.path.basename(p)}")

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
            bad.append(f"classification[{cid}]: digitized_in_kernel={row['digitized_in_kernel']} 与 category={row['category']} 不符")
        if want_dig and row["kernel_digitization_status"] == "not_kernel":
            bad.append(f"classification[{cid}]: category={row['category']} 但 kernel_digitization_status=not_kernel")
        if not want_dig and row["kernel_digitization_status"] != "not_kernel":
            bad.append(f"classification[{cid}]: category={row['category']} 但 kernel_digitization_status={row['kernel_digitization_status']!r}")
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

    # 6. 核对 legacy-v1-unreviewed.jsonl（仅验隔离完整性，不对旧格式跑 v2 核对）
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
                if rec.get("schema_version") != "fm60a-kernel-v1":
                    bad.append(f"legacy[{lcid}]: 隔离文件只应含 fm60a-kernel-v1，实际 {rec.get('schema_version')!r}")
                if rec.get("exemplar") is not False:
                    bad.append(f"legacy[{lcid}]: 隔离文件只应含非示范条目（exemplar=false）")

    # 7. 核对 kernel-cases.jsonl（v2 三层格式，9 条示范判例）
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
    n_statements = 0
    n_models = 0
    n_instances = 0
    n_cf_author = 0
    n_cf_organizer = 0
    n_cond_evals = 0

    for kc in kcases:
        cid = kc.get("case_id", "?")
        miss = [k for k in CASE_V2_KEYS if k not in kc]
        if miss:
            bad.append(f"{cid}: 缺顶层字段 {miss}")
            continue
        if cid in seen_k:
            bad.append(f"{cid}: case_id 重复")
        seen_k.add(cid)
        if kc["schema_version"] != "fm60a-kernel-v2":
            bad.append(f"{cid}: schema_version 须为 'fm60a-kernel-v2'，实际 {kc['schema_version']!r}")
        if kc["exemplar"] is not True:
            bad.append(f"{cid}: 当前 kernel-cases.jsonl 仅收示范判例（exemplar=true）")
        if kc["category"] not in ("kernel_only", "both"):
            bad.append(f"{cid}: category 非法 {kc['category']!r}")
        if cid in cls_by_id and kc["category"] != cls_by_id[cid]["category"]:
            bad.append(f"{cid}: category 与 classification.jsonl 不一致")
        if cid in inv and kc["group"] != inv[cid]["group"]:
            bad.append(f"{cid}: group 与清点表不一致")
        if kc["input_kind"] not in INPUT_KINDS:
            bad.append(f"{cid}: input_kind 非法 {kc['input_kind']!r}")
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

        # 确认原清点表作者引文 100% 保留
        if cid in inv:
            kept = {(ct["lesson"], ct["line"], tuple(ct["char_span"])) for ct in cites}
            for ict in inv[cid]["cites"]:
                if ict["speaker"] == "作者":
                    key = (ict["lesson"], ict["line"], tuple(ict["char_span"]))
                    if key not in kept:
                        bad.append(f"{cid}: 遗漏了清点表原作者引文 {ict['lesson']}:{ict['line']}{ict['char_span']}")

        # 递归检查所有 refs
        walk_all_refs(kc, cites, cid, bad)

        # 7b. 第一层：作者陈述层 author_statements
        statements = kc["author_statements"]
        if not isinstance(statements, list) or not statements:
            bad.append(f"{cid}: author_statements 不能为空")
            continue
        as_map = {}
        lv_global = {}  # value_id -> (statement_id, lv_obj)
        all_as_refs = []
        for j, st in enumerate(statements):
            sid = st.get("statement_id", f"#{j}")
            tag = f"{cid}.author_statements[{sid}]"
            for req in ("statement_id", "mood", "antecedent", "statement", "literal_values", "evidence_tier", "refs"):
                if req not in st:
                    bad.append(f"{tag}: 缺字段 {req}")
            if any(req not in st for req in ("statement_id", "mood", "antecedent", "statement", "literal_values", "evidence_tier", "refs")):
                continue
            if sid in as_map:
                bad.append(f"{tag}: statement_id 重复")
            as_map[sid] = st
            mood = st["mood"]
            if not isinstance(mood, str) or mood not in MOODS:
                bad.append(f"{tag}: mood 非法或为空 {mood!r}（合法枚举：{sorted(MOODS)}）")
            ant = st["antecedent"]
            if mood in CONDITIONAL_MOODS:
                if not isinstance(ant, str) or not ant.strip():
                    bad.append(f"{tag}: mood={mood!r} 必须填写非空 antecedent 保留原条件")
            else:
                if ant is not None:
                    bad.append(f"{tag}: mood={mood!r} 时 antecedent 应为 null（若为条件句请改 mood）")
            stmt_text = st["statement"]
            if not isinstance(stmt_text, str) or not stmt_text.strip():
                bad.append(f"{tag}: statement 不能为空")
            refs_ok = check_refs_list(st["refs"], cites, tag, bad, require_nonempty=True)
            if refs_ok:
                want_tier = compute_tier_from_refs(st["refs"], cites)
                if st["evidence_tier"] != want_tier:
                    bad.append(f"{tag}: evidence_tier={st['evidence_tier']!r} 现算 {want_tier!r}")
                all_as_refs.extend(st["refs"])
                refs_concat = "".join(r["literal"] for r in st["refs"])
                # 核对 statement / antecedent 中每一个阿拉伯数值均出现在 refs 引文中
                for fname, ftxt in (("statement", stmt_text), ("antecedent", ant or "")):
                    for raw_num, fval in extract_arabic_numbers(ftxt):
                        if not num_in_refs(fval, st["refs"]):
                            bad.append(f"{tag}.{fname}: 含数值 {raw_num!r} 未出现在 refs 引文中")
                    # 核对高风险未引限定词不得私自加入
                    for q in FORBIDDEN_UNQUOTED_QUALIFIERS:
                        if q in ftxt and q not in refs_concat:
                            bad.append(f"{tag}.{fname}: 含引文未出现的限定词 {q!r}")
            # 核对 literal_values
            lvs = st["literal_values"]
            if not isinstance(lvs, list):
                bad.append(f"{tag}: literal_values 须为数组")
            else:
                for lvi, lv in enumerate(lvs):
                    lvtag = f"{tag}.literal_values[{lvi}]"
                    for req in ("value_id", "value", "unit_or_role", "author_target", "binds_instance_target_literally"):
                        if req not in lv:
                            bad.append(f"{lvtag}: 缺字段 {req}")
                    if any(req not in lv for req in ("value_id", "value", "unit_or_role", "author_target", "binds_instance_target_literally")):
                        continue
                    vid = lv["value_id"]
                    if vid in lv_global:
                        bad.append(f"{lvtag}: value_id {vid!r} 在本判例内重复")
                    lv_global[vid] = (sid, lv)
                    if isinstance(lv["value"], bool) or not isinstance(lv["value"], (int, float)):
                        bad.append(f"{lvtag}: value 须为数值，实际 {lv['value']!r}")
                    elif refs_ok and not num_in_refs(lv["value"], st["refs"]):
                        bad.append(f"{lvtag}: literal value {lv['value']} 未出现在 refs 引文中")
                    if not isinstance(lv["binds_instance_target_literally"], bool):
                        bad.append(f"{lvtag}: binds_instance_target_literally 须为布尔值")
                    if not lv.get("unit_or_role") or not lv.get("author_target"):
                        bad.append(f"{lvtag}: unit_or_role 与 author_target 均不能为空")
            n_statements += 1

        if all_as_refs:
            want_grade = compute_tier_from_refs(all_as_refs, cites)
            if kc["evidence_grade"] != want_grade:
                bad.append(f"{cid}: evidence_grade={kc['evidence_grade']!r} 现算 {want_grade!r}")

        # 7c. 第二层：整理者建模层 organizer_models
        models = kc["organizer_models"]
        if not isinstance(models, list) or not models:
            bad.append(f"{cid}: organizer_models 不能为空")
            continue
        model_map = {}
        model_conds = {}
        model_expects = {}
        for mi, md in enumerate(models):
            mid = md.get("model_id", f"#{mi}")
            tag = f"{cid}.organizer_models[{mid}]"
            req_m = (
                "model_id", "title", "reading_group", "depends_on_statements",
                "symbol_schema", "added_premises", "alternative_models",
                "computable_conditions", "expected_under_model",
            )
            miss_m = [k for k in req_m if k not in md]
            if miss_m:
                bad.append(f"{tag}: 缺字段 {miss_m}")
                continue
            if mid in model_map:
                bad.append(f"{tag}: model_id 重复")
            model_map[mid] = md
            check_depends_on(md["depends_on_statements"], as_map, tag, bad)
            if not md.get("title") or not md.get("reading_group"):
                bad.append(f"{tag}: title 与 reading_group 不能为空")
            if not isinstance(md["symbol_schema"], dict) or md["symbol_schema"].get("domain") != kc["input_kind"]:
                bad.append(f"{tag}.symbol_schema: domain 须等于 input_kind ({kc['input_kind']!r})")
            # added_premises
            prems = md["added_premises"]
            prem_ids = set()
            if not isinstance(prems, list) or not prems:
                bad.append(f"{tag}: added_premises 须为非空数组")
            else:
                for pi, pr in enumerate(prems):
                    ptag = f"{tag}.added_premises[{pi}]"
                    if not isinstance(pr, dict) or not pr.get("premise_id") or not pr.get("category") or not pr.get("statement"):
                        bad.append(f"{ptag}: 须含非空 premise_id / category / statement")
                        continue
                    if pr["premise_id"] in prem_ids:
                        bad.append(f"{ptag}: premise_id {pr['premise_id']!r} 重复")
                    prem_ids.add(pr["premise_id"])
            # alternative_models
            alts = md["alternative_models"]
            if not isinstance(alts, list) or not alts or any(not isinstance(a, str) or not a.strip() for a in alts):
                bad.append(f"{tag}: alternative_models 须为非空字符串数组")
            # computable_conditions
            conds = md["computable_conditions"]
            cmap = {}
            if not isinstance(conds, list) or not conds:
                bad.append(f"{tag}: computable_conditions 不能为空")
            else:
                for ci, co in enumerate(conds):
                    cid_co = co.get("cond_id", f"#{ci}")
                    ctag = f"{tag}.computable_conditions[{cid_co}]"
                    for req in ("cond_id", "depends_on_statements", "uses_premises", "description", "expr"):
                        if req not in co:
                            bad.append(f"{ctag}: 缺字段 {req}")
                    if any(req not in co for req in ("cond_id", "depends_on_statements", "uses_premises", "description", "expr")):
                        continue
                    if cid_co in cmap:
                        bad.append(f"{ctag}: cond_id 重复")
                    cmap[cid_co] = co
                    check_depends_on(co["depends_on_statements"], as_map, ctag, bad)
                    if not isinstance(co["uses_premises"], list):
                        bad.append(f"{ctag}: uses_premises 须为数组")
                    else:
                        for pid in co["uses_premises"]:
                            if pid not in prem_ids:
                                bad.append(f"{ctag}: uses_premises 含未知前提 {pid!r}")
                    if not co.get("description"):
                        bad.append(f"{ctag}: description 不能为空")
            model_conds[mid] = cmap
            # expected_under_model
            exps = md["expected_under_model"]
            emap = {}
            if not isinstance(exps, list) or not exps:
                bad.append(f"{tag}: expected_under_model 不能为空")
            else:
                for ei, ex in enumerate(exps):
                    eid = ex.get("expect_id", f"#{ei}")
                    etag = f"{tag}.expected_under_model[{eid}]"
                    for req in ("expect_id", "depends_on_statements", "uses_premises", "subject", "expected", "compatibility_note"):
                        if req not in ex:
                            bad.append(f"{etag}: 缺字段 {req}")
                    if any(req not in ex for req in ("expect_id", "depends_on_statements", "uses_premises", "subject", "expected", "compatibility_note")):
                        continue
                    if eid in emap:
                        bad.append(f"{etag}: expect_id 重复")
                    emap[eid] = ex
                    check_depends_on(ex["depends_on_statements"], as_map, etag, bad)
                    if not isinstance(ex["uses_premises"], list):
                        bad.append(f"{etag}: uses_premises 须为数组")
                    else:
                        for pid in ex["uses_premises"]:
                            if pid not in prem_ids:
                                bad.append(f"{etag}: uses_premises 含未知前提 {pid!r}")
                    if not ex.get("subject") or not isinstance(ex.get("expected"), dict) or not ex.get("compatibility_note"):
                        bad.append(f"{etag}: subject / expected(dict) / compatibility_note 不能为空")
            model_expects[mid] = emap
            n_models += 1

        # 7d. 第三层：实例层 instances（全部合成）
        insts = kc["instances"]
        if not isinstance(insts, list) or not insts:
            bad.append(f"{cid}: instances 不能为空")
            continue
        seen_inst = set()
        used_models = set()
        for ii, ins in enumerate(insts):
            iid = ins.get("instance_id", f"#{ii}")
            tag = f"{cid}.instances[{iid}]"
            if "determined_by_text" in ins:
                bad.append(f"{tag}: v2 严禁存在中间态字段 determined_by_text")
            req_i = (
                "instance_id", "model_id", "synthetic", "instance_role",
                "counterfactual_proposer", "counterfactual_statement_id",
                "counterfactual_rationale", "expected_under_instance",
                "data", "literal_bindings", "free_parameters", "check_conditions",
            )
            miss_i = [k for k in req_i if k not in ins]
            if miss_i:
                bad.append(f"{tag}: 缺字段 {miss_i}")
                continue
            if iid in seen_inst:
                bad.append(f"{tag}: instance_id 重复")
            seen_inst.add(iid)
            mid = ins["model_id"]
            if mid not in model_map:
                bad.append(f"{tag}: model_id={mid!r} 不在 organizer_models 中")
                continue
            used_models.add(mid)
            if ins["synthetic"] is not True:
                bad.append(f"{tag}: 外层 synthetic 必须为 true")
            idata = ins["data"]
            if not isinstance(idata, dict) or idata.get("synthetic") is not True:
                bad.append(f"{tag}: data.synthetic 必须显式为 true")

            role = ins["instance_role"]
            if role not in INSTANCE_ROLES:
                bad.append(f"{tag}: instance_role 非法 {role!r}")
            prop = ins["counterfactual_proposer"]
            cf_sid = ins["counterfactual_statement_id"]
            cf_rat = ins["counterfactual_rationale"]
            overrides = ins.get("condition_overrides") or {}
            if not isinstance(overrides, dict):
                bad.append(f"{tag}: condition_overrides 须为对象")
                overrides = {}

            if role == "positive":
                if prop is not None:
                    bad.append(f"{tag}: positive 实例的 counterfactual_proposer 须为 null")
                if cf_sid is not None:
                    bad.append(f"{tag}: positive 实例的 counterfactual_statement_id 须为 null")
                if cf_rat is not None:
                    bad.append(f"{tag}: positive 实例的 counterfactual_rationale 须为 null")
                if overrides:
                    bad.append(f"{tag}: positive 实例不允许使用 condition_overrides")
                eui = ins["expected_under_instance"]
                if not isinstance(eui, list) or not eui:
                    bad.append(f"{tag}: positive 实例的 expected_under_instance 须为非空 expect_id 列表")
                else:
                    for eid in eui:
                        if eid not in model_expects[mid]:
                            bad.append(f"{tag}: expected_under_instance 含未知 expect_id {eid!r}")
            elif role == "counterfactual":
                if prop not in CF_PROPOSERS:
                    bad.append(f"{tag}: 反事实实例 counterfactual_proposer 必填且须为 'author' 或 'organizer'，实际 {prop!r}")
                if not isinstance(cf_rat, str) or not cf_rat.strip():
                    bad.append(f"{tag}: 反事实实例 counterfactual_rationale 不能为空")
                if prop == "author":
                    n_cf_author += 1
                    if not isinstance(cf_sid, str) or cf_sid not in as_map:
                        bad.append(f"{tag}: counterfactual_proposer='author' 时 counterfactual_statement_id 必须指向合法作者陈述，实际 {cf_sid!r}")
                    elif as_map[cf_sid]["mood"] != "假设或反事实":
                        bad.append(
                            f"{tag}: counterfactual_proposer='author' 指向 {cf_sid}，"
                            f"但其 mood={as_map[cf_sid]['mood']!r} != '假设或反事实'"
                        )
                elif prop == "organizer":
                    n_cf_organizer += 1
                    if cf_sid is not None:
                        bad.append(f"{tag}: counterfactual_proposer='organizer' 时 counterfactual_statement_id 须为 null")
                eui = ins["expected_under_instance"]
                if not isinstance(eui, dict) or not eui.get("scope_note") or not isinstance(eui.get("expected"), dict):
                    bad.append(f"{tag}: counterfactual 实例的 expected_under_instance 须为含 scope_note 与 expected(dict) 的对象")

            # 核对 data 全部数值在 literal_bindings 与 free_parameters 间严格二分（不重不漏）
            all_targets = collect_data_numeric_targets(idata, tag, bad)
            lit_targets = set()
            free_targets = set()

            lbinds = ins["literal_bindings"]
            if not isinstance(lbinds, list):
                bad.append(f"{tag}: literal_bindings 须为数组")
            else:
                for li, lb in enumerate(lbinds):
                    ltag = f"{tag}.literal_bindings[{li}]"
                    for req in ("target", "value", "statement_id", "value_id"):
                        if req not in lb:
                            bad.append(f"{ltag}: 缺字段 {req}")
                    if any(req not in lb for req in ("target", "value", "statement_id", "value_id")):
                        continue
                    tgt = lb["target"]
                    if tgt in lit_targets:
                        bad.append(f"{ltag}: target {tgt!r} 重复")
                    lit_targets.add(tgt)
                    sid = lb["statement_id"]
                    vid = lb["value_id"]
                    if sid not in as_map:
                        bad.append(f"{ltag}: statement_id={sid!r} 不存在")
                    elif vid not in lv_global or lv_global[vid][0] != sid:
                        bad.append(f"{ltag}: {sid} 中不存在 literal value {vid!r}")
                    else:
                        lv_obj = lv_global[vid][1]
                        if lv_obj["binds_instance_target_literally"] is not True:
                            bad.append(
                                f"{ltag}: {sid}.{vid} 的 binds_instance_target_literally=false"
                                f"（原文未字面指定所指字段），不得放入 literal_bindings，请移入 free_parameters"
                            )
                        if abs(float(lb["value"]) - float(lv_obj["value"])) > EPS:
                            bad.append(f"{ltag}: value={lb['value']} != {sid}.{vid}.value={lv_obj['value']}")
                    if tgt not in all_targets:
                        bad.append(f"{ltag}: target {tgt!r} 不在 data 数值集合中")
                    elif abs(all_targets[tgt] - float(lb["value"])) > EPS:
                        bad.append(f"{ltag}: data[{tgt}]={all_targets[tgt]} != value={lb['value']}")

            fparams = ins["free_parameters"]
            if not isinstance(fparams, list):
                bad.append(f"{tag}: free_parameters 须为数组")
            else:
                for fi, fp in enumerate(fparams):
                    ftag = f"{tag}.free_parameters[{fi}]"
                    for req in ("target", "value", "note"):
                        if req not in fp:
                            bad.append(f"{ftag}: 缺字段 {req}")
                    if any(req not in fp for req in ("target", "value", "note")):
                        continue
                    tgt = fp["target"]
                    if tgt in free_targets:
                        bad.append(f"{ftag}: target {tgt!r} 重复")
                    free_targets.add(tgt)
                    if not isinstance(fp["note"], str) or not fp["note"].strip():
                        bad.append(f"{ftag}: note 不能为空")
                    if tgt not in all_targets:
                        bad.append(f"{ftag}: target {tgt!r} 不在 data 数值集合中")
                    elif abs(all_targets[tgt] - float(fp["value"])) > EPS:
                        bad.append(f"{ftag}: data[{tgt}]={all_targets[tgt]} != value={fp['value']}")

            overlap_t = sorted(lit_targets & free_targets)
            if overlap_t:
                bad.append(f"{tag}: literal_bindings 与 free_parameters 重叠：{overlap_t}")
            missing_t = sorted(set(all_targets.keys()) - (lit_targets | free_targets))
            if missing_t:
                bad.append(f"{tag}: data 中以下数值既不在 literal_bindings 也不在 free_parameters：{missing_t}")

            # 核对 check_conditions
            cmap = model_conds[mid]
            cconds = ins["check_conditions"]
            if not isinstance(cconds, list) or not cconds:
                bad.append(f"{tag}: check_conditions 不能为空")
            else:
                for ok_cid in overrides:
                    if ok_cid not in cmap:
                        bad.append(f"{tag}: condition_overrides 含未知条件 {ok_cid!r}")
                    elif ok_cid not in cconds:
                        bad.append(f"{tag}: condition_overrides 覆盖了未列入 check_conditions 的 {ok_cid!r}")
                for co_id in cconds:
                    if co_id not in cmap:
                        bad.append(f"{tag}: check_conditions 含未知条件 {co_id!r}")
                        continue
                    expr = overrides.get(co_id, cmap[co_id]["expr"])
                    try:
                        res = eval_expr(expr, idata)
                    except (KeyError, ValueError, TypeError) as e:
                        bad.append(f"{tag}: 条件 {co_id} 求值出错：{e}")
                        continue
                    n_cond_evals += 1
                    if not res:
                        bad.append(f"{tag}: 条件 {co_id} 在合成数据上不成立（expr={expr}）")
            n_instances += 1

        # 检查无悬空模型
        unused_m = sorted(set(model_map.keys()) - used_models)
        if unused_m:
            bad.append(f"{cid}: 以下 organizer_models 缺少对应实例：{unused_m}")

        # real_market_dependency
        rmd = kc["real_market_dependency"]
        if not isinstance(rmd, dict) or rmd.get("needs_historical_data_for_kernel") is not False or not rmd.get("historical_data_meaning"):
            bad.append(f"{cid}: real_market_dependency 字段不完整或 needs_historical_data_for_kernel 不为 false")

    # 8. 核对 classification / kernel-cases (v2) / legacy-v1-unreviewed 三方对齐
    want_v2_ids = {r["case_id"] for r in cls_rows if r["kernel_digitization_status"] == "v2_exemplar"}
    want_legacy_ids = {r["case_id"] for r in cls_rows if r["kernel_digitization_status"] == "v1_legacy_unreviewed"}
    if seen_k & legacy_ids:
        bad.append(f"kernel-cases.jsonl 与 legacy-v1-unreviewed.jsonl 存在重叠：{sorted(seen_k & legacy_ids)}")
    if seen_k != want_v2_ids:
        bad.append(f"kernel-cases.jsonl 与 classification(v2_exemplar) 不一致：漏 {sorted(want_v2_ids - seen_k)}，多 {sorted(seen_k - want_v2_ids)}")
    if legacy_ids != want_legacy_ids:
        bad.append(f"legacy-v1-unreviewed.jsonl 与 classification(v1_legacy_unreviewed) 不一致：漏 {sorted(want_legacy_ids - legacy_ids)}，多 {sorted(legacy_ids - want_legacy_ids)}")

    if bad:
        print(f"FAIL: 共 {len(bad)} 处不符：", file=sys.stderr)
        for m in bad:
            print(" -", m, file=sys.stderr)
        sys.exit(1)

    cat_cnt = Counter(r["category"] for r in cls_rows)
    grade_cnt = Counter(k["evidence_grade"] for k in kcases)
    print(
        f"OK: classification={len(cls_rows)} 条 "
        f"(kernel_only={cat_cnt['kernel_only']}, market_only={cat_cnt['market_only']}, "
        f"both={cat_cnt['both']}, unusable={cat_cnt['unusable']}) | "
        f"v2示范={len(kcases)} 条 | 旧格式隔离未审={len(legacy_ids)} 条 | "
        f"cites={n_cites} | 作者陈述={n_statements} | 整理者建模={n_models} | "
        f"合成实例={n_instances} (作者反事实={n_cf_author}, 整理者反事实={n_cf_organizer}) | "
        f"条件求值通过={n_cond_evals} | 证据等级={dict(grade_cnt)}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
