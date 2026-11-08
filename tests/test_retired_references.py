"""Guard against references to retired code and genealogy (#1952 / PR #1955).

Two rules, checked over every tracked file:

1. Code (.py .rs .lean .sh .ts .mts, any directory) that cites a genealogy
   entry by number (``NNN号``, ``谱系 NNN``, ``genealogy NNN``,
   ``settled/NNN-``) needs that entry to exist under ``.chanlun/genealogy/``.
2. Docs and pages (.md .html) outside ``HISTORICAL`` must not link to a path
   that does not exist, name a script/command file that does not exist, or
   tell the reader to run a retired slash command (``RETIRED_COMMANDS``).

``HISTORICAL`` lists files kept as records on purpose. Per AGENTS.md
「文档层名分」, inference-layer documents are historical records and are not
updated after the fact; review drafts, snapshots and vendored text likewise.
Each entry says why. An entry that no longer matches any tracked file fails,
so the list cannot rot.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parent.parent

CODE_EXT = {".py", ".rs", ".lean", ".sh", ".ts", ".mts"}
DOC_EXT = {".md", ".html"}

GENEALOGY_NUM = [
    re.compile(r"(?<![0-9#.\w])(\d{3}[a-z]?)\s*号"),
    re.compile(r"谱系\s*[#＃]?\s*(\d{3}[a-z]?)(?![0-9])"),
    re.compile(r"(?i)genealogy[\s/#-]*(\d{3}[a-z]?)(?![0-9a-z])"),
    re.compile(r"(?i)settled/(\d{3}[a-z]?)[-_.]"),
]

# (path prefix, number) pairs that are deliberately not real entries.
FAKE_GENEALOGY_IDS = {
    ("tests/", "999"): "fixtures that test the missing-entry path on purpose",
}

# Slash commands whose machinery was retired. /ritual, /escalate and /inquire
# are user-level commands (~/.claude/commands) that still work without any
# deleted repo file, so they are not listed.
RETIRED_COMMANDS = {
    "ceremony": "ceremony_scan.py and .chanlun/sessions/ retired in #1952",
}

# Repo paths of executable entry points / command files named in prose.
ENTRY_PATH = re.compile(
    r"(?<![\w./-])((?:scripts|topological-computation|src/newchan|\.claude/commands|\.claude/hooks)"
    r"/[\w./-]+\.(?:py|sh|md|ts|mts))")
SLASH = re.compile(r"(?<![\w/.:'\"-])/(" + "|".join(RETIRED_COMMANDS) + r")(?![\w/-])")
LINK = re.compile(r"\]\(([^)\s]+)\)|href=\"([^\"]+)\"")
# A line that itself says the thing is gone is a historical note, not an
# instruction to run it.
RETIRED_NOTE = re.compile(r"退役|已删除|已删|retired|removed", re.I)

INFERENCE = "inference layer, historical record (AGENTS.md 文档层名分: 不追溯更新)"
HISTORICAL = {
    # whole trees
    "analysis/": INFERENCE,
    ".chanlun/archive/": "archived swarm-era material",
    ".chanlun/genealogy/": "genealogy entries are immutable history",
    ".chanlun/review-results/": "review drafts bound to closed tickets",
    ".chanlun/diagnostics/": "point-in-time diagnostic reports",
    ".chanlun/specs/": "swarm-era design specs, superseded",
    ".chanlun/escalations/": "escalation records",
    ".chanlun/reports/": "point-in-time reports",
    ".chanlun/agent-roster-2026-09-30.md": "dated roster snapshot",
    ".chanlun/codex-on-breakthrough-verdict-2026-06-30.md": "dated verdict record",
    ".chanlun/.interrupt-point.md": "ENDED snapshot; header explains the retirement",
    ".rtas/review-results/": "review drafts",
    "chanlun/review-results/": "review drafts",
    "chanlun/harness/vendor/": "vendored third-party text",
    ".auto-memory-snapshot/": "memory snapshot export",
    ".scratch/": "scratch notes",
    "topological-computation/signifier_net/": "ingested corpus data",
    "topological-computation/docs/escalate-integration-gaps.md":
        "gap analysis of the retired escalate pipeline",
    ".claude/skills/writing-skills/anthropic-best-practices.md":
        "vendored copy of Anthropic docs (site-relative links)",
    ".agents/skills/domain-modeling/CONTEXT-FORMAT.md": "vendored skill; example paths",
    ".agents/skills/setup-ts-deep-modules/SKILL.md": "vendored skill; example paths",
    ".agents/skills/git-guardrails-claude-code/SKILL.md":
        "vendored skill; paths are in the target project it installs into",
    "meta-lead.md": "2026-02 swarm router draft; banner marks it historical",
    "docs/teach/lessons/0011-resume-goal-command-toolbox.html":
        "historical lesson; banner points to python scripts/goal_reducer.py",
    "docs/teach/lessons/0013-goal-command-usage.html":
        "historical lesson; banner points to python scripts/goal_reducer.py",
    # inference-layer docs/ 散件 with stale paths
    "docs/accounting_trading_exhaustive_enumeration.md": INFERENCE,
    "docs/backtest-protocol-v0.md": INFERENCE,
    "docs/dialectical_exhaustion.md": INFERENCE,
    "docs/spiral_completeness_and_course_coverage.md": INFERENCE,
    "docs/three_stages_accounting_design.md": INFERENCE,
    "docs/architecture/complete_fugue_design.md": INFERENCE,
}


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    return [f for f in out.split("\0") if f and (ROOT / f).is_file()]


def _historical(f: str) -> bool:
    return any(f == k or (k.endswith("/") and f.startswith(k)) for k in HISTORICAL)


def _lines(f: str):
    try:
        text = (ROOT / f).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    return text.split("\n")


def _present_genealogy() -> set[str]:
    nums = set()
    for sub in ("settled", "pending", "archive"):
        d = ROOT / ".chanlun" / "genealogy" / sub
        if d.is_dir():
            for p in d.iterdir():
                m = re.match(r"(\d{3}[a-z]?)[-_.]", p.name)
                if m:
                    nums.add(m.group(1))
    return nums


def _exists_from(f: str, target: str) -> bool:
    """True if target resolves from the file's directory, any ancestor, or repo root."""
    d = (ROOT / f).parent
    while True:
        if (d / target).exists():
            return True
        if d == ROOT:
            return False
        d = d.parent


