"""只读内核 PID/出生身份，不读取 argv、环境、凭据或模型日志。"""
from __future__ import annotations

import ctypes
import errno
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class EndedProcess:
    birth: str


def collect(enumerate_pids: Callable[[], set[int]],
            read: Callable[[int], list | EndedProcess | None]) -> dict[int, list]:
    """退出读取必须经过后置枚举 fence；不是忽略 ENOENT 后接受原枚举。

    每次 fence 重新读在场身份，补入此间出生的进程（包括已退出父进程的
    孤儿）。成功读到的旧记录保留为保守上界，不能因下次枚举消失清除它。
    无需 PID 集合不变；最后一轮只要求 fence 内每个 PID 有身份/非执行态。
    连续三轮都有未读退出时拒绝证明，不无限等全机安静。
    """
    result: dict[int, list] = {}
    ended: dict[int, str] = {}
    for _ in range(3):
        missing = False
        for pid in sorted(enumerate_pids()):
            try:
                data = read(pid)
            except OSError as error:
                if error.errno not in (errno.ENOENT, errno.ESRCH):
                    raise
                missing = True
                continue
            if isinstance(data, EndedProcess):
                if pid in ended and ended[pid] != data.birth:
                    raise UnstableSnapshot('process_identity_changed')
                if pid in result and result[pid][0] != data.birth:
                    raise UnstableSnapshot('process_identity_changed')
                # 初见 zombie 前仍可能 fork；必须在其终态观察之后再枚举后代。
                missing |= pid not in ended
                ended[pid] = data.birth
                continue
            if data is not None:
                if pid in ended:
                    raise UnstableSnapshot('process_identity_changed')
                if pid in result and result[pid][0] != data[0]:
                    raise UnstableSnapshot('process_identity_changed')
                result[pid] = data
        if not missing:
            return result
    raise UnstableSnapshot('exit_fence_incomplete')


def snapshot() -> dict[int, list]:
    """同 UID 活跃身份的保守集合；权限/短读/身份错配仍拒绝。"""
    if sys.platform == 'darwin':
        lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        def enumerate_pids():
            ctypes.set_errno(0)
            size = lib.proc_listpids(4, os.getuid(), None, 0)
            if size <= 0:
                raise UnstableSnapshot(f'proc_listpids_size errno={ctypes.get_errno()}')
            buf = (ctypes.c_int * (size // 4 + 128))()
            ctypes.set_errno(0)
            count = lib.proc_listpids(4, os.getuid(), buf, ctypes.sizeof(buf))
            if count <= 0 or count >= ctypes.sizeof(buf):
                raise UnstableSnapshot(f'proc_listpids_incomplete errno={ctypes.get_errno()}')
            return {pid for pid in buf[:count // 4] if pid > 0}
        def read(pid):
            info = BSDInfo()
            ctypes.set_errno(0)
            got = lib.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
            number = ctypes.get_errno()
            if got == 0 and number == errno.ESRCH:
                raise ProcessLookupError(number, 'process_exited')
            if got != ctypes.sizeof(info):
                raise UnstableSnapshot(f'proc_pidinfo_size errno={number}')
            if info.pid != pid or info.uid != os.getuid():
                raise UnstableSnapshot('proc_pidinfo_identity')
            if info.status != 5:
                return [f'{pid}:{info.seconds}:{info.microseconds}', info.ppid]
            return EndedProcess(f'{pid}:{info.seconds}:{info.microseconds}')
        return collect(enumerate_pids, read)
    if sys.platform.startswith('linux'):
        def enumerate_pids():
            return {int(path.name) for path in Path('/proc').iterdir() if path.name.isdigit()}
        def read(pid):
            path = Path('/proc') / str(pid)
            # 目录 fd 绑定这一 incarnation，避免 stat(uid) 与 stat 文件跨 PID 复用。
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                if os.fstat(fd).st_uid != os.getuid():
                    return None
                stat_fd = os.open('stat', os.O_RDONLY, dir_fd=fd)
                with os.fdopen(stat_fd) as stream:
                    text = stream.read()
                if int(text.split('(', 1)[0]) != pid:
                    raise UnstableSnapshot('process_identity_changed')
                fields = text.rsplit(')', 1)[1].split()
                if fields[0] != 'Z':
                    return [f'{pid}:{fields[19]}', int(fields[1])]
                return EndedProcess(f'{pid}:{fields[19]}')
            finally:
                os.close(fd)
        return collect(enumerate_pids, read)
    raise UnstableSnapshot('unsupported process census')


def stable_snapshot() -> dict[int, list]:
    failures = []
    for _ in range(3):
        try:
            return snapshot()
        except UnstableSnapshot as error:
            failures.append(str(error))
        except OSError as error:
            failures.append(f'process_read errno={error.errno}')
        except (ValueError, IndexError):
            failures.append('process_record_invalid')
    raise UnstableSnapshot('process census incomplete: ' + '; '.join(failures))
