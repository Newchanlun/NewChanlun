"""#1375：在独占 Linux tmpfs 上，以正式 E/B socket 核冷启动、来源 EOF 和责任核清。

挂载：/seed = AC3 四臂的 recapture 原件目录，/binset = 候选五个程序，
/corpus = 仓内 s_session/tests/fixtures/tb03c，/out = 空目录。模式：legacy / sealed / uncovered。
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

ROOT, OUT, SEED = Path("/tmp/chain"), Path("/out"), Path("/seed")
P = "/events/0"


def canonical(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(b):
    return hashlib.sha256(b).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def save(path, obj):
    path.write_bytes(canonical(obj))
    return digest(path.read_bytes())


def receipt_item(doc, token):
    ev = doc["events"][0]
    src = ev["source"]
    fk = [src[x] for x in ("source_namespace", "source_epoch", "external_fact_id")]
    return dict(token=token, fact_key=digest(canonical(fk)), fact_hash=digest(canonical(dict(
        raw_sha256=digest(canonical(doc)), json_pointer=P, event=ev, units=doc["units"]))))


def sealed_fixture(m, include_fee):
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
        documents.append(dict(emitted_ns="1", raw_utf8=canonical(doc).decode(), tokens=[entry["token"]]))
        bp, rp = ROOT / f"{a}-authority.json", ROOT / f"{a}-unit-review.json"
        bundle, review = read(bp), read(rp)
        bundle["bindings"][0]["opening_source"].update(raw_sha256=raw_hash, fact_hash=entry["fact_hash"])
        artifact = next(x for x in bundle["artifacts"] if x["name"] == "opening_raw")
        artifact.update(sha256=raw_hash, bytes=str(p.stat().st_size))
        review.update(bundle_sha256=save(bp, bundle), artifacts=bundle["artifacts"])
        auth = next(x for x in m["voice_binding"]["authorities"] if x["authority_id"] == a)
        auth.update(bundle_sha256=review["bundle_sha256"], verification_sha256=save(rp, review))

    # 两条独立回报共用游标。已导入的 20 TEST-CASH 保留不降：
    # 1 单位成交的现金 14 + 已列佣金 1 + 随后交易所费用 3 = 18。
    corpus = read(Path("/corpus/raw/chong-R1.json"))
    for i, name in [(1, "fill"), (3, "fee")]:
        ev = corpus["events"][i]
        ev["source"].update(source_namespace="test", source_epoch="one", source_cursor="2")
        ev["chong_id"] = "alpha"
        if name == "fill":
            ev["known_cost_components"][0].update(amount_text="14", canonical_amount="14")
        else:
            ev["depends_on"].update(source_namespace="test", source_epoch="one", external_fact_id="R-buy")
            ev["known_cost_components"][0]["fill_ref"].update(source_namespace="test", source_epoch="one",
                external_fact_id="R-buy", allocation_id="alloc-R-buy", chong_id="alpha")
        fragments = {k: [dict(json_pointer=x["json_pointer"].replace(f"/events/{i}/", P + "/")) for x in paths]
                     for k, paths in corpus["evidence_index"]["fragments"].items()
                     if all(x["json_pointer"].startswith(f"/events/{i}/") for x in paths)}
        doc = dict(format=corpus["format"], units=corpus["units"], events=[ev],
                   evidence_index=dict(fragments=fragments))
        entry = receipt_item(doc, name)
        documents.append(dict(emitted_ns="179", raw_utf8=canonical(doc).decode(), tokens=[name]))
        if name == "fill" or include_fee:
            coverage.append(entry)
    data["baseline"]["covered_facts"] = coverage
    m["finance"]["input_sha256"] = save(ROOT / "input.json", data)
    tape = dict(format="test-only-economic-source/1", session_id=m["session_id"],
                session_generation=m["session_generation"], source=m["finance"]["coordinator_source"],
                documents=documents)
    p = ROOT / "source.json"
    m["test_only_capture_tape"] = dict(path=str(p), sha256=save(p, tape))
    m["book_revision"] = "tb03c-book/1"
    m["authorized_sources"][0]["operations"].append("ResolveEvidence")
    return documents


def run(mode):
    assert mode in {"legacy", "sealed", "uncovered"}
    assert os.listdir("/sys/class/net") == ["lo"]
    disk = Path("/ej")
    v = os.statvfs(disk)
    assert 0 < v.f_blocks * v.f_frsize <= 16 << 20 and disk.stat().st_dev != Path("/tmp").stat().st_dev
    assert not list(disk.iterdir()) and not list(OUT.iterdir())
    ROOT.mkdir()
    for pattern in ("*-authority.json", "*-unit-review.json", "*-opening_raw.json", "*-input.json",
                    "*-instrument_declaration.json", "*-controlled_gammas.json", "*-carrier_objects.json",
                    "s-unit-stub.sh", "s-unit-basis-stub.json", "input.json"):
        for f in SEED.glob(pattern):
            shutil.copyfile(f, ROOT / f.name)
    (ROOT / "s-unit-stub.sh").chmod(0o700)
    manifest = read(SEED / "manifest.json")
    docs = sealed_fixture(manifest, mode == "sealed") if mode != "legacy" else None
    clock = manifest["clock"]["plan"]["messages"]
    for name, ns in [("cold-release", 1200), ("stale-release", 1200), ("fill", 1010), ("fee", 1020),
                     ("resolve-fill", 1030), ("resolve-fee", 1040), ("bad-token", 1010), ("bad-raw", 1010)]:
        clock[name] = dict(received_ns=str(ns), first_known_ns=str(ns+1), commit_ns=str(ns+2))
    # 重送的同一 Capture 在 epoch 2 使用新接纳时钟，不改变信封。
    clock["fill"] = {k: [str(180+j), val] for j, (k, val) in enumerate(clock["fill"].items())}
    mp = ROOT / "manifest.json"
    save(mp, manifest)
    nodes = {"E": manifest["e"], **{r["chong_id"]: r for r in manifest["chongs"]}}
    processes, epochs = {}, dict.fromkeys(nodes, "1")
    frames = {}
    def cli(node, *args):
        return ["/binset/" + ("e_economic_session" if node == "E" else "b_chong_session"),
                args[0], "--manifest", str(mp), "--db", nodes[node]["db"],
                *([] if node == "E" else ["--chong", node]), *args[1:]]
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
            time.sleep(.01)
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
        (OUT / (label+".request.wire")).write_bytes(sent)
        (OUT / (label+".reply.wire")).write_bytes(received)
        reply = json.loads(received)
        assert reply["producer_epoch"] == epochs[node] and reply["payload_hash"] == digest(canonical(reply["payload"]))
        result = reply["payload"]
        if kind: assert result["kind"] == kind, (label, result)
        if error: assert result["kind"] == "Error" and error in result["error"], (label, result)
        frames[label] = result
        return result
    def capture_body(item):
        ev = json.loads(item["raw_utf8"])["events"][0]
        return dict(op="CaptureExternal", raw_utf8=item["raw_utf8"], json_pointer=P,
                    token=item["tokens"][0], source_event_time=ev["source"].get("source_event_time"))
    def cold_release(label, **checks):
        p = read(SEED / "ReleaseExact-alpha-late.request.wire")["payload"]
        p["writer_epoch"] = epochs["E"]
        return wire(label, "ReleaseExact-alpha-late", p, "cold-release", **checks)
    try:
        for n in nodes:
            subprocess.run(cli(n,"init"), check=True, stdout=subprocess.DEVNULL)
            start(n)
        for idx, a in enumerate(("alpha", "beta")):
            key = "capture-"+a
            fact = wire(key, key, capture_body(docs[idx]) if docs else None, kind="Recorded")
            for op, field, kind in [("apply-", "expected_fact_hash","Applied"), ("bind-", "opening_basis","VoiceBound")]:
                label = op+a
                body = read(SEED / (label+".request.wire"))["payload"]
                if op == "bind-": body[field]["expected_fact_hash"] = fact["fact_hash"]
                else: body[field] = fact["fact_hash"]
                wire(label, label, body, node=a, kind=kind)
        for label, n, kind in [("ImportResponsibility-existing20","E","ResponsibilityImportedReceipt"),
                ("PrepareDecision-alpha","alpha","PreparedReceipt"), ("PrepareDecision-beta","beta","PreparedReceipt"),
                ("Reserve-slot","E","ReserveReceipt"), ("CommitDecision-alpha","alpha","LocalCommitReceipt"),
                ("CommitDecision-beta","beta","LocalCommitReceipt"), ("MakeDispatchable-alpha","E","DispatchableReceipt")]:
            p = read(SEED / (label+".request.wire"))["payload"]
            if label.startswith("CommitDecision"):
                p["grant_id"] = next(g["grant_id"] for g in frames["Reserve-slot"]["record"]["grants"]
                                     if g["decision_id"] == n)
            wire(label,label,p,node=n,kind=kind)
        disp = frames["MakeDispatchable-alpha"]
        pad = disk / "only-test-padding"
        with pad.open("xb") as f:
            v = os.statvfs(disk)
            os.posix_fallocate(f.fileno(), 0, v.f_bavail*v.f_frsize)
        assert os.statvfs(disk).f_bavail == 0
        wire("fault", "capture-late", capture_body(docs[2]) if docs else None,
             "fill" if docs else None, error="full")
        # 在仍满的卷上杀掉唯一 E owner，然后才归还空间。
        old = processes["E"]
        old.kill()
        old.wait()
        pad.unlink()
        Path(nodes["E"]["socket"]).unlink()
        r = subprocess.run(cli("E","recover"), capture_output=True, check=True)
        recovered = json.loads(r.stdout)
        assert recovered["writer_epoch"] == "2" and recovered["cut"] == disp["cut"]
        save(OUT/"recovery.json", recovered)
        epochs["E"] = "2"
        start("E")
        stale = read(SEED / "ReleaseExact-alpha-late.request.wire")["payload"]
        stale["writer_epoch"] = "1"
        wire("stale-epoch-release", "ReleaseExact-alpha-late", stale, "stale-release", error="StaleWriter")
        cold_release("unresolved", error="来源")
        assert wire("held", "after-recapture-command", kind="EconomicCommand")["receipts"] == [disp]
        assert wire("old-dispatch", "MakeDispatchable-alpha", kind="DispatchableReceipt") == disp
        if docs:
            for i, name in [(2,"fill"),(3,"fee")]:
                body = capture_body(docs[i])
                if name == "fill":
                    wire("wrong-token","capture-late",dict(body,token="wrong"),"bad-token",error="token")
                    tampered = json.loads(body["raw_utf8"])
                    tampered["events"][0]["source"]["external_fact_id"] = "R-forged"
                    wire("tampered-raw","capture-late",dict(body,raw_utf8=canonical(tampered).decode()),
                         "bad-raw",error="IdentityConflict")
                fact = wire("restage-"+name, "capture-late", body, name, kind="Recorded")
                assert fact == wire("repeat-"+name, "capture-late", body, name, kind="Recorded")
                if name == "fill":
                    cold_release("still-missing-fee", error="未补录")
            assert (OUT/"fault.request.wire").read_bytes() == (OUT/"restage-fill.request.wire").read_bytes()
            if mode == "sealed":
                # 两件均已补录但尚未经 ResolveEvidence 核清，仍为 Pending，不得放行。
                cold_release("still-pending-both", error="Pending")
            for name in ("fill","fee"):
                fact = frames["restage-"+name]
                resolve = dict(op="ResolveEvidence", evidence_id=name,
                    covered=[{k:fact[k] for k in ("fact_key","fact_hash","token")}],
                    frontier=dict(source_namespace="test",source_epoch="one",cursor="2"),
                    dependency_version="retained-existing20")
                if mode == "uncovered" and name == "fee":
                    wire("uncovered-fee","capture-late",resolve,"resolve-fee",error="责任界")
                    cold_release("not-cleared",error="责任界")
                    break
                wire("resolve-"+name,"capture-late",resolve,"resolve-"+name,kind="Resolved")
                if mode == "sealed" and name == "fill":
                    # 仅核清 fill、fee 仍 Pending，不得放行。
                    cold_release("still-pending-fee", error="Pending")
            if mode == "sealed":
                released = cold_release("released",kind="ReleasedExactReceipt")
                assert int(released["cut"]["commit_seq"]) > int(disp["cut"]["commit_seq"])
                # 原来源此刻离线，原消息与命令查询仍然是历史读。
                (ROOT/"source.json").rename(ROOT/"offline.json")
                assert cold_release("redelivered",kind="ReleasedExactReceipt") == released
                q = wire("released-command","after-recapture-command",kind="EconomicCommand")
                assert q["state"] == "ReleasedExact" and q["receipts"] == [disp,released]
                # 来源继续离线，E 再换代至 epoch 3 重启，已提交收据仍可原身份与新消息重取。
                prev_e = processes["E"]
                prev_e.terminate()
                prev_e.wait(timeout=10)
                Path(nodes["E"]["socket"]).unlink()
                r3 = subprocess.run(cli("E","recover"), capture_output=True, check=True)
                rec3 = json.loads(r3.stdout)
                assert rec3["writer_epoch"] == "3" and rec3["cut"] == released["cut"]
                save(OUT/"recovery-epoch3.json", rec3)
                epochs["E"] = "3"
                start("E")
                q3 = wire("epoch3-released-command","after-recapture-command",kind="EconomicCommand")
                assert q3["state"] == "ReleasedExact" and q3["receipts"] == [disp,released]
                orig_rel = read(SEED / "ReleaseExact-alpha-late.request.wire")["payload"]
                orig_rel["writer_epoch"] = "2"
                assert wire("epoch3-redelivered","ReleaseExact-alpha-late",orig_rel,"cold-release",
                            kind="ReleasedExactReceipt") == released
                assert wire("epoch3-alias-redelivered","ReleaseExact-alpha-late",orig_rel,
                            "cold-release-epoch3-resend",kind="ReleasedExactReceipt") == released
        save(OUT/"result.json",dict(mode=mode,old_pid=old.pid,new_pid=processes["E"].pid,
            cut=disp["cut"],final=frames.get("released",frames["unresolved"])))
    finally:
        for proc in processes.values():
            if proc.poll() is None: proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    run(sys.argv[1])
