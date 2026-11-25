#!/usr/bin/env python3
"""#1407 C3 R2：用真实父头 #2081（/2 + FIN/5）历史与候选正式入口逐态验证升级配对、独立 E 守门与归档只读。"""
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
import threading
import time
from contextlib import closing
from pathlib import Path

from history_fixture_model import model

SRC = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC / "s_session"))
sys.path.insert(0, str(SRC / "s_session/tests"))
from s_socket_client import canonical, decode_frame, digest, reply_envelope, validate_reply


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


def prepare_v5_session(run: Path, fixture: Path, *, with_history_source: Path | None = None, x_model_hash: str | None = None):
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
    sid, gen = manifest["session_id"], manifest["session_generation"]
    source_fields = ("source_namespace", "source_epoch", "producer_id", "producer_epoch")
    src_business = {k: manifest["authorized_sources"][0][k] for k in source_fields}
    src_x = {k: manifest["authorized_sources"][1][k] for k in source_fields}
    messages = {m: "1" for m in manifest["clock"]["plan"]["messages"]}
    messages["ReleaseExact-alpha"] = "2"
    messages["ReleaseExact-alpha-replay"] = "2"
    messages["CloseApplicants-beta"] = "2"
    manifest["clock"] = dict(kind="logical-bar/1", bars=dict(init="0", messages=messages, recover=["2", "3", "4"]))

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
    if with_history_source is not None:
        assert x_model_hash is not None
        if "CaptureExternal" not in manifest["authorized_sources"][1]["operations"]:
            manifest["authorized_sources"][1]["operations"].append("CaptureExternal")
        manifest["history_simulation_source"] = dict(
            source_namespace=src_x["source_namespace"],
            source_epoch=src_x["source_epoch"],
            producer_id=src_x["producer_id"],
            producer_epoch=src_x["producer_epoch"],
            x_db=str(with_history_source),
            model_content_hash=x_model_hash,
        )
    manifest_path = write("manifest.json", manifest)
    return dict(
        run=run,
        manifest=manifest,
        manifest_path=manifest_path,
        data=data,
        plans={q["decision_id"]: q for q in data["plans"]},
        freeze=data["exact_release"],
        nodes=nodes,
        sid=sid,
        gen=gen,
        src_business=src_business,
        src_x=src_x,
        opener=opener,
        binding=binding,
    )


def init_and_spawn_eb(sess, bins: Path, epoch: str, tag: str, *, need_b: bool = True):
    run = sess["run"]
    mp = sess["manifest_path"]
    if not Path(sess["nodes"]["E"]["db"]).exists():
        subprocess.run(
            [str(bins / "e_economic_session"), "init", "--manifest", str(mp), "--db", sess["nodes"]["E"]["db"]],
            check=True,
        )
    elif epoch != "1":
        subprocess.run(
            [str(bins / "e_economic_session"), "recover", "--manifest", str(mp), "--db", sess["nodes"]["E"]["db"]],
            check=True,
        )
    procs = []
    logs = []
    if need_b:
        for c in ("alpha", "beta"):
            db = sess["nodes"]["B:" + c]["db"]
            if not Path(db).exists():
                subprocess.run(
                    [str(bins / "b_chong_session"), "init", "--manifest", str(mp), "--db", db, "--chong", c],
                    check=True,
                )
    targets = [("E", [str(bins / "e_economic_session"), "serve", "--manifest", str(mp), "--db", sess["nodes"]["E"]["db"], "--epoch", epoch])]
    if need_b:
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
        logs.append(errp)
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


def make_ewire(sess, epoch: str, prefix: str):
    run = sess["run"]

    def ewire(node: str, message_id: str, payload: dict, expected_kind: str, *, save_as: str | None = None):
        req = dict(
            schema_revision="economic-session/1",
            session_id=sess["sid"],
            session_generation=sess["gen"],
            message_id=message_id,
            payload=payload,
            payload_hash=digest(payload),
            causal_refs=[],
            **sess["src_business"],
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


def run_up_to_dispatchable(sess, parent_bins: Path):
    procs = init_and_spawn_eb(sess, parent_bins, "1", "parent-eb")
    try:
        ewire = make_ewire(sess, "1", "parent")
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
        md_payload = dict(
            op="MakeDispatchable",
            decision_id="alpha",
            plan_hash=digest(sess["plans"]["alpha"]),
            writer_epoch="1",
        )
        md = ewire("E", "MakeDispatchable-alpha", md_payload, "DispatchableReceipt", save_as="MakeDispatchable-alpha")
        return dict(grants=grants, md_payload=md_payload, md_receipt=md)
    finally:
        stop_procs(procs)


def build_release_payload(sess, grants, epoch: str):
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
        writer_epoch=epoch,
    )


