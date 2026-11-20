"""Linux B13 fixture: trace exec environments in an isolated process group."""

import ctypes
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# -xx represents every string byte as hex; unexpanded and truncated arrays
# cannot match this grammar. Never include the raw trace in diagnostics.
STRING = r'"(?:\\x[0-9a-f]{2})*"'
ARRAY = rf'\[(?:{STRING}(?:, {STRING})*)?\]'
EXEC = re.compile(
    rf'execve(?:at\([^,]+, |\()({STRING}), ({ARRAY}), ({ARRAY})'
    r'(?:, [A-Z0-9_|]+)?\)\s+= (0|-1 [A-Z0-9_]+ \(.*\))'
)
FORK = re.compile(r'(?:clone3?|fork|vfork)\(.*\)\s+= ([1-9][0-9]*)$')
PR_SET_CHILD_SUBREAPER = 36


class CaptureError(Exception):
    pass


def decode(word):
    return bytes.fromhex(word[1:-1].replace(r"\x", ""))


def events(log):
    prefix = "production_session "
    return [
        json.loads(line[len(prefix):])
        for line in log.read_text().splitlines()
        if line.startswith(prefix)
    ]


def records(root, directory, launcher_events):
    files = {int(p.suffix[1:]): p for p in directory.glob("exec.[0-9]*")}
    if root not in files:
        raise CaptureError("缺 launcher 的 exec 文件")
    edges, threads = {}, {}
    executions = {}
    for pid, path in files.items():
        lines = path.read_text(encoding="ascii").splitlines()
        if not lines or not lines[-1].startswith("+++ "):
            raise CaptureError(f"PID {pid} 的跟踪文件为空或未完成")
        edges[pid], threads[pid], executions[pid] = set(), set(), []
        for line in lines:
            if fork := FORK.fullmatch(line):
                child = int(fork[1])
                edges[pid].add(child)
                if "CLONE_THREAD" in line:
                    threads[pid].add(child)
            if line.startswith(("execve(", "execveat(", "<... execve")):
                call = EXEC.fullmatch(line)
                if call is None:
                    raise CaptureError(f"PID {pid} 的 exec 记录不完整或无法解析")
                if call[4] == "0":
                    args = [decode(s) for s in re.findall(STRING, call[2])]
                    entries = [decode(s) for s in re.findall(STRING, call[3])]
                    if any(b"=" not in entry for entry in entries):
                        raise CaptureError(f"PID {pid} 的环境项缺键值边界")
                    keys = {entry.split(b"=", 1)[0] for entry in entries}
                    executions[pid].append((decode(call[1]), args, keys))
    pending, reached = [root], set()
    while pending:
        pid = pending.pop()
        if pid not in files:
            raise CaptureError(f"创建了 PID {pid}，但无跟踪文件")
        if pid not in reached:
            reached.add(pid)
            pending.extend(edges[pid])
    if reached != files.keys() or not executions[root]:
        raise CaptureError("无法从 launcher 的首个 exec 还原完整进程树")
    announced = [e for e in launcher_events if e["event"] in {"init", "spawn"}]
    starts = {e["pid"] for e in announced if e["event"] == "spawn"}
    launcher_children = set()
    pending = [root]
    while pending:
        pid = pending.pop()
        launcher_children.update(edges[pid] - threads[pid])
        pending.extend(threads[pid])
    direct_execs = {pid for pid in launcher_children if executions[pid]}
    if len(direct_execs) < len(announced) or not starts <= direct_execs:
        raise CaptureError("直接子进程 exec 记录少于 launcher 的启动记录")
    # Every direct process creation by this launcher is a Command launch.
    if direct_execs != launcher_children:
        raise CaptureError("launcher 创建的子进程缺完整 exec 记录")
    return executions


def kill(pid, sig):
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass


