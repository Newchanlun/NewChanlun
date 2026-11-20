import json,re,sys
B='/home/workspace/src/NewChanlun/docs/chanlun/text/blog/'
c=json.load(open('/tmp/vf2114c/cands.json',encoding='utf-8'))
files={}
def L(f):
    if f not in files: files[f]=open(B+f,encoding='utf-8').read().split('\n')
    return files[f]
def boundary(f):
    for i,l in enumerate(L(f),1):
        if '↑正文' in l: return i
    return None
STRUCT=re.compile(r'缠中说[禅缠]|匿名\]|\d{4}-\s?\d{2}-\s?\d{2}|^\s*[=\-]{2,}\s*$|每日解盘|附录|转载|^作者')
NOTE2=re.compile(r'[（(]\s*(娇注|娇|注)\s*[：:]|娇注|[（(]娇')
START=re.compile(r'^\s*[（(]?\s*(娇注|娇|注)\s*[：:]')
def t(s,n): return s if len(s)<=n else s[:n]+'…'
lo=int(sys.argv[1]); hi=int(sys.argv[2])
c.sort(key=lambda a:(a['file'],a['line']))
for a in c:
    num=int(a['file'][:3])
    if not(lo<=num<=hi): continue
    f=a['file']; ln=a['line']; q=a['quote']; ls=L(f); b=boundary(f)
    line=ls[ln-1] if ln<=len(ls) else ''
    flags=[]
    pos=line.find(q)
    if pos<0 and q.replace(' ','\u00a0') in line:
        q=q.replace(' ','\u00a0'); pos=line.find(q); flags.append('NBSP')
    if pos<0:
        found=[i for i,l in enumerate(ls,1) if q in l]
        flags.append('NOTINLINE found_at=%s'%found)
    else:
        others=[i for i,l in enumerate(ls,1) if q in l and i!=ln]
        if others: flags.append('also@%s'%others)
    side='NOB' if b is None else ('pre' if ln<b else 'post')
    if START.search(line): flags.append('STARTNOTE')
    if NOTE2.search(q): flags.append('QNOTE')
    notes=['%d:%s'%(m.start(),t(line[m.start():m.start()+24],24)) for m in NOTE2.finditer(line)]
    au={'master_body':'B','master_reply':'R','master_daily_commentary':'D','reader':'RD','editor_note':'ED','unclear':'UN'}[a['author']]
    sy={'trend_formed_now':'F','trend_not_yet_or_needs_more':'N','can_still_be_overturned':'O','center_completion_rule':'C','abstract_definition':'A','other_relevant':'X'}[a['says']]
    print('## %s:%d %s b=%s %s/%s len=%d %s'%(f[:3],ln,side,b,au,sy,len(line),' '.join(flags)))
    full = len(sys.argv)>3
    print(' Q: %s'%(q if full or sy in 'FN' else t(q,60)))
    if side!='pre' or flags or notes:
        if pos>=0:
            pre=line[:pos]
            if pre: print(' pre[%d]: %s ‖ %s'%(pos,t(pre,30) if len(pre)>90 else '', pre[-60:]))
            if line[pos+len(q):]: print(' post: %s'%t(line[pos+len(q):],40))
        else:
            print(' LINE: %s'%t(line,160))
    if notes: print(' notes(q=%d..%d): %s'%(pos,pos+len(q),notes))
    if side!='pre':
        ctx=[]; i=ln-1
        while i>=1 and len(ctx)<3 and ln-i<80:
            l=ls[i-1]
            if STRUCT.search(l): ctx.append('%d:%s'%(i,t(l.strip(),34)))
            i-=1
        nxt=''
        for j in range(ln+1,min(len(ls),ln+12)+1):
            if STRUCT.search(ls[j-1]): nxt='%d:%s'%(j,t(ls[j-1].strip(),36)); break
        print(' up: '+' | '.join(ctx)); print(' dn: '+nxt)
