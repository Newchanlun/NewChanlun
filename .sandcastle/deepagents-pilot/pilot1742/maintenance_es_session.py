"""显式原生ES会话；签名/root peer认证之后才绑定原准入resource。默认不启用。"""
from __future__ import annotations

import ctypes
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import TextIO

from .maintenance import Gate, evidence_write, identity, now, token
from .maintenance_epoch import local_epoch
from .maintenance_es import Action, AuditIdentity, Coverage, OfflineES, Source
from .maintenance_es_native import DevelopmentConsumer

# Only bounds evidence transport after real helper wait AND ES process closure.
# Expiry revokes the session; it never supplies wait/closure evidence.
WAIT_EVIDENCE_SECONDS = 5.0

def protected_file(path: str) -> Path:
    """信任配置与可加载代码必须在不可由业务用户改写的root路径中。"""
    target = Path(path)
    if not target.is_absolute():
        raise ValueError('absolute managed path required')
    for part in (target, *target.parents):
        metadata = part.lstat()
        if stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError('unprotected managed path')
    if not stat.S_ISREG(target.stat().st_mode):
        raise ValueError('managed regular file required')
    return target


def verify_artifact(path: str, requirement_path: str) -> str:
    artifact = protected_file(path)
    requirement = protected_file(requirement_path).read_text()
    if not requirement or len(requirement) > 4095 or '\0' in requirement:
        raise ValueError('invalid signing requirement')
    checked = subprocess.run(['/usr/bin/codesign', '--verify', '--strict', '-R', requirement, str(artifact)],
                             capture_output=True, check=False)
    metadata = subprocess.run(['/usr/bin/codesign', '--display', '--verbose=2', str(artifact)],
                              capture_output=True, check=False)
    # Do not expose signature diagnostics or reflect free-text into the ledger.
    if checked.returncode or metadata.returncode or b'flags=' not in metadata.stderr or b'adhoc' in metadata.stderr:
        raise ValueError('managed signature unverified')
    return str(artifact)


class VerifiedChannel:
    """Only connect constructs this object; no trust/fixture/production boolean."""
    socket: socket.socket
    reader: TextIO
    config: dict[str, str]
    parent: AuditIdentity
    epoch: str

    def __new__(cls, *args, **kwargs):
        raise TypeError('use authenticated native connection')

    @classmethod
    def connect(cls, config_path: Path, resource: str, nonce: str):
        if sys.platform != 'darwin':
            raise ValueError('native ES requires macOS')
        config = json.loads(protected_file(str(config_path)).read_text())
        if set(config) != {'library', 'library_requirement', 'collector_requirement', 'helper', 'helper_requirement', 'socket', 'image'}:
            raise ValueError('invalid native configuration')
        if any(type(v) is not str for v in config.values()):
            raise ValueError('invalid native configuration values')
        token(config['image'])
        library = verify_artifact(config['library'], config['library_requirement'])
        config['helper'] = verify_artifact(config['helper'], config['helper_requirement'])
        protected_file(config['collector_requirement'])
        native = ctypes.CDLL(library)
        native.session_connect.argtypes = [ctypes.c_char_p] * 5
        native.session_connect.restype = ctypes.c_int
        fd = native.session_connect(*(os.fsencode(x) for x in
                                    (config['socket'], config['collector_requirement'], resource, nonce, config['image'])))
        if fd < 0:
            raise ValueError('collector kernel peer or signature unavailable')
        channel = object.__new__(cls)
        channel.socket = socket.socket(fileno=fd)
        channel.socket.settimeout(5)
        channel.reader = channel.socket.makefile('r', encoding='ascii', errors='strict')
        channel.config = config
        try:
            record = channel.read()
            if set(record) != {'type', 'epoch', 'protocol', 'parent'} or record['type'] != 'session' or record['protocol'] != 'macos-es-v1':
                raise ValueError('managed session unavailable')
            channel.parent = AuditIdentity(tuple(record['parent']))
            if channel.parent.words[5] != os.getpid() or channel.parent.words[1] != os.geteuid():
                raise ValueError('wrong scheduler kernel peer')
            channel.epoch = token(record['epoch'])
            channel.socket.settimeout(None)
            return channel
        except BaseException:
            channel.close()
            raise

    def read(self) -> dict:
        line = self.reader.readline(4097)
        if not line or len(line) > 4096 or not line.endswith('\n'):
            raise ValueError('native stream ended or truncated')
        record = json.loads(line)
        if type(record) is not dict:
            raise ValueError('invalid native frame')
        return record

    def send(self, message: str) -> None:
        self.socket.sendall(message.encode('ascii'))

    def shutdown(self) -> None:
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def close(self) -> None:
        self.shutdown()
        self.reader.close()
        self.socket.close()


