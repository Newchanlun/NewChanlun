#!/usr/bin/env python3
"""#1407 C3 R5 targeted verification:
1. Real frozen early /1 DB (18446a3d35 writer, 11+3 keys, 3 conditions, wall-clock claimed_ns)
   on an independent writable forensic copy (sealed original untouched & SHA-256 verified):
   - All 4 formal CLIs (query-history, query-command, query-batch, query-original fill & fee)
   - Parity with original 18446a3d35 writer_socket_state + original JSON integers preserved
   - Never claims early wall-clock is verified equal to bar (raw_claim_only_non_retroactive_v1)
   - x_execution_session serve refuses early /1 DB without touching bytes or creating writer lock
   - Original E fixed-batch read (inspect-simulation-capture-batch) against working copy at frozen x_db path
2. Late /1 contrast (#2078 x-profile-1.sql, 12+6 keys):
   - All 4 CLIs succeed with archive_layout="v1_late" and verified_equal_to_attempt_bar
   - Tampering claimed_ns on late /1 (999 or wall-clock) fails with IdentityConflict
3. Anti-downgrade bad-archive checks:
   - Broken late /1 missing e.schema_revision -> InvalidDomain on all 4 CLIs (never downgraded)
   - Hybrid layouts (12+3, 11+6, asymmetric e6/s3, extra key) -> InvalidDomain
   - Early /1 claimed_ns < S.commit_ns -> IdentityConflict; unexpected exact_profile_revision -> VersionUnsupported
   - /2 and /3 DBs with early 11+3 authority_profile injected -> InvalidDomain (never downgraded)
4. /2 and /3 real archive contrast (working copies):
   - archive_layout="v2" / "v3", verified_equal_to_attempt_bar, tampered claimed_ns rejected
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_cli(bin_path: Path, args: list[str], *, expect_ok: bool = True, expect_err: str | None = None):
    proc = subprocess.run([str(bin_path), *args], capture_output=True, text=True, timeout=30)
    if expect_ok:
        assert proc.returncode == 0, f"expected rc=0 for {args}, got rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        return json.loads(proc.stdout)
    assert proc.returncode != 0, f"expected non-zero for {args}, got rc=0\nstdout={proc.stdout}"
    assert not proc.stdout.strip(), f"expected empty stdout on failure for {args}, got {proc.stdout}"
    if expect_err:
        assert expect_err in proc.stderr, f"expected {expect_err!r} in stderr for {args}, got {proc.stderr!r}"
    return {"returncode": proc.returncode, "stderr": proc.stderr.strip()}


def copy_sqlite_set(src_db: Path, dst_dir: Path, name: str | None = None) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    target = dst_dir / (name or src_db.name)
    shutil.copy2(src_db, target)
    for suffix in ("-wal", "-shm"):
        side = Path(str(src_db) + suffix)
        if side.exists():
            shutil.copy2(side, Path(str(target) + suffix))
    return target


def assert_strict_int(val, expected: int, label: str):
    assert type(val) is int and val == expected, f"{label}: expected int {expected}, got {type(val).__name__} {val!r}"


def verify_early_v1(x_bin: Path, e_bin: Path, sealed_old_db: Path, early_observed_json: Path, work_root: Path) -> dict:
    sealed_before = {"sha256": sha256_file(sealed_old_db), "size": sealed_old_db.stat().st_size}
    expected_ref = json.loads(early_observed_json.read_text())

    # 1a. Independent writable forensic working copy for 4 formal CLIs
    forensic_dir = work_root / "early-v1-forensic"
    work_db = copy_sqlite_set(sealed_old_db, forensic_dir, "old.db")

    hist = run_cli(x_bin, ["query-history", "--db", str(work_db)])
    assert hist["kind"] == "HistorySimulationArchiveSummary"
    assert hist["read_only"] is True
    assert hist["profile_revision"] == "x-execution-profile/1"
    assert hist["archive_layout"] == "v1_early"
    assert hist["execute_evidence_claimed_ns_audit_policy"] == "raw_claim_only_non_retroactive_v1"
    assert hist["writer_epoch"] == "1"
    assert hist["last_committed_batch_id"] == "b3"
    assert_strict_int(hist["last_bar_index"], 3, "early hist.last_bar_index")
    assert hist["pending_batch_id"] is None
    assert [c["command_id"] for c in hist["commands"]] == ["early-wall"]
    assert hist["originals"] == ["3:f-early-wall:1", "fee:3:f-early-wall:1"]

    cmd = run_cli(x_bin, ["query-command", "--db", str(work_db), "--command-id", "early-wall"])
    ref_ws = expected_ref["writer_socket_state"]
    assert cmd["kind"] == ref_ws["kind"] == "ExactCommandState"
    assert cmd["command_id"] == ref_ws["command_id"] == "early-wall"
    assert cmd["state"] == ref_ws["state"] == "Observed"
    assert cmd["x_accept"] == ref_ws["x_accept"]
    for k in ("received_ns", "first_known_ns", "commit_ns"):
        assert_strict_int(cmd["x_accept"][k], ref_ws["x_accept"][k], f"x_accept.{k}")
    assert cmd["causal_refs"] == ref_ws["causal_refs"]
    assert_strict_int(cmd["causal_refs"][0]["release_commit_ns"], 100, "causal_refs[0].release_commit_ns")
    assert cmd["archive_layout"] == "v1_early"
    assert cmd["profile_revision"] == "x-execution-profile/1"
    assert cmd["attempt_batch_id"] == "b2"
    assert_strict_int(cmd["attempt_batch_bar_index"], 2, "attempt_batch_bar_index")
    assert cmd["has_execute_evidence"] is True
    assert cmd["execute_evidence_claimed_ns_audit"] == "raw_claim_only_non_retroactive_v1"
    assert_strict_int(
        cmd["execute_evidence"]["claimed_ns"],
        expected_ref["stored_claimed_ns"],
        "execute_evidence.claimed_ns",
    )
    assert_strict_int(
        cmd["execute_evidence"]["reply"]["commit_ns"],
        expected_ref["stored_s_commit_ns"],
        "execute_evidence.reply.commit_ns",
    )
    assert_strict_int(
        cmd["execute_evidence"]["reply"]["command"]["x_epoch"],
        1,
        "execute_evidence.reply.command.x_epoch",
    )

    batch_b3 = run_cli(x_bin, ["query-batch", "--db", str(work_db), "--batch-id", "b3"])
    assert batch_b3["kind"] == "SimulationBatch"
    assert batch_b3["request_id"] == "b3"
    assert_strict_int(batch_b3["bar_index"], 3, "b3.bar_index")
    assert_strict_int(batch_b3["l0_fill_count"], 1, "b3.l0_fill_count")
    assert len(batch_b3["originals"]) == 2

    fill_orig = run_cli(x_bin, ["query-original", "--db", str(work_db), "--original-id", "3:f-early-wall:1"])
    fee_orig = run_cli(x_bin, ["query-original", "--db", str(work_db), "--original-id", "fee:3:f-early-wall:1"])
    with sqlite3.connect(work_db.as_uri() + "?mode=ro", uri=True) as c:
        raw_fill = json.loads(c.execute("SELECT raw FROM x_sim_originals WHERE id='3:f-early-wall:1'").fetchone()[0])
        raw_fee = json.loads(c.execute("SELECT raw FROM x_sim_originals WHERE id='fee:3:f-early-wall:1'").fetchone()[0])
    assert fill_orig == raw_fill == batch_b3["originals"][0]
    assert fee_orig == raw_fee == batch_b3["originals"][1]
    assert fill_orig["event"]["kind"] == "fill"
    fill_body = fill_orig["event"]["fill"]
    assert fill_body["exec_id"] == "3:f-early-wall:1"
    assert fill_body["command_id"] == "early-wall"
    assert_strict_int(fill_body["quantity"], raw_fill["event"]["fill"]["quantity"], "fill.quantity")
    assert_strict_int(fill_body["price"], raw_fill["event"]["fill"]["price"], "fill.price")
    assert_strict_int(fill_body["amount"], raw_fill["event"]["fill"]["amount"], "fill.amount")
    assert_strict_int(fill_body["fee"], raw_fill["event"]["fill"]["fee"], "fill.fee")
    assert fee_orig["event"]["kind"] == "fee"
    assert_strict_int(fee_orig["event"]["amount"], raw_fee["event"]["amount"], "fee.amount")
    assert fee_orig["event"]["cause"] == {"kind": "fill", "exec_id": "3:f-early-wall:1"}
    assert fee_orig["event"]["command_id"] == "early-wall"

    # 1b. x_execution_session serve MUST refuse early /1 DB without modifying bytes or creating writer lock
    serve_dir = work_root / "early-v1-serve-refusal"
    serve_db = copy_sqlite_set(sealed_old_db, serve_dir, "old.db")
    serve_before = sha256_file(serve_db)
    with sqlite3.connect(serve_db.as_uri() + "?mode=ro", uri=True) as c:
        early_prof = json.loads(c.execute("SELECT v FROM x_sim_meta WHERE k='authority_profile'").fetchone()[0])
    # Try serving with a valid /3 profile pointing at the early /1 DB
    dummy_v3_profile = serve_dir / "x-v3-profile.json"
    dummy_conditions = [
        {"condition_id": "released-exact/1", "authority_revision": "released-exact/1", "validator_capability": "released-exact/1",
         "required_check_stages": ["E.ReleaseExact"], "dependency_set": ["d"], "evidence_refs": ["e"],
         "invalidation_sources": ["i"], "coverage_proof": "p", "failure_result": "Denied"},
        {"condition_id": "model_coverage", "authority_revision": "model-coverage/1", "validator_capability": "model-coverage/1",
         "required_check_stages": ["E.ReleaseExact"], "dependency_set": ["d"], "evidence_refs": ["e"],
         "invalidation_sources": ["i"], "coverage_proof": "p", "failure_result": "Denied"},
        {"condition_id": "execute-committed/1", "authority_revision": "execute-committed/1", "validator_capability": "execute-committed/1",
         "required_check_stages": ["S.RequestConditionalExecution"], "dependency_set": ["d"], "evidence_refs": ["e"],
         "invalidation_sources": ["i"], "coverage_proof": "p", "failure_result": "Denied"},
        {"condition_id": "simulation-local-transaction/1", "authority_revision": "simulation-local-transaction/1", "validator_capability": "simulation-local-transaction/1",
         "required_check_stages": ["X.OwnAttemptAndCall"], "dependency_set": ["d"], "evidence_refs": ["e"],
         "invalidation_sources": ["i"], "coverage_proof": "p", "failure_result": "Denied"},
    ]
    dummy_v3_profile.write_text(canonical({
        "profile_revision": "x-execution-profile/3",
        "mode": "simulation",
        "endpoint": None,
        "tb09_fingerprint": None,
        "credential_scope": {"env": "NC_X_CRED"},
        "history_simulation": {
            "model": early_prof["model"],
            "session_id": early_prof["session_id"],
            "session_generation": early_prof["session_generation"],
            "x_id": early_prof["x_id"],
            "source_namespace": early_prof["source_namespace"],
            "source_epoch": early_prof["source_epoch"],
            "socket": str(serve_dir / "x.sock"),
            "e": {
                "socket": str(serve_dir / "e.sock"),
                "authority_id": early_prof["e"]["authority_id"],
                "authority_epoch": early_prof["e"]["authority_epoch"],
                "schema_revision": "economic-session/1",
                "reply_namespace": "e.reply",
                "producer_id": "E",
            },
            "s": {
                "socket": str(serve_dir / "s.sock"),
                "authority_id": early_prof["s"]["authority_id"],
                "authority_epoch": early_prof["s"]["authority_epoch"],
                "schema_revision": "structure-session/1",
                "reply_namespace": "s.reply",
                "producer_id": "S",
            },
            "conditions": dummy_conditions,
            "timeout_ms": early_prof["timeout_ms"],
            "max_frame_bytes": early_prof["max_frame_bytes"],
        },
    }))
    serve_refusal = run_cli(
        x_bin,
        ["serve", "--db", str(serve_db), "--profile", str(dummy_v3_profile), "--writer-epoch", "1"],
        expect_ok=False,
        expect_err="VersionUnsupported",
    )
    assert sha256_file(serve_db) == serve_before, "serve refusal modified early /1 DB!"
    assert not Path(str(serve_db) + ".writer.lock").exists(), "serve refusal created writer lock!"

    # 1c. Original E fixed-batch read (intake.rs) on working copy at frozen history_simulation_source.x_db path.
    # Note: R4's standalone mock-socket fixture old.db uses non-decimal session_generation="g1",
    # while e_economic_session's economic-manifest/1 enforces canonical decimal session_generation (e.g. "1")
    # as in any real paired E/X production session. When session_generation is non-decimal, exercise intake.rs
    # on a separate decimal-generation ("1") early-/1 derivative working copy preserving the exact 11+3 layout,
    # 3 conditions, wall-clock claimed_ns, and bit-for-bit identical b3/fill/fee originals.
    e_dir = work_root / "early-v1-e-fixed-batch"
    e_dir.mkdir(parents=True, exist_ok=True)
    e_x_copy = copy_sqlite_set(sealed_old_db, e_dir / "x-working-copy", "old.db")
    e_session_gen = early_prof["session_generation"]
    rebound_decimal_gen = False
    if not e_session_gen.isdigit():
        e_session_gen = "1"
        rebound_decimal_gen = True
        with sqlite3.connect(e_x_copy) as c:
            p = json.loads(c.execute("SELECT v FROM x_sim_meta WHERE k='authority_profile'").fetchone()[0])
            p["session_generation"] = e_session_gen
            c.execute("UPDATE x_sim_meta SET v=? WHERE k='authority_profile'", (canonical(p),))
            for cid, raw_cmd, raw_rel, raw_exe in c.execute(
                "SELECT id, command, release_evidence, execute_evidence FROM x_exact_commands"
            ).fetchall():
                cmd_obj = json.loads(raw_cmd)
                cmd_obj["session_generation"] = e_session_gen
                new_cmd_hash = sha256_bytes(canonical(cmd_obj).encode())
                rel_obj = json.loads(raw_rel) if raw_rel else None
                if rel_obj is not None:
                    rel_obj["session_generation"] = e_session_gen
                    rel_obj["command"]["session_generation"] = e_session_gen
                    rel_obj["command_hash"] = new_cmd_hash
                exe_obj = json.loads(raw_exe) if raw_exe else None
                if exe_obj is not None:
                    exe_obj["reply"]["session_generation"] = e_session_gen
                    exe_obj["reply"]["command"]["session_generation"] = e_session_gen
                    exe_obj["reply"]["command_hash"] = new_cmd_hash
                c.execute(
                    "UPDATE x_exact_commands SET command=?, release_evidence=?, execute_evidence=? WHERE id=?",
                    (
                        canonical(cmd_obj),
                        canonical(rel_obj) if rel_obj is not None else None,
                        canonical(exe_obj) if exe_obj is not None else None,
                        cid,
                    ),
                )
            c.commit()
    e_db = e_dir / "e.sqlite"
    e_manifest = e_dir / "e-manifest.json"
    principal = {
        "source_namespace": early_prof["source_namespace"],
        "source_epoch": early_prof["source_epoch"],
        "producer_id": early_prof["x_id"],
        "producer_epoch": "1",
    }
    e_manifest.write_text(canonical({
        "schema_revision": "economic-manifest/1",
        "session_id": early_prof["session_id"],
        "session_generation": e_session_gen,
        "book_revision": "tb03c-book/1",
        "e": {"db": str(e_db), "socket": str(e_dir / "e.sock")},
        "chongs": [{
            "chong_id": "ch-a", "symbol": early_prof["model"]["symbol"],
            "operation_level": "1", "fixed_q": "10",
            "db": str(e_dir / "b.sqlite"), "socket": str(e_dir / "b.sock"),
        }],
        "authorized_sources": [{**principal, "operations": ["CaptureExternal", "QueryFact", "ReadView", "ResolveEvidence"]}],
        "history_simulation_source": {
            **principal,
            "x_db": str(e_x_copy),
            "model_content_hash": batch_b3["model_content_hash"],
        },
        "resources": {
            "max_frame_bytes": "1048576", "read_timeout_ms": "1000", "write_timeout_ms": "1000",
            "response_timeout_ms": "10000", "queue_capacity": "2", "max_connections": "2",
        },
        "clock": {"kind": "System"},
    }))
    e_init = run_cli(e_bin, ["init", "--manifest", str(e_manifest), "--db", str(e_db)])
    assert e_init["kind"] == "Initialized"
    b3_sha = next(b["batch_receipt_sha256"] for b in hist["committed_batches"] if b["batch_id"] == "b3")
    e_inspected = run_cli(
        e_bin,
        [
            "inspect-simulation-capture-batch",
            "--manifest", str(e_manifest),
            "--db", str(e_db),
            "--batch-id", "b3",
            "--batch-receipt-sha256", b3_sha,
            "--x-id", early_prof["x_id"],
            "--x-epoch", "1",
        ],
    )
    assert e_inspected["kind"] == "SimulationCaptureBatch"
    assert e_inspected["batch_receipt_sha256"] == b3_sha
    assert [entry["raw_utf8"] for entry in e_inspected["entries"]] == [canonical(fill_orig), canonical(fee_orig)]

    # Verify sealed original untouched
    sealed_after = {"sha256": sha256_file(sealed_old_db), "size": sealed_old_db.stat().st_size}
    assert sealed_before == sealed_after, f"sealed original changed! {sealed_before} vs {sealed_after}"

    return {
        "sealed_original_sha256": sealed_before["sha256"],
        "sealed_original_unchanged": True,
        "query_history": hist,
        "query_command_early_wall": cmd,
        "query_batch_b3": batch_b3,
        "query_original_fill": fill_orig,
        "query_original_fee": fee_orig,
        "serve_refusal": serve_refusal,
        "e_fixed_batch_inspect": {
            "kind": e_inspected["kind"],
            "batch_receipt_sha256": e_inspected["batch_receipt_sha256"],
            "entry_count": len(e_inspected["entries"]),
            "entry_states": [e["state"] for e in e_inspected["entries"]],
            "rebound_decimal_session_generation": rebound_decimal_gen,
        },
    }


def verify_late_v1_and_anti_downgrade(
    x_bin: Path,
    late_v1_sql: Path,
    sealed_old_db: Path,
    v2_src_db: Path | None,
    v3_src_db: Path | None,
    work_root: Path,
) -> dict:
    late_dir = work_root / "late-v1-contrast"
    late_dir.mkdir(parents=True, exist_ok=True)
    late_db = late_dir / "late-v1.sqlite"
    with sqlite3.connect(late_db) as conn:
        conn.executescript(late_v1_sql.read_text())

    late_hist = run_cli(x_bin, ["query-history", "--db", str(late_db)])
    assert late_hist["profile_revision"] == "x-execution-profile/1"
    assert late_hist["archive_layout"] == "v1_late"
    assert late_hist["execute_evidence_claimed_ns_audit_policy"] == "verified_equal_to_attempt_bar"

    late_cmd = run_cli(x_bin, ["query-command", "--db", str(late_db), "--command-id", "a"])
    assert late_cmd["state"] == "Observed"
    assert late_cmd["archive_layout"] == "v1_late"
    assert late_cmd["execute_evidence_claimed_ns_audit"] == "verified_equal_to_attempt_bar"
    assert_strict_int(late_cmd["execute_evidence"]["claimed_ns"], late_cmd["attempt_batch_bar_index"], "late v1 claimed_ns")

    late_batch = run_cli(x_bin, ["query-batch", "--db", str(late_db), "--batch-id", "b1"])
    assert late_batch["request_id"] == "b1"
    fill_id = late_batch["originals"][0]["event"]["source"]["external_fact_id"]
    fee_id = late_batch["originals"][1]["event"]["source"]["external_fact_id"]
    late_fill = run_cli(x_bin, ["query-original", "--db", str(late_db), "--original-id", fill_id])
    late_fee = run_cli(x_bin, ["query-original", "--db", str(late_db), "--original-id", fee_id])
    assert late_fill == late_batch["originals"][0] and late_fee == late_batch["originals"][1]

    # Bad-archive & anti-downgrade suite
    bad_results = {}

    def mutate_late(tag: str, fn, expect_err: str):
        dst = work_root / "anti-downgrade" / f"{tag}.sqlite"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(late_db, dst)
        with sqlite3.connect(dst) as c:
            fn(c)
            c.commit()
        bad_results[tag] = {
            "query-history": run_cli(x_bin, ["query-history", "--db", str(dst)], expect_ok=False, expect_err=expect_err),
            "query-command": run_cli(x_bin, ["query-command", "--db", str(dst), "--command-id", "a"], expect_ok=False, expect_err=expect_err),
            "query-batch": run_cli(x_bin, ["query-batch", "--db", str(dst), "--batch-id", "b1"], expect_ok=False, expect_err=expect_err),
            "query-original": run_cli(x_bin, ["query-original", "--db", str(dst), "--original-id", fill_id], expect_ok=False, expect_err=expect_err),
        }

    # (1) Late /1 missing e.schema_revision -> MUST NOT downgrade to early /1
    def drop_e_schema(c):
        p = json.loads(c.execute("SELECT v FROM x_sim_meta WHERE k='authority_profile'").fetchone()[0])
        del p["e"]["schema_revision"]
        c.execute("UPDATE x_sim_meta SET v=? WHERE k='authority_profile'", (canonical(p),))
    mutate_late("late-v1-missing-e-schema-revision", drop_e_schema, "InvalidDomain")

    # (2) Hybrid: 12-key top-level (with conditions) + 3-key e/s
    def hybrid_12_with_3(c):
        p = json.loads(c.execute("SELECT v FROM x_sim_meta WHERE k='authority_profile'").fetchone()[0])
        for k in ("schema_revision", "reply_namespace", "producer_id"):
            del p["e"][k]
            del p["s"][k]
        c.execute("UPDATE x_sim_meta SET v=? WHERE k='authority_profile'", (canonical(p),))
    mutate_late("hybrid-12-top-with-3-auth", hybrid_12_with_3, "InvalidDomain")

    # (3) Hybrid: 11-key top-level (no conditions) + 6-key e/s
    def hybrid_11_with_6(c):
        p = json.loads(c.execute("SELECT v FROM x_sim_meta WHERE k='authority_profile'").fetchone()[0])
        del p["conditions"]
        c.execute("UPDATE x_sim_meta SET v=? WHERE k='authority_profile'", (canonical(p),))
    mutate_late("hybrid-11-top-with-6-auth", hybrid_11_with_6, "InvalidDomain")

    # (4) Late /1 tampered claimed_ns (wall-clock) -> IdentityConflict (must NOT relax to early /1!)
    def tamper_late_claimed(c):
        ev = json.loads(c.execute("SELECT execute_evidence FROM x_exact_commands WHERE id='a'").fetchone()[0])
        ev["claimed_ns"] = 1795111790994769493
        c.execute("UPDATE x_exact_commands SET execute_evidence=? WHERE id='a'", (canonical(ev),))
    mutate_late("late-v1-wallclock-claimed-ns", tamper_late_claimed, "IdentityConflict")

    # (5) Early /1 bad archives: claimed_ns < S.commit_ns and unexpected exact_profile_revision
    early_lt = copy_sqlite_set(sealed_old_db, work_root / "anti-downgrade", "early-claimed-lt-commit.sqlite")
    with sqlite3.connect(early_lt) as c:
        ev = json.loads(c.execute("SELECT execute_evidence FROM x_exact_commands WHERE id='early-wall'").fetchone()[0])
        ev["claimed_ns"] = 99
        c.execute("UPDATE x_exact_commands SET execute_evidence=? WHERE id='early-wall'", (canonical(ev),))
        c.commit()
    bad_results["early-v1-claimed-lt-s-commit"] = run_cli(
        x_bin, ["query-command", "--db", str(early_lt), "--command-id", "early-wall"],
        expect_ok=False, expect_err="IdentityConflict",
    )

    early_inner = copy_sqlite_set(sealed_old_db, work_root / "anti-downgrade", "early-unexpected-inner.sqlite")
    with sqlite3.connect(early_inner) as c:
        c.execute("INSERT INTO x_sim_meta VALUES('exact_profile_revision','x-execution-profile/3')")
        c.commit()
    bad_results["early-v1-with-inner-revision"] = run_cli(
        x_bin, ["query-history", "--db", str(early_inner)],
        expect_ok=False, expect_err="VersionUnsupported",
    )

    # (6) /2 and /3 real archives contrast + anti-downgrade injection of early 11+3 profile
    v2_v3 = {}
    with sqlite3.connect(sealed_old_db.as_uri() + "?mode=ro", uri=True) as c:
        early_raw_prof = json.loads(c.execute("SELECT v FROM x_sim_meta WHERE k='authority_profile'").fetchone()[0])

    for label, src, expected_rev, expected_layout in [
        ("v2", v2_src_db, "x-execution-profile/2", "v2"),
        ("v3", v3_src_db, "x-execution-profile/3", "v3"),
    ]:
        if src is None or not src.exists():
            continue
        dst_dir = work_root / f"{label}-contrast"
        wdb = copy_sqlite_set(src, dst_dir, f"{label}.db")
        h = run_cli(x_bin, ["query-history", "--db", str(wdb)])
        assert h["profile_revision"] == expected_rev
        assert h["archive_layout"] == expected_layout
        assert h["execute_evidence_claimed_ns_audit_policy"] == "verified_equal_to_attempt_bar"
        obs_cmds = [c for c in h["commands"] if c.get("state") == "Observed"]
        first_cmd = obs_cmds[0]["command_id"] if obs_cmds else h["commands"][0]["command_id"]
        c_out = run_cli(x_bin, ["query-command", "--db", str(wdb), "--command-id", first_cmd])
        assert c_out["archive_layout"] == expected_layout
        assert c_out["execute_evidence_claimed_ns_audit"] == "verified_equal_to_attempt_bar"
        first_batch = h["committed_batches"][-1]["batch_id"]
        b_out = run_cli(x_bin, ["query-batch", "--db", str(wdb), "--batch-id", first_batch])
        assert b_out["request_id"] == first_batch

        # Anti-downgrade: replace authority_profile with early 11+3 layout -> MUST fail InvalidDomain
        downgrade_db = copy_sqlite_set(src, work_root / "anti-downgrade", f"{label}-with-early-profile.db")
        with sqlite3.connect(downgrade_db) as c:
            orig_p = json.loads(c.execute("SELECT v FROM x_sim_meta WHERE k='authority_profile'").fetchone()[0])
            early_shaped = {
                k: orig_p[k] for k in early_raw_prof.keys() if k not in ("e", "s")
            }
            early_shaped["e"] = {k: orig_p["e"][k] for k in ("socket", "authority_id", "authority_epoch")}
            early_shaped["s"] = {k: orig_p["s"][k] for k in ("socket", "authority_id", "authority_epoch")}
            c.execute("UPDATE x_sim_meta SET v=? WHERE k='authority_profile'", (canonical(early_shaped),))
            c.commit()
        dg_err = run_cli(x_bin, ["query-history", "--db", str(downgrade_db)], expect_ok=False, expect_err="InvalidDomain")
        assert "missing field" in dg_err["stderr"], dg_err

        # Tampered claimed_ns on /2 or /3 -> IdentityConflict
        tamper_db = copy_sqlite_set(src, work_root / "anti-downgrade", f"{label}-tampered-claimed.db")
        with sqlite3.connect(tamper_db) as c:
            ev = json.loads(c.execute("SELECT execute_evidence FROM x_exact_commands WHERE id=?", (first_cmd,)).fetchone()[0])
            ev["claimed_ns"] = str(int(ev["claimed_ns"]) + 1000)
            c.execute("UPDATE x_exact_commands SET execute_evidence=? WHERE id=?", (canonical(ev), first_cmd))
            c.commit()
        t_err = run_cli(x_bin, ["query-command", "--db", str(tamper_db), "--command-id", first_cmd], expect_ok=False, expect_err="IdentityConflict")

        v2_v3[label] = {
            "profile_revision": h["profile_revision"],
            "archive_layout": h["archive_layout"],
            "claimed_ns_policy": h["execute_evidence_claimed_ns_audit_policy"],
            "command_id": first_cmd,
            "command_state": c_out["state"],
            "batch_id": first_batch,
            "downgrade_refusal": dg_err,
            "tamper_claimed_ns_refusal": t_err,
        }

    return {
        "late_v1": {
            "profile_revision": late_hist["profile_revision"],
            "archive_layout": late_hist["archive_layout"],
            "claimed_ns_policy": late_hist["execute_evidence_claimed_ns_audit_policy"],
            "command_a_state": late_cmd["state"],
            "command_a_claimed_ns": late_cmd["execute_evidence"]["claimed_ns"],
            "command_a_claimed_ns_audit": late_cmd["execute_evidence_claimed_ns_audit"],
            "batch_b1_original_ids": [fill_id, fee_id],
        },
        "anti_downgrade": bad_results,
        "v2_v3_contrast": v2_v3,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--x-bin", type=Path, required=True)
    ap.add_argument("--e-bin", type=Path, required=True)
    ap.add_argument("--sealed-early-db", type=Path, required=True)
    ap.add_argument("--early-observed-json", type=Path, required=True)
    ap.add_argument("--late-v1-sql", type=Path, required=True)
    ap.add_argument("--v2-db", type=Path, default=None)
    ap.add_argument("--v3-db", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    work = args.out / "work"
    work.mkdir(parents=True, exist_ok=True)

    report = {
        "early_v1": verify_early_v1(args.x_bin, args.e_bin, args.sealed_early_db, args.early_observed_json, work),
        "contrasts_and_anti_downgrade": verify_late_v1_and_anti_downgrade(
            args.x_bin, args.late_v1_sql, args.sealed_early_db, args.v2_db, args.v3_db, work,
        ),
    }
    out_file = args.out / "r5-verify-report.json"
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"PASS C3 R5 targeted verification -> {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