def stop(tracer, root_fd):
    # Let the owner reap normally while strace is still attached. If init
    # stalls, kill the whole private group, then reap any adopted orphans.
    if root_fd is not None:
        try:
            signal.pidfd_send_signal(root_fd, signal.SIGTERM)
        except ProcessLookupError:
            pass
    elif tracer.poll() is None:
        kill(-tracer.pid, signal.SIGTERM)
    deadline = time.monotonic() + 1.5
    try:
        tracer.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        kill(-tracer.pid, signal.SIGKILL)
        tracer.wait(timeout=max(0, deadline - time.monotonic()))
    killed_group = False
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            if not killed_group:
                kill(-tracer.pid, signal.SIGKILL)
                killed_group = True
            if time.monotonic() >= deadline:
                raise CaptureError("跟踪进程组未在清理时限内回收")
            time.sleep(0.01)


def collect(tool, launcher, manifest):
    directory = manifest.parent
    log = directory / "launcher.log"
    root = root_fd = None
    if ctypes.CDLL(None, use_errno=True).prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0):
        raise CaptureError("无法启用 Linux 孤儿进程回收")
    with log.open("w") as stderr:
        tracer = subprocess.Popen(
            [tool, "-ff", "-v", "-xx", "-s", "131072", "-o", str(directory / "exec"),
             "-e", "trace=execve,execveat,clone,clone3,fork,vfork",
             "--", str(launcher), "--manifest", str(manifest)],
            # Keep the trace confined to synthetic credentials.
            env={"PATH": os.environ.get("PATH", "")},
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stderr,
            start_new_session=True,
        )
        try:
            children = Path(f"/proc/{tracer.pid}/task/{tracer.pid}/children")
            deadline = time.monotonic() + 30
            while True:
                if tracer.poll() is not None:
                    raise CaptureError("strace 或 launcher 在域就绪前退出；检查 ptrace 权限")
                if root is None:
                    pids = children.read_text().split()
                    if pids:
                        root = int(pids[0])
                        root_fd = os.pidfd_open(root)
                try:
                    x_started = any(
                        e.get("event") == "spawn" and e.get("domain") == "X"
                        for e in events(log)
                    )
                except json.JSONDecodeError:
                    x_started = False  # launcher may still be writing its last line
                # X opens its durable DB before announcing it can serve.
                ready = "x_execution_session serving" in log.read_text() and all(
                    (directory / name).is_socket() for name in ("s.sock", "e.sock", "b.sock")
                )
                if root is not None and x_started and ready:
                    break
                if time.monotonic() >= deadline:
                    raise CaptureError("30 秒内域未就绪")
                time.sleep(0.02)
        finally:
            try:
                stop(tracer, root_fd)
            finally:
                if root_fd is not None:
                    os.close(root_fd)
    if tracer.returncode:
        raise CaptureError(f"strace 或 launcher 退出码 {tracer.returncode}")
    return root, records(root, directory, events(log))


def main():
    launcher, x_bin, manifest = map(Path, sys.argv[1:4])
    key = os.fsencode(sys.argv[4])
    tool = shutil.which("strace")
    if tool is None:
        raise CaptureError("PATH 中缺 strace")
    root, executions = collect(tool, launcher, manifest)
    if executions[root][0][0] != os.fsencode(launcher):
        raise CaptureError("首条 exec 不是受测 launcher")
    found_x = False
    for pid, calls in executions.items():
        for path, argv, keys in calls:
            if path == os.fsencode(x_bin):
                found_x = True
                if key not in keys:
                    raise AssertionError("B13 X 的 exec 未收到完整凭据键")
            elif key in keys:
                verb = argv[1] if len(argv) > 1 and argv[1] in (b"init", b"serve") else b""
                raise AssertionError(
                    f"B13 凭据键进入非 X: PID {pid} {os.fsdecode(os.path.basename(path))} "
                    f"{verb.decode()}"
                )
    if not found_x:
        raise CaptureError("未采到 X 的 exec")


try:
    main()
except (CaptureError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
    sys.exit(f"B13 取样失败：{error}")
except AssertionError as error:
    sys.exit(str(error))
