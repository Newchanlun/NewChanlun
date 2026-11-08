"""#1937：仓库迁到组织 Newchanlun 后，所有写死的 App 身份必须一致，旧账号下的批准记录仍然有效。"""
import ast
import json
import subprocess
from pathlib import Path

from pilot1742.run import parse_approval_ledger

SANDCASTLE = Path(__file__).resolve().parents[2]
EXPECTED = (5486877, 179444545, 1150335160, "Newchanlun/NewChanlun")


def _tracked_sources():
    listed = subprocess.run(["git", "ls-files", "-z", "--", "*.py"], cwd=SANDCASTLE, check=True,
                            capture_output=True, text=True).stdout
    return sorted(SANDCASTLE / name for name in listed.split("\0") if name and "tests" not in Path(name).parts)


def _literal_identities():
    for path in _tracked_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "AppIdentity":
                values = [a.value for a in node.args[:4] if isinstance(a, ast.Constant)]
                if len(values) >= 3:
                    yield path.relative_to(SANDCASTLE), values


def test_every_hardcoded_app_identity_points_at_the_org_installation():
    found = list(_literal_identities())
    assert found, "没有找到任何写死的 AppIdentity，扫描路径可能错了"
    for path, values in found:
        assert tuple(values[:3]) == EXPECTED[:3], f"{path} 仍指向旧身份 {values}"
        if len(values) == 4:
            assert values[3] == EXPECTED[3], f"{path} 仍写着旧仓库名 {values[3]}"


def _row(owner):
    return json.dumps({"ticket": 1742, "scope": "pilot_acceptance", "decision": "approve", "head": "a" * 40,
                       "source": {"kind": "tracker_comment", "registered_by": "controller",
                                  "reference": f"https://github.com/{owner}/NewChanlun/issues/1742#issuecomment-123"}})


def test_approval_ledger_accepts_comment_urls_before_and_after_the_transfer():
    records, problems = parse_approval_ledger(_row("xy7365527-lang") + "\n" + _row("Newchanlun") + "\n")
    assert problems == []
    assert len(records) == 2


def test_approval_ledger_still_rejects_other_owners():
    records, problems = parse_approval_ledger(_row("someone-else") + "\n")
    assert records == [] and len(problems) == 1
