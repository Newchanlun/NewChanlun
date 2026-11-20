#!/usr/bin/env python3
"""Probe for #2079 direction brief: kernel facts behind 'move aside, verify the moved object, never delete'.
Run: python3 -I probe.py <empty-workdir>
"""
import ctypes, errno, fcntl, os, signal, socket, struct, sys, time, platform

libc = ctypes.CDLL(None, use_errno=True)
SYS_renameat2 = 316  # x86_64
SYS_openat2 = 437
RENAME_NOREPLACE = 1
RESOLVE_NO_SYMLINKS = 0x04
AT_FDCWD = -100

def renameat2(dfd, old, new, flags):
    r = libc.syscall(SYS_renameat2, dfd, old.encode(), dfd, new.encode(), flags)
    return 0 if r == 0 else -ctypes.get_errno()

def openat2_nosym(path):
    how = struct.pack("QQQ", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC, 0, RESOLVE_NO_SYMLINKS)
    r = libc.syscall(SYS_openat2, AT_FDCWD, path.encode(), how, len(how))
    return r if r >= 0 else -ctypes.get_errno()

def conn(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.setblocking(False)
    try:
        s.connect(path)
        return "connected"
    except OSError as e:
        return errno.errorcode.get(e.errno, str(e.errno))
    finally:
        s.close()

def ident(st):
    return (st.st_dev, st.st_ino, st.st_ctime_ns)

def child_listener(path, lockpath, ready_w):
    pid = os.fork()
    if pid:
        return pid
    lf = os.open(lockpath, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(path); s.listen(4)
    os.write(ready_w, b"1")
    while True:
        try:
            c, _ = s.accept(); c.send(b"ok"); c.close()
        except Exception:
            pass

def out(k, v):
    print(f"{k}={v}")

def main():
    wd = os.path.realpath(sys.argv[1])
    out("uname", platform.release()); out("machine", platform.machine())
    d = os.path.join(wd, "ep"); os.mkdir(d, 0o700)
    k = os.path.join(d, "e.socket"); lock = os.path.join(wd, "e.db.writer.lock")
    r, w = os.pipe()
    pid = child_listener(k, lock, w); os.read(r, 1)
    out("live_connect", conn(k))
    lf = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB); out("live_lock", "acquired")
    except OSError as e:
        out("live_lock", errno.errorcode[e.errno])
    bound = ident(os.lstat(k))
    os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
    fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB); out("dead_lock", "acquired")
    out("dead_path_exists", os.path.lexists(k)); out("dead_connect", conn(k))
    s = socket.socket(socket.AF_UNIX); 
    try: s.bind(k); out("bind_on_residue", "ok")
    except OSError as e: out("bind_on_residue", errno.errorcode[e.errno])
    s.close()
    # 1. directory fd without symlinks
    dfd = openat2_nosym(d); out("openat2_nosymlinks_plain", "fd" if dfd >= 0 else errno.errorcode[-dfd])
    os.symlink(d, os.path.join(wd, "link")); 
    bad = openat2_nosym(os.path.join(wd, "link")); out("openat2_nosymlinks_on_symlink", "fd" if bad >= 0 else errno.errorcode[-bad])
    # 2. pin the residue with O_PATH and probe it through the pin
    pin = os.open("e.socket", os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dfd)
    out("pin_identity_equals_bound", ident(os.fstat(pin)) == bound)
    out("dead_connect_via_pin", conn(f"/proc/self/fd/{pin}"))
    # 3. move aside with NOREPLACE; identity of the moved object
    ino = os.fstat(pin).st_ino
    retired = f"e.socket.retired.{ino}"
    out("move_aside", renameat2(dfd, "e.socket", retired, RENAME_NOREPLACE))
    st = os.stat(retired, dir_fd=dfd, follow_symlinks=False)
    out("moved_dev_ino_equal_pin", (st.st_dev, st.st_ino) == (os.fstat(pin).st_dev, os.fstat(pin).st_ino))
    out("moved_ctime_changed", st.st_ctime_ns != bound[2])
    out("k_absent_after_move", not os.path.lexists(k))
    # 4. bind relative to the verified directory fd
    s2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s2.bind(f"/proc/self/fd/{dfd}/e.socket"); s2.listen(4)
    out("bind_via_dirfd_creates_k", os.path.lexists(k)); out("new_listener_connect_by_path", conn(k))
    out("retired_still_present", os.path.lexists(os.path.join(d, retired)))
    s2.close(); os.unlink(k); os.close(pin)
    # 5. inode-number reuse without a pin, and none with a pin
    a = socket.socket(socket.AF_UNIX); a.bind(k); i1 = os.lstat(k).st_ino; a.close(); os.unlink(k)
    b = socket.socket(socket.AF_UNIX); b.bind(k); i2 = os.lstat(k).st_ino
    out("ino_reused_without_pin", i1 == i2)
    pin2 = os.open(k, os.O_PATH | os.O_NOFOLLOW); b.close(); os.unlink(k)
    c = socket.socket(socket.AF_UNIX); c.bind(k); i3 = os.lstat(k).st_ino; c.close(); os.unlink(k)
    out("ino_reused_with_pin", i2 == i3); os.close(pin2)
    # 6. SAFE-RACE: competitor swaps in a LIVE socket between pre-verify and move
    r2, w2 = os.pipe(); lock2 = os.path.join(wd, "x.lock")
    p1 = child_listener(k, lock2, w2); os.read(r2, 1); os.kill(p1, signal.SIGKILL); os.waitpid(p1, 0)
    pin3 = os.open("e.socket", os.O_PATH | os.O_NOFOLLOW, dir_fd=dfd)          # pre-verify pins my dead residue
    pre = os.fstat(pin3); out("race_pre_verify_dead", conn(f"/proc/self/fd/{pin3}"))
    os.unlink(k)                                                              # competitor (same UID, ignores contract)
    r3, w3 = os.pipe(); p2 = child_listener(k, os.path.join(wd, "y.lock"), w3); os.read(r3, 1)
    comp = os.lstat(k)
    name = f"e.socket.retired.{pre.st_ino}"
    out("race_move_aside", renameat2(dfd, "e.socket", name, RENAME_NOREPLACE))
    moved = os.stat(name, dir_fd=dfd, follow_symlinks=False)
    same = (moved.st_dev, moved.st_ino) == (pre.st_dev, pre.st_ino)
    out("race_post_verify_same_object", same)
    if not same:
        out("race_put_back", renameat2(dfd, name, "e.socket", RENAME_NOREPLACE))
    out("race_competitor_object_kept", (os.lstat(k).st_dev, os.lstat(k).st_ino) == (comp.st_dev, comp.st_ino))
    out("race_competitor_still_answers", conn(k))
    os.kill(p2, signal.SIGKILL); os.waitpid(p2, 0)
    # 7. NOREPLACE refuses when the retired name is taken
    open(os.path.join(d, "taken"), "w").close()
    out("noreplace_on_existing", errno.errorcode.get(-renameat2(dfd, "e.socket", "taken", RENAME_NOREPLACE)))
    # 8. SIGSTOP and full backlog are not ECONNREFUSED
    os.unlink(k); r4, w4 = os.pipe(); p3 = child_listener(k, os.path.join(wd, "z.lock"), w4); os.read(r4, 1)
    os.kill(p3, signal.SIGSTOP); time.sleep(0.1)
    res = [conn(k) for _ in range(12)]
    out("stopped_connect_results", ",".join(sorted(set(res))))
    os.kill(p3, signal.SIGKILL); os.waitpid(p3, 0)

main()
