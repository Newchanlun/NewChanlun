#!/usr/bin/env python3
"""#1407 C2：从空库通过正式 E/B/X 进程执行受控场景，保存原始请求、应答和全表业务转储。"""
import argparse
import errno
import hashlib
import json
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
from urllib.request import Request, urlopen

from history_fixture_model import model

parser = argparse.ArgumentParser(description="正式 E/B/X 和 Q 的 #1407 C2 非空工作例。输入为项目 /5 组件夹具原件，不复制数据库。")
parser.add_argument("--fixture", type=Path, required=True)
parser.add_argument("--bin", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--geckodriver", type=Path, help="在同一 HTTP 服务上用 Firefox 核验 cut 5 和 6")
parser.add_argument("--profile-root", type=Path, help="Firefox 与 geckodriver 共用的临时配置父目录")
parser.add_argument("--twice", action="store_true", help="同一路径两次从空库启动，对比 E/B/X 全表规范转储")
args = parser.parse_args()
src = Path(__file__).resolve().parents[2]
fixture, bins, run = (p.resolve() for p in (args.fixture, args.bin, args.out))
run.mkdir(mode=0o700)
if args.twice:
    # 绝对路径是冻结身份的一部分。保留第一轮目录，第二轮用同一空路径；不改写转储。
    child = [sys.executable, str(Path(__file__).resolve()), "--fixture", str(fixture),
             "--bin", str(bins), "--out", str(run / "case")]
    for name in ("a", "b"):
        browser = []
        if name == "b" and args.geckodriver:
            browser = ["--geckodriver", str(args.geckodriver)]
            if args.profile_root:
                browser += ["--profile-root", str(args.profile_root)]
        subprocess.run(child + browser, check=True)
        (run / "case").rename(run / name)
    first = (run / "a/business.json").read_bytes()
    assert first == (run / "b/business.json").read_bytes(), "两次空库的 E/B/X 全表不一致"
    print(f"PASS: 两次 E/B/X 全表转储逐字节相同，{len(first)} 字节")
    sys.exit(0)
sys.path.insert(0, str(src / "s_session"))
from s_socket_client import canonical, decode_frame, digest, validate_reply

def write(name, obj):
    p = run / name
    with p.open("xb") as f:
        f.write(canonical(obj))
    return p

def load(path):
    return decode_frame(path.read_bytes())

def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def copied(name):
    p = run / name
    shutil.copyfile(fixture / name, p)
    return p

manifest = load(fixture / "manifest.json")
assert manifest["finance"]["schema_revision"] == "tb03b-finance/5"
assert manifest["clock"]["kind"] == "TestOnly"
assert manifest["clock"]["plan"]["messages"]["ReleaseExact-alpha"]["commit_ns"] == "162"
assert "test_only_fault" not in manifest and manifest.get("protocol_revision") in (None, "economic-session/1")
sid, gen = manifest["session_id"], manifest["session_generation"]
assert (sid, gen) == ("tb03b-unit", "1")
source_fields = ("source_namespace", "source_epoch", "producer_id", "producer_epoch")
src_x = {k: manifest["authorized_sources"][1][k] for k in source_fields}
src_business = {k: manifest["authorized_sources"][0][k] for k in source_fields}
assert src_x == dict(source_namespace="x-sim", source_epoch="epoch1", producer_id="X", producer_epoch="1")
qsource = dict(source_namespace="test-query", source_epoch="fixture-1", producer_id="reader", producer_epoch="1")
manifest["authorized_sources"].append(dict(qsource, operations=["ReadView", "Watch", "QueryCommand","EconomicReadOpen","EconomicReadPage","EconomicReadClose"]))
messages = {m: "1" for m in manifest["clock"]["plan"]["messages"]}
messages["ReleaseExact-alpha"] = "2"
manifest["clock"] = dict(kind="logical-bar/1", bars=dict(init="0", messages=messages, recover=["3"]))
opener, binding = {}, {}
for authority in manifest["voice_binding"]["authorities"]:
    a = authority["authority_id"]
    assert a in ("alpha", "beta")
    bundle = load(fixture / f"{a}-authority.json")
    verification = load(fixture / f"{a}-unit-review.json")
    assert verification["scope"] == "unit trust fixture only; no independent acceptance"
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
    authority.update(bundle_path=str(bundle_path), bundle_sha256=bh,
                     verification_path=str(review_path), verification_sha256=file_digest(review_path))
    ref = bundle["bindings"][0]
    origin = ref["opening_source"]
    binding[a] = dict(op="BindVoice", binding_id=f"voice-{a}", evidence_id=a,
        carrier_ref=ref["carrier_ref"], gamma_ref=ref["gamma_ref"], parent_voice_id=None,
        sigma="Long", n="0", opening_basis={k if k != "fact_hash" else "expected_fact_hash": origin[k]
        for k in ("fact_key", "fact_hash", "allocation_id")})

data_path = copied("input.json")
assert manifest["finance"]["input_sha256"] == file_digest(data_path)
data = load(data_path)
assert data["schema_revision"] == "tb03b-finance/5" and data["kind"] == "TestOnly"
plans = {q["decision_id"]: q for q in data["plans"]}
assert list(plans) == ["alpha", "beta"] and data["policy"]["cap"] == "100"
assert data["slots"][0]["applicants"] == ["alpha", "beta"]
basis = copied("s-unit-basis-stub.json")
stub = run / "s-unit-stub.sh"
assert "'" not in str(basis)
stub.write_text(f"#!/bin/sh\nexec /bin/cat '{basis}'\n")
stub.chmod(0o700)
manifest["finance"]["input_path"] = str(data_path)
manifest["finance"]["structure"].update(binary=str(stub), binary_sha256=file_digest(stub), db=str(run / "s-unit.db"))
nodes = {"E": manifest["e"], **{f"B:{x['chong_id']}": x for x in manifest["chongs"]}}
for domain, node in nodes.items():
    name = "e" if domain == "E" else node["chong_id"]
    node.update(db=str(run / f"{name}.db"), socket=str(run / f"{name}.sock"))
path = write("manifest.json", manifest)
eb, bb, xb = [str(bins / x) for x in ("e_economic_session", "b_chong_session", "x_execution_session")]
epochs = {d: "1" for d in nodes}
lc = write("economic-launcher.json", dict(schema_revision="economic-launcher/1", manifest=str(path),
    manifest_hash=digest(manifest), python=sys.executable, e_binary=eb, b_binary=bb,
    state_root=str(run / "control"), startup_timeout_ms="15000", probe_source=qsource, expected_epochs=epochs))
qc = write("economic-query.json", dict(schema_revision="economic-query/1", manifest=str(path),
    manifest_hash=digest(manifest), query_source=qsource, producer_epoch="1", expected_epochs=epochs,
    resources=dict(max_frame_bytes="16777216", timeout_ms="10000", operation_timeout_ms="30000",
        max_reply_bytes="16777216", max_cached_bytes="16777216", max_snapshots="4", max_domains="3", max_changes="10")))

processes, owners = [], []
trace = (run / "steps.jsonl").open("x", buffering=1)
ctl_trace = (run / "commands.jsonl").open("x", buffering=1)
def command(label, args, *, expected=0):
    args = list(map(str, args))
    with (run / f"{label}.stdout").open("xb") as out, (run / f"{label}.stderr").open("xb") as err:
        if expected is None:
            p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
            processes.append((label, p))
            info = {"pid": p.pid}
        else:
            p = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=20)
            info = {"exit": p.returncode}
    ctl_trace.write(json.dumps(dict(step=label, argv=args, **info)) + "\n")
    if expected is not None:
        assert p.returncode == expected, (label, p.returncode, (run / f"{label}.stderr").read_text())
    return p

