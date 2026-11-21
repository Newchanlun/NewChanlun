"""#1931 回滚/事故评测集与外部审查基线统计离线单测（不依赖仓外卷）。"""

from __future__ import annotations

import itertools
import json
import subprocess
from pathlib import Path

import pytest

from pilot1742.review_eval import (
    SCHEMA_VERSION,
    BugLocation,
    CasePrediction,
    DispositionEntry,
    DispositionLabel,
    EvalCase,
    EvalScore,
    EvalValidationError,
    PredictedFinding,
    _extract_markdown_link_ref_defs,
    _git_blob_line_count,
    _git_diff_added_ranges,
    _git_diff_tree_status_map,
    _mask_inline_non_prose_in_block,
    _parse_commonmark_blocks,
    _parse_leading_severity_tag,
    _parse_unified_diff_added_ranges,
    _score_from_dict,
    analyze_review_runs,
    classify_finding_heuristic,
    compare_scores,
    compute_cases_fingerprint,
    is_non_blocking_or_nit_finding,
    is_style_or_format_finding,
    load_cases,
    load_dispositions,
    main,
    render_baseline_markdown,
    score_predictions,
    validate_cases,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_CASES = REPO_ROOT / ".sandcastle" / "review-eval" / "cases.json"

SHA_1 = "1" * 40
SHA_2 = "2" * 40
SHA_3 = "3" * 40
SHA_4 = "4" * 40
SHA_5 = "5" * 40
SHA_6 = "6" * 40
SHA_7 = "7" * 40
SHA_8 = "8" * 40
SHA_9 = "9" * 40
SHA_A = "a" * 40
SHA_B = "b" * 40


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sample_cases() -> tuple[EvalCase, ...]:
    return (
        EvalCase(
            case_id="bug-alpha",
            kind="bug",
            title="样例 bug A",
            base_sha=SHA_1,
            head_sha=SHA_2,
            fix_sha=SHA_3,
            bug_locations=(
                BugLocation(
                    file="pkg/auth.py",
                    line_start=40,
                    line_end=45,
                    summary="未做边界检查",
                    category="authz_bypass",
                ),
                BugLocation(
                    file="pkg/state.py",
                    line_start=100,
                    line_end=105,
                    summary="早退未写回状态",
                    category="state_divergence",
                ),
            ),
        ),
        EvalCase(
            case_id="bug-beta",
            kind="bug",
            title="样例 bug B",
            base_sha=SHA_4,
            head_sha=SHA_5,
            bug_locations=(
                BugLocation(
                    file="pkg/parser.py",
                    line_start=20,
                    line_end=22,
                    summary="前缀匹配绕过",
                    category="fail_open_regression",
                ),
            ),
        ),
        EvalCase(
            case_id="clean-one",
            kind="clean",
            title="样例干净 PR 1",
            base_sha=SHA_6,
            head_sha=SHA_7,
        ),
        EvalCase(
            case_id="clean-two",
            kind="clean",
            title="样例干净 PR 2",
            base_sha=SHA_8,
            head_sha=SHA_9,
        ),
    )


def _is_full_git_checkout(root: Path) -> bool:
    inside = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        check=False,
        capture_output=True,
        text=True,
    )
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return False
    shallow = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-shallow-repository"],
        check=False,
        capture_output=True,
        text=True,
    )
    return shallow.returncode == 0 and shallow.stdout.strip() == "false"


def test_canonical_cases_json_schema_valid() -> None:
    cases = load_cases(CANONICAL_CASES)
    validate_cases(cases, repo_root=None)

    bug_cases = [c for c in cases if c.kind == "bug"]
    clean_cases = [c for c in cases if c.kind == "clean"]
    assert len(bug_cases) >= 9
    assert len(clean_cases) >= 5
    assert all(len(c.bug_locations) >= 1 for c in bug_cases)
    assert all(len(c.bug_locations) == 0 for c in clean_cases)

    by_id = {c.case_id: c for c in cases}
    case_1950 = by_id["bug-1950-agent-devskim-hash-revert"]
    assert len(case_1950.bug_locations) == 1
    assert case_1950.bug_locations[0].file == ".sandcastle/deepagents-pilot/pilot1742/agent.py"
    assert case_1950.bug_locations[0].line_start == 284
    assert case_1950.bug_locations[0].line_end == 284
    assert case_1950.bug_locations[0].extra_ranges == ((355, 355),)
    assert case_1950.bug_locations[0].all_ranges == ((284, 284), (355, 355))


def test_canonical_cases_json_git_history_verified() -> None:
    if not _is_full_git_checkout(REPO_ROOT):
        pytest.skip("浅克隆或非完整 Git 仓库环境，跳过完整历史对象溯源校验")
    cases = load_cases(CANONICAL_CASES)
    validate_cases(cases, repo_root=REPO_ROOT)


def test_schema_and_validation_reject_invalid_inputs(tmp_path: Path) -> None:
    bad_schema = tmp_path / "bad_schema.json"
    bad_schema.write_text(json.dumps({"schema_version": "wrong/1", "cases": []}), encoding="utf-8")
    with pytest.raises(EvalValidationError, match="schema_version"):
        load_cases(bad_schema)

    dup_id = _sample_cases()[0]
    with pytest.raises(EvalValidationError, match="重复的 case_id"):
        validate_cases((dup_id, dup_id))

    empty_bug = EvalCase(
        case_id="bug-empty",
        kind="bug",
        title="缺少定位",
        base_sha=SHA_A,
        head_sha=SHA_B,
        bug_locations=(),
    )
    with pytest.raises(EvalValidationError, match="bug_locations 不能为空"):
        validate_cases((empty_bug,))

    dirty_clean = EvalCase(
        case_id="clean-with-loc",
        kind="clean",
        title="干净案不许有定位",
        base_sha=SHA_A,
        head_sha=SHA_B,
        bug_locations=(
            BugLocation(file="a.py", line_start=1, line_end=2, summary="x", category="y"),
        ),
    )
    with pytest.raises(EvalValidationError, match="bug_locations 必须为空"):
        validate_cases((dirty_clean,))


def test_strict_40_char_lowercase_sha_validation(tmp_path: Path) -> None:
    # 拒绝短 SHA（7 位、39 位）、大写 SHA 以及带前后空白的 40+ 字符 SHA
    bad_shas = (
        "1234567",
        "a" * 39,
        "A" * 40,
        "a" * 39 + "B",
        " " + "a" * 40 + " ",
        " " + "a" * 40,
        "a" * 40 + "\n",
    )
    for idx, bad_sha in enumerate(bad_shas):
        bad_case = EvalCase(
            case_id="bad-sha",
            kind="clean",
            title="非法 SHA",
            base_sha=bad_sha,
            head_sha=SHA_B,
        )
        with pytest.raises(EvalValidationError, match="40 位小写"):
            validate_cases((bad_case,))

        bad_json = tmp_path / f"bad_sha_{idx}.json"
        bad_json.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "cases": [
                        {
                            "case_id": "bad-sha-json",
                            "kind": "clean",
                            "title": "非法 SHA JSON",
                            "base_sha": bad_sha,
                            "head_sha": SHA_B,
                            "fix_sha": None,
                            "bug_locations": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(EvalValidationError, match="40 位小写"):
            load_cases(bad_json)


def test_validate_cases_checks_git_repo_line_bounds_and_diff_hunks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    (repo / "app.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    (repo / "untouched.py").write_text("old1\nold2\n", encoding="utf-8")
    _git(repo, "add", "app.py", "untouched.py")
    _git(repo, "commit", "-qm", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    (repo / "app.py").write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-qm", "buggy")
    head_sha = _git(repo, "rev-parse", "HEAD")

    ok_case = EvalCase(
        case_id="ok-git",
        kind="bug",
        title="合法行号且命中 diff hunk",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="app.py", line_start=4, line_end=4, summary="缺陷", category="bug"),),
    )
    validate_cases((ok_case,), repo_root=repo)

    oob_case = EvalCase(
        case_id="oob-git",
        kind="bug",
        title="行号越界",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="app.py", line_start=2, line_end=99, summary="越界", category="bug"),),
    )
    with pytest.raises(EvalValidationError, match="行号越界"):
        validate_cases((oob_case,), repo_root=repo)

    # 仅修改第 4 行，指向未改动的第 1..2 行必须被 diff hunk 校验拒绝
    non_diff_lines_case = EvalCase(
        case_id="non-diff-lines",
        kind="bug",
        title="指向未改动历史行",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="app.py", line_start=1, line_end=2, summary="历史行", category="bug"),),
    )
    with pytest.raises(EvalValidationError, match="diff hunk"):
        validate_cases((non_diff_lines_case,), repo_root=repo)

    # 指向 base..head 完全未改动的文件必须被 diff hunk 校验拒绝
    untouched_file_case = EvalCase(
        case_id="untouched-file",
        kind="bug",
        title="指向未改动文件",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="untouched.py", line_start=1, line_end=2, summary="历史文件", category="bug"),),
    )
    with pytest.raises(EvalValidationError, match="diff hunk"):
        validate_cases((untouched_file_case,), repo_root=repo)

    missing_sha_case = EvalCase(
        case_id="missing-sha",
        kind="clean",
        title="不存在的 SHA",
        base_sha=base_sha,
        head_sha="deadbeef" * 5,
    )
    with pytest.raises(EvalValidationError, match="在仓库中不存在"):
        validate_cases((missing_sha_case,), repo_root=repo)

    missing_fix_sha_case = EvalCase(
        case_id="missing-fix-sha",
        kind="bug",
        title="不存在的 fix_sha",
        base_sha=base_sha,
        head_sha=head_sha,
        fix_sha="cafebabe" * 5,
        bug_locations=(BugLocation(file="app.py", line_start=4, line_end=4, summary="缺陷", category="bug"),),
    )
    with pytest.raises(EvalValidationError, match="fix_sha"):
        validate_cases((missing_fix_sha_case,), repo_root=repo)

    missing_file_case = EvalCase(
        case_id="missing-file",
        kind="bug",
        title="head_sha 中不存在的文件",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="ghost.py", line_start=1, line_end=1, summary="缺文件", category="bug"),),
    )
    with pytest.raises(EvalValidationError, match="中不存在"):
        validate_cases((missing_file_case,), repo_root=repo)

    # 浅克隆（fetch-depth: 1）被 _is_full_git_checkout 识别为非完整仓，避免 CI 浅克隆炸红
    assert _is_full_git_checkout(repo) is True
    shallow_repo = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth=1", f"file://{repo}", str(shallow_repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert _is_full_git_checkout(shallow_repo) is False

    # extra_ranges 校验：每个离散区间都必须不越界且与 diff hunk 相交
    (repo / "multi.py").write_text("a1\na2\na3\na4\na5\na6\n", encoding="utf-8")
    _git(repo, "add", "multi.py")
    _git(repo, "commit", "-qm", "multi-base")
    m_base = _git(repo, "rev-parse", "HEAD")

    (repo / "multi.py").write_text("a1_mod\na2\na3\na4\na5\na6_mod\n", encoding="utf-8")
    _git(repo, "add", "multi.py")
    _git(repo, "commit", "-qm", "multi-head")
    m_head = _git(repo, "rev-parse", "HEAD")

    ok_extra = EvalCase(
        case_id="ok-extra",
        kind="bug",
        title="双离散改动点均命中 diff hunk",
        base_sha=m_base,
        head_sha=m_head,
        bug_locations=(
            BugLocation(
                file="multi.py",
                line_start=1,
                line_end=1,
                extra_ranges=((6, 6),),
                summary="两处离散改动",
                category="bug",
            ),
        ),
    )
    validate_cases((ok_extra,), repo_root=repo)

    extra_non_diff = EvalCase(
        case_id="extra-non-diff",
        kind="bug",
        title="extra_ranges 指向未改动中间行",
        base_sha=m_base,
        head_sha=m_head,
        bug_locations=(
            BugLocation(
                file="multi.py",
                line_start=1,
                line_end=1,
                extra_ranges=((3, 3),),
                summary="未改动行",
                category="bug",
            ),
        ),
    )
    with pytest.raises(EvalValidationError, match="diff hunk"):
        validate_cases((extra_non_diff,), repo_root=repo)

    extra_oob = EvalCase(
        case_id="extra-oob",
        kind="bug",
        title="extra_ranges 越界",
        base_sha=m_base,
        head_sha=m_head,
        bug_locations=(
            BugLocation(
                file="multi.py",
                line_start=1,
                line_end=1,
                extra_ranges=((99, 99),),
                summary="越界",
                category="bug",
            ),
        ),
    )
    with pytest.raises(EvalValidationError, match="行号越界"):
        validate_cases((extra_oob,), repo_root=repo)


