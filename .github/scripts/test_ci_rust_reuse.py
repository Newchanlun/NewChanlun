"""ci-rust-reuse.py 的判定：指纹只排除跳过集；同 PR 分支、本仓库、未过期 artifact、.github 相同才复用；出错一律全跑。"""
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


class Fake:
    def __init__(self, trees, roots, runs, artifacts, base_files=()):
        self.trees, self.roots, self.runs, self.artifacts, self.calls = trees, roots, runs, artifacts, []
        self.base_files = list(base_files)

    def __call__(self, path):
        self.calls.append(path)
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
        if "/actions/workflows/" in path:
            return {"workflow_runs": self.runs}
        if "/artifacts?name=" in path:
            run_id = int(path.split("/runs/")[1].split("/")[0])
            return {"artifacts": self.artifacts.get(run_id, [])}
        raise AssertionError(path)


def run(i, head="H1", repo_id=1, head_repo_id=1):
    return {"id": i, "head_sha": head, "html_url": f"u/{i}", "repository": {"id": repo_id},
            "head_repository": {"id": head_repo_id}}


class ReuseTest(unittest.TestCase):
    def setUp(self):
        base = [blob("rust/a.rs"), blob(".github/workflows/ci.yml")]
        self.trees = {"M": {"truncated": False, "tree": base + [blob(".sandcastle/x.ts", "new")]},
                      "OLD": {"truncated": False, "tree": base + [blob(".sandcastle/x.ts", "old")]}}
        self.key = M.tree_key(lambda p: self.trees["OLD"], R, "OLD", SKIP)

    def fake(self, runs, artifacts=None, roots=None, base_files=()):
        art = artifacts if artifacts is not None else {7: [{"name": M.ARTIFACT_PREFIX + self.key, "expired": False}]}
        return Fake(self.trees, roots or {"M": "G", "H1": "G"}, runs, art, base_files)

    def test_key_ignores_skip_set_only(self):
        self.assertEqual(M.tree_key(lambda p: self.trees["M"], R, "M", SKIP), self.key)
        self.trees["M"]["tree"][0] = blob("rust/a.rs", "changed")
        self.assertNotEqual(M.tree_key(lambda p: self.trees["M"], R, "M", SKIP), self.key)

    def test_reuses_matching_green_run(self):
        d = M.decide(self.fake([run(7)]), R, "M", "br", 99, SKIP)
        self.assertEqual(d, {"rust": "false", "rust_key": self.key, "reuse": "u/7"})

    def test_rust_change_runs(self):
        self.trees["M"]["tree"][0] = blob("rust/a.rs", "changed")
        self.assertEqual(M.decide(self.fake([run(7)]), R, "M", "br", 99, SKIP)["rust"], "true")

    def test_different_github_tree_runs(self):
        d = M.decide(self.fake([run(7)], roots={"M": "G", "H1": "OTHER"}), R, "M", "br", 99, SKIP)
        self.assertEqual(d["rust"], "true")

    def test_base_side_github_change_runs(self):
        """kimi #2027：那次 run 测的是 merge(head, 当时 base)；base 一侧改过 .github 时不能用 head 的 .github 代表它。"""
        fake = self.fake([run(7)], base_files=[".sandcastle/x.ts", ".github/workflows/ci.yml"])
        self.assertEqual(M.decide(fake, R, "M", "br", 99, SKIP)["rust"], "true")
        self.assertIn("/compare/H1...B", fake.compare)

    def test_base_side_non_github_change_reuses(self):
        fake = self.fake([run(7)], base_files=[".sandcastle/x.ts", "rust/b.rs"])
        self.assertEqual(M.decide(fake, R, "M", "br", 99, SKIP)["rust"], "false")

    def test_truncated_compare_runs(self):
        fake = self.fake([run(7)], base_files=["a"] * 300)
        self.assertEqual(M.decide(fake, R, "M", "br", 99, SKIP)["rust"], "true")

    def test_fork_run_ignored(self):
        self.assertEqual(M.decide(self.fake([run(7, head_repo_id=2)]), R, "M", "br", 99, SKIP)["rust"], "true")

    def test_expired_or_missing_artifact_runs(self):
        for art in ({7: [{"name": M.ARTIFACT_PREFIX + self.key, "expired": True}]}, {7: []}):
            self.assertEqual(M.decide(self.fake([run(7)], art), R, "M", "br", 99, SKIP)["rust"], "true")

    def test_own_or_newer_run_not_reused(self):
        for current in (7, 6):
            self.assertEqual(M.decide(self.fake([run(7)]), R, "M", "br", current, SKIP)["rust"], "true")

    def test_truncated_tree_runs_without_key(self):
        self.trees["M"]["truncated"] = True
        self.assertEqual(M.decide(self.fake([run(7)]), R, "M", "br", 99, SKIP)["rust_key"], "")

    def test_api_error_runs(self):
        def boom(path):
            if "/actions/" in path:
                raise RuntimeError("HTTP 502\nbody")
            return self.fake([])(path)
        d = M.decide(boom, R, "M", "br", 99, SKIP)
        self.assertEqual((d["rust"], d["rust_key"]), ("true", self.key))


if __name__ == "__main__":
    unittest.main()
