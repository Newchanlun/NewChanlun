from __future__ import annotations

import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from approval_signing.protocol import ApprovalRequest, CommitTarget, Decision, Scope
from signing_fixture import Signer

from pilot1742.approval import REPOSITORY_ID, SIGN_COMMAND, SignedApprovals
from pilot1742.review_risk import (
    DEFAULT_POLICY_PATH,
    MANDATORY_HIGH_RISK_PATTERNS,
    SCHEMA_VERSION,
    ReviewDepth,
    RiskAssessment,
    RiskPolicy,
    RiskPolicyError,
    RiskTier,
    assess_diff,
    classify_paths,
    evaluate_high_risk_approval,
    extract_diff_paths,
    load_policy,
    match_glob,
)

HEAD_A = "a" * 40
HEAD_B = "b" * 40
NOW = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _init_repo(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "RiskTester")
    _git(root, "config", "user.email", "risk-tester@example.invalid")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    return _git(root, "rev-parse", "HEAD")


def test_default_policy_loads_cleanly() -> None:
    policy = load_policy()
    assert DEFAULT_POLICY_PATH.exists()
    assert policy.schema_version == SCHEMA_VERSION
    assert set(policy.high_risk_categories) == {"live_trading_and_funds", "secrets_and_credentials"}
    for mandatory in MANDATORY_HIGH_RISK_PATTERNS:
        assert mandatory in policy.high_risk_categories["secrets_and_credentials"]


@pytest.mark.parametrize(
    ("path", "expected_category"),
    [
        ("rust/src/bin/x_execution_session.rs", "live_trading_and_funds"),
        ("rust/src/economic_session/runner.rs", "live_trading_and_funds"),
        ("rust/src/theta_v0/nautilus/adapter/bridge.rs", "live_trading_and_funds"),
        ("rust/src/theta_v0/venue_fee/calc.rs", "live_trading_and_funds"),
        ("trading_system/execution/router.py", "live_trading_and_funds"),
        ("trading_system/live/ibkr_client.py", "live_trading_and_funds"),
        ("trading_system/config/broker_config.py", "live_trading_and_funds"),
        (".sandcastle/approval-signing/approval_signing/decision.py", "secrets_and_credentials"),
        (".sandcastle/cliproxy-env.mts", "secrets_and_credentials"),
        (".sandcastle/cliproxy-env-prod.mts", "secrets_and_credentials"),
        (".sandcastle/deepagents-pilot/pilot1742/approval.py", "secrets_and_credentials"),
        (".sandcastle/deepagents-pilot/pilot1742/review_risk.py", "secrets_and_credentials"),
        (".sandcastle/review-risk-tiers.json", "secrets_and_credentials"),
        (".env", "secrets_and_credentials"),
        (".envrc", "secrets_and_credentials"),
        ("a/b/.env", "secrets_and_credentials"),
        ("deploy/.env", "secrets_and_credentials"),
        (".env.local", "secrets_and_credentials"),
        ("deploy/.env.production", "secrets_and_credentials"),
        ("foo.env", "secrets_and_credentials"),
        ("service.env", "secrets_and_credentials"),
        ("deploy/service.env", "secrets_and_credentials"),
        ("docs/service.envrc", "secrets_and_credentials"),
        ("docs/service.env.backup", "secrets_and_credentials"),
        ("deploy/service.env.secret", "secrets_and_credentials"),
        ("cert.pem", "secrets_and_credentials"),
        ("docs/nested/key.pem", "secrets_and_credentials"),
    ],
)
def test_high_risk_paths_require_human_approval_and_forbid_patch_reuse(
    path: str,
    expected_category: str,
) -> None:
    assessment = classify_paths([path])
    assert assessment.tier is RiskTier.HIGH
    assert assessment.review_depth is ReviewDepth.DEEP
    assert assessment.requires_human_approval is True
    assert assessment.allow_patch_reuse is False
    assert any(m.path == path and m.category == expected_category for m in assessment.matched_high_paths)


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        ".github/CODEOWNERS",
        ".sandcastle/deepagents-pilot/pilot1742/external_review.py",
        ".sandcastle/external-review-worker.mts",
        ".sandcastle/external-review-worker-v2.mts",
        "REVIEW.md",
    ],
)
def test_deep_ai_only_paths_do_not_require_human_approval(path: str) -> None:
    assessment = classify_paths([path, "docs/guide.md"])
    assert assessment.tier is RiskTier.NORMAL
    assert assessment.review_depth is ReviewDepth.DEEP
    assert assessment.requires_human_approval is False
    assert assessment.allow_patch_reuse is True
    assert any(m.path == path for m in assessment.matched_deep_paths)


