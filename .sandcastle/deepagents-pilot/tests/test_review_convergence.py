from __future__ import annotations

import itertools
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
    RoundHistoryEntry,
    RoundOutcome,
    Severity,
    VerificationVerdict,
    VerifiedFinding,
    VerifiedRound,
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
) -> tuple[FinderBatch, ...]:
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
        else _batches_for_panel(findings, panel=panel, round_number=round_number)
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
    author_reply: AuthorReply | None = None,
) -> VerifiedFinding:
    return VerifiedFinding(
        finding=finding,
        verdict=verdict,
        verifier_model=verifier_model,
        verifier_evidence=verifier_evidence,
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
    prior_ids = (
        frozenset(f.finding_id for f in history[-1].unresolved_important)
        if history and history[-1].outcome != RoundOutcome.PASS
        else frozenset()
    )
    current_findings = [vf.finding for vf in verdicts if vf.finding.finding_id not in prior_ids]
    candidates = _candidates(
        current_findings,
        round_number=round_number,
        head_sha=head_sha,
        panel=panel,
        history=history,
    )
    return VerifiedRound(candidates=candidates, verdicts=tuple(verdicts))


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
    fp1 = fingerprint("./pilot1742\\sub//a.py", "Race  Condition", "Concurrent   Write loses update")
    fp2 = fingerprint("pilot1742/sub/a.py", "race condition", "concurrent write loses update")
    fp3 = fingerprint("pilot1742/sub/b.py", "race condition", "concurrent write loses update")
    assert fp1 == fp2
    assert len(fp1) == 16
    assert all(c in "0123456789abcdef" for c in fp1)
    assert fp1 != fp3


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
        category="error  handling",
        failure_scenario="swallows   ioerror silently",
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
        category="race condition",
        failure_scenario="shared cache mutated without lock",
        evidence="第 9 行直接修改共享字典导致并发竞态丢更新",
        class_scope=None,
        source_models=("gpt-6.1-sol",),
    )
    f_nit_20 = _finding(
        severity=Severity.NIT,
        file="pilot1742/order.py",
        line=20,
        category="RACE CONDITION",
        failure_scenario="SHARED CACHE MUTATED WITHOUT LOCK",
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
        FinderBatch(model="gpt-6-astra", session_id="s1", findings=(foreign_finding,))
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=1,
            head_sha=HEAD_1,
            panel=fast_panel,
            finder_batches=(FinderBatch(model="claude-opus-5-5", session_id="s1", findings=(foreign_finding,)),),
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
        FinderBatch(model="gpt-6-astra", session_id="s1", findings=(f_same_family,))
    with pytest.raises(ConvergenceError):
        RoundCandidates(
            round_number=1,
            head_sha=HEAD_1,
            panel=DEFAULT_PANEL,
            finder_batches=(
                FinderBatch(model="claude-sonnet-4-6", session_id="s1", findings=(f_same_family,)),
                FinderBatch(model="gpt-6.1-sol", session_id="s2", findings=()),
            ),
        )

    # 候选发现仅含占位符或空 source_models 也不允许绕过异家族与面板归属检查
    f_no_source = _finding(file="a.py", category="c1", failure_scenario="s1", source_models=())
    with pytest.raises(ConvergenceError):
        FinderBatch(model="gpt-6-astra", session_id="s1", findings=(f_no_source,))
    with pytest.raises(ConvergenceError):
        RoundHistoryEntry(1, HEAD_1, frozenset({f_no_source.finding_id}), (f_no_source,))

    f_only_placeholder = _finding(file="a.py", category="c1", failure_scenario="s1", source_models=("prior-round",))
    with pytest.raises(ConvergenceError):
        FinderBatch(model="gpt-6-astra", session_id="s1", findings=(f_only_placeholder,))
    with pytest.raises(ConvergenceError):
        RoundHistoryEntry(1, HEAD_1, frozenset({f_only_placeholder.finding_id}), (f_only_placeholder,))

    # 跨轮 carry-over 时 build_round_candidates 必须完整保留原有真实 source_models，防新轮换用同家族核实者
    f_prior_from_claude = _finding(
        file="carry.py",
        category="carry",
        failure_scenario="old bug",
        source_models=("claude-opus-5-5", "kimi-k3.1-pro"),
    )
    history1 = (RoundHistoryEntry(1, HEAD_1, frozenset({f_prior_from_claude.finding_id}), (f_prior_from_claude,)),)
    plan2 = plan_next_round(BASE_SHA, HEAD_2, history1)
    empty_r2_batches = _batches_for_panel([], panel=DEFAULT_PANEL, round_number=2)
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
        finder_batches=_batches_for_panel([], panel=gemini_verifier_panel, round_number=2),
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
                FinderBatch(model="gemini-2.5-pro", session_id="s1", findings=(f_foreign,)),
                FinderBatch(model="gpt-6.1-sol", session_id="s2", findings=()),
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
        FinderBatch(model="gpt-6.1-sol", session_id="s1", findings=(f_mixed_foreign,))

    # 跨轮继承的 unresolved_prior_important 通过 history 进入 RoundCandidates.prior_important，仍强制异家族
    f_prior_kimi = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/prior_carry.py",
        line=33,
        category="跨轮遗留",
        failure_scenario="前轮由 kimi 发现的阻断缺陷",
        source_models=("kimi-k3.1-pro",),
    )
    history1 = (RoundHistoryEntry(1, HEAD_1, frozenset({f_prior_kimi.finding_id}), (f_prior_kimi,)),)
    plan2 = plan_next_round(BASE_SHA, HEAD_2, history1)
    assert plan2.prior_important_sources == {f_prior_kimi.finding_id: frozenset({"kimi-k3.1-pro"})}
    with pytest.raises(TypeError):
        plan2.prior_important_sources["tamper"] = frozenset({"gemini-2.5-pro"})  # type: ignore[index]

    r2_empty = _batches_for_panel([], panel=panel, round_number=2)
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
        RoundHistoryEntry(1, HEAD_1, frozenset({f_foreign_nit.finding_id}), (f_foreign_nit,))


