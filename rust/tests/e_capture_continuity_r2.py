"""#1375 AC3 R2 长期回归锁（Linux Docker 隔离实测）：
覆盖健康无 tape 重启、旧库无改 manifest 升级（干净/真实故障对照）、写失败后 SIGTERM 禁发交接、
放行时刻结束界（2000 未来事实不挡 1202，179 过去缺口仍挡）、责任界分级（已知且充分覆盖无关重
Pending 不停摆全账；未覆盖/未知范围 account:* 仍保守全域拦截）。
"""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

SEED = Path("/seed")
CORPUS = Path("/corpus")
ROOT = Path("/tmp/chain")
OUT = Path("/out")
P = "/events/0"


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    raw = canonical(value)
    path.write_bytes(raw)
    return digest(raw)


def receipt_item(doc, token):
    ev = doc["events"][0]
    src = ev["source"]
    fk = [src[x] for x in ("source_namespace", "source_epoch", "external_fact_id")]
    return dict(
        token=token,
        fact_key=digest(canonical(fk)),
        fact_hash=digest(
            canonical(
                dict(
                    raw_sha256=digest(canonical(doc)),
                    json_pointer=P,
                    event=ev,
                    units=doc["units"],
                )
            )
        ),
    )


def make_reconcile_item(raw_utf8, token, json_pointer=P):
    doc = json.loads(raw_utf8)
    ev = doc["events"][0]
    src = ev["source"]
    fk = digest(
        canonical([src[x] for x in ("source_namespace", "source_epoch", "external_fact_id")])
    )
    raw_sha = digest(raw_utf8.encode())
    fh = digest(
        canonical(
            dict(
                raw_sha256=raw_sha,
                json_pointer=json_pointer,
                event=ev,
                units=doc["units"],
            )
        )
    )
    return dict(
        fact_key=fk,
        fact_hash=fh,
        raw_sha256=raw_sha,
        json_pointer=json_pointer,
        token=token,
        source_cursor=src["source_cursor"],
    )


def build_sealed_fixture(m, extras):
    """extras: list of (name, chong_id, emitted_ns, covered, cursor, ext_id, is_fee)"""
    data = read(ROOT / "input.json")
    documents, coverage = [], []
    for a in ("alpha", "beta"):
        p = ROOT / f"{a}-opening_raw.json"
        doc = read(p)
        ev = doc["events"][0]
        ev["stable_point"] = dict(profile="TestOnly", seq="1", source_ref="sp")
        ev["book_identity"]["side"] = "long"
        doc["evidence_index"]["fragments"]["sp"] = [dict(json_pointer=P + "/stable_point")]
        raw_hash = save(p, doc)
        entry = receipt_item(doc, "token-" + a)
        coverage.append(entry)
        documents.append(
            dict(emitted_ns="1", raw_utf8=canonical(doc).decode(), tokens=[entry["token"]])
        )
        bp, rp = ROOT / f"{a}-authority.json", ROOT / f"{a}-unit-review.json"
        bundle, review = read(bp), read(rp)
        bundle["bindings"][0]["opening_source"].update(
            raw_sha256=raw_hash, fact_hash=entry["fact_hash"]
        )
        artifact = next(x for x in bundle["artifacts"] if x["name"] == "opening_raw")
        artifact.update(sha256=raw_hash, bytes=str(p.stat().st_size))
        review.update(bundle_sha256=save(bp, bundle), artifacts=bundle["artifacts"])
        auth = next(x for x in m["voice_binding"]["authorities"] if x["authority_id"] == a)
        auth.update(bundle_sha256=review["bundle_sha256"], verification_sha256=save(rp, review))

    corpus = read(CORPUS / "raw/chong-R1.json")
    for name, chong_id, emitted_ns, covered, cursor, ext_id, is_fee in extras:
        i = 3 if is_fee else 1
        ev = json.loads(json.dumps(corpus["events"][i]))
        ev["source"].update(
            source_namespace="test",
            source_epoch="one",
            source_cursor=cursor,
            external_fact_id=ext_id,
        )
        ev["chong_id"] = chong_id
        if not is_fee:
            ev["allocation_id"] = f"alloc-{ext_id}"
            ev["known_cost_components"][0].update(amount_text="14", canonical_amount="14")
        else:
            ev["depends_on"].update(
                source_namespace="test", source_epoch="one", external_fact_id="R-buy"
            )
            ev["known_cost_components"][0]["fill_ref"].update(
                source_namespace="test",
                source_epoch="one",
                external_fact_id="R-buy",
                allocation_id="alloc-R-buy",
                chong_id=chong_id,
            )
        fragments = {
            k: [dict(json_pointer=x["json_pointer"].replace(f"/events/{i}/", P + "/")) for x in paths]
            for k, paths in corpus["evidence_index"]["fragments"].items()
            if all(x["json_pointer"].startswith(f"/events/{i}/") for x in paths)
        }
        doc = dict(
            format=corpus["format"],
            units=corpus["units"],
            events=[ev],
            evidence_index=dict(fragments=fragments),
        )
        entry = receipt_item(doc, name)
        documents.append(
            dict(emitted_ns=str(emitted_ns), raw_utf8=canonical(doc).decode(), tokens=[name])
        )
        if covered:
            coverage.append(entry)
    data["baseline"]["covered_facts"] = coverage
    m["finance"]["input_sha256"] = save(ROOT / "input.json", data)
    tape = dict(
        format="test-only-economic-source/1",
        session_id=m["session_id"],
        session_generation=m["session_generation"],
        source=m["finance"]["coordinator_source"],
        documents=documents,
    )
    p = ROOT / "source.json"
    m["test_only_capture_tape"] = dict(path=str(p), sha256=save(p, tape))
    m["book_revision"] = "tb03c-book/1"
    m["authorized_sources"][0]["operations"].append("ResolveEvidence")
    return documents


