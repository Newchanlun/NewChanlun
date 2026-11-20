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
