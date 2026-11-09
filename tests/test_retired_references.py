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

# One genealogy id, and a list of ids joined by / 、 , → + (e.g. "256/264",
# "598 → 603 → 615", "615/616/617"). Ranges like 189-215 are not expanded.
# "#NNN" is a ticket/issue number in this repo, never a genealogy id.
# Not part of a version tag (v198) and not a count (106 例 / 300 个 / 120 条).
_ID = r"(?<![0-9#＃A-Za-z])\d{3}[a-z]?(?![0-9a-z])(?!\s*(?:例|个|条|次|行|根|笔|段|%|×))"
_NOTE = r"(?:\s*(?:（[^）]{0,80}）|\([^)]{0,80}\)))?"   # 597（仓位塔 payoff 纤维）/601
_SEP = r"\s*(?:/|、|,|，|→|->|\+|&)\s*"
_LIST = rf"{_ID}{_NOTE}(?:{_SEP}{_ID}{_NOTE})*"
GENEALOGY_CITE = [
    re.compile(rf"(?<![#＃.\w])({_LIST})\s*号"),                     # 603号 / 007/008号
    # 谱系 603 / 谱系：598 → 603 / 谱系引用**：663
    re.compile(rf"谱系(?:引用|编号|依据|条目)?[\s*：:（(]*({_LIST})"),
    # an explicit label "谱系引用：…" / "谱系：…": every id on the rest of the line
    re.compile(r"谱系(?:引用|编号|依据|条目)?\**\s*[：:](.*)$"),
    re.compile(rf"(?i)genealogy(?:\s+(?:ref|refs|id|entry|entries))?[\s/#:：*-]*({_LIST})"),
    re.compile(r"(?i)settled/(\d{3}[a-z]?)[-_.]"),
]
_ID_RE = re.compile(_ID)

# Docs in the live layer README.md「谱系」defines; their genealogy citations are
# checked like code. Anything under HISTORICAL is still skipped.
LIVE_DOC_PREFIXES = (".chanlun/definitions/", "docs/adr/", "docs/agents/", "formal/",
                     ".claude/", ".agents/", "spec/", ".github/")
LIVE_DOC_FILES = {"AGENTS.md", "CLAUDE.md", "CONTEXT.md"}

# (path prefix, number) pairs that are deliberately not real entries.
FAKE_GENEALOGY_IDS = {
    ("tests/", "999"): "fixtures that test the missing-entry path on purpose",
    **{("tests/test_retired_references.py", n): "negative-control fixture ids"
       for n in ("801", "802", "803", "804", "805")},
    ("rust/src/theta_v0/strategy/overlay_state.rs", "146"):
        "cites 146 next to entry 646; 146 never existed as a genealogy entry",
}

# Slash commands whose machinery was retired. /ritual, /escalate and /inquire
# are user-level commands (~/.claude/commands) that still work without any
# deleted repo file, so they are not listed.
RETIRED_COMMANDS = {
    "ceremony": "ceremony_scan.py and .chanlun/sessions/ retired in #1952",
}

# Any repo-relative path written in prose (backtick-quoted or bare): it starts
# with a tracked top-level directory and ends in a file extension or "/".
# The pattern is built from the tree in _repo_path_re().
PATH_CHARS = r"[^\s`'\"<>()\[\]{}|*,;:，。、；：（）「」【】]"
PLACEHOLDER = re.compile(r"NNN|XXX|\.\.\.|…|\$|%|<|>|\{|\}|\*")
SLASH = re.compile(r"(?<![\w/.:'\"-])/(" + "|".join(RETIRED_COMMANDS) + r")(?![\w/-])")
LINK = re.compile(r"\]\(([^)\s]+)\)|href=\"([^\"]+)\"")
# A line that itself says the thing is gone is a historical note, not an
# instruction to run it.
RETIRED_NOTE = re.compile(r"退役|已删除|已删|不再|retired|removed|no longer", re.I)

