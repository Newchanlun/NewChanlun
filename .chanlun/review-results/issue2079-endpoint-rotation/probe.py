"""仅验证 Unix listener FD 跨进程交接；不模拟业务数据库或部署授权。"""
import errno
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

def line(**values):
    print(json.dumps(values, ensure_ascii=False, sort_keys=True), flush=True)

def worker():
    with socket.socket(fileno=int(sys.argv[2])) as sock:
        assert sock.family == socket.AF_UNIX
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_STREAM
        if platform.system() == 'Linux':
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)
        assert sock.getsockname() == sys.argv[3]
        line(pid=os.getpid())
        conn, _ = sock.accept()
        with conn:
            conn.settimeout(5)
            data = conn.recv(64)
            conn.sendall(sys.argv[4].encode() + b":" + data)

def supervisor():
    fd = int(sys.argv[2])
    p = subprocess.run([sys.executable, __file__, 'worker', *sys.argv[2:]],
                       pass_fds=(fd,), timeout=12)
    sys.exit(p.returncode)

def connect(path):
    s=socket.socket(socket.AF_UNIX)
    s.settimeout(5)
    s.connect(path)
    return s

def keeper():
    with tempfile.TemporaryDirectory(dir='/tmp') as d:
        path = str(Path(d) / 'service.sock')
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(path)
            listener.listen(8)
            ident=(os.lstat(path).st_dev, os.lstat(path).st_ino)
            os_pid=platform.system()
            line(os=os_pid,phase='托管端创建实名监听器',owner=os.getpid(),path=path,identity=ident)
            with socket.socket(socket.AF_UNIX) as second:
                try: second.bind(path)
                except OSError as e: assert e.errno == errno.EADDRINUSE
                else: raise AssertionError('duplicate bind')
            line(phase='原路径仍在，不能另行 bind')
            def spawn(generation):
                fd=listener.fileno()
                p=subprocess.Popen([sys.executable,__file__,'supervisor',str(fd),path,generation],
                                   pass_fds=(fd,),stdout=subprocess.PIPE,text=True)
                return p,json.loads(p.stdout.readline())['pid']
            p1,w1 = spawn('一代')
            with connect(path) as c:
                c.sendall(b'one'); assert c.recv(64)=='一代:one'.encode()
            assert p1.wait(timeout=5)==0
            # 两层应用进程都已退出。独立的托管方仍持监听 FD；同一路径仍可建连排队。
            with connect(path) as queued:
                queued.sendall(b'queued-before-next-generation')
                p2,w2 = spawn('二代')
                recv=queued.recv(80)
                assert recv=='二代:queued-before-next-generation'.encode()
            assert p2.wait(timeout=5)==0 and w1!=w2 and p1.pid!=p2.pid
            assert ident==(os.lstat(path).st_dev,os.lstat(path).st_ino)
            line(phase='两层新进程接回同一监听器；上一代空窗的原始请求也到了新进程',
                 launchers=[p1.pid,p2.pid],workers=[w1,w2],same_path_inode=True,received=recv.decode())
        # 无存活监听句柄，名字仍在；生产候选不得拿这个事实擅自清理。
        assert os.path.exists(path)
        with socket.socket(socket.AF_UNIX) as s:
            try: s.bind(path)
            except OSError as e: assert e.errno==errno.EADDRINUSE
            else: raise AssertionError('name unexpectedly freed')
        line(phase='最后持有者也退出则路径仍在；不承诺托管者全失后的自动接管')
if __name__=='__main__':
    {'keeper':keeper,'supervisor':supervisor,'worker':worker}[sys.argv[1]]()
