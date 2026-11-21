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
    compare_scores,
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


def test_canonical_cases_json_valid_and_git_verified() -> None:
    cases = load_cases(CANONICAL_CASES)
    validate_cases(cases, repo_root=REPO_ROOT)

    bug_cases = [c for c in cases if c.kind == "bug"]
    clean_cases = [c for c in cases if c.kind == "clean"]
    assert len(bug_cases) >= 9
    assert len(clean_cases) >= 5
    assert all(len(c.bug_locations) >= 1 for c in bug_cases)
    assert all(len(c.bug_locations) == 0 for c in clean_cases)


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
    # 拒绝短 SHA（7 位、39 位）与大写 SHA
    for bad_sha in ("1234567", "a" * 39, "A" * 40, "a" * 39 + "B"):
        bad_case = EvalCase(
            case_id="bad-sha",
            kind="clean",
            title="非法 SHA",
            base_sha=bad_sha,
            head_sha=SHA_B,
        )
        with pytest.raises(EvalValidationError, match="40 位小写"):
            validate_cases((bad_case,))

        bad_json = tmp_path / f"bad_{len(bad_sha)}_{bad_sha[0]}.json"
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
    assert partial.missing_cases == 2
    assert partial.coverage_rate == pytest.approx(0.5)
    # clean-one 被 BLOCK，clean-two 缺失不充当零误报分母 -> clean FP rate = 1/1 = 1.0
    assert partial.clean_false_positive_cases == 1
    assert partial.clean_false_positive_rate == pytest.approx(1.0)
    by_id = {d.case_id: d for d in partial.case_details}
    assert by_id["bug-beta"].verdict == "MISSING"
    assert by_id["clean-two"].verdict == "MISSING"

    # 若没有任何已评 clean 案，clean_false_positive_rate 为 0.0 且 coverage_rate 暴露缺口
    no_clean_partial = score_predictions(cases, (partial_preds[0],), allow_partial=True)
    assert no_clean_partial.clean_false_positive_rate == pytest.approx(0.0)
    assert no_clean_partial.coverage_rate == pytest.approx(0.25)


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
    assert metrics.finding_heuristic_categories["style_or_format"] == 1
    assert metrics.finding_heuristic_categories["non_blocking_or_nit"] == 3
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

    metrics = analyze_review_runs(runs_dir)
    assert metrics.unorderable_runs == 1
    # PR 201(1) + PR 202(2) + PR 203(1) = 4 条不可判定；仅 PR 204(1) 可判定且未推定已修
    assert metrics.subsequent_head_pass_undeterminable_findings == 4
    assert metrics.subsequent_head_pass_total_block_findings == 1
    assert metrics.subsequent_head_pass_inferred_fixed == 0
    assert metrics.subsequent_head_pass_inferred_rate == pytest.approx(0.0)


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
    assert cmp_data["bug_case_recall_delta"] == pytest.approx(1.0)

    # 缺漏案例在默认模式下返回退出码 2，显式 --allow-partial 返回 0
    pred_partial = tmp_path / "pred_partial.json"
    pred_partial.write_text(json.dumps([{"case_id": "b1", "verdict": "PASS", "findings": []}]), encoding="utf-8")
    assert main(["score", "--cases", str(cases_path), "--predictions", str(pred_partial)]) == 2
    assert main(["score", "--cases", str(cases_path), "--predictions", str(pred_partial), "--allow-partial"]) == 0

    # 非法输入返回退出码 2（fail-closed）
    assert main(["validate-cases", "--cases", str(tmp_path / "missing.json")]) == 2
