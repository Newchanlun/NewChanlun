"""#1375：对权威提交批核原件，再让原 E 接纳口补录。不开经济放行。"""
import json
import socket
import sqlite3
import subprocess
import time


def exercise(e_bin, directory, e_socket, x_db, source, receipt, alternate, other, canonical, digest,
             *, archived_v1=False):
    def client(source_db, name):
        db = directory / f"{name}.sqlite"
        manifest = directory / f"{name}.json"
        manifest.write_text(canonical(dict(
            schema_revision="economic-manifest/1",
            session_id=source["session_id"],
            session_generation=source["session_generation"],
            book_revision="tb03c-book/1",
            e=dict(db=str(db), socket=str(e_socket)),
            chongs=[dict(chong_id="ch-a", symbol="TEST", operation_level="1", fixed_q="10",
                         db=str(directory / f"B-{name}.sqlite"), socket=str(e_socket) + "-b")],
            authorized_sources=[dict(**principal, operations=[
                "CaptureExternal", "QueryFact", "ReadView", "ResolveEvidence"
            ])],
            history_simulation_source=dict(**principal, x_db=str(source_db),
                                           model_content_hash=receipt["model_content_hash"]),
            resources=dict(max_frame_bytes="1048576", read_timeout_ms="1000",
                           write_timeout_ms="1000", response_timeout_ms="10000",
                           queue_capacity="2", max_connections="2"),
            clock=dict(kind="System"),
        )))

        def argv(op, *args):
            return [str(e_bin), op, "--manifest", str(manifest), "--db", str(db), *args]

        def run(op, *args, error=None):
            r = subprocess.run(argv(op, *args), capture_output=True, timeout=15)
            if error:
                assert r.returncode != 0 and error in r.stderr.decode(), (r.stdout, r.stderr)
                assert not r.stdout
                with (directory / "inspect-refusals.log").open("a") as log:
                    log.write(f"{r.returncode}: {r.stderr.decode()}")
                return
            assert not r.returncode, (r.stdout, r.stderr)
            return json.loads(r.stdout)

        assert run("init")["kind"] == "Initialized"

        def inspect(anchor=receipt, epoch="1", error=None):
            return run(
                "inspect-simulation-capture-batch", "--batch-id", anchor["request_id"],
                "--batch-receipt-sha256", digest(anchor), "--x-id", source["x_id"],
                "--x-epoch", epoch, error=error,
            )

        return db, argv, run, inspect

    principal = dict(source_namespace=source["source_namespace"], source_epoch=source["source_epoch"],
                     producer_id=source["x_id"], producer_epoch="1")

    def send(message, payload):
        frame = dict(schema_revision="economic-session/1", **principal,
                     session_id=source["session_id"], session_generation=source["session_generation"],
                     message_id=message, payload_hash=digest(payload), causal_refs=[], payload=payload)
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(5)
            connection.connect(str(e_socket))
            connection.sendall((canonical(frame) + "\n").encode())
            connection.shutdown(socket.SHUT_WR)
            response = json.loads(connection.makefile("rb").readline())
        return response["payload"]

    def save(label, value):
        (directory / f"{label}.json").write_text(canonical(value) + "\n")

    def capture(article):
        # Only the already authorized source is allowed to repair its facts.
        # Retain the same message ID and token in case of a lost response.
        key = article["fact_key"]
        return send(f"capture-{key}", dict(op="CaptureExternal", raw_utf8=article["raw_utf8"],
                                          json_pointer=article["json_pointer"], token=f"token-{key}",
                                          source_event_time=article["source_event_time"]))

    def reject_corrupt_x(name, sql, args, error):
        corrupt = directory / f"{name}.sqlite"
        with sqlite3.connect(x_db.as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(corrupt) as dst:
            src.backup(dst)
            assert dst.execute(sql, args).rowcount == 1
        e_db, _, _, inspect_corrupt = client(corrupt, f"{name}-e")
        inspect_corrupt(error=error)
        with sqlite3.connect(e_db.as_uri() + "?mode=ro", uri=True) as c:
            assert c.execute("SELECT count(*) FROM facts").fetchone() == (0,)

    # Keep batch and result fixed. Each copy lacks a different independent proof.
    wrong_revision = "x-execution-profile/3" if archived_v1 else "x-execution-profile/1"
    reject_corrupt_x("mixed-profile", "UPDATE x_meta SET value=? WHERE key='profile_revision'",
                     (wrong_revision,), "VersionUnsupported")
    if archived_v1:
        # 两层均声称 /2 或 /3 但仍是 /1 原件：必须在对应版本解码失败，不得改用 /1 重试。
        for claimed in ("x-execution-profile/2", "x-execution-profile/3"):
            tag = claimed.rsplit("/", 1)[1]
            corrupt = directory / f"v{tag}-with-v1-wire.sqlite"
            with sqlite3.connect(x_db.as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(corrupt) as dst:
                src.backup(dst)
                dst.execute("UPDATE x_meta SET value=? WHERE key='profile_revision'", (claimed,))
                dst.execute("INSERT INTO x_sim_meta VALUES('exact_profile_revision',?)", (claimed,))
            _, _, _, inspect_wrong_wire = client(corrupt, f"v{tag}-with-v1-wire-e")
            inspect_wrong_wire(error="InvalidDomain")
        reject_corrupt_x("wrong-e-proof", "UPDATE x_exact_commands SET release_evidence="
                         "json_set(release_evidence,'$.command_hash','wrong') WHERE id=?", ("a",),
                         "权威回执未绑定原命令")
        reject_corrupt_x("wrong-s-release", "UPDATE x_exact_commands SET execute_evidence="
                         "json_set(execute_evidence,'$.reply.release_receipt_id','wrong') WHERE id=?",
                         ("a",), "S 收据未绑定本次精确交付")
    fee = receipt["originals"][1]["event"]["source"]["external_fact_id"]
    reject_corrupt_x("missing-fee", "DELETE FROM x_sim_originals WHERE id=?", (fee,),
                     "Query returned no rows")
    reject_corrupt_x("missing-x-command", "DELETE FROM x_exact_commands WHERE id=?", ("a",),
                     "缺已接纳命令权威原件")
    reject_corrupt_x("missing-s-proof", "UPDATE x_exact_commands SET execute_evidence=NULL WHERE id=?",
                     ("a",), "执行缺S原件")
    reject_corrupt_x("wrong-release-link", "UPDATE x_exact_commands SET release_receipt=? WHERE id=?",
                     ("wrong-receipt", "a"), "交付引用不符")

    if alternate is not None:
        _, _, _, alternate_inspect = client(alternate, "alternate-frontier-e")
        alternate_result = alternate_inspect(anchor=other)
        assert alternate_result["state_content_hash"] == receipt["state_content_hash"]
        assert alternate_result["batch_receipt_sha256"] == digest(other)
        assert [e["raw_utf8"] for e in alternate_result["entries"]] == list(map(canonical, other["originals"]))
        alternate_inspect(anchor=receipt, error="完整回执摘要不同")
        save("alternate-frontier-inspected", alternate_result)
    save("query-batch-b1", receipt)
    save("query-batch-b1-alternate", other)

    _, argv, run, inspect = client(x_db, "good-e")
    assert other["state_content_hash"] == receipt["state_content_hash"] and other != receipt
    inspect(anchor=other, error="完整回执摘要不同")
    inspect(epoch="2", error="writer epoch")
    inspect(anchor={**receipt, "state_content_hash": "0" * 64}, error="完整回执摘要不同")
    inspect(anchor={**receipt, "request_id": "uncommitted"}, error="Query returned no rows")
    empty = inspect()
    assert empty["kind"] == "SimulationCaptureBatch" and empty["release_eligibility"] == "NotEvaluated"
    assert empty["batch_receipt_sha256"] == digest(receipt)
    assert empty["state_content_hash"] == receipt["state_content_hash"]
    assert [e["state"] for e in empty["entries"]] == ["Missing", "Missing"]
    assert [e["source_cursor"] for e in empty["entries"]] == ["1", "1"]
    fills = receipt["originals"]
    assert len(fills) == 2 and [e["event"]["kind"] for e in fills] == ["fill", "fee"]
    assert [e["raw_utf8"] for e in empty["entries"]] == list(map(canonical, fills))
    save("batch-before", empty)

    def start(epoch):
        with (directory / f"e-{epoch}.stderr").open("wb") as log:
            process = subprocess.Popen(argv("serve", "--epoch", epoch),
                                       stdout=subprocess.DEVNULL, stderr=log)
        until = time.monotonic() + 5
        while time.monotonic() < until and process.poll() is None:
            with socket.socket(socket.AF_UNIX) as connection:
                try:
                    connection.connect(str(e_socket))
                except (FileNotFoundError, ConnectionRefusedError):
                    time.sleep(.01)
                else:
                    return process
        if process.poll() is None:
            process.terminate()
            process.wait(5)
        raise AssertionError((directory / f"e-{epoch}.stderr").read_text())

    def stop(process):
        if process.poll() is None:
            process.terminate()
        process.wait(5)
        e_socket.unlink(missing_ok=True)  # isolated process fixture, not an S recovery operation

    e = start("1")
    try:
        # First fill already made it across. The read-side plan must distinguish the missing fee.
        fill_receipt = capture(empty["entries"][0])
        assert fill_receipt["kind"] == "Recorded", fill_receipt
        one_missing = inspect()
        save("batch-missing-fee", one_missing)
        fill_entry, fee_entry = one_missing["entries"]
        assert fill_entry["receipt"] == fill_receipt
        assert fill_entry["state"] == "Recorded" and fee_entry["state"] == "Missing"
        fee_receipt = capture(fee_entry)
        assert fee_receipt["kind"] == "Recorded", fee_receipt
        assert capture(fee_entry) == fee_receipt
        complete = inspect()
        assert complete["e_cut"]["commit_seq"] == "2", complete
        assert [item["receipt"] for item in complete["entries"]] == [fill_receipt, fee_receipt]
        assert all(item["pending"]["reason"]["on"] == "economic_components" for item in complete["entries"])
        save("batch-after", complete)
        for item in complete["entries"]:
            fact = send("fact-" + item["fact_key"], dict(op="QueryFact", fact_key=item["fact_key"]))
            assert fact["kind"] == "EconomicFact" and fact["receipt"] == item["receipt"]
            assert fact["fact"]["raw_utf8"] == item["raw_utf8"]
        entry = complete["entries"][0]
        covered = {field: fill_receipt[field] for field in ("fact_key", "token", "fact_hash")}
        refused = send("still-not-settled", dict(op="ResolveEvidence", evidence_id="missing-components",
                       covered=[covered], frontier=dict(
                           source_namespace=principal["source_namespace"],
                           source_epoch=principal["source_epoch"], cursor=entry["source_cursor"]),
                       dependency_version="1"))
        assert refused["kind"] == "Error" and "分量" in refused["error"], refused
        save("resolve-refused", refused)
        assert inspect() == complete
    finally:
        stop(e)

    recovered = run("recover")
    assert recovered["cut"] == complete["e_cut"] and recovered["writer_epoch"] == "2", recovered
    save("e-recovered", recovered)
    again = start("2")
    try:
        assert again.pid != e.pid and inspect() == complete
        assert capture(fee_entry) == fee_receipt
        assert inspect() == complete
        view = send("recovered-view", dict(op="ReadView", cut=None, as_known_ns=None))
        assert len(view["image"]["recorded"]) == len(view["image"]["pending"]) == 2
        assert view["image"]["applied"] == [] and view["image"]["book"] is None
        save("recovered-view", view)
    finally:
        stop(again)
    print("PASS #1375: full batch identity and X cold audit; alternate frontier, missing command and missing fee refused; 1 missing → 2 Recorded/Pending; original receipts survive new E process")