def test_discrete_extra_ranges_matching_and_fingerprint_for_case_1950(tmp_path: Path) -> None:
    cases = load_cases(CANONICAL_CASES)
    case_1950 = next(c for c in cases if c.case_id == "bug-1950-agent-devskim-hash-revert")
    target_cases = (case_1950,)
    target_file = ".sandcastle/deepagents-pilot/pilot1742/agent.py"

    # 1) line_tolerance=0 报 284 行命中（1.0）
    score_284 = score_predictions(
        target_cases,
        (
            CasePrediction(
                case_id=case_1950.case_id,
                verdict="BLOCK",
                findings=(PredictedFinding(file=target_file, line_start=284, line_end=284, severity="blocking"),),
            ),
        ),
        line_tolerance=0,
    )
    assert score_284.bug_case_recall == pytest.approx(1.0)
    assert score_284.bug_location_recall == pytest.approx(1.0)
    assert score_284.blocking_precision == pytest.approx(1.0)

    # 2) line_tolerance=0 报 355 行命中（1.0）
    score_355 = score_predictions(
        target_cases,
        (
            CasePrediction(
                case_id=case_1950.case_id,
                verdict="BLOCK",
                findings=(PredictedFinding(file=target_file, line_start=355, line_end=355, severity="blocking"),),
            ),
        ),
        line_tolerance=0,
    )
    assert score_355.bug_case_recall == pytest.approx(1.0)
    assert score_355.bug_location_recall == pytest.approx(1.0)
    assert score_355.blocking_precision == pytest.approx(1.0)

    # 3) line_tolerance=0 报未改动的第 320 行绝不命中（0.0）
    score_320 = score_predictions(
        target_cases,
        (
            CasePrediction(
                case_id=case_1950.case_id,
                verdict="BLOCK",
                findings=(PredictedFinding(file=target_file, line_start=320, line_end=320, severity="blocking"),),
            ),
        ),
        line_tolerance=0,
    )
    assert score_320.bug_case_recall == pytest.approx(0.0)
    assert score_320.bug_location_recall == pytest.approx(0.0)
    assert score_320.blocking_precision == pytest.approx(0.0)

    # 4) 同时报 284 与 355 仍只计 1 个位置命中，且多报一条拉低 precision 为 0.5
    score_both = score_predictions(
        target_cases,
        (
            CasePrediction(
                case_id=case_1950.case_id,
                verdict="BLOCK",
                findings=(
                    PredictedFinding(file=target_file, line_start=284, line_end=284, severity="blocking"),
                    PredictedFinding(file=target_file, line_start=355, line_end=355, severity="blocking"),
                ),
            ),
        ),
        line_tolerance=0,
    )
    assert score_both.matched_bug_locations == 1
    assert score_both.bug_location_recall == pytest.approx(1.0)
    assert score_both.total_blocking_findings == 2
    assert score_both.matched_blocking_findings == 1
    assert score_both.blocking_precision == pytest.approx(0.5)

    # 5) extra_ranges 变更影响 cases_fingerprint；非法 JSON extra_ranges 被 load_cases 拒绝
    alt_case = EvalCase(
        case_id=case_1950.case_id,
        kind="bug",
        title=case_1950.title,
        base_sha=case_1950.base_sha,
        head_sha=case_1950.head_sha,
        bug_locations=(
            BugLocation(
                file=target_file,
                line_start=284,
                line_end=284,
                extra_ranges=(),
                summary="s",
                category="c",
            ),
        ),
    )
    assert compute_cases_fingerprint((case_1950,)) != compute_cases_fingerprint((alt_case,))

    bad_extra_json = tmp_path / "bad_extra.json"
    bad_extra_json.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "cases": [
                    {
                        "case_id": "bad-extra",
                        "kind": "bug",
                        "title": "bad",
                        "base_sha": SHA_1,
                        "head_sha": SHA_2,
                        "fix_sha": None,
                        "bug_locations": [
                            {
                                "file": "a.py",
                                "line_start": 10,
                                "line_end": 10,
                                "extra_ranges": [[20, 15]],
                                "summary": "s",
                                "category": "c",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(EvalValidationError, match="行号区间非法"):
        load_cases(bad_extra_json)


def test_score_predictions_tolerance_clean_fp_and_compare() -> None:
    cases = _sample_cases()

    before_preds = (
        CasePrediction(
            case_id="bug-alpha",
            verdict="BLOCK",
            findings=(
                # 45 + 10 = 55，在 line_tolerance=15 内命中 pkg/auth.py:40-45
                PredictedFinding(file="./pkg/auth.py", line_start=55, line_end=55, severity="important"),
                # 105 + 20 = 125，超出 tolerance=15，不命中 pkg/state.py:100-105
                PredictedFinding(file="pkg/state.py", line_start=125, line_end=126, severity="blocking"),
            ),
        ),
        CasePrediction(
            case_id="bug-beta",
            verdict="PASS",
            findings=(PredictedFinding(file="pkg/parser.py", line_start=20, line_end=22, severity="nit"),),
        ),
        CasePrediction(
            case_id="clean-one",
            verdict="PASS",
            # 非阻断 nit 不应计为 clean PR 误报
            findings=(PredictedFinding(file="pkg/ok.py", line_start=1, line_end=1, severity="nit"),),
        ),
        CasePrediction(
            case_id="clean-two",
            verdict="BLOCK",
            findings=(PredictedFinding(file="pkg/ok2.py", line_start=3, line_end=5, severity="blocking"),),
        ),
    )

    before = score_predictions(cases, before_preds, line_tolerance=15)
    assert before.bug_case_recall == pytest.approx(0.5)
    assert before.bug_location_recall == pytest.approx(1 / 3, rel=1e-5)
    assert before.clean_false_positive_rate == pytest.approx(0.5)
    assert before.blocking_precision == pytest.approx(1 / 3, rel=1e-5)
    assert before.f1 == pytest.approx(1 / 3, rel=1e-5)

    after_preds = (
        CasePrediction(
            case_id="bug-alpha",
            verdict="BLOCK",
            findings=(
                PredictedFinding(file="pkg/auth.py", line_start=42, line_end=43, severity="blocking"),
                PredictedFinding(file="pkg/state.py", line_start=102, line_end=103, severity="blocking"),
            ),
        ),
        CasePrediction(
            case_id="bug-beta",
            verdict="BLOCK",
            findings=(PredictedFinding(file="pkg/parser.py", line_start=21, line_end=21, severity="important"),),
        ),
        CasePrediction(case_id="clean-one", verdict="PASS"),
        CasePrediction(case_id="clean-two", verdict="PASS"),
    )

    after = score_predictions(cases, after_preds, line_tolerance=15)
    assert after.bug_case_recall == pytest.approx(1.0)
    assert after.bug_location_recall == pytest.approx(1.0)
    assert after.clean_false_positive_rate == pytest.approx(0.0)
    assert after.blocking_precision == pytest.approx(1.0)
    assert after.f1 == pytest.approx(1.0)

    diff = compare_scores(before, after)
    assert diff.bug_case_recall_delta == pytest.approx(0.5)
    assert diff.clean_false_positive_rate_delta == pytest.approx(-0.5)
    assert diff.improved_cases == ("bug-alpha", "bug-beta", "clean-two")
    assert diff.regressed_cases == ()
    assert diff.mixed_cases == ()
    assert diff.unchanged_cases == ("clean-one",)

    rev_diff = compare_scores(after, before)
    assert rev_diff.regressed_cases == ("bug-alpha", "bug-beta", "clean-two")


def test_clean_pr_block_with_only_nit_is_still_false_positive() -> None:
    cases = (
        EvalCase(case_id="clean-nit-block", kind="clean", title="clean", base_sha=SHA_1, head_sha=SHA_2),
        EvalCase(case_id="clean-nit-pass", kind="clean", title="clean2", base_sha=SHA_3, head_sha=SHA_4),
    )
    preds = (
        CasePrediction(
            case_id="clean-nit-block",
            verdict="BLOCK",
            findings=(PredictedFinding(file="x.py", line_start=1, line_end=1, severity="nit", summary="命名风格"),),
        ),
        CasePrediction(
            case_id="clean-nit-pass",
            verdict="PASS",
            findings=(PredictedFinding(file="x.py", line_start=1, line_end=1, severity="nit", summary="命名风格"),),
        ),
    )
    score = score_predictions(cases, preds)
    assert score.clean_false_positive_cases == 1
    assert score.clean_false_positive_rate == pytest.approx(0.5)
    by_id = {d.case_id: d for d in score.case_details}
    assert by_id["clean-nit-block"].clean_false_positive is True
    assert by_id["clean-nit-pass"].clean_false_positive is False


def test_duplicate_findings_and_wide_span_cannot_game_metrics() -> None:
    cases = (
        EvalCase(
            case_id="bug-two-locs",
            kind="bug",
            title="同文件两处缺陷",
            base_sha=SHA_1,
            head_sha=SHA_2,
            bug_locations=(
                BugLocation(file="a.py", line_start=50, line_end=55, summary="loc1", category="bug"),
                BugLocation(file="a.py", line_start=500, line_end=505, summary="loc2", category="bug"),
            ),
        ),
        EvalCase(
            case_id="bug-one-loc",
            kind="bug",
            title="单处缺陷",
            base_sha=SHA_3,
            head_sha=SHA_4,
            bug_locations=(BugLocation(file="b.py", line_start=20, line_end=25, summary="loc", category="bug"),),
        ),
    )

    # 1) 1 条真发现复制 9 份 + 1 条误报 -> 一对一匹配仅计 1 条真阳性，precision = 1/10 = 0.1
    dup_preds = (
        CasePrediction(case_id="bug-two-locs", verdict="PASS"),
        CasePrediction(
            case_id="bug-one-loc",
            verdict="BLOCK",
            findings=(
                *(PredictedFinding(file="b.py", line_start=22, line_end=22, severity="blocking") for _ in range(9)),
                PredictedFinding(file="other.py", line_start=1, line_end=1, severity="blocking"),
            ),
        ),
    )
    dup_score = score_predictions(cases, dup_preds)
    assert dup_score.matched_bug_locations == 1
    assert dup_score.matched_blocking_findings == 1
    assert dup_score.total_blocking_findings == 10
    assert dup_score.blocking_precision == pytest.approx(0.1)

    # 2) 1 条宽区间 1..1000 覆盖 50 行与 500 行 -> 被 max_finding_span=120 拦截，0 命中
    wide_preds = (
        CasePrediction(
            case_id="bug-two-locs",
            verdict="BLOCK",
            findings=(PredictedFinding(file="a.py", line_start=1, line_end=1000, severity="blocking"),),
        ),
        CasePrediction(case_id="bug-one-loc", verdict="PASS"),
    )
    wide_score = score_predictions(cases, wide_preds, max_finding_span=120)
    assert wide_score.matched_bug_locations == 0
    assert wide_score.recalled_bug_cases == 0
    assert wide_score.blocking_precision == pytest.approx(0.0)

    # 3) 即便放宽 span 上限，单条发现经一对一匹配也最多领取 1 个 location 召回
    single_covers_two = score_predictions(cases, wide_preds, max_finding_span=1000)
    assert single_covers_two.matched_bug_locations == 1
    assert single_covers_two.matched_blocking_findings == 1

    # 4) 复制同一坐标发现 2 次（含 ./ 前缀等价路径）绝不能刷高两处缺陷的召回率，反而拉低精确率
    two_close_locs = (
        EvalCase(
            case_id="bug-close-pair",
            kind="bug",
            title="同文件相距 72 行两处位置",
            base_sha=SHA_5,
            head_sha=SHA_6,
            bug_locations=(
                BugLocation(file="agent.py", line_start=284, line_end=284, summary="loc1", category="bug"),
                BugLocation(file="agent.py", line_start=355, line_end=355, summary="loc2", category="bug"),
            ),
        ),
    )
    one_spanning = score_predictions(
        two_close_locs,
        (
            CasePrediction(
                case_id="bug-close-pair",
                verdict="BLOCK",
                findings=(PredictedFinding(file="agent.py", line_start=284, line_end=355, severity="blocking"),),
            ),
        ),
        max_finding_span=120,
    )
    assert one_spanning.matched_bug_locations == 1
    assert one_spanning.bug_location_recall == pytest.approx(0.5)
    assert one_spanning.blocking_precision == pytest.approx(1.0)

    duplicated_spanning = score_predictions(
        two_close_locs,
        (
            CasePrediction(
                case_id="bug-close-pair",
                verdict="BLOCK",
                findings=(
                    PredictedFinding(file="agent.py", line_start=284, line_end=355, severity="blocking"),
                    PredictedFinding(file="./agent.py", line_start=284, line_end=355, severity="blocking"),
                ),
            ),
        ),
        max_finding_span=120,
    )
    assert duplicated_spanning.matched_bug_locations == 1
    assert duplicated_spanning.bug_location_recall == pytest.approx(0.5)
    assert duplicated_spanning.total_blocking_findings == 2
    assert duplicated_spanning.matched_blocking_findings == 1
    assert duplicated_spanning.blocking_precision == pytest.approx(0.5)

    # 5) 闭区间跨度边界：284..403 覆盖 120 行允许，284..404 覆盖 121 行必须拒绝
    span_case = (
        EvalCase(
            case_id="bug-span-boundary",
            kind="bug",
            title="跨度边界",
            base_sha=SHA_7,
            head_sha=SHA_8,
            bug_locations=(BugLocation(file="span.py", line_start=300, line_end=300, summary="loc", category="bug"),),
        ),
    )
    span_120 = score_predictions(
        span_case,
        (
            CasePrediction(
                case_id="bug-span-boundary",
                verdict="BLOCK",
                findings=(PredictedFinding(file="span.py", line_start=284, line_end=403, severity="blocking"),),
            ),
        ),
        max_finding_span=120,
    )
    assert span_120.matched_bug_locations == 1
    assert span_120.recalled_bug_cases == 1

    span_121 = score_predictions(
        span_case,
        (
            CasePrediction(
                case_id="bug-span-boundary",
                verdict="BLOCK",
                findings=(PredictedFinding(file="span.py", line_start=284, line_end=404, severity="blocking"),),
            ),
        ),
        max_finding_span=120,
    )
    assert span_121.matched_bug_locations == 0
    assert span_121.recalled_bug_cases == 0


def test_missing_predictions_rejected_by_default_and_explicit_in_partial_mode() -> None:
    cases = _sample_cases()
    partial_preds = (
        CasePrediction(
            case_id="bug-alpha",
            verdict="BLOCK",
            findings=(PredictedFinding(file="pkg/auth.py", line_start=42, line_end=42, severity="blocking"),),
        ),
        CasePrediction(
            case_id="clean-one",
            verdict="BLOCK",
            findings=(PredictedFinding(file="pkg/ok.py", line_start=1, line_end=1, severity="blocking"),),
        ),
    )

    with pytest.raises(EvalValidationError, match="预测缺少案例"):
        score_predictions(cases, partial_preds)

    partial = score_predictions(cases, partial_preds, allow_partial=True)
    assert partial.total_cases == 4
    assert partial.evaluated_cases == 2
    assert partial.failed_cases == 0
    assert partial.missing_cases == 2
    assert partial.coverage_rate == pytest.approx(0.5)
    # clean-one 被 BLOCK，clean-two 缺失不充当零误报分母 -> clean FP rate = 1/1 = 1.0
    assert partial.clean_false_positive_cases == 1
    assert partial.clean_false_positive_rate == pytest.approx(1.0)
    by_id = {d.case_id: d for d in partial.case_details}
    assert by_id["bug-beta"].verdict == "MISSING"
    assert by_id["clean-two"].verdict == "MISSING"

    # 若没有任何已裁定 clean 案，decided_clean_cases == 0 且 clean_false_positive_rate 为 None（绝不伪装成 0.0）
    no_clean_partial = score_predictions(cases, (partial_preds[0],), allow_partial=True)
    assert no_clean_partial.decided_clean_cases == 0
    assert no_clean_partial.clean_false_positive_rate is None
    assert no_clean_partial.coverage_rate == pytest.approx(0.25)


def test_missing_and_failed_never_grant_improved_and_failed_lowers_coverage() -> None:
    cases = (
        EvalCase(
            case_id="bug-recalled",
            kind="bug",
            title="已召回 bug",
            base_sha=SHA_1,
            head_sha=SHA_2,
            bug_locations=(BugLocation(file="a.py", line_start=10, line_end=12, summary="b1", category="bug"),),
        ),
        EvalCase(
            case_id="bug-unrecalled",
            kind="bug",
            title="未召回 bug",
            base_sha=SHA_3,
            head_sha=SHA_4,
            bug_locations=(BugLocation(file="b.py", line_start=20, line_end=22, summary="b2", category="bug"),),
        ),
        EvalCase(case_id="clean-1877", kind="clean", title="clean 1877", base_sha=SHA_5, head_sha=SHA_6),
        EvalCase(case_id="clean-1886", kind="clean", title="clean 1886", base_sha=SHA_7, head_sha=SHA_8),
    )

    before = score_predictions(
        cases,
        (
            CasePrediction(
                case_id="bug-recalled",
                verdict="BLOCK",
                findings=(PredictedFinding(file="a.py", line_start=11, line_end=11, severity="blocking"),),
            ),
            CasePrediction(
                case_id="bug-unrecalled",
                verdict="BLOCK",
                findings=(PredictedFinding(file="wrong.py", line_start=1, line_end=1, severity="blocking"),),
            ),
            CasePrediction(
                case_id="clean-1877",
                verdict="BLOCK",
                findings=(PredictedFinding(file="c.py", line_start=5, line_end=5, severity="blocking"),),
            ),
            CasePrediction(case_id="clean-1886", verdict="PASS"),
        ),
    )
    assert before.evaluated_cases == 4
    assert before.failed_cases == 0
    assert before.missing_cases == 0
    assert before.coverage_rate == pytest.approx(1.0)
    assert before.clean_false_positive_rate == pytest.approx(0.5)

    # 1) clean-1877 从 BLOCK -> MISSING，bug-recalled -> MISSING，clean-1886 PASS -> MISSING，bug-unrecalled -> MISSING
    after_missing = score_predictions(cases, (), allow_partial=True)
    assert after_missing.evaluated_cases == 0
    assert after_missing.failed_cases == 0
    assert after_missing.missing_cases == 4
    assert after_missing.decided_clean_cases == 0
    assert after_missing.clean_false_positive_rate is None
    assert after_missing.coverage_rate == pytest.approx(0.0)
    cmp_missing = compare_scores(before, after_missing)
    assert cmp_missing.improved_cases == ()
    assert cmp_missing.regressed_cases == ("bug-recalled", "clean-1886")
    assert cmp_missing.undecided_cases == ("bug-unrecalled", "clean-1877")
    assert cmp_missing.clean_false_positive_rate_delta is None
    assert cmp_missing.coverage_rate_delta == pytest.approx(-1.0)

    # 2) clean-1877 从 BLOCK -> FAILED：绝不进 improved_cases，且 FAILED 降低 coverage_rate、不充当 clean 零误报分母
    after_failed = score_predictions(
        cases,
        (
            CasePrediction(case_id="bug-recalled", verdict="FAILED"),
            CasePrediction(case_id="bug-unrecalled", verdict="FAILED"),
            CasePrediction(case_id="clean-1877", verdict="FAILED"),
            CasePrediction(case_id="clean-1886", verdict="BLOCK"),
        ),
    )
    assert after_failed.evaluated_cases == 1
    assert after_failed.failed_cases == 3
    assert after_failed.missing_cases == 0
    assert after_failed.coverage_rate == pytest.approx(0.25)
    # 仅 clean-1886 实际产出裁定（BLOCK），clean-1877 为 FAILED 不充当零误报 -> clean FP rate = 1/1 = 1.0
    assert after_failed.clean_false_positive_cases == 1
    assert after_failed.clean_false_positive_rate == pytest.approx(1.0)

    cmp_failed = compare_scores(before, after_failed)
    assert cmp_failed.improved_cases == ()
    assert cmp_failed.regressed_cases == ("bug-recalled", "clean-1886")
    assert cmp_failed.undecided_cases == ("bug-unrecalled", "clean-1877")
    assert cmp_failed.coverage_rate_delta == pytest.approx(-0.75)

    # 3) 两侧均为 MISSING/FAILED -> undecided_cases；从 FAILED/MISSING 恢复为 PASS/BLOCK 也不授予 improved_cases
    cmp_both_undecided = compare_scores(after_missing, after_failed)
    assert cmp_both_undecided.improved_cases == ()
    assert cmp_both_undecided.undecided_cases == ("bug-recalled", "bug-unrecalled", "clean-1877", "clean-1886")

    cmp_recover_from_failed = compare_scores(after_failed, before)
    assert cmp_recover_from_failed.improved_cases == ("clean-1886",)
    assert cmp_recover_from_failed.undecided_cases == ("bug-recalled", "bug-unrecalled", "clean-1877")


def test_single_clean_case_block_to_failed_or_missing_yields_none_fp_rate_and_delta(tmp_path: Path) -> None:
    single_clean = (
        EvalCase(case_id="clean-1877", kind="clean", title="唯一 clean 案", base_sha=SHA_1, head_sha=SHA_2),
    )
    before = score_predictions(
        single_clean,
        (
            CasePrediction(
                case_id="clean-1877",
                verdict="BLOCK",
                findings=(PredictedFinding(file="c.py", line_start=1, line_end=1, severity="blocking"),),
            ),
        ),
    )
    assert before.decided_clean_cases == 1
    assert before.clean_false_positive_rate == pytest.approx(1.0)

    # 1) 唯一 clean 案从 BLOCK -> FAILED：绝不报告 clean_false_positive_rate=0.0 或 delta=-1.0
    after_failed = score_predictions(
        single_clean,
        (CasePrediction(case_id="clean-1877", verdict="FAILED"),),
    )
    assert after_failed.decided_clean_cases == 0
    assert after_failed.clean_false_positive_rate is None
    cmp_failed = compare_scores(before, after_failed)
    assert cmp_failed.clean_false_positive_rate_delta is None
    assert cmp_failed.improved_cases == ()
    assert cmp_failed.undecided_cases == ("clean-1877",)

    # 2) 唯一 clean 案从 BLOCK -> MISSING（allow_partial=True）：同样为 None
    after_missing = score_predictions(single_clean, (), allow_partial=True)
    assert after_missing.decided_clean_cases == 0
    assert after_missing.clean_false_positive_rate is None
    cmp_missing = compare_scores(before, after_missing)
    assert cmp_missing.clean_false_positive_rate_delta is None
    assert cmp_missing.improved_cases == ()
    assert cmp_missing.undecided_cases == ("clean-1877",)

    # 3) CLI JSON 序列化与 _score_from_dict 往返兼容 null
    before_json = tmp_path / "before.json"
    after_json = tmp_path / "after.json"
    cmp_json = tmp_path / "cmp.json"
    before_json.write_text(json.dumps(before.to_dict()), encoding="utf-8")
    after_json.write_text(json.dumps(after_failed.to_dict()), encoding="utf-8")
    assert json.loads(after_json.read_text(encoding="utf-8"))["clean_false_positive_rate"] is None
    assert main(["compare", "--before", str(before_json), "--after", str(after_json), "--out-json", str(cmp_json)]) == 0
    cmp_payload = json.loads(cmp_json.read_text(encoding="utf-8"))
    assert cmp_payload["clean_false_positive_rate_delta"] is None
    assert cmp_payload["improved_cases"] == []


def test_compare_scores_enforces_compatibility_and_catches_precision_regression() -> None:
    cases = _sample_cases()
    base_preds = (
        CasePrediction(
            case_id="bug-alpha",
            verdict="BLOCK",
            findings=(PredictedFinding(file="pkg/auth.py", line_start=42, line_end=43, severity="blocking"),),
        ),
        CasePrediction(
            case_id="bug-beta",
            verdict="BLOCK",
            findings=(PredictedFinding(file="pkg/parser.py", line_start=20, line_end=21, severity="blocking"),),
        ),
        CasePrediction(case_id="clean-one", verdict="PASS"),
        CasePrediction(case_id="clean-two", verdict="PASS"),
    )
    score_base = score_predictions(cases, base_preds, line_tolerance=15, max_finding_span=120)

    # 1) 不同 line_tolerance / max_finding_span 拒绝对比
    score_diff_tol = score_predictions(cases, base_preds, line_tolerance=5, max_finding_span=120)
    with pytest.raises(EvalValidationError, match="line_tolerance 不一致"):
        compare_scores(score_base, score_diff_tol)

    score_diff_span = score_predictions(cases, base_preds, line_tolerance=15, max_finding_span=60)
    with pytest.raises(EvalValidationError, match="max_finding_span 不一致"):
        compare_scores(score_base, score_diff_span)

    # 2) 不同评测集指纹拒绝对比
    other_cases = cases[:2]
    score_other = score_predictions(other_cases, base_preds[:2], line_tolerance=15, max_finding_span=120)
    with pytest.raises(EvalValidationError, match="评测集指纹不一致"):
        compare_scores(score_base, score_other)

    # 3) 精确率回归进 regressed_cases，召回上升但误报增加进 mixed_cases
    noisy_preds = (
        # bug-alpha：召回从 1 个位置升到 2 个位置，但同时新增 2 条误报 -> mixed_cases
        CasePrediction(
            case_id="bug-alpha",
            verdict="BLOCK",
            findings=(
                PredictedFinding(file="pkg/auth.py", line_start=42, line_end=43, severity="blocking"),
                PredictedFinding(file="pkg/state.py", line_start=101, line_end=102, severity="blocking"),
                PredictedFinding(file="pkg/unrelated.py", line_start=1, line_end=2, severity="blocking"),
                PredictedFinding(file="pkg/unrelated2.py", line_start=1, line_end=2, severity="blocking"),
            ),
        ),
        # bug-beta：召回不变（仍为 1），但新增 1 条未命中误报 -> regressed_cases（绝不能算 unchanged）
        CasePrediction(
            case_id="bug-beta",
            verdict="BLOCK",
            findings=(
                PredictedFinding(file="pkg/parser.py", line_start=20, line_end=21, severity="blocking"),
                PredictedFinding(file="pkg/noise.py", line_start=10, line_end=11, severity="blocking"),
            ),
        ),
        CasePrediction(case_id="clean-one", verdict="PASS"),
        CasePrediction(case_id="clean-two", verdict="PASS"),
    )
    score_noisy = score_predictions(cases, noisy_preds, line_tolerance=15, max_finding_span=120)
    cmp_res = compare_scores(score_base, score_noisy)
    assert cmp_res.regressed_cases == ("bug-beta",)
    assert cmp_res.mixed_cases == ("bug-alpha",)
    assert cmp_res.unchanged_cases == ("clean-one", "clean-two")
    assert cmp_res.improved_cases == ()


def _write_run(
    runs_dir: Path,
    name: str,
    *,
    pr_number: int,
    head_sha: str | None,
    registered_at_ns: int | None,
    attempt: int | None,
    verdict: str | None,
    reviews: list[dict[str, object]] | None = None,
    receipts: dict[str, dict[str, object]] | None = None,
    reused_from: str | None = None,
) -> Path:
    run_dir = runs_dir / name
    run_dir.mkdir(parents=True)
    target: dict[str, object] = {
        "pr_number": pr_number,
        "base_sha": "0" * 40,
    }
    if attempt is not None:
        target["attempt"] = attempt
    if head_sha is not None:
        target["head_sha"] = head_sha
    if registered_at_ns is not None:
        target["registered_at_ns"] = registered_at_ns
    (run_dir / "target.json").write_text(json.dumps(target), encoding="utf-8")
    if verdict is not None:
        outcome: dict[str, object] = {
            "run_id": f"run-{name}",
            "verdict": verdict,
            "target": target,
            "reviews": reviews or [],
        }
        if reused_from is not None:
            outcome["reused_from"] = reused_from
        (run_dir / "outcome.json").write_text(json.dumps(outcome), encoding="utf-8")
    for model_name, receipt_obj in (receipts or {}).items():
        mdir = run_dir / model_name
        mdir.mkdir(parents=True)
        (mdir / "receipt.json").write_text(json.dumps(receipt_obj), encoding="utf-8")
    return run_dir


def test_analyze_review_runs_rounds_corrupted_and_dispositions(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # PR 101: 第 1 轮 FAILED（infra），第 2 轮 BLOCK（head A），第 3 轮 PASS（head B）
    # 全量口径首 PASS = 3 轮；有效评审口径（去 FAILED 与复用）= 2 轮。
    _write_run(
        runs_dir,
        "p101-r1",
        pr_number=101,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="FAILED",
        reviews=[
            {"model": "kimi-k3.1-pro", "verdict": "FAILED"},
            {"model": "claude-opus-5-5", "verdict": "FAILED"},
        ],
        receipts={"kimi-k3.1-pro": {"status": "failed", "model": "kimi-k3.1-pro", "result": None}},
    )
    _write_run(
        runs_dir,
        "p101-r2",
        pr_number=101,
        head_sha="a" * 40,
        registered_at_ns=200,
        attempt=2,
        verdict="BLOCK",
        reviews=[
            {"model": "kimi-k3.1-pro", "verdict": "PASS"},
            {"model": "claude-opus-5-5", "verdict": "BLOCK"},
        ],
        receipts={
            "claude-opus-5-5": {
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {
                    "status": "blocked",
                    "findings": [
                        "[P1] auth.py:12 缺少边界校验导致越权",
                        "请运行 rustfmt 修复缩进格式问题",
                        "[nit] 建议后续补充文档说明",
                    ],
                },
            }
        },
    )
    _write_run(
        runs_dir,
        "p101-r3",
        pr_number=101,
        head_sha="b" * 40,
        registered_at_ns=300,
        attempt=3,
        verdict="PASS",
        reviews=[
            {"model": "kimi-k3.1-pro", "verdict": "PASS"},
            {"model": "claude-opus-5-5", "verdict": "PASS"},
        ],
        receipts={
            "kimi-k3.1-pro": {
                "status": "completed",
                "model": "kimi-k3.1-pro",
                "result": {
                    "status": "completed",
                    "findings": ["非阻断：可顺手抽取常量", "非阻断：可补充注释说明"],
                },
            }
        },
    )

    # PR 102: 单轮 PASS（沿用历史复用）
    _write_run(
        runs_dir,
        "p102-r1",
        pr_number=102,
        head_sha="c" * 40,
        registered_at_ns=150,
        attempt=1,
        verdict="PASS",
        reused_from="earlier-run",
        reviews=[
            {"model": "kimi-k3.1-pro", "verdict": "PASS"},
            {"model": "claude-opus-5-5", "verdict": "PASS"},
        ],
    )

    # PR 103: 缺 outcome.json 且含损坏 JSON 与非法 UTF-8 字节 receipt.json
    p103 = _write_run(
        runs_dir,
        "p103-r1",
        pr_number=103,
        head_sha="d" * 40,
        registered_at_ns=400,
        attempt=1,
        verdict=None,
    )
    bad_model_dir = p103 / "claude-opus-5-5"
    bad_model_dir.mkdir()
    (bad_model_dir / "receipt.json").write_text("{broken json", encoding="utf-8")
    bad_utf8_dir = p103 / "kimi-k3.1-pro"
    bad_utf8_dir.mkdir()
    (bad_utf8_dir / "receipt.json").write_bytes(b"\xff\xfe\x00invalid utf8")

    disp_path = tmp_path / "dispositions.jsonl"
    disp_rows = [
        {"run_id": "run-p101-r2", "pr_number": 101, "model": "claude-opus-5-5", "finding_index": 0, "disposition": "fixed"},
        {
            "run_id": "run-p101-r2",
            "pr_number": 101,
            "model": "claude-opus-5-5",
            "finding_index": 1,
            "disposition": "not_important",
        },
        {
            "run_id": "run-p101-r2",
            "pr_number": 101,
            "model": "claude-opus-5-5",
            "finding_index": 2,
            "disposition": "false_positive",
        },
        {
            "run_id": "run-p101-r3",
            "pr_number": 101,
            "model": "kimi-k3.1-pro",
            "finding_index": 0,
            "disposition": "intentional",
        },
        {
            "run_id": "run-p101-r3",
            "pr_number": 101,
            "model": "kimi-k3.1-pro",
            "finding_index": 1,
            "disposition": "unresolved",
        },
    ]
    disp_path.write_text("\n".join(json.dumps(r) for r in disp_rows) + "\n", encoding="utf-8")

    loaded_disp = load_dispositions(disp_path)
    assert len(loaded_disp) == 5
    assert loaded_disp[0].disposition is DispositionLabel.FIXED

    metrics = analyze_review_runs(runs_dir, dispositions_path=disp_path)
    assert metrics.total_runs == 5
    assert metrics.missing_outcome_runs == 1
    assert metrics.reused_runs == 1
    assert metrics.fresh_pass_runs == 1
    assert metrics.unorderable_runs == 0
    assert metrics.corrupted_files == (
        "p103-r1/claude-opus-5-5/receipt.json",
        "p103-r1/kimi-k3.1-pro/receipt.json",
    )
    assert metrics.verdict_counts == {"BLOCK": 1, "FAILED": 1, "MISSING_OUTCOME": 1, "PASS": 2}
    # 含复用分母：1 / (2 + 1) = 1/3；仅新产生裁定分母：1 / (1 + 1) = 0.5
    assert metrics.block_rate_decided_including_reuse == pytest.approx(1 / 3, rel=1e-5)
    assert metrics.block_rate_decided == pytest.approx(1 / 3, rel=1e-5)
    assert metrics.block_rate_fresh_decided == pytest.approx(0.5)
    assert metrics.unique_prs == 3
    assert metrics.prs_with_pass == 2
    assert metrics.prs_without_pass == 1
    assert metrics.prs_first_pass_reused == 1

    # 全量口径：PR 101 = 3 轮，PR 102 = 1 轮 -> 中位数 2.0，均值 2.0
    assert metrics.rounds_to_first_pass_all.prs_counted == 2
    assert metrics.rounds_to_first_pass_all.bucket_1 == 1
    assert metrics.rounds_to_first_pass_all.bucket_3 == 1
    assert metrics.rounds_to_first_pass_all.median == pytest.approx(2.0)

    # 有效评审口径（排除 reused_from）：仅 PR 101 = 2 轮（PR 102 首次 PASS 为历史复用已单列）
    assert metrics.rounds_to_first_pass_effective.prs_counted == 1
    assert metrics.rounds_to_first_pass_effective.bucket_2 == 1
    assert metrics.rounds_to_first_pass_effective.mean == pytest.approx(2.0)

    assert metrics.total_findings == 5
    assert metrics.findings_by_receipt_status == {"blocked": 3, "completed": 2}
    assert metrics.finding_heuristic_categories["blocking_substantive"] == 1
    assert metrics.finding_heuristic_categories["blocking_style_or_format"] == 1
    assert metrics.finding_heuristic_categories["non_blocking_or_nit"] == 3
    assert metrics.style_or_format_findings == 1
    assert metrics.nit_style_or_format_findings == 0
    # p101-r2 的 2 条非 Nit 阻断发现随后在 p101-r3 更晚时间戳不同 head 转 PASS
    assert metrics.subsequent_head_pass_total_block_findings == 2
    assert metrics.subsequent_head_pass_inferred_fixed == 2
    assert metrics.subsequent_head_pass_undeterminable_findings == 0
    assert metrics.subsequent_head_pass_inferred_rate == pytest.approx(1.0)

    # 显式台账 5 条覆盖 5 条发现 -> 100%，4 类已定性各占 25%
    assert metrics.disposition_total == 5
    assert metrics.disposition_coverage_rate == pytest.approx(1.0)
    for key in ("fixed", "false_positive", "intentional", "not_important"):
        assert metrics.disposition_resolved_rates[key] == pytest.approx(0.25)

    md = render_baseline_markdown(metrics)
    assert "收据实测事实" in md
    assert "正则/启发式分类" in md
    assert "显式去向台账统计" in md
    assert "当前显式去向覆盖率" in md
    assert "仅新产生裁定分母" in md
    assert "含历史复用 PASS 分母" in md


def test_analyze_review_runs_unorderable_and_missing_head_sha(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # PR 201: BLOCK 缺少 registered_at_ns，不得排序到 0 也不得被后续 PASS 推定已修
    _write_run(
        runs_dir,
        "p201-r1-nots",
        pr_number=201,
        head_sha="a" * 40,
        registered_at_ns=None,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 缺陷 A"]},
            }
        },
    )
    _write_run(
        runs_dir,
        "p201-r2-pass",
        pr_number=201,
        head_sha="b" * 40,
        registered_at_ns=500,
        attempt=2,
        verdict="PASS",
    )

    # PR 202: BLOCK 缺少 head_sha，虽有更晚 PASS 但不可判定是否换 head
    _write_run(
        runs_dir,
        "p202-r1-nohead",
        pr_number=202,
        head_sha="",
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 缺陷 B", "[P1] 缺陷 C"]},
            }
        },
    )
    _write_run(
        runs_dir,
        "p202-r2-pass",
        pr_number=202,
        head_sha="c" * 40,
        registered_at_ns=200,
        attempt=2,
        verdict="PASS",
    )

    # PR 203: BLOCK 有完整字段，但后续 PASS 缺少 head_sha -> 同样不可判定
    _write_run(
        runs_dir,
        "p203-r1-block",
        pr_number=203,
        head_sha="d" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 缺陷 D"]},
            }
        },
    )
    _write_run(
        runs_dir,
        "p203-r2-pass-nohead",
        pr_number=203,
        head_sha=None,
        registered_at_ns=200,
        attempt=2,
        verdict="PASS",
    )

    # PR 204: BLOCK 与 PASS 时间戳相同（未严格 pass_ts > block_ts）-> 不计推定已修
    _write_run(
        runs_dir,
        "p204-r1-block",
        pr_number=204,
        head_sha="e" * 40,
        registered_at_ns=300,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 缺陷 E"]},
            }
        },
    )
    _write_run(
        runs_dir,
        "p204-r2-pass-samets",
        pr_number=204,
        head_sha="f" * 40,
        registered_at_ns=300,
        attempt=2,
        verdict="PASS",
    )

    # PR 205: 同 PR 仅有 head A 的带时间戳 BLOCK 与 head B 的缺时间戳 PASS -> 无法判断先后，必须计入不可判定
    _write_run(
        runs_dir,
        "p205-r1-block",
        pr_number=205,
        head_sha="1" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 缺陷 F"]},
            }
        },
    )
    _write_run(
        runs_dir,
        "p205-r2-pass-nots",
        pr_number=205,
        head_sha="2" * 40,
        registered_at_ns=None,
        attempt=2,
        verdict="PASS",
    )

    # PR 206: 同 PR 虽有无时间戳 PASS，但也存在严格更晚且换 head 的可排序 PASS -> 仍可正判为推定已修
    _write_run(
        runs_dir,
        "p206-r1-block",
        pr_number=206,
        head_sha="3" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 缺陷 G"]},
            }
        },
    )
    _write_run(
        runs_dir,
        "p206-r2-pass-nots",
        pr_number=206,
        head_sha="4" * 40,
        registered_at_ns=None,
        attempt=2,
        verdict="PASS",
    )
    _write_run(
        runs_dir,
        "p206-r3-pass-later",
        pr_number=206,
        head_sha="5" * 40,
        registered_at_ns=200,
        attempt=3,
        verdict="PASS",
    )

    metrics = analyze_review_runs(runs_dir)
    assert metrics.unorderable_runs == 3
    # PR 201(1) + PR 202(2) + PR 203(1) + PR 205(1) = 5 条不可判定；PR 204(1 未修) + PR 206(1 已修) = 2 条可判定
    assert metrics.subsequent_head_pass_undeterminable_findings == 5
    assert metrics.subsequent_head_pass_total_block_findings == 2
    assert metrics.subsequent_head_pass_inferred_fixed == 1
    assert metrics.subsequent_head_pass_inferred_rate == pytest.approx(0.5)