def test_low_risk_paths_only_when_every_path_matches_and_not_excluded() -> None:
    low = classify_paths(
        [
            "README.md",
            "docs/notes/plan.md",
            "docs/diagram.png",
            "docs/environment.md",
            "docs/env.md",
            "docs/my_env_notes.md",
            ".chanlun/definitions/beichi.md",
        ]
    )
    assert low.tier is RiskTier.LOW
    assert low.review_depth is ReviewDepth.QUICK
    assert low.requires_human_approval is False
    assert low.allow_patch_reuse is True

    excluded = classify_paths(["docs/REVIEW.md"])
    assert excluded.tier is RiskTier.NORMAL
    assert excluded.review_depth is ReviewDepth.STANDARD
    assert excluded.requires_human_approval is False

    mixed = classify_paths(["docs/notes.md", "scripts/helper.py"])
    assert mixed.tier is RiskTier.NORMAL
    assert mixed.review_depth is ReviewDepth.STANDARD
    assert mixed.requires_human_approval is False


def test_case_variant_paths_cannot_bypass_protection_or_downgrade_to_low() -> None:
    # 保护类规则大小写不敏感：高风险与代码自保路径绝不降级
    for high_path in (
        ".sandcastle/deepagents-pilot/pilot1742/APPROVAL.PY",
        ".SANDCASTLE/REVIEW-RISK-TIERS.JSON",
        "RUST/SRC/ECONOMIC_SESSION/a.rs",
        "certs/PROD.PEM",
        "docs/SERVICE.ENVRC",
    ):
        assessment = classify_paths([high_path])
        assert assessment.tier is RiskTier.HIGH, high_path
        assert assessment.review_depth is ReviewDepth.DEEP, high_path
        assert assessment.requires_human_approval is True, high_path
        assert assessment.allow_patch_reuse is False, high_path

    # 深审路径大小写变体仍走 DEEP，不会掉进 LOW
    lower_review = classify_paths(["review.md"])
    assert lower_review.tier is RiskTier.NORMAL
    assert lower_review.review_depth is ReviewDepth.DEEP
    assert lower_review.requires_human_approval is False
    assert [m.path for m in lower_review.matched_deep_paths] == ["review.md"]

    # 低风险排除项大小写不敏感：docs/Review.MD 不可落入 LOW
    nested_review = classify_paths(["docs/Review.MD"])
    assert nested_review.tier is RiskTier.NORMAL
    assert nested_review.review_depth is ReviewDepth.STANDARD
    assert nested_review.requires_human_approval is False

    # low_risk_patterns 保持大小写敏感，非标准大小写拼写不混入 LOW
    for non_low_path in ("DOCS/diagram.png", "README.MD", ".CHANLUN/notes.txt"):
        non_low = classify_paths([non_low_path])
        assert non_low.tier is RiskTier.NORMAL, non_low_path
        assert non_low.review_depth is ReviewDepth.STANDARD, non_low_path


def test_high_risk_dominates_deep_and_low_paths() -> None:
    assessment = classify_paths(["docs/guide.md", ".github/workflows/ci.yml", "docs/secret.env"])
    assert assessment.tier is RiskTier.HIGH
    assert assessment.review_depth is ReviewDepth.DEEP
    assert assessment.requires_human_approval is True
    assert assessment.allow_patch_reuse is False
    assert [m.path for m in assessment.matched_high_paths] == ["docs/secret.env"]
    assert [m.path for m in assessment.matched_deep_paths] == [".github/workflows/ci.yml"]


