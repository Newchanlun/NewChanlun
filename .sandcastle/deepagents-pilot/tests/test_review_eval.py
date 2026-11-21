"""#1931 回滚/事故评测集与外部审查基线统计离线单测（不依赖仓外卷）。"""

from __future__ import annotations

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
    EvalValidationError,
    PredictedFinding,
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
    attempt: int,
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
        "attempt": attempt,
    }
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