def test_unorderable_pass_same_head_vs_different_head_dual_control(tmp_path: Path) -> None:
    # 对照 A：无时间戳 PASS 用不同 head B -> 无法确认先后，可判定 0、不可判定 1、推定已修 0
    diff_head_dir = tmp_path / "diff-head"
    diff_head_dir.mkdir()
    _write_run(
        diff_head_dir,
        "p501-r1-block",
        pr_number=501,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 真实阻断缺陷"]},
            }
        },
    )
    _write_run(
        diff_head_dir,
        "p501-r2-pass-nots-head-b",
        pr_number=501,
        head_sha="b" * 40,
        registered_at_ns=None,
        attempt=2,
        verdict="PASS",
    )
    diff_metrics = analyze_review_runs(diff_head_dir)
    assert diff_metrics.subsequent_head_pass_total_block_findings == 0
    assert diff_metrics.subsequent_head_pass_undeterminable_findings == 1
    assert diff_metrics.subsequent_head_pass_inferred_fixed == 0

    # 对照 B：无时间戳 PASS 改用相同 head A -> 无论先后都不满足“换 head 后 PASS”，可判定 1、不可判定 0、推定已修 0
    same_head_dir = tmp_path / "same-head"
    same_head_dir.mkdir()
    _write_run(
        same_head_dir,
        "p502-r1-block",
        pr_number=502,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 真实阻断缺陷"]},
            }
        },
    )
    _write_run(
        same_head_dir,
        "p502-r2-pass-nots-head-a",
        pr_number=502,
        head_sha="a" * 40,
        registered_at_ns=None,
        attempt=2,
        verdict="PASS",
    )
    same_metrics = analyze_review_runs(same_head_dir)
    assert same_metrics.subsequent_head_pass_total_block_findings == 1
    assert same_metrics.subsequent_head_pass_undeterminable_findings == 0
    assert same_metrics.subsequent_head_pass_inferred_fixed == 0

    # 对照 C：无时间戳 PASS 缺 head_sha -> 不可判定 1
    missing_head_dir = tmp_path / "missing-head"
    missing_head_dir.mkdir()
    _write_run(
        missing_head_dir,
        "p503-r1-block",
        pr_number=503,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 真实阻断缺陷"]},
            }
        },
    )
    _write_run(
        missing_head_dir,
        "p503-r2-pass-nots-nohead",
        pr_number=503,
        head_sha=None,
        registered_at_ns=None,
        attempt=2,
        verdict="PASS",
    )
    missing_metrics = analyze_review_runs(missing_head_dir)
    assert missing_metrics.subsequent_head_pass_total_block_findings == 0
    assert missing_metrics.subsequent_head_pass_undeterminable_findings == 1
    assert missing_metrics.subsequent_head_pass_inferred_fixed == 0


def test_dispositions_reject_duplicates_and_dangling_references(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_run(
        runs_dir,
        "p301-r1",
        pr_number=301,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 唯一发现"]},
            }
        },
    )

    # 1) load_dispositions 拒绝重复键 (run_id, model, finding_index)
    dup_file = tmp_path / "dup.jsonl"
    row = {"run_id": "run-p301-r1", "pr_number": 301, "model": "claude-opus-5-5", "finding_index": 0, "disposition": "fixed"}
    dup_file.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(EvalValidationError, match="重复去向键"):
        load_dispositions(dup_file)

    # 2) 不存在的 (run_id, model) 回执 -> 拒绝
    with pytest.raises(EvalValidationError, match="不存在的回执"):
        analyze_review_runs(
            runs_dir,
            dispositions=(
                DispositionEntry(
                    run_id="run-missing",
                    pr_number=301,
                    model="claude-opus-5-5",
                    finding_index=0,
                    disposition=DispositionLabel.FIXED,
                ),
            ),
        )

    # 3) pr_number 不一致 -> 拒绝
    with pytest.raises(EvalValidationError, match="pr_number 与回执不一致"):
        analyze_review_runs(
            runs_dir,
            dispositions=(
                DispositionEntry(
                    run_id="run-p301-r1",
                    pr_number=999,
                    model="claude-opus-5-5",
                    finding_index=0,
                    disposition=DispositionLabel.FIXED,
                ),
            ),
        )

    # 4) finding_index 越界 -> 拒绝
    with pytest.raises(EvalValidationError, match="finding_index 越界"):
        analyze_review_runs(
            runs_dir,
            dispositions=(
                DispositionEntry(
                    run_id="run-p301-r1",
                    pr_number=301,
                    model="claude-opus-5-5",
                    finding_index=1,
                    disposition=DispositionLabel.FALSE_POSITIVE,
                ),
            ),
        )