def build_x_profile(run: Path, sess, x_rev: str, x_model: dict, sock_name: str, cred_file: Path):
    cred_file.write_text("sentinel-r2\n")
    return dict(
        profile_revision=x_rev,
        mode="simulation",
        endpoint=None,
        tb09_fingerprint=None,
        credential_scope=dict(env="NC_X_VENUE_CREDENTIAL_SENTINEL", file=str(cred_file)),
        history_simulation=dict(
            model=x_model,
            session_id=sess["sid"],
            session_generation=sess["gen"],
            x_id="X",
            source_namespace=sess["src_x"]["source_namespace"],
            source_epoch=sess["src_x"]["source_epoch"],
            socket=str(run / sock_name),
            e=dict(
                socket=sess["nodes"]["E"]["socket"],
                authority_id="E",
                authority_epoch="1",
                schema_revision="economic-session/1",
                reply_namespace="economic-session/replies",
                producer_id=f"E:{sess['sid']}",
            ),
            s=dict(
                socket=str(run / "s.sock"),
                authority_id="S",
                authority_epoch="1",
                schema_revision="s-authority-fixture/1",
                reply_namespace="s-authority-fixture/replies",
                producer_id="S:fixture",
            ),
            conditions=sess["freeze"]["conditions"],
            timeout_ms=5000,
            max_frame_bytes=1048576,
        ),
    )


def x_call(sock_path: Path, op: str, payload, save_prefix: Path | None = None):
    raw_req = canonical(dict(protocol="x-exact-simulation/1", op=op, payload=payload)) + b"\n"
    raw_rep = send_frame(str(sock_path), raw_req)
    if save_prefix is not None:
        save_prefix.with_suffix(".request.wire").write_bytes(raw_req)
        save_prefix.with_suffix(".reply.wire").write_bytes(raw_rep)
    return decode_frame(raw_rep)


