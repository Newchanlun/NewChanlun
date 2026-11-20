import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-prod-no-test-hooks.py")
SPEC = importlib.util.spec_from_file_location("check_prod_no_test_hooks_meta", SCRIPT)
_meta = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_meta)

ROOTS_SKELETON = _meta.ROOTS
ENTRY = "rust/src/bin/s_structure_session.rs"
OWNER = "rust/src/bin/s_session_v3/audit_owner.rs"
LIB = "rust/src/lib.rs"
OWNER_HEADER = '#[path = "s_session_v3/audit_owner.rs"]\nmod audit_owner;\n'
SAVEPOINT_FN = 'fn review_case() {\n    let _ = "SAVEPOINT s";\n}\n'
SAVEPOINT_CONST = 'const NOTE: &str = "SAVEPOINT";\n'
ROLLBACK_CONST = 'const A: &str = "ROLLBACK TO";\n'
ALLOWLISTED_PATH = "rust/src/theta_v0/venue_fee/datum_io.rs"
ALLOWLISTED_LITERAL = "venue fee datum {}: schema_version={} 不受支持（本实装只认 {}）"


def run_cli(files: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """在临时源码树上通过真实 CLI 入口运行检查器，不替换任何常量、不调用内部函数。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for base in ROOTS_SKELETON:
            target = root / base
            if target.suffix:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            else:
                target.mkdir(parents=True, exist_ok=True)
        for rel, content in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-W", "error", str(SCRIPT), str(root)],
            capture_output=True,
            text=True,
            check=False,
        )


def error_lines(res: subprocess.CompletedProcess[str]) -> list[str]:
    return [line for line in res.stdout.splitlines() if line.startswith("::error::")]


class RawSqlCliBehaviorTests(unittest.TestCase):
    def test_r1_literal_variants_via_cli(self):
        cases = [
            ("plain", '"SAVEPOINT s"', 1),
            ("raw", 'r"ROLLBACK TO s"', 1),
            ("raw_hash", 'r#"SAVEPOINT s"#', 1),
            ("multiline", '"ROLLBACK\n TO s"', 1),
            ("continued", '"SAVE\\\n  POINT s"', 1),
            ("concat", 'concat!("ROLLBACK ", "TO s")', 0),
            ("format", 'format!("{} {}", "ROLLBACK", "TO s")', 0),
            ("format_intact", 'format!("ROLLBACK TO {}", "s")', 1),
            ("mixed", '"SavePoint s"', 1),
            ("spaces", '"rollback   to s"', 1),
            ("schema", '"PRAGMA schema_version = 1"', 1),
            ("qualified", '"PRAGMA main.schema_version=1"', 1),
            ("bytes", 'b"SAVEPOINT s"', 0),
            ("raw_bytes", 'br#"SAVEPOINT s"#', 0),
            ("const", '{ const Q: &str = "SAVEPOINT s"; Q }', 1),
            ("eq", '"schema_version == x"', 0),
        ]
        for name, expr, expected_rc in cases:
            with self.subTest(case=name):
                body = f"fn review_case() {{\n    let _ = {expr};\n}}\n"
                res = run_cli({ENTRY: OWNER_HEADER, OWNER: body})
                self.assertEqual(res.stderr, "")
                self.assertEqual(res.returncode, expected_rc, res.stdout)
                errs = error_lines(res)
                if expected_rc == 1:
                    self.assertEqual(len(errs), 1, errs)
                    self.assertTrue(errs[0].startswith(f"::error::{OWNER}:2:"), errs)
                    self.assertNotIn("\n", errs[0])
                else:
                    self.assertEqual(errs, [])

    def test_r1_field_assignment_comments_diagnostic_and_integration_dir(self):
        cases = [
            (
                "field",
                {
                    ENTRY: OWNER_HEADER,
                    OWNER: "struct State { schema_version: i32 }\nfn update(active: &mut State) { active.schema_version = 1; }\n",
                },
                0,
                None,
            ),
            (
                "comments",
                {
                    ENTRY: OWNER_HEADER,
                    OWNER: '/// SAVEPOINT s\n/** ROLLBACK TO s */\nfn f() { /* schema_version=1 */ /* "SAVEPOINT s" */ }\n',
                },
                0,
                None,
            ),
            (
                "diagnostic",
                {ENTRY: OWNER_HEADER, OWNER: 'fn info() {\n    eprintln!("SAVEPOINT unavailable");\n}\n'},
                1,
                f"::error::{OWNER}:2:",
            ),
            (
                "integration",
                {ENTRY: OWNER_HEADER, "rust/tests/review.rs": SAVEPOINT_FN},
                0,
                None,
            ),
        ]
        for name, files, expected_rc, prefix in cases:
            with self.subTest(case=name):
                res = run_cli(files)
                self.assertEqual(res.stderr, "")
                self.assertEqual(res.returncode, expected_rc, res.stdout)
                errs = error_lines(res)
                if expected_rc == 1:
                    self.assertEqual(len(errs), 1, errs)
                    self.assertTrue(errs[0].startswith(prefix), errs)
                else:
                    self.assertEqual(errs, [])

    def test_r1_prod_fn_reports_all_three_patterns_with_exact_lines(self):
        body = (
            "pub fn run() {\n"
            '    let _ = "ROLLBACK TO x";\n'
            '    let _ = "PRAGMA main.schema_version=1";\n'
            '    let _ = "SAVEPOINT s";\n'
            "}\n"
        )
        res = run_cli({ENTRY: OWNER_HEADER, OWNER: body})
        self.assertEqual(res.returncode, 1, res.stdout)
        errs = error_lines(res)
        self.assertEqual(len(errs), 3, errs)
        self.assertTrue(errs[0].startswith(f"::error::{OWNER}:2:"), errs)
        self.assertTrue(errs[1].startswith(f"::error::{OWNER}:3:"), errs)
        self.assertTrue(errs[2].startswith(f"::error::{OWNER}:4:"), errs)

    def test_r1_cfg_test_mod_fn_and_external_file_rules(self):
        sibling = "rust/src/bin/s_session_v3/shared_review.rs"
        for name, files, expected_rc, prefix in [
            ("test_mod", {ENTRY: OWNER_HEADER, OWNER: f"#[cfg(test)]\nmod tests {{\n{SAVEPOINT_FN}}}\n"}, 0, None),
            ("test_fn", {ENTRY: OWNER_HEADER, OWNER: f"#[cfg(test)]\n{SAVEPOINT_FN}"}, 0, None),
            ("test_attribute", {ENTRY: OWNER_HEADER, OWNER: f"#[test]\n{SAVEPOINT_FN}"}, 0, None),
            (
                "external_without_inner_cfg_is_reported",
                {
                    ENTRY: OWNER_HEADER,
                    OWNER: '#[cfg(test)]\n#[path = "shared_review.rs"]\nmod review;\n',
                    sibling: SAVEPOINT_FN,
                },
                1,
                f"::error::{sibling}:2:",
            ),
            (
                "external_with_top_inner_cfg_test_is_excluded",
                {
                    ENTRY: OWNER_HEADER,
                    OWNER: '#[cfg(test)]\n#[path = "shared_review.rs"]\nmod review;\n',
                    sibling: f"//! 模块文档\n#![cfg(test)]\n{SAVEPOINT_FN}",
                },
                0,
                None,
            ),
        ]:
            with self.subTest(case=name):
                res = run_cli(files)
                self.assertEqual(res.returncode, expected_rc, res.stdout)
                errs = error_lines(res)
                if expected_rc == 1:
                    self.assertEqual(len(errs), 1, errs)
                    self.assertTrue(errs[0].startswith(prefix), errs)
                else:
                    self.assertEqual(errs, [])

    def test_r1_dual_route_outside_roots_and_combined_axes(self):
        sibling = "rust/src/bin/s_session_v3/shared_review.rs"
        test_first = (
            '#[cfg(test)]\n#[path = "shared_review.rs"]\nmod first;\n'
            '#[cfg(not(test))]\n#[path = "shared_review.rs"]\nmod second;\n'
        )
        prod_first = (
            '#[cfg(not(test))]\n#[path = "shared_review.rs"]\nmod second;\n'
            '#[cfg(test)]\n#[path = "shared_review.rs"]\nmod first;\n'
        )
        res_a = run_cli({ENTRY: OWNER_HEADER, OWNER: test_first, sibling: SAVEPOINT_FN})
        res_b = run_cli({ENTRY: OWNER_HEADER, OWNER: prod_first, sibling: SAVEPOINT_FN})
        self.assertEqual(res_a.returncode, 1, res_a.stdout)
        self.assertEqual(res_a.stdout, res_b.stdout)
        self.assertEqual(error_lines(res_a), [
            f"::error::{sibling}:2: 生产可达字符串字面量含禁用裸 SQL 模式（SAVEPOINT，#2009）"
        ])

        helper = "rust/src/bin/review_helper.rs"
        res_out = run_cli({ENTRY: OWNER_HEADER + "mod review_helper;\n", helper: SAVEPOINT_FN})
        self.assertEqual(res_out.returncode, 1, res_out.stdout)
        self.assertTrue(error_lines(res_out)[0].startswith(f"::error::{helper}:2:"), res_out.stdout)

        combined = (
            "fn review_for_test() {\n"
            '    let _ = std::env::var("REVIEW_SETTING");\n'
            '    let _ = "SAVEPOINT s";\n'
            "}\n"
        )
        res_comb = run_cli({ENTRY: OWNER_HEADER, OWNER: combined})
        self.assertEqual(res_comb.returncode, 1, res_comb.stdout)
        errs = error_lines(res_comb)
        self.assertEqual(len(errs), 3, errs)
        self.assertTrue(any(f"{OWNER}:1:" in e and "review_for_test" in e for e in errs), errs)
        self.assertTrue(any("REVIEW_SETTING" in e for e in errs), errs)
        self.assertTrue(any(f"{OWNER}:3:" in e and "SAVEPOINT" in e for e in errs), errs)

    def test_r2_include_and_path_and_cfg_attr_and_crate_bins(self):
        part = "rust/src/bin/s_session_v3/part.rs"
        cases = [
            ("include_prod", {ENTRY: OWNER_HEADER, OWNER: 'include!("part.rs");\n', part: SAVEPOINT_CONST}, 1, f"::error::{part}:1:"),
            (
                "include_test_without_inner_cfg",
                {ENTRY: OWNER_HEADER, OWNER: '#[cfg(test)]\ninclude!("part.rs");\n', part: SAVEPOINT_CONST},
                1,
                f"::error::{part}:1:",
            ),
            (
                "include_test_with_inner_cfg",
                {ENTRY: OWNER_HEADER, OWNER: '#[cfg(test)]\ninclude!("part.rs");\n', part: f"#![cfg(test)]\n{SAVEPOINT_CONST}"},
                0,
                None,
            ),
            (
                "cfg_attr_not_test_path",
                {
                    LIB: '#[cfg_attr(not(test), path = "alternate.rs")]\nmod sel;\n',
                    "rust/src/alternate.rs": SAVEPOINT_CONST,
                    "rust/src/sel.rs": "",
                },
                1,
                "::error::rust/src/alternate.rs:1:",
            ),
            (
                "raw_path_and_nested_submod",
                {
                    LIB: '#[path = r"sub/custom.rs"]\nmod sel;\n',
                    "rust/src/sub/custom.rs": "mod y;\n",
                    "rust/src/sub/y.rs": SAVEPOINT_CONST,
                },
                1,
                "::error::rust/src/sub/y.rs:1:",
            ),
            ("autobin_other", {"rust/src/bin/other.rs": SAVEPOINT_CONST}, 1, "::error::rust/src/bin/other.rs:1:"),
            ("main_rs", {"rust/src/main.rs": SAVEPOINT_CONST}, 1, "::error::rust/src/main.rs:1:"),
            (
                "hook_allowlist_does_not_exempt_sql",
                {"rust/src/bin/s_session_v3/sqlite_pager_probe.rs": SAVEPOINT_CONST},
                1,
                "::error::rust/src/bin/s_session_v3/sqlite_pager_probe.rs:1:",
            ),
        ]
        for name, files, expected_rc, prefix in cases:
            with self.subTest(case=name):
                res = run_cli(files)
                self.assertEqual(res.returncode, expected_rc, res.stdout)
                errs = error_lines(res)
                if expected_rc == 1:
                    self.assertEqual(len(errs), 1, errs)
                    self.assertTrue(errs[0].startswith(prefix), errs)
                else:
                    self.assertEqual(errs, [])

    def test_r2_inner_cfg_test_scope_not_hoisted_to_whole_file(self):
        local_mod = (
            "mod private {\n"
            "    #![cfg(test)]\n"
            '    const INSIDE: &str = "SAVEPOINT";\n'
            "}\n"
            'const OUTSIDE: &str = "SAVEPOINT";\n'
        )
        res = run_cli({LIB: local_mod})
        self.assertEqual(res.returncode, 1, res.stdout)
        errs = error_lines(res)
        self.assertEqual(len(errs), 1, errs)
        self.assertTrue(errs[0].startswith(f"::error::{LIB}:5:"), errs)

        mid_file = (
            "const FIRST: i32 = 1;\n"
            "#![cfg(test)]\n"
            'const SECOND: &str = "SAVEPOINT";\n'
        )
        res_mid = run_cli({LIB: mid_file})
        self.assertEqual(res_mid.returncode, 1, res_mid.stdout)
        self.assertTrue(error_lines(res_mid)[0].startswith(f"::error::{LIB}:3:"), res_mid.stdout)

        file_root = f"//! 注释\n#![ cfg ( test ) ]\n{SAVEPOINT_CONST}"
        res_root = run_cli({LIB: file_root})
        self.assertEqual(res_root.returncode, 0, res_root.stdout)

    def test_r2_non_exact_cfg_and_third_party_test_macros_are_reported(self):
        cases = [
            ("production_session", '#[cfg(feature = "production_session")]\n' + SAVEPOINT_CONST),
            ("testonly_feature", '#[cfg(feature = "s_capture_native_testonly")]\n' + SAVEPOINT_CONST),
            ("any_test_feature", '#[cfg(any(test, feature = "x"))]\n' + SAVEPOINT_CONST),
            ("all_test_unix", "#[cfg(all(test, unix))]\n" + SAVEPOINT_CONST),
            ("not_test", "#[cfg(not(test))]\n" + SAVEPOINT_CONST),
            ("cfg_attr_test", "#[cfg_attr(not(test), cfg(test))]\n" + SAVEPOINT_CONST),
            ("tokio_test", '#[tokio::test]\nasync fn case() {\n    let _ = "SAVEPOINT";\n}\n'),
            ("rstest", '#[rstest]\nfn case() {\n    let _ = "SAVEPOINT";\n}\n'),
            ("test_case", '#[test_case(1)]\nfn case(_v: i32) {\n    let _ = "SAVEPOINT";\n}\n'),
            ("bench", '#[bench]\nfn case(_: &mut test::Bencher) {\n    let _ = "SAVEPOINT";\n}\n'),
            ("test_attr_on_const_not_fn", "#[test]\n" + SAVEPOINT_CONST),
        ]
        for name, body in cases:
            with self.subTest(case=name):
                res = run_cli({LIB: body})
                self.assertEqual(res.returncode, 1, res.stdout)
                self.assertEqual(len(error_lines(res)), 1, res.stdout)

    def test_r2_array_semicolon_spacing_stacked_attrs_and_item_boundaries(self):
        zero_cases = [
            ("test_array_return", '#[test]\nfn case() -> Result<(), [u8; 1]> {\n    let _ = "SAVEPOINT";\n    Ok(())\n}\n'),
            ("cfg_test_array_const", '#[cfg(test)]\nconst FIXTURES: [&str; 1] = ["SAVEPOINT"];\n'),
            ("cfg_test_tuple_const", '#[cfg(test)]\nconst PAIR: (&str, &str) = ("SAVEPOINT", "ROLLBACK TO");\n'),
            ("cfg_test_where_array_block", '#[cfg(test)]\nfn f<const N: usize>() where [u8; { 1 + 1 }]: Sized {\n    let _ = "SAVEPOINT";\n}\n'),
            ("cfg_test_spacing", "#[cfg (test)]\n" + SAVEPOINT_CONST),
            ("cfg_test_extra_spacing", "#[ cfg ( test ) ]\n" + SAVEPOINT_CONST),
            ("bench_with_cfg_test", '#[cfg(test)]\n#[bench]\nfn case(_: &mut test::Bencher) {\n    let _ = "SAVEPOINT";\n}\n'),
            ("stacked_test_attrs", '#[allow(dead_code)]\n#[ignore]\n#[test]\n#[should_panic(expected = "SAVEPOINT")]\nfn case() -> Result<(), [u8; 1]> {\n    let _ = "SAVEPOINT";\n    Ok(())\n}\n'),
            ("qualified_core_test", '#[core::prelude::v1::test]\nfn case() {\n    let _ = "SAVEPOINT";\n}\n'),
            ("qualified_std_test", '#[::std::prelude::v1::test]\nfn case() {\n    let _ = "SAVEPOINT";\n}\n'),
        ]
        for name, body in zero_cases:
            with self.subTest(zero_case=name):
                res = run_cli({LIB: body})
                self.assertEqual(res.returncode, 0, res.stdout)

        boundary_cases = [
            (
                "after_test_fn_nested",
                (
                    "#[test]\n"
                    "fn case() {\n"
                    '    fn inside() { let _ = "SAVEPOINT"; }\n'
                    '    let _c = || "ROLLBACK TO";\n'
                    '    const X: &str = "schema_version=1";\n'
                    "}\n"
                    + SAVEPOINT_CONST
                ),
                7,
            ),
            (
                "after_cfg_test_array_const",
                '#[cfg(test)]\nconst FIXTURES: [&str; 1] = ["SAVEPOINT"];\n' + ROLLBACK_CONST,
                3,
            ),
            (
                "after_cfg_test_impl",
                'struct T;\n#[cfg(test)]\nimpl T { const TEST_VAL: &str = "SAVEPOINT"; }\n' + ROLLBACK_CONST,
                4,
            ),
            (
                "after_cfg_test_use_group",
                "#[cfg(test)]\nuse core::{fmt, mem};\n" + SAVEPOINT_CONST,
                3,
            ),
            (
                "after_cfg_test_if_else",
                (
                    "fn run(flag: bool) {\n"
                    "    #[cfg(test)]\n"
                    "    if flag {\n"
                    '        let _ = "SAVEPOINT a";\n'
                    "    } else {\n"
                    '        let _ = "SAVEPOINT b";\n'
                    "    }\n"
                    '    let _ = "SAVEPOINT live";\n'
                    "}\n"
                ),
                8,
            ),
        ]
        for name, body, expected_line in boundary_cases:
            with self.subTest(boundary=name):
                res = run_cli({LIB: body})
                self.assertEqual(res.returncode, 1, res.stdout)
                errs = error_lines(res)
                self.assertEqual(len(errs), 1, errs)
                self.assertTrue(errs[0].startswith(f"::error::{LIB}:{expected_line}:"), errs)

    def test_raw_sql_allowlist_is_exact_on_path_and_literal(self):
        exact_body = f'fn err() -> &\'static str {{\n    "{ALLOWLISTED_LITERAL}"\n}}\n'
        res_exact = run_cli({ALLOWLISTED_PATH: exact_body})
        self.assertEqual(res_exact.returncode, 0, res_exact.stdout)

        mutated_literal = ALLOWLISTED_LITERAL.replace("不受支持", "不被支持")
        mutated_body = f'fn err() -> &\'static str {{\n    "{mutated_literal}"\n}}\n'
        res_mutated = run_cli({ALLOWLISTED_PATH: mutated_body})
        self.assertEqual(res_mutated.returncode, 1, res_mutated.stdout)
        errs_mut = error_lines(res_mutated)
        self.assertEqual(len(errs_mut), 1, errs_mut)
        self.assertTrue(errs_mut[0].startswith(f"::error::{ALLOWLISTED_PATH}:2:"), errs_mut)

        res_other_file = run_cli({ENTRY: OWNER_HEADER, OWNER: exact_body})
        self.assertEqual(res_other_file.returncode, 1, res_other_file.stdout)
        errs_other = error_lines(res_other_file)
        self.assertEqual(len(errs_other), 1, errs_other)
        self.assertTrue(errs_other[0].startswith(f"::error::{OWNER}:2:"), errs_other)


if __name__ == "__main__":
    unittest.main()