def wait_ready(p, address, label):
    limit = time.monotonic() + 10
    while time.monotonic() < limit:
        assert p.poll() is None, (label, p.returncode, (run / f"{label}.stderr").read_text())
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(1)
            try:
                s.connect(address)
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(.02)
                continue
            try:
                s.shutdown(socket.SHUT_WR)
            except OSError as exc:
                if exc.errno != errno.ENOTCONN:
                    raise
            raw = s.makefile("rb").readline()
            if raw:
                assert decode_frame(raw).get("ok") is False, (label, raw)
                (run / f"{label}.ready-wire").write_bytes(raw)
                return
    raise TimeoutError((label, address))

x_socket = str(run / "x.sock")
def wire(domain, label, request, *, expected=None):
    message = canonical(request) + b"\n"
    (run / f"{label}.request.wire").write_bytes(message)
    address = x_socket if domain == "X" else nodes[domain]["socket"]
    trace.write(json.dumps({"label": label, "domain": domain, "sent": request.get("op") or request["payload"]["op"]}) + "\n")
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
        result = validate_reply(request, result, producer=domain, producer_epoch="1")
    trace.write(json.dumps({"label":label,"kind":result.get("kind"), "state":result.get("state") or
        (result.get("record") or {}).get("state"), "cut":result.get("cut"), "error":result.get("error")}) + "\n")
    if expected is not None:
        assert result.get("kind") == expected, (label, result)
    return result

