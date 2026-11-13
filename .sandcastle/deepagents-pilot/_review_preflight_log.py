"""#1742 私有日志读取器；宿主与容器使用同一解析实现。"""
import json
import os
import re
import signal
import stat
import sys
import time
from pathlib import Path


def route_from_log(log_dir: Path, session: str, since: float, wait: float) -> list[tuple[str, str]] | None:
    """按本次唯一 Session-Id 找 CLIProxy request-log，读出每次上游尝试的 (provider, 主机)。
    proxy 的日志以 `=== RESPONSE ===` 段收尾；只在该段已出现、且相邻两次轮询文件标识、大小与修改时间不变时解析，
    避免把写到一半的 `provider=clau` 当成定论。找不到或一直没写完返回 None。"""
    end = time.monotonic() + wait
    sizes: dict = {}
    while time.monotonic() <= end:
        try:
            paths = list(log_dir.glob("v1-responses-*.log"))
        except OSError:  # 日志目录不可读：按找不到日志处理
            paths = []
        candidates = []
        for path in paths:
            try:  # 其他会话的日志可能在 glob 与 stat 之间被轮转删除
                candidates.append((path.stat().st_mtime, path))
            except OSError:
                continue
        for mtime, path in sorted(candidates, reverse=True):
            if mtime < since - 1:
                break
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode) or before.st_mtime < since - 1:
                        continue
                    raw = stream.read()
                    after = os.fstat(stream.fileno())
                stamp = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                if before != after:
                    continue
            except OSError:
                continue
            text = raw.decode("utf-8", "replace")
            if not re.search(r"^Session-Id: " + re.escape(session) + r"$", text.split("=== API REQUEST", 1)[0], re.M):
                continue
            stable = sizes.get(path) == stamp
            sizes[path] = stamp
            if "\n=== RESPONSE ===" in text and stable:
                # 只读各 API REQUEST 段（到下一个 === 段头为止）：响应正文里伪造的同名行不算路由
                requests = re.findall(r"^=== API REQUEST \d+ ===\n(.*?)(?=^=== )", text, re.M | re.S)
                attempts = []
                for section in requests:
                    provider = re.search(r"^Auth: provider=([\w.-]+)(?=,|\s*$)", section, re.M)
                    host = re.search(r"^Upstream URL: https?://([^/:?\s]+)", section, re.M)
                    if not (provider and host):
                        return []
                    attempts.append((provider.group(1), host.group(1)))
                return attempts
            break
        time.sleep(0.05)
    return None



def main():
    # 绝对到期时间也约束 daemon 延迟启动的 exec；SIGALRM 覆盖阻塞读取与输出。
    log_dir, session, since, expires, budget, known_json = sys.argv[1:]
    remaining = float(expires) - time.time()
    if not 0 < remaining <= float(budget):
        return 2
    signal.signal(signal.SIGALRM, lambda *_: os._exit(2))
    signal.setitimer(signal.ITIMER_REAL, remaining)
    known = {tuple(route): "@".join(route) for route in json.loads(known_json)}
    attempts = route_from_log(Path(log_dir), session, float(since), remaining)
    print(json.dumps({"session": session, "complete_stable": attempts is not None,
                      "routes": [known.get(route, "other") for route in attempts or []]}), flush=True)
    return 0


if __name__ == "__main__":
    # traceback/路径/日志内容不能越过容器边界。
    try:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), 2)
        os._exit(main())
    except BaseException:
        os._exit(2)
