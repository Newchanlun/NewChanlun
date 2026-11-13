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
    """v8.0.63 文本日志没有正文帧或可信完成标记，不能用作路由证明。

    保留旧入口与返回合同，但拒绝据此放行。恢复条件见 REVIEW-PREFLIGHT.md
    的“可信证据缺口”；不能用增加正则或等待文件稳定来替代生产者证据。
    """
    return None


SCHEMA = "cliproxy-preflight-v1"
SESSION = re.compile(r"preflight-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
RECEIPT_ROUTES = frozenset({"kimi@api.kimi.com", "kimi-ai@api.kimi.ai", "claude@api.anthropic.com",
                            "antigravity@daily-cloudcode-pa.googleapis.com", "other"})


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def route_from_receipt(root: Path, session: str, since: float, wait: float) -> list[tuple[str, str]] | None:
    """仅消费生产者原子发布的私有收据；正式调用在有截止时间的子进程中执行。"""
    if not SESSION.fullmatch(session):
        return None
    end = time.monotonic() + max(0, wait)
    while True:
        try:
            # 逐层禁止 symlink；不跟随轮转目录或读取 FIFO/设备。
            parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                directory = os.open(session, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            finally:
                os.close(parent)
            try:
                fd = os.open("receipt.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            finally:
                os.close(directory)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 16384:
                    return None
                raw = os.read(fd, 16385)
            finally:
                os.close(fd)
            payload = json.loads(raw, object_pairs_hook=_unique_object)
            if (not isinstance(payload, dict)
                    or set(payload) != {"schema", "session", "started_ns", "finished_ns", "complete", "routes"}
                    or payload["schema"] != SCHEMA or payload["session"] != session
                    or payload["complete"] is not True
                    or type(payload["started_ns"]) is not int or type(payload["finished_ns"]) is not int
                    or not int((since - 1) * 1e9) <= payload["started_ns"] <= payload["finished_ns"] <= time.time_ns()
                    or payload["finished_ns"] - payload["started_ns"] > 50_000_000_000
                    or not isinstance(payload["routes"], list) or not 1 <= len(payload["routes"]) <= 64
                    or any(not isinstance(route, str) or route not in RECEIPT_ROUTES for route in payload["routes"])):
                return None
            return [tuple(route.split("@")) if route != "other" else ("other", "other") for route in payload["routes"]]
        except FileNotFoundError:
            if time.monotonic() >= end:
                return None
            time.sleep(min(0.02, max(0, end - time.monotonic())))
        except (OSError, ValueError, TypeError):
            return None


def main():
    # 绝对到期时间也约束 daemon 延迟启动的 exec；SIGALRM 覆盖阻塞读取与输出。
    arguments = sys.argv[1:]
    receipt_mode = arguments[:1] == ["--receipt"]
    if receipt_mode:
        arguments = arguments[1:]
    log_dir, session, since, expires, budget, known_json = arguments
    remaining = float(expires) - time.time()
    if not 0 < remaining <= float(budget):
        return 2
    signal.signal(signal.SIGALRM, lambda *_: os._exit(2))
    signal.setitimer(signal.ITIMER_REAL, remaining)
    known = {tuple(route): "@".join(route) for route in json.loads(known_json)}
    reader = route_from_receipt if receipt_mode else route_from_log
    attempts = reader(Path(log_dir), session, float(since), remaining)
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
