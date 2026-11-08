"""#1984：本 PR 改过的每个文件都不得再写「合入 main 要等人」。

口径以 #1742 裁定为准（https://github.com/Newchanlun/NewChanlun/issues/1742#issuecomment-6719202631）：
合入 main 不设人工批准步骤，由分支保护的必需检查 deepagents/review 与 ci-ok 把关；
人确认只剩实盘下单/资金与密钥/凭证两类。代码里的单一来源是 pilot1742/domain.py 的 MERGE_GATE。

FILES 是 #1984 改过、仍存在的文本文件。不在这里的文件（.sandcastle/docs/graph-engineering.md、harvest.sh、
docs/agents/wayfinder-workflow.md、review_sweep.py 等）归 #1915 那组 PR 迁移，本测试不管。
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

FILES = (
    ".chanlun/manifest.yaml",
    ".claude/commands/refactor-clean.md",
    ".claude/commands/verify.md",
    ".github/workflows/ci.yml",
    ".sandcastle/CODING_STANDARDS.md",
    ".sandcastle/codex-implement-prompt.md",
    ".sandcastle/codex-review-prompt.md",
    ".sandcastle/deepagents-pilot/EXECUTOR.md",
    ".sandcastle/deepagents-pilot/EXTERNAL-REVIEW.md",
    ".sandcastle/deepagents-pilot/pilot1742/agent.py",
    ".sandcastle/deepagents-pilot/pilot1742/domain.py",
    ".sandcastle/deepagents-pilot/pilot1742/executor.py",
    ".sandcastle/deepagents-pilot/pilot1742/external_review.py",
    ".sandcastle/deepagents-pilot/tests/test_executor.py",
    ".sandcastle/swarm-implement-prompt.md",
    "CLAUDE.md",
    "docs/agents/deepagents-queue/README.md",
    "scripts/wayfinder_engine.mts",
)

# 只抓「合入」与「人」挨在一起的说法；「人闸标签」（票面挂起标签）这类与合入无关的词不算。
HUMAN_MERGE = (
    re.compile(r"合入[^。；\n]{0,20}?(人工闸|人闸|由人|人决定|人批|等人|人来)"),
    re.compile(r"(人工闸|人闸|人决定|人批|等待人|等人|由人)[^。；\n]{0,6}合入"),
    re.compile(r"闸二|人只守三闸"),
    re.compile(r"merg\w*[^.\n]{0,40}\bhuman[- ](gate|decision|approval|merge)", re.I),
    re.compile(r"\bhuman[- ]gate\b[^.\n]{0,40}merg", re.I),
)


def human_merge_lines(text: str) -> list[tuple[int, str]]:
    return [(n, line.strip()) for n, line in enumerate(text.splitlines(), 1)
            if any(p.search(line) for p in HUMAN_MERGE)]


@pytest.mark.parametrize("path", FILES)
def test_pr_files_do_not_say_a_human_merges_main(path):
    hits = human_merge_lines((REPO / path).read_text(encoding="utf-8"))
    assert not hits, f"{path} 仍写人工合入（改用 MERGE_GATE 口径，见 #1742 裁定）：{hits}"


@pytest.mark.parametrize("line", [
    "- **不关 issue、不 merge、不 push、不动 main**——验收与合入是编排层人工闸。",
    "人只守三闸：spec 批准、P 类决策、合入 main。",
    "（本提交由 wayfinder_engine 自动起草；合入 main 为人工闸【闸二】，本引擎不碰。）",
    "交付冻结 head `abc` 到 `codex/deepagents/t1`，PR https://x，等待人合入。",
    "合入 main 由人决定。",
    "merging is the human gate",
])
def test_detector_catches_known_human_merge_sentences(line):
    assert human_merge_lines(line)


@pytest.mark.parametrize("line", [
    "拒绝 `sandcastle`、`agent:*`、`wayfinder:grilling`、所有人闸标签、有负责人",
    "合入 main 不设人工批准步骤，由必需检查 `deepagents/review` 与 `ci-ok` 把关；涉及实盘下单/资金或密钥/凭证的改动仍须人确认。",
])
def test_detector_ignores_unrelated_human_gates(line):
    assert not human_merge_lines(line)


def test_merge_gate_constant_names_both_required_checks():
    from pilot1742.domain import MERGE_GATE
    assert "deepagents/review" in MERGE_GATE and "ci-ok" in MERGE_GATE and not human_merge_lines(MERGE_GATE)
