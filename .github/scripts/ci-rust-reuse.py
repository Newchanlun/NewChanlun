#!/usr/bin/env python3
"""#1875 同 PR 内复用 Rust 作业结果。

PR run 的 Rust 输入（检出树去掉跳过集里的路径）与本 PR 分支上一次全绿 run 完全相同时，本次不再跑 Rust 作业。
典型场景：main 只合入了 .sandcastle 改动，列车把 main 追平进 PR。

凭据是那次 run 里名为 `rust-green <指纹>` 且结论为 success 的作业（ci.yml 的 rust-green 作业）：
  - 作业名由 GitHub 服务端渲染，指纹取自 changes 作业的输出；changes 作业只执行 .github/scripts 下的本脚本，其他作业里的
    PR 代码写不了它的输出，也改不了作业名。artifact 不能当凭据：同一 run 里先于上传执行的 PR 代码（build.rs、conftest.py）
    拿得到运行时令牌，可以替将来的树预先上传（#2027 独审）。
  - rust-green 依赖全部 Rust 作业，任一失败或被跳过它就不会成功。
所以要证明的只剩：那次 run 用的 workflow（含 changes 作业和本脚本）与本次相同。那次 run 检出的是 merge(head, 当时的目标分支)，
GitHub 不给出这个 merge 提交，run 对象的 pull_requests 字段又是查询时现算的；只用 GitHub 记录的历史证明：
  1. 本分支作为 head 的全部 PR（含已关闭）目标分支都是本仓库 main，且都没改过目标分支（没有 base_ref_changed、
     automatic_base_change_succeeded / failed 任一事件；后两者是栈式 PR 的目标分支被合入删除后 GitHub 自动改指）；
  2. 那次 run 的 head 的 .github（去掉跳过集）与本次检出的相同；
  3. 从那个 head 与本次 base 的分叉点到本次 base，base 一侧没有改动 .github 下跳过集以外的文件（compare 的净改动）；
  4. 只认比本次早创建的 run，所以它当时的 base 不晚于本次 base；且只认 7 天内的 run（stable 工具链不在指纹里）。
当时的 base 要么是 head 的祖先，要么落在第 3 条的区间里，所以那次 merge 提交的 .github 就是本次的。只认本仓库分支上的 run。
任何一条查不全（分页上限、截断）都当作不满足；任何查询出错都按全跑处理（rust=true）。
已知局限：第 3 条只看净改动。main 在区间内先改 .github 再改回去时，那次 run 可能用的是中间那版 workflow；那一版同样是
main 上经独审合入的，不是攻击者可控的，最坏是那一次测得不如现在全。

接受的风险（#2027 第五轮独审）：第 1 条按分支「现在的名字」查 PR 历史。有本仓写权限的人可以先让 PR 指向一个改过 ci.yml 的
旁路分支、凭那份 workflow 渲染出 rust-green 作业，再借分支改名之类 API 不留可靠证据的操作，让这次 run 看起来属于一个只指向
main 的分支。前提是攻击者能在本仓推分支、开 PR，而本仓只有用户本人与受控代理有这个权限——同样的人今天已经能用旁路 base 的
PR run 让 push 去重认下一次「全绿」。后果上限：这个 PR 的 ci-ok 少跑一次 Rust；main 合入后的 push run 只认真跑过 Rust 的
PR run（ci.yml push 去重），复用命中的 run 不算，所以 main 上仍完整跑一次 Rust，问题在合入后立即暴露，不会被悄悄放过。

总时限：整次判定最多 DEADLINE_SECONDS 秒（changes 作业上限 5 分钟）；超时与其他查询错误一样按全跑处理。

用法：ci-rust-reuse.py <仓库> <检出 commit> <PR 分支> <本次 run id> <跳过集正则>
标准输出逐行打印 key=value（rust、rust_key、reuse），调用方追加进 GITHUB_OUTPUT。指纹算不出时 rust_key 为空。
"""
import datetime
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.parse

GREEN_JOB = "rust-green "
BASE_CHANGE_EVENTS = {"base_ref_changed", "automatic_base_change_succeeded", "automatic_base_change_failed"}
DEADLINE_SECONDS = 120
MAX_CANDIDATES = 20
MAX_AGE = datetime.timedelta(days=7)  # stable 工具链不在指纹里：凭据只管 7 天


def deadline_api(seconds: float = DEADLINE_SECONDS):
    """gh api 调用，整体超过 seconds 秒即抛错（调用方按全跑处理）。"""
    end = time.monotonic() + seconds

    def api(path: str):
        left = end - time.monotonic()
        if left <= 0:
            raise TimeoutError("reuse lookup deadline exceeded")
        out = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True,
                             timeout=min(60, left)).stdout
        return json.loads(out)
    return api


