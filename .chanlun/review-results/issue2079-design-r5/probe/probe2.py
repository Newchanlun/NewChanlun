import os, socket, sys, errno
wd = sys.argv[1]; k = os.path.join(wd, "live.sock")
if os.path.lexists(k): os.unlink(k)
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.bind(k); s.listen(2)
pin = os.open(k, os.O_PATH | os.O_NOFOLLOW)
c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); c.setblocking(False)
try:
    c.connect(f"/proc/self/fd/{pin}"); print("live_connect_via_pin=connected")
except OSError as e:
    print("live_connect_via_pin=" + errno.errorcode.get(e.errno, str(e.errno)))