def retained_liability(ewire) -> int:
    view = ewire("E", "ReadView-check", dict(op="ReadView", cut=None, as_known_ns=None), "EconomicView")
    return sum(int(r["amount"]) for r in view["image"]["finance"]["responsibilities"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--parent-bin", type=Path, required=True)
    parser.add_argument("--candidate-bin", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    fixture, pbin, cbin, out = (p.resolve() for p in (args.fixture, args.parent_bin, args.candidate_bin, args.out))
    out.mkdir(mode=0o700, parents=True)

    x_model = {**model(), "symbol": "alpha"}
    x_model_hash = digest(x_model)
    report = {}

    # ── State A: Parent #2081 FIN/5 + logical-bar/1 stopped at Dispatchable (cut 5) ──
    sess_a = prepare_v5_session(out / "state_a_dispatchable", fixture)
    state_a = run_up_to_dispatchable(sess_a, pbin)
    e_db_a = Path(sess_a["nodes"]["E"]["db"])
    dump_a_before = business_dump(e_db_a)

    # Candidate standalone formal E (NO X online, NO B needed for Dispatchable replay / ReleaseExact refusal!)
    procs_a = init_and_spawn_eb(sess_a, cbin, "2", "cand-a", need_b=False)
    try:
        ewire = make_ewire(sess_a, "2", "cand-a")
        q_before = ewire(
            "E",
            "QueryCommand-alpha-before",
            dict(op="QueryCommand", command_id="cmd-alpha", cut=None, as_known_ns=None),
            "EconomicCommand",
            save_as="QueryCommand-before",
        )
        assert q_before["state"] == "Dispatchable"
        # Original-ID replay of committed MakeDispatchable returns byte-identical receipt FIRST
        replay_md = ewire("E", "MakeDispatchable-alpha", state_a["md_payload"], "DispatchableReceipt", save_as="MakeDispatchable-replay")
        assert same(replay_md, state_a["md_receipt"])
        # NEW ReleaseExact on Dispatchable FIN/5 logical-bar is REFUSED (VersionUnsupported), 0 new receipt!
        rel_payload_a = build_release_payload(sess_a, state_a["grants"], "2")
        refused_rel = ewire("E", "ReleaseExact-alpha", rel_payload_a, "Error", save_as="ReleaseExact-refused")
        assert refused_rel["error"].startswith("VersionUnsupported："), refused_rel
        # NEW MakeDispatchable on beta is REFUSED (VersionUnsupported) even with B offline!
        md_beta = dict(op="MakeDispatchable", decision_id="beta", plan_hash=digest(sess_a["plans"]["beta"]), writer_epoch="2")
        refused_md_beta = ewire("E", "MakeDispatchable-beta", md_beta, "Error", save_as="MakeDispatchable-beta-refused")
        assert refused_md_beta["error"].startswith("VersionUnsupported："), refused_md_beta
        q_after = ewire(
            "E",
            "QueryCommand-alpha-after",
            dict(op="QueryCommand", command_id="cmd-alpha", cut=None, as_known_ns=None),
            "EconomicCommand",
            save_as="QueryCommand-after",
        )
        assert q_after["state"] == "Dispatchable" and same(q_before, q_after)
        liab_a = retained_liability(ewire)
        assert liab_a == 90
    finally:
        stop_procs(procs_a)
    dump_a_after = business_dump(e_db_a)
    # Only epochs table added epoch=2 on restart; all business tables (commits/receipts/messages/book/facts/pending) unchanged!
    for table in ("commits", "receipts", "messages", "book", "facts", "pending", "applications", "unmatched"):
        assert same(dump_a_before[table], dump_a_after[table]), (table, "mutated in state_a")

    # Also verify non-delivery economic write (CloseApplicants) still succeeds on a FIN/5 logical-bar DB (NOT globally read-only!)
    sess_a_other = prepare_v5_session(out / "state_a_other_fin5_write", fixture)
    run_up_to_dispatchable(sess_a_other, pbin)
    procs_other = init_and_spawn_eb(sess_a_other, cbin, "2", "cand-other", need_b=False)
    try:
        ewire_o = make_ewire(sess_a_other, "2", "cand-other")
        beta_plan = sess_a_other["plans"]["beta"]
        closed = ewire_o(
            "E",
            "CloseApplicants-beta",
            dict(
                op="CloseApplicants",
                slot_id=beta_plan["slot_id"],
                writer_epoch="2",
                closed=[
                    dict(
                        owner=beta_plan["owner"],
                        applicant_epoch=beta_plan["applicant_epoch"],
                        applicant_generation=beta_plan["applicant_generation"],
                    )
                ],
                reason="r2-verify-fin5-not-readonly",
            ),
            "ApplicantsClosedReceipt",
            save_as="CloseApplicants-beta",
        )
        assert closed["record"]["state"] == "ApplicantsClosed"
    finally:
        stop_procs(procs_other)

    report["state_a_dispatchable"] = dict(
        command_state="Dispatchable",
        original_make_dispatchable_replayed=True,
        new_release_exact_error=refused_rel["error"],
        new_make_dispatchable_beta_error=refused_md_beta["error"],
        retained_liability=liab_a,
        business_tables_unchanged=True,
        other_fin5_economic_write_succeeded=True,
    )

    # ── State B: Parent #2081 FIN/5 ReleasedExact (cut 6) + Parent /2 X in-flight (Accepted, non-terminal) ──
    sess_b = prepare_v5_session(out / "state_b_released_and_inflight", fixture)
    state_b = run_up_to_dispatchable(sess_b, pbin)
    rel_payload_b1 = build_release_payload(sess_b, state_b["grants"], "1")
    procs_b_p = init_and_spawn_eb(sess_b, pbin, "2", "parent-b-rel", need_b=False)
    try:
        ewire_bp = make_ewire(sess_b, "2", "parent-b")
        rel_payload_b2 = dict(rel_payload_b1, writer_epoch="2")
        rel_b = ewire_bp("E", "ReleaseExact-alpha", rel_payload_b2, "ReleasedExactReceipt", save_as="ReleaseExact-alpha")
        assert rel_b["record"]["state"] == "ReleasedExact"
        exact_v5 = rel_b["record"]["command"]
        assert "model_ref" not in exact_v5

        # Start real parent #2081 /2 X and accept cmd-alpha at bar 2 (in-flight Accepted, NOT yet Observed!)
        xp_v2 = build_x_profile(sess_b["run"], sess_b, "x-execution-profile/2", x_model, "x-v2.sock", sess_b["run"] / "cred.txt")
        xp_v2["history_simulation"]["e"]["authority_epoch"] = "2"
        xp_v2_path = sess_b["run"] / "x-profile-v2.json"
        xp_v2_path.write_bytes(canonical(xp_v2))
        x_db_b = sess_b["run"] / "x-v2-inflight.db"
        x_err_b = sess_b["run"] / "parent-x-v2.stderr"
        xf = x_err_b.open("wb")
        xp_proc = subprocess.Popen(
            [str(pbin / "x_execution_session"), "serve", "--db", str(x_db_b), "--profile", str(xp_v2_path), "--writer-epoch", "1"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=xf,
        )
        try:
            wait_ready(xp_proc, str(sess_b["run"] / "x-v2.sock"), "parent-x-v2", x_err_b)
            for idx in (0, 1):
                b_res = x_call(
                    sess_b["run"] / "x-v2.sock",
                    "AdvanceBar",
                    dict(request_id=f"b{idx}", known_frontier_cut=f"f{idx}", bar=dict(index=idx, open=14, high=15, low=13, close=14), close_changes=[], capacity=dict(kind="none"), scenario_busts=[]),
                )
                assert b_res["kind"] == "SimulationBatch", b_res
            acc_v2 = x_call(sess_b["run"] / "x-v2.sock", "AcceptExact", exact_v5, sess_b["run"] / "parent-v2-accept")
            assert acc_v2["kind"] == "ExactCommandState" and acc_v2["state"] == "Accepted", acc_v2
        finally:
            stop_procs([(xp_proc, xf)])
    finally:
        stop_procs(procs_b_p)

    # Snapshot real parent in-flight /2 X DB & E DB BEFORE first candidate open
    x_db_b_sha_before = file_digest(x_db_b)
    x_wal_b = Path(str(x_db_b) + "-wal")
    x_wal_b_sha_before = file_digest(x_wal_b) if x_wal_b.exists() else None
    dump_x_b_before = business_dump(x_db_b)
    e_db_b = Path(sess_b["nodes"]["E"]["db"])
    dump_e_b_before = business_dump(e_db_b)

    # 1) Candidate X refuses in-flight /2 DB with both /2 profile and rewritten /3 profile (0 bytes modified on FIRST open!)
    refuse_v2_prof = subprocess.run(
        [str(cbin / "x_execution_session"), "serve", "--db", str(x_db_b), "--profile", str(xp_v2_path), "--writer-epoch", "2"],
        capture_output=True,
        text=True,
    )
    assert refuse_v2_prof.returncode != 0 and "VersionUnsupported" in refuse_v2_prof.stderr, refuse_v2_prof.stderr
    assert file_digest(x_db_b) == x_db_b_sha_before
    assert (file_digest(x_wal_b) if x_wal_b.exists() else None) == x_wal_b_sha_before
    assert same(business_dump(x_db_b), dump_x_b_before)

    xp_v3_same = copy.deepcopy(xp_v2)
    xp_v3_same["profile_revision"] = "x-execution-profile/3"
    xp_v3_same_path = sess_b["run"] / "x-profile-v3-rewritten.json"
    xp_v3_same_path.write_bytes(canonical(xp_v3_same))
    refuse_v3_resume = subprocess.run(
        [str(cbin / "x_execution_session"), "serve", "--db", str(x_db_b), "--profile", str(xp_v3_same_path), "--writer-epoch", "2"],
        capture_output=True,
        text=True,
    )
    assert refuse_v3_resume.returncode != 0 and "VersionUnsupported" in refuse_v3_resume.stderr, refuse_v3_resume.stderr
    assert file_digest(x_db_b) == x_db_b_sha_before
    assert (file_digest(x_wal_b) if x_wal_b.exists() else None) == x_wal_b_sha_before
    assert same(business_dump(x_db_b), dump_x_b_before)
    refuse_v3_repeat = subprocess.run(
        [str(cbin / "x_execution_session"), "serve", "--db", str(x_db_b), "--profile", str(xp_v3_same_path), "--writer-epoch", "2"],
        capture_output=True,
        text=True,
    )
    assert refuse_v3_repeat.returncode != 0 and "VersionUnsupported" in refuse_v3_repeat.stderr, refuse_v3_repeat.stderr
    assert file_digest(x_db_b) == x_db_b_sha_before
    assert (file_digest(x_wal_b) if x_wal_b.exists() else None) == x_wal_b_sha_before

    # 2) Candidate standalone formal E on ReleasedExact FIN/5 DB:
    #    - original ReleaseExact replay returns byte-identical receipt FIRST
    #    - tampered ReleaseExact returns IdentityConflict
    #    - QueryCommand & QueryReleasedExact preserve original 14-field command & liability 90
    #    - fresh /3 X rejects raw and forged-model_ref delivery of this /5 command (0 calls, 0 fills)
    procs_b_c = init_and_spawn_eb(sess_b, cbin, "3", "cand-b", need_b=False)
    try:
        ewire_bc = make_ewire(sess_b, "3", "cand-b")
        replayed_rel = ewire_bc("E", "ReleaseExact-alpha", rel_payload_b2, "ReleasedExactReceipt", save_as="ReleaseExact-replay")
        assert same(replayed_rel, rel_b)
        tampered = copy.deepcopy(rel_payload_b2)
        tampered["x_epoch"] = "9"
        tampered_err = ewire_bc("E", "ReleaseExact-alpha", tampered, "Error", save_as="ReleaseExact-tampered")
        assert tampered_err["error"].startswith("IdentityConflict："), tampered_err
        q_cmd = ewire_bc(
            "E",
            "QueryCommand-alpha",
            dict(op="QueryCommand", command_id="cmd-alpha", cut=None, as_known_ns=None),
            "EconomicCommand",
        )
        assert q_cmd["state"] == "ReleasedExact" and same(q_cmd["record"]["command"], exact_v5)
        liab_b = retained_liability(ewire_bc)
        assert liab_b == 90

        # Fresh candidate /3 X cannot accept the /5 ReleasedExact command (raw or forged model_ref)
        xp_v3_fresh = build_x_profile(sess_b["run"], sess_b, "x-execution-profile/3", x_model, "x-v3-fresh.sock", sess_b["run"] / "cred.txt")
        xp_v3_fresh["history_simulation"]["e"]["authority_epoch"] = "3"
        xp_v3_fresh_path = sess_b["run"] / "x-profile-v3-fresh.json"
        xp_v3_fresh_path.write_bytes(canonical(xp_v3_fresh))
        x_db_v3 = sess_b["run"] / "x-v3-fresh.db"
        x_err_v3 = sess_b["run"] / "cand-x-v3.stderr"
        xf3 = x_err_v3.open("wb")
        xp3 = subprocess.Popen(
            [str(cbin / "x_execution_session"), "serve", "--db", str(x_db_v3), "--profile", str(xp_v3_fresh_path), "--writer-epoch", "1"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=xf3,
        )
        try:
            wait_ready(xp3, str(sess_b["run"] / "x-v3-fresh.sock"), "cand-x-v3", x_err_v3)
            for idx in (0, 1):
                assert x_call(
                    sess_b["run"] / "x-v3-fresh.sock",
                    "AdvanceBar",
                    dict(request_id=f"b{idx}", known_frontier_cut=f"f{idx}", bar=dict(index=idx, open=14, high=15, low=13, close=14), close_changes=[], capacity=dict(kind="none"), scenario_busts=[]),
                )["kind"] == "SimulationBatch"
            raw_rej = x_call(sess_b["run"] / "x-v3-fresh.sock", "AcceptExact", exact_v5, sess_b["run"] / "cand-v3-accept-raw-v5")
            assert raw_rej["kind"] == "Error" and "model_ref" in raw_rej["error"], raw_rej
            forged = copy.deepcopy(exact_v5)
            forged["model_ref"] = dict(model_id=x_model["model_id"], revision=x_model["revision"], content_hash=x_model_hash)
            forged_rej = x_call(sess_b["run"] / "x-v3-fresh.sock", "AcceptExact", forged, sess_b["run"] / "cand-v3-accept-forged-v5")
            assert forged_rej["kind"] == "Error" and "IdentityConflict" in forged_rej["error"], forged_rej
            assert x_call(sess_b["run"] / "x-v3-fresh.sock", "QueryCommand", "cmd-alpha")["state"] == "NoRecord"
        finally:
            stop_procs([(xp3, xf3)])
    finally:
        stop_procs(procs_b_c)

    dump_e_b_after = business_dump(e_db_b)
    for table in ("commits", "receipts", "messages", "book", "facts", "pending", "applications", "unmatched"):
        assert same(dump_e_b_before[table], dump_e_b_after[table]), (table, "mutated in state_b")

    report["state_b_released_and_inflight"] = dict(
        e_state="ReleasedExact",
        original_release_exact_replayed=True,
        tampered_release_exact_error=tampered_err["error"],
        inflight_v2_x_refused_with_v2_profile=refuse_v2_prof.stderr.strip(),
        inflight_v2_x_refused_with_v3_profile=refuse_v3_resume.stderr.strip(),
        inflight_v2_x_db_sha256_unchanged=(file_digest(x_db_b) == x_db_b_sha_before),
        fresh_v3_x_raw_v5_error=raw_rej["error"],
        fresh_v3_x_forged_v5_error=forged_rej["error"],
        retained_liability=liab_b,
    )

    # ── State C: Parent #2081 terminal /2 batch (Observed, b3) read-only inspection & X writer refusal ──
    sess_c = prepare_v5_session(out / "state_c_terminal_v2_batch", fixture)
    state_c = run_up_to_dispatchable(sess_c, pbin)
    procs_c_p = init_and_spawn_eb(sess_c, pbin, "2", "parent-c", need_b=False)
    s_listener = socket.socket(socket.AF_UNIX)
    s_listener.bind(str(sess_c["run"] / "s.sock"))
    s_listener.listen(4)
    s_listener.settimeout(0.2)
    stop_s = threading.Event()
    expected_c = {}

    drop_first_s = {"remaining": 1}

    def s_server():
        with s_listener:
            while not stop_s.is_set():
                try:
                    sock, _ = s_listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    return
                with sock:
                    frame = decode_frame(sock.makefile("rb").readline(1048577))
                    if drop_first_s["remaining"] > 0:
                        drop_first_s["remaining"] -= 1
                        continue
                    q = frame["payload"]
                    receipt = {k: v for k, v in q.items() if k != "op"}
                    receipt.update(
                        state="ExecuteCommitted",
                        receipt_id=expected_c["eligibility_ref"],
                        commit_ns="2",
                    )
                    response = reply_envelope(
                        frame,
                        receipt,
                        session_id=sess_c["sid"],
                        session_generation=sess_c["gen"],
                        namespace="s-authority-fixture/replies",
                        producer_id="S:fixture",
                        producer_epoch="1",
                    )
                    sock.sendall(canonical(response) + b"\n")

    signer = threading.Thread(target=s_server)
    signer.start()
    try:
        ewire_cp = make_ewire(sess_c, "2", "parent-c")
        rel_c = ewire_cp("E", "ReleaseExact-alpha", build_release_payload(sess_c, state_c["grants"], "2"), "ReleasedExactReceipt")
        exact_c = rel_c["record"]["command"]
        q_alpha = sess_c["plans"]["alpha"]
        x_alpha = q_alpha["exact"]
        expected_c.update(exact=exact_c, receipt_key=rel_c["receipt_key"], eligibility_ref=x_alpha["eligibility_ref"])

        xp_c = build_x_profile(sess_c["run"], sess_c, "x-execution-profile/2", x_model, "x-v2-term.sock", sess_c["run"] / "cred.txt")
        xp_c["history_simulation"]["e"]["authority_epoch"] = "2"
        xp_c_path = sess_c["run"] / "x-profile-v2.json"
        xp_c_path.write_bytes(canonical(xp_c))
        x_db_c = sess_c["run"] / "x-v2-terminal.db"
        x_err_c = sess_c["run"] / "parent-c-x.stderr"
        xfc = x_err_c.open("wb")
        xpc = subprocess.Popen(
            [str(pbin / "x_execution_session"), "serve", "--db", str(x_db_c), "--profile", str(xp_c_path), "--writer-epoch", "1"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=xfc,
        )
        try:
            wait_ready(xpc, str(sess_c["run"] / "x-v2-term.sock"), "parent-c-x", x_err_c)
            for idx in (0, 1):
                assert x_call(
                    sess_c["run"] / "x-v2-term.sock",
                    "AdvanceBar",
                    dict(request_id=f"b{idx}", known_frontier_cut=f"f{idx}", bar=dict(index=idx, open=14, high=15, low=13, close=14), close_changes=[], capacity=dict(kind="none"), scenario_busts=[]),
                )["kind"] == "SimulationBatch"
            assert x_call(sess_c["run"] / "x-v2-term.sock", "AcceptExact", exact_c)["state"] == "Accepted"
            local_change = dict(
                kind="submit",
                order=dict(
                    command_id=x_alpha["command_id"],
                    family_id=x_alpha["logical_order_family"],
                    chong_id=x_alpha["chong_id"],
                    revision=int(x_alpha["revision"]),
                    side=x_alpha["side"],
                    quantity=int(q_alpha["quantity"]),
                    kind=dict(kind="limit", price=int(q_alpha["limit_price"])),
                    eligibility_ref=x_alpha["eligibility_ref"],
                    projection_manifest=x_alpha["projection_manifest"],
                ),
            )
            # First AdvanceBar b2 drops S reply -> parent /2 X persists genuine ExecutionRequested + pending_batch (可能在途)
            b2_drop = x_call(
                sess_c["run"] / "x-v2-term.sock",
                "AdvanceBar",
                dict(request_id="b2", known_frontier_cut="f2", bar=dict(index=2, open=14, high=15, low=13, close=14), close_changes=[local_change], capacity=dict(kind="none"), scenario_busts=[]),
                sess_c["run"] / "parent-v2-b2-drop",
            )
            assert b2_drop["kind"] == "Error", b2_drop
            qreq = x_call(sess_c["run"] / "x-v2-term.sock", "QueryCommand", "cmd-alpha", sess_c["run"] / "parent-v2-query-execution-requested")
            assert qreq["kind"] == "ExactCommandState" and qreq["state"] == "ExecutionRequested", qreq
        finally:
            stop_procs([(xpc, xfc)])

        # Snapshot ExecutionRequested + pending_batch (可能在途) /2 X DB before retrying b2 + advancing b3 to Observed
        x_db_mhc = sess_c["run"] / "x-v2-execution-requested.db"
        shutil.copy2(x_db_c, x_db_mhc)
        for suffix in ("-wal", "-shm"):
            side = Path(str(x_db_c) + suffix)
            if side.exists():
                shutil.copy2(side, Path(str(x_db_mhc) + suffix))

        # Resume parent #2081 /2 X at writer_epoch=1 to complete pending b2 and advance b3 to terminal Observed
        term_sock = sess_c["run"] / "x-v2-term.sock"
        if term_sock.exists():
            term_sock.unlink()
        x_err_c2 = sess_c["run"] / "parent-c-x-b3.stderr"
        xfc2 = x_err_c2.open("wb")
        xpc2 = subprocess.Popen(
            [str(pbin / "x_execution_session"), "serve", "--db", str(x_db_c), "--profile", str(xp_c_path), "--writer-epoch", "1"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=xfc2,
        )
        try:
            wait_ready(xpc2, str(sess_c["run"] / "x-v2-term.sock"), "parent-c-x-b3", x_err_c2)
            assert x_call(
                sess_c["run"] / "x-v2-term.sock",
                "AdvanceBar",
                dict(request_id="b2", known_frontier_cut="f2", bar=dict(index=2, open=14, high=15, low=13, close=14), close_changes=[local_change], capacity=dict(kind="none"), scenario_busts=[]),
            )["kind"] == "SimulationBatch"
            b3 = x_call(
                sess_c["run"] / "x-v2-term.sock",
                "AdvanceBar",
                dict(request_id="b3", known_frontier_cut="f3", bar=dict(index=3, open=14, high=15, low=13, close=14), close_changes=[], capacity=dict(kind="none"), scenario_busts=[]),
            )
            assert b3["kind"] == "SimulationBatch" and [o["event"]["kind"] for o in b3["originals"]] == ["fill", "fee"]
            qobs = x_call(sess_c["run"] / "x-v2-term.sock", "QueryCommand", "cmd-alpha", sess_c["run"] / "parent-v2-query-observed")
            assert qobs["kind"] == "ExactCommandState" and qobs["state"] == "Observed", qobs
            qb3 = x_call(sess_c["run"] / "x-v2-term.sock", "QueryBatch", "b3", sess_c["run"] / "parent-v2-query-b3")
            assert qb3["kind"] == "SimulationBatch"
            b3_sha = digest(qb3)
        finally:
            stop_procs([(xpc2, xfc2)])
    finally:
        stop_s.set()
        try:
            s_listener.close()
        except OSError:
            pass
        signer.join(2)
        stop_procs(procs_c_p)

    # Verify candidate X refuses the ExecutionRequested + pending_batch (可能在途) /2 X DB under both /2 and rewritten /3 profiles without mutating rows
    dump_mhc_before = business_dump(x_db_mhc)
    xp_c_v3 = copy.deepcopy(xp_c)
    xp_c_v3["profile_revision"] = "x-execution-profile/3"
    xp_c_v3_path = sess_c["run"] / "x-profile-v3.json"
    xp_c_v3_path.write_bytes(canonical(xp_c_v3))
    mhc_refuse_v2 = subprocess.run(
        [str(cbin / "x_execution_session"), "serve", "--db", str(x_db_mhc), "--profile", str(xp_c_path), "--writer-epoch", "1"],
        capture_output=True,
        text=True,
    )
    assert mhc_refuse_v2.returncode != 0 and "VersionUnsupported" in mhc_refuse_v2.stderr, mhc_refuse_v2.stderr
    assert same(business_dump(x_db_mhc), dump_mhc_before)
    mhc_refuse_v3 = subprocess.run(
        [str(cbin / "x_execution_session"), "serve", "--db", str(x_db_mhc), "--profile", str(xp_c_v3_path), "--writer-epoch", "1"],
        capture_output=True,
        text=True,
    )
    assert mhc_refuse_v3.returncode != 0 and "VersionUnsupported" in mhc_refuse_v3.stderr, mhc_refuse_v3.stderr
    assert same(business_dump(x_db_mhc), dump_mhc_before)
    mhc_sha_checkpointed = file_digest(x_db_mhc)
    mhc_refuse_v3_repeat = subprocess.run(
        [str(cbin / "x_execution_session"), "serve", "--db", str(x_db_mhc), "--profile", str(xp_c_v3_path), "--writer-epoch", "1"],
        capture_output=True,
        text=True,
    )
    assert mhc_refuse_v3_repeat.returncode != 0 and "VersionUnsupported" in mhc_refuse_v3_repeat.stderr, mhc_refuse_v3_repeat.stderr
    assert file_digest(x_db_mhc) == mhc_sha_checkpointed
    report["state_b2_execution_requested_pending"] = dict(
        x_command_state="ExecutionRequested",
        has_pending_batch=True,
        refused_with_v2_profile=mhc_refuse_v2.stderr.strip(),
        refused_with_v3_profile=mhc_refuse_v3.stderr.strip(),
        x_db_tables_unchanged=True,
        x_db_sha256_unchanged=(file_digest(x_db_mhc) == mhc_sha_checkpointed),
    )

    # Inspect terminal /2 batch via BOTH parent #2081 reader AND candidate R2 reader on a tb03c archive-bound E DB
    dump_x_c_before = business_dump(x_db_c)
    x_db_c_sha_before = file_digest(x_db_c)
    reader_dir = out / "state_c_reader"
    reader_dir.mkdir(mode=0o700, parents=True)
    reader_e_db = reader_dir / "e.db"
    reader_manifest = dict(
        schema_revision="economic-manifest/1",
        session_id=sess_c["sid"],
        session_generation=sess_c["gen"],
        book_revision="tb03c-book/1",
        e=dict(db=str(reader_e_db), socket=str(reader_dir / "e.sock")),
        chongs=[
            dict(
                chong_id="alpha",
                symbol="alpha",
                operation_level="1",
                fixed_q="10",
                db=str(reader_dir / "b-alpha.db"),
                socket=str(reader_dir / "b-alpha.sock"),
            )
        ],
        authorized_sources=[
            dict(**sess_c["src_x"], operations=["CaptureExternal", "ResolveEvidence", "ReadView"])
        ],
        history_simulation_source=dict(
            **sess_c["src_x"],
            x_db=str(x_db_c),
            model_content_hash=x_model_hash,
        ),
        resources=dict(
            max_frame_bytes="1048576",
            read_timeout_ms="1000",
            write_timeout_ms="1000",
            response_timeout_ms="30000",
            queue_capacity="2",
            max_connections="2",
        ),
        clock=dict(kind="System"),
    )
    reader_manifest_path = reader_dir / "manifest.json"
    reader_manifest_path.write_bytes(canonical(reader_manifest))
    subprocess.run(
        [str(pbin / "e_economic_session"), "init", "--manifest", str(reader_manifest_path), "--db", str(reader_e_db)],
        check=True,
    )
    parent_inspect = subprocess.run(
        [
            str(pbin / "e_economic_session"),
            "inspect-simulation-capture-batch",
            "--manifest", str(reader_manifest_path),
            "--db", str(reader_e_db),
            "--batch-id", "b3",
            "--batch-receipt-sha256", b3_sha,
            "--x-id", "X",
            "--x-epoch", "1",
        ],
        capture_output=True,
        check=True,
    )
    cand_inspect = subprocess.run(
        [
            str(cbin / "e_economic_session"),
            "inspect-simulation-capture-batch",
            "--manifest", str(reader_manifest_path),
            "--db", str(reader_e_db),
            "--batch-id", "b3",
            "--batch-receipt-sha256", b3_sha,
            "--x-id", "X",
            "--x-epoch", "1",
        ],
        capture_output=True,
        check=True,
    )
    assert parent_inspect.stdout == cand_inspect.stdout
    (out / "state_c_terminal_v2_batch/parent-inspect-b3.stdout").write_bytes(parent_inspect.stdout)
    (out / "state_c_terminal_v2_batch/candidate-inspect-b3.stdout").write_bytes(cand_inspect.stdout)
    assert same(business_dump(x_db_c), dump_x_c_before)
    assert file_digest(x_db_c) == x_db_c_sha_before

    # Candidate X refuses to resume/write terminal /2 X DB
    term_refuse = subprocess.run(
        [str(cbin / "x_execution_session"), "serve", "--db", str(x_db_c), "--profile", str(xp_c_v3_path), "--writer-epoch", "2"],
        capture_output=True,
        text=True,
    )
    assert term_refuse.returncode != 0 and "VersionUnsupported" in term_refuse.stderr, term_refuse.stderr
    assert same(business_dump(x_db_c), dump_x_c_before)
    x_db_c_sha_checkpointed = file_digest(x_db_c)
    term_refuse_repeat = subprocess.run(
        [str(cbin / "x_execution_session"), "serve", "--db", str(x_db_c), "--profile", str(xp_c_v3_path), "--writer-epoch", "2"],
        capture_output=True,
        text=True,
    )
    assert term_refuse_repeat.returncode != 0 and "VersionUnsupported" in term_refuse_repeat.stderr, term_refuse_repeat.stderr
    assert file_digest(x_db_c) == x_db_c_sha_checkpointed

    report["state_c_terminal_v2_batch"] = dict(
        b3_receipt_sha256=b3_sha,
        inspect_stdout_byte_identical_to_parent=True,
        x_db_tables_unchanged=True,
        x_db_sha256_unchanged=(file_digest(x_db_c) == x_db_c_sha_checkpointed),
        candidate_x_resume_refusal=term_refuse.stderr.strip(),
    )

    (out / "r2_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print("PASS C3 R2 upgrade-pairing verification:", json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
