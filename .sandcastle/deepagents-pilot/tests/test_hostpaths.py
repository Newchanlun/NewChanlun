"""#2048：宿主路径环境变量。缺省值必须等于 Mac 现役位置；cutover.py 内联副本与 hostpaths 同口径。"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pilot1742.hostpaths import service_manager, systemd_unit

PILOT = Path(__file__).resolve().parents[1]
VARS = ("AGENT_STORAGE", "PILOT1742_WORKERS_LOG", "PSTACK_SKILLS_ROOT", "SANDCASTLE_HOST_REPO", "SERVICE_MANAGER")
PROBE = """
import json
from pilot1742 import claims, cutover, executor, hostpaths, run
print(json.dumps({
    "claims": str(claims.CLAIMS_ROOT), "home": str(run.DEFAULT_HOME), "skills": run.SKILLS_ROOT,
    "state": str(executor.DEFAULT_STATE_ROOT), "workers": str(executor.WORKERS_LOG),
    "cut_state": str(cutover.STATE_ROOT), "cut_drain": str(cutover.DRAIN_ROOT),
    "cut_workers": str(cutover.WORKERS_LOG), "legacy": str(cutover.LEGACY_HOST_REPO),
    "managed": sorted(cutover.MANAGED_LEGACY_ENTRYPOINTS)[0], "hp_workers": str(hostpaths.WORKERS_LOG),
}))
"""


def probe(**env: str) -> dict[str, str]:
    base = {k: v for k, v in os.environ.items() if k not in VARS}
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=PILOT, env={**base, **env},
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def test_defaults_equal_mac_locations() -> None:
    got = probe()
    assert got["claims"] == "/Volumes/AgentStorage/deepagents-exec/claims"
    assert got["home"] == "/Volumes/AgentStorage/issue1742-deepagents-pilot-20261027"
    assert got["skills"] == "/Users/silencehan/.codex/pstack-upstream-source/installed/skills/"
    assert got["state"] == got["cut_state"] == "/Volumes/AgentStorage/deepagents-exec"
    assert got["cut_drain"] == "/Volumes/AgentStorage/newchanlun-legacy-drain"
    assert got["workers"] == got["cut_workers"] == got["hp_workers"] == \
        "/Users/silencehan/Projects/NewChanlun/.sandcastle/logs/workers.jsonl"
    assert got["legacy"] == "/Users/silencehan/Projects/NewChanlun-sandcastle-host"
    assert got["managed"].startswith("/Volumes/AgentStorage/h1-managed43r/")


def test_env_overrides_every_location() -> None:
    got = probe(AGENT_STORAGE="/srv/as", PILOT1742_WORKERS_LOG="/srv/w.jsonl", PSTACK_SKILLS_ROOT="/srv/skills/",
                SANDCASTLE_HOST_REPO="/srv/host")
    assert got["claims"] == "/srv/as/deepagents-exec/claims"
    assert got["home"] == "/srv/as/issue1742-deepagents-pilot-20261027"
    assert got["skills"] == "/srv/skills/"
    assert got["state"] == got["cut_state"] == "/srv/as/deepagents-exec"
    assert got["cut_drain"] == "/srv/as/newchanlun-legacy-drain"
    assert got["workers"] == got["cut_workers"] == "/srv/w.jsonl"
    assert got["legacy"] == "/srv/host"
    assert got["managed"].startswith("/srv/as/h1-managed43r/")


def test_service_manager() -> None:
    assert service_manager("") == "launchctl"
    assert service_manager("systemd") == "systemd"
    with pytest.raises(ValueError, match="SERVICE_MANAGER"):
        service_manager("upstart")
    assert systemd_unit("com.newchanlun.sandcastle-claimer") == "newchanlun-sandcastle-claimer.service"
