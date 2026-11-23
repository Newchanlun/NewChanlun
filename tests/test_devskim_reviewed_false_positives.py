"""#1488：精确误报豁免不得吞掉同三元键的新结果。"""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

original_spec = importlib.util.spec_from_file_location(
    "original_devskim_gate_tests", Path(__file__).with_name("test_devskim_sarif_gate.py")
)
original = importlib.util.module_from_spec(original_spec)
original_spec.loader.exec_module(original)

HELPER = Path(__file__).resolve().parents[1] / "scripts/devskim_reviewed_false_positives.py"
spec = importlib.util.spec_from_file_location("reviewed_fp", HELPER)
fp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fp)

_BASELINE_JSON = json.dumps({"schema": "devskim-baseline/v1", "findings": []})


class TestReviewedFalsePositives(unittest.TestCase):
    run_gate = original.TestDevskimSarifGate.run_gate
    write_scan = original.TestDevskimSarifGate.write_scan

    def setUp(self):
        original.TestDevskimSarifGate.setUp(self)
        self.source = self.root / "evidence.json"
        self.source.write_text('{"kind":"fixture"}\n')
        self.record = original.finding("evidence.json")
        self.record["locations"][0]["physicalLocation"]["region"].update({
            "startColumn": 2, "endLine": 1, "endColumn": 8,
            "snippet": {"text": "fixture"},
        })
        self.allow = self.root / "allow.json"
        self.manifest = {"schema": "devskim-reviewed-false-positives/v1", "issue": 1488,
                         "files": [{"path": "evidence.json",
                                    "sha256_bytes": list(hashlib.sha256(self.source.read_bytes()).digest()),
                                    "results": [{"rule": "DS000001", "identity_bytes": list(fp.identity(self.record))}]}]}
        self.write_allow()
        self.baseline.write_text(_BASELINE_JSON)
        self.write_scan([self.record])

    def write_allow(self):
        self.allow.write_text(json.dumps(self.manifest))

    def reviewed_gate(self, *extra):
        return self.run_gate("--baseline", str(self.baseline), "--false-positives",
                             str(self.allow), "--source-root", str(self.root), *extra)

    def _run_isolated_gate(
        self,
        name: str,
        *,
        results: list[dict] | None = None,
        manifest: dict | None = None,
        allow_text: str | None = None,
        source_text: str | None = '{"kind":"fixture"}\n',
        extra: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess:
        case_dir = self.root / name
        case_dir.mkdir()
        source = case_dir / "evidence.json"
        if source_text is not None:
            source.write_text(source_text)
        sarif = case_dir / "results.json"
        sarif.write_text(json.dumps({
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "devskim", "version": "1.0.90"}},
                "results": [self.record] if results is None else results,
            }],
        }, ensure_ascii=False), encoding="utf-8")
        allow = case_dir / "allow.json"
        if allow_text is not None:
            allow.write_text(allow_text)
        else:
            allow.write_text(json.dumps(self.manifest if manifest is None else manifest))
        return subprocess.run(
            [original.BASH, str(original.SCRIPT), "--sarif", str(sarif),
             "--scanner-outcome", "success", "--artifact-name", "test-sarif",
             "--artifact-outcome", "success", "--retention-days", "14",
             "--baseline", str(self.baseline), "--false-positives", str(allow),
             "--source-root", str(case_dir), *extra],
            capture_output=True, timeout=30, check=False,
        )

    def test_exact_result_passes_and_preserves_raw_scan(self):
        original_bytes = self.sarif.read_bytes()
        result = self.reviewed_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"Reviewed false-positive results:** `1`", result.stdout)
        self.assertEqual(self.sarif.read_bytes(), original_bytes)

    def test_same_old_key_new_position_or_snippet_stays_red(self):
        cases = [("startColumn", 3), ("endColumn", 9), ("snippet", {"text": "new finding"})]

        def run_case(item):
            field, value = item
            changed = copy.deepcopy(self.record)
            changed["locations"][0]["physicalLocation"]["region"][field] = value
            return field, self._run_isolated_gate(f"pos-{field}", results=[self.record, changed])

        with ThreadPoolExecutor(max_workers=len(cases)) as pool:
            outcomes = list(pool.map(run_case, cases))
        for field, result in outcomes:
            with self.subTest(field=field):
                self.assertEqual(result.returncode, 1)
                self.assertIn(b"DS000001|evidence.json|1", result.stdout)

    def test_new_rule_stays_red(self):
        changed = copy.deepcopy(self.record)
        changed["ruleId"] = "DS000002"
        self.write_scan([self.record, changed])
        self.assertEqual(self.reviewed_gate().returncode, 1)

    def test_file_drift_and_missing_file_fail(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            drift = pool.submit(self._run_isolated_gate, "drift", source_text="changed")
            missing = pool.submit(self._run_isolated_gate, "missing", source_text=None)
            self.assertEqual(drift.result().returncode, 1)
            self.assertEqual(missing.result().returncode, 1)

    def test_escape_paths_fail(self):
        names = ["../evidence.json", str(self.source), "./evidence.json"]

        def run_case(item):
            idx, name = item
            manifest = copy.deepcopy(self.manifest)
            manifest["files"][0]["path"] = name
            return name, self._run_isolated_gate(f"escape-{idx}", manifest=manifest)

        with ThreadPoolExecutor(max_workers=len(names)) as pool:
            outcomes = list(pool.map(run_case, enumerate(names)))
        for name, result in outcomes:
            with self.subTest(name=name):
                self.assertEqual(result.returncode, 1)

    def test_symlink_escape_fails(self):
        self.source.unlink()
        self.source.symlink_to(HELPER)
        self.assertEqual(self.reviewed_gate().returncode, 1)

    def test_bad_schema_and_identity_fail(self):
        bad_schema = copy.deepcopy(self.manifest)
        bad_schema["schema"] = "other"
        bad_sha = copy.deepcopy(self.manifest)
        bad_sha["files"][0]["sha256_bytes"] = [0]
        with ThreadPoolExecutor(max_workers=3) as pool:
            r1 = pool.submit(self._run_isolated_gate, "bad-schema", manifest=bad_schema)
            r2 = pool.submit(self._run_isolated_gate, "bad-sha", manifest=bad_sha)
            r3 = pool.submit(self._run_isolated_gate, "bad-json", allow_text="{")
            self.assertEqual(r1.result().returncode, 1)
            self.assertEqual(r2.result().returncode, 1)
            self.assertEqual(r3.result().returncode, 1)

    def test_scan_upload_and_tool_failures_are_not_exempt(self):
        cases = [
            ("--scanner-outcome", "failure"),
            ("--artifact-outcome", "failure"),
            ("--expected-tool-version", "other"),
        ]
        with ThreadPoolExecutor(max_workers=len(cases)) as pool:
            outcomes = list(pool.map(
                lambda item: (item[0], self.reviewed_gate(item[0], item[1])),
                cases,
            ))
        for option, result in outcomes:
            with self.subTest(option=option):
                self.assertEqual(result.returncode, 1)

    def test_unconfigured_keeps_original_red(self):
        result = self.run_gate("--baseline", str(self.baseline))
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(b"Reviewed false-positive results", result.stdout)

    def test_source_root_without_manifest_fails(self):
        self.write_scan([])
        self.assertEqual(self.run_gate("--source-root", str(self.root)).returncode, 1)

    def test_manifest_without_source_root_fails(self):
        self.assertEqual(self.run_gate("--false-positives", str(self.allow)).returncode, 1)


if __name__ == "__main__":
    unittest.main()