def test_mandatory_self_protection_cannot_be_removed_by_tampered_config(tmp_path: Path) -> None:
    tampered = tmp_path / "tampered.json"
    tampered.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "high_risk_categories": {"only_custom": ["custom/**"]},
                "deep_ai_only_patterns": [],
                "low_risk_patterns": [".sandcastle/**"],
                "low_risk_excludes": [],
            }
        ),
        encoding="utf-8",
    )
    policy = load_policy(tampered)
    direct_policy = RiskPolicy(
        schema_version=SCHEMA_VERSION,
        high_risk_categories={},
        deep_ai_only_patterns=(),
        low_risk_patterns=(".sandcastle/**",),
        low_risk_excludes=(),
    )

    protected_samples = [
        ".sandcastle/review-risk-tiers.json",
        ".SANDCASTLE/REVIEW-RISK-TIERS.JSON",
        ".sandcastle/deepagents-pilot/pilot1742/review_risk.py",
        ".sandcastle/deepagents-pilot/pilot1742/approval.py",
        ".sandcastle/deepagents-pilot/pilot1742/APPROVAL.PY",
        ".sandcastle/approval-signing/approval_signing/protocol.py",
    ]
    for candidate_policy in (policy, direct_policy):
        for path in protected_samples:
            assessment = classify_paths([path], policy=candidate_policy)
            assert assessment.tier is RiskTier.HIGH
            assert assessment.requires_human_approval is True
            assert assessment.allow_patch_reuse is False


def test_posix_segment_glob_edge_cases() -> None:
    # 单段 * 绝不跨斜杠
    assert match_glob(".sandcastle/cliproxy-env-v2.mts", ".sandcastle/cliproxy-env*.mts") is True
    assert match_glob(".sandcastle/cliproxy-env/v2.mts", ".sandcastle/cliproxy-env*.mts") is False

    # ** 匹配零层或多层目录；末尾 /** 至少匹配一层且不误匹配前缀相似目录
    assert match_glob("README.md", "**/*.md") is True
    assert match_glob("a/b/c.md", "**/*.md") is True
    assert match_glob("docs/a.txt", "docs/**") is True
    assert match_glob("docs", "docs/**") is False
    assert match_glob("docs2/a.md", "docs/**") is False

    # 根目录精确匹配 vs 任意深度匹配
    assert match_glob("REVIEW.md", "REVIEW.md") is True
    assert match_glob("docs/REVIEW.md", "REVIEW.md") is False
    assert match_glob("REVIEW.md", "**/REVIEW.md") is True
    assert match_glob("docs/REVIEW.md", "**/REVIEW.md") is True

    # 文件名包含方括号不被 fnmatch 当字符集误解析
    assert match_glob("docs/[draft].md", "**/*.md") is True
    assert match_glob("docs/[draft].md", "docs/[draft].md") is True
    assert match_glob("docs/d.md", "docs/[draft].md") is False

    # case_sensitive 默认 True，显式 False 时按大小写不敏感匹配
    assert match_glob("docs/Review.MD", "**/REVIEW.md") is False
    assert match_glob("docs/Review.MD", "**/REVIEW.md", case_sensitive=False) is True
    assert match_glob("docs/service.envrc", "**/*.env*") is True
    assert match_glob("docs/environment.md", "**/*.env*") is False


def test_empty_paths_fail_closed_as_high() -> None:
    assessment = classify_paths([])
    assert assessment.tier is RiskTier.HIGH
    assert assessment.review_depth is ReviewDepth.DEEP
    assert assessment.requires_human_approval is True
    assert assessment.allow_patch_reuse is False
    assert assessment.all_paths == ()
    assert assessment.matched_high_paths == ()