def ewire(domain, message, payload, expected=None, source=src_business):
    return wire(domain, message, dict(schema_revision="economic-session/1", session_id=sid,
        session_generation=gen, **source, message_id=message, payload_hash=digest(payload),
        causal_refs=[], payload=payload), expected=expected)

def xwire(message, op, payload, expected):
    return wire("X", message, dict(protocol="x-exact-simulation/1", op=op, payload=payload), expected=expected)

def same(left, right):
    # Compare canonical bytes; Python's equality alone conflates booleans with integers.
    return canonical(left) == canonical(right)

def business_dump(db):
    with closing(sqlite3.connect(db.as_uri()+"?mode=ro", uri=True)) as c:
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        def cell(x):
            return {"blob": x.hex()} if isinstance(x, bytes) else x
        return {n: sorted(([cell(v) for v in r] for r in c.execute('SELECT * FROM "'+n.replace('"','""')+'"')),
                          key=canonical) for n in names}

def observe():
    with closing(sqlite3.connect((run / "x.db").as_uri()+"?mode=ro", uri=True)) as c:
        accepted = c.execute("SELECT count(*) FROM x_exact_commands").fetchone()[0]
        owned = c.execute("SELECT count(*) FROM x_exact_commands WHERE execute_evidence IS NOT NULL AND state IN ('MayHaveCalled','Observed')").fetchone()[0]
        # 只计该命令在正式本地模拟场所已提交的动作；空 bar 不是调用。
        calls = sum(1 for (r,) in c.execute("SELECT request FROM x_sim_batches")
                    for change in json.loads(r)["close_changes"] if change.get("order",change)["command_id"]=="cmd-alpha")
    return dict(accepted=accepted, owned=owned, calls=calls, s=len(s_requests))

def launcher(action, domain):
    return command(f"{action}-{domain.replace(':','-')}", [sys.executable,
        src / "s_session/economic_service_control.py", action, "--config", lc, "--domain", domain])

