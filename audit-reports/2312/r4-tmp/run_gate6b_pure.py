"""Pure Python + Git Gate 6b probes (ZERO Lean invoked!)."""

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
SOURCES = ("run_gates.py", "pins.json", "Audit.lean", "EnvGates.lean", "SourceGates.lean", "garbage-signoffs.yaml")

WORK_DIR.mkdir(parents=True, exist_ok=True)
repo = Path(tempfile.mkdtemp(prefix="P9c_gate6b_pure-", dir=WORK_DIR))
steps = []
try:
    fm = repo / "formal_math"
    (fm / "verification").mkdir(parents=True)
    for fn in SOURCES:
        shutil.copy2(VERIF / fn, fm / "verification" / fn)
    (fm / "Chan.lean").write_text("module\n")
    (fm / "Chan/Defs").mkdir(parents=True)
    (fm / "Chan/Defs/Base.lean").write_text("module\n@[expose] public section\ndef x : Nat := 1\n")
    env = os.environ.copy()
    env.pop("GITHUB_HEAD_REF", None)

    def git(*a):
        return subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=T", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *a],
            cwd=repo, check=True, capture_output=True, text=True,
        )

    def run6b(extra_env=None):
        e = dict(env)
        if extra_env:
            e.update(extra_env)
        r = subprocess.run(
            [sys.executable, str(fm / "verification/run_gates.py"), "--repo-root", str(repo), "--gate", "6b"],
            cwd=repo, env=e, capture_output=True, text=True, check=False,
        )
        return {"rc": r.returncode, "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}

    git("init", "-q", "-b", "main")
    git("add", "formal_math")
    git("commit", "-qm", "base")
    git("update-ref", "refs/remotes/origin/main", "HEAD")

    # 1. proof/branch with untracked file at repo root
    git("switch", "-qc", "proof/t1")
    (repo / "stray_root.txt").write_text("x\n")
    steps.append({"name": "proof_untracked_root_file", **run6b()})
    (repo / "stray_root.txt").unlink()

    # 2. proof/branch with untracked file in formal_math/Chan/Defs/
    (fm / "Chan/Defs/Sneak.lean").write_text("module\n")
    steps.append({"name": "proof_untracked_defs_file", **run6b()})
    (fm / "Chan/Defs/Sneak.lean").unlink()

    # 3. proof/branch modifying Chan/Defs in HEAD then reverting in worktree (should NOT cancel!)
    (fm / "Chan/Defs/Base.lean").write_text("module\n@[expose] public section\ndef x : Nat := 2\n")
    git("add", "formal_math/Chan/Defs/Base.lean")
    git("commit", "-qm", "edit defs")
    (fm / "Chan/Defs/Base.lean").write_text("module\n@[expose] public section\ndef x : Nat := 1\n")
    steps.append({"name": "proof_commit_then_worktree_revert_defs", **run6b()})

    # 4. proof/branch modifying Chan/Defs in commit 1 then reverting in commit 2 (net zero diff base..HEAD)
    git("add", "formal_math/Chan/Defs/Base.lean")
    git("commit", "-qm", "revert defs")
    steps.append({"name": "proof_commit_then_commit_revert_defs", **run6b()})

    # 5. infra/branch adding non-empty signoffs when base already has empty signoffs
    git("switch", "-q", "main")
    git("switch", "-qc", "infra/t2")
    (fm / "verification/garbage-signoffs.yaml").write_text('{"Chan.x":{"Nat.div":{"count":1,"review":"r"}}}\n')
    git("add", "formal_math/verification/garbage-signoffs.yaml")
    git("commit", "-qm", "nonempty signoffs")
    steps.append({"name": "infra_nonempty_signoff", **run6b()})

    # 6. infra/branch initializing empty signoffs when base has NO signoffs
    git("switch", "-q", "main")
    git("rm", "-q", "formal_math/verification/garbage-signoffs.yaml")
    git("commit", "-qm", "remove signoffs on main")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    git("switch", "-qc", "infra/init-empty")
    (fm / "verification/garbage-signoffs.yaml").write_text("{}\n")
    git("add", "formal_math/verification/garbage-signoffs.yaml")
    git("commit", "-qm", "init empty signoffs")
    steps.append({"name": "infra_init_empty_signoff", **run6b()})

    # 7. infra/branch initializing NON-EMPTY signoffs when base has NO signoffs
    (fm / "verification/garbage-signoffs.yaml").write_text('{"Chan.x":{"Nat.div":{"count":1,"review":"r"}}}\n')
    git("add", "formal_math/verification/garbage-signoffs.yaml")
    git("commit", "-qm", "init nonempty signoffs")
    steps.append({"name": "infra_init_nonempty_signoff", **run6b()})

    # 8. detached HEAD with GITHUB_HEAD_REF = "decl/" (empty suffix after /)
    git("switch", "-q", "main")
    git("switch", "--detach", "HEAD")
    (fm / "Chan/Defs/Base.lean").write_text("module\n@[expose] public section\ndef x : Nat := 99\n")
    git("add", "formal_math/Chan/Defs/Base.lean")
    git("commit", "-qm", "decl empty suffix")
    steps.append({"name": "detached_decl_empty_suffix", **run6b({"GITHUB_HEAD_REF": "decl/"})})

    # 9. proof/branch with symlink inside formal_math/Chan/Thm/ pointing to ../Defs/Base.lean
    git("switch", "-q", "main")
    git("switch", "-qc", "proof/symlink-check")
    (fm / "Chan/Thm").mkdir(parents=True, exist_ok=True)
    (fm / "Chan/Thm/Sym.lean").symlink_to("../Defs/Base.lean")
    git("add", "formal_math/Chan/Thm/Sym.lean")
    git("commit", "-qm", "add symlink")
    steps.append({"name": "proof_symlink_in_thm", **run6b()})

finally:
    shutil.rmtree(repo, ignore_errors=True)

(TMP_ROOT / "gate6b_pure.json").write_text(json.dumps(steps, ensure_ascii=False, indent=2))
for s in steps:
    print(f"{s['name']}: rc={s['rc']} stdout={s['stdout']} stderr={s['stderr']}")
