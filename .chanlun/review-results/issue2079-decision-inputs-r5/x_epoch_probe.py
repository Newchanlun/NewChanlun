"""True E and simulation X binaries at b9d898dc; no command released and no venue."""
from contextlib import contextmanager
import os
import tempfile
from x_helpers import BIN, ROOT, CONDITIONS, canonical, command, connect_probe, model, request, order, SIM, subprocess, time, json

E = BIN.with_name("e_economic_session")

@contextmanager
def server(argv, endpoint, logpath):
    with logpath.open("wb") as log:
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 10
            while connect_probe(endpoint) is None:
                assert child.poll() is None and time.monotonic() < deadline, logpath.read_text()
                time.sleep(.02)
            yield child
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(5)
            print(endpoint.name, "exit", child.returncode, logpath.read_text().strip(), flush=True)

with tempfile.TemporaryDirectory(prefix="p2129-", dir=str(ROOT)) as d:
    from pathlib import Path
    w=Path(d)
    ep=w/"e.sock"; xp=w/"x.sock"; db=w/"e.db"
    mp=w/"economic.json"; pp=w/"profile.json"
    src=dict(source_namespace="x-sim", source_epoch="1", producer_id="X", producer_epoch="1",
        operations=["ReadView"])
    config=dict(schema_revision="economic-manifest/1", session_id="session", session_generation="1",
        e={"db":str(db),"socket":str(ep)}, chongs=[dict(chong_id="ch-test",symbol="TEST",
            operation_level="1",fixed_q="10",db=str(w/"b.db"),socket=str(w/"b.sock"))],
        authorized_sources=[src], resources=dict(max_frame_bytes="1048576", read_timeout_ms="1000",
            write_timeout_ms="1000", response_timeout_ms="3000", queue_capacity="2", max_connections="2"),
        clock=dict(kind="TestOnly",plan=dict(init_ns="1",recover_ns=["10"],messages={})))
    mp.write_text(canonical(config))
    sim=dict(model=model(),session_id="session",session_generation="1",x_id="X",
        source_namespace="x-sim",source_epoch="1",socket=str(xp),
        e=dict(socket=str(ep),authority_id="E",authority_epoch="1",schema_revision="economic-session/1",
            reply_namespace="economic-session/replies",producer_id="E:session"),
        s=dict(socket=str(w/"s.sock"),authority_id="S",authority_epoch="1",schema_revision="s-session/3",
            reply_namespace="s-session/replies",producer_id="S:session"),
        conditions=CONDITIONS, timeout_ms=5000,max_frame_bytes=1048576)
    SIM.update(sim)
    pp.write_text(canonical(dict(profile_revision="x-execution-profile/1",mode="simulation",
        credential_scope=dict(env="UNUSED_SIMULATION_CREDENTIAL"),history_simulation=sim)))
    args=["--manifest",str(mp),"--db",str(db)]
    def ecli(op):
        result=subprocess.run([E,op,*args],capture_output=True,text=True,timeout=10)
        assert result.returncode == 0,(result.returncode,result.stderr)
        return json.loads(result.stdout)
    print("init",ecli("init")["writer_epoch"],flush=True)
    c=command(dict(kind="submit",order=order("probe")))
    c["session_generation"]="1"
    with server([BIN,"serve","--db",w/"x.db","--profile",pp,"--writer-epoch","1"],xp,w/"x.log") as x:
        with server([E,"serve",*args,"--epoch","1"],ep,w/"e1.log"):
            same=request(xp,"AcceptExact",c)
            print("E=1, same X",x.pid,same,flush=True)
            assert same["error"].startswith("MissingDependency：权威拒绝："),same
        assert json.loads(pp.read_text())["history_simulation"]["e"]["authority_epoch"] == "1"
        ep.rename(w/"e.old")
        rec=ecli("recover")
        print("formal recovery",rec["kind"],rec["writer_epoch"],flush=True)
        assert rec["writer_epoch"]=="2"
        with server([E,"serve",*args,"--epoch","2"],ep,w/"e2.log"):
            after=request(xp,"AcceptExact",c)
            print("E=2, same X",x.pid,after,flush=True)
            assert after=={"kind":"Error","error":"IdentityConflict：权威回复信封的身份/epoch/因果/规范字节不符"},after
            q=request(xp,"QueryCommand","probe")
            print("X state",q,flush=True)
            assert q["state"]=="NoRecord"
