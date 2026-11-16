"""#1986：删审阅卷之后把 Colima VM 里释放的块还给宿主。

VM 的数据盘是 macOS 系统盘上的稀疏文件；VM 里删卷只是把块标记为空闲，不跑 fstrim 宿主就收不回来，
系统盘只减不增（2026-11-09 实测一次 fstrim 回收 5.8 GiB）。

做法：`colima --profile <p> ssh -- sudo -n fstrim -v /var/lib/docker`。没有用「--privileged 一次性容器挂
/var/lib/docker 去 trim」：本仓的容器合同不许特权容器、不许挂宿主或 VM 的 Docker 数据目录，审阅镜像也不保证带
fstrim；colima ssh 走的是宿主用户本来就有的 VM 登录，不经 Docker daemon，也不起任何容器。

只用标准库，可单独运行（TS 监督以 `python3 -I vm_trim.py <checkout_root>` 调用），也可被 external_review 导入。
失败（不是 Colima、colima 不在、sudo 要密码、超时）只返回记录，不抛错，调用方不据此改结论。
节流：checkout_root 下一把非阻塞 flock，拿不到就跳过（另一个 trim 正在跑）；拿到后看时间戳文件，
距上次尝试不足 TRIM_INTERVAL_SECONDS 就跳过。时间戳在尝试前写，失败也计入间隔，免得每轮都去撞一个坏掉的 VM。
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

TRIM_INTERVAL_SECONDS = 600
TRIM_TIMEOUT_SECONDS = 60
CONTEXT_TIMEOUT_SECONDS = 10
LOCK_NAME = ".vm-trim.lock"
STAMP_NAME = ".vm-trim.stamp"
# 宿主 Docker 定位合同：显式 context 贯穿准入、监督、回收与 trim；未指定时仍由 Docker 选默认。
# 不传 DOCKER_HOST、DOCKER_CONFIG 或任意凭据；这不是审阅容器的环境白名单。
DOCKER_ENV = ("PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "DOCKER_CONTEXT")
TRIM_TARGET = "/var/lib/docker"

Runner = Callable[[List[str], float], subprocess.CompletedProcess]


def run_command(argv: List[str], timeout: float) -> subprocess.CompletedProcess:
    """在自己的进程组里跑命令；超时杀整组（colima 会再起 ssh 子进程，只杀直接子进程时管道不关、会一直等）。
    超时返回码 124，命令不存在 127。stdout/stderr 原样返回，由调用方决定记什么。"""
    env = {k: os.environ[k] for k in DOCKER_ENV if k in os.environ}
    try:
        proc = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError:
        return subprocess.CompletedProcess(argv, 127, "", "")
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        return subprocess.CompletedProcess(argv, 124, "", "")
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def colima_profile(context: str) -> Optional[str]:
    """docker context 名映射到 Colima profile：colima → default，colima-<p> → <p>；别的 context 不是 Colima。"""
    if context == "colima":
        return "default"
    match = re.fullmatch(r"colima-([A-Za-z0-9][A-Za-z0-9._-]*)", context)
    return match[1] if match else None


def trim_vm_disk(root: Path, *, run: Runner = run_command, now: Callable[[], float] = time.time,
                 interval: float = TRIM_INTERVAL_SECONDS, timeout: float = TRIM_TIMEOUT_SECONDS) -> Dict[str, object]:
    """对当前 docker context 背后的 Colima VM 跑一次 fstrim。返回一条可直接落日志的记录，从不抛错。
    state：trimmed / failed / skipped（不是 Colima 或 root 不存在）/ busy（另一个 trim 正在跑）/ throttled。
    只记返回码与 fstrim 的一行回收量，不记 stderr（ssh 的报错可能带 VM 登录密钥的路径）。"""
    root = Path(root)
    if not root.is_dir():
        return {"state": "skipped", "reason": "no_root"}
    try:
        fd = os.open(root / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return {"state": "failed", "reason": "lock_unavailable"}
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"state": "busy"}
        stamp = root / STAMP_NAME
        started = now()
        try:
            since = started - stamp.stat().st_mtime
        except FileNotFoundError:
            since = None
        # 时钟回拨（since<0）不算节流，照常 trim。
        if since is not None and 0 <= since < interval:
            return {"state": "throttled", "seconds_since_last": int(since)}
        stamp.touch(mode=0o600)
        os.utime(stamp, (started, started))
        context = run(["docker", "context", "show"], CONTEXT_TIMEOUT_SECONDS)
        if context.returncode:
            return {"state": "failed", "reason": "docker_context", "returncode": context.returncode}
        profile = colima_profile(context.stdout.strip())
        if profile is None:
            return {"state": "skipped", "reason": "not_colima"}
        done = run(["colima", "--profile", profile, "ssh", "--", "sudo", "-n", "fstrim", "-v", TRIM_TARGET], timeout)
        if done.returncode:
            return {"state": "failed", "reason": "timeout" if done.returncode == 124 else "fstrim",
                    "returncode": done.returncode, "profile": profile}
        return {"state": "trimmed", "profile": profile, "output": done.stdout.strip()[-200:],
                "seconds": round(now() - started, 1)}
    except OSError:
        return {"state": "failed", "reason": "stamp_unavailable"}
    finally:
        os.close(fd)


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("用法：vm_trim.py <checkout_root>\n")
        return 2
    sys.stdout.write(json.dumps(trim_vm_disk(Path(argv[1])), ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