# Missing-path findings that already existed on main before #1955 (review drafts
# archived in #504, files renamed long ago, pilot artifacts never committed,
# example paths in vendored skills). Frozen like the DevSkim baseline (#1194):
# new findings fail; an entry that no longer reproduces must be deleted, so the
# list only shrinks. Keyed "file|path" (line numbers drift).
BASELINE = Path(__file__).with_name("retired_references_baseline.txt")

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
    "docs/teach/lessons/0004a-why-structural-workstations-dont-autostart.html":
        "historical lesson on retired dispatch-dag.yaml / hooks; banner says so",
    "docs/teach/lessons/0010-permanently-solving-structural-workstations.html":
        "historical lesson on retired dispatch-dag.yaml / hooks; banner says so",
    ".chanlun/proposals/PROP-002-dispatch-dag-c-task-recursion.md":
        "withdrawn proposal (status: withdrawn); its target file was retired",
    ".chanlun/pdf-review/": "point-in-time PDF review notes",
    "docs/architecture/openclaw-api-design.md": INFERENCE,
    "docs/architecture/openclaw-resource-protocol.md": INFERENCE,
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
    """Ids of entries in settled/ and pending/. archive/ holds pending-NNN drafts,
    a separate numbering, so it does not satisfy a genealogy citation."""
    nums = set()
    for sub in ("settled", "pending"):
        d = ROOT / ".chanlun" / "genealogy" / sub
        if d.is_dir():
            for p in d.iterdir():
                m = re.match(r"(\d{3}[a-z]?)[-_.]", p.name)
                if m:
                    nums.add(m.group(1))
    return nums


def _tree(files: list[str]) -> tuple[set[str], set[str]]:
    """Tracked files and every directory that contains one (repo-relative)."""
    dirs = set()
    for f in files:
        parts = f.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))
    return set(files), dirs


def _repo_path_re(dirs: set[str]) -> re.Pattern:
    tops = sorted((d for d in dirs if "/" not in d), key=len, reverse=True)
    return re.compile(r"(?<![\w./~-])((?:" + "|".join(re.escape(t) for t in tops)
                      + r")/" + PATH_CHARS + r"*)")


def _exists_from(f: str, target: str, tree: tuple[set[str], set[str]]) -> bool:
    """True if target names a tracked file/dir from the repo root or any ancestor
    directory of f (skills and sub-projects quote paths relative to themselves)."""
    files, dirs = tree
    target = target.rstrip("/")
    parts = f.split("/")[:-1]
    for i in range(len(parts), -1, -1):
        cand = "/".join(parts[:i] + [target]) if i else target
        cand = os.path.normpath(cand)
        if cand in files or cand in dirs:
            return True
    return False


def _repo_path_tokens(line: str, pat: re.Pattern):
    for m in pat.finditer(line):
        tok = m.group(1)
        tok = re.sub(r"#.*$", "", tok)            # anchors
        tok = tok.rstrip(".")                      # sentence punctuation
        if PLACEHOLDER.search(tok):
            continue
        last = tok.rsplit("/", 1)[-1]
        if not (tok.endswith("/") or re.search(r"\.[A-Za-z0-9]{1,8}$", last)):
            continue                               # not a file or explicit dir
        yield tok


def _checks_genealogy(f: str) -> bool:
    if Path(f).suffix in CODE_EXT:
        return True
    if Path(f).suffix in DOC_EXT and not _historical(f):
        return f in LIVE_DOC_FILES or f.startswith(LIVE_DOC_PREFIXES)
    return False


def cited_ids(line: str) -> list[str]:
    """Every genealogy id a line cites, including each id in a cited list."""
    out = []
    for pat in GENEALOGY_CITE:
        for m in pat.finditer(line):
            out += _ID_RE.findall(m.group(1))
    return list(dict.fromkeys(out))


def missing_genealogy_refs(files: list[str]) -> list[str]:
    present = _present_genealogy()
    bad = []
    for f in files:
        if not _checks_genealogy(f):
            continue
        for ln, line in enumerate(_lines(f), 1):
            for n in cited_ids(line):
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


def _git_ignored(paths: list[str]) -> set[str]:
    """Paths git ignores on purpose (local secrets, logs, caches, build output)."""
    if not paths or not (ROOT / ".git").exists():
        return set()
    proc = subprocess.run(["git", "check-ignore", "--no-index", "--stdin"], cwd=ROOT,
                          input="\n".join(paths), capture_output=True, text=True, check=False)
    return set(proc.stdout.split("\n")) - {""}