def test_conflicting_receipt_run_id_marked_corrupted_and_rejected_by_dispositions(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # 反例：outcome.json 声明 run_id="A"，receipt.json 声明 run_id="C"
    run_a = runs_dir / "run-a"
    run_a.mkdir()
    (run_a / "target.json").write_text(
        json.dumps({"pr_number": 401, "base_sha": "0" * 40, "head_sha": "a" * 40, "registered_at_ns": 100, "attempt": 1}),
        encoding="utf-8",
    )
    (run_a / "outcome.json").write_text(
        json.dumps({"run_id": "A", "verdict": "BLOCK", "reviews": [{"model": "claude-opus-5-5", "verdict": "BLOCK"}]}),
        encoding="utf-8",
    )
    model_dir = run_a / "claude-opus-5-5"
    model_dir.mkdir()
    (model_dir / "receipt.json").write_text(
        json.dumps(
            {
                "run_id": "C",
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 跨轮混入发现"]},
            }
        ),
        encoding="utf-8",
    )

    # 无 outcome.json 时，target.json 声明 run_id="T" 但 receipt.json 声明 run_id="X" 也必须拒绝
    run_t = runs_dir / "run-t"
    run_t.mkdir()
    (run_t / "target.json").write_text(
        json.dumps(
            {
                "run_id": "T",
                "pr_number": 402,
                "base_sha": "0" * 40,
                "head_sha": "b" * 40,
                "registered_at_ns": 200,
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )
    model_dir_t = run_t / "kimi-k3.1-pro"
    model_dir_t.mkdir()
    (model_dir_t / "receipt.json").write_text(
        json.dumps(
            {
                "run_id": "X",
                "status": "completed",
                "model": "kimi-k3.1-pro",
                "result": {"status": "blocked", "findings": ["[P1] target 冲突发现"]},
            }
        ),
        encoding="utf-8",
    )

    metrics = analyze_review_runs(runs_dir)
    assert metrics.corrupted_files == (
        "run-a/claude-opus-5-5/receipt.json",
        "run-t/kimi-k3.1-pro/receipt.json",
    )
    assert metrics.total_receipts == 0
    assert metrics.total_findings == 0

    for bad_run_id in ("A", "C"):
        with pytest.raises(EvalValidationError, match="不存在的回执"):
            analyze_review_runs(
                runs_dir,
                dispositions=(
                    DispositionEntry(
                        run_id=bad_run_id,
                        pr_number=401,
                        model="claude-opus-5-5",
                        finding_index=0,
                        disposition=DispositionLabel.FIXED,
                    ),
                ),
            )


def test_conflicting_outcome_and_target_run_id_rejects_omitted_and_tagged_receipts(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # 精确反例：outcome.run_id="A" + target.run_id="B" + 回执省略 run_id（另附一条显式带 run_id="A" 的回执）
    run_conflict = runs_dir / "run-conflict"
    run_conflict.mkdir()
    (run_conflict / "target.json").write_text(
        json.dumps(
            {
                "run_id": "B",
                "pr_number": 403,
                "base_sha": "0" * 40,
                "head_sha": "c" * 40,
                "registered_at_ns": 300,
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )
    (run_conflict / "outcome.json").write_text(
        json.dumps({"run_id": "A", "verdict": "BLOCK", "reviews": [{"model": "M", "verdict": "BLOCK"}]}),
        encoding="utf-8",
    )
    m_omitted = run_conflict / "M"
    m_omitted.mkdir()
    (m_omitted / "receipt.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "model": "M",
                "result": {"status": "blocked", "findings": ["[P1] 省略 run_id 的回执发现"]},
            }
        ),
        encoding="utf-8",
    )
    m_tagged = run_conflict / "M2"
    m_tagged.mkdir()
    (m_tagged / "receipt.json").write_text(
        json.dumps(
            {
                "run_id": "A",
                "status": "completed",
                "model": "M2",
                "result": {"status": "blocked", "findings": ["[P1] 自带 run_id=A 的回执发现"]},
            }
        ),
        encoding="utf-8",
    )

    metrics = analyze_review_runs(runs_dir)
    assert "run-conflict/outcome.json" in metrics.corrupted_files
    assert "run-conflict/target.json" in metrics.corrupted_files
    assert "run-conflict/M/receipt.json" in metrics.corrupted_files
    assert "run-conflict/M2/receipt.json" in metrics.corrupted_files
    assert metrics.total_receipts == 0
    assert metrics.total_findings == 0

    for bad_run_id in ("A", "B", "run-conflict"):
        for model_name in ("M", "M2"):
            with pytest.raises(EvalValidationError, match="不存在的回执"):
                analyze_review_runs(
                    runs_dir,
                    dispositions=(
                        DispositionEntry(
                            run_id=bad_run_id,
                            pr_number=403,
                            model=model_name,
                            finding_index=0,
                            disposition=DispositionLabel.FIXED,
                        ),
                    ),
                )


def test_cli_end_to_end_and_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cases_path = tmp_path / "cases.json"
    cases_payload = {
        "schema_version": SCHEMA_VERSION,
        "cases": [
            {
                "case_id": "b1",
                "kind": "bug",
                "title": "bug 1",
                "base_sha": SHA_1,
                "head_sha": SHA_2,
                "fix_sha": None,
                "bug_locations": [
                    {
                        "file": "a.py",
                        "line_start": 10,
                        "line_end": 12,
                        "summary": "s",
                        "category": "cat",
                    }
                ],
            },
            {
                "case_id": "c1",
                "kind": "clean",
                "title": "clean 1",
                "base_sha": SHA_3,
                "head_sha": SHA_4,
                "fix_sha": None,
                "bug_locations": [],
            },
        ],
    }
    cases_path.write_text(json.dumps(cases_payload), encoding="utf-8")

    assert main(["validate-cases", "--cases", str(cases_path)]) == 0
    capsys.readouterr()

    pred_a = tmp_path / "pred_a.json"
    pred_a.write_text(
        json.dumps([{"case_id": "b1", "verdict": "PASS", "findings": []}, {"case_id": "c1", "verdict": "PASS"}]),
        encoding="utf-8",
    )
    score_a = tmp_path / "score_a.json"
    assert main(["score", "--cases", str(cases_path), "--predictions", str(pred_a), "--out-json", str(score_a)]) == 0

    pred_b = tmp_path / "pred_b.json"
    pred_b.write_text(
        json.dumps(
            [
                {
                    "case_id": "b1",
                    "verdict": "BLOCK",
                    "findings": [{"file": "a.py", "line_start": 11, "line_end": 11, "severity": "blocking"}],
                },
                {"case_id": "c1", "verdict": "PASS", "findings": []},
            ]
        ),
        encoding="utf-8",
    )
    score_b = tmp_path / "score_b.json"
    assert main(["score", "--cases", str(cases_path), "--predictions", str(pred_b), "--out-json", str(score_b)]) == 0

    cmp_out = tmp_path / "cmp.json"
    assert main(["compare", "--before", str(score_a), "--after", str(score_b), "--out-json", str(cmp_out)]) == 0
    cmp_data = json.loads(cmp_out.read_text(encoding="utf-8"))
    assert cmp_data["improved_cases"] == ["b1"]
    assert cmp_data["mixed_cases"] == []
    assert cmp_data["undecided_cases"] == []
    assert cmp_data["bug_case_recall_delta"] == pytest.approx(1.0)

    # 缺漏案例在默认模式下返回退出码 2，显式 --allow-partial 返回 0
    pred_partial = tmp_path / "pred_partial.json"
    pred_partial.write_text(json.dumps([{"case_id": "b1", "verdict": "PASS", "findings": []}]), encoding="utf-8")
    assert main(["score", "--cases", str(cases_path), "--predictions", str(pred_partial)]) == 2
    assert main(["score", "--cases", str(cases_path), "--predictions", str(pred_partial), "--allow-partial"]) == 0

    # 非法输入返回退出码 2（fail-closed）
    assert main(["validate-cases", "--cases", str(tmp_path / "missing.json")]) == 2


def test_bug_location_ranges_validation_and_fingerprint_normalization(tmp_path: Path) -> None:
    bad_range_cases: list[tuple[str, int, int, tuple[tuple[int, int], ...]]] = [
        ("duplicate", 10, 12, ((10, 12),)),
        ("unsorted", 20, 25, ((10, 12),)),
        ("overlapping", 10, 15, ((14, 20),)),
        ("adjacent-unmerged", 10, 15, ((16, 20),)),
        ("extra-adjacent", 10, 12, ((20, 22), (23, 25))),
        ("extra-unsorted", 10, 12, ((30, 32), (20, 22))),
    ]
    for label, start, end, extra in bad_range_cases:
        case = EvalCase(
            case_id=f"bad-{label}",
            kind="bug",
            title=label,
            base_sha=SHA_1,
            head_sha=SHA_2,
            bug_locations=(
                BugLocation(
                    file="a.py",
                    line_start=start,
                    line_end=end,
                    extra_ranges=extra,
                    summary="s",
                    category="c",
                ),
            ),
        )
        with pytest.raises(EvalValidationError, match="严格升序"):
            validate_cases((case,))

        json_path = tmp_path / f"bad_{label}.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "cases": [
                        {
                            "case_id": f"bad-{label}",
                            "kind": "bug",
                            "title": label,
                            "base_sha": SHA_1,
                            "head_sha": SHA_2,
                            "fix_sha": None,
                            "bug_locations": [
                                {
                                    "file": "a.py",
                                    "line_start": start,
                                    "line_end": end,
                                    "extra_ranges": [[s, e] for s, e in extra],
                                    "summary": "s",
                                    "category": "c",
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(EvalValidationError, match="严格升序"):
            load_cases(json_path)

    # 即使绕过 validate_cases 直接调用 compute_cases_fingerprint，等价行集合也产生相同指纹
    canonical_merged = EvalCase(
        case_id="fp-norm",
        kind="bug",
        title="norm",
        base_sha=SHA_1,
        head_sha=SHA_2,
        bug_locations=(BugLocation(file="a.py", line_start=10, line_end=20, summary="s", category="c"),),
    )
    adjacent_unmerged = EvalCase(
        case_id="fp-norm",
        kind="bug",
        title="norm",
        base_sha=SHA_1,
        head_sha=SHA_2,
        bug_locations=(
            BugLocation(
                file="a.py",
                line_start=16,
                line_end=20,
                extra_ranges=((10, 15), (12, 14)),
                summary="s",
                category="c",
            ),
        ),
    )
    assert compute_cases_fingerprint((canonical_merged,)) == compute_cases_fingerprint((adjacent_unmerged,))


def test_diff_hunk_full_line_coverage_and_segment_1210_counterexample(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    (repo / "gap.py").write_text("l1\nl2\nl3\nl4\nl5\nl6\n", encoding="utf-8")
    _git(repo, "add", "gap.py")
    _git(repo, "commit", "-qm", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    # 仅改第 1..2 行与第 5..6 行，第 3..4 行未改动
    (repo / "gap.py").write_text("l1_new\nl2_new\nl3\nl4\nl5_new\nl6_new\n", encoding="utf-8")
    _git(repo, "add", "gap.py")
    _git(repo, "commit", "-qm", "head")
    head_sha = _git(repo, "rev-parse", "HEAD")

    # 横跨未改动空档 3..4 的 1..6 必须被严格逐行包含校验拒绝
    spanning_gap = EvalCase(
        case_id="span-gap",
        kind="bug",
        title="含未改动空档",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="gap.py", line_start=1, line_end=6, summary="s", category="c"),),
    )
    with pytest.raises(EvalValidationError, match="未完全落在.*可用 hunk：1\\.\\.2, 5\\.\\.6"):
        validate_cases((spanning_gap,), repo_root=repo)

    # 拆成 1..2 与 extra_ranges=((5, 6),) 后通过
    split_clean = EvalCase(
        case_id="split-clean",
        kind="bug",
        title="精确离散区间",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(
            BugLocation(
                file="gap.py",
                line_start=1,
                line_end=2,
                extra_ranges=((5, 6),),
                summary="s",
                category="c",
            ),
        ),
    )
    validate_cases((split_clean,), repo_root=repo)

    # R4 反例：cases.json 中 bug-1978 loc[1] 精确拆段后，报未改动空行 segment.rs:1210 在 line_tolerance=0 下绝不命中
    cases = load_cases(CANONICAL_CASES)
    case_1978 = next(c for c in cases if c.case_id == "bug-1978-segment-seed-scan-revert")
    assert case_1978.bug_locations[1].all_ranges == ((1176, 1187), (1193, 1193), (1215, 1217), (1223, 1223))
    score_1210 = score_predictions(
        (case_1978,),
        (
            CasePrediction(
                case_id=case_1978.case_id,
                verdict="BLOCK",
                findings=(
                    PredictedFinding(
                        file="rust/src/theta_v0/parser/segment.rs",
                        line_start=1210,
                        line_end=1210,
                        severity="blocking",
                    ),
                ),
            ),
        ),
        line_tolerance=0,
    )
    assert score_1210.matched_bug_locations == 0
    assert score_1210.bug_case_recall == pytest.approx(0.0)


def test_explicit_invalid_identity_fields_and_cross_receipt_conflict(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # 1) 回执携带显式非法 run_id=7 与 run_id="   "：绝不回退到目录 run_id，记入 corrupted_files 并拒收
    run_bad_r = runs_dir / "run-bad-receipt"
    run_bad_r.mkdir()
    (run_bad_r / "target.json").write_text(
        json.dumps(
            {
                "run_id": "R1",
                "pr_number": 701,
                "base_sha": "0" * 40,
                "head_sha": "a" * 40,
                "registered_at_ns": 100,
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )
    (run_bad_r / "outcome.json").write_text(
        json.dumps({"run_id": "R1", "verdict": "BLOCK", "reviews": [{"model": "M-ok", "verdict": "BLOCK"}]}),
        encoding="utf-8",
    )
    for model_name, bad_rid in (("M-int", 7), ("M-ws", "   ")):
        mdir = run_bad_r / model_name
        mdir.mkdir()
        (mdir / "receipt.json").write_text(
            json.dumps(
                {
                    "run_id": bad_rid,
                    "status": "completed",
                    "model": model_name,
                    "result": {"status": "blocked", "findings": ["[P1] 非法 run_id 发现"]},
                }
            ),
            encoding="utf-8",
        )
    m_ok = run_bad_r / "M-ok"
    m_ok.mkdir()
    (m_ok / "receipt.json").write_text(
        json.dumps(
            {
                "run_id": "R1",
                "status": "completed",
                "model": "M-ok",
                "result": {"status": "blocked", "findings": ["[P1] 合法回执发现"]},
            }
        ),
        encoding="utf-8",
    )

    # 2) 目录层无 run_id 且无 outcome.json，但两份回执分别声明 "A" 与 "B"（另含省略 run_id 的第 3 份）
    #    -> 整个目录所有回执全部进 corrupted_files 并拒收
    run_split = runs_dir / "run-no-outcome-split"
    run_split.mkdir()
    (run_split / "target.json").write_text(
        json.dumps({"pr_number": 702, "head_sha": "b" * 40, "registered_at_ns": 200, "attempt": 1}),
        encoding="utf-8",
    )
    for model_name, extra in (("M-a", {"run_id": "A"}), ("M-b", {"run_id": "B"}), ("M-omit", {})):
        mdir = run_split / model_name
        mdir.mkdir()
        payload: dict[str, object] = {
            "status": "completed",
            "model": model_name,
            "result": {"status": "blocked", "findings": [f"[P1] {model_name} 发现"]},
            **extra,
        }
        (mdir / "receipt.json").write_text(json.dumps(payload), encoding="utf-8")

    metrics = analyze_review_runs(runs_dir)
    assert metrics.corrupted_files == (
        "run-bad-receipt/M-int/receipt.json",
        "run-bad-receipt/M-ws/receipt.json",
        "run-no-outcome-split/M-a/receipt.json",
        "run-no-outcome-split/M-b/receipt.json",
        "run-no-outcome-split/M-omit/receipt.json",
    )
    assert metrics.total_receipts == 1
    assert metrics.total_findings == 1

    # 拒收的非法/冲突回执均不可被 dispositions 台账引用
    for rid, pr, model in (
        ("R1", 701, "M-int"),
        ("R1", 701, "M-ws"),
        ("A", 702, "M-a"),
        ("B", 702, "M-b"),
        ("run-no-outcome-split", 702, "M-omit"),
    ):
        with pytest.raises(EvalValidationError, match="不存在的回执"):
            analyze_review_runs(
                runs_dir,
                dispositions=(
                    DispositionEntry(
                        run_id=rid,
                        pr_number=pr,
                        model=model,
                        finding_index=0,
                        disposition=DispositionLabel.FIXED,
                    ),
                ),
            )


def test_conflicting_target_and_outcome_identity_isolated_from_pr_timeline(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # R4 反例：PR 1 在 t=1, head A 有有效 BLOCK（1 条阻断发现）
    _write_run(
        runs_dir,
        "p1-r1-block",
        pr_number=1,
        head_sha="a" * 40,
        registered_at_ns=1,
        attempt=1,
        verdict="BLOCK",
        reviews=[{"model": "claude-opus-5-5", "verdict": "BLOCK"}],
        receipts={
            "claude-opus-5-5": {
                "run_id": "run-p1-r1-block",
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 真实缺陷"]},
            }
        },
    )

    # 下一目录：target.json 属 PR 1、run B、t=2、head B，但 outcome.json 的 PASS 属 PR 2、run C
    conflict_dir = runs_dir / "p1-vs-p2-conflict"
    conflict_dir.mkdir()
    (conflict_dir / "target.json").write_text(
        json.dumps(
            {
                "run_id": "B",
                "pr_number": 1,
                "base_sha": "0" * 40,
                "head_sha": "b" * 40,
                "registered_at_ns": 2,
                "attempt": 2,
            }
        ),
        encoding="utf-8",
    )
    (conflict_dir / "outcome.json").write_text(
        json.dumps(
            {
                "run_id": "C",
                "verdict": "PASS",
                "reused_from": "earlier-run",
                "target": {
                    "run_id": "C",
                    "pr_number": 2,
                    "head_sha": "c" * 40,
                    "registered_at_ns": 2,
                    "attempt": 1,
                },
                "reviews": [
                    {"model": "claude-opus-5-5", "verdict": "PASS"},
                    {"model": "kimi-k3.1-pro", "verdict": "PASS"},
                ],
            }
        ),
        encoding="utf-8",
    )
    c_receipt_dir = conflict_dir / "claude-opus-5-5"
    c_receipt_dir.mkdir()
    (c_receipt_dir / "receipt.json").write_text(
        json.dumps(
            {
                "run_id": "C",
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "completed", "findings": ["非阻断：冲突目录内回执"]},
            }
        ),
        encoding="utf-8",
    )

    metrics = analyze_review_runs(runs_dir)
    assert metrics.total_runs == 2
    assert metrics.verdict_counts == {"BLOCK": 1, "CORRUPTED_IDENTITY": 1}
    assert metrics.corrupted_files == (
        "p1-vs-p2-conflict/target.json",
        "p1-vs-p2-conflict/outcome.json",
        "p1-vs-p2-conflict/claude-opus-5-5/receipt.json",
    )
    assert metrics.unique_prs == 1
    assert metrics.prs_with_pass == 0
    assert metrics.prs_without_pass == 1
    assert metrics.reused_runs == 0
    assert metrics.total_receipts == 1
    assert metrics.total_findings == 1
    assert metrics.model_verdict_counts == {"claude-opus-5-5": {"BLOCK": 1}}
    assert metrics.model_pair_agreement == {}
    assert metrics.subsequent_head_pass_inferred_fixed == 0
    assert metrics.subsequent_head_pass_total_block_findings == 1
    assert metrics.subsequent_head_pass_undeterminable_findings == 0


def test_orthogonal_nit_and_style_format_classification(tmp_path: Path) -> None:
    assert is_non_blocking_or_nit_finding("[Nit] formatting", "blocked") is True
    assert is_style_or_format_finding("[Nit] formatting") is True
    assert classify_finding_heuristic("[Nit] formatting", "blocked") == "non_blocking_or_nit"

    assert is_non_blocking_or_nit_finding("请运行 rustfmt 修复缩进格式问题", "blocked") is False
    assert is_style_or_format_finding("请运行 rustfmt 修复缩进格式问题") is True
    assert classify_finding_heuristic("请运行 rustfmt 修复缩进格式问题", "blocked") == "blocking_style_or_format"

    assert classify_finding_heuristic("[P1] 越权漏洞", "blocked") == "blocking_substantive"

    # R4 反例：合法时间与 head 的 BLOCK 轮次，result.status="blocked"，唯一发现 "[Nit] formatting"
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_run(
        runs_dir,
        "p801-r1-nit-fmt",
        pr_number=801,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "run_id": "run-p801-r1-nit-fmt",
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[Nit] formatting"]},
            }
        },
    )

    metrics = analyze_review_runs(runs_dir)
    assert metrics.total_findings == 1
    assert metrics.style_or_format_findings == 1
    assert metrics.nit_style_or_format_findings == 1
    assert metrics.finding_heuristic_categories == {"non_blocking_or_nit": 1}
    assert metrics.subsequent_head_pass_total_block_findings == 0
    assert metrics.subsequent_head_pass_undeterminable_findings == 0
    assert metrics.subsequent_head_pass_inferred_fixed == 0

    md = render_baseline_markdown(metrics)
    assert "格式/风格主题正交命中总数" in md
    assert "nit_style_or_format_findings" in md


def test_cli_unwritable_out_json_returns_friendly_error_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    rc = main(["baseline-stats", "--runs-dir", str(runs_dir), "--out-json", "/dev/null/out.json"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "/dev/null/out.json" in captured.err
    assert "无法写入输出文件" in captured.err
    assert "Traceback" not in captured.err


def test_git_diff_inter_hunk_context_and_unified_diff_plus_line_parsing(tmp_path: Path) -> None:
    # 1) 直接测试 unified diff 逐行 `+` 解析：含上下文空档、删除行、内容以 `++ ` 开头的新增行与无换行标记
    synthetic_diff = "\n".join(
        [
            "diff --git a/demo.py b/demo.py",
            "index 1111111..2222222 100644",
            "--- a/demo.py",
            "+++ b/demo.py",
            "@@ -1,6 +1,6 @@",
            "-old1",
            "+new1",
            "-old2",
            "+++ literal_plus_plus_line",
            " untouched3",
            " untouched4",
            "-old5",
            "+new5",
            "-old6",
            "+new6",
            "\\ No newline at end of file",
        ]
    )
    assert _parse_unified_diff_added_ranges(synthetic_diff) == ((1, 2), (5, 6))

    # 2) 真实临时 Git 仓显式开启 diff.interHunkContext=100：两处改动之间的未改动空档仍必须被 validate_cases 拒绝
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "diff.interHunkContext", "100")

    (repo / "gap.py").write_text("l1\nl2\nl3\nl4\nl5\nl6\n", encoding="utf-8")
    _git(repo, "add", "gap.py")
    _git(repo, "commit", "-qm", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    (repo / "gap.py").write_text("l1_new\nl2_new\nl3\nl4\nl5_new\nl6_new\n", encoding="utf-8")
    _git(repo, "add", "gap.py")
    _git(repo, "commit", "-qm", "head")
    head_sha = _git(repo, "rev-parse", "HEAD")

    # 确认裸 git diff -U0 在该配置下确实会把两处 hunk 合并成 @@ -1,6 +1,6 @@
    raw_diff = _git(repo, "diff", "-U0", base_sha, head_sha, "--", "gap.py")
    assert "@@ -1,6 +1,6 @@" in raw_diff

    spanning_gap = EvalCase(
        case_id="inter-hunk-gap",
        kind="bug",
        title="开启 interHunkContext=100 时仍拒绝未改动空档",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="gap.py", line_start=1, line_end=6, summary="s", category="c"),),
    )
    with pytest.raises(EvalValidationError, match="未完全落在.*可用 hunk：1\\.\\.2, 5\\.\\.6"):
        validate_cases((spanning_gap,), repo_root=repo)

    untouched_only = EvalCase(
        case_id="inter-hunk-untouched",
        kind="bug",
        title="仅指向未改动空档行",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="gap.py", line_start=3, line_end=4, summary="s", category="c"),),
    )
    with pytest.raises(EvalValidationError, match="未完全落在"):
        validate_cases((untouched_only,), repo_root=repo)

    split_valid = EvalCase(
        case_id="inter-hunk-split-ok",
        kind="bug",
        title="精确拆段通过",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(
            BugLocation(
                file="gap.py",
                line_start=1,
                line_end=2,
                extra_ranges=((5, 6),),
                summary="s",
                category="c",
            ),
        ),
    )
    validate_cases((split_valid,), repo_root=repo)


def test_leading_severity_tag_precedence_and_negation_safe_heuristic(tmp_path: Path) -> None:
    # 1) PR #2063 真实反例：显式 [阻断] 标签绝不被正文“不是可选后续优化”覆盖
    pr2063_blocking = (
        "[阻断] `.sandcastle/docs/maintenance-1742.md:193` 明确记录 macOS 现役可用性未验收，"
        "目标部署路径为 macOS `/Volumes`，因此这是当前 PR 自身确认尚未满足的发布条件，不是可选后续优化。"
    )
    assert _parse_leading_severity_tag(pr2063_blocking) == "blocking"
    assert is_non_blocking_or_nit_finding(pr2063_blocking, "blocked") is False
    assert classify_finding_heuristic(pr2063_blocking, "blocked") == "blocking_substantive"

    # 2) PR #2063 真实反例：全角 【nit】 归为 non_blocking_or_nit
    pr2063_nit = "【nit】`.sandcastle/decision-claimer.mts:622` 的 close 回调新增了 `signal` 参数，但没有使用。"
    assert _parse_leading_severity_tag(pr2063_nit) == "non_blocking"
    assert is_non_blocking_or_nit_finding(pr2063_nit, "blocked") is True
    assert classify_finding_heuristic(pr2063_nit, "blocked") == "non_blocking_or_nit"

    # 3) 各类显式行首标签（列表符号、粗体、方括号、全角方括号、冒号前导）
    for nb_text in (
        "[非阻断] 可稍后整理",
        "【非阻断/低】建议补充注释",
        "- **[P3 非阻断]** 小优化",
        "1. **Nit:** 变量命名可更清晰",
        "非阻断：可顺手抽取辅助函数",
        "不阻断：仅作记录",
        "[低] 影响轻微",
        "【低】可后续优化",
        "[信息] 仅提示",
        "【信息】行为符合预期",
        "[建议] 考虑抽取常量",
        "[提示] 注意缓存失效",
        "[已核对/无问题] 已核实无回归",
        "【核实通过】校验逻辑正确",
    ):
        assert _parse_leading_severity_tag(nb_text) == "non_blocking", nb_text
        assert is_non_blocking_or_nit_finding(nb_text, "blocked") is True, nb_text

    for blk_text in (
        "【阻断】核心路径存在空指针，这不是可选建议",
        "- **[BLOCK]** 越权绕过，非可选修复",
        "1. **[Important]** 数据丢失风险（建议后续也补监控）",
        "[P0] 崩溃缺陷，可顺手加单测",
        "[P1] 权限校验缺失",
        "[高] 严重回归",
        "【高】必须修复",
        "阻断：不可合入，不是可选后续优化",
        "Important: missing authz check (not optional)",
        "Blocker: breaks prod migration",
    ):
        assert _parse_leading_severity_tag(blk_text) == "blocking", blk_text
        assert is_non_blocking_or_nit_finding(blk_text, "blocked") is False, blk_text

    # 4) 文件路径前缀绝不误判为冒号严重度标签
    for path_prefixed in (
        "pilot1742/blocker.py:12: 路径解析错误",
        "src/low_level.rs:42: 边界越界",
        "docs/info.md:5: 缺少说明",
    ):
        assert _parse_leading_severity_tag(path_prefixed) is None, path_prefixed

    # 5) 无显式行首标签时，正文否定语境不误触发非阻断
    for negated in (
        "这是发布硬门条件，不是可选后续优化",
        "该安全修复非可选优化",
        "此处状态同步并非可选",
        "该项为必需修复，不是建议后续处理",
        "此逻辑非建议后续再改",
        "此缺陷并非建议后续跟进",
        "这不是可选：必须修复",
    ):
        assert _parse_leading_severity_tag(negated) is None, negated
        assert is_non_blocking_or_nit_finding(negated, "blocked") is False, negated

    # 6) 端到端统计：PR #2063 两类发现在 subsequent_head_pass_total_block_findings 中精确分流
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_run(
        runs_dir,
        "p2063-r1",
        pr_number=2063,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "kimi-k3.1-pro": {
                "run_id": "run-p2063-r1",
                "status": "completed",
                "model": "kimi-k3.1-pro",
                "result": {"status": "blocked", "findings": [pr2063_blocking]},
            },
            "claude-opus-5-5": {
                "run_id": "run-p2063-r1",
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": [pr2063_nit]},
            },
        },
    )
    metrics = analyze_review_runs(runs_dir)
    assert metrics.finding_heuristic_categories == {
        "blocking_substantive": 1,
        "non_blocking_or_nit": 1,
    }
    assert metrics.subsequent_head_pass_total_block_findings == 1
    assert metrics.subsequent_head_pass_inferred_fixed == 0


def test_outcome_non_dict_target_triggers_corrupted_identity_isolation(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # PR 1 在 t=1, head=a 有有效 BLOCK（1 条阻断发现）
    _write_run(
        runs_dir,
        "p1-r1-block",
        pr_number=1,
        head_sha="a" * 40,
        registered_at_ns=1,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "run_id": "run-p1-r1-block",
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[阻断] 真实缺陷"]},
            }
        },
    )

    # 第二目录：target.json 为 PR 1, t=2, head=b，但 outcome.json 的 target 为非 dict（7）
    bad_int_dir = runs_dir / "p1-r2-bad-target-int"
    bad_int_dir.mkdir()
    (bad_int_dir / "target.json").write_text(
        json.dumps({"pr_number": 1, "head_sha": "b" * 40, "registered_at_ns": 2, "attempt": 2}),
        encoding="utf-8",
    )
    (bad_int_dir / "outcome.json").write_text(
        json.dumps({"verdict": "PASS", "target": 7}),
        encoding="utf-8",
    )

    metrics = analyze_review_runs(runs_dir)
    assert metrics.corrupted_files == (
        "p1-r2-bad-target-int/target.json",
        "p1-r2-bad-target-int/outcome.json",
    )
    assert metrics.prs_with_pass == 0
    assert metrics.subsequent_head_pass_inferred_fixed == 0
    assert metrics.subsequent_head_pass_total_block_findings == 1
    assert metrics.verdict_counts == {"BLOCK": 1, "CORRUPTED_IDENTITY": 1}

    # 显式 target=null 同样按损坏隔离，绝不借用 target.json 纳入 PASS
    bad_null_dir = runs_dir / "p1-r3-bad-target-null"
    bad_null_dir.mkdir()
    (bad_null_dir / "target.json").write_text(
        json.dumps({"pr_number": 1, "head_sha": "c" * 40, "registered_at_ns": 3, "attempt": 3}),
        encoding="utf-8",
    )
    (bad_null_dir / "outcome.json").write_text(
        json.dumps({"verdict": "PASS", "target": None}),
        encoding="utf-8",
    )
    metrics_with_null = analyze_review_runs(runs_dir)
    assert "p1-r3-bad-target-null/outcome.json" in metrics_with_null.corrupted_files
    assert metrics_with_null.prs_with_pass == 0
    assert metrics_with_null.subsequent_head_pass_inferred_fixed == 0
    assert metrics_with_null.verdict_counts["CORRUPTED_IDENTITY"] == 2


def test_receipt_only_pr_number_preserved_for_disposition_binding(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # 无 target.json / outcome.json，仅回执给出合法 run_id="R", pr_number=1, model="M"
    run_only = runs_dir / "orphan-run"
    model_dir = run_only / "M"
    model_dir.mkdir(parents=True)
    (model_dir / "receipt.json").write_text(
        json.dumps(
            {
                "run_id": "R",
                "pr_number": 1,
                "status": "completed",
                "model": "M",
                "result": {"status": "blocked", "findings": ["[阻断] 孤立目录有效发现"]},
            }
        ),
        encoding="utf-8",
    )

    metrics = analyze_review_runs(
        runs_dir,
        dispositions=(
            DispositionEntry(
                run_id="R",
                pr_number=1,
                model="M",
                finding_index=0,
                disposition=DispositionLabel.FIXED,
            ),
        ),
    )
    assert metrics.corrupted_files == ()
    assert metrics.verdict_counts == {"MISSING_OUTCOME": 1}
    assert metrics.missing_outcome_runs == 1
    assert metrics.unorderable_runs == 1
    assert metrics.disposition_total == 1
    assert metrics.disposition_counts["fixed"] == 1
    assert metrics.disposition_coverage_rate == pytest.approx(1.0)


def test_duplicate_receipt_key_detected_and_rejected_by_dispositions(tmp_path: Path) -> None:
    # 1) 同目录下 X/receipt.json 与 Y/receipt.json 均声明 model="M"
    runs_dir = tmp_path / "same-dir-dup"
    run_dir = runs_dir / "run-dup"
    run_dir.mkdir(parents=True)
    (run_dir / "target.json").write_text(
        json.dumps({"run_id": "R", "pr_number": 1, "head_sha": "a" * 40, "registered_at_ns": 10, "attempt": 1}),
        encoding="utf-8",
    )
    for sub_name, finding_text in (("X", "[阻断] 发现 X"), ("Y", "[阻断] 发现 Y")):
        sub = run_dir / sub_name
        sub.mkdir()
        (sub / "receipt.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "model": "M",
                    "result": {"status": "blocked", "findings": [finding_text]},
                }
            ),
            encoding="utf-8",
        )

    metrics = analyze_review_runs(runs_dir)
    assert metrics.corrupted_files == (
        "run-dup/X/receipt.json",
        "run-dup/Y/receipt.json",
    )

    with pytest.raises(EvalValidationError, match="重复回执键"):
        analyze_review_runs(
            runs_dir,
            dispositions=(
                DispositionEntry(
                    run_id="R",
                    pr_number=1,
                    model="M",
                    finding_index=0,
                    disposition=DispositionLabel.FIXED,
                ),
            ),
        )

    # 2) 跨目录产生相同 (run_id="R2", model="M") 同样记入 corrupted_files 并拒绝歧义台账绑定
    cross_dir = tmp_path / "cross-dir-dup"
    for dname in ("dir-1", "dir-2"):
        d = cross_dir / dname
        (d / "M").mkdir(parents=True)
        (d / "target.json").write_text(
            json.dumps({"run_id": "R2", "pr_number": 2, "head_sha": "b" * 40, "registered_at_ns": 20, "attempt": 1}),
            encoding="utf-8",
        )
        (d / "M" / "receipt.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "model": "M",
                    "result": {"status": "blocked", "findings": [f"[阻断] {dname}"]},
                }
            ),
            encoding="utf-8",
        )

    cross_metrics = analyze_review_runs(cross_dir)
    assert cross_metrics.corrupted_files == (
        "dir-1/M/receipt.json",
        "dir-2/M/receipt.json",
    )
    with pytest.raises(EvalValidationError, match="重复回执键"):
        analyze_review_runs(
            cross_dir,
            dispositions=(
                DispositionEntry(
                    run_id="R2",
                    pr_number=2,
                    model="M",
                    finding_index=0,
                    disposition=DispositionLabel.FIXED,
                ),
            ),
        )


def test_corrupted_identity_without_outcome_counts_missing_outcome_runs(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    bad_dir = runs_dir / "bad-pr-no-outcome"
    bad_dir.mkdir(parents=True)
    (bad_dir / "target.json").write_text(json.dumps({"pr_number": -1}), encoding="utf-8")

    metrics = analyze_review_runs(runs_dir)
    assert metrics.total_runs == 1
    assert metrics.verdict_counts == {"CORRUPTED_IDENTITY": 1}
    assert metrics.missing_outcome_runs == 1
    assert metrics.corrupted_files == ("bad-pr-no-outcome/target.json",)


def test_validate_cases_rejects_non_blob_tree_path_and_strict_lf_blob_line_count(tmp_path: Path) -> None:
    # 1) 临时 Git 仓：目录 scripts 下有文件修改，将 bug_location 指向目录 "scripts" 必须被非 blob 校验拒绝
    repo = tmp_path / "tree-repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "tool.py").write_text("line1\n", encoding="utf-8")
    _git(repo, "add", "scripts/tool.py")
    _git(repo, "commit", "-qm", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    (scripts_dir / "tool.py").write_text("line1_mod\n", encoding="utf-8")
    _git(repo, "add", "scripts/tool.py")
    _git(repo, "commit", "-qm", "head")
    head_sha = _git(repo, "rev-parse", "HEAD")

    tree_case = EvalCase(
        case_id="bug-tree-dir",
        kind="bug",
        title="目录路径伪装缺陷位置",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="scripts", line_start=1, line_end=1, summary="s", category="c"),),
    )
    with pytest.raises(EvalValidationError, match="不是 Git blob 文件：scripts（实际类型：tree）"):
        validate_cases((tree_case,), repo_root=repo)

    # 2) 真实主仓案例 bug-2016-spec-revocation-regression 将 file 改为目录 "scripts", line 213 同样必须被拒绝
    if _is_full_git_checkout(REPO_ROOT):
        canonical = load_cases(CANONICAL_CASES)
        case_2016 = next(c for c in canonical if c.case_id == "bug-2016-spec-revocation-regression")
        tampered_2016 = EvalCase(
            case_id=case_2016.case_id,
            kind=case_2016.kind,
            title=case_2016.title,
            base_sha=case_2016.base_sha,
            head_sha=case_2016.head_sha,
            fix_sha=case_2016.fix_sha,
            bug_locations=(
                BugLocation(file="scripts", line_start=213, line_end=213, summary="s", category="c"),
            ),
        )
        with pytest.raises(EvalValidationError, match="不是 Git blob 文件：scripts（实际类型：tree）"):
            validate_cases((tampered_2016,), repo_root=REPO_ROOT)

    # 3) _git_blob_line_count 严格按 LF 计数（空文件、无尾换行、含孤立 CR / \x0b / \x0c / U+2028）
    (repo / "empty.txt").write_bytes(b"")
    (repo / "no_eol.txt").write_bytes(b"a\rb\x0bc\x0cd")
    (repo / "two_lines.txt").write_bytes("first\u2028inside\nsecond\rinline\n".encode())
    _git(repo, "add", "empty.txt", "no_eol.txt", "two_lines.txt")
    _git(repo, "commit", "-qm", "blobs")
    blob_sha = _git(repo, "rev-parse", "HEAD")
    assert _git_blob_line_count(repo, f"{blob_sha}:empty.txt") == 0
    assert _git_blob_line_count(repo, f"{blob_sha}:no_eol.txt") == 1
    assert _git_blob_line_count(repo, f"{blob_sha}:two_lines.txt") == 2


def test_unified_diff_and_git_diff_strict_lf_for_u2028_and_inline_cr(tmp_path: Path) -> None:
    # 1) 直接送 UTF-8 编码的 "first\u2028inside\nsecond\n" 到 git diff --no-index -U0 -- /dev/null -
    payload = "first\u2028inside\nsecond\n".encode()
    proc = subprocess.run(
        ["git", "diff", "--no-index", "-U0", "--", "/dev/null", "-"],
        input=payload,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 1
    assert _parse_unified_diff_added_ranges(proc.stdout.decode("utf-8", errors="replace")) == ((1, 2),)

    # 2) 临时 Git 仓真实提交包含 U+2028、行内孤立 \r 与其他非 LF 控制符，diff 与 blob 行数必须完全对齐 Git LF 行号
    repo = tmp_path / "lf-repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    (repo / "placeholder.txt").write_bytes(b"init\n")
    _git(repo, "add", "placeholder.txt")
    _git(repo, "commit", "-qm", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    (repo / "u2028.txt").write_bytes("first\u2028inside\nsecond\n".encode())
    (repo / "inline_cr.txt").write_bytes(b"alpha\rbeta\ngamma\x0b\x0c\xe2\x80\xa9delta\n")
    _git(repo, "add", "u2028.txt", "inline_cr.txt")
    _git(repo, "commit", "-qm", "head")
    head_sha = _git(repo, "rev-parse", "HEAD")

    assert _git_blob_line_count(repo, f"{head_sha}:u2028.txt") == 2
    assert _git_diff_added_ranges(repo, base_sha, head_sha, "u2028.txt") == ((1, 2),)
    assert _git_blob_line_count(repo, f"{head_sha}:inline_cr.txt") == 2
    assert _git_diff_added_ranges(repo, base_sha, head_sha, "inline_cr.txt") == ((1, 2),)

    valid_case = EvalCase(
        case_id="lf-valid",
        kind="bug",
        title="含 U+2028 与行内 CR 的两行文件",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(
            BugLocation(file="u2028.txt", line_start=1, line_end=2, summary="s1", category="c"),
            BugLocation(file="inline_cr.txt", line_start=1, line_end=2, summary="s2", category="c"),
        ),
    )
    validate_cases((valid_case,), repo_root=repo)

    out_of_bounds = EvalCase(
        case_id="lf-oob",
        kind="bug",
        title="第 3 行不存在",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="u2028.txt", line_start=3, line_end=3, summary="s", category="c"),),
    )
    with pytest.raises(EvalValidationError, match="行号越界：3 > 2"):
        validate_cases((out_of_bounds,), repo_root=repo)


def test_r6_severity_tag_and_body_heuristic_counterexamples(tmp_path: Path) -> None:
    # R6 三条核心反例在 receipt_result_status="blocked" 下均必须归为 blocking_substantive
    counterexamples = (
        "src/low:1 数据丢失",
        "[P2] 数据丢失，可选方案是先缓存",
        "这不是非阻断建议，必须修复",
    )
    for text in counterexamples:
        assert is_non_blocking_or_nit_finding(text, "blocked") is False, text
        assert classify_finding_heuristic(text, "blocked") == "blocking_substantive", text

    # 衍生边界：无扩展名路径/file:line、裸可选技术词、被否定的非阻断/不阻断/non-blocking
    assert _parse_leading_severity_tag("src/low:1 数据丢失") is None
    assert _parse_leading_severity_tag("low:12 数据丢失") is None
    assert _parse_leading_severity_tag("src/info:3 权限绕过") is None
    assert _parse_leading_severity_tag("[P2] 数据丢失，可选方案是先缓存") == "blocking"
    assert _parse_leading_severity_tag("P2: 数据丢失") == "blocking"
    assert _parse_leading_severity_tag("p2:1 数据丢失") is None
    assert _parse_leading_severity_tag("这不是非阻断：必须修复") is None

    for blocking_body in (
        "数据丢失，可选方案是先缓存",
        "可选路径绕过鉴权",
        "可选参数未校验导致崩溃",
        "并非不阻断，必须修复",
        "这不属于非阻断项，必须修复",
        "This is not non-blocking, must fix",
        "This is not a non-blocking issue",
    ):
        assert is_non_blocking_or_nit_finding(blocking_body, "blocked") is False, blocking_body
        assert classify_finding_heuristic(blocking_body, "blocked") == "blocking_substantive", blocking_body

    # 真实历史语料保持正确归类
    assert _parse_leading_severity_tag("[P2/非阻断] 可稍后清理") == "non_blocking"
    assert classify_finding_heuristic("[P2/非阻断] 可稍后清理", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("[Nit] formatting", "blocked") == "non_blocking_or_nit"
    assert (
        classify_finding_heuristic(
            "【nit】`.sandcastle/decision-claimer.mts:622` 的 close 回调新增了 `signal` 参数，但没有使用。",
            "blocked",
        )
        == "non_blocking_or_nit"
    )
    assert (
        classify_finding_heuristic(
            "[阻断] `.sandcastle/docs/maintenance-1742.md:193` 尚未满足发布条件，不是可选后续优化。",
            "blocked",
        )
        == "blocking_substantive"
    )
    assert classify_finding_heuristic("这是可选优化，可后续整理", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("这是可选后续建议", "blocked") == "non_blocking_or_nit"

    # 端到端 BLOCK 运行：3 条反例全部计入 subsequent_head_pass_total_block_findings，且后续不同 head PASS 时全部计入推定已修
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_run(
        runs_dir,
        "p901-r1-block",
        pr_number=901,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "run_id": "run-p901-r1-block",
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {
                    "status": "blocked",
                    "findings": [
                        *counterexamples,
                        "[P2/非阻断] 可稍后清理",
                    ],
                },
            }
        },
    )
    _write_run(
        runs_dir,
        "p901-r2-pass",
        pr_number=901,
        head_sha="b" * 40,
        registered_at_ns=200,
        attempt=2,
        verdict="PASS",
    )
    metrics = analyze_review_runs(runs_dir)
    assert metrics.corrupted_files == ()
    assert metrics.finding_heuristic_categories == {
        "blocking_substantive": 3,
        "non_blocking_or_nit": 1,
    }
    assert metrics.subsequent_head_pass_total_block_findings == 3
    assert metrics.subsequent_head_pass_inferred_fixed == 3
    assert metrics.subsequent_head_pass_undeterminable_findings == 0


def test_duplicate_receipt_key_excluded_from_subsequent_head_pass_metrics(tmp_path: Path) -> None:
    # 1) R6 最小反例：同目录 X/Y 双回执均声明 model="M" + outcome BLOCK + 后续不同 head PASS
    same_dir_runs = tmp_path / "same-dir-block-then-pass"
    run_dup = same_dir_runs / "run-1-block"
    run_dup.mkdir(parents=True)
    (run_dup / "target.json").write_text(
        json.dumps({"run_id": "R", "pr_number": 1, "head_sha": "a" * 40, "registered_at_ns": 10, "attempt": 1}),
        encoding="utf-8",
    )
    (run_dup / "outcome.json").write_text(json.dumps({"verdict": "BLOCK"}), encoding="utf-8")
    for sub_name, finding_text in (("X", "[阻断] 重复键发现 X"), ("Y", "[阻断] 重复键发现 Y")):
        sub = run_dup / sub_name
        sub.mkdir()
        (sub / "receipt.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "model": "M",
                    "result": {"status": "blocked", "findings": [finding_text]},
                }
            ),
            encoding="utf-8",
        )
    _write_run(
        same_dir_runs,
        "run-2-pass",
        pr_number=1,
        head_sha="b" * 40,
        registered_at_ns=20,
        attempt=2,
        verdict="PASS",
    )

    same_metrics = analyze_review_runs(same_dir_runs)
    assert same_metrics.corrupted_files == (
        "run-1-block/X/receipt.json",
        "run-1-block/Y/receipt.json",
    )
    assert same_metrics.total_receipts == 2
    assert same_metrics.total_findings == 2
    assert same_metrics.subsequent_head_pass_total_block_findings == 0
    assert same_metrics.subsequent_head_pass_inferred_fixed == 0
    assert same_metrics.subsequent_head_pass_undeterminable_findings == 0
    with pytest.raises(EvalValidationError, match="重复回执键"):
        analyze_review_runs(
            same_dir_runs,
            dispositions=(
                DispositionEntry(
                    run_id="R",
                    pr_number=1,
                    model="M",
                    finding_index=0,
                    disposition=DispositionLabel.FIXED,
                ),
            ),
        )

    # 2) 跨目录重复键 (R2, M)（含可排序 BLOCK、不可排序 BLOCK、后续不同 head PASS，以及同目录非歧义模型 M2）
    cross_dir_runs = tmp_path / "cross-dir-block-then-pass"
    d1 = cross_dir_runs / "dir-1-block"
    (d1 / "M").mkdir(parents=True)
    (d1 / "M2").mkdir(parents=True)
    (d1 / "target.json").write_text(
        json.dumps({"run_id": "R2", "pr_number": 2, "head_sha": "c" * 40, "registered_at_ns": 10, "attempt": 1}),
        encoding="utf-8",
    )
    (d1 / "outcome.json").write_text(json.dumps({"verdict": "BLOCK"}), encoding="utf-8")
    (d1 / "M" / "receipt.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "model": "M",
                "result": {"status": "blocked", "findings": ["[阻断] 跨目录重复 M-1"]},
            }
        ),
        encoding="utf-8",
    )
    (d1 / "M2" / "receipt.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "model": "M2",
                "result": {"status": "blocked", "findings": ["[阻断] 非歧义模型 M2"]},
            }
        ),
        encoding="utf-8",
    )

    # dir-2 无时间戳（不可排序 BLOCK），同样声明 (R2, M)，不得计入 undeterminable_block_findings
    d2 = cross_dir_runs / "dir-2-unorderable-block"
    (d2 / "M").mkdir(parents=True)
    (d2 / "target.json").write_text(
        json.dumps({"run_id": "R2", "pr_number": 2, "head_sha": "c" * 40}),
        encoding="utf-8",
    )
    (d2 / "outcome.json").write_text(json.dumps({"verdict": "BLOCK"}), encoding="utf-8")
    (d2 / "M" / "receipt.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "model": "M",
                "result": {"status": "blocked", "findings": ["[阻断] 跨目录重复 M-2"]},
            }
        ),
        encoding="utf-8",
    )
    _write_run(
        cross_dir_runs,
        "dir-3-pass",
        pr_number=2,
        head_sha="d" * 40,
        registered_at_ns=20,
        attempt=2,
        verdict="PASS",
    )

    cross_metrics = analyze_review_runs(cross_dir_runs)
    assert cross_metrics.corrupted_files == (
        "dir-1-block/M/receipt.json",
        "dir-2-unorderable-block/M/receipt.json",
    )
    assert cross_metrics.total_receipts == 3
    assert cross_metrics.total_findings == 3
    # 仅非歧义的 M2（1 条）进入可判定分母与推定已修分子；重复键 (R2, M) 两条均不进入分母/分子/不可判定
    assert cross_metrics.subsequent_head_pass_total_block_findings == 1
    assert cross_metrics.subsequent_head_pass_inferred_fixed == 1
    assert cross_metrics.subsequent_head_pass_undeterminable_findings == 0
    with pytest.raises(EvalValidationError, match="重复回执键"):
        analyze_review_runs(
            cross_dir_runs,
            dispositions=(
                DispositionEntry(
                    run_id="R2",
                    pr_number=2,
                    model="M",
                    finding_index=0,
                    disposition=DispositionLabel.FIXED,
                ),
            ),
        )


