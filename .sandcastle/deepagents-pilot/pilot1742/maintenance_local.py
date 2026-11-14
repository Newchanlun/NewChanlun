"""本机 CLI session 监督：先绑定域，再派发；实际 wait 与域清空分别取证。"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys

if not __package__:
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pilot1742.maintenance_epoch import local_epoch


def resources_idle(rows: list[dict], diagnostics: list[str] | None = None) -> bool:
    def reject(reason: str) -> bool:
        if diagnostics is not None:
            diagnostics.append(reason)
        return False
    if not rows:
        return True
    try:
        from pilot1742.maintenance_processes import stable_snapshot
        epoch = local_epoch()
        if any((r['host'], r['boot']) != epoch for r in rows):
            return reject('epoch_or_binding_missing')
        rows = [r for r in rows if not r.get('not_started')]
        if any(not r['waited_at'] or not r['domain'] for r in rows):
            return reject('wait_or_domain_missing')
        pending = [r for r in rows if not r['domain']['sealed_at']]
        if not pending:
            return True
        snapshot_rows = []
        from pilot1742.maintenance_subreaper import KIND, idle
        for row in pending:
            domain = json.loads(row['domain']['baseline'])
            if domain.get('kind') == 'macos-es-v1':
                return reject('native_es_closure_pending')
            if domain.get('kind') == KIND:
                if (domain.get('pid') != row['pid'] or domain.get('birth') != row['domain']['supervisor']
                        or not idle(domain)):
                    return reject('subreaper_pending_or_wrong_supervisor')
            else:
                snapshot_rows.append(row)
        if not snapshot_rows:
            return True
        current = stable_snapshot()
        for row in snapshot_rows:
            baseline = {int(pid): data for pid, data in json.loads(row['domain']['baseline']).items()}
            # 原祖先可能接收 reparent 后代，不能将其当成“无关分支”。
            ancestors = {0, 1, row['pid']}
            parent = baseline[row['pid']][1]
            while parent in baseline and parent not in ancestors:
                ancestors.add(parent)
                parent = baseline[parent][1]
            outside = {pid for pid, data in current.items()
                       if pid not in ancestors and baseline.get(pid, [None])[0] == data[0]}
            # 只排除可沿当前父链回到预存无关分支的进程；孤儿/setsid 不凭消失放行。
            while True:
                more = {pid for pid, data in current.items() if data[1] in outside}
                if more <= outside:
                    break
                outside.update(more)
            unclassified = [pid for pid, data in current.items()
                            if pid != os.getpid() and pid not in outside and baseline.get(pid, [None])[0] != data[0]]
            if unclassified:
                return reject('unclassified_process_pids=' + ','.join(map(str, sorted(unclassified))))
        return True
    except OSError as error:
        from pilot1742.maintenance_processes import UnstableSnapshot
        return reject(str(error) if isinstance(error, UnstableSnapshot) else f'resource_read errno={error.errno}')
    except (ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return reject('resource_evidence_invalid')


def main() -> int:
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--resource', required=True)
    parser.add_argument('--es-config', type=Path)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        return 78
    if args.es_config is not None:
        from pilot1742.maintenance_es_session import run
        try:
            return run(args, command)
        except (ValueError, OSError, subprocess.SubprocessError):
            print('native ES source unavailable', file=sys.stderr, flush=True)
            return 78
    if sys.platform.startswith('linux'):
        return linux_guardian(args, command)
    return supervise(args, command)


def supervise(args, command: list[str], notify: int | None = None, signal_mask=None) -> int:
    from pilot1742.maintenance import Gate, evidence_write
    received = []
    child = None
    def forward(signum, frame):
        received.append(signum)
        if child is not None and child.poll() is None:
            child.send_signal(signum)
    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    if signal_mask is not None:
        signal.pthread_sigmask(signal.SIG_SETMASK, signal_mask)
    os.setsid()
    gate = Gate(args.root)
    from pilot1742.maintenance_processes import UnstableSnapshot
    try:
        gate.bind_local_resource(args.resource, subreaper=notify is not None)  # 此后才允许启动 CLI，无 check/spawn 领取间隙。
    except UnstableSnapshot as error:
        with evidence_write():
            gate.local_resource_not_started(args.resource)
        print(str(error), file=sys.stderr, flush=True)  # 固定原因码/errno，不输出 argv/环境。
        if notify is not None:
            os.write(notify, b'78\n')
            os.close(notify)
        return 78  # 未派发失败；不能继续执行下面的 Popen。
    if received:
        # 已绑定但尚未调用 Popen；信号取消这次派发，不启动再杀业务。
        with evidence_write():
            gate.local_resource_not_started(args.resource, cancelled=True)
        result = 128 + received[-1]
        if notify is not None:
            os.write(notify, f'{result}\n'.encode())
            os.close(notify)
        return result
    # 不持有账本锁等待进程；stdout/stderr/stdin 原样透传，不读取凭据或记录命令。
    try:
        child = subprocess.Popen(command)
    except OSError:
        # Popen 的 exec-error 通道已同步回收未 exec 的子进程；不伪造业务 wait。
        with evidence_write():
            gate.local_resource_not_started(args.resource, exec_failed=True)
        if notify is not None:
            os.write(notify, b'127\n')
            os.close(notify)
        return 127
    if received:
        child.send_signal(received[-1])
    code = child.wait()
    # 业务 wait 已完成；控制账本失败不能改写业务码或放弃内核后代监督。
    waited = False
    try:
        gate.local_resource_waited(args.resource, child.pid, code)
        waited = True
        gate.seal_local_resource(args.resource)
    except Exception:
        print("local resource evidence write failed", file=sys.stderr, flush=True)
    result = code if code >= 0 else 128 - code
    if notify is not None:
        # 返回真实 wait 码与账本提交解耦；即使调用方失联也继续监督后代。
        try:
            os.write(notify, f'{result}\n'.encode())
        except OSError:
            pass
        finally:
            os.close(notify)
        devnull = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(devnull, fd)
        if devnull > 2:
            os.close(devnull)
        from pilot1742.maintenance_subreaper import wait_remaining
        wait_remaining()
        if waited:
            try:
                gate.seal_local_resource(args.resource)
            except Exception:
                pass  # 不补签失败的 wait；封闭提交失败仍由账本保持 unknown。
    return result


def linux_guardian(args, command: list[str]) -> int:
    """外层保留原退出合同；独立 guardian 自然 wait 到最后一个后代结束。"""
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
    reader, writer = os.pipe()
    guardian = None
    def forward(signum, frame):
        if guardian is not None and guardian > 0:
            try:
                os.kill(guardian, signum)
            except ProcessLookupError:
                pass
    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    guardian = os.fork()
    if guardian == 0:
        os.close(reader)
        try:
            supervise(args, command, writer, mask)
        except Exception:
            print("local guardian failed before completion", file=sys.stderr, flush=True)
        finally:
            os._exit(0)
    os.close(writer)
    signal.pthread_sigmask(signal.SIG_SETMASK, mask)
    with os.fdopen(reader) as pipe:
        value = pipe.readline().strip()
    # Guardian 在可信 wait 前崩溃没有回执；action-exited 仍会保持 unknown。
    return int(value) if value.isdecimal() and 0 <= int(value) <= 255 else 78


if __name__ == '__main__':
    raise SystemExit(main())
