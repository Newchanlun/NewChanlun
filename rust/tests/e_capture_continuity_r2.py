"""#1375 AC3 R3 长期回归锁（Linux Docker 隔离实测）：
覆盖：
- 健康无 tape 重启（clean_handoff 保留）
- 独审独立账本 4 臂（upgrade 2/2 clean、3/2 omitted、3/3 un-recaptured 与同代 3/2 omitted）：
  禁止自报 events 清障（ReconcileCaptureContinuity 拒收），无独立持久来源锁在 Dispatchable(cut-5)
- 写失败后 SIGTERM 禁发交接
- 放行时刻结束界与从核到用重核（1202 放行 alpha 后推进到 2102 仍实时拦下 2000，补录并核清后放行 beta）
- 责任界分级（已知且充分覆盖无关重 Pending 不停摆全账；未覆盖/未知范围 account:* 仍保守全域拦截）。
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


def build_sealed_fixture(m, extras, allow_beta_exact=False):
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
    if allow_beta_exact:
        mc = data["exact_release"]["model_coverage"]
        mc["input_domain"].append(
            dict(allocation_model="#1349/atomic-slot-wait/v1", concurrency="batched", order_kind="limit")
        )
        mc["unsupported_domains"] = [
            dict(allocation_model="#1349/atomic-slot-wait/v1", concurrency="batched", order_kind="market")
        ]
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
    elif mode == "advance-after-check":
        docs = build_sealed_fixture(
            manifest,
            [
                ("fill", "alpha", 179, True, "2", "R-buy", False),
                ("fill-beta", "beta", 2000, True, "3", "R-beta-late", False),
            ],
            allow_beta_exact=True,
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
        ("MakeDispatchable-beta", 2050),
        ("beta-release-1", 2100),
        ("fill-beta", 2120),
        ("beta-release-2", 2150),
        ("resolve-fill-beta", 2170),
        ("beta-release-3", 2200),
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
    bindir = "/parent" if mode in {"upgrade-clean", "upgrade-faulted", "upgrade-faulted-parent", "ledger-clean", "ledger-omitted", "ledger-complete"} else "/binset"

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

        elif mode in {"ledger-clean", "ledger-omitted", "ledger-complete", "ledger-r2-omitted"}:
            # 复用独审独立账本逻辑：2/2 clean、3/2 omitted（升级及同代）与 3/3 un-recaptured
            # 在 R3 下全部拒收自报 ReconcileCaptureContinuity，并将 alpha 锁在 Dispatchable(cut-5)。
            late_p = read(SEED / "capture-late.request.wire")["payload"]
            late = make_reconcile_item(late_p["raw_utf8"], late_p["token"], late_p["json_pointer"])
            complete = recorded_items + ([] if mode == "ledger-clean" else [late])
            save(OUT / "independent-ledger.json", complete)
            if mode != "ledger-clean":
                pad = fill_disk()
                wire("fault-late", "capture-late", error="full")
                pad.unlink()
            switch = mode != "ledger-r2-omitted"
            stop_rc, recovered = restart_e(switch_to_binset=switch)
            assert digest(mp.read_bytes()) == manifest_sha, "manifest must remain untouched"
            assert recovered["cut"] == disp["cut"] and recovered["writer_epoch"] == "2"
            assert wire("old-dispatch", "MakeDispatchable-alpha", kind="DispatchableReceipt") == disp
            q0 = wire("before-query", "after-recapture-command", kind="EconomicCommand")
            assert q0["state"] == "Dispatchable" and q0["receipts"] == [disp]
            before_err = cold_release("before-reconcile", error="缺少独立持久原件与可证结束界")
            report = complete if mode == "ledger-complete" else recorded_items
            payload = dict(
                op="ReconcileCaptureContinuity",
                writer_epoch="2",
                range_start="genesis",
                range_end_cursor=str(max(int(r["source_cursor"]) for r in complete)),
                through_ns="1000",
                events=report,
            )
            reconcile_err = wire(
                "reconcile",
                "capture-alpha",
                payload,
                "reconcile-clean",
                error="未获准",
            )
            after_err = cold_release("after-reconcile", msg="cold-release-2", error="缺少独立持久原件与可证结束界")
            q = wire("after-query", "after-recapture-command", kind="EconomicCommand")
            assert q["state"] == "Dispatchable" and q["receipts"] == [disp] and q["cut"] == disp["cut"]
            save(
                OUT / "result.json",
                dict(
                    mode=mode,
                    stop_rc=stop_rc,
                    manifest_unchanged=True,
                    start_cut=q0["cut"],
                    end_cut=q["cut"],
                    ledger_count=len(complete),
                    reported_count=len(report),
                    before_error=before_err["error"],
                    reconcile_error=reconcile_err["error"],
                    after_error=after_err["error"],
                    state=q["state"],
                ),
            )

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
            blocked_direct = cold_release("blocked-after-fault-sigterm", error="缺少独立持久原件与可证结束界")
            reconcile_err = wire(
                "rec-self-attest",
                "capture-alpha",
                dict(op="ReconcileCaptureContinuity", writer_epoch="2", range_start="genesis", range_end_cursor="1", through_ns="1000", events=recorded_items),
                "rec-self-attest",
                error="未获准",
            )
            # 即使正式补录 capture-late，无独立持久来源仍不得放行新风险。
            wire("recapture-late", "capture-late", kind="Recorded")
            assert (OUT / "fault-late.request.wire").read_bytes() == (OUT / "recapture-late.request.wire").read_bytes()
            rel_err = cold_release("blocked-after-recapture", msg="cold-release-2", error="责任界")
            q = wire("after-query", "after-recapture-command", kind="EconomicCommand")
            assert q["state"] == "Dispatchable" and q["receipts"] == [disp]
            save(OUT / "result.json", dict(mode=mode, stop_rc=old.returncode, blocked_direct=blocked_direct["error"], reconcile_error=reconcile_err["error"], final=rel_err["error"], state=q["state"], cut=q["cut"]))

        elif mode == "upgrade-faulted-parent":
            pad = fill_disk()
            wire("fault-late", "capture-late", error="full")
            old = processes["E"]
            old.terminate()
            old.wait(timeout=10)
            pad.unlink()
            Path(nodes["E"]["socket"]).unlink(missing_ok=True)
            r = subprocess.run(cli("E", "recover"), capture_output=True, check=True)
            rec = json.loads(r.stdout)
            epochs["E"] = rec["writer_epoch"]
            start("E")
            assert digest(mp.read_bytes()) == manifest_sha
            # 对照：父头 734847be 在磁盘满丢 capture-late 后重启竟直接放行！
            rel = cold_release("parent-blind-release", kind="ReleasedExactReceipt")
            save(OUT / "result.json", dict(mode=mode, parent_blind_release=rel["kind"], cut=rel["cut"]))

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

        elif mode == "advance-after-check":
            # 有区分力覆盖：1202 核过放行 alpha 后，前沿推进到 2102（跨过 2000 的 beta 成交）立即拦截，
            # 证明没有核清布尔位；补录后因 Pending 仍拦，Resolve 后才真实放出第二张 ReleasedExactReceipt。
            stop_rc, rec = restart_e(sigkill=True)
            assert rec["writer_epoch"] == "2"
            blocked_past = cold_release("blocked-past-179", error="未补录")
            fact1 = wire("restage-fill-alpha", "capture-late", capture_body(docs[2]), "fill", kind="Recorded")
            blocked_pending1 = cold_release("blocked-pending-179", error="Pending")
            wire(
                "resolve-fill-alpha",
                "capture-late",
                dict(
                    op="ResolveEvidence",
                    evidence_id="fill",
                    covered=[{k: fact1[k] for k in ("fact_key", "fact_hash", "token")}],
                    frontier=dict(source_namespace="test", source_epoch="one", cursor="2"),
                    dependency_version="retained-existing20",
                ),
                "resolve-fill",
                kind="Resolved",
            )
            rel_alpha = cold_release("release-alpha-at-1202", msg="cold-release-2", kind="ReleasedExactReceipt")
            # 现在推进到 beta，commit_ns=2102 跨过 emitted_ns=2000 的 docs[3]
            beta_plan_hash = frames["CommitDecision-beta"]["record"]["local_commit_receipt"]["plan_hash"]
            beta_grant_id = frames["CommitDecision-beta"]["record"]["local_commit_receipt"]["grant_id"]
            disp_beta = wire(
                "MakeDispatchable-beta",
                "MakeDispatchable-alpha",
                dict(op="MakeDispatchable", decision_id="beta", plan_hash=beta_plan_hash, writer_epoch=epochs["E"]),
                "MakeDispatchable-beta",
                kind="DispatchableReceipt",
            )
            beta_plan = frames["CommitDecision-beta"]["record"]["prepared"]["plan"]
            bx = beta_plan["exact"]
            beta_change = dict(
                kind="submit",
                order=dict(
                    command_id=bx["command_id"],
                    family_id=bx["logical_order_family"],
                    chong_id=bx["chong_id"],
                    revision=int(bx["revision"]),
                    side=bx["side"],
                    quantity=int(beta_plan["quantity"]),
                    kind=dict(kind="limit", price=int(beta_plan["limit_price"])),
                    eligibility_ref=bx["eligibility_ref"],
                    projection_manifest=bx["projection_manifest"],
                ),
            )
            rel_beta_payload = read(SEED / "ReleaseExact-alpha-late.request.wire")["payload"]
            rel_beta_payload["decision_id"] = "beta"
            rel_beta_payload["command_id"] = "cmd-beta"
            rel_beta_payload["plan_hash"] = digest(canonical(beta_change))
            rel_beta_payload["writer_epoch"] = epochs["E"]
            rel_beta_payload["certificate"]["responsibility_refs"] = [beta_grant_id]
            blocked_advance = wire("beta-blocked-at-2102", "ReleaseExact-alpha-late", rel_beta_payload, "beta-release-1", error="未补录")
            fact2 = wire("restage-fill-beta", "capture-late", capture_body(docs[3]), "fill-beta", kind="Recorded")
            blocked_pending2 = wire("beta-blocked-pending-2152", "ReleaseExact-alpha-late", rel_beta_payload, "beta-release-2", error="Pending")
            wire(
                "resolve-fill-beta",
                "capture-late",
                dict(
                    op="ResolveEvidence",
                    evidence_id="fill-beta",
                    covered=[{k: fact2[k] for k in ("fact_key", "fact_hash", "token")}],
                    frontier=dict(source_namespace="test", source_epoch="one", cursor="3"),
                    dependency_version="retained-existing20",
                ),
                "resolve-fill-beta",
                kind="Resolved",
            )
            rel_beta = wire("release-beta-at-2202", "ReleaseExact-alpha-late", rel_beta_payload, "beta-release-3", kind="ReleasedExactReceipt")
            save(
                OUT / "result.json",
                dict(
                    mode=mode,
                    stop_rc=stop_rc,
                    blocked_past=blocked_past["error"],
                    blocked_pending1=blocked_pending1["error"],
                    alpha_release_cut=rel_alpha["cut"],
                    blocked_advance=blocked_advance["error"],
                    blocked_pending2=blocked_pending2["error"],
                    beta_release_cut=rel_beta["cut"],
                    beta_receipt_id=rel_beta["receipt_key"],
                ),
            )

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