class BoundSession(OfflineES):
    """Shared reserved-resource protocol. Its default trust remains offline."""
    expected_trust = 'offline'

    def __init__(self, gate: Gate, channel):
        self.channel = channel
        super().__init__(gate)

    def prepare_resource(self, resource: str, nonce: str) -> None:
        """Bind exactly one unused reservation of an already admitted local action."""
        host, boot = local_epoch()
        with self.gate.tx() as db:
            source = self._source(db, self.channel.epoch)
            row = db.execute('SELECT local_resources.*,jobs.owner,jobs.state,local_actions.host AS action_host,'
                             'local_actions.boot AS action_boot FROM local_resources JOIN jobs ON jobs.id=local_resources.job '
                             'JOIN local_actions ON local_actions.job=jobs.id WHERE local_resources.id=?', (token(resource),)).fetchone()
            if (row is None or row['pid'] != os.getpid() or row['start'] != identity(os.getpid()) or row['state'] != 'active' or
                    (row['action_host'], row['action_boot']) != (host, boot) or not source.ready or source.trust != self.expected_trust):
                raise ValueError('unused current local reservation required')
            self.gate._owner(db, row['owner'])
            if db.execute('SELECT 1 FROM local_resource_not_started WHERE resource=?', (resource,)).fetchone():
                raise ValueError('resource dispatch cancelled')
            if db.execute('SELECT 1 FROM action_exits WHERE job=?', (row['job'],)).fetchone():
                raise ValueError('local action already returned')
            if db.execute(f'SELECT 1 FROM {self.action_table} WHERE resource=? OR nonce=?', (resource, token(nonce))).fetchone():
                raise ValueError('old ES action cannot be reattached')
            # SESSION is authenticated and established before this new helper is spawned.
            action = Action(resource, row['job'], source.epoch, nonce, self.channel.parent.key,
                            self.channel.config['image'], source.last if source.last is not None else -1)
            db.execute('UPDATE local_resources SET host=?,boot=?,pid=?,start=?,sid=? WHERE id=?',
                       (host, boot, os.getpid(), identity(os.getpid()), os.getsid(0), resource))
            db.execute('INSERT INTO local_resource_domains VALUES(?,?,?,NULL)',
                       (resource, json.dumps({'kind': 'macos-es-v1', 'epoch': source.epoch}), self.channel.parent.key))
            self._save(db, source, [action])
            self._log(db, 'native-prepare', {'resource': resource, 'job': row['job'], 'epoch': source.epoch})

    def prepare(self, *args, **kwargs):
        raise ValueError('native sessions require original reserved resource')

    def launch(self, *args, **kwargs):
        raise ValueError('native dispatch uses signed helper only')

