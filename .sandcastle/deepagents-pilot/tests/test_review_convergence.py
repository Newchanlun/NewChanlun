from __future__ import annotations

import itertools

import pytest

from pilot1742.review_convergence import (
    COMMENT_MARKER_PREFIX,
    MAX_AUTO_ROUNDS,
    NON_CONVERGENT_DESCRIPTION,
    AuthorReply,
    ConvergenceError,
    Finding,
    RenderedComment,
    ReviewPanel,
    RoundHistoryEntry,
    Severity,
    VerificationVerdict,
    VerifiedFinding,
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
    accepted = accept_quick_pass_findings(fast_panel, [f_imp])
    assert len(accepted) == 1
    assert accepted[0].verdict is VerificationVerdict.CONFIRMED
    assert accepted[0].is_blocking is True
    assert accepted[0].verifier_model == "quick-pass:gpt-6-astra"

    # require_verifier=True 的面板禁止走快审直通入口
    with pytest.raises(ConvergenceError):
        accept_quick_pass_findings(DEFAULT_PANEL, [f_imp])

    # 快审发现来源不在 panel.finder_models 中 -> 拒绝
    foreign_finding = _finding(source_models=("claude-opus-5-5",))
    with pytest.raises(ConvergenceError):
        accept_quick_pass_findings(fast_panel, [foreign_finding])

    # require_verifier=False 的面板禁止混入 parse_verifier_output
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {"verdicts": [{"finding_id": f_imp.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
            [f_imp],
            panel=fast_panel,
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

    payload = {
        "verdicts": [
            {"finding_id": f_nit.finding_id, "verdict": "confirmed", "verifier_evidence": "b.py 确实命名不一致"},
            {"finding_id": f_imp.finding_id, "verdict": "confirmed", "verifier_evidence": "a.py 确实触发异常"},
            {"finding_id": f_pre.finding_id, "verdict": "confirmed", "verifier_evidence": "c.py 历史遗留"},
        ]
    }
    verified = parse_verifier_output(
        payload,
        [f_imp, f_nit, f_pre],
        panel=DEFAULT_PANEL,
        verifier_model="claude-opus-5-5",
    )
    assert [v.finding.finding_id for v in verified] == [f_imp.finding_id, f_nit.finding_id, f_pre.finding_id]
    assert is_blocking_finding(verified[0]) is True
    assert is_blocking_finding(verified[1]) is False
    assert is_blocking_finding(verified[2]) is False


def test_parse_verifier_output_rejects_same_family_candidate_and_mismatched_panel_verifier() -> None:
    # 即使 panel 本身合法，若某个候选发现实际来自与 verifier 同家族的模型，必须拒收
    f_same_family = _finding(
        file="a.py",
        category="c1",
        failure_scenario="s1",
        source_models=("claude-sonnet-4-6",),
    )
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {"verdicts": [{"finding_id": f_same_family.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
            [f_same_family],
            panel=DEFAULT_PANEL,
            verifier_model="claude-opus-5-5",
        )

    # 候选发现仅含占位符或空 source_models 也不允许绕过异家族检查
    f_no_source = _finding(file="a.py", category="c1", failure_scenario="s1", source_models=())
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {"verdicts": [{"finding_id": f_no_source.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
            [f_no_source],
            panel=DEFAULT_PANEL,
            verifier_model="claude-opus-5-5",
        )
    f_only_placeholder = _finding(file="a.py", category="c1", failure_scenario="s1", source_models=("prior-round",))
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {"verdicts": [{"finding_id": f_only_placeholder.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
            [f_only_placeholder],
            panel=DEFAULT_PANEL,
            verifier_model="claude-opus-5-5",
        )

    # 跨轮 carry-over 时 build_round_candidates 必须完整保留原有真实 source_models，防新轮换用同家族核实者
    f_prior_from_claude = _finding(
        file="carry.py",
        category="carry",
        failure_scenario="old bug",
        source_models=("claude-opus-5-5", "kimi-k3.1-pro"),
    )
    plan2 = plan_next_round(
        BASE_SHA,
        HEAD_2,
        [RoundHistoryEntry(1, HEAD_1, frozenset({f_prior_from_claude.finding_id}), (f_prior_from_claude,))],
    )
    candidates2 = build_round_candidates(plan2, [])
    assert candidates2[0].source_models == ("claude-opus-5-5", "kimi-k3.1-pro")
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {"verdicts": [{"finding_id": f_prior_from_claude.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
            candidates2,
            panel=DEFAULT_PANEL,
            verifier_model="claude-opus-5-5",
        )

    # verifier_model 与 panel.verifier_model 不一致 -> 拒收
    f_ok = _finding(source_models=("gpt-6-astra",))
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {"verdicts": [{"finding_id": f_ok.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
            [f_ok],
            panel=DEFAULT_PANEL,
            verifier_model="gemini-4-neon",
        )


def test_parse_verifier_output_binds_candidate_sources_to_panel_and_allows_prior_important() -> None:
    panel = ReviewPanel(
        finder_models=("gpt-6.1-sol", "gpt-6.1-sol"),
        verifier_model="claude-opus-5-5",
        require_verifier=True,
    )

    # 复审反例：面板为双 gpt-6.1-sol + claude-opus-5-5，面板外 gemini-2.5-pro 候选必须立即拒绝
    f_foreign = _finding(
        file="pilot1742/foreign.py",
        line=12,
        category="面板外来源",
        failure_scenario="来源模型不在当前审查面板 finder_models 中",
        source_models=("gemini-2.5-pro",),
    )
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {"verdicts": [{"finding_id": f_foreign.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
            [f_foreign],
            panel=panel,
            verifier_model="claude-opus-5-5",
        )

    # 混合来源（含面板外模型）同样必须拒绝
    f_mixed_foreign = _finding(
        file="pilot1742/mixed.py",
        line=18,
        category="混合来源",
        failure_scenario="含面板外来源模型",
        source_models=("gpt-6.1-sol", "gemini-2.5-pro"),
    )
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {
                "verdicts": [
                    {"finding_id": f_mixed_foreign.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}
                ]
            },
            [f_mixed_foreign],
            panel=panel,
            verifier_model="claude-opus-5-5",
        )

    # 跨轮继承的 unresolved_prior_important 可通过显式 prior_important_ids 放行其历史 finder 模型，但仍强制异家族
    f_prior_kimi = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/prior_carry.py",
        line=33,
        category="跨轮遗留",
        failure_scenario="前轮由 kimi 发现的阻断缺陷",
        source_models=("kimi-k3.1-pro",),
    )
    plan2 = plan_next_round(
        BASE_SHA,
        HEAD_2,
        [RoundHistoryEntry(1, HEAD_1, frozenset({f_prior_kimi.finding_id}), (f_prior_kimi,))],
    )
    candidates2 = build_round_candidates(plan2, [])
    # 未显式传 prior_important_ids 时仍拒绝
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {"verdicts": [{"finding_id": f_prior_kimi.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
            candidates2,
            panel=panel,
            verifier_model="claude-opus-5-5",
        )
    # 显式传入 plan2.prior_important_ids 且 verifier 异家族 -> 放行
    verified_prior = parse_verifier_output(
        {"verdicts": [{"finding_id": f_prior_kimi.finding_id, "verdict": "confirmed", "verifier_evidence": "仍存在"}]},
        candidates2,
        panel=panel,
        verifier_model="claude-opus-5-5",
        prior_important_ids=plan2.prior_important_ids,
    )
    assert len(verified_prior) == 1
    assert verified_prior[0].finding.finding_id == f_prior_kimi.finding_id

    # 若 verifier 与历史 finder 同家族，即便在 prior_important_ids 中也必须拒收
    kimi_verifier_panel = ReviewPanel(
        finder_models=("gpt-6.1-sol", "gpt-6.1-sol"),
        verifier_model="kimi-k3.1-pro",
        require_verifier=True,
    )
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {"verdicts": [{"finding_id": f_prior_kimi.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
            candidates2,
            panel=kimi_verifier_panel,
            verifier_model="kimi-k3.1-pro",
            prior_important_ids=plan2.prior_important_ids,
        )

    # 非 Important 发现不得借 prior_important_ids 放行面板外模型
    f_foreign_nit = _finding(
        severity=Severity.NIT,
        file="pilot1742/foreign_nit.py",
        line=5,
        category="面板外 Nit",
        failure_scenario="非阻断项不得走 prior_important_ids",
        source_models=("gemini-2.5-pro",),
    )
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {"verdicts": [{"finding_id": f_foreign_nit.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
            [f_foreign_nit],
            panel=panel,
            verifier_model="claude-opus-5-5",
            prior_important_ids=frozenset({f_foreign_nit.finding_id}),
        )


def test_parse_verifier_output_rejects_invented_missing_duplicate_or_empty_evidence() -> None:
    f1 = _finding(file="a.py", category="c1", failure_scenario="s1")
    f2 = _finding(file="b.py", category="c2", failure_scenario="s2")

    # 引入候选外的新发现
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {
                "verdicts": [
                    {"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"},
                    {"finding_id": "deadbeef12345678", "verdict": "confirmed", "verifier_evidence": "新问题"},
                ]
            },
            [f1],
            panel=DEFAULT_PANEL,
            verifier_model="claude-opus-5-5",
        )

    # 漏判候选
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {"verdicts": [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
            [f1, f2],
            panel=DEFAULT_PANEL,
            verifier_model="claude-opus-5-5",
        )

    # 重复裁决
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {
                "verdicts": [
                    {"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "ok1"},
                    {"finding_id": f1.finding_id, "verdict": "rejected", "verifier_evidence": "ok2"},
                ]
            },
            [f1],
            panel=DEFAULT_PANEL,
            verifier_model="claude-opus-5-5",
        )

    # 空核实证据
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {"verdicts": [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "   "}]},
            [f1],
            panel=DEFAULT_PANEL,
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
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {
                "verdicts": [
                    {
                        "finding_id": f_imp.finding_id,
                        "verdict": "resolved_by_wontfix",
                        "verifier_evidence": "无回复强行放行",
                    }
                ]
            },
            [f_imp],
            panel=DEFAULT_PANEL,
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
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {
                "verdicts": [
                    {
                        "finding_id": f_imp.finding_id,
                        "verdict": "resolved_by_wontfix",
                        "verifier_evidence": "试图用无 comment_id 评论放行",
                    }
                ]
            },
            [f_imp],
            panel=DEFAULT_PANEL,
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
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {
                "verdicts": [
                    {"finding_id": f_a1.finding_id, "verdict": "resolved_by_wontfix", "verifier_evidence": "ok"},
                    {"finding_id": f_a2.finding_id, "verdict": "confirmed", "verifier_evidence": "still broken"},
                ]
            },
            [f_a1, f_a2],
            panel=DEFAULT_PANEL,
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
        plan1.round_number,
        [_verified(f_imp, VerificationVerdict.CONFIRMED), _verified(f_nit, VerificationVerdict.CONFIRMED)],
        already_posted=plan1.already_posted_fingerprints,
    )
    rendered1 = render_findings_comment(1928, HEAD_1, dec1)
    assert dec1.outcome == "blocked"
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
    candidates2 = build_round_candidates(plan2, [])
    verified2 = parse_verifier_output(
        {
            "verdicts": [
                {
                    "finding_id": f_imp.finding_id,
                    "verdict": "resolved_by_wontfix",
                    "verifier_evidence": "核实旧入口确实校验了空值",
                }
            ]
        },
        candidates2,
        panel=DEFAULT_PANEL,
        verifier_model="claude-opus-5-5",
        author_replies=plan2.author_replies,
        consumed_reply_keys=plan2.consumed_reply_keys,
        prior_important_ids=plan2.prior_important_ids,
    )
    dec2 = evaluate_round(
        plan2.round_number,
        verified2,
        already_posted=plan2.already_posted_fingerprints,
        author_replies=plan2.author_replies,
    )
    rendered2 = render_findings_comment(1928, HEAD_2, dec2)
    entry2 = dec2.to_history_entry(HEAD_2, rendered=rendered2)
    assert dec2.outcome == "pass"
    assert f_imp.finding_id in entry2.resolved_fingerprints
    assert replies_r2[0].reply_key in entry2.consumed_reply_keys
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

    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {
                "verdicts": [
                    {
                        "finding_id": f_imp.finding_id,
                        "verdict": "resolved_by_wontfix",
                        "verifier_evidence": "试图复用第 2 轮旧回复解除重开问题",
                    }
                ]
            },
            [f_imp],
            panel=DEFAULT_PANEL,
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
        {
            "verdicts": [
                {
                    "finding_id": f_imp.finding_id,
                    "verdict": "resolved_by_wontfix",
                    "verifier_evidence": "核实新回复理由成立",
                }
            ]
        },
        [f_imp],
        panel=DEFAULT_PANEL,
        verifier_model="claude-opus-5-5",
        author_replies=plan3_with_new.author_replies,
        consumed_reply_keys=plan3_with_new.consumed_reply_keys,
    )
    assert verified3[0].author_reply is not None
    assert verified3[0].author_reply.comment_id == "501"

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
    dec1 = evaluate_round(plan1.round_number, [_verified(f_imp, VerificationVerdict.CONFIRMED)])
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
    candidates2 = build_round_candidates(plan2, [])
    verified2 = parse_verifier_output(
        {
            "verdicts": [
                {
                    "finding_id": f_imp.finding_id,
                    "verdict": "resolved_by_wontfix",
                    "verifier_evidence": "核实 102 理由成立",
                }
            ]
        },
        candidates2,
        panel=DEFAULT_PANEL,
        verifier_model="claude-opus-5-5",
        author_replies=plan2.author_replies,
        consumed_reply_keys=plan2.consumed_reply_keys,
        prior_important_ids=plan2.prior_important_ids,
    )
    assert verified2[0].author_reply is not None
    assert verified2[0].author_reply.comment_id == "102"

    # 即使 evaluate_round 未额外重传 author_replies，也能通过 VerifiedFinding.related_reply_keys 消费 101 与 102
    dec2 = evaluate_round(plan2.round_number, verified2, already_posted=plan2.already_posted_fingerprints)
    rendered2 = render_findings_comment(1928, HEAD_2, dec2)
    entry2 = dec2.to_history_entry(HEAD_2, rendered=rendered2)
    assert replies_r2[0].reply_key in entry2.consumed_reply_keys
    assert replies_r2[1].reply_key in entry2.consumed_reply_keys
    history.append(entry2)

    # 第 3 轮重开仍传入 [101, 102] -> 两条均已消费，绝不能放行
    plan3 = plan_next_round(BASE_SHA, HEAD_3, history, author_replies=replies_r2)
    assert plan3.author_replies == ()
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {
                "verdicts": [
                    {
                        "finding_id": f_imp.finding_id,
                        "verdict": "resolved_by_wontfix",
                        "verifier_evidence": "试图用未选中的旧评论 101 绕过门禁",
                    }
                ]
            },
            [f_imp],
            panel=DEFAULT_PANEL,
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
        {
            "verdicts": [
                {
                    "finding_id": f_imp.finding_id,
                    "verdict": "resolved_by_wontfix",
                    "verifier_evidence": "核实 103 理由成立",
                }
            ]
        },
        [f_imp],
        panel=DEFAULT_PANEL,
        verifier_model="claude-opus-5-5",
        author_replies=plan3_new.author_replies,
        consumed_reply_keys=plan3_new.consumed_reply_keys,
    )
    assert verified3[0].author_reply is not None
    assert verified3[0].author_reply.comment_id == "103"


def test_resolved_by_fix_and_rejected_also_consume_matching_replies() -> None:
    f_fix = _finding(file="fix.py", line=10, category="c1", failure_scenario="s1")
    f_rej = _finding(file="rej.py", line=20, category="c2", failure_scenario="s2")
    comments = [
        {"id": 201, "user": {"login": "alice", "type": "User"}, "body": f"[{f_fix.finding_id}] 不修：先写过不修但后来修了"},
        {"id": 202, "user": {"login": "alice", "type": "User"}, "body": f"[{f_rej.finding_id}] 不修：先写过不修但后来被驳回"},
    ]
    replies = parse_wontfix_replies(comments, allowed_authors={"alice"})
    verified = parse_verifier_output(
        {
            "verdicts": [
                {"finding_id": f_fix.finding_id, "verdict": "resolved_by_fix", "verifier_evidence": "已修复"},
                {"finding_id": f_rej.finding_id, "verdict": "rejected", "verifier_evidence": "误报驳回"},
            ]
        },
        [f_fix, f_rej],
        panel=DEFAULT_PANEL,
        verifier_model="claude-opus-5-5",
        author_replies=replies,
    )
    dec = evaluate_round(2, verified, already_posted=frozenset({f_fix.finding_id, f_rej.finding_id}))
    assert replies[0].reply_key in dec.consumed_reply_keys
    assert replies[1].reply_key in dec.consumed_reply_keys


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
    dec1 = evaluate_round(1, [_verified(f_imp, VerificationVerdict.CONFIRMED, verifier_evidence="R1 初次核实证据")])
    rendered1 = render_findings_comment(1928, HEAD_1, dec1)
    entry1 = dec1.to_history_entry(HEAD_1, rendered=rendered1)
    assert f_imp.finding_id in entry1.posted_fingerprints

    # 第 2 轮：rejected -> 移出活跃已贴集合
    plan2 = plan_next_round(BASE_SHA, HEAD_2, [entry1])
    assert f_imp.finding_id in plan2.already_posted_fingerprints
    dec2 = evaluate_round(
        plan2.round_number,
        [_verified(f_imp, VerificationVerdict.REJECTED, verifier_evidence="R2 核实认为上游已保护")],
        already_posted=plan2.already_posted_fingerprints,
    )
    rendered2 = render_findings_comment(1928, HEAD_2, dec2)
    entry2 = dec2.to_history_entry(HEAD_2, rendered=rendered2)
    assert f_imp.finding_id in entry2.rejected_fingerprints
    assert f_imp.finding_id not in entry2.posted_fingerprints

    # 第 3 轮：再次 confirmed -> 完整贴出最新证据，不出现“前轮已贴出且仍未解除”
    plan3 = plan_next_round(BASE_SHA, HEAD_3, [entry1, entry2])
    assert f_imp.finding_id not in plan3.already_posted_fingerprints
    dec3 = evaluate_round(
        plan3.round_number,
        [_verified(f_imp, VerificationVerdict.CONFIRMED, verifier_evidence="R3 最新核实证据_UNIQUE_R3")],
        already_posted=plan3.already_posted_fingerprints,
    )
    assert [vf.finding.finding_id for vf in dec3.postable_findings] == [f_imp.finding_id]
    rendered3 = render_findings_comment(1928, HEAD_3, dec3)
    assert "重新确认后的最新失败场景_R3_SCENARIO" in rendered3.body
    assert "R3 最新核实证据_UNIQUE_R3" in rendered3.body
    assert "前轮已贴出且仍未解除" not in rendered3.body


def test_round_4_non_convergent_fails_closed_and_stops_auto_rereview() -> None:
    f_imp = _finding(severity=Severity.IMPORTANT)
    history = [
        RoundHistoryEntry(1, HEAD_1, frozenset({f_imp.finding_id}), (f_imp,)),
        RoundHistoryEntry(2, HEAD_2, frozenset({f_imp.finding_id}), (f_imp,)),
        RoundHistoryEntry(3, HEAD_3, frozenset({f_imp.finding_id}), (f_imp,)),
    ]
    assert MAX_AUTO_ROUNDS == 3

    plan4 = plan_next_round(BASE_SHA, HEAD_4, history)
    assert plan4.round_number == 4
    assert plan4.review_scope == "incremental_diff"
    assert plan4.diff_base_sha == HEAD_3
    assert plan4.exceeds_auto_rounds is True

    dec4_fail = evaluate_round(
        plan4.round_number,
        [_verified(f_imp, VerificationVerdict.CONFIRMED)],
        already_posted=plan4.already_posted_fingerprints,
    )
    assert dec4_fail.outcome == "non_convergent"
    assert dec4_fail.github_state == "failure"
    assert dec4_fail.description == NON_CONVERGENT_DESCRIPTION
    assert dec4_fail.stop_auto_rereview is True
    assert dec4_fail.postable_findings == ()

    reply = AuthorReply(f_imp.finding_id, None, None, "外层锁已保护该不变量", "200", "alice")
    dec4_pass = evaluate_round(
        plan4.round_number,
        [_verified(f_imp, VerificationVerdict.RESOLVED_BY_WONTFIX, verifier_evidence="核实外层持锁成立", author_reply=reply)],
        already_posted=plan4.already_posted_fingerprints,
    )
    assert dec4_pass.outcome == "pass"
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
    dec = evaluate_round(2, [])
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

    dec2 = evaluate_round(
        2,
        [
            _verified(f_prior, VerificationVerdict.CONFIRMED, verifier_evidence="前轮核实证据_UNIQUE_PRIOR_EVIDENCE"),
            _verified(f_new, VerificationVerdict.CONFIRMED, verifier_evidence="本轮核实证据_UNIQUE_NEW_EVIDENCE"),
        ],
        already_posted=frozenset({f_prior.finding_id}),
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
    f_fixed = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/old.py",
        line=3,
        category="旧缺陷",
        failure_scenario="旧问题已修复",
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

    dec = evaluate_round(
        1,
        [
            _verified(f_imp, VerificationVerdict.CONFIRMED, verifier_evidence="核实第 88 行确实未验签"),
            _verified(f_nit_small, VerificationVerdict.CONFIRMED, verifier_evidence="短核实证据"),
            _verified(f_pre_huge, VerificationVerdict.CONFIRMED, verifier_evidence="B" * 600),
            _verified(f_fixed, VerificationVerdict.RESOLVED_BY_FIX, verifier_evidence="已修复"),
            _verified(f_rejected, VerificationVerdict.REJECTED, verifier_evidence="代码已有前置校验"),
        ],
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
        plan2.round_number,
        [_verified(f_imp, VerificationVerdict.RESOLVED_BY_FIX, verifier_evidence="第 2 轮已补验签")],
        already_posted=plan2.already_posted_fingerprints,
        pending_non_blocking=plan2.pending_non_blocking,
    )
    assert dec2.outcome == "pass"
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
        1,
        [
            _verified(f_imp, VerificationVerdict.CONFIRMED, verifier_evidence="核实 a.py:10 确有缺陷"),
            _verified(f_huge_nit, VerificationVerdict.CONFIRMED, verifier_evidence="E" * 70_000),
        ],
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
        1,
        [_verified(f, VerificationVerdict.CONFIRMED, verifier_evidence="V" * 120) for f in blockers],
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
