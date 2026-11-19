"""ci-rust-reuse.py 的判定：凭据只认那次 run 里服务端渲染的 `rust-green <指纹>` 作业结论；本分支全部 PR 只指向本仓 main、
未改过目标分支；候选 run 本仓库、更早、7 天内；head 的 .github（去掉跳过集）相同且 base 一侧未改；任何出错一律全跑。"""
import datetime
import importlib.util
import pathlib
import re
import unittest

SPEC = importlib.util.spec_from_file_location("reuse", pathlib.Path(__file__).with_name("ci-rust-reuse.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
SKIP = re.compile(r"^(\.sandcastle/.+|package\.json|\.github/devskim/.+)$")
R = "o/r"
NOW = datetime.datetime.now(datetime.timezone.utc)


def blob(path, sha="b1"):
    return {"path": path, "mode": "100644", "type": "blob", "sha": sha}


def pr(number=1, base_ref="main", base_repo=1, head_repo=1):
    return {"number": number, "base": {"ref": base_ref, "repo": {"id": base_repo}}, "head": {"repo": {"id": head_repo}}}


def run(i=7, head="H1", head_repo_id=1, age_days=0):
    created = (NOW - datetime.timedelta(days=age_days)).isoformat().replace("+00:00", "Z")
    return {"id": i, "head_sha": head, "html_url": f"u/{i}", "created_at": created,
            "repository": {"id": 1}, "head_repository": {"id": head_repo_id}}


class Fake:
    def __init__(self, trees, runs, jobs, prs, events=None, base_files=()):
        self.trees, self.runs, self.jobs, self.prs = trees, runs, jobs, prs
        self.events = events or {}
        self.base_files = list(base_files)
        self.compare = None

    def __call__(self, path):
        if "/git/trees/" in path:
            return self.trees[path.split("/git/trees/")[1].split("?")[0]]
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
        if "/jobs?" in path:
            jobs = self.jobs.get(int(path.split("/actions/runs/")[1].split("/")[0]), [])
            return {"total_count": len(jobs), "jobs": jobs}
        if "/actions/workflows/ci.yml/runs?" in path:
            return {"workflow_runs": self.runs}
        raise AssertionError(path)


class ReuseTest(unittest.TestCase):
    def setUp(self):
        common = [blob("rust/a.rs"), blob(".github/workflows/ci.yml")]
        self.trees = {"M": {"truncated": False, "tree": common + [blob(".sandcastle/x.ts", "new")]},
                      "H1": {"truncated": False, "tree": common + [blob(".sandcastle/x.ts", "old")]}}
        self.key = M.digest(M.tree_entries(lambda p: self.trees["H1"], R, "H1", SKIP))

    def green(self, key=None, conclusion="success"):
        return {7: [{"name": "ci-ok", "conclusion": "success"},
                    {"name": M.GREEN_JOB + (key or self.key), "conclusion": conclusion}]}

    def fake(self, runs=None, jobs=None, prs=None, **kw):
        return Fake(self.trees, runs if runs is not None else [run()], jobs if jobs is not None else self.green(),
                    prs if prs is not None else [pr()], **kw)

    def decide(self, api, current=99):
        return M.decide(api, R, "M", "br", current, SKIP)

    def test_key_ignores_skip_set_only(self):
        key = lambda t: M.digest(M.tree_entries(lambda p: self.trees[t], R, t, SKIP))
        self.assertEqual(key("M"), self.key)
        self.trees["M"]["tree"][0] = blob("rust/a.rs", "changed")
        self.assertNotEqual(key("M"), self.key)

    def test_key_encoding_is_unambiguous(self):
        """kimi #2027：文件名可含换行、制表符；一个改名条目不能与两个原条目序列化成同一串字节。"""
        two = [["rust/a.rs", "100644", "blob", "A"], ["rust/b.rs", "100644", "blob", "B"]]
        forged = [["rust/a.rs 100644 blob A\nrust/b.rs", "100644", "blob", "B"]]
        forged2 = [["rust/a.rs\t100644\tblob\tA\nrust/b.rs", "100644", "blob", "B"]]
        self.assertNotIn(M.digest(two), {M.digest(forged), M.digest(forged2)})

    def test_reuses_matching_green_run(self):
        self.assertEqual(self.decide(self.fake()), {"rust": "false", "rust_key": self.key, "reuse": "u/7"})

    def test_evidence_is_green_job_not_anything_else(self):
        """opus #2027：凭据只能是服务端渲染的 rust-green <指纹> 作业且 success；名字不对、失败、跳过都不认。"""
        for jobs in (self.green(key="other"), self.green(conclusion="skipped"), self.green(conclusion="failure"),
                     {7: [{"name": "ci-ok", "conclusion": "success"}]}):
            self.assertEqual(self.decide(self.fake(jobs=jobs))["rust"], "true", jobs)

    def test_rust_change_runs(self):
        self.trees["M"]["tree"][0] = blob("rust/a.rs", "changed")
        self.assertEqual(self.decide(self.fake())["rust"], "true")

    def test_github_change_runs_even_with_matching_green_job(self):
        """opus #2027 第五轮：作业名用本次指纹，只有 head 的 .github 不同，必须由第 2 条拒绝（不能靠作业名对不上顺带拒绝）。"""
        self.trees["H1"]["tree"][1] = blob(".github/workflows/ci.yml", "evil")
        self.assertEqual(self.decide(self.fake(jobs=self.green(key=self.key)))["rust"], "true")

    def test_skip_set_inside_github_does_not_block_reuse(self):
        self.trees["H1"]["tree"].append(blob(".github/devskim/x.json"))
        self.trees["M"]["tree"].append(blob(".github/devskim/x.json", "other"))
        self.assertEqual(self.decide(self.fake())["rust"], "false")

    def test_skip_set_uses_fullmatch(self):
        """Python 的 $ 在末尾换行符前也匹配；文件名 'package.json\\n' 不在跳过集里，必须计入指纹。"""
        skip = re.compile(r"^(package\.json)$")
        entries = M.tree_entries(lambda p: {"truncated": False, "tree": [blob("package.json\n")]}, R, "X", skip)
        self.assertEqual([e[0] for e in entries], ["package.json\n"])

    def test_any_pr_of_branch_not_targeting_main_runs(self):
        """opus #2027：run.pull_requests 是查询时现算的；按分支列全部 PR（含已关闭），任一不指向本仓 main 就不复用。"""
        for prs in ([pr(), pr(2, base_ref="evil-base")], [pr(base_repo=2)], []):
            self.assertEqual(self.decide(self.fake(prs=prs))["rust"], "true", prs)

    def test_any_base_change_event_runs(self):
        """栈式 PR 的目标分支被合入删除后，GitHub 自动改指 main，记的是 automatic_base_change_*，不是 base_ref_changed。"""
        for ev in ("base_ref_changed", "automatic_base_change_succeeded", "automatic_base_change_failed"):
            fake = self.fake(events={1: [{"event": "labeled"}, {"event": ev}]})
            self.assertEqual(self.decide(fake)["rust"], "true", ev)

    def test_deadline_runs_full(self):
        """总时限：假时钟在指纹算完后走过时限，后续查询必须抛错、按全跑（删掉 left<=0 判断时本例失败）。"""
        fake, now = self.fake(), [0.0]

        def call(path):
            now[0] += 100  # 每次查询耗 100 s
            return fake(path)
        d = self.decide(M.deadline_api(120, clock=lambda: now[0], call=call))
        self.assertEqual((d["rust"], d["rust_key"]), ("true", self.key))
        self.assertIn("deadline", d["reuse"])

    def test_within_deadline_reuses(self):
        fake = self.fake()
        self.assertEqual(self.decide(M.deadline_api(120, clock=lambda: 0.0, call=fake))["rust"], "false")

    def test_run_filters(self):
        for r in (run(head_repo_id=2), run(age_days=8)):
            self.assertEqual(self.decide(self.fake(runs=[r]))["rust"], "true", r)

    def test_own_or_newer_run_not_reused(self):
        for current in (7, 6):
            self.assertEqual(self.decide(self.fake(), current)["rust"], "true")

    def test_base_side_github_change_runs(self):
        fake = self.fake(base_files=[".sandcastle/x.ts", ".github/workflows/ci.yml"])
        self.assertEqual(self.decide(fake)["rust"], "true")
        self.assertIn("/compare/H1...B", fake.compare)

    def test_base_side_check_uses_fullmatch(self):
        """base 一侧改了名为 '.github/devskim/x\\n' 之外的 .github 文件：用 match 会被 $ 在换行前匹配误判为跳过集。"""
        skip = re.compile(r"^(\.sandcastle/.+|package\.json|\.github/devskim/x)$")
        fake = self.fake(base_files=[".github/devskim/x\n"])
        self.assertTrue(M.base_side_touches_github(fake, R, "H1", "B", skip))

    def test_base_side_skip_set_or_non_github_change_reuses(self):
        fake = self.fake(base_files=[".sandcastle/x.ts", "rust/b.rs", ".github/devskim/y.json"])
        self.assertEqual(self.decide(fake)["rust"], "false")

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

    def test_truncated_jobs_list_runs(self):
        fake = self.fake()

        def truncated(path):
            got = fake(path)
            return {**got, "total_count": 500} if "/jobs?" in path else got
        self.assertEqual(self.decide(truncated)["rust"], "true")

    def test_api_error_runs(self):
        fake = self.fake()

        def boom(path):
            if "/actions/" in path:
                raise RuntimeError("HTTP 502\nbody")
            return fake(path)
        d = self.decide(boom)
        self.assertEqual((d["rust"], d["rust_key"]), ("true", self.key))


class WorkflowConsistencyTest(unittest.TestCase):
    """rust-green 必须依赖 ci-ok 认定的全部 Rust 作业（#2018 删 rust-test-backtest-bin 时 needs 悬空过）。"""

    def test_rust_green_needs_match_ci_ok_rust_jobs(self):
        text = pathlib.Path(__file__).resolve().parents[1].joinpath("workflows/ci.yml").read_text()
        block = text[text.index("\n  rust-green:\n"):]
        needs_block = block[block.index("    needs:\n") + len("    needs:\n"):]
        needs = set()
        for line in needs_block.splitlines():
            m = re.match(r"^      - ([A-Za-z0-9_-]+)$", line)
            if not m:
                break
            needs.add(m.group(1))
        rust_jobs = set(re.findall(r'"([A-Za-z0-9_-]+)"', re.search(r"rust_jobs = \{([^}]*)\}", text).group(1)))
        jobs = set(re.findall(r"^  ([A-Za-z0-9_-]+):$", text, re.M))
        self.assertTrue(rust_jobs, "ci-ok 的 rust_jobs 解析为空")
        self.assertEqual(needs - {"changes"}, rust_jobs)
        self.assertLessEqual(needs, jobs, "rust-green 依赖了不存在的作业")


if __name__ == "__main__":
    unittest.main()
