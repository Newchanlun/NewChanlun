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
REVIEW_LAUNCH = re.compile(r"review-(?:preflight-)?[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
REVIEW_SESSION = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
RECEIPT_ROUTES = frozenset({"codex:gpt-6.2-sol@chatgpt.com", "codex:gpt-6.2-astra@chatgpt.com",
                            "kimi@api.kimi.com", "kimi-ai@api.kimi.ai", "claude@api.anthropic.com",
                            "antigravity@daily-cloudcode-pa.googleapis.com", "other"})
REVIEW_RECEIPT_ROUTES = frozenset({"codex:gpt-6.2-sol@chatgpt.com", "codex:gpt-6.2-astra@chatgpt.com"})
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
MAX_REVIEW_DURATION_NS = 7_200_000_000_000
MAX_REVIEW_RECEIPT_BYTES = 65536
MAX_REVIEW_RESPONSE_IDS = 512


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _trusted_fd(fd: int, *, is_dir: bool) -> os.stat_result | None:
    """校验已打开描述符的属主与私有权限（仅当前有效用户可读写，禁止 group/other 任何位），防止非受信账户伪造收据。"""
    info = os.fstat(fd)
    ok_type = stat.S_ISDIR(info.st_mode) if is_dir else stat.S_ISREG(info.st_mode)
    if not ok_type or info.st_uid != os.geteuid() or (info.st_mode & 0o077):
        return None
    return info


def route_from_receipt(root: Path, session: str, since: float, wait: float) -> list[tuple[str, str]] | None:
    """仅消费生产者原子发布的私有收据；正式调用在有截止时间的子进程中执行。"""
    if not SESSION.fullmatch(session):
        return None
    end = time.monotonic() + max(0, wait)
    while True:
        try:
            # 逐层禁止 symlink 并核验已打开 fd 的受信属主与私有权限；不跟随轮转目录或读取 FIFO/设备。
            parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                if _trusted_fd(parent, is_dir=True) is None:
                    return None
                directory = os.open(session, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            finally:
                os.close(parent)
            try:
                if _trusted_fd(directory, is_dir=True) is None:
                    return None
                try:
                    os.stat("seal.pending", dir_fd=directory, follow_symlinks=False)
                    return None
                except FileNotFoundError:
                    pass
                except OSError:
                    return None
                fd = os.open("receipt.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            finally:
                os.close(directory)
            try:
                info = _trusted_fd(fd, is_dir=False)
                if info is None or not 0 < info.st_size <= 16384:
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
    """消费代理为正式独审 launch 封存的不可变 cliproxy-review-v1 收据；缺项、污染或模型不符立即返回 None；
    未封存（sealed!=True）绝不放行，仅在 wait 截止时间内轮询等待封存落盘，超时仍未封存返回 None。"""
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
                if _trusted_fd(parent, is_dir=True) is None:
                    return None
                directory = os.open(launch, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            finally:
                os.close(parent)
            try:
                if _trusted_fd(directory, is_dir=True) is None:
                    return None
                try:
                    os.stat("seal.pending", dir_fd=directory, follow_symlinks=False)
                    return None
                except FileNotFoundError:
                    pass
                except OSError:
                    return None
                fd = os.open("receipt.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            finally:
                os.close(directory)
            try:
                info = _trusted_fd(fd, is_dir=False)
                if info is None or not 0 < info.st_size <= MAX_REVIEW_RECEIPT_BYTES:
                    return None
                raw = os.read(fd, MAX_REVIEW_RECEIPT_BYTES + 1)
            finally:
                os.close(fd)
            payload = json.loads(raw, object_pairs_hook=_unique_object)
            now_ns = time.time_ns()
            if (not isinstance(payload, dict)
                    or set(payload) != {"schema", "launch", "session", "started_ns", "finished_ns", "sealed_at_ns",
                                        "complete", "sealed", "tainted", "requests", "routes",
                                        "response_id_sha256s", "last_response_id_sha256", "last_output_sha256"}
                    or payload["schema"] != REVIEW_SCHEMA or payload["launch"] != launch
                    or payload["session"] != session
                    or payload["complete"] is not True or payload["tainted"] is not False
                    or type(payload["sealed"]) is not bool
                    or type(payload["requests"]) is not int or not 1 <= payload["requests"] <= MAX_REVIEW_RESPONSE_IDS
                    or type(payload["started_ns"]) is not int or type(payload["finished_ns"]) is not int
                    or type(payload["sealed_at_ns"]) is not int
                    or not int((since - 1) * 1e9) <= payload["started_ns"] <= payload["finished_ns"] <= now_ns
                    or payload["finished_ns"] - payload["started_ns"] > MAX_REVIEW_DURATION_NS
                    or not isinstance(payload["routes"], list) or len(payload["routes"]) != 1
                    or not isinstance(payload["routes"][0], str)
                    or payload["routes"][0] not in REVIEW_RECEIPT_ROUTES
                    or not isinstance(payload["response_id_sha256s"], list)
                    or len(payload["response_id_sha256s"]) != payload["requests"]
                    or any(not isinstance(item, str) or not SHA256_HEX.fullmatch(item)
                           for item in payload["response_id_sha256s"])
                    or not isinstance(payload["last_response_id_sha256"], str)
                    or not SHA256_HEX.fullmatch(payload["last_response_id_sha256"])
                    or payload["response_id_sha256s"][-1] != payload["last_response_id_sha256"]
                    or not isinstance(payload["last_output_sha256"], str)
                    or (payload["last_output_sha256"] != "" and not SHA256_HEX.fullmatch(payload["last_output_sha256"]))):
                return None
            if payload["sealed"] is not True:
                if payload["sealed_at_ns"] != 0:
                    return None
                if time.monotonic() >= end:
                    return None
                time.sleep(min(0.02, max(0, end - time.monotonic())))
                continue
            if not payload["finished_ns"] <= payload["sealed_at_ns"] <= now_ns:
                return None
            result = {
                "routes": [tuple(payload["routes"][0].split("@"))],
                "requests": payload["requests"],
                "sealed": True,
                "response_id_sha256s": list(payload["response_id_sha256s"]),
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
            "complete_stable": bool(info is not None and info.get("sealed") is True),
            "sealed": bool(info is not None and info.get("sealed") is True),
            "routes": [known.get(route, "other") for route in (info["routes"] if info else [])],
            "requests": info["requests"] if info else 0,
            "response_id_sha256s": info["response_id_sha256s"] if info else [],
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
