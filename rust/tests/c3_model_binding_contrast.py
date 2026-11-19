#!/usr/bin/env python3
"""#1407 C3：用正式 production_session 与已落盘非空夹具对比匹配模型、同命令费率替换与旧 /5 三臂。"""
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
from r4_anchor_fixture import TestAnchor
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


def run_arm(name: str, fixture: Path, bins: Path, out: Path, *, maker_numerator: int, upgrade_v6: bool):
    run = out / name
    run.mkdir(mode=0o700, parents=True)

    def write(filename: str, obj) -> Path:
        p = run / filename
        with p.open("xb") as f:
            f.write(canonical(obj))
        return p

    def load(path: Path):
        return decode_frame(path.read_bytes())

    def copied(filename: str) -> Path:
        p = run / filename
        shutil.copyfile(fixture / filename, p)
        return p

    manifest = load(fixture / "manifest.json")
    assert manifest["finance"]["schema_revision"] in ("tb03b-finance/5", "tb03b-finance/6")
    sid, gen = manifest["session_id"], manifest["session_generation"]
    assert (sid, gen) == ("tb03b-unit", "1")
    source_fields = ("source_namespace", "source_epoch", "producer_id", "producer_epoch")
    src_business = {k: manifest["authorized_sources"][0][k] for k in source_fields}
    src_x = {k: manifest["authorized_sources"][1][k] for k in source_fields}
    messages = {m: "1" for m in manifest["clock"]["plan"]["messages"]}
    messages["ReleaseExact-alpha"] = "2"
    manifest["clock"] = dict(kind="logical-bar/1", bars=dict(init="0", messages=messages, recover=["3"]))

    opener, binding = {}, {}
    for authority in manifest["voice_binding"]["authorities"]:
        a = authority["authority_id"]
        assert a in ("alpha", "beta")
        bundle = load(fixture / f"{a}-authority.json")
        verification = load(fixture / f"{a}-unit-review.json")
        for artifact in bundle["artifacts"]:
            p = copied(Path(artifact["path"]).name)
            assert artifact["sha256"] == file_digest(p) and int(artifact["bytes"]) == p.stat().st_size
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

    control_model = {**model(), "symbol": "alpha"}
    x_model = copy.deepcopy(control_model)
    x_model["fee_profile"]["maker"]["numerator"] = maker_numerator

    assert manifest["finance"]["input_sha256"] == file_digest(fixture / "input.json")
    data = load(fixture / "input.json")
    if upgrade_v6:
        data["schema_revision"] = "tb03b-finance/6"
        data["exact_release"]["model_coverage"]["model_ref"] = dict(
            model_id=control_model["model_id"],
            revision=control_model["revision"],
            content_hash=digest(control_model),
        )
        data_path = write("input.json", data)
        manifest["finance"]["schema_revision"] = "tb03b-finance/6"
        manifest["finance"]["input_sha256"] = file_digest(data_path)
    else:
        assert data["schema_revision"] == "tb03b-finance/5"
        data_path = copied("input.json")

    plans = {q["decision_id"]: q for q in data["plans"]}
    freeze = data["exact_release"]
    basis = copied("s-unit-basis-stub.json")
    stub = run / "s-unit-stub.sh"
    assert "'" not in str(basis)
    stub.write_text(f"#!/bin/sh\nexec /bin/cat '{basis}'\n")
    stub.chmod(0o700)
    manifest["finance"]["input_path"] = str(data_path)
    manifest["finance"]["structure"].update(
        binary=str(stub), binary_sha256=file_digest(stub), db=str(run / "s-unit.db")
    )
    nodes = {"E": manifest["e"], **{f"B:{x['chong_id']}": x for x in manifest["chongs"]}}
    for domain, node in nodes.items():
        short = "e" if domain == "E" else node["chong_id"]
        node.update(db=str(run / f"{short}.db"), socket=str(run / f"{short}.sock"))
    manifest_path = write("manifest.json", manifest)

    x_socket = str(run / "x.sock")
    pp = write(
        "x-profile.json",
        dict(
            profile_revision="x-execution-profile/3",
            mode="simulation",
            credential_scope=dict(env="UNUSED_SIMULATION_CREDENTIAL"),
            history_simulation=dict(
                model=x_model,
                session_id=sid,
                session_generation=gen,
                x_id="X",
                source_namespace=src_x["source_namespace"],
                source_epoch=src_x["source_epoch"],
                socket=x_socket,
                timeout_ms=5000,
                max_frame_bytes=1048576,
                conditions=freeze["conditions"],
                e=dict(
                    socket=nodes["E"]["socket"],
                    authority_id="E",
                    authority_epoch="1",
                    schema_revision="economic-session/1",
                    reply_namespace="economic-session/replies",
                    producer_id=f"E:{sid}",
                ),
                s=dict(
                    socket=str(run / "s.sock"),
                    authority_id="S",
                    authority_epoch="1",
                    schema_revision="s-authority-fixture/1",
                    reply_namespace="s-authority-fixture/replies",
                    producer_id="S:fixture",
                ),
            ),
        ),
    )

    sd = run / "sd"
    sd.mkdir()
    sdb = sd / "s.db"
    dec = dict(category="TestOnlyStructure", namespaces=["testonly.ohlc"])
    df = write("decl.json", dec)
    sclock = write(
        "sclock.json",
        dict(
            schema_revision="s-clock-plan/1",
            clock_plan_id="pse-01",
            origin_utc="2000-01-01T00:00:00Z",
            unit="ns",
            events={"input-1": dict(accept_ns="10", attempts=[dict(begin_ns="11", commit_ns="12")])},
        ),
    )
    catalog = SRC / "s_session/catalog/signed-catalog.json"
    sprofile = SRC / "s_session/profiles/ohlc_integer_tb02a_v1.json"
    init_res = subprocess.run(
        [
            str(bins / "s_structure_session"),
            "init",
            "--protocol-revision",
            "s-session/3",
            "--db",
            str(sdb),
            "--session",
            sid,
            "--catalog",
            str(catalog),
            "--profile",
            str(sprofile),
            "--session-generation",
            gen,
            "--clock-plan",
            str(sclock),
            "--delivery-retain-generations",
            "4",
            "--structure-source",
            str(df),
        ],
        capture_output=True,
        timeout=20,
    )
    assert init_res.returncode == 0, (init_res.stdout, init_res.stderr)
    sstate = sd / "state"
    sstate.mkdir()
    anchor = TestAnchor(
        sdb,
        sstate,
        limits=dict(
            max_total_wire_bytes="1073741824",
            max_total_node_bytes="1073741824",
            max_total_nodes="10000000",
            max_total_records="10000000",
            max_total_requests="1000000",
            max_elapsed_ms="600000",
            max_staged_bytes="67108864",
            max_store_bytes="1073741824",
        ),
    )
    env = dict(os.environ, **anchor.env())
    sres = write(
        "s-resources.json",
        dict(
            schema_revision="s-structure-resources/1",
            s_resources=dict(
                max_frame_bytes="1048576",
                read_timeout_ms="1000",
                write_timeout_ms="1000",
                response_timeout_ms="30000",
                audit_cache_source_bytes="1048576",
                queue_capacity="2",
                max_connections="2",
            ),
        ),
    )
    control = write(
        "production.json",
        dict(
            manifest_revision="production-session-manifest/1",
            profile="simulation",
            state_dir=str(run / "launcher-state"),
            execution_capabilities=dict(namespaces=["x-sim"]),
            structure_source=dec,
            s=dict(
                db=str(sdb),
                session=sid,
                catalog=str(catalog),
                profile=str(sprofile),
                clock_plan=str(sclock),
                session_generation=gen,
                delivery_retain_generations="4",
                admission_job_limits=str(anchor.limits_path),
                writer_epoch="1",
                socket=str(run / "structure.sock"),
                resource_config=str(sres),
            ),
            economic=dict(
                manifest=str(manifest_path),
                e=dict(db=str(nodes["E"]["db"]), epoch="1"),
                b=[dict(chong=a, db=str(nodes["B:" + a]["db"]), epoch="1") for a in ["alpha", "beta"]],
            ),
            x=dict(db=str(run / "x.db"), profile=str(pp), writer_epoch="1"),
        ),
    )

    out_log = (run / "outer.stdout").open("wb")
    err_log = (run / "outer.stderr").open("wb")
    outer = subprocess.Popen(
        [str(bins / "production_session"), "--manifest", str(control)],
        stdin=subprocess.DEVNULL,
        stdout=out_log,
        stderr=err_log,
        env=env,
    )

    s_requests = []
    s_listener = socket.socket(socket.AF_UNIX)
    s_listener.bind(str(run / "s.sock"))
    s_listener.listen(4)
    s_listener.settimeout(0.2)
    stop_s = threading.Event()
    expected_release = {}

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
                    q = frame["payload"]
                    s_requests.append(q)
                    assert q["op"] == "RequestConditionalExecution"
                    assert same(q["command"], expected_release["exact"])
                    assert q["release_receipt_id"] == expected_release["receipt_key"]
                    assert q["command_hash"] == digest(expected_release["exact"])
                    receipt = {k: v for k, v in q.items() if k != "op"}
                    receipt.update(
                        state="ExecuteCommitted",
                        receipt_id=expected_release["eligibility_ref"],
                        commit_ns="2",
                    )
                    response = reply_envelope(
                        frame,
                        receipt,
                        session_id=sid,
                        session_generation=gen,
                        namespace="s-authority-fixture/replies",
                        producer_id="S:fixture",
                        producer_epoch="1",
                    )
                    write(f"S-eligibility-{len(s_requests)}.request.json", frame)
                    write(f"S-eligibility-{len(s_requests)}.reply.json", response)
                    sock.sendall(canonical(response) + b"\n")

    signer = threading.Thread(target=s_server, daemon=True)
    signer.start()

    def wire(domain: str, label: str, req, *, expected=None):
        message = canonical(req) + b"\n"
        (run / f"{label}.request.wire").write_bytes(message)
        address = x_socket if domain == "X" else nodes[domain]["socket"]
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(12)
            s.connect(address)
            s.sendall(message)
            s.shutdown(socket.SHUT_WR)
            raw = s.makefile("rb").readline(16777217)
        (run / f"{label}.reply.wire").write_bytes(raw)
        assert raw.endswith(b"\n") and len(raw) <= 16777216, (label, raw[:200])
        result = decode_frame(raw)
        if domain != "X":
            result = validate_reply(req, result, producer=domain, producer_epoch="1")
        if expected is not None:
            assert result.get("kind") == expected, (label, result)
        return result

    def ewire(domain: str, message: str, payload, expected=None, source=src_business):
        return wire(
            domain,
            message,
            dict(
                schema_revision="economic-session/1",
                session_id=sid,
                session_generation=gen,
                **source,
                message_id=message,
                payload_hash=digest(payload),
                causal_refs=[],
                payload=payload,
            ),
            expected=expected,
        )

    def xwire(message: str, op: str, payload, expected=None):
        return wire(
            "X",
            message,
            dict(protocol="x-exact-simulation/1", op=op, payload=payload),
            expected=expected,
        )

    def observe():
        with closing(sqlite3.connect((run / "x.db").as_uri() + "?mode=ro", uri=True)) as c:
            accepted = c.execute("SELECT count(*) FROM x_exact_commands").fetchone()[0]
            owned = c.execute(
                "SELECT count(*) FROM x_exact_commands WHERE execute_evidence IS NOT NULL AND state IN ('MayHaveCalled','Observed')"
            ).fetchone()[0]
            calls = sum(
                1
                for (r,) in c.execute("SELECT request FROM x_sim_batches")
                for ch in json.loads(r)["close_changes"]
                if ch.get("order", ch)["command_id"] == "cmd-alpha"
            )
        return dict(accepted=accepted, owned=owned, calls=calls, s=len(s_requests))

    try:
        for addr in [n["socket"] for n in nodes.values()] + [x_socket]:
            wait_ready(outer, addr, f"outer-{name}", run / "outer.stderr")

        for a, raw in opener.items():
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
            ewire(f"B:{a}", f"bind-{a}", binding[a], "VoiceBound")

        rid = data["baseline"]["responsibility_id"]
        ewire(
            "E",
            f"ImportResponsibility-{rid}",
            dict(op="ImportResponsibility", responsibility_id=rid, writer_epoch="1"),
            "ResponsibilityImportedReceipt",
        )
        for a, q in plans.items():
            ewire(
                f"B:{a}",
                f"PrepareDecision-{a}",
                dict(op="PrepareDecision", decision_id=a, plan_hash=digest(q), writer_epoch="1"),
                "PreparedReceipt",
            )
        slot = data["slots"][0]
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
        for a, q in plans.items():
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
        before_view = ewire("E", "view-before-dispatch", dict(op="ReadView", cut=None, as_known_ns=None), "EconomicView")
        q = plans["alpha"]
        ewire(
            "E",
            "MakeDispatchable-alpha",
            dict(op="MakeDispatchable", decision_id="alpha", plan_hash=digest(q), writer_epoch="1"),
            "DispatchableReceipt",
        )
        x = q["exact"]
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
        certificate = dict(
            rd11_policy=freeze["rd11_policy"],
            responsibility_refs=[grants["alpha"]],
            structure_dependencies=[q["s_ref"]["object_id"] + "@" + q["s_ref"]["object_hash"]],
            market_dependencies=freeze["market_dependencies"],
            rule_revision=freeze["rule_revision"],
            conditions=freeze["conditions"],
        )
        cid = x["command_id"]
        release = ewire(
            "E",
            "ReleaseExact-alpha",
            dict(
                op="ReleaseExact",
                decision_id="alpha",
                command_id=cid,
                plan_hash=digest(change),
                certificate=certificate,
                x_id="X",
                x_epoch="1",
                writer_epoch="1",
            ),
            "ReleasedExactReceipt",
        )
        record = release["record"]
        exact = record["command"]
        expected_release.update(exact=exact, receipt_key=release["receipt_key"], eligibility_ref=x["eligibility_ref"])

        after_view = ewire("E", "view-after-release", dict(op="ReadView", cut=release["cut"], as_known_ns=None), "EconomicView")
        liability = before_view["image"]["finance"]["responsibilities"]
        assert same(liability, after_view["image"]["finance"]["responsibilities"])
        retained = sum(int(r["amount"]) for r in liability)
        assert retained == 90, retained

        def bar(i: int, changes=()):
            return dict(
                request_id=f"b{i}",
                known_frontier_cut=f"frontier{i}",
                bar=dict(index=i, open=14, low=13, high=15, close=14),
                capacity=dict(kind="none"),
                close_changes=list(changes),
                scenario_busts=[],
            )

        def advance(i: int, changes=(), expected="SimulationBatch", label=None):
            return xwire(label or f"x-bar-{i}", "AdvanceBar", bar(i, changes), expected)

        order = change["order"]
        local_change = {
            **change,
            "order": {
                **order,
                "revision": int(order["revision"]),
                "quantity": int(order["quantity"]),
                "kind": {"kind": "limit", "price": int(order["kind"]["price"])},
            },
        }

        advance(0)
        dbs = {d: Path(n["db"]) for d, n in nodes.items()}
        dbs["X"] = run / "x.db"
        baseline = {d: business_dump(p) for d, p in dbs.items()}

        if upgrade_v6 and maker_numerator == 1:
            early = xwire("early", "AcceptExact", exact, "Error")
            assert early["error"].startswith("InvalidDomain：X 接纳时钟早于 E 持久交付"), early
            assert xwire("query-early", "QueryCommand", cid, "ExactCommandState")["state"] == "NoRecord"
            counts_early = observe()
            assert counts_early == dict(accepted=0, owned=0, calls=0, s=0)
            advance(1)
            accepted = xwire("retry", "AcceptExact", exact, "ExactCommandState")
            assert accepted["state"] == "Accepted"
            counts_accepted = observe()
            assert counts_accepted == dict(accepted=1, owned=0, calls=0, s=0)
            advance(2, [local_change])
            counts_executed = observe()
            assert counts_executed == dict(accepted=1, owned=1, calls=1, s=1)
            filled = advance(3)
            assert [o["event"]["kind"] for o in filled["originals"]] == ["fill", "fee"]
            fill = filled["originals"][0]["event"]["fill"]
            fee = filled["originals"][1]["event"]["amount"]
            assert (fill["quantity"], fill["price"], fill["amount"], fill["fee"], fee) == (2, 14, 28, 1, 1), filled
            assert filled["model_content_hash"] == digest(x_model) == record["model_ref"]["content_hash"]
            outcome = dict(
                arm=name,
                finance_revision=manifest["finance"]["schema_revision"],
                x_profile_revision="x-execution-profile/3",
                command_hash=record["command_hash"],
                release_receipt=release["receipt_key"],
                e_model=record["model_ref"],
                x_model=filled["model_content_hash"],
                accept_result="Accepted",
                fill=dict(quantity=fill["quantity"], price=fill["price"], amount=fill["amount"], fee=fill["fee"]),
                fee_original=fee,
                counts=dict(early=counts_early, accepted=counts_accepted, executed=counts_executed),
                retained_liability=retained,
            )
        elif upgrade_v6 and maker_numerator == 10:
            advance(1)
            refused = xwire("accept-mismatched", "AcceptExact", exact, "Error")
            assert refused["error"] == "IdentityConflict：精确命令获准模型身份与 X 实际装载模型内容不符", refused
            assert xwire("query-mismatched", "QueryCommand", cid, "ExactCommandState")["state"] == "NoRecord"
            counts_after_accept = observe()
            assert counts_after_accept == dict(accepted=0, owned=0, calls=0, s=0)

            refused_bar = advance(2, [local_change], expected="Error", label="advance-unaccepted")
            assert refused_bar["error"].startswith("MissingDependency："), refused_bar
            assert observe() == dict(accepted=0, owned=0, calls=0, s=0)

            forged = copy.deepcopy(exact)
            forged["model_ref"]["content_hash"] = digest(x_model)
            refused_forged = xwire("accept-forged-model-ref", "AcceptExact", forged, "Error")
            assert (
                refused_forged["error"]
                == "MissingDependency：权威拒绝：IdentityConflict：同 command_id 的命令内容与 E 已交付对象不同"
            ), refused_forged
            assert xwire("query-forged", "QueryCommand", cid, "ExactCommandState")["state"] == "NoRecord"
            assert observe() == dict(accepted=0, owned=0, calls=0, s=0)

            stripped = copy.deepcopy(exact)
            stripped.pop("model_ref")
            refused_stripped = xwire("accept-stripped-model-ref", "AcceptExact", stripped, "Error")
            assert "model_ref" in refused_stripped["error"], refused_stripped
            assert observe() == dict(accepted=0, owned=0, calls=0, s=0)

            advance(2)
            bar3 = advance(3)
            assert bar3["originals"] == [], bar3
            assert bar3["model_content_hash"] == digest(x_model)
            assert bar3["model_content_hash"] != record["model_ref"]["content_hash"]
            counts_final = observe()
            assert counts_final == dict(accepted=0, owned=0, calls=0, s=0)
            outcome = dict(
                arm=name,
                finance_revision=manifest["finance"]["schema_revision"],
                x_profile_revision="x-execution-profile/3",
                command_hash=record["command_hash"],
                release_receipt=release["receipt_key"],
                e_model=record["model_ref"],
                x_model=bar3["model_content_hash"],
                accept_result=refused["error"],
                advance_unaccepted_error=refused_bar["error"],
                forged_model_ref_error=refused_forged["error"],
                stripped_model_ref_error=refused_stripped["error"],
                originals=bar3["originals"],
                counts=dict(after_accept=counts_after_accept, final=counts_final),
                retained_liability=retained,
            )
        else:
            # Legacy tb03b-finance/5 E + active x-execution-profile/3 X
            assert "model_ref" not in exact
            advance(1)
            refused_legacy = xwire("accept-legacy-v5", "AcceptExact", exact, "Error")
            assert "model_ref" in refused_legacy["error"], refused_legacy
            forged_v5 = copy.deepcopy(exact)
            forged_v5["model_ref"] = dict(
                model_id=x_model["model_id"],
                revision=x_model["revision"],
                content_hash=digest(x_model),
            )
            refused_forged_v5 = xwire("accept-legacy-v5-forged", "AcceptExact", forged_v5, "Error")
            assert (
                refused_forged_v5["error"]
                == "MissingDependency：权威拒绝：IdentityConflict：同 command_id 的命令内容与 E 已交付对象不同"
            ), refused_forged_v5
            assert xwire("query-legacy-v5", "QueryCommand", cid, "ExactCommandState")["state"] == "NoRecord"
            advance(2)
            bar3 = advance(3)
            assert bar3["originals"] == []
            counts_final = observe()
            assert counts_final == dict(accepted=0, owned=0, calls=0, s=0)
            outcome = dict(
                arm=name,
                finance_revision=manifest["finance"]["schema_revision"],
                x_profile_revision="x-execution-profile/3",
                command_hash=record["command_hash"],
                release_receipt=release["receipt_key"],
                e_model=record["model_ref"],
                x_model=bar3["model_content_hash"],
                legacy_v5_error=refused_legacy["error"],
                forged_v5_error=refused_forged_v5["error"],
                originals=bar3["originals"],
                counts=dict(final=counts_final),
                retained_liability=retained,
            )

        assert all(same(baseline[d], business_dump(dbs[d])) for d in nodes)
        write("business.json", {d: business_dump(p) for d, p in dbs.items()})
        write("summary.json", outcome)
        return outcome
    finally:
        stop_s.set()
        try:
            s_listener.close()
        except OSError:
            pass
        signer.join(2)
        if outer.poll() is None:
            outer.terminate()
        try:
            outer.wait(timeout=8)
        except subprocess.TimeoutExpired:
            outer.kill()
            outer.wait()
        out_log.close()
        err_log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--bin", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    fixture, bins, out = (p.resolve() for p in (args.fixture, args.bin, args.out))
    out.mkdir(mode=0o700, parents=True)

    control = run_arm("control", fixture, bins, out, maker_numerator=1, upgrade_v6=True)
    altered = run_arm("altered", fixture, bins, out, maker_numerator=10, upgrade_v6=True)
    legacy_v5 = run_arm("legacy_v5", fixture, bins, out, maker_numerator=1, upgrade_v6=False)

    assert (out / "control/input.json").read_bytes() == (out / "altered/input.json").read_bytes()
    assert control["command_hash"] == altered["command_hash"]
    assert control["release_receipt"] == altered["release_receipt"]
    assert control["e_model"] == altered["e_model"]
    assert control["x_model"] != altered["x_model"]
    assert control["retained_liability"] == altered["retained_liability"] == legacy_v5["retained_liability"] == 90

    comparison = dict(
        only_model_change="fee_profile.maker.numerator:1->10",
        byte_equal=dict(
            input_json=True,
            command_hash=(control["command_hash"] == altered["command_hash"]),
            release_receipt=(control["release_receipt"] == altered["release_receipt"]),
            accept_request_wire=(
                (out / "control/retry.request.wire").read_bytes()
                == (out / "altered/accept-mismatched.request.wire").read_bytes()
            ),
        ),
        control=control,
        altered=altered,
        legacy_v5=legacy_v5,
    )
    (out / "comparison.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False) + "\n")
    print("PASS C3 model-binding contrast:", json.dumps(comparison, ensure_ascii=False))


if __name__ == "__main__":
    main()
