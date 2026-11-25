"""Copy text-only R4 review fixtures, scripts, logs, and report to evidence worktree."""

import hashlib
import shutil
from pathlib import Path

SRC_TMP = Path("/Volumes/AgentStorage/fm/tmp/2312-d-review")
SRC_REPORT = Path("/Volumes/AgentStorage/fm/r2/2312-neon-review-r4.md")
TASK_LOGS = Path(
    "/Users/silencehan/.t3/userdata/providers/antigravity/"
    "ac0a3dfd6dddb20962cecff6ee5fe65e19d3923be20e52c5ab52ff877f7e4c32/"
    "antigravity-acp/brain/de61fc30-3ca3-48ea-bc5a-ad778845a206/.system_generated/tasks"
)
DST_BASE = Path("/Volumes/AgentStorage/wt-2312-d-report/audit-reports/2312")
DST_REPORT = DST_BASE / "2312-neon-review-r4.md"
DST_TMP = DST_BASE / "r4-tmp"

TEXT_EXTS = {".py", ".lean", ".toml", ".yaml", ".yml", ".json", ".jsonl", ".log", ".txt", ".md"}
SKIP_DIRS = {"warm", "work", ".lake", "__pycache__", ".git"}
SKIP_FILES = {"run_batch2.py", "run_batch3.py", "run_batch_mathlib.py", "sentinel_zero_import_rce.txt", "sentinel_sudo_by_elab_pwned.txt", "host_secret_probe.txt"}


def main():
    if not SRC_REPORT.is_file():
        raise SystemExit(f"Missing report: {SRC_REPORT}")
    DST_BASE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC_REPORT, DST_REPORT)

    if DST_TMP.exists():
        shutil.rmtree(DST_TMP)
    DST_TMP.mkdir(parents=True, exist_ok=True)

    copied = 0
    for path in sorted(SRC_TMP.rglob("*")):
        rel = path.relative_to(SRC_TMP)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.name in SKIP_FILES:
            continue
        if path.is_file() and path.suffix in TEXT_EXTS:
            # Skip unused/draft batch scripts that were not run if needed? Keep all scripts & results for transparency.
            dst = DST_TMP / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dst)
            copied += 1

    # Also copy task logs for batch1 (task-152), batch_fast (task-271), batch_surgical (task-412)
    logs_dir = DST_TMP / "logs"
    logs_dir.mkdir(exist_ok=True)
    for src_name, dst_name in (
        ("task-152.log", "batch1.log"),
        ("task-271.log", "batch_fast.log"),
        ("task-412.log", "batch_surgical.log"),
    ):
        p = TASK_LOGS / src_name
        if p.is_file():
            shutil.copy2(p, logs_dir / dst_name)
            copied += 1

    sha = hashlib.sha256(DST_REPORT.read_bytes()).hexdigest()
    print(f"Copied report + {copied} text files to {DST_BASE}")
    print(f"Report SHA256: {sha}")


if __name__ == "__main__":
    main()
