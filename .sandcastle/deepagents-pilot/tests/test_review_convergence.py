from __future__ import annotations

import pytest

from pilot1742.review_convergence import (
    COMMENT_MARKER_PREFIX,
    MAX_AUTO_ROUNDS,
    NON_CONVERGENT_DESCRIPTION,
    AuthorReply,
    ConvergenceError,
    Finding,
    ReviewPanel,
    RoundHistoryEntry,
    Severity,
    VerificationVerdict,
    VerifiedFinding,
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


# ── 1. 分级、指纹与发现合并 ──────────────────────────────────────────────


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
    # 按严重度排序：Important -> Pre-existing -> Nit
    assert [f.severity for f in merged] == [Severity.IMPORTANT, Severity.PRE_EXISTING, Severity.NIT]
    top = merged[0]
    assert top.file == "pilot1742/x.py"
    assert top.line == 18
    assert top.source_models == ("gpt-6-astra", "gpt-6.1-sol")
    assert top.evidence == f_imp.evidence
    assert top.class_scope == f_imp.class_scope


def test_merge_and_dedupe_pre_existing_beats_nit() -> None:
    f_nit = _finding(severity=Severity.NIT, file="a.py", category="c", failure_scenario="s", evidence="short")
    f_pre = _finding(severity=Severity.PRE_EXISTING, file="a.py", category="c", failure_scenario="s", evidence="more detailed")
    merged = merge_and_dedupe_findings([("gpt-6-astra", [f_nit]), ("gpt-6.1-sol", [f_pre])])
    assert len(merged) == 1
    assert merged[0].severity is Severity.PRE_EXISTING


# ── 2. 模型家族与审查面板合同 ───────────────────────────────────────────


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


def test_review_panel_fast_path_allows_single_finder_without_verifier() -> None:
    fast_panel = ReviewPanel(finder_models=("gpt-6-astra",), verifier_model=None, require_verifier=False)
    assert fast_panel.verifier_family is None
    assert fast_panel.finder_families == frozenset({"openai"})

    # 快审路径若显式提供核实者，仍不得与 finder 同家族
    with pytest.raises(ConvergenceError):
        ReviewPanel(finder_models=("gpt-6-astra",), verifier_model="gpt-6.1-sol", require_verifier=False)


# ── 3. 核实者输出校验与唯一阻断判据 ──────────────────────────────────────


def test_parse_verifier_output_enforces_exact_candidate_bijection() -> None:
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
    verified = parse_verifier_output(payload, [f_imp, f_nit, f_pre], verifier_model="claude-opus-5-5")
    assert [v.finding.finding_id for v in verified] == [f_imp.finding_id, f_nit.finding_id, f_pre.finding_id]
    assert is_blocking_finding(verified[0]) is True
    assert is_blocking_finding(verified[1]) is False
    assert is_blocking_finding(verified[2]) is False


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
            verifier_model="claude-opus-5-5",
        )

    # 漏判候选
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {"verdicts": [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "ok"}]},
            [f1, f2],
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
            verifier_model="claude-opus-5-5",
        )

    # 空核实证据
    with pytest.raises(ConvergenceError):
        parse_verifier_output(
            {"verdicts": [{"finding_id": f1.finding_id, "verdict": "confirmed", "verifier_evidence": "   "}]},
            [f1],
            verifier_model="claude-opus-5-5",
        )


def test_only_confirmed_important_blocks_merge() -> None:
    f_imp = _finding(severity=Severity.IMPORTANT)
    f_nit = _finding(severity=Severity.NIT, file="n.py")
    f_pre = _finding(severity=Severity.PRE_EXISTING, file="p.py")

    assert _verified(f_imp, VerificationVerdict.CONFIRMED).is_blocking is True
    assert _verified(f_imp, VerificationVerdict.REJECTED).is_blocking is False
    assert _verified(f_imp, VerificationVerdict.RESOLVED_BY_FIX).is_blocking is False
    assert _verified(f_imp, VerificationVerdict.RESOLVED_BY_WONTFIX).is_blocking is False
    assert _verified(f_nit, VerificationVerdict.CONFIRMED).is_blocking is False
    assert _verified(f_pre, VerificationVerdict.CONFIRMED).is_blocking is False


# ── 4. 作者 `不修：<理由>` 回复解析 ──────────────────────────────────────


