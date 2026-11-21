#!/usr/bin/env python3
"""#1407 C3 R4 增量验证：
1. B1：冻结 X/1、仅授 X/2 QueryReleasedExact（+拆项 X/1 ReadView）的离线放行与真实 X/1、X/2 对拍；
   以及同项 (X, producer_epoch="1", QueryReleasedExact) 但 source_epoch="99" 的拒绝反例。
2. B2：由真实 R2 /2 库派生的 MayHaveCalled 工作副本（非真实崩溃）中，
   claimed_ns="2" 合法对照通过 vs claimed_ns="999" 篡改反例被 IdentityConflict 拒绝；
   并核对真实 /2 终态批 b3 实际读口字段（originals 与 query-history.committed_batches[*].batch_receipt_sha256）。
3. B3：按修订后的单一封存取证规程，对未 checkpoint 的 b2 活 WAL 副本（主库仅 Accepted，
   WAL 含 ExecutionRequested + pending b2）完整实走：封存原件不打开 → 恢复至独立可写取证目录 →
   CLI 查到仅在 WAL 的状态 → 验证封存原件字节与目录清单零改动。
"""
import argparse
import copy
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from c3_r3_decisive_verify import (
    build_release_payload,
    business_dump,
    drive_to_committed,
    file_digest,
    init_and_spawn_eb,
    make_ewire,
    run_cli,
    same,
    send_frame,
    stop_procs,
    wait_ready,
)
from history_fixture_model import model

SRC = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC / "s_session"))
sys.path.insert(0, str(SRC / "s_session/tests"))
from s_socket_client import canonical, decode_frame, digest


def prepare_v5_session_custom(run: Path, fixture: Path, extra_x_sources):
    run.mkdir(mode=0o700, parents=True)

    def write(name: str, obj) -> Path:
        p = run / name
        p.write_bytes(canonical(obj))
        return p

    def load(p: Path):
        return decode_frame(p.read_bytes())

    def copied(name: str) -> Path:
        p = run / name
        shutil.copyfile(fixture / name, p)
        return p

    manifest = load(fixture / "manifest.json")
    assert manifest["finance"]["schema_revision"] == "tb03b-finance/5"
    assert manifest["clock"]["kind"] == "TestOnly", manifest["clock"]
    assert "history_simulation_source" not in manifest
    sid, gen = manifest["session_id"], manifest["session_generation"]
    source_fields = ("source_namespace", "source_epoch", "producer_id", "producer_epoch")
    src_business = {k: manifest["authorized_sources"][0][k] for k in source_fields}

    # Replace X entries with exact test entries
    manifest["authorized_sources"] = [
        a for a in manifest["authorized_sources"] if a["producer_id"] != "X"
    ] + list(extra_x_sources)

    opener, binding = {}, {}
    for authority in manifest["voice_binding"]["authorities"]:
        a = authority["authority_id"]
        bundle = load(fixture / f"{a}-authority.json")
        verification = load(fixture / f"{a}-unit-review.json")
        for artifact in bundle["artifacts"]:
            p = copied(Path(artifact["path"]).name)
            artifact["path"] = str(p)
            if artifact["name"] == "opening_raw":
                opener[a] = p.read_text()
        bundle_path = write(f"{a}-authority.json", bundle)
        bh = file_digest(bundle_path)
        verification.update(bundle_sha256=bh, artifacts=bundle["artifacts"])
        review_path = write(f"{a}-unit-review.json", verification)
        authority.update(
            bundle_path=str(bundle_path),
            bundle_sha256=bh,
            verification_path=str(review_path),
            verification_sha256=file_digest(review_path),
        )
        ref = bundle["bindings"][0]
        origin = ref["opening_source"]
        binding[a] = dict(
            op="BindVoice",
            binding_id=f"voice-{a}",
            evidence_id=a,
            carrier_ref=ref["carrier_ref"],
            gamma_ref=ref["gamma_ref"],
            parent_voice_id=None,
            sigma="Long",
            n="0",
            opening_basis={
                k if k != "fact_hash" else "expected_fact_hash": origin[k]
                for k in ("fact_key", "fact_hash", "allocation_id")
            },
        )

    data_path = copied("input.json")
    data = load(data_path)
    assert data["schema_revision"] == "tb03b-finance/5"
    basis = copied("s-unit-basis-stub.json")
    stub = run / "s-unit-stub.sh"
    stub.write_text(f"#!/bin/sh\nexec /bin/cat '{basis}'\n")
    stub.chmod(0o700)
    manifest["finance"]["input_path"] = str(data_path)
    manifest["finance"]["structure"].update(
        binary=str(stub),
        binary_sha256=file_digest(stub),
        db=str(run / "s-unit.db"),
    )
    nodes = {"E": manifest["e"], **{f"B:{c['chong_id']}": c for c in manifest["chongs"]}}
    for domain, node in nodes.items():
        short = "e" if domain == "E" else node["chong_id"]
        node.update(db=str(run / f"{short}.db"), socket=str(run / f"{short}.sock"))
    mp = write("manifest.json", manifest)
    plans = {p["decision_id"]: p for p in data["plans"]}
    return dict(
        run=run,
        manifest_path=mp,
        manifest=manifest,
        data=data,
        plans=plans,
        freeze=data["exact_release"],
        nodes=nodes,
        sid=sid,
        gen=gen,
        src_business=src_business,
        opener=opener,
        binding=binding,
    )


