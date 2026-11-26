#!/usr/bin/env python3
"""FM-60a 内核判例数字化（#2324）机械核对脚本。

用法（仓库内任意目录）：
    python3 -I fm60a-kernel/check.py

仅使用 Python 标准库；通过 `git rev-parse --show-toplevel` 定位仓库根，不含任何机器绝对路径。

核对内容：
  1. classification.jsonl 与 fm60a-inventory/cases.jsonl 逐一双射（61 条齐全、无重复、类别枚举合法），
     且 kernel_only + both 集合与 kernel-cases.jsonl 的 case_id 集合完全一致；
  2. kernel-cases.jsonl 每条记录字段齐全、枚举合法、case_id 唯一；
  3. 每条 cite 的 quote 逐字等于语料 docs/chanlun/text/blog/<lesson>-*.md 对应行 char_span 处的字符
     （不做任何字符归一化）；
  4. 每条 cite 的 in_admit_table / admit_id / tier 与准入表 git 对象
     `7d0082ff6f8b1d7d9b7b98eb24712723d0a95d9c:formal_math/sources/admit/candidate/tier1_candidate.jsonl`
     现场重算完全一致（取不到准入表即退 2，绝不静默跳过）；
  5. zone 与「↑正文」界标一致；from_inventory=true 的 cite 与清点表逐字一致；
  6. 递归扫描每条记录中全部 refs：指向有效 cite、speaker 必须为「作者」（严禁网友/编者作证据）、
     ref.literal 必须逐字出现在对应 cite.quote 中；
  7. 非合成区（structure_spec、assertions、counterfactuals、literal_facts）及合成区 locked_values 中的
     每一个字面数值，都必须能在其所引原文 refs 的 literal 文本中以等值数字出现（防静默补数）；
  8. 每条 assertion 的 evidence_tier 与整条判例的 evidence_grade 按其引用 cite 现场重算一致；
  9. 每个合成见证（synthetic_witnesses）必须显式标记 synthetic=true，写清 determined_by_text、
     free_parameters 与 freedom_justification，locked_values 与 data 中数值逐项一致，且
     check_constraints 中的每条约束在 data 上求值全为真（对 counterfactual 变体核对替换后的约束）。

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
INPUT_KINDS = {
    "polyline_segments",
    "polyline_with_strength",
    "multilevel_tower_state",
    "kbar_fractal_pen",
}
ZONES = {"正文", "答疑", "课间", "解盘", "拿不准"}
TIERS = {"硬证据", "二级，未提升", "非作者，不作证据"}
SPEAKERS = {"作者", "网友", "编者"}
PROVENANCES = {"literal", "derived_from_text", "structural_default"}
FREEDOM_MODES = {
    "order_invariant",
    "multi_instance_coverage",
    "order_invariant_plus_multi_instance",
    "explicit_freedom_documented",
}

CLASS_KEYS = [
    "case_id",
    "group",
    "category",
    "digitized_in_kernel",
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
    "input_kind",
    "target_concepts",
    "evidence_grade",
    "base_and_pen",
    "paired_cases",
    "cites",
    "literal_facts",
    "structure_spec",
    "assertions",
    "counterfactuals",
    "synthetic_witnesses",
    "interpretive_choices",
    "real_market_dependency",
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

NUM_RE = re.compile(r"(?<![A-Za-z0-9_])(?:\d+(?:\.\d+)?)(?![A-Za-z0-9_])")
# 文本中汉字紧邻数字（如「4087到4122点」「5分钟」「3个中枢」「9段」「5386.47比」）
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
    """从原文片段中提取所有字面出现的数值集合（含简单中文数字如「三」「两」「一」「四」「九」）。"""
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


def num_in_refs(num, refs, cites):
    """检查数字 num 是否作为字面数值出现在 refs 指向的 literal 文本中。"""
    target = float(num)
    for r in refs:
        lit = r.get("literal", "")
        for cand in extract_numbers_from_text(lit):
            if abs(cand - target) <= EPS:
                return True
    return False


def collect_numeric_literals_from_expr(expr):
    """收集约束表达式里的裸数字常量（用于 provenance='literal' 的防补数核对）。"""
    out = []
    if isinstance(expr, bool):
        return out
    if isinstance(expr, (int, float)):
        out.append(expr)
    elif isinstance(expr, list):
        for x in expr:
            out.extend(collect_numeric_literals_from_expr(x))
    elif isinstance(expr, dict):
        for k, v in expr.items():
            if k in ("op", "fn", "key", "first_dir", "outer", "inner", "a", "b", "bars"):
                continue
            out.extend(collect_numeric_literals_from_expr(v))
    return out


# ---------------- 合成见证约束求值器（纯算术/序关系核对，不是缠论定义） ----------------
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
    raise ValueError(f"未知约束算子 {op!r}")


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
        if not isinstance(idx, int) or not (0 <= idx < len(cites)):
            bad.append(f"{rtag}: cite 索引越界 {idx!r}")
            ok = False
            continue
        ct = cites[idx]
        if ct["speaker"] != "作者":
            bad.append(f"{rtag}: 禁止引用非作者（{ct['speaker']}）cite[{idx}] 作为结构或断言依据")
            ok = False
        if not isinstance(lit, str) or not lit:
            bad.append(f"{rtag}: literal 须为非空字符串")
            ok = False
        elif lit not in ct["quote"]:
            bad.append(f"{rtag}: literal {lit!r} 未逐字出现在 cites[{idx}].quote 中")
            ok = False
    return ok


def walk_all_refs(obj, cites, path, bad):
    """递归检查整条记录内出现的所有 refs 字段，杜绝遗漏的悬空或非作者引用。"""
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
    for p in (class_path, kernel_path):
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
        if not isinstance(row["digitized_in_kernel"], bool):
            bad.append(f"classification[{cid}]: digitized_in_kernel 须为布尔值")
        want_dig = row["category"] in ("kernel_only", "both")
        if row["digitized_in_kernel"] != want_dig:
            bad.append(f"classification[{cid}]: digitized_in_kernel={row['digitized_in_kernel']} 与 category={row['category']} 不符")
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

    # 6. 核对 kernel-cases.jsonl
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
    n_assertions = 0
    n_witnesses = 0
    n_constraint_evals = 0
    n_counterfactuals = 0

    for kc in kcases:
        cid = kc.get("case_id", "?")
        miss = [k for k in CASE_KEYS if k not in kc]
        if miss:
            bad.append(f"{cid}: 缺字段 {miss}")
            continue
        if cid in seen_k:
            bad.append(f"{cid}: case_id 重复")
        seen_k.add(cid)
        if kc["schema_version"] != "fm60a-kernel-v1":
            bad.append(f"{cid}: schema_version 非法 {kc['schema_version']!r}")
        if kc["category"] not in ("kernel_only", "both"):
            bad.append(f"{cid}: kernel-cases 中只应含 kernel_only/both，实际 {kc['category']!r}")
        if cid in cls_by_id and kc["category"] != cls_by_id[cid]["category"]:
            bad.append(f"{cid}: category 与 classification.jsonl 不一致")
        if cid in inv and kc["group"] != inv[cid]["group"]:
            bad.append(f"{cid}: group 与清点表不一致")
        if kc["input_kind"] not in INPUT_KINDS:
            bad.append(f"{cid}: input_kind 非法 {kc['input_kind']!r}")
        if not isinstance(kc["exemplar"], bool):
            bad.append(f"{cid}: exemplar 须为布尔值")
        if not isinstance(kc["target_concepts"], list) or not kc["target_concepts"]:
            bad.append(f"{cid}: target_concepts 须为非空数组")

        # 6a. 核对 cites
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
            # 准入表重算
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
            # 界标检查
            m = marker(k)
            if ct["zone"] == "正文":
                if m is None or n >= m:
                    bad.append(f"{tag}: zone=正文 但 {k}:{n} 不在 ↑正文 界标（{m}）之前")
            elif m is not None and n < m and ct["speaker"] == "作者":
                bad.append(f"{tag}: zone={ct['zone']!r} 但作者行 {k}:{n} 在 ↑正文 界标（{m}）之前")
            if want_tier == "硬证据" and ct["zone"] != "正文":
                bad.append(f"{tag}: 硬证据但 zone 不是正文")
            n_cites += 1

        # 确认清点表里的所有作者 cite 都被保留（不丢原清点证据）
        if cid in inv:
            kept = {(ct["lesson"], ct["line"], tuple(ct["char_span"])) for ct in cites}
            for ict in inv[cid]["cites"]:
                if ict["speaker"] == "作者":
                    key = (ict["lesson"], ict["line"], tuple(ict["char_span"]))
                    if key not in kept:
                        bad.append(f"{cid}: 遗漏了清点表原作者引文 {ict['lesson']}:{ict['line']}{ict['char_span']}")

        # 6b. 递归核对全记录 refs
        walk_all_refs(kc, cites, cid, bad)

        # 6c. literal_facts
        lfacts = kc["literal_facts"]
        if not isinstance(lfacts, list) or not lfacts:
            bad.append(f"{cid}: literal_facts 不能为空")
        for j, lf in enumerate(lfacts):
            tag = f"{cid}.literal_facts[{j}]"
            for k in ("fact_id", "kind", "statement", "refs"):
                if k not in lf:
                    bad.append(f"{tag}: 缺字段 {k}")
            check_refs_list(lf.get("refs"), cites, tag, bad, require_nonempty=True)

        # 6d. structure_spec & constraints
        spec = kc["structure_spec"]
        if not isinstance(spec, dict) or spec.get("domain") != kc["input_kind"]:
            bad.append(f"{cid}.structure_spec: domain 须等于 input_kind ({kc['input_kind']!r})")
        constraints = spec.get("constraints") or []
        if not constraints:
            bad.append(f"{cid}.structure_spec: constraints 不能为空")
        cmap = {}
        for j, con in enumerate(constraints):
            tag = f"{cid}.constraints[{j}]"
            for k in ("id", "expr", "provenance", "refs"):
                if k not in con:
                    bad.append(f"{tag}: 缺字段 {k}")
                    continue
            if con["id"] in cmap:
                bad.append(f"{tag}: 约束 id 重复 {con['id']!r}")
            cmap[con["id"]] = con
            prov = con.get("provenance")
            if prov not in PROVENANCES:
                bad.append(f"{tag}: provenance 非法 {prov!r}")
            if prov in ("literal", "derived_from_text"):
                check_refs_list(con.get("refs"), cites, tag, bad, require_nonempty=True)
            if prov == "derived_from_text" and not con.get("rationale"):
                bad.append(f"{tag}: derived_from_text 必须带 rationale")
            if prov == "literal":
                # 严防在 literal 约束中夹带未出现在原文的数值
                for num in collect_numeric_literals_from_expr(con["expr"]):
                    if not num_in_refs(num, con["refs"], cites):
                        bad.append(f"{tag}: literal 约束含数值 {num}，但未出现在其 refs 原文中")

        # 检查 vertices/kbars 中的字面价格或字面值必须出现在 refs
        for j, vtx in enumerate(spec.get("vertices") or []):
            tag = f"{cid}.vertices[{j}]"
            if vtx.get("literal_price") is not None:
                if check_refs_list(vtx.get("refs"), cites, tag, bad, require_nonempty=True):
                    if not num_in_refs(vtx["literal_price"], vtx["refs"], cites):
                        bad.append(f"{tag}: literal_price={vtx['literal_price']} 未出现在其 refs 原文中")
        for j, kb in enumerate(spec.get("kbars") or []):
            tag = f"{cid}.kbars[{j}]"
            for fld in ("literal_high", "literal_low"):
                if kb.get(fld) is not None:
                    if check_refs_list(kb.get("refs"), cites, tag, bad, require_nonempty=True):
                        if not num_in_refs(kb[fld], kb["refs"], cites):
                            bad.append(f"{tag}: {fld}={kb[fld]} 未出现在其 refs 原文中")

        # 6e. assertions 与 evidence_grade 重算
        assertions = kc["assertions"]
        if not isinstance(assertions, list) or not assertions:
            bad.append(f"{cid}: assertions 不能为空")
        all_assert_refs = []
        assert_ids = set()
        for j, a in enumerate(assertions):
            tag = f"{cid}.assertions[{j}]"
            for k in ("id", "kind", "subject", "expected", "evidence_tier", "refs"):
                if k not in a:
                    bad.append(f"{tag}: 缺字段 {k}")
                    continue
            if a["id"] in assert_ids:
                bad.append(f"{tag}: assertion id 重复 {a['id']!r}")
            assert_ids.add(a["id"])
            if check_refs_list(a["refs"], cites, tag, bad, require_nonempty=True):
                want_at = compute_tier_from_refs(a["refs"], cites)
                if a["evidence_tier"] != want_at:
                    bad.append(f"{tag}: evidence_tier={a['evidence_tier']!r} 现算 {want_at!r}")
                all_assert_refs.extend(a["refs"])
                # 递归检查 assertions.expected / subject 里的所有字面数值是否均出现在 refs 中
                for box_name in ("subject", "expected"):
                    for num in collect_numeric_literals_from_expr(a[box_name]):
                        if not num_in_refs(num, a["refs"], cites):
                            bad.append(f"{tag}.{box_name} 含数值 {num} 未出现在其 refs 原文中")
            n_assertions += 1

        if all_assert_refs:
            want_grade = compute_tier_from_refs(all_assert_refs, cites)
            if kc["evidence_grade"] != want_grade:
                bad.append(f"{cid}: evidence_grade={kc['evidence_grade']!r} 现算 {want_grade!r}")

        # 6f. counterfactuals
        cf_map = {}
        for j, cf in enumerate(kc["counterfactuals"]):
            tag = f"{cid}.counterfactuals[{j}]"
            for k in ("id", "description", "replace_constraints", "expected_change", "evidence_tier", "refs"):
                if k not in cf:
                    bad.append(f"{tag}: 缺字段 {k}")
                    continue
            cf_map[cf["id"]] = cf
            if check_refs_list(cf["refs"], cites, tag, bad, require_nonempty=True):
                want_ct = compute_tier_from_refs(cf["refs"], cites)
                if cf["evidence_tier"] != want_ct:
                    bad.append(f"{tag}: evidence_tier={cf['evidence_tier']!r} 现算 {want_ct!r}")
            for rc in cf.get("replace_constraints") or []:
                if rc.get("target") not in cmap:
                    bad.append(f"{tag}: replace_constraints.target={rc.get('target')!r} 不在 constraints 中")
            n_counterfactuals += 1

        # 6g. synthetic_witnesses 标记 + locked_values + 约束求值
        wits = kc["synthetic_witnesses"]
        if not isinstance(wits, list) or not wits:
            bad.append(f"{cid}: synthetic_witnesses 不能为空")
        for j, w in enumerate(wits):
            tag = f"{cid}.synthetic_witnesses[{j}]({w.get('witness_id','?')})"
            for k in (
                "witness_id", "synthetic", "variant", "covers_assertion_ids",
                "determined_by_text", "free_parameters", "freedom_justification",
                "locked_values", "data", "check_constraints",
            ):
                if k not in w:
                    bad.append(f"{tag}: 缺字段 {k}")
                    continue
            if w.get("synthetic") is not True:
                bad.append(f"{tag}: 合成见证必须显式标记 synthetic=true")
            if not w.get("determined_by_text"):
                bad.append(f"{tag}: determined_by_text 不能为空")
            if not w.get("free_parameters"):
                bad.append(f"{tag}: free_parameters 不能为空")
            fj = w.get("freedom_justification") or {}
            if fj.get("mode") not in FREEDOM_MODES or not fj.get("note"):
                bad.append(f"{tag}: freedom_justification 须含合法 mode 与非空 note")
            if fj.get("mode") in ("multi_instance_coverage", "order_invariant_plus_multi_instance") and len(wits) < 2:
                bad.append(f"{tag}: freedom_justification 声明多实例覆盖但见证数 < 2")
            for aid in w.get("covers_assertion_ids") or []:
                if aid not in assert_ids and aid not in cf_map:
                    bad.append(f"{tag}: covers_assertion_ids 含未知编号 {aid!r}")
            # 核对 locked_values 与 data 一致且字面出现在 refs
            wdata = w.get("data") or {}
            for lidx, lv in enumerate(w.get("locked_values") or []):
                ltag = f"{tag}.locked_values[{lidx}]"
                if check_refs_list(lv.get("refs"), cites, ltag, bad, require_nonempty=True):
                    if not num_in_refs(lv["value"], lv["refs"], cites):
                        bad.append(f"{ltag}: 锁定值 {lv['value']} 未出现在其 refs 原文中")
                try:
                    actual = eval_val(lv["symbol"], wdata)
                    if abs(actual - float(lv["value"])) > EPS:
                        bad.append(f"{ltag}: data 中 {lv['symbol']}={actual} != locked value {lv['value']}")
                except (KeyError, ValueError, TypeError) as e:
                    bad.append(f"{ltag}: 无法在 data 中读取 {lv['symbol']!r}: {e}")
            # 核对约束在 data 上全部成立
            overrides = {}
            cf_id = w.get("counterfactual_id")
            if cf_id is not None:
                if cf_id not in cf_map:
                    bad.append(f"{tag}: counterfactual_id={cf_id!r} 未定义")
                else:
                    for rc in cf_map[cf_id]["replace_constraints"]:
                        overrides[rc["target"]] = rc["expr"]
            if not w.get("check_constraints"):
                bad.append(f"{tag}: check_constraints 不能为空")
            for con_id in w.get("check_constraints") or []:
                if con_id not in cmap:
                    bad.append(f"{tag}: check_constraints 含未知约束 {con_id!r}")
                    continue
                expr = overrides.get(con_id, cmap[con_id]["expr"])
                try:
                    res = eval_expr(expr, wdata)
                except (KeyError, ValueError, TypeError) as e:
                    bad.append(f"{tag}: 约束 {con_id} 求值出错：{e}")
                    continue
                n_constraint_evals += 1
                if not res:
                    bad.append(f"{tag}: 约束 {con_id} 在合成数据上不成立（expr={expr}）")
            n_witnesses += 1

        # 6h. interpretive_choices & real_market_dependency
        if not isinstance(kc["interpretive_choices"], list):
            bad.append(f"{cid}: interpretive_choices 须为数组")
        for j, ic in enumerate(kc["interpretive_choices"]):
            for k in ("choice_id", "summary", "basis", "alternatives"):
                if k not in ic or not ic[k]:
                    bad.append(f"{cid}.interpretive_choices[{j}]: 缺或空字段 {k}")
        rmd = kc["real_market_dependency"]
        if not isinstance(rmd, dict) or not isinstance(rmd.get("needs_historical_data_for_kernel"), bool) or not rmd.get("historical_data_meaning"):
            bad.append(f"{cid}: real_market_dependency 字段不完整")
        if rmd.get("needs_historical_data_for_kernel") is not False:
            bad.append(f"{cid}: 内核判例的 needs_historical_data_for_kernel 应为 false")

    # 7. 核对 classification 中标记 digitized_in_kernel=true 的集合与 kernel-cases.jsonl 完全一致
    want_k = {cid for cid, row in cls_by_id.items() if row["digitized_in_kernel"]}
    if want_k != seen_k:
        bad.append(f"kernel-cases.jsonl 与 classification 不一致：漏 {sorted(want_k - seen_k)}，多 {sorted(seen_k - want_k)}")

    if bad:
        dedup = list(dict.fromkeys(bad))
        print(f"不符 {len(dedup)} 处：")
        for s in dedup:
            print("  -", s)
        sys.exit(1)

    cat_cnt = Counter(r["category"] for r in cls_rows)
    kind_cnt = Counter(kc["input_kind"] for kc in kcases)
    grade_cnt = Counter(kc["evidence_grade"] for kc in kcases)
    cite_tier_cnt = Counter(ct["tier"] for kc in kcases for ct in kc["cites"])
    print(
        f"全部通过：分类 {len(cls_rows)} 条（{dict(cat_cnt)}）；"
        f"内核判例 {len(kcases)} 条（示范 {sum(1 for x in kcases if x['exemplar'])} 条），"
        f"{n_cites} 条引文，{n_assertions} 条断言，{n_counterfactuals} 条反事实，"
        f"{n_witnesses} 个合成见证，{n_constraint_evals} 次约束求值全部成立；"
        f"准入表 {n_admit} 条"
    )
    print("input_kind：    ", dict(kind_cnt))
    print("evidence_grade：", dict(grade_cnt))
    print("cite tier：     ", dict(cite_tier_cnt))
    sys.exit(0)


if __name__ == "__main__":
    main()
