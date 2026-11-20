import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("check-prod-no-test-hooks.py")
SPEC = importlib.util.spec_from_file_location("check_prod_no_test_hooks", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class RawSqlAxisTests(unittest.TestCase):
    def check_files(self, files: dict[str, str]) -> list[str]:
        gen = checker.load_gen()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for rel, content in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            with patch.object(gen, "CRATE_ROOTS", ("src/lib.rs",)), \
                 patch.object(gen._checker, "ROOTS", ("src",)):
                return checker.raw_sql_violations(root)

    def test_prod_fn_reports_each_forbidden_literal_with_file_and_line(self):
        lib = (
            "pub fn run() {\n"
            '    let _ = "ROLLBACK TO x";\n'
            '    let _ = "PRAGMA main.schema_version=1";\n'
            '    let _ = "SAVEPOINT s";\n'
            "}\n"
        )
        found = self.check_files({"src/lib.rs": lib})
        self.assertEqual(len(found), 3, found)
        self.assertTrue(found[0].startswith("src/lib.rs:2:"), found)
        self.assertTrue(found[1].startswith("src/lib.rs:3:"), found)
        self.assertTrue(found[2].startswith("src/lib.rs:4:"), found)

    def test_case_insensitive_whitespace_raw_string_and_incremental_feature_reported(self):
        lib = (
            '#[cfg(feature = "s_incremental")]\n'
            "pub fn run() {\n"
            '    let _ = "savepoint sp1";\n'
            '    let _ = "rollback   to sp1";\n'
            '    let _ = r#"pragma temp.SCHEMA_VERSION = 2"#;\n'
            "}\n"
        )
        found = self.check_files({"src/lib.rs": lib})
        self.assertEqual(len(found), 3, found)
        self.assertTrue(found[0].startswith("src/lib.rs:3:"), found)
        self.assertTrue(found[1].startswith("src/lib.rs:4:"), found)
        self.assertTrue(found[2].startswith("src/lib.rs:5:"), found)

    def test_inline_cfg_test_mod_reports_zero(self):
        lib = (
            "#[cfg(test)]\n"
            "mod tests {\n"
            "    fn helper() {\n"
            '        let _ = "ROLLBACK TO x";\n'
            '        let _ = "PRAGMA main.schema_version=1";\n'
            '        let _ = "SAVEPOINT s";\n'
            "    }\n"
            "}\n"
        )
        self.assertEqual(self.check_files({"src/lib.rs": lib}), [])

    def test_function_level_cfg_test_reports_zero_and_following_prod_fn_still_reported(self):
        lib = (
            "#[cfg(test)]\n"
            "fn helper() -> Result<Option<String>, String> {\n"
            '    let _ = "ROLLBACK TO x";\n'
            '    let _ = "PRAGMA main.schema_version=1";\n'
            '    let _ = "SAVEPOINT s";\n'
            "    Ok(None)\n"
            "}\n"
            "pub fn after_test() {\n"
            '    let _ = "SAVEPOINT prod_hit";\n'
            "}\n"
        )
        found = self.check_files({"src/lib.rs": lib})
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0].startswith("src/lib.rs:9:"), found)

    def test_external_cfg_test_mod_file_reports_zero_while_prod_submod_reported(self):
        lib = (
            "#[cfg(test)]\n"
            "mod ext_tests;\n"
            "mod prod_sub;\n"
        )
        ext_tests = (
            "fn helper() {\n"
            '    let _ = "ROLLBACK TO x";\n'
            '    let _ = "PRAGMA main.schema_version=1";\n'
            '    let _ = "SAVEPOINT s";\n'
            "}\n"
        )
        prod_sub = (
            "pub fn run() {\n"
            '    let _ = "SAVEPOINT sub_hit";\n'
            "}\n"
        )
        found = self.check_files({
            "src/lib.rs": lib,
            "src/ext_tests.rs": ext_tests,
            "src/prod_sub.rs": prod_sub,
        })
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0].startswith("src/prod_sub.rs:2:"), found)

    def test_equality_non_literal_assignment_and_comments_report_zero(self):
        lib = (
            "pub fn safe(active: &mut State, next: &State) -> bool {\n"
            '    let _ = "schema_version == x";\n'
            '    let _ = "schema_version==1";\n'
            '    let _ = "schema_version != 1";\n'
            '    let _ = "PRAGMA main.schema_version";\n'
            '    let _ = "rollback total";\n'
            '    let _ = "savepoints";\n'
            "    // SAVEPOINT s; ROLLBACK TO x; PRAGMA main.schema_version=1\n"
            "    /* SAVEPOINT s\n"
            "       ROLLBACK TO x\n"
            "       schema_version = 1 */\n"
            '    #[allow(dead_code, reason = "SAVEPOINT s")]\n'
            "    let _ = 1;\n"
            "    active.schema_version = next.schema_version;\n"
            "    active.schema_version == next.schema_version\n"
            "}\n"
        )
        self.assertEqual(self.check_files({"src/lib.rs": lib}), [])

    def test_testonly_feature_gate_reports_zero(self):
        lib = (
            '#[cfg(feature = "s_capture_native_testonly")]\n'
            "pub fn diag() {\n"
            '    let _ = "ROLLBACK TO x";\n'
            '    let _ = "PRAGMA main.schema_version=1";\n'
            '    let _ = "SAVEPOINT s";\n'
            "}\n"
        )
        self.assertEqual(self.check_files({"src/lib.rs": lib}), [])

    def test_multiline_comments_attributes_and_raw_strings_keep_exact_line_number(self):
        lib = (
            "/* block comment\n"
            '   with "SAVEPOINT" inside\n'
            "   and nested /* comment */ end */\n"
            "#[allow(\n"
            '    dead_code,\n'
            '    reason = "multiline attr"\n'
            ")]\n"
            "pub fn run() {\n"
            '    let _ = b"bytes";\n'
            "    let _ = '\"';\n"
            '    let _ = r#"\n'
            "        benign multiline\n"
            '    "#;\n'
            '    let _ = "SAVEPOINT exact_line";\n'
            "}\n"
        )
        found = self.check_files({"src/lib.rs": lib})
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0].startswith("src/lib.rs:14:"), found)


if __name__ == "__main__":
    unittest.main()
