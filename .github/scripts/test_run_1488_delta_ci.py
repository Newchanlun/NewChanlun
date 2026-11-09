import importlib.util
import pathlib
import unittest

SPEC = importlib.util.spec_from_file_location(
    "run_1488_delta_ci", pathlib.Path(__file__).with_name("run-1488-delta-ci.py")
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SELECT_BINARY = MODULE.select_binary  # 其他测试会替换 MODULE.select_binary，这里保留原函数

NATIVE = ["default", "s_capture_native_testonly", "s_incremental", "s_session"]


class FeatureClosureTest(unittest.TestCase):
    def test_native_exact_closure_accepted(self):
        MODULE.check_feature_closure("Native", NATIVE)

    def test_native_extra_feature_rejected(self):
        with self.assertRaisesRegex(ValueError, "features 不符"):
            MODULE.check_feature_closure("Native", NATIVE + ["s_allocation_json_testonly"])

    def test_native_missing_incremental_rejected(self):
        with self.assertRaisesRegex(ValueError, "features 不符"):
            MODULE.check_feature_closure(
                "Native", ["default", "s_capture_native_testonly", "s_session"]
            )

    def test_native_legacy_closure_rejected(self):
        legacy = {"default", *MODULE.FEATURES["Native"].split(",")}
        with self.assertRaisesRegex(ValueError, "features 不符"):
            MODULE.check_feature_closure("Native", sorted(legacy))

    def test_plain_and_owned_accepted(self):
        MODULE.check_feature_closure("Plain", ["default", "s_session"])
        MODULE.check_feature_closure(
            "Owned", ["default", "s_allocation_json_testonly", "s_session"]
        )

    def test_closures_cover_requested_features(self):
        self.assertEqual(set(MODULE.FEATURE_CLOSURES), set(MODULE.FEATURES))
        for mode, requested in MODULE.FEATURES.items():
            self.assertLessEqual(
                {"default", *requested.split(",")}, MODULE.FEATURE_CLOSURES[mode]
            )


class ParallelRunTest(unittest.TestCase):
    """#1875 / #1964 独审 Pre-existing：CI_1488_TEST_JOBS>1 的线程池路径。用假的 cargo 与二进制驱动 run_target，
    不执行 Rust。核对：报告顺序 = 计划顺序；估计最长的锁最先提交（LPT）；单条失败被准确汇报；串行路径不受影响。"""

    LOCKS = [
        {"name": "m::a_short", "lane": "A", "target": "bin", "modes": ["Native"]},
        {"name": "m::b_short", "lane": "A", "target": "bin", "modes": ["Native"]},
        {"name": "m::c_long", "lane": "B", "target": "bin", "modes": ["Native"]},
        {"name": "m::d_mid", "lane": "C", "target": "bin", "modes": ["Native"]},
    ]

    def setUp(self):
        import os
        import tempfile
        import threading
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.order = []
        self.lock = threading.Lock()
        self.failing = set()
        self.saved = {k: getattr(MODULE, k, None) for k in
                      ("required_locks", "select_binary", "same_binary", "sha256", "run_logged", "ESTIMATED_SECONDS")}
        self.env = os.environ.get("CI_1488_TEST_JOBS")
        MODULE.required_locks = lambda mode, target: list(self.LOCKS)
        MODULE.select_binary = lambda *a: {"path": "/fake/bin"}
        MODULE.same_binary = lambda binary: None
        MODULE.sha256 = lambda path: "0" * 64
        MODULE.ESTIMATED_SECONDS = {"m::c_long": 600, "m::d_mid": 100}

        def fake_run_logged(argv, cwd, log_path, receipts):
            receipts.append({"argv": argv})
            if "--no-run" in argv:
                log_path.write_text("")
            elif "--list" in argv:
                log_path.write_text("".join(f"{lock['name']}: test\n" for lock in self.LOCKS))
            else:
                name = argv[1]
                with self.lock:
                    self.order.append(name)
                if name in self.failing:
                    log_path.write_text(f"test {name} ... FAILED\n")
                    return 101
                log_path.write_text(f"test {name} ... ok\n"
                                    "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 9 filtered out\n")
            return 0
        MODULE.run_logged = fake_run_logged

    def tearDown(self):
        import os
        import shutil
        for k, v in self.saved.items():
            setattr(MODULE, k, v)
        if self.env is None:
            os.environ.pop("CI_1488_TEST_JOBS", None)
        else:
            os.environ["CI_1488_TEST_JOBS"] = self.env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_with(self, jobs):
        import os
        os.environ["CI_1488_TEST_JOBS"] = str(jobs)
        report = {"targets": {}}
        ok = MODULE.run_target(self.tmp, self.tmp, self.tmp, "bin", "Native", report)
        return ok, report["targets"]["bin"]

    def test_parallel_report_keeps_plan_order_and_all_pass(self):
        ok, result = self.run_with(4)
        self.assertTrue(ok)
        self.assertEqual([t["name"] for t in result["tests"]], [lock["name"] for lock in self.LOCKS])
        self.assertTrue(all(t["success"] for t in result["tests"]))

    def test_parallel_submits_longest_estimate_first(self):
        self.run_with(1)  # 串行：按计划顺序
        self.assertEqual(self.order, ["m::a_short", "m::b_short", "m::c_long", "m::d_mid"])
        self.order.clear()
        self.assertEqual([item[1]["name"] for item in MODULE.submission_order(
            [(i, lock, {}) for i, lock in enumerate(self.LOCKS)])],
            ["m::c_long", "m::d_mid", "m::a_short", "m::b_short"])

    def test_parallel_pool_receives_longest_first(self):
        """线程池换成「提交即同步执行」的执行器，执行顺序即提交顺序，与线程调度无关。"""
        import concurrent.futures

        class Inline:
            def __init__(self, max_workers):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def submit(self, fn, *args):
                future = concurrent.futures.Future()
                fn(*args)
                future.set_result(None)
                return future

        saved = MODULE.concurrent.futures.ThreadPoolExecutor
        MODULE.concurrent.futures.ThreadPoolExecutor = Inline
        try:
            ok, result = self.run_with(4)
        finally:
            MODULE.concurrent.futures.ThreadPoolExecutor = saved
        self.assertTrue(ok)
        self.assertEqual(self.order, ["m::c_long", "m::d_mid", "m::a_short", "m::b_short"])
        self.assertEqual([t["name"] for t in result["tests"]], [lock["name"] for lock in self.LOCKS])

    def test_parallel_single_failure_is_reported_in_plan_order(self):
        self.failing = {"m::d_mid", "m::a_short"}
        ok, result = self.run_with(4)
        self.assertFalse(ok)
        self.assertIn("['m::a_short', 'm::d_mid']", result["error"])
        failed = [t["name"] for t in result["tests"] if not t["success"]]
        self.assertEqual(failed, ["m::a_short", "m::d_mid"])

    def test_estimates_only_name_real_locks(self):
        saved = self.saved["ESTIMATED_SECONDS"] or {}
        names = {lock["name"] for lock in MODULE.LOCKS}
        self.assertEqual([n for n in saved if n not in names], [])


if __name__ == "__main__":
    unittest.main()


class EaccesRetryLogTest(unittest.TestCase):
    """#2025：cargo-eacces-retry.sh 重试成功后，构建日志里先失败、后成功；只认重试标记之后那次。"""

    def _fixture(self):
        import json, os, stat, tempfile
        root = pathlib.Path(tempfile.mkdtemp())
        rust = root / "rust"
        target = rust / "target"
        (target / "debug" / "deps").mkdir(parents=True)
        exe = target / "debug" / "deps" / "s_structure_session-abc"
        exe.write_bytes(b"#!/bin/sh\n")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
        artifact = {"reason": "compiler-artifact", "profile": {"test": True}, "executable": str(exe),
                    "features": ["default", "s_session"], "fresh": False,
                    "target": {"name": "s_structure_session", "kind": ["bin"],
                               "src_path": str(rust / "src/bin/s_structure_session.rs")},
                    "manifest_path": str(rust / "Cargo.toml")}
        failed = json.dumps({"reason": "build-finished", "success": False})
        ok = "\n".join([json.dumps(artifact), json.dumps({"reason": "build-finished", "success": True})])
        return rust, target, failed, ok

    def test_retry_marker_keeps_only_last_attempt(self):
        rust, target, failed, ok = self._fixture()
        marker = MODULE.EACCES_RETRY_MARKER + "host=box could not execute process `x/build-script-build`"
        log = "\n".join([failed, marker, ok])
        self.assertEqual(SELECT_BINARY(log, rust, target, "bin", "Plain")["features"], ["default", "s_session"])

    def test_two_attempts_without_marker_still_rejected(self):
        rust, target, failed, ok = self._fixture()
        with self.assertRaisesRegex(ValueError, "未唯一声明成功完成"):
            SELECT_BINARY("\n".join([failed, ok]), rust, target, "bin", "Plain")
