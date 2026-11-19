#!/usr/bin/env python3
"""#1407 C3 R3：两臂 TestOnly FIN/5 正式 E 二进制对比 + 真实 /2 三态只读 CLI + 首次拒绝不 checkpoint 活 WAL 证据。"""
import argparse
import copy
import errno
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from history_fixture_model import model

SRC = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC / "s_session"))
sys.path.insert(0, str(SRC / "s_session/tests"))
from s_socket_client import canonical, decode_frame, digest


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same(left, right) -> bool:
    return canonical(left) == canonical(right)


def business_dump(db: Path):
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as c:
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

        def cell(x):
            return {"blob": x.hex()} if isinstance(x, bytes) else x

        return {
            n: sorted(
                ([cell(v) for v in r] for r in c.execute('SELECT * FROM "' + n.replace('"', '""') + '"')),
                key=canonical,
            )
            for n in names
        }


def wait_ready(proc, address: str, label: str, stderr_path: Path):
    limit = time.monotonic() + 15
    while time.monotonic() < limit:
        assert proc.poll() is None, (label, proc.returncode, stderr_path.read_text())
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(1)
            try:
                s.connect(address)
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.02)
                continue
            try:
                s.shutdown(socket.SHUT_WR)
            except OSError as exc:
                if exc.errno != errno.ENOTCONN:
                    raise
            raw = s.makefile("rb").readline()
            if raw:
                assert decode_frame(raw).get("ok") is False, (label, raw)
                return raw
    raise TimeoutError((label, address))


def send_frame(address: str, raw: bytes) -> bytes:
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(15)
        s.connect(address)
        s.sendall(raw)
        s.shutdown(socket.SHUT_WR)
        reply = s.makefile("rb").readline(1048577)
    assert reply, (address, "empty reply")
    return reply


def prepare_testonly_v5_session(run: Path, fixture: Path, *, authorize_x: bool):
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
    src_x = None
    for entry in manifest["authorized_sources"]:
        if entry["producer_id"] == "X":
            src_x = {k: entry[k] for k in source_fields}
            break
    if src_x is None:
        src_x = dict(
            source_namespace=src_business["source_namespace"],
            source_epoch=src_business["source_epoch"],
            producer_id="X",
            producer_epoch="1",
        )
    if authorize_x:
        if not any(a["producer_id"] == "X" for a in manifest["authorized_sources"]):
            manifest["authorized_sources"].append(dict(**src_x, operations=["QueryReleasedExact"]))
    else:
        manifest["authorized_sources"] = [
            a for a in manifest["authorized_sources"] if a["producer_id"] != "X"
        ]

    # Ensure TestOnly clock plan has entries for CloseApplicants-beta too
    msgs = manifest["clock"]["plan"]["messages"]
    if "CloseApplicants-beta" not in msgs:
        msgs["CloseApplicants-beta"] = dict(received_ns="200", first_known_ns="201", commit_ns="202")

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
        src_x=src_x,
        opener=opener,
        binding=binding,
    )


