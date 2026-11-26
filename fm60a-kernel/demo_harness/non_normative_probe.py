#!/usr/bin/env python3
"""非规范演示判定器（NON-NORMATIVE DEMO ONLY — NOT A CHANLUN DEFINITION）。

声明：
  1. 本脚本与核心数据材料（classification.jsonl / kernel-cases.jsonl）严格分离，
     **不是**缠论形式化定义，也**不替**任何候选定义或作者断言下对错结论。
  2. 本脚本唯一目的，是向 FM-60b（ChanTest）作者证明：
     只读取 fm60a-kernel/kernel-cases.jsonl（完全不回读任何博文 .md），
     即可直接驱动参数化判定器，并把原典判例转化为能区分不同候选公理分叉的回归测试。

用法（仓库内任意目录）：
    python3 -I fm60a-kernel/demo_harness/non_normative_probe.py
"""
import json
import os
import sys

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
    for b in bars:
        cur = {"id": b["id"], "high": b["high"], "low": b["low"], "raw_ids": [b["id"]]}
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
                    "raw_ids": prev["raw_ids"] + cur["raw_ids"],
                }
            else:
                out[-1] = {
                    "id": f"{prev['id']}+{cur['id']}",
                    "high": min(prev["high"], cur["high"]),
                    "low": min(prev["low"], cur["low"]),
                    "raw_ids": prev["raw_ids"] + cur["raw_ids"],
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


def demo_026(cases):
    c = cases["FM60A-026"]
    print("\n[1] FM60A-026（第54课 d1=g2 边界：闭区间 vs 开区间）")
    for w in c["synthetic_witnesses"]:
        vp = w["data"]["vertex_prices"]
        for closed in (True, False):
            z1 = overlap([seg_interval(vp, "g0", "d1"), seg_interval(vp, "d1", "g1"), seg_interval(vp, "g1", "d2")], closed=closed)
            z_deg = overlap([seg_interval(vp, "d1", "g1"), seg_interval(vp, "g1", "d2"), seg_interval(vp, "d2", "g2")], closed=closed)
            g2_is_3s = (z1 is not None) and (not touches(seg_interval(vp, "d2", "g2"), z1, closed=closed))
            g3_is_3s = (z1 is not None) and (not touches(seg_interval(vp, "d3", "g3"), z1, closed=closed))
            mode = "闭区间" if closed else "开区间"
            print(f"  {w['witness_id']:28s} | {mode} | [d1,g1]={z1} | 单点[d1,g2]={z_deg} | g2三卖={g2_is_3s} | g3三卖={g3_is_3s}")


def demo_012(cases):
    c = cases["FM60A-012"]
    print("\n[2] FM60A-012（第24课 C段三检查点门禁：完整门禁 vs 仅比面积）")
    for w in c["synthetic_witnesses"]:
        vp = w["data"]["vertex_prices"]
        st = w["data"]["strengths"]
        fl = w["data"]["flags"]
        a_sum = st["a_red1"] + st["a_red2"]
        cps = [
            ("9:35", vp["c1_peak"], st["c_red1"], fl["t1_has_internal_center"]),
            ("10:40", vp["c2_peak"], st["c_red1"] + st["c_red2"], fl["t2_has_internal_center"]),
            ("13:05", vp["c3_peak"], st["c_red1"] + st["c_red2"] + st["c_red3"], fl["t3_has_internal_center"]),
        ]
        full = [(pk > vp["a_peak"] + EPS) and has_z and (csum < a_sum - EPS) for _, pk, csum, has_z in cps]
        area_only = [csum < a_sum - EPS for _, _, csum, _ in cps]
        print(f"  {w['witness_id']:32s} | 全门禁(新高+中枢+面积和)={full} | 仅比面积={area_only}")


def demo_021(cases):
    c = cases["FM60A-021"]
    print("\n[3] FM60A-021（第57课 530 九段升级 [4015,4122]：块外缘交集 vs 中枢核交集 + 多义性）")
    for w in c["synthetic_witnesses"]:
        vp = w["data"]["vertex_prices"]
        b1_segs = [("v1", "v2"), ("v2", "v3"), ("v3", "v4")]
        b2_segs = [("v4", "v5"), ("v5", "v6"), ("v6", "v7")]
        b3_segs = [("v7", "v8"), ("v8", "v9"), ("v9", "v10")]
        hull_5m = overlap([block_hull(vp, b1_segs), block_hull(vp, b2_segs), block_hull(vp, b3_segs)], closed=True)
        c1 = overlap([seg_interval(vp, a, b) for a, b in b1_segs], closed=True)
        c2 = overlap([seg_interval(vp, a, b) for a, b in b2_segs], closed=True)
        c3 = overlap([seg_interval(vp, a, b) for a, b in b3_segs], closed=True)
        core_5m = overlap([c1, c2, c3], closed=True) if (c1 and c2 and c3) else None
        alt_1m = overlap([seg_interval(vp, "v3", "v4"), seg_interval(vp, "v4", "v5"), seg_interval(vp, "v5", "v6")], closed=True)
        print(f"  {w['witness_id']:24s} | 块外缘交集={hull_5m} | 核交集={core_5m} | 另分34/45/56={alt_1m}")


def demo_043(cases):
    c = cases["FM60A-043"]
    print("\n[4] FM60A-043（第102课 6124 下来 4 线段 0 中枢：成核不含首段 vs 含首段）")
    for w in c["synthetic_witnesses"]:
        vp = w["data"]["vertex_prices"]
        s1 = seg_interval(vp, "p0", "p1")
        s2 = seg_interval(vp, "p1", "p2")
        s3 = seg_interval(vp, "p2", "p3")
        s4 = seg_interval(vp, "p3", "p4")
        excl = overlap([s2, s3, s4], closed=True)
        incl = overlap([s1, s2, s3], closed=True)
        print(f"  {w['witness_id']:30s} | 不含首段(s2∩s3∩s4)={excl} | 含首段(s1∩s2∩s3)={incl}")


def demo_031(cases):
    c = cases["FM60A-031"]
    print("\n[5] FM60A-031（第81课 0.08 差与包含关系：老笔 5 根阈值 vs 新笔 4/5 根阈值）")
    for w in c["synthetic_witnesses"]:
        raw = w["data"]["kbars"]
        merged = merge_kbars(raw, initial_dir="down")
        b_idx = next((i for i in range(1, len(merged) - 1) if is_bottom_fractal(merged[i - 1], merged[i], merged[i + 1])), None)
        t_idx = next((i for i in range(1, len(merged) - 1) if is_top_fractal(merged[i - 1], merged[i], merged[i + 1])), None)
        span_merged = (t_idx - b_idx + 1) if (b_idx is not None and t_idx is not None) else 0
        old_pen = span_merged >= 5
        new_pen = span_merged >= 4 and len(raw) >= 5
        top_id = merged[t_idx]["id"] if t_idx is not None else None
        print(f"  {w['witness_id']:36s} | 合并后顶={top_id:16s} | 合并后跨度={span_merged} | 老笔={old_pen} | 新笔={new_pen}")


def demo_056(cases):
    c = cases["FM60A-056"]
    print("\n[6] FM60A-056（第108课 周线包含推迟底分型 vs 突破 2523 打破包含）")
    for w in c["synthetic_witnesses"]:
        raw = w["data"]["kbars"]
        merged = merge_kbars(raw, initial_dir="down")
        has_bf = len(merged) >= 3 and is_bottom_fractal(merged[0], merged[1], merged[2])
        print(f"  {w['witness_id']:36s} | 合并后根数={len(merged)} | 当周构成底分型={has_bf}")


def main():
    cases = load_cases()
    print("=== 非规范演示探针（NOT A DEFINITION）===")
    print(f"仅读取 fm60a-kernel/kernel-cases.jsonl（共 {len(cases)} 条），零博文回读。")
    demo_026(cases)
    demo_012(cases)
    demo_021(cases)
    demo_043(cases)
    demo_031(cases)
    demo_056(cases)


if __name__ == "__main__":
    main()