def test_round_candidates_blocks_retired_model_tampering_in_new_round() -> None:
    """R5 复审反例 4：第 1 轮 gemini-2.5-pro 报 p.py:12；第 2 轮面板已无 Gemini，退役模型绝不能提交 p.py:3 篡改行号与证据。"""
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
    history1 = (RoundHistoryEntry(1, HEAD_1, frozenset({f_r1_gemini.finding_id}), (f_r1_gemini,)),)
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
                FinderBatch(model="gemini-2.5-pro", session_id="s1", findings=(f_r2_gemini_tamper,)),
                FinderBatch(model="gpt-6.1-sol", session_id="s2", findings=()),
            ),
            history=history1,
        )
    with pytest.raises(ConvergenceError):
        FinderBatch(model="gpt-6.1-sol", session_id="s1", findings=(f_r2_gemini_tamper,))

    # 2) RoundCandidates 不再接受外部直接传入 prior_important 或 current_round_findings
    with pytest.raises(TypeError):
        RoundCandidates(  # type: ignore[call-arg]
            round_number=2,
            head_sha=HEAD_2,
            panel=panel_r2,
            finder_batches=_batches_for_panel([], panel=panel_r2, round_number=2),
            prior_important=(f_r1_gemini, f_r2_gemini_tamper),
        )

    # 3) 合法保留第 1 轮未解除的 gemini-2.5-pro 发现 -> 第 2 轮行号仍为 12、证据原封不动，并可由异家族 claude 核实
    candidates_carry = build_round_candidates(
        round_number=2,
        head_sha=HEAD_2,
        panel=panel_r2,
        finder_batches=_batches_for_panel([], panel=panel_r2, round_number=2),
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
            FinderBatch(model="gpt-6.1-sol", session_id="r2-s1", findings=(f_r2_current_finder,)),
            FinderBatch(model="gpt-6.1-sol", session_id="r2-s2", findings=()),
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
    assert replies[4] == AuthorReply(None, "pilot1742/inline.py", 77, "热路径刻意避免额外拷贝", "105", "Bob")

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
        finder_batches=_batches_for_panel([], panel=DEFAULT_PANEL, round_number=2),
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
    entry1 = RoundHistoryEntry(1, HEAD_1, frozenset({f_fix.finding_id}), (f_fix,), panel=DEFAULT_PANEL)
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
        RoundHistoryEntry(1, HEAD_1, frozenset({f_imp.finding_id}), (f_imp,), panel=DEFAULT_PANEL),
        RoundHistoryEntry(2, HEAD_2, frozenset({f_imp.finding_id}), (f_imp,), panel=DEFAULT_PANEL),
        RoundHistoryEntry(3, HEAD_3, frozenset({f_imp.finding_id}), (f_imp,), panel=DEFAULT_PANEL),
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
            [RoundHistoryEntry(2, HEAD_1, frozenset(), ())],
        )


