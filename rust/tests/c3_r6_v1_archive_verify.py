#!/usr/bin/env python3
"""#1407 C3 R6 comprehensive historical-archive readback verification:
1. Real frozen late /1 archives from R5 non-author recovery (mounted read-only, SHA-256 verified untouched):
   - late-intro-legacy-pair (1f0a42bc20, legacy E capability released-exact-probe/1)
   - late-middle-pair-valid-incomplete (2ed00abd6c, model_coverage only)
   - late-lemmas-control (1f0a42bc20, 4 standard conditions)
   For each:
   - All 4 X readback CLIs (query-history, query-command, query-batch, query-original fill & fee)
   - Byte-for-byte canonical parity against original socket .reply.wire (batch, fill, fee) and command meaning
   - Explicit condition_audit_policy="v1_late_common_12_6_invariants_only" and condition_audit_unproven
   - Logical bar non-weakening (tampered claimed_ns -> IdentityConflict)
   - Unmodified working-copy fixture E inspect-simulation-capture-batch (native session_generation="1")
   - x_execution_session serve refusal (VersionUnsupported, zero byte changes, no .writer.lock)
2. Real frozen early /1 archives:
   - early-1942-logical-bar (3cd162ea4c, 11+3+3, native session_generation="1"):
     4 X CLIs match .reply.wire, condition_audit_policy="v1_early_frozen_three_conditions",
     fixture E inspect-simulation-capture-batch succeeds on unmodified working copy.
   - early-r4-wall-clock (18446a3d35, 11+3+3, wall-clock claimed_ns, native session_generation="g1"):
     4 X CLIs match R4 writer_socket_state & stored originals, raw_claim_only_non_retroactive_v1;
     e_economic_session init REJECTS session_generation="g1" (preserving X vs original E distinction
     without mutating g1->1).
3. #2078 late /1 SQL fixture + corrupt negative controls & anti-downgrade checks:
   - Real late-2078-missing-e-schema -> InvalidDomain on all 4 CLIs
   - Hybrid layouts (12+3, 11+6, asym e6/s3, extra key) -> InvalidDomain
   - Late /1 common-invariant negative controls (unsupported X.* capability, missing model_coverage,
     command/profile condition mismatch, unexpected exact_profile_revision)
   - Early /1 claimed_ns < S.commit_ns -> IdentityConflict
4. /2 and /3 real archive contrast & strict non-weakening:
   - condition_audit_policy="verified_current_condition_semantics_and_completeness", condition_audit_unproven=[]
   - Injecting 1f0a42bc20 legacy pairing -> Unsupported; 2ed00abd6c incomplete -> MissingDependency;
     early 11+3 -> InvalidDomain; tampered claimed_ns -> IdentityConflict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

LATE_UNPROVEN = [
    "condition_semantics_pairing_table_2ed00abd6c",
    "required_four_capabilities_completeness_b66b61a0b0",
]
EARLY_UNPROVEN = [
    "model_coverage_condition_1f0a42bc20",
    "condition_semantics_pairing_table_2ed00abd6c",
    "required_four_capabilities_completeness_b66b61a0b0",
]


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_sealed(db_path: Path) -> dict[str, dict]:
    out = {}
    for p in [db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")]:
        if p.exists():
            out[p.name] = {"sha256": sha256_file(p), "size": p.stat().st_size}
    return out


def snapshot_db_and_wal(db_path: Path) -> dict[str, dict]:
    """Snapshot durable SQLite bytes (.db and -wal), excluding volatile -shm wal-index."""
    out = {}
    for p in [db_path, Path(str(db_path) + "-wal")]:
        if p.exists():
            out[p.name] = {"sha256": sha256_file(p), "size": p.stat().st_size}
    return out


def copy_sqlite_set(src_db: Path, dst_dir: Path, name: str | None = None) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    target = dst_dir / (name or src_db.name)
    shutil.copy2(src_db, target)
    for suffix in ("-wal", "-shm"):
        side = Path(str(src_db) + suffix)
        if side.exists():
            shutil.copy2(side, Path(str(target) + suffix))
    return target


def run_cli(bin_path: Path, args: list[str], *, expect_ok: bool = True, expect_err: str | None = None):
    proc = subprocess.run([str(bin_path), *args], capture_output=True, text=True, timeout=30)
    if expect_ok:
        assert proc.returncode == 0, (
            f"expected rc=0 for {bin_path.name} {args}, got rc={proc.returncode}\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}"
        )
        return json.loads(proc.stdout)
    assert proc.returncode != 0, f"expected non-zero for {bin_path.name} {args}, got rc=0\nstdout={proc.stdout}"
    assert not proc.stdout.strip(), f"expected empty stdout on failure for {args}, got {proc.stdout}"
    if expect_err:
        assert expect_err in proc.stderr, f"expected {expect_err!r} in stderr for {args}, got {proc.stderr!r}"
    return {"returncode": proc.returncode, "stderr": proc.stderr.strip()}


def assert_strict_int(val, expected: int, label: str):
    assert type(val) is int and val == expected, f"{label}: expected int {expected}, got {type(val).__name__} {val!r}"


def dummy_v3_profile_json(prof: dict, serve_dir: Path) -> dict:
    conditions = [
        {
            "condition_id": "released-exact/1",
            "authority_revision": "released-exact/1",
            "validator_capability": "released-exact/1",
            "required_check_stages": ["E.ReleaseExact"],
            "dependency_set": ["d"],
            "evidence_refs": ["e"],
            "invalidation_sources": ["i"],
            "coverage_proof": "p",
            "failure_result": "Denied",
        },
        {
            "condition_id": "model_coverage",
            "authority_revision": "model-coverage/1",
            "validator_capability": "model-coverage/1",
            "required_check_stages": ["E.ReleaseExact"],
            "dependency_set": ["d"],
            "evidence_refs": ["e"],
            "invalidation_sources": ["i"],
            "coverage_proof": "p",
            "failure_result": "Denied",
        },
        {
            "condition_id": "execute-committed/1",
            "authority_revision": "execute-committed/1",
            "validator_capability": "execute-committed/1",
            "required_check_stages": ["S.RequestConditionalExecution"],
            "dependency_set": ["d"],
            "evidence_refs": ["e"],
            "invalidation_sources": ["i"],
            "coverage_proof": "p",
            "failure_result": "Denied",
        },
        {
            "condition_id": "simulation-local-transaction/1",
            "authority_revision": "simulation-local-transaction/1",
            "validator_capability": "simulation-local-transaction/1",
            "required_check_stages": ["X.OwnAttemptAndCall"],
            "dependency_set": ["d"],
            "evidence_refs": ["e"],
            "invalidation_sources": ["i"],
            "coverage_proof": "p",
            "failure_result": "Denied",
        },
    ]
    return {
        "profile_revision": "x-execution-profile/3",
        "mode": "simulation",
        "endpoint": None,
        "tb09_fingerprint": None,
        "credential_scope": {"env": "NC_X_CRED"},
        "history_simulation": {
            "model": prof["model"],
            "session_id": prof["session_id"],
            "session_generation": prof["session_generation"],
            "x_id": prof["x_id"],
            "source_namespace": prof["source_namespace"],
            "source_epoch": prof["source_epoch"],
            "socket": str(serve_dir / "x.sock"),
            "e": {
                "socket": str(serve_dir / "e.sock"),
                "authority_id": prof["e"]["authority_id"],
                "authority_epoch": prof["e"]["authority_epoch"],
                "schema_revision": "economic-session/1",
                "reply_namespace": "e.reply",
                "producer_id": "E",
            },
            "s": {
                "socket": str(serve_dir / "s.sock"),
                "authority_id": prof["s"]["authority_id"],
                "authority_epoch": prof["s"]["authority_epoch"],
                "schema_revision": "structure-session/1",
                "reply_namespace": "s.reply",
                "producer_id": "S",
            },
            "conditions": conditions,
            "timeout_ms": prof["timeout_ms"],
            "max_frame_bytes": prof["max_frame_bytes"],
        },
    }


def run_fixture_e_fixed_batch(
    e_bin: Path,
    e_dir: Path,
    unmodified_x_copy: Path,
    prof: dict,
    batch_id: str,
    batch_sha: str,
    model_hash: str,
    expected_fill: dict,
    expected_fee: dict,
) -> dict:
    """Exercise intake.rs fixed-batch readback on an UNMODIFIED X working copy with native decimal session_generation.
    Explicitly represents a newly initialized fixture E (not a pre-existing original E cut/liability)."""
    e_dir.mkdir(parents=True, exist_ok=True)
    e_db = e_dir / "e.sqlite"
    e_manifest = e_dir / "e-manifest.json"
    principal = {
        "source_namespace": prof["source_namespace"],
        "source_epoch": prof["source_epoch"],
        "producer_id": prof["x_id"],
        "producer_epoch": "1",
    }
    e_manifest.write_text(
        canonical(
            {
                "schema_revision": "economic-manifest/1",
                "session_id": prof["session_id"],
                "session_generation": prof["session_generation"],
                "book_revision": "tb03c-book/1",
                "e": {"db": str(e_db), "socket": str(e_dir / "e.sock")},
                "chongs": [
                    {
                        "chong_id": "ch-a",
                        "symbol": prof["model"]["symbol"],
                        "operation_level": "1",
                        "fixed_q": "10",
                        "db": str(e_dir / "b.sqlite"),
                        "socket": str(e_dir / "b.sock"),
                    }
                ],
                "authorized_sources": [
                    {**principal, "operations": ["CaptureExternal", "QueryFact", "ReadView", "ResolveEvidence"]}
                ],
                "history_simulation_source": {
                    **principal,
                    "x_db": str(unmodified_x_copy),
                    "model_content_hash": model_hash,
                },
                "resources": {
                    "max_frame_bytes": "1048576",
                    "read_timeout_ms": "1000",
                    "write_timeout_ms": "1000",
                    "response_timeout_ms": "10000",
                    "queue_capacity": "2",
                    "max_connections": "2",
                },
                "clock": {"kind": "System"},
            }
        )
    )
    init_out = run_cli(e_bin, ["init", "--manifest", str(e_manifest), "--db", str(e_db)])
    assert init_out["kind"] == "Initialized"
    inspected = run_cli(
        e_bin,
        [
            "inspect-simulation-capture-batch",
            "--manifest",
            str(e_manifest),
            "--db",
            str(e_db),
            "--batch-id",
            batch_id,
            "--batch-receipt-sha256",
            batch_sha,
            "--x-id",
            prof["x_id"],
            "--x-epoch",
            "1",
        ],
    )
    assert inspected["kind"] == "SimulationCaptureBatch"
    assert inspected["batch_receipt_sha256"] == batch_sha
    assert [entry["raw_utf8"] for entry in inspected["entries"]] == [
        canonical(expected_fill),
        canonical(expected_fee),
    ]
    return {
        "note": "fixture_e_unmodified_x_working_copy_not_original_e_liability",
        "session_generation": prof["session_generation"],
        "batch_id": batch_id,
        "batch_receipt_sha256": batch_sha,
        "entry_count": len(inspected["entries"]),
        "fill_fee_exact_raw_utf8_match": True,
    }


def verify_observed_case(
    name: str,
    case_dir: Path,
    x_bin: Path,
    e_bin: Path,
    work_root: Path,
    *,
    expected_layout: str,
    expected_claimed_policy: str,
    expected_cond_policy: str,
    expected_unproven: list[str],
    test_tampered_bar: bool,
) -> dict:
    sealed_db = case_dir / "sealed" / "old.db"
    sealed_before = snapshot_sealed(sealed_db)

    wire_cmd = json.loads((case_dir / "query-command.reply.wire").read_text())
    wire_batch_text = (case_dir / "query-batch.reply.wire").read_text().strip()
    wire_batch = json.loads(wire_batch_text)
    wire_fill_text = (case_dir / "query-original-fill.reply.wire").read_text().strip()
    wire_fill = json.loads(wire_fill_text)
    wire_fee_text = (case_dir / "query-original-fee.reply.wire").read_text().strip()
    wire_fee = json.loads(wire_fee_text)

    cmd_id = wire_cmd["command_id"]
    batch_id = wire_batch["request_id"]
    fill_id = json.loads((case_dir / "query-original-fill.request.wire").read_text())["payload"]
    fee_id = json.loads((case_dir / "query-original-fee.request.wire").read_text())["payload"]

    forensic_dir = work_root / f"case-{name}" / "forensic"
    work_db = copy_sqlite_set(sealed_db, forensic_dir, "old.db")

    hist = run_cli(x_bin, ["query-history", "--db", str(work_db)])
    assert hist["kind"] == "HistorySimulationArchiveSummary"
    assert hist["read_only"] is True
    assert hist["profile_revision"] == "x-execution-profile/1"
    assert hist["archive_layout"] == expected_layout
    assert hist["execute_evidence_claimed_ns_audit_policy"] == expected_claimed_policy
    assert hist["condition_audit_policy"] == expected_cond_policy
    assert hist["condition_audit_unproven"] == expected_unproven
    assert hist["last_committed_batch_id"] == batch_id
    assert [c["command_id"] for c in hist["commands"]] == [cmd_id]
    assert hist["originals"] == [fill_id, fee_id]

    cmd = run_cli(x_bin, ["query-command", "--db", str(work_db), "--command-id", cmd_id])
    assert cmd["kind"] == wire_cmd["kind"] == "ExactCommandState"
    assert cmd["command_id"] == wire_cmd["command_id"] == cmd_id
    assert cmd["state"] == wire_cmd["state"]
    assert cmd["x_accept"] == wire_cmd["x_accept"]
    for k in ("received_ns", "first_known_ns", "commit_ns"):
        assert_strict_int(cmd["x_accept"][k], wire_cmd["x_accept"][k], f"{name}.x_accept.{k}")
    assert cmd["causal_refs"] == wire_cmd["causal_refs"]
    assert_strict_int(
        cmd["causal_refs"][0]["release_commit_ns"],
        wire_cmd["causal_refs"][0]["release_commit_ns"],
        f"{name}.causal_refs[0].release_commit_ns",
    )
    assert cmd["archive_layout"] == expected_layout
    assert cmd["execute_evidence_claimed_ns_audit"] == expected_claimed_policy
    assert cmd["condition_audit_policy"] == expected_cond_policy
    assert cmd["condition_audit_unproven"] == expected_unproven
    assert cmd["has_execute_evidence"] is True
    assert_strict_int(
        cmd["execute_evidence"]["claimed_ns"],
        cmd["attempt_batch_bar_index"],
        f"{name}.claimed_ns==attempt_bar",
    )

    batch = run_cli(x_bin, ["query-batch", "--db", str(work_db), "--batch-id", batch_id])
    assert canonical(batch) == wire_batch_text, f"{name}: query-batch mismatch vs original socket wire!"
    fill = run_cli(x_bin, ["query-original", "--db", str(work_db), "--original-id", fill_id])
    assert canonical(fill) == wire_fill_text, f"{name}: query-original fill mismatch vs original socket wire!"
    fee = run_cli(x_bin, ["query-original", "--db", str(work_db), "--original-id", fee_id])
    assert canonical(fee) == wire_fee_text, f"{name}: query-original fee mismatch vs original socket wire!"

    # Check fill & fee exact semantics (quantity, price, amount, fee, cause)
    assert fill["event"]["kind"] == "fill"
    assert fill["event"]["fill"]["command_id"] == cmd_id
    assert fee["event"]["kind"] == "fee"
    assert fee["event"]["command_id"] == cmd_id
    assert fee["event"]["cause"] == {"kind": "fill", "exec_id": fill_id}
    assert_strict_int(fee["event"]["amount"], fill["event"]["fill"]["fee"], f"{name}.fee==fill.fee")

    # Serve refusal without modifying bytes or creating lock
    serve_dir = work_root / f"case-{name}" / "serve-refusal"
    serve_db = copy_sqlite_set(sealed_db, serve_dir, "old.db")
    serve_before = snapshot_db_and_wal(serve_db)
    with sqlite3.connect(work_db.as_uri() + "?mode=ro", uri=True) as c:
        prof = json.loads(c.execute("SELECT v FROM x_sim_meta WHERE k='authority_profile'").fetchone()[0])
    v3_prof_path = serve_dir / "x-v3-profile.json"
    v3_prof_path.write_text(canonical(dummy_v3_profile_json(prof, serve_dir)))
    serve_refusal = run_cli(
        x_bin,
        ["serve", "--db", str(serve_db), "--profile", str(v3_prof_path), "--writer-epoch", "1"],
        expect_ok=False,
        expect_err="VersionUnsupported",
    )
    serve_after = snapshot_db_and_wal(serve_db)
    assert serve_after == serve_before, f"{name}: serve refusal mutated DB/WAL! before={serve_before} after={serve_after}"
    assert not Path(str(serve_db) + ".writer.lock").exists()

    # Fixture E fixed-batch read on UNMODIFIED working copy (native session_generation="1")
    b_sha = next(b["batch_receipt_sha256"] for b in hist["committed_batches"] if b["batch_id"] == batch_id)
    e_copy = copy_sqlite_set(sealed_db, work_root / f"case-{name}" / "e-x-copy", "old.db")
    e_result = run_fixture_e_fixed_batch(
        e_bin,
        work_root / f"case-{name}" / "e-fixed-batch",
        e_copy,
        prof,
        batch_id,
        b_sha,
        batch["model_content_hash"],
        fill,
        fee,
    )

    tampered_bar_err = None
    if test_tampered_bar:
        bad_bar_db = copy_sqlite_set(sealed_db, work_root / f"case-{name}" / "bad-bar", "old.db")
        with sqlite3.connect(bad_bar_db) as c:
            raw_exec = c.execute("SELECT execute_evidence FROM x_exact_commands WHERE id=?", (cmd_id,)).fetchone()[0]
            ev = json.loads(raw_exec)
            ev["claimed_ns"] = 1795111790994769493
            c.execute("UPDATE x_exact_commands SET execute_evidence=? WHERE id=?", (canonical(ev), cmd_id))
            c.commit()
        tampered_bar_err = run_cli(
            x_bin,
            ["query-command", "--db", str(bad_bar_db), "--command-id", cmd_id],
            expect_ok=False,
            expect_err="IdentityConflict",
        )["stderr"]

    sealed_after = snapshot_sealed(sealed_db)
    assert sealed_after == sealed_before, f"{name}: sealed original changed!"

    return {
        "archive_layout": hist["archive_layout"],
        "claimed_ns_audit_policy": hist["execute_evidence_claimed_ns_audit_policy"],
        "condition_audit_policy": hist["condition_audit_policy"],
        "condition_audit_unproven": hist["condition_audit_unproven"],
        "wire_parity": {
            "query_batch_exact_wire_match": True,
            "query_original_fill_exact_wire_match": True,
            "query_original_fee_exact_wire_match": True,
            "query_command_meaning_match": {
                "command_id": cmd_id,
                "state": cmd["state"],
                "x_accept": cmd["x_accept"],
                "causal_refs_count": len(cmd["causal_refs"]),
                "attempt_batch_bar_index": cmd["attempt_batch_bar_index"],
                "claimed_ns": cmd["execute_evidence"]["claimed_ns"],
            },
            "fill_summary": {
                "exec_id": fill["event"]["fill"]["exec_id"],
                "quantity": fill["event"]["fill"]["quantity"],
                "price": fill["event"]["fill"]["price"],
                "amount": fill["event"]["fill"]["amount"],
                "fee": fill["event"]["fill"]["fee"],
            },
            "fee_summary": {
                "amount": fee["event"]["amount"],
                "cause": fee["event"]["cause"],
            },
        },
        "serve_refusal_stderr": serve_refusal["stderr"],
        "tampered_claimed_ns_stderr": tampered_bar_err,
        "fixture_e_fixed_batch": e_result,
        "sealed_untouched": True,
        "sealed_files": sealed_after,
    }


def verify_early_r4_g1(
    x_bin: Path,
    e_bin: Path,
    sealed_old_db: Path,
    early_observed_json: Path,
    work_root: Path,
) -> dict:
    sealed_before = snapshot_sealed(sealed_old_db)
    expected_ref = json.loads(early_observed_json.read_text())

    forensic_dir = work_root / "early-r4-g1" / "forensic"
    work_db = copy_sqlite_set(sealed_old_db, forensic_dir, "old.db")

    hist = run_cli(x_bin, ["query-history", "--db", str(work_db)])
    assert hist["profile_revision"] == "x-execution-profile/1"
    assert hist["archive_layout"] == "v1_early"
    assert hist["session_generation"] == "g1"
    assert hist["execute_evidence_claimed_ns_audit_policy"] == "raw_claim_only_non_retroactive_v1"
    assert hist["condition_audit_policy"] == "v1_early_frozen_three_conditions"
    assert hist["condition_audit_unproven"] == EARLY_UNPROVEN
    assert hist["last_committed_batch_id"] == "b3"
    assert hist["originals"] == ["3:f-early-wall:1", "fee:3:f-early-wall:1"]

    cmd = run_cli(x_bin, ["query-command", "--db", str(work_db), "--command-id", "early-wall"])
    ref_ws = expected_ref["writer_socket_state"]
    assert cmd["state"] == ref_ws["state"] == "Observed"
    assert cmd["x_accept"] == ref_ws["x_accept"]
    assert cmd["causal_refs"] == ref_ws["causal_refs"]
    assert cmd["execute_evidence_claimed_ns_audit"] == "raw_claim_only_non_retroactive_v1"
    assert cmd["condition_audit_policy"] == "v1_early_frozen_three_conditions"
    assert cmd["condition_audit_unproven"] == EARLY_UNPROVEN
    assert_strict_int(cmd["execute_evidence"]["claimed_ns"], expected_ref["stored_claimed_ns"], "r4.claimed_ns")

    b3 = run_cli(x_bin, ["query-batch", "--db", str(work_db), "--batch-id", "b3"])
    fill = run_cli(x_bin, ["query-original", "--db", str(work_db), "--original-id", "3:f-early-wall:1"])
    fee = run_cli(x_bin, ["query-original", "--db", str(work_db), "--original-id", "fee:3:f-early-wall:1"])
    with sqlite3.connect(work_db.as_uri() + "?mode=ro", uri=True) as c:
        prof = json.loads(c.execute("SELECT v FROM x_sim_meta WHERE k='authority_profile'").fetchone()[0])
        raw_fill = json.loads(c.execute("SELECT raw FROM x_sim_originals WHERE id='3:f-early-wall:1'").fetchone()[0])
        raw_fee = json.loads(c.execute("SELECT raw FROM x_sim_originals WHERE id='fee:3:f-early-wall:1'").fetchone()[0])
    assert fill == raw_fill == b3["originals"][0]
    assert fee == raw_fee == b3["originals"][1]

    # Direct proof of historical X vs original E distinction:
    # e_economic_session init REJECTS non-decimal session_generation="g1" (no faked derivative g1->1 copy).
    e_dir = work_root / "early-r4-g1" / "e-reject-g1"
    e_dir.mkdir(parents=True, exist_ok=True)
    e_db = e_dir / "e.sqlite"
    e_manifest = e_dir / "e-manifest.json"
    principal = {
        "source_namespace": prof["source_namespace"],
        "source_epoch": prof["source_epoch"],
        "producer_id": prof["x_id"],
        "producer_epoch": "1",
    }
    e_manifest.write_text(
        canonical(
            {
                "schema_revision": "economic-manifest/1",
                "session_id": prof["session_id"],
                "session_generation": "g1",
                "book_revision": "tb03c-book/1",
                "e": {"db": str(e_db), "socket": str(e_dir / "e.sock")},
                "chongs": [
                    {
                        "chong_id": "ch-a",
                        "symbol": prof["model"]["symbol"],
                        "operation_level": "1",
                        "fixed_q": "10",
                        "db": str(e_dir / "b.sqlite"),
                        "socket": str(e_dir / "b.sock"),
                    }
                ],
                "authorized_sources": [
                    {**principal, "operations": ["CaptureExternal", "QueryFact", "ReadView", "ResolveEvidence"]}
                ],
                "history_simulation_source": {
                    **principal,
                    "x_db": str(work_db),
                    "model_content_hash": b3["model_content_hash"],
                },
                "resources": {
                    "max_frame_bytes": "1048576",
                    "read_timeout_ms": "1000",
                    "write_timeout_ms": "1000",
                    "response_timeout_ms": "10000",
                    "queue_capacity": "2",
                    "max_connections": "2",
                },
                "clock": {"kind": "System"},
            }
        )
    )
    e_g1_refusal = run_cli(
        e_bin,
        ["init", "--manifest", str(e_manifest), "--db", str(e_db)],
        expect_ok=False,
        expect_err="不是规范十进制整数",
    )

    # Serve refusal
    serve_dir = work_root / "early-r4-g1" / "serve-refusal"
    serve_db = copy_sqlite_set(sealed_old_db, serve_dir, "old.db")
    serve_before = snapshot_db_and_wal(serve_db)
    v3_prof_path = serve_dir / "x-v3-profile.json"
    v3_prof_path.write_text(canonical(dummy_v3_profile_json(prof, serve_dir)))
    serve_refusal = run_cli(
        x_bin,
        ["serve", "--db", str(serve_db), "--profile", str(v3_prof_path), "--writer-epoch", "1"],
        expect_ok=False,
        expect_err="VersionUnsupported",
    )
    assert snapshot_db_and_wal(serve_db) == serve_before
    assert not Path(str(serve_db) + ".writer.lock").exists()

    sealed_after = snapshot_sealed(sealed_old_db)
    assert sealed_after == sealed_before
    return {
        "archive_layout": hist["archive_layout"],
        "session_generation": hist["session_generation"],
        "claimed_ns_audit_policy": hist["execute_evidence_claimed_ns_audit_policy"],
        "condition_audit_policy": hist["condition_audit_policy"],
        "condition_audit_unproven": hist["condition_audit_unproven"],
        "stored_wall_clock_claimed_ns": cmd["execute_evidence"]["claimed_ns"],
        "e_init_g1_rejection_stderr": e_g1_refusal["stderr"],
        "serve_refusal_stderr": serve_refusal["stderr"],
        "sealed_untouched": True,
        "sealed_files": sealed_after,
    }


def verify_corrupt_and_non_weakening(
    x_bin: Path,
    r5_observed: Path,
    issue2078_sql: Path,
    v2_db_src: Path,
    v3_db_src: Path,
    work_root: Path,
) -> dict:
    results = {}

    # 1. Real R5 broken fixture: late-2078-missing-e-schema
    broken_src = r5_observed / "late-2078-missing-e-schema" / "working" / "old.db"
    broken_copy = copy_sqlite_set(broken_src, work_root / "neg-missing-e-schema", "broken.db")
    results["real_missing_e_schema"] = {
        "query_history": run_cli(x_bin, ["query-history", "--db", str(broken_copy)], expect_ok=False, expect_err="InvalidDomain")["stderr"],
        "query_command": run_cli(x_bin, ["query-command", "--db", str(broken_copy), "--command-id", "c1"], expect_ok=False, expect_err="InvalidDomain")["stderr"],
        "query_batch": run_cli(x_bin, ["query-batch", "--db", str(broken_copy), "--batch-id", "b0"], expect_ok=False, expect_err="InvalidDomain")["stderr"],
        "query_original": run_cli(x_bin, ["query-original", "--db", str(broken_copy), "--original-id", "missing"], expect_ok=False, expect_err="InvalidDomain")["stderr"],
    }

    # 2. #2078 late /1 positive control + tampered claimed_ns negative control
    db2078 = work_root / "issue2078" / "x-profile-1.db"
    db2078.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db2078) as c:
        c.executescript(issue2078_sql.read_text())
        c.commit()
    h2078 = run_cli(x_bin, ["query-history", "--db", str(db2078)])
    assert h2078["archive_layout"] == "v1_late"
    assert h2078["execute_evidence_claimed_ns_audit_policy"] == "verified_equal_to_attempt_bar"
    assert h2078["condition_audit_policy"] == "v1_late_common_12_6_invariants_only"
    assert h2078["condition_audit_unproven"] == LATE_UNPROVEN
    results["issue2078_control"] = {
        "archive_layout": h2078["archive_layout"],
        "condition_audit_policy": h2078["condition_audit_policy"],
        "condition_audit_unproven": h2078["condition_audit_unproven"],
        "last_committed_batch_id": h2078["last_committed_batch_id"],
    }

    # 3. Late /1 common-invariant negative controls built from real late-intro-legacy-pair copy
    late_src = r5_observed / "late-intro-legacy-pair" / "sealed" / "old.db"

    def mutate_late_profile(tag: str, mutator, expect_err: str) -> str:
        db = copy_sqlite_set(late_src, work_root / f"neg-late-{tag}", "old.db")
        with sqlite3.connect(db) as c:
            prof = json.loads(c.execute("SELECT v FROM x_sim_meta WHERE k='authority_profile'").fetchone()[0])
            mutator(c, prof)
            c.execute("UPDATE x_sim_meta SET v=? WHERE k='authority_profile'", (canonical(prof),))
            c.commit()
        return run_cli(x_bin, ["query-history", "--db", str(db)], expect_ok=False, expect_err=expect_err)["stderr"]

    def mut_bad_x_cap(_c, prof):
        for cond in prof["conditions"]:
            if any(s.startswith("X.") for s in cond["required_check_stages"]):
                cond["validator_capability"] = "venue-call/1"
                cond["authority_revision"] = "venue-call/1"

    def mut_no_model_cov(_c, prof):
        prof["conditions"] = [c for c in prof["conditions"] if c["condition_id"] != "model_coverage"]

    def mut_cond_mismatch(_c, prof):
        prof["conditions"][0]["coverage_proof"] = "tampered-proof"

    def mut_hybrid_12_3(_c, prof):
        for k in ("schema_revision", "reply_namespace", "producer_id"):
            prof["e"].pop(k)
            prof["s"].pop(k)

    def mut_inner_rev(c, _prof):
        c.execute("INSERT INTO x_sim_meta VALUES('exact_profile_revision','x-execution-profile/3')")

    results["late_v1_common_invariant_negatives"] = {
        "unsupported_x_capability": mutate_late_profile("bad-x-cap", mut_bad_x_cap, "Unsupported"),
        "missing_model_coverage": mutate_late_profile("no-model-cov", mut_no_model_cov, "MissingDependency"),
        "command_profile_cond_mismatch": mutate_late_profile("cond-mismatch", mut_cond_mismatch, "Unsupported"),
        "hybrid_12_with_3": mutate_late_profile("hybrid-12-3", mut_hybrid_12_3, "InvalidDomain"),
        "unexpected_inner_revision": mutate_late_profile("inner-rev", mut_inner_rev, "VersionUnsupported"),
    }

    # 4. Early /1 negative control: claimed_ns < S.commit_ns -> IdentityConflict
    early_src = r5_observed / "early-1942-logical-bar" / "sealed" / "old.db"
    early_lt = copy_sqlite_set(early_src, work_root / "neg-early-lt", "old.db")
    with sqlite3.connect(early_lt) as c:
        ev = json.loads(c.execute("SELECT execute_evidence FROM x_exact_commands WHERE id='witness'").fetchone()[0])
        ev["claimed_ns"] = ev["reply"]["commit_ns"] - 1
        c.execute("UPDATE x_exact_commands SET execute_evidence=? WHERE id='witness'", (canonical(ev),))
        c.commit()
    results["early_v1_claimed_lt_commit"] = run_cli(
        x_bin, ["query-history", "--db", str(early_lt)], expect_ok=False, expect_err="IdentityConflict"
    )["stderr"]

    # 5. /2 and /3 real archives + strict non-weakening against 1f0a42bc20 & 2ed00abd6c conditions + early 11+3
    conds_1f0a = json.loads((r5_observed / "late-intro-legacy-pair" / "profile.json").read_text())["history_simulation"]["conditions"]
    conds_2ed0 = json.loads((r5_observed / "late-middle-pair-valid-incomplete" / "profile.json").read_text())["history_simulation"]["conditions"]
    early_11_3_prof = json.loads((r5_observed / "early-1942-logical-bar" / "profile.json").read_text())["history_simulation"]

    strict_out = {}
    for label, src_db, expected_rev in [
        ("v2", v2_db_src, "x-execution-profile/2"),
        ("v3", v3_db_src, "x-execution-profile/3"),
    ]:
        src_before = snapshot_sealed(src_db)
        work_db = copy_sqlite_set(src_db, work_root / f"strict-{label}" / "ok", src_db.name)
        h = run_cli(x_bin, ["query-history", "--db", str(work_db)])
        assert h["profile_revision"] == expected_rev
        assert h["archive_layout"] == label
        assert h["execute_evidence_claimed_ns_audit_policy"] == "verified_equal_to_attempt_bar"
        assert h["condition_audit_policy"] == "verified_current_condition_semantics_and_completeness"
        assert h["condition_audit_unproven"] == []

        def inject_strict(tag: str, mut_fn, expect_err: str) -> str:
            db = copy_sqlite_set(src_db, work_root / f"strict-{label}" / tag, src_db.name)
            with sqlite3.connect(db) as c:
                prof = json.loads(c.execute("SELECT v FROM x_sim_meta WHERE k='authority_profile'").fetchone()[0])
                new_prof = mut_fn(prof)
                c.execute("UPDATE x_sim_meta SET v=? WHERE k='authority_profile'", (canonical(new_prof),))
                c.commit()
            return run_cli(x_bin, ["query-history", "--db", str(db)], expect_ok=False, expect_err=expect_err)["stderr"]

        strict_out[label] = {
            "ok_policy": h["condition_audit_policy"],
            "ok_unproven": h["condition_audit_unproven"],
            "reject_1f0a_legacy_pair": inject_strict("legacy-1f0a", lambda p: {**p, "conditions": conds_1f0a}, "Unsupported"),
            "reject_2ed0_incomplete": inject_strict("incomplete-2ed0", lambda p: {**p, "conditions": conds_2ed0}, "MissingDependency"),
            "reject_early_11_3_downgrade": inject_strict("early-11-3", lambda _p: early_11_3_prof, "InvalidDomain"),
            "source_untouched": snapshot_sealed(src_db) == src_before,
        }
        assert strict_out[label]["source_untouched"]
    results["strict_v2_v3_non_weakening"] = strict_out
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--x-bin", type=Path, required=True)
    ap.add_argument("--e-bin", type=Path, required=True)
    ap.add_argument("--r5-observed", type=Path, required=True)
    ap.add_argument("--r4-early-db", type=Path, required=True)
    ap.add_argument("--r4-early-observed", type=Path, required=True)
    ap.add_argument("--issue2078-sql", type=Path, required=True)
    ap.add_argument("--v2-db", type=Path, required=True)
    ap.add_argument("--v3-db", type=Path, required=True)
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()

    if args.work_dir.exists():
        shutil.rmtree(args.work_dir)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "late_intro_legacy_pair_1f0a42bc20": verify_observed_case(
            "late-intro-legacy-pair",
            args.r5_observed / "late-intro-legacy-pair",
            args.x_bin,
            args.e_bin,
            args.work_dir,
            expected_layout="v1_late",
            expected_claimed_policy="verified_equal_to_attempt_bar",
            expected_cond_policy="v1_late_common_12_6_invariants_only",
            expected_unproven=LATE_UNPROVEN,
            test_tampered_bar=True,
        ),
        "late_middle_pair_valid_incomplete_2ed00abd6c": verify_observed_case(
            "late-middle-pair-valid-incomplete",
            args.r5_observed / "late-middle-pair-valid-incomplete",
            args.x_bin,
            args.e_bin,
            args.work_dir,
            expected_layout="v1_late",
            expected_claimed_policy="verified_equal_to_attempt_bar",
            expected_cond_policy="v1_late_common_12_6_invariants_only",
            expected_unproven=LATE_UNPROVEN,
            test_tampered_bar=True,
        ),
        "late_lemmas_control_1f0a42bc20": verify_observed_case(
            "late-lemmas-control",
            args.r5_observed / "late-lemmas-control",
            args.x_bin,
            args.e_bin,
            args.work_dir,
            expected_layout="v1_late",
            expected_claimed_policy="verified_equal_to_attempt_bar",
            expected_cond_policy="v1_late_common_12_6_invariants_only",
            expected_unproven=LATE_UNPROVEN,
            test_tampered_bar=True,
        ),
        "early_1942_logical_bar_3cd162ea4c": verify_observed_case(
            "early-1942-logical-bar",
            args.r5_observed / "early-1942-logical-bar",
            args.x_bin,
            args.e_bin,
            args.work_dir,
            expected_layout="v1_early",
            expected_claimed_policy="raw_claim_only_non_retroactive_v1",
            expected_cond_policy="v1_early_frozen_three_conditions",
            expected_unproven=EARLY_UNPROVEN,
            test_tampered_bar=False,
        ),
        "early_r4_wall_clock_18446a3d35_g1": verify_early_r4_g1(
            args.x_bin,
            args.e_bin,
            args.r4_early_db,
            args.r4_early_observed,
            args.work_dir,
        ),
        "corrupt_and_non_weakening": verify_corrupt_and_non_weakening(
            args.x_bin,
            args.r5_observed,
            args.issue2078_sql,
            args.v2_db,
            args.v3_db,
            args.work_dir,
        ),
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"R6 verification PASS -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
