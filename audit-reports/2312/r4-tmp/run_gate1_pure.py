"""Pure Python Gate 1 manifest source-type probe (ZERO Lean build invoked!)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WT = Path("/Volumes/AgentStorage/wt-2312-d-review")
VERIF = WT / "formal_math/verification"
TMP_ROOT = Path("/Volumes/AgentStorage/fm/tmp/2312-d-review")
WORK_DIR = TMP_ROOT / "work"

WORK_DIR.mkdir(parents=True, exist_ok=True)
repo = Path(tempfile.mkdtemp(prefix="P9e_gate1_pure-", dir=WORK_DIR))
try:
    fm = repo / "formal_math"
    (fm / "verification").mkdir(parents=True)
    shutil.copy2(VERIF / "run_gates.py", fm / "verification/run_gates.py")
    shutil.copy2(VERIF / "pins.json", fm / "verification/pins.json")
    shutil.copy2(WT / "formal_math/lean-toolchain", fm / "lean-toolchain")
    manifest = json.loads((WT / "formal_math/lake-manifest.json").read_text())
    # Tamper Cli entry to type=path pointing to local dir while keeping rev intact!
    for pkg in manifest["packages"]:
        if pkg["name"] == "Cli":
            pkg["type"] = "path"
            pkg["dir"] = "../evil-cli"
            pkg["url"] = "https://evil.example/cli.git"
    (fm / "lake-manifest.json").write_text(json.dumps(manifest, indent=2))
    env = os.environ.copy()
    elan_bin = str(Path.home() / ".elan/bin")
    if elan_bin not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = elan_bin + os.pathsep + env.get("PATH", "")
    r = subprocess.run(
        [sys.executable, str(fm / "verification/run_gates.py"), "--repo-root", str(repo), "--gate", "1"],
        cwd=repo, env=env, capture_output=True, text=True, check=False,
    )
    res = {"rc": r.returncode, "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}
    (TMP_ROOT / "gate1_pure.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print("gate1_manifest_path_tamper:", res)
finally:
    shutil.rmtree(repo, ignore_errors=True)
