#!/usr/bin/env python3
"""#1875 同 PR 内复用 Rust 作业结果。

PR run 的 Rust 输入（检出树去掉跳过集里的路径）与本 PR 分支上一次全绿 run 完全相同，且那次 run 的 .github
与本次相同时，本次不再跑 Rust 作业。典型场景：main 只合入了 .sandcastle 改动，列车把 main 追平进 PR。
全绿的 run 由 ci-ok 上传名为 rust-green-<指纹> 的 artifact，本脚本按名字找它。

为什么还要比 .github：artifact 由那次 run 的 workflow 上传，只有那份 workflow 与本次相同，才能信它测过的就是
这个指纹（被改过的 workflow 可以不跑测试就上传）。那次 run 检出的是 merge(head, 当时的 base)，GitHub 不给出这个
merge 提交，artifact 内容又是那份 workflow 自己写的，不能拿来证明。所以只用 GitHub 给的数据证明：
  1. 那次 run 的 head 的 .github 与本次检出的 .github 相同；
  2. 从那个 head 与本次 base 的分叉点到本次 base，base 一侧没有改动 .github 下任何文件。
当时的 base 位于分叉点之前或之后、本次 base 之前，按第 2 条，它的 .github 改动都已在 head 里，所以那次 merge 提交的
.github 就是 head 的 .github，也就是本次的。只认本仓库分支上的 run；fork 的 run 不认。

用法：ci-rust-reuse.py <仓库> <检出 commit> <PR 分支> <本次 run id> <跳过集正则>
标准输出逐行打印 key=value（rust、rust_key、reuse），调用方追加进 GITHUB_OUTPUT。
任何查询出错都按全跑处理（rust=true）；指纹算不出时 rust_key 为空，ci-ok 不上传。
"""
import hashlib
import json
import re
import subprocess
import sys
import urllib.parse

ARTIFACT_PREFIX = "rust-green-"


def gh_api(path: str):
    out = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True, timeout=60).stdout
    return json.loads(out)


def tree_key(api, repo: str, sha: str, skip: re.Pattern) -> str:
    listing = api(f"repos/{repo}/git/trees/{sha}?recursive=1")
    if listing.get("truncated"):
        raise RuntimeError("tree listing truncated")
    lines = sorted(f"{e['mode']} {e['type']} {e['sha']}\t{e['path']}"
                   for e in listing["tree"] if e["type"] != "tree" and not skip.match(e["path"]))
    if not lines:
        raise RuntimeError("empty tree")
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def github_tree(api, repo: str, sha: str) -> str:
    for e in api(f"repos/{repo}/git/trees/{sha}")["tree"]:
        if e["path"] == ".github" and e["type"] == "tree":
            return e["sha"]
    raise RuntimeError(f"{sha} has no .github tree")


def base_of(api, repo: str, sha: str) -> str:
    parents = api(f"repos/{repo}/git/commits/{sha}")["parents"]
    if len(parents) != 2:
        raise RuntimeError(f"{sha} is not a PR merge commit")
    return parents[0]["sha"]


def base_side_touches_github(api, repo: str, head: str, base: str) -> bool:
    cmp = api(f"repos/{repo}/compare/{head}...{base}?per_page=100")
    files = cmp.get("files")
    if files is None or len(files) >= 300 or cmp.get("total_commits", 0) > 250:
        return True  # 列表可能被截断：当作改过
    return any(f["filename"].startswith(".github/") or (f.get("previous_filename") or "").startswith(".github/")
               for f in files)


def find_reuse(api, repo: str, branch: str, run_id: int, key: str, ours: str, base: str):
    name = ARTIFACT_PREFIX + key
    runs = api(f"repos/{repo}/actions/workflows/ci.yml/runs?event=pull_request&status=success"
               f"&branch={urllib.parse.quote(branch, safe='')}&per_page=30")["workflow_runs"]
    for run in runs:
        head_repo = run.get("head_repository") or {}
        # 只认比本次早创建的 run（run id 单调递增；重跑沿用原 id）：它当时的 base 不晚于本次 base，上面第 2 条才覆盖得到。
        if run["id"] >= run_id or head_repo.get("id") != run["repository"]["id"]:
            continue
        # 那次 run 的 workflow 来自 merge(head, 目标分支)：目标分支必须是本仓库 main，否则改过 ci.yml 的旁路 base 能伪造凭据。
        prs = run.get("pull_requests") or []
        if not prs or any(p["base"]["ref"] != "main" or p["base"]["repo"]["id"] != run["repository"]["id"] for p in prs):
            continue
        artifacts = api(f"repos/{repo}/actions/runs/{run['id']}/artifacts?name={name}")["artifacts"]
        if not any(a["name"] == name and not a["expired"] for a in artifacts):
            continue
        if github_tree(api, repo, run["head_sha"]) != ours:
            continue
        if base_side_touches_github(api, repo, run["head_sha"], base):
            continue
        return run["html_url"]
    return None


def decide(api, repo: str, sha: str, branch: str, run_id: int, skip: re.Pattern) -> dict:
    try:
        key = tree_key(api, repo, sha, skip)
    except Exception as e:  # noqa: BLE001 — 算不出指纹就全跑、不上传
        return {"rust": "true", "rust_key": "", "reuse": f"no key: {e}"}
    try:
        url = find_reuse(api, repo, branch, run_id, key, github_tree(api, repo, sha), base_of(api, repo, sha))
    except Exception as e:  # noqa: BLE001 — 查询出错全跑
        return {"rust": "true", "rust_key": key, "reuse": f"lookup failed: {e}"}
    if url is None:
        return {"rust": "true", "rust_key": key, "reuse": "none"}
    return {"rust": "false", "rust_key": key, "reuse": url}


def main(argv: list[str]) -> int:
    if len(argv) != 6:
        print(__doc__, file=sys.stderr)
        return 64
    repo, sha, branch, run_id, skip = argv[1:]
    for k, v in decide(gh_api, repo, sha, branch, int(run_id), re.compile(skip)).items():
        print(f"{k}={' '.join(str(v).split())}")  # 单行，避免写坏 GITHUB_OUTPUT
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