class NativeES(BoundSession):
    """Only authenticated native channels can commit closure into the original Gate."""
    source_table = "native_es_sources"
    action_table = "native_es_actions"
    audit_table = "native_es_audit"
    expected_trust = 'native'

    def __init__(self, gate: Gate, channel: VerifiedChannel):
        if type(channel) is not VerifiedChannel:
            raise ValueError('authenticated native channel required')
        self.channel = channel
        self.gate = gate
        self.current = None
        self.revoked = {}
        self._schema()

    def source(self, epoch: str, host: str, boot: str, coverage: Coverage) -> None:
        if epoch != self.channel.epoch or (host, boot) != local_epoch() or not coverage.ready() or self.current is not None:
            raise ValueError('native source binding mismatch')
        with self.gate.tx() as db:
            if db.execute('SELECT 1 FROM native_es_sources WHERE epoch=?', (epoch,)).fetchone():
                raise ValueError('native epoch cannot be reopened')
            source = Source(epoch, host, boot, True, trust='native')
            self._save(db, source, [])
            self._log(db, 'native-session', {'epoch': epoch, 'parent': self.channel.parent.key})
        self.current = epoch

    def status(self, resource: str) -> dict:
        report = super().status(resource)
        with self.gate.tx() as db:
            sealed = db.execute('SELECT sealed_at FROM local_resource_domains WHERE resource=?', (resource,)).fetchone()
        phase = report.pop('offline_phase')
        return dict(report, phase=phase, trust='native', production_accepted=bool(sealed and sealed[0]))

    def seal(self, resource: str) -> bool:
        return settle_native_resource(self.gate, resource)


def settle_native_resource(gate: Gate, resource: str) -> bool:
    """Consume persisted authenticated closure, including after consumer exit. Never reopen a source."""
    host, boot = local_epoch()
    with gate.tx() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='native_es_actions'").fetchone():
            return False
        record = db.execute('SELECT data FROM native_es_actions WHERE resource=?', (token(resource),)).fetchone()
        if record is None:
            return False
        action = Action(**json.loads(record[0]))
        source = NativeES._source(db, action.epoch)
        row = db.execute('SELECT * FROM local_resources WHERE id=?', (resource,)).fetchone()
        domain = db.execute('SELECT * FROM local_resource_domains WHERE resource=?', (resource,)).fetchone()
        binding = db.execute('SELECT data FROM bindings WHERE job=?', (action.job,)).fetchone()
        if (row is None or domain is None or source.trust != 'native' or (source.host, source.boot) != (host, boot)
                or (row['host'], row['boot']) != (host, boot) or row['job'] != action.job or action.unknown
                or not action.claimed or action.closed_seq is None or action.code is None or action.primary is None
                or action.live or action.root is None or action.permit is None or action.root != action.peer
                or action.parents.get(action.primary) != action.root or int(action.parent.split(':')[5]) != row['pid']
                or domain['supervisor'] != action.parent
                or json.loads(domain['baseline']) != {'kind': 'macos-es-v1', 'epoch': action.epoch}):
            return False
        snapshot = record[0]
        binding_data = binding[0] if binding else None
    if binding_data is not None:
        try:
            if not gate._resources_idle(json.loads(binding_data), [], set()):
                return False
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            return False
    with gate.tx() as db:
        current = db.execute('SELECT data FROM native_es_actions WHERE resource=?', (resource,)).fetchone()
        current_binding = db.execute('SELECT data FROM bindings WHERE job=?', (action.job,)).fetchone()
        if current is None or current[0] != snapshot or (current_binding[0] if current_binding else None) != binding_data:
            return False
        current_domain = db.execute('SELECT * FROM local_resource_domains WHERE resource=?', (resource,)).fetchone()
        if current_domain is None or current_domain['baseline'] != domain['baseline'] or current_domain['supervisor'] != domain['supervisor']:
            return False
        if current_domain['sealed_at'] is None:
            NativeES._log(db, 'native-closure-consumed', {'resource': resource, 'epoch': action.epoch, 'closed_seq': action.closed_seq})
        db.execute('UPDATE local_resources SET child_pid=?,code=?,waited_at=COALESCE(waited_at,?) WHERE id=?',
                   (int(action.primary.split(':')[5]), action.code, now(), resource))
        db.execute('UPDATE local_resource_domains SET sealed_at=COALESCE(sealed_at,?) WHERE resource=?', (now(), resource))
    return True


