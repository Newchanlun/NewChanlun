import random, json
UP,DOWN='U','D'
def U(d,lo,hi,s,e): return dict(d=d,lo=lo,hi=hi,s=s,e=e)
def from_endpoints(p):
    return [U(UP if b>a else DOWN,min(a,b),max(a,b),k*4,k*4+4) for k,(a,b) in enumerate(zip(p,p[1:]))]
def pos(u,zd,zg):
    if u['hi']<zd: return 'below'
    if u['hi']==zd: return 'touch'
    if u['lo']>zg: return 'above'
    if u['lo']==zg: return 'touch'
    return 'in'
def scan(units, complete=True):
    i=0; wins=[]
    while i+2<len(units):
        a,b,c=units[i:i+3]
        zd=max(a['lo'],b['lo'],c['lo']); zg=min(a['hi'],b['hi'],c['hi'])
        ok = zd<zg and (not complete or (a['d']!=b['d'] and b['d']!=c['d']))
        if not ok: i+=1; continue
        j=i+3
        while j<len(units) and pos(units[j],zd,zg) in ('in','touch'): j+=1
        wins.append(dict(seed=i,exit=j,zd=zd,zg=zg,up=(j-i)>=9))
        i = j+1 if j<len(units) else j
    return wins
def joint(zd,zg,prev,cur):
    p=pos(cur,zd,zg)
    if p not in('above','below'): return 'NotOutside'
    side = UP if p=='above' else DOWN
    if cur['d']==side: return 'BreakUnitOutward'
    if prev['d']!=side: return 'DirectionNotAlternating'
    if pos(prev,zd,zg) in ('above','below'): return 'PrevNotOverlap'
    conn = prev['e']==cur['s'] and (prev['hi']==cur['hi'] if side==UP else prev['lo']==cur['lo'])
    return 'Proven' if conn else 'JointNotConnected'
def witnesses(units,complete=True):
    out=[]; poisoned=None
    wins=scan(units,complete)
    for k,w in enumerate(wins):
        if w['exit']>=len(units): out.append('Open'); continue
        jr=joint(w['zd'],w['zg'],units[w['exit']-1],units[w['exit']])
        if poisoned is not None: r='UpstreamUnproven(%d)'%poisoned
        elif w['up']: r='UpgradePending'
        else: r=jr
        if jr!='Proven' and poisoned is None: poisoned=k
        out.append(r)
    return wins,out
if __name__=='__main__':
    UPp=[10,40,20,35,30,38,21,25,5,15,2,12,4,9,6]
    for k in (8,10,12):
        u=from_endpoints(UPp[:k+2]); print('UP K%d'%k, witnesses(u))
    dn=[45-p for p in UPp]
    print('DOWN K8', witnesses(from_endpoints(dn[:10])))
    # outward break
    base=[U(UP,10,40,0,4),U(DOWN,20,40,4,8),U(UP,20,35,8,12),U(DOWN,30,37,12,16)]
    print('outward', witnesses(base+[U(UP,36,50,16,20)]))
    print('outward+return', witnesses(base+[U(UP,36,50,16,20),U(DOWN,33,50,20,24)]))
    # case X
    cx=[U(UP,10,40,0,4),U(DOWN,20,40,4,8),U(UP,20,35,8,12),U(DOWN,25,36,12,16),U(UP,22,45,16,20),U(DOWN,38,50,20,24)]
    print('caseX', witnesses(cx))
    # tangent
    tg=[U(UP,10,40,0,4),U(DOWN,20,40,4,8),U(UP,20,35,8,12),U(DOWN,25,35,12,16),U(UP,25,45,16,20),U(DOWN,35,45,20,24)]
    print('tangent', witnesses(tg))
    # real fixture
    d=json.load(open('/tmp/r5fx.json'))
    ru=[U(UP if x['dir']=='UP' else DOWN,x['lo'],x['hi'],x['start_index'],x['end_index']) for x in d['tower_units']]
    print('real', witnesses(ru))
    j=[(a['hi']==b['hi']) if a['d']==UP else (a['lo']==b['lo']) for a,b in zip(ru,ru[1:])]
    print('real joints connected', j, [a['e']==b['s'] for a,b in zip(ru,ru[1:])])
    # property on connected alternating
    rnd=random.Random(7); tot=0; bad=0; upg=0
    for t in range(20000):
        p=[50]
        for k in range(rnd.randint(4,40)):
            step=rnd.randint(1,9)+(15 if rnd.randint(0,6)==0 else 0)
            p.append(p[-1]+step if k%2==0 else p[-1]-step)
        u=from_endpoints(p); wins,ws=witnesses(u)
        for w,r in zip(wins,ws):
            if r=='Open': continue
            tot+=1
            if r=='UpgradePending': upg+=1
            elif r!='Proven': bad+=1
    print('prop settled',tot,'upgraded',upg,'non-proven',bad)
    # poison example: outward break first, then a connected textbook window
    tail=[55,60,90,70,85,80,88,71,75,55,65]  # shift of UP stream +50, starting after
    pre=base+[U(UP,36,50,16,20)]
    t=from_endpoints([p+100 for p in UPp[:10]])
    for x in t: x['s']+=20; x['e']+=20
    print('poison', witnesses(pre+t))
    print('control', witnesses(from_endpoints(UPp[:10])+ [dict(x) for x in t]))