def init_and_spawn_eb(sess, bins: Path, epoch: str, tag: str):
    run = sess["run"]
    mp = sess["manifest_path"]
    if not Path(sess["nodes"]["E"]["db"]).exists():
        subprocess.run(
            [str(bins / "e_economic_session"), "init", "--manifest", str(mp), "--db", sess["nodes"]["E"]["db"]],
            check=True,
            capture_output=True,
            text=True,
        )
        for c in ("alpha", "beta"):
            subprocess.run(
                [
                    str(bins / "b_chong_session"),
                    "init",
                    "--manifest",
                    str(mp),
                    "--db",
                    sess["nodes"]["B:" + c]["db"],
                    "--chong",
                    c,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
    procs = []
    targets = [
        ("E", [str(bins / "e_economic_session"), "serve", "--manifest", str(mp), "--db", sess["nodes"]["E"]["db"], "--epoch", epoch]),
    ]
    for c in ("alpha", "beta"):
        targets.append(
            (
                "B:" + c,
                [
                    str(bins / "b_chong_session"),
                    "serve",
                    "--manifest",
                    str(mp),
                    "--db",
                    sess["nodes"]["B:" + c]["db"],
                    "--chong",
                    c,
                    "--epoch",
                    epoch,
                    "--e-epoch",
                    epoch,
                ],
            )
        )
    for name, cmd in targets:
        sock = Path(sess["nodes"][name]["socket"])
        if sock.exists():
            sock.unlink()
        errp = run / f"{tag}-{name.replace(':', '-')}.stderr"
        f = errp.open("wb")
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=f)
        wait_ready(p, str(sock), f"{tag}:{name}", errp)
        procs.append((p, f))
    return procs


def stop_procs(procs):
    for p, f in procs:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        f.close()


def make_ewire(sess, prefix: str, *, src=None):
    run = sess["run"]
    source = src if src is not None else sess["src_business"]

    def ewire(node: str, message_id: str, payload: dict, expected_kind: str, *, save_as: str | None = None):
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
        raw_req = canonical(req) + b"\n"
        raw_rep = send_frame(sess["nodes"][node]["socket"], raw_req)
        if save_as:
            (run / f"{prefix}-{save_as}.request.wire").write_bytes(raw_req)
            (run / f"{prefix}-{save_as}.reply.wire").write_bytes(raw_rep)
        rep = decode_frame(raw_rep)
        assert rep["payload"]["kind"] == expected_kind, (node, message_id, rep)
        return rep["payload"]

    return ewire


def drive_to_committed(sess, ewire):
    for a, raw in sess["opener"].items():
        capture = ewire(
            "E",
            f"capture-{a}",
            dict(
                op="CaptureExternal",
                raw_utf8=raw,
                json_pointer="/events/0",
                token=f"token-{a}",
                source_event_time=None,
            ),
            "Recorded",
        )
        ewire(
            f"B:{a}",
            f"apply-{a}",
            dict(
                op="ApplyAllocation",
                fact_key=capture["fact_key"],
                allocation_id=f"allocation-{a}",
                expected_fact_hash=capture["fact_hash"],
            ),
            "Applied",
        )
        ewire(f"B:{a}", f"bind-{a}", sess["binding"][a], "VoiceBound")

    rid = sess["data"]["baseline"]["responsibility_id"]
    ewire(
        "E",
        f"ImportResponsibility-{rid}",
        dict(op="ImportResponsibility", responsibility_id=rid, writer_epoch="1"),
        "ResponsibilityImportedReceipt",
    )
    for a, q in sess["plans"].items():
        ewire(
            f"B:{a}",
            f"PrepareDecision-{a}",
            dict(op="PrepareDecision", decision_id=a, plan_hash=digest(q), writer_epoch="1"),
            "PreparedReceipt",
        )
    slot = sess["data"]["slots"][0]
    reserve = ewire(
        "E",
        "Reserve-slot",
        dict(
            op="Reserve",
            slot_id=slot["slot_id"],
            request_set_hash=digest(slot["applicants"]),
            writer_epoch="1",
        ),
        "ReserveReceipt",
    )
    grants = {g["decision_id"]: g["grant_id"] for g in reserve["record"]["grants"]}
    for a, q in sess["plans"].items():
        ewire(
            f"B:{a}",
            f"CommitDecision-{a}",
            dict(
                op="CommitDecision",
                decision_id=a,
                plan_hash=digest(q),
                grant_id=grants[a],
                writer_epoch="1",
            ),
            "LocalCommitReceipt",
        )
    return grants


def build_release_payload(sess, grants):
    q = sess["plans"]["alpha"]
    x = q["exact"]
    freeze = sess["freeze"]
    change = dict(
        kind="submit",
        order=dict(
            command_id=x["command_id"],
            family_id=x["logical_order_family"],
            chong_id=x["chong_id"],
            revision=x["revision"],
            side=x["side"],
            quantity=q["quantity"],
            kind=dict(kind="limit", price=q["limit_price"]),
            eligibility_ref=x["eligibility_ref"],
            projection_manifest=x["projection_manifest"],
        ),
    )
    cert = dict(
        rd11_policy=freeze["rd11_policy"],
        responsibility_refs=[grants["alpha"]],
        structure_dependencies=[q["s_ref"]["object_id"] + "@" + q["s_ref"]["object_hash"]],
        market_dependencies=freeze["market_dependencies"],
        rule_revision=freeze["rule_revision"],
        conditions=freeze["conditions"],
    )
    return dict(
        op="ReleaseExact",
        decision_id="alpha",
        command_id=x["command_id"],
        x_id="X",
        x_epoch="1",
        plan_hash=digest(change),
        certificate=cert,
        writer_epoch="1",
    )


def run_cli(cmd, *, expect_ok: bool = True):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if expect_ok:
        assert res.returncode == 0, (cmd, res.returncode, res.stdout, res.stderr)
        return json.loads(res.stdout), res
    else:
        assert res.returncode != 0, (cmd, "expected failure", res.stdout, res.stderr)
        return None, res


def make_cold_wal_copy(src_db: Path, dst_dir: Path, name: str, sql_mutation: str):
    """Create a cold uncheckpointed WAL pair (<name>.db + <name>.db-wal, NO -shm, NO .writer.lock)."""
    work = dst_dir / f"_build_{name}"
    work.mkdir(mode=0o700, parents=True)
    tmp_db = work / f"{name}.db"
    shutil.copyfile(src_db, tmp_db)

    # Open two connections in WAL mode with autocheckpoint disabled so commit stays in -wal
    c_writer = sqlite3.connect(str(tmp_db), isolation_level=None)
    c_writer.execute("PRAGMA journal_mode=WAL;")
    c_writer.execute("PRAGMA wal_autocheckpoint=0;")
    c_reader = sqlite3.connect(str(tmp_db), isolation_level=None)
    c_reader.execute("BEGIN;")
    c_reader.execute("SELECT COUNT(*) FROM x_meta;").fetchone()
    c_writer.execute("BEGIN IMMEDIATE;")
    c_writer.execute(sql_mutation)
    c_writer.execute("COMMIT;")

    tmp_wal = Path(str(tmp_db) + "-wal")
    assert tmp_wal.exists() and tmp_wal.stat().st_size > 0, "expected uncheckpointed -wal"

    target_dir = dst_dir / name
    target_dir.mkdir(mode=0o700, parents=True)
    cold_db = target_dir / f"{name}.db"
    cold_wal = target_dir / f"{name}.db-wal"
    shutil.copyfile(tmp_db, cold_db)
    shutil.copyfile(tmp_wal, cold_wal)

    c_reader.close()
    c_writer.close()
    shutil.rmtree(work)
    assert cold_db.exists() and cold_wal.exists() and cold_wal.stat().st_size > 0
    assert not Path(str(cold_db) + "-shm").exists()
    assert not Path(str(cold_db) + ".writer.lock").exists()
    return target_dir, cold_db, cold_wal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True, help="C1 TestOnly FIN/5 fixture dir")
    parser.add_argument("--r2-dir", type=Path, required=True, help="R2 upgrade_pairing archive dir")
    parser.add_argument("--bin", type=Path, required=True, help="Candidate debug/release bin dir")
    parser.add_argument("--out", type=Path, required=True, help="Output evidence dir")
    args = parser.parse_args()
    fixture, r2_dir, cbin, out = (p.resolve() for p in (args.fixture, args.r2_dir, args.bin, args.out))
    out.mkdir(mode=0o700, parents=True)
    report = {}

    # ══════════════════════════════════════════════════════════════════════════
    # Suite 1: Two-arm TestOnly FIN/5 formal E binary contrast (B1)
    # ══════════════════════════════════════════════════════════════════════════
    arm_a = prepare_testonly_v5_session(out / "suite1_arm_a_b9d898_x_authorized", fixture, authorize_x=True)
    procs_a = init_and_spawn_eb(arm_a, cbin, "1", "arm-a")
    try:
        ewire_a = make_ewire(arm_a, "arm-a")
        drive_to_committed(arm_a, ewire_a)
        dump_a_before = business_dump(Path(arm_a["nodes"]["E"]["db"]))
        md_a = dict(
            op="MakeDispatchable",
            decision_id="alpha",
            plan_hash=digest(arm_a["plans"]["alpha"]),
            writer_epoch="1",
        )
        refused_a = ewire_a("E", "MakeDispatchable-alpha", md_a, "Error", save_as="MakeDispatchable-refused")
        assert refused_a["error"].startswith("VersionUnsupported："), refused_a
        dump_a_after_refusal = business_dump(Path(arm_a["nodes"]["E"]["db"]))
        assert same(dump_a_before, dump_a_after_refusal), "Arm A refused MakeDispatchable must leave E DB unchanged"

        q_a = ewire_a(
            "E",
            "QueryCommand-alpha",
            dict(op="QueryCommand", command_id="cmd-alpha", cut=None, as_known_ns=None),
            "EconomicCommand",
            save_as="QueryCommand-after-refusal",
        )
        assert q_a["state"] == "NoRecord", q_a

        beta_plan = arm_a["plans"]["beta"]
        closed_a = ewire_a(
            "E",
            "CloseApplicants-beta",
            dict(
                op="CloseApplicants",
                slot_id=beta_plan["slot_id"],
                writer_epoch="1",
                closed=[
                    dict(
                        owner=beta_plan["owner"],
                        applicant_epoch=beta_plan["applicant_epoch"],
                        applicant_generation=beta_plan["applicant_generation"],
                    )
                ],
                reason="r3-verify-fin5-other-writes-intact",
            ),
            "ApplicantsClosedReceipt",
            save_as="CloseApplicants-beta",
        )
        assert closed_a["record"]["state"] == "ApplicantsClosed", closed_a
    finally:
        stop_procs(procs_a)

    arm_b = prepare_testonly_v5_session(out / "suite1_arm_b_isolated_c1", fixture, authorize_x=False)
    procs_b = init_and_spawn_eb(arm_b, cbin, "1", "arm-b")
    try:
        ewire_b = make_ewire(arm_b, "arm-b")
        grants_b = drive_to_committed(arm_b, ewire_b)
        md_b = dict(
            op="MakeDispatchable",
            decision_id="alpha",
            plan_hash=digest(arm_b["plans"]["alpha"]),
            writer_epoch="1",
        )
        disp_b = ewire_b("E", "MakeDispatchable-alpha", md_b, "DispatchableReceipt", save_as="MakeDispatchable-alpha")
        assert disp_b["record"]["state"] == "Dispatchable"
        rel_b_payload = build_release_payload(arm_b, grants_b)
        rel_b = ewire_b("E", "ReleaseExact-alpha", rel_b_payload, "ReleasedExactReceipt", save_as="ReleaseExact-alpha")
        assert rel_b["record"]["state"] == "ReleasedExact"
        cmd_v5 = rel_b["record"]["command"]
        assert "model_ref" not in cmd_v5

        # Prove Arm B CANNOT hand a redeemable authorization to real historical X:
        # 1) Direct QueryReleasedExact frame from producer_id="X" on Arm B's formal E socket is REJECTED (来源未获准)!
        ewire_b_as_x = make_ewire(arm_b, "arm-b-as-x", src=arm_b["src_x"])
        x_auth_req = dict(
            op="QueryReleasedExact",
            command_id=cmd_v5["command_id"],
            command_hash=digest(cmd_v5),
            command=cmd_v5,
            session_id=arm_b["sid"],
            session_generation=arm_b["gen"],
            authority_id="E",
            authority_epoch="1",
            release_receipt_id=None,
        )
        x_rejected = ewire_b_as_x("E", "X-QueryReleasedExact-alpha", x_auth_req, "Error", save_as="QueryReleasedExact-rejected")
        assert "来源未获准" in x_rejected["error"], x_rejected

        # 2) Live candidate /3 X also rejects raw Arm B /5 command (missing field `model_ref`)
        cred_b = arm_b["run"] / "cred.txt"
        cred_b.write_text("sentinel-r3\n")
        x_model = {**model(), "symbol": "alpha"}
        xp_v3 = dict(
            profile_revision="x-execution-profile/3",
            mode="simulation",
            endpoint=None,
            tb09_fingerprint=None,
            credential_scope=dict(env="NC_X_VENUE_CREDENTIAL_SENTINEL", file=str(cred_b)),
            history_simulation=dict(
                model=x_model,
                session_id=arm_b["sid"],
                session_generation=arm_b["gen"],
                x_id="X",
                source_namespace=arm_b["src_x"]["source_namespace"],
                source_epoch=arm_b["src_x"]["source_epoch"],
                socket=str(arm_b["run"] / "x-v3.sock"),
                e=dict(
                    socket=arm_b["nodes"]["E"]["socket"],
                    authority_id="E",
                    authority_epoch="1",
                    schema_revision="economic-session/1",
                    reply_namespace="economic-session/replies",
                    producer_id=f"E:{arm_b['sid']}",
                ),
                s=dict(
                    socket=str(arm_b["run"] / "s.sock"),
                    authority_id="S",
                    authority_epoch="1",
                    schema_revision="s-authority-fixture/1",
                    reply_namespace="s-authority-fixture/replies",
                    producer_id="S:fixture",
                ),
                conditions=arm_b["freeze"]["conditions"],
                timeout_ms=5000,
                max_frame_bytes=1048576,
            ),
        )
        xp_v3_path = arm_b["run"] / "x-profile-v3.json"
        xp_v3_path.write_bytes(canonical(xp_v3))
        x_db_b = arm_b["run"] / "x-v3.db"
        x_err_b = arm_b["run"] / "x-v3.stderr"
        xf = x_err_b.open("wb")
        xp_proc = subprocess.Popen(
            [str(cbin / "x_execution_session"), "serve", "--db", str(x_db_b), "--profile", str(xp_v3_path), "--writer-epoch", "1"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=xf,
        )
        try:
            wait_ready(xp_proc, str(arm_b["run"] / "x-v3.sock"), "arm-b-x-v3", x_err_b)
            raw_x_req = canonical(dict(protocol="x-exact-simulation/1", op="AcceptExact", payload=cmd_v5)) + b"\n"
            raw_x_rep = send_frame(str(arm_b["run"] / "x-v3.sock"), raw_x_req)
            (arm_b["run"] / "arm-b-x-v3-accept-v5.request.wire").write_bytes(raw_x_req)
            (arm_b["run"] / "arm-b-x-v3-accept-v5.reply.wire").write_bytes(raw_x_rep)
            x_v3_rep = decode_frame(raw_x_rep)
            assert x_v3_rep["kind"] == "Error" and "model_ref" in x_v3_rep["error"], x_v3_rep
        finally:
            stop_procs([(xp_proc, xf)])
    finally:
        stop_procs(procs_b)

    report["suite1_two_arm_testonly_fin5"] = dict(
        arm_a_b9d898_x_authorized=dict(
            clock_kind="TestOnly",
            has_history_simulation_source=False,
            x_authorized_for_query_released_exact=True,
            new_make_dispatchable_error=refused_a["error"],
            e_db_unchanged_after_refusal=True,
            command_state_after_refusal=q_a["state"],
            close_applicants_beta_succeeded=True,
        ),
        arm_b_isolated_c1=dict(
            clock_kind="TestOnly",
            has_history_simulation_source=False,
            x_authorized_for_query_released_exact=False,
            make_dispatchable_state=disp_b["record"]["state"],
            release_exact_state=rel_b["record"]["state"],
            x_query_released_exact_over_e_socket_error=x_rejected["error"],
            v3_x_accept_error=x_v3_rep["error"],
        ),
    )

    # ══════════════════════════════════════════════════════════════════════════
    # Suite 2: Real R2 /2 three-state DBs via audited x_execution_session CLI (B2)
    # ══════════════════════════════════════════════════════════════════════════
    s2 = out / "suite2_real_v2_readonly_cli"
    s2.mkdir(mode=0o700, parents=True)

    # 2A: Accepted (state_b_released_and_inflight/x-v2-inflight.db)
    src_acc = r2_dir / "state_b_released_and_inflight"
    db_acc = s2 / "x-v2-inflight.db"
    shutil.copyfile(src_acc / "x-v2-inflight.db", db_acc)
    sha_acc_before = file_digest(db_acc)
    parent_acc_wire = decode_frame((src_acc / "parent-v2-accept.reply.wire").read_bytes())

    hist_acc, _ = run_cli([str(cbin / "x_execution_session"), "query-history", "--db", str(db_acc)])
    cmd_acc, _ = run_cli([str(cbin / "x_execution_session"), "query-command", "--db", str(db_acc), "--command-id", "cmd-alpha"])
    meta_acc, _ = run_cli([str(cbin / "x_execution_session"), "query", "--db", str(db_acc)])
    (s2 / "accepted-query-history.json").write_bytes(canonical(hist_acc))
    (s2 / "accepted-query-command.json").write_bytes(canonical(cmd_acc))
    assert file_digest(db_acc) == sha_acc_before
    assert hist_acc["profile_revision"] == "x-execution-profile/2"
    assert hist_acc["last_bar_index"] == 1
    assert cmd_acc["state"] == "Accepted"
    assert same(cmd_acc["x_accept"], parent_acc_wire["x_accept"])
    assert same(cmd_acc["causal_refs"], parent_acc_wire["causal_refs"])
    assert cmd_acc["pending_batch_id"] is None
    assert meta_acc["profile_revision"] == "x-execution-profile/2"

    # 2B: ExecutionRequested + pending b2 (state_c_terminal_v2_batch/x-v2-execution-requested.db)
    src_c = r2_dir / "state_c_terminal_v2_batch"
    db_req = s2 / "x-v2-execution-requested.db"
    shutil.copyfile(src_c / "x-v2-execution-requested.db", db_req)
    sha_req_before = file_digest(db_req)
    parent_req_wire = decode_frame((src_c / "parent-v2-query-execution-requested.reply.wire").read_bytes())

    hist_req, _ = run_cli([str(cbin / "x_execution_session"), "query-history", "--db", str(db_req)])
    cmd_req, _ = run_cli([str(cbin / "x_execution_session"), "query-command", "--db", str(db_req), "--command-id", "cmd-alpha"])
    _, batch_b2_pending = run_cli(
        [str(cbin / "x_execution_session"), "query-batch", "--db", str(db_req), "--batch-id", "b2"],
        expect_ok=False,
    )
    (s2 / "execution-requested-query-history.json").write_bytes(canonical(hist_req))
    (s2 / "execution-requested-query-command.json").write_bytes(canonical(cmd_req))
    (s2 / "execution-requested-query-batch-b2.stderr").write_text(batch_b2_pending.stderr)
    assert file_digest(db_req) == sha_req_before
    assert cmd_req["state"] == "ExecutionRequested"
    assert cmd_req["pending_batch_id"] == "b2"
    assert cmd_req["pending_epoch"] == "1"
    assert cmd_req["attempt_batch_id"] == "b2"
    assert same(cmd_req["x_accept"], parent_req_wire["x_accept"])
    assert same(cmd_req["causal_refs"], parent_req_wire["causal_refs"])
    assert "MissingDependency" in batch_b2_pending.stderr, batch_b2_pending.stderr

    # 2C: Terminal Observed + committed b3 (fill + fee originals) (state_c_terminal_v2_batch/x-v2-terminal.db)
    db_term = s2 / "x-v2-terminal.db"
    shutil.copyfile(src_c / "x-v2-terminal.db", db_term)
    sha_term_before = file_digest(db_term)
    parent_obs_wire = decode_frame((src_c / "parent-v2-query-observed.reply.wire").read_bytes())
    parent_b3_wire = decode_frame((src_c / "parent-v2-query-b3.reply.wire").read_bytes())

    hist_term, _ = run_cli([str(cbin / "x_execution_session"), "query-history", "--db", str(db_term)])
    cmd_term, _ = run_cli([str(cbin / "x_execution_session"), "query-command", "--db", str(db_term), "--command-id", "cmd-alpha"])
    batch_b3, _ = run_cli([str(cbin / "x_execution_session"), "query-batch", "--db", str(db_term), "--batch-id", "b3"])
    (s2 / "terminal-query-history.json").write_bytes(canonical(hist_term))
    (s2 / "terminal-query-command.json").write_bytes(canonical(cmd_term))
    (s2 / "terminal-query-batch-b3.json").write_bytes(canonical(batch_b3))
    assert cmd_term["state"] == "Observed"
    assert cmd_term["last_committed_batch_id"] == "b3"
    assert cmd_term["last_bar_index"] == 3
    assert same(cmd_term["x_accept"], parent_obs_wire["x_accept"])
    assert same(cmd_term["causal_refs"], parent_obs_wire["causal_refs"])
    # Exact byte-identical SimulationBatch (including fill + fee originals + state_content_hash)
    assert same(batch_b3, parent_b3_wire), ("batch b3 differs from parent wire!", batch_b3, parent_b3_wire)
    event_kinds = [o["event"]["kind"] for o in batch_b3["originals"]]
    assert event_kinds == ["fill", "fee"], event_kinds
    orig_ids = [o["event"]["source"]["external_fact_id"] for o in batch_b3["originals"]]
    assert orig_ids == hist_term["originals"], (orig_ids, hist_term["originals"])
    queried_originals = {}
    for oid in orig_ids:
        orig_doc, _ = run_cli([str(cbin / "x_execution_session"), "query-original", "--db", str(db_term), "--original-id", oid])
        queried_originals[oid] = orig_doc
        safe = oid.replace(":", "_")
        (s2 / f"terminal-query-original-{safe}.json").write_bytes(canonical(orig_doc))
    for expected_orig in batch_b3["originals"]:
        oid = expected_orig["event"]["source"]["external_fact_id"]
        assert same(queried_originals[oid], expected_orig), (oid, "original mismatch")
    assert file_digest(db_term) == sha_term_before

    report["suite2_real_v2_readonly_cli"] = dict(
        accepted=dict(
            db_sha256_unchanged=True,
            profile_revision=hist_acc["profile_revision"],
            command_state=cmd_acc["state"],
            x_accept_matches_parent_wire=True,
            causal_refs_matches_parent_wire=True,
        ),
        execution_requested=dict(
            db_sha256_unchanged=True,
            command_state=cmd_req["state"],
            pending_batch_id=cmd_req["pending_batch_id"],
            pending_epoch=cmd_req["pending_epoch"],
            query_pending_batch_b2_refused_error=batch_b2_pending.stderr.strip(),
        ),
        terminal_observed_b3=dict(
            db_sha256_unchanged=True,
            command_state=cmd_term["state"],
            last_committed_batch_id=cmd_term["last_committed_batch_id"],
            last_bar_index=cmd_term["last_bar_index"],
            batch_b3_canonical_matches_parent_wire=True,
            original_event_kinds=event_kinds,
            original_ids=orig_ids,
            originals_byte_identical=True,
        ),
    )

    # ══════════════════════════════════════════════════════════════════════════
    # Suite 3: Cold uncheckpointed WAL first-open refusal & live-WAL visibility (B3)
    # ══════════════════════════════════════════════════════════════════════════
    s3 = out / "suite3_cold_wal_first_open"
    s3.mkdir(mode=0o700, parents=True)

    # 3A & 3B: Valid cold uncheckpointed WAL copy of real x-v2-execution-requested.db (baseline BEFORE first open!)
    cold_dir, cold_db, cold_wal = make_cold_wal_copy(
        src_c / "x-v2-execution-requested.db",
        s3,
        "cold_v2_exec_req",
        "PRAGMA user_version = 7;",
    )
    baseline = dict(
        db_size=cold_db.stat().st_size,
        db_sha256=file_digest(cold_db),
        wal_size=cold_wal.stat().st_size,
        wal_sha256=file_digest(cold_wal),
        files_before=sorted(p.name for p in cold_dir.iterdir()),
    )

    # Copy rewritten /3 profile from R2 archive
    xp_v3_refuse = s3 / "x-profile-v3.json"
    shutil.copyfile(src_c / "x-profile-v3.json", xp_v3_refuse)

    # VERY FIRST OPEN by candidate x_execution_session serve -> MUST refuse VersionUnsupported with ZERO checkpoint!
    first_refuse = subprocess.run(
        [str(cbin / "x_execution_session"), "serve", "--db", str(cold_db), "--profile", str(xp_v3_refuse), "--writer-epoch", "2"],
        capture_output=True,
        text=True,
    )
    (s3 / "first-serve-refuse.stderr").write_text(first_refuse.stderr)
    assert first_refuse.returncode != 0 and "VersionUnsupported" in first_refuse.stderr, first_refuse.stderr
    after_first_serve = dict(
        db_size=cold_db.stat().st_size,
        db_sha256=file_digest(cold_db),
        wal_exists=cold_wal.exists(),
        wal_size=cold_wal.stat().st_size if cold_wal.exists() else 0,
        wal_sha256=file_digest(cold_wal) if cold_wal.exists() else None,
        writer_lock_exists=Path(str(cold_db) + ".writer.lock").exists(),
        files_after_first_serve=sorted(p.name for p in cold_dir.iterdir()),
    )
    assert after_first_serve["db_sha256"] == baseline["db_sha256"], "main .db modified on first refused open!"
    assert after_first_serve["wal_exists"] and after_first_serve["wal_sha256"] == baseline["wal_sha256"], "-wal modified/checkpointed!"
    assert not after_first_serve["writer_lock_exists"], ".writer.lock must not be created on refused open!"

    # Read-only CLI on the SAME cold uncheckpointed WAL DB:
    # - `query-command` succeeds and returns ExecutionRequested + pending b2
    # - `.db` and `-wal` SHA-256 STILL 100% unchanged, zero writer.lock!
    live_cmd, _ = run_cli([str(cbin / "x_execution_session"), "query-command", "--db", str(cold_db), "--command-id", "cmd-alpha"])
    assert live_cmd["state"] == "ExecutionRequested" and live_cmd["pending_batch_id"] == "b2"
    after_readonly_cli = dict(
        db_sha256=file_digest(cold_db),
        wal_sha256=file_digest(cold_wal),
        writer_lock_exists=Path(str(cold_db) + ".writer.lock").exists(),
        files_after_cli=sorted(p.name for p in cold_dir.iterdir()),
    )
    assert after_readonly_cli["db_sha256"] == baseline["db_sha256"]
    assert after_readonly_cli["wal_sha256"] == baseline["wal_sha256"]
    assert not after_readonly_cli["writer_lock_exists"]

    # 3C: Live-WAL visibility probe (proving SQLITE_OPEN_READ_ONLY reads live -wal, NOT immutable=1!):
    # Mutate writer_epoch to '7' ONLY inside uncheckpointed -wal (main .db still has '1'):
    # - `query` sees writer_epoch == "7" (immutable=1 would return stale "1")
    # - `query-command` catches PendingBatch mismatch against live -wal writer_epoch=7
    # - AND neither `.db` nor `-wal` bytes are modified!
    vis_dir, vis_db, vis_wal = make_cold_wal_copy(
        src_c / "x-v2-execution-requested.db",
        s3,
        "live_wal_visibility_probe",
        "UPDATE x_meta SET value = '7' WHERE key = 'writer_epoch';",
    )
    vis_db_sha_before = file_digest(vis_db)
    vis_wal_sha_before = file_digest(vis_wal)
    vis_meta, _ = run_cli([str(cbin / "x_execution_session"), "query", "--db", str(vis_db)])
    assert vis_meta["writer_epoch"] == "7", ("expected live WAL writer_epoch='7', not stale main DB '1'!", vis_meta)
    _, vis_audit_res = run_cli(
        [str(cbin / "x_execution_session"), "query-command", "--db", str(vis_db), "--command-id", "cmd-alpha"],
        expect_ok=False,
    )
    (s3 / "live-wal-visibility-audit.stderr").write_text(vis_audit_res.stderr)
    assert "PendingBatch" in vis_audit_res.stderr, vis_audit_res.stderr
    assert file_digest(vis_db) == vis_db_sha_before
    assert file_digest(vis_wal) == vis_wal_sha_before

    report["suite3_cold_wal_first_open"] = dict(
        baseline=baseline,
        first_serve_refuse_stderr=first_refuse.stderr.strip(),
        after_first_serve=after_first_serve,
        live_wal_command_state_seen=live_cmd["state"],
        live_wal_pending_batch_seen=live_cmd["pending_batch_id"],
        after_readonly_cli=after_readonly_cli,
        live_wal_visibility_probe=dict(
            writer_epoch_seen_from_live_wal=vis_meta["writer_epoch"],
            audit_caught_live_wal_pending_epoch_mismatch=True,
            audit_stderr=vis_audit_res.stderr.strip(),
            db_and_wal_sha256_unchanged=True,
        ),
    )

    (out / "summary.json").write_bytes(canonical(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