def run(mode, expect="pass"):
    assert os.listdir("/sys/class/net") == ["lo"]
    disk = Path("/ej")
    v = os.statvfs(disk)
    assert 0 < v.f_blocks * v.f_frsize <= 16 << 20 and disk.stat().st_dev != Path("/tmp").stat().st_dev
    assert not list(disk.iterdir()) and not list(OUT.iterdir())
    ROOT.mkdir()
    for pattern in (
        "*-authority.json",
        "*-unit-review.json",
        "*-opening_raw.json",
        "*-input.json",
        "*-instrument_declaration.json",
        "*-controlled_gammas.json",
        "*-carrier_objects.json",
        "s-unit-stub.sh",
        "s-unit-basis-stub.json",
        "input.json",
    ):
        for f in SEED.glob(pattern):
            shutil.copyfile(f, ROOT / f.name)
    (ROOT / "s-unit-stub.sh").chmod(0o700)
    manifest = read(SEED / "manifest.json")

    docs = None
    if mode in {"future-live", "future-restart", "future-kill"}:
        docs = build_sealed_fixture(
            manifest,
            [
                ("fill", "alpha", 2000, True, "2", "R-buy", False),
                ("fee", "alpha", 2000, True, "2", "R-fee", True),
            ],
        )
    elif mode == "future-plus-past-gap":
        docs = build_sealed_fixture(
            manifest,
            [
                ("fill", "alpha", 179, True, "2", "R-buy", False),
                ("fee", "alpha", 2000, True, "2", "R-fee", True),
            ],
        )
    elif mode == "scoped-pending-covered":
        docs = build_sealed_fixture(
            manifest,
            [("fill", "beta", 179, True, "2", "R-beta-buy", False)],
        )
    elif mode == "scoped-pending-uncovered":
        docs = build_sealed_fixture(
            manifest,
            [("fill", "beta", 179, False, "2", "R-beta-buy", False)],
        )
    elif mode == "scoped-pending-unknown":
        docs = build_sealed_fixture(
            manifest,
            [("fill", "gamma", 179, True, "2", "R-gamma-buy", False)],
        )

    clock = manifest["clock"]["plan"]["messages"]
    for name, ns in [
        ("cold-release", 1200),
        ("cold-release-2", 1250),
        ("fill", 1010),
        ("fee", 1020),
        ("resolve-fill", 1030),
        ("resolve-fee", 1040),
    ]:
        clock[name] = dict(received_ns=str(ns), first_known_ns=str(ns + 1), commit_ns=str(ns + 2))
    clock["fill"] = {k: [str(180 + j), val] for j, (k, val) in enumerate(clock["fill"].items())}
    clock["capture-late"] = {
        k: [str(180 + j), str(1010 + j)] for j, k in enumerate(("received_ns", "first_known_ns", "commit_ns"))
    }
    mp = ROOT / "manifest.json"
    manifest_sha = save(mp, manifest)

    nodes = {"E": manifest["e"], **{r["chong_id"]: r for r in manifest["chongs"]}}
    processes, epochs = {}, dict.fromkeys(nodes, "1")
    frames = {}
    bindir = "/parent" if mode in {"upgrade-clean", "upgrade-faulted", "upgrade-faulted-parent"} else "/binset"

    def cli(node, *args):
        return [
            bindir + "/" + ("e_economic_session" if node == "E" else "b_chong_session"),
            args[0],
            "--manifest",
            str(mp),
            "--db",
            nodes[node]["db"],
            *([] if node == "E" else ["--chong", node]),
            *args[1:],
        ]

    def start(node):
        args = cli(node, "serve", "--epoch", epochs[node])
        if node != "E":
            args.extend(["--e-epoch", epochs["E"]])
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL)
        processes[node] = proc
        for _ in range(300):
            if proc.poll() is not None:
                raise RuntimeError((args, proc.returncode))
            if Path(nodes[node]["socket"]).exists():
                break
            time.sleep(0.01)
        else:
            raise TimeoutError(args)

    def wire(label, base, payload=None, msg=None, node="E", kind=None, error=None):
        frame = read(SEED / (base + ".request.wire"))
        p = payload if payload is not None else frame["payload"]
        frame.update(payload=p, payload_hash=digest(canonical(p)), message_id=msg or frame["message_id"])
        sent = canonical(frame) + b"\n"
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(20)
            s.connect(nodes[node]["socket"])
            s.sendall(sent)
            s.shutdown(socket.SHUT_WR)
            received = s.makefile("rb").readline()
        (OUT / (label + ".request.wire")).write_bytes(sent)
        (OUT / (label + ".reply.wire")).write_bytes(received)
        reply = json.loads(received)
        assert reply["producer_epoch"] == epochs[node] and reply["payload_hash"] == digest(
            canonical(reply["payload"])
        )
        result = reply["payload"]
        if kind:
            assert result["kind"] == kind, (label, result)
        if error:
            assert result["kind"] == "Error" and error in result["error"], (label, result)
        frames[label] = result
        return result

    def capture_body(item):
        ev = json.loads(item["raw_utf8"])["events"][0]
        return dict(
            op="CaptureExternal",
            raw_utf8=item["raw_utf8"],
            json_pointer=P,
            token=item["tokens"][0],
            source_event_time=ev["source"].get("source_event_time"),
        )

    def cold_release(label, msg="cold-release", **checks):
        p = read(SEED / "ReleaseExact-alpha-late.request.wire")["payload"]
        p["writer_epoch"] = epochs["E"]
        return wire(label, "ReleaseExact-alpha-late", p, msg, **checks)

    def fill_disk():
        pad = disk / "pad"
        v_now = os.statvfs(disk)
        with pad.open("wb") as f:
            os.posix_fallocate(f.fileno(), 0, v_now.f_bavail * v_now.f_frsize)
        assert os.statvfs(disk).f_bavail == 0
        return pad

    def restart_e(sigkill=False, switch_to_binset=False):
        nonlocal bindir
        old = processes["E"]
        if sigkill:
            old.kill()
        else:
            old.terminate()
        old.wait(timeout=10)
        Path(nodes["E"]["socket"]).unlink(missing_ok=True)
        if switch_to_binset:
            bindir = "/binset"
        r = subprocess.run(cli("E", "recover"), capture_output=True, check=True)
        recovered = json.loads(r.stdout)
        epochs["E"] = recovered["writer_epoch"]
        start("E")
        return old.returncode, recovered

    try:
        for n in nodes:
            subprocess.run(cli(n, "init"), check=True, stdout=subprocess.DEVNULL)
            start(n)
        recorded_items = []
        for idx, a in enumerate(("alpha", "beta")):
            key = "capture-" + a
            body = capture_body(docs[idx]) if docs else None
            fact = wire(key, key, body, kind="Recorded")
            sent_p = json.loads((OUT / (key + ".request.wire")).read_text())["payload"]
            recorded_items.append(make_reconcile_item(sent_p["raw_utf8"], sent_p["token"], sent_p["json_pointer"]))
            for op, field, kind in [("apply-", "expected_fact_hash", "Applied"), ("bind-", "opening_basis", "VoiceBound")]:
                label = op + a
                b = read(SEED / (label + ".request.wire"))["payload"]
                if op == "bind-":
                    b[field]["expected_fact_hash"] = fact["fact_hash"]
                else:
                    b[field] = fact["fact_hash"]
                wire(label, label, b, node=a, kind=kind)
        for label, n, kind in [
            ("ImportResponsibility-existing20", "E", "ResponsibilityImportedReceipt"),
            ("PrepareDecision-alpha", "alpha", "PreparedReceipt"),
            ("PrepareDecision-beta", "beta", "PreparedReceipt"),
            ("Reserve-slot", "E", "ReserveReceipt"),
            ("CommitDecision-alpha", "alpha", "LocalCommitReceipt"),
            ("CommitDecision-beta", "beta", "LocalCommitReceipt"),
            ("MakeDispatchable-alpha", "E", "DispatchableReceipt"),
        ]:
            p = read(SEED / (label + ".request.wire"))["payload"]
            if label.startswith("CommitDecision"):
                p["grant_id"] = next(
                    g["grant_id"] for g in frames["Reserve-slot"]["record"]["grants"] if g["decision_id"] == n
                )
            wire(label, label, p, node=n, kind=kind)
        disp = frames["MakeDispatchable-alpha"]

        if mode == "healthy-restart":
            stop_rc, rec = restart_e(sigkill=False)
            assert rec["writer_epoch"] == "2" and rec["cut"] == disp["cut"]
            assert wire("old-dispatch", "MakeDispatchable-alpha", kind="DispatchableReceipt") == disp
            if expect == "pass":
                rel = cold_release("after-restart", kind="ReleasedExactReceipt")
                q = wire("after-query", "after-recapture-command", kind="EconomicCommand")
                assert q["receipts"] == [disp, rel]
            else:
                rel = cold_release("after-restart", error="外部接纳存在未核来源缺口")
                q = wire("after-query", "after-recapture-command", kind="EconomicCommand")
                assert q["receipts"] == [disp]
            save(OUT / "result.json", dict(mode=mode, expect=expect, stop_rc=stop_rc, result=rel["kind"], error=rel.get("error"), state=q["state"], query_cut=q["cut"]))

        elif mode == "fault-sigterm":
            pad = fill_disk()
            wire("fault-late", "capture-late", error="full")
            # 写故障发生后即使正常 SIGTERM，也不得签发 clean_handoff。
            old = processes["E"]
            old.terminate()
            old.wait(timeout=10)
            pad.unlink()
            Path(nodes["E"]["socket"]).unlink(missing_ok=True)
            r = subprocess.run(cli("E", "recover"), capture_output=True, check=True)
            rec = json.loads(r.stdout)
            epochs["E"] = rec["writer_epoch"]
            start("E")
            assert wire("old-dispatch", "MakeDispatchable-alpha", kind="DispatchableReceipt") == disp
            cold_release("blocked-after-fault-sigterm", error="外部接纳存在未核来源缺口")

            late_p = read(SEED / "capture-late.request.wire")["payload"]
            late_item = make_reconcile_item(late_p["raw_utf8"], late_p["token"], late_p["json_pointer"])
            # 陈旧 through_ns、局部单批、缺漏真实未补录原件均须拒收。
            wire("rec-stale-ns", "capture-alpha", dict(op="ReconcileCaptureContinuity", writer_epoch="2", range_start="genesis", range_end_cursor="1", through_ns="999", events=recorded_items), "rec-stale-ns", error="早于")
            wire("rec-partial", "capture-alpha", dict(op="ReconcileCaptureContinuity", writer_epoch="2", range_start="genesis", range_end_cursor="1", through_ns="1000", events=[recorded_items[0]]), "rec-partial", error="未覆盖全部")
            wire("rec-missing-late", "capture-alpha", dict(op="ReconcileCaptureContinuity", writer_epoch="2", range_start="genesis", range_end_cursor="1", through_ns="1000", events=recorded_items + [late_item]), "rec-missing-late", error="未补录")

            # 正式补录真实丢失的 capture-late -> 来源核清通过 -> 但因 late-opening 不在责任覆盖集，仍由责任界拦截。
            wire("recapture-late", "capture-late", kind="Recorded")
            assert (OUT / "fault-late.request.wire").read_bytes() == (OUT / "recapture-late.request.wire").read_bytes()
            reconciled = wire("rec-ok", "capture-alpha", dict(op="ReconcileCaptureContinuity", writer_epoch="2", range_start="genesis", range_end_cursor="1", through_ns="1012", events=recorded_items + [late_item]), "rec-ok", kind="CaptureContinuityReconciled")
            assert reconciled["source_gap_cleared"] is True
            rel_err = cold_release("blocked-by-uncovered-late", error="责任界")
            save(OUT / "result.json", dict(mode=mode, stop_rc=old.returncode, reconciled=reconciled, final=rel_err))

        elif mode == "upgrade-clean":
            stop_rc, rec = restart_e(sigkill=False, switch_to_binset=True)
            assert digest(mp.read_bytes()) == manifest_sha, "manifest must remain untouched"
            assert rec["writer_epoch"] == "2" and rec["cut"] == disp["cut"]
            assert wire("old-dispatch", "MakeDispatchable-alpha", kind="DispatchableReceipt") == disp
            # 旧库无租约不能凭空判安全：直接放行必须被拒。
            direct_err = cold_release("direct-after-upgrade", error="外部接纳存在未核来源缺口")
            # 不改原 manifest，由原绑定来源交付完整连续范围核清。
            reconciled = wire("reconcile-clean", "capture-alpha", dict(op="ReconcileCaptureContinuity", writer_epoch="2", range_start="genesis", range_end_cursor="1", through_ns="1000", events=recorded_items), "reconcile-clean", kind="CaptureContinuityReconciled")
            assert reconciled["source_gap_cleared"] is True
            rel = cold_release("released-after-reconcile", msg="cold-release-2", kind="ReleasedExactReceipt")
            q = wire("after-query", "after-recapture-command", kind="EconomicCommand")
            assert q["receipts"] == [disp, rel]
            save(OUT / "result.json", dict(mode=mode, stop_rc=stop_rc, manifest_unchanged=True, direct_error=direct_err["error"], reconciled=reconciled, released=rel["kind"], query_cut=q["cut"]))

        elif mode in {"upgrade-faulted", "upgrade-faulted-parent"}:
            pad = fill_disk()
            wire("fault-late", "capture-late", error="full")
            old = processes["E"]
            old.terminate()
            old.wait(timeout=10)
            pad.unlink()
            Path(nodes["E"]["socket"]).unlink(missing_ok=True)
            if mode == "upgrade-faulted":
                bindir = "/binset"
            r = subprocess.run(cli("E", "recover"), capture_output=True, check=True)
            rec = json.loads(r.stdout)
            epochs["E"] = rec["writer_epoch"]
            start("E")
            assert digest(mp.read_bytes()) == manifest_sha
            if mode == "upgrade-faulted-parent":
                # 对照：父头 734847be 在磁盘满丢 capture-late 后重启竟直接放行！
                rel = cold_release("parent-blind-release", kind="ReleasedExactReceipt")
                save(OUT / "result.json", dict(mode=mode, parent_blind_release=rel["kind"], cut=rel["cut"]))
            else:
                direct_err = cold_release("direct-blocked", error="外部接纳存在未核来源缺口")
                late_p = read(SEED / "capture-late.request.wire")["payload"]
                late_item = make_reconcile_item(late_p["raw_utf8"], late_p["token"], late_p["json_pointer"])
                miss_err = wire("rec-missing", "capture-alpha", dict(op="ReconcileCaptureContinuity", writer_epoch="2", range_start="genesis", range_end_cursor="1", through_ns="1000", events=recorded_items + [late_item]), "rec-missing", error="未补录")
                wire("recapture-late", "capture-late", kind="Recorded")
                reconciled = wire("rec-ok", "capture-alpha", dict(op="ReconcileCaptureContinuity", writer_epoch="2", range_start="genesis", range_end_cursor="1", through_ns="1012", events=recorded_items + [late_item]), "rec-ok", kind="CaptureContinuityReconciled")
                assert reconciled["source_gap_cleared"] is True
                final_err = cold_release("blocked-uncovered", msg="cold-release-2", error="责任界")
                save(OUT / "result.json", dict(mode=mode, manifest_unchanged=True, direct_error=direct_err["error"], miss_error=miss_err["error"], reconciled=reconciled, final_error=final_err["error"]))

        elif mode in {"future-live", "future-restart", "future-kill"}:
            stop_rc = None
            if mode != "future-live":
                stop_rc, rec = restart_e(sigkill=(mode == "future-kill"))
                assert rec["writer_epoch"] == "2" and rec["cut"] == disp["cut"]
                assert wire("old-dispatch", "MakeDispatchable-alpha", kind="DispatchableReceipt") == disp
            if expect == "pass":
                rel = cold_release("release-at-1202", kind="ReleasedExactReceipt")
                q = wire("after-query", "after-recapture-command", kind="EconomicCommand")
                assert q["receipts"] == [disp, rel]
            else:
                rel = cold_release("release-at-1202", error="未补录")
                q = wire("after-query", "after-recapture-command", kind="EconomicCommand")
                assert q["receipts"] == [disp]
            save(OUT / "result.json", dict(mode=mode, expect=expect, stop_rc=stop_rc, result=rel["kind"], error=rel.get("error"), state=q["state"], query_cut=q["cut"]))

        elif mode == "future-plus-past-gap":
            # SIGKILL 崩溃：179 的 fill 未补录必须拦下 1202；补录并核清 179 后，不补录 2000 的 fee 也必须放行 1202。
            stop_rc, rec = restart_e(sigkill=True)
            assert rec["writer_epoch"] == "2"
            blocked_past = cold_release("blocked-past-179", error="未补录")
            fact = wire("restage-fill", "capture-late", capture_body(docs[2]), "fill", kind="Recorded")
            blocked_pending = cold_release("blocked-pending-179", error="Pending")
            resolve = dict(
                op="ResolveEvidence",
                evidence_id="fill",
                covered=[{k: fact[k] for k in ("fact_key", "fact_hash", "token")}],
                frontier=dict(source_namespace="test", source_epoch="one", cursor="2"),
                dependency_version="retained-existing20",
            )
            wire("resolve-fill", "capture-late", resolve, "resolve-fill", kind="Resolved")
            # 注意：docs[3] (fee, emitted_ns=2000) 故意未补录！
            rel = cold_release("released-despite-future-2000", msg="cold-release-2", kind="ReleasedExactReceipt")
            save(OUT / "result.json", dict(mode=mode, stop_rc=stop_rc, blocked_past=blocked_past["error"], blocked_pending=blocked_pending["error"], released=rel["kind"], cut=rel["cut"]))

        elif mode in {"scoped-pending-covered", "scoped-pending-uncovered", "scoped-pending-unknown"}:
            pad = fill_disk()
            wire("fault-other", "capture-late", capture_body(docs[2]), "fill", error="full")
            old = processes["E"]
            old.kill()
            old.wait()
            pad.unlink()
            Path(nodes["E"]["socket"]).unlink(missing_ok=True)
            r = subprocess.run(cli("E", "recover"), capture_output=True, check=True)
            rec = json.loads(r.stdout)
            epochs["E"] = rec["writer_epoch"]
            start("E")
            # 未补录前，全账仍必须拦截 alpha。
            cold_release("blocked-before-recapture", error="未补录")
            # 补录非 alpha 事实，但不调用 ResolveEvidence，让其保持 Pending！
            wire("recapture-other", "capture-late", capture_body(docs[2]), "fill", kind="Recorded")
            if mode == "scoped-pending-covered":
                if expect == "pass":
                    rel = cold_release("release-alpha", kind="ReleasedExactReceipt")
                    save(OUT / "result.json", dict(mode=mode, expect=expect, result=rel["kind"], cut=rel["cut"]))
                else:
                    rel = cold_release("release-alpha", error="Pending")
                    save(OUT / "result.json", dict(mode=mode, expect=expect, result=rel["kind"], error=rel["error"]))
            elif mode == "scoped-pending-uncovered":
                rel = cold_release("release-alpha", error="责任界")
                save(OUT / "result.json", dict(mode=mode, result=rel["kind"], error=rel["error"]))
            else:
                rel = cold_release("release-alpha", error="账户范围")
                save(OUT / "result.json", dict(mode=mode, result=rel["kind"], error=rel["error"]))
        else:
            raise ValueError(f"unknown mode: {mode}")
    finally:
        for proc in processes.values():
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    mode = sys.argv[1]
    expect = sys.argv[2] if len(sys.argv) > 2 else "pass"
    run(mode, expect)
