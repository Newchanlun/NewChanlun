#!/usr/bin/env python3
"""非规范演示判定器（NON-NORMATIVE DEMO ONLY — NOT A CHANLUN DEFINITION）。

声明：
  1. 本脚本与核心数据材料（classification.jsonl / kernel-cases.jsonl）严格分离，
     **不是**缠论形式化定义，也**不替**任何候选定义或作者陈述下对错结论。
  2. 本脚本唯一目的，是向 FM-60b（ChanTest）作者证明：
     只读取 fm60a-kernel/kernel-cases.jsonl（fm60a-kernel-v2 三层格式，完全不回读任何博文 .md），
     即可直接消费并列建模（M1/M2/M3）与合成实例，观察在各建模前提下不同候选定义与作者陈述的相容性。

用法（仓库内任意目录）：
    python3 -I fm60a-kernel/demo_harness/non_normative_probe.py
"""
import json
import os

EPS = 1e-9


def seg_interval(vp, a, b):
    x, y = vp[a], vp[b]
    return (x, y) if x <= y else (y, x)


def overlap(ivs, closed=True):
    lo = max(a for a, _ in ivs)
    hi = min(b for _, b in ivs)
    ok = (lo <= hi + EPS) if closed else (lo < hi - EPS)
    return (lo, hi) if ok else None


def touches(seg_iv, center_iv, closed=True):
    return overlap([seg_iv, center_iv], closed=closed) is not None


def block_hull(vp, seg_pairs):
    vals = [vp[u] for pair in seg_pairs for u in pair]
    return (min(vals), max(vals))


def merge_kbars(bars, initial_dir="up"):
    """最简演示版包含处理（非正式定义）。"""
    out = []
    direction = initial_dir
    for raw_idx, b in enumerate(bars):
        cur = {"id": b["id"], "high": b["high"], "low": b["low"], "raw_indices": [raw_idx]}
        if not out:
            out.append(cur)
            continue
        prev = out[-1]
        contains = (prev["high"] >= cur["high"] - EPS and prev["low"] <= cur["low"] + EPS) or (
            cur["high"] >= prev["high"] - EPS and cur["low"] <= prev["low"] + EPS
        )
        if contains:
            if direction == "up":
                out[-1] = {
                    "id": f"{prev['id']}+{cur['id']}",
                    "high": max(prev["high"], cur["high"]),
                    "low": max(prev["low"], cur["low"]),
                    "raw_indices": prev["raw_indices"] + cur["raw_indices"],
                }
            else:
                out[-1] = {
                    "id": f"{prev['id']}+{cur['id']}",
                    "high": min(prev["high"], cur["high"]),
                    "low": min(prev["low"], cur["low"]),
                    "raw_indices": prev["raw_indices"] + cur["raw_indices"],
                }
        else:
            if cur["high"] > prev["high"] + EPS and cur["low"] > prev["low"] + EPS:
                direction = "up"
            elif cur["high"] < prev["high"] - EPS and cur["low"] < prev["low"] - EPS:
                direction = "down"
            out.append(cur)
    return out


def is_bottom_fractal(b1, b2, b3):
    return (
        b2["low"] < b1["low"] - EPS
        and b2["low"] < b3["low"] - EPS
        and b2["high"] < b1["high"] - EPS
        and b2["high"] < b3["high"] - EPS
    )


def is_top_fractal(b1, b2, b3):
    return (
        b2["high"] > b1["high"] + EPS
        and b2["high"] > b3["high"] + EPS
        and b2["low"] > b1["low"] + EPS
        and b2["low"] > b3["low"] + EPS
    )


def load_cases():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.normpath(os.path.join(here, "..", "kernel-cases.jsonl"))
    by_id = {}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                d = json.loads(raw)
                by_id[d["case_id"]] = d
    return by_id


def tag_inst(ins):
    cf = f"cf:{ins['counterfactual_proposer']}" if ins["instance_role"] == "counterfactual" else "pos"
    return f"{ins['instance_id']}({ins['model_id']},{cf})"


def demo_026(cases):
    c = cases["FM60A-026"]
    print("\n[1] FM60A-026（第54课 d1=g2 边界与作者亲口反事实 d1>g2：闭区间 vs 开区间）")
    for ins in c["instances"]:
        vp = ins["data"]["vertex_prices"]
        for closed in (True, False):
            z1 = overlap([seg_interval(vp, "g0", "d1"), seg_interval(vp, "d1", "g1"), seg_interval(vp, "g1", "d2")], closed=closed)
            z_deg = overlap([seg_interval(vp, "d1", "g1"), seg_interval(vp, "g1", "d2"), seg_interval(vp, "d2", "g2")], closed=closed)
            g2_is_3s = (z1 is not None) and (not touches(seg_interval(vp, "d2", "g2"), z1, closed=closed))
            g3_is_3s = (z1 is not None) and (not touches(seg_interval(vp, "d3", "g3"), z1, closed=closed))
            mode = "闭区间" if closed else "开区间"
            print(f"  {tag_inst(ins):20s} | {mode} | [d1,g1]={z1} | 单点[d1,g2]={z_deg} | g2三卖={g2_is_3s} | g3三卖={g3_is_3s}")