def run(args, command: list[str]) -> int:
    """Explicit local-command entry. Never falls back to snapshot or unsupervised spawn."""
    resource, nonce = token(args.resource), uuid.uuid4().hex
    received: list[int] = []
    old = {signum: signal.signal(signum, lambda signum, frame: received.append(signum))
           for signum in (signal.SIGTERM, signal.SIGINT)}
    channel = None
    try:
        os.setsid()
        gate = Gate(args.root)
        gate.bind_local_resource_identity(resource)
        try:
            channel = VerifiedChannel.connect(args.es_config, resource, nonce)
            reducer = NativeES(gate, channel)
        except Exception:
            with evidence_write():
                gate.local_resource_not_started(resource)
            raise
        return _run_session(reducer, channel, resource, nonce, command, received)
    finally:
        if channel is not None:
            with evidence_write():
                channel.close()
        for signum, handler in old.items():
            signal.signal(signum, handler)


def _run_session(reducer, channel, resource: str, nonce: str, command: list[str], received: list[int] | None = None) -> int:
    """Shared orchestration; offline tests use OfflineES, never a VerifiedChannel."""
    received = [] if received is None else received
    lock = threading.Condition(threading.RLock())
    consumer = DevelopmentConsumer(reducer, channel.send)
    try:
        consumer.accept({'type': 'source', 'epoch': channel.epoch, 'protocol': 'macos-es-v1'})
        reducer.prepare_resource(resource, nonce)
    except Exception:
        with evidence_write():
            reducer.gate.local_resource_not_started(resource)
        with evidence_write():
            consumer.lost()
        raise
    def receive():
        try:
            while not consumer.failed:
                record = channel.read()
                with lock:
                    consumer.accept(record)
                    lock.notify_all()
        except Exception:
            pass  # Fixed loss evidence below; no raw wire/argv diagnostic.
        finally:
            with lock:
                consumer.failed = True
                with evidence_write():
                    consumer.lost()
                lock.notify_all()
            channel.shutdown()
    reader = threading.Thread(target=receive, name='native-es-consumer', daemon=True)
    reader.start()
    helper = None
    old = {}
    def forward(signum, frame):
        received.append(signum)
        if helper is not None and helper.poll() is None:
            helper.send_signal(signum)
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            old[signum] = signal.signal(signum, forward)
        config = channel.config
        # Exact executable/requirements were verified before channel establishment.
        with lock:
            if consumer.failed or received:
                with evidence_write():
                    reducer.gate.local_resource_not_started(resource, cancelled=True)
                return 128 + received[-1] if received else 78
            helper = subprocess.Popen([config['helper'], '--managed-session', config['socket'], config['collector_requirement'],
                                       config['helper_requirement'], resource, nonce, config['image'], '--', *command])
        code = helper.wait()
        # Preserve real helper wait even if registration or evidence is incomplete.
        with evidence_write():
            with lock:
                wait_deadline = None
                while not consumer.failed:
                    registration = consumer.registrations.get(resource)
                    if registration is None or not registration.arm_sent:
                        # wait() is a business result, not proof of non-dispatch.
                        # Revoke under the same lock as accept/_progress: a queued
                        # REGISTER can no longer consume or send a permit. Keep the
                        # resource unknown; never invent not_started from this race.
                        consumer.lost()
                        break
                    status = reducer.status(resource)
                    if status['unknown']:
                        break
                    if status['process_closed']:
                        if status['business_waited']:
                            reducer.seal(resource)
                            break
                        # ES EXIT and socket WAIT are separate ordered streams.
                        # Keep consuming the bound WAIT after EXIT, but a dead
                        # helper must not leave an unbounded transport wait.
                        if wait_deadline is None:
                            wait_deadline = time.monotonic() + WAIT_EVIDENCE_SECONDS
                        remaining = wait_deadline - time.monotonic()
                        if remaining <= 0:
                            consumer.lost()
                            break
                        lock.wait(remaining)
                    else:
                        lock.wait()
        return code if code >= 0 else 128 - code
    except OSError:
        if helper is None:
            with evidence_write():
                reducer.gate.local_resource_not_started(resource, exec_failed=True)
            return 127
        raise
    finally:
        # Channel EOF closes unarmed helper permission, never signals accepted business.
        with lock:
            consumer.failed = True
            with evidence_write():
                consumer.lost()
        with evidence_write():
            channel.close()
        reader.join()
        for signum, handler in old.items():
            signal.signal(signum, handler)