def send_e_raw(sess, message_id: str, payload: dict, source: dict):
    req = dict(
        schema_revision="economic-session/1",
        session_id=sess["sid"],
        session_generation=sess["gen"],
        message_id=message_id,
        payload=payload,
        payload_hash=digest(payload),
        causal_refs=[],
        **source,
    )
    raw_rep = send_frame(sess["nodes"]["E"]["socket"], canonical(req) + b"\n")
    return decode_frame(raw_rep)["payload"]


def make_uncheckpointed_b2_wal_pair(
    base_accepted_db: Path,
    exec_req_db: Path,
    dest_dir: Path,
):
    """Build a genuine uncheckpointed WAL pair where:
    - main .db alone has cmd-alpha=Accepted (no pending_batch), and
    - live -wal contains the committed SQLite transition to ExecutionRequested + pending_batch=b2.
    """
    dest_dir.mkdir(mode=0o700, parents=True)
    db = dest_dir / "x-v2-pending-b2.db"
    shutil.copyfile(base_accepted_db, db)

    with closing(sqlite3.connect(exec_req_db.as_uri() + "?mode=ro", uri=True)) as src:
        pending_batch = src.execute("SELECT v FROM x_sim_meta WHERE k='pending_batch'").fetchone()[0]
        pending_epoch = src.execute("SELECT v FROM x_sim_meta WHERE k='pending_epoch'").fetchone()[0]
        attempt_batch = src.execute("SELECT attempt_batch FROM x_exact_commands WHERE id='cmd-alpha'").fetchone()[0]
        state_val = src.execute("SELECT state FROM x_exact_commands WHERE id='cmd-alpha'").fetchone()[0]
    assert state_val == "ExecutionRequested", state_val

    # Open db in WAL mode, disable autocheckpoint, hold a reader connection so close() cannot auto-checkpoint!
    conn_w = sqlite3.connect(str(db), isolation_level=None)
    conn_w.execute("PRAGMA journal_mode=WAL;")
    conn_w.execute("PRAGMA wal_autocheckpoint=0;")
    conn_w.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    # Pin a read snapshot BEFORE the transition to ExecutionRequested
    conn_r = sqlite3.connect(str(db), isolation_level=None)
    conn_r.execute("BEGIN DEFERRED;")
    pre_state = conn_r.execute("SELECT state FROM x_exact_commands WHERE id='cmd-alpha'").fetchone()[0]
    assert pre_state == "Accepted", pre_state

    # Apply the ExecutionRequested + pending_batch b2 transition into WAL only
    conn_w.execute("BEGIN IMMEDIATE;")
    conn_w.execute("INSERT OR REPLACE INTO x_sim_meta(k,v) VALUES('pending_batch', ?)", (pending_batch,))
    conn_w.execute("INSERT OR REPLACE INTO x_sim_meta(k,v) VALUES('pending_epoch', ?)", (pending_epoch,))
    conn_w.execute(
        "UPDATE x_exact_commands SET state='ExecutionRequested', attempt_batch=? WHERE id='cmd-alpha'",
        (attempt_batch,),
    )
    conn_w.execute("COMMIT;")

    wal = Path(str(db) + "-wal")
    assert wal.exists() and wal.stat().st_size > 0, "expected non-empty live -wal"

    # Snapshot a consistent pair while reader holds snapshot (zero checkpoint occurred on main db!)
    snap_dir = dest_dir / "sealed_source"
    snap_dir.mkdir(mode=0o700)
    sealed_db = snap_dir / "x-v2-pending-b2.db"
    sealed_wal = snap_dir / "x-v2-pending-b2.db-wal"
    shutil.copyfile(db, sealed_db)
    shutil.copyfile(wal, sealed_wal)

    conn_w.close()
    conn_r.execute("ROLLBACK;")
    conn_r.close()

    # Verify main-only (isolated copy without -wal) really only has Accepted (proving pending b2 lives ONLY in -wal!)
    check_dir = dest_dir / "main_only_check"
    check_dir.mkdir(mode=0o700)
    main_only = check_dir / "main-only.db"
    shutil.copyfile(sealed_db, main_only)
    with closing(sqlite3.connect(str(main_only))) as mc:
        main_state = mc.execute("SELECT state FROM x_exact_commands WHERE id='cmd-alpha'").fetchone()[0]
        main_pending = mc.execute("SELECT v FROM x_sim_meta WHERE k='pending_batch'").fetchone()
    assert main_state == "Accepted" and main_pending is None, (main_state, main_pending)
    shutil.rmtree(check_dir)

    return snap_dir, sealed_db, sealed_wal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", required=True, help="C1 /5 TestOnly fixture dir")
    ap.add_argument("--candidate-bin", required=True, help="R4 candidate debug bin dir")
    ap.add_argument("--r2-v2-dir", required=True, help="R2 upgrade_pairing dir containing real /2 DBs")
    ap.add_argument("--out", required=True, help="Output dir for R4 raw evidence")
    args = ap.parse_args()

    fixture = Path(args.fixture).resolve()
    cbin = Path(args.candidate_bin).resolve()
    r2_dir = Path(args.r2_v2_dir).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    report = {}

    # =========================================================================
    # Suite R4-1: B1 wrong-epoch / split-entry offline signing + X/1 & X/2 pair-off
    #             AND non-1 source_epoch="99" counterexample rejection
    # =========================================================================
    s1 = out / "suite1_b1_epoch_gate"
    s1.mkdir(mode=0o700, parents=True)

    # 1A: Frozen x_target=X/1, authorized_sources has:
    #   - X/1 with ReadView ONLY (split entry)
    #   - X/2 with QueryReleasedExact AND source_epoch="1" (wrong writer epoch)
    arm_1a = prepare_v5_session_custom(
        s1 / "arm_1a_wrong_epoch_and_split",
        fixture,
        extra_x_sources=[
            dict(source_namespace="x-sim", source_epoch="epoch1", producer_id="X", producer_epoch="1", operations=["ReadView"]),
            dict(source_namespace="x-sim", source_epoch="1", producer_id="X", producer_epoch="2", operations=["QueryReleasedExact"]),
        ],
    )
    procs_1a = init_and_spawn_eb(arm_1a, cbin, "1", "arm-1a")
    try:
        ewire_1a = make_ewire(arm_1a, "arm-1a")
        grants_1a = drive_to_committed(arm_1a, ewire_1a)

        md_1a = ewire_1a(
            "E",
            "MakeDispatchable-alpha",
            dict(op="MakeDispatchable", decision_id="alpha", plan_hash=digest(arm_1a["plans"]["alpha"]), writer_epoch="1"),
            "DispatchableReceipt",
            save_as="MakeDispatchable-alpha",
        )
        rel_1a = ewire_1a(
            "E",
            "ReleaseExact-alpha",
            build_release_payload(arm_1a, grants_1a),
            "ReleasedExactReceipt",
            save_as="ReleaseExact-alpha",
        )
        (s1 / "arm1a-md.json").write_bytes(canonical(md_1a))
        (s1 / "arm1a-rel.json").write_bytes(canonical(rel_1a))

        cmd_v5 = rel_1a["record"]["command"]
        assert cmd_v5["x_id"] == "X" and cmd_v5["x_epoch"] == "1"
        assert "model_ref" not in cmd_v5
        q_payload = dict(
            op="QueryReleasedExact",
            protocol="x-exact-authority/1",
            session_id=arm_1a["sid"],
            session_generation=arm_1a["gen"],
            authority_id="E",
            authority_epoch="1",
            command_id=cmd_v5["command_id"],
            command_hash=digest(cmd_v5),
            command=cmd_v5,
            release_receipt_id=None,
        )
        # Real X/1 cannot query E (Config::authorized rejects)
        x1_src = dict(source_namespace="x-sim", source_epoch="epoch1", producer_id="X", producer_epoch="1")
        x1_q = send_e_raw(arm_1a, "x1-query", q_payload, x1_src)
        (s1 / "arm1a-x1-query.json").write_bytes(canonical(x1_q))
        assert x1_q["kind"] == "Error" and "来源未获准" in x1_q["error"], x1_q

        # X/2 CAN query E because X/2 was authorized, so prove formal X running at writer_epoch=2 STILL cannot accept X/1 command!
        x2_src = dict(source_namespace="x-sim", source_epoch="1", producer_id="X", producer_epoch="2")
        x2_q = send_e_raw(arm_1a, "x2-query", q_payload, x2_src)
        (s1 / "arm1a-x2-query.json").write_bytes(canonical(x2_q))
        assert x2_q["state"] == "ReleasedExact", x2_q

        # Launch candidate /3 x_execution_session at writer_epoch=2 (matching X/2) and submit raw /5 cmd + forged model_ref cmd
        x2_run = s1 / "x2_runtime"
        x2_run.mkdir(mode=0o700)
        sim_model = {**model(), "symbol": "alpha"}
        cred_x2 = x2_run / "cred"
        cred_x2.write_text("unused\n")
        x2_profile = dict(
            profile_revision="x-execution-profile/3",
            mode="simulation",
            endpoint=None,
            tb09_fingerprint=None,
            credential_scope=dict(env="NC_X_VENUE_CREDENTIAL", file=str(cred_x2)),
            history_simulation=dict(
                model=sim_model,
                session_id=arm_1a["sid"],
                session_generation=arm_1a["gen"],
                x_id="X",
                source_namespace="x-sim",
                source_epoch="1",
                socket=str(x2_run / "x2.sock"),
                e=dict(
                    socket=arm_1a["nodes"]["E"]["socket"],
                    authority_id="E",
                    authority_epoch="1",
                    schema_revision="economic-session/1",
                    reply_namespace="economic-session/replies",
                    producer_id=f"E:{arm_1a['sid']}",
                ),
                s=dict(
                    socket=str(x2_run / "s.sock"),
                    authority_id="S",
                    authority_epoch="1",
                    schema_revision="s-authority-fixture/1",
                    reply_namespace="s-authority-fixture/replies",
                    producer_id="S:fixture",
                ),
                conditions=arm_1a["freeze"]["conditions"],
                timeout_ms=5000,
                max_frame_bytes=1048576,
            ),
        )
        x2_profile_path = x2_run / "x2-profile.json"
        x2_profile_path.write_bytes(canonical(x2_profile))
        x2_db = x2_run / "x2.db"
        x2_err = x2_run / "x2.stderr"
        x2_stderr = x2_err.open("wb")
        x2_proc = subprocess.Popen(
            [str(cbin / "x_execution_session"), "serve", "--db", str(x2_db), "--profile", str(x2_profile_path), "--writer-epoch", "2"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=x2_stderr,
        )
        try:
            wait_ready(x2_proc, str(x2_run / "x2.sock"), "x2", x2_err)
            # Raw /5 command sent to /3 X/2 -> rejected (missing model_ref)
            raw_x2_reply = decode_frame(
                send_frame(str(x2_run / "x2.sock"), canonical(dict(protocol="x-exact-simulation/1", op="AcceptExact", payload=cmd_v5)) + b"\n")
            )
            # Even if model_ref is forged onto the X/1 command, writer_epoch=2 rejects x_epoch="1" with IdentityConflict!
            forged = copy.deepcopy(cmd_v5)
            forged["model_ref"] = dict(
                model_id=sim_model["model_id"],
                revision=sim_model["revision"],
                content_hash=digest(sim_model),
            )
            forged_x2_reply = decode_frame(
                send_frame(str(x2_run / "x2.sock"), canonical(dict(protocol="x-exact-simulation/1", op="AcceptExact", payload=forged)) + b"\n")
            )
            (s1 / "arm1a-x2-accept-raw.json").write_bytes(canonical(raw_x2_reply))
            (s1 / "arm1a-x2-accept-forged.json").write_bytes(canonical(forged_x2_reply))
            assert raw_x2_reply["kind"] == "Error" and "model_ref" in raw_x2_reply["error"], raw_x2_reply
            assert forged_x2_reply["kind"] == "Error" and "IdentityConflict" in forged_x2_reply["error"], forged_x2_reply
        finally:
            stop_procs([(x2_proc, x2_stderr)])
    finally:
        stop_procs(procs_1a)

    # 1B: Frozen x_target=X/1, same entry matches (producer_id="X", producer_epoch="1", QueryReleasedExact)
    #     with non-1 source_namespace="custom-sim-ns", source_epoch="99" -> MUST be rejected!
    arm_1b = prepare_v5_session_custom(
        s1 / "arm_1b_custom_source_epoch_99",
        fixture,
        extra_x_sources=[
            dict(source_namespace="custom-sim-ns", source_epoch="99", producer_id="X", producer_epoch="1", operations=["QueryReleasedExact"]),
        ],
    )
    procs_1b = init_and_spawn_eb(arm_1b, cbin, "1", "arm-1b")
    try:
        ewire_1b = make_ewire(arm_1b, "arm-1b")
        drive_to_committed(arm_1b, ewire_1b)
        e_before_1b = business_dump(Path(arm_1b["nodes"]["E"]["db"]))
        md_1b = ewire_1b(
            "E",
            "MakeDispatchable-alpha",
            dict(op="MakeDispatchable", decision_id="alpha", plan_hash=digest(arm_1b["plans"]["alpha"]), writer_epoch="1"),
            "Error",
            save_as="MakeDispatchable-refused",
        )
        (s1 / "arm1b-md-refused.json").write_bytes(canonical(md_1b))
        assert md_1b["kind"] == "Error" and md_1b["error"].startswith("VersionUnsupported："), md_1b
        assert same(business_dump(Path(arm_1b["nodes"]["E"]["db"])), e_before_1b), "arm 1b mutated E DB on refusal"
    finally:
        stop_procs(procs_1b)

    report["suite1_b1_epoch_gate"] = dict(
        arm_1a_wrong_epoch_and_split=dict(
            offline_make_dispatchable=md_1a["kind"],
            offline_release_exact=rel_1a["kind"],
            real_x1_query_error=x1_q["error"],
            x2_query_state=x2_q["state"],
            x2_accept_raw_v5_error=raw_x2_reply["error"],
            x2_accept_forged_x1_epoch_error=forged_x2_reply["error"],
        ),
        arm_1b_custom_source_epoch_99=dict(
            make_dispatchable_error=md_1b["error"],
            e_db_unchanged=True,
        ),
    )

    # =========================================================================
    # Suite R4-2: B2 Derived /2 MayHaveCalled working copies (control=2 vs tampered=999)
    #             + real /2 terminal b3 actual CLI field inventory
    # =========================================================================
    s2 = out / "suite2_b2_claimed_ns_and_cli_fields"
    s2.mkdir(mode=0o700, parents=True)

    src_req = r2_dir / "state_c_terminal_v2_batch" / "x-v2-execution-requested.db"
    src_term = r2_dir / "state_c_terminal_v2_batch" / "x-v2-terminal.db"
    assert src_req.exists() and src_term.exists()

    # Extract real /2 S execute_evidence from real x-v2-terminal.db (claimed_ns="2", S.commit_ns="2")
    with closing(sqlite3.connect(src_term.as_uri() + "?mode=ro", uri=True)) as tc:
        real_exec_ev_raw = tc.execute("SELECT execute_evidence FROM x_exact_commands WHERE id='cmd-alpha'").fetchone()[0]
    real_exec_ev = decode_frame(real_exec_ev_raw.encode())
    assert real_exec_ev["claimed_ns"] == "2", real_exec_ev

    # Build two explicitly-labeled DERIVED working copies (NOT real process crashes)
    ctrl_db = s2 / "derived-v2-mhc-control-claimed-2.db"
    tamp_db = s2 / "derived-v2-mhc-tampered-claimed-999.db"
    shutil.copyfile(src_req, ctrl_db)
    shutil.copyfile(src_req, tamp_db)

    with closing(sqlite3.connect(str(ctrl_db))) as cc:
        cc.execute(
            "UPDATE x_exact_commands SET state='MayHaveCalled', execute_evidence=? WHERE id='cmd-alpha'",
            (real_exec_ev_raw,),
        )
        cc.commit()

    tampered_ev = copy.deepcopy(real_exec_ev)
    tampered_ev["claimed_ns"] = "999"
    with closing(sqlite3.connect(str(tamp_db))) as tc2:
        tc2.execute(
            "UPDATE x_exact_commands SET state='MayHaveCalled', execute_evidence=? WHERE id='cmd-alpha'",
            (canonical(tampered_ev).decode(),),
        )
        tc2.commit()

    # Legitimate control (claimed_ns == "2" == b2.bar.index) -> PASSES
    ctrl_hist, _ = run_cli([str(cbin / "x_execution_session"), "query-history", "--db", str(ctrl_db)])
    ctrl_cmd, _ = run_cli([str(cbin / "x_execution_session"), "query-command", "--db", str(ctrl_db), "--command-id", "cmd-alpha"])
    (s2 / "derived-control-query-history.json").write_bytes(canonical(ctrl_hist))
    (s2 / "derived-control-query-command.json").write_bytes(canonical(ctrl_cmd))
    assert ctrl_cmd["state"] == "MayHaveCalled"
    assert ctrl_cmd["attempt_batch_id"] == "b2"
    assert ctrl_cmd["attempt_batch_bar_index"] == 2
    assert ctrl_cmd["execute_evidence"]["claimed_ns"] == "2"
    assert ctrl_cmd["execute_evidence_claimed_ns_audit"] == "verified_equal_to_attempt_bar"
    assert ctrl_hist["execute_evidence_claimed_ns_audit_policy"] == "verified_equal_to_attempt_bar"

    # Tampered counterexample (claimed_ns == "999" != b2.bar.index) -> REJECTED with IdentityConflict
    _, tamp_hist_res = run_cli([str(cbin / "x_execution_session"), "query-history", "--db", str(tamp_db)], expect_ok=False)
    _, tamp_cmd_res = run_cli(
        [str(cbin / "x_execution_session"), "query-command", "--db", str(tamp_db), "--command-id", "cmd-alpha"],
        expect_ok=False,
    )
    (s2 / "derived-tampered-999-query-history.stderr").write_text(tamp_hist_res.stderr)
    (s2 / "derived-tampered-999-query-command.stderr").write_text(tamp_cmd_res.stderr)
    assert "IdentityConflict" in tamp_hist_res.stderr and "999" in tamp_hist_res.stderr, tamp_hist_res.stderr
    assert "IdentityConflict" in tamp_cmd_res.stderr and "999" in tamp_cmd_res.stderr, tamp_cmd_res.stderr

    # Verify real /2 terminal DB actual CLI keys (query-batch vs query-history.committed_batches[*])
    term_copy = s2 / "real-v2-terminal-copy.db"
    shutil.copyfile(src_term, term_copy)
    term_hist, _ = run_cli([str(cbin / "x_execution_session"), "query-history", "--db", str(term_copy)])
    term_b3, _ = run_cli([str(cbin / "x_execution_session"), "query-batch", "--db", str(term_copy), "--batch-id", "b3"])
    (s2 / "real-v2-terminal-query-history.json").write_bytes(canonical(term_hist))
    (s2 / "real-v2-terminal-query-batch-b3.json").write_bytes(canonical(term_b3))
    b3_keys = sorted(term_b3.keys())
    assert "originals" in b3_keys
    for absent in ("orders", "fills", "fees", "scenario_busts", "batch_receipt_sha256"):
        assert absent not in term_b3, (absent, b3_keys)
    b3_summary = [b for b in term_hist["committed_batches"] if b["batch_id"] == "b3"][0]
    assert b3_summary["batch_receipt_sha256"] == digest(term_b3)

    report["suite2_b2_claimed_ns_and_cli_fields"] = dict(
        derived_v2_mhc_note="Derived working copies constructed from real R2 /2 DBs (NOT real process crashes)",
        control_claimed_2=dict(
            state=ctrl_cmd["state"],
            attempt_batch_id=ctrl_cmd["attempt_batch_id"],
            attempt_batch_bar_index=ctrl_cmd["attempt_batch_bar_index"],
            claimed_ns=ctrl_cmd["execute_evidence"]["claimed_ns"],
            claimed_ns_audit=ctrl_cmd["execute_evidence_claimed_ns_audit"],
        ),
        tampered_claimed_999=dict(
            query_history_stderr=tamp_hist_res.stderr.strip(),
            query_command_stderr=tamp_cmd_res.stderr.strip(),
        ),
        real_v2_b3_actual_keys=b3_keys,
        real_v2_b3_receipt_sha256_in_query_history=b3_summary["batch_receipt_sha256"],
    )

    # =========================================================================
    # Suite R4-3: B3 Single operational sealing runbook walkthrough on uncheckpointed b2 WAL copy
    # =========================================================================
    s3 = out / "suite3_b3_sealing_runbook"
    s3.mkdir(mode=0o700, parents=True)

    src_acc = r2_dir / "state_b_released_and_inflight" / "x-v2-inflight.db"
    assert src_acc.exists()

    # Step 1: Produce consistent cut with WAL-only ExecutionRequested + pending b2, seal RO (0555/0444)
    sealed_dir, sealed_db, sealed_wal = make_uncheckpointed_b2_wal_pair(src_acc, src_req, s3 / "prep")
    # Also retain original E liability evidence marker in sealed archive
    e_marker = sealed_dir / "original-e-liability-evidence.json"
    e_marker.write_bytes(canonical(dict(note="retained alongside sealed X .db + -wal")))
    sealed_before = dict(
        files=sorted(p.name for p in sealed_dir.iterdir()),
        db_size=sealed_db.stat().st_size,
        db_sha256=file_digest(sealed_db),
        wal_size=sealed_wal.stat().st_size,
        wal_sha256=file_digest(sealed_wal),
        e_marker_sha256=file_digest(e_marker),
    )
    # Lock down sealed archive read-only (0444 files, 0555 dir) and NEVER open sealed originals directly
    for f in (sealed_db, sealed_wal, e_marker):
        os.chmod(f, 0o444)
    os.chmod(sealed_dir, 0o555)

    try:
        # Step 2: Restore full copy (.db + -wal) to independent writable forensic directory
        forensic_dir = s3 / "forensic_writable_copy"
        forensic_dir.mkdir(mode=0o700)
        work_db = forensic_dir / sealed_db.name
        work_wal = forensic_dir / sealed_wal.name
        shutil.copyfile(sealed_db, work_db)
        shutil.copyfile(sealed_wal, work_wal)
        os.chmod(work_db, 0o644)
        os.chmod(work_wal, 0o644)

        # Step 3: Run x_execution_session query-* on the restored writable working copy
        f_hist, _ = run_cli([str(cbin / "x_execution_session"), "query-history", "--db", str(work_db)])
        f_cmd, _ = run_cli([str(cbin / "x_execution_session"), "query-command", "--db", str(work_db), "--command-id", "cmd-alpha"])
        _, f_b2_res = run_cli(
            [str(cbin / "x_execution_session"), "query-batch", "--db", str(work_db), "--batch-id", "b2"],
            expect_ok=False,
        )
        (s3 / "forensic-query-history.json").write_bytes(canonical(f_hist))
        (s3 / "forensic-query-command.json").write_bytes(canonical(f_cmd))
        (s3 / "forensic-query-batch-b2.stderr").write_text(f_b2_res.stderr)

        # Confirm WAL-only ExecutionRequested + pending b2 is read cleanly
        assert f_hist["pending_batch_id"] == "b2" and f_hist["pending_epoch"] == "1", f_hist
        assert f_hist["last_bar_index"] == 1, f_hist
        assert f_cmd["state"] == "ExecutionRequested", f_cmd
        assert f_cmd["attempt_batch_id"] == "b2" and f_cmd["attempt_batch_bar_index"] == 2, f_cmd
        assert f_cmd["pending_batch_id"] == "b2" and f_cmd["pending_epoch"] == "1", f_cmd
        assert "MissingDependency" in f_b2_res.stderr, f_b2_res.stderr

        # Step 4: Verify sealed source is 100% untouched (bytes, file list, no -shm, no lock)
        sealed_after = dict(
            files=sorted(p.name for p in sealed_dir.iterdir()),
            db_size=sealed_db.stat().st_size,
            db_sha256=file_digest(sealed_db),
            wal_size=sealed_wal.stat().st_size,
            wal_sha256=file_digest(sealed_wal),
            e_marker_sha256=file_digest(e_marker),
        )
        assert sealed_after == sealed_before, (sealed_before, sealed_after)

        report["suite3_b3_sealing_runbook"] = dict(
            main_db_only_state="Accepted (no pending_batch; verified before sealing)",
            sealed_before=sealed_before,
            sealed_after=sealed_after,
            sealed_unchanged=True,
            forensic_files_after_query=sorted(p.name for p in forensic_dir.iterdir()),
            forensic_wal_only_state_read=dict(
                command_state=f_cmd["state"],
                pending_batch_id=f_cmd["pending_batch_id"],
                pending_epoch=f_cmd["pending_epoch"],
                attempt_batch_id=f_cmd["attempt_batch_id"],
                attempt_batch_bar_index=f_cmd["attempt_batch_bar_index"],
                last_bar_index=f_hist["last_bar_index"],
                query_batch_b2_stderr=f_b2_res.stderr.strip(),
            ),
        )
    finally:
        # Restore permissions so out dir can be copied/tarred cleanly
        os.chmod(sealed_dir, 0o700)
        for f in (sealed_db, sealed_wal, e_marker):
            os.chmod(f, 0o600)

    (out / "summary.json").write_bytes(canonical(report))
    print(canonical(report).decode())


if __name__ == "__main__":
    main()