def broken_doc_refs(files: list[str], tree: tuple[set[str], set[str]] | None = None) -> list[str]:
    tree = tree or _tree(files)
    path_re = _repo_path_re(tree[1])
    pending: list[tuple[str, str]] = []  # (finding, path) checked against .gitignore last
    bad = []
    for f in files:
        if Path(f).suffix not in DOC_EXT or _historical(f):
            continue
        is_html = f.endswith(".html")
        for ln, line in enumerate(_lines(f), 1):
            noted = bool(RETIRED_NOTE.search(line))
            for p in ([] if noted else _repo_path_tokens(line, path_re)):
                if not _exists_from(f, p, tree):
                    pending.append((f"{f}:{ln}: names missing path {p}", p))
            for m in ([] if noted else SLASH.finditer(line)):
                bad.append(f"{f}:{ln}: tells reader to use retired /{m.group(1)} "
                           f"({RETIRED_COMMANDS[m.group(1)]})")
            for t in _link_targets(line, is_html):
                rel = os.path.normpath(os.path.join(os.path.dirname(f), t))
                if not any(c in tree[0] or c in tree[1]
                           for c in (rel, os.path.normpath(t.rstrip("/")))):
                    bad.append(f"{f}:{ln}: links to missing path {t}")
    ignored = _git_ignored(sorted({p for _, p in pending}))
    bad += [msg for msg, p in pending if p not in ignored and p.rstrip("/") not in ignored]
    return bad


@pytest.fixture(scope="module")
def tracked():
    return _tracked()


def test_code_cites_only_present_genealogy(tracked):
    bad = missing_genealogy_refs(tracked)
    assert not bad, "restore the entry or drop the citation:\n" + "\n".join(bad)


def _finding_key(finding: str) -> str | None:
    """'file:LINE: names missing path P' -> 'file|P' (None for non-path findings)."""
    m = re.match(r"^(.+?):\d+: (?:names missing path|links to missing path) (.+)$", finding)
    return f"{m.group(1)}|{m.group(2)}" if m else None


def _baseline() -> set[str]:
    if not BASELINE.exists():
        return set()
    return {l for l in BASELINE.read_text(encoding="utf-8").split("\n")
            if l and not l.startswith("#")}


def test_docs_do_not_point_at_missing_or_retired_entries(tracked):
    frozen = _baseline()
    bad = broken_doc_refs(tracked)
    new = [b for b in bad if _finding_key(b) not in frozen]
    assert not new, ("fix the reference, or add the file to HISTORICAL with a reason:\n"
                     + "\n".join(new))
    seen = {_finding_key(b) for b in bad}
    gone = sorted(frozen - seen)
    assert not gone, ("these baseline entries no longer reproduce; delete them from "
                      f"{BASELINE.name}:\n" + "\n".join(gone))


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
        "`scripts/gone_tool.py` 已随 #1952 退役\n"
        "精读 `.chanlun/genealogy/pending/gone-20260624.md`（对偶基准）\n"
        "bare .chanlun/genealogy/pending/also-gone.md here\n"
        "ok `scripts/real.py`, `.chanlun/genealogy/`, and `scripts/<name>.py`\n",
        encoding="utf-8")
    (tmp_path / "b.lean").write_text(
        "-- 谱系：001 → 801 → 802\n"            # colon label + arrow list
        "-- 谱系 001/803\n"                      # slash list after 谱系
        "-- 谱系引用**：Q1（x）；804（σ_p）\n"   # label, non-numeric first item
        "-- 谱系引用：001（a）/805（b）\n"        # annotated list
        "-- 谱系：#806 task id, v807-swarm, 808 例\n",  # ticket / version / count: ignored
        encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    assert [b.split(": ")[1] for b in missing_genealogy_refs(["a.py"])] == [
        "cites genealogy 999, not under .chanlun/genealogy/"]
    cited = [b.split("genealogy ")[1].split(",")[0] for b in missing_genealogy_refs(["b.lean"])]
    assert cited == ["801", "802", "803", "804", "805"]
    files = ["g.md", "scripts/real.py", ".chanlun/genealogy/settled/001-x.md"]
    found = [b.split(": ", 1)[1] for b in broken_doc_refs(["g.md"], _tree(files))]
    assert sorted(found) == sorted([
        "names missing path scripts/gone_tool.py",
        "tells reader to use retired /ceremony (" + RETIRED_COMMANDS["ceremony"] + ")",
        "links to missing path nope/missing.md",
        "names missing path .chanlun/genealogy/pending/gone-20260624.md",
        "names missing path .chanlun/genealogy/pending/also-gone.md",
    ])