@pytest.mark.parametrize(
    "bad_path",
    [
        "",
        "../secret.py",
        "docs/../.env",
        "/etc/passwd",
        "C:/secret.env",
        "docs\\guide.md",
        "docs/a\x00b.md",
        "./docs/guide.md",
        "docs//guide.md",
        "docs/",
    ],
)
def test_invalid_paths_raise_risk_policy_error(bad_path: str) -> None:
    with pytest.raises(RiskPolicyError):
        classify_paths([bad_path])


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b'{"schema_version": "review-risk-tiers/1", "schema_version": "review-risk-tiers/1"}',
        json.dumps({"schema_version": "review-risk-tiers/999"}).encode(),
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "high_risk_categories": {},
                "deep_ai_only_patterns": [],
                "low_risk_patterns": [],
                "low_risk_excludes": [],
            }
        ).encode(),
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "high_risk_categories": {"a": ["../escape.py"]},
                "deep_ai_only_patterns": [],
                "low_risk_patterns": [],
                "low_risk_excludes": [],
            }
        ).encode(),
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "high_risk_categories": {"a": ["foo**bar/x.py"]},
                "deep_ai_only_patterns": [],
                "low_risk_patterns": [],
                "low_risk_excludes": [],
            }
        ).encode(),
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "high_risk_categories": {"a": ["x.py"]},
                "deep_ai_only_patterns": [],
                "low_risk_patterns": [],
                "low_risk_excludes": [],
                "unexpected": True,
            }
        ).encode(),
    ],
)
def test_malformed_or_tampered_policy_files_fail_closed(tmp_path: Path, payload: bytes) -> None:
    cfg = tmp_path / "bad.json"
    cfg.write_bytes(payload)
    with pytest.raises(RiskPolicyError):
        load_policy(cfg)


def test_missing_policy_file_raises(tmp_path: Path) -> None:
    with pytest.raises(RiskPolicyError):
        load_policy(tmp_path / "missing.json")