def tree_entries(api, repo: str, sha: str, skip: re.Pattern) -> list:
    listing = api(f"repos/{repo}/git/trees/{sha}?recursive=1")
    if listing.get("truncated"):
        raise RuntimeError("tree listing truncated")
    return sorted([e["path"], e["mode"], e["type"], e["sha"]]
                  for e in listing["tree"] if e["type"] != "tree" and not skip.fullmatch(e["path"]))


def digest(entries: list) -> str:
    # 每个条目单独 JSON 编码：路径里可以合法地含换行、制表符，拼接编码会有歧义（#2027 独审）。
    return hashlib.sha256("\n".join(json.dumps(e, ensure_ascii=False) for e in entries).encode()).hexdigest()


def github_part(entries: list) -> str:
    return digest([e for e in entries if e[0].startswith(".github/")])


def base_of(api, repo: str, sha: str) -> str:
    parents = api(f"repos/{repo}/git/commits/{sha}")["parents"]
    if len(parents) != 2:
        raise RuntimeError(f"{sha} is not a PR merge commit")
    return parents[0]["sha"]


def pages(api, path: str, limit: int = 10) -> list:
    """逐页取完；超过 limit 页当作查不全，抛错（调用方按全跑处理）。"""
    out = []
    for page in range(1, limit + 1):
        items = api(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
        out += items
        if len(items) < 100:
            return out
    raise RuntimeError(f"too many pages: {path}")


def branch_only_targets_main(api, repo: str, branch: str) -> bool:
    owner = repo.split("/")[0]
    prs = pages(api, f"repos/{repo}/pulls?head={owner}:{urllib.parse.quote(branch, safe='')}&state=all")
    if not prs:
        return False
    for pr in prs:
        if pr["base"]["ref"] != "main" or pr["base"]["repo"]["id"] != pr["head"]["repo"]["id"]:
            return False
        if any(e.get("event") in BASE_CHANGE_EVENTS for e in pages(api, f"repos/{repo}/issues/{pr['number']}/events")):
            return False
    return True


def base_side_touches_github(api, repo: str, head: str, base: str, skip: re.Pattern) -> bool:
    cmp = api(f"repos/{repo}/compare/{head}...{base}?per_page=100")
    files = cmp.get("files")
    if files is None or len(files) >= 300 or cmp.get("total_commits", 0) > 250:
        return True  # 列表可能被截断：当作改过
    names = [n for f in files for n in (f["filename"], f.get("previous_filename")) if n]
    return any(n.startswith(".github/") and not skip.fullmatch(n) for n in names)


def green_job(api, repo: str, run_id: int, key: str) -> bool:
    got = api(f"repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100")
    if got.get("total_count", 0) > len(got["jobs"]):
        raise RuntimeError("jobs list truncated")
    return any(j["name"] == GREEN_JOB + key and j["conclusion"] == "success" for j in got["jobs"])


def created(run) -> datetime.datetime:
    return datetime.datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))


def find_reuse(api, repo: str, branch: str, run_id: int, key: str, ours_github: str, base: str, skip: re.Pattern,
               now: datetime.datetime | None = None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if not branch_only_targets_main(api, repo, branch):
        return None
    runs = api(f"repos/{repo}/actions/workflows/ci.yml/runs?event=pull_request&status=success"
               f"&branch={urllib.parse.quote(branch, safe='')}&per_page=50")["workflow_runs"]
    # 只认比本次早创建的 run（run id 单调递增；重跑沿用原 id），本仓库分支上的。
    older = [r for r in runs if r["id"] < run_id and now - created(r) <= MAX_AGE
             and (r.get("head_repository") or {}).get("id") == r["repository"]["id"]][:MAX_CANDIDATES]
    for run in older:
        if not green_job(api, repo, run["id"], key):
            continue
        if github_part(tree_entries(api, repo, run["head_sha"], skip)) != ours_github:
            continue
        if base_side_touches_github(api, repo, run["head_sha"], base, skip):
            continue
        return run["html_url"]
    return None


def decide(api, repo: str, sha: str, branch: str, run_id: int, skip: re.Pattern) -> dict:
    try:
        entries = tree_entries(api, repo, sha, skip)
        if not entries:
            raise RuntimeError("empty tree")
        key = digest(entries)
    except Exception as e:  # noqa: BLE001 — 算不出指纹就全跑，也不出凭据
        return {"rust": "true", "rust_key": "", "reuse": f"no key: {e}"}
    try:
        url = find_reuse(api, repo, branch, run_id, key, github_part(entries), base_of(api, repo, sha), skip)
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
    for k, v in decide(deadline_api(), repo, sha, branch, int(run_id), re.compile(skip)).items():
        print(f"{k}={' '.join(str(v).split())}")  # 单行，避免写坏 GITHUB_OUTPUT
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
