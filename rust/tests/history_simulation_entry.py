#!/usr/bin/env python3
"""#1381: 真实 X binary + 明确受控 E/S authority；非真实 producer/财务闭环。

本文件是 X 接口的故障注入夹具（E/S 回错、帧界、回复丢失等），受控 E 只为能注入真 E 不会产生的错误回复。
真 E 放行 → X 接纳 → S → X 占有的端到端链与 #1621 对拍在 economic_session 的 exact_x_e2e_tests.rs（#1407 C2）。
"""
import copy, errno, hashlib, json, os, socket, sqlite3, subprocess, sys, tempfile, threading, time
from pathlib import Path
BIN=Path(sys.argv[1]).resolve()
ROOT=Path(sys.argv[2]).resolve(); ROOT.mkdir(parents=True,exist_ok=True)
def canonical(x): return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(x): return hashlib.sha256(canonical(x).encode()).hexdigest()
# logical-bar/1: the open bar index X has reached (last committed bar + 1), the only clock E/S may report.
CLOCK={'bar':0}
# #1407 C2：x-exact-authority/1 走 IC:9 共同信封；回复须等于由原请求重建的 reply_envelope。
SIM={}
def x_envelope(role,payload,epoch=1):
    a=SIM[role]; h=digest(payload)
    return dict(schema_revision=a['schema_revision'],session_id=SIM['session_id'],session_generation=SIM['session_generation'],source_namespace=SIM['source_namespace'],source_epoch=SIM['source_epoch'],message_id='x-authority-'+h,producer_id=SIM['x_id'],producer_epoch=str(epoch),payload_hash=h,causal_refs=[],payload=payload)
def reply_envelope(request,payload,a):
    h=digest(payload); mid='reply-'+digest([request['source_namespace'],request['source_epoch'],request['message_id'],h])
    return dict(schema_revision=a['schema_revision'],session_id=request['session_id'],session_generation=request['session_generation'],source_namespace=a['reply_namespace'],source_epoch=a['authority_epoch'],message_id=mid,producer_id=a['producer_id'],producer_epoch=a['authority_epoch'],payload_hash=h,causal_refs=[{k:request[k] for k in ['source_namespace','source_epoch','message_id','payload_hash']}],payload=payload)
def connect_probe(path):
    # Readiness is a listening socket, not a file: bind() creates the path before listen(), and a connect in
    # between is refused (measured on Belay: refused, then connectable 10ms later with X alive). One successful
    # connect is the portable test (Linux and macOS alike). Returns None while not listening, otherwise what the
    # peer wrote before closing. Only X is probed: session_transport reads EOF on the empty connection in its I/O
    # thread, answers its own {"ok":false,...} and closes, without queueing a job for the handler or touching the
    # store. The controlled E/S below treat every connection as a request and are never probed (they listen
    # before their thread starts).
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(5)
        try: s.connect(str(path))
        except (FileNotFoundError,ConnectionRefusedError): return None
        try: s.shutdown(socket.SHUT_WR)
        except OSError as e:
            if e.errno!=errno.ENOTCONN: raise
        return s.makefile('rb').read()
def listening(path): return connect_probe(path) is not None
def check_listening_predicate():
    with tempfile.TemporaryDirectory(prefix='i1381p-') as root:
        bound=Path(root)/'bound-only'; ready=Path(root)/'ready'
        with socket.socket(socket.AF_UNIX) as b, socket.socket(socket.AF_UNIX) as r:
            assert not listening(bound), 'a missing socket is not ready'
            b.bind(str(bound)); r.bind(str(ready))
            assert bound.exists() and not listening(bound), 'a bound but not listening socket is not ready'
            assert ready.exists() and not listening(ready)
            r.listen(2)
            def serve_eof():
                with r.accept()[0] as c:
                    assert c.recv(1)==b''
                    c.sendall(b'{"ok":false}\n')
            t=threading.Thread(target=serve_eof,daemon=True); t.start()
            assert connect_probe(ready)==b'{"ok":false}\n'
            t.join(5); assert not t.is_alive()
            def serve_fast_close():
                r.accept()[0].close()
            t2=threading.Thread(target=serve_fast_close,daemon=True); t2.start()
            assert connect_probe(ready)==b''
            t2.join(5); assert not t2.is_alive()
        assert ready.exists() and not listening(ready), 'a closed stale socket file is not ready'
    assert not Path(root).exists()
def request(path,op,payload):
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(5); s.connect(str(path)); s.sendall((canonical({'protocol':'x-exact-simulation/1','op':op,'payload':payload})+'\n').encode())
        s.shutdown(socket.SHUT_WR)
        r=json.loads(s.makefile('rb').readline())
    if r.get('kind')=='SimulationBatch': CLOCK['bar']=max(CLOCK['bar'],r['bar_index']+1)
    return r
class Authority:
    def __init__(self,path,role):
        self.path=path; self.role=role; self.calls=[]; self.bad=None; self.records={}; self.authorizations={}; self.drop_after=None; self.swallow=None; self.compact={}; self.replies=[]; self.frames=[]
        self.sock=socket.socket(socket.AF_UNIX); self.sock.bind(str(path)); self.sock.listen(16)
        self.thread=threading.Thread(target=self.run,daemon=True); self.thread.start()
    def run(self):
        while True:
            try: c,_=self.sock.accept()
            except OSError: return
            with c:
                envelope=json.loads(c.makefile('rb').readline()); q=envelope['payload']; self.calls.append(q)
                r={k:q[k] for k in ['protocol','session_id','session_generation','authority_id','authority_epoch','command_id','command_hash','command']}
                r.update(state='ReleasedExact' if self.role=='E' else 'ExecuteCommitted',receipt_id=self.role+':'+q['command_id'],release_receipt_id=q['release_receipt_id'],commit_ns=CLOCK['bar'])
                if q['command_id'] in self.compact:
                    r['receipt_id']=self.compact[q['command_id']]; r.pop('release_receipt_id')
                if self.role=='S':
                    key=q['command_id']
                    if key==self.swallow and q['op']=='RequestConditionalExecution': continue
                    if q['op']=='RequestConditionalExecution':
                        assert key not in self.records, 'X tried to authorize twice'
                        self.records[key]=copy.deepcopy(r); self.authorizations[key]=self.authorizations.get(key,0)+1
                    elif q['op']=='QueryExecuteCommitted':
                        r=copy.deepcopy(self.records.get(key,r)); r['state']='ExecuteCommitted' if key in self.records else 'NoRecord'
                    else: raise AssertionError(q['op'])
                    if key==self.drop_after: continue
                if self.bad=='denied': r['state']='Denied'
                if self.bad=='identity': r['authority_epoch']='wrong'
                if self.bad=='content': r['command']['symbol']='wrong'
                if self.bad=='future': r['commit_ns']=9_000_000_000_000_000_000
                if self.bad=='missing': r['state']='NoRecord'
                reply=reply_envelope(envelope,r,SIM[self.role.lower()])
                self.replies.append(reply); c.sendall((canonical(reply)+'\n').encode())
