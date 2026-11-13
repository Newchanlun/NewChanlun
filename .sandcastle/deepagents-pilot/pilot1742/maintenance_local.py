"""本机 CLI session 监督：先绑定域，再派发；实际 wait 与域清空分别取证。"""
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
        current = stable_snapshot()
        for row in pending:
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

    from pilot1742.maintenance import Gate
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--resource', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        return 78
    os.setsid()
    gate = Gate(args.root)
    from pilot1742.maintenance_processes import UnstableSnapshot
    try:
        gate.bind_local_resource(args.resource)  # 此后才允许启动 CLI，无 check/spawn 领取间隙。
    except UnstableSnapshot as error:
        gate.local_resource_not_started(args.resource)
        print(str(error), file=sys.stderr)  # 固定原因码/errno，不输出 argv/环境。
        return 78  # 未派发失败；不能继续执行下面的 Popen。
    received = []
    child = None
    def forward(signum, frame):
        received.append(signum)
        if child is not None and child.poll() is None:
            child.send_signal(signum)
    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    # 不持有账本锁等待进程；stdout/stderr/stdin 原样透传，不读取凭据或记录命令。
    child = subprocess.Popen(command)
    if received:
        child.send_signal(received[-1])
    code = child.wait()
    gate.local_resource_waited(args.resource, child.pid, code)
    gate.seal_local_resource(args.resource)
    return code if code >= 0 else 128 - code


if __name__ == '__main__':
    raise SystemExit(main())
