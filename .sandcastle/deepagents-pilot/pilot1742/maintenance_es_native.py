"""原生开发传输消费端；复用已验证归约器，仍不授予生产证据权限。

collector stdout专用管道调用 accept；任意EOF/解码/transport异常必须调用 lost。
此接口不启动collector/helper，无默认生产入口。fixture用同一协议但不构成kernel来源。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, TextIO

from .maintenance import evidence_write, token
from .maintenance_epoch import local_epoch
from .maintenance_es import EVENTS, AuditIdentity, Coverage, OfflineES, Peer


@dataclass
class Registration:
    nonce: str
    peer: Peer
    arm_sent: bool = False
    pid: int | None = None
    code: int | None = None
    bound: AuditIdentity | None = None
    waited: bool = False


class DevelopmentConsumer:
    """send写入同一collector的stdin，不将RPC字段视为内核身份认证。

    调用者须保持stdout管道来源与已核collector实例绑定。当前仅隔离开发账本，
    不提供fixture→生产可信来源转换，真实peer认证在C端LOCAL_PEERTOKEN+SecCode中。
    """

    def __init__(self, reducer: OfflineES, send: Callable[[str], None]):
        self.reducer = reducer
        self.send = send
        self.epoch: str | None = None
        self.registrations: dict[str, Registration] = {}
        self.failed = False

    def lost(self) -> None:
        self.failed = True
        if self.epoch is not None:
            self.reducer.lost(self.epoch, 'source_lost')

    def accept(self, record: dict) -> None:
        try:
            self._accept(record)
            self._progress()
        except BaseException:
            self.failed = True
            with evidence_write():
                self.lost()
            raise

    def _accept(self, record: dict) -> None:
        if self.failed:
            raise ValueError('native development session lost')
        kind = record.get('type')
        fields = {
            'source': {'type', 'epoch', 'protocol'}, 'event': {'type', 'event'},
            'register': {'type', 'resource', 'nonce', 'image', 'peer'},
            'started': {'type', 'resource', 'pid'}, 'waited': {'type', 'resource', 'pid', 'code'},
            'lost': {'type', 'epoch', 'reason'},
        }
        if kind not in fields or set(record) != fields[kind]:
            raise ValueError('non-whitelisted native record')
        if kind == 'source':
            if self.epoch is not None or record['protocol'] != 'macos-es-v1':
                raise ValueError('unexpected native source')
            self.epoch = token(record['epoch'])
            host, boot = local_epoch()
            # C only emits source after subscription/mute/signature checks. This is still offline trust.
            self.reducer.source(self.epoch, host, boot, Coverage(5, EVENTS, ()))
            return
        if self.epoch is None:
            raise ValueError('native source not initialized')
        if kind == 'event':
            self.reducer.ingest_wire(record['event'])
        elif kind == 'lost':
            if record['epoch'] != self.epoch:
                raise ValueError('wrong loss epoch')
            self.failed = True
            self.reducer.lost(self.epoch, record['reason'])
        elif kind == 'register':
            resource, nonce = token(record['resource']), token(record['nonce'])
            if resource in self.registrations:
                raise ValueError('duplicate native registration')
            peer = Peer(AuditIdentity(tuple(record['peer'])), record['image'])
            self.reducer.register_peer(resource, nonce, peer)
            self.registrations[resource] = Registration(nonce, peer)
        else:
            resource, pid = token(record['resource']), record['pid']
            registration = self.registrations[resource]
            if not registration.arm_sent or type(pid) is not int or pid <= 0:
                raise ValueError('unarmed helper result')
            if kind == 'started':
                if registration.pid is not None:
                    raise ValueError('duplicate primary result')
                registration.pid = pid
            else:
                code = record['code']
                if registration.pid != pid or registration.code is not None or type(code) is not int or not 0 <= code <= 255:
                    raise ValueError('unbound wait result')
                registration.code = code

    def _progress(self) -> None:
        if self.failed:
            return
        for resource, registration in self.registrations.items():
            if not registration.arm_sent:
                permit = self.reducer.arm(resource, registration.peer)
                if permit is None:
                    continue
                if not self.reducer.claim_launch(resource, permit, registration.peer):
                    raise ValueError('native permit already consumed')
                registration.arm_sent = True  # Before write: send error cannot authorize retransmission.
                self.send(f'ARM {resource} {registration.nonce} {permit}\n')
            if registration.pid is not None and registration.bound is None:
                with self.reducer.gate.tx() as db:
                    _, action = self.reducer._bound(db, resource)
                # START may beat ES FORK; wait for the exact helper parent edge, never infer from PID alone.
                candidates = [key for key, parent in action.parents.items()
                              if parent == action.root and int(key.split(':')[5]) == registration.pid]
                # EXEC also keeps parent edges. The original FORK identity is the first insertion.
                if candidates:
                    primary = AuditIdentity(tuple(map(int, candidates[0].split(':'))))
                    self.reducer.bind_primary(resource, registration.peer, primary)
                    registration.bound = primary
            if registration.code is not None and registration.bound is not None and not registration.waited:
                self.reducer.waited(resource, registration.peer, registration.bound, registration.code)
                registration.waited = True
                self.send(f'WAITED {resource} {registration.nonce}\n')


def consume_stream(consumer: DevelopmentConsumer, reader: TextIO, writer: TextIO) -> None:
    """仅消费已建立的专用管道；EOF/畸形/失败均撤销来源并关闭许可写端。"""
    try:
        while not consumer.failed:
            line = reader.readline(4097)
            if not line:
                break
            if len(line) > 4096 or not line.endswith('\n'):
                raise ValueError('incomplete native frame')
            record = json.loads(line)
            if type(record) is not dict:
                raise ValueError('invalid native record')
            consumer.accept(record)
    finally:
        try:
            consumer.lost()
        finally:
            writer.close()  # collector收到EOF；不发送信号给已派发helper/业务。


def scheduler_identity(library: str, socket_path: str, collector_requirement: str) -> AuditIdentity:
    """显式开发调用：本进程连接受管collector，原生层验证服务器后读取内核peer身份。"""
    import ctypes
    import os
    import sys

    if sys.platform != 'darwin':
        raise ValueError('native scheduler identity requires macOS')
    native = ctypes.CDLL(library)
    words = (ctypes.c_uint32 * 8)()
    native.scheduler_identity.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32)]
    native.scheduler_identity.restype = ctypes.c_int
    if native.scheduler_identity(os.fsencode(socket_path), os.fsencode(collector_requirement), words) != 0:
        raise ValueError('scheduler kernel identity unavailable')
    return AuditIdentity(tuple(words))
