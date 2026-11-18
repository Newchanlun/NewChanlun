"""仅限下述私有 Linux 容器。受管方与域用两个真实 UID，不触宿主路径。"""
import array, errno, json, os, socket, sys
from pathlib import Path
ROOT=Path('/tmp/ipc-proof')
ADDR=str(ROOT/'domain.sock')
def log(**x): print(json.dumps(x,ensure_ascii=False),flush=True)
def acquire(g):
    root=ROOT
    root.mkdir(mode=0o755,exist_ok=True)
    # 本单测调用顺序由外部控制器确认前代两个进程都已终止；
    # 非本代登记绝不替换。本段不是可部署清理工具。
    record=root/'registered.json'
    if g=='2':
        old=json.loads(record.read_text()); st=os.lstat(ADDR)
        assert old==[st.st_dev,st.st_ino,st.st_uid] and st.st_uid==os.geteuid()
        os.unlink(ADDR)
    with socket.socket(socket.AF_UNIX) as listener, socket.socket(socket.AF_UNIX) as ch:
        listener.bind(ADDR); os.chmod(ADDR,0o660); listener.listen(8)
        st=os.lstat(ADDR); record.write_text(json.dumps([st.st_dev,st.st_ino,st.st_uid]))
        ctl=str(root/('control.'+g))
        ch.bind(ctl); os.chmod(ctl,0o660); ch.listen(1)
        log(stage='published',generation=g,publisher_uid=os.geteuid())
        handoff,_=ch.accept()
        with handoff:
            fds=array.array('i',[listener.fileno()])
            assert handoff.sendmsg([b'F'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,fds)])==1
            assert handoff.recv(1)==b'A'
    # 此处不删应用端点，也不留任何 listener FD。
def worker(g):
    with socket.socket(socket.AF_UNIX) as ch:
        ch.connect(str(ROOT/('control.'+g)))
        ints=array.array('i')
        _,anc,flags,_=ch.recvmsg(1,socket.CMSG_SPACE(ints.itemsize))
        assert not flags
        for level,kind,value in anc:
            if (level,kind)==(socket.SOL_SOCKET,socket.SCM_RIGHTS):
                ints.frombytes(value[:len(value)//ints.itemsize*ints.itemsize])
        assert len(ints)==1
        listener=socket.socket(fileno=ints[0])
        assert listener.getsockname()==ADDR and listener.getsockopt(socket.SOL_SOCKET,socket.SO_ACCEPTCONN)
        ch.sendall(b'A')
    with listener:
        log(stage='worker',generation=g,worker_uid=os.geteuid(),pid=os.getpid())
        assert sys.stdin.readline().strip()=='accept-one'
        c,_=listener.accept()
        with c:
            body=c.recv(64)
            assert body==b'new'
            c.sendall(('from-'+g).encode())
        if g=='1':
            assert sys.stdin.readline().strip()=='exit'
def client():
    for name,act in [('create',lambda:(ROOT/'unsanctioned').touch()),
                     ('rename',lambda:os.rename(ADDR,ROOT/'replacement')),
                     ('unlink',lambda:os.unlink(ADDR))]:
        try: act()
        except OSError as e: assert e.errno in (errno.EACCES,errno.EPERM)
        else: raise AssertionError(name+' should be denied')
    with socket.socket(socket.AF_UNIX) as c:
        c.settimeout(5);c.connect(ADDR);c.sendall(b'new')
        log(stage='client',uid=os.geteuid(),namespace_writes='create/rename/unlink denied',reply=c.recv(64).decode())
def queued():
    with socket.socket(socket.AF_UNIX) as c:
        c.settimeout(10);c.connect(ADDR);c.sendall(b'old')
        log(stage='old-message-queued')
        try: x=c.recv(8)
        except ConnectionResetError: reason='ECONNRESET'
        else: assert not x;reason='EOF'
        log(stage='old-connection-ended',result=reason)
if __name__=='__main__':
    {'acquire':acquire,'worker':worker,'client':client,'queued':queued}[sys.argv[1]](*sys.argv[2:])