def missing_genealogy_refs(files: list[str]) -> list[str]:
    present = _present_genealogy()
    bad = []
    for f in files:
        if Path(f).suffix not in CODE_EXT:
            continue
        for ln, line in enumerate(_lines(f), 1):
            for pat in GENEALOGY_NUM:
                for m in pat.finditer(line):
                    n = m.group(1)
                    if n in present or any(f.startswith(p) and n == k
                                           for (p, k) in FAKE_GENEALOGY_IDS):
                        continue
                    bad.append(f"{f}:{ln}: cites genealogy {n}, not under .chanlun/genealogy/")
    return bad


def _link_targets(line: str, is_html: bool):
    for m in LINK.finditer(line):
        t = unquote(m.group(1) or m.group(2))
        if re.match(r"^(?:[a-z][a-z0-9+.-]*:|#|\{|<)", t, re.I) or "..." in t:
            continue
        t = t.split("#")[0].split("?")[0]
        if not t or ("/" not in t and "." not in t):
            continue  # anchors / placeholders such as (link) or (ℓ)
        if t.startswith("/") and is_html:
            continue  # site-root URL served by the page's web server
        yield t.lstrip("/") if t.startswith("/") else t


def broken_doc_refs(files: list[str]) -> list[str]:
    bad = []
    for f in files:
        if Path(f).suffix not in DOC_EXT or _historical(f):
            continue
        is_html = f.endswith(".html")
        for ln, line in enumerate(_lines(f), 1):
            noted = bool(RETIRED_NOTE.search(line))
            for m in ENTRY_PATH.finditer(line):
                p = m.group(1).rstrip(".")
                if not noted and not _exists_from(f, p):
                    bad.append(f"{f}:{ln}: names missing file {p}")
            for m in ([] if noted else SLASH.finditer(line)):
                bad.append(f"{f}:{ln}: tells reader to use retired /{m.group(1)} "
                           f"({RETIRED_COMMANDS[m.group(1)]})")
            for t in _link_targets(line, is_html):
                base = (ROOT / f).parent
                if not ((base / t).exists() or (ROOT / t).exists()):
                    bad.append(f"{f}:{ln}: links to missing path {t}")
    return bad


@pytest.fixture(scope="module")
def tracked():
    return _tracked()


def test_code_cites_only_present_genealogy(tracked):
    bad = missing_genealogy_refs(tracked)
    assert not bad, "restore the entry or drop the citation:\n" + "\n".join(bad)


def test_docs_do_not_point_at_missing_or_retired_entries(tracked):
    bad = broken_doc_refs(tracked)
    assert not bad, ("fix the reference, or add the file to HISTORICAL with a reason:\n"
                     + "\n".join(bad))


def test_historical_allowlist_has_no_stale_entries(tracked):
    stale = [k for k in HISTORICAL
             if not any(f == k or (k.endswith("/") and f.startswith(k)) for f in tracked)]
    assert not stale, f"HISTORICAL entries match no tracked file: {stale}"


def test_checker_catches_known_bad_cases(tmp_path, monkeypatch):
    """Negative control: the rules do fire on the defects they exist for."""
    (tmp_path / ".chanlun" / "genealogy" / "settled").mkdir(parents=True)
    (tmp_path / ".chanlun" / "genealogy" / "settled" / "001-x.md").write_text("x")
    (tmp_path / "a.py").write_text("# 001号 ok\n# 999号 gone\n", encoding="utf-8")
    (tmp_path / "g.md").write_text(
        "run `python scripts/gone_tool.py`\nthen `/ceremony`\n[x](nope/missing.md)\n"
        "`scripts/gone_tool.py` 已随 #1952 退役\n",
        encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    assert [b.split(": ")[1] for b in missing_genealogy_refs(["a.py"])] == [
        "cites genealogy 999, not under .chanlun/genealogy/"]
    kinds = [b.split(": ", 1)[1].split(" ")[0:2] for b in broken_doc_refs(["g.md"])]
    assert kinds == [["names", "missing"], ["tells", "reader"], ["links", "to"]]