def test_extract_diff_paths_rename_out_of_high_risk_and_unicode_spaces(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_sha = _init_repo(repo)

    live_file = repo / "trading_system" / "live" / "实盘 策略.py"
    live_file.parent.mkdir(parents=True, exist_ok=True)
    live_file.write_text("ORDER_SIZE = 100\n# keep content identical for rename detection\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "add live strategy")
    commit_with_live = _git(repo, "rev-parse", "HEAD")

    # 重命名高风险文件到低风险 docs/ 目录，并附带中文和空格文件名
    target_doc = repo / "docs" / "缠论 归档" / "说明 01.md"
    target_doc.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "mv", "trading_system/live/实盘 策略.py", "docs/缠论 归档/说明 01.md")
    _git(repo, "commit", "-qm", "rename live strategy into docs")
    rename_sha = _git(repo, "rev-parse", "HEAD")

    paths = extract_diff_paths(repo, commit_with_live, rename_sha)
    assert paths == ("docs/缠论 归档/说明 01.md", "trading_system/live/实盘 策略.py")

    assessment = assess_diff(repo, commit_with_live, rename_sha)
    assert assessment.tier is RiskTier.HIGH
    assert assessment.requires_human_approval is True
    assert assessment.allow_patch_reuse is False
    assert assessment.base_sha == commit_with_live
    assert assessment.head_sha == rename_sha
    assert [m.path for m in assessment.matched_high_paths] == ["trading_system/live/实盘 策略.py"]

    # 同一提交空 diff -> extract 返回空元组，assess_diff fail-closed 判 HIGH 且仍写入 SHA
    assert extract_diff_paths(repo, base_sha, base_sha) == ()
    empty_assessment = assess_diff(repo, base_sha, base_sha)
    assert empty_assessment.tier is RiskTier.HIGH
    assert empty_assessment.requires_human_approval is True
    assert empty_assessment.base_sha == base_sha
    assert empty_assessment.head_sha == base_sha

    # 复制高风险文件并修改原文件（-C 场景）：同时覆盖旧新路径
    secret_src = repo / "deploy" / "prod.env"
    secret_src.parent.mkdir(parents=True, exist_ok=True)
    secret_src.write_text("TOKEN=secret-value-for-copy-detection\nLINE2=abcdef0123456789\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "add env file")
    before_copy = _git(repo, "rev-parse", "HEAD")

    copied_doc = repo / "docs" / "copied_env.md"
    copied_doc.write_text("TOKEN=secret-value-for-copy-detection\nLINE2=abcdef0123456789\n", encoding="utf-8")
    secret_src.write_text("TOKEN=secret-value-for-copy-detection\nLINE2=abcdef0123456789\nEXTRA=1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "copy env to docs")
    after_copy = _git(repo, "rev-parse", "HEAD")
    assert extract_diff_paths(repo, before_copy, after_copy) == ("deploy/prod.env", "docs/copied_env.md")
    assert assess_diff(repo, before_copy, after_copy).tier is RiskTier.HIGH

    # 非法 SHA 与不存在的 SHA 均抛 RiskPolicyError
    with pytest.raises(RiskPolicyError):
        extract_diff_paths(repo, "--output=/tmp/pwn", rename_sha)
    with pytest.raises(RiskPolicyError):
        extract_diff_paths(repo, base_sha, "f" * 40)


def test_extract_diff_paths_detects_copy_from_untouched_high_risk_source(tmp_path: Path) -> None:
    repo = tmp_path / "repo-copy-harder"
    _init_repo(repo)

    high_src = repo / "trading_system" / "live" / "untouched_executor.py"
    high_src.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        "ACCOUNT_ID = 'DU123456'\n"
        "def submit_live_order(symbol: str, qty: int) -> str:\n"
        "    return f'{ACCOUNT_ID}:{symbol}:{qty}'\n"
    )
    high_src.write_text(payload, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "add untouched high-risk source")
    before_copy = _git(repo, "rev-parse", "HEAD")

    # 高风险源文件完全不动，仅原样复制到 docs/copied.md
    copied = repo / "docs" / "copied.md"
    copied.parent.mkdir(parents=True, exist_ok=True)
    copied.write_text(payload, encoding="utf-8")
    _git(repo, "add", "docs/copied.md")
    _git(repo, "commit", "-qm", "copy untouched high-risk file to docs")
    after_copy = _git(repo, "rev-parse", "HEAD")

    paths = extract_diff_paths(repo, before_copy, after_copy)
    assert paths == ("docs/copied.md", "trading_system/live/untouched_executor.py")

    assessment = assess_diff(repo, before_copy, after_copy)
    assert assessment.tier is RiskTier.HIGH
    assert assessment.review_depth is ReviewDepth.DEEP
    assert assessment.requires_human_approval is True
    assert assessment.allow_patch_reuse is False
    assert assessment.base_sha == before_copy
    assert assessment.head_sha == after_copy
    assert [m.path for m in assessment.matched_high_paths] == ["trading_system/live/untouched_executor.py"]


def test_low_and_normal_risk_skip_human_approval_without_writing_request(tmp_path: Path) -> None:
    desk_dir = tmp_path / "desk"
    for assessment in (
        classify_paths(["docs/guide.md"], head_sha=HEAD_A),
        classify_paths([".github/workflows/ci.yml"], head_sha=HEAD_A),
        classify_paths(["scripts/tool.py"], head_sha=HEAD_A),
    ):
        result = evaluate_high_risk_approval(
            assessment,
            pr_number=1930,
            head_sha=HEAD_A,
            desk_folder=desk_dir,
            now=NOW,
        )
        assert result.required is False
        assert result.satisfied is True
        assert result.status == "not_required"
        assert result.head_sha == HEAD_A
        assert result.request_path is None
        assert result.sign_command is None
    assert not desk_dir.exists()


def test_evaluate_high_risk_approval_requires_matching_head_sha_binding(tmp_path: Path) -> None:
    desk_dir = tmp_path / "desk"

    # 未绑定 head_sha 的评估一律拒收（无论 LOW 还是 HIGH）
    unbound_low = classify_paths(["docs/guide.md"])
    unbound_high = classify_paths(["trading_system/live/ibkr_client.py"])
    for assessment in (unbound_low, unbound_high):
        with pytest.raises(RiskPolicyError):
            evaluate_high_risk_approval(
                assessment,
                pr_number=1930,
                head_sha=HEAD_A,
                desk_folder=desk_dir,
                now=NOW,
            )

    # 拿提交 A 的 LOW 免签评估错配给提交 B -> 必须拒绝（fail-closed）
    low_a = classify_paths(["docs/guide.md"], base_sha=HEAD_B, head_sha=HEAD_A)
    with pytest.raises(RiskPolicyError):
        evaluate_high_risk_approval(
            low_a,
            pr_number=1930,
            head_sha=HEAD_B,
            desk_folder=desk_dir,
            now=NOW,
        )

    # 拿提交 A 的 HIGH 评估错配给提交 B -> 同样拒绝
    high_a = classify_paths(["trading_system/live/ibkr_client.py"], head_sha=HEAD_A)
    with pytest.raises(RiskPolicyError):
        evaluate_high_risk_approval(
            high_a,
            pr_number=1930,
            head_sha=HEAD_B,
            desk_folder=desk_dir,
            now=NOW,
        )

    assert not desk_dir.exists()


def test_high_risk_ecdsa_p256_approval_lifecycle_and_head_rotation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signer = Signer(tmp_path / "authority")
    approvals = signer.protect(monkeypatch)
    desk_dir = tmp_path / "pr 1930's approvals"
    assessment_a = classify_paths(["trading_system/execution/order_router.py"], head_sha=HEAD_A)
    assessment_b = classify_paths(["trading_system/execution/order_router.py"], head_sha=HEAD_B)

    # 1. 未签批 -> awaiting_human 且写出规范 CommitTarget 请求；sign_command 对含空格和单引号的路径做安全引用
    pending = evaluate_high_risk_approval(
        assessment_a,
        pr_number=1930,
        head_sha=HEAD_A,
        desk_folder=desk_dir,
        approvals=approvals,
        now=NOW,
    )
    assert pending.required is True
    assert pending.satisfied is False
    assert pending.status == "awaiting_human"
    assert pending.head_sha == HEAD_A
    assert pending.request_path is not None
    assert pending.sign_command == f"{SIGN_COMMAND} {shlex.quote(pending.request_path)}"
    assert shlex.split(pending.sign_command)[-1] == pending.request_path

    req_a = ApprovalRequest.parse(Path(pending.request_path).read_bytes())
    assert (req_a.repository_id, req_a.ticket, req_a.run_id, req_a.claim_generation, req_a.scope, req_a.target) == (
        REPOSITORY_ID,
        1930,
        "pr-1930-high-risk",
        1,
        Scope.CANDIDATE_HEAD,
        CommitTarget(HEAD_A),
    )

    # 2. 真实 ECDSA-P256 签批精确 head_sha -> approved
    signer.publish(pending.request_path, Decision.APPROVE)
    approved = evaluate_high_risk_approval(
        assessment_a,
        pr_number=1930,
        head_sha=HEAD_A,
        desk_folder=desk_dir,
        approvals=approvals,
        now=NOW,
    )
    assert approved.required is True
    assert approved.satisfied is True
    assert approved.status == "approved"
    assert approved.head_sha == HEAD_A
    assert approved.sign_command is None

    # 3. 推新提交换 head_sha -> 旧批准立刻失效并轮换 nonce
    rotated = evaluate_high_risk_approval(
        assessment_b,
        pr_number=1930,
        head_sha=HEAD_B,
        desk_folder=desk_dir,
        approvals=approvals,
        now=NOW,
    )
    assert rotated.required is True
    assert rotated.satisfied is False
    assert rotated.status == "awaiting_human"
    assert rotated.head_sha == HEAD_B
    assert rotated.request_path is not None
    req_b = ApprovalRequest.parse(Path(rotated.request_path).read_bytes())
    assert req_b.target == CommitTarget(HEAD_B)
    assert req_b.request_nonce != req_a.request_nonce
    assert req_a.encode() in [p.read_bytes() for p in (desk_dir / "history").iterdir()]

    # 4. 对新 head 签批后，后续 REJECT 覆盖之前的 APPROVE
    signer.publish(rotated.request_path, Decision.APPROVE)
    approved_b = evaluate_high_risk_approval(
        assessment_b,
        pr_number=1930,
        head_sha=HEAD_B,
        desk_folder=desk_dir,
        approvals=approvals,
        now=NOW,
    )
    assert approved_b.satisfied is True and approved_b.status == "approved"

    signer.publish(rotated.request_path, Decision.REJECT)
    rejected_b = evaluate_high_risk_approval(
        assessment_b,
        pr_number=1930,
        head_sha=HEAD_B,
        desk_folder=desk_dir,
        approvals=approvals,
        now=NOW,
    )
    assert rejected_b.required is True
    assert rejected_b.satisfied is False
    assert rejected_b.status == "rejected"


def test_high_risk_missing_trust_config_returns_not_configured(tmp_path: Path) -> None:
    assessment = classify_paths([".sandcastle/review-risk-tiers.json"], head_sha=HEAD_A)
    result = evaluate_high_risk_approval(
        assessment,
        pr_number=1930,
        head_sha=HEAD_A,
        desk_folder=tmp_path / "desk",
        approvals=SignedApprovals(trust_path=tmp_path / "absent-trust.json"),
        now=NOW,
    )
    assert result.required is True
    assert result.satisfied is False
    assert result.status == "not_configured"
    assert result.request_path is not None
    assert result.sign_command == f"{SIGN_COMMAND} {shlex.quote(result.request_path)}"


def test_evaluate_high_risk_approval_rejects_bad_arguments(tmp_path: Path) -> None:
    assessment = classify_paths(["docs/guide.md"], head_sha=HEAD_A)
    with pytest.raises(RiskPolicyError):
        evaluate_high_risk_approval(assessment, pr_number=0, head_sha=HEAD_A, desk_folder=tmp_path)
    with pytest.raises(RiskPolicyError):
        evaluate_high_risk_approval(assessment, pr_number=1930, head_sha="not-a-sha", desk_folder=tmp_path)
    with pytest.raises(RiskPolicyError):
        evaluate_high_risk_approval(assessment, pr_number=1930, head_sha=HEAD_A, desk_folder=tmp_path, generation=0)


def test_assessment_invariants_cannot_be_violated_manually() -> None:
    with pytest.raises(RiskPolicyError):
        RiskAssessment(
            tier=RiskTier.HIGH,
            review_depth=ReviewDepth.DEEP,
            requires_human_approval=True,
            allow_patch_reuse=True,
            matched_high_paths=(),
            matched_deep_paths=(),
            all_paths=(),
            reason="broken",
        )
    with pytest.raises(RiskPolicyError):
        RiskAssessment(
            tier=RiskTier.HIGH,
            review_depth=ReviewDepth.STANDARD,
            requires_human_approval=True,
            allow_patch_reuse=False,
            matched_high_paths=(),
            matched_deep_paths=(),
            all_paths=(),
            reason="broken",
        )
    with pytest.raises(RiskPolicyError):
        RiskAssessment(
            tier=RiskTier.LOW,
            review_depth=ReviewDepth.QUICK,
            requires_human_approval=False,
            allow_patch_reuse=True,
            matched_high_paths=(),
            matched_deep_paths=(),
            all_paths=("docs/a.md",),
            reason="bad head sha",
            head_sha="A" * 40,
        )
    with pytest.raises(RiskPolicyError):
        classify_paths(["docs/a.md"], base_sha="not-a-sha")
