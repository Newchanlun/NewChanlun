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
            base_sha="1111111",
            head_sha="2222222",
            fix_sha="3333333",
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
            base_sha="4444444",
            head_sha="5555555",
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
            base_sha="6666666",
            head_sha="7777777",
        ),
        EvalCase(
            case_id="clean-two",
            kind="clean",
            title="样例干净 PR 2",
            base_sha="8888888",
            head_sha="9999999",
        ),
    )


def test_canonical_cases_json_valid_and_git_verified() -> None:
    cases = load_cases(CANONICAL_CASES)
    validate_cases(cases, repo_root=REPO_ROOT)

    bug_cases = [c for c in cases if c.kind == "bug"]
    clean_cases = [c for c in cases if c.kind == "clean"]
    assert len(bug_cases) >= 8
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
        base_sha="aaaaaaa",
        head_sha="bbbbbbb",
        bug_locations=(),
    )
    with pytest.raises(EvalValidationError, match="bug_locations 不能为空"):
        validate_cases((empty_bug,))

    dirty_clean = EvalCase(
        case_id="clean-with-loc",
        kind="clean",
        title="干净案不许有定位",
        base_sha="aaaaaaa",
        head_sha="bbbbbbb",
        bug_locations=(
            BugLocation(file="a.py", line_start=1, line_end=2, summary="x", category="y"),
        ),
    )
    with pytest.raises(EvalValidationError, match="bug_locations 必须为空"):
        validate_cases((dirty_clean,))


def test_validate_cases_checks_git_repo_and_line_bounds(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    (repo / "app.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-qm", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    (repo / "app.py").write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-qm", "buggy")
    head_sha = _git(repo, "rev-parse", "HEAD")

    ok_case = EvalCase(
        case_id="ok-git",
        kind="bug",
        title="合法行号",
        base_sha=base_sha,
        head_sha=head_sha,
        bug_locations=(BugLocation(file="app.py", line_start=2, line_end=4, summary="缺陷", category="bug"),),
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

    missing_sha_case = EvalCase(
        case_id="missing-sha",
        kind="clean",
        title="不存在的 SHA",
        base_sha=base_sha,
        head_sha="deadbeefdeadbeef",
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
    assert diff.unchanged_cases == ("clean-one",)

    rev_diff = compare_scores(after, before)
    assert rev_diff.regressed_cases == ("bug-alpha", "bug-beta", "clean-two")


def _write_run(
    runs_dir: Path,
    name: str,
    *,
    pr_number: int,
    head_sha: str,
    registered_at_ns: int,
    attempt: int,
    verdict: str | None,
    reviews: list[dict[str, object]] | None = None,
    receipts: dict[str, dict[str, object]] | None = None,
    reused_from: str | None = None,
) -> Path:
    run_dir = runs_dir / name
    run_dir.mkdir(parents=True)
    target = {
        "pr_number": pr_number,
        "head_sha": head_sha,
        "base_sha": "0" * 40,
        "registered_at_ns": registered_at_ns,
        "attempt": attempt,
    }
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
    # 全量口径首 PASS = 3 轮；有效评审口径（去 FAILED）= 2 轮。
    _write_run(
        runs_dir,
        "p101-r1",
        pr_number=101,
        head_sha="aaaa1111",
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
        head_sha="aaaa1111",
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
        head_sha="bbbb2222",
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
                "result": {"status": "completed", "findings": ["非阻断：可顺手抽取常量"]},
            }
        },
    )

    # PR 102: 单轮 PASS（沿用历史）
    _write_run(
        runs_dir,
        "p102-r1",
        pr_number=102,
        head_sha="cccc3333",
        registered_at_ns=150,
        attempt=1,
        verdict="PASS",
        reused_from="earlier-run",
        reviews=[
            {"model": "kimi-k3.1-pro", "verdict": "PASS"},
            {"model": "claude-opus-5-5", "verdict": "PASS"},
        ],
    )

    # PR 103: 缺 outcome.json 且含损坏 receipt.json
    p103 = _write_run(
        runs_dir,
        "p103-r1",
        pr_number=103,
        head_sha="dddd4444",
        registered_at_ns=400,
        attempt=1,
        verdict=None,
    )
    bad_model_dir = p103 / "claude-opus-5-5"
    bad_model_dir.mkdir()
    (bad_model_dir / "receipt.json").write_text("{broken json", encoding="utf-8")

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
    assert metrics.corrupted_files == ("p103-r1/claude-opus-5-5/receipt.json",)
    assert metrics.verdict_counts == {"BLOCK": 1, "FAILED": 1, "MISSING_OUTCOME": 1, "PASS": 2}
    assert metrics.unique_prs == 3
    assert metrics.prs_with_pass == 2
    assert metrics.prs_without_pass == 1

    # PR 101 = 3 轮，PR 102 = 1 轮 -> 中位数 2.0，均值 2.0
    assert metrics.rounds_to_first_pass_all.bucket_1 == 1
    assert metrics.rounds_to_first_pass_all.bucket_3 == 1
    assert metrics.rounds_to_first_pass_all.median == pytest.approx(2.0)

    # 有效评审口径：PR 101 = 2 轮，PR 102 = 1 轮 -> 均值 1.5
    assert metrics.rounds_to_first_pass_effective.bucket_1 == 1
    assert metrics.rounds_to_first_pass_effective.bucket_2 == 1
    assert metrics.rounds_to_first_pass_effective.mean == pytest.approx(1.5)

    assert metrics.total_findings == 4
    assert metrics.findings_by_receipt_status == {"blocked": 3, "completed": 1}
    assert metrics.finding_heuristic_categories["blocking_substantive"] == 1
    assert metrics.finding_heuristic_categories["style_or_format"] == 1
    assert metrics.finding_heuristic_categories["non_blocking_or_nit"] == 2
    # p101-r2 的 2 条非 Nit 阻断发现随后在 p101-r3 不同 head 转 PASS
    assert metrics.subsequent_head_pass_total_block_findings == 2
    assert metrics.subsequent_head_pass_inferred_fixed == 2
    assert metrics.subsequent_head_pass_inferred_rate == pytest.approx(1.0)

    # 显式台账 4 类已定性各占 25%
    assert metrics.disposition_total == 5
    for key in ("fixed", "false_positive", "intentional", "not_important"):
        assert metrics.disposition_resolved_rates[key] == pytest.approx(0.25)

    md = render_baseline_markdown(metrics)
    assert "收据实测事实" in md
    assert "正则/启发式分类" in md
    assert "显式去向台账统计" in md


def test_cli_end_to_end_and_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cases_path = tmp_path / "cases.json"
    cases_payload = {
        "schema_version": SCHEMA_VERSION,
        "cases": [
            {
                "case_id": "b1",
                "kind": "bug",
                "title": "bug 1",
                "base_sha": "1111111",
                "head_sha": "2222222",
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
                "base_sha": "3333333",
                "head_sha": "4444444",
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
    assert cmp_data["bug_case_recall_delta"] == pytest.approx(1.0)

    # 非法输入返回退出码 2（fail-closed）
    assert main(["validate-cases", "--cases", str(tmp_path / "missing.json")]) == 2