def model():
    return dict(model_id='history-sim/bar-batch-known-frontier/1',revision='oracle-1',symbol='TEST',quantity_unit='TEST-UNIT',currency='TEST-CASH',tick_value=1,rd11_policy='controlled-fixture-rd11',rd12_policy='per-leg-source-attribution/1',projection_kind='per_leg',seed='none',fee_profile=dict(reference='controlled-fee/1',role_source='controlled-role-map/1',limit_role='maker',market_role='taker',maker=dict(numerator=1,denominator=100,rounding='ceiling'),taker=dict(numerator=2,denominator=100,rounding='ceiling'),market_slippage_ticks=1,market_slippage_source='controlled-oracle/1'))
def order(name,side='buy',quantity=100,price=100):
    return dict(command_id=name,family_id='f-'+name,chong_id='ch-'+name,revision=1,side=side,quantity=quantity,kind=dict(kind='limit',price=price),eligibility_ref='S:'+name,projection_manifest='controlled-projection-'+name)
# The approved list frozen in both E's exact_release and X's profile (#1407 C2 item 1), model_coverage included.
CONDITIONS=[dict(condition_id=cid,authority_revision=cap,dependency_set=['controlled-dependency'],invalidation_sources=['controlled-invalidation'],required_check_stages=[stage],evidence_refs=['controlled-evidence'],coverage_proof='controlled-coverage',validator_capability=cap,failure_result='Denied') for cid,cap,stage in [('released-exact/1','released-exact/1','E.ReleaseExact'),('execute-committed/1','execute-committed/1','S.RequestConditionalExecution'),('simulation-local-transaction/1','simulation-local-transaction/1','X.OwnAttemptAndCall'),('model_coverage','model-coverage/1','E.ReleaseExact')]]
def command(change):
    o=change.get('order',change); cid=o['command_id']; family=o['family_id']
    cert=dict(rd11_policy='controlled-fixture-rd11',responsibility_refs=['controlled-responsibility'],structure_dependencies=['controlled-structure'],market_dependencies=['controlled-market'],rule_revision='controlled-rule',conditions=copy.deepcopy(CONDITIONS))
    return dict(command_id=cid,logical_order_family=family,session_id='session',session_generation='g1',x_id='X',x_epoch=1,symbol='TEST',projection_kind='per_leg',change=change,plan_hash=digest(change),certificate_hash=digest(cert),certificate=cert)
def batch(i,changes=[]):
    return dict(request_id='b'+str(i),known_frontier_cut='frontier'+str(i),bar=dict(index=i,open=100,low=90,high=110,close=105),capacity=dict(kind='none'),close_changes=changes,scenario_busts=[])
