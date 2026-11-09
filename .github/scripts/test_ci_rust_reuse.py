"""ci-rust-reuse.py 的判定：指纹只排除跳过集；本分支全部 PR 都只指向本仓 main、未改过目标分支，候选 run 为本仓库、
更早、全绿的 ci.yml pull_request run，head 的 .github 相同且 base 一侧未改 .github 才复用；任何出错一律全跑。"""
import importlib.util
import pathlib
import re
import unittest

SPEC = importlib.util.spec_from_file_location("reuse", pathlib.Path(__file__).with_name("ci-rust-reuse.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
SKIP = re.compile(r"^(\.sandcastle/.+|package\.json)$")
R = "o/r"


def blob(path, sha="b1"):
    return {"path": path, "mode": "100644", "type": "blob", "sha": sha}


def pr(number=1, base_ref="main", base_repo=1, head_repo=1):
    return {"number": number, "base": {"ref": base_ref, "repo": {"id": base_repo}}, "head": {"repo": {"id": head_repo}}}


def run(i=7, head="H1", event="pull_request", conclusion="success", head_repo_id=1, path=".github/workflows/ci.yml"):
    return {"id": i, "head_sha": head, "html_url": f"u/{i}", "event": event, "conclusion": conclusion, "path": path,
            "repository": {"id": 1}, "head_repository": {"id": head_repo_id}}


def art(key, run_id=7, branch="br", expired=False, head_repo=1):
    return {"name": M.ARTIFACT_PREFIX + key, "expired": expired,
            "workflow_run": {"id": run_id, "head_branch": branch, "repository_id": 1, "head_repository_id": head_repo}}


class Fake:
    def __init__(self, trees, runs, artifacts, prs, events=None, roots=None, base_files=()):
        self.trees, self.runs, self.artifacts, self.prs = trees, {r["id"]: r for r in runs}, artifacts, prs
        self.events = events or {}
        self.roots = roots or {"M": "G", "H1": "G"}
        self.base_files = list(base_files)
        self.compare = None

    def __call__(self, path):
        if "/git/trees/" in path:
            sha = path.split("/git/trees/")[1].split("?")[0]
            if path.endswith("?recursive=1"):
                return self.trees[sha]
            return {"tree": [{"path": ".github", "type": "tree", "sha": self.roots[sha]}]}
        if "/git/commits/" in path:
            return {"parents": [{"sha": "B"}, {"sha": "H"}]}
        if "/compare/" in path:
            self.compare = path
            return {"total_commits": 1, "files": [{"filename": f} for f in self.base_files]}
        if "/pulls?head=" in path:
            return self.prs if "page=1" in path else []
        if "/events" in path:
            n = int(path.split("/issues/")[1].split("/")[0])
            return self.events.get(n, []) if "page=1" in path else []
        if "/actions/artifacts?name=" in path:
            return {"artifacts": self.artifacts}
        if "/actions/runs/" in path:
            return self.runs[int(path.split("/actions/runs/")[1])]
        raise AssertionError(path)


class ReuseTest(unittest.TestCase):
    def setUp(self):
        base = [blob("rust/a.rs"), blob(".github/workflows/ci.yml")]
        self.trees = {"M": {"truncated": False, "tree": base + [blob(".sandcastle/x.ts", "new")]},
                      "OLD": {"truncated": False, "tree": base + [blob(".sandcastle/x.ts", "old")]}}
        self.key = M.tree_key(lambda p: self.trees["OLD"], R, "OLD", SKIP)

    def fake(self, runs=None, artifacts=None, prs=None, **kw):
        return Fake(self.trees, runs if runs is not None else [run()],
                    artifacts if artifacts is not None else [art(self.key)],
                    prs if prs is not None else [pr()], **kw)

    def decide(self, api, current=99):
        return M.decide(api, R, "M", "br", current, SKIP)

    def test_key_ignores_skip_set_only(self):
        self.assertEqual(M.tree_key(lambda p: self.trees["M"], R, "M", SKIP), self.key)
        self.trees["M"]["tree"][0] = blob("rust/a.rs", "changed")
        self.assertNotEqual(M.tree_key(lambda p: self.trees["M"], R, "M", SKIP), self.key)

    def test_reuses_matching_green_run(self):
        self.assertEqual(self.decide(self.fake()), {"rust": "false", "rust_key": self.key, "reuse": "u/7"})

    def test_rust_change_runs(self):
        self.trees["M"]["tree"][0] = blob("rust/a.rs", "changed")
        self.assertEqual(self.decide(self.fake())["rust"], "true")

    def test_different_github_tree_runs(self):
        self.assertEqual(self.decide(self.fake(roots={"M": "G", "H1": "OTHER"}))["rust"], "true")

    def test_any_pr_of_branch_not_targeting_main_runs(self):
        """opus #2027：run.pull_requests 是查询时现算的；按分支列全部 PR（含已关闭），任一不指向本仓 main 就不复用。"""
        for prs in ([pr(), pr(2, base_ref="evil-base")], [pr(base_repo=2)], []):
            self.assertEqual(self.decide(self.fake(prs=prs))["rust"], "true", prs)

    def test_base_ref_changed_runs(self):
        fake = self.fake(events={1: [{"event": "labeled"}, {"event": "base_ref_changed"}]})
        self.assertEqual(self.decide(fake)["rust"], "true")

    def test_candidate_run_must_be_green_pr_ci_run_of_this_repo(self):
        for r in (run(event="push"), run(conclusion="failure"), run(head_repo_id=2), run(path=".github/workflows/x.yml")):
            self.assertEqual(self.decide(self.fake(runs=[r]))["rust"], "true", r)

    def test_artifact_filters(self):
        for a in (art(self.key, expired=True), art(self.key, branch="other"), art(self.key, head_repo=2), art("other")):
            self.assertEqual(self.decide(self.fake(artifacts=[a]))["rust"], "true", a)

    def test_own_or_newer_run_not_reused(self):
        for current in (7, 6):
            self.assertEqual(self.decide(self.fake(), current)["rust"], "true")

    def test_base_side_github_change_runs(self):
        fake = self.fake(base_files=[".sandcastle/x.ts", ".github/workflows/ci.yml"])
        self.assertEqual(self.decide(fake)["rust"], "true")
        self.assertIn("/compare/H1...B", fake.compare)

    def test_base_side_non_github_change_reuses(self):
        self.assertEqual(self.decide(self.fake(base_files=[".sandcastle/x.ts", "rust/b.rs"]))["rust"], "false")

    def test_truncated_compare_runs(self):
        self.assertEqual(self.decide(self.fake(base_files=["a"] * 300))["rust"], "true")

    def test_truncated_tree_runs_without_key(self):
        self.trees["M"]["truncated"] = True
        self.assertEqual(self.decide(self.fake())["rust_key"], "")

    def test_too_many_pages_runs(self):
        fake = self.fake()
        many = [pr(i) for i in range(100)]

        def endless(path):
            return many if "/pulls?head=" in path else fake(path)
        d = self.decide(endless)
        self.assertEqual((d["rust"], d["rust_key"]), ("true", self.key))

    def test_api_error_runs(self):
        fake = self.fake()

        def boom(path):
            if "/actions/" in path:
                raise RuntimeError("HTTP 502\nbody")
            return fake(path)
        d = self.decide(boom)
        self.assertEqual((d["rust"], d["rust_key"]), ("true", self.key))


if __name__ == "__main__":
    unittest.main()