def test_r7_pure_rename_and_modified_rename_diff_validation(tmp_path: Path) -> None:
    repo = tmp_path / "rename-repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")

    # 1) R100 纯重命名：零内容改动，绝不能被当成整文件新增
    (repo / "old_pure.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    # 2) R<100 重命名伴修改：10 行中仅改第 6 行，相似度 ~90%
    base_lines = [f"line_{i:02d}_payload_content" for i in range(1, 11)]
    (repo / "old_mod.py").write_text("\n".join(base_lines) + "\n", encoding="utf-8")
    _git(repo, "add", "old_pure.py", "old_mod.py")
    _git(repo, "commit", "-qm", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    _git(repo, "mv", "old_pure.py", "new_pure.py")
    _git(repo, "mv", "old_mod.py", "new_mod.py")
    mod_lines = list(base_lines)
    mod_lines[5] = "line_06_modified_bug_here"
    (repo / "new_mod.py").write_text("\n".join(mod_lines) + "\n", encoding="utf-8")
    _git(repo, "add", "new_mod.py")
    _git(repo, "commit", "-qm", "rename-pure-and-modified")
    head_sha = _git(repo, "rev-parse", "HEAD")

    status_map = _git_diff_tree_status_map(repo, base_sha, head_sha)
    assert status_map["new_pure.py"] == ("R100", "old_pure.py")
    mod_status, mod_old = status_map["new_mod.py"]
    assert mod_status.startswith("R") and mod_status != "R100"
    assert mod_old == "old_mod.py"

    assert _git_diff_added_ranges(repo, base_sha, head_sha, "new_pure.py") == ()
    assert _git_diff_added_ranges(repo, base_sha, head_sha, "new_mod.py") == ((6, 6),)

    pure_rename_case = EvalCase(
        case_id="pure-rename-line1",
        kind="bug",
        title="R100 纯重命名文件第 1 行必须被拒",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="new_pure.py", line_start=1, line_end=1, summary="s", category="c"),),
    )
    with pytest.raises(EvalValidationError, match="diff hunk"):
        validate_cases((pure_rename_case,), repo_root=repo)

    mod_rename_valid = EvalCase(
        case_id="mod-rename-changed-line",
        kind="bug",
        title="R<100 仅真实修改行通过",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="new_mod.py", line_start=6, line_end=6, summary="s", category="c"),),
    )
    validate_cases((mod_rename_valid,), repo_root=repo)

    mod_rename_untouched = EvalCase(
        case_id="mod-rename-untouched-line",
        kind="bug",
        title="R<100 未改动行必须被拒",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="new_mod.py", line_start=1, line_end=1, summary="s", category="c"),),
    )
    with pytest.raises(EvalValidationError, match="diff hunk"):
        validate_cases((mod_rename_untouched,), repo_root=repo)

    # 3) 真实主仓回归：提交 289fd82f6e9efc684704c79716e31483dbf3fa5e 纯重命名 .sandcastle/claude-route.mts
    real_head = "289fd82f6e9efc684704c79716e31483dbf3fa5e"
    if _is_full_git_checkout(REPO_ROOT):
        has_head = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{real_head}^{{commit}}"],
            capture_output=True,
            check=False,
        )
        parent_proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", f"{real_head}^"],
            capture_output=True,
            text=True,
            check=False,
        )
        if has_head.returncode == 0 and parent_proc.returncode == 0:
            real_base = parent_proc.stdout.strip()
            assert _git_diff_added_ranges(REPO_ROOT, real_base, real_head, ".sandcastle/claude-route.mts") == ()
            real_pure_rename = EvalCase(
                case_id="real-289fd82f-pure-rename",
                kind="bug",
                title="真实 R100 纯重命名文件第 1 行必须被拒",
                base_sha=real_base,
                head_sha=real_head,
                bug_locations=(
                    BugLocation(
                        file=".sandcastle/claude-route.mts",
                        line_start=1,
                        line_end=1,
                        summary="s",
                        category="c",
                    ),
                ),
            )
            with pytest.raises(EvalValidationError, match="diff hunk"):
                validate_cases((real_pure_rename,), repo_root=REPO_ROOT)


def test_r7_markdown_link_and_path_brackets_not_misclassified_as_nit(tmp_path: Path) -> None:
    assert classify_finding_heuristic("[P1] [src/low:1](src/low#L1) 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[src/low:1](src/low#L1) 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[P1] [src/low] 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[P2/非阻断] 说明", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("[P2] [非阻断] 说明", "blocked") == "non_blocking_or_nit"

    # 额外边界：路径/文件坐标方括号与后续非显式降级方括号绝不将阻断降为 Nit
    assert _parse_leading_severity_tag("[P1] [src/low:1](src/low#L1) 数据丢失") == "blocking"
    assert _parse_leading_severity_tag("[src/low:1](src/low#L1) 数据丢失") is None
    assert _parse_leading_severity_tag("[P1] [src/low] 数据丢失") == "blocking"
    assert _parse_leading_severity_tag("[pilot1742/a.py] 路径越权") is None
    assert _parse_leading_severity_tag("[P1] [low] 指标错误") == "blocking"
    assert _parse_leading_severity_tag("[P1] [info] 权限泄露") == "blocking"
    assert _parse_leading_severity_tag("[P2] [nit] 命名建议") == "non_blocking"
    assert _parse_leading_severity_tag("[P2] [non-blocking] 可后续优化") == "non_blocking"
    assert _parse_leading_severity_tag("[低，非阻断] 可忽略") == "non_blocking"
    assert _parse_leading_severity_tag("[非阻断/低] 可忽略") == "non_blocking"

    # 端到端验证：[P1] [src/low:1](src/low#L1) 数据丢失在 BLOCK 运行中正确计入 subsequent_head_pass_total_block_findings
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_run(
        runs_dir,
        "p971-r1-block",
        pr_number=971,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "run_id": "run-p971-r1-block",
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {
                    "status": "blocked",
                    "findings": [
                        "[P1] [src/low:1](src/low#L1) 数据丢失",
                        "[P2] [非阻断] 说明",
                    ],
                },
            }
        },
    )
    _write_run(
        runs_dir,
        "p971-r2-pass",
        pr_number=971,
        head_sha="b" * 40,
        registered_at_ns=200,
        attempt=2,
        verdict="PASS",
    )
    metrics = analyze_review_runs(runs_dir)
    assert metrics.finding_heuristic_categories == {
        "blocking_substantive": 1,
        "non_blocking_or_nit": 1,
    }
    assert metrics.subsequent_head_pass_total_block_findings == 1
    assert metrics.subsequent_head_pass_inferred_fixed == 1
    assert metrics.subsequent_head_pass_undeterminable_findings == 0


def test_r7_load_dispositions_preserves_u2028_u2029_and_crlf(tmp_path: Path) -> None:
    disp_path = tmp_path / "dispositions_u2028.jsonl"
    row_u2028 = {
        "run_id": "r",
        "model": "m",
        "finding_index": 0,
        "pr_number": 1,
        "disposition": "fixed",
        "note": "a\u2028b",
    }
    row_u2029_crlf = {
        "run_id": "r",
        "model": "m",
        "finding_index": 1,
        "pr_number": 1,
        "disposition": "not_important",
        "note": "c\u2029d\x85e",
    }
    content = (
        json.dumps(row_u2028, ensure_ascii=False)
        + "\n"
        + json.dumps(row_u2029_crlf, ensure_ascii=False)
        + "\r\n"
    )
    disp_path.write_bytes(content.encode("utf-8"))

    entries = load_dispositions(disp_path)
    assert len(entries) == 2
    assert entries[0].disposition is DispositionLabel.FIXED
    assert entries[0].note == "a\u2028b"
    assert entries[1].disposition is DispositionLabel.NOT_IMPORTANT
    assert entries[1].note == "c\u2029d\x85e"


def test_r9_r100_reordered_rename_and_identical_rename_diff(tmp_path: Path) -> None:
    repo = tmp_path / "r100-reorder-repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")

    (repo / "old_reordered.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (repo / "old_identical.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    _git(repo, "add", "old_reordered.txt", "old_identical.txt")
    _git(repo, "commit", "-qm", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    _git(repo, "mv", "old_reordered.txt", "new_reordered.txt")
    (repo / "new_reordered.txt").write_text("gamma\nbeta\nalpha\n", encoding="utf-8")
    _git(repo, "mv", "old_identical.txt", "new_identical.txt")
    _git(repo, "add", "new_reordered.txt", "new_identical.txt")
    _git(repo, "commit", "-qm", "rename-r100-reordered-and-identical")
    head_sha = _git(repo, "rev-parse", "HEAD")

    status_map = _git_diff_tree_status_map(repo, base_sha, head_sha)
    assert status_map["new_reordered.txt"] == ("R100", "old_reordered.txt")
    assert status_map["new_identical.txt"] == ("R100", "old_identical.txt")

    # R100 重排行顺序：blob diff 必须返回真实新增/重排的 + 行（第 2..3 行），而非 ()
    assert _git_diff_added_ranges(repo, base_sha, head_sha, "new_reordered.txt") == ((2, 3),)
    # R100 内容字节完全相同：blob diff 自然为空，返回 ()
    assert _git_diff_added_ranges(repo, base_sha, head_sha, "new_identical.txt") == ()

    valid_reordered = EvalCase(
        case_id="r100-reordered-valid",
        kind="bug",
        title="R100 重排行真实改动行通过",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="new_reordered.txt", line_start=2, line_end=3, summary="s", category="c"),),
    )
    validate_cases((valid_reordered,), repo_root=repo)

    unchanged_reordered = EvalCase(
        case_id="r100-reordered-line1",
        kind="bug",
        title="R100 重排行未改动行被拒",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="new_reordered.txt", line_start=1, line_end=1, summary="s", category="c"),),
    )
    with pytest.raises(EvalValidationError, match="diff hunk"):
        validate_cases((unchanged_reordered,), repo_root=repo)

    identical_case = EvalCase(
        case_id="r100-identical-line1",
        kind="bug",
        title="R100 纯内容相同重命名被拒",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="new_identical.txt", line_start=1, line_end=1, summary="s", category="c"),),
    )
    with pytest.raises(EvalValidationError, match="diff hunk"):
        validate_cases((identical_case,), repo_root=repo)

    # 真实主仓 289fd82f6e9efc684704c79716e31483dbf3fa5e 纯内容相同的 R100 仍返回 ()
    real_head = "289fd82f6e9efc684704c79716e31483dbf3fa5e"
    if _is_full_git_checkout(REPO_ROOT):
        has_head = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{real_head}^{{commit}}"],
            capture_output=True,
            check=False,
        )
        parent_proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", f"{real_head}^"],
            capture_output=True,
            text=True,
            check=False,
        )
        if has_head.returncode == 0 and parent_proc.returncode == 0:
            real_base = parent_proc.stdout.strip()
            assert _git_diff_added_ranges(REPO_ROOT, real_base, real_head, ".sandcastle/claude-route.mts") == ()


def test_r9_literal_pathspec_glob_filename_isolation(tmp_path: Path) -> None:
    repo = tmp_path / "glob-pathspec-repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")

    (repo / "[id].ts").write_text("l1\nl2\n", encoding="utf-8")
    (repo / "i.ts").write_text("a1\na2\n", encoding="utf-8")
    (repo / "a*b.ts").write_text("x1\nx2\n", encoding="utf-8")
    (repo / "axb.ts").write_text("y1\ny2\n", encoding="utf-8")
    _git(repo, "add", "--", "[id].ts", "i.ts", "a*b.ts", "axb.ts")
    _git(repo, "commit", "-qm", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    # [id].ts 只改第 2 行，i.ts 只改第 1 行；a*b.ts 只改第 2 行，axb.ts 只改第 1 行
    (repo / "[id].ts").write_text("l1\nl2_changed\n", encoding="utf-8")
    (repo / "i.ts").write_text("a1_changed\na2\n", encoding="utf-8")
    (repo / "a*b.ts").write_text("x1\nx2_changed\n", encoding="utf-8")
    (repo / "axb.ts").write_text("y1_changed\ny2\n", encoding="utf-8")
    _git(repo, "add", "--", "[id].ts", "i.ts", "a*b.ts", "axb.ts")
    _git(repo, "commit", "-qm", "modify-glob-named-files")
    head_sha = _git(repo, "rev-parse", "HEAD")

    assert _git_diff_added_ranges(repo, base_sha, head_sha, "[id].ts") == ((2, 2),)
    assert _git_diff_added_ranges(repo, base_sha, head_sha, "i.ts") == ((1, 1),)
    assert _git_diff_added_ranges(repo, base_sha, head_sha, "a*b.ts") == ((2, 2),)
    assert _git_diff_added_ranges(repo, base_sha, head_sha, "axb.ts") == ((1, 1),)

    bad_case = EvalCase(
        case_id="glob-bracket-line1-rejected",
        kind="bug",
        title="[id].ts:1..1 不得借用 i.ts 的第 1 行改动",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="[id].ts", line_start=1, line_end=1, summary="s", category="c"),),
    )
    with pytest.raises(EvalValidationError, match="未完全落在.*可用 hunk：2\\.\\.2"):
        validate_cases((bad_case,), repo_root=repo)

    good_case = EvalCase(
        case_id="glob-bracket-line2-accepted",
        kind="bug",
        title="[id].ts:2..2 精确命中自身改动",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="[id].ts", line_start=2, line_end=2, summary="s", category="c"),),
    )
    validate_cases((good_case,), repo_root=repo)