# ── 6. 幂等 PR 评论渲染、前轮 Important 不重复展开、截断保全部阻断与历史对齐 ───


def test_render_findings_comment_zero_findings_and_marker_uses_decision_round() -> None:
    entry1 = RoundHistoryEntry(1, HEAD_1, frozenset(), (), panel=DEFAULT_PANEL)
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

    entry1 = RoundHistoryEntry(1, HEAD_1, frozenset({f_prior.finding_id}), (f_prior,), panel=DEFAULT_PANEL)
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

    # FinderBatch 拒绝空 model / 空 session_id / 混合或异源 findings
    with pytest.raises(ConvergenceError):
        FinderBatch(model="   ", session_id="s1", findings=())
    with pytest.raises(ConvergenceError):
        FinderBatch(model="gpt-6-astra", session_id="", findings=())
    with pytest.raises(ConvergenceError):
        FinderBatch(model="gpt-6-astra", session_id="s1", findings=(f_other,))

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
            finder_batches=(FinderBatch(model="gpt-6-astra", session_id="s1", findings=(f_ok,)),),
        )

    # 模型多重集不匹配 -> 拒绝
    with pytest.raises(ConvergenceError):
        build_round_candidates(
            round_number=1,
            head_sha=HEAD_1,
            panel=DEFAULT_PANEL,
            finder_batches=(
                FinderBatch(model="gpt-6-astra", session_id="s1", findings=()),
                FinderBatch(model="gpt-6-astra", session_id="s2", findings=()),
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
                FinderBatch(model="gpt-6.1-sol", session_id="dup-session", findings=()),
                FinderBatch(model="gpt-6.1-sol", session_id="dup-session", findings=()),
            ),
        )
    ok_same_model = build_round_candidates(
        round_number=1,
        head_sha=HEAD_1,
        panel=same_model_panel,
        finder_batches=(
            FinderBatch(model="gpt-6.1-sol", session_id="sess-a", findings=(f_other,)),
            FinderBatch(model="gpt-6.1-sol", session_id="sess-b", findings=()),
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
    pass_entry = RoundHistoryEntry(1, HEAD_1, frozenset(), (), panel=DEFAULT_PANEL, outcome=RoundOutcome.PASS)
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
        RoundHistoryEntry(1, HEAD_1, frozenset({f_foreign.finding_id}), (f_foreign,), panel=DEFAULT_PANEL)


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
        finder_batches=_batches_for_panel([f_a], round_number=1),
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
        finder_batches=_batches_for_panel([], round_number=2),
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
        finder_batches=_batches_for_panel([f_c], round_number=3),
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
    entry1 = RoundHistoryEntry(1, HEAD_1, frozenset({f_r1.finding_id}), (f_r1,), panel=DEFAULT_PANEL)

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
            FinderBatch(model="gpt-6-astra", session_id="r2-s1", findings=()),
            FinderBatch(model="gpt-6.1-sol", session_id="r2-s2", findings=(f_r2,)),
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

    # 同评论内针对同一 target_finding_id 的重复相同指令去重；冲突不同理由指令拒收歧义
    dup_same = parse_wontfix_replies(
        [{"id": 9, "author": "alice", "body": f"[{f_a.finding_id}] 不修：同理由\n[{f_a.finding_id}] 不修：同理由"}],
        allowed_authors={"alice"},
    )
    assert len(dup_same) == 1
    conflict_diff = parse_wontfix_replies(
        [{"id": 10, "author": "alice", "body": f"[{f_a.finding_id}] 不修：理由甲\n[{f_a.finding_id}] 不修：理由乙"}],
        allowed_authors={"alice"},
    )
    assert conflict_diff == ()


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
