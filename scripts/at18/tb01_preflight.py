#!/usr/bin/env python3
"""用一次性 TB-01 测试库复现正式签锚门；不签发、模拟或放宽资源合同。"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "s_session"
FIXTURE = SESSION / "tests/fixtures/tb01c"
CONTRACT = SESSION / "contracts/admission-small-v1.json"
VERSION = "s-admission-small/1-awaiting-measurement"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True, help="本提交构建的正式 s_structure_session")
    parser.add_argument("--work", type=Path, required=True, help="全新的 runner 临时目录，保留失败原件")
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    work = args.work.resolve()
    work.mkdir(mode=0o700)
    state = work / "control"
    state.mkdir(mode=0o700)
    db = work / "session.sqlite"
    plan = json.loads((FIXTURE / "runtime-plan.json").read_bytes())
    with (FIXTURE / "messages.jsonl").open("rb") as source:
        first = json.loads(source.readline())
    subprocess.run([binary, "init", "--db", db, "--session", first["session_id"],
                    "--session-generation", first["session_generation"],
                    "--catalog", SESSION / "catalog/signed-catalog.json",
                    "--profile", FIXTURE / "profile.json", "--clock-plan", FIXTURE / "clock-plan.json",
                    "--delivery-retain-generations", plan["delivery_retain_generations"]],
                   check=True)
    result = subprocess.run([binary, "admission-prepare", "--db", db, "--state-dir", state,
                             "--service-uid", str(os.geteuid()), "--contract-version", VERSION,
                             "--contract", CONTRACT, "--startup-timeout-ms", str(plan["startup_timeout_ms"])],
                            check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