def test_r9_markdown_reference_links_not_misclassified_as_nit(tmp_path: Path) -> None:
    full_ref_finding = "[P1] [nit][location] 数据丢失\n\n[location]: src/nit#L1"
    collapsed_ref_finding = "[P1] [nit][] 数据丢失\n\n[nit]: src/nit#L1"
    shortcut_ref_finding = "[P1] [nit] 数据丢失\n\n[nit]: src/nit#L1"

    assert classify_finding_heuristic(full_ref_finding, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(collapsed_ref_finding, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(shortcut_ref_finding, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[P2] [非阻断] 说明", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("[P2][非阻断] 说明", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("[P2/非阻断] 说明", "blocked") == "non_blocking_or_nit"

    # 额外边界：标签归一化（大小写/空白折叠）、无定义引用链接、定义覆盖合法严重度词、首行 [P1]: 与真实语料 [P2][Spec]/[非阻断][规范]
    assert _parse_leading_severity_tag(full_ref_finding) == "blocking"
    assert _parse_leading_severity_tag(collapsed_ref_finding) == "blocking"
    assert _parse_leading_severity_tag(shortcut_ref_finding) == "blocking"
    assert _parse_leading_severity_tag("[P1] [nit][location] 数据丢失") == "blocking"
    assert _parse_leading_severity_tag("[P1] [nit][src/low:1] 数据丢失") == "blocking"
    assert _parse_leading_severity_tag("[P1] [nit][P2] 数据丢失\n\n[P2]: src/nit#L1") == "blocking"
    assert _parse_leading_severity_tag("[P1] [nit] 数据丢失\n\n  [  NIT  ]: src/nit#L1") == "blocking"
    assert _parse_leading_severity_tag("[P1]: 越权漏洞 需要修复") == "blocking"
    assert _parse_leading_severity_tag("[P1]: 越权漏洞") is None
    assert _parse_leading_severity_tag("[P2][Spec] 存在空指针，可顺手清理注释") == "blocking"
    assert _parse_leading_severity_tag("[非阻断][规范] 本 PR 的提交标题未遵循格式") == "non_blocking"
    assert _parse_leading_severity_tag("[P2][非阻断] 说明") == "non_blocking"

    # 端到端验证：[P1] [nit][location] 数据丢失\n\n[location]: src/nit#L1 在 BLOCK 运行中正确计入 subsequent_head_pass_total_block_findings
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_run(
        runs_dir,
        "p991-r1-block",
        pr_number=991,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "run_id": "run-p991-r1-block",
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {
                    "status": "blocked",
                    "findings": [
                        full_ref_finding,
                        "[P2][非阻断] 说明",
                    ],
                },
            }
        },
    )
    _write_run(
        runs_dir,
        "p991-r2-pass",
        pr_number=991,
        head_sha="b" * 40,
        registered_at_ns=200,
        attempt=2,
        verdict="PASS",
    )
    metrics = analyze_review_runs(runs_dir)
    assert metrics.finding_heuristic_categories == {
        "blocking_substantive": 1,
        "non_blocking_or_nit": 1,
    }
    assert metrics.subsequent_head_pass_total_block_findings == 1
    assert metrics.subsequent_head_pass_inferred_fixed == 1
    assert metrics.subsequent_head_pass_undeterminable_findings == 0


def test_r10_commonmark_block_aware_link_ref_defs(tmp_path: Path) -> None:
    # 1) 双向核心反例：引用块/列表内有效定义被准确提取，围栏/缩进/HTML 块内假定义被忽略
    bq_def = "[P1] [nit] 数据丢失\n\n> [nit]: src/nit#L1"
    list_def = "[P1] [nit] 数据丢失\n\n- [nit]: src/nit#L1"
    nested_bq_def = "[P1] [nit] 数据丢失\n\n> > [nit]: /x"
    ordered_list_def = "[P1] [nit] 数据丢失\n\n1. [nit]: src/nit#L1"
    bq_list_def = "[P1] [nit] 数据丢失\n\n> - [nit]: src/nit#L1"
    tilde_fence_fake = "[P2] [非阻断] 说明\n\n~~~markdown\n[非阻断]: 示例\n~~~"
    backtick_fence_fake = "[P2] [非阻断] 说明\n\n```markdown\n[非阻断]: 示例\n```"
    indented_code_fake = "[P2] [非阻断] 说明\n\n    [非阻断]: /demo"
    tab_indented_fake = "[P2] [非阻断] 说明\n\n\t[非阻断]: /demo"
    html_comment_fake = "[P2] [非阻断] 说明\n\n<!--\n[非阻断]: /demo\n-->"
    bq_fence_fake = "[P2] [非阻断] 说明\n\n> ```markdown\n> [非阻断]: 示例\n> ```"

    assert classify_finding_heuristic(bq_def, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(list_def, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(nested_bq_def, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(ordered_list_def, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(bq_list_def, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(tilde_fence_fake, "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic(backtick_fence_fake, "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic(indented_code_fake, "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic(tab_indented_fake, "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic(html_comment_fake, "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic(bq_fence_fake, "blocked") == "non_blocking_or_nit"

    # 2) CommonMark §4.7 段落边界、连续定义、标题回退与首行中文冒号说明豁免
    # 段落中间行不能打断段落，不构成链接引用定义
    assert classify_finding_heuristic("[P2] [非阻断] 说明\n[非阻断]: /demo", "blocked") == "non_blocking_or_nit"
    # 与目标同行的标题后有尾随非空白 -> 非法定义
    assert (
        classify_finding_heuristic('[P2] [非阻断] 说明\n\n[非阻断]: /demo "title" trailing', "blocked")
        == "non_blocking_or_nit"
    )
    # 跨行标题后有尾随非空白 -> 回退无标题仍为有效定义
    assert (
        classify_finding_heuristic('[P1] [nit] 数据丢失\n\n[nit]: /demo\n"title" trailing', "blocked")
        == "blocking_substantive"
    )
    # 同段落连续多条定义 + 尖括号目标 + 括号平衡目标
    assert (
        classify_finding_heuristic(
            "[P1] [nit] 数据丢失\n\n[a]: /foo(bar)/baz\n[nit]: <src/nit with space#L1>",
            "blocked",
        )
        == "blocking_substantive"
    )
    # 纯 CommonMark §4.7：单 token `[P1]: 阻断说明` 属于合法链接引用定义；多词正文行不是链接定义
    assert _extract_markdown_link_ref_defs("[P1]: 阻断说明") == {"p1": (0,)}
    assert _extract_markdown_link_ref_defs("[P1]: 阻断说明 需要修复") == {}
    assert classify_finding_heuristic("[P1]: 阻断说明", "blocked") == "blocking_substantive"
    assert _extract_markdown_link_ref_defs("[nit]: src/nit#L1\n\n[P1] [nit] 数据丢失") == {"nit": (0,)}
    # 制表位与行尾 CRLF/CR 兼容（不把 U+2028 当换行）
    assert classify_finding_heuristic("[P1] [nit] 数据丢失\r\n\r\n>\t[nit]: /x\r\n", "blocked") == "blocking_substantive"
    assert (
        classify_finding_heuristic("[P2] [非阻断] 说明\r\n\r\n>\t\t[非阻断]: /x\r\n", "blocked")
        == "non_blocking_or_nit"
    )
    assert (
        classify_finding_heuristic("[P2] [非阻断] 说明\u2028[非阻断]: /demo", "blocked")
        == "non_blocking_or_nit"
    )

    # 3) 端到端验证两个方向在 subsequent_head_pass_total_block_findings 分母中均正确计入/排除
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_run(
        runs_dir,
        "p1010-r1-block",
        pr_number=1010,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "run_id": "run-p1010-r1-block",
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {
                    "status": "blocked",
                    "findings": [
                        bq_def,
                        list_def,
                        tilde_fence_fake,
                        backtick_fence_fake,
                        indented_code_fake,
                    ],
                },
            }
        },
    )
    _write_run(
        runs_dir,
        "p1010-r2-pass",
        pr_number=1010,
        head_sha="b" * 40,
        registered_at_ns=200,
        attempt=2,
        verdict="PASS",
    )
    metrics = analyze_review_runs(runs_dir)
    assert metrics.corrupted_files == ()
    assert metrics.finding_heuristic_categories == {
        "blocking_substantive": 2,
        "non_blocking_or_nit": 3,
    }
    assert metrics.subsequent_head_pass_total_block_findings == 2
    assert metrics.subsequent_head_pass_inferred_fixed == 2
    assert metrics.subsequent_head_pass_undeterminable_findings == 0


def test_r10_compare_scores_tracks_matched_location_index_sets_and_validates_json(tmp_path: Path) -> None:
    # 1) 复现 Codex R9 最小反例：直接取仓内 bug-1978-segment-seed-scan-revert
    canonical = load_cases(CANONICAL_CASES)
    case_1978 = next(c for c in canonical if c.case_id == "bug-1978-segment-seed-scan-revert")
    assert len(case_1978.bug_locations) == 2

    before_1978 = score_predictions(
        (case_1978,),
        (
            CasePrediction(
                case_id=case_1978.case_id,
                verdict="BLOCK",
                findings=(
                    PredictedFinding(
                        file="rust/src/theta_v0/parser/segment.rs",
                        line_start=538,
                        line_end=538,
                        severity="blocking",
                    ),
                ),
            ),
        ),
    )
    after_1978 = score_predictions(
        (case_1978,),
        (
            CasePrediction(
                case_id=case_1978.case_id,
                verdict="BLOCK",
                findings=(
                    PredictedFinding(
                        file="rust/src/theta_v0/parser/segment.rs",
                        line_start=1176,
                        line_end=1176,
                        severity="blocking",
                    ),
                ),
            ),
        ),
    )
    assert before_1978.case_details[0].matched_location_indices == (0,)
    assert after_1978.case_details[0].matched_location_indices == (1,)

    cmp_1978 = compare_scores(before_1978, after_1978)
    assert cmp_1978.bug_case_recall_delta == 0.0
    assert cmp_1978.bug_location_recall_delta == 0.0
    assert cmp_1978.mixed_cases == ("bug-1978-segment-seed-scan-revert",)
    assert cmp_1978.unchanged_cases == ()
    assert cmp_1978.improved_cases == ()
    assert cmp_1978.regressed_cases == ()

    # 2) JSON 往返 compare CLI 保持一致
    before_json = tmp_path / "before_1978.json"
    after_json = tmp_path / "after_1978.json"
    out_json = tmp_path / "cmp_1978.json"
    before_json.write_text(json.dumps(before_1978.to_dict()), encoding="utf-8")
    after_json.write_text(json.dumps(after_1978.to_dict()), encoding="utf-8")
    assert main(["compare", "--before", str(before_json), "--after", str(after_json), "--out-json", str(out_json)]) == 0
    cli_cmp = json.loads(out_json.read_text(encoding="utf-8"))
    assert cli_cmp["bug_case_recall_delta"] == 0.0
    assert cli_cmp["bug_location_recall_delta"] == 0.0
    assert cli_cmp["mixed_cases"] == ["bug-1978-segment-seed-scan-revert"]
    assert cli_cmp["unchanged_cases"] == []

    # 3) 集合演变边界：{0}->{0,1} improved，{0,1}->{1} regressed，{0}->{1,2} mixed，{0,1}->{0,1} unchanged
    three_loc_case = (
        EvalCase(
            case_id="bug-three-locs",
            kind="bug",
            title="三缺陷位置集合演变",
            base_sha=SHA_1,
            head_sha=SHA_2,
            bug_locations=(
                BugLocation(file="a.py", line_start=10, line_end=10, summary="l0", category="bug"),
                BugLocation(file="b.py", line_start=20, line_end=20, summary="l1", category="bug"),
                BugLocation(file="c.py", line_start=30, line_end=30, summary="l2", category="bug"),
            ),
        ),
    )

    def _score_locs(*loc_coords: tuple[str, int]) -> tuple[EvalScore, tuple[int, ...]]:
        score = score_predictions(
            three_loc_case,
            (
                CasePrediction(
                    case_id="bug-three-locs",
                    verdict="BLOCK",
                    findings=tuple(
                        PredictedFinding(file=f, line_start=ln, line_end=ln, severity="blocking")
                        for f, ln in loc_coords
                    ),
                ),
            ),
        )
        return (score, score.case_details[0].matched_location_indices)

    s_0, idx_0 = _score_locs(("a.py", 10))
    s_01, idx_01 = _score_locs(("a.py", 10), ("b.py", 20))
    s_1, idx_1 = _score_locs(("b.py", 20))
    s_12, idx_12 = _score_locs(("b.py", 20), ("c.py", 30))
    assert idx_0 == (0,)
    assert idx_01 == (0, 1)
    assert idx_1 == (1,)
    assert idx_12 == (1, 2)

    assert compare_scores(s_0, s_01).improved_cases == ("bug-three-locs",)
    assert compare_scores(s_01, s_1).regressed_cases == ("bug-three-locs",)
    assert compare_scores(s_0, s_12).mixed_cases == ("bug-three-locs",)
    assert compare_scores(s_01, s_01).unchanged_cases == ("bug-three-locs",)

    # 4) _score_from_dict 反序列化严格校验 matched_location_indices（重复/长度不符/负数/布尔/越界一律拒绝）
    base_dict = before_1978.to_dict()

    bad_dup = json.loads(json.dumps(base_dict))
    bad_dup["case_details"][0]["matched_locations"] = 2
    bad_dup["case_details"][0]["matched_location_indices"] = [0, 0]
    with pytest.raises(EvalValidationError, match="重复索引"):
        _score_from_dict(bad_dup)

    bad_len = json.loads(json.dumps(base_dict))
    bad_len["case_details"][0]["matched_locations"] = 1
    bad_len["case_details"][0]["matched_location_indices"] = [0, 1]
    with pytest.raises(EvalValidationError, match="长度.*不一致"):
        _score_from_dict(bad_len)

    bad_neg = json.loads(json.dumps(base_dict))
    bad_neg["case_details"][0]["matched_locations"] = 1
    bad_neg["case_details"][0]["matched_location_indices"] = [-1]
    with pytest.raises(EvalValidationError, match="不能为负"):
        _score_from_dict(bad_neg)

    bad_bool = json.loads(json.dumps(base_dict))
    bad_bool["case_details"][0]["matched_locations"] = 1
    bad_bool["case_details"][0]["matched_location_indices"] = [True]
    with pytest.raises(EvalValidationError, match="必须是整数"):
        _score_from_dict(bad_bool)

    bad_oob = json.loads(json.dumps(base_dict))
    bad_oob["case_details"][0]["matched_locations"] = 1
    bad_oob["case_details"][0]["matched_location_indices"] = [2]
    with pytest.raises(EvalValidationError, match="超出 expected_locations"):
        _score_from_dict(bad_oob)


def test_r11_bipartite_matching_permutation_invariant_lex_min() -> None:
    # 1) R10 Important 1 核心反例：真值位置 30, 10, 50（索引 0, 1, 2），发现第 20, 40 行（容差 15）
    # 无论发现按 (20, 40) 还是 (40, 20) 输入，按横截拟阵升序增广必然唯一命中 (0, 1)
    three_loc_case = (
        EvalCase(
            case_id="bug-matroid-order-invariance",
            kind="bug",
            title="等价最大匹配必须与发现输入顺序完全无关",
            base_sha=SHA_1,
            head_sha=SHA_2,
            bug_locations=(
                BugLocation(file="a.py", line_start=30, line_end=30, summary="l0", category="bug"),
                BugLocation(file="a.py", line_start=10, line_end=10, summary="l1", category="bug"),
                BugLocation(file="a.py", line_start=50, line_end=50, summary="l2", category="bug"),
            ),
        ),
    )
    f20 = PredictedFinding(file="a.py", line_start=20, line_end=20, severity="blocking", summary="f20")
    f40 = PredictedFinding(file="a.py", line_start=40, line_end=40, severity="blocking", summary="f40")

    score_20_40 = score_predictions(
        three_loc_case,
        (CasePrediction(case_id="bug-matroid-order-invariance", verdict="BLOCK", findings=(f20, f40)),),
    )
    score_40_20 = score_predictions(
        three_loc_case,
        (CasePrediction(case_id="bug-matroid-order-invariance", verdict="BLOCK", findings=(f40, f20)),),
    )
    assert score_20_40.case_details[0].matched_location_indices == (0, 1)
    assert score_40_20.case_details[0].matched_location_indices == (0, 1)
    assert score_20_40.case_details[0].matched_blocking_findings == 2
    assert score_40_20.case_details[0].matched_blocking_findings == 2

    cmp_perm = compare_scores(score_20_40, score_40_20)
    assert cmp_perm.unchanged_cases == ("bug-matroid-order-invariance",)
    assert cmp_perm.mixed_cases == ()
    assert cmp_perm.improved_cases == ()
    assert cmp_perm.regressed_cases == ()

    # 2) 多位置多发现全排列不变性（4! = 24 种输入排列全部产出唯一最小字典序匹配）
    five_loc_case = (
        EvalCase(
            case_id="bug-matroid-all-perms",
            kind="bug",
            title="四发现全排列不变性验证",
            base_sha=SHA_1,
            head_sha=SHA_2,
            bug_locations=(
                BugLocation(file="m.py", line_start=30, line_end=30, summary="l0", category="bug"),
                BugLocation(file="m.py", line_start=10, line_end=10, summary="l1", category="bug"),
                BugLocation(file="m.py", line_start=50, line_end=50, summary="l2", category="bug"),
                BugLocation(file="m.py", line_start=70, line_end=70, summary="l3", category="bug"),
                BugLocation(file="m.py", line_start=90, line_end=90, summary="l4", category="bug"),
            ),
        ),
    )
    findings_pool = (
        PredictedFinding(file="m.py", line_start=20, line_end=20, severity="blocking", summary="a"),
        PredictedFinding(file="m.py", line_start=40, line_end=40, severity="blocking", summary="b"),
        PredictedFinding(file="m.py", line_start=80, line_end=80, severity="blocking", summary="c"),
        PredictedFinding(file="m.py", line_start=20, line_end=20, severity="important", summary="dup-a"),
    )
    baseline_score = score_predictions(
        five_loc_case,
        (CasePrediction(case_id="bug-matroid-all-perms", verdict="BLOCK", findings=findings_pool),),
    )
    assert baseline_score.case_details[0].matched_location_indices == (0, 1, 3)
    for perm in itertools.permutations(findings_pool):
        perm_score = score_predictions(
            five_loc_case,
            (CasePrediction(case_id="bug-matroid-all-perms", verdict="BLOCK", findings=perm),),
        )
        assert perm_score.case_details[0].matched_location_indices == (0, 1, 3)
        assert perm_score.case_details[0].matched_blocking_findings == 3
        cmp_p = compare_scores(baseline_score, perm_score)
        assert cmp_p.unchanged_cases == ("bug-matroid-all-perms",)
        assert cmp_p.mixed_cases == ()


def test_r11_commonmark_ascii_ordered_digits_and_sibling_items() -> None:
    # 1) R10 Important 2：禁止全角数字等非 ASCII Unicode 数字被当作 CommonMark 有序列表标记
    assert classify_finding_heuristic("[P2] [非阻断] 说明\n\n１. [非阻断]: /demo", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("[P2] [非阻断] 说明\n\n١. [非阻断]: /demo", "blocked") == "non_blocking_or_nit"
    assert _extract_markdown_link_ref_defs("１. [非阻断]: /demo") == {}
    assert _extract_markdown_link_ref_defs("1. [非阻断]: /demo") == {"非阻断": (3,)}

    # 2) R10 Important 3：已打开列表内兄弟序号（2. / 0. / 99. 等）合法开启新列表项，顶层段落后 2. 仍不得打断段落
    assert (
        classify_finding_heuristic("[P2] [非阻断] 说明\n\n1. text\n2. [非阻断]: /demo", "blocked")
        == "blocking_substantive"
    )
    assert (
        classify_finding_heuristic("[P2] [非阻断] 说明\n\n1. text\n2. ```\n[非阻断]: /demo", "blocked")
        == "blocking_substantive"
    )
    assert (
        classify_finding_heuristic("[P2] [非阻断] 说明\n\npara\n2. [非阻断]: /demo", "blocked")
        == "non_blocking_or_nit"
    )

    # 衍生嵌套边界：缩进在 1. 段落内部的 2. 仍不得打断段落；内层/外层已开列表兄弟项 2. 均可正常开启；围栏内缩进不提取
    assert (
        classify_finding_heuristic("[P2] [非阻断] 说明\n\n1. a\n   2. [非阻断]: /demo", "blocked")
        == "non_blocking_or_nit"
    )
    assert (
        classify_finding_heuristic("[P2] [非阻断] 说明\n\n1. a\n   1. b\n   2. [非阻断]: /demo", "blocked")
        == "blocking_substantive"
    )
    assert (
        classify_finding_heuristic("[P2] [非阻断] 说明\n\n1. a\n   1. b\n2. [非阻断]: /demo", "blocked")
        == "blocking_substantive"
    )
    assert (
        classify_finding_heuristic("[P2] [非阻断] 说明\n\n1. text\n2. ```\n   [非阻断]: /demo", "blocked")
        == "non_blocking_or_nit"
    )
    assert _extract_markdown_link_ref_defs("1. text\n2. [非阻断]: /demo") == {"非阻断": (11,)}
    assert _extract_markdown_link_ref_defs("1. text\n2. ```\n[非阻断]: /demo") == {"非阻断": (15,)}
    assert _extract_markdown_link_ref_defs("para\n2. [非阻断]: /demo") == {}


def test_r11_body_fallback_unwraps_markdown_links_and_ignores_code_and_defs(tmp_path: Path) -> None:
    # 1) R10 Important 4 全部 5 组核心反例
    shortcut_link = "[nit] 数据丢失\n\n[nit]: /demo"
    inline_link = "[nit](src/nit#L1) 数据丢失"
    full_ref_link = "[nit][loc] 数据丢失\n\n[loc]: /demo"
    fenced_code_nit = "数据丢失\n\n```text\n[nit] 示例代码\n```"
    real_nit_body = "数据丢失（[nit] 仅样式建议）"

    assert classify_finding_heuristic(shortcut_link, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(inline_link, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(full_ref_link, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(fenced_code_nit, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(real_nit_body, "blocked") == "non_blocking_or_nit"

    # 2) 直接校验 _parse_commonmark_blocks 与 _mask_inline_non_prose_in_block 逐块占位屏蔽行为
    shortcut_defs, shortcut_blocks = _parse_commonmark_blocks(shortcut_link)
    assert shortcut_blocks == ("[nit] 数据丢失",)
    assert _mask_inline_non_prose_in_block(shortcut_blocks[0], {d.norm_label for d in shortcut_defs}) == " \x01  数据丢失"

    _, inline_blocks = _parse_commonmark_blocks(inline_link)
    assert inline_blocks == (inline_link,)
    assert _mask_inline_non_prose_in_block(inline_blocks[0], set()) == " \x01  数据丢失"

    full_defs, full_blocks = _parse_commonmark_blocks(full_ref_link)
    assert full_blocks == ("[nit][loc] 数据丢失",)
    assert _mask_inline_non_prose_in_block(full_blocks[0], {d.norm_label for d in full_defs}) == " \x01  数据丢失"

    _, fenced_blocks = _parse_commonmark_blocks(fenced_code_nit)
    assert fenced_blocks == ("数据丢失",)

    _, real_nit_blocks = _parse_commonmark_blocks(real_nit_body)
    assert real_nit_blocks == (real_nit_body,)
    assert _mask_inline_non_prose_in_block(real_nit_blocks[0], set()) == real_nit_body

    # 3) 衍生边界：折叠引用链接、缩进代码块、HTML 注释块、反斜杠转义、仅含链接定义、含括号目标的内联链接、反引号前缀干扰
    assert classify_finding_heuristic("[nit][] 数据丢失\n\n[nit]: /demo", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("数据丢失\n\n    [nit] 示例代码", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("数据丢失\n\n<!--\n[nit] 注释\n-->", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("数据丢失\n\n[nit]: /demo", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[nit](src/a(1).py \"title ) here\") 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("`arr[` 缺少校验，见 [nit](src/nit#L1) 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("数据丢失 \\[nit] 仅样式建议\n\n[nit]: /demo", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("[nit] 仅样式建议\n\n```markdown\n[nit]: /demo\n```", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("[说明]: 建议后续优化 需要处理", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("[说明]: 建议后续优化", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("数据丢失 [nit] 问题\n\n1. text\n2. [nit]: /demo", "blocked") == "blocking_substantive"

    # 4) 端到端统计验证：4 条真实阻断反例全部计入 subsequent_head_pass_total_block_findings，真实 Nit 排除
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_run(
        runs_dir,
        "p1111-r1-block",
        pr_number=1111,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "run_id": "run-p1111-r1-block",
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {
                    "status": "blocked",
                    "findings": [
                        shortcut_link,
                        inline_link,
                        full_ref_link,
                        fenced_code_nit,
                        real_nit_body,
                    ],
                },
            }
        },
    )
    _write_run(
        runs_dir,
        "p1111-r2-pass",
        pr_number=1111,
        head_sha="b" * 40,
        registered_at_ns=200,
        attempt=2,
        verdict="PASS",
    )
    metrics = analyze_review_runs(runs_dir)
    assert metrics.corrupted_files == ()
    assert metrics.finding_heuristic_categories == {
        "blocking_substantive": 4,
        "non_blocking_or_nit": 1,
    }
    assert metrics.subsequent_head_pass_total_block_findings == 4
    assert metrics.subsequent_head_pass_inferred_fixed == 4
    assert metrics.subsequent_head_pass_undeterminable_findings == 0


def test_r12_block_isolated_visible_blocks_and_inline_masking(tmp_path: Path) -> None:
    # 1) R11 4 项 Important 核心反例与回归对拍
    lead_def_p1 = "[nit]: /demo\n\n[P1] 数据丢失"
    lead_def_nit = "[P1]: /demo\n\n[nit] 命名建议"
    link_colon = "说明 [nit](/doc): 数据丢失"
    cross_para_unclosed_link = "数据丢失 [nit](\n\n/demo)"
    inline_code_nit = "数据丢失，输入 `[nit]` 会触发错误"
    shortcut_ref_nit = "[nit] 数据丢失\n\n[nit]: /demo"
    full_ref_p1 = "[P1] [nit][location] 数据丢失\n\n[location]: src/nit#L1"
    inline_path_p1 = "[P1] [src/low:1](src/low#L1) 数据丢失"
    tilde_fence_non_blocking = "[P2] [非阻断] 说明\n\n~~~markdown\n[非阻断]: 示例\n~~~"
    real_nit_paren = "数据丢失（[nit] 仅样式建议）"

    assert classify_finding_heuristic(lead_def_p1, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(lead_def_nit, "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic(link_colon, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(cross_para_unclosed_link, "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic(inline_code_nit, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(shortcut_ref_nit, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(full_ref_p1, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(inline_path_p1, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(tilde_fence_non_blocking, "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic(real_nit_paren, "blocked") == "non_blocking_or_nit"

    # 2) Important 1：_parse_commonmark_blocks 返回独立 visible_blocks，行首解析只看首个非空可见块
    defs_1, blocks_1 = _parse_commonmark_blocks(lead_def_p1)
    assert [d.norm_label for d in defs_1] == ["nit"]
    assert blocks_1 == ("[P1] 数据丢失",)
    assert _parse_leading_severity_tag(lead_def_p1) == "blocking"

    defs_2, blocks_2 = _parse_commonmark_blocks(lead_def_nit)
    assert [d.norm_label for d in defs_2] == ["p1"]
    assert blocks_2 == ("[nit] 命名建议",)
    assert _parse_leading_severity_tag(lead_def_nit) == "non_blocking"

    # 前置链接定义在引用块/列表/同段落/多条定义时，行首严重度均准确落在首个可见正文块
    assert _parse_leading_severity_tag("> [nit]: /demo\n\n[P1] 数据丢失") == "blocking"
    assert _parse_leading_severity_tag("- [P1]: /demo\n\n[nit] 命名建议") == "non_blocking"
    assert _parse_leading_severity_tag("[nit]: /demo\n[P1] 数据丢失") == "blocking"
    assert _parse_leading_severity_tag("[nit]: /demo\n\n[P1]: 阻断说明 需要修复") == "blocking"
    assert _parse_leading_severity_tag("[P1]: 数据丢失 需要修复") == "blocking"
    assert _parse_leading_severity_tag("[nit]: /demo") is None
    assert _parse_leading_severity_tag("[P1] [nit] 数据丢失\n\n> [nit]: src/nit#L1") == "blocking"
    assert _parse_leading_severity_tag(tilde_fence_non_blocking) == "non_blocking"
    # 纯缩进/围栏代码块不含可见正文块，不误判为行首 Nit 标签
    assert _parse_leading_severity_tag("    [nit] 示例代码") is None
    assert classify_finding_heuristic("    [nit] 示例代码", "blocked") == "blocking_substantive"
    assert _parse_leading_severity_tag("```text\n[nit] 示例代码\n```") is None
    assert classify_finding_heuristic("```text\n[nit] 示例代码\n```", "blocked") == "blocking_substantive"

    # 3) Important 2：链接/图片/自动链接/行内 HTML 统一屏蔽为隔离占位符 " \x01 "，绝不与紧邻冒号拼接出伪标签
    assert _mask_inline_non_prose_in_block(link_colon, set()) == "说明  \x01 : 数据丢失"
    assert classify_finding_heuristic("说明 [nit](/doc)：数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[nit](/doc): 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("说明 ![nit](/img.png): 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("说明 ![nit][img]: 数据丢失\n\n[img]: /img.png", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("说明 [![nit](/img.png)](/doc): 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("说明 [nit][ref]: 数据丢失\n\n[ref]: /doc", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("说明 [nit][]: 数据丢失\n\n[nit]: /doc", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("说明 [nit]: 数据丢失\n\n[nit]: /doc", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("数据丢失 <!-- [nit] --> 必须修复", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic('数据丢失 <span title="nit: demo">必须修复</span>', "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("数据丢失 <https://example.com/nit:1> 必须修复", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("数据丢失 <![CDATA[[nit]]]> 必须修复", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("数据丢失 <?pi nit:1?> 必须修复", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("数据丢失 <!DOCTYPE nit:1> 必须修复", "blocked") == "blocking_substantive"
    # 按 CommonMark §6.3/§6.5：内联 `(` 解析失败时合法快捷引用链接 `[nit]` 仍被屏蔽；未定义或后接未定义完整引用时不屏蔽
    assert _mask_inline_non_prose_in_block("数据丢失 [nit](", {"nit"}) == "数据丢失  \x01 ("
    assert classify_finding_heuristic("数据丢失 [nit](\n\n[nit]: /doc", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("数据丢失 [missing]( [nit]", "blocked") == "non_blocking_or_nit"
    assert _mask_inline_non_prose_in_block("数据丢失 [nit](", {"missing"}) == "数据丢失 [nit]("
    assert _mask_inline_non_prose_in_block("数据丢失 [nit][missing]", {"nit"}) == "数据丢失 [nit][missing]"

    # 4) Important 3：每个段落独立进入 visible_blocks，绝不跨空行拼接行内链接或代码跨度
    _, split_blocks = _parse_commonmark_blocks(cross_para_unclosed_link)
    assert split_blocks == ("数据丢失 [nit](", "/demo)")
    assert classify_finding_heuristic("数据丢失 `[nit]\n\n` 仅样式建议", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("数据丢失 [nit][\n\nloc]\n\n[loc]: /demo", "blocked") == "non_blocking_or_nit"
    # 对照：同一段落内的单换行软回车内联链接合法闭合，仍正确屏蔽
    assert classify_finding_heuristic("数据丢失 [nit](\n/demo)", "blocked") == "blocking_substantive"

    # 5) Important 4：单/多反引号行内代码跨度屏蔽为 " \x01 "，未闭合反引号与反斜杠转义保持语义准确
    assert _mask_inline_non_prose_in_block(inline_code_nit, set()) == "数据丢失，输入  \x01  会触发错误"
    assert classify_finding_heuristic("数据丢失，输入 `` `[nit]` `` 会触发错误", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("数据丢失，标记 `非阻断` 与 `minor` 会触发解析错误", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("数据丢失，字段 `nit`: 未做边界校验", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("`[nit]` 导致服务崩溃", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("**`[nit]`** 导致服务崩溃", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[P1] `[nit]` 导致服务崩溃", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("数据丢失 ``未闭合 [nit] 仅样式建议", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("数据丢失 \\`[nit]` 仅样式建议", "blocked") == "non_blocking_or_nit"

    # 6) 端到端统计验证：全部 4 项 Important 反例在 BLOCK -> PASS 统计口径中精确分流
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_run(
        runs_dir,
        "p1212-r1-block",
        pr_number=1212,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "run_id": "run-p1212-r1-block",
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {
                    "status": "blocked",
                    "findings": [
                        lead_def_p1,
                        lead_def_nit,
                        link_colon,
                        cross_para_unclosed_link,
                        inline_code_nit,
                    ],
                },
            }
        },
    )
    _write_run(
        runs_dir,
        "p1212-r2-pass",
        pr_number=1212,
        head_sha="b" * 40,
        registered_at_ns=200,
        attempt=2,
        verdict="PASS",
    )
    metrics = analyze_review_runs(runs_dir)
    assert metrics.corrupted_files == ()
    assert metrics.finding_heuristic_categories == {
        "blocking_substantive": 3,
        "non_blocking_or_nit": 2,
    }
    assert metrics.subsequent_head_pass_total_block_findings == 3
    assert metrics.subsequent_head_pass_inferred_fixed == 3
    assert metrics.subsequent_head_pass_undeterminable_findings == 0


def test_r13_pure_commonmark_link_defs_and_empty_visible_blocks() -> None:
    # Important 1：纯 CommonMark §4.7 剥离所有合法链接引用定义（包括无路径标点的相对目标如 `README`）
    assert classify_finding_heuristic("[nit]: README\n\n[P1] 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[nit]: README\n\n数据丢失，见 [nit] 详情", "blocked") == "blocking_substantive"
    defs_readme, blocks_readme = _parse_commonmark_blocks("[nit]: README\n\n[P1] 数据丢失")
    assert [d.norm_label for d in defs_readme] == ["nit"]
    assert blocks_readme == ("[P1] 数据丢失",)
    assert _extract_markdown_link_ref_defs("[nit]: README") == {"nit": (0,)}

    # Important 2：剥离链接引用定义后 visible_blocks 为空时不回退扫描原始文本
    assert _parse_leading_severity_tag("[nit]: /demo") is None
    assert _parse_leading_severity_tag("[nit]: README") is None
    assert classify_finding_heuristic("[nit]: /demo", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[nit]: README", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[nit]: /demo\n[minor]: /m", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[nit]: /demo", "completed") == "non_blocking_or_nit"


def test_r13_commonmark_bracket_stack_nesting_and_shortcut_fallback(tmp_path: Path) -> None:
    # Important 3：内联链接 `(...)` 解析失败回退快捷引用链接；后接完整引用 `[missing]` 或空白 `[ ]` 不回退
    fallback_see_details = "数据丢失，见 [nit](see details)\n\n[nit]: /doc"
    fallback_unclosed_paren = "数据丢失，见 [nit](\n\n[nit]: /doc"
    fallback_unclosed_title = '数据丢失，见 [nit](/a "unclosed)\n\n[nit]: /doc'
    fallback_unclosed_ref = "数据丢失，见 [nit][unclosed\n\n[nit]: /doc"
    no_fallback_missing_ref = "数据丢失，见 [nit][missing]\n\n[nit]: /doc"
    no_fallback_ws_ref = "数据丢失，见 [nit][ ]\n\n[nit]: /doc"

    assert classify_finding_heuristic(fallback_see_details, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(fallback_unclosed_paren, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(fallback_unclosed_title, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(fallback_unclosed_ref, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(no_fallback_missing_ref, "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic(no_fallback_ws_ref, "blocked") == "non_blocking_or_nit"

    # Important 4：CommonMark §6.3 链接不得包含链接（外层 `[` 失效）；图片可含链接且不使外层链接失效
    nested_link_exposes_nit = "[说明 [文档](/doc) [nit]](/issue)"
    image_containing_link = "![图片 [文档](/doc) [nit]](/img.png)"
    link_containing_image = "[外层 ![图](/img.png) [nit]](/issue)"
    deep_link_in_image_breaks_outer_link = "[a ![b [c](/x)](/img) [nit]](/url)"
    inner_shortcut_breaks_outer_link = "[[nit]](/url)\n\n[nit]: /doc"
    inner_link_breaks_outer_full_ref = "[前导 [文档](/doc) [nit]][ref]\n\n[ref]: /r"
    inner_link_keeps_outer_image_full_ref = "![前导 [文档](/doc) [nit]][ref]\n\n[ref]: /r"

    assert classify_finding_heuristic(nested_link_exposes_nit, "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic(image_containing_link, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(link_containing_image, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(deep_link_in_image_breaks_outer_link, "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic(inner_shortcut_breaks_outer_link, "blocked") == "blocking_substantive"
    assert classify_finding_heuristic(inner_link_breaks_outer_full_ref, "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic(inner_link_keeps_outer_image_full_ref, "blocked") == "blocking_substantive"

    assert _mask_inline_non_prose_in_block(nested_link_exposes_nit, set()) == "[说明  \x01  [nit]](/issue)"
    assert _mask_inline_non_prose_in_block(image_containing_link, set()) == " \x01 "
    assert _mask_inline_non_prose_in_block(link_containing_image, set()) == " \x01 "
    assert _mask_inline_non_prose_in_block("数据丢失，见 [nit](see details)", {"nit"}) == "数据丢失，见  \x01 (see details)"

    # 端到端验证上述反例在 BLOCK -> PASS 统计中的归类与分母
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_run(
        runs_dir,
        "p1313-r1-block",
        pr_number=1313,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "run_id": "run-p1313-r1-block",
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {
                    "status": "blocked",
                    "findings": [
                        "[nit]: README\n\n[P1] 数据丢失",
                        "[nit]: /demo",
                        fallback_see_details,
                        nested_link_exposes_nit,
                        image_containing_link,
                        link_containing_image,
                        no_fallback_missing_ref,
                    ],
                },
            }
        },
    )
    _write_run(
        runs_dir,
        "p1313-r2-pass",
        pr_number=1313,
        head_sha="b" * 40,
        registered_at_ns=200,
        attempt=2,
        verdict="PASS",
    )
    metrics = analyze_review_runs(runs_dir)
    assert metrics.corrupted_files == ()
    assert metrics.finding_heuristic_categories == {
        "blocking_substantive": 5,
        "non_blocking_or_nit": 2,
    }
    assert metrics.subsequent_head_pass_total_block_findings == 5
    assert metrics.subsequent_head_pass_inferred_fixed == 5
    assert metrics.subsequent_head_pass_undeterminable_findings == 0


def test_r13_per_field_merge_target_and_outcome_target(tmp_path: Path) -> None:
    # Important 5：复现 Codex R12 最小反例（target.json 缺 registered_at_ns，outcome.target 提供合法正整数，无回执）
    runs_min = tmp_path / "runs_min"
    run_1 = runs_min / "r1"
    run_1.mkdir(parents=True)
    (run_1 / "target.json").write_text(json.dumps({"pr_number": 1}), encoding="utf-8")
    (run_1 / "outcome.json").write_text(
        json.dumps({"verdict": "PASS", "target": {"pr_number": 1, "registered_at_ns": 100}}),
        encoding="utf-8",
    )
    m_min = analyze_review_runs(runs_min)
    assert m_min.corrupted_files == ()
    assert m_min.unorderable_runs == 0
    assert m_min.rounds_to_first_pass_all.bucket_1 == 1
    assert m_min.rounds_to_first_pass_effective.bucket_1 == 1

    # 按字段合并 attempt：target.json 提供 registered_at_ns、outcome.target 提供 attempt 决定同时间戳先后顺序
    runs_att = tmp_path / "runs_att"
    r_att_a = runs_att / "z-first-by-attempt"
    r_att_b = runs_att / "a-second-by-attempt"
    r_att_a.mkdir(parents=True)
    r_att_b.mkdir(parents=True)
    (r_att_a / "target.json").write_text(
        json.dumps({"pr_number": 2, "head_sha": "a" * 40, "registered_at_ns": 100}),
        encoding="utf-8",
    )
    (r_att_a / "outcome.json").write_text(
        json.dumps({"verdict": "BLOCK", "target": {"pr_number": 2, "attempt": 1}}),
        encoding="utf-8",
    )
    (r_att_b / "target.json").write_text(
        json.dumps({"pr_number": 2, "head_sha": "b" * 40}),
        encoding="utf-8",
    )
    (r_att_b / "outcome.json").write_text(
        json.dumps({"verdict": "PASS", "target": {"pr_number": 2, "registered_at_ns": 100, "attempt": 2}}),
        encoding="utf-8",
    )
    m_att = analyze_review_runs(runs_att)
    assert m_att.corrupted_files == ()
    assert m_att.unorderable_runs == 0
    assert m_att.rounds_to_first_pass_all.bucket_2 == 1
    assert m_att.rounds_to_first_pass_effective.bucket_2 == 1

    # 负对照：两处 registered_at_ns 冲突、或任一处显式非法时均归入 unorderable_runs
    for case_name, target_obj, outcome_target_obj in [
        ("ts_conflict", {"pr_number": 1, "registered_at_ns": 100}, {"pr_number": 1, "registered_at_ns": 200}),
        ("outcome_ts_zero", {"pr_number": 1, "registered_at_ns": 100}, {"pr_number": 1, "registered_at_ns": 0}),
        ("target_ts_bool", {"pr_number": 1, "registered_at_ns": True}, {"pr_number": 1, "registered_at_ns": 100}),
        ("target_ts_none", {"pr_number": 1, "registered_at_ns": None}, {"pr_number": 1, "registered_at_ns": 100}),
        ("outcome_ts_str", {"pr_number": 1, "registered_at_ns": 100}, {"pr_number": 1, "registered_at_ns": "100"}),
    ]:
        runs_bad = tmp_path / f"runs_{case_name}"
        r_bad = runs_bad / "r1"
        r_bad.mkdir(parents=True)
        (r_bad / "target.json").write_text(json.dumps(target_obj), encoding="utf-8")
        (r_bad / "outcome.json").write_text(
            json.dumps({"verdict": "PASS", "target": outcome_target_obj}),
            encoding="utf-8",
        )
        m_bad = analyze_review_runs(runs_bad)
        assert m_bad.corrupted_files == ()
        assert m_bad.unorderable_runs == 1, case_name
        assert m_bad.rounds_to_first_pass_all.prs_counted == 0, case_name
        assert m_bad.rounds_to_first_pass_effective.prs_counted == 0, case_name


def test_r14_attempt_conflict_and_invalid_unorderable(tmp_path: Path) -> None:
    # Important 1：复现 Codex R13 最小反例（两种冲突方向：3 vs 1 与 1 vs 3）
    for direction_name, target_att, outcome_att in [
        ("target_3_outcome_1", 3, 1),
        ("target_1_outcome_3", 1, 3),
    ]:
        runs_dir = tmp_path / f"conflict_{direction_name}"
        r_pass = runs_dir / "r-pass"
        r_block = runs_dir / "r-block"
        r_pass.mkdir(parents=True)
        (r_block / "claude-opus-5-5").mkdir(parents=True)

        (r_pass / "target.json").write_text(
            json.dumps({"pr_number": 1, "head_sha": "b" * 40, "registered_at_ns": 100, "attempt": 2}),
            encoding="utf-8",
        )
        (r_pass / "outcome.json").write_text(
            json.dumps(
                {
                    "verdict": "PASS",
                    "target": {"pr_number": 1, "head_sha": "b" * 40, "registered_at_ns": 100, "attempt": 2},
                }
            ),
            encoding="utf-8",
        )

        (r_block / "target.json").write_text(
            json.dumps({"pr_number": 1, "head_sha": "a" * 40, "registered_at_ns": 100, "attempt": target_att}),
            encoding="utf-8",
        )
        (r_block / "outcome.json").write_text(
            json.dumps(
                {
                    "verdict": "BLOCK",
                    "target": {"pr_number": 1, "head_sha": "a" * 40, "registered_at_ns": 100, "attempt": outcome_att},
                }
            ),
            encoding="utf-8",
        )
        (r_block / "claude-opus-5-5" / "receipt.json").write_text(
            json.dumps(
                {
                    "run_id": f"run-{direction_name}",
                    "pr_number": 1,
                    "head_sha": "a" * 40,
                    "status": "completed",
                    "model": "claude-opus-5-5",
                    "result": {"status": "blocked", "findings": ["[P1] 真实缺陷"]},
                }
            ),
            encoding="utf-8",
        )

        m = analyze_review_runs(runs_dir)
        assert m.corrupted_files == (), direction_name
        assert m.unorderable_runs == 1, direction_name
        assert m.rounds_to_first_pass_all.prs_counted == 0, direction_name
        assert m.rounds_to_first_pass_effective.prs_counted == 0, direction_name
        # R15 起 subsequent_head_pass_* 仅依赖严格时间戳，不因 attempt 冲突丢弃合法时间戳样本；
        # 本用例两轮均为 ts=100（非严格更晚），故归入可判定未修（total=1, fixed=0, undeterminable=0）。
        assert m.subsequent_head_pass_undeterminable_findings == 0, direction_name
        assert m.subsequent_head_pass_total_block_findings == 1, direction_name
        assert m.subsequent_head_pass_inferred_fixed == 0, direction_name

    # PASS 轮 attempt 冲突但时间戳合法（同 ts=100）：排除首 PASS 轮次，同时不污染 subsequent_head_pass_undeterminable_findings
    runs_pass_bad = tmp_path / "pass_attempt_conflict"
    r_b = runs_pass_bad / "r1-block"
    r_p = runs_pass_bad / "r2-pass"
    (r_b / "claude-opus-5-5").mkdir(parents=True)
    r_p.mkdir(parents=True)
    (r_b / "target.json").write_text(
        json.dumps({"pr_number": 7, "head_sha": "a" * 40, "registered_at_ns": 100, "attempt": 1}),
        encoding="utf-8",
    )
    (r_b / "outcome.json").write_text(
        json.dumps({"verdict": "BLOCK", "target": {"pr_number": 7, "registered_at_ns": 100, "attempt": 1}}),
        encoding="utf-8",
    )
    (r_b / "claude-opus-5-5" / "receipt.json").write_text(
        json.dumps(
            {
                "run_id": "run-p7-block",
                "pr_number": 7,
                "head_sha": "a" * 40,
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 缺陷"]},
            }
        ),
        encoding="utf-8",
    )
    (r_p / "target.json").write_text(
        json.dumps({"pr_number": 7, "head_sha": "b" * 40, "registered_at_ns": 100, "attempt": 3}),
        encoding="utf-8",
    )
    (r_p / "outcome.json").write_text(
        json.dumps({"verdict": "PASS", "target": {"pr_number": 7, "registered_at_ns": 100, "attempt": 1}}),
        encoding="utf-8",
    )
    m_pb = analyze_review_runs(runs_pass_bad)
    assert m_pb.corrupted_files == ()
    assert m_pb.unorderable_runs == 1
    assert m_pb.rounds_to_first_pass_all.prs_counted == 0
    assert m_pb.subsequent_head_pass_undeterminable_findings == 0
    assert m_pb.subsequent_head_pass_total_block_findings == 1
    assert m_pb.subsequent_head_pass_inferred_fixed == 0

    # 显式非法 attempt（bool / 负数 / 字符串 / None / float）无论出现在哪一侧均判不可排序
    for bad_name, target_obj, outcome_target_obj in [
        ("target_bool_true", {"pr_number": 1, "registered_at_ns": 100, "attempt": True}, {"pr_number": 1, "attempt": 2}),
        ("outcome_bool_false", {"pr_number": 1, "registered_at_ns": 100, "attempt": 1}, {"pr_number": 1, "attempt": False}),
        ("target_negative", {"pr_number": 1, "registered_at_ns": 100, "attempt": -1}, {"pr_number": 1}),
        ("outcome_negative", {"pr_number": 1, "registered_at_ns": 100}, {"pr_number": 1, "attempt": -2}),
        ("target_str", {"pr_number": 1, "registered_at_ns": 100, "attempt": "1"}, {"pr_number": 1, "attempt": 1}),
        ("outcome_none", {"pr_number": 1, "registered_at_ns": 100, "attempt": 1}, {"pr_number": 1, "attempt": None}),
        ("target_float", {"pr_number": 1, "registered_at_ns": 100, "attempt": 1.5}, {"pr_number": 1}),
    ]:
        runs_inv = tmp_path / f"inv_{bad_name}"
        r_inv = runs_inv / "r1"
        r_inv.mkdir(parents=True)
        (r_inv / "target.json").write_text(json.dumps(target_obj), encoding="utf-8")
        (r_inv / "outcome.json").write_text(
            json.dumps({"verdict": "PASS", "target": outcome_target_obj}),
            encoding="utf-8",
        )
        m_inv = analyze_review_runs(runs_inv)
        assert m_inv.corrupted_files == (), bad_name
        assert m_inv.unorderable_runs == 1, bad_name
        assert m_inv.rounds_to_first_pass_all.prs_counted == 0, bad_name

    # 正对照：attempt == 0（非负整数）与双侧省略（默认 0）均合法且按 0 < 1 排序
    runs_zero = tmp_path / "valid_zero_attempt"
    r_z1 = runs_zero / "z-block-attempt-0"
    r_z2 = runs_zero / "a-pass-attempt-1"
    r_z1.mkdir(parents=True)
    r_z2.mkdir(parents=True)
    (r_z1 / "target.json").write_text(
        json.dumps({"pr_number": 3, "head_sha": "a" * 40, "registered_at_ns": 100, "attempt": 0}),
        encoding="utf-8",
    )
    (r_z1 / "outcome.json").write_text(
        json.dumps({"verdict": "BLOCK", "target": {"pr_number": 3, "attempt": 0}}),
        encoding="utf-8",
    )
    (r_z2 / "target.json").write_text(
        json.dumps({"pr_number": 3, "head_sha": "b" * 40, "registered_at_ns": 100}),
        encoding="utf-8",
    )
    (r_z2 / "outcome.json").write_text(
        json.dumps({"verdict": "PASS", "target": {"pr_number": 3, "attempt": 1}}),
        encoding="utf-8",
    )
    m_zero = analyze_review_runs(runs_zero)
    assert m_zero.corrupted_files == ()
    assert m_zero.unorderable_runs == 0
    assert m_zero.rounds_to_first_pass_all.bucket_2 == 1
    assert m_zero.rounds_to_first_pass_effective.bucket_2 == 1


def test_r14_leading_tag_parenthetical_negated_pass_and_style_word_boundary() -> None:
    # Important 2：非链接括号附注不再误杀行首标签，真实链接仍由 CommonMark §6.3 栈屏蔽
    assert (
        classify_finding_heuristic("[P1](Linux only) 数据丢失，建议后续也补监控", "blocked")
        == "blocking_substantive"
    )
    assert _parse_leading_severity_tag("[P1](Linux only) 数据丢失，建议后续也补监控") == "blocking"
    assert classify_finding_heuristic("[nit](Linux only) 命名可微调", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("[P1] [src/low:1](src/low#L1) 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[nit](/doc) 数据丢失", "blocked") == "blocking_substantive"
    assert (
        classify_finding_heuristic("[P1] [nit][location] 数据丢失\n\n[location]: src/nit#L1", "blocked")
        == "blocking_substantive"
    )

    # Important 3：_TAG_NON_BLOCKING_RE 中“通过”加否定保护，防止“[阻断/验收未通过]”误判非阻断
    assert classify_finding_heuristic("[阻断/验收未通过] 数据丢失", "blocked") == "blocking_substantive"
    assert _parse_leading_severity_tag("[阻断/验收未通过] 数据丢失") == "blocking"
    assert classify_finding_heuristic("[验收不通过] 数据丢失", "blocked") == "blocking_substantive"
    assert _parse_leading_severity_tag("[验收不通过] 数据丢失") is None
    assert classify_finding_heuristic("[测试没通过] 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[没有通过校验] 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[非通过状态] 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[未获通过] 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[通过] 无问题", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("【核实通过】无问题", "blocked") == "non_blocking_or_nit"

    # Nit：_STYLE_FORMAT_RE 英文词项词边界保护，防止 blacklist 误命中 black
    assert is_style_or_format_finding("blacklist 校验失效导致数据丢失") is False
    assert classify_finding_heuristic("blacklist 校验失效导致数据丢失", "blocked") == "blocking_substantive"
    assert is_style_or_format_finding("black 格式化失败") is True
    assert classify_finding_heuristic("black 格式化失败", "blocked") == "blocking_style_or_format"
    assert is_style_or_format_finding("black check failed") is True
    assert is_style_or_format_finding("scruffy state causes crash") is False
    assert is_style_or_format_finding("ruff lint failed") is True
    assert is_style_or_format_finding("typography rendering panic") is False
    assert is_style_or_format_finding("typo in comment") is True
    assert is_style_or_format_finding("reimport order mismatch") is False
    assert is_style_or_format_finding("fix import order") is True
    assert is_style_or_format_finding("import 排序混乱") is True


def test_r15_separated_orderability_gate_for_subsequent_head_pass(tmp_path: Path) -> None:
    # Important 1：BLOCK 轮 attempt 冲突（1 vs 2）但时间戳严格合法（ts=100），后续 head B（ts=200）PASS
    runs_block_att = tmp_path / "block_attempt_conflict_strict_later"
    r1 = runs_block_att / "r1-block"
    r2 = runs_block_att / "r2-pass"
    (r1 / "claude-opus-5-5").mkdir(parents=True)
    r2.mkdir(parents=True)
    (r1 / "target.json").write_text(
        json.dumps({"pr_number": 1501, "head_sha": "a" * 40, "registered_at_ns": 100, "attempt": 1}),
        encoding="utf-8",
    )
    (r1 / "outcome.json").write_text(
        json.dumps(
            {
                "verdict": "BLOCK",
                "target": {"pr_number": 1501, "head_sha": "a" * 40, "registered_at_ns": 100, "attempt": 2},
            }
        ),
        encoding="utf-8",
    )
    (r1 / "claude-opus-5-5" / "receipt.json").write_text(
        json.dumps(
            {
                "run_id": "run-p1501-r1",
                "pr_number": 1501,
                "head_sha": "a" * 40,
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 缺陷"]},
            }
        ),
        encoding="utf-8",
    )
    (r2 / "target.json").write_text(
        json.dumps({"pr_number": 1501, "head_sha": "b" * 40, "registered_at_ns": 200, "attempt": 2}),
        encoding="utf-8",
    )
    (r2 / "outcome.json").write_text(
        json.dumps(
            {
                "verdict": "PASS",
                "target": {"pr_number": 1501, "head_sha": "b" * 40, "registered_at_ns": 200, "attempt": 2},
            }
        ),
        encoding="utf-8",
    )
    m1 = analyze_review_runs(runs_block_att)
    assert m1.corrupted_files == ()
    assert m1.unorderable_runs == 1
    assert m1.rounds_to_first_pass_all.prs_counted == 0
    assert m1.rounds_to_first_pass_effective.prs_counted == 0
    assert m1.subsequent_head_pass_inferred_fixed == 1
    assert m1.subsequent_head_pass_total_block_findings == 1
    assert m1.subsequent_head_pass_undeterminable_findings == 0

    # 反向场景：PASS 轮 attempt 冲突但时间戳严格更晚（ts=200 > ts=100），同样应计入推定已修
    runs_pass_att = tmp_path / "pass_attempt_conflict_strict_later"
    _write_run(
        runs_pass_att,
        "p1502-r1-block",
        pr_number=1502,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "run_id": "run-p1502-r1-block",
                "pr_number": 1502,
                "head_sha": "a" * 40,
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 缺陷"]},
            }
        },
    )
    rp = runs_pass_att / "r2-pass"
    rp.mkdir(parents=True)
    (rp / "target.json").write_text(
        json.dumps({"pr_number": 1502, "head_sha": "b" * 40, "registered_at_ns": 200, "attempt": 1}),
        encoding="utf-8",
    )
    (rp / "outcome.json").write_text(
        json.dumps(
            {
                "verdict": "PASS",
                "target": {"pr_number": 1502, "head_sha": "b" * 40, "registered_at_ns": 200, "attempt": 2},
            }
        ),
        encoding="utf-8",
    )
    m2 = analyze_review_runs(runs_pass_att)
    assert m2.corrupted_files == ()
    assert m2.unorderable_runs == 1
    assert m2.rounds_to_first_pass_all.prs_counted == 0
    assert m2.rounds_to_first_pass_effective.prs_counted == 0
    assert m2.subsequent_head_pass_inferred_fixed == 1
    assert m2.subsequent_head_pass_total_block_findings == 1
    assert m2.subsequent_head_pass_undeterminable_findings == 0


def test_r15_causal_key_tie_ambiguity_independent_of_dir_name(tmp_path: Path) -> None:
    # Important 2：同 (registered_at_ns=100, attempt=1) 并列 BLOCK 与 PASS，对调目录名结果必须完全一致且跳过该 PR
    results: list[tuple[int, int, int, int]] = []
    for order_name, block_dir, pass_dir in [
        ("block_before_pass", "a-run", "b-run"),
        ("pass_before_block", "b-run", "a-run"),
    ]:
        runs_dir = tmp_path / f"tie_{order_name}"
        runs_dir.mkdir()
        _write_run(
            runs_dir,
            block_dir,
            pr_number=1510,
            head_sha="a" * 40,
            registered_at_ns=100,
            attempt=1,
            verdict="BLOCK",
            receipts={
                "claude-opus-5-5": {
                    "run_id": f"run-{block_dir}",
                    "status": "completed",
                    "model": "claude-opus-5-5",
                    "result": {"status": "blocked", "findings": ["[P1] 缺陷"]},
                }
            },
        )
        _write_run(
            runs_dir,
            pass_dir,
            pr_number=1510,
            head_sha="b" * 40,
            registered_at_ns=100,
            attempt=1,
            verdict="PASS",
        )
        m = analyze_review_runs(runs_dir)
        assert m.corrupted_files == (), order_name
        assert m.unorderable_runs == 0, order_name
        assert m.rounds_to_first_pass_all.prs_counted == 0, order_name
        assert m.rounds_to_first_pass_effective.prs_counted == 0, order_name
        assert m.prs_first_pass_reused == 0, order_name
        assert m.subsequent_head_pass_total_block_findings == 1, order_name
        assert m.subsequent_head_pass_inferred_fixed == 0, order_name
        results.append(
            (
                m.unorderable_runs,
                m.rounds_to_first_pass_all.prs_counted,
                m.rounds_to_first_pass_effective.prs_counted,
                m.prs_first_pass_reused,
            )
        )
    assert results[0] == results[1]

    # 同组混合复用 PASS 与新产生 PASS 也存在歧义（影响 rounds_effective 与 prs_first_pass_reused），对调目录名均跳过
    for order_name, reused_dir, fresh_dir in [
        ("reused_first", "a-run", "b-run"),
        ("fresh_first", "b-run", "a-run"),
    ]:
        runs_mix = tmp_path / f"tie_mixed_reuse_{order_name}"
        runs_mix.mkdir()
        _write_run(
            runs_mix,
            reused_dir,
            pr_number=1511,
            head_sha="a" * 40,
            registered_at_ns=100,
            attempt=1,
            verdict="PASS",
            reused_from="prev-pass",
        )
        _write_run(
            runs_mix,
            fresh_dir,
            pr_number=1511,
            head_sha="a" * 40,
            registered_at_ns=100,
            attempt=1,
            verdict="PASS",
        )
        m_mix = analyze_review_runs(runs_mix)
        assert m_mix.unorderable_runs == 0, order_name
        assert m_mix.rounds_to_first_pass_all.prs_counted == 0, order_name
        assert m_mix.rounds_to_first_pass_effective.prs_counted == 0, order_name
        assert m_mix.prs_first_pass_reused == 0, order_name

    # 无歧义并列正对照：早期双 BLOCK 并列 + 后续单 PASS -> 确定 3 轮；早期单 BLOCK + 后续双同型 fresh PASS -> 确定 2 轮；
    # 歧义并列 PR 若后续在更晚时间戳出现不同 head PASS，subsequent_head_pass_* 仍按严格 > 正常统计。
    runs_ok = tmp_path / "tie_non_ambiguous_and_subsequent"
    runs_ok.mkdir()
    _write_run(runs_ok, "p1512-b1", pr_number=1512, head_sha="a" * 40, registered_at_ns=100, attempt=1, verdict="BLOCK")
    _write_run(runs_ok, "p1512-b2", pr_number=1512, head_sha="a" * 40, registered_at_ns=100, attempt=1, verdict="BLOCK")
    _write_run(runs_ok, "p1512-p3", pr_number=1512, head_sha="b" * 40, registered_at_ns=200, attempt=1, verdict="PASS")

    _write_run(runs_ok, "p1513-b1", pr_number=1513, head_sha="a" * 40, registered_at_ns=100, attempt=1, verdict="BLOCK")
    _write_run(runs_ok, "p1513-p2a", pr_number=1513, head_sha="b" * 40, registered_at_ns=200, attempt=1, verdict="PASS")
    _write_run(runs_ok, "p1513-p2b", pr_number=1513, head_sha="b" * 40, registered_at_ns=200, attempt=1, verdict="PASS")

    _write_run(runs_ok, "p1514-b1", pr_number=1514, head_sha="a" * 40, registered_at_ns=100, attempt=1, verdict="BLOCK")
    _write_run(
        runs_ok,
        "p1514-p2a",
        pr_number=1514,
        head_sha="b" * 40,
        registered_at_ns=200,
        attempt=1,
        verdict="PASS",
        reused_from="old-1",
    )
    _write_run(
        runs_ok,
        "p1514-p2b",
        pr_number=1514,
        head_sha="b" * 40,
        registered_at_ns=200,
        attempt=1,
        verdict="PASS",
        reused_from="old-2",
    )

    _write_run(
        runs_ok,
        "p1515-b1",
        pr_number=1515,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="BLOCK",
        receipts={
            "claude-opus-5-5": {
                "run_id": "run-p1515-b1",
                "status": "completed",
                "model": "claude-opus-5-5",
                "result": {"status": "blocked", "findings": ["[P1] 真实缺陷"]},
            }
        },
    )
    _write_run(runs_ok, "p1515-p1", pr_number=1515, head_sha="a" * 40, registered_at_ns=100, attempt=1, verdict="PASS")
    _write_run(runs_ok, "p1515-p2", pr_number=1515, head_sha="b" * 40, registered_at_ns=200, attempt=2, verdict="PASS")

    m_ok = analyze_review_runs(runs_ok)
    assert m_ok.unorderable_runs == 0
    assert m_ok.rounds_to_first_pass_all.prs_counted == 3
    assert m_ok.rounds_to_first_pass_all.bucket_2 == 2
    assert m_ok.rounds_to_first_pass_all.bucket_3 == 1
    assert m_ok.rounds_to_first_pass_effective.prs_counted == 2
    assert m_ok.rounds_to_first_pass_effective.bucket_2 == 1
    assert m_ok.rounds_to_first_pass_effective.bucket_3 == 1
    assert m_ok.prs_first_pass_reused == 1
    assert m_ok.subsequent_head_pass_total_block_findings == 1
    assert m_ok.subsequent_head_pass_inferred_fixed == 1
    assert m_ok.subsequent_head_pass_undeterminable_findings == 0


def test_r15_three_tier_full_token_severity_tags() -> None:
    # Important 3：三层全词元分级，杜绝“无法通过”/“信息泄露”/“流程提示”子串覆盖显式阻断或无标签阻断
    assert classify_finding_heuristic("[阻断/验收无法通过] 数据丢失", "blocked") == "blocking_substantive"
    assert _parse_leading_severity_tag("[阻断/验收无法通过] 数据丢失") == "blocking"
    assert classify_finding_heuristic("[P1/信息泄露] 泄露密钥", "blocked") == "blocking_substantive"
    assert _parse_leading_severity_tag("[P1/信息泄露] 泄露密钥") == "blocking"
    assert classify_finding_heuristic("[验收无法通过] 数据丢失", "blocked") == "blocking_substantive"
    assert _parse_leading_severity_tag("[验收无法通过] 数据丢失") is None
    assert classify_finding_heuristic("[信息泄露] 泄露密钥", "blocked") == "blocking_substantive"
    assert _parse_leading_severity_tag("[信息泄露] 泄露密钥") is None
    assert classify_finding_heuristic("【流程提示】不能沿用改动前的旧 PASS", "blocked") == "blocking_substantive"
    assert _parse_leading_severity_tag("【流程提示】不能沿用改动前的旧 PASS") is None
    assert classify_finding_heuristic("[P1/信息] 必须修复", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[阻断/建议] 必须修复", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[must-fix/信息] 必须修复", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[must fix/通过] 必须修复", "blocked") == "blocking_substantive"

    # Tier 1 显式非阻断覆盖与 Tier 3 纯信息/通过/建议全词元保留
    for nb_text in (
        "[P2/非阻断] 说明",
        "[P2/non-blocking] 说明",
        "[P2 non blocking] 说明",
        "[P3 非阻断] 说明",
        "[低，非阻断] 说明",
        "[非阻断/Nit] 说明",
        "【低｜待核】行号漂移",
        "[信息] 补充说明",
        "【信息】补充说明",
        "【信息级，不阻断】补充说明",
        "[信息级] 补充说明",
        "[通过] 校验一致",
        "【核实通过】无问题",
        "[核验通过] 逻辑无误",
        "[通过项] 与脚本一致",
        "[已核对/无问题] 已核实",
        "[已核，未发现问题] 已核实",
        "[建议] 可抽常量",
        "[提示] 补充注释",
        "[可选] 顺手清理",
        "[确认无问题] 符合预期",
        "[确认无误] 符合预期",
    ):
        assert classify_finding_heuristic(nb_text, "blocked") == "non_blocking_or_nit", nb_text


def test_r15_reused_pass_runs_vs_stale_reuse_markdown(tmp_path: Path) -> None:
    # Nit：STALE + reused_from 不得在 Markdown 中显示为“沿用历史 PASS：1”
    runs_stale = tmp_path / "stale_reuse"
    r_stale = runs_stale / "r1-stale"
    r_stale.mkdir(parents=True)
    (r_stale / "target.json").write_text(
        json.dumps({"pr_number": 1520, "head_sha": "a" * 40, "registered_at_ns": 100, "attempt": 1}),
        encoding="utf-8",
    )
    (r_stale / "outcome.json").write_text(
        json.dumps({"verdict": "STALE", "reused_from": "prev"}),
        encoding="utf-8",
    )
    m_stale = analyze_review_runs(runs_stale)
    assert m_stale.verdict_counts == {"STALE": 1}
    assert m_stale.reused_runs == 1
    assert m_stale.reused_pass_runs == 0
    assert m_stale.fresh_pass_runs == 0
    md_stale = render_baseline_markdown(m_stale)
    assert "沿用历史 PASS（`reused_from` 且终态为 `PASS`）：`0`（含非 `PASS` 复用总计 `1`）" in md_stale
    assert "沿用历史 PASS：`1`" not in md_stale
    assert "沿用历史 PASS：1" not in md_stale

    # 混合正对照：1 条复用 PASS + 1 条复用 STALE + 1 条新产生 PASS
    runs_mix = tmp_path / "mix_reuse"
    runs_mix.mkdir()
    _write_run(
        runs_mix,
        "r1-reused-pass",
        pr_number=1521,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=1,
        verdict="PASS",
        reused_from="prev-pass",
    )
    _write_run(
        runs_mix,
        "r2-reused-stale",
        pr_number=1521,
        head_sha="a" * 40,
        registered_at_ns=200,
        attempt=2,
        verdict="STALE",
        reused_from="prev-stale",
    )
    _write_run(
        runs_mix,
        "r3-fresh-pass",
        pr_number=1521,
        head_sha="b" * 40,
        registered_at_ns=300,
        attempt=3,
        verdict="PASS",
    )
    m_mix = analyze_review_runs(runs_mix)
    assert m_mix.reused_runs == 2
    assert m_mix.reused_pass_runs == 1
    assert m_mix.fresh_pass_runs == 1
    md_mix = render_baseline_markdown(m_mix)
    assert "沿用历史 PASS（`reused_from` 且终态为 `PASS`）：`1`（含非 `PASS` 复用总计 `2`）" in md_mix


def test_r16_missing_attempt_unknown_tie_and_controls(tmp_path: Path) -> None:
    # Important 1：同时间戳内缺失 attempt 为未知（None），绝不默认填 0 编造 PASS 领先于 attempt=2 的 BLOCK
    for order_name, pass_dir, block_dir in [
        ("pass_first", "a-pass", "b-block"),
        ("block_first", "b-pass", "a-block"),
    ]:
        runs_tie = tmp_path / f"missing_attempt_tie_{order_name}"
        runs_tie.mkdir()
        _write_run(
            runs_tie,
            pass_dir,
            pr_number=1601,
            head_sha="b" * 40,
            registered_at_ns=100,
            attempt=None,
            verdict="PASS",
        )
        _write_run(
            runs_tie,
            block_dir,
            pr_number=1601,
            head_sha="a" * 40,
            registered_at_ns=100,
            attempt=2,
            verdict="BLOCK",
        )
        m_tie = analyze_review_runs(runs_tie)
        assert m_tie.corrupted_files == (), order_name
        assert m_tie.unorderable_runs == 0, order_name
        assert m_tie.rounds_to_first_pass_all.prs_counted == 0, order_name
        assert m_tie.rounds_to_first_pass_all.bucket_1 == 0, order_name
        assert m_tie.rounds_to_first_pass_effective.prs_counted == 0, order_name
        assert m_tie.prs_first_pass_reused == 0, order_name

    # 同时间戳混有复用 PASS 与新产生 PASS 且存在缺失 attempt：同样歧义跳过
    runs_mix_reuse = tmp_path / "missing_attempt_mixed_reuse"
    runs_mix_reuse.mkdir()
    _write_run(
        runs_mix_reuse,
        "a-fresh-pass",
        pr_number=1602,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=None,
        verdict="PASS",
    )
    _write_run(
        runs_mix_reuse,
        "b-reused-pass",
        pr_number=1602,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=2,
        verdict="PASS",
        reused_from="prev-pass",
    )
    m_mix_reuse = analyze_review_runs(runs_mix_reuse)
    assert m_mix_reuse.unorderable_runs == 0
    assert m_mix_reuse.rounds_to_first_pass_all.prs_counted == 0
    assert m_mix_reuse.rounds_to_first_pass_effective.prs_counted == 0
    assert m_mix_reuse.prs_first_pass_reused == 0

    # 正对照 1：单条 PASS 省略 attempt -> 无同时间戳并列，bucket_1 == 1
    runs_single = tmp_path / "single_pass_missing_attempt"
    runs_single.mkdir()
    _write_run(
        runs_single,
        "p1603-r1",
        pr_number=1603,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=None,
        verdict="PASS",
    )
    m_single = analyze_review_runs(runs_single)
    assert m_single.unorderable_runs == 0
    assert m_single.rounds_to_first_pass_all.prs_counted == 1
    assert m_single.rounds_to_first_pass_all.bucket_1 == 1
    assert m_single.rounds_to_first_pass_effective.prs_counted == 1
    assert m_single.rounds_to_first_pass_effective.bucket_1 == 1

    # 正对照 2：不同时间戳 ts=100 BLOCK(attempt=None) + ts=200 PASS(attempt=None) -> bucket_2 == 1
    runs_diff_ts = tmp_path / "diff_ts_missing_attempt"
    runs_diff_ts.mkdir()
    _write_run(
        runs_diff_ts,
        "p1604-r1",
        pr_number=1604,
        head_sha="a" * 40,
        registered_at_ns=100,
        attempt=None,
        verdict="BLOCK",
    )
    _write_run(
        runs_diff_ts,
        "p1604-r2",
        pr_number=1604,
        head_sha="b" * 40,
        registered_at_ns=200,
        attempt=None,
        verdict="PASS",
    )
    m_diff_ts = analyze_review_runs(runs_diff_ts)
    assert m_diff_ts.unorderable_runs == 0
    assert m_diff_ts.rounds_to_first_pass_all.prs_counted == 1
    assert m_diff_ts.rounds_to_first_pass_all.bucket_2 == 1
    assert m_diff_ts.rounds_to_first_pass_effective.prs_counted == 1
    assert m_diff_ts.rounds_to_first_pass_effective.bucket_2 == 1

    # 正对照 3：同时间戳全为同型 fresh PASS（含缺失 attempt）、严格更早时间戳并列缺失 attempt BLOCK、
    # 以及同时间戳 attempt 均已知且可分出先后 -> 均确定计入
    runs_det = tmp_path / "deterministic_controls"
    runs_det.mkdir()
    # PR 1605：ts=100 双同型 fresh PASS（其中一条 attempt=None）-> 1 轮
    _write_run(runs_det, "p1605-p1", pr_number=1605, head_sha="a" * 40, registered_at_ns=100, attempt=None, verdict="PASS")
    _write_run(runs_det, "p1605-p2", pr_number=1605, head_sha="a" * 40, registered_at_ns=100, attempt=2, verdict="PASS")
    # PR 1606：ts=100 双 BLOCK(attempt=None) + ts=200 PASS(attempt=None) -> 3 轮（早期组求和满足交换律）
    _write_run(runs_det, "p1606-b1", pr_number=1606, head_sha="a" * 40, registered_at_ns=100, attempt=None, verdict="BLOCK")
    _write_run(runs_det, "p1606-b2", pr_number=1606, head_sha="a" * 40, registered_at_ns=100, attempt=None, verdict="BLOCK")
    _write_run(runs_det, "p1606-p3", pr_number=1606, head_sha="b" * 40, registered_at_ns=200, attempt=None, verdict="PASS")
    # PR 1607：同 ts=100 但 attempt 全已知（BLOCK attempt=1 < PASS attempt=2）-> 2 轮
    _write_run(runs_det, "p1607-b1", pr_number=1607, head_sha="a" * 40, registered_at_ns=100, attempt=1, verdict="BLOCK")
    _write_run(runs_det, "p1607-p2", pr_number=1607, head_sha="b" * 40, registered_at_ns=100, attempt=2, verdict="PASS")
    m_det = analyze_review_runs(runs_det)
    assert m_det.unorderable_runs == 0
    assert m_det.rounds_to_first_pass_all.prs_counted == 3
    assert m_det.rounds_to_first_pass_all.bucket_1 == 1
    assert m_det.rounds_to_first_pass_all.bucket_2 == 1
    assert m_det.rounds_to_first_pass_all.bucket_3 == 1
    assert m_det.rounds_to_first_pass_effective.prs_counted == 3
    assert m_det.rounds_to_first_pass_effective.bucket_1 == 1
    assert m_det.rounds_to_first_pass_effective.bucket_2 == 1
    assert m_det.rounds_to_first_pass_effective.bucket_3 == 1


def test_r16_severity_tag_nonblocking_and_mustfix_variants() -> None:
    # Important 2：无连字符/下划线同义词元 nonblocking / non_blocking 与 mustfix / must_fix
    assert classify_finding_heuristic("[P2/nonblocking] 数据丢失", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("[P2/non_blocking] 数据丢失", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("[mustfix/信息] 数据丢失", "blocked") == "blocking_substantive"
    assert classify_finding_heuristic("[must_fix/信息] 数据丢失", "blocked") == "blocking_substantive"

    assert _parse_leading_severity_tag("[P2/nonblocking] 数据丢失") == "non_blocking"
    assert _parse_leading_severity_tag("[P2/non_blocking] 数据丢失") == "non_blocking"
    assert _parse_leading_severity_tag("[non_blocking/P2] 数据丢失") == "non_blocking"
    assert _parse_leading_severity_tag("[P2][nonblocking] 数据丢失") == "non_blocking"
    assert _parse_leading_severity_tag("[P2][non_blocking] 数据丢失") == "non_blocking"
    assert _parse_leading_severity_tag("[mustfix/信息] 数据丢失") == "blocking"
    assert _parse_leading_severity_tag("[must_fix/信息] 数据丢失") == "blocking"
    assert classify_finding_heuristic("non_blocking: 建议后续整理", "blocked") == "non_blocking_or_nit"
    assert classify_finding_heuristic("must_fix: 修复状态分叉", "blocked") == "blocking_substantive"


def test_r16_narrowed_bug_locations_exclude_unrelated_lines() -> None:
    # Important 3：#1904/#1994/#1944 精确收窄至缺陷行本身，剔除无关中间行
    cases = load_cases(CANONICAL_CASES)
    by_id = {c.case_id: c for c in cases}

    case_1904 = by_id["bug-1904-nonce-substring-row-match"]
    assert len(case_1904.bug_locations) == 1
    assert case_1904.bug_locations[0].all_ranges == ((540, 540), (564, 564))

    case_1994 = by_id["bug-1994-review-identity-sweep-gap"]
    assert len(case_1994.bug_locations) == 2
    assert case_1994.bug_locations[0].all_ranges == (
        (1108, 1109),
        (1111, 1113),
        (1143, 1143),
        (1148, 1148),
        (1158, 1158),
    )
    assert case_1994.bug_locations[1].all_ranges == ((69, 70), (83, 83), (87, 87))

    case_1944 = by_id["bug-1944-recover-stale-disk-divergence"]
    assert len(case_1944.bug_locations) == 1
    assert case_1944.bug_locations[0].all_ranges == (
        (910, 910),
        (913, 914),
        (920, 920),
        (923, 923),
        (926, 926),
    )

    # Codex R15 最小反例：仅提交 #1904 中间无关行 552（await holding;），line_tolerance=0 不得命中
    unrelated_552 = score_predictions(
        (case_1904,),
        (
            CasePrediction(
                case_id=case_1904.case_id,
                verdict="BLOCK",
                findings=(
                    PredictedFinding(
                        file=".sandcastle/deployment-acceptance.test.mts",
                        line_start=552,
                        line_end=552,
                        severity="blocking",
                        summary="无关中间行",
                    ),
                ),
            ),
        ),
        line_tolerance=0,
    )
    assert unrelated_552.bug_case_recall == 0.0
    assert unrelated_552.case_details[0].matched_locations == 0

    for exact_line in (540, 564):
        hit = score_predictions(
            (case_1904,),
            (
                CasePrediction(
                    case_id=case_1904.case_id,
                    verdict="BLOCK",
                    findings=(
                        PredictedFinding(
                            file=".sandcastle/deployment-acceptance.test.mts",
                            line_start=exact_line,
                            line_end=exact_line,
                            severity="blocking",
                            summary="精确命中 includes('-14') 缺陷行",
                        ),
                    ),
                ),
            ),
            line_tolerance=0,
        )
        assert hit.bug_case_recall == 1.0, exact_line
        assert hit.case_details[0].matched_locations == 1, exact_line

    # #1994 与 #1944 剔除的无关中间行在 line_tolerance=0 下也不得误命中
    unrelated_1994 = score_predictions(
        (case_1994,),
        (
            CasePrediction(
                case_id=case_1994.case_id,
                verdict="BLOCK",
                findings=(
                    PredictedFinding(
                        file=".sandcastle/deepagents-pilot/pilot1742/external_review.py",
                        line_start=1120,
                        line_end=1120,
                        severity="blocking",
                        summary="无关的读取异常处理行",
                    ),
                    PredictedFinding(
                        file=".sandcastle/deepagents-pilot/pilot1742/github_app.py",
                        line_start=85,
                        line_end=85,
                        severity="blocking",
                        summary="无关的权限正则校验行",
                    ),
                ),
            ),
        ),
        line_tolerance=0,
    )
    assert unrelated_1994.bug_case_recall == 0.0
    assert unrelated_1994.case_details[0].matched_locations == 0

    unrelated_1944 = score_predictions(
        (case_1944,),
        (
            CasePrediction(
                case_id=case_1944.case_id,
                verdict="BLOCK",
                findings=(
                    PredictedFinding(
                        file=".sandcastle/deepagents-pilot/pilot1742/external_review.py",
                        line_start=927,
                        line_end=927,
                        severity="blocking",
                        summary="早退分支之外的 verdict 计算行",
                    ),
                ),
            ),
        ),
        line_tolerance=0,
    )
    assert unrelated_1944.bug_case_recall == 0.0
    assert unrelated_1944.case_details[0].matched_locations == 0
