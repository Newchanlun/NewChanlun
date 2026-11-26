#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R4：真实 origin/main 历史回放（无误红复查）。

支持四种模式（默认 sample）：
  - sample       四类组合抽样回放（第一父最近 250 + 双根附近 120 + 合并双父 160x2 + .github/scripts 240 + 双根自身 2）
  - gh-scripts   全量扫描改动 .github/ 或 scripts/ 的历史提交（前两父，main + proof/x）
  - merges       全量扫描所有合并提交（全部父提交，main + proof/x）
  - first-parent 全量扫描整条第一父链（从根提交到 tip，五种分支名轮询）

用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I replay_origin_main.py [--mode sample|gh-scripts|merges|first-parent] [--workers 4] [--precheck PATH] [--real-repo PATH]
"""
import argparse
import concurrent.futures
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_PRECHECK = os.path.join(ROOT, "formal_math", "verification", "precheck", "precheck.py")
GENV = {
    "PATH": os.environ.get("PATH", os.defpath),
    "LC_ALL": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
}
RUN_ENV = {"PATH": GENV["PATH"], "LC_ALL": "C.UTF-8"}


def git_lines(repo, *args):
    p = subprocess.run(["git", "-C", repo, *args], env=GENV, capture_output=True, check=True)
    return [ln for ln in p.stdout.decode("utf-8").splitlines() if ln]


def run_tasks(precheck, repo, tasks, workers):
    def one(item):
        base, head, br, cats = item
        p = subprocess.run([sys.executable, "-I", precheck, repo, base, head, br], env=RUN_ENV, capture_output=True)
        if p.returncode != 0:
            return (base, head, br, cats, p.returncode,
                    p.stdout.decode("utf-8", "replace").strip(),
                    p.stderr.decode("utf-8", "replace").strip())
        return None

    fails = []
    if workers <= 1:
        for item in tasks:
            r = one(item)
            if r:
                fails.append(r)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            for r in ex.map(one, tasks):
                if r:
                    fails.append(r)
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("sample", "gh-scripts", "merges", "first-parent"), default="sample")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--precheck", default=DEFAULT_PRECHECK)
    ap.add_argument("--real-repo", default=ROOT)
    ap.add_argument("--ref", default="origin/main")
    ns = ap.parse_args()

    t0 = time.monotonic()
    tip = git_lines(ns.real_repo, "rev-parse", ns.ref)[0]
    cat_counts = {}
    tasks = []

    if ns.mode == "sample":
        parents_map = {}
        for ln in git_lines(ns.real_repo, "rev-list", "--parents", ns.ref):
            parts = ln.split()
            parents_map[parts[0]] = parts[1:]

        fp_recent = git_lines(ns.real_repo, "rev-list", "--first-parent", "-n", "250", ns.ref)
        all_rev = git_lines(ns.real_repo, "rev-list", "--reverse", ns.ref)
        roots = [c for c in all_rev if not parents_map[c]]
        earliest = [c for c in all_rev[:150] if parents_map[c]][:120]
        root_children = {}
        for c, ps in parents_map.items():
            for p in ps:
                root_children.setdefault(p, []).append(c)
        extra_near_roots = []
        for r in roots:
            frontier = list(root_children.get(r, []))
            seen = {r}
            got = []
            while frontier and len(got) < 30:
                cur = frontier.pop(0)
                if cur in seen:
                    continue
                seen.add(cur)
                got.append(cur)
                frontier.extend(root_children.get(cur, []))
            extra_near_roots.extend(got)

        merges_all = git_lines(ns.real_repo, "rev-list", "--merges", ns.ref)
        merges_sel = merges_all[:80] + merges_all[-80:]
        gh_sc_all = git_lines(ns.real_repo, "rev-list", ns.ref, "--", ".github", "scripts")
        gh_sc_sel = gh_sc_all[:120] + gh_sc_all[-120:]

        pairs = {}

        def add_pair(base, head, cat):
            pairs.setdefault((base, head), set()).add(cat)

        for r in roots:
            add_pair(r, r, "root_self")
        for c in fp_recent:
            if parents_map.get(c):
                add_pair(parents_map[c][0], c, "first_parent_recent")
        for c in earliest + extra_near_roots:
            if parents_map.get(c):
                add_pair(parents_map[c][0], c, "near_root")
        for m in merges_sel:
            ps = parents_map.get(m, [])
            if len(ps) >= 1:
                add_pair(ps[0], m, "merge_p1")
            if len(ps) >= 2:
                add_pair(ps[1], m, "merge_p2")
        for c in gh_sc_sel:
            ps = parents_map.get(c, [])
            if ps:
                add_pair(ps[0], c, "github_scripts")

        key_heads = {"6d221b2f216f08b38be656a7b3fd8ba4d02b0f24", "9560db2d08ddd0ca2e2810cf2d915d9fe2a2dd9e"}
        branches_core = ("main", "proof/x")
        branches_full = ("main", "proof/x", "decl/x", "audit/x", "infra/x", "")
        for idx, ((base, head), cats) in enumerate(sorted(pairs.items())):
            for cat in cats:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
            brs = branches_full if (idx % 5 == 0 or head in key_heads or "root_self" in cats) else branches_core
            for br in brs:
                tasks.append((base, head, br, sorted(cats)))
        uniq_pairs = len(pairs)
        print(f"ROOTS: {roots}")
    elif ns.mode == "gh-scripts":
        commits = git_lines(ns.real_repo, "rev-list", "--parents", ns.ref, "--", ".github", "scripts")
        pairs = sorted({(p, parts[0]) for ln in commits for parts in (ln.split(),) for p in parts[1:3]})
        uniq_pairs = len(pairs)
        cat_counts["github_scripts_all"] = uniq_pairs
        tasks = [(b, h, br, ["github_scripts_all"]) for b, h in pairs for br in ("main", "proof/x")]
    elif ns.mode == "merges":
        merges = git_lines(ns.real_repo, "rev-list", "--parents", "--merges", ns.ref)
        pairs = sorted({(p, parts[0]) for ln in merges for parts in (ln.split(),) for p in parts[1:]})
        uniq_pairs = len(pairs)
        cat_counts["merges_all_parents"] = uniq_pairs
        tasks = [(b, h, br, ["merges_all_parents"]) for b, h in pairs for br in ("main", "proof/x")]
    else:
        fp = git_lines(ns.real_repo, "rev-list", "--first-parent", "--reverse", ns.ref)
        pairs = [(fp[i], fp[i + 1]) for i in range(len(fp) - 1)]
        uniq_pairs = len(pairs)
        cat_counts["first_parent_all"] = uniq_pairs
        brs = ("main", "proof/x", "decl/x", "audit/x", "infra/x")
        tasks = [(b, h, brs[i % 5], ["first_parent_all"]) for i, (b, h) in enumerate(pairs)]

    failures = run_tasks(ns.precheck, ns.real_repo, tasks, ns.workers)
    dt = time.monotonic() - t0
    print(f"MODE: {ns.mode} | REF: {ns.ref} ({tip})")
    print(f"UNIQUE PAIRS: {uniq_pairs} | TOTAL INVOCATIONS: {len(tasks)} | FAILURES: {len(failures)} | ELAPSED: {dt:.2f}s")
    print("CATEGORY PAIR COUNTS:")
    for k in sorted(cat_counts):
        print(f"  {k}: {cat_counts[k]}")
    if failures:
        print("FAILURES DETAIL (up to 20):")
        for base, head, br, cats, rc, out, err in failures[:20]:
            print(f"  {base[:10]}..{head[:10]} br={br!r} cats={cats} rc={rc} out={out!r} err={err!r}")
    return 1 if failures else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
