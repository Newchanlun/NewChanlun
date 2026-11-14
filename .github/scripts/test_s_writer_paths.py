#!/usr/bin/env python3
"""#1855：s_writer_paths.py 的判定样例与派生路径锁（在 rust-check 里跑）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import s_writer_paths as w  # noqa: E402


class StaticSet(unittest.TestCase):
    def test_writer_paths(self):
        for path in [
            "rust/src/bin/s_structure_session.rs",
            "rust/src/bin/s_session_v3/driver.rs",
            "rust/src/bin/s_session_v2/mod.rs",
            "rust/src/theta_v0/parser/inclusion.rs",
            "rust/src/brand_new_module.rs",
            "rust/Cargo.lock",
            "rust/tests/fixtures/x.json",
            "s_session/catalog/signed-catalog.json",
            "s_session/tests/fixtures/tb02d/raw-ledger.json",
            "s_session/tests/issue1527_recovery/test_support.rs",
            ".github/actions/rust-job-setup/action.yml",
            ".github/scripts/run-cargo-with-telemetry.sh",
            ".github/scripts/cargo-eacces-retry.sh",
            ".github/workflows/w2-cold-locks.yml",
        ]:
            self.assertTrue(w.static_hit(path), path)

    def test_paths_the_writer_never_reads(self):
        for path in [
            "rust/src/economic_session/service.rs",
            "rust/src/bin/x_execution_session.rs",
            "rust/src/bin/pi_bsp_timing/main.rs",
            "rust/src/lav_seal/mod.rs",
            "rust/src/segment_tangency_tests.rs",
            "rust/tests/nest_isolation_guard.rs",
            "docs/adr/0042-s-writer-incremental-production-path.md",
            ".github/workflows/ci.yml",
        ]:
            self.assertFalse(w.static_hit(path), path)


class DerivedSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tracked = w.tracked_files(ROOT)
        cls.derived = w.derived_paths(ROOT, cls.tracked)

    def test_known_lock_inputs_are_derived(self):
        # 阻断 2 的两处：CD 冷锁运行时读的夹具，以及经 #[path] 引入的 job limits。
        for path in [
            "s_session/tests/fixtures/tb02d/raw-ledger.json",
            "s_session/tests/issue1527_recovery/test_support.rs",
        ]:
            self.assertIn(path, self.derived, path)

    def test_every_derived_path_is_a_writer_path(self):
        changed = sorted(self.derived)
        self.assertEqual(w.s_writer_files(changed, ROOT), changed)

    def test_a_pr_touching_only_raw_ledger_runs_the_locks(self):
        changed = ["s_session/tests/fixtures/tb02d/raw-ledger.json"]
        self.assertEqual(w.s_writer_files(changed, ROOT), changed)

    def test_derived_set_is_what_extends_the_static_one(self):
        # 静态集合外、只经派生进入的文件：改它们同样要跑冷锁。
        extra = sorted(p for p in self.derived if not w.static_hit(p))
        self.assertEqual(w.s_writer_files(extra, ROOT), extra)

    def test_docs_only_change_skips_the_locks(self):
        self.assertEqual(w.s_writer_files(["docs/agents/issue-tracker.md", "README.md"], ROOT), [])


if __name__ == "__main__":
    unittest.main()
