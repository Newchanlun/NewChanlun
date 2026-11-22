from __future__ import annotations

import dataclasses
import itertools
import json
from collections.abc import Sequence

import pytest

from pilot1742.review_convergence import (
    COMMENT_MARKER_PREFIX,
    MAX_AUTO_ROUNDS,
    NON_CONVERGENT_DESCRIPTION,
    AuthorReply,
    ConvergenceError,
    FinderBatch,
    Finding,
    RenderedComment,
    ReviewPanel,
    RoundCandidates,
    RoundDecision,
    RoundHistoryEntry,
    RoundOutcome,
    RoundPlan,
    Severity,
    VerificationVerdict,
    VerifiedFinding,
    VerifiedRound,
    _clip_formatted_inline,
    _contains_raw_html_outside_code,
    _escape_unmatched_backticks,
    _extract_code_span_text,
    _format_code_location,
    _format_inline_markdown_field,
    _format_nested_fenced_code,
    _has_visible_gfm_text,
    _leaves_html_suppressed,
    _normalize_fingerprint_text,
    _parse_commonmark_blocks,
    _render_compact_new_blocking_item,
    _render_compact_non_blocking_item,
    _render_minimal_blocking_item,
    _render_new_blocking_item,
    _render_non_blocking_item,
    _render_prior_blocking_summary,
    _single_line,
    _tokenize_inline_clip_segments,
    accept_quick_pass_findings,
    bind_author_replies,
    build_round_candidates,
    evaluate_round,
    fingerprint,
    infer_model_family,
    is_blocking_finding,
    merge_and_dedupe_findings,
    parse_comment_marker,
    parse_finder_output,
    parse_severity,
    parse_verifier_output,
    parse_wontfix_replies,
    plan_next_round,
    render_findings_comment,
    select_postable_findings,
)

BASE_SHA = "a" * 40
HEAD_1 = "1" * 40
HEAD_2 = "2" * 40
HEAD_3 = "3" * 40
HEAD_4 = "4" * 40

DEFAULT_PANEL = ReviewPanel(
    finder_models=("gpt-6-astra", "gpt-6.1-sol"),
    verifier_model="claude-opus-5-5",
    require_verifier=True,
)


def _finding(
    *,
    severity: Severity = Severity.IMPORTANT,
    file: str = "pilot1742/demo.py",
    line: int | None = 42,
    category: str = "空值解引用",
    failure_scenario: str = "配置缺失时直接访问属性触发 AttributeError",
    evidence: str = "第 42 行未判空直接取 .strip()",
    class_scope: str | None = None,
    source_models: tuple[str, ...] = ("gpt-6-astra",),
) -> Finding:
    return Finding(
        severity=severity,
        file=file,
        line=line,
        category=category,
        failure_scenario=failure_scenario,
        evidence=evidence,
        class_scope=class_scope,
        source_models=source_models,
    )


def _batches_for_panel(
    findings: Sequence[Finding] = (),
    *,
    panel: ReviewPanel = DEFAULT_PANEL,
    round_number: int = 1,
    head_sha: str | None = None,
) -> tuple[FinderBatch, ...]:
    sha = head_sha or (HEAD_1 if round_number == 1 else f"{round_number}" * 40)
    by_model: dict[str, list[Finding]] = {}
    for item in findings:
        if len(item.source_models) != 1:
            raise AssertionError(f"helper 需要单来源 Finding，实际收到 {item.source_models!r}")
        by_model.setdefault(item.source_models[0], []).append(item)
    used_counts: dict[str, int] = {}
    batches: list[FinderBatch] = []
    for idx, model in enumerate(panel.finder_models, start=1):
        count = used_counts.get(model, 0)
        used_counts[model] = count + 1
        batch_findings = tuple(by_model.pop(model, [])) if count == 0 else ()
        batches.append(
            FinderBatch(
                model=model,
                session_id=f"r{round_number}-slot-{idx}",
                head_sha=sha,
                findings=batch_findings,
            )
        )
    if by_model:
        raise AssertionError(f"helper 收到不在 panel.finder_models 中的发现来源：{list(by_model)!r}")
    return tuple(batches)


def _candidates(
    findings: Sequence[Finding] = (),
    *,
    round_number: int = 1,
    head_sha: str | None = None,
    panel: ReviewPanel = DEFAULT_PANEL,
    history: Sequence[RoundHistoryEntry] = (),
    finder_batches: Sequence[FinderBatch] | None = None,
) -> RoundCandidates:
    sha = head_sha or (HEAD_1 if round_number == 1 else f"{round_number}" * 40)
    batches = (
        tuple(finder_batches)
        if finder_batches is not None
        else _batches_for_panel(findings, panel=panel, round_number=round_number, head_sha=sha)
    )
    return RoundCandidates(
        round_number=round_number,
        head_sha=sha,
        panel=panel,
        finder_batches=batches,
        history=tuple(history),
    )


def _verifier_payload(
    candidates: RoundCandidates,
    verdicts: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "round_number": candidates.round_number,
        "head_sha": candidates.head_sha,
        "verdicts": verdicts,
    }


def _verified(
    finding: Finding,
    verdict: VerificationVerdict = VerificationVerdict.CONFIRMED,
    *,
    verifier_model: str = "claude-opus-5-5",
    verifier_evidence: str = "核实第 42 行确实未校验 None",
    round_number: int = 1,
    head_sha: str | None = None,
    author_reply: AuthorReply | None = None,
) -> VerifiedFinding:
    sha = head_sha or (HEAD_1 if round_number == 1 else f"{round_number}" * 40)
    return VerifiedFinding(
        finding=finding,
        verdict=verdict,
        verifier_model=verifier_model,
        verifier_evidence=verifier_evidence,
        round_number=round_number,
        head_sha=sha,
        author_reply=author_reply,
    )


def _verified_round(
    verdicts: Sequence[VerifiedFinding],
    *,
    round_number: int = 1,
    head_sha: str | None = None,
    panel: ReviewPanel = DEFAULT_PANEL,
    history: Sequence[RoundHistoryEntry] = (),
) -> VerifiedRound:
    sha = head_sha or (HEAD_1 if round_number == 1 else f"{round_number}" * 40)
    prior_ids = (
        frozenset(f.finding_id for f in history[-1].unresolved_important)
        if history and history[-1].outcome != RoundOutcome.PASS
        else frozenset()
    )
    current_findings = [vf.finding for vf in verdicts if vf.finding.finding_id not in prior_ids]
    candidates = _candidates(
        current_findings,
        round_number=round_number,
        head_sha=sha,
        panel=panel,
        history=history,
    )
    aligned_verdicts = tuple(
        VerifiedFinding(
            finding=vf.finding,
            verdict=vf.verdict,
            verifier_model=vf.verifier_model,
            verifier_evidence=vf.verifier_evidence,
            round_number=round_number,
            head_sha=sha,
            author_reply=vf.author_reply,
            related_reply_keys=vf.related_reply_keys,
        )
        for vf in verdicts
    )
    return VerifiedRound(candidates=candidates, verdicts=aligned_verdicts)


# ── 1. 分级、指纹与发现合并（含全排列顺序无关性） ────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Important", Severity.IMPORTANT),
        ("important", Severity.IMPORTANT),
        ("重要", Severity.IMPORTANT),
        ("Nit", Severity.NIT),
        ("nit", Severity.NIT),
        ("细节", Severity.NIT),
        ("Pre-existing", Severity.PRE_EXISTING),
        ("pre-existing", Severity.PRE_EXISTING),
        ("原本就有", Severity.PRE_EXISTING),
        ("  重要  ", Severity.IMPORTANT),
    ],
)
def test_parse_severity_accepts_english_and_chinese_aliases(raw: str, expected: Severity) -> None:
    assert parse_severity(raw) is expected


@pytest.mark.parametrize("raw", ["", "   ", "critical", "high", "minor", "blocker", None, 123])
def test_parse_severity_rejects_invalid_values(raw: object) -> None:
    with pytest.raises(ConvergenceError):
        parse_severity(raw)


def test_fingerprint_normalizes_path_whitespace_and_case() -> None:
    fp1 = fingerprint(
        "./pilot1742\\sub//a.py",
        "  Race  Condition ",
        "\r\nConcurrent Write loses update\r\n",
    )
    fp2 = fingerprint("pilot1742/sub/a.py", "Race Condition", "Concurrent Write loses update")
    fp3 = fingerprint("pilot1742/sub/b.py", "Race Condition", "Concurrent Write loses update")
    fp_case = fingerprint("pilot1742/sub/a.py", "race condition", "Concurrent Write loses update")
    assert fp1 == fp2
    assert len(fp1) == 16
    assert all(c in "0123456789abcdef" for c in fp1)
    assert fp1 != fp3
    assert fp1 != fp_case


def test_parse_finder_output_strict_validation() -> None:
    payload = {
        "findings": [
            {
                "severity": "重要",
                "file": "./pilot1742/a.py",
                "line": 12,
                "category": "越界访问",
                "failure_scenario": "空列表取首元素抛 IndexError",
                "evidence": "a.py:12 直接取 items[0]",
                "class_scope": "同类解析器共 3 处",
            },
            {
                "severity": "Nit",
                "file": "pilot1742/b.py",
                "line": None,
                "category": "命名不一致",
                "failure_scenario": "字段名与文档不符易误解",
                "evidence": "b.py 使用了旧别名",
            },
        ]
    }
    findings = parse_finder_output(payload, source_model="gpt-6-astra")
    assert len(findings) == 2
    assert findings[0].severity is Severity.IMPORTANT
    assert findings[0].file == "pilot1742/a.py"
    assert findings[0].source_models == ("gpt-6-astra",)
    assert findings[0].class_scope == "同类解析器共 3 处"
    assert findings[1].severity is Severity.NIT
    assert findings[1].line is None


@pytest.mark.parametrize(
    "bad_payload",
    [
        {},
        {"findings": "not-a-list"},
        {"findings": ["not-a-dict"]},
        {"findings": [{"severity": "Important", "file": "", "category": "c", "failure_scenario": "s", "evidence": "e"}]},
        {"findings": [{"severity": "Important", "file": "a.py", "category": " ", "failure_scenario": "s", "evidence": "e"}]},
        {"findings": [{"severity": "Important", "file": "a.py", "category": "c", "failure_scenario": "", "evidence": "e"}]},
        {"findings": [{"severity": "Important", "file": "a.py", "category": "c", "failure_scenario": "s", "evidence": ""}]},
        {"findings": [{"severity": "Blocker", "file": "a.py", "category": "c", "failure_scenario": "s", "evidence": "e"}]},
        {"findings": [{"severity": "Important", "file": "a.py", "line": 0, "category": "c", "failure_scenario": "s", "evidence": "e"}]},
        {"findings": [{"severity": "Important", "file": "a.py", "line": True, "category": "c", "failure_scenario": "s", "evidence": "e"}]},
    ],
)
def test_parse_finder_output_fail_closed(bad_payload: dict) -> None:
    with pytest.raises(ConvergenceError):
        parse_finder_output(bad_payload, source_model="gpt-6-astra")


def test_merge_and_dedupe_prefers_stricter_severity_and_richer_details() -> None:
    f_nit = _finding(
        severity=Severity.NIT,
        file="./pilot1742/x.py",
        line=20,
        category="Error Handling",
        failure_scenario="Swallows IOError silently",
        evidence="第 20 行吞错",
        class_scope=None,
        source_models=("gpt-6.1-sol",),
    )
    f_imp = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/x.py",
        line=18,
        category="Error  Handling",
        failure_scenario="Swallows IOError silently\r\n",
        evidence="第 18-24 行捕获 OSError 后返回空字典，导致状态丢失",
        class_scope="pilot1742 下其余 2 个持久化读取函数存在同类问题",
        source_models=("gpt-6-astra",),
    )
    f_pre = _finding(
        severity=Severity.PRE_EXISTING,
        file="pilot1742/y.py",
        line=5,
        category="旧接口",
        failure_scenario="历史遗留无超时调用",
        evidence="y.py:5 原本就未设 timeout",
        source_models=("gpt-6-astra",),
    )
    f_only_nit = _finding(
        severity=Severity.NIT,
        file="pilot1742/z.py",
        line=9,
        category="文案",
        failure_scenario="提示语错别字",
        evidence="z.py:9 拼写笔误",
        source_models=("gpt-6.1-sol",),
    )

    merged = merge_and_dedupe_findings(
        [
            ("gpt-6.1-sol", [f_nit, f_only_nit]),
            ("gpt-6-astra", [f_imp, f_pre]),
        ]
    )
    assert len(merged) == 3
    assert [f.severity for f in merged] == [Severity.IMPORTANT, Severity.PRE_EXISTING, Severity.NIT]
    top = merged[0]
    assert top.file == "pilot1742/x.py"
    assert top.line == 18
    assert top.source_models == ("gpt-6-astra", "gpt-6.1-sol")
    assert top.evidence == f_imp.evidence
    assert top.class_scope == f_imp.class_scope


def test_merge_and_dedupe_is_completely_order_invariant_across_all_permutations() -> None:
    # Important 无行号 + 两条 Nit 分别在 9/20 行：所有 6 种排列必须归约为完全相同的 Finding（line=9）
    f_imp_no_line = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/order.py",
        line=None,
        category="Race Condition",
        failure_scenario="Shared cache mutated without lock",
        evidence="无锁写入",
        class_scope="全局缓存",
        source_models=("gpt-6-astra",),
    )
    f_nit_9 = _finding(
        severity=Severity.NIT,
        file="./pilot1742/order.py",
        line=9,
        category="  Race  Condition ",
        failure_scenario="Shared cache mutated without lock\r\n",
        evidence="第 9 行直接修改共享字典导致并发竞态丢更新",
        class_scope=None,
        source_models=("gpt-6.1-sol",),
    )
    f_nit_20 = _finding(
        severity=Severity.NIT,
        file="pilot1742//order.py",
        line=20,
        category="Race   Condition",
        failure_scenario="\nShared cache mutated without lock\n",
        evidence="第 20 行同样访问",
        class_scope="pilot1742 缓存模块共 3 处无锁修改",
        source_models=("kimi-k3.1-pro",),
    )
    items = [
        ("gpt-6-astra", [f_imp_no_line]),
        ("gpt-6.1-sol", [f_nit_9]),
        ("kimi-k3.1-pro", [f_nit_20]),
    ]

    results = [merge_and_dedupe_findings(list(perm)) for perm in itertools.permutations(items)]
    expected = results[0]
    assert len(expected) == 1
    assert expected[0].severity is Severity.IMPORTANT
    assert expected[0].line == 9
    assert expected[0].category == "Race Condition"
    assert expected[0].failure_scenario == "Shared cache mutated without lock"
    assert expected[0].evidence == f_nit_9.evidence
    assert expected[0].class_scope == f_nit_20.class_scope
    assert expected[0].source_models == ("gpt-6-astra", "gpt-6.1-sol", "kimi-k3.1-pro")
    for res in results[1:]:
        assert res == expected

    # 当最高等级成员本身有行号时，优先取最高等级成员的最小非空行号（而非更低等级的更小行号）
    f_imp_line_25 = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/order.py",
        line=25,
        category="Race Condition",
        failure_scenario="Shared cache mutated without lock",
        evidence="第 25 行",
        source_models=("gpt-6-astra",),
    )
    f_imp_line_15 = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/order.py",
        line=15,
        category="Race Condition",
        failure_scenario="Shared cache mutated without lock",
        evidence="第 15 行",
        source_models=("gpt-6.1-sol",),
    )
    top_line_items = [
        ("gpt-6-astra", [f_imp_line_25]),
        ("gpt-6.1-sol", [f_imp_line_15]),
        ("kimi-k3.1-pro", [f_nit_9]),
    ]
    top_line_results = [merge_and_dedupe_findings(list(perm)) for perm in itertools.permutations(top_line_items)]
    assert top_line_results[0][0].line == 15
    for res in top_line_results[1:]:
        assert res == top_line_results[0]


def test_merge_and_dedupe_pre_existing_beats_nit() -> None:
    f_nit = _finding(severity=Severity.NIT, file="a.py", category="c", failure_scenario="s", evidence="short")
    f_pre = _finding(severity=Severity.PRE_EXISTING, file="a.py", category="c", failure_scenario="s", evidence="more detailed")
    merged = merge_and_dedupe_findings([("gpt-6-astra", [f_nit]), ("gpt-6.1-sol", [f_pre])])
    assert len(merged) == 1
    assert merged[0].severity is Severity.PRE_EXISTING


# ── 2. 模型家族、审查面板强绑定与快审直通入口 ───────────────────────────────


@pytest.mark.parametrize(
    ("model", "expected_family"),
    [
        ("claude-opus-5-5", "anthropic"),
        ("anthropic/claude-sonnet-4-6", "anthropic"),
        ("gpt-6.1-sol", "openai"),
        ("gpt-6-astra", "openai"),
        ("openai/codex-mini", "openai"),
        ("kimi-k3.1-pro", "moonshot"),
        ("moonshot/kimi-latest", "moonshot"),
        ("gemini-4-neon", "google"),
        ("google/gemini-2.5-pro", "google"),
    ],
)
def test_infer_model_family_recognizes_major_families(model: str, expected_family: str) -> None:
    assert infer_model_family(model) == expected_family


@pytest.mark.parametrize("bad_model", ["", "   ", "mystery-model-9", "local-custom-llm"])
def test_infer_model_family_rejects_unknown_models(bad_model: str) -> None:
    with pytest.raises(ConvergenceError):
        infer_model_family(bad_model)


def test_review_panel_allows_dual_same_family_finders_with_cross_family_verifier() -> None:
    panel = ReviewPanel(
        finder_models=("gpt-6-astra", "gpt-6-astra"),
        verifier_model="claude-opus-5-5",
        require_verifier=True,
    )
    assert panel.finder_families == frozenset({"openai"})
    assert panel.verifier_family == "anthropic"


def test_review_panel_rejects_same_family_verifier_or_missing_finder() -> None:
    with pytest.raises(ConvergenceError):
        ReviewPanel(finder_models=("gpt-6-astra", "gpt-6.1-sol"), verifier_model="openai/codex-latest")
    with pytest.raises(ConvergenceError):
        ReviewPanel(finder_models=("gpt-6-astra",), verifier_model="claude-opus-5-5", require_verifier=True)
    with pytest.raises(ConvergenceError):
        ReviewPanel(finder_models=("gpt-6-astra", "gpt-6-astra"), verifier_model=None, require_verifier=True)
    with pytest.raises(ConvergenceError):
        ReviewPanel(finder_models=("gpt-6-astra", "claude-opus-5-5"), verifier_model="anthropic/claude-sonnet-4-6")


def test_quick_pass_explicit_entry_and_panel_isolation() -> None:
    fast_panel = ReviewPanel(finder_models=("gpt-6-astra",), verifier_model=None, require_verifier=False)
    assert fast_panel.verifier_family is None
    assert fast_panel.finder_families == frozenset({"openai"})

    f_imp = _finding(source_models=("gpt-6-astra",))
    fast_candidates = _candidates([f_imp], panel=fast_panel)
    accepted_round = accept_quick_pass_findings(fast_candidates)
    assert isinstance(accepted_round, VerifiedRound)
    assert len(accepted_round.verdicts) == 1
    assert accepted_round.verdicts[0].verdict is VerificationVerdict.CONFIRMED
    assert accepted_round.verdicts[0].is_blocking is True
    assert accepted_round.verdicts[0].verifier_model == "quick-pass:gpt-6-astra"

    # require_verifier=True 的面板禁止走快审直通入口
    with pytest.raises(ConvergenceError):
        accept_quick_pass_findings(_candidates([f_imp], panel=DEFAULT_PANEL))

    # 快审发现来源不在 panel.finder_models 中 -> 在 FinderBatch / RoundCandidates 构造期即拒绝
    foreign_finding = _finding(source_models=("claude-opus-5-5",))
    with pytest.raises(ConvergenceError):
        FinderBatch(model="gpt-6-astra", session_id="s1", head_sha=HEAD_1, findings=(foreign_finding,))
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=1,
            head_sha=HEAD_1,
            panel=fast_panel,
            finder_batches=(
                FinderBatch(model="claude-opus-5-5", session_id="s1", head_sha=HEAD_1, findings=(foreign_finding,)),
            ),
        )

    # require_verifier=False 的面板禁止混入 parse_verifier_output
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                fast_candidates,
                [{"finding_id": f_imp.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}],
            ),
            fast_candidates,
            verifier_model="claude-opus-5-5",
        )

    # 快审路径若显式提供核实者，仍不得与 finder 同家族
    with pytest.raises(ConvergenceError):
        ReviewPanel(finder_models=("gpt-6-astra",), verifier_model="gpt-6.1-sol", require_verifier=False)


# ── 3. 核实者输出校验、同家族拒收、无回复 wontfix 拒收与唯一阻断判据 ─────────


def test_parse_verifier_output_enforces_exact_candidate_bijection_and_panel_binding() -> None:
    f_imp = _finding(severity=Severity.IMPORTANT, file="a.py", category="c1", failure_scenario="s1")
    f_nit = _finding(severity=Severity.NIT, file="b.py", category="c2", failure_scenario="s2")
    f_pre = _finding(severity=Severity.PRE_EXISTING, file="c.py", category="c3", failure_scenario="s3")

    cand = _candidates([f_imp, f_nit, f_pre])
    payload = _verifier_payload(
        cand,
        [
            {"finding_id": f_nit.finding_id, "verdict": "confirmed", "verifier_evidence": "b.py 确实命名不一致"},
            {"finding_id": f_imp.finding_id, "verdict": "confirmed", "verifier_evidence": "a.py 确实触发异常"},
            {"finding_id": f_pre.finding_id, "verdict": "confirmed", "verifier_evidence": "c.py 历史遗留"},
        ],
    )
    verified_round = parse_verifier_output(
        payload,
        cand,
        verifier_model="claude-opus-5-5",
    )
    assert isinstance(verified_round, VerifiedRound)
    verified = verified_round.verdicts
    assert [v.finding.finding_id for v in verified] == [f_imp.finding_id, f_pre.finding_id, f_nit.finding_id]
    assert is_blocking_finding(verified[0]) is True
    assert is_blocking_finding(verified[1]) is False
    assert is_blocking_finding(verified[2]) is False

    # 拒绝直接传入裸 Finding 列表绕过 RoundCandidates 类型边界
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            payload,
            [f_imp, f_nit, f_pre],  # type: ignore[arg-type]
            verifier_model="claude-opus-5-5",
        )


def test_parse_verifier_output_rejects_same_family_candidate_and_mismatched_panel_verifier() -> None:
    # 即使 panel 本身合法，若某个候选发现实际来自与 verifier 同家族的模型，FinderBatch/RoundCandidates 构造期即拒收
    f_same_family = _finding(
        file="a.py",
        category="c1",
        failure_scenario="s1",
        source_models=("claude-sonnet-4-6",),
    )
    with pytest.raises(ConvergenceError):
        FinderBatch(model="gpt-6-astra", session_id="s1", head_sha=HEAD_1, findings=(f_same_family,))
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=1,
            head_sha=HEAD_1,
            panel=DEFAULT_PANEL,
            finder_batches=(
                FinderBatch(model="claude-sonnet-4-6", session_id="s1", head_sha=HEAD_1, findings=(f_same_family,)),
                FinderBatch(model="gpt-6.1-sol", session_id="s2", head_sha=HEAD_1, findings=()),
            ),
        )

    # 候选发现仅含占位符或空 source_models 也不允许绕过异家族与面板归属检查
    f_no_source = _finding(file="a.py", category="c1", failure_scenario="s1", source_models=())
    with pytest.raises(ConvergenceError):
        FinderBatch(model="gpt-6-astra", session_id="s1", head_sha=HEAD_1, findings=(f_no_source,))
    with pytest.raises(ConvergenceError):
        RoundHistoryEntry(
            1,
            HEAD_1,
            frozenset({f_no_source.finding_id}),
            (f_no_source,),
            panel=DEFAULT_PANEL,
            finder_session_ids=frozenset({"r1-s1", "r1-s2"}),
        )

    f_only_placeholder = _finding(file="a.py", category="c1", failure_scenario="s1", source_models=("prior-round",))
    with pytest.raises(ConvergenceError):
        FinderBatch(model="gpt-6-astra", session_id="s1", head_sha=HEAD_1, findings=(f_only_placeholder,))
    with pytest.raises(ConvergenceError):
        RoundHistoryEntry(
            1,
            HEAD_1,
            frozenset({f_only_placeholder.finding_id}),
            (f_only_placeholder,),
            panel=DEFAULT_PANEL,
            finder_session_ids=frozenset({"r1-s1", "r1-s2"}),
        )

    # 跨轮 carry-over 时 build_round_candidates 必须完整保留原有真实 source_models，防新轮换用同家族核实者
    f_prior_from_claude = _finding(
        file="carry.py",
        category="carry",
        failure_scenario="old bug",
        source_models=("claude-opus-5-5", "kimi-k3.1-pro"),
    )
    r1_claude_kimi_panel = ReviewPanel(
        finder_models=("claude-opus-5-5", "kimi-k3.1-pro"),
        verifier_model="gemini-4-neon",
        require_verifier=True,
    )
    history1 = (
        RoundHistoryEntry(
            1,
            HEAD_1,
            frozenset({f_prior_from_claude.finding_id}),
            (f_prior_from_claude,),
            panel=r1_claude_kimi_panel,
            finder_session_ids=frozenset({"r1-ck-1", "r1-ck-2"}),
        ),
    )
    plan2 = plan_next_round(BASE_SHA, HEAD_2, history1)
    empty_r2_batches = _batches_for_panel([], panel=DEFAULT_PANEL, round_number=2, head_sha=HEAD_2)
    # 若新轮面板核实者为 claude（与历史来源同家族），build_round_candidates 即立刻拒绝
    with pytest.raises(ConvergenceError):
        build_round_candidates(
            round_number=plan2.round_number,
            head_sha=plan2.diff_head_sha,
            panel=DEFAULT_PANEL,
            finder_batches=empty_r2_batches,
            history=plan2.history,
        )
    # 换用异家族核实者（gemini）时，build_round_candidates 合法保留原有全部真实 source_models
    gemini_verifier_panel = ReviewPanel(
        finder_models=("gpt-6-astra", "gpt-6.1-sol"),
        verifier_model="gemini-4-neon",
        require_verifier=True,
    )
    candidates2 = build_round_candidates(
        round_number=plan2.round_number,
        head_sha=plan2.diff_head_sha,
        panel=gemini_verifier_panel,
        finder_batches=_batches_for_panel([], panel=gemini_verifier_panel, round_number=2, head_sha=HEAD_2),
        history=plan2.history,
    )
    assert candidates2.findings[0].source_models == ("claude-opus-5-5", "kimi-k3.1-pro")

    # verifier_model 与 panel.verifier_model 不一致 -> 拒收
    f_ok = _finding(source_models=("gpt-6-astra",))
    cand_ok = _candidates([f_ok])
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand_ok,
                [{"finding_id": f_ok.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}],
            ),
            cand_ok,
            verifier_model="gemini-4-neon",
        )


def test_parse_verifier_output_binds_candidate_sources_to_panel_and_allows_prior_important() -> None:
    panel = ReviewPanel(
        finder_models=("gpt-6.1-sol", "gpt-6.1-sol"),
        verifier_model="claude-opus-5-5",
        require_verifier=True,
    )

    # 复审反例：面板为双 gpt-6.1-sol + claude-opus-5-5，面板外 gemini-2.5-pro 本轮候选必须立即拒绝
    f_foreign = _finding(
        file="pilot1742/foreign.py",
        line=12,
        category="面板外来源",
        failure_scenario="来源模型不在当前审查面板 finder_models 中",
        source_models=("gemini-2.5-pro",),
    )
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=1,
            head_sha=HEAD_1,
            panel=panel,
            finder_batches=(
                FinderBatch(model="gemini-2.5-pro", session_id="s1", head_sha=HEAD_1, findings=(f_foreign,)),
                FinderBatch(model="gpt-6.1-sol", session_id="s2", head_sha=HEAD_1, findings=()),
            ),
        )

    # 混合来源（含面板外模型）同样在 FinderBatch 构造期即拒绝
    f_mixed_foreign = _finding(
        file="pilot1742/mixed.py",
        line=18,
        category="混合来源",
        failure_scenario="含面板外来源模型",
        source_models=("gpt-6.1-sol", "gemini-2.5-pro"),
    )
    with pytest.raises(ConvergenceError):
        FinderBatch(model="gpt-6.1-sol", session_id="s1", head_sha=HEAD_1, findings=(f_mixed_foreign,))

    # 跨轮继承的 unresolved_prior_important 通过 history 进入 RoundCandidates.prior_important，仍强制异家族
    f_prior_kimi = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/prior_carry.py",
        line=33,
        category="跨轮遗留",
        failure_scenario="前轮由 kimi 发现的阻断缺陷",
        source_models=("kimi-k3.1-pro",),
    )
    r1_kimi_panel = ReviewPanel(
        finder_models=("kimi-k3.1-pro", "kimi-k3.1-pro"),
        verifier_model="claude-opus-5-5",
        require_verifier=True,
    )
    history1 = (
        RoundHistoryEntry(
            1,
            HEAD_1,
            frozenset({f_prior_kimi.finding_id}),
            (f_prior_kimi,),
            panel=r1_kimi_panel,
            finder_session_ids=frozenset({"r1-kimi-1", "r1-kimi-2"}),
        ),
    )
    plan2 = plan_next_round(BASE_SHA, HEAD_2, history1)
    assert plan2.prior_important_sources == {f_prior_kimi.finding_id: frozenset({"kimi-k3.1-pro"})}
    with pytest.raises(TypeError):
        plan2.prior_important_sources["tamper"] = frozenset({"gemini-2.5-pro"})  # type: ignore[index]

    r2_empty = _batches_for_panel([], panel=panel, round_number=2, head_sha=HEAD_2)
    candidates2 = build_round_candidates(
        round_number=plan2.round_number,
        head_sha=plan2.diff_head_sha,
        panel=panel,
        finder_batches=r2_empty,
        history=plan2.history,
    )
    assert isinstance(candidates2, RoundCandidates)
    verified_prior = parse_verifier_output(
        _verifier_payload(
            candidates2,
            [{"finding_id": f_prior_kimi.finding_id, "verdict": "confirmed", "verifier_evidence": "仍存在"}],
        ),
        candidates2,
        verifier_model="claude-opus-5-5",
    )
    assert len(verified_prior.verdicts) == 1
    assert verified_prior.verdicts[0].finding.finding_id == f_prior_kimi.finding_id

    # 若 verifier 与历史 finder 同家族，build_round_candidates 与直接构造 RoundCandidates 均必须拒收
    kimi_verifier_panel = ReviewPanel(
        finder_models=("gpt-6.1-sol", "gpt-6.1-sol"),
        verifier_model="kimi-k3.1-pro",
        require_verifier=True,
    )
    with pytest.raises(ConvergenceError):
        build_round_candidates(
            round_number=plan2.round_number,
            head_sha=plan2.diff_head_sha,
            panel=kimi_verifier_panel,
            finder_batches=r2_empty,
            history=plan2.history,
        )
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=2,
            head_sha=HEAD_2,
            panel=kimi_verifier_panel,
            finder_batches=r2_empty,
            history=history1,
        )

    # 非 Important 发现不得进入 RoundHistoryEntry.unresolved_important
    f_foreign_nit = _finding(
        severity=Severity.NIT,
        file="pilot1742/foreign_nit.py",
        line=5,
        category="面板外 Nit",
        failure_scenario="非阻断项不得走 prior_important",
        source_models=("gemini-2.5-pro",),
    )
    with pytest.raises(ConvergenceError):
        RoundHistoryEntry(
            1,
            HEAD_1,
            frozenset({f_foreign_nit.finding_id}),
            (f_foreign_nit,),
            panel=panel,
            finder_session_ids=frozenset({"r1-s1", "r1-s2"}),
        )


def test_round_candidates_blocks_retired_model_tampering_in_new_round() -> None:
    """R5 复审反例 4：第 1 轮 gemini-2.5-pro 报 p.py:12；第 2 轮面板已无 Gemini，退役模型绝不能提交 p.py:3 篡改行号与证据。"""
    panel_r1 = ReviewPanel(
        finder_models=("gemini-2.5-pro", "gemini-2.5-pro"),
        verifier_model="claude-opus-5-5",
        require_verifier=True,
    )
    panel_r2 = ReviewPanel(
        finder_models=("gpt-6.1-sol", "gpt-6.1-sol"),
        verifier_model="claude-opus-5-5",
        require_verifier=True,
    )

    # 第 1 轮 gemini-2.5-pro 报 p.py:12
    f_r1_gemini = _finding(
        severity=Severity.IMPORTANT,
        file="p.py",
        line=12,
        category="状态损坏",
        failure_scenario="并发写未加锁导致状态回退",
        evidence="第 1 轮 p.py:12 无锁写入",
        source_models=("gemini-2.5-pro",),
    )
    history1 = (
        RoundHistoryEntry(
            1,
            HEAD_1,
            frozenset({f_r1_gemini.finding_id}),
            (f_r1_gemini,),
            panel=panel_r1,
            finder_session_ids=frozenset({"r1-gem-1", "r1-gem-2"}),
        ),
    )
    plan2 = plan_next_round(BASE_SHA, HEAD_2, history1)
    assert plan2.prior_important_sources == {f_r1_gemini.finding_id: frozenset({"gemini-2.5-pro"})}

    # 第 2 轮已退役的 gemini-2.5-pro 企图用同指纹提交 p.py:3 与超长伪造证据
    f_r2_gemini_tamper = _finding(
        severity=Severity.IMPORTANT,
        file="p.py",
        line=3,
        category="状态损坏",
        failure_scenario="并发写未加锁导致状态回退",
        evidence="p.py:3 退役模型篡改的超长伪造证据内容，企图覆盖第 1 轮行号与证据",
        source_models=("gemini-2.5-pro",),
    )
    assert f_r2_gemini_tamper.finding_id == f_r1_gemini.finding_id

    # 1) 无论批次标 gemini-2.5-pro 还是伪装标 gpt-6.1-sol，均在合并前被拒绝
    with pytest.raises(ConvergenceError):
        build_round_candidates(
            round_number=2,
            head_sha=HEAD_2,
            panel=panel_r2,
            finder_batches=(
                FinderBatch(model="gemini-2.5-pro", session_id="s1", head_sha=HEAD_2, findings=(f_r2_gemini_tamper,)),
                FinderBatch(model="gpt-6.1-sol", session_id="s2", head_sha=HEAD_2, findings=()),
            ),
            history=history1,
        )
    with pytest.raises(ConvergenceError):
        FinderBatch(model="gpt-6.1-sol", session_id="s1", head_sha=HEAD_2, findings=(f_r2_gemini_tamper,))

    # 2) RoundCandidates 不再接受外部直接传入 prior_important 或 current_round_findings
    with pytest.raises(TypeError):
        RoundCandidates(  # type: ignore[call-arg]
            round_number=2,
            head_sha=HEAD_2,
            panel=panel_r2,
            finder_batches=_batches_for_panel([], panel=panel_r2, round_number=2, head_sha=HEAD_2),
            prior_important=(f_r1_gemini, f_r2_gemini_tamper),
        )

    # 3) 合法保留第 1 轮未解除的 gemini-2.5-pro 发现 -> 第 2 轮行号仍为 12、证据原封不动，并可由异家族 claude 核实
    candidates_carry = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=panel_r2,
        finder_batches=_batches_for_panel([], panel=panel_r2, round_number=2, head_sha=HEAD_2),
        history=history1,
    )
    assert len(candidates_carry.findings) == 1
    assert candidates_carry.findings[0].line == 12
    assert candidates_carry.findings[0].evidence == "第 1 轮 p.py:12 无锁写入"
    assert candidates_carry.findings[0].source_models == ("gemini-2.5-pro",)
    verified_carry = parse_verifier_output(
        _verifier_payload(
            candidates_carry,
            [{"finding_id": f_r1_gemini.finding_id, "verdict": "confirmed", "verifier_evidence": "仍存在"}],
        ),
        candidates_carry,
        verifier_model="claude-opus-5-5",
    )
    assert len(verified_carry.verdicts) == 1
    assert verified_carry.verdicts[0].finding.line == 12

    # 4) 合法历史模型切换 + 当前面板 finder 复现补充 -> 保留当前轮新证据并合并历史 source_models
    f_r2_current_finder = _finding(
        severity=Severity.IMPORTANT,
        file="p.py",
        line=12,
        category="状态损坏",
        failure_scenario="并发写未加锁导致状态回退",
        evidence="第 2 轮 gpt-6.1-sol 补充复现证据内容",
        source_models=("gpt-6.1-sol",),
    )
    candidates_migrated = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=panel_r2,
        finder_batches=(
            FinderBatch(model="gpt-6.1-sol", session_id="r2-s1", head_sha=HEAD_2, findings=(f_r2_current_finder,)),
            FinderBatch(model="gpt-6.1-sol", session_id="r2-s2", head_sha=HEAD_2, findings=()),
        ),
        history=history1,
    )
    assert candidates_migrated.findings[0].source_models == ("gemini-2.5-pro", "gpt-6.1-sol")
    assert candidates_migrated.findings[0].evidence == "第 2 轮 gpt-6.1-sol 补充复现证据内容"
    verified_migrated = parse_verifier_output(
        _verifier_payload(
            candidates_migrated,
            [{"finding_id": f_r1_gemini.finding_id, "verdict": "confirmed", "verifier_evidence": "仍存在"}],
        ),
        candidates_migrated,
        verifier_model="claude-opus-5-5",
    )
    assert len(verified_migrated.verdicts) == 1
    assert verified_migrated.verdicts[0].finding.finding_id == f_r1_gemini.finding_id


def test_parse_verifier_output_rejects_invented_missing_duplicate_or_empty_evidence() -> None:
    f1 = _finding(file="a.py", category="c1", failure_scenario="s1")
    f2 = _finding(file="b.py", category="c2", failure_scenario="s2")
    cand1 = _candidates([f1])
    cand12 = _candidates([f1, f2])

    # 引入候选外的新发现
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand1,
                [
                    {"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"},
                    {"finding_id": "deadbeef12345678", "verdict": "confirmed", "verifier_evidence": "新问题"},
                ],
            ),
            cand1,
            verifier_model="claude-opus-5-5",
        )

    # 漏判候选
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand12,
                [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}],
            ),
            cand12,
            verifier_model="claude-opus-5-5",
        )

    # 重复裁决
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand1,
                [
                    {"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "ok1"},
                    {"finding_id": f1.finding_id, "verdict": "rejected", "verifier_evidence": "ok2"},
                ],
            ),
            cand1,
            verifier_model="claude-opus-5-5",
        )

    # 空核实证据
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand1,
                [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "   "}],
            ),
            cand1,
            verifier_model="claude-opus-5-5",
        )


def test_resolved_by_wontfix_without_author_reply_fails_closed() -> None:
    f_imp = _finding(severity=Severity.IMPORTANT)

    # 直接构造 VerifiedFinding 缺少 author_reply -> 立即抛 ConvergenceError
    with pytest.raises(ConvergenceError):
        VerifiedFinding(
            finding=f_imp,
            verdict=VerificationVerdict.RESOLVED_BY_WONTFIX,
            verifier_model="claude-opus-5-5",
            verifier_evidence="声称作者不修但实际无回复",
            round_number=1,
            head_sha=HEAD_1,
            author_reply=None,
        )

    # parse_verifier_output 收到 resolved_by_wontfix 但无匹配作者回复 -> 立即抛 ConvergenceError
    cand = _candidates([f_imp])
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand,
                [
                    {
                        "finding_id": f_imp.finding_id,
                        "verdict": "resolved_by_wontfix",
                        "verifier_evidence": "无回复强行放行",
                    }
                ],
            ),
            cand,
            verifier_model="claude-opus-5-5",
            author_replies=(),
        )


def test_only_confirmed_important_blocks_merge() -> None:
    f_imp = _finding(severity=Severity.IMPORTANT)
    f_nit = _finding(severity=Severity.NIT, file="n.py")
    f_pre = _finding(severity=Severity.PRE_EXISTING, file="p.py")
    reply = AuthorReply(f_imp.finding_id, None, None, "设计如此", "10", "alice")

    assert _verified(f_imp, VerificationVerdict.CONFIRMED).is_blocking is True
    assert _verified(f_imp, VerificationVerdict.REJECTED).is_blocking is False
    assert _verified(f_imp, VerificationVerdict.RESOLVED_BY_FIX).is_blocking is False
    assert _verified(f_imp, VerificationVerdict.RESOLVED_BY_WONTFIX, author_reply=reply).is_blocking is False
    assert _verified(f_nit, VerificationVerdict.CONFIRMED).is_blocking is False
    assert _verified(f_pre, VerificationVerdict.CONFIRMED).is_blocking is False


# ── 4. 作者白名单、Markdown 隔离与回复唯一绑定 ──────────────────────────────


def test_parse_wontfix_replies_enforces_author_whitelist_and_markdown_isolation() -> None:
    comments = [
        # 含 marker 的机器人评论必须整体忽略（即使 login 在白名单中）
        {
            "id": 100,
            "user": {"login": "alice", "type": "User"},
            "body": f"{COMMENT_MARKER_PREFIX} pr=1 round=1 head={HEAD_1} -->\n[abc12345] 不修：模板示例",
        },
        # Bot 账号（user.type == "Bot"）即便 login 在白名单中也必须拒绝
        {
            "id": 101,
            "user": {"login": "alice", "type": "Bot"},
            "body": "[abc12345] 不修：机器人冒充作者",
        },
        # 缺失作者必须拒绝
        {
            "id": 102,
            "body": "[abc12345] 不修：匿名评论",
        },
        # 非白名单作者必须拒绝
        {
            "id": 103,
            "user": {"login": "mallory", "type": "User"},
            "body": "[abc12345] 不修：路人试图绕过门禁",
        },
        # 合法白名单作者（大小写不敏感匹配）+ 各类 Markdown 代码块/引用干扰
        {
            "id": 104,
            "user": {"login": "ALICE", "type": "User"},
            "body": "\n".join(
                [
                    "> [deadbeef] 不修：引用机器人提示，不应解析",
                    "    [11112222] 不修：4 空格缩进代码块，不应解析",
                    "\t[33334444] 不修：Tab 缩进代码块，不应解析",
                    "```markdown",
                    "[cafebabe] 不修：反引号围栏代码块",
                    "```",
                    "~~~~text",
                    "[55556666] 不修：波浪线 4 字符围栏内",
                    "~~~",
                    "[77778888] 不修：长度不足的波浪线不能闭合 4 字符围栏",
                    "```",
                    "[99990000] 不修：反引号也不能闭合波浪线围栏",
                    "~~~~",
                    "[abc12345] 不修：上层入口已保证非空",
                    "不修(def67890): 兼容性要求保留旧行为",
                    "./pilot1742/foo.py:42 不修：此处仅用于离线诊断",
                    "pilot1742/bar.py 不修: 整文件为只读测试夹具",
                    "不修：   ",
                    "[11223344] 不修:",
                    "纯说明：如果不修这里会怎样？",
                ]
            ),
        },
        # PR 行内评论无显式锚点时继承 path/line
        {
            "id": 105,
            "author": "Bob",
            "path": "./pilot1742/inline.py",
            "line": 77,
            "body": "不修：热路径刻意避免额外拷贝",
        },
    ]

    replies = parse_wontfix_replies(comments, allowed_authors={"alice", "bob"})
    assert len(replies) == 5
    assert replies[0] == AuthorReply("abc12345", None, None, "上层入口已保证非空", "104", "ALICE")
    assert replies[1] == AuthorReply("def67890", None, None, "兼容性要求保留旧行为", "104", "ALICE")
    assert replies[2] == AuthorReply(None, "pilot1742/foo.py", 42, "此处仅用于离线诊断", "104", "ALICE")
    assert replies[3] == AuthorReply(None, "pilot1742/bar.py", None, "整文件为只读测试夹具", "104", "ALICE")
    assert replies[4] == AuthorReply(
        None, "pilot1742/inline.py", 77, "热路径刻意避免额外拷贝", "105", "Bob", is_inline_anchor=True
    )

    # 空或非集合 allowed_authors 必须 fail-closed
    with pytest.raises(ConvergenceError):
        parse_wontfix_replies(comments, allowed_authors=())
    with pytest.raises(ConvergenceError):
        parse_wontfix_replies(comments, allowed_authors="alice")  # type: ignore[arg-type]


def test_parse_wontfix_replies_isolates_list_fences_and_lazy_blockquote_continuations() -> None:
    # 复审反例 A：列表项内的波浪线/反引号代码围栏 + 缩进闭合围栏 -> 必须返回 0 条回复
    list_fence_comments = [
        {
            "id": 901,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "- ~~~text",
                    "  [abc12345] 不修：示例理由",
                    "  ~~~",
                    "* ```markdown",
                    "  [def67890] 不修：星号列表反引号围栏示例",
                    "  ```",
                    "+ ~~~~",
                    "  [11223344] 不修：加号列表四波浪线示例",
                    "  ~~~~",
                    "1. ```text",
                    "   [22334455] 不修：有序点号列表围栏示例",
                    "   ```",
                    "2) ~~~text",
                    "   [33445566] 不修：有序括号列表围栏示例",
                    "   ~~~",
                ]
            ),
        }
    ]
    assert parse_wontfix_replies(list_fence_comments, allowed_authors={"alice"}) == ()

    # 复审反例 B：> 引用后紧跟未重复 > 的惰性引用续行 -> 必须返回 0 条回复
    lazy_quote_comments = [
        {
            "id": 902,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "> 示例",
                    "[abc12345] 不修：示例理由",
                ]
            ),
        }
    ]
    assert parse_wontfix_replies(lazy_quote_comments, allowed_authors={"alice"}) == ()

    # 空行退出引用状态、闭合列表围栏后，后续真实回复仍能正常解析
    mixed_comments = [
        {
            "id": 903,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "- ~~~text",
                    "  [11111111] 不修：列表围栏内示例",
                    "  ~~~",
                    "[22222222] 不修：围栏闭合后的真实回复",
                    "> 引用说明",
                    "[33333333] 不修：惰性续行示例",
                    "",
                    "[44444444] 不修：空行退出引用后的真实回复",
                ]
            ),
        }
    ]
    parsed_mixed = parse_wontfix_replies(mixed_comments, allowed_authors={"alice"})
    assert [(r.finding_id, r.reason, r.comment_id) for r in parsed_mixed] == [
        ("22222222", "围栏闭合后的真实回复", "903"),
        ("44444444", "空行退出引用后的真实回复", "903"),
    ]


def test_parse_wontfix_replies_enforces_commonmark_closing_fence_indent_and_list_blockquote_interrupt() -> None:
    # R4 反例 1a：顶层 ~~~text（container_col=0）内四格缩进 ~~~ 不能闭合围栏 -> 0 条回复
    top_indented_close = [
        {
            "id": 910,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "~~~text",
                    "    ~~~",
                    "[abc12345] 不修：示例",
                ]
            ),
        },
        {
            "id": 911,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "~~~text",
                    "\t~~~",
                    "[abc12345] 不修：制表符缩进闭合同样无效",
                ]
            ),
        },
        {
            "id": 912,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "   ~~~text",
                    "    ~~~",
                    "[abc12345] 不修：开围栏缩进 3 格时容器列仍为 0，4 格不能闭合",
                ]
            ),
        },
    ]
    assert parse_wontfix_replies(top_indented_close, allowed_authors={"alice"}) == ()

    # R4 反例 1b：列表内 - ~~~text（container_col=2），缩进 2 正常闭合；缩进 6（> 2+3）不提前闭合
    list_close_ok = [
        {
            "id": 913,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "- ~~~text",
                    "  [11111111] 不修：列表围栏内示例",
                    "  ~~~",
                    "[22222222] 不修：2 格缩进闭合后的真实回复",
                ]
            ),
        }
    ]
    parsed_list_ok = parse_wontfix_replies(list_close_ok, allowed_authors={"alice"})
    assert [(r.finding_id, r.reason, r.comment_id) for r in parsed_list_ok] == [
        ("22222222", "2 格缩进闭合后的真实回复", "913"),
    ]

    list_close_over_indented = [
        {
            "id": 914,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "- ~~~text",
                    "      ~~~",
                    "  [33333333] 不修：列表内缩进 6 超过 2+3 不得提前闭合",
                ]
            ),
        }
    ]
    assert parse_wontfix_replies(list_close_over_indented, allowed_authors={"alice"}) == ()

    # 若后续行退缩回顶层（缩进 0 < 2），按 CommonMark 退出列表项并关闭其内部未闭围栏 -> 顶层真实回复正常解析
    list_over_indented_then_top_level = [
        {
            "id": 9140,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "- ~~~text",
                    "      ~~~",
                    "[33333333] 不修：退缩至顶层后退出列表项与内部未闭围栏",
                ]
            ),
        }
    ]
    parsed_unindented = parse_wontfix_replies(list_over_indented_then_top_level, allowed_authors={"alice"})
    assert [(r.finding_id, r.reason) for r in parsed_unindented] == [
        ("33333333", "退缩至顶层后退出列表项与内部未闭围栏"),
    ]

    # 列表内临界缩进 5（== 2+3）应正常闭合
    list_close_boundary = [
        {
            "id": 915,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "- ~~~text",
                    "     ~~~",
                    "[44444444] 不修：临界 5 格闭合后的真实回复",
                ]
            ),
        }
    ]
    parsed_list_boundary = parse_wontfix_replies(list_close_boundary, allowed_authors={"alice"})
    assert [(r.finding_id, r.reason) for r in parsed_list_boundary] == [
        ("44444444", "临界 5 格闭合后的真实回复"),
    ]

    # R4 反例 2：CommonMark §5.1 列表项中断引用块 vs 惰性续行 vs 引用内列表
    list_interrupts_quote = [
        {
            "id": 920,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "> 示例",
                    "- [abc12345] 不修：理由",
                ]
            ),
        },
        {
            "id": 921,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "> 示例",
                    "1. [def67890] 不修：有序列表同样中断引用",
                ]
            ),
        },
    ]
    parsed_interrupt = parse_wontfix_replies(list_interrupts_quote, allowed_authors={"alice"})
    assert [(r.finding_id, r.reason, r.comment_id) for r in parsed_interrupt] == [
        ("abc12345", "理由", "920"),
        ("def67890", "有序列表同样中断引用", "921"),
    ]

    # 对照 1：普通无列表前缀的惰性引用续行仍返回 0 条
    lazy_plain_continuation = [
        {
            "id": 922,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "> 示例",
                    "[abc12345] 不修：理由",
                ]
            ),
        }
    ]
    assert parse_wontfix_replies(lazy_plain_continuation, allowed_authors={"alice"}) == ()

    # 对照 2：显式 > 前缀的引用内列表仍返回 0 条
    quoted_list = [
        {
            "id": 923,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "> 示例",
                    "> - [abc12345] 不修：理由",
                ]
            ),
        }
    ]
    assert parse_wontfix_replies(quoted_list, allowed_authors={"alice"}) == ()


def test_parse_wontfix_replies_commonmark_phase1_container_stack_and_html_blocks() -> None:
    """R5 复审反例 1–3：容器栈出栈关闭未闭叶子块、列表 5 空格缩进代码、HTML 注释与全 7 类 HTML 块。"""
    # R5 反例 1a：列表内未闭围栏后紧跟顶层 ~~~ -> 先关闭 ListItem 与内部围栏，顶层 ~~~ 开新顶层围栏 -> 0 条
    list_exit_opens_top_fence = [
        {
            "id": 930,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "- ~~~text",
                    "  示例",
                    "~~~",
                    "[abc12345] 不修：顶层新围栏内示例",
                ]
            ),
        },
        {
            "id": 931,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "- ~~~text",
                    "  示例",
                    " ~~~",
                    "[abc12345] 不修：1 空格退缩列表后开新顶层围栏",
                ]
            ),
        },
        {
            "id": 932,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "- - ~~~text",
                    "    示例",
                    "  ~~~",
                    "  [abc12345] 不修：退缩内层列表后在外层列表开新围栏",
                ]
            ),
        },
    ]
    assert parse_wontfix_replies(list_exit_opens_top_fence, allowed_authors={"alice"}) == ()

    # R5 反例 1b：列表内未闭围栏后空行再顶层真实回复 -> 退出 ListItem 并关闭内部未闭围栏 -> 1 条
    list_exit_then_real_reply = [
        {
            "id": 933,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "- ~~~text",
                    "  示例",
                    "",
                    "[abc12345] 不修：真实理由",
                ]
            ),
        }
    ]
    parsed_exit_real = parse_wontfix_replies(list_exit_then_real_reply, allowed_authors={"alice"})
    assert [(r.finding_id, r.reason, r.comment_id) for r in parsed_exit_real] == [
        ("abc12345", "真实理由", "933"),
    ]

    # R5 反例 2：列表项标记后 >= 5 空格（或双 Tab）按 CommonMark §5.2 判为 IndentedCode -> 0 条；1..4 空格（或单 Tab）判为段落 -> 1 条
    list_indented_code_cases = [
        {"id": 934, "user": {"login": "alice", "type": "User"}, "body": "-     [abc12345] 不修：5 空格缩进代码"},
        {"id": 935, "user": {"login": "alice", "type": "User"}, "body": "1.     [def67890] 不修：有序列表 5 空格缩进代码"},
        {"id": 936, "user": {"login": "alice", "type": "User"}, "body": "-\t\t[11223344] 不修：双 Tab 缩进代码"},
        {
            "id": 937,
            "user": {"login": "alice", "type": "User"},
            "body": "- 正常说明\n\n      [22334455] 不修：列表空行后 6 空格缩进代码",
        },
    ]
    assert parse_wontfix_replies(list_indented_code_cases, allowed_authors={"alice"}) == ()

    list_valid_indent_cases = [
        {"id": 938, "user": {"login": "alice", "type": "User"}, "body": "- [abc12345] 不修：1 空格正常列表"},
        {"id": 939, "user": {"login": "alice", "type": "User"}, "body": "-    [def67890] 不修：4 空格临界正常列表"},
        {"id": 940, "user": {"login": "alice", "type": "User"}, "body": "-\t[11223344] 不修：单 Tab 正常列表"},
        {"id": 941, "user": {"login": "alice", "type": "User"}, "body": "1.    [22334455] 不修：有序列表 4 空格正常列表"},
    ]
    parsed_valid_list = parse_wontfix_replies(list_valid_indent_cases, allowed_authors={"alice"})
    assert [(r.finding_id, r.comment_id) for r in parsed_valid_list] == [
        ("abc12345", "938"),
        ("def67890", "939"),
        ("11223344", "940"),
        ("22334455", "941"),
    ]

    # R5 反例 3：HTML 注释（单行/多行/行内）与全部 7 类 CommonMark HTMLBlock
    html_block_cases = [
        {
            "id": 942,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "<!-- [11111111] 不修：单行注释示例 -->",
                    "<!--",
                    "[22222222] 不修：多行注释示例",
                    "-->",
                    "<!-- note --> [33333333] 不修：Type 2 块同行尾部",
                    "<pre>",
                    "[44444444] 不修：Type 1 pre 块内",
                    "</pre>",
                    "<script>",
                    "[55555555] 不修：Type 1 script 块内",
                    "</script>",
                    "<?php",
                    "[66666666] 不修：Type 3 PI 块内",
                    "?>",
                    "<!DOCTYPE html",
                    "[77777777] 不修：Type 4 声明块内",
                    ">",
                    "<![CDATA[",
                    "[88888888] 不修：Type 5 CDATA 块内",
                    "]]>",
                    "<details>",
                    "<summary>折叠模板</summary>",
                    "[99999999] 不修：Type 6 details 块内",
                    "</details>",
                    "",
                    "<custom-box>",
                    "[aaaaaaaa] 不修：Type 7 自定义标签块内",
                    "</custom-box>",
                    "",
                    "段落说明 <!--",
                    "[bbbbbbbb] 不修：跨行行内注释示例",
                    "-->",
                    "[cccccccc] <!-- 行内备注 --> 不修：真实回复",
                ]
            ),
        },
        {
            "id": 943,
            "user": {"login": "alice", "type": "User"},
            "body": "\n".join(
                [
                    "> 引用段落",
                    "<span>Type 7 不可中断引用</span>",
                    "[dddddddd] 不修：仍在惰性引用续行内",
                ]
            ),
        },
    ]
    parsed_html = parse_wontfix_replies(html_block_cases, allowed_authors={"alice"})
    assert [(r.finding_id, r.reason, r.comment_id) for r in parsed_html] == [
        ("cccccccc", "真实回复", "942"),
    ]


def test_parse_wontfix_replies_and_author_reply_require_real_comment_id() -> None:
    f_imp = _finding(severity=Severity.IMPORTANT)

    # 缺少 id / comment_id、空字符串或非正整数 id 的评论必须忽略，绝不能解除 Important
    no_id_comments = [
        {"user": {"login": "alice", "type": "User"}, "body": f"[{f_imp.finding_id}] 不修：无 comment_id"},
        {"id": None, "user": {"login": "alice", "type": "User"}, "body": f"[{f_imp.finding_id}] 不修：null id"},
        {"id": "   ", "user": {"login": "alice", "type": "User"}, "body": f"[{f_imp.finding_id}] 不修：空白 id"},
        {"id": 0, "user": {"login": "alice", "type": "User"}, "body": f"[{f_imp.finding_id}] 不修：零 id"},
        {"id": -5, "user": {"login": "alice", "type": "User"}, "body": f"[{f_imp.finding_id}] 不修：负 id"},
    ]
    parsed = parse_wontfix_replies(no_id_comments, allowed_authors={"alice"})
    assert parsed == ()
    cand_no_id = _candidates([f_imp])
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand_no_id,
                [
                    {
                        "finding_id": f_imp.finding_id,
                        "verdict": "resolved_by_wontfix",
                        "verifier_evidence": "试图用无 comment_id 评论放行",
                    }
                ],
            ),
            cand_no_id,
            verifier_model="claude-opus-5-5",
            author_replies=parsed,
        )

    # 直接构造缺少 comment_id 的 AuthorReply 也必须 fail-closed
    with pytest.raises(ConvergenceError):
        AuthorReply(f_imp.finding_id, None, None, "无 ID", "", "alice")
    with pytest.raises(ConvergenceError):
        AuthorReply(f_imp.finding_id, None, None, "无 ID", None, "alice")  # type: ignore[arg-type]


def test_bind_author_replies_rejects_ambiguous_and_supports_multi_reply_comment() -> None:
    f_a1 = _finding(file="pilot1742/shared.py", line=10, category="cat1", failure_scenario="scen1")
    f_a2 = _finding(file="pilot1742/shared.py", line=20, category="cat2", failure_scenario="scen2")
    f_other = _finding(file="pilot1742/other.py", line=5, category="cat3", failure_scenario="scen3")

    # 1) 无行号路径命中 2 个同文件发现 -> 歧义，拒绝绑定到任何发现
    ambiguous_path_reply = AuthorReply(None, "pilot1742/shared.py", None, "整文件都不修", "200", "alice")
    bound_ambig = bind_author_replies([f_a1, f_a2, f_other], [ambiguous_path_reply])
    assert bound_ambig == {}

    # 2) 短 ID 前缀命中超过 1 个发现 -> 歧义，拒绝绑定到任何发现（确定性 6 位前缀碰撞对）
    f_col_1 = _finding(file="pilot1742/c.py", line=10, category="cat", failure_scenario="scen-6730")
    f_col_2 = _finding(file="pilot1742/c.py", line=20, category="cat", failure_scenario="scen-12471")
    assert f_col_1.finding_id[:6] == f_col_2.finding_id[:6] == "e72ae7"
    assert f_col_1.finding_id != f_col_2.finding_id
    ambig_prefix_reply = AuthorReply("e72ae7", None, None, "短前缀歧义", "201", "alice")
    assert bind_author_replies([f_col_1, f_col_2], [ambig_prefix_reply]) == {}

    # 3) 同一评论含多条分别唯一指向不同发现的回复 -> 各自成功绑定；且支持 consumed_comment_ids 过滤
    multi_comment = [
        {
            "id": 300,
            "user": {"login": "alice", "type": "User"},
            "body": (
                f"[{f_a1.finding_id}] 不修：仅影响离线脚本\n"
                f"pilot1742/shared.py:20 不修：调用方已做边界校验\n"
                f"pilot1742/other.py 不修：该文件只有这一个发现\n"
            ),
        }
    ]
    parsed = parse_wontfix_replies(multi_comment, allowed_authors={"alice"})
    bound = bind_author_replies([f_a1, f_a2, f_other], parsed)
    assert set(bound.keys()) == {f_a1.finding_id, f_a2.finding_id, f_other.finding_id}
    assert bound[f_a1.finding_id].reason == "仅影响离线脚本"
    assert bound[f_a2.finding_id].reason == "调用方已做边界校验"
    assert bound[f_other.finding_id].reason == "该文件只有这一个发现"
    assert bind_author_replies([f_a1, f_a2, f_other], parsed, consumed_comment_ids={"300"}) == {}

    # 4) 歧义回复传入 parse_verifier_output 触发 resolved_by_wontfix 时必须 fail-closed
    cand_ambig = _candidates([f_a1, f_a2])
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand_ambig,
                [
                    {"finding_id": f_a1.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "ok"},
                    {"finding_id": f_a2.finding_id, "verdict": "confirmed", "verifier_evidence": "still broken"},
                ],
            ),
            cand_ambig,
            verifier_model="claude-opus-5-5",
            author_replies=[ambiguous_path_reply],
        )


# ── 5. 多轮收敛、不重复贴出与重开生命周期隔离 ─────────────────────────────────


def test_multi_round_convergence_reopen_cannot_reuse_old_wontfix_reply() -> None:
    f_imp = _finding(severity=Severity.IMPORTANT, file="a.py", line=10, category="空值", failure_scenario="空指针")
    f_nit = _finding(severity=Severity.NIT, file="b.py", line=20, category="风格", failure_scenario="多余空行")

    # 第 1 轮：全 PR 审查
    plan1 = plan_next_round(BASE_SHA, HEAD_1, [])
    assert plan1.round_number == 1
    assert plan1.review_scope == "full_pr"

    dec1 = evaluate_round(
        _verified_round(
            [_verified(f_imp, VerificationVerdict.CONFIRMED), _verified(f_nit, VerificationVerdict.CONFIRMED)],
            round_number=plan1.round_number,
            head_sha=HEAD_1,
        )
    )
    rendered1 = render_findings_comment(1928, HEAD_1, dec1)
    assert dec1.outcome == RoundOutcome.BLOCKED
    assert rendered1.posted_fingerprints == frozenset({f_imp.finding_id, f_nit.finding_id})

    # 第 2 轮：作者发回复不修，核实采信 -> PASS，记录 resolved_fingerprints 与 consumed_reply_keys
    old_comment = [
        {
            "id": 500,
            "user": {"login": "alice", "type": "User"},
            "body": f"[{f_imp.finding_id}] 不修：旧版本入口已有前置校验",
        }
    ]
    replies_r2 = parse_wontfix_replies(old_comment, allowed_authors={"alice"})
    history = [dec1.to_history_entry(HEAD_1, rendered=rendered1)]
    plan2 = plan_next_round(BASE_SHA, HEAD_2, history, author_replies=replies_r2)
    candidates2 = build_round_candidates(
        round_number=plan2.round_number,
        head_sha=plan2.diff_head_sha,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], panel=DEFAULT_PANEL, round_number=2),
        history=plan2.history,
    )
    verified2 = parse_verifier_output(
        _verifier_payload(
            candidates2,
            [
                {
                    "finding_id": f_imp.finding_id,
                    "verdict": "resolved_by_wontfix",
                    "verifier_evidence": "核实旧入口确实校验了空值",
                }
            ],
        ),
        candidates2,
        verifier_model="claude-opus-5-5",
        author_replies=plan2.author_replies,
        consumed_reply_keys=plan2.consumed_reply_keys,
    )
    dec2 = evaluate_round(verified2, author_replies=plan2.author_replies)
    rendered2 = render_findings_comment(1928, HEAD_2, dec2)
    entry2 = dec2.to_history_entry(HEAD_2, rendered=rendered2)
    assert dec2.outcome == RoundOutcome.PASS
    assert f_imp.finding_id in entry2.resolved_fingerprints
    assert replies_r2[0].reply_key in entry2.consumed_reply_keys
    assert f"comment:500:resolved:{f_imp.finding_id}" in entry2.consumed_reply_keys
    assert f_imp.finding_id not in entry2.posted_fingerprints
    assert f_nit.finding_id in entry2.posted_fingerprints

    # 第 3 轮：同指纹发现被重新引入（reopen）
    history.append(entry2)
    plan3 = plan_next_round(BASE_SHA, HEAD_3, history, author_replies=replies_r2)
    assert f_imp.finding_id not in plan3.already_posted_fingerprints
    assert f_nit.finding_id in plan3.already_posted_fingerprints
    # 旧回复已被过滤且记录在 consumed_reply_keys 中，绝不能复用解除重开的发现！
    assert plan3.author_replies == ()
    assert replies_r2[0].reply_key in plan3.consumed_reply_keys

    cand3 = _candidates([f_imp], round_number=3, head_sha=HEAD_3, history=history)
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand3,
                [
                    {
                        "finding_id": f_imp.finding_id,
                        "verdict": "resolved_by_wontfix",
                        "verifier_evidence": "试图复用第 2 轮旧回复解除重开问题",
                    }
                ],
            ),
            cand3,
            verifier_model="claude-opus-5-5",
            author_replies=replies_r2,
            consumed_reply_keys=plan3.consumed_reply_keys,
        )

    # 重开后若作者发一条全新评论（新 comment_id），可以合法解除
    new_comment = [
        {
            "id": 501,
            "user": {"login": "alice", "type": "User"},
            "body": f"[{f_imp.finding_id}] 不修：新入口同样已有前置校验",
        }
    ]
    replies_r3_new = parse_wontfix_replies(old_comment + new_comment, allowed_authors={"alice"})
    plan3_with_new = plan_next_round(BASE_SHA, HEAD_3, history, author_replies=replies_r3_new)
    assert len(plan3_with_new.author_replies) == 1
    assert plan3_with_new.author_replies[0].comment_id == "501"
    verified3 = parse_verifier_output(
        _verifier_payload(
            cand3,
            [
                {
                    "finding_id": f_imp.finding_id,
                    "verdict": "resolved_by_wontfix",
                    "verifier_evidence": "核实新回复理由成立",
                }
            ],
        ),
        cand3,
        verifier_model="claude-opus-5-5",
        author_replies=plan3_with_new.author_replies,
        consumed_reply_keys=plan3_with_new.consumed_reply_keys,
    )
    assert verified3.verdicts[0].author_reply is not None
    assert verified3.verdicts[0].author_reply.comment_id == "501"

    # 重开后如果被确认成立，必须允许重新贴出；已贴过的 Nit 仍不重复贴
    postable3 = select_postable_findings(
        [_verified(f_imp, VerificationVerdict.CONFIRMED), _verified(f_nit, VerificationVerdict.CONFIRMED)],
        plan3.already_posted_fingerprints,
    )
    assert [vf.finding.finding_id for vf in postable3] == [f_imp.finding_id]


def test_reopen_consumes_all_prior_replies_including_unselected_siblings_and_allows_new_comment() -> None:
    """复审反例：第 2 轮同一发现有评论 101 与 102，选中 102 后第 3 轮重开不得复用 101；新增 103 才可合法解除。"""
    f_imp = _finding(severity=Severity.IMPORTANT, file="a.py", line=10, category="空值", failure_scenario="空指针")

    # 第 1 轮：确认 Important
    plan1 = plan_next_round(BASE_SHA, HEAD_1, [])
    dec1 = evaluate_round(
        _verified_round([_verified(f_imp, VerificationVerdict.CONFIRMED)], round_number=plan1.round_number, head_sha=HEAD_1)
    )
    rendered1 = render_findings_comment(1928, HEAD_1, dec1)
    history = [dec1.to_history_entry(HEAD_1, rendered=rendered1)]

    # 第 2 轮：同一作者发了评论 101 与 102 均指向 f_imp，系统选中 102 放行
    dual_comments = [
        {"id": 101, "user": {"login": "alice", "type": "User"}, "body": f"[{f_imp.finding_id}] 不修：旧理由 101"},
        {"id": 102, "user": {"login": "alice", "type": "User"}, "body": f"[{f_imp.finding_id}] 不修：较新理由 102"},
    ]
    replies_r2 = parse_wontfix_replies(dual_comments, allowed_authors={"alice"})
    assert [r.comment_id for r in replies_r2] == ["101", "102"]

    plan2 = plan_next_round(BASE_SHA, HEAD_2, history, author_replies=replies_r2)
    candidates2 = build_round_candidates(
        round_number=plan2.round_number,
        head_sha=plan2.diff_head_sha,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], panel=DEFAULT_PANEL, round_number=2),
        history=plan2.history,
    )
    verified2 = parse_verifier_output(
        _verifier_payload(
            candidates2,
            [
                {
                    "finding_id": f_imp.finding_id,
                    "verdict": "resolved_by_wontfix",
                    "verifier_evidence": "核实 102 理由成立",
                }
            ],
        ),
        candidates2,
        verifier_model="claude-opus-5-5",
        author_replies=plan2.author_replies,
        consumed_reply_keys=plan2.consumed_reply_keys,
    )
    assert verified2.verdicts[0].author_reply is not None
    assert verified2.verdicts[0].author_reply.comment_id == "102"

    # 即使 evaluate_round 未额外重传 author_replies，也能通过 VerifiedFinding.related_reply_keys 消费 101 与 102
    dec2 = evaluate_round(verified2)
    rendered2 = render_findings_comment(1928, HEAD_2, dec2)
    entry2 = dec2.to_history_entry(HEAD_2, rendered=rendered2)
    assert replies_r2[0].reply_key in entry2.consumed_reply_keys
    assert replies_r2[1].reply_key in entry2.consumed_reply_keys
    history.append(entry2)

    # 第 3 轮重开仍传入 [101, 102] -> 两条均已消费，绝不能放行
    plan3 = plan_next_round(BASE_SHA, HEAD_3, history, author_replies=replies_r2)
    assert plan3.author_replies == ()
    cand3 = _candidates([f_imp], round_number=3, head_sha=HEAD_3, history=history)
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand3,
                [
                    {
                        "finding_id": f_imp.finding_id,
                        "verdict": "resolved_by_wontfix",
                        "verifier_evidence": "试图用未选中的旧评论 101 绕过门禁",
                    }
                ],
            ),
            cand3,
            verifier_model="claude-opus-5-5",
            author_replies=replies_r2,
            consumed_reply_keys=plan3.consumed_reply_keys,
        )

    # 第 3 轮新增评论 103 -> 合法解除
    comment_103 = [
        {"id": 103, "user": {"login": "alice", "type": "User"}, "body": f"[{f_imp.finding_id}] 不修：重开后的全新理由 103"}
    ]
    replies_r3 = parse_wontfix_replies(dual_comments + comment_103, allowed_authors={"alice"})
    plan3_new = plan_next_round(BASE_SHA, HEAD_3, history, author_replies=replies_r3)
    assert [r.comment_id for r in plan3_new.author_replies] == ["103"]
    verified3 = parse_verifier_output(
        _verifier_payload(
            cand3,
            [
                {
                    "finding_id": f_imp.finding_id,
                    "verdict": "resolved_by_wontfix",
                    "verifier_evidence": "核实 103 理由成立",
                }
            ],
        ),
        cand3,
        verifier_model="claude-opus-5-5",
        author_replies=plan3_new.author_replies,
        consumed_reply_keys=plan3_new.consumed_reply_keys,
    )
    assert verified3.verdicts[0].author_reply is not None
    assert verified3.verdicts[0].author_reply.comment_id == "103"


def test_reopen_blocks_inline_comment_reuse_even_when_github_diff_line_shifts() -> None:
    """R4 复审反例：第 2 轮消费行内评论 101（line=12），第 3 轮仅因新提交漂移至 line=13，仍必须拒绝复用。"""
    f_r1 = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/shifted.py",
        line=12,
        category="边界校验",
        failure_scenario="缺失前置校验触发异常",
        evidence="第 12 行未校验输入",
    )
    dec1 = evaluate_round(_verified_round([_verified(f_r1, VerificationVerdict.CONFIRMED)], round_number=1, head_sha=HEAD_1))
    rendered1 = render_findings_comment(1928, HEAD_1, dec1)
    history = [dec1.to_history_entry(HEAD_1, rendered=rendered1)]

    # 第 2 轮消费行内评论 101（line=12, original_line=12）
    inline_r2 = [
        {
            "id": 101,
            "user": {"login": "alice", "type": "User"},
            "path": "pilot1742/shifted.py",
            "line": 12,
            "original_line": 12,
            "body": "不修：上层调用方已保证非空",
        }
    ]
    replies_r2 = parse_wontfix_replies(inline_r2, allowed_authors={"alice"})
    assert len(replies_r2) == 1
    assert replies_r2[0].line == 12
    assert replies_r2[0].reply_key.startswith("comment:101:inline:")

    plan2 = plan_next_round(BASE_SHA, HEAD_2, history, author_replies=replies_r2)
    candidates2 = build_round_candidates(
        round_number=plan2.round_number,
        head_sha=plan2.diff_head_sha,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_r1], panel=DEFAULT_PANEL, round_number=2),
        history=plan2.history,
    )
    verified2 = parse_verifier_output(
        _verifier_payload(
            candidates2,
            [
                {
                    "finding_id": f_r1.finding_id,
                    "verdict": "resolved_by_wontfix",
                    "verifier_evidence": "核实上层确已校验",
                }
            ],
        ),
        candidates2,
        verifier_model="claude-opus-5-5",
        author_replies=plan2.author_replies,
        consumed_reply_keys=plan2.consumed_reply_keys,
    )
    dec2 = evaluate_round(verified2)
    rendered2 = render_findings_comment(1928, HEAD_2, dec2)
    entry2 = dec2.to_history_entry(HEAD_2, rendered=rendered2)
    assert replies_r2[0].reply_key in entry2.consumed_reply_keys
    assert f"comment:101:resolved:{f_r1.finding_id}" in entry2.consumed_reply_keys
    history.append(entry2)

    # 第 3 轮新提交把同指纹问题移到第 13 行，GitHub 将未编辑的评论 101 偏移为 line=13, original_line=12
    f_r3_reopened = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/shifted.py",
        line=13,
        category="边界校验",
        failure_scenario="缺失前置校验触发异常",
        evidence="第 13 行未校验输入",
    )
    assert f_r3_reopened.finding_id == f_r1.finding_id
    inline_r3_shifted = [
        {
            "id": 101,
            "user": {"login": "alice", "type": "User"},
            "path": "pilot1742/shifted.py",
            "line": 13,
            "original_line": 12,
            "body": "不修：上层调用方已保证非空",
        }
    ]
    replies_r3 = parse_wontfix_replies(inline_r3_shifted, allowed_authors={"alice"})
    assert len(replies_r3) == 1
    assert replies_r3[0].line == 13
    assert replies_r3[0].reply_key == replies_r2[0].reply_key

    plan3 = plan_next_round(BASE_SHA, HEAD_3, history, author_replies=replies_r3)
    assert plan3.author_replies == ()
    assert (
        bind_author_replies(
            [f_r3_reopened],
            replies_r3,
            consumed_reply_keys=plan3.consumed_reply_keys,
        )
        == {}
    )
    cand3 = _candidates([f_r3_reopened], round_number=3, head_sha=HEAD_3, history=history)
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand3,
                [
                    {
                        "finding_id": f_r3_reopened.finding_id,
                        "verdict": "resolved_by_wontfix",
                        "verifier_evidence": "试图借行号漂移复用已消费旧评论 101",
                    }
                ],
            ),
            cand3,
            verifier_model="claude-opus-5-5",
            author_replies=replies_r3,
            consumed_reply_keys=plan3.consumed_reply_keys,
        )

    # 同一评论 200 内多条指向同文件不同行且不同理由的不修指令，reply_key 互不冲突且不依赖顺序下标
    f_line10 = _finding(file="pilot1742/multi.py", line=10, category="cat1", failure_scenario="scen1")
    f_line20 = _finding(file="pilot1742/multi.py", line=20, category="cat2", failure_scenario="scen2")
    multi_dir_comment = [
        {
            "id": 200,
            "user": {"login": "alice", "type": "User"},
            "body": (
                "pilot1742/multi.py:10 不修：第一条理由\n"
                "pilot1742/multi.py:20 不修：第二条理由\n"
            ),
        }
    ]
    parsed_multi = parse_wontfix_replies(multi_dir_comment, allowed_authors={"alice"})
    assert len(parsed_multi) == 2
    assert parsed_multi[0].reply_key != parsed_multi[1].reply_key
    bound_after_consuming_first = bind_author_replies(
        [f_line10, f_line20],
        parsed_multi,
        consumed_reply_keys={parsed_multi[0].reply_key},
    )
    assert set(bound_after_consuming_first.keys()) == {f_line20.finding_id}
    assert bound_after_consuming_first[f_line20.finding_id].reason == "第二条理由"


def test_resolved_by_fix_and_rejected_also_consume_matching_replies() -> None:
    f_fix = _finding(file="fix.py", line=10, category="c1", failure_scenario="s1")
    f_rej = _finding(file="rej.py", line=20, category="c2", failure_scenario="s2")
    # 第 1 轮先确认 f_fix，使之进入第 2 轮 prior_important（第 2 轮才允许对其标 resolved_by_fix）
    entry1 = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset({f_fix.finding_id}),
        (f_fix,),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r1-fix-1", "r1-fix-2"}),
    )
    comments = [
        {"id": 201, "user": {"login": "alice", "type": "User"}, "body": f"[{f_fix.finding_id}] 不修：先写过不修但后来修了"},
        {"id": 202, "user": {"login": "alice", "type": "User"}, "body": f"[{f_rej.finding_id}] 不修：先写过不修但后来被驳回"},
    ]
    replies = parse_wontfix_replies(comments, allowed_authors={"alice"})
    cand2 = _candidates([f_rej], round_number=2, head_sha=HEAD_2, history=(entry1,))
    verified = parse_verifier_output(
        _verifier_payload(
            cand2,
            [
                {"finding_id": f_fix.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "已修复"},
                {"finding_id": f_rej.finding_id, "verdict": "rejected", "verifier_evidence": "误报驳回"},
            ],
        ),
        cand2,
        verifier_model="claude-opus-5-5",
        author_replies=replies,
    )
    dec = evaluate_round(verified)
    assert replies[0].reply_key in dec.consumed_reply_keys
    assert replies[1].reply_key in dec.consumed_reply_keys
    assert f"comment:201:resolved:{f_fix.finding_id}" in dec.consumed_reply_keys
    assert f"comment:202:resolved:{f_rej.finding_id}" in dec.consumed_reply_keys


def test_confirmed_rejected_confirmed_three_round_sequence_reposts_full_evidence() -> None:
    """Nit 回归：confirmed -> rejected -> confirmed 第 3 轮重新确认时完整贴出最新证据，不误写前轮未解除。"""
    f_imp = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/flaky.py",
        line=44,
        category="边界条件",
        failure_scenario="重新确认后的最新失败场景_R3_SCENARIO",
        evidence="原始证据",
    )

    # 第 1 轮：confirmed
    dec1 = evaluate_round(
        _verified_round([_verified(f_imp, VerificationVerdict.CONFIRMED, verifier_evidence="R1 初次核实证据")], round_number=1, head_sha=HEAD_1)
    )
    rendered1 = render_findings_comment(1928, HEAD_1, dec1)
    entry1 = dec1.to_history_entry(HEAD_1, rendered=rendered1)
    assert f_imp.finding_id in entry1.posted_fingerprints

    # 第 2 轮：rejected -> 移出活跃已贴集合
    plan2 = plan_next_round(BASE_SHA, HEAD_2, [entry1])
    assert f_imp.finding_id in plan2.already_posted_fingerprints
    dec2 = evaluate_round(
        _verified_round(
            [_verified(f_imp, VerificationVerdict.REJECTED, verifier_evidence="R2 核实认为上游已保护")],
            round_number=plan2.round_number,
            head_sha=HEAD_2,
            history=[entry1],
        )
    )
    rendered2 = render_findings_comment(1928, HEAD_2, dec2)
    entry2 = dec2.to_history_entry(HEAD_2, rendered=rendered2)
    assert f_imp.finding_id in entry2.rejected_fingerprints
    assert f_imp.finding_id not in entry2.posted_fingerprints

    # 第 3 轮：再次 confirmed -> 完整贴出最新证据，不出现“前轮已贴出且仍未解除”
    plan3 = plan_next_round(BASE_SHA, HEAD_3, [entry1, entry2])
    assert f_imp.finding_id not in plan3.already_posted_fingerprints
    dec3 = evaluate_round(
        _verified_round(
            [_verified(f_imp, VerificationVerdict.CONFIRMED, verifier_evidence="R3 最新核实证据_UNIQUE_R3")],
            round_number=plan3.round_number,
            head_sha=HEAD_3,
            history=[entry1, entry2],
        )
    )
    assert [vf.finding.finding_id for vf in dec3.postable_findings] == [f_imp.finding_id]
    rendered3 = render_findings_comment(1928, HEAD_3, dec3)
    assert "重新确认后的最新失败场景_R3_SCENARIO" in rendered3.body
    assert "R3 最新核实证据_UNIQUE_R3" in rendered3.body
    assert "前轮已贴出且仍未解除" not in rendered3.body


def test_round_4_non_convergent_fails_closed_and_stops_auto_rereview() -> None:
    f_imp = _finding(severity=Severity.IMPORTANT)
    history = [
        RoundHistoryEntry(
            1,
            HEAD_1,
            frozenset({f_imp.finding_id}),
            (f_imp,),
            panel=DEFAULT_PANEL,
            finder_session_ids=frozenset({"r1-nc-1", "r1-nc-2"}),
        ),
        RoundHistoryEntry(
            2,
            HEAD_2,
            frozenset({f_imp.finding_id}),
            (f_imp,),
            panel=DEFAULT_PANEL,
            finder_session_ids=frozenset({"r2-nc-1", "r2-nc-2"}),
        ),
        RoundHistoryEntry(
            3,
            HEAD_3,
            frozenset({f_imp.finding_id}),
            (f_imp,),
            panel=DEFAULT_PANEL,
            finder_session_ids=frozenset({"r3-nc-1", "r3-nc-2"}),
        ),
    ]
    assert MAX_AUTO_ROUNDS == 3

    plan4 = plan_next_round(BASE_SHA, HEAD_4, history)
    assert plan4.round_number == 4
    assert plan4.review_scope == "incremental_diff"
    assert plan4.diff_base_sha == HEAD_3
    assert plan4.exceeds_auto_rounds is True

    dec4_fail = evaluate_round(
        _verified_round(
            [_verified(f_imp, VerificationVerdict.CONFIRMED)],
            round_number=plan4.round_number,
            head_sha=HEAD_4,
            history=history,
        )
    )
    assert dec4_fail.outcome == RoundOutcome.NON_CONVERGENT
    assert dec4_fail.github_state == "failure"
    assert dec4_fail.description == NON_CONVERGENT_DESCRIPTION
    assert dec4_fail.stop_auto_rereview is True
    assert dec4_fail.postable_findings == ()

    reply = AuthorReply(f_imp.finding_id, None, None, "外层锁已保护该不变量", "200", "alice")
    dec4_pass = evaluate_round(
        _verified_round(
            [_verified(f_imp, VerificationVerdict.RESOLVED_BY_WONTFIX, verifier_evidence="核实外层持锁成立", author_reply=reply)],
            round_number=plan4.round_number,
            head_sha=HEAD_4,
            history=history,
        )
    )
    assert dec4_pass.outcome == RoundOutcome.PASS
    assert dec4_pass.github_state == "success"
    assert dec4_pass.stop_auto_rereview is False


def test_plan_next_round_rejects_non_consecutive_history() -> None:
    with pytest.raises(ConvergenceError):
        plan_next_round(
            BASE_SHA,
            HEAD_2,
            [
                RoundHistoryEntry(
                    2,
                    HEAD_1,
                    frozenset(),
                    (),
                    panel=DEFAULT_PANEL,
                    finder_session_ids=frozenset({"r2-s1", "r2-s2"}),
                )
            ],
        )


# ── 6. 幂等 PR 评论渲染、前轮 Important 不重复展开、截断保全部阻断与历史对齐 ───


def test_render_findings_comment_zero_findings_and_marker_uses_decision_round() -> None:
    entry1 = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r1-z1", "r1-z2"}),
    )
    dec = evaluate_round(_verified_round([], round_number=2, head_sha=HEAD_2, history=[entry1]))
    c1 = render_findings_comment(1928, HEAD_2, dec)
    c2 = render_findings_comment(1928, HEAD_2, dec)
    assert isinstance(c1, RenderedComment)
    assert c1 == c2
    assert c1.truncated is False
    assert c1.posted_fingerprints == frozenset()
    assert c1.omitted_non_blocking_fingerprints == frozenset()
    lines = c1.body.splitlines()
    assert lines[0] == f"{COMMENT_MARKER_PREFIX} pr=1928 round=2 head={HEAD_2} -->"
    assert parse_comment_marker(c1.body) == (1928, 2, HEAD_2)
    assert lines[1].startswith("0 项 Important，0 项 Nit，0 项 Pre-existing")
    assert "无需要修复的问题" in lines[1]


def test_render_findings_comment_does_not_repeat_prior_important_details() -> None:
    f_prior = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/prior.py",
        line=15,
        category="旧阻断",
        failure_scenario="前轮已贴出的超长失败场景说明_UNIQUE_PRIOR_SCENARIO",
        evidence="前轮证据",
    )
    f_new = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/new.py",
        line=99,
        category="新阻断",
        failure_scenario="本轮新发现的失败场景_UNIQUE_NEW_SCENARIO",
        evidence="本轮证据",
    )

    entry1 = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset({f_prior.finding_id}),
        (f_prior,),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r1-p1", "r1-p2"}),
    )
    dec2 = evaluate_round(
        _verified_round(
            [
                _verified(f_prior, VerificationVerdict.CONFIRMED, verifier_evidence="前轮核实证据_UNIQUE_PRIOR_EVIDENCE"),
                _verified(f_new, VerificationVerdict.CONFIRMED, verifier_evidence="本轮核实证据_UNIQUE_NEW_EVIDENCE"),
            ],
            round_number=2,
            head_sha=HEAD_2,
            history=[entry1],
        )
    )
    rendered = render_findings_comment(1928, HEAD_2, dec2)
    lines = rendered.body.splitlines()
    assert lines[0] == f"{COMMENT_MARKER_PREFIX} pr=1928 round=2 head={HEAD_2} -->"
    # 首行计数照常计入全部 2 项 Important
    assert lines[1] == "2 项 Important，0 项 Nit，0 项 Pre-existing"
    # 本轮新 Important 完整展开
    assert f_new.finding_id in rendered.body
    assert "本轮新发现的失败场景_UNIQUE_NEW_SCENARIO" in rendered.body
    assert "本轮核实证据_UNIQUE_NEW_EVIDENCE" in rendered.body
    # 前轮已贴出 Important 只保留紧凑引用摘要（ID + file:line），绝不重复贴出失败场景与核实证据
    assert f_prior.finding_id in rendered.body
    assert "pilot1742/prior.py:15" in rendered.body
    assert "前轮已贴出的超长失败场景说明_UNIQUE_PRIOR_SCENARIO" not in rendered.body
    assert "前轮核实证据_UNIQUE_PRIOR_EVIDENCE" not in rendered.body


def test_render_findings_comment_truncation_preserves_all_blocking_and_omitted_nits_stay_unposted() -> None:
    f_imp = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/core.py",
        line=88,
        category="状态机越权",
        failure_scenario="未校验签名直接发布状态",
        evidence="core.py:88 跳过验签",
        class_scope="发布路径共 2 处同类入口",
    )
    f_nit_small = _finding(
        severity=Severity.NIT,
        file="pilot1742/style.py",
        line=12,
        category="日志措辞",
        failure_scenario="缺少上下文编号",
        evidence="style.py:12 仅打印了短消息",
    )
    f_pre_huge = _finding(
        severity=Severity.PRE_EXISTING,
        file="pilot1742/legacy.py",
        line=5,
        category="历史债务",
        failure_scenario="旧代码未设超时",
        evidence="legacy.py:5 原本如此",
    )
    f_wontfix = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/old.py",
        line=3,
        category="旧缺陷",
        failure_scenario="旧问题设计如此",
        evidence="old.py:3",
    )
    f_rejected = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/false.py",
        line=7,
        category="误报",
        failure_scenario="核实不成立",
        evidence="false.py:7",
    )
    wf_reply = AuthorReply(f_wontfix.finding_id, None, None, "设计如此", "77", "alice")

    dec = evaluate_round(
        _verified_round(
            [
                _verified(f_imp, VerificationVerdict.CONFIRMED, verifier_evidence="核实第 88 行确实未验签"),
                _verified(f_nit_small, VerificationVerdict.CONFIRMED, verifier_evidence="短核实证据"),
                _verified(f_pre_huge, VerificationVerdict.CONFIRMED, verifier_evidence="B" * 600),
                _verified(f_wontfix, VerificationVerdict.RESOLVED_BY_WONTFIX, verifier_evidence="已核实不修理由", author_reply=wf_reply),
                _verified(f_rejected, VerificationVerdict.REJECTED, verifier_evidence="代码已有前置校验"),
            ],
            round_number=1,
            head_sha=HEAD_1,
        )
    )

    full = render_findings_comment(1928, HEAD_1, dec)
    assert full.truncated is False
    assert full.posted_fingerprints == frozenset({f_imp.finding_id, f_nit_small.finding_id, f_pre_huge.finding_id})
    assert full.omitted_non_blocking_fingerprints == frozenset()
    lines = full.body.splitlines()
    assert lines[0] == f"{COMMENT_MARKER_PREFIX} pr=1928 round=1 head={HEAD_1} -->"
    assert lines[1] == "1 项 Important，1 项 Nit，1 项 Pre-existing"
    assert f_imp.finding_id in full.body
    assert "pilot1742/core.py:88" in full.body
    assert "发布路径共 2 处同类入口" in full.body
    assert f"[{f_imp.finding_id}] 不修：<理由>" in full.body
    assert "### 非阻断项（Nit / Pre-existing）" in full.body
    assert "### 已解除与核实驳回摘要" in full.body

    # RoundDecision 不再暴露渲染前提前算好的 next_posted_fingerprints，避免误记已贴
    assert not hasattr(dec, "next_posted_fingerprints")

    # 预算略紧时：超长 Pre-existing 自动降级为紧凑单行版，当轮即可完整呈现而不会整条蒸发
    compact_fit = render_findings_comment(1928, HEAD_1, dec, max_chars=560)
    assert compact_fit.truncated is True
    assert len(compact_fit.body) <= 560
    assert f_imp.finding_id in compact_fit.body
    assert f_nit_small.finding_id in compact_fit.body
    assert f_pre_huge.finding_id in compact_fit.body
    assert compact_fit.posted_fingerprints == frozenset({f_imp.finding_id, f_nit_small.finding_id, f_pre_huge.finding_id})
    assert compact_fit.omitted_non_blocking == ()
    assert compact_fit.omitted_non_blocking_fingerprints == frozenset()

    # 极紧预算下：仅容得下阻断项 + 短 Nit，连 Pre-existing 最小单行也放不下 -> 记入 omitted_non_blocking 并跨轮自动补发
    tight_omit = render_findings_comment(1928, HEAD_1, dec, max_chars=510)
    assert tight_omit.truncated is True
    assert len(tight_omit.body) <= 510
    assert f_imp.finding_id in tight_omit.body
    assert f_nit_small.finding_id in tight_omit.body
    assert f_pre_huge.finding_id not in tight_omit.body
    assert tight_omit.posted_fingerprints == frozenset({f_imp.finding_id, f_nit_small.finding_id})
    assert tight_omit.omitted_non_blocking_fingerprints == frozenset({f_pre_huge.finding_id})
    assert [vf.finding.finding_id for vf in tight_omit.omitted_non_blocking] == [f_pre_huge.finding_id]

    # 唯一权威历史更新入口 to_history_entry(..., rendered=...) -> 第 2 轮新 diff 为空仍自动补发 f_pre_huge 并入账
    entry1 = dec.to_history_entry(HEAD_1, rendered=tight_omit)
    assert f_pre_huge.finding_id not in entry1.posted_fingerprints
    assert f_nit_small.finding_id in entry1.posted_fingerprints
    assert [vf.finding.finding_id for vf in entry1.pending_non_blocking] == [f_pre_huge.finding_id]

    plan2 = plan_next_round(BASE_SHA, HEAD_2, [entry1])
    assert f_pre_huge.finding_id not in plan2.already_posted_fingerprints
    assert [vf.finding.finding_id for vf in plan2.pending_non_blocking] == [f_pre_huge.finding_id]

    # 第 2 轮新 diff 不涉 legacy.py，仅修复了 f_imp -> 仍自动补发 f_pre_huge
    dec2 = evaluate_round(
        _verified_round(
            [_verified(f_imp, VerificationVerdict.RESOLVED_BY_FIX, verifier_evidence="第 2 轮已补验签")],
            round_number=plan2.round_number,
            head_sha=HEAD_2,
            history=[entry1],
        )
    )
    assert dec2.outcome == RoundOutcome.PASS
    assert [vf.finding.finding_id for vf in dec2.postable_findings] == [f_pre_huge.finding_id]
    rendered2 = render_findings_comment(1928, HEAD_2, dec2)
    assert f_pre_huge.finding_id in rendered2.body
    assert f_pre_huge.finding_id in rendered2.posted_fingerprints
    assert rendered2.omitted_non_blocking == ()

    entry2 = dec2.to_history_entry(HEAD_2, rendered=rendered2)
    assert f_pre_huge.finding_id in entry2.posted_fingerprints
    assert entry2.pending_non_blocking == ()

    plan3 = plan_next_round(BASE_SHA, HEAD_3, [entry1, entry2])
    assert f_pre_huge.finding_id in plan3.already_posted_fingerprints
    assert plan3.pending_non_blocking == ()


def test_render_findings_comment_70k_nit_degrades_to_compact_line_in_default_budget() -> None:
    """复审反例：第 1 轮 a.py Important + b.py Nit（70,000 字证据）在默认 65,536 预算下当轮降级呈现，绝不蒸发。"""
    f_imp = _finding(
        severity=Severity.IMPORTANT,
        file="a.py",
        line=10,
        category="状态损坏",
        failure_scenario="未校验输入导致状态损坏",
        evidence="a.py:10",
    )
    f_huge_nit = _finding(
        severity=Severity.NIT,
        file="b.py",
        line=25,
        category="日志冗余",
        failure_scenario="调试日志输出过多字段",
        evidence="b.py:25",
    )
    dec1 = evaluate_round(
        _verified_round(
            [
                _verified(f_imp, VerificationVerdict.CONFIRMED, verifier_evidence="核实 a.py:10 确有缺陷"),
                _verified(f_huge_nit, VerificationVerdict.CONFIRMED, verifier_evidence="E" * 70_000),
            ],
            round_number=1,
            head_sha=HEAD_1,
        )
    )
    assert not hasattr(dec1, "next_posted_fingerprints")

    rendered1 = render_findings_comment(1928, HEAD_1, dec1)
    assert rendered1.truncated is True
    assert len(rendered1.body) <= 65536
    assert f_imp.finding_id in rendered1.body
    assert f_huge_nit.finding_id in rendered1.body
    assert "[Nit]" in rendered1.body
    assert "b.py:25" in rendered1.body
    assert "日志冗余" in rendered1.body
    assert "调试日志输出过多字段" in rendered1.body
    assert rendered1.posted_fingerprints == frozenset({f_imp.finding_id, f_huge_nit.finding_id})
    assert rendered1.omitted_non_blocking == ()

    entry1 = dec1.to_history_entry(HEAD_1, rendered=rendered1)
    assert f_huge_nit.finding_id in entry1.posted_fingerprints
    assert entry1.pending_non_blocking == ()


def test_render_findings_comment_never_silently_drops_any_blocking_finding() -> None:
    blockers = [
        _finding(
            severity=Severity.IMPORTANT,
            file=f"pilot1742/mod_{i}.py",
            line=10 + i,
            category=f"严重缺陷{i}",
            failure_scenario=f"触发严重状态损坏场景_{i}_" + ("X" * 80),
            evidence=f"证据_{i}",
        )
        for i in range(5)
    ]
    dec = evaluate_round(
        _verified_round(
            [_verified(f, VerificationVerdict.CONFIRMED, verifier_evidence="V" * 120) for f in blockers],
            round_number=1,
            head_sha=HEAD_1,
        )
    )

    # 紧凑预算：放不下展开版阻断项，但放得下 header + 全部 5 项最小清单 + 少量说明
    tight = render_findings_comment(1928, HEAD_1, dec, max_chars=420)
    assert tight.truncated is True
    assert len(tight.body) <= 420
    assert tight.posted_fingerprints == frozenset(f.finding_id for f in blockers)
    for idx, f in enumerate(blockers):
        assert f"[{f.finding_id}]" in tight.body
        assert f"pilot1742/mod_{idx}.py:{10 + idx}" in tight.body

    # 预算连 header + 全部阻断项最小清单都放不下 -> 必须显式抛 ConvergenceError，绝不静默切掉任何阻断项
    with pytest.raises(ConvergenceError):
        render_findings_comment(1928, HEAD_1, dec, max_chars=180)


# ── 7. R6 根治回归：8 项 Important（5 项领域模型不变式 + 3 项 CommonMark 解析） ──


def test_r6_finding1_and_finding2_finder_batch_and_round_candidates_unbypassable_boundary() -> None:
    """R5 Finding 1 + Finding 2：FinderBatch 强校验、面板完备性、会话唯一性与连续历史链，禁止空批伪 PASS 与伪造历史。"""
    f_ok = _finding(source_models=("gpt-6-astra",))
    f_other = _finding(source_models=("gpt-6.1-sol",))

    # FinderBatch 拒绝空 model / 空 session_id / 空 head_sha / 混合或异源 findings
    with pytest.raises(ConvergenceError):
        FinderBatch(model="   ", session_id="s1", head_sha=HEAD_1, findings=())
    with pytest.raises(ConvergenceError):
        FinderBatch(model="gpt-6-astra", session_id="", head_sha=HEAD_1, findings=())
    with pytest.raises(ConvergenceError):
        FinderBatch(model="gpt-6-astra", session_id="s1", head_sha="   ", findings=())
    with pytest.raises(ConvergenceError):
        FinderBatch(model="gpt-6-astra", session_id="s1", head_sha=HEAD_1, findings=(f_other,))

    # 双 finder 面板传空批次或少传 1 批 -> 立即报错，绝不产生空候选伪 PASS
    with pytest.raises(ConvergenceError):
        build_round_candidates(
            round_number=1,
            head_sha=HEAD_1,
            panel=DEFAULT_PANEL,
            finder_batches=(),
        )
    with pytest.raises(ConvergenceError):
        build_round_candidates(
            round_number=1,
            head_sha=HEAD_1,
            panel=DEFAULT_PANEL,
            finder_batches=(FinderBatch(model="gpt-6-astra", session_id="s1", head_sha=HEAD_1, findings=(f_ok,)),),
        )

    # 模型多重集不匹配 -> 拒绝
    with pytest.raises(ConvergenceError):
        build_round_candidates(
            round_number=1,
            head_sha=HEAD_1,
            panel=DEFAULT_PANEL,
            finder_batches=(
                FinderBatch(model="gpt-6-astra", session_id="s1", head_sha=HEAD_1, findings=()),
                FinderBatch(model="gpt-6-astra", session_id="s2", head_sha=HEAD_1, findings=()),
            ),
        )

    # 同名双 finder 面板：重复 session_id 必须拒绝，不同 session_id 合法放行
    same_model_panel = ReviewPanel(
        finder_models=("gpt-6.1-sol", "gpt-6.1-sol"),
        verifier_model="claude-opus-5-5",
        require_verifier=True,
    )
    with pytest.raises(ConvergenceError):
        build_round_candidates(
            round_number=1,
            head_sha=HEAD_1,
            panel=same_model_panel,
            finder_batches=(
                FinderBatch(model="gpt-6.1-sol", session_id="dup-session", head_sha=HEAD_1, findings=()),
                FinderBatch(model="gpt-6.1-sol", session_id="dup-session", head_sha=HEAD_1, findings=()),
            ),
        )
    ok_same_model = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=same_model_panel,
        finder_batches=(
            FinderBatch(model="gpt-6.1-sol", session_id="sess-a", head_sha=HEAD_1, findings=(f_other,)),
            FinderBatch(model="gpt-6.1-sol", session_id="sess-b", head_sha=HEAD_1, findings=()),
        ),
    )
    assert len(ok_same_model.findings) == 1
    assert ok_same_model.prior_important == ()

    # 历史链长度必须严格等于 round_number - 1，且首轮或上一轮 PASS 后 prior_important 恒为空
    with pytest.raises(ConvergenceError):
        build_round_candidates(
            round_number=2,
            head_sha=HEAD_2,
            panel=DEFAULT_PANEL,
            finder_batches=_batches_for_panel([], round_number=2),
            history=(),
        )
    pass_entry = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r1-pass-1", "r1-pass-2"}),
        outcome=RoundOutcome.PASS,
    )
    cand_after_pass = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=2),
        history=(pass_entry,),
    )
    assert cand_after_pass.prior_important == ()

    # 历史中第 1 轮若记录了 panel，却塞入不在该 panel.finder_models 中的面板外模型 -> 构造即拒绝
    f_foreign = _finding(source_models=("gemini-2.5-pro",))
    with pytest.raises(ConvergenceError):
        RoundHistoryEntry(
            1,
            HEAD_1,
            frozenset({f_foreign.finding_id}),
            (f_foreign,),
            panel=DEFAULT_PANEL,
            finder_session_ids=frozenset({"r1-f1", "r1-f2"}),
        )


def test_r6_finding3_verifier_round_head_binding_and_resolved_by_fix_guard() -> None:
    """R5 Finding 3 反例：A 轮确认 -> B 轮 resolved_by_fix 得 PASS -> C 轮重现，重放 B 轮输出或改头标 resolved_by_fix 均拒收。"""
    head_a = "a" * 40
    head_b = "b" * 40
    head_c = "c" * 40
    f_a = _finding(severity=Severity.IMPORTANT, file="p.py", line=12, category="竞态", failure_scenario="写丢数据")

    # Round 1 (head A): 确认 p.py:12 Important
    cand_a = build_round_candidates(
        round_number=1,
        head_sha=head_a,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_a], round_number=1, head_sha=head_a),
    )
    ver_a = parse_verifier_output(
        {
            "round_number": 1,
            "head_sha": head_a,
            "verdicts": [{"finding_id": f_a.finding_id, "verdict": "confirmed", "verifier_evidence": "checked A"}],
        },
        cand_a,
        verifier_model="claude-opus-5-5",
    )
    dec_a = evaluate_round(ver_a)
    rendered_a = render_findings_comment(1928, head_a, dec_a)
    entry_a = dec_a.to_history_entry(rendered=rendered_a)
    assert entry_a.outcome == RoundOutcome.BLOCKED
    assert entry_a.panel == DEFAULT_PANEL
    assert entry_a.head_sha == head_a

    # Round 2 (head B): 核实 resolved_by_fix -> PASS
    cand_b = build_round_candidates(
        round_number=2,
        head_sha=head_b,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=2, head_sha=head_b),
        history=(entry_a,),
    )
    verifier_json_b = {
        "round_number": 2,
        "head_sha": head_b,
        "verdicts": [{"finding_id": f_a.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "checked B"}],
    }
    ver_b = parse_verifier_output(verifier_json_b, cand_b, verifier_model="claude-opus-5-5")
    dec_b = evaluate_round(ver_b)
    rendered_b = render_findings_comment(1928, head_b, dec_b)
    entry_b = dec_b.to_history_entry(rendered=rendered_b)
    assert dec_b.outcome == RoundOutcome.PASS
    assert entry_b.outcome == RoundOutcome.PASS

    # Round 3 (head C): finder 在 p.py:20 再次报同指纹问题
    f_c = _finding(severity=Severity.IMPORTANT, file="p.py", line=20, category="竞态", failure_scenario="写丢数据")
    assert f_c.finding_id == f_a.finding_id
    cand_c = build_round_candidates(
        round_number=3,
        head_sha=head_c,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_c], round_number=3, head_sha=head_c),
        history=(entry_a, entry_b),
    )
    assert cand_c.prior_important == ()

    # 反例 3a：直接重放 B 轮核实 JSON 到 C 轮 -> 因 round_number/head_sha 不匹配立即拒绝
    with pytest.raises(ConvergenceError):
        parse_verifier_output(verifier_json_b, cand_c, verifier_model="claude-opus-5-5")

    # 反例 3b：缺失 round_number / head_sha 或传 bool round_number -> 立即拒绝
    for bad_payload in (
        {"head_sha": head_c, "verdicts": [{"finding_id": f_c.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
        {"round_number": 3, "verdicts": [{"finding_id": f_c.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
        {"round_number": True, "head_sha": head_c, "verdicts": [{"finding_id": f_c.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
    ):
        with pytest.raises(ConvergenceError):
            parse_verifier_output(bad_payload, cand_c, verifier_model="claude-opus-5-5")

    # 反例 3c：即使改写 round_number=3, head_sha=head_c，但该问题在 B 轮已 PASS 不在 C 轮 prior_important 中，仍禁止 resolved_by_fix！
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {
                "round_number": 3,
                "head_sha": head_c,
                "verdicts": [{"finding_id": f_c.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "企图绕过"}],
            },
            cand_c,
            verifier_model="claude-opus-5-5",
        )

    # 合法误报应标 false_positive（映射为 REJECTED）
    ver_c_fp = parse_verifier_output(
        {
            "round_number": 3,
            "head_sha": head_c,
            "verdicts": [{"finding_id": f_c.finding_id, "verdict": "false_positive", "verifier_evidence": "C 轮已有锁保护"}],
        },
        cand_c,
        verifier_model="claude-opus-5-5",
    )
    assert ver_c_fp.verdicts[0].verdict is VerificationVerdict.REJECTED

    # evaluate_round 拒绝非 VerifiedRound 松散入参
    with pytest.raises(ConvergenceError):
        evaluate_round(ver_c_fp.verdicts)  # type: ignore[arg-type]


def test_r6_finding4_cross_round_merge_preserves_current_round_location_and_evidence() -> None:
    """R5 Finding 4 反例：前轮 p.py:12 未解除，新 HEAD 移至 p.py:20 -> 合并后保留第 20 行与本轮证据，锁定 Important。"""
    f_r1 = _finding(
        severity=Severity.IMPORTANT,
        file="p.py",
        line=12,
        category="空值解引用",
        failure_scenario="缺失校验导致崩盘",
        evidence="第 1 轮在 p.py:12 发现的超长历史证据内容，长度刻意远超第 2 轮证据",
        source_models=("gpt-6-astra",),
    )
    entry1 = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset({f_r1.finding_id}),
        (f_r1,),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r1-m1", "r1-m2"}),
    )

    # 第 2 轮代码挪到第 20 行，本轮 finder 报第 20 行（即便标 Nit 且证据更短）
    f_r2 = _finding(
        severity=Severity.NIT,
        file="p.py",
        line=20,
        category="空值解引用",
        failure_scenario="缺失校验导致崩盘",
        evidence="第 2 轮新定位 p.py:20",
        source_models=("gpt-6.1-sol",),
    )
    assert f_r2.finding_id == f_r1.finding_id
    cand2 = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=(
            FinderBatch(model="gpt-6-astra", session_id="r2-s1", head_sha=HEAD_2, findings=()),
            FinderBatch(model="gpt-6.1-sol", session_id="r2-s2", head_sha=HEAD_2, findings=(f_r2,)),
        ),
        history=(entry1,),
    )
    assert len(cand2.findings) == 1
    merged = cand2.findings[0]
    assert merged.line == 20
    assert merged.severity is Severity.IMPORTANT
    assert merged.evidence == "第 2 轮新定位 p.py:20"
    assert merged.source_models == ("gpt-6-astra", "gpt-6.1-sol")

    # 在旧第 12 行回复无法匹配；在新第 20 行回复成功唯一匹配并解除！
    reply_old_line = parse_wontfix_replies(
        [{"id": 601, "author": "alice", "path": "p.py", "line": 12, "body": "不修：旧行号理由"}],
        allowed_authors={"alice"},
    )
    assert bind_author_replies(cand2.findings, reply_old_line) == {}

    reply_new_line = parse_wontfix_replies(
        [{"id": 602, "author": "alice", "path": "p.py", "line": 20, "body": "不修：新行号调用方已保证非空"}],
        allowed_authors={"alice"},
    )
    ver2 = parse_verifier_output(
        _verifier_payload(
            cand2,
            [{"finding_id": merged.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "核实第 20 行理由成立"}],
        ),
        cand2,
        verifier_model="claude-opus-5-5",
        author_replies=reply_new_line,
    )
    assert ver2.verdicts[0].author_reply is not None
    assert ver2.verdicts[0].author_reply.line == 20


def test_r6_finding5_consumed_reply_key_decoupled_from_directive_order() -> None:
    """R5 Finding 5 反例：评论 id=1 先消费 [A]，第 3 轮仅在其前插入 [B] -> [A] 仍已消费，[B] 可正常用于 B。"""
    f_a = _finding(file="a.py", line=10, category="catA", failure_scenario="scenA")
    f_b = _finding(file="b.py", line=20, category="catB", failure_scenario="scenB")

    # 第 1 轮确认 A
    dec1 = evaluate_round(_verified_round([_verified(f_a, VerificationVerdict.CONFIRMED)], round_number=1, head_sha=HEAD_1))
    entry1 = dec1.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1))

    # 第 2 轮评论 id=1 含 [A] 不修：说明 并消费
    comment_r2 = [{"id": 1, "author": "alice", "body": f"[{f_a.finding_id}] 不修：说明"}]
    replies_r2 = parse_wontfix_replies(comment_r2, allowed_authors={"alice"})
    assert len(replies_r2) == 1
    assert replies_r2[0].reply_key == f"comment:1:finding:{f_a.finding_id}"

    cand2 = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=2),
        history=(entry1,),
    )
    ver2 = parse_verifier_output(
        _verifier_payload(
            cand2,
            [{"finding_id": f_a.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "采信 A 不修"}],
        ),
        cand2,
        verifier_model="claude-opus-5-5",
        author_replies=replies_r2,
    )
    dec2 = evaluate_round(ver2)
    entry2 = dec2.to_history_entry(rendered=render_findings_comment(1928, HEAD_2, dec2))
    assert f"comment:1:finding:{f_a.finding_id}" in entry2.consumed_reply_keys
    assert f"comment:1:resolved:{f_a.finding_id}" in entry2.consumed_reply_keys

    # 第 3 轮：A 重开且新发现 B；作者编辑评论 id=1，仅在 [A] 前面插入 [B] 不修：新说明
    comment_r3_prepended = [
        {
            "id": 1,
            "author": "alice",
            "body": f"[{f_b.finding_id}] 不修：新说明\n[{f_a.finding_id}] 不修：说明",
        }
    ]
    replies_r3 = parse_wontfix_replies(comment_r3_prepended, allowed_authors={"alice"})
    assert len(replies_r3) == 2
    cand3 = build_round_candidates(
        round_number=3,
        head_sha=HEAD_3,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_a, f_b], round_number=3),
        history=(entry1, entry2),
    )

    # [A] 仍被判已消费，试图解除 A 必须失败！
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand3,
                [
                    {"finding_id": f_a.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图借插行重放 A"},
                    {"finding_id": f_b.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "采信 B"},
                ],
            ),
            cand3,
            verifier_model="claude-opus-5-5",
            author_replies=replies_r3,
        )

    # 即使作者把评论 1 里的 [A] 改成短前缀 8 位，comment:1:resolved:<fp> 仍彻底封杀复用！
    comment_r3_short_prefix = [
        {
            "id": 1,
            "author": "alice",
            "body": f"[{f_b.finding_id}] 不修：新说明\n[{f_a.finding_id[:8]}] 不修：改短前缀重放",
        }
    ]
    replies_r3_short = parse_wontfix_replies(comment_r3_short_prefix, allowed_authors={"alice"})
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand3,
                [
                    {"finding_id": f_a.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "短前缀绕过"},
                    {"finding_id": f_b.finding_id, "verdict": "confirmed", "verifier_evidence": "B 成立"},
                ],
            ),
            cand3,
            verifier_model="claude-opus-5-5",
            author_replies=replies_r3_short,
        )

    # 而新插入的 [B] 可以合法解除 B（A 维持 confirmed）
    ver3_ok = parse_verifier_output(
        _verifier_payload(
            cand3,
            [
                {"finding_id": f_a.finding_id, "verdict": "confirmed", "verifier_evidence": "A 仍存在"},
                {"finding_id": f_b.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "采信新插入的 B"},
            ],
        ),
        cand3,
        verifier_model="claude-opus-5-5",
        author_replies=replies_r3,
    )
    by_id = {vf.finding.finding_id: vf for vf in ver3_ok.verdicts}
    assert by_id[f_b.finding_id].author_reply is not None
    assert by_id[f_b.finding_id].author_reply.reason == "新说明"

    # 同评论内针对同一 target_finding_id 的重复相同指令去重；冲突不同理由指令保留至下游按解析后目标整组拒收
    dup_same = parse_wontfix_replies(
        [{"id": 9, "author": "alice", "body": f"[{f_a.finding_id}] 不修：同理由\n[{f_a.finding_id}] 不修：同理由"}],
        allowed_authors={"alice"},
    )
    assert len(dup_same) == 1
    conflict_diff = parse_wontfix_replies(
        [{"id": 10, "author": "alice", "body": f"[{f_a.finding_id}] 不修：理由甲\n[{f_a.finding_id}] 不修：理由乙"}],
        allowed_authors={"alice"},
    )
    assert len(conflict_diff) == 2
    assert bind_author_replies([f_a], conflict_diff) == {}
    cand_conflict_id = _candidates([f_a])
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand_conflict_id,
                [{"finding_id": f_a.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "冲突指令不得放行"}],
            ),
            cand_conflict_id,
            verifier_model="claude-opus-5-5",
            author_replies=conflict_diff,
        )


def test_r6_finding6_finding7_finding8_commonmark_inline_linkdef_and_line_endings() -> None:
    """R5 Finding 6/7/8：CommonMark §2.1 断行、§4.7 链接引用定义与 Setext 交互、§6 行内扫描器离线回归。"""
    d = "[abc12345] 不修：示例"
    d2 = "[def67890] 不修：真实理由"

    def parse_body(body: str) -> list[str | None]:
        return [
            r.finding_id
            for r in parse_wontfix_replies(
                [{"id": 800, "user": {"login": "alice", "type": "User"}, "body": body}],
                allowed_authors={"alice"},
            )
        ]

    # Finding 8: 禁止 str.splitlines() 将 Unicode / 控制分隔符视作换行
    assert parse_body(f"说明\u2028{d}") == []
    assert parse_body(f"\u2028{d}") == []
    assert parse_body(f"说明\u2029{d}") == []
    assert parse_body(f"说明\x0b{d}") == []
    assert parse_body(f"说明\x0c{d}") == []
    assert parse_body(f"说明\x85{d}") == []
    assert parse_body(f"说明\r\n{d2}") == ["def67890"]
    assert parse_body(f"说明\r{d2}") == ["def67890"]
    assert parse_body(f"说明\x00\n{d2}") == ["def67890"]

    # Finding 7: CommonMark §4.7 链接引用定义剥离（双引号/单引号/圆括号/多行目标与标题/回退/Setext 交互）
    assert parse_body(f'见下\n\n[x]: /demo "说明\n{d}\n"') == []
    assert parse_body(f"见下\n\n[x]: /demo '说明\n{d}\n'") == []
    assert parse_body(f"见下\n\n[x]: /demo (说明\n{d}\n)") == []
    assert parse_body(f'[x]:\n  </demo>\n  "说明\n{d}\n"') == []
    assert parse_body(f'[x]: /demo "说明\n{d}\n"\n{d2}') == ["def67890"]
    assert parse_body(f"[x]: /demo\n===\n{d2}") == ["def67890"]
    assert parse_body(f"[x]: /demo\n---\n{d2}") == ["def67890"]
    assert parse_body(f"[x]: /demo\n{d}\n===") == []
    assert parse_body(f'[x]: /demo\n"title" {d2}') == []
    assert parse_body(f'[x]: /demo "title" ok\n{d2}') == ["def67890"]

    # Finding 6: CommonMark §6 段落行内扫描器（代码跨度/多行 HTML 属性与注释/行内链接/图片/反斜杠转义/未闭合反引号）
    assert parse_body(f"说明 `示例\n{d}\n结束`") == []
    assert parse_body(f"说明 ``示例 ` \n{d}\n结束``") == []
    assert parse_body(f"`<!--`\n{d2}\n`-->`") == ["def67890"]
    assert parse_body(f'说明 <span title="\n{d}\n">内容</span>') == []
    assert parse_body(f'<span title="a>b\n{d}\n">x</span>') == []
    assert parse_body(f'<span title="\n{d}\n">{d2}</span>') == ["def67890"]
    assert parse_body(f"<!-->\n{d}") == []
    assert parse_body(f"<!--->\n{d}") == []
    assert parse_body(f"x <!-->\n{d2}") == ["def67890"]
    assert parse_body(f"<?>\n{d}") == []
    assert parse_body(f'[x](/u "\n{d}\n")') == []
    assert parse_body(f'[x](/u "\n{d}\n")\n{d2}') == ["def67890"]
    assert parse_body(f'![\n{d}\n](/u "\n{d}\n")') == []
    assert parse_body(f"[img]: /u\n\n![\n{d}\n][img]") == []
    assert parse_body(f"<https://example.com> {d}") == []
    assert parse_body(f"\\`\n{d2}\n\\`") == ["def67890"]
    assert parse_body(f'\\<span title="\n{d2}\n">') == ["def67890"]
    assert parse_body(f'\\[x](/u "\n{d2}\n")') == ["def67890"]
    assert parse_body(f"说明 ``未闭合\n{d2}") == ["def67890"]


# ── 8. R7 全链路根治回归：Codex R6 全部 11 项 Important 最小反例 ──────────────


def test_r7_finding1_verified_finding_binds_round_and_head_blocking_cross_round_replay() -> None:
    """R6 Finding 1 反例：第 1 轮 confirmed -> 第 2 轮 resolved_by_fix -> 第 3 轮重开 confirmed -> 第 4 轮 VerifiedRound(c4, v2.verdicts) 必须拒收。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/replay.py", line=10, category="竞态", failure_scenario="写丢状态")

    # Round 1: confirmed
    c1 = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f1], round_number=1, head_sha=HEAD_1),
    )
    v1 = parse_verifier_output(
        _verifier_payload(c1, [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "r1"}]),
        c1,
        verifier_model="claude-opus-5-5",
    )
    assert v1.verdicts[0].round_number == 1
    assert v1.verdicts[0].head_sha == HEAD_1
    dec1 = evaluate_round(v1)
    e1 = dec1.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1))

    # Round 2: resolved_by_fix -> PASS
    c2 = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=2, head_sha=HEAD_2),
        history=(e1,),
    )
    v2 = parse_verifier_output(
        _verifier_payload(c2, [{"finding_id": f1.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "r2 fixed"}]),
        c2,
        verifier_model="claude-opus-5-5",
    )
    assert v2.verdicts[0].round_number == 2
    assert v2.verdicts[0].head_sha == HEAD_2
    dec2 = evaluate_round(v2)
    e2 = dec2.to_history_entry(rendered=render_findings_comment(1928, HEAD_2, dec2))
    assert dec2.outcome == RoundOutcome.PASS

    # Round 3: reopened & confirmed
    c3 = build_round_candidates(
        round_number=3,
        head_sha=HEAD_3,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f1], round_number=3, head_sha=HEAD_3),
        history=(e1, e2),
    )
    v3 = parse_verifier_output(
        _verifier_payload(c3, [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "r3 reopened"}]),
        c3,
        verifier_model="claude-opus-5-5",
    )
    dec3 = evaluate_round(v3)
    e3 = dec3.to_history_entry(rendered=render_findings_comment(1928, HEAD_3, dec3))

    # Round 4: f1 in prior_important -> 企图重放 v2.verdicts（round=2, head=HEAD_2）到 c4 必须立即报错
    c4 = build_round_candidates(
        round_number=4,
        head_sha=HEAD_4,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=4, head_sha=HEAD_4),
        history=(e1, e2, e3),
    )
    with pytest.raises(ConvergenceError):
        VerifiedRound(c4, v2.verdicts)

    # 非法 round_number / 空 head_sha 的 VerifiedFinding 构造期即拒绝
    with pytest.raises(ConvergenceError):
        VerifiedFinding(f1, VerificationVerdict.CONFIRMED, "claude-opus-5-5", "ok", round_number=0, head_sha=HEAD_1)
    with pytest.raises(ConvergenceError):
        VerifiedFinding(f1, VerificationVerdict.CONFIRMED, "claude-opus-5-5", "ok", round_number=1, head_sha="  ")


def test_r7_finding2_finder_batch_binds_head_sha_and_forbids_cross_round_session_reuse() -> None:
    """R6 Finding 2 反例：HEAD A 的 finder_batches 原样传入 HEAD B 第 2 轮或同 HEAD 复用旧 session_id 必须立即拒收。"""
    f1 = _finding(severity=Severity.IMPORTANT)
    c1 = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f1], round_number=1, head_sha=HEAD_1),
    )
    v1 = parse_verifier_output(
        _verifier_payload(c1, [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "r1"}]),
        c1,
        verifier_model="claude-opus-5-5",
    )
    dec1 = evaluate_round(v1)
    e1 = dec1.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1))
    assert e1.finder_session_ids == frozenset({"r1-slot-1", "r1-slot-2"})

    # 1) HEAD A 的 c1.finder_batches 原样传入 HEAD B 第 2 轮 -> 立即拒收
    with pytest.raises(ConvergenceError):
        build_round_candidates(
            round_number=2,
            head_sha=HEAD_2,
            panel=DEFAULT_PANEL,
            finder_batches=c1.finder_batches,
            history=(e1,),
        )
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=2,
            head_sha=HEAD_2,
            panel=DEFAULT_PANEL,
            finder_batches=c1.finder_batches,
            history=(e1,),
        )

    # 2) 即使同 head_sha 重跑，也不得复用历史轮次已用过的 session_id
    reused_same_head_batches = (
        FinderBatch(model="gpt-6-astra", session_id="r1-slot-1", head_sha=HEAD_1, findings=()),
        FinderBatch(model="gpt-6.1-sol", session_id="r2-fresh-2", head_sha=HEAD_1, findings=()),
    )
    with pytest.raises(ConvergenceError):
        build_round_candidates(
            round_number=2,
            head_sha=HEAD_1,
            panel=DEFAULT_PANEL,
            finder_batches=reused_same_head_batches,
            history=(e1,),
        )


def test_r7_finding3_and_finding5_required_history_panel_and_settled_history_cross_family() -> None:
    """R6 Finding 3 + Finding 5：RoundHistoryEntry.panel 必填封死注入；已结清历史发现不阻拦后续新面板换用原 finder 家族作核实者。"""
    # Finding 3a: 省略 panel 构造 RoundHistoryEntry 立即报 TypeError；传 panel=None 报 ConvergenceError
    f_gemini = _finding(severity=Severity.IMPORTANT, source_models=("gemini-2.5-pro",))
    with pytest.raises(TypeError):
        RoundHistoryEntry(
            1,
            HEAD_1,
            frozenset({f_gemini.finding_id}),
            (f_gemini,),
            finder_session_ids=frozenset({"r1-s1", "r1-s2"}),
        )  # type: ignore[call-arg]
    with pytest.raises(ConvergenceError):
        RoundHistoryEntry(
            1,
            HEAD_1,
            frozenset({f_gemini.finding_id}),
            (f_gemini,),
            panel=None,  # type: ignore[arg-type]
            finder_session_ids=frozenset({"r1-s1", "r1-s2"}),
        )

    # Finding 3b: 无法把 gemini_finding 注入双 GPT 历史链（首轮及后续轮均拒收）
    with pytest.raises(ConvergenceError):
        RoundHistoryEntry(
            1,
            HEAD_1,
            frozenset({f_gemini.finding_id}),
            (f_gemini,),
            panel=DEFAULT_PANEL,
            finder_session_ids=frozenset({"r1-s1", "r1-s2"}),
        )
    e1_pass = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r1-p1", "r1-p2"}),
        outcome=RoundOutcome.PASS,
    )
    e2_forged = RoundHistoryEntry(
        2,
        HEAD_2,
        frozenset({f_gemini.finding_id}),
        (f_gemini,),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r2-p1", "r2-p2"}),
    )
    with pytest.raises(ConvergenceError):
        build_round_candidates(
            round_number=3,
            head_sha=HEAD_3,
            panel=DEFAULT_PANEL,
            finder_batches=_batches_for_panel([], round_number=3, head_sha=HEAD_3),
            history=(e1_pass, e2_forged),
        )

    # Finding 5: 第 1 轮 GPT 发现/Claude 确认 -> 第 2 轮修复并 PASS -> 第 3 轮改双 Gemini finder + GPT verifier 且无结转 -> 正常通过！
    f_gpt = _finding(severity=Severity.IMPORTANT, file="pilot1742/f5.py", line=15, source_models=("gpt-6-astra",))
    c1 = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_gpt], round_number=1, head_sha=HEAD_1),
    )
    v1 = parse_verifier_output(
        _verifier_payload(c1, [{"finding_id": f_gpt.finding_id, "verdict": "confirmed", "verifier_evidence": "r1"}]),
        c1,
        verifier_model="claude-opus-5-5",
    )
    dec1 = evaluate_round(v1)
    entry1 = dec1.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1))

    c2 = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=2, head_sha=HEAD_2),
        history=(entry1,),
    )
    v2 = parse_verifier_output(
        _verifier_payload(c2, [{"finding_id": f_gpt.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "fixed"}]),
        c2,
        verifier_model="claude-opus-5-5",
    )
    dec2 = evaluate_round(v2)
    entry2 = dec2.to_history_entry(rendered=render_findings_comment(1928, HEAD_2, dec2))
    assert dec2.outcome == RoundOutcome.PASS

    gemini_finders_gpt_verifier = ReviewPanel(
        finder_models=("gemini-4-neon", "gemini-2.5-pro"),
        verifier_model="gpt-6.1-sol",
        require_verifier=True,
    )
    f_r3_gemini = _finding(
        severity=Severity.NIT,
        file="pilot1742/new_mod.py",
        line=8,
        category="命名",
        failure_scenario="变量命名可更直观",
        source_models=("gemini-4-neon",),
    )
    c3 = build_round_candidates(
        round_number=3,
        head_sha=HEAD_3,
        panel=gemini_finders_gpt_verifier,
        finder_batches=_batches_for_panel([f_r3_gemini], panel=gemini_finders_gpt_verifier, round_number=3, head_sha=HEAD_3),
        history=(entry1, entry2),
    )
    assert c3.prior_important == ()
    v3 = parse_verifier_output(
        _verifier_payload(c3, [{"finding_id": f_r3_gemini.finding_id, "verdict": "confirmed", "verifier_evidence": "nit ok"}]),
        c3,
        verifier_model="gpt-6.1-sol",
    )
    dec3 = evaluate_round(v3)
    assert dec3.outcome == RoundOutcome.PASS

    # 对照：若第 1 轮 GPT 发现尚未结清（仍在第 2 轮 prior_important 中），第 2 轮改用 GPT verifier 仍必须拒收
    with pytest.raises(ConvergenceError):
        build_round_candidates(
            round_number=2,
            head_sha=HEAD_2,
            panel=gemini_finders_gpt_verifier,
            finder_batches=_batches_for_panel([], panel=gemini_finders_gpt_verifier, round_number=2, head_sha=HEAD_2),
            history=(entry1,),
        )


def test_r7_finding4_verified_round_validates_author_reply_target_matching() -> None:
    """R6 Finding 4 反例：指向其他指纹/坐标/过期行内/歧义目标的回复塞进 resolved_by_wontfix 必须立即拒收。"""
    f_a = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42, category="c1", failure_scenario="s1")
    f_b = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=88, category="c2", failure_scenario="s2")
    assert f_a.finding_id != "abcdef"
    cand_single = _candidates([f_a], round_number=1, head_sha=HEAD_1)
    cand_pair = _candidates([f_a, f_b], round_number=1, head_sha=HEAD_1)

    # 1) 指向 abcdef 的回复塞给 f_a -> 立即抛 ConvergenceError
    wrong_id_reply = AuthorReply("abcdef", None, None, "无关回复", "901", "alice")
    with pytest.raises(ConvergenceError):
        VerifiedRound(
            cand_single,
            (
                VerifiedFinding(
                    finding=f_a,
                    verdict=VerificationVerdict.RESOLVED_BY_WONTFIX,
                    verifier_model="claude-opus-5-5",
                    verifier_evidence="伪造绑定",
                    round_number=1,
                    head_sha=HEAD_1,
                    author_reply=wrong_id_reply,
                ),
            ),
        )

    # 2) 错误 file:line 坐标回复塞给 f_a -> 立即抛 ConvergenceError
    wrong_loc_reply = AuthorReply(None, "pilot1742/demo.py", 999, "错误行号", "902", "alice")
    with pytest.raises(ConvergenceError):
        VerifiedFinding(
            finding=f_a,
            verdict=VerificationVerdict.RESOLVED_BY_WONTFIX,
            verifier_model="claude-opus-5-5",
            verifier_evidence="错误行号",
            round_number=1,
            head_sha=HEAD_1,
            author_reply=wrong_loc_reply,
        )

    # 3) 过期行内评论（line=None, is_inline_anchor=True）-> 立即抛 ConvergenceError
    outdated_inline_reply = AuthorReply(None, "pilot1742/demo.py", None, "过期评论", "903", "alice", is_inline_anchor=True)
    with pytest.raises(ConvergenceError):
        VerifiedFinding(
            finding=f_a,
            verdict=VerificationVerdict.RESOLVED_BY_WONTFIX,
            verifier_model="claude-opus-5-5",
            verifier_evidence="过期评论",
            round_number=1,
            head_sha=HEAD_1,
            author_reply=outdated_inline_reply,
        )

    # 4) 仅文件级回复在单发现上成立，但在双同文件发现候选集上存在歧义 -> VerifiedRound 立即抛 ConvergenceError
    ambig_file_reply = AuthorReply(None, "pilot1742/demo.py", None, "整文件不修", "904", "alice")
    vf_a_ambig = VerifiedFinding(
        finding=f_a,
        verdict=VerificationVerdict.RESOLVED_BY_WONTFIX,
        verifier_model="claude-opus-5-5",
        verifier_evidence="试图用歧义文件回复解除 f_a",
        round_number=1,
        head_sha=HEAD_1,
        author_reply=ambig_file_reply,
    )
    vf_b_ok = VerifiedFinding(
        finding=f_b,
        verdict=VerificationVerdict.CONFIRMED,
        verifier_model="claude-opus-5-5",
        verifier_evidence="仍成立",
        round_number=1,
        head_sha=HEAD_1,
    )
    with pytest.raises(ConvergenceError):
        VerifiedRound(cand_pair, (vf_a_ambig, vf_b_ok))


def test_r7_finding6_outdated_github_inline_comment_never_falls_back_to_original_line() -> None:
    """R6 Finding 6 反例：line=None, original_line=42 的过期评论无显式目标时不得误绑到当前 HEAD 第 42 行新发现。"""
    f_new = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="新缺陷",
        failure_scenario="新提交在第 42 行引入的空指针",
    )
    outdated_inline = [
        {
            "id": 701,
            "user": {"login": "alice", "type": "User"},
            "path": "pilot1742/demo.py",
            "line": None,
            "original_line": 42,
            "original_commit_id": HEAD_1,
            "body": "不修：旧问题无需改",
        }
    ]
    replies = parse_wontfix_replies(outdated_inline, allowed_authors={"alice"})
    assert all(r.line is None for r in replies)
    assert bind_author_replies([f_new], replies) == {}

    # 过期评论若正文写了显式 [finding_id]，仍可按指纹精确绑定
    outdated_with_explicit_id = [
        {
            "id": 702,
            "user": {"login": "alice", "type": "User"},
            "path": "pilot1742/demo.py",
            "line": None,
            "original_line": 42,
            "original_commit_id": HEAD_1,
            "body": f"[{f_new.finding_id}] 不修：显式指纹明确确认不修",
        }
    ]
    replies_explicit = parse_wontfix_replies(outdated_with_explicit_id, allowed_authors={"alice"})
    bound_explicit = bind_author_replies([f_new], replies_explicit)
    assert set(bound_explicit.keys()) == {f_new.finding_id}
    assert bound_explicit[f_new.finding_id].reason == "显式指纹明确确认不修"


def test_r7_finding7_explicit_file_line_reply_key_no_collision_and_conflict_guard() -> None:
    """R6 Finding 7 反例：同评论 id=9 含 a.py:1 与 b.py:2 同理由指令，第 1 轮消费 A 后第 2 轮 B 仍有效且可解除 B。"""
    f_a = _finding(severity=Severity.IMPORTANT, file="a.py", line=1, category="cA", failure_scenario="sA")
    f_b = _finding(severity=Severity.IMPORTANT, file="b.py", line=2, category="cB", failure_scenario="sB")

    comment_9 = [
        {
            "id": 9,
            "user": {"login": "alice", "type": "User"},
            "body": "a.py:1 不修：兼容性\nb.py:2 不修：兼容性",
        }
    ]
    replies = parse_wontfix_replies(comment_9, allowed_authors={"alice"})
    assert len(replies) == 2
    assert replies[0].reply_key == "comment:9:loc:a.py:1"
    assert replies[1].reply_key == "comment:9:loc:b.py:2"
    assert replies[0].reply_key != replies[1].reply_key

    # 第 1 轮：消费 A（A 解除，B 仍确认阻断）
    c1 = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_a, f_b], round_number=1, head_sha=HEAD_1),
    )
    v1 = parse_verifier_output(
        _verifier_payload(
            c1,
            [
                {"finding_id": f_a.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "采信 A 兼容性理由"},
                {"finding_id": f_b.finding_id, "verdict": "confirmed", "verifier_evidence": "B 待进一步核查"},
            ],
        ),
        c1,
        verifier_model="claude-opus-5-5",
        author_replies=replies,
    )
    dec1 = evaluate_round(v1)
    e1 = dec1.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1))
    assert "comment:9:loc:a.py:1" in e1.consumed_reply_keys
    assert f"comment:9:resolved:{f_a.finding_id}" in e1.consumed_reply_keys
    assert "comment:9:loc:b.py:2" not in e1.consumed_reply_keys

    # 第 2 轮：B 在新 HEAD 重新定位后，B 对应回复依然有效且可正常解除 B
    plan2 = plan_next_round(BASE_SHA, HEAD_2, [e1], author_replies=replies)
    assert [r.reply_key for r in plan2.author_replies] == ["comment:9:loc:b.py:2"]
    c2 = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_b], round_number=2, head_sha=HEAD_2),
        history=plan2.history,
    )
    v2 = parse_verifier_output(
        _verifier_payload(
            c2,
            [{"finding_id": f_b.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "第 2 轮采信 B 兼容性理由"}],
        ),
        c2,
        verifier_model="claude-opus-5-5",
        author_replies=plan2.author_replies,
        consumed_reply_keys=plan2.consumed_reply_keys,
    )
    dec2 = evaluate_round(v2)
    assert dec2.outcome == RoundOutcome.PASS
    assert v2.verdicts[0].author_reply is not None
    assert v2.verdicts[0].author_reply.reply_key == "comment:9:loc:b.py:2"

    # 同评论内针对同一 (target_file, target_line) 同理由去重、不同理由保留至下游按解析后目标整组拒收
    dup_loc = parse_wontfix_replies(
        [{"id": 10, "author": "alice", "body": "a.py:1 不修：同理由\na.py:1 不修：同理由"}],
        allowed_authors={"alice"},
    )
    assert len(dup_loc) == 1
    conflict_loc = parse_wontfix_replies(
        [{"id": 11, "author": "alice", "body": "a.py:1 不修：理由甲\na.py:1 不修：理由乙"}],
        allowed_authors={"alice"},
    )
    assert len(conflict_loc) == 2
    assert bind_author_replies([f_a], conflict_loc) == {}
    cand_conflict_loc = _candidates([f_a])
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand_conflict_loc,
                [{"finding_id": f_a.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "冲突坐标指令不得放行"}],
            ),
            cand_conflict_loc,
            verifier_model="claude-opus-5-5",
            author_replies=conflict_loc,
        )
    direct_conflict = [
        AuthorReply(None, "a.py", 1, "理由甲", "12", "alice"),
        AuthorReply(None, "a.py", 1, "理由乙", "12", "alice"),
    ]
    assert bind_author_replies([f_a], direct_conflict) == {}


def test_r7_finding8_finding9_finding10_commonmark_ascii_digits_inline_html_tags_and_code_span_reasons() -> None:
    """R6 Finding 8 + Finding 9 + Finding 10：全角数字禁作列表、配对行内抑制标签屏蔽、行内代码理由保真与禁零宽空理由。"""
    fid = "a98df8e465064919"

    def parse_one(body: str) -> tuple[AuthorReply, ...]:
        return parse_wontfix_replies(
            [{"id": 880, "user": {"login": "alice", "type": "User"}, "body": body}],
            allowed_authors={"alice"},
        )

    # Finding 8: 仅允许 ASCII [0-9] 作为有序列表标记，全角数字 ２. / 阿拉伯-印度数字 ١. 不得中断引用块
    assert parse_one(f"> 引用\n２. [{fid}] 不修：示例") == ()
    assert parse_one(f"> 引用\n١. [{fid}] 不修：示例") == ()
    ascii_list_interrupt = parse_one(f"> 引用\n2. [{fid}] 不修：ASCII 有序列表中断引用")
    assert [(r.finding_id, r.reason) for r in ascii_list_interrupt] == [(fid, "ASCII 有序列表中断引用")]

    # Finding 9: 屏蔽行内配对 HTML 代码/原样标签内部文本
    for tag in ("code", "pre", "kbd", "samp", "var", "script", "style", "textarea", "template", "noscript"):
        assert parse_one(f"说明 <{tag}>\n[{fid}] 不修：示例\n</{tag}>") == ()
    assert parse_one(f"<code>[{fid}] 不修：单行标签内示例</code>") == ()
    assert parse_one(f"说明 <code class=\"py\">\n[{fid}] 不修：带属性标签\n</code>\n[def67890] 不修：闭合后真实理由") == (
        AuthorReply("def67890", None, None, "闭合后真实理由", "880", "alice"),
    )
    assert parse_one(f"说明 <script>\n<code>\n[{fid}] 不修：script 内嵌 code\n</code>\n</script>") == ()
    assert parse_one(f"`<code>`\n[{fid}] 不修：反引号里的开标签不开启抑制栈")[0].finding_id == fid

    # Finding 10: 行内代码作理由保留真实内容，禁零宽/空反引号/纯注释充当理由
    r_code_only = parse_one(f"[{fid}] 不修：`兼容旧配置`")
    assert len(r_code_only) == 1
    assert r_code_only[0].finding_id == fid
    assert r_code_only[0].reason == "兼容旧配置"
    assert "\u200b" not in r_code_only[0].reason

    r_multi_code = parse_one(f"[{fid}] 不修：依赖 `foo` 与 `bar` 兼容")
    assert len(r_multi_code) == 1
    assert r_multi_code[0].reason == "依赖 foo 与 bar 兼容"

    assert parse_one(f"[{fid}] 不修：`   `") == ()
    assert parse_one(f"[{fid}] 不修：<!-- 注释 -->") == ()
    assert parse_one(f"[{fid}] 不修：\u200b\ufeff") == ()
    assert parse_one(f"说明 `示例\n[{fid}] 不修：x\n结束`") == ()
    assert parse_one(f"说明 <code>\n[{fid}] 不修：x\n</code>") == ()

    with pytest.raises(ConvergenceError):
        AuthorReply(fid, None, None, "\u200b\ufeff", "881", "alice")


def test_r7_finding11_rendered_comment_binds_round_head_and_enforces_non_blocking_conservation() -> None:
    """R6 Finding 11 反例：RenderedComment 强绑定 (round_number, head_sha) 与非阻断发现守恒，绝不让 Nit 凭空消失。"""
    f_nit = _finding(
        severity=Severity.NIT,
        file="pilot1742/nit_only.py",
        line=12,
        category="可读性",
        failure_scenario="局部变量命名不够清晰",
    )

    # decisionA: 第 1 轮 0 发现 -> 渲染出空 rA
    dec_a = evaluate_round(_verified_round([], round_number=1, head_sha=HEAD_1))
    r_a = render_findings_comment(1928, HEAD_1, dec_a)
    assert r_a.round_number == 1
    assert r_a.head_sha == HEAD_1
    assert r_a.posted_fingerprints == frozenset()
    assert r_a.deferred_fingerprints == frozenset()

    # decisionB: 同轮同 HEAD 但含 1 项确认 Nit -> 传空 rA 必须因非阻断覆盖不守恒抛 ConvergenceError
    dec_b_same_round = evaluate_round(
        _verified_round([_verified(f_nit, VerificationVerdict.CONFIRMED)], round_number=1, head_sha=HEAD_1)
    )
    with pytest.raises(ConvergenceError):
        dec_b_same_round.to_history_entry(rendered=r_a)

    # decisionB2: 第 2 轮 HEAD_2 含 Nit -> 传第 1 轮 rA 因 (round_number, head_sha) 不匹配抛 ConvergenceError
    e1_empty = dec_a.to_history_entry(rendered=r_a)
    dec_b_round2 = evaluate_round(
        _verified_round(
            [_verified(f_nit, VerificationVerdict.CONFIRMED)],
            round_number=2,
            head_sha=HEAD_2,
            history=[e1_empty],
        )
    )
    with pytest.raises(ConvergenceError):
        dec_b_round2.to_history_entry(rendered=r_a)

    # 伪造 posted 与 deferred 重叠的 RenderedComment 构造期即拒收
    vf_nit = dec_b_same_round.non_blocking_findings[0]
    with pytest.raises(ConvergenceError):
        RenderedComment(
            round_number=1,
            head_sha=HEAD_1,
            body="fake",
            posted_fingerprints=frozenset({f_nit.finding_id}),
            deferred_fingerprints=frozenset({f_nit.finding_id}),
            omitted_non_blocking_fingerprints=frozenset({f_nit.finding_id}),
            truncated=True,
            omitted_non_blocking=(vf_nit,),
        )

    # 正常渲染 dec_b_same_round 并转历史 -> 成功且 f_nit 完整入账；第 2 轮重报同 Nit（已贴抑制）仍守恒通过
    r_b = render_findings_comment(1928, HEAD_1, dec_b_same_round)
    assert r_b.round_number == 1
    assert r_b.head_sha == HEAD_1
    assert r_b.posted_fingerprints == frozenset({f_nit.finding_id})
    assert r_b.deferred_fingerprints == frozenset()
    e1_nit = dec_b_same_round.to_history_entry(rendered=r_b)
    assert f_nit.finding_id in e1_nit.posted_fingerprints

    dec_r2_suppressed = evaluate_round(
        _verified_round(
            [_verified(f_nit, VerificationVerdict.CONFIRMED)],
            round_number=2,
            head_sha=HEAD_2,
            history=[e1_nit],
        )
    )
    r_r2 = render_findings_comment(1928, HEAD_2, dec_r2_suppressed)
    assert r_r2.posted_fingerprints == frozenset()
    assert r_r2.deferred_fingerprints == frozenset()
    e2_nit = dec_r2_suppressed.to_history_entry(rendered=r_r2)
    assert f_nit.finding_id in e2_nit.posted_fingerprints


# ── 9. R8 精准回归：Codex R7 全部 8 项 Important + 1 项 Nit 最小反例 ────────────


def test_r8_important1_ignores_left_side_and_invalid_side_inline_comments() -> None:
    """R7 Important 1：GitHub side='LEFT' / start_side='LEFT' / 非法 side 严禁绑定到当前 HEAD 新侧发现。"""
    f = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    left_comment = [
        {
            "id": 9,
            "author": "alice",
            "path": "pilot1742/demo.py",
            "side": "LEFT",
            "line": 42,
            "body": "不修：旧行",
        }
    ]
    replies_left = parse_wontfix_replies(left_comment, allowed_authors={"alice"})
    assert len(replies_left) == 1
    assert replies_left[0].line is None
    assert bind_author_replies([f], replies_left) == {}

    cand = _candidates([f], round_number=1, head_sha=HEAD_1)
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand,
                [{"finding_id": f.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图借 LEFT 侧放行"}],
            ),
            cand,
            verifier_model="claude-opus-5-5",
            author_replies=replies_left,
        )

    # 非法 side 与 side=None 且 start_side="LEFT" 均必须将 line 置 None
    for extra in (
        {"side": "left"},
        {"side": "BOTH"},
        {"side": ""},
        {"side": 123},
        {"side": None, "start_side": "LEFT"},
        {"start_side": "LEFT"},
        {"start_side": "INVALID"},
    ):
        bad_replies = parse_wontfix_replies(
            [{"id": 10, "author": "alice", "path": "pilot1742/demo.py", "line": 42, "body": "不修：旧行", **extra}],
            allowed_authors={"alice"},
        )
        assert len(bad_replies) == 1
        assert bad_replies[0].line is None
        assert bind_author_replies([f], bad_replies) == {}

    # 对照：side="RIGHT"、start_side="RIGHT"（当 side 省略/None）或省略 side 均正常绑定第 42 行
    for extra in (
        {"side": "RIGHT"},
        {"side": " right "},
        {"start_side": "RIGHT"},
        {"side": None, "start_side": "RIGHT"},
        {},
    ):
        ok_replies = parse_wontfix_replies(
            [{"id": 11, "author": "alice", "path": "pilot1742/demo.py", "line": 42, "body": "不修：新行正当理由", **extra}],
            allowed_authors={"alice"},
        )
        assert len(ok_replies) == 1
        assert ok_replies[0].line == 42
        bound = bind_author_replies([f], ok_replies)
        assert set(bound.keys()) == {f.finding_id}


def test_r8_important2_cross_paragraph_html_suppress_tags_persist_across_blank_lines() -> None:
    """R7 Important 2：跨段落 HTML 抑制标签（<code>/<blockquote>/<q> 等）遇空行不清空，且不从代码/注释误更新栈。"""
    fid = "a98df8e465064919"

    def parse_one(body: str) -> tuple[AuthorReply, ...]:
        return parse_wontfix_replies(
            [{"id": 890, "user": {"login": "alice", "type": "User"}, "body": body}],
            allowed_authors={"alice"},
        )

    # 核心反例：<code> 与 <blockquote> 跨空行包裹段落 -> 0 条回复
    assert parse_one(f"<code>\n\n[{fid}] 不修：示例\n\n</code>") == ()
    assert parse_one(f"<blockquote>\n\n[{fid}] 不修：示例\n\n</blockquote>") == ()

    # 全抑制标签集跨空行段落均持续屏蔽，闭合后恢复可见
    for tag in ("code", "pre", "kbd", "samp", "var", "script", "style", "textarea", "template", "noscript", "blockquote", "q"):
        assert parse_one(f"<{tag}>\n\n[{fid}] 不修：示例1\n\n[{fid}] 不修：示例2\n\n</{tag}>") == ()
        after = parse_one(f"<{tag}>\n\n[{fid}] 不修：屏蔽示例\n\n</{tag}>\n\n[def67890] 不修：闭合后真理由")
        assert [(r.finding_id, r.reason) for r in after] == [("def67890", "闭合后真理由")]

    # 正向对照：反引号代码跨度、HTML 注释、围栏代码、缩进代码、Markdown 引用内的开标签绝不污染栈
    for body in (
        f"`<code>`\n\n[{fid}] 不修：真理由",
        f"<!-- <code> -->\n\n[{fid}] 不修：真理由",
        f"<!--\n<blockquote>\n-->\n\n[{fid}] 不修：真理由",
        f"```html\n<code>\n```\n\n[{fid}] 不修：真理由",
        f"    <code>\n\n[{fid}] 不修：真理由",
        f"> <blockquote>\n\n[{fid}] 不修：真理由",
    ):
        parsed = parse_one(body)
        assert [(r.finding_id, r.reason) for r in parsed] == [(fid, "真理由")], f"unexpected for {body!r}"


def test_r8_important3_decodes_html_entities_before_non_empty_reason_check() -> None:
    """R7 Important 3：解码非行内代码跨度的 HTML 字符实体后校验非空理由，封杀实体零宽/空白伪理由。"""
    fid = "a98df8e465064919"

    def parse_one(body: str) -> tuple[AuthorReply, ...]:
        return parse_wontfix_replies(
            [{"id": 891, "user": {"login": "alice", "type": "User"}, "body": body}],
            allowed_authors={"alice"},
        )

    assert parse_one(f"[{fid}] 不修：&#8203;") == ()
    assert parse_one(f"[{fid}] 不修：&#x200B;") == ()
    assert parse_one(f"[{fid}] 不修：&ZeroWidthSpace;&nbsp;") == ()
    assert parse_one(f"[{fid}] 不修：&#160;&#xFEFF;") == ()
    assert parse_one(f"[{fid}] 不修：<code>&#8203;</code>") == ()

    # 直接构造仅含不可见/空白字符理由的 AuthorReply 必须抛 ConvergenceError（不做二次 HTML 实体解码）
    for bad_reason in ("\u200b", "\u200b\u00a0", "\u00a0\ufeff", "\x07\x1b", "\u2028\u2029"):
        with pytest.raises(ConvergenceError):
            AuthorReply(fid, None, None, bad_reason, "892", "alice")

    # 正向对照：行内代码跨度字面保留、普通文本实体正常解码
    r_code = parse_one(f"[{fid}] 不修：`兼容旧配置`")
    assert [(r.finding_id, r.reason) for r in r_code] == [(fid, "兼容旧配置")]

    r_code_literal_entity = parse_one(f"[{fid}] 不修：`a &amp; b`")
    assert [(r.finding_id, r.reason) for r in r_code_literal_entity] == [(fid, "a &amp; b")]

    r_amp = parse_one(f"[{fid}] 不修：兼容 &amp; 保留")
    assert [(r.finding_id, r.reason) for r in r_amp] == [(fid, "兼容 & 保留")]


def test_r8_important4_history_entry_requires_complete_finder_session_ids() -> None:
    """R7 Important 4：RoundHistoryEntry.finder_session_ids 必填且数量必须等于 len(panel.finder_models)。"""
    f1 = _finding(severity=Severity.IMPORTANT)

    # 1) 省略 finder_session_ids 立即报 TypeError
    with pytest.raises(TypeError):
        RoundHistoryEntry(1, HEAD_1, frozenset({f1.finding_id}), (f1,), panel=DEFAULT_PANEL)  # type: ignore[call-arg]

    # 2) 空集合、数量不足、数量过多或空白归一后不足 -> 立即抛 ConvergenceError
    for bad_sessions in (
        frozenset(),
        frozenset({"only-one"}),
        frozenset({"s1", "s2", "s3"}),
        frozenset({"s1", " s1 "}),
    ):
        with pytest.raises(ConvergenceError):
            RoundHistoryEntry(
                1,
                HEAD_1,
                frozenset({f1.finding_id}),
                (f1,),
                panel=DEFAULT_PANEL,
                finder_session_ids=bad_sessions,
            )

    # 3) 无法通过伪造空 finder_session_ids 历史把 c1.finder_batches 重放到第 2 轮
    c1 = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f1], round_number=1, head_sha=HEAD_1),
    )
    e1 = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset({f1.finding_id}),
        (f1,),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset(b.session_id for b in c1.finder_batches),
    )
    with pytest.raises(ConvergenceError):
        build_round_candidates(
            round_number=2,
            head_sha=HEAD_1,
            panel=DEFAULT_PANEL,
            finder_batches=c1.finder_batches,
            history=(e1,),
        )


def test_r8_important5_history_chain_enforces_unresolved_important_conservation() -> None:
    """R7 Important 5：历史链强制校验前轮未解除 Important 在下一轮必须有明确去向（结转/解除/驳回），禁止静默消失。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/conserve.py", line=15)
    e1 = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset({f1.finding_id}),
        (f1,),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r1-c1", "r1-c2"}),
    )
    # 伪造第 2 轮：f1 既不在 unresolved_important，也不在 resolved_fingerprints / rejected_fingerprints
    e2_dropped = RoundHistoryEntry(
        2,
        HEAD_2,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r2-c1", "r2-c2"}),
        resolved_fingerprints=frozenset(),
        rejected_fingerprints=frozenset(),
    )
    with pytest.raises(ConvergenceError):
        plan_next_round(BASE_SHA, HEAD_3, (e1, e2_dropped))
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=3,
            head_sha=HEAD_3,
            panel=DEFAULT_PANEL,
            finder_batches=_batches_for_panel([], round_number=3, head_sha=HEAD_3),
            history=(e1, e2_dropped),
        )

    # 正向对照：第 2 轮明确记录 resolved_fingerprints 或 rejected_fingerprints 时，第 3 轮合法通过
    for kw in (
        {"resolved_fingerprints": frozenset({f1.finding_id})},
        {"rejected_fingerprints": frozenset({f1.finding_id})},
    ):
        e2_accounted = RoundHistoryEntry(
            2,
            HEAD_2,
            frozenset(),
            (),
            panel=DEFAULT_PANEL,
            finder_session_ids=frozenset({"r2-ok-1", "r2-ok-2"}),
            **kw,
        )
        plan3 = plan_next_round(BASE_SHA, HEAD_3, (e1, e2_accounted))
        assert plan3.round_number == 3
        c3 = build_round_candidates(
            round_number=3,
            head_sha=HEAD_3,
            panel=DEFAULT_PANEL,
            finder_batches=_batches_for_panel([], round_number=3, head_sha=HEAD_3),
            history=(e1, e2_accounted),
        )
        assert c3.prior_important == ()


def test_r8_important6_same_head_sha_forbids_resolved_by_fix() -> None:
    """R7 Important 6：同 head_sha 无新提交时禁止将历史 Important 标为 resolved_by_fix。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/same_head.py", line=30)
    c1 = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f1], round_number=1, head_sha=HEAD_1),
    )
    v1 = parse_verifier_output(
        _verifier_payload(c1, [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "r1"}]),
        c1,
        verifier_model="claude-opus-5-5",
    )
    dec1 = evaluate_round(v1)
    e1 = dec1.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1))

    # 第 2 轮使用全新 finder 会话，但 head_sha 仍为 HEAD_1（无新提交）
    c2_same_head = build_round_candidates(
        round_number=2,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=2, head_sha=HEAD_1),
        history=(e1,),
    )
    # 1) parse_verifier_output 拒收 resolved_by_fix
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                c2_same_head,
                [{"finding_id": f1.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "同 HEAD 伪称已修"}],
            ),
            c2_same_head,
            verifier_model="claude-opus-5-5",
        )
    # 2) 直接构造 VerifiedRound 同样拒收 resolved_by_fix
    with pytest.raises(ConvergenceError):
        VerifiedRound(
            c2_same_head,
            (
                VerifiedFinding(
                    finding=f1,
                    verdict=VerificationVerdict.RESOLVED_BY_FIX,
                    verifier_model="claude-opus-5-5",
                    verifier_evidence="同 HEAD 绕过",
                    round_number=2,
                    head_sha=HEAD_1,
                ),
            ),
        )

    # 对照 1：同 HEAD 仍允许通过作者不修回复解除（resolved_by_wontfix）
    reply = AuthorReply(f1.finding_id, None, None, "设计如此无需新提交", "700", "alice")
    v2_wontfix = parse_verifier_output(
        _verifier_payload(
            c2_same_head,
            [{"finding_id": f1.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "核实不修理由成立"}],
        ),
        c2_same_head,
        verifier_model="claude-opus-5-5",
        author_replies=(reply,),
    )
    assert v2_wontfix.verdicts[0].verdict is VerificationVerdict.RESOLVED_BY_WONTFIX

    # 对照 2：有新提交 HEAD_2 != HEAD_1 时允许 resolved_by_fix
    c2_new_head = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=2, head_sha=HEAD_2),
        history=(e1,),
    )
    v2_fix = parse_verifier_output(
        _verifier_payload(
            c2_new_head,
            [{"finding_id": f1.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "HEAD_2 已修复"}],
        ),
        c2_new_head,
        verifier_model="claude-opus-5-5",
    )
    assert v2_fix.verdicts[0].verdict is VerificationVerdict.RESOLVED_BY_FIX


def test_r8_important7_quick_pass_only_allows_confirmed_verdict() -> None:
    """R7 Important 7：快审直通模式（require_verifier=False）无独立核实者，禁止使用非 CONFIRMED 裁决。"""
    fast_panel = ReviewPanel(finder_models=("gpt-6-astra",), verifier_model=None, require_verifier=False)
    f_imp = _finding(severity=Severity.IMPORTANT, source_models=("gpt-6-astra",))
    c = _candidates([f_imp], panel=fast_panel, round_number=1, head_sha=HEAD_1)
    v = accept_quick_pass_findings(c)
    assert v.verdicts[0].verdict is VerificationVerdict.CONFIRMED

    # 反例：篡改为 REJECTED 后重构造 VerifiedRound 立即抛 ConvergenceError
    vf_rejected = dataclasses.replace(v.verdicts[0], verdict=VerificationVerdict.REJECTED)
    with pytest.raises(ConvergenceError):
        VerifiedRound(c, (vf_rejected,))

    # 篡改为 RESOLVED_BY_WONTFIX 同样立即抛 ConvergenceError
    reply = AuthorReply(f_imp.finding_id, None, None, "快审不能免核实放行", "801", "alice")
    vf_wontfix = dataclasses.replace(
        v.verdicts[0],
        verdict=VerificationVerdict.RESOLVED_BY_WONTFIX,
        author_reply=reply,
    )
    with pytest.raises(ConvergenceError):
        VerifiedRound(c, (vf_wontfix,))


def test_r8_important8_author_reply_requires_non_empty_author() -> None:
    """R7 Important 8：AuthorReply.author 为必填非空字符串，禁止无作者身份解除 Important。"""
    f = _finding(severity=Severity.IMPORTANT)

    # 缺 author -> TypeError
    with pytest.raises(TypeError):
        AuthorReply(f.finding_id, None, None, "r", "9")  # type: ignore[call-arg]

    # None / 空串 / 空白串 -> ConvergenceError
    for bad_author in (None, "", "   "):
        with pytest.raises(ConvergenceError):
            AuthorReply(f.finding_id, None, None, "r", "9", bad_author)  # type: ignore[arg-type]

    # 合法作者首尾空白规范化写回
    ok = AuthorReply(f.finding_id, None, None, "r", "9", "  alice  ")
    assert ok.author == "alice"


def test_r8_nit1_to_history_entry_validates_and_uses_own_non_blocking_records() -> None:
    """R7 Nit 1：RoundDecision.to_history_entry 校验并采用 self 自己的非阻断核实记录，禁止串用另一决定行号。"""
    f_nit_line1 = _finding(
        severity=Severity.NIT,
        file="pilot1742/nit_swap.py",
        line=1,
        category="命名风格",
        failure_scenario="变量命名可更直观",
        evidence="第 1 行命名偏短",
    )
    f_nit_line2 = _finding(
        severity=Severity.NIT,
        file="pilot1742/nit_swap.py",
        line=2,
        category="命名风格",
        failure_scenario="变量命名可更直观",
        evidence="第 2 行命名偏短",
    )
    assert f_nit_line1.finding_id == f_nit_line2.finding_id

    dec_a = evaluate_round(
        _verified_round([_verified(f_nit_line1, VerificationVerdict.CONFIRMED)], round_number=1, head_sha=HEAD_1)
    )
    dec_b = evaluate_round(
        _verified_round([_verified(f_nit_line2, VerificationVerdict.CONFIRMED)], round_number=1, head_sha=HEAD_1)
    )

    # 极紧预算使非阻断项进入 omitted_non_blocking
    r_a = render_findings_comment(1928, HEAD_1, dec_a, max_chars=136)
    assert [vf.finding.line for vf in r_a.omitted_non_blocking] == [1]

    # 将决定 A 的渲染结果传给决定 B -> 因 omitted_non_blocking 与 B 自身记录不一致立即抛 ConvergenceError
    with pytest.raises(ConvergenceError):
        dec_b.to_history_entry(rendered=r_a)

    # 使用决定 B 自己的渲染结果 -> 成功且 pending_non_blocking 保留 B 的第 2 行
    r_b = render_findings_comment(1928, HEAD_1, dec_b, max_chars=136)
    assert [vf.finding.line for vf in r_b.omitted_non_blocking] == [2]
    e_b = dec_b.to_history_entry(rendered=r_b)
    assert [vf.finding.line for vf in e_b.pending_non_blocking] == [2]


# ── 10. R9 精准回归：Codex R8 全部 6 项 Important 最小反例 ──────────────────────


def test_r9_important1_cross_head_stale_location_blocks_coordinate_binding_and_persists() -> None:
    """R8 Important 1：跨 HEAD 结转且未在新 HEAD 重新定位的旧发现，严禁按行号/坐标绑定当前评论，仅允许显式 [finding_id]。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)

    # 第 1 轮（HEAD_1）确认 demo.py:42 的 Important
    c1 = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f1], round_number=1, head_sha=HEAD_1),
    )
    assert c1.stale_location_fingerprints == frozenset()
    v1 = parse_verifier_output(
        _verifier_payload(c1, [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "r1 确认"}]),
        c1,
        verifier_model="claude-opus-5-5",
    )
    dec1 = evaluate_round(v1)
    e1 = dec1.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1))
    assert e1.relocated_fingerprints == frozenset({f1.finding_id})

    # 第 2 轮切 HEAD_2，双 finder 均返回空 -> f1 保留 line=42 供展示，但记入 stale_location_fingerprints
    c2 = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=2, head_sha=HEAD_2),
        history=(e1,),
    )
    assert c2.findings[0].line == 42
    assert c2.stale_location_fingerprints == frozenset({f1.finding_id})

    # 新 HEAD 上 side="RIGHT", line=42 的无 ID 行内回复 -> 0 匹配，parse_verifier_output 与 VerifiedRound 均抛 ConvergenceError
    inline_r2 = parse_wontfix_replies(
        [
            {
                "id": 910,
                "user": {"login": "alice", "type": "User"},
                "path": "pilot1742/demo.py",
                "side": "RIGHT",
                "line": 42,
                "body": "不修：此行是测试夹具",
            }
        ],
        allowed_authors={"alice"},
    )
    assert len(inline_r2) == 1
    assert bind_author_replies(c2.findings, inline_r2, stale_location_fingerprints=c2.stale_location_fingerprints) == {}

    # 显式 file:line 与仅 file 坐标回复对过期发现同样禁止绑定
    loc_replies = parse_wontfix_replies(
        [
            {"id": 911, "user": {"login": "alice", "type": "User"}, "body": "pilot1742/demo.py:42 不修：旧行号"},
            {"id": 912, "user": {"login": "alice", "type": "User"}, "body": "不修(pilot1742/demo.py)：仅文件"},
        ],
        allowed_authors={"alice"},
    )
    assert bind_author_replies(c2.findings, loc_replies, stale_location_fingerprints=c2.stale_location_fingerprints) == {}

    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                c2,
                [{"finding_id": f1.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图按旧行号放行"}],
            ),
            c2,
            verifier_model="claude-opus-5-5",
            author_replies=inline_r2,
        )
    with pytest.raises(ConvergenceError):
        VerifiedRound(
            c2,
            (
                VerifiedFinding(
                    finding=c2.findings[0],
                    verdict=VerificationVerdict.RESOLVED_BY_WONTFIX,
                    verifier_model="claude-opus-5-5",
                    verifier_evidence="直接构造绕过旧行号",
                    round_number=2,
                    head_sha=HEAD_2,
                    author_reply=inline_r2[0],
                ),
            ),
        )

    # 若第 2 轮仍确认未解除，写入 RoundHistoryEntry 后第 3 轮即使停在 HEAD_2 也绝不丢失过期标记
    v2_still = parse_verifier_output(
        _verifier_payload(c2, [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "r2 仍未修"}]),
        c2,
        verifier_model="claude-opus-5-5",
    )
    dec2_still = evaluate_round(v2_still)
    assert dec2_still.stale_location_fingerprints == frozenset({f1.finding_id})
    assert dec2_still.relocated_fingerprints == frozenset()
    e2_still = dec2_still.to_history_entry(rendered=render_findings_comment(1928, HEAD_2, dec2_still))
    assert e2_still.relocated_fingerprints == frozenset()

    c3_same_head = build_round_candidates(
        round_number=3,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=3, head_sha=HEAD_2),
        history=(e1, e2_still),
    )
    assert c3_same_head.stale_location_fingerprints == frozenset({f1.finding_id})
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                c3_same_head,
                [{"finding_id": f1.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "第 3 轮同 HEAD 试图借旧行号放行"}],
            ),
            c3_same_head,
            verifier_model="claude-opus-5-5",
            author_replies=inline_r2,
        )

    # 显式 [finding_id] 仍能精确解除过期发现
    explicit_id_reply = parse_wontfix_replies(
        [
            {
                "id": 913,
                "user": {"login": "alice", "type": "User"},
                "body": f"[{f1.finding_id}] 不修：显式指纹确认设计如此",
            }
        ],
        allowed_authors={"alice"},
    )
    v2_explicit = parse_verifier_output(
        _verifier_payload(
            c2,
            [{"finding_id": f1.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "显式 ID 核实通过"}],
        ),
        c2,
        verifier_model="claude-opus-5-5",
        author_replies=explicit_id_reply,
    )
    assert v2_explicit.verdicts[0].verdict is VerificationVerdict.RESOLVED_BY_WONTFIX

    # 第 2 轮 finder 在 HEAD_2 的 demo.py:20 重新定位到同指纹 -> 清除过期标记，第 20 行行内回复正常解除
    f1_relocated = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=20)
    assert f1_relocated.finding_id == f1.finding_id
    c2_reloc = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f1_relocated], round_number=2, head_sha=HEAD_2),
        history=(e1,),
    )
    assert c2_reloc.stale_location_fingerprints == frozenset()
    assert c2_reloc.findings[0].line == 20
    inline_line20 = parse_wontfix_replies(
        [
            {
                "id": 914,
                "user": {"login": "alice", "type": "User"},
                "path": "pilot1742/demo.py",
                "side": "RIGHT",
                "line": 20,
                "body": "不修：新行号处已确认夹具逻辑",
            }
        ],
        allowed_authors={"alice"},
    )
    v2_reloc = parse_verifier_output(
        _verifier_payload(
            c2_reloc,
            [{"finding_id": f1.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "重新定位行号后核实通过"}],
        ),
        c2_reloc,
        verifier_model="claude-opus-5-5",
        author_replies=inline_line20,
    )
    assert v2_reloc.verdicts[0].verdict is VerificationVerdict.RESOLVED_BY_WONTFIX

    # RoundHistoryEntry 校验 relocated_fingerprints 必须是 unresolved_important 的子集
    with pytest.raises(ConvergenceError):
        RoundHistoryEntry(
            1,
            HEAD_1,
            frozenset(),
            (),
            panel=DEFAULT_PANEL,
            finder_session_ids=frozenset({"s-stale-1", "s-stale-2"}),
            relocated_fingerprints=frozenset({f1.finding_id}),
        )


def test_r9_important2_cross_blank_line_html_comment_and_raw_text_state() -> None:
    """R8 Important 2：跨空行 HTML 注释与原始文本标签状态持久传递，防止注释内 </blockquote> 提前关闭抑制。"""
    fid = "a98df8e465064919"

    def parse_one(body: str) -> tuple[AuthorReply, ...]:
        return parse_wontfix_replies(
            [{"id": 920, "user": {"login": "alice", "type": "User"}, "body": body}],
            allowed_authors={"alice"},
        )

    # 核心反例：未闭 HTML 注释跨空行包裹 </blockquote>，后续段落仍在 <blockquote> 内 -> 0 条回复
    tricky_blockquote = f"<blockquote>\n<!-- note\n\n</blockquote> -->\n\n[{fid}] 不修：示例\n\n</blockquote>"
    assert parse_one(tricky_blockquote) == ()

    f_target = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="空值解引用",
        failure_scenario="配置缺失时直接访问属性触发 AttributeError",
    )
    tricky_for_target = f"<blockquote>\n<!-- note\n\n</blockquote> -->\n\n[{f_target.finding_id}] 不修：示例\n\n</blockquote>"
    parsed_tricky = parse_one(tricky_for_target)
    assert parsed_tricky == ()
    cand = _candidates([f_target], round_number=1, head_sha=HEAD_1)
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand,
                [{"finding_id": f_target.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图借跨空行注释关闭 blockquote"}],
            ),
            cand,
            verifier_model="claude-opus-5-5",
            author_replies=parsed_tricky,
        )

    # 跨空行纯 HTML 注释 -> 0 条；闭合后新段落恢复可见
    assert parse_one(f"<!--\n\n[{fid}] 不修：示例\n\n-->") == ()
    after_comment = parse_one(f"<!-- note\n\n[{fid}] 不修：示例\n\n-->\n\n[def67890] 不修：注释后真理由")
    assert [(r.finding_id, r.reason) for r in after_comment] == [("def67890", "注释后真理由")]

    # 注释内既有段落又有伪 </blockquote>，闭合注释后再经真实 </blockquote> 才恢复可见
    nested_comment = (
        f"<blockquote>\n<!--\n\n[{fid}] 不修：注释内示例\n\n</blockquote> -->\n\n"
        f"[def67890] 不修：仍在引用内\n\n</blockquote>\n\n[12345678] 不修：闭合后真理由"
    )
    assert [(r.finding_id, r.reason) for r in parse_one(nested_comment)] == [("12345678", "闭合后真理由")]

    # <div> 内开未闭注释，段落中裸 --> 会被 CommonMark 转义为 --&gt;，注释不提前关闭
    assert parse_one(f"<div>\n<!--\n\n[{fid}] 不修：示例\n\n-->\n\n[def67890] 不修：仍在注释内") == ()

    # 短注释 <!--> 与 <!---> 立即闭合，不吞掉外层 <blockquote>
    assert parse_one(f"<blockquote>\n<!-->\n\n[{fid}] 不修：示例\n\n</blockquote>") == ()
    assert parse_one(f"<blockquote>\n<!--->\n\n[{fid}] 不修：示例\n\n</blockquote>") == ()

    # 跨空行原始文本标签 <script>/<style>/<textarea> 状态持久传递，闭合后恢复可见
    for raw_tag in ("script", "style", "textarea"):
        body = f"<div>\n<{raw_tag}>\n\n[{fid}] 不修：屏蔽示例\n\n</{raw_tag}>\n\n[def67890] 不修：闭合后真理由"
        assert [(r.finding_id, r.reason) for r in parse_one(body)] == [("def67890", "闭合后真理由")]


def test_r9_important3_and_important4_single_entity_decode_and_emphasis_stripping() -> None:
    """R8 Important 3 + 4：严格单次实体解码 + 剥离配对排版强调/删除线定界符，封杀 **&#8203;** 且保留 `&nbsp;` / &amp;nbsp;。"""
    fid = "a98df8e465064919"

    def parse_one(body: str) -> tuple[AuthorReply, ...]:
        return parse_wontfix_replies(
            [{"id": 930, "user": {"login": "alice", "type": "User"}, "body": body}],
            allowed_authors={"alice"},
        )

    # Important 3：配对强调/删除线包裹不可见实体或空白/注释 -> 剥离定界符后为空 -> 0 条回复
    for empty_formatted in (
        f"[{fid}] 不修：**&#8203;**",
        f"[{fid}] 不修：*&#8203;*",
        f"[{fid}] 不修：_&#8203;_",
        f"[{fid}] 不修：__&#8203;__",
        f"[{fid}] 不修：___&#8203;___",
        f"[{fid}] 不修：~~&#8203;~~",
        f"[{fid}] 不修：***&ZeroWidthSpace;***",
        f"[{fid}] 不修：**&nbsp;**",
        f"[{fid}] 不修：**&#160;**",
        f"[{fid}] 不修：&#8203;",
        f"[{fid}] 不修：**<!-- 注释 -->**",
        f"[{fid}] 不修：**[&#8203;](https://example.com)**",
        f"[{fid}] 不修：[**&#8203;**](https://example.com)",
        f"[{fid}] 不修：**&#8203;** _&#8203;_ ~~&#8203;~~",
    ):
        assert parse_one(empty_formatted) == (), f"expected 0 replies for {empty_formatted!r}"

    # Important 4：行内代码跨度 `&nbsp;` 与普通文本 &amp;nbsp; 严格单次解码 -> 均保留字面 "&nbsp;"
    r_code_nbsp = parse_one(f"[{fid}] 不修：`&nbsp;`")
    assert [(r.finding_id, r.reason) for r in r_code_nbsp] == [(fid, "&nbsp;")]

    r_amp_nbsp = parse_one(f"[{fid}] 不修：&amp;nbsp;")
    assert [(r.finding_id, r.reason) for r in r_amp_nbsp] == [(fid, "&nbsp;")]

    r_code_zwsp = parse_one(f"[{fid}] 不修：`&#8203;`")
    assert [(r.finding_id, r.reason) for r in r_code_zwsp] == [(fid, "&#8203;")]

    r_amp_zwsp = parse_one(f"[{fid}] 不修：&amp;#8203;")
    assert [(r.finding_id, r.reason) for r in r_amp_zwsp] == [(fid, "&#8203;")]

    # AuthorReply.__post_init__ 不做二次 html.unescape，直接接受已解码的字面 "&nbsp;"
    direct_literal = AuthorReply(fid, None, None, "&nbsp;", "931", "alice")
    assert direct_literal.reason == "&nbsp;"

    # 正常排版强调/删除线剥离后保留真实理由；转义符、代码跨度、词内下划线与空白包围星号保持字面
    assert [(r.finding_id, r.reason) for r in parse_one(f"[{fid}] 不修：**兼容旧配置**")] == [(fid, "兼容旧配置")]
    assert [(r.finding_id, r.reason) for r in parse_one(f"[{fid}] 不修：**a _b_ ~~c~~**")] == [(fid, "a b c")]
    assert [(r.finding_id, r.reason) for r in parse_one(f"[{fid}] 不修：foo_bar_baz")] == [(fid, "foo_bar_baz")]
    assert [(r.finding_id, r.reason) for r in parse_one(f"[{fid}] 不修：a * b * c")] == [(fid, "a * b * c")]
    assert [(r.finding_id, r.reason) for r in parse_one(f"[{fid}] 不修：\\*\\*&#8203;\\*\\*")] == [(fid, "****")]
    assert [(r.finding_id, r.reason) for r in parse_one(f"[{fid}] 不修：`**`")] == [(fid, "**")]
    assert [(r.finding_id, r.reason) for r in parse_one(f"[{fid}] 不修：&#42;foo&#42;")] == [(fid, "*foo*")]


def test_r9_important5_history_chain_enforces_monotonic_source_models() -> None:
    """R8 Important 5：历史链未解除项 source_models 单调不减，禁止丢掉原 finder 绕过异家族核实。"""
    f_r1 = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/monotonic.py",
        line=18,
        source_models=("gpt-6-astra",),
    )
    e1 = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset({f_r1.finding_id}),
        (f_r1,),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r1-m-1", "r1-m-2"}),
    )

    panel_r2 = ReviewPanel(
        finder_models=("gemini-2.5-pro", "gemini-2.5-flash"),
        verifier_model="claude-opus-5-5",
        require_verifier=True,
    )
    # 伪造第 2 轮：保留同指纹却丢掉原来源 gpt-6-astra，仅留 gemini-2.5-pro
    f_r2_shrunk = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/monotonic.py",
        line=18,
        source_models=("gemini-2.5-pro",),
    )
    assert f_r2_shrunk.finding_id == f_r1.finding_id
    e2_shrunk = RoundHistoryEntry(
        2,
        HEAD_2,
        frozenset({f_r1.finding_id}),
        (f_r2_shrunk,),
        panel=panel_r2,
        finder_session_ids=frozenset({"r2-m-1", "r2-m-2"}),
    )

    panel_r3_gpt_verifier = ReviewPanel(
        finder_models=("gemini-2.5-pro", "gemini-2.5-flash"),
        verifier_model="gpt-6-astra",
        require_verifier=True,
    )
    with pytest.raises(ConvergenceError):
        plan_next_round(BASE_SHA, HEAD_3, (e1, e2_shrunk))
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=3,
            head_sha=HEAD_3,
            panel=panel_r3_gpt_verifier,
            finder_batches=_batches_for_panel([], panel=panel_r3_gpt_verifier, round_number=3, head_sha=HEAD_3),
            history=(e1, e2_shrunk),
        )

    # 正向对照：第 2 轮完整保留原来源 + 新来源时，plan_next_round 通过，且第 3 轮仍禁止用 gpt-6-astra 核实
    f_r2_cumulative = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/monotonic.py",
        line=18,
        source_models=("gemini-2.5-pro", "gpt-6-astra"),
    )
    e2_valid = RoundHistoryEntry(
        2,
        HEAD_2,
        frozenset({f_r1.finding_id}),
        (f_r2_cumulative,),
        panel=panel_r2,
        finder_session_ids=frozenset({"r2-m-ok-1", "r2-m-ok-2"}),
    )
    plan3 = plan_next_round(BASE_SHA, HEAD_3, (e1, e2_valid))
    assert plan3.round_number == 3
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=3,
            head_sha=HEAD_3,
            panel=panel_r3_gpt_verifier,
            finder_batches=_batches_for_panel([], panel=panel_r3_gpt_verifier, round_number=3, head_sha=HEAD_3),
            history=(e1, e2_valid),
        )
    c3_ok = RoundCandidates(
        round_number=3,
        head_sha=HEAD_3,
        panel=panel_r2,
        finder_batches=_batches_for_panel([], panel=panel_r2, round_number=3, head_sha=HEAD_3),
        history=(e1, e2_valid),
    )
    assert c3_ok.findings[0].source_models == ("gemini-2.5-pro", "gpt-6-astra")


def test_r9_important6_normalizes_commit_sha_case_to_block_same_head_fix_bypass() -> None:
    """R8 Important 6：全链路规范化十六进制提交 SHA 为小写，禁止大小写变体绕过同提交 resolved_by_fix 校验。"""
    sha_lower = "d44378842677ac7656376c493766fa14e638bf98"
    sha_upper = sha_lower.upper()
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/sha_case.py", line=10)

    # 第 1 轮使用小写 SHA
    c1 = build_round_candidates(
        round_number=1,
        head_sha=sha_lower,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f1], round_number=1, head_sha=sha_lower),
    )
    v1 = parse_verifier_output(
        _verifier_payload(c1, [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "r1 确认"}]),
        c1,
        verifier_model="claude-opus-5-5",
    )
    dec1 = evaluate_round(v1)
    r1 = render_findings_comment(1928, sha_upper, dec1)
    assert r1.head_sha == sha_lower
    assert parse_comment_marker(r1.body) == (1928, 1, sha_lower)
    e1 = dec1.to_history_entry(sha_upper, rendered=r1)
    assert e1.head_sha == sha_lower

    # 第 2 轮使用大写 SHA 变体 -> 全部规范化为小写且识别为同一 HEAD
    plan2 = plan_next_round(BASE_SHA.upper(), sha_upper, (e1,))
    assert plan2.diff_base_sha == sha_lower
    assert plan2.diff_head_sha == sha_lower

    c2 = build_round_candidates(
        round_number=2,
        head_sha=sha_upper,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=2, head_sha=sha_upper),
        history=(e1,),
    )
    assert c2.head_sha == sha_lower
    assert all(b.head_sha == sha_lower for b in c2.finder_batches)

    # 1) parse_verifier_output 传入大写或小写 head_sha 提交 resolved_by_fix -> 均立即抛 ConvergenceError
    for payload_head in (sha_upper, sha_lower):
        with pytest.raises(ConvergenceError):
            parse_verifier_output(
                {
                    "round_number": 2,
                    "head_sha": payload_head,
                    "verdicts": [
                        {
                            "finding_id": f1.finding_id,
                            "verdict": "resolved_by_fix",
                            "verifier_evidence": "试图借大写 SHA 绕过同提交校验",
                        }
                    ],
                },
                c2,
                verifier_model="claude-opus-5-5",
            )

    # 2) 直接构造 VerifiedRound 传入大写 SHA -> VerifiedFinding 归一化后同样立即抛 ConvergenceError
    vf_upper = VerifiedFinding(
        finding=f1,
        verdict=VerificationVerdict.RESOLVED_BY_FIX,
        verifier_model="claude-opus-5-5",
        verifier_evidence="直接构造大写 SHA 绕过",
        round_number=2,
        head_sha=sha_upper,
    )
    assert vf_upper.head_sha == sha_lower
    with pytest.raises(ConvergenceError):
        VerifiedRound(c2, (vf_upper,))

    # 3) 大小写混合的 marker 同样归一化为小写
    assert parse_comment_marker(f"{COMMENT_MARKER_PREFIX} pr=1928 round=1 head={sha_upper} -->") == (
        1928,
        1,
        sha_lower,
    )


# ── 11. R10 精准回归：Codex R9 全部 7 项 Important 最小反例 ──────────────────────


def test_r10_important1_rejects_abbreviated_and_invalid_commit_shas() -> None:
    """R9 Important 1：全链路仅接受完整 40 位（SHA-1）或 64 位（SHA-256）十六进制 SHA，入口立即拒绝短 SHA。"""
    full_sha1 = "c93c17d9887e17b0955ca49f7e213116ef9fa324"
    short_sha = "c93c17d"
    full_sha256_upper = "ABCDEF0123456789" * 4
    full_sha256_lower = full_sha256_upper.lower()
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/sha_len.py", line=15)

    # 第 1 轮使用完整 40 位 SHA
    c1 = build_round_candidates(
        round_number=1,
        head_sha=full_sha1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f1], round_number=1, head_sha=full_sha1),
    )
    v1 = parse_verifier_output(
        _verifier_payload(c1, [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "r1 确认"}]),
        c1,
        verifier_model="claude-opus-5-5",
    )
    dec1 = evaluate_round(v1)
    e1 = dec1.to_history_entry(rendered=render_findings_comment(1928, full_sha1, dec1))

    # 核心反例：第 2 轮传入 7 位短 SHA `c93c17d`，所有入口立即抛 ConvergenceError，绝不被误判为新提交已修复
    for bad_sha in (
        short_sha,
        "a" * 39,
        "a" * 41,
        "a" * 63,
        "a" * 65,
        "g" * 40,
        "HEAD",
        "",
        "   ",
    ):
        with pytest.raises(ConvergenceError):
            plan_next_round(BASE_SHA, bad_sha, (e1,))
        with pytest.raises(ConvergenceError):
            FinderBatch(model="gpt-6-astra", session_id="s-short", head_sha=bad_sha, findings=())
        with pytest.raises(ConvergenceError):
            RoundCandidates(
                round_number=2,
                head_sha=bad_sha,
                panel=DEFAULT_PANEL,
                finder_batches=(),
                history=(e1,),
            )
        with pytest.raises(ConvergenceError):
            VerifiedFinding(
                finding=f1,
                verdict=VerificationVerdict.RESOLVED_BY_FIX,
                verifier_model="claude-opus-5-5",
                verifier_evidence="短 SHA 绕过尝试",
                round_number=2,
                head_sha=bad_sha,
            )
        with pytest.raises(ConvergenceError):
            RoundHistoryEntry(
                1,
                bad_sha,
                frozenset(),
                (),
                panel=DEFAULT_PANEL,
                finder_session_ids=frozenset({"s1", "s2"}),
            )
        with pytest.raises(ConvergenceError):
            render_findings_comment(1928, bad_sha, dec1)

    # verifier 输出中携带短 SHA 同样立即拒绝
    c2_same = build_round_candidates(
        round_number=2,
        head_sha=full_sha1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=2, head_sha=full_sha1),
        history=(e1,),
    )
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {
                "round_number": 2,
                "head_sha": short_sha,
                "verdicts": [{"finding_id": f1.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "短 SHA"}],
            },
            c2_same,
            verifier_model="claude-opus-5-5",
        )

    # 正向对照：完整 64 位 SHA-256（大写）正常接受并规范化为小写
    plan_sha256 = plan_next_round(BASE_SHA, full_sha256_upper, (e1,))
    assert plan_sha256.diff_head_sha == full_sha256_lower
    c2_sha256 = build_round_candidates(
        round_number=2,
        head_sha=full_sha256_upper,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=2, head_sha=full_sha256_upper),
        history=(e1,),
    )
    assert c2_sha256.head_sha == full_sha256_lower
    assert parse_comment_marker(f"{COMMENT_MARKER_PREFIX} pr=1928 round=2 head={full_sha256_upper} -->") == (
        1928,
        2,
        full_sha256_lower,
    )
    assert parse_comment_marker(f"{COMMENT_MARKER_PREFIX} pr=1928 round=2 head={short_sha} -->") is None


def test_r10_important2_stale_location_fail_closed_via_relocated_fingerprints() -> None:
    """R9 Important 2：RoundHistoryEntry 改为 fail-closed 的 relocated_fingerprints，缺省空集永不放行过期坐标。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)

    # RoundHistoryEntry 已移除 fail-open 的 stale_location_fingerprints 参数
    with pytest.raises(TypeError):
        RoundHistoryEntry(
            1,
            HEAD_1,
            frozenset({f1.finding_id}),
            (f1,),
            panel=DEFAULT_PANEL,
            finder_session_ids=frozenset({"r1-fc-1", "r1-fc-2"}),
            stale_location_fingerprints=frozenset(),  # type: ignore[call-arg]
        )

    # 第 1 轮在 HEAD_1 确认 demo.py:42
    c1 = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f1], round_number=1, head_sha=HEAD_1),
    )
    v1 = parse_verifier_output(
        _verifier_payload(c1, [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "r1 确认"}]),
        c1,
        verifier_model="claude-opus-5-5",
    )
    dec1 = evaluate_round(v1)
    assert dec1.relocated_fingerprints == frozenset({f1.finding_id})
    e1 = dec1.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1))
    assert e1.relocated_fingerprints == frozenset({f1.finding_id})

    # 第 2 轮切到 HEAD_2、finder 为空 -> e2.relocated_fingerprints 为空集
    c2 = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=2, head_sha=HEAD_2),
        history=(e1,),
    )
    v2 = parse_verifier_output(
        _verifier_payload(c2, [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "r2 仍在"}]),
        c2,
        verifier_model="claude-opus-5-5",
    )
    dec2 = evaluate_round(v2)
    e2 = dec2.to_history_entry(rendered=render_findings_comment(1928, HEAD_2, dec2))
    assert e2.relocated_fingerprints == frozenset()

    # 核心反例：把 e2 缺省/重置为 relocated_fingerprints=frozenset()，第 3 轮留在 HEAD_2 且 finder 仍空
    e2_rehydrated = RoundHistoryEntry(
        round_number=e2.round_number,
        head_sha=e2.head_sha,
        posted_fingerprints=e2.posted_fingerprints,
        unresolved_important=e2.unresolved_important,
        panel=e2.panel,
        finder_session_ids=e2.finder_session_ids,
        resolved_fingerprints=e2.resolved_fingerprints,
        consumed_reply_keys=e2.consumed_reply_keys,
        rejected_fingerprints=e2.rejected_fingerprints,
        pending_non_blocking=e2.pending_non_blocking,
        outcome=e2.outcome,
    )
    assert e2_rehydrated.relocated_fingerprints == frozenset()

    c3 = build_round_candidates(
        round_number=3,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=3, head_sha=HEAD_2),
        history=(e1, e2_rehydrated),
    )
    assert c3.stale_location_fingerprints == frozenset({f1.finding_id})

    inline_42 = parse_wontfix_replies(
        [
            {
                "id": 1001,
                "user": {"login": "alice", "type": "User"},
                "path": "pilot1742/demo.py",
                "side": "RIGHT",
                "line": 42,
                "body": "不修：旧行号测试夹具",
            }
        ],
        allowed_authors={"alice"},
    )
    assert bind_author_replies(c3.findings, inline_42, stale_location_fingerprints=c3.stale_location_fingerprints) == {}
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                c3,
                [{"finding_id": f1.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图借缺省历史放行旧行号"}],
            ),
            c3,
            verifier_model="claude-opus-5-5",
            author_replies=inline_42,
        )

    # 伪造 relocated_fingerprints：第 2 轮换用 gemini 面板却未将 gemini 写入 source_models，立即拒收
    gemini_panel = ReviewPanel(
        finder_models=("gemini-2.5-pro", "gemini-2.5-flash"),
        verifier_model="claude-opus-5-5",
        require_verifier=True,
    )
    e2_forged_reloc = RoundHistoryEntry(
        2,
        HEAD_2,
        frozenset({f1.finding_id}),
        (f1,),
        panel=gemini_panel,
        finder_session_ids=frozenset({"r2-fg-1", "r2-fg-2"}),
        relocated_fingerprints=frozenset({f1.finding_id}),
    )
    with pytest.raises(ConvergenceError):
        plan_next_round(BASE_SHA, HEAD_2, (e1, e2_forged_reloc))

    # 正向对照：第 2 轮 finder 在 HEAD_2 重新定位到第 20 行 -> 第 3 轮留在 HEAD_2 时坐标有效，切 HEAD_3 再次过期
    f1_line20 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=20)
    c2_reloc = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f1_line20], round_number=2, head_sha=HEAD_2),
        history=(e1,),
    )
    v2_reloc = parse_verifier_output(
        _verifier_payload(c2_reloc, [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "r2 仍在第 20 行"}]),
        c2_reloc,
        verifier_model="claude-opus-5-5",
    )
    dec2_reloc = evaluate_round(v2_reloc)
    e2_reloc = dec2_reloc.to_history_entry(rendered=render_findings_comment(1928, HEAD_2, dec2_reloc))
    assert e2_reloc.relocated_fingerprints == frozenset({f1.finding_id})

    c3_still_h2 = build_round_candidates(
        round_number=3,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=3, head_sha=HEAD_2),
        history=(e1, e2_reloc),
    )
    assert c3_still_h2.stale_location_fingerprints == frozenset()
    inline_20 = parse_wontfix_replies(
        [
            {
                "id": 1002,
                "user": {"login": "alice", "type": "User"},
                "path": "pilot1742/demo.py",
                "side": "RIGHT",
                "line": 20,
                "body": "不修：已核对 HEAD_2 第 20 行",
            }
        ],
        allowed_authors={"alice"},
    )
    v3_ok = parse_verifier_output(
        _verifier_payload(
            c3_still_h2,
            [{"finding_id": f1.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "同 HEAD 有效坐标核实通过"}],
        ),
        c3_still_h2,
        verifier_model="claude-opus-5-5",
        author_replies=inline_20,
    )
    assert v3_ok.verdicts[0].verdict is VerificationVerdict.RESOLVED_BY_WONTFIX

    c3_moved_h3 = build_round_candidates(
        round_number=3,
        head_sha=HEAD_3,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=3, head_sha=HEAD_3),
        history=(e1, e2_reloc),
    )
    assert c3_moved_h3.stale_location_fingerprints == frozenset({f1.finding_id})


def test_r10_important3_history_chain_blocks_same_family_and_quick_pass_clearances() -> None:
    """R9 Important 3：历史链对每轮结转进入的发现（含被解除/驳回项）强制校验跨家族核实与禁止快审直通结清。"""
    f1 = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/self_reject.py",
        line=25,
        source_models=("gpt-6-astra",),
    )
    e1 = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset({f1.finding_id}),
        (f1,),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r1-sr-1", "r1-sr-2"}),
    )

    # 核心反例：第 2 轮用与原 finder 同家族的 gpt-6-astra 作核实者，试图把 f1 标为 rejected 或 resolved
    tampered_r2_panel = ReviewPanel(
        finder_models=("gemini-2.5-pro", "gemini-2.5-flash"),
        verifier_model="gpt-6-astra",
        require_verifier=True,
    )
    for clearance_kw in (
        {"rejected_fingerprints": frozenset({f1.finding_id})},
        {"resolved_fingerprints": frozenset({f1.finding_id})},
    ):
        e2_tampered = RoundHistoryEntry(
            2,
            HEAD_2,
            frozenset(),
            (),
            panel=tampered_r2_panel,
            finder_session_ids=frozenset({"r2-sr-1", "r2-sr-2"}),
            **clearance_kw,
        )
        with pytest.raises(ConvergenceError):
            plan_next_round(BASE_SHA, HEAD_3, (e1, e2_tampered))
        with pytest.raises(ConvergenceError):
            RoundCandidates(
                round_number=3,
                head_sha=HEAD_3,
                panel=DEFAULT_PANEL,
                finder_batches=_batches_for_panel([], round_number=3, head_sha=HEAD_3),
                history=(e1, e2_tampered),
            )

    # 快审直通面板（require_verifier=False）无独立核实者，禁止出现任何 resolved_fingerprints 或 rejected_fingerprints
    quick_panel = ReviewPanel(
        finder_models=("gemini-2.5-pro",),
        verifier_model=None,
        require_verifier=False,
    )
    for clearance_kw in (
        {"rejected_fingerprints": frozenset({f1.finding_id})},
        {"resolved_fingerprints": frozenset({f1.finding_id})},
    ):
        with pytest.raises(ConvergenceError):
            RoundHistoryEntry(
                2,
                HEAD_2,
                frozenset(),
                (),
                panel=quick_panel,
                finder_session_ids=frozenset({"r2-qp-1"}),
                **clearance_kw,
            )

    # 正向对照：第 2 轮由异家族核实者（claude-opus-5-5）合法结清后，第 3 轮无结转项，可自由选用 gpt-6-astra 作核实者
    e2_legit = RoundHistoryEntry(
        2,
        HEAD_2,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r2-ok-1", "r2-ok-2"}),
        rejected_fingerprints=frozenset({f1.finding_id}),
    )
    plan3 = plan_next_round(BASE_SHA, HEAD_3, (e1, e2_legit))
    assert plan3.round_number == 3
    assert plan3.unresolved_prior_important == ()
    c3_gpt_verifier = build_round_candidates(
        round_number=3,
        head_sha=HEAD_3,
        panel=tampered_r2_panel,
        finder_batches=_batches_for_panel([], panel=tampered_r2_panel, round_number=3, head_sha=HEAD_3),
        history=(e1, e2_legit),
    )
    assert c3_gpt_verifier.prior_important == ()


def test_r10_important4_and_5_cross_block_quoted_attrs_and_html5_non_void_tags() -> None:
    """R9 Important 4 + 5：跨空行未闭带引号 HTML 属性状态持久传递，且 12 个非空抑制标签写 `/>` 仍按 HTML5 入栈。"""
    fid = "a98df8e465064919"

    def parse_one(body: str) -> tuple[AuthorReply, ...]:
        return parse_wontfix_replies(
            [{"id": 1010, "user": {"login": "alice", "type": "User"}, "body": body}],
            allowed_authors={"alice"},
        )

    # Important 4 核心反例：双引号与单引号跨空行属性包裹 </blockquote>，不提前闭合外层 <blockquote>
    assert (
        parse_one(f'<blockquote>\n<div title="\n\n</blockquote>">\n\n[{fid}] 不修：引用示例\n\n</div></blockquote>')
        == ()
    )
    assert (
        parse_one(f"<blockquote>\n<div title='\n\n</blockquote>'>\n\n[{fid}] 不修：引用示例\n\n</div></blockquote>")
        == ()
    )
    assert (
        parse_one(
            f'<blockquote>\n<div title="\n\ntext </blockquote>">\n\n[{fid}] 不修：引用示例\n\n</div></blockquote>'
        )
        == ()
    )
    assert parse_one(f'<blockquote title="\n\n">\n\n[{fid}] 不修：引用内示例\n\n</blockquote>') == ()

    # 正向对照：非抑制标签跨空行引号属性闭合后，后续段落恢复可见
    after_div_attr = parse_one(f'<div title="\n\nhello">\n\n[{fid}] 不修：闭合后真理由')
    assert [(r.finding_id, r.reason) for r in after_div_attr] == [(fid, "闭合后真理由")]

    # Important 5 核心反例：<blockquote/> 与 <code/> 在 HTML5 中绝不自闭合，全部 12 个抑制标签同理
    assert parse_one(f"<blockquote/>\n\n[{fid}] 不修：引用示例\n\n</blockquote>") == ()
    assert parse_one(f"<code/>\n\n[{fid}] 不修：代码示例\n\n</code>") == ()
    assert parse_one(f"说明 <code/> [{fid}] 不修：行内代码示例 </code>") == ()
    for tag in (
        "code",
        "pre",
        "kbd",
        "samp",
        "var",
        "script",
        "style",
        "textarea",
        "template",
        "noscript",
        "blockquote",
        "q",
    ):
        assert parse_one(f"<{tag}/>\n\n[{fid}] 不修：示例\n\n</{tag}>") == ()
        assert parse_one(f"<{tag} />\n\n[{fid}] 不修：示例\n\n</{tag}>") == ()
        recovered = parse_one(f"<{tag}/>\n\n[{fid}] 不修：示例\n\n</{tag}>\n\n[def67890] 不修：闭合后真理由")
        assert [(r.finding_id, r.reason) for r in recovered] == [("def67890", "闭合后真理由")]


def test_r10_important6_paragraph_wide_emphasis_delimiters_across_soft_breaks() -> None:
    """R9 Important 6：在整段范围内配对强调/删除线定界符，封杀跨软换行 `**&#8203;\\n&#8203;**` 伪理由并保留合法多行强调。"""
    fid = "a98df8e465064919"

    def parse_one(body: str) -> tuple[AuthorReply, ...]:
        return parse_wontfix_replies(
            [{"id": 1020, "user": {"login": "alice", "type": "User"}, "body": body}],
            allowed_authors={"alice"},
        )

    # 核心反例：跨软换行/硬换行的空强调/删除线定界符配对剥离后理由为空 -> 0 条回复
    for empty_multiline in (
        f"[{fid}] 不修：**&#8203;\n&#8203;**",
        f"[{fid}] 不修：*&#8203;\n&#8203;*",
        f"[{fid}] 不修：_&#8203;\n&#8203;_",
        f"[{fid}] 不修：__&#8203;\n&#8203;__",
        f"[{fid}] 不修：~~&#8203;\n&#8203;~~",
        f"[{fid}] 不修：**&nbsp;\n&nbsp;**",
        f"[{fid}] 不修：**&#8203;\\\n&#8203;**",
        f"[{fid}] 不修：**[&#8203;\n&#8203;](https://example.com)**",
    ):
        assert parse_one(empty_multiline) == (), f"expected 0 replies for {empty_multiline!r}"

    # 正向对照：跨软换行强调包裹真实理由 -> 剥离定界符后提取第 1 行可见理由
    multiline_ok = parse_one(f"[{fid}] 不修：**兼容旧配置\n补充说明**")
    assert [(r.finding_id, r.reason) for r in multiline_ok] == [(fid, "兼容旧配置")]

    # 跨空行属于不同段落，不跨段落误配对
    cross_para = parse_one(f"[{fid}] 不修：**单边星号\n\n第二段**")
    assert [(r.finding_id, r.reason) for r in cross_para] == [(fid, "**单边星号")]

    # 回归确认 R8 规则完好
    assert [(r.finding_id, r.reason) for r in parse_one(f"[{fid}] 不修：`&nbsp;`")] == [(fid, "&nbsp;")]
    assert [(r.finding_id, r.reason) for r in parse_one(f"[{fid}] 不修：&amp;nbsp;")] == [(fid, "&nbsp;")]
    assert parse_one(f"[{fid}] 不修：**&#8203;**") == ()
    assert [(r.finding_id, r.reason) for r in parse_one(f"[{fid}] 不修：**兼容旧配置**")] == [(fid, "兼容旧配置")]


def test_r10_important7_machine_comment_filter_uses_parse_comment_marker_only() -> None:
    """R9 Important 7：仅凭首行 parse_comment_marker 跳过机器评论，不误杀正文/代码块中提及标记前缀的人类回复。"""
    fid = "a98df8e465064919"

    # 核心反例：人类评论在代码块中演示机器评论标记前缀，随后给出真实不修回复
    body_with_fenced_marker = (
        f"示例：\n\n```\n{COMMENT_MARKER_PREFIX}\n```\n\n[{fid}] 不修：保留兼容性"
    )
    replies = parse_wontfix_replies(
        [{"id": 1030, "user": {"login": "alice", "type": "User"}, "body": body_with_fenced_marker}],
        allowed_authors={"alice"},
    )
    assert [(r.finding_id, r.reason) for r in replies] == [(fid, "保留兼容性")]

    # 引用块中提及完整机器标记行同样不误杀后续人类回复
    body_with_quoted_marker = (
        f"> {COMMENT_MARKER_PREFIX} pr=1928 round=1 head={HEAD_1} -->\n\n[{fid}] 不修：引用机器人标记后回复"
    )
    quoted_replies = parse_wontfix_replies(
        [{"id": 1031, "user": {"login": "alice", "type": "User"}, "body": body_with_quoted_marker}],
        allowed_authors={"alice"},
    )
    assert [(r.finding_id, r.reason) for r in quoted_replies] == [(fid, "引用机器人标记后回复")]

    # 首行含非法短 SHA 标记不算机器评论且不抛异常，后续真实回复正常提取
    body_malformed_marker = (
        f"{COMMENT_MARKER_PREFIX} pr=1928 round=1 head=c93c17d -->\n\n[{fid}] 不修：非合法机器标记"
    )
    malformed_replies = parse_wontfix_replies(
        [{"id": 1032, "user": {"login": "alice", "type": "User"}, "body": body_malformed_marker}],
        allowed_authors={"alice"},
    )
    assert [(r.finding_id, r.reason) for r in malformed_replies] == [(fid, "非合法机器标记")]

    # 正向对照：真实由 render_findings_comment 生成的机器评论仍被可靠跳过
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    dec1 = evaluate_round(_verified_round([_verified(f1, VerificationVerdict.CONFIRMED)], round_number=1, head_sha=HEAD_1))
    rendered = render_findings_comment(1928, HEAD_1, dec1)
    assert parse_comment_marker(rendered.body) == (1928, 1, HEAD_1)
    assert (
        parse_wontfix_replies(
            [{"id": 1033, "user": {"login": "alice", "type": "User"}, "body": rendered.body}],
            allowed_authors={"alice"},
        )
        == ()
    )


def test_r11_important1_history_chain_requires_valid_resolution_basis() -> None:
    """R10 Important 1：历史链校验每条 resolved_fingerprints 的合法解除依据（同 HEAD 或非结转项必须有未复用消费键）。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    f2 = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/other.py",
        line=15,
        category="边界",
        failure_scenario="空切片越界",
    )
    e1 = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset({f1.finding_id}),
        (f1,),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r11-i1-r1-1", "r11-i1-r1-2"}),
    )

    # 核心反例：第 2 轮仍在同一 HEAD_1，无消费键却将 f1 标为 resolved_fingerprints -> 必须拒收
    e2_same_head_unproven = RoundHistoryEntry(
        2,
        HEAD_1,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r11-i1-r2-1", "r11-i1-r2-2"}),
        resolved_fingerprints=frozenset({f1.finding_id}),
        consumed_reply_keys=frozenset(),
    )
    with pytest.raises(ConvergenceError):
        plan_next_round(BASE_SHA, HEAD_1, (e1, e2_same_head_unproven))
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=3,
            head_sha=HEAD_1,
            panel=DEFAULT_PANEL,
            finder_batches=_batches_for_panel([], round_number=3, head_sha=HEAD_1),
            history=(e1, e2_same_head_unproven),
        )

    # 伪造空 comment_id 消费键在构造 RoundHistoryEntry 时即立即拒收
    with pytest.raises(ConvergenceError):
        RoundHistoryEntry(
            2,
            HEAD_1,
            frozenset(),
            (),
            panel=DEFAULT_PANEL,
            finder_session_ids=frozenset({"r11-i1-r2e-1", "r11-i1-r2e-2"}),
            resolved_fingerprints=frozenset({f1.finding_id}),
            consumed_reply_keys=frozenset({f"comment::resolved:{f1.finding_id}"}),
        )

    # 第 1 轮直接标 resolved_fingerprints 但无消费键 -> 拒收
    e1_unproven = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r11-i1-u1-1", "r11-i1-u1-2"}),
        resolved_fingerprints=frozenset({f1.finding_id}),
        consumed_reply_keys=frozenset(),
    )
    with pytest.raises(ConvergenceError):
        plan_next_round(BASE_SHA, HEAD_2, (e1_unproven,))

    # 第 2 轮即使推进到 HEAD_2，非前轮结转项 f2 标 resolved_fingerprints 且无消费键 -> 拒收
    e2_non_prior_unproven = RoundHistoryEntry(
        2,
        HEAD_2,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r11-i1-np-1", "r11-i1-np-2"}),
        resolved_fingerprints=frozenset({f1.finding_id, f2.finding_id}),
        consumed_reply_keys=frozenset(),
    )
    with pytest.raises(ConvergenceError):
        plan_next_round(BASE_SHA, HEAD_3, (e1, e2_non_prior_unproven))

    # 正向对照 1：同 HEAD_1 但携带合法 comment:10:resolved:<fp> 消费键 -> 合法通过
    e2_same_head_wontfix = RoundHistoryEntry(
        2,
        HEAD_1,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r11-i1-ok-1", "r11-i1-ok-2"}),
        resolved_fingerprints=frozenset({f1.finding_id}),
        consumed_reply_keys=frozenset({f"comment:10:resolved:{f1.finding_id}"}),
    )
    plan3_wontfix = plan_next_round(BASE_SHA, HEAD_1, (e1, e2_same_head_wontfix))
    assert plan3_wontfix.round_number == 3
    c3_wontfix = build_round_candidates(
        round_number=3,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=3, head_sha=HEAD_1),
        history=(e1, e2_same_head_wontfix),
    )
    assert c3_wontfix.prior_important == ()

    # 正向对照 2：新提交 HEAD_2 解除前轮结转项 f1（RESOLVED_BY_FIX）无需消费键 -> 合法通过
    e2_new_head_fix = RoundHistoryEntry(
        2,
        HEAD_2,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r11-i1-fix-1", "r11-i1-fix-2"}),
        resolved_fingerprints=frozenset({f1.finding_id}),
        consumed_reply_keys=frozenset(),
    )
    plan3_fix = plan_next_round(BASE_SHA, HEAD_3, (e1, e2_new_head_fix))
    assert plan3_fix.round_number == 3


def test_r11_important2_paired_anchor_recovery_marks_stale_on_unproven_relocation() -> None:
    """R10 Important 2：成对追踪 (head_sha, file, line) 定位锚点，坐标变化且缺重定位证明时强制判为过期。"""
    f1_line42 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    f1_line20 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=20)
    assert f1_line42.finding_id == f1_line20.finding_id
    fid = f1_line42.finding_id

    # 第 1 轮在 HEAD_1 的 demo.py:42 确认 f1
    c1 = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f1_line42], round_number=1, head_sha=HEAD_1),
    )
    v1 = parse_verifier_output(
        _verifier_payload(c1, [{"finding_id": fid, "verdict": "confirmed", "verifier_evidence": "r1 确认于第 42 行"}]),
        c1,
        verifier_model="claude-opus-5-5",
    )
    dec1 = evaluate_round(v1)
    e1 = dec1.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1))

    # 第 2 轮在 HEAD_2 重新定位到第 20 行并确认，恢复历史时省略 relocated_fingerprints
    c2 = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f1_line20], round_number=2, head_sha=HEAD_2),
        history=(e1,),
    )
    v2 = parse_verifier_output(
        _verifier_payload(c2, [{"finding_id": fid, "verdict": "confirmed", "verifier_evidence": "r2 移至第 20 行"}]),
        c2,
        verifier_model="claude-opus-5-5",
    )
    dec2 = evaluate_round(v2)
    e2 = dec2.to_history_entry(rendered=render_findings_comment(1928, HEAD_2, dec2))
    e2_without_reloc = RoundHistoryEntry(
        round_number=e2.round_number,
        head_sha=e2.head_sha,
        posted_fingerprints=e2.posted_fingerprints,
        unresolved_important=e2.unresolved_important,
        panel=e2.panel,
        finder_session_ids=e2.finder_session_ids,
        resolved_fingerprints=e2.resolved_fingerprints,
        consumed_reply_keys=e2.consumed_reply_keys,
        rejected_fingerprints=e2.rejected_fingerprints,
        pending_non_blocking=e2.pending_non_blocking,
        outcome=e2.outcome,
    )

    # 第 3 轮回到 HEAD_1 且 finder 无新发现 -> 因第 2 轮坐标从 42 变为 20 且缺重定位证明，强制标为 stale
    c3 = build_round_candidates(
        round_number=3,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=3, head_sha=HEAD_1),
        history=(e1, e2_without_reloc),
    )
    assert fid in c3.stale_location_fingerprints

    inline_line20 = parse_wontfix_replies(
        [
            {
                "id": 2101,
                "user": {"login": "alice", "type": "User"},
                "path": "pilot1742/demo.py",
                "side": "RIGHT",
                "line": 20,
                "body": "不修：保留",
            }
        ],
        allowed_authors={"alice"},
    )
    assert bind_author_replies(c3.findings, inline_line20, stale_location_fingerprints=c3.stale_location_fingerprints) == {}
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                c3,
                [{"finding_id": fid, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图借未证明坐标放行"}],
            ),
            c3,
            verifier_model="claude-opus-5-5",
            author_replies=inline_line20,
        )

    # 仅显式 [finding_id] 可合法解除
    explicit_reply = parse_wontfix_replies(
        [{"id": 2102, "user": {"login": "alice", "type": "User"}, "body": f"[{fid}] 不修：显式指纹确认保留"}],
        allowed_authors={"alice"},
    )
    v3_ok = parse_verifier_output(
        _verifier_payload(
            c3,
            [{"finding_id": fid, "verdict": "resolved_by_wontfix", "verifier_evidence": "显式指纹回复有效"}],
        ),
        c3,
        verifier_model="claude-opus-5-5",
        author_replies=explicit_reply,
    )
    assert v3_ok.verdicts[0].verdict is VerificationVerdict.RESOLVED_BY_WONTFIX

    # 正向对照：第 2 轮未重定位且坐标保持第 42 行不变 -> 第 3 轮回到 HEAD_1 时成对锚点匹配，非 stale
    e2_unchanged_42 = RoundHistoryEntry(
        2,
        HEAD_2,
        frozenset({fid}),
        (f1_line42,),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r11-i2-u2-1", "r11-i2-u2-2"}),
    )
    c3_back_to_h1 = build_round_candidates(
        round_number=3,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=3, head_sha=HEAD_1),
        history=(e1, e2_unchanged_42),
    )
    assert c3_back_to_h1.stale_location_fingerprints == frozenset()


def test_r11_important3_infer_model_family_rejects_multi_family_prefixes() -> None:
    """R10 Important 3：模型名同时命中多个家族时 fail-closed 拒收，禁止路由前缀伪装异家族。"""
    with pytest.raises(ConvergenceError):
        ReviewPanel(("deepseek-chat", "deepseek-chat"), "openai/deepseek-chat")

    for ambiguous_model in (
        "openai/deepseek-chat",
        "anthropic/gpt-6",
        "google/claude-opus-5-5",
        "moonshot/gemini-4-neon",
        "openai:qwen3-coder",
        "claude-gpt-bridge",
    ):
        with pytest.raises(ConvergenceError):
            infer_model_family(ambiguous_model)

    expected_single_family = {
        "gpt-6.1-sol": "openai",
        "gpt-6.2-astra": "openai",
        "openai/gpt-6.1-sol": "openai",
        "claude-opus-5-5": "anthropic",
        "anthropic/claude-opus-5-5": "anthropic",
        "kimi-k3.1-pro": "moonshot",
        "gemini-4-neon": "google",
        "deepseek-chat": "deepseek",
        "qwen3-coder": "qwen",
        "mistral-large": "mistral",
        "meta-llama-3.1": "meta",
    }
    for model_name, expected_family in expected_single_family.items():
        assert infer_model_family(model_name) == expected_family


def test_r11_important4_same_comment_conflict_grouped_by_resolved_target_fingerprint() -> None:
    """R10 Important 4：同评论冲突检查按解析后目标指纹 fid 分组，封堵缩写+全长与混合锚点不同理由绕过。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    f2 = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/other.py",
        line=10,
        category="边界",
        failure_scenario="独立发现不受影响",
    )
    fid = f1.finding_id
    short_id = fid[:8]

    # 核心反例：单候选 F，同评论含 [F[:8]] 不修：理由甲 与 [F] 不修：理由乙 -> 不绑定，resolved_by_wontfix 抛 ConvergenceError
    parsed_conflict = parse_wontfix_replies(
        [
            {
                "id": 2201,
                "user": {"login": "alice", "type": "User"},
                "body": f"[{short_id}] 不修：理由甲\n[{fid}] 不修：理由乙",
            }
        ],
        allowed_authors={"alice"},
    )
    assert bind_author_replies([f1], parsed_conflict) == {}
    cand = _candidates([f1])
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand,
                [{"finding_id": fid, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图绕过同评论冲突"}],
            ),
            cand,
            verifier_model="claude-opus-5-5",
            author_replies=parsed_conflict,
        )

    # 直接构造 AuthorReply（绕过 parse_wontfix_replies）同样拒收
    direct_short_full = [
        AuthorReply(short_id, None, None, "理由甲", "2202", "alice"),
        AuthorReply(fid, None, None, "理由乙", "2202", "alice"),
    ]
    assert bind_author_replies([f1], direct_short_full) == {}

    # 同评论混写显式 ID 与显式文件路径+行号指向同一 F 且理由不同 -> 不得用高优先级 ID 覆盖不同理由
    mixed_anchor = parse_wontfix_replies(
        [
            {
                "id": 2203,
                "user": {"login": "alice", "type": "User"},
                "body": f"[{fid}] 不修：理由甲\npilot1742/demo.py:42 不修：理由乙",
            }
        ],
        allowed_authors={"alice"},
    )
    assert bind_author_replies([f1], mixed_anchor) == {}

    # 同评论走私前缀：[F[:8]] 理由甲 + [F] 理由乙 + [F] 理由丙 -> 保留至下游按解析后目标整组拒收
    smuggled_prefix = parse_wontfix_replies(
        [
            {
                "id": 2204,
                "user": {"login": "alice", "type": "User"},
                "body": f"[{short_id}] 不修：理由甲\n[{fid}] 不修：理由乙\n[{fid}] 不修：理由丙",
            }
        ],
        allowed_authors={"alice"},
    )
    assert len(smuggled_prefix) == 3
    assert bind_author_replies([f1], smuggled_prefix) == {}
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand,
                [{"finding_id": fid, "verdict": "resolved_by_wontfix", "verifier_evidence": "走私前缀不得放行"}],
            ),
            cand,
            verifier_model="claude-opus-5-5",
            author_replies=smuggled_prefix,
        )
    assert (
        bind_author_replies(
            [f1],
            [
                AuthorReply(short_id, None, None, "理由甲", "2204", "alice"),
                AuthorReply(fid, None, None, "理由乙", "2204", "alice"),
                AuthorReply(fid, None, None, "理由丙", "2204", "alice"),
            ],
        )
        == {}
    )

    # 同一行内评论多行不同理由 -> 拒收
    inline_conflict = parse_wontfix_replies(
        [
            {
                "id": 2205,
                "user": {"login": "alice", "type": "User"},
                "path": "pilot1742/demo.py",
                "side": "RIGHT",
                "line": 42,
                "body": "不修：理由甲\n不修：理由乙",
            }
        ],
        allowed_authors={"alice"},
    )
    assert bind_author_replies([f1], inline_conflict) == {}

    # 正向对照：同评论内缩写 + 全长理由完全相同 -> 不误报冲突；且同评论内另一独立发现 f2 仍可正常绑定
    same_reason_plus_other = parse_wontfix_replies(
        [
            {
                "id": 2206,
                "user": {"login": "alice", "type": "User"},
                "body": f"[{short_id}] 不修：保留兼容性\n[{fid}] 不修：保留兼容性\n[{f2.finding_id}] 不修：另一独立理由",
            }
        ],
        allowed_authors={"alice"},
    )
    bound_ok = bind_author_replies([f1, f2], same_reason_plus_other)
    assert set(bound_ok.keys()) == {fid, f2.finding_id}
    assert bound_ok[fid].reason == "保留兼容性"
    assert bound_ok[f2.finding_id].reason == "另一独立理由"

    # 同评论中 f1 冲突但 f2 不冲突 -> 仅拒收 f1，f2 照常绑定
    partial_conflict = parse_wontfix_replies(
        [
            {
                "id": 2207,
                "user": {"login": "alice", "type": "User"},
                "body": f"[{short_id}] 不修：理由甲\n[{fid}] 不修：理由乙\n[{f2.finding_id}] 不修：独立合法理由",
            }
        ],
        allowed_authors={"alice"},
    )
    bound_partial = bind_author_replies([f1, f2], partial_conflict)
    assert set(bound_partial.keys()) == {f2.finding_id}


def test_r11_important5_reason_requires_visible_base_character() -> None:
    """R10 Important 5：理由必须含至少一个可见基字符，拒绝纯变体选择符与组合附加符号，同时保留合法 emoji/变音符。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    fid = f1.finding_id

    def parse_one(body: str) -> tuple[AuthorReply, ...]:
        return parse_wontfix_replies(
            [{"id": 2301, "user": {"login": "alice", "type": "User"}, "body": body}],
            allowed_authors={"alice"},
        )

    # 核心反例：纯变体选择符与组合附加符号 -> 0 条回复
    for invisible_body in (
        f"[{fid}] 不修：&#xFE0F;",
        f"[{fid}] 不修：&#x0301;&#xFE0F;",
        f"[{fid}] 不修：&#xFE0E;",
        f"[{fid}] 不修：\u20dd",
        f"[{fid}] 不修：\u0903",
        f"[{fid}] 不修：**&#xFE0F;**",
        f"[{fid}] 不修：[&#xFE0F;](https://example.com)",
    ):
        assert parse_one(invisible_body) == (), f"expected 0 replies for {invisible_body!r}"

    # 端到端验证 resolved_by_wontfix 抛 ConvergenceError
    cand = _candidates([f1])
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand,
                [{"finding_id": fid, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图用变体选择符充当理由"}],
            ),
            cand,
            verifier_model="claude-opus-5-5",
            author_replies=parse_one(f"[{fid}] 不修：&#xFE0F;"),
        )

    # AuthorReply 直接构造同样拒收
    for bad_reason in ("\ufe0f", "\u0301\ufe0f", "\ufe0e", "\u20dd", "\u0903", "\ue000"):
        with pytest.raises(ConvergenceError):
            AuthorReply(fid, None, None, bad_reason, "2302", "alice")

    # 正向对照：含可见基字符的 emoji（保留 \ufe0f）与组合音标文本完整保留
    emoji_replies = parse_one(f"[{fid}] 不修：⚠️ 保留兼容性")
    assert [(r.finding_id, r.reason) for r in emoji_replies] == [(fid, "⚠️ 保留兼容性")]
    assert "\ufe0f" in emoji_replies[0].reason

    cafe_nfc = parse_one(f"[{fid}] 不修：café")
    assert [(r.finding_id, r.reason) for r in cafe_nfc] == [(fid, "café")]
    cafe_nfd = parse_one(f"[{fid}] 不修：cafe\u0301")
    assert [(r.finding_id, r.reason) for r in cafe_nfd] == [(fid, "cafe\u0301")]


def test_r11_important6_parse_comment_marker_requires_0_to_3_leading_spaces() -> None:
    """R10 Important 6：parse_comment_marker 仅接受 0–3 空格缩进，4 空格或 Tab 缩进代码块不当作机器评论标记。"""
    head_ones = "1" * 40
    marker_line = f"<!-- deepagents:review-findings pr=1 round=1 head={head_ones} -->"

    # 核心反例：4 空格缩进代码块内的机器标记不视为机器评论，后续人类回复正常提取
    indented_4_body = f"    {marker_line}\n\n[abcdef12] 不修：保留"
    assert parse_comment_marker(indented_4_body) is None
    replies_4 = parse_wontfix_replies(
        [{"id": 2401, "user": {"login": "alice", "type": "User"}, "body": indented_4_body}],
        allowed_authors={"alice"},
    )
    assert [(r.finding_id, r.reason) for r in replies_4] == [("abcdef12", "保留")]

    # Tab 及 1..3 空格后接 Tab（展开均 >= 4 列）同样不视为机器评论
    for tab_prefix in ("\t", " \t", "  \t", "   \t", "     "):
        indented_body = f"{tab_prefix}{marker_line}\n\n[abcdef12] 不修：缩进代码块后回复"
        assert parse_comment_marker(indented_body) is None
        parsed = parse_wontfix_replies(
            [{"id": 2402, "user": {"login": "alice", "type": "User"}, "body": indented_body}],
            allowed_authors={"alice"},
        )
        assert [(r.finding_id, r.reason) for r in parsed] == [("abcdef12", "缩进代码块后回复")]

    # 正向对照：0–3 空格缩进（含尾部空格/Tab）仍被识别为机器评论并跳过
    for valid_prefix in ("", " ", "  ", "   "):
        valid_body = f"{valid_prefix}{marker_line}  \t\n\n[abcdef12] 不修：机器评论内示范"
        assert parse_comment_marker(valid_body) == (1, 1, head_ones)
        assert (
            parse_wontfix_replies(
                [{"id": 2403, "user": {"login": "alice", "type": "User"}, "body": valid_body}],
                allowed_authors={"alice"},
            )
            == ()
        )


def test_r12_important1_preserve_conflicting_directives_until_target_resolution() -> None:
    """R11 Important 1：不在 parse_wontfix_replies 提前丢弃冲突指令，保留全部指令至下游按解析后最终目标整组拒收。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    f2 = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/other.py",
        line=10,
        category="边界",
        failure_scenario="同评论独立发现不受影响",
    )
    fid = f1.finding_id
    cand_f1 = _candidates([f1])

    # Codex R11 最小反例：[F] 甲 + [F] 乙 + pilot1742/demo.py:42 丙 -> 整组拒收，绝不绑定 F
    id_conflict_plus_loc = parse_wontfix_replies(
        [
            {
                "id": 2501,
                "user": {"login": "alice", "type": "User"},
                "body": f"[{fid}] 不修：甲\n[{fid}] 不修：乙\npilot1742/demo.py:42 不修：丙",
            }
        ],
        allowed_authors={"alice"},
    )
    assert len(id_conflict_plus_loc) == 3
    assert bind_author_replies([f1], id_conflict_plus_loc) == {}
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand_f1,
                [{"finding_id": fid, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图借坐标绕过重复 ID 冲突"}],
            ),
            cand_f1,
            verifier_model="claude-opus-5-5",
            author_replies=id_conflict_plus_loc,
        )

    # 反向反例：pilot1742/demo.py:42 甲 + pilot1742/demo.py:42 乙 + [F] 丙 -> 同样整组拒收
    loc_conflict_plus_id = parse_wontfix_replies(
        [
            {
                "id": 2502,
                "user": {"login": "alice", "type": "User"},
                "body": f"pilot1742/demo.py:42 不修：甲\npilot1742/demo.py:42 不修：乙\n[{fid}] 不修：丙",
            }
        ],
        allowed_authors={"alice"},
    )
    assert len(loc_conflict_plus_id) == 3
    assert bind_author_replies([f1], loc_conflict_plus_id) == {}
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand_f1,
                [{"finding_id": fid, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图借 ID 绕过重复坐标冲突"}],
            ),
            cand_f1,
            verifier_model="claude-opus-5-5",
            author_replies=loc_conflict_plus_id,
        )

    # 重复 ID + 纯行内锚点混合 -> 同样整组拒收
    id_conflict_plus_inline = parse_wontfix_replies(
        [
            {
                "id": 2503,
                "user": {"login": "alice", "type": "User"},
                "path": "pilot1742/demo.py",
                "side": "RIGHT",
                "line": 42,
                "body": f"[{fid}] 不修：甲\n[{fid}] 不修：乙\n不修：丙",
            }
        ],
        allowed_authors={"alice"},
    )
    assert len(id_conflict_plus_inline) == 3
    assert bind_author_replies([f1], id_conflict_plus_inline) == {}

    # 同评论中 f1 存在冲突（含坐标走私）时仅拒收 f1，同评论内独立发现 f2 的无冲突指令不受影响
    mixed_with_f2 = parse_wontfix_replies(
        [
            {
                "id": 2504,
                "user": {"login": "alice", "type": "User"},
                "body": (
                    f"[{fid}] 不修：甲\n"
                    f"[{fid}] 不修：乙\n"
                    f"pilot1742/demo.py:42 不修：丙\n"
                    f"[{f2.finding_id}] 不修：独立合法理由"
                ),
            }
        ],
        allowed_authors={"alice"},
    )
    bound_mixed = bind_author_replies([f1, f2], mixed_with_f2)
    assert set(bound_mixed.keys()) == {f2.finding_id}
    assert bound_mixed[f2.finding_id].reason == "独立合法理由"
    cand_both = _candidates([f1, f2])
    ver_both = parse_verifier_output(
        _verifier_payload(
            cand_both,
            [
                {"finding_id": fid, "verdict": "confirmed", "verifier_evidence": "f1 冲突未解除"},
                {"finding_id": f2.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "f2 合法采信"},
            ],
        ),
        cand_both,
        verifier_model="claude-opus-5-5",
        author_replies=mixed_with_f2,
    )
    by_fid = {vf.finding.finding_id: vf for vf in ver_both.verdicts}
    assert by_fid[f2.finding_id].author_reply is not None
    assert by_fid[f2.finding_id].author_reply.reason == "独立合法理由"


def test_r12_important2_strict_consumed_reply_keys_canonical_format() -> None:
    """R11 Important 2：严格校验 consumed_reply_keys 规范格式，拒绝评论 ID / 指纹含空格或非规范写法。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    fid = f1.finding_id

    # Codex R11 最小反例：第 1 轮用 comment:42:resolved:<F> 解除 F -> 第 2 轮重开确认 F -> 第 3 轮传 comment: 42 :resolved:<F>
    e1 = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r12-i2-r1-1", "r12-i2-r1-2"}),
        resolved_fingerprints=frozenset({fid}),
        consumed_reply_keys=frozenset({f"comment:42:resolved:{fid}"}),
    )
    e2 = RoundHistoryEntry(
        2,
        HEAD_2,
        frozenset({fid}),
        (f1,),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r12-i2-r2-1", "r12-i2-r2-2"}),
    )

    # 1) 构造 RoundHistoryEntry 立即抛 ConvergenceError
    with pytest.raises(ConvergenceError):
        RoundHistoryEntry(
            3,
            HEAD_2,
            frozenset(),
            (),
            panel=DEFAULT_PANEL,
            finder_session_ids=frozenset({"r12-i2-r3-1", "r12-i2-r3-2"}),
            resolved_fingerprints=frozenset({fid}),
            consumed_reply_keys=frozenset({f"comment: 42 :resolved:{fid}"}),
        )

    # 2) 即使绕过 __post_init__ 篡改历史项，plan_next_round 与 RoundCandidates 也在 _validate_history_chain 中立即拒收
    e3_tampered = RoundHistoryEntry(
        3,
        HEAD_2,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r12-i2-r3t-1", "r12-i2-r3t-2"}),
        resolved_fingerprints=frozenset({fid}),
        consumed_reply_keys=frozenset({f"comment:99:resolved:{fid}"}),
    )
    object.__setattr__(e3_tampered, "consumed_reply_keys", frozenset({f"comment: 42 :resolved:{fid}"}))
    with pytest.raises(ConvergenceError):
        plan_next_round(BASE_SHA, HEAD_2, (e1, e2, e3_tampered))
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=4,
            head_sha=HEAD_2,
            panel=DEFAULT_PANEL,
            finder_batches=_batches_for_panel([], round_number=4, head_sha=HEAD_2),
            history=(e1, e2, e3_tampered),
        )

    # 3) 覆盖所有非法键形态：RoundHistoryEntry / RoundDecision / parse_verifier_output / bind_author_replies 全部统一拒收
    bad_keys = (
        "",
        "   ",
        f" comment:42:resolved:{fid}",
        f"comment:42:resolved:{fid} ",
        f"COMMENT:42:resolved:{fid}",
        f"comment: 42 :resolved:{fid}",
        f"comment:42 :resolved:{fid}",
        f"comment: 42:resolved:{fid}",
        f"comment:4 2:resolved:{fid}",
        f"comment:42\u200b:resolved:{fid}",
        f"comment:42\u3164:resolved:{fid}",
        f"comment::resolved:{fid}",
        f"comment:42:resolved:{fid.upper()}",
        f"comment:42:resolved: {fid}",
        "comment:42:resolved:abcdef12",
        "comment:42:finding:abcde",
        "comment:42:finding:ABCDEF12",
        "comment:42:inline:0123456789abcde",
        "comment:42:inline:0123456789ABCDEF",
        f"comment:42:unknown:{fid}",
        "comment:42:loc:",
        "comment:42:loc:./pilot1742/demo.py:42",
        "comment:42:loc:pilot1742//demo.py:42",
        "comment:42:loc:pilot1742/demo.py:0",
        "comment:42:loc:pilot1742/demo.py:042",
        "comment:42:loc:pilot1742/demo.py: 42",
        "comment:42:loc:pilot1742/demo.py:",
        "comment:42:loc:a:b:42",
        f"comment:42:extra:resolved:{fid}",
    )
    cand = _candidates([f1])
    valid_payload = _verifier_payload(
        cand,
        [{"finding_id": fid, "verdict": "confirmed", "verifier_evidence": "确认问题存在"}],
    )
    for bad_key in bad_keys:
        with pytest.raises(ConvergenceError):
            RoundHistoryEntry(
                1,
                HEAD_1,
                frozenset(),
                (),
                panel=DEFAULT_PANEL,
                finder_session_ids=frozenset({"r12-bad-1", "r12-bad-2"}),
                consumed_reply_keys=frozenset({bad_key}),
            )
        with pytest.raises(ConvergenceError):
            RoundDecision(
                round_number=1,
                head_sha=HEAD_1,
                panel=DEFAULT_PANEL,
                outcome=RoundOutcome.PASS,
                github_state="success",
                description="pass",
                stop_auto_rereview=False,
                verified_findings=(),
                blocking_findings=(),
                non_blocking_findings=(),
                resolved_findings=(),
                rejected_findings=(),
                postable_findings=(),
                unresolved_important=(),
                consumed_reply_keys=frozenset({bad_key}),
            )
        with pytest.raises(ConvergenceError):
            parse_verifier_output(
                valid_payload,
                cand,
                verifier_model="claude-opus-5-5",
                consumed_reply_keys={bad_key},
            )
        with pytest.raises(ConvergenceError):
            bind_author_replies([f1], (), consumed_reply_keys={bad_key})

    # 4) 正向对照：4 种规范格式全部通过
    canonical_keys = frozenset(
        {
            f"comment:42:finding:{fid[:8]}",
            f"comment:42:finding:{fid}",
            "comment:42:inline:0123456789abcdef",
            f"comment:42:resolved:{fid}",
            "comment:42:loc:pilot1742/demo.py",
            "comment:42:loc:pilot1742/demo.py:42",
        }
    )
    ok_entry = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r12-ok-1", "r12-ok-2"}),
        resolved_fingerprints=frozenset({fid}),
        consumed_reply_keys=canonical_keys,
    )
    assert plan_next_round(BASE_SHA, HEAD_2, (ok_entry,)).consumed_reply_keys == canonical_keys


def test_r12_important3_exclude_default_ignorable_and_blank_fillers_from_visible_base() -> None:
    """R11 Important 3：将所有 Unicode Default_Ignorable_Code_Point 与空白填充符排除出可见基字符判定。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    fid = f1.finding_id

    def parse_one(body: str) -> tuple[AuthorReply, ...]:
        return parse_wontfix_replies(
            [{"id": 2601, "user": {"login": "alice", "type": "User"}, "body": body}],
            allowed_authors={"alice"},
        )

    # Codex R11 最小反例：Hangul Filler (U+3164) 与其他空白填充符/Default_Ignorable -> 0 条回复
    for blank_body in (
        f"[{fid}] 不修：&#x3164;",
        f"[{fid}] 不修：&#x115F;&#x1160;&#xFFA0;&#x2800;",
        f"[{fid}] 不修：\u3164",
        f"[{fid}] 不修：\u115f\u1160\uffa0\u2800",
        f"[{fid}] 不修：&#x00AD;&#x034F;&#x061C;&#x17B4;&#x17B5;&#x180B;&#x180E;",
        f"[{fid}] 不修：&#x200B;&#x202A;&#x2060;&#xFEFF;&#x1BCA0;&#x1D173;&#xE0020;&#xE0100;",
    ):
        assert parse_one(blank_body) == (), f"expected 0 replies for {blank_body!r}"

    # 端到端验证 resolved_by_wontfix 抛 ConvergenceError
    cand = _candidates([f1])
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand,
                [{"finding_id": fid, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图用 U+3164 充当理由"}],
            ),
            cand,
            verifier_model="claude-opus-5-5",
            author_replies=parse_one(f"[{fid}] 不修：&#x3164;"),
        )

    # 直接构造 AuthorReply 同样全部抛 ConvergenceError
    for bad_reason in (
        "\u3164",
        "\u115f",
        "\u1160",
        "\uffa0",
        "\u2800",
        "\u115f\u1160\uffa0\u2800",
        "\u00ad",
        "\u034f",
        "\u061c",
        "\u17b4",
        "\u17b5",
        "\u180b",
        "\u180e",
        "\u200b",
        "\u202a",
        "\u2060",
        "\ufeff",
        "\U0001bca0",
        "\U0001d173",
        "\U000e0020",
        "\U000e0100",
    ):
        with pytest.raises(ConvergenceError):
            AuthorReply(fid, None, None, bad_reason, "2602", "alice")

    # 正向对照：含变体选择符的 emoji、变音符、韩文音节全部完整保留
    emoji_replies = parse_one(f"[{fid}] 不修：⚠️ 保留兼容性")
    assert [(r.finding_id, r.reason) for r in emoji_replies] == [(fid, "⚠️ 保留兼容性")]
    assert "\ufe0f" in emoji_replies[0].reason

    cafe_replies = parse_one(f"[{fid}] 不修：café")
    assert [(r.finding_id, r.reason) for r in cafe_replies] == [(fid, "café")]
    cafe_nfd_replies = parse_one(f"[{fid}] 不修：cafe\u0301")
    assert [(r.finding_id, r.reason) for r in cafe_nfd_replies] == [(fid, "cafe\u0301")]

    korean_replies = parse_one(f"[{fid}] 不修：한국어")
    assert [(r.finding_id, r.reason) for r in korean_replies] == [(fid, "한국어")]


def test_r13_important1_pin_loc_and_inline_reply_targets_prevent_rebinding_to_new_finding() -> None:
    """R12 Important 1：坐标/行内回复首次命中后锁定目标指纹，禁止在后续轮次改绑到同位置的新指纹 B，同时保留同目标解除语义。"""
    f_a = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="空值解引用",
        failure_scenario="旧缺陷 A：第 42 行未判空",
    )
    f_b = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="越界访问",
        failure_scenario="新缺陷 B：第 42 行数组索引未校验",
    )
    assert f_a.finding_id != f_b.finding_id

    # 1) Codex R12 最小反例（loc 坐标回复）：第 1 轮评论 42 命中 A 但核实者仍确认 A -> 锁定至 A；第 2 轮 A 已修，同行出现新指纹 B -> 禁止改绑到 B
    replies_loc = parse_wontfix_replies(
        [
            {
                "id": 42,
                "user": {"login": "alice", "type": "User"},
                "body": "pilot1742/demo.py:42 不修：保留旧行为",
            }
        ],
        allowed_authors={"alice"},
    )
    assert len(replies_loc) == 1
    loc_key = replies_loc[0].reply_key
    assert loc_key == "comment:42:loc:pilot1742/demo.py:42"

    c1 = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_a], round_number=1, head_sha=HEAD_1),
    )
    v1 = parse_verifier_output(
        _verifier_payload(
            c1,
            [{"finding_id": f_a.finding_id, "verdict": "confirmed", "verifier_evidence": "A 仍构成真实空指针风险"}],
        ),
        c1,
        verifier_model="claude-opus-5-5",
        author_replies=replies_loc,
    )
    dec1 = evaluate_round(v1)
    assert dec1.outcome == RoundOutcome.BLOCKED
    assert dec1.github_state == "failure"
    assert loc_key not in dec1.consumed_reply_keys
    assert (loc_key, f_a.finding_id) in dec1.bound_reply_targets
    e1 = dec1.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1))
    assert (loc_key, f_a.finding_id) in e1.bound_reply_targets

    # 第 2 轮换 HEAD：A 已修，第 42 行出现新指纹 B，无新回复
    plan2 = plan_next_round(BASE_SHA, HEAD_2, [e1], author_replies=replies_loc)
    assert (loc_key, f_a.finding_id) in plan2.bound_reply_targets
    assert (
        bind_author_replies(
            [f_b],
            plan2.author_replies,
            consumed_reply_keys=plan2.consumed_reply_keys,
            bound_reply_targets=plan2.bound_reply_targets,
        )
        == {}
    )

    c2 = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_b], round_number=2, head_sha=HEAD_2),
        history=plan2.history,
    )
    # 即使调用方未显式传 bound_reply_targets，parse_verifier_output 也必须从 candidates.history 继承锁定并拒绝 B
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                c2,
                [
                    {"finding_id": f_a.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "A 已在新提交中修复"},
                    {"finding_id": f_b.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图复用旧评论 42 放行 B"},
                ],
            ),
            c2,
            verifier_model="claude-opus-5-5",
            author_replies=plan2.author_replies,
            consumed_reply_keys=plan2.consumed_reply_keys,
        )

    # 绕过 parse_verifier_output 直接构造 VerifiedRound 同样立即抛 ConvergenceError
    vf_a_fixed = _verified(
        f_a,
        VerificationVerdict.RESOLVED_BY_FIX,
        verifier_evidence="A 已修复",
        round_number=2,
        head_sha=HEAD_2,
    )
    vf_b_hijack = _verified(
        f_b,
        VerificationVerdict.RESOLVED_BY_WONTFIX,
        verifier_evidence="试图绕过 parse_verifier_output 改绑 B",
        round_number=2,
        head_sha=HEAD_2,
        author_reply=replies_loc[0],
    )
    with pytest.raises(ConvergenceError):
        VerifiedRound(candidates=c2, verdicts=(vf_a_fixed, vf_b_hijack))

    # 偷带历史锁定到 A 的 related_reply_keys 到 B 上也必须被 VerifiedRound 拒收
    vf_b_smuggled = VerifiedFinding(
        finding=f_b,
        verdict=VerificationVerdict.CONFIRMED,
        verifier_model="claude-opus-5-5",
        verifier_evidence="B 成立",
        round_number=2,
        head_sha=HEAD_2,
        related_reply_keys=(loc_key,),
    )
    with pytest.raises(ConvergenceError):
        VerifiedRound(candidates=c2, verdicts=(vf_a_fixed, vf_b_smuggled))

    # 正常路径：A 标 resolved_by_fix、B 标 confirmed -> BLOCKED，且历史锁定持续延续
    v2_ok = parse_verifier_output(
        _verifier_payload(
            c2,
            [
                {"finding_id": f_a.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "A 已修复"},
                {"finding_id": f_b.finding_id, "verdict": "confirmed", "verifier_evidence": "B 为新问题，阻断合并"},
            ],
        ),
        c2,
        verifier_model="claude-opus-5-5",
        author_replies=plan2.author_replies,
        consumed_reply_keys=plan2.consumed_reply_keys,
    )
    dec2_ok = evaluate_round(v2_ok, author_replies=replies_loc)
    assert dec2_ok.outcome == RoundOutcome.BLOCKED
    assert (loc_key, f_a.finding_id) in dec2_ok.bound_reply_targets
    assert loc_key in dec2_ok.consumed_reply_keys
    e2_ok = dec2_ok.to_history_entry(rendered=render_findings_comment(1928, HEAD_2, dec2_ok))
    assert (loc_key, f_a.finding_id) in e2_ok.bound_reply_targets
    assert loc_key in e2_ok.consumed_reply_keys

    # 正向对照：第 2 轮若 A 本身仍在第 42 行重定位（哪怕同行新出现 B），评论 42 仍只匹配 A 并可解除同一个 A，绝不匹配 B
    c2_same_a = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_a, f_b], round_number=2, head_sha=HEAD_2),
        history=plan2.history,
    )
    v2_same_a = parse_verifier_output(
        _verifier_payload(
            c2_same_a,
            [
                {"finding_id": f_a.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "第 2 轮采信针对 A 的理由"},
                {"finding_id": f_b.finding_id, "verdict": "confirmed", "verifier_evidence": "B 仍阻断"},
            ],
        ),
        c2_same_a,
        verifier_model="claude-opus-5-5",
        author_replies=plan2.author_replies,
        consumed_reply_keys=plan2.consumed_reply_keys,
    )
    by_id_same_a = {vf.finding.finding_id: vf for vf in v2_same_a.verdicts}
    assert by_id_same_a[f_a.finding_id].author_reply == replies_loc[0]
    assert by_id_same_a[f_b.finding_id].related_reply_keys == ()

    # 2) 行内回复（inline）同样锁定首次匹配目标，且非阻断 Nit（第 1 轮 PASS）也锁定目标指纹
    f_nit = _finding(
        severity=Severity.NIT,
        file="pilot1742/demo.py",
        line=42,
        category="命名风格",
        failure_scenario="变量命名略显简略",
    )
    replies_inline = parse_wontfix_replies(
        [
            {
                "id": 43,
                "user": {"login": "alice", "type": "User"},
                "path": "pilot1742/demo.py",
                "line": 42,
                "side": "RIGHT",
                "body": "不修：行内保持现有命名",
            }
        ],
        allowed_authors={"alice"},
    )
    assert len(replies_inline) == 1
    inline_key = replies_inline[0].reply_key
    assert inline_key.startswith("comment:43:inline:")

    c1_nit = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_nit], round_number=1, head_sha=HEAD_1),
    )
    v1_nit = parse_verifier_output(
        _verifier_payload(
            c1_nit,
            [{"finding_id": f_nit.finding_id, "verdict": "confirmed", "verifier_evidence": "Nit 成立但不阻断"}],
        ),
        c1_nit,
        verifier_model="claude-opus-5-5",
        author_replies=replies_inline,
    )
    dec1_nit = evaluate_round(v1_nit)
    assert dec1_nit.outcome == RoundOutcome.PASS
    assert (inline_key, f_nit.finding_id) in dec1_nit.bound_reply_targets
    e1_nit = dec1_nit.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1_nit))

    plan2_nit = plan_next_round(BASE_SHA, HEAD_2, [e1_nit], author_replies=replies_inline)
    assert (inline_key, f_nit.finding_id) in plan2_nit.bound_reply_targets
    c2_after_nit = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_b], round_number=2, head_sha=HEAD_2),
        history=plan2_nit.history,
    )
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                c2_after_nit,
                [{"finding_id": f_b.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "不得用 Nit 的行内回复解除新 Important B"}],
            ),
            c2_after_nit,
            verifier_model="claude-opus-5-5",
            author_replies=plan2_nit.author_replies,
        )

    # 3) 第 1 轮歧义多目标坐标回复不会导致 evaluate_round 冲突崩溃，并被消费防后续改绑
    ambig_reply = AuthorReply(None, "pilot1742/demo.py", None, "整文件不修", "44", "alice")
    c1_ambig = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_a, f_b], round_number=1, head_sha=HEAD_1),
    )
    v1_ambig = parse_verifier_output(
        _verifier_payload(
            c1_ambig,
            [
                {"finding_id": f_a.finding_id, "verdict": "confirmed", "verifier_evidence": "A 成立"},
                {"finding_id": f_b.finding_id, "verdict": "confirmed", "verifier_evidence": "B 成立"},
            ],
        ),
        c1_ambig,
        verifier_model="claude-opus-5-5",
        author_replies=[ambig_reply],
    )
    dec1_ambig = evaluate_round(v1_ambig)
    assert ambig_reply.reply_key in dec1_ambig.consumed_reply_keys
    assert all(k != ambig_reply.reply_key for k, _ in dec1_ambig.bound_reply_targets)

    # 4) bound_reply_targets 格式与冲突强校验（同轮冲突、跨轮冲突、非 loc/inline 键、非法指纹）
    for bad_targets in (
        frozenset({(f"comment:42:finding:{f_a.finding_id}", f_a.finding_id)}),
        frozenset({(f"comment:42:resolved:{f_a.finding_id}", f_a.finding_id)}),
        frozenset({("commnet:42:loc:pilot1742/demo.py:42", f_a.finding_id)}),
        frozenset({(loc_key, f_a.finding_id[:8])}),
        frozenset({(loc_key, f_a.finding_id.upper())}),
        frozenset({(loc_key, f_a.finding_id), (loc_key, f_b.finding_id)}),
    ):
        with pytest.raises(ConvergenceError):
            RoundHistoryEntry(
                1,
                HEAD_1,
                frozenset(),
                (),
                panel=DEFAULT_PANEL,
                finder_session_ids=frozenset({"r13-bt-1", "r13-bt-2"}),
                bound_reply_targets=bad_targets,
            )
        with pytest.raises(ConvergenceError):
            RoundPlan(
                round_number=1,
                review_scope="full_pr",
                diff_base_sha=BASE_SHA,
                diff_head_sha=HEAD_1,
                unresolved_prior_important=(),
                author_replies=(),
                already_posted_fingerprints=frozenset(),
                bound_reply_targets=bad_targets,
            )
        with pytest.raises(ConvergenceError):
            bind_author_replies([f_a], (), bound_reply_targets=bad_targets)

    # 跨历史链同一 reply_key 锁定不同指纹 -> _validate_history_chain 立即抛 ConvergenceError
    e1_pin_a = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r13-cross-1a", "r13-cross-1b"}),
        bound_reply_targets=frozenset({(loc_key, f_a.finding_id)}),
    )
    e2_pin_b = RoundHistoryEntry(
        2,
        HEAD_2,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r13-cross-2a", "r13-cross-2b"}),
        bound_reply_targets=frozenset({(loc_key, f_b.finding_id)}),
    )
    with pytest.raises(ConvergenceError):
        plan_next_round(BASE_SHA, HEAD_3, (e1_pin_a, e2_pin_b))
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=3,
            head_sha=HEAD_3,
            panel=DEFAULT_PANEL,
            finder_batches=_batches_for_panel([], round_number=3, head_sha=HEAD_3),
            history=(e1_pin_a, e2_pin_b),
        )


def test_r13_important2_reject_non_canonical_reply_keys_like_commnet_typo() -> None:
    """R12 Important 2：_validate_consumed_reply_key 删除非 comment: 逃生分支，严格拒绝一切非 4 种规范格式键。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    fid = f1.finding_id
    cand = _candidates([f1])
    valid_payload = _verifier_payload(
        cand,
        [{"finding_id": fid, "verdict": "confirmed", "verifier_evidence": "确认问题存在"}],
    )

    typo_keys = (
        "commnet:42:resolved:a98df8e465064919",
        f"commnet:42:resolved:{fid}",
        "reply:42:resolved:a98df8e465064919",
        "custom-arbitrary-key",
        "42:loc:pilot1742/demo.py:42",
    )
    for bad_key in typo_keys:
        with pytest.raises(ConvergenceError):
            RoundHistoryEntry(
                1,
                HEAD_1,
                frozenset(),
                (),
                panel=DEFAULT_PANEL,
                finder_session_ids=frozenset({"r13-i2-1", "r13-i2-2"}),
                consumed_reply_keys=frozenset({bad_key}),
            )
        with pytest.raises(ConvergenceError):
            RoundPlan(
                round_number=1,
                review_scope="full_pr",
                diff_base_sha=BASE_SHA,
                diff_head_sha=HEAD_1,
                unresolved_prior_important=(),
                author_replies=(),
                already_posted_fingerprints=frozenset(),
                consumed_reply_keys=frozenset({bad_key}),
            )
        with pytest.raises(ConvergenceError):
            parse_verifier_output(
                valid_payload,
                cand,
                verifier_model="claude-opus-5-5",
                consumed_reply_keys={bad_key},
            )
        with pytest.raises(ConvergenceError):
            bind_author_replies([f1], (), consumed_reply_keys={bad_key})
        with pytest.raises(ConvergenceError):
            VerifiedFinding(
                finding=f1,
                verdict=VerificationVerdict.CONFIRMED,
                verifier_model="claude-opus-5-5",
                verifier_evidence="核实存在",
                round_number=1,
                head_sha=HEAD_1,
                related_reply_keys=(bad_key,),
            )

    # 即使事后篡改历史项，plan_next_round 与 RoundCandidates 也立即抛 ConvergenceError
    tampered = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r13-i2-t1", "r13-i2-t2"}),
    )
    object.__setattr__(tampered, "consumed_reply_keys", frozenset({"commnet:42:resolved:a98df8e465064919"}))
    with pytest.raises(ConvergenceError):
        plan_next_round(BASE_SHA, HEAD_2, (tampered,))
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=2,
            head_sha=HEAD_2,
            panel=DEFAULT_PANEL,
            finder_batches=_batches_for_panel([], round_number=2, head_sha=HEAD_2),
            history=(tampered,),
        )


def test_r13_important3_loc_key_cannot_masquerade_as_resolved_proof_in_history_chain() -> None:
    """R12 Important 3：按结构化键类型判断 resolved 凭证，禁止 comment:<cid>:loc:resolved:<fp> 伪装 resolved。"""
    f_numeric_fp = _finding(category="2944")
    fp = f_numeric_fp.finding_id
    assert fp == "5435290667808544"

    e1 = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset({fp}),
        (f_numeric_fp,),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r13-i3-r1-1", "r13-i3-r1-2"}),
    )
    spoof_loc_key = f"comment:42:loc:resolved:{fp}"
    e2_spoof = RoundHistoryEntry(
        2,
        HEAD_1,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r13-i3-r2-1", "r13-i3-r2-2"}),
        resolved_fingerprints=frozenset({fp}),
        consumed_reply_keys=frozenset({spoof_loc_key}),
    )

    with pytest.raises(ConvergenceError):
        plan_next_round(BASE_SHA, HEAD_1, (e1, e2_spoof))
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=3,
            head_sha=HEAD_1,
            panel=DEFAULT_PANEL,
            finder_batches=_batches_for_panel([], round_number=3, head_sha=HEAD_1),
            history=(e1, e2_spoof),
        )

    # 正向对照：真实 comment:42:resolved:<fp> 凭证正常通过
    e2_real = RoundHistoryEntry(
        2,
        HEAD_1,
        frozenset(),
        (),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r13-i3-ok-1", "r13-i3-ok-2"}),
        resolved_fingerprints=frozenset({fp}),
        consumed_reply_keys=frozenset({f"comment:42:resolved:{fp}"}),
    )
    plan3 = plan_next_round(BASE_SHA, HEAD_1, (e1, e2_real))
    assert plan3.round_number == 3
    assert plan3.unresolved_prior_important == ()


def test_r13_important4_verifier_evidence_and_finding_text_require_visible_base_char() -> None:
    """R12 Important 4：verifier_evidence 与发现核心文本字段强制包含至少 1 个可见基字符，封堵 U+3164 等不可见占位。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    fid = f1.finding_id
    cand = _candidates([f1])

    invisible_samples = (
        "\u3164",
        "\u200b",
        "\ufe0f",
        "\u2800",
        "\u115f\u1160\uffa0",
        "\u0301",
        "\ufeff",
        "\U000e0020",
    )
    for bad_text in invisible_samples:
        with pytest.raises(ConvergenceError):
            parse_verifier_output(
                _verifier_payload(
                    cand,
                    [{"finding_id": fid, "verdict": "rejected", "verifier_evidence": bad_text}],
                ),
                cand,
                verifier_model="claude-opus-5-5",
            )
        with pytest.raises(ConvergenceError):
            VerifiedFinding(
                finding=f1,
                verdict=VerificationVerdict.REJECTED,
                verifier_model="claude-opus-5-5",
                verifier_evidence=bad_text,
                round_number=1,
                head_sha=HEAD_1,
            )
        with pytest.raises(ConvergenceError):
            _finding(category=bad_text)
        with pytest.raises(ConvergenceError):
            _finding(failure_scenario=bad_text)
        with pytest.raises(ConvergenceError):
            _finding(evidence=bad_text)
        with pytest.raises(ConvergenceError):
            _finding(class_scope=bad_text)
        with pytest.raises(ConvergenceError):
            parse_finder_output(
                {
                    "findings": [
                        {
                            "severity": "Important",
                            "file": "pilot1742/demo.py",
                            "line": 42,
                            "category": "空值解引用",
                            "failure_scenario": "真实失败场景",
                            "evidence": bad_text,
                        }
                    ]
                },
                source_model="gpt-6-astra",
            )

    # 正向对照：含变体选择符/组合音符/多语种可见基字符的证据与发现字段正常通过
    for good_evidence in ("⚠️ 核实第 42 行已判空", "café 已校验", "cafe\u0301 核实通过", "한국어 核实"):
        vr = parse_verifier_output(
            _verifier_payload(
                cand,
                [{"finding_id": fid, "verdict": "rejected", "verifier_evidence": good_evidence}],
            ),
            cand,
            verifier_model="claude-opus-5-5",
        )
        assert vr.verdicts[0].verifier_evidence == good_evidence


def test_r14_important1_cross_head_first_seen_loc_reply_conflicts_with_stale_finding() -> None:
    """R13 Important 1：首次读入的跨 HEAD 无 ID 坐标/行内回复若命中过期结转发现坐标，判为歧义拒收，并在过期发现离场时消费旧回复。"""
    f_a = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="空值解引用",
        failure_scenario="第 1 轮缺陷 A：第 42 行未判空",
    )
    f_b = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="越界访问",
        failure_scenario="第 2 轮新缺陷 B：第 42 行索引越界",
    )
    f_c = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="除零风险",
        failure_scenario="第 3 轮新缺陷 C：第 42 行未校验分母为零",
    )
    f_other = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/other.py",
        line=10,
        category="资源泄漏",
        failure_scenario="其他文件第 10 行未关闭句柄",
    )
    assert len({f_a.finding_id, f_b.finding_id, f_c.finding_id, f_other.finding_id}) == 4

    # 1) 第 1 轮在 HEAD_1 确认 A（此时尚无作者回复）
    c1 = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_a], round_number=1, head_sha=HEAD_1),
    )
    v1 = parse_verifier_output(
        _verifier_payload(
            c1,
            [{"finding_id": f_a.finding_id, "verdict": "confirmed", "verifier_evidence": "A 确认阻断"}],
        ),
        c1,
        verifier_model="claude-opus-5-5",
    )
    dec1 = evaluate_round(v1)
    e1 = dec1.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1))
    assert e1.bound_reply_targets == frozenset()

    # 两轮之间作者发评论（首次读入）：pilot1742/demo.py:42 不修：保留 A
    stale_loc_replies = parse_wontfix_replies(
        [
            {
                "id": 3101,
                "user": {"login": "alice", "type": "User"},
                "body": "pilot1742/demo.py:42 不修：保留 A",
            }
        ],
        allowed_authors={"alice"},
    )
    assert len(stale_loc_replies) == 1
    stale_loc_key = stale_loc_replies[0].reply_key

    # 同坐标行内回复与同文件无行号坐标回复同样应判歧义
    stale_inline_replies = parse_wontfix_replies(
        [
            {
                "id": 3102,
                "user": {"login": "alice", "type": "User"},
                "path": "pilot1742/demo.py",
                "line": 42,
                "side": "RIGHT",
                "body": "不修：保留 A（行内）",
            }
        ],
        allowed_authors={"alice"},
    )
    stale_file_replies = parse_wontfix_replies(
        [
            {
                "id": 3103,
                "user": {"login": "alice", "type": "User"},
                "body": "不修(pilot1742/demo.py)：保留 A（文件级）",
            }
        ],
        allowed_authors={"alice"},
    )

    # 2) 第 2 轮换 HEAD_2：A 结转过期，新发现 B 出现在同一 demo.py:42
    plan2 = plan_next_round(BASE_SHA, HEAD_2, [e1], author_replies=stale_loc_replies)
    c2 = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_b], round_number=2, head_sha=HEAD_2),
        history=plan2.history,
    )
    assert c2.stale_location_fingerprints == frozenset({f_a.finding_id})

    # bind_author_replies 既不绑定 A 也不绑定 B
    for candidate_replies in (stale_loc_replies, stale_inline_replies, stale_file_replies):
        assert (
            bind_author_replies(
                c2.findings,
                candidate_replies,
                stale_location_fingerprints=c2.stale_location_fingerprints,
            )
            == {}
        )

    # parse_verifier_output 给 A=resolved_by_fix、B=resolved_by_wontfix 必须抛 ConvergenceError
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                c2,
                [
                    {"finding_id": f_a.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "A 已修复"},
                    {"finding_id": f_b.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图误用保留 A 的评论解除 B"},
                ],
            ),
            c2,
            verifier_model="claude-opus-5-5",
            author_replies=stale_loc_replies,
        )

    # 直接构造 VerifiedRound 绕过 parse_verifier_output 同样抛 ConvergenceError
    with pytest.raises(ConvergenceError):
        VerifiedRound(
            candidates=c2,
            verdicts=(
                _verified(
                    f_a,
                    VerificationVerdict.RESOLVED_BY_FIX,
                    verifier_evidence="A 已修复",
                    round_number=2,
                    head_sha=HEAD_2,
                ),
                _verified(
                    f_b,
                    VerificationVerdict.RESOLVED_BY_WONTFIX,
                    verifier_evidence="绕过 parse_verifier_output 误绑 B",
                    round_number=2,
                    head_sha=HEAD_2,
                    author_reply=stale_loc_replies[0],
                ),
            ),
        )

    # 3) 第 2 轮合法裁决：A=resolved_by_fix、B=confirmed -> 旧回复在第 2 轮记入 consumed_reply_keys（无需重传 author_replies 亦成立）
    v2 = parse_verifier_output(
        _verifier_payload(
            c2,
            [
                {"finding_id": f_a.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "A 已修复"},
                {"finding_id": f_b.finding_id, "verdict": "confirmed", "verifier_evidence": "B 为新问题，继续阻断"},
            ],
        ),
        c2,
        verifier_model="claude-opus-5-5",
        author_replies=stale_loc_replies,
    )
    dec2 = evaluate_round(v2)
    assert dec2.outcome == RoundOutcome.BLOCKED
    assert stale_loc_key in dec2.consumed_reply_keys
    assert all(k != stale_loc_key for k, _ in dec2.bound_reply_targets)
    e2 = dec2.to_history_entry(rendered=render_findings_comment(1928, HEAD_2, dec2))
    assert stale_loc_key in e2.consumed_reply_keys

    # 4) 第 3 轮 A 离场后，该旧回复不能复活误解除 B 或新发现 C
    plan3 = plan_next_round(BASE_SHA, HEAD_3, [e1, e2], author_replies=stale_loc_replies)
    assert stale_loc_key in plan3.consumed_reply_keys
    assert plan3.author_replies == ()
    c3 = build_round_candidates(
        round_number=3,
        head_sha=HEAD_3,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_b, f_c], round_number=3, head_sha=HEAD_3),
        history=plan3.history,
    )
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                c3,
                [
                    {"finding_id": f_b.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图在第 3 轮复活旧回复解除 B"},
                    {"finding_id": f_c.finding_id, "verdict": "confirmed", "verifier_evidence": "C 阻断"},
                ],
            ),
            c3,
            verifier_model="claude-opus-5-5",
            author_replies=stale_loc_replies,
        )

    # 4b) 仅过期发现 A 在第 2 轮被修复（第 2 轮同行尚无 B），旧回复同样被消费，第 3 轮新发现 C 不能被复活解除
    c2_only_a = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=2, head_sha=HEAD_2),
        history=plan2.history,
    )
    v2_only_a = parse_verifier_output(
        _verifier_payload(
            c2_only_a,
            [{"finding_id": f_a.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "A 已修复"}],
        ),
        c2_only_a,
        verifier_model="claude-opus-5-5",
        author_replies=stale_loc_replies,
    )
    dec2_only_a = evaluate_round(v2_only_a)
    assert dec2_only_a.outcome == RoundOutcome.PASS
    assert stale_loc_key in dec2_only_a.consumed_reply_keys
    assert all(k != stale_loc_key for k, _ in dec2_only_a.bound_reply_targets)
    e2_only_a = dec2_only_a.to_history_entry(rendered=render_findings_comment(1928, HEAD_2, dec2_only_a))
    c3_new_c = build_round_candidates(
        round_number=3,
        head_sha=HEAD_3,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_c], round_number=3, head_sha=HEAD_3),
        history=(e1, e2_only_a),
    )
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                c3_new_c,
                [{"finding_id": f_c.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图在第 3 轮复活旧回复解除 C"}],
            ),
            c3_new_c,
            verifier_model="claude-opus-5-5",
            author_replies=stale_loc_replies,
        )

    # 5) 正向对照：
    # ① 写显式 [B_id] 不修：... 仍精确绑定 B
    explicit_b_reply = parse_wontfix_replies(
        [{"id": 3104, "user": {"login": "alice", "type": "User"}, "body": f"[{f_b.finding_id}] 不修：明确针对 B"}],
        allowed_authors={"alice"},
    )
    assert set(
        bind_author_replies(
            c2.findings,
            explicit_b_reply,
            stale_location_fingerprints=c2.stale_location_fingerprints,
        )
    ) == {f_b.finding_id}
    v2_explicit_b = parse_verifier_output(
        _verifier_payload(
            c2,
            [
                {"finding_id": f_a.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "A 已修复"},
                {"finding_id": f_b.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "显式 ID 解除 B"},
            ],
        ),
        c2,
        verifier_model="claude-opus-5-5",
        author_replies=explicit_b_reply,
    )
    assert evaluate_round(v2_explicit_b).outcome == RoundOutcome.PASS

    # ② 写其他文件/行号（other.py:10，未命中任何过期发现坐标）仍正常绑定 other.py:10 上的新发现
    c2_with_other = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_other], round_number=2, head_sha=HEAD_2),
        history=plan2.history,
    )
    other_loc_reply = parse_wontfix_replies(
        [{"id": 3105, "user": {"login": "alice", "type": "User"}, "body": "pilot1742/other.py:10 不修：生命周期由上层管理"}],
        allowed_authors={"alice"},
    )
    assert set(
        bind_author_replies(
            c2_with_other.findings,
            other_loc_reply,
            stale_location_fingerprints=c2_with_other.stale_location_fingerprints,
        )
    ) == {f_other.finding_id}

    # ③ 第 2 轮 A 在新 HEAD 被重新定位到第 20 行（不在 stale_location_fingerprints 中），第 20 行回复仍正常绑定 A
    f_a_line20 = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=20,
        category="空值解引用",
        failure_scenario="第 1 轮缺陷 A：第 42 行未判空",
    )
    assert f_a_line20.finding_id == f_a.finding_id
    c2_reloc = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_a_line20], round_number=2, head_sha=HEAD_2),
        history=plan2.history,
    )
    assert c2_reloc.stale_location_fingerprints == frozenset()
    reloc_reply = parse_wontfix_replies(
        [{"id": 3106, "user": {"login": "alice", "type": "User"}, "body": "pilot1742/demo.py:20 不修：新行号处确认不修"}],
        allowed_authors={"alice"},
    )
    assert set(
        bind_author_replies(
            c2_reloc.findings,
            reloc_reply,
            stale_location_fingerprints=c2_reloc.stale_location_fingerprints,
        )
    ) == {f_a.finding_id}


def test_r14_important2_verified_round_preserves_explicit_bound_reply_targets() -> None:
    """R13 Important 2：VerifiedRound 保留并校验显式传入的 bound_reply_targets，不再丢失单轮显式绑定。"""
    f_a = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="空值解引用",
        failure_scenario="A：第 42 行未判空",
    )
    f_b = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="越界访问",
        failure_scenario="B：第 42 行越界",
    )
    assert f_a.finding_id != f_b.finding_id

    reply = AuthorReply(None, "pilot1742/demo.py", 42, "仅针对 A 保持旧逻辑", "3201", "alice")
    explicit_targets = {reply.reply_key: f_a.finding_id}

    # 1) Codex R13 最小反例：A、B 同在 demo.py:42，历史为空，传入 bound_reply_targets={reply.reply_key: A.finding_id}
    bound = bind_author_replies([f_a, f_b], [reply], bound_reply_targets=explicit_targets)
    assert bound == {f_a.finding_id: reply}

    c1 = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_a, f_b], round_number=1, head_sha=HEAD_1),
    )
    v1 = parse_verifier_output(
        _verifier_payload(
            c1,
            [
                {"finding_id": f_a.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "采信对 A 的显式锁定不修理由"},
                {"finding_id": f_b.finding_id, "verdict": "confirmed", "verifier_evidence": "B 仍构成阻断"},
            ],
        ),
        c1,
        verifier_model="claude-opus-5-5",
        author_replies=[reply],
        bound_reply_targets=explicit_targets,
    )
    assert v1.bound_reply_targets == frozenset({(reply.reply_key, f_a.finding_id)})

    dec1 = evaluate_round(v1)
    assert dec1.outcome == RoundOutcome.BLOCKED
    assert [vf.finding.finding_id for vf in dec1.resolved_findings] == [f_a.finding_id]
    assert [vf.finding.finding_id for vf in dec1.blocking_findings] == [f_b.finding_id]
    assert (reply.reply_key, f_a.finding_id) in dec1.bound_reply_targets
    assert reply.reply_key in dec1.consumed_reply_keys

    e1 = dec1.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1))
    assert (reply.reply_key, f_a.finding_id) in e1.bound_reply_targets
    assert reply.reply_key in e1.consumed_reply_keys

    # 2) VerifiedRound 必须强校验 bound_reply_targets：非法类型/格式、与历史矛盾指纹、跨目标误用均抛 ConvergenceError
    vf_a_confirmed = _verified(f_a, VerificationVerdict.CONFIRMED, verifier_evidence="A 成立", round_number=1, head_sha=HEAD_1)
    vf_b_confirmed = _verified(f_b, VerificationVerdict.CONFIRMED, verifier_evidence="B 成立", round_number=1, head_sha=HEAD_1)
    with pytest.raises(ConvergenceError):
        VerifiedRound(
            candidates=c1,
            verdicts=(vf_a_confirmed, vf_b_confirmed),
            bound_reply_targets=[(reply.reply_key, f_a.finding_id)],  # type: ignore[arg-type]
        )
    with pytest.raises(ConvergenceError):
        VerifiedRound(
            candidates=c1,
            verdicts=(vf_a_confirmed, vf_b_confirmed),
            bound_reply_targets=frozenset({(f"comment:3201:finding:{f_a.finding_id}", f_a.finding_id)}),
        )
    with pytest.raises(ConvergenceError):
        VerifiedRound(
            candidates=c1,
            verdicts=(
                vf_a_confirmed,
                _verified(
                    f_b,
                    VerificationVerdict.RESOLVED_BY_WONTFIX,
                    verifier_evidence="试图用锁定到 A 的回复解除 B",
                    round_number=1,
                    head_sha=HEAD_1,
                    author_reply=reply,
                ),
            ),
            bound_reply_targets=frozenset({(reply.reply_key, f_a.finding_id)}),
        )

    # 与历史轮次已锁定指纹冲突 -> VerifiedRound 立即抛 ConvergenceError
    c2 = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_b], round_number=2, head_sha=HEAD_2),
        history=(e1,),
    )
    with pytest.raises(ConvergenceError):
        VerifiedRound(
            candidates=c2,
            verdicts=(_verified(f_b, VerificationVerdict.CONFIRMED, verifier_evidence="B 成立", round_number=2, head_sha=HEAD_2),),
            bound_reply_targets=frozenset({(reply.reply_key, f_b.finding_id)}),
        )


def test_r14_important3_gfm_rendered_visibility_for_verifier_evidence_and_finding_text() -> None:
    """R13 Important 3：按 GFM 渲染后可见性校验 verifier_evidence 与发现核心字段，封堵 HTML 实体/注释/空标签/链接定义等不可见证据。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    fid = f1.finding_id
    cand = _candidates([f1])

    invisible_markdown_samples = (
        "&#x3164;",
        "**&#x3164;**",
        "*&#x3164;*",
        "__&#x3164;__",
        "_&#x3164;_",
        "~~&#x3164;~~",
        "&#8203;",
        "&nbsp;",
        "<!-- hidden -->",
        "<!-- 伪证据 -->",
        "<span>&#xFE0F;</span>",
        "<span></span>",
        "[x]: /demo",
        "[&#x3164;](https://example.com)",
        "```python\n```",
        "```\n\u3164\n```",
    )
    for bad_md in invisible_markdown_samples:
        with pytest.raises(ConvergenceError):
            parse_verifier_output(
                _verifier_payload(
                    cand,
                    [{"finding_id": fid, "verdict": "rejected", "verifier_evidence": bad_md}],
                ),
                cand,
                verifier_model="claude-opus-5-5",
            )
        with pytest.raises(ConvergenceError):
            VerifiedFinding(
                finding=f1,
                verdict=VerificationVerdict.REJECTED,
                verifier_model="claude-opus-5-5",
                verifier_evidence=bad_md,
                round_number=1,
                head_sha=HEAD_1,
            )
        with pytest.raises(ConvergenceError):
            _finding(failure_scenario=bad_md)
        with pytest.raises(ConvergenceError):
            _finding(evidence=bad_md)
        with pytest.raises(ConvergenceError):
            parse_finder_output(
                {
                    "findings": [
                        {
                            "severity": "Important",
                            "file": "pilot1742/demo.py",
                            "line": 42,
                            "category": "空值解引用",
                            "failure_scenario": bad_md,
                            "evidence": "真实证据",
                        }
                    ]
                },
                source_model="gpt-6-astra",
            )
        with pytest.raises(ConvergenceError):
            parse_finder_output(
                {
                    "findings": [
                        {
                            "severity": "Important",
                            "file": "pilot1742/demo.py",
                            "line": 42,
                            "category": "空值解引用",
                            "failure_scenario": "真实场景",
                            "evidence": bad_md,
                        }
                    ]
                },
                source_model="gpt-6-astra",
            )

    # 正向对照：普通中英文、行内代码、代码块/多行、&amp; 实体、emoji 全部正常通过
    valid_markdown_samples = (
        "核实第 42 行已通过判空保护",
        "Confirmed null check at line 42",
        "输入 `&nbsp;` 会触发异常",
        "`&nbsp;`",
        "已复现：\n```python\nassert x is not None\n```",
        "```python\nassert x is not None\n```",
        "条件 a &amp; b 在空输入下恒为假",
        "&amp;",
        "⚠️ 核实存在空指针风险",
        "⚠️",
    )
    for good_md in valid_markdown_samples:
        vr = parse_verifier_output(
            _verifier_payload(
                cand,
                [{"finding_id": fid, "verdict": "rejected", "verifier_evidence": good_md}],
            ),
            cand,
            verifier_model="claude-opus-5-5",
        )
        assert vr.verdicts[0].verifier_evidence == good_md
        f_ok = _finding(failure_scenario=good_md, evidence=good_md)
        assert f_ok.failure_scenario == good_md
        assert f_ok.evidence == good_md


def test_r15_gfm_visibility_accepts_blocks_and_rejects_invisible_variants() -> None:
    """R15 缺陷 1：合法引用块/ATX 标题/Setext 标题/缩进代码/非静默 HTML 放行，各自全不可见变体继续拒绝，且不改变作者不修指令隔离语义。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    fid = f1.finding_id
    cand = _candidates([f1])

    valid_block_samples = (
        "> quoted line: demo.py:42 returns None",
        "> > nested quote: missing null guard",
        "> ### Root cause in quote",
        "> Root cause in quote\n> ---",
        ">     return None",
        "> <div>real text in quote</div>",
        "### Root cause: missing check",
        "### Root cause ###",
        "Root cause\n---",
        "Root cause\n===",
        "<div>real text</div>",
        "<div>\n  <p>real text</p>\n</div>",
        "<pre>return None</pre>",
        "<span>\nreal text\n</span>",
        "<blockquote>real text</blockquote>",
        "<!-- note -->real text",
        "\n\n    return None",
        "    return None",
        "    &#x3164;",
        "---\n\n    return None",
        "<!-- note -->\n\n    return None",
        "[x]: /demo\n\n    return None",
        "`&nbsp;`",
        "&amp;",
        "⚠️",
    )
    for good_md in valid_block_samples:
        vr = parse_verifier_output(
            _verifier_payload(
                cand,
                [{"finding_id": fid, "verdict": "rejected", "verifier_evidence": good_md}],
            ),
            cand,
            verifier_model="claude-opus-5-5",
        )
        assert vr.verdicts[0].verifier_evidence == good_md
        f_ok = _finding(failure_scenario=good_md, evidence=good_md)
        assert f_ok.failure_scenario == good_md
        assert f_ok.evidence == good_md

    invisible_block_samples = (
        "---",
        "***",
        "___",
        "[x]: /demo",
        "[x]: /demo\n---",
        "&#x3164;",
        "&#8203;",
        "**&#x3164;**",
        "> &#x3164;",
        "> **&#x3164;**",
        "> ---",
        "> [x]: /demo",
        ">",
        "> ### &#x3164;",
        "> <div>&#x3164;</div>",
        ">     \u3164",
        "###",
        "### ###",
        "### &#x3164;",
        "### &#x3164; ###",
        "### **&#x3164;**",
        "### <!-- hidden -->",
        "&#x3164;\n---",
        "**&#x3164;**\n===",
        "    \u3164",
        "---\n\n    \u3164",
        "[x]: /demo\n\n    \u3164",
        "<!-- hidden -->",
        "<!-- hidden -->\n\n    \u3164",
        "<!-- unclosed\n\n    return None",
        "<!-- unclosed\n\n### Root cause",
        "<!-- unclosed\n\n<div>real text</div>",
        "<script>alert(1)</script>",
        "<style>body{display:none}</style>",
        "<textarea>hidden</textarea>",
        "<template>hidden</template>",
        "<template>\n\n    return None\n\n</template>",
        "<noscript>hidden</noscript>",
        "<span></span>",
        "<span>&#xFE0F;</span>",
        "<span>\n&#xFE0F;\n</span>",
        "<div></div>",
        "<div>&#x3164;</div>",
        "<div title=\"real text\"></div>",
        "<div title=\"a>b\">&#x3164;</div>",
        "<div><!-- hidden --></div>",
        "<div><script>x</script><style>y</style></div>",
        "<pre>&#x3164;</pre>",
        "<blockquote>\n\n**&#x3164;**\n\n</blockquote>",
        "```python\n```",
        "```\n\u3164\n```",
    )
    for bad_md in invisible_block_samples:
        with pytest.raises(ConvergenceError):
            parse_verifier_output(
                _verifier_payload(
                    cand,
                    [{"finding_id": fid, "verdict": "rejected", "verifier_evidence": bad_md}],
                ),
                cand,
                verifier_model="claude-opus-5-5",
            )
        with pytest.raises(ConvergenceError):
            VerifiedFinding(
                finding=f1,
                verdict=VerificationVerdict.REJECTED,
                verifier_model="claude-opus-5-5",
                verifier_evidence=bad_md,
                round_number=1,
                head_sha=HEAD_1,
            )
        with pytest.raises(ConvergenceError):
            _finding(failure_scenario=bad_md)
        with pytest.raises(ConvergenceError):
            _finding(evidence=bad_md)

    # 回归确认：作者不修指令解析路径仍严格忽略引用块/标题/缩进与围栏代码/HTML 块
    non_directive_comments = [
        {"id": 9101, "user": {"login": "alice", "type": "User"}, "body": f"> [{fid}] 不修：引用块内不算指令"},
        {"id": 9102, "user": {"login": "alice", "type": "User"}, "body": f"### [{fid}] 不修：ATX 标题内不算指令"},
        {"id": 9103, "user": {"login": "alice", "type": "User"}, "body": f"[{fid}] 不修：Setext 标题不算指令\n---"},
        {"id": 9104, "user": {"login": "alice", "type": "User"}, "body": f"    [{fid}] 不修：缩进代码不算指令"},
        {"id": 9105, "user": {"login": "alice", "type": "User"}, "body": f"<div>[{fid}] 不修：HTML 块不算指令</div>"},
    ]
    assert parse_wontfix_replies(non_directive_comments, allowed_authors={"alice"}) == ()


def test_r15_stale_confirmed_consumes_unpinned_cross_head_coord_replies() -> None:
    """R15 缺陷 2：第 2 轮过期发现 A 保持 CONFIRMED 且无碰撞时，跨 HEAD 坐标/文件/行内回复须立即消费，第 3 轮 A 移位后绝不复活误绑新发现 C。"""
    f_a_line42 = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="空值解引用",
        failure_scenario="缺陷 A：第 42 行未判空",
    )
    f_a_line50 = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=50,
        category="空值解引用",
        failure_scenario="缺陷 A：第 42 行未判空",
    )
    assert f_a_line50.finding_id == f_a_line42.finding_id

    f_c_line42 = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="并发竞争",
        failure_scenario="第 3 轮新缺陷 C：第 42 行无锁写入",
    )
    assert f_c_line42.finding_id != f_a_line42.finding_id

    # R1 (HEAD_1): A@42 确认，尚无作者回复
    c1 = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_a_line42], round_number=1, head_sha=HEAD_1),
    )
    v1 = parse_verifier_output(
        _verifier_payload(
            c1,
            [{"finding_id": f_a_line42.finding_id, "verdict": "confirmed", "verifier_evidence": "A@42 确认成立"}],
        ),
        c1,
        verifier_model="claude-opus-5-5",
    )
    dec1 = evaluate_round(v1)
    e1 = dec1.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1))

    # 依次验证 3 种未在前轮锁定的跨 HEAD 坐标回复形态：行号 loc / 文件级 loc / 行内锚定 inline
    reply_cases = (
        parse_wontfix_replies(
            [{"id": 4201, "user": {"login": "alice", "type": "User"}, "body": "pilot1742/demo.py:42 不修：保留 A"}],
            allowed_authors={"alice"},
        ),
        parse_wontfix_replies(
            [{"id": 4202, "user": {"login": "alice", "type": "User"}, "body": "不修(pilot1742/demo.py)：保留 A"}],
            allowed_authors={"alice"},
        ),
        parse_wontfix_replies(
            [
                {
                    "id": 4203,
                    "path": "pilot1742/demo.py",
                    "line": 42,
                    "side": "RIGHT",
                    "user": {"login": "alice", "type": "User"},
                    "body": "不修：保留 A",
                }
            ],
            allowed_authors={"alice"},
        ),
    )

    for case_replies in reply_cases:
        assert len(case_replies) == 1
        rk = case_replies[0].reply_key

        # R2 (HEAD_2): finder 未重报 A，A 进入 stale_location_fingerprints，且本轮无 B 碰撞，核实者判 A = CONFIRMED
        plan2 = plan_next_round(BASE_SHA, HEAD_2, [e1], author_replies=case_replies)
        c2 = build_round_candidates(
            round_number=2,
            head_sha=HEAD_2,
            panel=DEFAULT_PANEL,
            finder_batches=_batches_for_panel([], round_number=2, head_sha=HEAD_2),
            history=plan2.history,
        )
        assert c2.stale_location_fingerprints == frozenset({f_a_line42.finding_id})
        assert (
            bind_author_replies(
                c2.findings,
                case_replies,
                stale_location_fingerprints=c2.stale_location_fingerprints,
            )
            == {}
        )
        v2 = parse_verifier_output(
            _verifier_payload(
                c2,
                [{"finding_id": f_a_line42.finding_id, "verdict": "confirmed", "verifier_evidence": "A 尚未修复"}],
            ),
            c2,
            verifier_model="claude-opus-5-5",
            author_replies=case_replies,
        )
        dec2 = evaluate_round(v2)
        assert dec2.outcome == RoundOutcome.BLOCKED
        assert rk in dec2.consumed_reply_keys
        assert all(k != rk for k, _ in dec2.bound_reply_targets)
        e2 = dec2.to_history_entry(rendered=render_findings_comment(1928, HEAD_2, dec2))
        assert rk in e2.consumed_reply_keys
        assert all(k != rk for k, _ in e2.bound_reply_targets)

        # 直传 evaluate_round(..., author_replies=...) 路径同样立即消费
        v2_direct = VerifiedRound(
            candidates=c2,
            verdicts=(
                _verified(
                    f_a_line42,
                    VerificationVerdict.CONFIRMED,
                    verifier_evidence="A 尚未修复",
                    round_number=2,
                    head_sha=HEAD_2,
                ),
            ),
        )
        dec2_direct = evaluate_round(v2_direct, author_replies=case_replies)
        assert rk in dec2_direct.consumed_reply_keys
        assert all(k != rk for k, _ in dec2_direct.bound_reply_targets)

        # R3 (HEAD_3): A 移位至第 50 行（不再 stale），同时第 42 行出现新发现 C；旧回复不得复活误绑 C
        plan3 = plan_next_round(BASE_SHA, HEAD_3, [e1, e2], author_replies=case_replies)
        assert rk in plan3.consumed_reply_keys
        assert plan3.author_replies == ()
        c3 = build_round_candidates(
            round_number=3,
            head_sha=HEAD_3,
            panel=DEFAULT_PANEL,
            finder_batches=_batches_for_panel([f_a_line50, f_c_line42], round_number=3, head_sha=HEAD_3),
            history=plan3.history,
        )
        assert c3.stale_location_fingerprints == frozenset()
        assert (
            bind_author_replies(
                c3.findings,
                case_replies,
                consumed_reply_keys=plan3.consumed_reply_keys,
                stale_location_fingerprints=c3.stale_location_fingerprints,
                bound_reply_targets=plan3.bound_reply_targets,
            )
            == {}
        )
        with pytest.raises(ConvergenceError):
            parse_verifier_output(
                _verifier_payload(
                    c3,
                    [
                        {"finding_id": f_a_line50.finding_id, "verdict": "confirmed", "verifier_evidence": "A@50 仍成立"},
                        {"finding_id": f_c_line42.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "试图复活旧回复解除 C"},
                    ],
                ),
                c3,
                verifier_model="claude-opus-5-5",
                author_replies=case_replies,
            )

    # 正向对照：已在 R1（同一 HEAD_1）锁定到 A 的回复，在 R2 过期期间保持锁定、永不改绑 C、并在 R3 A 清除时消费
    pinned_replies = parse_wontfix_replies(
        [{"id": 4204, "user": {"login": "alice", "type": "User"}, "body": "pilot1742/demo.py:42 不修：R1 锁定给 A"}],
        allowed_authors={"alice"},
    )
    pinned_rk = pinned_replies[0].reply_key
    v1_pinned = parse_verifier_output(
        _verifier_payload(
            c1,
            [{"finding_id": f_a_line42.finding_id, "verdict": "confirmed", "verifier_evidence": "R1 暂不采信，保留 A"}],
        ),
        c1,
        verifier_model="claude-opus-5-5",
        author_replies=pinned_replies,
    )
    dec1_pinned = evaluate_round(v1_pinned)
    assert (pinned_rk, f_a_line42.finding_id) in dec1_pinned.bound_reply_targets
    assert pinned_rk not in dec1_pinned.consumed_reply_keys
    e1_pinned = dec1_pinned.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, dec1_pinned))

    plan2_pinned = plan_next_round(BASE_SHA, HEAD_2, [e1_pinned], author_replies=pinned_replies)
    c2_pinned = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([], round_number=2, head_sha=HEAD_2),
        history=plan2_pinned.history,
    )
    v2_pinned = parse_verifier_output(
        _verifier_payload(
            c2_pinned,
            [{"finding_id": f_a_line42.finding_id, "verdict": "confirmed", "verifier_evidence": "R2 过期 A 仍成立"}],
        ),
        c2_pinned,
        verifier_model="claude-opus-5-5",
        author_replies=pinned_replies,
    )
    dec2_pinned = evaluate_round(v2_pinned)
    assert (pinned_rk, f_a_line42.finding_id) in dec2_pinned.bound_reply_targets
    assert pinned_rk not in dec2_pinned.consumed_reply_keys
    e2_pinned = dec2_pinned.to_history_entry(rendered=render_findings_comment(1928, HEAD_2, dec2_pinned))

    plan3_pinned = plan_next_round(BASE_SHA, HEAD_3, [e1_pinned, e2_pinned], author_replies=pinned_replies)
    c3_pinned = build_round_candidates(
        round_number=3,
        head_sha=HEAD_3,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_a_line50, f_c_line42], round_number=3, head_sha=HEAD_3),
        history=plan3_pinned.history,
    )
    # 锁定给 A 的回复在 R3 不得改绑同坐标新发现 C
    assert (
        bind_author_replies(
            c3_pinned.findings,
            pinned_replies,
            consumed_reply_keys=plan3_pinned.consumed_reply_keys,
            stale_location_fingerprints=c3_pinned.stale_location_fingerprints,
            bound_reply_targets=plan3_pinned.bound_reply_targets,
        )
        == {}
    )
    # A 在 R3 修复清除时，锁定给 A 的回复随之消费
    v3_pinned = parse_verifier_output(
        _verifier_payload(
            c3_pinned,
            [
                {"finding_id": f_a_line50.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "A 已修复"},
                {"finding_id": f_c_line42.finding_id, "verdict": "confirmed", "verifier_evidence": "C 阻断"},
            ],
        ),
        c3_pinned,
        verifier_model="claude-opus-5-5",
        author_replies=pinned_replies,
    )
    dec3_pinned = evaluate_round(v3_pinned)
    assert pinned_rk in dec3_pinned.consumed_reply_keys


def test_r16_gfm_pipe_table_visibility_and_wontfix_isolation() -> None:
    """R16 Important 1：完整支持 GFM §4.10 管道表格，拒绝全不可见/超列丢弃表格证据并彻底隔离表格内伪不修指令。"""
    f1 = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    fid = f1.finding_id
    cand = _candidates([f1])

    invisible_table_samples = (
        "| &#8203; |\n| --- |",
        "| &#8203; |\n| --- |\n| &#8203; | extra_dropped_cell |",
        "> | &#8203; |\n> | --- |",
        "- | &#8203; |\n  | --- |",
        "| |\n| --- |",
        "||\n| --- |",
        "| &#8203; | &#x3164; |\n| :--- | ---: |\n| <!-- hidden --> | ![alt](/x.png) |",
        "| &#8203; |\n| --- |\n| ~~&#8203;~~ |",
        "[x]: /demo\n\n| [&#8203;][x] |\n| --- |",
        "<template>\n\n| visible |\n| --- |\n\n</template>",
        "| &#8203; |\n| --- |\n    <!-- hidden --> | extra",
        "| &#8203; |\n| --- |\n| <script>alert(1)</script> |",
    )
    for bad_table in invisible_table_samples:
        with pytest.raises(ConvergenceError):
            parse_verifier_output(
                _verifier_payload(
                    cand,
                    [{"finding_id": fid, "verdict": "rejected", "verifier_evidence": bad_table}],
                ),
                cand,
                verifier_model="claude-opus-5-5",
            )
        with pytest.raises(ConvergenceError):
            VerifiedFinding(
                finding=f1,
                verdict=VerificationVerdict.REJECTED,
                verifier_model="claude-opus-5-5",
                verifier_evidence=bad_table,
                round_number=1,
                head_sha=HEAD_1,
            )
        with pytest.raises(ConvergenceError):
            _finding(failure_scenario=bad_table)
        with pytest.raises(ConvergenceError):
            _finding(evidence=bad_table)
        with pytest.raises(ConvergenceError):
            parse_finder_output(
                {
                    "findings": [
                        {
                            "severity": "Important",
                            "file": "pilot1742/demo.py",
                            "line": 42,
                            "category": "空值解引用",
                            "failure_scenario": bad_table,
                            "evidence": "真实证据",
                        }
                    ]
                },
                source_model="gpt-6-astra",
            )

    visible_table_samples = (
        "| demo.py:42 |\n| --- |",
        "说明 | 位置\n--- | ---\nA | B",
        "| &#8203; |\n| --- |\n| \\| |",
        "| &#8203; |\n| --- |\n| `&#8203;` |",
        "| &#8203; | &#8203; |\n| --- | --- |\n| x\\\\| y |",
        "| &#8203; |\n| --- |\n| x\\\\\\| |",
        "| &#8203; |\n| --- |\n| x\\|",
        "| &#8203; |\n| --- |\n    <!-- hidden -->",
        "| demo.py:42\n| ---",
        "demo.py:42 |\n--- |",
        "> | demo.py:42 |\n> | --- |",
        "- | demo.py:42 |\n  | --- |",
        "| &#8203; |\n| --- |\n\nvisible after table",
    )
    for good_table in visible_table_samples:
        vr = parse_verifier_output(
            _verifier_payload(
                cand,
                [{"finding_id": fid, "verdict": "rejected", "verifier_evidence": good_table}],
            ),
            cand,
            verifier_model="claude-opus-5-5",
        )
        assert vr.verdicts[0].verifier_evidence == good_table
        dec = evaluate_round(vr)
        assert dec.outcome == RoundOutcome.PASS
        f_ok = _finding(failure_scenario=good_table, evidence=good_table)
        assert f_ok.failure_scenario == good_table
        assert f_ok.evidence == good_table

    # 表格内全部伪不修指令均须跳过
    table_only_comments = [
        {
            "id": 9201,
            "user": {"login": "alice", "type": "User"},
            "body": "说明 | 位置\n--- | ---\ndemo.py:42 不修：示例 | A",
        },
        {
            "id": 9202,
            "user": {"login": "alice", "type": "User"},
            "body": "| 位置 | 说明 |\n| --- | --- |\n| demo.py:42 不修：表格单元格内 | A |",
        },
        {
            "id": 9203,
            "user": {"login": "alice", "type": "User"},
            "body": "| a |\n| --- |\n    demo.py:42 不修：x | y",
        },
        {
            "id": 9204,
            "user": {"login": "alice", "type": "User"},
            "body": "| a |\n| --- |\n    demo.py:42 不修：表格闭合后的4空格缩进代码",
        },
        {
            "id": 9205,
            "user": {"login": "alice", "type": "User"},
            "body": "- | a |\n  | --- |\n  | demo.py:42 不修：列表内表格 |",
        },
        {
            "id": 9206,
            "user": {"login": "alice", "type": "User"},
            "body": "> | a |\n> | --- |\n> | demo.py:42 不修：引用内表格 |",
        },
    ]
    assert parse_wontfix_replies(table_only_comments, allowed_authors={"alice"}) == ()

    # 表格闭合后的正文段落、无竖线续行及打断表格的列表项均正常解析为回复
    after_table_replies = parse_wontfix_replies(
        [
            {
                "id": 9211,
                "user": {"login": "alice", "type": "User"},
                "body": "| a |\n| --- |\n\ndemo.py:42 不修：正文理由",
            },
            {
                "id": 9212,
                "user": {"login": "alice", "type": "User"},
                "body": "| a |\n| --- |\n- demo.py:42 不修：无序列表打断表格",
            },
            {
                "id": 9213,
                "user": {"login": "alice", "type": "User"},
                "body": "| a |\n| --- |\n1. demo.py:42 不修：有序列表打断表格",
            },
            {
                "id": 9214,
                "user": {"login": "alice", "type": "User"},
                "body": "| a | b |\n| --- | --- |\ndemo.py:42 不修：无竖线立即闭合表格",
            },
        ],
        allowed_authors={"alice"},
    )
    assert [(r.comment_id, r.file, r.line, r.reason) for r in after_table_replies] == [
        ("9211", "demo.py", 42, "正文理由"),
        ("9212", "demo.py", 42, "无序列表打断表格"),
        ("9213", "demo.py", 42, "有序列表打断表格"),
        ("9214", "demo.py", 42, "无竖线立即闭合表格"),
    ]


def test_r16_indented_code_preserves_leading_indent_across_all_markdown_entries() -> None:
    """R16 Important 2：保留 4 空格/Tab 缩进代码前导缩进，三个 Markdown 入口全链路放行合法缩进代码并拒绝 3/0 空格注释与真不可见字符。"""
    valid_indented_samples = (
        "    <!-- hidden -->",
        "\t<!-- hidden -->",
        "    &#x3164;",
        "\t&#x3164;",
        "    <span></span>",
    )
    for good_code in valid_indented_samples:
        # 1. parse_finder_output -> Finding -> merge_and_dedupe_findings -> build_round_candidates
        parsed_findings = parse_finder_output(
            {
                "findings": [
                    {
                        "severity": "Important",
                        "file": "pilot1742/demo.py",
                        "line": 42,
                        "category": "缩进代码证据",
                        "failure_scenario": good_code,
                        "evidence": good_code,
                    }
                ]
            },
            source_model="gpt-6-astra",
        )
        assert len(parsed_findings) == 1
        assert parsed_findings[0].failure_scenario == good_code
        assert parsed_findings[0].evidence == good_code

        c_round = build_round_candidates(
            round_number=1,
            head_sha=HEAD_1,
            panel=DEFAULT_PANEL,
            finder_batches=_batches_for_panel(list(parsed_findings), round_number=1, head_sha=HEAD_1),
        )
        assert c_round.findings[0].failure_scenario == good_code
        assert c_round.findings[0].evidence == good_code
        fid = c_round.findings[0].finding_id

        # 2. parse_verifier_output -> VerifiedFinding -> evaluate_round -> render_findings_comment -> to_history_entry
        vr_confirmed = parse_verifier_output(
            _verifier_payload(
                c_round,
                [{"finding_id": fid, "verdict": "confirmed", "verifier_evidence": good_code}],
            ),
            c_round,
            verifier_model="claude-opus-5-5",
        )
        assert vr_confirmed.verdicts[0].verifier_evidence == good_code
        dec_blocked = evaluate_round(vr_confirmed)
        assert dec_blocked.outcome == RoundOutcome.BLOCKED
        rendered = render_findings_comment(1928, HEAD_1, dec_blocked)
        assert parse_comment_marker(rendered.body) == (1928, 1, HEAD_1)
        assert good_code in rendered.body
        rendered_blocks, _ = _parse_commonmark_blocks(rendered.body, include_all_visible_blocks=True)
        expected_literal = good_code.lstrip(" \t")
        code_blocks = [txt for kind, txt in rendered_blocks if kind == "code"]
        assert code_blocks.count(expected_literal) == 2
        assert _has_visible_gfm_text(rendered.body)
        hist_entry = dec_blocked.to_history_entry(rendered=rendered)
        assert fid in hist_entry.posted_fingerprints

        vr_rejected = parse_verifier_output(
            _verifier_payload(
                c_round,
                [{"finding_id": fid, "verdict": "rejected", "verifier_evidence": good_code}],
            ),
            c_round,
            verifier_model="claude-opus-5-5",
        )
        assert vr_rejected.verdicts[0].verifier_evidence == good_code
        dec_pass = evaluate_round(vr_rejected)
        assert dec_pass.outcome == RoundOutcome.PASS
        rendered_pass = render_findings_comment(1928, HEAD_1, dec_pass)
        pass_blocks, _ = _parse_commonmark_blocks(rendered_pass.body, include_all_visible_blocks=True)
        pass_code_blocks = [txt for kind, txt in pass_blocks if kind == "code"]
        assert pass_code_blocks.count(expected_literal) == 1
        assert _has_visible_gfm_text(rendered_pass.body)

    f_base = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    cand_base = _candidates([f_base])
    rejected_samples = (
        "   <!-- hidden -->",
        "<!-- hidden -->",
        "    \u3164",
        "\t\u3164",
        "   &#x3164;",
    )
    for bad_md in rejected_samples:
        with pytest.raises(ConvergenceError):
            _finding(failure_scenario=bad_md)
        with pytest.raises(ConvergenceError):
            _finding(evidence=bad_md)
        with pytest.raises(ConvergenceError):
            parse_finder_output(
                {
                    "findings": [
                        {
                            "severity": "Important",
                            "file": "pilot1742/demo.py",
                            "line": 42,
                            "category": "空值解引用",
                            "failure_scenario": bad_md,
                            "evidence": "真实证据",
                        }
                    ]
                },
                source_model="gpt-6-astra",
            )
        with pytest.raises(ConvergenceError):
            parse_finder_output(
                {
                    "findings": [
                        {
                            "severity": "Important",
                            "file": "pilot1742/demo.py",
                            "line": 42,
                            "category": "空值解引用",
                            "failure_scenario": "真实场景",
                            "evidence": bad_md,
                        }
                    ]
                },
                source_model="gpt-6-astra",
            )
        with pytest.raises(ConvergenceError):
            VerifiedFinding(
                finding=f_base,
                verdict=VerificationVerdict.REJECTED,
                verifier_model="claude-opus-5-5",
                verifier_evidence=bad_md,
                round_number=1,
                head_sha=HEAD_1,
            )
        with pytest.raises(ConvergenceError):
            parse_verifier_output(
                _verifier_payload(
                    cand_base,
                    [{"finding_id": f_base.finding_id, "verdict": "rejected", "verifier_evidence": bad_md}],
                ),
                cand_base,
                verifier_model="claude-opus-5-5",
            )


def test_r17_gfm_table_escape_continuation_and_comment_visibility() -> None:
    """R17 回归：覆盖反斜杠紧邻竖线转义、无未转义竖线即闭合表格，以及评论全路径缩进代码可读性保全。"""
    # --- Important 1: GFM 表格紧邻前字符 `\` 转义判定 ---
    escaped_pipe_table_comments = [
        {
            "id": 9701,
            "user": {"login": "alice", "type": "User"},
            "body": "a\\|b | c\n--- | ---\ndemo.py:42 不修：表内示例 | A",
        },
        {
            "id": 9702,
            "user": {"login": "alice", "type": "User"},
            "body": "a\\\\|b | c\n--- | ---\ndemo.py:42 不修：表内示例 | A",
        },
        {
            "id": 9703,
            "user": {"login": "alice", "type": "User"},
            "body": "a\\\\\\|b | c\n--- | ---\ndemo.py:42 不修：表内示例 | A",
        },
        {
            "id": 9704,
            "user": {"login": "alice", "type": "User"},
            "body": "a\\\\\\\\|b | c\n--- | ---\ndemo.py:42 不修：表内示例 | A",
        },
        {
            "id": 9705,
            "user": {"login": "alice", "type": "User"},
            "body": "| a\\\\|\n| --- |\n| demo.py:42 不修：末尾转义竖线单列表 |",
        },
    ]
    assert parse_wontfix_replies(escaped_pipe_table_comments, allowed_authors={"alice"}) == ()

    f_probe = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=42)
    cand_probe = _candidates([f_probe])
    # 1 列表格内 `\\|` 仍被转义，不会误切成 2 列而丢弃可见文本
    for ev in (
        "| &#8203; |\n| --- |\n| &#8203;\\\\| visible |",
        "| &#8203; |\n| --- |\n| a\\\\|",
    ):
        vr = parse_verifier_output(
            _verifier_payload(cand_probe, [{"finding_id": f_probe.finding_id, "verdict": "rejected", "verifier_evidence": ev}]),
            cand_probe,
            verifier_model="claude-opus-5-5",
        )
        assert vr.verdicts[0].verifier_evidence == ev

    # --- Important 2: 含未转义 `|` 才续接表体，无 `|` 立即闭合表格 ---
    cont_replies = parse_wontfix_replies(
        [
            {
                "id": 9711,
                "user": {"login": "alice", "type": "User"},
                "body": "| &#8203; |\n| --- |\n2. demo.py:42 不修：保留旧接口",
            },
            {
                "id": 9712,
                "user": {"login": "alice", "type": "User"},
                "body": "| a |\n| --- |\ndemo.py:42 不修：仅含转义竖线 a\\|b",
            },
            {
                "id": 9713,
                "user": {"login": "alice", "type": "User"},
                "body": "| a |\n| --- |\ndemo.py:42 不修：无竖线普通段落",
            },
        ],
        allowed_authors={"alice"},
    )
    assert [(r.comment_id, r.file, r.line, r.reason) for r in cont_replies] == [
        ("9711", "demo.py", 42, "保留旧接口"),
        ("9712", "demo.py", 42, "仅含转义竖线 a|b"),
        ("9713", "demo.py", 42, "无竖线普通段落"),
    ]

    still_in_table_comments = [
        {
            "id": 9721,
            "user": {"login": "alice", "type": "User"},
            "body": "| a |\n| --- |\n    demo.py:42 不修：x | y",
        },
        {
            "id": 9722,
            "user": {"login": "alice", "type": "User"},
            "body": "| a |\n| --- |\n2. demo.py:42 不修：x | y",
        },
        {
            "id": 9723,
            "user": {"login": "alice", "type": "User"},
            "body": "| a |\n| --- |\n- demo.py:42 不修：x | y",
        },
        {
            "id": 9724,
            "user": {"login": "alice", "type": "User"},
            "body": "| a |\n| --- |\n> demo.py:42 不修：x | y",
        },
        {
            "id": 9725,
            "user": {"login": "alice", "type": "User"},
            "body": "| a |\n| --- |\n# demo.py:42 不修：x | y",
        },
    ]
    assert parse_wontfix_replies(still_in_table_comments, allowed_authors={"alice"}) == ()

    # 表格后无 `|` 缩进代码块闭合表格并成为可见代码块；含未转义 `|` 留在表体行则第 2 列丢弃、整段不可见
    vr_table_code = parse_verifier_output(
        _verifier_payload(
            cand_probe,
            [{"finding_id": f_probe.finding_id, "verdict": "rejected", "verifier_evidence": "| &#8203; |\n| --- |\n    <!-- hidden -->"}],
        ),
        cand_probe,
        verifier_model="claude-opus-5-5",
    )
    assert vr_table_code.verdicts[0].verifier_evidence == "| &#8203; |\n| --- |\n    <!-- hidden -->"
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            _verifier_payload(
                cand_probe,
                [{"finding_id": f_probe.finding_id, "verdict": "rejected", "verifier_evidence": "| &#8203; |\n| --- |\n    <!-- hidden --> | extra"}],
            ),
            cand_probe,
            verifier_model="claude-opus-5-5",
        )

    # --- Important 3: render_findings_comment 全路径保全缩进代码与块级可见性 ---
    indented_cases = (
        ("    <!-- hidden -->", "<!-- hidden -->"),
        ("\t<!-- hidden -->", "<!-- hidden -->"),
        ("    &#x3164;", "&#x3164;"),
        ("\t&#x3164;", "&#x3164;"),
        ("    <span></span>", "<span></span>"),
    )
    for raw_code, literal in indented_cases:
        f_imp = _finding(
            severity=Severity.IMPORTANT,
            file="pilot1742/demo.py",
            line=42,
            category="阻断缩进",
            failure_scenario=raw_code,
            evidence=raw_code,
        )
        f_nit = _finding(
            severity=Severity.NIT,
            file="pilot1742/demo.py",
            line=50,
            category="非阻断缩进",
            failure_scenario=raw_code,
            evidence=raw_code,
        )
        f_fix = _finding(
            severity=Severity.IMPORTANT,
            file="pilot1742/demo.py",
            line=60,
            category="已修复项",
            failure_scenario="修复前触发异常",
            evidence="修复前堆栈",
        )
        f_rej = _finding(
            severity=Severity.IMPORTANT,
            file="pilot1742/demo.py",
            line=70,
            category="核实驳回项",
            failure_scenario="疑似空值",
            evidence="疑似路径",
        )
        # R1 先产生 f_fix 阻断项，再进 R2 验证 resolved_by_fix 与 rejected/confirmed/nit 的完整评论渲染
        c_r1 = build_round_candidates(
            round_number=1,
            head_sha=HEAD_1,
            panel=DEFAULT_PANEL,
            finder_batches=_batches_for_panel([f_fix], round_number=1, head_sha=HEAD_1),
        )
        v_r1 = parse_verifier_output(
            _verifier_payload(c_r1, [{"finding_id": f_fix.finding_id, "verdict": "confirmed", "verifier_evidence": "R1 确证"}]),
            c_r1,
            verifier_model="claude-opus-5-5",
        )
        d_r1 = evaluate_round(v_r1)
        e_r1 = d_r1.to_history_entry(rendered=render_findings_comment(1928, HEAD_1, d_r1))
        plan_r2 = plan_next_round(BASE_SHA, HEAD_2, [e_r1])
        cand_all = build_round_candidates(
            round_number=2,
            head_sha=HEAD_2,
            panel=DEFAULT_PANEL,
            finder_batches=_batches_for_panel([f_imp, f_nit, f_rej], round_number=2, head_sha=HEAD_2),
            history=plan_r2.history,
        )
        vr_all = parse_verifier_output(
            _verifier_payload(
                cand_all,
                [
                    {"finding_id": f_imp.finding_id, "verdict": "confirmed", "verifier_evidence": raw_code},
                    {"finding_id": f_nit.finding_id, "verdict": "confirmed", "verifier_evidence": raw_code},
                    {"finding_id": f_fix.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": raw_code},
                    {"finding_id": f_rej.finding_id, "verdict": "rejected", "verifier_evidence": raw_code},
                ],
            ),
            cand_all,
            verifier_model="claude-opus-5-5",
        )
        dec_all = evaluate_round(vr_all)

        # 1) 全量渲染：阻断项、非阻断项与已解除/驳回摘要均保留嵌套缩进代码块
        full_rendered = render_findings_comment(1928, HEAD_2, dec_all)
        assert not full_rendered.truncated
        full_blocks, _ = _parse_commonmark_blocks(full_rendered.body, include_all_visible_blocks=True)
        code_block_texts = [txt.strip("\n") for kind, txt in full_blocks if kind == "code"]
        # f_imp (失败场景+核实证据) + f_nit (失败场景+核实证据) + f_fix (已修复) + f_rej (核实驳回) = 6 个嵌套缩进代码块
        assert code_block_texts.count(literal) == 6
        assert "已修复：\n\n" in full_rendered.body
        assert "核实驳回：\n\n" in full_rendered.body
        assert _has_visible_gfm_text(full_rendered.body)

        # 2) 非阻断项紧凑降级渲染（预算容得下完整阻断项，但逼迫非阻断项降级为紧凑单行）
        f_nit_long = _finding(
            severity=Severity.NIT,
            file="pilot1742/demo.py",
            line=51,
            category="超长非阻断",
            failure_scenario=raw_code,
            evidence=raw_code,
            class_scope="同类范围：" + ("X" * 300),
        )
        cand_nb_compact = _candidates([f_imp, f_nit_long])
        vr_nb_compact = parse_verifier_output(
            _verifier_payload(
                cand_nb_compact,
                [
                    {"finding_id": f_imp.finding_id, "verdict": "confirmed", "verifier_evidence": raw_code},
                    {"finding_id": f_nit_long.finding_id, "verdict": "confirmed", "verifier_evidence": raw_code},
                ],
            ),
            cand_nb_compact,
            verifier_model="claude-opus-5-5",
        )
        dec_nb_compact = evaluate_round(vr_nb_compact)
        full_nb_len = len(render_findings_comment(1928, HEAD_1, dec_nb_compact).body)
        compact_nb_rendered = render_findings_comment(1928, HEAD_1, dec_nb_compact, max_chars=full_nb_len - 80)
        assert compact_nb_rendered.truncated
        assert f_nit_long.finding_id in compact_nb_rendered.posted_fingerprints
        assert f"超长非阻断：`{literal}`" in compact_nb_rendered.body
        assert f"（核实证据：`{literal}`）" in compact_nb_rendered.body

        # 3) 阻断项紧凑降级与极紧预算截断（_render_compact_new_blocking_item & _render_blocking_section_with_budget）
        cand_imp_only = _candidates([f_imp])
        vr_imp_only = parse_verifier_output(
            _verifier_payload(
                cand_imp_only,
                [{"finding_id": f_imp.finding_id, "verdict": "confirmed", "verifier_evidence": raw_code}],
            ),
            cand_imp_only,
            verifier_model="claude-opus-5-5",
        )
        dec_imp_only = evaluate_round(vr_imp_only)
        full_imp_len = len(render_findings_comment(1928, HEAD_1, dec_imp_only).body)
        # 触发紧凑单行阻断渲染
        compact_imp_rendered = render_findings_comment(1928, HEAD_1, dec_imp_only, max_chars=full_imp_len - 10)
        assert compact_imp_rendered.truncated
        assert f"阻断缩进：`{literal}`" in compact_imp_rendered.body
        # 触发极紧预算截断分支（比紧凑版再短，测试反引号截断仍保持闭合）
        tight_budget = len(compact_imp_rendered.body) - 25
        tight_imp_rendered = render_findings_comment(1928, HEAD_1, dec_imp_only, max_chars=tight_budget)
        assert tight_imp_rendered.truncated
        assert len(tight_imp_rendered.body) <= tight_budget
        # 确认无孤立未闭合反引号：每行反引号数均为偶数
        for rendered_line in tight_imp_rendered.body.split("\n"):
            assert rendered_line.count("`") % 2 == 0

    # 含反引号的缩进代码在摘要路径保留嵌套代码块，在紧凑行内路径按 CommonMark §6.1 使用双反引号包裹
    backtick_code = "    `<!-- inner -->`"
    f_bt = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=88,
        category="反引号缩进",
        failure_scenario=backtick_code,
        evidence=backtick_code,
    )
    cand_bt = _candidates([f_bt])
    vr_bt = parse_verifier_output(
        _verifier_payload(cand_bt, [{"finding_id": f_bt.finding_id, "verdict": "rejected", "verifier_evidence": backtick_code}]),
        cand_bt,
        verifier_model="claude-opus-5-5",
    )
    rendered_bt = render_findings_comment(1928, HEAD_1, evaluate_round(vr_bt))
    bt_blocks, _ = _parse_commonmark_blocks(rendered_bt.body, include_all_visible_blocks=True)
    assert [txt.strip("\n") for kind, txt in bt_blocks if kind == "code"] == ["`<!-- inner -->`"]
    assert _format_inline_markdown_field(backtick_code) == "`` `<!-- inner -->` ``"


def test_r18_inline_clip_keeps_embedded_code_closed_and_safe() -> None:
    """R18 Important 1：混合文本中嵌入式行内代码截断必须保持反引号闭合且不得泄漏未闭合 HTML 抑制态。"""
    # 1. Codex R16 最小复现：failure:\n\n    <!-- hidden --> + 'x'*80 在 max_chars=259 下截断
    mixed_scenario = "failure:\n\n    <!-- hidden -->" + ("x" * 80)
    f_mixed = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="bug",
        failure_scenario=mixed_scenario,
        evidence=mixed_scenario,
    )
    cand_mixed = _candidates([f_mixed])
    vr_mixed = parse_verifier_output(
        _verifier_payload(cand_mixed, [{"finding_id": f_mixed.finding_id, "verdict": "confirmed", "verifier_evidence": mixed_scenario}]),
        cand_mixed,
        verifier_model="claude-opus-5-5",
    )
    dec_mixed = evaluate_round(vr_mixed)
    rendered_259 = render_findings_comment(1928, HEAD_1, dec_mixed, max_chars=259)
    assert rendered_259.truncated
    assert len(rendered_259.body) <= 259
    assert "failure: `<!-- hidden -->" in rendered_259.body
    assert not _leaves_html_suppressed(rendered_259.body)
    for line in rendered_259.body.split("\n"):
        if f"[{f_mixed.finding_id}]" in line:
            assert line.count("`") % 2 == 0
            assert "failure:" in line
            assert "`<!-- hidden -->" in line
            assert line.endswith("…`")

    # 2. 遍历极紧预算：无论截断点落在代码片段前/中/极窄余量，绝不产生孤立反引号或未闭合 HTML
    for budget in range(215, 290, 3):
        rendered_b = render_findings_comment(1928, HEAD_1, dec_mixed, max_chars=budget)
        assert len(rendered_b.body) <= budget
        assert not _leaves_html_suppressed(rendered_b.body)
        for line in rendered_b.body.split("\n"):
            assert line.count("`") % 2 == 0

    # 3. _clip_formatted_inline 单元测试：开头/中段/多段/双反引号代码与普通文本 HTML 注释/script 回退
    mixed_fmt = f"failure: `<!-- hidden -->{'x' * 80}`"
    clipped_mid = _clip_formatted_inline(mixed_fmt, 34)
    assert len(clipped_mid) <= 34
    assert clipped_mid.startswith("failure: `<!-- hidden -->")
    assert clipped_mid.endswith("…`")
    assert clipped_mid.count("`") == 2

    # 剩余预算不足以容纳闭合代码片段（仅余 3 字符）时，丢弃半截代码片段仅保留前缀加省略号
    clipped_tiny_rem = _clip_formatted_inline(mixed_fmt, 12)
    assert clipped_tiny_rem == "failure:…"
    assert len(clipped_tiny_rem) <= 12

    # 嵌入双反引号代码片段在预算内保持双反引号闭合
    double_bt_fmt = f"msg: `` `<!-- hidden -->`{'y' * 40} ``"
    clipped_dbt = _clip_formatted_inline(double_bt_fmt, 34)
    assert len(clipped_dbt) <= 34
    assert clipped_dbt.startswith("msg: `` `<!-- hidden -->")
    assert clipped_dbt.endswith("… ``")

    # 截断点落在普通文本内嵌 HTML 注释或 <script> 区间时，绝不泄漏未闭合抑制态
    clipped_comment = _clip_formatted_inline("visible <!-- secret long note --> tail", 18)
    assert len(clipped_comment) <= 18
    assert clipped_comment == "visible…"
    assert not _leaves_html_suppressed(clipped_comment)

    clipped_script = _clip_formatted_inline("ok <script>1234567890</script> end", 20)
    assert len(clipped_script) <= 20
    assert clipped_script == "ok…"
    assert not _leaves_html_suppressed(clipped_script)

    # 非阻断紧凑降级路径同样保持混合文本嵌入式代码闭合，不隐藏结尾括号
    f_nb = _finding(
        severity=Severity.NIT,
        file="pilot1742/demo.py",
        line=55,
        category="nit-bug",
        failure_scenario=mixed_scenario,
        evidence=mixed_scenario,
        class_scope="X" * 300,
    )
    f_blk = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=10, category="blk")
    cand_nb = _candidates([f_blk, f_nb])
    vr_nb = parse_verifier_output(
        _verifier_payload(
            cand_nb,
            [
                {"finding_id": f_blk.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"},
                {"finding_id": f_nb.finding_id, "verdict": "confirmed", "verifier_evidence": mixed_scenario},
            ],
        ),
        cand_nb,
        verifier_model="claude-opus-5-5",
    )
    dec_nb = evaluate_round(vr_nb)
    full_nb_len = len(render_findings_comment(1928, HEAD_1, dec_nb).body)
    compact_nb = render_findings_comment(1928, HEAD_1, dec_nb, max_chars=full_nb_len - 180)
    assert compact_nb.truncated
    assert f_nb.finding_id in compact_nb.posted_fingerprints
    assert not _leaves_html_suppressed(compact_nb.body)
    for line in compact_nb.body.split("\n"):
        assert line.count("`") % 2 == 0


def test_r18_unclosed_html_suppression_isolated_in_fenced_blocks_and_replies() -> None:
    """R18 Important 2：未闭合 HTML 注释/声明/处理指令/CDATA/静默标签/开标签一律隔离进围栏代码块，绝不吞噬后续字段与发现。"""
    suppressed_samples = (
        "okay\n\n<!--",
        "okay <!--",
        "okay\n\n<script>",
        "okay <script>",
        "okay\n\n<style>",
        "okay\n\n<textarea>",
        "okay\n\n<title>",
        "okay\n\n<template>",
        "okay\n\n<noscript>",
        "okay\n\n<?php",
        "okay\n\n<!DOCTYPE",
        "okay\n\n<![CDATA[",
        'okay\n\n<div a="x',
        'okay <div a="x',
        "```\nokay\n```\n\n<!--",
    )
    for sample in suppressed_samples:
        assert _leaves_html_suppressed(sample), f"应识别未闭合 HTML 抑制态：{sample!r}"

    # 正常闭合 HTML、缩进代码块与围栏代码块内注释不应误判为遗留抑制态
    assert not _leaves_html_suppressed("okay\n\n<!-- closed -->")
    assert not _leaves_html_suppressed("okay <script>x</script>")
    assert not _leaves_html_suppressed("    <!-- hidden -->")
    assert not _leaves_html_suppressed("okay\n```\n<!--")
    assert not _leaves_html_suppressed("已核实无问题")

    # 内含 ``` 时自动升级为 4 反引号围栏
    fenced_4 = _format_nested_fenced_code("```\nokay\n```\n\n<!--", content_indent="    ")
    assert fenced_4.startswith("    ````\n")
    assert fenced_4.endswith("\n    ````")

    # Codex R16 最小复现 + 后续发现共存：第一条发现含未闭合 <!-- / <script> / <style>，绝不吞掉核实证据、处置与第二条发现
    for payload in ("okay\n\n<!--", "okay <!--", "okay\n\n<script>", "okay\n\n<style>", "okay\n\n<title>"):
        f1 = _finding(
            severity=Severity.IMPORTANT,
            file="pilot1742/demo.py",
            line=42,
            category="bug1",
            failure_scenario=payload,
            evidence=payload,
        )
        f2 = _finding(
            severity=Severity.IMPORTANT,
            file="pilot1742/demo.py",
            line=99,
            category="bug2",
            failure_scenario="第二条发现必须完整可见",
            evidence="第二条核实证据",
        )
        cand = _candidates([f1, f2])
        vr = parse_verifier_output(
            _verifier_payload(
                cand,
                [
                    {"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": payload},
                    {"finding_id": f2.finding_id, "verdict": "confirmed", "verifier_evidence": "第二条核实证据"},
                ],
            ),
            cand,
            verifier_model="claude-opus-5-5",
        )
        rendered = render_findings_comment(1928, HEAD_1, evaluate_round(vr))
        assert not _leaves_html_suppressed(rendered.body)
        assert "  - 失败场景：\n\n    ```" in rendered.body
        assert "  - 核实证据：\n\n    ```" in rendered.body
        assert f"  - 处置：请在新提交中修复，或回复 `[{f1.finding_id}] 不修：<理由>`" in rendered.body
        assert "第二条发现必须完整可见" in rendered.body
        assert "第二条核实证据" in rendered.body

    # 作者不修理由含未闭合 <!-- 时必须经 _format_inline_markdown_field 安全包裹，防止吞噬后续 --> 证据
    f_wf = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=77, category="wontfix-html")
    cand_wf = _candidates([f_wf])
    reply_unclosed = AuthorReply(
        comment_id="c-r18-html",
        author="alice",
        finding_id=f_wf.finding_id,
        file=None,
        line=None,
        reason="okay <!--",
    )
    vr_wf = parse_verifier_output(
        _verifier_payload(
            cand_wf,
            [{"finding_id": f_wf.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "accepted -->"}],
        ),
        cand_wf,
        verifier_model="claude-opus-5-5",
        author_replies=[reply_unclosed],
    )
    rendered_wf = render_findings_comment(1928, HEAD_1, evaluate_round(vr_wf))
    assert "（理由：`okay <!--`）：accepted -->" in rendered_wf.body
    assert not _leaves_html_suppressed(rendered_wf.body)


def test_r18_preserves_code_literal_double_spaces_and_disposition_nested_blocks() -> None:
    """R18 Important 3：保留代码字面量内部双空格，且 disposition_lines 对缩进/块级/未闭合 HTML 证据复用嵌套块渲染。"""
    double_space_code = '    assert "a  b" != "a b"'
    expected_code = 'assert "a  b" != "a b"'

    # 1. _format_inline_markdown_field 对 code 块不折叠内部连续空格（无论 collapse_whitespace 真假）
    assert _format_inline_markdown_field(double_space_code) == f"`{expected_code}`"
    assert _format_inline_markdown_field(double_space_code, collapse_whitespace=True) == f"`{expected_code}`"

    # 2. Codex R16 最小复现：verdict="rejected" + 缩进断言代码在 disposition_lines 渲染为 2 空格缩进嵌套代码块
    f_rej = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="assertion",
        failure_scenario="双空格断言",
        evidence=double_space_code,
    )
    f_plain = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=43,
        category="plain",
        failure_scenario="普通单行",
        evidence="普通证据",
    )
    cand = _candidates([f_rej, f_plain])
    vr = parse_verifier_output(
        _verifier_payload(
            cand,
            [
                {"finding_id": f_rej.finding_id, "verdict": "rejected", "verifier_evidence": double_space_code},
                {"finding_id": f_plain.finding_id, "verdict": "rejected", "verifier_evidence": "已核实无问题"},
            ],
        ),
        cand,
        verifier_model="claude-opus-5-5",
    )
    rendered = render_findings_comment(1928, HEAD_1, evaluate_round(vr))
    assert not rendered.truncated
    # 缩进代码证据输出为 `- ` 列表项下的 2 空格缩进嵌套块（2 + 4 = 6 空格），双空格原样保留
    assert f"- `[{f_rej.finding_id}]` `pilot1742/demo.py:42` — 核实驳回：\n\n      {expected_code}" in rendered.body
    # 普通单行安全文本保持原单行格式（100% 兼容既有单测）
    assert f"- `[{f_plain.finding_id}]` `pilot1742/demo.py:43` — 核实驳回：已核实无问题" in rendered.body
    blocks, _ = _parse_commonmark_blocks(rendered.body, include_all_visible_blocks=True)
    code_blocks = [txt for kind, txt in blocks if kind == "code"]
    assert expected_code in code_blocks

    # 3. disposition_lines 对 Tab 缩进代码与未闭合 HTML 同样安全嵌套（Tab 在 2 空格缩进下按 CommonMark 4 列对齐展开）
    f_tab = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=44, category="tab-code")
    f_html = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=45, category="unclosed-html")
    cand2 = _candidates([f_tab, f_html])
    vr2 = parse_verifier_output(
        _verifier_payload(
            cand2,
            [
                {"finding_id": f_tab.finding_id, "verdict": "rejected", "verifier_evidence": "\t<!-- hidden -->"},
                {"finding_id": f_html.finding_id, "verdict": "rejected", "verifier_evidence": "okay\n\n<!--"},
            ],
        ),
        cand2,
        verifier_model="claude-opus-5-5",
    )
    rendered2 = render_findings_comment(1928, HEAD_1, evaluate_round(vr2))
    assert not _leaves_html_suppressed(rendered2.body)
    blocks2, _ = _parse_commonmark_blocks(rendered2.body, include_all_visible_blocks=True)
    code_blocks2 = [txt for kind, txt in blocks2 if kind == "code"]
    assert "<!-- hidden -->" in code_blocks2
    assert "okay\n\n<!--" in code_blocks2

    # 4. 紧凑非阻断降级路径中缩进代码字面量同样保留双空格
    f_nb_ds = _finding(
        severity=Severity.NIT,
        file="pilot1742/demo.py",
        line=60,
        category="ds-nit",
        failure_scenario=double_space_code,
        evidence=double_space_code,
        class_scope="Y" * 300,
    )
    f_blk_ds = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=11, category="ds-blk")
    cand_ds = _candidates([f_blk_ds, f_nb_ds])
    vr_ds = parse_verifier_output(
        _verifier_payload(
            cand_ds,
            [
                {"finding_id": f_blk_ds.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"},
                {"finding_id": f_nb_ds.finding_id, "verdict": "confirmed", "verifier_evidence": double_space_code},
            ],
        ),
        cand_ds,
        verifier_model="claude-opus-5-5",
    )
    dec_ds = evaluate_round(vr_ds)
    full_ds_len = len(render_findings_comment(1928, HEAD_1, dec_ds).body)
    compact_ds = render_findings_comment(1928, HEAD_1, dec_ds, max_chars=full_ds_len - 80)
    assert compact_ds.truncated
    assert f"`{expected_code}`" in compact_ds.body


def test_r19_unmatched_backticks_escaped_before_code_span_join_and_clip() -> None:
    """R19 Important 1：混合文本转单行拼接与截断时转义普通段裸未配对反引号，防止吞掉相邻代码段并严禁切裂转义反斜杠。"""
    assert _escape_unmatched_backticks("found `") == r"found \`"
    assert _escape_unmatched_backticks("found ``") == r"found \`\`"
    assert _escape_unmatched_backticks(r"found \`") == r"found \`"
    assert _escape_unmatched_backticks("found \\\\`") == r"found \\\`"
    assert _escape_unmatched_backticks("ok `a` and `") == r"ok `a` and \`"
    assert _escape_unmatched_backticks("see <https://example.com> and `x`") == "see <https://example.com> and `x`"

    # 1. Codex R17 最小复现：found `\n\n    <!-- hidden --> + 'x'*80 在 max_chars=259 下渲染
    s_repro = "found `\n\n    <!-- hidden -->" + ("x" * 80)
    formatted = _format_inline_markdown_field(s_repro)
    assert formatted.startswith(r"found \` `<!-- hidden -->")
    assert not _contains_raw_html_outside_code(formatted)

    f_repro = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="bug",
        failure_scenario=s_repro,
        evidence=s_repro,
    )
    cand = _candidates([f_repro])
    vr = parse_verifier_output(
        _verifier_payload(cand, [{"finding_id": f_repro.finding_id, "verdict": "confirmed", "verifier_evidence": s_repro}]),
        cand,
        verifier_model="claude-opus-5-5",
    )
    dec = evaluate_round(vr)
    rendered_259 = render_findings_comment(1928, HEAD_1, dec, max_chars=259)
    assert rendered_259.truncated
    assert len(rendered_259.body) <= 259
    assert r"found \` `<!-- hidden -->" in rendered_259.body
    assert not _leaves_html_suppressed(rendered_259.body)
    finding_lines = [ln for ln in rendered_259.body.split("\n") if f"[{f_repro.finding_id}]" in ln]
    assert len(finding_lines) == 1
    assert not _contains_raw_html_outside_code(finding_lines[0])
    assert finding_lines[0].endswith("…`")

    # 2. 遍历极紧预算：任意截断点既不暴露代码外原始 HTML，也不把 \` 切剩孤立反斜杠 \…
    for budget in range(215, 310, 2):
        rendered_b = render_findings_comment(1928, HEAD_1, dec, max_chars=budget)
        assert len(rendered_b.body) <= budget
        assert not _leaves_html_suppressed(rendered_b.body)
        for ln in rendered_b.body.split("\n"):
            if f"[{f_repro.finding_id}]" in ln:
                assert not _contains_raw_html_outside_code(ln)
                assert not ln.endswith("\\…")

    # 3. _clip_formatted_inline 在转义反引号 \` 正中间截断时必须退回完整词边界，不遗留半个反斜杠
    assert _clip_formatted_inline(formatted, 8) == "found…"
    assert _clip_formatted_inline(formatted, 9) == r"found \`…"
    for limit in range(4, 36):
        clipped = _clip_formatted_inline(formatted, limit)
        assert len(clipped) <= limit
        assert not clipped.endswith("\\…")
        if clipped:
            assert not _contains_raw_html_outside_code(clipped)

    # 4. 多段含未配对反引号 + 行内代码段，以及 category 含未配对反引号时均不吞噬后续代码段
    multi_para = "found `\n\nsee `<!-- hidden -->`"
    assert _format_inline_markdown_field(multi_para) == r"found \` see `<!-- hidden -->`"
    assert not _contains_raw_html_outside_code(_format_inline_markdown_field(multi_para))

    f_cat_bt = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=43,
        category="bug `",
        failure_scenario="    <!-- hidden -->",
        evidence="    <!-- hidden -->",
    )
    cand_cb = _candidates([f_cat_bt])
    vr_cb = parse_verifier_output(
        _verifier_payload(cand_cb, [{"finding_id": f_cat_bt.finding_id, "verdict": "confirmed", "verifier_evidence": "    <!-- hidden -->"}]),
        cand_cb,
        verifier_model="claude-opus-5-5",
    )
    dec_cb = evaluate_round(vr_cb)
    full_cb = len(render_findings_comment(1928, HEAD_1, dec_cb).body)
    compact_cb = render_findings_comment(1928, HEAD_1, dec_cb, max_chars=full_cb - 10)
    assert r"bug \`：`<!-- hidden -->`" in compact_cb.body
    for ln in compact_cb.body.split("\n"):
        if f"[{f_cat_bt.finding_id}]" in ln:
            assert not _contains_raw_html_outside_code(ln)


def test_r19_raw_html_outside_code_isolated_in_findings_and_wontfix_replies() -> None:
    """R19 Important 2：对字段中任何代码外原始 HTML（含 <head>/<iframe>/<div hidden> 等）一律安全隔离，且不误伤正常行内代码与自动链接。"""
    # 1. <head> 纳入 HTML5 静默容器识别，同时合法 <div>real text</div> 仍通过可见性校验
    assert not _has_visible_gfm_text("<head>hidden</head>")
    assert _has_visible_gfm_text("okay <head>")
    assert _leaves_html_suppressed("okay <head>")
    assert _has_visible_gfm_text("<div>real text</div>")

    # 2. _contains_raw_html_outside_code 精准区分代码外原始 HTML 与正常 Markdown 对照样本
    raw_html_samples = (
        "okay <head>",
        "okay <iframe>",
        "okay <details>",
        "okay <div hidden>",
        'okay <span style="display:none">hidden</span>',
        "okay <!-- note -->",
        "okay <?xml",
        "okay <!DOCTYPE html>",
        "okay </p>",
        "<div>real text</div>",
        "# <head>",
    )
    for sample in raw_html_samples:
        assert _contains_raw_html_outside_code(sample), f"应识别代码外原始 HTML：{sample!r}"

    safe_controls = (
        "Run `<span>` and `<!-- hidden -->`",
        "See <https://example.com> and <user@example.com>",
        "Check a < b and x < 1 and <理由>",
        "    <!-- hidden -->",
        r"escaped \<head>",
    )
    for control in safe_controls:
        assert not _contains_raw_html_outside_code(control), f"不应误伤正常文本：{control!r}"

    # 3. Codex R17 最小复现 + 扩展 HTML5 容器标签：第一条发现含 <head>/<iframe>/<div hidden> 时一律围栏隔离，绝不吞噬后续证据与第二条发现
    for payload in (
        "okay <head>",
        "okay <iframe>",
        "okay <div hidden>",
        "okay <details>",
        'okay <span style="display:none">',
    ):
        f1 = _finding(
            severity=Severity.IMPORTANT,
            file="pilot1742/demo.py",
            line=10,
            category="bug1",
            failure_scenario=payload,
            evidence="FIRST_EVIDENCE_VISIBLE",
        )
        f2 = _finding(
            severity=Severity.IMPORTANT,
            file="pilot1742/demo.py",
            line=20,
            category="bug2",
            failure_scenario="SECOND_VISIBLE",
            evidence="SECOND_EVIDENCE_VISIBLE",
        )
        cand = _candidates([f1, f2])
        vr = parse_verifier_output(
            _verifier_payload(
                cand,
                [
                    {"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "FIRST_EVIDENCE_VISIBLE"},
                    {"finding_id": f2.finding_id, "verdict": "confirmed", "verifier_evidence": "SECOND_EVIDENCE_VISIBLE"},
                ],
            ),
            cand,
            verifier_model="claude-opus-5-5",
        )
        rendered = render_findings_comment(1928, HEAD_1, evaluate_round(vr))
        assert not _leaves_html_suppressed(rendered.body)
        assert f"  - 失败场景：\n\n    ```\n    {payload}\n    ```" in rendered.body
        assert "  - 核实证据：FIRST_EVIDENCE_VISIBLE" in rendered.body
        assert "  - 失败场景：SECOND_VISIBLE" in rendered.body
        # 跳过首行去重 HTML 注释 marker 后，整条评论代码外不得残余原始 HTML
        body_after_marker = "\n".join(rendered.body.split("\n")[1:])
        assert not _contains_raw_html_outside_code(body_after_marker)

    # 4. 作者不修理由含 okay <head> 时经 _format_inline_markdown_field 用代码段包裹，不吞噬后续核实证据
    f_wf = _finding(severity=Severity.IMPORTANT, file="pilot1742/demo.py", line=30, category="wf-head")
    cand_wf = _candidates([f_wf])
    reply_head = AuthorReply(
        comment_id="c-r19-head",
        author="alice",
        finding_id=f_wf.finding_id,
        file=None,
        line=None,
        reason="okay <head>",
    )
    vr_wf = parse_verifier_output(
        _verifier_payload(
            cand_wf,
            [{"finding_id": f_wf.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "WONTFIX_EVIDENCE_VISIBLE"}],
        ),
        cand_wf,
        verifier_model="claude-opus-5-5",
        author_replies=[reply_head],
    )
    rendered_wf = render_findings_comment(1928, HEAD_1, evaluate_round(vr_wf))
    assert "（理由：`okay <head>`）：WONTFIX_EVIDENCE_VISIBLE" in rendered_wf.body
    assert not _leaves_html_suppressed(rendered_wf.body)
    assert not _contains_raw_html_outside_code("\n".join(rendered_wf.body.split("\n")[1:]))

    # 5. 对照组：普通行内代码 `<span>`、自动链接 <https://example.com> 与数学比较 a < b 保持行内渲染，不误加围栏
    normal_text = "Run `<span>` with <https://example.com> when a < b"
    f_norm = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=35,
        category="normal-md",
        failure_scenario=normal_text,
        evidence=normal_text,
    )
    cand_norm = _candidates([f_norm])
    vr_norm = parse_verifier_output(
        _verifier_payload(cand_norm, [{"finding_id": f_norm.finding_id, "verdict": "confirmed", "verifier_evidence": normal_text}]),
        cand_norm,
        verifier_model="claude-opus-5-5",
    )
    rendered_norm = render_findings_comment(1928, HEAD_1, evaluate_round(vr_norm))
    assert f"  - 失败场景：{normal_text}" in rendered_norm.body
    assert "    ```" not in rendered_norm.body


def test_r19_single_line_preserves_inline_code_span_whitespace_in_compact_mode() -> None:
    """R19 Important 3：_single_line 行内代码感知空白规整，紧凑模式下完整保留反引号代码内部连续空格。"""
    code = 'assert "a  b" != "a b"'
    assert _single_line(f"Run `{code}`") == f"Run `{code}`"
    assert _single_line(f"  Run   `{code}`   now  ") == f"Run `{code}` now"
    assert _single_line('Run `assert "a  b" !=\n"a b"`') == f"Run `{code}`"
    assert _single_line("  `a  b`   `c  d`  ") == "`a  b` `c  d`"

    # 1. Codex R17 最小复现：Severity.NIT + class_scope='X'*300 在 max_chars=65536 与 max_chars=400 均保留双空格断言
    f_nit = _finding(
        severity=Severity.NIT,
        file="pilot1742/demo.py",
        line=55,
        category="nit",
        failure_scenario=f"Run `{code}`",
        evidence=f"Check `{code}`",
        class_scope="X" * 300,
    )
    cand = _candidates([f_nit])
    vr = parse_verifier_output(
        _verifier_payload(cand, [{"finding_id": f_nit.finding_id, "verdict": "confirmed", "verifier_evidence": f"Check `{code}`"}]),
        cand,
        verifier_model="claude-opus-5-5",
    )
    dec = evaluate_round(vr)
    rendered_full = render_findings_comment(1928, HEAD_1, dec, max_chars=65536)
    rendered_compact = render_findings_comment(1928, HEAD_1, dec, max_chars=400)
    assert not rendered_full.truncated
    assert rendered_compact.truncated
    assert f_nit.finding_id in rendered_compact.posted_fingerprints
    assert code in rendered_full.body
    assert code in rendered_compact.body
    assert f"Run `{code}`" in rendered_compact.body
    assert f"（核实证据：Check `{code}`）" in rendered_compact.body

    # 2. 阻断项紧凑降级路径同样保留行内代码内部双空格
    f_imp = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=60,
        category="imp-ws",
        failure_scenario=f"Run `{code}`",
        evidence="E" * 300,
    )
    cand_imp = _candidates([f_imp])
    vr_imp = parse_verifier_output(
        _verifier_payload(cand_imp, [{"finding_id": f_imp.finding_id, "verdict": "confirmed", "verifier_evidence": "E" * 300}]),
        cand_imp,
        verifier_model="claude-opus-5-5",
    )
    dec_imp = evaluate_round(vr_imp)
    full_imp_len = len(render_findings_comment(1928, HEAD_1, dec_imp).body)
    compact_imp = render_findings_comment(1928, HEAD_1, dec_imp, max_chars=full_imp_len - 80)
    assert compact_imp.truncated
    assert f"Run `{code}`" in compact_imp.body


# ── R20 精准回归（Codex R18 全部 3 项 Important）──────────────────────────────────


def test_r20_important1_fingerprint_preserves_code_case_and_whitespace() -> None:
    """R20 Important 1（R24 无损契约）：指纹归一化无损保留大小写、空格与代码块结构，仅规范路径、类别多余空白、换行与首尾空行。"""
    # 1. Codex R18 最小复现：GET `/A` returns 500 (line 10) 与 GET `/a` returns 500 (line 42) 不得误合并
    f_upper = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/routes.py",
        line=10,
        category="http-500",
        failure_scenario="GET `/A` returns 500",
        evidence="uppercase route crashes",
    )
    f_lower = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/routes.py",
        line=42,
        category="http-500",
        failure_scenario="GET `/a` returns 500",
        evidence="lowercase route crashes",
    )
    assert f_upper.finding_id != f_lower.finding_id
    merged_distinct = merge_and_dedupe_findings([("gpt-6-astra", [f_upper, f_lower])])
    assert len(merged_distinct) == 2
    assert {item.line for item in merged_distinct} == {10, 42}
    assert {item.failure_scenario for item in merged_distinct} == {"GET `/A` returns 500", "GET `/a` returns 500"}

    # 2. 同语义变体（./路径、类别首尾空白、CRLF 与首尾空行）仍正常去重；大小写差异不误合并
    f_upper_norm_variant = _finding(
        severity=Severity.IMPORTANT,
        file="./pilot1742/routes.py",
        line=10,
        category="  http-500  ",
        failure_scenario="\r\nGET `/A` returns 500\r\n",
        evidence="same uppercase route",
    )
    assert f_upper.finding_id == f_upper_norm_variant.finding_id
    merged_same = merge_and_dedupe_findings(
        [("gpt-6-astra", [f_upper]), ("gpt-6.1-sol", [f_upper_norm_variant])]
    )
    assert len(merged_same) == 1
    assert merged_same[0].source_models == ("gpt-6-astra", "gpt-6.1-sol")
    assert fingerprint("pilot1742/routes.py", "HTTP-500", "GET `/A` returns 500") != f_upper.finding_id

    # 3. 缩进代码块与围栏代码块保留大小写、内部水平空格及各自原始形态（不再有损折叠）
    indented_a = '    assert "A" == "a"'
    indented_b = '    assert "a" == "a"'
    assert fingerprint("pilot1742/a.py", "bug", indented_a) != fingerprint("pilot1742/a.py", "bug", indented_b)

    fenced_a = '```\nassert "A" == "a"\n```'
    fenced_b = '```\nassert "a" == "a"\n```'
    assert fingerprint("pilot1742/a.py", "bug", fenced_a) != fingerprint("pilot1742/a.py", "bug", fenced_b)
    assert fingerprint("pilot1742/a.py", "bug", indented_a) != fingerprint("pilot1742/a.py", "bug", fenced_a)

    assert fingerprint("pilot1742/a.py", "bug", '    assert "a  b"') != fingerprint(
        "pilot1742/a.py", "bug", '    assert "a b"'
    )

    # 4. 行内代码保留内部水平空格与原文大小写
    assert fingerprint("pilot1742/a.py", "bug", 'Run `assert "a  b"`') != fingerprint(
        "pilot1742/a.py", "bug", 'Run `assert "a b"`'
    )
    assert fingerprint("pilot1742/a.py", "bug", "GET `/A` returns 500") != fingerprint(
        "pilot1742/a.py", "bug", "get `` /A `` returns 500"
    )

    # 5. category 行内无损归一化：折叠内部多余空白、去首尾空白、保留大小写
    assert _normalize_fingerprint_text("  Race  Condition ", "category") == "Race Condition"
    assert _normalize_fingerprint_text("Race  Condition", "category") != _normalize_fingerprint_text(
        "race condition", "category"
    )
    assert _normalize_fingerprint_text("---", "category") == "---"
    assert _normalize_fingerprint_text("---", "category") != _normalize_fingerprint_text("***", "category")


def test_r20_important2_inline_markdown_preserves_html_blocks_alongside_code_blocks() -> None:
    """R20 Important 2：含代码块时不再静默丢弃同字段中的原始 HTML 块，改为隔离为可见行内代码字面量。"""
    repro = "Repro:\n\n<!-- REQUIRED -->\n\n    check()"

    # 1. Codex R18 最小复现：_format_inline_markdown_field 同时保留 HTML 注释与缩进代码块
    formatted = _format_inline_markdown_field(repro)
    assert formatted == "Repro: `<!-- REQUIRED -->` `check()`"
    assert not _contains_raw_html_outside_code(formatted)
    assert not _leaves_html_suppressed(formatted)

    # 2. 变体：HTML 块内部双空格、反引号、未闭合 HTML 块、表格单元格内纯 HTML、段落内 <script> 均安全隔离保留
    assert (
        _format_inline_markdown_field("Repro:\n\n<!-- a  b -->\n\n    check()")
        == "Repro: `<!-- a  b -->` `check()`"
    )
    assert (
        _format_inline_markdown_field("Repro:\n\n<!-- `tick` -->\n\n    check()")
        == "Repro: ``<!-- `tick` -->`` `check()`"
    )
    unclosed_fmt = _format_inline_markdown_field("Repro:\n\n<!-- OPEN\n\n    check()")
    assert "<!-- OPEN" in unclosed_fmt
    assert "check()" in unclosed_fmt
    assert not _contains_raw_html_outside_code(unclosed_fmt)
    assert not _leaves_html_suppressed(unclosed_fmt)

    table_html_fmt = _format_inline_markdown_field("| h1 | h2 |\n| --- | --- |\n| <!-- CELL --> | ok |")
    assert "`<!-- CELL -->`" in table_html_fmt
    assert "ok" in table_html_fmt
    assert not _contains_raw_html_outside_code(table_html_fmt)

    script_para_fmt = _format_inline_markdown_field("See <script>x</script>\n\n    check()")
    assert "`See <script>x</script>` `check()`" == script_para_fmt
    assert not _contains_raw_html_outside_code(script_para_fmt)

    # 3. 放入已确认 Important（evidence='E'*900, max_chars=400），评论源码同时可见 <!-- REQUIRED --> 与 check()
    f_imp = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=42,
        category="html-block",
        failure_scenario=repro,
        evidence="E" * 900,
    )
    cand = _candidates([f_imp])
    vr = parse_verifier_output(
        _verifier_payload(cand, [{"finding_id": f_imp.finding_id, "verdict": "confirmed", "verifier_evidence": "E" * 900}]),
        cand,
        verifier_model="claude-opus-5-5",
    )
    dec = evaluate_round(vr)
    rendered = render_findings_comment(1928, HEAD_1, dec, max_chars=400)
    assert rendered.truncated
    assert len(rendered.body) <= 400
    assert "Repro: `<!-- REQUIRED -->` `check()`" in rendered.body
    body_after_marker = "\n".join(rendered.body.split("\n")[1:])
    assert not _contains_raw_html_outside_code(body_after_marker)
    assert not _leaves_html_suppressed(rendered.body)


def test_r20_important3_code_locations_safely_wrap_backtick_filenames() -> None:
    """R20 Important 3：全部 7 处评论位置渲染点统一复用 _format_code_location，精确保全含反引号合法文件名。"""

    def extract_code_spans(line: str) -> list[str]:
        spans: list[str] = []
        for kind, raw in _tokenize_inline_clip_segments(line):
            if kind == "code":
                k = 0
                while k < len(raw) and raw[k] == "`":
                    k += 1
                spans.append(_extract_code_span_text(raw[k : len(raw) - k]))
        return spans

    # 1. 普通路径与多种反引号边界路径
    f_plain = _finding(file="pilot1742/demo.py", line=42)
    assert _format_code_location(f_plain) == "`pilot1742/demo.py:42`"

    cases = (
        ("docs/a`b.md", 42, "``docs/a`b.md:42``", "docs/a`b.md:42"),
        ("`a.md", 42, "`` `a.md:42 ``", "`a.md:42"),
        ("a.md`", None, "`` a.md` ``", "a.md`"),
        ("docs/a``b.md", 42, "```docs/a``b.md:42```", "docs/a``b.md:42"),
    )
    for raw_file, raw_line, expected_md, expected_plain in cases:
        f_case = _finding(file=raw_file, line=raw_line)
        rendered_loc = _format_code_location(f_case)
        assert rendered_loc == expected_md
        assert extract_code_spans(rendered_loc) == [expected_plain]

    # 2. 全部 7 处位置渲染点逐一验证 docs/a`b.md:42 精确保真
    f_bt = _finding(
        severity=Severity.IMPORTANT,
        file="docs/a`b.md",
        line=42,
        category="backtick-path",
        failure_scenario="含反引号路径触发解析问题",
        evidence="确认路径含反引号",
    )
    vf_imp = _verified(f_bt, VerificationVerdict.CONFIRMED)
    expected_loc_plain = "docs/a`b.md:42"
    expected_loc_md = "``docs/a`b.md:42``"

    # (1) _render_new_blocking_item
    item_new = _render_new_blocking_item(vf_imp)
    assert expected_loc_md in item_new.split("\n")[0]
    assert expected_loc_plain in extract_code_spans(item_new.split("\n")[0])

    # (2) _render_prior_blocking_summary
    item_prior = _render_prior_blocking_summary([vf_imp])
    assert expected_loc_md in item_prior
    assert expected_loc_plain in extract_code_spans(item_prior)

    # (3) _render_minimal_blocking_item
    item_min = _render_minimal_blocking_item(vf_imp)
    assert expected_loc_md in item_min
    assert expected_loc_plain in extract_code_spans(item_min)

    # (4) _render_compact_new_blocking_item
    item_compact_imp = _render_compact_new_blocking_item(vf_imp)
    assert expected_loc_md in item_compact_imp
    assert expected_loc_plain in extract_code_spans(item_compact_imp)

    # (5) _render_non_blocking_item & (6) _render_compact_non_blocking_item
    f_bt_nit = _finding(
        severity=Severity.NIT,
        file="docs/a`b.md",
        line=42,
        category="backtick-nit",
        failure_scenario="非阻断反引号路径",
        evidence="非阻断证据",
    )
    vf_nit = _verified(f_bt_nit, VerificationVerdict.CONFIRMED)
    item_nb = _render_non_blocking_item(vf_nit)
    assert expected_loc_md in item_nb.split("\n")[0]
    assert expected_loc_plain in extract_code_spans(item_nb.split("\n")[0])

    item_compact_nb = _render_compact_non_blocking_item(vf_nit, 200)
    assert item_compact_nb is not None
    assert expected_loc_md in item_compact_nb
    assert expected_loc_plain in extract_code_spans(item_compact_nb)

    # (7) render_findings_comment 的 disposition_lines（RESOLVED_BY_FIX / RESOLVED_BY_WONTFIX / REJECTED）
    f_bt_fix = _finding(severity=Severity.IMPORTANT, file="docs/a`b.md", line=11, category="fix-bt")
    f_bt_wf = _finding(severity=Severity.IMPORTANT, file="`a.md", line=22, category="wf-bt")
    f_bt_rej = _finding(severity=Severity.IMPORTANT, file="docs/a``b.md", line=33, category="rej-bt")
    reply_wf = AuthorReply(
        comment_id="c-r20-wf",
        author="alice",
        finding_id=f_bt_wf.finding_id,
        file=None,
        line=None,
        reason="保留现有文件名",
    )
    e1_prev = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset({f_bt_fix.finding_id, f_bt_wf.finding_id}),
        (f_bt_fix, f_bt_wf),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r1-bt-1", "r1-bt-2"}),
    )
    cand_disp = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([f_bt_rej], round_number=2, head_sha=HEAD_2),
        history=(e1_prev,),
    )
    vr_disp = parse_verifier_output(
        _verifier_payload(
            cand_disp,
            [
                {"finding_id": f_bt_fix.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "已修复"},
                {"finding_id": f_bt_wf.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "确认不修"},
                {"finding_id": f_bt_rej.finding_id, "verdict": "rejected", "verifier_evidence": "误报"},
            ],
        ),
        cand_disp,
        verifier_model="claude-opus-5-5",
        author_replies=[reply_wf],
    )
    rendered_disp = render_findings_comment(1928, HEAD_2, evaluate_round(vr_disp))
    assert "``docs/a`b.md:11``" in rendered_disp.body
    assert "`` `a.md:22 ``" in rendered_disp.body
    assert "```docs/a``b.md:33```" in rendered_disp.body
    all_disp_spans = [span for ln in rendered_disp.body.split("\n") for span in extract_code_spans(ln)]
    assert "docs/a`b.md:11" in all_disp_spans
    assert "`a.md:22" in all_disp_spans
    assert "docs/a``b.md:33" in all_disp_spans


# ── R21 精准回归（Codex R19 全部 3 项 Important：指纹归一化彻底解耦块解析） ─────────


def _r21_probe(a: str, b: str, *, category: bool = False) -> tuple[Finding, Finding, tuple[Finding, ...]]:
    """复刻 Codex R19 probe(...) 构造：测试两组输入指纹与 merge_and_dedupe_findings 归并结果。"""
    if category:
        f1 = Finding(Severity.IMPORTANT, "pilot1742/demo.py", 10, a, "boom", "e1")
        f2 = Finding(Severity.IMPORTANT, "pilot1742/demo.py", 20, b, "boom", "e2")
    else:
        f1 = Finding(Severity.IMPORTANT, "pilot1742/demo.py", 10, "bug", a, "e1")
        f2 = Finding(Severity.IMPORTANT, "pilot1742/demo.py", 20, "bug", b, "e2")
    merged = merge_and_dedupe_findings([("gpt-6-astra", [f1, f2])])
    return f1, f2, merged


def test_r21_important1_multiline_code_span_preserves_trailing_spaces_before_newline() -> None:
    """R21 Important 1（R24 无损契约）：跨行代码跨度完整保留换行前空格与续行空格，仅统一换行符与首尾空行。"""
    # 1. Codex R19 原例：Run `a  \nb` (3 spaces) vs Run `a\nb` (1 space)
    f1, f2, merged = _r21_probe("Run `a  \nb`", "Run `a\nb`")
    assert f1.finding_id != f2.finding_id
    assert len(merged) == 2
    assert {item.finding_id for item in merged} == {f1.finding_id, f2.finding_id}
    norm_3sp = _normalize_fingerprint_text("Run `a  \nb`", "failure_scenario", allow_code_blocks=True)
    norm_1sp = _normalize_fingerprint_text("Run `a\nb`", "failure_scenario", allow_code_blocks=True)
    assert norm_3sp == "Run `a  \nb`"
    assert norm_1sp == "Run `a\nb`"

    # 2. CRLF 与首尾空行规整到同指纹，非空行内前导/尾随空格原样保留
    assert fingerprint("pilot1742/demo.py", "bug", "Run `a  \r\nb`") == f1.finding_id
    assert fingerprint("pilot1742/demo.py", "bug", "Run `a\r\nb`") == f2.finding_id
    assert fingerprint("pilot1742/demo.py", "bug", "\nRun `a\nb`\r\n\r\n") == f2.finding_id
    assert fingerprint("pilot1742/demo.py", "bug", "Run `a\n  b`") != f2.finding_id
    assert fingerprint("pilot1742/demo.py", "bug", "Run `a  \n  b`") != f1.finding_id

    # 3. 既有单行代码大小写区分与无损去重回归校验
    fa, fb, merged_ab = _r21_probe("GET `/A` returns 500", "GET `/a` returns 500")
    assert fa.finding_id != fb.finding_id
    assert len(merged_ab) == 2

    fc1, fc2, merged_same = _r21_probe("GET `/A` returns 500", "\r\nGET `/A` returns 500\r\n")
    assert fc1.finding_id == fc2.finding_id
    assert len(merged_same) == 1
    assert merged_same[0].finding_id == fc1.finding_id


def test_r21_important2_link_reference_definitions_and_inline_link_targets_preserved() -> None:
    """R21 Important 2（R24 无损契约）：链接引用定义、内联链接与自动链接目标原样保留，绝不因剥离或小写折叠误合并。"""
    # 1. Codex R19 原例：[endpoint]: /v1/users vs /v2/users
    f1, f2, merged = _r21_probe(
        "GET [endpoint] fails\n\n[endpoint]: /v1/users",
        "GET [endpoint] fails\n\n[endpoint]: /v2/users",
    )
    assert f1.finding_id != f2.finding_id
    assert len(merged) == 2
    assert {item.finding_id for item in merged} == {f1.finding_id, f2.finding_id}

    # 2. 链接引用定义目标大小写敏感：/v1/A vs /v1/a
    f_up, f_lo, merged_case = _r21_probe(
        "GET [endpoint] fails\n\n[endpoint]: /v1/A",
        "GET [endpoint] fails\n\n[endpoint]: /v1/a",
    )
    assert f_up.finding_id != f_lo.finding_id
    assert len(merged_case) == 2
    assert {item.finding_id for item in merged_case} == {f_up.finding_id, f_lo.finding_id}

    # 3. 无损契约：CRLF 变体归一到同 ID，写法/大小写差异不再有损折并
    assert fingerprint(
        "pilot1742/demo.py", "bug", "GET [endpoint] fails\r\n\r\n[endpoint]: /v1/A\r\n"
    ) == f_up.finding_id
    assert fingerprint(
        "pilot1742/demo.py", "bug", "GET [endpoint] fails\n\n[ENDPOINT]:\n  </v1/A>"
    ) != f_up.finding_id

    # 4. 内联链接目标保留大小写
    il_up, il_lo, merged_il = _r21_probe("GET [ep](/v1/A) fails", "GET [ep](/v1/a) fails")
    assert il_up.finding_id != il_lo.finding_id
    assert len(merged_il) == 2
    assert fingerprint("pilot1742/demo.py", "bug", "GET [ep](/v1/A) fails\r\n") == il_up.finding_id

    # 5. 自动链接 URI 保留路径大小写
    auto_up, auto_lo, merged_auto = _r21_probe(
        "See <https://api.example.com/v1/A>",
        "See <https://api.example.com/v1/a>",
    )
    assert auto_up.finding_id != auto_lo.finding_id
    assert len(merged_auto) == 2


def test_r21_important3_category_vs_indented_code_and_merge_id_invariance() -> None:
    """R21 Important 3（R24 无损契约）：category 去首尾/折多余空白且保留大小写，failure_scenario 保留缩进与大小写，归并永不突变 ID。"""
    # 1. category="    GET /A" 与 "GET /A" 完全一致（输入/指纹/归并 100% 统一），且与 "    GET /a" 绝不误合并
    c1, c2, merged_cat_distinct = _r21_probe("    GET /A", "    GET /a", category=True)
    assert c1.finding_id != c2.finding_id
    assert len(merged_cat_distinct) == 2
    assert {item.finding_id for item in merged_cat_distinct} == {c1.finding_id, c2.finding_id}

    cs1, cs2, merged_cat_same = _r21_probe("    GET /A", "GET  /A", category=True)
    assert cs1.finding_id == cs2.finding_id
    assert len(merged_cat_same) == 1
    assert merged_cat_same[0].finding_id == cs1.finding_id
    assert merged_cat_same[0].category == "GET  /A"
    assert fingerprint("pilot1742/demo.py", "GET /A", "boom") == cs1.finding_id

    # 与 parse_finder_output 入口解析出的 Finding 指纹完全一致
    parsed_cat = parse_finder_output(
        {
            "findings": [
                {
                    "severity": "Important",
                    "file": "pilot1742/demo.py",
                    "line": 10,
                    "category": "    GET /A",
                    "failure_scenario": "boom",
                    "evidence": "e1",
                }
            ]
        },
        source_model="gpt-6-astra",
    )
    assert parsed_cat[0].finding_id == c1.finding_id

    # category 带前导空格但含行内反引号代码：仍保留代码大小写且归并后 ID 不突变
    cc1, cc2, merged_cat_code = _r21_probe("    GET `/A`", "    GET `/a`", category=True)
    assert cc1.finding_id != cc2.finding_id
    assert len(merged_cat_code) == 2
    assert {item.finding_id for item in merged_cat_code} == {cc1.finding_id, cc2.finding_id}

    # 2. failure_scenario 4 空格 / Tab 缩进代码块均保留大小写与原始缩进，归并后保留 2 条且 ID 不变
    s1, s2, merged_scen = _r21_probe("    GET /A", "    GET /a", category=False)
    assert s1.finding_id != s2.finding_id
    assert len(merged_scen) == 2
    assert {item.finding_id for item in merged_scen} == {s1.finding_id, s2.finding_id}
    assert fingerprint("pilot1742/demo.py", "bug", "\tGET /A") != fingerprint("pilot1742/demo.py", "bug", "\tGET /a")
    assert fingerprint("pilot1742/demo.py", "bug", "\tGET /A") != s1.finding_id

    # 各类上下文中大小写差异均不误合并
    assert fingerprint("pilot1742/demo.py", "bug", "Intro\n    GET /A") != fingerprint(
        "pilot1742/demo.py", "bug", "intro get /a"
    )
    assert fingerprint("pilot1742/demo.py", "bug", "Intro\n\n    GET /A") != fingerprint(
        "pilot1742/demo.py", "bug", "Intro\n\n    GET /a"
    )
    assert fingerprint("pilot1742/demo.py", "bug", "# Route\n    GET /A") != fingerprint(
        "pilot1742/demo.py", "bug", "# Route\n    GET /a"
    )

    # 3. 混合批量归并不变量：输出 ID 集合与输入分组 ID 集合严格相等、永不突变、永不重复
    mixed = [
        Finding(Severity.IMPORTANT, "pilot1742/demo.py", 10, "    GET /A", "boom", "e1"),
        Finding(Severity.NIT, "pilot1742/demo.py", 11, "  GET  /A  ", "boom\r\n", "e2"),
        Finding(Severity.IMPORTANT, "pilot1742/demo.py", 12, "    GET `/A`", "Run `a  \nb`", "e3"),
        Finding(Severity.IMPORTANT, "pilot1742/demo.py", 13, "    GET `/a`", "Run `a\nb`", "e4"),
        Finding(Severity.IMPORTANT, "pilot1742/demo.py", 14, "bug", "    GET /A", "e5"),
        Finding(Severity.IMPORTANT, "pilot1742/demo.py", 15, "bug", "    GET /a", "e6"),
        Finding(Severity.IMPORTANT, "pilot1742/demo.py", 16, "bug", "GET [ep] fails\n\n[ep]: /v1/A", "e7"),
        Finding(Severity.IMPORTANT, "pilot1742/demo.py", 17, "bug", "GET [ep] fails\n\n[ep]: /v1/a", "e8"),
    ]
    expected_ids = {f.finding_id for f in mixed}
    merged_mixed = merge_and_dedupe_findings([("gpt-6-astra", mixed)])
    merged_ids = [f.finding_id for f in merged_mixed]
    assert len(merged_ids) == len(set(merged_ids))
    assert set(merged_ids) == expected_ids


# ── R22 精准回归（Codex R20 全部 3 项 Important：R24 无损指纹契约保持全部异义区分） ────────


def test_r22_important1_thematic_break_and_container_indented_code_reuse_canonical_parser() -> None:
    """R22 Important 1（R24 无损契约）：分隔线/容器后缩进代码块均不误合并，且权威块解析器默认语义不受影响。"""
    # 1. Codex R20 复现①：分隔线 --- 后接缩进代码块保留大小写，绝不误合并
    f1, f2, merged = _r21_probe("Run\n\n---\n    GET /A", "Run\n\n---\n    GET /a")
    assert f1.finding_id != f2.finding_id
    assert len(merged) == 2
    assert {item.finding_id for item in merged} == {f1.finding_id, f2.finding_id}

    # 2. Setext 标题下划线、块引用与列表项内的缩进代码块均严格区分大小写
    for upper_case, lower_case in (
        ("Run\n---\n    GET /A", "Run\n---\n    GET /a"),
        ("Run\n\n>     GET /A", "Run\n\n>     GET /a"),
        ("Run\n\n-     GET /A", "Run\n\n-     GET /a"),
    ):
        fa, fb, m = _r21_probe(upper_case, lower_case)
        assert fa.finding_id != fb.finding_id
        assert len(m) == 2

    # 3. 缩进代码块与围栏代码块保持各自指纹（不再有损折叠），且默认 _parse_commonmark_blocks 调用语义不变
    assert fingerprint("pilot1742/demo.py", "bug", "Run\n\n---\n    GET /A") != fingerprint(
        "pilot1742/demo.py", "bug", "Run\n\n---\n```\nGET /A\n```"
    )
    default_blocks, _ = _parse_commonmark_blocks("Run `a  \nb`", include_all_visible_blocks=True)
    assert default_blocks == [("paragraph", "Run `a\nb`")]


def test_r22_important2_container_link_reference_definitions_and_titles_captured() -> None:
    """R22 Important 2（R24 无损契约）：块引用、列表项及嵌套容器内的链接引用定义与 title 完整保留、绝不误合并。"""
    # 1. Codex R20 复现②：块引用内链接引用定义 > [ep]: /A vs > [ep]: /a
    fq1, fq2, merged_q = _r21_probe("See [ep].\n\n> [ep]: /A", "See [ep].\n\n> [ep]: /a")
    assert fq1.finding_id != fq2.finding_id
    assert len(merged_q) == 2
    assert {item.finding_id for item in merged_q} == {fq1.finding_id, fq2.finding_id}

    # 2. 列表项内及多层嵌套容器内的链接引用定义
    fl1, fl2, merged_l = _r21_probe("See [ep].\n\n- [ep]: /A", "See [ep].\n\n- [ep]: /a")
    assert fl1.finding_id != fl2.finding_id
    assert len(merged_l) == 2
    assert {item.finding_id for item in merged_l} == {fl1.finding_id, fl2.finding_id}

    fn1, fn2, merged_n = _r21_probe("See [ep].\n\n> - [ep]: /A", "See [ep].\n\n> - [ep]: /a")
    assert fn1.finding_id != fn2.finding_id
    assert len(merged_n) == 2

    # 3. CRLF 变体归一到同 ID，附加链接定义不再被静默忽略
    assert fingerprint("pilot1742/demo.py", "bug", "See [ep].\r\n\r\n> [ep]: /A\r\n") == fq1.finding_id
    assert fingerprint("pilot1742/demo.py", "bug", "See [ep].\n\n> [ep]: /A\n\n- [ep]: /B") != fq1.finding_id

    # 4. 链接引用定义 title 区分（大小写敏感、不同 title 与无 title 均不碰撞）
    ft1, ft2, merged_t = _r21_probe('See [ep].\n\n> [ep]: /A "TitleA"', 'See [ep].\n\n> [ep]: /A "TitleB"')
    assert ft1.finding_id != ft2.finding_id
    assert len(merged_t) == 2
    assert ft1.finding_id != fq1.finding_id
    assert fingerprint("pilot1742/demo.py", "bug", 'See [ep].\n\n> [ep]: /A "TitleA"') != fingerprint(
        "pilot1742/demo.py", "bug", 'See [ep].\n\n> [ep]: /A "titlea"'
    )


def test_r22_important3_injective_typed_json_tokens_eliminate_delimiter_collisions() -> None:
    """R22 Important 3（R24 无损契约）：无损文本 + 注入式 JSON 数组指纹杜绝内联链接、字段分隔符与自动链接碰撞。"""
    # 1. Codex R20 复现③：GET [ep](</A)b>) vs GET [ep](/A)b) 绝不碰撞
    f1, f2, merged = _r21_probe("GET [ep](</A)b>)", "GET [ep](/A)b)")
    assert f1.finding_id != f2.finding_id
    assert len(merged) == 2
    assert {item.finding_id for item in merged} == {f1.finding_id, f2.finding_id}
    assert _normalize_fingerprint_text("GET [ep](</A)b>)", "failure_scenario", allow_code_blocks=True) == "GET [ep](</A)b>)"
    assert _normalize_fingerprint_text("GET [ep](/A)b)", "failure_scenario", allow_code_blocks=True) == "GET [ep](/A)b)"
    # 字段间含分隔符字符 `|` 绝不发生跨字段碰撞
    assert fingerprint("pilot1742/a|b.py", "cat", "scen") != fingerprint("pilot1742/a", "b.py|cat", "scen")

    # 2. 内联链接 title 区分、图片与链接区分、自动链接 Email/URI 大小写保留
    lt1, lt2, merged_lt = _r21_probe('GET [ep](/A "T1")', 'GET [ep](/A "T2")')
    assert lt1.finding_id != lt2.finding_id
    assert len(merged_lt) == 2
    assert fingerprint("pilot1742/demo.py", "bug", 'GET [ep](/A "T1")') != fingerprint(
        "pilot1742/demo.py", "bug", "GET [ep](/A)"
    )

    img_f, lnk_f, merged_il = _r21_probe("See ![ep](/A)", "See [ep](/A)")
    assert img_f.finding_id != lnk_f.finding_id
    assert len(merged_il) == 2

    em1, em2, merged_em = _r21_probe("Notify <Admin@Example.com>", "Notify <admin@example.com>")
    assert em1.finding_id != em2.finding_id
    assert len(merged_em) == 2

    # 3. 无损契约：CRLF 变体归一到同 ID，大小写/空白改动不再有损折叠
    assert fingerprint("pilot1742/demo.py", "bug", "Swallows IOError silently\r\n") == fingerprint(
        "pilot1742/demo.py", "bug", "Swallows IOError silently"
    )
    assert fingerprint("pilot1742/demo.py", "bug", "Swallows IOError silently") != fingerprint(
        "pilot1742/demo.py", "bug", "swallows   ioerror silently"
    )


# ── R23 精准回归（Codex R21 全部 4 项 Important：保留块解析器精度 + R24 无损指纹去重） ────


def test_r23_important1_fenced_code_strips_opening_fence_indent() -> None:
    """R23 Important 1：_parse_commonmark_blocks 围栏代码块按 CommonMark §4.5 剥离起始围栏缩进，且无损指纹不误合并。"""
    # 1. Codex R21 最小复现：0 格围栏 vs 2 格缩进围栏
    f1, f2, merged = _r21_probe("Run\n\n~~~\n  pass\n~~~", "Run\n\n  ~~~\n  pass\n  ~~~")
    assert f1.finding_id != f2.finding_id
    assert len(merged) == 2
    assert {item.finding_id for item in merged} == {f1.finding_id, f2.finding_id}

    # 2. _parse_commonmark_blocks 对 0/1/2/3 格围栏与 Tab 展开保持 CommonMark §4.5 精确缩进剥离
    assert _parse_commonmark_blocks("Run\n\n~~~\n  pass\n~~~", include_all_visible_blocks=True)[0] == [
        ("paragraph", "Run"),
        ("code", "  pass"),
    ]
    assert _parse_commonmark_blocks("Run\n\n  ~~~\n  pass\n  ~~~", include_all_visible_blocks=True)[0] == [
        ("paragraph", "Run"),
        ("code", "pass"),
    ]
    assert _parse_commonmark_blocks(" ```\n   pass\n ```", include_all_visible_blocks=True)[0] == [("code", "  pass")]
    assert _parse_commonmark_blocks("  ```\n   pass\n  ```", include_all_visible_blocks=True)[0] == [("code", " pass")]
    assert _parse_commonmark_blocks("   ```\n   pass\n   ```", include_all_visible_blocks=True)[0] == [("code", "pass")]
    assert _parse_commonmark_blocks("   ```\n pass\n   ```", include_all_visible_blocks=True)[0] == [("code", "pass")]
    assert _parse_commonmark_blocks("  ~~~\n\tpass\n  ~~~", include_all_visible_blocks=True)[0] == [("code", "  pass")]


def test_r23_important2_gfm_table_preserves_2d_cell_positions_and_short_row_padding() -> None:
    """R23 Important 2：_parse_commonmark_blocks 二维 GFM 表格结构完整保留，且无损指纹不误合并任意行列位移。"""
    # 1. Codex R21 最小复现：|200|| vs ||200|
    t1 = "|Expected|Actual|\n|---|---|\n|200||"
    t2 = "|Expected|Actual|\n|---|---|\n||200|"
    f1, f2, merged = _r21_probe(t1, t2)
    assert f1.finding_id != f2.finding_id
    assert len(merged) == 2
    assert {item.finding_id for item in merged} == {f1.finding_id, f2.finding_id}

    # 2. _parse_commonmark_blocks 精确输出二维表格行列结构并按表头列数补空/截断
    b1, _ = _parse_commonmark_blocks(t1, include_all_visible_blocks=True)
    b2, _ = _parse_commonmark_blocks(t2, include_all_visible_blocks=True)
    assert b1[0][0] == "table" and json.loads(b1[0][1]) == [["Expected", "Actual"], ["200", ""]]
    assert b2[0][0] == "table" and json.loads(b2[0][1]) == [["Expected", "Actual"], ["", "200"]]
    b_short, _ = _parse_commonmark_blocks("|A|B|C|\n|---|---|---|\n|1|", include_all_visible_blocks=True)
    assert json.loads(b_short[0][1]) == [["A", "B", "C"], ["1", "", ""]]
    b_long, _ = _parse_commonmark_blocks("|A|B|\n|---|---|\n|1|2|extra|", include_all_visible_blocks=True)
    assert json.loads(b_long[0][1]) == [["A", "B"], ["1", "2"]]

    # 3. 多行多列空单元格位置精确区分（列位移与行位移均不同 ID）
    m_c0 = "|A|B|C|\n|---|---|---|\n|200|||\n||||"
    m_c1 = "|A|B|C|\n|---|---|---|\n||200||\n||||"
    m_c2 = "|A|B|C|\n|---|---|---|\n|||200|\n||||"
    m_r2 = "|A|B|C|\n|---|---|---|\n||||\n|200|||"
    multi_ids = {fingerprint("pilot1742/demo.py", "bug", tbl) for tbl in (m_c0, m_c1, m_c2, m_r2)}
    assert len(multi_ids) == 4

    # 4. 表格可见性判定与 wontfix 跳过表格语义保持不变
    assert _has_visible_gfm_text(t1)
    assert not _has_visible_gfm_text("| | |\n|---|---|\n| | |")
    assert parse_wontfix_replies(
        [{"id": "c-tbl", "user": {"login": "alice"}, "body": "|Col|\n|---|\n|不修：表格内忽略|"}],
        allowed_authors=["alice"],
    ) == ()


def test_r23_important3_inline_raw_html_preserves_case_as_typed_token() -> None:
    """R23 Important 3（R24 无损契约）：行内 HTML 标签、属性与注释严格保留原始大小写。"""
    # 1. Codex R21 最小复现：href="/A" vs href="/a"
    h1 = 'GET <a href="/A">endpoint</a>'
    h2 = 'GET <a href="/a">endpoint</a>'
    f1, f2, merged = _r21_probe(h1, h2)
    assert f1.finding_id != f2.finding_id
    assert len(merged) == 2
    assert {item.finding_id for item in merged} == {f1.finding_id, f2.finding_id}
    assert _normalize_fingerprint_text(h1, "failure_scenario", allow_code_blocks=True) == h1

    # 2. 对照：CRLF/首尾空行变体归一到同 ID，大小写差异保持区分
    f_same1, f_same2, merged_same = _r21_probe(f"\r\n{h1}\r\n", h1)
    assert f_same1.finding_id == f_same2.finding_id
    assert len(merged_same) == 1

    # 3. 行内 HTML 注释与标签名大小写同样保留
    hc1, hc2, merged_hc = _r21_probe("Check <!-- FlagA --> value", "Check <!-- flaga --> value")
    assert hc1.finding_id != hc2.finding_id
    assert len(merged_hc) == 2


def test_r23_important4_gfm_extended_bare_url_autolinks_preserve_case() -> None:
    """R23 Important 4（R24 无损契约）：任意裸 URL、带前后缀 URL 与标点上下文均无损保留大小写。"""
    # 1. Codex R21 最小复现：https://example.org/A vs https://example.org/a
    u1, u2, merged_u = _r21_probe("GET https://example.org/A", "GET https://example.org/a")
    assert u1.finding_id != u2.finding_id
    assert len(merged_u) == 2
    assert {item.finding_id for item in merged_u} == {u1.finding_id, u2.finding_id}
    assert (
        _normalize_fingerprint_text("GET https://example.org/A", "failure_scenario", allow_code_blocks=True)
        == "GET https://example.org/A"
    )

    # 2. www. 与 ftp:// 裸 URL 路径大小写区分
    w1, w2, merged_w = _r21_probe("GET www.example.org/A", "GET www.example.org/a")
    assert w1.finding_id != w2.finding_id
    assert len(merged_w) == 2

    ftp1, ftp2, merged_ftp = _r21_probe("GET ftp://files.example.org/A", "GET ftp://files.example.org/a")
    assert ftp1.finding_id != ftp2.finding_id
    assert len(merged_ftp) == 2

    # 3. 句末标点与括号上下文均保持大小写区分，CRLF 变体仍正常去重
    p1, p2, merged_p = _r21_probe("GET https://example.org/A.", "GET https://example.org/A.\r\n")
    assert p1.finding_id == p2.finding_id
    assert len(merged_p) == 1
    assert fingerprint("pilot1742/demo.py", "bug", "GET https://example.org/A.") != fingerprint(
        "pilot1742/demo.py", "bug", "GET https://example.org/a."
    )
    assert fingerprint("pilot1742/demo.py", "bug", "See (https://example.org/A).") != fingerprint(
        "pilot1742/demo.py", "bug", "See (https://example.org/a)."
    )
    assert fingerprint("pilot1742/demo.py", "bug", "See https://example.org/A&amp;.") != fingerprint(
        "pilot1742/demo.py", "bug", "See https://example.org/a&amp;."
    )
    assert fingerprint("pilot1742/demo.py", "bug", "prefix_https://example.org/A") != fingerprint(
        "pilot1742/demo.py", "bug", "prefix_https://example.org/a"
    )
    assert fingerprint("pilot1742/demo.py", "bug", "mywww.example.org/A") != fingerprint(
        "pilot1742/demo.py", "bug", "mywww.example.org/a"
    )


# ── R24 架构简化与根因收口（无损指纹契约：全量消除 Markdown/HTML/URL/邮箱/标志大小写误合并） ────


def test_r24_lossless_fingerprint_prevents_all_markdown_html_url_email_case_collisions() -> None:
    """R24 根治回归：覆盖 Codex R22 全部 5 组复现 + R18–R21 碰撞反例 + 裸路径/HTML/标志 + 正向去重与 ID 不变量。"""
    distinct_pairs: tuple[tuple[str, str], ...] = (
        # Codex R22 全部 5 组最小复现
        ("GET _https://example.org/A_", "GET _https://example.org/a_"),
        ("GET www.dev/A", "GET www.dev/a"),
        ("Send Alice@example.org", "Send alice@example.org"),
        ("Run <code>git add -A</code>", "Run <code>git add -a</code>"),
        ("Run\n\n~~~python2\nprint(1/2)\n~~~", "Run\n\n~~~python3\nprint(1/2)\n~~~"),
        # Codex R18–R21 全部代表性碰撞反例
        ("GET `/A` returns 500", "GET `/a` returns 500"),
        ("Run `a  \nb`", "Run `a\nb`"),
        ("GET [endpoint] fails\n\n[endpoint]: /v1/users", "GET [endpoint] fails\n\n[endpoint]: /v2/users"),
        ("    GET /A", "    GET /a"),
        ("Run\n\n---\n    GET /A", "Run\n\n---\n    GET /a"),
        ("See [ep].\n\n> [ep]: /A", "See [ep].\n\n> [ep]: /a"),
        ("GET [ep](</A)b>)", "GET [ep](/A)b)"),
        ("Run\n\n~~~\n  pass\n~~~", "Run\n\n  ~~~\n  pass\n  ~~~"),
        ("|Expected|Actual|\n|---|---|\n|200||", "|Expected|Actual|\n|---|---|\n||200|"),
        ('GET <a href="/A">endpoint</a>', 'GET <a href="/a">endpoint</a>'),
        ("GET https://example.org/A", "GET https://example.org/a"),
        # 新增裸路径 / HTML <kbd> / CLI 标志反例
        ("GET /A", "GET /a"),
        ("Press <kbd>Ctrl+A</kbd>", "Press <kbd>Ctrl+a</kbd>"),
        ("Pass flag -A to sync", "Pass flag -a to sync"),
    )
    for left, right in distinct_pairs:
        f1, f2, merged = _r21_probe(left, right)
        assert f1.finding_id != f2.finding_id, f"unexpected collision for {left!r} vs {right!r}"
        assert len(merged) == 2
        assert {item.finding_id for item in merged} == {f1.finding_id, f2.finding_id}

    # category 行内无损边界：首尾与内部多余空白归一，大小写严格保留
    c_eq1, c_eq2, m_ceq = _r21_probe("    GET /A", "GET /A", category=True)
    assert c_eq1.finding_id == c_eq2.finding_id
    assert len(m_ceq) == 1
    assert m_ceq[0].finding_id == c_eq1.finding_id
    assert m_ceq[0].category == "GET /A"

    c_sp1, c_sp2, m_csp = _r21_probe("Error  Handling", "Error Handling", category=True)
    assert c_sp1.finding_id == c_sp2.finding_id
    assert len(m_csp) == 1
    assert m_csp[0].finding_id == c_sp1.finding_id

    for cat_a, cat_b in (("    GET /A", "    GET /a"), ("GET `/A`", "GET `/a`")):
        ca, cb, mc = _r21_probe(cat_a, cat_b, category=True)
        assert ca.finding_id != cb.finding_id
        assert len(mc) == 2
        assert {item.finding_id for item in mc} == {ca.finding_id, cb.finding_id}

    # 正向去重对照：CRLF/CR/LF、首尾完全空行、./path 规范化均稳定命中同指纹，非空行空白不被剥离
    f_lf = _finding(
        severity=Severity.NIT,
        file="./pilot1742//demo.py",
        line=12,
        category="  Error  Handling  ",
        failure_scenario="Run\n\n~~~python3\n  print(1/2)\n~~~",
        evidence="lf",
        source_models=("gpt-6.1-sol",),
    )
    f_crlf = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/demo.py",
        line=10,
        category="Error Handling",
        failure_scenario="\r\n\r\nRun\r\n\r\n~~~python3\r\n  print(1/2)\r\n~~~\r\n",
        evidence="crlf",
        source_models=("gpt-6-astra",),
    )
    assert f_lf.finding_id == f_crlf.finding_id
    merged_norm = merge_and_dedupe_findings([("gpt-6.1-sol", [f_lf]), ("gpt-6-astra", [f_crlf])])
    assert len(merged_norm) == 1
    assert merged_norm[0].finding_id == f_lf.finding_id
    assert merged_norm[0].severity is Severity.IMPORTANT
    assert merged_norm[0].source_models == ("gpt-6-astra", "gpt-6.1-sol")

    # R25：非代码块首尾仅含 ASCII 空格/制表符的空行规整并剥离；代码块内部空行与尾随空格原样保留
    assert _normalize_fingerprint_text("  \nfoo\n  ", "failure_scenario", allow_code_blocks=True) == "foo"
    assert _normalize_fingerprint_text("\n\nfoo\r\n", "failure_scenario", allow_code_blocks=True) == "foo"
    assert _normalize_fingerprint_text("\n    GET /A\n", "failure_scenario", allow_code_blocks=True) == "    GET /A"


# ── R25 精准回归（Codex R23 全部 2 项 Important：category 代码跨度空格保护 + 段末/文末不可见尾随空白归一） ────


def test_r25_category_code_span_spaces_and_trailing_narrative_spaces() -> None:
    """R25 精准回归：锁定核实候选数与跨轮待贴数，覆盖复现 A/B、多段落、围栏尾空格、跨行代码跨度、硬换行与代码块尾空格。"""
    # 1. 复现 A（Important 1）：category 行内反引号代码跨度内连续空格绝不折叠，核实候选数为 2
    a = Finding(Severity.IMPORTANT, "importer.py", 10, "CSV 列 `unit price`", "导入时该列被静默丢弃", "复核通过")
    b = Finding(Severity.IMPORTANT, "importer.py", 20, "CSV 列 `unit  price`", "导入时该列被静默丢弃", "复核通过")
    assert a.finding_id != b.finding_id
    merged_ab = merge_and_dedupe_findings([("gpt-6-astra", [a, b])])
    assert len(merged_ab) == 2
    assert {item.finding_id for item in merged_ab} == {a.finding_id, b.finding_id}
    cand_ab = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel(
            [
                dataclasses.replace(a, source_models=("gpt-6-astra",)),
                dataclasses.replace(b, source_models=("gpt-6.1-sol",)),
            ],
            round_number=1,
            head_sha=HEAD_1,
        ),
    )
    assert len(cand_ab.findings) == 2
    assert {item.finding_id for item in cand_ab.findings} == {a.finding_id, b.finding_id}

    # 对照：普通叙述中的多余空白仍与 _pick_best_text 保持归并一致且 ID 恒等
    a_ws = Finding(Severity.IMPORTANT, "importer.py", 10, "  CSV  列  `unit price`  ", "导入时该列被静默丢弃", "复核通过")
    assert a_ws.finding_id == a.finding_id
    merged_a_ws = merge_and_dedupe_findings([("gpt-6-astra", [a]), ("gpt-6.1-sol", [a_ws])])
    assert len(merged_a_ws) == 1
    assert merged_a_ws[0].finding_id == a.finding_id

    # 2. 复现 B（Important 2）：failure_scenario 文末/段末 ASCII 尾随空格与制表符归一，跨轮待贴数为 0
    x = Finding(Severity.IMPORTANT, "importer.py", 10, "CSV 导入", "导入空表时抛出异常", "复核通过")
    y = Finding(Severity.IMPORTANT, "importer.py", 10, "CSV 导入", "导入空表时抛出异常 ", "复核通过")
    y_tab = Finding(Severity.IMPORTANT, "importer.py", 10, "CSV 导入", "导入空表时抛出异常   \t  ", "复核通过")
    assert x.finding_id == y.finding_id == y_tab.finding_id
    vf_y = _verified(y, VerificationVerdict.CONFIRMED, verifier_evidence="复核通过")
    assert len(select_postable_findings([vf_y], frozenset({x.finding_id}))) == 0

    # 完整 evaluate_round 跨轮验证：第 1 轮已贴出 x，第 2 轮发现 y 仅句末多空格，postable_findings 为 0
    x_r1 = dataclasses.replace(x, source_models=("gpt-6-astra",))
    y_r2 = dataclasses.replace(y, source_models=("gpt-6-astra",))
    e1_x = RoundHistoryEntry(
        1,
        HEAD_1,
        frozenset({x_r1.finding_id}),
        (x_r1,),
        panel=DEFAULT_PANEL,
        finder_session_ids=frozenset({"r1-x-1", "r1-x-2"}),
    )
    cand_r2 = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=DEFAULT_PANEL,
        finder_batches=_batches_for_panel([y_r2], round_number=2, head_sha=HEAD_2),
        history=(e1_x,),
    )
    assert len(cand_r2.findings) == 1
    assert cand_r2.findings[0].finding_id == x.finding_id
    vr_r2 = parse_verifier_output(
        _verifier_payload(cand_r2, [{"finding_id": x.finding_id, "verdict": "confirmed", "verifier_evidence": "仍存在"}]),
        cand_r2,
        verifier_model="claude-opus-5-5",
    )
    dec_r2 = evaluate_round(vr_r2)
    assert len(dec_r2.postable_findings) == 0
    assert len(dec_r2.blocking_findings) == 1

    # 3. 多段落段尾空格、空行内仅空白、闭合围栏尾空格均归一到同指纹且跨轮不重贴
    p_clean = Finding(Severity.IMPORTANT, "importer.py", 10, "CSV 导入", "第一段\n\n第二段", "e1")
    p_trail = Finding(Severity.IMPORTANT, "importer.py", 10, "CSV 导入", "第一段  \n   \t \n第二段 ", "e2")
    assert p_clean.finding_id == p_trail.finding_id
    assert len(merge_and_dedupe_findings([("gpt-6-astra", [p_clean, p_trail])])) == 1
    assert len(select_postable_findings([_verified(p_trail, VerificationVerdict.CONFIRMED)], frozenset({p_clean.finding_id}))) == 0

    fence_clean = Finding(Severity.IMPORTANT, "importer.py", 10, "CSV 导入", "```\ncode\n```", "e1")
    fence_trail = Finding(Severity.IMPORTANT, "importer.py", 10, "CSV 导入", "```\ncode\n```   \t", "e2")
    assert fence_clean.finding_id == fence_trail.finding_id
    assert len(merge_and_dedupe_findings([("gpt-6-astra", [fence_clean, fence_trail])])) == 1
    assert (
        len(select_postable_findings([_verified(fence_trail, VerificationVerdict.CONFIRMED)], frozenset({fence_clean.finding_id})))
        == 0
    )

    # 4. 严禁误伤：跨行代码跨度、硬换行、缩进/围栏代码块行尾空格、代码块内空行与 U+00A0 均保持 distinct（候选数 = 2）
    preserved_pairs: tuple[tuple[str, str], ...] = (
        ("Run `a  \nb`", "Run `a\nb`"),
        ("line1  \nline2", "line1\nline2"),
        ("    code  ", "    code"),
        ("```\ncode  \n```", "```\ncode\n```"),
        ("```\n  \ncode\n```", "```\ncode\n```"),
        ("    code1\n     \n    code2", "    code1\n\n    code2"),
        ("导入空表时抛出异常\u00a0", "导入空表时抛出异常"),
    )
    for left, right in preserved_pairs:
        f1, f2, merged_pair = _r21_probe(left, right)
        assert f1.finding_id != f2.finding_id, f"unexpected collision for {left!r} vs {right!r}"
        assert len(merged_pair) == 2
        assert {item.finding_id for item in merged_pair} == {f1.finding_id, f2.finding_id}
        assert len(select_postable_findings([_verified(f2, VerificationVerdict.CONFIRMED)], frozenset({f1.finding_id}))) == 1

    # 5. merge_and_dedupe_findings 身份不变性（含 NIT + IMPORTANT 优先级交叉归约）
    x_nit = Finding(Severity.NIT, "importer.py", 10, "CSV 导入", "导入空表时抛出异常", "e-nit")
    y_imp = Finding(Severity.IMPORTANT, "importer.py", 12, "CSV  导入", "导入空表时抛出异常   \t", "e-imp")
    merged_inv = merge_and_dedupe_findings([("gpt-6-astra", [x_nit]), ("gpt-6.1-sol", [y_imp])])
    assert len(merged_inv) == 1
    assert merged_inv[0].finding_id == x_nit.finding_id == y_imp.finding_id
    assert merged_inv[0].severity is Severity.IMPORTANT