def test_parse_wontfix_replies_supports_all_anchor_formats_and_ignores_invalid() -> None:
    comments = [
        # 机器人自身评论必须整体忽略
        {
            "id": 100,
            "user": {"login": "review-bot"},
            "body": f"{COMMENT_MARKER_PREFIX} pr=1 round=1 head={HEAD_1} -->\n[abc12345] 不修：模板示例",
        },
        # 多种合法锚点 + 空理由/引用/代码块干扰
        {
            "id": 101,
            "user": {"login": "alice"},
            "body": "\n".join(
                [
                    "> [deadbeef] 不修：引用机器人提示，不应解析",
                    "```",
                    "[cafebabe] 不修：代码块里的示例",
                    "```",
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
            "id": 102,
            "author": "bob",
            "path": "./pilot1742/inline.py",
            "line": 77,
            "body": "不修：热路径刻意避免额外拷贝",
        },
    ]

    replies = parse_wontfix_replies(comments)
    assert len(replies) == 5
    assert replies[0] == AuthorReply("abc12345", None, None, "上层入口已保证非空", "101", "alice")
    assert replies[1] == AuthorReply("def67890", None, None, "兼容性要求保留旧行为", "101", "alice")
    assert replies[2] == AuthorReply(None, "pilot1742/foo.py", 42, "此处仅用于离线诊断", "101", "alice")
    assert replies[3] == AuthorReply(None, "pilot1742/bar.py", None, "整文件为只读测试夹具", "101", "alice")
    assert replies[4] == AuthorReply(None, "pilot1742/inline.py", 77, "热路径刻意避免额外拷贝", "102", "bob")


# ── 5. 多轮收敛状态机与不重复贴出 ────────────────────────────────────────


def test_multi_round_convergence_incremental_scope_dedupe_and_reintroduction() -> None:
    f_imp = _finding(severity=Severity.IMPORTANT, file="a.py", line=10, category="空值", failure_scenario="空指针")
    f_nit = _finding(severity=Severity.NIT, file="b.py", line=20, category="风格", failure_scenario="多余空行")

    # 第 1 轮：全 PR 审查
    plan1 = plan_next_round(BASE_SHA, HEAD_1, [])
    assert plan1.round_number == 1
    assert plan1.review_scope == "full_pr"
    assert plan1.diff_base_sha == BASE_SHA
    assert plan1.diff_head_sha == HEAD_1
    assert plan1.unresolved_prior_important == ()

    dec1 = evaluate_round(
        plan1.round_number,
        [_verified(f_imp, VerificationVerdict.CONFIRMED), _verified(f_nit, VerificationVerdict.CONFIRMED)],
        already_posted=plan1.already_posted_fingerprints,
    )
    assert dec1.outcome == "blocked"
    assert dec1.github_state == "failure"
    assert dec1.stop_auto_rereview is False
    assert {vf.finding.finding_id for vf in dec1.postable_findings} == {f_imp.finding_id, f_nit.finding_id}

    # 第 2 轮：增量 diff + 携带未解除 Important + 作者修复后解除
    history = [dec1.to_history_entry(HEAD_1)]
    plan2 = plan_next_round(BASE_SHA, HEAD_2, history)
    assert plan2.round_number == 2
    assert plan2.review_scope == "incremental_diff"
    assert plan2.diff_base_sha == HEAD_1
    assert plan2.diff_head_sha == HEAD_2
    assert plan2.unresolved_prior_important == (f_imp,)

    candidates2 = build_round_candidates(plan2, [])
    assert [f.finding_id for f in candidates2] == [f_imp.finding_id]

    dec2 = evaluate_round(
        plan2.round_number,
        [_verified(f_imp, VerificationVerdict.RESOLVED_BY_FIX, verifier_evidence="已在 HEAD_2 补齐判空")],
        already_posted=plan2.already_posted_fingerprints,
    )
    assert dec2.outcome == "pass"
    assert dec2.github_state == "success"
    assert dec2.unresolved_important == ()
    assert f_imp.finding_id not in dec2.next_posted_fingerprints
    assert f_nit.finding_id in dec2.next_posted_fingerprints

    # 第 3 轮：如果原问题被重新引入，必须允许重新贴出；仍已贴过的 Nit 不重复贴
    history.append(dec2.to_history_entry(HEAD_2))
    plan3 = plan_next_round(BASE_SHA, HEAD_3, history)
    assert f_imp.finding_id not in plan3.already_posted_fingerprints
    assert f_nit.finding_id in plan3.already_posted_fingerprints
    postable3 = select_postable_findings(
        [_verified(f_imp, VerificationVerdict.CONFIRMED), _verified(f_nit, VerificationVerdict.CONFIRMED)],
        plan3.already_posted_fingerprints,
    )
    assert [vf.finding.finding_id for vf in postable3] == [f_imp.finding_id]


def test_round_4_non_convergent_fails_closed_and_stops_auto_rereview() -> None:
    f_imp = _finding(severity=Severity.IMPORTANT)
    history = [
        RoundHistoryEntry(1, HEAD_1, frozenset({f_imp.finding_id}), (f_imp,)),
        RoundHistoryEntry(2, HEAD_2, frozenset({f_imp.finding_id}), (f_imp,)),
        RoundHistoryEntry(3, HEAD_3, frozenset({f_imp.finding_id}), (f_imp,)),
    ]
    assert MAX_AUTO_ROUNDS == 3

    # 第 4 轮仍允许核实第 3 轮后的提交
    plan4 = plan_next_round(BASE_SHA, HEAD_4, history)
    assert plan4.round_number == 4
    assert plan4.review_scope == "incremental_diff"
    assert plan4.diff_base_sha == HEAD_3
    assert plan4.exceeds_auto_rounds is True

    # 仍有未解除 Important -> 绝不自动 PASS
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

    # 若第 4 轮核实为全部通过（例如作者 `不修：<理由>` 获核实采信），仍可正常 PASS
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


# ── 6. 幂等 PR 评论渲染与截断保护 ────────────────────────────────────────


def test_render_findings_comment_zero_findings_and_idempotency() -> None:
    dec = evaluate_round(1, [])
    c1 = render_findings_comment(1928, 1, HEAD_1, dec)
    c2 = render_findings_comment(1928, 1, HEAD_1, dec)
    assert c1 == c2
    lines = c1.splitlines()
    assert lines[0] == f"{COMMENT_MARKER_PREFIX} pr=1928 round=1 head={HEAD_1} -->"
    assert parse_comment_marker(c1) == (1928, 1, HEAD_1)
    assert lines[1].startswith("0 项 Important，0 项 Nit，0 项 Pre-existing")
    assert "无需要修复的问题" in lines[1]


def test_render_findings_comment_includes_all_sections_and_truncates_safely() -> None:
    f_imp = _finding(
        severity=Severity.IMPORTANT,
        file="pilot1742/core.py",
        line=88,
        category="状态机越权",
        failure_scenario="未校验签名直接发布状态",
        evidence="core.py:88 跳过验签",
        class_scope="发布路径共 2 处同类入口",
    )
    f_nit = _finding(
        severity=Severity.NIT,
        file="pilot1742/style.py",
        line=12,
        category="日志措辞",
        failure_scenario="缺少上下文编号",
        evidence="style.py:12 仅打印了短消息",
    )
    f_pre = _finding(
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
            _verified(f_nit, VerificationVerdict.CONFIRMED, verifier_evidence="A" * 600),
            _verified(f_pre, VerificationVerdict.CONFIRMED, verifier_evidence="B" * 600),
            _verified(f_fixed, VerificationVerdict.RESOLVED_BY_FIX, verifier_evidence="已修复"),
            _verified(f_rejected, VerificationVerdict.REJECTED, verifier_evidence="代码已有前置校验"),
        ],
    )

    full = render_findings_comment(1928, 1, HEAD_1, dec)
    lines = full.splitlines()
    assert lines[0] == f"{COMMENT_MARKER_PREFIX} pr=1928 round=1 head={HEAD_1} -->"
    assert lines[1] == "1 项 Important，1 项 Nit，1 项 Pre-existing"
    assert f_imp.finding_id in full
    assert "pilot1742/core.py:88" in full
    assert "发布路径共 2 处同类入口" in full
    assert f"[{f_imp.finding_id}] 不修：<理由>" in full
    assert "### 非阻断项（Nit / Pre-existing）" in full
    assert "### 已解除与核实驳回摘要" in full

    # 严格截断时，必须保留 marker、首行计数摘要与阻断项，且长度 <= max_chars
    truncated = render_findings_comment(1928, 1, HEAD_1, dec, max_chars=520)
    assert len(truncated) <= 520
    t_lines = truncated.splitlines()
    assert t_lines[0] == f"{COMMENT_MARKER_PREFIX} pr=1928 round=1 head={HEAD_1} -->"
    assert t_lines[1] == "1 项 Important，1 项 Nit，1 项 Pre-existing"
    assert f_imp.finding_id in truncated
    assert "未校验签名直接发布状态" in truncated
