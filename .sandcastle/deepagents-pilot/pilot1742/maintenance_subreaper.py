"""Linux 本机 CLI 域：派发前成为 subreaper，内核收养逃逸/孤儿后代。"""
import ctypes
import os
import signal
import sys
from pathlib import Path

from pilot1742.maintenance_processes import UnstableSnapshot

KIND = 'linux-subreaper-v1'


def birth() -> str:
    text = Path('/proc/self/stat').read_text()
    return f'{os.getpid()}:{text.rsplit(")", 1)[1].split()[19]}'


def enabled() -> bool:
    flag = ctypes.c_int()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(37, ctypes.byref(flag), 0, 0, 0) != 0:  # PR_GET_CHILD_SUBREAPER
        raise UnstableSnapshot(f'subreaper_get errno={ctypes.get_errno()}')
    return flag.value == 1


def empty() -> bool:
    """只供专用单线程监督器调用；回收已结束后代，不杀活进程。"""
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return True  # ECHILD：内核确认域内没有可继续 fork 的执行根。
        if pid == 0:
            return False


def bind() -> dict:
    if not sys.platform.startswith('linux'):
        raise UnstableSnapshot('subreaper_unsupported')
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0 or not enabled():  # PR_SET_CHILD_SUBREAPER
        raise UnstableSnapshot(f'subreaper_set errno={ctypes.get_errno()}')
    if not empty():
        raise UnstableSnapshot('subreaper_preexisting_children')
    return dict(kind=KIND, pid=os.getpid(), birth=birth())


def idle(domain: dict) -> bool:
    # 外部 status/reconcile 不得用自己的 ECHILD 替别人签发证明。
    return (sys.platform.startswith('linux') and domain.get('pid') == os.getpid()
            and domain.get('birth') == birth() and enabled() and empty())


def wait_remaining() -> None:
    while True:
        try:
            os.waitpid(-1, 0)
        except ChildProcessError:
            return
