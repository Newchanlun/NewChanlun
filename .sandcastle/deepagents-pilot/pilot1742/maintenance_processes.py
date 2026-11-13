"""只读内核 PID/出生身份，不读取 argv、环境、凭据或模型日志。"""
import ctypes
import os
import sys
from pathlib import Path


class UnstableSnapshot(OSError):
    pass


class BSDInfo(ctypes.Structure):
    _fields_ = [('flags', ctypes.c_uint32), ('status', ctypes.c_uint32),
                ('xstatus', ctypes.c_uint32), ('pid', ctypes.c_uint32),
                ('ppid', ctypes.c_uint32), ('uid', ctypes.c_uint32),
                ('gids', ctypes.c_uint32 * 6), ('names', ctypes.c_char * 48),
                ('controls', ctypes.c_uint32 * 6),
                ('seconds', ctypes.c_uint64), ('microseconds', ctypes.c_uint64)]


def snapshot() -> dict[int, list]:
    """同 UID 的完整出生身份集合；枚举期间消失/不可读则拒绝本次证明。"""
    if sys.platform == 'darwin':
        lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        size = lib.proc_listpids(4, os.getuid(), None, 0)
        if size <= 0:
            raise UnstableSnapshot('process enumeration unavailable')
        buf = (ctypes.c_int * (size // 4 + 128))()
        count = lib.proc_listpids(4, os.getuid(), buf, ctypes.sizeof(buf))
        if count <= 0 or count >= ctypes.sizeof(buf):
            raise UnstableSnapshot('process enumeration truncated')
        result = {}
        for pid in buf[:count // 4]:
            if pid <= 0:
                continue
            info = BSDInfo()
            got = lib.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
            if got != ctypes.sizeof(info) or info.pid != pid or info.uid != os.getuid():
                raise UnstableSnapshot('process identity changed during enumeration')
            if info.status != 5:  # SZOMB：不能再 fork/执行请求。
                result[pid] = [f'{pid}:{info.seconds}:{info.microseconds}', info.ppid]
        return result
    if sys.platform.startswith('linux'):
        result = {}
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():
                continue
            if path.stat().st_uid != os.getuid():
                continue
            fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
            if fields[0] != 'Z':
                result[int(path.name)] = [f'{path.name}:{fields[19]}', int(fields[1])]
        return result
    raise UnstableSnapshot('unsupported process census')


def stable_snapshot() -> dict[int, list]:
    for _ in range(3):
        try:
            return snapshot()
        except (OSError, ValueError, IndexError):
            pass
    raise UnstableSnapshot('process census incomplete')
