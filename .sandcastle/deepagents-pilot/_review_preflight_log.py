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
REVIEW_SCHEMA = "cliproxy-review-v1"
SESSION = re.compile(r"preflight-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
REVIEW_LAUNCH = re.compile(r"review-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
REVIEW_SESSION = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
RECEIPT_ROUTES = frozenset({"codex:gpt-6.2-sol@chatgpt.com", "codex:gpt-6.2-astra@chatgpt.com",
                            "kimi@api.kimi.com", "kimi-ai@api.kimi.ai", "claude@api.anthropic.com",
                            "antigravity@daily-cloudcode-pa.googleapis.com", "other"})
REVIEW_RECEIPT_ROUTES = frozenset({"codex:gpt-6.2-sol@chatgpt.com", "codex:gpt-6.2-astra@chatgpt.com"})
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
MAX_REVIEW_DURATION_NS = 7_200_000_000_000


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


def review_from_receipt(
    root: Path, launch: str, session: str, since: float, wait: float, *,
    expected_response_id_sha256: str = "", expected_output_sha256: str = "", min_requests: int = 1,
) -> dict | None:
    """消费代理为正式独审 launch 原子发布的 cliproxy-review-v1 收据；缺项、污染或模型不符立即返回 None；
    多轮收据在最终轮尚未异步落盘时在 wait 截止时间内轮询等待期望的最终响应摘要与轮数。"""
    if not REVIEW_LAUNCH.fullmatch(launch) or not REVIEW_SESSION.fullmatch(session):
        return None
    if expected_response_id_sha256 and not SHA256_HEX.fullmatch(expected_response_id_sha256):
        return None
    if expected_output_sha256 and not SHA256_HEX.fullmatch(expected_output_sha256):
        return None
    end = time.monotonic() + max(0, wait)
    while True:
        try:
            parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                directory = os.open(launch, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
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
                    or set(payload) != {"schema", "launch", "session", "started_ns", "finished_ns",
                                        "complete", "tainted", "requests", "routes",
                                        "last_response_id_sha256", "last_output_sha256"}
                    or payload["schema"] != REVIEW_SCHEMA or payload["launch"] != launch
                    or payload["session"] != session
                    or payload["complete"] is not True or payload["tainted"] is not False
                    or type(payload["requests"]) is not int or payload["requests"] < 1
                    or type(payload["started_ns"]) is not int or type(payload["finished_ns"]) is not int
                    or not int((since - 1) * 1e9) <= payload["started_ns"] <= payload["finished_ns"] <= time.time_ns()
                    or payload["finished_ns"] - payload["started_ns"] > MAX_REVIEW_DURATION_NS
                    or not isinstance(payload["routes"], list) or len(payload["routes"]) != 1
                    or not isinstance(payload["routes"][0], str)
                    or payload["routes"][0] not in REVIEW_RECEIPT_ROUTES
                    or not isinstance(payload["last_response_id_sha256"], str)
                    or not SHA256_HEX.fullmatch(payload["last_response_id_sha256"])
                    or not isinstance(payload["last_output_sha256"], str)
                    or (payload["last_output_sha256"] != "" and not SHA256_HEX.fullmatch(payload["last_output_sha256"]))):
                return None
            result = {
                "routes": [tuple(payload["routes"][0].split("@"))],
                "requests": payload["requests"],
                "last_response_id_sha256": payload["last_response_id_sha256"],
                "last_output_sha256": payload["last_output_sha256"],
            }
            matched = (
                payload["requests"] >= max(1, min_requests)
                and (not expected_response_id_sha256 or payload["last_response_id_sha256"] == expected_response_id_sha256)
                and (not expected_output_sha256 or payload["last_output_sha256"] == expected_output_sha256)
            )
            if matched or time.monotonic() >= end:
                return result
            time.sleep(min(0.02, max(0, end - time.monotonic())))
        except FileNotFoundError:
            if time.monotonic() >= end:
                return None
            time.sleep(min(0.02, max(0, end - time.monotonic())))
        except (OSError, ValueError, TypeError):
            return None


def main():
    # 绝对到期时间也约束 daemon 延迟启动的 exec；SIGALRM 覆盖阻塞读取与输出。
    arguments = sys.argv[1:]
    if arguments[:1] == ["--review-receipt"]:
        rest = arguments[1:]
        if len(rest) == 7:
            log_dir, launch, session, since, expires, budget, known_json = rest
            expected_rid, expected_out, min_reqs = "", "", 1
        elif len(rest) == 10:
            log_dir, launch, session, since, expires, budget, known_json, expected_rid, expected_out, raw_min = rest
            min_reqs = int(raw_min)
        else:
            return 2
        remaining = float(expires) - time.time()
        if not 0 < remaining <= float(budget):
            return 2
        signal.signal(signal.SIGALRM, lambda *_: os._exit(2))
        signal.setitimer(signal.ITIMER_REAL, remaining)
        known = {tuple(route): "@".join(route) for route in json.loads(known_json)}
        info = review_from_receipt(
            Path(log_dir), launch, session, float(since), remaining,
            expected_response_id_sha256=expected_rid, expected_output_sha256=expected_out, min_requests=min_reqs,
        )
        print(json.dumps({
            "launch": launch,
            "session": session,
            "complete_stable": info is not None,
            "routes": [known.get(route, "other") for route in (info["routes"] if info else [])],
            "requests": info["requests"] if info else 0,
            "last_response_id_sha256": info["last_response_id_sha256"] if info else "",
            "last_output_sha256": info["last_output_sha256"] if info else "",
        }), flush=True)
        return 0
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