def demo_012(cases):
    c = cases["FM60A-012"]
    print("\n[2] FM60A-012（第24课 C段三检查点门禁与三种峰价排序读法 M1/M2/M3）")
    for ins in c["instances"]:
        vp = ins["data"]["vertex_prices"]
        st = ins["data"]["strengths"]
        fl = ins["data"]["flags"]
        a_sum = st["a_red1"] + st["a_red2"]
        cps = [
            ("9:35", vp["c1_peak"], st["c_red1"], fl["t1_has_internal_center"]),
            ("10:40", vp["c2_peak"], st["c_red1"] + st["c_red2"], fl["t2_has_internal_center"]),
            ("13:05", vp["c3_peak"], st["c_red1"] + st["c_red2"] + st["c_red3"], fl["t3_has_internal_center"]),
        ]
        gate = [(pk > vp["a_peak"] + EPS) and has_z and (csum < a_sum - EPS) for _, pk, csum, has_z in cps]
        area_ok = [csum < a_sum - EPS for _, _, csum, _ in cps]
        print(f"  {tag_inst(ins):22s} | 门禁(新高+中枢+面积和)={gate} | 仅面积和<{a_sum:.0f}={area_ok}")


def demo_021(cases):
    c = cases["FM60A-021"]
    print("\n[3] FM60A-021（第57课 530 九段升级 [4015,4122] 与条件二买两支 M1/M2 + 核对照 M3）")
    for ins in c["instances"]:
        vp = ins["data"]["vertex_prices"]
        st = ins["data"]["strengths"]
        b1_segs = [("v1", "v2"), ("v2", "v3"), ("v3", "v4")]
        b2_segs = [("v4", "v5"), ("v5", "v6"), ("v6", "v7")]
        b3_segs = [("v7", "v8"), ("v8", "v9"), ("v9", "v10")]
        hull_5m = overlap([block_hull(vp, b1_segs), block_hull(vp, b2_segs), block_hull(vp, b3_segs)], closed=True)
        c1 = overlap([seg_interval(vp, a, b) for a, b in b1_segs], closed=True)
        c2 = overlap([seg_interval(vp, a, b) for a, b in b2_segs], closed=True)
        c3 = overlap([seg_interval(vp, a, b) for a, b in b3_segs], closed=True)
        core_5m = overlap([c1, c2, c3], closed=True) if (c1 and c2 and c3) else None
        b2_branch = "不创新低" if vp["v9"] >= vp["v7"] - EPS else ("创低盘背" if st["s_89"] < st["s_67"] - EPS else "均否")
        print(f"  {tag_inst(ins):20s} | 块外缘交集={hull_5m} | 核交集={core_5m} | 9点二买支={b2_branch}")


def demo_043(cases):
    c = cases["FM60A-043"]
    print("\n[4] FM60A-043（第102课 4 线段 0 中枢：候选解释 M1/M2 + 精确等号 I2 vs 越过 50 点 I3）")
    for ins in c["instances"]:
        vp = ins["data"]["vertex_prices"]
        s1 = seg_interval(vp, "p0", "p1")
        s2 = seg_interval(vp, "p1", "p2")
        s3 = seg_interval(vp, "p2", "p3")
        s4 = seg_interval(vp, "p3", "p4")
        excl_c = overlap([s2, s3, s4], closed=True)
        excl_o = overlap([s2, s3, s4], closed=False)
        incl_c = overlap([s1, s2, s3], closed=True)
        elig = ins["data"]["flags"]["triple_center_eligible"]
        print(f"  {tag_inst(ins):22s} | s2∩s3∩s4(闭)={excl_c} | s2∩s3∩s4(开)={excl_o} | s1∩s2∩s3(闭)={incl_c} | 资格={elig}")


def demo_031(cases):
    c = cases["FM60A-031"]
    print("\n[5] FM60A-031（第81课 0.08 差：三种并列读法 M1/M2/M3 + 老笔 vs 081:110 新笔双条款）")
    for ins in c["instances"]:
        raw = ins["data"]["kbars"]
        merged = merge_kbars(raw, initial_dir="down")
        b_idx = next((i for i in range(1, len(merged) - 1) if is_bottom_fractal(merged[i - 1], merged[i], merged[i + 1])), None)
        t_idx = next((i for i in range(1, len(merged) - 1) if is_top_fractal(merged[i - 1], merged[i], merged[i + 1])), None)
        span_merged = (t_idx - b_idx + 1) if (b_idx is not None and t_idx is not None) else 0
        old_pen = span_merged >= 5
        # 精确实现 081:110 两项条款：1) 包含处理后顶底分型不共用 K 线；2) 原始极值 K 线之间（不含两根）不计包含 >= 3 根
        no_shared_merged = (b_idx is not None and t_idx is not None) and ((t_idx - 1) > (b_idx + 1))
        if b_idx is not None and t_idx is not None:
            raw_b_low = min(merged[b_idx]["raw_indices"], key=lambda idx: raw[idx]["low"])
            raw_t_high = max(merged[t_idx]["raw_indices"], key=lambda idx: raw[idx]["high"])
            raw_between = max(0, raw_t_high - raw_b_low - 1)
        else:
            raw_between = 0
        new_pen_081_110 = no_shared_merged and (raw_between >= 3)
        top_id = merged[t_idx]["id"] if t_idx is not None else "None"
        print(
            f"  {tag_inst(ins):22s} | 合并顶={top_id:16s} | 合并跨度={span_merged} | "
            f"老笔={old_pen} | 081:110新笔={new_pen_081_110}(不共用={no_shared_merged},原始间根={raw_between})"
        )


def main():
    cases = load_cases()
    print("=== 非规范演示探针（NOT A DEFINITION · fm60a-kernel-v2）===")
    print(f"仅读取 fm60a-kernel/kernel-cases.jsonl（共 {len(cases)} 条 v2 示范），零博文回读。")
    demo_026(cases)
    demo_012(cases)
    demo_021(cases)
    demo_043(cases)
    demo_031(cases)


if __name__ == "__main__":
    main()