def run(name):
    directory=ROOT/f'{name}-{os.getpid()}-{time.time_ns()}'; directory.mkdir()
    # Unix socket path stays below sockaddr_un limit; data remains under task root.
    # Same socket paths for both runs: they are frozen in authority_profile, which the full-table comparison covers.
    CLOCK['bar']=0; sockets=Path(tempfile.gettempdir())/('i1381-'+str(os.getpid())); sockets.mkdir()
    e=Authority(sockets/'e','E'); s=Authority(sockets/'s','S'); xp=sockets/'x'
    # S's long schema_revision keeps every S request larger than the matching E reply (oversized-frame case below).
    sim=dict(model=model(),session_id='session',session_generation='g1',x_id='X',source_namespace='x-sim',source_epoch='epoch1',socket=str(xp),e=dict(socket=str(e.path),authority_id='E',authority_epoch='e1',schema_revision='e-authority-fixture/1',reply_namespace='e/replies',producer_id='E:session'),s=dict(socket=str(s.path),authority_id='S',authority_epoch='s1',schema_revision='s-authority-fixture/1#'+'s'*512,reply_namespace='s/replies',producer_id='S:session'),conditions=CONDITIONS,timeout_ms=500,max_frame_bytes=262144)
    SIM.clear(); SIM.update(sim)
    profile=dict(profile_revision='x-execution-profile/1',mode='simulation',credential_scope=dict(env='UNUSED_SIMULATION_CREDENTIAL'),history_simulation=sim)
    pp=directory/'profile.json'; pp.write_text(canonical(profile)); db=directory/'x.sqlite'
    log=open(directory/'x.log','ab')
    fixture=len(sys.argv)>3 and sys.argv[3]=='runtime-fixture'
    def argv(epoch=1):
        return [str(BIN),'--exact','history_simulation::tests::runtime_process_fixture','--nocapture'] if fixture else [str(BIN),'serve','--db',str(db),'--profile',str(pp),'--writer-epoch',str(epoch)]
    def env(crash=None,epoch=1):
        e=dict(os.environ,ISSUE1381_FIXTURE_DB=str(db),ISSUE1381_FIXTURE_PROFILE=str(pp),ISSUE1381_FIXTURE_EPOCH=str(epoch))
        if crash: e['ISSUE1381_TEST_CRASH_AFTER_CLAIM']=crash
        return e
    def start(crash=None,epoch=1,slow_claim=False):
        e=env(crash,epoch)
        if slow_claim: e['ISSUE1381_TEST_SLOW_CLAIM']='1'
        p=subprocess.Popen(argv(epoch),env=e,stdout=log,stderr=log)
        deadline=time.monotonic()+8
        while (refusal:=connect_probe(xp)) is None:
            assert p.poll() is None, (directory/'x.log').read_text()
            assert time.monotonic()<deadline, 'X socket timeout'
            time.sleep(.02)
        # The probe ended at the transport: it never became a request to X's handler.
        assert json.loads(refusal).get('ok') is False, refusal
        return p
    def reject_new_epoch(p,crash=None):
        if p.poll() is None: p.kill(); p.wait(5)
        xp.unlink(missing_ok=True)
        with sqlite3.connect(db) as c:
            before=c.execute("select id,command,state,attempt_batch,execute_evidence from x_exact_commands order by id").fetchall()
            pending=c.execute("select k,v from x_sim_meta where k in ('pending_batch','pending_epoch') order by k").fetchall()
        blocked=subprocess.run(argv(2),env=env(epoch=2),capture_output=True,timeout=5)
        assert blocked.returncode!=0 and b'PendingBatch' in blocked.stderr,(blocked.stdout,blocked.stderr)
        with sqlite3.connect(db) as c:
            assert c.execute("select id,command,state,attempt_batch,execute_evidence from x_exact_commands order by id").fetchall()==before
            assert c.execute("select k,v from x_sim_meta where k in ('pending_batch','pending_epoch') order by k").fetchall()==pending
            if not fixture: assert c.execute("select value from x_meta where key='writer_epoch'").fetchone()==('1',)
        return start(crash)
    main_db=db
    if fixture:
        # Test-only process exits immediately before/after the real initialization transaction commit.
        for phase,code in [('before',44),('after',45)]:
            db=directory/('init-'+phase+'.sqlite'); init_env=env(); init_env['ISSUE1381_TEST_INIT_INTERRUPT']=phase
            interrupted=subprocess.run(argv(),env=init_env,capture_output=True,timeout=5)
            assert interrupted.returncode==code,(phase,interrupted.stdout,interrupted.stderr)
            with sqlite3.connect(db) as c:
                tables={row[0] for row in c.execute("select name from sqlite_master where type='table'")}
                if phase=='before': assert not any(t.startswith('x_sim_') or t=='x_exact_commands' for t in tables)
                else:
                    assert {'x_sim_meta','x_sim_batches','x_sim_originals','x_sim_busts','x_exact_commands'}<=tables
                    assert json.loads(c.execute("select v from x_sim_meta where k='authority_profile'").fetchone()[0])==sim
            recovered=start()
            try: assert request(xp,'QueryCommand','never-submitted')['state']=='NoRecord'
            finally: recovered.terminate(); recovered.wait(5); xp.unlink(missing_ok=True)
        db=main_db
    else:
        # Abort the launcher metadata write after simulation initialization; both belong to one transaction.
        with sqlite3.connect(db) as c:
            c.execute('CREATE TABLE x_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            c.execute("CREATE TRIGGER issue1381_init_abort BEFORE INSERT ON x_meta WHEN NEW.key='writer_epoch' BEGIN SELECT RAISE(ABORT,'controlled init fault'); END")
        interrupted=subprocess.run(argv(),env=env(),capture_output=True,timeout=5)
        assert interrupted.returncode!=0
        with sqlite3.connect(db) as c:
            assert c.execute('select count(*) from x_meta').fetchone()==(0,)
            assert c.execute("select count(*) from sqlite_master where type='table' and (name like 'x_sim_%' or name='x_exact_commands')").fetchone()==(0,)
            c.execute('DROP TRIGGER issue1381_init_abort')
        recovered=start(); recovered.kill(); recovered.wait(5); xp.unlink(missing_ok=True)
        with sqlite3.connect(db) as c:
            assert c.execute("select value from x_meta where key='writer_epoch'").fetchone()==('1',)
            assert json.loads(c.execute("select v from x_sim_meta where k='authority_profile'").fetchone()[0])==sim
    p=start()
    try:
        a=dict(kind='submit',order=order('a')); ca=command(a)
        # The production open path holds the S-authorize-once state: WAL and synchronous=FULL, as E's store.
        with sqlite3.connect(db) as c: assert c.execute('PRAGMA journal_mode').fetchone()==('wal',)
        if not fixture:
            lines=[l for l in (directory/'x.log').read_text().splitlines() if l.startswith('x_execution_session storage ')]
            assert lines, 'X did not report its storage preconditions'
            storage=json.loads(lines[-1].split(' ',2)[2])
            assert (storage['journal_mode'],storage['synchronous'])==('wal','2'),storage
        before=len(s.calls)
        for bad in ['denied','identity','content','future']:
            e.bad=bad
            rejected=request(xp,'AcceptExact',ca)
            assert rejected.get('kind')=='Error',(bad,rejected)
            assert request(xp,'QueryCommand','a')['state']=='NoRecord'
        e.bad=None
        moved=e.path.with_name('e-unavailable'); e.path.rename(moved)
        assert request(xp,'AcceptExact',ca)['kind']=='Error'
        moved.rename(e.path)
        unknown=copy.deepcopy(ca); unknown['certificate']['conditions'][0]['validator_capability']='unknown'; unknown['certificate_hash']=digest(unknown['certificate'])
        assert request(xp,'AcceptExact',unknown)['kind']=='Error'
        assert request(xp,'AcceptExact',ca)['state']=='Accepted'
        assert len(s.calls)==before, 'Accept must never ask S/call adapter'
        conflicting=copy.deepcopy(ca); conflicting['x_epoch']=2
        assert request(xp,'AcceptExact',conflicting)['kind']=='Error'
        assert request(xp,'AcceptExact',ca)['state']=='Accepted'
        # Invalid input cannot consume S eligibility or poison Accepted with MayHaveCalled.
        invalid_ohlc=batch(0,[a]); invalid_ohlc['bar']['low']=111
        sibling=copy.deepcopy(a); sibling['order'].update(command_id='a-conflict',eligibility_ref='S:a-conflict')
        assert request(xp,'AcceptExact',command(sibling))['state']=='Accepted'
        invalid_close=batch(0,[a,sibling])
        invalid_bust=batch(0,[a]); invalid_bust['scenario_busts']=[dict(exec_id='missing',quantity=1,scenario_ref='missing')]
        before=len(s.calls)
        for invalid in [invalid_ohlc,invalid_close,invalid_bust]:
            assert request(xp,'AdvanceBar',invalid)['kind']=='Error'
            assert request(xp,'QueryCommand','a')['state']=='Accepted'
            assert request(xp,'QueryCommand','a-conflict')['state']=='Accepted'
            assert len(s.calls)==before, 'invalid input consumed S eligibility'
            with sqlite3.connect(db) as c:
                assert c.execute('select attempt_batch from x_exact_commands where id=?',('a',)).fetchone()==(None,)
                assert c.execute('select count(*) from x_sim_batches').fetchone()==(0,)
        # Oversized S frame is known unsent: refuse before PendingBatch, never touch S, stay Accepted.
        # Compact E replies leave a few bytes where the E reply fits but the S request does not.
        limit=sim['max_frame_bytes']
        def sized(name,pad=0):
            cmd=command(dict(kind='submit',order=order(name)))
            cmd['certificate']['responsibility_refs']=['controlled-responsibility'+'x'*pad]; cmd['certificate_hash']=digest(cmd['certificate'])
            return cmd
        e.compact={'big-p':'Ep','big-x':'Ex'}
        assert request(xp,'AcceptExact',sized('big-p'))['state']=='Accepted'
        probe=e.calls[-1]; reply=e.replies[-1]
        s_payload=dict(probe,op='RequestConditionalExecution',authority_id='S',authority_epoch='s1',release_receipt_id='Ep')
        reply_len=len(canonical(reply))+1; s_len=len(canonical(x_envelope('s',s_payload)))+1
        assert s_len>reply_len,(s_len,reply_len)
        big=sized('big-x',limit-reply_len)
        assert request(xp,'AcceptExact',big)['state']=='Accepted'
        assert len(canonical(x_envelope('s',dict(s_payload,command=big,command_hash=digest(big),command_id='big-x',release_receipt_id='Ex'))))+1>limit
        before=len(s.calls)
        oversized=request(xp,'AdvanceBar',batch(0,[big['change']]))
        assert oversized['kind']=='Error' and '帧界' in canonical(oversized),oversized
        assert request(xp,'QueryCommand','big-x')['state']=='Accepted'
        assert len(s.calls)==before, 'oversized frame reached S'
        with sqlite3.connect(db) as c:
            assert c.execute("select count(*) from x_sim_meta where k='pending_batch'").fetchone()==(0,)
        for bad in ['denied','identity','content','future']:
            s.bad=bad; assert request(xp,'AdvanceBar',batch(0,[a]))['kind']=='Error'
            assert request(xp,'QueryCommand','a')['state']=='ExecutionRequested'
        s.bad=None
        p=reject_new_epoch(p)  # ExecutionRequested remains recoverable by epoch 1.
        r0=request(xp,'AdvanceBar',batch(0,[a])); assert r0['originals']==[]
        assert request(xp,'QueryCommand','a')['state']=='Observed'
        # Replace at bar 1 close: current fill still old price, next bar new price and remaining quantity.
        replacement=copy.deepcopy(a['order']); replacement.update(command_id='r',revision=2,eligibility_ref='S:r',kind=dict(kind='limit',price=95))
        change=dict(kind='replace',order=replacement)
        assert request(xp,'AcceptExact',command(change))['state']=='Accepted'
        b1=batch(1,[change]); b1['capacity']=dict(kind='scenario',reference='controlled-cap-40',buy=40,sell=0)
        r1=request(xp,'AdvanceBar',b1); fill=r1['originals'][0]['event']['fill']; assert (fill['quantity'],fill['price'],fill['amount'],fill['fee'])==(40,100,4000,40),r1
        assert request(xp,'AdvanceBar',b1)==r1
        p.terminate(); p.wait(5); xp.unlink(missing_ok=True); p=start()
        assert request(xp,'AdvanceBar',b1)==r1
        r2=request(xp,'AdvanceBar',batch(2)); fill=r2['originals'][0]['event']['fill']; assert (fill['quantity'],fill['price'])==(60,95)
        pending=dict(kind='submit',order=order('cancel-me',quantity=10))
        assert request(xp,'AcceptExact',command(pending))['state']=='Accepted'
        # S socket absent is known unsent: stay Accepted, then retry against a reachable S authorizes once.
        if fixture:
            # The durable ExecutionRequested write outlasts timeout_ms; the S deadline must not include it.
            p.terminate(); p.wait(5); xp.unlink(missing_ok=True); p=start(slow_claim=True)
        before=len(s.calls); moved=s.path.with_name('s-unavailable'); s.path.rename(moved)
        assert request(xp,'AdvanceBar',batch(3,[pending]))['kind']=='Error'
        assert request(xp,'QueryCommand','cancel-me')['state']=='Accepted'
        assert len(s.calls)==before
        moved.rename(s.path)
        assert request(xp,'AdvanceBar',batch(3,[pending]))['originals']==[]
        assert [q['op'] for q in s.calls[before:]]==['RequestConditionalExecution']
        assert s.authorizations['cancel-me']==1
        cancel=dict(kind='cancel',command_id='cancel',family_id='f-cancel-me',eligibility_ref='S:cancel')
        market_order=order('market',side='sell',quantity=2); market_order['kind']=dict(kind='market',exec_index=5)
        market=dict(kind='submit',order=market_order)
        for change in [cancel,market]: assert request(xp,'AcceptExact',command(change))['state']=='Accepted'
        b4=batch(4,[cancel,market]); b4['capacity']=dict(kind='scenario',reference='controlled-cap-4',buy=4,sell=0)
        r4=request(xp,'AdvanceBar',b4); assert r4['originals'][0]['event']['fill']['quantity']==4
        r5=request(xp,'AdvanceBar',batch(5)); assert len(r5['originals'])==2
        fill=r5['originals'][0]['event']['fill']; assert (fill['quantity'],fill['price'],fill['fee'],fill['slot'])==(2,104,5,'close')
        for raw in r1['originals']+r2['originals']+r4['originals']+r5['originals']:
            assert request(xp,'QueryOriginal',raw['event']['source']['external_fact_id'])==raw
        # R3: stable (1,2) epoch survives process restart; varying capacity ref cannot reset it.
        cap_orders=[dict(kind='submit',order=order('epoch-a',quantity=1)),dict(kind='submit',order=order('epoch-b',quantity=2))]
        for change in cap_orders: assert request(xp,'AcceptExact',command(change))['state']=='Accepted'
        b6=batch(6,cap_orders)
        wrong=copy.deepcopy(b6); wrong['close_changes'][1]['order']['kind']['price']=99
        before=len(s.calls); assert request(xp,'AdvanceBar',wrong)['kind']=='Error'
        assert len(s.calls)==before, 'late command mismatch consumed earlier S eligibility'
        for command_name in ['epoch-a','epoch-b']: assert request(xp,'QueryCommand',command_name)['state']=='Accepted'
        # First S committed and persisted locally; second S committed but reply was lost.
        s.drop_after='epoch-b'; failed=request(xp,'AdvanceBar',b6); assert failed['kind']=='Error',failed
        assert request(xp,'QueryCommand','epoch-a')['state']=='ExecutionReady'
        assert request(xp,'QueryCommand','epoch-b')['state']=='ExecutionRequested'
        s.drop_after=None
        p=reject_new_epoch(p,'b6' if fixture else None)  # ExecutionReady + ExecutionRequested
        bypass=batch(6); bypass['request_id']='bypass6'
        assert request(xp,'AdvanceBar',bypass)['kind']=='Error'
        s.bad='missing'; assert request(xp,'AdvanceBar',b6)['kind']=='Error'; s.bad=None
        assert request(xp,'QueryCommand','epoch-b')['state']=='ExecutionRequested'
        assert s.authorizations['epoch-b']==1, 'NoRecord caused reauthorization'
        if fixture:
            try: request(xp,'AdvanceBar',b6)
            except (ValueError,ConnectionError): pass
            assert p.wait(5)==43
        else:
            # Fault the model transaction after real X has durably claimed MayHaveCalled.
            with sqlite3.connect(db) as c:
                c.execute("CREATE TRIGGER issue1381_block_publish BEFORE INSERT ON x_sim_batches WHEN NEW.id='b6' BEGIN SELECT RAISE(ABORT,'controlled publish fault'); END")
            assert request(xp,'AdvanceBar',b6)['kind']=='Error'
        with sqlite3.connect(db) as c:
            assert c.execute("select count(*) from x_exact_commands where state='MayHaveCalled'").fetchone()==(2,)
            assert c.execute("select count(*) from x_sim_batches where id='b6'").fetchone()==(0,)
        p=reject_new_epoch(p)  # MayHaveCalled cannot irreversibly advance writer_epoch.
        if not fixture:
            with sqlite3.connect(db) as c: c.execute('DROP TRIGGER issue1381_block_publish')
        assert request(xp,'AdvanceBar',bypass)['kind']=='Error'
        r6=request(xp,'AdvanceBar',b6); assert r6['originals']==[]
        assert s.authorizations['epoch-a']==s.authorizations['epoch-b']==1

        reordered=copy.deepcopy(b6); reordered['close_changes'].reverse(); assert request(xp,'AdvanceBar',reordered)==r6
        b7=batch(7); b7['capacity']=dict(kind='scenario',reference='r3-source-7',buy=1,sell=0)
        half=copy.deepcopy(b7); half['capacity_participants']=['f-epoch-a']; assert request(xp,'AdvanceBar',half)['kind']=='Error'
        r7=request(xp,'AdvanceBar',b7); assert r7['originals'][0]['event']['fill']['family_id']=='f-epoch-b'
        assert request(xp,'QueryBatch','b7')==r7
        p.terminate(); p.wait(5); xp.unlink(missing_ok=True); p=start()
        assert request(xp,'AdvanceBar',b7)==r7
        b8=batch(8); b8['capacity']=dict(kind='scenario',reference='r3-source-8',buy=1,sell=0)
        r8=request(xp,'AdvanceBar',b8); assert r8['originals'][0]['event']['fill']['family_id']=='f-epoch-b'
        assert r7['originals'][0]['event']['fill']['capacity_epoch']==r8['originals'][0]['event']['fill']['capacity_epoch']
        b9=batch(9); b9['capacity']=dict(kind='scenario',reference='r3-source-9',buy=1,sell=0)
        r9=request(xp,'AdvanceBar',b9); assert r9['originals'][0]['event']['fill']['family_id']=='f-epoch-a'
        # Sequential historical busts reach the full original amount: cold replay must use each prior frontier.
        bust_exec=r1['originals'][0]['event']['fill']['exec_id']
        bust_batches=[]
        for index,quantity in [(10,5),(11,35)]:
            bb=batch(index); bb['capacity']=dict(kind='scenario',reference='bust-r5',buy=0,sell=0)
            bb['scenario_busts']=[dict(exec_id=bust_exec,quantity=quantity,scenario_ref='bust-r5')]
            rr=request(xp,'AdvanceBar',bb); assert rr['kind']=='SimulationBatch',rr
            assert len(rr['originals'])==1 and rr['originals'][0]['event']['kind']=='bust'
            bust_batches.append(rr)
        # Two independent processes must leave every X table byte-identical, clocks included.
        with sqlite3.connect(db) as c:
            assert c.execute('PRAGMA journal_mode').fetchone()==('wal',), 'X store not opened in WAL'
            tables='\n'.join(c.iterdump())
            clocks=c.execute('select accept_clock,release_evidence from x_exact_commands').fetchall()
            for clock,release in clocks:
                clock=json.loads(clock); release=json.loads(release)
                assert clock['received_ns']<=clock['first_known_ns']<=clock['commit_ns']
                assert clock['first_known_ns']>=release['commit_ns']
        (directory/'tables.sql').write_text(tables)
        p.terminate(); p.wait(5); xp.unlink(missing_ok=True)
        # Cold recovery refuses missing authority/original evidence; exact restoration resumes.
        original_id=r7['originals'][0]['event']['source']['external_fact_id']
        for table,key in [('x_exact_commands','a'),('x_sim_originals',original_id)]:
            with sqlite3.connect(db) as c:
                row=c.execute('select * from '+table+' where id=?',(key,)).fetchone()
                c.execute('delete from '+table+' where id=?',(key,))
            blocked=subprocess.run(argv(),env=env(),capture_output=True,timeout=5)
            assert blocked.returncode!=0, (table,blocked.stdout,blocked.stderr)
            with sqlite3.connect(db) as c: c.execute('insert into '+table+' values('+','.join('?' for _ in row)+')',row)
        with sqlite3.connect(db) as c:
            receipt=c.execute('select execute_evidence from x_exact_commands where id=?',('a',)).fetchone()[0]
            c.execute('update x_exact_commands set execute_evidence=NULL where id=?',('a',))
        blocked=subprocess.run(argv(),env=env(),capture_output=True,timeout=5)
        assert blocked.returncode!=0
        with sqlite3.connect(db) as c: c.execute('update x_exact_commands set execute_evidence=? where id=?',(receipt,'a'))
        # Joint derived-evidence damage cannot erase obligations still present in input batches.
        for mode in ['fee-delete','fee-modify','bust-delete']:
            bid='b10' if mode=='bust-delete' else 'b1'
            with sqlite3.connect(db) as c:
                saved_result=c.execute('select result from x_sim_batches where id=?',(bid,)).fetchone()[0]
                result=json.loads(saved_result); kind='bust' if mode=='bust-delete' else 'fee'
                target=next(d for d in result['originals'] if d['event']['kind']==kind)
                oid=target['event']['source']['external_fact_id']
                saved_original=c.execute('select raw from x_sim_originals where id=?',(oid,)).fetchone()[0]
                saved_bust=c.execute('select * from x_sim_busts where id=?',(oid,)).fetchone()
                if mode=='fee-modify':
                    target['event']['amount']+=1
                    c.execute('update x_sim_originals set raw=? where id=?',(canonical(target),oid))
                else:
                    result['originals']=[d for d in result['originals'] if d['event']['source']['external_fact_id']!=oid]
                    c.execute('delete from x_sim_originals where id=?',(oid,))
                    if saved_bust: c.execute('delete from x_sim_busts where id=?',(oid,))
                c.execute('update x_sim_batches set result=? where id=?',(canonical(result),bid))
            blocked=subprocess.run(argv(),env=env(),capture_output=True,timeout=5)
            assert blocked.returncode!=0,(mode,blocked.stdout,blocked.stderr)
            with sqlite3.connect(db) as c:
                c.execute('update x_sim_batches set result=? where id=?',(saved_result,bid))
                c.execute('insert or replace into x_sim_originals values(?,?)',(oid,saved_original))
                if saved_bust: c.execute('insert into x_sim_busts values(?,?,?)',saved_bust)
        with sqlite3.connect(db) as c:
            binding=c.execute("select v from x_sim_meta where k='authority_profile'").fetchone()[0]
            c.execute("delete from x_sim_meta where k='authority_profile'")
        changed_profile=copy.deepcopy(profile)
        changed_profile['history_simulation']['e']['socket']=str(sockets/'wrong-e')
        changed_profile['history_simulation']['s']['socket']=str(sockets/'wrong-s')
        for candidate in [profile,changed_profile]:
            pp.write_text(canonical(candidate)); blocked=subprocess.run(argv(),env=env(),capture_output=True,timeout=5)
            assert blocked.returncode!=0 and b'IdentityConflict' in blocked.stderr
            with sqlite3.connect(db) as c: assert c.execute("select v from x_sim_meta where k='authority_profile'").fetchone() is None
        pp.write_text(canonical(profile))
        with sqlite3.connect(db) as c: c.execute("insert into x_sim_meta values('authority_profile',?)",(binding,))
        p=start(); assert request(xp,'QueryBatch','b7')==r7; assert request(xp,'QueryOriginal',original_id)==r7['originals'][0]
        assert request(xp,'QueryBatch','b10')==bust_batches[0] and request(xp,'QueryBatch','b11')==bust_batches[1]
        p.terminate(); p.wait(5); xp.unlink(missing_ok=True)
        # Frozen namespace cannot be re-opened as venue/dry-run profile.
        bad=copy.deepcopy(profile); bad.pop('history_simulation'); bad['mode']='dry-run'; pp.write_text(canonical(bad))
        blocked=subprocess.run(argv(),env=env(),capture_output=True,timeout=5)
        assert blocked.returncode!=0 and (fixture or b'IdentityConflict' in blocked.stderr)
        pp.write_text(canonical(profile))
        # S received the frame but committed nothing: possibly sent, so stay pending and only query, never resend.
        p=start()
        stuck=dict(kind='submit',order=order('stuck',quantity=1))
        assert request(xp,'AcceptExact',command(stuck))['state']=='Accepted'
        before=len(s.calls); s.swallow='stuck'
        assert request(xp,'AdvanceBar',batch(12,[stuck]))['kind']=='Error'
        assert request(xp,'QueryCommand','stuck')['state']=='ExecutionRequested'
        s.swallow=None
        assert request(xp,'AdvanceBar',batch(12,[stuck]))['kind']=='Error'
        assert request(xp,'QueryCommand','stuck')['state']=='ExecutionRequested'
        assert [q['op'] for q in s.calls[before:]]==['RequestConditionalExecution','QueryExecuteCommitted']
        assert 'stuck' not in s.authorizations
        p.terminate(); p.wait(5); xp.unlink(missing_ok=True)
        # Recovery uses the same clock predicate and refuses a corrupted earlier-than-release record.
        with sqlite3.connect(db) as c:
            clock,release=c.execute('select accept_clock,release_evidence from x_exact_commands where id=?',('r',)).fetchone()
            clock=json.loads(clock); early=json.loads(release)['commit_ns']-1
            assert early>=0
            clock.update(received_ns=early,first_known_ns=early,commit_ns=early)
            c.execute('update x_exact_commands set accept_clock=? where id=?',(canonical(clock),'r'))
        blocked=subprocess.run(argv(),env=env(),capture_output=True,timeout=5)
        assert blocked.returncode!=0 and b'InvalidDomain' in blocked.stderr
        print(name+': PASS '+('test runtime with post-claim exit43' if fixture else 'production X binary')+', invalid input stays Accepted, unsent S failures stay Accepted, sent-but-unknown stays query-only, S reply loss/query-only recovery, unique S authorization, pending epoch2 rejected without writes, full fee/bust replay, frozen binding, atomic first initialization recovery')
        return tables
    finally:
        if p.poll() is None: p.terminate(); p.wait(5)
        log.close(); e.sock.close(); s.sock.close()
        for file in sockets.iterdir(): file.unlink()
        sockets.rmdir()
def rebind_attempts():
    """Real X + controlled S seam; the E live E/B arm is in production_session_entry."""
    profile_path=ROOT/'x.json'; db=ROOT/'x.db'; xp=ROOT/'x'; sp=ROOT/'s'; ep=ROOT/'e'
    sdb=ROOT/'s.db'; edb=ROOT/'e.db'; manifest=ROOT/'e.json'; handoff_path=ROOT/'rebind.json'
    sim=dict(model=model(),session_id='session',session_generation='1',x_id='X',
        source_namespace='x-sim',source_epoch='epoch1',
        e=dict(authority_id='E',authority_epoch='1',schema_revision='economic-session/1',
            reply_namespace='economic-session/replies',producer_id='E:session'),
        s=dict(authority_id='S',authority_epoch='1',schema_revision='s-authority-fixture/1',
            reply_namespace='s/replies',producer_id='S:session'),
        conditions=CONDITIONS,timeout_ms=600,max_frame_bytes=1048576)
    s_config=dict(rule_revision='rule/1',profile_hash='1'*64,catalog_hash='2'*64,
        clock_plan_hash='3'*64,structure_source=dict(category='TestOnlyStructure',namespaces=['testonly.ohlc']))
    e_business=dict(schema_revision='economic-manifest/2',protocol_revision='economic-session/1',
        book_revision='tb03c-book/1',session_id='session',session_generation='1',
        chongs=[dict(chong_id='alpha',symbol='TEST',operation_level='1',fixed_q='1')],
        authorized_sources=[dict(source_namespace='x-sim',source_epoch='epoch1',producer_id='X',
            producer_epoch='1',operations=['ReadView'])],
        resources=dict(max_frame_bytes='1048576',read_timeout_ms='1000',write_timeout_ms='1000',
            response_timeout_ms='2000',queue_capacity='2',max_connections='2'),
        clock=dict(kind='TestOnly',plan=dict(init_ns='1',recover_ns=['10'],messages={})))
    e_deploy=dict(schema_revision='economic-deployment/1',domains={
        'E':dict(db=str(edb),socket=str(ep)),'B:alpha':dict(db=str(ROOT/'b.db'),socket=str(ROOT/'b'))},
        voice={},finance=None,fault_markers=[],x_db=None)
    manifest.write_text(canonical(dict(schema_revision='economic-session-config/2',business=e_business,deployment=e_deploy)))
    def e_cli(op,*args):
        result=subprocess.run([os.environ['X_FIXTURE_E_BIN'],op,'--db',str(edb),
            '--manifest',str(manifest),*args],capture_output=True,timeout=5)
        assert result.returncode==0,(result.stdout,result.stderr)
        return json.loads(result.stdout)
    original_cut=e_cli('init')['cut']
    sim.update(schema_revision='x-simulation-authority/2',
        recovery_identity=dict(e_manifest_hash=digest(e_business),s_config=s_config))
    deploy=dict(schema_revision='x-simulation-deployment/1',db=str(db),socket=str(xp),
        e_socket=str(ep),s_socket=str(sp),recovery_domains=dict(e_db=str(edb),e_manifest=str(manifest),s_db=str(sdb)))
    outer=dict(profile_revision='x-execution-profile/1',mode='simulation',
        credential_scope=dict(env='UNUSED_SIMULATION_CREDENTIAL'),history_simulation=dict(business=sim,deployment=deploy))
    profile_path.write_text(canonical(outer))

    def argv(rebind=False,other=db,profile=profile_path):
        out=[str(BIN),'serve','--db',str(other),'--profile',str(profile),'--writer-epoch','1']
        return out+(['--authority-rebind',str(handoff_path)] if rebind else [])
    def save(v):
        with os.fdopen(os.open(handoff_path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w') as f:
            f.write(canonical(v))
    def refused(args):
        result=subprocess.run(args,capture_output=True,timeout=5)
        assert result.returncode==2,(result.stdout,result.stderr)
        return result.stderr.decode()
    def source_s(from_epoch):
        return dict(verification='current-recovery',db=str(sdb),receipt=dict(kind='NamedRecoveryReceipt',
            writer_epoch=str(from_epoch+1),recover_ns=str(300+from_epoch),
            request=dict(schema_revision='s-recovery/1',domain_id='S',session_id='session',
                session_generation='1',recovery_id=f's-{from_epoch}',from_epoch=str(from_epoch),
                cut=dict(generation='0',structure_cut='cut-0',index_frontier=''),config=s_config,
                clock_event_id=f'recover-{from_epoch}')))
    def handoff(from_epoch):
        return dict(schema_revision='x-authority-rebind-input/1',domains=['S'],s=source_s(from_epoch))
    def dump():
        with sqlite3.connect(db) as conn: return '\n'.join(conn.iterdump())
    def binding():
        with sqlite3.connect(db) as conn:
            return [json.loads(v) for v, in conn.execute('SELECT record FROM x_authority_bindings ORDER BY binding_seq')]
    def cmd(name):
        val=command(dict(kind='submit',order=order(name,quantity=1)))
        val['session_generation']='1'
        return val
    def ask(op,val): return request(xp,op,val)
    def query(id,state):
        val=ask('QueryCommand',id)
        assert val['state']==state,val
        return val
    def verdict(op,val,kind):
        result=ask(op,val)
        assert result['kind']==kind,result
        return result
    def start(rebind=False,other=db,profile=profile_path):
        p=subprocess.Popen(argv(rebind,other,profile),stdout=subprocess.DEVNULL,stderr=log)
        for _ in range(500):
            if listening(xp): return p
            assert p.poll() is None,(p.returncode,(ROOT/'x.log').read_text())
            time.sleep(.01)
        p.kill(); p.wait(5)
        raise AssertionError('X not listening')
    def stop_x(p):
        p.kill(); assert p.wait(5)==-9
        if xp.exists(): xp.rename(ROOT/f'x-stopped-{p.pid}')
    def audit():
        out=subprocess.run([str(BIN),'audit','--db',str(db)],capture_output=True,timeout=5)
        assert out.returncode==0,(out.stdout,out.stderr)

    class Source:
        def __init__(self,path,role):
            self.role=role; self.epoch='1'; self.drop=None; self.hide=None; self.wrong_original=False
            self.records={}; self.calls=[]
            self.sock=socket.socket(socket.AF_UNIX); self.sock.bind(str(path)); self.sock.listen(16)
            self.thread=threading.Thread(target=self.run,daemon=True); self.thread.start()
        def run(self):
            while True:
                try: c,_=self.sock.accept()
                except OSError: break
                with c:
                    req=json.loads(c.makefile('rb').readline())
                    q=req['payload']; self.calls.append(copy.deepcopy(q))
                    role=sim[self.role.lower()]
                    authority=dict(role,authority_epoch=self.epoch)
                    assert req['producer_id']=='X' and req['producer_epoch']=='1' and req['source_epoch']=='epoch1'
                    assert q['authority_id']==self.role and q['authority_epoch']==self.epoch
                    id=q['command_id']; op=q['op']
                    if op=='QueryExecuteCommitted':
                        if self.hide==id or id not in self.records:
                            wire=reply_envelope(req,dict(kind='NoRecord'),authority)
                        else:
                            attempt,original=self.records[id]
                            assert q['original_attempt']==attempt
                            proof=copy.deepcopy(original)
                            if self.wrong_original:
                                proof['producer_epoch']=self.epoch
                            wire=reply_envelope(req,dict(kind='ExecuteCommittedOriginal',original_reply=proof),authority)
                    else:
                        result={k:v for k,v in q.items() if k!='op'}
                        state='ReleasedExact' if self.role=='E' else 'ExecuteCommitted'
                        result.update(state=state,receipt_id=f'{self.role}:{id}',commit_ns=0)
                        wire=reply_envelope(req,result,authority)
                        if self.role=='S':
                            assert op=='RequestConditionalExecution'
                            assert id not in self.records, 'duplicate S qualification'
                            self.records[id]=(req,wire)
                            if self.drop==id: continue
                    c.sendall((canonical(wire)+'\n').encode())

    log=open(ROOT/'x.log','wb',buffering=0)
    e=Source(ep,'E'); s=Source(sp,'S')
    p=None
    try:
        save(handoff(1))
        assert '原 X 库' in refused(argv(True))
        assert not db.exists() and not Path(str(db)+'.writer.lock').exists()
        db.touch()
        refused(argv(True))
        assert db.read_bytes()==b''
        db.rename(ROOT/'uninitialized.db')
        p=start()
        observed,ready,lost,pending=map(cmd,['o','a','b','next'])
        for val in (observed,ready,lost,pending):
            assert verdict('AcceptExact',val,'ExactCommandState')['state']=='Accepted'
        verdict('AdvanceBar',batch(0,[observed['change']]),'SimulationBatch')
        mixed=batch(1,[ready['change'],lost['change']])
        s.drop='b'
        verdict('AdvanceBar',mixed,'Error')
        states={'o':'Observed','a':'ExecutionReady','b':'ExecutionRequested','next':'Accepted'}
        frozen={k:query(k,v)['authority_history'] for k,v in states.items()}
        assert all(item['binding_seq']==0 for rows in frozen.values() for item in rows)
        assert all(item['original']['request']['payload']['authority_epoch']=='1'
            for rows in frozen.values() for item in rows if item['phase'] in ('accept','request'))
        stop_x(p); p=None; audit()
        before=dump()
        mutations=[
            {},
            dict(writer_epoch='2'),
            source_s(0)['receipt'],
            dict(schema_revision='x-authority-rebind-input/1'),
        ]
        for key,value in [('verification','query-recovery'),('db',str(edb))]:
            with_change=handoff(1); with_change['s'][key]=value; mutations.append(with_change)
        for key,value in [('schema_revision','economic-recovery/1'),('session_id','other'),
                          ('session_generation','2'),('config',dict(bogus='path')),
                          ('cut',dict(generation='0',structure_cut='/tmp/path',index_frontier=''))]:
            with_change=handoff(1); with_change['s']['receipt']['request'][key]=value; mutations.append(with_change)
        jump=handoff(1); jump['s']['receipt']['writer_epoch']='3'; mutations.append(jump)
        for attempt in mutations:
            save(attempt); refused(argv(True)); assert dump()==before
        flat=copy.deepcopy(outer)
        flat['history_simulation']=copy.deepcopy(sim)
        for key in ('schema_revision','recovery_identity'): flat['history_simulation'].pop(key)
        flat['history_simulation'].update(socket=str(xp))
        flat['history_simulation']['e']['socket']=str(ep)
        flat['history_simulation']['s']['socket']=str(sp)
        legacy_profile=ROOT/'legacy.json'; legacy_profile.write_text(canonical(flat))
        legacy=ROOT/'legacy.db'
        p=start(other=legacy,profile=legacy_profile); stop_x(p); p=None
        with sqlite3.connect(legacy) as conn: legacy_before=list(conn.iterdump())
        save(handoff(1))
        assert '就地升级' in refused(argv(True,legacy,legacy_profile))
        edited_outer=copy.deepcopy(outer)
        edited_outer['history_simulation']['deployment']['db']=str(legacy)
        edited_profile=ROOT/'attempted-upgrade.json'
        edited_profile.write_text(canonical(edited_outer))
        assert '禁止切换部署合同版本' in refused(argv(True,legacy,edited_profile))
        with sqlite3.connect(legacy) as conn: assert legacy_before==list(conn.iterdump())
        print('authority_rebind_rejects_invalid_transition: malformed/old/query/wrong S context/no X DB rejected without writes')

        e_request=ROOT/'e-recovery.json'
        e_request.write_text(canonical(dict(schema_revision='economic-recovery/1',domain_id='E',
            recovery_id='recover-e',session_id='session',session_generation='1',from_epoch='1',
            manifest_hash=digest(e_business),cut=original_cut)))
        actual=e_cli('recover-named','--recovery-request',str(e_request))
        assert actual==e_cli('current-recovery','--recovery-request',str(e_request))
        combined=handoff(1)
        combined.update(domains=['E','S'],e=dict(verification='current-recovery',db=str(edb),receipt=actual))
        save(combined)
        e.epoch='2'; s.epoch='2'; s.drop=None
        p=start(True)
        assert binding()[1]['new_vector']==dict(e_authority_epoch=2,s_authority_epoch=2)
        for k,v in states.items():
            result=query(k,v)
            assert result['current_binding_seq']==1 and result['authority_history']==frozen[k],result
        drift=copy.deepcopy(lost); drift['symbol']='OTHER'
        assert 'IdentityConflict' in verdict('AcceptExact',drift,'Error')['error']
        assert ask('AcceptExact',observed)['authority_history']==frozen['o']
        s.hide='b'
        verdict('AdvanceBar',mixed,'Error')
        s.hide=None; s.wrong_original=True
        verdict('AdvanceBar',mixed,'Error')
        s.wrong_original=False
        assert query('b','ExecutionRequested')['authority_history']==frozen['b']
        # 确定性故障注入：只让真实 X 的批发布事务失败，不伪造任何命令状态或占有。
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TRIGGER block_test_batch BEFORE INSERT ON x_sim_batches WHEN NEW.id='b1' BEGIN SELECT RAISE(ABORT,'fixture interruption'); END")
        verdict('AdvanceBar',mixed,'Error')
        old_claims={id:query(id,'MayHaveCalled')['authority_history'] for id in ('a','b')}
        evidence=old_claims['b'][2]
        assert evidence['binding_seq']==1
        assert evidence['original']['observed_query']['reply']['producer_epoch']=='2'
        assert evidence['original']['original_reply']['producer_epoch']=='1'
        assert evidence['original']['original_reply']['payload']['commit_ns']==0
        assert old_claims['a'][2]['binding_seq']==0
        assert [m['op'] for m in s.calls if m['command_id']=='b']==[
            'RequestConditionalExecution','QueryExecuteCommitted','QueryExecuteCommitted','QueryExecuteCommitted']
        stop_x(p); p=None; audit()
        with sqlite3.connect(db) as conn: conn.execute('DROP TRIGGER block_test_batch')
        rebound=dump()
        p=start(True); assert dump()==rebound and len(binding())==2
        stop_x(p); p=None
        diff=copy.deepcopy(combined); diff['s']['receipt']['recover_ns']='950'; save(diff)
        assert '同权威转换' in refused(argv(True))
        assert dump()==rebound
        save(handoff(2)); s.epoch='3'
        p=start(True)
        assert binding()[2]['new_vector']==dict(e_authority_epoch=2,s_authority_epoch=3)
        for id in old_claims: assert query(id,'MayHaveCalled')['authority_history']==old_claims[id]
        call_count=len(s.calls)
        value=verdict('AdvanceBar',mixed,'SimulationBatch')
        assert verdict('AdvanceBar',mixed,'SimulationBatch')==value and len(s.calls)==call_count
        for id in old_claims:
            items=query(id,'Observed')['authority_history']
            assert items[:-1]==old_claims[id] and items[-1]['binding_seq']==2
        assert query('o','Observed')['authority_history']==frozen['o']
        verdict('AdvanceBar',batch(2,[pending['change']]),'SimulationBatch')
        assert s.calls[-1]['op']=='RequestConditionalExecution' and s.calls[-1]['authority_epoch']=='3'
        assert len(s.records)==4 and len(s.calls)==call_count+1
        stop_x(p); p=None; audit()
        before=dump(); save(combined); refused(argv(True)); assert dump()==before
        # 新旧向量中的 E 代可能相同，仍不能把旧事件改标为另一绑定。
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE x_authority_events SET binding_seq=1 WHERE command_id='o' AND phase='accept'")
        bad_audit=subprocess.run([str(BIN),'audit','--db',str(db)],capture_output=True,timeout=5)
        assert bad_audit.returncode==2 and b'IdentityConflict' in bad_audit.stderr
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE x_authority_events SET binding_seq=0 WHERE command_id='o' AND phase='accept'")
        p=start(); assert len(binding())==3
        print('authority_rebind_s_and_dual_domain_vector: controlled S 1→2 with genuine E recovery; S alone 2→3, E stays 2')
        print('authority_rebind_preserves_original_attempts: Accepted, ExecutionRequested/NoRecord/bad proof, ExecutionReady, MayHaveCalled, Observed; one S claim per command, exact historic wire replay and audit')
    finally:
        if p is not None and p.poll() is None: stop_x(p)
        log.close(); e.sock.close(); s.sock.close()

if __name__=='__main__':
    if len(sys.argv)>3 and sys.argv[3]=='authority-rebind':
        rebind_attempts()
    else:
        check_listening_predicate()
        a=run('run-a'); b=run('run-b'); assert a==b, 'fresh process X tables differ'
        print('PASS two fresh processes: byte-identical X tables')