try:
    for domain in nodes:
        launcher("start", domain)
        owners.append(domain)
    for a, raw in opener.items():
        capture = ewire("E", f"capture-{a}", dict(op="CaptureExternal", raw_utf8=raw,
            json_pointer="/events/0", token=f"token-{a}", source_event_time=None), "Recorded")
        assert capture["fact_key"] == binding[a]["opening_basis"]["fact_key"]
        assert capture["fact_hash"] == binding[a]["opening_basis"]["expected_fact_hash"]
        ewire(f"B:{a}", f"apply-{a}", dict(op="ApplyAllocation", fact_key=capture["fact_key"],
            allocation_id=f"allocation-{a}", expected_fact_hash=capture["fact_hash"]), "Applied")
        ewire(f"B:{a}", f"bind-{a}", binding[a], "VoiceBound")
    rid = data["baseline"]["responsibility_id"]
    ewire("E", f"ImportResponsibility-{rid}", dict(op="ImportResponsibility", responsibility_id=rid,
        writer_epoch="1"), "ResponsibilityImportedReceipt")
    for a, q in plans.items():
        ewire(f"B:{a}", f"PrepareDecision-{a}", dict(op="PrepareDecision", decision_id=a,
            plan_hash=digest(q), writer_epoch="1"), "PreparedReceipt")
    slot = data["slots"][0]
    reserve = ewire("E", "Reserve-slot", dict(op="Reserve", slot_id=slot["slot_id"],
        request_set_hash=digest(slot["applicants"]), writer_epoch="1"), "ReserveReceipt")
    assert reserve["record"]["state"] == "Reserved"
    grants = {g["decision_id"]: g["grant_id"] for g in reserve["record"]["grants"]}
    for a, q in plans.items():
        cm = ewire(f"B:{a}", f"CommitDecision-{a}", dict(op="CommitDecision", decision_id=a,
            plan_hash=digest(q), grant_id=grants[a], writer_epoch="1"), "LocalCommitReceipt")
        assert cm["record"]["state"] == "Committed"
    before = ewire("E", "view-before-dispatch", dict(op="ReadView", cut=None, as_known_ns=None), "EconomicView")
    q = plans["alpha"]
    disp = ewire("E", "MakeDispatchable-alpha", dict(op="MakeDispatchable", decision_id="alpha",
        plan_hash=digest(q), writer_epoch="1"), "DispatchableReceipt")
    assert disp["record"]["state"] == "Dispatchable" and disp["record"]["grant_id"] == grants["alpha"]
    x, freeze = q["exact"], data["exact_release"]
    change = dict(kind="submit", order=dict(command_id=x["command_id"], family_id=x["logical_order_family"],
        chong_id=x["chong_id"], revision=x["revision"], side=x["side"], quantity=q["quantity"],
        kind=dict(kind="limit", price=q["limit_price"]), eligibility_ref=x["eligibility_ref"],
        projection_manifest=x["projection_manifest"]))
    certificate = dict(rd11_policy=freeze["rd11_policy"], responsibility_refs=[grants["alpha"]],
        structure_dependencies=[q["s_ref"]["object_id"] + "@" + q["s_ref"]["object_hash"]],
        market_dependencies=freeze["market_dependencies"], rule_revision=freeze["rule_revision"],
        conditions=freeze["conditions"])
    cid = x["command_id"]
    release = ewire("E", "ReleaseExact-alpha", dict(op="ReleaseExact", decision_id="alpha", command_id=cid,
        plan_hash=digest(change), certificate=certificate, x_id="X", x_epoch="1", writer_epoch="1"), "ReleasedExactReceipt")
    at, record = release["cut"], release["record"]
    exact = record["command"]
    expected_command = dict(command_id=cid, logical_order_family=x["logical_order_family"], session_id=sid,
        session_generation=gen, x_id="X", x_epoch="1", first_quantity=x["first_quantity"], allocation_id=x["allocation_id"], symbol=x["symbol"], projection_kind=freeze["projection_kind"],
        change=change, plan_hash=digest(change), certificate=certificate, certificate_hash=digest(certificate))
    assert same(exact, expected_command)
    assert record["state"] == "ReleasedExact" and record["release_commit_ns"] == "2"
    assert (record["allocation_id"], record["first_quantity"]) == ("alloc-alpha", "2")
    queried = ewire("E", "QueryCommand-release-cut", dict(op="QueryCommand", command_id=cid, cut=at,
        as_known_ns=None), "EconomicCommand")
    assert queried["state"] == "ReleasedExact" and same(queried["cut"], at)
    assert same(queried["record"], record) and same(queried["receipts"], [disp, release])
    hist = ewire("E", "QueryCommand-dispatch-cut", dict(op="QueryCommand", command_id=cid, cut=disp["cut"],
        as_known_ns=None), "EconomicCommand")
    assert hist["state"] == "Dispatchable" and same(hist["cut"], disp["cut"])
    assert same(hist["record"], disp["record"]) and same(hist["receipts"], [disp])
    after = ewire("E", "view-release-cut", dict(op="ReadView", cut=at, as_known_ns=None), "EconomicView")
    liability = before["image"]["finance"]["responsibilities"]
    assert same(liability, after["image"]["finance"]["responsibilities"])
    assert sum(int(r["amount"]) for r in liability) == 90

    aq = dict(op="QueryReleasedExact", protocol="x-exact-authority/1", session_id=sid, session_generation=gen,
        authority_id="E", authority_epoch="1", command_id=cid, command_hash=digest(exact),
        command=exact, release_receipt_id=None)
    auth = ewire("E", "x-authority-" + digest(aq), aq, source=src_x)
    assert auth["state"] == "ReleasedExact" and auth["receipt_id"] == release["receipt_key"]
    assert auth["commit_ns"] == "2" and same(auth["command"], exact)
    assert auth["command_hash"] == record["command_hash"] == digest(exact)

    model_config = {**model(), "symbol":"alpha"}
    pp = write("x-profile.json", dict(profile_revision="x-execution-profile/2", mode="simulation",
        credential_scope=dict(env="UNUSED_SIMULATION_CREDENTIAL"), history_simulation=dict(model=model_config,
            session_id=sid, session_generation=gen, x_id="X", source_namespace=src_x["source_namespace"],
            source_epoch=src_x["source_epoch"], socket=x_socket, timeout_ms=5000, max_frame_bytes=1048576,
            conditions=freeze["conditions"], e=dict(socket=nodes["E"]["socket"], authority_id="E", authority_epoch="1",
                schema_revision="economic-session/1", reply_namespace="economic-session/replies", producer_id=f"E:{sid}"),
            s=dict(socket=str(run / "s.sock"), authority_id="S", authority_epoch="1",
                schema_revision="s-authority-fixture/1", reply_namespace="s-authority-fixture/replies", producer_id="S:fixture"))))
    xp = command("serve-x", [xb, "serve", "--db", run / "x.db", "--profile", pp, "--writer-epoch", "1"], expected=None)
    wait_ready(xp, x_socket, "serve-x")
    s_requests = []
    def sign_once(listener):
        with listener, listener.accept()[0] as sock:
            frame = decode_frame(sock.makefile("rb").readline(1048577))
            q = frame["payload"]
            assert q["op"] == "RequestConditionalExecution" and same(q["command"], exact)
            assert q["release_receipt_id"] == release["receipt_key"] and q["command_hash"] == digest(exact)
            from s_socket_client import reply_envelope
            receipt = {k:v for k,v in q.items() if k != "op"}
            receipt.update(state="ExecuteCommitted", receipt_id=x["eligibility_ref"], commit_ns="2")
            response = reply_envelope(frame, receipt, session_id=sid, session_generation=gen, namespace="s-authority-fixture/replies",
                                      producer_id="S:fixture", producer_epoch="1")
            write("S-eligibility.request.json", frame)
            write("S-eligibility.reply.json", response)
            s_requests.append(q)
            sock.sendall(canonical(response)+b"\n")

    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(run / "s.sock"))
    listener.listen(1)
    signer = threading.Thread(target=sign_once, args=(listener,), daemon=True)
    signer.start()
    def bar(i, changes=()):
        return dict(request_id=f"b{i}", known_frontier_cut=f"frontier{i}",
            bar=dict(index=i, open=14, low=13, high=15, close=14),
            capacity=dict(kind="none"), close_changes=list(changes), scenario_busts=[])
    def advance(i, changes=()):
        return xwire(f"x-bar-{i}", "AdvanceBar", bar(i, changes), "SimulationBatch")
    advance(0)
    dbs = {d: Path(n["db"]) for d,n in nodes.items()}
    dbs["X"] = run / "x.db"
    baseline = {d: business_dump(p) for d,p in dbs.items()}
    early = xwire("early", "AcceptExact", exact, "Error")
    assert early["error"].startswith("InvalidDomain：X 接纳时钟早于 E 持久交付")
    assert xwire("query-early","QueryCommand",cid,"ExactCommandState")["state"] == "NoRecord"
    assert all(same(baseline[d], business_dump(p)) for d,p in dbs.items())
    counts = {"early":observe()}
    assert counts["early"] == dict(accepted=0, owned=0, calls=0, s=0)
    advance(1)
    accepted = xwire("retry", "AcceptExact", exact, "ExactCommandState")
    assert (run / "retry.request.wire").read_bytes() == (run / "early.request.wire").read_bytes()
    assert accepted["state"] == "Accepted" and accepted["x_accept"] == dict(received_ns="2", first_known_ns="2", commit_ns="2")
    assert accepted["causal_refs"] == [dict(authority_id="E",authority_epoch="1",receipt_id=release["receipt_key"],
        command_hash=record["command_hash"],release_commit_ns=record["release_commit_ns"])]
    counts["accepted"] = observe()
    assert counts["accepted"] == dict(accepted=1,owned=0,calls=0,s=0)
    order = change["order"]
    local_change = {**change, "order":{**order, "revision":int(order["revision"]), "quantity":int(order["quantity"]),
        "kind":{"kind":"limit", "price":int(order["kind"]["price"])}}}
    batch2 = advance(2, [local_change])
    assert xwire("bar-2-retry","AdvanceBar",bar(2,[local_change]),"SimulationBatch") == batch2
    signer.join(2)
    counts["executed"] = observe()
    assert counts["executed"] == dict(accepted=1,owned=1,calls=1,s=1)
    filled = advance(3)
    assert [o["event"]["kind"] for o in filled["originals"]]==["fill","fee"]
    assert filled["originals"][0]["event"]["fill"]["quantity"]==2
    assert all(same(baseline[d],business_dump(dbs[d])) for d in nodes)
    write("business.json", {d: business_dump(p) for d,p in dbs.items()})

    # Q 使用既有 HTTP handler、完整来源白名单和真实 owner；只绑定环回临时端口。
    from economic_query import EconomicQuery
    from s_readonly_server import Handler, QueryHTTPServer
    resources = load(src / "s_session/tests/fixtures/tb01c/query-resources.json")
    Handler.browser_path = str(src / "s_session/browser/index.html")
    http = QueryHTTPServer(("127.0.0.1",0), Handler, str(run / "unused-structure.db"), resources, 1)
    http.economic_query = EconomicQuery(qc)
    thread = threading.Thread(target=http.serve_forever,daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{http.server_port}/api/economic/"
        for n, rec, receipts in [(1,disp,[disp]),(2,release,[disp,release])]:
            request_index=0
            def query(op,payload):
                global request_index
                request_index+=1
                frame = dict(schema_revision="economic-session/1",session_id=sid,session_generation=gen,**qsource,
                    message_id=f"http-{op}-{n}-{request_index}",causal_refs=[],payload_hash=digest(payload),payload=payload)
                raw_request = canonical(frame)
                (run / f"http-{op}-{n}-{request_index}.request.wire").write_bytes(raw_request)
                request = Request(base+op, data=raw_request, headers={"Content-Type":"application/json"})
                with urlopen(request,timeout=30) as stream:
                    raw = stream.read()
                (run / f"http-{op}-{n}-{request_index}.reply.wire").write_bytes(raw)
                return validate_reply(frame, decode_frame(raw), producer="Q", producer_epoch="1")
            from s_socket_client import read_economic_pages
            snapshot = read_economic_pages(dict(op="snapshot",cuts=None,as_known_ns=str(n),snapshot_token=None),
                lambda payload, remaining_ms:query("read",payload),session_id=sid,session_generation=gen,
                producer_id="Q:"+sid,producer_epoch="1",manifest_hash=digest(manifest),owner_epochs=epochs,
                deadline=time.monotonic()+30)
            write(f"snapshot-{n}.json",snapshot)
            assert snapshot["completeness"]=="CompleteVector", snapshot["domains"].keys()
            cuts = {d:v["cut"] for d,v in snapshot["domains"].items()}
            assert cuts["E"]==rec["cut"]
            original = query("original",dict(op="original",kind="command",object_id=cid,domain_id="E",cuts=cuts))
            assert original["cuts"]==cuts and same(original["original"]["record"],rec["record"])
            assert same(original["original"]["receipts"],receipts)
        if args.geckodriver:
            check = [sys.executable, str(src / "s_session/tests/c2_command_browser.py"),
                     "--geckodriver", str(args.geckodriver), "--run", str(run),
                     "--port", str(http.server_port)]
            if args.profile_root:
                check += ["--profile-root", str(args.profile_root)]
            subprocess.run(check, check=True, timeout=150)
    finally:
        http.shutdown()
        http.server_close()
    write("summary.json",dict(cuts=[disp["cut"],at],receipt_keys=[disp["receipt_key"],release["receipt_key"]],
        first_quantity=exact["first_quantity"],allocation_id=exact["allocation_id"],release_bar=auth["commit_ns"],
        maximum_liability=sum(int(r["amount"]) for r in liability),counts=counts))
    print("PASS: 正式 E 放行 2；X 读 1 拒绝、读 2 接纳、受控执行一次；HTTP 同 cut 原件和全部业务表已保存")
finally:
    for label, p in reversed(processes):
        if p.poll() is None:
            p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        ctl_trace.write(json.dumps(dict(step=label + "-exit", pid=p.pid, exit=p.returncode)) + "\n")

    for domain in reversed(owners):
        launcher("stop",domain)
