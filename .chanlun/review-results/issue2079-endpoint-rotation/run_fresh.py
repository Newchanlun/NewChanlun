import json, subprocess as sp, sys
from pathlib import Path
D=Path(__file__).resolve().parent
DOCKER=['docker','--context','orbstack']
def display(t): print(t,flush=True)
def run(*args,**kw): return sp.run([*DOCKER,*args],text=True,check=True,**kw)
cid=run('run','--rm','-d','--pull','never','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--tmpfs','/tmp:mode=1777','-v',f'{D}:/p:ro','python:3.11-bookworm','sleep','90',capture_output=True).stdout.strip()
def child(role,g=None,uid='65534:0'):
    argv=['exec','-i','--user',uid,cid,'python','-B','/p/fresh_listener.py',role]
    if g: argv += [g]
    return sp.Popen([*DOCKER,*argv],text=True,stdin=sp.PIPE,stdout=sp.PIPE)
def one(p,stage):
    line=p.stdout.readline()
    assert line and json.loads(line)['stage']==stage,repr(line)
    display(line.strip())
def send(p,s):p.stdin.write(s+'\n');p.stdin.flush()
def expect(p):assert p.wait(timeout=12)==0
try:
    for g in ['1','2']:
        a=child('acquire',g,'0:0');one(a,'published')
        w=child('worker',g);one(w,'worker');expect(a)
        send(w,'accept-one')
        c=child('client');one(c,'client');expect(c)
        if g=='1':
            q=child('queued');one(q,'old-message-queued')
            send(w,'exit');expect(w)
            one(q,'old-connection-ended');expect(q)
        else:expect(w)
    display('PASS: 原绝对路径两次重新发布，非发布者不能换名，旧积压未传到新一代。')
finally:
    run('rm','-f',cid,stdout=sp.DEVNULL)
