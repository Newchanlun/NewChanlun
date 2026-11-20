import json,re,sys,collections
B='/home/workspace/src/NewChanlun/docs/chanlun/text/blog/'
exec(open('/tmp/vf2114c/spec.py',encoding='utf-8').read())
c=json.load(open('/tmp/vf2114c/cands.json',encoding='utf-8'))
_f={}
def L(f):
    if f not in _f: _f[f]=open(B+f,encoding='utf-8').read().split('\n')
    return _f[f]
def bnd(f):
    for i,l in enumerate(L(f),1):
        if '↑正文' in l: return i
NOTE2=re.compile(r'[（(]\s*(娇注|娇|注|备注)\s*[：:]|娇注|[（(]娇|后续走势为此类|5分中枢ZD')
K=lambda a:'%s:%d'%(a['file'][:3],a['line'])
AU={'master_body':'B','master_reply':'R','master_daily_commentary':'D','reader':'RD','editor_note':'ED','unclear':'UN'}
SY={'trend_formed_now':'F','trend_not_yet_or_needs_more':'N','can_still_be_overturned':'O','center_completion_rule':'C','abstract_definition':'A','other_relevant':'X'}
ZH={'B':'正','R':'复','D':'盘'}
gmap={}
for g,(lab,ks) in G.items():
    for k in ks.split():
        assert k not in gmap,k; gmap[k]=g
keys=[K(a) for a in c]; assert len(set(keys))==411
prob=[]
for k in keys:
    n=(k in IND)+(k in gmap)+(k in REJ)
    if n!=1: prob.append(('assign',k,n))
for k in list(IND)+list(gmap)+list(REJ):
    if k not in keys: prob.append(('unknown key',k))
def nb(s): return s.replace(' ',' ')
def chk(f,ln,frag):
    line=nb(L(f)[ln-1]); pos=0; ok=True
    for p in frag.split('…'):
        i=line.find(p,pos)
        if i<0: ok=False; break
        if NOTE2.search(p): ok=False
        pos=i+len(p)
    return ok
rows=[]; full=[]
for a in c:
    k=K(a); f=a['file']; ln=a['line']; line=L(f)[ln-1]
    q=a['quote']; verb = q in line or q in nb(line) or nb(q) in nb(line)
    if not verb: prob.append(('quote',k))
    au=AOVR.get(k,AU[a['author']]); sy=SOVR.get(k,SY[a['says']])
    dag='†' if (NOTE2.search(line) and au in 'BRD') else ''
    b=bnd(f)
    rec=dict(key=k,file=f,line=ln,quote=q,verbatim=verb,nbsp=(q not in line and verb),boundary=b,side=('无界线' if b is None else ('界前' if ln<b else '界后')),author=au,says=sy,inline_note_in_line=bool(dag),basis=a['attribution_basis'],state=a['state'],wording=a['wording'])
    if k in REJ: rec['verdict']='rejected: '+REJ[k]
    elif k in gmap: rec['verdict']='kept:'+gmap[k]; rows.append((f[:3],ln,au,sy,dag,None,None,gmap[k]))
    else:
        cls,frag,st=IND[k]; sy=cls or sy; rec['says']=sy
        if not chk(f,ln,frag): prob.append(('frag',k,frag))
        rec['verdict']='kept'; rec['key_fragment']=frag; rec['state_verified']=st or a['state']
        rows.append((f[:3],ln,au,sy,dag,frag,st,None))
    full.append(rec)
for k,(f,au,sy,frag,st,basis) in NEW.items():
    ln=int(k[4:]); line=L(f)[ln-1]
    if not chk(f,ln,frag): prob.append(('newfrag',k))
    dag='†' if NOTE2.search(line) else ''
    rows.append((f[:3],ln,au,sy,dag,frag,st,None))
    full.append(dict(key=k+'#verifier-added',file=f,line=ln,quote=frag,verbatim=True,author=au,says=sy,basis=basis,state=st,verdict='kept (added by verifier)',key_fragment=frag))
rows.sort(key=lambda r:(r[0],r[1]))
print('problems',prob)
ind=[r for r in rows if r[7] is None]; grp=[r for r in rows if r[7]]
out=[]
for r in ind:
    cell=r[5]+('｜'+r[6] if r[6] else '')
    out.append('|%s:%d|%s%s%s|%s|'%(r[0],r[1],ZH[r[2]],r[3],r[4],cell))
gout=[]
for g,(lab,ks) in G.items():
    mem=[r for r in grp if r[7]==g]
    DEF={'G1':'C','G2':'O','G3':'A','G4':'O','G5':'X','G6':'X'}[g]
    fm=lambda r:'%s:%d%s%s%s'%(r[0],r[1],ZH[r[2]],'' if r[3]==DEF else r[3],r[4])
    if g=='G5':
        tail=set(ks.split()[-7:]); a1=[r for r in mem if '%s:%d'%(r[0],r[1]) not in tail]; a2=[r for r in mem if '%s:%d'%(r[0],r[1]) in tail]
        s=' '.join(fm(r) for r in a1)+' ／线段类中枢类比：'+' '.join(fm(r) for r in a2)
    else:
        s=' '.join(fm(r) for r in mem)
    gout.append('|组%s|%d条·默认%s|%s：%s|'%(g[1],len(mem),DEF,lab,s))
table='|课:行|作·类|逐字关键句｜状态与核对注|\n|-|-|-|\n'+'\n'.join(out)+'\n'+'\n'.join(gout)
open('table.md','w',encoding='utf-8').write(table)
json.dump(full,open('verified.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print('ind',len(ind),'grp',len(grp),'table chars',len(table))
cs=collections.Counter(r[3] for r in rows); ca=collections.Counter(ZH[r[2]] for r in rows)
print(cs,ca,len(rows))
print(collections.Counter(r[7] for r in grp))
print('dagger',sum(1 for r in rows if r[4]))
